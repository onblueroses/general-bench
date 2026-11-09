"""Build the Kolín pack's terrain.npz and the OSM-derived part of features from raw sources.

Usage (from the repo root, after tools/fetch_sources.sh CACHE; KOLIN is
tests/kriegsspiel/fixtures/packs/kolin):

    uv run --with tifffile --with imagecodecs python -I $KOLIN/tools/build_terrain.py CACHE

Inputs in CACHE: cop_N49_00_E015_00.tif, cop_N50_00_E015_00.tif (Copernicus GLO-30 DSM),
osm.json (Overpass, see fetch_sources.sh). Outputs: terrain.npz,
tools/osm_extract.json (the OSM geometry kept, in local metres) and a preview PNG
in CACHE. tifffile/imagecodecs are build-time only; the engine reads the .npz with numpy.

Projection: UTM zone 33N on WGS84 (central meridian 15 E, the battlefield straddles it).
Local x = easting - ORIGIN_E, y = northing - ORIGIN_N; origin is the grid's south-west corner.
"""

from __future__ import annotations

import itertools
import json
import math
import sys
import zlib
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
DATA = HERE.parent

CELL = 25.0
ORIGIN_E = 501_000.0  # UTM 33N easting of the south-west corner
ORIGIN_N = 5_538_100.0  # UTM 33N northing of the south-west corner
NX, NY = 576, 328  # 14.4 km x 8.2 km

# Cover codes (kriegsspiel.types.Cover)
OPEN, ROUGH, WOOD, VILLAGE, ORCHARD, MARSH, WATER, ROAD = range(8)

# --------------------------------------------------------------------------- UTM (Snyder 1987)
A = 6378137.0
F = 1 / 298.257223563
E2 = F * (2 - F)
EP2 = E2 / (1 - E2)
K0 = 0.9996
LON0 = math.radians(15.0)


def _m(phi):
    e4, e6 = E2 * E2, E2**3
    return A * (
        (1 - E2 / 4 - 3 * e4 / 64 - 5 * e6 / 256) * phi
        - (3 * E2 / 8 + 3 * e4 / 32 + 45 * e6 / 1024) * np.sin(2 * phi)
        + (15 * e4 / 256 + 45 * e6 / 1024) * np.sin(4 * phi)
        - (35 * e6 / 3072) * np.sin(6 * phi)
    )


def ll_to_utm(lat, lon):
    phi, lam = np.radians(lat), np.radians(lon)
    n = A / np.sqrt(1 - E2 * np.sin(phi) ** 2)
    t = np.tan(phi) ** 2
    c = EP2 * np.cos(phi) ** 2
    a = np.cos(phi) * (lam - LON0)
    x = (
        K0
        * n
        * (a + (1 - t + c) * a**3 / 6 + (5 - 18 * t + t * t + 72 * c - 58 * EP2) * a**5 / 120)
    )
    y = K0 * (
        _m(phi)
        + n
        * np.tan(phi)
        * (
            a * a / 2
            + (5 - t + 9 * c + 4 * c * c) * a**4 / 24
            + (61 - 58 * t + t * t + 600 * c - 330 * EP2) * a**6 / 720
        )
    )
    return x + 500_000.0, y


def utm_to_ll(e, nn):
    x = np.asarray(e) - 500_000.0
    m = np.asarray(nn) / K0
    mu = m / (A * (1 - E2 / 4 - 3 * E2**2 / 64 - 5 * E2**3 / 256))
    e1 = (1 - math.sqrt(1 - E2)) / (1 + math.sqrt(1 - E2))
    phi1 = (
        mu
        + (3 * e1 / 2 - 27 * e1**3 / 32) * np.sin(2 * mu)
        + (21 * e1**2 / 16 - 55 * e1**4 / 32) * np.sin(4 * mu)
        + (151 * e1**3 / 96) * np.sin(6 * mu)
        + (1097 * e1**4 / 512) * np.sin(8 * mu)
    )
    n1 = A / np.sqrt(1 - E2 * np.sin(phi1) ** 2)
    t1 = np.tan(phi1) ** 2
    c1 = EP2 * np.cos(phi1) ** 2
    r1 = A * (1 - E2) / (1 - E2 * np.sin(phi1) ** 2) ** 1.5
    d = x / (n1 * K0)
    lat = phi1 - (n1 * np.tan(phi1) / r1) * (
        d * d / 2
        - (5 + 3 * t1 + 10 * c1 - 4 * c1 * c1 - 9 * EP2) * d**4 / 24
        + (61 + 90 * t1 + 298 * c1 + 45 * t1 * t1 - 252 * EP2 - 3 * c1 * c1) * d**6 / 720
    )
    lon = LON0 + (
        d
        - (1 + 2 * t1 + c1) * d**3 / 6
        + (5 - 2 * c1 + 28 * t1 - 3 * c1 * c1 + 8 * EP2 + 24 * t1 * t1) * d**5 / 120
    ) / np.cos(phi1)
    return np.degrees(lat), np.degrees(lon)


