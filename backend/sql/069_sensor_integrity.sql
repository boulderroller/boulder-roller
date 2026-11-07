-- Sensor integrity layer for per-activity quality scoring.
-- Implements memo item #8: "Treat data quality as a model input, not cleanup."
-- Stores composite integrity score and sub-scores as JSONB on rides table.

ALTER TABLE rides ADD COLUMN IF NOT EXISTS sensor_integrity JSONB;

COMMENT ON COLUMN rides.sensor_integrity IS 'Per-activity sensor quality report (GPS coverage, elevation plausibility, sampling regularity, composite score)';

-- Index for finding low-integrity rides
CREATE INDEX IF NOT EXISTS idx_rides_low_integrity
    ON rides ((sensor_integrity->>'integrity_score'))
    WHERE sensor_integrity IS NOT NULL;
