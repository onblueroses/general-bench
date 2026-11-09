"""The cross-pack report over synthetic grids: a complete Kolín grid, a partial grid of a hill
field (attacker on the second side) with a rejudged, a stopped, a running and a pending cell."""

from __future__ import annotations

import csv
import io
import itertools
import json
from pathlib import Path

import pytest
from test_engine_kit import KOLIN

from kriegsspiel import cross, grid, results
from kriegsspiel.scenario import load_meta, resolve


def _cell(
    out: Path,
    name: str,
    players: dict,
    seed: int,
    *,
    winner=None,
    p=None,
    dec=None,
    lost=None,
    achieved=None,
    rejudge=None,
    stopped=False,
) -> None:
    """A run.jsonl with the records `game_row` reads: header, a commander reply per model
    side, a tick of orders, and a verdict (or a stop, or nothing: a game still running)."""
    d = out / name
    d.mkdir(parents=True)
    recs = [
        {
            "type": "header",
            "seed": seed,
            "scenario": "x",
            "play": {"players": players, "sides": list(players)},
        }
    ]
    orders = []
    for side, who in players.items():
        if who != "script":
            recs.append(
                {
                    "type": "commander",
                    "side": side,
                    "commander": who,
                    "wall_s": 10.0,
                    "orders": ["a"],
                    "meta": {},
                }
            )
        orders.append({"at": 0, "side": side, "text": "Advance.", "clarifications": ["?"]})
    recs.append({"type": "tick", "tick": 0, "orders": orders, "jev": [{"cost": 0.001}]})

    def verdict(w, pp, dd, ach):
        v = {
            "winner": w,
            "decisiveness": dd,
            "attacker_achieved": False,
            "rationale": f"winner {w} (p=0.6); attacker achieved p={pp}; decisiveness x",
        }
        if ach:
            v["achieved"] = ach
        return v

    text = "Time 19:30.\n" + "".join(
        f"{s}: 30,000 men at the start, {n:,} lost, 0 bodies\n" for s, n in (lost or {}).items()
    )
    if stopped:
        recs.append({"type": "stopped", "tick": 60, "reason": "HTTP 403 limit"})
    elif winner:
        recs.append(
            {
                "type": "verdict",
                "tick": 390,
                "summary": text,
                "verdict": verdict(winner, p, dec, achieved),
            }
        )
        if rejudge:
            recs.append(
                {
                    "type": "rejudge",
                    "tick": 390,
                    "umpire_version": 3,
                    "replayed": "abc1234",
                    "account": text,
                    "verdict": verdict(*rejudge),
                }
            )
    (d / "run.jsonl").write_text("".join(json.dumps(r) + "\n" for r in recs))


def _manifest(
    out: Path,
    scenario: str,
    sides: list[str],
    seeds: list[int],
    cells: list[dict],
    commit: str = "deadbee",
) -> None:
    out.mkdir(parents=True, exist_ok=True)
    (out / "manifest.json").write_text(
        json.dumps(
            {
                "config": {
                    "scenario": scenario,
                    "sides": sides,
                    "seeds": seeds,
                    "engine_commit": commit,
                },
                "cells": cells,
            }
        )
    )


def _mc(name, model, role, seed, status="done"):
    return {"name": name, "model": model, "role": role, "seed": seed, "status": status}


