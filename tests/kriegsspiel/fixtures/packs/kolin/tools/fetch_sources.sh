#!/usr/bin/env bash
# Fetch the raw inputs for the Kolín pack into a cache directory (not committed).
# Usage: tests/kriegsspiel/fixtures/packs/kolin/tools/fetch_sources.sh CACHE_DIR
# Sources: Copernicus GLO-30 DEM (public AWS bucket, no key), OpenStreetMap via Overpass.
set -euo pipefail
out="${1:?cache dir}"
mkdir -p "$out"
ua="general-bench-kriegsspiel/0.1 (research)"
for t in N49_00_E015_00 N50_00_E015_00; do
  f="$out/cop_$t.tif"
  [ -s "$f" ] || curl -sS -fL -o "$f" \
    "https://copernicus-dem-30m.s3.amazonaws.com/Copernicus_DSM_COG_10_${t}_DEM/Copernicus_DSM_COG_10_${t}_DEM.tif"
done
bb="49.995,15.015,50.067,15.215"
q="[out:json][timeout:180];(
way[\"highway\"~\"^(primary|secondary|tertiary|unclassified|trunk)\$\"]($bb);
way[\"natural\"=\"wood\"]($bb);way[\"landuse\"=\"forest\"]($bb);
relation[\"landuse\"=\"forest\"]($bb);relation[\"natural\"=\"wood\"]($bb);
way[\"waterway\"]($bb);way[\"natural\"=\"water\"]($bb);relation[\"natural\"=\"water\"]($bb);
way[\"natural\"=\"wetland\"]($bb);way[\"landuse\"=\"orchard\"]($bb);
node[\"amenity\"=\"place_of_worship\"]($bb);way[\"amenity\"=\"place_of_worship\"]($bb);
node[\"historic\"]($bb);node[\"natural\"=\"peak\"]($bb);node[\"place\"]($bb););out geom;"
for ep in https://overpass-api.de/api/interpreter https://overpass.kumi.systems/api/interpreter https://overpass.private.coffee/api/interpreter; do
  if curl -sS -f -m 300 -A "$ua" -o "$out/osm.json" --data-urlencode "data=$q" "$ep"; then
    echo "osm from $ep"; break
  fi
done
