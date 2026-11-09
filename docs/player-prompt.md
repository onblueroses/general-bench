# The player prompt

What a general is given, in what order, and why. The texts are built by `narrator.py` from the
pack and the code; every model under evaluation reads the same bytes, and the two sides of a
battle read the same text with the names swapped. Nothing in it is phrased for one model.

The design rule: the general gets the whole setup and the whole situation, so that he can act
competently, but never a method. He is told what the staff can read, how the field behaves and
what the rules decide; he is never told where to attack or how to use the ground.

## What the general reads

Every consultation sends a system prompt and a brief.

The **system prompt** is `commander.SYSTEM` followed by the persona. `SYSTEM` fixes the reply
format: orders only, each on its own line, each beginning with the name of the formation or
officer it is for, plain prose, no headings, lists, markdown, commentary or questions to the
umpire; or exactly "No orders.".

The **persona** (`Narrator.persona(side)`) heads the first brief and has five layers:

1. **Who and where.** "You are General Thursby, commanding the Red army near Teasel Village. It
   is 09:00 on a day in high summer; sunset is at about 20:05; your headquarters stands ...".
   The battle packs give a season and the sunset, never a date.
2. **The fixed layer**, `narrator.GAME`: "How this game works", the same text in every battle
   (below).
3. **The rules sheet**, [`rules-sheet.md`](rules-sheet.md), for every pack whose `meta.json`
   sets `"rules_sheet": true` (all three battles): the engine's numbers.
4. **The battle layer**: "Your situation, as your headquarters knows it at 09:00:" followed by
   the side's section of the pack's `players.md`.
5. **The order of battle** at the start: every formation with its commander, its strength by
   arm and where it stood.

After the persona comes the brief proper: the clock, dispatches, orders, own troops, the enemy as
known, the ground and the named places ([engine: the brief](engine.md#the-brief)). Later
consultations in the same conversation get update briefs.

The umpire reads `objectives.md` and the engine's account of the field, never `players.md`.

## The fixed layer

`narrator.GAME` tells a general of the period, in plain prose and without a single number:

- what the game is: one army against another, both under the same rules, and that the result is
  a win, a draw or a loss by the rule in his orders, the object being the win and a draw worth
  half a win (the ordinal packs replace the general version's two sentences about an umpire's
  judgment with this, `narrator.GAME_ORDINAL`);
- that he commands by writing: the staff read each line, decide which formation it is for and
  what it asks, and send it by aide; an order acts only when the rider arrives; reports come
  back the same way;
- what he knows of the field: only his brief; there is no map; a report shows where a brigade
  was when its commander wrote; brigade commanders report of their own accord on first contact,
  on reaching the objective, when a body breaks, when losses grow heavy; headquarters sees from
  where it stands and can be moved;
- when he is asked: every quarter of an hour of battle time, and at once on a report of first
  contact, of a body of his breaking, or a staff question; the battle stands still while he
  thinks, so there is no reward for haste and no penalty for care; silence or "No orders."
  leaves every order in force;
- how to write an order the staff can read: one formation and one task a line, named as in the
  order of battle; one sequel after "then"; objectives the staff can fix (a named place, an
  enemy body as the brief names it, a friendly formation, "our left flank", "our right flank",
  "our centre", "our rear", or a point set off from a named place by a measured distance and a
  compass point); the task words, formations, manners, reactions, start and stop conditions and
  prohibitions the staff understand;
- what the staff cannot do: split a formation, read several formations' tasks in one line, find
  an unnamed place or an unseen enemy, carry two sequels; an unreadable order holds the
  formation and comes back as a question; every line is an order;
- how the field behaves, in words: fatigue and recovery; shaken troops, routs, rallying and the
  recovery after a repulse; pursuit; columns, lines and squares; cavalry against foot; guns
  limbering, roundshot and canister, ammunition; woods, villages, marsh, heights, streams, fords
  and roads; trains; and that the light does not fail.

The vocabulary in this layer is drawn from what `staff.py` actually offers (its kinds, states,
reactions, manners, start conditions and prohibitions) and from `command.py`'s relative places,
so that a general who follows it writes orders the staff can read.

## The battle layer: `players.md`

One `## <side>: <commander>` section per side; the heading's first word names the side as in
`oob.json`. Any other `## ` section is refused by `scenario.parse_players`, so umpire text can
never reach a general through this file. Bodies are unwrapped on load, so a name wrapped over
two source lines is one string to the player and the staff. In the battle packs the file is
generated by `tools/build_pack.py` from a template, so that the two sides' sections differ only
where the design says they differ.

Each section has six parts:

| part | holds |
|---|---|
| Who you are | the army's strength and composition, its formations by name and commander, each formation's quality, where headquarters stands |
| How the army came here | the army's state this morning and its deployment |
| What headquarters knows of the enemy | his order of battle in outline: what he has, never where he stands or what he intends |
| The ground | the field as a staff would describe it, by the brief's place names: roads and their directions, villages, farms, streams, fords, heights, woods, the way back |
| Your orders | the mission and the verdict in full (the four points of [the verdict](battles/README.md#the-verdict)) |
| The conventions of the day | the period's rules of thumb in round figures, and the clock: start, end hour, play-on |

Writing rules for this layer:

- The voice of a staff memorandum of the period, in clear modern English, addressed to the
  general as "you". Prose paragraphs; no lists inside a section.
- Only what that headquarters could know at the start.
- Names exactly as in `features.json` and `oob.json`.
- Never a method or a plan: no axis of attack, no turning movement, no sequence of attacks, no
  recommended route for a reserve. The ground may be described; a use of it may not be
  suggested.
- Never the umpire's questions or criteria, and never anything the headquarters could not know:
  the enemy's deployment, his moves, his plan.

## Why the numbers are stated

A general of the period knew how far a musket carried, how fast a column marched and when a
battalion would break, from experience. A model has no experience of this engine. Rather than
make it guess, the battle packs give it the engine's own numbers: ranges, march rates, deployment
distances, when a body breaks, what rallies it, how often the general is consulted. The rules
sheet is the same bytes for every model and both sides, and `test_rules_sheet.py` holds every
number in it to the constant it cites, so the sheet cannot drift from the code. The fixed layer
stays free of numbers so that it reads as a general's instruction, not a table.

## Budgets

| text | budget | battle packs |
|---|---|---|
| fixed layer, `narrator.GAME` | at most 1,700 words | about 1,680 |
| rules sheet | at most 1,300 words (`narrator.RULES_SHEET_MAX_WORDS`) | 1,275 |
| one side of `players.md` | 400 to 900 words | 875 to 897 |
| the persona without the rules sheet (`narrator.PERSONA_MAX_WORDS`) | at most 3,200 words | about 2,800 |

The whole first brief stays inside the narrator's 6,000-word budget. `test_player_prompt.py`
checks every budget, that every pack's `players.md` parses, that the persona carries no umpire
text and the umpire's text no paragraph of `players.md` (with a positive control), that the
fixed layer holds no digit and no number word, and that an ordinal pack's persona says the rule
decides.
