"""Staff translation of Kolín orders, replayed from recorded Jev fixtures (offline).

Re-record: `uv run python -m pytest tests/kriegsspiel -k jev` replays; to record afresh set
JEV_MODE=record (spends a few hundredths of a cent per order). The live test runs only with
OPENROUTER_API_KEY available and JEV_LIVE=1.
"""

from __future__ import annotations

import os

import pytest

from kriegsspiel.jev import DEFAULT_FIXTURES, Answer, JevClient, load_key
from kriegsspiel.staff import JevStaff, split_clauses
from kriegsspiel.types import (
    Arm,
    ConditionKind,
    EnemyView,
    FormationView,
    Manner,
    RefKind,
    SideView,
    TaskKind,
)


def kolin_prussia() -> SideView:
    f = FormationView
    return SideView(
        side="Prussia",
        formations=[
            f(
                "army",
                "the Prussian army",
                "Frederick",
                ["the King's army", "the whole army"],
                "army",
            ),
            f("hulsen", "Hülsen's advance guard", "Hülsen", ["the advance guard"]),
            f("tresckow", "Tresckow's brigade", "Tresckow", ["Tresckow's infantry"]),
            f("manstein", "Manstein's brigade", "Manstein", ["Manstein's grenadiers"]),
            f("bevern", "Bevern's wing", "Bevern", ["the left wing infantry"]),
            f("zieten", "Zieten's hussars", "Zieten", ["the hussars"]),
            f("krosigk", "Krosigk's cuirassiers", "Krosigk", ["the cuirassiers"]),
            f("normann", "Normann's dragoons", "Normann", ["the dragoons"]),
            f("tauentzien", "Tauentzien's brigade", "Tauentzien", []),
            f("artillery", "Frederick's artillery", "", ["the artillery", "the guns"]),
        ],
        feature_names=[
            "Křečhoř",
            "Chocenice",
            "Bříství",
            "Kutlíře",
            "the oak wood",
            "the Kaiserstrasse",
            "the Křečhoř heights",
        ],
        enemies=[
            EnemyView("Austrian line on the heights", Arm.INFANTRY, None, 0.0, 0.0, 0.0, "c1"),
            EnemyView("Croats in Chocenice", Arm.INFANTRY, None, 0.0, 0.0, 0.0, "c2"),
            EnemyView("Austrian cavalry behind Křečhoř", Arm.CAVALRY, None, 0.0, 0.0, 0.0, "c3"),
        ],
    )


ORDERS = {
    "zieten": "Zieten, take the hussars round the oak wood and strike their right; "
    "Hülsen will follow once you are engaged.",
    "hulsen": "Hülsen, advance along the road to Chocenice and clear the Croats out of it, "
    "then wait for Tresckow.",
    "tresckow": "Tresckow, form line south of the road facing the heights and hold until "
    "further orders.",
    "artillery": "The artillery will unlimber on the rise north of Chocenice and bombard the "
    "Austrian line on the heights.",
    "manstein": "Manstein, you are not to engage; keep your grenadiers in column behind Hülsen.",
    "forward": "Everything forward! Bevern and Tresckow storm the heights at Křečhoř, cavalry to "
    "cover the left.",
}


def _staff(mode: str) -> JevStaff:
    return JevStaff(JevClient(mode=mode, fixture_dir=DEFAULT_FIXTURES))


_MODE = os.environ.get("JEV_MODE", "replay")
_cache: dict[str, object] = {}


def translate(name: str):
    if name not in _cache:
        _cache[name] = _staff(_MODE).translate(ORDERS[name], kolin_prussia())
    return _cache[name]


def by_formation(result) -> dict:
    return {t.formation: t for t in result}


def test_split_clauses():
    assert split_clauses(ORDERS["zieten"]) == [
        "Zieten, take the hussars round the oak wood and strike their right;",
        "Hülsen will follow once you are engaged.",
    ]
    assert len(split_clauses(ORDERS["forward"])) == 2


def test_every_order_replays_offline_with_one_check_per_task():
    for name in ORDERS:
        r = translate(name)
        # addressing (with the per-clause reading) and details, then one check per task sent;
        # "forward" addresses the whole army, so the formations read into the same words are
        # asked once more whether they have an order of their own; a failed check re-reads
        own = 1 if name == "forward" else 0
        rereads = 2 * sum(1 for c in r.checks if c["pass"] == 2)
        first = sum(1 for c in r.checks if c["pass"] == 1)
        assert len(r.calls) >= 2 + own + first, name
        assert len(r.calls) <= 2 + own + first + rereads + 2, name
        assert all(c.source in ("fixture", "live") for c in r.calls)
        assert all(t.source_text for t in r), name


# Known misses: what Jev did differently from the ideal reading, recorded honestly. The assertion
# pins the recorded behaviour so a change shows up; the reason says what is wrong with it.
KNOWN_MISSES = {
    ("forward", "army", "kind"): (
        TaskKind.ATTACK,
        (
            "'Everything forward!' reads as ADVANCE; Jev took the army's kind from the storming "
            "clause (both clauses attribute to the army)."
        ),
    ),
}


