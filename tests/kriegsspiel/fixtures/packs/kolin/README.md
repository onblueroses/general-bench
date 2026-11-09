# Kolín, 18 June 1757: test pack

A historical pack kept for the tests only: the staff, umpire, narrator and play-loop tests run
on it, and its recorded Jev fixtures (`tests/kriegsspiel/fixtures/jev/`) replay against it. It
is not one of the benchmark's battles. Its sources, order of battle and deployment are in
`docs/kolin-test-pack.md`; `script.json` is the historical afternoon (the King's and Daun's
orders at their times), played by `tests/kriegsspiel/kolin_afternoon.py`.

## Departures from the design

`meta.json` `tuning` lists them; `strength_documented` keeps the documented figures.

- Austrian strength x 0.77 (every body): 54512 -> 41949, toward CDB90's 44,000.
- Křečhoř garrison and right flank (A-NAD Nádasdy's foot, A-MOR his horse) start 1.75 km
  south, well back behind the village: the village and the oak wood become a race the
  Prussian vanguard can win by moving first.
- Austrian centre and right (A-WIE, A-RWC, A-STA, A-AND) start 1 km south, behind the crest of
  the Křečhoř heights: every objective was held at the start, so the attack had nothing to
  decide.
- Prussian vanguard (P-VAN: Hülsen, Zieten's hussars) starts 700 m south of the Kaiserstrasse,
  toward the heights: it brings the first wave within reach of Křečhoř.

The scripted afternoon's Jev fixtures predate this deployment, so
`test_kolin_afternoon.py` is skipped in replay mode until they are re-recorded
(JEV_MODE=record).
