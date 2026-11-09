"""A ready Sim from a battle pack: the staff and the umpire on one Jev client, the narrator, the
pack's end clock and battle-over rule, an ordinal pack's judge, and the initial reports.

    sim = build("data/plain-crossroads", seed=1, mode="record", log="runs/x.jsonl")

Modes are the JevClient modes (live, record, replay, stub) plus "log", which serves the Jev
answers of an earlier run log in order (`jev.LogReplayClient`, passed as `client`).
"""

from __future__ import annotations

import copy
from pathlib import Path

from .decisions_llm import make_client
from .jev import DEFAULT_FIXTURES, JevClient
from .jev import MODES as CLIENT_MODES
from .log import RunLog
from .narrator import Narrator
from .scenario import load, load_sides, relpath, resolve
from .sim import Sim
from .staff import JevStaff
from .umpire import umpire_for
from .verdict import ordinal_judge_for

MODES = (*CLIENT_MODES, "log")
NEVER = 10**9  # battle_over_after for a game played to its end (build(battle_over=False))


def build(
    scenario_dir: str | Path,
    seed: int,
    mode: str = "stub",
    *,
    fixture_dir: str | Path | None = None,
    log: str | Path | RunLog | None = None,
    client: JevClient | None = None,
    header: dict | None = None,
    battle_over: bool = True,
) -> Sim:
    """A ready Sim for the scenario with JevStaff and JevUmpire sharing one client (so the
    run log keeps their calls in the order made). `client` overrides `mode`; mode "log" needs
    a `LogReplayClient` passed as `client`. `header` adds keys to the log header.
    `battle_over=False` never asks the umpire whether the battle is over (on a pack without
    an ordinal verdict, the stub umpire would end every game at the first question)."""
    if mode not in MODES:
        raise ValueError(f"mode must be one of {MODES}")
    d = resolve(scenario_dir)
    world, formations, units, objectives, meta = load(d)
    if client is None:
        if mode == "log":
            raise ValueError("mode 'log' needs client=LogReplayClient(...)")
        # Jev, or a chat model standing in for it (JEV_MODEL=codex/<slug>)
        client = make_client(mode, fixture_dir or DEFAULT_FIXTURES)
    sides = load_sides(d)
    umpire = umpire_for(objectives, meta, sides, client)
    narrator = Narrator(world, meta, objectives, copy.deepcopy(formations), copy.deepcopy(units))
    # an ordinal pack (mission.json "verdict": "ordinal"): the mechanical judge ends the
    # battle (break, or possession at the end hour and in the play-on) and gives the verdict
    ordinal = ordinal_judge_for(d, world.features, list(umpire.sides), meta.start, meta.end_clock)
    narrator.ordinal = ordinal is not None  # the persona says the rule decides, not an umpire
    sim = Sim(
        world,
        formations,
        units,
        seed=seed,
        umpire=umpire,
        staff=JevStaff(client),
        log=log if isinstance(log, RunLog) or log is None else RunLog(log),
        clock_start=meta.start,
        scenario=relpath(d),
        jev_client=client,
        header={"jev_model": client.model, "mode": mode, **(header or {})},
        defer_header=True,
        narrator=narrator,
        scenario_dir=d,
        end_clock=meta.end_clock,
        account_context={
            "sides": list(umpire.sides),
            "objectives": umpire.objectives,
            "sunset": meta.sunset,
            "deadline": meta.deadline,
        },
        ordinal=ordinal,
        battle_over_after=meta.battle_over_after if battle_over else NEVER,
        battle_over_every=meta.battle_over_every,
    )
    # meta `initial_reports` {side: text}: what each army hq knows at the start beyond its
    # own sight (docs/pack-format.md), a report in hand at minute 0
    for side, text in sorted((meta.raw.get("initial_reports") or {}).items()):
        if side in sim.forces.sides() and text:
            sim.command.send_report(
                side, sim.forces.root(side).id, str(text), {"why": ["initial report"]}, 0, delay=0.0
            )
    sim.write_header()  # hash0: the state as the scenario left it, initial reports in hand
    return sim
