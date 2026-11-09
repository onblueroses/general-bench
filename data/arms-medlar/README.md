# Arms (Medlar Village): data pack

The third designed battle of the ladder (`docs/battles/README.md`, item 3, "Arms' armies"):
Plain's ground, clock, verdict and mission words under new names, with two
armies of equal strength by the period's rate and different makeup. The horse army (White,
side `horse`) stands west: 5 infantry brigades, 5 cavalry brigades, two 6-pounder horse
batteries; 11,240 men, 36 guns. The foot army (Green, side `foot`) stands east: 8 infantry
brigades, 2 cavalry brigades, three 12-pounder batteries; 13,160 men, 56 guns. Points (a
horseman two foot, a gun thirty-five men): 16,260 against 16,360. Both first lines stand 3.5 km
from Medlar Village at 09:00. Design: `docs/battles/arms.md`; every number and why:
`design-notes.md`.

## Files

| file | content |
|---|---|
| `terrain.npz` | Plain's raster, built by Plain's `terrain()`: 200 m everywhere; open, the VILLAGE disc r 200 m, two roads one cell wide; 321 x 241 cells of 25 m from (-12.5, -12.5) |
| `features.json` | Plain's 11 features renamed: Medlar Village (a point at the crossroads), Post road, Salt road, Quince, Damson, Bullace, Pippin Farm, four exits |
| `oob.json` | sides `horse`, `foot`; per side an army root and 11 formations; 22 and 23 bodies |
| `deployment.json` | every body on the map at 09:00: the horse army with a hussar and a dragoon brigade on each wing and its guns and cuirassiers behind the centre; the foot army in two lines of four brigades, a horse brigade on each wing, its guns behind the centre |
| `mission.json` | Plain's ordinal verdict on Medlar Village |
| `players.md` | the generals' battle layer: Plain's ground, orders, verdict and clock word for word; each army's own order of battle with qualities, its deployment and the enemy's order of battle in outline (793 and 780 words) |
| `objectives.md` | the umpire's text: the same mission and verdict per side, `## Umpire` (narrative only), `## Outcome` (none) |
| `script.json` | Plain's plan fitted to each army (needs Jev) |
| `meta.json` | Plain's clock and light, `rules_sheet: true`, roles "meeting engagement", strengths |
| `tools/build_pack.py` | builds every file above from its constants, the templates beside it (`players_template.md`, `army_horse.md`, `army_foot.md`, `objectives_template.md`), Plain's builder and the shared `kriegsspiel.designed` |

## Rebuild and play

```
uv run python -I data/arms-medlar/tools/build_pack.py   # deterministic, byte-identical
uv run pytest tests/kriegsspiel/test_pack_arms.py
uv run python -m kriegsspiel.run --scenario data/arms-medlar --mode stub \
    --players horse=bot:strong,foot=bot:strong
```

The doctrine bot is not a calibrator for this rung: the horse army wins every seed by break
before 11:00 (design-notes.md). Arms is calibrated by a model pilot, both ways (the ladder,
"Calibration"); the armies are untuned.
