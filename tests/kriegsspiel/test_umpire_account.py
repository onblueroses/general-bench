"""The umpire's v2 account (who holds the ground, per-body state and position, flight) on a
small synthetic field, and `umpire rejudge`: the record is appended, the game's verdict and
replay are untouched, and the grid summary shows the rejudged verdict."""

from __future__ import annotations

import json
from pathlib import Path

from kriegsspiel import grid, results
from kriegsspiel.account import Body, Field, Places, render
from kriegsspiel.jev import JevClient
from kriegsspiel.log import jev_calls, read_records
from kriegsspiel.types import Feature, FeatureKind, GeometryKind
from kriegsspiel.umpire import ground_section, rejudge


def _square(cx: float, cy: float, half: float) -> list[tuple[float, float]]:
    return [
        (cx - half, cy - half),
        (cx + half, cy - half),
        (cx + half, cy + half),
        (cx - half, cy + half),
        (cx - half, cy - half),
    ]


# A 3 km x 1 km ridge (an area: split in thirds), a copse on it, two villages north of it and
# a road 200 m beyond them. y grows northward; bearings are compass bearings.
FEATURES = [
    Feature(
        "Long heights",
        FeatureKind.HEIGHT,
        GeometryKind.POLYGON,
        [(0, 0), (3000, 0), (3000, 1000), (0, 1000), (0, 0)],
        ["the heights"],
    ),
    Feature("Copse", FeatureKind.WOOD, GeometryKind.POLYGON, _square(1500, 450, 50)),
    Feature("Westdorf", FeatureKind.VILLAGE, GeometryKind.POLYGON, _square(500, 1500, 100)),
    Feature("Ostdorf", FeatureKind.VILLAGE, GeometryKind.POLYGON, _square(2500, 1500, 100)),
    Feature(
        "High road",
        FeatureKind.ROAD,
        GeometryKind.POLYLINE,
        [(-500, 1800), (1500, 1800), (3500, 1800)],
        ["the road"],
    ),
    Feature("Mill brook", FeatureKind.STREAM, GeometryKind.POLYLINE, [(0, 3000), (3000, 3000)]),
]
OBJECTIVES = (
    "red (General Red): take the heights and the Copse and open the road.\n\n"
    "blue (General Blue): hold the heights and Westdorf."
)


def body(
    id_: str,
    side: str,
    x: float,
    y: float,
    *,
    state: str = "line",
    morale: float = 80,
    disorder: float = 0,
    flee_to=None,
    men: int = 500,
    formation: str = "1st brigade",
):
    return Body(
        id=id_,
        name=id_,
        side=side,
        formation=formation,
        arm="infantry",
        men=men,
        start_men=600,
        x=x,
        y=y,
        state=state,
        morale=morale,
        disorder=disorder,
        flee_to=flee_to,
    )


BODIES = [
    body("R-west", "red", 500, 1500),  # in Westdorf
    body("R-copse", "red", 1500, 700),  # 200 m north of the Copse, centre of the heights
    body("R-road", "red", 1500, 1800),  # on the road between the villages
    body("R-north", "red", 500, 2400),  # 800 m north of Westdorf
    body("B-east", "blue", 2500, 500),  # eastern third of the heights
    body("B-copse", "blue", 1500, 380, morale=30),  # shaken, at the Copse
    body("B-flee", "blue", 2500, 950, state="routed", flee_to=(2500, 1300)),  # running north
    body("B-west", "blue", 300, 300, state="routed"),  # broken, out of reach
    body("B-gone", "blue", 1000, 500, state="destroyed", men=20),
]
FIELD = Field(clock="19:30", minutes=390, bodies=BODIES)


def _account() -> str:
    return render(FIELD, FEATURES, ["red", "blue"], OBJECTIVES, sunset="20:11")


def _line(text: str, start: str) -> str:
    return next(ln.strip() for ln in text.splitlines() if ln.strip().startswith(start))


def test_conditions_from_state_morale_disorder_and_flight():
    by = {b.id: b.condition for b in BODIES}
    assert by == {
        "R-west": "steady",
        "R-copse": "steady",
        "R-road": "steady",
        "R-north": "steady",
        "B-east": "steady",
        "B-copse": "shaken",
        "B-flee": "in flight",
        "B-west": "routed",
        "B-gone": "destroyed",
    }
    assert body("x", "red", 0, 0, disorder=40).condition == "shaken"


