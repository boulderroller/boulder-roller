-- Climb Road Attribution Migration
-- Boulder Rollers v2: Add road name attribution to climb patterns
--
-- Adds road attribution fields to patterns_climb table for OSM road naming

-- Add road attribution columns to patterns_climb
ALTER TABLE patterns_climb ADD COLUMN IF NOT EXISTS road_name TEXT;
ALTER TABLE patterns_climb ADD COLUMN IF NOT EXISTS road_grade FLOAT;
ALTER TABLE patterns_climb ADD COLUMN IF NOT EXISTS road_coverage_pct FLOAT;
ALTER TABLE patterns_climb ADD COLUMN IF NOT EXISTS attribution_summary TEXT;

-- Index for road name lookups
CREATE INDEX IF NOT EXISTS idx_climb_patterns_road_name ON patterns_climb(road_name) WHERE road_name IS NOT NULL;

COMMENT ON COLUMN patterns_climb.road_name IS 'Primary road name from OSM attribution (e.g., Manayunk Wall)';
COMMENT ON COLUMN patterns_climb.road_grade IS 'Average road grade from OSM data';
COMMENT ON COLUMN patterns_climb.road_coverage_pct IS 'Percentage of climb on primary road';
COMMENT ON COLUMN patterns_climb.attribution_summary IS 'Human-readable attribution summary';
