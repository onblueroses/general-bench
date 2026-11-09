# Plain: Teasel Village

The first battle of the ladder and the reference for the other two. Two identical armies stand
on opposite sides of a flat plain; one village on the crossroads at its centre is the only thing
worth having. Pack: `data/plain-crossroads/`; the reason for every number is in its
`design-notes.md`.

## Premise

Two armies have marched on the same crossroads from opposite sides and stand drawn up for battle
at 09:00, each first line 3.5 km from Teasel Village. Each general knows the ground, his own army
and that the enemy's is the same as his, formation for formation; he does not know how the enemy
is drawn up or what he means to do. Both know the verdict: break the enemy, or hold the village
at four o'clock with an army that has not broken.

## What it measures

Concentration, timing, the use of the reserve, combined arms and order discipline, with nothing
else to explain a result: no terrain to read, no asymmetry of force or position, no arrivals, no
deadline but the clock. Either side faces exactly the same problem.

## Ground

| feature | where | what it does |
|---|---|---|
| Teasel Village | a point at the crossroads, (4,000, 3,000); houses in a disc of 200 m about it | the objective; cover for its holders; possession within 250 m of the crossroads |
| High road | west edge to east edge through the village | the armies' axis; road speed |
| Drove road | south edge to north edge through the village | lateral road speed |
| Mallow, Vetch, Yarrow, Burdock Farm | 2 km from the village on the diagonals (NW, NE, SE, SW) | names to steer by; no cover |
| West, East, South, North exit | where the roads meet the map edge | ways off the field |

Everything else is open, flat (200 m everywhere), dry ground. Red's half is the west, Blue's the
east. The rotation about the village maps Mallow to Yarrow and Vetch to Burdock.

## Armies

Identical, per side: seven infantry brigades of two battalions of 700, each battalion with two
battalion guns (one grenadier brigade of quality 5, four line brigades 3, two new-raised
brigades 2); three cavalry brigades of two regiments of 400 (cuirassiers 4, dragoons 3, hussars
3); a reserve artillery of two batteries of eight 12-pounders (3); a headquarters. 12,440 men and
44 guns, 22 bodies.

| | Red | Blue |
|---|---|---|
| army | General Thursby | General Raikes |
| Grenadier brigade | Calloway | Dewhurst |
| First to Fourth brigade | Brandreth, Fenwick, Haddow, Pellow | Ellerby, Garside, Hesketh, Jessop |
| Fifth, Sixth brigade (new-raised) | Quarrie, Stannard | Nuttall, Upjohn |
| Cuirassier, Dragoon, Hussar brigade | Ormerod, Lattimer, Vowell | Whitlock, Ibbotson, Rudge |
| Reserve artillery | Kitto | Tranter |

## Deployment at 09:00

First line 3.5 km from the crossroads: the First, Second and Third brigades left to right, the
hussars on the left wing, the dragoons on the right. Second line 250 m behind: the Fifth, Fourth
and Sixth brigades, the cuirassiers behind the dragoons. Behind the centre: the grenadiers in
column and the reserve guns limbered, headquarters between them and the second line. Foot and
horse of the two lines start in line. Blue's deployment is Red's turned by 180 degrees about the
crossroads, so each army's right faces the other's left.

## Mission and verdict

The same for both, names swapped: take and hold the crossroads at Teasel Village; the enemy
marches on it from the other side under the same orders. The verdict is the ladder's
([battles](README.md#the-verdict)), stated in full in every first brief with the clock and both
orders of battle (the enemy's in outline).

## Scripted plan

`script.json` holds one plan for both sides: the centre brigade takes the village by the High
road and holds it, the flank brigades and the second line follow, the horse covers the flanks,
the grenadiers go up at noon. It lets either side face a scripted opponent under a live staff.
