"""Execution drills (docs/engine.md, "Drills"): per body and minute, the body's formation task
becomes a plan (where to go, in which state, whether to fire or close), and the plan becomes
movement. Drills are fixed, deterministic rules, not a planner. Every body drills against the
field as it stood at the start of the minute; `resolve_moves` then runs the paths together in
time and halts each body where it meets the enemy.
"""

from __future__ import annotations

import itertools
import math
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

import numpy as np

from . import geometry as geo
from .combat import CONTACT_M, SQUARE_RECOGNISE_M, steady_square
from .morale import add_disorder, rout
from .movement import (
    BLOWN_DISORDER,
    DOUBLE_TIME,
    GALLOP_MAX_MIN,
    BodyRT,
    advance_timers,
    arm_class,
    busy,
    follow_route,
    order_change,
    order_turn,
    profile_for,
    snap_body,
)
from .types import (
    Arm,
    Cover,
    Forbid,
    GeometryKind,
    Manner,
    OnContact,
    RefKind,
    Task,
    TaskKind,
    Unit,
    UnitKind,
    UnitState,
)
from .units import frontage
from .vision import Sighting

if TYPE_CHECKING:
    from .sim import Sim

from .command import condition_met, exit_objective, passable_near, resolve_ref

# ---------------------------------------------------------------------------
# Constants (the spec's unless marked "assumption")
DEPLOY_M = {
    Manner.CAUTIOUS: 600.0,
    Manner.MEASURED: 400.0,
    Manner.BOLD: 300.0,
    Manner.RECKLESS: 300.0,
}  # RECKLESS: assumption, as BOLD
FIRE_HALT_M = {
    Manner.CAUTIOUS: 200.0,
    Manner.MEASURED: 120.0,
    Manner.BOLD: 80.0,
    Manner.RECKLESS: 60.0,
}  # assumption: where an attacking line halts to fire
ASSAULT_AFTER_MIN = {
    Manner.CAUTIOUS: None,
    Manner.MEASURED: 10,
    Manner.BOLD: 5,
    Manner.RECKLESS: 0,
}  # assumption: minutes of fire before the bayonet
DEPLOY_SLACK_M = 2.0  # a column halted at the deployment line counts as there
ASSAULT_IF_DISORDER = 50.0  # assumption: an attacker closes early on a disordered target
SQUARE_CAV_M = 400.0  # SPEC: form square when cavalry within 400 m
SQUARE_COVER_M = 600.0  # assumption: friendly cavalry within 600 m counts as cover
SQUARE_CLEAR_M = 600.0  # assumption: leave square when no enemy cavalry within 600 m ...
SQUARE_CLEAR_MIN = 3  # assumption: ... for 3 minutes
# assumption: the square reflex answers cavalry seen within the last 3 minutes; an older sighting
# (memory keeps 30) holds no square, so a square re-forms SQUARE_CLEAR_MIN after the last fresh
# sighting within SQUARE_CLEAR_M
CAV_SIGHT_FRESH_MIN = 3
SQUARE_FLANK_M = 150.0  # assumption: a flank is covered by a formed friend within 150 m of it
EVADE_REFUGE_M = 600.0  # assumption: Grenzer and skirmishers look this far for cover or a line
EVADE_STOP_M = 80.0  # assumption: an evading body halts this near the friendly line it seeks
EVADE_AWAY_M = 300.0  # assumption: with no refuge it falls back this far from the cavalry
# Cavalry that pulled up before a steady square (command.PULLUP_BAR_MIN) screens it at 300 to
# 500 m (period practice: cavalry kept infantry in square for the guns) or takes another target
# of its task (assumptions).
SCREEN_SQUARE_MIN_M, SCREEN_SQUARE_MAX_M, SCREEN_SQUARE_AT_M = 300.0, 500.0, 400.0
CAV_TROT_M = 800.0  # SPEC
CAV_GALLOP_M = 250.0  # SPEC
CAV_ENGAGE_M = 600.0  # assumption: cavalry on ENGAGE/PRESS charges enemies within 600 m
REFORM_MIN = 5  # assumption: cavalry re-forms 5 minutes after a charge
BOMBARD_STANDOFF_M = 800.0  # SPEC
SCREEN_MIN_M, SCREEN_MAX_M, SCREEN_BACK_M = 600.0, 1000.0, 800.0  # SPEC 600..1000
SUPPORT_M = 300.0  # SPEC
FALL_BACK_M = 600.0  # assumption: FALL_BACK on contact retires 600 m
ARRIVE_M = 30.0  # assumption: within 30 m of its slot a body has arrived
VIA_REACHED_M = 100.0  # assumption
REPLAN_MIN = 5  # assumption: routes to moving objectives are refreshed every 5 minutes
THREAT_FACE_M = 1500.0  # assumption: halted bodies face known enemies within 1.5 km
ROUT_FLEE_CLEAR_M = 1000.0  # assumption: a routed body flees until no enemy within 1 km
ROUT_STEP_M = 300.0  # assumption: flee goal a few hundred metres ahead each minute
TRAIN_BOLT_M = 300.0  # design assumption: a train bolts at enemy cavalry within 300 m ...
TRAIN_COVER_M = 300.0  # ... when no formed friendly body is within 300 m of it
# An ADVANCE that leaves by an exit fights only what stands in its way, a body ahead within
# BLOCK_CORRIDOR_M of its line of march, and goes round what it will not fight (cavalry at a square
# it has pulled up before) by a point DETOUR_M beside it; a square it formed on the march moves on
# at square pace. Assumptions.
BLOCK_CORRIDOR_M = 200.0
DETOUR_M = 400.0
FORMED = (UnitState.LINE, UnitState.COLUMN, UnitState.SQUARE, UnitState.UNLIMBERED)  # flank cover
IN_COVER = (Cover.WOOD, Cover.VILLAGE)  # cover that shelters infantry from cavalry


# ---------------------------------------------------------------------------
# Advances that leave by an exit


def leaving_advance(sim: Sim, t: Task) -> bool:
    """An ADVANCE told to leave by an exit that may meet the enemy on its way (ENGAGE or
    PRESS): it fights through what blocks it and goes round what it cannot fight. Every other
    ADVANCE halts at what it meets."""
    if t.kind != TaskKind.ADVANCE or t.on_contact not in (OnContact.ENGAGE, OnContact.PRESS):
        return False
    return exit_objective(sim, t) is not None


