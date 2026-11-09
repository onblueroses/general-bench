# Battle pack format

A battle is a directory, a pack. `scenario.load(dir)` reads it into a world, the formations and
bodies, the objectives and the meta:

```python
world, formations, units, objectives, meta = scenario.load("data/plain-crossroads")
```

and `python -m kriegsspiel.run --scenario <dir>` plays it. The three battles are under `data/`;
the test packs are under `tests/kriegsspiel/fixtures/packs/`.

| file | required | read by |
|---|---|---|
| `terrain.npz` | yes | `world.World.load` |
| `features.json` | yes | `world.World.load` |
| `oob.json` | yes | `units.load_forces` |
| `deployment.json` | yes | `units.load_forces`, `scenario.load` |
| `mission.json` | no; the battle packs carry the verdict here | `verdict.py` |
| `players.md` | no; each side's battle layer ([player prompt](player-prompt.md)) | `scenario.parse_players` |
| `objectives.md` | no; the umpire's text, and the general's when there is no `players.md` | `scenario.parse_objectives` |
| `meta.json` | no; defaults below | `scenario.load` |
| `script.json` | no; needed for `script` players | `scenario.load_script` |
| `tools/` | no | build scripts, never loaded |

Coordinates are metres, `x` east, `y` north, origin the south-west corner of the raster. Clock
strings are `"HH:MM"` on the pack's own clock; `meta.start` is sim minute 0. Wherever a time is
asked for, an integer is read as minutes after the start instead.

## terrain.npz

| array | type | content |
|---|---|---|
| `elev` | float32 (ny, nx) | elevation in metres |
| `cover` | uint8 (ny, nx) | `types.Cover`: 0 open, 1 rough, 2 wood, 3 village, 4 orchard, 5 marsh, 6 water, 7 road |
| `cell_m` | scalar | cell size in metres |
| `origin` | [x0, y0] | the south-west corner of cell (0, 0) |

Row 0 is the south edge, column 0 the west edge. Roads are rasterised as road cover. Water is
impassable except within a bridge's radius or at a ford the arm may use.

## features.json

A list of objects:

```json
{"name": "Curlew Ford", "kind": "ford",
 "geometry": {"type": "point", "coords": [[2400.0, 4200.0]]},
 "aliases": ["the north ford"], "radius_m": 40.0,
 "passable": ["infantry", "cavalry", "artillery", "train"],
 "speed": {"infantry": 0.5, "cavalry": 0.5, "artillery": 0.25, "train": 0.25}}
```

Geometry is a point, a polyline or a polygon. Names and aliases are unique within a world,
case-insensitively; the staff also folds diacritics and tolerates one wrong letter, so keep
names at least three edits apart. Kinds: `village`, `wood`, `height`, `ridge`, `stream`, `pond`,
`road`, `bridge`, `farm`, `mill`, `church`, `ford`, `entry`, `exit`. Any other key is kept in
`Feature.props`; the engine reads these:

