"""Shared builders for the engine tests: flat worlds, single bodies, the test packs, and a
scripted staff that maps order text to ready-made tasks."""

from __future__ import annotations

import copy
from pathlib import Path

import numpy as np

from kriegsspiel.log import RunLog
from kriegsspiel.sim import Sim
from kriegsspiel.types import (
    Arm,
    Cover,
    Feature,
    Formation,
    SideView,
    Task,
    Terrain,
    Unit,
    UnitKind,
    UnitState,
)
from kriegsspiel.units import load_forces
from kriegsspiel.world import World

ROOT = Path(__file__).resolve().parents[2]
PACKS = Path(__file__).resolve().parent / "fixtures" / "packs"  # the test-only packs
KOLIN = PACKS / "kolin"
TESTFIELD = PACKS / "testfield"
ARM = {
    "line": Arm.INFANTRY,
    "grenadier": Arm.INFANTRY,
    "cuirassier": Arm.CAVALRY,
    "hussar": Arm.CAVALRY,
    "foot_battery": Arm.ARTILLERY,
    "horse_battery": Arm.ARTILLERY,
}  # the arm of each body kind `body` builds


def flat_world(
    size_m: float = 4000.0,
    cell: float = 25.0,
    cover=None,
    elev=None,
    features: list[Feature] | None = None,
) -> World:
    n = int(size_m / cell)
    xs = (np.arange(n) + 0.5) * cell
    X, Y = np.meshgrid(xs, xs)
    e = np.full((n, n), 200.0, dtype=np.float32) if elev is None else elev(X, Y).astype(np.float32)
    c = np.full((n, n), Cover.OPEN, dtype=np.uint8)
    if cover is not None:
        c = cover(X, Y, c).astype(np.uint8)
    return World(Terrain(cell_m=cell, elev_m=e, cover=c), features or [])


def body(
    uid: str,
    side: str,
    kind: str,
    x: float,
    y: float,
    state: UnitState,
    facing: float = 0.0,
    men: int = 600,
    quality: int = 3,
    guns: int = 0,
    calibre: int = 6,
    brigade: str | None = None,
) -> Unit:
    arm = ARM[kind]
    crew = guns * 10 if arm == Arm.ARTILLERY else 0
    return Unit(
        id=uid,
        name=uid,
        side=side,
        parent=brigade or f"{side}-b-{uid}",
        arm=arm,
        kind=UnitKind(kind),
        men=crew if crew else men,
        quality=quality,
        x=x,
        y=y,
        facing_deg=facing,
        state=state,
        guns=guns,
        crew=crew,
        calibre_lb=calibre,
    )


def forces_for(
    units: list[Unit], hq: dict[str, tuple[float, float]] | None = None
) -> list[Formation]:
    """One army root per side, one brigade per distinct parent."""
    hq = hq or {}
    out = []
    for side in sorted({u.side for u in units}):
        root = f"{side}-army"
        out.append(
            Formation(
                id=root,
                name=f"{side} army",
                side=side,
                commander=f"{side} C",
                parent=None,
                hq=hq.get(side),
                level="army",
            )
        )
        out.extend(
            Formation(id=b, name=b, side=side, commander=f"{b} cdr", parent=root)
            for b in sorted({u.parent for u in units if u.side == side})
        )
    return out


def make_sim(
    units: list[Unit],
    world: World | None = None,
    seed: int = 7,
    hq: dict[str, tuple[float, float]] | None = None,
    log: RunLog | None = None,
    **kw,
) -> Sim:
    w = world or flat_world()
    return Sim(w, forces_for(units, hq), units, seed=seed, log=log, **kw)


def load_testfield() -> tuple[World, list[Formation], list[Unit]]:
    w = World.load(TESTFIELD)
    f, u = load_forces(TESTFIELD)
    return w, f, u


def test_kit_builds_a_world():
    w = flat_world()
    assert w.cover(10, 10) == Cover.OPEN and w.elev(100, 100) == 200.0


class ScriptedStaff:
    """Test staff: maps order text to ready-made tasks (no language model)."""

    def __init__(self, script: dict[str, list[Task]] | None = None):
        self.script: dict[str, list[Task]] = dict(script or {})
        self.clarifications: list[str] = []

    def add(self, text: str, tasks: list[Task]) -> str:
        self.script[text] = tasks
        return text

    def translate(self, text: str, side_view: SideView) -> list[Task]:
        out = []
        for t in self.script.get(text, []):
            t2 = copy.deepcopy(t)
            t2.source_text = t2.source_text or text
            out.append(t2)
        return out


def test_hold_is_default_noop():
    u = body("a", "blue", "line", 1000, 1000, UnitState.LINE)
    s = make_sim([u])
    s.step()
    assert (u.x, u.y) == (1000, 1000)
