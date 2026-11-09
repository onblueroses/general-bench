"""The player prompt layer (docs/player-prompt.md): every persona carries the fixed
layer (`narrator.GAME`) and, for a pack with players.md, the side's battle layer in place of the
umpire's objectives text; the umpire never sees players.md; the budgets hold; the fixed layer
names no engine number."""

# ruff: noqa: SIM905  (a word table reads better as one string)
from __future__ import annotations

import re

import pytest
from test_engine_kit import KOLIN, TESTFIELD

from kriegsspiel.jev import REPO_ROOT
from kriegsspiel.narrator import (
    GAME,
    GAME_ORDINAL,
    GAME_UMPIRE_SENTENCES,
    PERSONA_MAX_WORDS,
    RULES_SHEET_MAX_WORDS,
    Narrator,
    takes_rules_sheet,
)
from kriegsspiel.scenario import load, parse_players
from kriegsspiel.umpire import umpire_for

DATA = REPO_ROOT / "data"
PACKS = {
    "kolin": KOLIN,
    **{p: DATA / p for p in ("plain-crossroads", "mirror-fords", "arms-medlar")},
}
# docs/player-prompt.md budgets
FIXED_MAX_WORDS = 1700
SIDE_MIN_WORDS, SIDE_MAX_WORDS = 400, 900  # the designed packs spell the verdict out
NUMBER_WORDS = set(
    """two three four five six seven eight nine ten eleven twelve fifteen twenty
thirty forty fifty sixty hundred hundreds thousand thousands dozen percent metre metres meter
meters kilometre kilometres yard yards pace paces mile miles league leagues""".split()
)


@pytest.fixture(scope="module", params=sorted(PACKS))
def pack(request):
    world, formations, units, objectives, meta = load(PACKS[request.param])
    return request.param, Narrator(world, meta, objectives, formations, units), objectives, meta


def _words(text: str) -> int:
    return len(text.split())


def _umpire_lines(objectives) -> list[str]:
    """The umpire's text in objectives.md: every line of the Outcome and Umpire sections, and
    every question in the side sections (the Kolín pack puts the umpire's questions
    there; a designed pack's side section is the commander's own words, which the battle
    layer may repeat), long enough to be a sentence of its own."""
    out = []
    for body in [objectives.umpire, objectives.outcome]:
        out += [ln.strip() for ln in body.splitlines() if len(ln.strip()) >= 40]
    for body in objectives.sides.values():
        flat = " ".join(body.split())
        out += [q.strip() for q in re.findall(r"[^.?!]*\?", flat) if len(q.strip()) >= 40]
    return out


def test_players_md_parses_for_every_pack(pack):
    slug, _nar, objectives, meta = pack
    sides = list(objectives.players)
    assert sorted(sides) == sorted(meta.sides), slug
    for side, text in objectives.players.items():
        n = _words(text)
        assert SIDE_MIN_WORDS <= n <= SIDE_MAX_WORDS, (slug, side, n)
        assert "?" not in text, (slug, side)  # the umpire's questions are questions


def test_persona_has_the_layers_and_no_umpire_text(pack):
    slug, nar, objectives, meta = pack
    for side in meta.sides:
        persona = nar.persona(side)
        assert (GAME_ORDINAL if nar.ordinal else GAME) in persona
        assert objectives.for_player(side) in persona
        assert "Your objectives, in your own words" not in persona
        lines = _umpire_lines(objectives)
        # positive control: the check finds the umpire's text where it is
        assert lines and any(ln in objectives.text for ln in lines), slug
        for line in lines:
            assert line not in persona, (slug, side, line)
        if objectives.umpire:
            assert objectives.umpire not in persona
        # the rules sheet (docs/battles/README.md) sits outside the persona budget for packs
        # that take it
        budget = PERSONA_MAX_WORDS + (RULES_SHEET_MAX_WORDS if takes_rules_sheet(meta) else 0)
        assert _words(persona) <= budget, (slug, side, _words(persona))


def test_the_umpire_never_reads_players_md(pack):
    slug, _nar, objectives, meta = pack
    sides = list(meta.sides)
    text = umpire_for(objectives, meta, sides, client=None).objectives
    for side in sides:
        assert objectives.for_side(side) in text
        for para in objectives.for_player(side).split("\n\n"):
            if len(para) >= 40:
                assert para not in text, (slug, side, para[:60])


def test_kolin_persona_gives_no_method():
    world, formations, units, objectives, meta = load(KOLIN)
    persona = Narrator(world, meta, objectives, formations, units).persona("prussia")
    assert "roll up" in objectives.for_side("prussia")  # the umpire's text keeps the method
    for word in ("roll up", "wheel", "successive", "refused", "oblique", "past his front"):
        assert word not in persona.casefold(), word


def test_the_fixed_layer_has_no_engine_number():
    assert _words(GAME) <= FIXED_MAX_WORDS
    assert not re.search(r"\d", GAME)
    words = set(re.findall(r"[a-z]+", GAME.casefold()))
    assert not words & NUMBER_WORDS, words & NUMBER_WORDS
    # the consultation contract and the staff's vocabulary are there
    for phrase in (
        "quarter of an hour",
        "stands still",
        "No orders.",
        "our left flank",
        "then",
        "until",
        "You may ask nothing of the umpire",
    ):
        assert phrase in GAME, phrase


def test_a_pack_without_players_md_keeps_its_objectives():
    world, formations, units, objectives, meta = load(TESTFIELD)
    assert not objectives.players
    nar = Narrator(world, meta, objectives, formations, units)
    persona = nar.persona("blue")
    assert GAME in persona and "Your objectives, in your own words" in persona


def test_players_md_refuses_a_section_that_is_no_side():
    with pytest.raises(ValueError, match="Umpire"):
        parse_players("## Blue: X\n\nHold.\n\n## Umpire: weigh\n\nWho holds it?\n", ["blue", "red"])
    got = parse_players(
        "# t\n\nintro\n\n## Red: Y\n\nHold the\nbridge.\n\n### The ground\n\nA river.\n",
        ["blue", "red"],
    )
    assert got == {"red": "Hold the bridge.\n\n### The ground\n\nA river."}


def test_an_ordinal_pack_says_the_rule_decides_and_names_no_umpire_verdict():
    """On the designed packs the fixed layer says the result is a win, a draw or a loss by the
    rule in the orders and that the object is the win; the two umpire sentences go. A pack
    without an ordinal verdict keeps GAME unchanged."""
    from kriegsspiel.build import build

    sim = build(REPO_ROOT / "data" / "plain-crossroads", seed=1, mode="stub", log=None)
    nar = sim.narrator
    assert nar.ordinal
    for side in ("red", "blue"):
        persona = nar.persona(side)
        assert GAME_ORDINAL in persona and GAME not in persona
        for old, new in GAME_UMPIRE_SENTENCES:
            assert old not in persona and new in persona
        assert "the object is the win, and a draw is worth half a win" in persona
    assert not re.search(r"\d", GAME_ORDINAL)
    umpired = build(KOLIN, seed=1, mode="stub", log=None)
    assert not umpired.narrator.ordinal
    assert GAME in umpired.narrator.persona(next(iter(umpired.forces.sides())))
