"""Scenario acceptance: Kolín loads, strengths match the documentation, start
positions are passable, feature names are unique, the ridge stands above the road. The
synthetic test field loads through the same loader."""

from __future__ import annotations

import numpy as np
import pytest
from test_engine_kit import KOLIN, TESTFIELD

from kriegsspiel.scenario import Objectives, load, parse_objectives
from kriegsspiel.types import Arm, Cover, FeatureKind, UnitState
from kriegsspiel.world import World


@pytest.fixture(scope="module")
def kolin():
    return load(KOLIN)


def _arm_key(u) -> str:
    return {Arm.INFANTRY: "inf", Arm.CAVALRY: "cav", Arm.ARTILLERY: "art"}[u.arm]


def test_kolin_loads(kolin):
    world, formations, units, _objectives, meta = kolin
    assert isinstance(world, World)
    assert world.terrain.cell_m == 25.0
    ny, nx = world.terrain.elev_m.shape
    assert world.terrain.cover.shape == (ny, nx)
    assert world.terrain.elev_m.dtype == np.float32 and world.terrain.cover.dtype == np.uint8
    # about 14 km x 8 km, Planian to Kolín
    assert 12_000 <= world.terrain.width_m <= 16_000
    assert 7_000 <= world.terrain.height_m <= 9_000
    assert meta.date == "1757-06-18" and meta.start == "13:00" and meta.start_minute == 780
    assert meta.sunset_minute is not None and 19 * 60 < meta.sunset_minute < 21 * 60
    assert {f.side for f in formations} == {"prussia", "austria"}
    assert len(units) > 100


def test_bodies_sum_to_documented_strengths(kolin):
    """Prussia at its documented strength; Austria at 0.77 of it, the pack's balance tuning
    (41,949, a little under CDB90's 44,000; meta.json `tuning`)."""
    _, _, units, _, meta = kolin
    scale = {"prussia": 1.0, "austria": 0.81 * 0.95}
    for side, documented in meta.strength_documented.items():
        total = sum(u.men for u in units if u.side == side)
        want = scale[side] * documented
        assert abs(total - want) <= 0.05 * want, (side, total, want)
    # and the documented strengths are the sourced ones (docs/kolin-test-pack.md): Prussia at the
    # CDB90 figure, Austria at Nafziger's 53,790 plus heavy-gun crews
    assert abs(meta.strength_documented["prussia"] - 32_000) <= 0.05 * 32_000
    assert abs(meta.strength_documented["austria"] - 53_790) <= 0.05 * 53_790


def test_every_unit_is_well_formed(kolin):
    _, formations, units, _, _ = kolin
    fids = {f.id for f in formations}
    assert len(fids) == len(formations)
    assert len({u.id for u in units}) == len(units)
    for u in units:
        assert u.parent in fids
        assert 1 <= u.quality <= 5
        assert u.men > 0
        if u.arm == Arm.ARTILLERY:
            assert u.guns > 0 and u.crew > 0 and u.calibre_lb > 0
        assert u.morale == pytest.approx(60 + 8 * u.quality)
    roots = [f for f in formations if f.parent is None]
    assert sorted(f.side for f in roots) == ["austria", "prussia"]
    assert all(f.hq is not None for f in roots)
    assert {f.commander for f in roots} == {"Frederick II", "Daun"}


def test_historical_commanders_present(kolin):
    _, formations, _, _, _ = kolin
    cmd = " ".join(f.commander for f in formations)
    for name in [
        "Hülsen",
        "Tresckow",
        "Manstein",
        "Bevern",
        "Zieten",
        "Krosigk",
        "Normann",
        "Moritz",
        "Penavaire",
        "Daun",
        "Wied",
        "Sincère",
        "Andlau",
        "Starhemberg",
        "Serbelloni",
        "Nádasdy",
        "Beck",
        "Nostitz",
        "O'Donell",
        "Colloredo",
        "Puebla",
        "Feuerstein",
    ]:
        assert name in cmd, name


def test_start_positions_are_passable(kolin):
    world, _, units, _, _ = kolin
    for u in units:
        assert world.in_bounds(u.x, u.y), u.id
        assert world.passable(u.x, u.y, _arm_key(u)), (u.id, u.x, u.y, world.cover(u.x, u.y))
        assert world.cover(u.x, u.y) != Cover.WATER


