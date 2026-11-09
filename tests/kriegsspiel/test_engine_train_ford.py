"""Trains (UnitKind.TRAIN) and fords (FeatureKind.FORD) on small synthetic
fields, each rule with its control."""

from __future__ import annotations

import itertools
import math

import numpy as np
import pytest
from test_engine_kit import body, flat_world, make_sim

from kriegsspiel import geometry as geo
from kriegsspiel.account import field_of, render
from kriegsspiel.morale import rout
from kriegsspiel.types import (
    Arm,
    Cover,
    Feature,
    FeatureKind,
    GeometryKind,
    Ref,
    RefKind,
    Task,
    TaskKind,
    Unit,
    UnitKind,
    UnitState,
)
from kriegsspiel.world import World


def train(uid: str, side: str, x: float, y: float, men: int = 120, guns: int = 0) -> Unit:
    return Unit(
        id=uid,
        name=f"Train {uid}",
        side=side,
        parent=f"{side}-b-{uid}",
        arm=Arm.TRAIN,
        kind=UnitKind.TRAIN,
        men=men,
        quality=1,
        x=x,
        y=y,
        facing_deg=90.0,
        state=UnitState.COLUMN,
        guns=guns,
    )


def road_world(**kw) -> World:
    """Open ground, a 50 m road along y = 2000 and a wood south of y = 600."""

    def cover(X, Y, c):
        c[(Y > 1975) & (Y < 2025)] = Cover.ROAD
        c[Y < 600] = Cover.WOOD
        return c

    return flat_world(cover=cover, **kw)


def far(side: str = "red") -> Unit:
    return body(f"{side}-far", side, "line", 3800.0, 3800.0, UnitState.LINE)


def advance(sim, fid: str, point, side: str = "blue") -> None:
    sim.submit_tasks(side, [Task(TaskKind.ADVANCE, fid, Ref(RefKind.POINT, point=point))])


# ---------------------------------------------------------------------------- trains


def test_a_train_moves_50_on_the_road_25_on_open_ground_and_not_into_a_wood():
    w = road_world()
    assert w.passable(1000, 1000, "train") and w.passable(1000, 2000, "train")
    assert not w.passable(1000, 300, "train") and w.passable(1000, 300, "inf")
    on_road, off_road = train("t1", "blue", 500.0, 2000.0), train("t2", "blue", 500.0, 1000.0)
    sim = make_sim([on_road, off_road, far()], world=w, hq={"blue": (500.0, 1500.0)})
    advance(sim, "blue-b-t1", (3500.0, 2000.0))
    advance(sim, "blue-b-t2", (3500.0, 1000.0))
    sim.run(2)  # the aides need a minute or so; measure from the first minute of march
    x1, x2 = on_road.x, off_road.x
    sim.run(10)
    assert 10 * 50 * 0.9 <= on_road.x - x1 <= 10 * 50 * 1.01
    assert 10 * 25 * 0.9 <= off_road.x - x2 <= 10 * 25 * 1.01
    assert on_road.state == off_road.state == UnitState.COLUMN


def test_a_train_never_fires():
    t = train("t", "blue", 1000.0, 1000.0)
    e = body("e", "red", "line", 1000.0, 1150.0, UnitState.LINE, facing=180.0)
    sim = make_sim([t, e, body("f", "blue", "line", 900.0, 1000.0, UnitState.LINE)])
    sim.run(3)
    assert not any(ev.kind == "fire" and ev.data["firer"] == "t" for ev in sim.events)
    assert any(ev.kind == "fire" and ev.data["firer"] == "e" for ev in sim.events)


def test_cavalry_takes_a_train_without_a_melee():
    t = train("t", "blue", 2000.0, 2000.0, guns=10)
    c = body("c", "red", "hussar", 2000.0, 2900.0, UnitState.LINE, facing=180.0)
    sim = make_sim(
        [t, c, far("blue")],
        world=road_world(),
        hq={"red": (2000.0, 3500.0), "blue": (500.0, 2000.0)},
    )
    sim.submit_tasks("red", [Task(TaskKind.CHARGE, "red-b-c", Ref(RefKind.ENEMY, "t"))])
    sim.run(15)
    rec = sim.offmap.get("t")
    assert rec is not None and rec["fate"] == "captured" and rec["by"] == "c"
    assert rec["men"] == 120 and rec["guns"] == 10
    assert t.men == 0 and t.casualties == 120 and t.state == UnitState.DESTROYED
    assert not any(ev.kind == "melee" for ev in sim.events)
    assert sim.losses()["blue"] == 120
    text = render(field_of(sim), sim.world.features, ["blue", "red"])
    assert "Train t (train, 0 of 120): captured by c at 13:" in text
    assert "1 captured (120 men)" in text


