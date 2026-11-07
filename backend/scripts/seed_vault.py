#!/usr/bin/env python3
"""
Seed the climb vault with canonical Philadelphia climbs.

These are derived from OSM/geographic data - NOT user-generated segments.
Run: python scripts/seed_vault.py
"""

import asyncio
import os
import sys
from uuid import uuid4

# Add parent to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.services.patterns.climb_signature import ClimbSignatureGenerator


# =============================================================================
# CANONICAL PHILLY CLIMBS
# =============================================================================

PHILLY_CLIMBS = [
    {
        "name": "Manayunk Wall",
        "slug": "manayunk-wall",
        "description": "The iconic Philly climb - a brutal 17% grade wall featured in multiple pro races",
        "region": "Philadelphia",
        "country_code": "US",
        # Geographic bounds (lat/lon)
        "bounds_min_lat": 40.0230,
        "bounds_max_lat": 40.0280,
        "bounds_min_lon": -75.2320,
        "bounds_max_lon": -75.2250,
        # Profile characteristics
        "base_elevation_m": 15.0,
        "peak_elevation_m": 75.0,
        "total_vert_m": 60.0,
        "avg_gradient_pct": 17.0,
        "max_gradient_pct": 24.0,
        "distance_m": 350.0,
        # UCI category
        "uci_category": "4",
        # Elevation profile (normalized 0-1 distance, elevation in meters)
        # Manayunk Wall starts steep, stays steep, slight easing at top
        "elevation_profile": [
            (0.0, 15.0),
            (0.1, 22.0),   # 20% to start
            (0.2, 30.0),   # ~22%
            (0.3, 39.0),   # steep middle
            (0.4, 48.0),
            (0.5, 55.0),   # peak gradient zone
            (0.6, 61.0),   # starting to ease
            (0.7, 66.0),
            (0.8, 70.0),
            (0.9, 73.0),
            (1.0, 75.0),   # summit
        ],
        "tags": ["iconic", "pro-race", "steep", "philadelphia"],
    },
    {
        "name": "Lemon Hill",
        "slug": "lemon-hill",
        "description": "Popular training climb in Fairmount Park with scenic views of the city",
        "region": "Philadelphia",
        "country_code": "US",
        "bounds_min_lat": 39.9680,
        "bounds_max_lat": 39.9750,
        "bounds_min_lon": -75.1920,
        "bounds_max_lon": -75.1850,
        "base_elevation_m": 10.0,
        "peak_elevation_m": 40.0,
        "total_vert_m": 30.0,
        "avg_gradient_pct": 6.0,
        "max_gradient_pct": 8.0,
        "distance_m": 500.0,
        "uci_category": "UC",  # Uncategorized - too short
        # More gradual, consistent grade
        "elevation_profile": [
            (0.0, 10.0),
            (0.1, 12.5),
            (0.2, 15.5),
            (0.3, 18.5),
            (0.4, 22.0),
            (0.5, 25.0),
            (0.6, 28.5),
            (0.7, 32.0),
            (0.8, 35.0),
            (0.9, 37.5),
            (1.0, 40.0),
        ],
        "tags": ["fairmount-park", "training", "scenic"],
    },
    {
        "name": "Belmont Plateau",
        "slug": "belmont-plateau",
        "description": "Classic West Philly climb through Fairmount Park to the plateau overlook",
        "region": "Philadelphia",
        "country_code": "US",
        "bounds_min_lat": 39.9780,
        "bounds_max_lat": 39.9880,
        "bounds_min_lon": -75.2250,
        "bounds_max_lon": -75.2150,
        "base_elevation_m": 20.0,
        "peak_elevation_m": 65.0,
        "total_vert_m": 45.0,
        "avg_gradient_pct": 5.0,
        "max_gradient_pct": 9.0,
        "distance_m": 900.0,
        "uci_category": "UC",
        # Variable gradient - easier start, steeper middle, eases at top
        "elevation_profile": [
            (0.0, 20.0),
            (0.1, 22.0),   # gentle start
            (0.2, 25.0),   # ~3%
            (0.3, 30.0),   # steepening
            (0.4, 36.0),   # ~6.5%
            (0.5, 43.0),   # steepest section
            (0.6, 50.0),   # ~7%
            (0.7, 55.0),
            (0.8, 59.0),   # easing
            (0.9, 62.0),
            (1.0, 65.0),   # plateau
        ],
        "tags": ["fairmount-park", "plateau", "west-philly"],
    },
]


