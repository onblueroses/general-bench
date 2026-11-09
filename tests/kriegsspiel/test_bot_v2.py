"""The bot's presets: what separates the strong one from the weak one.

Each test builds a pack at minute 0 and drives one planning step of `BotCommander` with a
hand-made picture fragment (contacts, reports), so no game is played."""

from __future__ import annotations

import pytest

from kriegsspiel import geometry as geo
from kriegsspiel.bot import REAR_GUARD_MIN, BotCommander
from kriegsspiel.build import build
from kriegsspiel.command import Contact
from kriegsspiel.types import TaskKind


def bot(side: str, preset: str, pack: str = "plain-crossroads") -> BotCommander:
    sim = build(f"data/{pack}", 1, "stub")
    return BotCommander(sim, side, preset)


def contact(
    key: str,
    x: float,
    y: float,
    arm: str = "infantry",
    men: int | None = 600,
    routed: bool = False,
    seen: int = 0,
) -> Contact:
    return Contact(
        key=key,
        name=f"the enemy {arm} {key}",
        arm=arm,
        est_men=men,
        x=x,
        y=y,
        seen_at=seen,
        learned_at=seen,
        source="hq",
        routed=routed,
    )


def test_presets_differ_in_the_reserve():
    """Weak sends every infantry element to the objective; strong holds back the infantry
    farthest from it, then sends the rest."""
    w = bot("red", "weak")
    s = bot("red", "strong")
    assert not w.reserve and s.reserve
    w.plan(0)
    s.plan(0)
    inf = {k for k, e in w.elements.items() if e.arm == "infantry"}
    assert w.allotted == inf
    assert s.allotted == inf - set(s.reserve)
    far = max(geo.dist(s.elements[k].pos, s.place.point) for k in s.allotted)
    assert all(geo.dist(s.elements[k].pos, s.place.point) >= far for k in s.reserve)


def test_a_body_seen_too_far_to_count_is_never_weakened():
    """A contact once counted at 1,200 and now seen with no count (ident 0) is not "a third
    fewer": v1 read the unknown default (600) against the old count and chased it."""
    b = bot("red", "strong")
    b.max_seen["F1"] = 1200
    assert not b._weakened(contact("F1", 0, 0, men=None), 10)
    assert b._weakened(contact("F1", 0, 0, men=700), 10)


def test_strong_reads_a_rallied_enemy_as_shaken():
    for preset, want in (("strong", True), ("weak", False)):
        b = bot("red", preset)
        b.routed_at["F2"] = 20.0
        b.max_seen["F2"] = 600
        assert b._weakened(contact("F2", 0, 0, men=600, seen=40), 40) is want
        assert not b._weakened(contact("F2", 0, 0, men=600, seen=80), 80)


def test_reckoning_moves_an_element_out_of_contact_only():
    b = bot("red", "strong")
    e = next(x for x in b.elements.values() if x.arrives_at is None and x.arm == "infantry")
    goal = geo.offset(e.pos, 90.0, 5000.0)
    b.goal[e.id] = (goal, 5.0)
    moved = b._reckon(e, 25)
    assert geo.dist(moved, e.pos) == pytest.approx(20 * 50.0)  # 20 min at the planning rate
    assert geo.dist(moved, goal) < geo.dist(e.pos, goal)
    e.engaged_at = 20.0  # a report with the enemy in sight
    assert b._reckon(e, 25) == e.pos
    assert BotCommander(b.sim, "red", "weak").doctrine.reckon is False


def test_strong_rallies_a_broken_brigade_and_weak_does_not():
    for preset in ("strong", "weak"):
        b = bot("red", preset)
        e = next(x for x in b.elements.values() if x.arm == "infantry")
        b.broken[e.id] = 30.0
        r = b._rally(31, e, [])
        if preset == "strong":
            assert r is not None and r[0].kind == TaskKind.RALLY
            # a formed enemy near: no rally
            b2 = bot("red", preset)
            b2.broken[e.id] = 30.0
            assert b2._rally(31, b2.elements[e.id], [contact("X", *e.pos)]) is None
        else:
            assert r is None


def test_staged_withdrawal_holds_a_rear_guard_then_follows():
    b = bot("red", "strong")
    live = dict(b.elements)
    enemy = [contact("F9", *geo.offset(b.start_centroid, 180.0, 800.0))]
    b.withdraw_at = 100.0
    first: dict = {}
    b._plan_withdrawal(100, live, enemy, (enemy[0].x, enemy[0].y), first)
    holds = {k for k, (t, _) in first.items() if t.kind == TaskKind.HOLD}
    goes = {k for k, (t, _) in first.items() if t.kind == TaskKind.WITHDRAW}
    assert holds and goes
    men = {k: b.elements[k].men for k in first}
    assert sum(men[k] for k in holds) <= 0.25 * sum(men.values()) + max(men.values())
    later: dict = {}
    b._plan_withdrawal(100 + REAR_GUARD_MIN, live, enemy, (enemy[0].x, enemy[0].y), later)
    assert all(t.kind == TaskKind.WITHDRAW for t, _ in later.values())
    w = bot("red", "weak")
    w.withdraw_at = 100.0
    allgo: dict = {}
    w._plan_withdrawal(100, dict(w.elements), enemy, (enemy[0].x, enemy[0].y), allgo)
    assert all(t.kind == TaskKind.WITHDRAW for t, _ in allgo.values())
