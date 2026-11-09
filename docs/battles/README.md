# The battles

General Bench plays three designed battles: Plain, Mirror and Arms. They form a ladder: each
rung changes one thing from the one before, so that a difference between a model's results on
two rungs can be read as a response to that one thing.

| battle | pack | what changes | what it adds to the test |
|---|---|---|---|
| [Plain](plain.md) | `data/plain-crossroads/` | the reference: flat open ground, identical armies | concentration, timing, the reserve, combined arms, order discipline |
| [Mirror](mirror.md) | `data/mirror-fords/` | the ground: brooks, fords, a ridge and a wood a side | reading terrain and choosing where to fight |
| [Arms](arms.md) | `data/arms-medlar/` | the armies: equal strength, different makeup | fighting with the army one has |

## Why designed battles

The battles are invented, not historical. A historical battle gives one side the stronger hand
and carries an answer a model may remember; an invented field with invented names gives every
model the same problem and nothing to recall. The game is closer to chess than to a history
exam: the rules are known, the opponent is not.

Plain and Mirror are exactly symmetric: the 180-degree rotation about the village maps the
ground, the armies and the deployment of one side onto the other's. Arms keeps Plain's ground
and changes only the armies. Every pair of models plays every battle from both sides, so any
advantage of one side cancels in the standings.

All three share a box of 8 km east to west by 6 km north to south, a 25 m raster, a village at
the centre (4,000, 3,000) and the same clock, mission and verdict. The shared builder is
`src/kriegsspiel/designed.py`; each pack's `tools/build_pack.py` adds its own ground, names and
texts and rebuilds every file of the pack byte for byte. The reasons for each number are in the
pack's `design-notes.md`.

## The armies

On Plain and Mirror both armies are identical: eleven formations and a headquarters, 12,440 men
(gun crews included) and 44 guns.

| arm | formations | quality |
|---|---|---|
| foot | seven brigades of two battalions of 700, each battalion with two battalion guns | one grenadier brigade 5; four line brigades 3; two brigades of new-raised regiments 2 |
| horse | three brigades of two regiments of 400 | cuirassiers 4; dragoons 3; hussars 3 |
| guns | a reserve artillery of two batteries of eight 12-pounders | 3 |

Quality is mixed by formation, so a general can reason with it: where to put the grenadiers,
what to ask of the new-raised brigades. Arms' two armies are described on [its page](arms.md).

Both armies stand drawn up at 09:00 in two lines with the horse on the wings and the reserve
behind the centre, each first line 3.5 km from the village.

## The brief

A general's first brief carries everything the design fixes; nothing is held back. It gives the
mission, the verdict below in full, the [rules sheet](../rules-sheet.md) with the engine's
numbers, the clock, his own order of battle with every formation's quality and where it stands,
and the enemy's order of battle in outline: what he has, never where he is or what he intends.
Both sides read the same text with the names swapped (on Arms, the two armies' own sections
differ). What a general reads and why: [player prompt](../player-prompt.md).

## The verdict

The verdict is ordinal: win, draw or loss, by rule. There is no composite score and no weight.
It is the rule the age used: the loser is the army that can no longer contest the field. It is
implemented by `OrdinalJudge` in `src/kriegsspiel/verdict.py` and parameterised by each pack's
`mission.json`:

```json
{"verdict": "ordinal", "objective": "Teasel Village", "break_share": 0.4,
 "break_persist_min": 30, "play_on_min": 120, "break_tie_margin": 0.1}
```

The judge reads the field at the end of every minute.

**1. An army that breaks loses.** An army's broken share is the starting men of its broken
bodies over all its starting men; a body is broken when it is routed or destroyed, has fled off
the map, or has been captured. (A body that marched off by an exit, or has not yet arrived, is
not broken.) An army is broken when its share has stayed above 40% for 30 minutes without a
break. A dip to 40% or below, by rallies, starts the count again. The battle ends at the minute
the break is ruled.

- The winner by a break must itself be at or under 40% at that minute.
- If both armies are over 40% at that minute, the less broken army wins, unless the two shares
  are within 10 points of each other: then it is a draw.

**2. Otherwise the side in possession of the village at the end hour wins.** Possession is read
within musket range (250 m, `combat.MUSKET_RANGE_M`) of the village's point at the crossroads,
from formed bodies only: steady or shaken, not in flight, routed or destroyed.

- The side with formed foot or guns there, while the enemy has none, holds it.
- If neither side has foot or guns there, the side with formed cavalry there, while the enemy
  has none, holds it.
- Both sides present in the deciding arm: contested. Nobody: empty.

Cavalry thus holds an empty village and holds it against cavalry, never against formed foot or
guns: the engine fires no volleys from the saddle and dismounts no dragoons.

**3. Contested or empty at the end hour: play on.** The village is read again every quarter hour
for two hours at most, and the first clear possession wins. The break rule goes on applying every
minute. The general's staff tell him each reading (the brief's "From the umpire" section).

**4. At the last reading**, if the village is still not held: an army over 40% broken at that
minute loses to one that is not, whether or not its share has persisted for 30 minutes.
Otherwise the battle is a draw.

Nothing else counts. Casualties, formed strength and ground elsewhere are recorded with each
verdict as the margin (`casualty_share`, `formed_share`, `broken_share` per side), for reading,
never for the result. The verdict record also gives `how` the battle was decided (`break`,
`possession`, `play-on`, `last-reading`, `draw`), every possession reading with the formed men
near the village, and the minute each army first crossed the break share.

A general who takes the village at 2:1 losses wins, as at Malplaquet, and is one bad volley from
losing outright. Blood matters the way it did: through breaking, and through who can still stand
in the village.

### Why these numbers

- **40%.** In the CDB90 battle database, losing armies of 1700 to 1815 lost a median 22% of their
  men (upper quartile 34%). An army with two fifths of its men in broken bodies cannot contest the
  field.
- **30 minutes** is the engine's rally window: a rout that rallies inside it was not a break.
- **10 points** is about a brigade of foot (1,400 of 12,440 men), the largest body a general moves
  by one order. Two armies whose shares differ by less broke alike.
- **250 m** is the engine's musket range.
- **Two hours** of play-on ends long before the light fails.

## The clock

| | |
|---|---|
| start | 09:00 |
| end hour | 16:00 |
| play-on | quarter-hour readings from 16:00 to 18:00 |
| season | high summer; sunset about 20:05 |

Times are local apparent solar time. Daylight is never the limit. The general is consulted every
15 battle minutes and on reports (see [the play loop](../engine.md#the-play-loop)); the battle
stands still while he thinks.

## Reading results

- **The umpire's factor.** Every melee is scaled by a factor between 0.7 and 1.4 that the
  decisions model chooses from a prose account of the clash ([engine](../engine.md#melee)). It
  is the one model judgment inside the physics.
- **The staff asks.** An order the staff cannot read with confidence holds the formation and
  comes back to the general as a question. How often a model draws questions is part of how it
  commands.
- **The both-broken tie-break** (rule 1, second point) was added after the first 60 games, and
  those games were re-judged under it; it changed ten results.
- **The first seat on Arms.** The horse army, listed first, wins more often than the foot army.
  Plain and Mirror are exactly symmetric and split close to even between the sides. Because every pair plays both sides, the effect
  cancels in the standings; on Arms it measures which models use the stronger arm.
- **The narrative verdict.** The umpire also names a winner at the end of each game. It is
  recorded (`jev_winner`) and decides nothing.
- **The staff model.** Most games were staffed by Jev; some by a Codex model standing in. Each
  game record names its staff model, and the [staff study](../staff-study.md) measures how far
  the two readers agree.
