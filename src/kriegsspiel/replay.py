"""Replaying a run log, named by what is served from the log and what is played again. Every
replay re-runs the scenario from its seed and fails at the first difference, with its tick.

    replay_tasks(world, formations, units, log)   # the logged tasks and umpire answers: no
                                                  # staff, no Jev
    replay_jev("runs/x.jsonl")    # the staff re-read every order and the umpire re-asks every
                                  # question; Jev's answers come from the log
    replay_game("runs/x.jsonl")   # a played game: the generals' replies and Jev's answers come
                                  # from the log, the play loop and the bots run again
"""

from __future__ import annotations

import copy
from dataclasses import dataclass
from pathlib import Path

from .bot import BotCommander, doctrine_for, is_bot
from .build import build
from .commander import Commander, CommanderReplayMismatch, ReplayCommander
from .jev import JevError, LogReplayClient
from .log import RunLog, dumps, jev_calls, read_log, read_records, task_from_json
from .play import CADENCE_MIN, play
from .scenario import DEFAULT_END
from .sim import Sim
from .types import Formation, Unit, Verdict


@dataclass
class Replay:
    """`ok` when the replay was bit-identical; else `reason` and the tick it first differed
    at (`first_mismatch`, -1 for the initial state)."""

    ok: bool
    ticks: int  # ticks replayed
    first_mismatch: int | None = None
    reason: str = ""


@dataclass
class TaskReplay(Replay):
    expected: str | None = None  # the logged state hash where it differed
    got: str | None = None


@dataclass
class JevReplay(Replay):
    verdict: Verdict | None = None
    logged_verdict: dict | None = None
    sim: Sim | None = None  # the replayed sim, at its final state


@dataclass
class GameReplay(Replay):
    verdict: Verdict | None = None
    sim: Sim | None = None


def replay_tasks(
    world,
    formations: list[Formation],
    units: list[Unit],
    log: str | Path | tuple[dict, list[dict]],
    ticks: int | None = None,
) -> TaskReplay:
    """Re-run from the forces, the seed and the log, with the orders as the tasks the staff
    produced and the umpire's answers taken from the log, comparing hashes every tick."""
    header, records = read_log(log) if isinstance(log, str | Path) else log
    sim = Sim(
        world,
        copy.deepcopy(formations),
        copy.deepcopy(units),
        seed=header["seed"],
        clock_start=header.get("clock_start", "13:00"),
    )
    if header.get("hash0") and sim.state_hash() != header["hash0"]:
        return TaskReplay(
            ok=False, ticks=0, first_mismatch=-1, expected=header["hash0"], got=sim.state_hash()
        )
    sim.logged_umpire = []
    n = 0
    for rec in records:
        if ticks is not None and n >= ticks:
            break
        if rec["tick"] != sim.now:
            return TaskReplay(ok=False, ticks=n, first_mismatch=rec["tick"])
        for o in rec.get("orders", []):
            sim.submit_tasks(
                o["side"],
                [task_from_json(t) for t in o["tasks"]],
                at=sim.now,
                text=o["text"],
                clarifications=o.get("clarifications"),
            )
            sim.pending_orders[-1]["at"] = o["at"]
        sim.logged_umpire.extend(rec.get("umpire", []))
        sim.step()
        n += 1
        got = sim.state_hash()
        if got != rec["hash"]:
            return TaskReplay(
                ok=False, ticks=n, first_mismatch=rec["tick"], expected=rec["hash"], got=got
            )
    return TaskReplay(ok=True, ticks=n)


def replay_jev(log_path: str | Path, scenario_dir: str | Path | None = None) -> JevReplay:
    """Re-run a Jev-driven run from its log without network: the staff re-translates every
    order and the umpire re-asks every question against a `LogReplayClient`, which fails on
    any request that differs from the logged one; hashes are compared every tick and the
    verdict at the end."""
    records = read_records(log_path)
    header = next(r for r in records if r.get("type") == "header")
    ticks = [r for r in records if r.get("type", "tick") == "tick"]
    verdicts = [r for r in records if r.get("type") == "verdict"]
    client = LogReplayClient(jev_calls(records), model=header.get("jev_model") or "")
    sim = build(scenario_dir or header["scenario"], header["seed"], "log", client=client)
    if sim.state_hash() != header.get("hash0", sim.state_hash()):
        return JevReplay(False, 0, -1, "initial state differs", sim=sim)
    n = 0
    try:
        for rec in ticks:
            if rec["tick"] != sim.now:
                return JevReplay(False, n, rec["tick"], "tick numbering", sim=sim)
            for o in rec.get("orders", []):
                if o.get("staff"):
                    sim.submit_order(o["side"], o["text"], at=o["at"])
                else:
                    sim.submit_tasks(
                        o["side"],
                        [task_from_json(t) for t in o["tasks"]],
                        at=o["at"],
                        text=o["text"],
                        clarifications=o.get("clarifications"),
                    )
            sim.step()
            n += 1
            if sim.state_hash() != rec["hash"]:
                return JevReplay(False, n, rec["tick"], "state hash differs", sim=sim)
        v = sim.verdict() if verdicts else None
    except (JevError, AssertionError) as e:  # a mismatch is a failed replay, with its tick
        return JevReplay(False, n, sim.now, f"{type(e).__name__}: {e}", sim=sim)
    if client.remaining:
        return JevReplay(
            False, n, None, f"{client.remaining} logged Jev calls not replayed", sim=sim
        )
    logged = verdicts[-1]["verdict"] if verdicts else None
    if v is not None and logged != v.to_json():
        return JevReplay(False, n, None, "verdict differs", v, logged, sim=sim)
    return JevReplay(True, n, verdict=v, logged_verdict=logged, sim=sim)


