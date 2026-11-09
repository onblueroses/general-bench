"""Data pack acceptance for the designed battle Plain (data/plain-crossroads/).

The design is docs/battles/README.md ("Plain's armies", "The brief", "The verdict"): flat open
ground with one crossroads village, two identical armies deployed symmetrically under the 180°
rotation about the crossroads, an ordinal mission, and first briefs that carry the mission, the
verdict, the clock, the own order of battle with its qualities and the enemy's in outline, the
same for both sides with the names swapped."""

from __future__ import annotations

import json
import re
from collections import Counter
from pathlib import Path

import numpy as np
import pytest

from kriegsspiel import verdict
from kriegsspiel.build import build
from kriegsspiel.combat import MUSKET_RANGE_M
from kriegsspiel.narrator import Narrator
from kriegsspiel.scenario import load, load_script
from kriegsspiel.staff_text import Lexicon, same_word, staff_view, variant
from kriegsspiel.types import Cover, FeatureKind

ROOT = Path(__file__).resolve().parents[2]
PACK = ROOT / "data" / "plain-crossroads"
W, H = 8000.0, 6000.0
CX, CY = W / 2, H / 2
KEYS = ["G", "L1", "L2", "L3", "L4", "N1", "N2", "CU", "DR", "HU", "AR"]
QUALITY = {
    "G": 5,
    "L1": 3,
    "L2": 3,
    "L3": 3,
    "L4": 3,
    "N1": 2,
    "N2": 2,
    "CU": 4,
    "DR": 3,
    "HU": 3,
    "AR": 3,
}
KIND = {"G": "grenadier", "CU": "cuirassier", "DR": "dragoon", "HU": "hussar", "AR": "foot_battery"}
SIDES = ("red", "blue")
P = {"red": "R", "blue": "B"}


def rot(x: float, y: float) -> tuple[float, float]:
    return (W - x, H - y)


@pytest.fixture(scope="module")
def pack():
    return load(PACK)


@pytest.fixture(scope="module")
def oob():
    return json.loads((PACK / "oob.json").read_text())


@pytest.fixture(scope="module")
def dep():
    return json.loads((PACK / "deployment.json").read_text())


def test_pack_loads(pack):
    world, formations, units, objectives, meta = pack
    t = world.terrain
    assert (t.width_m, t.height_m) == (W + 25.0, H + 25.0)  # one cell more: an odd grid
    assert t.origin == (-12.5, -12.5)
    assert meta.start == "09:00" and meta.end == "16:00"
    assert meta.sunset_minute is not None and meta.sunset_minute > 19 * 60
    assert "date" not in meta.raw and meta.raw["season"]
    assert set(objectives.sides) == set(SIDES) == set(objectives.players)
    assert "narrative only" not in objectives.for_side("red")
    assert "narrates and does not rule" in objectives.umpire
    # no side is privileged: neither is "attacker", so Meta.attacker falls
    # back to the first side in oob.json (red), as design-notes.md records
    assert all(v["role"] != "attacker" for v in meta.sides.values())
    assert list(json.loads((PACK / "oob.json").read_text())["sides"]) == list(SIDES)
    assert {f.side for f in formations} == set(SIDES) and len(units) == 44


def test_armies_identical_and_as_designed(pack, oob):
    _, formations, units, _, _ = pack
    for side in SIDES:
        fs = [f for f in formations if f.side == side]
        roots = [f for f in fs if f.parent is None]
        assert len(roots) == 1 and roots[0].hq is not None and roots[0].level == "army"
        brigades = [f for f in fs if f.parent is not None]
        assert len(brigades) == 11 and {f.id for f in brigades} == {f"{P[side]}-{k}" for k in KEYS}
        us = [u for u in units if u.side == side]
        assert sum(u.men for u in us) == 12_440  # 9,800 foot, 2,400 horse, 240 gunners
        for k in KEYS:
            mine = [u for u in us if u.parent == f"{P[side]}-{k}"]
            assert len(mine) == 2, k
            assert {u.quality for u in mine} == {QUALITY[k]}, k
            assert {u.kind.value for u in mine} == {KIND.get(k, "line")}, k
            for u in mine:
                if k == "AR":
                    assert (u.guns, u.calibre_lb) == (8, 12)
                elif k in ("CU", "DR", "HU"):
                    assert u.men == 400
                else:
                    assert (u.men, u.bn_guns) == (700, 2)
        assert sum(u.guns + u.bn_guns for u in us) == 44

    # same names, kinds and numbers on both sides; commanders all different
    def strip(s):
        return re.sub(r"^(Red|Blue) ", "", s)

    by = {
        s: sorted(
            (strip(u["name"]), u["kind"], u["men"], u["quality"], u.get("guns", 0))
            for u in oob["units"]
            if u["side"] == s
        )
        for s in SIDES
    }
    assert by["red"] == by["blue"]
    surnames = [f["commander"].split()[-1] for f in oob["formations"]]
    assert len(set(surnames)) == 24