def test_infantry_marches_in_and_takes_a_train_instead_of_firing_at_it():
    t = train("t", "blue", 2000.0, 1500.0)
    i = body("i", "red", "line", 2000.0, 1800.0, UnitState.COLUMN, facing=180.0)
    sim = make_sim([t, i, far("blue")], hq={"red": (2000.0, 2500.0), "blue": (300.0, 300.0)})
    sim.submit_tasks("red", [Task(TaskKind.ATTACK, "red-b-i", Ref(RefKind.ENEMY, "t"))])
    sim.run(12)
    assert sim.offmap.get("t", {}).get("fate") == "captured"
    assert not any(ev.kind == "fire" and ev.data["firer"] == "i" for ev in sim.events)


def test_a_train_bolts_at_enemy_cavalry_unless_a_formed_friend_is_near():
    def run(escort: bool):
        t = train("t", "blue", 2000.0, 2000.0)
        c = body("c", "red", "hussar", 2000.0, 2250.0, UnitState.LINE, facing=180.0)
        us = [t, c]
        if escort:
            us.append(body("g", "blue", "line", 2150.0, 2000.0, UnitState.LINE, facing=0.0))
        sim = make_sim(
            us, world=road_world(), hq={"red": (2000.0, 3500.0), "blue": (500.0, 2000.0)}
        )
        sim.step()
        return sim, t

    sim, t = run(escort=False)
    bolts = [e for e in sim.events if e.kind == "rout" and e.data["unit"] == "t"]
    assert t.state == UnitState.ROUTED and bolts and bolts[0].data["severity"] == "bolt"
    sim, t = run(escort=True)
    assert t.state == UnitState.COLUMN and not any(e.kind == "rout" for e in sim.events)


def test_a_bolted_train_is_rallied_by_a_friend_and_keeps_its_march():
    t = train("t", "blue", 2000.0, 2000.0)
    g = body("g", "blue", "line", 2000.0, 1850.0, UnitState.LINE, facing=0.0)
    sim = make_sim([t, g, far()], world=road_world(), hq={"blue": (500.0, 2000.0)})
    advance(sim, "blue-b-t", (3500.0, 2000.0))
    sim.run(6)  # the aide's ride from headquarters
    task = t.task
    assert task is not None and task.kind == TaskKind.ADVANCE
    rout(sim, t, "test", "bolt")
    sim.run(4)
    assert t.state == UnitState.COLUMN and t.task is task  # rallied; the march stands
    assert any(e.kind == "rally" and e.data["unit"] == "t" for e in sim.events)
    x = t.x
    sim.run(5)
    assert t.x > x + 100.0


def test_a_train_is_laid_out_in_column_along_the_road_behind_its_objective():
    """A train's bodies got slots abreast across the road, two in wood and
    one off the map; wagons want places one behind the other along the road."""
    from kriegsspiel.command import TRAIN_SPACING_M

    def cover(X, Y, c):
        c[(Y > 1975) & (Y < 2025)] = Cover.ROAD
        c[(np.abs(Y - 2000.0) > 40.0) & (X > 2000.0)] = Cover.WOOD  # a forest road
        return c

    w = flat_world(cover=cover)
    wagons = [
        Unit(
            id=f"t{k}",
            name=f"Train {k}",
            side="blue",
            parent="blue-train",
            arm=Arm.TRAIN,
            kind=UnitKind.TRAIN,
            men=120,
            quality=1,
            x=1200.0 - 100.0 * k,
            y=2012.5,
            facing_deg=90.0,
            state=UnitState.COLUMN,
        )
        for k in range(7)
    ]
    sim = make_sim([*wagons, far()], world=w, hq={"blue": (1200.0, 2012.5)})
    goal = (3500.0, 2012.5)
    advance(sim, "blue-train", goal)
    sim.run(2)
    slots = [sim.rt[t.id].slot for t in wagons]
    assert all(w.passable(x, y, "train") for x, y in slots), slots
    assert all(abs(y - 2012.5) < 30.0 for _, y in slots), slots  # on the road
    assert geo.dist(slots[0], goal) < 1.0  # the head at the objective, the rest behind it
    xs = [x for x, _ in slots]
    assert xs == sorted(xs, reverse=True)
    assert all(a - b == pytest.approx(TRAIN_SPACING_M, abs=1.0) for a, b in itertools.pairwise(xs))
    sim.run(80)
    for t, s in zip(wagons, slots, strict=True):
        assert w.passable(t.x, t.y, "train") and geo.dist((t.x, t.y), s) < 40.0, t.id


# ---------------------------------------------------------------------------- fords

RIVER_X = 2000.0


