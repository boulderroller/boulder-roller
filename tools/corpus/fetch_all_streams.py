#!/usr/bin/env python3
"""
Fetch ALL missing Strava streams for the golden corpus.

Unlike prefetch_streams.py, this fetches streams for EVERY ride
regardless of segment effort data. Fetches in chronological order
(oldest first) with --resume support.

Usage:
    export STRAVA_CLIENT_ID=...
    export STRAVA_CLIENT_SECRET=...
    export SUPABASE_SERVICE_KEY=sb_secret_...
    python tools/corpus/fetch_all_streams.py --resume
    python tools/corpus/fetch_all_streams.py --resume --limit 100
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
REQUEST_DELAY_S = 1.5
REQUESTS_PER_15MIN = 95

SB_URL = "https://qzkqjevawthyboymqrle.supabase.co"


def require_env(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        print(f"Missing required environment variable: {name}", file=sys.stderr)
        sys.exit(2)
    return value


def get_strava_token() -> str:
    strava_client_id = require_env("STRAVA_CLIENT_ID")
    strava_client_secret = require_env("STRAVA_CLIENT_SECRET")
    sb_key = (
        os.environ.get("SUPABASE_SERVICE_KEY", "").strip()
        or os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "").strip()
    )
    if not sb_key:
        print(
            "Missing required environment variable: SUPABASE_SERVICE_KEY "
            "(or legacy SUPABASE_SERVICE_ROLE_KEY)",
            file=sys.stderr,
        )
        sys.exit(2)

    supabase_headers = {"apikey": sb_key}
    if not sb_key.startswith("sb_secret_"):
        supabase_headers["Authorization"] = f"Bearer {sb_key}"
    resp = httpx.get(
        f"{SB_URL}/rest/v1/strava_connections",
        params={"is_active": "eq.true", "select": "refresh_token"},
        headers=supabase_headers,
        timeout=10,
    )
    refresh_token = resp.json()[0]["refresh_token"]

    token_resp = httpx.post(
        "https://www.strava.com/oauth/token",
        data={
            "client_id": strava_client_id,
            "client_secret": strava_client_secret,
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
        },
        timeout=10,
    )
    result = token_resp.json()
    if "access_token" not in result:
        print(f"Token error: {result}")
        sys.exit(1)
    return result["access_token"]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", default=str(GOLDEN_DB))
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--resume", action="store_true", default=True)
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

    # Get ALL rides, not just scorable ones
    cached = set(
        r[0] for r in conn.execute("SELECT activity_id FROM activity_streams").fetchall()
    )

    rows = conn.execute("""
        SELECT activity_id, name, elevation_gain_m, start_date
        FROM rides
        ORDER BY start_date ASC
    """).fetchall()

    missing = [(r[0], r[1], r[2], r[3]) for r in rows if r[0] not in cached]

    print(f"Total rides: {len(rows)}")
    print(f"Already cached: {len(cached)}")
    print(f"Missing: {len(missing)}")

    if args.limit > 0:
        missing = missing[:args.limit]

    print(f"Fetching: {len(missing)}")
    est_min = len(missing) * REQUEST_DELAY_S / 60
    est_pauses = len(missing) // REQUESTS_PER_15MIN
    print(f"Estimated: ~{est_min + est_pauses * 15:.0f} min total\n")

    access_token = get_strava_token()

    fetched = 0
    failed = 0
    rate_count = 0
    rate_window_start = time.time()

    for idx, (aid, name, elev, date) in enumerate(missing):
        # Rate limiting
        elapsed = time.time() - rate_window_start
        if elapsed >= 900:
            rate_count = 0
            rate_window_start = time.time()
        if rate_count >= REQUESTS_PER_15MIN:
            wait = 900 - elapsed + 5
            print(f"  Rate limit pause. Waiting {wait:.0f}s...")
            time.sleep(wait)
            rate_count = 0
            rate_window_start = time.time()

        try:
            resp = httpx.get(
                f"https://www.strava.com/api/v3/activities/{aid}/streams",
                headers={"Authorization": f"Bearer {access_token}"},
                params={
                    "keys": "time,latlng,altitude,watts,heartrate,cadence,distance",
                    "key_type": "time",
                },
                timeout=30,
            )
        except Exception as e:
            print(f"  [{idx+1}/{len(missing)}] {aid} — error: {e}")
            failed += 1
            continue

        rate_count += 1

        if resp.status_code == 429:
            print(f"  [{idx+1}/{len(missing)}] Rate limited — waiting 15min...")
            time.sleep(900)
            rate_count = 0
            rate_window_start = time.time()
            try:
                resp = httpx.get(
                    f"https://www.strava.com/api/v3/activities/{aid}/streams",
                    headers={"Authorization": f"Bearer {access_token}"},
                    params={
                        "keys": "time,latlng,altitude,watts,heartrate,cadence,distance",
                        "key_type": "time",
                    },
                    timeout=30,
                )
            except Exception as e:
                print(f"  [{idx+1}/{len(missing)}] Retry error: {e}")
                failed += 1
                continue
            rate_count += 1

        if resp.status_code == 200:
            data = resp.json()
            streams_json = json.dumps(data)
            conn.execute(
                "INSERT OR REPLACE INTO activity_streams (activity_id, streams_json, fetched_at) VALUES (?, ?, ?)",
                (aid, streams_json, datetime.now(timezone.utc).isoformat()),
            )
            conn.commit()
            fetched += 1

            samples = len(data[0]["data"]) if data else 0
            has_pwr = any(s["type"] == "watts" for s in data) if data else False
            pwr_tag = " [PWR]" if has_pwr else ""
            label = (name or aid)[:30]
            print(
                f"  [{idx+1}/{len(missing)}] {aid}  {(date or '')[:10]}  {label:30s}  "
                f"elev={elev or 0:4.0f}m  samples={samples}{pwr_tag}"
            )
        elif resp.status_code in (401, 403):
            print(f"  [{idx+1}/{len(missing)}] Auth error ({resp.status_code}). Refreshing token...")
            access_token = get_strava_token()
            failed += 1
        else:
            failed += 1
            print(f"  [{idx+1}/{len(missing)}] {aid} — HTTP {resp.status_code}")

        time.sleep(REQUEST_DELAY_S)

    total_cached = conn.execute("SELECT COUNT(*) FROM activity_streams").fetchone()[0]
    print(f"\nDone. Fetched: {fetched}, Failed: {failed}, Total cached: {total_cached}/{len(rows)}")


if __name__ == "__main__":
    main()
