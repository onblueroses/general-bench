"""The simulation loop (docs/engine.md, sections 3 and 9).

Sim(world, formations, units, seed, umpire=None, staff=None). `step()` advances one minute in
fixed phase order: deliver messages, apply newly received orders, movement, vision and
reports, combat, morale, recovery, log. `build.build` makes a Sim from a pack and passes the
pack-level keywords (narrator, scenario_dir, end_clock, account_context, the ordinal judge, the
battle-over questions); a Sim made by hand (the engine tests) runs without them.
"""

from __future__ import annotations

import copy
import hashlib
import struct
import zlib
from pathlib import Path
from typing import TYPE_CHECKING, Protocol

import numpy as np

from . import command as cmd
from . import drill
from . import geometry as geo
from .account import field_of, render
from .clock import clock
from .combat import UMPIRE_RANGE, fire_phase, melee_phase, steady_square
from .log import RunLog, dumps, task_to_json
from .morale import morale_phase, recovery_phase
from .movement import BASE_SPEED, BodyRT, busy
from .types import (
    Arm,
    Event,
    Formation,
    MessageKind,
    Ref,
    RefKind,
    Task,
    TaskKind,
    Unit,
    UnitState,
    Verdict,
)
from .units import Forces
from .verdict import OrdinalJudge, field_at
from .vision import Vision

if TYPE_CHECKING:
    from .narrator import Narrator

# ---------------------------------------------------------------------------
BATTLE_OVER_AFTER_MIN = 120  # engine.md 7: ask every 30 minutes after the first 2 hours
BATTLE_OVER_EVERY_MIN = 30
SEQUEL_COMPLETES = (TaskKind.ADVANCE, TaskKind.ATTACK, TaskKind.CHARGE, TaskKind.WITHDRAW)
# Arrivals and exits (docs/pack-format.md; assumptions unless the design says)
ENTRY_CLEAR_M = 100.0  # design assumption: a body enters when its entry is clear within 100 m
ARRIVAL_STEP_M = 300.0  # assumption: with no order and no `assemble`, it marches this far in
EXIT_RADIUS_M = 100.0  # assumption: within this of an exit its task names, a body leaves
EDGE_FLEE_M = 50.0  # assumption: with exits in the pack, a routed body this near an edge flees
# off the map (lost to the battle)
# What one body may see of another while both drill (Sim._movement): these fields are set
# back to their start values between drills and applied after.
_SEEN_UNIT = ("x", "y", "facing_deg", "state", "morale", "disorder")
_SEEN_RT = ("change_to", "change_left", "turn_to")


class Umpire(Protocol):
    def situation_modifier(self, context: str) -> float: ...
    def battle_over(self, summary: str) -> bool: ...
    def verdict(self, summary: str) -> Verdict: ...


