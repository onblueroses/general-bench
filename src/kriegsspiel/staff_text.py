"""Text matching for the staff: names of formations, places and enemy bodies in an order.

Jev reads the order; these rules only find what the order plainly names, so that the staff can
check Jev's reading against the words (a single addressee for "the cavalry", an enemy body the
side has not seen, the headquarters, the friendly formation of a "support"). Matching is
diacritic- and case-insensitive (NFKD with combining marks stripped, casefold) on both sides,
and tolerates one letter dropped, added or changed in words of six letters or more ("Krecor"
for "Křečhoř" folded to "krechor").
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field, replace

from . import geometry
from .types import Arm, FormationView, Ref, RefKind, SideView

LEVEL_RANK = {"army": 3, "wing": 2, "column": 1, "brigade": 0}

ARM_WORDS: dict[Arm, set[str]] = {
    Arm.CAVALRY: {
        "cavalry",
        "horse",
        "hussar",
        "hussars",
        "cuirassier",
        "cuirassiers",
        "dragoon",
        "dragoons",
        "squadrons",
        "troopers",
        "uhlans",
        "chevaux",
        "legers",
    },
    Arm.ARTILLERY: {"artillery", "guns", "gun", "batteries", "battery", "cannon"},
    Arm.INFANTRY: {
        "infantry",
        "foot",
        "battalions",
        "grenadiers",
        "musketeers",
        "fusiliers",
        "grenzer",
    },
}
ARM_OF_WORD = {w: a for a, ws in ARM_WORDS.items() for w in ws}
# words that alone do not name a particular formation ("the heavy guns", "the Prussian horse")
_ARM_ONLY = set(ARM_OF_WORD) | {
    "the",
    "heavy",
    "light",
    "our",
    "s",
    "prussian",
    "austrian",
    "imperial",
    "saxon",
    "whole",
}
_TITLES = {
    "general",
    "generalmajor",
    "generalleutnant",
    "major",
    "prince",
    "count",
    "graf",
    "baron",
    "feldmarschall",
    "field",
    "marshal",
    "colonel",
    "oberst",
    "lieutenant",
    "von",
    "der",
    "de",
    "the",
    "king",
    "gm",
    "fml",
    "est",
    "senior",
    "battalion",
    "commander",
    "unrecorded",
    "artillery",
    "prussian",
    "austrian",
    "post",
    "commanders",
    "reserve",
}
# Side words by the side ids the packs use (oob.json "sides"). A side's own words are its row
# plus every demonym its own formations carry in a name or alias (an allied army may have
# "the British cavalry" and "the Hessian column"); every other demonym is the enemy's.
# single title words that are a formation's role: "the Reserve" alone addresses the formation
# so named (not a proper name: it does not make a surname or a friendly word)
ROLE_WORDS = {"reserve", "reserves"}
# words that end an unnamed commander's description and are no surname ("left batteries
# officer", "reserve brigadier (unrecorded)", "train commissary")
_GENERIC_PEOPLE = {
    "officer",
    "officers",
    "brigadier",
    "commissary",
    "captain",
    "adjutant",
    "unknown",
    "name",
    "unrecorded",
    "brigade",
    "batteries",
    "battery",
    "staff",
    "leader",
    "chief",
    "colonel",
    "major",
}
DEMONYMS: dict[str, set[str]] = {
    "prussia": {"prussian", "prussians"},
    "austria": {
        "austrian",
        "austrians",
        "imperial",
        "imperialist",
        "imperialists",
        "croat",
        "croats",
        "pandour",
        "pandours",
        "hungarian",
        "saxon",
        "saxons",
    },
    "red": {"red", "reds"},
    "blue": {"blue", "blues"},
    # Arms (data/arms-medlar): the sides are named by their arm, the armies by colour
    "horse": {"white", "whites"},
    "foot": {"green", "greens"},
    "allies": {
        "allied",
        "allies",
        "hanoverian",
        "hanoverians",
        "hessian",
        "hessians",
        "brunswicker",
        "brunswickers",
    },
    "france": {"french", "frenchmen"},
    "america": {"american", "americans", "continental", "continentals", "rebel", "rebels"},
    "britain": {
        "british",
        "redcoats",
        "english",
        "loyalist",
        "loyalists",
        "provincial",
        "provincials",
    },
}
ALL_DEMONYMS = set().union(*DEMONYMS.values())
# words that name the people, not a body ("the Croats", "the French", "the Reds")
NOUN_DEMONYMS = {
    "croats",
    "croat",
    "pandours",
    "pandour",
    "saxons",
    "prussians",
    "austrians",
    "imperialists",
    "reds",
    "blues",
    "whites",
    "greens",
    "allies",
    "hanoverians",
    "hessians",
    "brunswickers",
    "frenchmen",
    "americans",
    "continentals",
    "rebels",
    "redcoats",
    "loyalists",
    "provincials",
}
# a train, park or baggage: wagons, the enemy's when the side has no such formation
TRAIN_WORDS = {
    "train",
    "trains",
    "wagon",
    "wagons",
    "baggage",
    "park",
    "convoy",
    "carts",
    "waggons",
    "waggon",
}
ENEMY_ADJ = {"enemy", "hostile", "their"}
_OLD_NOUNS = {"croats", "croat", "pandours", "pandour", "saxons"}  # light infantry by name
ENEMY_NOUNS = (
    set(ARM_OF_WORD)
    | {
        "troops",
        "line",
        "lines",
        "body",
        "bodies",
        "column",
        "columns",
        "right",
        "left",
        "flank",
        "wing",
        "regiments",
        "regiment",
        "force",
        "forces",
        "army",
        "corps",
        "division",
        "brigade",
        "squadron",
        "men",
        "people",
        "rearguard",
        "front",
        "centre",
        "center",
        "position",
    }
    | TRAIN_WORDS
)
PLACE_PREPS = {
    "at",
    "near",
    "in",
    "behind",
    "beyond",
    "by",
    "on",
    "around",
    "before",
    "about",
    "of",
    "from",
    "towards",
    "toward",
    "outside",
    "below",
    "above",
}
SUPPORT_VERBS = {
    "support",
    "supporting",
    "follow",
    "following",
    "join",
    "reinforce",
    "assist",
    "second",
    "back",
    "behind",
    "with",
}
MOVE_VERBS = {
    "march",
    "marching",
    "move",
    "moving",
    "go",
    "ride",
    "proceed",
    "hasten",
    "hurry",
    "bring",
    "take",
    "lead",
    "advance",
    "come",
    "push",
    "send",
}
REFERENCE_WORDS = {
    "on",
    "upon",
    "behind",
    "of",
    "to",
    "with",
    "support",
    "supporting",
    "follow",
    "following",
    "join",
    "reinforce",
    "as",
    "while",
    "whilst",
    "when",
    "once",
    "until",
    "after",
    "before",
    "past",
    "near",
    "beside",
}
ROUTE_PREPS = {"past", "round", "around", "by", "through", "via", "beyond", "along"}
FLANK_VERBS = {
    "take",
    "taking",
    "fall",
    "falling",
    "strike",
    "striking",
    "attack",
    "attacking",
    "turn",
    "turning",
    "charge",
    "charging",
    "hit",
    "roll",
    "rolling",
}

ARMY_ALIASES = ["the headquarters", "my headquarters", "the King", "the Feldmarschall"]
_OPENING_SKIP = {
    "general",
    "generalmajor",
    "the",
    "to",
    "herr",
    "you",
    "and",
    "but",
    "then",
    "while",
}
_MODALS = {"will", "shall", "must", "is", "are", "to", "should"}

# A conditional reaction ("be ready to charge any enemy horse that ...", "charging any enemy
# horse that falls on its flank"): what to do if something happens, not the task itself.
_REACTION = re.compile(
    r"\b(?:(?:be|stand|stands|keep\s+\w+|keeping\s+\w+|remain|remains|held|is\s+to\s+be|are\s+to\s+be)"
    r"\s+)?ready\s+to\b"
    r"|\b(?:charg(?:e|ing)|strik(?:e|ing)|fall(?:ing)?\s+(?:up)?on)\s+(?:any|whatever)\b",
    re.IGNORECASE,
)
# "keep closed up", "the brigades ahead of you", "follow the column ahead"
_FOLLOW_AHEAD = re.compile(
    r"\bclosed?\s+up\b|\b(?:brigades?|columns?|troops|infantry|battalions|those|one)\s+"
    r"(?:ahead|in\s+front)\b|\bahead\s+of\s+(?:you|him|them|it)\b|\bthe\s+order\s+of\s+march\b",
    re.IGNORECASE,
)
STATION_VERBS = {
    "stand",
    "standing",
    "post",
    "form",
    "forming",
    "halt",
    "remain",
    "wait",
    "rally",
    "reform",
    "gathering",
    "gather",
    "assemble",
    "take",
    "draw",
    "keep",
}
ATTACK_VERBS = {
    "attack",
    "attacking",
    "storm",
    "storming",
    "carry",
    "carrying",
    "seize",
    "seizing",
    "take",
    "taking",
    "capture",
    "assault",
    "assaulting",
    "clear",
    "clearing",
    "drive",
    "driving",
    "charge",
    "charging",
    "strike",
    "striking",
    "throw",
    "throwing",
    "bombard",
    "bombarding",
    "cannonade",
}
_NEGATIONS = {"no", "not", "never", "nor", "without", "nothing", "none"}
_OWN_GUNS = re.compile(
    r"\b(?:your|his|their|its|own|the\s+six|six|four|two|battalion|"
    r"regimental)\s+(?:\w+\s+)?guns\b",
    re.IGNORECASE,
)
_ARTILLERY_PROPER = re.compile(
    r"\bheavy\s+(?:artillery|guns|batteries)\b|\bthe\s+artillery\b|\bthe\s+batteries\b"
    r"|\bartillery\s+commander\b|\bcommander\s+of\s+the\s+(?:heavy\s+)?artillery\b"
    r"|^\s*(?:the\s+)?guns\b",
    re.IGNORECASE,
)
_NUMBERS = {
    "one": 1,
    "two": 2,
    "three": 3,
    "four": 4,
    "five": 5,
    "six": 6,
    "seven": 7,
    "eight": 8,
    "nine": 9,
    "ten": 10,
    "eleven": 11,
    "twelve": 12,
}
_CLOCK = re.compile(
    r"\b(?:(?P<q>a\s+quarter|half)\s+(?P<rel>past|to)\s+(?P<h1>\w+)"
    r"|(?P<h2>\d{1,2})[:.](?P<m2>\d{2})"
    r"|(?P<h3>\w+)\s+o'?\s*clock)\b",
    re.IGNORECASE,
)


def reaction_span(clause: str) -> tuple[int, int] | None:
    """(start, end) of the conditional reaction: to the next ", and" / ", then" / ";" or the
    end ("charging any enemy horse that falls on it, and then follow it to Plaňany")."""
    m = _REACTION.search(clause)
    if m is None:
        return None
    rest = re.search(r",\s*(?:and\s+)?then\b|,\s*and\b|;", clause[m.end() :])
    return m.start(), (m.end() + rest.start()) if rest else len(clause)


def follow_ahead(text: str) -> bool:
    return bool(_FOLLOW_AHEAD.search(text))


def own_guns(text: str) -> bool:
    """ "your six guns", "his guns": a brigade's own battalion guns."""
    return bool(_OWN_GUNS.search(text))


