"""Combat physics: musketry, artillery, melee.

Rates are expected casualties per minute; the sim turns them into whole men by stochastic
rounding from a seeded stream. Numbers are the spec's unless marked "assumption".
"""

from __future__ import annotations

import math

import numpy as np

from .command import place
from .geometry import angle_diff, aspect, bearing, dist, snap_m
from .morale import add_disorder, rout, set_clock
from .movement import arm_class, busy
from .types import Arm, Cover, Forbid, Unit, UnitKind, UnitState

# ---------------------------------------------------------------------------
# Musketry
MUSKET_RANGE_M = 250.0
# (range m, hits per man firing per minute). Calibration values, not measurements.
# The spec's table, [(25, 0.008), (50, 0.005), (100, 0.003), (150, 0.0015), (200, 0.0007),
# (250, 0.0003)], has two fresh 600-man battalions at 100 m exchange 2 to 3 men a minute: too
# weak for close fire to decide anything before the bayonet (Duffy: effectiveness rises
# sharply inside about 50 yards). 0.015 at 50 m and 0.008 at 100 m are trial values
# (assumption); the others keep the spec table's shape scaled by 8/3 (assumption). Two fresh
# quality-3 battalions at 100 m exchange about 5.8 men a minute each at the outset.
HIT_RATE = [
    (25.0, 0.024),
    (50.0, 0.015),
    (100.0, 0.008),
    (150.0, 0.004),
    (200.0, 0.0019),
    (250.0, 0.0008),
]
# fraction of men firing, by firer state
FIRING_FRACTION = {
    UnitState.LINE: 1.0,
    UnitState.SQUARE: 0.25,  # assumption: one face of four bears on a given target
    UnitState.COLUMN: 1.0 / 6.0,  # spec: front rank only
    UnitState.SKIRMISH: 0.5,  # spec
}
SKIRMISH_HIT_MULT = 1.5  # spec
# hits taken, by target state (spec: skirmish 0.5, column 1.5)
TARGET_STATE_MUSKET = {UnitState.SKIRMISH: 0.5, UnitState.COLUMN: 1.5}
COVER_FACTOR = {
    Cover.WOOD: 0.5,
    Cover.VILLAGE: 0.5,
    Cover.ROUGH: 0.8,
    Cover.ORCHARD: 0.8,
}  # orchard: assumption, as rough
ASPECT_FACTOR = {"front": 1.0, "flank": 1.5, "rear": 2.0}  # spec
FIRE_ARC_DEG = 60.0  # assumption: a line fires at targets within 60 degrees of its front
ARTILLERY_ARC_DEG = 45.0  # assumption: guns traverse 45 degrees either side without turning
MOVED_NO_FIRE_M = 10.0  # assumption: a body that moved more than this in the tick does not fire
AMMO_MUSKETRY = 2.0  # spec: per minute of musketry
# Fire masking (assumption, a cheap stand-in for frontage footprints): a body does not fire at a
# target when a friendly body's centre lies in a 60 m wide corridor between them, more than
# 25 m in front of the firer (closer is beside it on the firing line). Guns on a height firing
# over their own troops are not modelled.
MASK_CORRIDOR_M = 60.0
MASK_NEAR_M = 25.0
AMMO_ARTILLERY = 1.0  # spec: per minute of artillery fire
AMMO_LOW = 20.0  # spec: below 20 the rate halves
FATIGUE_FIRE_DIV = 200.0  # musketry x (1 - fatigue / 200)

# ---------------------------------------------------------------------------
# Artillery
ROUNDSHOT_RANGE_M = {3: 800.0, 6: 1000.0, 12: 1400.0}  # 3-pdr: assumption
CANISTER_RANGE_M = 400.0
# per gun per minute; the spec's points 300 and 600 m; the long-range tail (0.25 at max range) is
# an assumption.
ROUNDSHOT = [(300.0, 1.0), (600.0, 0.6)]
ROUNDSHOT_AT_MAX = 0.25
CANISTER = [(100.0, 5.0), (200.0, 3.0), (400.0, 1.0)]  # 400 m point: assumption
# Weapon types (assumptions): a howitzer fires shell at a direct target at half a cannon's
# rate, and its bursting shell gets no depth bonus against a square (factor 1, not 2.5);
# mortars are siege and position pieces and do not fire in v0.
HOWITZER_DIRECT_MULT = 0.5
# Battalion guns (assumptions): light 3-pounders, two per battalion, served with the
# battalion when it stands in line: roundshot to 600 m and canister to 300 m at about half a
# 6-pounder's effect per gun (lighter ball, fewer balls in the canister).
BN_GUN_RANGE_M = 600.0
BN_CANISTER_RANGE_M = 300.0
BN_ROUNDSHOT = [(300.0, 0.5), (600.0, 0.3)]
BN_CANISTER = [(100.0, 2.5), (200.0, 1.5), (300.0, 0.75)]
ARTY_TARGET_STATE = {
    UnitState.LINE: 1.0,
    UnitState.COLUMN: 2.0,
    UnitState.SQUARE: 2.5,
    UnitState.SKIRMISH: 0.4,
    UnitState.ROUTED: 1.0,  # assumption
    UnitState.LIMBERED: 0.5,
    UnitState.UNLIMBERED: 0.5,
}  # spec counter-battery
# Assumption: the per-gun rates above are for a target of battalion size, whose men fill the
# beaten zone of a shot or a canister cone; a smaller body presents fewer men in it, so gun
# casualties scale by min(1, men / GUN_FULL_TARGET_MEN) (unscaled, companies of 31 to 300
# men would take a battalion's losses).
GUN_FULL_TARGET_MEN = 300.0