class Sim:
    def __init__(
        self,
        world,
        formations: list[Formation],
        units: list[Unit],
        seed: int,
        umpire: Umpire | None = None,
        staff: cmd.Staff | None = None,
        log: RunLog | None = None,
        clock_start: str = "13:00",
        scenario: str = "",
        jev_client=None,
        header: dict | None = None,
        defer_header: bool = False,
        narrator: Narrator | None = None,
        scenario_dir: Path | None = None,
        end_clock: str | None = None,
        account_context: dict | None = None,
        ordinal: OrdinalJudge | None = None,
        battle_over_after: int = BATTLE_OVER_AFTER_MIN,
        battle_over_every: int = BATTLE_OVER_EVERY_MIN,
    ):
        self.world = world
        self.forces = Forces(formations, units)
        self.seed = int(seed)
        self.umpire = umpire
        self.staff = staff
        self.clock_start = clock_start
        self.now = 0
        self.rt: dict[str, BodyRT] = {
            u.id: BodyRT(start_men=u.men) for u in self.forces.units.values()
        }
        # bodies off the map: "awaiting" arrival, "exited" by an exit, "fled"
        # off an edge, "captured" (a train). Such a body is inert, held in state DESTROYED;
        # its record here says why. Empty (and not in the snapshot) in a pack without them.
        self.offmap: dict[str, dict] = {}
        self._arrival_seq = {u.id: k for k, u in enumerate(units)}
        for u in units:
            if u.arrives_at is None:
                continue
            if u.entry and world.has_feature(u.entry):
                u.x, u.y = world.anchor(world.feature(u.entry))
            self.offmap[u.id] = {
                "fate": "awaiting",
                "at": float(u.arrives_at),
                "due_clock": clock(clock_start, u.arrives_at),
                "entry": u.entry,
                "state": u.state.value,
                "x": float(u.x),
                "y": float(u.y),
            }
            u.state = UnitState.DESTROYED
        self.forces.inert_anchor = self._inert_anchor
        self.vision = Vision(world)
        self.command = cmd.Command(self)
        self.events: list[Event] = []
        self.tick_events: list[Event] = []
        self.pending_orders: list[dict] = []
        self.waiting_tasks: list[Task] = []  # received, start condition not yet met
        self.hq_tasks: dict[str, Task] = {}
        self.tick_losses: dict[str, float] = {}
        self.melee_requests: list[tuple[str, str, str]] = []
        # the movement phase's paths, gathered while every body drills against the field as
        # it stood at the start of the minute, then resolved together (drill.resolve_moves);
        # bodies whose task ended mid-movement hold where they end the minute
        self.moves: dict | None = None
        self._hold_here: list[str] = []
        self.routed_now: list[str] = []
        self.over = False
        self.log = log
        self._order_seq = 0
        self._tick_orders: list[dict] = []
        self._tick_umpire: list[dict] = []
        self.tick_messages: list[dict] = []  # the messages delivered in the last step
        # the umpire's answers of a logged run, served in place of asking (replay.replay_tasks)
        self.logged_umpire: list[dict] | None = None
        self._positions_cache: tuple[int, dict] | None = None
        # Jev clients whose calls go into the run log, each once (one shared client keeps
        # the order of the staff's and the umpire's calls)
        clients = (jev_client, getattr(staff, "client", None), getattr(umpire, "client", None))
        self.jev_clients = list({id(c): c for c in clients if hasattr(c, "drain")}.values())
        self.verdict_given: Verdict | None = None
        # The pack (from build.build): the narrator holding the start of the day, the pack
        # directory, the clock the day ends at, the umpire's account context (sides,
        # objectives, sunset, deadline), an ordinal pack's judge, which ends the battle in
        # place of the umpire's question and gives the verdict, and when the umpire is asked
        # whether the battle is over.
        self.narrator = narrator
        self.scenario_dir = scenario_dir
        self.end_clock = end_clock
        self.account_context = account_context
        self.ordinal = ordinal
        self.battle_over_after = battle_over_after
        self.battle_over_every = battle_over_every
        # initial sight so the first orders see the field as it stands (what the army hqs see)
        self.vision.update(self.forces, self.now)
        for side in self.forces.sides():
            for sg in self.vision.seen_from(
                self.forces, self.command.army_hq(side), side, self.now
            ).values():
                self.command.learn(side, sg, self.now, "hq")
        # the log header carries hash0, the state replay starts from; a builder that changes
        # the state after construction (build.build's initial reports) defers it and calls
        # write_header() once the scenario is fully applied
        self._header = {
            "seed": self.seed,
            "scenario": scenario,
            "clock_start": clock_start,
            "extra": dict(header or {}),
        }
        if log is not None and not defer_header:
            self.write_header()

    def write_header(self) -> None:
        """Write the log header, hash0 the current state's hash (once; step() writes a
        deferred header no one wrote before the first tick)."""
        if self.log is None or self.log.header is not None:
            return
        h = self._header
        self.log.write_header(
            {
                "seed": h["seed"],
                "scenario": h["scenario"],
                "clock_start": h["clock_start"],
                "hash0": self.state_hash(),
                **h["extra"],
            }
        )

    # ------------------------------------------------------------- utilities
    def place_key(self, u: Unit) -> tuple[int, int]:
        """Where a body stands, as the engine keys and orders events by it: its offset from the
        field's centre in whole millimetres, the sign turned so that a point and its image
        under the 180° rotation about the centre have the same key: the rotated game draws,
        and takes events in, the order the game did."""
        dx = round((float(u.x) - self.world.cx) * 1000.0)
        dy = round((float(u.y) - self.world.cy) * 1000.0)
        return (-dx, -dy) if dx < 0 or (dx == 0 and dy < 0) else (dx, dy)

    def event_rng(self, stream: str, *bodies: Unit) -> np.random.Generator:
        """A fresh generator for one event: keyed by (seed, stream, tick) and by where the
        bodies in it stand, never by their ids or by how many draws came before it, so
        renaming the armies or the order in which events are taken cannot change a draw. The
        bodies are given in the event's own order, each keyed by `place_key`, so the rotated
        game draws what the game drew."""
        k = [self.seed, zlib.crc32(stream.encode()), self.now]
        k.extend(zlib.crc32(struct.pack("<2q", *self.place_key(u))) for u in bodies)
        return np.random.default_rng(k)

    def emit(self, event_kind: str, /, **data) -> None:
        e = Event(tick=self.now, kind=event_kind, data=data)
        self.tick_events.append(e)
        self.events.append(e)

    def inflict(self, uid: str, n: int, cause: str) -> None:
        u = self.forces.units[uid]
        n = max(0, min(int(n), u.men))
        if n == 0:
            return
        u.men -= n
        u.casualties += n
        self.tick_losses[uid] = self.tick_losses.get(uid, 0.0) + n

    def release_melee(self, u: Unit) -> None:
        rt = self.rt[u.id]
        if rt.melee_with is not None:
            other = self.rt[rt.melee_with]
            other.melee_with, other.melee_left = None, 0
            rt.melee_with, rt.melee_left = None, 0

    def request_melee(self, a: Unit, d: Unit, gait: str) -> None:
        self.melee_requests.append((a.id, d.id, gait))

    def alive_by_side(self) -> dict:
        if self._positions_cache is None or self._positions_cache[0] != self.now:
            by: dict[str, tuple[list[Unit], np.ndarray]] = {}
            for side in self.forces.sides():
                us = [
                    u
                    for u in self.forces.units.values()
                    if u.side == side and u.state != UnitState.DESTROYED
                ]
                xy = np.array([(u.x, u.y) for u in us], dtype=float).reshape(-1, 2)
                by[side] = (us, xy)
            self._positions_cache = (self.now, by)
        return self._positions_cache[1]

    def enemies_near(self, u: Unit, radius: float) -> list[Unit]:
        """Enemy bodies within radius (true positions; physics, not knowledge)."""
        out = []
        for side, (us, xy) in self.alive_by_side().items():
            if side == u.side or not us:
                continue
            d2 = (xy[:, 0] - u.x) ** 2 + (xy[:, 1] - u.y) ** 2
            for k in np.nonzero(d2 <= radius * radius)[0].tolist():
                v = us[k]
                if v.state != UnitState.DESTROYED:
                    out.append(v)
        return out

    def friendly_cavalry_near(self, u: Unit, radius: float) -> bool:
        for v in self.forces.units.values():
            if (
                v.side == u.side
                and v.arm == Arm.CAVALRY
                and v.state not in (UnitState.ROUTED, UnitState.DESTROYED)
                and geo.dist((u.x, u.y), (v.x, v.y)) <= radius
            ):
                return True
        return False

    def situation_modifier(self, context: str) -> float:
        if self.logged_umpire is not None:
            if not self.logged_umpire:
                return 1.0  # the logged run had no umpire
            rec = self.logged_umpire.pop(0)
            assert rec["call"] == "situation_modifier" and rec["context"] == context, rec
            factor = float(rec["factor"])
        elif self.umpire is None:
            return 1.0
        else:
            raw = float(self.umpire.situation_modifier(context))
            factor = min(UMPIRE_RANGE[1], max(UMPIRE_RANGE[0], raw))
        self._tick_umpire.append(
            {"call": "situation_modifier", "context": context, "factor": factor}
        )
        return factor

    def end_task(self, u: Unit) -> None:
        """The task of u's formation ends (its `until` fired, or a task with a sequel is
        complete): the sequel `then` starts (or waits for its own start condition); without a
        sequel the formation holds where it stands."""
        t = u.task
        assert t is not None
        if t.then is not None:
            nxt = copy.deepcopy(t.then)
            nxt.formation = nxt.formation or t.formation
            nxt.source_text = nxt.source_text or t.source_text
            nxt.issued_at, nxt.received_at = t.issued_at, float(self.now)
            for b in self.forces.bodies(t.formation):
                if b.task is t:
                    b.task = None
            self.emit("task_ended", formation=t.formation, task=t.kind.value, then=nxt.kind.value)
            side = self._side_of(nxt.formation)
            if cmd.condition_met(self, side, nxt.formation, nxt.start):
                cmd.apply_task(self, nxt)
                self.emit(
                    "task_started",
                    formation=nxt.formation,
                    task=nxt.kind.value,
                    text=nxt.source_text,
                )
            else:
                self.waiting_tasks.append(nxt)
            return
        hold = Task(
            kind=TaskKind.HOLD,
            formation=t.formation,
            source_text=f"(until) {t.source_text}",
            issued_at=t.issued_at,
            received_at=float(self.now),
        )
        for b in self.forces.bodies(t.formation):
            if b.task is t:
                b.task = hold
                rt = self.rt[b.id]
                rt.slot, rt.route, rt.route_goal, rt.phase = (b.x, b.y), [], None, "march"
                if self.moves is not None:  # mid-movement: hold where it ends the minute
                    self._hold_here.append(b.id)

    # ----------------------------------------------------- arrivals and exits
    def _inert_anchor(self, fid: str):
        """Where a formation with no body on the map is: the entry of its next arrival, else
        where its last body left the map; None if it has no body off the map."""
        recs = [
            (uid, self.offmap[uid])
            for uid in (u.id for u in self.forces.bodies(fid))
            if uid in self.offmap
        ]
        if not recs:
            return None
        waiting = [r for r in recs if r[1]["fate"] == "awaiting"]
        if waiting:
            _, rec = min(waiting, key=lambda r: (r[1]["at"], self._arrival_seq.get(r[0], 0)))
        else:
            _, rec = max(recs, key=lambda r: (r[1]["at"], r[0]))
        return (rec["x"], rec["y"])

    def _entry_blocked(self, p) -> bool:
        r2 = ENTRY_CLEAR_M * ENTRY_CLEAR_M
        return any(
            u.state != UnitState.DESTROYED and (u.x - p[0]) ** 2 + (u.y - p[1]) ** 2 < r2
            for u in self.forces.units.values()
        )

    def assemble_point(self, u: Unit, p) -> tuple[float, float]:
        a = u.assemble
        if isinstance(a, str) and self.world.has_feature(a):
            return self.world.anchor(self.world.feature(a), p)
        if isinstance(a, tuple | list) and len(a) == 2:
            return (float(a[0]), float(a[1]))
        t = self.world.terrain
        centre = (t.origin[0] + t.width_m / 2.0, t.origin[1] + t.height_m / 2.0)
        q = geo.toward(p, centre, ARRIVAL_STEP_M)
        return (float(q[0]), float(q[1]))

    def _arrivals(self) -> None:
        """Bodies due on the map enter at their entry, one per entry per minute, first come
        first served, when nobody stands within ENTRY_CLEAR_M of it (else they wait)."""
        due = sorted(
            (rec["at"], self._arrival_seq.get(uid, 0), uid)
            for uid, rec in self.offmap.items()
            if rec["fate"] == "awaiting" and rec["at"] <= self.now
        )
        used: set[str] = set()
        for _, _, uid in due:
            entry = self.offmap[uid]["entry"]
            if entry in used:
                continue
            used.add(entry)
            p = self.world.anchor(self.world.feature(entry))
            if not self._entry_blocked(p):
                self._arrive(uid, p)

    def _arrive(self, uid: str, p) -> None:
        u = self.forces.units[uid]
        rec = self.offmap.pop(uid)
        u.state = UnitState(rec["state"])
        u.x, u.y = float(p[0]), float(p[1])
        self.rt[uid] = BodyRT(start_men=self.rt[uid].start_men)
        asm = self.assemble_point(u, p)
        t = u.task
        if t is None or t.tentative:
            t = Task(
                kind=TaskKind.HOLD,
                formation=u.id,
                objective=Ref(RefKind.POINT, point=asm),
                source_text="(arrived) assembling",
                issued_at=float(self.now),
                received_at=float(self.now),
            )
        cmd.start_body(self, u, t, asm)
        slot = self.rt[uid].slot or asm
        if geo.dist(p, slot) > 1.0:
            u.facing_deg = geo.bearing(p, slot)
        self._positions_cache = None
        self.emit("arrived", unit=uid, side=u.side, entry=rec["entry"], men=u.men)

    def _exits(self) -> None:
        """A body whose task names an exit leaves the map within the exit's radius; with any
        exit in the pack, a routed body at an edge flees off the map."""
        w = self.world
        if not w.exits():
            return
        for u in self.forces.units.values():
            if u.state == UnitState.DESTROYED or self.rt[u.id].melee_with is not None:
                continue
            if u.state == UnitState.ROUTED:
                if w.edge_distance(u.x, u.y) <= EDGE_FLEE_M:
                    self.leave(u, "fled", None)
                continue
            for f in cmd.leaving_exits(self, u.task):  # a move or withdrawal naming an exit
                if w.feature_distance(u.x, u.y, f) <= float(f.props.get("radius_m", EXIT_RADIUS_M)):
                    self.leave(u, "exited", f.name)
                    break
        self._positions_cache = None

    def leave(self, u: Unit, fate: str, exit_name: str | None, **extra) -> None:
        """`u` leaves the map ("exited" by an exit, "fled" off an edge, "captured"); it keeps
        its men in the record (a captured body's are lost) and its brigade reports it."""
        self.release_melee(u)
        rec = {
            "fate": fate,
            "at": self.now,
            "clock": clock(self.clock_start, self.now),
            "men": int(u.men),
            "x": round(float(u.x), 1),
            "y": round(float(u.y), 1),
            **extra,
        }
        if exit_name:
            rec["exit"] = exit_name
        u.state = UnitState.DESTROYED
        u.engaged = set()
        rt = self.rt[u.id]
        rt.route, rt.route_goal = [], None
        self.offmap[u.id] = rec
        self.emit(fate, unit=u.id, side=u.side, exit=exit_name, men=int(u.men), **extra)
        b = self.forces.brigade_of(u.id)
        what = (
            f"has left the field by {exit_name}"
            if fate == "exited"
            else "has fled off the field"
            if fate == "fled"
            else "has been captured"
        )
        self.command.send_report(
            u.side,
            b.id,
            f"{rec['clock']}, {b.commander} ({b.name}): {u.name} {what}.",
            {"why": [f"{u.name} {what}"], fate: u.id},
            self.now,
        )

    def _side_of(self, fid: str) -> str:
        f = self.forces
        return f.formations[fid].side if fid in f.formations else f.units[fid].side

    def _sequels(self) -> None:
        """A task with a sequel ends when it is complete: for ADVANCE, ATTACK, CHARGE and
        WITHDRAW when the reached fraction of its live bodies has arrived and none of them is
        engaged (assumption); other kinds end only by `until`."""
        seen: set[int] = set()
        for uid in sorted(self.forces.units):
            u = self.forces.units[uid]
            t = u.task
            if t is None or t.then is None or id(t) in seen:
                continue
            seen.add(id(t))
            if t.kind not in SEQUEL_COMPLETES:
                continue
            bodies = [
                b
                for b in self.forces.bodies(t.formation)
                if b.task is t and b.state not in (UnitState.ROUTED, UnitState.DESTROYED)
            ]
            if not bodies or any(b.engaged for b in bodies):
                continue
            arrived = sum(self.rt[b.id].phase == "arrived" for b in bodies)
            if arrived >= cmd.REACHED_FRACTION * len(bodies):
                self.end_task(bodies[0])

    # ---------------------------------------------------------------- orders
    def submit_order(self, side: str, text: str, at: float | None = None) -> None:
        """The army commander writes an order at sim minute `at` (default now)."""
        self._order_seq += 1
        self.pending_orders.append(
            {
                "seq": self._order_seq,
                "side": side,
                "text": text,
                "at": float(self.now if at is None else at),
                "tasks": None,
            }
        )

    def submit_tasks(
        self,
        side: str,
        tasks: list[Task],
        at: float | None = None,
        text: str = "",
        clarifications: list[str] | None = None,
    ) -> None:
        """Bypass the staff: send ready-made tasks (scripted runs, replay)."""
        self._order_seq += 1
        self.pending_orders.append(
            {
                "seq": self._order_seq,
                "side": side,
                "text": text or "; ".join(t.source_text for t in tasks),
                "at": float(self.now if at is None else at),
                "tasks": [copy.deepcopy(t) for t in tasks],
                "clarifications": list(clarifications or []),
            }
        )

    def _write_orders(self) -> None:
        due = sorted(
            (o for o in self.pending_orders if o["at"] <= self.now),
            key=lambda o: (o["at"], o["seq"]),
        )
        for o in due:
            self.pending_orders.remove(o)
            tasks = o["tasks"]
            clar: list[str] = list(o.get("clarifications") or [])
            if tasks is None:
                if self.staff is None:
                    raise RuntimeError("submit_order needs a staff; use submit_tasks")
                tasks = self.staff.translate(o["text"], self.command.side_view(o["side"]))
                clar = list(self.staff.clarifications)
                if clar:
                    self.staff.clarifications = []
            for t in tasks:
                t.source_text = t.source_text or o["text"]
            self._tick_orders.append(
                {
                    "side": o["side"],
                    "text": o["text"],
                    "at": o["at"],
                    "tasks": [task_to_json(t) for t in tasks],
                    "clarifications": clar,
                    "staff": o["tasks"] is None,
                }
            )
            msgs = self.command.send_order(o["side"], o["text"], tasks, self.now)
            for m in msgs:
                if m.data.get("undeliverable"):
                    self.emit("order_undeliverable", id=m.id, side=m.side, to=m.recipient)
                    continue
                self.emit(
                    "order_sent",
                    id=m.id,
                    side=m.side,
                    to=m.recipient,
                    arrives=round(m.data["arrives"], 3),
                )
            for c in clar:
                self.command.send_report(
                    o["side"],
                    self.forces.root(o["side"]).id,
                    c,
                    {},
                    self.now,
                    kind=MessageKind.CLARIFICATION,
                    delay=0.0,
                )

    def _deliver(self) -> None:
        for m in self.command.due(self.now):
            self.tick_messages.append(
                {
                    "id": m.id,
                    "kind": m.kind.value,
                    "sent_at": m.sent_at,
                    "received_at": m.received_at,
                }
            )
            self.emit(f"{m.kind.value}_received", id=m.id, side=m.side, to=m.recipient)
            if m.kind == MessageKind.ORDER:
                for t in m.tasks:
                    t.received_at = float(self.now)
                    self.waiting_tasks.append(t)
            else:
                self.command.receive(m, self.now)

    def _apply_tasks(self) -> None:
        still = []
        for t in self.waiting_tasks:
            side = self._side_of(t.formation)
            if cmd.condition_met(self, side, t.formation, t.start):
                cmd.apply_task(self, t)
                self.emit(
                    "task_started", formation=t.formation, task=t.kind.value, text=t.source_text
                )
            else:
                still.append(t)
        self.waiting_tasks = still

    def _move_hqs(self) -> None:
        for fid in sorted(self.hq_tasks):
            t = self.hq_tasks[fid]
            f = self.forces.formations[fid]
            p, _ = cmd.resolve_ref(self, f.side, t.objective)
            if p is None:
                del self.hq_tasks[fid]
                continue
            here = self.forces.hq(fid)
            speed = BASE_SPEED["hq"][0]  # straight, at the road rate; assumption
            # a lattice step from a lattice point, so an HQ and its image under the 180°
            # rotation ride to exact images
            centre = self.world.centre
            here = geo.snap_point(here, centre)
            to = geo.snap_point(p, centre)
            d = geo.dist(here, to)
            if d <= speed:
                f.hq = to
            else:
                f.hq = (
                    here[0] + geo.snap_m((to[0] - here[0]) * speed / d),
                    here[1] + geo.snap_m((to[1] - here[1]) * speed / d),
                )
            if geo.dist(f.hq, p) < 1.0:
                del self.hq_tasks[fid]

    # ------------------------------------------------------------------ step
    def _movement(self) -> None:
        """Every body drills its minute at once. Each plans and moves against the field as it stood
        at the start of the minute: what one body did is hidden from the others until all have
        drilled (its position, facing, formation, morale and disorder, and the formation change or
        turn it began, are set back to their start values between drills and applied after), so the
        order in which bodies are taken (their ids) decides nothing. Where the paths meet is then
        settled in time (drill.resolve_moves)."""
        units = self.forces.units
        seen = {
            uid: ([getattr(u, f) for f in _SEEN_UNIT], [getattr(self.rt[uid], f) for f in _SEEN_RT])
            for uid, u in units.items()
        }
        start = {uid: (u.state, steady_square(u, busy(self.rt[uid]))) for uid, u in units.items()}
        self.moves = {}
        self._hold_here = []
        after = {}
        try:
            for uid, u in units.items():
                drill.drill(self, u)
                after[uid] = (
                    [getattr(u, f) for f in _SEEN_UNIT],
                    [getattr(self.rt[uid], f) for f in _SEEN_RT],
                )
                _set_seen(u, self.rt[uid], *seen[uid])
            for uid, u in units.items():
                _set_seen(u, self.rt[uid], *after[uid])
            self._positions_cache = None
            drill.resolve_moves(self, self.moves, start)
            for uid in self._hold_here:
                if self.rt[uid].slot is not None:
                    self.rt[uid].slot = (units[uid].x, units[uid].y)
        finally:
            self.moves = None

    def _snap(self) -> None:
        """Set every body's position on the position lattice about the field's centre and its
        facing on the facing lattice (geometry.SNAP_M, SNAP_DEG: powers of two), and the
        headquarters' positions likewise (after movement and at the end of the minute).
        Floating-point movement leaves a body a few 1e-12 m off where the same march, rotated
        by 180° about the centre, leaves its image; two bodies on the same spot, or at exactly
        contact distance, are then told apart by that noise. On the lattice the image of a
        position is exactly representable, so the rotated game starts every minute from the
        exact image of the game. The lattice is far below anything the physics resolves."""
        centre = self.world.centre
        for u in self.forces.units.values():
            u.x, u.y = geo.snap_point((u.x, u.y), centre)
            u.facing_deg = geo.snap_deg(u.facing_deg)
        for f in self.forces.formations.values():
            if f.hq is not None:
                f.hq = geo.snap_point(f.hq, centre)

    def step(self) -> list[Event]:
        if self.over:
            return []
        self.write_header()
        self.tick_events = []
        self.tick_losses = {}
        self.routed_now = []
        self._tick_orders, self._tick_umpire, self.tick_messages = [], [], []
        self._positions_cache = None
        # 1. deliver messages (orders written now leave now; arrivals are handed over)
        self._write_orders()
        self._deliver()
        if self.offmap:
            self._arrivals()  # bodies due enter at their entries (they take orders received)
        # 2. apply newly received orders (and waiting ones whose start has come); sequels
        self._apply_tasks()
        self._sequels()
        # 3. movement
        self._move_hqs()
        self._snap()  # arrivals, HQs and the first minute's deployment onto the lattice
        self._movement()
        self._exits()
        self._snap()
        self._positions_cache = None
        # 4. vision and reports
        for e in self.vision.update(self.forces, self.now):
            self.emit("sighting", **e)
        for side in self.forces.sides():
            for s in self.vision.seen_from(
                self.forces, self.command.army_hq(side), side, self.now
            ).values():
                self.command.learn(side, s, self.now, "hq")
        # 5. combat
        fire_phase(self)
        melee_phase(self)
        self.command.note_events(self.tick_events)
        # 6. morale
        morale_phase(self)
        # reports go out after the tick's losses and routs are known
        for m in self.command.brigade_reports(self.now, self.routed_now):
            arrives = m.data["arrives"]
            self.emit(
                "report_sent",
                id=m.id,
                side=m.side,
                sender=m.sender,
                arrives=None if arrives is None else round(arrives, 3),
            )
        # 7. recovery
        recovery_phase(self)
        self._ask_battle_over()
        self._snap()
        # 8. log: the hash is of the state after the tick (clock advanced)
        tick = self.now
        self.now += 1
        h = self.state_hash()
        if self.log is not None:
            self.log.write_tick(
                {
                    "tick": tick,
                    "hash": h,
                    "events": [{"kind": e.kind, **e.data} for e in self.tick_events],
                    "orders": self._tick_orders,
                    "messages": self.tick_messages,
                    "umpire": self._tick_umpire,
                    "jev": self._drain_jev(),
                }
            )
        else:
            self._drain_jev()
        return self.tick_events

    def _drain_jev(self) -> list[dict]:
        return [r.to_json() for c in self.jev_clients for r in c.drain()]

    def run(self, minutes: int) -> None:
        for _ in range(minutes):
            if self.over:
                break
            self.step()

    def _ask_battle_over(self) -> None:
        t = self.now + 1  # minutes elapsed at the end of this tick
        if self.ordinal is not None:  # an ordinal pack: the mechanical judge, never Jev
            if self.ordinal.observe(field_at(self, t), t):
                self.over = True
                r = self.ordinal.result
                self.emit("battle_over", at=t, winner=r["winner"], how=r["how"])
            return
        if t < self.battle_over_after or (t - self.battle_over_after) % self.battle_over_every:
            return
        if self.logged_umpire is not None:
            if self.logged_umpire and self.logged_umpire[0]["call"] == "battle_over":
                rec = self.logged_umpire.pop(0)
                self.over = bool(rec["answer"])
                self._tick_umpire.append(rec)
                if self.over:
                    self.emit("battle_over", at=t)
            return
        if self.umpire is None:
            return
        s = self.summary()
        ans = bool(self.umpire.battle_over(s))
        self._tick_umpire.append({"call": "battle_over", "summary": s, "answer": ans})
        self.over = ans
        if ans:
            self.emit("battle_over", at=t)

    # ------------------------------------------------------------- read-outs
    def picture(self, side: str) -> cmd.Picture:
        return self.command.picture(side)

    def side_view(self, side: str):
        return self.command.side_view(side)

    def losses(self) -> dict[str, int]:
        out: dict[str, int] = {}
        for u in self.forces.units.values():
            out[u.side] = out.get(u.side, 0) + int(u.casualties)
        return out

    def summary(self) -> str:
        """The umpire's account of the field (`account.render`): per side the strength and the
        bodies by state, who holds each place the objectives name, every body. Asked by battle_over
        and the verdict. `account_context` (build.build) gives the sides, the objectives, sunset and
        deadline; without it the umpire's sides and objectives, else the forces' sides."""
        ctx = self.account_context or {}
        sides = list(ctx.get("sides") or getattr(self.umpire, "sides", None) or self.forces.sides())
        objectives = ctx.get("objectives", getattr(self.umpire, "objectives", "") or "")
        return render(
            field_of(self, with_hash=False),
            self.world.features,
            sides,
            objectives,
            ctx.get("sunset"),
            ctx.get("deadline"),
        )

    def offmap_counts(self, side: str) -> str:
        """'2 bodies (1,200 men) off the map by East exit; 1 body (300 men) captured' or
        ''."""
        groups: dict[str, list[int]] = {}
        for uid, rec in sorted(self.offmap.items()):
            if self.forces.units[uid].side != side:
                continue
            fate = rec["fate"]
            key = {
                "exited": f"off the map by {rec.get('exit')}",
                "fled": "fled off the map",
                "captured": "captured",
                "awaiting": "not yet arrived",
            }[fate]
            men = self.forces.units[uid].men if fate == "awaiting" else rec["men"]
            groups.setdefault(key, []).append(int(men))
        return "; ".join(
            f"{len(v)} {'body' if len(v) == 1 else 'bodies'} ({sum(v):,} men) {k}"
            for k, v in groups.items()
        )

    def verdict(self) -> Verdict:
        """The umpire's verdict on the day as it stands; logged (with its Jev call) once.
        Under an ordinal pack the judge's verdict is the verdict; the umpire is still asked,
        and its winner is kept beside it (`jev_winner`, `umpire`) as a health number."""
        if self.ordinal is not None:
            return self._ordinal_verdict()
        if self.umpire is None:
            return Verdict(winner="undecided", rationale="no umpire")
        s = self.summary()
        v = self.umpire.verdict(s)
        self.verdict_given = v
        rec = {"tick": self.now, "summary": s, "verdict": v.to_json(), "jev": self._drain_jev()}
        if self.log is not None:
            self.log.write_record("verdict", rec)
        return v

    def _ordinal_verdict(self) -> Verdict:
        r = self.ordinal.verdict(field_at(self, self.now), self.now)
        s = self.summary()
        ump = self.umpire.verdict(s) if self.umpire is not None else None
        text = (
            f"{r['winner']} by {r['how']} at {r['clock']}"
            if r["winner"] != "undecided"
            else f"unfinished at {r['clock']}"
        )
        v = Verdict(
            winner=r["winner"],
            rationale=f"ordinal verdict: {text}",
            winner_source="ordinal",
            jev_winner=ump.winner if ump else None,
            ordinal={**r, **({"umpire": ump.to_json()} if ump else {})},
        )
        self.verdict_given = v
        rec = {"tick": self.now, "summary": s, "verdict": v.to_json(), "jev": self._drain_jev()}
        if self.log is not None:
            self.log.write_record("verdict", rec)
        return v

    # -------------------------------------------------------------- snapshot
    def snapshot(self) -> dict:
        units = {}
        for uid, u in self.forces.units.items():
            units[uid] = {
                "x": u.x,
                "y": u.y,
                "facing": u.facing_deg,
                "state": u.state.value,
                "men": u.men,
                "morale": u.morale,
                "fatigue": u.fatigue,
                "ammo": u.ammo,
                "disorder": u.disorder,
                "casualties": u.casualties,
                "engaged": sorted(u.engaged),
                "task": task_to_json(u.task) if u.task else None,
                "rt": self.rt[uid].to_json(),
            }
        return {
            "now": self.now,
            "over": self.over,
            "units": units,
            "hq": {f.id: list(f.hq) if f.hq else None for f in self.forces.formations.values()},
            "vision": self.vision.snapshot(),
            "command": self.command.snapshot(),
            "waiting": [task_to_json(t) for t in self.waiting_tasks],
            "hq_tasks": {k: task_to_json(v) for k, v in sorted(self.hq_tasks.items())},
            **({"offmap": dict(sorted(self.offmap.items()))} if self.offmap else {}),
            # orders not yet written are inputs, logged in the tick they are written
        }

    def state_hash(self) -> str:
        return hashlib.sha256(dumps(self.snapshot()).encode()).hexdigest()


def _set_seen(u: Unit, rt: BodyRT, unit_vals: list, rt_vals: list) -> None:
    for f, v in zip(_SEEN_UNIT, unit_vals, strict=True):
        setattr(u, f, v)
    for f, v in zip(_SEEN_RT, rt_vals, strict=True):
        setattr(rt, f, v)


__all__ = ["Sim", "Umpire"]
