#!/usr/bin/env python3
"""
Fetch Strava segment efforts for rides and store in golden_corpus.db.

This script builds the auto-annotated golden corpus by:
1. Listing all cycling activities from the connected Strava account
2. Filtering to rides with meaningful elevation (optionally by geography)
3. Fetching full activity details (including segment_efforts) from the API
4. Storing segment efforts as ground-truth climb annotations
5. Tagging rides by geography based on start_lat/start_lon

Rate limits: 100 requests/15min, 1000/day.
The script respects these limits with automatic backoff.

Usage:
    # Fetch all SEPA rides with >=100m elevation (default)
    python tools/corpus/fetch_strava_segments.py

    # Fetch ALL rides regardless of location
    python tools/corpus/fetch_strava_segments.py --all --min-elevation 50

    # Resume after interruption (skips already-fetched activities)
    python tools/corpus/fetch_strava_segments.py --all --resume

    # Fetch a specific number of rides
    python tools/corpus/fetch_strava_segments.py --limit 50

    # Include all SEPA rides regardless of elevation
    python tools/corpus/fetch_strava_segments.py --min-elevation 0

    # Tag geography on existing rides without re-fetching
    python tools/corpus/fetch_strava_segments.py --tag-geography-only
"""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

try:
    import httpx
except ImportError:
    print("httpx required: pip install httpx")
    sys.exit(1)

DB_PATH = Path(__file__).parent / "golden_corpus.db"

# SEPA bounding box
SEPA_LAT_MIN, SEPA_LAT_MAX = 39.7, 40.3
SEPA_LON_MIN, SEPA_LON_MAX = -75.7, -74.8

# Rate limit settings
REQUESTS_PER_15MIN = 95  # Stay under 100
REQUESTS_PER_DAY = 950   # Stay under 1000
REQUEST_DELAY_S = 1.5    # Base delay between requests

# Geography bounding boxes for ride tagging
# Each entry: (name, lat_min, lat_max, lon_min, lon_max)
GEOGRAPHY_BOXES = [
    ("SEPA",        39.7,  40.3,  -75.7, -74.8),   # Philadelphia / SE Pennsylvania
    ("LA/Malibu",   33.7,  34.4, -118.9, -117.8),   # Los Angeles / Malibu / Santa Monica Mtns
    ("Tucson",      31.8,  32.6, -111.3, -110.5),   # Tucson / Mt Lemmon
    ("Vermont/NH",  42.7,  44.5,  -73.5,  -71.5),   # Vermont / New Hampshire
    ("Georgia/NC",  33.5,  36.0,  -84.5,  -80.5),   # Georgia / North Carolina mountains
    ("Virginia",    37.0,  39.0,  -80.0,  -77.0),   # Virginia / Blue Ridge
    ("Colorado",    38.5,  40.5, -106.5, -104.5),   # Colorado Front Range / ski country
    ("NorCal",      37.0,  38.5, -122.8, -121.5),   # San Francisco / Bay Area / Mt Tam
    ("SoCal",       32.5,  33.7, -117.8, -116.5),   # San Diego / Palomar
    ("NYC/NJ",      40.3,  41.3,  -74.8,  -73.5),   # New York / New Jersey
    ("New England", 41.0,  42.7,  -73.5,  -70.5),   # Connecticut / Massachusetts
]


def classify_geography(lat: float, lon: float) -> str:
    """Classify a lat/lon into a named geography region."""
    if lat is None or lon is None:
        return "Unknown"
    for name, lat_min, lat_max, lon_min, lon_max in GEOGRAPHY_BOXES:
        if lat_min <= lat <= lat_max and lon_min <= lon <= lon_max:
            return name
    return "Other"


