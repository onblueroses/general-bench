"""How each general commands: every number in `docs/generals.md`, from the published records.

    uv run python scripts/generals.py                  # the matrix: games/round-1, round-2
    uv run python scripts/generals.py --quotes         # also check and print the cited orders

Per model, over its seats (one side of one game; format: `scripts/slim_games.py`). "The others"
are the seats of the other six models pooled. A share is pooled over seats (the sum of the
counts over the sum of the bases), never a mean of per-game shares. After the shared table, one
section per model: its measures against the other six, their intervals, and the game the doc
tells. `--quotes` checks every quoted order against its record and exits 1 if one is missing.

Breaks and rallies, from the reports in the general's own briefs:

- break: a report line ("- [Report, received ...]") saying one of the side's own bodies "has
  broken", counted once per body and minute written; its brigade is the body's parent in
  `data/<pack>/oob.json`, and the report's minute is when it reached headquarters;
- breaks: breaks per game;
- rally 15, rally 30: the share of breaks whose brigade is given a rally task (a task of kind
  rally, or one whose `then` is a rally) within 15 or 30 minutes of the report;
- hard answer: of breaks whose brigade gets any order within 30 minutes, the share whose first
  such order is a hold, an attack or a charge;
- recovered: 1 minus the men of the bodies broken at the verdict over the men of every body
  that broke at some time in the game (each body counted once);
- broken at end: the median share of the army routed or destroyed at the verdict.

Orders, as the staff read them (`staff`), one per order line:

- by 09:05: the share of all the side's orders written in the first five minutes;
- stands: the median minutes from an order to a formation until the next order to the same
  formation, or the verdict for its last; an order counts once per formation it addresses,
  orders to the whole army and headquarters moves left out;
- repeats: the share of those orders, after a formation's first, that set the same kind of task
  on the same objective as the order before it;
- standing, placed: as in `scripts/styles.py` ("without further orders"; "behind", "beside",
  "right of"), the share of orders;
- quarter: the share of orders that hand a brigade a side, edge, part, half, quarter, end or
  houses of the village ("the eastern houses of Teasel Village");
- at all costs: the share of orders with the phrase; held: the share of those in which it
  follows "hold" within the clause; garrison: brigades per game given an order with the phrase
  at 09:00;
- opening attack: the share of games with an attack task written by 09:05, and the brigades
  given one;
- measured: the share of orders naming a point by a distance and a point of the compass ("a
  point 400 metres east of", "eight hundred metres west of"), by set of games.

Consultations (`turns`):

- silent when hurt: of the briefs carrying a report of one of its own bodies broken, the share
  answered with no order;
- off the field: games with one reply sending three or more orders to withdraw, retire, retreat
  or fall back to an exit.

Results: score is 1 for a win, 0.5 for a draw, 0 for a loss, with the tie-break of
`scripts/standings.py`; lost by 11:30 is the share of games lost with the verdict before 11:30.

Intervals: 2,000 resamples of the games with replacement (seed 1); a resampled game brings both
its seats, so a model's seat and its opponent's move together. Each interval is the 2.5th to
97.5th percentile of the difference named beside it.
"""

from __future__ import annotations

import argparse
import gzip
import json
import math
import random
import re
import statistics
from collections import Counter, defaultdict
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from functools import cache
from pathlib import Path
from typing import NamedTuple

from records import MATRIX, PACKS, ROOT, records
from standings import tie_margin, winner
from styles import PHRASES

MODELS = ("astra", "fable", "sol", "opus", "luna", "deepseek", "sonnet")  # standings order
SCORE = {"win": 1.0, "draw": 0.5, "loss": 0.0}