def to_local(lat, lon):
    e, n = ll_to_utm(np.asarray(lat, float), np.asarray(lon, float))
    return e - ORIGIN_E, n - ORIGIN_N


# --------------------------------------------------------------------------- DEM
def load_dem(cache: Path):
    import tifffile

    tiles = []
    for name in ("cop_N49_00_E015_00.tif", "cop_N50_00_E015_00.tif"):
        with tifffile.TiffFile(cache / name) as t:
            p = t.pages[0]
            arr = p.asarray().astype(np.float64)
            sx, sy, _ = p.tags["ModelPixelScaleTag"].value
            _, _, _, lon0, lat0, _ = p.tags["ModelTiepointTag"].value
            tiles.append((arr, lon0, lat0, sx, sy))
    return tiles


def sample_dem(tiles, lat, lon):
    out = np.full(lat.shape, np.nan)
    for arr, lon0, lat0, sx, sy in tiles:
        # pixel-is-area: centre of pixel (r, c) at lon0 + (c + .5) sx, lat0 - (r + .5) sy
        c = (lon - lon0) / sx - 0.5
        r = (lat0 - lat) / sy - 0.5
        # half a pixel of tolerance bridges the seam between the N49 and N50 tiles
        ok = (r >= -0.5) & (r <= arr.shape[0] - 0.5) & (c >= -0.5) & (c <= arr.shape[1] - 0.5)
        r0 = np.clip(np.floor(r).astype(int), 0, arr.shape[0] - 2)
        c0 = np.clip(np.floor(c).astype(int), 0, arr.shape[1] - 2)
        fr, fc = np.clip(r - r0, 0, 1), np.clip(c - c0, 0, 1)
        v = (
            arr[r0, c0] * (1 - fr) * (1 - fc)
            + arr[r0 + 1, c0] * fr * (1 - fc)
            + arr[r0, c0 + 1] * (1 - fr) * fc
            + arr[r0 + 1, c0 + 1] * fr * fc
        )
        out = np.where(ok & np.isnan(out), v, out)
    assert not np.isnan(out).any(), "DEM does not cover the grid"
    return out


# --------------------------------------------------------------------------- raster helpers
JJ, II = np.meshgrid(np.arange(NX), np.arange(NY))
CX = (JJ + 0.5) * CELL
CY = (II + 0.5) * CELL


def poly_mask(xy):
    """Even-odd point-in-polygon for every cell centre."""
    xs, ys = np.asarray([p[0] for p in xy]), np.asarray([p[1] for p in xy])
    mask = np.zeros((NY, NX), bool)
    j = len(xs) - 1
    for i in range(len(xs)):
        xi, yi, xj, yj = xs[i], ys[i], xs[j], ys[j]
        if yi != yj:
            cond = ((yi > CY) != (yj > CY)) & ((xj - xi) * (CY - yi) / (yj - yi) + xi > CX)
            mask ^= cond
        j = i
    return mask


def line_mask(xy, half_width):
    mask = np.zeros((NY, NX), bool)
    for (x0, y0), (x1, y1) in itertools.pairwise(xy):
        dx, dy = x1 - x0, y1 - y0
        L2 = dx * dx + dy * dy or 1e-9
        t = np.clip(((CX - x0) * dx + (CY - y0) * dy) / L2, 0, 1)
        d2 = (CX - x0 - t * dx) ** 2 + (CY - y0 - t * dy) ** 2
        mask |= d2 <= half_width**2
    return mask


def disc_mask(x, y, r):
    return (CX - x) ** 2 + (CY - y) ** 2 <= r * r