# ---------------------------------------------------------------------------
# Melee
CONTACT_M = 60.0  # assumption: bodies within 60 m are in contact
ATTACK_STATE = {"gallop": 3.0, "trot": 2.0, "walk": 1.0}  # cavalry; walk: assumption
INF_ATTACK_STATE = {
    UnitState.COLUMN: 1.5,
    UnitState.LINE: 1.0,
    UnitState.SKIRMISH: 0.5,
}  # skirmish: assumption
DEF_SQUARE_VS_CAV = 4.0
# A steady, unshaken line with fire usually repulsed a frontal charge; a disordered or flanked
# one broke. The spec's 1.5 lets fresh quality-4 cuirassiers break a steady quality-3 line
# head-on (ratio about 2.2). 3.0 (a calibration judgment, not a fitted number) gives
# an equal-quality, equal-strength steady line in the open a ratio just under 1 against a
# frontal gallop after its two defensive volleys; the shaken factor below is unchanged.
DEF_LINE_VS_CAV_STEADY = 3.0
DEF_LINE_VS_CAV_SHAKEN = 0.5
DEF_LINE_VS_INF = 1.2
DEF_COVER = 2.0  # in VILLAGE or WOOD
DEF_ROUTED = 0.1
DEF_COLUMN = 1.0  # assumption
DEF_SKIRMISH = 0.5  # assumption: open order cannot stand a charge
DEF_CAV_HALTED = 0.7  # assumption: halted cavalry receiving a charge
DEF_GUNS_UNLIMBERED = 0.5  # assumption: crews defending their pieces
DEF_GUNS_LIMBERED = 0.2  # assumption
DEF_FLANKED_MULT = 0.5  # assumption: any non-square defender attacked in flank or rear
DISORDERED = 30.0  # assumption: disorder at which a line counts as shaken / a square unsteady
BREAK_RATIO, REPULSE_RATIO = 1.5, 0.67
BREAK_DEF_LOSS, BREAK_ATT_LOSS = 0.08, 0.02
MELEE_MIN, MELEE_LOSS_PER_MIN = 3, 0.03
REPULSE_LOSS, REPULSE_BACK_M = 0.06, 100.0
REPULSE_DISORDER = 30.0  # assumption
WIN_DISORDER = {"cavalry": 30.0, "infantry": 15.0}  # assumption: disorder of a victor
WIN_DISORDER_OTHER = 15.0  # assumption: of a victor of another arm (guns, a train)
CHARGE_FIRE_RANGES = (100.0, 50.0)  # assumption: the "last 2 minutes" of fire at a charge
UMPIRE_RANGE = (0.7, 1.4)
# impact value = men x quality x state factor x morale / MORALE_SHOCK_DIV, the attacker's also
# x (1 - fatigue / FATIGUE_SHOCK_DIV)
MORALE_SHOCK_DIV = 60.0
FATIGUE_SHOCK_DIV = 150.0
# Pursuit (assumptions): a body reaching a routed enemy cuts into it once per flight: the routed
# body loses 5%, the pursuer is disordered and may not strike again for 3 minutes.
PURSUIT_LOSS = 0.05
# Squares (assumptions): cavalry recognises a formed, steady square at 100 m and pulls up; it
# takes the square's fire at that range, loses 1% more in the turn and falls back disordered.
# No melee: the spec's "repulsed regardless" without the 6% repulse loss.
SQUARE_RECOGNISE_M = 100.0
SQUARE_ABORT_LOSS = 0.01
PURSUIT_DISORDER = 20.0
PURSUIT_REFORM_MIN = 3
# Trains (design assumption): a formed enemy body within CAPTURE_M of a train takes it without
# a melee. Assumption: CONTACT_M plus the slack of a body halted at contact distance.
CAPTURE_M = 75.0


def interp(table: list[tuple[float, float]], x: float) -> float:
    xs = [p[0] for p in table]
    ys = [p[1] for p in table]
    return float(np.interp(x, xs, ys))


def quality_factor(q: int) -> float:
    # assumption: 0.6 + 0.2 q, so quality 3 gives 1.2 and two fresh 600-man battalions
    # at 100 m inflict 600 * 0.008 * 1.2 = 5.8 men a minute (spec table: 2.2)
    return 0.6 + 0.2 * q


def ammo_factor(ammo: float) -> float:
    if ammo <= 0.0:
        return 0.0
    return 0.5 if ammo < AMMO_LOW else 1.0


def cover_factor(world, target: Unit) -> float:
    return COVER_FACTOR.get(world.cover(target.x, target.y), 1.0)


def aspect_factor(firer: Unit, target: Unit) -> float:
    if target.state == UnitState.SQUARE:
        return 1.0
    return ASPECT_FACTOR[aspect((target.x, target.y), target.facing_deg, (firer.x, firer.y))]


def can_musket(u: Unit) -> bool:
    return u.arm == Arm.INFANTRY and u.state in FIRING_FRACTION and u.ammo > 0.0 and u.men > 0


def in_arc(u: Unit, target: Unit, arc: float) -> bool:
    if u.state == UnitState.SQUARE:
        return True
    return angle_diff(bearing((u.x, u.y), (target.x, target.y)), u.facing_deg) <= arc


