"""Movement physics: speeds, multipliers, formation-change times, route following.

Every number below is the spec's unless marked "assumption".
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from .geometry import (
    SNAP_DEG,
    Point,
    angle_diff,
    dist,
    lattice_bearing,
    snap_deg,
    snap_m,
    snap_point,
)
from .types import Arm, Cover, Unit, UnitKind, UnitState

# ---------------------------------------------------------------------------
# Constants

# Assumption: the spec gives cavalry one speed per gait and none for roads, so a cavalry column
# would ignore roads. Walk and trot gain infantry's road ratio (75 / 60) on a
# road; the gallop (a charge) does not.
CAV_ROAD_FACTOR = 75.0 / 60.0
# Base speeds, metres per minute, fresh, open ground: (on road, cross-country).
BASE_SPEED: dict[str, tuple[float, float]] = {
    "inf_column": (75.0, 60.0),
    "inf_line": (40.0, 40.0),
    "inf_square": (20.0, 20.0),
    "inf_skirmish": (50.0, 50.0),  # assumption: open order between column and line
    "inf_routed": (75.0, 70.0),  # assumption: a fleeing mob, a little faster than column
    "cav_walk": (100.0 * CAV_ROAD_FACTOR, 100.0),
    "cav_trot": (200.0 * CAV_ROAD_FACTOR, 200.0),
    "cav_gallop": (350.0, 350.0),
    "art_foot": (60.0, 40.0),
    "art_horse": (100.0, 100.0),
    "train": (50.0, 25.0),  # design assumption: wagons 50 m/min on a road, 25 on open ground
    "courier_road": (400.0, 250.0),  # spec: aide 400 m/min by road, 250 cross-country
    "hq": (200.0, 150.0),  # assumption: a general and staff at the trot
}
# Infantry double time multiplier (RECKLESS assaults, routs). Assumption: quick step ~1.3x.
DOUBLE_TIME = 1.3
GALLOP_MAX_MIN = 3  # minutes at gallop before blown (spec)
BLOWN_DISORDER = 20.0  # assumption: disorder added when a charge runs past 3 min of gallop

# Cover multipliers by arm class. WATER is impassable (0) except bridges and road cells.
COVER_MULT: dict[str, dict[int, float]] = {
    "inf": {
        Cover.OPEN: 1.0,
        Cover.ROUGH: 0.7,
        Cover.WOOD: 0.5,
        Cover.VILLAGE: 0.5,
        Cover.ORCHARD: 0.7,
        Cover.MARSH: 0.3,
        Cover.WATER: 0.0,
        Cover.ROAD: 1.0,
    },
    "cav": {
        Cover.OPEN: 1.0,
        Cover.ROUGH: 0.7,
        Cover.WOOD: 0.25,
        Cover.VILLAGE: 0.5,
        Cover.ORCHARD: 0.7,
        Cover.MARSH: 0.3,
        Cover.WATER: 0.0,
        Cover.ROAD: 1.0,
    },
    # assumption: guns move through wood like cavalry (teams and limbers); marsh stops them
    # off a road (the spec's MARSH 0.3 is for foot and horse)
    "art": {
        Cover.OPEN: 1.0,
        Cover.ROUGH: 0.7,
        Cover.WOOD: 0.25,
        Cover.VILLAGE: 0.5,
        Cover.ORCHARD: 0.7,
        Cover.MARSH: 0.0,
        Cover.WATER: 0.0,
        Cover.ROAD: 1.0,
    },
    # design assumption: wagons move only on roads and open ground (and bridges and fords that
    # pass them); woods, villages off the road, broken ground, orchards and marsh stop them
    "train": {c: (1.0 if c in (Cover.OPEN, Cover.ROAD) else 0.0) for c in Cover},
    # assumption: an aide is slowed only by water; road vs cross-country is in BASE_SPEED
    "courier": {c: (0.0 if c == Cover.WATER else 1.0) for c in Cover},
}
MIN_UPHILL_FACTOR = 0.4  # spec: 1 - 2 * grade, floor 0.4

# Formation change times, minutes: (from, to) -> minutes. "*" matches any state.
CHANGE_MIN: dict[tuple[str, str], float] = {
    ("column", "line"): 3.0,
    ("line", "column"): 2.0,
    ("*", "square"): 2.0,
    ("square", "line"): 2.0,  # assumption: same as forming square
    ("square", "column"): 2.0,  # assumption
    ("*", "skirmish"): 2.0,  # assumption
    ("skirmish", "*"): 2.0,  # assumption
    ("limbered", "unlimbered"): 3.0,
    ("unlimbered", "limbered"): 3.0,
    ("routed", "column"): 0.0,  # rally sets the state directly (morale.py)
}
HORSE_LIMBER_MIN = 2.0  # spec: horse artillery limbers/unlimbers in 2
CAV_CHANGE_MIN = 1.0  # assumption: cavalry column <-> line in 1 minute
FACING_DEG_PER_MIN = 90.0  # spec: 1 min per 90 degrees
# Wheels on the move: a body in line pays the facing rate when its route turns (Duffy: about
# two minutes for a battalion's substantial wheel, i.e. 180 degrees at the spec's rate); columns,
# squares, skirmishers, limbered guns and routed bodies follow their head for free.
# Assumption: heading changes up to 15 degrees are dressing on the march and cost nothing.
WHEEL_FREE_DEG = 15.0

# Fatigue per minute. Assumption: a routed body flees at double time and pays the
# double-time rate.
FATIGUE_DOUBLE_OR_TROT = 1.0
FATIGUE_GALLOP_OR_MELEE = 3.0
FATIGUE_MUSKETRY = 0.5
FATIGUE_RECOVER = -1.0
FATIGUE_MARCH = 0.0  # assumption: the spec lists no cost for ordinary marching
FATIGUE_MAX = 100.0  # fatigue runs from 0 (fresh) to this (exhausted)
# step speed x (1 - fatigue / FATIGUE_SLOW_DIV) x (1 - disorder / DISORDER_SLOW_DIV)
FATIGUE_SLOW_DIV = 200.0
DISORDER_SLOW_DIV = 200.0

# ---------------------------------------------------------------------------
# Runtime state


@dataclass
class BodyRT:
    """Engine-private runtime state of a body (part of the snapshot)."""

    route: list[Point] = field(default_factory=list)
    route_goal: Point | None = None
    change_to: str | None = None  # target formation state while changing
    change_left: float = 0.0
    turn_to: float | None = None
    gait: str = "walk"
    gallop_min: int = 0
    moved: float = 0.0  # metres moved this tick
    fired: bool = False  # fired this tick
    melee_with: str | None = None
    melee_left: int = 0
    melee_attacker: bool = False
    melee_encounter: bool = False  # two charging bodies met: a tie is a mutual recoil
    phase: str = "idle"  # drill phase
    phase_since: int = 0
    slot: Point | None = None
    target: str | None = None  # enemy unit id being engaged by the drill
    replan_at: int = 0
    start_men: int = 0
    prev_state: str | None = None  # state before forming square
    last_dist: dict[str, float] = field(default_factory=dict)
    cover_wait: int = 0
    blocked: int = 0
    via: list[Point] = field(default_factory=list)  # task route waypoints still to pass
    offset: Point = (0.0, 0.0)  # slot offset from the objective point
    origin: Point | None = None  # position when the task arrived
    blown: bool = False
    fire_target: str | None = None  # whom it fired at last tick
    pace: str = "halt"  # how it moved when it last moved: walk, double, trot, gallop
    melee_tick: int = -1  # the last minute it fought hand to hand
    rally_at: int = 0  # recovery clock: a routed body cannot rally before this minute
    attack_at: int = 0  # ... and no body strikes (charge, assault, pursuit) before this one
    pursued: bool = False  # a routed body already pursued in this flight is not struck again
    bn_lost: int = 0  # battalion guns lost (overrun when the battalion broke in a melee)
    bn_ammo: float = 100.0  # the gun section's ammunition

    def to_json(self) -> dict:
        return {
            "route": [list(p) for p in self.route],
            "route_goal": list(self.route_goal) if self.route_goal else None,
            "change_to": self.change_to,
            "change_left": self.change_left,
            "turn_to": self.turn_to,
            "gait": self.gait,
            "gallop_min": self.gallop_min,
            "moved": self.moved,
            "fired": self.fired,
            "melee_with": self.melee_with,
            "melee_left": self.melee_left,
            "melee_attacker": self.melee_attacker,
            "melee_encounter": self.melee_encounter,
            "phase": self.phase,
            "phase_since": self.phase_since,
            "slot": list(self.slot) if self.slot else None,
            "target": self.target,
            "replan_at": self.replan_at,
            "start_men": self.start_men,
            "prev_state": self.prev_state,
            "cover_wait": self.cover_wait,
            "blocked": self.blocked,
            "via": [list(p) for p in self.via],
            "offset": list(self.offset),
            "origin": list(self.origin) if self.origin else None,
            "blown": self.blown,
            "fire_target": self.fire_target,
            "pace": self.pace,
            "melee_tick": self.melee_tick,
            "rally_at": self.rally_at,
            "attack_at": self.attack_at,
            "pursued": self.pursued,
            "bn_lost": self.bn_lost,
            "bn_ammo": self.bn_ammo,
            "last_dist": dict(sorted(self.last_dist.items())),
        }


def busy(rt: BodyRT) -> bool:
    return rt.change_left > 0.0 or rt.turn_to is not None or rt.melee_with is not None


# ---------------------------------------------------------------------------
# Speeds, formation changes and turns


def arm_class(unit: Unit) -> str:
    return {Arm.INFANTRY: "inf", Arm.CAVALRY: "cav", Arm.ARTILLERY: "art", Arm.TRAIN: "train"}[
        unit.arm
    ]


def profile_for(unit: Unit, gait: str = "walk", state: UnitState | None = None) -> str:
    """Speed profile key for a body in a state and gait."""
    s = state or unit.state
    if unit.arm == Arm.INFANTRY:
        if s == UnitState.ROUTED:
            return "inf_routed"
        return {
            UnitState.LINE: "inf_line",
            UnitState.SQUARE: "inf_square",
            UnitState.SKIRMISH: "inf_skirmish",
        }.get(s, "inf_column")
    if unit.arm == Arm.CAVALRY:
        if s == UnitState.ROUTED:
            return "cav_trot"
        return {"trot": "cav_trot", "gallop": "cav_gallop"}.get(gait, "cav_walk")
    if unit.arm == Arm.TRAIN:
        return "train"
    if unit.kind == UnitKind.HORSE_BATTERY:
        return "art_horse"
    return "art_foot"


def profile_arm(profile: str) -> str:
    if profile.startswith("courier") or profile == "hq":
        return "courier"
    return profile.split("_", maxsplit=1)[0]


def uphill_factor(grade: float) -> float:
    if grade <= 0.0:
        return 1.0
    return max(MIN_UPHILL_FACTOR, 1.0 - 2.0 * grade)


def change_time(unit: Unit, frm: UnitState, to: UnitState) -> float:
    if frm == to:
        return 0.0
    if unit.arm == Arm.TRAIN:
        return 0.0  # a train has no formations (rallying sets it back in column)
    if unit.arm == Arm.ARTILLERY and {frm, to} == {UnitState.LIMBERED, UnitState.UNLIMBERED}:
        return (
            HORSE_LIMBER_MIN
            if unit.kind == UnitKind.HORSE_BATTERY
            else CHANGE_MIN[(frm.value, to.value)]
        )
    if unit.arm == Arm.CAVALRY:
        return CAV_CHANGE_MIN
    for key in ((frm.value, to.value), ("*", to.value), (frm.value, "*")):
        if key in CHANGE_MIN:
            return CHANGE_MIN[key]
    return 2.0  # assumption: any other change of formation


def order_change(unit: Unit, rt: BodyRT, to: UnitState) -> None:
    """Begin a formation change (no-op if already in or changing to that state)."""
    if unit.state == to or rt.change_to == to.value:
        return
    t = change_time(unit, unit.state, to)
    if t <= 0.0:
        unit.state = to
        rt.change_to, rt.change_left = None, 0.0
        return
    rt.change_to, rt.change_left = to.value, t


def order_turn(unit: Unit, rt: BodyRT, facing: float) -> None:
    if angle_diff(unit.facing_deg, facing) < 10.0:
        return
    rt.turn_to = snap_deg(facing)  # on the facing lattice, as every facing (follow_route)


def advance_timers(unit: Unit, rt: BodyRT, minutes: float = 1.0) -> float:
    """Spend time on formation changes and turns. Returns minutes left for moving."""
    left = minutes
    if rt.change_left > 0.0:
        spend = min(left, rt.change_left)
        rt.change_left -= spend
        left -= spend
        if rt.change_left <= 1e-9:
            rt.change_left = 0.0
            unit.state = UnitState(rt.change_to)
            rt.change_to = None
    if left > 0.0 and rt.turn_to is not None:
        need = angle_diff(unit.facing_deg, rt.turn_to) / FACING_DEG_PER_MIN
        if need <= left:
            unit.facing_deg = rt.turn_to
            rt.turn_to = None
            left -= need
        else:
            # rotate partially toward turn_to
            frac = left / need
            d = (rt.turn_to - unit.facing_deg + 540.0) % 360.0 - 180.0
            unit.facing_deg = snap_deg(unit.facing_deg + _snap_turn(d * frac))
            left = 0.0
    return left


def _snap_turn(a: float) -> float:
    """An angle turned, on the facing lattice (sign kept exactly): a facing on the lattice
    plus it stays on the lattice, so a turn and its image under the 180° rotation end exactly
    180° apart."""
    return round(a / SNAP_DEG) * SNAP_DEG


def step_speed(world, unit: Unit, gait: str, here: Point, nxt: Point) -> float:
    """Metres per minute for this body at `here` heading to `nxt`."""
    prof = profile_for(unit, gait)
    road, cross = BASE_SPEED[prof]
    c = world.cover(*here)
    base = road if c == Cover.ROAD else cross
    mult = COVER_MULT[arm_class(unit)][int(c)]
    if c == Cover.WATER and world.bridged(*here):
        mult = 1.0
    elif c == Cover.WATER:
        mult = world.ford_factor(here[0], here[1], arm_class(unit))
    if mult == 0.0:
        mult = 0.3  # leaving a water cell the body stands in (should not happen)
    d = dist(here, nxt)
    grade = 0.0
    if d > 1.0:
        # the probe steps from `here` by a lattice offset, so a probe and its image under the
        # 180° rotation are images exactly
        f = min(1.0, 25.0 / d)
        probe = (here[0] + snap_m((nxt[0] - here[0]) * f), here[1] + snap_m((nxt[1] - here[1]) * f))
        dz = world.elev(*probe) - world.elev(*here)
        grade = dz / max(1.0, dist(here, probe))
    v = base * mult * uphill_factor(grade)
    v *= max(0.0, 1.0 - unit.fatigue / FATIGUE_SLOW_DIV)
    v *= max(0.0, 1.0 - unit.disorder / DISORDER_SLOW_DIV)
    return v


def pace_of(unit: Unit, gait: str, speed_mult: float) -> str:
    """The exertion a minute of movement costs: gallop, trot, double (time) or walk."""
    if unit.arm == Arm.INFANTRY:
        return "double" if speed_mult > 1.0 or unit.state == UnitState.ROUTED else "walk"
    if gait in ("trot", "gallop"):
        return gait
    return "walk"


def fatigue_rate(unit: Unit, rt: BodyRT, now: int) -> float:
    """Fatigue change for the minute just played (spec), from what the body did in it: the
    highest of melee or gallop (+3), trot or double time (+1), musketry (+0.5); a body halted
    and not engaged recovers (-1); ordinary marching costs nothing."""
    rates = []
    if rt.melee_tick == now or rt.melee_with is not None:
        rates.append(FATIGUE_GALLOP_OR_MELEE)
    if rt.moved > 0.0:
        rates.append(
            {
                "gallop": FATIGUE_GALLOP_OR_MELEE,
                "trot": FATIGUE_DOUBLE_OR_TROT,
                "double": FATIGUE_DOUBLE_OR_TROT,
            }.get(rt.pace, FATIGUE_MARCH)
        )
    if rt.fired and unit.arm == Arm.INFANTRY:
        rates.append(FATIGUE_MUSKETRY)
    if any(r > 0.0 for r in rates):
        return max(rates)
    if rt.moved == 0.0 and not unit.engaged:
        return FATIGUE_RECOVER
    return 0.0


def apply_fatigue(unit: Unit, rt: BodyRT, now: int) -> None:
    unit.fatigue = min(FATIGUE_MAX, max(0.0, unit.fatigue + fatigue_rate(unit, rt, now)))


def pays_wheel(unit: Unit) -> bool:
    return unit.state == UnitState.LINE and unit.arm in (Arm.INFANTRY, Arm.CAVALRY)


def snap_body(world, unit: Unit) -> Point:
    """Set the body on the position lattice about the field's centre and its facing on the
    facing lattice (as Sim._snap does at the end of every minute). Returns the centre."""
    centre = world.centre
    unit.x, unit.y = snap_point((unit.x, unit.y), centre)
    unit.facing_deg = snap_deg(unit.facing_deg)
    return centre


def follow_route(
    world,
    unit: Unit,
    rt: BodyRT,
    minutes: float,
    gait: str,
    speed_mult: float = 1.0,
    stop_at: float | None = None,
    check=None,
    trace: list | None = None,
) -> float:
    """Move the body along rt.route for `minutes`. Returns metres moved.

    Speed is re-evaluated every sub-step of at most one raster cell, so cover and slope are
    followed on the fine raster. `stop_at` limits the total distance (contact clipping).
    `trace`, when given, receives one point (t, x, y, facing, popped) after every sub-step:
    minutes used so far, the position and facing then, and how many route points were passed;
    the simultaneous movement resolution (drill.resolve_moves) cuts a body short on it.

    Every point of the path stands on Sim._snap's lattice about the field's centre and every
    facing on its facing lattice: the body is set on them
    first, each route point is taken at its lattice point, a heading is `lattice_bearing`, and
    a step adds a lattice offset to a lattice point. A march and its image under the 180°
    rotation then pass exactly image points at exactly the same minutes, so where and when
    paths meet (drill.resolve_moves) cannot tell them apart.
    """
    popped = 0
    centre = snap_body(world, unit)

    def mark() -> None:
        if trace is not None:
            trace.append((minutes - budget_t, unit.x, unit.y, unit.facing_deg, popped))

    moved = 0.0
    budget_t = minutes
    sub = world.terrain.cell_m
    limit = math.inf if stop_at is None else max(0.0, stop_at)
    while budget_t > 1e-9 and rt.route and moved < limit - 1e-9:
        here = (unit.x, unit.y)
        tgt = snap_point(rt.route[0], centre)
        d = dist(here, tgt)
        if d < 1e-6:
            rt.route.pop(0)
            popped += 1
            continue
        heading = lattice_bearing(tgt[0] - here[0], tgt[1] - here[1])
        if pays_wheel(unit):
            turn = angle_diff(unit.facing_deg, heading)
            if turn > WHEEL_FREE_DEG:
                need = turn / FACING_DEG_PER_MIN
                if need > budget_t:  # wheel part of the way; the rest next minute
                    dd = (heading - unit.facing_deg + 540.0) % 360.0 - 180.0
                    unit.facing_deg = snap_deg(unit.facing_deg + _snap_turn(dd * budget_t / need))
                    budget_t = 0.0
                    mark()
                    break
                unit.facing_deg = heading
                budget_t -= need
                mark()
                continue
        v = step_speed(world, unit, gait, here, tgt) * speed_mult
        if v <= 1e-6:
            break
        step = min(d, sub, v * budget_t, limit - moved)
        nx = here[0] + snap_m((tgt[0] - here[0]) * step / d)
        ny = here[1] + snap_m((tgt[1] - here[1]) * step / d)
        if not world.passable(nx, ny, arm_class(unit)):
            rt.blocked += 1
            break
        if check is not None and not check(nx, ny):
            # close up to the boundary: bisect the sub-step
            lo, hi = 0.0, 1.0
            for _ in range(6):
                mid = (lo + hi) / 2.0
                if check(
                    here[0] + snap_m((nx - here[0]) * mid), here[1] + snap_m((ny - here[1]) * mid)
                ):
                    lo = mid
                else:
                    hi = mid
            if lo > 0.0:
                unit.x = here[0] + snap_m((nx - here[0]) * lo)
                unit.y = here[1] + snap_m((ny - here[1]) * lo)
                moved += step * lo
                budget_t -= step * lo / v
                mark()
            break
        unit.x, unit.y = nx, ny
        unit.facing_deg = heading
        moved += step
        budget_t -= step / v
        if step >= d - 1e-6:
            rt.route.pop(0)
            popped += 1
        mark()
    if moved > 0.0:
        rt.pace = pace_of(unit, gait, speed_mult)
    return moved
