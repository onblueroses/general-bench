"""The umpire: Jev judges what is judgment.

The engine writes plain prose (named places, states, flanks, who is fresh or blown); Jev reads
it and grades. Jev is never handed numbers it must compute with.

Re-judging a finished run with the v2 account (`account.py`), appended to its log:

    uv run python -m kriegsspiel.umpire rejudge runs/x/run.jsonl [--mode live|record]
        [--rev COMMIT] [--dry-run]

The run is replayed bit-identically with `replay.replay_jev` to its final state; a game played on
older code replays only on that code, so `--rev` exports that commit and replays there. The
record `{"type": "rejudge", "verdict", "account", "jev", "umpire_version": 3, ...}` is appended;
the game's own verdict stays in the log.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from .account import UMPIRE_VERSION, Field, render
from .decisions_llm import make_client
from .jev import REPO_ROOT, JevClient, choice, noul, score
from .log import dumps, read_records
from .scenario import Meta, Objectives, load, load_sides, resolve
from .types import Verdict

MOD_LO, MOD_HI = 0.7, 1.4
SITUATION_LEVELS = [
    "hopeless: the attack cannot succeed; the defender holds every advantage",
    "poor: the attacker is at a clear disadvantage",
    "even: neither side has a clear advantage",
    "favourable: the attacker has a clear advantage",
    "decisive: the attacker holds every advantage; the defender cannot withstand it",
]
# How much of its own objective a side achieved (the battle designs' per-side question). Most
# first, so a stub umpire's first option is "wholly".
ACHIEVED_LEVELS = {
    "wholly": "wholly: every part of the objective achieved",
    "in_the_main": "in the main: the essentials achieved, something lost or left undone",
    "in_part": "in part: some of it achieved, the essentials not",
    "not_at_all": "not at all: nothing of the objective achieved",
}
ACHIEVED_WORDS = {
    "wholly": "wholly",
    "in_the_main": "in the main",
    "in_part": "in part",
    "not_at_all": "not at all",
}
# Below this winner probability a winner that contradicts the per-side levels is replaced by
# the levels' winner (a side named winner at p=0.47 that achieved "in part" against one that
# achieved "in the main")
WINNER_TRUST_P = 0.5
DECISIVENESS_LEVELS = [
    "indecisive: no real result, both armies intact",
    "marginal: a narrow result, the loser retires in order",
    "clear: a clear defeat, the loser driven from the field",
    "crushing: the loser's army broken and in flight",
]


def _map_level(level: float, n: int, lo: float, hi: float) -> float:
    return lo + (hi - lo) * max(0.0, min(1.0, level / (n - 1)))


class JevUmpire:
    def __init__(
        self,
        client: JevClient,
        sides: tuple[str, str] = ("Prussia", "Austria"),
        attacker: str | None = None,
        objectives: str = "",
    ) -> None:
        self.client = client
        self.sides = sides
        self.attacker = attacker or sides[0]
        self.objectives = objectives

    def situation_modifier(self, context: str) -> float:
        """Factor in [0.7, 1.4] on the attacker's impact value; low confidence pulls it to 1.0."""
        a = self.client.ask(
            {
                "document": "An umpire's account of a clash about to be decided.",
                "situation": context,
            },
            {
                "situation": score(
                    "Judge the attacker's prospects in this clash from what the account says "
                    "about formation, order, terrain, flanks, fatigue, morale and surprise.",
                    SITUATION_LEVELS,
                )
            },
        )["situation"]
        if a.score is None:
            return 1.0
        raw = _map_level(a.score, len(SITUATION_LEVELS), MOD_LO, MOD_HI)
        conf = a.confidence if a.confidence is not None else a.p_max
        return round(1.0 + max(0.0, min(1.0, conf)) * (raw - 1.0), 4)

    def _state(self, summary: str) -> dict:
        state = {
            "document": "An umpire's account of the state of a battle.",
            "sides": f"{self.sides[0]} and {self.sides[1]}; the attacker is {self.attacker}.",
            "account": summary,
        }
        if self.objectives:
            state["objectives"] = self.objectives
        return state

    def battle_over(self, summary: str) -> bool:
        a = self.client.ask(
            self._state(summary),
            {
                "over": noul(
                    "Is the battle over: has one side been driven from the field or given up "
                    "its attack, or has the fighting died away so that the day is settled?",
                    "yes, the battle is over",
                    "no, the fighting goes on and the result is still open",
                )
            },
        )["over"]
        return a.yes

    def verdict(self, summary: str) -> Verdict:
        """Per side, how much of its own objective it achieved (wholly, in the main, in part,
        not at all: the battle designs' question), the winner and the decisiveness.
        `attacker_achieved` is the attacker's level being wholly or in the main; its
        probability is the sum of those two options'."""
        s0, s1 = self.sides
        questions = {
            "winner": choice(
                "Judged against each side's objectives, who won the day? A side won only if "
                "it achieved more of its own objective than the other side did of its own.",
                {
                    "side_0": f"{s0} won",
                    "side_1": f"{s1} won",
                    "undecided": "neither side won; the day is undecided",
                },
            ),
            **{
                f"achieved_{i}": choice(
                    f"Judged against {side}'s own objective only, how much of it has {side} "
                    f"achieved?",
                    ACHIEVED_LEVELS,
                )
                for i, side in enumerate(self.sides)
            },
            "decisive": score("How decisive was the result?", DECISIVENESS_LEVELS),
        }
        ans = self.client.ask(self._state(summary), questions)
        w = ans["winner"]
        winner = {"side_0": s0, "side_1": s1}.get(w.choice or "", "undecided")
        d = ans["decisive"]
        decisiveness = (
            round(max(0.0, min(1.0, d.score / (len(DECISIVENESS_LEVELS) - 1))), 4)
            if d.score is not None
            else None
        )
        achieved: dict[str, str] = {}
        parts = []
        p_att = None
        for i, side in enumerate(self.sides):
            a = ans[f"achieved_{i}"]
            if a.choice in ACHIEVED_WORDS:
                achieved[side] = ACHIEVED_WORDS[a.choice]
            parts.append(f"{side} achieved {achieved.get(side, '?')} (p={a.p_max:.2f})")
            if side == self.attacker:
                pr = a.probabilities or {}
                p_att = (
                    round(float(pr.get("wholly", 0.0)) + float(pr.get("in_the_main", 0.0)), 4)
                    if pr
                    else None
                )
                if p_att is None and a.choice in ACHIEVED_WORDS:
                    p_att = 1.0 if a.choice in ("wholly", "in_the_main") else 0.0
        att = achieved.get(self.attacker)
        # consistency: the winner question says a side won only if it
        # achieved more of its own objective than the other; when the levels order the sides
        # and a low-confidence winner answer disagrees, the levels decide
        jev_winner, source, note = winner, "jev", ""
        rank = {lvl: k for k, lvl in enumerate(("not at all", "in part", "in the main", "wholly"))}
        if s0 in achieved and s1 in achieved and achieved[s0] != achieved[s1]:
            by_levels = s0 if rank[achieved[s0]] > rank[achieved[s1]] else s1
            if winner != by_levels and w.p_max < WINNER_TRUST_P:
                winner, source = by_levels, "levels"
                note = f"; winner from the levels (Jev: {jev_winner} p={w.p_max:.2f})"
        return Verdict(
            winner=winner,
            attacker_achieved=None if att is None else att in ("wholly", "in the main"),
            decisiveness=decisiveness,
            rationale=(
                f"winner {jev_winner} (p={w.p_max:.2f}); {'; '.join(parts)}; "
                f"attacker achieved p={p_att}; decisiveness level {d.score}{note}"
            ),
            raw={k: v.raw for k, v in ans.items()},
            achieved=achieved,
            winner_source=source,
            jev_winner=jev_winner if source != "jev" else None,
        )


