# Test field: anonymisation mapping (test fixture)

A committed stand-in for the private `.local/battles/<slug>-mapping.md` files, so that
`tests/kriegsspiel/test_anonymised_packs.py` exercises the build and the leak checks without
them. The test field's German names are invented; here they play the real names.

| Real | Placeholder |
|---|---|
| General Blau | General Ostrey |
| General Roth | General Wendle |
| Neudorf | (generated) |
| Kapellenberg | Tarn Hill |

## Build key

```json
{
 "slug": "testfield-anon",
 "source": "testfield",
 "seed": 7,
 "battle": "Tarn Hill",
 "season": "late spring",
 "sides": {"blue": "blue", "red": "red"},
 "armies": {"blue": "Blue army", "red": "Red army"},
 "people": {
  "General Blau": "General Ostrey",
  "Oberst B1": "Colonel Ravick",
  "Major B2": "Major Selbury",
  "Rittmeister B": "Captain Dunmore",
  "Hauptmann B": "Captain Halvard",
  "General Roth": "General Wendle",
  "Oberst R1": "Colonel Pellow",
  "Major R2": "Major Corrin",
  "Rittmeister R": "Captain Brisley",
  "Hauptmann R": "Captain Tolver"
 },
 "names": {},
 "labels": {},
 "features": {"Kapellenberg": "Tarn Hill", "Hoher Ruecken": "Long Ridge"},
 "weather": "dry and clear",
 "objectives": {
  "blue": "Take the Long Ridge and Tarn Hill from the enemy and hold them at nightfall, with your army still fit to fight.",
  "red": "Hold the Long Ridge and Tarn Hill against the enemy until nightfall without losing the army.",
  "umpire": "Who holds the Long Ridge and Tarn Hill at the end, with how many formed bodies; losses of each side."
 },
 "script": [
  {"minute": 0, "side": "blue", "text": "Oberst B1, advance to Neudorf in line."},
  {"minute": 0, "side": "blue", "text": "Major B2, attack the Kapellenberg."},
  {"minute": 0, "side": "red", "text": "Oberst R1, hold the Hoher Ruecken in line."},
  {"minute": 10, "side": "red", "text": "Rittmeister R, charge the enemy horse near Neudorf."},
  {"minute": 5, "side": "blue", "text": "Rittmeister B, attack the enemy cuirassiers behind the Eichwald."},
  {"minute": 5, "side": "blue", "text": "Hauptmann B, bombard Hof Lindenau and then the Muehle."}
 ]
}
```
