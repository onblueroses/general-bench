"""The play loop: commanders (LLM generals, scripts, the doctrine bot) consulted in near real
time while the battle runs, and the games built on it.

    sim = build("data/plain-crossroads", seed=1, mode="record", log="runs/x.jsonl")
    res = play(sim, {"red": LLMCommander(...), "blue": ScriptedCommander(...)})
    res = play_game({"red": "opus", "blue": "script"}, mode="record", log="runs/x/run.jsonl")
    res = run_script("data/plain-crossroads", "stub")   # both sides play the pack's script
"""

from __future__ import annotations

import time
from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .bot import BotCommander, doctrine_for, is_bot
from .build import build
from .clock import at_minute, clock
from .commander import (
    Commander,
    LLMCommander,
    NullCommander,
    ScriptedCommander,
    split_orders,
)
from .jev import JevError, ReplayMismatch
from .log import RunLog
from .narrator import FIRST_CONTACT, Narrator, report_whys
from .players import ROSTER
from .scenario import DEFAULT_END, DEFAULT_SCENARIO, load_meta, load_script, load_sides, resolve
from .sim import Sim
from .types import MessageKind, Verdict
from .verdict import play_on_notice

CADENCE_MIN = 15  # the general is consulted every 15 simulated minutes
TRIGGER_GAP_MIN = 5  # a report-triggered consultation at most once per 5 sim minutes
REPLY_COOLDOWN_MIN = 5  # no cadence consultation within 5 sim minutes of the last reply
# None: the sim waits for the general, so every model gets the same decisions whatever its
# speed; a number paces the sim at that many sim minutes per wall second while he thinks
DEFAULT_SPEED: float | None = None
DEFAULT_SEED = 1


@dataclass
class GameResult:
    sim: Sim
    verdict: Verdict
    wall_s: float
    consultations: list[dict] = field(default_factory=list)  # the logged commander records
    cost: float = 0.0
    calls: int = 0  # Jev calls

    @property
    def orders(self) -> list[dict]:
        """The logged orders, with the tasks the staff read and the questions it sent back."""
        return self.sim.log.orders() if self.sim.log is not None else []


@dataclass
class Consultation:
    side: str
    consulted_at: int
    trigger: str
    brief: str
    commander: Commander
    future: Future | None = None  # a realtime general thinking in a thread
    due_at: int | None = None  # a reply given at once: the minute it reaches the loop
    reply: str | None = None
    arrived_at: int | None = None
    t0: float = 0.0
    last: dict = field(default_factory=dict)

    def ready(self, now: int) -> bool:
        if self.future is not None:
            return self.future.done()
        return self.due_at is not None and now >= self.due_at

    def take(self, reply: str | None) -> None:
        """The reply, and what the commander logged with it."""
        self.reply = reply
        self.last = dict(self.commander.last or {})

    def record(self, start: str) -> dict:
        """The `commander` record of the run log."""
        last = self.last or {}
        return {
            "side": self.side,
            "commander": self.commander.name,
            "consulted_at": self.consulted_at,
            "consulted_clock": clock(start, self.consulted_at),
            "trigger": self.trigger,
            "brief": self.brief,
            "brief_words": len(self.brief.split()),
            "reply": self.reply,
            "orders": split_orders(self.reply),
            "arrived_at": self.arrived_at,
            "arrived_clock": clock(start, self.arrived_at) if self.arrived_at is not None else None,
            "wall_s": last.get("wall_s", 0.0),
            "meta": last.get("meta", {}),
            "memory": bool(self.commander.memory),
            **{k: last[k] for k in ("system", "player", "model", "session_id") if k in last},
        }


@dataclass
class _SideState:
    wake_at: frozenset[int] = frozenset()  # the commander's own minutes
    next_cadence: int = 0
    last_consult: int | None = None
    last_brief: int = 0
    trigger: str | None = None
    pending: Consultation | None = None
    last_reply: int | None = None  # the minute his last reply arrived


