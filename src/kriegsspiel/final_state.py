"""The final state of a replayed run as plain JSON, for the umpire's account (umpire v2).

This file must run against any revision of the engine: a game is replayed bit-identically only
by the code it was played with, so `umpire rejudge --rev` exports that revision and runs this
file's source with the old `kriegsspiel` on the path. It therefore imports nothing from the
package at module level and touches only attributes every revision has (forces, rt, clock).

    python -c "$(cat final_state.py)" LOG OUT.json     # with PYTHONPATH=<tree>/src
"""

from __future__ import annotations

import json
import sys


def field_json(sim, with_hash: bool = True) -> dict:
    """Bodies (strength, state, position, flight goal) and the clock of `sim` as JSON;
    `with_hash=False` leaves out the state hash (the account asked in game)."""
    try:
        from kriegsspiel.clock import clock
    except ImportError:  # an engine from before the clock module
        from kriegsspiel.command import clock

    forms = sim.forces.formations
    offmap = getattr(sim, "offmap", None) or {}  # bodies off the map
    bodies = []
    for u in sim.forces.units.values():
        rt = sim.rt[u.id]
        f = forms.get(u.parent)
        route = list(getattr(rt, "route", []) or [])
        extra = {"fate": dict(offmap[u.id])} if u.id in offmap else {}
        bodies.append(
            {
                **extra,
                "id": u.id,
                "name": u.name,
                "side": u.side,
                "formation": f.name if f else u.parent,
                "arm": str(u.arm.value),
                "men": int(u.men),
                "start_men": int(rt.start_men),
                "x": float(u.x),
                "y": float(u.y),
                "state": str(u.state.value),
                "morale": float(u.morale if u.morale is not None else 0.0),
                "disorder": float(u.disorder),
                "flee_to": [float(route[0][0]), float(route[0][1])] if route else None,
                "engaged": bool(u.engaged),
            }
        )
    out = {"minutes": int(sim.now), "clock": clock(sim.clock_start, sim.now), "bodies": bodies}
    if with_hash:
        out["state_hash"] = sim.state_hash()
    return out


def replay_final(log_path: str) -> dict:
    """Replay `log_path` with the engine's Jev replay (`replay.replay_jev`, which serves the
    staff's and the umpire's calls from the log) and return its outcome and, when the replay
    was bit-identical, the final field."""
    try:
        from kriegsspiel.replay import replay_jev
    except ImportError:  # an engine from before replay_jev
        r, sim = _replay_run_patched(log_path)
    else:
        r = replay_jev(log_path)
        sim = r.sim
    out = {
        "ok": bool(r.ok),
        "ticks": r.ticks,
        "reason": r.reason,
        "first_mismatch": r.first_mismatch,
    }
    if r.ok and sim is not None:
        out["field"] = field_json(sim)
    return out


def _replay_run_patched(log_path: str):
    """`run.replay_run` of an older engine, which does not hand back its sim: the sim is
    caught as `run.build` makes it."""
    from kriegsspiel import run

    built = []
    orig = run.build

    def build(*a, **k):
        s = orig(*a, **k)
        built.append(s)
        return s

    run.build = build
    try:
        r = run.replay_run(log_path)
    finally:
        run.build = orig
    return r, built[-1] if built else None


def main(argv: list[str]) -> int:
    log_path, out_path = argv[1], argv[2]
    res = replay_final(log_path)
    with open(out_path, "w") as fh:
        json.dump(res, fh, ensure_ascii=False)
    return 0 if res["ok"] else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
