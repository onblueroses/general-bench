"""Reproductions for the engine's realism defects (cavalry clashes, fatigue, routs and pursuit,
squares, battalion guns, wheeling, ammunition, fire through friends): each test failed before
its fix."""

from __future__ import annotations

from collections import Counter

import pytest
from test_engine_kit import KOLIN, body, load_testfield, make_sim
from test_engine_replay import orders as replay_orders

from kriegsspiel import combat, morale, movement
from kriegsspiel.geometry import angle_diff
from kriegsspiel.sim import Sim
from kriegsspiel.types import Arm, Ref, RefKind, Task, TaskKind, UnitState

# ---------------------------------------------------------------------------
# A frontal cavalry clash does not depend on which body has the lower id


def _clash(blue_id: str, red_id: str):
    b = body(
        blue_id,
        "blue",
        "cuirassier",
        2600.0,
        2000.0,
        UnitState.LINE,
        facing=270.0,
        men=450,
        quality=4,
    )
    r = body(
        red_id, "red", "cuirassier", 2000.0, 2000.0, UnitState.LINE, facing=90.0, men=450, quality=4
    )
    s = make_sim([b, r])
    s.submit_tasks("blue", [Task(TaskKind.CHARGE, blue_id, Ref(RefKind.ENEMY, red_id))])
    s.submit_tasks("red", [Task(TaskKind.CHARGE, red_id, Ref(RefKind.ENEMY, blue_id))])
    for _ in range(12):
        s.step()
    melees = [e for e in s.events if e.kind == "melee"]
    assert melees, "the regiments never met"
    out = {}
    for side, u in (("blue", b), ("red", r)):
        out[side] = (u.state, u.men, round(u.morale, 6))
    first = melees[0].data
    gaits = {first["gait"], first.get("defender_gait")}
    return out, first, gaits


def test_countercharge_outcome_is_invariant_under_id_swap():
    one, ev1, gaits1 = _clash("a", "z")
    two, ev2, gaits2 = _clash("z", "a")
    assert one == two, (one, two)
    # the defender met the charge at its own gait, not as halted cavalry
    assert ev1["defender_factor"] != "halted cavalry"
    assert gaits1 == gaits2 == {"gallop"}
    assert ev1["ratio"] == ev2["ratio"]


# ---------------------------------------------------------------------------
# Fatigue is integrated once a minute from what the body actually did


def test_five_minutes_at_the_trot_cost_five_fatigue():
    k = body("k", "blue", "hussar", 2000.0, 3000.0, UnitState.COLUMN, facing=180.0, men=400)
    s = make_sim([k])
    s.submit_tasks(
        "blue", [Task(TaskKind.WITHDRAW, "k", Ref(RefKind.POINT, point=(2000.0, 500.0)))]
    )
    trots = 0
    for _ in range(5):
        s.step()
        trots += s.rt["k"].gait == "trot"
    assert trots == 5, "the regiment did not trot every minute"
    assert 900.0 < 3000.0 - k.y <= 1000.0  # about 1 km in five minutes
    assert k.fatigue == 5.0


def test_a_minute_of_melee_costs_three_fatigue_once():
    inf = body("i", "red", "line", 2000.0, 2000.0, UnitState.LINE, facing=90.0)
    cav = body(
        "k", "blue", "cuirassier", 2500.0, 2000.0, UnitState.LINE, facing=270.0, men=600, quality=3
    )
    h = body("h", "red", "hussar", 1700.0, 2200.0, UnitState.LINE, men=400)
    s = make_sim([inf, cav, h])
    s.submit_tasks("blue", [Task(TaskKind.CHARGE, "k", Ref(RefKind.ENEMY, "i"))])
    s.submit_tasks(
        "red", [Task(TaskKind.HOLD, "i", state=UnitState.LINE), Task(TaskKind.HOLD, "h")]
    )
    for _ in range(8):
        fi, fk = inf.fatigue, cav.fatigue
        s.step()
        ev = [e for e in s.tick_events if e.kind == "melee"]
        if ev:
            break
    assert ev and ev[0].data["outcome"] == "melee", ev
    assert inf.fatigue - fi == 3.0  # fired and fought: the melee rate, once
    assert cav.fatigue - fk == 3.0  # galloped and fought: once


# ---------------------------------------------------------------------------
# A rout is flight, then a recovery clock; a pursuit is one event, not a melee loop


def _cavalry_breaks_a_battalion():
    w, _, _ = load_testfield()
    i1 = body("i1", "red", "line", 1000.0, 1600.0, UnitState.LINE, facing=0.0, brigade="rb")
    i1.disorder = 60.0
    i2 = body("i2", "red", "line", 1000.0, 1150.0, UnitState.LINE, facing=0.0, brigade="rb")
    k = body(
        "k", "blue", "cuirassier", 1000.0, 2050.0, UnitState.LINE, facing=180.0, men=450, quality=4
    )
    s = make_sim([i1, i2, k], world=w)
    s.submit_tasks("blue", [Task(TaskKind.CHARGE, "k", Ref(RefKind.ENEMY, "i1"))])
    s.submit_tasks("red", [Task(TaskKind.HOLD, "rb")])
    return s, i1


