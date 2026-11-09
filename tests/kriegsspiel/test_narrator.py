"""The narrator renders the commander's picture, never the truth."""

from __future__ import annotations

import copy

import pytest
from test_engine_kit import KOLIN

from kriegsspiel.build import build
from kriegsspiel.command import Contact, Picture
from kriegsspiel.scenario import load
from kriegsspiel.types import Message, MessageKind


@pytest.fixture(scope="module")
def kolin():
    world, formations, units, objectives, meta = load(KOLIN)
    return world, formations, units, objectives, meta


def _narrator(kolin):
    from kriegsspiel.narrator import Narrator

    world, formations, units, objectives, meta = kolin
    return Narrator(world, meta, objectives, copy.deepcopy(formations), copy.deepcopy(units))


def _report(
    i: int, at: float, text: str, brigade: str = "P-HUL", why=("situation report",), sightings=()
):
    return Message(
        id=f"prussia-report-{i:05d}",
        side="prussia",
        kind=MessageKind.REPORT,
        sender=brigade,
        recipient="P",
        text=text,
        sent_at=at - 5,
        received_at=at,
        data={
            "brigade": brigade,
            "position": [9000.0, 4200.0],
            "men": 4100,
            "start_men": 4480,
            "why": list(why),
            "sightings": list(sightings),
        },
    )


def _sight(key: str, x: float, y: float, dist: float, arm="infantry", men=600, routed=False):
    return {
        "key": key,
        "x": x,
        "y": y,
        "ident": 1,
        "arm": arm,
        "est_men": men,
        "seen_at": 0,
        "dist": dist,
        "state": None,
        "routed": routed,
    }


def test_brief_shows_only_the_picture(kolin):
    _world, formations, _units, objectives, _meta = kolin
    nar = _narrator(kolin)
    contact = Contact(
        key="A-NAD-1",
        name="the enemy cavalry near Kutlíře",
        arm="cavalry",
        est_men=1200,
        x=9500.0,
        y=3600.0,
        seen_at=20,
        learned_at=24,
        source="P-ZIE",
    )
    pic = Picture(
        side="prussia",
        now=30,
        clock="13:30",
        hq=(6641.0, 4961.0),
        reports=[
            _report(
                1,
                24.0,
                "13:19, Hülsen (Hülsen's corps) at Kaiserstrasse: "
                "we are engaged. Strength 4,100 of 4,480.",
            )
        ],
        contacts=[contact],
        own={"P-HUL": {"position": [9000.0, 4200.0], "men": 4100, "as_of": 19.0}},
    )
    text = nar.brief(pic, "prussia", since=0)
    # the persona once, at the top: how the game works, the player's situation (players.md;
    # never the umpire's objectives), own order of battle
    assert text.startswith("You are Frederick II")
    assert objectives.for_player("prussia") in text
    assert objectives.for_side("prussia") not in text
    assert "Zieten's hussars (Generalmajor von Katte)" in text
    assert "You may ask nothing of the umpire" in text
    # the known enemy body, the report verbatim with its clock, the reported position
    assert "the enemy cavalry near Kutlíře: one body, cavalry, about 1,200 men" in text
    assert "received 13:24] 13:19, Hülsen (Hülsen's corps)" in text
    assert "4,100 men" in text and "reported 13:19" in text
    # no truth: Austrian formations and commanders the hq has not seen (and the Prussian
    # objectives do not name) are absent; no other contact is invented
    austrian = [f for f in formations if f.side == "austria"]
    for f in austrian:
        for word in (f.name, f.commander):
            if word in objectives.for_player("prussia") or len(word) < 6:
                continue
            assert word not in text, word
    assert text[len(nar.persona("prussia")) :].count("the enemy ") == 1  # past the persona
    assert "Saxon" not in text and "Nostitz" not in text
    # a brigade with no report yet stands where it stood at 13:00
    assert "no report yet; as at 13:00" in text
    # later briefs leave the persona out and show only the new dispatches as new
    again = nar.brief(pic, "prussia", since=30)
    assert not again.startswith("You are") and objectives.for_player("prussia") not in again
    assert "New dispatches since your last brief:\nNone." in again


def test_brief_never_reads_the_live_state(kolin):
    sim = build(KOLIN, 1, "stub")
    nar = sim.narrator
    hidden = next(
        u for u in sim.forces.units.values() if u.side == "austria" and u.parent == "A-WOL"
    )
    hidden.x, hidden.y = 6700.0, 5000.0  # in truth next to the Prussian hq, never reported
    mine = next(u for u in sim.forces.units.values() if u.parent == "P-SCH")
    mine.x, mine.y = 12000.0, 2000.0  # a Prussian body far away in truth, no report
    pic = sim.picture("prussia")
    pic.contacts = [c for c in pic.contacts if c.key != hidden.id]
    text = nar.brief(pic, "prussia", since=0)
    assert hidden.name not in text and "Wöllwarth" not in text
    line = next(x for x in text.splitlines() if x.startswith("- Schönaich's brigade"))
    assert "as at 13:00" in line and "Kaiserstrasse" in line


def test_brief_stays_under_the_word_budget_and_summarises_old_reports(kolin):
    nar = _narrator(kolin)
    filler = (
        "13:00, Hülsen (Hülsen's corps) at Kaiserstrasse: situation report. Enemy seen: "
        + "; ".join(["troops at Křečhoř heights"] * 6)
        + ". Strength 4,480 of 4,480."
    )
    near = [_sight("A-1", 9300.0, 4200.0, 300.0)]
    reps = [
        _report(
            i,
            float(i),
            filler,
            why=("first contact with the enemy",) if i == 1 else ("situation report",),
            sightings=near if i == 1 else (),
        )
        for i in range(1, 300)
    ]
    pic = Picture(side="prussia", now=300, clock="18:00", hq=(6641.0, 4961.0), reports=reps)
    text = nar.brief(pic, "prussia", since=290)
    assert len(text.split()) <= 6000
    assert "Older dispatches, in brief:" in text
    assert "Hülsen's corps: " in text and "first contact with the enemy" in text


