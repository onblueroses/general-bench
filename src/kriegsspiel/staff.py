"""The staff: a commander's free-text order -> list[Task], via Jev (docs/engine.md, "The staff").

Pipeline (two Jev requests per order, sometimes three, both against the same clean state: the
order text and the side's formations by name, commander and alias):

1. Addressing. Per formation, a noul "does this order give <formation> an instruction"; for an
   order of several clauses, also a noul per (formation, clause), which attributes clauses to
   formations so that "Zieten, ...; Hülsen will follow once you are engaged" yields two tasks.
2. Details. Per addressed formation, choices for kind, objective (features, known enemy bodies,
   friendly formations, "no specific objective", "something not on this list"), route waypoint,
   desired state and on_contact; a score for manner; nouls for each start condition with a
   choice for the condition subject.

Between and after the two requests the staff checks Jev's reading against the words of the
order (staff_text.py; diacritic- and case-insensitive): headquarters clauses become MOVE_HQ on
the army root without asking Jev; a clause that opens with a formation's name goes to it; an
arm word goes to one formation; a formation named only as a reference is not addressed; an
enemy body the side cannot see holds the task and asks; and three compound patterns ("keep X on
Y's left", "march to X and support Y", "take Y in flank") are carried. A kind Jev cannot read
from the whole order is asked once more with the formation's clause alone.

The staff assembles Tasks with `source_text`. A low-confidence kind or objective (largest
probability under 0.5), or an objective outside the side's vocabulary, gives a HOLD task and a
clarification for the commander. Jev never counts or computes; all option lists come from the
SideView."""

from __future__ import annotations

import itertools
import json
import re
import unicodedata
from dataclasses import asdict, dataclass, field
from typing import NamedTuple

from .clock import clock
from .jev import Answer, CallRecord, JevClient, choice, noul, score
from .staff_text import (
    ARM_OF_WORD,
    SUPPORT_VERBS,
    Lexicon,
    artillery_named,
    clock_minute,
    fold,
    follow_ahead,
    is_hq_clause,
    own_guns,
    reaction_span,
    staff_view,
    surnames,
    with_offsets,
    words,
)
from .types import (
    Arm,
    Condition,
    ConditionKind,
    EnemyView,
    Forbid,
    FormationView,
    Manner,
    OnContact,
    Ref,
    RefKind,
    SideView,
    Task,
    TaskKind,
    UnitState,
)

CONFIDENT = 0.5
# The check before sending: above this, the task goes against its words. Calibrated on nine
# readings of one full game: fair readings answer 0.07 to 0.48, fair but partial ones (an
# echelon attack read as one attack) 0.57 to 0.68, readings that break a prohibition or a
# trigger 0.74 and 0.94.
CHECK_FAIL = 0.7
# the kinds that fight (or break off a fight): a friendly is never their objective
_CONTACT = (TaskKind.ATTACK, TaskKind.CHARGE, TaskKind.BOMBARD, TaskKind.WITHDRAW)
# "march to X and <verb> Y" with one of these verbs is a SUPPORT of Y by way of X
SUPPORT_WORDS = SUPPORT_VERBS - {"behind", "with", "back"}
# Jev refuses requests above its token limit (HTTP 400 max_tokens_exceeded, as for an order
# addressed to 40 formations); questions are packed into requests of at most this many bytes of
# question JSON, which stays under it.
REQUEST_BUDGET = 80_000

KIND_OPTIONS: dict[str, tuple[TaskKind, str]] = {
    "hold": (TaskKind.HOLD, "hold or stay where it is, keep a position, wait in place"),
    "advance": (
        TaskKind.ADVANCE,
        "advance or march forward towards a place, without being told to attack",
    ),
    "attack": (
        TaskKind.ATTACK,
        "attack, assault, storm or clear the enemy out of a place (infantry)",
    ),
    "charge": (TaskKind.CHARGE, "charge or strike the enemy with cavalry"),
    "withdraw": (TaskKind.WITHDRAW, "withdraw, retreat or fall back"),
    "screen": (
        TaskKind.SCREEN,
        "screen, cover, watch or protect a flank without closing with the enemy",
    ),
    "bombard": (TaskKind.BOMBARD, "bombard or cannonade the enemy with artillery"),
    "support": (TaskKind.SUPPORT, "follow or support another friendly formation, stay behind it"),
    "rally": (TaskKind.RALLY, "rally, reform or restore order"),
    "move_hq": (TaskKind.MOVE_HQ, "move the headquarters or the commander himself"),
}

STATE_OPTIONS: dict[str, tuple[UnitState | None, str]] = {
    "column": (UnitState.COLUMN, "in column (march column, attack column)"),
    "line": (UnitState.LINE, "in line, deployed, formed in line of battle"),
    "square": (UnitState.SQUARE, "in square"),
    "skirmish": (UnitState.SKIRMISH, "in skirmish order, dispersed"),
    "limbered": (UnitState.LIMBERED, "guns limbered for moving"),
    "unlimbered": (UnitState.UNLIMBERED, "guns unlimbered, in battery, ready to fire"),
    "unspecified": (None, "the order does not say what formation to take"),
}

CONTACT_OPTIONS: dict[str, tuple[OnContact, str]] = {
    "halt": (OnContact.HALT, "stop and avoid fighting when meeting the enemy"),
    "engage": (OnContact.ENGAGE, "fight the enemy it meets (the usual case, also when not stated)"),
    "press": (OnContact.PRESS, "press home the attack, push through whatever it meets"),
    "fall_back": (OnContact.FALL_BACK, "fall back when it meets the enemy"),
}

MANNER_LEVELS = [
    "cautious: carefully, avoiding risk, not to engage",
    "measured: an ordinary order with no particular urgency or caution",
    "bold: vigorous, with urgency, attack or strike",
    "reckless: at all costs, everything forward, storm regardless of losses",
]
MANNERS = [Manner.CAUTIOUS, Manner.MEASURED, Manner.BOLD, Manner.RECKLESS]

START_NOULS: dict[str, tuple[ConditionKind | None, str]] = {
    "now": (None, "starts at once, as soon as the order is received"),
    "engaged": (
        ConditionKind.WHEN_ENGAGED,
        "starts only once another formation is engaged with the enemy",
    ),
    "reached": (ConditionKind.WHEN_REACHED, "starts only once a certain place has been reached"),
    "seen": (ConditionKind.WHEN_ENEMY_SEEN, "starts only once the enemy comes into sight"),
    "routs": (ConditionKind.WHEN_ROUTS, "starts only once some body breaks or routs"),
}


FORBID_OPTIONS: dict[str, tuple[Forbid | None, str]] = {
    "none": (None, "nothing in particular is forbidden, or it is not a prohibition"),
    "charge_formed_infantry": (
        Forbid.CHARGE_FORMED_INFANTRY,
        (
            "not to charge the enemy's formed infantry: his line, his battalions, his squares, the "
            "troops on the heights"
        ),
    ),
    "attack": (
        Forbid.ATTACK,
        (
            "not to attack or assault at all, or only on a further order ('attack nothing', 'come "
            "into the attack only on my order')"
        ),
    ),
    "pursue": (Forbid.PURSUE, "not to pursue or follow up a beaten or fleeing enemy"),
    "advance_beyond": (
        Forbid.ADVANCE_BEYOND,
        "not to go beyond or farther than a certain place, not to be drawn off",
    ),
    "engage": (
        Forbid.ENGAGE,
        "not to engage, fight, halt or turn against the enemy, or be drawn into a fight",
    ),
}
TRIGGER_OPTIONS: dict[str, str] = {
    "none": "no event or time is named: it is to be done at once, or it is a standing rule",
    "start": (
        "it is to be done only when or after something happens or a time comes ('as soon as', "
        "'once', 'when', 'after', 'at <time>')"
    ),
    "until": "it is to last only until something happens or a time comes ('until', 'till')",
}
EVENT_OPTIONS: dict[str, str] = {
    "none": "no particular event",
    "reached": "a formation reaches, takes, holds or passes a place",
    "engaged": "a formation is engaged with the enemy or attacks",
    "time": "a clock time comes",
    "seen": "the enemy comes into sight or approaches",
    "routs": "some body breaks, flees or gives way",
    "order": "a further order from the commander arrives",
}
MANNER_WORDS = {
    Manner.CAUTIOUS: "carefully",
    Manner.MEASURED: "",
    Manner.BOLD: "boldly",
    Manner.RECKLESS: "at all costs",
}
VERB_WORDS = {
    TaskKind.HOLD: "hold",
    TaskKind.ADVANCE: "advance on",
    TaskKind.ATTACK: "attack",
    TaskKind.CHARGE: "charge",
    TaskKind.WITHDRAW: "fall back on",
    TaskKind.SCREEN: "screen",
    TaskKind.BOMBARD: "bombard",
    TaskKind.SUPPORT: "follow",
    TaskKind.RALLY: "rally at",
    TaskKind.MOVE_HQ: "move the headquarters to",
}
FORBID_WORDS = {
    Forbid.CHARGE_FORMED_INFANTRY.value: "charging formed infantry",
    Forbid.ATTACK.value: "attacking",
    Forbid.PURSUE.value: "pursuing",
    Forbid.ADVANCE_BEYOND.value: "going beyond",
    Forbid.ENGAGE.value: "engaging",
}


def _ref_words(ref: Ref | None, lex: Lexicon) -> str:
    if ref is None:
        return ""
    if ref.kind == RefKind.FRIENDLY and ref.name:
        f = next((f for f in lex.sv.formations if f.id == ref.name), None)
        if f is None:
            return ref.name
        sn = surnames(f.commander or "")
        if sn and not any(x in fold(f.name) for x in sn):  # "Penavaire's cuirassiers (Krockow)"
            return f"{f.name} ({f.commander})"
        return f.name
    return ref.name or "a point"


