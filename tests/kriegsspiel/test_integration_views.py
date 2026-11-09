"""Integration of the staff and the engine (the jev-resolver requests): arms, feature
aliases and relative places in the SideView, stable enemy names, task sequels."""

from __future__ import annotations

from test_engine_kit import KOLIN, body, load_testfield, make_sim
from test_engine_replay import orders

from kriegsspiel.command import resolve_ref
from kriegsspiel.geometry import dist
from kriegsspiel.jev import Answer, JevClient
from kriegsspiel.log import task_from_json, task_to_json
from kriegsspiel.scenario import load
from kriegsspiel.sim import Sim
from kriegsspiel.staff import JevStaff
from kriegsspiel.types import (
    Arm,
    EnemyView,
    FormationView,
    Ref,
    RefKind,
    SideView,
    Task,
    TaskKind,
    UnitState,
)


def kolin_sim() -> Sim:
    w, f, u, _, meta = load(KOLIN)
    return Sim(w, f, u, seed=1, clock_start=meta.start)


def test_side_view_carries_arms_aliases_and_places():
    s = kolin_sim()
    sv = s.side_view("prussia")
    by = {f.id: f for f in sv.formations}
    assert by["P-ZIE"].arm == Arm.CAVALRY and by["P-CAV"].arm == Arm.CAVALRY
    assert by["P-ART"].arm == Arm.ARTILLERY and by["P-MAN"].arm == Arm.INFANTRY
    assert by["P"].arm is None  # mixed arms
    assert "the road" in sv.feature_aliases["Kaiserstrasse"]
    names = {"our left flank", "our right flank", "our centre", "our rear"}
    assert names == set(sv.places) and names <= set(sv.feature_names)
    left, right = sv.places["our left flank"], sv.places["our right flank"]
    assert dist(left, right) > 1000.0  # the army is spread over kilometres
    # a Ref to a relative place resolves, as a point and by name alone
    p, _ = resolve_ref(s, "prussia", Ref(RefKind.FEATURE, "our left flank"))
    assert p == left


def test_staff_offers_places_as_points_and_groups_numbered_enemies():
    sv = SideView(
        side="blue",
        formations=[FormationView("a", "A brigade", "Smith", arm=Arm.INFANTRY)],
        feature_names=["Hill", "our left flank"],
        enemies=[
            EnemyView("the enemy infantry near Hill", Arm.INFANTRY, None, 0, 0, 0, "k1"),
            EnemyView("the enemy infantry near Hill (2)", Arm.INFANTRY, None, 0, 0, 0, "k2"),
            EnemyView("the enemy cavalry near Hill", Arm.CAVALRY, None, 0, 0, 0, "k3"),
        ],
        feature_aliases={"Hill": ["the hill"]},
        places={"our left flank": (10.0, 20.0)},
    )
    vocab = JevStaff._vocab(sv)
    descs = [o.desc for o in vocab]
    assert "Hill (also: the hill)" in descs
    left = next(o for o in vocab if o.desc.startswith("our left flank"))
    assert left.ref == Ref(RefKind.POINT, "our left flank", (10.0, 20.0))
    enemies = [o for o in vocab if o.ref.kind == RefKind.ENEMY]
    assert [o.ref.name for o in enemies] == [
        "the enemy infantry near Hill",
        "the enemy cavalry near Hill",
    ]
    from kriegsspiel.staff import formation_label

    assert formation_label(sv.formations[0]) == "A brigade (infantry, General Smith)"


def test_staff_drops_a_subordinate_addressed_by_its_superiors_words():
    forms = [
        FormationView("army", "the army", "King", level="army"),
        FormationView("w", "the wing", "Wing", level="wing", parent="army"),
        FormationView("b", "the brigade", "Brig", parent="w"),
    ]
    staff = JevStaff(JevClient(mode="stub"))
    staff.client.ask = lambda state, qs: {k: Answer("noul", noul=1.0) for k in qs}
    addressed, _sources = staff._addressing({}, "Forward.", ["Forward."], forms)
    # the brigade (the wing's only child) is part of its wing's task; the wing, read into the
    # army's words, is asked whether it has an order of its own (yes here); ancestors first
    assert [f.id for f in addressed] == ["army", "w"]
    # with a second brigade not addressed, the wing is dropped and the brigade keeps the order
    forms.append(FormationView("b2", "the other brigade", "Other", parent="w"))
    staff.client.ask = lambda state, qs: {
        k: Answer("noul", noul=0.0 if k.startswith("a3") else 1.0) for k in qs
    }
    addressed, _ = staff._addressing({}, "Forward.", ["Forward."], forms)
    assert [f.id for f in addressed] == ["army", "b"]


def test_enemy_names_are_stable_between_views():
    w, f, u = load_testfield()
    s = Sim(w, f, u, seed=5)
    orders(s)
    s.run(30)
    a = {e.key: e.name for e in s.side_view("blue").enemies}
    s.run(30)
    b = {e.key: e.name for e in s.side_view("blue").enemies}
    assert a and all(b[k] == v for k, v in a.items())


def test_sequel_starts_when_the_first_task_is_complete():
    a = body("a", "blue", "line", 500.0, 500.0, UnitState.COLUMN)
    s = make_sim([a])
    second = Task(TaskKind.ADVANCE, "a", Ref(RefKind.POINT, point=(500.0, 1500.0)))
    first = Task(TaskKind.ADVANCE, "a", Ref(RefKind.POINT, point=(1500.0, 500.0)), then=second)
    rt = task_from_json(task_to_json(first))
    assert rt.then is not None and rt.then.objective.point == (500.0, 1500.0)
    s.submit_tasks("blue", [first])
    s.run(90)
    kinds = [e.kind for e in s.events]
    assert "task_ended" in kinds
    assert dist((a.x, a.y), (500.0, 1500.0)) < 100.0


def test_sequel_hold_after_until():
    a = body("a", "blue", "line", 500.0, 500.0, UnitState.COLUMN)
    s = make_sim([a])
    from kriegsspiel.types import Condition, ConditionKind

    first = Task(
        TaskKind.ADVANCE,
        "a",
        Ref(RefKind.POINT, point=(3500.0, 500.0)),
        until=Condition(ConditionKind.TIME, at=10),
        then=Task(TaskKind.HOLD, ""),
    )
    s.submit_tasks("blue", [first])
    s.run(12)
    x = a.x
    s.run(20)
    assert a.task is not None and a.task.kind == TaskKind.HOLD and a.task.formation == "a"
    assert abs(a.x - x) < 1.0 and x < 3000.0
