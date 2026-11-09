"""What the designed battles share (docs/battles/README.md): the box, the
armies, the deployment, the clock, the ordinal verdict, the brief's assembly and the scripted
plan's assembly. Each pack's `tools/build_pack.py` imports this and adds its own ground,
names and texts; nothing here is read by the engine.

The rungs differ in one thing each (docs/battles/README.md, "The ladder"): Plain is the
reference, Mirror changes the ground, Arms the armies (`add_army` with its own formations and
layout, and the text helpers' per-side `keys`, `colours`, templates and plans). Every number
here is Plain's and its reason is in data/plain-crossroads/design-notes.md.

Symmetry: the box is centred on (CX, CY) with an odd raster, so a cell centre sits on the
centre and the raster is exactly invariant under the 180° rotation (x, y) -> (W - x, H - y)
(`flip` of a mask is its rotation). Red is built and Blue is its rotation.
"""

from __future__ import annotations

import io
import json
import zipfile
from pathlib import Path

import numpy as np

# --------------------------------------------------------------------------- the box
W, H = 8000.0, 6000.0  # metres, x east, y north (the ladder: 8 km east-west, 6 km north-south)
CELL = 25.0  # as every pack
NX, NY = 321, 241  # odd, so that the centre of the box is the centre of a cell
ORIGIN = -CELL / 2  # the raster spans -12.5 to W + 12.5: cell centres are symmetric
CX, CY = W / 2, H / 2  # the village, the centre of the map and of the rotation
EXIT_IN_M = 10.0  # exits stand 10 m inside the edge, on the road
EXIT_RADIUS_M = 100.0  # the format's default
SIDES = ("red", "blue")
PREFIX = {"red": "R", "blue": "B"}  # of each side's formation and body ids
START = "09:00"  # the clock of minute 0
SOURCE = "docs/battles/README.md, Plain's armies (DES)"


def rot(x: float, y: float) -> tuple[float, float]:
    """The image of (x, y) under the 180° rotation about the centre of the box."""
    return (round(W - x, 1), round(H - y, 1))


def grid() -> tuple[np.ndarray, np.ndarray]:
    """The x and y of every cell centre, (NY, NX) each; row 0 is the south edge."""
    xs = ORIGIN + (np.arange(NX) + 0.5) * CELL
    ys = ORIGIN + (np.arange(NY) + 0.5) * CELL
    return np.meshgrid(xs, ys)


def flip(a: np.ndarray) -> np.ndarray:
    """A raster turned by 180° about the centre of the box."""
    return a[::-1, ::-1]


def terrain_arrays(elev: np.ndarray, cover: np.ndarray) -> dict:
    return {
        "elev": elev,
        "cover": cover,
        "cell_m": np.float64(CELL),
        "origin": np.array([ORIGIN, ORIGIN]),
    }


def pt(x: float, y: float) -> dict:
    return {"type": "point", "coords": [[round(x, 1), round(y, 1)]]}


