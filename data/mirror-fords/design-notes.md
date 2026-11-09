# Mirror (Plover Village): design notes for the data pack

Why every number in `data/mirror-fords/` is what it is. The ruling is
`docs/battles/README.md` ("The ladder" item 2, "Mirror's ground", and "Mirror's brook,
re-laid", option 5); the design doc is `docs/battles/mirror.md`. Tags as in Plain's notes: **LAD** fixed by the
ruling, **DES** chosen here to carry it out, **EST** an estimate with its rule. Nothing is
sourced history.

## What is Plain's (LAD: "same box, armies, deployment distance, verdict and village")

Built by the same code (`src/kriegsspiel/designed.py`, imported by both builders; Plain
rebuilds byte-identical, `test_pack_mirror.py` checks both builds):

- the box (8 x 6 km), the raster (25 m, 321 x 241, origin (-12.5, -12.5), an odd grid so the
  village is the centre of a cell and `flip` of a raster is its rotation);
- the armies, qualities, unit names, ids, crews, and the deployment: `deployment.json` is
  byte-identical to Plain's (first line 3.5 km from the village, x 500);
- `meta.json` (clock 09:00 to 16:00, play-on to 18:00, high summer, `rules_sheet: true`, roles
  "meeting engagement") but for the battle's name, commanders and doc;
- `mission.json` (ordinal, break 0.4 for 30 minutes, play-on 120) but for the objective's name;
- the scripted plan, with the village renamed; the brief's template
  (`tools/players_template.md`) with the changes below.

Plain's reasons for each of these are in `../plain-crossroads/design-notes.md`.

## Ground

Red's half is built and Blue's is its rotation: every raster layer is computed for Red and
completed with `designed.flip`, every feature is its own image or has a twin, so the pack is
exactly symmetric by construction (`test_pack_mirror.py`: `cover` and `elev` equal their
180° turn element for element; every feature's image is a feature of its kind).

Why the re-lay (the ladder, "Mirror's brook, re-laid"): the first ground ran one brook north to
south through the village with the bridge in it; the 250 m possession disc covered both banks,
each army stood in "the village" on its own bank, and the pilot drew 3 of 5 contested to 18:00.
Any one connected brook that is its own image passes through the centre, so the brook is
broken at the village and slanted to the corners.

Places are given in the brooks' frame (`build_pack.at(t, s)`): `t` metres along
U = (-0.8, 0.6) from the village (towards the north-west corner, which is exactly 5,000 U from
the village), `s` metres along N = (0.6, 0.8), across the brooks towards Blue. The diagonal
s = 0 splits the field into Red's half (s < 0, south-west) and Blue's (s > 0, north-east); Blue's
places are Red's at (-t, -s). U and N have components in fifths, so every place lands on a
round decimetre and its image is exact.

| item | value | tag | why |
|---|---|---|---|
| fields | open, 200 m | EST | Plain's |
| Curlew Brook, Godwit Brook | WATER where \|s\| <= 25 m and t > 500 m: Curlew from 500 m off the village past its ford to the north-west corner (0, 6,000), Godwit its image to the south-east corner (8,000, 0); features are the polylines head, ford, corner | LAD / DES | "two streams rise at a dry saddle about a kilometre wide at the village and run away from it to opposite corners". The heads are 1 km apart; the nearest water cell is 515 m from the village, so the 200 m village disc and the 250 m possession disc are dry (pack test: no water within 500 m). Half-width 25 m, not 12.5: on the slant a one-cell line is a staircase whose cells touch only at corners, and the router samples a coarse edge 8 to 12 m apart; at 25 m the band is 4-connected and any straight line across it runs at least 15 m in water. With water laid across the saddle and the fords removed, no arm's route joins the two starts (pack test, with the fords left in as positive control). Water is impassable to every arm but at a ford (`World.passable`). The names are new: "Dunlin Brook" was one brook and is gone |
| bridge | none | LAD | "no bridge"; the High road crosses no water |
| Plover Village | VILLAGE disc r 200 m about (4,000, 3,000), on the saddle; feature a point at the crossroads | LAD | Plain's village; the fight for it resolves by combat on dry ground, as on Plain |
| Curlew Ford, Godwit Ford | points at (2,400, 4,200) and (5,600, 1,800), t = ±2,000, cell centres; `radius_m` 40 (seven water cells, a front of some 60 m) | LAD | "one ford on each stream two kilometres from the village"; images of each other. Measured: 2,000 m from the village each |
| ford arms | `passable` infantry, cavalry, artillery, train | LAD | "passable by all arms". The engine's default is foot and horse only |
| ford speed | foot and horse 0.5, guns and wagons 0.25 of cross-country speed | LAD / EST | "but slow": the format's half speed for those that wade, a quarter for wheels in a stream bed (EST) |
| Curlew Mill, Godwit Mill | (2,316, 4,188) and its image (5,684, 1,812): t 2,060, s -60, 85 m from the ford on Red's bank of Curlew (Godwit's on Blue's bank of Godwit) | LAD / DES | "with its mill". Points, no cover |
| Heron Ridge (Red's), Bittern Ridge (Blue's) | Heron's crest from (2,960, 3,030) through (2,560, 3,330) to (2,160, 3,630): parallel to Curlew Brook, s = -600, t 850 to 1,850. Bittern's (5,040, 2,970) to (5,840, 2,370). Measured: middle 1,477 m from the village; near end 1,040 m from the village and 1,297 m from the Curlew Ford; far end 618 m from the ford | LAD / DES | "re-placed clear of the water on their own army's side", "a kilometre and a half from the village, within roundshot of it ... and the near ford": a 12-pounder's roundshot reaches 1,400 m (`combat.ROUNDSHOT_RANGE_M[12]`), so guns on the near end reach both the village and the ford. At s = -600 the rise (500 m) ends 100 m short of the water (pack test: no water cell within 500 m of the crest). Trade-off: the wedge between the High road and the brook is 37° wide, too narrow inside roundshot to hold a 500 m rise clear of both, so the near end stands 30 m north of the High road and the road crosses the ridge's southern slope (the crest is still on the army's left) |
| ridge height | 25 m at the crest, falling as cos² to the fields 500 m from it | EST | as before: line of sight masks a body behind the ridge from beyond the brook and the crest sees over it (pack test); foot climb at 0.84 at the steepest; the narrator reads the crest as "25 m above" |
| Siskin Wood (Red's), Linnet Wood (Blue's) | WOOD polygon, Red's beside Godwit Brook, t -2,850 to -1,150 (1.7 km along the brook) and s -1,600 to -300 (1.3 km deep), corners cut: (5,410, 130), (5,760, 680), (5,940, 1,170), (4,900, 1,950), (4,500, 1,750), (4,120, 1,160), (4,240, 820), (5,120, 160); Linnet its image | LAD / DES | "a wood covering each side's march to its right-hand ford", "stop about 300 m short of the water". The Godwit lane runs 200 m outside its far side and then square through it to the ford; the last 300 m are open, 912 m from Bittern's far end (within roundshot). Measured: nearest wood cell to a water cell 283 m. It touches no other road; Bittern stands on the far bank |
| High road | west edge to east edge, one cell, through the village | LAD | the armies' axis |
| Withy road (Red's), Osier road (Blue's) | from the Curlew Ford along Curlew Brook 100 m on Red's side (s -100, t 1,900 to 500) to the village; Osier its image along Godwit Brook | LAD | "one road along each stream on its army's side, running from the ford to the village". With the High road they make the village the crossroads the brief names. The names (willow words) stay true |
| Curlew lane, Godwit lane | Red's fork on the High road at x 1,000 (t 2,400, s -1,800): to the Curlew Ford past Wren Farm (2.0 km, meeting the water at 53°, round the foot of Heron's far end); to the Godwit Ford along s -1,800 to Finch Farm, then square through Siskin Wood (6.2 km). Each lane goes on over its ford as the other army's lane | LAD | "lanes from each army's fork to each ford, bending at a farm". From the centre of Red's first line, a column reaches the far bank of the Curlew Ford in 37 minutes, of the Godwit Ford in 75, the village in 47 (`World.path_cost`, foot in column; horse at the walk 22, 45, 28; foot guns 51, 94, 58): the short hook and the long hook |
| farms | Wren (1,440, 3,920), Finch (4,520, 360); Thrush (6,560, 2,080) and Starling (3,480, 5,640) their images | LAD / DES | one at each lane's bend: Wren t 2,600, s -800; Finch t -2,000, s -1,800 (360 m from the south edge); no cover |
| exits | West and East exit on the High road | DES | no other road leaves the box |
| clock, daylight | Plain's | LAD | |

## Names

Invented, as on Plain. Places are birds of a river meadow (Plover, Curlew,
Godwit, Heron, Bittern, Siskin, Linnet, Wren, Finch, Thrush, Starling) and two willow words for
the bank roads (Withy, Osier), none Plain's. The two brooks are named for their fords (Curlew
Brook, Godwit Brook), so the rotation maps name to name; "Dunlin Brook" and "Plover Bridge"
are retired with the ground they named. Twenty-four commander surnames, three or more edits
from each other, from Plain's and from the words of the place names. Aliases: the period
spelling, the lower-case form, and "the north ford", "the south brook", "the north lane" and
the like.

## The brief

`tools/players_template.md` is Plain's with these changes, under the side budget (400 to 900
words; 875 a side):