def umpire_for(
    objectives: Objectives, meta: Meta, sides: list[str], client: JevClient | None
) -> JevUmpire:
    """JevUmpire from the scenario: the two sides in OOB order, the attacker by meta role, and
    each side's objective in its commander's words (the historical outcome is not shown)."""
    text = "\n\n".join(
        f"{s} ({meta.commander(s)}): {objectives.for_side(s)}"
        for s in sides
        if objectives.for_side(s)
    )
    if objectives.umpire:  # the pack's `## Umpire` section: what the umpire is to weigh
        text += "\n\nFor the umpire: " + objectives.umpire
    return JevUmpire(
        client, sides=(sides[0], sides[1]), attacker=meta.attacker(sides), objectives=text
    )


# ---------------------------------------------------------------------------
# Re-judging a finished run with the v2 account


class RejudgeError(RuntimeError):
    pass


def verdict_json(v: Verdict) -> dict:
    return v.to_json()


def _without_rejudges(log: Path, tmp: Path) -> Path:
    """The log as the game left it: earlier rejudge records carry Jev calls that the replay
    of an older revision would count as calls never made."""
    lines = log.read_text().splitlines(keepends=True)
    keep = [x for x in lines if not (x.strip() and json.loads(x).get("type") == "rejudge")]
    if len(keep) == len(lines):
        return log
    out = tmp / "run.jsonl"
    out.write_text("".join(keep))
    return out