def play(
    sim: Sim,
    commanders: dict[str, Commander],
    cadence_min: int = CADENCE_MIN,
    speed: float | None = DEFAULT_SPEED,
    *,
    narrator: Narrator | None = None,
    end: str | None = None,
    trigger_gap_min: int = TRIGGER_GAP_MIN,
    out=print,
    stop_at: int | None = None,
    on_step=None,
) -> GameResult:
    """Play the battle with `commanders` (side -> Commander, consulted in this side order).

    Each general is consulted every `cadence_min` sim minutes, at a scripted commander's own
    minutes, and when a report of first contact, a rout or a staff question reaches his hq
    (at most once per `trigger_gap_min`). A `realtime` commander thinks in a thread while the
    sim keeps stepping at `speed` sim minutes per wall second; his reply is submitted at the
    sim minute at which it arrived (logged as `arrived_at`). `speed=None` waits for the model.
    Replies that arrive in the same minute are submitted in side order, so the order of the
    staff's Jev calls does not depend on thread timing. A slot that passes while the general
    is still thinking is skipped. Stops when the umpire rules the battle over or at `end`
    (default: the scenario's end clock), then asks the verdict.

    If Jev fails for good mid-game (an HTTP error after the client's retries, e.g. the key's
    spending cap), the game stops cleanly: the half-run tick is not logged, a `stopped` record
    names the tick and the reason, and no verdict is asked. `stop_at` (a tick) is how
    `replay.replay_game` ends a stopped game at the same place. A replay mismatch is never
    swallowed."""
    return _Play(
        sim, commanders, cadence_min, speed, narrator, end, trigger_gap_min, out, stop_at, on_step
    ).run()