def _canon(rec: dict) -> dict:
    """A record with its Jev calls reduced to what replay must reproduce (request key,
    questions, answers); how a call was served (live, fixture, log) and its latency differ."""
    return {
        **rec,
        "jev": [{k: c.get(k) for k in ("key", "questions", "answers")} for c in rec.get("jev", [])],
    }


def replay_game(
    log_path: str | Path, scenario_dir: str | Path | None = None, out=None, on_step=None
) -> GameReplay:
    """Re-play a play log with no model and no Jev call: every reply comes from the log's
    commander records (ReplayCommander, checked against the re-narrated brief), every Jev
    answer from its calls (LogReplayClient), every submission at its logged minute. A bot is
    deterministic, so it is rebuilt and plays again. The new log's ticks, commander records
    and verdict must equal the old ones exactly. `on_step(sim)` is called after every minute,
    as in `play`, for a reader that wants the field as the game goes."""
    records = read_records(log_path)
    header = next(r for r in records if r.get("type") == "header")
    cfg = header.get("play") or {}
    old_ticks = [r for r in records if r.get("type", "tick") == "tick"]
    old_cmd = [r for r in records if r.get("type") == "commander"]
    old_verdict = [r for r in records if r.get("type") == "verdict"]
    client = LogReplayClient(jev_calls(records), model=header.get("jev_model") or "")
    runlog = RunLog()
    sim = build(
        scenario_dir or header["scenario"],
        header["seed"],
        "log",
        client=client,
        log=runlog,
        header={"play": cfg},
        battle_over=cfg.get("battle_over") is not False,
    )
    if sim.state_hash() != header.get("hash0"):
        return GameReplay(False, 0, -1, "initial state differs", sim=sim)
    sides = cfg.get("sides") or list(dict.fromkeys(r["side"] for r in old_cmd))
    specs = cfg.get("players") or {}
    commanders: dict[str, Commander] = {
        s: (
            BotCommander(sim, s, doctrine_for(specs[s]))
            if is_bot(specs.get(s, ""))
            else ReplayCommander(old_cmd, s)
        )
        for s in sides
    }
    try:
        stop = next((r["tick"] for r in records if r.get("type") == "stopped"), None)
        res = play(
            sim,
            commanders,
            cfg.get("cadence_min", CADENCE_MIN),
            None,
            end=cfg.get("end", DEFAULT_END),
            out=out,
            stop_at=stop,
            on_step=on_step,
        )
    except (JevError, CommanderReplayMismatch, AssertionError) as e:
        return GameReplay(False, sim.now, sim.now, f"{type(e).__name__}: {e}", sim=sim)
    n = len(runlog.records)
    for a, b in zip(old_ticks, runlog.records, strict=False):
        if dumps(_canon(a)) != dumps(_canon(b)):
            return GameReplay(False, b["tick"], a["tick"], "tick record differs", sim=sim)
    if len(old_ticks) != n:
        return GameReplay(False, n, reason="tick count differs", sim=sim)
    new_cmd = [r for r in runlog.extra if r["type"] == "commander"]
    if [dumps(r) for r in old_cmd] != [dumps(r) for r in new_cmd]:
        return GameReplay(False, n, reason="commander records differ", sim=sim)
    new_verdict = [r for r in runlog.extra if r["type"] == "verdict"]
    if [dumps(_canon(r)) for r in old_verdict] != [dumps(_canon(r)) for r in new_verdict]:
        return GameReplay(False, n, reason="verdict differs", verdict=res.verdict, sim=sim)
    left = client.remaining + sum(
        c.remaining for c in commanders.values() if isinstance(c, ReplayCommander)
    )
    if left:
        return GameReplay(False, n, reason=f"{left} logged calls not replayed", sim=sim)
    return GameReplay(True, n, verdict=res.verdict, sim=sim)