def musket_rate(world, firer: Unit, target: Unit, rng_m: float | None = None) -> float:
    """Expected casualties per minute inflicted by firer's musketry on target."""
    r = dist((firer.x, firer.y), (target.x, target.y)) if rng_m is None else rng_m
    if r > MUSKET_RANGE_M or not can_musket(firer):
        return 0.0
    hit = interp(HIT_RATE, r)
    men = firer.men * FIRING_FRACTION[firer.state]
    if firer.state == UnitState.SKIRMISH:
        hit *= SKIRMISH_HIT_MULT
    rate = men * hit * quality_factor(firer.quality)
    rate *= TARGET_STATE_MUSKET.get(target.state, 1.0)
    rate *= cover_factor(world, target) * aspect_factor(firer, target)
    rate *= ammo_factor(firer.ammo) * max(0.0, 1.0 - firer.fatigue / FATIGUE_FIRE_DIV)
    return rate


def gun_range(u: Unit) -> float:
    cal = u.calibre_lb or 6
    nearest = min(ROUNDSHOT_RANGE_M, key=lambda c: (abs(c - cal), c))
    return ROUNDSHOT_RANGE_M[nearest]


def guns_serviceable(u: Unit) -> int:
    if u.arm != Arm.ARTILLERY or u.guns <= 0:
        return 0
    per = u.crew / u.guns if u.crew else 0.0
    if per <= 0:
        return u.guns
    return min(u.guns, math.floor(u.men / per + 1e-9))


def can_cannon(u: Unit) -> bool:
    return (
        u.arm == Arm.ARTILLERY
        and u.state == UnitState.UNLIMBERED
        and u.ammo > 0.0
        and guns_serviceable(u) > 0
    )


def gun_exposure(target: Unit) -> float:
    """Fraction of a battalion-size target a body presents to guns (1 for 300 men or more)."""
    if target.arm == Arm.ARTILLERY:
        return 1.0  # a battery's exposure is its guns and teams, not its crew count
    return min(1.0, max(0.0, target.men) / GUN_FULL_TARGET_MEN)


def gun_rate(world, gun: Unit, target: Unit, rng_m: float | None = None) -> float:
    r = dist((gun.x, gun.y), (target.x, target.y)) if rng_m is None else rng_m
    max_r = gun_range(gun)
    if r > max_r or not can_cannon(gun):
        return 0.0
    if r <= ROUNDSHOT[0][0]:
        per = ROUNDSHOT[0][1]
    elif r <= ROUNDSHOT[1][0]:
        per = interp(ROUNDSHOT, r)
    else:
        per = interp([ROUNDSHOT[1], (max_r, ROUNDSHOT_AT_MAX)], r)
    if r <= CANISTER_RANGE_M:
        per = max(per, interp(CANISTER, r))
    state = ARTY_TARGET_STATE.get(target.state, 1.0)
    how = min(gun.howitzers, gun.guns)
    mor = min(gun.mortars, gun.guns - how)
    cannon = gun.guns - how - mor
    how_state = 1.0 if target.state == UnitState.SQUARE else state
    mix = (cannon * state + how * HOWITZER_DIRECT_MULT * how_state) / gun.guns
    rate = guns_serviceable(gun) * per * mix * cover_factor(world, target)
    rate *= ammo_factor(gun.ammo) * gun_exposure(target)
    return rate


def bn_guns_ready(u: Unit, rt) -> int:
    """Battalion guns that can fire this minute: the battalion stands in line, formed."""
    n = u.bn_guns - rt.bn_lost
    if (
        n <= 0
        or u.arm != Arm.INFANTRY
        or u.state != UnitState.LINE
        or rt.bn_ammo <= 0.0
        or u.men <= 0
    ):
        return 0
    return n


def bn_gun_rate(world, u: Unit, rt, target: Unit, rng_m: float) -> float:
    n = bn_guns_ready(u, rt)
    if n == 0 or rng_m > BN_GUN_RANGE_M:
        return 0.0
    per = interp(BN_ROUNDSHOT, rng_m)
    if rng_m <= BN_CANISTER_RANGE_M:
        per = max(per, interp(BN_CANISTER, rng_m))
    rate = n * per * ARTY_TARGET_STATE.get(target.state, 1.0) * cover_factor(world, target)
    return rate * ammo_factor(rt.bn_ammo) * gun_exposure(target)


def fire_rate(world, firer: Unit, target: Unit, rng_m: float | None = None) -> float:
    if firer.arm == Arm.ARTILLERY:
        return gun_rate(world, firer, target, rng_m)
    return musket_rate(world, firer, target, rng_m)


def fire_arc(u: Unit) -> float:
    """The arc a body fires into, either side of its facing."""
    return ARTILLERY_ARC_DEG if u.arm == Arm.ARTILLERY else FIRE_ARC_DEG


def weapon_range(u: Unit) -> float:
    if u.arm == Arm.ARTILLERY:
        return gun_range(u)
    if u.arm == Arm.INFANTRY:
        return MUSKET_RANGE_M
    return 0.0


def can_fire(u: Unit) -> bool:
    return can_cannon(u) if u.arm == Arm.ARTILLERY else can_musket(u)


def spend_ammo(u: Unit, volleys: int = 1) -> None:
    """A minute's (or a volley's) ammunition (spec): -2 musketry, -1 artillery."""
    per = AMMO_ARTILLERY if u.arm == Arm.ARTILLERY else AMMO_MUSKETRY
    u.ammo = max(0.0, u.ammo - per * volleys)


# ---------------------------------------------------------------------------
# Melee values