@pytest.fixture
def grids(tmp_path, monkeypatch):
    monkeypatch.setattr(results, "FRESH_S", 3600.0)  # the verdict-less log below is "running"
    kolin = tmp_path / "grid-t-kolin"
    pk = {"prussia": "script", "austria": "script"}
    mcells = []
    # opus as Prussia (attacker): wins seed 1, loses seed 2
    for seed, w, p, dec, lp, la in (
        (1, "prussia", 0.5, 0.6, 6000, 12000),
        (2, "austria", 0.2, 0.3, 8000, 4000),
    ):
        _cell(
            kolin,
            f"opus-prussia-s{seed}",
            {**pk, "prussia": "opus"},
            seed,
            winner=w,
            p=p,
            dec=dec,
            lost={"prussia": lp, "austria": la},
            achieved={"prussia": "in part", "austria": "in part"},
        )
        mcells.append(_mc(f"opus-prussia-s{seed}", "opus", "prussia", seed))
    for seed in (1, 2):
        _cell(
            kolin,
            f"opus-austria-s{seed}",
            {**pk, "austria": "opus"},
            seed,
            winner="austria",
            p=0.05,
            dec=0.2,
            lost={"prussia": 6000, "austria": 3000},
        )
        _cell(
            kolin,
            f"sol-prussia-s{seed}",
            {**pk, "prussia": "sol"},
            seed,
            winner="austria",
            p=0.1,
            dec=0.1,
            lost={"prussia": 5000, "austria": 5000},
        )
        _cell(
            kolin,
            f"sol-austria-s{seed}",
            {**pk, "austria": "sol"},
            seed,
            winner="austria",
            p=0.1,
            dec=0.2,
            lost={"prussia": 5000, "austria": 5000},
        )
        _cell(
            kolin,
            f"script-baseline-s{seed}",
            pk,
            seed,
            winner="austria",
            p=0.1,
            dec=0.2,
            lost={"prussia": 5000, "austria": 4000},
        )
        _cell(
            kolin,
            f"opus-vs-sol-s{seed}",
            {"prussia": "opus", "austria": "sol"},
            seed,
            winner="prussia" if seed == 1 else "austria",
            p=0.4,
            dec=0.5,
            lost={"prussia": 7000, "austria": 7000},
        )
        mcells += [
            _mc(f"opus-austria-s{seed}", "opus", "austria", seed),
            _mc(f"sol-prussia-s{seed}", "sol", "prussia", seed),
            _mc(f"sol-austria-s{seed}", "sol", "austria", seed),
            _mc(f"script-baseline-s{seed}", "script", "baseline", seed),
            _mc(f"opus-vs-sol-s{seed}", "opus vs sol", "pair", seed),
        ]
    _manifest(kolin, str(KOLIN), ["prussia", "austria"], [1, 2], mcells)

    field = tmp_path / "hill-field"  # a pack whose meta names the second side the attacker
    field.mkdir()
    (field / "meta.json").write_text(
        json.dumps({"sides": {"north": {"role": "defender"}, "south": {"role": "attacker"}}})
    )
    hill = tmp_path / "grid-t-hill"
    ph = {"north": "script", "south": "script"}
    # rejudged: the game said south won at p=0.6; umpire v3 gives it to north at p=0.3
    _cell(
        hill,
        "opus-north-s1",
        {**ph, "north": "opus"},
        1,
        winner="south",
        p=0.6,
        dec=0.5,
        lost={"north": 900, "south": 300},
        rejudge=("north", 0.3, 0.4, {"north": "in the main", "south": "in part"}),
    )
    _cell(hill, "opus-south-s1", {**ph, "south": "opus"}, 1, stopped=True)
    _cell(hill, "script-baseline-s1", ph, 1)  # no verdict yet, fresh: running
    _manifest(
        hill,
        str(field),
        ["north", "south"],
        [1],
        [
            _mc("opus-north-s1", "opus", "north", 1),
            _mc("opus-south-s1", "opus", "south", 1, "failed"),
            _mc("script-baseline-s1", "script", "baseline", 1, "running"),
            _mc("opus-vs-sol-s1", "opus vs sol", "pair", 1, "pending"),
        ],
        commit="feed123",
    )
    return kolin, hill


def _section(text: str, head: str) -> str:
    start = text.index(head)
    nxt = text.find("\n## ", start + 1)
    return text[start : nxt if nxt > 0 else None]


