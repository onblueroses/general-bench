"""Build data/mirror-fords/ (the designed battle Mirror) from the numbers below.

    uv run python -I data/mirror-fords/tools/build_pack.py

Writes terrain.npz, features.json, oob.json, deployment.json, meta.json, mission.json,
script.json, players.md and objectives.md; the notes are hand-written. Deterministic: two
builds give identical bytes. docs/battles/README.md ("Mirror's ground", "Mirror's brook,
re-laid") is the design it implements; design-notes.md gives the reason for every number. The
box, the armies, the deployment, the clock, the verdict and the assembly of the texts are
Plain's (`kriegsspiel.designed`); only the ground and the names are this file's.

Symmetry: every raster layer is built for Red's half and completed by its rotation
(`designed.flip`), every feature is either its own image or has its twin under
(x, y) -> (W - x, H - y), and the deployment is Plain's. The pack test and
tests/kriegsspiel/test_symmetry_mirror.py check it.
"""

from __future__ import annotations

import itertools
from pathlib import Path

import numpy as np

from kriegsspiel import designed as d
from kriegsspiel.designed import CELL, CX, CY, EXIT_IN_M, EXIT_RADIUS_M, NX, NY, W, flip, rot

PACK = Path(__file__).resolve().parents[1]
OPEN, WOOD, VILLAGE, WATER, ROAD = 0, 2, 3, 6, 7  # types.Cover

# --------------------------------------------------------------------------- ground
# The brooks' frame (the ladder, "Mirror's brook, re-laid"): the two brooks lie on the diagonal
# through the village, Curlew Brook running to the north-west corner (0, H) along U, Godwit
# Brook its image to the south-east corner (W, 0). A place is (t, s): t metres along U from the
# village, s metres along N (north-east, Blue's side of the diagonal); Red's ground is s < 0.
# Red's places are given in (t, s); Blue's are their rotation, (-t, -s).
U = (-0.8, 0.6)  # the corner (0, 6000) is the village + 5,000 U: each brook ends in a corner
N = (0.6, 0.8)
ELEV_M = 200.0  # EST: the fields, as Plain
VILLAGE_R_M = 200.0  # EST: as Plain's, some 400 m across, on the dry saddle
HEAD_T = 500.0  # each brook rises 500 m from the village: a dry saddle 1 km wide
# water where |s| <= 25 m beyond the head: on the slant a 4-connected band two to three
# cells deep, with at least 15 m of water on any straight line across it (a lane's 0.75 cell
# would leave 2.5 m, which the router's samples, 8 to 12 m apart on a coarse edge, could
# step over)
STREAM_HALF_M = 25.0
ROAD_HALF_M = 12.5  # an axis-parallel road is one cell wide
LANE_HALF_M = 0.75 * CELL  # a slanting road: every cell its line passes near (4-connected)
FORD_T = 2000.0  # the ladder: each ford two kilometres from the village along its brook
FORD_RADIUS_M = 40.0  # the format's default: the band's water within 40 m of the ford point
# the ladder "passable by all arms but slow": foot and horse wade at the format's half speed,
# guns and wagons at a quarter (EST: limbers and wagons in a stream bed)
FORD_SPEED = {"infantry": 0.5, "cavalry": 0.5, "artillery": 0.25, "train": 0.25}
BANK_S = -100.0  # the Withy road, 100 m off Curlew Brook on Red's side, ford to village
# Red's ridge: a crest parallel to Curlew Brook 600 m on Red's side of it (its rise ends
# 100 m short of the water), from 850 m to 1,850 m along it. Its middle is 1.48 km from the
# village; its near end 1.04 km from the village and 1.30 km from the Curlew Ford, both inside
# a 12-pounder's roundshot (combat.ROUNDSHOT_RANGE_M[12] = 1,400 m); its far end 0.62 km from
# the ford. Its near end stands 30 m north of the High road, which crosses its southern slope
# (the wedge between road and brook is too narrow inside roundshot to hold the rise clear).
RIDGE_S, RIDGE_T0, RIDGE_T1 = -600.0, 850.0, 1850.0
RIDGE_H_M = 25.0  # EST: a low ridge; LOS hides the ground behind it, foot climb at 0.84
RIDGE_HALF_W_M = 500.0  # the rise falls off as cos² over 500 m from the crest
# Red's wood, on its right, beside Godwit Brook: 1.7 km along it (t -2,850 to -1,150) and
# 1.3 km deep (s -1,600 to -300), its edge 300 m short of the water; the Godwit lane runs
# along its far side to Finch Farm and then straight through it to the ford.
WOOD_TS = [
    (-2850.0, -1450.0),
    (-2800.0, -800.0),
    (-2650.0, -300.0),
    (-1350.0, -300.0),
    (-1150.0, -700.0),
    (-1200.0, -1400.0),
    (-1500.0, -1600.0),
    (-2600.0, -1600.0),
]
# Red's two lanes from the High road 500 m in front of its first line (t 2,400, s -1,800):
# to the Curlew Ford past Wren Farm, meeting the water at 53° round the foot of the ridge's
# far end; to the Godwit Ford along the wood's far side to Finch Farm, then square through
# the wood to the water. Blue's lanes are their images.
LANE_FORK = (1000.0, CY)
WREN_TS = (2600.0, -800.0)
FINCH_TS = (-FORD_T, -1800.0)
MILL_TS = (FORD_T + 60.0, -60.0)  # the Curlew Mill on Red's bank 85 m from the ford

