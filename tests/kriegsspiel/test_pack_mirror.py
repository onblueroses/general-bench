"""Data pack acceptance for the designed battle Mirror (data/mirror-fords/).

The design is docs/battles/README.md ("Mirror's ground" and "Mirror's brook, re-laid"): Plain's
box, armies, deployment, clock, verdict and brief, on ground that matters, laid out with exact
180° rotational symmetry about the village: two brooks rising on a dry saddle at the village
and running to the north-west and south-east corners, no bridge, one ford on each 2 km from the
village passable by all arms but slow, a low ridge on each side's left 1.5 km from the village
within 12-pounder roundshot of it and of the near ford, a wood on each side's right covering
its approach to its right-hand ford, lanes from each start to each ford, a bank road from each
army's left-hand ford to the village."""

from __future__ import annotations

import itertools
import json
import math
import re
from collections import Counter
from pathlib import Path

import numpy as np
import pytest

from kriegsspiel import combat, verdict
from kriegsspiel.build import build
from kriegsspiel.combat import MUSKET_RANGE_M
from kriegsspiel.narrator import Narrator, takes_rules_sheet
from kriegsspiel.scenario import load, load_script
from kriegsspiel.staff_text import Lexicon, same_word, staff_view, variant
from kriegsspiel.types import Cover, FeatureKind, GeometryKind

ROOT = Path(__file__).resolve().parents[2]
PACK = ROOT / "data" / "mirror-fords"
PLAIN = ROOT / "data" / "plain-crossroads"
W, H = 8000.0, 6000.0
CX, CY = W / 2, H / 2
SIDES = ("red", "blue")
# the brooks' frame: t along Curlew Brook (to the north-west corner), s across it (north-east,
# Blue's side); Red's ground is s < 0
DIR, NRM = (-0.8, 0.6), (0.6, 0.8)
FORD_T = 2000.0
CURLEW, GODWIT = (2400.0, 4200.0), (5600.0, 1800.0)


def rot(x: float, y: float) -> tuple[float, float]:
    return (W - x, H - y)


def at(t: float, s: float) -> tuple[float, float]:
    return (CX + t * DIR[0] + s * NRM[0], CY + t * DIR[1] + s * NRM[1])


def _ts(p) -> tuple[float, float]:
    dx, dy = p[0] - CX, p[1] - CY
    return (dx * DIR[0] + dy * DIR[1], dx * NRM[0] + dy * NRM[1])


def _off(p, ds: float) -> tuple[float, float]:
    """`p` moved `ds` metres across the brooks (towards Blue's side)."""
    return (p[0] + ds * NRM[0], p[1] + ds * NRM[1])


def _grid_shape(shape) -> tuple[np.ndarray, np.ndarray]:
    ny, nx = shape
    return np.meshgrid(-12.5 + (np.arange(nx) + 0.5) * 25.0, -12.5 + (np.arange(ny) + 0.5) * 25.0)


def _grid(t) -> tuple[np.ndarray, np.ndarray]:
    return _grid_shape(t.cover.shape)


def _seg_dist(x, y, a, b):
    vx, vy = b[0] - a[0], b[1] - a[1]
    u = np.clip(((x - a[0]) * vx + (y - a[1]) * vy) / (vx * vx + vy * vy), 0.0, 1.0)
    return np.hypot(x - a[0] - u * vx, y - a[1] - u * vy)


def _passes(a, pts, p, tol: float) -> bool:
    """Whether the route from `a` through `pts` passes within `tol` metres of `p`."""
    legs = [tuple(a), *map(tuple, pts)]
    return any(
        float(_seg_dist(np.array(p[0]), np.array(p[1]), q, r)) <= tol
        for q, r in itertools.pairwise(legs)
        if q != r
    )


@pytest.fixture(scope="module")
def pack():
    return load(PACK)


def _json(name: str, pack: Path = PACK):
    return json.loads((pack / name).read_text())


