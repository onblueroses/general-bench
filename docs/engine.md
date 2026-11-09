# The engine

General Bench is a free Kriegsspiel with machine parts. A general writes orders in prose; a
staff model reads them into tasks; aides carry them across the field; a continuous engine works
out marching, fire, shock, morale and rout one minute at a time; and a mechanical verdict decides
the battle. This page describes each part as the code implements it. Package: `src/kriegsspiel/`.

The division of labour is strict. The staff and the umpire are language models and judge only
what is judgment: what an order means, how favourable a clash looks. They never see a number
they must compute with. Everything that is physics (distances, speeds, casualties, morale) is
computed by the engine, deterministically from the scenario, the seed and the orders.

Every number a general may need is stated to him in the [rules sheet](rules-sheet.md), and a
test holds each of those numbers to the constant it cites. This page explains the mechanisms and
gives the numbers where they explain something; the rules sheet is the complete table.

| module | what it does |
|---|---|
| `types.py` | the shared data types: cover codes, features, bodies, formations, tasks, messages |
| `world.py`, `geometry.py` | terrain raster, named features, routing, line of sight |
| `units.py`, `scenario.py` | loading a battle pack ([pack format](pack-format.md)) |
| `movement.py`, `vision.py`, `combat.py`, `morale.py` | the physics of one minute |
| `command.py` | the staff protocol, couriers, reports, the headquarters' picture |
| `drill.py` | the per-minute drills that execute tasks, and simultaneous movement |
| `staff.py`, `staff_text.py` | prose orders to tasks |
| `umpire.py` | the melee factor; the narrative verdict |
| `jev.py`, `decisions_llm.py` | the decisions clients (Jev, or a Codex model standing in) |
| `narrator.py`, `account.py` | the general's brief; the umpire's account of the field |
| `verdict.py` | the ordinal verdict |
| `sim.py`, `clock.py` | the minute loop; clock strings and minutes |
| `commander.py`, `players.py` | generals, model harnesses |
| `build.py`, `play.py`, `report.py`, `run.py` | a game built from a pack, the play loop, the game report, the command line |
| `grid.py`, `results.py`, `cross.py` | batches of games, their results read from the logs, the cross-pack report |
| `log.py`, `replay.py` | the run log and bit-identical replay |
| `bot.py` | a scripted opponent for stub games and tests |

## World and terrain

Positions are floats in metres on a plane: `x` east, `y` north, origin at the pack's south-west
corner. There are no hexes.

Terrain is a raster (`types.Terrain`): a cell size (`cell_m`, 25 m in every battle pack), an
elevation array and a cover array. Cover is one of open, rough, wood, village, orchard, marsh,
water and road (`types.Cover`). Slope is derived from elevation. Roads are rasterised onto the
cover layer.

