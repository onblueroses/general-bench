"""Reproductions for the drill's contact, recovery and square rules and for the courier and
condition rules of command.py; each failed before its fix."""

from __future__ import annotations

import math

from test_engine_kit import body, make_sim

from kriegsspiel.combat import CONTACT_M
from kriegsspiel.drill import SCREEN_SQUARE_MAX_M, SCREEN_SQUARE_MIN_M
from kriegsspiel.types import Cover, Manner, Ref, RefKind, Task, TaskKind, UnitState


def _dist(a, b) -> float:
    return math.hypot(a.x - b.x, a.y - b.y)


def _spy_contacts(s) -> list[tuple[int, str, str, float]]:
    """Record every contact request the drill makes: (tick, attacker, defender, distance)."""
    seen: list[tuple[int, str, str, float]] = []
    orig = s.request_melee

    def spy(a, d, gait):
        seen.append((s.now, a.id, d.id, _dist(a, d)))
        orig(a, d, gait)

    s.request_melee = spy
    return seen


# ---------------------------------------------------------------------------
# No charge or assault while the recovery clock runs


def test_cavalry_does_not_charge_while_its_attack_clock_runs():
    k = body("k", "blue", "cuirassier", 2000.0, 2300.0, UnitState.LINE, facing=180.0, men=450)
    e = body("e", "red", "line", 2000.0, 2000.0, UnitState.LINE, facing=0.0)
    h = body("h", "red", "hussar", 1700.0, 1850.0, UnitState.LINE, men=300)  # keeps e in line
    s = make_sim([k, e, h])
    s.rt["k"].attack_at = 12
    contacts = _spy_contacts(s)
    s.submit_tasks("blue", [Task(TaskKind.CHARGE, "k", Ref(RefKind.ENEMY, "e"))])
    s.submit_tasks("red", [Task(TaskKind.HOLD, "e"), Task(TaskKind.HOLD, "h")])
    for _ in range(12):
        s.step()
        assert _dist(k, e) > 250.0, (s.now, _dist(k, e))
    assert not contacts
    for _ in range(6):  # control: once the clock has run, it charges
        s.step()
    assert contacts and contacts[0][0] >= 12


def test_infantry_does_not_assault_while_its_attack_clock_runs():
    a = body("a", "blue", "line", 2000.0, 2300.0, UnitState.LINE, facing=180.0, men=900, quality=5)
    e = body("e", "red", "line", 2000.0, 2000.0, UnitState.LINE, facing=0.0, men=300, quality=1)
    s = make_sim([a, e])
    s.rt["a"].attack_at = 25
    contacts = _spy_contacts(s)
    s.submit_tasks(
        "blue", [Task(TaskKind.ATTACK, "a", Ref(RefKind.ENEMY, "e"), manner=Manner.BOLD)]
    )
    s.submit_tasks("red", [Task(TaskKind.HOLD, "e")])
    for _ in range(25):
        s.step()
        assert _dist(a, e) >= 70.0, (s.now, _dist(a, e))
    assert not contacts
    for _ in range(10):  # control: then it goes in with the bayonet
        s.step()
        if contacts or e.state == UnitState.ROUTED:
            break
    assert contacts or e.state == UnitState.ROUTED


# ---------------------------------------------------------------------------
# A body stops at contact distance; it never steps into or through an enemy


def test_a_charge_makes_contact_at_the_contact_distance_not_inside_it():
    k = body("k", "blue", "cuirassier", 2000.0, 2400.0, UnitState.LINE, facing=180.0, men=450)
    e = body("e", "red", "line", 2000.0, 2000.0, UnitState.LINE, facing=0.0)
    h = body("h", "red", "hussar", 1700.0, 1850.0, UnitState.LINE, men=300)
    s = make_sim([k, e, h])
    contacts = _spy_contacts(s)
    s.submit_tasks("blue", [Task(TaskKind.CHARGE, "k", Ref(RefKind.ENEMY, "e"))])
    s.submit_tasks("red", [Task(TaskKind.HOLD, "e"), Task(TaskKind.HOLD, "h")])
    for _ in range(6):
        s.step()
        if contacts:
            break
    assert contacts
    assert CONTACT_M <= contacts[0][3] <= CONTACT_M + 1.0, contacts[0]  # bisection slack