class _Play:
    """One game of `play`: the consultation schedule of every side and the minute loop."""

    def __init__(
        self,
        sim: Sim,
        commanders: dict[str, Commander],
        cadence_min: int,
        speed: float | None,
        narrator: Narrator | None,
        end: str | None,
        trigger_gap_min: int,
        out,
        stop_at: int | None,
        on_step,
    ):
        self.sim = sim
        self.commanders = commanders
        self.cadence_min = cadence_min
        self.speed = speed
        self.narrator = narrator or sim.narrator
        if self.narrator is None:
            raise ValueError("play needs a narrator (build() attaches one)")
        self.trigger_gap_min = trigger_gap_min
        self.out = out
        self.stop_at = stop_at
        self.on_step = on_step
        self.start = sim.clock_start
        self.limit = int(at_minute(self.start, end or sim.end_clock or DEFAULT_END))
        if sim.ordinal is not None:  # the judge ends it, at the latest when the
            self.limit = sim.ordinal.last_minute  # play-on after the pack's end hour runs out
        self.sides = [s for s in commanders if s in sim.forces.sides()]
        self.st = {s: _SideState(wake_at=frozenset(commanders[s].wake_at)) for s in self.sides}
        self.ready: list[Consultation] = []
        self.records: list[dict] = []
        self.pool = ThreadPoolExecutor(
            max_workers=max(1, len(self.sides)), thread_name_prefix="general"
        )
        self.pace: list[float] | None = None  # [wall anchor, steps paced since]
        self.stopped: str | None = None

    # -- the minute loop
    def run(self) -> GameResult:
        t_start = time.monotonic()
        sim = self.sim
        try:
            while not sim.over and sim.now < self.limit:
                if self._minute():
                    continue  # a reply came in while pacing: collect it at this minute
                self._flush()
                if self.stop_at is not None and sim.now >= self.stop_at:  # the logged game
                    self.stopped = f"stopped at tick {self.stop_at}, as the logged game"
                    break
                try:
                    sim.step()
                except JevError as e:
                    if isinstance(e, ReplayMismatch):
                        raise
                    self.stopped = f"{type(e).__name__}: {str(e)[:300]}"
                    break
                self._note_triggers()
                if self.on_step is not None:
                    self.on_step(sim)
            self._flush()
            self._abandon()
        finally:
            self.pool.shutdown(wait=True)
            for com in self.commanders.values():
                com.close()
        if self.stopped is not None:
            if sim.log is not None:
                sim.log.write_record("stopped", {"tick": sim.now, "reason": self.stopped})
            if self.out is not None:
                self.out(
                    f"Game stopped at {clock(self.start, sim.now)} (tick {sim.now}): {self.stopped}"
                )
            verdict = Verdict(winner="undecided", rationale=f"game stopped: {self.stopped}")
        else:
            verdict = sim.verdict()
        client = getattr(sim.staff, "client", None)
        return GameResult(
            sim=sim,
            verdict=verdict,
            wall_s=time.monotonic() - t_start,
            consultations=self.records,
            cost=getattr(client, "total_cost", 0.0),
            calls=sim.log.jev_call_count() if sim.log is not None else 0,
        )

    def _minute(self) -> bool:
        """Collect the replies that are in, consult whoever is due, and pace the sim while a
        general thinks; True when a reply arrived while pacing (the minute is run again)."""
        now = self.sim.now
        for side in self.sides:
            c = self.st[side].pending
            if c is not None and c.ready(now):
                self._finish(c, now)
        for side in self.sides:
            if self.st[side].pending is None:
                why = self._due(side, now)
                if why:
                    self._consult(side, now, why)
        pending = [self.st[x].pending for x in self.sides]
        live = [c for c in pending if c is not None and c.future is not None]
        if live and self.speed:
            if self.pace is None:  # anchored when the first general began to think
                self.pace = [min(c.t0 for c in live), 0.0]
            remaining = self.pace[0] + (self.pace[1] + 1.0) / self.speed - time.monotonic()
            if remaining > 0:
                done, _ = wait(
                    [c.future for c in live], timeout=remaining, return_when=FIRST_COMPLETED
                )
                if done:
                    return True
            self.pace[1] += 1.0
        elif not live:
            self.pace = None
        return False

    # -- the schedule
    def _due(self, side: str, now: int) -> str | None:
        s = self.st[side]
        if s.last_consult is not None and now <= s.last_consult:
            return None  # never twice in one minute
        if s.last_reply is not None and now <= s.last_reply:
            return None  # his orders of this minute are not yet written: the brief lacks them
        if now in s.wake_at:
            return "script"
        if s.trigger and (s.last_consult is None or now >= s.last_consult + self.trigger_gap_min):
            return s.trigger  # every trigger is a report of substance
        cool = s.last_reply is not None and now < s.last_reply + REPLY_COOLDOWN_MIN
        if now >= s.next_cadence and not cool:
            return "cadence"  # a cadence slot waits out the cooldown; it is not skipped
        return None

    def _skip_passed_slots(self, s: _SideState, now: int) -> None:
        if now >= s.next_cadence:
            s.next_cadence = (now // self.cadence_min + 1) * self.cadence_min

    def _consult(self, side: str, now: int, why: str) -> None:
        s = self.st[side]
        com = self.commanders[side]
        judge = self.sim.ordinal
        brief = self.narrator.brief(
            self.sim.picture(side),
            side,
            since=s.last_brief,
            update=bool(com.memory),
            notice=play_on_notice(judge) if judge is not None else "",
        )
        s.last_brief, s.last_consult, s.trigger = now, now, None
        self._skip_passed_slots(s, now)
        c = Consultation(side=side, consulted_at=now, trigger=why, brief=brief, commander=com)
        s.pending = c
        if com.realtime and self.speed is not None:
            c.t0 = time.monotonic()
            c.future = self.pool.submit(com.orders, brief, now)
            return
        c.take(com.orders(brief, now))
        c.due_at = com.reply_at(now)
        if c.ready(now):
            self._finish(c, now)

    def _finish(self, c: Consultation, now: int) -> None:
        s = self.st[c.side]
        if c.future is not None:
            c.take(c.future.result())
        c.arrived_at = now
        s.pending = None
        if c.consulted_at != now:  # a reply that took sim time
            s.last_reply = now
        self._skip_passed_slots(s, now)  # slots missed while thinking are skipped
        self.ready.append(c)

    def _flush(self) -> None:
        """Submit the replies that arrived, in side order, and log them."""
        self.ready.sort(key=lambda c: (self.sides.index(c.side), c.consulted_at))
        for c in self.ready:
            for text in split_orders(c.reply):
                self.sim.submit_order(c.side, text, at=c.arrived_at)
            rec = self._log_consultation(c)
            if self.out is not None:
                reply = " ".join((c.reply or "No orders.").split())
                self.out(
                    f"[{clock(self.start, c.consulted_at)}->{clock(self.start, c.arrived_at or 0)}]"
                    f" {c.side} ({rec['commander']}, {c.trigger}): {rec['wall_s']:.1f} s; "
                    f"{reply[:120]}"
                )
        self.ready.clear()

    def _abandon(self) -> None:
        """Replies still thinking when the day ends are logged, never submitted."""
        for side in self.sides:
            c = self.st[side].pending
            if c is None:
                continue
            if c.future is not None:
                c.take(c.future.result())
            self._log_consultation(c, abandoned=True)
            if self.out is not None:
                self.out(
                    f"[{clock(self.start, c.consulted_at)}->end] {side}: reply came after the end"
                )

    def _log_consultation(self, c: Consultation, abandoned: bool = False) -> dict:
        rec = c.record(self.start)
        if abandoned:
            rec["abandoned"] = True
        self.records.append(rec)
        if self.sim.log is not None:
            self.sim.log.write_record("commander", rec)
        return rec

    def _note_triggers(self) -> None:
        """Reasons to consult a general at once, from the messages his hq received this
        minute: a staff question, a report of a rout or of first contact."""
        sim = self.sim
        ids = {d["id"] for d in sim.tick_messages}
        if not ids:
            return
        whys: dict[str, dict[str, list[str]]] = {}
        for m in sim.command.messages:
            if m.id not in ids or m.side not in self.st:
                continue
            reasons = []
            if m.kind == MessageKind.CLARIFICATION:
                reasons.append("clarification")
            elif m.kind == MessageKind.REPORT:
                # first contact as the narrator tells it: an enemy within reach, or fire
                if m.side not in whys:
                    whys[m.side] = report_whys(sim.picture(m.side).reports)
                said = whys[m.side].get(m.id, [])
                if any("has broken" in w for w in m.data.get("why", [])):
                    reasons.append("rout")
                if FIRST_CONTACT in said:
                    reasons.append("first contact")
            if reasons:
                s = self.st[m.side]
                have = s.trigger.split(", ") if s.trigger else []
                s.trigger = ", ".join(dict.fromkeys(have + reasons))


# ---------------------------------------------------------------------------
# Games: a pack, its players, the play loop


def scenario_script(scenario: str | Path, side: str, start: str) -> list[tuple[int, str]]:
    """A side's scripted orders as a ScriptedCommander script (minute, text), from the
    scenario's `script.json`; a pack without one has no script (the side gives no orders)."""
    orders = load_script(resolve(scenario), start)
    return [(int(m), text) for m, s, text in orders or [] if s == side]


def make_commander(
    spec: str,
    side: str,
    narrator: Narrator,
    start: str = "13:00",
    memory: bool = True,
    scenario: str | Path = DEFAULT_SCENARIO,
    sim: Sim | None = None,
) -> Commander:
    """'script' (the side's orders in the scenario's script.json), 'null', 'bot' /
    'bot:strong' / 'bot:weak' (the doctrine opponent, kriegsspiel.bot; needs `sim`), or a
    model name from players.ROSTER."""
    if is_bot(spec):
        if sim is None:
            raise ValueError("a bot commander needs the sim (make_commander(..., sim=sim))")
        return BotCommander(sim, side, doctrine_for(spec))
    if spec == "script":
        return ScriptedCommander(scenario_script(scenario, side, start))
    if spec == "null":
        return NullCommander()
    if spec not in ROSTER:
        raise ValueError(
            f"unknown player {spec!r}; script, null, bot[:strong|weak] or one of {sorted(ROSTER)}"
        )
    return LLMCommander(ROSTER[spec], narrator.persona(side), memory=memory)


def play_game(
    players: dict[str, str],
    mode: str = "stub",
    seed: int = DEFAULT_SEED,
    log: str | Path | None = None,
    speed: float | None = DEFAULT_SPEED,
    cadence_min: int = CADENCE_MIN,
    end: str | None = None,
    fixture_dir: str | Path | None = None,
    scenario: str | Path = DEFAULT_SCENARIO,
    out=print,
    memory: bool = True,
    battle_over: bool = True,
    on_step=None,
) -> GameResult:
    """Build the scenario and play it with the named players (side -> 'script', 'null',
    'bot[:preset]' or a ROSTER name). The header records what `replay.replay_game` needs.
    `end` defaults to the scenario's end clock. `battle_over=False` never asks the umpire
    whether the battle is over (play runs to `end`)."""
    end = end or load_meta(resolve(scenario)).end_clock
    cfg: dict[str, Any] = {
        "players": dict(players),
        "cadence_min": cadence_min,
        "speed": speed,
        "end": end,
        "sides": list(players),
        "memory": memory,
    }
    if not battle_over:
        cfg["battle_over"] = False
    sim = build(
        scenario,
        seed,
        mode,
        fixture_dir=fixture_dir,
        log=RunLog(log),
        header={"play": cfg},
        battle_over=battle_over,
    )
    commanders = {
        s: make_commander(p, s, sim.narrator, sim.clock_start, memory, scenario, sim=sim)
        for s, p in players.items()
    }
    return play(sim, commanders, cadence_min, speed, end=end, out=out, on_step=on_step)


def run_script(
    scenario: str | Path = DEFAULT_SCENARIO,
    mode: str = "replay",
    log: str | Path | None = None,
    seed: int = DEFAULT_SEED,
    fixture_dir: str | Path | None = None,
    end: str | None = None,
) -> GameResult:
    """Script against script: every side plays the scenario's `script.json`, sides in
    oob.json order, until the battle is over or `end` (default the scenario's)."""
    d = resolve(scenario)
    sim = build(d, seed, mode, fixture_dir=fixture_dir, log=RunLog(log))
    commanders: dict[str, Commander] = {
        s: ScriptedCommander(scenario_script(d, s, sim.clock_start)) for s in load_sides(d)
    }
    return play(sim, commanders, speed=None, end=end, out=None)
