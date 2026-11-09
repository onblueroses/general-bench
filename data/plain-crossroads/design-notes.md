# Plain (Teasel Village): design notes for the data pack

Why every number in `data/plain-crossroads/` is what it is. The ruling is
`docs/battles/README.md` ("Plain's armies", "The brief", "The verdict"); the design doc is
`docs/battles/plain.md`. Everything here is a design
choice: **LAD** is fixed by the ladder ruling, **DES** is chosen here to carry it out, **EST**
is an estimate with its rule. Nothing is sourced history.

## Ground

| item | value | tag | why |
|---|---|---|---|
| box | 8 km east-west by 6 km north-south | LAD | |
| raster | 25 m cells, 321 x 241, origin (-12.5, -12.5) | DES | every pack uses 25 m. An odd grid puts the crossroads (4,000, 3,000) at the centre of a cell, so the raster is exactly invariant under the 180° rotation and the road is one cell on the centre line. With an even grid (320 x 240, tried first) the crossroads fell on a cell corner, the village's cell lay in Blue's quadrant, and the bot game went to Blue every seed. The raster therefore spans 12.5 m beyond the 8 x 6 km box on every side |
| elevation | 200 m everywhere | EST | flat; any constant gives the same physics |
| cover | open, except the village and the two roads | LAD | |
| village | a disc of VILLAGE cover, radius 200 m, about the crossroads | EST | a crossroads village some 400 m across; the possession radius (250 m) covers it and 50 m of fields |
| roads | High road (west-east) and Drove road (south-north), one cell, edge to edge through the crossroads; road cells inside the village stay road | LAD / DES | roads are drawn after villages |
| village feature | a **point** at the crossroads, aliases "the village", "the crossroads" | DES | the verdict judges possession within musket range of the crossroads; `verdict.possession` measures from the feature, so a point makes the test exactly the ruling (a polygon would add its radius) |
| farms | Mallow (NW), Vetch (NE), Yarrow (SE), Burdock (SW), 2,000 m from the crossroads on the diagonals, no cover | LAD | rotation pairs Mallow-Yarrow, Vetch-Burdock |
| exits | West, East, South, North exit, 10 m inside the box on the road, radius 100 m | DES | kind `exit`, so a routed body near an edge flees off the map (docs/pack-format.md, Exits) and an army can be marched off |
| clock | start 09:00, end 16:00, play-on to 18:00 | LAD | `meta.end` 16:00; `mission.play_on_min` 120 |
| daylight | season "high summer", `daylight_date` 07-05, sunrise 03:53, sunset 20:07, civil dusk 20:50 (local apparent solar time, 50° N) | EST | a Central European summer day; the light never limits play |

## Names

Invented: a place is an English word plus the kind's noun, with a period spelling as alias;
officers are "General <surname>"; units are "<Side> <arm word> NN". Twenty-four commander
surnames, none a common word or a word of a place, all three or more edits apart; the
formation names are the same on both sides (an army is addressed by its own side's names
only). No GeoNames check was run.

## Armies (LAD, both sides identical)

| formation | bodies | quality | deployed (Red; Blue is the rotation) |
|---|---|---|---|
| First, Second, Third brigade (line) | 2 battalions of 700, 2 battalion guns each | 3 | first line, x 500 (3.5 km from the crossroads), left to right, brigade centres 350 m apart |
| Hussar brigade | 2 regiments of 400 | 3 | first line, left wing |
| Dragoon brigade | 2 regiments of 400 | 3 | first line, right wing |
| Fifth, Fourth, Sixth brigade | 2 battalions of 700 | 2, 3, 2 | second line, x 250, behind the first |
| Cuirassier brigade | 2 regiments of 400 | 4 | second line, behind the dragoons |
| Grenadier brigade | 2 battalions of 700 | 5 | behind the centre, x 100, in column |
| Reserve artillery | 2 batteries of 8 x 12-pdr, 120 crew each | 3 | behind the centre, x 100, limbered |
| headquarters | | | x 175, behind the centre |

- 12,440 men a side: 9,800 foot, 2,400 horse and 240 gunners (the ladder's "about 12,200" counts
  foot and horse); 44 guns: 16 reserve 12-pounders and 28 battalion guns.
- Crew 15 a gun (EST, the Kolín rule used by every pack).
- Which line brigades stand where (DES): the three steady brigades in the first line, the two
  new-raised ones on the wings of the second line behind them, the fourth line brigade in the
  second line's centre; the grenadiers as the reserve ("one brigade behind"); the cuirassiers,
  the third horse brigade, behind the right wing. Rotation maps each army's right onto the
  other's right, so both have their dragoons and cuirassiers on the right.