def get_strava_credentials() -> Dict[str, str]:
    """Read Strava/Supabase credentials from the local environment."""
    required = [
        "SUPABASE_URL",
        "SUPABASE_SERVICE_KEY",
        "STRAVA_CLIENT_ID",
        "STRAVA_CLIENT_SECRET",
    ]
    env = {name: os.environ.get(name, "").strip() for name in required}
    missing = [name for name, value in env.items() if not value]
    if missing:
        print(f"Missing required environment variable(s): {', '.join(missing)}", file=sys.stderr)
        sys.exit(2)
    return env


def get_access_token(env: Dict[str, str]) -> str:
    """Get a fresh Strava access token via refresh token from Supabase."""
    supabase_headers = {"apikey": env["SUPABASE_SERVICE_KEY"]}
    if not env["SUPABASE_SERVICE_KEY"].startswith("sb_secret_"):
        supabase_headers["Authorization"] = (
            f"Bearer {env['SUPABASE_SERVICE_KEY']}"
        )
    resp = httpx.get(
        f"{env['SUPABASE_URL']}/rest/v1/strava_connections",
        params={"is_active": "eq.true", "select": "refresh_token"},
        headers=supabase_headers,
        timeout=10,
    )
    refresh_token = resp.json()[0]["refresh_token"]

    token_resp = httpx.post(
        "https://www.strava.com/oauth/token",
        data={
            "client_id": env["STRAVA_CLIENT_ID"],
            "client_secret": env["STRAVA_CLIENT_SECRET"],
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
        },
        timeout=10,
    )
    tokens = token_resp.json()
    return tokens["access_token"]


def init_db(db_path: Path) -> sqlite3.Connection:
    """Initialize the golden corpus database."""
    conn = sqlite3.connect(str(db_path))
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("""
        CREATE TABLE IF NOT EXISTS rides (
            activity_id TEXT PRIMARY KEY,
            name TEXT,
            start_date TEXT,
            distance_m REAL,
            elevation_gain_m REAL,
            moving_time_s INTEGER,
            start_lat REAL,
            start_lon REAL,
            end_lat REAL,
            end_lon REAL,
            type TEXT,
            fetched_at TEXT,
            segment_effort_count INTEGER,
            geography TEXT
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS strava_segment_efforts (
            id INTEGER PRIMARY KEY,
            activity_id TEXT NOT NULL,
            segment_id INTEGER NOT NULL,
            segment_name TEXT,
            elapsed_time_s INTEGER,
            moving_time_s INTEGER,
            start_index INTEGER,
            end_index INTEGER,
            distance_m REAL,
            average_grade REAL,
            maximum_grade REAL,
            elevation_high REAL,
            elevation_low REAL,
            elevation_diff REAL,
            climb_category INTEGER,
            start_date TEXT,
            pr_rank INTEGER,
            is_climb INTEGER,
            FOREIGN KEY (activity_id) REFERENCES rides(activity_id)
        )
    """)
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_efforts_activity
        ON strava_segment_efforts(activity_id)
    """)
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_efforts_climb
        ON strava_segment_efforts(is_climb)
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS fetch_progress (
            key TEXT PRIMARY KEY,
            value TEXT
        )
    """)
    conn.commit()

    # Migrate: add geography column if missing (existing DBs)
    cols = [row[1] for row in conn.execute("PRAGMA table_info(rides)").fetchall()]
    if "geography" not in cols:
        conn.execute("ALTER TABLE rides ADD COLUMN geography TEXT")
        conn.commit()

    return conn


def tag_all_geographies(conn: sqlite3.Connection) -> int:
    """Tag all rides with geography based on start_lat/start_lon. Returns count updated."""
    rows = conn.execute(
        "SELECT activity_id, start_lat, start_lon FROM rides"
    ).fetchall()
    updated = 0
    for activity_id, lat, lon in rows:
        geo = classify_geography(lat, lon)
        conn.execute(
            "UPDATE rides SET geography = ? WHERE activity_id = ?",
            (geo, activity_id),
        )
        updated += 1
    conn.commit()
    return updated


