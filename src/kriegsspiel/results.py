"""Game results read from run logs: one row of measured outcomes per game, a grid
directory's manifest and cells, and the markdown tables the grid summary and the cross-pack
report are written in."""

from __future__ import annotations

import json
import os
import re
import statistics
import time
from pathlib import Path

FRESH_S = 180.0  # a log without a verdict written to this recently is a game still running
_ATTACKER_P = re.compile(r"attacker achieved p=([\d.]+)")
_LOSS = re.compile(r"^(\w+): ([\d,]+) men at the start, ([\d,]+) lost", re.MULTILINE)
_WALL = re.compile(r"; wall ([\d.]+) s, ")


def attacker_p(verdict: dict) -> float | None:
    """The umpire's probability that the attacker achieved its objective, from a verdict's
    rationale ("attacker achieved p=0.35"); None when the rationale gives none."""
    m = _ATTACKER_P.search(verdict.get("rationale", ""))
    return float(m.group(1)) if m else None


def last_record(log: Path) -> dict | None:
    """The last JSON record of a JSONL log, read from the tail (logs run to megabytes).
    Rejudge records, appended after a game by `umpire rejudge`, are skipped: the game's own
    closing record (its verdict) says whether it finished."""
    if not log.exists() or log.stat().st_size == 0:
        return None
    with log.open("rb") as fh:
        fh.seek(0, os.SEEK_END)
        size = fh.tell()
        chunk = 1 << 16
        buf = b""
        pos = size
        while pos > 0:
            step = min(chunk, pos)
            pos -= step
            fh.seek(pos)
            buf = fh.read(step) + buf
            lines = [x for x in buf.split(b"\n") if x.strip()]
            body = lines if pos == 0 else lines[1:]  # the first may be cut by the seek
            if pos == 0 or any(b'"type":"rejudge"' not in x for x in body):
                break
            chunk *= 4
    for line in reversed(lines if pos == 0 else (lines[1:] or lines)):
        try:
            rec = json.loads(line)
        except json.JSONDecodeError:
            continue  # a half-written last line
        if rec.get("type") != "rejudge":
            return rec
    return None


def verdict_summary(rec: dict | None) -> dict | None:
    """A verdict record as a grid manifest keeps it: the verdict without its rationale, plus
    the attacker's p (when the rationale gives one) and the tick."""
    if not rec or rec.get("type") != "verdict":
        return None
    v = dict(rec.get("verdict") or {})
    p = attacker_p(v)
    v.pop("rationale", None)
    if p is not None:
        v["attacker_p"] = p
    v["tick"] = rec.get("tick")
    return v


def game_row(cell_dir: Path, manifest_cell: dict | None = None) -> dict:
    """Measured outcomes of one game, from its run.jsonl (and stdout.txt for wall time)."""
    log = cell_dir / "run.jsonl"
    row: dict = {"cell": cell_dir.name}
    if not log.exists():
        return {**row, "status": "no log"}
    header: dict = {}
    verdict: dict | None = None
    rejudged: dict | None = None
    stopped: dict | None = None
    cmd: list[dict] = []
    orders: list[dict] = []
    jev_cost = 0.0
    jev_seen = False
    with log.open() as fh:
        for line in fh:
            if not line.strip():
                continue
            try:
                r = json.loads(line)
            except json.JSONDecodeError:
                continue
            t = r.get("type", "tick")
            if t == "header":
                header = r
            elif t == "tick":
                orders.extend(r.get("orders") or [])
            elif t == "commander":
                cmd.append(r)
            elif t == "verdict":
                verdict = r
            elif t == "rejudge" and r.get("verdict"):
                rejudged = r  # the latest wins
            elif t == "stopped":
                stopped = r
            for c in (r.get("jev") or []) if t != "rejudge" else []:  # the game's own
                if c.get("cost") is not None:
                    jev_cost += float(c["cost"])
                    jev_seen = True
    players = (header.get("play") or {}).get("players") or {}
    model_sides = [s for s, p in players.items() if p != "script"]
    side = model_sides[0] if len(model_sides) == 1 else None
    if len(model_sides) > 1:
        row.update(model=" vs ".join(players[s] for s in model_sides), role="pair")
    else:
        row.update(model=players.get(side, "script") if side else "script", role=side or "baseline")
    row["seed"] = header.get("seed")
    shown = rejudged or verdict
    if shown:
        v = shown.get("verdict") or {}
        row.update(
            status="done",
            winner=v.get("winner"),
            attacker_p=attacker_p(v),
            decisiveness=v.get("decisiveness"),
            minute=shown.get("tick"),
            how=v.get("how"),  # an ordinal verdict: break, possession, play-on, draw
            judged=(f"rejudge v{rejudged.get('umpire_version', '?')}" if rejudged else "game"),
            rejudge_commit=(rejudged or {}).get("replayed"),
        )
        for name, _start, lost in _LOSS.findall(shown.get("summary") or shown.get("account") or ""):
            row[f"lost_{name}"] = int(lost.replace(",", ""))
        for name, level in (v.get("achieved") or {}).items():
            row[f"achieved_{name}"] = level
    else:
        fresh = time.time() - log.stat().st_mtime < FRESH_S
        row.update(
            status="stopped" if stopped else ("running" if fresh else "incomplete"),
            winner="stopped" if stopped else "-",
            minute=(stopped or {}).get("tick"),
        )
    if side:
        row.update(_side_stats(side, cmd, orders))
    elif model_sides:  # a pair: each side's measures under a side suffix
        for s_ in model_sides:
            row["player_" + s_] = players[s_]
            row.update({f"{k}_{s_}": v for k, v in _side_stats(s_, cmd, orders).items()})
    else:
        row["orders"] = len(orders)
        row["staff_questions"] = sum(len(o.get("clarifications") or []) for o in orders)
    row["jev_cost"] = round(jev_cost, 4) if jev_seen else None
    wall = None
    so = cell_dir / "stdout.txt"
    if so.exists():
        m = _WALL.search(so.read_text(errors="replace"))
        if m:
            wall = float(m.group(1))
    if wall is None and manifest_cell and manifest_cell.get("wall_s") is not None:
        wall = float(manifest_cell["wall_s"])
    row["wall_min"] = round(wall / 60, 1) if wall is not None else None
    return row


