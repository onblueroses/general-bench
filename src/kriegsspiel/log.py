"""Run log: JSONL, a header line then one line per tick with the state hash, events,
orders (with the tasks the staff produced), messages and umpire answers."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .types import (
    Condition,
    ConditionKind,
    Manner,
    OnContact,
    Ref,
    RefKind,
    Task,
    TaskKind,
    UnitState,
)


def ref_to_json(r: Ref | None) -> dict | None:
    if r is None:
        return None
    return {"kind": r.kind.value, "name": r.name, "point": list(r.point) if r.point else None}


def ref_from_json(d: dict | None) -> Ref | None:
    if d is None:
        return None
    p = d.get("point")
    return Ref(
        kind=RefKind(d["kind"]), name=d.get("name"), point=(float(p[0]), float(p[1])) if p else None
    )


def cond_to_json(c: Condition | float | None) -> Any:
    if c is None or isinstance(c, int | float):
        return c
    d = {"kind": c.kind.value, "subject": ref_to_json(c.subject), "at": c.at}
    if c.place is not None:  # only when present, so older logs hash as before
        d["place"] = ref_to_json(c.place)
    return d


def cond_from_json(d: Any) -> Condition | float | None:
    if d is None or isinstance(d, int | float):
        return d
    return Condition(
        kind=ConditionKind(d["kind"]),
        subject=ref_from_json(d.get("subject")),
        at=d.get("at"),
        place=ref_from_json(d.get("place")),
    )


def task_to_json(t: Task) -> dict:
    d = {
        "kind": t.kind.value,
        "formation": t.formation,
        "objective": ref_to_json(t.objective),
        "route": [ref_to_json(r) for r in t.route],
        "state": t.state.value if t.state else None,
        "start": cond_to_json(t.start),
        "on_contact": t.on_contact.value,
        "until": cond_to_json(t.until),
        "manner": t.manner.value,
        "source_text": t.source_text,
        "issued_at": t.issued_at,
        "received_at": t.received_at,
    }
    if t.then is not None:  # only when present, so logs without sequels hash as before
        d["then"] = task_to_json(t.then)
    if t.tentative:
        d["tentative"] = True
    if t.forbid:
        d["forbid"] = list(t.forbid)
    return d


def task_from_json(d: dict) -> Task:
    until = cond_from_json(d.get("until"))
    return Task(
        kind=TaskKind(d["kind"]),
        formation=d["formation"],
        objective=ref_from_json(d.get("objective")),
        route=[r for r in (ref_from_json(x) for x in d.get("route", [])) if r],
        state=UnitState(d["state"]) if d.get("state") else None,
        start=cond_from_json(d.get("start")),
        on_contact=OnContact(d.get("on_contact", "engage")),
        until=until if isinstance(until, Condition) else None,
        manner=Manner(d.get("manner", "measured")),
        source_text=d.get("source_text", ""),
        issued_at=d.get("issued_at"),
        received_at=d.get("received_at"),
        then=task_from_json(d["then"]) if d.get("then") else None,
        tentative=bool(d.get("tentative", False)),
        forbid=list(d.get("forbid") or []),
    )


def dumps(obj: Any) -> str:
    """Canonical JSON (sorted keys, no whitespace); floats keep their exact repr."""
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


class RunLog:
    """Collects records in memory and, if given a path, appends them as JSONL."""

    def __init__(self, path: str | Path | None = None):
        self.path = Path(path) if path else None
        self.header: dict | None = None
        self.records: list[dict] = []
        self.extra: list[dict] = []
        if self.path:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text("")

    def write_header(self, header: dict) -> None:
        self.header = {"type": "header", **header}
        self._emit(self.header)

    def write_tick(self, record: dict) -> None:
        rec = {"type": "tick", **record}
        self.records.append(rec)
        self._emit(rec)

    def write_record(self, kind: str, record: dict) -> None:
        """A non-tick record (e.g. the verdict); `read_log` leaves these out of the ticks."""
        rec = {"type": kind, **record}
        self.extra.append(rec)
        self._emit(rec)

    def orders(self) -> list[dict]:
        """The orders written in the ticks, in order, each with the tasks the staff read."""
        return [o for r in self.records for o in r.get("orders", [])]

    def jev_call_count(self) -> int:
        """Jev calls made in the run: in the ticks and in the other records (the verdict)."""
        return sum(len(r.get("jev", [])) for r in self.records + self.extra)

    def _emit(self, rec: dict) -> None:
        if self.path:
            with self.path.open("a") as fh:
                fh.write(dumps(rec) + "\n")


def read_records(path: str | Path) -> list[dict]:
    """Every record of a log, in order (header, ticks, verdict)."""
    return [json.loads(line) for line in Path(path).read_text().splitlines() if line.strip()]


def read_log(path: str | Path) -> tuple[dict, list[dict]]:
    """(header, tick records); other record types (the verdict) are left out."""
    header, ticks = {}, []
    for rec in read_records(path):
        if rec.get("type") == "header":
            header = rec
        elif rec.get("type", "tick") == "tick":
            ticks.append(rec)
    return header, ticks


def jev_calls(records: list[dict]) -> list[dict]:
    """The Jev call records of a log, in the order they were made. Rejudge records (appended
    after the game by `umpire rejudge`) are not part of the game and are left out."""
    return [c for r in records if r.get("type") != "rejudge" for c in r.get("jev", [])]
