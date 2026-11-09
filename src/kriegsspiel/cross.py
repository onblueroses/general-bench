"""The cross-pack report: several grids (one per battle pack) read into one markdown report or
one CSV row per cell. Per model, role and pack; per model and role over the packs, with the
script baseline and a paired bootstrap difference; model against model; battle balance; and
coverage. Measured outcomes only: no composite score, no ranking.

    uv run python -m kriegsspiel.grid cross runs/cross.md runs/grid-x-plain runs/grid-x-mirror
"""

from __future__ import annotations

import csv
import io
import json
import random
import statistics
from pathlib import Path

from .results import FRESH_S, fmt_value, game_row, load_grid, mean_of, text_table
from .scenario import DEFAULT_SCENARIO, Meta, load_meta, load_sides, resolve

BOOT_B = 10_000  # bootstrap resamples
BOOT_SEED = 0  # fixed: the same logs give the same interval
HOW = ("break", "possession", "play-on", "draw")  # how an ordinal verdict fell


def _meta(scenario: str) -> Meta:
    """The pack's meta, or the defaults for a pack that cannot be read."""
    try:
        return load_meta(resolve(scenario))
    except (OSError, json.JSONDecodeError):
        return Meta()


def _side_label(pack: dict, kind: str) -> str:
    """A side as the report shows it: "prussia (attacker)" where the meta names an attacker;
    the side alone where it names none ("horse", "foot" on Arms; "red", "blue" on Plain), so
    no report calls a meeting engagement's first army the attacker."""
    side = pack["attacker"] if kind == "attacker" else pack["defender"]
    return f"{side} ({kind})" if pack.get("named", True) else side


def _coverage(row: dict | None, mcell: dict | None) -> str:
    """done, running, failed or pending for one cell: the log decides when there is one."""
    if row is None or row.get("status") == "no log":
        st = (mcell or {}).get("status")
        return st if st in ("running", "failed") else "pending"
    st = row.get("status")
    return st if st in ("done", "running") else "failed"  # stopped or incomplete


def _ratio(a, b):
    return (
        round(a / b, 4)
        if isinstance(a, (int, float)) and isinstance(b, (int, float)) and b
        else None
    )


def cross_rows(dirs: list[Path]) -> tuple[list[dict], list[dict]]:
    """Per grid directory its pack (label, scenario, sides, attacker, seeds, cells by
    coverage), and one row per cell: `game_row` plus the pack, the coverage status, the
    engine commit and the attacker/defender and own/enemy views of the measures. A manifest
    cell with no directory yet is a pending row with only its name, model, role and seed."""
    packs: list[dict] = []
    rows: list[dict] = []
    labels: set[str] = set()
    for out in map(Path, dirs):
        config, mcells, cdirs = load_grid(out)
        scenario = config.get("scenario") or DEFAULT_SCENARIO
        sides = tuple(config.get("sides") or load_sides(resolve(None)))
        label = Path(scenario).name
        if label in labels:  # two grids of one pack stay apart
            label = f"{label} ({out.name})"
        labels.add(label)
        meta = _meta(scenario)
        att = meta.attacker(sides)
        dfn = next((s for s in sides if s != att), sides[-1])
        pack = {
            "label": label,
            "dir": str(out),
            "scenario": scenario,
            "sides": sides,
            "attacker": att,
            "defender": dfn,
            "named": meta.names_attacker(sides),
            "engine_commit": config.get("engine_commit"),
            "seeds": list(config.get("seeds") or []),
            "cells": {k: [] for k in ("done", "running", "failed", "pending")},
        }
        seen = set()
        for d in cdirs:
            mc = mcells.get(d.name)
            r = game_row(d, mc)
            r["coverage"] = _coverage(r, mc)
            r["engine_commit"] = (mc or {}).get("engine_commit") or config.get("engine_commit")
            rows.append(_views(r, pack))
            seen.add(d.name)
        for name, mc in mcells.items():
            if name in seen:
                continue
            if mc.get("role") == "pair":
                a, _, b = str(mc.get("model", "")).partition(" vs ")
                extra = {f"player_{sides[0]}": a, f"player_{sides[1]}": b}
            else:
                extra = {}
            r = {
                "cell": name,
                "model": mc.get("model"),
                "role": mc.get("role"),
                "seed": mc.get("seed"),
                "status": mc.get("status") or "pending",
                "winner": None,
                "coverage": _coverage(None, mc),
                "engine_commit": mc.get("engine_commit") or config.get("engine_commit"),
                **extra,
            }
            rows.append(_views(r, pack))
        for r in rows:
            if r["pack"] == label:
                pack["cells"][r["coverage"]].append(r["cell"])
                if r.get("seed") is not None and r["seed"] not in pack["seeds"]:
                    pack["seeds"].append(r["seed"])
        pack["seeds"].sort()
        packs.append(pack)
    return packs, rows