def _cond_words(c: Condition | float | None, lex: Lexicon) -> str:
    if c is None:
        return "now"
    if isinstance(c, int | float):
        return f"at minute {c:g}"
    start = lex.sv.clock_start or "13:00"
    who = _ref_words(c.subject, lex)
    if c.kind == ConditionKind.TIME:
        return f"at {clock(start, c.at or 0)}"
    if c.kind == ConditionKind.WHEN_REACHED:
        if c.place is not None:
            return f"once {who} holds {_ref_words(c.place, lex)}"
        if c.subject is not None and c.subject.kind == RefKind.FRIENDLY:
            return f"once {who} has reached its objective"
        return f"once it has reached {who}" if who else "once it has reached its objective"
    if c.kind == ConditionKind.WHEN_ENGAGED:
        return f"once {who or 'it'} is engaged"
    if c.kind == ConditionKind.WHEN_ENEMY_SEEN:
        return f"once {who or 'the enemy'} is in sight"
    return f"once {who or 'some body'} breaks"


def render(t: Task, lex: Lexicon, head: bool = True) -> str:
    """A task in plain words, for the staff's own check ("Krockow's cuirassiers: attack the
    enemy troops near Křečhoř heights, boldly, starting now")."""
    obj = _ref_words(t.objective, lex)
    if not obj:
        obj = (
            "where it stands"
            if t.kind in (TaskKind.HOLD, TaskKind.RALLY)
            else "the enemy in front"
            if t.kind in (TaskKind.ATTACK, TaskKind.CHARGE, TaskKind.BOMBARD)
            else ""
        )
    bits = [f"{VERB_WORDS.get(t.kind, t.kind.value)} {obj}".strip()]
    if t.route:
        bits.append("by way of " + ", ".join(_ref_words(r, lex) for r in t.route))
    if t.state in (UnitState.LINE, UnitState.COLUMN, UnitState.SQUARE):
        bits.append(f"in {t.state.value}")
    elif t.state == UnitState.SKIRMISH:
        bits.append("in skirmish order")
    if MANNER_WORDS.get(t.manner):
        bits.append(MANNER_WORDS[t.manner])
    if t.on_contact == OnContact.HALT:
        bits.append("halting when it meets the enemy")
    elif t.on_contact == OnContact.FALL_BACK:
        bits.append("falling back when it meets the enemy")
    for x in t.forbid:
        base, _, place = x.partition(":")
        what = FORBID_WORDS.get(base, base.lower()) + (f" {place}" if place else "")
        if t.then is not None and x not in t.then.forbid:
            bits.append(f"without {what} on the way")  # a limit that ends with this leg
        else:
            bits.append(f"never {what}")
    if t.start is not None:
        bits.append("starting " + _cond_words(t.start, lex))
    if t.until is not None:
        bits.append("until " + _cond_words(t.until, lex).removeprefix("once "))
    out = ", ".join(bits)
    if head:
        f = next((f for f in lex.sv.formations if f.id == t.formation), None)
        out = f"{f.name if f else t.formation}: {out}"
    if t.then is not None:
        out += "; then " + render(t.then, lex, head=False)
    return out


def _guns_rule(
    addressed: list[FormationView], parts: dict[str, list[int]], clauses: list[str], lex: Lexicon
) -> list[FormationView]:
    """ "Your six guns", "his guns" in a brigade's words are its own battalion guns: the
    artillery formation is addressed only by "the heavy artillery", "the batteries", "the heavy
    guns" or its commander (or the words opening the clause)."""
    for f in list(addressed):
        if lex.arm_of(f) != Arm.ARTILLERY or f.level == "army":
            continue
        keep = [
            k
            for k in parts[f.id]
            if not (
                own_guns(clauses[k])
                and not artillery_named(clauses[k])
                and lex.subject_at_start(clauses[k]) != f.id
            )
        ]
        if keep:
            parts[f.id] = keep
        else:
            addressed = [g for g in addressed if g.id != f.id]
            del parts[f.id]
    return addressed


def _inherit_forbids(tasks: list[Task], lex: Lexicon) -> None:
    """A subordinate's task in its superior's order keeps the superior's prohibitions ("do not
    charge the line" to Penavaire binds Krosigk's reserve, told to follow the cuirassiers)."""
    for t in tasks:
        up = (
            set(lex.ancestors(t.formation))
            if any(f.id == t.formation for f in lex.sv.formations)
            else set()
        )
        extra = [x for u in tasks if u.formation in up for x in u.forbid]
        if not extra:
            continue
        c: Task | None = t
        while c is not None:
            c.forbid = list(dict.fromkeys([*c.forbid, *extra]))
            c = c.then


def view_to_json(sv: SideView) -> dict:
    """A SideView as plain JSON (frozen views for staff tests and measurements)."""
    d = asdict(sv)
    for f in d["formations"]:
        f["arm"] = f["arm"].value if f["arm"] is not None else None
    for e in d["enemies"]:
        e["arm"] = e["arm"].value if e["arm"] is not None else None
    d["places"] = {k: list(v) for k, v in sv.places.items()}
    d["feature_points"] = {k: list(v) for k, v in sv.feature_points.items()}
    d["offsets"] = {k: list(v) for k, v in sv.offsets.items()}
    return d


def view_from_json(d: dict) -> SideView:
    forms = [
        FormationView(**{**f, "arm": Arm(f["arm"]) if f.get("arm") else None})
        for f in d["formations"]
    ]
    enemies = [
        EnemyView(**{**e, "arm": Arm(e["arm"]) if e.get("arm") else None}) for e in d["enemies"]
    ]
    return SideView(
        side=d["side"],
        formations=forms,
        feature_names=list(d["feature_names"]),
        enemies=enemies,
        now=float(d.get("now", 0.0)),
        feature_aliases={k: list(v) for k, v in (d.get("feature_aliases") or {}).items()},
        places={k: (float(v[0]), float(v[1])) for k, v in (d.get("places") or {}).items()},
        march_order=list(d.get("march_order") or []),
        clock_start=str(d.get("clock_start") or ""),
        feature_points={
            k: (float(v[0]), float(v[1])) for k, v in (d.get("feature_points") or {}).items()
        },
        offsets={k: (float(v[0]), float(v[1])) for k, v in (d.get("offsets") or {}).items()},
    )


class TranslateResult(list):
    """A list of Tasks (what the Staff protocol returns) carrying the clarification requests
    for the commander and the Jev calls made."""

    def __init__(
        self,
        tasks: list[Task] = (),
        clarifications: list[str] = (),
        calls: list[CallRecord] = (),
    ) -> None:
        super().__init__(tasks)
        self.clarifications = list(clarifications)
        self.calls = list(calls)
        self.checks: list[dict] = []  # the check before sending, per task (logged with calls)

    @property
    def tasks(self) -> list[Task]:
        return list(self)


@dataclass
class _Option:
    oid: str
    desc: str
    ref: Ref | None  # None for "none"; "other" is handled separately
    short: str = ""  # desc without aliases (for the secondary questions)

    def __post_init__(self) -> None:
        self.short = self.short or self.desc


def _slug(text: str) -> str:
    s = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    s = re.sub(r"[^a-zA-Z0-9]+", "_", s).strip("_").lower()
    return s[:32] or "x"


_JOIN = re.compile(r"(?:,\s*|\s+)but\s+|,\s*(?:and|then|while)\s+", re.IGNORECASE)
NEGATION = re.compile(
    r"^(?:but\s+)?(?:do\s+not|don't|not\b|never|on\s+no\s+account|nobody|no\s+\w+\s+is\s+to)",
    re.IGNORECASE,
)


def split_clauses(text: str, lex: Lexicon | None = None) -> list[str]:
    """Sentences and semicolon clauses, in order; with a lexicon, also the parts of a sentence
    after "but", and after ", and" / ", then" / ", while" where a new subject or a prohibition
    begins ("Krockow's cuirassiers lead, and Krosigk's reserve ... are to be in support")."""
    parts = re.split(r"(?<=[.;!?])\s+", text.strip())
    parts = [p.strip() for p in parts if p.strip()]
    if lex is None:
        return parts
    out: list[str] = []
    for p in parts:
        cuts = []
        for m in _JOIN.finditer(p):
            cut = m.start() + len(m.group()) - len(m.group().lstrip(", \t"))
            rest = p[cut:]
            head = p[cuts[-1] if cuts else 0 : m.start()]
            if len(rest.split()) < 3 or len(head.split()) < 2:
                continue
            conj = m.group().strip(" ,\t").lower()
            after = p[m.end() :]
            if conj == "but" or NEGATION.match(after) or lex.subjects_at_start(after):
                cuts.append(cut)
        bounds = [0, *cuts, len(p)]
        out += [p[a:b].strip() for a, b in itertools.pairwise(bounds) if p[a:b].strip()]
    return out


def formation_label(f: FormationView) -> str:
    label = f.name
    bits = [f.arm.value] if f.arm is not None and f.level != "army" else []
    if f.commander and f.commander.lower() not in f.name.lower():
        bits.append(f"General {f.commander}")
    if bits:
        label += f" ({', '.join(bits)})"
    if f.aliases:
        label += "; also called " + ", ".join(f.aliases)
    return label


@dataclass
class _Reading:
    """What one clause says beside its action: a prohibition, and the event or time it waits
    for or lasts until (Jev's per-clause answers, checked against the words)."""

    prohib: bool = False
    forbid: str | None = None
    trig: str = "none"  # none, start, until
    event: str = "none"
    who: str | None = None  # "self" or a formation id
    where: Ref | None = None
    at: float | None = None  # TIME: sim minute of the clock phrase