def test_a_refused_contact_does_not_carry_the_body_through_the_enemy():
    from kriegsspiel.drill import Plan, _move

    k = body("k", "blue", "cuirassier", 2000.0, 2200.0, UnitState.LINE, facing=180.0, men=450)
    e = body("e", "red", "line", 2000.0, 2000.0, UnitState.LINE, facing=0.0)
    s = make_sim([k, e])
    rt = s.rt["k"]
    closest = math.inf
    for _ in range(6):  # the engine refuses every contact (as while reorganising)
        _move(s, k, rt, Plan(goal=(2000.0, 1500.0), gait="trot", assault=True, direct=True), 1.0)
        s.melee_requests = []
        closest = min(closest, _dist(k, e))
    assert closest >= CONTACT_M - 1e-6, closest
    assert k.y > e.y  # still on its own side


def test_a_march_past_an_enemy_body_stops_short_of_it():
    from kriegsspiel.drill import Plan, _move

    c = body("c", "blue", "line", 2000.0, 2200.0, UnitState.COLUMN, facing=180.0)
    e = body("e", "red", "line", 2000.0, 2150.0, UnitState.LINE, facing=0.0)
    s = make_sim([c, e])
    rt = s.rt["c"]
    c.x, c.y = 2000.0, 2190.0  # walked into contact range of a body that moved up
    for _ in range(3):
        _move(s, c, rt, Plan(goal=(2000.0, 1500.0), state=UnitState.COLUMN, direct=True), 1.0)
    assert c.y >= 2190.0 - 1e-6  # no closer, so not through
    _move(s, c, rt, Plan(goal=(2000.0, 2600.0), state=UnitState.COLUMN, direct=True), 1.0)
    assert c.y > 2200.0  # it may draw off


# ---------------------------------------------------------------------------
# An assault is not carried through a routed body in its path


def test_a_charge_stops_short_of_fugitives_in_its_path():
    k = body("k", "blue", "cuirassier", 2000.0, 2700.0, UnitState.LINE, facing=180.0, men=450)
    e = body("e", "red", "line", 2000.0, 2000.0, UnitState.LINE, facing=0.0)
    r = body("r", "red", "line", 2000.0, 2350.0, UnitState.ROUTED, facing=180.0, men=300)
    h = body("h", "red", "hussar", 1700.0, 1850.0, UnitState.LINE, men=300)
    s = make_sim([k, e, r, h], hq={"red": (2000.0, 3900.0)})  # r flees north, across k's path
    s.rt["r"].rally_at = 999
    contacts = _spy_contacts(s)
    s.submit_tasks("blue", [Task(TaskKind.CHARGE, "k", Ref(RefKind.ENEMY, "e"))])
    s.submit_tasks("red", [Task(TaskKind.HOLD, "e"), Task(TaskKind.HOLD, "h")])
    closest = math.inf
    for _ in range(10):
        s.step()
        closest = min(closest, _dist(k, r))
    assert not [c for c in contacts if c[2] == "r"], contacts
    assert not [ev for ev in s.events if ev.kind == "pursuit"]
    assert closest >= CONTACT_M - 1e-6


# ---------------------------------------------------------------------------
# Cavalry pulls up at the recognition range of a steady square


def test_cavalry_pulls_up_at_the_recognition_range_of_a_steady_square():
    from kriegsspiel.combat import SQUARE_RECOGNISE_M

    sq = body("i", "red", "line", 2000.0, 2000.0, UnitState.SQUARE, facing=0.0)
    k = body("k", "blue", "cuirassier", 2000.0, 2500.0, UnitState.LINE, facing=180.0, men=450)
    s = make_sim([sq, k])
    contacts = _spy_contacts(s)
    s.submit_tasks("blue", [Task(TaskKind.CHARGE, "k", Ref(RefKind.ENEMY, "i"))])
    s.submit_tasks("red", [Task(TaskKind.HOLD, "i", state=UnitState.SQUARE)])
    for _ in range(8):
        s.step()
        if contacts:
            break
    assert contacts and contacts[0][2] == "i"
    assert SQUARE_RECOGNISE_M <= contacts[0][3] <= SQUARE_RECOGNISE_M + 1.0, contacts[0]
    assert [e for e in s.events if e.kind == "charge_aborted"]
    assert not [e for e in s.events if e.kind == "melee"]


