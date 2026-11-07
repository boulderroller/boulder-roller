#!/usr/bin/env python3
"""
Filter climb matches to Philly metro area and prepare for vault seeding.
"""
import json
from pathlib import Path

# Philly metro bounding box (generous)
PHILLY_BOUNDS = {
    "min_lat": 39.85,
    "max_lat": 40.20,
    "min_lon": -75.55,
    "max_lon": -74.85,
}

def in_philly(bounds: dict) -> bool:
    """Check if road segment is in Philly metro area."""
    return (
        bounds["min_lat"] >= PHILLY_BOUNDS["min_lat"]
        and bounds["max_lat"] <= PHILLY_BOUNDS["max_lat"]
        and bounds["min_lon"] >= PHILLY_BOUNDS["min_lon"]
        and bounds["max_lon"] <= PHILLY_BOUNDS["max_lon"]
    )

def main():
    # Load matches
    matches_file = Path(__file__).parent / "climb_matches.json"
    with open(matches_file) as f:
        matches = json.load(f)

    # Load full roads data for Valley Green lookup
    roads_file = Path(__file__).parent.parent / "data" / "roads_philly.json"
    with open(roads_file) as f:
        roads = json.load(f)

    # Find Valley Green Road in Philly area
    for r in roads:
        name = r.get("name", "")
        if "Valley Green" in name:
            geom = r.get("geometry", [])
            if len(geom) >= 2:
                min_lat = min(p[1] for p in geom)
                max_lat = max(p[1] for p in geom)
                min_lon = min(p[0] for p in geom)
                max_lon = max(p[0] for p in geom)
                bounds = {"min_lat": min_lat, "max_lat": max_lat, "min_lon": min_lon, "max_lon": max_lon}
                if in_philly(bounds):
                    matches.setdefault("valley green", []).append({
                        "osm_way_id": r.get("osm_way_id"),
                        "name": name,
                        "road_class": r.get("road_class"),
                        "grade_pct": r.get("grade"),
                        "length_m": r.get("length_m"),
                        "h3_count": len(r.get("h3_cells", [])),
                        "h3_cells": r.get("h3_cells", []),
                        "bounds": bounds,
                        "geometry": geom,
                    })

    # Filter to Philly area and select best segment per road
    philly_climbs = {}

    for target, road_list in matches.items():
        philly_roads = [r for r in road_list if in_philly(r["bounds"])]
        if philly_roads:
            # Sort by length, take longest
            philly_roads.sort(key=lambda x: x.get("length_m") or 0, reverse=True)
            # Take top segments (some roads have multiple segments)
            philly_climbs[target] = philly_roads[:3]

    print("="*80)
    print("PHILLY METRO CLIMB CANDIDATES")
    print("="*80)

    total_segments = 0
    for target in sorted(philly_climbs.keys()):
        segments = philly_climbs[target]
        total_segments += len(segments)
        print(f"\n{target.upper()}:")
        for s in segments:
            length = s.get("length_m", 0) or 0
            grade = s.get("grade_pct")
            grade_str = f"{grade:.1f}%" if grade else "needs elevation"
            print(f"  - {s['name']} ({length:.0f}m, {grade_str})")
            print(f"    OSM: {s['osm_way_id']}, H3: {s['h3_count']} cells")
            print(f"    Bounds: {s['bounds']['min_lat']:.4f},{s['bounds']['min_lon']:.4f} to {s['bounds']['max_lat']:.4f},{s['bounds']['max_lon']:.4f}")

    print(f"\n{'='*80}")
    print(f"Total: {len(philly_climbs)} roads, {total_segments} segments")

    # Save filtered results
    output_file = Path(__file__).parent / "philly_climb_candidates.json"
    with open(output_file, "w") as f:
        json.dump(philly_climbs, f, indent=2)
    print(f"Saved to {output_file}")

if __name__ == "__main__":
    main()
