"""Data pack acceptance for the designed battle Arms (data/arms-medlar/).

The design is docs/battles/README.md (item 3 and "Arms' armies"): Plain's ground, clock,
verdict and mission words, with two armies of equal strength by the period's own rate and
different makeup, a horse army and a foot army, quality following Plain's pattern within each
arm. The sides are `horse` and `foot`. The first briefs carry the same mission, verdict, clock
and rules sheet, and each its own army in full and the enemy's in outline, so they differ in
more than names by design."""

from __future__ import annotations

import itertools
import json
import re
from collections import Counter
from pathlib import Path

import numpy as np
import pytest

from kriegsspiel import verdict
from kriegsspiel.build import build
from kriegsspiel.combat import MUSKET_RANGE_M
from kriegsspiel.narrator import GAME_ORDINAL, Narrator, rules_sheet, takes_rules_sheet
from kriegsspiel.scenario import load, load_script
from kriegsspiel.staff_text import Lexicon, same_word, staff_view, variant
from kriegsspiel.types import FeatureKind

ROOT = Path(__file__).resolve().parents[2]
PACK = ROOT / "data" / "arms-medlar"
PLAIN = ROOT / "data" / "plain-crossroads"
MIRROR = ROOT / "data" / "mirror-fords"
W, H = 8000.0, 6000.0
CX, CY = W / 2, H / 2
SIDES = ("horse", "foot")
P = {"horse": "H", "foot": "F"}
HORSE_KINDS = {"cuirassier", "dragoon", "hussar"}
FOOT_KINDS = {"line", "grenadier"}
# design-notes.md "Quality": (kind, quality, bodies) per formation key
OOB = {
    "horse": {
        "G": ("grenadier", 5, 2),
        "L1": ("line", 3, 2),
        "L2": ("line", 3, 2),
        "L3": ("line", 3, 2),
        "N1": ("line", 2, 2),
        "CU": ("cuirassier", 4, 2),
        "DR1": ("dragoon", 3, 2),
        "DR2": ("dragoon", 3, 2),
        "HU1": ("hussar", 3, 2),
        "HU2": ("hussar", 3, 2),
        "AR": ("horse_battery", 3, 2),
    },
    "foot": {
        "G": ("grenadier", 5, 2),
        "L1": ("line", 3, 2),
        "L2": ("line", 3, 2),
        "L3": ("line", 3, 2),
        "L4": ("line", 3, 2),
        "L5": ("line", 3, 2),
        "N1": ("line", 2, 2),
        "N2": ("line", 2, 2),
        "DR": ("dragoon", 3, 2),
        "HU": ("hussar", 3, 2),
        "AR": ("foot_battery", 3, 3),
    },
}


def rot(x: float, y: float) -> tuple[float, float]:
    return (W - x, H - y)


def _json(name: str, pack: Path = PACK):
    return json.loads((pack / name).read_text())


@pytest.fixture(scope="module")
def pack():
    return load(PACK)


def points(units, side: str) -> int:
    """the ladder "Arms' armies": a horseman two foot, a gun about thirty-five men (the gun's crew
    inside the thirty-five, so gunners are not counted again). The ladder's own sums: 16,300
    against 16,400."""
    us = [u for u in units if u.side == side]
    foot = sum(u.men for u in us if u.kind.value in FOOT_KINDS)
    horse = sum(u.men for u in us if u.kind.value in HORSE_KINDS)
    guns = sum(u.guns + u.bn_guns for u in us)
    return foot + 2 * horse + 35 * guns


def test_pack_loads_with_plains_clock_and_verdict(pack):
    _world, formations, units, objectives, meta = pack
    assert meta.start == "09:00" and meta.end == "16:00"
    assert takes_rules_sheet(meta)
    assert _json("oob.json")["sides"] == list(SIDES)
    assert set(objectives.sides) == set(SIDES) == set(objectives.players) == set(meta.sides)
    # neither side is "attacker": Meta.attacker takes the first, horse
    assert all(v["role"] == "meeting engagement" for v in meta.sides.values())
    assert {f.side for f in formations} == set(SIDES) and len(units) == 22 + 23
    pm, am = _json("meta.json", PLAIN), _json("meta.json")
    drop = ("battle", "sides", "doc", "strength_documented", "bodies")
    assert {k: v for k, v in pm.items() if k not in drop} == {
        k: v for k, v in am.items() if k not in drop
    }
    assert am["strength_documented"] == {"horse": 11_240, "foot": 13_160}
    assert am["bodies"] == {"horse": 22, "foot": 23}
    pm, am = _json("mission.json", PLAIN), _json("mission.json")
    assert {**pm, "objective": None} == {**am, "objective": None}
    assert am["objective"] == "Medlar Village"


