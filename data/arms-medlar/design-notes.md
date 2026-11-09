# Arms (Medlar Village): design notes for the data pack

Why every number in `data/arms-medlar/` is what it is. The ruling is
`docs/battles/README.md` ("The ladder" item 3, "Arms' armies", "Calibration"); the design doc
is `docs/battles/arms.md`. Tags as in
Plain's notes: **LAD** fixed by the ruling, **DES** chosen here to carry it out, **EST** an
estimate with its rule. Nothing is sourced history.

## What is Plain's (LAD: "Plain's ground; each rung changes one thing")

- The raster: `terrain.npz` is built by Plain's own `terrain()` (the builder imports
  `../plain-crossroads/tools/build_pack.py`), so it is Plain's array for array; the test
  compares `cover`, `elev`, origin and size.
- The features: Plain's eleven, same kinds, geometry and radii in the same order, under new
  names (below). The exits keep their compass names: they say only where a road leaves.
- `meta.json`: Plain's clock (09:00 to 16:00, play-on to 18:00), season, light and
  `rules_sheet: true`; roles "meeting engagement". Only the battle's name, the sides, the
  commanders, the strengths and the doc differ (test).
- `mission.json`: Plain's ordinal verdict (break 0.4 for 30 minutes, play-on 120 minutes) on
  Medlar Village; the mission words (`tools/objectives_template.md`) are Plain's with the
  village renamed, the same for both generals.
- The brief's ground, orders-and-verdict and conventions paragraphs
  (`tools/players_template.md`) are Plain's with the new names.

## Names (DES)

| Plain | Arms | why |
|---|---|---|
| Teasel Village | Medlar Village | a new invented name in Plain's style (a plant word plus the kind's noun, a period spelling "Medlare" as alias), so no model can tell this is Plain's field |
| High road, Drove road | Post road, Salt road | the same two roads; Plain's names would give the field away |
| Mallow, Vetch, Yarrow, Burdock Farm | Quince, Damson, Bullace, Pippin Farm | NW, NE, SE, SW as on Plain; all four distinct under the staff's one-letter tolerance (test) |
| Red army, Blue army | White army (horse), Green army (foot) | the armies need a colour to be called by: the side ids `horse` and `foot` are arm words ("the horse" is cavalry to the staff), so they cannot be the armies' names. Neither colour appears in any other pack; `staff_text.DEMONYMS` gains `horse: white`, `foot: green` so "the Greens" reads as the enemy for the horse army |
| 24 commanders | 24 new surnames | none of Plain's or Mirror's (test), three or more edits apart, no common word, no place |

## Sides (DES)

- `oob.json` sides `["horse", "foot"]`, ids `H-<key>-<n>` and `F-<key>-<n>`; `meta.json`
  `army` "H" and "F". The horse army stands west, the foot army east.
- Neither side has role "attacker", so `run.umpire_for` and `grid._attacker` take the first
  side, horse, as Plain takes red. It touches neither the verdict nor the bot. The cross
  report (`grid.cross`) now shows a pack that names no attacker by its side names: "horse" and
  "foot" in section 1, "Sides in this seat: arms-medlar horse (first side, no attacker
  named)" in section 2 (`grid._side_label`, `test_grid_cross.py`).

## Armies (LAD numbers, DES quality and layout)

the ladder "Arms' armies", per side; every count is the ruling's:

| | horse army (White) | foot army (Green) |
|---|---|---|
| infantry | 5 brigades, 10 battalions of 700, 2 battalion guns each: 7,000 | 8 brigades, 16 battalions: 11,200 |
| cavalry | 5 brigades, 10 regiments of 400: 4,000 | 2 brigades, 4 regiments: 1,600 |
| artillery | Horse artillery: two 6-pounder horse batteries of 8 (16 guns), kind `horse_battery` | Reserve artillery: three 12-pounder foot batteries of 8 (24 guns) |
| guns | 16 + 20 battalion guns = 36 | 24 + 32 = 56 |
| men (foot and horse) | 11,000 | 12,800 |
| men with gunners (15 a gun, the Kolín rule, EST) | 11,240 | 13,160 |
| formations | 11 and a headquarters | 11 and a headquarters |
| bodies | 22 | 23 (three batteries) |

### Quality (DES, "Plain's pattern within each arm")