VILLAGE_NAME = "Plover Village"


def at(t: float, s: float) -> tuple[float, float]:
    """The map point of (t, s) in the brooks' frame, to the decimetre."""
    return (round(CX + t * U[0] + s * N[0], 1), round(CY + t * U[1] + s * N[1], 1))


CURLEW_FORD = at(FORD_T, 0.0)  # (2,400, 4,200), a cell centre
GODWIT_FORD = rot(*CURLEW_FORD)  # (5,600, 1,800)
WREN, FINCH = at(*WREN_TS), at(*FINCH_TS)


def _frame(gx, gy):
    dx, dy = gx - CX, gy - CY
    return dx * U[0] + dy * U[1], dx * N[0] + dy * N[1]


def _seg_dist(gx, gy, a, b):
    ax, ay, bx, by = a[0], a[1], b[0], b[1]
    vx, vy = bx - ax, by - ay
    t = np.clip(((gx - ax) * vx + (gy - ay) * vy) / (vx * vx + vy * vy), 0.0, 1.0)
    return np.hypot(gx - ax - t * vx, gy - ay - t * vy)


def _poly_dist(gx, gy, coords):
    return np.minimum.reduce([_seg_dist(gx, gy, a, b) for a, b in itertools.pairwise(coords)])


def _inside(gx, gy, poly):
    """Cell centres inside a polygon (even-odd rule)."""
    out = np.zeros(gx.shape, bool)
    for (x0, y0), (x1, y1) in zip(poly, poly[1:] + poly[:1], strict=True):
        cross = (y0 > gy) != (y1 > gy)
        with np.errstate(divide="ignore", invalid="ignore"):
            xi = x0 + (gy - y0) * (x1 - x0) / (y1 - y0)
        out ^= cross & (gx < xi)
    return out


def curlew_brook() -> list[list[float]]:
    """From its head by the village past the Curlew Ford to the north-west corner."""
    return [list(at(HEAD_T, 0.0)), list(CURLEW_FORD), [0.0, d.H]]


def ridge_crest() -> list[list[float]]:
    return [list(at(t, RIDGE_S)) for t in (RIDGE_T0, (RIDGE_T0 + RIDGE_T1) / 2, RIDGE_T1)]


def wood_poly() -> list[tuple[float, float]]:
    return [at(t, s) for t, s in WOOD_TS]


def withy_road() -> list[list[float]]:
    """Red's bank road: from the Curlew Ford along the brook to the village."""
    return [
        list(p) for p in (CURLEW_FORD, at(FORD_T - 100.0, BANK_S), at(HEAD_T, BANK_S), (CX, CY))
    ]


def curlew_lane() -> list[list[float]]:
    """The north lane, Red's fork to Blue's: Red's way to the Curlew Ford, then the image of
    Red's way to the Godwit Ford (Blue's way to the same ford)."""
    red_left = [LANE_FORK, WREN, CURLEW_FORD]
    red_right = [LANE_FORK, FINCH, GODWIT_FORD]
    blue_right = [rot(*p) for p in red_right]
    return [[float(x), float(y)] for x, y in red_left + blue_right[::-1][1:]]


