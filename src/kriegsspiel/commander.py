"""Army commanders: something that reads the general's brief and answers with prose orders,
or with nothing.

    Commander.orders(brief, now) -> str | None

Every commander derives from `CommanderBase`, which gives the rest of the `Commander` protocol
its defaults (answers at once, no memory, woken at no fixed minutes, nothing to close).

- `LLMCommander(player, persona, memory=True)`: a `kriegsspiel.players` player (`claude -p`
  or `codex exec`, effort pinned high, the players' clean environment). With memory (the
  default) the general keeps one conversation for the whole game (`HarnessSession`: `claude -p
  --session-id/--resume`, `codex exec` then `codex exec resume <id>`): the first message
  carries the persona and the full brief, later ones only the update brief. `memory=False` is
  the one-shot ablation: a fresh process per consultation, the persona as the system prompt
  every time, the full brief every time. The reply is plain prose.
- `ScriptedCommander(script)`: fixed `(minute, text)` orders, each given at the first
  consultation at or after its minute (the play loop also wakes it at those minutes).
- `NullCommander`: never orders.
- `ReplayCommander(records)`: serves the replies of a run log with no model call, and fails
  loudly (`CommanderReplayMismatch`) when the brief or the minute differs from the logged one.

`realtime = True` marks a commander the play loop calls in a thread while the simulation keeps
running; the others answer at once. `memory` asks the narrator for update briefs after the
first. After each call `last` holds what the play loop logs (system, wall seconds, the player's
meta with token counts).
"""

from __future__ import annotations

import contextlib
import dataclasses
import re
import subprocess
import time
import uuid
from collections.abc import Collection
from pathlib import Path
from typing import Any, Protocol

from .players import Player, Reply, jail

SYSTEM = (
    "You are playing a free Kriegsspiel, the war game of 1824, as the commanding general of "
    "an army. Stay in your role and in your century. Your reply is handed to your staff and "
    "carried by aides as you write it, so write nothing but orders: each order on its own "
    "line, each beginning with the name of the subordinate (or formation) it is for, in plain "
    "prose, no headings, no lists, no markdown, no commentary, no questions to the umpire. "
    "If you wish to give no orders now, reply exactly: No orders."
)
NO_ORDERS = re.compile(r"^\W*no orders\W*$", re.IGNORECASE)
MIN_ORDER_WORDS = 3  # a line shorter than this is a salutation or a signature, not an order
LIST_MARK = re.compile(r"^\s*(?:[-*•]+|\d+[.)])\s+")


class Commander(Protocol):
    name: str
    realtime: bool  # consulted in a thread while the sim runs on (when the sim is paced)
    memory: bool  # keeps the conversation, so later briefs are updates
    last: dict[str, Any]  # what the play loop logs about the last call

    @property
    def wake_at(self) -> Collection[int]: ...  # minutes it is consulted at whatever happens

    def orders(self, brief: str, now: int) -> str | None: ...

    def reply_at(self, now: int) -> int | None: ...

    def close(self) -> None: ...


class CommanderBase:
    """The `Commander` defaults: answers at once, no memory, no fixed minutes."""

    name = "commander"
    realtime = False
    memory = False
    wake_at: Collection[int] = ()

    def __init__(self) -> None:
        self.last: dict[str, Any] = {}

    def orders(self, brief: str, now: int) -> str | None:
        raise NotImplementedError

    def reply_at(self, now: int) -> int | None:
        """The sim minute the reply just given reaches the play loop (None: never)."""
        return now

    def close(self) -> None:
        """Release what the commander holds for the game (a harness session's jail)."""


class CommanderReplayMismatch(RuntimeError):
    pass


class GeneralUnreachable(Exception):
    """The harness failed every retry: the game stops rather than play on with a silent
    general (the grid marks the cell failed and --resume reruns it)."""


def split_orders(text: str | None) -> list[str]:
    """The separate orders in a reply: one per line, list marks and markdown emphasis
    stripped, lines under `MIN_ORDER_WORDS` words dropped; "No orders" gives none."""
    if text is None or NO_ORDERS.match(text.strip() or "no orders"):
        return []
    out = []
    for raw in text.splitlines():
        line = LIST_MARK.sub("", raw).replace("**", "").strip()
        if len(line.split()) < MIN_ORDER_WORDS or NO_ORDERS.match(line):
            continue
        out.append(line)
    return out


class NullCommander(CommanderBase):
    name = "null"

    def orders(self, brief: str, now: int) -> str | None:
        self.last = {"wall_s": 0.0, "meta": {}}
        return None


