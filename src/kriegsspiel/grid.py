"""The model grid: models x roles x seeds of one scenario, each cell a `kriegsspiel.run` game
in its own subprocess, a per-harness concurrency limit, a manifest, resume, and a summary
table of measured outcomes (no composite score, no ranking).

    uv run python -m kriegsspiel.grid --models opus,fable,sol,luna,astra \
        --roles red,blue --seeds 1,2 --baseline
    uv run python -m kriegsspiel.grid --resume --out runs/grid-plain
    uv run python -m kriegsspiel.grid summary runs/grid-plain
    uv run python -m kriegsspiel.grid cross runs/cross.md runs/grid-x-plain runs/grid-x-mirror ...

`--scenario data/<slug>` plays another pack (default data/plain-crossroads); its sides come from its
oob.json. A cell plays `<role>=<model>` against `<other side>=script` (the side's script.json). The
baseline cells play script against script, one per seed. Cell directory
`<out>/<model>-<role>-s<seed>/` (baseline `script-baseline-s<seed>`) holds `run.jsonl`, `stdout.txt`
(stdout and stderr) and, in record mode, the Jev fixtures under `jev/`.

`--cmd` (or `KRIEGSSPIEL_GRID_CMD`) replaces the game command prefix
(`uv run python -m kriegsspiel.run`); the cell arguments are appended unchanged. Tests use it
to run a stub that writes a tiny log.

`cross OUT DIR [DIR ...]` writes one report across several grids (`kriegsspiel.cross`);
`--format csv` writes one flat row per cell instead.

API-route players (`ApiPlayer` in `kriegsspiel.players`) are billed per token and are refused
unless `--allow-api` is given.
"""

from __future__ import annotations

import argparse
import contextlib
import datetime as _dt
import json
import os
import shlex
import signal
import subprocess
import sys
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import IO

from . import results
from .bot import is_bot
from .cross import cross, cross_csv
from .jev import REPO_ROOT
from .players import ROSTER
from .results import game_row, last_record, load_grid, mean_of, table, verdict_summary
from .scenario import DEFAULT_SCENARIO, load_sides, resolve

DEFAULT_MODELS = ("opus", "fable", "sol", "luna", "astra")
DEFAULT_SEEDS = (1, 2)
DEFAULT_PARALLEL = {"claude": 2, "codex": 2, "api": 4}  # script and anything unnamed: unlimited
GAME_CMD = ("uv", "run", "python", "-m", "kriegsspiel.run")
CMD_ENV = "KRIEGSSPIEL_GRID_CMD"
POLL_S = 0.5
TERM_GRACE_S = 15.0


def scenario_sides(scenario: str | Path | None) -> tuple[str, ...]:
    """The sides of a scenario in oob.json order (the default scenario's when none is given)."""
    return tuple(load_sides(resolve(scenario)))


def harness_of(model: str) -> str:
    """'script', 'bot', 'claude', 'codex' or 'api' for a player spec (a ROSTER name, script,
    or bot[:strong|weak], the doctrine opponent: no model, no concurrency limit)."""
    if model == "script":
        return "script"
    if is_bot(model):
        return "bot"
    p = ROSTER.get(model)
    if p is None:
        raise SystemExit(f"unknown model {model!r}; one of {sorted(ROSTER)}")
    return p.harness


@dataclass
class Cell:
    name: str
    model: str  # "script" for a baseline cell, "a vs b" for a pair
    role: str  # the side the model plays; "baseline" (script vs script) or "pair"
    seed: int
    players: str  # the --players value
    harness: str  # "claude", "codex", "api", "script"; a pair "claude+codex"
    status: str = "pending"  # pending, running, done, failed
    start: str | None = None  # ISO wall time
    end: str | None = None
    wall_s: float | None = None
    pid: int | None = None
    returncode: int | None = None
    reason: str | None = None
    verdict: dict | None = None
    attempts: int = 0
    external: bool = False  # running, but started outside this grid process (no child of ours)
    engine_commit: str | None = None  # repo HEAD when the cell's game was started

    @property
    def uses(self) -> list[str]:
        """One harness slot per LLM side of the game."""
        return self.harness.split("+")

    def manifest(self) -> dict:
        return asdict(self)


