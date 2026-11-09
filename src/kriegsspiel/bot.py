"""A Jev-free doctrine opponent with two presets, strong and weak.

`BotCommander(sim, side, doctrine)` is a `commander.Commander`, woken every reaction time,
that never writes prose and never calls the staff: at each consultation it reads
`sim.picture(side)` (what has reached its headquarters: reports, contacts, its own orders) and
submits structured `Task`s with `Sim.submit_tasks`, so they ride by aide with the courier
delays like any written order. It returns None, so the play loop submits nothing else.

What it knows beyond the picture is what a general is told before the battle: the ground
(features, heights, roads), its own order of battle with each body's start place, arrival time
and entry, and the objective of the pack's ordinal verdict (`mission.json`). It never reads the
enemy's true positions or its own bodies' true state after the start: own brigades are where
their last report put them (strong: plus the progress its last order should have made since).

Doctrine (one code for every pack):

- the objective is occupied and held by the infantry; strong holds back a reserve
  (`reserve_fraction` of the infantry, the bodies farthest from the objective);
- an element with formed enemies within `ENEMY_NEAR_M` of the objective attacks when the
  visible local odds (own men allotted near the objective over the enemy's estimated men)
  reach `concentration`; else it holds the objective if it is there, or waits at a staging
  point short of it;
- strong's reserve is committed where its weight tips the odds: at once when the objective is
  outnumbered or in distress, `COMMIT_AFTER_MIN` after formed enemies are first seen there,
  and whatever is left `LATE_COMMIT_MIN` before the end;
- an enemy body seen routed, seen to have lost a third of the most men it was seen with
  (strong: in any report's sightings, not only the picture's latest), or seen rallied within
  `SHAKEN_MIN` of a rout (strong: shaken), within reach is counterattacked (infantry) or
  pursued (cavalry);
- strong halts a brigade that reports a body broken (RALLY, no formed enemy near);
- guns go to the highest ground within 900 m of the objective and hold there unlimbered;
  cavalry goes to the flanks of the objective (advancing with ENGAGE, so it charges what comes
  within reach) and pursues broken bodies; a train halts;
- a side whose reported losses pass `loss_threshold` withdraws 1.5 km back from the enemy.
  Weak goes all at once; strong in two stages: the rear guard (the freshest elements nearest
  the enemy, at most `REAR_GUARD_SHARE` of the men) holds for `REAR_GUARD_MIN`, then follows.

Deterministic: no wall clock, no randomness, iteration in sorted order; a recorded bot game
replays bit-identically (`replay.replay_game` rebuilds the bot from the header instead of serving
logged replies).
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from . import geometry as geo
from .clock import at_minute
from .command import courier_minutes
from .commander import CommanderBase
from .types import (
    Condition,
    ConditionKind,
    Feature,
    GeometryKind,
    Manner,
    OnContact,
    Ref,
    RefKind,
    Task,
    TaskKind,
    UnitState,
)
from .verdict import load as load_mission
from .verdict import ordinal_params

# ---------------------------------------------------------------------------
# Constants (assumptions)
ENEMY_NEAR_M = 1000.0  # formed enemies this near the objective contest it
OWN_NEAR_M = 2000.0  # own allotted elements this near the objective count in its odds
STAGE_M = 1200.0  # an outnumbered element waits this far short of the objective
AT_PLACE_M = 600.0  # an element this near the objective is "there" (defends it)
CONTACT_FRESH_MIN = 45  # contacts older than this are not counted in the odds
ROUTED_FRESH_MIN = 10  # a rout seen within this is pursued
PURSUE_M = 3000.0  # cavalry pursues broken bodies within this
COUNTER_M = 1200.0  # infantry counterattacks a weakened enemy within this
WEAKENED = 0.67  # an enemy seen at two thirds of the most men it was seen with is weakened
FLANK_M = 1500.0  # cavalry flank posts this far to either side of the objective
GUN_RADII = (0.0, 300.0, 600.0, 900.0)  # commanding ground is searched on these circles
GUN_BEARINGS = 12
RESERVE_BACK_M = 1000.0  # the reserve waits this far behind the objective
WITHDRAW_BACK_M = 1500.0  # a withdrawal falls back this far
INSET_M = 600.0  # posts and withdrawal points stay this far inside the map
DISTRESS_MIN = 30  # a rout or quarter-lost report marks its element for this long
RALLY_MIN = 15  # a rally order holds the brigade this long (morale.RALLY_MORALE re-forms)
RALLY_CLEAR_M = 1000.0  # no rally with a formed enemy known this near
REORDER_M = 500.0  # a point objective that moved less than this is not a new order
UNKNOWN_MEN = {"infantry": 600, "cavalry": 400, "artillery": 150, "train": 100}
UNKNOWN_ARM_MEN = 500  # a body of unknown arm and number
GUN_MEN = 25  # a battery seen as N guns counts as N x this many men in the odds
# a staff officer's planning rate with halts, below the drill speeds (own dead reckoning only)
MARCH_M_MIN = {"infantry": 50.0, "cavalry": 90.0, "artillery": 40.0, "train": 30.0}
ENGAGED_FRESH_MIN = 35  # an element that reported the enemy in sight (or engaged) this
# recently is not reckoned on: in contact it moves as the fight goes, not as ordered
COMMIT_AFTER_MIN = 20  # strong: the reserve goes in this long after formed enemies are seen
LATE_COMMIT_MIN = 150  # strong: whatever is in reserve this long before the end goes in
SHAKEN_MIN = 30  # an enemy seen routed and then formed again within this is still shaken
REAR_GUARD_SHARE = 0.25  # strong: at most this share of the fighting men stays as rear guard
REAR_GUARD_MIN = 25  # the rear guard holds this long after the withdrawal starts, then goes


@dataclass(frozen=True)
class Doctrine:
    name: str
    aggression: float  # 0..1: BOLD attacks above 0.6, and the counterattack odds
    reserve_fraction: float  # of the infantry men held back
    loss_threshold: float  # reported own losses at which the army withdraws
    concentration: float  # visible local odds needed to attack
    reaction_min: int  # minutes between re-plans
    commit_reserve: bool
    rally: bool = False  # halt a brigade that reports a body broken, to let it re-form
    reckon: bool = False  # own positions: freshest report plus the last order's progress
    read_reports: bool = False  # enemy strength history from every report's sightings
    staged: bool = False  # withdrawal in two stages: the rest first, the rear guard after


PRESETS = {
    # the presets differ in the reserve (weak keeps none) and in how much of its picture each
    # reads (strong reckons its own positions and reads every report's sightings)
    "strong": Doctrine(
        "strong",
        aggression=0.7,
        reserve_fraction=0.15,
        loss_threshold=0.5,
        concentration=1.3,
        reaction_min=5,
        commit_reserve=True,
        rally=True,
        read_reports=True,
        reckon=True,
        staged=True,
    ),
    "weak": Doctrine(
        "weak",
        aggression=0.4,
        reserve_fraction=0.0,
        loss_threshold=0.45,
        concentration=0.6,
        reaction_min=30,
        commit_reserve=False,
    ),
}


def doctrine_for(spec: str) -> Doctrine:
    """'bot' or 'bot:strong' -> strong, 'bot:weak' -> weak."""
    _, _, name = spec.partition(":")
    name = name or "strong"
    if name not in PRESETS:
        raise ValueError(f"unknown bot preset {name!r}; one of {sorted(PRESETS)}")
    return PRESETS[name]


def is_bot(spec: str) -> bool:
    return spec == "bot" or spec.startswith("bot:")


# ---------------------------------------------------------------------------


@dataclass
class Element:
    """A formation that holds bodies directly (a brigade, a column, a battery): what the bot
    orders. Bodies of a child formation move with a parent's order (Forces.bodies)."""

    id: str
    arm: str
    start_men: int
    men: int
    pos: geo.Point  # as last reported (or the start / entry)
    as_of: float
    parent: str | None = None  # the nearest ancestor element, if any
    children: list[str] = field(default_factory=list)
    arrives_at: float | None = None
    est: geo.Point | None = None  # strong: reckoned position now
    engaged_at: float = -1e9  # when a report last saw the enemy or said "we are engaged"

    @property
    def at(self) -> geo.Point:
        return self.est if self.est is not None else self.pos


