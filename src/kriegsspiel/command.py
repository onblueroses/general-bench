"""Command (docs/engine.md, "Command"): the staff protocol, couriers and reports, the army
commander's picture, references and start conditions, and the application of a formation task
to its bodies (slots in line, column or square). The per-minute drills that move the bodies are
in `drill`.
"""

from __future__ import annotations

import hashlib
import itertools
import math
from dataclasses import dataclass, field, replace
from typing import TYPE_CHECKING, Protocol

import numpy as np

from . import geometry as geo
from .clock import clock
from .log import dumps, task_to_json
from .movement import (
    BASE_SPEED,
    profile_arm,
    profile_for,
)
from .types import (
    Arm,
    Condition,
    ConditionKind,
    EnemyView,
    FeatureKind,
    FormationView,
    Message,
    MessageKind,
    Ref,
    RefKind,
    SideView,
    Task,
    TaskKind,
    Unit,
    UnitState,
)
from .units import INTERVAL_M, frontage
from .vision import Sighting
from .world import sym_floor

if TYPE_CHECKING:
    from .sim import Sim

# ---------------------------------------------------------------------------
# Constants (the spec's unless marked "assumption")
HOLD_ON_M = 200.0  # assumption: a body this near a feature it is told to hold is on it
PLACE_REAR_M = 500.0  # assumption: 'our rear' lies this far behind the rearmost body
# Cavalry that pulled up before a steady square does not charge that square again while it
# stands in square, and not at all for this long (assumption; the screen is drill.SCREEN_SQUARE_*)
PULLUP_BAR_MIN = 15
WITHDRAW_DEFAULT_M = 1000.0  # assumption: WITHDRAW with no objective falls back 1 km
WITHDRAW_COVER_MIN = 5  # assumption: the rear body covers for 5 minutes
REPORT_EVERY_MIN = 30  # spec
REPORT_LOSS_FRACTION = 0.25  # spec
COURIER_PROFILE = "courier_road"  # 400 m/min road, 250 cross-country
REACHED_FRACTION = 0.5  # assumption: a formation has reached when half its bodies have
TRAIN_SPACING_M = 100.0  # assumption: a train's bodies take places 100 m apart along the road
SLOT_SEARCH_M = 500.0  # assumption: how far a slot on ground closed to the body is moved


# ---------------------------------------------------------------------------
# Staff


class Staff(Protocol):
    """Reads an order into tasks; the questions it sends back to the general for the last
    order it read wait in `clarifications` until the sim takes them."""

    clarifications: list[str]

    def translate(self, text: str, side_view: SideView) -> list[Task]: ...


# ---------------------------------------------------------------------------
# Army picture


@dataclass
class Contact:
    key: str
    name: str
    arm: str | None
    est_men: int | None
    x: float
    y: float
    seen_at: int
    learned_at: int
    source: str
    routed: bool = False

    def to_json(self) -> dict:
        return dict(self.__dict__)


@dataclass
class Picture:
    side: str
    now: int
    clock: str
    hq: tuple[float, float]
    reports: list[Message] = field(default_factory=list)
    contacts: list[Contact] = field(default_factory=list)
    # brigade -> last reported state: position, men, strength_start, as_of
    own: dict[str, dict] = field(default_factory=dict)
    # the side's own orders (the general knows what he wrote, when the aide left and, once
    # the aide is back, when it was received): ORDER messages in sending order
    orders: list[Message] = field(default_factory=list)


def place(world, p: geo.Point) -> str:
    """'600 m south-east of Neudorf' style description."""
    if not world.features:
        return f"at ({p[0]:.0f}, {p[1]:.0f})"
    f = world.nearest_feature_cell(p[0], p[1])
    d = world.feature_distance(p[0], p[1], f)
    if d < 150.0:
        return f"at {f.name}"
    a = world.anchor(f, p)
    b = geo.bearing(a, p)
    names = [
        "north",
        "north-east",
        "east",
        "south-east",
        "south",
        "south-west",
        "west",
        "north-west",
    ]
    return f"{round(d, -2):.0f} m {names[int(((b + 22.5) % 360) // 45)]} of {f.name}"


def courier_minutes(world, hq: geo.Point, other: geo.Point) -> float:
    """An aide's ride between the army hq and another point, either way (assumption: the
    same time both ways): straight to the hq's route node, node to node over the road-
    preferring graph (Dijkstra from the hq node, cached), then straight on. Off-graph legs
    ride cross-country at 250 m/min. No way on the raster (water with no bridge or
    ford in between) is math.inf: the aide cannot get through."""
    na, nb = world.node_of(hq), world.node_of(other)
    if na == nb:
        return _leg(world, hq, other)
    m = float(world.minutes_field(hq, COURIER_PROFILE)[world.coarse_ij(other)])
    if not math.isfinite(m):
        return math.inf
    return _leg(world, hq, na) + m + _leg(world, nb, other)


