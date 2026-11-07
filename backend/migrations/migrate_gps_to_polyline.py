#!/usr/bin/env python3
"""
Migration script: Move GPS points from gps_points table to rides.gps_track polyline.

This migration:
1. Reads all GPS points for each ride
2. Encodes them as polyline + delta arrays
3. Stores in rides.gps_track JSONB column
4. Optionally deletes from gps_points table

Usage:
    python -m migrations.migrate_gps_to_polyline [--dry-run] [--delete-after]

Run from backend directory.
"""

import asyncio
import os
import sys
import json
import argparse
from datetime import datetime

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from supabase import Client

from app.utils.polyline import encode_gps_track, estimate_size
from app.repositories import get_supabase_client


def get_client() -> Client:
    """Get Supabase client from existing infrastructure."""
    return get_supabase_client()


def fetch_gps_points(client: Client, ride_id: str) -> list:
    """Fetch all GPS points for a ride with pagination."""
    PAGE_SIZE = 1000
    all_points = []
    offset = 0

    while True:
        response = (
            client.table("gps_points")
            .select("sequence_num, timestamp, latitude, longitude, elevation_m, distance_m")
            .eq("ride_id", ride_id)
            .order("sequence_num")
            .range(offset, offset + PAGE_SIZE - 1)
            .execute()
        )
        data = response.data or []
        if not data:
            break
        all_points.extend(data)
        if len(data) < PAGE_SIZE:
            break
        offset += PAGE_SIZE

    return all_points


def update_ride_gps_track(client: Client, ride_id: str, gps_track: dict) -> bool:
    """Update ride with encoded GPS track."""
    try:
        response = (
            client.table("rides")
            .update({"gps_track": gps_track})
            .eq("id", ride_id)
            .execute()
        )
        return len(response.data or []) > 0
    except Exception as e:
        print(f"  ERROR updating ride {ride_id}: {e}")
        return False


def delete_gps_points(client: Client, ride_id: str) -> int:
    """Delete GPS points for a ride after successful migration."""
    try:
        response = (
            client.table("gps_points")
            .delete()
            .eq("ride_id", ride_id)
            .execute()
        )
        return len(response.data or [])
    except Exception as e:
        print(f"  ERROR deleting GPS points for {ride_id}: {e}")
        return 0


def migrate_ride(client: Client, ride_id: str, dry_run: bool = False, delete_after: bool = False) -> dict:
    """Migrate a single ride's GPS data to polyline format."""
    result = {
        "ride_id": ride_id,
        "points": 0,
        "raw_bytes": 0,
        "encoded_bytes": 0,
        "savings_pct": 0,
        "status": "pending",
    }

    # Fetch GPS points
    points = fetch_gps_points(client, ride_id)
    result["points"] = len(points)

    if not points:
        result["status"] = "no_points"
        return result

    # Encode to polyline format
    encoded = encode_gps_track(points)
    size_info = estimate_size(points)

    result["raw_bytes"] = size_info["raw_bytes"]
    result["encoded_bytes"] = size_info["encoded_bytes"]
    result["savings_pct"] = size_info["savings_pct"]

    if dry_run:
        result["status"] = "dry_run"
        return result

    # Update ride with encoded track
    if update_ride_gps_track(client, ride_id, encoded):
        result["status"] = "migrated"

        # Optionally delete old GPS points
        if delete_after:
            deleted = delete_gps_points(client, ride_id)
            result["deleted"] = deleted
            result["status"] = "migrated_and_deleted"
    else:
        result["status"] = "failed"

    return result


def main():
    parser = argparse.ArgumentParser(description="Migrate GPS points to polyline format")
    parser.add_argument("--dry-run", action="store_true", help="Show what would be done without making changes")
    parser.add_argument("--delete-after", action="store_true", help="Delete GPS points after successful migration")
    parser.add_argument("--ride-id", type=str, help="Migrate only a specific ride ID")
    args = parser.parse_args()

    print("=" * 60)
    print("GPS Points to Polyline Migration")
    print("=" * 60)
    print(f"Dry run: {args.dry_run}")
    print(f"Delete after migration: {args.delete_after}")
    print()

    client = get_client()

    # Get rides to migrate
    if args.ride_id:
        ride_ids = [args.ride_id]
    else:
        response = client.table("rides").select("id").execute()
        ride_ids = [r["id"] for r in (response.data or [])]

    print(f"Found {len(ride_ids)} rides to process")
    print()

    # Track totals
    total_points = 0
    total_raw = 0
    total_encoded = 0
    migrated = 0
    failed = 0
    skipped = 0

    for i, ride_id in enumerate(ride_ids, 1):
        print(f"[{i}/{len(ride_ids)}] Processing ride {ride_id}...")

        result = migrate_ride(client, ride_id, args.dry_run, args.delete_after)

        total_points += result["points"]
        total_raw += result["raw_bytes"]
        total_encoded += result["encoded_bytes"]

        status = result["status"]
        if status in ("migrated", "migrated_and_deleted", "dry_run"):
            migrated += 1
            print(f"  ✓ {result['points']} points, {result['raw_bytes']:,}B → {result['encoded_bytes']:,}B ({result['savings_pct']:.1f}% savings)")
        elif status == "no_points":
            skipped += 1
            print(f"  - No GPS points")
        else:
            failed += 1
            print(f"  ✗ {status}")

    # Summary
    print()
    print("=" * 60)
    print("SUMMARY")
    print("=" * 60)
    print(f"Total rides:     {len(ride_ids)}")
    print(f"Migrated:        {migrated}")
    print(f"Skipped:         {skipped}")
    print(f"Failed:          {failed}")
    print()
    print(f"Total points:    {total_points:,}")
    print(f"Raw size:        {total_raw:,} bytes ({total_raw / 1024 / 1024:.1f} MB)")
    print(f"Encoded size:    {total_encoded:,} bytes ({total_encoded / 1024 / 1024:.1f} MB)")

    if total_raw > 0:
        savings = (1 - total_encoded / total_raw) * 100
        print(f"Savings:         {savings:.1f}%")

    if not args.dry_run and args.delete_after:
        print()
        print("GPS points have been deleted after migration.")
        print("Run 'VACUUM gps_points;' to reclaim disk space.")


if __name__ == "__main__":
    main()