REPORT = re.compile(r"- \[Report, received (\d\d:\d\d)\] (\d\d:\d\d), ")
BROKE = re.compile(r"([A-Z][a-z]+ [A-Za-z ]+? \d\d) has broken")
AT_ALL_COSTS = re.compile(r"at all costs", re.I)
HOLD_AT_ALL_COSTS = re.compile(r"\bhold\b[^,;.]*at all costs", re.I)
EXIT = re.compile(r"\bexit\b", re.I)
RETIRE = re.compile(r"withdraw|retire|retreat|fall back", re.I)
_DIR = r"(?:north|south|east|west)"
QUARTER = re.compile(
    rf"\b{_DIR}(?:-?(?:east|west))?(?:ern)?\s+(?:side|edge|part|half|quarter|end|outskirts|houses)"
    r"\s+of\s+(?:the\s+)?(?:village|\w+ village)",
    re.I,
)
_NUMBER_WORD = (
    r"(?:one|two|three|four|five|six|seven|eight|nine|ten|twelve|fifteen|twenty|thirty|fifty"
    r"|hundred|thousand|half|quarter|a)"
)
_NUMBER = rf"(?:\d[\d,.]*|{_NUMBER_WORD}(?:[\s-]+(?:and[\s-]+)?{_NUMBER_WORD})*)"
MEASURED = re.compile(
    rf"\b{_NUMBER}\s*(?:m|metres|meters|km|kilometres?|yards|paces|miles?)\b"
    rf"(?:\s+\w+){{0,3}}?\s+(?:to the\s+)?{_DIR}",
    re.I,
)


class Quote(NamedTuple):
    """An order docs/generals.md or the README quotes: the model, its game (`<set>/<pack>/<run>`
    under `games/`), the clock its reply arrived (None: cited without one), the order."""

    model: str
    game: str
    at: str | None
    text: str


QUOTES = (
    Quote(
        "astra",
        "round-2/plain-crossroads/astra-vs-deepseek-s3",
        "10:15",
        "Pellow, withdraw to 1500 m west of Teasel Village, then rally the Fourth brigade there.",
    ),
    Quote(
        "astra",
        "round-2/plain-crossroads/astra-vs-deepseek-s3",
        "10:43",
        "Brandreth, rally the First brigade at 1500 m west of Teasel Village.",
    ),
    Quote(
        "fable",
        "round-1/arms-medlar/sol-vs-fable-s2",
        "09:50",
        "Sixth brigade: advance to Bullace Farm and hold there in column behind the First "
        "brigade, attacking nothing without further orders.",
    ),
    Quote(
        "fable",
        "round-2/arms-medlar/fable-vs-opus-s3",
        "09:00",
        "Fourth brigade, follow the Grenadier brigade by the Post road to a point 500 m westward "
        "of Medlar Village and halt there in column as the reserve, attacking nothing without a "
        "further order.",
    ),
    Quote(
        "sol",
        "round-1/plain-crossroads/sol-vs-fable-s2",
        "09:00",
        "Fourth brigade, follow Second brigade and support it at Teasel Village.",
    ),
    Quote(
        "sol",
        "round-2/mirror-fords/luna-vs-sol-s4",
        "09:00",
        "Royle attack Plover Village boldly, then hold Plover Village.",
    ),
    Quote(
        "opus",
        "round-1/plain-crossroads/astra-vs-opus-s1",
        "09:00",
        "Second brigade will march at once in column by the High road, with all speed, to "
        "Teasel Village, occupy it and hold it at all costs.",
    ),
    Quote(
        "opus",
        "round-1/plain-crossroads/astra-vs-opus-s1",
        "10:25",
        "Grenadier brigade will hold Teasel Village at all costs and report to me how it stands.",
    ),
    Quote(
        "luna",
        "round-2/plain-crossroads/deepseek-vs-luna-s4",
        "09:00",
        "Sixth brigade advance in column to Teasel Village, deploy and attack any enemy there "
        "boldly.",
    ),
    Quote(
        "luna",
        "round-2/plain-crossroads/deepseek-vs-luna-s4",
        "10:30",
        "First brigade rally, then withdraw to East exit.",
    ),
    Quote(
        "deepseek",
        "round-2/plain-crossroads/astra-vs-deepseek-s3",
        "10:40",
        "Fifth brigade: hold the eastern houses of Teasel Village and do not quit the village.",
    ),
    Quote(
        "deepseek",
        "round-2/mirror-fords/deepseek-vs-opus-s4",
        None,
        "Fourth brigade (Bunce): hold the north side of Plover Village at all costs.",
    ),
    Quote(
        "sonnet",
        "round-1/mirror-fords/sonnet-vs-fable-s2",
        "10:55",
        "Mawhood, the Second brigade will fall back to Heron Ridge in good order and form in "
        "line on the right of the Third brigade.",
    ),
    Quote(
        "sonnet",
        "round-1/mirror-fords/sonnet-vs-fable-s2",
        "13:55",
        "Treloar, the Third brigade will attack Plover Village.",
    ),
)
STORIES = {  # one game per model, told in a paragraph of docs/generals.md
    "astra": "round-2/plain-crossroads/astra-vs-deepseek-s3",
    "fable": "round-2/arms-medlar/fable-vs-opus-s3",
    "sol": "round-1/plain-crossroads/sol-vs-fable-s2",
    "opus": "round-1/plain-crossroads/astra-vs-opus-s1",
    "luna": "round-2/plain-crossroads/deepseek-vs-luna-s4",
    "deepseek": "round-2/mirror-fords/deepseek-vs-opus-s4",
    "sonnet": "round-1/mirror-fords/sonnet-vs-fable-s2",
}