def attempt_minutes(hq: geo.Point, other: geo.Point) -> float:
    """How long an aide who cannot get through is away before his failure is known at hq
    (assumption: he rides halfway, finds no way across and comes back: the straight ride's
    time cross-country)."""
    return geo.dist(hq, other) / BASE_SPEED[COURIER_PROFILE][1]


def _leg(world, a: geo.Point, b: geo.Point) -> float:
    t = float(
        world.segment_minutes(
            COURIER_PROFILE, np.array(a[0]), np.array(a[1]), np.array(b[0]), np.array(b[1])
        )
    )
    return t if math.isfinite(t) else math.inf


@dataclass
class ReportState:
    first_contact: bool = False
    engaged: bool = False
    reached_task: str | None = None
    losses25: bool = False
    last_report: int = 0
    routed: list[str] = field(default_factory=list)

    def to_json(self) -> dict:
        return dict(self.__dict__)


class Command:
    """Messages, reports and the army picture for every side."""

    def __init__(self, sim: Sim):
        self.sim = sim
        self.messages: list[Message] = []
        self.contacts: dict[str, dict[str, Contact]] = {s: {} for s in sim.forces.sides()}
        self.report_state: dict[str, ReportState] = {
            f.id: ReportState() for f in sim.forces.brigades()
        }
        self._seq = 0
        # drill memory: square -> the last minute enemy cavalry was within SQUARE_CLEAR_M;
        # "cavalry>square" -> the minute the cavalry last pulled up before that square
        self.cav_seen: dict[str, int] = {}
        self.pullups: dict[str, int] = {}
        self._digest = hashlib.sha256()
        self._digested = 0

    # ---------------------------------------------------------- messages
    def _mid(self, side: str, kind: MessageKind) -> str:
        self._seq += 1
        return f"{side}-{kind.value}-{self._seq:05d}"

    def army_hq(self, side: str) -> geo.Point:
        f = self.sim.forces
        return f.hq(f.root(side).id)

    def send_order(self, side: str, text: str, tasks: list[Task], now: int) -> list[Message]:
        """Group tasks by addressee; one aide per addressed formation."""
        f = self.sim.forces
        hq = self.army_hq(side)
        root = f.root(side).id
        out = []
        by: dict[str, list[Task]] = {}
        for t in tasks:
            t.issued_at = float(now)
            by.setdefault(t.formation, []).append(t)
        for fid in sorted(by):
            if fid == root or all(t.kind == TaskKind.MOVE_HQ for t in by[fid]):
                dest, delay = hq, 0.0  # the commander's own staff: no aide needed
            else:
                dest = f.hq(fid) if fid in f.formations else (f.units[fid].x, f.units[fid].y)
                delay = courier_minutes(self.sim.world, hq, dest)
            mid = self._mid(side, MessageKind.ORDER)
            through = math.isfinite(delay)
            m = Message(
                id=mid,
                side=side,
                kind=MessageKind.ORDER,
                sender=root,
                recipient=fid,
                text=text,
                sent_at=float(now),
                tasks=by[fid],
                origin=hq,
                destination=dest,
                data={"arrives": now + delay}
                if through
                else {"arrives": None, "undeliverable": True},
            )
            self.messages.append(m)
            out.append(m)
            if not through:  # the aide comes back with the order: no way across
                back = attempt_minutes(hq, dest)
                name = f.formations[fid].name if fid in f.formations else f.units[fid].name
                self.send_report(
                    side,
                    root,
                    f"{clock(self.sim.clock_start, now + back)}: the aide carrying "
                    f"the order to {name} could not get through; he found no way across and "
                    f"has brought the order back.",
                    {"why": ["the aide could not get through"], "undeliverable": m.id},
                    now,
                    delay=back,
                )
        return out

    def send_report(
        self,
        side: str,
        sender: str,
        text: str,
        data: dict,
        now: int,
        kind: MessageKind = MessageKind.REPORT,
        delay: float | None = None,
    ) -> Message:
        f = self.sim.forces
        origin = f.hq(sender) if sender in f.formations else self.army_hq(side)
        hq = self.army_hq(side)
        mid = self._mid(side, kind)
        if delay is None:
            delay = courier_minutes(self.sim.world, hq, origin)
        # a report from a body cut off from hq never arrives
        arrival = (
            {"arrives": now + delay}
            if math.isfinite(delay)
            else {"arrives": None, "undeliverable": True}
        )
        m = Message(
            id=mid,
            side=side,
            kind=kind,
            sender=sender,
            recipient=f.root(side).id,
            text=text,
            sent_at=float(now),
            origin=origin,
            destination=hq,
            data={**data, **arrival},
        )
        self.messages.append(m)
        return m

    def due(self, now: int) -> list[Message]:
        """Messages arriving by `now`, in arrival order (undeliverable ones never do)."""
        out = [
            m
            for m in self.messages
            if m.received_at is None
            and m.data["arrives"] is not None
            and m.data["arrives"] <= now + 1e-9
        ]
        out.sort(key=lambda m: (m.data["arrives"], m.id))
        for m in out:
            m.received_at = float(m.data["arrives"])
        return out

    # ---------------------------------------------------------- contacts
    def _name(self, side: str, s: Sighting) -> str:
        w = self.sim.world
        where = w.nearest_feature_cell(s.x, s.y).name if w.features else f"{s.x:.0f},{s.y:.0f}"
        arm = {
            "infantry": "infantry",
            "cavalry": "cavalry",
            "artillery": "guns",
            "train": "train",
        }.get(s.arm or "", "troops")
        base = f"the enemy {arm} near {where}"
        taken = {c.name for c in self.contacts[side].values()}
        if base not in taken:
            return base
        k = 2
        while f"{base} ({k})" in taken:
            k += 1
        return f"{base} ({k})"

    def learn(self, side: str, s: Sighting, now: int, source: str) -> None:
        known = self.contacts[side]
        c = known.get(s.key)
        if c is not None and c.seen_at > s.seen_at:
            return
        if c is None:
            c = Contact(
                key=s.key,
                name=self._name(side, s),
                arm=s.arm,
                est_men=s.est_men,
                x=s.x,
                y=s.y,
                seen_at=s.seen_at,
                learned_at=now,
                source=source,
                routed=s.routed,
            )
            known[s.key] = c
            self.contacts[side] = dict(sorted(known.items()))
            return
        c.x, c.y, c.seen_at, c.learned_at, c.source = s.x, s.y, s.seen_at, now, source
        c.routed = s.routed
        if s.arm and (c.arm is None or s.ident >= 1):
            c.arm = s.arm
        if s.est_men is not None:
            c.est_men = s.est_men

    def find_contact(self, side: str, name: str) -> Contact | None:
        key = name.casefold()
        for c in self.contacts[side].values():
            if c.name.casefold() == key or c.key.casefold() == key:
                return c
        return None

    # ---------------------------------------------------------- reports
    def brigade_reports(self, now: int, routed_now: list[str]) -> list[Message]:
        sim = self.sim
        f = sim.forces
        out = []
        for b in f.brigades():
            st = self.report_state[b.id]
            bodies = [f.units[u] for u in b.units]
            alive = [u for u in bodies if u.state != UnitState.DESTROYED]
            if not alive:
                continue
            why = []
            known = sim.vision.known(b.id)
            if known and not st.first_contact:
                st.first_contact = True
                why.append("first contact with the enemy")
            if any(u.engaged for u in alive) and not st.engaged:
                st.engaged = True
                why.append("we are engaged")
            task = alive[0].task
            if task is not None and task.kind not in (TaskKind.HOLD, TaskKind.RALLY):
                tid = f"{task.issued_at}:{task.kind.value}:{task.source_text}"
                arrived = sum(1 for u in alive if sim.rt[u.id].phase == "arrived")
                if arrived >= REACHED_FRACTION * len(alive) and st.reached_task != tid:
                    st.reached_task = tid
                    why.append("we have reached our objective")
            why.extend(
                f"{f.units[u].name} has broken" for u in routed_now if f.units[u].parent == b.id
            )
            # strength of the bodies on the map against their own start: a body still to
            # arrive or gone by an exit is neither strength nor loss
            fate = {u.id: sim.offmap[u.id]["fate"] for u in bodies if u.id in sim.offmap}
            away = {k: sum(1 for v in fate.values() if v == k) for k in ("awaiting", "exited")}
            counted = [u for u in bodies if fate.get(u.id) not in ("awaiting", "exited")]
            start = sum(sim.rt[u.id].start_men for u in counted)
            men = sum(u.men for u in alive)
            if start and (start - men) / start >= REPORT_LOSS_FRACTION and not st.losses25:
                st.losses25 = True
                why.append("our losses pass a quarter of our strength")
            if not why and now - st.last_report >= REPORT_EVERY_MIN:
                why.append("situation report")
            if not why:
                continue
            st.last_report = now
            out.append(self._report(b, start, men, why, known, now, away))
        return out

    def _report(self, b, start, men, why, known, now, away=None) -> Message:
        sim = self.sim
        w = sim.world
        pos = sim.forces.hq(b.id)
        seen = sorted(
            (s for s in known.values() if s.seen_at == now or now - s.seen_at <= 5),
            key=lambda s: (s.dist, s.key),
        )
        bits = []
        for s in seen[:6]:
            size = f"about {s.est_men:,} " if s.est_men else ""
            what = s.arm or "troops"
            if s.arm == "artillery" and s.est_men:
                size, what = f"{s.est_men} ", "guns"
            bits.append(
                f"{size}{what} {place(w, (s.x, s.y))}" + (" (in flight)" if s.routed else "")
            )
        enemy = ("Enemy seen: " + "; ".join(bits) + ".") if bits else "No enemy in sight."
        text = (
            f"{clock(sim.clock_start, now)}, {b.commander} ({b.name}) "
            f"{place(w, pos)}: {'; '.join(why)}. {enemy} "
            f"Strength {men:,} of {start:,}."
        )
        away = away or {}

        def bodies_word(n: int) -> str:
            return f"{n} body" if n == 1 else f"{n} bodies"

        if away.get("awaiting"):
            text += f" {bodies_word(away['awaiting'])} yet to arrive."
        if away.get("exited"):
            text += f" {bodies_word(away['exited'])} off the map by an exit."
        data = {
            "brigade": b.id,
            "position": list(pos),
            "men": men,
            "start_men": start,
            "why": why,
            "sightings": [s.to_json() for s in seen],
        }
        data.update({k: n for k, n in away.items() if n})
        return self.send_report(b.side, b.id, text, data, now)

    def receive(self, m: Message, now: int) -> None:
        if m.kind == MessageKind.REPORT:
            for d in m.data.get("sightings", []):
                self.learn(m.side, Sighting.from_json(d), now, m.sender)

    def picture(self, side: str) -> Picture:
        sim = self.sim
        reps = [
            m
            for m in self.messages
            if m.side == side
            and m.received_at is not None
            and m.kind in (MessageKind.REPORT, MessageKind.CLARIFICATION)
        ]
        reps.sort(key=lambda m: (m.received_at, m.id))
        own: dict[str, dict] = {}
        for m in reps:
            if "brigade" in m.data:
                # strength_start: the reported bodies' men at the start (bodies still to arrive
                # or gone by an exit are in neither figure), so men / strength_start is the
                # share left as the brigade reported it
                own[m.data["brigade"]] = {
                    "position": m.data["position"],
                    "men": m.data["men"],
                    "strength_start": m.data.get("start_men"),
                    "as_of": m.sent_at,
                }
        orders = sorted(
            (m for m in self.messages if m.side == side and m.kind == MessageKind.ORDER),
            key=lambda m: (m.sent_at, m.id),
        )
        return Picture(
            side=side,
            now=sim.now,
            clock=clock(sim.clock_start, sim.now),
            hq=self.army_hq(side),
            reports=reps,
            contacts=list(self.contacts[side].values()),
            own=own,
            orders=orders,
        )

    def side_view(self, side: str) -> SideView:
        f = self.sim.forces
        forms = []
        for x in f.formations.values():
            if x.side != side:
                continue
            arms = {u.arm for u in f.bodies(x.id)}
            forms.append(
                FormationView(
                    id=x.id,
                    name=x.name,
                    commander=x.commander,
                    aliases=list(x.aliases),
                    level=x.level,
                    parent=x.parent,
                    arm=Arm(arms.pop()) if len(arms) == 1 else None,
                )
            )
        enemies = [
            EnemyView(
                name=c.name,
                arm=Arm(c.arm) if c.arm else None,
                est_men=c.est_men,
                x=c.x,
                y=c.y,
                last_seen=float(c.seen_at),
                key=c.key,
            )
            for c in self.contacts[side].values()
        ]
        feats = self.sim.world.features
        places = self.places(side)
        hq = self.army_hq(side)
        return SideView(
            side=side,
            formations=forms,
            feature_names=[x.name for x in feats] + list(places),
            enemies=enemies,
            now=float(self.sim.now),
            feature_aliases={x.name: list(x.aliases) for x in feats if x.aliases},
            places=places,
            march_order=self.march_order(side),
            clock_start=self.sim.clock_start,
            feature_points={x.name: tuple(self.sim.world.anchor(x, hq)) for x in feats},
        )

    def march_order(self, side: str) -> list[str]:
        """The side's brigades, head first: each brigade's centroid projected on the side's
        mean facing (the staff's default for "the brigades ahead")."""
        f = self.sim.forces
        bodies = [
            u
            for u in f.units.values()
            if u.side == side and u.state not in (UnitState.ROUTED, UnitState.DESTROYED)
        ]
        if not bodies:
            return []
        sx = sum(math.sin(math.radians(u.facing_deg)) for u in bodies)
        cy = sum(math.cos(math.radians(u.facing_deg)) for u in bodies)
        theta = math.radians(math.degrees(math.atan2(sx, cy)) % 360.0)
        fx, fy = math.sin(theta), math.cos(theta)
        rows = []
        for b in f.brigades():
            if b.side != side:
                continue
            c = f.centroid(b.id)
            if c is not None:
                rows.append((-(c[0] * fx + c[1] * fy), b.id))
        return [fid for _, fid in sorted(rows)]

    def places(self, side: str) -> dict[str, tuple[float, float]]:
        """Relative places as pseudo-features, from the side's own formed bodies now: the
        centroid, the mean facing (assumption: a column on the march faces its road, so
        'left' is left of the line of march), the lateral extremes and a point behind the
        rearmost body (assumption: 500 m)."""
        bodies = [
            u
            for u in self.sim.forces.units.values()
            if u.side == side and u.state not in (UnitState.ROUTED, UnitState.DESTROYED)
        ]
        if not bodies:
            return {}
        c = geo.centroid([(u.x, u.y) for u in bodies])
        sx = sum(math.sin(math.radians(u.facing_deg)) for u in bodies)
        cy = sum(math.cos(math.radians(u.facing_deg)) for u in bodies)
        theta = math.degrees(math.atan2(sx, cy)) % 360.0
        fx, fy = math.sin(math.radians(theta)), math.cos(math.radians(theta))
        rx, ry = fy, -fx  # right-hand axis
        lat = [(u.x - c[0]) * rx + (u.y - c[1]) * ry for u in bodies]
        dep = [(u.x - c[0]) * fx + (u.y - c[1]) * fy for u in bodies]
        t = self.sim.world.terrain
        x0, y0 = t.origin

        def pt(along: float, across: float) -> tuple[float, float]:
            x = c[0] + along * fx + across * rx
            y = c[1] + along * fy + across * ry
            return (
                round(min(max(x, x0 + 1.0), x0 + t.width_m - 1.0), 1),
                round(min(max(y, y0 + 1.0), y0 + t.height_m - 1.0), 1),
            )

        return {
            "our left flank": pt(0.0, min(lat)),
            "our right flank": pt(0.0, max(lat)),
            "our centre": pt(0.0, 0.0),
            "our rear": pt(min(dep) - PLACE_REAR_M, 0.0),
        }

    def snapshot(self) -> dict:
        """Messages in transit in full; delivered ones by a running digest (they are frozen)."""
        while self._digested < len(self.messages):
            m = self.messages[self._digested]
            if m.received_at is None and not m.data.get("undeliverable"):
                break  # in transit; an undeliverable message is as frozen as a delivered one
            self._digest.update(dumps(message_json(m)).encode())
            self._digested += 1
        return {
            "messages": [message_json(m) for m in self.messages[self._digested :]],
            "delivered": [self._digested, self._digest.hexdigest()],
            "contacts": {
                s: {k: c.to_json() for k, c in v.items()} for s, v in sorted(self.contacts.items())
            },
            "reports": {k: v.to_json() for k, v in sorted(self.report_state.items())},
            "seq": self._seq,
            **({"cav_seen": dict(sorted(self.cav_seen.items()))} if self.cav_seen else {}),
            **({"pullups": dict(sorted(self.pullups.items()))} if self.pullups else {}),
        }

    def note_events(self, events) -> None:
        """Remember the tick's pull-ups (combat's `charge_aborted`) for the drills."""
        for e in events:
            if e.kind == "charge_aborted":
                self.pullups[f"{e.data['attacker']}>{e.data['defender']}"] = e.tick

    def shuns(self, cav: str, target: str) -> bool:
        """Has `cav` pulled up before `target` (a square) so that it does not charge it now?"""
        t = self.pullups.get(f"{cav}>{target}")
        if t is None:
            return False
        return (
            self.sim.now - t < PULLUP_BAR_MIN
            or self.sim.forces.units[target].state == UnitState.SQUARE
        )