def test_pack_loads_with_plains_clock_and_verdict(pack):
    world, formations, units, objectives, meta = pack
    t = world.terrain
    assert (t.width_m, t.height_m) == (W + 25.0, H + 25.0) and t.origin == (-12.5, -12.5)
    assert meta.start == "09:00" and meta.end == "16:00"
    assert takes_rules_sheet(meta)
    assert set(objectives.sides) == set(SIDES) == set(objectives.players)
    assert "narrates and does not rule" in objectives.umpire
    assert all(v["role"] != "attacker" for v in meta.sides.values())
    assert {f.side for f in formations} == set(SIDES) and len(units) == 44
    # everything but the ground and the names is Plain's
    pm, mm = _json("meta.json", PLAIN), _json("meta.json")
    drop = ("battle", "sides", "doc")
    assert {k: v for k, v in pm.items() if k not in drop} == {
        k: v for k, v in mm.items() if k not in drop
    }
    pm, mm = _json("mission.json", PLAIN), _json("mission.json")
    assert {**pm, "objective": None} == {**mm, "objective": None}
    assert mm["objective"] == "Plover Village"


def test_armies_and_deployment_are_plains(pack):
    assert _json("deployment.json") == _json("deployment.json", PLAIN)

    def strip(oob):
        keep = (
            "id",
            "side",
            "parent",
            "kind",
            "men",
            "quality",
            "guns",
            "crew",
            "calibre_lb",
            "battalion_guns",
            "level",
            "name",
        )
        return (
            [{k: v for k, v in f.items() if k in keep} for f in oob["formations"]],
            [{k: v for k, v in u.items() if k in keep} for u in oob["units"]],
        )

    assert strip(_json("oob.json")) == strip(_json("oob.json", PLAIN))
    oob = _json("oob.json")
    surnames = [f["commander"].split()[-1] for f in oob["formations"]]
    plain = {f["commander"].split()[-1] for f in _json("oob.json", PLAIN)["formations"]}
    assert len(set(surnames)) == 24 and not plain & set(surnames)  # new names


def test_raster_exactly_symmetric(pack):
    t = pack[0].terrain
    assert np.array_equal(t.cover, t.cover[::-1, ::-1])
    assert np.array_equal(t.elev_m, t.elev_m[::-1, ::-1])
    assert set(np.unique(t.cover)) == {
        Cover.OPEN,
        Cover.WOOD,
        Cover.VILLAGE,
        Cover.WATER,
        Cover.ROAD,
    }


def test_brooks_saddle_and_fords(pack):
    w = pack[0]
    t = w.terrain
    gx, gy = _grid(t)
    water = t.cover == Cover.WATER
    r = np.hypot(gx - CX, gy - CY)
    # the saddle: no water within 500 m of the village, so the village and the possession
    # disc are dry ground; and no bridge anywhere
    assert water.any() and r[water].min() > 500.0
    assert not any(f.kind == FeatureKind.BRIDGE for f in w.features)
    # water on the diagonal from each head to its corner, both corners sealed
    for tt in np.arange(525.0, 5001.0, 25.0):
        assert w.cover(*at(tt, 0.0)) == Cover.WATER, tt
        assert w.cover(*rot(*at(tt, 0.0))) == Cover.WATER, tt
    assert w.cover(0.0, H) == Cover.WATER and w.cover(W, 0.0) == Cover.WATER
    assert w.cover(*at(450.0, 0.0)) != Cover.WATER  # the head
    # the High road crosses no water
    assert all(w.cover(x, CY) == Cover.ROAD for x in np.arange(0.0, W + 1, 25.0))
    # every water cell is impassable to every arm but within the ford's 40 m
    fords = (CURLEW, GODWIT)
    for i, j in zip(*np.nonzero(water), strict=True):
        x, y = float(gx[i, j]), float(gy[i, j])
        near = min(math.dist((x, y), p) for p in fords) <= 40.0
        for arm in ("inf", "cav", "art", "train"):
            assert w.passable(x, y, arm) == near, (x, y, arm)
    assert w.ford_factor(*CURLEW, "inf") == w.ford_factor(*CURLEW, "cav") == 0.5
    assert w.ford_factor(*GODWIT, "art") == w.ford_factor(*GODWIT, "train") == 0.25
    for name, p in (("Curlew Ford", CURLEW), ("Godwit Ford", GODWIT)):
        f = w.feature(name)
        assert f.kind == FeatureKind.FORD and tuple(f.coords[0]) == p
        assert math.dist(p, (CX, CY)) == pytest.approx(2000.0)  # the ladder: two kilometres
        assert set(f.props["passable"]) == {"infantry", "cavalry", "artillery", "train"}
        mill = w.feature(name.replace("Ford", "Mill"))
        assert math.dist(mill.coords[0], p) < 100.0
        brook = w.feature(name.replace("Ford", "Brook"))
        assert brook.kind == FeatureKind.STREAM and p in [tuple(q) for q in brook.coords]
    # every arm gets from start to start, and from one bank of a ford to the other over it
    for prof in ("inf_column", "cav_walk", "art_foot", "train"):
        m, pts = w.path_cost((1000.0, CY), (7000.0, CY), prof)
        assert math.isfinite(m) and pts, prof
    for prof in ("inf_column", "cav_walk", "art_foot"):
        a, b = at(FORD_T - 300.0, -300.0), at(FORD_T + 300.0, 300.0)
        m, pts = w.path_cost(a, b, prof)
        assert math.isfinite(m), prof
        assert _passes(a, pts, CURLEW, 60.0), (prof, pts)


