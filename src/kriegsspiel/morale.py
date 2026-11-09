"""Morale, rout, rally and recovery. Every number here is an assumption unless
marked "spec"; the spec fixes only the starting morale (60 + 8 x quality) and the fatigue rates."""

from __future__ import annotations

from typing import TYPE_CHECKING

from . import geometry as geo
from .movement import apply_fatigue
from .types import Arm, TaskKind, Unit, UnitState

if TYPE_CHECKING:
    from .sim import Sim

# ---------------------------------------------------------------------------
# Constants (assumptions; period sources put the breaking point of a battalion at
# roughly a third of its men lost in a short time)
START_MORALE_BASE = 60.0  # spec: starting morale is 60 + 8 x quality
START_MORALE_PER_QUALITY = 8.0
MORALE_PER_PCT_LOSS = 1.5  # morale points lost per 1% of starting strength lost
DISORDER_PER_PCT_LOSS = 1.0
ROUT_MORALE = 25.0  # below this a body routs
NEIGHBOUR_ROUT_M = 300.0
NEIGHBOUR_ROUT_MORALE = 5.0  # a friend breaking nearby costs this much morale
DESTROYED_FRACTION = 0.10  # a body under 10% of its start strength is gone
DESTROYED_MIN_MEN = 5  # floor under the fraction: a 50-man company goes at 5, not at 30
MORALE_RECOVER = 0.2  # per quiet minute, up to the starting value
DISORDER_RECOVER = 2.0  # per minute not engaged
ROUTED_RECOVER = 0.5  # per minute with no enemy within ROUTED_SAFE_M
RALLY_RECOVER = 2.0  # per minute under a RALLY task
ROUTED_SAFE_M = 800.0
RALLY_CLEAR_M = 600.0
RALLY_MORALE = 45.0  # can re-form under a RALLY task
SELF_RALLY_MORALE = 55.0  # re-forms on its own
RALLY_DISORDER = 50.0  # a rallied body starts disordered
ROUT_MORALE_HIT = 15.0  # assumption: breaking costs this much morale, and leaves at most
# ROUT_MORALE, so a body that broke from a melee is as shaken as one that broke from losses
# Recovery clocks, minutes after the event (defend = may rally and stand, attack = may strike
# again): the floors of Reisswitz 1824 section 52 as read here, 4/6 after a repulse, 6/12
# after a defeat, 10/20 after a complete defeat. Assumption: the translation's timing is
# ambiguous; "defeat" is a lost melee or a rout under fire, "complete" is broken at impact.
RECOVERY_MIN = {
    "repulse": (4, 6),
    "defeat": (6, 12),
    "complete": (10, 20),
    "bolt": (2, 2),
}  # bolt: a train's drivers (assumption)
# Trains (design assumption): a bolted train may be rallied by a formed friendly body
# within TRAIN_RALLY_M once no enemy cavalry is within TRAIN_BOLT_M (drill.TRAIN_BOLT_M).
TRAIN_RALLY_M = 200.0


def start_morale(u: Unit) -> float:
    return START_MORALE_BASE + START_MORALE_PER_QUALITY * u.quality  # spec


def set_clock(sim: Sim, u: Unit, severity: str) -> None:
    """Start the recovery clock of `u` after a repulse, defeat or complete defeat."""
    rt = sim.rt[u.id]
    defend, attack = RECOVERY_MIN[severity]
    rt.rally_at = max(rt.rally_at, sim.now + defend)
    rt.attack_at = max(rt.attack_at, sim.now + attack)


def rout(sim: Sim, u: Unit, cause: str, severity: str = "defeat") -> None:
    if u.state in (UnitState.ROUTED, UnitState.DESTROYED):
        return
    rt = sim.rt[u.id]
    u.morale = max(0.0, min(ROUT_MORALE, u.morale - ROUT_MORALE_HIT))
    set_clock(sim, u, severity)
    rt.pursued = False
    u.state = UnitState.ROUTED
    rt.change_to, rt.change_left, rt.turn_to = None, 0.0, None
    rt.route, rt.route_goal = [], None
    rt.phase = "routed"
    sim.release_melee(u)
    sim.routed_now.append(u.id)
    sim.emit(
        "rout",
        unit=u.id,
        side=u.side,
        cause=cause,
        severity=severity,
        men=u.men,
        morale=round(u.morale, 3),
        x=round(u.x, 1),
        y=round(u.y, 1),
    )


def destroy(sim: Sim, u: Unit, cause: str) -> None:
    u.state = UnitState.DESTROYED
    sim.release_melee(u)
    sim.emit("destroyed", unit=u.id, side=u.side, cause=cause, men=u.men)