def test_start_states(kolin):
    _, _, units, _, _ = kolin
    pr = [u for u in units if u.side == "prussia" and u.arm == Arm.INFANTRY]
    au = [u for u in units if u.side == "austria" and u.arm == Arm.INFANTRY]
    assert all(u.state == UnitState.COLUMN for u in pr)  # on the march at 13:00
    assert all(u.state in (UnitState.LINE, UnitState.SKIRMISH) for u in au)
    assert all(u.fatigue > 0 for u in pr) and all(u.fatigue == 0 for u in au)


def test_feature_names_unique(kolin):
    world, _, _, _, _ = kolin
    seen: set[str] = set()
    for f in world.features:
        for n in f.names:
            assert n.casefold() not in seen, n
            seen.add(n.casefold())
    for name in [
        "Křečhoř",
        "Chotzemitz",
        "Bříství",
        "Kutlirz",
        "Radowesnitz",
        "Planian",
        "Nová Ves",
        "Kolín",
        "Oak wood",
        "Eichbusch",
        "Kaiserstrasse",
        "the road",
        "Křečhoř heights",
        "Křečhoř crest",
        "Friedrichsberg",
        "Peklo brook",
    ]:
        assert world.has_feature(name), name


def test_ridge_higher_than_road(kolin):
    world, _, units, _, _ = kolin
    crest = world.feature("Křečhoř crest")
    road = world.feature("Kaiserstrasse")
    assert crest.kind == FeatureKind.RIDGE and road.kind == FeatureKind.ROAD
    xs = [p[0] for p in crest.coords]
    crest_e = [world.elev(x, y) for x, y in crest.coords]
    pts = np.linspace(0, 1, 400)
    road_e = []
    for t in pts:  # sample the road over the crest's west-east span
        k = int(t * (len(road.coords) - 1))
        (x0, y0), (x1, y1) = road.coords[k], road.coords[min(k + 1, len(road.coords) - 1)]
        x, y = (x0 + x1) / 2, (y0 + y1) / 2
        if min(xs) <= x <= max(xs):
            road_e.append(world.elev(x, y))
    assert road_e
    assert min(crest_e) > np.mean(road_e) + 20
    assert world.elev(*world.feature("Křečhoř hill").coords[0]) > max(road_e) + 40
    # and the Austrians, on the heights, start higher than the Prussians on the road
    pe = np.mean([world.elev(u.x, u.y) for u in units if u.side == "prussia"])
    ae = np.mean([world.elev(u.x, u.y) for u in units if u.side == "austria"])
    assert ae > pe + 20


def test_villages_and_wood_are_rasterised(kolin):
    world, _, _, _, _ = kolin
    for v in ["Křečhoř", "Chocenice", "Bříství", "Kolín"]:
        f = world.feature(v)
        xs, ys = [p[0] for p in f.coords], [p[1] for p in f.coords]
        cells = [
            world.cover(x, y)
            for x in np.arange(min(xs), max(xs), 25.0)
            for y in np.arange(min(ys), max(ys), 25.0)
            if world.inside(x, y, f)
        ]
        assert cells and sum(c == Cover.VILLAGE for c in cells) / len(cells) > 0.6, v
    oak = world.feature("Oak wood")
    cx = sum(p[0] for p in oak.coords) / len(oak.coords)
    cy = sum(p[1] for p in oak.coords) / len(oak.coords)
    assert world.cover(cx, cy) == Cover.WOOD
    x, y = world.feature("Kaiserstrasse").coords[10]
    assert world.cover(x, y) == Cover.ROAD


def test_objectives(kolin):
    _, _, _, objectives, _ = kolin
    assert isinstance(objectives, Objectives)
    assert "Krzeczhorz" in objectives.for_side("prussia")
    assert "road to Kolín" in objectives.for_side("prussia")
    assert "Hold the" in objectives.for_side("austria")
    assert "13,770" in objectives.outcome
    assert "13,770" not in objectives.for_side("prussia") + objectives.for_side("austria")


def test_parse_objectives_minimal():
    o = parse_objectives("# T\n\n## Blue: X\nattack\n\n## Outcome\nblue won\n", ["blue", "red"])
    assert o.sides == {"blue": "attack"} and o.outcome == "blue won"


@pytest.mark.skipif(not (TESTFIELD / "oob.json").exists(), reason="test field not generated")
def test_testfield_loads():
    world, formations, units, objectives, meta = load(TESTFIELD)
    assert world.terrain.cell_m == 50.0
    assert len({f.side for f in formations}) == 2
    assert units and all(world.passable(u.x, u.y, _arm_key(u)) for u in units)
    assert objectives.sides == {} and meta.start == "13:00"