def message_json(m: Message) -> dict:
    return {
        "id": m.id,
        "side": m.side,
        "kind": m.kind.value,
        "sender": m.sender,
        "recipient": m.recipient,
        "text": m.text,
        "sent_at": m.sent_at,
        "received_at": m.received_at,
        "tasks": [task_to_json(t) for t in m.tasks],
        "data": m.data,
    }


# ---------------------------------------------------------------------------
# References and conditions


def resolve_ref(
    sim: Sim, side: str, ref: Ref | None, near: geo.Point | None = None, brigade: str | None = None
) -> tuple[geo.Point | None, str | None]:
    """(point, enemy key) for a reference, as known to `side` (brigade sight first)."""
    if ref is None:
        return None, None
    if ref.kind == RefKind.POINT and ref.point is not None:
        return (float(ref.point[0]), float(ref.point[1])), None
    if ref.kind == RefKind.FEATURE and ref.name and sim.world.has_feature(ref.name):
        return sim.world.anchor(sim.world.feature(ref.name), near), None
    if ref.kind == RefKind.FEATURE and ref.name and ref.point is None:
        p = sim.command.places(side).get(ref.name.casefold())
        if p is not None:  # a relative place named without its point: as it stands now
            return p, None
    if ref.kind == RefKind.FRIENDLY and ref.name:
        fid = sim.forces.resolve(ref.name, side)
        if fid is not None:
            return sim.forces.hq(fid), None
        return None, None
    if ref.kind == RefKind.ENEMY and ref.name:
        c = sim.command.find_contact(side, ref.name)
        key = c.key if c else (ref.name if ref.name in sim.forces.units else None)
        if key is None:
            return None, None
        if brigade is not None:
            s = sim.vision.known(brigade).get(key)
            if s is not None:
                return (s.x, s.y), key
        if c is not None:
            return (c.x, c.y), key
        return None, key
    if ref.point is not None:
        return (float(ref.point[0]), float(ref.point[1])), None
    return None, None