def artillery_named(text: str) -> bool:
    """ "the heavy artillery", "the batteries", "the heavy guns", the artillery commander."""
    return bool(_ARTILLERY_PROPER.search(text))


def clock_minute(text: str, start: str) -> float | None:
    """The sim minute of a clock phrase ("until a quarter to seven", "at 15:30", "at four
    o'clock"), afternoon hours read after `start` ("13:00"); None when there is none."""
    if not start:
        return None
    m = _CLOCK.search(text)
    if m is None:
        return None
    h0, m0 = (int(v) for v in start.split(":"))

    def hour(w: str) -> int | None:
        w = w.lower()
        return int(w) if w.isdigit() else _NUMBERS.get(w)

    if m.group("q"):
        h = hour(m.group("h1"))
        if h is None:
            return None
        frac = 15 if m.group("q").lower().startswith("a") else 30
        mins = (h * 60 + frac) if m.group("rel").lower() == "past" else (h * 60 - frac)
    elif m.group("h2"):
        mins = int(m.group("h2")) * 60 + int(m.group("m2"))
    else:
        h = hour(m.group("h3"))
        if h is None:
            return None
        mins = h * 60
    t0 = h0 * 60 + m0
    while mins < t0 and mins + 12 * 60 < 24 * 60:  # "seven" in an afternoon is 19:00
        mins += 12 * 60
    return float(mins - t0) if mins >= t0 else None


