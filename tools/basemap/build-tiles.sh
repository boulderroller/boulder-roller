#!/bin/sh
# Builds the map ground's vector tiles on the droplet (never on a laptop):
# OpenMapTiles-schema PMTiles from Geofabrik's Pennsylvania, New Jersey and Delaware
# extracts with Planetiler's default OpenMapTiles profile, then installs them where
# Caddy serves https://api.boulderroller.xyz/basemap/tiles/.
#
#   scp tools/basemap/build-tiles.sh root@<droplet>:/root/basemap-build/
#   ssh root@<droplet> 'cd /root/basemap-build && nohup nice -n 19 ./build-tiles.sh > build.log 2>&1 &'
#
# Production shares the 2-vCPU, 4 GB box, so every step runs in a throwaway container
# capped at 1.6 GB of memory without swap, one CPU at low weight, and an OOM score that
# makes it the first thing the kernel kills under pressure.
#
# Inputs, fetched beforehand into /root/basemap-build (the URLs Planetiler would use):
#   osm/{pennsylvania,new-jersey,delaware}-$EXTRACT.osm.pbf   download.geofabrik.de
#   sources/natural_earth_vector.sqlite.zip                     naciscdn.org
#   sources/lake_centerline.shp.zip                             github.com/acalcutt/osm-lakelines v12
#   sources/water-polygons-split-3857.zip                       osmdata.openstreetmap.de
# WATER may name an empty placeholder when osmdata.openstreetmap.de is unreachable; the
# tiles then have no OSM ocean at zoom 6 and above, so rebuild once the host is back.
set -eu

EXTRACT=${EXTRACT:-261020}                 # Geofabrik extract date, YYMMDD
OUT=${OUT:-omt-pa-nj-de-2026-10-20.pmtiles}
WATER=${WATER:-sources/water-polygons-split-3857.zip}
BOUNDS=${BOUNDS:--80.62,38.40,-73.80,42.40} # Pennsylvania, New Jersey and Delaware
PLANETILER=${PLANETILER:-ghcr.io/onthegomap/planetiler:0.10.2}
SERVE=/var/lib/docker/volumes/boulder-repo_caddy_data/_data/www/basemap/tiles
CAPS="--memory=1600m --memory-swap=1600m --cpus=1 --cpu-shares=128 --oom-score-adj=1000"

cd "$(dirname "$0")"
mkdir -p out tmp

echo "== merge extracts $(date -u +%FT%TZ)"
docker run --rm $CAPS -v "$PWD:/w" -w /w ubuntu:22.04 sh -c '
  set -e
  apt-get update -qq && DEBIAN_FRONTEND=noninteractive apt-get install -y -qq osmium-tool > /dev/null
  osmium merge --overwrite -o osm/pa-nj-de-'"$EXTRACT"'.osm.pbf \
    osm/pennsylvania-'"$EXTRACT"'.osm.pbf osm/new-jersey-'"$EXTRACT"'.osm.pbf osm/delaware-'"$EXTRACT"'.osm.pbf
  osmium fileinfo osm/pa-nj-de-'"$EXTRACT"'.osm.pbf | sed -n "1,12p"'

echo "== planetiler $(date -u +%FT%TZ)"
docker run --rm $CAPS -e JAVA_TOOL_OPTIONS="-Xmx1100m" -v "$PWD:/data" "$PLANETILER" \
  --osm_path="/data/osm/pa-nj-de-$EXTRACT.osm.pbf" \
  --natural_earth_path=/data/sources/natural_earth_vector.sqlite.zip \
  --lake_centerlines_path=/data/sources/lake_centerline.shp.zip \
  --water_polygons_path="/data/$WATER" \
  --bounds="$BOUNDS" --threads=2 --tmpdir=/data/tmp \
  --nodemap_type=sparsearray --nodemap_storage=mmap \
  --output="/data/out/$OUT" --force

echo "== install $(date -u +%FT%TZ)"
mkdir -p "$SERVE"
cp "out/$OUT" "$SERVE/$OUT.partial" && mv "$SERVE/$OUT.partial" "$SERVE/$OUT"
ls -la "$SERVE"
rm -rf tmp
echo "== done $(date -u +%FT%TZ)"
