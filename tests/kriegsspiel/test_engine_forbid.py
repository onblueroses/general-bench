"""The staff's prohibitions honoured by the engine: ADVANCE_BEYOND as a movement
boundary, PURSUE and ENGAGE where the drill and combat decide contact. Each with its control."""

from __future__ import annotations

from test_engine_kit import body, flat_world, make_sim

from kriegsspiel import combat
from kriegsspiel.morale import rout
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

ROAD = Feature(
    "High road", FeatureKind.ROAD, GeometryKind.POLYLINE, [(0.0, 2000.0), (4000.0, 2000.0)]
)
VILLAGE = Feature(
    "Steinbach",
    FeatureKind.VILLAGE,
    GeometryKind.POLYGON,
    [(1900.0, 1900.0), (2100.0, 1900.0), (2100.0, 2100.0), (1900.0, 2100.0)],
)
HQ = {"blue": (2000.0, 600.0), "red": (200.0, 3900.0)}


def far():
    return body("r-far", "red", "line", 200.0, 3800.0, UnitState.LINE)


def march(forbid, goal=(2000.0, 2600.0), start=(2000.0, 1500.0)):
    u = body("u", "blue", "line", *start, UnitState.COLUMN, facing=0.0)
    sim = make_sim([u, far()], world=flat_world(features=[ROAD, VILLAGE]), hq=HQ)
    sim.submit_tasks(
        "blue",
        [Task(TaskKind.ADVANCE, "blue-b-u", Ref(RefKind.POINT, point=goal), forbid=list(forbid))],
    )
    sim.run(40)
    return u


def test_a_line_feature_is_a_boundary_the_body_does_not_cross():
    u = march(["ADVANCE_BEYOND:High road"])
    assert 1950.0 < u.y < 2000.0  # halted at the road
    assert march([]).y > 2550.0  # control: without the prohibition it goes on to its goal


def test_a_place_bounds_the_advance_at_its_far_edge():
    u = march(["ADVANCE_BEYOND:Steinbach"], goal=(2400.0, 2800.0))
    assert u.y > 1950.0 and u.y <= 2100.0 + 1.0  # no farther than the village's far edge
    free = march([], goal=(2400.0, 2800.0))
    assert free.y > 2700.0


def test_an_unknown_boundary_feature_bounds_nothing():
    assert march(["ADVANCE_BEYOND:Nowhere"]).y > 2550.0


def test_a_body_beyond_its_boundary_may_come_back():
    from kriegsspiel.drill import boundaries

    u = body("u", "blue", "line", 2000.0, 1500.0, UnitState.COLUMN)
    sim = make_sim([u, far()], world=flat_world(features=[ROAD, VILLAGE]), hq=HQ)
    u.task = Task(TaskKind.ADVANCE, "blue-b-u", forbid=["ADVANCE_BEYOND:Steinbach"])
    sim.rt["u"].origin = (2000.0, 1500.0)
    (ok,) = boundaries(sim, u, sim.rt["u"])
    assert ok(2000.0, 2000.0, 2000.0, 2090.0) and not ok(2000.0, 2090.0, 2000.0, 2110.0)
    assert ok(2000.0, 2200.0, 2000.0, 2150.0)  # beyond (pushed there): it may come back
    assert not ok(2000.0, 2200.0, 2000.0, 2250.0)


def _cav_against_fugitives(forbid):
    a = body("a", "blue", "hussar", 2000.0, 2000.0, UnitState.LINE, facing=0.0)
    d = body("d", "red", "line", 2000.0, 2050.0, UnitState.LINE, facing=180.0)
    sim = make_sim([a, d], hq=HQ)
    a.task = Task(TaskKind.CHARGE, "blue-b-a", Ref(RefKind.ENEMY, "d"), forbid=list(forbid))
    rout(sim, d, "test", "defeat")
    combat._contact(sim, a, d, "gallop", None, sim.event_rng("test", a, d))
    return sim


def test_no_pursuit_under_a_pursue_ban():
    sim = _cav_against_fugitives(["PURSUE"])
    assert not any(e.kind == "pursuit" for e in sim.tick_events)
    sim = _cav_against_fugitives([])  # control
    assert any(e.kind == "pursuit" for e in sim.tick_events)


def _approach(forbid, arm="line", start_y=1000.0, on_contact=OnContact.ENGAGE):
    st = UnitState.COLUMN if arm == "line" else UnitState.LINE
    u = body("u", "blue", arm, 2000.0, start_y, st, facing=0.0)
    e = body("e", "red", "line", 2000.0, 2000.0, UnitState.LINE, facing=180.0)
    sim = make_sim([u, e], hq={"blue": (2000.0, start_y - 200.0), "red": (2000.0, 3500.0)})
    sim.submit_tasks(
        "blue",
        [
            Task(
                TaskKind.ADVANCE,
                "blue-b-u",
                Ref(RefKind.POINT, point=(2000.0, 2500.0)),
                on_contact=on_contact,
                forbid=list(forbid),
            )
        ],
    )
    sim.submit_tasks("red", [Task(TaskKind.HOLD, "red-b-e")])
    sim.run(40)
    return sim, u, e


def test_infantry_under_an_engage_ban_halts_where_it_finds_the_enemy():
    sim, u, e = _approach(["ENGAGE"])
    gap = e.y - u.y
    assert 390.0 <= gap <= 420.0 and u.state == UnitState.LINE  # deployed at 400 m, no closer
    assert not any(ev.kind == "fire" and ev.data["firer"] == "u" for ev in sim.events)
    sim, u, e = _approach([])  # control: it closes to its firing halt and fires
    assert e.y - u.y < 200.0
    assert any(ev.kind == "fire" and ev.data["firer"] == "u" for ev in sim.events)


def test_cavalry_under_an_engage_ban_does_not_charge():
    sim, u, e = _approach(["ENGAGE"], arm="hussar", start_y=1300.0)
    assert not any(ev.kind in ("melee", "charge_aborted") for ev in sim.events)
    assert e.y - u.y > 300.0
    sim, u, e = _approach([], arm="hussar", start_y=1300.0)  # control: it charges
    assert any(ev.kind in ("melee", "charge_aborted") for ev in sim.events)
