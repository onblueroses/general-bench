# Plain (Teasel Village): data pack

The first designed battle of the ladder (`docs/battles/README.md`, item 1): flat open ground, 8 x 6 km, one crossroads village in the middle, two identical armies of
eleven formations (12,440 men, 44 guns) drawn up 3.5 km from it at 09:00, symmetric under the
180° rotation about the crossroads. Red stands west, Blue east. The ordinal verdict decides:
a break, else possession of Teasel Village at 16:00, else play on to 18:00, else a draw.
Design: `docs/battles/plain.md`; every number and why: `design-notes.md`.

## Files

| file | content |
|---|---|
| `terrain.npz` | `elev` float32 (241, 321), 200 m everywhere; `cover` uint8: open, VILLAGE disc r 200 m at the crossroads, the two roads one cell wide; `cell_m` 25; `origin` (-12.5, -12.5) |
| `features.json` | 11 features: Teasel Village (a point at the crossroads), High road, Drove road, four farms, four exits |
| `oob.json` | sides `red`, `blue`; per side an army root and 11 brigades, 22 bodies |
| `deployment.json` | every body on the map at 09:00 in two lines, the wings, the reserve; HQs behind the centre |
| `mission.json` | the ordinal verdict (`kriegsspiel.verdict.OrdinalJudge`) |
| `players.md` | the generals' battle layer: the army with its qualities, the deployment, the enemy in outline, the ground, the mission and the verdict, the clock |
| `objectives.md` | the umpire's text: the same mission and verdict per side, `## Umpire` (narrative only), `## Outcome` (none) |
| `script.json` | one symmetric plan for `script` players (needs Jev) |
| `meta.json` | clock 09:00 to 16:00, high summer, sunset 20:07, roles, strengths |
| `tools/build_pack.py` | builds every file above from its constants, the two templates beside it and `kriegsspiel.designed` (box, armies, deployment, clock, verdict and text assembly, shared with Mirror) |

## Rebuild and play

```
uv run python -I data/plain-crossroads/tools/build_pack.py   # deterministic, byte-identical
uv run pytest tests/kriegsspiel/test_pack_plain.py
uv run python -m kriegsspiel.run --scenario data/plain-crossroads --mode stub \
    --players red=bot:strong,blue=bot:strong
```

The ordinal judge ends a game on a break or at the end of the play-on. A `script` game needs
live Jev (`--mode record`). Self-play results and the two findings they gave (the side the
engine processed first won; the bot always collides at the crossroads): `design-notes.md`.