def final_field(log: str | Path, rev: str | None = None) -> tuple[dict, str]:
    """Replay `log` to its final state in a subprocess, with the working tree's engine or
    with commit `rev` exported from git, and return (field JSON, where it was replayed)."""
    log = Path(log).resolve()
    src_file = Path(__file__).with_name("final_state.py")
    with tempfile.TemporaryDirectory(prefix="rejudge-") as td:
        tmp = Path(td)
        if rev:
            tree = tmp / "tree"
            tree.mkdir()
            arch = subprocess.run(
                ["git", "-C", str(REPO_ROOT), "archive", rev, "src", "data"],
                capture_output=True,
                check=False,
            )
            if arch.returncode:
                raise RejudgeError(f"git archive {rev}: {arch.stderr.decode()[:300]}")
            subprocess.run(["tar", "-x", "-C", str(tree)], input=arch.stdout, check=True)
            where = subprocess.run(
                ["git", "-C", str(REPO_ROOT), "rev-parse", "--short", rev],
                capture_output=True,
                text=True,
                check=True,
            ).stdout.strip()
        else:
            tree = REPO_ROOT
            head = subprocess.run(
                ["git", "-C", str(REPO_ROOT), "rev-parse", "--short", "HEAD"],
                capture_output=True,
                text=True,
                check=False,
            ).stdout.strip()
            where = f"working tree at {head or '?'}"
        out = tmp / "field.json"
        env = {**os.environ, "PYTHONPATH": str(tree / "src")}
        p = subprocess.run(
            [
                sys.executable,
                "-c",
                src_file.read_text(),
                str(_without_rejudges(log, tmp)),
                str(out),
            ],
            cwd=tree,
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )
        if not out.exists():
            raise RejudgeError(f"replay crashed ({where}): {p.stderr[-800:]}")
        res = json.loads(out.read_text())
    if not res.get("ok"):
        raise RejudgeError(
            f"replay of {log} on the {where} is not bit-identical: {res.get('reason')} "
            f"(tick {res.get('first_mismatch')}); pass --rev with the commit the game was "
            f"played on"
        )
    return res["field"], where


def scenario_umpire(header: dict, client: JevClient):
    """(JevUmpire, features, sunset, deadline) for the run's scenario, as `build.build` sets
    them up."""
    d = resolve(header.get("scenario"))
    world, _formations, _units, objectives, meta = load(d)
    umpire = umpire_for(objectives, meta, load_sides(d), client)
    return umpire, world.features, meta.sunset, meta.deadline


def rejudge(
    log: str | Path,
    mode: str = "live",
    *,
    rev: str | None = None,
    client: JevClient | None = None,
    fixture_dir: str | Path | None = None,
    field: dict | None = None,
    judge: bool = True,
) -> dict:
    """Judge the final state of `log` with the v2 account and append the rejudge record.
    `field` skips the replay (tests); `client` overrides `mode`; `judge=False` only renders
    the account (no Jev call, nothing appended)."""
    log = Path(log)
    records = read_records(log)
    header = next(r for r in records if r.get("type") == "header")
    where = "given field"
    if field is None:
        field, where = final_field(log, rev)
    if client is None:
        client = make_client(mode, fixture_dir or log.parent / "jev")
    umpire, features, sunset, deadline = scenario_umpire(header, client)
    account = render(
        Field.from_json(field), features, umpire.sides, umpire.objectives, sunset, deadline
    )
    rec: dict = {
        "type": "rejudge",
        "umpire_version": UMPIRE_VERSION,
        "tick": field["minutes"],
        "replayed": where,
        "state_hash": field.get("state_hash"),
        "at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "account": account,
    }
    if judge:
        rec["verdict"] = verdict_json(umpire.verdict(account))
        rec["jev"] = [c.to_json() for c in client.drain()]
        with log.open("a") as fh:
            fh.write(dumps(rec) + "\n")
    return rec


def ground_section(account: str) -> str:
    lines = account.splitlines()
    try:
        i = next(k for k, x in enumerate(lines) if x.startswith("Ground."))
    except StopIteration:
        return ""
    j = next((k for k in range(i + 1, len(lines)) if not lines[k].startswith("  ")), len(lines))
    return "\n".join(lines[i + 1 : j])


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        prog="python -m kriegsspiel.umpire", description="Umpire tools (v2 account)."
    )
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("rejudge", help="re-judge a finished run and append the verdict")
    r.add_argument("log")
    r.add_argument("--mode", default="live", choices=("live", "record"))
    r.add_argument("--rev", default=None, help="commit the game was played on (replay there)")
    r.add_argument(
        "--fixtures",
        default=None,
        help="fixture dir for --mode record (default: jev/ beside the log)",
    )
    r.add_argument(
        "--dry-run",
        action="store_true",
        help="print the account only: no Jev call, nothing appended",
    )
    a = ap.parse_args(argv)
    old = [x for x in read_records(a.log) if x.get("type") == "verdict"]
    try:
        rec = rejudge(
            a.log,
            a.mode,
            rev=a.rev,
            fixture_dir=a.fixtures,
            client=JevClient(mode="stub") if a.dry_run else None,
            judge=not a.dry_run,
        )
    except RejudgeError as e:
        print(f"rejudge failed: {e}", file=sys.stderr)
        return 1
    if a.dry_run:
        print(rec["account"])
        print(f"({len(rec['account'].encode())} bytes)")
        return 0
    tokens = sum(c.get("input_tokens") or 0 for c in rec["jev"])
    print(f"{a.log} (replayed on the {rec['replayed']}, tick {rec['tick']})")
    print("  game verdict:    " + (old[-1]["verdict"]["rationale"] if old else "none"))
    print(f"  rejudge (v{rec['umpire_version']}):    " + rec["verdict"]["rationale"])
    print(f"  account: {len(rec['account'].encode()):,} bytes, {tokens:,} input tokens")
    print("Ground:\n" + ground_section(rec["account"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
