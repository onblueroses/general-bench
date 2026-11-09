"""Write the Kolín pack's {features,oob,deployment,meta}.json from the tables below.

Usage (repo root, after build_terrain.py):
    uv run python -I tests/kriegsspiel/fixtures/packs/kolin/tools/build_scenario.py

Every number here is sourced or labelled in docs/kolin-test-pack.md. Key to the source tags:
  NAF  Nafziger 757FAR / 757FAS (generalstaff.org), after Decker and the Prussian General Staff
  KRO  kronoskaf.com, Project Seven Years War, "1757-06-18 - Battle of Kolin" (after the
       Grosser Generalstab, Die Kriege Friedrichs des Grossen III/3, Anlage 3-4)
  CDB  CDB90 isqno 67 (jrnold/CDB90)
  EST  our estimate; the rule is stated where it is applied
"""

from __future__ import annotations

import itertools
import json
import math
import sys
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
DATA = HERE.parent

terrain = np.load(DATA / "terrain.npz")
ELEV, COVER, CELL = terrain["elev"], terrain["cover"], float(terrain["cell_m"])
NY, NX = ELEV.shape
WATER = 6
extract = json.loads((HERE / "osm_extract.json").read_text())
hand = json.loads((HERE / "hand_features.json").read_text())

sys.path.insert(0, str(HERE))
from build_terrain import to_local  # noqa: E402 - importable only after the path insert

# =========================================================================== features


def circle(x, y, r, n=16):
    return [
        [
            round(x + r * math.cos(2 * math.pi * k / n), 1),
            round(y + r * math.sin(2 * math.pi * k / n), 1),
        ]
        for k in range(n)
    ]


def chain_ways(ways):
    """Greedy join of OSM way segments sharing endpoints into one polyline."""
    segs = [list(map(tuple, w["xy"])) for w in ways]
    segs.sort(key=len, reverse=True)
    line = segs.pop(0)
    grown = True
    while grown and segs:
        grown = False
        for s in list(segs):
            for cand in (s, s[::-1]):
                if math.dist(cand[0], line[-1]) < 1.0:
                    line += cand[1:]
                elif math.dist(cand[-1], line[0]) < 1.0:
                    line = cand[:-1] + line
                else:
                    continue
                segs.remove(s)
                grown = True
                break
    return [[round(x, 1), round(y, 1)] for x, y in line]


def in_grid(x, y):
    return 0 <= x < NX * CELL and 0 <= y < NY * CELL


features: list[dict] = []


def feat(name, kind, gtype, coords, aliases):
    features.append(
        {
            "name": name,
            "kind": kind,
            "geometry": {"type": gtype, "coords": coords},
            "aliases": aliases,
        }
    )


for v in hand["villages"]:
    x, y = (float(c) for c in to_local(*v["latlon"]))
    kind = "farm" if v["name"] == "Zlaté Slunce" else "village"
    feat(v["name"], kind, "polygon", circle(x, y, v["radius_m"]), v["aliases"])
for w in hand["woods"]:
    feat(w["name"], "wood", "polygon", [list(p) for p in w["xy"]], w["aliases"])

feat(
    "Křečhoř heights",
    "height",
    "polygon",
    [[round(a, 1), round(b, 1)] for a, b in extract["heights"]],
    [
        "Krzeczhorzer Höhen",
        "Krechor heights",
        "the heights",
        "Kamhajek-Berg",
        "Kamhajek Berg",
        "the Austrian heights",
    ],
)
feat(
    "Křečhoř crest",
    "ridge",
    "polyline",
    [list(p) for p in extract["crest"]],
    ["the crest", "the ridge", "Krechor crest", "crest of the heights"],
)
peaks = {p["name"]: p for p in extract["peaks"] if p["name"]}
kx, ky = peaks["Křečhoř"]["xy"]
feat(
    "Křečhoř hill",
    "height",
    "point",
    [[round(kx, 1), round(ky, 1)]],
    ["Krzeczhorzer Berg", "Krzeczhorz hill", "Krechor hill", "Height of Krzeczhorz"],
)
# Przerovsky: kronoskaf leaves it unidentified; we take the western summit of the same ridge,
# across the saddle from Křečhoř hill (EST, see docs/kolin-test-pack.md).
feat(
    "Przerovsky height",
    "height",
    "point",
    [[5250.0, 2850.0]],
    ["Przerovsky", "Przerovsky Hill", "Height of Przerovsky", "Přerovský vrch"],
)
bx, by = peaks["Bedřichov"]["xy"]
feat(
    "Friedrichsberg",
    "height",
    "point",
    [[round(bx, 1), round(by, 1)]],
    ["Bedřichov", "Bedrichov", "Frederick's hill", "the King's hill"],
)
feat(
    "Kaiserstrasse",
    "road",
    "polyline",
    [[round(x, 1), round(y, 1)] for x, y in extract["kaiserstrasse"]],
    [
        "the Kaiserstrasse",
        "the high road",
        "the highway",
        "the road",
        "the road to Kolín",
        "the road to Kolin",
        "Císařská silnice",
        "Prague road",
    ],
)

stream_names = {
    "Pekelský potok": ("Peklo brook", ["Pekelský potok", "Peklo", "Peklo-Bach", "Peklo stream"]),
    "Blinka": ("Blinka brook", ["Blinka stream", "Blinka-Bach"]),
    "Nouzovský potok": ("Nouzov brook", ["Nouzovský potok"]),
    "Polepka": ("Polepka brook", ["Polepka", "Polepka stream"]),
    "Hluboký potok": ("Hluboký brook", ["Hluboký potok"]),
    "Miletínský potok": ("Miletín brook", ["Miletínský potok"]),
}
by_name: dict[str, list] = {}
for s in extract["streams"]:
    if s["name"] in stream_names or s["name"] == "Peklo":
        key = "Pekelský potok" if s["name"] == "Peklo" else s["name"]
        by_name.setdefault(key, []).append(s)
for osm_name, ways in by_name.items():
    line = list(chain_ways(ways))
    if not any(in_grid(*p) for p in line):
        continue
    name, aliases = stream_names[osm_name]
    feat(name, "stream", "polyline", line, aliases)
feat("Elbe", "stream", "polyline", chain_ways(extract["elbe"]), ["Labe", "the Elbe", "Elbe river"])

pond_names = {
    "Hořejší rybník": ["Horejsi rybnik"],
    "Svojšický rybník": ["Svojsicky rybnik"],
    "Hořešák": ["Horesak"],
    "Nouzov": ["Nouzov pond"],
    "Nouzáček": ["Nouzacek"],
    "Obecňák": ["Obecnak"],
    "Peklo": ["Peklo rybník"],
    "Hradišťko": ["Hradistko pond"],
    "Rozkoš": ["Rozkos"],
    "Karasák": ["Karasak"],
}
for p in extract["ponds"]:
    if p["name"] in pond_names:
        cx = sum(q[0] for q in p["xy"]) / len(p["xy"])
        cy = sum(q[1] for q in p["xy"]) / len(p["xy"])
        if not in_grid(cx, cy):
            continue
        name = p["name"] + (" pond" if p["name"] in ("Peklo", "Nouzov") else "")
        aliases = [a for a in pond_names[p["name"]] if a.casefold() != name.casefold()]
        feat(
            name, "pond", "polygon", [[round(a, 1), round(b, 1)] for a, b in p["xy"][:-1]], aliases
        )

