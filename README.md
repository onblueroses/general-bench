# General Bench

**Language models as generals in a free Kriegsspiel.**

Each model commands a horse-and-musket army of about 12,000 men. It writes its orders in
prose, as a general of 1800 would. A staff reads them into tasks and asks back when an order
is unclear. Couriers carry them across the field at a horse's pace, and a continuous engine
resolves marching, musketry, artillery, charges, morale and rout minute by minute. The general
sees only what its officers report. The battle ends when an army breaks.

![Mirror at 11:55: GPT-6 Astra's red army holds Plover Village while Claude Opus 5.5's blue brigades attack it from the south-east](docs/figures/battle.png)

Seven models played every other model from both sides on three battles, four seeds each:
**504 full games**.
Every brief, every order, every reading of an order and every verdict is in [`games/`](games/).

## Results

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="docs/figures/standings-dark.png">
  <img alt="Ratings with 95% intervals: GPT-6 Astra 1628; Claude Fable 5.1 1539, GPT-6 Sol 1532, Claude Opus 5.5 1517, GPT-6 Luna 1478; DeepSeek V4.1 Flash 1405, Claude Sonnet 5.5 1400" src="docs/figures/standings.png">
</picture>

| rank | model | W-D-L | share | 95% interval | rating | likely rank |
|---|---|---|---|---|---|---|
| 1 | GPT-6 Astra | 93-15-36 | 70% | 63 to 77% | 1628 | 1 |
| 2 | Claude Fable 5.1 | 73-16-55 | 56% | 49 to 64% | 1539 | 2 to 4 |
| 3 | GPT-6 Sol | 71-17-56 | 55% | 47 to 63% | 1532 | 2 to 4 |
| 4 | Claude Opus 5.5 | 68-16-60 | 53% | 45 to 60% | 1517 | 2 to 5 |
| 5 | GPT-6 Luna | 64-6-74 | 47% | 38 to 54% | 1478 | 3 to 5 |
| 6 | DeepSeek V4.1 Flash | 45-11-88 | 35% | 28 to 43% | 1405 | 6 to 7 |
| 7 | Claude Sonnet 5.5 | 45-9-90 | 34% | 27 to 42% | 1400 | 6 to 7 |

144 games per model. A draw counts half. The rating is a Bradley-Terry strength on the Elo
scale. Intervals and ranks come from resampling the games. Reproduce with
`uv run python scripts/standings.py`.

**Read it as three tiers, not seven places.** Astra is first in 99% of the resamples. Fable,
Sol, Opus and Luna form a middle group whose order is not settled. DeepSeek and Sonnet are
below it and cannot be told apart. The battles agree on the tiers but not on the order inside
them: Fable takes 62% on Plain and 46% on Arms, where the armies differ; DeepSeek takes 45% on
Plain and 26% on Mirror's broken ground.

Head to head, rounds, replays, the noise floor and the seat balance: [`docs/results.md`](docs/results.md).

## Each model commands in its own way

The same brief, 144 games, and each model keeps a recognisable style. Measured from the staff's
reading of every order (`scripts/styles.py`); the orders below are quoted from the games.

- **Astra advances and rallies.** It rallies broken units more than any other model and ends
  its battles with the least of its army broken: 18%, against 37 to 54% for the others.
  > Pettifer, advance boldly in column by High road to Plover Village, seize the crossroads, and
  > hold within 200 m of them; do not pursue beyond the village.
- **Sol is laconic.** Its replies run to a median of 22 words, it is silent at two briefs in
  five, and it sends the fewest orders, 52 a game.
  > Royle attack Plover Village boldly, then hold Plover Village.
- **Fable builds a line and fences it.** One order in eight carries a standing limit
  ("attacking nothing without a further order"), and one in five places a brigade by another;
  no other model does either as often. It writes to its brigades most often among the Claude
  and GPT models and fights the longest battles.
  > Sixth brigade: advance to Bullace Farm and hold there in column behind the First brigade,
  > attacking nothing without further orders.
- **Opus is quiet and direct.** It is silent at 40% of its briefs and, when it speaks, it is
  the model most ready to spend a brigade: 16% of its tasks are to be carried out at all costs.
  > Second brigade, Pashley, will attack Medlar Village in column at all costs, then hold it.
- **Luna attacks.** A fifth of its tasks are attacks, two to three times any other model's
  share, and it fights the shortest battles.
  > Grenadier brigade advance in column to Plover Village, then support the Second brigade.
- **DeepSeek over-controls.** It answers almost every brief, with a median of 284 words, and
  sends 328 orders a game, 44% of them "hold". It places brigades by measured distances.
  > Second brigade (Quayle): march by the High road to a point 400 m east of Plover Village;
  > halt there and form line facing west.
- **Sonnet is passive.** It is silent at 46% of its briefs and gives the most support orders.
  > Fourth brigade: advance to Osier road and support the Grenadier brigade.

## The battles

Three battles on invented ground with invented names, so that no model can recall a historical
answer. Each changes one thing:

- **Plain**: open ground, identical armies, one crossroads village between them.
- **Mirror**: the same armies on ground that matters (brooks, fords, a ridge and a wood on each
  side), laid out so that each army sees the same field from its end.
- **Arms**: Plain's ground, armies of equal strength and different make-up: a horse army against
  a foot army.

Each army on Plain and Mirror has eleven formations of mixed quality, 12,440 men and 44 guns.
The day runs from 09:00 to 16:00, with up to two hours of play-on. Design and numbers:
[`docs/battles/`](docs/battles/README.md).

## How a game works