def test_order1_zieten_round_the_wood_and_hulsen_follows():
    r = translate("zieten")
    t = by_formation(r)
    assert set(t) == {"zieten", "hulsen"}
    z, h = t["zieten"], t["hulsen"]
    # "strike their right" names no known body by name; Jev puts the Austrian line between
    # 0.47 and 0.61 against "other" (recordings and live runs). The recording (army aliases in
    # the state) charges it; a hold-and-ask is the other right answer (test_live_kolin_orders).
    # "their right" is an enemy the side can see, so the unseen-enemy rule does not hold it.
    assert z.kind == TaskKind.CHARGE
    assert (z.objective.kind, z.objective.name) == (RefKind.ENEMY, "Austrian line on the heights")
    assert [x.name for x in z.route] == ["the oak wood"]
    assert z.source_text.startswith("Zieten, take the hussars")
    assert not r.clarifications
    assert h.kind == TaskKind.SUPPORT
    assert (h.objective.kind, h.objective.name) == (RefKind.FRIENDLY, "zieten")
    assert h.start.kind == ConditionKind.WHEN_ENGAGED
    assert (h.start.subject.kind, h.start.subject.name) == (RefKind.FRIENDLY, "zieten")
    assert h.source_text == "Hülsen will follow once you are engaged."


def test_order2_hulsen_clears_chocenice():
    r = translate("hulsen")
    (h,) = r
    assert h.formation == "hulsen"
    assert h.kind == TaskKind.ATTACK
    assert (h.objective.kind, h.objective.name) == (RefKind.ENEMY, "Croats in Chocenice")
    assert [x.name for x in h.route] == ["Chocenice"]
    assert h.start is None and h.until is None
    # "then wait for Tresckow": a HOLD sequel where it stands (waiting is not following)
    assert h.then is not None and h.then.kind == TaskKind.HOLD and h.then.objective is None
    assert not r.clarifications


def test_order3_tresckow_forms_line_and_holds():
    (t,) = translate("tresckow")
    assert t.formation == "tresckow"
    assert t.kind == TaskKind.HOLD
    assert t.objective is None  # "south of the road" is no named place: hold where it stands
    assert t.state is not None and t.state.value == "line"
    assert t.then is None  # "hold until further orders" is one phase


def test_order4_artillery_bombards_the_line():
    (a,) = translate("artillery")
    assert a.formation == "artillery"
    assert a.kind == TaskKind.BOMBARD
    assert (a.objective.kind, a.objective.name) == (RefKind.ENEMY, "Austrian line on the heights")
    assert a.state is not None and a.state.value == "unlimbered"


def test_order5_manstein_follows_in_column_without_engaging():
    (m,) = translate("manstein")
    assert m.formation == "manstein"
    assert m.kind == TaskKind.SUPPORT
    assert (m.objective.kind, m.objective.name) == (RefKind.FRIENDLY, "hulsen")
    assert m.state is not None and m.state.value == "column"
    assert m.on_contact.value == "halt"
    assert m.manner == Manner.CAUTIOUS


def test_order6_everything_forward():
    r = translate("forward")
    t = by_formation(r)
    for f in ("bevern", "tresckow"):
        assert t[f].kind == TaskKind.ATTACK
        assert (t[f].objective.kind, t[f].objective.name) == (
            RefKind.FEATURE,
            "the Křečhoř heights",
        )
        assert t[f].manner in (Manner.BOLD, Manner.RECKLESS)
    assert "tauentzien" not in t and "manstein" not in t and "artillery" not in t
    want, _why = KNOWN_MISSES[("forward", "army", "kind")]
    assert t["army"].kind == want
    # "cavalry to cover the left": every cavalry formation is addressed; "the left" is not in
    # the side's vocabulary, so those that did not tie it to a friendly formation hold and ask.
    cav = {"zieten", "krosigk", "normann"}
    assert cav <= set(t)
    for f in cav:
        assert t[f].kind in (TaskKind.HOLD, TaskKind.SCREEN)
    held = {f for f in cav if t[f].kind == TaskKind.HOLD}
    assert held and len(r.clarifications) == len(held)
    assert all("cannot identify" in c for c in r.clarifications)


def test_unaddressed_order_asks_whom():
    staff = JevStaff(JevClient(mode="stub"))
    staff.client.ask = lambda state, qs: {k: Answer("noul", noul=0.0) for k in qs}  # all "no"
    r = staff.translate("Somebody do something.", kolin_prussia())
    assert list(r) == [] and r.clarifications and staff.clarifications == r.clarifications


def _live_ok() -> bool:
    return os.environ.get("JEV_LIVE") == "1" and load_key() is not None


@pytest.mark.skipif(not _live_ok(), reason="live Jev: set JEV_LIVE=1 with OPENROUTER_API_KEY")
def test_live_kolin_orders():
    """Real calls (about $0.0025): the six orders and the Zieten order, robust assertions only."""
    client = JevClient(mode="live")
    staff = JevStaff(client)
    sv = kolin_prussia()
    results = {n: staff.translate(o, sv) for n, o in ORDERS.items()}
    got = {n: by_formation(r) for n, r in results.items()}
    # "strike their right" names no known body; Jev puts the Austrian line at 0.48 to 0.61
    # against "other" (4 live runs), so either a charge or a hold-and-ask is right.
    if got["zieten"]["zieten"].kind == TaskKind.HOLD:
        assert results["zieten"].clarifications
    else:
        assert got["zieten"]["zieten"].kind == TaskKind.CHARGE
    assert got["zieten"]["hulsen"].start is not None
    assert got["hulsen"]["hulsen"].kind == TaskKind.ATTACK
    assert got["tresckow"]["tresckow"].kind == TaskKind.HOLD
    assert got["artillery"]["artillery"].kind == TaskKind.BOMBARD
    assert got["manstein"]["manstein"].kind == TaskKind.SUPPORT
    assert {"bevern", "tresckow"} <= set(got["forward"])
    assert len(client.calls) == 12 and all(c.source == "live" for c in client.calls)
    assert 0 < client.live_cost < 0.02