churches = {c["name"]: c["xy"] for c in extract["churches"] if c["name"]}
feat(
    "Kolín church",
    "church",
    "point",
    [[round(v, 1) for v in churches["svatý Bartoloměj"]]],
    ["St. Bartholomew", "Kostel svatého Bartoloměje", "Kolin church"],
)
feat(
    "Plaňany church",
    "church",
    "point",
    [[round(v, 1) for v in churches["Narození svatého Jana Křtitele"]]],
    ["Planian church", "Planjan church tower", "Planany church"],
)
krx, kry = (float(c) for c in to_local(50.0255, 15.1268))
feat(
    "Křečhoř church",
    "church",
    "point",
    [[round(krx, 1), round(kry, 1)]],
    ["Krzeczhorz church", "Krechor church"],
)

# =========================================================================== order of battle
# Quality rule (EST): 5 guard and grenadiers of the Prussian army, Prussian Garde du Corps;
# 4 Prussian line infantry and all Prussian cavalry, Austrian picked troops (Kommandierte,
# converged grenadiers, Saxon Karabiniergarde), Austrian heavy artillery; 3 Austrian line
# infantry and regular cavalry, Saxon chevaux-légers, regular hussar regiments, Grenzer
# infantry, Prussian heavy artillery; 2 Grenz-hussar detachments.

units: list[dict] = []
formations: list[dict] = []


def F(fid, name, side, commander, parent, level, aliases=()):
    formations.append(
        {
            "id": fid,
            "name": name,
            "side": side,
            "commander": commander,
            "parent": parent,
            "level": level,
            "aliases": list(aliases),
        }
    )


def U(uid, name, side, parent, kind, quality, men=0, source="", **extra):
    d = {
        "id": uid,
        "name": name,
        "side": side,
        "parent": parent,
        "kind": kind,
        "men": round(men),
        "quality": quality,
        "source": source,
    }
    d.update(extra)
    units.append(d)


# --------------------------------------------------------------------------- Prussia
P = "prussia"
PR_TOTAL = 32_000  # CDB
PR_CUIR_SQN, PR_HUS_SQN = 130, 110  # EST: 66 x 130 + 50 x 110 = 14,080 ~ CDB cavalry 14,000
PR_GUN_CREW = 15  # EST per heavy piece
PR_GREN_BN = 500  # EST
PR_HEAVY = 6 + 10 + 12  # KRO: 21 x 12-pdr, 4 howitzers, 3 mortars = 28 pieces
PR_CAV = 66 * PR_CUIR_SQN + 50 * PR_HUS_SQN
PR_INF = PR_TOTAL - PR_CAV - PR_HEAVY * PR_GUN_CREW
PR_LINE_BN = (PR_INF - 7 * PR_GREN_BN) / 25  # 25 musketeer/fusilier/guard bns

F("P", "Prussian Army", P, "Frederick II", None, "army", ["the army", "the King's army"])
F(
    "P-VAN",
    "Vanguard",
    P,
    "Zieten",
    "P",
    "wing",
    ["the vanguard", "the advance guard", "Zieten's corps"],
)
F(
    "P-ZIE",
    "Zieten's hussars",
    P,
    "Generalmajor von Katte",
    "P-VAN",
    "brigade",
    ["the hussars", "Zieten's hussars", "the Prussian hussars"],
)
F(
    "P-HUL",
    "Hülsen's corps",
    P,
    "Hülsen",
    "P-VAN",
    "brigade",
    ["Hülsen's brigade", "Hulsen's corps", "Hülsen's infantry"],
)
F(
    "P-INF",
    "Infantry",
    P,
    "Moritz of Anhalt-Dessau",
    "P",
    "wing",
    ["the infantry", "the centre", "Prince Moritz's infantry", "Moritz"],
)
F(
    "P-TRE",
    "Left wing infantry",
    P,
    "Tresckow",
    "P-INF",
    "column",
    ["the left wing", "Tresckow's division", "the first column"],
)
F("P-PAN", "Pannwitz's brigade", P, "Pannwitz", "P-TRE", "brigade", ["Pannwitz"])
F(
    "P-FRA",
    "Prince Franz's brigade",
    P,
    "Prince Franz of Brunswick",
    "P-TRE",
    "brigade",
    ["Braunschweig's brigade", "Prince Franz"],
)
F(
    "P-FLG",
    "Flank-guard grenadiers",
    P,
    "Major von Kahlden (senior battalion commander, EST)",
    "P-TRE",
    "brigade",
    ["the flank guard", "the three grenadier battalions", "the grenadiers of the flank guard"],
)
F(
    "P-BEV",
    "Right wing infantry",
    P,
    "Bevern",
    "P-INF",
    "column",
    ["the right wing", "Bevern's division", "the second column"],
)
F("P-MAN", "Manstein's brigade", P, "Manstein", "P-BEV", "brigade", ["Manstein"])
F(
    "P-PUT",
    "Puttkamer's brigade",
    P,
    "Puttkamer",
    "P-BEV",
    "brigade",
    ["the Guard brigade", "Tauentzien's guard battalion"],
)
F("P-ING", "Ingersleben's brigade", P, "Ingersleben", "P-BEV", "brigade", ["Ingersleben"])
F(
    "P-CAV",
    "Cavalry",
    P,
    "Penavaire",
    "P",
    "wing",
    ["the cavalry", "the horse", "Penavaire's cavalry"],
)
F(
    "P-KRK",
    "Penavaire's cuirassiers",
    P,
    "Krockow",
    "P-CAV",
    "brigade",
    ["the cuirassiers", "Krockow's brigade", "the twenty squadrons"],
)
F(
    "P-SCH",
    "Schönaich's brigade",
    P,
    "Schönaich",
    "P-CAV",
    "brigade",
    ["Schönaich", "the right-wing cuirassiers", "the Garde du Corps brigade"],
)
F(
    "P-NOR",
    "Normann's dragoons",
    P,
    "Normann",
    "P-CAV",
    "brigade",
    ["Normann's brigade", "the dragoons"],
)
F("P-MEI", "Meinicke's dragoons", P, "Meinicke", "P-CAV", "brigade", ["Meinicke's brigade"])
F(
    "P-KRO",
    "Krosigk's cavalry reserve",
    P,
    "Krosigk",
    "P-CAV",
    "brigade",
    ["the cavalry reserve", "Krosigk's brigade", "Krosigk's reserve", "the third column"],
)
F(
    "P-ART",
    "Heavy artillery",
    P,
    "Prussian artillery commander (unrecorded)",
    "P",
    "brigade",
    ["the artillery", "the heavy guns", "the batteries", "the Prussian guns"],
)