def _views(r: dict, pack: dict) -> dict:
    att, dfn = pack["attacker"], pack["defender"]
    r.update(
        pack=pack["label"],
        scenario=pack["scenario"],
        attacker_side=att,
        defender_side=dfn,
        attacker_losses=r.get(f"lost_{att}"),
        defender_losses=r.get(f"lost_{dfn}"),
        attacker_level=r.get(f"achieved_{att}"),
        defender_level=r.get(f"achieved_{dfn}"),
    )
    done = r.get("coverage") == "done"
    r["attacker_won"] = (r.get("winner") == att) if done else None
    role = r.get("role")
    if role in (att, dfn):
        enemy = dfn if role == att else att
        r.update(
            role_kind="attacker" if role == att else "defender",
            own_losses=r.get(f"lost_{role}"),
            enemy_losses=r.get(f"lost_{enemy}"),
            own_level=r.get(f"achieved_{role}"),
            enemy_level=r.get(f"achieved_{enemy}"),
            model_won=(r.get("winner") == role) if done else None,
        )
        r["loss_ratio"] = _ratio(r["own_losses"], r["enemy_losses"])
    elif role == "pair":
        r.update(attacker_model=r.get(f"player_{att}"), defender_model=r.get(f"player_{dfn}"))
        for k in ("consultations", "orders", "staff_questions", "harness_errors"):
            r[f"{k}_attacker"], r[f"{k}_defender"] = r.get(f"{k}_{att}"), r.get(f"{k}_{dfn}")
    return r


def _side_view(r: dict, kind: str) -> dict:
    """One game seen from its attacker or defender: won, attacker p, decisiveness, losses
    of that side over the other's."""
    own, enemy = (
        (r["attacker_losses"], r["defender_losses"])
        if kind == "attacker"
        else (r["defender_losses"], r["attacker_losses"])
    )
    side = r["attacker_side"] if kind == "attacker" else r["defender_side"]
    return {
        "won": float(r.get("winner") == side),
        "attacker_p": r.get("attacker_p"),
        "decisiveness": r.get("decisiveness"),
        "loss_ratio": _ratio(own, enemy),
        "result": _result(r, side),
    }


def _result(r: dict, side: str) -> str:
    """W, D or L for `side` in a finished game: a draw is any finished game that no side of
    the pack won (an ordinal draw, a weighted "undecided")."""
    w = r.get("winner")
    if w == side:
        return "W"
    if w in (r.get("attacker_side"), r.get("defender_side")):
        return "L"
    return "D"


def _wdl(results: list[str]) -> tuple[str, str]:
    """('W-D-L', 'share') with a draw counting half; share '-' with no games."""
    w, d, lo = (results.count(x) for x in "WDL")
    n = w + d + lo
    return f"{w}-{d}-{lo}", (f"{(w + 0.5 * d) / n:.0%}" if n else "-")


def _how_counts(rs: list[dict]) -> str:
    """Counts of an ordinal verdict's `how` over finished games, '-' when none carries one."""
    hs = [r.get("how") for r in rs if r.get("coverage") == "done" and r.get("how")]
    if not hs:
        return "-"
    out = " / ".join(str(hs.count(h)) for h in HOW)
    other = len(hs) - sum(hs.count(h) for h in HOW)
    return out + (f" (+{other} other)" if other else "")