A feature is a named thing a general or the staff can refer to: a village, wood, height, ridge,
stream, pond, road, bridge, farm, mill, church, ford, entry or exit, with point, polyline or
polygon geometry and a list of aliases. Names and aliases are unique within a world,
case-insensitively. A feature is what the staff can resolve an order's place to; ground that has
no name cannot be ordered to, except as a measured offset from a named place (see
[the staff](#the-staff)).

Water is impassable except within a bridge's radius (40 m by default) or at a ford whose
`passable` list includes the arm. A ford slows the arms that may use it (by default foot and
horse at half speed; a pack can set a factor per arm). Aides cross wherever cavalry can.

`World.path_cost` routes a body: an A* search on a coarse 100 m grid with a node on every bridge
and ford, preferring roads, followed by a straight-line smoothing pass where the straight leg is
passable and no slower. Routing is deterministic.

`World.line_of_sight` walks a ray over the elevation model (eye height 2 m for a body, 3 m for a
mounted general; target 2 m tall). Woods and villages block sight more than 50 m deep into them.
Smoke, night and weather are not modelled; in every battle pack the light lasts past the end of
play.

## Bodies and formations

The simulated entity is the tactical body (`types.Unit`): an infantry battalion, a cavalry
regiment, a battery. Each body has an arm (infantry, cavalry, artillery, train), a kind (line,
grenadier, fusilier, grenzer, cuirassier, dragoon, hussar, foot battery, horse battery, train),
men (for a battery, its crew), guns and calibre, a quality from 1 to 5, a position and facing,
and a state: column, line, square, skirmish, limbered, unlimbered, routed or destroyed. It also
carries morale (0 to 100, starting at 60 + 8 x quality), fatigue (0 to 100), ammunition (starting
at 100), disorder (0 to 100) and its current task.

Infantry battalions can carry battalion guns (`battalion_guns` in the order of battle). These
are not separate bodies: they fire with the battalion while it stands in line and are lost when
it is broken hand to hand.

Formations (`types.Formation`) are the command tree: an army root per side, then wings, columns
or brigades, each with a commander, aliases and optionally a headquarters position. Generals
address formations; the drills decompose a formation's task to its bodies. In the battle packs
every army is a root and eleven brigades of two bodies each (one Arms brigade has three).

## The minute

`Sim.step()` advances one minute in a fixed phase order:

1. **Messages.** Orders written this minute leave with their aides; messages whose aide has
   arrived are handed over. Bodies due to arrive enter at their entries.
2. **Orders.** Newly received tasks are applied, as are waiting tasks whose start condition has
   come; finished tasks hand over to their sequels.
3. **Movement.** Headquarters ride; every body moves along its route; bodies at an exit their
   task names leave the map.
4. **Vision and reports.** Sightings are updated for every body and headquarters.
5. **Combat.** Fire, then melee.
6. **Morale.** Losses lower morale; bodies break or are destroyed; brigade reports are written.
7. **Recovery.** Fatigue, disorder and morale recover; routed bodies flee or rally.
8. **The verdict** reads the field (see [the verdict](#the-verdict)); the state hash is taken and
   the tick is logged.

## Movement

Speeds are metres a minute for fresh troops in the open, by road and across country:

| body | road | country |
|---|---|---|
| infantry in column | 75 | 60 |
| infantry in line | 40 | 40 |
| infantry in skirmish order | 50 | 50 |
| infantry in square | 20 | 20 |
| cavalry at the walk | 125 | 100 |
| cavalry at the trot | 250 | 200 |
| cavalry at the gallop | 350 | 350 |
| foot battery | 60 | 40 |
| horse battery | 100 | 100 |
| train | 50 | 25 |
| aide | 400 | 250 |
| headquarters | 200 | 150 |

Bold and reckless assaults go at the double, 1.3 times as fast; a routed body flees at 75 m a
minute by road and 70 across country. Cavalry is blown after 3 minutes at
the gallop. Cover multiplies speed: wood 0.5 for foot and 0.25 for horse and guns, village 0.5,
rough ground and orchards 0.7, marsh 0.3 for foot and horse and closed to guns off a road; trains
move only on roads and open ground. Uphill the factor is 1 - 2 x grade, never below 0.4; downhill
costs nothing. Fatigue and disorder each multiply speed by (1 - value / 200).

Formation changes take time: column to line 3 minutes, line to column 2, to or from square 2, to
or from skirmish order 2, cavalry 1; a foot battery limbers or unlimbers in 3, a horse battery in
2. Turning costs a minute per 90 degrees. A line that wheels on the march pays the turning rate;
columns and limbered guns follow their head for free.

Fatigue rises each minute by 1 at the trot or the double, 3 at the gallop or in melee, 0.5 while
firing muskets; ordinary marching costs nothing; a halted body out of the fight recovers 1 a
minute.

## Fire

Musketry reaches 250 m. Hits per musket per minute fall with range (0.024 at 25 m, 0.015 at
50 m, 0.008 at 100 m, 0.0008 at 250 m, interpolated between), scaled by quality, fatigue and
ammunition: 700 fresh men of quality 3 kill about 6.7 a minute at 100 m. A line fires with all
its men, a square with a quarter, a column with a sixth; skirmishers fire with half their men at
1.5 times the rate. Columns take 1.5 times the musketry, skirmishers half. Fire into a flank
counts 1.5, into the rear 2. Targets in wood or village take half of all fire, on rough ground
0.8. A body fires only at targets it can see, within 60 degrees of its front (guns 45), not
through friends (a friendly body in a 60 m corridor between firer and target masks it), and not
in a minute in which it moved more than 10 m.

Artillery: roundshot reaches 1,400 m from a 12-pounder and 1,000 m from a 6-pounder; a gun kills
1 man a minute out to 300 m, 0.6 at 600 m, 0.25 at extreme range. Canister, within 400 m, kills
5 at 100 m and 3 at 200 m. Columns suffer twice, squares 2.5 times, skirmishers 0.4, batteries
half. Gun casualties scale down against bodies smaller than 300 men, which fill less of the
beaten zone. Battalion guns fire roundshot to 600 m and canister to 300 m at half a battery
gun's effect.

Every body starts with 100 rounds of ammunition: musketry spends 2 a minute, guns 1. Below 20,
fire halves; at 0 it stops. There is no resupply.

Rates are expected casualties per minute. The engine turns them into whole men by seeded
stochastic rounding, so a game is noisy in its details and exactly reproducible from its seed.

## Melee

Bodies within 60 m are in contact. A body whose task and drill take it into an enemy (an
infantry assault, a cavalry charge) asks for a clash.

Each side's weight is men x quality x a state factor x morale / 60; the attacker's is also
multiplied by (1 - fatigue / 150) and by the umpire's factor. Attacker state factors: cavalry at
the gallop 3, trot 2, walk 1; infantry in column 1.5, line 1, skirmish 0.5. Defender state
factors: square against horse 4; steady line against horse 3, shaken or flanked line against
horse 0.5; line against foot 1.2; foot in wood or village 2; column 1; skirmishers 0.5; halted
horse 0.7; guns unlimbered 0.5, limbered 0.2; routed 0.1. Any defender but a square struck in
flank or rear counts half. A defender that can fire gets up to two volleys into the attacker as
it comes in.

The ratio decides:

| attacker / defender | result |
|---|---|
| over 1.5 | the defender breaks at once; it loses 8%, the attacker 2% |
| 0.67 to 1.5 | hand to hand for 3 minutes, each side losing 3% of its men a minute; the lower morale breaks |
| under 0.67 | the attacker is repulsed, loses 6% and falls back 100 m disordered |

Horse meeting horse at the charge both strike, and either may break. Cavalry charging a steady
square recognises it at 100 m, pulls up, takes its fire, loses 1% more and falls back; it does
not charge that square again for 15 minutes, nor while it stays in square. A body that reaches a
routed enemy cuts into it once per flight (5% of its men) and is disordered for 3 minutes.

**The umpire's factor.** Before a clash resolves, the engine writes a plain-prose account of it
(who strikes whom, formations, ground, flank or front, fatigue, steadiness) and the umpire grades
the attacker's prospects on five levels: hopeless, poor, even, favourable, decisive. The levels
map linearly onto 0.7 to 1.4 (even is 1.05), and the factor is pulled toward 1.0 by the umpire's
confidence: `factor = 1 + confidence x (level_value - 1)`. So every melee in a game is scaled by
a factor between 0.7 and 1.4, chosen by a model reading a description. The engine stores the
account, the answer and the factor in the log (`umpire` records). Without an umpire the factor is
1.0.

**Who strikes first.** All clashes of a minute are resolved from the field as it stands after
movement and fire. A body takes part in at most one new clash a minute. When two bodies go in at
each other, a seeded draw decides which strikes as the attacker; when clashes compete for a body,
a draw orders them. The draws are keyed by where the bodies stand, never by their ids or sides,
so renaming the armies or swapping the order in which sides are processed changes no draw. Two
bodies alike in every respect standing at each other's image through the field's centre make an
even clash: both recoil disordered.

## Morale, rout and rally

Morale falls 1.5 points for each per cent of a body's starting men lost, and disorder rises 1
point per cent. A body breaks (routs) when its morale falls below 25. Losses taken quickly
therefore break quality 2 at about 34% lost, quality 3 at 39% and quality 5 at 50%. A body
breaking costs friends within 300 m 5 morale. A body is destroyed below 10% of its starting men
(or 5 men), and a battery with no serviceable gun is destroyed. Out of the fight and taking no
losses, a body regains 0.2 morale a minute, never above its starting value, and sheds 2 disorder
a minute.

A routed body flees until no enemy is within 1 km. With no enemy within 800 m it regains 0.5
morale a minute, or 2 under a RALLY task. It re-forms, in column and disordered, when no enemy is
within 600 m, its recovery clock has run, and its morale has reached 55, or 45 under the order to
rally: from the breaking point at least 60 minutes alone, 10 with the order. It then takes up its
formation's task again.

Recovery clocks, in minutes before a body may rally and before it may charge or assault again:
repulsed 4 and 6; broken by fire or a lost melee 6 and 12; broken at the first shock 10 and 20.
Horse re-forms for 5 minutes after any charge.

Routed and destroyed bodies, and bodies that fled off the map or were captured, count toward
their army's break (see [the verdict](#the-verdict)).

## Vision and fog

A body sees enemy troops in the open up to 2,500 m away, troops in a wood or village only from
400 m, subject to line of sight. Beyond 1,200 m an enemy is only "troops"; within it his arm and
his size to the nearest 100 men are made out; within 500 m his exact strength and formation. A
brigade remembers an enemy it has lost sight of for 30 minutes. A routed body sees nothing.

Sightings reach the brigade commander at once. The army commander knows only what his
headquarters sees from where it stands and what reports have reached it (`command.picture`).
Everything the general reads is built from that picture.

## Command

### Tasks

What the staff produces and the drills execute is a `Task`: a kind (hold, advance, attack,
charge, withdraw, screen, bombard, support, rally, move headquarters), the addressed formation,
an objective (a named feature, an enemy body as the side knows it, a friendly formation, or a
point), optional route waypoints, a desired state, a start (on receipt, a time, or a condition:
when engaged, when a place is reached, when an enemy is seen, when a body routs), a reaction on
contact (halt, engage, press, fall back), an optional stop condition, a manner (cautious,
measured, bold, reckless), prohibitions (do not charge formed infantry, do not attack, do not
pursue, do not engage, do not advance beyond a place), one sequel task (`then`), and the order's
source sentence.

### Drills

Tasks are executed by fixed, deterministic drills, not a planner:

- Infantry march in column, by road where the route allows, and deploy into line at 600 m from a
  known enemy if cautious, 400 m ordinarily, 300 m if bold. Told to attack, the line halts to fire
  at 200, 120, 80 or 60 m (cautious, measured, bold, reckless) and goes in with the bayonet after
  10, 5 or 0 minutes of fire, sooner if the enemy falls into heavy disorder; a cautious attack
  never closes.
- Infantry form square of their own accord when enemy horse is seen within 400 m, no friendly
  horse is within 600 m and a flank lacks a formed friend within 150 m; troops in a wood or
  village stay as they are. They leave square when no enemy horse has been within 600 m for 3
  minutes.
- Cavalry told to charge trots from 800 m and gallops the last 250 m; advancing horse not told to
  halt or avoid a fight charges any enemy within 600 m.
- Guns move limbered and unlimber at their objective, or within 800 m of the enemy when told to
  bombard.
- Hold deploys facing the nearest threat; screen keeps 600 to 1,000 m from the enemy and falls
  back when pressed; support follows a friendly formation at 300 m; withdraw moves away from the
  nearest enemy, 1 km if no objective is given; rally lets a formation's routed bodies recover
  and halts it where it stands, or, when the order names a place, marches it there and halts.
- An order the formation is already carrying out, sent again in other words or at another time,
  changes nothing: a line keeps its fire before the bayonet and horse keeps re-forming.
- An advance told to leave by an exit, engaging or pressing, fights only what stands within
  200 m of its line of march and goes round what it will not fight. Any other advance halts at
  what it meets.

### Couriers and reports

An order leaves headquarters when the general writes it and acts when its aide arrives. Aides
ride 400 m a minute by road and 250 m across country, crossing water only at bridges and fords;
an order with no way across comes back. An order moving headquarters acts at once.

A brigade reports on first contact, on being engaged, on reaching its objective, when one of its
bodies breaks, when its losses pass 25%, and otherwise every 30 minutes. Reports are written from
what that brigade knew when it wrote them and ride back at the aides' pace, so a report is as old
as its ride. All messages are logged with their send and receive times.

## The staff

The staff (`staff.py`) turns a general's prose order into tasks. It reads the order against the
side's own vocabulary: its formations by name, commander and alias; the named places; the enemy
bodies the headquarters currently knows, named as the brief names them; and relative places such
as "our left flank". It asks the decisions model typed questions and assembles tasks from the
answers.

Per order, usually in two requests:

1. **Addressing.** For each formation, a yes/no question: does this order give it an
   instruction? For an order of several clauses, also one per formation and clause.
2. **Details.** For each addressed formation: choices for kind, objective, route waypoint,
   desired state and reaction on contact; a graded question for manner; yes/no questions for each
   start condition with a choice for its subject; questions for prohibitions, triggers and the
   sequel after "then".

Text rules check the model's reading against the words of the order before anything is sent: a
clause that opens with a formation's name goes to that formation; an arm word ("the cavalry")
goes to one formation; a formation named only as a reference is not addressed; a headquarters
clause becomes a move-headquarters task without a question; an order that places a point by a
measured distance and compass direction from a named place ("halt 900 m east of Medlar Village")
adds that point to the vocabulary as a place of its own. A final question checks each task
against its words, and a task that goes against them is not sent.

**The staff asks back.** When the reading of a kind or objective is unsure (the largest
probability under 0.5), or names something outside the side's vocabulary, the staff does not
guess. The formation gets a tentative hold (which never replaces a task it already has), and the
general receives a question at once (for example "I read «...» as ...; what do you intend?"). A
staff question triggers a consultation (see [the play loop](#the-play-loop)).

The decisions model is Jev (`typesafe/jev-1.14`, TypeSafe's decision model) through OpenRouter or
the Vercel AI Gateway (`jev.py`; `JEV_PROVIDER` chooses, else the key found decides). It answers
a state and a map of named questions of three types (choice, yes/no, graded) in one request. With
`JEV_MODEL=codex/<model>` a Codex model answers the same requests in Jev's shape
(`decisions_llm.py`); the [staff study](staff-study.md) measures how far the two agree. Each game
record names its staff model.

## The umpire

The umpire (`umpire.py`) is the same decisions model asked different questions.

- **The melee factor**, above: the one place where a model's judgment enters the physics.
- **The narrative verdict.** At the end of a game the umpire reads an account of the field
  (`account.py`: each side's men at the start, lost and still formed; bodies by condition; who
  holds each named place) and names a winner. In the battle packs this is recorded beside the
  mechanical verdict (`jev_winner`) as a health number and decides nothing.

## The verdict

A battle pack whose `mission.json` says `"verdict": "ordinal"` is decided by `OrdinalJudge` in
`verdict.py`, which reads the field at the end of every minute. The rule, its parameters and why
they are set as they are: [battles](battles/README.md#the-verdict). The judge reads plain field
records, so a recorded game is judged by the same code.

## The brief

The narrator (`narrator.py`) writes what the general reads. It is built from copies of the
start-of-day data and reads only the side's `command.Picture`, never the live simulation, so the
truth cannot leak into a brief. Tests check this with an unseen enemy body and an unreported
friendly move.

The first brief of a side opens with the persona ([player prompt](player-prompt.md)), then:

1. the clock and where headquarters stands;
2. the umpire's notice, during the play-on (the last reading of the village and when the next
   one falls);
3. new dispatches since the last brief, verbatim with their receipt times, staff questions
   included;
4. earlier dispatches of the last hour, verbatim;
5. older dispatches in brief, one line per sender;
6. the general's own orders: addressees, when each aide left, whether it has arrived;
7. his own troops as last reported: place, distance and bearing from headquarters, men, report
   time, the last order and the staff's reading of it (an order to the army counts as a
   brigade's last order only when it sets that brigade a task);
8. the enemy as known at headquarters, grouped: count, arm, estimated strength, place, distance
   and bearing, when last seen;
9. the ground around headquarters: the cover underfoot, and on eight bearings the cover at 1, 2
   and 3 km and the rise or fall of the ground;
10. named places, nearest first, with distance, bearing and relative height.

The budget is 6,000 words; above it the farthest named places go first, then the older half of
the earlier dispatches.

A general keeps one conversation for the whole game, so after the first brief he gets update
briefs: the clock, the notice, the new dispatches, the orders on the road or delivered since, and
a standing picture of one line per own brigade and the grouped enemy. The ground and the named
places come again only when headquarters has moved more than 500 m.

## The play loop

`play.play` runs a game between two commanders (`commander.py`): a model general
(`LLMCommander`), a scripted list of orders, a scripted bot, a commander that never orders, or a
replay of a logged game.

**Consultation cadence.** Each general is consulted every 15 battle minutes from the start, and
at once when a report of first contact or of a broken body, or a staff question, reaches his
headquarters, but never twice within 5 minutes and never twice in one minute. A cadence slot
waits until 5 minutes after his last reply has arrived.

**The clock waits.** While a general thinks, the battle stands still: his reply is submitted at
the minute he was consulted, whatever its wall-clock latency. Every model therefore gets the same
number of decisions at the same moments, and speed never trades against outcome. Reply latency
is logged (`wall_s`) and reported separately. (`--speed N` instead runs the simulation at N
battle minutes per wall second while a general thinks; the benchmark games use the waiting
clock.)

**Replies.** The reply is plain prose. It is split into orders: one per line, list marks and
markdown emphasis stripped, lines under three words and "No orders" dropped. Orders of a minute
are submitted in side order, then consultation order, so thread timing never reorders the
staff's requests. Silence, or "No orders.", leaves the orders in force.

**Harness failures.** A lost turn (a non-zero exit, an error flag, an empty reply under a rate
limit, a timeout) is retried up to 12 times with waits doubling from 15 s to at most 300 s. A
general who stays unreachable stops the game, so a silent model is never scored as a model that
chose not to order. If the decisions model fails for good mid-game, the game also stops cleanly:
the half-run tick is not logged and a `stopped` record says why.

The loop ends when the verdict rules the battle over, or at the end of the play-on.

## Changes since the matrix

The 504 matrix games and the records in `games/` were played before three faults were fixed; the
game study found them (`docs/generals.md`). The code at the tag `matrix` is the code round 2 was
played with, and its games replay there bit for bit.

- An order sent again reset the body to the start of its task: a line's fire before the bayonet
  began again and horse cut its re-form short. A general who repeated his orders every few
  minutes gained by it; DeepSeek did most.
- An order to the army, such as moving headquarters, showed in the brief as every brigade's last
  order until the brigade had a new one, hiding the task it was carrying out.
- A rally halted the formation where it stood, whatever place the order named.

## Determinism and replay

Given the pack, the seed and the orders with their minutes, a game is bit-identical. Every random
draw comes from a generator keyed by the seed, the event's kind, the minute and where the bodies
in it stand. Positions and facings are set on a fine lattice (2^-16 m and degrees) after
movement and at the end of each minute, so the image of a position under the 180-degree rotation
is exactly representable. On a pack whose ground and armies are symmetric (Plain, Mirror), the
rotated game is therefore the exact image of the game, and the symmetry tests check this. The
wall clock enters only as the minute a reply is submitted, which is logged.

`replay.replay_game(log)` plays a logged game again with no model and no network: replies come from
the log's commander records (each brief is re-narrated and must equal the logged one), decisions
answers from the logged calls (a request that differs fails the replay), and each submission
happens at its logged minute. The new ticks, commander records and verdict must equal the old
ones. `replay.replay_jev(log)` replays from the orders, re-translated by the staff against the
logged answers.

## The run log

`log.RunLog` writes JSONL:

- a header: seed, scenario, decisions model and mode, the hash of the starting state; for a play
  game also the players, cadence, side order and memory setting;
- one tick record per minute: the state hash, events, the orders written that minute with the
  staff's tasks and questions, messages, umpire answers and every decisions call;
- one `commander` record per consultation: side, trigger, minute, the full brief and its word
  count, the reply, the split orders, wall seconds, session id, player, model, and the harness's
  exit code and token counts;
- the `verdict` record, or a `stopped` record.

The published game records under `games/` are condensed from these logs.

## Running games

```sh
# a stub game: scripted bots, no model, no staff
uv run python -m kriegsspiel.run --scenario data/plain-crossroads \
  --players red=bot,blue=bot --mode stub --no-battle-over

# a model game, decisions recorded as fixtures beside the log
uv run python -m kriegsspiel.run --scenario data/plain-crossroads \
  --players red=opus,blue=sol --mode record --log runs/demo/run.jsonl

# replay it with no model and no network
uv run python -m kriegsspiel.run replay runs/demo/run.jsonl
```

`--players` takes `side=player` pairs: a name from `players.ROSTER`, `script` (the pack's
`script.json`, which needs a live staff), `bot` or `null`. Decisions modes: `live`, `record` (use
a fixture when one exists, else call and save it), `replay` (fixtures only), `stub` (no network;
first option, 0.5, middle level). `kriegsspiel.grid` runs many games as subprocesses with a
manifest, per-harness concurrency limits and `--resume`; [players](players.md) describes the
harnesses.