class ScriptedCommander(CommanderBase):
    name = "script"

    def __init__(self, script: list[tuple[int, str]]):
        super().__init__()
        self.script = sorted(((int(m), t) for m, t in script), key=lambda x: x[0])
        self._given = 0

    @property
    def wake_at(self) -> list[int]:
        return sorted({m for m, _ in self.script})

    def orders(self, brief: str, now: int) -> str | None:
        due = []
        while self._given < len(self.script) and self.script[self._given][0] <= now:
            due.append(self.script[self._given][1])
            self._given += 1
        self.last = {"wall_s": 0.0, "meta": {}}
        return "\n".join(due) if due else None


class HarnessSession:
    """One persistent conversation with a player for a whole game. A command-line player runs
    every turn in the same jail directory outside the home tree (claude keys its sessions by
    working directory), with the one-shot players' isolation; the API route keeps the
    conversation as its own message list. `close()` removes the jail."""

    # A turn the harness loses (HTTP 429 after codex's own reconnects, a claude turn flagged
    # is_error, a non-zero exit, a timeout, an HTTP error on the API route) is retried with
    # growing waits before the general is declared unreachable, so a lost reply never passes
    # as "no orders".
    RETRIES = 12
    BACKOFF_S = 15.0
    MAX_BACKOFF_S = 300.0

    def __init__(self, player: Player):
        self.player = player
        self.kind = getattr(player, "harness", None)
        if self.kind not in ("claude", "codex", "api"):
            raise TypeError(f"no session support for {type(player).__name__}")
        self.session_id: str | None = None
        self.turns = 0
        self.messages: list[dict] = []  # the API route keeps the conversation itself
        self._stack = contextlib.ExitStack()
        self.cwd: Path | None = None
        if self.kind != "api":
            self.cwd = self._stack.enter_context(jail())

    def close(self) -> None:
        self._stack.close()

    def send(self, system: str, prompt: str) -> Reply:
        last = "?"
        for attempt in range(self.RETRIES + 1):
            if attempt:
                time.sleep(min(self.BACKOFF_S * 2 ** (attempt - 1), self.MAX_BACKOFF_S))
            try:
                reply = self._once(system, prompt)
            except (subprocess.SubprocessError, OSError, RuntimeError) as e:
                last = f"{type(e).__name__}: {str(e)[:300]}"
                continue
            why = self._lost(reply)
            if why is None:
                if attempt:
                    reply.meta["attempts"] = attempt + 1
                return reply
            last = why
        raise GeneralUnreachable(
            f"{getattr(self.player, 'name', '?')}: {self.RETRIES + 1} attempts failed; last: {last}"
        )

    def _once(self, system: str, prompt: str) -> Reply:
        turn = self.turns
        if self.kind == "api":
            reply = self._api(system, prompt)
            return self._stamp(reply, turn, turn > 0, messages=len(self.messages))
        resumed = self.session_id is not None
        reply = (
            self._claude(system, prompt) if self.kind == "claude" else self._codex(system, prompt)
        )
        return self._stamp(reply, turn, resumed)

    def _stamp(self, reply: Reply, turn: int, resumed: bool, **extra) -> Reply:
        """The reply with its place in the session in its meta."""
        meta = {**reply.meta, "turn": turn, "resumed": resumed, "session_id": self.session_id}
        return dataclasses.replace(reply, meta={**meta, **extra})

    @staticmethod
    def _lost(reply: Reply) -> str | None:
        """Why this reply is the harness failing rather than the general answering."""
        m = reply.meta
        if m.get("exit") not in (None, 0):
            return f"exit {m['exit']}: {(m.get('stderr') or '')[-300:]}"
        if m.get("is_error"):
            return f"is_error: {reply.text[:300]}"
        if not reply.text.strip() and ("429" in (m.get("stderr") or "") or m.get("parse_error")):
            return f"empty reply: {(m.get('stderr') or '')[-300:]}"
        return None

    def _api(self, system: str, prompt: str) -> Reply:
        """Stateless chat API: the session is the message list, resent whole each turn."""
        if not self.messages:
            self.messages.append({"role": "system", "content": system})
            self.session_id = f"api-{uuid.uuid4()}"
        self.messages.append({"role": "user", "content": prompt})
        reply = self.player.chat(self.messages)
        self.messages.append({"role": "assistant", "content": reply.text})
        self.turns += 1
        return reply

    def _claude(self, system: str, prompt: str) -> Reply:
        sid = self.session_id or str(uuid.uuid4())
        reply = self.player.call(
            system, prompt, self.cwd, session_id=sid, resume=self.session_id is not None
        )
        if reply.meta["exit"] == 0 and not reply.meta.get("is_error"):
            self.session_id = reply.session_id or sid
            self.turns += 1
        return reply

    def _codex(self, system: str, prompt: str) -> Reply:
        p = self.player
        first = self.session_id is None
        reply = p.call(
            p.first_message(system, prompt) if first else prompt,
            self.cwd,
            out_name=f"last-{self.turns}.txt",
            resume_id=self.session_id,
            ephemeral=False,
        )
        if reply.meta["exit"] == 0:
            if first and reply.session_id:
                self.session_id = reply.session_id
            self.turns += 1
        return reply


