"""Movement rates, formation change times, slope and cover effects."""

from __future__ import annotations

import itertools
import math

import pytest
from test_engine_kit import body, flat_world, load_testfield, make_sim

from kriegsspiel.geometry import angle_diff
from kriegsspiel.movement import BodyRT, follow_route, uphill_factor
from kriegsspiel.types import Cover, Ref, RefKind, Task, TaskKind, UnitState


def _march(kind, state, start, goal, world=None, minutes=5, task_state=None, **kw):
    u = body("u", "blue", kind, *start, state, facing=90.0, **kw)
    s = make_sim([u], world=world)
    s.submit_tasks(
        "blue",
        [Task(TaskKind.ADVANCE, u.id, Ref(RefKind.POINT, point=goal), state=task_state or state)],
    )
    s.step()  # order delivered (the army hq is the brigade's centroid here: no delay)
    x0, y0 = u.x, u.y
    for _ in range(minutes):
        s.step()
    return math.hypot(u.x - x0, u.y - y0) / minutes, u, s


def road_world():
    def cover(X, Y, c):
        c[(Y > 975) & (Y < 1025)] = Cover.ROAD
        return c

    return flat_world(cover=cover)


@pytest.mark.parametrize(
    ("state", "speed"),
    [(UnitState.LINE, 40.0), (UnitState.SQUARE, 20.0), (UnitState.SKIRMISH, 50.0)],
)
def test_formed_infantry_speeds(state, speed):
    w = flat_world()
    u = body("u", "blue", "line", 500.0, 1000.0, state, facing=90.0)  # facing its march
    rt = BodyRT(route=[(3500.0, 1000.0)])
    moved = follow_route(w, u, rt, 1.0, "walk")
    assert moved == pytest.approx(speed)


def test_cavalry_gaits():
    w = flat_world()
    for gait, speed in (("walk", 100.0), ("trot", 200.0), ("gallop", 350.0)):
        u = body("u", "blue", "cuirassier", 500.0, 1000.0, UnitState.LINE, facing=90.0)
        assert follow_route(w, u, BodyRT(route=[(3500.0, 1000.0)]), 1.0, gait) == (
            pytest.approx(speed)
        )


@pytest.mark.parametrize(
    ("kind", "state", "world", "speed"),
    [
        ("line", UnitState.COLUMN, None, 60.0),
        ("cuirassier", UnitState.COLUMN, None, 100.0),
        ("foot_battery", UnitState.LIMBERED, None, 40.0),
        ("horse_battery", UnitState.LIMBERED, None, 100.0),
    ],
)
def test_base_speeds_open_ground(kind, state, world, speed):
    v, _, _ = _march(kind, state, (500.0, 1000.0), (3500.0, 1000.0), guns=6)
    assert v == pytest.approx(speed, rel=0.02)


def test_column_on_road_is_75_and_battery_60():
    v, _, _ = _march(
        "line", UnitState.COLUMN, (500.0, 1000.0), (3500.0, 1000.0), world=road_world()
    )
    assert v == pytest.approx(75.0, rel=0.02)
    v, _, _ = _march(
        "foot_battery",
        UnitState.LIMBERED,
        (500.0, 1000.0),
        (3500.0, 1000.0),
        world=road_world(),
        guns=6,
    )
    assert v == pytest.approx(60.0, rel=0.02)


def test_cavalry_marches_faster_on_a_road_and_routes_by_it():
    """Cavalry road speed equalled its cross-country speed, so reserve cuirassiers marched
    880 m off the road. Assumption: walk and trot gain infantry's 75/60 on a road."""
    from kriegsspiel.movement import BASE_SPEED, CAV_ROAD_FACTOR

    assert pytest.approx(75.0 / 60.0) == CAV_ROAD_FACTOR
    assert BASE_SPEED["cav_walk"] == (125.0, 100.0) and BASE_SPEED["cav_trot"] == (250.0, 200.0)
    assert BASE_SPEED["cav_gallop"] == (350.0, 350.0)  # a charge is not a road march
    v, _, _ = _march(
        "cuirassier", UnitState.COLUMN, (500.0, 1000.0), (3500.0, 1000.0), world=road_world()
    )
    assert v == pytest.approx(125.0, rel=0.02)

    # a road 300 m aside of the straight line, joined at both ends: the column takes it
    def detour(X, Y, c):
        c[(Y > 1300) & (Y < 1325) & (X > 500) & (X < 3500)] = Cover.ROAD
        c[(X > 500) & (X < 525) & (Y > 1000) & (Y < 1325)] = Cover.ROAD
        c[(X > 3475) & (X < 3500) & (Y > 1000) & (Y < 1325)] = Cover.ROAD
        return c

    w = flat_world(cover=detour)
    m, pts = w.path_cost((512.5, 1012.5), (3487.5, 1012.5), "cav_walk")
    assert m < 3000.0 / 100.0 and max(p[1] for p in pts) > 1250.0


def test_cover_multipliers():
    def wood(X, Y, c):
        c[:] = Cover.WOOD
        return c

    v, _, _ = _march(
        "line", UnitState.COLUMN, (500.0, 1000.0), (3500.0, 1000.0), world=flat_world(cover=wood)
    )
    assert v == pytest.approx(30.0, rel=0.02)  # 60 x 0.5
    v, _, _ = _march(
        "hussar", UnitState.COLUMN, (500.0, 1000.0), (3500.0, 1000.0), world=flat_world(cover=wood)
    )
    assert v == pytest.approx(25.0, rel=0.02)  # 100 x 0.25

    def marsh(X, Y, c):
        c[:] = Cover.MARSH
        return c

    v, _, _ = _march(
        "line", UnitState.COLUMN, (500.0, 1000.0), (3500.0, 1000.0), world=flat_world(cover=marsh)
    )
    assert v == pytest.approx(18.0, rel=0.02)  # 60 x 0.3


