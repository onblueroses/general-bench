"""Courier delay equals distance over speed; the army commander's picture lags the
truth. Also staff, start conditions and reports."""

from __future__ import annotations

import pytest
from test_engine_kit import ScriptedStaff, body, flat_world, make_sim

from kriegsspiel.command import courier_minutes
from kriegsspiel.types import (
    Condition,
    ConditionKind,
    Cover,
    MessageKind,
    Ref,
    RefKind,
    Task,
    TaskKind,
    UnitState,
)


def test_courier_cross_country_is_distance_over_250():
    # the points are route nodes: the lattice is centred on the field, so on this 4 km field
    # its nodes stand at whole hundreds of metres
    w = flat_world()
    assert courier_minutes(w, (600.0, 600.0), (3100.0, 600.0)) == pytest.approx(10.0)
    assert courier_minutes(w, (600.0, 600.0), (2600.0, 2600.0)) == pytest.approx(
        2000.0 * 2**0.5 / 250.0
    )


def test_courier_on_the_road_is_distance_over_400():
    def cover(X, Y, c):
        c[(Y > 1000) & (Y < 1025)] = Cover.ROAD
        return c

    w = flat_world(cover=cover)
    assert courier_minutes(w, (512.5, 1012.5), (3512.5, 1012.5)) == pytest.approx(
        3000.0 / 400.0, rel=0.02
    )  # nodes snap to road cells: one cell of slop


def test_order_arrives_after_the_courier_ride():
    u = body("u", "blue", "line", 3100.0, 600.0, UnitState.COLUMN)  # on route nodes, as above
    s = make_sim([u], hq={"blue": (600.0, 600.0)})
    s.submit_tasks("blue", [Task(TaskKind.ADVANCE, "u", Ref(RefKind.POINT, point=(3100, 2000)))])
    for _ in range(10):
        s.step()
        assert u.task is None
    s.step()  # minute 10: the aide arrives
    assert u.task is not None and u.task.received_at == 10.0
    m = next(m for m in s.command.messages if m.kind == MessageKind.ORDER)
    assert m.received_at - m.sent_at == pytest.approx(10.0)


def test_picture_lags_the_truth():
    # brigade at (1000, 1000) sees the enemy; the army hq is 3 km away and sees nothing
    u = body("u", "blue", "line", 1000.0, 1000.0, UnitState.LINE)
    e = body("e", "red", "line", 1000.0, 2500.0, UnitState.COLUMN, facing=180.0)
    s = make_sim([u, e], hq={"blue": (3900.0, 100.0), "red": (1000.0, 3900.0)})
    s.submit_tasks("red", [Task(TaskKind.ADVANCE, "e", Ref(RefKind.POINT, point=(1000, 1700)))])
    s.step()
    assert "e" in s.vision.known(u.parent)
    first = [m for m in s.command.messages if m.kind == MessageKind.REPORT and m.side == "blue"]
    assert first, "first contact must be reported at once"
    delay = first[0].data["arrives"] - first[0].sent_at
    assert delay == pytest.approx(courier_minutes(s.world, (3900.0, 100.0), (1000.0, 1000.0)))
    seen_at_y = first[0].data["sightings"][0]["y"]
    while s.now < delay:  # delivered in the first tick at or after arrival
        assert not s.picture("blue").contacts  # the hq does not know yet
        s.step()
    s.step()
    pic = s.picture("blue")
    assert [c.key for c in pic.contacts] == ["e"]
    assert pic.contacts[0].y == pytest.approx(seen_at_y)
    assert e.y < seen_at_y - 100.0  # the enemy has moved on since
    assert any(m.kind == MessageKind.REPORT for m in pic.reports)
    assert pic.contacts[0].name.startswith("the enemy")


def test_submit_order_goes_through_the_staff_and_side_view():
    u = body("u", "blue", "line", 1000.0, 1000.0, UnitState.COLUMN)
    staff = ScriptedStaff()
    seen = {}

    class Spy(ScriptedStaff):
        def translate(self, text, side_view):
            seen["view"] = side_view
            return staff.translate(text, side_view)

    staff.add("Forward!", [Task(TaskKind.ADVANCE, "u", Ref(RefKind.POINT, point=(1000, 2000)))])
    s = make_sim([u], staff=Spy())
    s.submit_order("blue", "Forward!", at=3)
    for _ in range(5):
        s.step()
    assert u.task is not None and u.task.source_text == "Forward!"
    assert seen["view"].side == "blue"
    assert u.parent in {f.id for f in seen["view"].formations}


def test_start_condition_waits():
    u = body("u", "blue", "line", 1000.0, 1000.0, UnitState.COLUMN)
    s = make_sim([u])
    s.submit_tasks(
        "blue",
        [
            Task(
                TaskKind.ADVANCE,
                "u",
                Ref(RefKind.POINT, point=(1000, 2000)),
                start=Condition(ConditionKind.TIME, at=5),
            )
        ],
    )
    for _ in range(5):
        s.step()
    assert u.task is None and u.y == 1000.0
    s.step()
    assert u.task is not None


def test_periodic_reports_every_30_minutes():
    u = body("u", "blue", "line", 1000.0, 1000.0, UnitState.LINE)
    s = make_sim([u], hq={"blue": (1000.0, 500.0)})
    s.run(61)
    reps = [m for m in s.command.messages if m.kind == MessageKind.REPORT]
    assert [m.sent_at for m in reps] == [30.0, 60.0]


def test_the_picture_carries_each_brigades_starting_strength():
    """A general (or the bot) reads losses as a share: `Picture.own` gives the reported men and
    the reported bodies' men at the start, not only the men."""
    u = body("u", "blue", "line", 1000.0, 1000.0, UnitState.LINE, men=600)
    s = make_sim([u], hq={"blue": (1000.0, 500.0)})
    s.run(20)
    u.men, u.casualties = 450, 150
    s.run(20)
    rep = s.picture("blue").own[u.parent]
    assert rep["men"] == 450 and rep["strength_start"] == 600