def polygon_area(xy):
    s = 0.0
    for (x0, y0), (x1, y1) in zip(xy, xy[1:] + xy[:1], strict=True):
        s += x0 * y1 - x1 * y0
    return abs(s) / 2


def inpaint(elev: np.ndarray, hole: np.ndarray, iters: int = 4000) -> np.ndarray:
    z = elev.astype(np.float64).copy()
    known = ~hole
    # start from the mean of known neighbours to speed convergence
    z[hole] = float(z[known].mean())
    for _ in range(iters):
        p = np.pad(z, 1, mode="edge")
        avg = (p[:-2, 1:-1] + p[2:, 1:-1] + p[1:-1, :-2] + p[1:-1, 2:]) / 4
        z[hole] = avg[hole]
    return z.astype(np.float32)


def heights_polygon(elev: np.ndarray, level: float = 295.0):
    """Convex hull of the largest connected area above `level` m inside the battle window."""
    win = (CX > 3500) & (CX < 10500) & (CY > 800) & (CY < 4200)
    m = (elev >= level) & win
    lab = np.zeros(m.shape, int)
    best, best_n, cur = 0, 0, 0
    for i0, j0 in zip(*np.nonzero(m), strict=True):
        if lab[i0, j0]:
            continue
        cur += 1
        stack, n = [(i0, j0)], 0
        lab[i0, j0] = cur
        while stack:
            i, j = stack.pop()
            n += 1
            for di, dj in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                a, b = i + di, j + dj
                if 0 <= a < NY and 0 <= b < NX and m[a, b] and not lab[a, b]:
                    lab[a, b] = cur
                    stack.append((a, b))
        if n > best_n:
            best, best_n = cur, n
    pts = sorted(
        {(float(CX[i, j]), float(CY[i, j])) for i, j in zip(*np.nonzero(lab == best), strict=True)}
    )

    def cross(o, a, b):
        return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])

    lower, upper = [], []
    for p in pts:
        while len(lower) >= 2 and cross(lower[-2], lower[-1], p) <= 0:
            lower.pop()
        lower.append(p)
    for p in reversed(pts):
        while len(upper) >= 2 and cross(upper[-2], upper[-1], p) <= 0:
            upper.pop()
        upper.append(p)
    return lower[:-1] + upper[:-1]