def formation_knowledge(sim: Sim, side: str, fid: str) -> dict[str, Sighting | Contact]:
    """What the commander of `fid` knows of the enemy: the army commander his picture (what his
    hq saw and what reports have told him); any other formation's commander what its brigades
    see and remember (assumption: a wing or column commander rides with his brigades and is told
    at once); the newest sighting per enemy body."""
    f = sim.forces
    if fid == f.root(side).id:
        return dict(sim.command.contacts[side])
    out: dict[str, Sighting | Contact] = {}
    for b in sorted({u.parent for u in f.bodies(fid)}):
        for k, s in sim.vision.known(b).items():
            if k not in out or s.seen_at > out[k].seen_at:
                out[k] = s
    return out


def condition_met(sim: Sim, side: str, fid: str, cond: Condition | float | None) -> bool:
    if cond is None:
        return True
    if isinstance(cond, int | float):
        return sim.now >= cond
    f = sim.forces
    subj = cond.subject
    if cond.kind == ConditionKind.TIME:
        return cond.at is None or sim.now >= cond.at
    sub_fid = fid
    if subj is not None and subj.kind == RefKind.FRIENDLY and subj.name:
        sub_fid = f.resolve(subj.name, side) or fid
    bodies = f.bodies(sub_fid)
    if cond.kind == ConditionKind.WHEN_ENGAGED:
        return any(u.engaged for u in bodies)
    if cond.kind == ConditionKind.WHEN_ROUTS:
        if subj is not None and subj.kind == RefKind.ENEMY and subj.name:
            # from what the formation's commander has seen or been told, not the truth
            _, key = resolve_ref(sim, side, subj)
            seen = formation_knowledge(sim, side, fid).get(key) if key is not None else None
            return seen is not None and seen.routed
        return any(u.state == UnitState.ROUTED for u in bodies)
    if cond.kind == ConditionKind.WHEN_REACHED:
        if cond.place is not None and subj is not None and subj.kind == RefKind.FRIENDLY:
            # a friendly formation reaching or holding a place ("once Hülsen holds Křečhoř")
            p, _ = resolve_ref(sim, side, cond.place)
            c = f.centroid(sub_fid)
            if p is None or c is None:
                return False
            if (
                cond.place.kind == RefKind.FEATURE
                and cond.place.name
                and sim.world.has_feature(cond.place.name)
            ):
                return sim.world.inside(c[0], c[1], cond.place.name) or geo.dist(c, p) <= 200.0
            return geo.dist(c, p) <= 200.0
        if subj is not None and subj.kind in (RefKind.FEATURE, RefKind.POINT):
            p, _ = resolve_ref(sim, side, subj)
            c = f.centroid(fid)
            if p is None or c is None:
                return False
            if subj.kind == RefKind.FEATURE:
                return sim.world.inside(c[0], c[1], subj.name) or geo.dist(c, p) <= 200.0
            return geo.dist(c, p) <= 200.0
        alive = [u for u in bodies if u.state != UnitState.DESTROYED]
        return bool(alive) and sum(sim.rt[u.id].phase == "arrived" for u in alive) >= (
            REACHED_FRACTION * len(alive)
        )
    if cond.kind == ConditionKind.WHEN_ENEMY_SEEN:
        known = formation_knowledge(sim, side, fid)
        if subj is not None and subj.kind == RefKind.ENEMY and subj.name:
            _, key = resolve_ref(sim, side, subj)
            return key is not None and key in known
        if subj is not None and subj.kind == RefKind.FEATURE and subj.name:
            feat = sim.world.feature(subj.name)
            return any(sim.world.feature_distance(s.x, s.y, feat) <= 300.0 for s in known.values())
        return bool(known)
    return False


