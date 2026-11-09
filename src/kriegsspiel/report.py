"""The plain-text report of a finished game: clock, losses, every order with the tasks the
staff read from it, the umpire's account and the verdict; for a played game also one line per
consultation."""

from __future__ import annotations

from .clock import clock
from .play import GameResult
from .types import UnitState


def report(res: GameResult) -> str:
    sim = res.sim
    lines = [
        (
            f"Clock {clock(sim.clock_start, sim.now)} ({sim.now} min), "
            f"{'battle over' if sim.over else 'time limit'}; wall {res.wall_s:.1f} s, "
            f"{res.calls} Jev calls, ${res.cost:.5f} (recorded cost)."
        )
    ]
    for side, lost in sim.losses().items():
        routed = [
            u.name
            for u in sim.forces.units.values()
            if u.side == side and u.state == UnitState.ROUTED
        ]
        gone = sum(
            u.side == side and u.state == UnitState.DESTROYED and u.id not in sim.offmap
            for u in sim.forces.units.values()
        )
        lines.append(
            f"{side}: {lost:,} lost; {len(routed)} routed, {gone} destroyed"
            + (
                f" ({', '.join(routed[:12])}{', ...' if len(routed) > 12 else ''})"
                if routed
                else ""
            )
        )
        off = sim.offmap_counts(side)
        if off:
            lines.append(f"  {side}: {off}")
    lines.append("Orders:")
    for o in res.orders:
        tasks = "; ".join(
            f"{t['formation']} {t['kind']}"
            + (
                f" -> {t['objective'].get('name') or t['objective'].get('point')}"
                if t.get("objective")
                else ""
            )
            + (f" then {t['then']['kind']}" if t.get("then") else "")
            for t in o["tasks"]
        )
        lines.append(f"  [{o['side']} {o['at']:.0f}] {o['text']}\n      => {tasks or '(none)'}")
        lines.extend(f"      ?? {c}" for c in o.get("clarifications", []))
    lines.append("Summary:\n" + sim.summary())
    v = res.verdict
    if v.ordinal is not None:  # the rule decided; its rationale says how and when
        lines.append(f"Verdict: {v.rationale}")
    else:
        per = "".join(f"; {s} achieved {lvl}" for s, lvl in v.achieved.items())
        lines.append(
            f"Verdict: winner {v.winner}{per}; attacker achieved {v.attacker_achieved}; "
            f"decisiveness {v.decisiveness}; {v.rationale}"
        )
    return "\n".join(lines)


def play_report(res: GameResult) -> str:
    """The report plus one line per consultation."""
    lines = [report(res), "Consultations:"]
    lines.extend(
        f"  {r['side']} {r['consulted_clock']} -> {r['arrived_clock'] or 'after the end'} "
        f"({r['trigger']}): {r['wall_s']:.1f} s, {len(r['orders'])} orders"
        for r in res.consultations
    )
    return "\n".join(lines)
