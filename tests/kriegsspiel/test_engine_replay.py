"""Replay is bit-identical over 60 ticks on the test field with scripted orders;
a scripted test-field afternoon produces losses in the thousands."""

from __future__ import annotations

import copy

from test_engine_kit import ScriptedStaff, load_testfield

from kriegsspiel.log import RunLog, read_log
from kriegsspiel.replay import replay_tasks
from kriegsspiel.sim import Sim
from kriegsspiel.types import Manner, OnContact, Ref, RefKind, Task, TaskKind, UnitState


def orders(sim: Sim) -> None:
    sim.submit_tasks(
        "blue",
        [
            Task(TaskKind.ATTACK, "B-inf1", Ref(RefKind.FEATURE, "Hoher Ruecken")),
            Task(
                TaskKind.ATTACK, "B-inf2", Ref(RefKind.FEATURE, "Kapellenberg"), manner=Manner.BOLD
            ),
            Task(TaskKind.BOMBARD, "B-art", Ref(RefKind.FEATURE, "Kapellenberg")),
            Task(
                TaskKind.ADVANCE,
                "B-cav",
                Ref(RefKind.FEATURE, "Muehle"),
                route=[Ref(RefKind.FEATURE, "Muehlbach bridge")],
                on_contact=OnContact.ENGAGE,
            ),
        ],
        text="The army attacks the ridge.",
    )
    sim.submit_tasks(
        "red",
        [
            Task(TaskKind.HOLD, "R-inf1"),
            Task(TaskKind.HOLD, "R-inf2"),
            Task(TaskKind.BOMBARD, "R-art"),
            Task(TaskKind.SCREEN, "R-cav", Ref(RefKind.FEATURE, "Eichwald")),
        ],
        text="Hold the ridge.",
    )
    sim.submit_tasks(
        "red",
        [Task(TaskKind.CHARGE, "R-cav", Ref(RefKind.FEATURE, "Neudorf"))],
        at=40,
        text="Cavalry, forward.",
    )


def test_replay_is_bit_identical_over_60_ticks(tmp_path):
    w, f, u = load_testfield()
    f0, u0 = copy.deepcopy(f), copy.deepcopy(u)
    staff = ScriptedStaff()
    staff.add("Kirchweg!", [Task(TaskKind.ADVANCE, "B-inf1", Ref(RefKind.FEATURE, "Kirchweg"))])
    path = tmp_path / "run.jsonl"
    sim = Sim(w, f, u, seed=3, log=RunLog(path), staff=staff, scenario="testfield")
    orders(sim)
    sim.submit_order("blue", "Kirchweg!", at=25)  # through the staff, logged with its tasks
    sim.run(60)
    header, records = read_log(path)
    assert len(records) == 60 and header["seed"] == 3
    assert any(r["orders"] for r in records[1:])
    # replay on a fresh world object and on the same one (caches must not matter)
    w2, _, _ = load_testfield()
    res = replay_tasks(w2, f0, u0, path)
    assert res.ok, res
    assert res.ticks == 60
    assert replay_tasks(w, f0, u0, (header, records)).ok
    # positive control: a tampered order is caught
    bad = copy.deepcopy(records)
    for r in bad:
        for o in r["orders"]:
            for t in o["tasks"]:
                if t["formation"] == "B-inf2":
                    t["manner"] = "cautious"
    res2 = replay_tasks(w2, f0, u0, (header, bad))
    assert not res2.ok and res2.first_mismatch is not None


def test_different_seeds_diverge():
    def run(seed):
        w, f, u = load_testfield()
        s = Sim(w, f, u, seed=seed)
        orders(s)
        s.run(60)
        return s.state_hash()

    assert run(1) == run(1)
    assert run(1) != run(2)


def test_scripted_afternoon_produces_losses_in_the_thousands():
    w, f, u = load_testfield()
    sim = Sim(w, f, u, seed=5)
    orders(sim)
    sim.run(360)
    losses = sim.losses()
    total = sum(losses.values())
    assert 1_000 <= total <= 10_000, losses
    assert min(losses.values()) >= 300, losses
    kinds = {e.kind for e in sim.events}
    assert {"fire", "melee", "rout", "report_received", "sighting"} <= kinds
    assert any(
        x.state in (UnitState.ROUTED, UnitState.DESTROYED) or x.casualties > 0
        for x in sim.forces.units.values()
    )
    assert "Hoher Ruecken" in sim.summary() or "Kapellenberg" in sim.summary()


def test_the_log_header_hash_includes_the_initial_reports(tmp_path):
    """build.build hands out meta `initial_reports` after the Sim exists; hash0 must be the
    state with those reports in hand, so a pack that has them replays."""
    import json
    import shutil

    from test_engine_kit import TESTFIELD

    from kriegsspiel.build import build
    from kriegsspiel.play import play_game
    from kriegsspiel.replay import replay_game

    d = tmp_path / "pack"
    shutil.copytree(TESTFIELD, d, ignore=shutil.ignore_patterns("make.py"))
    (d / "meta.json").write_text(
        json.dumps(
            {
                "start": "13:00",
                "initial_reports": {"blue": "Patrols report the enemy on the ridge."},
            }
        )
    )
    plain = build(TESTFIELD, 1, "stub").state_hash()
    log = tmp_path / "play.jsonl"
    play_game(
        {"blue": "null", "red": "null"},
        mode="stub",
        seed=1,
        log=log,
        speed=None,
        end="13:05",
        scenario=d,
        out=None,
    )
    header = json.loads(log.read_text().splitlines()[0])
    assert header["type"] == "header"
    assert header["hash0"] == build(d, 1, "stub").state_hash() != plain
    rep = replay_game(log)
    assert rep.ok, rep
