"""Arrivals at named entries and exits off the map edge (docs/pack-format.md), on
small synthetic fields."""

from __future__ import annotations

import json
import shutil

from test_engine_kit import TESTFIELD, body, flat_world, make_sim

from kriegsspiel import geometry as geo
from kriegsspiel.account import field_of, render
from kriegsspiel.scenario import load
from kriegsspiel.sim import ARRIVAL_STEP_M, ENTRY_CLEAR_M, Sim
from kriegsspiel.types import (
    Feature,
    FeatureKind,
    GeometryKind,
    MessageKind,
    Ref,
    RefKind,
    Task,
    TaskKind,
    UnitState,
)
from kriegsspiel.units import Forces

WEST = Feature("West gate", FeatureKind.ENTRY, GeometryKind.POINT, [(10.0, 2000.0)])
EAST = Feature(
    "East exit", FeatureKind.EXIT, GeometryKind.POLYLINE, [(3990.0, 1500.0), (3990.0, 2500.0)]
)
MILL = Feature("Mill", FeatureKind.MILL, GeometryKind.POINT, [(1500.0, 3000.0)])


def world(*extra: Feature):
    return flat_world(features=[WEST, MILL, *extra])


def arriving(uid: str, at: float, side: str = "blue", kind: str = "line", **kw):
    u = body(uid, side, kind, 0.0, 0.0, UnitState.COLUMN, brigade=kw.pop("brigade", None), **kw)
    u.arrives_at, u.entry = at, "West gate"
    return u


def far_enemy():
    return body("r1", "red", "line", 3500.0, 3800.0, UnitState.LINE)


def test_a_body_arrives_at_its_minute_and_assembles_inward():
    a = arriving("a", 5)
    sim = make_sim([a, far_enemy()], world=world(), hq={"blue": (500.0, 500.0)})
    assert a.state == UnitState.DESTROYED and sim.offmap["a"]["fate"] == "awaiting"
    assert (a.x, a.y) == (10.0, 2000.0)
    assert sim.forces.hq("blue-b-a") == (10.0, 2000.0)  # the formation is at its entry
    sim.run(5)
    assert a.state == UnitState.DESTROYED and "a" not in sim.vision.visible
    sim.step()
    arrived = [e for e in sim.events if e.kind == "arrived"]
    assert [(e.tick, e.data["unit"], e.data["entry"]) for e in arrived] == [(5, "a", "West gate")]
    assert a.state == UnitState.COLUMN and "a" not in sim.offmap
    sim.run(15)
    goal = (10.0 + ARRIVAL_STEP_M, 2000.0)
    assert geo.dist((a.x, a.y), goal) < 35.0  # held at its assembly point, off the entry


def test_bodies_enter_one_at_a_time_when_the_entry_is_clear():
    units = [arriving(f"c{k}", 0, brigade="blue-col") for k in range(3)]
    sim = make_sim([*units, far_enemy()], world=world(), hq={"blue": (500.0, 500.0)})
    sim.run(12)
    ticks = {e.data["unit"]: e.tick for e in sim.events if e.kind == "arrived"}
    assert list(ticks) == ["c0", "c1", "c2"]  # first come, first served, in deployment order
    assert ticks["c0"] == 0 and ticks["c1"] > ticks["c0"] and ticks["c2"] > ticks["c1"]
    # each entered only when its predecessor had cleared ENTRY_CLEAR_M (column 60 m/min)
    assert ticks["c1"] - ticks["c0"] >= ENTRY_CLEAR_M / 60.0


def test_an_order_reaching_an_unarrived_formation_is_carried_out_on_arrival():
    a = arriving("a", 20)
    sim = make_sim([a, far_enemy()], world=world(), hq={"blue": (500.0, 500.0)})
    sim.submit_tasks(
        "blue",
        [Task(TaskKind.ADVANCE, "blue-b-a", Ref(RefKind.FEATURE, "Mill"))],
        text="To the mill.",
    )
    sim.run(20)
    order = next(m for m in sim.command.messages if m.kind == MessageKind.ORDER)
    assert order.destination == (10.0, 2000.0)  # the aide rides to the entry
    assert order.received_at is not None and order.received_at < 20
    assert a.task is not None and a.task.kind == TaskKind.ADVANCE  # held for it off the map
    sim.run(60)
    assert geo.dist((a.x, a.y), (1500.0, 3000.0)) < 40.0  # went to the mill, not to assemble


