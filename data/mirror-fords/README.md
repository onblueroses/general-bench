# Mirror (Plover Village): data pack

The second designed battle of the ladder (`docs/battles/README.md`, item 2): Plain's box,
armies, deployment, clock, verdict and brief on ground that matters (`docs/battles/README.md`,
"Mirror's brook, re-laid"). Two brooks rise on a dry saddle 500 m either
side of Plover Village and run to the north-west and south-east corners (Curlew Brook, Godwit
Brook), with no bridge; each has one ford 2 km from the village, with its mill (Curlew Ford,
Godwit Ford); each army has a bank road from its left-hand ford to the village, a low ridge on
its left (Heron Ridge, Bittern Ridge: 25 m, 1.5 km from the village, 600 m off the brook, inside
12-pounder roundshot of the village and of the near ford) and a wood on its right covering its way to
the right-hand ford (Siskin Wood, Linnet Wood). The whole field is exactly symmetric under the
180° rotation about the village. Red stands west, Blue east. Design:
`docs/battles/mirror.md`; every number and why: `design-notes.md`.

## Files

| file | content |
|---|---|
| `terrain.npz` | `elev` float32 (241, 321): 200 m, the two ridges up to 225 m; `cover` uint8: open, WATER (the two brooks, a band 50 m across on the slant), WOOD (the two woods), VILLAGE (r 200 m), ROAD (High road, the two bank roads, the two lanes); `cell_m` 25; `origin` (-12.5, -12.5) |
| `features.json` | 22 features: Plover Village (a point at the crossroads), Curlew Brook, Godwit Brook, two fords and two mills, two ridges (crest lines), two woods, the High road, Curlew lane, Godwit lane, Withy road, Osier road, four farms, West and East exit |
| `oob.json` | Plain's armies under new commanders: sides `red`, `blue`; per side an army root and 11 brigades, 22 bodies |
| `deployment.json` | byte-identical to Plain's |
| `mission.json` | Plain's ordinal verdict on Plover Village |
| `players.md` | the generals' battle layer: Plain's template, the ground rewritten, the enemy in a shorter outline, the orders paragraph (875 words a side) |
| `objectives.md` | the umpire's text: the same mission and verdict per side, `## Umpire` (narrative only), `## Outcome` (none) |
| `script.json` | Plain's plan with the village renamed (needs Jev) |
| `meta.json` | Plain's, renamed |
| `tools/build_pack.py` | builds every file above from its constants, the two templates beside it and the shared `kriegsspiel.designed` |

## Rebuild and play

```
uv run python -I data/mirror-fords/tools/build_pack.py   # deterministic, byte-identical
uv run pytest tests/kriegsspiel/test_pack_mirror.py tests/kriegsspiel/test_symmetry_mirror.py
uv run python -m kriegsspiel.run --scenario data/mirror-fords --mode stub \
    --players red=bot:strong,blue=bot:strong
uv run python scripts/symmetry_diff.py 1 rotate data/mirror-fords
```

Self-play (both armies break in the same minute, a draw, on every seed) and what the bot does
and does not do with the ground: `design-notes.md`.