# --------------------------------------------------------------------------- armies
# The ladder, "Plain's armies": 7 infantry brigades of 2 battalions of 700, 3 cavalry brigades of
# 2 regiments of 400, an artillery reserve of two 12-pounder batteries of 8 guns, 2 battalion
# guns per battalion; quality by formation. (key, name, aliases, kind, quality)
BN_MEN, REGT_MEN, GUNS, CREW_PER_GUN = 700, 400, 8, 15  # crew: 15 a gun (EST)
FORMATIONS = [
    ("G", "Grenadier brigade", ["the grenadiers", "the grenadier brigade"], "grenadier", 5),
    ("L1", "First brigade", ["the first brigade"], "line", 3),
    ("L2", "Second brigade", ["the second brigade"], "line", 3),
    ("L3", "Third brigade", ["the third brigade"], "line", 3),
    ("L4", "Fourth brigade", ["the fourth brigade"], "line", 3),
    ("N1", "Fifth brigade", ["the fifth brigade"], "line", 2),
    ("N2", "Sixth brigade", ["the sixth brigade"], "line", 2),
    (
        "CU",
        "Cuirassier brigade",
        ["the cuirassiers", "the cuirassier brigade", "the heavy horse"],
        "cuirassier",
        4,
    ),
    ("DR", "Dragoon brigade", ["the dragoons", "the dragoon brigade"], "dragoon", 3),
    ("HU", "Hussar brigade", ["the hussars", "the hussar brigade", "the light horse"], "hussar", 3),
    (
        "AR",
        "Reserve artillery",
        ["the reserve artillery", "the reserve guns", "the twelve-pounders"],
        "foot_battery",
        3,
    ),
]
KEYS = [k for k, *_ in FORMATIONS]
# unit names by arm and number ("Blue Foot 01")
UNIT_WORD = {
    "grenadier": "Grenadiers",
    "line": "Foot",
    "cuirassier": "Heavy Horse",
    "dragoon": "Dragoons",
    "hussar": "Light Horse",
    "foot_battery": "Heavy Battery",
    "horse_battery": "Horse Battery",
}
BATTERY_KINDS = {"foot_battery": 12, "horse_battery": 6}  # kind -> calibre (lb)
HORSE_KINDS = ("cuirassier", "dragoon", "hussar")

# Red's deployment (Red is the west army, facing east; its left is north). Blue is the
# rotation. First line 3.5 km from the centre (x 500), second line 250 m behind it, the
# grenadiers and the reserve guns behind the centre, headquarters between them.
FIRST_X, SECOND_X, RESERVE_X, HQ_X = 500.0, 250.0, 100.0, 175.0
BN_STEP = 170.0  # a battalion of 700 in line is 140 m wide, plus the 30 m interval
REGT_STEP = 210.0  # a regiment of 400 in line is 180 m wide, plus the interval
BRIGADE_STEP = 350.0  # centre to centre: a brigade's 310 m and a 40 m gap
WING_Y = 1.5 * BRIGADE_STEP + 245.0  # a cavalry brigade's centre: 70 m beyond the flank
SLOTS = {  # formation -> (x, y) of its centre
    "L1": (FIRST_X, CY + BRIGADE_STEP),
    "L2": (FIRST_X, CY),
    "L3": (FIRST_X, CY - BRIGADE_STEP),
    "HU": (FIRST_X, CY + WING_Y),  # the left wing
    "DR": (FIRST_X, CY - WING_Y),  # the right wing
    "N1": (SECOND_X, CY + BRIGADE_STEP),
    "L4": (SECOND_X, CY),
    "N2": (SECOND_X, CY - BRIGADE_STEP),
    "CU": (SECOND_X, CY - WING_Y),  # behind the dragoons
    "G": (RESERVE_X, CY),
}
BATTERY_Y = (CY + 250.0, CY - 250.0)  # the reserve guns either side of the grenadiers


def plain_place(key: str, kind: str, i: int) -> tuple[float, float, str]:
    """Where body `i` of formation `key` stands in Plain's deployment, west frame."""
    if kind in BATTERY_KINDS:
        return RESERVE_X, BATTERY_Y[i], "limbered"
    sx, sy = SLOTS[key]
    if kind in HORSE_KINDS:
        return sx, sy + (0.5 - i) * REGT_STEP, "line"
    # the grenadiers stand in column behind the centre, the lines in line
    return sx, sy + (0.5 - i) * BN_STEP, ("column" if key == "G" else "line")