def godwit_lane() -> list[list[float]]:
    return [list(rot(*p)) for p in curlew_lane()]


def terrain() -> dict:
    gx, gy = d.grid()
    t, s = _frame(gx, gy)
    # Red's half of each layer; Blue's is its rotation, so the raster is exactly symmetric
    rise = np.clip(_poly_dist(gx, gy, ridge_crest()) / RIDGE_HALF_W_M, 0.0, 1.0)
    ridge = np.where(rise < 1.0, RIDGE_H_M * np.cos(rise * np.pi / 2) ** 2, 0.0)
    elev = (ELEV_M + ridge + flip(ridge)).astype(np.float32)  # the two never overlap

    wood = _inside(gx, gy, wood_poly())
    lane = _poly_dist(gx, gy, curlew_lane()) <= LANE_HALF_M
    bank = _poly_dist(gx, gy, withy_road()) <= LANE_HALF_M
    brook = (t > HEAD_T) & (np.abs(s) <= STREAM_HALF_M)  # Curlew Brook; Godwit's is its image
    cover = np.full((NY, NX), OPEN, np.uint8)
    cover[wood | flip(wood)] = WOOD
    cover[np.hypot(gx - CX, gy - CY) <= VILLAGE_R_M] = VILLAGE
    # roads after the wood and the village (a lane through a wood stays road); the brooks
    # after the roads, so a road stops at its ford's water
    cover[lane | flip(lane) | bank | flip(bank) | (np.abs(gy - CY) <= ROAD_HALF_M)] = ROAD
    cover[brook | flip(brook)] = WATER
    return d.terrain_arrays(elev, cover)


def features() -> list[dict]:
    pt = d.pt

    def line(coords):
        return {"type": "polyline", "coords": [[round(x, 1), round(y, 1)] for x, y in coords]}

    def pair(name_red: str, name_blue: str, kind: str, geom_red: dict, aliases, **props):
        """A feature on Red's side and its image on Blue's."""
        geom_blue = {
            "type": geom_red["type"],
            "coords": [list(rot(*p)) for p in geom_red["coords"]],
        }
        return [
            {"name": n, "kind": kind, "geometry": g, "aliases": aliases(n), **props}
            for n, g in ((name_red, geom_red), (name_blue, geom_blue))
        ]

    def word_aliases(kind_word: str):
        return lambda n: [
            f"{n.split()[0]}e {kind_word}",
            f"the {n.split()[0].lower()} {kind_word.lower()}",
        ]

    def compass(word: str):  # Curlew's is the north one, Godwit's the south one
        return lambda n: [
            *word_aliases(word)(n),
            f"the {'north' if n.startswith('Curlew') else 'south'} {word.lower()}",
        ]

    out = [
        {
            "name": VILLAGE_NAME,
            "kind": "village",
            "geometry": pt(CX, CY),
            "aliases": ["the village", "the crossroads", "Plovere Village", "Plover crossroads"],
            "radius_m": VILLAGE_R_M,
            "note": "a point at the crossroads of the High road and the two bank roads: "
            "possession is judged within musket range of it (docs/battles/README.md, the "
            "verdict); the houses are the VILLAGE disc of terrain.npz, on the dry saddle "
            "between the heads of the two brooks",
        },
        {
            "name": "High road",
            "kind": "road",
            "geometry": line([(0.0, CY), (CX, CY), (W, CY)]),
            "aliases": ["the high road", "the main road"],
        },
        {
            "name": "Curlew lane",
            "kind": "road",
            "geometry": line(curlew_lane()),
            "aliases": ["the curlew lane", "the north lane"],
        },
        {
            "name": "Godwit lane",
            "kind": "road",
            "geometry": line(godwit_lane()),
            "aliases": ["the godwit lane", "the south lane"],
        },
    ]
    out += pair(
        "Curlew Brook",
        "Godwit Brook",
        "stream",
        line(curlew_brook()),
        compass("Brook"),
        note="water, a band of cells from 500 m off the village to the corner: "
        "impassable but at its ford",
    )
    out += pair(
        "Curlew Ford",
        "Godwit Ford",
        "ford",
        pt(*CURLEW_FORD),
        compass("Ford"),
        radius_m=FORD_RADIUS_M,
        passable=list(FORD_SPEED),
        speed=dict(FORD_SPEED),
    )
    out += pair(
        "Withy road",
        "Osier road",
        "road",
        line(withy_road()),
        lambda n: [f"the {n.split()[0].lower()} road"],
    )
    out += pair("Curlew Mill", "Godwit Mill", "mill", pt(*at(*MILL_TS)), word_aliases("Mill"))
    out += pair(
        "Heron Ridge",
        "Bittern Ridge",
        "ridge",
        line(ridge_crest()),
        word_aliases("Ridge"),
        note=f"a crest {RIDGE_H_M:.0f} m over the fields, falling off over {RIDGE_HALF_W_M:.0f} m",
    )
    out += pair(
        "Siskin Wood",
        "Linnet Wood",
        "wood",
        {"type": "polygon", "coords": [[x, y] for x, y in wood_poly()]},
        word_aliases("Wood"),
    )
    out += pair("Wren Farm", "Thrush Farm", "farm", pt(*WREN), word_aliases("Farm"))
    out += pair("Finch Farm", "Starling Farm", "farm", pt(*FINCH), word_aliases("Farm"))
    for name, (x, y) in (("West exit", (EXIT_IN_M, CY)), ("East exit", (W - EXIT_IN_M, CY))):
        word = name.split()[0].lower()
        out.append(
            {
                "name": name,
                "kind": "exit",
                "geometry": pt(x, y),
                "aliases": [f"the {word} exit", f"the high road {word} exit"],
                "radius_m": EXIT_RADIUS_M,
                "road": "High road",
            }
        )
    return out


