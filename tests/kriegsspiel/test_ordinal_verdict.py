"""The ordinal verdict (kriegsspiel.verdict.OrdinalJudge; docs/battles/README.md): break, else
possession of the objective at the end hour, else play on in quarter hours, else draw."""

from __future__ import annotations

import json
import shutil

import pytest
from test_engine_kit import KOLIN, TESTFIELD

from kriegsspiel import verdict
from kriegsspiel.account import Body, Field
from kriegsspiel.build import build
from kriegsspiel.jev import REPO_ROOT
from kriegsspiel.play import make_commander, play, play_game
from kriegsspiel.replay import replay_game
from kriegsspiel.types import Feature, FeatureKind, GeometryKind, UnitState

TOWN = Feature("Town", FeatureKind.VILLAGE, GeometryKind.POINT, [(0.0, 0.0)])
ORD = {
    "verdict": "ordinal",
    "objective": "Town",
    "break_share": 0.4,
    "break_persist_min": 30,
    "play_on_min": 120,
}
# start 09:00, end hour 16:00 (minute 420), play-on to 18:00 (minute 540)
END, LAST = 420, 540


def _b(i, side, x=5000.0, y=0.0, men=1000, start=1000, state="line", arm="infantry", fate=None):
    return Body(
        id=f"{side}{i}",
        name=f"{side}{i}",
        side=side,
        formation=f"{side}-F",
        arm=arm,
        men=men,
        start_men=start,
        x=x,
        y=y,
        state=state,
        morale=80.0,
        disorder=0.0,
        fate=fate,
    )


def _army(side, x=5000.0, broken=0, n=10, **kw):
    """n bodies of 1000; the first `broken` routed."""
    return [_b(k, side, x=x, state="routed" if k < broken else "line", **kw) for k in range(n)]


def _judge(**over):
    return verdict.OrdinalJudge({**ORD, **over}, [TOWN], ["a", "b"], "09:00", "16:00")


def _fld(bodies, minute=0):
    return Field(clock="", minutes=minute, bodies=bodies)


def test_break_needs_the_share_to_persist():
    j = _judge()
    calm = _army("a") + _army("b")
    shaken = _army("a", broken=5) + _army("b")  # 50% of a's men routed
    rallied = _army("a", broken=3) + _army("b")  # 30%: back under the 40% line
    assert not j.observe(_fld(calm), 100)
    for m in range(101, 121):  # broken for 20 minutes, then rallies
        assert not j.observe(_fld(shaken), m)
    assert not j.observe(_fld(rallied), 121)
    for m in range(122, 151):  # broken again: the 30 minutes start over at 122
        assert not j.observe(_fld(shaken), m)
    assert j.observe(_fld(shaken), 152)
    r = j.result
    assert (r["winner"], r["how"], r["minute"]) == ("b", "break", 152)
    assert r["break"]["a"] == {"first_crossed": 101, "crossed": 122}
    assert r["margin"]["a"]["broken_share"] == 0.5 and r["possession"] == []


def test_exactly_the_share_is_not_broken_and_destroyed_or_fled_count():
    j = _judge(break_persist_min=0)
    assert not j.observe(_fld(_army("a", broken=4) + _army("b")), 10)  # 40% is not "more"
    a = _army("a")
    a[0].state = "destroyed"
    a[1].fate = {"fate": "fled", "at": 5}
    a[2].fate = {"fate": "captured", "at": 5}
    a[3].fate = {"fate": "exited", "exit": "Gate", "at": 5, "men": 1000}  # marched off: fine
    a[4].fate = {"fate": "awaiting", "at": 600}  # not yet arrived: not broken
    assert verdict.broken_share(a) == pytest.approx(0.3)
    a[5].state = "routed"
    a[6].state = "routed"
    assert j.observe(_fld(a + _army("b")), 11) and j.result["winner"] == "b"


def test_both_broken_at_one_reading_is_a_draw():
    j = _judge()
    both = _army("a", broken=6) + _army("b", broken=5)
    for m in range(200, 230):
        assert not j.observe(_fld(both), m)
    assert j.observe(_fld(both), 230)
    assert (j.result["winner"], j.result["how"]) == ("draw", "break")