def test_a_body_leaves_by_an_exit_its_task_names_and_keeps_its_men():
    a = body("a", "blue", "line", 3600.0, 2000.0, UnitState.COLUMN, facing=90.0)
    b = body("b", "blue", "line", 3600.0, 1200.0, UnitState.COLUMN, facing=90.0)
    sim = make_sim([a, b, far_enemy()], world=world(EAST), hq={"blue": (3000.0, 1600.0)})
    sim.submit_tasks(
        "blue",
        [
            Task(TaskKind.ADVANCE, "blue-b-a", Ref(RefKind.FEATURE, "East exit")),
            # the control: marches to the edge beside the exit, but its task does not name it
            Task(TaskKind.ADVANCE, "blue-b-b", Ref(RefKind.POINT, point=(3980.0, 1400.0))),
        ],
        text="Off by the east exit.",
    )
    sim.run(20)
    rec = sim.offmap.get("a")
    assert rec is not None and rec["fate"] == "exited" and rec["exit"] == "East exit"
    assert rec["men"] == 600 and a.casualties == 0 and a.state == UnitState.DESTROYED
    assert b.state != UnitState.DESTROYED and "b" not in sim.offmap and b.x > 3900.0
    assert any(e.kind == "exited" and e.data["unit"] == "a" for e in sim.events)
    assert "1 off the map (600 men)" in sim.summary()
    sim.run(5)
    assert any(
        "has left the field by East exit" in m.text
        for m in sim.command.messages
        if m.kind == MessageKind.REPORT
    )
    text = render(field_of(sim), sim.world.features, ["blue", "red"], deadline="13:05")
    assert "1 off the map (600 men)" in text
    assert "left the map by East exit at 13:" in text and "(after the deadline)" in text


def test_a_routed_body_at_the_edge_flees_off_the_map_only_in_a_pack_with_exits():
    def run(features):
        u = body("u", "blue", "line", 30.0, 2000.0, UnitState.ROUTED, facing=270.0)
        e = body("e", "red", "line", 300.0, 2000.0, UnitState.LINE, facing=270.0)
        u.morale = 10.0
        sim = make_sim(
            [u, e],
            world=flat_world(features=features),
            hq={"blue": (2000.0, 3500.0), "red": (2000.0, 500.0)},
        )
        sim.run(3)
        return sim, u

    sim, u = run([WEST, MILL, EAST])
    assert sim.offmap["u"]["fate"] == "fled" and u.state == UnitState.DESTROYED
    assert "fled off the map" in sim.summary()
    sim, u = run([WEST, MILL])  # no exits: the old edge behaviour (it stays, routed)
    assert u.state == UnitState.ROUTED and not sim.offmap


def test_the_snapshot_carries_offmap_only_when_used():
    plain = make_sim([body("a", "blue", "line", 1000, 1000, UnitState.LINE), far_enemy()])
    assert "offmap" not in plain.snapshot()
    sim = make_sim([arriving("a", 5), far_enemy()], world=world())
    assert sim.snapshot()["offmap"]["a"]["due_clock"] == "13:05"


def test_a_pack_with_arrivals_loads_them_from_the_deployment(tmp_path):
    d = tmp_path / "pack"
    shutil.copytree(TESTFIELD, d, ignore=shutil.ignore_patterns("make.py"))
    feats = json.loads((d / "features.json").read_text())
    feats.append(
        {
            "name": "West road entry",
            "kind": "entry",
            "geometry": {"type": "point", "coords": [[25.0, 900.0]]},
            "aliases": [],
        }
    )
    (d / "features.json").write_text(json.dumps(feats))
    dep = json.loads((d / "deployment.json").read_text())
    dep["units"]["B-inf1-1"].update(
        {"arrives_at": "13:30", "entry": "West road entry", "assemble": "Neudorf"}
    )
    (d / "deployment.json").write_text(json.dumps(dep))
    w, f, u, _, _ = load(d)
    a = next(x for x in u if x.id == "B-inf1-1")
    assert (a.arrives_at, a.entry, a.assemble, (a.x, a.y)) == (
        30.0,
        "West road entry",
        "Neudorf",
        (25.0, 900.0),
    )
    sim = Sim(w, f, u, seed=1)
    assert sim.offmap["B-inf1-1"]["fate"] == "awaiting"
    assert isinstance(sim.forces, Forces)
    sim.run(31)
    assert a.state == UnitState.COLUMN
    assert sim.rt["B-inf1-1"].slot == sim.world.anchor(sim.world.feature("Neudorf"), (25.0, 900.0))


