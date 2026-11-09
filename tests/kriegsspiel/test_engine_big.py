"""A Kolín-sized stand-in: the test field tiled 3 x 3 at 25 m cells (12 km x 9 km, 252 bodies),
both sides on fixed orders for 6 hours. under 2 minutes of wall time."""

from __future__ import annotations

import copy
import time

import numpy as np
from test_engine_kit import load_testfield

from kriegsspiel.log import RunLog
from kriegsspiel.sim import Sim
from kriegsspiel.types import (
    Feature,
    Manner,
    OnContact,
    Ref,
    RefKind,
    Task,
    TaskKind,
    Terrain,
)
from kriegsspiel.world import World

TILES = 3


def big_field():
    w, forms, units = load_testfield()
    t = w.terrain
    elev = np.repeat(np.repeat(t.elev_m, 2, axis=0), 2, axis=1)
    cover = np.repeat(np.repeat(t.cover, 2, axis=0), 2, axis=1)
    elev = np.tile(elev, (TILES, TILES))
    cover = np.tile(cover, (TILES, TILES))
    feats, out_f, out_u = [], [], []
    W, H = t.width_m, t.height_m
    for ti in range(TILES):
        for tj in range(TILES):
            dx, dy, tag = tj * W, ti * H, f"{ti}{tj}"
            feats.extend(
                Feature(
                    name=f"{f.name} {tag}",
                    kind=f.kind,
                    geometry_kind=f.geometry_kind,
                    coords=[(x + dx, y + dy) for x, y in f.coords],
                )
                for f in w.features
            )
            for f in forms:
                if f.parent is None:
                    continue
                g = copy.deepcopy(f)
                g.id, g.name, g.aliases = f"{f.id}.{tag}", f"{f.name} {tag}", []
                out_f.append(g)
            for u in units:
                v = copy.deepcopy(u)
                v.id, v.parent, v.x, v.y = f"{u.id}.{tag}", f"{u.parent}.{tag}", u.x + dx, u.y + dy
                out_u.append(v)
    for f in forms:
        if f.parent is None:
            g = copy.deepcopy(f)
            g.hq = (f.hq[0] + W, f.hq[1] + H) if f.hq else None
            out_f.append(g)
    world = World(Terrain(cell_m=25.0, elev_m=elev, cover=cover), feats)
    return world, out_f, out_u


def scripted_orders(sim: Sim, tags) -> None:
    for tag in tags:
        sim.submit_tasks(
            "blue",
            [
                Task(
                    TaskKind.ATTACK,
                    f"B-inf1.{tag}",
                    Ref(RefKind.FEATURE, f"Hoher Ruecken {tag}"),
                    manner=Manner.MEASURED,
                ),
                Task(
                    TaskKind.ATTACK,
                    f"B-inf2.{tag}",
                    Ref(RefKind.FEATURE, f"Kapellenberg {tag}"),
                    manner=Manner.BOLD,
                ),
                Task(TaskKind.BOMBARD, f"B-art.{tag}", Ref(RefKind.FEATURE, f"Kapellenberg {tag}")),
                Task(
                    TaskKind.ADVANCE,
                    f"B-cav.{tag}",
                    Ref(RefKind.FEATURE, f"Muehle {tag}"),
                    on_contact=OnContact.ENGAGE,
                ),
            ],
            text=f"general attack {tag}",
        )
        sim.submit_tasks(
            "red",
            [
                Task(TaskKind.HOLD, f"R-inf1.{tag}"),
                Task(TaskKind.HOLD, f"R-inf2.{tag}"),
                Task(TaskKind.BOMBARD, f"R-art.{tag}"),
                Task(TaskKind.HOLD, f"R-cav.{tag}"),
            ],
            text=f"hold the ridge {tag}",
        )
        # a counter-attack written in advance for the second hour
        sim.submit_tasks(
            "red",
            [Task(TaskKind.CHARGE, f"R-cav.{tag}", Ref(RefKind.FEATURE, f"Neudorf {tag}"))],
            at=90,
            text=f"cavalry forward {tag}",
        )


def test_six_hour_afternoon_runs_under_two_minutes():
    world, forms, units = big_field()
    assert len(units) == 252
    sim = Sim(world, forms, units, seed=11, log=RunLog())
    scripted_orders(sim, [f"{i}{j}" for i in range(TILES) for j in range(TILES)])
    t0 = time.perf_counter()
    sim.run(360)
    wall = time.perf_counter() - t0
    print(f"360 ticks, {len(units)} bodies: {wall:.1f} s; losses {sim.losses()}")
    assert wall < 120.0
    total = sum(sim.losses().values())
    assert 3_000 <= total <= 60_000
