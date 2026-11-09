"""Offset places: "600 m east of Medlar Village" is a point the staff can place from the named
feature's anchor. Offline: the reader, the view, the vocabulary and a translate with scripted
Jev answers."""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

from test_jev_staff_rules import Scripted, opt, pick

from kriegsspiel.staff import JevStaff, view_from_json, view_to_json
from kriegsspiel.staff_text import Lexicon, offset_places, staff_view, with_offsets
from kriegsspiel.types import RefKind, TaskKind

VIEWS = Path(__file__).parent / "fixtures" / "jev" / "views"
ANCHORS = {"Křečhoř": (5000.0, 6000.0), "Nové Město": (2000.0, 1000.0), "Kaiserstrasse": (0.0, 0.0)}


def view():
    sv = view_from_json(json.loads((VIEWS / "kolin_1300_prussia.json").read_text()))
    return replace(sv, feature_points=dict(ANCHORS))


def test_reads_distance_direction_and_named_place():
    out = offset_places("Hülsen, halt in reserve 600 m east of Křečhoř and hold.", view())
    assert out == {"600 m east of Křečhoř": (5600.0, 6000.0)}


def test_units_directions_abbreviations_and_aliases():
    sv = view()
    got = offset_places(
        "First: 1.5 km to the north-west of Nove Mesto. Second: 400 metres SW from the Krzeczhorz. "
        "Third: 2 km south of Kaiserstrasse, 1,2 km northeastward of Křečhoř.",
        sv,
    )
    assert set(got) == {
        "1.5 km north-west of Nové Město",
        "400 m south-west of Křečhoř",
        "2 km south of Kaiserstrasse",
        "1.2 km north-east of Křečhoř",
    }
    x, y = got["1.5 km north-west of Nové Město"]
    assert abs(x - (2000 - 1500 / 2**0.5)) < 1 and abs(y - (1000 + 1500 / 2**0.5)) < 1
    assert got["2 km south of Kaiserstrasse"] == (0.0, -2000.0)


def test_numbers_in_words():
    sv = view()
    got = offset_places(
        "Hold six hundred metres eastward of Křečhoř; the reserve a kilometre north of Nové Město; "
        "the guns half a kilometre south of Kaiserstrasse; the hussars two thousand yards west of "
        "Křečhoř; one and a half km north-east of Nove Mesto.",
        sv,
    )
    assert got["600 m east of Křečhoř"] == (5600.0, 6000.0)
    assert got["1 km north of Nové Město"] == (2000.0, 2000.0)
    assert got["500 m south of Kaiserstrasse"] == (0.0, -500.0)
    assert "1829 m west of Křečhoř" in got and "1.5 km north-east of Nové Město" in got


def test_nothing_without_a_distance_a_direction_or_an_anchor():
    sv = view()
    assert offset_places("advance east of Křečhoř; halt 600 m short of the village", sv) == {}
    assert offset_places("halt 600 m east of Bříství", sv) == {}  # a feature with no anchor
    assert offset_places("halt 600 m east of Křečhoř", replace(sv, feature_points={})) == {}


def test_with_offsets_adds_point_features_the_lexicon_and_vocabulary_see():
    sv = with_offsets(staff_view(view()), "Hülsen, halt 600 m east of Křečhoř.")
    assert "600 m east of Křečhoř" in sv.feature_names and sv.offsets == {
        "600 m east of Křečhoř": (5600.0, 6000.0)
    }
    lex = Lexicon(sv)
    assert [m.key for m in lex.features_in("halt 600 m east of Křečhoř")] == [
        "600 m east of Křečhoř"
    ]
    ref = lex.feature_ref("600 m east of Křečhoř")
    assert ref.kind == RefKind.POINT and ref.point == (5600.0, 6000.0)
    assert with_offsets(sv, "No orders.") is sv
    again = view_from_json(view_to_json(sv))
    assert again.offsets == sv.offsets and again.feature_points == sv.feature_points


def test_translate_places_the_task_on_the_offset_point():
    seen = {}

    def details(state, qs):
        if "q0_obj" not in qs:
            return {}
        seen["option"] = opt(qs, "q0_obj", "600 m east of Křečhoř")
        return {"q0_kind": pick("hold", 0.95), "q0_obj": pick(seen["option"], 0.95)}

    staff = JevStaff(Scripted({"P-HUL"}, details))
    r = staff.translate("Hülsen, halt in reserve 600 m east of Křečhoř.", view())
    (t,) = r
    assert t.formation == "P-HUL" and t.kind == TaskKind.HOLD
    assert t.objective.kind == RefKind.POINT and t.objective.point == (5600.0, 6000.0)
    assert t.objective.name == "600 m east of Křečhoř"
    assert not r.clarifications
    assert "placed by that distance and direction" in qs_desc(seen["option"], staff)


def qs_desc(oid: str, staff: JevStaff) -> str:
    sv = with_offsets(staff_view(view()), "600 m east of Křečhoř")
    return next(o.desc for o in staff._vocab(sv) if o.oid == oid)
