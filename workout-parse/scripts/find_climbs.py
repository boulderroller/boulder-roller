#!/usr/bin/env python3
"""
Search roads_philly.json for potential climb roads and extract their data.
"""
import json
from pathlib import Path

# Roads the user wants to find (normalized to lowercase)
TARGET_ROADS = [
    "rose glen",
    "waverly",
    "harts",
    "green",
    "lafayette",
    "manor",
    "hollow",
    "youngsford",
    "county line",
    "saw mill",
    "shurs",
    "barren hill",
    "bells mill",
    "valley green",
    "wises mill",
    "conshohocken",
    "arden",
    "old gulph",
    "hidden river",
    "ashland",
    "falls",
    "lansdowne",
    "welsh valley",
    "diamond rock",
]

def normalize(name: str) -> str:
    """Normalize road name for matching."""
    if not name:
        return ""
    # Lowercase, remove common suffixes
    n = name.lower()
    for suffix in [" road", " rd", " lane", " ln", " drive", " dr", " avenue", " ave", " street", " st"]:
        n = n.replace(suffix, "")
    return n.strip()

def main():
    roads_file = Path(__file__).parent.parent / "data" / "roads_philly.json"

    print(f"Loading {roads_file}...")
    with open(roads_file) as f:
        roads = json.load(f)

    print(f"Loaded {len(roads)} roads")

    # Find matches
    matches = {target: [] for target in TARGET_ROADS}

    for road in roads:
        name = road.get("name", "")
        if not name:
            continue

        norm_name = normalize(name)

        for target in TARGET_ROADS:
            if target in norm_name:
                geom = road.get("geometry", [])

                # Geometry is [[lon, lat], [lon, lat], ...]
                if len(geom) >= 2:
                    min_lat = min(p[1] for p in geom)
                    max_lat = max(p[1] for p in geom)
                    min_lon = min(p[0] for p in geom)
                    max_lon = max(p[0] for p in geom)
                else:
                    min_lat = max_lat = min_lon = max_lon = 0

                matches[target].append({
                    "osm_way_id": road.get("osm_way_id"),
                    "name": name,
                    "road_class": road.get("road_class"),
                    "grade_pct": road.get("grade"),
                    "length_m": road.get("length_m"),
                    "point_count": len(geom),
                    "h3_cells": road.get("h3_cells", []),
                    "h3_count": len(road.get("h3_cells", [])),
                    "bounds": {
                        "min_lat": min_lat,
                        "max_lat": max_lat,
                        "min_lon": min_lon,
                        "max_lon": max_lon,
                    },
                    "geometry": geom,
                })
                break

    # Report findings
    print("\n" + "="*80)
    print("CLIMB ROAD SEARCH RESULTS")
    print("="*80)

    found_count = 0
    for target in TARGET_ROADS:
        road_matches = matches[target]
        if road_matches:
            found_count += 1
            # Sort by length (descending) to get full segments
            road_matches.sort(key=lambda x: x["length_m"] or 0, reverse=True)
            print(f"\n{target.upper()} ({len(road_matches)} segments):")
            for m in road_matches[:5]:  # Show top 5
                grade_str = f"{m['grade_pct']:.1f}%" if m['grade_pct'] else "N/A"
                length_str = f"{m['length_m']:.0f}m" if m['length_m'] else "N/A"
                print(f"  - {m['name']} (OSM:{m['osm_way_id']})")
                print(f"    length: {length_str}, grade: {grade_str}, h3: {m['h3_count']} cells")
                print(f"    bounds: [{m['bounds']['min_lat']:.4f}, {m['bounds']['min_lon']:.4f}] to [{m['bounds']['max_lat']:.4f}, {m['bounds']['max_lon']:.4f}]")
        else:
            print(f"\n{target.upper()}: NOT FOUND")

    print(f"\n{'='*80}")
    print(f"Found {found_count}/{len(TARGET_ROADS)} target roads")

    # Save matches for next step (without full geometry to keep it manageable)
    output_file = Path(__file__).parent / "climb_matches.json"
    summary_matches = {}
    for target, road_list in matches.items():
        summary_matches[target] = []
        for m in road_list:
            summary_matches[target].append({
                "osm_way_id": m["osm_way_id"],
                "name": m["name"],
                "road_class": m["road_class"],
                "grade_pct": m["grade_pct"],
                "length_m": m["length_m"],
                "h3_count": m["h3_count"],
                "h3_cells": m["h3_cells"],
                "bounds": m["bounds"],
                "geometry": m["geometry"],  # Keep full geometry for signature generation
            })

    with open(output_file, "w") as f:
        json.dump(summary_matches, f, indent=2)
    print(f"Saved matches to {output_file}")

if __name__ == "__main__":
    main()
