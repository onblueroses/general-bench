"""The narrator: what the army headquarters knows, written up as the general's brief, in the
words a 1757 staff would use.

    nar = Narrator(world, meta, objectives, formations, units)   # start-of-day copies
    text = nar.brief(sim.picture("prussia"), "prussia", since=last_brief_minute)

The narrator sees only two things: the `command.Picture` of the side (reports and sightings
that reached the hq, the hq's position, the side's own orders) and the scenario's own-side
data at the start (order of battle, positions at 13:00, objectives). It never reads the live
simulation, so the truth cannot leak into a brief.

The first brief of a side opens with the persona block (`persona(side)`): who the general is,
how this game works (`GAME`, the fixed layer), for a pack whose meta.json sets `rules_sheet`
the rules in numbers (`rules_sheet()`, docs/rules-sheet.md), his situation (the pack's
players.md, or objectives.md verbatim for a pack without one) and his order of battle at the start
(docs/player-prompt.md). Later briefs leave it out; `LLMCommander` sends it as the system prompt
on every call, since the harnesses are one-shot.
"""

from __future__ import annotations

import copy
import datetime as dt
import functools
import math
import re
from pathlib import Path

from . import geometry as geo
from .clock import clock
from .command import Picture, place
from .geometry import POINTS8, bearing_word, dist_words
from .scenario import Meta, unwrap
from .types import (
    Arm,
    Cover,
    Feature,
    FeatureKind,
    Formation,
    GeometryKind,
    Message,
    TaskKind,
    Unit,
)

# ---------------------------------------------------------------------------
# Constants (assumptions)
MAX_WORDS = 6000  # spec brief budget: about 6,000 words
VERBATIM_HOUR_MIN = 60  # older reports than this are summarised (after the first hour)
GROUND_RINGS_M = (1000.0, 2000.0, 3000.0)  # where the ground is described on each bearing
LEVEL_M = 8.0  # an elevation difference under this reads as "level"
HQ_MOVED_M = 500.0  # the update brief repeats the ground when the hq moved this far
CONTACT_REACH_M = 600.0  # "first contact": an enemy body within this of the brigade (or fire)
AT_FEATURE_M = 150.0  # a group of sightings all this close to its place is "at" it, else "near"
FIRST_CONTACT = "first contact with the enemy"
ORDERS_PROMPT = (
    "Your orders? (Each on its own line, beginning with the name of the one it is "
    'for; or "No orders".)'
)
COVER_WORDS = {
    Cover.OPEN: "open fields",
    Cover.ROUGH: "broken ground",
    Cover.WOOD: "wood",
    Cover.VILLAGE: "village",
    Cover.ORCHARD: "orchards",
    Cover.MARSH: "marsh",
    Cover.WATER: "water",
    Cover.ROAD: "the road",
}
KIND_WORDS = {
    FeatureKind.VILLAGE: "village",
    FeatureKind.WOOD: "wood",
    FeatureKind.HEIGHT: "height",
    FeatureKind.RIDGE: "ridge",
    FeatureKind.STREAM: "brook",
    FeatureKind.POND: "pond",
    FeatureKind.ROAD: "road",
    FeatureKind.BRIDGE: "bridge",
    FeatureKind.FARM: "farm or inn",
    FeatureKind.MILL: "mill",
    FeatureKind.CHURCH: "church",
    FeatureKind.FORD: "ford",
    FeatureKind.ENTRY: "road onto the field",
    FeatureKind.EXIT: "way off the field",
}
ARM_WORDS = {
    Arm.INFANTRY: ("infantry", "battalion", "men"),
    Arm.CAVALRY: ("cavalry", "regiment", "sabres"),
    Arm.ARTILLERY: ("artillery", "battery", "guns"),
    Arm.TRAIN: ("train", "wagon body", "drivers"),
}

