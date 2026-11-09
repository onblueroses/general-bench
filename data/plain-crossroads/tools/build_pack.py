"""Build data/plain-crossroads/ (the designed battle Plain) from the numbers below.

    uv run python -I data/plain-crossroads/tools/build_pack.py

Writes terrain.npz, features.json, oob.json, deployment.json, meta.json, mission.json,
script.json, players.md and objectives.md; the notes are hand-written. Deterministic: two
builds give identical bytes. Every number is a design choice (design-notes.md says why);
docs/battles/README.md is the design it implements. The box, the armies,
the deployment, the clock, the verdict and the assembly of the texts are shared with the
other designed battles (`kriegsspiel.designed`); this file holds Plain's ground and names.

Symmetry: the ground, the features and the deployment are invariant under the 180° rotation
about the crossroads, (x, y) -> (W - x, H - y), facing + 180°, red <-> blue. Red is built
and Blue is its rotation, so the symmetry holds by construction (the pack test checks it).
"""

from __future__ import annotations

from pathlib import Path

import numpy as np

from kriegsspiel import designed as d
from kriegsspiel.designed import CX, CY, EXIT_IN_M, EXIT_RADIUS_M, NX, NY, H, W

PACK = Path(__file__).resolve().parents[1]

# --------------------------------------------------------------------------- ground
ELEV_M = 200.0  # EST: flat; any constant gives the same physics
VILLAGE_R_M = 200.0  # EST: a crossroads village some 400 m across
ROAD_HALF_M = 12.5  # a road is one cell wide, on the centre line
FARM_M = 2000.0  # the ladder: four farms two kilometres from the village on the diagonals
OPEN, VILLAGE, ROAD = 0, 3, 7  # types.Cover

VILLAGE_NAME = "Teasel Village"


def terrain() -> dict:
    gx, gy = d.grid()
    cover = np.full((NY, NX), OPEN, np.uint8)
    cover[np.hypot(gx - CX, gy - CY) <= VILLAGE_R_M] = VILLAGE
    # roads after the village: the road through a village stays road
    cover[np.abs(gy - CY) <= ROAD_HALF_M] = ROAD  # the high road, west to east
    cover[np.abs(gx - CX) <= ROAD_HALF_M] = ROAD  # the drove road, south to north
    elev = np.full((NY, NX), ELEV_M, np.float32)
    return d.terrain_arrays(elev, cover)


def features() -> list[dict]:
    r = FARM_M / 2**0.5
    pt = d.pt
    out = [
        {
            "name": VILLAGE_NAME,
            "kind": "village",
            "geometry": pt(CX, CY),
            "aliases": ["the village", "the crossroads", "Teasele Village", "Teasel crossroads"],
            "radius_m": VILLAGE_R_M,
            "note": "a point at the crossroads: possession is judged within musket range of it "
            "(docs/battles/README.md, the verdict); the houses are the VILLAGE disc of terrain.npz",
        },
        {
            "name": "High road",
            "kind": "road",
            "geometry": {"type": "polyline", "coords": [[0.0, CY], [CX, CY], [W, CY]]},
            "aliases": ["the high road", "the main road"],
        },
        {
            "name": "Drove road",
            "kind": "road",
            "geometry": {"type": "polyline", "coords": [[CX, 0.0], [CX, CY], [CX, H]]},
            "aliases": ["the drove road"],
        },
    ]
    # the four farms, in rotation pairs: north-west <-> south-east, north-east <-> south-west
    for name, (sx, sy) in (
        ("Mallow Farm", (-1, 1)),
        ("Vetch Farm", (1, 1)),
        ("Yarrow Farm", (1, -1)),
        ("Burdock Farm", (-1, -1)),
    ):
        word = name.split()[0]
        out.append(
            {
                "name": name,
                "kind": "farm",
                "geometry": pt(CX + sx * r, CY + sy * r),
                "aliases": [f"{word}e Farm", f"the {word.lower()} farm"],
            }
        )
    # the four road exits, in rotation pairs: west <-> east, south <-> north
    for name, (x, y), road in (
        ("West exit", (EXIT_IN_M, CY), "High road"),
        ("East exit", (W - EXIT_IN_M, CY), "High road"),
        ("South exit", (CX, EXIT_IN_M), "Drove road"),
        ("North exit", (CX, H - EXIT_IN_M), "Drove road"),
    ):
        word = name.split()[0].lower()
        out.append(
            {
                "name": name,
                "kind": "exit",
                "geometry": pt(x, y),
                "aliases": [f"the {word} exit", f"the {road.lower()} {word} exit"],
                "radius_m": EXIT_RADIUS_M,
                "road": road,
            }
        )
    return out