def test_the_fords_and_the_saddle_are_the_only_ways_over(tmp_path):
    """With water across the saddle, the field falls into the two armies' halves, joined
    only at the fords; without the fords as well, no arm gets from one start to the other
    (positive control: the brooks really are a wall to the router, not only to the raster)."""
    import shutil

    from kriegsspiel.scenario import load as load_pack

    def variant(name: str, fords: bool) -> Path:
        dst = tmp_path / name
        shutil.copytree(PACK, dst, ignore=shutil.ignore_patterns("tools"))
        z = dict(np.load(dst / "terrain.npz"))
        gx, gy = _grid_shape(z["cover"].shape)
        s = (gx - CX) * NRM[0] + (gy - CY) * NRM[1]
        z["cover"] = np.where(np.abs(s) <= 25.0, np.uint8(Cover.WATER), z["cover"])
        np.savez(dst / "terrain.npz", **z)
        feats = json.loads((dst / "features.json").read_text())
        if not fords:
            feats = [f for f in feats if f["kind"] != "ford"]
        (dst / "features.json").write_text(json.dumps(feats))
        return dst

    walled = load_pack(variant("walled", True))[0]
    shut = load_pack(variant("shut", False))[0]
    for prof in ("inf_column", "cav_walk", "art_foot", "train"):
        m, pts = walled.path_cost((1000.0, CY), (7000.0, CY), prof)
        assert math.isfinite(m), prof
        assert any(_passes((1000.0, CY), pts, p, 60.0) for p in (CURLEW, GODWIT)), prof
        assert not math.isfinite(shut.path_cost((1000.0, CY), (7000.0, CY), prof)[0]), prof


def test_ridges_within_roundshot_and_high_enough(pack):
    w = pack[0]
    reach = combat.ROUNDSHOT_RANGE_M[12]
    heron, bittern = w.feature("Heron Ridge"), w.feature("Bittern Ridge")
    assert heron.kind == bittern.kind == FeatureKind.RIDGE
    crest = [tuple(p) for p in heron.coords]
    assert [rot(*p) for p in crest] == [tuple(p) for p in bittern.coords]
    mid = crest[1]
    assert mid[0] < CX and mid[1] > CY  # Red (west, facing east) has it on its left
    assert all(_ts(p)[1] < 0 for p in crest)  # on Red's side of Curlew Brook
    assert math.dist(mid, (CX, CY)) == pytest.approx(1500.0, abs=50.0)  # the ladder: 1.5 km
    # its near end within a 12-pounder's roundshot of the village and of the near ford:
    # 1,040 m and 1,297 m
    near = min(crest, key=lambda p: math.dist(p, (CX, CY)))
    assert math.dist(near, (CX, CY)) < reach and math.dist(near, CURLEW) < reach
    # clear of the water: the rise (500 m either side of the crest) ends short of the brook
    t = w.terrain
    gx, gy = _grid(t)
    water = t.cover == Cover.WATER
    for p, q in itertools.pairwise(crest):
        assert _seg_dist(gx[water], gy[water], p, q).min() > 500.0
    # a real rise: 25 m at the crest, level 600 m off it, 8 m or more (the narrator's
    # "level" threshold) for 250 m either side
    assert w.elev(*mid) - w.elev(CX, CY) == pytest.approx(25.0, abs=0.1)
    assert w.elev(*_off(mid, -600.0)) == w.elev(CX, CY) == 200.0
    assert w.elev(*_off(mid, 250.0)) - 200.0 >= 8.0
    # the ridge hides what stands behind it from beyond the brook, and the crest sees there
    behind, far_bank = _off(mid, -400.0), _off(mid, 900.0)
    assert not w.line_of_sight(far_bank, behind)
    assert w.line_of_sight(mid, far_bank)