def in_the_way(u: Unit, slot: geo.Point | None, known: dict[str, Sighting]) -> dict[str, Sighting]:
    """The sightings ahead of `u` on its line to `slot`, within BLOCK_CORRIDOR_M of it."""
    if slot is None:
        return {}
    dx, dy = slot[0] - u.x, slot[1] - u.y
    d = math.hypot(dx, dy)
    if d < 1.0:
        return {}
    ax, ay = dx / d, dy / d
    out = {}
    for k, s in known.items():
        along = (s.x - u.x) * ax + (s.y - u.y) * ay
        across = abs(-(s.x - u.x) * ay + (s.y - u.y) * ax)
        if 0.0 < along <= d + BLOCK_CORRIDOR_M and across <= BLOCK_CORRIDOR_M:
            out[k] = s
    return out


def detour(sim: Sim, u: Unit, slot: geo.Point, e: Sighting) -> geo.Point:
    """A point DETOUR_M beside the blocker `e`, on the side of it away from the line of march
    (its right when it stands dead ahead), moved onto ground the body may stand on."""
    b = geo.bearing((u.x, u.y), slot)
    r = math.radians(b + 90.0)
    lat = (e.x - u.x) * math.sin(r) + (e.y - u.y) * math.cos(r)
    side = -1.0 if lat > 0.0 else 1.0  # pass on the side away from the blocker
    return passable_near(sim, u, geo.offset((e.x, e.y), b + 90.0 * side, DETOUR_M))


# ---------------------------------------------------------------------------
# Drills (per body, per tick)


@dataclass
class Plan:
    goal: geo.Point | None = None
    state: UnitState | None = None
    gait: str = "walk"
    face: float | None = None
    assault: bool = False
    speed_mult: float = 1.0
    direct: bool = False
    stop_near: tuple[geo.Point, float] | None = None  # halt on reaching this distance of it


def nearest_threat(
    u: Unit,
    known: dict[str, Sighting],
    arm: str | None = None,
    include_routed: bool = False,
    units=None,
) -> tuple[Sighting | None, float]:
    best, bd = None, math.inf
    for s in known.values():
        if s.routed and not include_routed and s.arm != Arm.TRAIN.value:
            continue  # a bolted train is still there to be taken
        if arm is not None:
            a = s.arm if s.arm else (units[s.key].arm.value if units and s.ident >= 1 else None)
            if a != arm:
                continue
        d = geo.dist((u.x, u.y), (s.x, s.y))
        if d < bd or (d == bd and best is not None and s.key < best.key):
            best, bd = s, d
    return best, bd


def _facing_to(u: Unit, e) -> float | None:
    """The bearing from the body to `e`, or None (no turn) when `e` stands within a metre of
    it: a bearing of no length is not a direction (it would come out as north, which the 180°
    rotation of the field does not turn into south)."""
    if (e.x - u.x) ** 2 + (e.y - u.y) ** 2 < 1.0:
        return None
    return geo.bearing((u.x, u.y), (e.x, e.y))


def _objective_target(
    u: Unit, rt: BodyRT, known: dict[str, Sighting]
) -> tuple[Sighting | None, float]:
    if (
        rt.target
        and rt.target in known
        and (not known[rt.target].routed or known[rt.target].arm == Arm.TRAIN.value)
    ):
        s = known[rt.target]
        return s, geo.dist((u.x, u.y), (s.x, s.y))
    return nearest_threat(u, known)


def _slot(sim: Sim, u: Unit, rt: BodyRT) -> geo.Point | None:
    t = u.task
    if t is None:
        return None
    if (
        t.objective is not None
        and t.objective.kind in (RefKind.ENEMY, RefKind.FRIENDLY)
        and (sim.now >= rt.replan_at)
    ):
        p, _ = resolve_ref(sim, u.side, t.objective, near=(u.x, u.y), brigade=u.parent)
        if p is not None:
            if t.kind == TaskKind.SUPPORT:
                fid = sim.forces.resolve(t.objective.name or "", u.side)
                fac = _mean_facing(sim, fid) if fid else u.facing_deg
                p = geo.offset(p, fac + 180.0, SUPPORT_M)
            rt.slot = (p[0] + rt.offset[0], p[1] + rt.offset[1])
    return rt.slot


def _mean_facing(sim: Sim, fid: str) -> float:
    bs = [b for b in sim.forces.bodies(fid) if b.state != UnitState.DESTROYED]
    if not bs:
        return 0.0
    sx = sum(math.sin(math.radians(b.facing_deg)) for b in bs)
    cy = sum(math.cos(math.radians(b.facing_deg)) for b in bs)
    return math.degrees(math.atan2(sx, cy)) % 360.0


def _arrive_or_march(
    u: Unit, rt: BodyRT, slot: geo.Point | None, known, march_state, final_state, gait="walk"
) -> Plan:
    if slot is None or geo.dist((u.x, u.y), slot) <= ARRIVE_M:
        rt.phase = "arrived"
        e, d = nearest_threat(u, known)
        ft = known.get(rt.fire_target) if rt.fire_target else None
        if ft is not None and not ft.routed:
            e = ft  # a line in a firefight keeps facing its target; it does not wheel
        face = _facing_to(u, e) if e and d <= THREAT_FACE_M else None
        if (
            face is None
            and rt.origin is not None
            and slot is not None
            and geo.dist(rt.origin, slot) > ARRIVE_M
        ):
            face = geo.bearing(rt.origin, slot)  # face the way the formation came
        return Plan(goal=None, state=final_state, face=face)
    if rt.phase == "arrived":
        rt.phase = "march"
    return Plan(goal=slot, state=march_state, gait=gait)


