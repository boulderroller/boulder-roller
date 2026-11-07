#!/usr/bin/env python3
"""
Import preprocessed OSM road features into the tile_features database.

Usage:
    python tools/import_tile_features.py ../workout-parse/data/roads.json
    python tools/import_tile_features.py roads.json --truncate --batch-size 5000
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, Generator, List

# Add parent to path for app imports
sys.path.insert(0, str(Path(__file__).parent.parent))
from app.config import load_supabase_settings
from app.supabase_client import create_backend_supabase_client


def load_roads_json(path: Path) -> Generator[Dict[str, Any], None, None]:
    """Stream road features from JSON file."""
    print(f"Loading roads from {path}...")
    with path.open("r", encoding="utf-8") as f:
        data = json.load(f)

    if not isinstance(data, list):
        raise ValueError("Expected JSON array of road features")

    print(f"  Found {len(data)} road features")
    for road in data:
        yield road


def import_tile_features(
    path: Path,
    truncate: bool = False,
    batch_size: int = 1000,
    named_only: bool = True,
) -> None:
    """Import road features and tile mappings into Supabase."""
    settings = load_supabase_settings()
    if not settings:
        raise RuntimeError(
            "Supabase configuration missing: set SUPABASE_URL and service role key"
        )

    client = create_backend_supabase_client(settings.url, settings.service_key)

    # Optionally truncate existing data
    if truncate:
        print("Truncating existing tile_features and road_features...")
        client.table("tile_features").delete().neq("tile_id", "").execute()
        client.table("road_features").delete().neq("id", 0).execute()
        print("  Done")

    # Track stats
    roads_imported = 0
    tiles_imported = 0
    roads_skipped = 0

    # Batch buffers
    road_batch: List[Dict[str, Any]] = []
    tile_batch: List[Dict[str, Any]] = []

    # We need to track road_feature_id mapping since we're doing bulk inserts
    # Use osm_way_id as the key since it's unique
    osm_to_id: Dict[int, int] = {}

    print(f"\nImporting road features (batch_size={batch_size})...")

    for road in load_roads_json(path):
        # Skip unnamed roads if requested
        if named_only and not road.get("name"):
            roads_skipped += 1
            continue

        # Prepare road feature row
        road_row = {
            "osm_way_id": road["osm_way_id"],
            "name": road.get("name"),
            "road_class": road.get("road_class", "Unknown"),
            "grade": road.get("grade"),
            "length_m": road.get("length_m", 0),
            "has_bike_infra": road.get("has_bike_infra", False),
            "surface": road.get("surface"),
        }
        road_batch.append(road_row)

        # Flush road batch if full
        if len(road_batch) >= batch_size:
            _flush_road_batch(client, road_batch, osm_to_id)
            roads_imported += len(road_batch)
            print(f"  Roads: {roads_imported:,} imported, {roads_skipped:,} skipped")
            road_batch = []

    # Flush remaining roads
    if road_batch:
        _flush_road_batch(client, road_batch, osm_to_id)
        roads_imported += len(road_batch)
        print(f"  Roads: {roads_imported:,} imported, {roads_skipped:,} skipped")

    print(f"\nImporting tile mappings...")

    # Second pass: import tile mappings
    for road in load_roads_json(path):
        if named_only and not road.get("name"):
            continue

        osm_way_id = road["osm_way_id"]
        road_feature_id = osm_to_id.get(osm_way_id)
        if road_feature_id is None:
            continue

        h3_cells = road.get("h3_cells", [])
        for tile_id in h3_cells:
            tile_batch.append({
                "tile_id": tile_id,
                "road_feature_id": road_feature_id,
            })

        # Flush tile batch if full
        if len(tile_batch) >= batch_size:
            _flush_tile_batch(client, tile_batch)
            tiles_imported += len(tile_batch)
            if tiles_imported % 50000 == 0:
                print(f"  Tiles: {tiles_imported:,} imported")
            tile_batch = []

    # Flush remaining tiles
    if tile_batch:
        _flush_tile_batch(client, tile_batch)
        tiles_imported += len(tile_batch)

    print(f"\n{'='*50}")
    print(f"Import complete!")
    print(f"  Roads imported:  {roads_imported:,}")
    print(f"  Roads skipped:   {roads_skipped:,}")
    print(f"  Tiles imported:  {tiles_imported:,}")
    print(f"{'='*50}")


def _flush_road_batch(
    client,
    batch: List[Dict[str, Any]],
    osm_to_id: Dict[int, int],
) -> None:
    """Insert road batch and track ID mappings."""
    if not batch:
        return

    # Upsert roads
    response = client.table("road_features").upsert(
        batch,
        on_conflict="osm_way_id"
    ).execute()

    # Fetch the IDs for the roads we just inserted
    osm_ids = [r["osm_way_id"] for r in batch]
    id_response = client.table("road_features").select(
        "id, osm_way_id"
    ).in_("osm_way_id", osm_ids).execute()

    for row in id_response.data:
        osm_to_id[row["osm_way_id"]] = row["id"]


def _flush_tile_batch(client, batch: List[Dict[str, Any]]) -> None:
    """Insert tile batch with conflict handling."""
    if not batch:
        return

    # Use upsert with ignore to handle duplicates
    client.table("tile_features").upsert(
        batch,
        on_conflict="tile_id,road_feature_id"
    ).execute()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Import OSM road features into tile_features database"
    )
    parser.add_argument(
        "json_file",
        type=Path,
        help="Path to roads.json from osm-preprocess",
    )
    parser.add_argument(
        "--truncate",
        action="store_true",
        help="Delete existing data before importing",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=1000,
        help="Batch size for database inserts (default: 1000)",
    )
    parser.add_argument(
        "--include-unnamed",
        action="store_true",
        help="Include roads without names (default: named only)",
    )

    args = parser.parse_args()

    if not args.json_file.exists():
        print(f"Error: File not found: {args.json_file}")
        sys.exit(1)

    import_tile_features(
        args.json_file,
        truncate=args.truncate,
        batch_size=args.batch_size,
        named_only=not args.include_unnamed,
    )


if __name__ == "__main__":
    main()