def test_ground_is_plains_under_new_names(pack):
    t, p = pack[0].terrain, load(PLAIN)[0].terrain
    assert np.array_equal(t.cover, p.cover) and np.array_equal(t.elev_m, p.elev_m)
    assert (t.origin, t.width_m, t.height_m) == (p.origin, p.width_m, p.height_m)
    a, b = _json("features.json"), _json("features.json", PLAIN)
    assert [(f["kind"], f["geometry"], f.get("radius_m")) for f in a] == [
        (f["kind"], f["geometry"], f.get("radius_m")) for f in b
    ]

    # new names for everything but the four exits (which say only where the road leaves)
    def words(fs):
        return {
            w
            for f in fs
            if f["kind"] != "exit"
            for n in [f["name"], *f["aliases"]]
            for w in re.findall(r"[A-Z]\w+", n)
        } - {"Farm", "Village"}

    assert not words(a) & words(b) and not words(a) & words(_json("features.json", MIRROR))
    village = pack[0].feature("Medlar Village")
    assert village.kind == FeatureKind.VILLAGE and tuple(village.coords[0]) == (CX, CY)
    assert pack[0].feature("the crossroads") is village
    names = [(f.name, variant(n)) for f in pack[0].features for n in [f.name, *f.aliases]]
    for (x, vx), (y, vy) in itertools.combinations(names, 2):
        if x != y and len(vx) == len(vy):
            assert not all(same_word(i, j) for i, j in zip(vx, vy, strict=True)), (x, y)


def test_armies_as_designed(pack):
    _, formations, units, _, _ = pack
    for side in SIDES:
        fs = [f for f in formations if f.side == side]
        roots = [f for f in fs if f.parent is None]
        assert len(roots) == 1 and roots[0].hq is not None and roots[0].level == "army"
        brigades = {f.id for f in fs if f.parent is not None}
        assert brigades == {f"{P[side]}-{k}" for k in OOB[side]}  # eleven formations
        us = [u for u in units if u.side == side]
        for k, (kind, quality, n) in OOB[side].items():
            mine = [u for u in us if u.parent == f"{P[side]}-{k}"]
            assert len(mine) == n, (side, k)
            assert {(u.kind.value, u.quality) for u in mine} == {(kind, quality)}, (side, k)
            for u in mine:
                if kind.endswith("battery"):
                    calibre = 6 if kind == "horse_battery" else 12
                    assert (u.guns, u.calibre_lb, u.men) == (8, calibre, 120), u.id
                elif kind in HORSE_KINDS:
                    assert (u.men, u.bn_guns) == (400, 0)
                else:
                    assert (u.men, u.bn_guns) == (700, 2)

    def count(side, kinds):
        return sum(1 for u in units if u.side == side and u.kind.value in kinds)

    # the ladder's table: battalions, regiments, batteries
    assert (
        count("horse", FOOT_KINDS),
        count("horse", HORSE_KINDS),
        count("horse", {"horse_battery"}),
    ) == (10, 10, 2)
    assert (
        count("foot", FOOT_KINDS),
        count("foot", HORSE_KINDS),
        count("foot", {"foot_battery"}),
    ) == (16, 4, 3)
    men = {
        s: sum(
            u.men
            for u in units
            if u.side == s and u.kind.value not in ("horse_battery", "foot_battery")
        )
        for s in SIDES
    }
    assert men == {"horse": 11_000, "foot": 12_800}  # the ladder's "men" row
    guns = {s: sum(u.guns + u.bn_guns for u in units if u.side == s) for s in SIDES}
    assert guns == {"horse": 16 + 20, "foot": 24 + 32}
    surnames = [f.commander.split()[-1] for f in formations]
    old = {
        f["commander"].split()[-1]
        for p in (PLAIN, MIRROR)
        for f in _json("oob.json", p)["formations"]
    }
    assert len(set(surnames)) == 24 and not old & set(surnames)