def fold(text: str) -> str:
    s = unicodedata.normalize("NFKD", text)
    s = "".join(c for c in s if not unicodedata.combining(c))
    return s.replace("’", "'").replace("‘", "'").casefold()


@dataclass(frozen=True)
class Tok:
    w: str  # folded
    start: int  # span in the original text
    end: int


def toks(text: str) -> list[Tok]:
    """Folded word tokens with their spans; "Hülsen's" gives "hulsen", "s"."""
    return [
        Tok(p.group(), m.start(), m.end())
        for m in re.finditer(r"[^\W_]+", text)
        for p in re.finditer(r"[a-z0-9]+", fold(m.group()))
    ]


def words(text: str) -> list[str]:
    return [t.w for t in toks(text)]


def _lev1(a: str, b: str) -> bool:
    """Edit distance at most one."""
    if a == b:
        return True
    if abs(len(a) - len(b)) > 1:
        return False
    if len(a) > len(b):
        a, b = b, a
    i = 0
    while i < len(a) and a[i] == b[i]:
        i += 1
    if len(a) == len(b):
        return a[i + 1 :] == b[i + 1 :]
    return a[i:] == b[i + 1 :]


def same_word(a: str, b: str) -> bool:
    if a == b:
        return True
    if min(len(a), len(b)) < 6:
        return False
    return _lev1(a, b)


def variant(name: str) -> tuple[str, ...]:
    w = words(name)
    while w and w[0] == "the":
        w = w[1:]
    return tuple(w)


def find(ws: list[str], v: tuple[str, ...], start: int = 0) -> list[int]:
    n = len(v)
    if not n:
        return []
    return [
        i
        for i in range(start, len(ws) - n + 1)
        if all(same_word(ws[i + j], v[j]) for j in range(n))
    ]


def surnames(commander: str) -> list[str]:
    """The words a general is called by: "Generalmajor von Katte" -> katte, "Moritz of
    Anhalt-Dessau" -> moritz, dessau; titles and generic words dropped."""
    c = re.sub(r"\(.*?\)", " ", commander)
    w = [x for x in words(c) if not re.fullmatch(r"[ivx]+", x)]
    out: list[str] = []
    if "von" in w and w.index("von") + 1 < len(w):
        out.append(w[w.index("von") + 1])
    if "of" in w and w.index("of") > 0:
        out.append(w[w.index("of") - 1])
    if w:
        out.append(w[-1])
    return [
        x
        for x in dict.fromkeys(out)
        if len(x) >= 4 and x not in _TITLES and x not in _GENERIC_PEOPLE
    ]


@dataclass
class Mention:
    key: str  # formation id or feature name
    i: int  # first token
    j: int  # one past the last token
    proper: bool = True  # False for an arm word alone ("the cavalry")


