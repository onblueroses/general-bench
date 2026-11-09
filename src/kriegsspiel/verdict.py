"""The ordinal verdict of a battle (docs/battles/README.md; no weights).

A pack opts in with `data/<pack>/mission.json`:

    {"verdict": "ordinal", "objective": "<feature>", "break_share": 0.4,
     "break_persist_min": 30, "play_on_min": 120, "break_tie_margin": 0.1}

In game the Sim asks the judge at the end of every tick (`Sim._ask_battle_over`) in place of
the umpire's "is it over?"; the judge reads plain `Field`s, so a recorded game is judged by
the same code. The rule: (1) an army over the break share for `break_persist_min` without a
dip loses, to an army itself under the share at that minute; both over it, the less broken
army wins unless the shares are within `break_tie_margin` of each other (draw); (2) else
possession of the objective within musket range at the end hour (formed foot or guns, else
formed horse); (3) else quarter-hour readings up to `play_on_min`, the first clear one wins;
at the last reading an army over the share loses to one that is not; (4) else a draw
(docs/battles/README.md).

A pack without mission.json (the test packs) has no judge: the umpire is asked whether the
battle is over, and gives the verdict.
"""

from __future__ import annotations

import json
from pathlib import Path

from . import geometry as geo
from .account import Body, Field, field_of
from .clock import at_minute, clock
from .combat import MUSKET_RANGE_M
from .types import Feature

ORDINAL = "ordinal"
ORDINAL_DEFAULTS = {
    "break_share": 0.4,
    "break_persist_min": 30,
    "play_on_min": 120,
    "break_tie_margin": 0.10,
}  # about a brigade of foot (docs/battles/README.md)
PLAY_ON_STEP_MIN = 15  # the play-on is judged in quarter hours (docs/battles/README.md rule 3)
FOOT_OR_GUNS = ("infantry", "artillery")  # types.Arm values
HORSE = ("cavalry",)
DRAW = "draw"
CONTESTED, EMPTY = "contested", "empty"
POSSESSION_RADIUS_M = MUSKET_RANGE_M  # an objective is held within musket range of it


class MissionError(ValueError):
    pass


# ---------------------------------------------------------------------------
# Loading


def mission_path(scenario_dir: str | Path) -> Path:
    return Path(scenario_dir) / "mission.json"


def load(scenario_dir: str | Path) -> dict:
    p = mission_path(scenario_dir)
    if not p.exists():
        raise MissionError(f"no mission.json in {scenario_dir}")
    return json.loads(p.read_text())


# ---------------------------------------------------------------------------
# Reading a field


def _start(b: Body) -> int:
    return int(b.start_men)


def lost_men(b: Body) -> int:
    fate = (b.fate or {}).get("fate")
    if fate == "awaiting":
        return 0
    if fate in ("captured", "fled"):
        return _start(b)
    return max(0, _start(b) - int(b.men))


def _formed_near(bodies: list[Body], f: Feature, r: float) -> list[Body]:
    return [b for b in bodies if b.fate is None and b.formed and geo.feature_dist(b.p, f) <= r]


def loss_fraction(bodies: list[Body]) -> float:
    start = sum(_start(b) for b in bodies)
    return sum(lost_men(b) for b in bodies) / start if start else 0.0


def is_broken_body(b: Body) -> bool:
    """A body that counts toward its army's break: routed or destroyed on the field, fled
    off the map, or captured. A body marched off by an exit, or not yet arrived, does not."""
    fate = (b.fate or {}).get("fate")
    if fate is not None:
        return fate in ("fled", "captured")
    return b.state in ("routed", "destroyed")


def broken_share(bodies: list[Body]) -> float:
    """Starting men of the side's broken bodies over all its starting men."""
    start = sum(_start(b) for b in bodies)
    return sum(_start(b) for b in bodies if is_broken_body(b)) / start if start else 0.0


def formed_share(bodies: list[Body]) -> float:
    """Men in formed bodies on the field over the side's starting men."""
    start = sum(_start(b) for b in bodies)
    formed = sum(int(b.men) for b in bodies if b.fate is None and b.formed)
    return formed / start if start else 0.0


def _formed_near_by_side(
    fld: Field, objective: Feature, sides: list[str], radius_m: float | None
) -> dict[str, list[Body]]:
    r = POSSESSION_RADIUS_M if radius_m is None else radius_m
    return {s: _formed_near([b for b in fld.bodies if b.side == s], objective, r) for s in sides}