def flanked(attacker: Unit, defender: Unit) -> bool:
    if defender.state == UnitState.SQUARE:
        return False
    return (
        aspect((defender.x, defender.y), defender.facing_deg, (attacker.x, attacker.y)) != "front"
    )


def attacker_value(a: Unit, gait: str) -> float:
    if a.arm == Arm.CAVALRY:
        sf = ATTACK_STATE.get(gait, 1.0)
    elif a.arm == Arm.INFANTRY:
        sf = INF_ATTACK_STATE.get(a.state, 1.0)
    else:
        sf = 0.3  # assumption: guns do not charge; crews defending forward
    return (
        a.men
        * a.quality
        * sf
        * (a.morale / MORALE_SHOCK_DIV)
        * (1.0 - a.fatigue / FATIGUE_SHOCK_DIV)
    )


def defender_value(world, d: Unit, a: Unit) -> tuple[float, str]:
    """Defender impact value and the factor's label."""
    vs_cav = a.arm == Arm.CAVALRY
    fl = flanked(a, d)
    c = world.cover(d.x, d.y)
    if d.state == UnitState.ROUTED:
        sf, why = DEF_ROUTED, "routed"
    elif d.state == UnitState.SQUARE:
        sf, why = (DEF_SQUARE_VS_CAV, "square") if vs_cav else (DEF_COLUMN, "square vs foot")
    elif d.arm == Arm.ARTILLERY:
        sf, why = (
            (DEF_GUNS_UNLIMBERED, "guns")
            if d.state == UnitState.UNLIMBERED
            else (DEF_GUNS_LIMBERED, "limbered guns")
        )
    elif c in (Cover.VILLAGE, Cover.WOOD) and d.arm == Arm.INFANTRY:
        sf, why = DEF_COVER, f"in {c.name.lower()}"
    elif d.arm == Arm.CAVALRY:
        sf, why = DEF_CAV_HALTED, "halted cavalry"
    elif d.state == UnitState.LINE:
        if vs_cav:
            shaken = fl or d.disorder >= DISORDERED
            sf, why = (
                (DEF_LINE_VS_CAV_SHAKEN, "line flanked or disordered")
                if shaken
                else (DEF_LINE_VS_CAV_STEADY, "steady line")
            )
        else:
            sf, why = DEF_LINE_VS_INF, "line"
    elif d.state == UnitState.SKIRMISH:
        sf, why = DEF_SKIRMISH, "skirmishers"
    else:
        sf, why = DEF_COLUMN, "column"
    # flank penalty for others (the line-vs-cavalry case already carries it)
    if (
        fl
        and d.state not in (UnitState.ROUTED, UnitState.SQUARE)
        and not (vs_cav and d.state == UnitState.LINE)
    ):
        sf *= DEF_FLANKED_MULT
        why += ", flanked"
    return d.men * d.quality * sf * (d.morale / MORALE_SHOCK_DIV), why


def steady_square(d: Unit, changing: bool) -> bool:
    return d.state == UnitState.SQUARE and not changing and d.disorder < DISORDERED


# ---------------------------------------------------------------------------
# Phases (called by sim.Sim.step)

ENGAGED_RANGE_M = 400.0  # assumption: fire within 400 m puts both bodies "engaged"


def stochastic_round(x: float, rng) -> int:
    base = math.floor(x)
    return int(base + (1 if rng.random() < x - base else 0))


def masked(u: Unit, tx: float, ty: float, d: float, fxy: np.ndarray) -> bool:
    """Whether any friendly centre in `fxy` (n x 2) stands in the firing corridor from u to
    the target at (tx, ty), d metres away."""
    if d <= MASK_NEAR_M or len(fxy) == 0:
        return False
    vx, vy = (tx - u.x) / d, (ty - u.y) / d
    wx, wy = fxy[:, 0] - u.x, fxy[:, 1] - u.y
    along = wx * vx + wy * vy
    across = np.abs(wx * vy - wy * vx)
    hit = (along > MASK_NEAR_M) & (along < d) & (across <= MASK_CORRIDOR_M / 2.0)
    return bool(hit.any())


