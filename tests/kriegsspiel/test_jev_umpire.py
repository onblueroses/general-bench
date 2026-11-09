"""Umpire judgments replayed from recorded Jev fixtures (offline); JEV_MODE=record re-records."""

from __future__ import annotations

import os

import pytest

from kriegsspiel.jev import DEFAULT_FIXTURES, JevClient
from kriegsspiel.umpire import MOD_HI, MOD_LO, JevUmpire

MODE = os.environ.get("JEV_MODE", "replay")

OBJECTIVES = (
    "Frederick (Prussia): dislodge Daun from the Křečhoř heights and reopen the Kaiserstrasse "
    "to Kolín before nightfall. Daun (Austria): hold the heights and the road, preserve the army."
)

FAVOURABLE = (
    "Zieten's hussars, fresh and in good order, come out of the oak wood and charge the right "
    "flank of the Austrian line on the Křečhoř heights. The Austrian battalions there stand in "
    "line facing west, already shaken by musketry, and did not see the hussars until they left "
    "the wood. No Austrian cavalry is near."
)
POOR = (
    "Hülsen's advance guard, tired after a long march and disordered after clearing Chocenice, "
    "attacks uphill in column against fresh Austrian grenadiers in line behind the churchyard "
    "wall of Křečhoř, who are supported by guns on the heights. Austrian cavalry waits behind "
    "the village."
)
END_OF_DAY = (
    "Evening, near sunset. The Austrian army still holds the Křečhoř heights, the village of "
    "Křečhoř and the Kaiserstrasse. The Prussian infantry of Hülsen, Tresckow and Manstein has "
    "been broken on the slopes and is falling back west towards Planian; the Prussian cavalry "
    "was routed by a counter-charge of Austrian and Saxon horse. Prussian losses are very heavy, "
    "Austrian losses moderate. Daun's army is intact and in good order on its position; the "
    "Prussians are no longer attacking anywhere."
)


@pytest.fixture(scope="module")
def umpire() -> JevUmpire:
    client = JevClient(mode=MODE, fixture_dir=DEFAULT_FIXTURES)
    return JevUmpire(
        client, sides=("Prussia", "Austria"), attacker="Prussia", objectives=OBJECTIVES
    )


def test_situation_modifier_reads_advantage(umpire):
    good = umpire.situation_modifier(FAVOURABLE)
    bad = umpire.situation_modifier(POOR)
    assert MOD_LO <= bad < 1.0 < good <= MOD_HI


def test_verdict_kolin_historical_end(umpire):
    v = umpire.verdict(END_OF_DAY)
    assert v.winner == "Austria"
    assert v.attacker_achieved is False
    assert v.decisiveness is not None and v.decisiveness >= 1 / 3
    assert set(v.raw) == {"winner", "achieved_0", "achieved_1", "decisive"}
    # per side, against its own objective: Prussia failed, Austria held
    assert v.achieved["Prussia"] in ("not at all", "in part")
    assert v.achieved["Austria"] in ("wholly", "in the main")
    assert "attacker achieved p=" in v.rationale


def test_battle_over_at_kolin_evening(umpire):
    assert umpire.battle_over(END_OF_DAY) is True


def test_stub_umpire_is_neutral_enough():
    u = JevUmpire(JevClient(mode="stub"))
    # Stub answers the middle of five levels ("even"), which maps linearly to 1.05.
    assert u.situation_modifier("anything") == pytest.approx(1.05)
    v = u.verdict("anything")
    assert v.winner == "Prussia"  # stub picks the first option
    assert v.achieved == {"Prussia": "wholly", "Austria": "wholly"} and v.attacker_achieved


def test_low_confidence_pulls_modifier_to_one(monkeypatch):
    client = JevClient(mode="stub")
    u = JevUmpire(client)
    from kriegsspiel import jev

    def fake(q):
        return {"type": "score", "score": 4.0, "confidence": 0.25, "probabilities": {}}

    monkeypatch.setattr(jev, "_stub_answer", fake)
    # decisive level maps to 1.4; a quarter confidence keeps a quarter of the deviation.
    assert u.situation_modifier("x") == pytest.approx(1.1)


@pytest.mark.parametrize(
    ("p_winner", "expect", "source"), [(0.47, "Austria", "levels"), (0.62, "Prussia", None)]
)
def test_a_low_confidence_winner_against_the_levels_is_set_from_the_levels(
    monkeypatch, p_winner, expect, source
):
    """Jev named Red (p=0.47) while Red achieved "in part" and Blue "in the main". Below
    0.5 the levels decide and the record says so; Jev's own answer stays in `raw`."""
    from kriegsspiel import jev

    def fake(q):
        text = q.get("instructions", "")
        if "who won the day" in text:
            return {
                "type": "choice",
                "choice": "side_0",
                "confidence": 0.2,
                "probabilities": {"side_0": p_winner, "side_1": 0.9 - p_winner, "undecided": 0.1},
            }
        if "achieved" in text:
            level = "in_part" if "Prussia's" in text else "in_the_main"
            return {
                "type": "choice",
                "choice": level,
                "confidence": 0.3,
                "probabilities": {level: 0.4},
            }
        return {"type": "score", "score": 1.0, "confidence": 0.5, "probabilities": {}}

    monkeypatch.setattr(jev, "_stub_answer", fake)
    u = JevUmpire(
        JevClient(mode="stub"),
        sides=("Prussia", "Austria"),
        attacker="Prussia",
        objectives=OBJECTIVES,
    )
    v = u.verdict("anything")
    assert v.achieved == {"Prussia": "in part", "Austria": "in the main"}
    assert v.winner == expect
    assert v.raw["winner"]["choice"] == "side_0"  # Jev's answer kept
    assert v.to_json().get("winner_source") == source
    if source:
        assert v.to_json()["jev_winner"] == "Prussia" and "from the levels" in v.rationale