def bootstrap_ci(
    xs: list[float], b: int = BOOT_B, seed: int = BOOT_SEED
) -> tuple[float, float] | None:
    """Percentile 95% interval of the mean, resampling the paired units with replacement;
    None under two units (no spread to resample)."""
    if len(xs) < 2:
        return None
    rng = random.Random(seed)
    n = len(xs)
    means = sorted(sum(rng.choices(xs, k=n)) / n for _ in range(b))
    return means[int(0.025 * b)], means[int(0.975 * b) - 1]


def _signed(x: float) -> str:
    return f"{x:+.3f}".replace("-", "−")


def _diff_cell(xs: list[float]) -> str:
    if not xs:
        return "-"
    m = statistics.fmean(xs)
    ci = bootstrap_ci(xs)
    return _signed(m) + (f" [{_signed(ci[0])}, {_signed(ci[1])}]" if ci else " [n<2]")


def _seeded(rs_by_seed: dict, seeds: list, fn) -> str:
    """'v1 / v2' over the pack's seeds; a seed with no cell shows 'no cell'."""
    parts = []
    for s in seeds:
        r = rs_by_seed.get(s)
        parts.append("no cell" if r is None else fn(r))
    return " / ".join(parts)


def _outcome(r: dict, key: str = "winner") -> str:
    if r.get("coverage") != "done":
        return r.get("coverage") or "-"
    return fmt_value(r.get(key))


def _done_only(key):
    return lambda r: fmt_value(r.get(key)) if r.get("coverage") == "done" else "·"


def _models_in_order(rows: list[dict]) -> list[str]:
    return list(
        dict.fromkeys(
            r["model"]
            for r in rows
            if r.get("role_kind") and r.get("model") not in (None, "script")
        )
    )


def cross(dirs: list[Path]) -> str:
    """The markdown report: an introduction, five sections and the method footer."""
    packs, rows = cross_rows(dirs)
    singles = [r for r in rows if r.get("role_kind")]
    base = [r for r in rows if r.get("role") == "baseline"]
    pairs = [r for r in rows if r.get("role") == "pair"]
    models = _models_in_order(singles)
    parts = [
        _intro(packs),
        _per_model_role_pack(models, packs, singles),
        _per_model_by_role(models, packs, singles, base),
        _model_against_model(packs, pairs),
        _battle_balance(packs, singles, base, pairs),
        _coverage_table(packs, rows),
        _method(),
    ]
    return "\n".join(line for part in parts for line in part)


def _intro(packs: list[dict]) -> list[str]:
    return [
        f"# Cross-pack report: {len(packs)} grid(s)",
        "",
        (
            "Measured outcomes per model, role and battle pack. The attacker is the side whose "
            "pack meta names it so (else the first side: a designed battle names none, and its "
            'sides are shown by their own names, horse and foot on Arms); "attacker p" is the '
            "umpire's "
            "probability that the attacker achieved its objective, from the latest rejudge "
            "when a game was rejudged. Loss ratio is the side's own losses over the enemy's "
            "(lower is better for that side). No composite score: roles and packs are never "
            "summed or weighted into one number."
        ),
        "",
    ]


def _per_model_role_pack(models: list[str], packs: list[dict], singles: list[dict]) -> list[str]:
    """Section 1: one line per model, side and pack, the seeds side by side."""
    out: list[str] = [
        "## 1. Per model, role and pack",
        "",
        (
            'One line per model, side and pack; each cell lists the seeds in order ("s1 / '
            's2", the seeds column). A game not finished shows its coverage status; "·" '
            "marks a measure of an unfinished game."
        ),
        "",
    ]
    cols1 = [
        ("model", "model"),
        ("pack", "pack"),
        ("side", "side (role)"),
        ("seeds", "seeds"),
        ("winner", "winner"),
        ("attacker_p", "attacker p"),
        ("own_level", "own level"),
        ("enemy_level", "enemy level"),
        ("decisiveness", "decisiveness"),
        ("own_losses", "own losses"),
        ("enemy_losses", "enemy losses"),
        ("consultations", "consultations"),
        ("orders", "orders"),
        ("staff_questions", "staff questions"),
        ("harness_errors", "harness errors"),
        ("judged", "verdict from"),
    ]
    t1 = []
    for m in models:
        for kind in ("attacker", "defender"):
            for p in packs:
                rs = {
                    r["seed"]: r
                    for r in singles
                    if r["model"] == m and r["role_kind"] == kind and r["pack"] == p["label"]
                }
                if not rs:
                    continue
                line = {
                    "model": m,
                    "pack": p["label"],
                    "side": _side_label(p, kind),
                    "seeds": " / ".join(map(str, p["seeds"])),
                    "winner": _seeded(rs, p["seeds"], _outcome),
                }
                for k, _ in cols1[5:]:
                    line[k] = _seeded(rs, p["seeds"], _done_only(k))
                t1.append(line)
    out += text_table(t1, cols1) if t1 else ["(no model games)"]
    return out