def test_a_cavalry_win_is_followed_by_one_pursuit_not_a_melee_loop():
    s, i1 = _cavalry_breaks_a_battalion()
    routed_at = None
    for _ in range(60):
        s.step()
        if routed_at is None and i1.state == UnitState.ROUTED:
            routed_at = s.now - 1
            morale_at_rout = i1.morale
    assert routed_at is not None, "the cavalry never broke the battalion"
    assert morale_at_rout <= morale.ROUT_MORALE
    after = [e for e in s.events if e.tick > routed_at and e.data.get("defender") == "i1"]
    assert sum(e.kind == "pursuit" for e in after) <= 1
    assert not [e for e in after if e.kind == "melee" and e.tick <= routed_at + 10], after
    rallies = [e for e in s.events if e.kind == "rally" and e.data["unit"] == "i1"]
    if rallies:  # not before the recovery clock, and it then holds where it stands
        assert rallies[0].tick >= routed_at + morale.RECOVERY_MIN["defeat"][0]
        assert i1.task is not None and i1.task.kind == TaskKind.HOLD


def test_melees_between_any_pair_are_bounded_on_the_test_field():
    w, f, u = load_testfield()
    s = Sim(w, f, u, seed=3)
    replay_orders(s)
    s.run(180)
    pairs = Counter(
        tuple(sorted((e.data["attacker"], e.data["defender"])))
        for e in s.events
        if e.kind == "melee"
    )
    assert pairs and max(pairs.values()) <= 3, pairs.most_common(3)
    assert not [
        e for e in s.events if e.kind == "melee" and e.data["defender_factor"].startswith("routed")
    ]


# ---------------------------------------------------------------------------
# Cavalry recognises a steady square and pulls up; it does not fight a melee


def test_a_charge_into_a_steady_square_pulls_up_with_under_three_percent_loss():
    inf = body("i", "red", "line", 2000.0, 2000.0, UnitState.SQUARE, facing=90.0)
    cav = body(
        "k", "blue", "cuirassier", 2500.0, 2000.0, UnitState.LINE, facing=270.0, men=450, quality=4
    )
    s = make_sim([inf, cav])
    s.submit_tasks("blue", [Task(TaskKind.CHARGE, "k", Ref(RefKind.ENEMY, "i"))])
    s.submit_tasks("red", [Task(TaskKind.HOLD, "i", state=UnitState.SQUARE)])
    for _ in range(8):
        s.step()
        if any(e.kind in ("melee", "charge_aborted") for e in s.tick_events):
            break
    assert not [e for e in s.events if e.kind == "melee"]
    assert [e for e in s.events if e.kind == "charge_aborted"]
    assert 450 - cav.men < 0.03 * 450, cav.men
    assert inf.state == UnitState.SQUARE
    assert ((cav.x - inf.x) ** 2 + (cav.y - inf.y) ** 2) ** 0.5 >= 150.0  # fell back
    assert cav.disorder >= 25.0


# ---------------------------------------------------------------------------
# Battalion guns fire with their battalion; batteries keep their weapon types


def test_kolin_loads_battalion_guns_and_weapon_types():
    from kriegsspiel import scenario

    _, _, units, _, _ = scenario.load(KOLIN)
    by = {u.id: u for u in units}
    guns = Counter()
    for u in units:
        guns[u.side] += u.bn_guns
    # the oob's count (docs/kolin-test-pack.md: 62 and 93)
    assert guns == {"prussia": 64, "austria": 99}
    assert all(u.bn_guns == 0 for u in units if u.arm != Arm.INFANTRY)
    assert (by["P-ART-1"].howitzers, by["P-ART-1"].mortars) == (2, 0)
    assert (by["P-ART-2"].howitzers, by["P-ART-2"].mortars) == (2, 3)
    assert sum(u.howitzers for u in units) == 4 and sum(u.mortars for u in units) == 3


def _gun_duel(bn_guns: int):
    w, _, _ = load_testfield()
    a = body("a", "blue", "line", 1000.0, 1400.0, UnitState.LINE, facing=0.0)
    a.bn_guns = bn_guns
    t = body("t", "red", "line", 1000.0, 1850.0, UnitState.LINE, facing=180.0)
    s = make_sim([a, t], world=w)
    s.submit_tasks("blue", [Task(TaskKind.HOLD, "a")])
    s.submit_tasks("red", [Task(TaskKind.HOLD, "t")])
    for _ in range(10):
        s.step()
    fired = [e for e in s.events if e.kind == "fire" and e.data["firer"] == "a"]
    return fired, 600 - t.men


def test_battalion_guns_fire_with_their_battalion_on_the_test_field():
    fired, lost = _gun_duel(2)
    assert fired and {e.data["weapon"] for e in fired} == {"battalion guns"}
    assert fired[0].data["range"] == 450.0
    assert lost > 0
    none, lost0 = _gun_duel(0)  # control: at 450 m a battalion alone does not fire
    assert not none and lost0 == 0


