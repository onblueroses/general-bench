"""Can a chat model do Jev's job? Replay recorded Jev requests (fixtures: state + questions +
Jev's answers) through `LlmDecisionsClient` and score the agreement, question by question.

    uv run python scripts/jev_vs_llm.py --model codex/gpt-6-luna --reasoning medium \
        --out runs/jev-vs-luna.md

Agreement per type: choice, the same option (and, as the staff reads it, the same option above
the 0.5 confidence line or both below it); noul, the same side of 0.5; score, the expected
levels rounded to the same level, with the mean absolute difference. Question families come
from the staff's naming (`a<i>` addressing, `a<i>_c<k>` clause attribution, `c<k>_*` clause
reading, `q<j>_kind`/`_obj`/... details, `k<i>`/`m<i>` checks, umpire questions by name).
Answers are recorded under `.local/llm-jev/<model>-<reasoning>/`, so a rerun is free.
"""

from __future__ import annotations

import argparse
import collections
import glob
import json
import re
import statistics as st
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from kriegsspiel.decisions_llm import LlmDecisionsClient  # noqa: E402 - needs the path above
from kriegsspiel.jev import DEFAULT_FIXTURES  # noqa: E402 - needs the path above

CONFIDENT = 0.5


def family(name: str) -> str:
    if re.fullmatch(r"a\d+", name):
        return "addressing (a<i>)"
    if re.fullmatch(r"a\d+_c\d+", name):
        return "clause attribution (a<i>_c<k>)"
    if re.fullmatch(r"o\d+", name):
        return "own clause (o<i>)"
    m = re.fullmatch(r"c\d+_(\w+)", name)
    if m:
        return f"clause {m.group(1)}"
    m = re.fullmatch(r"[qrh]\d*_(\w+?)(_\d+)?", name)
    if m:
        return f"detail {m.group(1)}"
    if re.fullmatch(r"[km]\d+", name):
        return "check (task vs words)"
    return f"umpire {name.split('_', maxsplit=1)[0]}"


def gate(name: str, jev: dict) -> bool | None:
    """Is this question's answer used at all, under Jev's reading of the gate it hangs on?
    None for an ungated question. Mirrors the staff: `forbid` behind `prohib`; `who`/`where`
    behind a confident, non-"none" `trig`; `then_kind`/`then_obj` behind `then`."""
    m = re.fullmatch(r"(c\d+)_(forbid|who|where)", name)
    if m:
        if m.group(2) == "forbid":
            return float(jev[f"{m.group(1)}_prohib"].get("noul") or 0) > 0.5
        t = jev[f"{m.group(1)}_trig"]
        return bool(t.get("choice") and t["choice"] != "none" and pmax(t) >= CONFIDENT)
    m = re.fullmatch(r"([qrh]\d*)_then_(kind|obj)", name)
    if m:
        return float(jev[f"{m.group(1)}_then"].get("noul") or 0) >= 0.5
    return None


def pmax(a: dict) -> float:
    if a.get("type") == "noul":
        p = float(a.get("noul") or 0.0)
        return max(p, 1 - p)
    pr = a.get("probabilities") or {}
    return max(pr.values()) if pr else float(a.get("confidence") or 0.0)