def _per_model_by_role(
    models: list[str], packs: list[dict], singles: list[dict], base: list[dict]
) -> list[str]:
    """Section 2: per model across packs as attacker and as defender, against the script
    baseline, with the paired bootstrap difference."""
    out: list[str] = [
        "",
        "## 2. Per model across packs, by role",
        "",
        (
            "Means over finished games. The script baseline row reads the script-against-script "
            "games from the same side. The paired difference is model minus baseline on the "
            "same pack and seed (wins as 0/1), with a bootstrap 95% interval (footer). W-D-L "
            "counts the model's wins, draws (a finished game no side won) and losses; the "
            "share counts a draw half."
        ),
        "",
    ]
    cols2 = [
        ("model", "model"),
        ("games", "games (done / cells)"),
        ("wins", "wins"),
        ("attacker_p", "mean attacker p"),
        ("decisiveness", "mean decisiveness"),
        ("loss_ratio", "mean loss ratio"),
        ("wdl", "W-D-L"),
        ("share", "share (draw ½)"),
    ]
    colsd = [
        ("model", "model"),
        ("n", "paired (pack, seed)"),
        ("won", "Δ win"),
        ("attacker_p", "Δ attacker p"),
        ("decisiveness", "Δ decisiveness"),
        ("loss_ratio", "Δ loss ratio"),
    ]
    base_done = [r for r in base if r.get("coverage") == "done"]
    base_at = {(r["pack"], r["seed"]): r for r in base_done}
    for kind in ("attacker", "defender"):
        t2, td = [], []
        for m in models:
            rs = [r for r in singles if r["model"] == m and r["role_kind"] == kind]
            if not rs:
                continue  # a model never cast in this role
            done = [r for r in rs if r.get("coverage") == "done"]
            vs = [_side_view(r, kind) for r in done]
            wdl, share = _wdl([v["result"] for v in vs])
            t2.append(
                {
                    "model": m,
                    "games": f"{len(done)} / {len(rs)}",
                    "wins": fmt_value(int(sum(v["won"] for v in vs))),
                    **{
                        k: fmt_value(mean_of(vs, k))
                        for k in ("attacker_p", "decisiveness", "loss_ratio")
                    },
                    "wdl": wdl,
                    "share": share,
                }
            )
            diffs: dict[str, list[float]] = {
                k: [] for k in ("won", "attacker_p", "decisiveness", "loss_ratio")
            }
            n = 0
            for r, v in zip(done, vs, strict=True):
                b = base_at.get((r["pack"], r["seed"]))
                if b is None:
                    continue
                n += 1
                bv = _side_view(b, kind)
                for k, xs in diffs.items():
                    if isinstance(v[k], (int, float)) and isinstance(bv[k], (int, float)):
                        xs.append(v[k] - bv[k])
            td.append({"model": m, "n": str(n), **{k: _diff_cell(x) for k, x in diffs.items()}})
        bvs = [_side_view(r, kind) for r in base_done]
        wdl, share = _wdl([v["result"] for v in bvs])
        t2.append(
            {
                "model": "script (baseline)",
                "games": f"{len(base_done)} / {len(base)}",
                "wins": fmt_value(int(sum(v["won"] for v in bvs))),
                **{
                    k: fmt_value(mean_of(bvs, k))
                    for k in ("attacker_p", "decisiveness", "loss_ratio")
                },
                "wdl": wdl,
                "share": share,
            }
        )
        out += [f"### Model as {kind}", ""]
        out += [
            "Sides in this seat: "
            + "; ".join(
                f"{p['label']} {p['attacker'] if kind == 'attacker' else p['defender']}"
                + (
                    ""
                    if p["named"]
                    else f" ({'first' if kind == 'attacker' else 'second'} side, no attacker named)"
                )
                for p in packs
            )
            + ".",
            "",
        ]
        out += text_table(t2, cols2)
        out += ["", f"Paired difference against the baseline, model as {kind}:", ""]
        out += text_table(td, colsd) if td else ["(no model games)"]
        out.append("")
    return out


