"""Musketry at 100 m, canister against a column, cavalry against square and flanked
line, morale collapse and rout, rally."""

from __future__ import annotations

import pytest
from test_engine_kit import body, make_sim

from kriegsspiel import combat
from kriegsspiel.types import Ref, RefKind, Task, TaskKind, UnitState


def _losses_per_min(sim, uid, minutes):
    u = sim.forces.units[uid]
    m0 = u.men
    for _ in range(minutes):
        sim.step()
    return (m0 - u.men) / minutes


def test_hit_rate_table():
    # hits per musket and minute at 50, 100 and 250 m
    assert combat.interp(combat.HIT_RATE, 50.0) == pytest.approx(0.015)
    assert combat.interp(combat.HIT_RATE, 100.0) == pytest.approx(0.008)
    assert combat.interp(combat.HIT_RATE, 250.0) == pytest.approx(0.0008)
    assert combat.interp(combat.HIT_RATE, 60.0) > 1.5 * combat.interp(combat.HIT_RATE, 100.0)


def test_musketry_exchange_at_100m_follows_the_fire_table():
    # the fire table gives 600 * 0.008 * 1.2 = 5.8 men a minute at the outset, a little less
    # as the firing ranks thin and tire
    a = body("a", "blue", "line", 1000.0, 1000.0, UnitState.LINE, facing=0.0)
    b = body("b", "red", "line", 1000.0, 1100.0, UnitState.LINE, facing=180.0)
    s = make_sim([a, b])
    s.submit_tasks("blue", [Task(TaskKind.HOLD, "a")])
    s.submit_tasks("red", [Task(TaskKind.HOLD, "b")])
    s.step()  # orders in; first volleys
    ma, mb = a.men, b.men
    for _ in range(10):
        s.step()
    first = 600 * combat.interp(combat.HIT_RATE, 100.0) * combat.quality_factor(3)
    for lost in (ma - a.men, mb - b.men):
        assert 0.85 * first <= lost / 10 <= 1.05 * first, lost
    assert a.engaged == {"b"} and b.engaged == {"a"}
    assert a.ammo == pytest.approx(100.0 - 2 * 11)


def test_canister_against_a_column():
    g = body("g", "blue", "foot_battery", 1000.0, 1000.0, UnitState.UNLIMBERED, facing=0.0, guns=8)
    col = body("c", "red", "line", 1000.0, 1150.0, UnitState.COLUMN, facing=180.0)
    line = body("l", "red", "line", 1000.0, 1150.0, UnitState.LINE, facing=180.0)
    expect_col = combat.gun_rate(make_sim([g, col]).world, g, col)
    expect_line = combat.gun_rate(make_sim([g, line]).world, g, line)
    assert expect_col == pytest.approx(8 * 4.0 * 2.0)  # 150 m: canister 4.0, column x2
    assert expect_col == pytest.approx(2 * expect_line)
    s = make_sim([g, col])
    s.submit_tasks("red", [Task(TaskKind.HOLD, "c", state=UnitState.COLUMN)])
    s.step()
    assert 600 - col.men == pytest.approx(expect_col, abs=1.5)


def test_guns_take_from_a_small_body_in_proportion_to_the_men_it_presents():
    """Three 6-pounders took 14 to 17 men a minute from columns of 80 to 116."""
    g = body("g", "blue", "foot_battery", 1000.0, 1000.0, UnitState.UNLIMBERED, facing=0.0, guns=3)
    w = make_sim([g]).world
    rate = {
        n: combat.gun_rate(w, g, body("c", "red", "line", 1000.0, 1150.0, UnitState.COLUMN, men=n))
        for n in (100, 300, 600)
    }
    assert rate[600] == rate[300] == pytest.approx(3 * 4.0 * 2.0)  # battalion scale unchanged
    assert rate[100] == pytest.approx(rate[300] / 3.0)
    assert rate[100] / 100 <= rate[600] / 300  # never a larger share of a small body


def test_a_small_company_is_destroyed_at_a_tenth_of_its_strength_not_at_30_men():
    from kriegsspiel import morale

    def survives(men_left: int) -> bool:
        c = body("c", "red", "line", 1000.0, 1000.0, UnitState.LINE, men=50)
        s = make_sim([c, body("b", "blue", "line", 3500.0, 3500.0, UnitState.LINE)])
        c.men = men_left
        morale.morale_phase(s)
        return c.state != UnitState.DESTROYED

    assert survives(29) and survives(6) and not survives(5)
    assert morale.DESTROYED_MIN_MEN <= 5