def list_all_activities(access_token: str) -> List[Dict]:
    """Paginate through all athlete activities."""
    all_activities = []
    page = 1
    while True:
        resp = httpx.get(
            "https://www.strava.com/api/v3/athlete/activities",
            headers={"Authorization": f"Bearer {access_token}"},
            params={"per_page": 200, "page": page},
            timeout=30,
        )
        if resp.status_code == 429:
            print("  Rate limited on activity list. Waiting 15 minutes...")
            time.sleep(900)
            continue
        resp.raise_for_status()
        batch = resp.json()
        if not batch:
            break
        all_activities.extend(batch)
        print(f"  Page {page}: {len(batch)} activities (total: {len(all_activities)})")
        page += 1
        time.sleep(0.5)
    return all_activities


def filter_sepa_rides(
    activities: List[Dict],
    min_elevation: float = 100.0,
) -> List[Dict]:
    """Filter to SEPA cycling rides with meaningful elevation."""
    return filter_rides(activities, min_elevation=min_elevation, all_geographies=False)


def filter_rides(
    activities: List[Dict],
    min_elevation: float = 100.0,
    all_geographies: bool = False,
) -> List[Dict]:
    """Filter cycling rides, optionally restricting to SEPA bounding box.

    Args:
        activities: Raw Strava activity list.
        min_elevation: Minimum total_elevation_gain in meters.
        all_geographies: If True, include rides from any location.
                         If False, restrict to SEPA bounding box.
    """
    filtered = []
    for a in activities:
        if a.get("type") not in ("Ride", "VirtualRide", "EBikeRide"):
            continue
        latlng = a.get("start_latlng")
        if not latlng or len(latlng) < 2:
            continue
        lat, lon = latlng[0], latlng[1]
        # Geographic filter (skip if --all)
        if not all_geographies:
            if not (SEPA_LAT_MIN <= lat <= SEPA_LAT_MAX and SEPA_LON_MIN <= lon <= SEPA_LON_MAX):
                continue
        if a.get("total_elevation_gain", 0) < min_elevation:
            continue
        filtered.append(a)
    return filtered


def fetch_activity_segments(
    activity_id: int,
    access_token: str,
) -> Optional[Dict]:
    """Fetch full activity detail including segment_efforts."""
    resp = httpx.get(
        f"https://www.strava.com/api/v3/activities/{activity_id}",
        headers={"Authorization": f"Bearer {access_token}"},
        timeout=30,
    )
    if resp.status_code == 429:
        return None  # Rate limited
    if resp.status_code == 404:
        return {"not_found": True}
    resp.raise_for_status()
    return resp.json()


def store_activity(conn: sqlite3.Connection, activity: Dict, efforts: List[Dict]) -> int:
    """Store activity and its segment efforts. Returns climb count."""
    activity_id = str(activity["id"])
    end_latlng = activity.get("end_latlng") or [None, None]
    start_lat = activity.get("start_latlng", [None])[0]
    start_lon = activity.get("start_latlng", [None, None])[1]
    geography = classify_geography(start_lat, start_lon)

    conn.execute(
        """INSERT OR REPLACE INTO rides
           (activity_id, name, start_date, distance_m, elevation_gain_m,
            moving_time_s, start_lat, start_lon, end_lat, end_lon, type,
            fetched_at, segment_effort_count, geography)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            activity_id,
            activity.get("name"),
            activity.get("start_date"),
            activity.get("distance"),
            activity.get("total_elevation_gain"),
            activity.get("moving_time"),
            start_lat,
            start_lon,
            end_latlng[0],
            end_latlng[1],
            activity.get("type"),
            datetime.now(timezone.utc).isoformat(),
            len(efforts),
            geography,
        ),
    )

    # Remove old efforts for this activity (in case of re-fetch)
    conn.execute("DELETE FROM strava_segment_efforts WHERE activity_id = ?", (activity_id,))

    climb_count = 0
    for e in efforts:
        seg = e.get("segment", {})
        elev_high = seg.get("elevation_high") or 0
        elev_low = seg.get("elevation_low") or 0
        elev_diff = elev_high - elev_low
        avg_grade = seg.get("average_grade") or 0
        is_climb = 1 if elev_diff > 10 and avg_grade > 0.5 else 0
        if is_climb:
            climb_count += 1

        conn.execute(
            """INSERT INTO strava_segment_efforts
               (activity_id, segment_id, segment_name, elapsed_time_s,
                moving_time_s, start_index, end_index, distance_m,
                average_grade, maximum_grade, elevation_high, elevation_low,
                elevation_diff, climb_category, start_date, pr_rank, is_climb)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                activity_id,
                seg.get("id"),
                seg.get("name"),
                e.get("elapsed_time"),
                e.get("moving_time"),
                e.get("start_index"),
                e.get("end_index"),
                e.get("distance"),
                seg.get("average_grade"),
                seg.get("maximum_grade"),
                elev_high,
                elev_low,
                elev_diff,
                seg.get("climb_category", 0),
                e.get("start_date"),
                e.get("pr_rank"),
                is_climb,
            ),
        )

    conn.commit()
    return climb_count


