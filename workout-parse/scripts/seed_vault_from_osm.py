#!/usr/bin/env python3
"""
Seed the climb vault with canonical Philadelphia climbs from OSM data.
Uses elevation profiles fetched from OpenTopoData.

Run: python scripts/seed_vault_from_osm.py
"""

import json
import os
import sys
from pathlib import Path

# Add backend to path for imports
backend_path = Path(__file__).parent.parent.parent / "backend"
sys.path.insert(0, str(backend_path))

from app.services.patterns.climb_signature import ClimbSignatureGenerator

# Minimum thresholds for a "real" climb
MIN_CLIMB_M = 25  # At least 25m total climb
MIN_AVG_GRADE = 2.0  # At least 2% average grade

def slugify(name: str) -> str:
    """Convert name to URL slug."""
    return name.lower().replace(" ", "-").replace("'", "")

def generate_signature_for_profile(profile: list, stats: dict) -> str:
    """Generate 64-byte signature from elevation profile."""
    if not profile or len(profile) < 5:
        return None

    elevations = [p["elevation_m"] for p in profile]
    distances = [p["dist_m"] for p in profile]

    # Estimate timestamps (assume ~15 km/h = 4.17 m/s)
    timestamps = [int(d / 4.17) for d in distances]

    generator = ClimbSignatureGenerator()
    sig = generator.generate(elevations, timestamps, distances)
    return sig.hex

def build_sql(climb: dict) -> str:
    """Build INSERT statement for a climb."""
    difficulty = climb["total_vert_m"] * (1 + abs(climb["avg_gradient_pct"]) / 10)

    return f"""
INSERT INTO climb_vault (
    id, name, slug, description, region, country_code,
    bounds_min_lat, bounds_max_lat, bounds_min_lon, bounds_max_lon,
    base_elevation_m, peak_elevation_m,
    total_vert_m, avg_gradient_pct, max_gradient_pct, distance_m,
    signature_hex, signature_tolerance,
    uci_category, difficulty_score,
    tags, source, verified, active, featured
) VALUES (
    gen_random_uuid(),
    '{climb["name"].replace("'", "''")}',
    '{climb["slug"]}',
    '{climb["description"].replace("'", "''")}',
    '{climb["region"]}',
    '{climb["country_code"]}',
    {climb["bounds_min_lat"]},
    {climb["bounds_max_lat"]},
    {climb["bounds_min_lon"]},
    {climb["bounds_max_lon"]},
    {climb["base_elevation_m"]},
    {climb["peak_elevation_m"]},
    {climb["total_vert_m"]},
    {climb["avg_gradient_pct"]},
    {climb["max_gradient_pct"]},
    {climb["distance_m"]},
    '{climb["signature_hex"]}',
    0.55,  -- signature tolerance (0.55 = 55% similarity required)
    'UC',  -- Uncategorized for local climbs
    {difficulty:.1f},
    ARRAY{climb["tags"]}::TEXT[],
    'osm',
    TRUE,
    TRUE,
    FALSE
)
ON CONFLICT (slug) DO UPDATE SET
    description = EXCLUDED.description,
    signature_hex = EXCLUDED.signature_hex,
    total_vert_m = EXCLUDED.total_vert_m,
    avg_gradient_pct = EXCLUDED.avg_gradient_pct,
    max_gradient_pct = EXCLUDED.max_gradient_pct,
    distance_m = EXCLUDED.distance_m,
    updated_at = NOW();
"""