def test_howitzers_get_no_square_bonus_and_mortars_do_not_fire():
    w = make_sim([body("x", "blue", "line", 0.0, 0.0, UnitState.LINE)]).world
    sq = body("s", "red", "line", 1000.0, 1500.0, UnitState.SQUARE)
    ln = body("l", "red", "line", 1000.0, 1500.0, UnitState.LINE)
    can = body("c", "blue", "foot_battery", 1000.0, 1000.0, UnitState.UNLIMBERED, guns=4)
    how = body("h", "blue", "foot_battery", 1000.0, 1000.0, UnitState.UNLIMBERED, guns=4)
    how.howitzers = 4
    mor = body("m", "blue", "foot_battery", 1000.0, 1000.0, UnitState.UNLIMBERED, guns=4)
    mor.mortars = 4
    assert combat.gun_rate(w, can, sq) == pytest.approx(2.5 * combat.gun_rate(w, can, ln))
    assert combat.gun_rate(w, how, sq) == pytest.approx(combat.gun_rate(w, how, ln))
    assert combat.gun_rate(w, how, ln) == pytest.approx(
        combat.HOWITZER_DIRECT_MULT * combat.gun_rate(w, can, ln)
    )
    assert combat.gun_rate(w, mor, ln) == 0.0


# ---------------------------------------------------------------------------
# A line pays for wheeling on the move


def test_a_line_reversing_direction_is_not_back_within_a_minute():
    s = make_sim([body("l", "blue", "line", 1000.0, 1000.0, UnitState.LINE, facing=0.0)])
    u, rt = s.forces.units["l"], s.rt["l"]
    rt.route = [(1000.0, 1020.0), (1000.0, 1000.0)]
    moved = movement.follow_route(s.world, u, rt, 1.0, "walk")
    assert moved == pytest.approx(20.0)  # 20 m forward in half a minute ...
    assert u.y == pytest.approx(1020.0)  # ... then the about-turn takes the rest and more
    assert 0.0 < angle_diff(u.facing_deg, 0.0) < 180.0
    moved = movement.follow_route(s.world, u, rt, 1.0, "walk")  # still wheeling: 135 of 180
    assert moved == pytest.approx(0.0) and angle_diff(u.facing_deg, 180.0) == pytest.approx(45.0)
    moved = movement.follow_route(s.world, u, rt, 1.0, "walk")  # 30 s more, then 20 m back
    assert u.y == pytest.approx(1000.0) and moved == pytest.approx(20.0)
    assert u.facing_deg == pytest.approx(180.0)
    # a column follows its head without paying
    c = body("c", "blue", "line", 1000.0, 1000.0, UnitState.COLUMN, facing=0.0)
    s2 = make_sim([c])
    s2.rt["c"].route = [(1000.0, 1020.0), (1000.0, 1000.0)]
    movement.follow_route(s2.world, c, s2.rt["c"], 1.0, "walk")
    assert c.y == pytest.approx(1000.0)


# ---------------------------------------------------------------------------
# Defensive volleys at a charge spend ammunition


def test_defensive_volleys_at_a_charge_spend_ammunition():
    inf = body("i", "red", "line", 2000.0, 2000.0, UnitState.LINE, facing=90.0)
    cav = body("k", "blue", "cuirassier", 2500.0, 2000.0, UnitState.LINE, facing=270.0, men=600)
    h = body("h", "red", "hussar", 1700.0, 2200.0, UnitState.LINE, men=400)
    s = make_sim([inf, cav, h])
    s.submit_tasks("blue", [Task(TaskKind.CHARGE, "k", Ref(RefKind.ENEMY, "i"))])
    s.submit_tasks(
        "red", [Task(TaskKind.HOLD, "i", state=UnitState.LINE), Task(TaskKind.HOLD, "h")]
    )
    for _ in range(8):
        before = inf.ammo
        s.step()
        if any(e.kind == "melee" for e in s.tick_events):
            break
    fired = any(e.kind == "fire" and e.data["firer"] == "i" for e in s.tick_events)
    # the minute's musketry (if any) plus at least one volley at the charge
    assert before - inf.ammo >= combat.AMMO_MUSKETRY * (2 if fired else 1)


# ---------------------------------------------------------------------------
# A body does not fire through a friendly body in front of it


def _second_line(with_first: bool):
    units = [
        body("b", "blue", "line", 1000.0, 880.0, UnitState.LINE, facing=0.0),
        body("c", "red", "line", 1000.0, 1100.0, UnitState.LINE, facing=180.0),
    ]
    if with_first:
        units.append(body("a", "blue", "line", 1000.0, 1000.0, UnitState.LINE, facing=0.0))
    s = make_sim(units)
    s.submit_tasks("blue", [Task(TaskKind.HOLD, u.id) for u in units if u.side == "blue"])
    s.submit_tasks("red", [Task(TaskKind.HOLD, "c")])
    for _ in range(3):
        s.step()
    return [e for e in s.events if e.kind == "fire" and e.data["firer"] == "b"]


def test_a_second_line_cannot_fire_through_the_first():
    assert _second_line(with_first=False), "control: the second line alone fires at 220 m"
    assert not _second_line(with_first=True)
