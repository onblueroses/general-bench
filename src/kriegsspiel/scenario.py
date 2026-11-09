"""Scenario loader: a battle directory -> world, forces, objectives, meta.

    world, formations, units, objectives, meta = load("data/plain-crossroads")

The directory holds terrain.npz, features.json, oob.json and deployment.json in the format of
docs/pack-format.md (read through world.World.load and units.load_forces), plus objectives.md
and meta.json. The last two are optional so the synthetic test field loads too.

`players.md` (optional, docs/player-prompt.md) is the battle layer of each side's
persona: one `## <side>` section per side, written for the player. It lands in
`Objectives.players`; the narrator gives it to that side's general, the umpire never sees it
(the umpire reads `objectives.md`: its side sections, Outcome and Umpire).
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .clock import at_minute
from .jev import REPO_ROOT
from .movement import arm_class
from .types import Cover, Formation, Unit
from .units import load_forces
from .world import World

DEFAULT_SCENARIO = "data/plain-crossroads"  # the pack a game or a grid plays when none is named
DEFAULT_END = "19:30"  # the clock a pack whose meta.json names no `end` is played to
# Deployment keys beyond the engine's (x, y, facing_deg, state) that the loader applies.
_EXTRA_STATE = ("fatigue", "morale", "ammo", "disorder")


def resolve(scenario: str | Path | None = None) -> Path:
    """A pack's directory: the path as given when it is absolute or exists, else under the
    repository root (so `data/<slug>` works from any directory); None is DEFAULT_SCENARIO."""
    d = Path(scenario or DEFAULT_SCENARIO)
    if not d.is_absolute() and not d.exists():
        d = REPO_ROOT / d
    return d


def relpath(d: Path) -> str:
    """A pack as a run log's header names it: relative to the repository root when inside."""
    try:
        return str(d.resolve().relative_to(REPO_ROOT))
    except ValueError:
        return str(d.resolve())


def load_sides(path: str | Path) -> list[str]:
    """The pack's sides in oob.json order (sorted from its formations when it names none)."""
    oob = json.loads((Path(path) / "oob.json").read_text())
    return list(oob.get("sides") or sorted({f["side"] for f in oob["formations"]}))


@dataclass
class Objectives:
    """Historical objectives in the commanders' own terms, free text per side."""

    sides: dict[str, str] = field(default_factory=dict)  # side -> objective text
    outcome: str = ""  # the historical outcome, for the record (not shown to commanders)
    umpire: str = ""  # `## Umpire` section: what the umpire weighs (not shown to commanders)
    text: str = ""  # the whole objectives.md
    # players.md: side -> the player's situation (the persona's battle layer); never given to
    # the umpire
    players: dict[str, str] = field(default_factory=dict)

    def for_side(self, side: str) -> str:
        return self.sides.get(side, "")

    def for_player(self, side: str) -> str:
        return self.players.get(side, "")


@dataclass
class Meta:
    battle: str = ""
    date: str = ""
    start: str = "13:00"  # local apparent solar time
    sunset: str | None = None
    weather: str = ""
    sides: dict[str, dict[str, Any]] = field(default_factory=dict)
    strength_documented: dict[str, int] = field(default_factory=dict)
    par: dict[str, Any] = field(default_factory=dict)
    sources: list[str] = field(default_factory=list)
    end: str | None = None  # clock at which play stops (docs/pack-format.md); None: run default
    deadline: str | None = None  # the mission's deadline, stated in the umpire's account
    battle_over_after: int = 120  # minutes before the umpire is first asked "is it over?"
    battle_over_every: int = 30
    raw: dict[str, Any] = field(default_factory=dict)

    @property
    def end_clock(self) -> str:
        """The clock play stops at: the pack's `end`, else DEFAULT_END."""
        return self.end or DEFAULT_END

    def attacker(self, sides: list[str] | tuple[str, ...]) -> str:
        """The side whose role is "attacker", else the first side (a meeting engagement
        names both or neither)."""
        return next((s for s in sides if self.role(s) == "attacker"), sides[0])

    def names_attacker(self, sides: list[str] | tuple[str, ...]) -> bool:
        """Whether a side's role is "attacker"; a designed battle names none, and its
        "attacker" is only its first side."""
        return any(self.role(s) == "attacker" for s in sides)

    def role(self, side: str) -> str | None:
        return (self.sides.get(side) or {}).get("role")

    def commander(self, side: str) -> str:
        return (self.sides.get(side) or {}).get("commander", side)

    @property
    def start_minute(self) -> int:
        """Start as minutes after midnight."""
        h, m = self.start.split(":")
        return int(h) * 60 + int(m)

    def minute(self, at: str | float) -> float:
        """Sim minute of a clock string ("14:30") or of a number (minutes after the start)."""
        return float(at_minute(self.start, at))

    @property
    def sunset_minute(self) -> int | None:
        if not self.sunset:
            return None
        h, m = self.sunset.split(":")
        return int(h) * 60 + int(m)


def parse_objectives(text: str, sides: list[str]) -> Objectives:
    """Split objectives.md on `## ` headings. A heading whose first word names a side
    (case-insensitive) is that side's objective; a heading starting with 'Outcome' is the
    historical outcome; one starting with 'Umpire' is for the umpire only."""
    obj = Objectives(text=text)
    parts = re.split(r"^## +", text, flags=re.MULTILINE)
    for part in parts[1:]:
        head, _, body = part.partition("\n")
        first = head.strip().split()[0].casefold().strip(":,.") if head.strip() else ""
        body = body.strip()
        if first == "outcome":
            obj.outcome = body
        elif first == "umpire":
            obj.umpire = body
        elif first in {s.casefold() for s in sides}:
            side = next(s for s in sides if s.casefold() == first)
            obj.sides[side] = body
    return obj