def load(game: str) -> dict:
    with gzip.open(ROOT / "games" / f"{game}.json.gz", "rt", encoding="utf-8") as fh:
        return json.load(fh)


@dataclass
class Army:
    units: dict  # by name: side, brigade ("parent"), men
    men: Counter  # by side
    tie_margin: float | None


@dataclass
class Break:
    unit: str
    brigade: str
    men: int
    received: int


@dataclass
class Seat:
    """One side of one game: who played it, how it ended, and its counts.

    A measure is a ratio: `num[key] / den[key]`, summed over the seats it is taken over."""

    model: str
    game: str  # <set>/<pack>/<run>
    pack: str
    set: str
    side: str
    score: float
    minute: int
    broken: float
    num: Counter = field(default_factory=Counter)
    den: Counter = field(default_factory=Counter)
    stands: list[float] = field(default_factory=list)

    def add(self, key: str, num: float, den: float = 1) -> None:
        self.num[key] += num
        self.den[key] += den


def minute(clock: str, start: str) -> int:
    (h, m), (h0, m0) = (map(int, c.split(":")) for c in (clock, start))
    return (h - h0) * 60 + m - m0


def clock(minutes: float, start: str = "09:00") -> str:
    h0, m0 = map(int, start.split(":"))
    t = h0 * 60 + m0 + int(minutes)
    return f"{t // 60:02d}:{t % 60:02d}"


@cache
def army(pack: str) -> Army:
    oob = json.loads((ROOT / "data" / pack / "oob.json").read_text())
    men = Counter()
    for u in oob["units"]:
        men[u["side"]] += u["men"]
    return Army({u["name"]: u for u in oob["units"]}, men, tie_margin(pack))


# ---------------------------------------------------------------- reading one seat


def broken_reports(brief: str) -> Iterator[tuple[str, str, str]]:
    """(clock received, clock written, body) for each "has broken" in the brief's reports."""
    for row in brief.splitlines():
        if "has broken" in row and (rep := REPORT.match(row)):
            for name in BROKE.findall(row):
                yield rep.group(1), rep.group(2), name


def own_breaks(record: dict, side: str, units: dict) -> list[Break]:
    start, seen, out = record["game"]["clock_start"], set(), []
    for turn in record["turns"]:
        if turn["side"] != side:
            continue
        for received, written, name in broken_reports(turn.get("brief") or ""):
            u = units.get(name)
            if u is None or u["side"] != side or (name, written) in seen:
                continue
            seen.add((name, written))
            out.append(Break(name, u["parent"], u["men"], minute(received, start)))
    return out


