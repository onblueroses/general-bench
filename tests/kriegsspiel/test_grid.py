"""The grid runner with a stub game command: per-harness limits, resume, summary, API refusal."""

from __future__ import annotations

import json
import os
import signal
import sys
import textwrap
import time
from pathlib import Path

import pytest
from test_engine_kit import KOLIN

from kriegsspiel import grid, results

ON_KOLIN = ["--scenario", str(KOLIN)]  # the stub games are shaped like Kolín's

# A stub game: parses the cell arguments, records its start and end in $STUB_TRACE, sleeps
# $STUB_SLEEP, and writes a tiny log shaped like an umpired Kolín game. A model named in
# $STUB_FAIL exits 1 after a header only (a game that died before the verdict).
STUB = textwrap.dedent(
    """
    import argparse, json, os, sys, time
    ap = argparse.ArgumentParser()
    ap.add_argument("--players"); ap.add_argument("--seed", type=int); ap.add_argument("--log")
    ap.add_argument("--mode"); ap.add_argument("--speed"); ap.add_argument("--cadence")
    ap.add_argument("--end"); ap.add_argument("--no-memory", action="store_true")
    ap.add_argument("--scenario")
    a = ap.parse_args()
    players = dict(p.split("=") for p in a.players.split(","))
    name = os.path.basename(os.path.dirname(a.log))
    trace = os.environ.get("STUB_TRACE")
    def mark(what):
        if trace:
            with open(trace, "a") as fh:
                fh.write(f"{what} {name} {time.time()}\\n")
    mark("start")
    print("stub", sys.argv[1:], flush=True)
    time.sleep(float(os.environ.get("STUB_SLEEP", "0")))
    with open(a.log, "w") as fh:
        def w(r): fh.write(json.dumps(r) + "\\n")
        w({"type": "header", "seed": a.seed,
           "scenario": "tests/kriegsspiel/fixtures/packs/kolin",
           "play": {"players": players, "end": a.end}})
        if any(m in os.environ.get("STUB_FAIL", "").split(",") for m in players.values()):
            mark("end"); sys.exit(1)
        w({"type": "verdict", "tick": 390, "summary": "",
           "verdict": {"winner": "austria", "attacker_achieved": False, "decisiveness": 0.3,
                       "rationale": "winner austria (p=0.6); attacker achieved p=0.25; x"}})
    mark("end")
    """
)


@pytest.fixture
def stub(tmp_path, monkeypatch):
    path = tmp_path / "stub_game.py"
    path.write_text(STUB)
    monkeypatch.setattr(grid, "POLL_S", 0.02)
    monkeypatch.setattr(results, "FRESH_S", 0.0)  # a stub log is never mistaken for a live game
    monkeypatch.setenv("STUB_TRACE", str(tmp_path / "trace.txt"))
    monkeypatch.delenv("STUB_FAIL", raising=False)
    return f"{sys.executable} {path}"


def _peaks(trace: Path, harness: dict[str, str]) -> dict[str, int]:
    """Peak number of stub games alive at once per harness, from their own start/end marks."""
    events = []
    for line in trace.read_text().splitlines():
        what, name, t = line.split()
        events.append((float(t), 0 if what == "end" else 1, name))
    live: dict[str, int] = {}
    peak: dict[str, int] = {}
    for _, start, name in sorted(events):
        h = harness[name.split("-")[0]]
        live[h] = live.get(h, 0) + (1 if start else -1)
        peak[h] = max(peak.get(h, 0), live[h])
    return peak