@dataclass
class Place:
    name: str
    point: geo.Point
    feature: Feature


def _arm_of(bodies) -> str:
    men: dict[str, int] = {}
    for u in bodies:
        men[u.arm.value] = men.get(u.arm.value, 0) + max(1, u.men)
    return max(sorted(men), key=lambda a: men[a])


class BotCommander(CommanderBase):
    def __init__(self, sim, side: str, doctrine: Doctrine | str = "strong"):
        super().__init__()
        self.sim = sim
        self.side = side
        self.doctrine = (
            doctrine
            if isinstance(doctrine, Doctrine)
            else doctrine_for(
                "bot:" + doctrine if not str(doctrine).startswith("bot") else doctrine
            )
        )
        self.name = f"bot:{self.doctrine.name}"
        self.world = sim.world
        f = sim.forces
        self.root = f.root(side).id
        # own elements from the order of battle and the deployment (static knowledge)
        self.elements: dict[str, Element] = {}
        for b in sorted(f.brigades(side), key=lambda x: x.id):
            direct = [f.units[u] for u in b.units]
            arr = [u.arrives_at for u in direct if u.arrives_at is not None]
            pos = geo.centroid([(u.x, u.y) for u in direct])
            self.elements[b.id] = Element(
                id=b.id,
                arm=_arm_of(direct),
                start_men=sum(sim.rt[u.id].start_men for u in direct),
                men=sum(sim.rt[u.id].start_men for u in direct),
                pos=(float(pos[0]), float(pos[1])),
                as_of=0.0,
                arrives_at=min(arr) if arr else None,
            )
        for e in self.elements.values():
            anc = f.ancestors(e.id) if e.id in f.formations else []
            par = next((a for a in anc if a in self.elements and a != e.id), None)
            e.parent = par
            if par is not None:
                self.elements[par].children.append(e.id)
        self.start_centroid = self._centroid(
            [e for e in self.elements.values() if e.arrives_at is None]
            or list(self.elements.values())
        )
        end = sim.end_clock
        self.limit = int(at_minute(sim.clock_start, end)) if end else 600
        self.place = self._objective(sim.scenario_dir)
        self.allotted: set[str] = set()  # infantry elements sent to the objective
        self.reserve: list[str] = []
        self.flank: dict[str, int] = {}  # cavalry element -> -1 left, +1 right
        self.flank_posts: dict[str, geo.Point] = {}
        self.reserve_post: geo.Point | None = None
        self.guns: dict[str, geo.Point] = {}
        self.sent: dict[str, tuple] = {}  # element -> (signature, point) of its last order
        self.sent_at: dict[str, float] = {}
        self.goal: dict[str, tuple[geo.Point | None, float]] = {}  # element -> (goal, eta)
        self.max_seen: dict[str, int] = {}
        self.routed_at: dict[str, float] = {}  # enemy key -> last time seen routed
        self.distress: dict[str, float] = {}
        self.broken: dict[str, float] = {}  # element -> when a report said a body broke
        self.rally_until: dict[str, float] = {}
        self.contested_since: float | None = None  # formed enemies first seen at the objective
        self.reports_seen = 0
        self.strength: dict[str, tuple[int, int]] = {}  # brigade -> (men, start) as reported
        self.withdrawing = False
        self.withdraw_at: float | None = None
        self.guard: list[str] = []
        self.last_plan: int | None = None
        self._initial_allotment()

    # ------------------------------------------------------------ static setup
    def _centroid(self, els: list[Element]) -> geo.Point:
        tot = sum(max(1, e.men) for e in els) or 1
        return (
            sum(e.pos[0] * max(1, e.men) for e in els) / tot,
            sum(e.pos[1] * max(1, e.men) for e in els) / tot,
        )

    def _objective(self, scenario_dir) -> Place:
        """The objective of the pack's ordinal verdict, which the side is to hold."""
        name = ordinal_params(load_mission(scenario_dir))["objective"]
        f = self.world.feature(name)
        return Place(name, self._anchor(f), f)

    def _anchor(self, f: Feature) -> geo.Point:
        if f.geometry_kind == GeometryKind.POLYGON:
            c = geo.ring_centroid(f.coords)
        else:
            c = self.world.anchor(f, self.start_centroid)
        return (float(c[0]), float(c[1]))

    def _initial_allotment(self) -> None:
        d = self.doctrine
        fighting = [e for e in self.elements.values() if e.arm == "infantry"]
        if d.reserve_fraction > 0 and len(fighting) > 2:
            want = d.reserve_fraction * sum(e.start_men for e in fighting)
            main = self.place.point
            # the reserve: the infantry farthest from the objective (it has time to come)
            got = 0.0
            for e in sorted(fighting, key=lambda e: (-geo.dist(e.pos, main), e.id)):
                if got + e.start_men > want * 1.2 and got > 0:
                    continue
                if e.arrives_at is not None and got > 0:
                    continue
                self.reserve.append(e.id)
                got += e.start_men
                if got >= want:
                    break
        k = 0
        for e in sorted(self.elements.values(), key=lambda e: e.id):
            if e.arm == "cavalry":
                self.flank[e.id] = -1 if k % 2 == 0 else 1
                k += 1

    # ------------------------------------------------------------ protocol
    @property
    def wake_at(self) -> list[int]:
        return list(range(0, self.limit + 1, max(1, self.doctrine.reaction_min)))

    def orders(self, brief: str, now: int) -> str | None:
        self.last = {"wall_s": 0.0, "meta": {}}
        if self.last_plan is not None and now < self.last_plan + self.doctrine.reaction_min:
            return None
        self.last_plan = now
        tasks = self.plan(now)
        if tasks:
            text = "; ".join(t.source_text for t in tasks)
            self.sim.submit_tasks(self.side, tasks, at=float(now), text=f"[{self.name}] {text}")
        self.last = {"wall_s": 0.0, "meta": {"tasks": len(tasks)}}
        return None

    # ------------------------------------------------------------ picture
    def _read_picture(self, now: int):
        pic = self.sim.picture(self.side)
        for bid, st in sorted(pic.own.items()):
            e = self.elements.get(bid)
            if e is not None and st["as_of"] >= e.as_of:
                e.pos = (float(st["position"][0]), float(st["position"][1]))
                e.men = int(st["men"])
                e.as_of = float(st["as_of"])
        for m in pic.reports[self.reports_seen :]:
            if "brigade" in m.data and "start_men" in m.data:
                self.strength[m.data["brigade"]] = (int(m.data["men"]), int(m.data["start_men"]))
            why = " ".join(m.data.get("why", []))
            bid = m.data.get("brigade") or m.sender
            if bid in self.elements and ("has broken" in why or "losses pass a quarter" in why):
                self.distress[bid] = float(now)
            if bid in self.elements and "has broken" in why:
                self.broken[bid] = float(m.sent_at)
            if bid in self.elements and ("engaged" in why or m.data.get("sightings")):
                self.elements[bid].engaged_at = float(m.sent_at)
            if self.doctrine.read_reports:
                for s in m.data.get("sightings", []):
                    if s.get("est_men") is not None and s.get("arm") != "train":
                        n = int(s["est_men"]) * (GUN_MEN if s.get("arm") == "artillery" else 1)
                        self.max_seen[s["key"]] = max(self.max_seen.get(s["key"], 0), n)
                    if s.get("routed"):
                        self.routed_at[s["key"]] = max(
                            self.routed_at.get(s["key"], -1e9), float(s["seen_at"])
                        )
        self.reports_seen = len(pic.reports)
        contacts = []
        for c in pic.contacts:
            men = self._men_of(c)
            if c.est_men is not None:  # a body seen too far to count says nothing of its size
                self.max_seen[c.key] = max(self.max_seen.get(c.key, 0), men)
            if c.routed:
                self.routed_at[c.key] = max(self.routed_at.get(c.key, -1e9), float(c.seen_at))
            if now - c.seen_at <= CONTACT_FRESH_MIN:
                contacts.append(c)
        if self.doctrine.reckon:
            for e in self.elements.values():
                e.est = self._reckon(e, now)
        return pic, contacts

    def _reckon(self, e: Element, now: int) -> geo.Point:
        """Where the element should be now: its last reported position (or start, or entry),
        moved toward its last order's goal at the planning march rate for the time since the
        later of the report and the order's estimated arrival; not past the goal, and not at
        all while it reports itself engaged."""
        if e.arrives_at is not None and now < e.arrives_at:
            return e.pos
        goal, eta = self.goal.get(e.id, (None, None))
        if goal is None or eta is None or now - e.engaged_at <= ENGAGED_FRESH_MIN:
            return e.pos
        t0 = max(e.as_of, eta, e.arrives_at or 0.0)
        if now <= t0:
            return e.pos
        rate = MARCH_M_MIN.get(e.arm, 50.0)
        q = geo.toward(e.pos, goal, rate * (now - t0))
        return (float(q[0]), float(q[1]))

    def _men_of(self, c) -> int:
        if c.est_men is None:
            return UNKNOWN_MEN.get(c.arm, UNKNOWN_ARM_MEN)
        if c.arm == "artillery":
            return int(c.est_men) * GUN_MEN
        return int(c.est_men)

    def _weakened(self, c, now: int) -> bool:
        if c.est_men is not None and self._men_of(c) <= WEAKENED * self.max_seen.get(c.key, 0):
            return True
        if not self.doctrine.read_reports:
            return False
        r = self.routed_at.get(c.key)
        return r is not None and not c.routed and now - r <= SHAKEN_MIN

    # ------------------------------------------------------------ planning
    def plan(self, now: int) -> list[Task]:
        d = self.doctrine
        pic, contacts = self._read_picture(now)
        formed = [c for c in contacts if not c.routed and c.arm != "train"]
        t = self.world.terrain  # no formed enemy known: the middle of the map, origin counted
        enemy_c = (
            geo.centroid([(c.x, c.y) for c in formed])
            if formed
            else (t.origin[0] + t.width_m / 2, t.origin[1] + t.height_m / 2)
        )
        live = dict(self.elements)
        desired: dict[str, tuple[Task, tuple]] = {}

        start, lost = 0, 0
        for e in live.values():
            if e.arm == "train":
                continue
            men, st = self.strength.get(e.id, (e.start_men, e.start_men))
            start += st
            lost += max(0, st - men)
        if not self.withdrawing and start and lost / start >= d.loss_threshold:
            self.withdrawing = True
            self.withdraw_at = float(now)

        for e in self._of(live, "train"):
            desired[e.id] = self._task(TaskKind.HOLD, e.id, None, "the train halts")

        if self.withdrawing:
            self._plan_withdrawal(now, live, formed, enemy_c, desired)
        else:
            self._plan_fight(now, live, contacts, formed, enemy_c, desired)
        return self._emit(now, pic, desired)

    def _of(self, live: dict[str, Element], arm: str) -> list[Element]:
        return [e for k, e in sorted(live.items()) if e.arm == arm]

    def _task(
        self,
        kind: TaskKind,
        fid: str,
        obj: Ref | None,
        why: str,
        *,
        manner: Manner = Manner.MEASURED,
        on_contact: OnContact = OnContact.ENGAGE,
        state: UnitState | None = None,
    ) -> tuple[Task, tuple]:
        t = Task(
            kind=kind,
            formation=fid,
            objective=obj,
            manner=manner,
            on_contact=on_contact,
            state=state,
            source_text=f"{fid}: {why}",
        )
        o = None
        if obj is not None:
            o = (obj.kind.value, obj.name)
        return t, (kind.value, o, manner.value, on_contact.value, state.value if state else None)

    def _point(self, p: geo.Point) -> Ref:
        return Ref(RefKind.POINT, point=(float(p[0]), float(p[1])))

    # ------------------------------------------------------------ the fight
    def _odds(self, live, near_enemy: list, now: int) -> tuple[float, float]:
        """(own allotted men near the objective and on the map, enemy men near it)."""
        en = float(sum(self._men_of(c) for c in near_enemy))
        near = float(
            sum(
                live[k].men
                for k in sorted(self.allotted)
                if k in live
                and geo.dist(live[k].at, self.place.point) <= OWN_NEAR_M
                and not (live[k].arrives_at is not None and live[k].arrives_at > now)
            )
        )
        return near, en

    def _plan_fight(self, now, live, contacts, formed, enemy_c, desired) -> None:
        d = self.doctrine
        p = self.place
        near_enemy = [c for c in formed if geo.dist((c.x, c.y), p.point) <= ENEMY_NEAR_M]
        if near_enemy and self.contested_since is None:
            self.contested_since = float(now)
        # every infantry element not in reserve goes to the objective
        inf = [
            e
            for e in self._of(live, "infantry")
            if e.id not in self.reserve and e.id not in desired
        ]
        self.allotted.update(e.id for e in inf)
        # commit the reserve (strong): at once when the objective is outnumbered or in
        # distress; when contested and it can tip the odds after COMMIT_AFTER_MIN; everything
        # late in the day
        if d.commit_reserve and self.reserve:
            self._commit_reserve(now, live, near_enemy)
        # infantry (strong: a brigade with a body broken and no enemy near halts to rally)
        for e in inf:
            r = self._rally(now, e, formed)
            if r is not None:
                desired[e.id] = r
                continue
            desired[e.id] = self._infantry_task(now, e, live, formed)
        if self.reserve_post is None:  # fixed once: the reserve does not drift
            back = (
                geo.bearing(enemy_c, p.point)
                if geo.dist(enemy_c, p.point) > 1
                else geo.bearing(p.point, self.start_centroid)
            )
            self.reserve_post = self._inset(geo.offset(p.point, back, RESERVE_BACK_M))
        for k in self.reserve:
            if k in live and k not in desired:
                desired[k] = self._task(
                    TaskKind.HOLD, k, self._point(self.reserve_post), "waits in reserve"
                )
        # guns
        for e in self._of(live, "artillery"):
            if e.id in desired:
                continue
            if e.id not in self.guns:
                self.guns[e.id] = self._commanding(p.point, enemy_c)
            desired[e.id] = self._task(
                TaskKind.HOLD,
                e.id,
                self._point(self.guns[e.id]),
                f"guns on the high ground covering {p.name}",
                state=UnitState.UNLIMBERED,
            )
        self._plan_cavalry(now, live, contacts, enemy_c, desired)

    def _commit_reserve(self, now, live, near_enemy: list) -> None:
        near, en = self._odds(live, near_enemy, now)
        hurt = any(now - self.distress.get(k, -1e9) <= DISTRESS_MIN for k in self.allotted)
        since = self.contested_since
        ripe = (
            since is not None
            and now - since >= COMMIT_AFTER_MIN
            and en > 0
            and (near < self.doctrine.concentration * en)
        )
        if (en > 0 and en > near) or hurt or ripe:
            r = min(
                (k for k in self.reserve if k in live),
                key=lambda k: (geo.dist(live[k].at, self.place.point), k),
                default=None,
            )
            if r is not None:
                self.reserve.remove(r)
                self.allotted.add(r)
            return
        if now >= self.limit - LATE_COMMIT_MIN:
            for k in list(self.reserve):
                if k in live:
                    self.reserve.remove(k)
                    self.allotted.add(k)

    def _plan_cavalry(self, now, live, contacts, enemy_c, desired) -> None:
        routed = [
            c
            for c in contacts
            if c.routed and now - c.seen_at <= ROUTED_FRESH_MIN and c.arm != "train"
        ]
        axis = geo.bearing(self._centroid(list(live.values())), enemy_c)
        p = self.place
        for e in self._of(live, "cavalry"):
            if e.id in desired:
                continue
            near_r = [c for c in routed if geo.dist((c.x, c.y), e.at) <= PURSUE_M]
            if near_r:
                c = min(near_r, key=lambda c: (geo.dist((c.x, c.y), e.at), c.key))
                desired[e.id] = self._task(
                    TaskKind.CHARGE,
                    e.id,
                    Ref(RefKind.ENEMY, c.name),
                    f"pursues {c.name}",
                    manner=Manner.BOLD,
                    on_contact=OnContact.PRESS,
                )
                continue
            side = self.flank.get(e.id, 1)
            if e.id not in self.flank_posts:  # fixed once: no drifting posts
                fp = geo.offset(p.point, axis + 90.0 * side, FLANK_M)
                fp = geo.offset(fp, axis + 180.0, 300.0)
                self.flank_posts[e.id] = self._inset(fp)
            fp = self.flank_posts[e.id]
            desired[e.id] = self._task(
                TaskKind.ADVANCE,
                e.id,
                self._point(fp),
                f"covers the {'left' if side < 0 else 'right'} flank",
                on_contact=OnContact.ENGAGE,
            )

    def _rally(self, now, e: Element, formed) -> tuple[Task, tuple] | None:
        if not self.doctrine.rally:
            return None
        until = self.rally_until.get(e.id)
        if until is None or now >= until:
            b = self.broken.get(e.id)
            if b is None or now - b > DISTRESS_MIN or (until is not None and b < until):
                return None
            if any(geo.dist((c.x, c.y), e.at) <= RALLY_CLEAR_M for c in formed):
                return None
            until = float(now + RALLY_MIN)
            self.rally_until[e.id] = until
        t, sig = self._task(TaskKind.RALLY, e.id, None, "halts and rallies its broken men")
        t.until = Condition(ConditionKind.TIME, at=until)
        return t, (*sig, until)

    def _infantry_task(self, now, e: Element, live, formed) -> tuple[Task, tuple]:
        d = self.doctrine
        p = self.place
        manner = Manner.BOLD if d.aggression >= 0.6 else Manner.MEASURED
        # counterattack a weakened, shaken or broken enemy within reach
        weak = [
            c
            for c in formed
            if geo.dist((c.x, c.y), e.at) <= COUNTER_M
            and self._weakened(c, now)
            and e.men >= (1.0 / max(0.1, d.aggression)) * 0.7 * self._men_of(c)
        ]
        if weak:
            c = min(weak, key=lambda c: (geo.dist((c.x, c.y), e.at), c.key))
            return self._task(
                TaskKind.ATTACK,
                e.id,
                Ref(RefKind.ENEMY, c.name),
                f"counterattacks {c.name}",
                manner=manner,
                on_contact=OnContact.PRESS,
            )
        en = [c for c in formed if geo.dist((c.x, c.y), p.point) <= ENEMY_NEAR_M]
        if not en:
            return self._task(
                TaskKind.HOLD,
                e.id,
                Ref(RefKind.FEATURE, p.name),
                f"occupies and holds {p.name}",
                state=UnitState.LINE,
            )
        en_men = sum(self._men_of(c) for c in en)
        own = sum(
            live[k].men
            for k in sorted(self.allotted)
            if k in live and geo.dist(live[k].at, p.point) <= OWN_NEAR_M
        )
        if own >= d.concentration * en_men:
            # the objective itself is the objective: the drill takes the nearest enemy on the
            # way, and the order stays the same while the contacts change
            return self._task(
                TaskKind.ATTACK,
                e.id,
                Ref(RefKind.FEATURE, p.name),
                f"attacks the enemy at {p.name}",
                manner=manner,
                on_contact=OnContact.PRESS,
            )
        if geo.dist(e.at, p.point) <= AT_PLACE_M:
            return self._task(
                TaskKind.HOLD,
                e.id,
                Ref(RefKind.FEATURE, p.name),
                f"holds {p.name}",
                state=UnitState.LINE,
            )
        stage = geo.toward(p.point, e.at, min(STAGE_M, geo.dist(e.at, p.point)))
        return self._task(
            TaskKind.HOLD,
            e.id,
            self._point(stage),
            f"waits short of {p.name} for support",
            state=UnitState.LINE,
        )

    def _commanding(self, p: geo.Point, enemy_c: geo.Point) -> geo.Point:
        """The highest passable point near p (ties: nearer the enemy side, then nearer the
        army's start). Distances are compared to the millimetre and the bearing's index comes
        last, so a tie the rotation keeps is never broken by enumeration order or float noise:
        on a field symmetric under the 180° rotation (Mirror, two equal ridges either side of
        the village, no enemy seen so enemy_c is the village) a key of (elevation, enemy
        distance, radius, index) would send both armies' guns to the same ridge."""
        best = None
        for r in GUN_RADII:
            for k in range(GUN_BEARINGS if r > 0 else 1):
                q = geo.offset(p, k * 360.0 / GUN_BEARINGS, r) if r > 0 else p
                if not self.world.in_bounds(q[0], q[1]) or not self.world.passable(
                    q[0], q[1], "art"
                ):
                    continue
                key = (
                    round(self.world.elev(q[0], q[1]), 1),
                    -round(geo.dist(q, enemy_c), 3),
                    -r,
                    -round(geo.dist(q, self.start_centroid), 3),
                    k,
                )
                if best is None or key > best[0]:
                    best = (key, (float(q[0]), float(q[1])))
        return best[1] if best else p

    def _inset(self, p: geo.Point) -> geo.Point:
        t = self.world.terrain
        x0, y0 = t.origin
        m = INSET_M
        return (
            min(max(p[0], x0 + m), x0 + t.width_m - m),
            min(max(p[1], y0 + m), y0 + t.height_m - m),
        )

    # ------------------------------------------------------------ withdrawal
    def _plan_withdrawal(self, now, live, formed, enemy_c, desired) -> None:
        d = self.doctrine
        fighting = [
            e
            for e in sorted(live.values(), key=lambda e: e.id)
            if e.arm != "train" and e.id not in desired
        ]
        guard: set[str] = set()
        if d.staged and formed and len(fighting) > 1:
            # stage one: the freshest elements nearest the enemy hold, up to a share of the men
            if not self.guard:

                def fresh(e: Element) -> float:
                    men, st = self.strength.get(e.id, (e.men, e.start_men))
                    return men / max(1, st)

                cand = sorted(
                    fighting,
                    key=lambda e: (
                        min(geo.dist(e.at, (c.x, c.y)) for c in formed) / 1000.0
                        - fresh(e)
                        - (0.5 if e.arm == "cavalry" else 0.0),
                        e.id,
                    ),
                )
                tot = sum(e.men for e in fighting) or 1
                got = 0
                for e in cand:
                    if got + e.men > REAR_GUARD_SHARE * tot and self.guard:
                        break
                    self.guard.append(e.id)
                    got += e.men
            if self.withdraw_at is not None and now < self.withdraw_at + REAR_GUARD_MIN:
                guard = set(self.guard)
        for e in fighting:
            if e.id in guard:
                desired[e.id] = self._task(
                    TaskKind.HOLD,
                    e.id,
                    None,
                    "holds as the rear guard",
                    state=UnitState.LINE if e.arm == "infantry" else None,
                )
                continue
            away = geo.bearing(enemy_c, e.at) if geo.dist(enemy_c, e.at) > 1 else 180.0
            q = self._inset(geo.offset(e.at, away, WITHDRAW_BACK_M))
            desired[e.id] = self._task(
                TaskKind.WITHDRAW, e.id, self._point(q), "withdraws out of reach"
            )

    # ------------------------------------------------------------ emitting
    def _emit(self, now: int, pic, desired: dict[str, tuple[Task, tuple]]) -> list[Task]:
        """Orders only where the wanted task differs from the last one sent. An order to an
        element with child elements re-tasks them too, so their next order is re-sent once
        the parent's aide should have arrived."""
        out: list[Task] = []
        for k in sorted(desired):
            task, sig = desired[k]
            old = self.sent.get(k)
            if old is not None and old[0] == sig:
                q0, q1 = old[1], task.objective.point if task.objective else None
                if q0 is None or q1 is None or geo.dist(q0, q1) <= REORDER_M:
                    continue
            par = self.elements[k].parent
            if par is not None and par in self.sent_at:
                eta = self.sent_at[par] + self._courier(pic.hq, self.elements[par].at) + 1.0
                if now < eta:
                    continue  # the parent's order would override this one on arrival
            self.sent[k] = (sig, task.objective.point if task.objective else None)
            self.sent_at[k] = float(now)
            self._note_goal(k, task, now, pic)
            for c in self.elements[k].children:
                self.sent.pop(c, None)
                if k in self.goal:
                    self.goal[c] = self.goal[k]
            out.append(task)
        return out

    def _note_goal(self, k: str, task: Task, now: int, pic) -> None:
        """Where the element's last order sends it, and when the aide should arrive: the
        bot's own knowledge of its orders, for the reckoning of its position."""
        if not self.doctrine.reckon:
            return
        e = self.elements[k]
        goal = None
        o = task.objective
        if task.kind != TaskKind.RALLY and o is not None:
            if o.kind == RefKind.POINT and o.point is not None:
                goal = (float(o.point[0]), float(o.point[1]))
            elif o.kind == RefKind.FEATURE and self.world.has_feature(o.name or ""):
                q = self.world.anchor(self.world.feature(o.name), e.at)
                goal = (float(q[0]), float(q[1]))
            elif o.kind == RefKind.ENEMY:
                c = next((c for c in pic.contacts if c.name == o.name), None)
                goal = (float(c.x), float(c.y)) if c is not None else None
            elif o.kind == RefKind.FRIENDLY and o.name in self.elements:
                goal = self.elements[o.name].at
        eta = float(now) + self._courier(pic.hq, e.at)
        self.goal[k] = (goal, eta)

    def _courier(self, hq: geo.Point, p: geo.Point) -> float:
        m = courier_minutes(self.world, hq, p)
        return m if math.isfinite(m) else 60.0


__all__ = ["PRESETS", "BotCommander", "Doctrine", "doctrine_for", "is_bot"]