def fire_phase(sim) -> None:
    units = sim.forces.units
    expected: dict[str, float] = {}
    for u in units.values():
        u.engaged = set()
    by_side = {
        side: (np.array([v.id for v in us]), xy) for side, (us, xy) in sim.alive_by_side().items()
    }
    for u in units.values():
        rt = sim.rt[u.id]
        rt.fired = False
        rt.fire_target = None
        if (
            u.state in (UnitState.ROUTED, UnitState.DESTROYED)
            or busy(rt)
            or rt.moved > MOVED_NO_FIRE_M
        ):
            continue
        guns = bn_guns_ready(u, rt)
        if not can_fire(u) and not guns:
            continue
        rmax = max(weapon_range(u) if can_fire(u) else 0.0, BN_GUN_RANGE_M if guns else 0.0)
        arc = fire_arc(u)
        cands = [
            (tid, d)
            for tid, d in sim.vision.visible.get(u.id, ())
            if d <= rmax and units[tid].state != UnitState.DESTROYED and in_arc(u, units[tid], arc)
        ]
        if cands:
            ids, xy = by_side.get(u.side, (np.array([]), np.zeros((0, 2))))
            near = (
                (ids != u.id) & ((xy[:, 0] - u.x) ** 2 + (xy[:, 1] - u.y) ** 2 <= rmax * rmax)
                if len(ids)
                else ids.astype(bool)
            )
            fxy = xy[near] if len(ids) else xy
            cands = [
                (tid, d) for tid, d in cands if not masked(u, units[tid].x, units[tid].y, d, fxy)
            ]
        if not cands:
            continue
        # the body's own weapon (musketry or a battery's guns), then the battalion guns
        shots = []
        if can_fire(u):
            shots.append(("guns" if u.arm == Arm.ARTILLERY else "musketry", weapon_range(u)))
        if guns:
            shots.append(("battalion guns", BN_GUN_RANGE_M))
        for weapon, wr in shots:
            inr = [c for c in cands if c[1] <= wr]
            if not inr:
                continue
            pick = next((c for c in inr if c[0] == rt.target), None)
            if pick is None and rt.fire_target is not None:
                pick = next((c for c in inr if c[0] == rt.fire_target), None)
            if pick is None:
                formed = [c for c in inr if units[c[0]].state != UnitState.ROUTED]
                pick = (formed or inr)[0]
            tid, d = pick
            t = units[tid]
            if weapon == "battalion guns":
                rate = bn_gun_rate(sim.world, u, rt, t, d)
            else:
                rate = fire_rate(sim.world, u, t, d)
            if rate <= 0.0:
                continue
            expected[tid] = expected.get(tid, 0.0) + rate
            if weapon == "battalion guns":
                rt.bn_ammo = max(0.0, rt.bn_ammo - AMMO_ARTILLERY)
            else:
                rt.fired = True  # fatigue: movement.fatigue_rate
                spend_ammo(u)
            rt.fire_target = rt.fire_target or tid
            rt.last_dist[tid] = d
            if d <= ENGAGED_RANGE_M:
                u.engaged.add(tid)
                t.engaged.add(u.id)
            sim.emit(
                "fire",
                firer=u.id,
                target=tid,
                range=round(d, 1),
                rate=round(rate, 4),
                weapon=weapon,
            )
    for tid in sorted(expected):  # one draw per target, keyed by where it stands
        t = units[tid]
        sim.inflict(tid, stochastic_round(expected[tid], sim.event_rng("fire", t)), "fire")


def countercharge_gait(sim, d: Unit, a: Unit) -> str | None:
    """The gait of a defending cavalry body that is itself moving to contact with `a` (it was
    charging this tick and faces it), else None (it receives the charge halted)."""
    rd = sim.rt[d.id]
    if (
        d.arm != Arm.CAVALRY
        or d.state == UnitState.ROUTED
        or rd.phase != "charge"
        or rd.gait not in ("trot", "gallop")
    ):
        return None
    if angle_diff(bearing((d.x, d.y), (a.x, a.y)), d.facing_deg) > FIRE_ARC_DEG:
        return None
    return rd.gait


def melee_phase(sim) -> None:
    """Continue running melees, then resolve the tick's new contacts, all from the field as
    it stands after movement and fire: a body takes part in at
    most one new clash a minute; two bodies that went in at each other make one clash, in
    which a draw of the game's seed decides which strikes as the attacker; where clashes
    compete for a body, a draw orders them. The draws are keyed by where the bodies stand
    (Sim.event_rng), so neither the ids nor the side decide who strikes first."""
    units = sim.forces.units
    # running melees: both lose 3% a minute; at the end the lower morale breaks
    done = set()
    for uid in sorted(units):
        rt = sim.rt[uid]
        if rt.melee_with is None or not rt.melee_attacker or uid in done:
            continue
        a, d = units[uid], units[rt.melee_with]
        done |= {a.id, d.id}
        _melee_minute(sim, a, d, sim.event_rng("melee", a, d))
    capture_phase(sim)
    asked: dict[tuple[str, str], str] = {}
    for a_id, d_id, gait in sim.melee_requests:
        asked.setdefault((a_id, d_id), gait)
    clashes = []
    for pair in sorted({tuple(sorted(k)) for k in asked}):
        x, y = (units[k] for k in pair)
        # where they stand, not their ids, in a key the 180° rotation leaves unchanged
        x, y = sorted((x, y), key=sim.place_key)
        g = sim.event_rng("contact", x, y)
        order, coin = float(g.random()), float(g.random())
        goes = [(a, d) for a, d in ((x, y), (y, x)) if (a.id, d.id) in asked and strikes(sim, a, d)]
        if not goes:
            continue
        if len(goes) == 2 and sim.place_key(x) == sim.place_key(y):
            # the two stand at each other's image through the field's centre: where they
            # stand tells them apart in no way the 180° rotation keeps, and their ids or
            # sides in no way the swap of colours keeps.
            # The body with the better initiative is taken first; two bodies alike in every
            # respect make an even clash.
            ix, iy = _initiative(x), _initiative(y)
            if ix == iy:
                clashes.append((order, x, y, True))
                continue
            if ix < iy:
                goes.reverse()
        a, d = goes[0] if len(goes) == 1 or coin < 0.5 else goes[1]
        clashes.append((order, a, d, False))
    taken: set[str] = set()
    for _, a, d, even in sorted(clashes, key=lambda c: (c[0], sim.place_key(c[1]))):
        if a.id in taken or d.id in taken:
            continue  # it is already in a clash this minute; it may go in again next minute
        taken |= {a.id, d.id}
        if even:
            _even_clash(sim, a, d)
            continue
        _contact(
            sim, a, d, asked[(a.id, d.id)], asked.get((d.id, a.id)), sim.event_rng("melee", a, d)
        )
    sim.melee_requests = []


