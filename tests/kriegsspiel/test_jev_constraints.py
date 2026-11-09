"""What the staff's prohibitions and triggers ask of the engine: Task.forbid honoured by the
drill, and a start condition on a friendly formation holding a place. Each has a control that
shows the behaviour without the constraint."""

from __future__ import annotations

import math

from test_engine_kit import body, make_sim

from kriegsspiel.command import condition_met
from kriegsspiel.log import task_from_json, task_to_json
from kriegsspiel.types import (
    Condition,
    ConditionKind,
    Forbid,
    Manner,
    Ref,
    RefKind,
    Task,
    TaskKind,
    UnitState,
)


def _dist(a, b) -> float:
    return math.hypot(a.x - b.x, a.y - b.y)


def _contacts(s) -> list[tuple[int, str, str]]:
    seen: list[tuple[int, str, str]] = []
    orig = s.request_melee

    def spy(a, d, gait):
        seen.append((s.now, a.id, d.id))
        orig(a, d, gait)

    s.request_melee = spy
    return seen


def _cavalry_against_line(forbid: list[str]):
    k = body("k", "blue", "cuirassier", 2000.0, 2400.0, UnitState.LINE, facing=180.0, men=450)
    e = body("e", "red", "line", 2000.0, 2000.0, UnitState.LINE, facing=0.0)
    s = make_sim([k, e])
    seen = _contacts(s)
    s.submit_tasks(
        "blue", [Task(TaskKind.SUPPORT, "k", Ref(RefKind.FRIENDLY, "blue-b-k"), forbid=forbid)]
    )
    s.submit_tasks("red", [Task(TaskKind.HOLD, "e")])
    for _ in range(15):
        s.step()
    return seen, k, e


def test_cavalry_forbidden_to_charge_formed_infantry_does_not():
    seen, k, e = _cavalry_against_line([Forbid.CHARGE_FORMED_INFANTRY.value])
    assert not seen and _dist(k, e) > 300.0
    seen, _, _ = _cavalry_against_line([])  # control: on_contact ENGAGE charges the line
    assert seen


def _infantry_attack(forbid: list[str]):
    a = body("a", "blue", "line", 2000.0, 2300.0, UnitState.LINE, facing=180.0, men=900, quality=5)
    e = body("e", "red", "line", 2000.0, 2000.0, UnitState.LINE, facing=0.0, men=300, quality=1)
    s = make_sim([a, e])
    seen = _contacts(s)
    s.submit_tasks(
        "blue",
        [Task(TaskKind.ATTACK, "a", Ref(RefKind.ENEMY, "e"), manner=Manner.BOLD, forbid=forbid)],
    )
    s.submit_tasks("red", [Task(TaskKind.HOLD, "e")])
    for _ in range(40):
        s.step()
        if seen or e.state == UnitState.ROUTED:
            break
    return seen, a, e


def test_infantry_forbidden_to_attack_does_not_assault():
    seen, _a, e = _infantry_attack([Forbid.ATTACK.value])
    assert not seen and e.state != UnitState.ROUTED
    seen, _a, e = _infantry_attack([])  # control
    assert seen or e.state == UnitState.ROUTED


def test_start_when_a_friendly_formation_holds_a_place():
    a = body("a", "blue", "line", 1000.0, 1000.0, UnitState.COLUMN)
    b = body("b", "blue", "line", 1500.0, 1000.0, UnitState.COLUMN)
    s = make_sim([a, b])
    cond = Condition(
        ConditionKind.WHEN_REACHED,
        subject=Ref(RefKind.FRIENDLY, "blue-b-a"),
        place=Ref(RefKind.POINT, "the knoll", (3000.0, 1000.0)),
    )
    assert not condition_met(s, "blue", "blue-b-b", cond)
    a.x = 2950.0
    assert condition_met(s, "blue", "blue-b-b", cond)
    # the old meaning without a place: the subject's own arrival, unchanged
    old = Condition(ConditionKind.WHEN_REACHED, subject=Ref(RefKind.FRIENDLY, "blue-b-a"))
    assert old.place is None


def test_forbid_and_place_round_trip_and_stay_out_of_old_logs():
    t = Task(
        TaskKind.SUPPORT,
        "x",
        Ref(RefKind.FRIENDLY, "y"),
        start=Condition(
            ConditionKind.WHEN_REACHED,
            Ref(RefKind.FRIENDLY, "y"),
            place=Ref(RefKind.FEATURE, "Křečhoř"),
        ),
        forbid=["CHARGE_FORMED_INFANTRY", "ADVANCE_BEYOND:Radovesnice"],
    )
    d = task_to_json(t)
    back = task_from_json(d)
    assert back.forbid == t.forbid and back.start.place.name == "Křečhoř"
    assert back.forbids(Forbid.ADVANCE_BEYOND) and not back.forbids(Forbid.ATTACK)
    plain = task_to_json(Task(TaskKind.HOLD, "x", start=Condition(ConditionKind.TIME, at=5)))
    assert "forbid" not in plain and "place" not in plain["start"]
