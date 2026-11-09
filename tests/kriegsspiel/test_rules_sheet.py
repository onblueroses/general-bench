"""The rules sheet (docs/rules-sheet.md; docs/battles/README.md): every number in it is the
engine's own, cited in a comment and checked here against the code; a pack opts in with
meta.json "rules_sheet": true and then every general on both sides reads the same bytes, after
the fixed layer and before the battle layer, in every first brief and every one-shot system
prompt; a pack without the flag renders exactly as it would without the sheet."""

from __future__ import annotations

import hashlib
import importlib
import json
import re
import shutil
from decimal import Decimal

import pytest
from test_engine_kit import KOLIN

from kriegsspiel.build import build
from kriegsspiel.commander import LLMCommander
from kriegsspiel.narrator import (
    GAME,
    RULES_SHEET_MAX_WORDS,
    RULES_SHEET_PATH,
    rules_sheet,
    strip_comments,
)

COMMENT = re.compile(r"<!--(.*?)-->", re.DOTALL)
NUMBER = re.compile(r"(?<![\w.])\d+(?:\.\d+)?")
CITE = re.compile(r"^(?P<mod>[a-z_]+)(?:\.(?P<name>.+)|:\s*(?P<expr>.+))$", re.DOTALL)

# First briefs of a pack without the flag (the Kolín test pack, seed 1, stub mode): the
# narrator's output without the rules sheet, with the general's charge in the fixed layer for
# every pack and the staff's offset places. Pinned at the revision that added offset places,
# where the earlier pins (taken before the rules sheet existed) still held.
BEFORE = {
    "austria": "66383a1abda2a5b7d20c7a8d368b2fa2282e22b77a7bf7fd48a89e3c870f53da",
    "prussia": "bce90d17fb440edad13b78fd9d2d1f53144b6d131b58eab76501889363064ed9",
}


def citations(raw: str) -> list[tuple[str, str]]:
    """(number as written, citation) for every cited number; raises AssertionError when a
    number has no citation of its own or a citation follows no number."""
    out = []
    pos = 0
    for m in COMMENT.finditer(raw):
        before, pos = raw[pos : m.start()], m.end()
        body = m.group(1).strip()
        nums = NUMBER.findall(before)
        if body == "input" or CITE.match(body):
            assert nums, f"citation <!-- {body} --> follows no number"
            assert len(nums) == 1, f"numbers {nums} share the citation <!-- {body} -->"
            assert before.rstrip().endswith(nums[-1]), f"<!-- {body} --> is not after its number"
            out.append((nums[-1], body))
        else:  # a maintainers' note
            assert not nums, f"numbers {nums} before a note carry no citation"
    tail = NUMBER.findall(raw[pos:])
    assert not tail, f"numbers {tail} after the last citation carry none"
    return out


def engine_value(cite: str) -> float:
    m = CITE.match(cite)
    assert m, cite
    mod = importlib.import_module(f"kriegsspiel.{m['mod']}")
    expr = m["name"] if m["name"] is not None else m["expr"]
    return float(eval(expr, {"__builtins__": {}}, dict(vars(mod))))


def check(raw: str) -> list[str]:
    """Every cited number against the engine: the value rounded to the places written."""
    bad = []
    for shown, cite in citations(raw):
        if cite == "input":
            continue
        places = -Decimal(shown).as_tuple().exponent
        value = engine_value(cite)
        if round(value, places) != float(shown):
            bad.append(f"{shown} <!-- {cite} --> is {value} in the engine")
    return bad


def test_every_number_is_the_engines_own():
    raw = RULES_SHEET_PATH.read_text(encoding="utf-8")
    assert len(citations(raw)) > 100
    assert check(raw) == []