1. "The ground" describes the two brooks rising on the saddle and running to the corners behind
   the reader's left and beyond his right, the fords with their mills at two kilometres, the
   village on the saddle with the High road crossing the two bank roads, the lanes past the
   farms (the short way round his right, the long way round his left), the own ridge (height,
   distance, what its guns reach) and wood, and "his side is the same ground turned about".
   Compass words are left out, since north and south change places between the two briefs.
2. "What headquarters knows of the enemy" gives his order of battle in outline as "the same as
   yours, formation for formation and quality for quality", with the totals.
3. "the other side of the plain" is "the other side of the brooks".
4. The orders paragraph is rewritten for Mirror: no "with the army fit to fight
   tomorrow", a draw worth half a win, the break count restarting after a rally, both armies
   broken at once a draw, possession read every quarter hour in the play-on, at six a draw
   unless only one army is over 40% broken, "nothing else counts".
   `tools/objectives_template.md` carries the same verdict in four numbered points.

The two sections differ only in names by construction; the test swaps every name by the
rotation and compares, line for line, the whole first brief.

## The doctrine bot on this ground (seeds 1-4, as built and turned)

`bot:strong` both sides, `--mode stub`. Casualties are men lost over starting men; broken is the
starting men of routed or destroyed bodies, at the end.

