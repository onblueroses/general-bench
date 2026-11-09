"""Paired wordings: one intent in four wordings that carry the same information (formation,
action, objective, and the same manner and contact words or none) must translate alike.

Eight intents, four registers each (terse, formal staff, florid, modern), against the Prussian
side view at 13:00 frozen in fixtures/jev/views/. Replayed from one recording; JEV_MODE=record
re-records (about two cents). The assertion is agreement: the same formations, kinds and
objectives for all four wordings of an intent, and the same number of staff questions; a second
test pins what the agreed reading is.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from kriegsspiel.jev import DEFAULT_FIXTURES, JevClient
from kriegsspiel.staff import JevStaff, view_from_json
from kriegsspiel.types import TaskKind

VIEWS = Path(__file__).parent / "fixtures" / "jev" / "views"
MODE = os.environ.get("JEV_MODE", "replay")
REGISTERS = ("terse", "formal", "florid", "modern")

ENEMY = "the enemy troops near Křečhoř heights"

# intent -> (four wordings, expected tasks as (formation, kind, objective name or None), questions)
INTENTS: dict[str, tuple[tuple[str, str, str, str], set[tuple], int]] = {
    "cavalry_screens_left": (
        (
            "Cavalry: screen our left flank.",
            "The cavalry is to screen the left flank of the army.",
            (
                "It is my pleasure that the cavalry should spread itself as a screen across our "
                "left flank."
            ),
            "Cavalry, set up a screen on our left flank.",
        ),
        {("P-CAV", TaskKind.SCREEN, "our left flank")},
        0,
    ),
    "hussars_charge_unseen_cavalry": (
        (
            "Zieten's hussars: charge the enemy cavalry at Kutlíře.",
            "Zieten's hussars will charge the enemy cavalry posted at Kutlíře.",
            "Let Zieten's hussars fall upon the enemy horse that stands yonder at Kutlíře.",
            "Zieten's hussars, hit the enemy cavalry at Kutlíře.",
        ),
        {("P-ZIE", TaskKind.HOLD, None)},
        1,
    ),
    "headquarters_to_bristvi": (
        (
            "Headquarters to Bříství.",
            "The headquarters will remove to Bříství.",
            "I shall ride with my headquarters to Bříství.",
            "Moving HQ to Bříství.",
        ),
        {("P", TaskKind.MOVE_HQ, "Bříství")},
        0,
    ),
    "hussars_guard_hulsens_left": (
        (
            "Katte: keep Zieten's hussars on Hülsen's left as he attacks Křečhoř.",
            (
                "Generalmajor von Katte will keep Zieten's hussars on Hülsen's left while Hülsen "
                "attacks Křečhoř."
            ),
            (
                "Let Katte hold Zieten's hussars upon Hülsen's left whilst that general falls upon "
                "Křečhoř."
            ),
            "Katte, keep Zieten's hussars on Hülsen's left flank while he attacks Křečhoř.",
        ),
        {("P-ZIE", TaskKind.SUPPORT, "P-HUL")},
        0,
    ),
    "dragoons_march_and_support": (
        (
            "Normann: march to Bříství and support Hülsen.",
            "Normann's dragoons will march to Bříství and support Hülsen's corps.",
            "Let Normann lead his dragoons to Bříství and there lend his support to Hülsen.",
            "Normann, move to Bříství and back up Hülsen.",
        ),
        {("P-NOR", TaskKind.SUPPORT, "P-HUL")},
        0,
    ),
    "hulsen_takes_krechor_in_flank": (
        (
            "Hülsen: march past Bříství, wheel right, take Křečhoř in flank.",
            "Hülsen's corps will march past Bříství, wheel to the right and take Křečhoř in flank.",
            (
                "Let Hülsen lead his corps past Bříství, then wheel to the right and fall upon "
                "Křečhoř in flank."
            ),
            "Hülsen, go past Bříství, swing right and hit Křečhoř in the flank.",
        ),
        {("P-HUL", TaskKind.ATTACK, "Křečhoř")},
        0,
    ),
    "manstein_advances_to_nove_mesto": (
        (
            "Manstein: advance to Nové Město.",
            "Manstein's brigade will advance to Nové Město.",
            "Let Manstein bring his brigade forward as far as Nové Město.",
            "Manstein, move up to Nove Mesto.",
        ),
        {("P-MAN", TaskKind.ADVANCE, "Nové Město")},
        0,
    ),
    "artillery_bombards_the_heights": (
        (
            "Artillery: bombard the enemy troops on Křečhoř heights.",
            "The heavy artillery will bombard the enemy troops on the Křečhoř heights.",
            "Let our heavy guns play upon the enemy troops arrayed on the Křečhoř heights.",
            "Artillery, shell the enemy troops on Křečhoř heights.",
        ),
        {("P-ART", TaskKind.BOMBARD, ENEMY)},
        0,
    ),
}


def prussia_1300():
    return view_from_json(json.loads((VIEWS / "kolin_1300_prussia.json").read_text()))


_staff = JevStaff(JevClient(mode=MODE, fixture_dir=DEFAULT_FIXTURES))
_cache: dict[str, object] = {}


def translate(text: str):
    if text not in _cache:
        _cache[text] = _staff.translate(text, prussia_1300())
    return _cache[text]


def reading(r) -> set[tuple]:
    return {(t.formation, t.kind, t.objective.name if t.objective else None) for t in r}


@pytest.mark.parametrize("intent", sorted(INTENTS))
def test_four_wordings_agree(intent):
    wordings, _want, _q = INTENTS[intent]
    results = [translate(w) for w in wordings]
    readings = [reading(r) for r in results]
    assert all(x == readings[0] for x in readings), dict(zip(REGISTERS, readings, strict=True))
    counts = [len(r.clarifications) for r in results]
    assert len(set(counts)) == 1, dict(zip(REGISTERS, counts, strict=True))


@pytest.mark.parametrize("intent", sorted(INTENTS))
def test_agreed_reading(intent):
    wordings, want, questions = INTENTS[intent]
    for w in wordings:
        r = translate(w)
        assert reading(r) == want, w
        assert len(r.clarifications) == questions, (w, r.clarifications)