def generate_signature_for_climb(climb: dict) -> str:
    """
    Generate a 64-byte signature from a climb's elevation profile.
    """
    profile = climb["elevation_profile"]
    distance_m = climb["distance_m"]

    # Expand to more points for accurate signature
    elevations = []
    distances = []
    timestamps = []

    num_points = 50  # 50 data points
    for i in range(num_points):
        t = i / (num_points - 1)  # 0 to 1

        # Interpolate elevation from profile
        for j in range(len(profile) - 1):
            t0, e0 = profile[j]
            t1, e1 = profile[j + 1]
            if t0 <= t <= t1:
                # Linear interpolation
                frac = (t - t0) / (t1 - t0) if t1 != t0 else 0
                elev = e0 + frac * (e1 - e0)
                break
        else:
            elev = profile[-1][1]

        elevations.append(elev)
        distances.append(t * distance_m)
        # Assume ~15 km/h average = 4.17 m/s
        timestamps.append(int(t * distance_m / 4.17))

    # Generate signature
    generator = ClimbSignatureGenerator()
    sig = generator.generate(elevations, timestamps, distances)

    return sig.hex


def build_insert_sql(climb: dict, signature_hex: str) -> str:
    """Build INSERT statement for a climb."""
    difficulty = climb["total_vert_m"] * (1 + climb["avg_gradient_pct"] / 10)

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
    '{climb["name"]}',
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
    '{signature_hex}',
    0.60,  -- signature tolerance (0.6 = 60% similarity required)
    '{climb["uci_category"]}',
    {difficulty:.1f},
    ARRAY{climb["tags"]}::TEXT[],
    'manual',
    TRUE,
    TRUE,
    TRUE
)
ON CONFLICT (slug) DO UPDATE SET
    description = EXCLUDED.description,
    signature_hex = EXCLUDED.signature_hex,
    updated_at = NOW();
"""


def main():
    print("=" * 60)
    print("SEEDING CLIMB VAULT WITH PHILADELPHIA CLIMBS")
    print("=" * 60)

    all_sql = []

    for climb in PHILLY_CLIMBS:
        print(f"\nProcessing: {climb['name']}")
        print(f"  Vert: {climb['total_vert_m']}m")
        print(f"  Grade: {climb['avg_gradient_pct']}%")
        print(f"  Distance: {climb['distance_m']}m")

        # Generate signature
        sig_hex = generate_signature_for_climb(climb)
        print(f"  Signature: {sig_hex[:32]}...")

        # Build SQL
        sql = build_insert_sql(climb, sig_hex)
        all_sql.append(sql)

    # Output combined SQL
    combined = "\n".join(all_sql)

    print("\n" + "=" * 60)
    print("SQL TO EXECUTE:")
    print("=" * 60)
    print(combined)

    # Save to file
    output_file = os.path.join(os.path.dirname(__file__), "seed_vault.sql")
    with open(output_file, "w") as f:
        f.write("-- Auto-generated by seed_vault.py\n")
        f.write("-- Canonical Philadelphia climbs\n\n")
        f.write(combined)

    print(f"\nSQL saved to: {output_file}")
    print("\nTo execute:")
    print("  ssh root@localhost \"PGPASSWORD='...' psql -h ... -f /tmp/seed_vault.sql\"")


if __name__ == "__main__":
    main()