def _initiative(u: Unit) -> tuple:
    """What tells two bodies apart that neither their ids, their sides nor where they stand
    does: higher morale, more men, less disorder, less fatigue, better quality, then the rest
    of their state."""
    return (
        u.morale,
        u.men,
        -u.disorder,
        -u.fatigue,
        u.quality,
        u.ammo,
        u.arm.value,
        u.kind.value,
        u.state.value,
        u.guns,
        u.bn_guns,
    )


def _engage(sim, a: Unit, d: Unit, fought: bool = True) -> None:
    """`a` and `d` are in contact; `fought`: they fought this minute (movement.fatigue_rate)."""
    a.engaged.add(d.id)
    d.engaged.add(a.id)
    if fought:
        sim.rt[a.id].melee_tick = sim.rt[d.id].melee_tick = sim.now


def _even_clash(sim, a: Unit, d: Unit) -> None:
    """Two bodies alike in every respect, standing at each other's image through the centre
    of the field, go in at each other: neither gives way, both recoil disordered (as an even
    clash of two charging bodies does, _melee_minute). Any other outcome would have to pick
    one of them by its name or by its place, which a symmetric field must not do."""
    _engage(sim, a, d)
    sim.emit(
        "melee_end",
        attacker=a.id,
        defender=d.id,
        loser=None,
        even=True,
        attacker_morale=round(a.morale, 3),
        defender_morale=round(d.morale, 3),
    )
    for u, o in ((a, d), (d, a)):
        _fall_back(sim, u, o)
        set_clock(sim, u, "repulse")


def _going_in(sim, a: Unit, d: Unit) -> str | None:
    """What a's going in at d comes to this minute: "capture" (wagons are taken, not fought),
    "pursue" (a routed enemy), "fight", or None (nothing)."""
    ra, rd = sim.rt[a.id], sim.rt[d.id]
    if (
        a.state in (UnitState.ROUTED, UnitState.DESTROYED)
        or d.state == UnitState.DESTROYED
        or ra.melee_with
        or rd.melee_with
    ):
        return None
    if UnitKind.TRAIN in (d.kind, a.kind):
        return "capture" if d.kind == UnitKind.TRAIN and a.kind != UnitKind.TRAIN else None
    if sim.now < ra.attack_at:
        return None  # still reorganising after a repulse, a defeat or a pursuit: it halts
    if a.task is not None and a.task.forbids(Forbid.ENGAGE):
        return None  # "not to be drawn into any fight": it seeks no contact
    if d.state == UnitState.ROUTED:
        if a.task is not None and a.task.forbids(Forbid.PURSUE):
            return None  # "nobody is to pursue": it halts at the fugitives
        return "pursue"
    return "fight"


def strikes(sim, a: Unit, d: Unit) -> bool:
    """Whether a's going in at d comes to anything this minute (a routed enemy is pursued
    once per flight)."""
    what = _going_in(sim, a, d)
    if what == "pursue":
        return not sim.rt[d.id].pursued
    return what is not None


def _contact(sim, a: Unit, d: Unit, gait: str, d_asked: str | None, rng) -> None:
    what = _going_in(sim, a, d)
    if what == "capture":
        capture(sim, d, a)
    elif what == "pursue":
        _pursue(sim, a, d, rng)
    if what != "fight":
        return
    rd = sim.rt[d.id]
    d_gait = (
        d_asked
        if d_asked is not None and d.arm == Arm.CAVALRY and d.state != UnitState.ROUTED
        else countercharge_gait(sim, d, a)
    )
    if d_gait is not None and a.arm == Arm.CAVALRY:
        _encounter(sim, a, d, gait, d_gait, rng)
        return
    if a.arm == Arm.CAVALRY and steady_square(d, busy(rd)):
        _pull_up(sim, a, d, gait, rng)
        return
    # defensive fire during the last two minutes of the approach
    if can_fire(d) and in_arc(d, a, fire_arc(d)) and d.state != UnitState.ROUTED:
        ranges = CHARGE_FIRE_RANGES[1:] if rd.fired else CHARGE_FIRE_RANGES
        exp = sum(fire_rate(sim.world, d, a, r) for r in ranges)
        if exp > 0.0:
            spend_ammo(d, len(ranges))  # each volley costs a minute's ammunition
        sim.inflict(a.id, stochastic_round(exp, rng), "defensive fire")
        if a.men <= 0:
            return
    ctx = melee_context(sim, a, d, gait)
    factor = sim.situation_modifier(ctx)
    av = attacker_value(a, gait) * factor
    dv, why = defender_value(sim.world, d, a)
    ratio = av / dv if dv > 0 else math.inf
    _engage(sim, a, d)
    if ratio > BREAK_RATIO:
        outcome = "broken"
    elif ratio >= REPULSE_RATIO:
        outcome = "melee"
    else:
        outcome = "repulsed"
    sim.emit(
        "melee",
        attacker=a.id,
        defender=d.id,
        gait=gait,
        attacker_value=round(av, 3),
        defender_value=round(dv, 3),
        defender_factor=why,
        ratio=round(ratio, 4),
        umpire_factor=factor,
        context=ctx,
        outcome=outcome,
    )
    if outcome == "broken":
        _break(sim, d, a, rng)
    elif outcome == "repulsed":
        _repulse(sim, a, d, rng)
    else:
        _start_melee(sim, a, d, rng, encounter=False)


def capture(sim, train: Unit, captor: Unit) -> None:
    """A train taken by a formed enemy body: no melee; its men (drivers) and cargo guns are
    lost to its side; it leaves the battle (Sim.offmap, fate "captured")."""
    men = int(train.men)
    sim.leave(train, "captured", None, by=captor.id, by_name=captor.name, guns=int(train.guns))
    train.casualties += men
    train.men = 0


