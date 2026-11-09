"""The umpire's account of the field, version 2 (the end-of-battle questions).

It gives, per side, the strength and the count of bodies steady, shaken, in flight or routed,
and destroyed; then a ground section saying who holds each place the objectives name; then
every body with its strength, state and position relative to the nearest small named place,
with bearing and distance. Never a brigade's centroid by the nearest feature: on a field with
a 5 km heights polygon that reads "at the heights" for nearly every body of both armies, and
Jev cannot tell who holds the ground.

The account is prose built from engine facts; Jev is never handed numbers it must compute
with. It is rendered from a `Field` (plain data, `final_state.field_json`) and the scenario's
features, so a run replayed under an older revision is judged with this account.
"""

from __future__ import annotations

import math
import re
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from itertools import pairwise

from . import geometry as geo
from .combat import DISORDERED
from .final_state import field_json
from .geometry import bearing_word, dist_words
from .types import Feature, FeatureKind, GeometryKind

# Account versions: 2, this account (rejudge only); 3, the same account asked in game, and the
# verdict asks each side's achievement (wholly, in the main, in part, not at all)
UMPIRE_VERSION = 3

# Constants (assumptions unless marked)
STEADY_MORALE = 45.0  # assumption: below the rally threshold (morale.RALLY_MORALE) a formed
# body is shaken: it would not re-form from a rout at this morale
SHAKEN_DISORDER = DISORDERED  # the disorder at which a line counts as shaken
AREA_SPAN_M = 2000.0  # assumption: a polygon longer than this is an area (the heights), not a
# place: bodies are "on" it, and the ground section splits it into thirds
AT_M = 100.0  # within this of a place's edge a body is "in" or "at" it
HOLD_PLACE_M = 500.0  # assumption: bodies within this of a village, wood or farm hold it
ROAD_ALONG_M = 150.0  # within this of a road a body is "on" it
HOLD_ROAD_M = 500.0  # assumption: bodies within this of a stretch of road hold that stretch
ROAD_PLACE_M = 900.0  # assumption: a village or farm whose edge is within this of a road
# divides it into stretches (villages may lie 700-900 m off a high road)
FLIGHT_CONE_DEG = 40.0  # a fleeing body runs "toward" a place within this of its heading
FLIGHT_REACH_M = 6000.0
SAMPLE_M = 200.0  # grid step for an area's sector centres

ANCHOR_KINDS = (
    FeatureKind.VILLAGE,
    FeatureKind.FARM,
    FeatureKind.WOOD,
    FeatureKind.HEIGHT,
    FeatureKind.POND,
    FeatureKind.MILL,
    FeatureKind.BRIDGE,
    FeatureKind.CHURCH,
    FeatureKind.FORD,
)
TOWARD_KINDS = (FeatureKind.VILLAGE, FeatureKind.FARM, FeatureKind.WOOD)
CONDITIONS = ("steady", "shaken", "in flight", "routed", "destroyed")
# bodies off the map; listed only when a side has any
OFFMAP_CONDITIONS = ("off the map", "fled off the map", "captured", "not yet arrived")
FATE_CONDITION = {
    "exited": "off the map",
    "fled": "fled off the map",
    "captured": "captured",
    "awaiting": "not yet arrived",
}


@dataclass
class Body:
    id: str
    name: str
    side: str
    formation: str
    arm: str
    men: int
    start_men: int
    x: float
    y: float
    state: str  # UnitState value
    morale: float
    disorder: float
    flee_to: tuple[float, float] | None = None
    engaged: bool = False
    fate: dict | None = None  # off the map: Sim.offmap's record (exited, fled, captured, ...)

    @property
    def condition(self) -> str:
        """steady, shaken (formed but disordered or near breaking), in flight (routed and
        running from an enemy), routed (broken, out of reach, not yet rallied), destroyed;
        off the map, fled off the map, captured, not yet arrived."""
        if self.fate:
            return FATE_CONDITION.get(self.fate.get("fate", ""), "destroyed")
        if self.state == "destroyed":
            return "destroyed"
        if self.state == "routed":
            return "in flight" if self.flee_to else "routed"
        if self.morale < STEADY_MORALE or self.disorder >= SHAKEN_DISORDER:
            return "shaken"
        return "steady"

    @property
    def formed(self) -> bool:
        return self.condition in ("steady", "shaken")

    @property
    def p(self) -> geo.Point:
        return (self.x, self.y)


