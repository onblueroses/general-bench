"""Staff v3: the order reader on the battle packs (no Jev call)."""

from __future__ import annotations

from functools import cache
from pathlib import Path

from test_engine_kit import KOLIN

from kriegsspiel.build import build
from kriegsspiel.staff_text import Lexicon, staff_view, surnames
from kriegsspiel.types import Arm

DATA = Path(__file__).resolve().parents[2] / "data"
PACKS = {"kolin": KOLIN, "plain-crossroads": DATA / "plain-crossroads"}


@cache
def lex(pack: str, side: str) -> Lexicon:
    sim = build(PACKS[pack], 1757, "stub")
    return Lexicon(staff_view(sim.command.side_view(side)))


def test_side_demonyms_are_the_enemys_unless_our_own_names_carry_them():
    blue = lex("plain-crossroads", "blue")
    assert blue.enemy_phrases("drive the Red cavalry off the ridge")[0][1] == Arm.CAVALRY
    assert not blue.enemy_phrases("the Blue cavalry holds")
    prussia = lex("kolin", "prussia")
    assert "prussian" in prussia.own_words
    assert prussia.enemy_phrases("attack the Austrian infantry")
    assert not prussia.enemy_phrases("support the Prussian grenadiers")
    assert lex("kolin", "austria").enemy_phrases("charge the Prussian cavalry")


def test_train_words_name_the_enemys_train_when_we_have_none():
    ph = lex("plain-crossroads", "blue").enemy_phrases("fall on the train wherever you reach it")
    assert ph and ph[0][1] == Arm.TRAIN


def test_an_unnamed_officer_is_no_surname():
    assert surnames("du Muy's artillery officer (name unknown)") == []
    assert surnames("reserve brigadier (unrecorded; under du Muy)") == []
    assert surnames("Oberstwachtmeister Pirkner (train commissary)") == ["pirkner"]


def test_comma_lists_address_every_name():
    p = lex("kolin", "prussia")
    assert p.grammatical_subjects(
        "Hülsen, Tresckow and Zieten, march east along the Kaiserstrasse."
    ) == ["P-HUL", "P-TRE", "P-VAN"]
    r = lex("plain-crossroads", "red")
    assert r.grammatical_subjects(
        "Calloway, the First brigade and the guns, withdraw along the High road."
    ) == ["R-G", "R-L1"]


def test_a_titled_commander_is_addressed_with_his_title():
    """The designed packs list officers as "General Calloway"; "General Calloway, attack ..."
    opens with him all the same (found by the corpus screen)."""
    lx = lex("plain-crossroads", "red")
    f = next(f for f in lx.sv.formations if f.commander == "General Calloway")
    assert lx.subject_at_start("General Calloway attack Teasel Village boldly.") == f.id
    assert lx.subject_at_start("General Calloway, attack Teasel Village boldly.") == f.id
    assert lx.subject_at_start("Calloway, attack Teasel Village boldly.") == f.id
    k = lex("kolin", "prussia")
    z = next(f for f in k.sv.formations if f.commander == "Generalmajor von Katte")
    assert k.subject_at_start("Generalmajor von Katte, screen our right flank.") == z.id
