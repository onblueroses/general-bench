"""Checks on the published games: how battles end, the seat advantage, the noise floor and the
replays.

    uv run python scripts/checks.py

- verdicts: how the matrix games were decided (break, possession, play-on, draw) and when;
- seats: the first side's share on each battle (the first side in `game.sides`: red on Plain
  and Mirror, the horse army on Arms);
- noise floor: `games/extra/noise-a` and `noise-b` replay the same Plain pairings under the same
  settings; how often the same pairing has the same winner, and how far a model's share moves;
- replays: `games/extra/codex-replays/*` replay the pairings among Astra, Sol and Luna under
  today's code (`now`, seeds 1 and 2; `seeds-3-4`), the round-1 code (`old-code`) and the
  round-1 code with the round-1 Codex CLI (`old-cli`), beside the matrix's own rounds;
- DeepSeek rerun: `games/extra/deepseek-rerun` replays DeepSeek's round-1 games after a staff fix.
"""

from __future__ import annotations

import statistics
from collections import Counter

from records import GAMES, MATRIX, PACKS, pct, records
from standings import load, shares

TRIO = {"astra", "sol", "luna"}


def verdicts() -> None:
    how, minute = Counter(), []
    for _, record in records(MATRIX):
        v = record["verdict"]
        how[v["how"]] += 1
        minute.append(v["minute"])
    n = sum(how.values())
    print(f"## Verdicts ({n} games)\n")
    for k, c in how.most_common():
        print(f"- {k}: {c} ({pct(c / n)})")
    q = statistics.quantiles(minute, n=4)
    print(
        f"- minutes to the verdict: median {statistics.median(minute):.0f}, "
        f"quartiles {q[0]:.0f} and {q[2]:.0f}\n"
    )


def seats(games: list[dict]) -> None:
    print("## First side's share\n")
    print("| battle | games | first side | share |\n|---|---|---|---|")
    for pack, name in PACKS.items():
        gs = [g for g in games if g["pack"] == pack]
        first = gs[0]["sides"][0]
        score = sum(
            1.0 if g["winner"] == first else 0.5 if g["winner"] == "draw" else 0.0 for g in gs
        )
        print(f"| {name} | {len(gs)} | {first} | {pct(score / len(gs))} |")
    print()


def noise_floor() -> None:
    a = {
        (g["pack"], tuple(sorted(g["players"].items()))): g["winner"]
        for g in load([GAMES / "extra" / "noise-a"])
    }
    b = {
        (g["pack"], tuple(sorted(g["players"].items()))): g["winner"]
        for g in load([GAMES / "extra" / "noise-b"])
    }
    both = sorted(a.keys() & b.keys())
    same = sum(a[k] == b[k] for k in both)
    sa, sb = (shares(load([GAMES / "extra" / x])) for x in ("noise-a", "noise-b"))
    moves = [abs(sa[m] - sb[m]) for m in sa.keys() & sb.keys()]
    print("## Noise floor (Plain, the same pairings played twice)\n")
    print(f"- same winner in {same} of {len(both)} pairings ({pct(same / len(both))})")
    print(
        f"- a model's share moves by {100 * statistics.mean(moves):.0f} points on average "
        f"between the two runs (largest {100 * max(moves):.0f})"
    )
    print(
        "- shares: "
        + ", ".join(
            f"{m} {pct(sa[m])} / {pct(sb[m])}" for m in sorted(sa, key=lambda m: -sa[m] - sb[m])
        )
        + "\n"
    )


def replays(matrix: list[dict]) -> None:
    def trio(gs: list[dict]) -> list[dict]:
        return [g for g in gs if set(g["players"].values()) <= TRIO]

    sets = {
        "round 1 (matrix)": trio([g for g in matrix if g["set"] == "round-1"]),
        "round 2 (matrix)": trio([g for g in matrix if g["set"] == "round-2"]),
    }
    for arm in ("now", "seeds-3-4", "old-code", "old-cli"):
        sets[f"replay: {arm}"] = load([GAMES / "extra" / "codex-replays" / arm])
    print("## Replays among Astra, Sol and Luna\n")
    print("| set | games | astra | sol | luna |\n|---|---|---|---|---|")
    for name, gs in sets.items():
        s = shares(gs)
        print(
            f"| {name} | {len(gs)} | "
            + " | ".join(pct(s[m]) for m in ("astra", "sol", "luna"))
            + " |"
        )
    print()


def deepseek_rerun(matrix: list[dict]) -> None:
    before = shares([g for g in matrix if g["set"] == "round-1"])["deepseek"]
    after = shares(load([GAMES / "extra" / "deepseek-rerun"]))["deepseek"]
    print("## DeepSeek rerun\n")
    print(f"- DeepSeek's round-1 share {pct(before)}; replayed after the staff fix {pct(after)}\n")


def main() -> int:
    matrix = load(MATRIX)
    verdicts()
    seats(matrix)
    noise_floor()
    replays(matrix)
    deepseek_rerun(matrix)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