for pid, name, sqns, half in [
    ("ZIE", "Zieten Hussars", 10, True),
    ("WER", "Werner Hussars", 10, True),
    ("PUT", "Puttkamer Hussars", 10, True),
    ("WAR", "Wartenberg Hussars", 10, True),
    ("SEY", "Seydlitz Hussars", 5, False),
    ("SZE", "Szekely Hussars", 5, False),
]:
    parts = ["I", "II"] if half else [""]
    for part in parts:
        n = sqns // len(parts)
        U(
            f"P-{pid}{part and '-' + part}",
            f"{name}{part and ' ' + part}".strip(),
            P,
            "P-ZIE",
            "hussar",
            4,
            n * PR_HUS_SQN,
            "KRO sqns; EST 110/sqn",
            sqns=n,
        )
for uid, name, kind, q in [
    ("P-NIM", "Grenadier Battalion Nimschöfsky", "grenadier", 5),
    ("P-WAL", "Grenadier Battalion Waldow", "grenadier", 5),
    ("P-FIN", "Grenadier Battalion Finck", "grenadier", 5),
]:
    U(uid, name, P, "P-HUL", kind, q, PR_GREN_BN, "KRO; EST 500/grenadier bn", battalion_guns=2)
for reg, kind, code in [("Schultze", "line", "SCHU"), ("Münchow Fusiliers", "fusilier", "MUNC")]:
    for b in ("I", "II"):
        U(
            f"P-{code}-{b}",
            f"{b}./{reg}",
            P,
            "P-HUL",
            kind,
            4,
            PR_LINE_BN,
            "KRO; EST line bn",
            battalion_guns=2,
        )
U(
    "P-STE",
    "Stechow Dragoons",
    P,
    "P-HUL",
    "dragoon",
    4,
    5 * PR_CUIR_SQN,
    "KRO sqns; EST 130/sqn",
    sqns=5,
)
U(
    "P-ART-HUL",
    "Hülsen's heavy battery",
    P,
    "P-HUL",
    "foot_battery",
    3,
    0,
    "KRO 6 heavy guns; EST crew",
    guns=6,
    crew=6 * PR_GUN_CREW,
    calibre_lb=12,
)


def prussian_regiment(parent, reg, kind, nbns=2, q=4, code=None):
    code = code or reg.split()[0][:4].upper().replace("Ü", "U").replace("Ö", "O")
    for b in ["I", "II"] if nbns == 2 else ["I"]:
        U(
            f"P-{code}-{b}",
            f"{b}./{reg}" if nbns == 2 else reg,
            P,
            parent,
            kind,
            q,
            PR_LINE_BN,
            "KRO; EST line bn",
            battalion_guns=2,
        )


prussian_regiment("P-PAN", "Bornstedt", "line", code="BORN")
prussian_regiment("P-PAN", "Anhalt-Dessau", "line", code="ANHD")
prussian_regiment("P-FRA", "Hülsen", "line", code="HULS")
prussian_regiment("P-FRA", "Braunschweig-Bevern", "line", code="BRBE")
for code, name in [
    ("WAN", "Grenadier Battalion Wangenheim"),
    ("MOL", "Grenadier Battalion Möllendorff"),
    ("KAH", "Grenadier Battalion Kahlden"),
]:
    U(
        f"P-{code}",
        name,
        P,
        "P-FLG",
        "grenadier",
        5,
        PR_GREN_BN,
        "KRO; EST 500/grenadier bn",
        battalion_guns=2,
    )
prussian_regiment("P-MAN", "Kalckstein", "line", code="KALC")
prussian_regiment("P-MAN", "Prinz Moritz von Anhalt", "line", code="PMOR")
prussian_regiment("P-MAN", "Manteuffel", "line", code="MANT")
U(
    "P-GEM",
    "Grenadier Battalion Gemmingen",
    P,
    "P-PUT",
    "grenadier",
    5,
    PR_GREN_BN,
    "KRO; EST 500/grenadier bn",
    battalion_guns=2,
)
U(
    "P-LGD",
    "I./Leibgarde (Tauentzien)",
    P,
    "P-PUT",
    "line",
    5,
    PR_LINE_BN,
    "KRO; EST line bn",
    battalion_guns=2,
)
prussian_regiment("P-PUT", "Kreytzen Fusiliers", "fusilier", code="KREY")
prussian_regiment("P-ING", "Prinz Heinrich Fusiliers", "fusilier", code="PHEI")
prussian_regiment("P-ING", "Wied Fusiliers", "fusilier", code="WIED")
for uid, name, parent, kind, sqns, q in [
    ("P-CAR", "Leib-Carabiniers", "P-KRK", "cuirassier", 5, 4),
    ("P-LRP", "Leibregiment zu Pferde", "P-KRK", "cuirassier", 5, 4),
    ("P-KYA", "Kyau Cuirassiers", "P-KRK", "cuirassier", 5, 4),
    ("P-KRC", "Krockow Cuirassiers", "P-KRK", "cuirassier", 5, 4),
    ("P-GDC", "Garde du Corps", "P-SCH", "cuirassier", 1, 5),
    ("P-SCC", "Schönaich Cuirassiers", "P-SCH", "cuirassier", 5, 4),
    ("P-DRI", "Driesen Cuirassiers", "P-SCH", "cuirassier", 5, 4),
    ("P-BLA", "Blanckensee Dragoons", "P-NOR", "dragoon", 5, 4),
    ("P-KAT", "Katte Dragoons", "P-NOR", "dragoon", 5, 4),
    ("P-MED", "Meinicke Dragoons", "P-MEI", "dragoon", 5, 4),
    ("P-ROC", "Rochow Cuirassiers", "P-KRO", "cuirassier", 5, 4),
    ("P-PVP", "Prinz von Preußen Cuirassiers", "P-KRO", "cuirassier", 5, 4),
    ("P-NOD", "Normann Dragoons", "P-KRO", "dragoon", 5, 4),
]:
    U(uid, name, P, parent, kind, q, sqns * PR_CUIR_SQN, "KRO sqns; EST 130/sqn", sqns=sqns)
U(
    "P-ART-1",
    "Heavy battery (first)",
    P,
    "P-ART",
    "foot_battery",
    3,
    0,
    "KRO: 8 x 12-pdr + 2 howitzers (split EST)",
    guns=10,
    crew=10 * PR_GUN_CREW,
    calibre_lb=12,
)
U(
    "P-ART-2",
    "Heavy battery (second)",
    P,
    "P-ART",
    "foot_battery",
    3,
    0,
    "KRO: 7 x 12-pdr + 2 howitzers + 3 mortars (split EST)",
    guns=12,
    crew=12 * PR_GUN_CREW,
    calibre_lb=12,
)