def make_cells(
    models: list[str],
    roles: list[str],
    seeds: list[int],
    baseline: bool,
    pairs: list[tuple[str, str]] = (),
    sides: tuple[str, ...] | None = None,
) -> list[Cell]:
    """Cells in launch order: per seed, the roles, then the models, then the pairs (a plays
    the first side, b the second), so the first games to start spread over the harnesses.
    `sides` defaults to the default scenario's."""
    sides = sides or scenario_sides(None)
    cells = []
    for seed in seeds:
        for role in roles:
            for m in models:
                # sides always in OOB order: play() submits in this order
                players = ",".join(f"{s}={m if s == role else 'script'}" for s in sides)
                cells.append(
                    Cell(
                        name=f"{m}-{role}-s{seed}",
                        model=m,
                        role=role,
                        seed=seed,
                        players=players,
                        harness=harness_of(m),
                    )
                )
        if baseline:
            cells.append(
                Cell(
                    name=f"script-baseline-s{seed}",
                    model="script",
                    role="baseline",
                    seed=seed,
                    players=",".join(f"{s}=script" for s in sides),
                    harness="script",
                )
            )
        for a, b in pairs:
            cells.append(
                Cell(
                    name=f"{a}-vs-{b}-s{seed}",
                    model=f"{a} vs {b}",
                    role="pair",
                    seed=seed,
                    players=f"{sides[0]}={a},{sides[1]}={b}",
                    harness=f"{harness_of(a)}+{harness_of(b)}",
                )
            )
    return cells


def _find_pid(needle: str) -> int | None:
    """A live process whose command line contains `needle` (the cell's log path), from
    /proc; None if there is none or /proc is unreadable."""
    try:
        entries = os.listdir("/proc")
    except OSError:
        return None
    me = os.getpid()
    for e in entries:
        if not e.isdigit() or int(e) == me:
            continue
        try:
            cmd = (
                Path(f"/proc/{e}/cmdline")
                .read_bytes()
                .replace(b"\0", b" ")
                .decode(errors="replace")
            )
        except OSError:
            continue
        if needle in cmd and "kriegsspiel.run" in cmd:
            return int(e)
    return None


def parse_parallel(text: str) -> dict[str, int]:
    out = dict(DEFAULT_PARALLEL)
    for part in filter(None, (p.strip() for p in text.split(","))):
        k, _, v = part.partition("=")
        if not v:
            raise SystemExit(f"--parallel wants harness=N pairs, got {part!r}")
        out[k.strip()] = int(v)
    return out


def engine_commit() -> str | None:
    """Short HEAD of the repo, `+dirty` when src/ or data/ differ from it; None without git."""
    try:
        head = subprocess.run(
            ["git", "-C", str(REPO_ROOT), "rev-parse", "--short", "HEAD"],
            check=False,
            capture_output=True,
            text=True,
            timeout=10,
        )
        if head.returncode:
            return None
        dirty = subprocess.run(
            ["git", "-C", str(REPO_ROOT), "diff", "--quiet", "HEAD", "--", "src", "data"],
            check=False,
            capture_output=True,
            timeout=10,
        ).returncode
        return head.stdout.strip() + ("+dirty" if dirty else "")
    except (OSError, subprocess.SubprocessError):
        return None


def _now_iso() -> str:
    return _dt.datetime.now().astimezone().isoformat(timespec="seconds")