def plan_infantry(sim: Sim, u: Unit, rt: BodyRT, t: Task, known) -> Plan:
    slot = _slot(sim, u, rt)
    deploy = DEPLOY_M[t.manner]
    final = t.state or UnitState.LINE
    if t.kind == TaskKind.RALLY:
        return Plan(goal=None, state=None)
    if t.kind == TaskKind.HOLD:
        return _arrive_or_march(u, rt, slot, known, UnitState.COLUMN, final)
    if t.kind == TaskKind.WITHDRAW or rt.phase == "fallback":
        return _withdraw(u, rt, slot, known, UnitState.COLUMN, UnitState.LINE)
    if t.kind == TaskKind.SCREEN:
        return _screen(u, rt, slot, known, UnitState.SKIRMISH, "walk")
    leaving = leaving_advance(sim, t)
    if leaving:  # fighting through: only what stands in the way is fought, and it is pressed
        known = in_the_way(u, slot, known)
    attacking = (
        (t.kind in (TaskKind.ATTACK, TaskKind.CHARGE) or t.on_contact == OnContact.PRESS or leaving)
        and not t.forbids(Forbid.ATTACK)
        and not t.forbids(Forbid.ENGAGE)
    )
    manner = Manner.RECKLESS if t.kind == TaskKind.CHARGE else t.manner
    e, d = _objective_target(u, rt, known)
    if e is not None and e.arm == Arm.TRAIN.value and attacking and d <= deploy + DEPLOY_SLACK_M:
        # wagons are not fought in line: the infantry marches in and takes them
        return Plan(goal=(e.x, e.y), state=None, assault=True, direct=True)
    if e is not None and d <= deploy + DEPLOY_SLACK_M:
        epos = (e.x, e.y)
        face = _facing_to(u, e)
        if (
            t.on_contact == OnContact.HALT or t.forbids(Forbid.ATTACK) or t.forbids(Forbid.ENGAGE)
        ) and not attacking:
            # "not to be drawn into any fight": it halts in line where it finds the enemy
            return Plan(goal=None, state=UnitState.LINE, face=face)
        if t.on_contact == OnContact.FALL_BACK:
            rt.phase = "fallback"
            rt.slot = geo.offset((u.x, u.y), geo.bearing(epos, (u.x, u.y)), FALL_BACK_M)
            return _withdraw(u, rt, rt.slot, known, UnitState.COLUMN, UnitState.LINE)
        if rt.phase not in ("closing", "firing", "assault"):
            rt.phase, rt.phase_since = "closing", sim.now
        halt = FIRE_HALT_M[manner]
        if rt.phase == "closing":
            if d > halt:
                return Plan(
                    goal=geo.toward(epos, (u.x, u.y), halt), state=UnitState.LINE, direct=True
                )
            rt.phase, rt.phase_since = "firing", sim.now
        if rt.phase == "firing":
            wait = ASSAULT_AFTER_MIN[manner]
            target = sim.forces.units[e.key]
            if (
                attacking
                and wait is not None
                and sim.now >= rt.attack_at
                and (sim.now - rt.phase_since >= wait or target.disorder >= ASSAULT_IF_DISORDER)
            ):
                rt.phase, rt.phase_since = "assault", sim.now
            else:
                if d > halt + 40.0:
                    rt.phase = "closing"
                return Plan(goal=None, state=UnitState.LINE, face=face)
        if sim.now < rt.attack_at:  # reorganising after a repulse or defeat: no assault
            rt.phase, rt.phase_since = "firing", sim.now
            return Plan(goal=None, state=UnitState.LINE, face=face)
        mult = DOUBLE_TIME if manner in (Manner.BOLD, Manner.RECKLESS) else 1.0
        return Plan(
            goal=epos,
            state=None
            if u.state == UnitState.COLUMN and manner == Manner.RECKLESS
            else UnitState.LINE,
            assault=True,
            speed_mult=mult,
            direct=True,
        )
    if rt.phase in ("closing", "firing", "assault"):
        rt.phase = "march"
    keep_line = u.state == UnitState.LINE and e is not None and d <= 1.5 * deploy
    plan = _arrive_or_march(
        u, rt, slot, known, UnitState.LINE if keep_line else UnitState.COLUMN, final
    )
    if e is not None and plan.goal is not None:
        plan.stop_near = ((e.x, e.y), deploy)  # halt at the deployment distance
    return plan


def _withdraw(u, rt, slot, known, march_state, final_state, gait="walk") -> Plan:
    if rt.cover_wait > 0:
        rt.cover_wait -= 1
        e, _ = nearest_threat(u, known)
        face = _facing_to(u, e) if e else None
        return Plan(goal=None, state=final_state, face=face)
    return _arrive_or_march(u, rt, slot, known, march_state, final_state, gait)


def _screen(u, rt, slot, known, state, gait) -> Plan:
    e, d = nearest_threat(u, known)
    if e is not None and d < SCREEN_MIN_M:
        away = geo.bearing((e.x, e.y), (u.x, u.y))
        return Plan(
            goal=geo.offset((e.x, e.y), away, SCREEN_BACK_M), state=state, gait=gait, direct=True
        )
    if (
        e is not None
        and d <= SCREEN_MAX_M - 200.0
        and slot is not None
        and geo.dist((e.x, e.y), slot) < d
    ):
        return Plan(goal=None, state=state, face=_facing_to(u, e))
    return _arrive_or_march(u, rt, slot, known, state, state, gait)