def _both_over(b_broken, **over):
    """a crosses at 200, b at 220; the ruling minute is 230 (a's 30 minutes)."""
    j = _judge(**over)
    a_only = _army("a", broken=6) + _army("b")
    both = _army("a", broken=6) + _army("b", broken=b_broken)
    for m in range(200, 220):
        j.observe(_fld(a_only), m)
    for m in range(220, 230):
        assert not j.observe(_fld(both), m)
    assert j.observe(_fld(both), 230)  # a's 30 minutes are up; b is over the share too
    assert j.result["break"]["b"]["crossed"] == 220
    return j.result


def test_both_over_the_share_alike_at_the_ruling_minute_is_a_draw():
    """The winner by a break must itself be under the share at that minute. Without that, a
    Plain pilot game went to an army 88% broken because the other had crossed two minutes
    earlier."""
    r = _both_over(6)
    assert (r["winner"], r["how"]) == ("draw", "break")


def test_both_over_the_less_broken_army_wins_beyond_the_tie_margin():
    """60% against 80% broken is a win for the 60%; 60% against 70% is
    within the margin of a tenth (about a brigade of foot) and stays a draw; the margin is a
    pack parameter."""
    r = _both_over(8)
    assert (r["winner"], r["how"]) == ("a", "break")
    assert r["params"]["break_tie_margin"] == pytest.approx(0.1)
    r = _both_over(7)
    assert (r["winner"], r["how"]) == ("draw", "break")
    r = _both_over(7, break_tie_margin=0.05)
    assert (r["winner"], r["how"]) == ("a", "break")
    j = _judge()
    a_only = _army("a", broken=9) + _army("b")
    both = _army("a", broken=9) + _army("b", broken=5)
    for m in range(200, 220):
        j.observe(_fld(a_only), m)
    for m in range(220, 230):
        j.observe(_fld(both), m)
    assert (
        j.observe(_fld(both), 230) and j.result["winner"] == "b"
    )  # the later crosser, less broken


def test_one_side_broken_while_the_other_rallied_under_the_share():
    j = _judge()
    a_only = _army("a", broken=6) + _army("b")
    both = _army("a", broken=6) + _army("b", broken=6)
    for m in range(200, 220):
        j.observe(_fld(a_only), m)
    for m in range(220, 229):
        assert not j.observe(_fld(both), m)
    assert j.observe(_fld(a_only), 230)  # b rallied under 40% in time: b wins by a's break
    assert (j.result["winner"], j.result["how"]) == ("b", "break")


def test_last_reading_an_army_over_the_share_loses():
    """At the last reading an army over the share loses to one that is not,
    persisted or not (the Mirror pilot game drawn at 47% broken)."""
    j = _judge()
    level = _fld([_b(0, "a", x=100.0), _b(0, "b", x=-100.0)])  # contested, nobody broken
    for m in range(END, LAST - 1):
        assert not j.observe(level, m)
    b_over = _fld([_b(0, "a", x=100.0), _b(0, "b", x=-100.0), *_army("b", broken=5, n=9, x=9000.0)])
    assert not j.observe(b_over, LAST - 1)  # over the share for one minute only: no break
    assert j.observe(b_over, LAST)
    assert (j.result["winner"], j.result["how"], j.result["clock"]) == (
        "a",
        "last-reading",
        "18:00",
    )
    assert j.result["possession"][-1]["state"] == "contested"


def test_last_reading_both_over_the_share_is_a_draw():
    j = _judge()
    level = _fld([_b(0, "a", x=100.0), _b(0, "b", x=-100.0)])
    for m in range(END, LAST):
        assert not j.observe(level, m)
    both = _fld(
        [
            _b(0, "a", x=100.0),
            _b(0, "b", x=-100.0),
            *_army("a", broken=5, n=9, x=9000.0),
            *_army("b", broken=5, n=9, x=-9000.0),
        ]
    )
    assert j.observe(both, LAST)
    assert (j.result["winner"], j.result["how"]) == ("draw", "draw")


def test_readings_carry_the_formed_strength_within_musket_range():
    j = _judge()
    fld = _fld(
        [
            _b(0, "a", x=100.0, men=700),
            _b(1, "a", x=120.0, men=300, arm="cavalry"),
            _b(0, "b", x=-100.0, men=500),
            _b(1, "b", x=5000.0, men=900),
        ]
    )
    assert not j.observe(fld, END)
    assert j.readings[-1]["near"] == {
        "a": {"foot_guns": 700, "horse": 300},
        "b": {"foot_guns": 500, "horse": 0},
    }