# --------------------------------------------------------------------------- names
# Invented surnames, as Plain's: three edits apart from each other, from Plain's and from the
# words of the place names; the army's first, then the formations in FORMATIONS order.
COMMANDERS = {
    "red": [
        "Gorringe",
        "Pettifer",
        "Ackroyd",
        "Mawhood",
        "Treloar",
        "Bunce",
        "Pinnock",
        "Snelling",
        "Hebditch",
        "Cundall",
        "Lorimer",
        "Venables",
    ],
    "blue": [
        "Fairclough",
        "Royle",
        "Tasker",
        "Quayle",
        "Pargeter",
        "Kemble",
        "Gubbins",
        "Shillito",
        "Etheridge",
        "Hammick",
        "Mallinson",
        "Jupe",
    ],
}
# The ground as each side sees it (Red faces east, its left is north; Blue faces west).
GROUND = {
    "red": {
        "own_ridge": "Heron Ridge",
        "enemy_ridge": "Bittern Ridge",
        "own_wood": "Siskin Wood",
        "enemy_wood": "Linnet Wood",
        "left_brook": "Curlew Brook",
        "right_brook": "Godwit Brook",
        "left_ford": "Curlew Ford",
        "right_ford": "Godwit Ford",
        "left_mill": "Curlew Mill",
        "right_mill": "Godwit Mill",
        "left_lane": "Curlew lane",
        "right_lane": "Godwit lane",
        "own_bank": "Withy road",
        "far_bank": "Osier road",
        "own_left": "Wren Farm",
        "own_right": "Finch Farm",
        "own_exit": "West exit",
        "far_exit": "East exit",
    },
    "blue": {
        "own_ridge": "Bittern Ridge",
        "enemy_ridge": "Heron Ridge",
        "own_wood": "Linnet Wood",
        "enemy_wood": "Siskin Wood",
        "left_brook": "Godwit Brook",
        "right_brook": "Curlew Brook",
        "left_ford": "Godwit Ford",
        "right_ford": "Curlew Ford",
        "left_mill": "Godwit Mill",
        "right_mill": "Curlew Mill",
        "left_lane": "Godwit lane",
        "right_lane": "Curlew lane",
        "own_bank": "Osier road",
        "far_bank": "Withy road",
        "own_left": "Thrush Farm",
        "own_right": "Starling Farm",
        "own_exit": "East exit",
        "far_exit": "West exit",
    },
}