def _side_stats(side: str, cmd: list[dict], orders: list[dict]) -> dict:
    mine = [c for c in cmd if c.get("side") == side]
    walls = [float(c.get("wall_s") or 0.0) for c in mine if not c.get("abandoned")]
    # claude reports cost_usd cumulative over a resumed session: the session's last value
    by_session: dict = {}
    for i, c in enumerate(mine):
        x = (c.get("meta") or {}).get("cost_usd")
        if x is not None:
            k = c.get("session_id") or (c.get("meta") or {}).get("session_id") or i
            by_session[k] = max(by_session.get(k, 0.0), float(x))
    own = [o for o in orders if o.get("side") == side]
    return {
        "consultations": len(mine),
        "orders": len(own),
        "staff_questions": sum(len(o.get("clarifications") or []) for o in own),
        "mean_reply_s": round(statistics.fmean(walls), 1) if walls else None,
        "harness_errors": sum(1 for c in mine if (c.get("meta") or {}).get("error")),
        "player_cost": round(sum(by_session.values()), 3) if by_session else None,
    }


def fmt_value(v) -> str:
    if v is None:
        return "-"
    if isinstance(v, bool):
        return str(v)
    if isinstance(v, int):
        return f"{v:,}"
    if isinstance(v, float):
        return f"{v:,.0f}" if abs(v) >= 100 else f"{v:.4g}"
    return str(v)


def table(rows: list[dict], cols: list[tuple[str, str]]) -> list[str]:
    """A markdown table of `rows` under the (key, heading) columns, values by `fmt_value`
    (the seed as it is)."""
    return text_table(
        [{k: str(r.get(k)) if k == "seed" else fmt_value(r.get(k)) for k, _ in cols} for r in rows],
        cols,
    )


def text_table(rows: list[dict], cols: list[tuple[str, str]]) -> list[str]:
    """A markdown table of `rows` whose values are already text ("" when missing)."""
    out = ["| " + " | ".join(h for _, h in cols) + " |", "|" + "|".join("---" for _ in cols) + "|"]
    out.extend("| " + " | ".join(str(r.get(k, "")) for k, _ in cols) + " |" for r in rows)
    return out


def mean_of(rows: list[dict], key: str) -> float | None:
    xs = [r[key] for r in rows if isinstance(r.get(key), (int, float))]
    return round(statistics.fmean(xs), 3) if xs else None


def load_grid(out: Path) -> tuple[dict, dict[str, dict], list[Path]]:
    """A grid directory's manifest config, its manifest cells by name (launch order), and the
    cell directories to read: the manifest's first, then any other directory with a log."""
    out = Path(out)
    config: dict = {}
    mcells: dict[str, dict] = {}
    mf = out / "manifest.json"
    if mf.exists():
        man = json.loads(mf.read_text())
        config = man.get("config") or {}
        for c in man.get("cells", []):
            mcells[c["name"]] = c
    dirs = [out / n for n in mcells if (out / n).is_dir()]
    dirs += sorted(
        d
        for d in out.iterdir()
        if d.is_dir()
        and not d.name.startswith(".")
        and d not in dirs
        and (d / "run.jsonl").exists()
    )
    return config, mcells, dirs