def capture_phase(sim) -> None:
    """Every train with a formed enemy body (not a train) within CAPTURE_M is captured by the
    nearest (ties by id), whatever the train's own state."""
    units = sim.forces.units
    trains = [
        u for u in units.values() if u.kind == UnitKind.TRAIN and u.state != UnitState.DESTROYED
    ]
    for t in sorted(trains, key=lambda u: u.id):
        near = [
            e
            for e in sim.enemies_near(t, CAPTURE_M)
            if e.state not in (UnitState.ROUTED, UnitState.DESTROYED) and e.kind != UnitKind.TRAIN
        ]
        if near:
            capture(sim, t, min(near, key=lambda e: ((e.x - t.x) ** 2 + (e.y - t.y) ** 2, e.id)))


def _encounter(sim, a: Unit, d: Unit, gait: str, d_gait: str, rng) -> None:
    """Two cavalry bodies charging each other: both strike at their own gait. The umpire is
    asked once, about the pair with `a` first, and its factor applies to `a`; which of the two
    is `a` is a seeded draw (melee_phase), never their ids (with no umpire the factor is 1
    and the encounter is symmetric)."""
    ctx = melee_context(sim, a, d, gait) + f" {d.name} countercharges at the {d_gait}."
    factor = sim.situation_modifier(ctx)
    av = attacker_value(a, gait) * factor
    dv = attacker_value(d, d_gait)
    # both are moving, and point bodies can pass through each other within a tick: a flank is
    # judged from the headings (d not meeting a's line of advance head-on), not the positions
    if angle_diff(d.facing_deg, (a.facing_deg + 180.0) % 360.0) > FIRE_ARC_DEG:
        dv *= DEF_FLANKED_MULT
    ratio = av / dv if dv > 0 else math.inf
    _engage(sim, a, d)
    if ratio > BREAK_RATIO:
        outcome = "broken"
    elif ratio * BREAK_RATIO < 1.0:
        outcome = "attacker broken"
    else:
        outcome = "melee"
    sim.emit(
        "melee",
        attacker=a.id,
        defender=d.id,
        gait=gait,
        defender_gait=d_gait,
        attacker_value=round(av, 3),
        defender_value=round(dv, 3),
        defender_factor=f"countercharge at the {d_gait}",
        ratio=round(ratio, 4),
        umpire_factor=factor,
        context=ctx,
        outcome=outcome,
    )
    if outcome == "broken":
        _break(sim, d, a, rng)
    elif outcome == "attacker broken":
        _break(sim, a, d, rng)
    else:
        _start_melee(sim, a, d, rng, encounter=True)


def _pull_up(sim, a: Unit, d: Unit, gait: str, rng) -> None:
    """Cavalry charging a formed, steady square recognises it at SQUARE_RECOGNISE_M and pulls
    up: one volley at that range, a small loss in the turn, and it falls back disordered."""
    fire = fire_rate(sim.world, d, a, SQUARE_RECOGNISE_M) if can_fire(d) else 0.0
    n_fire = stochastic_round(fire, rng)
    if fire > 0.0:
        spend_ammo(d)
    n_turn = stochastic_round(a.men * SQUARE_ABORT_LOSS, rng)
    sim.inflict(a.id, n_fire, "defensive fire")
    sim.inflict(a.id, n_turn, "pulled up")
    _engage(sim, a, d, fought=False)
    ux, uy = _away(d, a)
    back = SQUARE_RECOGNISE_M + REPULSE_BACK_M
    nx, ny = d.x + snap_m(back * ux), d.y + snap_m(back * uy)
    if sim.world.passable(nx, ny, arm_class(a)):
        a.x, a.y = nx, ny
        add_disorder(a, REPULSE_DISORDER)
        rt = sim.rt[a.id]
        rt.route = []
        rt.phase, rt.phase_since = "reform", sim.now
    else:
        _fall_back(sim, a, d)
    set_clock(sim, a, "repulse")
    sim.emit(
        "charge_aborted",
        attacker=a.id,
        defender=d.id,
        gait=gait,
        reason="steady square",
        loss=n_fire + n_turn,
    )


def _pursue(sim, a: Unit, d: Unit, rng) -> None:
    """A body reaching a routed enemy: one pursuit per flight, never a melee."""
    rd, ra = sim.rt[d.id], sim.rt[a.id]
    if rd.pursued:
        return
    rd.pursued = True
    n = stochastic_round(d.men * PURSUIT_LOSS, rng)
    sim.inflict(d.id, n, "pursuit")
    add_disorder(a, PURSUIT_DISORDER)
    ra.attack_at = max(ra.attack_at, sim.now + PURSUIT_REFORM_MIN)
    ra.melee_tick = sim.now
    ra.route = []
    if a.arm == Arm.CAVALRY:
        ra.phase, ra.phase_since = "reform", sim.now
    sim.emit("pursuit", attacker=a.id, defender=d.id, loss=n)


def _start_melee(sim, a: Unit, d: Unit, rng, encounter: bool) -> None:
    ra, rd = sim.rt[a.id], sim.rt[d.id]
    ra.melee_with, rd.melee_with = d.id, a.id
    ra.melee_left = rd.melee_left = MELEE_MIN
    ra.melee_attacker, rd.melee_attacker = True, False
    ra.melee_encounter = rd.melee_encounter = encounter
    ra.route, rd.route = [], []
    _melee_minute(sim, a, d, rng)


