#!/usr/bin/env python3
"""
Prefetch and cache Strava activity streams for golden corpus scoring.

Downloads time/latlng/altitude/watts/heartrate streams for each scorable
ride and stores them in golden_corpus.db. Once cached, scoring runs
offline with no API calls.

Usage:
    export SUPABASE_URL=...
    export SUPABASE_SERVICE_KEY=...
    export STRAVA_CLIENT_ID=...
    export STRAVA_CLIENT_SECRET=...

    python tools/corpus/prefetch_streams.py           # Fetch all scorable rides
    python tools/corpus/prefetch_streams.py --limit 50  # Fetch first 50
    python tools/corpus/prefetch_streams.py --resume    # Skip already cached
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

try:
    import httpx
except ImportError:
    print("httpx required: pip install httpx")
    sys.exit(1)

GOLDEN_DB = Path(__file__).parent / "golden_corpus.db"
MIN_CLIMB_VERT_M = 25.0
MIN_CLIMB_GRADE_PCT = 2.0
MIN_SEGMENTS = 3
REQUEST_DELAY_S = 1.5
REQUESTS_PER_15MIN = 95


def require_env(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        print(f"Missing required environment variable: {name}", file=sys.stderr)
        sys.exit(2)
    return value


def get_strava_token() -> str:
    supabase_url = require_env("SUPABASE_URL")
    supabase_key = require_env("SUPABASE_SERVICE_KEY")
    strava_client_id = require_env("STRAVA_CLIENT_ID")
    strava_client_secret = require_env("STRAVA_CLIENT_SECRET")

    supabase_headers = {"apikey": supabase_key}
    if not supabase_key.startswith("sb_secret_"):
        supabase_headers["Authorization"] = f"Bearer {supabase_key}"
    resp = httpx.get(
        f"{supabase_url}/rest/v1/strava_connections",
        params={"is_active": "eq.true", "select": "refresh_token"},
        headers=supabase_headers,
        timeout=10,
    )
    token_resp = httpx.post(
        "https://www.strava.com/oauth/token",
        data={
            "client_id": strava_client_id,
            "client_secret": strava_client_secret,
            "grant_type": "refresh_token",
            "refresh_token": resp.json()[0]["refresh_token"],
        },
        timeout=10,
    )
    return token_resp.json()["access_token"]


def main():
    parser = argparse.ArgumentParser(description="Prefetch Strava streams for golden corpus")
    parser.add_argument("--db", default=str(GOLDEN_DB))
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--resume", action="store_true")
    args = parser.parse_args()

    conn = sqlite3.connect(args.db)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS activity_streams (
            activity_id TEXT PRIMARY KEY,
            streams_json TEXT NOT NULL,
            fetched_at TEXT
        )
    """)
    conn.commit()

    # Get scorable rides
    rows = conn.execute("""
        SELECT DISTINCT r.activity_id, r.name, r.elevation_gain_m
        FROM rides r
        JOIN strava_segment_efforts s ON r.activity_id = s.activity_id
        WHERE s.is_climb = 1 AND s.elevation_diff >= ? AND s.average_grade >= ?
        GROUP BY r.activity_id
        HAVING COUNT(s.id) >= ?
        ORDER BY r.elevation_gain_m DESC
    """, (MIN_CLIMB_VERT_M, MIN_CLIMB_GRADE_PCT, MIN_SEGMENTS)).fetchall()

    activity_ids = [(r[0], r[1], r[2]) for r in rows]
    print(f"Scorable rides: {len(activity_ids)}")

    if args.resume:
        cached = set(
            r[0] for r in conn.execute("SELECT activity_id FROM activity_streams").fetchall()
        )
        before = len(activity_ids)
        activity_ids = [(a, n, e) for a, n, e in activity_ids if a not in cached]
        print(f"  Already cached: {before - len(activity_ids)}, remaining: {len(activity_ids)}")

    if args.limit > 0:
        activity_ids = activity_ids[:args.limit]

    print(f"Fetching streams for {len(activity_ids)} rides...")
    print(f"Estimated time: {len(activity_ids) * REQUEST_DELAY_S / 60:.0f} min (plus rate limit pauses)\n")

    access_token = get_strava_token()

    fetched = 0
    failed = 0
    rate_count = 0
    rate_window_start = time.time()

    for idx, (aid, name, elev) in enumerate(activity_ids):
        # Rate limiting
        elapsed = time.time() - rate_window_start
        if elapsed >= 900:
            rate_count = 0
            rate_window_start = time.time()
        if rate_count >= REQUESTS_PER_15MIN:
            wait = 900 - elapsed + 5
            print(f"  Rate limit. Waiting {wait:.0f}s...")
            time.sleep(wait)
            rate_count = 0
            rate_window_start = time.time()

        resp = httpx.get(
            f"https://www.strava.com/api/v3/activities/{aid}/streams",
            headers={"Authorization": f"Bearer {access_token}"},
            params={"keys": "time,latlng,altitude,watts,heartrate,cadence", "key_type": "time"},
            timeout=30,
        )
        rate_count += 1

        if resp.status_code == 429:
            print(f"  [{idx+1}/{len(activity_ids)}] {aid} — rate limited, waiting 15min...")
            time.sleep(900)
            rate_count = 0
            rate_window_start = time.time()
            resp = httpx.get(
                f"https://www.strava.com/api/v3/activities/{aid}/streams",
                headers={"Authorization": f"Bearer {access_token}"},
                params={"keys": "time,latlng,altitude,watts,heartrate,cadence", "key_type": "time"},
                timeout=30,
            )
            rate_count += 1

        if resp.status_code == 200:
            streams_json = json.dumps(resp.json())
            conn.execute(
                "INSERT OR REPLACE INTO activity_streams (activity_id, streams_json, fetched_at) VALUES (?, ?, ?)",
                (aid, streams_json, datetime.now(timezone.utc).isoformat()),
            )
            conn.commit()
            fetched += 1
            label = (name or aid)[:35]
            samples = len(resp.json()[0]["data"]) if resp.json() else 0
            print(f"  [{idx+1}/{len(activity_ids)}] {aid}  {label:35s}  elev={elev or 0:4.0f}m  samples={samples}")
        else:
            failed += 1
            print(f"  [{idx+1}/{len(activity_ids)}] {aid} — HTTP {resp.status_code}")
            if resp.status_code == 403 or resp.status_code == 401:
                print("  Auth error. Refreshing token...")
                access_token = get_strava_token()

        time.sleep(REQUEST_DELAY_S)

    total_cached = conn.execute("SELECT COUNT(*) FROM activity_streams").fetchone()[0]
    print(f"\nDone. Fetched: {fetched}, Failed: {failed}, Total cached: {total_cached}")


if __name__ == "__main__":
    main()