def tasks_by_formation(record: dict, side: str) -> dict[str, list[tuple[float, dict]]]:
    """Per brigade, its orders in issue order: (minute, the order's first task for it)."""
    out = defaultdict(list)
    for o in record["staff"]:
        if o["side"] != side:
            continue
        seen = set()
        for t in o.get("tasks") or []:
            f = t["formation"]
            if "-" not in f or f in seen or t["kind"] == "move_hq":
                continue
            seen.add(f)
            out[f].append((o["at"], t))
    return out


def is_rally(task: dict) -> bool:
    return task["kind"] == "rally" or (task.get("then") or {}).get("kind") == "rally"


def objective(task: dict) -> str | None:
    return (task.get("objective") or {}).get("name")


def count_breaks(seat: Seat, breaks: list[Break], tasks: dict, end_men: float) -> None:
    seat.add("breaks", len(breaks))
    for b in breaks:
        after = [(at - b.received, t) for at, t in tasks.get(b.brigade, []) if at >= b.received]
        rally = [d for d, t in after if is_rally(t)]
        seat.add("rally 15", any(d <= 15 for d in rally))
        seat.add("rally 30", any(d <= 30 for d in rally))
        answer = next((t for d, t in after if d <= 30), None)
        if answer is not None:
            seat.add("hard answer", answer["kind"] in ("hold", "attack", "charge"))
    ever = sum({b.unit: b.men for b in breaks}.values())
    seat.add("recovered", ever - end_men, ever)


def count_tasks(seat: Seat, tasks: dict) -> None:
    for seq in tasks.values():
        for i, (at, t) in enumerate(seq):
            nxt = seq[i + 1][0] if i + 1 < len(seq) else seat.minute
            seat.stands.append(max(0.0, nxt - at))
            if i:
                prev = seq[i - 1][1]
                same = (prev["kind"], objective(prev)) == (t["kind"], objective(t))
                seat.add("repeats", same)


def count_orders(seat: Seat, orders: list[dict]) -> None:
    garrison, opening_attack = set(), set()
    for o in orders:
        text = o.get("text") or ""
        early = o["at"] <= 5
        seat.add("by 09:05", early)
        for key, rx in PHRASES.items():
            seat.add(key, bool(rx.search(text)))
        seat.add("quarter", bool(QUARTER.search(text)))
        seat.add(f"measured {seat.set}", bool(MEASURED.search(text)))
        costly = bool(AT_ALL_COSTS.search(text))
        seat.add("at all costs", costly)
        if costly:
            seat.add("held", bool(HOLD_AT_ALL_COSTS.search(text)))
        for t in o.get("tasks") or []:
            if costly and o["at"] == 0:
                garrison.add(t["formation"])
            if early and t["kind"] == "attack":
                opening_attack.add(t["formation"])
    seat.add("garrison", len(garrison))
    seat.add("opening attack", bool(opening_attack))
    seat.add("attackers at 09:00", len(opening_attack))
    key = "after an opening attack" if opening_attack else "after a quiet opening"
    seat.add(key, seat.score)


def orders_of(turn: dict) -> list[str]:
    return [o.strip() for o in turn.get("orders") or [] if o.strip()]


def is_hurt(turn: dict, side: str, units: dict) -> bool:
    """Does the brief report one of the side's own bodies broken?"""
    return any(
        units.get(name, {}).get("side") == side
        for _, _, name in broken_reports(turn.get("brief") or "")
    )


def count_turns(seat: Seat, turns: list[dict], units: dict) -> None:
    off_field = False
    for turn in turns:
        orders = orders_of(turn)
        if is_hurt(turn, seat.side, units):
            seat.add("silent when hurt", not orders)
        off_field |= sum(bool(EXIT.search(o) and RETIRE.search(o)) for o in orders) >= 3
    seat.add("off the field", off_field)


def count_result(seat: Seat) -> None:
    battle = PACKS[seat.pack]
    seat.add("score", seat.score)
    seat.add(f"score {battle}", seat.score)
    if battle == "Arms":
        seat.add(f"score Arms {seat.side}", seat.score)
    else:
        seat.add("score Plain+Mirror", seat.score)
    seat.add("lost by 11:30", seat.score == 0 and seat.minute < 150)