@dataclass
class Lexicon:
    """What the side's names look like in folded words."""

    sv: SideView
    forms: dict[str, list[tuple[tuple[str, ...], bool]]] = field(default_factory=dict)
    feats: dict[str, list[tuple[str, ...]]] = field(default_factory=dict)
    friendly_words: set[str] = field(default_factory=set)
    feature_words: set[str] = field(default_factory=set)

    def __post_init__(self) -> None:
        for f in self.sv.formations:
            vs: list[tuple[tuple[str, ...], bool]] = []
            for n in [f.name, *f.aliases, re.sub(r"\(.*?\)", " ", f.commander or "")]:
                v = variant(n)
                if v and len(v) == 1 and v[0] in ROLE_WORDS and n != f.commander:
                    vs.append((v, False))  # "the Reserve": a role, addressed like an arm word
                elif v and not (len(v) == 1 and v[0] in _TITLES):
                    vs.append((v, not set(v) <= _ARM_ONLY))
            vs += [((s,), True) for s in surnames(f.commander or "")]
            self.forms[f.id] = list(dict.fromkeys(vs))
            for v, proper in vs:
                if proper:
                    self.friendly_words.update(x for x in v if x not in _ARM_ONLY)
        for name in self.sv.feature_names:
            vs2 = [variant(n) for n in [name, *self.sv.feature_aliases.get(name, [])]]
            self.feats[name] = [v for v in dict.fromkeys(vs2) if v]
            for v in self.feats[name]:
                self.feature_words.update(v)
        # own side words: the side's row and every demonym in its own names and aliases
        own_names = {w for f in self.sv.formations for n in [f.name, *f.aliases] for w in words(n)}
        self.own_words = DEMONYMS.get(fold(self.sv.side), set()) | (own_names & ALL_DEMONYMS)
        self.enemy_adj = ENEMY_ADJ | (ALL_DEMONYMS - self.own_words)
        self.enemy_nouns = NOUN_DEMONYMS - self.own_words
        # train words name the enemy's wagons unless the side has a train of its own
        self.enemy_train = TRAIN_WORDS - own_names

    def feature_tokens(self, ws: list[str]) -> set[int]:
        """Token indices inside a feature's name ("the imperial road", "the French ridge")."""
        return {i for m in self._best(ws, self.feats, False) for i in range(m.i, m.j)}

    # -- mentions ------------------------------------------------------------

    def _best(self, ws: list[str], table: dict, proper_only: bool) -> list[Mention]:
        """Non-overlapping mentions, longest first."""
        cands: list[Mention] = []
        for key, vs in table.items():
            for item in vs:
                v, proper = item if isinstance(item[0], tuple) else (item, True)
                if proper_only and not proper:
                    continue
                cands.extend(Mention(key, i, i + len(v), proper) for i in find(ws, v))
        cands.sort(key=lambda m: (-(m.j - m.i), m.i))
        taken: set[int] = set()
        out: list[Mention] = []
        for m in cands:
            if taken & set(range(m.i, m.j)):
                continue
            taken.update(range(m.i, m.j))
            out.append(m)
        return sorted(out, key=lambda m: m.i)

    def formations_in(self, text: str, proper_only: bool = True) -> list[Mention]:
        return self._best(words(text), self.forms, proper_only)

    def features_in(self, text: str) -> list[Mention]:
        return self._best(words(text), self.feats, False)

    def feature_ref(self, name: str) -> Ref:
        if name in self.sv.places:
            return Ref(RefKind.POINT, name, self.sv.places[name])
        if name in self.sv.offsets:
            return Ref(RefKind.POINT, name, self.sv.offsets[name])
        return Ref(RefKind.FEATURE, name)

    def formation(self, fid: str) -> FormationView:
        return next(f for f in self.sv.formations if f.id == fid)

    def arm_of(self, f: FormationView) -> Arm | None:
        if f.arm is not None:
            return f.arm
        arms = {ARM_OF_WORD[w] for v, _ in self.forms.get(f.id, []) for w in v if w in ARM_OF_WORD}
        return arms.pop() if len(arms) == 1 else None

    def ancestors(self, fid: str) -> list[str]:
        by = {f.id: f for f in self.sv.formations}
        out, p = [], by[fid].parent if fid in by else None
        while p is not None and p in by and p not in out:
            out.append(p)
            p = by[p].parent
        return out

    def subject_at_start(self, clause: str) -> str | None:
        """The formation an order clause opens with ("Krosigk's reserve waits ...",
        "General Normann, ..."), proper names and arm aliases alike."""
        subs = self.subjects_at_start(clause)
        return subs[0] if subs else None

    def subjects_at_start(self, clause: str) -> list[str]:
        """The formations an order clause opens with, joined by "and" ("Krosigk's reserve and
        Normann's dragoons are to be in support"); "the commander of the heavy artillery"
        opens with the heavy artillery."""
        ws = words(clause)
        k = 0
        while k < len(ws) and ws[k] in _OPENING_SKIP:
            k += 1
        if ws[k : k + 2] == ["commander", "of"]:
            k += 2
            while k < len(ws) and ws[k] in _OPENING_SKIP:
                k += 1
        ms = self._best(ws, self.forms, False)
        tk = toks(clause)
        out: list[str] = []
        anded = False
        last_end = 0
        at = k
        while True:
            m = next((m for m in ms if m.i == at), None)
            if m is None and at == k:
                # "General Ashby, ..." when the roll says "General Ashby": the title that
                # the opening skipped is part of the name, so the mention starts before `at`
                m = next((m for m in ms if m.i < at < m.j), None)
            if m is None:
                break
            out.append(m.key)
            at = m.j
            last_end = tk[m.j - 1].end
            if at < len(ws) and ws[at] == "s":
                at += 1
            sep = clause[tk[at - 1].end : tk[at].start] if at < len(ws) else ""
            if at < len(ws) and ws[at] == "and":
                anded = True
                at += 1
            elif "," in sep:  # "Gunby, Ford and Campbell, withdraw"
                pass
            else:
                break
            while at < len(ws) and ws[at] in {"the", "general", "generalmajor"}:
                at += 1
        # a list joined by commas alone is a list only when it is closed by a comma
        # ("Fischer, Royal Dragons and Thianges, withdraw"), not an apposition
        # ("Zieten, the hussars will ...")
        if len(out) > 1 and not anded and not clause[last_end:].lstrip().startswith(","):
            out = out[:1]
        return list(dict.fromkeys(out))

    def grammatical_subjects(self, clause: str) -> list[str]:
        """The clause's subject: the formations it opens with, else a formation named
        mid-clause and followed at once by a verb of command ("At once, Hülsen will ...")."""
        subs = self.subjects_at_start(clause)
        if subs:
            return subs
        ws = words(clause)
        for m in self._best(ws, self.forms, True):
            prev = ws[m.i - 1] if m.i > 0 else ""
            if ws[max(0, m.i - 2) : m.i] == ["at", "once"]:
                prev = ""
            if prev in REFERENCE_WORDS or prev in PLACE_PREPS or prev in SUPPORT_VERBS:
                continue
            if ws[m.j : m.j + 1] and ws[m.j] in _MODALS:
                return [m.key]
        return []

    def descendants(self, fid: str) -> set[str]:
        return {f.id for f in self.sv.formations if fid in self.ancestors(f.id)}

    def with_group(self, clause: str) -> set[str]:
        """Formations named by proper name after "with" ("with Prince Franz and Pannwitz at
        the head"): they go with the addressee, they are not addressed."""
        ws = words(clause)
        ms = self._best(ws, self.forms, True)
        out: set[str] = set()
        for i, w in enumerate(ws):
            if w != "with":
                continue
            at = i + 1
            while at < len(ws) and ws[at] in {"the", "general", "generalmajor"}:
                at += 1
            while True:
                m = next((m for m in ms if m.i == at), None)
                if m is None:
                    break
                out.add(m.key)
                at = m.j
                if at < len(ws) and ws[at] == "and":
                    at += 1
                else:
                    break
        # "..., Prince Franz and Pannwitz at the head, ...": named as the head of the march
        chain: list[str] = []
        for m in ms:
            chain = [*chain, m.key] if chain and ws[m.i - 1 : m.i] == ["and"] else [m.key]
            if ws[m.j : m.j + 3] in (["at", "the", "head"], ["in", "the", "lead"]) or ws[
                m.j : m.j + 2
            ] == ["in", "front"]:
                out.update(chain)
        return out

    def back_reference(self, clause: str) -> bool:
        """A third-person pronoun for the addressee ("will cover him", "to his support"): the
        clause tells the addressee about others, it does not order them."""
        return bool({"him", "his"} & set(words(clause)))

    def only_referenced(self, text: str, fid: str) -> bool:
        """Every mention of the formation by name is a reference, not an address: after a
        word such as "on", "behind", "support", "while" (REFERENCE_WORDS)."""
        ws = words(text)
        ms = [m for m in self._best(ws, self.forms, True) if m.key == fid]
        if not ms:
            return False
        for m in ms:
            k = m.i - 1
            while k >= 0 and ws[k] in {"the", "general", "generalmajor", "that"}:
                k -= 1
            if k < 0 or ws[k] not in REFERENCE_WORDS:
                return False
        return True

    def arm_addressee(self, word: str, arm: Arm) -> str | None:
        """The one formation an arm word stands for: a name or alias of that arm containing the
        word, an alias that is the word itself first, then the highest level."""
        best: tuple | None = None
        for f in self.sv.formations:
            if f.level == "army" or self.arm_of(f) != arm:
                continue
            for v, _ in self.forms[f.id]:
                if not any(same_word(x, word) for x in v):
                    continue
                rank = (len(v) == 1, LEVEL_RANK.get(f.level, 0), -len(v))
                if best is None or rank > best[0]:
                    best = (rank, f.id)
        return best[1] if best else None

    # -- enemies -------------------------------------------------------------

    def enemy_phrases(self, text: str) -> list[tuple[str, Arm | None, str | None]]:
        """Enemy bodies the text plainly names: (quoted phrase, arm or None, feature name of
        the place it is said to be at, or None)."""
        tk = toks(text)
        ws = [t.w for t in tk]
        adj = self.enemy_adj
        noun_demonyms = self.enemy_nouns
        in_feature = self.feature_tokens(ws)
        in_friend = {i for m in self._best(ws, self.forms, True) for i in range(m.i, m.j)}
        found: list[tuple[int, int, Arm | None]] = []
        i = 0
        while i < len(ws):
            w = ws[i]
            hit = None
            if i in in_feature or i in in_friend:
                pass  # "the imperial road", "the French ridge", our own "the train"
            elif w in adj:
                j = i + 1
                if j < len(ws) and ws[j] == "s":
                    j += 1
                for k in range(j, min(j + 3, len(ws))):
                    if ws[k] in ENEMY_NOUNS and k not in in_feature and k not in in_friend:
                        arm = Arm.TRAIN if ws[k] in TRAIN_WORDS else ARM_OF_WORD.get(ws[k])
                        hit = (i, k + 1, arm)
                        break
                if hit is None and w in noun_demonyms:
                    hit = (i, i + 1, Arm.INFANTRY if w in _OLD_NOUNS else None)
            elif w in noun_demonyms:
                hit = (i, i + 1, Arm.INFANTRY if w in _OLD_NOUNS else None)
            elif w in self.enemy_train and i > 0 and ws[i - 1] in {"the", "his", "any"}:
                hit = (i, i + 1, Arm.TRAIN)  # "fall on the train": the enemy's wagons
            elif (
                i + 2 < len(ws)
                and ws[i + 1] == "s"
                and ws[i + 2] in ENEMY_NOUNS
                and w not in self.friendly_words
                and w not in self.feature_words
                and w not in ENEMY_ADJ
                and text[tk[i].start : tk[i].start + 1].isupper()
            ):
                hit = (i, i + 3, ARM_OF_WORD.get(ws[i + 2]))
            if hit:
                a, b, arm = hit
                if a > 0 and ws[a - 1] in {"the", "any", "an", "a"}:
                    a -= 1
                found.append((a, b, arm))
                i = b
            else:
                i += 1
        out: list[tuple[str, Arm | None, str | None]] = []
        feats = self._best(ws, self.feats, False)
        for a, b, arm in found:
            place, end = None, b
            for m in feats:
                if b <= m.i <= b + 6 and any(ws[x] in PLACE_PREPS for x in range(b, m.i)):
                    place, end = m.key, m.j
                    break
            out.append((text[tk[a].start : tk[end - 1].end], arm, place))
        return out

    def enemy_known(self, arm: Arm | None, place: str | None) -> str | None:
        """The name of the first known body that fits (arm and place, where given)."""
        place_vs = self.feats.get(place, []) if place else []
        for e in self.sv.enemies:
            if arm is not None and e.arm is not None and e.arm != arm:
                continue
            if place_vs and not any(find(words(e.name), v) for v in place_vs):
                continue
            return e.name
        return None

    def unknown_enemy(self, text: str) -> str | None:
        for phrase, arm, place in self.enemy_phrases(text):
            if arm == Arm.TRAIN:
                continue  # an unseen train is what a raid looks for, not a reason to halt
            if self.enemy_known(arm, place) is None:
                return phrase
        return None

    def known_enemy_at(self, text: str) -> str | None:
        """The known body the words name at a place ("the enemy troops on Křečhoř heights")."""
        for _phrase, arm, place in self.enemy_phrases(text):
            if place is not None:
                hit = self.enemy_known(arm, place)
                if hit is not None:
                    return hit
        return None

    # -- patterns of compound orders -------------------------------------------

    def _friendly_after(self, ws: list[str], i: int, f: FormationView, span: int = 4) -> str | None:
        excl = {f.id, *self.ancestors(f.id)}
        for m in self._best(ws, self.forms, True):
            if m.key not in excl and i <= m.i <= i + span:
                return m.key
        return None

    def flank_guard(self, text: str, f: FormationView) -> str | None:
        """ "keep X on Y's left", "cover Y's flank", "on the left of Y": Y."""
        ws = words(text)
        excl = {f.id, *self.ancestors(f.id)}
        ms = [m for m in self._best(ws, self.forms, True) if m.key not in excl]
        for m in ms:
            nxt = ws[m.j : m.j + 2]
            if nxt[:1] == ["s"] and nxt[1:] and nxt[1] in {"left", "right", "flank", "flanks"}:
                before = ws[max(0, m.i - 3) : m.i]
                if {"on", "upon", "cover", "covering", "guard", "protect", "watch"} & set(before):
                    return m.key
            prev = ws[max(0, m.i - 4) : m.i]
            if (
                prev[-1:] == ["of"]
                and {"left", "right", "flank"} & set(prev)
                and ({"on", "upon", "cover", "covering", "guard", "protect", "watch"} & set(prev))
            ):
                return m.key
        return None

    def support_subject(self, text: str, f: FormationView) -> str | None:
        """The friendly formation a "support" order names: the one after a support word, else
        the only one named."""
        ws = words(text)
        for i, w in enumerate(ws):
            if w in SUPPORT_VERBS:
                k = self._friendly_after(ws, i + 1, f)
                if k:
                    return k
        g = self.flank_guard(text, f)
        if g:
            return g
        excl = {f.id, *self.ancestors(f.id)}
        names = {m.key for m in self._best(ws, self.forms, True) if m.key not in excl}
        return names.pop() if len(names) == 1 else None

    def march_to_and(self, text: str) -> tuple[str, str] | None:
        """ "march (with all speed) to X and <verb> ...": (feature X, verb)."""
        ws = words(text)
        feats = self._best(ws, self.feats, False)
        for i, w in enumerate(ws):
            if w not in MOVE_VERBS:
                continue
            for k in range(i + 1, min(i + 14, len(ws))):
                if ws[k] != "to":
                    continue
                m = next((m for m in feats if k + 1 <= m.i <= k + 2), None)
                if m is None:
                    continue
                rest = ws[m.j : m.j + 3]
                if "and" in rest:
                    a = m.j + rest.index("and") + 1
                    while a < len(ws) and ws[a] in {"there", "then", "at", "once"}:
                        a += 1
                    if ws[a : a + 2] == ["back", "up"]:
                        return m.key, "support"
                    if a < len(ws):
                        return m.key, ws[a]
        return None

    def flank_attack(self, text: str) -> tuple[bool, str | None, str | None]:
        """ "take Y in flank", "fall on the flank of Y": (found, feature Y or None, feature of
        the way "past/round X" before it or None)."""
        ws = words(text)
        feats = self._best(ws, self.feats, False)
        at = None
        for i, w in enumerate(ws):
            if w not in FLANK_VERBS:
                continue
            seg = ws[i + 1 : i + 10]
            if "flank" not in seg:
                continue
            k = i + 1 + seg.index("flank")
            pre = ws[i + 1 : k]
            if (
                pre[-1:] == ["in"]
                or pre[-2:] == ["in", "the"]
                or ({"on", "upon", "against", "into"} & set(pre))
            ):
                at = (i, k)
                break
        if at is None:
            return False, None, None
        i, k = at
        target = next((m.key for m in feats if i < m.i < k or k < m.i <= k + 3), None)
        way = None
        for m in feats:
            if m.i < i and m.i > 0 and ws[m.i - 1] in ROUTE_PREPS - {"along"}:
                way = m.key
        return True, target, way

    def follow_subject(
        self, text: str, f: FormationView, skip: set[str] = frozenset()
    ) -> str | None:
        """The friendly formation a follow or support order names, the formation itself, its
        ancestors and `skip` (co-addressees) aside: after a support word first, else the only
        one named."""
        ws = words(text)
        excl = {f.id, *self.ancestors(f.id), *skip}
        ms = [m for m in self._best(ws, self.forms, True) if m.key not in excl]
        for i in range(len(ws) - 1):  # "keep closed up on Pannwitz" names the one to follow
            if ws[i : i + 2] == ["up", "on"]:
                k = next((m.key for m in ms if i + 2 <= m.i <= i + 4), None)
                if k:
                    return k
        for i, w in enumerate(ws):
            if w in SUPPORT_VERBS:
                k = next((m.key for m in ms if i + 1 <= m.i <= i + 5), None)
                if k:
                    return k
        g = self.flank_guard(text, f)
        if g and g not in excl:
            return g
        names = {m.key for m in ms}
        if len(names) == 1:
            return names.pop()
        if not names:
            # "the brigade battery follows the hussars": a formation named by its arm alias
            # right after a follow word, when no proper name is given
            arm_ms = [
                m for m in self._best(ws, self.forms, False) if not m.proper and m.key not in excl
            ]
            for i, w in enumerate(ws):
                if w in SUPPORT_VERBS or w in {"follows", "supports", "joins"}:
                    k = next((m.key for m in arm_ms if i + 1 <= m.i <= i + 2), None)
                    if k:
                        return k
        return None

    def stand_behind(self, text: str, f: FormationView) -> str | None:
        """ "to stand north of Bříství and behind Hülsen", "take post behind Manstein's
        brigade": the friendly formation the formation is to stand behind (the last named)."""
        ws = words(text)
        if not STATION_VERBS & set(ws):
            return None
        excl = {f.id, *self.ancestors(f.id)}
        ms = [m for m in self._best(ws, self.forms, True) if m.key not in excl]
        out = None
        for i, w in enumerate(ws):
            if w == "behind":
                k = next((m.key for m in ms if i + 1 <= m.i <= i + 3), None)
                if k:
                    out = k
        return out

    def attack_object(self, text: str) -> str | None:
        """The place an attack verb takes as its object ("carry the village of Bříství,
        driving out the enemy infantry there"): the feature named first after the verb, before
        any enemy body; a place gone round or past on the way is no object."""
        ws = words(text)
        feats = self._best(ws, self.feats, False)
        friends = self._best(ws, self.forms, False)
        adj = self.enemy_adj
        for i, w in enumerate(ws):
            if w not in ATTACK_VERBS or _NEGATIONS & set(ws[max(0, i - 5) : i]):
                continue  # "no brigade ... attacking before it is east of X" forbids
            for k in range(i + 1, min(i + 9, len(ws))):
                if any(m.i == k for m in friends):
                    break  # "take the hussars ...": the verb's object is our own
                m = next((m for m in feats if m.i == k), None)
                if m is not None:  # a place first: "bombard the French ridge"
                    if ws[k - 1] in ROUTE_PREPS:
                        break
                    return m.key
                if ws[k] in adj:
                    break
            else:
                continue
            break
        return None

    def trigger_place(self, text: str) -> str | None:
        """The place named in the words of a trigger ("as soon as Hülsen holds Křečhoř",
        "once Manstein's brigade has passed Zlaté Slunce"): the first feature after the cue."""
        ws = words(text)
        feats = self._best(ws, self.feats, False)
        for i in self._cues(ws):
            m = next((m for m in feats if i < m.i <= i + 10), None)
            if m is not None:
                return m.key
            # "once Hülsen holds the village": the place last named before the cue
            if {"village", "wood", "heights", "hill", "it", "place", "town", "crest"} & set(
                ws[i + 1 : i + 10]
            ):
                before = [m for m in feats if m.j <= i]
                if before:
                    return before[-1].key
        return None

    @staticmethod
    def _cues(ws: list[str]) -> list[int]:
        out = []
        for i, w in enumerate(ws):
            cue = w in {"once", "until", "till", "when", "after"} or ws[i : i + 3] == [
                "as",
                "soon",
                "as",
            ]
            if cue and ws[max(0, i - 1) : i + 1] != ["at", "once"]:
                out.append(i)
        return out

    def trigger_subject(self, text: str, f: FormationView) -> str | None:
        """The friendly formation the words of a trigger name ("as soon as Prince Franz's and
        Ingersleben's brigades strike", "until the grenadiers reach him"): the first named
        after the cue, the formation itself and its superiors aside."""
        ws = words(text)
        excl = {f.id, *self.ancestors(f.id)}
        ms = [m for m in self._best(ws, self.forms, False) if m.key not in excl]
        for i in self._cues(ws):
            m = next((m for m in ms if i < m.i <= i + 6), None)
            if m is not None:
                return m.key
        return None

    def hold_object(self, text: str) -> str | None:
        """ "hold Bříští ... until ...", "hold the village of Křečhoř firmly until ...": the
        place to hold, when the words hold it until something."""
        ws = words(text)
        if not {"until", "till"} & set(ws):
            return None
        feats = self._best(ws, self.feats, False)
        for i, w in enumerate(ws):
            if w in {"hold", "holding", "occupy"}:
                m = next((m for m in feats if i < m.i <= i + 5), None)
                if m is not None and not any(x in {"until", "till"} for x in ws[i : m.i]):
                    return m.key
        return None

    def cover_subject(self, text: str, f: FormationView) -> str | None:
        """ "cover Manstein's brigade", "cover the withdrawal of Prince Franz's brigade": the
        friendly formation to cover."""
        ws = words(text)
        excl = {f.id, *self.ancestors(f.id)}
        ms = [m for m in self._best(ws, self.forms, True) if m.key not in excl]
        for i, w in enumerate(ws):
            if w in {"cover", "covering", "protect", "protecting", "guard", "guarding"}:
                k = next((m.key for m in ms if i + 1 <= m.i <= i + 6), None)
                if k:
                    return k
        return None

    def march_place(self, text: str) -> str | None:
        """The place a march is directed on ("continue the march ... toward Zlaté Slunce"):
        the first feature after "to" or "toward"."""
        ws = words(text)
        for m in self._best(ws, self.feats, False):
            if m.i > 0 and ws[m.i - 1] in {"to", "toward", "towards"}:
                return m.key
            if m.i > 1 and ws[m.i - 2] in {"to", "toward", "towards"} and ws[m.i - 1] == "the":
                return m.key
        return None

    def beyond_place(self, text: str) -> str | None:
        """ "not to be drawn beyond Radovesnice", "no farther than X": X."""
        ws = words(text)
        feats = self._best(ws, self.feats, False)
        for i, w in enumerate(ws):
            if w in {"beyond", "farther", "further", "past"}:
                m = next((m for m in feats if i + 1 <= m.i <= i + 5), None)
                if m is not None:
                    return m.key
        return None

    def hq_destination(self, text: str) -> str | None:
        """Where "the headquarters will ride ... to X" goes: the place after the last "to"
        ("to near X" too), else the last place named."""
        ws = words(text)
        feats = self._best(ws, self.feats, False)
        ok = [m for m in feats if "not" not in ws[max(0, m.i - 4) : m.i]]  # "not to remain at"
        for m in reversed(ok):
            pre = ws[max(0, m.i - 3) : m.i]
            if "to" in pre:
                return m.key
        return ok[-1].key if ok else None


