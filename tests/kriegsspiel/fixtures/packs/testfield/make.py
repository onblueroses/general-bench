"""Generate the synthetic 4 km x 3 km Kriegsspiel test field.

Run: uv run python tests/kriegsspiel/fixtures/packs/testfield/make.py
(writes terrain.npz, features.json, oob.json, deployment.json beside this file).
Deterministic; no randomness.

Layout: a ridge (Hoher Ruecken) across the north third with a summit (Kapellenberg); the wood
Eichwald on its western slope; the village Neudorf on the road in the south-centre; the stream
Muehlbach running north-south near the east edge, crossed once by the road at the
Muehlbach bridge. Blue (4 brigades) deploys in the south, Red (4 brigades) on the ridge.
"""

from __future__ import annotations

import itertools
import json
import math
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
W, H, CELL = 4000.0, 3000.0, 50.0
OPEN, ROUGH, WOOD, VILLAGE, ORCHARD, MARSH, WATER, ROAD = range(8)

RIDGE = [(300.0, 2050.0), (1000.0, 2120.0), (2000.0, 2150.0), (2800.0, 2100.0), (3250.0, 2000.0)]
STREAM = [
    (3300.0, 3000.0),
    (3350.0, 2300.0),
    (3420.0, 1600.0),
    (3450.0, 1050.0),
    (3500.0, 500.0),
    (3550.0, 0.0),
]
ROAD_PTS = [(0.0, 900.0), (1200.0, 950.0), (2400.0, 1000.0), (3450.0, 1050.0), (4000.0, 1150.0)]
KIRCHWEG = [(2400.0, 1000.0), (2200.0, 1600.0), (2000.0, 2150.0), (2000.0, 3000.0)]
NEUDORF = [(2250.0, 880.0), (2560.0, 880.0), (2580.0, 1130.0), (2240.0, 1140.0)]
EICHWALD = [(600.0, 2150.0), (1200.0, 2120.0), (1250.0, 2550.0), (650.0, 2600.0)]
ORCHARD_POLY = [(2560.0, 900.0), (2760.0, 900.0), (2760.0, 1100.0), (2580.0, 1120.0)]
MARSH_POLY = [(3380.0, 200.0), (3650.0, 200.0), (3680.0, 450.0), (3400.0, 480.0)]
BRIDGE = (3450.0, 1050.0)


def grid():
    nx, ny = int(W / CELL), int(H / CELL)
    xs = (np.arange(nx) + 0.5) * CELL
    ys = (np.arange(ny) + 0.5) * CELL
    return np.meshgrid(xs, ys)  # X[i, j], Y[i, j]; row 0 = south


def in_poly(X, Y, ring):
    inside = np.zeros(X.shape, dtype=bool)
    n = len(ring)
    for k in range(n):
        x1, y1 = ring[k]
        x2, y2 = ring[(k + 1) % n]
        cond = (y1 > Y) != (y2 > Y)
        with np.errstate(divide="ignore", invalid="ignore"):
            xint = (x2 - x1) * (Y - y1) / (y2 - y1) + x1
        inside ^= cond & (xint > X)
    return inside