def main():
    # Load elevation data
    data_file = Path(__file__).parent / "philly_climbs_with_elevation.json"
    with open(data_file) as f:
        climbs_data = json.load(f)

    print("=" * 70)
    print("SEEDING CLIMB VAULT FROM OSM DATA")
    print("=" * 70)

    vault_climbs = []
    skipped = []

    for road_name, segment in climbs_data.items():
        stats = segment.get("stats", {})
        profile = segment.get("elevation_profile", [])

        total_climb = stats.get("total_climb_m", 0)
        avg_grade = abs(stats.get("avg_grade_pct", 0))
        max_grade = stats.get("max_grade_pct", 0)

        # Filter to actual climbs
        if total_climb < MIN_CLIMB_M:
            skipped.append((road_name, f"too little climb ({total_climb:.0f}m < {MIN_CLIMB_M}m)"))
            continue

        if avg_grade < MIN_AVG_GRADE and max_grade < 5.0:
            skipped.append((road_name, f"too flat (avg {avg_grade:.1f}%, max {max_grade:.1f}%)"))
            continue

        print(f"\nProcessing: {segment['name']}")
        print(f"  Total climb: {total_climb:.0f}m")
        print(f"  Avg grade: {stats['avg_grade_pct']:.1f}%")
        print(f"  Max grade: {max_grade:.1f}%")
        print(f"  Distance: {stats['total_dist_m']:.0f}m")

        # Generate signature
        sig_hex = generate_signature_for_profile(profile, stats)
        if not sig_hex:
            skipped.append((road_name, "couldn't generate signature"))
            continue
        print(f"  Signature: {sig_hex[:32]}...")

        # Build vault entry
        vault_climb = {
            "name": segment["name"],
            "slug": slugify(segment["name"]),
            "description": f"Local climb in the Philadelphia area - {total_climb:.0f}m elevation gain",
            "region": "Philadelphia",
            "country_code": "US",
            "bounds_min_lat": segment["bounds"]["min_lat"],
            "bounds_max_lat": segment["bounds"]["max_lat"],
            "bounds_min_lon": segment["bounds"]["min_lon"],
            "bounds_max_lon": segment["bounds"]["max_lon"],
            "base_elevation_m": stats["start_ele_m"],
            "peak_elevation_m": stats["max_ele_m"],
            "total_vert_m": total_climb,
            "avg_gradient_pct": stats["avg_grade_pct"],
            "max_gradient_pct": max_grade,
            "distance_m": stats["total_dist_m"],
            "signature_hex": sig_hex,
            "tags": ["philadelphia", "local", road_name.replace(" ", "-")],
        }
        vault_climbs.append(vault_climb)

    print("\n" + "=" * 70)
    print(f"RESULTS: {len(vault_climbs)} climbs ready for vault")
    print("=" * 70)

    if skipped:
        print(f"\nSkipped {len(skipped)} roads:")
        for name, reason in skipped:
            print(f"  - {name}: {reason}")

    # Generate SQL
    all_sql = [build_sql(c) for c in vault_climbs]
    combined_sql = "\n".join(all_sql)

    print("\n" + "=" * 70)
    print("SQL READY FOR EXECUTION")
    print("=" * 70)

    # Save SQL
    output_sql = Path(__file__).parent / "seed_osm_climbs.sql"
    with open(output_sql, "w") as f:
        f.write("-- Auto-generated from OSM data by seed_vault_from_osm.py\n")
        f.write(f"-- {len(vault_climbs)} canonical Philadelphia climbs\n\n")
        f.write(combined_sql)
    print(f"\nSQL saved to: {output_sql}")

    # Also save JSON for reference
    output_json = Path(__file__).parent / "vault_climbs.json"
    with open(output_json, "w") as f:
        json.dump(vault_climbs, f, indent=2)
    print(f"JSON saved to: {output_json}")

    # Print summary
    print("\n" + "=" * 70)
    print("CLIMBS TO ADD TO VAULT:")
    print("=" * 70)
    vault_climbs.sort(key=lambda x: x["total_vert_m"], reverse=True)
    for c in vault_climbs:
        print(f"  {c['name']:30s} {c['total_vert_m']:5.0f}m  {c['avg_gradient_pct']:5.1f}%  {c['distance_m']:6.0f}m")

if __name__ == "__main__":
    main()
