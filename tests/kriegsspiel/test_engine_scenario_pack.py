"""Scenario-owned scripts and generic play (docs/pack-format.md): any data pack plays from its
own script.json, sides from its oob.json, its end and battle-over times from meta.json."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

from kolin_afternoon import KOLIN_ORDERS, kolin_script
from test_engine_kit import KOLIN, TESTFIELD

from kriegsspiel import grid
from kriegsspiel.log import read_records
from kriegsspiel.play import run_script, scenario_script
from kriegsspiel.scenario import load, load_script


def pack(
    tmp_path: Path,
    meta: dict | None = None,
    script: list | dict | None = None,
    objectives: str | None = None,
) -> Path:
    """The test field as a data pack of its own, with optional meta, script and objectives."""
    d = tmp_path / "field-pack"
    shutil.copytree(TESTFIELD, d, ignore=shutil.ignore_patterns("make.py"))
    if meta is not None:
        (d / "meta.json").write_text(json.dumps(meta))
    if script is not None:
        (d / "script.json").write_text(json.dumps(script))
    if objectives is not None:
        (d / "objectives.md").write_text(objectives)
    return d


def test_kolin_script_json_is_the_export_of_kolin_orders():
    orders = load_script(KOLIN)
    assert orders is not None
    assert [(s, t) for _, s, t in orders] == [(s, t) for _, s, t in KOLIN_ORDERS]
    for side in ("prussia", "austria"):
        assert scenario_script(KOLIN, side, "13:00") == kolin_script(side, "13:00")


def test_script_reads_clock_and_minutes_and_a_bare_list(tmp_path):
    d = pack(
        tmp_path,
        meta={"start": "11:00"},
        script=[
            {"at": "11:30", "side": "blue", "text": "Blue 1. Brigade, attack the Hoher Ruecken."},
            {"minute": 5, "side": "red", "text": "Red Cavalry, hold the Eichwald."},
        ],
    )
    assert load_script(d) == [
        (30.0, "blue", "Blue 1. Brigade, attack the Hoher Ruecken."),
        (5.0, "red", "Red Cavalry, hold the Eichwald."),
    ]
    assert scenario_script(d, "red", "11:00") == [(5, "Red Cavalry, hold the Eichwald.")]
    assert scenario_script(pack(tmp_path / "b"), "blue", "13:00") == []  # no script: no orders


def test_meta_end_deadline_and_battle_over_times_load(tmp_path):
    d = pack(
        tmp_path,
        meta={
            "start": "11:00",
            "end": "11:40",
            "deadline": "11:30",
            "battle_over_after": 20,
            "battle_over_every": 10,
        },
        objectives="## Blue: General Blau\nTake the ridge.\n\n## Umpire\nWeigh the ridge.\n",
    )
    _, _, _, obj, meta = load(d)
    assert (meta.end, meta.deadline, meta.battle_over_after, meta.battle_over_every) == (
        "11:40",
        "11:30",
        20,
        10,
    )
    assert meta.minute("11:30") == 30.0 and meta.minute(7) == 7.0
    assert obj.for_side("blue") == "Take the ridge." and obj.umpire == "Weigh the ridge."
    from kriegsspiel.jev import JevClient
    from kriegsspiel.umpire import umpire_for

    ump = umpire_for(obj, meta, ["blue", "red"], JevClient(mode="stub"))
    assert ump.objectives.endswith("For the umpire: Weigh the ridge.")
    assert "Weigh" not in obj.for_side("blue")  # never shown to a general
    _, _, _, _, kolin = load(KOLIN)  # Kolín has none of the new keys: the old behaviour
    assert (kolin.end, kolin.deadline, kolin.battle_over_after) == (None, None, 120)


def test_a_pack_plays_script_against_script_to_its_own_end(tmp_path):
    d = pack(
        tmp_path,
        meta={
            "start": "11:00",
            "end": "11:40",
            "battle_over_after": 20,
            "battle_over_every": 10,
            "sides": {"blue": {"role": "attacker"}},
        },
        script={
            "orders": [
                {
                    "at": "11:00",
                    "side": "blue",
                    "text": "Blue 1. Brigade, attack the Hoher Ruecken.",
                },
                {"at": "11:10", "side": "red", "text": "Red Cavalry, hold the Eichwald."},
            ]
        },
        objectives="## Blue: General Blau\nTake the ridge.\n\n## Red: General Roth\nHold it.\n",
    )
    log = tmp_path / "run.jsonl"
    res = run_script(d, "stub", log, fixture_dir=tmp_path / "jev")
    recs = read_records(log)
    ticks = [r for r in recs if r["type"] == "tick"]
    orders = [(o["side"], o["at"], o["text"]) for r in ticks for o in r["orders"]]
    assert orders == [
        ("blue", 0.0, "Blue 1. Brigade, attack the Hoher Ruecken."),
        ("red", 10.0, "Red Cavalry, hold the Eichwald."),
    ]
    # the stub umpire ends the battle at its first battle-over question (minute 20)
    asked = [r["tick"] for r in ticks for u in r["umpire"] if u["call"] == "battle_over"]
    assert asked == [19] and len(ticks) == 20 and res.sim.over
    assert recs[-1]["type"] == "verdict"
    # umpire v3: the battle-over question and the verdict read the v2 account, and the
    # verdict says per side how much of its own objective it achieved
    over = next(u for r in ticks for u in r["umpire"] if u["call"] == "battle_over")
    assert "blue, body by body:" in over["summary"] and "Ground." in over["summary"]
    assert "blue, body by body:" in recs[-1]["summary"]
    assert set(recs[-1]["verdict"]["achieved"]) == {"blue", "red"}
    assert recs[0]["scenario"].endswith("field-pack")


def test_a_pack_without_an_umpire_ruling_stops_at_its_end(tmp_path):
    d = pack(tmp_path, meta={"start": "11:00", "end": "11:25"})
    log = tmp_path / "run.jsonl"
    run_script(d, "stub", log, fixture_dir=tmp_path / "jev")
    assert sum(r["type"] == "tick" for r in read_records(log)) == 25


def test_grid_takes_the_sides_and_scenario_of_the_pack(tmp_path):
    d = pack(tmp_path)
    sides = grid.scenario_sides(d)
    assert sides == ("blue", "red") and grid.scenario_sides(None) == ("red", "blue")
    cells = grid.make_cells(["script"], ["red"], [1], True, sides=sides)
    assert [c.players for c in cells] == ["blue=script,red=script", "blue=script,red=script"]
    assert [x for x, _ in grid.columns(sides) if x.startswith("lost_")] == ["lost_blue", "lost_red"]


def test_grid_cli_passes_the_scenario_to_every_game(tmp_path, capsys):
    d = pack(tmp_path)
    rc = grid.main(
        [
            "--scenario",
            str(d),
            "--models",
            "script",
            "--seeds",
            "7",
            "--baseline",
            "--out",
            str(tmp_path / "g"),
            "--dry-run",
        ]
    )
    out = capsys.readouterr().out
    assert rc == 0
    lines = [x for x in out.splitlines() if x.strip()]
    assert len(lines) == 3  # script as blue, script as red, the baseline
    assert all(f"--scenario {d}" in x and "blue=script,red=script" in x for x in lines)


def test_initial_reports_are_in_hand_at_the_start(tmp_path):
    from kriegsspiel.build import build

    d = pack(
        tmp_path,
        meta={
            "start": "11:00",
            "initial_reports": {"blue": "11:00. Prisoners say the enemy holds the Eichwald."},
        },
    )
    sim = build(d, 1, "stub")
    sim.step()
    texts = [m.text for m in sim.picture("blue").reports]
    assert texts == ["11:00. Prisoners say the enemy holds the Eichwald."]
    assert not sim.picture("red").reports
