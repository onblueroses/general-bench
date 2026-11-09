"""The battlefield: raster terrain, named features, routes and line of sight."""

from __future__ import annotations

import heapq
import itertools
import json
import math
from pathlib import Path
from typing import Any

import numpy as np

from . import geometry as geo
from .movement import BASE_SPEED, COVER_MULT, MIN_UPHILL_FACTOR, profile_arm, profile_for
from .types import Cover, Feature, FeatureKind, GeometryKind, Terrain, Unit, UnitState

# ---------------------------------------------------------------------------
# Constants
COARSE_M = 100.0  # spec: A* on a coarse 100 m grid
LOS_BLOCK_DEPTH_M = 50.0  # spec: woods and villages block beyond 50 m inside them
LOS_TARGET_HEIGHT_M = 2.0  # assumption: a formed body stands ~2 m tall (men, colours)
LOS_MAX_SAMPLES = 160  # assumption: ray samples per pair cap (~16 m spacing at 2.5 km)
POINT_FEATURE_RADIUS_M = 150.0  # assumption: "at the mill" means within 150 m of it
LINE_FEATURE_RADIUS_M = 100.0  # assumption: "on the road / at the stream" within 100 m
BRIDGE_RADIUS_M = 40.0  # assumption: a bridge makes water passable within 40 m of its point
# Fords (docs/pack-format.md): water passable for some arms, slowly. A ford may name its
# arms and speed; the defaults are foot and horse at half speed, the radius the bridge's
# (assumption).
FORD_RADIUS_M = 40.0
FORD_SPEED = 0.5
FORD_ARMS = ("infantry", "cavalry")
ARM_CLASS_OF = {"infantry": "inf", "cavalry": "cav", "artillery": "art", "train": "train"}
BLOCKING_COVER = (int(Cover.WOOD), int(Cover.VILLAGE))
# Profiles that also route on the fine road graph: wheels that may not leave road and open
# ground; `path_cost` takes the faster of the 100 m route and the road route.
ROAD_GRAPH_PROFILES = ("train",)
ROAD_ENTRY_TRIES = 40  # nearest road cells tried for the straight leg onto the road
ROUTE_TIE_MIN = 1e-9  # routes within this many minutes of each other are equally fast
_FEATURE_KEYS = ("name", "kind", "geometry", "aliases")  # the rest of a feature is its props