# --------------------------------------------------------------------------- Austria
A = "austria"
# NAF regimental strengths (men incl. grenadier companies). L. Daun and Harrach have none in
# 757FAR; they get the residual of NAF's infantry total (35,160) over the listed regiments.
NAF_INF = {
    "Erzherzog Carl": 1310,
    "Moltke": 2200,
    "Puebla": 2300,
    "Arenberg": 2320,
    "Türheim": 2140,
    "Neipperg": 1900,
    "Gaisruck": 1330,
    "Haller": 1460,
    "Deutschmeister": 1560,
    "Baden-Baden": 1260,
    "Botta": 2120,
    "Los Rios": 620,
    "Salm": 1190,
    "Platz": 860,
    "Starhemberg": 900,
    "d'Arberg": 420,
    "Sachsen-Gotha": 550,
    "Mercy-Argenteau": 670,
    "de Ligne": 550,
}
NAF_GRENZ = {
    "Warasdiner-Creutzer": 700,
    "Gradiskaner": 1290,
    "Banal": 930,
    "Karlstädter-Szluiner": 1320,
    "Brooder": 1160,
}
NAF_INF_TOTAL, NAF_CAV_TOTAL = 35_160, 18_630
resid = NAF_INF_TOTAL - sum(NAF_INF.values()) - sum(NAF_GRENZ.values())
NAF_INF["Leopold Daun"] = resid * 3 / 5  # KRO 3 bns
NAF_INF["Harrach"] = resid * 2 / 5  # KRO 2 bns
# Picked men (Kommandierte, KRO ~800) and the two converged grenadier battalions (KRO: 4 + 6
# companies; EST 100 men/company) come out of the line regiments, pro rata (EST).
KOMM_INF, GREN_SORO, GREN_FIOR = 800, 400, 600
carve = (KOMM_INF + GREN_SORO + GREN_FIOR) / sum(NAF_INF.values())
NAF_INF = {k: v * (1 - carve) for k, v in NAF_INF.items()}

NAF_CAV = {
    "Festetics": 570,
    "Dessewffy": 90,
    "Morocz": 730,
    "Kaiser": 1300,
    "Karlstädter GH": 150,
    "Prinz Karl": 610,
    "Prinz Albrecht": 400,
    "Brühl": 1000,
    "Banal GH": 130,
    "Warasdiner GH": 60,
    "Splényi": 280,
    "Esterházy": 240,
    "Jazygier-Kumanier": 860,
    "Baranyay": 240,
    "Hadik": 200,
    "Kálnoky": 700,
    "Nádasdy": 400,
    "Savoyen": 650,
    "Kolowrat": 570,
    "Kalkreuth": 710,
    "Ligne": 520,
    "Portugal": 530,
    "Schmerzing": 580,
    "O'Donell": 610,
    "Jung-Modena": 420,
    "Saxon Karabiniergarde": 370,
    "Serbelloni": 650,
    "Porporati": 500,
    "Hessen-Darmstadt": 560,
    "Gelhay": 540,
    "Alt-Modena": 570,
    "Sachsen-Gotha Dragoons": 650,
}
cres = NAF_CAV_TOTAL - sum(NAF_CAV.values())
NAF_CAV["Birkenfeld"] = cres / 2  # no strength in 757FAR: residual, split evenly (EST)
NAF_CAV["Württemberg"] = cres / 2
KOMM_CAV = 1000  # KRO; drawn from the German (cuirassier/dragoon) regiments pro rata (EST)
HEAVY_REGTS = [
    "Savoyen",
    "Kolowrat",
    "Kalkreuth",
    "Ligne",
    "Portugal",
    "Schmerzing",
    "O'Donell",
    "Birkenfeld",
    "Jung-Modena",
    "Württemberg",
    "Serbelloni",
    "Porporati",
    "Hessen-Darmstadt",
    "Gelhay",
    "Alt-Modena",
    "Sachsen-Gotha Dragoons",
]
hv = sum(NAF_CAV[k] for k in HEAVY_REGTS)
for k in HEAVY_REGTS:
    NAF_CAV[k] *= 1 - KOMM_CAV / hv
A_GUN_CREW = 12  # EST per heavy piece incl. labourers

