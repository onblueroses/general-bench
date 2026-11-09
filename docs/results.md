# Results

Seven models, three battles, every ordered pair of models from both sides, four seeds: 504
games, 144 for each model. Rounds 1 (seeds 1 and 2) and 2 (seeds 3 and 4) were played a week
apart with the same settings; between them the staff learned to place a measured point and the
generals' brief was changed to allow one ([The staff](#the-staff)). Every number on this page is reproduced from
the records in `games/` by the scripts named under it.

| name | model | played through |
|---|---|---|
| astra | GPT-6 Astra | Codex CLI |
| sol | GPT-6 Sol | Codex CLI |
| luna | GPT-6 Luna | Codex CLI |
| opus | Claude Opus 5.5 | Claude Code |
| fable | Claude Fable 5.1 | Claude Code |
| sonnet | Claude Sonnet 5.5 | Claude Code |
| deepseek | DeepSeek V4.1 Flash | OpenAI-compatible API |

Every model plays at high reasoning effort with no cap on its output.

## Standings

`uv run python scripts/standings.py`

| rank | model | W-D-L | share | 95% interval | rating | 95% interval | likely rank | Plain | Mirror | Arms |
|---|---|---|---|---|---|---|---|---|---|---|
| 1 | astra | 93-15-36 | 70% | 63 to 77% | 1628 | 1582 to 1682 | 1 | 65% | 70% | 75% |
| 2 | fable | 73-16-55 | 56% | 49 to 64% | 1539 | 1493 to 1586 | 2 to 4 | 62% | 60% | 46% |
| 3 | sol | 71-17-56 | 55% | 47 to 63% | 1532 | 1482 to 1583 | 2 to 4 | 50% | 59% | 56% |
| 4 | opus | 68-16-60 | 53% | 45 to 60% | 1517 | 1467 to 1566 | 2 to 5 | 55% | 52% | 51% |
| 5 | luna | 64-6-74 | 47% | 38 to 54% | 1478 | 1425 to 1526 | 3 to 5 | 38% | 55% | 47% |
| 6 | deepseek | 45-11-88 | 35% | 28 to 43% | 1405 | 1352 to 1453 | 6 to 7 | 45% | 26% | 34% |
| 7 | sonnet | 45-9-90 | 34% | 27 to 42% | 1400 | 1348 to 1449 | 6 to 7 | 35% | 27% | 41% |

- **share**: wins plus half the draws, over 144 games.
- **rating**: Bradley-Terry strength on the Elo scale (400 points for a factor of ten in the
  odds), centred on 1500, with a draw counted as half a win each way. A 100-point gap means the
  stronger model is expected to take about 64% against the weaker.
- **intervals**: 2,000 resamples of the 504 games with replacement.
- **likely rank**: the narrowest range of ranks that holds in 90% of the resamples.
- A draw in which both armies are broken is re-ruled by the tie-break the packs carry now (the
  less broken army wins unless the two are within ten points). This rule was added after the
  first 60 games; it changes ten of them.

**Read it as three tiers.** Astra is first in every resample but 1%. Fable, Sol, Opus and Luna
form a middle group, inside which the order is not settled: neighbours swap in 15 to 42% of the
resamples. DeepSeek and Sonnet are below the middle group and indistinguishable from each other
(they swap in 45%). Between Luna and DeepSeek the order holds in 97% of the resamples.

The battles agree on the tiers but not on the order inside them. Fable is second on Plain and
Mirror and below even on Arms; Luna is sixth on Plain and fourth on Mirror; DeepSeek takes 45% on
open ground and 26% on Mirror's broken ground.

## Head to head

The row model's share against the column model, 24 games each (both sides, three battles,
four seeds).

| | astra | fable | sol | opus | luna | deepseek | sonnet |
|---|---|---|---|---|---|---|---|
| **astra** | · | 65% | 58% | 56% | 79% | 83% | 77% |
| **fable** | 35% | · | 38% | 50% | 62% | 67% | 85% |
| **sol** | 42% | 62% | · | 60% | 46% | 62% | 58% |
| **opus** | 44% | 50% | 40% | · | 46% | 75% | 62% |
| **luna** | 21% | 38% | 54% | 54% | · | 52% | 60% |
| **deepseek** | 17% | 33% | 38% | 25% | 48% | · | 50% |
| **sonnet** | 23% | 15% | 42% | 38% | 40% | 50% | · |

Astra beats every model. The middle group is not transitive: Fable beats Luna, Luna holds Sol
and Opus, Sol beats Fable. At 24 games a pair, a single cell has an interval of about ±20
points, so the grid shows matchups worth a closer look rather than settled results.

## Round 1 against round 2

| model | round 1 | round 2 |
|---|---|---|
| astra | 72% | 67% |
| fable | 56% | 57% |
| sol | 60% | 50% |
| opus | 55% | 51% |
| luna | 36% | 57% |
| deepseek | 37% | 33% |
| sonnet | 34% | 35% |

Five models are within five points of themselves. Luna gained 21 points and Sol lost 10, so we
replayed the pairings among the three GPT-6 models to find out why
(`uv run python scripts/checks.py`, games in `games/extra/codex-replays/`):

