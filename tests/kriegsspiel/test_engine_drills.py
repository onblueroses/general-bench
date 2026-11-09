"""Drills: deployment distance, withdraw with a covering body, screen, support,
bombard standoff, MOVE_HQ."""

from __future__ import annotations

import math

from test_engine_kit import body, make_sim

from kriegsspiel.geometry import dist
from kriegsspiel.types import Manner, Ref, RefKind, Task, TaskKind, UnitState


def test_column_deploys_into_line_at_400m_from_known_enemy():
    a = body("a", "blue", "line", 1000.0, 500.0, UnitState.COLUMN)
    e = body("e", "red", "line", 1000.0, 1500.0, UnitState.LINE, facing=180.0)
    s = make_sim([a, e])
    s.submit_tasks(
        "blue",
        [
            Task(
                TaskKind.ATTACK, "a", Ref(RefKind.POINT, point=(1000, 1600)), manner=Manner.MEASURED
            )
        ],
    )
    deployed_at = None
    for _ in range(40):
        s.step()
        if a.state == UnitState.LINE and deployed_at is None:
            deployed_at = 1500.0 - a.y
    assert deployed_at is not None and 380.0 <= deployed_at <= 420.0


def test_withdraw_moves_away_and_the_rear_body_covers():
    a1 = body("a1", "blue", "line", 1000.0, 1000.0, UnitState.LINE, brigade="bb")
    a2 = body("a2", "blue", "line", 1000.0, 800.0, UnitState.LINE, brigade="bb")
    e = body("e", "red", "line", 1000.0, 1700.0, UnitState.LINE, facing=180.0)
    s = make_sim([a1, a2, e], hq={"blue": (1000.0, 900.0)})
    s.submit_tasks("blue", [Task(TaskKind.WITHDRAW, "bb")])
    s.run(5)
    assert a1.y == 1000.0  # nearest the enemy: still covering
    assert a2.y < 800.0 - 50.0
    s.run(15)
    assert a1.y < 1000.0


def test_screen_keeps_its_distance():
    h = body("h", "blue", "hussar", 1000.0, 1000.0, UnitState.COLUMN, men=400)
    e = body("e", "red", "line", 1000.0, 1450.0, UnitState.COLUMN, facing=180.0)
    s = make_sim([h, e])
    s.submit_tasks("blue", [Task(TaskKind.SCREEN, "h", Ref(RefKind.POINT, point=(1000, 1300)))])
    s.run(6)
    assert dist((h.x, h.y), (e.x, e.y)) >= 600.0


def test_support_follows_at_300m():
    lead = body("l", "blue", "line", 1000.0, 1000.0, UnitState.COLUMN, brigade="lead")
    sup = body("s", "blue", "line", 1500.0, 500.0, UnitState.COLUMN, brigade="sup")
    s = make_sim([lead, sup], hq={"blue": (1200.0, 800.0)})
    s.submit_tasks(
        "blue",
        [
            Task(TaskKind.ADVANCE, "lead", Ref(RefKind.POINT, point=(1000, 2500))),
            Task(TaskKind.SUPPORT, "sup", Ref(RefKind.FRIENDLY, "lead")),
        ],
    )
    s.run(70)  # the leader halts at 2,500 m after ~25 minutes; the support closes up
    assert 250.0 <= lead.y - sup.y <= 350.0
    assert abs(sup.x - lead.x) < 60.0


def test_bombard_unlimbers_at_800m():
    g = body("g", "blue", "foot_battery", 1000.0, 200.0, UnitState.LIMBERED, guns=8)
    e = body("e", "red", "line", 1000.0, 1800.0, UnitState.LINE, facing=180.0)
    s = make_sim([g, e])
    s.submit_tasks("blue", [Task(TaskKind.BOMBARD, "g", Ref(RefKind.ENEMY, "e"))])
    for _ in range(60):
        s.step()
        if g.state == UnitState.UNLIMBERED:
            break
    assert g.state == UnitState.UNLIMBERED
    assert 760.0 <= 1800.0 - g.y <= 820.0
    s.run(3)
    assert e.casualties > 0


def test_move_hq_shortens_the_courier_ride():
    u = body("u", "blue", "line", 3000.0, 3000.0, UnitState.LINE)
    s = make_sim([u], hq={"blue": (500.0, 500.0)})
    s.submit_tasks(
        "blue", [Task(TaskKind.MOVE_HQ, "blue-army", Ref(RefKind.POINT, point=(2500.0, 2500.0)))]
    )
    s.run(20)
    hq = s.forces.hq("blue-army")
    assert math.isclose(hq[0], 2500.0) and math.isclose(hq[1], 2500.0)
