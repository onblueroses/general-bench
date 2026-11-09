"""The game command line: script against script, a game with players, or a replay.

    uv run python -m kriegsspiel.run --scenario data/plain-crossroads --mode stub
    uv run python -m kriegsspiel.run --scenario data/plain-crossroads \
        --players red=opus,blue=sol --mode record --log runs/plain-opus-1/run.jsonl
    uv run python -m kriegsspiel.run replay runs/plain-opus-1/run.jsonl

Without `--players` both sides play the pack's script.json. `--mode` is the Jev mode (live,
record, replay from fixtures, stub). `replay LOG` plays a logged game again with no model and
no Jev call (`replay.replay_game`) and exits non-zero unless it is bit-identical.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from .jev import MODES, REPO_ROOT
from .play import CADENCE_MIN, DEFAULT_SEED, play_game, run_script
from .replay import replay_game
from .report import play_report, report
from .scenario import DEFAULT_END, DEFAULT_SCENARIO, resolve


def _players(text: str) -> dict[str, str]:
    out = {}
    for part in text.split(","):
        side, _, spec = part.partition("=")
        if not spec:
            raise SystemExit(f"--players wants side=player pairs, got {part!r}")
        out[side.strip()] = spec.strip()
    return out


def _parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        prog="kriegsspiel.run",
        description="A battle, Jev-driven: script against script (the scenario's script.json), "
        "a game with --players, or `replay LOG`.",
    )
    ap.add_argument(
        "--scenario",
        default=DEFAULT_SCENARIO,
        help=f"data pack directory (default {DEFAULT_SCENARIO})",
    )
    ap.add_argument(
        "--mode",
        default="replay",
        choices=MODES,
        help="Jev mode: live, record (live, kept as fixtures), replay (from the fixtures) or "
        "stub (default replay)",
    )
    ap.add_argument("--seed", type=int, default=DEFAULT_SEED)
    ap.add_argument(
        "--log", default=None, help="run log (default runs/<pack>-script|play/run.jsonl)"
    )
    ap.add_argument(
        "--players",
        default=None,
        help="e.g. red=opus,blue=script (script, null, bot[:strong|weak] or a ROSTER name)",
    )
    ap.add_argument(
        "--speed",
        type=float,
        default=None,
        help="pace the sim at this many sim minutes per wall second while a general thinks "
        "(default: the sim waits for the general)",
    )
    ap.add_argument("--cadence", type=int, default=CADENCE_MIN)
    ap.add_argument(
        "--end",
        default=None,
        help="clock to stop at (default: the scenario's end, else " + DEFAULT_END + ")",
    )
    ap.add_argument(
        "--fixtures",
        default=None,
        help="Jev fixture dir for record/replay (default: beside the log)",
    )
    ap.add_argument(
        "--no-memory",
        action="store_true",
        help="one-shot generals: a fresh process and the full brief each time",
    )
    ap.add_argument(
        "--no-battle-over",
        action="store_true",
        help="never ask the umpire whether the battle is over (play to the end)",
    )
    sub = ap.add_subparsers(dest="command", metavar="{replay}")
    rp = sub.add_parser("replay", help="play a logged game again from its log, no model call")
    rp.add_argument("log", help="the game's run.jsonl")
    return ap


def main(argv: list[str] | None = None) -> None:
    a = _parser().parse_args(argv)
    if a.command == "replay":
        r = replay_game(a.log)
        print(
            f"replay of {a.log}: {'ok' if r.ok else 'FAILED'}, {r.ticks} ticks"
            + (f"; {r.reason} (tick {r.first_mismatch})" if not r.ok else "")
            + (f"; verdict {r.verdict.winner}: {r.verdict.rationale}" if r.verdict else "")
        )
        raise SystemExit(0 if r.ok else 1)
    scen = resolve(a.scenario)
    if a.players is None:
        log = Path(a.log or REPO_ROOT / "runs" / f"{scen.name}-script" / "run.jsonl")
        res = run_script(
            scen, a.mode, log, a.seed, fixture_dir=a.fixtures or log.parent / "jev", end=a.end
        )
        print(report(res))
        return
    log = Path(a.log or REPO_ROOT / "runs" / f"{scen.name}-play" / "run.jsonl")
    res = play_game(
        _players(a.players),
        mode=a.mode,
        seed=a.seed,
        log=log,
        speed=a.speed,
        cadence_min=a.cadence,
        end=a.end,
        fixture_dir=a.fixtures or log.parent / "jev",
        memory=not a.no_memory,
        scenario=scen,
        battle_over=not a.no_battle_over,
    )
    print(play_report(res))


if __name__ == "__main__":
    main()