def river_world(*features: Feature) -> World:
    """Open ground cut north-south by a 50 m river at x = 2000 (no road)."""

    def cover(X, Y, c):
        c[np_abs(X - RIVER_X) < 25.0] = Cover.WATER
        return c

    return flat_world(cover=cover, features=list(features))


def np_abs(a):
    import numpy as np

    return np.abs(a)


FORD = Feature("Mill ford", FeatureKind.FORD, GeometryKind.POINT, [(RIVER_X, 2000.0)])


def test_a_ford_passes_the_arms_it_names_at_its_speed():
    w = river_world(FORD)
    assert w.passable(RIVER_X, 2000.0, "inf") and w.passable(RIVER_X, 2000.0, "cav")
    assert w.passable(RIVER_X, 2000.0, "courier")  # aides cross where horse can
    assert not w.passable(RIVER_X, 2000.0, "art") and not w.passable(RIVER_X, 2000.0, "train")
    assert not w.passable(RIVER_X, 1000.0, "inf")  # the rest of the river is water
    assert w.ford_factor(RIVER_X, 2000.0, "inf") == 0.5
    assert math.isfinite(w.path_cost((1500.0, 1000.0), (2500.0, 1000.0), "inf_column")[0])
    assert math.isinf(w.path_cost((1500.0, 1000.0), (2500.0, 1000.0), "art_foot")[0])
    # the control: without the ford nobody crosses
    assert math.isinf(river_world().path_cost((1500.0, 1000.0), (2500.0, 1000.0), "inf_column")[0])
    guns = Feature(
        "Gun ford",
        FeatureKind.FORD,
        GeometryKind.POINT,
        [(RIVER_X, 2000.0)],
        props={"passable": ["infantry", "cavalry", "artillery", "train"], "speed": 0.25},
    )
    w2 = river_world(guns)
    assert w2.passable(RIVER_X, 2000.0, "art") and w2.ford_factor(RIVER_X, 2000.0, "train") == 0.25


def test_a_ford_speed_may_differ_by_arm():
    f = Feature(
        "Wheel ford",
        FeatureKind.FORD,
        GeometryKind.POINT,
        [(RIVER_X, 2000.0)],
        props={
            "passable": ["infantry", "cavalry", "train"],
            "speed": {"infantry": 0.8, "train": 0.4},
        },
    )
    w = river_world(f)
    assert w.ford_factor(RIVER_X, 2000.0, "inf") == 0.8
    assert w.ford_factor(RIVER_X, 2000.0, "train") == 0.4
    assert w.ford_factor(RIVER_X, 2000.0, "cav") == 0.5  # not named: the default
    assert w.ford_factor(RIVER_X, 2000.0, "courier") == 0.5
    assert w.ford_factor(RIVER_X, 2000.0, "art") == 0.0  # not passable at all


def test_foot_cross_by_the_ford_and_guns_are_stopped_by_it():
    w = river_world(FORD)
    i = body("i", "blue", "line", 1500.0, 2000.0, UnitState.COLUMN, facing=90.0)
    g = body("g", "blue", "foot_battery", 1500.0, 1700.0, UnitState.LIMBERED, guns=6, facing=90.0)
    sim = make_sim([i, g, far()], world=w, hq={"blue": (1400.0, 1850.0)})
    advance(sim, "blue-b-i", (2500.0, 2000.0))
    advance(sim, "blue-b-g", (2500.0, 1700.0))
    sim.run(30)
    assert geo.dist((i.x, i.y), (2500.0, 2000.0)) < 40.0  # over the river by the ford
    assert g.x < RIVER_X  # the guns could not cross


def test_a_ford_is_slower_than_a_bridge():
    bridge = Feature("Mill bridge", FeatureKind.BRIDGE, GeometryKind.POINT, [(RIVER_X, 2000.0)])
    a, b = (1900.0, 2000.0), (2100.0, 2000.0)
    t_ford, _ = river_world(FORD).path_cost(a, b, "inf_column")
    t_bridge, _ = river_world(bridge).path_cost(a, b, "inf_column")
    assert t_bridge < t_ford < 2.0 * t_bridge + 1e-9


def test_a_polyline_ford_and_a_wide_bridge():
    line = Feature(
        "Long ford", FeatureKind.FORD, GeometryKind.POLYLINE, [(RIVER_X, 2900.0), (RIVER_X, 3100.0)]
    )
    w = river_world(line)
    assert w.passable(RIVER_X, 3000.0, "inf") and w.passable(RIVER_X, 2910.0, "cav")
    assert not w.passable(RIVER_X, 2800.0, "inf")
    wide = Feature(
        "Wide bridge",
        FeatureKind.BRIDGE,
        GeometryKind.POINT,
        [(RIVER_X, 1000.0)],
        props={"radius_m": 80.0},
    )
    w = river_world(wide)
    assert w.passable(RIVER_X, 1070.0, "art") and not river_world(
        Feature("Narrow bridge", FeatureKind.BRIDGE, GeometryKind.POINT, [(RIVER_X, 1000.0)])
    ).passable(RIVER_X, 1070.0, "art")