def _pair_loss(sim, a: Unit, d: Unit, frac: float, rng, cause: str) -> None:
    """Both bodies lose `frac` of their men, rounded stochastically from one shared draw, so two
    equal bodies lose equally whichever of them is `a`."""
    r = rng.random()
    for u in (a, d):
        x = u.men * frac
        base = math.floor(x)
        sim.inflict(u.id, int(base + (1 if r < x - base else 0)), cause)


def _loss(sim, u: Unit, frac: float, rng, cause: str) -> None:
    sim.inflict(u.id, stochastic_round(u.men * frac, rng), cause)


def _break(sim, loser: Unit, winner: Unit, rng) -> None:
    _loss(sim, loser, BREAK_DEF_LOSS, rng, "melee")
    _loss(sim, winner, BREAK_ATT_LOSS, rng, "melee")
    sim.rt[loser.id].bn_lost = loser.bn_guns  # its battalion guns are overrun
    rout(sim, loser, f"broken by {winner.id}", "complete")
    wrt = sim.rt[winner.id]
    add_disorder(winner, WIN_DISORDER.get(winner.arm.value, WIN_DISORDER_OTHER))
    if winner.arm == Arm.CAVALRY:
        wrt.phase, wrt.phase_since = "reform", sim.now
    else:
        wrt.phase, wrt.phase_since = "march", sim.now
    wrt.route = []


def _repulse(sim, a: Unit, d: Unit, rng) -> None:
    _loss(sim, a, REPULSE_LOSS, rng, "repulsed")
    _fall_back(sim, a, d)
    set_clock(sim, a, "repulse")


def _away(d: Unit, a: Unit) -> tuple[float, float]:
    """The unit vector from d to a (north when they stand on one spot). Taken from the
    difference itself, and the step from it set on the position lattice, so the image of a
    repulse under the 180° rotation lands exactly on the image."""
    dx, dy = a.x - d.x, a.y - d.y
    n = math.hypot(dx, dy)
    return (dx / n, dy / n) if n > 0.0 else (0.0, 1.0)


def _fall_back(sim, a: Unit, d: Unit) -> None:
    """`a` falls back REPULSE_BACK_M from `d`, disordered."""
    ux, uy = _away(d, a)
    nx, ny = a.x + snap_m(REPULSE_BACK_M * ux), a.y + snap_m(REPULSE_BACK_M * uy)
    if sim.world.passable(nx, ny, arm_class(a)):
        a.x, a.y = nx, ny
    add_disorder(a, REPULSE_DISORDER)
    rt = sim.rt[a.id]
    rt.route = []
    rt.phase, rt.phase_since = ("reform" if a.arm == Arm.CAVALRY else "firing"), sim.now


def _melee_minute(sim, a: Unit, d: Unit, rng) -> None:
    ra, rd = sim.rt[a.id], sim.rt[d.id]
    _pair_loss(sim, a, d, MELEE_LOSS_PER_MIN, rng, "melee")
    _engage(sim, a, d)
    ra.melee_left -= 1
    rd.melee_left = ra.melee_left
    if ra.melee_left > 0:
        return
    ra.melee_with = rd.melee_with = None
    encounter = ra.melee_encounter
    ra.melee_encounter = rd.melee_encounter = False
    if encounter and abs(a.morale - d.morale) < 1e-9:
        # an even clash of two charging bodies: neither gives way, both recoil disordered
        sim.emit(
            "melee_end",
            attacker=a.id,
            defender=d.id,
            loser=None,
            attacker_morale=round(a.morale, 3),
            defender_morale=round(d.morale, 3),
        )
        for u, o in ((a, d), (d, a)):
            _fall_back(sim, u, o)
            set_clock(sim, u, "repulse")
        return
    loser, winner = (a, d) if a.morale <= d.morale else (d, a)
    sim.emit(
        "melee_end",
        attacker=a.id,
        defender=d.id,
        loser=loser.id,
        attacker_morale=round(a.morale, 3),
        defender_morale=round(d.morale, 3),
    )
    rout(sim, loser, f"lost the melee with {winner.id}", "defeat")
    sim.rt[loser.id].bn_lost = loser.bn_guns  # its battalion guns are overrun
    add_disorder(winner, WIN_DISORDER.get(winner.arm.value, WIN_DISORDER_OTHER))
    wrt = sim.rt[winner.id]
    wrt.phase, wrt.phase_since = ("reform" if winner.arm == Arm.CAVALRY else "march"), sim.now


def melee_context(sim, a: Unit, d: Unit, gait: str) -> str:
    """The situation text the umpire judges (no numbers it must compute with)."""
    w = sim.world
    fl = "face" if d.state == UnitState.SQUARE else aspect((d.x, d.y), d.facing_deg, (a.x, a.y))
    terrain = w.cover(d.x, d.y).name.lower()

    def tired(u: Unit) -> str:
        return "fresh" if u.fatigue < 30 else "tired" if u.fatigue < 70 else "exhausted"

    def shaken(u: Unit) -> str:
        return "steady" if u.disorder < 30 else "shaken" if u.disorder < 60 else "in disorder"

    how = f"charges at the {gait}" if a.arm == Arm.CAVALRY else f"assaults in {a.state.value}"
    return (
        f"{a.name} ({a.kind.value} {a.arm.value}, {tired(a)}, {shaken(a)}) {how} "
        f"{d.name} ({d.kind.value} {d.arm.value} in {d.state.value}, {tired(d)}, "
        f"{shaken(d)}) on {terrain} ground {place(w, (d.x, d.y))}, striking its {fl}."
    )