class Grid:
    def __init__(
        self,
        out: Path,
        cells: list[Cell],
        *,
        cmd: list[str],
        game_args: list[str],
        limits: dict[str, int],
        config: dict,
        out_fn=print,
    ):
        self.out = out
        self.cells = cells
        self.cmd = cmd
        self.game_args = game_args
        self.limits = limits
        self.config = config
        self.say = out_fn
        self.procs: dict[str, subprocess.Popen] = {}
        self.files: dict[str, IO[str]] = {}
        self.t0: dict[str, float] = {}  # wall clock at each running child's start
        self.max_running: dict[str, int] = {}  # observed peak per harness (tests read it)

    # -- manifest
    def write_manifest(self) -> None:
        data = {
            "config": self.config,
            "updated": _now_iso(),
            "cells": [c.manifest() for c in self.cells],
        }
        tmp = self.out / "manifest.json.tmp"
        tmp.write_text(json.dumps(data, indent=1, ensure_ascii=False) + "\n")
        tmp.replace(self.out / "manifest.json")

    def cell_dir(self, c: Cell) -> Path:
        return self.out / c.name

    def argv(self, c: Cell) -> list[str]:
        log = self.cell_dir(c) / "run.jsonl"
        return [
            *self.cmd,
            "--players",
            c.players,
            "--seed",
            str(c.seed),
            "--log",
            str(log),
            *self.game_args,
        ]

    # -- resume
    def is_live(self, c: Cell) -> bool:
        """A game outside our children is live while its process runs (found by its log path
        in /proc) or its log was written within FRESH_S."""
        log = self.cell_dir(c) / "run.jsonl"
        pid = _find_pid(f"{self.out.name}/{c.name}/run.jsonl")
        if pid is not None:
            c.pid = pid
            return True
        try:
            return time.time() - log.stat().st_mtime < results.FRESH_S
        except OSError:
            return False

    def reconcile(self, resume: bool) -> None:
        """Mark cells whose log ends in a verdict as done. Without --resume an existing cell
        directory is refused; with it, a game still running outside this process (started by
        hand or by another grid) is followed as `external`, and an incomplete one is moved
        aside to `<out>/.attempts/` (never deleted) and the cell reruns. A cell directory may
        hold a symlinked run.jsonl of a game played elsewhere."""
        old = {}
        mf = self.out / "manifest.json"
        if mf.exists():
            try:
                old = {c["name"]: c for c in json.loads(mf.read_text()).get("cells", [])}
            except (json.JSONDecodeError, OSError):
                old = {}
        for c in self.cells:
            d = self.cell_dir(c)
            if not d.exists():
                continue
            if not resume:
                raise SystemExit(f"{d} exists; pass --resume to continue this grid")
            rec = last_record(d / "run.jsonl")
            prev = old.get(c.name, {})
            c.attempts = int(prev.get("attempts") or 0)
            if rec and rec.get("type") == "verdict":
                c.status, c.verdict = "done", verdict_summary(rec)
                for k in ("start", "end", "wall_s", "pid", "returncode", "engine_commit"):
                    setattr(c, k, prev.get(k))
                continue
            if self.is_live(c):
                c.status, c.external = "running", True
                c.start = prev.get("start") or _dt.datetime.fromtimestamp(
                    d.stat().st_ctime
                ).astimezone().isoformat(timespec="seconds")
                self.say(
                    f"{c.name}: running outside this grid"
                    + (f" (pid {c.pid})" if c.pid else "")
                    + "; following its log"
                )
                continue
            stamp = _dt.datetime.now().strftime("%Y%m%dT%H%M%S")
            dest = self.out / ".attempts" / f"{c.name}-{stamp}"
            dest.parent.mkdir(parents=True, exist_ok=True)
            d.rename(dest)
            self.say(
                f"{c.name}: incomplete ({(rec or {}).get('type', 'no log')}); "
                f"moved to {dest.relative_to(self.out)}, rerunning"
            )

    # -- scheduling
    def running(self, harness: str) -> int:
        return sum(c.uses.count(harness) for c in self.cells if c.status == "running")

    def can_start(self, c: Cell) -> bool:
        """Every harness the game uses has room; a pair needing more slots than the limit
        starts when that harness is otherwise idle."""
        for h in set(c.uses):
            lim, busy = self.limits.get(h), self.running(h)
            if lim is not None and busy and busy + c.uses.count(h) > lim:
                return False
        return True

    def start(self, c: Cell) -> None:
        d = self.cell_dir(c)
        d.mkdir(parents=True, exist_ok=True)
        fh = (d / "stdout.txt").open("w")
        env = {**os.environ, "PYTHONUNBUFFERED": "1"}
        p = subprocess.Popen(
            self.argv(c),
            stdout=fh,
            stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL,
            cwd=REPO_ROOT,
            env=env,
            start_new_session=True,
        )  # Ctrl-C reaches the grid, not the games
        self.procs[c.name], self.files[c.name], self.t0[c.name] = p, fh, time.time()
        c.status, c.pid, c.start, c.end = "running", p.pid, _now_iso(), None
        c.returncode = c.reason = c.verdict = c.wall_s = None
        c.attempts += 1
        c.engine_commit = self.config.get("engine_commit")
        for h in set(c.uses):
            self.max_running[h] = max(self.max_running.get(h, 0), self.running(h))
        self.say(f"start {c.name} (pid {p.pid}, {c.harness})")

    def finish(self, c: Cell, rc: int, reason: str | None = None) -> None:
        self.procs.pop(c.name, None)
        fh = self.files.pop(c.name, None)
        if fh is not None:
            fh.close()
        t0 = self.t0.pop(c.name, None)
        c.end, c.returncode = _now_iso(), rc
        c.wall_s = round(time.time() - t0, 1) if t0 else None
        rec = last_record(self.cell_dir(c) / "run.jsonl")
        if reason is None and rc == 0 and rec and rec.get("type") == "verdict":
            c.status, c.verdict = "done", verdict_summary(rec)
        else:
            c.status = "failed"
            c.reason = reason or (f"exit {rc}; last record {(rec or {}).get('type', 'none')}")
            if rec and rec.get("type") == "stopped":
                c.reason += f": {str(rec.get('reason', ''))[:200]}"
        v = c.verdict or {}
        self.say(
            f"{c.status} {c.name} in {c.wall_s} s"
            + (f": winner {v.get('winner')}" if v else f" ({c.reason})")
        )

    def run(self) -> int:
        self.write_manifest()
        try:
            while True:
                changed = False
                for c in self.cells:
                    if c.status == "running" and c.external:
                        rec = last_record(self.cell_dir(c) / "run.jsonl")
                        if rec and rec.get("type") == "verdict":
                            c.status, c.verdict, c.end = "done", verdict_summary(rec), _now_iso()
                            self.say(f"done {c.name} (external): winner {c.verdict['winner']}")
                            changed = True
                        elif not self.is_live(c):
                            c.status, c.end = "failed", _now_iso()
                            c.reason = (
                                f"external game went quiet; last record "
                                f"{(rec or {}).get('type', 'none')}"
                            )
                            self.say(f"failed {c.name} ({c.reason}); --resume reruns it")
                            changed = True
                    elif c.status == "running":
                        rc = self.procs[c.name].poll()
                        if rc is not None:
                            self.finish(c, rc)
                            changed = True
                for c in self.cells:
                    if c.status == "pending" and self.can_start(c):
                        self.start(c)
                        changed = True
                if changed:
                    self.write_manifest()
                if not any(c.status in ("pending", "running") for c in self.cells):
                    break
                time.sleep(POLL_S)
        except KeyboardInterrupt:
            self.say("interrupted: stopping the running games")
            self.terminate()
            self.write_manifest()
            return 130
        self.write_manifest()
        failed = [c.name for c in self.cells if c.status == "failed"]
        self.say(
            f"grid finished: {len(self.cells) - len(failed)} done, {len(failed)} failed"
            + (f" ({', '.join(failed)})" if failed else "")
        )
        return 1 if failed else 0

    def terminate(self) -> None:
        """SIGTERM every game's process group (uv, python and the harness children), then
        SIGKILL what is still alive after the grace period."""
        live = {n: p for n, p in self.procs.items() if p.poll() is None}
        for p in live.values():
            with contextlib.suppress(ProcessLookupError):
                os.killpg(p.pid, signal.SIGTERM)
        deadline = time.time() + TERM_GRACE_S
        for p in live.values():
            try:
                p.wait(timeout=max(0.1, deadline - time.time()))
            except subprocess.TimeoutExpired:
                with contextlib.suppress(ProcessLookupError):
                    os.killpg(p.pid, signal.SIGKILL)
                p.wait()
        for c in self.cells:
            if c.status == "running" and not c.external:  # never touch a game we did not start
                p = self.procs.get(c.name)
                self.finish(
                    c, p.returncode if p and p.returncode is not None else -1, reason="interrupted"
                )