def test_play_on_notice_reads_the_last_reading():
    j = _judge()
    assert verdict.play_on_notice(j) == ""
    j.observe(_fld([_b(0, "a", x=100.0), _b(0, "b", x=-100.0)]), END)
    n = verdict.play_on_notice(j)
    assert n.startswith(
        "The umpire's reading at 16:00: both armies had formed troops within "
        "musket range of Town: contested."
    )
    assert "the last at 18:00" in n
    j.observe(_fld([_b(0, "a", x=3000.0), _b(0, "b", x=-3000.0)]), END + 15)
    assert "at 16:15: neither army" in verdict.play_on_notice(j)
    j.observe(_fld([_b(0, "a", x=100.0), _b(0, "b", x=-3000.0)]), END + 30)
    assert j.result["winner"] == "a" and verdict.play_on_notice(j) == ""


def test_possession_foot_over_cavalry():
    fld = _fld(
        [
            _b(0, "a", x=200.0, arm="infantry"),
            _b(0, "b", x=100.0, arm="cavalry"),
            *_army("a", n=3),
            *_army("b", n=3),
        ]
    )
    assert verdict.possession(fld, TOWN, ["a", "b"]) == "a"
    guns = _fld([_b(0, "a", x=100.0, arm="cavalry"), _b(0, "b", x=240.0, arm="artillery")])
    assert verdict.possession(guns, TOWN, ["a", "b"]) == "b"
    j = _judge()
    assert j.observe(fld, END)
    assert (j.result["winner"], j.result["how"], j.result["clock"]) == ("a", "possession", "16:00")


def test_cavalry_holds_an_empty_village_and_against_cavalry_only():
    alone = _fld([_b(0, "b", x=150.0, arm="cavalry"), _b(1, "a", x=600.0)])
    assert verdict.possession(alone, TOWN, ["a", "b"]) == "b"  # a's foot is 600 m off
    horse = _fld([_b(0, "a", x=150.0, arm="cavalry"), _b(0, "b", x=-150.0, arm="cavalry")])
    assert verdict.possession(horse, TOWN, ["a", "b"]) == "contested"
    routed = _fld([_b(0, "a", x=10.0, state="routed"), _b(0, "b", x=150.0, arm="cavalry")])
    assert verdict.possession(routed, TOWN, ["a", "b"]) == "b"  # routed foot holds nothing
    out = _fld([_b(0, "a", x=260.0), _b(0, "b", x=-260.0)])  # beyond musket range (250 m)
    assert verdict.possession(out, TOWN, ["a", "b"]) == "empty"


def test_contested_at_the_end_hour_then_clear_in_the_play_on():
    j = _judge()
    contested = _fld([_b(0, "a", x=100.0), _b(0, "b", x=-100.0)])
    a_holds = _fld([_b(0, "a", x=100.0), _b(0, "b", x=-100.0, state="routed")])
    assert not j.observe(contested, END - 1)
    assert not j.observe(contested, END)
    for m in range(END + 1, END + 30):  # readings only at quarter hours
        assert not j.observe(a_holds if m == END + 7 else contested, m)
    assert j.observe(a_holds, END + 30)
    r = j.result
    assert (r["winner"], r["how"], r["clock"]) == ("a", "play-on", "16:30")
    assert [(x["clock"], x["state"]) for x in r["possession"]] == [
        ("16:00", "contested"),
        ("16:15", "contested"),
        ("16:30", "a"),
    ]


def test_draw_after_the_play_on_bound():
    j = _judge()
    empty = _fld([_b(0, "a", x=3000.0), _b(0, "b", x=-3000.0)])
    for m in range(END, LAST):
        assert not j.observe(empty, m)
    assert j.observe(empty, LAST)
    r = j.result
    assert (r["winner"], r["how"], r["clock"]) == ("draw", "draw", "18:00")
    assert len(r["possession"]) == 9 and {x["state"] for x in r["possession"]} == {"empty"}


def test_break_beats_possession_at_the_same_reading():
    j = _judge(break_persist_min=0)
    fld = _fld([_b(0, "a", x=100.0), *_army("a", broken=5, x=9000.0), _b(0, "b", x=8000.0)])
    assert j.observe(fld, END)
    assert (j.result["winner"], j.result["how"]) == ("b", "break")


def test_validate_ordinal():
    assert verdict.validate(ORD, [TOWN]) == []
    errs = verdict.validate({**ORD, "objective": "town", "play_on_min": 100}, [TOWN])
    assert any("not a feature" in e for e in errs) and any("multiple" in e for e in errs)
    assert verdict.validate({"objective": "Town"}, [TOWN]) == ["verdict None, not 'ordinal'"]