Games = dict[str, list[Seat]]  # a game's two seats, by `<set>/<pack>/<run>`
Models = dict[str, list[Seat]]  # every seat of a model


def read_seats(dirs: list[Path]) -> Games:
    games = {}
    for d, record in records(dirs):
        game, verdict = record["game"], record["verdict"]
        a = army(game["pack"])
        won = winner(verdict, game["sides"], a.tie_margin)
        name = f"{d.name}/{game['pack']}/{game['run']}"
        seats = []
        for side, model in game["players"].items():
            result = "draw" if won == "draw" else "win" if won == side else "loss"
            broken = verdict["margin"][side]["broken_share"]
            seat = Seat(
                model, name, game["pack"], d.name, side, SCORE[result], verdict["minute"], broken
            )
            tasks = tasks_by_formation(record, side)
            count_breaks(seat, own_breaks(record, side, a.units), tasks, broken * a.men[side])
            count_tasks(seat, tasks)
            count_orders(seat, [o for o in record["staff"] if o["side"] == side])
            count_turns(seat, [t for t in record["turns"] if t["side"] == side], a.units)
            count_result(seat)
            seats.append(seat)
        games[name] = seats
    return games


# ---------------------------------------------------------------- measures and intervals


def ratio(seats: list[Seat], key: str) -> float:
    den = sum(s.den[key] for s in seats)
    return sum(s.num[key] for s in seats) / den if den else math.nan


Stat = Callable[[Callable[[str], float], Callable[[str], float]], float]


def interval(
    games: Games, model: str, keys: tuple[str, ...], stat: Stat, n: int = 2000
) -> tuple[float, float, float]:
    """`stat(focus, others)` with its game-resampled 95% interval. `focus(key)` and
    `others(key)` give the ratio of `key` over the model's seats and the other six's."""
    cols = {(who, part, k): [] for who in ("f", "o") for part in ("num", "den") for k in keys}
    for seats in games.values():
        for who in ("f", "o"):
            mine = [s for s in seats if (s.model == model) == (who == "f")]
            for k in keys:
                cols[who, "num", k].append(sum(s.num[k] for s in mine))
                cols[who, "den", k].append(sum(s.den[k] for s in mine))

    def value(idx: list[int]) -> float:
        def getter(who: str) -> Callable[[str], float]:
            def get(k: str) -> float:
                den = sum(map(cols[who, "den", k].__getitem__, idx))
                return sum(map(cols[who, "num", k].__getitem__, idx)) / den if den else math.nan

            return get

        return stat(getter("f"), getter("o"))

    draws = sorted(v for v in map(value, resamples(len(games), n)) if not math.isnan(v))
    k = len(draws)  # a small set can leave a resample with nothing to count
    return value(list(range(len(games)))), draws[int(0.025 * k)], draws[int(0.975 * k) - 1]


@cache
def resamples(size: int, n: int) -> tuple[list[int], ...]:
    """The same `n` resamples of `size` games for every interval (seed 1)."""
    rng = random.Random(1)
    return tuple(rng.choices(range(size), k=size) for _ in range(n))


def by_model(games: Games) -> Models:
    """Every seat of each model, in standings order, for the models the games include."""
    out = defaultdict(list)
    for seats in games.values():
        for s in seats:
            out[s.model].append(s)
    return {m: out[m] for m in MODELS if m in out}


TABLE = {  # measure: format; a count per game, or a share
    "score": "{:.0%}",
    "breaks": "{:.1f}",
    "rally 15": "{:.0%}",
    "rally 30": "{:.0%}",
    "recovered": "{:.0%}",
    "hard answer": "{:.0%}",
    "silent when hurt": "{:.0%}",
    "by 09:05": "{:.0%}",
    "repeats": "{:.0%}",
    "standing": "{:.0%}",
    "placed": "{:.0%}",
    "quarter": "{:.0%}",
    "at all costs": "{:.0%}",
    "held": "{:.0%}",
    "garrison": "{:.1f}",
    "opening attack": "{:.0%}",
    "attackers at 09:00": "{:.1f}",
    "off the field": "{:.0%}",
    "lost by 11:30": "{:.0%}",
}