def test_woods_cover_the_way_to_the_right_hand_ford(pack):
    w = pack[0]
    siskin, linnet = w.feature("Siskin Wood"), w.feature("Linnet Wood")
    assert siskin.geometry_kind == GeometryKind.POLYGON
    assert [rot(*p) for p in siskin.coords] == [tuple(p) for p in linnet.coords]
    # Red's wood: beside Godwit Brook on Red's side, on its right
    assert all(_ts(p)[0] < 0 and _ts(p)[1] < 0 for p in siskin.coords)
    # the Godwit lane runs through it square to the brook, the wood either side
    lane = w.feature("Godwit lane")
    assert any(tuple(p) == GODWIT for p in lane.coords)
    on_lane = [at(-FORD_T, s) for s in np.arange(-1550.0, -349.0, 50.0)]
    assert all(w.cover(x, y) == Cover.ROAD for x, y in on_lane)
    for s in np.arange(-1450.0, -349.0, 200.0):
        assert w.cover(*at(-FORD_T - 75.0, s)) == Cover.WOOD
        assert w.cover(*at(-FORD_T + 75.0, s)) == Cover.WOOD
    # the last 300 m to the ford is open, under the enemy's ridge (within roundshot of it)
    for s in (-250.0, -150.0, -75.0):
        assert w.cover(*at(-FORD_T - 75.0, s)) == Cover.OPEN
        assert w.cover(*at(-FORD_T + 75.0, s)) == Cover.OPEN
    bittern = [tuple(p) for p in w.feature("Bittern Ridge").coords]
    assert min(math.dist(p, at(-FORD_T, -300.0)) for p in bittern) < combat.ROUNDSHOT_RANGE_M[12]
    # the wood stops about 300 m short of the water (cell centres 283 m apart at the least)
    t = w.terrain
    gx, gy = _grid(t)
    wood, water = t.cover == Cover.WOOD, t.cover == Cover.WATER
    wx, wy = gx[water], gy[water]
    assert (
        min(np.hypot(wx - x, wy - y).min() for x, y in zip(gx[wood], gy[wood], strict=True)) > 275.0
    )


def test_lanes_and_bank_roads(pack):
    w = pack[0]
    curlew, godwit = w.feature("Curlew lane"), w.feature("Godwit lane")
    assert [rot(*p) for p in curlew.coords] == [tuple(p) for p in godwit.coords]
    withy, osier = w.feature("Withy road"), w.feature("Osier road")
    assert [rot(*p) for p in withy.coords] == [tuple(p) for p in osier.coords]
    for lane, ford, farms in (
        (curlew, CURLEW, ("Wren Farm", "Starling Farm")),
        (godwit, GODWIT, ("Thrush Farm", "Finch Farm")),
    ):
        pts = [tuple(p) for p in lane.coords]
        assert {pts[0], pts[-1]} == {(1000.0, CY), (7000.0, CY)}  # from the High road
        assert ford in pts  # over the ford
        for farm in farms:  # bending at a farm on each side of it
            assert tuple(w.feature(farm).coords[0]) in pts
    # Withy road: from the Curlew Ford along the brook on Red's side to the village
    pts = [tuple(p) for p in withy.coords]
    assert pts[0] == CURLEW and pts[-1] == (CX, CY)
    assert all(_ts(p)[1] < 0 for p in pts[1:-1])
    for road in (curlew, godwit, withy, osier):  # road all the way, but for the ford's water
        for p, q in itertools.pairwise([tuple(c) for c in road.coords]):
            for t in np.linspace(0.0, 1.0, 60):
                x, y = p[0] + t * (q[0] - p[0]), p[1] + t * (q[1] - p[1])
                assert w.cover(x, y) in (Cover.ROAD, Cover.WATER), (road.name, x, y)
                if w.cover(x, y) == Cover.WATER:
                    assert min(math.dist((x, y), f) for f in (CURLEW, GODWIT)) <= 40.0