def print_geography_report(conn: sqlite3.Connection):
    """Print a breakdown of rides and segments by geography."""
    rows = conn.execute("""
        SELECT
            COALESCE(r.geography, 'Untagged') as geo,
            COUNT(DISTINCT r.activity_id) as rides,
            COUNT(s.id) as total_efforts,
            SUM(CASE WHEN s.is_climb = 1 THEN 1 ELSE 0 END) as climb_efforts,
            COUNT(DISTINCT CASE WHEN s.is_climb = 1 THEN s.segment_id END) as unique_climb_segs
        FROM rides r
        LEFT JOIN strava_segment_efforts s ON r.activity_id = s.activity_id
        GROUP BY r.geography
        ORDER BY rides DESC
    """).fetchall()

    # Also count scorable rides per geography (>=3 quality climb segments)
    scorable_rows = conn.execute("""
        SELECT
            COALESCE(r.geography, 'Untagged') as geo,
            COUNT(DISTINCT r.activity_id) as scorable
        FROM rides r
        JOIN strava_segment_efforts s ON r.activity_id = s.activity_id
        WHERE s.is_climb = 1 AND s.elevation_diff >= 25 AND s.average_grade >= 2.0
        GROUP BY r.geography
        HAVING COUNT(s.id) >= 3
    """).fetchall()
    scorable_map = {row[0]: row[1] for row in scorable_rows}

    # Check which scorable rides have cached streams
    cached_rows = conn.execute("""
        SELECT
            COALESCE(r.geography, 'Untagged') as geo,
            COUNT(DISTINCT r.activity_id) as cached
        FROM rides r
        JOIN strava_segment_efforts s ON r.activity_id = s.activity_id
        JOIN activity_streams st ON r.activity_id = st.activity_id
        WHERE s.is_climb = 1 AND s.elevation_diff >= 25 AND s.average_grade >= 2.0
        GROUP BY r.geography
        HAVING COUNT(s.id) >= 3
    """).fetchall()
    cached_map = {row[0]: row[1] for row in cached_rows}

    print(f"\n{'='*80}")
    print(f"GEOGRAPHY BREAKDOWN")
    print(f"{'='*80}")
    print(f"{'Geography':<16} {'Rides':>6} {'Efforts':>8} {'Climbs':>7} {'Uniq Segs':>10} {'Scorable':>9} {'Cached':>7}")
    print(f"{'-'*16} {'-'*6} {'-'*8} {'-'*7} {'-'*10} {'-'*9} {'-'*7}")
    total_rides = 0
    total_efforts = 0
    total_climbs = 0
    total_scorable = 0
    total_cached = 0
    for geo, rides, efforts, climbs, uniq_segs in rows:
        scorable = scorable_map.get(geo, 0)
        cached = cached_map.get(geo, 0)
        print(f"{geo:<16} {rides:>6} {efforts:>8} {climbs:>7} {uniq_segs:>10} {scorable:>9} {cached:>7}")
        total_rides += rides
        total_efforts += efforts
        total_climbs += climbs
        total_scorable += scorable
        total_cached += cached
    print(f"{'-'*16} {'-'*6} {'-'*8} {'-'*7} {'-'*10} {'-'*9} {'-'*7}")
    print(f"{'TOTAL':<16} {total_rides:>6} {total_efforts:>8} {total_climbs:>7} {'':>10} {total_scorable:>9} {total_cached:>7}")
    print(f"{'='*80}")