def test_complete_grid(grids, tmp_path):
    kolin, _ = grids
    out = tmp_path / "cross.md"
    assert grid.main(["cross", str(out), str(kolin)]) == 0
    text = out.read_text()
    s1 = _section(text, "## 1.")
    # seeds in one cell, own/enemy from the model's side, levels per side
    assert (
        "| opus | kolin | prussia (attacker) | 1 / 2 | prussia / austria | 0.5 / 0.2 | "
        "in part / in part | in part / in part | 0.6 / 0.3 | 6,000 / 8,000 | "
        "12,000 / 4,000 | 1 / 1 | 1 / 1 | 1 / 1 | 0 / 0 | game / game |"
    ) in s1
    assert "| opus | kolin | austria (defender) | 1 / 2 | austria / austria |" in s1
    s2 = _section(text, "## 2.")
    att = s2[s2.index("### Model as attacker") : s2.index("### Model as defender")]
    # opus attacking: 1 win, mean p (0.5+0.2)/2, mean dec 0.45, loss ratios 0.5 and 2.0
    assert "| opus | 2 / 2 | 1 | 0.35 | 0.45 | 1.25 |" in att
    assert "| script (baseline) | 2 / 2 | 0 | 0.1 | 0.2 | 1.25 |" in att
    # paired against the baseline of the same seed: win +1 and 0, p +0.4 and +0.1
    assert "| opus | 2 | +0.500 [+0.000, +1.000] | +0.250 [+0.100, +0.400] |" in att
    dfn = s2[s2.index("### Model as defender") :]
    assert "| script (baseline) | 2 / 2 | 2 | 0.1 | 0.2 | 0.8 |" in dfn
    assert "| opus | 2 / 2 | 2 | 0.05 | 0.2 | 0.5 |" in dfn
    s3 = _section(text, "## 3.")
    assert "| attacker \\ defender | sol |" in s3 and "| opus | 1 – 1 (n=2) |" in s3
    assert "| kolin | opus | sol | 1 | prussia | 0.4 |" in s3
    s4 = _section(text, "## 4.")
    # attacker won: opus s1 and the pair s1, of 4 + 4 single games and 2 pairs
    assert (
        "| kolin | prussia | austria | 1 / 2 | austria / austria | 0.1 / 0.1 | 0.2 / 0.2 | "
        "1 / 4 (25%) | 0 / 4 (0%) | 1 / 2 (50%) | 2 / 10 (20%) |"
    ) in s4
    s5 = _section(text, "## 5.")
    assert "| kolin | grid-t-kolin | deadbee | 12 | 12 | 0 | 0 | 0 | 0 | - |" in s5
    assert "percentile bootstrap" in text and "10,000" in text
    lines = text.splitlines()
    heads = [a.lower() for a, b in itertools.pairwise(lines) if b.startswith("|---")]
    assert len(heads) == 11  # 9, plus the W-D-L tables per pair and per model in section 3
    assert not any(w in h for h in heads for w in ("score", "rank", "elo", "composite", "total"))


def test_partial_grid_and_rejudge(grids, tmp_path):
    kolin, hill = grids
    out = tmp_path / "cross.md"
    assert grid.main(["cross", str(out), str(kolin), str(hill)]) == 0
    text = out.read_text()
    s1 = _section(text, "## 1.")
    # the hill field's attacker is south, the second side; north is the defender
    assert (
        "| opus | hill-field | north (defender) | 1 | north | 0.3 | in the main "
        "| in part | 0.4 | 900 | 300 |"
    ) in s1
    assert "rejudge v3 |" in s1
    assert "| opus | hill-field | south (attacker) | 1 | failed | · |" in s1
    s4 = _section(text, "## 4.")
    assert "| hill-field | south | north | 1 | running | · | · |" in s4
    s5 = _section(text, "## 5.")
    assert (
        "| hill-field | grid-t-hill | feed123 | 4 | 1 | 1 | 1 | 1 | 1 | "
        "opus-south-s1 (failed), script-baseline-s1 (running), "
        "opus-vs-sol-s1 (pending) |"
    ) in s5
    s3 = _section(text, "## 3.")
    # the hill field's pair puts sol (south) on the attack; pending, so no game counted
    assert "| sol |" in s3 and "0 – 0 (n=0 of 1)" in s3
    # the defender baseline on the hill never finished: opus pairs only on Kolín's seeds
    dfn = _section(text, "## 2.")
    dfn = dfn[dfn.index("### Model as defender") :]
    assert "| opus | 3 / 3 | 3 |" in dfn
    assert "| opus | 2 |" in dfn.split("Paired difference")[1]


