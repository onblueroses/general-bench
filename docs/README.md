# Documentation

General Bench puts language models in command of horse-and-musket armies in a free Kriegsspiel.
A general writes prose orders; a staff model reads them into tasks and may ask what was meant;
aides carry them across the field; a continuous engine resolves movement, fire, melee and morale
minute by minute; and a mechanical verdict decides the battle.

| document | what it covers |
|---|---|
| [engine.md](engine.md) | the engine as built: terrain, bodies, movement, fire, melee and the umpire's factor, morale and rout, vision, command and the staff, the brief, the play loop, determinism, replay and the run log |
| [battles/README.md](battles/README.md) | why the battles are designed, what each rung changes, the verdict rule exactly as implemented, the clock, what to keep in mind when reading results |
| [battles/plain.md](battles/plain.md) | Plain: one crossroads on open ground, identical armies |
| [battles/mirror.md](battles/mirror.md) | Mirror: brooks, fords, a ridge and a wood a side, symmetric under rotation |
| [battles/arms.md](battles/arms.md) | Arms: Plain's ground, a horse army against a foot army of equal strength |
| [rules-sheet.md](rules-sheet.md) | the engine's numbers as every general reads them, each tied to the constant it cites |
| [player-prompt.md](player-prompt.md) | what a general is given, in what order, and why |
| [players.md](players.md) | how each model is run (`claude -p`, `codex exec`, an OpenAI-compatible API), the isolation measures and their evidence |
| [pack-format.md](pack-format.md) | the files of a battle pack and every key the loader reads |
| [staff-study.md](staff-study.md) | whether a general chat model (GPT-6 Luna) can do the staff's job: method and agreement with Jev |
| [staff-study-tables.md](staff-study-tables.md) | the full agreement report behind the staff study |
| [kolin-test-pack.md](kolin-test-pack.md) | the sources and numbers of the Kolín test pack |
| [results.md](results.md) | the standings, head to head, rounds, replays, noise floor, seats and styles of the published games |
| [generals.md](generals.md) | how each model commands, in depth: rallies, silence, the opening, repeats, with a game told for each |

Start with [battles/README.md](battles/README.md) for what is being measured and
[engine.md](engine.md) for how. The code is in `src/kriegsspiel/`, the battle packs in `data/`,
the game records in `games/`.