def test_scheduling_respects_per_harness_limits(tmp_path, stub, monkeypatch):
    monkeypatch.setenv("STUB_SLEEP", "0.4")
    out = tmp_path / "g"
    rc = grid.main(
        [
            "--models",
            "opus,fable,sol,luna,astra",
            "--roles",
            "prussia,austria",
            "--seeds",
            "1757",
            "--baseline",
            "--parallel",
            "claude=1,codex=2",
            "--out",
            str(out),
            "--cmd",
            stub,
            "--end",
            "13:30",
            "--speed",
            "2",
            *ON_KOLIN,
        ]
    )
    assert rc == 0
    m = json.loads((out / "manifest.json").read_text())
    assert [c["status"] for c in m["cells"]] == ["done"] * 11
    assert all(
        c["pid"] and c["start"] and c["end"] and c["verdict"]["winner"] == "austria"
        for c in m["cells"]
    )
    harness = {
        "opus": "claude",
        "fable": "claude",
        "sol": "codex",
        "luna": "codex",
        "astra": "codex",
        "script": "script",
    }
    peaks = _peaks(tmp_path / "trace.txt", harness)
    assert peaks["claude"] == 1
    assert peaks["codex"] == 2
    # pass-through flags reach the game unchanged, sides in OOB order, unbuffered stdout file
    so = (out / "opus-austria-s1757" / "stdout.txt").read_text()
    assert "'--players', 'prussia=script,austria=opus'" in so
    assert "'--end', '13:30'" in so and "'--speed', '2'" in so and "'--mode', 'record'" in so
    assert (out / "SUMMARY.md").exists()


def test_resume_skips_done_and_reruns_failed(tmp_path, stub, monkeypatch):
    out = tmp_path / "g"
    args = [
        "--models",
        "opus,sol",
        "--roles",
        "prussia",
        "--seeds",
        "1757",
        "--out",
        str(out),
        "--cmd",
        stub,
        *ON_KOLIN,
    ]
    monkeypatch.setenv("STUB_FAIL", "sol")
    assert grid.main(args) == 1
    m = {c["name"]: c for c in json.loads((out / "manifest.json").read_text())["cells"]}
    assert m["opus-prussia-s1757"]["status"] == "done"
    assert m["sol-prussia-s1757"]["status"] == "failed"
    assert "last record header" in m["sol-prussia-s1757"]["reason"]
    with pytest.raises(SystemExit, match="--resume"):
        grid.main(args)  # an existing grid is never overwritten silently
    monkeypatch.delenv("STUB_FAIL")
    (tmp_path / "trace.txt").write_text("")
    assert grid.main([*args, "--resume"]) == 0
    started = [
        ln.split()[1]
        for ln in (tmp_path / "trace.txt").read_text().splitlines()
        if ln.startswith("start")
    ]
    assert started == ["sol-prussia-s1757"]
    m = {c["name"]: c for c in json.loads((out / "manifest.json").read_text())["cells"]}
    assert m["sol-prussia-s1757"]["status"] == "done"
    assert m["sol-prussia-s1757"]["attempts"] == 2
    assert m["opus-prussia-s1757"]["attempts"] == 1
    moved = list((out / ".attempts").iterdir())  # the failed attempt is kept, not deleted
    assert len(moved) == 1 and moved[0].name.startswith("sol-prussia-s1757-")


def test_pairs_take_a_slot_per_side(tmp_path, stub, monkeypatch):
    monkeypatch.setenv("STUB_SLEEP", "0.3")
    out = tmp_path / "g"
    rc = grid.main(
        [
            "--models",
            "opus",
            "--roles",
            "prussia",
            "--seeds",
            "1757",
            "--pairs",
            "fable:sol,sol:luna",
            "--parallel",
            "claude=2,codex=2",
            "--out",
            str(out),
            "--cmd",
            stub,
            *ON_KOLIN,
        ]
    )
    assert rc == 0
    m = {c["name"]: c for c in json.loads((out / "manifest.json").read_text())["cells"]}
    assert set(m) == {"opus-prussia-s1757", "fable-vs-sol-s1757", "sol-vs-luna-s1757"}
    assert m["sol-vs-luna-s1757"]["players"] == "prussia=sol,austria=luna"
    assert m["sol-vs-luna-s1757"]["harness"] == "codex+codex"
    # sol:luna needs both codex slots, so it never overlaps fable:sol
    ev = {}
    for line in (tmp_path / "trace.txt").read_text().splitlines():
        what, name, t = line.split()
        ev[(what, name)] = float(t)
    a, b = "fable-vs-sol-s1757", "sol-vs-luna-s1757"
    assert ev[("end", a)] <= ev[("start", b)] or ev[("end", b)] <= ev[("start", a)]
    assert grid.parse_parallel("")["api"] == 4