# ---------------------------------------------------------------------------
# Summary: one row per game from its log


def outcome_columns(sides: tuple[str, ...], ordinal: bool = False) -> list[tuple[str, str]]:
    """The winner, how the verdict fell (an ordinal pack's rule, or the umpire's attacker
    probability and decisiveness) and each side's losses."""
    how = (
        [("how", "how it ended"), ("minute", "minute")]
        if ordinal
        else [
            ("attacker_p", "attacker achieved p"),
            ("decisiveness", "decisiveness"),
            ("judged", "verdict from"),
        ]
    )
    return [("winner", "winner"), *how, *[(f"lost_{s}", f"{s} losses") for s in sides]]


def columns(sides: tuple[str, ...], ordinal: bool = False) -> list[tuple[str, str]]:
    return [
        ("model", "model"),
        ("role", "role"),
        ("seed", "seed"),
        *outcome_columns(sides, ordinal),
        ("consultations", "consultations"),
        ("orders", "orders"),
        ("staff_questions", "staff questions"),
        ("mean_reply_s", "mean reply s"),
        ("harness_errors", "harness errors"),
        ("wall_min", "game wall min"),
        ("jev_cost", "Jev $"),
        ("player_cost", "player $ (notional)"),
        # the umpire's per-side levels, which an ordinal pack's rule does not use
        *([] if ordinal else [(f"achieved_{s}", f"{s} achieved") for s in sides]),
        ("status", "status"),
    ]