1. **Brief.** Both generals get the same text with the names swapped: the mission, the verdict
   rule word for word, a rules sheet with the engine's numbers, their own order of battle and
   the enemy's in outline. The opening brief runs to about 4,700 words.
2. **General.** One conversation per general per game, with no tools. It is consulted every
   fifteen battle minutes and when a report arrives, and the battle clock waits while it
   thinks. Every model plays at high reasoning effort, and we set no output cap.
3. **Staff.** A decisions model reads each order through fixed questions: who is addressed,
   which task, which objective and route, what to do on contact, when to start and stop. An
   order it cannot place goes back to the general as a question.
4. **Engine.** Movement, fire, melee, morale, rally, line of sight and couriers, one minute at
   a time, deterministic given the seed and the orders.
5. **Umpire.** It weighs each melee from a written account and scales the attacker by a factor
   between 0.7 and 1.4.
6. **Verdict.** An army with more than 40% of its men routed or destroyed for thirty minutes
   has lost. If neither breaks, whoever holds the village at 16:00 wins; if it is contested,
   play goes on by quarter hours for up to two hours, then it is a draw. 85% of the games were
   decided by a break.

The engine, the staff, the brief and the play loop: [`docs/engine.md`](docs/engine.md).

## What to keep in mind

- **A single game is close to a coin flip.** Replaying the same pairings with identical settings
  gave the same winner in 15 of 30 games. The standings rest on many games, which is what their
  intervals measure.
- **The staff is part of the instrument.** Every order is read by a model, and a different
  reading moves results. Jev 1.14 read 450 of the games; GPT-6 Luna, also a player, read 54.
  Their agreement is measured in the [staff study](docs/staff-study.md).
- **The harnesses differ.** The Claude models play through Claude Code, the GPT-6 models through
  the Codex CLI, DeepSeek through its API. Our prompt bytes are identical; each harness wraps
  them in its own system prompt ([`docs/players.md`](docs/players.md)).
- **Two rules changed after the first games.** The tie-break for two broken armies was added
  after 60 games and applied back to them (it changes ten results). After round 1 the staff
  learned to place a point given as "400 m east of the village", and the generals' brief, which
  had said such a point cannot be found, was changed to allow it; DeepSeek's round-1 games,
  replayed with both, moved from 37% to 32%. Round 2 was played with both.
- **Luna's round 2.** Luna scored 36% in round 1 and 57% in round 2. Controlled replays put it
  back at 29 to 42%, so we pool the rounds and read the jump as chance.
- **The horse army on Arms wins 55%.** Plain and Mirror are even. Every pair plays both sides,
  so the seat cancels in the standings.
- **Built with a contestant.** The engine and the harness were written with the help of Claude
  Fable 5.1 and Codex models. Fable also plays.
- **One engine, one era.** The results describe command in this game.

## Running it

```sh
uv sync --group dev
uv run pytest                     # the test suite, about two minutes

# a scripted game: both sides play the pack's script, a stub staff, no model and no network
uv run python -m kriegsspiel.run --scenario data/plain-crossroads --mode stub

# a game between two models; the staff is Jev through the Vercel AI Gateway (AI_GATEWAY_API_KEY)
# or OpenRouter (OPENROUTER_API_KEY), either key in .local/.env; or a Codex model standing in
# for Jev with JEV_MODEL=codex/gpt-6-luna
uv run python -m kriegsspiel.run --scenario data/plain-crossroads \
  --players red=opus,blue=sol --mode record

# replay a game from its full run log and the staff's recorded answers beside it, bit for bit,
# with no model or network call (the records in games/ are slimmed and do not replay)
uv run python -m kriegsspiel.run replay runs/<game>/run.jsonl

# a round robin on one battle (the matrix ran this on all three, seeds 1 to 4),
# then the standings over its records
uv run python -m kriegsspiel.grid --scenario data/plain-crossroads \
  --round-robin opus,sol,luna --seeds 1 --out runs/my-grid
uv run python scripts/slim_games.py --out games/mine runs/my-grid
uv run python scripts/standings.py games/mine
```

Claude players need `claude` installed and logged in, GPT players `codex`. API players (DeepSeek)
read `DEEPSEEK_API_KEY` and need `--allow-api` on a grid. To add a model, add an entry to
`ROSTER` in [`src/kriegsspiel/players.py`](src/kriegsspiel/players.py).

## Game records

`games/round-1/` and `games/round-2/` hold the 504 matrix games, one gzipped JSON per game:
both generals' system prompts, every consultation with its brief and reply, every order as the
staff read it, every melee the umpire weighed, and the verdict. The format is described in
[`scripts/slim_games.py`](scripts/slim_games.py). `games/extra/` holds the noise-floor replays,
the DeepSeek rerun and the GPT-6 replays.

| script | what it prints |
|---|---|
| `scripts/standings.py` | standings, ratings, intervals, likely ranks, head to head, by round |
| `scripts/styles.py` | how each model commands |
| `scripts/checks.py` | how battles end, seats, the noise floor, the replays, the DeepSeek rerun |
| `scripts/figures.py` | the figures above (`uv run --group figures`); the map replays a full run log |

## Repository

| path | what |
|---|---|
| `src/kriegsspiel/` | the engine, staff, umpire, narrator, verdict, players and grid runner |
| `data/` | the three battles: `plain-crossroads`, `mirror-fords`, `arms-medlar` |
| `games/` | the published game records |
| `docs/` | the engine, the battles, the players, the staff study, the results |
| `scripts/` | the analysis scripts above and the record slimmer |
| `tests/` | the test suite, with two test-only packs (Kolín 1757 and a flat test field) |

MIT licence. The game records and documents may be reused with attribution.