def possession(
    fld: Field, objective: Feature, sides: list[str], radius_m: float | None = None
) -> str:
    """Who holds `objective`: a side name, "contested" or "empty" (docs/battles/README.md rule
    2). Formed foot or guns within musket range hold against everything; formed cavalry holds
    only where neither side has formed foot or guns."""
    near = _formed_near_by_side(fld, objective, sides, radius_m)
    for arms in (FOOT_OR_GUNS, HORSE):
        there = [s for s in sides if any(b.arm in arms for b in near[s])]
        if len(there) == 1:
            return there[0]
        if len(there) > 1:
            return CONTESTED
    return EMPTY


def near_strength(
    fld: Field, objective: Feature, sides: list[str], radius_m: float | None = None
) -> dict[str, dict[str, int]]:
    """Formed men within the possession radius per side, foot and guns apart from horse:
    recorded with each reading for the margin, never for the verdict."""
    near = _formed_near_by_side(fld, objective, sides, radius_m)
    return {
        s: {
            "foot_guns": int(sum(b.men for b in near[s] if b.arm in FOOT_OR_GUNS)),
            "horse": int(sum(b.men for b in near[s] if b.arm in HORSE)),
        }
        for s in sides
    }


def ordinal_margin(fld: Field, sides: list[str]) -> dict[str, dict[str, float]]:
    """For reading, never for the verdict: per side the casualty share, the formed share and
    the broken share of its starting men."""
    out = {}
    for s in sides:
        bodies = [b for b in fld.bodies if b.side == s]
        out[s] = {
            "casualty_share": round(loss_fraction(bodies), 4),
            "formed_share": round(formed_share(bodies), 4),
            "broken_share": round(broken_share(bodies), 4),
        }
    return out


# ---------------------------------------------------------------------------
# The judge


def is_ordinal(mission: dict | None) -> bool:
    return bool(mission) and mission.get("verdict") == ORDINAL


def ordinal_params(mission: dict) -> dict:
    out = {**ORDINAL_DEFAULTS, **{k: mission[k] for k in ORDINAL_DEFAULTS if k in mission}}
    out["objective"] = mission["objective"]
    return out


def validate(mission: dict, features: list[Feature]) -> list[str]:
    """Problems with an ordinal mission (empty when it is sound): an objective that is not
    a feature (exact names, as in features.json), parameters out of range."""
    if not is_ordinal(mission):
        return [f"verdict {mission.get('verdict')!r}, not {ORDINAL!r}"]
    errs: list[str] = []
    if mission.get("objective") not in {f.name for f in features}:
        errs.append(f"objective {mission.get('objective')!r}, not a feature")
    p = {**ORDINAL_DEFAULTS, **mission}
    if not 0.0 < float(p["break_share"]) < 1.0:
        errs.append("break_share outside (0, 1)")
    if not 0.0 <= float(p["break_tie_margin"]) < 1.0:
        errs.append("break_tie_margin outside [0, 1)")
    if float(p["break_persist_min"]) < 0 or float(p["play_on_min"]) < 0:
        errs.append("negative minutes")
    if float(p["play_on_min"]) % PLAY_ON_STEP_MIN:
        errs.append(f"play_on_min not a multiple of {PLAY_ON_STEP_MIN}")
    return errs


