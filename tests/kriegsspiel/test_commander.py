"""Commanders and the play loop: submission minutes, triggers, near real time, replay from the
log. No network and no model call: stub Jev, stub commanders."""

from __future__ import annotations

import dataclasses
import itertools
import json
import time
from pathlib import Path

from test_engine_kit import KOLIN

from kriegsspiel.build import build
from kriegsspiel.commander import (
    CommanderBase,
    LLMCommander,
    NullCommander,
    ScriptedCommander,
    split_orders,
)
from kriegsspiel.log import RunLog, read_records
from kriegsspiel.play import play, play_game
from kriegsspiel.replay import replay_game

ORDER = "Hülsen, march east along the Kaiserstrasse and storm Křečhoř."


class Fixed(CommanderBase):
    """Answers ORDER at its first consultation at or after `at`, then nothing."""

    name = "fixed"

    def __init__(self, at: int = 0, delay_s: float = 0.0, realtime: bool = False):
        super().__init__()
        self.at, self.delay_s, self.realtime = at, delay_s, realtime
        self.given = False
        self.seen: list[int] = []
        self.last: dict = {}

    def orders(self, brief: str, now: int) -> str | None:
        self.seen.append(now)
        if self.delay_s:
            time.sleep(self.delay_s)
        self.last = {"wall_s": self.delay_s, "meta": {"stub": True}}
        if now >= self.at and not self.given:
            self.given = True
            return ORDER
        return None


def _orders(log: RunLog, side: str = "prussia") -> list[dict]:
    return [o for r in log.records for o in r.get("orders", []) if o["side"] == side]


def _game(commanders, end="13:40", cadence=15, speed=None, log=None):
    runlog = log or RunLog()
    sim = build(KOLIN, 1, "stub", log=runlog)
    res = play(sim, commanders, cadence, speed, end=end, out=None)
    return res, runlog


def test_split_orders():
    assert split_orders("No orders.") == [] and split_orders(None) == []
    assert split_orders("**No orders**") == []
    text = "1. Hülsen, storm Křečhoř at once.\n\n- Zieten, cover his left with the hussars.\nF."
    assert split_orders(text) == [
        "Hülsen, storm Křečhoř at once.",
        "Zieten, cover his left with the hussars.",
    ]


def test_order_is_submitted_at_the_minute_of_the_consultation():
    res, log = _game({"prussia": Fixed(at=0), "austria": NullCommander()})
    first = _orders(log)
    assert [(o["text"], o["at"]) for o in first] == [(ORDER, 0.0)]
    rec = res.consultations[0]
    assert rec["side"] == "prussia" and rec["consulted_at"] == 0 and rec["arrived_at"] == 0
    # an order the general gives only from minute 20 goes out at the first consultation then
    res, log = _game({"prussia": Fixed(at=20), "austria": NullCommander()})
    gave = next(r for r in res.consultations if r["orders"])
    assert gave["consulted_at"] == min(
        r["consulted_at"]
        for r in res.consultations
        if r["side"] == "prussia" and r["consulted_at"] >= 20
    )
    assert [o["at"] for o in _orders(log)] == [float(gave["consulted_at"])]


def test_a_sighting_out_of_reach_is_no_first_contact():
    """At 13:00 every brigade sees the Austrians on the heights, 2 to 4 km off: the reports say
    so ("first contact" in the engine's why), but the general is told "enemy in sight" and is
    not called for it."""
    res, log = _game(
        {"prussia": Fixed(at=10_000), "austria": NullCommander()}, end="13:30", cadence=1000
    )
    recs = [r for r in res.consultations if r["side"] == "prussia"]
    raw = [e for r in log.records for e in r["events"] if e["kind"] == "report_sent"]
    assert raw  # positive control: the reports went out
    assert not [r for r in recs if "first contact" in r["trigger"]]


def test_no_cadence_consultation_within_five_minutes_of_a_reply():
    slow = Fixed(at=0, delay_s=2.0, realtime=True)
    res, _ = _game({"prussia": slow, "austria": NullCommander()}, end="13:14", cadence=5, speed=2.0)
    recs = [r for r in res.consultations if r["side"] == "prussia"]
    first, second = recs[0], recs[1]
    assert first["arrived_at"] > first["consulted_at"]
    # the slot at 13:05 is not skipped but waits out the cooldown after the reply
    assert second["trigger"] == "cadence"
    assert second["consulted_at"] >= first["arrived_at"] + 5, (first, second)