def _model_against_model(packs: list[dict], pairs: list[dict]) -> list[str]:
    """Section 3: the attacker-by-defender matrix, W-D-L per pair and per model, and every
    model-against-model game."""
    out: list[str] = [
        "## 3. Model against model",
        "",
        (
            "Rows the model on the attacking side, columns the model defending; each cell is "
            "attacker wins – defender wins over its finished games, pooled over packs and "
            "seeds (other outcomes make up the rest of n)."
        ),
        "",
    ]
    pdone = [r for r in pairs if r.get("coverage") == "done"]
    atts = list(dict.fromkeys(r.get("attacker_model") for r in pairs))
    dfns = list(dict.fromkeys(r.get("defender_model") for r in pairs))
    if pairs:
        matrix = [
            "| attacker \\ defender | " + " | ".join(map(str, dfns)) + " |",
            "|" + "|".join("---" for _ in range(len(dfns) + 1)) + "|",
        ]
        for a in atts:
            cells = []
            for d in dfns:
                g = [
                    r
                    for r in pdone
                    if r.get("attacker_model") == a and r.get("defender_model") == d
                ]
                planned = [
                    r
                    for r in pairs
                    if r.get("attacker_model") == a and r.get("defender_model") == d
                ]
                if not planned:
                    cells.append("")
                    continue
                aw = sum(1 for r in g if r.get("winner") == r["attacker_side"])
                dw = sum(1 for r in g if r.get("winner") == r["defender_side"])
                cells.append(
                    f"{aw} – {dw} (n={len(g)}"
                    + (f" of {len(planned)})" if len(planned) != len(g) else ")")
                )
            matrix.append(f"| {a} | " + " | ".join(cells) + " |")
        out += matrix
        out += [
            "",
            (
                "W-D-L per pair (both side assignments pooled, read for the first-named "
                "model) and per model (each seat it held in a model-against-model game); "
                "a draw is a finished game no side won, and counts half in the share."
            ),
            "",
        ]
        seats = [
            (r, s, r.get(f"player_{s}"))
            for r in pdone
            for s in (r["attacker_side"], r["defender_side"])
        ]
        tp = []
        for key in dict.fromkeys(
            tuple(sorted((str(r.get("attacker_model")), str(r.get("defender_model")))))
            for r in pairs
        ):
            first = key[0]
            res = [
                _result(r, s)
                for r, s, m in seats
                if str(m) == first
                and tuple(sorted((str(r.get("attacker_model")), str(r.get("defender_model")))))
                == key
            ]
            if key[0] == key[1]:  # a model against itself: count each game once
                res = res[::2]
            planned = sum(
                1
                for r in pairs
                if tuple(sorted((str(r.get("attacker_model")), str(r.get("defender_model")))))
                == key
            )
            wdl, share = _wdl(res)
            tp.append(
                {
                    "pair": f"{key[0]} vs {key[1]}",
                    "games": f"{len(res)} / {planned}",
                    "wdl": wdl,
                    "share": share,
                }
            )
        out += text_table(
            tp,
            [
                ("pair", "pair"),
                ("games", "games (done / cells)"),
                ("wdl", "W-D-L (first model)"),
                ("share", "share first model (draw ½)"),
            ],
        )
        out.append("")
        tm = []
        for m in dict.fromkeys(str(m) for _, _, m in seats):
            wdl, share = _wdl([_result(r, s) for r, s, x in seats if str(x) == m])
            tm.append(
                {
                    "model": m,
                    "seats": str(sum(1 for *_, x in seats if str(x) == m)),
                    "wdl": wdl,
                    "share": share,
                }
            )
        out += text_table(
            tm,
            [
                ("model", "model"),
                ("seats", "seats played"),
                ("wdl", "W-D-L"),
                ("share", "share (draw ½)"),
            ],
        )
        out += ["", "Per pack:", ""]
        cols3 = [
            ("pack", "pack"),
            ("attacker_model", "attacker"),
            ("defender_model", "defender"),
            ("seed", "seed"),
            ("winner", "winner"),
            ("attacker_p", "attacker p"),
            ("decisiveness", "decisiveness"),
            ("attacker_losses", "attacker losses"),
            ("defender_losses", "defender losses"),
            ("attacker_level", "attacker level"),
            ("defender_level", "defender level"),
            ("judged", "verdict from"),
        ]
        t3 = []
        for r in sorted(
            pairs,
            key=lambda r: (
                [p["label"] for p in packs].index(r["pack"]),
                str(r.get("attacker_model")),
                str(r.get("defender_model")),
                r.get("seed") or 0,
            ),
        ):
            line = {
                k: fmt_value(r.get(k)) if r.get("coverage") == "done" else "·" for k, _ in cols3
            }
            line.update(
                pack=r["pack"],
                attacker_model=str(r.get("attacker_model")),
                defender_model=str(r.get("defender_model")),
                seed=str(r.get("seed")),
                winner=_outcome(r),
            )
            t3.append(line)
        out += text_table(t3, cols3)
    else:
        out.append("(no model-against-model cells)")
    return out


