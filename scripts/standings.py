"""Standings from the published game records.

    uv run python scripts/standings.py                      # the matrix: games/round-1, round-2
    uv run python scripts/standings.py games/extra/noise-a  # any set of records
    uv run python scripts/standings.py --json out.json      # the numbers, for figures

Reads `<dir>/<pack>/<game>.json.gz` (format: `scripts/slim_games.py`). A draw counts half.
A draw with both armies over the break share is re-ruled by the tie-break the packs carry now
(`break_tie_margin` in `data/<pack>/mission.json`): the less broken army wins unless the two
are within the margin. The first games were played before that rule existed.

Prints, per model: games, wins-draws-losses, share with a 95% interval, a Bradley-Terry
rating on the Elo scale with a 95% interval, the narrowest range of ranks that holds in 90% of
resamples, and the share on each battle. Then the head-to-head shares, how often each pair of
neighbours in the order swaps under resampling, and the share in each round. Intervals come
from resampling whole games with replacement.
"""

from __future__ import annotations

import argparse
import itertools
import json
import math
import random
from collections import Counter, defaultdict
from pathlib import Path

from records import MATRIX, PACKS, ROOT, pct, records

SCORE = {"W": 1.0, "D": 0.5, "L": 0.0}
ELO = 400 / math.log(10)  # Elo points per unit of log-strength


def tie_margin(pack: str) -> float | None:
    f = ROOT / "data" / pack / "mission.json"
    return json.loads(f.read_text()).get("break_tie_margin") if f.exists() else None


def winner(verdict: dict, sides: list[str], margin: float | None) -> str:
    """The recorded winner, or for a both-broken draw the less broken side when the two are
    further apart than the pack's tie margin."""
    if margin is None or (verdict["winner"], verdict.get("how")) != ("draw", "break"):
        return verdict["winner"]
    broken = {s: verdict["margin"][s]["broken_share"] for s in sides}
    least = min(sides, key=broken.__getitem__)
    return least if max(broken.values()) - broken[least] > margin + 1e-9 else "draw"


def load(dirs: list[Path]) -> list[dict]:
    """One row per game: set (the directory name), pack, seed, players by side, the sides in
    the pack's order, the winner side or "draw"."""
    margins: dict[str, float | None] = {}
    games = []
    for d, record in records(dirs):
        game, verdict = record["game"], record["verdict"]
        pack = game["pack"]
        if pack not in margins:
            margins[pack] = tie_margin(pack)
        games.append(
            {
                "set": d.name,
                "pack": pack,
                "seed": game["seed"],
                "players": game["players"],
                "sides": game["sides"],
                "winner": winner(verdict, game["sides"], margins[pack]),
            }
        )
    return games


def results(games: list[dict]):
    """(game, model, opponent, W|D|L) for each seat of each game."""
    for g in games:
        (sa, ma), (sb, mb) = g["players"].items()
        for side, model, other in ((sa, ma, mb), (sb, mb, ma)):
            yield (
                g,
                model,
                other,
                ("D" if g["winner"] == "draw" else "W" if g["winner"] == side else "L"),
            )


def shares(games: list[dict]) -> dict[str, float]:
    s: dict[str, list[float]] = defaultdict(lambda: [0.0, 0])
    for _, m, _, r in results(games):
        s[m][0] += SCORE[r]
        s[m][1] += 1
    return {m: a / n for m, (a, n) in s.items()}


def ratings(games: list[dict], tol: float = 1e-10) -> dict[str, float]:
    """Bradley-Terry strengths by the MM algorithm (a draw is half a win each way, no seat
    advantage), as Elo-scale ratings centred on 1500."""
    wins: dict[str, float] = defaultdict(float)
    met: Counter = Counter()
    for _, m, o, r in results(games):
        wins[m] += SCORE[r]
        met[(m, o)] += 1
    models = sorted(wins)
    p = dict.fromkeys(models, 1.0)
    for _ in range(10_000):
        q = {}
        for i in models:
            denom = sum(n / (p[i] + p[j]) for (a, j), n in met.items() if a == i)
            q[i] = max(wins[i], 1e-9) / denom
        mean = math.exp(sum(math.log(v) for v in q.values()) / len(q))
        q = {m: v / mean for m, v in q.items()}
        done = max(abs(q[m] - p[m]) for m in models) < tol
        p = q
        if done:
            break
    return {m: 1500 + ELO * math.log(v) for m, v in p.items()}


def rank_range(counts: Counter, n: int, mass: float = 0.9) -> tuple[int, int]:
    """The narrowest run of ranks holding at least `mass` of the resamples."""
    ranks = sorted(counts)
    best = (ranks[0], ranks[-1])
    for i, lo in enumerate(ranks):
        total = 0
        for hi in ranks[i:]:
            total += counts[hi]
            if total >= mass * n:
                if hi - lo < best[1] - best[0]:
                    best = (lo, hi)
                break
    return best


def ci(v: list[float]) -> tuple[float, float]:
    """The central 95% of resampled values."""
    v = sorted(v)
    return v[int(0.025 * (len(v) - 1))], v[int(0.975 * (len(v) - 1))]