def plan_cavalry(sim: Sim, u: Unit, rt: BodyRT, t: Task, known) -> Plan:
    slot = _slot(sim, u, rt)
    if rt.phase == "reform":
        if sim.now - rt.phase_since < REFORM_MIN:
            return Plan(goal=None, state=UnitState.LINE)
        rt.phase = "march"
        rt.blown = False
    if t.kind == TaskKind.RALLY:
        return Plan(goal=None)
    if t.kind == TaskKind.HOLD:
        return _arrive_or_march(u, rt, slot, known, UnitState.COLUMN, t.state or UnitState.LINE)
    if t.kind == TaskKind.WITHDRAW or rt.phase == "fallback":
        return _withdraw(u, rt, slot, known, UnitState.COLUMN, UnitState.LINE, "trot")
    if t.kind == TaskKind.SCREEN:
        return _screen(u, rt, slot, known, UnitState.COLUMN, "walk")
    charging = (
        (
            t.kind in (TaskKind.CHARGE, TaskKind.ATTACK)
            or t.on_contact in (OnContact.ENGAGE, OnContact.PRESS)
        )
        and not t.forbids(Forbid.ATTACK)
        and not t.forbids(Forbid.ENGAGE)
    )
    if t.forbids(Forbid.CHARGE_FORMED_INFANTRY):
        # "do not charge the enemy's line": formed infantry, and a body whose arm is not
        # made out, is never a charge target (routed bodies and known horse or guns are)
        known = {
            k: s
            for k, s in known.items()
            if s.routed
            or (
                s.arm
                or (
                    sim.forces.units[k].arm.value
                    if s.ident >= 1 and k in sim.forces.units
                    else None
                )
            )
            in (Arm.CAVALRY.value, Arm.ARTILLERY.value, Arm.TRAIN.value)
        }
    leaving = leaving_advance(sim, t)
    if leaving:  # fighting through: only what stands in the way is charged
        known = in_the_way(u, slot, known)
    e, d = _objective_target(u, rt, known)
    reach = CAV_TROT_M if t.kind in (TaskKind.CHARGE, TaskKind.ATTACK) else CAV_ENGAGE_M
    if e is not None and d <= reach and charging and sim.command.shuns(u.id, e.key):
        alt = {k: v for k, v in known.items() if not sim.command.shuns(u.id, k)}
        e2, d2 = nearest_threat(u, alt)
        if e2 is None or d2 > reach:  # nothing else to charge: screen the square
            if rt.phase == "charge":
                rt.phase = "march"
            if leaving and slot is not None:  # or ride round it, on its way
                return Plan(
                    goal=detour(sim, u, slot, e), state=UnitState.COLUMN, gait="trot", direct=True
                )
            return _screen_square(u, e, d)
        e, d = e2, d2
    if e is not None and d <= reach:
        epos = (e.x, e.y)
        if t.on_contact == OnContact.FALL_BACK and t.kind != TaskKind.CHARGE:
            rt.phase = "fallback"
            rt.slot = geo.offset((u.x, u.y), geo.bearing(epos, (u.x, u.y)), FALL_BACK_M)
            return _withdraw(u, rt, rt.slot, known, UnitState.COLUMN, UnitState.LINE, "trot")
        if not charging or (t.on_contact == OnContact.HALT and t.kind == TaskKind.ADVANCE):
            return Plan(goal=None, state=UnitState.LINE, face=geo.bearing((u.x, u.y), epos))
        if sim.now < rt.attack_at:  # reorganising: hold, face the enemy, re-form
            if rt.phase == "charge":
                rt.phase = "march"
            return Plan(goal=None, state=UnitState.LINE, face=geo.bearing((u.x, u.y), epos))
        rt.phase = "charge"
        gait = "gallop" if d <= CAV_GALLOP_M and not rt.blown else "trot"
        if rt.blown:
            gait = "walk"
        return Plan(goal=epos, state=UnitState.LINE, gait=gait, assault=True, direct=True)
    if rt.phase == "charge":
        rt.phase = "march"
    gait = (
        "trot"
        if t.kind in (TaskKind.CHARGE, TaskKind.ATTACK)
        and slot is not None
        and (geo.dist((u.x, u.y), slot) <= CAV_TROT_M)
        else "walk"
    )
    return _arrive_or_march(u, rt, slot, known, UnitState.COLUMN, t.state or UnitState.LINE, gait)


def _screen_square(u: Unit, e: Sighting, d: float) -> Plan:
    """Keep SCREEN_SQUARE_MIN_M to SCREEN_SQUARE_MAX_M from a square it will not charge."""
    here, sq = (u.x, u.y), (e.x, e.y)
    if SCREEN_SQUARE_MIN_M <= d <= SCREEN_SQUARE_MAX_M:
        return Plan(goal=None, state=UnitState.LINE, face=geo.bearing(here, sq))
    goal = geo.offset(sq, geo.bearing(sq, here), SCREEN_SQUARE_AT_M)
    return Plan(
        goal=goal,
        state=UnitState.LINE,
        gait="trot" if d < SCREEN_SQUARE_MIN_M else "walk",
        direct=True,
    )


def plan_artillery(sim: Sim, u: Unit, rt: BodyRT, t: Task, known) -> Plan:
    slot = _slot(sim, u, rt)
    if t.kind == TaskKind.RALLY:
        return Plan(goal=None)
    e, d = _objective_target(u, rt, known)
    face = _facing_to(u, e) if e is not None else None
    if t.kind == TaskKind.WITHDRAW or rt.phase == "fallback":
        return _withdraw(u, rt, slot, known, UnitState.LIMBERED, UnitState.UNLIMBERED)
    at_slot = slot is None or geo.dist((u.x, u.y), slot) <= ARRIVE_M
    standoff = e is not None and d <= BOMBARD_STANDOFF_M and t.kind != TaskKind.HOLD
    if at_slot or standoff:
        rt.phase = "arrived" if at_slot else "deployed"
        return Plan(
            goal=None,
            state=UnitState.UNLIMBERED,
            face=face if e is not None and d <= THREAT_FACE_M else None,
        )
    rt.phase = "march"
    return Plan(goal=slot, state=UnitState.LIMBERED)


def plan_train(sim: Sim, u: Unit, rt: BodyRT, t: Task, known) -> Plan:
    """A train goes where its task sends it, in column, by road where it can; it never closes
    with an enemy (an ATTACK or CHARGE moves it to the objective like an ADVANCE) and holds
    nothing but its place."""
    slot = _slot(sim, u, rt)
    if t.kind == TaskKind.RALLY:
        return Plan(goal=None)
    return _arrive_or_march(u, rt, slot, known, UnitState.COLUMN, UnitState.COLUMN)


def _train_bolts(sim: Sim, u: Unit) -> bool:
    """Enemy cavalry within TRAIN_BOLT_M and no formed friendly body within TRAIN_COVER_M."""
    if not any(
        e.arm == Arm.CAVALRY and e.state != UnitState.ROUTED
        for e in sim.enemies_near(u, TRAIN_BOLT_M)
    ):
        return False
    return not any(
        v.side == u.side
        and v.id != u.id
        and v.arm != Arm.TRAIN
        and v.state not in (UnitState.ROUTED, UnitState.DESTROYED)
        and geo.dist((u.x, u.y), (v.x, v.y)) <= TRAIN_COVER_M
        for v in sim.forces.units.values()
    )


def drill(sim: Sim, u: Unit) -> None:
    """Advance one body by one minute of its drill: formation changes, turning, moving."""
    rt = sim.rt[u.id]
    rt.moved = 0.0
    if u.state == UnitState.DESTROYED or rt.melee_with is not None:
        return
    if u.arm == Arm.TRAIN and u.state != UnitState.ROUTED and _train_bolts(sim, u):
        rout(sim, u, "bolted at the enemy cavalry", "bolt")
    if u.state == UnitState.ROUTED:
        _flee(sim, u, rt)
        return
    known = sim.vision.known(u.parent)
    if u.arm == Arm.INFANTRY and _cavalry_reflex(sim, u, rt, known):
        return
    left = advance_timers(u, rt)
    if left <= 1e-9 or busy(rt):
        return
    t = u.task
    if t is None:
        return
    if t.until is not None and condition_met(sim, u.side, t.formation, t.until):
        sim.end_task(u)
        t = u.task
        if t is None:  # the sequel waits for its own start
            return
    if u.arm == Arm.INFANTRY:
        plan = plan_infantry(sim, u, rt, t, known)
    elif u.arm == Arm.CAVALRY:
        plan = plan_cavalry(sim, u, rt, t, known)
    elif u.arm == Arm.TRAIN:
        plan = plan_train(sim, u, rt, t, known)
    else:
        plan = plan_artillery(sim, u, rt, t, known)
    if plan.state is not None and plan.state != u.state:
        order_change(u, rt, plan.state)
        left = advance_timers(u, rt, left)
        if left <= 1e-9 or busy(rt):
            return
    if plan.goal is None:
        rt.route, rt.route_goal = [], None
        if plan.face is not None:
            order_turn(u, rt, plan.face)
            advance_timers(u, rt, left)
        return
    if u.state == UnitState.UNLIMBERED:
        order_change(u, rt, UnitState.LIMBERED)
        advance_timers(u, rt, left)
        return
    _move(sim, u, rt, plan, left)


