#!/usr/bin/env python3
"""Projection-only DEM elevation-correction backfill for existing rides.

Feature: boulderroller-v2-odmi6.2.1. New uploads get corrected at Phase 1;
this fills the same read-model columns for rides processed before the feature
landed. It reads the stored ``rides.gps_track`` polyline (no file re-parse),
computes the correction, and updates ONLY the ``elevation_correction_*`` /
``elevation_corrected_gain_m`` projection columns. It never touches
``elevation_gain_m``, economics, attestation, patterns, or achievements, so
it is safe to run against production at any time.

Usage (inside the API container):
    python tools/backfill_elevation_correction.py --ride-id <uuid> [--ride-id ...]
    python tools/backfill_elevation_correction.py --recent 50
    python tools/backfill_elevation_correction.py --recent 50 --recorrect
    python tools/backfill_elevation_correction.py --recent 50 --dry-run

By default rides that already carry a correction status are skipped;
``--recorrect`` recomputes them (e.g. after a grid or algorithm upgrade).
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

sys.path.insert(0, str(Path(__file__).parent.parent))

from app.repositories import get_supabase_client  # noqa: E402
from app.services.elevation_correction import (  # noqa: E402
    correct_route_elevation,
    load_dem_grid,
    route_points_from_gps_dicts,
)
from app.utils.polyline import decode_gps_track  # noqa: E402


def _select_columns() -> str:
    return "id,processing_status,elevation_correction_status,elevation_gain_m,gps_track"


def fetch_rides(client: Any, args: argparse.Namespace) -> List[Dict[str, Any]]:
    if args.ride_id:
        rows: List[Dict[str, Any]] = []
        for ride_id in args.ride_id:
            response = (
                client.table("rides")
                .select(_select_columns())
                .eq("id", ride_id)
                .limit(1)
                .execute()
            )
            rows.extend(response.data or [])
        return rows
    response = (
        client.table("rides")
        .select(_select_columns())
        .order("created_at", desc=True)
        .limit(args.recent)
        .execute()
    )
    return response.data or []


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ride-id", action="append", default=None)
    parser.add_argument("--recent", type=int, default=25)
    parser.add_argument("--recorrect", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    dem = load_dem_grid()
    if dem is None:
        print("WARNING: no DEM grid available — corrections will abstain (dem_grid_missing)")

    client = get_supabase_client()
    rides = fetch_rides(client, args)
    print(f"considering {len(rides)} ride(s)")

    updated = corrected = unavailable = skipped = 0
    for ride in rides:
        ride_id = ride.get("id")
        existing_status: Optional[str] = ride.get("elevation_correction_status")
        if existing_status and not args.recorrect:
            skipped += 1
            continue
        points = decode_gps_track(ride.get("gps_track") or {})
        result = correct_route_elevation(route_points_from_gps_dicts(points), dem)
        fields = result.as_ride_fields()
        raw_gain = ride.get("elevation_gain_m")
        print(
            f"  {ride_id}: {result.status} coverage={result.coverage_bps}bps "
            f"corrected_gain={result.elevation_gain_m} raw_gain={raw_gain} "
            f"points={len(points)}"
            + (f" reason={result.reason}" if result.reason else "")
        )
        if result.status == "corrected":
            corrected += 1
        else:
            unavailable += 1
        if args.dry_run:
            continue
        client.table("rides").update(fields).eq("id", str(ride_id)).execute()
        updated += 1

    print(
        f"done: {updated} updated, {corrected} corrected, "
        f"{unavailable} unavailable, {skipped} skipped (already corrected)"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
