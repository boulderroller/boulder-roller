-- Add GPS start/end coordinates to patterns_climb for GPS-gated vault matching.
-- These coordinates come from the tile sample at the effort start/end indices.
-- Used by find_best_vault_match() which applies a 150m proximity gate.

ALTER TABLE patterns_climb ADD COLUMN IF NOT EXISTS start_lat DOUBLE PRECISION;
ALTER TABLE patterns_climb ADD COLUMN IF NOT EXISTS start_lon DOUBLE PRECISION;
ALTER TABLE patterns_climb ADD COLUMN IF NOT EXISTS end_lat DOUBLE PRECISION;
ALTER TABLE patterns_climb ADD COLUMN IF NOT EXISTS end_lon DOUBLE PRECISION;

COMMENT ON COLUMN patterns_climb.start_lat IS 'Latitude at effort start (for GPS-gated vault matching)';
COMMENT ON COLUMN patterns_climb.start_lon IS 'Longitude at effort start (for GPS-gated vault matching)';
COMMENT ON COLUMN patterns_climb.end_lat IS 'Latitude at effort end (for GPS-gated vault matching)';
COMMENT ON COLUMN patterns_climb.end_lon IS 'Longitude at effort end (for GPS-gated vault matching)';

-- Also add GPS to indexed_vaults for candidate matching
ALTER TABLE indexed_vaults ADD COLUMN IF NOT EXISTS start_lat DOUBLE PRECISION;
ALTER TABLE indexed_vaults ADD COLUMN IF NOT EXISTS start_lon DOUBLE PRECISION;

COMMENT ON COLUMN indexed_vaults.start_lat IS 'Latitude at vault climb start (for GPS proximity matching)';
COMMENT ON COLUMN indexed_vaults.start_lon IS 'Longitude at vault climb start (for GPS proximity matching)';