# ---------------------------------------------------------------------------
# Task application: decompose a formation task to its bodies


def _lateral(theta: float, p: geo.Point, origin: geo.Point) -> float:
    r = math.radians(theta + 90.0)
    return (p[0] - origin[0]) * math.sin(r) + (p[1] - origin[1]) * math.cos(r)


# Only a move or a withdrawal takes a body off the map by an exit it names; a screen, hold or
# attack whose place is an exit keeps the body on the map (a screen of a wood's edge on the map's
# edge is not a march off it).
LEAVE_KINDS = (TaskKind.ADVANCE, TaskKind.WITHDRAW)


def leaving_exits(sim: Sim, task: Task | None) -> list:
    """The exit features by which a body under `task` leaves the map: those its objective or
    route names, for a move or a withdrawal only."""
    if task is None or task.kind not in LEAVE_KINDS:
        return []
    w = sim.world
    out = []
    for r in (task.objective, *task.route):
        if r is not None and r.kind == RefKind.FEATURE and r.name and w.has_feature(r.name):
            f = w.feature(r.name)
            if f.kind == FeatureKind.EXIT:
                out.append(f)
    return out


def exit_objective(sim: Sim, task: Task):
    """The exit a leaving task's objective names, else None."""
    ex = leaving_exits(sim, task)
    o = task.objective
    return next((f for f in ex if o is not None and f.name == o.name), None)