def test_morale_collapse_and_rout_under_canister():
    g = body("g", "blue", "foot_battery", 1000.0, 1000.0, UnitState.UNLIMBERED, facing=0.0, guns=8)
    col = body("c", "red", "line", 1000.0, 1120.0, UnitState.COLUMN, facing=180.0)
    s = make_sim([g, col])
    s.submit_tasks("red", [Task(TaskKind.HOLD, "c", state=UnitState.COLUMN)])
    for _ in range(8):
        s.step()
        if col.state == UnitState.ROUTED:
            break
    assert col.state == UnitState.ROUTED
    assert any(e.kind == "rout" and e.data["unit"] == "c" for e in s.events)
    y0 = col.y
    s.step()
    s.step()
    assert col.y > y0 + 50.0  # flees away from the guns


def _charge(defender_state, defender_facing, cover=False):
    inf = body("i", "red", "line", 2000.0, 2000.0, defender_state, facing=defender_facing)
    cav = body(
        "k", "blue", "cuirassier", 2500.0, 2000.0, UnitState.LINE, facing=270.0, men=450, quality=4
    )
    units = [inf, cav]
    if cover:
        # a friendly regiment nearby keeps the line from forming square, and an enemy line
        # 150 m to its front holds its attention (it keeps facing north)
        units.append(body("h", "red", "hussar", 1700.0, 2200.0, UnitState.LINE, men=400))
        units.append(body("f", "blue", "line", 2000.0, 2150.0, UnitState.LINE, facing=180.0))
    s = make_sim(units)
    s.submit_tasks("blue", [Task(TaskKind.CHARGE, "k", Ref(RefKind.ENEMY, "i"))])
    s.submit_tasks("red", [Task(TaskKind.HOLD, "i", state=defender_state)])
    if cover:
        s.submit_tasks("blue", [Task(TaskKind.HOLD, "f")])
    for _ in range(8):
        s.step()
        if any(e.kind in ("melee", "charge_aborted") for e in s.tick_events):
            break
    melee = [e for e in s.events if e.kind in ("melee", "charge_aborted")]
    assert melee, "the charge never struck"
    return melee[0], inf, cav


def test_cavalry_charge_into_a_square_is_repulsed():
    ev, inf, cav = _charge(UnitState.SQUARE, 90.0)
    assert ev.kind == "charge_aborted"  # it pulls up: repulsed without a melee
    assert inf.state == UnitState.SQUARE
    assert cav.disorder >= combat.REPULSE_DISORDER
    assert ev.data["gait"] == "gallop"


def test_cavalry_charge_into_a_flanked_line_breaks_it():
    ev, inf, _ = _charge(UnitState.LINE, 0.0, cover=True)  # line faces north, cav from east
    assert "flanked" in ev.data["defender_factor"]
    assert ev.data["outcome"] == "broken"
    assert inf.state == UnitState.ROUTED


def _frontal_charge(disorder: float = 0.0, cav_quality: int = 3, cav_men: int = 600):
    """A fresh line in the open facing east, cuirassiers galloping in from the east; a friendly
    regiment nearby keeps the line from forming square."""
    inf = body("i", "red", "line", 2000.0, 2000.0, UnitState.LINE, facing=90.0)
    inf.disorder = disorder
    cav = body(
        "k",
        "blue",
        "cuirassier",
        2500.0,
        2000.0,
        UnitState.LINE,
        facing=270.0,
        men=cav_men,
        quality=cav_quality,
    )
    h = body("h", "red", "hussar", 1700.0, 2200.0, UnitState.LINE, men=400)
    s = make_sim([inf, cav, h])
    s.submit_tasks("blue", [Task(TaskKind.CHARGE, "k", Ref(RefKind.ENEMY, "i"))])
    s.submit_tasks(
        "red", [Task(TaskKind.HOLD, "i", state=UnitState.LINE), Task(TaskKind.HOLD, "h")]
    )
    for _ in range(8):
        s.step()
        if any(e.kind == "melee" for e in s.tick_events):
            break
    melee = [e for e in s.events if e.kind == "melee"]
    assert melee, "the charge never struck"
    return melee[0], inf


def test_steady_line_holds_a_frontal_charge_of_equal_quality():
    ev, inf = _frontal_charge()
    assert ev.data["defender_factor"] == "steady line" and ev.data["gait"] == "gallop"
    assert ev.data["ratio"] < 1.0, ev.data
    assert ev.data["outcome"] != "broken"
    assert inf.state != UnitState.ROUTED or ev.data["outcome"] == "melee"  # no rout at impact