def standings(games: list[dict], resamples: int = 2000, seed: int = 1) -> dict:
    """Everything the report prints: the table in rating order, head to head, how often
    neighbours swap under resampling, and the share in each set."""
    share, rating = shares(games), ratings(games)
    order = sorted(share, key=lambda m: -rating[m])
    wdl: dict[str, Counter] = defaultdict(Counter)
    h2h: dict[tuple[str, str], list[float]] = defaultdict(lambda: [0.0, 0])
    for _, m, o, r in results(games):
        wdl[m][r] += 1
        h2h[(m, o)][0] += SCORE[r]
        h2h[(m, o)][1] += 1
    packs = [p for p in PACKS if any(g["pack"] == p for g in games)]
    by_pack = {p: shares([g for g in games if g["pack"] == p]) for p in packs}
    sets = sorted({g["set"] for g in games})
    by_set = {s: shares([g for g in games if g["set"] == s]) for s in sets}

    rng = random.Random(seed)
    boot_share, boot_rating = defaultdict(list), defaultdict(list)
    ranks: dict[str, Counter] = defaultdict(Counter)
    for _ in range(resamples):
        sample = [rng.choice(games) for _ in games]
        s, r = shares(sample), ratings(sample)
        for m in order:
            boot_share[m].append(s[m])
            boot_rating[m].append(r[m])
        for i, m in enumerate(sorted(order, key=lambda m: -r[m]), 1):
            ranks[m][i] += 1

    table = [
        {
            "model": m,
            "games": sum(wdl[m].values()),
            "W": wdl[m]["W"],
            "D": wdl[m]["D"],
            "L": wdl[m]["L"],
            "share": share[m],
            "share_ci": list(ci(boot_share[m])),
            "rating": rating[m],
            "rating_ci": list(ci(boot_rating[m])),
            "rank_range": list(rank_range(ranks[m], resamples)),
            "packs": {PACKS[p]: by_pack[p].get(m) for p in packs},
            "sets": {s: by_set[s].get(m) for s in sets},
        }
        for m in order
    ]
    swaps = [
        (x, y, sum(boot_rating[y][i] > boot_rating[x][i] for i in range(resamples)) / resamples)
        for x, y in itertools.pairwise(order)
    ]
    return {
        "games": len(games),
        "order": order,
        "packs": [PACKS[p] for p in packs],
        "sets": sets,
        "table": table,
        "h2h": {f"{m}|{o}": [v[0] / v[1], v[1]] for (m, o), v in h2h.items()},
        "swaps": swaps,
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("dirs", nargs="*", type=Path, default=MATRIX)
    ap.add_argument("--resamples", type=int, default=2000)
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--json", type=Path, help="also write the numbers here")
    a = ap.parse_args(argv)
    st = standings(load(a.dirs), a.resamples, a.seed)
    order = st["order"]

    names = ", ".join(
        str(d.resolve().relative_to(ROOT)) if d.resolve().is_relative_to(ROOT) else str(d)
        for d in a.dirs
    )
    print(f"{st['games']} games from {names}\n")
    print(
        "| rank | model | games | W-D-L | share | 95% interval | rating | 95% interval | "
        "likely rank | " + " | ".join(st["packs"]) + " |"
    )
    print("|---|---|---|---|---|---|---|---|---|" + "---|" * len(st["packs"]))
    for i, row in enumerate(st["table"], 1):
        (slo, shi), (rlo, rhi), (lo, hi) = row["share_ci"], row["rating_ci"], row["rank_range"]
        print(
            f"| {i} | {row['model']} | {row['games']} | {row['W']}-{row['D']}-{row['L']} | "
            f"{pct(row['share'])} | {pct(slo)} to {pct(shi)} | {row['rating']:.0f} | "
            f"{rlo:.0f} to {rhi:.0f} | {lo if lo == hi else f'{lo} to {hi}'} | "
            + " | ".join(pct(row["packs"][p] or 0) for p in st["packs"])
            + " |"
        )

    print("\nHead to head: the row model's share against the column model (games)\n")
    print("| | " + " | ".join(order) + " |\n|---|" + "---|" * len(order))
    for m in order:
        cells = []
        for o in order:
            v = st["h2h"].get(f"{m}|{o}")
            cells.append("·" if m == o else f"{pct(v[0])} ({v[1]})" if v else "")
        print(f"| {m} | " + " | ".join(cells) + " |")

    print("\nNeighbours swapped under resampling (by rating):")
    for x, y, p in st["swaps"]:
        print(f"- {y} above {x}: {pct(p)}")

    if len(st["sets"]) > 1:
        print("\nShare by set:\n")
        print("| model | " + " | ".join(st["sets"]) + " |\n|---|" + "---|" * len(st["sets"]))
        for row in st["table"]:
            print(
                f"| {row['model']} | "
                + " | ".join(pct(row["sets"][s] or 0) for s in st["sets"])
                + " |"
            )

    if a.json:
        a.json.write_text(json.dumps(st, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