def _battle_balance(
    packs: list[dict], singles: list[dict], base: list[dict], pairs: list[dict]
) -> list[str]:
    """Section 4: per pack the baseline outcome and how often the attacking side won."""
    out: list[str] = [
        "",
        "## 4. Battle balance",
        "",
        (
            "Per pack, the script-against-script outcome per seed and how often the attacking "
            "side won the model games (finished games only). A pack where the attacker rarely "
            "wins, even with a model in command, is defender-favoured. Draws count every "
            'finished game (baseline and model) that no side won; "how decided" counts an '
            'ordinal pack\'s verdicts by how they fell ("-" for a weighted pack).'
        ),
        "",
    ]
    cols4 = [
        ("pack", "pack"),
        ("attacker", "attacker"),
        ("defender", "defender"),
        ("seeds", "seeds"),
        ("base_winner", "baseline winner"),
        ("base_p", "baseline attacker p"),
        ("base_dec", "baseline decisiveness"),
        ("m_att", "attacker won: model attacks"),
        ("m_def", "attacker won: model defends"),
        ("m_pair", "attacker won: model vs model"),
        ("m_all", "attacker won: all model games"),
        ("draws", "draws: all games"),
        ("how", "how decided: " + " / ".join(HOW)),
    ]
    t4 = []

    def rate(rs):
        d = [r for r in rs if r.get("coverage") == "done"]
        if not d:
            return "-"
        k = sum(1 for r in d if r.get("attacker_won"))
        return f"{k} / {len(d)} ({k / len(d):.0%})"

    def draws(rs):
        d = [r for r in rs if r.get("coverage") == "done"]
        if not d:
            return "-"
        k = sum(1 for r in d if r.get("winner") not in (r["attacker_side"], r["defender_side"]))
        return f"{k} / {len(d)} ({k / len(d):.0%})"

    for p in packs:
        bs = {r["seed"]: r for r in base if r["pack"] == p["label"]}
        ms = [r for r in singles if r["pack"] == p["label"]]
        ps = [r for r in pairs if r["pack"] == p["label"]]
        t4.append(
            {
                "pack": p["label"],
                "attacker": p["attacker"],
                "defender": p["defender"],
                "seeds": " / ".join(map(str, p["seeds"])),
                "base_winner": _seeded(bs, p["seeds"], _outcome) if bs else "no baseline",
                "base_p": _seeded(bs, p["seeds"], _done_only("attacker_p")) if bs else "-",
                "base_dec": (_seeded(bs, p["seeds"], _done_only("decisiveness")) if bs else "-"),
                "m_att": rate([r for r in ms if r["role_kind"] == "attacker"]),
                "m_def": rate([r for r in ms if r["role_kind"] == "defender"]),
                "m_pair": rate(ps),
                "m_all": rate(ms + ps),
                "draws": draws(list(bs.values()) + ms + ps),
                "how": _how_counts(list(bs.values()) + ms + ps),
            }
        )
    out += text_table(t4, cols4)
    return out