F(
    "A",
    "Imperial Army",
    A,
    "Daun",
    None,
    "army",
    ["the army", "the Imperial army", "the Austrian army"],
)
F(
    "A-NAD",
    "Nádasdy's corps",
    A,
    "Nádasdy",
    "A",
    "wing",
    ["the right flank corps", "Nadasdy's corps", "the light horse", "Nádasdy's cavalry"],
)
F("A-MOR", "Morocz's division", A, "Morocz", "A-NAD", "column", ["Morocz"])
F("A-SCH", "Schröger's hussars", A, "Schröger", "A-MOR", "brigade", ["Schröger's brigade"])
F("A-ERD", "Erdödy's hussars", A, "Erdödy", "A-MOR", "brigade", ["Erdödy's brigade"])
F(
    "A-NOS",
    "Saxon chevaux-légers",
    A,
    "Nostitz",
    "A-MOR",
    "brigade",
    ["the Saxons", "the Saxon cavalry", "Nostitz's brigade", "Benkendorf"],
)
F("A-HAD", "Hadik's division", A, "Hadik", "A-NAD", "column", ["Hadik"])
F("A-SZE", "Széchényi's hussars", A, "Széchényi", "A-HAD", "brigade", ["Széchényi's brigade"])
F("A-PAL", "Pálffy's hussars", A, "Pálffy", "A-HAD", "brigade", ["Pálffy's brigade"])
F("A-BAB", "Babocsay's hussars", A, "Babocsay", "A-HAD", "brigade", ["Babocsay's brigade"])
F(
    "A-STK",
    "Kommandierte cavalry",
    A,
    "Starhemberg (GM)",
    "A-NAD",
    "brigade",
    ["the picked horse", "the Kommandierten", "Starhemberg's picked cavalry"],
)
F(
    "A-GRZ",
    "Grenzer in the villages",
    A,
    "Grenzer post commanders (unrecorded)",
    "A-NAD",
    "brigade",
    ["the Croats", "the Grenzer", "the village garrisons"],
)
F(
    "A-RWC",
    "Right-wing cavalry",
    A,
    "Serbelloni",
    "A",
    "wing",
    ["the right-wing cavalry", "Serbelloni's cavalry", "the cuirassiers of the right"],
)
F(
    "A-BDA",
    "Benedikt Daun's cavalry",
    A,
    "Benedikt Daun",
    "A-RWC",
    "brigade",
    ["first-line cavalry of the right", "Trauttmansdorff's brigade"],
)
F(
    "A-ODO",
    "O'Donell's division",
    A,
    "O'Donell",
    "A-RWC",
    "brigade",
    ["O'Donell", "O'Donell's cavalry"],
)
F(
    "A-CEN",
    "Centre infantry",
    A,
    "Marschall",
    "A",
    "wing",
    ["the centre", "the Austrian infantry", "Marschall's infantry", "the main line"],
)
F("A-AND", "Andlau's division", A, "Andlau", "A-CEN", "column", ["Andlau"])
F("A-EST", "Esterházy's brigade", A, "Esterházy (GM)", "A-AND", "brigade", ["Esterházy's infantry"])
F("A-MAY", "Mayern's brigade", A, "Mayern", "A-AND", "brigade", ["Mayern"])
F("A-PUE", "Puebla's division", A, "Puebla", "A-CEN", "column", ["Puebla"])
F("A-GEM", "Gemmingen's brigade", A, "Gemmingen", "A-PUE", "brigade", ["Gemmingen"])
F("A-ANG", "Angern's brigade", A, "Angern", "A-PUE", "brigade", ["Angern"])
F(
    "A-STA",
    "Starhemberg's division",
    A,
    "Starhemberg",
    "A-CEN",
    "column",
    ["Starhemberg's infantry", "the second line infantry"],
)
F("A-KTD", "Krottendorf's brigade", A, "Krottendorf", "A-STA", "brigade", ["Krottendorf"])
F("A-WUL", "Wulffen's brigade", A, "Wulffen", "A-STA", "brigade", ["Wulffen"])
F("A-SIN", "Sincère's division", A, "Sincère", "A-CEN", "column", ["Sincère", "Sincere's division"])
F("A-PLO", "Plonquet's brigade", A, "Plonquet", "A-SIN", "brigade", ["Plonquet"])
F(
    "A-GRE",
    "Grenadier reserve",
    A,
    "Grenadier reserve commander (unrecorded)",
    "A-CEN",
    "brigade",
    ["the grenadiers", "the Austrian grenadiers"],
)
F("A-RES", "Reserve", A, "Colloredo", "A", "wing", ["the reserve", "Colloredo's reserve"])
F("A-WIE", "Wied's division", A, "Wied", "A-RES", "column", ["Wied", "Wied's infantry"])
F("A-REI", "Reichlin's brigade", A, "Reichlin", "A-WIE", "brigade", ["Reichlin"])
F("A-MUF", "Müffling's brigade", A, "Müffling", "A-WIE", "brigade", ["Müffling"])
F("A-LUT", "Lützow's division", A, "Lützow", "A-RES", "column", ["Lützow", "the reserve cavalry"])
F("A-CAS", "Castiglione's brigade", A, "Castiglione", "A-LUT", "brigade", ["Castiglione"])
F("A-KOB", "Köbel's brigade", A, "Köbel", "A-LUT", "brigade", ["Köbel"])
F(
    "A-LWC",
    "Left-wing cavalry",
    A,
    "Stampach",
    "A",
    "wing",
    ["the left-wing cavalry", "Stampach's cavalry", "the cavalry of the left"],
)
F(
    "A-KOL",
    "Kolowrat's cavalry",
    A,
    "Kolowrat",
    "A-LWC",
    "brigade",
    ["first-line cavalry of the left"],
)
F("A-WOL", "Wöllwarth's division", A, "Wöllwarth", "A-LWC", "brigade", ["Wöllwarth"])
F(
    "A-BEC",
    "Beck's flank guard",
    A,
    "Beck",
    "A",
    "brigade",
    ["Beck's Croats", "the left flank guard", "Beck's brigade"],
)
F(
    "A-ART",
    "Artillery",
    A,
    "Feuerstein",
    "A",
    "brigade",
    ["the artillery", "the Austrian guns", "the heavy batteries", "Feuerstein's guns"],
)

ROMAN = ["I", "II", "III"]


def austrian_regiment(
    parent, reg, nbns, code, kind="line", q=3, strength=None, src="NAF strength; KRO bns"
):
    men = (strength if strength is not None else NAF_INF[reg]) / nbns
    guns = 1 if kind == "grenzer" else 2  # KRO: 84 bn guns for the line, 9 for 9 Grenzer bns
    for k in range(nbns):
        b = ROMAN[k]
        name = f"{b}./{reg}" if nbns > 1 else reg
        U(
            f"A-{code}-{b}" if nbns > 1 else f"A-{code}",
            name,
            A,
            parent,
            kind,
            q,
            men,
            src,
            battalion_guns=guns,
        )


austrian_regiment("A-EST", "Erzherzog Carl", 2, "ECAR")
austrian_regiment("A-EST", "Moltke", 3, "MOLT")
austrian_regiment("A-MAY", "Puebla", 3, "PUEB")
austrian_regiment("A-GEM", "Arenberg", 3, "AREN")
austrian_regiment("A-GEM", "Türheim", 3, "TURH")
austrian_regiment("A-ANG", "Leopold Daun", 3, "LDAU", src="NAF residual (EST); KRO bns")
austrian_regiment("A-ANG", "Harrach", 2, "HARR", src="NAF residual (EST); KRO bns")
austrian_regiment("A-KTD", "Neipperg", 3, "NEIP")
austrian_regiment("A-KTD", "Gaisruck", 3, "GAIS")
austrian_regiment("A-WUL", "Haller", 2, "HALL")
austrian_regiment("A-PLO", "Deutschmeister", 2, "DMEI")
austrian_regiment("A-PLO", "Baden-Baden", 2, "BADE")
austrian_regiment("A-PLO", "Botta", 3, "BOTT")
for reg, code in [("Los Rios", "LRIO"), ("Platz", "PLAT"), ("Starhemberg", "STAR")]:
    austrian_regiment("A-REI", reg, 1, code)
austrian_regiment("A-REI", "Salm", 2, "SALM")
for reg, code in [
    ("d'Arberg", "ARBE"),
    ("Sachsen-Gotha", "SAGO"),
    ("Mercy-Argenteau", "MERC"),
    ("de Ligne", "LIGN"),
]:
    austrian_regiment("A-MUF", reg, 1, code)
U(
    "A-GSORO",
    "Grenadier Battalion Soro",
    A,
    "A-GRE",
    "grenadier",
    4,
    GREN_SORO,
    "KRO 4 coys; EST 100/coy",
    battalion_guns=0,
)
U(
    "A-GFIOR",
    "Grenadier Battalion Fiorenza",
    A,
    "A-GRE",
    "grenadier",
    4,
    GREN_FIOR,
    "KRO 6 coys; EST 100/coy",
    battalion_guns=4,
)
austrian_regiment("A-GRZ", "Banal", 2, "BANA", "grenzer", strength=NAF_GRENZ["Banal"])
austrian_regiment(
    "A-GRZ",
    "Karlstädter-Szluiner",
    2,
    "SZLU",
    "grenzer",
    strength=NAF_GRENZ["Karlstädter-Szluiner"],
)
austrian_regiment(
    "A-GRZ", "Warasdiner-Creutzer", 1, "WARA", "grenzer", strength=NAF_GRENZ["Warasdiner-Creutzer"]
)
austrian_regiment("A-BEC", "Gradiskaner", 2, "GRAD", "grenzer", strength=NAF_GRENZ["Gradiskaner"])
austrian_regiment("A-BEC", "Brooder", 2, "BROO", "grenzer", strength=NAF_GRENZ["Brooder"])
U("A-KOMI", "Kommandierte infantry", A, "A-BEC", "line", 4, KOMM_INF, "KRO ~800", battalion_guns=0)


