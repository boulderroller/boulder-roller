#!/usr/bin/env python3
"""
Fetch elevation data for Philly climb candidates using OpenTopoData API.
"""
import json
import time
import urllib.request
import urllib.parse
from pathlib import Path
from math import radians, sin, cos, sqrt, atan2

API_URL = "https://api.opentopodata.org/v1/ned10m"
BATCH_SIZE = 100  # Max points per request

def haversine(lat1, lon1, lat2, lon2):
    """Calculate distance in meters between two points."""
    R = 6371000
    phi1, phi2 = radians(lat1), radians(lat2)
    dphi = radians(lat2 - lat1)
    dlam = radians(lon2 - lon1)
    a = sin(dphi/2)**2 + cos(phi1)*cos(phi2)*sin(dlam/2)**2
    return 2 * R * atan2(sqrt(a), sqrt(1-a))

def fetch_elevations(points: list[tuple[float, float]]) -> list[float]:
    """Fetch elevations for a batch of points [(lat, lon), ...]."""
    locations = "|".join(f"{lat},{lon}" for lat, lon in points)
    url = f"{API_URL}?locations={urllib.parse.quote(locations)}"

    try:
        with urllib.request.urlopen(url, timeout=30) as resp:
            data = json.loads(resp.read())
            if data.get("status") == "OK":
                return [r["elevation"] for r in data["results"]]
    except Exception as e:
        print(f"  Error fetching elevations: {e}")

    return [None] * len(points)

def process_segment(segment: dict) -> dict:
    """Add elevation profile to a road segment."""
    geom = segment["geometry"]
    if len(geom) < 2:
        return segment

    # Extract points (geometry is [[lon, lat], ...])
    points = [(p[1], p[0]) for p in geom]

    # Fetch elevations in batches
    elevations = []
    for i in range(0, len(points), BATCH_SIZE):
        batch = points[i:i+BATCH_SIZE]
        batch_elevations = fetch_elevations(batch)
        elevations.extend(batch_elevations)
        if i + BATCH_SIZE < len(points):
            time.sleep(1)  # Rate limit

    # Calculate cumulative distance and grade
    if not all(e is not None for e in elevations):
        segment["elevation_error"] = True
        return segment

    # Build elevation profile
    profile = []
    cumulative_dist = 0
    for i, (lat, lon) in enumerate(points):
        if i > 0:
            cumulative_dist += haversine(points[i-1][0], points[i-1][1], lat, lon)
        profile.append({
            "lat": lat,
            "lon": lon,
            "elevation_m": elevations[i],
            "dist_m": cumulative_dist,
        })

    segment["elevation_profile"] = profile

    # Calculate overall stats
    start_ele = elevations[0]
    end_ele = elevations[-1]
    max_ele = max(elevations)
    min_ele = min(elevations)

    # Calculate climbing (sum of positive elevation changes)
    total_climb = 0
    total_descent = 0
    for i in range(1, len(elevations)):
        diff = elevations[i] - elevations[i-1]
        if diff > 0:
            total_climb += diff
        else:
            total_descent += abs(diff)

    total_dist = cumulative_dist
    net_gain = end_ele - start_ele
    avg_grade = (net_gain / total_dist * 100) if total_dist > 0 else 0

    # Calculate max grade over 100m windows
    max_grade = 0
    window_dist = 100  # meters
    for i in range(len(profile)):
        # Find point ~100m ahead
        start_dist = profile[i]["dist_m"]
        start_ele = profile[i]["elevation_m"]
        for j in range(i+1, len(profile)):
            seg_dist = profile[j]["dist_m"] - start_dist
            if seg_dist >= window_dist:
                seg_gain = profile[j]["elevation_m"] - start_ele
                seg_grade = (seg_gain / seg_dist * 100) if seg_dist > 0 else 0
                max_grade = max(max_grade, abs(seg_grade))
                break

    segment["stats"] = {
        "start_ele_m": round(start_ele, 1),
        "end_ele_m": round(end_ele, 1),
        "max_ele_m": round(max_ele, 1),
        "min_ele_m": round(min_ele, 1),
        "total_climb_m": round(total_climb, 1),
        "total_descent_m": round(total_descent, 1),
        "net_gain_m": round(net_gain, 1),
        "total_dist_m": round(total_dist, 1),
        "avg_grade_pct": round(avg_grade, 1),
        "max_grade_pct": round(max_grade, 1),
    }

    return segment

def main():
    # Load candidates
    candidates_file = Path(__file__).parent / "philly_climb_candidates.json"
    with open(candidates_file) as f:
        candidates = json.load(f)

    print("Fetching elevation data for Philly climb candidates...")
    print(f"API: {API_URL}")
    print()

    # Process each road's best segment
    processed = {}
    for road_name, segments in candidates.items():
        print(f"Processing {road_name}...")
        # Take just the first (longest) segment
        segment = segments[0]
        print(f"  {segment['name']} - {len(segment['geometry'])} points")

        processed_seg = process_segment(segment)

        if "stats" in processed_seg:
            stats = processed_seg["stats"]
            print(f"  -> {stats['total_climb_m']}m climb, {stats['avg_grade_pct']:.1f}% avg, {stats['max_grade_pct']:.1f}% max")
            processed[road_name] = processed_seg
        else:
            print(f"  -> SKIPPED (elevation error)")

        time.sleep(1.5)  # Rate limit between roads

    print()
    print("="*80)
    print(f"Processed {len(processed)} climbs with elevation data")

    # Save results
    output_file = Path(__file__).parent / "philly_climbs_with_elevation.json"
    with open(output_file, "w") as f:
        json.dump(processed, f, indent=2)
    print(f"Saved to {output_file}")

    # Print summary
    print()
    print("CLIMB SUMMARY (sorted by total climb):")
    print("-"*60)
    climbs = [(name, seg["stats"]) for name, seg in processed.items() if "stats" in seg]
    climbs.sort(key=lambda x: x[1]["total_climb_m"], reverse=True)
    for name, stats in climbs:
        print(f"{name:20s} {stats['total_climb_m']:5.0f}m climb, {stats['avg_grade_pct']:5.1f}% avg, {stats['max_grade_pct']:5.1f}% max")

if __name__ == "__main__":
    main()