- Intervals (EST): a battalion of 700 in line is 140 m wide (3 ranks, 0.6 m a file), 170 m
  centre to centre with the 30 m interval; a regiment of 400 in line is 180 m, 210 m centre to
  centre; the wings stand 70 m beyond the flank brigades. Foot and horse of the lines start in
  line, the grenadiers in column, the guns limbered.
- The first line stands 3.5 km from the crossroads, so the reserve stands 100 m from the map's
  edge (the box leaves no more room); a routed body flees off the map within 50 m of an edge.
- Ids: `R-<key>-<n>` and `B-<key>-<n>`; sides in `oob.json` are `["red", "blue"]`.

## Roles and the attacker

Both sides have role "meeting engagement". `run.umpire_for` and `grid._attacker` take the side
whose role is exactly "attacker", else the first side in `oob.json`: Red. The umpire's
attacker framing (its situation modifier and "attacker achieved") is therefore Red's, and the
cross report's attacker columns read Red. Neither touches the verdict, which is the ordinal
judge's (`mission.json`).

## Mission and the brief

- `mission.json` holds exactly the ladder's keys (`verdict` ordinal, `objective` Teasel
  Village, `break_share` 0.4, `break_persist_min` 30, `play_on_min` 120, `note`); the judge
  is `kriegsspiel.verdict.OrdinalJudge`.
- `players.md` is what the generals read (the persona's battle layer); `objectives.md` goes to
  the umpire only. Both are built from templates in `tools/` by `tools/build_pack.py`, so the
  two sides' texts differ only in names by construction. Per the ladder's "The brief", the
  players' section carries the mission, the verdict's four points (from
  the ladder verbatim, without the ruling's provenance), the clock, the army's formations with
  their commanders and qualities (quality is not in the narrator's order of battle, so it is
  stated here), and the enemy's order of battle in outline, never where he is. This departs
  from docs/player-prompt.md's "no engine number" by ruling. The rules sheet with the engine's
  numbers, also in the ladder's brief, is not in this pack's text: it belongs to every designed
  battle (`docs/rules-sheet.md`, `meta.json` "rules_sheet").
- Budget: 791 words a side, inside docs/player-prompt.md's 400 to 800; the persona is 2,724 words.
- The umpire section says that under this pack the umpire narrates and does not rule.

## Script (`script.json`)

One plan for both sides, names swapped (`SCRIPT` in `tools/build_pack.py`): the Second
brigade advances on the village by the high road and holds it; the First and Third advance on
its left and right; the second line follows the first; the hussars and dragoons cover the
flanks, the cuirassiers stand behind the dragoons; the grenadiers stay in reserve and go up to
the village at noon; the reserve guns support the Second brigade. Every order names its
addressee first and the village by its name (test: the staff's Lexicon reads them).

The script needs Jev: in `--mode stub` the staff takes every order's first option (HOLD at the
first feature), so a stub script-against-script game is plumbing only. Self-play in stub mode
uses the doctrine bot.

## The doctrine bot on an ordinal mission

`kriegsspiel.bot` plays for the verdict's objective: it holds the village with its infantry,
covers the flanks with its horse and puts its guns on the highest ground near it. It steers by
the objective only and scores nothing.

## Self-play (single games, `bot:strong` both sides, `--mode stub`)

Measured with the ordinal judge when the pack was built, before the engine resolved a tick
simultaneously (see finding 1). A game takes about 2 s of wall time.

| seeds | first contact | verdict | casualties at the end, Red / Blue |
|---|---|---|---|
| 1-5 | 09:41 (the horse wings) | Blue by break at 10:43-10:46, every seed (Red 58-60% of its men in broken bodies, Blue 15-19%); Blue holds the village | 16-18% / 14-16% |

What happens: the horse wings meet first; then the bot sends every battalion of both armies
to the crossroads, about twelve battalions a side meet in column inside 100 m of it at 10:00,
and one or both armies pass 40% broken by 10:15. Possession changes hands three to five times
before the break. No game reaches the end hour.

Two findings, neither the pack's to fix:

1. **The side processed first won a symmetric game.** Blue won every seed. Renaming the
   formation ids so that Red's sort first (`A-...` against `B-...`) gave Red the same win at
   10:52; interleaving only the unit ids did not change it: the engine resolved a tick in id
   order, and on a mirror-image field that order decided. Fixed since: a tick is simultaneous
   and the router is anchored at the field's centre, so renaming the armies or turning the
   field changes no game (`tests/kriegsspiel/test_symmetry.py`).
2. **The bot is a poor calibrator for this battle.** It concentrates everything on the one
   place it is told to hold, so every game is a head-on collision decided by break within two
   hours; the draw share and the possession rule are never exercised. Calibration needs a
   better bot or model games, not a redesign of the field.