_HQ_PATTERNS = [
    re.compile(  # the headquarters as the subject: "concerned my headquarters only" is not
        r"^\s*(?:and\s+|but\s+)?(?:the|my|our|his majesty's|royal|army)\s+headquarters?\b"
        r".*\b(?:ride|rides|"
        r"riding|move|moves|moving|go|goes|shift|shifts|remove|removes|transfer|"
        r"proceed|proceeds|march|marches|be|is|will|establish|follow|follows)\b"
    ),
    re.compile(r"^\s*headquarters?\b"),
    re.compile(r"\bh\.?q\.?(?!\w)"),
    re.compile(
        r"\bi\s+(?:will|shall|am going to|now)\s+(?:\w+\s+)?(?:move|ride|go|shift|"
        r"transfer|proceed|establish|remove)\b"
    ),
    re.compile(
        r"\b(?:the\s+)?(?:king|feldmarschall|field\s*marshal|commander[- ]in[- ]chief)\s+"
        r"(?:will\s+|shall\s+)?(?:ride|rides|move|moves|go|goes|proceed|proceeds|"
        r"shift|shifts)\b"
    ),
]


def is_hq_clause(clause: str) -> bool:
    """The clause moves the headquarters or the commander himself."""
    s = fold(clause)
    return any(p.search(s) for p in _HQ_PATTERNS)