def test_a_long_straight_leg_never_steps_over_a_river_away_from_its_bridge():
    """Twelve samples along a 3 km leg are 250 m apart and skipped a 50 m river, so the router
    went straight over it whenever any crossing existed."""
    bridge = Feature("North bridge", FeatureKind.BRIDGE, GeometryKind.POINT, [(RIVER_X, 3800.0)])
    w = river_world(bridge)
    a, b = (500.0, 300.0), (3500.0, 600.0)  # the straight line crosses the river at y ~ 450
    assert not w.segment_passable("inf_column", a, b)
    minutes, pts = w.path_cost(a, b, "inf_column")
    assert math.isfinite(minutes)
    legs = list(zip([a, *pts], pts, strict=False))
    # legs that cross or touch the river's middle line (the lattice is centred on the field,
    # so the bridge itself, on that line, is a waypoint and the river is reached by one leg
    # and left by the next)
    crossing = [(p, q) for p, q in legs if (p[0] - RIVER_X) * (q[0] - RIVER_X) <= 0]
    assert 1 <= len(crossing) <= 2  # the river is crossed once, by the bridge

    def at_river(p, q):  # where the leg meets the river's middle line
        if p[0] == q[0]:
            return p[1]
        return p[1] + (q[1] - p[1]) * (RIVER_X - p[0]) / (q[0] - p[0])

    assert all(abs(at_river(p, q) - 3800.0) < 150.0 for p, q in crossing)
    assert minutes > 2.0 * math.dist(a, b) / 60.0  # the detour, not 50 minutes straight over
    assert all(w.segment_passable("inf_column", p, q) for p, q in legs)
    # the control: a short leg on open ground is costed as before (twelve samples)
    m_short = float(w.segment_minutes("inf_column", *map(np.array, (100.0, 100.0, 160.0, 100.0))))
    assert abs(m_short - 1.0) < 1e-9


@pytest.mark.parametrize("falling", [False, True])
def test_a_train_follows_an_oblique_road_one_cell_wide_through_a_wood(falling):
    """An oblique 25 m road band, its cells joined at their corners, was no
    road to the 100 m graph (legs between its nodes sample the wood); the train stood still.
    The fine road graph steps along it, diagonals included, rising or falling (a falling
    band's diagonal legs pass its cells' corners, which floor into the wood)."""

    def row(j):
        return 99 - np.round(j * 0.4).astype(int) if falling else np.round(j * 0.4).astype(int)

    def cover(X, Y, c):
        c[:] = Cover.WOOD
        j = np.arange(c.shape[1])
        c[row(j), j] = Cover.ROAD  # 8-connected, one cell wide
        return c

    w = flat_world(cover=cover)
    a, b = ((512.5, (row(20) + 0.5) * 25.0), (3512.5, (row(140) + 0.5) * 25.0))
    assert w.passable(*a, "train") and w.passable(*b, "train")
    assert not w.passable(512.5, a[1] + 50.0, "train")
    m, pts = w.path_cost(a, b, "train")
    assert math.isfinite(m) and pts[-1] == b
    assert 3231.0 / 50.0 <= m < 3600.0 / 50.0  # along the band at 50 m/min
    assert all(w.passable(x, y, "train") for x, y in pts)
    t = train("t", "blue", *a)
    sim = make_sim([t, far()], world=w)
    advance(sim, "blue-b-t", b)
    sim.run(100)
    assert geo.dist((t.x, t.y), b) < 50.0


def test_a_train_road_route_is_finite_over_a_falling_diagonal_of_four_cells():
    """With true road widths, a road leg four cells long running north-west to
    south-east passes its cells' corners at sampled points, which floor into the wood beside
    it; the road route's minutes come from the graph, not from those samples."""

    def cover(X, Y, c):
        c[:] = Cover.WOOD
        c[80, :61] = Cover.ROAD
        for k in range(1, 5):
            c[80 - k, 60 + k] = Cover.ROAD
        c[76, 64:] = Cover.ROAD
        return c

    w = flat_world(cover=cover)
    a, b = (512.5, 2012.5), (3512.5, 1912.5)
    m, pts = w.path_cost(a, b, "train")
    assert math.isfinite(m) and pts[-1] == b
    assert 2900.0 / 50.0 < m < 3100.0 / 50.0
    t = train("t", "blue", *a)
    sim = make_sim([t, far()], world=w)
    advance(sim, "blue-b-t", b)
    sim.run(75)
    assert geo.dist((t.x, t.y), b) < 50.0
