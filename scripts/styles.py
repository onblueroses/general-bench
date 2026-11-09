"""How each model commands, measured from the published game records.

    uv run python scripts/styles.py                    # the matrix: games/round-1, round-2
    uv run python scripts/styles.py --quotes 3         # also a few orders per model

Per model, over its games (format: `scripts/slim_games.py`):

- briefs: consultations per game; silent: the share answered with no order at all;
- words: median words in a reply that gives orders; think: median seconds per reply;
- orders: orders per game, as the staff split them out of the replies;
- queried: the share of orders the staff answered with a question;
- the share of the staff's tasks of each kind (attack, advance, hold, support, rally, ...)
  and of each manner (bold, reckless: "at all costs");
- standing: the share of orders with a standing limit ("attacking nothing without a further
  order"); placed: the share that place a body by another ("behind the First brigade");
- length: median minutes until the verdict; broken: median share of its own army routed or
  destroyed at the end.
"""

from __future__ import annotations

import argparse
import random
import re
import statistics
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path

from records import MATRIX, records

KINDS = ("attack", "advance", "hold", "support", "rally", "withdraw")
MANNERS = ("bold", "reckless")  # the other manners are "measured" and "cautious"
PHRASES = {  # wordings counted over the order texts
    "standing": re.compile(r"\b(until|without) (a )?further orders?\b", re.I),
    "placed": re.compile(r"\b(right|left) of\b|\bbehind\b|\bbeside\b", re.I),
}


@dataclass
class Tally:
    """Per model, what its games add up to."""

    games: Counter = field(default_factory=Counter)
    briefs: Counter = field(default_factory=Counter)
    silent: Counter = field(default_factory=Counter)
    words: defaultdict = field(default_factory=lambda: defaultdict(list))
    think: defaultdict = field(default_factory=lambda: defaultdict(list))
    orders: Counter = field(default_factory=Counter)
    queried: Counter = field(default_factory=Counter)
    phrases: defaultdict = field(default_factory=lambda: defaultdict(Counter))
    tasks: defaultdict = field(default_factory=lambda: defaultdict(Counter))
    manner: defaultdict = field(default_factory=lambda: defaultdict(Counter))
    length: defaultdict = field(default_factory=lambda: defaultdict(list))
    broken: defaultdict = field(default_factory=lambda: defaultdict(list))
    said: defaultdict = field(default_factory=lambda: defaultdict(list))


def is_silent(turn: dict) -> bool:
    return not [o for o in turn.get("orders") or [] if o.strip()]


def collect(dirs: list[Path]) -> Tally:
    t = Tally()
    for _, g in records(dirs):
        players, verdict = g["game"]["players"], g["verdict"]
        for side, model in players.items():
            t.games[model] += 1
            t.length[model].append(verdict["minute"])
            t.broken[model].append(verdict["margin"][side]["broken_share"])
        for turn in g["turns"]:
            m = players[turn["side"]]
            t.briefs[m] += 1
            if is_silent(turn):
                t.silent[m] += 1
                continue
            t.words[m].append(len((turn.get("reply") or "").split()))
            if turn.get("wall_s") is not None:
                t.think[m].append(turn["wall_s"])
            t.said[m].extend(o.strip() for o in turn["orders"] if o.strip())
        for o in g["staff"]:
            m = players[o["side"]]
            t.orders[m] += 1
            t.queried[m] += bool(o.get("clarifications"))
            for k, rx in PHRASES.items():
                t.phrases[m][k] += bool(rx.search(o.get("text") or ""))
            for task in o.get("tasks") or []:
                t.tasks[m][task["kind"]] += 1
                t.manner[m][task.get("manner")] += 1
    return t


def print_styles(t: Tally, quotes: int = 0) -> None:
    order = sorted(t.games, key=lambda m: -t.orders[m] / t.games[m])
    print(f"{sum(t.games.values()) // 2} games\n")
    head = [
        "model",
        "briefs",
        "silent",
        "words",
        "think s",
        "orders",
        "queried",
        *KINDS,
        *MANNERS,
        *PHRASES,
        "length min",
        "broken",
    ]
    print("| " + " | ".join(head) + " |\n|" + "---|" * len(head))
    for m in order:
        n, nt = t.games[m], sum(t.tasks[m].values())
        row = [
            m,
            f"{t.briefs[m] / n:.0f}",
            f"{t.silent[m] / t.briefs[m]:.0%}",
            f"{statistics.median(t.words[m]):.0f}",
            f"{statistics.median(t.think[m]):.0f}",
            f"{t.orders[m] / n:.0f}",
            f"{t.queried[m] / t.orders[m]:.0%}",
            *(f"{t.tasks[m][k] / nt:.0%}" for k in KINDS),
            *(f"{t.manner[m][k] / nt:.0%}" for k in MANNERS),
            *(f"{t.phrases[m][k] / t.orders[m]:.0%}" for k in PHRASES),
            f"{statistics.median(t.length[m]):.0f}",
            f"{statistics.median(t.broken[m]):.0%}",
        ]
        print("| " + " | ".join(row) + " |")
    if quotes:
        rng = random.Random(1)
        for m in order:
            print(f"\n{m}:")
            for q in rng.sample(t.said[m], min(quotes, len(t.said[m]))):
                print(f"  > {q}")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("dirs", nargs="*", type=Path, default=MATRIX)
    ap.add_argument("--quotes", type=int, default=0, help="orders to sample per model")
    a = ap.parse_args(argv)
    print_styles(collect(a.dirs), a.quotes)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