def cav(uid, name, parent, kind, q, men, sqns, src="NAF strength; KRO sqns", split=False):
    if split:
        for b in ("I", "II"):
            U(f"{uid}-{b}", f"{name} {b}", A, parent, kind, q, men / 2, src, sqns=sqns / 2)
    else:
        U(uid, name, A, parent, kind, q, men, src, sqns=sqns)


C = NAF_CAV
cav(
    "A-FEST",
    "Festetics Hussars (with Dessewffy sqn)",
    "A-SCH",
    "hussar",
    3,
    C["Festetics"] + C["Dessewffy"],
    7,
)
cav("A-MORH", "Morocz Hussars", "A-SCH", "hussar", 3, C["Morocz"], 6)
cav(
    "A-KAIS",
    "Kaiser Hussars (with Karlstädter sqns)",
    "A-ERD",
    "hussar",
    3,
    C["Kaiser"] + C["Karlstädter GH"],
    8,
    split=True,
)
cav("A-PKAR", "Prinz Karl Chevaux-légers", "A-NOS", "dragoon", 3, C["Prinz Karl"], 4)
cav("A-PALB", "Prinz Albrecht Chevaux-légers", "A-NOS", "dragoon", 3, C["Prinz Albrecht"], 3)
cav("A-BRUH", "Graf Brühl Chevaux-légers", "A-NOS", "dragoon", 3, C["Brühl"], 4, split=True)
cav(
    "A-SZGH",
    "Grenz-hussars (Banal, Warasdin) with Splényi",
    "A-SZE",
    "hussar",
    2,
    C["Banal GH"] + C["Warasdiner GH"] + C["Splényi"],
    6,
)
cav("A-ESTH", "Esterházy Hussars", "A-PAL", "hussar", 3, C["Esterházy"], 2)
cav(
    "A-JAZY",
    "Jazygier-Kumanier Hussars",
    "A-PAL",
    "hussar",
    3,
    C["Jazygier-Kumanier"],
    5,
    split=True,
)
cav("A-BARA", "Baranyay Hussars", "A-PAL", "hussar", 3, C["Baranyay"], 2)
cav("A-HADH", "Hadik Hussars", "A-BAB", "hussar", 3, C["Hadik"], 2)
cav("A-KALN", "Kálnoky Hussars", "A-BAB", "hussar", 3, C["Kálnoky"], 6)
cav("A-NADH", "Nádasdy Hussars", "A-BAB", "hussar", 3, C["Nádasdy"], 5)
cav("A-KOMC", "Kommandierte cavalry", "A-STK", "cuirassier", 4, KOMM_CAV, 0, "KRO ~1,000")
for uid, name, parent, kind, key, sq in [
    ("A-SAVO", "Savoyen Dragoons", "A-BDA", "dragoon", "Savoyen", 6),
    ("A-KOLO", "Kolowrat Dragoons", "A-BDA", "dragoon", "Kolowrat", 6),
    ("A-KALK", "Kalkreuth Cuirassiers", "A-BDA", "cuirassier", "Kalkreuth", 6),
    ("A-LIGD", "de Ligne Dragoons", "A-ODO", "dragoon", "Ligne", 6),
    ("A-PORT", "Infant von Portugal Cuirassiers", "A-ODO", "cuirassier", "Portugal", 6),
    ("A-SCHM", "Schmerzing Cuirassiers", "A-ODO", "cuirassier", "Schmerzing", 6),
    ("A-ODOC", "O'Donell Cuirassiers", "A-CAS", "cuirassier", "O'Donell", 6),
    ("A-BIRK", "Birkenfeld Cuirassiers", "A-CAS", "cuirassier", "Birkenfeld", 6),
    ("A-JMOD", "Jung-Modena Dragoons", "A-KOB", "dragoon", "Jung-Modena", 5),
    ("A-WURT", "Württemberg Dragoons", "A-KOB", "dragoon", "Württemberg", 6),
    ("A-SERB", "Serbelloni Cuirassiers", "A-KOL", "cuirassier", "Serbelloni", 6),
    ("A-PORP", "Porporati Dragoons", "A-KOL", "dragoon", "Porporati", 6),
    ("A-HDAR", "Hessen-Darmstadt Dragoons", "A-KOL", "dragoon", "Hessen-Darmstadt", 5),
    ("A-GELH", "Gelhay Cuirassiers", "A-WOL", "cuirassier", "Gelhay", 6),
    ("A-AMOD", "Alt-Modena Cuirassiers", "A-WOL", "cuirassier", "Alt-Modena", 6),
    ("A-SGOD", "Sachsen-Gotha Dragoons", "A-WOL", "dragoon", "Sachsen-Gotha Dragoons", 6),
]:
    src = (
        "NAF residual (EST); KRO sqns"
        if key in ("Birkenfeld", "Württemberg")
        else "NAF strength; KRO sqns"
    )
    cav(uid, name, parent, kind, 3, C[key], sq, src)
cav("A-KARA", "Saxon Karabiniergarde", "A-KOB", "cuirassier", 4, C["Saxon Karabiniergarde"], 4)
for k in range(6):
    cal = 12 if k < 2 else 6
    U(
        f"A-ART-{k + 1}",
        f"Heavy battery {k + 1} ({cal}-pdr)",
        A,
        "A-ART",
        "foot_battery",
        4,
        0,
        "KRO 60 heavy guns in 3 batteries; split into 10-gun bodies and calibres EST",
        guns=10,
        crew=10 * A_GUN_CREW,
        calibre_lb=cal,
    )

for u in units:
    if u["kind"] == "foot_battery":
        u["men"] = u["crew"]

# =========================================================================== deployment at 13:00
road = [tuple(p) for p in extract["kaiserstrasse"]]
cum = [0.0]
for a, b in itertools.pairwise(road):
    cum.append(cum[-1] + math.dist(a, b))


def road_at(s):
    """Point and unit tangent (eastward) at arc length s from the west end."""
    s = min(max(s, 0.0), cum[-1])
    for k in range(len(road) - 1):
        if cum[k + 1] >= s:
            t = (s - cum[k]) / max(cum[k + 1] - cum[k], 1e-9)
            (x0, y0), (x1, y1) = road[k], road[k + 1]
            L = math.hypot(x1 - x0, y1 - y0) or 1.0
            return (x0 + t * (x1 - x0), y0 + t * (y1 - y0)), ((x1 - x0) / L, (y1 - y0) / L)
    return road[-1], (1.0, 0.0)