def test_features_symmetric_and_distinct(pack):
    world = pack[0]
    feats = {f.name: f for f in world.features}
    for f in world.features:  # each feature's image is a feature of its kind
        img = sorted(rot(*p) for p in f.coords)
        twins = [
            g
            for g in world.features
            if g.kind == f.kind and sorted(map(tuple, g.coords)) == pytest.approx(img, abs=0.05)
        ]
        assert twins, f.name
    counts = Counter(f.kind for f in world.features)
    assert counts == {
        FeatureKind.VILLAGE: 1,
        FeatureKind.STREAM: 2,
        FeatureKind.FORD: 2,
        FeatureKind.MILL: 2,
        FeatureKind.RIDGE: 2,
        FeatureKind.WOOD: 2,
        FeatureKind.FARM: 4,
        FeatureKind.ROAD: 5,
        FeatureKind.EXIT: 2,
    }
    assert tuple(feats["Plover Village"].coords[0]) == (CX, CY)
    assert world.feature("the crossroads") is feats["Plover Village"]
    for f in world.features:
        if f.kind == FeatureKind.EXIT:
            assert (
                world.edge_distance(*f.coords[0]) < 25 and world.cover(*f.coords[0]) == Cover.ROAD
            )
    names = [(f.name, variant(n)) for f in world.features for n in [f.name, *f.aliases]]
    for a, va in names:
        for b, vb in names:
            if a < b and len(va) == len(vb):
                assert not all(same_word(x, y) for x, y in zip(va, vb, strict=True)), (a, b)


def test_mission_is_the_ordinal_verdict(pack):
    world, *_ = pack
    m = verdict.load(PACK)
    assert verdict.validate(m, world.features) == []
    sim = build(PACK, 1, "stub")
    assert sim.ordinal is not None and sim.ordinal.last_minute == 9 * 60
    # the village and the whole possession disc are dry ground: the fight for it resolves by
    # combat, as on Plain, not across water
    t = world.terrain
    gx, gy = _grid(t)
    disc = np.hypot(gx - CX, gy - CY) <= MUSKET_RANGE_M
    assert not (t.cover[disc] == Cover.WATER).any()
    assert (t.cover[np.hypot(gx - CX, gy - CY) <= 150.0] != Cover.OPEN).all()
    assert MUSKET_RANGE_M < 500.0


def test_script_is_symmetric_and_read(pack):
    orders = _json("script.json")["orders"]
    loaded = load_script(PACK)
    assert [(s, t) for _, s, t in loaded] == [(o["side"], o["text"]) for o in orders]
    by = {s: [(m, t) for m, side, t in loaded if side == s] for s in SIDES}
    assert [m for m, _ in by["red"]] == [m for m, _ in by["blue"]]
    sim = build(PACK, 1, "stub")
    for side in SIDES:
        lex = Lexicon(staff_view(sim.command.side_view(side)))
        own = {f.id for f in sim.forces.formations.values() if f.side == side}
        for _, text in by[side]:
            addressed = lex.formations_in(text)
            assert addressed and addressed[0].i == 0 and addressed[0].key in own, text
            if "Plover Village" in text:
                assert any(m.key == "Plover Village" for m in lex.features_in(text)), text


# --------------------------------------------------------------------------- the briefs
ROTATION_PAIRS = {
    "Red": "Blue",
    "Heron": "Bittern",
    "Siskin": "Linnet",
    "Curlew": "Godwit",
    "Withy": "Osier",
    "Wren": "Thrush",
    "Finch": "Starling",
    "West": "East",
    "North": "South",
    "west": "east",
    "north": "south",
    "heron": "bittern",
    "siskin": "linnet",
    "curlew": "godwit",
    "withy": "osier",
    "wren": "thrush",
    "finch": "starling",
}


def _swap(text: str) -> str:
    """Red's text in Blue's names: commanders, armies, the places by the rotation (period
    spellings too) and the compass words, all at once."""
    oob = _json("oob.json")
    pairs = dict(ROTATION_PAIRS)
    for a, b in list(ROTATION_PAIRS.items()):
        if a[0].isupper() and a not in ("Red", "West", "North"):
            pairs[a + "e"] = b + "e"
    red = {f["id"]: f["commander"].split()[-1] for f in oob["formations"] if f["side"] == "red"}
    for fid, sur in red.items():
        pairs[sur] = next(
            f["commander"].split()[-1]
            for f in oob["formations"]
            if f["id"] == fid.replace("R", "B", 1)
        )
    pairs.update({v: k for k, v in list(pairs.items())})
    pat = re.compile(r"\b(" + "|".join(map(re.escape, pairs)) + r")\b")
    return pat.sub(lambda m: pairs[m.group(1)], text)


