"""Slim game records for publication: one gzipped JSON per game from a grid's `run.jsonl` files.

    uv run python scripts/slim_games.py --out games/my-set runs/my-grid-*

A record keeps what a reader needs to follow a game and re-score it:

- `game`: pack, seed, the model on each side, the staff model, the clock start;
- `personas`: each side's system prompt, once (the same bytes at every consultation);
- `turns`: every consultation of a general in order: side, model, trigger (cadence or
  clarification), the minute it was asked and the minute the reply arrived, the brief, the
  reply, the orders split from it, wall seconds and token counts;
- `staff`: every order as the staff read it, minute by minute: the tasks it set (kind, manner,
  objective, on-contact, start and stop conditions) and the clarifications it sent back;
- `umpire`: every melee the umpire weighed, with the account it read and the factor it gave;
- `verdict`: the mechanical verdict record as the engine wrote it.

Dropped: the engine's per-minute event and unit-state hashes and the raw decisions-model
traffic (about three quarters of the bytes). A bit-exact replay (`kriegsspiel.run replay LOG`)
needs the full run log.
"""

from __future__ import annotations

import argparse
import gzip
import json
from pathlib import Path

META_KEEP = (
    "input_tokens",
    "output_tokens",
    "reasoning_tokens",
    "cache_read",
    "cache_create",
    "turn",
    "attempts",
    "model",
    "harness",
)


def slim(run: Path) -> dict | None:
    header, verdict, personas, turns, staff, umpire = None, None, {}, [], [], []
    for line in run.open(encoding="utf-8", errors="replace"):
        try:
            r = json.loads(line)
        except json.JSONDecodeError:
            continue
        t = r.get("type")
        if t == "header":
            header = r
        elif t == "verdict":
            verdict = r.get("verdict")
        elif t == "commander":
            side = r.get("side")
            if side and r.get("system") and side not in personas:
                personas[side] = r["system"]
            meta = r.get("meta") or {}
            turns.append(
                {
                    "side": side,
                    "model": r.get("player") or r.get("model"),
                    "trigger": r.get("trigger"),
                    "asked": r.get("consulted_clock"),
                    "arrived": r.get("arrived_clock"),
                    "brief": r.get("brief"),
                    "reply": r.get("reply"),
                    "orders": r.get("orders"),
                    "wall_s": r.get("wall_s"),
                    "meta": {k: meta[k] for k in META_KEEP if meta.get(k) is not None},
                }
            )
        elif t == "tick":
            tick = r.get("tick")
            staff.extend({"tick": tick, **o} for o in r.get("orders") or [])
            umpire.extend(
                {"tick": tick, "context": u.get("context"), "factor": u.get("factor")}
                for u in r.get("umpire") or []
                if u.get("call") == "situation_modifier"
            )
    if header is None or verdict is None:
        return None
    play = header.get("play") or {}
    return {
        "game": {
            "run": run.parent.name,
            "pack": Path(header.get("scenario", "")).name,
            "seed": header.get("seed"),
            "players": play.get("players"),
            "sides": play.get("sides"),
            "staff_model": header.get("jev_model"),
            "clock_start": header.get("clock_start"),
            "end": play.get("end"),
            "cadence_min": play.get("cadence_min"),
        },
        "personas": personas,
        "turns": turns,
        "staff": staff,
        "umpire": umpire,
        "verdict": verdict,
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("dirs", nargs="+", type=Path)
    a = ap.parse_args(argv)
    n = skipped = 0
    for d in a.dirs:
        for run in sorted(d.glob("*-vs-*/run.jsonl")):
            rec = slim(run)
            if rec is None:
                skipped += 1
                continue
            pack = rec["game"]["pack"] or d.name
            out = a.out / pack / f"{run.parent.name}.json.gz"
            out.parent.mkdir(parents=True, exist_ok=True)
            with gzip.open(out, "wt", encoding="utf-8") as fh:
                json.dump(rec, fh, ensure_ascii=False, separators=(",", ":"))
            n += 1
    print(f"{n} games written to {a.out}, {skipped} without a verdict skipped")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
