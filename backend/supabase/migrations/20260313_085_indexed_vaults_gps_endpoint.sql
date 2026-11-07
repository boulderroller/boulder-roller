-- ============================================================================
-- 085: Add end_lat/end_lon to indexed_vaults
-- ============================================================================
-- Migration 067 added start_lat/start_lon to indexed_vaults and all four
-- GPS coordinates (start + end) to patterns_climb. The end-point columns
-- were missed on indexed_vaults. GPS-gated vault matching needs both
-- endpoints for the 150m proximity gate (see find_best_vault_match()).
--
-- Migration: 085 (2026-03-13)
-- ============================================================================

-- 1. Add the columns (nullable, matching start_lat/start_lon type)
ALTER TABLE indexed_vaults
    ADD COLUMN IF NOT EXISTS end_lat DOUBLE PRECISION,
    ADD COLUMN IF NOT EXISTS end_lon DOUBLE PRECISION;

COMMENT ON COLUMN indexed_vaults.end_lat IS 'Latitude at vault climb end (for GPS proximity matching)';
COMMENT ON COLUMN indexed_vaults.end_lon IS 'Longitude at vault climb end (for GPS proximity matching)';

-- 2. Backfill from patterns_climb where we have matching signatures.
--    Uses a lateral subquery to pick the most recent non-null end coords
--    for each vault signature, avoiding overwrite with stale data.
UPDATE indexed_vaults iv
SET
    end_lat = pc.end_lat,
    end_lon = pc.end_lon
FROM (
    SELECT DISTINCT ON (signature_hex)
        signature_hex,
        end_lat,
        end_lon
    FROM patterns_climb
    WHERE signature_hex IS NOT NULL
      AND end_lat IS NOT NULL
      AND end_lon IS NOT NULL
    ORDER BY signature_hex, created_at DESC
) pc
WHERE iv.signature_hex = pc.signature_hex
  AND iv.end_lat IS NULL;

-- Refresh PostgREST schema cache so the new columns are writable
-- immediately through the Supabase REST API.
NOTIFY pgrst, 'reload schema';
