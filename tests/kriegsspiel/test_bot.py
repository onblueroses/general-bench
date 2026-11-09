"""The doctrine bot (kriegsspiel.bot): presets, a bot game that replays, and a bot that plans
from its picture alone."""

from __future__ import annotations

import json

import pytest

from kriegsspiel.bot import PRESETS, BotCommander, doctrine_for, is_bot
from kriegsspiel.build import build
from kriegsspiel.play import make_commander, play_game
from kriegsspiel.replay import replay_game
from kriegsspiel.verdict import load, ordinal_params

PLAIN = "data/plain-crossroads"


def test_doctrine_specs():
    assert doctrine_for("bot") is PRESETS["strong"]
    assert doctrine_for("bot:weak") is PRESETS["weak"]
    assert is_bot("bot:strong") and not is_bot("botany") and not is_bot("script")
    with pytest.raises(ValueError):
        doctrine_for("bot:clever")
    w, s = PRESETS["weak"], PRESETS["strong"]
    assert w.reaction_min > s.reaction_min and w.concentration < s.concentration
    assert not w.commit_reserve and s.commit_reserve


@pytest.mark.parametrize("pack", ["plain-crossroads", "mirror-fords", "arms-medlar"])
def test_bot_plays_for_the_objective(pack):
    sim = build(f"data/{pack}", 1, "stub")
    want = ordinal_params(load(sim.scenario_dir))["objective"]
    for side in sim.forces.sides():
        assert BotCommander(sim, side, "strong").place.name == want


def test_bot_game_replays_bit_identically(tmp_path):
    """Strong against weak on Plain for 45 minutes: the bots send tasks (never the staff, so no
    Jev translation call), and the game replays from its log to the same verdict."""
    log = tmp_path / "run.jsonl"
    res = play_game(
        {"red": "bot:strong", "blue": "bot:weak"},
        mode="stub",
        seed=3,
        log=log,
        speed=None,
        end="09:45",
        out=None,
        scenario=PLAIN,
    )
    orders = [o for r in res.sim.log.records for o in r.get("orders", [])]
    assert orders and all(not o["staff"] and o["tasks"] for o in orders)
    assert {o["side"] for o in orders} == {"red", "blue"}
    assert all(
        c.get("questions") is None or "translate" not in json.dumps(c)
        for r in res.sim.log.records
        for c in r.get("jev", [])
    )
    rep = replay_game(log)
    assert rep.ok, rep.reason
    assert rep.verdict.to_json() == res.verdict.to_json()


def test_bot_reads_only_its_picture():
    """The bot plans from its side's picture and static knowledge only: with the picture
    held fixed, scrambling the true positions of every body (both sides) after the bot is
    built changes none of its orders."""

    def first_orders(scramble: bool):
        sim = build(PLAIN, 1, "stub")
        for _ in range(30):
            sim.step()
        bot = BotCommander(sim, "red", "strong")
        pic = sim.picture("red")
        sim.picture = lambda side: pic  # type: ignore[method-assign]
        if scramble:
            for k, u in enumerate(sorted(sim.forces.units.values(), key=lambda u: u.id)):
                u.x, u.y = 500.0 + 37.0 * k, 5000.0 - 23.0 * k
        tasks = bot.plan(30)
        return [
            (
                t.formation,
                t.kind.value,
                t.objective.name if t.objective else None,
                t.objective.point if t.objective else None,
            )
            for t in tasks
        ]

    assert first_orders(False) == first_orders(True)


def test_make_commander_needs_sim():
    sim = build(PLAIN, 1, "stub")
    nar = sim.narrator
    c = make_commander("bot:weak", "blue", nar, sim.clock_start, sim=sim)
    assert isinstance(c, BotCommander) and c.doctrine is PRESETS["weak"]
    with pytest.raises(ValueError):
        make_commander("bot", "blue", nar, sim.clock_start)
