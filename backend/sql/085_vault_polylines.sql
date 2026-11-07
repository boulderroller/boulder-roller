-- Add polyline_json to indexed_vaults for GPS template matching.
-- Stores the vault's GPS corridor as a JSON array of [lat, lon] pairs.
-- Used by the template matching engine to detect climbs that elevation
-- detection may miss (noisy altimeter, short climbs below threshold).
--
-- Populated when a vault is created from a detected climb, or backfilled
-- from the first ride's GPS data that matched the vault.

ALTER TABLE indexed_vaults ADD COLUMN IF NOT EXISTS polyline_json TEXT;

COMMENT ON COLUMN indexed_vaults.polyline_json IS
    'JSON array of [lat, lon] coordinate pairs defining the vault GPS corridor for template matching';