def raster_line(mask, pts):
    ny, nx = mask.shape
    for (x1, y1), (x2, y2) in itertools.pairwise(pts):
        n = int(math.hypot(x2 - x1, y2 - y1) / (CELL / 4)) + 1
        for t in np.linspace(0.0, 1.0, n):
            j = min(nx - 1, max(0, int((x1 + (x2 - x1) * t) // CELL)))
            i = min(ny - 1, max(0, int((y1 + (y2 - y1) * t) // CELL)))
            mask[i, j] = True


def ridge_y(x):
    xs = [p[0] for p in RIDGE]
    ys = [p[1] for p in RIDGE]
    return np.interp(x, xs, ys)


def terrain():
    X, Y = grid()
    elev = 200.0 + 0.004 * Y  # gentle rise to the north
    ends = np.clip((X - 0.0) / 600.0, 0, 1) * np.clip((3700.0 - X) / 600.0, 0, 1)
    elev += 35.0 * ends * np.exp(-(((Y - ridge_y(X)) / 280.0) ** 2))
    elev += 10.0 * np.exp(-(((X - 2000.0) ** 2 + (Y - 2150.0) ** 2) / (300.0**2)))
    # stream valley
    sx = np.interp(Y, [p[1] for p in reversed(STREAM)], [p[0] for p in reversed(STREAM)])
    elev -= 6.0 * np.exp(-(((X - sx) / 120.0) ** 2))
    cover = np.full(X.shape, OPEN, dtype=np.uint8)
    cover[in_poly(X, Y, EICHWALD)] = WOOD
    cover[in_poly(X, Y, ORCHARD_POLY)] = ORCHARD
    cover[in_poly(X, Y, NEUDORF)] = VILLAGE
    cover[in_poly(X, Y, MARSH_POLY)] = MARSH
    farm = (X - 1200.0) ** 2 + (Y - 1300.0) ** 2 < 150.0**2
    cover[farm & (cover == OPEN)] = ROUGH
    water = np.zeros(X.shape, dtype=bool)
    raster_line(water, STREAM)
    cover[water] = WATER
    road = np.zeros(X.shape, dtype=bool)
    raster_line(road, ROAD_PTS)
    raster_line(road, KIRCHWEG)
    cover[road] = ROAD  # the road crosses the stream only at the bridge
    return elev.astype(np.float32), cover


def features():
    f = [
        ("Hoher Ruecken", "ridge", "polyline", RIDGE, ["the ridge", "Hoher Rücken"]),
        ("Kapellenberg", "height", "point", [(2000.0, 2150.0)], ["the chapel hill"]),
        ("Eichwald", "wood", "polygon", EICHWALD, ["the oak wood"]),
        ("Neudorf", "village", "polygon", NEUDORF, []),
        ("Neudorf church", "church", "point", [(2400.0, 1050.0)], []),
        ("Muehlbach", "stream", "polyline", STREAM, ["Mühlbach", "the stream"]),
        ("Muehlbach bridge", "bridge", "point", [BRIDGE], ["the bridge"]),
        ("Landstrasse", "road", "polyline", ROAD_PTS, ["the high road"]),
        ("Kirchweg", "road", "polyline", KIRCHWEG, []),
        ("Hof Lindenau", "farm", "point", [(1200.0, 1300.0)], ["the farm"]),
        ("Muehle", "mill", "point", [(3480.0, 1700.0)], ["the mill", "Mühle"]),
    ]
    return [
        {
            "name": n,
            "kind": k,
            "geometry": {"type": g, "coords": [list(p) for p in c]},
            "aliases": a,
        }
        for n, k, g, c, a in f
    ]


def side_oob(side, tag, south):
    """Army root, two infantry brigades, one cavalry, one artillery brigade."""
    army = f"{tag}-army"
    fs = [
        {
            "id": army,
            "name": f"{side.title()} Army",
            "side": side,
            "commander": "General Blau" if south else "General Roth",
            "parent": None,
            "level": "army",
            "aliases": ["the army"],
        }
    ]
    us = []
    inf_kind = ["line", "grenadier"] if south else ["fusilier", "grenzer"]
    for b in (1, 2):
        bid = f"{tag}-inf{b}"
        fs.append(
            {
                "id": bid,
                "name": f"{side.title()} {b}. Brigade",
                "side": side,
                "commander": f"{'Oberst' if b == 1 else 'Major'} {tag}{b}",
                "parent": army,
                "level": "brigade",
                "aliases": [f"{b}. Brigade"],
            }
        )
        us.extend(
            {
                "id": f"{bid}-{k}",
                "name": f"{tag} IR {b}/{k}",
                "side": side,
                "parent": bid,
                "kind": inf_kind[b - 1],
                "men": 600,
                "quality": 3 if b == 1 else 4,
            }
            for k in range(1, 5)
        )
    cid = f"{tag}-cav"
    fs.append(
        {
            "id": cid,
            "name": f"{side.title()} Cavalry",
            "side": side,
            "commander": f"Rittmeister {tag}",
            "parent": army,
            "level": "brigade",
            "aliases": ["the cavalry"],
        }
    )
    for k, kind in enumerate(["cuirassier", "cuirassier", "hussar"], 1):
        us.append(
            {
                "id": f"{cid}-{k}",
                "name": f"{tag} CR {k}",
                "side": side,
                "parent": cid,
                "kind": kind,
                "men": 450 if kind == "cuirassier" else 400,
                "quality": 4 if kind == "cuirassier" else 3,
            }
        )
    aid = f"{tag}-art"
    fs.append(
        {
            "id": aid,
            "name": f"{side.title()} Artillery",
            "side": side,
            "commander": f"Hauptmann {tag}",
            "parent": army,
            "level": "brigade",
            "aliases": ["the guns"],
        }
    )
    for k, (guns, cal) in enumerate([(8, 6), (8, 6), (6, 12)], 1):
        us.append(
            {
                "id": f"{aid}-{k}",
                "name": f"{tag} Bty {k}",
                "side": side,
                "parent": aid,
                "kind": "foot_battery",
                "guns": guns,
                "crew": guns * 10,
                "calibre_lb": cal,
                "quality": 3,
            }
        )
    return fs, us


def deployment(units):
    dep = {}
    hq = {}
    for side, y0, facing, tag in (("blue", 450.0, 0.0, "B"), ("red", 2050.0, 180.0, "R")):
        sign = 1.0 if side == "blue" else -1.0
        xs = {
            "inf1": 1300.0,
            "inf2": 2100.0,
            "cav": 2900.0 if side == "blue" else 600.0,
            "art": 1700.0,
        }
        for u in units:
            if u["side"] != side:
                continue
            brig = u["parent"].split("-")[1]
            k = int(u["id"].rsplit("-", 1)[1])
            if brig.startswith("inf"):
                x = xs[brig] + (k - 2.5) * 220.0
                y = y0
                state = "column" if side == "blue" else "line"
            elif brig == "cav":
                x = xs[brig] + (k - 2) * 200.0
                y = y0 - sign * 250.0
                state = "column"
            else:
                x = xs[brig] + (k - 2) * 300.0
                y = y0 - sign * 150.0 if side == "blue" else ridge_y(xs[brig] + (k - 2) * 300.0)
                state = "limbered" if side == "blue" else "unlimbered"
            if side == "red" and brig.startswith("inf"):
                y = float(ridge_y(x)) - 80.0
            dep[u["id"]] = {
                "x": round(float(x), 1),
                "y": round(float(y), 1),
                "facing_deg": facing,
                "state": state,
            }
        hq[f"{tag}-army"] = [2000.0, 150.0] if side == "blue" else [2000.0, 2300.0]
    return {"start": "13:00", "units": dep, "hq": hq}


def build():
    elev, cover = terrain()
    fb, ub = side_oob("blue", "B", True)
    fr, ur = side_oob("red", "R", False)
    units = ub + ur
    return {
        "terrain": {
            "elev": elev,
            "cover": cover,
            "cell_m": np.float64(CELL),
            "origin": np.array([0.0, 0.0]),
        },
        "features": features(),
        "oob": {"sides": ["blue", "red"], "formations": fb + fr, "units": units},
        "deployment": deployment(units),
    }


def write(out: Path = HERE) -> None:
    b = build()
    np.savez_compressed(out / "terrain.npz", **b["terrain"])
    for name in ("features", "oob", "deployment"):
        (out / f"{name}.json").write_text(json.dumps(b[name], indent=1, ensure_ascii=False) + "\n")


if __name__ == "__main__":
    write()