def test_resume_follows_games_started_elsewhere(tmp_path, stub, monkeypatch):
    """A cell directory written by a hand-started game: a fresh log without a verdict is
    followed, not relaunched; a symlinked finished log counts as done."""
    import threading

    monkeypatch.setattr(results, "FRESH_S", 30.0)
    out = tmp_path / "grid-x"
    live = out / "opus-austria-s1757"
    live.mkdir(parents=True)
    hdr = {
        "type": "header",
        "seed": 1757,
        "play": {"players": {"prussia": "script", "austria": "opus"}},
    }
    (live / "run.jsonl").write_text(json.dumps(hdr) + "\n")
    elsewhere = tmp_path / "kolin-opus-3"
    elsewhere.mkdir()
    verdict = {
        "type": "verdict",
        "tick": 390,
        "summary": "",
        "verdict": {
            "winner": "austria",
            "decisiveness": 0.2,
            "rationale": "attacker achieved p=0.3",
        },
    }
    (elsewhere / "run.jsonl").write_text(
        json.dumps(dict(hdr, play={"players": {"prussia": "opus", "austria": "script"}}))
        + "\n"
        + json.dumps(verdict)
        + "\n"
    )
    (out / "opus-prussia-s1757").mkdir()
    (out / "opus-prussia-s1757" / "run.jsonl").symlink_to(elsewhere / "run.jsonl")

    def finish_live():
        time.sleep(0.5)
        with (live / "run.jsonl").open("a") as fh:
            fh.write(json.dumps(verdict) + "\n")

    th = threading.Thread(target=finish_live)
    th.start()
    rc = grid.main(
        [
            "--models",
            "opus",
            "--roles",
            "prussia,austria",
            "--seeds",
            "1757",
            "--out",
            str(out),
            "--cmd",
            stub,
            "--resume",
            *ON_KOLIN,
        ]
    )
    th.join()
    assert rc == 0
    assert not (tmp_path / "trace.txt").exists()  # nothing was launched
    m = {c["name"]: c for c in json.loads((out / "manifest.json").read_text())["cells"]}
    assert m["opus-austria-s1757"]["status"] == "done" and m["opus-austria-s1757"]["external"]
    assert m["opus-prussia-s1757"]["status"] == "done"
    text = (out / "SUMMARY.md").read_text()
    assert "| opus | prussia | 1757 | austria | 0.3 |" in text
    assert "| opus | austria | 1757 | austria |" in text


def test_terminate_stops_running_games_and_marks_them_failed(tmp_path, stub, monkeypatch):
    monkeypatch.setenv("STUB_SLEEP", "60")
    out = tmp_path / "g"
    out.mkdir()
    cells = grid.make_cells(["opus"], ["prussia"], [1757], False, sides=("prussia", "austria"))
    g = grid.Grid(
        out, cells, cmd=stub.split(), game_args=[], limits={}, config={}, out_fn=lambda *_: None
    )
    g.start(cells[0])
    pid = cells[0].pid
    time.sleep(0.3)
    t0 = time.time()
    g.terminate()
    g.write_manifest()
    assert time.time() - t0 < 10
    assert cells[0].status == "failed" and cells[0].reason == "interrupted"
    with pytest.raises(ProcessLookupError):
        os.killpg(pid, 0)
    m = json.loads((out / "manifest.json").read_text())
    assert m["cells"][0]["status"] == "failed"
    assert signal.getsignal(signal.SIGTERM) is not grid._sigterm


def test_api_players_refused_without_allow_api(tmp_path, stub):
    out = tmp_path / "g"
    with pytest.raises(SystemExit, match="--allow-api"):
        grid.main(["--models", "opus,deepseek", "--out", str(out), "--cmd", stub])
    assert not out.exists()
    assert grid.main(["--models", "deepseek", "--allow-api", "--dry-run", "--out", str(out)]) == 0
    with pytest.raises(SystemExit, match="unknown model"):
        grid.main(["--models", "nobody", "--dry-run"])