# --------------------------------------------------------------------------- names
# Invented surnames (three edits apart, no common word, no
# word of a place); the army's first, then the formations in designed.FORMATIONS order.
COMMANDERS = {
    "red": [
        "Thursby",
        "Calloway",
        "Brandreth",
        "Fenwick",
        "Haddow",
        "Pellow",
        "Quarrie",
        "Stannard",
        "Ormerod",
        "Lattimer",
        "Vowell",
        "Kitto",
    ],
    "blue": [
        "Raikes",
        "Dewhurst",
        "Ellerby",
        "Garside",
        "Hesketh",
        "Jessop",
        "Nuttall",
        "Upjohn",
        "Whitlock",
        "Ibbotson",
        "Rudge",
        "Tranter",
    ],
}
# the ground as each side sees it: farms on its own half left and right, beyond the village
# left and right; the exit behind it, ahead, on its left, on its right
GROUND = {
    "red": {
        "own_left": "Mallow Farm",
        "own_right": "Burdock Farm",
        "far_left": "Vetch Farm",
        "far_right": "Yarrow Farm",
        "own_exit": "West exit",
        "far_exit": "East exit",
        "left_exit": "North exit",
        "right_exit": "South exit",
    },
    "blue": {
        "own_left": "Yarrow Farm",
        "own_right": "Vetch Farm",
        "far_left": "Burdock Farm",
        "far_right": "Mallow Farm",
        "own_exit": "East exit",
        "far_exit": "West exit",
        "left_exit": "South exit",
        "right_exit": "North exit",
    },
}

# --------------------------------------------------------------------------- texts, script
SCRIPT = [  # (clock, text); {KEY} is that formation's commander's surname
    ("09:00", "{L2}, advance by the high road to Teasel Village, then hold it."),
    ("09:00", "{L1}, advance to Teasel Village on the left of the second brigade, then hold."),
    ("09:00", "{L3}, advance to Teasel Village on the right of the second brigade, then hold."),
    ("09:00", "{L4}, follow the second brigade."),
    ("09:00", "{N1}, follow the first brigade."),
    ("09:00", "{N2}, follow the third brigade."),
    ("09:00", "{HU}, cover our left flank."),
    ("09:00", "{DR}, cover our right flank."),
    ("09:00", "{CU}, stand behind {DR}'s brigade."),
    ("09:00", "{G}, stay in reserve behind the fourth brigade."),
    ("09:00", "{AR}, support the second brigade."),
    ("12:00", "{G}, advance to Teasel Village and support the second brigade."),
    ("12:00", "{L2}, hold Teasel Village to the last."),
]
SCRIPT_NOTE = (
    "One plan for both sides, names swapped (tools/build_pack.py SCRIPT): the centre brigade "
    "advances on the village by the high road and holds it, the brigades either side and the "
    "second line follow it up, the horse covers the flanks, the grenadiers and the reserve "
    "guns stay behind; at noon the grenadiers go up to the village. For `script` players, "
    "whose orders Jev translates: stub-mode Jev reads every order as its first option, so a "
    "stub game of scripts checks plumbing only; stub self-play uses the doctrine bot "
    "(design-notes.md)."
)
PLAYERS_HEAD = (
    "# Teasel Village: the players' brief\n\n"
    "The persona's battle layer for each side (docs/player-prompt.md), "
    "built by tools/build_pack.py from tools/players_template.md with each side's "
    "names, so that the two sections differ only in names. Under the designed ladder "
    "(docs/battles/README.md, the brief) it carries the verdict, "
    "the clock, the qualities and the enemy's order of battle in outline, numbers "
    "included. The umpire never reads this file.\n"
)
OBJECTIVES_HEAD = (
    "# Teasel Village: objectives\n\n"
    "Each side's mission in its commander's words, the same for both sides "
    "(tools/objectives_template.md); the generals read it, with the verdict, in "
    "players.md. Designed battle: docs/battles/plain.md.\n"
)
# The umpire reads this section (it is in every recorded Jev request of the games), so its
# words stay as played, the module name `kriegsspiel.mission` (now `verdict`) included.
OBJECTIVES_TAIL = (
    "\n## Umpire (the narrative only)\n\n"
    "Under this pack the umpire narrates and does not rule. The verdict is mechanical: "
    "mission.json is the ordinal verdict above (kriegsspiel.mission.OrdinalJudge), which "
    "ends the battle on a break and reads possession of Teasel Village within musket range "
    "of the crossroads at 16:00 and in the play-on. The umpire's own verdict is kept beside "
    "it as a health number, never as the result. Name in the account Teasel Village (the "
    "crossroads), the High road, the Drove road, Mallow Farm, Vetch Farm, Yarrow Farm, "
    "Burdock Farm and the four exits, West, East, North and South.\n"
    "\n## Outcome (designed battle: none; not shown to commanders)\n\n"
    "No historical outcome. The self-play baseline is in design-notes.md.\n"
)


def main() -> None:
    oob, dep = d.armies(COMMANDERS)
    files = {
        "features.json": features(),
        "oob.json": oob,
        "deployment.json": dep,
        "meta.json": d.meta(oob, VILLAGE_NAME, COMMANDERS, "docs/battles/plain.md"),
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
