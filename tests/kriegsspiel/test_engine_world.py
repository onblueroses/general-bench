"""Line of sight on a ridge; world queries; vision ranges and identification."""

from __future__ import annotations

import pytest
from test_engine_kit import body, flat_world, load_testfield, make_sim

from kriegsspiel.types import Cover, FeatureKind, UnitState
from kriegsspiel.vision import IDENT_EXACT_M, ident_level


def test_line_of_sight_on_a_ridge():
    w, _, _ = load_testfield()
    crest = (2000.0, 2150.0)
    assert w.elev(*crest) > w.elev(2000.0, 1000.0) + 30.0
    assert w.line_of_sight((2000.0, 500.0), crest)  # up the forward slope
    assert w.line_of_sight(crest, (2000.0, 500.0))
    assert not w.line_of_sight((2000.0, 1200.0), (2000.0, 2900.0))  # dead ground beyond
    assert w.line_of_sight((2000.0, 2200.0), (2000.0, 2900.0))  # from the crest you see it


def test_woods_block_beyond_50m():
    def wood(X, Y, c):
        c[(X > 1000) & (X < 1500)] = Cover.WOOD
        return c

    w = flat_world(cover=wood)
    assert w.line_of_sight((500.0, 1000.0), (1030.0, 1000.0))  # 30 m into the wood
    assert not w.line_of_sight((500.0, 1000.0), (1200.0, 1000.0))  # 200 m in
    assert not w.line_of_sight((500.0, 1000.0), (2000.0, 1000.0))  # through it


def test_features_queries():
    w, _, _ = load_testfield()
    assert w.inside(2400.0, 1000.0, "Neudorf")
    assert not w.inside(1000.0, 1000.0, "Neudorf")
    assert w.nearest_feature(2390.0, 1020.0, FeatureKind.VILLAGE).name == "Neudorf"
    assert w.feature("the oak wood").name == "Eichwald"
    assert w.cover(1000.0, 2350.0) == Cover.WOOD
    assert w.slope(2000.0, 1900.0) > w.slope(500.0, 300.0)
    names = [f.name.casefold() for f in w.features]
    assert len(names) == len(set(names))


def test_testfield_starts_on_passable_ground():
    w, f, u = load_testfield()
    assert len([x for x in f if x.parent is not None and x.side == "blue"]) == 4
    assert len([x for x in f if x.parent is not None and x.side == "red"]) == 4
    for x in u:
        assert w.passable(x.x, x.y), x.id


def test_vision_ranges_and_identification():
    assert ident_level(400.0) == 2 and ident_level(1000.0) == 1 and ident_level(2000.0) == 0
    a = body("a", "blue", "line", 1000.0, 500.0, UnitState.LINE)
    near = body("n", "red", "line", 1000.0, 500.0 + IDENT_EXACT_M - 10, UnitState.LINE)
    mid = body("m", "red", "line", 1500.0, 1400.0, UnitState.LINE, men=640)
    far = body("f", "red", "line", 1000.0, 2900.0, UnitState.LINE)
    s = make_sim([a, near, mid, far])
    s.step()
    known = s.vision.known(a.parent)
    assert known["n"].ident == 2 and known["n"].est_men == near.men
    assert known["m"].ident == 1 and known["m"].est_men == 600 and known["m"].arm == "infantry"
    assert "f" in known and known["f"].ident == 0 and known["f"].arm is None  # 2.4 km
    s2 = make_sim([a, body("g", "red", "line", 1000.0, 3100.0, UnitState.LINE)])
    s2.step()
    assert "g" not in s2.vision.known(a.parent)  # beyond 2,500 m


def test_vision_into_a_village_is_400m():
    def village(X, Y, c):
        c[(Y > 1450) & (Y < 1550) & (X > 900) & (X < 1100)] = Cover.VILLAGE
        return c

    w = flat_world(cover=village)
    a = body("a", "blue", "line", 1000.0, 1000.0, UnitState.LINE)
    hidden = body("h", "red", "line", 1000.0, 1460.0, UnitState.LINE)  # 460 m, in the village
    s = make_sim([a, hidden], world=w)
    s.step()
    assert "h" not in s.vision.known(a.parent)
    hidden.y = 1380.0  # in the open, 380 m
    s.step()
    assert "h" in s.vision.known(a.parent)


@pytest.mark.parametrize("profile", ["inf_column", "cav_walk", "courier_road"])
def test_path_cost_is_deterministic(profile):
    w, _, _ = load_testfield()
    a = w.path_cost((200.0, 500.0), (3700.0, 2500.0), profile)
    w2, _, _ = load_testfield()
    assert w2.path_cost((200.0, 500.0), (3700.0, 2500.0), profile) == a