def _cavalry_reflex(sim: Sim, u: Unit, rt: BodyRT, known: dict[str, Sighting]) -> bool:
    """Infantry against enemy cavalry (the design spec's square rule, narrowed).
    With known enemy cavalry within SQUARE_CAV_M and no friendly cavalry within
    SQUARE_COVER_M: a body in a wood or village stays in its cover; Grenzer and skirmishers
    evade (toward cover or a friendly line); a body forms square only when a flank is exposed;
    a supported line stays in line and fires. The response lasts until no enemy cavalry has
    been within SQUARE_CLEAR_M for SQUARE_CLEAR_MIN minutes; a square then re-forms as it was.
    True when the reflex used the body's minute."""
    seen = sim.command.cav_seen
    fresh = {k: s for k, s in known.items() if sim.now - s.seen_at <= CAV_SIGHT_FRESH_MIN}
    cav, dc = nearest_threat(u, fresh, arm="cavalry", units=sim.forces.units)
    squared = u.state == UnitState.SQUARE or rt.change_to == UnitState.SQUARE.value
    active = squared or u.id in seen
    if active and cav is not None and dc <= SQUARE_CLEAR_M:
        seen[u.id] = sim.now
    lately = sim.now - seen.get(u.id, -SQUARE_CLEAR_MIN) < SQUARE_CLEAR_MIN
    if active and not lately:  # the threat has gone
        seen.pop(u.id, None)
        if (
            u.state == UnitState.SQUARE
            and rt.change_left == 0.0
            and not (u.task is not None and u.task.state == UnitState.SQUARE)
        ):
            order_change(u, rt, UnitState(rt.prev_state or "line"))
            rt.prev_state = None
        return False
    if squared:
        left = advance_timers(u, rt)  # stand in square
        t = u.task
        if (
            left > 1e-9
            and not busy(rt)
            and u.state == UnitState.SQUARE
            and t is not None
            and leaving_advance(sim, t)
        ):  # a square fighting through marches on
            slot = _slot(sim, u, rt)
            if slot is not None and geo.dist((u.x, u.y), slot) > ARRIVE_M:
                block, _ = nearest_threat(u, in_the_way(u, slot, known))
                goal = slot if block is None else detour(sim, u, slot, block)
                _move(sim, u, rt, Plan(goal=goal, direct=block is not None), left)
        return True
    if not active and (
        cav is None or dc > SQUARE_CAV_M or sim.friendly_cavalry_near(u, SQUARE_COVER_M)
    ):
        return False
    cover = sim.world.cover(u.x, u.y) in IN_COVER
    evader = u.kind == UnitKind.GRENZER or u.state == UnitState.SKIRMISH
    if not active and not cover and not evader and not _flank_exposed(sim, u):
        return False  # a steady line with covered flanks receives cavalry in line
    seen[u.id] = seen.get(u.id, sim.now)
    if cav is None:  # out of sight lately: stand
        advance_timers(u, rt)
        return True
    if cover:
        rt.route, rt.route_goal = [], None
        if not busy(rt):
            order_turn(u, rt, geo.bearing((u.x, u.y), (cav.x, cav.y)))
        advance_timers(u, rt)
        return True
    if evader:
        _evade(sim, u, rt, cav)
        return True
    rt.prev_state = u.state.value
    rt.turn_to = None
    order_change(u, rt, UnitState.SQUARE)
    advance_timers(u, rt)
    return True


def _flank_exposed(sim: Sim, u: Unit) -> bool:
    """A flank is covered when a formed friendly body (not skirmishers) lies on that side of the
    body's front within SQUARE_FLANK_M of its flank (centre distance less half the friend's
    frontage); exposed if either is not."""
    th = math.radians(u.facing_deg)
    rx, ry = math.cos(th), -math.sin(th)  # right-hand axis
    half = frontage(u) / 2.0
    friends = [
        v
        for v in sim.forces.units.values()
        if v.side == u.side and v.id != u.id and v.state in FORMED
    ]
    for side in (1.0, -1.0):
        fx, fy = u.x + side * half * rx, u.y + side * half * ry
        if not any(
            side * ((v.x - u.x) * rx + (v.y - u.y) * ry) > 0.0
            and math.hypot(v.x - fx, v.y - fy) - frontage(v) / 2.0 <= SQUARE_FLANK_M
            for v in friends
        ):
            return True
    return False


def _refuge(sim: Sim, u: Unit) -> tuple[geo.Point | None, bool]:
    """The nearest wood or village cell, or friendly formed line or square (whichever is
    nearer), within EVADE_REFUGE_M: (point, is a friendly body)."""
    w = sim.world
    t = w.terrain
    cell = t.cell_m
    i0, j0 = w.cell_ij(u.x - EVADE_REFUGE_M, u.y - EVADE_REFUGE_M)
    i1, j1 = w.cell_ij(u.x + EVADE_REFUGE_M, u.y + EVADE_REFUGE_M)
    win = np.asarray(t.cover)[i0 : i1 + 1, j0 : j1 + 1]
    best: tuple[float, geo.Point, bool] | None = None
    ii, jj = np.nonzero(np.isin(win, [int(c) for c in IN_COVER]))
    if ii.size:
        xs = t.origin[0] + (jj + j0 + 0.5) * cell
        ys = t.origin[1] + (ii + i0 + 0.5) * cell
        d = np.hypot(xs - u.x, ys - u.y)
        # nearest; ties by distance to the field's centre, then by side (kept by the 180°
        # rotation), not by raster order
        side = (xs - u.x) * (w.cy - u.y) - (ys - u.y) * (w.cx - u.x)
        k = int(np.lexsort((side, np.hypot(xs - w.cx, ys - w.cy), d))[0])
        if d[k] <= EVADE_REFUGE_M:
            best = (float(d[k]), (float(xs[k]), float(ys[k])), False)
    for v in sorted(sim.forces.units.values(), key=lambda v: v.id):
        if (
            v.side != u.side
            or v.id == u.id
            or v.arm != Arm.INFANTRY
            or v.kind == UnitKind.GRENZER
            or v.state not in (UnitState.LINE, UnitState.SQUARE)
        ):
            continue
        d = math.hypot(v.x - u.x, v.y - u.y)
        if d <= EVADE_REFUGE_M and (best is None or d < best[0]):
            best = (d, (v.x, v.y), True)
    return (best[1], best[2]) if best else (None, False)