class World:
    """Implements types.WorldLike."""

    def __init__(self, terrain: Terrain, features: list[Feature]):
        self.terrain = terrain
        self.features = sorted(features, key=lambda f: f.name)
        names: dict[str, Feature] = {}
        for f in self.features:
            for n in f.names:
                key = n.casefold()
                if key in names and names[key] is not f:
                    raise ValueError(f"duplicate feature name or alias: {n}")
                names[key] = f
        self._by_name = names
        self.cell = float(terrain.cell_m)
        self.ox, self.oy = (float(terrain.origin[0]), float(terrain.origin[1]))
        self.ny, self.nx = terrain.elev_m.shape
        self._elev = terrain.elev_m.astype(np.float32)
        self._cover = terrain.cover.astype(np.uint8)
        self._slope = terrain.slope
        self._nf_cache: dict[int, Feature] = {}  # raster cell -> nearest feature
        self._road_cell_cache: dict[str, tuple] = {}
        self._field_cache: dict[tuple, np.ndarray] = {}
        self._node_xy: tuple[np.ndarray, np.ndarray] | None = None
        self._bridged = self._bridge_mask()
        self._ford = self._ford_masks()  # arm class -> speed factor per cell (0: no ford)
        self._speed_cache: dict[str, np.ndarray] = {}
        self._coarse_cache: dict[str, np.ndarray] = {}
        self._route_cache: dict[tuple, tuple[float, list[geo.Point]]] = {}
        k = max(1, round(COARSE_M / self.cell))
        self.k = k
        self.coarse_m = cm = k * self.cell
        # The centre of the field. Every lookup that maps a position to a cell, and the
        # coarse routing lattice, are anchored here, so that a field symmetric under the 180°
        # rotation about its centre is routed symmetrically: a node sits on the centre and
        # the lattice runs out from it.
        self.cx = self.ox + self.nx * self.cell / 2.0
        self.cy = self.oy + self.ny * self.cell / 2.0
        hx = max(0, math.ceil((self.nx * self.cell / 2.0 - cm / 2.0) / cm - 1e-9))
        hy = max(0, math.ceil((self.ny * self.cell / 2.0 - cm / 2.0) / cm - 1e-9))
        self.cnx, self.cny = 2 * hx + 1, 2 * hy + 1
        self.cox = self.cx - (hx + 0.5) * cm  # the coarse lattice's south-west corner
        self.coy = self.cy - (hy + 0.5) * cm

    # ------------------------------------------------------------------ io
    @classmethod
    def load(cls, directory: str | Path) -> World:
        """Load terrain.npz + features.json (format in docs/pack-format.md)."""
        d = Path(directory)
        z = np.load(d / "terrain.npz")
        origin = tuple(float(v) for v in z["origin"]) if "origin" in z else (0.0, 0.0)
        terrain = Terrain(
            cell_m=float(z["cell_m"]),
            elev_m=z["elev"].astype(np.float32),
            cover=z["cover"].astype(np.uint8),
            origin=origin,
        )  # type: ignore[arg-type]
        feats = [feature_from_json(f) for f in json.loads((d / "features.json").read_text())]
        return cls(terrain, feats)

    @property
    def centre(self) -> geo.Point:
        """The centre of the field, about which the position lattice and the 180° rotation
        of a symmetric field are taken."""
        return (self.cx, self.cy)

    # -------------------------------------------------------------- raster
    def cell_ij(self, x: float, y: float) -> tuple[int, int]:
        return (
            _sym_index(y, self.oy, self.cell, self.ny, self.cy),
            _sym_index(x, self.ox, self.cell, self.nx, self.cx),
        )

    def cell_ij_many(self, xs: np.ndarray, ys: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        return (
            _sym_index_many(ys, self.oy, self.cell, self.ny, self.cy),
            _sym_index_many(xs, self.ox, self.cell, self.nx, self.cx),
        )

    def in_bounds(self, x: float, y: float) -> bool:
        return (
            self.ox <= x < self.ox + self.nx * self.cell
            and self.oy <= y < self.oy + self.ny * self.cell
        )

    def edge_distance(self, x: float, y: float) -> float:
        """Metres from (x, y) to the nearest edge of the map (0 outside it)."""
        return max(
            0.0,
            min(
                x - self.ox,
                self.ox + self.nx * self.cell - x,
                y - self.oy,
                self.oy + self.ny * self.cell - y,
            ),
        )

    def exits(self) -> list[Feature]:
        return [f for f in self.features if f.kind == FeatureKind.EXIT]

    def elev(self, x: float, y: float) -> float:
        i, j = self.cell_ij(x, y)
        return float(self._elev[i, j])

    def cover(self, x: float, y: float) -> Cover:
        i, j = self.cell_ij(x, y)
        return Cover(int(self._cover[i, j]))

    def slope(self, x: float, y: float) -> float:
        i, j = self.cell_ij(x, y)
        return float(self._slope[i, j])

    def bridged(self, x: float, y: float) -> bool:
        i, j = self.cell_ij(x, y)
        return bool(self._bridged[i, j])

    def passable(self, x: float, y: float, arm: str = "inf") -> bool:
        if not self.in_bounds(x, y):
            return False
        i, j = self.cell_ij(x, y)
        c = int(self._cover[i, j])
        if c == Cover.WATER:
            return bool(self._bridged[i, j]) or (arm in self._ford and self._ford[arm][i, j] > 0)
        return COVER_MULT.get(arm, COVER_MULT["inf"])[c] > 0.0

    def ford_factor(self, x: float, y: float, arm: str) -> float:
        """Speed factor of a ford cell for an arm class; 0 where there is no ford it may use."""
        if arm not in self._ford:
            return 0.0
        i, j = self.cell_ij(x, y)
        return float(self._ford[arm][i, j])

    def _bridge_mask(self) -> np.ndarray:
        mask = self._cover == Cover.ROAD
        yy, xx = np.mgrid[0 : self.ny, 0 : self.nx]
        cx = self.ox + (xx + 0.5) * self.cell
        cy = self.oy + (yy + 0.5) * self.cell
        for f in self.features:
            if f.kind == FeatureKind.BRIDGE:
                for p in f.coords:
                    r = max(float(f.props.get("radius_m", BRIDGE_RADIUS_M)), self.cell * 0.75)
                    mask |= (cx - p[0]) ** 2 + (cy - p[1]) ** 2 <= r * r
        return mask

    def _ford_masks(self) -> dict[str, np.ndarray]:
        """Per arm class, the speed factor on each water cell of a ford that arm may use (the
        fastest ford where two overlap). Aides and generals cross where cavalry can."""
        out: dict[str, np.ndarray] = {}
        fords = [f for f in self.features if f.kind == FeatureKind.FORD]
        if not fords:
            return out
        yy, xx = np.mgrid[0 : self.ny, 0 : self.nx]
        cx = self.ox + (xx + 0.5) * self.cell
        cy = self.oy + (yy + 0.5) * self.cell
        water = self._cover == Cover.WATER
        for f in fords:
            r = max(float(f.props.get("radius_m", FORD_RADIUS_M)), self.cell * 0.75)
            if f.geometry_kind == GeometryKind.POLYLINE and len(f.coords) > 1:
                near = np.zeros_like(water)
                for a, b in itertools.pairwise(f.coords):
                    ax, ay, bx, by = a[0], a[1], b[0], b[1]
                    vx, vy = bx - ax, by - ay
                    t = np.clip(
                        ((cx - ax) * vx + (cy - ay) * vy) / max(vx * vx + vy * vy, 1e-9), 0.0, 1.0
                    )
                    near |= (cx - ax - t * vx) ** 2 + (cy - ay - t * vy) ** 2 <= r * r
            else:
                near = np.zeros_like(water)
                for p in f.coords:
                    near |= (cx - p[0]) ** 2 + (cy - p[1]) ** 2 <= r * r
            # `speed`: one factor for every arm, or {arm: factor} (an arm missing from the
            # map crosses at FORD_SPEED): "foot and horse wade, wheels at half speed"
            sp = f.props.get("speed", FORD_SPEED)
            speeds = (
                {ARM_CLASS_OF[k]: float(v) for k, v in sp.items()} if isinstance(sp, dict) else {}
            )
            arms = [ARM_CLASS_OF[a] for a in f.props.get("passable", FORD_ARMS)]
            if "cav" in arms:
                arms.append("courier")
                speeds.setdefault("courier", speeds.get("cav", FORD_SPEED))
            for a in arms:
                speed = speeds.get(a, FORD_SPEED) if isinstance(sp, dict) else float(sp)
                cur = out.setdefault(a, np.zeros(water.shape, dtype=np.float64))
                np.maximum(cur, np.where(near & water, speed, 0.0), out=cur)
        return out

    # ------------------------------------------------------------ features
    def feature(self, name: str) -> Feature:
        try:
            return self._by_name[name.casefold()]
        except KeyError as e:
            raise KeyError(f"no feature named {name!r}") from e

    def has_feature(self, name: str) -> bool:
        return name.casefold() in self._by_name

    def feature_distance(self, x: float, y: float, f: Feature) -> float:
        return geo.feature_dist((x, y), f)

    def nearest_feature(self, x: float, y: float, kind: FeatureKind | None = None) -> Feature:
        cands = [f for f in self.features if kind is None or f.kind == kind]
        if not cands:
            raise LookupError(f"no feature of kind {kind}")
        return min(cands, key=lambda f: (self.feature_distance(x, y, f), f.name))

    def nearest_feature_cell(self, x: float, y: float) -> Feature:
        """Nearest feature to the centre of the raster cell holding (x, y) (cached)."""
        i, j = self.cell_ij(x, y)
        cache = self._nf_cache
        k = i * self.nx + j
        f = cache.get(k)
        if f is None:
            f = self.nearest_feature(
                self.ox + (j + 0.5) * self.cell, self.oy + (i + 0.5) * self.cell
            )
            cache[k] = f
        return f

    def node_of(self, p: geo.Point) -> geo.Point:
        nx_, ny_ = self._nodes()
        c = self.coarse_ij(p)
        return float(nx_[c]), float(ny_[c])

    def inside(self, x: float, y: float, feature: Feature | str) -> bool:
        f = self.feature(feature) if isinstance(feature, str) else feature
        if f.geometry_kind == GeometryKind.POLYGON:
            return geo.point_in_polygon((x, y), f.coords)
        if f.geometry_kind == GeometryKind.POLYLINE:
            return geo.polyline_dist((x, y), f.coords) <= LINE_FEATURE_RADIUS_M
        return geo.dist((x, y), f.coords[0]) <= POINT_FEATURE_RADIUS_M

    def anchor(self, f: Feature, near: geo.Point | None = None) -> geo.Point:
        """The point a body heads for when told to go to a feature."""
        if f.geometry_kind == GeometryKind.POINT:
            return f.coords[0]
        if f.geometry_kind == GeometryKind.POLYLINE:
            if near is None:
                return f.coords[len(f.coords) // 2]
            return geo.nearest_on_polyline(near, f.coords)
        return geo.centroid(f.coords)

    # -------------------------------------------------------------- routes
    def speed_raster(self, profile: str) -> np.ndarray:
        """Metres per minute on each fine cell for a profile, 0 where impassable."""
        if profile not in self._speed_cache:
            road, cross = BASE_SPEED[profile]
            mult = COVER_MULT[profile_arm(profile)]
            lut = np.array([mult[c] for c in range(len(Cover))], dtype=np.float64)
            v = lut[self._cover] * cross
            v = np.where(self._cover == Cover.ROAD, road, v)
            v = np.where((self._cover == Cover.WATER) & self._bridged, cross, v)
            ford = self._ford.get(profile_arm(profile))
            if ford is not None:  # a ford it may use: cross-country speed times the factor
                v = np.where(
                    (self._cover == Cover.WATER) & ~self._bridged & (ford > 0), cross * ford, v
                )
            self._speed_cache[profile] = v
        return self._speed_cache[profile]

    def _nodes(self) -> tuple[np.ndarray, np.ndarray]:
        """One waypoint per coarse cell: a bridge point if the cell holds one, else the road
        cell nearest the cell's middle, else the middle (of the part of the cell on the map).
        Routes run node to node. Ties between road cells go by distance to the field's
        centre, then by the side of the line from the middle to the centre they lie on, both
        unchanged by the 180° rotation; a tie these leave (two cells mirror images through the
        middle) keeps the middle. No tie is broken by raster order."""
        if self._node_xy is not None:
            return self._node_xy
        cm = self.coarse_m
        x_hi, y_hi = self.ox + self.nx * self.cell, self.oy + self.ny * self.cell
        lo_x = np.maximum(self.cox + np.arange(self.cnx) * cm, self.ox)
        hi_x = np.minimum(self.cox + (np.arange(self.cnx) + 1) * cm, x_hi)
        lo_y = np.maximum(self.coy + np.arange(self.cny) * cm, self.oy)
        hi_y = np.minimum(self.coy + (np.arange(self.cny) + 1) * cm, y_hi)
        nx_, ny_ = np.meshgrid((lo_x + hi_x) / 2.0, (lo_y + hi_y) / 2.0)
        ri, rj = np.nonzero(self._cover == Cover.ROAD)
        if len(ri):
            rx = self.ox + (rj + 0.5) * self.cell
            ry = self.oy + (ri + 0.5) * self.cell
            ci = _sym_index_many(ry, self.coy, cm, self.cny, self.cy)
            cj = _sym_index_many(rx, self.cox, cm, self.cnx, self.cx)
            px, py = nx_[ci, cj], ny_[ci, cj]
            d = np.hypot(rx - px, ry - py)
            dc = np.hypot(rx - self.cx, ry - self.cy)
            side = (rx - px) * (self.cy - py) - (ry - py) * (self.cx - px)
            order = np.lexsort((side, dc, d, cj, ci))
            k = 0
            while k < len(order):
                o = order[k]
                key = (int(ci[o]), int(cj[o]))
                m = k + 1
                while m < len(order) and (int(ci[order[m]]), int(cj[order[m]])) == key:
                    m += 1
                o2 = order[k + 1] if m > k + 1 else None
                if o2 is None or (d[o2], dc[o2], side[o2]) != (d[o], dc[o], side[o]):
                    nx_[key], ny_[key] = rx[o], ry[o]
                k = m
        for f in self.features:
            if f.kind == FeatureKind.BRIDGE:
                for p in f.coords:
                    c = self.coarse_ij(p)
                    nx_[c], ny_[c] = p
            elif f.kind == FeatureKind.FORD:  # a route node on the ford, as on a bridge
                p = f.coords[len(f.coords) // 2]
                c = self.coarse_ij(p)
                nx_[c], ny_[c] = p
        self._node_xy = (nx_, ny_)
        return self._node_xy

    _DIRS = ((-1, -1), (-1, 0), (-1, 1), (0, -1), (0, 1), (1, -1), (1, 0), (1, 1))
    _EDGE_SAMPLES = 12

    def segment_minutes(self, profile: str, ax, ay, bx, by) -> np.ndarray:
        """Fresh-body minutes along straight segments (vectorised); inf if impassable."""
        v = self.speed_raster(profile)
        t = (np.arange(self._EDGE_SAMPLES) + 0.5) / self._EDGE_SAMPLES
        xs = ax[..., None] + (bx - ax)[..., None] * t
        ys = ay[..., None] + (by - ay)[..., None] * t
        inb = (
            (xs >= self.ox)
            & (xs < self.ox + self.nx * self.cell)
            & (ys >= self.oy)
            & (ys < self.oy + self.ny * self.cell)
        )
        i, j = self.cell_ij_many(xs, ys)
        sp = np.where(inb, v[i, j], 0.0)
        length = np.hypot(bx - ax, by - ay)
        with np.errstate(divide="ignore"):
            tpm = np.where(sp > 0, 1.0 / np.where(sp > 0, sp, 1.0), np.inf).mean(axis=-1)
        ia, ja = self.cell_ij_many(ax, ay)
        ib, jb = self.cell_ij_many(bx, by)
        dz = self._elev[ib, jb].astype(np.float64) - self._elev[ia, ja]
        grade = np.where(length > 0, dz / np.maximum(length, 1e-9), 0.0)
        up = np.where(grade > 0, np.maximum(MIN_UPHILL_FACTOR, 1.0 - 2.0 * grade), 1.0)
        out = length * tpm / up
        # Twelve samples are about one per raster cell on a coarse edge, but a long leg (a
        # straight shortcut, a direct move, an aide's ride) can step over a river between
        # them. Such legs are also checked at half the raster step: any impassable sample
        # makes the leg impassable. The time estimate is still the twelve samples' (so the
        # minutes of legs that cross nothing are unchanged).
        dense = math.ceil(float(np.max(length, initial=0.0)) / (self.cell / 2.0))
        if dense > self._EDGE_SAMPLES:
            td = (np.arange(dense) + 0.5) / dense
            xd = ax[..., None] + (bx - ax)[..., None] * td
            yd = ay[..., None] + (by - ay)[..., None] * td
            inbd = (
                (xd >= self.ox)
                & (xd < self.ox + self.nx * self.cell)
                & (yd >= self.oy)
                & (yd < self.oy + self.ny * self.cell)
            )
            di, dj = self.cell_ij_many(xd, yd)
            blocked = (~inbd | (v[di, dj] <= 0)).any(axis=-1)
            out = np.where(blocked, np.inf, out)
        return out

    def _coarse(self, profile: str) -> np.ndarray:
        """Edge minutes (cny, cnx, 8) between coarse nodes for a profile."""
        if profile not in self._coarse_cache:
            nx_, ny_ = self._nodes()
            cost = np.full((self.cny, self.cnx, 8), np.inf)
            for d, (di, dj) in enumerate(self._DIRS):
                i0 = slice(max(0, -di), self.cny - max(0, di))
                j0 = slice(max(0, -dj), self.cnx - max(0, dj))
                i1 = slice(max(0, di), self.cny - max(0, -di))
                j1 = slice(max(0, dj), self.cnx - max(0, -dj))
                cost[i0, j0, d] = self.segment_minutes(
                    profile, nx_[i0, j0], ny_[i0, j0], nx_[i1, j1], ny_[i1, j1]
                )
            self._coarse_cache[profile] = cost
        return self._coarse_cache[profile]

    def coarse_ij(self, p: geo.Point) -> tuple[int, int]:
        return (
            _sym_index(float(p[1]), self.coy, self.coarse_m, self.cny, self.cy),
            _sym_index(float(p[0]), self.cox, self.coarse_m, self.cnx, self.cx),
        )

    def segment_passable(self, profile: str, a: geo.Point, b: geo.Point) -> bool:
        m = self.segment_minutes(
            profile, np.array(a[0]), np.array(a[1]), np.array(b[0]), np.array(b[1])
        )
        return bool(np.isfinite(m))

    def path_cost(
        self, a: geo.Point, b: geo.Point, formation_state: Any = "inf_column"
    ) -> tuple[float, list[geo.Point]]:
        """A* over coarse nodes (100 m) preferring roads, edges costed on the fine raster.

        Returns (minutes for a fresh body, waypoints ending at b); (inf, []) if unreachable.
        formation_state: a profile key (movement.BASE_SPEED), a Unit, or a UnitState
        (taken as infantry).
        """
        if isinstance(formation_state, Unit):
            profile = profile_for(formation_state)
        elif isinstance(formation_state, UnitState):
            profile = {UnitState.LINE: "inf_line", UnitState.SQUARE: "inf_square"}.get(
                formation_state, "inf_column"
            )
        else:
            profile = str(formation_state)
        a = (float(a[0]), float(a[1]))
        b = (float(b[0]), float(b[1]))
        key = (profile, a[0], a[1], b[0], b[1])  # exact: cached values are pure in the key
        if key in self._route_cache:
            m, pts = self._route_cache[key]
            return m, list(pts)
        if len(self._route_cache) > 20000:
            self._route_cache.clear()
        if self.segment_passable(profile, a, b) and geo.dist(a, b) <= self.coarse_m * 1.5:
            m = float(self.segment_minutes(profile, *map(np.array, (a[0], a[1], b[0], b[1]))))
            self._route_cache[key] = (m, [b])
            return m, [b]
        cost = self._coarse(profile)
        nx_, ny_ = self._nodes()
        s, g = self.coarse_ij(a), self.coarse_ij(b)
        result = self._astar(s, g, cost, profile)
        if result is None:
            m, pts = (
                self._road_route(profile, a, b)
                if profile in ROAD_GRAPH_PROFILES
                else (math.inf, [])
            )
            self._route_cache[key] = (m, pts)
            return m, list(pts)
        _, cells = result
        nodes = [(float(nx_[c]), float(ny_[c])) for c in cells]
        # start: skip the own-cell node when the direct leg to the next node is passable
        if len(nodes) > 1 and self.segment_passable(profile, a, nodes[1]):
            nodes = nodes[1:]
        # end: go straight to b from the last node, or from the one before if passable
        if len(nodes) > 1 and self.segment_passable(profile, nodes[-2], b):
            nodes = nodes[:-1]
        pts = [*nodes, b] if self.segment_passable(profile, nodes[-1], b) else nodes
        pts = _drop_collinear([a, *pts])[1:]
        legs = [a, *pts]
        minutes = float(
            sum(
                self.segment_minutes(profile, *map(np.array, (p[0], p[1], q[0], q[1])))
                for p, q in itertools.pairwise(legs)
            )
        )
        # a straight line that is passable and no slower beats the node-to-node zigzag
        straight = float(self.segment_minutes(profile, *map(np.array, (a[0], a[1], b[0], b[1]))))
        if math.isfinite(straight) and straight <= minutes:
            minutes, pts = straight, [b]
        if profile in ROAD_GRAPH_PROFILES:  # wheels: the fine road graph when it is faster
            rm, rpts = self._road_route(profile, a, b)
            if rm < minutes:
                minutes, pts = rm, rpts
        self._route_cache[key] = (minutes, pts)
        return minutes, list(pts)

    # ------------------------------------------------------- the road graph
    def _road_cells(self, profile: str) -> tuple[np.ndarray, dict[int, int]]:
        """Fine cells of the road graph for a profile: road, bridged water and fords open to
        it, where it can move. Returns (flat indices, flat index -> position)."""
        cache = self._road_cell_cache
        if profile not in cache:
            v = self.speed_raster(profile)
            water_ok = (self._cover == Cover.WATER) & (v > 0)
            mask = ((self._cover == Cover.ROAD) | water_ok) & (v > 0)
            flat = np.flatnonzero(mask)
            cache[profile] = (flat, {int(c): k for k, c in enumerate(flat)})
        return cache[profile]

    def _road_route(
        self, profile: str, a: geo.Point, b: geo.Point
    ) -> tuple[float, list[geo.Point]]:
        """Route along the fine road graph (road cells joined to their 8 neighbours, so a
        road band one cell wide is connected through its diagonal steps): a straight leg from
        `a` to the nearest road cell it can reach, the road, a straight leg to `b`. (inf, [])
        when there is none. The 100 m graph alone is not enough for wheels: it joins road
        nodes by sampled straight legs, which leave an oblique 25 m road band at its corners."""
        flat, pos = self._road_cells(profile)
        if len(flat) == 0:
            return math.inf, []
        ri, rj = np.divmod(flat, self.nx)
        cx = self.ox + (rj + 0.5) * self.cell
        cy = self.oy + (ri + 0.5) * self.cell

        def entry(p: geo.Point) -> int | None:
            # nearest first; ties by distance to the field's centre, then by the side of the
            # line from p to the centre (both unchanged by the 180° rotation), never by
            # raster order
            d = np.hypot(cx - p[0], cy - p[1])
            dc = np.hypot(cx - self.cx, cy - self.cy)
            side = (cx - p[0]) * (self.cy - p[1]) - (cy - p[1]) * (self.cx - p[0])
            for k in np.lexsort((side, dc, d))[:ROAD_ENTRY_TRIES]:
                q = (float(cx[k]), float(cy[k]))
                if d[k] < 1.0 or self.segment_passable(profile, p, q):
                    return int(k)
            return None

        s, g = entry(a), entry(b)
        if s is None or g is None:
            return math.inf, []
        v = self.speed_raster(profile)
        vflat = v.ravel()
        nx = self.nx

        def succ(cur: int):
            c = int(flat[cur])
            ci, cj = divmod(c, nx)
            for di, dj in self._DIRS:
                ni, nj = ci + di, cj + dj
                if not (0 <= ni < self.ny and 0 <= nj < nx):
                    continue
                n = pos.get(ni * nx + nj)
                if n is None:
                    continue
                step = self.cell * (math.sqrt(2.0) if di and dj else 1.0)
                yield n, step * 0.5 * (1.0 / vflat[c] + 1.0 / vflat[ni * nx + nj])

        # the edge costs are the same both ways, so the predecessors are the successors
        out = _canonical_path(
            s, g, succ, succ, cx.tolist(), cy.tolist(), 1.0 / max(BASE_SPEED[profile])
        )
        if out is None:
            return math.inf, []
        road_minutes, chain = out
        cells = [(float(cx[k]), float(cy[k])) for k in chain]
        pts = _drop_collinear([a, *cells, b])[1:]
        if len(pts) > 1 and geo.dist(pts[-2], b) < 1.0:
            pts = [*pts[:-2], b]

        def leg(p: geo.Point, q: geo.Point) -> float:
            if geo.dist(p, q) <= 0.0:
                return 0.0
            return float(self.segment_minutes(profile, *map(np.array, (p[0], p[1], q[0], q[1]))))

        # the road's minutes are the graph's: a sampled diagonal leg along a band one cell
        # wide hits its cells' corners, which floor into the neighbours (the off-road cells)
        # on a band running north-west to south-east
        minutes = leg(a, cells[0]) + road_minutes + leg(cells[-1], b)
        return minutes, pts

    def minutes_field(self, src: geo.Point, profile: str) -> np.ndarray:
        """Dijkstra from the node of src's coarse cell: minutes to every coarse node
        (inf where unreachable). Cached per (profile, cell): a pure function of the cell."""
        cell = self.coarse_ij(src)
        key = ("field", profile, cell)
        cache = self._field_cache
        if key in cache:
            return cache[key]
        if len(cache) > 256:
            cache.clear()
        cost = self._coarse(profile)
        cnx = self.cnx
        best = np.full(self.cny * self.cnx, np.inf)
        start = cell[0] * cnx + cell[1]
        best[start] = 0.0
        heap = [(0.0, start)]
        dirs = self._DIRS
        while heap:
            g, cur = heapq.heappop(heap)
            if g > best[cur]:
                continue
            ci, cj = divmod(cur, cnx)
            row = cost[ci, cj]
            for d in range(8):
                c = row[d]
                if c == math.inf:
                    continue
                di, dj = dirs[d]
                n = (ci + di) * cnx + cj + dj
                ng = g + c
                if ng < best[n]:
                    best[n] = ng
                    heapq.heappush(heap, (ng, n))
        out = best.reshape(self.cny, self.cnx)
        cache[key] = out
        return out

    def _astar(self, s, g, cost, profile):
        """The fastest route between two coarse nodes: (minutes, [(i, j), ...]) or None. Of
        routes equally fast, the one `_canonical_path` draws, never the first found."""
        cnx, cny = self.cnx, self.cny
        nx_, ny_ = self._nodes()
        dirs = self._DIRS
        rows = cost.reshape(cny * cnx, 8).tolist()

        def succ(cur: int):
            ci, cj = divmod(cur, cnx)
            row = rows[cur]
            for d in range(8):
                c = row[d]
                if c != math.inf:
                    di, dj = dirs[d]
                    yield (ci + di) * cnx + cj + dj, c

        def pred(cur: int):
            ci, cj = divmod(cur, cnx)
            for d in range(8):
                di, dj = dirs[d]
                pi, pj = ci - di, cj - dj
                if 0 <= pi < cny and 0 <= pj < cnx:
                    c = rows[pi * cnx + pj][d]
                    if c != math.inf:
                        yield pi * cnx + pj, c

        out = _canonical_path(
            s[0] * cnx + s[1],
            g[0] * cnx + g[1],
            succ,
            pred,
            nx_.ravel().tolist(),
            ny_.ravel().tolist(),
            1.0 / max(BASE_SPEED[profile]),
        )
        if out is None:
            return None
        minutes, cells = out
        return minutes, [divmod(c, cnx) for c in cells]

    # ----------------------------------------------------------- sighting
    def line_of_sight(self, a: geo.Point, b: geo.Point, eye_m: float = 2.0) -> bool:
        return bool(self.los_many(np.array([a], float), np.array([b], float), eye_m)[0])

    def los_many(
        self,
        a: np.ndarray,
        b: np.ndarray,
        eye_m: float = 2.0,
        target_m: float = LOS_TARGET_HEIGHT_M,
    ) -> np.ndarray:
        """Vectorised DEM ray walk for N pairs. a, b: (N, 2) arrays. Returns bool (N,)."""
        n = len(a)
        if n == 0:
            return np.zeros(0, dtype=bool)
        d = np.hypot(b[:, 0] - a[:, 0], b[:, 1] - a[:, 1])
        s = int(min(LOS_MAX_SAMPLES, max(8, math.ceil(float(d.max()) / (self.cell / 2)))))
        t = (np.arange(1, s) / s)[None, :]  # interior samples
        xs = a[:, 0:1] + (b[:, 0:1] - a[:, 0:1]) * t
        ys = a[:, 1:2] + (b[:, 1:2] - a[:, 1:2]) * t
        i, j = self.cell_ij_many(xs, ys)
        ia, ja = self.cell_ij_many(a[:, 0], a[:, 1])
        ib, jb = self.cell_ij_many(b[:, 0], b[:, 1])
        za = self._elev[ia, ja].astype(np.float64) + eye_m
        zb = self._elev[ib, jb].astype(np.float64) + target_m
        line = za[:, None] + (zb - za)[:, None] * t
        ground = self._elev[i, j]
        # ignore the observer's and target's own cells for terrain masking
        own = ((i == ia[:, None]) & (j == ja[:, None])) | ((i == ib[:, None]) & (j == jb[:, None]))
        terrain_block = ((ground > line) & ~own).any(axis=1)
        cov = self._cover[i, j]
        obstruct = np.isin(cov, BLOCKING_COVER)
        depth = obstruct.sum(axis=1) * (d / s)
        return ~terrain_block & (depth <= LOS_BLOCK_DEPTH_M)


def sym_floor(v: float, lo: float, size: float, centre: float) -> int:
    """The cell holding `v` on an axis of cells of `size` from `lo`: the floor, except that a
    value exactly on a boundary beyond the centre counts to the cell nearer the centre, so the
    lookup commutes with the 180° rotation about the centre (a point on a boundary always goes
    the centre's way). Not clamped."""
    t = (v - lo) / size
    j = math.floor(t)
    if v > centre and j == t:
        j -= 1
    return int(j)


def _sym_index(v: float, lo: float, size: float, n: int, centre: float) -> int:
    """`sym_floor` clamped to an axis of `n` cells."""
    return min(max(sym_floor(v, lo, size, centre), 0), n - 1)


def _sym_index_many(v: np.ndarray, lo: float, size: float, n: int, centre: float) -> np.ndarray:
    """`_sym_index` over an array."""
    v = np.asarray(v, dtype=np.float64)
    t = (v - lo) / size
    j = np.floor(t)
    j = np.where((v > centre) & (j == t), j - 1.0, j)
    return np.clip(j, 0, n - 1).astype(np.int64)


def _canonical_path(
    start: int, goal: int, succ, pred, xs: list[float], ys: list[float], h_rate: float
) -> tuple[float, list[int]] | None:
    """The fastest path from `start` to `goal` on a graph whose node n stands at (xs[n],
    ys[n]): (minutes, nodes) or None. `succ(n)` and `pred(n)` yield (node, minutes) for the
    edges out of and into n.

    A* with a consistent heuristic (straight-line distance at the profile's top speed, which
    no edge beats), run on until every node that could lie on a fastest path is settled: the
    settled times are then the shortest times, whatever order the search took nodes in. The
    path is drawn back from the goal on those times: at each node, of the predecessors on a
    fastest path, the one nearest the straight line from start to goal, then the one nearest
    the start, then the one left of that line. Every key is a function of positions that the
    180° rotation of the field leaves unchanged, so the rotated query gives the rotated path;
    no tie goes by enumeration order or node number (the node number decides only between
    two nodes at the same place).
    """
    gx, gy = xs[goal], ys[goal]
    best = {start: 0.0}
    heap = [(math.hypot(xs[start] - gx, ys[start] - gy) * h_rate, start)]
    closed: set[int] = set()
    bound = math.inf
    while heap:
        f, cur = heapq.heappop(heap)
        if f > bound:
            break
        if cur in closed:
            continue
        closed.add(cur)
        if cur == goal:
            bound = best[goal] + ROUTE_TIE_MIN
            continue
        gc = best[cur]
        for n, c in succ(cur):
            if n in closed:
                continue
            ng = gc + c
            if ng < best.get(n, math.inf):
                best[n] = ng
                heapq.heappush(heap, (ng + math.hypot(xs[n] - gx, ys[n] - gy) * h_rate, n))
    if goal not in closed:
        return None
    sx, sy = xs[start], ys[start]
    vx, vy = gx - sx, gy - sy
    path = [goal]
    cur = goal
    while cur != start:
        lim = best[cur] + ROUTE_TIE_MIN
        cand = None
        for p, c in pred(cur):
            if p not in closed or best[p] >= best[cur] or best[p] + c > lim:
                continue
            cr = (xs[p] - sx) * vy - (ys[p] - sy) * vx
            key = (abs(cr), math.hypot(xs[p] - sx, ys[p] - sy), -cr, p)
            if cand is None or key < cand:
                cand = key
        if cand is None:  # the goal was settled from a predecessor; cannot happen
            return None
        cur = cand[3]
        path.append(cur)
    path.reverse()
    return best[goal], path


def _drop_collinear(pts: list[geo.Point]) -> list[geo.Point]:
    if len(pts) < 3:
        return pts
    out = [pts[0]]
    for k in range(1, len(pts) - 1):
        a, b, c = out[-1], pts[k], pts[k + 1]
        cross = (b[0] - a[0]) * (c[1] - b[1]) - (b[1] - a[1]) * (c[0] - b[0])
        if abs(cross) > 1e-6:
            out.append(b)
    out.append(pts[-1])
    return out


def feature_from_json(d: dict) -> Feature:
    g = d["geometry"]
    return Feature(
        name=d["name"],
        kind=FeatureKind(d["kind"]),
        geometry_kind=GeometryKind(g["type"]),
        coords=[(float(x), float(y)) for x, y in g["coords"]],
        aliases=list(d.get("aliases", [])),
        props={k: v for k, v in d.items() if k not in _FEATURE_KEYS},
    )