def test_the_check_catches_a_drifted_number():
    """Positive controls: a changed number, an uncited number and two numbers on one citation
    all fail."""
    raw = RULES_SHEET_PATH.read_text(encoding="utf-8")
    drifted = raw.replace(
        "250 <!-- combat.MUSKET_RANGE_M -->", "300 <!-- combat.MUSKET_RANGE_M -->"
    )
    assert drifted != raw
    assert check(drifted) == ["300 <!-- combat.MUSKET_RANGE_M --> is 250.0 in the engine"]
    with pytest.raises(AssertionError):
        citations(raw.replace("The clock.", "The clock, in 1 page."))
    with pytest.raises(AssertionError):
        citations(raw.replace("Musketry reaches 250", "Musketry reaches 7 or 250"))


def test_the_sheet_a_general_reads_has_no_comments_and_fits():
    text = rules_sheet()
    assert "<!--" not in text and "-->" not in text
    assert "combat." not in text and "movement." not in text
    assert text.startswith("The rules in numbers\n\n")
    assert len(text.split()) <= RULES_SHEET_MAX_WORDS
    assert rules_sheet() == strip_comments(rules_sheet())
    # every cited number survives the stripping, in order
    raw = RULES_SHEET_PATH.read_text(encoding="utf-8")
    assert NUMBER.findall(text) == [n for n, _ in citations(raw)]


@pytest.fixture(scope="module")
def flagged(tmp_path_factory):
    """Kolín with the flag set: the same pack, opted in."""
    d = tmp_path_factory.mktemp("packs") / "kolin"
    shutil.copytree(KOLIN, d)
    meta = json.loads((d / "meta.json").read_text())
    meta["rules_sheet"] = True
    (d / "meta.json").write_text(json.dumps(meta, indent=2))
    return build(d, 1, "stub")


def test_both_sides_read_the_same_sheet_between_the_layers(flagged):
    sim = flagged
    sheet = rules_sheet()
    seen = []
    for side in sim.forces.sides():
        persona = sim.narrator.persona(side)
        assert persona.count(sheet) == 1
        g, s = persona.index(GAME), persona.index(sheet)
        layer = persona.index("Your situation, as your headquarters knows it")
        assert g + len(GAME) < s < s + len(sheet) < layer
        # exactly GAME, the sheet, the battle layer, joined as the persona joins its parts
        assert persona[g:layer] == f"{GAME}\n\n{sheet}\n\n"
        brief = sim.narrator.brief(sim.picture(side), side, since=0)
        assert brief.startswith(persona)
        seen.append(persona[s : s + len(sheet)].encode())
    assert len(seen) == 2 and seen[0] == seen[1]


class _Player:
    name, model = "probe", "probe"

    def __init__(self):
        self.calls: list[tuple[str, str]] = []

    def act(self, system: str, prompt: str):
        from kriegsspiel.players import Reply

        self.calls.append((system, prompt))
        return Reply(text="No orders.", latency_s=0.0)


def test_the_one_shot_path_carries_the_sheet_every_call(flagged):
    sim = flagged
    sheet = rules_sheet()
    for side in sim.forces.sides():
        player = _Player()
        gen = LLMCommander(player, sim.narrator.persona(side), memory=False)
        first = sim.narrator.brief(sim.picture(side), side, since=0)
        gen.orders(first, 0)
        gen.orders("=== a later brief ===", 15)
        assert len(player.calls) == 2
        for system, prompt in player.calls:
            assert system.count(sheet) == 1
            assert sheet not in prompt  # the persona heads the system prompt, not the prompt


@pytest.mark.parametrize("side", sorted(BEFORE))
def test_a_pack_without_the_flag_is_unchanged(side):
    sim = build(KOLIN, 1, "stub")
    assert "rules_sheet" not in sim.narrator.meta.raw
    text = sim.narrator.brief(sim.picture(side), side, since=0)
    assert "The rules in numbers" not in text
    assert hashlib.sha256(text.encode()).hexdigest() == BEFORE[side]


def test_only_true_opts_in(tmp_path):
    from kriegsspiel.narrator import takes_rules_sheet
    from kriegsspiel.scenario import Meta

    assert takes_rules_sheet(Meta(raw={"rules_sheet": True}))
    for v in (False, "true", 1, None):
        assert not takes_rules_sheet(Meta(raw={"rules_sheet": v}))
    assert not takes_rules_sheet(Meta())