def s_at_x(x):
    for k in range(len(road) - 1):
        if road[k][0] <= x <= road[k + 1][0]:
            return cum[k] + (x - road[k][0]) / (road[k + 1][0] - road[k][0]) * (cum[k + 1] - cum[k])
    return 0.0 if x < road[0][0] else cum[-1]


def bearing(dx, dy):
    return round(math.degrees(math.atan2(dx, dy)) % 360, 1)


def cover_at(x, y):
    return int(COVER[min(max(int(y // CELL), 0), NY - 1), min(max(int(x // CELL), 0), NX - 1)])


def dry(x, y):
    """Nudge a position off water to the nearest dry cell (spiral search, 25 m steps)."""
    if cover_at(x, y) != WATER:
        return x, y
    for r in range(1, 40):
        for k in range(16):
            a = 2 * math.pi * k / 16
            px, py = x + r * CELL * math.cos(a), y + r * CELL * math.sin(a)
            if cover_at(px, py) != WATER:
                return px, py
    raise ValueError("no dry ground near", x, y)


dep: dict[str, dict] = {}
LEN = {"inf": 150.0, "cav": 250.0, "art": 200.0}
GAP = 20.0


def arm_of(u):
    return (
        "art"
        if u["kind"].endswith("battery")
        else ("cav" if u["kind"] in ("cuirassier", "dragoon", "hussar") else "inf")
    )


def place(uid, x, y, facing, state, fatigue=0.0):
    x, y = dry(x, y)
    dep[uid] = {
        "x": round(x, 1),
        "y": round(y, 1),
        "facing_deg": facing,
        "state": state,
        "fatigue": fatigue,
    }


UNIT = {u["id"]: u for u in units}
PR_FATIGUE = 10.0  # EST: marched ~7 km from Planian since 06:00, then a three-hour halt


def column(ids, head_s, offset=0.0, state="column"):
    """Bodies in march column along the Kaiserstrasse (offset > 0: north of it), head first."""
    s = head_s
    for uid in ids:
        u = UNIT[uid]
        L = LEN[arm_of(u)]
        (x, y), (tx, ty) = road_at(s - L / 2)
        nx, ny = -ty, tx  # left normal (north for an eastward road)
        st = "limbered" if arm_of(u) == "art" else state
        place(uid, x + offset * nx, y + offset * ny, bearing(tx, ty), st, PR_FATIGUE)
        s -= L + GAP
    return s


def line(ids, a, b, facing, state="line", fatigue=0.0):
    """Bodies evenly spread along segment a->b."""
    n = len(ids)
    for k, uid in enumerate(ids):
        t = (k + 0.5) / n
        st = "unlimbered" if arm_of(UNIT[uid]) == "art" else state
        place(uid, a[0] + t * (b[0] - a[0]), a[1] + t * (b[1] - a[1]), facing, st, fatigue)


def ids_of(*parents):
    return [u["id"] for p in parents for u in units if u["parent"] == p]


# --- Prussia (KRO march order at 13:00; positions EST along it)
zs = s_at_x(6641)  # Zlaté Slunce inn
# Zieten's 50 hussar squadrons deployed in two lines astride the road east of the inn, facing
# Nádasdy (EST). First line north of the road, second line south.
hus = ids_of("P-ZIE")
p0, t0 = road_at(zs + 1500)
nx0, ny0 = -t0[1], t0[0]
first, second = hus[:5], hus[5:]
line(
    first,
    (p0[0] - 700 * t0[0] + 900 * nx0, p0[1] - 700 * t0[1] + 900 * ny0),
    (p0[0] + 300 * t0[0] - 300 * nx0, p0[1] + 300 * t0[1] - 300 * ny0),
    135.0,
    "line",
    PR_FATIGUE,
)
line(
    second,
    (p0[0] - 1100 * t0[0] + 700 * nx0, p0[1] - 1100 * t0[1] + 700 * ny0),
    (p0[0] - 100 * t0[0] - 500 * nx0, p0[1] - 100 * t0[1] - 500 * ny0),
    135.0,
    "line",
    PR_FATIGUE,
)
# Hülsen: 3 grenadier bns, 6 heavy guns, 4 bns, Stechow closing (KRO order of march)
s = column(
    [
        "P-NIM",
        "P-WAL",
        "P-FIN",
        "P-ART-HUL",
        "P-SCHU-I",
        "P-SCHU-II",
        "P-MUNC-I",
        "P-MUNC-II",
        "P-STE",
    ],
    zs + 700,
)
# first column: 20 cuirassier sqns, 14 bns, 11 sqns (KRO)
s = column(ids_of("P-KRK"), s - 150)
s = column(ids_of("P-PAN") + ids_of("P-FRA") + ids_of("P-MAN"), s - 100)
s = column(ids_of("P-SCH"), s - 100)
# second column north of the road: Normann's 10 sqns, 8 bns, Meinicke closing (KRO)
s2 = column(ids_of("P-NOR"), zs - 400, offset=450)
s2 = column(ids_of("P-ING") + ids_of("P-PUT"), s2 - 100, offset=450)
s2 = column(ids_of("P-MEI"), s2 - 100, offset=450)
# flank guard grenadiers level with the head of the first column's infantry, further north (KRO)
column(ids_of("P-FLG"), s_at_x(dep["P-BORN-I"]["x"]) + 300, offset=900)
# third column: Krosigk's 15 sqns (KRO), north of the second column
column(ids_of("P-KRO"), zs - 800, offset=1300)
# reserve heavy guns with the head of the first column's infantry (EST)
column(["P-ART-1", "P-ART-2"], s_at_x(dep["P-BORN-I"]["x"]) + 50, offset=180)

# --- Austria (KRO: three lines on the north slope of the heights, ~2 km south of the road)
crest = [tuple(p) for p in extract["crest"]]


def crest_y(x):
    if x <= crest[0][0]:
        return 2900.0 if x < 4000 else crest[0][1]
    for (x0, y0), (x1, y1) in itertools.pairwise(crest):
        if x0 <= x <= x1:
            return y0 + (x - x0) / (x1 - x0) * (y1 - y0)
    return crest[-1][1]


def austrian_line(ids, x_east, frontage, dy, facing=0.0, state="line"):
    """Lay bodies westward from x_east, `frontage` m each, dy m north of the crest."""
    x = x_east
    for uid in ids:
        f = frontage[arm_of(UNIT[uid])]
        cx = x - f / 2
        st = "unlimbered" if arm_of(UNIT[uid]) == "art" else state
        place(uid, cx, crest_y(cx) + dy, facing, st)
        x -= f
    return x


FRONT = {"inf": 175.0, "cav": 330.0, "art": 250.0}
x = austrian_line(ids_of("A-BDA"), 7800, FRONT, 350)
x = austrian_line(ids_of("A-EST", "A-MAY", "A-GEM", "A-ANG"), x - 50, FRONT, 350)
austrian_line(ids_of("A-KOL"), x - 50, FRONT, 350)
x = austrian_line(ids_of("A-ODO"), 7800, FRONT, 50)
x = austrian_line(ids_of("A-KTD", "A-WUL", "A-PLO"), x - 50, FRONT, 50)
austrian_line(ids_of("A-WOL"), x - 50, FRONT, 50)
# reserve behind the right wing at noon (KRO: Colloredo behind the second line of the right)
austrian_line(ids_of("A-REI", "A-MUF"), 7700, FRONT, -450)
austrian_line(ids_of("A-CAS", "A-KOB"), 7900, FRONT, -850)
austrian_line(ids_of("A-GRE"), 5600, FRONT, -300)
# heavy batteries in front of the first line (KRO: villages "well beset with batteries")
for k, xa in enumerate([7500, 6650, 5800, 4900, 4000, 3100]):
    place(f"A-ART-{k + 1}", xa, crest_y(xa) + 500, 0.0, "unlimbered")
# Grenzer in the villages (KRO): Banal in Krzeczhorz, Szluin in Chotzemitz, Warasdin in Pobor
for uid, (la, lo), dx in [
    ("A-BANA-I", (50.0255, 15.1268), -60),
    ("A-BANA-II", (50.0255, 15.1268), 60),
    ("A-SZLU-I", (50.0294, 15.0978), -60),
    ("A-SZLU-II", (50.0294, 15.0978), 60),
    ("A-WARA", (50.0242, 15.0492), 0),
]:
    vx, vy = (float(c) for c in to_local(la, lo))
    place(uid, vx + dx, vy, 0.0, "skirmish")
# Beck's flank guard on the left, west of Pobor towards Hradenin (EST from KRO's narrative)
line(ids_of("A-BEC"), (1500, 3700), (2400, 4100), 330.0, "skirmish")
# Nádasdy's corps on the heights east of Krzeczhorz in two lines facing the road (KRO; EST
# geometry): first line Morocz's division with the Saxons and the picked horse on its left
# (west), second line Hadik's division 300 m behind.
n1 = ids_of("A-NOS") + ids_of("A-STK") + ids_of("A-SCH") + ids_of("A-ERD")
line(n1, (8500, 2950), (10300, 4150), 315.0)
line(ids_of("A-SZE", "A-PAL", "A-BAB"), (8750, 2700), (10500, 3900), 315.0)

hq = {
    "P": [6641.0, 4961.0],  # Frederick at the Zlaté Slunce inn (KRO)
    "A": [round(kx, 1), round(ky, 1)],
}  # Daun on Křečhoř hill (EST)
hq = {k: list(dry(*v)) for k, v in hq.items()}

# =========================================================================== totals and meta
tot = {P: 0, A: 0}
for u in units:
    tot[u["side"]] += u["men"]
counts = {s: sum(1 for u in units if u["side"] == s) for s in (P, A)}


def sunset_local_solar(lat=50.03, lon=15.12, doy=169, year=1757):
    """NOAA solar position, sunset in local apparent solar time (period clocks)."""
    g = 2 * math.pi / 365 * (doy - 1)
    decl = (
        0.006918
        - 0.399912 * math.cos(g)
        + 0.070257 * math.sin(g)
        - 0.006758 * math.cos(2 * g)
        + 0.000907 * math.sin(2 * g)
        - 0.002697 * math.cos(3 * g)
        + 0.00148 * math.sin(3 * g)
    )
    phi = math.radians(lat)
    out = {}
    for name, zen in (("sunset", 90.833), ("civil_dusk", 96.0)):
        ha = math.degrees(
            math.acos(
                math.cos(math.radians(zen)) / (math.cos(phi) * math.cos(decl))
                - math.tan(phi) * math.tan(decl)
            )
        )
        m = 720 + 4 * ha
        out[name] = f"{int(m // 60):02d}:{round(m % 60):02d}"
    return out


sun = sunset_local_solar()
meta = {
    "battle": "Kolín",
    "date": "1757-06-18",
    "start": "13:00",
    "time_basis": "local apparent solar time, as in the period accounts",
    "sunset": sun["sunset"],
    "civil_dusk": sun["civil_dusk"],
    "historical_end": (
        "about 20:00-21:00 (KRO: issue uncertain until 19:00-20:00; CDB active period ends 21:00)"
    ),
    "weather": "dry, sunny, warm; morning fog lifted before the march (CDB wx D/S/T; KRO)",
    "sides": {
        P: {"commander": "Frederick II", "army": "P", "role": "attacker"},
        A: {"commander": "Daun", "army": "A", "role": "defender"},
    },
    "strength_documented": tot,
    "bodies": counts,
    "strength_sources": {
        P: "CDB90 32,000 (KRO ~33,000); allocated to KRO's 32 bns, 116 sqns, 28 heavy pieces",
        A: "NAF 35,160 inf + 18,630 cav = 53,790, plus heavy-gun crews (KRO ~54,000); CDB90 44,000",
    },
    "par": {
        "source": "CDB90 isqno 67",
        "prussia": {"str": 32000, "cas": 13768},
        "austria": {"str": 44000, "cas": 9000},
        "winner": A,
        "duration_min": 420,
    },
    "projection": {
        "crs": "UTM zone 33N (EPSG:32633), WGS84",
        "origin_utm": [501000.0, 5538100.0],
        "note": "local x = easting - 501000, y = northing - 5538100; SW corner of the grid",
        "cell_m": 25.0,
        "shape": [int(NY), int(NX)],
    },
    "sources": [
        "https://copernicus-dem-30m.s3.amazonaws.com/ (Copernicus GLO-30 DSM, tiles N49/N50 E015)",
        "https://overpass-api.de/api/interpreter (OpenStreetMap, fetched 2026-10-16, ODbL)",
        "https://www.generalstaff.org/NAF/Pt_I_1600-1783/757fas.pdf",
        "https://www.generalstaff.org/NAF/Pt_I_1600-1783/757far.pdf",
        "https://www.kronoskaf.com/syw/index.php?title=1757-06-18_-_Battle_of_Kolin",
        "https://github.com/jrnold/CDB90 (isqno 67)",
    ],
    "doc": "docs/kolin-test-pack.md",
}

for name, obj in [
    ("features.json", features),
    ("oob.json", {"sides": [P, A], "formations": formations, "units": units}),
    ("deployment.json", {"start": "13:00", "units": dep, "hq": hq}),
    ("meta.json", meta),
]:
    (DATA / name).write_text(json.dumps(obj, indent=1, ensure_ascii=False) + "\n")
print("strength", tot, "bodies", counts, "features", len(features), "sun", sun)
print("PR_LINE_BN", round(PR_LINE_BN, 1), "L.Daun+Harrach resid", resid, "cav resid", cres)