# The fixed layer of every persona (docs/player-prompt.md): the whole setup, the
# consultation contract, how to write an order the staff can read, and how the field behaves,
# all in words, never in the engine's numbers. Every model reads these exact bytes.
GAME = unwrap("""
How this game works

You are playing a free Kriegsspiel, the officers' war game with an umpire, as the commanding
general of an army of the horse-and-musket age. The ground is real ground, measured and
mapped. Another general commands the enemy; you never meet him and never see his orders. The
marching, fire and shock of both armies are worked out by the same rules for both, and when
the battle is over an umpire judges how far each side has done what it was sent to do. There
are no points to win: what counts is the state of the field and of your army when the day is
done, read against your mission. You are the general of this army. Nothing in it moves except by
your word, and the result is yours and no one else's. Command in earnest and to the best of
your ability: judge the field, form a plan, give the orders that carry it out, and change the
plan when the field changes. The general opposite is doing the same against you.

Your staff and your aides. You command as a general of the period did, by writing.
Everything you write goes to your staff at headquarters. They read it, decide which
formation each line is meant for and what it asks of it, and send it off by aide-de-camp. An
order reaches a formation only when the rider does, and the ride takes time in proportion to
the distance: an order to a wing at the far end of the field may be long on the road, and
the situation it answered may have changed before it arrives. The officer who receives it
acts on it as he understands it, and goes on acting on it until a new order reaches him.
Reports come back the same way, and take as long.

What you know of the field. You see the field only through your brief. It gives the hour;
the reports that have reached headquarters, each with the time it was written and the time
it came in; your own orders and whether their aides have arrived; where each of your
formations stood when it last reported; the enemy, as far as he has been seen by your
officers or from headquarters; and the ground and the named places around headquarters, with
their distances and bearings. There is no map. A report shows where a brigade was when its
commander wrote, not where it is now; an enemy nobody has seen may be anywhere. Your
formation commanders report of their own accord when they first meet the enemy, when they
reach their objective, when a body of theirs breaks, when their losses grow heavy, and
otherwise from time to time. Headquarters sees what can be seen from where it stands. You
may move it ("the headquarters will ride to the church"): that changes what it sees and how
long the aides ride.

When you are asked. Your staff bring you the brief every quarter of an hour of battle time,
and at once when a report of first contact with the enemy, a report that a body of yours has
broken, or a question from the staff reaches headquarters. While you read and write, the
battle stands still: it waits for your answer, however long you take, so there is no reward
for haste and no penalty for care. You may answer with orders or with none. If you write
nothing, or exactly "No orders.", every order already given stands and your troops go on
doing what they were last told.

How to write an order your staff can read. Write each order on its own line, in plain prose,
beginning with the formation or officer it is for: the formation's name as your order of
battle gives it, its commander's surname, or the word you would use for it when only one
formation answers to it ("the cavalry", "the reserve", "the artillery"). Give each line one
formation and one task. A line may carry a second phase after "then", provided the second
phase names its own place or the formation to follow. Name places exactly as your brief
names them. The staff can fix an objective only on a named place, on an enemy body called
exactly as your brief calls it, on one of your own formations, or on "our left flank", "our
right flank", "our centre" or "our rear", or on a point set off from a named place by a
measured distance and a point of the compass ("so far eastward of the village", the distance
stated). A direction without a distance, or a distance from a place your brief does not name,
cannot be found, so name the village, the height or the bridge itself, and give the route as
the named places to pass by ("by way of the bridge").

The staff understand what a general of the period asks: to hold a place, advance to it,
attack it, charge with horse, fall back or withdraw to a place, screen or watch a flank,
bombard with guns, follow or support another formation, rally, and move the headquarters.
They understand the formation to take (column, line, square, skirmish order; guns limbered
or in battery), the manner (carefully, boldly, at all costs), and what to do on meeting the
enemy (halt, engage, press home, fall back). They understand a condition to start ("when the
reserve is up", "once the village is ours", "when the enemy comes into sight", "if any body
on the left breaks", "at a stated hour") and a condition to stop ("hold the bridge until the
train has passed"). They understand a prohibition: not to charge formed infantry, to attack
nothing without a further order, not to pursue, to go no farther than a named place, not to
be drawn into a fight.

What the staff cannot do. They cannot split a formation: an order moves the formation
addressed, and every body under it, as a whole; to use part of a command, address the
smaller formation that holds it. They cannot follow a line that gives several formations
different tasks; give each its own line. They cannot place an objective on a place without a
name or a measured offset from one, nor on an enemy your brief has not shown. They cannot
carry more than one sequel in a line. When they cannot read an order, the formation stays
where it is and the staff ask you;
the question comes back in your next brief, and the answer is a fresh, clearer order. Every
line you write is taken as an order, so write no commentary, no reasoning and no questions
to the umpire. You may ask nothing of the umpire.

How the field behaves. The physics of the day are those of the century, and they are applied
the same way to both armies.
- Marching and fighting tire men and horses. Tired troops move more slowly and fight worse;
  they recover only when halted and out of the fight. Horse at the trot tire quickly, a
  charge at the gallop blows them, and after it they must re-form before they can charge
  again.
- Losses, a repulse, or the sight of a neighbouring body breaking shake a body. Shaken
  troops are disordered and less steady, and a body that has lost heavily breaks and flees.
  A broken body runs from the enemy; it can be rallied only when it is clear of the enemy
  and has had time, it comes back disordered, and troops that have just been repulsed or
  beaten cannot be sent straight back into an attack. An order to rally helps them.
- Troops that fall on a fleeing enemy cut him up, but the pursuit disorders them too, and
  they must re-form before they strike again.
- Infantry march in column, fastest on a road, and deploy into line as they come near a
  known enemy; deploying takes some minutes. A line fires with every musket but moves
  slowly; a column moves well but fires little and suffers more under fire. Musketry decides
  at close range, and fire into a flank or the rear is deadly. Infantry form square of their
  own accord when horse threatens and no friendly horse covers them; a square is proof
  against horse but moves hardly at all and is a fine target for guns.
- Cavalry cannot break a steady square, and seldom a steady line that faces it; a line taken
  in the flank, or already in disorder, can be ridden down. Horse is at its best against
  horse, against troops caught in column or in disorder, and in pursuit.
- Guns move limbered and must unlimber to fire, which takes some minutes; they must limber
  again to move. Roundshot reaches far, canister at close range is murderous, and columns
  and squares suffer most from both. A battery cannot defend itself against infantry close
  up or against horse. Guns keep to roads through marsh and move slowly over broken ground.
  In a long fight ammunition runs low and fire slackens.
- Woods and villages cover their defenders, slow and break up formed troops passing through
  them, and hide what is inside; troops in them are hard to dislodge. Marsh is slow going
  and closed to guns except by the roads. Heights slow those who climb them and give sight
  to those who hold them. Streams and rivers can be crossed only at bridges and fords, and a
  ford may pass foot and horse but not guns or wagons. Roads are the fastest going for every
  arm, above all for guns and wagons.
- Trains of wagons keep to roads and tracks, move slowly and never fight. Formed enemy
  troops that reach them take them; their drivers bolt when hostile horse come near and no
  formed friend is close by.
- The light does not fail in this game. The battle ends at the hour your situation names, or
  earlier when the umpire judges it decided, and what counts is where things stand then.
""")