def test_marsh_stops_wheels_off_the_road():
    """Marsh slowed every arm alike. Guns and trains cross it only by a road;
    foot and horse wade at 0.3."""

    def swamp(road: bool):
        def cover(X, Y, c):
            c[(X > 1900) & (X < 2100)] = Cover.MARSH
            if road:
                c[(Y > 975) & (Y < 1025) & (X > 1850) & (X < 2150)] = Cover.ROAD
            return c

        return flat_world(cover=cover)

    a, b = (1000.0, 2000.0), (3000.0, 2000.0)
    plain, causeway = swamp(False), swamp(True)
    for profile in ("art_foot", "art_horse", "train"):
        assert not plain.passable(2000.0, 2000.0, profile.split("_")[0])
        assert math.isinf(plain.path_cost(a, b, profile)[0]), profile
        assert math.isfinite(causeway.path_cost(a, b, profile)[0]), profile
    for profile in ("inf_column", "cav_walk"):
        assert math.isfinite(plain.path_cost(a, b, profile)[0]), profile


def test_slope_uphill_and_downhill():
    assert uphill_factor(0.1) == pytest.approx(0.8)
    assert uphill_factor(0.5) == pytest.approx(0.4)
    assert uphill_factor(-0.2) == 1.0
    up = flat_world(elev=lambda X, Y: 200.0 + 0.1 * X)
    v, _, _ = _march("line", UnitState.COLUMN, (500.0, 1000.0), (3500.0, 1000.0), world=up)
    assert v == pytest.approx(48.0, rel=0.03)  # 60 x (1 - 2 x 0.1)
    v, _, _ = _march("line", UnitState.COLUMN, (3500.0, 1000.0), (500.0, 1000.0), world=up)
    assert v == pytest.approx(60.0, rel=0.02)


def test_fatigue_and_disorder_slow_a_body():
    _, _u, _ = _march("line", UnitState.COLUMN, (500.0, 1000.0), (3500.0, 1000.0), minutes=1)
    u2 = body("v", "blue", "line", 500.0, 1000.0, UnitState.COLUMN, facing=90.0)
    u2.fatigue, u2.disorder = 100.0, 100.0
    s = make_sim([u2])
    s.submit_tasks(
        "blue",
        [
            Task(
                TaskKind.ADVANCE,
                "v",
                Ref(RefKind.POINT, point=(3500, 1000)),
                state=UnitState.COLUMN,
            )
        ],
    )
    s.step()
    x0 = u2.x
    s.step()
    assert u2.x - x0 == pytest.approx(60.0 * 0.5 * 0.5, rel=0.05)


def test_water_is_impassable_except_at_the_bridge():
    w, _, _ = load_testfield()
    assert not w.passable(3420.0, 1600.0)  # the stream
    assert w.passable(3450.0, 1050.0)  # the bridge
    minutes, pts = w.path_cost((3000.0, 2500.0), (3800.0, 2500.0), "inf_column")
    assert math.isfinite(minutes)
    assert any(math.hypot(p[0] - 3450.0, p[1] - 1050.0) < 120.0 for p in pts)
    # every leg is passable on the fine raster
    legs = [(3000.0, 2500.0), *pts]
    for a, b in itertools.pairwise(legs):
        assert w.segment_passable("inf_column", a, b)


def test_route_prefers_the_road():
    w, _, _ = load_testfield()
    _, pts = w.path_cost((100.0, 900.0), (3300.0, 1050.0), "inf_column")
    on_road = sum(w.cover(*p) == Cover.ROAD for p in pts)
    assert on_road >= len(pts) - 2


def _change(kind, frm, to, guns=0):
    u = body("u", "blue", kind, 1000.0, 1000.0, frm, guns=guns)
    s = make_sim([u])
    s.submit_tasks("blue", [Task(TaskKind.HOLD, "u", state=to)])
    s.step()  # tick 0: order arrives, change starts and the first minute is spent
    n = 1
    while u.state != to and n < 20:
        s.step()
        n += 1
    return n


@pytest.mark.parametrize(
    ("kind", "frm", "to", "minutes", "guns"),
    [
        ("line", UnitState.COLUMN, UnitState.LINE, 3, 0),
        ("line", UnitState.LINE, UnitState.COLUMN, 2, 0),
        ("line", UnitState.LINE, UnitState.SQUARE, 2, 0),
        ("foot_battery", UnitState.LIMBERED, UnitState.UNLIMBERED, 3, 6),
        ("horse_battery", UnitState.LIMBERED, UnitState.UNLIMBERED, 2, 6),
    ],
)
def test_formation_change_times(kind, frm, to, minutes, guns):
    assert _change(kind, frm, to, guns) == minutes


def test_facing_change_costs_a_minute_per_90_degrees():
    u = body("u", "blue", "line", 1000.0, 1000.0, UnitState.LINE, facing=0.0)
    e = body("e", "red", "line", 1000.0, 700.0, UnitState.LINE, facing=0.0)  # to the south
    s = make_sim([u, e])
    s.submit_tasks("blue", [Task(TaskKind.HOLD, "u")])
    s.step()
    assert angle_diff(u.facing_deg, 0.0) == pytest.approx(90.0)  # half way after 1 minute
    s.step()
    assert u.facing_deg == pytest.approx(180.0)
