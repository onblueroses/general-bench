# Mirror: Plover Village

The second battle of the ladder: Plain's armies, deployment, clock, mission and verdict on ground
that matters, laid out so that the 180-degree rotation about the village maps the field onto
itself. Each army faces exactly the ground the other faces. Pack: `data/mirror-fords/`; the
reason for every number is in its `design-notes.md`.

## Premise

Two armies have marched on the same village from opposite sides and stand drawn up at 09:00,
each first line 3.5 km from Plover Village, as on Plain. Two brooks rise on a dry saddle 500 m
either side of the village and run away to the north-west and south-east corners, so the field is
cut along the diagonal into the two armies' halves, joined at the saddle and at one ford on each
brook, 2 km from the village. Each general knows the ground, his own army and that the enemy's is
the same; he does not know how the enemy is drawn up or what he means to do. The verdict is
Plain's: break the enemy, or hold the village at four o'clock with an army that has not broken.

## What it measures

Everything Plain measures, plus reading terrain and choosing where to fight. A general can fight
for the village on the saddle head on, or turn the enemy by a ford, and then choose which: the
short hook over his left-hand ford, under his own ridge, round the enemy's right; or the long
hook over his right-hand ford, hidden by his own wood to 300 m short of the water and then in
the open under the enemy's ridge, round the enemy's left. Either side faces exactly the same
problem.

## Ground

| feature | where | what it does |
|---|---|---|
| Plover Village | a point at (4,000, 3,000); houses in a disc of 200 m about it, on the saddle | the objective; cover; possession within 250 m of the crossroads, all dry ground |
| Curlew Brook, Godwit Brook | from 500 m off the village to the north-west corner (Curlew) and the south-east corner (Godwit), on the diagonal; a band of water 50 m across | no arm crosses but at its ford; the corners beyond are reached only by the fords |
| Curlew Ford (Curlew Mill), Godwit Ford (Godwit Mill) | (2,400, 4,200) and (5,600, 1,800), 2 km from the village along each brook | every arm wades: foot and horse at half speed, guns and wagons at a quarter |
| Heron Ridge (Red's left), Bittern Ridge (Blue's left) | a crest 1 km long parallel to the army's left-hand brook, 600 m on its own side; its middle 1.48 km from the village | 25 m high: hides what is behind it from beyond the brook and sees over it; 12-pounders on its near end reach the village (1.04 km) and the near ford (1.30 km) |
| Siskin Wood (Red's right), Linnet Wood (Blue's right) | 1.7 by 1.3 km beside the army's right-hand brook, its edge 300 m short of the water | wood: slow going, half the fire, blocks sight; hides the approach to that side's right-hand ford, whose last 300 m are open under the enemy's ridge |
| High road | west edge to east edge through the village | the armies' axis; road speed |
| Withy road (Red's), Osier road (Blue's) | from the army's left-hand ford along that brook, 100 m on its own side, to the village | the short hook's road; with the High road it makes the village a crossroads |
| Curlew lane, Godwit lane | from the High road 500 m in front of each first line to each ford, past a farm; each goes on over its ford as the enemy's lane | the flank marches: 2.0 km to the left-hand ford, 6.2 km to the right-hand one |
| Wren, Finch (Red's), Thrush, Starling (Blue's) Farm | at the lanes' bends | names to steer by; no cover |
| West, East exit | the High road at the map edge | ways off the field |

There is no bridge. The rotation maps Heron to Bittern, Siskin to Linnet, Curlew to Godwit, Withy
to Osier, Wren to Thrush and Finch to Starling. So Curlew Ford lies under Red's ridge and at the
end of Blue's wood: Red's short hook and Blue's long one, a concealed approach for Blue whose
crossing is in the open under Red's guns. Godwit Ford is the same with the colours exchanged.

The briefs describe the ground in terms of the reader's own left and right and leave out compass
words, since north and south change places between the two sides.

## Armies and deployment

Plain's, formation for formation and position for position (`deployment.json` is the same
file), under other commanders.

| | Red | Blue |
|---|---|---|
| army | General Gorringe | General Fairclough |
| Grenadier brigade | Pettifer | Royle |
| First to Fourth brigade | Ackroyd, Mawhood, Treloar, Bunce | Tasker, Quayle, Pargeter, Kemble |
| Fifth, Sixth brigade (new-raised) | Pinnock, Snelling | Gubbins, Shillito |
| Cuirassier, Dragoon, Hussar brigade | Hebditch, Cundall, Lorimer | Etheridge, Hammick, Mallinson |
| Reserve artillery | Venables | Jupe |

## Mission, verdict and brief

Plain's mission and verdict on Plover Village ([battles](README.md#the-verdict)), in every first
brief with the clock, the rules sheet and both orders of battle. The enemy's is given in outline
as "the same as yours, formation for formation and quality for quality", with the totals.

## Symmetry

Red's half is built and Blue's is its rotation, so the pack is symmetric by construction:
`test_pack_mirror.py` checks that every raster layer equals its 180-degree turn element for
element and that every feature's image is a feature of its kind. `test_symmetry_mirror.py` plays
the field turned about the village and checks that the turned game is the exact image of the
game at every minute, with the same verdict at the same minute.

## Scripted plan

Plain's plan with the village renamed: the centre brigade by the High road to the village, the
rest following, the horse on the flanks, the grenadiers up at noon. It uses neither ford nor
ridge; it is a baseline opponent, not a plan for this field.