def test_deployment_symmetric_under_rotation(pack, dep):
    _, formations, units, _, _ = pack
    for u in units:
        if u.side != "red":
            continue
        b = dep["units"][u.id.replace("R-", "B-", 1)]
        r = dep["units"][u.id]
        assert rot(r["x"], r["y"]) == pytest.approx((b["x"], b["y"]), abs=0.05), u.id
        assert (r["facing_deg"] + 180) % 360 == b["facing_deg"]
        assert r["state"] == b["state"]
    assert rot(*dep["hq"]["R"]) == pytest.approx(tuple(dep["hq"]["B"]))
    # the first line 3.5 km from the village, the army behind it, nobody arriving later
    red = [d for k, d in dep["units"].items() if k.startswith("R-")]
    assert max(d["x"] for d in red) == pytest.approx(CX - 3500.0)
    assert min(d["x"] for d in red) > 50.0
    assert all("arrives_at" not in d for d in dep["units"].values())
    roots = {f.side: f for f in formations if f.parent is None}
    assert roots["red"].hq[0] < CX - 3500.0  # headquarters behind the centre


def test_ground_flat_open_and_symmetric(pack):
    t = pack[0].terrain
    assert float(t.elev_m.min()) == float(t.elev_m.max())
    assert set(np.unique(t.cover)) == {Cover.OPEN, Cover.VILLAGE, Cover.ROAD}
    assert np.array_equal(t.cover, t.cover[::-1, ::-1])  # the 180° rotation
    world = pack[0]
    assert world.cover(CX, CY) == Cover.ROAD
    assert world.cover(CX + 100, CY + 100) == Cover.VILLAGE
    for x, y in ((0.0, CY), (W, CY), (CX, 0.0), (CX, H), (CX - 2000, CY), (CX, CY + 1500)):
        assert world.cover(x, y) == Cover.ROAD, (x, y)
    assert world.cover(CX + 1000, CY + 1000) == Cover.OPEN


def test_features_symmetric_and_distinct(pack):
    world = pack[0]
    pts = {}
    for f in world.features:
        if f.kind in (FeatureKind.ROAD,):
            assert sorted(map(tuple, f.coords)) == sorted(rot(*p) for p in f.coords)
            continue
        pts[f.name] = (f.kind, tuple(f.coords[0]))
    village = world.feature("Teasel Village")
    assert village.kind == FeatureKind.VILLAGE and tuple(village.coords[0]) == (CX, CY)
    assert world.feature("the crossroads") is village
    for name, (kind, p) in pts.items():
        twin = [
            n for n, (k, q) in pts.items() if k == kind and q == pytest.approx(rot(*p), abs=0.05)
        ]
        assert twin, name
    farms = [f for f in world.features if f.kind == FeatureKind.FARM]
    exits = [f for f in world.features if f.kind == FeatureKind.EXIT]
    assert len(farms) == 4 and len(exits) == 4
    for f in farms:
        x, y = f.coords[0]
        assert np.hypot(x - CX, y - CY) == pytest.approx(2000.0, abs=0.2)
        assert abs(abs(x - CX) - abs(y - CY)) < 0.2  # on a diagonal
    for f in exits:
        x, y = f.coords[0]
        assert world.edge_distance(x, y) < 25 and world.cover(x, y) == Cover.ROAD
    # the staff's matching keeps every two names apart (one letter forgiven in long words)
    names = [(f.name, variant(n)) for f in world.features for n in [f.name, *f.aliases]]
    for a, va in names:
        for b, vb in names:
            if a < b and len(va) == len(vb):
                assert not all(same_word(x, y) for x, y in zip(va, vb, strict=True)), (a, b)