def print_table(models: Models) -> None:
    head = ["model", *TABLE, "stands min", "broken at end"]
    print("| " + " | ".join(head) + " |\n|" + "---|" * len(head))
    for m, seats in models.items():
        row = [m, *(fmt.format(ratio(seats, k)) for k, fmt in TABLE.items())]
        row.append(f"{statistics.median(x for s in seats for x in s.stands):.0f}")
        row.append(f"{statistics.median(s.broken for s in seats):.0%}")
        print("| " + " | ".join(row) + " |")
    sets = sorted({s.set for seats in models.values() for s in seats})
    print("\nmeasured points, share of orders by set:")
    for m in models:
        shares = (f"{ratio(models[m], f'measured {d}'):.0%}" for d in sets)
        print(f"  {m:9s} " + "  ".join(f"{d} {v}" for d, v in zip(sets, shares, strict=True)))


def line(models: Models, model: str, key: str) -> None:
    """The model's value, the range of the other six and the six pooled."""
    fmt = TABLE.get(key, "{:.0%}")
    others = sorted(ratio(seats, key) for m, seats in models.items() if m != model)
    pooled = ratio([s for m, seats in models.items() if m != model for s in seats], key)
    print(
        f"  {key}: {fmt.format(ratio(models[model], key))}; the others "
        f"{fmt.format(others[0])} to {fmt.format(others[-1])}, pooled {fmt.format(pooled)}"
    )


def diff(games: Games, model: str, label: str, keys: tuple[str, ...], stat: Stat) -> None:
    point, lo, hi = interval(games, model, keys, stat)
    fmt = "{:+.1f}" if all(TABLE.get(k) == "{:.1f}" for k in keys) else "{:+.1%}"
    print(f"  {label}: {fmt.format(point)} (95% {fmt.format(lo)} to {fmt.format(hi)})")


def versus(games: Games, model: str, key: str) -> None:
    """The model minus the other six, with its interval."""
    diff(games, model, f"{key}, {model} minus the others", (key,), lambda f, o: f(key) - o(key))


# The per-model sections: what each finding in docs/generals.md rests on.


def astra(games: Games, models: Models) -> None:
    for k in ("breaks", "rally 15", "recovered"):
        line(models, "astra", k)
    versus(games, "astra", "rally 15")
    versus(games, "astra", "recovered")


def fable(games: Games, models: Models) -> None:
    for k in ("standing", "placed", "score Plain+Mirror", "score Arms"):
        line(models, "fable", k)
    for k in ("score Arms horse", "score Arms foot"):
        line(models, "fable", k)
    keys = ("score Plain+Mirror", "score Arms")

    def drop(get: Callable[[str], float]) -> float:
        return get(keys[0]) - get(keys[1])

    for m in models:
        print(f"    {m:9s} Plain+Mirror minus Arms {drop(lambda k, m=m: ratio(models[m], k)):+.0%}")
    diff(games, "fable", "that drop, fable minus the others", keys, lambda f, o: drop(f) - drop(o))


def sol(games: Games, models: Models) -> None:
    line(models, "sol", "by 09:05")
    versus(games, "sol", "by 09:05")


def opus(games: Games, models: Models) -> None:
    for k in ("at all costs", "held", "garrison", "lost by 11:30"):
        line(models, "opus", k)
    versus(games, "opus", "garrison")