| kind | key | default | meaning |
|---|---|---|---|
| `bridge` | `radius_m` | 40 | water within this of each coordinate is passable for every arm at full speed |
| `ford` | `passable` | `["infantry", "cavalry"]` | arms that may cross: `infantry`, `cavalry`, `artillery`, `train`; aides and generals cross where cavalry can |
| `ford` | `speed` | 0.5 | factor on cross-country speed on the ford's water cells: one number for every arm, or a map per arm (an arm left out: 0.5) |
| `ford` | `radius_m` | 40 | water within this of the point or polyline is the ford |
| `entry` | | | where arriving bodies appear: a point, or a polyline whose middle vertex is used; on or just inside the map edge, on a road |
| `exit` | `radius_m` | 100 | a point or segment on the map edge; see [exits](#exits) |

Routing puts a node on every bridge and ford point, so the coarse search finds every crossing. A
ford an arm may not use is water to that arm.

The objective of an ordinal verdict should be a point feature: possession is measured from the
feature's geometry, so a point makes the test exactly "within 250 m of the crossroads".

## oob.json

```json
{"sides": ["red", "blue"],
 "formations": [{"id": "R", "name": "Red army", "side": "red", "commander": "General Thursby",
                 "parent": null, "level": "army",
                 "aliases": ["the army", "the Red army", "Thursby's army"]}, ...],
 "units": [{"id": "R-L1-1", "name": "Red Foot 01", "side": "red", "parent": "R-L1",
            "kind": "line", "men": 700, "quality": 3, "battalion_guns": 2}, ...]}
```

- `sides` is the order in which the sides are named and submitted.
- Formations: `id`, `name`, `side`, `commander`, `parent` (null for the one army root per side),
  `level` (`army`, `wing`, `column`, `brigade`), `aliases`. Give every formation the aliases a
  general will use for it.
- Units: `id`, `name`, `side`, `parent` (a formation id), `kind` (`types.UnitKind`), `men`,
  `quality` (1 to 5); for artillery `guns`, `crew` and `calibre_lb` (men default to the crew);
  for infantry `battalion_guns`; optionally `howitzers` and `mortars` (out of `guns`) and a free
  `source` note. The arm follows from the kind unless `arm` is given.

**Trains.** Unit kind `train` (arm `train`) is a wagon train: `men` are drivers and escort,
`guns` (optional) are pieces carried as cargo and lost with it. A train never fires and forms
nothing; it moves only on roads (50 m a minute) and open ground (25), and over bridges and fords
that pass `train`. A formed enemy body within 75 m takes it without a fight, and it bolts when
enemy cavalry comes within 300 m with no formed friend within 300 m. None of the three battles
has a train.

## deployment.json

```json
{"start": "09:00",
 "units": {"R-L1-1": {"x": 500.0, "y": 3435.0, "facing_deg": 90.0, "state": "line"}, ...},
 "hq": {"R": [175.0, 3000.0]}}
```

A unit entry holds `x`, `y`, `facing_deg` (compass, 0 north, 90 east), `state`
(`types.UnitState`; default column, guns limbered) and optionally `fatigue`, `morale`, `ammo`,
`disorder`. The army root of each side should carry an `hq`; a formation without one rides with
its bodies' centroid. `scenario.load` refuses a pack in which a body starts off the map or on
ground its arm cannot stand on, naming every such body.

**Arrivals.** A unit entry with `arrives_at` (clock or minute) and `entry` (an entry feature's
name) is off the map until then.

- At that minute, or later while the entry is blocked, it appears at the entry's point in its
  `state`, facing its line of march. Its `x`, `y` and `facing_deg` are ignored.
- One body per entry per minute, and only when no body, friend or foe, stands within 100 m of
  the entry point: an enemy on the entry cuts the road. Bodies wait in order of `arrives_at`,
  then of `units`.
- A body whose formation has received an order takes that task on arrival. Otherwise it marches
  to `assemble` (a feature name or `[x, y]`), by default 300 m from the entry toward the map
  centre, and holds there.
- An order to a formation none of whose bodies has arrived is carried to the entry of its first
  arriving body. Reports are written only by bodies on the map.

## mission.json

The verdict. The battle packs use the ordinal verdict:

```json
{"verdict": "ordinal", "objective": "Teasel Village", "break_share": 0.4,
 "break_persist_min": 30, "play_on_min": 120, "break_tie_margin": 0.1}
```

`objective` must name a feature; `break_share` lies in (0, 1); `play_on_min` is a multiple of 15.
Missing parameters take the values shown. The rule: [battles](battles/README.md#the-verdict). In
a pack with an ordinal mission the judge, not the umpire, decides when the battle is over.

## players.md and objectives.md

`players.md` holds one `## <side>: <commander>` section per side, written for the general
([player prompt](player-prompt.md)); the heading's first word names the side. Any other `## `
section is refused. The umpire never reads it.

`objectives.md` holds `## <side>: <commander>` sections (that side's objective in its commander's
words), an optional `## Outcome` (shown to nobody) and an optional `## Umpire` (what the umpire
weighs, never shown to a general). When the pack has a `players.md`, the side sections go to the
umpire only; otherwise each general gets his side's section as his battle layer.

## meta.json

| key | default | meaning |
|---|---|---|
| `battle` | the directory name | the name the persona uses ("near Teasel Village") |
| `date` | none | ISO date, stated in the persona; the battle packs give none |
| `season`, `daylight_date` | none | a season ("high summer"), stated with the sunset in place of a date; the day and month used for daylight |
| `start` | the deployment's `start`, else 13:00 | the clock at minute 0 |
| `end` | 19:30 | the end hour: the verdict's possession reading, or where play stops |
| `sunrise`, `sunset`, `civil_dusk`, `time_basis` | none | the light, for the persona and the record |
| `weather` | "" | for the record |
| `sides` | {} | per side: `commander`, `army` (root formation id), `role` (`attacker` frames the umpire's attacker; default the first side; other words are free text) |
| `rules_sheet` | false | true gives both generals the [rules sheet](rules-sheet.md) |
| `designed` | false | marks a designed battle |
| `strength_documented`, `bodies` | {} | per-side totals, checked by the pack's tests |
| `initial_reports` | none | `{side: text}`: what that headquarters knows at the start beyond its own sight, delivered as a report in hand at minute 0 |
| `deadline` | none | a mission deadline the umpire's account states |
| `battle_over_after`, `battle_over_every` | 120, 30 | for a pack without an ordinal mission: when the umpire is first asked whether the battle is over, and how often after |
| `par`, `sources`, `doc` | | for the record |

## script.json

The scripted plan of either side, played by `script` players and by script-against-script
baselines:

```json
{"note": "free text", "orders": [
  {"at": "09:00", "side": "red", "text": "Fenwick, advance by the high road to Teasel Village, then hold it."},
  {"minute": 180, "side": "red", "text": "Calloway, advance to Teasel Village and support the second brigade."}]}
```

`at` is a clock, `minute` minutes after the start; a bare list of orders is accepted too. A side's
orders go out in the listed order. Script orders are prose and go through the staff like any
general's, so a script game needs a live (or recorded) staff.

## Exits

A body leaves the map at an exit when its centre comes within the exit's `radius_m` and its task
names that exit as objective or waypoint. It keeps its men and is counted off the map by that
exit, with the minute. In a pack with at least one exit, a routed body within 50 m of any map
edge also leaves the map: it has fled, and counts as broken. A captured train stays in the
account as captured; its men and guns are lost.

## Building a pack

The three battles are generated: each pack's `tools/build_pack.py` writes every file from its
constants, templates beside it and `src/kriegsspiel/designed.py`, deterministically, so a rebuild
gives identical bytes:

```sh
uv run python -I data/plain-crossroads/tools/build_pack.py
uv run pytest tests/kriegsspiel/test_pack_plain.py
```