| set | games | astra | sol | luna |
|---|---|---|---|---|
| round 1, matrix | 36 | 71% | 54% | 25% |
| round 2, matrix | 36 | 67% | 33% | 50% |
| round 1's seeds, replayed with the current code | 36 | 60% | 54% | 35% |
| round 2's seeds, replayed with the current code | 36 | 69% | 52% | 29% |
| round 1's seeds, round 1's code | 36 | 73% | 40% | 38% |
| round 1's seeds, round 1's code and Codex CLI | 18 | 67% | 42% | 42% |

Replaying round 2's own seeds puts Luna back at 29%, so the seeds do not explain the jump,
and neither does the code or the CLI version. A 25-point swing on 36 games happens by
chance about once in thirty, and seven models were watched for one; with the replays pointing
the same way, the jump is best read as chance. The matrix pools both rounds.

## Noise floor

Plain was played twice more for the six models other than Fable with identical settings
(`games/extra/noise-a`, `noise-b`). The same pairing produced the same winner in 15 of 30
games. A model's share over its ten games moved by 7 points on average between the two runs,
and by 15 at most; Astra led both. A seed fixes the field and the armies, not the battle: the
engine's random draws are keyed to where bodies stand, so once two games' orders differ, their
draws differ too. A single game is close to a coin flip; the standings rest on many.

## Seats

| battle | first side | first side's share |
|---|---|---|
| Plain | red | 49% |
| Mirror | red | 49% |
| Arms | horse | 55% |

Plain and Mirror are fair to within noise. On Arms the horse army wins 55%. Every pair of
models plays both sides of every battle, so a seat advantage cancels in the standings.

## How battles end

428 of the 504 games (85%) were won by a break, 12 by possession of the village at the end
hour, 18 in the play-on and one at the last reading. 45 were draws: 22 with both armies broken
within ten points of each other, 23 with the village still contested when the play-on ran out. The median battle lasted 161 minutes from the
09:00 start; a quarter went past 14:40.

## The staff

450 games were read by Jev 1.14 as staff and umpire, 54 (in round 1) by GPT-6 Luna, which is
also a player. How far the two agree on the same requests is measured in the
[staff study](staff-study.md). After round 1, the staff learned to place a point given by
distance and compass direction from a named place ("400 m east of the village"), which
DeepSeek's orders use most, and the generals' brief changed with it: in round 1 it said that "a
point given only as so far in such a direction from a village cannot be found", in round 2 that
the staff can fix "a point set off from a named place by a measured distance and a point of the
compass" (each record carries the prompt it was played with). Orders naming such a point went
from 11% of DeepSeek's and none of the others' in round 1 to 11 to 74% of every model's in
round 2. DeepSeek's 72 round-1 games were replayed under the fixed staff
(`games/extra/deepseek-rerun`): its share went from 37% to 32%, inside its interval. Round 2 was
played with the fixed staff throughout; the matrix keeps the original round-1 games.

## How each model commands

`uv run python scripts/styles.py`, per game unless noted.

| model | briefs | silent | words | think s | orders | queried | attack | advance | hold | support | rally | withdraw | bold | reckless | standing | placed | battle length (min) | own army broken |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| deepseek | 32 | 2% | 284 | 15 | 328 | 11% | 6% | 14% | 44% | 7% | 6% | 2% | 20% | 15% | 5% | 9% | 148 | 52% |
| fable | 35 | 34% | 66 | 15 | 105 | 7% | 7% | 25% | 19% | 16% | 7% | 9% | 15% | 10% | 13% | 19% | 218 | 37% |
| astra | 32 | 31% | 36 | 46 | 77 | 5% | 7% | 34% | 17% | 10% | 12% | 10% | 14% | 1% | 5% | 3% | 179 | 18% |
| sonnet | 30 | 46% | 50 | 10 | 77 | 6% | 9% | 26% | 15% | 24% | 3% | 5% | 20% | 1% | 4% | 11% | 198 | 54% |
| luna | 23 | 28% | 27 | 37 | 66 | 5% | 20% | 16% | 15% | 13% | 10% | 10% | 32% | 2% | 1% | 0% | 133 | 42% |
| opus | 29 | 40% | 42 | 11 | 66 | 6% | 6% | 28% | 19% | 14% | 6% | 8% | 14% | 16% | 8% | 13% | 152 | 39% |
| sol | 28 | 39% | 22 | 44 | 52 | 6% | 6% | 28% | 13% | 17% | 8% | 11% | 17% | 5% | 0% | 1% | 144 | 40% |

- **briefs**: times the general was consulted. **silent**: the share of briefs answered with
  no order. **words**: median words in a reply that gives orders. **think s**: median seconds
  per reply, which includes the harness. **orders**: orders the staff read. **queried**: the
  share of orders the staff answered with a question.
- The task columns are the share of the staff's tasks of each kind; **bold** and
  **reckless** ("at all costs") are the share given in that manner. **standing** is the share of
  orders with a standing limit ("attacking nothing without a further order"), **placed** the
  share that place a body by another ("behind the First brigade").
- **battle length** and **own army broken** are medians at the verdict.

Astra ends its battles with the least of its army broken (18%): its bodies break as often as
anyone's, but it rallies them fastest. Opus gives the most tasks to be pressed at all costs
(16%), nearly all of them to hold the village; Luna the most bold ones (32%). DeepSeek writes
thirteen times as many words a reply as Sol and sends three times as many orders as Fable; 44%
of its tasks are "hold". Fable fences and places its brigades more than any other model. Luna
attacks two to three times as often as the others and fights the shortest battles. Sonnet is
silent at almost half its briefs and gives the most support orders. Each model in depth:
[generals.md](generals.md).
