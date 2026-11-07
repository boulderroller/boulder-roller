from __future__ import annotations

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[3]
MIGRATION = REPO_ROOT / "backend" / "sql" / "111_canon_climb_registry.sql"


def _migration_sql() -> str:
    return MIGRATION.read_text(encoding="utf-8")


def test_canon_registry_migration_defines_geometry_and_gate_lines() -> None:
    sql = _migration_sql()

    assert "CREATE TABLE IF NOT EXISTS public.canon_climbs" in sql
    assert "centerline_geom geometry(LINESTRING, 4326) NOT NULL" in sql
    assert "corridor_geom geometry(MULTIPOLYGON, 4326) NOT NULL" in sql
    assert "gate_start_line geometry(LINESTRING, 4326) NOT NULL" in sql
    assert "gate_end_line geometry(LINESTRING, 4326) NOT NULL" in sql
    assert "CHECK (ST_NPoints(gate_start_line) = 2)" in sql
    assert "CHECK (ST_NPoints(gate_end_line) = 2)" in sql
    assert "CREATE INDEX IF NOT EXISTS idx_canon_climbs_corridor_geom" in sql


def test_canon_registry_migration_defines_versioning_and_provenance() -> None:
    sql = _migration_sql()

    assert "canon_id uuid" in sql
    assert "version integer NOT NULL DEFAULT 1 CHECK (version >= 1)" in sql
    assert "status IN ('candidate', 'ratified', 'retired')" in sql
    assert "candidate_fingerprint text NOT NULL" in sql
    assert "osm_way_refs bigint[] NOT NULL DEFAULT '{}'" in sql
    assert "odbl_source text NOT NULL DEFAULT 'OpenStreetMap contributors'" in sql
    assert "record_continuity_policy text NOT NULL DEFAULT 'new_record_board'" in sql
    assert "CREATE UNIQUE INDEX IF NOT EXISTS idx_canon_climbs_canon_version" in sql


def test_canon_corridor_cells_match_tile_fast_path_contract() -> None:
    sql = _migration_sql()

    assert "CREATE TABLE IF NOT EXISTS public.canon_corridor_cells" in sql
    assert "h3_resolution smallint NOT NULL DEFAULT 10 CHECK (h3_resolution = 10)" in sql
    assert "tile_id text NOT NULL" in sql
    assert "coverage_role IN ('corridor', 'gate_start', 'gate_end')" in sql
    assert "PRIMARY KEY (canon_climb_id, h3_resolution, tile_id, coverage_role)" in sql
    assert "CREATE INDEX IF NOT EXISTS idx_canon_corridor_cells_resolution_tile" in sql