def crest_line(elev: np.ndarray):
    """West-to-east crest: per 250 m strip, the highest point between y 2000 and 3800 m."""
    out = []
    for x in range(4500, 9751, 250):
        j = int(x // CELL)
        i0, i1 = int(2000 // CELL), int(3800 // CELL)
        col = elev[i0:i1, j]
        i = i0 + int(np.argmax(col))
        out.append((float(x), float((i + 0.5) * CELL)))
    # 3-point running mean on y to remove single-cell jitter
    ys = [p[1] for p in out]
    sm = [ys[0]] + [(ys[k - 1] + ys[k] + ys[k + 1]) / 3 for k in range(1, len(ys) - 1)] + [ys[-1]]
    return [(p[0], round(y, 1)) for p, y in zip(out, sm, strict=True)]


# --------------------------------------------------------------------------- OSM
def osm_geoms(cache: Path):
    d = json.loads((cache / "osm.json").read_text())
    ways, nodes = [], []
    for e in d["elements"]:
        t = e.get("tags", {})
        if e["type"] == "node":
            x, y = to_local(e["lat"], e["lon"])
            nodes.append({"id": e["id"], "tags": t, "xy": (float(x), float(y))})
        elif e["type"] == "way" and "geometry" in e:
            g = e["geometry"]
            x, y = to_local([p["lat"] for p in g], [p["lon"] for p in g])
            ways.append(
                {
                    "id": e["id"],
                    "tags": t,
                    "xy": list(zip(map(float, x), map(float, y), strict=True)),
                }
            )
        elif e["type"] == "relation":
            for m in e.get("members", []):
                if m.get("role") == "outer" and "geometry" in m:
                    g = m["geometry"]
                    x, y = to_local([p["lat"] for p in g], [p["lon"] for p in g])
                    ways.append(
                        {
                            "id": e["id"],
                            "tags": t,
                            "xy": list(zip(map(float, x), map(float, y), strict=True)),
                        }
                    )
    return ways, nodes


def inside_grid(xy, margin=0.0):
    return any(
        -margin <= x <= NX * CELL + margin and -margin <= y <= NY * CELL + margin for x, y in xy
    )


def write_png(path: Path, rgb: np.ndarray) -> None:
    h, w, _ = rgb.shape
    raw = b"".join(b"\x00" + rgb[h - 1 - i].astype(np.uint8).tobytes() for i in range(h))

    def chunk(k, v):
        c = k + v
        return len(v).to_bytes(4, "big") + c + zlib.crc32(c).to_bytes(4, "big")

    png = b"\x89PNG\r\n\x1a\n" + chunk(
        b"IHDR", w.to_bytes(4, "big") + h.to_bytes(4, "big") + b"\x08\x02\x00\x00\x00"
    )
    png += chunk(b"IDAT", zlib.compress(raw, 9)) + chunk(b"IEND", b"")
    path.write_bytes(png)


def main(cache: Path) -> None:
    hand = json.loads((HERE / "hand_features.json").read_text())

    # ---- elevation
    tiles = load_dem(cache)
    lat, lon = utm_to_ll(ORIGIN_E + CX, ORIGIN_N + CY)
    elev = sample_dem(tiles, lat, lon).astype(np.float32)

    ways, nodes = osm_geoms(cache)
    cover = np.full((NY, NX), OPEN, np.uint8)
    kept: dict[str, list] = {
        "streams": [],
        "ponds": [],
        "wetlands": [],
        "woods": [],
        "lanes": [],
        "kaiserstrasse": [],
        "elbe": [],
        "churches": [],
        "peaks": [],
    }

    # streams carve small dells (ROUGH), per kronoskaf's description of the brooks
    for w in ways:
        t = w["tags"]
        if t.get("waterway") == "stream" and inside_grid(w["xy"]):
            if "svodnice" in (t.get("name") or ""):  # modern drainage ditches
                continue
            cover[line_mask(w["xy"], 15.0)] = ROUGH
            kept["streams"].append({"name": t.get("name"), "osm": w["id"], "xy": w["xy"]})
    # wetlands
    for w in ways:
        t = w["tags"]
        if t.get("natural") == "wetland" and inside_grid(w["xy"]) and len(w["xy"]) > 3:
            cover[poly_mask(w["xy"])] = MARSH
            kept["wetlands"].append({"osm": w["id"], "xy": w["xy"]})
    # hand-placed marsh along the lower Peklo brook (kronoskaf: "oozed through lakes and swamps")
    _, ry = to_local(*hand["peklo_marsh_from_latlon"])
    for w in ways:
        t = w["tags"]
        if t.get("waterway") == "stream" and t.get("name") in ("Pekelský potok", "Peklo"):
            m = line_mask(w["xy"], 37.5) & (float(ry) < CY)
            cover[m] = MARSH
    # woods: only the hand-placed 1757 woods; modern OSM woods are listed but not rasterised
    canopy = np.zeros((NY, NX), bool)
    for w in ways:
        t = w["tags"]
        if (t.get("natural") == "wood" or t.get("landuse") == "forest") and inside_grid(w["xy"]):
            kept["woods"].append({"osm": w["id"], "area_ha": round(polygon_area(w["xy"]) / 1e4, 1)})
            if len(w["xy"]) > 3:
                canopy |= poly_mask(w["xy"])
    # The DEM is a surface model: modern woods stand 15-25 m above the ground. Fill the ground
    # under them from the surrounding open cells (Laplace inpainting on a dilated mask).
    hole = canopy.copy()
    hole[1:, :] |= canopy[:-1, :]
    hole[:-1, :] |= canopy[1:, :]
    hole[:, 1:] |= canopy[:, :-1]
    hole[:, :-1] |= canopy[:, 1:]
    raw_elev = elev.copy()
    elev = inpaint(elev, hole)
    for wd in hand["woods"]:
        cover[poly_mask([tuple(q) for q in wd["xy"]])] = WOOD
    # villages: discs around the historical cores (20-30 houses each, kronoskaf)
    for v in hand["villages"]:
        x, y = to_local(*v["latlon"])
        cover[disc_mask(float(x), float(y), v["radius_m"])] = VILLAGE
    # ponds (natural water, not reservoirs/basins) and the Elbe
    for w in ways:
        t = w["tags"]
        if t.get("natural") == "water" and inside_grid(w["xy"]) and len(w["xy"]) > 3:
            if t.get("water") in ("reservoir", "basin", "wastewater", "canal", "lock"):
                continue
            if t.get("landuse") in ("reservoir", "basin"):
                continue
            if t.get("water") == "lake" and not t.get("name"):  # gravel pits by the Elbe
                continue
            cover[poly_mask(w["xy"])] = WATER
            kept["ponds"].append(
                {"name": t.get("name"), "water": t.get("water"), "osm": w["id"], "xy": w["xy"]}
            )
    for w in ways:
        t = w["tags"]
        if t.get("waterway") == "river" and t.get("name") == "Labe" and inside_grid(w["xy"]):
            cover[line_mask(w["xy"], 40.0)] = WATER
            kept["elbe"].append({"osm": w["id"], "xy": w["xy"]})
    # village lanes: tertiary/unclassified roads away from modern Kolín
    kx, ky = to_local(50.0281, 15.2014)
    for w in ways:
        t = w["tags"]
        if t.get("highway") in ("tertiary", "unclassified") and inside_grid(w["xy"]):
            if min(math.hypot(x - kx, y - ky) for x, y in w["xy"]) < 1500:
                continue
            m = line_mask(w["xy"], 12.5) & (cover != WATER)
            cover[m] = ROAD
            kept["lanes"].append({"osm": w["id"], "xy": w["xy"]})
    # the Kaiserstrasse: modern road 12 follows the old highway; joined to Kolín's market square
    segs = [
        w for w in ways if w["tags"].get("ref") == "12" and w["tags"].get("highway") == "primary"
    ]
    pts = sorted({p for w in segs for p in w["xy"]}, key=lambda p: p[0])
    # keep a monotone west-to-east chain (the road runs east-west); thin to ~50 m spacing
    chain = [pts[0]]
    for p in pts[1:]:
        if math.hypot(p[0] - chain[-1][0], p[1] - chain[-1][1]) >= 50:
            chain.append(p)
    chain.append((float(kx), float(ky)))
    kept["kaiserstrasse"] = chain
    cover[line_mask(chain, 12.5) & (cover != WATER)] = ROAD
    for nd in nodes:
        t = nd["tags"]
        if t.get("natural") == "peak":
            kept["peaks"].append({"name": t.get("name"), "ele": t.get("ele"), "xy": nd["xy"]})
    for w in ways:
        t = w["tags"]
        if t.get("amenity") == "place_of_worship" and inside_grid(w["xy"]):
            cx = sum(p[0] for p in w["xy"]) / len(w["xy"])
            cy = sum(p[1] for p in w["xy"]) / len(w["xy"])
            kept["churches"].append({"name": t.get("name"), "osm": w["id"], "xy": (cx, cy)})

    kept["heights"] = heights_polygon(elev)
    kept["crest"] = crest_line(elev)
    kept["canopy_cells"] = int(hole.sum())
    kept["canopy_mean_drop_m"] = float((raw_elev - elev)[hole].mean()) if hole.any() else 0.0
    np.savez_compressed(
        DATA / "terrain.npz",
        elev=elev,
        cover=cover,
        cell_m=np.float64(CELL),
        origin=np.array([0.0, 0.0]),
        origin_utm33n=np.array([ORIGIN_E, ORIGIN_N]),
    )
    (HERE / "osm_extract.json").write_text(json.dumps(kept, indent=0, ensure_ascii=False))

    # preview: hillshade tinted by cover
    gy, gx = np.gradient(elev.astype(float), CELL)
    shade = np.clip(0.75 + 3.0 * (-gx * 0.6 + gy * 0.8) / np.sqrt(1 + gx * gx + gy * gy), 0, 1)
    lo, hi = np.percentile(elev, [1, 99])
    base = np.clip((elev - lo) / (hi - lo), 0, 1)
    pal = np.array(
        [
            [235, 225, 190],
            [190, 170, 120],
            [40, 120, 50],
            [200, 40, 40],
            [150, 190, 90],
            [120, 160, 170],
            [40, 80, 200],
            [30, 30, 30],
        ],
        float,
    )
    rgb = pal[cover] * (0.55 + 0.45 * base[..., None]) * shade[..., None]
    write_png(cache / "kolin_preview.png", np.clip(rgb, 0, 255))
    print(
        "elev",
        float(elev.min()),
        float(elev.max()),
        "cover counts",
        np.bincount(cover.ravel(), minlength=8),
    )


if __name__ == "__main__":
    main(Path(sys.argv[1]))