class OrdinalJudge:
    """The ordinal verdict, read one field at a time: `observe(field, minute)` after every
    tick (minute = minutes elapsed at the end of it) returns True once the battle is ruled
    over, and `result` holds the verdict. A break is ruled at the first reading at least
    `break_persist_min` after the share crossed with every reading since above it, so the
    judge works at any reading cadence."""

    def __init__(
        self,
        mission: dict,
        features: list[Feature],
        sides: list[str],
        clock_start: str,
        end_clock: str,
    ):
        self.params = ordinal_params(mission)
        self.objective = next(f for f in features if f.name == self.params["objective"])
        self.sides = list(sides)
        self.clock_start = clock_start
        self.end_minute = int(at_minute(clock_start, end_clock))
        self.last_minute = self.end_minute + int(self.params["play_on_min"])
        self.crossed: dict[str, int | None] = dict.fromkeys(self.sides)
        self.first_crossed: dict[str, int | None] = dict.fromkeys(self.sides)
        self.readings: list[dict] = []  # possession at each quarter hour from the end hour
        self.result: dict | None = None

    def clock_of(self, minute: int) -> str:
        return clock(self.clock_start, minute)

    def record(self, fld: Field, minute: int, winner: str, how: str) -> dict:
        return {
            "winner": winner,
            "how": how,
            "minute": int(minute),
            "clock": self.clock_of(minute),
            "objective": self.objective.name,
            "break": {
                s: {"first_crossed": self.first_crossed[s], "crossed": self.crossed[s]}
                for s in self.sides
            },
            "possession": list(self.readings),
            "margin": ordinal_margin(fld, self.sides),
            "params": {k: self.params[k] for k in ORDINAL_DEFAULTS},
        }

    def _rule(self, fld: Field, minute: int, winner: str, how: str) -> bool:
        self.result = self.record(fld, minute, winner, how)
        return True

    def observe(self, fld: Field, minute: int) -> bool:
        if self.result is not None:
            return True
        share = float(self.params["break_share"])
        persist = int(self.params["break_persist_min"])
        broken = []
        for s in self.sides:
            if broken_share([b for b in fld.bodies if b.side == s]) <= share:
                self.crossed[s] = None  # rallied (or never broke): the clock starts again
                continue
            if self.crossed[s] is None:
                self.crossed[s] = minute
                if self.first_crossed[s] is None:
                    self.first_crossed[s] = minute
            if minute - self.crossed[s] >= persist:
                broken.append(s)
        if broken:
            # The army that wins by a break must itself be under the share at that minute,
            # whichever crossed first. Both over it at the ruling minute, the less broken army
            # wins unless the shares are within the tie margin, when it is a draw: an army
            # barely over the line is not beaten by one three quarters broken.
            standing = [s for s in self.sides if self.crossed[s] is None]
            if len(standing) == 1:
                return self._rule(fld, minute, standing[0], "break")
            shares = {s: broken_share([b for b in fld.bodies if b.side == s]) for s in self.sides}
            least = min(self.sides, key=shares.get)
            spread = max(shares.values()) - shares[least]
            if len(self.sides) == 2 and spread > float(self.params["break_tie_margin"]) + 1e-9:
                return self._rule(fld, minute, least, "break")
            return self._rule(fld, minute, DRAW, "break")
        if minute < self.end_minute or (minute - self.end_minute) % PLAY_ON_STEP_MIN:
            return False
        held = possession(fld, self.objective, self.sides)
        self.readings.append(
            {
                "minute": int(minute),
                "clock": self.clock_of(minute),
                "state": held,
                "near": near_strength(fld, self.objective, self.sides),
            }
        )
        if held in self.sides:
            return self._rule(
                fld, minute, held, "possession" if minute == self.end_minute else "play-on"
            )
        if minute >= self.last_minute:
            # at the last reading an army over the share loses to one that is not,
            # persisted or not
            over = [s for s in self.sides if self.crossed[s] is not None]
            if len(over) == 1:
                return self._rule(
                    fld, minute, next(s for s in self.sides if s not in over), "last-reading"
                )
            return self._rule(fld, minute, DRAW, "draw")
        return False

    def verdict(self, fld: Field, minute: int) -> dict:
        """The ruled verdict, or for a game that stopped before a ruling, winner undecided
        with how "unfinished" and the margin as it stands."""
        return self.result or self.record(fld, minute, "undecided", "unfinished")


def play_on_notice(judge: OrdinalJudge) -> str:
    """What the staff tell the general once the end hour has passed without a verdict: the
    last reading of the objective and that play goes on (the brief's "umpire's reading")."""
    if not judge.readings or judge.result is not None:
        return ""
    last = judge.readings[-1]
    state = last["state"]
    name = judge.objective.name
    what = (
        f"both armies had formed troops within musket range of {name}: contested"
        if state == CONTESTED
        else f"neither army had formed troops within musket range of {name}: empty"
    )
    return (
        f"The umpire's reading at {last['clock']}: {what}. Play goes on; the next reading "
        f"is a quarter of an hour later, the last at {judge.clock_of(judge.last_minute)}, "
        f"after which an undecided field is a draw."
    )


def ordinal_judge_for(
    scenario_dir: Path, features: list[Feature], sides: list[str], clock_start: str, end_clock: str
) -> OrdinalJudge | None:
    """The judge for a pack, None for a pack without an ordinal mission.json."""
    if not mission_path(scenario_dir).exists():
        return None
    m = load(scenario_dir)
    if not is_ordinal(m):
        return None
    return OrdinalJudge(m, features, sides, clock_start, end_clock)


def field_at(sim, minute: int) -> Field:
    """The field as it stands, labelled with `minute` (the judge reads at the end of a tick,
    before the sim's clock advances)."""
    fld = field_of(sim, with_hash=False)
    fld.minutes, fld.clock = int(minute), clock(sim.clock_start, minute)
    return fld