# ---------------------------------------------------------------------------
# The square reflex wants exposed flanks; Grenzer, skirmishers and bodies in cover do not
# square; a square stands until the cavalry has been gone for 3 minutes


def _brigade_line(n: int = 3, y: float = 2000.0):
    from kriegsspiel.units import INTERVAL_M, frontage

    probe = body("p", "red", "line", 0.0, 0.0, UnitState.LINE)
    step = frontage(probe) + INTERVAL_M
    x0 = 2000.0 - step * (n - 1) / 2.0
    return [
        body(f"i{k}", "red", "line", x0 + k * step, y, UnitState.LINE, facing=0.0, brigade="rb")
        for k in range(n)
    ]


def _threat(units, cav_y: float = 2350.0, extra=(), world=None):
    k = body("k", "blue", "cuirassier", 2000.0, cav_y, UnitState.LINE, facing=180.0, men=450)
    s = make_sim([*units, k, *extra], world=world)
    s.submit_tasks("blue", [Task(TaskKind.HOLD, "k")])
    s.submit_tasks("red", [Task(TaskKind.HOLD, u.id) for u in units if u.side == "red"])
    return s, k


def test_a_line_with_covered_flanks_receives_cavalry_in_line():
    line = _brigade_line()
    s, _ = _threat(line)
    s.run(4)
    assert line[1].state == UnitState.LINE and s.rt["i1"].change_to is None
    assert line[0].state == UnitState.SQUARE  # the end battalions' outer flanks are open
    assert line[2].state == UnitState.SQUARE


def test_a_lone_line_with_friendly_cavalry_at_500m_does_not_square():
    i = body("i", "red", "line", 2000.0, 2000.0, UnitState.LINE, facing=0.0)
    h = body("h", "red", "hussar", 2000.0, 1500.0, UnitState.LINE, men=300)
    s, _ = _threat([i], extra=(h,))
    s.submit_tasks("red", [Task(TaskKind.HOLD, "h")])
    s.run(4)
    assert i.state == UnitState.LINE


def test_a_square_re_forms_once_the_cavalry_is_no_longer_seen():
    """A battalion stood in square 27 minutes after the dragoons left, held by a remembered
    sighting at its old place (memory keeps it 30 minutes)."""
    from kriegsspiel.drill import CAV_SIGHT_FRESH_MIN

    i = body("i", "red", "line", 2000.0, 1000.0, UnitState.LINE, facing=0.0)
    s, k = _threat([i], cav_y=1350.0)
    s.run(5)
    assert i.state == UnitState.SQUARE
    k.x, k.y = 3900.0, 3900.0  # gone out of sight (3.4 km); the brigade still remembers it
    s.run(1)
    assert "k" in s.vision.known("red-b-i")
    for _ in range(CAV_SIGHT_FRESH_MIN + 10):
        s.step()
        if i.state == UnitState.LINE:
            break
    assert i.state == UnitState.LINE, (s.now, i.state, s.rt["i"].change_to)
    assert "k" in s.vision.known("red-b-i")  # remembered, but no longer a threat to square for


def test_grenzer_evade_toward_cover_instead_of_squaring():
    from test_engine_kit import flat_world

    def wood(X, Y, c):
        c[(X > 1700) & (X < 1800) & (Y > 1850) & (Y < 2150)] = Cover.WOOD
        return c

    g = body("g", "red", "line", 2100.0, 2000.0, UnitState.LINE, facing=0.0)
    from kriegsspiel.types import UnitKind

    g.kind = UnitKind.GRENZER
    k = body("k", "blue", "cuirassier", 2100.0, 2350.0, UnitState.LINE, facing=180.0, men=450)
    s = make_sim([g, k], world=flat_world(cover=wood))
    s.submit_tasks("blue", [Task(TaskKind.HOLD, "k")])
    s.submit_tasks("red", [Task(TaskKind.HOLD, "g")])
    for _ in range(12):
        s.step()
        assert g.state != UnitState.SQUARE and s.rt["g"].change_to != "square"
    assert s.world.cover(g.x, g.y) == Cover.WOOD, (g.x, g.y)