def test_side_totals_count_bodies_by_state():
    text = _account()
    assert text.startswith("Time 19:30 (390 minutes after the start). Sunset is at 20:11.")
    blue = _line(text, "blue: ")
    assert blue.startswith("blue: 3,000 men at the start, 980 lost, 1,000 still formed.")
    assert "1 steady (500 men), 1 shaken (500 men), 1 in flight (500 men), 1 routed " in blue
    assert blue.endswith("1 destroyed.")
    red = _line(text, "red: ")
    assert "4 steady (2,000 men), 0 shaken, 0 in flight, 0 routed, 0 destroyed." in red


def test_ground_says_who_holds_each_objective_place():
    ground = ground_section(_account())
    assert "Mill brook" not in ground  # not named by the objectives
    assert _line(ground, "Westdorf (within 500 m)").startswith(
        "Westdorf (within 500 m): held by red; red 1 body (500 men) formed, blue none formed"
    )
    assert ": contested; red 1 body (500 men) formed, blue 1 body (500 men) formed" in _line(
        ground, "Copse"
    )
    assert "Ostdorf" not in [ln.split(" (")[0].strip() for ln in ground.splitlines()]
    west = _line(ground, "Long heights, its western third")
    assert "empty of formed bodies" in west and "(blue 1 broken)" in west
    assert "held by blue" in _line(ground, "Long heights, its eastern third")
    assert "contested" in _line(ground, "Long heights, the centre")
    whole = _line(ground, "Long heights (anywhere on it)")
    assert "contested; red 1 body (500 men) formed, blue 2 bodies (1,000 men) formed" in whole
    # the road in stretches between the villages along it; the destroyed body counts nowhere
    assert "held by red" in _line(ground, "the High road from Westdorf to Ostdorf")
    # R-west, 300 m off the road at Westdorf, stands at the end of both stretches it bounds
    assert "held by red" in _line(ground, "the High road from its west end to Westdorf")
    assert "empty of formed bodies" in _line(ground, "the High road from Ostdorf to its east")


def test_bodies_are_placed_by_bearing_and_distance_with_state():
    text = _account()
    assert _line(text, "R-north").endswith("steady, line; 800 m north of Westdorf.")
    assert _line(text, "R-west").endswith("steady, line; in Westdorf.")
    assert "on the High road" in _line(text, "R-road")
    assert "shaken, line; on Long heights (centre), in Copse." in _line(text, "B-copse")
    assert _line(text, "B-flee").endswith(
        "in flight north, toward Ostdorf; on Long heights (east), 450 m south of Ostdorf."
    )
    assert "routed, out of reach of the enemy, not yet rallied" in _line(text, "B-west")
    assert _line(text, "B-gone").endswith("(infantry, 20 of 600): destroyed.")
    assert _line(text, "1st brigade").strip() == ("1st brigade: 2,000 men; 4 steady.")


def test_places_word_bearings_from_the_place():
    p = Places(FEATURES)
    assert p.relative((2500, 1000)) == "400 m south of Ostdorf"
    assert p.relative((3200, 1500)) == "600 m east of Ostdorf"
    assert p.toward((2500, 1000), (2800, 700)) == "south-east"  # nothing named that way


def _log(tmp_path: Path) -> Path:
    recs = [
        {
            "type": "header",
            "seed": 1,
            "scenario": "tests/kriegsspiel/fixtures/packs/kolin",
            "jev_model": "typesafe/jev-1.14",
            "play": {"players": {"prussia": "opus", "austria": "script"}},
        },
        {"type": "tick", "tick": 0, "hash": "h", "jev": [{"key": "k1", "cost": 0.001}]},
        {
            "type": "verdict",
            "tick": 390,
            "summary": "austria: 54,512 men at the start, 9 lost",
            "jev": [{"key": "k2", "cost": 0.001}],
            "verdict": {
                "winner": "austria",
                "attacker_achieved": False,
                "decisiveness": 0.3,
                "rationale": "winner austria (p=0.57); attacker achieved p=0.28; x",
            },
        },
    ]
    d = tmp_path / "opus-prussia-s1"
    d.mkdir()
    log = d / "run.jsonl"
    log.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in recs))
    return log