def compare(q: dict, jev: dict, llm: dict) -> dict:
    t = q["type"]
    if t == "choice":
        same = jev.get("choice") == llm.get("choice")
        jc = jev.get("choice") if pmax(jev) >= CONFIDENT else None
        lc = llm.get("choice") if pmax(llm) >= CONFIDENT else None
        return {
            "agree": same,
            "staff_agree": jc == lc,
            "jev": f"{jev.get('choice')} {pmax(jev):.2f}",
            "llm": f"{llm.get('choice')} {pmax(llm):.2f}",
        }
    if t == "noul":
        j, m = float(jev.get("noul") or 0.0), float(llm.get("noul") or 0.0)
        same = (j >= 0.5) == (m >= 0.5)
        return {
            "agree": same,
            "staff_agree": same,
            "jev": f"{j:.2f}",
            "llm": f"{m:.2f}",
            "diff": abs(j - m),
        }
    j, m = float(jev.get("score") or 0.0), float(llm.get("score") or 0.0)
    return {
        "agree": round(j) == round(m),
        "staff_agree": round(j) == round(m),
        "jev": f"{j:.2f}",
        "llm": f"{m:.2f}",
        "diff": abs(j - m),
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("--model", default="codex/gpt-6-luna")
    ap.add_argument("--reasoning", default="medium")
    ap.add_argument("--fixtures", default=str(DEFAULT_FIXTURES))
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--workers", type=int, default=12)
    ap.add_argument("--out", default="")
    ap.add_argument(
        "--tag", default="", help="suffix of the record directory (a prompt or shape variant)"
    )
    a = ap.parse_args(argv)

    files = sorted(glob.glob(f"{a.fixtures}/*.json"))
    if a.limit:
        files = files[: a.limit]
    rec_dir = (
        ROOT
        / ".local"
        / "llm-jev"
        / f"{a.model.replace('/', '-')}-{a.reasoning}{'-' + a.tag if a.tag else ''}"
    )
    client = LlmDecisionsClient(a.model, mode="record", reasoning=a.reasoning, fixture_dir=rec_dir)

    def one(path: str) -> dict:
        d = json.loads(Path(path).read_text())
        t0 = time.monotonic()
        try:
            ans = client.ask(d["state"], d["questions"])
        except Exception as e:  # noqa: BLE001 - a failed request is a row of its own, never a crash
            return {"path": path, "error": str(e)[:300]}
        rec = client.calls[-1]
        return {
            "path": path,
            "state": d["state"],
            "questions": d["questions"],
            "jev": d["response"]["answers"],
            "llm": {n: x.raw for n, x in ans.items()},
            "latency": round(time.monotonic() - t0, 1),
            "tokens": rec.input_tokens,
            "source": rec.source,
        }

    rows: list[dict] = []
    with ThreadPoolExecutor(max_workers=a.workers) as ex:
        futs = [ex.submit(one, f) for f in files]
        for i, fut in enumerate(as_completed(futs), 1):
            rows.append(fut.result())
            r = rows[-1]
            status = f"ERROR {r['error']}" if "error" in r else f"{r['latency']}s {r['tokens']} tok"
            print(
                f"[{i}/{len(files)}] {Path(r['path']).name} {status}",
                file=sys.stderr,
                flush=True,
            )

    # score
    by_type = collections.defaultdict(collections.Counter)
    by_family = collections.defaultdict(collections.Counter)
    diffs = collections.defaultdict(list)
    disagreements: list[dict] = []
    lat = [r["latency"] for r in rows if "latency" in r and r["source"] == "live"]
    toks = [r["tokens"] for r in rows if r.get("tokens")]
    errors = [r for r in rows if "error" in r]
    by_gated = collections.defaultdict(collections.Counter)
    for r in rows:
        if "error" in r:
            continue
        for n, q in r["questions"].items():
            c = compare(q, r["jev"][n], r["llm"][n])
            g = gate(n, r["jev"])
            if g:
                by_gated[family(n)]["n"] += 1
                by_gated[family(n)]["agree"] += c["agree"]
                by_gated[family(n)]["staff_agree"] += c["staff_agree"]
            for bucket in (by_type[q["type"]], by_family[family(n)]):
                bucket["n"] += 1
                bucket["agree"] += c["agree"]
                bucket["staff_agree"] += c["staff_agree"]
            if "diff" in c:
                diffs[q["type"]].append(c["diff"])
            if not c["staff_agree"]:
                disagreements.append(
                    {
                        "name": n,
                        "family": family(n),
                        "type": q["type"],
                        "instructions": q["instructions"][:220],
                        "order": (
                            r["state"].get("order")
                            or r["state"].get("situation")
                            or r["state"].get("account")
                            or ""
                        )[:200],
                        **c,
                    }
                )

    def pct(c: collections.Counter, k: str) -> str:
        return f"{100 * c[k] / c['n']:.0f}%" if c["n"] else "-"

    variant = f", {a.tag}" if a.tag else ""
    p90 = sorted(lat)[int(0.9 * (len(lat) - 1))] if lat else 0.0
    lines = [
        f"# Jev vs {a.model} ({a.reasoning} reasoning{variant}): agreement on recorded requests",
        "",
        f"{len(rows) - len(errors)} requests answered of {len(files)} fixtures "
        f"({len(errors)} failed); {sum(c['n'] for c in by_type.values())} questions. "
        + (f"Live latency median {st.median(lat):.0f} s, p90 {p90:.0f} s; " if lat else "")
        + (f"tokens per request median {st.median(toks):.0f}." if toks else ""),
        "",
        (
            "Agreement = the same answer (choice: same option; noul: same side of 0.5; score: "
            "same rounded level). Staff agreement = what the staff would do with it is the same "
            "(choice: the same option above the 0.5 line, or both below it)."
        ),
        "",
        "| type | questions | agree | staff agree | mean abs diff |",
        "|---|---|---|---|---|",
    ]
    for t, c in sorted(by_type.items()):
        d = f"{st.mean(diffs[t]):.2f}" if diffs.get(t) else "-"
        lines.append(f"| {t} | {c['n']} | {pct(c, 'agree')} | {pct(c, 'staff_agree')} | {d} |")
    lines += ["", "| family | questions | agree | staff agree |", "|---|---|---|---|"]
    for fam, c in sorted(by_family.items(), key=lambda kv: -kv[1]["n"]):
        lines.append(f"| {fam} | {c['n']} | {pct(c, 'agree')} | {pct(c, 'staff_agree')} |")
    lines += [
        "",
        (
            "Gated families counted only where the staff reads the answer (under Jev's reading "
            "of the gate: `forbid` when the clause is a prohibition, `who`/`where` when it names "
            "a trigger, `then_*` when a sequel follows):"
        ),
        "",
        "| family (gated) | questions used | agree | staff agree |",
        "|---|---|---|---|",
    ]
    for fam, c in sorted(by_gated.items(), key=lambda kv: -kv[1]["n"]):
        lines.append(f"| {fam} | {c['n']} | {pct(c, 'agree')} | {pct(c, 'staff_agree')} |")
    lines += [
        "",
        f"## Staff-level disagreements ({len(disagreements)})",
        "",
        "| family | order / account | question | Jev | model |",
        "|---|---|---|---|---|",
    ]
    for d in disagreements[:120]:
        order, question = d["order"].replace("|", "/"), d["instructions"].replace("|", "/")
        lines.append(f"| {d['family']} | {order} | {question} | {d['jev']} | {d['llm']} |")
    if errors:
        lines += ["", "## Failed requests", ""] + [
            f"- `{Path(e['path']).name}`: {e['error']}" for e in errors
        ]
    text = "\n".join(lines) + "\n"
    if a.out:
        Path(a.out).write_text(text)
        print(f"wrote {a.out}", file=sys.stderr)
    else:
        print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