def _coverage_table(packs: list[dict], rows: list[dict]) -> list[str]:
    """Section 5: cells per grid directory by coverage."""
    out: list[str] = [
        "",
        "## 5. Coverage",
        "",
        (
            "Cells per grid directory, from its manifest and the cell logs: done (the log ends "
            "in a verdict), running (a log without a verdict written in the last "
            f"{FRESH_S:.0f} s), failed (stopped, died or went quiet), pending (no cell "
            "directory yet)."
        ),
        "",
    ]
    cols5 = [
        ("pack", "pack"),
        ("dir", "directory"),
        ("engine", "engine commit"),
        ("cells", "cells"),
        ("done", "done"),
        ("failed", "failed"),
        ("running", "running"),
        ("pending", "pending"),
        ("rejudged", "rejudged"),
        ("open", "not done"),
    ]
    t5 = []
    for p in packs:
        c = p["cells"]
        prs = [r for r in rows if r["pack"] == p["label"]]
        t5.append(
            {
                "pack": p["label"],
                "dir": Path(p["dir"]).name,
                "engine": p["engine_commit"] or "not recorded",
                "cells": str(sum(len(v) for v in c.values())),
                **{k: str(len(c[k])) for k in ("done", "failed", "running", "pending")},
                "rejudged": str(
                    sum(1 for r in prs if str(r.get("judged", "")).startswith("rejudge"))
                ),
                "open": ", ".join(
                    f"{n} ({k})" for k in ("failed", "running", "pending") for n in c[k]
                )
                or "-",
            }
        )
    out += text_table(t5, cols5)
    return out


def _method() -> list[str]:
    """The footer: how the paired difference and its interval are computed."""
    out: list[str] = [
        "",
        "---",
        "",
        (
            "Method. Each model game against the script is paired with the script-against-"
            "script game of the same pack and seed, read from the same side (the model's role); "
            "the difference is model minus baseline for win (0/1), attacker p, decisiveness and "
            "loss ratio. The interval is a percentile bootstrap of the mean difference: the "
            f"paired (pack, seed) units are resampled with replacement {BOOT_B:,} times "
            f"(random seed {BOOT_SEED}), and the 2.5th and 97.5th percentiles of the resampled "
            "means are shown. Units are treated as exchangeable across packs; with two seeds "
            "per pack the interval mostly reflects the spread between packs. Fewer than two "
            'units give no interval ("n<2"). Games without a finished verdict, and pairs '
            "whose baseline did not finish, are left out. Mean loss ratio is the mean of per-"
            "game ratios, not a ratio of sums."
        ),
        "",
    ]
    return out


CSV_FIRST = (
    "pack",
    "scenario",
    "cell",
    "model",
    "role",
    "role_kind",
    "seed",
    "coverage",
    "status",
    "judged",
    "engine_commit",
    "rejudge_commit",
    "attacker_side",
    "defender_side",
    "attacker_model",
    "defender_model",
    "winner",
    "attacker_won",
    "model_won",
    "attacker_p",
    "decisiveness",
    "minute",
    "attacker_level",
    "defender_level",
    "own_level",
    "enemy_level",
    "attacker_losses",
    "defender_losses",
    "own_losses",
    "enemy_losses",
    "loss_ratio",
    "consultations",
    "orders",
    "staff_questions",
    "mean_reply_s",
    "harness_errors",
    "wall_min",
    "jev_cost",
    "player_cost",
)


def cross_csv(dirs: list[Path]) -> str:
    """One flat row per cell over every grid: the fixed columns first, then each other
    measure (side-named losses and levels, pair per-side measures) in name order."""
    _, rows = cross_rows(dirs)
    rest = sorted({k for r in rows for k in r} - set(CSV_FIRST))
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=[*CSV_FIRST, *rest], lineterminator="\n")
    w.writeheader()
    for r in rows:
        w.writerow({k: ("" if v is None else v) for k, v in r.items()})
    return buf.getvalue()