def _evade(sim: Sim, u: Unit, rt: BodyRT, cav: Sighting) -> None:
    """Grenzer and skirmishers do not form square: they make for cover or a friendly line
    (at double time), or fall back from the cavalry."""
    left = advance_timers(u, rt)
    if left <= 1e-9 or busy(rt):
        return
    goal, friend = _refuge(sim, u)
    stop = None
    if goal is None:
        goal = geo.offset((u.x, u.y), geo.bearing((cav.x, cav.y), (u.x, u.y)), EVADE_AWAY_M)
    elif friend:
        if geo.dist((u.x, u.y), goal) <= EVADE_STOP_M + 1.0:
            order_turn(u, rt, geo.bearing((u.x, u.y), (cav.x, cav.y)))
            advance_timers(u, rt, left)
            return
        stop = (goal, EVADE_STOP_M)
    _move(sim, u, rt, Plan(goal=goal, gait="walk", speed_mult=DOUBLE_TIME, stop_near=stop), left)


def boundaries(sim: Sim, u: Unit, rt: BodyRT):
    """Movement limits from the task's ADVANCE_BEYOND:<feature> prohibitions ("go no farther
    than the road", "not beyond the village"), as tests (x0, y0, x1, y1) -> may it move so.
    A line feature (road, stream, ridge) is a line it may not cross. A place (village, wood,
    height, point) bounds the advance along the line from where the body stood when the task
    reached it (`rt.origin`) through the place: no farther along it than the place's far
    edge; a body already beyond may only come back. Unknown features bound nothing."""
    t = u.task
    if t is None or not t.forbid:
        return []
    out = []
    w = sim.world
    origin = rt.origin or (u.x, u.y)
    for f in t.forbid:
        what, _, name = f.partition(":")
        if what != Forbid.ADVANCE_BEYOND.value or not name or not w.has_feature(name):
            continue
        feat = w.feature(name)
        if feat.geometry_kind == GeometryKind.POLYLINE and len(feat.coords) > 1:
            segs = list(zip(feat.coords, feat.coords[1:], strict=False))

            def no_cross(x0, y0, x1, y1, segs=segs) -> bool:
                return not any(geo.segments_cross((x0, y0), (x1, y1), a, b) for a, b in segs)

            out.append(no_cross)
            continue
        c = w.anchor(feat)
        d = geo.dist(origin, c)
        if d < 1.0:
            continue  # it stands on the place: no direction to bound
        ax, ay = (c[0] - origin[0]) / d, (c[1] - origin[1]) / d
        limit = max((p[0] - origin[0]) * ax + (p[1] - origin[1]) * ay for p in feat.coords)

        def not_beyond(x0, y0, x1, y1, ax=ax, ay=ay, limit=limit, o=origin) -> bool:
            s1 = (x1 - o[0]) * ax + (y1 - o[1]) * ay
            return s1 <= limit or s1 <= (x0 - o[0]) * ax + (y0 - o[1]) * ay

        out.append(not_beyond)
    return out


def _move(sim: Sim, u: Unit, rt: BodyRT, plan: Plan, minutes: float) -> None:
    w = sim.world
    goal = plan.goal
    assert goal is not None
    here = (u.x, u.y)
    while rt.via and geo.dist(here, rt.via[0]) <= VIA_REACHED_M:
        rt.via.pop(0)
        rt.route_goal = None
    target = rt.via[0] if rt.via and not plan.direct else goal
    need = (
        rt.route_goal is None
        or geo.dist(rt.route_goal, target) > 50.0
        or not rt.route
        or (rt.blocked and sim.now >= rt.replan_at)
    )
    if need:
        prof = profile_for(u, plan.gait, plan.state)
        if plan.direct and w.segment_passable(prof, here, target):
            rt.route = [target]
        else:
            _, rt.route = w.path_cost(here, target, prof)
            if not rt.route:
                rt.route = [target] if w.segment_passable(prof, here, target) else []
        rt.route_goal = target
        rt.replan_at = sim.now + REPLAN_MIN
        rt.blocked = 0
    stop = plan.stop_near
    bounds = boundaries(sim, u, rt)

    def check(nx: float, ny: float) -> bool:
        """May the body's centre go to (nx, ny)? Not into the circle it was told to stop at,
        nor across a prohibited boundary (ADVANCE_BEYOND): it halts at either (follow_route
        bisects the sub-step). Enemy bodies are not checked here: every body moves at once,
        so whom it meets, and where, is decided after all have moved (resolve_moves)."""
        if stop is not None and (stop[0][0] - nx) ** 2 + (stop[0][1] - ny) ** 2 < stop[1] ** 2:
            return False
        return not bounds or all(b(u.x, u.y, nx, ny) for b in bounds)

    t0 = 1.0 - minutes
    snap_body(w, u)  # the path starts on the lattice it steps on (follow_route)
    trace: list = []
    route0 = list(rt.route)
    pace0 = rt.pace
    start = (t0, u.x, u.y, u.facing_deg, 0)
    moved = follow_route(w, u, rt, minutes, plan.gait, plan.speed_mult, check=check, trace=trace)
    no_pursuit = u.task is not None and (
        u.task.forbids(Forbid.PURSUE) or u.task.forbids(Forbid.ENGAGE)
    )
    intent = MoveIntent(
        trace=[start] + [(t0 + t, x, y, f, k) for t, x, y, f, k in trace],
        route0=route0,
        plan=plan,
        pace0=pace0,
        moved=moved,
        constrained=True,
        no_pursuit=no_pursuit,
    )
    if sim.moves is not None:
        sim.moves[u.id] = intent  # resolved with every other body's (Sim.step)
    else:
        resolve_moves(sim, {u.id: intent})  # alone, against the field as it stands


# ---------------------------------------------------------------------------
# Movement, and where the paths meet