# -- offset places ---------------------------------------------------------------------------

COMPASS = {
    "north": 0.0,
    "north-east": 45.0,
    "east": 90.0,
    "south-east": 135.0,
    "south": 180.0,
    "south-west": 225.0,
    "west": 270.0,
    "north-west": 315.0,
}
_COMPASS_WORD = {
    **{k: k for k in COMPASS},
    "northeast": "north-east",
    "north east": "north-east",
    "northwest": "north-west",
    "north west": "north-west",
    "southeast": "south-east",
    "south east": "south-east",
    "southwest": "south-west",
    "south west": "south-west",
    "n": "north",
    "ne": "north-east",
    "e": "east",
    "se": "south-east",
    "s": "south",
    "sw": "south-west",
    "w": "west",
    "nw": "north-west",
}
_UNIT_M = {
    "m": 1.0,
    "metre": 1.0,
    "metres": 1.0,
    "meter": 1.0,
    "meters": 1.0,
    "km": 1000.0,
    "kilometre": 1000.0,
    "kilometres": 1000.0,
    "kilometer": 1000.0,
    "kilometers": 1000.0,
    "yard": 0.9144,
    "yards": 0.9144,
    "paces": 0.75,
    "pace": 0.75,
}
_DIR_RE = (
    r"north[- ]?east|north[- ]?west|south[- ]?east|south[- ]?west|north|south|east|west"
    r"|ne|nw|se|sw|n|s|e|w"
)
_SMALL = {
    "a": 1,
    "an": 1,
    "one": 1,
    "two": 2,
    "three": 3,
    "four": 4,
    "five": 5,
    "six": 6,
    "seven": 7,
    "eight": 8,
    "nine": 9,
    "ten": 10,
    "eleven": 11,
    "twelve": 12,
    "fifteen": 15,
    "twenty": 20,
    "thirty": 30,
    "forty": 40,
    "fifty": 50,
}
_FRACTION = {
    "half": 0.5,
    "half a": 0.5,
    "half an": 0.5,
    "a half": 0.5,
    "a quarter of a": 0.25,
    "three quarters of a": 0.75,
    "a third of a": 1 / 3,
    "two thirds of a": 2 / 3,
}
_NUM_RE = (
    r"\d+(?:[.,]\d+)?|"
    + "|".join(re.escape(k) for k in sorted(_FRACTION, key=len, reverse=True))
    + r"|(?:"
    + "|".join(_SMALL)
    + r")(?:[ -](?:hundred|thousand))?(?:\s+and\s+a\s+half)?"
)