@dataclass
class _Plan:
    """One addressed formation: the clauses it is given, the words of its action (prohibitions
    and conditional reactions left out) and all its words."""

    f: FormationView
    ks: list[int]
    act: str
    full: str
    co: set[str]
    inherited: bool = False  # a subordinate's own sub-clause in its superior's order
    prev: str | None = None  # the subject of the clause just before its words
    texts: dict[int, str] = field(default_factory=dict)  # its clauses, by index
    context: str = ""  # the whole sentences its clauses are part of (for the check)
    reacted: bool = False  # a conditional reaction was left out of its action words


@dataclass
class AssemblyContext:
    """What the staff knows of a formation's order beyond its words: the other formations
    the same clauses address (`co`), the subject named just before its words (`prev`), and
    whether this is the last reading (`final`: no re-read is left)."""

    co: set[str] = field(default_factory=set)
    prev: str | None = None
    final: bool = True


class Assembly(NamedTuple):
    """A formation's task as the staff assembled it, the question for the general when it
    could not read the order (`why`), and whether to re-read the clause alone first."""

    task: Task
    why: str | None
    again: bool = False


@dataclass
class _Draft:
    """The task being assembled: what the phases of `JevStaff._assemble` read and refine."""

    kind: TaskKind | None
    objective: Ref | None
    route: list[Ref]
    manner: Manner
    way: Ref | None = None  # the place marched to on the way to an attack


@dataclass
class _Order:
    """An order as the staff reads it: the words, the side's view with the order's offset
    places, the clauses (and which move the headquarters), Jev's state of the whole order, and
    the options the details questions offer."""

    text: str
    sv: SideView
    lex: Lexicon
    clauses: list[str]
    hq: list[int]  # the headquarters clauses
    state: dict
    vocab: list[_Option]
    by_id: dict[str, _Option]
    route_opts: list[_Option]


