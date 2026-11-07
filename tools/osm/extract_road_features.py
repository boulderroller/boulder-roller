#!/usr/bin/env python3
"""Extract road features from OSM PBF for climb detection enrichment.

Two-pass extraction using pyosmium (package: osmium):
  Pass 1: Collect highway ways — node refs, tags (name, bridge, tunnel, highway class)
  Pass 2: Resolve node coordinates for referenced nodes

Then compute:
  - Intersections: nodes shared by 2+ highway ways
  - Bridges: ways with bridge=yes
  - Tunnels: ways with tunnel=yes
  - Road segments: named highway ways

Output: CSV indexed by H3 resolution-10 tile for Supabase road_features table.

Usage:
    python tools/osm/extract_road_features.py /tmp/philly-metro.osm.pbf \
        --output tools/osm/philly_road_features.csv

Requires: pip install osmium h3  (in Python 3.12+ venv)
"""

import argparse
import csv
import json
import math
import sys
from collections import defaultdict
from dataclasses import dataclass, field

import h3
import osmium

# H3 resolution for tile indexing (matches project standard)
H3_RESOLUTION = 10

# Sample linear features every ~30m for H3 tile assignment
LINEAR_SAMPLE_INTERVAL_M = 30.0

# Highway classes we care about (excludes footways, service roads, etc.)
RELEVANT_HIGHWAY_CLASSES = frozenset({
    "motorway", "motorway_link",
    "trunk", "trunk_link",
    "primary", "primary_link",
    "secondary", "secondary_link",
    "tertiary", "tertiary_link",
    "unclassified",
    "residential",
    "living_street",
    "road",  # unknown classification
})


@dataclass
class WayInfo:
    """Collected info from a highway way."""
    osm_id: int
    node_refs: list[int]
    name: str | None
    highway_class: str
    is_bridge: bool
    is_tunnel: bool
    tags: dict[str, str]


def haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Haversine distance in meters between two (lat, lon) points."""
    R = 6_371_000.0
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlam = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlam / 2) ** 2
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def interpolate_points(coords: list[tuple[float, float]], interval_m: float) -> list[tuple[float, float]]:
    """Sample points along a polyline at roughly `interval_m` spacing.

    Always includes first and last point.
    """
    if len(coords) < 2:
        return list(coords)

    result = [coords[0]]
    accum = 0.0

    for i in range(1, len(coords)):
        d = haversine_m(coords[i - 1][0], coords[i - 1][1], coords[i][0], coords[i][1])
        accum += d
        if accum >= interval_m:
            result.append(coords[i])
            accum = 0.0

    # Always include last point
    if result[-1] != coords[-1]:
        result.append(coords[-1])

    return result


class WayCollector(osmium.SimpleHandler):
    """Pass 1: Collect highway ways and their node references."""

    def __init__(self):
        super().__init__()
        self.ways: dict[int, WayInfo] = {}
        self.needed_nodes: set[int] = set()

    def way(self, w):
        highway = w.tags.get("highway")
        if highway not in RELEVANT_HIGHWAY_CLASSES:
            return

        node_refs = [n.ref for n in w.nodes]
        tags = {t.k: t.v for t in w.tags}

        self.ways[w.id] = WayInfo(
            osm_id=w.id,
            node_refs=node_refs,
            name=w.tags.get("name"),
            highway_class=highway,
            is_bridge=w.tags.get("bridge", "no") == "yes",
            is_tunnel=w.tags.get("tunnel", "no") == "yes",
            tags=tags,
        )

        self.needed_nodes.update(node_refs)


class NodeCollector(osmium.SimpleHandler):
    """Pass 2: Resolve coordinates for needed nodes."""

    def __init__(self, needed: set[int]):
        super().__init__()
        self.needed = needed
        self.coords: dict[int, tuple[float, float]] = {}

    def node(self, n):
        if n.id in self.needed:
            self.coords[n.id] = (n.location.lat, n.location.lon)


@dataclass
class RoadFeature:
    """A single road feature row for CSV output."""
    tile_id: str
    feature_type: str  # intersection, bridge, tunnel, road_segment
    osm_id: int
    name: str | None
    highway_class: str | None
    lat: float
    lon: float
    road_names: list[str]
    degree: int | None
    tags: dict


def extract_intersections(
    ways: dict[int, WayInfo],
    coords: dict[int, tuple[float, float]],
) -> list[RoadFeature]:
    """Find nodes shared by 2+ highway ways = intersections."""
    # Count which ways reference each node, and collect way names/classes
    node_ways: dict[int, list[WayInfo]] = defaultdict(list)
    for way in ways.values():
        for nid in way.node_refs:
            node_ways[nid].append(way)

    features = []
    for nid, way_list in node_ways.items():
        if len(way_list) < 2:
            continue
        if nid not in coords:
            continue

        lat, lon = coords[nid]
        road_names = sorted({w.name for w in way_list if w.name})
        highway_classes = sorted({w.highway_class for w in way_list})
        degree = len(way_list)

        tile_id = h3.latlng_to_cell(lat, lon, H3_RESOLUTION)

        features.append(RoadFeature(
            tile_id=tile_id,
            feature_type="intersection",
            osm_id=nid,
            name=" / ".join(road_names) if road_names else None,
            highway_class=highway_classes[0] if highway_classes else None,
            lat=lat,
            lon=lon,
            road_names=road_names,
            degree=degree,
            tags={"highway_classes": highway_classes},
        ))

    return features


def extract_linear_features(
    ways: dict[int, WayInfo],
    coords: dict[int, tuple[float, float]],
    feature_type: str,
    filter_fn,
) -> list[RoadFeature]:
    """Extract bridge/tunnel/road_segment features from ways.

    For linear features, we sample points along the way geometry and create
    one feature row per H3 tile touched.
    """
    features = []

    for way in ways.values():
        if not filter_fn(way):
            continue

        # Resolve way geometry
        way_coords = []
        for nid in way.node_refs:
            if nid in coords:
                way_coords.append(coords[nid])

        if len(way_coords) < 2:
            continue

        # Compute centroid for the feature's canonical lat/lon
        centroid_lat = sum(c[0] for c in way_coords) / len(way_coords)
        centroid_lon = sum(c[1] for c in way_coords) / len(way_coords)

        # Sample points along the way for H3 tile assignment
        sampled = interpolate_points(way_coords, LINEAR_SAMPLE_INTERVAL_M)
        tiles_seen = set()

        for lat, lon in sampled:
            tile_id = h3.latlng_to_cell(lat, lon, H3_RESOLUTION)
            if tile_id in tiles_seen:
                continue
            tiles_seen.add(tile_id)

            # Minimal tags — drop geometry, keep useful metadata
            tags = {k: v for k, v in way.tags.items()
                    if k not in ("highway", "name", "bridge", "tunnel")}

            # For bridges, store way endpoints for elevation interpolation
            if feature_type == "bridge":
                tags["bridge_start_lat"] = way_coords[0][0]
                tags["bridge_start_lon"] = way_coords[0][1]
                tags["bridge_end_lat"] = way_coords[-1][0]
                tags["bridge_end_lon"] = way_coords[-1][1]
                tags["bridge_length_m"] = sum(
                    haversine_m(way_coords[j][0], way_coords[j][1],
                                way_coords[j + 1][0], way_coords[j + 1][1])
                    for j in range(len(way_coords) - 1)
                )

            features.append(RoadFeature(
                tile_id=tile_id,
                feature_type=feature_type,
                osm_id=way.osm_id,
                name=way.name,
                highway_class=way.highway_class,
                lat=centroid_lat,
                lon=centroid_lon,
                road_names=[way.name] if way.name else [],
                degree=None,
                tags=tags,
            ))

    return features


def write_csv(features: list[RoadFeature], output_path: str):
    """Write features to CSV compatible with Supabase COPY."""
    with open(output_path, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow([
            "tile_id", "feature_type", "osm_id", "name", "highway_class",
            "lat", "lon", "road_names", "degree", "tags",
        ])

        for feat in features:
            # Format road_names as Postgres array literal: {name1,name2}
            if feat.road_names:
                road_names_pg = "{" + ",".join(
                    '"' + n.replace('"', '\\"') + '"' for n in feat.road_names
                ) + "}"
            else:
                road_names_pg = "{}"

            writer.writerow([
                feat.tile_id,
                feat.feature_type,
                feat.osm_id,
                feat.name or "",
                feat.highway_class or "",
                f"{feat.lat:.7f}",
                f"{feat.lon:.7f}",
                road_names_pg,
                feat.degree if feat.degree is not None else "",
                json.dumps(feat.tags) if feat.tags else "{}",
            ])


def main():
    parser = argparse.ArgumentParser(description="Extract OSM road features for climb detection")
    parser.add_argument("pbf_path", help="Path to OSM PBF file")
    parser.add_argument("--output", "-o", default="road_features.csv",
                        help="Output CSV path (default: road_features.csv)")
    args = parser.parse_args()

    print(f"Pass 1: Collecting highway ways from {args.pbf_path}...")
    way_collector = WayCollector()
    way_collector.apply_file(args.pbf_path)
    print(f"  Found {len(way_collector.ways):,} highway ways, "
          f"{len(way_collector.needed_nodes):,} unique nodes referenced")

    print("Pass 2: Resolving node coordinates...")
    node_collector = NodeCollector(way_collector.needed_nodes)
    node_collector.apply_file(args.pbf_path)
    print(f"  Resolved {len(node_collector.coords):,} node coordinates")

    ways = way_collector.ways
    coords = node_collector.coords

    # Free the collectors
    del way_collector, node_collector

    print("Extracting intersections...")
    intersections = extract_intersections(ways, coords)
    print(f"  {len(intersections):,} intersection features")

    print("Extracting bridges...")
    bridges = extract_linear_features(
        ways, coords, "bridge",
        lambda w: w.is_bridge,
    )
    print(f"  {len(bridges):,} bridge tile features")

    print("Extracting tunnels...")
    tunnels = extract_linear_features(
        ways, coords, "tunnel",
        lambda w: w.is_tunnel,
    )
    print(f"  {len(tunnels):,} tunnel tile features")

    print("Extracting named road segments...")
    road_segments = extract_linear_features(
        ways, coords, "road_segment",
        lambda w: w.name is not None,
    )
    print(f"  {len(road_segments):,} road segment tile features")

    all_features = intersections + bridges + tunnels + road_segments
    print(f"\nTotal: {len(all_features):,} features")

    # Summary by type
    type_counts = defaultdict(int)
    for f in all_features:
        type_counts[f.feature_type] += 1
    for ft, count in sorted(type_counts.items()):
        print(f"  {ft}: {count:,}")

    # Unique tiles
    unique_tiles = {f.tile_id for f in all_features}
    print(f"  Spanning {len(unique_tiles):,} unique H3 tiles")

    print(f"\nWriting CSV to {args.output}...")
    write_csv(all_features, args.output)
    print("Done.")


if __name__ == "__main__":
    main()