def _number(w: str) -> float | None:
    w = w.strip()
    if re.fullmatch(r"\d+(?:[.,]\d+)?", w):
        return float(w.replace(",", "."))
    if w in _FRACTION:
        return _FRACTION[w]
    half = w.endswith(" and a half")
    if half:
        w = w[: -len(" and a half")]
    parts = re.split(r"[ -]", w)
    n = _SMALL.get(parts[0])
    if n is None:
        return None
    if len(parts) == 2:
        n *= {"hundred": 100, "thousand": 1000}[parts[1]]
    return n + (0.5 if half else 0.0)


def offset_places(text: str, sv: SideView) -> dict[str, tuple[float, float]]:
    """Points the order places by a measured distance and compass direction from a named
    feature ("600 m east of Medlar Village", "1.5 km to the north-west of the bridge", "900
    metres NE from Damson Farm"): canonical name -> point, from the feature's anchor in
    `sv.feature_points`. A place the view has no anchor for, a direction without a distance,
    or a distance without a direction gives nothing, so the staff ask as before."""
    if not sv.feature_points:
        return {}
    names: dict[str, str] = {}  # folded name or alias -> canonical feature name
    for name in sv.feature_points:
        names[fold(name)] = name
        for a in sv.feature_aliases.get(name) or []:
            names[fold(a)] = name
    alt = "|".join(re.escape(k) for k in sorted(names, key=len, reverse=True))
    if not alt:
        return {}
    pat = re.compile(
        r"(?<![\w.])(?P<d>"
        + _NUM_RE
        + r")\s*(?P<u>"
        + "|".join(sorted(_UNIT_M, key=len, reverse=True))
        + r")\b\s+(?:to\s+the\s+)?(?P<dir>"
        + _DIR_RE
        + r")(?:ward|wards)?\s+(?:of|from)\s+"
        r"(?:the\s+)?(?P<place>" + alt + r")(?![\w'-])"
    )
    out: dict[str, tuple[float, float]] = {}
    for m in pat.finditer(fold(text)):
        n = _number(m.group("d"))
        if n is None:
            continue
        d = n * _UNIT_M[m.group("u")]
        direction = _COMPASS_WORD[re.sub(r"\s+", " ", m.group("dir"))]
        place = names[m.group("place")]
        if d <= 0:
            continue
        metres = round(d)
        shown = f"{metres / 1000:g} km" if metres >= 1000 and metres % 100 == 0 else f"{metres} m"
        name = f"{shown} {direction} of {place}"
        out[name] = geometry.offset(sv.feature_points[place], COMPASS[direction], d)
    return out