@dataclass
class MoveIntent:
    """One body's movement this minute as planned against the field at the start of the
    minute (Sim.step's movement phase): its path in time, kept until resolve_moves has
    decided where it meets the enemy."""

    trace: list[tuple[float, float, float, float, int]]  # (minute, x, y, facing, passed)
    route0: list = field(default_factory=list)  # its route before it moved
    plan: Plan | None = None
    pace0: str = "halt"  # its pace before it moved
    moved: float = 0.0
    constrained: bool = False  # it closes on the enemy only to contact (a fleeing body is not)
    no_pursuit: bool = False  # its task forbids pursuit or engagement


def _finish_move(
    sim: Sim, u: Unit, rt: BodyRT, plan: Plan, moved: float, contact: list[str]
) -> None:
    """What follows from a minute's movement: a melee asked for (the contact it reached),
    the gallop count and the gait."""
    gait = plan.gait
    rt.moved = moved
    if contact:
        rt.route = []
        units = sim.forces.units
        first = min(contact, key=lambda k: (k != rt.target, _dist2(u, units[k]), k))
        sim.request_melee(u, units[first], gait)
    if u.arm == Arm.CAVALRY and moved > 0:
        if gait == "gallop":
            rt.gallop_min += 1
            if rt.gallop_min > GALLOP_MAX_MIN and not rt.blown:
                rt.blown = True
                add_disorder(u, BLOWN_DISORDER)
        else:
            rt.gallop_min = 0
    rt.gait = gait if moved > 0 else "halt"


def _at(tr: list, t: float) -> tuple[float, float]:
    """A body's position at minute `t` of the tick on its path (still before and after)."""
    if t <= tr[0][0]:
        return tr[0][1], tr[0][2]
    for k in range(1, len(tr)):
        t1 = tr[k][0]
        if t <= t1:
            t0 = tr[k - 1][0]
            f = 0.0 if t1 - t0 <= 1e-12 else (t - t0) / (t1 - t0)
            return (
                tr[k - 1][1] + (tr[k][1] - tr[k - 1][1]) * f,
                tr[k - 1][2] + (tr[k][2] - tr[k - 1][2]) * f,
            )
    return tr[-1][1], tr[-1][2]


def _first_meeting(tr_i: list, tr_j: list, r: float) -> float | None:
    """The first minute at which body i, moving along tr_i, would come within `r` of body j
    (moving along tr_j) while closing on it: where i must halt. None if it never does."""
    times = sorted({p[0] for p in tr_i} | {p[0] for p in tr_j} | {1.0})
    lo = tr_i[0][0]
    times = [t for t in times if t >= lo]
    r2 = r * r
    for a, b in itertools.pairwise(times):
        if b - a <= 1e-12:
            continue
        ia, ib = _at(tr_i, a), _at(tr_i, b)
        dix, diy = ib[0] - ia[0], ib[1] - ia[1]
        if dix * dix + diy * diy <= 1e-18:
            continue  # i stands (or wheels) here: it does not close
        ja, jb = _at(tr_j, a), _at(tr_j, b)
        d0x, d0y = ja[0] - ia[0], ja[1] - ia[1]
        wx, wy = (jb[0] - ja[0]) - dix, (jb[1] - ja[1]) - diy
        # within reach: |D0 + s W|^2 <= r^2
        qa, qb, qc = wx * wx + wy * wy, 2.0 * (d0x * wx + d0y * wy), d0x * d0x + d0y * d0y - r2
        if qa <= 1e-18:
            if qc > 0.0:
                continue
            s1, s2 = 0.0, 1.0
        else:
            disc = qb * qb - 4.0 * qa * qc
            if disc < 0.0:
                continue
            sq = math.sqrt(disc)
            s1, s2 = (-qb - sq) / (2.0 * qa), (-qb + sq) / (2.0 * qa)
        # closing: i's own motion takes it nearer j, dI . D(s) > 0
        c0, c1 = dix * d0x + diy * d0y, dix * wx + diy * wy
        if abs(c1) <= 1e-18:
            if c0 <= 0.0:
                continue
            k1, k2 = 0.0, 1.0
        elif c1 > 0.0:
            k1, k2 = -c0 / c1, 1.0
        else:
            k1, k2 = 0.0, -c0 / c1
        lower = max(0.0, s1, k1)
        upper = min(1.0, s2, k2)
        if lower <= upper and (lower < upper or c0 + c1 * lower > 0.0):
            return a + lower * (b - a)
    return None


def _cut(tr: list, t: float) -> list:
    """The path halted at minute t: as far as it got, standing there for the rest. A point
    reached at t itself is kept (a wheel finished at the moment of contact is done), so a
    halt at the very start of a leg does not depend on the last bit of t. The path is in
    offsets from the field's centre (resolve_moves) and the halt is set on the position
    lattice, so the halt of a path and of its image are images exactly."""
    out = [p for p in tr if p[0] <= t]
    if not out:
        return [tr[0]]
    nxt = next((p for p in tr if p[0] >= t), None)
    x, y = (geo.snap_m(v) for v in _at(tr, t))
    face = (
        nxt[3] if nxt is not None and (nxt[1], nxt[2]) != (out[-1][1], out[-1][2]) else out[-1][3]
    )
    out.append((t, x, y, face, out[-1][4]))
    return out


def _length(tr: list) -> float:
    return sum(math.hypot(b[1] - a[1], b[2] - a[2]) for a, b in itertools.pairwise(tr))


