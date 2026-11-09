"""The staff's rules on the words of an order, checked against Jev's reading.

Offline: text matching and the engine-side rules with scripted Jev answers; recorded: orders
against the Prussian side view at 13:00 (fixtures/jev/views/), JEV_MODE=record re-records.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from kriegsspiel.jev import DEFAULT_FIXTURES, Answer, JevClient
from kriegsspiel.staff import JevStaff, split_clauses, view_from_json
from kriegsspiel.staff_text import Lexicon, fold, is_hq_clause, staff_view
from kriegsspiel.types import ConditionKind, Forbid, Manner, RefKind, TaskKind

VIEWS = Path(__file__).parent / "fixtures" / "jev" / "views"
MODE = os.environ.get("JEV_MODE", "replay")


def prussia_1300():
    return view_from_json(json.loads((VIEWS / "kolin_1300_prussia.json").read_text()))


def lex() -> Lexicon:
    return Lexicon(staff_view(prussia_1300()))


# -- 1. diacritic- and case-insensitive matching --------------------------------------------


def test_fold_strips_diacritics_and_case():
    assert fold("Křečhoř") == "krechor"
    assert fold("Nové Město") == "nove mesto"
    assert fold("HÜLSEN’s") == "hulsen's"


def test_names_match_without_diacritics_and_with_one_slip():
    lx = lex()
    assert [m.key for m in lx.formations_in("hulsen, advance")] == ["P-HUL"]
    assert [m.key for m in lx.features_in("to Nove Mesto and KRECHOR")] == [
        "Nové Město",
        "Křečhoř",
    ]
    # one letter dropped in a long name ("Krecor"); short words are matched exactly
    assert [m.key for m in lx.features_in("towards Krecor")] == ["Křečhoř"]
    assert lx.features_in("Velin") == []
    assert lx.subject_at_start("Krosigk's reserve waits at Nove Mesto for orders.") == "P-KRO"


_staff = JevStaff(JevClient(mode=MODE, fixture_dir=DEFAULT_FIXTURES))
_cache: dict[str, object] = {}


def translate(text: str):
    if text not in _cache:
        _cache[text] = _staff.translate(text, prussia_1300())
    return _cache[text]


def test_krosigk_waits_at_nove_mesto():
    r = translate("Krosigk's reserve waits at Nove Mesto for orders.")
    (t,) = r
    assert t.formation == "P-KRO" and t.kind == TaskKind.HOLD
    assert (t.objective.kind, t.objective.name) == (RefKind.FEATURE, "Nové Město")
    assert not r.clarifications


# -- scripted Jev ----------------------------------------------------------------------------


class Scripted(JevClient):
    """Addressing: yes for the formation ids given; details: `details(state, questions)`
    answers what it knows, the rest as the stub would."""

    def __init__(self, yes: set[str], details=None) -> None:
        super().__init__(mode="stub")
        self.yes = yes
        self.details = details
        self.states: list[dict] = []
        self.view = staff_view(prussia_1300())

    def ask(self, state, questions):
        self.states.append(state)
        out = super().ask(state, questions)
        ids = [f.id for f in self.view.formations]
        for k in questions:
            if k.startswith("a") and k[1:].split("_")[0].isdigit():
                fid = ids[int(k[1:].split("_")[0])]
                out[k] = Answer("noul", noul=0.9 if fid in self.yes else 0.1)
            if k.startswith("o"):
                out[k] = Answer("noul", noul=0.1)
        if self.details:
            out.update(self.details(state, questions) or {})
        return out


def pick(choice: str, p: float = 0.9) -> Answer:
    return Answer("choice", choice=choice, probabilities={choice: p})


def opt(questions: dict, q: str, name_part: str) -> str:
    return next(k for k, v in questions[q]["criteria"].items() if name_part in v)


# -- 2. arm words ----------------------------------------------------------------------------


def test_the_cavalry_is_one_addressee_not_every_brigade():
    brigades = {"P-KRK", "P-KRO", "P-NOR", "P-MEI", "P-ZIE"}
    staff = JevStaff(Scripted(brigades))
    r = staff.translate("Cavalry: screen our left flank.", prussia_1300())
    assert [t.formation for t in r] == ["P-CAV"]


def test_the_hussars_and_the_guns_name_their_formation():
    staff = JevStaff(Scripted({"P-ZIE", "P-KRK", "P-NOR"}))
    assert [
        t.formation for t in staff.translate("The hussars screen our left.", prussia_1300())
    ] == ["P-ZIE"]


def test_brigades_named_severally_keep_their_orders():
    staff = JevStaff(Scripted({"P-KRO", "P-NOR"}))
    r = staff.translate("Krosigk and Normann, the cavalry: screen our left flank.", prussia_1300())
    assert sorted(t.formation for t in r) == ["P-KRO", "P-NOR"]


# -- 3. enemy references must be in the picture ----------------------------------------------


def test_an_unseen_enemy_holds_and_asks_whatever_jevs_confidence():
    def details(state, qs):
        if "q0_kind" not in qs:
            return {}
        return {"q0_kind": pick("charge", 0.99), "q0_obj": pick(opt(qs, "q0_obj", "Kutlíře"), 0.99)}

    staff = JevStaff(Scripted({"P-ZIE"}, details))
    r = staff.translate("Zieten's hussars, charge the enemy cavalry at Kutlíře.", prussia_1300())
    (t,) = r
    assert t.kind == TaskKind.HOLD and t.tentative
    assert r.clarifications == [
        "Generalmajor von Katte: I cannot see «the enemy cavalry at Kutlíře»; which body is meant?"
    ]


def test_named_enemy_commanders_count_as_enemy_bodies():
    lx = lex()
    assert lx.unknown_enemy("Fall upon Nádasdy's horse beyond Kutlíře") == (
        "Nádasdy's horse beyond Kutlíře"
    )
    assert lx.unknown_enemy("keep Zieten's hussars on Hülsen's left") is None  # our own
    # a body the side has seen is not questioned
    assert lx.unknown_enemy("bombard the enemy troops on Křečhoř heights") is None


# -- 4. headquarters -------------------------------------------------------------------------


class NoCalls(JevClient):
    def ask(self, state, questions):
        raise AssertionError("no Jev call expected")


def test_headquarters_orders_move_the_army_root_without_jev():
    sv = prussia_1300()
    for text in (
        (
            "The headquarters will ride east along the high road to near Bříství, behind Hülsen's "
            "wheel."
        ),
        "I will move my headquarters to Bříství.",
        "The King rides to Bříství.",
        "Headquarters, ride to Bříství.",
    ):
        r = JevStaff(NoCalls(mode="stub")).translate(text, sv)
        (t,) = r
        assert (t.formation, t.kind) == ("P", TaskKind.MOVE_HQ), text
        assert (t.objective.kind, t.objective.name) == (RefKind.FEATURE, "Bříství"), text
        assert not r.clarifications


def test_a_headquarters_order_goes_where_it_says_not_where_it_must_not_stay():
    # game 3 (runs/kolin-opus-3), 13:27: both clauses were read as "move to Bříství"
    lx = lex()
    text = (
        "The headquarters will ride at once back down to the high road and on to the "
        "Friedrichsberg, and is not to remain at Bříství."
    )
    assert is_hq_clause(text) and lx.hq_destination(text) == "Friedrichsberg"
    assert not is_hq_clause(
        "Hülsen, the order to march to Bříství concerned my headquarters only and not your corps."
    )


def test_army_root_answers_to_headquarters_and_commander():
    root = next(f for f in staff_view(prussia_1300()).formations if f.level == "army")
    assert {"the headquarters", "my headquarters", "the King", "the Feldmarschall"} <= set(
        root.aliases
    )
    assert not is_hq_clause("The King's army will advance on Křečhoř.")


def test_an_order_with_a_headquarters_clause_keeps_its_other_clauses():
    staff = JevStaff(Scripted({"P-HUL"}))
    r = staff.translate(
        "Hülsen, advance to Bříství. The headquarters will follow to Bříství.", prussia_1300()
    )
    by = {t.formation: t for t in r}
    assert set(by) == {"P-HUL", "P"}
    assert by["P-HUL"].source_text == "Hülsen, advance to Bříství."
    assert by["P"].kind == TaskKind.MOVE_HQ


# -- 5. compound orders (recorded) -----------------------------------------------------------


def test_keep_on_his_left_is_support_of_the_named_general():
    r = translate("Katte, keep Zieten's hussars on Hülsen's left as he attacks Křečhoř village.")
    (t,) = r
    assert (t.formation, t.kind) == ("P-ZIE", TaskKind.SUPPORT)
    assert (t.objective.kind, t.objective.name) == (RefKind.FRIENDLY, "P-HUL")
    assert not r.clarifications


def test_march_to_x_and_support_y_is_support_by_way_of_x():
    r = translate(
        "Pannwitz, march your brigade with all speed to Bříství and support Hülsen's corps."
    )
    (t,) = r
    assert (t.formation, t.kind) == ("P-PAN", TaskKind.SUPPORT)
    assert (t.objective.kind, t.objective.name) == (RefKind.FRIENDLY, "P-HUL")
    assert [x.name for x in t.route] == ["Bříství"]
    assert not r.clarifications


def test_take_in_flank_is_a_bold_attack_by_the_way_named():
    r = translate("Hülsen, march past Bříství, wheel right and take Křečhoř in flank.")
    (t,) = r
    assert (t.formation, t.kind) == ("P-HUL", TaskKind.ATTACK)
    assert (t.objective.kind, t.objective.name) == (RefKind.FEATURE, "Křečhoř")
    assert [x.name for x in t.route] == ["Bříství"]
    assert t.manner in (Manner.BOLD, Manner.RECKLESS)


# -- 6. retry with the clause alone ----------------------------------------------------------


def test_an_unclear_kind_is_asked_again_with_the_clause_alone():
    clause = "Normann, the dragoons go forward."

    def details(state, qs):
        if "q0_kind" not in qs:
            return {}
        if state["order"] == clause:
            return {"q0_kind": pick("advance", 0.8), "q0_obj": pick("none", 0.8)}
        return {"q0_kind": pick("advance", 0.4)}

    client = Scripted({"P-NOR"}, details)
    # the addressing gives Normann only the second clause
    real = client.ask

    def ask(state, qs):
        out = real(state, qs)
        for k in qs:
            if k.startswith("a") and k.endswith("_c0"):
                out[k] = Answer("noul", noul=0.1)
        return out

    client.ask = ask  # type: ignore[method-assign]
    r = JevStaff(client).translate("Everything waits for the signal. " + clause, prussia_1300())
    (t,) = r
    assert (t.formation, t.kind) == ("P-NOR", TaskKind.ADVANCE)
    assert not r.clarifications
    assert clause in [s["order"] for s in client.states]


def test_a_kind_unclear_in_a_single_clause_order_is_asked_back_without_a_retry():
    def details(state, qs):
        return {"q0_kind": pick("advance", 0.4)} if "q0_kind" in qs else {}

    client = Scripted({"P-NOR"}, details)
    r = JevStaff(client).translate("Normann, do the needful.", prussia_1300())
    assert r.clarifications and "unclear" in r.clarifications[0]
    assert len(client.states) == 2  # addressing and details, no retry of the same text


# -- 7. an adjutant's reading (staff v2): clauses, mentions, prohibitions, triggers, defaults ---


PENAVAIRE = (
    "Penavaire will bring the cavalry of the left eastward along the high road behind the "
    "infantry, to stand north of Bříství and behind Hülsen. Krockow's cuirassiers lead, and "
    "Krosigk's reserve and Normann's dragoons are to be in support. Be ready to charge any enemy "
    "horse that falls on Hülsen's flank or on the infantry as it climbs the slope, but do not "
    "charge the enemy's line on the heights without my order."
)


def test_clauses_split_where_the_subject_changes_or_a_prohibition_begins():
    assert split_clauses(PENAVAIRE, lex()) == [
        (
            "Penavaire will bring the cavalry of the left eastward along the high road behind the "
            "infantry, to stand north of Bříství and behind Hülsen."
        ),
        "Krockow's cuirassiers lead,",
        "and Krosigk's reserve and Normann's dragoons are to be in support.",
        (
            "Be ready to charge any enemy horse that falls on Hülsen's flank or on the infantry as "
            "it climbs the slope,"
        ),
        "but do not charge the enemy's line on the heights without my order.",
    ]
    # co-subjects joined by "and" are not split, nor is a plain "and" in one instruction
    assert len(split_clauses("Hülsen and Tresckow advance to Bříství and hold it.", lex())) == 1


def _clause_answers(qs, k, **picks):
    """Scripted per-clause reading for clause k: prohib=float, forbid/trig/event/who/where=
    the option whose description contains the text given."""
    out = {}
    for q, v in picks.items():
        name = f"c{k}_{q}"
        if name not in qs:
            continue
        if q == "prohib":
            out[name] = Answer("noul", noul=v)
        else:
            out[name] = pick(opt(qs, name, v) if v not in qs[name]["criteria"] else v)
    return out


def test_a_prohibition_is_a_constraint_not_the_task():
    def details(state, qs):
        out = _clause_answers(qs, 4, prohib=0.9, forbid="formed infantry")
        if "q0_kind" in qs:
            focus.append(qs["q0_kind"]["instructions"])
            out |= {"q0_kind": pick("hold"), "q0_obj": pick(opt(qs, "q0_obj", "Bříství"))}
        for p in ("q1", "q2", "q3"):  # the sub-clauses: "lead", "in support"
            if f"{p}_kind" in qs:
                out |= {f"{p}_kind": pick("support"), f"{p}_obj": pick("none")}
        return out

    focus: list[str] = []
    client = Scripted(set(), details)
    r = JevStaff(client).translate(PENAVAIRE, prussia_1300())
    cav = next(t for t in r if t.formation == "P-CAV")
    # "to stand ... behind Hülsen": support of Hülsen by way of Bříství; the ban is a forbid
    assert cav.kind == TaskKind.SUPPORT and cav.objective.name == "P-HUL"
    assert [x.name for x in cav.route][-1] == "Bříství"
    assert cav.forbid == [Forbid.CHARGE_FORMED_INFANTRY.value]
    # the words the details were asked about leave out the ban and the readiness
    assert "do not charge" not in focus[0] and "ready to charge" not in focus[0]
    # "Krockow's cuirassiers lead": nothing of its own, the cuirassiers keep Penavaire's task;
    # Krosigk and Normann "are to be in support": of the cuirassiers named just before
    by = {t.formation: t for t in r}
    assert "P-KRK" not in by
    for fid in ("P-KRO", "P-NOR"):
        assert by[fid].kind == TaskKind.SUPPORT and by[fid].objective.name == "P-KRK"
        assert Forbid.CHARGE_FORMED_INFANTRY.value in by[fid].forbid  # the superior's ban
    assert not r.clarifications


def test_a_trigger_on_another_formation_starts_the_task_after_a_march_to_its_waypoint():
    text = (
        "Prince Franz will march east along the high road to Zlaté Slunce, there wheel right "
        "and attack the Křečhoř crest, as soon as Hülsen holds Křečhoř."
    )

    def details(state, qs):
        out = _clause_answers(
            qs, 0, trig="start", event="reached", who="Hülsen's corps", where="Křečhoř"
        )
        if "c0_where" in qs:
            out["c0_where"] = pick(
                next(k for k, v in qs["c0_where"]["criteria"].items() if v == "Křečhoř")
            )
        if "q0_kind" in qs:
            out |= {
                "q0_kind": pick("attack"),
                "q0_obj": pick(opt(qs, "q0_obj", "Křečhoř crest")),
                "q0_route": pick(opt(qs, "q0_route", "Zlaté Slunce")),
            }
        return out

    r = JevStaff(Scripted(set(), details)).translate(text, prussia_1300())
    (t,) = r
    assert (t.formation, t.kind, t.objective.name) == ("P-FRA", TaskKind.ADVANCE, "Zlaté Slunce")
    main = t.then
    assert main.kind == TaskKind.ATTACK and main.objective.name == "Křečhoř crest"
    assert main.start.kind == ConditionKind.WHEN_REACHED
    assert (main.start.subject.name, main.start.place.name) == ("P-HUL", "Křečhoř")
    assert not r.clarifications


def test_a_clock_phrase_ends_a_hold():
    text = "Schönaich will hold Bříství until a quarter to seven."

    def details(state, qs):
        out = _clause_answers(qs, 0, trig="until", event="clock")
        if "q0_kind" in qs:
            out |= {"q0_kind": pick("hold"), "q0_obj": pick(opt(qs, "q0_obj", "Bříství"))}
        return out

    (t,) = JevStaff(Scripted(set(), details)).translate(text, prussia_1300())
    assert t.kind == TaskKind.HOLD and t.until.kind == ConditionKind.TIME
    assert t.until.at == 345.0  # 18:45 is minute 345 after 13:00


def test_mentions_are_not_addressees():
    # "your six guns": Hülsen's battalion guns, not the heavy artillery Jev read into them
    staff = JevStaff(Scripted({"P-HUL", "P-ART"}))
    r = staff.translate(
        "Hülsen will attack Křečhoř. Your six guns go forward with the attacking battalions.",
        prussia_1300(),
    )
    assert {t.formation for t in r} == {"P-HUL"}
    # a column named with its brigades at the head: the column's task, not theirs
    staff = JevStaff(Scripted({"P-FRA", "P-PAN"}))
    r = staff.translate(
        "Tresckow will lead the left wing east along the high road, with Prince "
        "Franz and Pannwitz at the head.",
        prussia_1300(),
    )
    assert {t.formation for t in r} == {"P-TRE"}
    # another formation's line inside an order that tells the addressee about it
    staff = JevStaff(Scripted({"P-MAN", "P-KRK", "P-KRO"}))
    r = staff.translate(
        "Manstein will march to Plaňany; Krockow's and Krosigk's horse at Zlaté "
        "Slunce will cover him.",
        prussia_1300(),
    )
    assert {t.formation for t in r} == {"P-MAN"}
    # a subordinate meant by its arm takes the words from its superior
    staff = JevStaff(Scripted({"P-VAN", "P-ZIE"}))
    r = staff.translate("Zieten, ride with the hussars to Kutlíře.", prussia_1300())
    assert {t.formation for t in r} == {"P-ZIE"}


def test_a_place_the_attack_verb_takes_is_the_objective():
    def details(state, qs):
        if "q0_kind" not in qs:
            return {}
        return {
            "q0_kind": pick("attack"),
            "q0_obj": pick(opt(qs, "q0_obj", "the enemy: the enemy troops near")),
        }

    r = JevStaff(Scripted(set(), details)).translate(
        "Hülsen will carry the village of Bříství, driving out the enemy infantry there.",
        prussia_1300(),
    )
    (t,) = r
    assert (t.kind, t.objective.kind, t.objective.name) == (
        TaskKind.ATTACK,
        RefKind.FEATURE,
        "Bříství",
    )
    assert not r.clarifications


def test_closed_up_on_the_brigades_ahead_follows_the_one_in_front():
    sv = prussia_1300()
    ahead = sv.march_order[sv.march_order.index("P-PUT") - 1]

    def details(state, qs):
        return {"q0_kind": pick("advance"), "q0_obj": pick("none")} if "q0_kind" in qs else {}

    r = JevStaff(Scripted(set(), details)).translate(
        "Puttkamer will continue east and keep closed up on the brigades ahead of him.", sv
    )
    (t,) = r
    # the brigade in front of it in its own column (the march order has the cuirassiers
    # between them)
    assert ahead == "P-KRK" and t.kind == TaskKind.SUPPORT and t.objective.name == "P-ING"
    assert not r.clarifications


def test_a_task_that_goes_against_its_words_is_read_again_then_asked_back():
    seen: list[str] = []

    def details(state, qs):
        out = {}
        for k in qs:
            if k[0] in "km" and k[1:].isdigit():
                seen.append(k)
                out[k] = Answer("noul", noul=0.9)  # the check: against the words, twice
        if "q0_kind" in qs or "r0_kind" in qs:
            p = "q0" if "q0_kind" in qs else "r0"
            out |= {f"{p}_kind": pick("attack"), f"{p}_obj": pick(opt(qs, f"{p}_obj", "Křečhoř"))}
        return out

    client = Scripted(set(), details)
    r = JevStaff(client).translate("Hülsen will storm Křečhoř.", prussia_1300())
    (t,) = r
    assert t.kind == TaskKind.HOLD and t.tentative
    assert seen == ["k0", "m0"]
    assert r.clarifications and "Hülsen will storm Křečhoř." in r.clarifications[0]
    assert [c["pass"] for c in r.checks] == [1, 2]
    # the re-read asked Jev with the clause alone as the order
    assert sum(1 for s in client.states if s.get("order") == "Hülsen will storm Křečhoř.") >= 2