KOLIN_FIELD = {
    "clock": "19:30",
    "minutes": 390,
    "state_hash": "abc",
    "bodies": [
        {
            "id": "P1",
            "name": "I./Schultze",
            "side": "prussia",
            "formation": "Hülsen's corps",
            "arm": "infantry",
            "men": 500,
            "start_men": 560,
            "x": 8083.0,
            "y": 3374.0,
            "state": "line",
            "morale": 70.0,
            "disorder": 0.0,
            "flee_to": None,
            "engaged": False,
        },
        {
            "id": "A1",
            "name": "Los Rios",
            "side": "austria",
            "formation": "Angern's brigade",
            "arm": "infantry",
            "men": 300,
            "start_men": 600,
            "x": 7000.0,
            "y": 2000.0,
            "state": "routed",
            "morale": 10.0,
            "disorder": 80.0,
            "flee_to": [7000.0, 1700.0],
            "engaged": False,
        },
    ],
}


def test_rejudge_appends_a_record_and_leaves_the_game_alone(tmp_path):
    log = _log(tmp_path)
    before = log.read_text()
    rec = rejudge(log, client=JevClient(mode="stub"), field=KOLIN_FIELD)
    after = log.read_text()
    assert after.startswith(before)  # appended, never rewritten
    last = read_records(log)[-1]
    assert last["type"] == "rejudge" and last["umpire_version"] == 3 and last == rec
    assert set(last["verdict"]) == {
        "winner",
        "attacker_achieved",
        "decisiveness",
        "rationale",
        "achieved",
    }
    assert last["jev"] and "Křečhoř (within 500 m): held by prussia" in last["account"]
    assert "prussia: 560 men at the start, 60 lost" in last["account"]
    # the game's Jev calls are unchanged for replay; the rejudge's are not among them
    assert [c["key"] for c in jev_calls(read_records(log))] == ["k1", "k2"]
    # the game's verdict record is still there, and the grid still sees the game as done
    assert sum(r["type"] == "verdict" for r in read_records(log)) == 1
    assert results.last_record(log)["type"] == "verdict"


def test_rejudge_dry_run_only_renders(tmp_path):
    log = _log(tmp_path)
    before = log.read_text()
    rec = rejudge(log, client=JevClient(mode="stub"), field=KOLIN_FIELD, judge=False)
    assert "verdict" not in rec and rec["account"] and log.read_text() == before


def test_grid_summary_prefers_the_latest_rejudge(tmp_path):
    log = _log(tmp_path)
    row = results.game_row(log.parent)
    assert row["winner"] == "austria" and row["judged"] == "game"
    for winner, p in (("undecided", "0.40"), ("prussia", "0.71")):
        with log.open("a") as fh:
            fh.write(
                json.dumps(
                    {
                        "type": "rejudge",
                        "umpire_version": 2,
                        "tick": 390,
                        "account": (
                            "prussia: 32,000 men at the start, 8,020 lost, 23,080 still formed."
                        ),
                        "jev": [{"key": "r", "cost": 0.5}],
                        "verdict": {
                            "winner": winner,
                            "attacker_achieved": True,
                            "decisiveness": 0.6,
                            "rationale": f"winner {winner} (p=0.6); attacker achieved p={p}; "
                            "decisiveness level 1.8",
                        },
                    }
                )
                + "\n"
            )
    row = results.game_row(log.parent)
    assert row["winner"] == "prussia" and row["attacker_p"] == 0.71
    assert row["judged"] == "rejudge v2" and row["lost_prussia"] == 8020
    assert row["jev_cost"] == 0.002  # the game's Jev spend only
    assert results.last_record(log)["type"] == "verdict"
    (tmp_path / "manifest.json").write_text(
        json.dumps({"config": {"sides": ["prussia", "austria"]}, "cells": []})
    )
    text = grid.summary(tmp_path)
    assert "verdict from" in text and "| prussia | 0.71 | 0.6 | rejudge v2 | 8,020 |" in text