def resolve_moves(sim: Sim, moves: dict[str, MoveIntent], start: dict | None = None) -> None:
    """Simultaneous movement. Every body has moved its minute
    along its path as planned against the field at the start of the minute, without regard to
    the enemy's bodies (MoveIntent). Here the paths are run together in time: a body that,
    closing on an enemy body, would come within contact (CONTACT_M; SQUARE_RECOGNISE_M for
    cavalry going in at a steady square) halts at the moment it does, wherever that enemy body
    is at that moment, and an assault records the contact it reached (not a routed body that
    is not its target: it stops short of fugitives in its path). Two bodies closing on
    each other halt at the same moment, so they meet where their speeds put them, whichever id
    sorts first. Halts are taken earliest first, and each halt can only delay the others'.
    `start`: per body, its state and whether it stood in a steady square at the start of the
    minute (Sim.step); None reads the field as it stands (a single body moved outside a tick,
    the tests).

    The paths are taken as offsets from the field's centre. Every point of a path is on Sim._snap's
    lattice (movement.follow_route), so the offsets are exact, the offsets of a path's image under
    the 180° rotation are exactly their negatives, and every quantity below (positions between
    points, meeting times, distances) is computed by operations that commute with the sign: a game
    and its rotated image meet, halt and choose contacts at exactly the same minutes and image
    places."""
    units = sim.forces.units
    if start is None:
        start = {uid: (v.state, steady_square(v, busy(sim.rt[uid]))) for uid, v in units.items()}
    cx, cy = sim.world.centre
    paths: dict[str, list] = {
        uid: [(t, x - cx, y - cy, f, k) for t, x, y, f, k in m.trace] for uid, m in moves.items()
    }
    for uid, v in units.items():
        if uid not in paths and v.state != UnitState.DESTROYED:
            paths[uid] = [(0.0, v.x - cx, v.y - cy, v.facing_deg, 0)]
    reach_out = {
        uid: max((math.hypot(p[1] - tr[0][1], p[2] - tr[0][2]) for p in tr), default=0.0)
        for uid, tr in paths.items()
    }
    r_max = max(CONTACT_M, SQUARE_RECOGNISE_M)
    pairs: dict[str, dict[str, float]] = {}  # mover -> enemy -> its contact distance
    for uid, m in moves.items():
        if not m.constrained:
            continue
        u = units[uid]
        cav_in = m.plan is not None and m.plan.assault and u.arm == Arm.CAVALRY
        x0, y0 = paths[uid][0][1], paths[uid][0][2]
        mine: dict[str, float] = {}
        for eid, tr in paths.items():
            e = units[eid]
            if e.side == u.side or start.get(eid, (e.state,))[0] == UnitState.DESTROYED:
                continue
            gap = math.hypot(tr[0][1] - x0, tr[0][2] - y0) - reach_out[uid] - reach_out[eid]
            if gap > r_max:
                continue
            sq = start.get(eid, (None, False))[1]
            shun = cav_in and sim.command.shuns(uid, eid)
            mine[eid] = SQUARE_RECOGNISE_M if cav_in and not shun and sq else CONTACT_M
        pairs[uid] = mine
    halted: dict[str, tuple[float, list[str]]] = {}
    cache: dict[tuple[str, str], float | None] = {}
    while True:
        first: dict[str, tuple[float, list[str]]] = {}
        for uid, mine in pairs.items():
            if uid in halted:
                continue
            for eid, r in mine.items():
                if (uid, eid) not in cache:
                    cache[(uid, eid)] = _first_meeting(paths[uid], paths[eid], r)
                t = cache[(uid, eid)]
                if t is None:
                    continue
                best = first.get(uid)
                if best is None or t < best[0] - 1e-9:
                    first[uid] = (t, [eid])
                elif t <= best[0] + 1e-9:
                    best[1].append(eid)
        if not first:
            break
        t_star = min(t for t, _ in first.values())
        now = [uid for uid, (t, _) in first.items() if t <= t_star + 1e-9]
        for uid in now:
            t, met = first[uid]
            halted[uid] = (t, sorted(met))
            paths[uid] = _cut(paths[uid], t)
        for key in [k for k in cache if k[1] in now or k[0] in now]:
            del cache[key]
    for uid in sorted(halted):  # every body where it halted, before any contact is chosen
        m, u, rt, tr = moves[uid], units[uid], sim.rt[uid], paths[uid]
        u.x, u.y, u.facing_deg = cx + tr[-1][1], cy + tr[-1][2], tr[-1][3]
        rt.route = m.route0[tr[-1][4] :]
        m.moved = _length(tr)
        if m.moved <= 0.0:
            rt.pace = m.pace0
    for uid in sorted(moves):
        m = moves[uid]
        u, rt = units[uid], sim.rt[uid]
        if not m.constrained:
            continue
        contact = []
        if uid in halted and m.plan is not None and m.plan.assault:
            for eid in halted[uid][1]:
                if sim.command.shuns(uid, eid) and u.arm == Arm.CAVALRY:
                    continue
                if start.get(eid, (units[eid].state,))[0] != UnitState.ROUTED or (
                    eid == rt.target and not m.no_pursuit
                ):
                    contact.append(eid)
        _finish_move(sim, u, rt, m.plan, m.moved, contact)


def _dist2(a: Unit, b: Unit) -> float:
    return (a.x - b.x) ** 2 + (a.y - b.y) ** 2


def _flee(sim: Sim, u: Unit, rt: BodyRT) -> None:
    near = sim.enemies_near(u, ROUT_FLEE_CLEAR_M)
    if not near:
        rt.route = []
        return
    e = min(near, key=lambda v: ((v.x - u.x) ** 2 + (v.y - u.y) ** 2, v.id))
    hq = sim.command.army_hq(u.side)

    def unit(x: float, y: float) -> tuple[float, float]:
        n = math.hypot(x, y)
        return (x / n, y / n) if n > 0.0 else (0.0, 1.0)  # no length: north, as bearing

    # blend away-from-enemy with toward-own-hq, then try deviations if blocked. The
    # directions are unit vectors of the differences themselves and a deviation turns the
    # vector, the step is set on the position lattice: the image of a flight under the 180°
    # rotation is then exactly the image (through bearings, sines and cosines it is not, and
    # at a bank one image could run where the other cannot)
    ax, ay = unit(u.x - e.x, u.y - e.y)
    hx, hy = unit(hq[0] - u.x, hq[1] - u.y) if geo.dist((u.x, u.y), hq) > 1 else (ax, ay)
    bx, by = unit(ax * 2 + hx, ay * 2 + hy)

    for dev in (0, 30, -30, 60, -60, 90, -90):
        c, s = math.cos(math.radians(dev)), math.sin(math.radians(dev))  # clockwise by dev
        g = (
            u.x + geo.snap_m(ROUT_STEP_M * (bx * c + by * s)),
            u.y + geo.snap_m(ROUT_STEP_M * (by * c - bx * s)),
        )
        if sim.world.passable(g[0], g[1], arm_class(u)) and sim.world.segment_passable(
            profile_for(u, "trot"), (u.x, u.y), g
        ):
            rt.route = [g]
            trace: list = []
            snap_body(sim.world, u)
            first = (0.0, u.x, u.y, u.facing_deg, 0)
            rt.moved = follow_route(sim.world, u, rt, 1.0, "trot", 1.0, trace=trace)
            if sim.moves is not None:  # others close on it where it is as it flees
                sim.moves[u.id] = MoveIntent(trace=[first, *trace], moved=rt.moved)
            return
    rt.route = []