def test_the_order_of_battle_says_when_and_where_a_formation_arrives():
    from test_engine_kit import forces_for

    from kriegsspiel.narrator import Narrator
    from kriegsspiel.scenario import Meta, Objectives

    units = [arriving("a", 5), body("b", "blue", "line", 900, 900, UnitState.LINE), far_enemy()]
    nar = Narrator(world(), Meta(), Objectives(), forces_for(units), units)
    oob = nar.order_of_battle("blue")
    assert (
        "- blue-b-a (blue-b-a cdr): infantry, 1 battalion, 600 men, arriving from 13:05 by "
        "West gate." in oob
    )
    assert "arriving" not in oob.split("blue-b-b")[1]


NARROW = Feature(
    "Narrow exit",
    FeatureKind.EXIT,
    GeometryKind.POLYLINE,
    [(3990.0, 1950.0), (3990.0, 2050.0)],
    props={"radius_m": 100.0},
)


def _wing(n: int = 6, x: float = 2600.0):
    """A brigade of n battalions in a line 1.5 km long, north to south, facing east."""
    return [
        body(
            f"w{k}",
            "blue",
            "line",
            x,
            1250.0 + 300.0 * k,
            UnitState.COLUMN,
            facing=90.0,
            brigade="blue-wing",
        )
        for k in range(n)
    ]


def test_a_wing_ordered_to_an_exit_heads_for_the_exit_itself_and_every_body_leaves():
    bodies = _wing()
    sim = make_sim([*bodies, far_enemy()], world=world(NARROW), hq={"blue": (2000.0, 2000.0)})
    sim.submit_tasks(
        "blue",
        [Task(TaskKind.WITHDRAW, "blue-wing", Ref(RefKind.FEATURE, "Narrow exit"))],
        text="Off the map.",
    )
    sim.run(4)
    for u in bodies:  # no line slots across the exit: each heads for the exit's nearest point
        assert sim.world.feature_distance(*sim.rt[u.id].slot, NARROW) < 1.0, u.id
    sim.run(60)
    assert all(sim.offmap.get(u.id, {}).get("fate") == "exited" for u in bodies), [
        (u.id, round(u.x), round(u.y)) for u in bodies if u.id not in sim.offmap
    ]


def test_brigade_strength_counts_only_bodies_on_the_map():
    """A report read "Strength 550 of 1,722" with half the brigade still to arrive. Bodies awaiting
    arrival or gone by an exit are neither strength nor loss; the report says where they are."""
    here = body("a", "blue", "line", 1000.0, 2000.0, UnitState.LINE, brigade="blue-bde")
    late = arriving("b", 200, brigade="blue-bde")
    gone = body(
        "c", "blue", "line", 3900.0, 2000.0, UnitState.COLUMN, facing=90.0, brigade="blue-bde"
    )
    sim = make_sim(
        [here, late, gone, far_enemy()], world=world(EAST), hq={"blue": (1000.0, 2000.0)}
    )
    sim.submit_tasks("blue", [Task(TaskKind.ADVANCE, "c", Ref(RefKind.FEATURE, "East exit"))])
    sim.run(40)
    assert sim.offmap["c"]["fate"] == "exited" and sim.offmap["b"]["fate"] == "awaiting"
    reps = [
        m
        for m in sim.command.messages
        if m.kind == MessageKind.REPORT and m.data.get("brigade") == "blue-bde"
    ]
    assert reps
    last = reps[-1]
    assert "Strength 600 of 600" in last.text, last.text
    assert "1 body yet to arrive" in last.text and "1 body off the map by an exit" in last.text
    assert not any("losses pass a quarter" in m.text for m in reps)


def test_a_screen_of_an_exit_keeps_bodies_on_the_map():
    bodies = _wing(2, x=3800.0)
    sim = make_sim([*bodies, far_enemy()], world=world(NARROW), hq={"blue": (2000.0, 2000.0)})
    sim.submit_tasks(
        "blue",
        [Task(TaskKind.SCREEN, "blue-wing", Ref(RefKind.FEATURE, "Narrow exit"))],
        text="Screen it.",
    )
    sim.run(30)
    assert not sim.offmap and all(u.state != UnitState.DESTROYED for u in bodies)
    assert min(sim.world.feature_distance(u.x, u.y, NARROW) for u in bodies) < 100.0