# A small log with the structure of an umpired Kolín game (fields trimmed).
SUMMARY_TEXT = (
    "Time 19:30 (390 minutes after the start).\n"
    "austria: 54,512 men at the start, 9,759 lost, 3 bodies in flight, 1 destroyed.\n"
    "  Angern's brigade: 2,772 men at Křečhoř heights.\n"
    "prussia: 32,000 men at the start, 10,980 lost, 3 bodies in flight, 0 destroyed.\n"
    "  Heavy artillery: 330 men at Kaiserstrasse.\n"
)
REAL_RECORDS = [
    {
        "clock_start": "13:00",
        "hash0": "d221",
        "jev_model": "typesafe/jev-1.14",
        "mode": "record",
        "play": {
            "cadence_min": 15,
            "end": "19:30",
            "memory": True,
            "players": {"austria": "script", "prussia": "opus"},
            "sides": ["prussia", "austria"],
            "speed": 0.5,
        },
        "scenario": "tests/kriegsspiel/fixtures/packs/kolin",
        "seed": 1757,
        "type": "header",
    },
    {
        "type": "tick",
        "tick": 0,
        "hash": "a",
        "events": [],
        "messages": [],
        "umpire": None,
        "orders": [
            {
                "at": 0,
                "side": "austria",
                "staff": True,
                "tasks": [],
                "text": "The whole army stands fast.",
                "clarifications": ["Nádasdy: the order is unclear; what am I to do?"],
            }
        ],
        "jev": [{"cost": 0.0008, "latency_s": 0.9, "key": "k1", "source": "live"}],
    },
    {
        "type": "commander",
        "side": "austria",
        "commander": "script",
        "consulted_at": 0,
        "arrived_at": 0,
        "trigger": "cadence",
        "wall_s": 0.0,
        "meta": {},
        "orders": ["x"],
    },
    {
        "type": "commander",
        "side": "prussia",
        "commander": "opus",
        "consulted_at": 0,
        "arrived_at": 10,
        "trigger": "cadence",
        "wall_s": 21.5,
        "orders": ["a", "b"],
        "session_id": "s1",
        "meta": {"cost_usd": 0.076, "exit": 0, "harness": "claude -p"},
    },
    {
        "type": "tick",
        "tick": 10,
        "hash": "b",
        "events": [],
        "messages": [],
        "umpire": None,
        "orders": [
            {
                "at": 10,
                "side": "prussia",
                "staff": True,
                "tasks": [],
                "text": "Hülsen, attack.",
                "clarifications": [],
            },
            {
                "at": 10,
                "side": "prussia",
                "staff": True,
                "tasks": [],
                "text": "Zieten, ride.",
                "clarifications": ["Zieten: which body is meant?"],
            },
        ],
        "jev": [{"cost": 0.0012, "key": "k2"}],
    },
    {
        "type": "commander",
        "side": "prussia",
        "commander": "opus",
        "consulted_at": 15,
        "arrived_at": 21,
        "trigger": "first contact",
        "wall_s": 12.5,
        "orders": ["c"],
        "session_id": "s1",
        "meta": {"cost_usd": 0.1364, "resumed": True, "error": "timeout"},
    },
    {
        "type": "commander",
        "side": "prussia",
        "commander": "opus",
        "consulted_at": 380,
        "arrived_at": None,
        "trigger": "cadence",
        "wall_s": 99.0,
        "orders": [],
        "abandoned": True,
        "meta": {},
    },
    {
        "type": "verdict",
        "tick": 390,
        "summary": SUMMARY_TEXT,
        "jev": [{"cost": 0.0001, "key": "k3"}],
        "verdict": {
            "attacker_achieved": False,
            "decisiveness": 0.2733,
            "rationale": "winner austria (p=0.66); attacker achieved p=0.26; "
            "decisiveness level 0.82",
            "winner": "austria",
        },
    },
]


def _write(d: Path, records: list[dict], stdout: str = "") -> None:
    d.mkdir(parents=True)
    (d / "run.jsonl").write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in records))
    (d / "stdout.txt").write_text(stdout)


