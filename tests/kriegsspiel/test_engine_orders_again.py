"""An order sent again leaves the body carrying it out as it was; a rally at a named place
goes there."""

from __future__ import annotations

import math

from test_engine_kit import body, make_sim

from kriegsspiel.command import same_orders
from kriegsspiel.types import Manner, Ref, RefKind, Task, TaskKind, UnitState


def _attack(**kw) -> Task:
    return Task(TaskKind.ATTACK, "a", Ref(RefKind.ENEMY, name="b"), manner=Manner.BOLD, **kw)


def test_same_orders_ignores_the_wording_and_the_times():
    a = _attack(source_text="First brigade, attack boldly.", issued_at=10.0, received_at=12.0)
    b = _attack(source_text="First brigade: attack them boldly!", issued_at=30.0)
    assert same_orders(a, b)
    assert not same_orders(a, Task(TaskKind.HOLD, "a"))
    assert not same_orders(a, _attack(then=Task(TaskKind.HOLD, "a")))
    assert not same_orders(None, a) and same_orders(None, None)


def _first_assault(resend_every: int | None) -> int:
    a = body("a", "blue", "line", 1000.0, 1000.0, UnitState.LINE, facing=0.0)
    b = body("b", "red", "line", 1000.0, 1400.0, UnitState.LINE, facing=180.0)
    s = make_sim([a, b])
    s.submit_tasks("blue", [_attack()])
    s.submit_tasks("red", [Task(TaskKind.HOLD, "b")])
    for t in range(1, 90):
        if resend_every and t % resend_every == 0:
            s.submit_tasks("blue", [_attack(source_text=f"again at {t}")])
        s.step()
        if s.rt["a"].phase == "assault":
            return t
    return 999


def test_an_attack_sent_again_does_not_restart_its_fire_before_the_bayonet():
    plain = _first_assault(None)
    assert plain < 999
    assert _first_assault(2) == plain


def test_a_different_order_still_takes_effect_at_once():
    a = body("a", "blue", "line", 1000.0, 1000.0, UnitState.LINE)
    s = make_sim([a])
    s.submit_tasks("blue", [Task(TaskKind.HOLD, "a")])
    s.step()
    s.submit_tasks(
        "blue", [Task(TaskKind.ADVANCE, "a", Ref(RefKind.POINT, point=(1000.0, 2000.0)))]
    )
    s.run(10)
    assert a.y > 1200.0


def test_a_rally_at_a_named_place_goes_there():
    here = (1000.0, 1000.0)
    there = (1000.0, 2200.0)

    def run(objective: Ref | None) -> float:
        u = body("u", "blue", "line", *here, UnitState.LINE)
        s = make_sim([u])
        s.submit_tasks("blue", [Task(TaskKind.RALLY, "u", objective)])
        s.run(40)
        return math.dist((u.x, u.y), there)

    assert run(None) == math.dist(here, there)  # without a place it rallies where it stands
    assert run(Ref(RefKind.POINT, point=there)) < 100.0


def test_a_rally_at_a_place_still_speeds_the_rally_of_a_broken_body():
    u = body("u", "blue", "line", 1000.0, 1000.0, UnitState.ROUTED)
    u.morale = 30.0
    s = make_sim([u])
    s.submit_tasks("blue", [Task(TaskKind.RALLY, "u", Ref(RefKind.POINT, point=(1000.0, 600.0)))])
    reformed = next((t for t in range(120) if (s.step(), u.state != UnitState.ROUTED)[1]), None)
    assert reformed is not None and reformed < 15