Plain's foot is 7 brigades: one grenadier brigade 5, four line 3, two new-raised 2 (2/7 of
the brigades new-raised). Plain's horse is one brigade each of cuirassiers 4, dragoons 3,
hussars 3. Guns 3.

| formation (key) | horse army | foot army |
|---|---|---|
| Grenadier brigade (G) | 5 | 5 |
| line brigades (L) | First, Second, Third: 3 | First to Fifth: 3 |
| new-raised brigades (N) | Fourth: 2 | Sixth, Seventh: 2 |
| foot mean | 3.2 | 3.0 |
| Cuirassier brigade (CU) | 4 | none |
| Dragoon brigades (DR) | First, Second: 3 | one: 3 |
| Hussar brigades (HU) | First, Second: 3 | one: 3 |
| horse mean | 3.2 | 3.0 |
| artillery (AR) | 3 | 3 |

- New-raised in Plain's proportion: 5 x 2/7 = 1.43, rounded to one brigade; 8 x 2/7 = 2.29,
  two. One grenadier brigade each, the rest line.
- Horse: Plain has one brigade of each kind. Five brigades cannot keep the 1:1:1 proportion;
  the horse army has one cuirassier brigade (Plain's one heavy reserve), two dragoon and two
  hussar brigades, so each wing has a light and a line brigade (its mean, 3.2, equals its
  foot's). The foot army keeps two of Plain's three: the dragoons and the hussars, one for
  each wing; dropping the cuirassiers keeps its horse at its foot's mean (3.0). The other
  choice for the horse army (two cuirassier brigades, mean 3.4) was not taken: it would add
  quality on top of numbers.
- The quality means differ (horse army 3.2, foot army 3.0) because the rounding falls that
  way; this is the pattern as ruled, not a correction. For reading only, the ladder's points
  weighted by quality (foot men x q + 2 x horse x q + 35 x guns x q, battalion guns at their
  battalion's q): 51,920 against 49,080, the horse army 6% ahead. With two new-raised brigades
  in the horse army it would be 48,980 against 49,080. Calibration decides (the ladder), not this
  sum.

### Points (LAD; test)

The period's own rate, the ladder "Arms' armies": a horseman two foot, a gun about thirty-five
men (crew inside the thirty-five, so the gunners are not counted again):

    points = foot + 2 x horsemen + 35 x guns
    horse army: 7,000 + 8,000 + 35 x 36 = 16,260
    foot army: 11,200 + 3,200 + 35 x 56 = 16,360

0.6% apart, inside the 2% bound the test holds; the ladder rounds them to 16,300 and 16,400.
(Reading "men + 2 x horsemen" with men already including the horsemen would count each
horseman three times, 20,260 against 17,960; the ladder's own sums show it means foot plus
twice the horse.)

### Deployment at 09:00 (DES)

Plain's lines and spacings (`kriegsspiel.designed`: first line x 500, 3.5 km from the
crossroads; second line 250 m behind; reserve line 100 m from the edge; battalion 170 m and
regiment 210 m centre to centre; brigade centres 350 m apart; a wing brigade 420 m beyond its
flank brigade, as on Plain: half a brigade, a 70 m gap, half a horse brigade). Each army is
laid out in the west frame facing east and the foot army is turned by 180° about the
crossroads, so both first lines are 3.5 km from the village and each army's left faces the
other's right, as on Plain. Foot and horse of the lines start in line, the grenadiers in
column, the guns limbered; headquarters x 175 behind the centre.

Horse army (west), its left is north:

| where | what | why |
|---|---|---|
| first line, x 500 | First, Second, Third brigade, centres +350, 0, -350 | Plain's first line: three brigades, 1 km front across the Post road |
| first line, wings | First Hussar brigade left (+770), Second right (-770) | "its cavalry on both wings": the light horse in front, where it meets the enemy's horse first |
| second line, x 250 | Fourth brigade (+175, left) and Grenadier brigade in column (-175, right) | five brigades leave two for the second line, behind the gaps; the grenadiers on the right, the old post of honour, as Plain's grenadiers stand in reserve |
| second line, wings | First Dragoon brigade behind the left wing, Second behind the right | a line brigade behind each light one: every wing two brigades deep |
| reserve, x 100 | Cuirassier brigade at the centre (regiments at +-105), Horse artillery at +-350 | "its guns central"; the heavy horse as the army's one shock reserve behind the centre, where it can go to either wing |

Foot army (east, turned), its left is south:

| where | what | why |
|---|---|---|
| first line, x 500 (frame) | First to Fourth brigade, centres +525, +175, -175, -525 | "two lines": four brigades a line; a 1.4 km front |
| first line, wings | Hussar brigade left (+945), Dragoon brigade right (-945) | "its small cavalry on the wings", as Plain: hussars left, dragoons right |
| second line, x 250 | Sixth, Fifth, Seventh brigade (+525, +175, -175), Grenadier brigade in column (-525, right) | the second line behind the first, brigade for brigade; the new-raised brigades behind the steady ones at either side of the Fifth; the grenadiers on the right |
| reserve, x 100 | three 12-pounder batteries at +350, 0, -350 | guns central, as Plain's reserve artillery |

No two bodies of a side stand closer than 150 m (test). The armies are not each other's image
and are not meant to be: the rotation keeps only the distance, 3.5 km, and the facing.

## The brief (LAD, DES)

- One template (`tools/players_template.md`) for the ground, the orders with the verdict
  (the ladder verbatim, as Plain's) and the conventions with the clock: these three sections are
  the same bytes for both sides, the ground with the farm and exit names turned (test).
- Each army's three paragraphs (`tools/army_horse.md`, `tools/army_foot.md`): who you are
  (the own order of battle with every formation's commander and quality), how the army came
  here (the deployment, own army only) and what headquarters knows of the enemy (his order
  of battle in outline: brigades by kind and quality, men and guns, never where or how he
  stands; never his commanders). Each says "an army strong in horse/foot" and the enemy's
  "His army is unlike yours ... strong in foot/horse", so each general knows he faces a
  different army.
- The rules sheet (`docs/rules-sheet.md`) comes in every persona by `meta.json`
  `rules_sheet: true`; it has the horse batteries' march and limbering and the 6-pounder's
  range already.
- Budget: 793 words (horse) and 780 (foot), inside docs/player-prompt.md's 400 to 800. To fit,
  Arms drops Plain's "each under its general" (the commanders are named one by one) and says
  "His army is unlike yours".

## Script (`script.json`, DES)

Plain's plan fitted to each army: the Second brigade advances on the village by the Post road
and holds it, the first-line brigades beside it advance with it, the second line follows, the
light horse covers the flanks with the dragoons behind (horse army), the cuirassiers and
grenadiers stay in reserve, the guns support the Second brigade, and at noon the grenadiers go
up to the village. Thirteen orders a side; every order names its addressee first and the
village by its name (test). It needs Jev; stub self-play uses the doctrine bot.

## Self-play (`bot:strong` both sides, `--mode stub`, seeds 1-6)

Seatings: `built` the pack; `order` the sides' order in oob.json reversed (foot first);
`turned` the field turned by 180° (horse east, foot west). Casualties: men lost (fled counts
lost) over starting men; broken: starting men of routed or destroyed bodies at the end.

| seating | seeds 1-6: winner, how, at | first contact | casualties horse / foot | broken horse / foot |
|---|---|---|---|---|
| built | horse by break at 10:45, every seed | 09:47 | 8% / 14% | 20-23% / 89% |
| order | as built, game for game | 09:47 | as built | as built |
| turned | as built, game for game | | | |

Why the horse army sweeps, read from seed 1 (the bot's plan, not the
design): the bot sends every body of both armies at the one place it is told to hold.
The horse army's two horse batteries, at 100 m a minute, stand on the crossroads at 09:45,
and its three first-line brigades close up on them by 09:55 (eight bodies within 250 m of the
crossroads against the foot army's four, its leading battalions coming up the Post road). The
foot army's horse (four regiments) meets ten regiments on the wings at 09:47-09:55 and is
broken. From 10:00 the foot army's battalions, stacked on and beside the road, assault the
houses in line; they break three battalions and a battery (10:03-10:09) but are repulsed,
and from 10:10 its brigades go one after the other by morale; at 10:20 14 of its 16
battalions and all three batteries are routed, and the break is ruled at 10:45. Every game, either army, is a head-on collision at the
crossroads decided by break before 11:00; the possession rule and the draw are never reached,
as on Plain. The armies are not tuned to this (the ladder "Calibration": Arms is calibrated by a
model pilot, both ways, the foot army gaining or losing a brigade).

Engine finding, not the pack's to fix: **the bot is a poor calibrator here too**: it fights the army it has in the same way, all
   of it to the crossroads, so the horse army's speed decides who stands in the houses first.
