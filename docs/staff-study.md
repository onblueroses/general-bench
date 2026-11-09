# Staff study: can a general chat model do the staff's job?

The staff that reads a general's prose into tasks, and the umpire that weighs each clash, are Jev
(`typesafe/jev-1.14`, TypeSafe's decision model) behind a paid decisions API. It is the one
external service a game depends on: if it is unavailable, the game stops. This study asks
whether a general chat model, GPT-6 Luna behind the Codex CLI, can answer exactly Jev's requests
well enough to stand in, first on recorded requests and then in a live game.

## What the staff does in a game

Measured over the 60 games of the first seed (five models, three battles):

| per game | median | mean | max |
|---|---|---|---|
| decisions requests | 376 | 413 | 894 |
| questions | 4,824 | 5,451 | 12,393 |
| cost | $0.068 | $0.075 | $0.179 |
| staff wall time, requests end to end | 53 min | 54 min | 105 min |

Request latency: median 2.9 s, p90 17 s. The questions: addressing (does this order instruct
formation i, per formation and per formation and clause) 42%, task details 37%, clause readings
18%, the check of a task against its words 2%, the umpire under 1%. Staff time is not battle
time: the battle waits for the staff as it waits for the general.

## The stand-in

`kriegsspiel.decisions_llm.LlmDecisionsClient` keeps the Jev client's surface: a state and named
questions in, Jev-shaped answers out, the same fixtures, logs and modes. It answers through the
Codex CLI from the players' clean `CODEX_HOME` in an empty directory ([players](players.md)). The
model is told what Jev is told (read the state, answer from it alone, never compute) and asked,
per question, for a compact answer: for a choice the option id and one probability, for a yes/no
question one probability, for a graded question the expected level and one probability. The
client rebuilds Jev's shape (probabilities over every option, confidence) from that. A request can
be cut into chunks of N questions that run in parallel (`LLM_JEV_CHUNK=N`; off by default, and
off in the games), keeping groups whole (a task's details, a clause's readings, the addressing
questions), and merged into one record.

It runs one `codex app-server` per game (JSON-RPC over stdio), each request a fresh ephemeral
thread on it with the preamble as the thread's base instructions. This is the form a game uses
and the form measured below: 5 to 6 s a request and about 190 output tokens. The alternative, one
`codex exec` process per request asking for the full probability tables, took about 35 s a
request (8 s of it process start-up, the rest some 3,400 output tokens) with the same agreement
(`LLM_JEV_PERSISTENT=0` selects it).

A game selects the stand-in with `JEV_MODEL=codex/gpt-6-luna`; `LLM_JEV_REASONING` (default
medium), `LLM_JEV_CHUNK` and `LLM_JEV_PARALLEL` tune it. The logical model name keys fixtures and
logs, so a game staffed by the stand-in never replays against Jev's fixtures or the reverse. Each
published game record names its staff model (`game.staff_model`), and some of the published games
were staffed by the stand-in.

## Method

`scripts/jev_vs_llm.py` replays the 177 recorded Jev fixtures in `tests/kriegsspiel/fixtures/jev/`
(2,875 questions, nearly all staff readings of orders from the Kolín test pack) through the
stand-in and scores agreement with Jev's answers:

- **agree**: for a choice, the same option; for a yes/no question, the same side of 0.5; for a
  graded question, the same rounded level;
- **staff agree**: whether the staff would do the same with the answer: the same option above the
  staff's 0.5 confidence line, or both below it.

Some questions only matter when another answer opens a gate: what is forbidden, when the clause
is a prohibition; a trigger's who and where, when the clause names a trigger; a sequel's kind and
objective, when a sequel follows. Those are scored only where the gate is open under Jev's
reading, since the staff never reads them otherwise.

## Agreement

GPT-6 Luna, medium reasoning, the persistent server and compact answers. All 177 requests
answered.

| type | questions | agree | staff agree |
|---|---|---|---|
| yes/no | 1,931 | 94% | 94% |
| choice | 874 | 69% | 63% |
| graded | 70 | 70% | 70% |

| family | questions | agree | staff agree |
|---|---|---|---|
| addressing (does this order instruct formation i) | 1,040 | 96% | 96% |
| clause attribution (formation i, clause k) | 360 | 93% | 93% |
| detail: kind of action | 67 | 88% | 85% |
| detail: desired state | 67 | 96% | 94% |
| detail: route | 67 | 90% | 88% |
| detail: on contact | 67 | 84% | 72% |
| detail: objective | 67 | 69% | 64% |
| detail: manner (graded) | 67 | 73% | 73% |
| detail: start now / when engaged / when reached / when seen / when a body routs | 67 each | 97 / 88 / 85 / 100 / 100% | the same |
| clause: is it a prohibition | 67 | 99% | 99% |
| check: task goes against its words | 56 | 80% | 80% |
| gated: sequel kind / objective | 28 | 79% / 64% | 54% / 46% |
| gated: trigger's who / where | 14 | 29% / 29% | 21% / 21% |
| gated: what is forbidden | 7 | 43% | 43% |

The full report, with every one of the 453 staff-level disagreements listed: [staff study
tables](staff-study-tables.md). The one-shot form at medium and at low reasoning gave the same
picture within noise (yes/no 94 to 95%, choice 67%, addressing 96 to 97%, 445 to 464 staff-level
disagreements), so reasoning effort is neither where the agreement nor where the time goes.

Ungated, the trigger and sequel families read 15% to 63%: when a clause has no trigger or a task no
sequel, Jev still names a formation and a place, and Luna answers "none", as the question allows.

### Reading the disagreements

A good share of the disagreements are Luna being the stricter reader. On "Cavalry: screen our
left flank" Jev addresses every cavalry brigade at 0.6 to 0.84 and Luna none (the staff's
arm-word rule picks one formation either way). On "Krosigk, bring your reserve ... behind
Hülsen's left" Jev addresses Hülsen's corps at 0.76, though it is a reference, not an order, and
Luna at 0.00 (the staff's reference rule strips it either way). The staff's text rules were built
around Jev's habits; Luna would need fewer of them.

The trigger clauses on which the two disagree about who or where, read against the words:

- **Equivalent in effect** (5): "hold until further orders", "until your head is well beyond
  Křečhoř", "Hülsen will follow once you are engaged", "until I order it", "until it is called
  upon". Jev names the addressed formation, Luna answers "self" or "none"; the staff resolves both
  to the same formation.
- **Luna closer to the words** (2): "until the infantry of the army comes up on your right" (Jev:
  the Křečhoř heights; Luna: our right flank); "once you are engaged" (Jev adds the oak wood at
  0.53, which the words do not name).
- **Jev more useful** (3): "keep Zieten's hussars on Hülsen's left as he attacks Křečhoř" in three
  variants. Both read the trigger as Hülsen engaged; Jev adds the place, Luna names none because
  the question lists "reaching, taking, holding or passing" and attacking is not among them. This
  is instruction following, not comprehension; a line in the question would close it.
- **Open** (3): conditional reactions ("ready to charge whatever comes against his flank",
  "charge any enemy cavalry that follows the hussars off the heights"), which Jev reads as a start
  condition and Luna as none; and "then wait for Tresckow", which Jev calls a trigger with no
  event.

Two differences are not about the words:

- **Confidence.** Jev spreads probability (0.49 on an objective it cannot place, 0.55 on
  "other"); Luna is close to certain on nearly everything, though the compact form returns 0.98,
  0.91 or 0.55 more often than the full one. The staff asks the general back when its largest
  probability is under 0.5, so with Luna it asks less often; and the umpire's melee factor, which
  is pulled toward 1.0 by low confidence, bites more fully. Jev's probabilities carry a signal
  Luna's mostly do not.
- **Enemy objectives.** Where the enemy body is in the vocabulary, Luna names it ("charge the enemy
  infantry 400 m north of the Kaiserstrasse": Jev "other" at 0.55, Luna the enemy body near the
  Křečhoř heights). Most of the objective family's 69% is this, and it reads as Luna's gain.

## Speed and cost

Jev answers a 15-question request in about 3 s; the stand-in in 5 to 6 s when it runs alone. On
one request, three variants, two runs each on the same server: full tables 32.0 and 29.8 s
(3,356 and 3,381 output tokens); compact 5.7 and 5.2 s (187 and 184); compact with the preamble as
base instructions 5.4 and 7.6 s (195 and 206, and 3,500 fewer input tokens); 12 to 14 of 15
answers agreeing in every run. Input is 24k to 31k tokens a request, most of it the Codex
harness's own prompt, served from cache once the prefix is warm. With twelve requests in flight
on one server beside a live game and the test suite, latency was median 16 s, p90 38 s. A game's
staff work comes to roughly 10M tokens, against the 65M a Codex general spends playing it, at no
marginal cost.

## Live game

Plain, Luna against Luna, seed 1, staffed by the stand-in. The opening pair of replies (65 and 41
s of thinking, 22 orders between them) went through the staff in 8.2 minutes of wall time: 75
requests, median 4.4 s, p90 14 s, four questions asked of the generals.

The game took 40 minutes of wall clock for 117 battle minutes: Blue won by break at 10:57 (Red 87%
broken, Blue 73%, 14 points apart, above the 10-point draw margin), Teasel Village held by Blue.
Over the game: 35 replies, 307 requests, 3,412 questions, none failed; latency median 4.3 s, p90
6.6 s, max 28.7 s; 25 minutes of staff time; 5 questions to the generals; 7.1M input tokens.

For comparison, the eight Jev-staffed Plain games of the first seed with Luna on one side: break
between 10:44 and 11:36, 259 to 425 requests, 0 to 6 questions, 29 to 65 minutes of staff time,
latency median 2.2 to 4.1 s. The stand-in game sits inside that band on every count. One trait
shows at the umpire: Jev names a narrative winner at 0.56 to 0.76 in those eight games, the
stand-in said "undecided" at 0.99. The ordinal verdict does not use it.

## Findings

- On the readings that decide a task (who is addressed, what kind of action, what formation,
  when to start), Luna agrees with Jev 94 to 96% of the time, and a hand reading of the
  disagreements splits them both ways.
- It is weaker on conditional readings (triggers, sequels, prohibitions) and gives almost no
  confidence signal, so the staff would ask the generals back less often.
- It is slower per request (about 4.3 s against 3 s in a game) and has no marginal cost. A full
  game ran on it inside the band of the Jev-staffed games.
- It works as a fallback staff behind `JEV_MODEL`. As the benchmark's only staff it would change
  what the generals are measured against: a different reader of their prose, asking fewer
  questions. That is why each game record names its staff and results can be split by it.