def test_points_within_two_percent(pack):
    units = pack[2]
    pts = {s: points(units, s) for s in SIDES}
    assert pts == {"horse": 16_260, "foot": 16_360}
    assert abs(pts["horse"] - 16_300) <= 50 and abs(pts["foot"] - 16_400) <= 50  # the ladder
    assert abs(pts["horse"] - pts["foot"]) / max(pts.values()) <= 0.02
    # positive control: one more cavalry brigade for the horse army breaks the 2% bound
    assert abs(pts["horse"] + 2 * 800 - pts["foot"]) / (pts["horse"] + 1600) > 0.02


def test_deployment(pack):
    _, _formations, units, _, _ = pack
    dep = _json("deployment.json")
    du = dep["units"]
    by = {s: {u.id: du[u.id] for u in units if u.side == s} for s in SIDES}
    # both first lines 3.5 km from the village; the foot army's frame is the turned one
    assert max(d["x"] for d in by["horse"].values()) == pytest.approx(CX - 3500.0)
    assert min(d["x"] for d in by["foot"].values()) == pytest.approx(CX + 3500.0)
    assert all(d["facing_deg"] == 90.0 for d in by["horse"].values())
    assert all(d["facing_deg"] == 270.0 for d in by["foot"].values())
    assert all(50.0 < d["x"] < W - 50.0 for d in du.values())
    assert all("arrives_at" not in d for d in du.values())
    assert rot(*dep["hq"]["H"]) == pytest.approx(tuple(dep["hq"]["F"]))
    # in each army's own frame (left = +y for horse, -y for foot): states, wings, guns
    for side in SIDES:
        sgn = 1.0 if side == "horse" else -1.0
        d = by[side]
        own_y = {k: sgn * (v["y"] - CY) for k, v in d.items()}
        for uid, v in d.items():
            kind = next(u.kind.value for u in units if u.id == uid)
            if kind.endswith("battery"):
                assert v["state"] == "limbered" and abs(own_y[uid]) <= 350.0, uid  # central
            elif "-G-" in uid:
                assert v["state"] == "column"
            else:
                assert v["state"] == "line", uid
        cav = [uid for uid in d if next(u.kind.value for u in units if u.id == uid) in HORSE_KINDS]
        foot = [uid for uid in d if uid not in cav and "-AR-" not in uid]
        top, bottom = max(own_y[u] for u in foot), min(own_y[u] for u in foot)
        wings = [u for u in cav if own_y[u] > top or own_y[u] < bottom]
        if side == "horse":  # every horse brigade but the cuirassiers on a wing
            assert sorted(wings) == sorted(u for u in cav if "-CU-" not in u)
            assert all(abs(own_y[u]) <= 105.0 for u in cav if "-CU-" in u)
        else:  # the hussars on the left wing, the dragoons on the right
            assert sorted(wings) == sorted(cav)
            assert all(own_y[u] > top for u in cav if "-HU-" in u)
            assert all(own_y[u] < bottom for u in cav if "-DR-" in u)
            assert len({v["x"] for u, v in d.items() if u in foot}) == 2  # two lines
        for a, b in itertools.combinations(d.values(), 2):  # nobody stands on another
            assert np.hypot(a["x"] - b["x"], a["y"] - b["y"]) >= 150.0


def test_mission_is_the_ordinal_verdict(pack):
    world, *_ = pack
    m = verdict.load(PACK)
    assert verdict.validate(m, world.features) == []
    sim = build(PACK, 1, "stub")
    assert sim.ordinal is not None and sim.ordinal.last_minute == 9 * 60
    assert MUSKET_RANGE_M == 250.0


def test_script_is_read(pack):
    loaded = load_script(PACK)
    assert [(s, t) for _, s, t in loaded] == [
        (o["side"], o["text"]) for o in _json("script.json")["orders"]
    ]
    sim = build(PACK, 1, "stub")
    for side in SIDES:
        lex = Lexicon(staff_view(sim.command.side_view(side)))
        own = {f.id for f in sim.forces.formations.values() if f.side == side}
        orders = [t for _, s, t in loaded if s == side]
        assert len(orders) == 13
        for text in orders:
            addressed = lex.formations_in(text)
            assert addressed and addressed[0].i == 0 and addressed[0].key in own, text
            if "Medlar Village" in text:
                assert any(m.key == "Medlar Village" for m in lex.features_in(text)), text


