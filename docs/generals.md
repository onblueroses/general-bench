# How each general commands

Seven models, 144 games each, the 504 games of the matrix (`games/round-1`, `games/round-2`).
Each section compares one model with the other six on the same measure. Three sources feed the
measures: the reports in the general's own briefs (which of its bodies broke, and when
headquarters heard), the staff's reading of every order (which task, which brigade, at what
minute) and the words of the orders themselves. "The others" means the range over the other six
models; "pooled" means their seats taken together. Intervals come from 2,000 resamples of whole
games. Every number on this page is printed by

    uv run python scripts/generals.py            # add --quotes to check every order quoted here

and each measure is defined in that script's docstring.

| model | score | rally 15 | recovered | broken at end | silent when hurt | by 09:05 | stands (min) | repeats | quarter | garrison | opening attack |
|---|---|---|---|---|---|---|---|---|---|---|---|
| astra | 70% | 85% | 52% | 18% | 9% | 25% | 25 | 18% | 1% | 0.0 | 28% |
| fable | 56% | 72% | 34% | 37% | 18% | 17% | 18 | 24% | 6% | 1.4 | 6% |
| sol | 55% | 71% | 30% | 40% | 17% | 29% | 30 | 21% | 0% | 0.4 | 27% |
| opus | 53% | 67% | 30% | 39% | 21% | 27% | 25 | 25% | 1% | 2.3 | 5% |
| luna | 47% | 66% | 24% | 42% | 14% | 19% | 20 | 22% | 0% | 0.0 | 56% |
| deepseek | 35% | 61% | 17% | 52% | 1% | 5% | 5 | 57% | 25% | 0.7 | 33% |
| sonnet | 34% | 38% | 15% | 54% | 40% | 18% | 25 | 19% | 0% | 0.4 | 13% |

- **rally 15**: the share of a model's broken bodies whose brigade is ordered to rally within 15
  minutes of the report. **recovered**: of the men in bodies that broke during a game, the share
  not broken at the verdict. **broken at end**: median share of the army routed or destroyed at
  the verdict.
- **silent when hurt**: the share of briefs reporting one of its own bodies broken that get no
  order. **by 09:05**: the share of all its orders written in the first five minutes.
  **stands**: median minutes before the next order to the same formation.
- **repeats**: orders that set a formation the same task on the same objective as the order
  before. **quarter**: orders that hand a brigade a side, edge or quarter of the village.
  **garrison**: brigades a game given an order "at all costs" at 09:00. **opening attack**:
  games with an attack task written by 09:05.

## Astra

Astra loses bodies as often as anyone and gets them back. It answers a break with a rally order
at once, often after sending the brigade well to the rear, and it ends its battles with the least
of its army broken.

- **It breaks as often as anyone.** 14.2 bodies broken a game; the others 13.4 to 15.0.
- **It rallies at once.** 85% of its breaks get a rally order to the brigade within 15 minutes;
  the others 38 to 72%. Astra is 23 points above the six pooled (95% interval +20 to +25).
- **It gets its men back.** It recovers 52% of the men that broke; the others 15 to 34% (+27
  points, +22 to +33). At the verdict a median 18% of its army is broken, against 37 to 54%.
- **It seldom answers a break by holding on.** Of breaks whose brigade gets an order within half
  an hour, 7% get a hold, an attack or a charge first; the others 10 to 52%.

> Pellow, withdraw to 1500 m west of Teasel Village, then rally the Fourth brigade there.

(`games/round-2/plain-crossroads/astra-vs-deepseek-s3.json.gz`, 10:15)

> Brandreth, rally the First brigade at 1500 m west of Teasel Village.

(the same game, 10:43)

**`round-2/plain-crossroads/astra-vs-deepseek-s3`** (Astra red). Astra sends its foot by the High
road into Teasel Village and holds its flanks 500 m out; 23 of its 53 orders are written by
09:05. From 10:12 its bodies break in the fight for the village. It pulls each brigade back
1,500 m and orders it to rally there, and 7 of its 10 breaks get a rally order within a quarter
hour. DeepSeek's army breaks at 11:42 with 48% broken; Astra's has 9%.

## Fable

Fable builds a line, fences each brigade with a standing limit and places it by its neighbour,
then lets the enemy come on. It does well on Plain and Mirror and less well on Arms, where the
armies differ.

