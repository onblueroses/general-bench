"""An ADVANCE ordered off the map by an exit fights through what blocks its way and goes round
what it will not fight. Without that, such an advance met a screen and stopped there for good:
infantry fired at a body that was not even on its road, formed square at hovering horse and
stood, and cavalry screened a square it would not charge."""

from __future__ import annotations

import pytest
from test_engine_kit import body, flat_world, make_sim

from kriegsspiel.types import (
    Feature,
    FeatureKind,
    GeometryKind,
    OnContact,
    Ref,
    RefKind,
    Task,
    TaskKind,
    UnitState,
)

EAST = Feature(
    "East exit", FeatureKind.EXIT, GeometryKind.POLYLINE, [(3990.0, 1500.0), (3990.0, 2500.0)]
)
EXIT = Ref(RefKind.FEATURE, "East exit")
BEHIND = Ref(RefKind.POINT, point=(3800.0, 2000.0))  # the same road, ending short of the exit


def run(
    arm: str,
    blocker: str,
    men: int,
    y: float = 2000.0,
    obj: Ref = EXIT,
    on_contact: OnContact = OnContact.ENGAGE,
    minutes: int = 150,
):
    a = body("a", "blue", arm, 1500.0, 2000.0, UnitState.COLUMN, facing=90.0)
    s = body("s", "red", blocker, 2600.0, y, UnitState.LINE, facing=270.0, men=men, quality=2)
    sim = make_sim(
        [a, s],
        world=flat_world(features=[EAST]),
        hq={"blue": (1000.0, 2000.0), "red": (3500.0, 3500.0)},
    )
    sim.submit_tasks(
        "blue",
        [Task(TaskKind.ADVANCE, "blue-b-a", obj, on_contact=on_contact)],
        text="March off by the east exit.",
    )
    sim.submit_tasks("red", [Task(TaskKind.HOLD, "red-b-s", None)], text="Hold.")
    squared = set()  # the bodies that stood in square at some minute
    for _ in range(minutes):
        sim.step()
        squared |= {u.id for u in (a, s) if u.state == UnitState.SQUARE}
    return sim, a, s, squared


def exited(sim, uid: str = "a") -> bool:
    return (sim.offmap.get(uid) or {}).get("fate") == "exited"


def test_infantry_fights_through_a_line_across_its_road():
    sim, a, s, _ = run("line", "line", 600)
    assert exited(sim)
    assert s.men < 600  # it was fought, not passed
    # the control: an advance to a point on the same road still stops in a firefight (an
    # ordinary ADVANCE engages without the bayonet; only the exit-bound advance presses)
    sim, a, s, _ = run("line", "line", 600, obj=BEHIND)
    assert not exited(sim) and a.x < 2600.0 and sim.rt["a"].phase == "firing"


def test_infantry_passes_a_body_off_its_road_without_a_fight():
    sim, _a, s, _ = run("line", "line", 600, y=2300.0)
    assert exited(sim) and s.men == 600 and sim.offmap["a"]["men"] == 600


def test_infantry_marches_on_in_square_past_hovering_horse():
    sim, a, _s, squared = run("line", "hussar", 150)
    assert "a" in squared and exited(sim)
    sim, a, _s, squared = run("line", "hussar", 150, obj=BEHIND)
    assert "a" in squared and not exited(sim) and a.x < 2400.0  # control: stands in square


def test_cavalry_rides_round_a_square_it_will_not_charge():
    sim, a, _s, squared = run("hussar", "line", 600)
    assert "s" in squared and exited(sim)
    sim, a, _s, _ = run("hussar", "line", 600, obj=BEHIND)
    assert not exited(sim) and a.x < 2400.0  # control: screens the square


@pytest.mark.parametrize("arm", ["line", "hussar"])
def test_an_exit_advance_told_to_halt_on_contact_still_halts(arm):
    sim, a, _s, _ = run(arm, "line", 600, on_contact=OnContact.HALT)
    assert not exited(sim) and a.x < 2600.0