def test_mission_is_the_ordinal_verdict(pack):
    world, *_ = pack
    m = verdict.load(PACK)
    assert set(m) == {
        "verdict",
        "objective",
        "break_share",
        "break_persist_min",
        "play_on_min",
        "break_tie_margin",
        "note",
    }
    assert (m["verdict"], m["objective"]) == ("ordinal", "Teasel Village")
    assert (m["break_share"], m["break_persist_min"], m["play_on_min"]) == (0.4, 30, 120)
    assert m["break_tie_margin"] == 0.1  # about a brigade of foot
    assert verdict.validate(m, world.features) == []
    sim = build(PACK, 1, "stub")
    assert sim.ordinal is not None and sim.ordinal.last_minute == 9 * 60  # 18:00
    assert MUSKET_RANGE_M == 250.0  # the brief states it


def test_script_is_symmetric_and_read(pack):
    orders = json.loads((PACK / "script.json").read_text())["orders"]
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
            if "Teasel Village" in text:
                assert any(m.key == "Teasel Village" for m in lex.features_in(text)), text


# --------------------------------------------------------------------------- the briefs


def _swap(text: str) -> str:
    """Red's text in Blue's names: commanders, armies, the farms and exits (by the rotation)
    and the compass words of positions, all at once."""
    oob = json.loads((PACK / "oob.json").read_text())
    pairs = {
        "Red": "Blue",
        "Mallow": "Yarrow",
        "Burdock": "Vetch",
        "Mallowe": "Yarrowe",
        "Burdocke": "Vetche",
        "West": "East",
        "North": "South",
        "west": "east",
        "north": "south",
    }
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


CLOCK = (
    "The clock: the battle starts at 09:00; the end hour is 16:00; if the village is "
    "contested then, play goes on by quarter hours until 18:00 at most."
)
ENEMY = (
    "His army is the same as yours, formation for formation: the {enemy} army, some "
    "twelve thousand four hundred men and forty-four guns; a Grenadier brigade of two "
    "battalions, quality 5; the First to the Fourth brigades of the line, quality 3; the "
    "Fifth and Sixth brigades of new-raised regiments, quality 2;"
)


@pytest.fixture(scope="module")
def briefs():
    sim = build(PACK, 1, "stub")
    nar = sim.narrator
    return {s: nar.brief(sim.picture(s), s, since=0, update=False) for s in SIDES}


def test_first_briefs_carry_the_design_and_differ_only_in_names(pack, briefs):
    world, formations, units, objectives, meta = pack
    nar = Narrator(world, meta, objectives, formations, units)
    nar.ordinal = True  # as build sets it for an ordinal pack (GAME_ORDINAL)
    for side in SIDES:
        enemy = "Blue" if side == "red" else "Red"
        brief = " ".join(briefs[side].split())
        assert brief.startswith(" ".join(nar.persona(side).split()))
        assert CLOCK in brief
        assert ENEMY.format(enemy=enemy) in brief
        assert "Reserve artillery of two batteries of eight twelve-pounders, quality 3" in brief
        # the verdict, all four points, and the own qualities by formation
        for words in (
            (
                "more than 40% of its men are in routed or destroyed bodies and stay "
                "so for 30 minutes together"
            ),
            "within musket range, 250 m, of the crossroads",
            "never against formed foot or guns, for in this game",
            "Still contested at six: a draw",
            "(4) Nothing else counts.",
            "the Grenadier brigade under",
            "quality 5 on a scale of 1 to 5",
            "new-raised regiments, quality 2",
            "the Cuirassier brigade under",
        ):
            assert words in brief, (side, words)
        for f in formations:
            if f.side == side and f.parent is not None and f.id.split("-")[1] != "AR":
                assert f.commander.split()[-1] in objectives.for_player(side)
    # the two briefs, and the two players.md sections, differ only in names
    assert _swap(objectives.for_player("red")) == objectives.for_player("blue")

    # line for line: the narrator lists the compass rose and equidistant places in a fixed
    # order, so the rotated lines come in another order; every line is the same
    def lines(t):
        return sorted(t.splitlines())

    assert lines(_swap(briefs["red"])) == lines(briefs["blue"])
    # positive control: the swap is not the identity, and a real difference shows
    assert briefs["red"] != briefs["blue"]
    assert lines(_swap(briefs["red"].replace("quality 2", "quality 1"))) != lines(briefs["blue"])


def test_counts_per_side():
    oob = json.loads((PACK / "oob.json").read_text())
    assert Counter(f["side"] for f in oob["formations"]) == {"red": 12, "blue": 12}
    assert Counter(u["side"] for u in oob["units"]) == {"red": 22, "blue": 22}