@pytest.fixture(scope="module")
def briefs():
    sim = build(PACK, 1, "stub")
    return {s: sim.narrator.brief(sim.picture(s), s, since=0, update=False) for s in SIDES}


def test_first_briefs_carry_the_design_and_differ_only_in_names(pack, briefs):
    world, formations, units, objectives, meta = pack
    nar = Narrator(world, meta, objectives, formations, units)
    nar.ordinal = True  # as build sets it for an ordinal pack (GAME_ORDINAL)
    for side in SIDES:
        enemy = "Blue" if side == "red" else "Red"
        brief = " ".join(briefs[side].split())
        assert brief.startswith(" ".join(nar.persona(side).split()))
        assert (
            "The clock: the battle starts at 09:00; the end hour is 16:00; if the village "
            "is contested then, play goes on by quarter hours until 18:00 at most."
        ) in brief
        assert (
            f"His army is the same as yours, formation for formation and quality for "
            f"quality: the {enemy} army, some twelve thousand four hundred men"
        ) in brief
        for words in (
            (
                "more than 40% of its men are in routed or destroyed bodies and stay "
                "so for 30 minutes together"
            ),
            "within musket range, 250 m, of the crossroads",
            "Still contested at six: a draw",
            "(4) Nothing else counts.",
            "quality 5 on a scale of 1 to 5",
            "new-raised regiments, quality 2",
            "Two brooks rise on a dry saddle",
            "Every arm crosses them only at a ford",
            "stands on the saddle",
            "the short way round his right",
            "the long way round his left",
            "rises twenty-five metres",
        ):
            assert words in brief, (side, words)
        layer = objectives.for_player(side)  # the battle layer (GAME's examples name bridges)
        for words in ("bridge", "Bridge", "Dunlin", "fit to fight tomorrow"):  # gone
            assert words not in layer, (side, words)
        for f in formations:
            if f.side == side and f.parent is not None and f.id.split("-")[1] != "AR":
                assert f.commander.split()[-1] in objectives.for_player(side)
    # each side's own ground: the near ford and the ridge on its left, the wood on its right
    assert "Curlew Ford and Curlew Mill on Curlew Brook, to your left" in (
        objectives.for_player("red")
    )
    assert "Godwit Ford and Godwit Mill on Godwit Brook, to your left" in (
        objectives.for_player("blue")
    )
    assert "On your left, a kilometre and a half from the village, Heron Ridge" in (
        objectives.for_player("red")
    )
    assert "On your right Linnet Wood hides the way to Curlew Ford" in (
        objectives.for_player("blue")
    )
    # the two players.md sections and the two briefs differ only in names
    assert _swap(objectives.for_player("red")) == objectives.for_player("blue")

    def lines(t):
        return sorted(t.splitlines())

    assert lines(_swap(briefs["red"])) == lines(briefs["blue"])
    # positive control: the swap is not the identity, and a real difference shows
    assert briefs["red"] != briefs["blue"]
    assert lines(_swap(briefs["red"].replace("Heron Ridge rises", "Heron Ridge stands"))) != (
        lines(briefs["blue"])
    )


def test_counts_per_side():
    oob = _json("oob.json")
    assert Counter(f["side"] for f in oob["formations"]) == {"red": 12, "blue": 12}
    assert Counter(u["side"] for u in oob["units"]) == {"red": 22, "blue": 22}


def test_build_is_deterministic_and_plain_unchanged(tmp_path):
    """The three designed builders, run into a copy, write the committed bytes (Plain and
    Arms are built from the shared module too, and Arms takes Plain's ground from Plain's
    builder, so a change there that moved any pack would show here)."""
    import importlib.util
    import shutil

    packs = (PACK, PLAIN, ROOT / "data" / "arms-medlar")
    for src in packs:  # all copied first: Arms' builder reads Plain's beside it
        shutil.copytree(src, tmp_path / src.name)
    for src in packs:
        dst = tmp_path / src.name
        for name in ("terrain.npz", "oob.json", "players.md"):  # control: the build writes
            (dst / name).write_bytes(b"")
        spec = importlib.util.spec_from_file_location(
            f"build_{src.name}", dst / "tools" / "build_pack.py"
        )
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        mod.main()
        for p in src.iterdir():
            if p.is_file():
                assert (dst / p.name).read_bytes() == p.read_bytes(), (src.name, p.name)