def unwrap(text: str) -> str:
    """Source-wrapped prose -> one line per paragraph, one per "- " item, so that a name
    wrapped over two lines in the file is one string to every reader (the staff's matching,
    the player)."""
    paras = []
    for para in re.split(r"\n\s*\n", text.strip()):
        items: list[str] = []
        for line in para.split("\n"):
            if line.startswith(("- ", "#")) or not items:
                items.append(line.strip())
            else:
                items[-1] += " " + line.strip()
        paras.append("\n".join(items))
    return "\n\n".join(paras)


def parse_players(text: str, sides: list[str]) -> dict[str, str]:
    """players.md: one `## <side> ...` section per side (the heading's first word names the
    side, case-insensitive), body unwrapped (`unwrap`); any other `## ` section is an error,
    so umpire text can never reach a general through this file."""
    out: dict[str, str] = {}
    folded = {s.casefold(): s for s in sides}
    for part in re.split(r"^## +", text, flags=re.MULTILINE)[1:]:
        head, _, body = part.partition("\n")
        first = head.strip().split()[0].casefold().strip(":,.") if head.strip() else ""
        if first not in folded:
            raise ValueError(f"players.md: section {head.strip()!r} names no side of {sides}")
        out[folded[first]] = unwrap(body)
    return out


def check_positions(world: World, units: list[Unit]) -> None:
    """Every body starts on the map, on ground its arm may stand on (a body still to arrive:
    at its entry). A body off the map would never take part, one on water could not move; the
    loader refuses both and names the bodies (spec: every start position is passable)."""
    bad = []
    for u in units:
        at = f"at ({u.x:.0f}, {u.y:.0f})" + (
            f", its entry {u.entry!r}" if u.arrives_at is not None else ""
        )
        if not world.in_bounds(u.x, u.y):
            bad.append(f"{u.id} ({u.name}) is off the map {at}")
        elif not world.passable(u.x, u.y, arm_class(u)):
            bad.append(
                f"{u.id} ({u.name}) stands on impassable ground "
                f"({Cover(world.cover(u.x, u.y)).name.lower()}) {at}"
            )
    if bad:
        raise ValueError(f"start positions refused ({len(bad)}): " + "; ".join(bad))


def load_meta(path: str | Path) -> Meta:
    """meta.json as a `Meta`; a pack without one gets the defaults (its start from
    deployment.json, else 13:00)."""
    d = Path(path)
    raw: dict[str, Any] = {}
    if (d / "meta.json").exists():
        raw = json.loads((d / "meta.json").read_text())
    if "start" in raw:
        start = raw["start"]
    elif (d / "deployment.json").exists():
        start = json.loads((d / "deployment.json").read_text()).get("start", "13:00")
    else:
        start = "13:00"
    return Meta(
        battle=raw.get("battle", d.name),
        date=raw.get("date", ""),
        start=start,
        sunset=raw.get("sunset"),
        weather=raw.get("weather", ""),
        sides=raw.get("sides", {}),
        strength_documented={k: int(v) for k, v in raw.get("strength_documented", {}).items()},
        par=raw.get("par", {}),
        sources=list(raw.get("sources", [])),
        end=raw.get("end"),
        deadline=raw.get("deadline"),
        battle_over_after=int(raw.get("battle_over_after", 120)),
        battle_over_every=int(raw.get("battle_over_every", 30)),
        raw=raw,
    )


def load(path: str | Path) -> tuple[World, list[Formation], list[Unit], Objectives, Meta]:
    d = Path(path)
    world = World.load(d)
    formations, units = load_forces(d)
    meta = load_meta(d)

    dep = json.loads((d / "deployment.json").read_text())
    for u in units:
        extra = dep["units"].get(u.id, {})
        for k in _EXTRA_STATE:
            if k in extra:
                setattr(u, k, float(extra[k]))
        if u.arrives_at is not None:  # an arriving body (docs/pack-format.md): at its entry
            u.arrives_at = float(at_minute(meta.start, u.arrives_at))
            if not u.entry or not world.has_feature(u.entry):
                raise ValueError(f"{u.id} arrives at an unknown entry {u.entry!r}")
            u.x, u.y = world.anchor(world.feature(u.entry))
    check_positions(world, units)
    by_id = {f.id: f for f in formations}
    for f in formations:
        f.children = sorted(c.id for c in formations if c.parent == f.id)
        f.units = sorted(u.id for u in units if u.parent == f.id)
    missing = [u.id for u in units if u.parent not in by_id]
    if missing:
        raise ValueError(f"units with unknown parent formation: {missing[:5]}")

    sides = load_sides(d)
    objectives = Objectives()
    if (d / "objectives.md").exists():
        objectives = parse_objectives((d / "objectives.md").read_text(), sides)
    if (d / "players.md").exists():
        objectives.players = parse_players((d / "players.md").read_text(), sides)
    return world, formations, units, objectives, meta


def load_script(path: str | Path, start: str | None = None) -> list[tuple[float, str, str]] | None:
    """The scenario's scripted orders (`script.json`, docs/pack-format.md) as (minute, side,
    text) in file order; None when the pack has no script. `start` is the clock of minute 0
    (default: meta.json's, else the deployment's, else 13:00)."""
    d = Path(path)
    f = d / "script.json"
    if not f.exists():
        return None
    data = json.loads(f.read_text())
    orders = data["orders"] if isinstance(data, dict) else data
    if start is None:
        start = load_meta(d).start
    out = []
    for o in orders:
        at = o["minute"] if "minute" in o else o["at"]
        out.append((float(at_minute(start, at)), str(o["side"]), str(o["text"])))
    return out