def test_first_contact_trigger_fires_once_per_new_report(monkeypatch):
    from kriegsspiel import narrator

    monkeypatch.setattr(narrator, "CONTACT_REACH_M", 1e9)  # every first sighting is contact
    com = Fixed(at=10_000)
    res, log = _game({"prussia": com, "austria": NullCommander()}, end="13:45", cadence=1000)
    recs = [r for r in res.consultations if r["side"] == "prussia"]
    assert recs[0]["trigger"] == "cadence" and recs[0]["consulted_at"] == 0
    fc = [r for r in recs if "first contact" in r["trigger"]]
    assert fc, recs
    mins = [r["consulted_at"] for r in recs]
    assert all(b - a >= 5 for a, b in itertools.pairwise(mins))  # at most once in 5
    # each such consultation answers a first-contact report that reached hq since the last
    # one, so an old report never fires twice
    reports = [
        (m["received_at"], m["id"])
        for r in log.records
        for m in r["messages"]
        if m["kind"] == "report"
    ]
    sim_msgs = {}
    for r in log.records:
        for e in r["events"]:
            if e["kind"] == "report_received":
                sim_msgs[e["id"]] = r["tick"]
    assert reports and sim_msgs
    prev = 0
    for r in recs[1:]:
        t = r["consulted_at"]
        if "first contact" in r["trigger"]:
            new = r["brief"].split("New dispatches since your last brief:\n", 1)[1]
            new = new.split("\n\n", 1)[0]
            assert "first contact with the enemy" in new, (prev, t)
        prev = t
    # once every brigade has reported its first contact, nothing more fires
    assert recs[-1]["consulted_at"] < 45


def test_slow_commander_order_lands_late():
    slow = Fixed(at=0, delay_s=2.0, realtime=True)
    t0 = time.monotonic()
    res, log = _game({"prussia": slow, "austria": NullCommander()}, end="13:06", speed=1.0)
    wall = time.monotonic() - t0
    o = _orders(log)
    assert len(o) == 1 and o[0]["text"] == ORDER
    # 2 s of thought at 1 sim minute per second: minute 2 when the sim keeps pace; on a
    # loaded machine a Kolín tick can outlast the pace (pacing is a ceiling), so it may be 1
    assert 1.0 <= o[0]["at"] <= 3.0, o
    rec = next(r for r in res.consultations if r["side"] == "prussia")
    assert rec["consulted_at"] == 0 and rec["arrived_at"] == o[0]["at"]
    assert wall >= 2.0
    # the same commander with speed=None: the sim waits, the order goes out at once
    res, log = _game(
        {"prussia": Fixed(at=0, delay_s=0.2, realtime=True), "austria": NullCommander()},
        end="13:03",
        speed=None,
    )
    assert [o["at"] for o in _orders(log)] == [0.0]


def test_play_log_replays_bit_identically(tmp_path):
    log = tmp_path / "play.jsonl"
    res = play_game(
        {"prussia": "script", "austria": "script"},
        mode="stub",
        seed=1757,
        log=log,
        speed=None,
        end="14:00",
        scenario=KOLIN,
        out=None,
    )
    assert res.consultations and any(r["orders"] for r in res.consultations)
    rep = replay_game(log)
    assert rep.ok, rep
    assert rep.ticks == 60
    # a tampered reply fails loudly: its order no longer matches the logged tick
    recs = read_records(log)
    for r in recs:
        if r.get("type") == "commander" and r["orders"]:
            r["reply"] = r["reply"].replace("Křečhoř", "Kutlíře")
            r["orders"] = split_orders(r["reply"])
            break
    bad = tmp_path / "bad.jsonl"
    bad.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in recs))
    assert not replay_game(bad).ok
    # a tampered brief: the re-narrated brief differs from the logged one
    recs = read_records(log)
    next(r for r in recs if r.get("type") == "commander")["brief"] += " "
    bad.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in recs))
    rep = replay_game(bad)
    assert not rep.ok and "CommanderReplayMismatch" in rep.reason


def test_scripted_commander_wakes_at_its_minutes():
    com = ScriptedCommander([(0, ORDER), (7, "Zieten, ride to Kutlíře with the hussars.")])
    _res, log = _game({"prussia": com, "austria": NullCommander()}, end="13:10")
    assert [(o["at"], o["text"][:6]) for o in _orders(log)] == [(0.0, "Hülsen"), (7.0, "Zieten")]


@dataclasses.dataclass
class FakePlayer:
    name: str = "fake"
    model: str = "fake-1"
    effort: str = "low"
    calls: list = dataclasses.field(default_factory=list)

    def act(self, system: str, prompt: str):
        from kriegsspiel.players import Reply

        self.calls.append((system, prompt))
        return Reply(
            text="No orders." if "wait" in prompt else ORDER,
            latency_s=0.5,
            meta={"input_tokens": 10, "output_tokens": 5},
        )


def test_llm_commander_sends_persona_as_system_and_pins_effort():
    player = FakePlayer()
    com = LLMCommander(player, "You are the King.", memory=False)
    assert player.effort == "low" and com.player.effort == "high"  # the roster is untouched
    assert com.orders("You are the King.\n\nIt is 13:00. Orders?", 0) == ORDER
    system, prompt = com.player.calls[0]
    assert system.endswith("You are the King.") and prompt == "It is 13:00. Orders?"
    assert com.last["meta"]["input_tokens"] == 10 and com.last["wall_s"] == 0.5
    assert com.orders("Please wait.", 15) is None


class Remembering(Fixed):
    memory = True