def main():
    parser = argparse.ArgumentParser(description="Fetch Strava segment efforts for golden corpus")
    parser.add_argument("--db", default=str(DB_PATH), help="Database path")
    parser.add_argument("--resume", action="store_true", help="Skip already-fetched activities")
    parser.add_argument("--limit", type=int, default=0, help="Max activities to fetch (0=all)")
    parser.add_argument("--min-elevation", type=float, default=100.0, help="Min elevation gain (meters)")
    parser.add_argument("--dry-run", action="store_true", help="List activities without fetching")
    parser.add_argument("--all", action="store_true", dest="all_geographies",
                        help="Fetch ALL rides regardless of location (not just SEPA)")
    parser.add_argument("--tag-geography-only", action="store_true",
                        help="Only tag geography on existing rides, no API calls")
    args = parser.parse_args()

    db_path = Path(args.db)
    conn = init_db(db_path)

    # Tag-only mode: update geography column on existing rides and print report
    if args.tag_geography_only:
        count = tag_all_geographies(conn)
        print(f"Tagged {count} rides with geography.")
        print_geography_report(conn)
        return

    print("Fetching Strava credentials...")
    env = get_strava_credentials()
    print("Refreshing access token...")
    access_token = get_access_token(env)
    print("Authenticated.\n")

    print("Listing all activities...")
    all_activities = list_all_activities(access_token)

    target_rides = filter_rides(
        all_activities,
        min_elevation=args.min_elevation,
        all_geographies=args.all_geographies,
    )
    # Sort oldest first for consistent ordering
    target_rides.sort(key=lambda a: a["start_date"])

    mode_label = "ALL" if args.all_geographies else "SEPA"
    print(f"\n{mode_label} rides with >={args.min_elevation}m elevation: {len(target_rides)}")

    if args.dry_run:
        # Group by geography for dry-run display
        from collections import Counter
        geo_counts: Dict[str, int] = Counter()
        for a in target_rides:
            latlng = a.get("start_latlng", [None, None])
            geo = classify_geography(latlng[0], latlng[1]) if latlng else "Unknown"
            geo_counts[geo] += 1
        print(f"\n  Geography distribution:")
        for geo, cnt in sorted(geo_counts.items(), key=lambda x: -x[1]):
            print(f"    {geo:<16} {cnt:>4} rides")

        print(f"\n  Sample rides:")
        for a in target_rides[:30]:
            latlng = a.get("start_latlng", [None, None])
            geo = classify_geography(latlng[0], latlng[1]) if latlng else "?"
            print(f"  {a['id']:>14d}  {a['start_date'][:10]}  {a.get('name','')[:35]:35s}  "
                  f"elev={a.get('total_elevation_gain',0):4.0f}m  [{geo}]")
        if len(target_rides) > 30:
            print(f"  ... and {len(target_rides) - 30} more")
        return

    # Filter out already-fetched if resuming
    if args.resume:
        existing = set(
            row[0] for row in conn.execute("SELECT activity_id FROM rides").fetchall()
        )
        before = len(target_rides)
        target_rides = [a for a in target_rides if str(a["id"]) not in existing]
        print(f"  Resuming: {before - len(target_rides)} already fetched, {len(target_rides)} remaining")

    if args.limit > 0:
        target_rides = target_rides[:args.limit]
        print(f"  Limited to {args.limit} activities")

    if not target_rides:
        print("\nNo new rides to fetch.")
        # Still tag and report
        tag_all_geographies(conn)
        print_geography_report(conn)
        return

    print(f"\nFetching segment efforts for {len(target_rides)} rides...")
    print(f"Estimated time: {len(target_rides) * REQUEST_DELAY_S / 60:.0f} minutes\n")

    request_count_15min = 0
    request_count_day = 0
    window_start = time.time()
    total_segments = 0
    total_climb_segments = 0

    for idx, activity in enumerate(target_rides):
        activity_id = activity["id"]

        # Rate limit: 15-minute window
        elapsed = time.time() - window_start
        if elapsed >= 900:
            request_count_15min = 0
            window_start = time.time()
        if request_count_15min >= REQUESTS_PER_15MIN:
            wait = 900 - elapsed + 5
            print(f"  Rate limit (15min). Waiting {wait:.0f}s...")
            time.sleep(wait)
            request_count_15min = 0
            window_start = time.time()

        # Rate limit: daily
        if request_count_day >= REQUESTS_PER_DAY:
            print(f"\n  Daily rate limit reached ({request_count_day} requests).")
            print(f"  {len(target_rides) - idx} rides remaining. Run with --resume tomorrow.")
            break

        # Fetch
        result = fetch_activity_segments(activity_id, access_token)
        request_count_15min += 1
        request_count_day += 1

        if result is None:
            # Rate limited by API — back off
            print(f"  [{idx+1}/{len(target_rides)}] {activity_id} — rate limited, waiting 15min...")
            time.sleep(900)
            request_count_15min = 0
            window_start = time.time()
            # Retry once
            result = fetch_activity_segments(activity_id, access_token)
            request_count_15min += 1
            request_count_day += 1
            if result is None:
                print(f"    Still rate limited. Stopping.")
                break

        if result.get("not_found"):
            print(f"  [{idx+1}/{len(target_rides)}] {activity_id} — 404 (skipped)")
            time.sleep(REQUEST_DELAY_S)
            continue

        efforts = result.get("segment_efforts", [])
        climb_count = store_activity(conn, result, efforts)
        total_segments += len(efforts)
        total_climb_segments += climb_count

        name = result.get("name", "")[:35]
        elev = result.get("total_elevation_gain", 0)
        latlng = activity.get("start_latlng", [None, None])
        geo = classify_geography(latlng[0], latlng[1]) if latlng else "?"
        print(f"  [{idx+1}/{len(target_rides)}] {activity_id}  {name:35s}  "
              f"elev={elev:4.0f}m  segs={len(efforts):3d}  climbs={climb_count:2d}  [{geo}]")

        time.sleep(REQUEST_DELAY_S)

    # Tag geography on all rides (including pre-existing ones that may lack it)
    tag_all_geographies(conn)

    # Summary
    ride_count = conn.execute("SELECT COUNT(*) FROM rides").fetchone()[0]
    effort_count = conn.execute("SELECT COUNT(*) FROM strava_segment_efforts").fetchone()[0]
    climb_effort_count = conn.execute(
        "SELECT COUNT(*) FROM strava_segment_efforts WHERE is_climb = 1"
    ).fetchone()[0]
    unique_segments = conn.execute(
        "SELECT COUNT(DISTINCT segment_id) FROM strava_segment_efforts WHERE is_climb = 1"
    ).fetchone()[0]

    print(f"\n{'='*60}")
    print(f"GOLDEN CORPUS SUMMARY")
    print(f"{'='*60}")
    print(f"Rides fetched:           {ride_count}")
    print(f"Total segment efforts:   {effort_count}")
    print(f"Climb segment efforts:   {climb_effort_count}")
    print(f"Unique climb segments:   {unique_segments}")
    print(f"Database:                {db_path}")
    print(f"{'='*60}")

    # Geography report
    print_geography_report(conn)


if __name__ == "__main__":
    main()
