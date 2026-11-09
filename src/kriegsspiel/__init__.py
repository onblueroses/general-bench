"""General Bench: a free Kriegsspiel in which language models command horse-and-musket armies.

The engine (docs/engine.md):

- `world`, `geometry`, `vision`: the ground, routes, line of sight and who sees whom;
- `types`, `units`, `scenario`: bodies, formations and a battle pack's files;
- `movement`, `combat`, `morale`: the physics of a minute;
- `command`, `drill`: orders by aide, reports, the commander's picture, and the per-minute
  drills that move the bodies;
- `sim`, `clock`: the minute loop, the log and the state hash, clock strings; `log`, `replay`:
  the run log and bit-identical replays;
- `staff`, `staff_text`, `jev`, `decisions_llm`: the staff that reads a general's prose into
  tasks, and the decision model behind it;
- `umpire`, `account`, `verdict`: the umpire's judgments and the mechanical ordinal verdict;
- `narrator`, `commander`, `players`, `bot`: the general's brief, the generals (language
  models through their harnesses, scripts, the doctrine bot);
- `build`, `play`, `report`, `run`: a game built from a pack, the play loop, the game report,
  the command line;
- `grid`, `results`, `cross`: batches of games, their results read from the logs, the
  cross-pack report;
- `designed`, `final_state`: the designed battles' shared builder, the final field of a
  replayed run for re-judging.

Numbers in the engine carry their provenance: "spec" marks a value taken from the engine's
design specification, "assumption" one chosen here; both are explained beside the constant.
"""