def test_memory_general_gets_the_full_brief_once_then_updates():
    com = Remembering(at=10_000)
    res, _ = _game({"prussia": com, "austria": NullCommander()}, end="13:40")
    briefs = [r["brief"] for r in res.consultations if r["side"] == "prussia"]
    assert len(briefs) >= 2 and all(
        r["memory"] for r in res.consultations if r["side"] == "prussia"
    )
    assert briefs[0].startswith("You are Frederick II") and "Named places" in briefs[0]
    for b in briefs[1:]:
        assert not b.startswith("You are") and "Named places" not in b  # the hq has not moved
        assert "Standing picture: the enemy" in b and "New dispatches since" in b
    assert max(len(b.split()) for b in briefs[1:]) < len(briefs[0].split())


def test_harness_session_resumes_the_same_conversation(monkeypatch, tmp_path):
    from kriegsspiel import commander as cm
    from kriegsspiel import players as gp

    calls = []

    class Done:
        def __init__(self, stdout="", stderr=""):
            self.returncode, self.stdout, self.stderr = 0, stdout, stderr

    def fake_run(cmd, **kw):
        calls.append((list(cmd), kw["cwd"]))
        if "exec" in cmd:
            out = cmd[cmd.index("-o") + 1]
            Path(out).write_text("Hülsen, attack.")
            return Done(stderr="session id: 0199aaaa-bbbb-cccc-dddd-eeeeffff0000\n")
        return Done(
            stdout=json.dumps(
                {
                    "result": "Hülsen, attack.",
                    "session_id": cmd[cmd.index("--session-id") + 1]
                    if "--session-id" in cmd
                    else cmd[cmd.index("--resume") + 1],
                    "usage": {},
                }
            )
        )

    monkeypatch.setattr(cm.subprocess, "run", fake_run)
    home = tmp_path / "codex-home"
    home.mkdir()
    (home / "auth.json").write_text("{}")
    for player in (
        gp.ClaudePlayer(name="c", binary="claude"),
        gp.CodexPlayer(name="x", binary="codex", codex_home=home),
    ):
        calls.clear()
        com = LLMCommander(player, "You are the King.")
        assert com.orders("You are the King.\n\nFirst brief.", 0) == "Hülsen, attack.", com.last
        sid = com.last["session_id"]
        assert sid
        com.orders("Update brief.", 15)
        assert com.last["session_id"] == sid and com.last["meta"]["resumed"]
        (c1, cwd1), (c2, cwd2) = calls
        assert cwd1 == cwd2  # one jail for the whole game
        if isinstance(player, gp.ClaudePlayer):
            assert c1[c1.index("--session-id") + 1] == sid and c2[c2.index("--resume") + 1] == sid
            assert "--no-session-persistence" not in c1 and c1[c1.index("--effort") + 1] == "high"
        else:
            assert c2[1:4] == ["exec", "resume", sid] and "--ephemeral" not in c1
            assert 'model_reasoning_effort="high"' in c2
            assert c1[-1].startswith(com.system) and c2[-1] == "Update brief."
        com.close()
        assert not cwd1.exists()


def test_a_jev_failure_stops_the_game_cleanly_and_replays(tmp_path):
    from kriegsspiel.jev import JevClient, JevError

    class Capped(JevClient):  # the key's spending cap, reached after a few calls
        def __init__(self):
            super().__init__(mode="stub")
            self.n = 0

        def ask(self, state, questions):
            self.n += 1
            if self.n > 6:
                raise JevError("HTTP 403: Key limit exceeded (total limit)")
            return super().ask(state, questions)

    log = tmp_path / "capped.jsonl"
    runlog = RunLog(log)
    sim = build(
        KOLIN,
        1,
        "stub",
        client=Capped(),
        log=runlog,
        header={"play": {"cadence_min": 15, "end": "13:40", "sides": ["prussia", "austria"]}},
    )
    script = ScriptedCommander(
        [
            (0, ORDER),
            (3, "Zieten, ride to Kutlíře with the hussars."),
            (6, "Bevern, hold the Kaiserstrasse at Zlaté Slunce."),
            (9, "Tresckow, follow Hülsen along the Kaiserstrasse."),
        ]
    )
    res = play(
        sim, {"prussia": script, "austria": NullCommander()}, speed=None, end="13:40", out=None
    )
    recs = read_records(log)
    stop = [r for r in recs if r["type"] == "stopped"]
    assert len(stop) == 1 and "Key limit" in stop[0]["reason"]
    assert res.verdict.winner == "undecided" and not [r for r in recs if r["type"] == "verdict"]
    ticks = [r for r in recs if r["type"] == "tick"]
    assert ticks and ticks[-1]["tick"] == stop[0]["tick"] - 1 < 40
    rep = replay_game(log)
    assert rep.ok and rep.ticks == len(ticks), rep


def test_the_sim_waits_for_the_general_by_default():
    """The consultation contract: scored games run with speed=None so a
    slow model is not consulted less often than a fast one; pacing is opt-in."""
    from kriegsspiel import play as play_mod

    assert play_mod.DEFAULT_SPEED is None