def with_offsets(sv: SideView, text: str) -> SideView:
    """The view with the order's offset places added as point features (names in
    `feature_names`, points in `offsets`); the view itself when the order names none."""
    found = offset_places(text, sv)
    if not found:
        return sv
    return replace(
        sv,
        feature_names=[*sv.feature_names, *[n for n in found if n not in sv.feature_names]],
        offsets={**sv.offsets, **found},
    )


def staff_view(sv: SideView) -> SideView:
    """The side view as the staff reads it: the army root also answers to the headquarters
    and the commander himself (ARMY_ALIASES)."""
    roots = [f.id for f in sv.formations if f.level == "army"] or [
        f.id for f in sv.formations if f.parent is None
    ][:1]
    forms = []
    for f in sv.formations:
        if f.id in roots:
            have = {fold(a) for a in f.aliases}
            extra = [a for a in ARMY_ALIASES if fold(a) not in have]
            forms.append(
                FormationView(
                    f.id, f.name, f.commander, [*f.aliases, *extra], f.level, f.parent, f.arm
                )
            )
        else:
            forms.append(f)
    return replace(
        sv,
        formations=forms,
        feature_names=list(sv.feature_names),
        enemies=list(sv.enemies),
        feature_aliases=dict(sv.feature_aliases),
        places=dict(sv.places),
        march_order=list(sv.march_order),
    )