def test_skirmishers_in_a_village_stay_in_it():
    from test_engine_kit import flat_world

    def village(X, Y, c):
        c[(X > 1900) & (X < 2100) & (Y > 1900) & (Y < 2100)] = Cover.VILLAGE
        return c

    sk = body("s", "red", "line", 2000.0, 2090.0, UnitState.SKIRMISH, facing=0.0)  # at the edge
    s, _ = _threat([sk], world=flat_world(cover=village))
    s.run(5)
    assert s.command.cav_seen  # it saw the cavalry
    assert sk.state == UnitState.SKIRMISH and (sk.x, sk.y) == (2000.0, 2090.0)


def test_a_square_reforms_line_three_minutes_after_the_cavalry_has_gone():
    i = body("i", "red", "line", 2000.0, 2000.0, UnitState.LINE, facing=0.0)
    s, k = _threat([i])
    s.run(4)
    assert i.state == UnitState.SQUARE
    k.x, k.y = 2000.0, 2700.0  # the regiment rides off (700 m: out of the 600 m)
    s.rt["k"].route, s.rt["k"].slot = [], (2000.0, 2700.0)
    gone_at = s.now
    changed = None
    for _ in range(8):
        s.step()
        if s.rt["i"].change_to == "line" or i.state == UnitState.LINE:
            changed = s.now - 1
            break
    assert changed is not None and changed - gone_at >= 3, (gone_at, changed)


# ---------------------------------------------------------------------------
# Cavalry that pulled up before a steady square does not charge it again


def _square_and_regiment(extra=()):
    sq = body("i", "red", "line", 2000.0, 2000.0, UnitState.SQUARE, facing=0.0)
    k = body("k", "blue", "cuirassier", 2000.0, 2600.0, UnitState.LINE, facing=180.0, men=450)
    s = make_sim([sq, k, *extra])
    s.submit_tasks("blue", [Task(TaskKind.CHARGE, "k", Ref(RefKind.ENEMY, "i"))])
    s.submit_tasks(
        "red",
        [Task(TaskKind.HOLD, "i", state=UnitState.SQUARE)]
        + [Task(TaskKind.HOLD, x.id) for x in extra],
    )
    return s, sq, k


def test_cavalry_pulls_up_before_a_square_once_and_then_screens_it():
    s, sq, k = _square_and_regiment()
    s.run(60)
    pullups = [e for e in s.events if e.kind == "charge_aborted"]
    assert len(pullups) == 1, [e.tick for e in pullups]
    assert SCREEN_SQUARE_MIN_M - 1.0 <= _dist(k, sq) <= SCREEN_SQUARE_MAX_M + 1.0, _dist(k, sq)


def test_cavalry_that_pulled_up_takes_another_target():
    g = body("g", "red", "foot_battery", 2600.0, 2200.0, UnitState.LIMBERED, guns=6)
    s, _, _ = _square_and_regiment(extra=(g,))
    for _ in range(40):
        s.step()
        if [e for e in s.events if e.kind == "melee" and e.data["defender"] == "g"]:
            break
    assert len([e for e in s.events if e.kind == "charge_aborted"]) == 1
    assert [e for e in s.events if e.kind == "melee" and e.data["defender"] == "g"]


def test_a_charge_at_another_target_does_not_pull_up_again_on_the_way_past():
    from kriegsspiel.drill import Plan, _move

    sq = body("i", "red", "line", 2000.0, 2000.0, UnitState.SQUARE, facing=0.0)
    g = body("g", "red", "foot_battery", 2000.0, 1500.0, UnitState.LIMBERED, guns=6)
    k = body("k", "blue", "cuirassier", 2030.0, 2300.0, UnitState.LINE, facing=180.0, men=450)
    s = make_sim([sq, g, k])
    s.command.pullups["k>i"] = 0
    contacts = _spy_contacts(s)
    for _ in range(3):  # straight at the battery, past the square it pulled up before
        _move(s, k, s.rt["k"], Plan(goal=(g.x, g.y), gait="gallop", assault=True, direct=True), 1.0)
    assert not [c for c in contacts if c[2] == "i"], contacts


# ---------------------------------------------------------------------------
# A courier with no way across does not ride over the water