class LLMCommander(CommanderBase):
    """A `kriegsspiel.players.Player` as the general. `persona` is the narrator's persona
    block (`Narrator.persona(side)`); it is the system prompt of every call (after the fixed
    `SYSTEM` rule), and stripped from the head of the first brief so it is not sent twice."""

    realtime = True

    def __init__(self, player: Player, persona: str, system: str = SYSTEM, memory: bool = True):
        super().__init__()
        if dataclasses.is_dataclass(player):  # effort pinned high; the roster stays untouched
            pins = {k: "high" for k in ("effort", "reasoning") if hasattr(player, k)}
            player = dataclasses.replace(player, **pins)  # type: ignore[type-var]
        self.player = player
        self.persona = persona
        self.system = f"{system}\n\n{persona}" if persona else system
        self.name = getattr(player, "name", "llm")
        self.memory = memory
        self.session: HarnessSession | None = None

    def close(self) -> None:
        if self.session is not None:
            self.session.close()

    def prompt_for(self, brief: str) -> str:
        if self.persona and brief.startswith(self.persona):
            return brief[len(self.persona) :].lstrip()
        return brief

    def orders(self, brief: str, now: int) -> str | None:
        prompt = self.prompt_for(brief)
        t0 = time.monotonic()
        try:
            if self.memory:
                if self.session is None:
                    self.session = HarnessSession(self.player)
                reply = self.session.send(self.system, prompt)
            else:
                reply = self.player.act(self.system, prompt)
            text, meta, wall = reply.text, dict(reply.meta), reply.latency_s
        except (OSError, RuntimeError, subprocess.SubprocessError) as e:  # a silent general
            text, meta, wall = "", {"error": f"{type(e).__name__}: {e}"}, time.monotonic() - t0
        self.last = {
            "wall_s": round(float(wall), 3),
            "meta": meta,
            "system": self.system,
            "prompt": prompt,
            "player": self.name,
            "memory": self.memory,
            "session_id": meta.get("session_id"),
            "model": getattr(self.player, "model", None),
        }
        text = (text or "").strip()
        if not text or NO_ORDERS.match(text):
            return None
        return text


class ReplayCommander(CommanderBase):
    """Replies of a side from a run log's `commander` records, in order. The brief and the
    minute of each consultation must equal the logged ones, and each reply reaches the play
    loop at the minute it arrived in the logged game."""

    def __init__(self, records: list[dict], side: str | None = None):
        super().__init__()
        self.records = [r for r in records if side is None or r.get("side") == side]
        self._next = 0
        self.name = self.records[0].get("commander", "replay") if self.records else "replay"
        self.memory = bool(self.records[0].get("memory")) if self.records else False

    @property
    def remaining(self) -> int:
        return len(self.records) - self._next

    @property
    def wake_at(self) -> list[int]:
        """The minutes a scripted commander was woken at, so they are consulted again."""
        return sorted({r["consulted_at"] for r in self.records if r.get("trigger") == "script"})

    def orders(self, brief: str, now: int) -> str | None:
        if self._next >= len(self.records):
            raise CommanderReplayMismatch(f"consultation at minute {now} is not in the log")
        rec = self.records[self._next]
        if rec["consulted_at"] != now:
            raise CommanderReplayMismatch(
                f"consultation {self._next} at minute {now}, logged at {rec['consulted_at']}"
            )
        if rec["brief"] != brief:
            raise CommanderReplayMismatch(
                f"brief of consultation {self._next} (minute {now}) differs from the log"
            )
        self._next += 1
        self.last = {
            k: v
            for k, v in rec.items()
            if k in ("wall_s", "meta", "system", "player", "model", "memory", "session_id")
        }
        self.last["arrived_at"] = rec.get("arrived_at")
        return rec.get("reply")

    def reply_at(self, now: int) -> int | None:
        return self.last.get("arrived_at")


__all__ = [
    "SYSTEM",
    "Commander",
    "CommanderBase",
    "CommanderReplayMismatch",
    "HarnessSession",
    "LLMCommander",
    "NullCommander",
    "ReplayCommander",
    "ScriptedCommander",
    "split_orders",
]
