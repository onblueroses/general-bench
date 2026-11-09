"""Bodies and formations: construction, loading, hierarchy queries.

File format of oob.json and deployment.json: docs/pack-format.md.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from .geometry import Point, centroid
from .types import Arm, Formation, Unit, UnitKind, UnitState

# ---------------------------------------------------------------------------
# Constants
FILE_M_LINE = 0.6  # assumption: frontage per file in line, metres (shoulder to shoulder)
RANKS = {"infantry": 3, "cavalry": 2}  # assumption: 3 ranks of foot, 2 of horse (1750s)
GUN_FRONT_M = 15.0  # assumption: frontage per gun in battery
COLUMN_FRONT_M = 50.0  # assumption: frontage of a column of divisions / squadrons
INTERVAL_M = 30.0  # assumption: interval between bodies in line

ARM_OF_KIND = {
    UnitKind.LINE: Arm.INFANTRY,
    UnitKind.GRENADIER: Arm.INFANTRY,
    UnitKind.FUSILIER: Arm.INFANTRY,
    UnitKind.GRENZER: Arm.INFANTRY,
    UnitKind.CUIRASSIER: Arm.CAVALRY,
    UnitKind.DRAGOON: Arm.CAVALRY,
    UnitKind.HUSSAR: Arm.CAVALRY,
    UnitKind.FOOT_BATTERY: Arm.ARTILLERY,
    UnitKind.HORSE_BATTERY: Arm.ARTILLERY,
    UnitKind.TRAIN: Arm.TRAIN,
}


# ---------------------------------------------------------------------------
# Frontage


def frontage(u: Unit, state: UnitState | None = None) -> float:
    s = state or u.state
    if u.arm == Arm.ARTILLERY:
        return max(1, u.guns) * GUN_FRONT_M
    if u.arm == Arm.TRAIN:
        return COLUMN_FRONT_M
    if s in (UnitState.COLUMN, UnitState.SQUARE, UnitState.ROUTED, UnitState.LIMBERED):
        return COLUMN_FRONT_M
    ranks = RANKS["cavalry" if u.arm == Arm.CAVALRY else "infantry"]
    width = u.men / ranks * FILE_M_LINE * (1.5 if u.arm == Arm.CAVALRY else 1.0)
    if s == UnitState.SKIRMISH:
        width *= 2.0
    return max(COLUMN_FRONT_M, width)


# ---------------------------------------------------------------------------
# Hierarchy


class Forces:
    """Index over formations and units; all iteration in sorted id order."""

    def __init__(self, formations: list[Formation], units: list[Unit]):
        self.formations = {f.id: f for f in sorted(formations, key=lambda f: f.id)}
        self.units = {u.id: u for u in sorted(units, key=lambda u: u.id)}
        # where a formation with no body on the map is (its entry, or where it left the map);
        # set by the Sim; None, or no answer from it: (0, 0)
        self.inert_anchor = None
        for f in self.formations.values():
            f.children = sorted(c.id for c in self.formations.values() if c.parent == f.id)
            f.units = sorted(u.id for u in self.units.values() if u.parent == f.id)

    def sides(self) -> list[str]:
        return sorted({u.side for u in self.units.values()})

    def root(self, side: str) -> Formation:
        roots = [f for f in self.formations.values() if f.side == side and not f.parent]
        if len(roots) != 1:
            raise ValueError(f"side {side} needs exactly one root formation, has {len(roots)}")
        return roots[0]

    def bodies(self, fid: str) -> list[Unit]:
        """All units under a formation (or the unit itself), sorted by id."""
        if fid in self.units:
            return [self.units[fid]]
        f = self.formations[fid]
        out = [self.units[u] for u in f.units]
        for c in f.children:
            out.extend(self.bodies(c))
        return sorted(out, key=lambda u: u.id)

    def brigade_of(self, uid: str) -> Formation:
        return self.formations[self.units[uid].parent]

    def brigades(self, side: str | None = None) -> list[Formation]:
        """Formations that hold bodies directly."""
        return [f for f in self.formations.values() if f.units and (side is None or f.side == side)]

    def ancestors(self, fid: str) -> list[str]:
        out = []
        f = self.formations.get(fid) or self.formations[self.units[fid].parent]
        if fid in self.units:
            out.append(f.id)
        while f.parent:
            out.append(f.parent)
            f = self.formations[f.parent]
        return out

    def centroid(self, fid: str) -> Point | None:
        bs = [u for u in self.bodies(fid) if u.state != UnitState.DESTROYED]
        if not bs:
            return None
        return centroid([(u.x, u.y) for u in bs])

    def hq(self, fid: str) -> Point:
        f = self.formations.get(fid)
        if f is not None and f.hq is not None:
            return f.hq
        c = self.centroid(fid)
        if c is None:
            c = (self.inert_anchor(fid) if self.inert_anchor is not None else None) or (0.0, 0.0)
        return c

    def resolve(self, name: str, side: str) -> str | None:
        """Formation or unit id by id, name, commander or alias (case-insensitive)."""
        key = name.casefold()
        for f in self.formations.values():
            if f.side == side and key in {
                f.id.casefold(),
                f.name.casefold(),
                f.commander.casefold(),
                *(a.casefold() for a in f.aliases),
            }:
                return f.id
        for u in self.units.values():
            if u.side == side and key in (u.id.casefold(), u.name.casefold()):
                return u.id
        return None


# ---------------------------------------------------------------------------
# Files


def _pieces(d: dict, word: str) -> int:
    """How many of a battery's guns are howitzers or mortars: the `howitzers` / `mortars` key
    when present, else the count the `source` note gives ("8 x 12-pdr + 2 howitzers"): a
    historical oob may record the split only in prose."""
    if word in d:
        return int(d[word])
    m = re.search(rf"(\d+)\s+{word[:-1]}s?\b", str(d.get("source", "")))
    return int(m.group(1)) if m else 0


def unit_from_json(d: dict, dep: dict | None = None) -> Unit:
    kind = UnitKind(d["kind"])
    arm = Arm(d.get("arm") or ARM_OF_KIND[kind])
    dep = dep or {}
    crew = int(d.get("crew", 0))
    men = int(d.get("men", crew))
    state = dep.get("state") or ("limbered" if arm == Arm.ARTILLERY else "column")
    if arm == Arm.TRAIN:
        state = "column"  # a train forms nothing
    guns = int(d.get("guns", 0))
    howitzers = mortars = 0
    if arm == Arm.ARTILLERY:
        howitzers = min(guns, _pieces(d, "howitzers"))
        mortars = min(guns - howitzers, _pieces(d, "mortars"))
    asm = dep.get("assemble")
    return Unit(
        id=d["id"],
        name=d["name"],
        side=d["side"],
        parent=d["parent"],
        arm=arm,
        kind=kind,
        men=men,
        quality=int(d["quality"]),
        x=float(dep.get("x", 0.0)),
        y=float(dep.get("y", 0.0)),
        facing_deg=float(dep.get("facing_deg", 0.0)),
        state=UnitState(state),
        guns=guns,
        crew=crew,
        calibre_lb=int(d.get("calibre_lb", 0)),
        bn_guns=int(d.get("battalion_guns", 0)) if arm == Arm.INFANTRY else 0,
        howitzers=howitzers,
        mortars=mortars,
        # a clock string here; scenario.load turns it into minutes after the start
        arrives_at=dep.get("arrives_at"),
        entry=dep.get("entry"),
        assemble=tuple(asm) if isinstance(asm, list) else asm,
    )  # type: ignore[arg-type]


def formation_from_json(d: dict, hq: list | None = None) -> Formation:
    return Formation(
        id=d["id"],
        name=d["name"],
        side=d["side"],
        commander=d["commander"],
        parent=d.get("parent"),
        hq=tuple(hq) if hq else None,  # type: ignore[arg-type]
        aliases=list(d.get("aliases", [])),
        level=d.get("level", "brigade"),
    )


def load_forces(directory: str | Path) -> tuple[list[Formation], list[Unit]]:
    d = Path(directory)
    oob = json.loads((d / "oob.json").read_text())
    dep = json.loads((d / "deployment.json").read_text())
    hqs = dep.get("hq", {})
    formations = [formation_from_json(f, hqs.get(f["id"])) for f in oob["formations"]]
    units = [unit_from_json(u, dep["units"].get(u["id"])) for u in oob["units"]]
    return formations, units
