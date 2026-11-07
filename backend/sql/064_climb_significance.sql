-- Significance scoring columns on patterns_climb.
-- Part of Climb Detection V2 (Phase 3: GPD Bootstrap).
--
-- These columns are populated after climb detection during ride processing.
-- NULL for rides processed before Phase 3 — backfill by re-running scoring.

ALTER TABLE patterns_climb ADD COLUMN IF NOT EXISTS persistence_m REAL;
ALTER TABLE patterns_climb ADD COLUMN IF NOT EXISTS significance_g REAL;
ALTER TABLE patterns_climb ADD COLUMN IF NOT EXISTS significance_percentile REAL;
ALTER TABLE patterns_climb ADD COLUMN IF NOT EXISTS significance_return_period REAL;
ALTER TABLE patterns_climb ADD COLUMN IF NOT EXISTS significance_confidence_tier INT;
ALTER TABLE patterns_climb ADD COLUMN IF NOT EXISTS significance_bootstrapped BOOLEAN DEFAULT FALSE;

COMMENT ON COLUMN patterns_climb.persistence_m IS 'Topological persistence in meters (from v2 detector)';
COMMENT ON COLUMN patterns_climb.significance_g IS 'Conservative GPD significance score 0-1 (higher = more remarkable)';
COMMENT ON COLUMN patterns_climb.significance_percentile IS 'Local percentile (e.g. 92 = top 8% in this area)';
COMMENT ON COLUMN patterns_climb.significance_return_period IS 'Expected return period (e.g. 125 = 1 in 125 climbs)';
COMMENT ON COLUMN patterns_climb.significance_confidence_tier IS '0=empirical, 1=low, 2=moderate, 3=full';
COMMENT ON COLUMN patterns_climb.significance_bootstrapped IS 'True if scored against DEM-bootstrapped terrain cell';
