"""Umpire hooks: situation modifier clamped and logged; battle_over asked every
30 minutes after 2 hours; answers replay from the log."""

from __future__ import annotations

import copy

from test_engine_kit import body, load_testfield, make_sim
from test_engine_replay import orders

from kriegsspiel.log import RunLog
from kriegsspiel.replay import replay_tasks
from kriegsspiel.sim import Sim
from kriegsspiel.types import Ref, RefKind, Task, TaskKind, UnitState, Verdict


class FakeUmpire:
    def __init__(self, factor=2.0, over_at=None):
        self.factor, self.over_at, self.asked, self.contexts = factor, over_at, [], []

    def situation_modifier(self, context: str) -> float:
        self.contexts.append(context)
        return self.factor

    def battle_over(self, summary: str) -> bool:
        self.asked.append(summary)
        return self.over_at is not None and len(self.asked) >= self.over_at

    def verdict(self, summary: str) -> Verdict:
        return Verdict(winner="blue", rationale=summary[:20])


def test_situation_modifier_is_clamped_and_stored():
    inf = body("i", "red", "line", 2000.0, 2000.0, UnitState.SQUARE, facing=90.0)
    inf.disorder = 60.0  # an unsteady square: a melee (cavalry pulls up before a steady one)
    cav = body("k", "blue", "cuirassier", 2500.0, 2000.0, UnitState.LINE, facing=270.0, men=450)
    ump = FakeUmpire(factor=2.0)
    s = make_sim([inf, cav], umpire=ump)
    s.submit_tasks("blue", [Task(TaskKind.CHARGE, "k", Ref(RefKind.ENEMY, "i"))])
    s.submit_tasks("red", [Task(TaskKind.HOLD, "i", state=UnitState.SQUARE)])
    s.run(8)
    ev = next(e for e in s.events if e.kind == "melee")
    assert ev.data["umpire_factor"] == 1.4
    assert "charges" in ev.data["context"] and ump.contexts[0] == ev.data["context"]


def test_no_umpire_means_factor_one_and_no_early_end():
    w, f, u = load_testfield()
    s = Sim(w, f, u, seed=1)
    s.run(200)
    assert not s.over and s.now == 200
    assert s.verdict().winner == "undecided"


def test_battle_over_cadence_and_replay():
    w, f, u = load_testfield()
    f0, u0 = copy.deepcopy(f), copy.deepcopy(u)
    ump = FakeUmpire(factor=1.2, over_at=2)
    log = RunLog()
    s = Sim(w, f, u, seed=9, umpire=ump, log=log)
    orders(s)
    s.run(400)
    assert len(ump.asked) == 2  # at 120 and 150 minutes
    assert s.over and s.now == 150
    assert s.verdict().winner == "blue"
    res = replay_tasks(w, f0, u0, (log.header, log.records))
    assert res.ok and res.ticks == 150
