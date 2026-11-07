-- Backfill GPS coordinates on indexed_vaults from patterns_climb.
-- On-chain vaults don't carry GPS, so we derive coordinates from
-- the first climb pattern that matched each vault's signature.

-- Add end coordinates (start_lat/start_lon already added in 067)
ALTER TABLE indexed_vaults ADD COLUMN IF NOT EXISTS end_lat DOUBLE PRECISION;
ALTER TABLE indexed_vaults ADD COLUMN IF NOT EXISTS end_lon DOUBLE PRECISION;

COMMENT ON COLUMN indexed_vaults.end_lat IS 'Latitude at vault climb end (from first matching patterns_climb)';
COMMENT ON COLUMN indexed_vaults.end_lon IS 'Longitude at vault climb end (from first matching patterns_climb)';

-- Backfill: take GPS from the earliest matching patterns_climb record
-- that has non-null coordinates. Uses signature_hex for matching.
UPDATE indexed_vaults iv
SET
    start_lat = COALESCE(iv.start_lat, pc.start_lat),
    start_lon = COALESCE(iv.start_lon, pc.start_lon),
    end_lat   = COALESCE(iv.end_lat,   pc.end_lat),
    end_lon   = COALESCE(iv.end_lon,   pc.end_lon)
FROM (
    SELECT DISTINCT ON (signature_hex)
        signature_hex, start_lat, start_lon, end_lat, end_lon
    FROM patterns_climb
    WHERE signature_hex IS NOT NULL
      AND start_lat IS NOT NULL
      AND start_lon IS NOT NULL
    ORDER BY signature_hex, created_at ASC
) pc
WHERE iv.signature_hex = pc.signature_hex
  AND (iv.start_lat IS NULL OR iv.end_lat IS NULL);
