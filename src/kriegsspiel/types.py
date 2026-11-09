"""Shared types of the Kriegsspiel engine.

Additions stay backwards compatible: a recorded game must load and replay.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import IntEnum, StrEnum
from typing import Any, Protocol, runtime_checkable

import numpy as np

# ---------------------------------------------------------------------------
# Enums (string enums serialise as their value)


class Cover(IntEnum):
    """Raster cover classes; values are the uint8 codes stored in terrain.npz."""

    OPEN = 0
    ROUGH = 1
    WOOD = 2
    VILLAGE = 3
    ORCHARD = 4
    MARSH = 5
    WATER = 6
    ROAD = 7


class FeatureKind(StrEnum):
    VILLAGE = "village"
    WOOD = "wood"
    HEIGHT = "height"
    RIDGE = "ridge"
    STREAM = "stream"
    POND = "pond"
    ROAD = "road"
    BRIDGE = "bridge"
    FARM = "farm"
    MILL = "mill"
    CHURCH = "church"
    # where arriving bodies appear and where bodies leave (docs/pack-format.md)
    ENTRY = "entry"
    EXIT = "exit"
    FORD = "ford"  # water passable for the arms in props["passable"] at props["speed"]


class GeometryKind(StrEnum):
    POINT = "point"
    POLYLINE = "polyline"
    POLYGON = "polygon"


class Arm(StrEnum):
    INFANTRY = "infantry"
    CAVALRY = "cavalry"
    ARTILLERY = "artillery"
    TRAIN = "train"  # wagons, a baggage or artillery park: never fights


class UnitKind(StrEnum):
    LINE = "line"
    GRENADIER = "grenadier"
    FUSILIER = "fusilier"
    GRENZER = "grenzer"
    CUIRASSIER = "cuirassier"
    DRAGOON = "dragoon"
    HUSSAR = "hussar"
    FOOT_BATTERY = "foot_battery"
    HORSE_BATTERY = "horse_battery"
    TRAIN = "train"


class UnitState(StrEnum):
    COLUMN = "column"
    LINE = "line"
    SQUARE = "square"
    SKIRMISH = "skirmish"
    LIMBERED = "limbered"
    UNLIMBERED = "unlimbered"
    ROUTED = "routed"
    DESTROYED = "destroyed"


class TaskKind(StrEnum):
    HOLD = "hold"
    ADVANCE = "advance"
    ATTACK = "attack"
    CHARGE = "charge"
    WITHDRAW = "withdraw"
    SCREEN = "screen"
    BOMBARD = "bombard"
    SUPPORT = "support"
    RALLY = "rally"
    MOVE_HQ = "move_hq"


class OnContact(StrEnum):
    HALT = "halt"
    ENGAGE = "engage"
    PRESS = "press"
    FALL_BACK = "fall_back"


class Manner(StrEnum):
    CAUTIOUS = "cautious"
    MEASURED = "measured"
    BOLD = "bold"
    RECKLESS = "reckless"


class ConditionKind(StrEnum):
    TIME = "time"
    WHEN_ENGAGED = "when_engaged"
    WHEN_REACHED = "when_reached"
    WHEN_ENEMY_SEEN = "when_enemy_seen"
    WHEN_ROUTS = "when_routs"


class RefKind(StrEnum):
    FEATURE = "feature"  # name = feature name (or alias)
    ENEMY = "enemy"  # name = enemy body as known to the side (SideView.enemies[].name)
    FRIENDLY = "friendly"  # name = friendly formation or unit id
    POINT = "point"  # point = (x, y) in metres


class MessageKind(StrEnum):
    ORDER = "order"
    REPORT = "report"
    CLARIFICATION = "clarification"


# ---------------------------------------------------------------------------
# World


@dataclass
class Terrain:
    """Raster terrain. Row i is y = origin_y + (i + 0.5) * cell_m (row 0 is the south edge);
    column j is x = origin_x + (j + 0.5) * cell_m."""

    cell_m: float
    elev_m: np.ndarray  # float32, shape (ny, nx)
    cover: np.ndarray  # uint8 Cover codes, shape (ny, nx)
    origin: tuple[float, float] = (0.0, 0.0)

    @property
    def shape(self) -> tuple[int, int]:
        return self.elev_m.shape  # type: ignore[return-value]

    @property
    def width_m(self) -> float:
        return self.elev_m.shape[1] * self.cell_m

    @property
    def height_m(self) -> float:
        return self.elev_m.shape[0] * self.cell_m

    @property
    def slope(self) -> np.ndarray:
        """Grade magnitude (rise over run, dimensionless), derived from elev_m."""
        gy, gx = np.gradient(self.elev_m.astype(np.float64), self.cell_m)
        return np.hypot(gx, gy).astype(np.float32)


@dataclass
class Feature:
    name: str
    kind: FeatureKind
    geometry_kind: GeometryKind
    coords: list[tuple[float, float]]  # one point, a polyline, or a closed polygon ring
    aliases: list[str] = field(default_factory=list)
    # any further keys of the feature's JSON (exit `radius_m`, ford `passable`, ...)
    props: dict[str, Any] = field(default_factory=dict)

    @property
    def names(self) -> list[str]:
        return [self.name, *self.aliases]


@runtime_checkable
class WorldLike(Protocol):
    """The World interface of the spec (implemented by world.World)."""

    terrain: Terrain
    features: list[Feature]

    def elev(self, x: float, y: float) -> float: ...
    def cover(self, x: float, y: float) -> Cover: ...
    def slope(self, x: float, y: float) -> float: ...
    def nearest_feature(self, x: float, y: float, kind: FeatureKind | None = None) -> Feature: ...
    def inside(self, x: float, y: float, feature: Feature | str) -> bool: ...
    def path_cost(
        self, a: tuple[float, float], b: tuple[float, float], formation_state: Any
    ) -> tuple[float, list[tuple[float, float]]]: ...
    def line_of_sight(
        self, a: tuple[float, float], b: tuple[float, float], eye_m: float = 2.0
    ) -> bool: ...


# ---------------------------------------------------------------------------
# Orders


@dataclass
class Ref:
    kind: RefKind
    name: str | None = None
    point: tuple[float, float] | None = None


@dataclass
class Condition:
    kind: ConditionKind
    subject: Ref | None = None
    at: float | None = None  # sim minute for TIME
    # WHEN_REACHED with a FRIENDLY subject: the place that formation must reach or hold
    # ("as soon as the second brigade holds the village"); None: its task's arrival
    place: Ref | None = None


class Forbid(StrEnum):
    """Constraints a prohibition clause puts on a task. The drill honours
    CHARGE_FORMED_INFANTRY and ATTACK; ADVANCE_BEYOND is a movement boundary, PURSUE and
    ENGAGE are honoured where the drill and combat decide contact."""

    CHARGE_FORMED_INFANTRY = "CHARGE_FORMED_INFANTRY"
    ATTACK = "ATTACK"
    PURSUE = "PURSUE"
    ADVANCE_BEYOND = "ADVANCE_BEYOND"  # written "ADVANCE_BEYOND:<feature>" in Task.forbid
    ENGAGE = "ENGAGE"


@dataclass
class Task:
    kind: TaskKind
    formation: str  # id of the addressed formation or unit
    objective: Ref | None = None
    route: list[Ref] = field(default_factory=list)
    state: UnitState | None = None
    start: float | Condition | None = None  # None = on receipt
    on_contact: OnContact = OnContact.ENGAGE
    until: Condition | None = None
    manner: Manner = Manner.MEASURED
    source_text: str = ""
    issued_at: float | None = None
    received_at: float | None = None
    then: Task | None = None  # sequel: started when this task ends (Sim.end_task)
    # A stand-in from an order the staff could not read (it asked back): it holds a formation
    # that has no task and never replaces one it has.
    tentative: bool = False
    # Prohibitions ("do not charge the line without my order"): Forbid values, and
    # "ADVANCE_BEYOND:<feature name>"; empty for an order that forbids nothing.
    forbid: list[str] = field(default_factory=list)

    def forbids(self, what: Forbid | str) -> bool:
        w = str(what)
        return any(f == w or f.startswith(w + ":") for f in self.forbid)


# ---------------------------------------------------------------------------
# Forces


@dataclass
class Unit:
    id: str
    name: str
    side: str
    parent: str  # brigade (formation) id
    arm: Arm
    kind: UnitKind
    men: int  # infantry and cavalry: men; artillery: equals crew
    quality: int  # 1..5
    x: float
    y: float
    facing_deg: float = 0.0  # compass bearing: 0 north, 90 east
    state: UnitState = UnitState.COLUMN
    guns: int = 0
    crew: int = 0
    calibre_lb: int = 0
    morale: float | None = None  # None -> 60 + 8 * quality at construction
    fatigue: float = 0.0
    ammo: float = 100.0
    disorder: float = 0.0
    casualties: float = 0.0
    engaged: set[str] = field(default_factory=set)
    task: Task | None = None
    order_log: list[dict] = field(default_factory=list)
    # Weapons (the defaults keep older callers and recorded games unchanged):
    # infantry: light battalion (regimental) guns attached to the body, fired with it;
    # artillery: how many of `guns` are howitzers and mortars (the rest are cannon).
    bn_guns: int = 0
    howitzers: int = 0
    mortars: int = 0
    # Arrival (docs/pack-format.md): off the map until sim minute `arrives_at`,
    # then it appears at the `entry` feature and marches to `assemble` (a feature name or a
    # point) unless an order has reached it. None: on the map from the start.
    arrives_at: float | None = None
    entry: str | None = None
    assemble: str | tuple[float, float] | None = None

    def __post_init__(self) -> None:
        if self.morale is None:
            self.morale = 60.0 + 8.0 * self.quality
        if self.arm == Arm.ARTILLERY and self.crew and not self.men:
            self.men = self.crew

    @property
    def alive(self) -> bool:
        return self.state != UnitState.DESTROYED


@dataclass
class Formation:
    id: str
    name: str
    side: str
    commander: str
    parent: str | None = None
    units: list[str] = field(default_factory=list)  # unit ids (bodies) directly under it
    children: list[str] = field(default_factory=list)  # sub-formation ids
    hq: tuple[float, float] | None = None  # None -> rides with the centroid
    aliases: list[str] = field(default_factory=list)
    level: str = "brigade"  # brigade, column, wing, army


# ---------------------------------------------------------------------------
# Command, events, judgments


@dataclass
class Message:
    id: str
    side: str
    kind: MessageKind
    sender: str  # formation id (or "army")
    recipient: str  # formation id
    text: str
    sent_at: float
    received_at: float | None = None  # None while in transit
    tasks: list[Task] = field(default_factory=list)  # ORDER payload
    origin: tuple[float, float] | None = None
    destination: tuple[float, float] | None = None
    data: dict[str, Any] = field(default_factory=dict)  # REPORT payload (sightings, losses)


@dataclass
class Event:
    tick: int
    kind: str  # move, fire, melee, rout, rally, sighting, order, report, ...
    data: dict[str, Any] = field(default_factory=dict)


@dataclass
class Verdict:
    winner: str  # side name or "undecided"
    attacker_achieved: bool | None = None  # the attacker's level is "wholly" or "in the main"
    decisiveness: float | None = None  # 0..1
    rationale: str = ""
    raw: dict[str, Any] = field(default_factory=dict)
    # per side, how much of its own objective it achieved: "wholly", "in the
    # main", "in part" or "not at all" (empty from an umpire that does not ask)
    achieved: dict[str, str] = field(default_factory=dict)
    # "levels" when the winner was set from the per-side levels against a
    # low-confidence Jev winner (umpire.WINNER_TRUST_P), with Jev's own pick in jev_winner
    winner_source: str = "jev"
    jev_winner: str | None = None
    # an ordinal pack's mechanical verdict (verdict.OrdinalJudge): how, minute, clock, break,
    # possession readings, margin, and the umpire's own verdict; winner_source "ordinal"
    ordinal: dict[str, Any] | None = None

    def to_json(self) -> dict[str, Any]:
        d: dict[str, Any] = {
            "winner": self.winner,
            "attacker_achieved": self.attacker_achieved,
            "decisiveness": self.decisiveness,
            "rationale": self.rationale,
        }
        if self.achieved:
            d["achieved"] = dict(self.achieved)
        if self.winner_source != "jev":
            d["winner_source"] = self.winner_source
            d["jev_winner"] = self.jev_winner
        if self.ordinal is not None:
            d.update({k: v for k, v in self.ordinal.items() if k != "winner"})
        return d


# ---------------------------------------------------------------------------
# Views given to the staff


@dataclass
class FormationView:
    id: str
    name: str
    commander: str
    aliases: list[str] = field(default_factory=list)
    level: str = "brigade"
    parent: str | None = None
    arm: Arm | None = None  # set when every body under the formation has the same arm


@dataclass
class EnemyView:
    name: str  # staff-given name, e.g. "the enemy cavalry near the mill"
    arm: Arm | None
    est_men: int | None
    x: float
    y: float
    last_seen: float
    key: str = ""  # stable internal handle (contact id), not shown to commanders


@dataclass
class SideView:
    side: str
    formations: list[FormationView]
    feature_names: list[str]
    enemies: list[EnemyView] = field(default_factory=list)
    now: float = 0.0
    feature_aliases: dict[str, list[str]] = field(default_factory=dict)  # name -> aliases
    # Pseudo-features for relative places ("our left flank"), computed when the view is built
    # from the side's own bodies; their names are also in feature_names. A Ref to one carries
    # the point as of the order (RefKind.POINT with the name).
    places: dict[str, tuple[float, float]] = field(default_factory=dict)
    # The point a body heads for when told to go to each named feature (world anchor), so
    # the staff can place an offset from it. Empty in frozen views that predate it.
    feature_points: dict[str, tuple[float, float]] = field(default_factory=dict)
    # Offset places read from the order's own words ("600 m east of Medlar Village"), added
    # by the staff per order; their names are also in feature_names. A Ref to one is a
    # RefKind.POINT with the name.
    offsets: dict[str, tuple[float, float]] = field(default_factory=dict)
    # The side's brigades, head of the line of march first (projection of each brigade's
    # centroid on the side's mean facing); the staff's default for "follow the brigades ahead".
    march_order: list[str] = field(default_factory=list)
    clock_start: str = ""  # "13:00": what sim minute 0 is on the clock (clock phrases)
