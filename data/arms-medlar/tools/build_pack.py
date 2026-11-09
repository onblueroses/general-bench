"""Build data/arms-medlar/ (the designed battle Arms) from the numbers below.

    uv run python -I data/arms-medlar/tools/build_pack.py

Writes terrain.npz, features.json, oob.json, deployment.json, meta.json, mission.json,
script.json, players.md and objectives.md; the notes are hand-written. Deterministic: two
builds give identical bytes. docs/battles/README.md (item 3, "Arms'
armies") is the design it implements; design-notes.md gives the reason for every number.

Arms is Plain with two different armies: the ground is Plain's raster, built by Plain's own
`terrain()` (imported from data/plain-crossroads/tools/build_pack.py, so it cannot drift), its
features at Plain's coordinates under new names; the clock, the verdict and the mission words
are Plain's (`kriegsspiel.designed`). The horse army stands west, the foot army east. Each
army is laid out in the west frame and the foot army is turned by 180° about the crossroads,
so both first lines stand 3.5 km from the village and each army's left is the other's right,
as on Plain; the armies themselves are not each other's image.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

from kriegsspiel import designed as d
from kriegsspiel.designed import (
    BN_STEP,
    CX,
    CY,
    EXIT_IN_M,
    EXIT_RADIUS_M,
    FIRST_X,
    REGT_STEP,
    RESERVE_X,
    SECOND_X,
    H,
    W,
)

PACK = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location(
    "plain_build", PACK.parent / "plain-crossroads" / "tools" / "build_pack.py"
)
plain = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(plain)

SIDES = ("horse", "foot")  # oob.json order: the horse army is the first side
PREFIX = {"horse": "H", "foot": "F"}
COLOURS = {"horse": "White", "foot": "Green"}  # the armies' names; the side ids say the arm
VILLAGE_NAME = "Medlar Village"

# --------------------------------------------------------------------------- armies
# the ladder "Arms' armies". (key, name, aliases, kind, quality[, bodies]); quality follows
# Plain's pattern within each arm (design-notes.md, "Quality").
HORSE_ARMY = [
    ("G", "Grenadier brigade", ["the grenadiers", "the grenadier brigade"], "grenadier", 5),
    ("L1", "First brigade", ["the first brigade"], "line", 3),
    ("L2", "Second brigade", ["the second brigade"], "line", 3),
    ("L3", "Third brigade", ["the third brigade"], "line", 3),
    ("N1", "Fourth brigade", ["the fourth brigade"], "line", 2),
    (
        "CU",
        "Cuirassier brigade",
        ["the cuirassiers", "the cuirassier brigade", "the heavy horse"],
        "cuirassier",
        4,
    ),
    (
        "DR1",
        "First Dragoon brigade",
        ["the first dragoons", "the first dragoon brigade"],
        "dragoon",
        3,
    ),
    (
        "DR2",
        "Second Dragoon brigade",
        ["the second dragoons", "the second dragoon brigade"],
        "dragoon",
        3,
    ),
    ("HU1", "First Hussar brigade", ["the first hussars", "the first hussar brigade"], "hussar", 3),
    (
        "HU2",
        "Second Hussar brigade",
        ["the second hussars", "the second hussar brigade"],
        "hussar",
        3,
    ),
    (
        "AR",
        "Horse artillery",
        ["the horse artillery", "the horse guns", "the six-pounders"],
        "horse_battery",
        3,
    ),
]
FOOT_ARMY = [
    ("G", "Grenadier brigade", ["the grenadiers", "the grenadier brigade"], "grenadier", 5),
    ("L1", "First brigade", ["the first brigade"], "line", 3),
    ("L2", "Second brigade", ["the second brigade"], "line", 3),
    ("L3", "Third brigade", ["the third brigade"], "line", 3),
    ("L4", "Fourth brigade", ["the fourth brigade"], "line", 3),
    ("L5", "Fifth brigade", ["the fifth brigade"], "line", 3),
    ("N1", "Sixth brigade", ["the sixth brigade"], "line", 2),
    ("N2", "Seventh brigade", ["the seventh brigade"], "line", 2),
    ("DR", "Dragoon brigade", ["the dragoons", "the dragoon brigade"], "dragoon", 3),
    ("HU", "Hussar brigade", ["the hussars", "the hussar brigade", "the light horse"], "hussar", 3),
    (
        "AR",
        "Reserve artillery",
        ["the reserve artillery", "the reserve guns", "the twelve-pounders"],
        "foot_battery",
        3,
        3,
    ),
]
ARMIES = {"horse": HORSE_ARMY, "foot": FOOT_ARMY}
KEYS = {s: [f[0] for f in ARMIES[s]] for s in SIDES}

# Deployment, west frame (facing east, left = north = +y). Plain's lines, steps and reserve
# line (designed.FIRST_X 500, SECOND_X 250, RESERVE_X 100); a brigade's centres 350 m apart
# (designed.BRIGADE_STEP); a wing brigade's centre 420 m beyond its flank brigade's centre (as
# Plain's: 155 m half a brigade, a 70 m gap, 195 m half a horse brigade).
STEP = d.BRIGADE_STEP
WING = 420.0
# The horse army: three brigades in the first line, a hussar brigade on each wing; second
# line the Fourth (left) and the grenadiers in column (right) behind the gaps, a dragoon
# brigade behind each hussar brigade; behind the centre the cuirassiers and the horse guns.
HORSE_SLOTS = {
    "L1": (FIRST_X, CY + STEP),
    "L2": (FIRST_X, CY),
    "L3": (FIRST_X, CY - STEP),
    "HU1": (FIRST_X, CY + STEP + WING),
    "HU2": (FIRST_X, CY - STEP - WING),
    "N1": (SECOND_X, CY + STEP / 2),
    "G": (SECOND_X, CY - STEP / 2),
    "DR1": (SECOND_X, CY + STEP + WING),
    "DR2": (SECOND_X, CY - STEP - WING),
    "CU": (RESERVE_X, CY),
}
HORSE_BATTERY_Y = (CY + 350.0, CY - 350.0)  # either side of the cuirassiers (CY ± 195)
# The foot army: two lines of four brigades, the hussars on the left wing and the dragoons on
# the right; the grenadiers in column at the right of the second line; behind the centre the
# three batteries.
FOOT_SLOTS = {
    "L1": (FIRST_X, CY + 1.5 * STEP),
    "L2": (FIRST_X, CY + 0.5 * STEP),
    "L3": (FIRST_X, CY - 0.5 * STEP),
    "L4": (FIRST_X, CY - 1.5 * STEP),
    "HU": (FIRST_X, CY + 1.5 * STEP + WING),
    "DR": (FIRST_X, CY - 1.5 * STEP - WING),
    "N1": (SECOND_X, CY + 1.5 * STEP),
    "L5": (SECOND_X, CY + 0.5 * STEP),
    "N2": (SECOND_X, CY - 0.5 * STEP),
    "G": (SECOND_X, CY - 1.5 * STEP),
}
FOOT_BATTERY_Y = (CY + 350.0, CY, CY - 350.0)


def _place(slots: dict, battery_y: tuple):
    def place(key: str, kind: str, i: int) -> tuple[float, float, str]:
        if kind in d.BATTERY_KINDS:
            return RESERVE_X, battery_y[i], "limbered"
        sx, sy = slots[key]
        if kind in d.HORSE_KINDS:
            return sx, sy + (0.5 - i) * REGT_STEP, "line"
        return sx, sy + (0.5 - i) * BN_STEP, ("column" if key == "G" else "line")

    return place


PLACE = {"horse": _place(HORSE_SLOTS, HORSE_BATTERY_Y), "foot": _place(FOOT_SLOTS, FOOT_BATTERY_Y)}


def armies() -> tuple[dict, dict]:
    oob: dict = {"sides": list(SIDES), "formations": [], "units": []}
    dep: dict = {"start": "09:00", "units": {}, "hq": {}}
    for side in SIDES:
        d.add_army(
            oob,
            dep,
            side,
            PREFIX[side],
            COLOURS[side],
            COMMANDERS[side],
            ARMIES[side],
            PLACE[side],
            turn=(side == "foot"),
            source="docs/battles/README.md, Arms' armies (DES)",
        )
    return oob, dep


# the ladder "Arms' armies" points: a horseman two foot, a gun about thirty-five men (its crew in
# the thirty-five, so gunners are not counted again)
def points(oob: dict, side: str) -> int:
    us = [u for u in oob["units"] if u["side"] == side]
    foot = sum(u["men"] for u in us if u["kind"] in ("line", "grenadier"))
    horse = sum(u["men"] for u in us if u["kind"] in d.HORSE_KINDS)
    guns = sum(u.get("guns", 0) + u.get("battalion_guns", 0) for u in us)
    return foot + 2 * horse + 35 * guns


# --------------------------------------------------------------------------- ground
# Plain's raster and Plain's feature geometry, new names.
NAMES = {
    "Teasel Village": VILLAGE_NAME,
    "High road": "Post road",
    "Drove road": "Salt road",
    "Mallow Farm": "Quince Farm",
    "Vetch Farm": "Damson Farm",
    "Yarrow Farm": "Bullace Farm",
    "Burdock Farm": "Pippin Farm",
}


def features() -> list[dict]:
    out = []
    for plain_feature in plain.features():
        f = dict(plain_feature)
        name = NAMES.get(f["name"], f["name"])
        word = name.split()[0]
        if f["kind"] == "village":
            f["aliases"] = [
                "the village",
                "the crossroads",
                f"{word}e Village",
                f"{word} crossroads",
            ]
        elif f["kind"] == "road":
            f["aliases"] = [f"the {name.lower()}"] + (
                ["the main road"] if name == "Post road" else []
            )
        elif f["kind"] == "farm":
            f["aliases"] = [f"{word}e Farm", f"the {word.lower()} farm"]
        elif f["kind"] == "exit":
            road = NAMES[f["road"]]
            w = name.split()[0].lower()
            f["aliases"] = [f"the {w} exit", f"the {road.lower()} {w} exit"]
            f["road"] = road
        f["name"] = name
        out.append(f)
    assert [f["geometry"] for f in out] == [f["geometry"] for f in plain.features()]
    assert {(CX, CY), (EXIT_IN_M, CY), (W - EXIT_IN_M, CY), (CX, H - EXIT_IN_M)} <= {
        tuple(f["geometry"]["coords"][0]) for f in out if f["geometry"]["type"] == "point"
    }
    assert all(f.get("radius_m", EXIT_RADIUS_M) for f in out)
    return out


# --------------------------------------------------------------------------- names
# Invented surnames (three edits apart, no common word, no
# word of a place), none of Plain's or Mirror's; the army's first, then the formations in
# HORSE_ARMY / FOOT_ARMY order.
COMMANDERS = {
    "horse": [
        "Ashdown",
        "Birtwistle",
        "Cradock",
        "Dimmock",
        "Elphick",
        "Fothergill",
        "Grimshaw",
        "Hollins",
        "Ingleby",
        "Jowett",
        "Kershaw",
        "Lumb",
    ],
    "foot": [
        "Merriman",
        "Nettleship",
        "Oxenham",
        "Pashley",
        "Rockliffe",
        "Scattergood",
        "Tunnicliffe",
        "Uttley",
        "Vardy",
        "Wolstenholme",
        "Yeadon",
        "Brocklehurst",
    ],
}
# the ground as each side sees it (the horse army faces east, its left is north)
GROUND = {
    "horse": {
        "own_left": "Quince Farm",
        "own_right": "Pippin Farm",
        "far_left": "Damson Farm",
        "far_right": "Bullace Farm",
        "own_exit": "West exit",
        "far_exit": "East exit",
        "left_exit": "North exit",
        "right_exit": "South exit",
    },
    "foot": {
        "own_left": "Bullace Farm",
        "own_right": "Damson Farm",
        "far_left": "Pippin Farm",
        "far_right": "Quince Farm",
        "own_exit": "East exit",
        "far_exit": "West exit",
        "left_exit": "South exit",
        "right_exit": "North exit",
    },
}


# --------------------------------------------------------------------------- texts, script
def player_templates() -> dict[str, str]:
    """The common template with each army's three paragraphs (who you are, how the army came
    here, the enemy) put in: tools/players_template.md and tools/army_<side>.md."""
    tools = PACK / "tools"
    common = (tools / "players_template.md").read_text()
    out = {}
    for side in SIDES:
        who, came, enemy = (tools / f"army_{side}.md").read_text().strip().split("\n\n")
        out[side] = (
            common.replace("<<who>>", who).replace("<<came>>", came).replace("<<enemy>>", enemy)
        )
    return out


SCRIPT = {  # (clock, text); {KEY} is that formation's commander's surname
    "horse": [
        ("09:00", "{L2}, advance by the post road to Medlar Village, then hold it."),
        ("09:00", "{L1}, advance to Medlar Village left of the second brigade, then hold."),
        ("09:00", "{L3}, advance to Medlar Village right of the second brigade, then hold."),
        ("09:00", "{N1}, follow the first brigade."),
        ("09:00", "{HU1}, cover our left flank."),
        ("09:00", "{HU2}, cover our right flank."),
        ("09:00", "{DR1}, follow {HU1}'s brigade."),
        ("09:00", "{DR2}, follow {HU2}'s brigade."),
        ("09:00", "{CU}, stand in reserve behind the second brigade."),
        ("09:00", "{G}, stay in reserve behind the third brigade."),
        ("09:00", "{AR}, support the second brigade."),
        ("12:00", "{G}, advance to Medlar Village and support the second brigade."),
        ("12:00", "{L2}, hold Medlar Village to the last."),
    ],
    "foot": [
        ("09:00", "{L2}, advance by the post road to Medlar Village, then hold it."),
        ("09:00", "{L3}, advance to Medlar Village right of the second brigade, then hold."),
        ("09:00", "{L1}, advance on the left of the second brigade."),
        ("09:00", "{L4}, advance on the right of the third brigade."),
        ("09:00", "{N1}, follow the first brigade."),
        ("09:00", "{L5}, follow the second brigade."),
        ("09:00", "{N2}, follow the third brigade."),
        ("09:00", "{HU}, cover our left flank."),
        ("09:00", "{DR}, cover our right flank."),
        ("09:00", "{G}, stay in reserve behind the fourth brigade."),
        ("09:00", "{AR}, support the second brigade."),
        ("12:00", "{G}, advance to Medlar Village and support the second brigade."),
        ("12:00", "{L2}, hold Medlar Village to the last."),
    ],
}
SCRIPT_NOTE = (
    "Plain's plan fitted to each army (tools/build_pack.py SCRIPT): the centre brigade "
    "advances on the village by the post road and holds it, the brigades beside it and the "
    "second line follow it up, the horse covers the flanks, the reserve stays behind and the "
    "grenadiers go up to the village at noon. For `script` players, whose orders Jev "
    "translates: stub-mode Jev reads every order as its first option, so a stub game of "
    "scripts checks plumbing only; stub self-play uses the doctrine bot (design-notes.md)."
)
PLAYERS_HEAD = (
    "# Medlar Village: the players' brief\n\n"
    "The persona's battle layer for each side (docs/player-prompt.md), "
    "built by tools/build_pack.py from tools/players_template.md and each army's "
    "tools/army_<side>.md, so that the two sections share the ground, the orders, the "
    "verdict and the clock word for word and differ in the two armies. Under the designed "
    "ladder (docs/battles/README.md, the brief) it carries the verdict, "
    "the clock, the own army with its qualities and the enemy's order of battle in outline, "
    "numbers included. The umpire never reads this file.\n"
)
OBJECTIVES_HEAD = (
    "# Medlar Village: objectives\n\n"
    "Each side's mission in its commander's words, the same for both sides "
    "(tools/objectives_template.md); the generals read it, with the verdict, in "
    "players.md. Designed battle: docs/battles/arms.md.\n"
)
# The umpire reads this section (it is in every recorded Jev request of the games), so its
# words stay as played, the module name `kriegsspiel.mission` (now `verdict`) included.
OBJECTIVES_TAIL = (
    "\n## Umpire (the narrative only)\n\n"
    "Under this pack the umpire narrates and does not rule. The verdict is mechanical: "
    "mission.json is the ordinal verdict above (kriegsspiel.mission.OrdinalJudge), which "
    "ends the battle on a break and reads possession of Medlar Village within musket range "
    "of the crossroads at 16:00 and in the play-on. The umpire's own verdict is kept beside "
    "it as a health number, never as the result. The two armies differ: the White army "
    "(horse) is strong in cavalry, the Green army (foot) in infantry and guns. Name in the "
    "account Medlar Village (the crossroads), the Post road, the Salt road, Quince Farm, "
    "Damson Farm, Bullace Farm, Pippin Farm and the four exits, West, East, North and "
    "South.\n"
    "\n## Outcome (designed battle: none; not shown to commanders)\n\n"
    "No historical outcome. The self-play baseline is in design-notes.md.\n"
)


def main() -> None:
    oob, dep = armies()
    files = {
        "features.json": features(),
        "oob.json": oob,
        "deployment.json": dep,
        "meta.json": d.meta(oob, VILLAGE_NAME, COMMANDERS, "docs/battles/arms.md"),
        "mission.json": d.mission(VILLAGE_NAME),
        "script.json": d.script(SCRIPT, SCRIPT_NOTE, COMMANDERS, GROUND, SIDES, KEYS, COLOURS),
    }
    tools = PACK / "tools"
    texts = {
        "players.md": d.players_md(
            PLAYERS_HEAD, player_templates(), COMMANDERS, GROUND, SIDES, KEYS, COLOURS
        ),
        "objectives.md": d.objectives_md(
            OBJECTIVES_HEAD,
            (tools / "objectives_template.md").read_text(),
            OBJECTIVES_TAIL,
            COMMANDERS,
            SIDES,
        ),
    }
    d.write_pack(PACK, plain.terrain(), files, texts)


if __name__ == "__main__":
    main()