# The designed packs (mission.json "verdict": "ordinal") have no umpire's verdict: the result
# is read by the rule in the general's orders. GAME_ORDINAL says so, and says that the object is
# the win, in place of GAME's two umpire sentences.
GAME_UMPIRE_SENTENCES = (
    (
        """the battle is over an umpire judges how far each side has done what it was sent to do.
There are no points to win: what counts is the state of the field and of your army when the day is
done, read against your mission.""",
        """the battle is over the result is a win, a draw or a loss by the rule stated in your
orders, and nothing else: the object is the win, and a draw is worth half a win to each side.""",
    ),
    (
        """- The light does not fail in this game. The battle ends at the hour your situation
  names, or earlier when the umpire judges it decided, and what counts is where things
  stand then.""",
        """- The light does not fail in this game. The battle ends when the rule in your orders
  ends it: on a break, at the end hour, or in the play-on your orders describe.""",
    ),
)
GAME_UMPIRE_SENTENCES = tuple((unwrap(o), unwrap(n)) for o, n in GAME_UMPIRE_SENTENCES)
GAME_ORDINAL = GAME
for _old, _new in GAME_UMPIRE_SENTENCES:
    assert _old in GAME_ORDINAL, _old  # GAME is unwrapped: one line per paragraph and item
    GAME_ORDINAL = GAME_ORDINAL.replace(_old, _new)
PERSONA_MAX_WORDS = 3200  # docs/player-prompt.md: the whole persona block, fixed and battle layers
# (the rules sheet, where a pack takes it, is outside this budget and has its own)

# The rules sheet (docs/battles/README.md): the engine's numbers, for the designed packs
# (meta.json "rules_sheet": true); the same bytes for both sides and every model, after GAME and
# before the battle layer. Its HTML comments cite the engine constants and are stripped here.
RULES_SHEET_PATH = Path(__file__).resolve().parents[2] / "docs" / "rules-sheet.md"
RULES_SHEET_MAX_WORDS = 1300
_COMMENT = re.compile(r"[ \t]*<!--.*?-->", re.DOTALL)


def strip_comments(text: str) -> str:
    return _COMMENT.sub("", text)


@functools.cache
def rules_sheet(path: Path = RULES_SHEET_PATH) -> str:
    """The rules sheet as a general reads it: comments stripped, prose unwrapped."""
    return unwrap(strip_comments(path.read_text(encoding="utf-8")).strip())


def takes_rules_sheet(meta: Meta) -> bool:
    """A pack takes the rules sheet only when its meta.json says `"rules_sheet": true`."""
    return (meta.raw or {}).get("rules_sheet") is True


def from_hq(hq: geo.Point, p: geo.Point) -> str:
    d = geo.dist(hq, p)
    if d < 100.0:
        return "at headquarters"
    return f"{dist_words(d)} {bearing_word(geo.bearing(hq, p))} of headquarters"


def _date_words(iso: str) -> str:
    try:
        d = dt.date.fromisoformat(iso)
    except ValueError:
        return iso
    return f"{d.day} {d.strftime('%B')} {d.year}"


def _season_words(meta: Meta) -> str:
    """A pack with no date (meta `season`) states the season and the sunset to five minutes
    instead of a date; other packs say nothing here."""
    season = (meta.raw or {}).get("season")
    if not season:
        return ""
    out = f" on a day in {season}"
    if meta.sunset:
        h, m = (int(v) for v in meta.sunset.split(":"))
        t = (h * 60 + m + 2) // 5 * 5
        out += f"; sunset is at about {t // 60:02d}:{t % 60:02d}"
    return out


def _words(text: str) -> int:
    return len(text.split())


def report_whys(reports: list[Message]) -> dict[str, list[str]]:
    """What each brigade report tells of, as the staff would put it: "first contact with the
    enemy" only when an enemy body is within CONTACT_REACH_M of the brigade or it is engaged
    (the first such report of each brigade); a first sighting farther off is "enemy in sight".
    Reads the reports in the order they reached headquarters."""
    out: dict[str, list[str]] = {}
    met: set[str] = set()
    for m in sorted(reports, key=lambda m: (m.received_at or 0.0, m.id)):
        d = m.data or {}
        if m.kind.value != "report" or "brigade" not in d:
            continue
        whys = [w for w in d.get("why", []) if w != FIRST_CONTACT]
        sights = d.get("sightings", [])
        near = min(
            (s.get("dist", math.inf) for s in sights if not s.get("routed")), default=math.inf
        )
        b = d["brigade"]
        if b not in met and (near <= CONTACT_REACH_M or "we are engaged" in whys):
            met.add(b)
            whys.insert(0, FIRST_CONTACT)
        elif FIRST_CONTACT in d.get("why", []):
            whys.insert(0, "enemy in sight")
        out[m.id] = [w for w in whys if w != "situation report"] or ["situation report"]
    return out