def summary(out: Path) -> str:
    out = Path(out)
    config, mcells, dirs = load_grid(out)
    sides = tuple(config.get("sides") or scenario_sides(None))
    rows = [game_row(d, mcells.get(d.name)) for d in dirs]
    ordinal = any(r.get("how") for r in rows)
    cols_all = columns(sides, ordinal)
    games = [r for r in rows if r.get("role") not in ("baseline", "pair")]
    base = [r for r in rows if r.get("role") == "baseline"]
    pairs = [r for r in rows if r.get("role") == "pair"]
    lines = [
        f"# Grid summary: {out.name}",
        "",
        (
            f"Measured outcomes per game; attacker is {sides[0].capitalize()} unless the "
            "scenario's meta names another. No composite score."
        ),
        "",
    ]
    lines += table(games, cols_all)
    agg = []
    for key in dict.fromkeys((r.get("model"), r.get("role")) for r in games):
        rs = [r for r in games if (r.get("model"), r.get("role")) == key]
        done = [r for r in rs if r.get("status") == "done"]
        agg.append(
            {
                "model": key[0],
                "role": key[1],
                "games": len(rs),
                "done": len(done),
                "wins": sum(1 for r in done if r.get("winner") == key[1]),
                **{
                    k: mean_of(done, k)
                    for k in (
                        "attacker_p",
                        "decisiveness",
                        *(f"lost_{s}" for s in sides),
                        "consultations",
                        "orders",
                        "staff_questions",
                        "mean_reply_s",
                        "wall_min",
                        "jev_cost",
                        "player_cost",
                    )
                },
            }
        )
    if agg:
        cols = [
            ("model", "model"),
            ("role", "role"),
            ("games", "games"),
            ("done", "done"),
            ("wins", "won by the model's side"),
            *[(k, h) for k, h in cols_all if k in agg[0] and k not in ("model", "role")],
        ]
        lines += ["", "## Per model and role (means over finished games)", ""]
        lines += table(agg, cols)
    if pairs:
        per = [
            ("consultations", "consultations"),
            ("orders", "orders"),
            ("staff_questions", "staff questions"),
            ("mean_reply_s", "mean reply s"),
            ("harness_errors", "harness errors"),
            ("player_cost", "player $"),
        ]
        cols = [
            *[(f"player_{s}", s.capitalize()) for s in sides],
            ("seed", "seed"),
            *outcome_columns(sides, ordinal),
            *[(f"{k}_{s}", f"{h} ({s[0].upper()})") for k, h in per for s in sides],
            ("wall_min", "game wall min"),
            ("jev_cost", "Jev $"),
            ("status", "status"),
        ]
        lines += ["", f"## Model against model ({sides[0].capitalize()} first)", ""]
        lines += table(pairs, cols)
    if base:
        cols = [
            c
            for c in cols_all
            if c[0]
            not in (
                "model",
                "role",
                "consultations",
                "mean_reply_s",
                "harness_errors",
                "player_cost",
            )
        ]
        lines += ["", "## Baseline: script against script", ""]
        lines += table(base, cols)
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# CLI


