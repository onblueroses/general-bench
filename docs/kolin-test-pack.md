# Kolín test pack

Kolín (18 June 1757) is a historical battle pack kept for the tests only, under
`tests/kriegsspiel/fixtures/packs/kolin/`. It is not one of the benchmark's battles. The staff,
umpire, narrator and play-loop tests run on it, and the recorded decisions fixtures in
`tests/kriegsspiel/fixtures/jev/` are readings of Kolín orders, so their feature and formation
names are this pack's. This page says where the pack's numbers come from, so that a failing test
can be read against them.

The pack is real ground from a public elevation model and OpenStreetMap filtered against the
1757 landscape, and both armies at battalion, regiment and battery level at 13:00.
`scenario.load` reads it like any pack; `tests/kriegsspiel/test_scenario.py` checks that it
loads, that the bodies sum to the strengths in `meta.json`, that every start position is
passable, that every feature name is unique and that the ridge stands above the road.

## Sources

| tag | source |
|---|---|
| NAF | George Nafziger, order-of-battle sheets [757FAS, Prussian army](https://www.generalstaff.org/NAF/Pt_I_1600-1783/757fas.pdf) and [757FAR, Imperial army](https://www.generalstaff.org/NAF/Pt_I_1600-1783/757far.pdf), after Decker and the Prussian General Staff |
| KRO | kronoskaf.com, Project Seven Years War, [Battle of Kolin](https://www.kronoskaf.com/syw/index.php?title=1757-06-18_-_Battle_of_Kolin) (read through the Wayback Machine's 2024 copy); its order of battle follows the Grosser Generalstab, *Die Kriege Friedrichs des Grossen* III/3, Anlage 3-4 |
| CDB | CDB90 battle `isqno` 67, [jrnold/CDB90](https://github.com/jrnold/CDB90) |
| DEM | [Copernicus GLO-30](https://copernicus-dem-30m.s3.amazonaws.com/) surface model, tiles `N49_00_E015_00` and `N50_00_E015_00`, public bucket |
| OSM | OpenStreetMap through the [Overpass API](https://overpass-api.de/api/interpreter) (ODbL) |
| WIK | [Battle of Kolín](https://en.wikipedia.org/wiki/Battle_of_Kol%C3%ADn), [Tauentzien](https://en.wikipedia.org/wiki/Bogislav_Friedrich_Emanuel_von_Tauentzien) (last resort) |
| EST | our estimate; the rule is stated where it is used |

## Files

| file | content |
|---|---|
| `terrain.npz` | `elev` float32 (328, 576), `cover` uint8 (328, 576), `cell_m` 25, `origin` [0, 0], `origin_utm33n` [501000, 5538100] |
| `features.json` | 49 named features, period German and Czech spellings as aliases |
| `oob.json` | 2 sides (`prussia`, `austria`), 60 formations, 154 bodies (59 Prussian, 95 Austrian) |
| `deployment.json` | position, facing, state and fatigue of every body at 13:00; army headquarters |
| `objectives.md` | each side's objective in its commander's terms; the historical outcome |
| `players.md` | each side's battle layer |
| `script.json` | the historical afternoon: the King's and Daun's orders at their times |
| `meta.json` | date, start 13:00, sunset 20:11, weather, documented strengths, the CDB90 par, `tuning` |
| `tools/` | `fetch_sources.sh` (elevation and OSM download), `build_terrain.py`, `build_scenario.py`, `hand_features.json` (hand-placed 1757 features), `osm_extract.json` (the OSM geometry kept, in local metres) |

Rebuild from scratch (network, about a minute):

```sh
K=tests/kriegsspiel/fixtures/packs/kolin
$K/tools/fetch_sources.sh ~/.cache/kolin-src
uv run --with tifffile --with imagecodecs python -I $K/tools/build_terrain.py ~/.cache/kolin-src
uv run python -I $K/tools/build_scenario.py
```

`tifffile` and `imagecodecs` are needed only to decode the elevation tiles; the engine reads the
`.npz` with numpy. `build_scenario.py` runs offline from the committed `osm_extract.json` and
`terrain.npz`.

## Departures from history

`meta.json` `tuning` lists the changes made so that the afternoon is a contest; `strength_documented`
keeps the sourced figures.

- Austrian strength x 0.77 on every body: 54,512 to 41,949, toward CDB90's 44,000.
- Nádasdy's foot and horse (the Křečhoř garrison and the right flank) start 1.75 km south, well
  behind the village, so that the village and the oak wood are a race the Prussian vanguard can
  win by moving first.
- The Austrian centre and right start 1 km south, behind the crest of the Křečhoř heights.
- The Prussian vanguard (Hülsen, Zieten's hussars) starts 700 m south of the Kaiserstrasse,
  toward the heights.

## Frame and terrain

UTM zone 33N (EPSG:32633); local `x = easting - 501000`, `y = northing - 5538100`. The grid is
576 x 328 cells of 25 m: 14.4 km east to west by 8.2 km north to south, 49.995 to 50.069 N,
15.014 to 15.215 E. Plaňany lies at the north-west, Kolín's market square at the east, the
Austrian heights fill the southern half.

**Elevation** is Copernicus GLO-30 (about 30 m) sampled at every cell centre. It is a surface
model, so under the OSM woods the surface was replaced by inpainting from the surrounding open
ground; buildings were not removed. Range 161 m (Elbe flats) to 345 m. The Kaiserstrasse runs at
235 to 260 m along the front; the heights 2 km south reach 333 m at Křečhoř hill and 327 m at a
western summit, with a saddle of 305 to 310 m between them; the slope from road to crest is 4 to
7% (KRO quotes 6%).

**Cover** is OSM filtered against 1757 plus hand-placed features, rasterised in this order: rough
ground in a 30 m band along every stream; marsh from OSM wetlands and a 75 m band along the Peklo
brook below Radovesnice; wood only for the oak wood (all modern woods are left out, EST: KRO
describes open fields and names the oak wood as the one wood that mattered); village discs of
100 to 250 m radius about each historical village (Kolín 380 m); water from ponds, oxbows and the
Elbe (reservoirs, canals and gravel pits excluded); road for the Kaiserstrasse and the minor roads
away from Kolín as stand-ins for the old village lanes.

## Features

Villages are 16-sided polygons of the cover discs, at OSM place nodes. Notes on the uncertain
ones:

- **Oak wood** (EST): an ellipse of 650 by 300 m centred at (8,700, 2,400), from two KRO
  distances ("one km behind Krzeczhorz", Radovesnice "one km farther to the south"); treat it as
  plus or minus 300 m.
- **Křečhoř heights**: the largest area above 295 m in the battle window. **Křečhoř crest**: the
  highest cell in each 250 m strip from x 4,500 to 9,750, smoothed. **Křečhoř hill**: the OSM peak.
- **Przerovsky height** (EST): KRO calls it unidentified; taken as the western summit across the
  saddle from Křečhoř hill.
- **Friedrichsberg**: the OSM peak Bedřichov, 2.2 km from the inn where KRO says 1 km.
- **Zlaté Slunce**, the inn where Frederick found Daun's position, has kind `farm`.

### Feature list

| name | kind | geometry (local m) | aliases |
|---|---|---|---|
| Plaňany | village | polygon, 16 pts, centre 1126, 6057 | Planian, Planjan, Planany |
| Žabonosy | village | polygon, 16 pts, centre 941, 4478 | Zabonos, Zabanos, Zabonosy |
| Hradenín | village | polygon, 16 pts, centre 2037, 3900 | Hradenin |
| Poboří | village | polygon, 16 pts, centre 2524, 3223 | Pobor, Pobori |
| Blinka | village | polygon, 16 pts, centre 3340, 4824 | Blinka village |
| Nové Město | village | polygon, 16 pts, centre 4391, 5548 | Novomiesto, Nove Mesto |
| Břežany | village | polygon, 16 pts, centre 4643, 4414 | Brzezan, Brezany |
| Chocenice | village | polygon, 16 pts, centre 6005, 3804 | Chotzemitz, Chozenitz, Chotzenitz, Cotzemitz |
| Bříství | village | polygon, 16 pts, centre 7172, 3828 | Brzistwi, Bristvi |
| Zlaté Slunce | farm | polygon, 16 pts, centre 6641, 4961 | Slatislunz, Zur goldenen Sonne, Goldene Sonne, the Golden Sun inn, Zlate Slunce |
| Křečhoř | village | polygon, 16 pts, centre 8083, 3374 | Krzeczhorz, Krzeczor, Kretschor, Krechor |
| Kutlíře | village | polygon, 16 pts, centre 9156, 3742 | Kutlirz, Kutlire |
| Nová Ves | village | polygon, 16 pts, centre 9338, 6333 | Neudorf, Nova Ves |
| Radovesnice | village | polygon, 16 pts, centre 9812, 1698 | Radowesnitz |
| Libodřice | village | polygon, 16 pts, centre 5320, 1035 | Libodritz, Libodrice |
| Krychnov | village | polygon, 16 pts, centre 3135, 1211 | Krichnow |
| Svojšice | village | polygon, 16 pts, centre 1988, 832 | Swojschitz, Svojsice |
| Bošice | village | polygon, 16 pts, centre 1328, 2266 | Boschitz, Bosice |
| Lošany | village | polygon, 16 pts, centre 8030, 271 | Gross Loschan, Losany |
| Velim | village | polygon, 16 pts, centre 6666, 7174 | Welim |
| Zibohlavy | village | polygon, 16 pts, centre 10359, 721 | Zibohlaw |
| Kolín | village | polygon, 16 pts, centre 13425, 3674 | Kolin, Collin, Kolin town |
| Oak wood | wood | polygon, 16 pts, centre 8700, 2400 | Eichbusch, Eichwald, the oak-wood, Dubina, Dubový háj |
| Křečhoř heights | height | polygon, 18 pts, centre 6851, 2719 | Krzeczhorzer Höhen, Krechor heights, the heights, Kamhajek-Berg, Kamhajek Berg, the Austrian heights |
| Křečhoř crest | ridge | polyline, 22 pts, centre 7125, 2741 | the crest, the ridge, Krechor crest, crest of the heights |
| Křečhoř hill | height | point 6770, 2776 | Krzeczhorzer Berg, Krzeczhorz hill, Krechor hill, Height of Krzeczhorz |
| Przerovsky height | height | point 5250, 2850 | Przerovsky, Przerovsky Hill, Height of Przerovsky, Přerovský vrch |
| Friedrichsberg | height | point 8767, 5560 | Bedřichov, Bedrichov, Frederick's hill, the King's hill |
| Kaiserstrasse | road | polyline, 66 pts, centre 6662, 4926 | the Kaiserstrasse, the high road, the highway, the road, the road to Kolín, the road to Kolin, Císařská silnice, Prague road |
| Peklo brook | stream | polyline, 156 pts, centre 10899, 2199 | Pekelský potok, Peklo, Peklo-Bach, Peklo stream |
| Blinka brook | stream | polyline, 232 pts, centre 3070, 3701 | Blinka stream, Blinka-Bach |
| Nouzov brook | stream | polyline, 88 pts, centre 8216, 7363 | Nouzovský potok |
| Polepka brook | stream | polyline, 443 pts, centre 12076, -576 | Polepka, Polepka stream |
| Hluboký brook | stream | polyline, 84 pts, centre 13233, 6671 | Hluboký potok |
| Miletín brook | stream | polyline, 310 pts, centre 1300, 2088 | Miletínský potok |
| Elbe | stream | polyline, 142 pts, centre 14346, 4922 | Labe, the Elbe, Elbe river |
| Hořejší rybník | pond | polygon, 15 pts, centre 9388, 2260 | Horejsi rybnik |
| Svojšický rybník | pond | polygon, 70 pts, centre 2012, 581 | Svojsicky rybnik |
| Nouzov pond | pond | polygon, 17 pts, centre 7349, 6895 |  |
| Hořešák | pond | polygon, 18 pts, centre 5320, 704 | Horesak |
| Nouzáček | pond | polygon, 17 pts, centre 7305, 6995 | Nouzacek |
| Obecňák | pond | polygon, 13 pts, centre 12184, 227 | Obecnak |
| Peklo pond | pond | polygon, 64 pts, centre 11405, 3375 | Peklo rybník |
| Karasák | pond | polygon, 24 pts, centre 10841, 7306 | Karasak |
| Hradišťko | pond | polygon, 99 pts, centre 12894, 6585 | Hradistko pond |
| Rozkoš | pond | polygon, 51 pts, centre 933, 4924 | Rozkos |
| Kolín church | church | point 13456, 3508 | St. Bartholomew, Kostel svatého Bartoloměje, Kolin church |
| Plaňany church | church | point 1344, 6229 | Planian church, Planjan church tower, Planany church |
| Křečhoř church | church | point 8083, 3374 | Krzeczhorz church, Krechor church |

## Order of battle

Structure (formations, commanders, battalions and squadrons) follows KRO; NAF supplies the
Austrian regimental strengths. A body is one infantry battalion, one cavalry regiment (split in
two above about 800 sabres, merged with a brigade neighbour below 200) or one battery of heavy
guns. Battalion guns are `battalion_guns` on their battalion.

| | Prussia | Austria |
|---|---:|---:|
| infantry | 32 battalions, 17,500 | 54 battalions and the picked infantry, 35,160 |
| cavalry | 116 squadrons in 24 bodies, 14,080 | 158 squadrons and picked horse in 34 bodies, 18,632 |
| heavy guns | 28 in 3 batteries, 420 crew | 60 in 6 batteries, 720 crew |
| documented total | 32,000 | 54,512 |
| in the pack (after tuning) | 32,000 | 41,949 |
| CDB90 par | 32,000 | 44,000 |

- **Prussia.** No source in reach gives Prussian unit strengths, so CDB90's 32,000 is allocated
  by rule (EST): cuirassier and dragoon squadrons 130, hussar squadrons 110 (14,080, matching
  CDB90's cavalry figure); 15 crew a heavy gun; the remaining 17,500 over 7 grenadier battalions
  of 500 and 25 battalions of 560. Formation tree: the Vanguard under Zieten (Katte's hussars;
  Hülsen's corps), the Infantry under Prince Moritz in two wings (Tresckow, Bevern), the Cavalry
  under Penavaire (Krockow, Schönaich, Normann, Meinicke, Krosigk's reserve), the heavy
  artillery.
- **Austria.** NAF regimental strengths split evenly over KRO's battalions and squadrons;
  regiments NAF gives no strength for share the residual (EST); picked troops (the Kommandierte,
  the converged grenadiers) come out of the line pro rata. Every unit-level source puts Daun's
  army near 54,000; CDB90's 44,000 has no breakdown.
- **Quality** (EST, by type and army, never by what the unit did at Kolín): 5 for Prussian
  grenadiers, I./Leibgarde and the Garde du Corps; 4 for other Prussian foot and horse, Austrian
  converged grenadiers, the Kommandierte, the Saxon Karabiniergarde and the Austrian heavy
  artillery; 3 for Austrian line foot and horse, Grenzer and Prussian heavy artillery; 2 for the
  merged Grenz-hussar body.

## Deployment at 13:00

The Prussian army marches east on the Kaiserstrasse in three columns (KRO), headquarters at the
Zlaté Slunce inn, Zieten's hussars deployed astride the road east of it; infantry and cavalry in
column, guns limbered, fatigue 10 (EST: some 7 km marched since 06:00, then a halt). The Austrian
army stands in lines on the heights about 2 km south of the road, Grenzer in skirmish order in
Křečhoř, Chocenice and Poboří, Beck's flank guard on the west, Nádasdy's corps east of Křečhoř;
infantry and cavalry in line, guns unlimbered, fatigue 0; Daun's headquarters on Křečhoř hill
(EST). Spacings and frontages are EST on KRO's order of march, and the tuning above then moves
the Austrian right and centre and the Prussian vanguard.

## Time and weather

Start 13:00 (KRO), local apparent solar time. Sunset 20:11, end of civil twilight 20:56, computed
for 50.03 N, day 169. KRO: the issue remained uncertain until 19:00 or 20:00. Weather: dry, sunny,
warm. Historical losses (for the record, in `objectives.md`): Prussia 13,776 men and 45 guns,
Austria 8,114 (KRO); CDB90 13,768 and 9,000.