BOT_TAG = re.compile(r"^\[bot(?::[a-z]+)?\] ")


def untagged(text: str) -> str:
    """A doctrine bot tags its orders "[bot:strong] ..." for the log; a general reading them
    in a brief (their own at a decision point, or the last order of a brigade) sees no tag."""
    return BOT_TAG.sub("", text, count=1)


class Narrator:
    def __init__(
        self,
        world,
        meta,
        objectives,
        formations: list[Formation],
        units: list[Unit],
        max_words: int = MAX_WORDS,
    ):
        """`formations` and `units` as at the start (they are copied: the narrator keeps the
        start of the day, never the live state)."""
        self.world = world
        self.meta = meta
        self.objectives = objectives
        self.ordinal = False  # set by build.build for an ordinal pack: GAME_ORDINAL in the persona
        self.max_words = max_words
        self.formations = {f.id: copy.deepcopy(f) for f in formations}
        self.units = {u.id: copy.deepcopy(u) for u in units}
        self._personas: dict[str, str] = {}
        self._briefed: set[str] = set()
        self._last_hq: dict[str, geo.Point] = {}
        self.start = meta.start or "13:00"

    # ------------------------------------------------------------- start of day
    def _bodies(self, fid: str) -> list[Unit]:
        out = [u for u in self.units.values() if u.parent == fid]
        for c in self.formations.values():
            if c.parent == fid:
                out += self._bodies(c.id)
        return sorted(out, key=lambda u: u.id)

    def _start_pos(self, fid: str) -> geo.Point | None:
        f = self.formations.get(fid)
        if f is not None and f.hq is not None:
            return f.hq
        bs = self._bodies(fid)
        return geo.centroid([(u.x, u.y) for u in bs]) if bs else None

    def root(self, side: str) -> Formation:
        return next(
            f
            for f in sorted(self.formations.values(), key=lambda f: f.id)
            if f.side == side and f.parent is None
        )

    def general(self, side: str) -> str:
        return (self.meta.sides.get(side) or {}).get("commander") or self.root(side).commander

    def _strength(self, fid: str) -> str:
        bs = self._bodies(fid)
        parts = []
        for arm in (Arm.INFANTRY, Arm.CAVALRY, Arm.ARTILLERY, Arm.TRAIN):
            group = [u for u in bs if u.arm == arm]
            if not group:
                continue
            word, body, count = ARM_WORDS[arm]
            if arm == Arm.ARTILLERY:
                parts.append(f"{sum(u.guns for u in group)} guns")
            else:
                n = len(group)
                parts.append(
                    f"{word}, {n} {body}{'s' if n != 1 else ''}, "
                    f"{sum(u.men for u in group):,} {count}"
                )
        return "; ".join(parts) or "no troops"

    def order_of_battle(self, side: str) -> str:
        root = self.root(side)
        lines: list[str] = []

        def walk(fid: str, depth: int) -> None:
            f = self.formations[fid]
            p = self._start_pos(fid)
            where = f", {place(self.world, p)}" if p is not None and depth > 0 else ""
            due = [u for u in self._bodies(fid) if u.arrives_at is not None]
            if due:  # bodies that enter the map later, at an entry
                first = min(due, key=lambda u: (u.arrives_at, u.id))
                every = len(due) == len(self._bodies(fid))
                where = (
                    f", {'arriving' if every else f'{len(due)} bodies arriving'} from "
                    f"{clock(self.start, first.arrives_at)} by {first.entry}"
                )
            lines.append(f"{'  ' * depth}- {f.name} ({f.commander}): {self._strength(fid)}{where}.")
            for c in sorted(
                (c for c in self.formations.values() if c.parent == fid), key=lambda c: c.id
            ):
                walk(c.id, depth + 1)

        walk(root.id, 0)
        return "\n".join(lines)

    def persona(self, side: str) -> str:
        """Who the general is, the fixed layer (`GAME`: how this game works), the rules sheet
        when the pack takes it (`takes_rules_sheet`; same bytes for both sides), his situation
        (the pack's players.md section for his side; a pack without one gives his objectives,
        objectives.md verbatim) and his order of battle at the start with its
        commanders. The umpire's questions never come here: players.md is written for the
        player, and objectives.md's Outcome and Umpire sections are not side sections."""
        if side in self._personas:
            return self._personas[side]
        root = self.root(side)
        gen = self.general(side)
        battle = self.meta.battle or "the field"
        when = _date_words(self.meta.date)  # a pack with a season has no date: no "on ..."
        hq = self._start_pos(root.id)
        situation = self.objectives.for_player(side)
        layer = (
            f"Your situation, as your headquarters knows it at {self.start}:\n\n{situation}"
            if situation
            else "Your objectives, in your own words:\n"
            + (self.objectives.for_side(side) or "(none written)")
        )
        text = "\n\n".join(
            x
            for x in [
                (
                    f"You are {gen}, commanding the {root.name} near {battle}"
                    f"{f' on {when}' if when else ''}. "
                    f"It is {self.start}{_season_words(self.meta)}; your headquarters stands "
                    f"{place(self.world, hq) if hq else 'with the army'}."
                ),
                GAME_ORDINAL if self.ordinal else GAME,
                rules_sheet() if takes_rules_sheet(self.meta) else "",
                layer,
                f"Your order of battle at {self.start}, with its commanders and where each stood "
                f"at {self.start}:\n" + self.order_of_battle(side),
            ]
            if x
        )
        self._personas[side] = text
        return text

    # ------------------------------------------------------------- the ground
    def _feature_point(self, f: Feature, hq: geo.Point) -> geo.Point:
        if f.geometry_kind == GeometryKind.POLYLINE:
            return geo.nearest_on_polyline(hq, f.coords)
        return self.world.anchor(f, hq)

    def map_prose(self, hq: geo.Point) -> str:
        w = self.world
        h0 = w.elev(*hq) if w.in_bounds(*hq) else 0.0
        rows = []
        for f in w.features:
            p = self._feature_point(f, hq)
            d = w.feature_distance(hq[0], hq[1], f)
            rows.append((d, f.name, f, p))
        rows.sort(key=lambda r: (r[0], r[1]))
        lines = []
        for d, _, f, p in rows:
            kind = KIND_WORDS.get(f.kind, f.kind.value)
            alias = next(
                (f" (also {a})" for a in f.aliases if f.name.casefold() not in a.casefold()), ""
            )
            if d < 100.0:
                where = "you are at it"
            elif f.geometry_kind == GeometryKind.POLYLINE:
                where = f"nearest {dist_words(d)} {bearing_word(geo.bearing(hq, p))}"
            else:
                where = f"{dist_words(geo.dist(hq, p))} {bearing_word(geo.bearing(hq, p))}"
            extra = ""
            if f.kind in (FeatureKind.HEIGHT, FeatureKind.RIDGE) and w.in_bounds(*p):
                rel = w.elev(*p) - h0
                extra = (
                    f", {abs(rel):.0f} m {'above' if rel > 0 else 'below'} you"
                    if abs(rel) >= LEVEL_M
                    else ", about your level"
                )
            lines.append(f"- {f.name}{alias}, {kind}: {where}{extra}.")
        return "\n".join(lines)

    def ground_prose(self, hq: geo.Point) -> str:
        w = self.world
        h0 = w.elev(*hq) if w.in_bounds(*hq) else 0.0
        here = COVER_WORDS.get(w.cover(*hq), "open fields") if w.in_bounds(*hq) else "?"
        lines = [f"Where you stand: {here}, {h0:.0f} m above the sea."]
        for k, name in enumerate(POINTS8):
            seen, last = [], None
            for r in GROUND_RINGS_M:
                p = geo.offset(hq, k * 45.0, r)
                if not w.in_bounds(*p):
                    break
                seen.append(f"{COVER_WORDS.get(w.cover(*p), 'open fields')} at {r / 1000:.0f} km")
                last = p
            if not seen:
                lines.append(f"- {name.capitalize()}: the edge of the map.")
                continue
            rel = w.elev(*last) - h0
            slope = (
                "level"
                if abs(rel) < LEVEL_M
                else f"{'rising' if rel > 0 else 'falling'} {abs(rel):.0f} m"
            )
            lines.append(
                f"- {name.capitalize()}: {', '.join(seen)}; the ground {slope} by "
                f"{geo.dist(hq, last) / 1000:.0f} km."
            )
        return "\n".join(lines)

    # ------------------------------------------------------------- the brief
    def _name_of(self, fid: str) -> str:
        if fid in self.formations:
            return self.formations[fid].name
        if fid in self.units:
            return self.units[fid].name
        return fid

    def _ancestors(self, fid: str) -> list[str]:
        out, f = (
            [],
            self.formations.get(fid)
            or (self.formations.get(self.units[fid].parent) if fid in self.units else None),
        )
        if fid in self.units and f is not None:
            out.append(f.id)
        while f is not None and f.parent is not None:
            out.append(f.parent)
            f = self.formations.get(f.parent)
        return out

    def _task_words(self, m: Message, fid: str, hq: bool = True) -> str:
        """The staff's reading of `m` for formation `fid`; without the headquarters' moves
        when `hq` is false."""
        bits = []
        for t in m.tasks:
            if t.formation != fid and fid not in self._descendants(t.formation):
                continue
            if not hq and t.kind == TaskKind.MOVE_HQ:
                continue
            obj = ""
            if t.objective is not None:
                obj = " " + (t.objective.name or "a point")
            bits.append(
                f"{t.kind.value}{obj}"
                + (f", then {t.then.kind.value}" if t.then is not None else "")
            )
        return "; ".join(bits)

    def _descendants(self, fid: str) -> set[str]:
        out: set[str] = set()
        for f in self.formations.values():
            if fid in self._ancestors(f.id):
                out.add(f.id)
        return out

    def own_prose(self, pic: Picture, side: str, start: str, compact: bool = False) -> str:
        hq = pic.hq
        lines = []
        brigades = sorted(
            (
                f
                for f in self.formations.values()
                if f.side == side and any(u.parent == f.id for u in self.units.values())
            ),
            key=lambda f: f.id,
        )
        for b in brigades:
            rep = pic.own.get(b.id)
            if rep is not None:
                p = tuple(rep["position"])
                men = f"{rep['men']:,} men" if rep.get("men") is not None else ""
                if men and rep.get("strength_start"):
                    men = f"{rep['men']:,} of {rep['strength_start']:,} men"
                when = f"reported {clock(start, rep['as_of'])}"
            else:
                p = self._start_pos(b.id)
                men = f"{sum(u.men for u in self._bodies(b.id)):,} men"
                when = f"no report yet; as at {start}"
            where = (
                f"{place(self.world, p)} ({from_hq(hq, p)})"
                if p is not None
                else "position unknown"
            )
            task = ""
            # its own orders, and those to a higher formation that set it a task (not, say,
            # the headquarters' move in an order to the army)
            mine = [
                m
                for m in pic.orders
                if m.recipient == b.id
                or (m.recipient in self._ancestors(b.id) and self._task_words(m, b.id, hq=False))
            ]
            if mine:
                m = mine[-1]
                status = (
                    f"received {clock(start, m.received_at)}"
                    if m.received_at is not None
                    else f"sent {clock(start, m.sent_at)}, still carried"
                )
                tw = self._task_words(m, b.id)
                if compact:
                    task = f" Task: {tw or 'see your order'} ({status})."
                else:
                    task = (
                        f' Last order ({status}): "{untagged(m.text)}"'
                        + (f" (staff: {tw})" if tw else "")
                        + "."
                    )
            lines.append(f"- {b.name} ({b.commander}): {men}, {where}; {when}.{task}")
        return "\n".join(lines)

    def enemy_prose(self, pic: Picture, start: str) -> str:
        """Known enemy bodies, grouped by their stable contact name up to the "(k)" counter
        (the staff offers such bodies as one option too)."""
        if not pic.contacts:
            return "No enemy body is known to headquarters."
        groups: dict[str, list] = {}
        for c in pic.contacts:
            groups.setdefault(re.sub(r" \(\d+\)$", "", c.name), []).append(c)
        rows = []
        for base, cs in groups.items():
            last = max(c.seen_at for c in cs)
            first = min(c.seen_at for c in cs)
            arms = sorted({c.arm or "" for c in cs})
            arm = ", ".join(
                {
                    "infantry": "infantry",
                    "cavalry": "cavalry",
                    "artillery": "guns",
                    "train": "wagons",
                }.get(a, "troops, arm not made out")
                for a in arms
            )
            men = [c.est_men for c in cs if c.est_men and c.arm != "artillery"]
            guns = [c.est_men for c in cs if c.est_men and c.arm == "artillery"]
            size = (
                "; ".join(
                    x
                    for x in [
                        f"about {sum(men):,} men" if men else "",
                        f"about {sum(guns)} guns" if guns else "",
                    ]
                    if x
                )
                or "strength not made out"
            )
            ds = [geo.dist(pic.hq, (c.x, c.y)) for c in cs]
            dirs = []
            for c in sorted(cs, key=lambda c: geo.dist(pic.hq, (c.x, c.y))):
                b = bearing_word(geo.bearing(pic.hq, (c.x, c.y)))
                if b not in dirs:
                    dirs.append(b)
            if len(cs) == 1:
                c = cs[0]
                where = f"{place(self.world, (c.x, c.y))} ({from_hq(pic.hq, (c.x, c.y))})"
                count = "one body"
            else:
                rng = (
                    dist_words(min(ds))
                    if dist_words(min(ds)) == dist_words(max(ds))
                    else f"{dist_words(min(ds))} to {dist_words(max(ds))}"
                )
                where = f"{rng} {' and '.join(dirs[:3])} of headquarters"
                count = f"{len(cs)} bodies"
            fled = sum(c.routed for c in cs)
            seen = (
                clock(start, last)
                if first == last
                else f"{clock(start, first)} to {clock(start, last)}"
            )
            rows.append(
                (
                    -last,
                    base,
                    f"- {base}: {count}, {arm}, {size}; {where}; last seen "
                    f"{seen}" + (f"; {fled} in flight" if fled else "") + ".",
                )
            )
        rows.sort()
        return "\n".join(r[2] for r in rows)

    def sightings_prose(self, sights: list[dict]) -> str:
        """Enemy sightings in a report, grouped by place and arm: "about 6 bodies of
        infantry, some 4,000 men, near Křečhoř heights (2 in flight)"; a body alone keeps its
        place in metres."""
        if not sights:
            return "No enemy in sight."
        w = self.world
        groups: dict[tuple[str, str], list[dict]] = {}
        for x in sorted(sights, key=lambda x: (x.get("dist", 0.0), x.get("key", ""))):
            near = w.nearest_feature_cell(x["x"], x["y"]).name if w.features else ""
            groups.setdefault((near, x.get("arm") or ""), []).append(x)
        bits = []
        for (near, arm), xs in groups.items():
            fled = sum(1 for x in xs if x.get("routed"))
            est = sum(x["est_men"] for x in xs if x.get("est_men"))
            if len(xs) == 1:
                x = xs[0]
                size = f"about {est:,} " if est else ""
                what = arm or "troops"
                if arm == "artillery" and est:
                    size, what = f"{est} ", "guns"
                bits.append(
                    f"{size}{what} {place(w, (x['x'], x['y']))}" + (" (in flight)" if fled else "")
                )
                continue
            f = w.feature(near) if near else None
            at = f is not None and all(
                w.feature_distance(x["x"], x["y"], f) <= AT_FEATURE_M for x in xs
            )
            where = f"{'at' if at else 'near'} {near}" if near else "in the field"
            if arm == "artillery":
                size = f", some {est} guns" if est else ""
                bits.append(
                    f"about {len(xs)} batteries{size}, {where}"
                    + (f" ({fled} in flight)" if fled else "")
                )
                continue
            what = {"infantry": "infantry", "cavalry": "cavalry", "train": "wagons"}.get(
                arm, "troops"
            )
            size = f", some {est:,} men" if est else ""
            bits.append(
                f"about {len(xs)} bodies of {what}{size}, {where}"
                + (f" ({fled} in flight)" if fled else "")
            )
        return "Enemy seen: " + "; ".join(bits) + "."

    def report_text(self, m: Message, whys: list[str] | None, start: str) -> str:
        """A brigade report as the brief gives it: its clock, sender and place, what it tells
        of (`report_whys`) and its sightings grouped; other messages verbatim."""
        d = m.data or {}
        b = self.formations.get(d.get("brigade", ""))
        if whys is None or b is None or "position" not in d or "men" not in d:
            return untagged(m.text)
        pos = tuple(d["position"])
        return (
            f"{clock(start, m.sent_at)}, {b.commander} ({b.name}) {place(self.world, pos)}: "
            f"{'; '.join(whys)}. {self.sightings_prose(d.get('sightings', []))} "
            f"Strength {d['men']:,} of {d.get('start_men', d['men']):,}."
        )

    def _report_line(self, m: Message, start: str, whys: dict | None = None) -> str:
        who = "From your staff" if m.kind.value == "clarification" else "Report"
        text = self.report_text(m, (whys or {}).get(m.id), start)
        return f"- [{who}, received {clock(start, m.received_at or 0)}] {text}"

    def reports_prose(
        self, pic: Picture, since: float, start: str, verbatim_from: float
    ) -> tuple[str, str, str]:
        """(new since the last brief, earlier within the hour verbatim, older summarised)."""
        # a brief at minute s sees what was delivered up to step s-1: received_at <= s-1
        # (a courier arriving at 14.4 is handed over in step 15)
        whys = report_whys(pic.reports)
        new = [m for m in pic.reports if (m.received_at or 0) > since - 1]
        old = [m for m in pic.reports if (m.received_at or 0) <= since - 1]
        recent = [m for m in old if (m.received_at or 0) >= verbatim_from]
        older = [m for m in old if (m.received_at or 0) < verbatim_from]
        new_t = "\n".join(self._report_line(m, start, whys) for m in new) or "None."
        recent_t = "\n".join(self._report_line(m, start, whys) for m in recent)
        by: dict[str, list[Message]] = {}
        for m in older:
            by.setdefault(m.sender, []).append(m)
        summ = []
        for sender in sorted(by, key=self._name_of):
            ms = by[sender]
            if ms[0].kind.value == "clarification":
                summ.append(
                    f"- Your staff asked {len(ms)} question(s) between "
                    f"{clock(start, ms[0].received_at or 0)} and "
                    f"{clock(start, ms[-1].received_at or 0)}; the last: "
                    f'"{untagged(ms[-1].text)}"'
                )
                continue
            told: list[str] = []
            for m in ms:
                for y in whys.get(m.id, m.data.get("why", [])):
                    if y != "situation report" and y not in told:
                        told.append(y)
            summ.append(
                f"- {self._name_of(sender)}: {len(ms)} report(s) received "
                f"{clock(start, ms[0].received_at or 0)} to "
                f"{clock(start, ms[-1].received_at or 0)}"
                + (f"; they told of: {'; '.join(told)}" if told else "")
                + "."
            )
        return new_t, recent_t, "\n".join(summ)

    def orders_prose(
        self, pic: Picture, start: str, verbatim_from: float, since: float | None = None
    ) -> str:
        """Every order with its aides; with `since`, only those still carried or sent or
        received since the last brief (the update brief)."""
        if not pic.orders:
            return "You have sent no orders yet."
        groups: dict[tuple[float, str], list[Message]] = {}
        for m in pic.orders:
            if (
                since is not None
                and m.received_at is not None
                and m.received_at <= since - 1
                and m.sent_at < since
            ):
                continue
            groups.setdefault((m.sent_at, untagged(m.text)), []).append(m)
        if not groups:
            return "Every order has been delivered; none was received since your last brief."
        lines = []
        for (sent, text), ms in groups.items():
            parts = []
            for m in ms:
                st = (
                    f"received {clock(start, m.received_at)}"
                    if m.received_at is not None
                    else "still carried"
                )
                parts.append(f"{self._name_of(m.recipient)} {st}")
            done = all(m.received_at is not None for m in ms)
            shown = (
                text
                if (sent >= verbatim_from or not done)
                else (text if len(text) <= 160 else text[:157] + "...")
            )
            lines.append(f'- {clock(start, sent)}: "{shown}" ({"; ".join(parts)}).')
        return "\n".join(lines)

    def _clock_head(self, pic: Picture, side: str) -> str:
        """The brief's first lines: the clock and where headquarters stands."""
        return (
            f"=== {pic.clock}, {self.general(side)}'s headquarters ===\n"
            f"It is {pic.clock}. Your headquarters is {place(self.world, pic.hq)}."
        )

    def brief(
        self, picture: Picture, side: str, since: int, update: bool = False, notice: str = ""
    ) -> str:
        """The general's brief at `picture.now`. `since` is the minute of his previous brief:
        reports received since then are given verbatim under "New dispatches".

        `update=True` (a general who keeps his conversation) gives, after the first full
        brief, only what is new: the clock, the new dispatches and staff questions, the
        orders still carried or delivered since, and a short standing picture (own troops
        and enemy in one line each); the ground and the named places again only when the
        headquarters has moved more than `HQ_MOVED_M`. `notice` is the umpire's word to the
        general, given under its own heading right after the clock (an ordinal pack's reading
        of the objective in the play-on, `verdict.play_on_notice`)."""
        start = self.start
        pic = picture
        first = side not in self._briefed
        self._briefed.add(side)
        moved = side not in self._last_hq or geo.dist(self._last_hq[side], pic.hq) > HQ_MOVED_M
        self._last_hq[side] = pic.hq
        if update and not first:
            new_t, _, _ = self.reports_prose(pic, float(since), start, -math.inf)
            sections = [
                ("", self._clock_head(pic, side)),
                ("From the umpire", notice),
                ("New dispatches since your last brief", new_t),
                (
                    "Orders on the road or delivered since your last brief",
                    self.orders_prose(pic, start, -math.inf, since=float(since)),
                ),
                (
                    "Standing picture: your own troops, as last reported",
                    self.own_prose(pic, side, start, compact=True),
                ),
                (
                    "Standing picture: the enemy, as known at headquarters",
                    self.enemy_prose(pic, start),
                ),
            ]
            if moved:
                sections += [
                    ("The ground around your new headquarters", self.ground_prose(pic.hq)),
                    ("Named places, nearest first, from headquarters", self.map_prose(pic.hq)),
                ]
            sections.append(("", ORDERS_PROMPT))
            return self._join([(h, b) for h, b in sections if b])
        verbatim_from = (
            -math.inf if pic.now < VERBATIM_HOUR_MIN else float(pic.now - VERBATIM_HOUR_MIN)
        )
        new_t, recent_t, older_t = self.reports_prose(pic, float(since), start, verbatim_from)
        sections: list[tuple[str, str]] = []
        if first:
            sections.append(("", self.persona(side)))
        sections += [
            ("", self._clock_head(pic, side)),
            ("From the umpire", notice),
            ("New dispatches since your last brief", new_t),
            ("Earlier dispatches of the last hour", recent_t),
            ("Older dispatches, in brief", older_t),
            ("Your orders and their aides", self.orders_prose(pic, start, verbatim_from)),
            ("Your own troops, as last reported", self.own_prose(pic, side, start)),
            ("The enemy, as known at headquarters", self.enemy_prose(pic, start)),
            ("The ground around headquarters", self.ground_prose(pic.hq)),
            ("Named places, nearest first, from headquarters", self.map_prose(pic.hq)),
            ("", ORDERS_PROMPT),
        ]
        sections = [(h, b) for h, b in sections if b]
        text = self._join(sections)
        # keep under the budget: drop the farthest named places, then the earlier verbatim
        # dispatches (they are summarised instead)
        while _words(text) > self.max_words:
            i = next((k for k, (h, _) in enumerate(sections) if h.startswith("Named places")), None)
            if i is not None and sections[i][1].count("\n") > 10:
                lines = sections[i][1].split("\n")
                sections[i] = (sections[i][0], "\n".join(lines[: max(10, len(lines) * 3 // 4)]))
            else:
                j = next(
                    (k for k, (h, _) in enumerate(sections) if h.startswith("Earlier dispatches")),
                    None,
                )
                if j is None:
                    break
                lines = sections[j][1].split("\n")
                if len(lines) <= 1:
                    del sections[j]
                else:
                    sections[j] = (sections[j][0], "\n".join(lines[len(lines) // 2 :]))
            text = self._join(sections)
        return text

    @staticmethod
    def _join(sections: list[tuple[str, str]]) -> str:
        return "\n\n".join(f"{h}:\n{b}" if h else b for h, b in sections) + "\n"


__all__ = [
    "CONTACT_REACH_M",
    "GAME",
    "MAX_WORDS",
    "PERSONA_MAX_WORDS",
    "RULES_SHEET_MAX_WORDS",
    "Narrator",
    "report_whys",
    "rules_sheet",
    "strip_comments",
    "takes_rules_sheet",
]