def _column_slots(
    sim: Sim, wagons: list[Unit], p: geo.Point, cen: geo.Point
) -> dict[str, geo.Point]:
    """Places for a train's bodies in column: the one nearest the objective at it, each next
    one TRAIN_SPACING_M farther back along its route from the formation."""
    _, pts = sim.world.path_cost(cen, p, "train")
    line = [p, *reversed([cen, *pts[:-1]])] if pts else [p, cen]
    out: dict[str, geo.Point] = {}
    order = sorted(wagons, key=lambda u: (geo.dist((u.x, u.y), p), u.id))
    for k, u in enumerate(order):
        want, q = k * TRAIN_SPACING_M, line[-1]
        for a, b in itertools.pairwise(line):
            seg = geo.dist(a, b)
            if want <= seg:
                q = geo.toward(a, b, want) if seg > 0 else a
                break
            want -= seg
        out[u.id] = (float(q[0]), float(q[1]))
    return out


def passable_near(sim: Sim, u: Unit, q: geo.Point) -> geo.Point:
    """`q` if the body may stand there, else the nearest cell centre within SLOT_SEARCH_M it
    may (a slot in a wood for wagons, or off the map, is moved), else `q`."""
    w = sim.world
    arm = profile_arm(profile_for(u))
    if w.passable(q[0], q[1], arm):
        return q
    c = w.cell
    n = int(SLOT_SEARCH_M // c)
    i0, j0 = sym_floor(q[1], w.oy, c, w.cy), sym_floor(q[0], w.ox, c, w.cx)
    best = None
    for r in range(1, n + 1):
        for di in range(-r, r + 1):
            for dj in (-r, r) if abs(di) != r else range(-r, r + 1):
                x, y = w.ox + (j0 + dj + 0.5) * c, w.oy + (i0 + di + 0.5) * c
                if w.passable(x, y, arm):
                    # nearest; ties by distance to the field's centre, then by side, both
                    # kept by the 180° rotation, never by the order of the search
                    key = (
                        math.hypot(x - q[0], y - q[1]),
                        math.hypot(x - w.cx, y - w.cy),
                        (x - q[0]) * (w.cy - q[1]) - (y - q[1]) * (w.cx - q[0]),
                    )
                    if best is None or key < best[0]:
                        best = (key, (x, y))
        if best is not None:
            return best[1]
    return q


def same_orders(a: Task | None, b: Task | None) -> bool:
    """Whether two tasks order the same thing, the wording and the times aside: the same
    order sent again."""
    if a is None or b is None:
        return a is b

    def bare(t: Task) -> Task:
        return replace(t, source_text="", issued_at=None, received_at=None, then=None)

    return bare(a) == bare(b) and same_orders(a.then, b.then)


def apply_task(sim: Sim, task: Task) -> None:
    f = sim.forces
    side = (
        f.formations[task.formation].side
        if task.formation in f.formations
        else f.units[task.formation].side
    )
    if task.kind == TaskKind.MOVE_HQ:
        sim.hq_tasks[task.formation if task.formation in f.formations else f.root(side).id] = task
        return
    offmap = getattr(sim, "offmap", {})
    if offmap and not task.tentative:  # bodies still to arrive take the task with them
        for u in f.bodies(task.formation):
            rec = offmap.get(u.id)
            if rec is not None and rec["fate"] == "awaiting":
                u.task = task
    bodies = [u for u in f.bodies(task.formation) if u.state != UnitState.DESTROYED]
    if not bodies:
        return
    if task.tentative:  # an order the staff could not read: only formations without a task
        bodies = [u for u in bodies if u.task is None]
        if not bodies:
            return
    cen = geo.centroid([(u.x, u.y) for u in bodies])
    brigade = bodies[0].parent
    p, key = resolve_ref(sim, side, task.objective, near=cen, brigade=brigade)
    via = []
    for r in task.route:
        q, _ = resolve_ref(sim, side, r, near=cen)
        if q is not None:
            via.append(q)
    if task.kind == TaskKind.WITHDRAW and p is None:
        e = _nearest_known_of(sim, bodies, cen)
        t = sim.world.terrain  # the map's middle counts its origin (a designed pack's is not 0)
        away = (
            geo.bearing(e, cen) if e else (180.0 if cen[1] > t.origin[1] + t.height_m / 2 else 0.0)
        )
        p = geo.offset(cen, away, WITHDRAW_DEFAULT_M)
    offsets: dict[str, geo.Point] = {}
    # a formation leaving by an exit: every body heads for the exit itself, the point of it
    # nearest to the body (as start_body heads an arriving body for its objective), queueing
    # on the route behind its neighbours instead of spreading a line across the exit
    leave_by = exit_objective(sim, task) if p is not None else None
    if p is not None and leave_by is None:  # a rally at a place forms there too
        theta = geo.bearing(cen, p) if geo.dist(cen, p) > 1.0 else bodies[0].facing_deg
        # order by brigade lateral position, then own lateral position (no crossing)
        blat: dict[str, float] = {}
        for u in bodies:
            blat.setdefault(u.parent, 0.0)
        for b in blat:
            mem = [u for u in bodies if u.parent == b]
            blat[b] = sum(_lateral(theta, (u.x, u.y), cen) for u in mem) / len(mem)
        order = sorted(
            bodies, key=lambda u: (blat[u.parent], _lateral(theta, (u.x, u.y), cen), u.id)
        )
        widths = [frontage(u, UnitState.LINE) + INTERVAL_M for u in order]
        total = sum(widths)
        acc = -total / 2.0
        for u, wdt in zip(order, widths, strict=True):
            lat = acc + wdt / 2.0
            acc += wdt
            q = geo.offset(p, theta + 90.0, lat)
            offsets[u.id] = (q[0] - p[0], q[1] - p[1])
    # a train's bodies (wagons, parks) in column along the road behind the objective
    wagons = [u for u in bodies if u.arm == Arm.TRAIN]
    column = (
        _column_slots(sim, wagons, p, cen)
        if wagons and p is not None and leave_by is None and task.kind != TaskKind.RALLY
        else {}
    )
    # covering body for a withdrawal: the one nearest the enemy
    cover_id = None
    if task.kind == TaskKind.WITHDRAW:
        e = _nearest_known_of(sim, bodies, cen)
        if e is not None and len(bodies) > 1:
            cover_id = min(bodies, key=lambda u: (geo.dist((u.x, u.y), e), u.id)).id
    hold_on = (
        sim.world.feature(task.objective.name)
        if task.kind == TaskKind.HOLD
        and task.objective is not None
        and task.objective.kind == RefKind.FEATURE
        and task.objective.name
        and sim.world.has_feature(task.objective.name)
        else None
    )
    for u in bodies:
        rt = sim.rt[u.id]
        again = same_orders(u.task, task)
        u.task = task
        u.order_log.append({"at": sim.now, "kind": task.kind.value, "text": task.source_text})
        if again:  # the order it is carrying out, sent again: it carries on as it was
            continue
        rt.offset = offsets.get(u.id, (0.0, 0.0))
        rt.slot = (p[0] + rt.offset[0], p[1] + rt.offset[1]) if p is not None else (u.x, u.y)
        if hold_on is not None and sim.world.feature_distance(u.x, u.y, hold_on) <= HOLD_ON_M:
            rt.slot = (u.x, u.y)  # already on the place it is to hold: stay where it stands
        if leave_by is not None:
            rt.slot = sim.world.anchor(leave_by, (u.x, u.y))
        elif u.id in column:
            rt.slot = column[u.id]
            rt.offset = (rt.slot[0] - p[0], rt.slot[1] - p[1])
        if p is not None and leave_by is None:
            rt.slot = passable_near(sim, u, rt.slot)
        rt.target = (
            key if task.kind in (TaskKind.ATTACK, TaskKind.CHARGE, TaskKind.BOMBARD) else None
        )
        rt.via = list(via)
        rt.route, rt.route_goal = [], None
        rt.phase, rt.phase_since = "march", sim.now
        rt.origin = (u.x, u.y)
        rt.cover_wait = WITHDRAW_COVER_MIN if u.id == cover_id else 0
        rt.replan_at = sim.now


def start_body(sim: Sim, u: Unit, task: Task, fallback: geo.Point) -> None:
    """One body takes up `task` on its own (a body arriving on the map): it heads
    for the task's objective itself (no slot in its formation's line), else for `fallback`."""
    here = (u.x, u.y)
    p, key = resolve_ref(sim, u.side, task.objective, near=here, brigade=u.parent)
    via = []
    for r in task.route:
        q, _ = resolve_ref(sim, u.side, r, near=here)
        if q is not None:
            via.append(q)
    rt = sim.rt[u.id]
    u.task = task
    u.order_log.append({"at": sim.now, "kind": task.kind.value, "text": task.source_text})
    rt.offset = (0.0, 0.0)
    rt.slot = p if p is not None and task.kind != TaskKind.RALLY else fallback
    rt.target = key if task.kind in (TaskKind.ATTACK, TaskKind.CHARGE, TaskKind.BOMBARD) else None
    rt.via = via
    rt.route, rt.route_goal = [], None
    rt.phase, rt.phase_since = "march", sim.now
    rt.origin = here
    rt.cover_wait = 0
    rt.replan_at = sim.now


def _nearest_known_of(sim: Sim, bodies: list[Unit], cen: geo.Point) -> geo.Point | None:
    best = None
    for b in sorted({u.parent for u in bodies}):
        for s in sim.vision.known(b).values():
            if s.routed:
                continue
            d = geo.dist(cen, (s.x, s.y))
            if best is None or d < best[0]:
                best = (d, (s.x, s.y))
    return best[1] if best else None