def luna(games: Games, models: Models) -> None:
    for k in ("opening attack", "attackers at 09:00", "off the field"):
        line(models, "luna", k)
    split = ("after an opening attack", "after a quiet opening")
    rest = [s for m, seats in models.items() if m != "luna" for s in seats]
    for who, seats in (("luna", models["luna"]), ("the others", rest)):
        games_in = [int(sum(s.den[k] for s in seats)) for k in split]
        print(
            f"    {who}: score {ratio(seats, split[0]):.0%} in {games_in[0]} games after an "
            f"opening attack, {ratio(seats, split[1]):.0%} in {games_in[1]} without"
        )
    off = [s for s in models["luna"] if s.num["off the field"]]
    print(
        f"    luna's games with the army sent off the field: {len(off)}, "
        f"score {ratio(off, 'score'):.0%}"
    )
    diff(
        games,
        "luna",
        "luna's score, opening attack minus none",
        split,
        lambda f, o: f(split[0]) - f(split[1]),
    )


def deepseek(games: Games, models: Models) -> None:
    for k in ("repeats", "quarter", "hard answer", "score Plain", "score Mirror", "score Arms"):
        line(models, "deepseek", k)
    versus(games, "deepseek", "hard answer")


def sonnet(games: Games, models: Models) -> None:
    for k in ("silent when hurt", "rally 30"):
        line(models, "sonnet", k)
    versus(games, "sonnet", "silent when hurt")
    versus(games, "sonnet", "rally 30")


SECTIONS = {f.__name__: f for f in (astra, fable, sol, opus, luna, deepseek, sonnet)}


def print_story(games: Games, model: str, game: str) -> None:
    """The seat's verdict and measures in one game, and the order it repeated most."""
    me = next(s for s in games[game] if s.model == model)
    them = next(s for s in games[game] if s is not me)
    record = load(game)
    turns = [t for t in record["turns"] if t["side"] == me.side]
    said = Counter(o for t in turns for o in orders_of(t))
    top, times = said.most_common(1)[0]
    units = army(me.pack).units
    hurt = [t["arrived"] for t in turns if is_hurt(t, me.side, units) and not orders_of(t)]
    how = {1.0: "won", 0.5: "drew", 0.0: "lost"}[me.score]
    print(
        f"  {game}: {model} ({me.side}) against {them.model}, {how} at {clock(me.minute)} "
        f"by {record['verdict']['how']}"
    )
    print(
        f"    broken at the verdict {me.broken:.0%} against {them.broken:.0%}; "
        f"orders {me.den['by 09:05']:.0f}, {me.num['by 09:05']:.0f} by 09:05; garrison "
        f"{me.num['garrison']:.0f}; attackers at 09:00 {me.num['attackers at 09:00']:.0f}"
    )
    print(
        f"    breaks {me.num['breaks']:.0f}, rallied within 15 min {me.num['rally 15']:.0f}; "
        f"silent at {len(hurt)} of {me.den['silent when hurt']:.0f} briefs when hurt "
        f"({', '.join(hurt) or 'none'})"
    )
    if times > 1:
        print(f"    sent most often, {times} times: {top}")


# ---------------------------------------------------------------- quotes


def check_quotes() -> bool:
    """Print each cited order with its record and the clocks it was sent at; False if any is
    not in the record at the clock cited (None: cited without a clock)."""
    ok = True
    for model, game, at, text in QUOTES:
        record = load(game)
        players = record["game"]["players"]
        sent = [
            t["arrived"]
            for t in record["turns"]
            if players[t["side"]] == model and text in (t["orders"] or [])
        ]
        found = at in sent if at else bool(sent)
        ok &= found
        when = at or f"{len(sent)} times, first at {sent[0] if sent else '-'}"
        print(
            f"{'ok' if found else 'NOT FOUND'}  {model}, games/{game}.json.gz, {when}\n  > {text}"
        )
    return ok


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("dirs", nargs="*", type=Path, default=MATRIX)
    ap.add_argument("--quotes", action="store_true", help="check and print the cited orders")
    a = ap.parse_args(argv)
    games = read_seats([d.resolve() for d in a.dirs])
    models = by_model(games)
    print(f"{len(games)} games\n")
    print_table(models)
    for name, section in SECTIONS.items():
        if name not in models:
            continue
        print(f"\n## {name}")
        section(games, models)
        if STORIES[name] in games:
            print_story(games, name, STORIES[name])
    if a.quotes:
        print()
        return 0 if check_quotes() else 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