# --------------------------------------------------------------------------- texts, script
SCRIPT = [  # Plain's plan on this ground (clock, text); {KEY}: that commander's surname
    ("09:00", "{L2}, advance by the high road to Plover Village, then hold it."),
    ("09:00", "{L1}, advance to Plover Village on the left of the second brigade, then hold."),
    ("09:00", "{L3}, advance to Plover Village on the right of the second brigade, then hold."),
    ("09:00", "{L4}, follow the second brigade."),
    ("09:00", "{N1}, follow the first brigade."),
    ("09:00", "{N2}, follow the third brigade."),
    ("09:00", "{HU}, cover our left flank."),
    ("09:00", "{DR}, cover our right flank."),
    ("09:00", "{CU}, stand behind {DR}'s brigade."),
    ("09:00", "{G}, stay in reserve behind the fourth brigade."),
    ("09:00", "{AR}, support the second brigade."),
    ("12:00", "{G}, advance to Plover Village and support the second brigade."),
    ("12:00", "{L2}, hold Plover Village to the last."),
]
SCRIPT_NOTE = (
    "Plain's plan on this ground, one for both sides, names swapped (tools/build_pack.py "
    "SCRIPT): the centre brigade advances on the village by the high road and holds it, the "
    "brigades either side and the second line follow it up, the horse covers the flanks, the "
    "grenadiers and the reserve guns stay behind; at noon the grenadiers go up to the village. "
    "It uses neither ford nor ridge: a baseline, not a plan for this field. For `script` "
    "players, whose orders Jev translates: stub-mode Jev reads every order as its first "
    "option, so a stub game of scripts checks plumbing only; stub self-play uses the doctrine "
    "bot (design-notes.md)."
)
PLAYERS_HEAD = (
    "# Plover Village: the players' brief\n\n"
    "The persona's battle layer for each side (docs/player-prompt.md), "
    "built by tools/build_pack.py from tools/players_template.md with each side's "
    "names, so that the two sections differ only in names. Under the designed ladder "
    "(docs/battles/README.md, the brief) it carries the verdict, "
    "the clock, the qualities and the enemy's order of battle in outline, numbers "
    "included. The umpire never reads this file.\n"
)
OBJECTIVES_HEAD = (
    "# Plover Village: objectives\n\n"
    "Each side's mission in its commander's words, the same for both sides "
    "(tools/objectives_template.md); the generals read it, with the verdict, in "
    "players.md. Designed battle: docs/battles/mirror.md.\n"
)
# The umpire reads this section (it is in every recorded Jev request of the games), so its
# words stay as played, the module name `kriegsspiel.mission` (now `verdict`) included.
OBJECTIVES_TAIL = (
    "\n## Umpire (the narrative only)\n\n"
    "Under this pack the umpire narrates and does not rule. The verdict is mechanical: "
    "mission.json is the ordinal verdict above (kriegsspiel.mission.OrdinalJudge), which "
    "ends the battle on a break and reads possession of Plover Village within musket range "
    "of the crossroads at 16:00 and in the play-on. The umpire's own verdict is kept beside "
    "it as a health number, never as the result. Name in the account Plover Village (the "
    "crossroads), Curlew Brook, Godwit Brook, Curlew Ford and Godwit Ford with their "
    "mills, Heron Ridge, Bittern Ridge, Siskin Wood, Linnet Wood, the High road, Curlew lane, "
    "Godwit lane, Withy road, Osier road, Wren Farm, Finch Farm, Thrush Farm, Starling Farm and "
    "the West and East exits.\n"
    "\n## Outcome (designed battle: none; not shown to commanders)\n\n"
    "No historical outcome. The self-play baseline is in design-notes.md.\n"
)


def main() -> None:
    oob, dep = d.armies(
        COMMANDERS, source="docs/battles/README.md, Plain's armies, Mirror's ground (DES)"
    )
    files = {
        "features.json": features(),
        "oob.json": oob,
        "deployment.json": dep,
        "meta.json": d.meta(oob, VILLAGE_NAME, COMMANDERS, "docs/battles/mirror.md"),
        "mission.json": d.mission(VILLAGE_NAME),
        "script.json": d.script(SCRIPT, SCRIPT_NOTE, COMMANDERS, GROUND),
    }
    tools = PACK / "tools"
    texts = {
        "players.md": d.players_md(
            PLAYERS_HEAD, (tools / "players_template.md").read_text(), COMMANDERS, GROUND
        ),
        "objectives.md": d.objectives_md(
            OBJECTIVES_HEAD,
            (tools / "objectives_template.md").read_text(),
            OBJECTIVES_TAIL,
            COMMANDERS,
        ),
    }
    d.write_pack(PACK, terrain(), files, texts)


if __name__ == "__main__":
    main()
