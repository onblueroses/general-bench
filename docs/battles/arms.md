# Arms: Medlar Village

The third battle of the ladder: Plain's field, clock, mission and verdict, with two armies of
equal strength by the period's own rate and different makeup, one strong in horse and one in
foot. Pack: `data/arms-medlar/`; the reason for every number is in its `design-notes.md`.

## Premise

Two armies have marched on the same crossroads from opposite sides and stand drawn up for battle
at 09:00, each first line 3.5 km from Medlar Village. Each general knows the ground, his own army
in full and the enemy's in outline: what he has, never where. He knows the enemy is not made like
his own. The verdict is Plain's: break the enemy, or hold the village at four o'clock with an army
that has not broken.

## What it measures

Whether a general fights with the army he has. The horse army is faster and stronger on the
wings and weak in foot and guns; the foot army is the opposite. The ground is Plain's open
plain, so nothing but the armies differs: a stream or a walled village would be the foot army's
ground and decide the battle before either general was tested.

## Ground

Plain's raster and features under new names, so that no model can tell it is Plain's field:

| feature | where | Plain's name |
|---|---|---|
| Medlar Village | a point at the crossroads, (4,000, 3,000); houses in a disc of 200 m about it | Teasel Village |
| Post road | west edge to east edge through the village | High road |
| Salt road | south edge to north edge through the village | Drove road |
| Quince (NW), Damson (NE), Bullace (SE), Pippin (SW) Farm | 2 km from the village on the diagonals | Mallow, Vetch, Yarrow, Burdock |
| West, East, South, North exit | where the roads meet the map edge | the same |

## Armies

| | horse army: White, side `horse`, west | foot army: Green, side `foot`, east |
|---|---|---|
| foot | Grenadier brigade 5; First to Third brigade 3; Fourth (new-raised) 2: 10 battalions of 700, two battalion guns each | Grenadier brigade 5; First to Fifth brigade 3; Sixth, Seventh (new-raised) 2: 16 battalions |
| horse | Cuirassier brigade 4; First, Second Dragoon brigade 3; First, Second Hussar brigade 3: 10 regiments of 400 | Dragoon brigade 3; Hussar brigade 3: 4 regiments |
| guns | Horse artillery: two batteries of eight 6-pounders, 3 | Reserve artillery: three batteries of eight 12-pounders, 3 |
| men with gunners | 11,240 | 13,160 |
| guns with battalion guns | 36 | 56 |
| bodies | 22 | 23 |
| points: foot + 2 x horse + 35 x guns | 16,260 | 16,360 |

"Equal strength" is the period's rate: a horseman counts as two foot, a gun as about thirty-five
men. Quality follows Plain's pattern within each arm (one grenadier brigade, about two sevenths of
the foot new-raised, horse at 3 or 4), so the horse army's mean quality comes out at 3.2 and the
foot army's at 3.0.

| | horse army | foot army |
|---|---|---|
| army | General Ashdown | General Merriman |
| Grenadier brigade | Birtwistle | Nettleship |
| line brigades | First to Third: Cradock, Dimmock, Elphick | First to Fifth: Oxenham, Pashley, Rockliffe, Scattergood, Tunnicliffe |
| new-raised brigades | Fourth: Fothergill | Sixth, Seventh: Uttley, Vardy |
| horse | Cuirassiers Grimshaw; Dragoons Hollins, Ingleby; Hussars Jowett, Kershaw | Dragoons Wolstenholme; Hussars Yeadon |
| guns | Horse artillery Lumb | Reserve artillery Brocklehurst |

## Deployment at 09:00

Horse army: first line the First, Second and Third brigades left to right, with the First Hussar
brigade on the left wing and the Second on the right; second line the Fourth brigade (left) and
the grenadiers in column (right), a dragoon brigade behind each wing; behind the centre the
cuirassiers and the horse artillery, limbered.

Foot army: two lines of four brigades (the First to Fourth; then the Sixth, Fifth, Seventh and
the grenadiers in column on the right), the hussars on the left wing and the dragoons on the
right, the three batteries limbered behind the centre.

Both first lines stand 3.5 km from the crossroads. The foot army's layout is turned by 180
degrees, so each army's left faces the other's right.

## Mission, verdict and brief

Plain's, in the same words for both: take and hold the crossroads at Medlar Village. The verdict
is the ladder's ([battles](README.md#the-verdict)). The two briefs differ by design in three
sections: the own order of battle, the own deployment and the enemy's order of battle in outline.

## The first seat

The horse army is the first side of the pack (`oob.json` lists `horse`, then `foot`) and wins more
often than the foot army. Plain and Mirror, which are symmetric, split close to even between the
sides, so the difference on Arms is the armies, not the seat. Every pair of models plays Arms from
both sides, so the advantage cancels in the standings; what remains is a measurement of which
models make use of the stronger arm. The share by side for each model is in the results.

## Scripted plan

Plain's plan fitted to each army: the centre brigade takes the village by the Post road, the first
line beside it and the second line follow, the light horse covers the flanks, the grenadiers go up
at noon.