def test_first_contact_means_within_reach_and_sightings_are_grouped(kolin):
    world = kolin[0]
    nar = _narrator(kolin)
    heights = world.feature("Křečhoř heights")
    hx, hy = world.anchor(heights, (9000.0, 4200.0))
    far = [_sight(f"A-{k}", hx + 20.0 * k, hy, 3000.0, men=700, routed=k == 0) for k in range(6)]
    first = _report(1, 7.0, "x", why=("first contact with the enemy",), sightings=far)
    later = _report(
        2,
        40.0,
        "x",
        why=("situation report",),
        sightings=[_sight("A-9", 9400.0, 4200.0, 450.0, arm="cavalry", men=300)],
    )
    pic = Picture(
        side="prussia", now=45, clock="13:45", hq=(6641.0, 4961.0), reports=[first, later]
    )
    text = nar.brief(pic, "prussia", since=0)
    line1 = next(x for x in text.splitlines() if "received 13:07]" in x)
    # 3 km off is not contact; six bodies on the heights are one line, not six
    assert "enemy in sight" in line1 and "first contact" not in line1
    assert (
        "about 6 bodies of infantry, some 4,200 men, near Křečhoř heights (1 in flight)" in (line1)
        or "about 6 bodies of infantry, some 4,200 men, at Křečhoř heights (1 in flight)" in line1
    )
    line2 = next(x for x in text.splitlines() if "received 13:40]" in x)
    assert "first contact with the enemy" in line2  # the first body within 600 m
    assert "about 300 cavalry" in line2
    # and a third report with a body near again is no second first contact
    again = _report(
        3,
        44.0,
        "x",
        why=("situation report",),
        sightings=[_sight("A-9", 9400.0, 4200.0, 300.0, arm="cavalry")],
    )
    from kriegsspiel.narrator import report_whys

    whys = report_whys([first, later, again])
    assert whys[again.id] == ["situation report"]


def test_prior_orders_drop_the_bot_tag():
    """A general taking over from a doctrine bot at a decision point reads the bot's orders as
    their own: the log tag "[bot:strong] " never reaches the brief."""
    from kriegsspiel.narrator import BOT_TAG

    assert BOT_TAG.sub("", "[bot:strong] R-02: holds the ridge", count=1) == "R-02: holds the ridge"
    assert BOT_TAG.sub("", "[bot] R-02: holds the ridge", count=1) == "R-02: holds the ridge"
    assert BOT_TAG.sub("", "Hülsen, [bot:strong] hold", count=1) == "Hülsen, [bot:strong] hold"


def test_own_troops_show_the_reported_strength_against_the_start(kolin):
    nar = _narrator(kolin)
    pic = Picture(
        side="prussia",
        now=30,
        clock="13:30",
        hq=(6641.0, 4961.0),
        own={
            "P-HUL": {
                "position": [9000.0, 4200.0],
                "men": 4100,
                "strength_start": 4480,
                "as_of": 19.0,
            }
        },
    )
    line = next(
        x for x in nar.own_prose(pic, "prussia", "13:00").splitlines() if x.startswith("- Hülsen")
    )
    assert "4,100 of 4,480 men" in line
    # a picture without the start figure keeps the plain count
    pic.own["P-HUL"].pop("strength_start")
    line = next(
        x for x in nar.own_prose(pic, "prussia", "13:00").splitlines() if x.startswith("- Hülsen")
    )
    assert "4,100 men" in line and "of 4,480" not in line


def test_an_order_to_the_army_shows_on_a_brigade_only_with_a_task_for_it(kolin):
    """The headquarters' move in an order to the army is not each brigade's last order; an
    army order that sets the brigades a task is."""
    from kriegsspiel.types import Ref, RefKind, Task, TaskKind

    nar = _narrator(kolin)

    def hulsen(orders):
        pic = Picture(side="prussia", now=30, clock="13:30", hq=(6641.0, 4961.0), orders=orders)
        return next(
            x
            for x in nar.own_prose(pic, "prussia", "13:00").splitlines()
            if x.startswith("- Hülsen")
        )

    own = Message(
        "m1",
        "prussia",
        MessageKind.ORDER,
        "army",
        "P-HUL",
        "Hülsen, hold the Krzeczhorz.",
        sent_at=5.0,
        received_at=9.0,
        tasks=[Task(TaskKind.HOLD, "P-HUL")],
    )
    ride = Message(
        "m2",
        "prussia",
        MessageKind.ORDER,
        "army",
        "P",
        "Headquarters will ride to the mill.",
        sent_at=20.0,
        received_at=20.0,
        tasks=[Task(TaskKind.MOVE_HQ, "P", Ref(RefKind.POINT, point=(7000.0, 5000.0)))],
    )
    halt = Message(
        "m3",
        "prussia",
        MessageKind.ORDER,
        "army",
        "P",
        "The whole army will halt.",
        sent_at=25.0,
        received_at=27.0,
        tasks=[Task(TaskKind.HOLD, "P")],
    )
    assert "hold the Krzeczhorz" in hulsen([own, ride])
    assert "The whole army will halt" in hulsen([own, ride, halt])