def test_summary_parses_a_real_shaped_log(tmp_path):
    out = tmp_path / "g"
    out.mkdir()
    (out / "manifest.json").write_text(
        json.dumps(
            {"config": {"scenario": str(KOLIN), "sides": ["prussia", "austria"]}, "cells": []}
        )
    )
    _write(
        out / "opus-prussia-s1757",
        REAL_RECORDS,
        "Clock 19:30 (390 min), time limit; wall 689.7 s, 370 Jev calls, $0.12908\n",
    )
    base = [
        dict(REAL_RECORDS[0], play={"players": {"prussia": "script", "austria": "script"}}),
        REAL_RECORDS[1],
        REAL_RECORDS[-1],
    ]
    _write(out / "script-baseline-s1757", base)
    stopped = [
        dict(REAL_RECORDS[0], seed=1758),
        {"type": "stopped", "tick": 120, "reason": "HTTP 403 limit"},
    ]
    _write(out / "opus-prussia-s1758", stopped)
    pair = [
        dict(REAL_RECORDS[0], play={"players": {"prussia": "opus", "austria": "deepseek"}}),
        *REAL_RECORDS[1:],
    ]
    _write(out / "opus-vs-deepseek-s1757", pair)

    row = results.game_row(out / "opus-prussia-s1757")
    assert row["model"] == "opus" and row["role"] == "prussia" and row["seed"] == 1757
    assert row["winner"] == "austria" and row["attacker_p"] == 0.26
    assert row["decisiveness"] == 0.2733
    assert row["lost_prussia"] == 10980 and row["lost_austria"] == 9759
    assert row["consultations"] == 3  # the abandoned reply counts as a consultation
    assert row["mean_reply_s"] == 17.0  # but not in the reply time: (21.5 + 12.5) / 2
    assert row["orders"] == 2 and row["staff_questions"] == 1  # Prussia's, not Austria's
    assert row["harness_errors"] == 1
    assert row["jev_cost"] == pytest.approx(0.0021)
    assert row["player_cost"] == pytest.approx(0.136)  # cumulative per session: the last
    assert row["wall_min"] == 11.5

    srow = results.game_row(out / "opus-prussia-s1758")
    assert srow["status"] == "stopped" and srow["winner"] == "stopped"

    rc = grid.main(["summary", str(out)])
    assert rc == 0
    text = (out / "SUMMARY.md").read_text()
    assert (
        "| opus | prussia | 1757 | austria | 0.26 | 0.2733 | game "
        "| 10,980 | 9,759 | 3 | 2 | 1 | 17 |" in text
    )
    assert "| opus | prussia | 1758 | stopped |" in text
    assert "## Per model and role" in text and "## Baseline: script against script" in text
    headers = [ln for ln in text.splitlines() if ln.startswith(("| model", "| seed", "| Prussia"))]
    assert len(headers) == 4
    prow = results.game_row(out / "opus-vs-deepseek-s1757")
    assert prow["role"] == "pair" and prow["model"] == "opus vs deepseek"
    assert prow["consultations_prussia"] == 3 and prow["consultations_austria"] == 1
    assert prow["staff_questions_austria"] == 1 and prow["orders_prussia"] == 2
    assert "## Model against model" in text
    assert "| opus | deepseek | 1757 | austria | 0.26 |" in text
    assert not any(w in h.lower() for h in headers for w in ("rank", "score", "elo"))
    agg = next(ln for ln in text.splitlines() if ln.startswith("| opus | prussia | 2 | 1 | 0 |"))
    assert agg


def test_round_robin_plays_every_ordered_pair_and_no_solo_cells(tmp_path, capsys):
    out = tmp_path / "g"
    args = ["--round-robin", "opus,sol,luna", "--seeds", "1,2", "--out", str(out), "--dry-run"]
    assert grid.main(args) == 0
    cells = [line.split(" ")[0] for line in capsys.readouterr().out.splitlines() if " [" in line]
    assert len(cells) == 3 * 2 * 2
    assert all("-vs-" in c for c in cells)
    assert "sol-vs-opus-s2" in cells and "opus-vs-sol-s2" in cells


def test_ordinal_columns_show_how_the_rule_decided():
    sides = ("red", "blue")
    keys = [k for k, _ in grid.columns(sides, ordinal=True)]
    assert "how" in keys and "minute" in keys
    assert not {"attacker_p", "decisiveness", "achieved_red"} & set(keys)
    assert "attacker_p" in [k for k, _ in grid.columns(sides)]