def _sigterm(signum, frame):  # a SIGTERM to the grid stops it as Ctrl-C does
    raise KeyboardInterrupt


def _csv(text: str) -> list[str]:
    return [x.strip() for x in text.split(",") if x.strip()]


def _parser() -> argparse.ArgumentParser:
    today = _dt.date.today().isoformat()
    ap = argparse.ArgumentParser(
        prog="kriegsspiel.grid",
        description="Run models x roles x seeds of a scenario, each against the scripted "
        "other side (the default command); `summary OUT` prints a grid's table, `cross OUT "
        "DIR ...` writes one report across grids.",
    )
    ap.add_argument(
        "--scenario",
        default=None,
        help=f"data pack directory (default {DEFAULT_SCENARIO}); passed to every game",
    )
    ap.add_argument(
        "--models",
        default=None,
        help="models that each play the pack's script from every role (default: "
        f"{','.join(DEFAULT_MODELS)}, or none when --pairs or --round-robin is given)",
    )
    ap.add_argument("--roles", default=None, help="sides the models play (default: all)")
    ap.add_argument("--seeds", default=",".join(map(str, DEFAULT_SEEDS)))
    ap.add_argument("--out", default=f"runs/grid-{today}")
    ap.add_argument(
        "--pairs",
        default="",
        help="model-vs-model cells, e.g. opus:sol,fable:astra (a plays the first "
        "side, b the second)",
    )
    ap.add_argument(
        "--round-robin",
        default="",
        help="models that play every other one from both sides, e.g. the matrix's "
        "astra,sol,luna,opus,fable,sonnet,deepseek",
    )
    ap.add_argument(
        "--baseline", action="store_true", help="add one script-vs-script cell per seed"
    )
    ap.add_argument(
        "--parallel",
        default="",
        help="per-harness limits, default claude=2,codex=2,api=4 (script is "
        "unlimited); a model-vs-model game takes a slot per side",
    )
    ap.add_argument(
        "--mode",
        default="record",
        choices=("record", "live", "stub"),
        help="Jev mode passed to the game",
    )
    ap.add_argument("--speed", type=float, default=None, help="passed to every game")
    ap.add_argument("--cadence", type=int, default=None, help="passed to every game")
    ap.add_argument("--end", default=None, help="passed to every game")
    ap.add_argument("--no-memory", action="store_true", help="passed to every game")
    ap.add_argument(
        "--resume",
        action="store_true",
        help="skip cells whose log ends in a verdict; rerun the rest",
    )
    ap.add_argument(
        "--allow-api", action="store_true", help="permit ApiPlayer models (billed per token)"
    )
    ap.add_argument(
        "--cmd",
        default=os.environ.get(CMD_ENV),
        help=f"game command prefix (default: {' '.join(GAME_CMD)}; env {CMD_ENV})",
    )
    ap.add_argument("--dry-run", action="store_true", help="print the cell commands only")
    sub = ap.add_subparsers(dest="command", metavar="{summary,cross}")
    sp = sub.add_parser("summary", help="markdown table of a grid's measured outcomes")
    sp.add_argument("out", help="the grid directory (SUMMARY.md is written there)")
    cp = sub.add_parser("cross", help="one report across several grids (one per battle pack)")
    cp.add_argument("out", help="the report file to write (.md, or .csv with --format csv)")
    cp.add_argument("dirs", nargs="+", help="grid directories, each with its manifest")
    cp.add_argument("--format", default="md", choices=("md", "csv"))
    return ap