class JevStaff:
    def __init__(self, client: JevClient) -> None:
        self.client = client
        self.clarifications: list[str] = []
        self._extra: dict[str, Answer] = {}

    # -- public ------------------------------------------------------------

    def translate(self, text: str, side_view: SideView) -> TranslateResult:
        """The tasks of an order, in phases: address the clauses to formations, ask Jev the
        details of each addressed formation's words, assemble the tasks, check them against
        the words and re-read those that fail, then collect them with the questions for the
        general (and the headquarters' move)."""
        n_calls = len(self.client.calls)
        o = self._order(text, side_view)
        addressed, parts, reading, inherited = self._address(o)
        root = next((f for f in o.sv.formations if f.level == "army"), None)
        hq_src = " ".join(o.clauses[k] for k in o.hq)
        clar: list[str] = []
        tasks: list[Task] = []
        checks: list[dict] = []
        if not addressed and not (o.hq and root):
            clar.append(
                f"The order «{text}» names no formation I can identify; to whom is it given?"
            )
        else:
            plans = [
                self._plan(f, parts, o.clauses, text, reading, o.lex, inherited) for f in addressed
            ]
            ans, hq_dest = self._ask_details(o, plans, root, hq_src)
            done: dict[int, tuple[Task, str | None]] = {}
            reread: list[int] = []
            for j, pl in enumerate(plans):
                task, why, again = self._assemble_plan(
                    f"q{j}", pl, ans, o.vocab, o.lex, reading, final=False
                )
                done[j] = (task, why)
                if again:
                    reread.append(j)
            # Check before sending: does each task contradict or exceed its words?
            sound = [j for j in done if j not in reread and not done[j][0].tentative]
            for j, bad in self._checked(plans, done, sound, o.lex, checks, "k", 1):
                if bad:
                    reread.append(j)
            if reread:
                done.update(self._reread(o, plans, reread, reading, checks))
            for j, pl in enumerate(plans):
                task, why = done[j]
                if pl.inherited and (
                    why
                    or not (
                        o.lex.features_in(pl.act)
                        or pl.prev
                        or [m for m in o.lex.formations_in(pl.act) if m.key != pl.f.id]
                    )
                ):
                    # a subordinate's sub-clause with nothing of its own ("Krockow's
                    # cuirassiers lead"), or one the staff cannot read: it keeps its
                    # superior's task, sent in the same order; no question
                    continue
                task.issued_at = side_view.now
                tasks.append(task)
                if why:
                    clar.append(why)
            _inherit_forbids(tasks, o.lex)
            if o.hq and root:
                task, why = self._assemble_hq(root, hq_src, hq_dest, ans, o.by_id, o.lex)
                if task is not None:
                    task.issued_at = side_view.now
                    tasks.append(task)
                if why:
                    clar.append(why)
        self.clarifications.extend(clar)
        res = TranslateResult(tasks, clar, self.client.calls[n_calls:])
        res.checks = checks
        return res

    def _order(self, text: str, side_view: SideView) -> _Order:
        sv = with_offsets(staff_view(side_view), text)
        lex = Lexicon(sv)
        clauses = split_clauses(text, lex)
        vocab = self._vocab(sv)
        return _Order(
            text=text,
            sv=sv,
            lex=lex,
            clauses=clauses,
            hq=[k for k, c in enumerate(clauses) if is_hq_clause(c)],
            state=self._state(text, sv.formations),
            vocab=vocab,
            by_id={o.oid: o for o in vocab},
            route_opts=[
                o for o in vocab if o.ref and o.ref.kind in (RefKind.FEATURE, RefKind.POINT)
            ],
        )

    def _address(
        self, o: _Order
    ) -> tuple[list[FormationView], dict[str, list[int]], dict[int, _Reading], dict[str, str]]:
        """The formations the order addresses and the clauses each is given (Jev's addressing,
        then the words' rules), each clause's reading, and the subordinates whose own
        sub-clause sits in a superior's order."""
        if len(o.hq) == len(o.clauses):
            addressed, parts, reading = [], {}, {}
        else:
            body = [k for k in range(len(o.clauses)) if k not in o.hq]
            extra = [self._clause_questions(k, o.clauses[k], o.sv, o.route_opts) for k in body]
            addressed, parts = self._addressing(o.state, o.text, o.clauses, o.sv.formations, extra)
            reading = {
                k: self._reading(k, o.clauses[k], self._extra, o.by_id, o.sv, o.lex) for k in body
            }
        addressed, parts = self._engine_addressing(addressed, parts, o.clauses, o.hq, o.lex)
        addressed, parts, inherited = self._mention_rules(addressed, parts, o.clauses, o.hq, o.lex)
        return addressed, parts, reading, inherited

    def _ask_details(
        self, o: _Order, plans: list[_Plan], root: FormationView | None, hq_src: str
    ) -> tuple[dict[str, Answer], str | None]:
        """Jev's details of every plan (and of the headquarters' move when the words do not
        name its place): (answers, the place the headquarters rides to)."""
        groups = [
            self._detail_questions(f"q{j}", pl.f, pl.act, o.vocab, o.route_opts, o.vocab)
            for j, pl in enumerate(plans)
        ]
        hq_dest = o.lex.hq_destination(hq_src) if o.hq else None
        if o.hq and root and hq_dest is None:
            groups.append(self._detail_questions("h", root, hq_src, o.vocab, o.route_opts, o.vocab))
        ans = self._ask_groups(o.state, groups) if groups else {}
        # A kind Jev cannot read from the whole order is asked once more with the
        # formation's own clause as the order, before the staff asks the commander.
        retry: dict[str, list[int]] = {}
        for j, pl in enumerate(plans):
            k = ans[f"q{j}_kind"]
            if (k.p_max < CONFIDENT or k.choice not in KIND_OPTIONS) and pl.act != o.text:
                retry.setdefault(pl.act, []).append(j)
        for src, js in retry.items():
            ans.update(self._ask_groups(self._state(src, o.sv.formations), [groups[j] for j in js]))
        return ans, hq_dest

    def _checked(
        self,
        plans: list[_Plan],
        done: dict[int, tuple[Task, str | None]],
        js: list[int],
        lex: Lexicon,
        checks: list[dict],
        tag: str,
        n: int,
    ) -> list[tuple[int, bool]]:
        """The check before sending of the tasks of plans `js` (pass `n`, logged in
        `checks`): (plan, goes against its words) each."""
        verdicts = self._check([(plans[j], done[j][0]) for j in js], lex, tag=tag)
        out = []
        for j, (bad, p_bad) in zip(js, verdicts, strict=True):
            checks.append(
                {
                    "formation": plans[j].f.id,
                    "task": render(done[j][0], lex),
                    "contradicts": round(p_bad, 3),
                    "pass": n,
                }
            )
            out.append((j, bad))
        return out

    def _reread(
        self,
        o: _Order,
        plans: list[_Plan],
        reread: list[int],
        reading: dict[int, _Reading],
        checks: list[dict],
    ) -> dict[int, tuple[Task, str | None]]:
        """The second reading of plans `reread`: each clause alone, a friendly never the
        objective of a fight, then checked again; a task that still goes against its words
        holds and asks the general."""
        regroups = [
            self._detail_questions(
                f"r{j}",
                plans[j].f,
                plans[j].act,
                o.vocab,
                o.route_opts,
                o.vocab,
                friendly_objective=False,
            )
            for j in reread
        ]
        ans2: dict[str, Answer] = {}
        for j, g in zip(reread, regroups, strict=True):
            ans2.update(self._ask_groups(self._state(plans[j].act, o.sv.formations), [g]))
        second = {}
        for j in reread:
            task, why, _ = self._assemble_plan(
                f"r{j}", plans[j], ans2, o.vocab, o.lex, reading, final=True
            )
            second[j] = (task, why)
        sound = [j for j in reread if not second[j][0].tentative]
        for j, bad in self._checked(plans, second, sound, o.lex, checks, "m", 2):
            if bad:
                pl = plans[j]
                second[j] = (
                    Task(
                        kind=TaskKind.HOLD,
                        formation=pl.f.id,
                        source_text=pl.full,
                        tentative=True,
                    ),
                    (
                        f"{pl.f.commander or pl.f.name}: I read «{pl.full}» as "
                        f"«{render(second[j][0], o.lex)}», and that does not square with "
                        "the words; what do you intend?"
                    ),
                )
        return second

    # -- per-clause reading (asked with the addressing) --------------------------

    @staticmethod
    def _clause_questions(
        k: int, c: str, sv: SideView, route_opts: list[_Option]
    ) -> dict[str, dict]:
        part = f"Read this part of the order: «{c}»."
        who = {
            "none": "no particular formation",
            "self": (
                "the general or formation this part of the order is given to ('you', 'he', 'it')"
            ),
        }
        for i, f in enumerate(sv.formations):
            if f.level != "army":
                who[f"w{i}"] = f"{f.name}" + (f" (General {f.commander})" if f.commander else "")
        where = {"none": "no particular place"} | {o.oid: o.short for o in route_opts}
        return {
            f"c{k}_prohib": noul(
                f"{part} Is it a prohibition or a limit, telling someone what not to do or how "
                "far not to go ('do not charge the line without my order', 'not to be drawn "
                "beyond X', 'attack nothing', 'only on my express order'), rather than an "
                "instruction to do something?",
                "yes, it forbids or limits something",
                "no, it is an instruction to act, or information",
            ),
            f"c{k}_forbid": choice(
                f"{part} If it forbids or limits something, what is forbidden?",
                {k2: v[1] for k2, v in FORBID_OPTIONS.items()},
            ),
            f"c{k}_trig": choice(
                f"{part} Does it tie what it orders to an event or a time?", TRIGGER_OPTIONS
            ),
            f"c{k}_event": choice(
                f"{part} If it names an event or a time on which what it orders starts or "
                "ends, what is that event?",
                EVENT_OPTIONS,
            ),
            f"c{k}_who": choice(
                f"{part} If it names such an event, whom does the event concern: which "
                "formation must reach or hold the place, be engaged, or break? 'You' is the "
                "general this part is given to; 'he' or 'him' is whoever the order last named.",
                who,
            ),
            f"c{k}_where": choice(
                f"{part} If the event is reaching, taking, holding or passing a place, which "
                "place?",
                where,
            ),
        }

    @staticmethod
    def _reading(
        k: int,
        c: str,
        ans: dict[str, Answer],
        by_id: dict[str, _Option],
        sv: SideView,
        lex: Lexicon,
    ) -> _Reading:
        def pick(q: str) -> str:
            a = ans.get(f"c{k}_{q}")
            return a.choice if a is not None and a.choice and a.p_max >= CONFIDENT else "none"

        r = _Reading()
        p = ans.get(f"c{k}_prohib")
        r.prohib = bool(p is not None and p.noul is not None and p.noul > 0.5)
        if r.prohib:
            fb = pick("forbid")
            val = FORBID_OPTIONS.get(fb, (None, ""))[0]
            if val == Forbid.ADVANCE_BEYOND:
                place = lex.beyond_place(c)
                r.forbid = f"{val.value}:{place}" if place else val.value
            elif val is not None:
                r.forbid = val.value
        r.trig = pick("trig")
        r.event = pick("event")
        who = pick("who")
        if who == "self":
            r.who = "self"
        elif who in by_id and by_id[who].ref and by_id[who].ref.kind == RefKind.FRIENDLY:
            r.who = by_id[who].ref.name
        elif who.startswith("w"):
            i = int(who[1:])
            if i < len(sv.formations):
                r.who = sv.formations[i].id
        wh = pick("where")
        if wh in by_id:
            r.where = by_id[wh].ref
        if r.event == "reached":
            named = lex.trigger_place(c)  # the place the words of the trigger name
            if named is not None:
                r.where = lex.feature_ref(named)
        if r.event == "time":
            r.at = clock_minute(c, sv.clock_start)
        return r

    # -- who is addressed: the words' subjects, not every name -------------------

    @staticmethod
    def _mention_rules(
        addressed: list[FormationView],
        parts: dict[str, list[int]],
        clauses: list[str],
        hq: list[int],
        lex: Lexicon,
    ) -> tuple[list[FormationView], dict[str, list[int]], dict[str, str]]:
        """The addressee of an order is the formation its first sentence opens with (or whose
        name is its grammatical subject). Every clause goes to its own subject, or, with none,
        to that addressee. Another formation named in the words ("on Prince Franz's right",
        "behind Hülsen", "your six guns", "with Prince Franz and Pannwitz at the head") is a
        reference, never an addressee; a subordinate of the addressee meant by its arm or its
        own name ("Zieten, take the hussars ...") takes the clause from him. A clause whose
        subject is a formation outside the addressee's command is an order to it only if Jev
        read one and it does not tell the addressee about it ("Krockow's horse will cover
        him"). Without an opening subject, Jev's addressing stands. Returns (addressed, parts,
        subordinates addressed only by their own sub-clause -> their superior)."""
        body = [k for k in range(len(clauses)) if k not in hq]
        if not body:
            return addressed, parts, {}
        opening = lex.grammatical_subjects(clauses[body[0]])
        if not opening or any(lex.formation(o).level == "army" for o in opening):
            return _guns_rule(addressed, parts, clauses, lex), parts, {}
        open_set = set(opening)
        family = set(open_set)
        for o in opening:
            family |= lex.descendants(o)
        jev = {k: {fid for fid, ks in parts.items() if k in ks} for k in body}
        new: dict[str, list[int]] = {}
        inherited: dict[str, str] = {}
        for k in body:
            c = clauses[k]
            subs = opening if k == body[0] else lex.grammatical_subjects(c)
            if subs and not set(subs) <= family:
                outside = [x for x in subs if x not in family]
                inside = [x for x in subs if x in family]
                if not inside:
                    if not lex.back_reference(c):
                        for x in outside:
                            if x in jev[k]:
                                new.setdefault(x, []).append(k)
                    continue
                subs = inside
            if not subs:
                subs = opening
            for x in subs:
                if x not in open_set and k != body[0]:
                    inherited[x] = next(o for o in opening if x in lex.descendants(o))
            with_g = lex.with_group(c)
            takers: list[str] = []
            for x in subs:
                desc = lex.descendants(x)
                for m in lex.formations_in(c, proper_only=False):
                    if m.key not in desc or m.key in with_g or m.key in takers:
                        continue
                    if m.proper and (m.key not in jev[k] or lex.only_referenced(c, m.key)):
                        continue
                    if (
                        lex.arm_of(lex.formation(m.key)) == Arm.ARTILLERY
                        and own_guns(c)
                        and (not artillery_named(c))
                    ):
                        continue
                    takers.append(m.key)
                if not any(t in desc for t in takers):
                    takers.append(x)
            for x in takers:
                new.setdefault(x, [])
                if k not in new[x]:
                    new[x].append(k)
        n = len(clauses)
        out_parts = {
            fid: (sorted(ks) if len(body) > 1 or n > 1 else list(range(n)))
            for fid, ks in new.items()
        }
        forms = [lex.formation(fid) for fid in out_parts]
        forms.sort(key=lambda f: len(lex.ancestors(f.id)))
        inherited = {x: a for x, a in inherited.items() if x in out_parts and x not in open_set}
        return forms, out_parts, inherited

    def _plan(
        self,
        f: FormationView,
        parts: dict[str, list[int]],
        clauses: list[str],
        text: str,
        reading: dict[int, _Reading],
        lex: Lexicon,
        inherited: dict[str, str],
    ) -> _Plan:
        ks = parts[f.id]
        full = text if len(ks) == len(clauses) else " ".join(clauses[k] for k in ks)
        pieces = []
        reacted = False
        for k in ks:
            c = clauses[k]
            r = reading.get(k)
            if r is not None and r.prohib:
                continue
            span = reaction_span(c)
            if span is not None:
                reacted = True
                a, b = span
                head = re.sub(r"(?:[\s,;]+(?:and|but|or|then))+\s*$", "", c[:a].rstrip(" ,;"))
                tail = c[b:].strip(" ,;.")
                if len(words(head)) + len(words(tail)) < 3:
                    continue  # the whole clause is a conditional reaction
                c = head.rstrip(" ,;") + (f", {tail}" if tail else "") + "."
            pieces.append(c)
        act = " ".join(pieces) if pieces else full
        if act == " ".join(clauses[k] for k in ks) and len(ks) == len(clauses):
            act = text
        co = {g for g, v in parts.items() if g != f.id and set(v) & set(ks)}
        prev = None
        if ks and ks[0] > 0:
            skip = {f.id, *co, *lex.ancestors(f.id)}
            prev = next(
                (x for x in lex.grammatical_subjects(clauses[ks[0] - 1]) if x not in skip), None
            )
        sentences = split_clauses(text)
        owner = [next((i for i, x in enumerate(sentences) if c in x), -1) for c in clauses]
        idx = sorted({owner[k] for k in ks if owner[k] >= 0})
        context = " ".join(sentences[i] for i in idx) if idx else full
        return _Plan(
            f,
            ks,
            act,
            full,
            co,
            f.id in inherited,
            prev,
            {k: clauses[k] for k in ks},
            context,
            reacted,
        )

    def _assemble_plan(
        self,
        p: str,
        pl: _Plan,
        ans: dict[str, Answer],
        vocab: list[_Option],
        lex: Lexicon,
        reading: dict[int, _Reading],
        final: bool,
    ) -> Assembly:
        """The task of one plan: Jev's details read against the words (`_assemble`), then the
        clauses' prohibitions and triggers. `again` asks for a re-read of the clause."""
        ctx = AssemblyContext(co=pl.co, prev=pl.prev, final=final)
        first = self._assemble(p, pl.f, pl.act, ans, vocab, lex, ctx)
        task = first.task
        task.source_text = pl.full
        if first.why is not None or first.again:
            return first
        if (
            pl.reacted
            and task.then is not None
            and task.then.kind in (TaskKind.ATTACK, TaskKind.CHARGE)
        ):
            task.then = None  # "ready to charge any enemy horse ...": a reaction, no phase
        held = lex.hold_object(pl.act)  # "hold Bříství until a quarter to seven, then ..."
        if held is not None:
            place = lex.feature_ref(held)
            if task.kind == TaskKind.HOLD:
                task.objective = place
                task.route = [x for x in task.route if x != place]
            else:
                head = Task(
                    kind=TaskKind.HOLD,
                    formation=task.formation,
                    objective=place,
                    manner=task.manner,
                    source_text=task.source_text,
                )
                task.route = [x for x in task.route if x != place]
                head.then, task = task, head
        return Assembly(self._apply_reading(task, pl, reading, lex), None)

    @staticmethod
    def _condition(
        r: _Reading, f: FormationView, lex: Lexicon
    ) -> tuple[Condition | None, Ref | None]:
        """(condition, own place): a clause's event as a Condition on another formation or on
        the clock; the formation's own arrival at a place is a way-point, not a condition."""
        if r.trig not in ("start", "until") or r.event in ("none", "order"):
            return None, None
        other = r.who not in (None, "self", f.id) and r.who not in lex.ancestors(f.id)
        subj = Ref(RefKind.FRIENDLY, r.who) if other else None
        if r.event == "reached":
            if other:
                return Condition(ConditionKind.WHEN_REACHED, subj, place=r.where), None
            return None, r.where
        if r.event == "engaged" and other:
            return Condition(ConditionKind.WHEN_ENGAGED, subj), None
        if r.event == "time" and r.at is not None:
            return Condition(ConditionKind.TIME, at=r.at), None
        if r.event == "seen":
            return Condition(ConditionKind.WHEN_ENEMY_SEEN), None
        if r.event == "routs" and other:
            return Condition(ConditionKind.WHEN_ROUTS, subj), None
        return None, None

    def _apply_reading(
        self, task: Task, pl: _Plan, reading: dict[int, _Reading], lex: Lexicon
    ) -> Task:
        """Prohibitions become Task.forbid; a clause's event becomes the start (or the end) of
        the task; a task that waits on another formation first marches to its way-point."""
        forbids: list[str] = []
        expiring: set[str] = set()
        starts: list[Condition] = []
        untils: list[Condition] = []
        own: Ref | None = None
        for k in pl.ks:
            r = reading.get(k)
            if r is None:
                continue
            if r.prohib:
                if r.forbid and r.forbid not in forbids:
                    forbids.append(r.forbid)
                    if r.trig in ("start", "until") and r.event not in ("none", "order"):
                        expiring.add(r.forbid)  # "not to attack before it is east of X"
                continue
            cond, place = self._condition(r, pl.f, lex)
            if cond is not None:
                (untils if r.trig == "until" else starts).append(cond)
            elif place is not None:
                own = place
        if starts:
            task.start = starts[-1]
        if untils:
            task.until = untils[-1]
        named = lex.trigger_subject(pl.act, pl.f)
        st = task.start
        if (
            named is not None
            and isinstance(st, Condition)
            and st.kind
            in (ConditionKind.WHEN_ENGAGED, ConditionKind.WHEN_REACHED, ConditionKind.WHEN_ROUTS)
            and (
                st.subject is None
                or st.subject.kind != RefKind.FRIENDLY
                or st.subject.name == pl.f.id
            )
            and not (
                st.kind == ConditionKind.WHEN_REACHED
                and st.subject is not None
                and st.subject.kind in (RefKind.FEATURE, RefKind.POINT)
            )
        ):
            st.subject = Ref(RefKind.FRIENDLY, named)  # "as soon as Prince Franz ... strikes"
        if (
            task.kind == TaskKind.HOLD
            and task.then is not None
            and task.until is None
            and {"until", "till"} & set(words(pl.act))
        ):
            # "hold Bříství until Manstein's brigade has passed, then ...": a hold ends only
            # by its `until`
            at = clock_minute(pl.act, lex.sv.clock_start)
            if at is not None:
                task.until = Condition(ConditionKind.TIME, at=at)
            elif named is not None:
                task.until = Condition(
                    ConditionKind.WHEN_REACHED, Ref(RefKind.FRIENDLY, named), place=task.objective
                )
        # the formation's own arrival at a place is where it goes first, not what it waits for
        if (
            isinstance(task.start, Condition)
            and task.start.kind == ConditionKind.WHEN_REACHED
            and task.start.place is None
            and task.start.subject is not None
            and task.start.subject.kind in (RefKind.FEATURE, RefKind.POINT)
        ):
            own = own or task.start.subject
            task.start = None
        if own is None and isinstance(task.start, Condition) and not task.route:
            mp = lex.march_place(pl.act)  # "continue the march ... toward Zlaté Slunce"
            if mp is not None:
                own = lex.feature_ref(mp)
        if own is not None and not task.route and own != task.objective:
            task.route = [own]
        standing = [x for x in forbids if x not in expiring]
        t: Task | None = task
        while t is not None:
            t.forbid = list(standing)
            t = t.then
        if isinstance(task.start, Condition) and task.route and task.kind != TaskKind.SUPPORT:
            # an adjutant's default: march to the way-point at once, wait there for the event
            first = Task(
                kind=TaskKind.ADVANCE,
                formation=task.formation,
                objective=task.route[0],
                manner=task.manner,
                source_text=task.source_text,
                forbid=list(forbids),
            )
            task.route = task.route[1:]
            first.then = task
            return first
        return task

    def _check(
        self, items: list[tuple[_Plan, Task]], lex: Lexicon, tag: str = "k"
    ) -> list[tuple[bool, float]]:
        """One noul per task, against a state of its own words and the task in plain words: does
        the task go against the order? True above CHECK_FAIL."""
        out = []
        for i, (pl, task) in enumerate(items):
            who = pl.f.name
            st = {
                "order": pl.context or pl.full,
                f"task given to {who}": render(task, lex, head=False),
            }
            q = noul(
                f"Does the task given to {who} go against the order: a different action or "
                f"objective than the order gives {who}, acting before the order allows, or "
                "doing what it forbids? Leaving out details is not going against it.",
                "yes, the task goes against the order",
                "no, the task carries out the order, perhaps with details left out",
            )
            v = self.client.ask(st, {f"{tag}{i}": q})[f"{tag}{i}"].noul
            out.append((v is not None and v > CHECK_FAIL, float(v or 0.0)))
        return out

    @staticmethod
    def _engine_addressing(
        addressed: list[FormationView],
        parts: dict[str, list[int]],
        clauses: list[str],
        hq: list[int],
        lex: Lexicon,
    ) -> tuple[list[FormationView], dict[str, list[int]]]:
        """Rules on the words after Jev's addressing:

        - headquarters clauses are no formation's task (the root gets a MOVE_HQ of its own),
          unless the clause opens with that formation's name;
        - a clause that opens with a formation's name and that Jev gave to nobody goes to that
          formation ("Krosigk's reserve waits at Nove Mesto for orders.");
        - an arm word ("the cavalry", "the guns") read into several formations of that arm from
          the same words goes to the one formation whose name or alias carries the word at the
          highest level, unless the order names them severally."""
        parts = {k: list(v) for k, v in parts.items()}
        n = len(clauses)
        for f in list(addressed):
            keep = [
                k for k in parts[f.id] if k not in hq or lex.subject_at_start(clauses[k]) == f.id
            ]
            if keep:
                parts[f.id] = keep
            else:
                addressed = [g for g in addressed if g.id != f.id]
                del parts[f.id]
        for k, c in enumerate(clauses):
            fid = lex.subject_at_start(c)
            if k in hq or fid is None or lex.formation(fid).level == "army":
                continue
            below = [g for g in parts if fid in lex.ancestors(g) and k in parts[g]]
            if fid not in parts and not below:
                addressed.append(lex.formation(fid))
                parts[fid] = [k] if n > 1 else list(range(n))
            elif fid in parts and k not in parts[fid] and not below:
                parts[fid] = sorted({*parts[fid], k})
            # a superior read into words addressed by name to its subordinate
            for a in lex.ancestors(fid):
                if a in parts and k in parts[a]:
                    parts[a] = [x for x in parts[a] if x != k]
        for fid in [g for g, v in parts.items() if not v]:
            addressed = [f for f in addressed if f.id != fid]
            del parts[fid]
        # a formation named only as a reference ("on Hülsen's left", "while Hülsen attacks",
        # "support Hülsen") is not addressed by those words
        for f in list(addressed):
            text = " ".join(clauses[k] for k in parts[f.id])
            if lex.only_referenced(text, f.id):
                addressed = [g for g in addressed if g.id != f.id]
                del parts[f.id]
        groups: dict[tuple, list[FormationView]] = {}
        for f in addressed:
            arm = lex.arm_of(f)
            if f.level != "army" and arm is not None:
                groups.setdefault((tuple(parts[f.id]), arm), []).append(f)
        for (ks, arm), fs in groups.items():
            if len(fs) < 2:
                continue
            text = " ".join(clauses[k] for k in ks)
            ws = words(text)
            word = next((w for w in ws if ARM_OF_WORD.get(w) == arm), None)
            if word is None:
                continue
            named = {m.key for m in lex.formations_in(text)}
            unnamed = [f for f in fs if f.id not in named]
            if len(fs) - len(unnamed) >= 2 or len(unnamed) < 2:
                continue
            pick = lex.arm_addressee(word, arm)
            if pick is None:
                continue
            drop = {f.id for f in unnamed}
            addressed = [f for f in addressed if f.id not in drop]
            for d in drop:
                del parts[d]
            if pick not in parts:
                addressed.append(lex.formation(pick))
                parts[pick] = list(ks)
        addressed.sort(key=lambda f: len(lex.ancestors(f.id)))
        return addressed, parts

    @staticmethod
    def _assemble_hq(
        root: FormationView,
        src: str,
        dest: str | None,
        ans: dict[str, Answer],
        by_id: dict[str, _Option],
        lex: Lexicon,
    ) -> tuple[Task | None, str | None]:
        """MOVE_HQ for the army root: the place the clause rides to, else Jev's objective."""
        objective = lex.feature_ref(dest) if dest else None
        if objective is None and "h_obj" in ans:
            o = ans["h_obj"]
            if o.choice in by_id and o.p_max >= CONFIDENT:
                objective = by_id[o.choice].ref
        if objective is None or objective.kind == RefKind.ENEMY:
            return None, f"The order «{src}» moves the headquarters; to which place?"
        return Task(
            kind=TaskKind.MOVE_HQ, formation=root.id, objective=objective, source_text=src
        ), None

    def _ask_groups(self, state: dict, groups: list[dict[str, dict]]) -> dict[str, Answer]:
        """Ask groups of questions (each group kept whole) in as few requests as fit the
        request budget; one request when everything fits, as before."""
        ans: dict[str, Answer] = {}
        batch: dict[str, dict] = {}
        size = 0
        for g in groups:
            n = len(json.dumps(g, ensure_ascii=False).encode())
            if batch and size + n > REQUEST_BUDGET:
                ans.update(self.client.ask(state, batch))
                batch, size = {}, 0
            batch.update(g)
            size += n
        if batch:
            ans.update(self.client.ask(state, batch))
        return ans

    # -- request 1 ---------------------------------------------------------

    @staticmethod
    def _state(text: str, forms: list[FormationView]) -> dict:
        return {
            "document": "A written order from the army commander to the generals of his army.",
            "order": text,
            "formations of this army": [formation_label(f) for f in forms],
        }

    def _addressing(
        self,
        state: dict,
        text: str,
        clauses: list[str],
        forms: list[FormationView],
        extra: list[dict[str, dict]] | None = None,
    ) -> tuple[list[FormationView], dict[str, list[int]]]:
        """Request 1: who is addressed, with `extra` groups (the per-clause reading) asked in
        the same request; their answers are left in `self._extra`."""
        groups: list[dict[str, dict]] = []
        for i, f in enumerate(forms):
            g = {f"a{i}": self._addr_question(f, None)}
            if len(clauses) > 1:
                for k, c in enumerate(clauses):
                    g[f"a{i}_c{k}"] = self._addr_question(f, c)
            groups.append(g)
        ans = self._ask_groups(state, groups + list(extra or []))
        self._extra = {k: v for k, v in ans.items() if k.startswith("c")}
        addressed: list[FormationView] = []
        sources: dict[str, str] = {}
        idx: dict[str, list[int]] = {}
        for i, f in enumerate(forms):
            if not ans[f"a{i}"].yes:
                continue
            addressed.append(f)
            ks = [k for k in range(len(clauses)) if len(clauses) > 1 and ans[f"a{i}_c{k}"].yes]
            idx[f.id] = ks or list(range(len(clauses)))
            sources[f.id] = " ".join(clauses[k] for k in ks) if ks else text
        # A formation and some of its subordinates addressed by the same words: if every child
        # formation is among them, the subordinates are part of the superior's task (one task,
        # one line); if only some are ("Zieten, the hussars ..." under Zieten's vanguard, whose
        # infantry is not meant), the superior is dropped and the subordinates keep the order.
        # The army is handled below.
        by_id = {f.id: f for f in forms}

        def ancestors(f: FormationView) -> list[str]:
            out, p = [], f.parent
            while p is not None and p in by_id and p not in out:
                out.append(p)
                p = by_id[p].parent
            return out

        ids = {f.id for f in addressed}
        drop: set[str] = set()
        for f in sorted(addressed, key=lambda f: len(ancestors(f))):
            if f.level == "army" or f.id in drop:
                continue
            same = [
                g
                for g in addressed
                if f.id in ancestors(g) and sources[g.id] == sources[f.id] and g.id not in drop
            ]
            if not same:
                continue
            children = [c.id for c in forms if c.parent == f.id]
            if all(c in ids and sources[c] == sources[f.id] for c in children):
                drop.update(g.id for g in same)
            else:
                drop.add(f.id)
        addressed = [f for f in addressed if f.id not in drop]
        # When the whole army is addressed, the formations read into the same words are asked
        # once more whether they have an instruction of their own ("the whole army holds the
        # heights" addresses the army, not forty formations; "Everything forward! Bevern
        # storms ..." addresses Bevern too).
        army = next((f for f in addressed if f.level == "army"), None)
        same = [
            f for f in addressed if army and f is not army and sources[f.id] == sources[army.id]
        ]
        if same:
            own = self._ask_groups(
                state,
                [{f"o{i}": self._own_question(f)} for i, f in enumerate(same)],
            )
            drop = {f.id for i, f in enumerate(same) if not own[f"o{i}"].yes}
            addressed = [f for f in addressed if f.id not in drop]
        # ancestors first, so that a subordinate's own task (sent later) overrides
        addressed.sort(key=lambda f: len(ancestors(f)))
        return addressed, {f.id: idx[f.id] for f in addressed}

    @staticmethod
    def _own_question(f: FormationView) -> dict:
        who = formation_label(f)
        return noul(
            f"Read the order. Apart from what the whole army is told to do, does it give {who} "
            "an instruction of its own: is this formation or its general named, or meant by "
            "its arm ('the cavalry', 'the guns'), and given something particular to do?",
            "yes, it has an instruction of its own",
            "no, it is only part of the whole army's instruction",
        )

    @staticmethod
    def _addr_question(f: FormationView, clause: str | None) -> dict:
        who = formation_label(f)
        where = f"this part of the order: «{clause}»" if clause else "the order"
        if f.level == "army":
            return noul(
                f"Read {where}. Is the whole army ({who}) told to do something as one body, "
                "for example 'everything forward' or 'the army will retire'? An instruction to "
                "particular generals or formations alone does not count.",
                "yes, an instruction to the whole army at once",
                "no, only particular formations are instructed, or none",
            )
        return noul(
            f"Read {where}. Does it give {who} an instruction: is this formation or its "
            "general named, addressed as 'you', or clearly meant (by arm, e.g. 'the cavalry', "
            "'the artillery', 'the hussars') as one who must do or not do something? Being "
            "mentioned only as a place to follow, wait for, or stay behind does not count, and "
            "neither does being the 'you' of a condition such as 'once you are engaged'.",
            "yes, this formation is given an instruction",
            "no, it is not instructed (perhaps only mentioned)",
        )

    # -- request 2 ---------------------------------------------------------

    @staticmethod
    def _vocab(sv: SideView) -> list[_Option]:
        opts: list[_Option] = []
        for i, name in enumerate(sv.feature_names):
            if name in sv.places:
                opts.append(
                    _Option(
                        f"f{i}_{_slug(name)}",
                        f"{name} (a place relative to our own army as it now stands)",
                        Ref(RefKind.POINT, name, sv.places[name]),
                    )
                )
                continue
            if name in sv.offsets:
                opts.append(
                    _Option(
                        f"f{i}_{_slug(name)}",
                        f"{name} (a point placed by that distance and direction from the "
                        "named place)",
                        Ref(RefKind.POINT, name, sv.offsets[name]),
                    )
                )
                continue
            desc = name
            aliases = list(sv.feature_aliases.get(name) or [])
            plain = fold(name)
            if plain != name.casefold() and plain not in {fold(a) for a in aliases}:
                aliases.append(
                    unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode()
                )
            if aliases:
                desc += " (also: " + ", ".join(aliases) + ")"
            opts.append(_Option(f"f{i}_{_slug(name)}", desc, Ref(RefKind.FEATURE, name), name))
        # Bodies the side's naming tells apart only by a number ("... near X (2)") are one
        # option: the first so named stands for the group (the drill then takes the nearest).
        groups: dict[str, str] = {}
        for e in sv.enemies:
            groups.setdefault(re.sub(r" \(\d+\)$", "", e.name), e.name)
        for i, (base, first) in enumerate(groups.items()):
            opts.append(
                _Option(
                    f"e{i}_{_slug(base)}",
                    f"the enemy: {base} (or a flank or part of it)",
                    Ref(RefKind.ENEMY, first),
                )
            )
        for i, f in enumerate(sv.formations):
            if f.level == "army":
                continue
            opts.append(
                _Option(
                    f"w{i}_{_slug(f.name)}",
                    f"our own {formation_label(f)}",
                    Ref(RefKind.FRIENDLY, f.id),
                )
            )
        return opts

    @staticmethod
    def _detail_questions(
        p: str,
        f: FormationView,
        src: str,
        vocab: list[_Option],
        route_opts: list[_Option],
        subject_opts: list[_Option],
        friendly_objective: bool = True,
    ) -> dict[str, dict]:
        who = formation_label(f)
        focus = f"Consider what the order tells {who} to do (the relevant words: «{src}»)."
        obj = {
            o.oid: o.desc
            for o in vocab
            if friendly_objective or o.ref is None or o.ref.kind != RefKind.FRIENDLY
        }
        obj["none"] = "no specific objective is named (e.g. simply 'forward' or 'hold')"
        obj["other"] = "a place or body that is not on this list, or one that cannot be told apart"
        route = {o.oid: o.desc for o in route_opts}
        route["none"] = "no route or way-point is given"
        subj = {o.oid: o.short for o in subject_opts}
        subj["none"] = "no such condition, or no particular subject"
        qs = {
            f"{p}_kind": choice(
                f"{focus} What kind of action is it?",
                {k: v[1] for k, v in KIND_OPTIONS.items()},
            ),
            f"{p}_obj": choice(
                f"{focus} What is the objective: the place to go to or hold, the enemy to attack, "
                "or the friendly formation to follow? A place only gone round, along or through on "
                "the way is the route, not the objective.",
                obj,
            ),
            f"{p}_route": choice(
                f"{focus} Which place must it go by or round on the way, if any?", route
            ),
            f"{p}_state": choice(
                f"{focus} In what formation is it to be at the objective?",
                {k: v[1] for k, v in STATE_OPTIONS.items()},
            ),
            f"{p}_contact": choice(
                f"{focus} What should it do when it meets the enemy?",
                {k: v[1] for k, v in CONTACT_OPTIONS.items()},
            ),
            f"{p}_manner": score(f"{focus} In what manner is it to act?", MANNER_LEVELS),
            f"{p}_subj": choice(
                f"{focus} If it is to start only after something happens (another formation is "
                "engaged, a place is reached, the enemy is seen or breaks), whom or what does "
                "that condition concern? 'You' in the order means the general addressed first.",
                subj,
            ),
        }
        qs[f"{p}_then"] = noul(
            f"{focus} Is it told to do something further once its first action is done, as a "
            "second phase (for example 'then wait for ...', 'then hold', 'and afterwards "
            "advance on ...')?",
            "yes, a second phase follows the first",
            "no, there is only one action",
        )
        qs[f"{p}_then_kind"] = choice(
            f"{focus} If a second phase follows the first action, what kind of action is that "
            "second phase?",
            {k: v[1] for k, v in KIND_OPTIONS.items()},
        )
        qs[f"{p}_then_obj"] = choice(
            f"{focus} If a second phase follows the first action, what is the objective of that "
            "second phase: the place to go to or hold, the enemy, or the friendly formation to "
            "follow or wait for?",
            {**{o.oid: o.short for o in vocab}, "none": obj["none"], "other": obj["other"]},
        )
        for k, (_, desc) in START_NOULS.items():
            qs[f"{p}_start_{k}"] = noul(
                f"{focus} When does it start? Does it {desc}?", f"yes, it {desc}", "no"
            )
        return qs

    def _assemble(
        self,
        p: str,
        f: FormationView,
        src: str,
        ans: dict[str, Answer],
        vocab: list[_Option],
        lex: Lexicon,
        ctx: AssemblyContext | None = None,
    ) -> Assembly:
        """The task of formation `f` from Jev's details (questions prefixed `p`) read against
        the words `src`, in phases: Jev's reading, the compound orders, the objective the words
        name, the friendly a support stands by, the objective settled, then state, contact,
        start and sequel. An order that cannot be read holds the formation and asks."""
        ctx = ctx or AssemblyContext()
        by_id = {o.oid: o for o in vocab}
        by_ref = {(o.ref.kind, o.ref.name): o for o in vocab if o.ref is not None}
        who = f.commander or f.name
        # the stand-in of an order the staff cannot read: holds a formation that has no task,
        # never replaces the one it has (Task.tentative)
        hold = Task(kind=TaskKind.HOLD, formation=f.id, source_text=src, tentative=True)
        d = self._jev_reading(p, ans, by_id)
        guard, march = self._compound_orders(d, f, src, lex, ctx)
        if d.kind is None:
            return Assembly(hold, f"{who}: the order «{src}» is unclear; what am I to do?")
        if march and not d.route and lex.feature_ref(march[0]) != d.objective:
            d.route = [lex.feature_ref(march[0])]
        unseen = self._objective_in_words(d, src, lex, march)
        if unseen is not None:
            return Assembly(hold, f"{who}: I cannot see «{unseen}»; which body is meant?")
        if d.kind in _CONTACT and d.objective is not None and d.objective.kind == RefKind.FRIENDLY:
            # a friendly is never the objective of a fight ("attack on Prince Franz's right"):
            # the clause is read again without friendlies; if it still names one, the
            # formation named is the one to stand by ("ready to charge whatever comes against
            # his flank")
            if not ctx.final and d.kind != TaskKind.WITHDRAW:
                return Assembly(hold, None, again=True)
            d.kind = TaskKind.SUPPORT
        if not self._friendly_objective(d, f, src, lex, ctx, guard):
            return Assembly(hold, f"{who}: whom am I to support or follow?")
        if not self._settle_objective(d, src, lex, ans[f"{p}_obj"], by_id, by_ref):
            return Assembly(
                hold,
                f"{who}: the order «{src}» names an objective I cannot identify; "
                "which place or body is meant?",
            )
        state, on_contact, start = self._state_contact_start(p, ans, by_id)
        task = Task(
            kind=d.kind,
            formation=f.id,
            objective=d.objective,
            route=d.route,
            state=state,
            start=start,
            on_contact=on_contact,
            manner=d.manner,
            source_text=src,
        )
        task.then, why = self._sequel(p, f, src, ans, by_id, d.manner, task, lex)
        return Assembly(task, why)

    @staticmethod
    def _jev_reading(p: str, ans: dict[str, Answer], by_id: dict[str, _Option]) -> _Draft:
        """Kind, objective, route and manner as Jev reads them, each where it is confident."""
        kind_a, obj_a = ans[f"{p}_kind"], ans[f"{p}_obj"]
        kind = (
            KIND_OPTIONS[kind_a.choice][0]
            if kind_a.p_max >= CONFIDENT and kind_a.choice in KIND_OPTIONS
            else None
        )
        objective = (
            by_id[obj_a.choice].ref if obj_a.choice in by_id and obj_a.p_max >= CONFIDENT else None
        )
        route: list[Ref] = []
        r = ans[f"{p}_route"]
        if r.choice in by_id and r.p_max >= CONFIDENT:
            route = [by_id[r.choice].ref]
        m = ans[f"{p}_manner"]
        manner = MANNERS[min(3, max(0, round(m.score)))] if m.score is not None else Manner.MEASURED
        return _Draft(kind, objective, route, manner)

    @staticmethod
    def _compound_orders(
        d: _Draft, f: FormationView, src: str, lex: Lexicon, ctx: AssemblyContext
    ) -> tuple[str | None, tuple[str, str] | None]:
        """Compound orders, read from the words: "keep X on Y's left as he attacks" -> SUPPORT
        Y; "march to X and support Y" -> SUPPORT Y by way of X; "take Y in flank" -> ATTACK
        Y, boldly, by the way named; "take post behind Y" -> SUPPORT. Returns the flank guard's
        subject and the march (place, verb) for the later phases."""
        guard = lex.flank_guard(src, f)
        march = lex.march_to_and(src)
        flank, flank_target, flank_way = lex.flank_attack(src)
        supporting = march is not None and march[1] in SUPPORT_WORDS
        if (guard or supporting) and d.kind not in _CONTACT:
            d.kind = TaskKind.SUPPORT
        if flank:
            d.kind = TaskKind.CHARGE if d.kind == TaskKind.CHARGE else TaskKind.ATTACK
            d.manner = d.manner if d.manner == Manner.RECKLESS else Manner.BOLD
            if flank_target:
                d.objective = lex.feature_ref(flank_target)
            if flank_way and not d.route:
                d.route = [lex.feature_ref(flank_way)]
        if d.kind is None and (
            lex.stand_behind(src, f)
            or (
                lex.follow_subject(src, f, ctx.co)
                and {"follow", "following", "behind", "support"} & set(words(src))
            )
        ):
            d.kind = TaskKind.SUPPORT  # "... and then take post behind Hülsen's corps"
        return guard, march

    @staticmethod
    def _objective_in_words(
        d: _Draft, src: str, lex: Lexicon, march: tuple[str, str] | None
    ) -> str | None:
        """The objective as the words name it: a place the attack verb takes as its object, the
        place marched to as the way of an attack, a known enemy body at the place named. An
        enemy the side cannot see is returned, to be asked about."""
        # A place the attack verb takes as its object is the objective, whatever enemy the
        # words also name ("carry the village of Bříství, driving out the enemy there")
        # (only over an enemy or no objective: a place Jev chose stands, "storm the heights at
        # Křečhoř" is the heights).
        place = (
            lex.attack_object(src)
            if d.kind in (TaskKind.ATTACK, TaskKind.CHARGE, TaskKind.ADVANCE, TaskKind.BOMBARD)
            and (d.objective is None or d.objective.kind == RefKind.ENEMY)
            else None
        )
        if place is not None:
            d.objective = lex.feature_ref(place)
            d.route = [x for x in d.route if x != d.objective]
        elif (
            d.kind in (TaskKind.ATTACK, TaskKind.CHARGE)
            and march is not None
            and d.objective == lex.feature_ref(march[0])
        ):
            # "march to Zlaté Slunce and there wheel right and attack ...": the place marched
            # to is the way, not what is attacked
            d.route = d.route or [d.objective]
            d.way, d.objective = d.objective, None
        # Enemy bodies must be in the side's picture: an objective of kind ENEMY that the
        # side does not know, or words that plainly name a body it has not seen.
        elif d.kind in (TaskKind.ATTACK, TaskKind.CHARGE, TaskKind.BOMBARD, TaskKind.ADVANCE):
            known = {e.name for e in lex.sv.enemies}
            if (
                d.objective is not None
                and d.objective.kind == RefKind.ENEMY
                and (d.objective.name not in known)
            ):
                return d.objective.name
            # an attack on a place the words name stands whatever unseen enemy they also name
            # ("attack Moravské Budějovice up the imperial road ..."): never a hold
            on_place = (
                d.objective is not None
                and d.objective.kind in (RefKind.FEATURE, RefKind.POINT)
                and d.objective.name == lex.attack_object(src)
            )
            unseen = None if on_place else lex.unknown_enemy(src)
            if unseen:
                return unseen
            # a place chosen where the words name a known body at that place: the body
            seen = lex.known_enemy_at(src)
            if seen is not None and (d.objective is None or d.objective.kind != RefKind.ENEMY):
                base = re.sub(r" \(\d+\)$", "", seen)
                first = next(e.name for e in lex.sv.enemies if e.name.startswith(base))
                d.objective = Ref(RefKind.ENEMY, first)
        return None

    def _friendly_objective(
        self,
        d: _Draft,
        f: FormationView,
        src: str,
        lex: Lexicon,
        ctx: AssemblyContext,
        guard: str | None,
    ) -> bool:
        """The friendly a support, a screen or a march with a friend stands by; False when a
        support has none the words or the order of march give."""
        if (
            d.kind in (TaskKind.ADVANCE, TaskKind.HOLD)
            and d.objective is not None
            and (d.objective.kind == RefKind.FRIENDLY)
        ):
            d.kind = TaskKind.SUPPORT  # "march behind the left wing", "stay with Hollenegg"
        if d.kind in (TaskKind.HOLD, TaskKind.ADVANCE):
            behind = lex.stand_behind(src, f)
            if behind is not None:  # "to stand north of Bříství and behind Hülsen"
                if d.objective is not None and d.objective.kind in (RefKind.FEATURE, RefKind.POINT):
                    d.route = [*[x for x in d.route if x != d.objective], d.objective]
                d.kind, d.objective = TaskKind.SUPPORT, Ref(RefKind.FRIENDLY, behind)
            elif d.objective is None and follow_ahead(src):
                d.kind = TaskKind.SUPPORT  # "keep closed up on the brigades ahead"
        if d.kind == TaskKind.SUPPORT and (
            d.objective is None or d.objective.kind != RefKind.FRIENDLY
        ):
            subject = (
                guard
                or lex.follow_subject(src, f, ctx.co)
                or lex.stand_behind(src, f)
                or ctx.prev
                or self._ahead(f, lex)
            )
            if subject is None:
                return False
            if d.objective is not None and d.objective.kind in (RefKind.FEATURE, RefKind.POINT):
                d.route = d.route or [d.objective]
            d.objective = Ref(RefKind.FRIENDLY, subject)
        if d.kind in (TaskKind.SCREEN, TaskKind.SUPPORT) and (
            d.objective is None or d.objective.kind != RefKind.FRIENDLY
        ):
            covered = lex.cover_subject(src, f)  # "cover Manstein's brigade as it comes down"
            if covered is not None:
                if d.objective is not None and d.objective.kind in (RefKind.FEATURE, RefKind.POINT):
                    d.route = d.route or [d.objective]
                d.objective = Ref(RefKind.FRIENDLY, covered)
        return True

    @staticmethod
    def _settle_objective(
        d: _Draft,
        src: str,
        lex: Lexicon,
        obj_a: Answer,
        by_id: dict[str, _Option],
        by_ref: dict[tuple, _Option],
    ) -> bool:
        """The objective at last: Jev's leaning taken where the words name it, a place named
        in the words, none for a hold where it stands; False when there is none to identify."""
        if d.objective is None and obj_a.choice not in ("other", "none") and obj_a.choice in by_id:
            # Jev leaned to a place under the cut-off: taken when the words name it
            top = by_id[obj_a.choice].ref
            named = {m.key for m in lex.features_in(src)}
            if top.kind in (RefKind.FEATURE, RefKind.POINT) and top.name in named and top != d.way:
                d.objective = top
        holding = d.kind == TaskKind.HOLD and obj_a.choice == "other"  # hold where it stands
        if (
            d.objective is None
            and not holding
            and (obj_a.choice == "other" or obj_a.p_max < CONFIDENT)
        ):
            return False
        if (
            d.objective is not None
            and (d.objective.kind, d.objective.name) not in by_ref
            and (d.objective.kind != RefKind.FRIENDLY)
        ):
            d.objective = lex.feature_ref(d.objective.name)  # a place named in the words
        d.route = [x for x in d.route if x != d.objective]
        return True

    @staticmethod
    def _state_contact_start(
        p: str, ans: dict[str, Answer], by_id: dict[str, _Option]
    ) -> tuple[UnitState | None, OnContact, Condition | None]:
        """The desired state, what to do on contact and the start condition, where Jev is
        confident (else: no state, engage, start now)."""
        st = ans[f"{p}_state"]
        state = (
            STATE_OPTIONS[st.choice][0]
            if st.choice in STATE_OPTIONS and st.p_max >= CONFIDENT
            else None
        )
        ct = ans[f"{p}_contact"]
        on_contact = (
            CONTACT_OPTIONS[ct.choice][0]
            if ct.choice in CONTACT_OPTIONS and ct.p_max >= CONFIDENT
            else OnContact.ENGAGE
        )
        start: Condition | None = None
        now_p = ans[f"{p}_start_now"].noul or 0.0
        best_k, best_p = None, 0.0
        for k, (ck, _) in START_NOULS.items():
            if ck is None:
                continue
            pk = ans[f"{p}_start_{k}"].noul or 0.0
            if pk > best_p:
                best_k, best_p = ck, pk
        if best_k is not None and best_p >= CONFIDENT and best_p > now_p:
            s = ans[f"{p}_subj"]
            subject = by_id[s.choice].ref if s.choice in by_id and s.p_max >= CONFIDENT else None
            # A place-reached condition with no identifiable place is the task's own arrival,
            # which the drill already handles; drop it rather than hand the engine a blank.
            if subject is not None or best_k != ConditionKind.WHEN_REACHED:
                start = Condition(kind=best_k, subject=subject)
        return state, on_contact, start

    @staticmethod
    def _ahead(f: FormationView, lex: Lexicon) -> str | None:
        """The brigade in front of the formation in the side's order of march ("keep closed up
        on the brigades ahead"): of its own column where there is one ahead, else of its own
        arm (a brigade of mixed arms counts), else any."""
        order = lex.sv.march_order
        mine = {f.id, *lex.descendants(f.id)}
        idx = [i for i, x in enumerate(order) if x in mine]
        if not idx:
            return None
        ahead = [x for x in order[: idx[0]] if x not in mine]
        arm = lex.arm_of(f)
        column = [x for x in ahead if f.parent is not None and lex.formation(x).parent == f.parent]
        same = [x for x in ahead if lex.arm_of(lex.formation(x)) in (arm, None)] if arm else []
        pick = column or same or ahead
        return pick[-1] if pick else None

    @staticmethod
    def _sequel(
        p: str,
        f: FormationView,
        src: str,
        ans: dict[str, Answer],
        by_id: dict[str, _Option],
        manner: Manner,
        first: Task,
        lex: Lexicon,
    ) -> tuple[Task | None, str | None]:
        """The second phase, if Jev reads one: HOLD where it stands when the sequel is 'wait for
        <friendly>' (waiting is not following); a SUPPORT sequel follows the friendly the words name
        ("then follow him", with one friendly named); a sequel of the first phase's kind with no
        other objective is the first phase itself ("hold ... until further orders", "follow and
        support him"); an unidentifiable objective for any other kind gives a HOLD sequel and a
        clarification."""
        if not ans[f"{p}_then"].yes:
            return None, None
        k, o = ans[f"{p}_then_kind"], ans[f"{p}_then_obj"]
        if k.p_max < CONFIDENT or k.choice not in KIND_OPTIONS:
            return None, None
        kind = KIND_OPTIONS[k.choice][0]
        obj = by_id[o.choice].ref if o.choice in by_id and o.p_max >= CONFIDENT else None
        if kind == first.kind and (obj is None or obj == first.objective):
            return None, None
        if kind == TaskKind.WITHDRAW and re.search(r"\b(?:if|should|unless)\b", src, re.IGNORECASE):
            return None, None  # "and if he is overborne, fall back": a contingency, no phase
        if kind in (TaskKind.ATTACK, TaskKind.CHARGE, TaskKind.BOMBARD) and (
            obj is not None and obj.kind == RefKind.FRIENDLY
        ):
            return None, None  # "charging any enemy horse that falls on it": a reaction
        hold = Task(kind=TaskKind.HOLD, formation=f.id, source_text=src, manner=manner)
        if kind == TaskKind.SUPPORT and (obj is None or obj.kind != RefKind.FRIENDLY):
            # "then follow him to X": the friendly the words name, after the "then" first;
            # "cover Prince Franz's withdrawal, then follow it": the first task's friendly
            tail = re.split(r"\bthen\b", src)[-1]
            excl = {f.id, *lex.ancestors(f.id)}
            subject = (
                lex.support_subject(tail, f)
                or lex.stand_behind(src, f)
                or lex.support_subject(src, f)
                or next((m.key for m in lex.formations_in(src) if m.key not in excl), None)
            )
            mine = (
                first.objective.name
                if first.objective is not None and (first.objective.kind == RefKind.FRIENDLY)
                else None
            )
            if subject is None and mine is not None and first.kind != TaskKind.SUPPORT:
                subject = mine
            if subject is not None and (subject != mine or first.kind != TaskKind.SUPPORT):
                obj = Ref(RefKind.FRIENDLY, subject)
            elif first.kind == TaskKind.SUPPORT:
                return None, None  # "follow and support its attack": the first phase itself
            else:
                return hold, None  # "re-form there": an adjutant holds it there, no question
        if kind == TaskKind.HOLD:
            if obj is not None and obj.kind in (RefKind.FEATURE, RefKind.POINT):
                hold.objective = obj
            elif first.kind in (TaskKind.SUPPORT, TaskKind.SCREEN):
                return None, None  # following or screening has no end to hold after
            return hold, None
        if (obj is None and o.choice != "none") or (
            kind == TaskKind.SUPPORT and (obj is None or obj.kind != RefKind.FRIENDLY)
        ):
            # a second phase the staff cannot place ("re-form there behind the infantry"):
            # the formation holds where the first phase leaves it; the check before sending
            # judges whether that still squares with the words
            if first.kind in (TaskKind.SUPPORT, TaskKind.SCREEN):
                return None, None  # following or screening has no end to hold after
            return hold, None
        return Task(kind=kind, formation=f.id, objective=obj, source_text=src, manner=manner), None