@dataclass
class Field:
    clock: str
    minutes: int
    bodies: list[Body]

    @classmethod
    def from_json(cls, d: dict) -> Field:
        bodies: list[Body] = []
        for b in d["bodies"]:
            ft = b.get("flee_to")
            bodies.append(Body(**{**b, "flee_to": (ft[0], ft[1]) if ft else None}))
        return cls(clock=d["clock"], minutes=int(d["minutes"]), bodies=bodies)


def field_of(sim, with_hash: bool = True) -> Field:
    return Field.from_json(field_json(sim, with_hash=with_hash))


# ---------------------------------------------------------------------------
# Places


def _extent(f: Feature) -> float:
    xs = [p[0] for p in f.coords]
    ys = [p[1] for p in f.coords]
    return max(max(xs) - min(xs), max(ys) - min(ys))


def is_area(f: Feature) -> bool:
    return f.geometry_kind == GeometryKind.POLYGON and _extent(f) > AREA_SPAN_M


def _centre(f: Feature) -> geo.Point:
    if f.geometry_kind == GeometryKind.POLYGON:
        return geo.ring_centroid(f.coords)
    return f.coords[len(f.coords) // 2]


def anchors(features: Iterable[Feature]) -> list[Feature]:
    """Small named places a position is given from: villages, farms, woods, hills, ponds."""
    return [
        f
        for f in features
        if f.kind in ANCHOR_KINDS and not is_area(f) and f.geometry_kind != GeometryKind.POLYLINE
    ]


class Places:
    """Position words over a scenario's features."""

    def __init__(self, features: Sequence[Feature]):
        self.features = list(features)
        self.anchors = anchors(self.features)
        self.areas = [f for f in self.features if is_area(f)]
        self.roads = [f for f in self.features if f.kind == FeatureKind.ROAD]
        self.sectors = {f.name: _sectors(f) for f in self.areas}

    def nearest(self, p: geo.Point, kinds: Sequence[FeatureKind] | None = None) -> Feature:
        cands = [f for f in self.anchors if kinds is None or f.kind in kinds] or self.anchors
        return min(cands, key=lambda f: (geo.feature_dist(p, f), f.name))

    def relative(self, p: geo.Point) -> str:
        """'in Křečhoř', '800 m south of Křečhoř' (bearing from the place's centre)."""
        if not self.anchors:
            return f"at ({p[0]:.0f}, {p[1]:.0f})"
        f = self.nearest(p)
        d = geo.feature_dist(p, f)
        if d <= AT_M:
            return f"{'in' if f.kind in (FeatureKind.VILLAGE, FeatureKind.WOOD) else 'at'} {f.name}"
        return f"{dist_words(d)} {bearing_word(geo.bearing(_centre(f), p))} of {f.name}"

    def on(self, p: geo.Point) -> list[str]:
        out = []
        for a in self.areas:
            if geo.point_in_polygon(p, a.coords):
                sec = next((s for s in self.sectors[a.name] if s.contains(p)), None)
                out.append(f"on {a.name}" + (f" ({sec.short})" if sec else ""))
        out.extend(
            f"on the {r.name}" for r in self.roads if geo.polyline_dist(p, r.coords) <= ROAD_ALONG_M
        )
        return out

    def where(self, p: geo.Point) -> str:
        return ", ".join([*self.on(p), self.relative(p)])

    def toward(self, p: geo.Point, goal: geo.Point) -> str:
        """'north-east, toward Kutlíře': the heading of a flight and the named place ahead."""
        head = geo.bearing(p, goal)
        best = None
        for f in self.anchors:
            if f.kind not in TOWARD_KINDS:
                continue
            c = _centre(f)
            d = geo.dist(p, c)
            if d < AT_M or d > FLIGHT_REACH_M:
                continue
            if geo.angle_diff(head, geo.bearing(p, c)) <= FLIGHT_CONE_DEG and (
                best is None or d < best[0]
            ):
                best = (d, f.name)
        return bearing_word(head) + (f", toward {best[1]}" if best else "")


# ---------------------------------------------------------------------------
# Ground: who holds each objective place


@dataclass
class Sector:
    """A third of an area: the part of its ring whose coordinate along the area's longer axis
    (x for an east-west area, y for a north-south one) lies in [lo, hi]."""

    label: str  # "its western third", "the centre"
    short: str  # "west", "centre"
    ring: list[geo.Point]
    ew: bool
    lo: float
    hi: float

    def contains(self, p: geo.Point) -> bool:
        t = p[0] if self.ew else p[1]
        return self.lo <= t <= self.hi and geo.point_in_polygon(p, self.ring)


def _sectors(f: Feature) -> list[Sector]:
    """An area split in thirds along its longer axis: 'western third' ... 'eastern third'."""
    xs = [p[0] for p in f.coords]
    ys = [p[1] for p in f.coords]
    ew = (max(xs) - min(xs)) >= (max(ys) - min(ys))
    lo, hi = (min(xs), max(xs)) if ew else (min(ys), max(ys))
    names = (
        (("western", "west"), ("centre", "centre"), ("eastern", "east"))
        if ew
        else (("southern", "south"), ("centre", "centre"), ("northern", "north"))
    )
    out = []
    for i, (n, short) in enumerate(names):
        a, b = lo + (hi - lo) * i / 3, lo + (hi - lo) * (i + 1) / 3
        label = "the centre" if n == "centre" else f"its {n} third"
        out.append(Sector(label, short, list(f.coords), ew, a, b))
    return out


def _sector_centre(s: Sector) -> geo.Point | None:
    xs = [p[0] for p in s.ring]
    ys = [p[1] for p in s.ring]
    pts = []
    y = min(ys) + SAMPLE_M / 2
    while y < max(ys):
        x = min(xs) + SAMPLE_M / 2
        while x < max(xs):
            if s.contains((x, y)):
                pts.append((x, y))
            x += SAMPLE_M
        y += SAMPLE_M
    return geo.centroid(pts) if pts else None


def _mentions(text: str, names: Iterable[str]) -> bool:
    t = text.casefold()
    for name in names:
        n = name.casefold().strip()
        if len(n) < 3:
            continue
        if re.search(r"(?<!\w)" + re.escape(n) + r"(?!\w)", t):
            return True
    return False


def objective_features(features: Sequence[Feature], objectives: str) -> list[Feature]:
    """Features the objectives text names (by name or alias), in the scenario's order."""
    return [f for f in features if f.kind != FeatureKind.CHURCH and _mentions(objectives, f.names)]


def _arc(pts: Sequence[geo.Point], p: geo.Point) -> tuple[float, float]:
    """(distance along the polyline of the point nearest p, distance from it)."""
    best = (math.inf, 0.0)
    run = 0.0
    for a, b in pairwise(pts):
        seg = geo.dist(a, b)
        if seg > 0:
            t = ((p[0] - a[0]) * (b[0] - a[0]) + (p[1] - a[1]) * (b[1] - a[1])) / seg**2
            t = max(0.0, min(1.0, t))
            q = (a[0] + t * (b[0] - a[0]), a[1] + t * (b[1] - a[1]))
            d = geo.dist(p, q)
            if d < best[0]:
                best = (d, run + t * seg)
        run += seg
    return best[1], best[0]


@dataclass
class GroundPlace:
    label: str
    test: Callable[[Body], bool]
    road: str | None = None  # a stretch of this road, from `frm` to `to`
    frm: str = ""
    to: str = ""


def ground_places(places: Places, objectives: str) -> list[GroundPlace]:
    """The places the objectives name: areas (whole, then in thirds), then villages, woods
    and other places, then roads in stretches between the named places along them."""
    feats = objective_features(places.features, objectives)
    areas = [f for f in feats if is_area(f)]
    roads = [
        f for f in feats if f.kind == FeatureKind.ROAD and f.geometry_kind == GeometryKind.POLYLINE
    ]
    rest = [f for f in feats if f not in areas and f not in roads]
    out: list[GroundPlace] = []
    for f in areas:
        out.append(
            GroundPlace(
                f"{f.name} (anywhere on it)", lambda b, f=f: geo.point_in_polygon(b.p, f.coords)
            )
        )
        for s in places.sectors[f.name]:
            c = _sector_centre(s)
            near = f", about {places.relative(c)}" if c is not None else ""
            out.append(GroundPlace(f"{f.name}, {s.label}{near}", lambda b, s=s: s.contains(b.p)))
    out.extend(
        GroundPlace(
            f"{f.name} (within {HOLD_PLACE_M:.0f} m)",
            lambda b, f=f: geo.feature_dist(b.p, f) <= HOLD_PLACE_M,
        )
        for f in rest
    )
    for f in roads:
        out += _road_stretches(places, f)
    return out


def _road_stretches(places: Places, road: Feature) -> list[GroundPlace]:
    """A road cut into stretches between the villages and farms along it, in the order the
    polyline runs."""
    pts = road.coords
    length = geo.polyline_length(pts)
    marks = []
    for f in places.anchors:
        if f.kind not in TOWARD_KINDS:
            continue
        s, _ = _arc(pts, _centre(f))
        if geo.feature_dist(geo.nearest_on_polyline(_centre(f), pts), f) <= ROAD_PLACE_M:
            marks.append((s, f.name))
    marks.sort()
    if not marks:
        return [
            GroundPlace(
                f"the {road.name} (within {HOLD_ROAD_M:.0f} m)",
                lambda b: geo.polyline_dist(b.p, pts) <= HOLD_ROAD_M,
            )
        ]
    start_end = bearing_word(geo.bearing(pts[-1], pts[0]))
    end_end = bearing_word(geo.bearing(pts[0], pts[-1]))
    bounds = [(0.0, f"its {start_end} end"), *marks, (length, f"its {end_end} end")]
    out = []
    for (a, na), (b, nb) in pairwise(bounds):
        if b - a < 1.0:
            continue

        def test(body, a=a, b=b):
            s, d = _arc(pts, body.p)
            return a <= s <= b and d <= HOLD_ROAD_M

        out.append(GroundPlace(f"the {road.name} from {na} to {nb}", test, road.name, na, nb))
    return out


def _count(bodies: list[Body]) -> str:
    if not bodies:
        return "none"
    men = sum(b.men for b in bodies)
    return f"{len(bodies)} {'body' if len(bodies) == 1 else 'bodies'} ({men:,} men)"


@dataclass
class Holding:
    place: GroundPlace
    verdict: str  # "held by <side>", "contested", "empty"
    formed: dict[str, list[Body]]
    broken: dict[str, list[Body]]

    @property
    def bare(self) -> bool:
        """Empty, with no broken body either."""
        return self.verdict == "empty" and not any(self.broken.values())

    def line(self, sides: Sequence[str], label: str | None = None) -> str:
        v = "empty of formed bodies" if self.verdict == "empty" else self.verdict
        parts = [f"{s} {_count(self.formed[s])} formed" for s in sides]
        extra = [f"{s} {len(self.broken[s])} broken" for s in sides if self.broken[s]]
        return (
            f"  {label or self.place.label}: {v}; "
            + ", ".join(parts)
            + (f" ({', '.join(extra)})" if extra else "")
            + "."
        )


def holding(gp: GroundPlace, bodies: list[Body], sides: Sequence[str]) -> Holding:
    """Who holds `gp`: the one side with formed bodies there; both is contested."""
    here = [
        b
        for b in bodies
        if b.condition in ("steady", "shaken", "in flight", "routed") and gp.test(b)
    ]
    formed = {s: [b for b in here if b.side == s and b.formed] for s in sides}
    broken = {s: [b for b in here if b.side == s and not b.formed] for s in sides}
    present = [s for s in sides if formed[s]]
    verdict = f"held by {present[0]}" if len(present) == 1 else "contested" if present else "empty"
    return Holding(gp, verdict, formed, broken)


def ground_lines(gps: list[GroundPlace], bodies: list[Body], sides: Sequence[str]) -> list[str]:
    """One line per place; consecutive bare stretches of one road are merged."""
    hs = [holding(gp, bodies, sides) for gp in gps]
    lines: list[str] = []
    i = 0
    while i < len(hs):
        h = hs[i]
        j = i
        if h.place.road and h.bare:
            while j + 1 < len(hs) and hs[j + 1].place.road == h.place.road and hs[j + 1].bare:
                j += 1
        if j > i:
            p = h.place
            lines.append(h.line(sides, f"the {p.road} from {p.frm} to {hs[j].place.to}"))
        else:
            lines.append(h.line(sides))
        i = j + 1
    return lines


# ---------------------------------------------------------------------------
# The account


def _men(b: Body) -> int:
    """Men the body still has: a captured body's are lost, a body off the map keeps them."""
    if b.fate and b.fate.get("fate") == "captured":
        return 0
    return b.men


def _side_line(side: str, bodies: list[Body]) -> str:
    start = sum(b.start_men for b in bodies)
    lost = sum(max(0, b.start_men - _men(b)) for b in bodies)
    by = {c: [b for b in bodies if b.condition == c] for c in CONDITIONS + OFFMAP_CONDITIONS}
    formed = sum(b.men for b in by["steady"] + by["shaken"])

    def n(c: str) -> str:
        xs = by[c]
        men = sum((b.fate or {}).get("men", b.men) if c == "captured" else b.men for b in xs)
        return f"{len(xs)} {c}" + (f" ({men:,} men)" if xs and c != "destroyed" else "")

    off = "".join(f", {n(c)}" for c in OFFMAP_CONDITIONS if by[c])
    return (
        f"{side}: {start:,} men at the start, {lost:,} lost, {formed:,} still formed. "
        f"Bodies: {n('steady')}, {n('shaken')}, {n('in flight')}, {n('routed')}, "
        f"{n('destroyed')}{off}."
    )


def _fate_line(b: Body, deadline: str | None) -> str:
    f = b.fate or {}
    when = f.get("clock")
    late = ""
    if deadline and when:
        late = " (before the deadline)" if when <= deadline else " (after the deadline)"
    kind = f.get("fate")
    if kind == "exited":
        return f"left the map by {f.get('exit')} at {when}{late}"
    if kind == "fled":
        return f"fled off the map at {when}, lost to the battle"
    if kind == "captured":
        return f"captured by {f.get('by_name') or f.get('by')} at {when}"
    if kind == "awaiting":
        return f"not yet arrived (due at {f.get('due_clock') or f.get('at')} by {f.get('entry')})"
    return "off the map"


def _body_line(places: Places, b: Body, deadline: str | None = None) -> str:
    c = b.condition
    head = f"    {b.name} ({b.arm}, {_men(b):,} of {b.start_men:,})"
    if b.fate:
        return f"{head}: {_fate_line(b, deadline)}."
    if c == "destroyed":
        return f"{head}: destroyed."
    if c == "in flight":
        how = f"in flight {places.toward(b.p, b.flee_to)}"  # type: ignore[arg-type]
    elif c == "routed":
        how = "routed, out of reach of the enemy, not yet rallied"
    else:
        how = f"{c}, {b.state}" + (", in contact" if b.engaged else "")
    return f"{head}: {how}; {places.where(b.p)}."


def render(
    field: Field,
    features: Sequence[Feature],
    sides: Sequence[str],
    objectives: str = "",
    sunset: str | None = None,
    deadline: str | None = None,
) -> str:
    """The v2 account: time, each side's totals, the ground, then every body."""
    places = Places(features)
    sides = list(sides) + sorted({b.side for b in field.bodies} - set(sides))
    lines = [
        f"Time {field.clock} ({field.minutes} minutes after the start)."
        + (f" Sunset is at {sunset}." if sunset else "")
        + (f" The deadline is {deadline}." if deadline else "")
    ]
    lines.append(
        "States: steady = formed and in order; shaken = formed but disordered or near "
        "breaking; in flight = broken and running from the enemy; routed = broken, out of "
        "the enemy's reach and not yet rallied; destroyed = no longer a body."
        + (
            " Off the map = left by an exit, men kept; fled off the map = broken and gone off "
            "an edge, lost to the battle; captured = taken by the enemy, men lost; not yet "
            "arrived = still to enter the map."
            if any(b.fate for b in field.bodies)
            else ""
        )
    )
    lines.extend(_side_line(s, [b for b in field.bodies if b.side == s]) for s in sides)
    gps = ground_places(places, objectives) if objectives else []
    if gps:
        lines.append("")
        lines.append(
            f"Ground. A side holds a place when it has formed bodies (steady or shaken) there "
            f"and the other side has none; contested when both have; empty when neither has. "
            f"'There' is within {HOLD_PLACE_M:.0f} m of a village, wood or farm, inside an "
            f"area of high ground, and within {HOLD_ROAD_M:.0f} m of a stretch of road. "
            f"Broken bodies (in flight or routed) do not hold ground."
        )
        lines += ground_lines(gps, field.bodies, sides)
    for s in sides:
        lines.append("")
        lines.append(f"{s}, body by body:")
        mine = [b for b in field.bodies if b.side == s]
        for form in dict.fromkeys(b.formation for b in mine):
            bs = [b for b in mine if b.formation == form]
            alive = [
                b
                for b in bs
                if b.condition in ("steady", "shaken", "in flight", "routed", "off the map")
            ]
            counts = ", ".join(
                f"{sum(b.condition == c for b in bs)} {c}"
                for c in CONDITIONS + OFFMAP_CONDITIONS
                if any(b.condition == c for b in bs)
            )
            lines.append(f"  {form}: {sum(b.men for b in alive):,} men; {counts}.")
            lines += [_body_line(places, b, deadline) for b in bs]
    return "\n".join(lines)


__all__ = [
    "UMPIRE_VERSION",
    "Body",
    "Field",
    "Places",
    "field_of",
    "ground_places",
    "objective_features",
    "render",
]