def main(argv: list[str] | None = None) -> int:
    a = _parser().parse_args(argv)
    if a.command == "summary":
        return _summary(a)
    if a.command == "cross":
        return _cross(a)
    return _run(a)


def _summary(a: argparse.Namespace) -> int:
    text = summary(Path(a.out))
    (Path(a.out) / "SUMMARY.md").write_text(text)
    print(text, end="")
    return 0


def _cross(a: argparse.Namespace) -> int:
    missing = [d for d in a.dirs if not Path(d).is_dir()]
    if missing:
        raise SystemExit(f"not a directory: {', '.join(missing)}")
    dirs = [Path(d) for d in a.dirs]
    text = cross_csv(dirs) if a.format == "csv" else cross(dirs)
    Path(a.out).write_text(text)
    if a.format == "md":
        print(text, end="")
    print(f"cross report: {a.out}", file=sys.stderr)
    return 0


def _run(a: argparse.Namespace) -> int:
    sides = scenario_sides(a.scenario)
    if a.models is None:
        a.models = "" if a.pairs or a.round_robin else ",".join(DEFAULT_MODELS)
    models, roles = _csv(a.models), _csv(a.roles) if a.roles else list(sides)
    league = _csv(a.round_robin)
    pairs = [(x, y) for x in league for y in league if x != y]
    for p in _csv(a.pairs):
        x, _, y = p.partition(":")
        if not x or not y or "script" in (x, y):
            raise SystemExit(f"--pairs wants model:model, got {p!r}")
        pairs.append((x, y))
    seeds = [int(s) for s in _csv(a.seeds)]
    bad = [r for r in roles if r not in sides]
    if bad:
        raise SystemExit(f"unknown role(s) {bad}; one of {sides}")
    harness = {m: harness_of(m) for m in [*models, *(m for pr in pairs for m in pr)]}
    api = [m for m, h in harness.items() if h == "api"]
    if api and not a.allow_api:
        raise SystemExit(
            f"{', '.join(api)}: API-route players are billed per token; pass --allow-api"
        )
    game_args = ["--mode", a.mode]
    if a.scenario:
        game_args += ["--scenario", a.scenario]
    if a.speed is not None:
        game_args += ["--speed", f"{a.speed:g}"]
    if a.cadence is not None:
        game_args += ["--cadence", str(a.cadence)]
    if a.end is not None:
        game_args += ["--end", a.end]
    if a.no_memory:
        game_args.append("--no-memory")
    cmd = shlex.split(a.cmd) if a.cmd else list(GAME_CMD)
    limits = parse_parallel(a.parallel)
    out = Path(a.out)
    if not out.is_absolute():
        out = REPO_ROOT / out
    cells = make_cells(models, roles, seeds, a.baseline, pairs, sides)
    config = {
        "scenario": a.scenario or DEFAULT_SCENARIO,
        "sides": list(sides),
        "models": models,
        "roles": roles,
        "seeds": seeds,
        "pairs": [f"{x}:{y}" for x, y in pairs],
        "baseline": a.baseline,
        "limits": limits,
        "cmd": cmd,
        "game_args": game_args,
        "engine_commit": None if a.dry_run else engine_commit(),
    }
    grid = Grid(out, cells, cmd=cmd, game_args=game_args, limits=limits, config=config)
    if a.dry_run:
        for c in cells:
            print(f"{c.name} [{c.harness}]: {shlex.join(grid.argv(c))}")
        return 0
    out.mkdir(parents=True, exist_ok=True)
    grid.reconcile(a.resume)
    prev = signal.signal(signal.SIGTERM, _sigterm)
    try:
        rc = grid.run()
    finally:
        signal.signal(signal.SIGTERM, prev)
    text = summary(out)
    (out / "SUMMARY.md").write_text(text)
    print(f"summary: {out / 'SUMMARY.md'}")
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