def add_army(
    oob: dict,
    dep: dict,
    side: str,
    prefix: str,
    colour: str,
    names: list[str],
    formations: list[tuple],
    place,
    turn: bool,
    source: str = SOURCE,
) -> None:
    """One army into oob.json and deployment.json. `formations`: (key, name, aliases, kind,
    quality) or the same with the number of bodies last (default 2); `names`: the army's
    surname, then one per formation; `place(key, kind, i)`: (x, y, state) of body `i` in the
    west frame (facing east); `turn`: the army stands east, at the rotation of that frame."""
    oob["formations"].append(
        {
            "id": prefix,
            "name": f"{colour} army",
            "side": side,
            "commander": f"General {names[0]}",
            "parent": None,
            "level": "army",
            "aliases": ["the army", f"the {colour} army", f"{names[0]}'s army"],
        }
    )
    dep["hq"][prefix] = list(rot(HQ_X, CY)) if turn else [HQ_X, CY]
    count: dict[str, int] = {}
    for spec, sur in zip(formations, names[1:], strict=True):
        key, fname, aliases, kind, quality = spec[:5]
        bodies = spec[5] if len(spec) > 5 else 2
        fid = f"{prefix}-{key}"
        own = [f"{sur}'s guns"] if kind in BATTERY_KINDS else [f"{sur}'s brigade"]
        oob["formations"].append(
            {
                "id": fid,
                "name": fname,
                "side": side,
                "commander": f"General {sur}",
                "parent": prefix,
                "level": "brigade",
                "aliases": [*aliases, *own],
            }
        )
        for i in range(bodies):
            n = count[kind] = count.get(kind, 0) + 1
            u = {
                "id": f"{fid}-{i + 1}",
                "name": f"{colour} {UNIT_WORD[kind]} {n:02d}",
                "side": side,
                "parent": fid,
                "kind": kind,
                "quality": quality,
                "source": source,
            }
            if kind in BATTERY_KINDS:
                u.update(
                    men=GUNS * CREW_PER_GUN,
                    guns=GUNS,
                    crew=GUNS * CREW_PER_GUN,
                    calibre_lb=BATTERY_KINDS[kind],
                    source=u["source"] + "; crew EST (15 a gun)",
                )
            elif kind in HORSE_KINDS:
                u["men"] = REGT_MEN
            else:
                u.update(men=BN_MEN, battalion_guns=2)
            x, y, state = place(key, kind, i)
            oob["units"].append(u)
            face = 90.0
            if turn:
                x, y = rot(x, y)
                face = 270.0
            dep["units"][u["id"]] = {
                "x": float(x),
                "y": float(y),
                "facing_deg": face,
                "state": state,
            }


def armies(commanders: dict[str, list[str]], source: str = SOURCE) -> tuple[dict, dict]:
    """Plain's oob.json and deployment.json. `commanders[side]`: the army's surname, then one
    per formation in FORMATIONS order. Red stands west, Blue is its rotation."""
    oob: dict = {"sides": list(SIDES), "formations": [], "units": []}
    dep: dict = {"start": START, "units": {}, "hq": {}}
    for side in SIDES:
        add_army(
            oob,
            dep,
            side,
            PREFIX[side],
            side.capitalize(),
            commanders[side],
            FORMATIONS,
            plain_place,
            side == "blue",
            source,
        )
    return oob, dep


# --------------------------------------------------------------------------- meta, mission
def meta(oob: dict, battle: str, commanders: dict[str, list[str]], doc: str) -> dict:
    men = {s: sum(u["men"] for u in oob["units"] if u["side"] == s) for s in oob["sides"]}
    return {
        "battle": battle,
        "designed": True,
        "rules_sheet": True,  # docs/battles/README.md: the engine's numbers go in the first brief
        "season": "high summer",
        "daylight_date": "07-05",
        "start": START,
        "end": "16:00",
        "time_basis": "local apparent solar time",
        "sunrise": "03:53",
        "sunset": "20:07",
        "civil_dusk": "20:50",
        "weather": "dry, clear and warm; the ground firm",
        "sides": {
            s: {
                "commander": f"General {commanders[s][0]}",
                "army": s[0].upper(),
                "role": "meeting engagement",
            }
            for s in oob["sides"]
        },
        "strength_documented": men,
        "bodies": {s: sum(u["side"] == s for u in oob["units"]) for s in oob["sides"]},
        "par": {
            "source": "none: designed battle; the baseline is self-play "
            "(docs/battles/README.md, calibration)"
        },
        "doc": doc,
    }