# --------------------------------------------------------------------------- the briefs
GROUND_PAIRS = {"Quince": "Bullace", "Pippin": "Damson", "West": "East", "North": "South"}


def _swap_ground(text: str) -> str:
    pairs = {**GROUND_PAIRS, **{v: k for k, v in GROUND_PAIRS.items()}}
    pat = re.compile(r"\b(" + "|".join(pairs) + r")\b")
    return pat.sub(lambda m: pairs[m.group(1)], text)


def _sections(text: str) -> dict[str, str]:
    parts = re.split(r"^### +", text, flags=re.MULTILINE)[1:]
    return {p.split("\n", 1)[0].strip(): p.split("\n", 1)[1].strip() for p in parts}


@pytest.fixture(scope="module")
def briefs():
    sim = build(PACK, 1, "stub")
    return {s: sim.narrator.brief(sim.picture(s), s, since=0, update=False) for s in SIDES}


def test_first_briefs_share_mission_verdict_clock_rules_and_differ_in_the_armies(pack, briefs):
    world, formations, units, objectives, meta = pack
    nar = Narrator(world, meta, objectives, formations, units)
    nar.ordinal = True  # as build sets it for an ordinal pack (GAME_ORDINAL)
    sec = {s: _sections(objectives.for_player(s)) for s in SIDES}
    assert (
        list(sec["horse"])
        == list(sec["foot"])
        == [
            "Who you are",
            "How the army came here",
            "What headquarters knows of the enemy",
            "The ground",
            "Your orders",
            "The conventions of the day",
        ]
    )
    # the same bytes: the mission and verdict, the clock, the rules sheet, the fixed layer
    assert sec["horse"]["Your orders"] == sec["foot"]["Your orders"]
    assert sec["horse"]["The conventions of the day"] == sec["foot"]["The conventions of the day"]
    assert _swap_ground(sec["horse"]["The ground"]) == sec["foot"]["The ground"]
    assert sec["horse"]["The ground"] != sec["foot"]["The ground"]  # control: swap is real
    for side in SIDES:
        brief = briefs[side]
        assert brief.startswith(nar.persona(side))
        assert GAME_ORDINAL in brief and rules_sheet() in brief
        flat = " ".join(brief.split())
        for words in (
            "(1) An army that breaks loses.",
            "(4) Nothing else counts.",
            "within musket range, 250 m, of the crossroads",
            "until 18:00 at most",
            "take and hold the crossroads at Medlar Village",
            "quality 5 on a scale of 1 to 5",
        ):
            assert words in flat, (side, words)
        for f in formations:  # every own formation's commander is named in his own brief
            if f.side == side and f.parent is not None:
                assert f.commander.split()[-1] in sec[side]["Who you are"], f.id
            if f.side != side:  # the enemy in outline: never his commanders
                assert f.commander.split()[-1] not in objectives.for_player(side), f.id
    # the army sections differ as designed: own army in full, the enemy's in outline
    h, f = sec["horse"], sec["foot"]
    assert "White army, an army strong in horse" in h["Who you are"]
    assert "Green army, an army strong in foot" in f["Who you are"]
    assert "Its horse is five brigades" in h["Who you are"] and (
        "Five brigades of horse" in f["What headquarters knows of the enemy"]
    )
    assert "Its foot is eight brigades" in f["Who you are"] and (
        "Eight brigades of foot" in h["What headquarters knows of the enemy"]
    )
    assert "thirty-six guns" in h["Who you are"] + f["What headquarters knows of the enemy"]
    assert (
        "fifty-six guns" in f["Who you are"]
        and "fifty-six guns" in (h["What headquarters knows of the enemy"])
    )
    assert "six-pounders" in h["Who you are"] and "twelve-pounders" in f["Who you are"]
    for key in ("Who you are", "How the army came here", "What headquarters knows of the enemy"):
        assert h[key] != f[key]
    # the enemy's whereabouts are never in the brief
    for s in SIDES:
        enemy = sec[s]["What headquarters knows of the enemy"]
        assert enemy.endswith("How he has drawn them up and what he intends is not known.")
        assert not re.search(r"\b(left|right|wing|kilometre|metre)s?\b", enemy), s


def test_counts_per_side():
    oob = _json("oob.json")
    assert Counter(f["side"] for f in oob["formations"]) == {"horse": 12, "foot": 12}
    assert Counter(u["side"] for u in oob["units"]) == {"horse": 22, "foot": 23}