def _river(gap: bool):
    from test_engine_kit import flat_world

    def cover(X, Y, c):
        band = (Y > 1900) & (Y < 2000)
        if gap:
            band &= ~((X > 3500) & (X < 3600))
        c[band] = Cover.WATER
        return c

    return flat_world(cover=cover)


def _order_across(gap: bool):
    from kriegsspiel.types import MessageKind

    u = body("u", "blue", "line", 1000.0, 3000.0, UnitState.LINE)
    s = make_sim([u], world=_river(gap), hq={"blue": (1000.0, 1000.0)})
    s.submit_tasks("blue", [Task(TaskKind.ADVANCE, "u", Ref(RefKind.POINT, point=(1000, 3500)))])
    s.run(30)
    notes = [
        m
        for m in s.command.messages
        if m.kind == MessageKind.REPORT and "could not get through" in m.text
    ]
    return s, u, notes


def test_an_order_with_no_way_across_the_water_is_not_delivered():
    from kriegsspiel.command import attempt_minutes

    s, u, notes = _order_across(gap=False)
    assert u.task is None  # before: delivered in 8 minutes, straight over the river
    assert [e for e in s.events if e.kind == "order_undeliverable"]
    assert len(notes) == 1 and notes[0].received_at == math.ceil(
        attempt_minutes((1000.0, 1000.0), (1000.0, 3000.0))
    )
    assert notes[0] in s.picture("blue").reports


def test_an_order_round_by_the_ford_is_delivered_late():
    _, u, notes = _order_across(gap=True)
    assert u.task is not None and not notes
    assert u.task.received_at > 2000.0 / 250.0 + 4.0  # the detour by the ford


# ---------------------------------------------------------------------------
# WHEN_ROUTS and WHEN_ENEMY_SEEN read the commander's knowledge


def test_when_routs_waits_until_the_formation_sees_the_rout():
    from kriegsspiel.types import Condition, ConditionKind

    near = body("n", "blue", "line", 2000.0, 2900.0, UnitState.LINE, brigade="near")
    far = body("f", "blue", "line", 2000.0, 200.0, UnitState.LINE, brigade="far")
    e = body("e", "red", "line", 2000.0, 3800.0, UnitState.LINE, facing=180.0)
    s = make_sim([near, far, e], hq={"blue": (2000.0, 2800.0), "red": (2000.0, 3900.0)})
    routs = Condition(ConditionKind.WHEN_ROUTS, subject=Ref(RefKind.ENEMY, "e"))
    s.submit_tasks(
        "blue",
        [
            Task(TaskKind.HOLD, "near", Ref(RefKind.POINT, point=(2000.0, 2800.0)), start=routs),
            Task(TaskKind.HOLD, "far", Ref(RefKind.POINT, point=(2000.0, 300.0)), start=routs),
        ],
    )
    s.run(3)
    assert near.task is None and far.task is None
    e.state = UnitState.ROUTED  # the truth changes; only the near brigade can see it
    s.rt["e"].rally_at = 999
    s.run(12)  # the far brigade's aide arrives at minute 11
    assert not s.waiting_tasks or all(t.formation == "far" for t in s.waiting_tasks)
    assert [m for m in s.command.messages if m.recipient == "far" and m.received_at]
    assert near.task is not None  # control: it saw the rout
    assert far.task is None, "3.6 km off, the far brigade cannot know the rout"


def test_army_when_enemy_seen_waits_for_the_report():
    from kriegsspiel.types import Condition, ConditionKind

    u = body("u", "blue", "line", 1000.0, 1000.0, UnitState.LINE)
    e = body("e", "red", "line", 1000.0, 2500.0, UnitState.LINE, facing=180.0)
    s = make_sim([u, e], hq={"blue": (3900.0, 100.0), "red": (1000.0, 3900.0)})
    seen = Condition(ConditionKind.WHEN_ENEMY_SEEN)
    s.submit_tasks("blue", [Task(TaskKind.HOLD, "blue-army", start=seen)])
    s.run(2)
    assert "e" in s.vision.known(u.parent)  # the brigade sees the enemy at once
    assert u.task is None  # before: the army's condition read the brigade's sight
    s.run(20)  # the first-contact report reaches the hq
    assert s.picture("blue").contacts and u.task is not None