def _rally(sim: Sim, u: Unit) -> None:
    """A routed body re-forms, disordered, and takes up its formation's standing task again as
    a fresh leg from where it rallied: same place in the formation (slot), a new route, its
    origin here. An offensive (ATTACK, CHARGE, ADVANCE) is resumed too: the recovery clock
    (`attack_at`) still bars a charge or an assault until it runs out, and a new order replaces
    the task as before. (Replacing an offensive task with a HOLD where the body rallied would
    leave rallied cavalry standing still to the end of the day.)"""
    rt = sim.rt[u.id]
    u.state = UnitState.LIMBERED if u.arm == Arm.ARTILLERY else UnitState.COLUMN
    u.disorder = max(u.disorder, RALLY_DISORDER)
    rt.phase, rt.phase_since = "march", sim.now
    rt.route, rt.route_goal = [], None
    rt.pursued = False
    rt.origin = (u.x, u.y)
    rt.replan_at = sim.now
    sim.emit(
        "rally",
        unit=u.id,
        side=u.side,
        morale=round(u.morale, 3),
        resumed=u.task.kind.value if u.task is not None else None,
    )


def _train_steadied(sim: Sim, u: Unit) -> bool:
    from .drill import TRAIN_BOLT_M  # drill imports morale (rout)

    if any(
        e.arm == Arm.CAVALRY and e.state != UnitState.ROUTED
        for e in sim.enemies_near(u, TRAIN_BOLT_M)
    ):
        return False
    return any(
        v.side == u.side
        and v.id != u.id
        and v.arm != Arm.TRAIN
        and v.state not in (UnitState.ROUTED, UnitState.DESTROYED)
        and geo.dist((u.x, u.y), (v.x, v.y)) <= TRAIN_RALLY_M
        for v in sim.forces.units.values()
    )


def add_disorder(u: Unit, n: float) -> None:
    """Disorder rises by n, to at most 100."""
    u.disorder = min(100.0, u.disorder + n)


def morale_phase(sim: Sim) -> None:
    from .combat import guns_serviceable  # combat imports morale (rout, set_clock)

    for uid, loss in sorted(sim.tick_losses.items()):
        u = sim.forces.units[uid]
        if u.state == UnitState.DESTROYED or loss <= 0:
            continue
        start = max(1, sim.rt[uid].start_men)
        pct = 100.0 * loss / start
        u.morale = max(0.0, u.morale - MORALE_PER_PCT_LOSS * pct)
        add_disorder(u, DISORDER_PER_PCT_LOSS * pct)
    for u in sim.forces.units.values():
        if u.state == UnitState.DESTROYED:
            continue
        start = sim.rt[u.id].start_men
        gone = u.men <= max(DESTROYED_MIN_MEN, DESTROYED_FRACTION * start)
        if u.arm == Arm.ARTILLERY:
            gone = gone or guns_serviceable(u) == 0
        if gone:
            destroy(sim, u, "losses")
        elif u.state != UnitState.ROUTED and u.morale < ROUT_MORALE:
            rout(sim, u, "morale")
    # a friend breaking nearby (one wave per tick; cascades show on later ticks)
    for rid in list(sim.routed_now):
        r = sim.forces.units[rid]
        for u in sim.forces.units.values():
            if (
                u.side == r.side
                and u.id != rid
                and u.state not in (UnitState.ROUTED, UnitState.DESTROYED)
                and geo.dist((u.x, u.y), (r.x, r.y)) <= NEIGHBOUR_ROUT_M
            ):
                u.morale = max(0.0, u.morale - NEIGHBOUR_ROUT_MORALE)


def recovery_phase(sim: Sim) -> None:
    for u in sim.forces.units.values():
        if u.state == UnitState.DESTROYED:
            continue
        rt = sim.rt[u.id]
        quiet = not u.engaged and sim.tick_losses.get(u.id, 0.0) == 0.0
        apply_fatigue(u, rt, sim.now)  # once a minute, from what it did
        if (
            u.state == UnitState.ROUTED
            and u.arm == Arm.TRAIN
            and sim.now >= rt.rally_at
            and _train_steadied(sim, u)
        ):
            u.morale = max(u.morale, RALLY_MORALE)
            _rally(sim, u)
            continue
        if u.state == UnitState.ROUTED:
            near = sim.enemies_near(u, ROUTED_SAFE_M)
            rallying = u.task is not None and u.task.kind == TaskKind.RALLY
            if not near:
                u.morale = min(
                    start_morale(u), u.morale + (RALLY_RECOVER if rallying else ROUTED_RECOVER)
                )
            clear = not sim.enemies_near(u, RALLY_CLEAR_M)
            if (
                clear
                and sim.now >= rt.rally_at
                and (u.morale >= SELF_RALLY_MORALE or (rallying and u.morale >= RALLY_MORALE))
            ):
                _rally(sim, u)
            continue
        if not u.engaged:
            u.disorder = max(0.0, u.disorder - DISORDER_RECOVER)
        if quiet:
            u.morale = min(start_morale(u), u.morale + MORALE_RECOVER)