def test_csv_one_row_per_cell(grids, tmp_path):
    kolin, hill = grids
    out = tmp_path / "cross.csv"
    assert grid.main(["cross", str(out), str(kolin), str(hill), "--format", "csv"]) == 0
    rows = list(csv.DictReader(io.StringIO(out.read_text())))
    assert len(rows) == 12 + 4
    r = next(x for x in rows if x["cell"] == "opus-north-s1")
    assert r["pack"] == "hill-field" and r["judged"] == "rejudge v3"
    assert r["engine_commit"] == "feed123" and r["rejudge_commit"] == "abc1234"
    assert r["winner"] == "north" and r["attacker_p"] == "0.3" and r["role_kind"] == "defender"
    assert r["own_losses"] == "900" and r["enemy_losses"] == "300" and r["loss_ratio"] == "3.0"
    pend = next(x for x in rows if x["cell"] == "opus-vs-sol-s1" and x["pack"] == "hill-field")
    assert pend["coverage"] == "pending" and pend["attacker_model"] == "sol"
    pair = next(x for x in rows if x["cell"] == "opus-vs-sol-s1" and x["pack"] == "kolin")
    assert pair["attacker_model"] == "opus" and pair["consultations_attacker"] == "1"


def test_bootstrap_ci():
    assert cross.bootstrap_ci([0.3]) is None
    lo, hi = cross.bootstrap_ci([0.0, 1.0, 0.5, 0.2])
    assert lo <= 0.425 <= hi and lo >= 0.0 and hi <= 1.0
    assert cross.bootstrap_ci([0.0, 1.0, 0.5, 0.2]) == (lo, hi)  # fixed seed


def _ordinal_cell(out: Path, name: str, players: dict, seed: int, winner: str, how: str):
    """A finished game of an ordinal pack: the verdict carries `how` (Verdict.to_json)."""
    d = out / name
    d.mkdir(parents=True)
    recs = [
        {
            "type": "header",
            "seed": seed,
            "scenario": "x",
            "play": {"players": players, "sides": list(players)},
        },
        {"type": "tick", "tick": 0, "orders": []},
        {
            "type": "verdict",
            "tick": 420,
            "verdict": {
                "winner": winner,
                "how": how,
                "winner_source": "ordinal",
                "rationale": f"ordinal verdict: {winner} ({how})",
            },
        },
    ]
    (d / "run.jsonl").write_text("".join(json.dumps(r) + "\n" for r in recs))


