"""Vision: who sees whom, at what level of identification.

Sightings accrue to the brigade commander at once (`brigade_known`) and to the army commander
only by report or by what the army hq itself sees (command.py).
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from .types import Arm, Cover, UnitState

# ---------------------------------------------------------------------------
# Constants
RANGE_OPEN_M = 2500.0  # spec: daylight, open
RANGE_INTO_COVER_M = 400.0  # spec: into woods or villages
IDENT_ROUGH_M = 1200.0  # spec: arm and rough size
IDENT_EXACT_M = 500.0  # spec: exact
HQ_EYE_M = 3.0  # assumption: a mounted general's eye height
BODY_EYE_M = 2.0  # spec default eye height
MEMORY_MIN = 30  # assumption: a brigade remembers an unseen enemy body for 30 minutes
ROUGH_ROUND = 100  # assumption: rough size is given to the nearest 100 men (guns exact)
LOS_CACHE_MAX = 400_000  # bound on cached static LOS answers


@dataclass
class Sighting:
    key: str  # enemy unit id (engine handle)
    x: float
    y: float
    ident: int  # 0 'troops', 1 arm + rough size, 2 exact
    arm: str | None
    est_men: int | None
    seen_at: int
    dist: float = 0.0
    state: str | None = None  # formation state when identified exactly
    routed: bool = False

    def to_json(self) -> dict:
        return {
            "key": self.key,
            "x": self.x,
            "y": self.y,
            "ident": self.ident,
            "arm": self.arm,
            "est_men": self.est_men,
            "seen_at": self.seen_at,
            "dist": self.dist,
            "state": self.state,
            "routed": self.routed,
        }

    @classmethod
    def from_json(cls, d: dict) -> Sighting:
        return cls(**d)


def ident_level(d: float) -> int:
    if d <= IDENT_EXACT_M:
        return 2
    if d <= IDENT_ROUGH_M:
        return 1
    return 0


def describe(target, d: float, now: int) -> Sighting:
    lvl = ident_level(d)
    strength = target.men if target.arm != Arm.ARTILLERY else target.guns
    est = None
    if lvl == 2:
        est = int(strength)
    elif lvl == 1:
        est = (
            int(strength)
            if target.arm == Arm.ARTILLERY
            else int(max(ROUGH_ROUND, round(strength / ROUGH_ROUND) * ROUGH_ROUND))
        )
    return Sighting(
        key=target.id,
        x=float(target.x),
        y=float(target.y),
        ident=lvl,
        arm=target.arm.value if lvl >= 1 else None,
        est_men=est,
        seen_at=now,
        dist=float(d),
        state=target.state.value if lvl == 2 else None,
        routed=target.state == UnitState.ROUTED and lvl >= 1,
    )


class Vision:
    """Per tick: per-body visible enemy lists; per-brigade knowledge with memory."""

    def __init__(self, world):
        self.world = world
        self.visible: dict[str, list[tuple[str, float]]] = {}  # observer -> [(target, dist)]
        self.brigade_known: dict[str, dict[str, Sighting]] = {}
        self._los_cache: dict[tuple[int, int, int], bool] = {}

    def los_pairs(self, ax, ay, bx, by, eye_m: float) -> np.ndarray:
        """LOS for pairs with a static cache keyed by (observer cell, target cell, eye tag)."""
        n = len(ax)
        out = np.zeros(n, dtype=bool)
        if n == 0:
            return out
        w = self.world
        ia, ja = w.cell_ij_many(ax, ay)
        ib, jb = w.cell_ij_many(bx, by)
        ka = (ia * w.nx + ja).tolist()
        kb = (ib * w.nx + jb).tolist()
        miss = []
        cache = self._los_cache
        tag = 0 if eye_m == BODY_EYE_M else 1
        for idx in range(n):
            key = (ka[idx], kb[idx], tag)
            v = cache.get(key)
            if v is None:
                miss.append(idx)
            else:
                out[idx] = v
        if miss:
            m = np.array(miss)

            # evaluate from cell centres so the cache is exact for its key
            def cx(j):
                return w.ox + (j + 0.5) * w.cell

            def cy(i):
                return w.oy + (i + 0.5) * w.cell

            a = np.stack([cx(ja[m]), cy(ia[m])], axis=1)
            b = np.stack([cx(jb[m]), cy(ib[m])], axis=1)
            res = np.zeros(len(m), dtype=bool)
            for s in range(0, len(m), 4096):
                res[s : s + 4096] = w.los_many(a[s : s + 4096], b[s : s + 4096], eye_m)
            if len(cache) > LOS_CACHE_MAX:
                cache.clear()
            for k, idx in enumerate(miss):
                cache[(ka[idx], kb[idx], tag)] = bool(res[k])
            out[m] = res
        return out

    def update(self, forces, now: int) -> list[dict]:
        """Recompute sight for all bodies. Returns first-sighting events (per brigade)."""
        units = [u for u in forces.units.values() if u.state != UnitState.DESTROYED]
        self.visible = {}
        events = []
        if not units:
            return events
        xs = np.array([u.x for u in units])
        ys = np.array([u.y for u in units])
        sides = np.array([u.side for u in units])
        covers = np.array([int(self.world.cover(u.x, u.y)) for u in units])
        rng = np.where(
            np.isin(covers, (Cover.WOOD, Cover.VILLAGE)), RANGE_INTO_COVER_M, RANGE_OPEN_M
        )
        obs_ok = np.array([u.state != UnitState.ROUTED for u in units])
        d = np.hypot(xs[:, None] - xs[None, :], ys[:, None] - ys[None, :])
        cand = (sides[:, None] != sides[None, :]) & (d <= rng[None, :]) & obs_ok[:, None]
        oi, ti = np.nonzero(cand)
        seen = self.los_pairs(xs[oi], ys[oi], xs[ti], ys[ti], BODY_EYE_M)
        oi, ti = oi[seen], ti[seen]
        for o, t in zip(oi.tolist(), ti.tolist(), strict=True):
            self.visible.setdefault(units[o].id, []).append((units[t].id, float(d[o, t])))
        for k in self.visible:
            self.visible[k].sort(key=lambda p: (p[1], p[0]))
        # brigade knowledge: best (closest) observation per enemy body
        fresh: dict[str, dict[str, Sighting]] = {}
        by_id = forces.units
        for oid in sorted(self.visible):
            bid = by_id[oid].parent
            known = fresh.setdefault(bid, {})
            for tid, dd in self.visible[oid]:
                prev = known.get(tid)
                if prev is None or dd < prev.dist:
                    known[tid] = describe(by_id[tid], dd, now)
        for bid in sorted(set(self.brigade_known) | set(fresh)):
            old = self.brigade_known.get(bid, {})
            new = fresh.get(bid, {})
            merged = {
                k: v
                for k, v in old.items()
                if now - v.seen_at <= MEMORY_MIN
                and k not in new
                and by_id[k].state != UnitState.DESTROYED
            }
            for k, v in new.items():
                if k not in old:
                    events.append(
                        {"brigade": bid, "target": k, "ident": v.ident, "dist": round(v.dist, 1)}
                    )
                merged[k] = v
            self.brigade_known[bid] = dict(sorted(merged.items()))
        return events

    def seen_from(self, forces, point, side: str, now: int) -> dict[str, Sighting]:
        """What an observer at `point` (e.g. the army hq) sees of the enemies of `side`."""
        tg = [u for u in forces.units.values() if u.side != side and u.state != UnitState.DESTROYED]
        if not tg:
            return {}
        bx = np.array([u.x for u in tg])
        by = np.array([u.y for u in tg])
        d = np.hypot(bx - point[0], by - point[1])
        covers = np.array([int(self.world.cover(u.x, u.y)) for u in tg])
        rng = np.where(
            np.isin(covers, (Cover.WOOD, Cover.VILLAGE)), RANGE_INTO_COVER_M, RANGE_OPEN_M
        )
        idx = np.nonzero(d <= rng)[0]
        ok = self.los_pairs(
            np.full(len(idx), point[0]), np.full(len(idx), point[1]), bx[idx], by[idx], HQ_EYE_M
        )
        return {tg[i].id: describe(tg[i], float(d[i]), now) for i in idx[ok].tolist()}

    def known(self, brigade_id: str) -> dict[str, Sighting]:
        return self.brigade_known.get(brigade_id, {})

    def snapshot(self) -> dict:
        return {
            b: [
                [s.key, s.x, s.y, s.ident, s.arm, s.est_men, s.seen_at, s.dist, s.state, s.routed]
                for s in v.values()
            ]
            for b, v in sorted(self.brigade_known.items())
        }