def test_disordered_line_still_breaks_under_a_frontal_charge():
    ev, inf = _frontal_charge(disorder=60.0)  # recovers on the way; still >= 30 at impact
    assert ev.data["defender_factor"] == "line flanked or disordered"
    assert ev.data["ratio"] > combat.BREAK_RATIO and ev.data["outcome"] == "broken"
    assert inf.state == UnitState.ROUTED


def test_infantry_forms_square_when_cavalry_threatens():
    inf = body("i", "red", "line", 2000.0, 2000.0, UnitState.LINE, facing=90.0)
    cav = body("k", "blue", "cuirassier", 2350.0, 2000.0, UnitState.LINE, facing=270.0, men=450)
    s = make_sim([inf, cav])
    s.submit_tasks("red", [Task(TaskKind.HOLD, "i")])
    for _ in range(3):
        s.step()
    assert inf.state == UnitState.SQUARE


def test_melee_values_and_repulse():
    a = body("a", "blue", "line", 0, 0, UnitState.LINE, men=300, quality=2)
    d = body("d", "red", "line", 0, 50, UnitState.LINE, facing=180.0, men=600, quality=4)
    s = make_sim([a, d])
    av = combat.attacker_value(a, "walk")
    dv, why = combat.defender_value(s.world, d, a)
    assert why == "line" and av / dv < combat.REPULSE_RATIO


def test_rally_reforms_a_routed_body_sooner_than_self_rally():
    def run(rally: bool) -> int:
        u = body("u", "blue", "line", 1000.0, 1000.0, UnitState.ROUTED)
        u.morale = 30.0
        s = make_sim([u])
        if rally:
            s.submit_tasks("blue", [Task(TaskKind.RALLY, "u")])
        for t in range(120):
            s.step()
            if u.state != UnitState.ROUTED:
                return t
        return 999

    with_order, alone = run(True), run(False)
    assert with_order < 15
    assert alone > with_order
    assert alone < 999


@pytest.mark.parametrize(
    "rally, morale, reforms",
    [
        (True, 43.0, True),
        (True, 42.5, False),  # under RALLY the bar is RALLY_MORALE
        (False, 54.5, True),
        (False, 54.0, False),  # alone it is SELF_RALLY_MORALE
    ],
)
def test_the_re_forming_thresholds_are_the_documented_rule(rally, morale, reforms):
    """The spec's "Rout and re-forming": 45 under RALLY, 55 alone, tested after the minute's
    recovery (2.0 under RALLY, 0.5 alone): 43 + 2 re-forms, 42.5 + 2 does not."""
    from kriegsspiel import morale as mor

    assert (mor.RALLY_MORALE, mor.SELF_RALLY_MORALE) == (45.0, 55.0)
    u = body("u", "blue", "line", 1000.0, 1000.0, UnitState.ROUTED)
    s = make_sim([u])
    if rally:
        s.submit_tasks("blue", [Task(TaskKind.RALLY, "u")])
    s.run(2)  # the order arrives (the hq is with the body)
    u.state, u.morale = UnitState.ROUTED, morale
    s.rt["u"].rally_at = 0
    mor.recovery_phase(s)
    assert (u.state != UnitState.ROUTED) == reforms


def test_a_rallied_body_resumes_its_formations_advance():
    """Rallied cuirassiers stood still to the end of the day because rallying replaced the
    advance with a HOLD where they stood."""
    from kriegsspiel import morale

    k = body("k", "blue", "cuirassier", 500.0, 1000.0, UnitState.LINE, facing=90.0, men=450)
    far = body("r", "red", "line", 3800.0, 3800.0, UnitState.LINE)
    s = make_sim([k, far])
    task = Task(TaskKind.ADVANCE, "k", Ref(RefKind.POINT, point=(3000.0, 1000.0)))
    s.submit_tasks("blue", [task])
    s.run(3)
    morale.rout(s, k, "test", "repulse")
    k.morale = 70.0  # recovers at once; the clock (4 minutes) decides when it rallies
    for _ in range(30):
        s.step()
        if k.state != UnitState.ROUTED:
            break
    assert k.state != UnitState.ROUTED
    rallied_x = k.x
    rally = next(e for e in s.events if e.kind == "rally")
    assert rally.data["resumed"] == "advance" and k.task.kind == TaskKind.ADVANCE
    s.run(10)
    assert k.x > rallied_x + 500.0  # marching on toward its objective