| seed | winner | how | at | contact | lost red | lost blue | broken red | broken blue |
|---|---|---|---|---|---|---|---|---|
| 1 | draw | break | 13:51 | 09:41 | 24% | 24% | 60% | 60% |
| 2 | draw | break | 12:27 | 09:41 | 21% | 21% | 49% | 49% |
| 3 | draw | break | 11:33 | 09:41 | 22% | 22% | 77% | 77% |
| 4 | draw | break | 11:56 | 09:41 | 23% | 23% | 72% | 72% |

The field turned by 180° (each army where the other stood) gives the same numbers row for
row: the engine and the ground are exactly symmetric, so it is a
check, not a second sample.

What happens: every brigade of foot marches on the village by the High road and meets the
enemy's on the dry saddle at 09:41; the two hussar and one cuirassier regiments of each army
ride for the village's flank and the router takes them over the army's left-hand ford (Red's
over Curlew, Blue's over Godwit) between 09:23 and 09:38. Nobody takes the right-hand ford or
uses the wood. The fight in the village is now a fight on open ground, not across water: every
game ends by a break before 14:00 (on the first ground five of six were contested to 18:00).
Each game is its own mirror and both armies break in the same minute, a draw by the rule, so
the draw share is 100% by symmetry: the bot is no calibrator for this rung, as for Plain.

## Symmetry (`tests/kriegsspiel/test_symmetry_mirror.py`)

Mirror turned by 180° about the village (`symmetry_kit.rotate_pack`) plays the turned game bit
for bit at every minute on seeds 1-5 and 15, with the same verdict and minute; each game is
also its own mirror (every Red body the image of its Blue namesake), its verdict a draw and
its margins equal.

The positive control (the steps within the minute taken off the lattice again) parted at a
ford on seed 4 of the first ground. On the re-laid ground seeds 1-14 and 16-24 stay turned
without the lattice; seed 15 parts (minute 135, a grenadier battalion's facing in the
village), so the control runs seed 15, which the main test plays turned
with the lattice on.