# ---------------------------------------------------------------------------
# In game: the judge ends the battle in place of the umpire's question


def _pack(tmp_path, end="13:30", play_on=30, hold=True):
    d = tmp_path / "pack"
    shutil.copytree(TESTFIELD, d, ignore=shutil.ignore_patterns("make.py"))
    (d / "meta.json").write_text(json.dumps({"start": "13:00", "end": end}))
    (d / "mission.json").write_text(
        json.dumps({"verdict": "ordinal", "objective": "Neudorf church", "play_on_min": play_on})
    )
    if hold:  # one blue grenadier battalion by the church: blue holds Neudorf at the end hour
        dep = json.loads((d / "deployment.json").read_text())
        dep["units"]["B-inf2-4"].update({"x": 2400.0, "y": 950.0})
        (d / "deployment.json").write_text(json.dumps(dep))
    return d


def test_ordinal_game_ends_on_possession_and_replays(tmp_path):
    d = _pack(tmp_path)
    log = tmp_path / "run.jsonl"
    res = play_game(
        {"blue": "null", "red": "null"},
        mode="stub",
        seed=1,
        log=log,
        speed=None,
        scenario=d,
        out=None,
    )
    assert res.sim.over and res.sim.now == 30
    v = res.verdict.to_json()
    assert (v["winner"], v["how"], v["minute"], v["winner_source"]) == (
        "blue",
        "possession",
        30,
        "ordinal",
    )
    assert set(v["margin"]) == {"blue", "red"} and "umpire" in v
    recs = [json.loads(x) for x in log.read_text().splitlines()]
    assert not any(c.get("call") == "battle_over" for r in recs for c in r.get("umpire", []))
    last = recs[-1]
    assert last["type"] == "verdict" and last["verdict"]["winner"] == "blue"
    from kriegsspiel.grid import last_record, verdict_summary

    assert verdict_summary(last_record(log))["winner"] == "blue"  # what grid reads
    rep = replay_game(log)
    assert rep.ok, rep.reason
    assert (rep.verdict.ordinal["winner"], rep.verdict.ordinal["how"]) == ("blue", "possession")


def test_ordinal_game_plays_on_to_a_draw(tmp_path):
    d = _pack(tmp_path, hold=False)
    res = play_game(
        {"blue": "null", "red": "null"},
        mode="stub",
        seed=1,
        log=None,
        speed=None,
        scenario=d,
        out=None,
        end="13:05",
    )  # `end` cannot cut it
    v = res.verdict.to_json()
    assert res.sim.now == 60 and (v["winner"], v["how"]) == ("draw", "draw")
    assert [r["clock"] for r in v["possession"]] == ["13:30", "13:45", "14:00"]


def test_ordinal_game_ends_on_a_break(tmp_path):
    d = _pack(tmp_path, end="15:00", hold=False)
    sim = build(d, 1, "stub")
    assert sim.ordinal is not None
    for uid in ("R-inf1-1", "R-inf1-2", "R-inf1-3", "R-inf1-4", "R-inf2-1", "R-inf2-2"):
        sim.forces.units[uid].state = UnitState.DESTROYED
    nar = sim.narrator
    coms = {s: make_commander("null", s, nar, sim.clock_start) for s in ("blue", "red")}
    res = play(sim, coms, speed=None, out=None)
    v = res.verdict.to_json()
    assert (v["winner"], v["how"], v["minute"]) == ("blue", "break", 31)
    assert v["break"]["red"]["first_crossed"] == 1


def test_a_pack_without_mission_json_keeps_the_umpire_question():
    sim = build(KOLIN, 1, "stub")
    assert sim.ordinal is None


def test_the_brief_carries_the_umpires_notice_first_and_in_updates():
    sim = build(REPO_ROOT / "data" / "plain-crossroads", seed=1, mode="stub", log=None)
    nar = sim.narrator
    first = nar.brief(
        sim.picture("red"), "red", since=0, notice="The umpire's reading at 16:00: x."
    )
    assert "From the umpire\n" in first or "From the umpire" in first
    i, j = first.index("It is 09:00."), first.index("The umpire's reading at 16:00: x.")
    assert i < j < first.index("Your orders?")
    update = nar.brief(
        sim.picture("red"), "red", since=0, update=True, notice="The umpire's reading at 16:15: y."
    )
    assert "The umpire's reading at 16:15: y." in update and "16:00: x" not in update
    plain = nar.brief(sim.picture("red"), "red", since=0, update=True)
    assert "From the umpire" not in plain