def mission(village: str) -> dict:
    return {
        "verdict": "ordinal",
        "objective": village,
        "break_share": 0.4,
        "break_persist_min": 30,
        "play_on_min": 120,
        "break_tie_margin": 0.10,
        "note": "docs/battles/README.md, the verdict: an army with more than 40% of its men in "
        "routed or destroyed bodies for 30 minutes loses (both over: the less broken wins, "
        "within 10 points a draw); otherwise the side in possession of "
        "the village (within musket range of the crossroads) at 16:00 wins; "
        "contested: play on by quarter hours, two hours at most, then a draw. "
        "Nothing else scores.",
    }


# --------------------------------------------------------------------------- files
def dump(obj) -> str:
    return json.dumps(obj, indent=1, ensure_ascii=False) + "\n"


def write_npz(path: Path, arrays: dict) -> None:
    """np.savez_compressed with fixed zip timestamps, so that a rebuild is byte-identical."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for k, v in arrays.items():
            a = io.BytesIO()
            np.lib.format.write_array(a, np.asanyarray(v), allow_pickle=False)
            info = zipfile.ZipInfo(f"{k}.npy", date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            zf.writestr(info, a.getvalue())
    path.write_bytes(buf.getvalue())


# --------------------------------------------------------------------------- texts, script
# One template per text, filled for each side with that side's names, so that the two sides'
# briefs differ only in names by construction (each pack's test checks the persona too). Arms,
# whose armies differ, passes its sides, per-side keys and colours, and per-side templates and
# plans (dicts by side).
def names_of(
    side: str,
    commanders: dict[str, list[str]],
    ground: dict[str, dict],
    keys: dict[str, list[str]] | None = None,
    colours: dict[str, str] | None = None,
) -> dict[str, str]:
    colours = colours or {s: s.capitalize() for s in SIDES}
    other = next(s for s in colours if s != side)
    out = dict(zip((keys or {}).get(side, KEYS), commanders[side][1:], strict=True))
    out.update(ground[side], army=f"{colours[side]} army", enemy_army=f"{colours[other]} army")
    return out


def general(side: str, commanders: dict[str, list[str]]) -> str:
    return f"General {commanders[side][0]}"


def _per_side(x, side: str):
    return x[side] if isinstance(x, dict) else x


def players_md(
    head: str,
    template,
    commanders: dict,
    ground: dict,
    sides=SIDES,
    keys: dict | None = None,
    colours: dict | None = None,
) -> str:
    return head + "".join(
        f"\n## {s.capitalize()}: {general(s, commanders)}\n\n"
        + _per_side(template, s).format(**names_of(s, commanders, ground, keys, colours))
        for s in sides
    )


def objectives_md(head: str, template: str, tail: str, commanders: dict, sides=SIDES) -> str:
    out = head + "".join(
        f"\n## {s.capitalize()}: {general(s, commanders)}\n\n{template}" for s in sides
    )
    return out + tail


def script(
    plan,
    note: str,
    commanders: dict,
    ground: dict,
    sides=SIDES,
    keys: dict | None = None,
    colours: dict | None = None,
) -> dict:
    orders = [
        {"at": at, "side": s, "text": text.format(**names_of(s, commanders, ground, keys, colours))}
        for s in sides
        for at, text in _per_side(plan, s)
    ]
    return {"note": note, "orders": orders}


def write_pack(pack: Path, terrain: dict, files: dict, texts: dict[str, str]) -> None:
    write_npz(pack / "terrain.npz", terrain)
    for name, obj in files.items():
        (pack / name).write_text(dump(obj))
    for name, text in texts.items():
        (pack / name).write_text(text)
    print("wrote", ", ".join(["terrain.npz", *files, *texts]))