- **It fences its brigades.** 13% of its orders carry a standing limit ("attacking nothing
  without a further order"); the others 0 to 8%. 19% place a brigade by another ("behind the
  First brigade"); the others 0 to 13%. Opus comes nearest on both, at 8% and 13%.
- **Arms is its weak battle.** It scores 61% on Plain and Mirror together and 46% on Arms, a drop
  of 16 points; the other six range from -9 to +3. Fable's drop exceeds the others' by 18 points,
  with an interval from 0 to +37: suggestive, not settled. It shows on both sides: 48% with the
  horse army (the six pooled 57%) and 44% with the foot army (45%).

> Sixth brigade: advance to Bullace Farm and hold there in column behind the First brigade,
> attacking nothing without further orders.

(`games/round-1/arms-medlar/sol-vs-fable-s2.json.gz`, 09:50)

> Fourth brigade, follow the Grenadier brigade by the Post road to a point 500 m westward of
> Medlar Village and halt there in column as the reserve, attacking nothing without a further
> order.

(`games/round-2/arms-medlar/fable-vs-opus-s3.json.gz`, 09:00)

**`round-2/arms-medlar/fable-vs-opus-s3`** (Fable with the horse army). At 09:00 Fable sends two
brigades into Medlar Village at all costs, posts two more 400 m to either side, and halts the
Fourth brigade and the Cuirassiers behind them under standing limits. It writes 159 orders over
the day and rallies 16 of its 28 breaks within a quarter hour, but the line wears down. Its army
breaks at 16:15 with 60% broken; Opus has none broken.

## Sol

Sol makes its plan in the first five minutes and leaves it to run. After the opening it orders
little, and an order it gives stands longer than any other model's.

- **The plan comes first.** 29% of all its orders are written by 09:05; the others 5 to 27%
  (Opus 27%, Astra 25%). Sol is 16 points above the six pooled (+13 to +18).
- **Its orders stand.** An order to a formation stands a median 30 minutes before the next one to
  the same formation; the others 5 to 25 minutes.

> Fourth brigade, follow Second brigade and support it at Teasel Village.

(`games/round-1/plain-crossroads/sol-vs-fable-s2.json.gz`, 09:00)

> Royle attack Plover Village boldly, then hold Plover Village.

(`games/round-2/mirror-fords/luna-vs-sol-s4.json.gz`, 09:00)

**`round-1/plain-crossroads/sol-vs-fable-s2`** (Sol red). At 09:00 Sol sends the Second brigade
down the High road into Teasel Village, every other foot brigade after it in support, and its
horse ahead and on the flank; 23 of its 30 orders are written by 09:05. The seven that follow
move two brigades onto the village's flanks and manage the horse. Fable's army breaks at 11:24
with 56% broken; Sol's has 3%.

## Opus

Opus opens every game the same way: two or three brigades march into the village under orders
to hold it at all costs. Its "at all costs" is a garrison order, not an attack.

- **The 09:00 garrison.** At 09:00 it gives 2.3 brigades a game an order "at all costs"; the
  others 0.0 to 1.4 (Fable 1.4). That is 1.8 brigades more than the six pooled (+1.7 to +1.9).
- **"At all costs" means hold.** 18% of its orders carry the phrase (DeepSeek 19%, Fable 13%, the
  rest 1 to 5%), and in 97% of them the phrase follows "hold"; the others 10 to 94%, with Astra
  lowest. The staff reads the phrase as the reckless manner, so most of Opus's reckless tasks are
  holds and the marches that lead to them.
- **Its losses come early.** 24% of its games are lost before 11:30, three times the rate of
  Fable and Astra (8%). Sol (23%), Luna (31%) and DeepSeek (33%) lose as early or earlier.

> Second brigade will march at once in column by the High road, with all speed, to Teasel
> Village, occupy it and hold it at all costs.

(`games/round-1/plain-crossroads/astra-vs-opus-s1.json.gz`, 09:00)

> Grenadier brigade will hold Teasel Village at all costs and report to me how it stands.

(the same game, 10:25)

**`round-1/plain-crossroads/astra-vs-opus-s1`** (Opus blue). Three brigades go into Teasel
Village at all costs at 09:00. When its bodies begin to break, Opus rallies 4 of its 16 breaks
within a quarter hour and tells the Grenadiers to hold the village at all costs and report. Its
army breaks at 10:53 with 80% broken; Astra's has 6%.

## Luna

Luna attacks from the first minute, often with the same line to every brigade. When the attack
fails it can order the whole army off the field.

- **It attacks at once.** In 56% of its games an attack task is written by 09:05; the others 5 to
  33%. Those opening attacks name 2.3 brigades a game; the others 0.1 to 0.5.
- **The opening attack costs it.** Luna scores 38% in the 81 games it opens with an attack and
  58% in the 63 it does not, a difference of 20 points (-36 to -5). For the other six the opening
  makes no difference: 50% with one, 51% without.
- **It orders the army off the field.** In 23 games (16%) one reply sends three or more
  formations to withdraw to an exit; the others do so in 0 to 3% of their games. Luna scores 17%
  in those 23 games.

> Sixth brigade advance in column to Teasel Village, deploy and attack any enemy there boldly.

(`games/round-2/plain-crossroads/deepseek-vs-luna-s4.json.gz`, 09:00)

> First brigade rally, then withdraw to East exit.

(the same game, 10:30)

**`round-2/plain-crossroads/deepseek-vs-luna-s4`** (Luna blue). At 09:00 Luna sends seven
brigades to Teasel Village to "deploy and attack any enemy there boldly". At first contact, at
10:06, it repeats the attack to every infantry brigade. By 10:30 its brigades are breaking, and it
orders every one of them and the guns to rally and withdraw to the East exit, with the horse
after them at 10:35. Its army breaks at 10:49 with 81% broken; DeepSeek's has 26%.

## DeepSeek

DeepSeek answers almost every brief and sends most of its orders again. It holds the village in
parcels, and it answers a broken body by telling it to hold or attack.

- **It re-sends everything.** An order to a formation stands a median 5 minutes before the next
  one to it; the others 18 to 30. 57% of its orders to a formation repeat the task and objective
  of the order before; the others 18 to 25%. The engine rewarded this (see below).
- **It parcels out the village.** 25% of its orders hand a brigade a side, edge or quarter of the
  village ("the north side of Plover Village"); the others 0 to 6%.
- **It answers a break by holding on.** Of breaks whose brigade gets an order within half an
  hour, 52% get a hold, an attack or a charge first; the others 7 to 19%. That is 38 points above
  the six pooled (+35 to +41).
- **Broken ground hurts it most.** It scores 45% on Plain, 34% on Arms and 26% on Mirror, where
  the other six range from 27 to 70%.

> Fifth brigade: hold the eastern houses of Teasel Village and do not quit the village.

(`games/round-2/plain-crossroads/astra-vs-deepseek-s3.json.gz`, 10:40)

> Fourth brigade (Bunce): hold the north side of Plover Village at all costs.

(`games/round-2/mirror-fords/deepseek-vs-opus-s4.json.gz`, sent 13 times, first at 09:20)

**`round-2/mirror-fords/deepseek-vs-opus-s4`** (DeepSeek red). DeepSeek writes 633 orders in this
game. It tells the Fourth brigade, in the same words, to hold the north side of Plover Village
at all costs 13 times from 09:20, and sends the Dragoons one rally order 23 times. It rallies 12
of its 30 breaks within a quarter hour. Its army breaks at 15:39 with 68% broken; Opus's has 6%.

## Sonnet

Sonnet goes quiet when it is hurt. When its bodies break it often gives no order at all, and
fewer than half of its broken bodies' brigades are told to rally.

- **Silent when hurt.** It gives no order at 40% of the briefs that report one of its bodies
  broken; the others 1 to 21%, pooled 13%. That is 26 points above the six pooled (+23 to +30).
- **It rallies least.** 43% of its breaks get a rally order within half an hour (38% within a
  quarter hour); the others 68 to 87%, 31 points fewer than the six pooled (-36 to -26). It
  recovers 15% of the men that broke and ends with a median 54% of its army broken, the most of
  any model.

> Mawhood, the Second brigade will fall back to Heron Ridge in good order and form in line on
> the right of the Third brigade.

(`games/round-1/mirror-fords/sonnet-vs-fable-s2.json.gz`, 10:55)

> Treloar, the Third brigade will attack Plover Village.

(the same game, 13:55)

**`round-1/mirror-fords/sonnet-vs-fable-s2`** (Sonnet red). Sonnet falls back to Heron Ridge at
10:55. Four briefs that report a body broken then pass without an order (11:06, 11:53, 12:05,
12:22); in between it moves only its horse. At 13:15 it advances again, and from 13:55 it sends
its brigades to attack Plover Village. It is silent at 15 of the 22 briefs that report a body
broken and rallies 3 of its 27 breaks within a quarter hour. It loses at 18:00, at the end of
the play-on, with 58% of its army broken; Fable has none broken.

## What to keep in mind

- **Task kinds are the staff's reading.** Rallies, holds, attacks and the minute an order was
  written come from the staff's reading of each order (Jev 1.14 in 450 games, GPT-6 Luna in 54);
  a different reading would move them. Standing limits, placement, quarters of the village, "at
  all costs" and silence are read from the general's own words. Breaks come from the reports in
  the general's briefs, so a body that broke without a report is not counted.
- **A single game is close to a coin flip.** Replaying the same pairings with identical settings
  gave the same winner in 15 of 30 games. The game in each section shows the pattern at work; it
  does not prove it. The findings rest on 144 games a model.
- **The generals' brief changed between rounds.** In round 1 it said that a point given as a
  distance and direction from a village cannot be found; in round 2 it allowed one. Orders naming
  such a point went from none of six models' and 11% of DeepSeek's in round 1 to 11% (Luna) to
  74% (Astra) of every model's in round 2. Any finding that a model places brigades by measured
  points is therefore a round-2 effect, and none is drawn here.
- **The games were played with three faults**, fixed since
  ([`docs/engine.md`](engine.md#changes-since-the-matrix)):
  - An order sent again restarted the body's task, which favoured a general who repeats himself.
    DeepSeek re-sends every few minutes, so its 35% was scored with that help. Its measures here
    describe what it wrote, not what the engine would make of it now.
  - A rally halted the formation where it stood, whatever place the order named. Astra's "rally
    the First brigade at 1500 m west" did not move the brigade; its "withdraw to ..., then rally"
    orders did. Its recovery was earned with the fault in place.
  - An order to the army showed in the brief as every brigade's last order, hiding the task the
    brigade was carrying out. Every model saw this in every game. It bears on what a general was
    shown of its own army, and so it may touch both Sonnet's and Opus's silence and DeepSeek's
    re-sending.