def test_ordinal_grid_counts_draws_and_how(tmp_path):
    g = tmp_path / "grid-t-plain"
    pk = {"blue": "script", "red": "script"}
    games = [  # (cell, players, model, role, seed, winner, how)
        ("script-baseline-s1", pk, "script", "baseline", 1, "blue", "break"),
        ("script-baseline-s2", pk, "script", "baseline", 2, "draw", "draw"),
        ("script-baseline-s3", pk, "script", "baseline", 3, "red", "possession"),
        ("script-baseline-s4", pk, "script", "baseline", 4, "draw", "draw"),
        ("opus-blue-s1", {**pk, "blue": "opus"}, "opus", "blue", 1, "blue", "play-on"),
        ("opus-blue-s2", {**pk, "blue": "opus"}, "opus", "blue", 2, "draw", "draw"),
        (
            "opus-vs-sol-s1",
            {"blue": "opus", "red": "sol"},
            "opus vs sol",
            "pair",
            1,
            "blue",
            "possession",
        ),
        (
            "opus-vs-sol-s2",
            {"blue": "opus", "red": "sol"},
            "opus vs sol",
            "pair",
            2,
            "draw",
            "draw",
        ),
        (
            "sol-vs-opus-s1",
            {"blue": "sol", "red": "opus"},
            "sol vs opus",
            "pair",
            1,
            "red",
            "break",
        ),
        (
            "sol-vs-opus-s2",
            {"blue": "sol", "red": "opus"},
            "sol vs opus",
            "pair",
            2,
            "draw",
            "draw",
        ),
    ]
    for cell, pl, _m, _r, seed, w, how in games:
        _ordinal_cell(g, cell, pl, seed, w, how)
    _manifest(
        g,
        "data/plain",
        ["blue", "red"],
        [1, 2, 3, 4],
        [_mc(c, m, r, s) for c, _p, m, r, s, _w, _h in games],
    )
    out = tmp_path / "cross.md"
    assert grid.main(["cross", str(out), str(g)]) == 0
    text = out.read_text()
    s2 = _section(text, "## 2.")
    att = s2[s2.index("### Model as attacker") : s2.index("### Model as defender")]
    # opus as blue: a win and a draw; the baseline from blue: W D L D
    assert "| opus | 2 / 2 | 1 |" in att and "| 1-1-0 | 75% |" in att
    assert "| script (baseline) | 4 / 4 | 1 |" in att and "| 1-2-1 | 50% |" in att
    dfn = s2[s2.index("### Model as defender") :]
    assert "| script (baseline) | 4 / 4 | 1 |" in dfn and "| 1-2-1 | 50% |" in dfn
    s3 = _section(text, "## 3.")
    # opus beats sol twice (once on each side), two draws
    assert "| opus vs sol | 4 / 4 | 2-2-0 | 75% |" in s3
    assert "| opus | 4 | 2-2-0 | 75% |" in s3 and "| sol | 4 | 0-2-2 | 25% |" in s3
    s4 = _section(text, "## 4.")
    # 5 of the 10 finished games drawn; break 2, possession 2, play-on 1, draw 5
    assert "| 5 / 10 (50%) | 2 / 2 / 1 / 5 |" in s4
    assert "how decided: break / possession / play-on / draw" in s4
    # a weighted pack shows no how counts
    assert cross._how_counts([{"coverage": "done", "winner": "a"}]) == "-"


def test_arms_sides_are_labelled_horse_and_foot(tmp_path):
    """Arms (data/arms-medlar) names no attacker: the report shows its sides as horse and
    foot, never "horse (attacker)" (docs/battles/README.md: the cross report labels sides horse
    and foot); a pack that names one keeps "side (attacker)"."""
    g = tmp_path / "grid-t-arms"
    pk = {"horse": "script", "foot": "script"}
    games = [
        ("opus-horse-s1", {**pk, "horse": "opus"}, "opus", "horse", 1, "horse", "break"),
        ("opus-foot-s1", {**pk, "foot": "opus"}, "opus", "foot", 1, "draw", "draw"),
        ("script-baseline-s1", pk, "script", "baseline", 1, "foot", "possession"),
    ]
    for cell, pl, _m, _r, seed, w, how in games:
        _ordinal_cell(g, cell, pl, seed, w, how)
    _manifest(
        g,
        "data/arms-medlar",
        ["horse", "foot"],
        [1],
        [_mc(c, m, r, s) for c, _p, m, r, s, _w, _h in games],
    )
    out = tmp_path / "cross.md"
    assert grid.main(["cross", str(out), str(g)]) == 0
    text = out.read_text()
    s1 = _section(text, "## 1.")
    assert "| opus | arms-medlar | horse | 1 | horse |" in s1
    assert "| opus | arms-medlar | foot | 1 | draw |" in s1
    assert "(attacker)" not in s1 and "(defender)" not in s1
    s2 = _section(text, "## 2.")
    assert "Sides in this seat: arms-medlar horse (first side, no attacker named)." in s2
    assert "Sides in this seat: arms-medlar foot (second side, no attacker named)." in s2
    s4 = _section(text, "## 4.")
    assert "| arms-medlar | horse | foot | 1 |" in s4
    # control: Kolín names its attacker, and its sections keep the role in the label
    assert load_meta(KOLIN).names_attacker(("prussia", "austria"))
    assert not load_meta(resolve("data/arms-medlar")).names_attacker(("horse", "foot"))
