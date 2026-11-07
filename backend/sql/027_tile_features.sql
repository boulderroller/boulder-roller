-- Tile Features Migration
-- Boulder Rollers v2: OSM Road Feature Attribution
--
-- This migration creates tables for tile-to-feature attribution:
-- - tile_features: H3 tile → road names mapping (from OSM preprocessing)
-- - road_features: Full road metadata (name, grade, class, geometry)
--
-- Enables attribution like "Your climb was 85% on Manayunk Wall"

-- =====================================================
-- ROAD_FEATURES TABLE
-- Full road metadata from OSM preprocessing
-- =====================================================

CREATE TABLE IF NOT EXISTS road_features (
    id SERIAL PRIMARY KEY,
    osm_way_id BIGINT NOT NULL UNIQUE,
    name TEXT,                          -- Road name (nullable for unnamed roads)
    road_class TEXT NOT NULL,           -- Primary, Secondary, Tertiary, Residential, Cycleway, etc.
    grade FLOAT,                        -- Average grade percentage (from OSM incline tag)
    length_m FLOAT NOT NULL,            -- Road length in meters
    has_bike_infra BOOLEAN DEFAULT FALSE,  -- Has cycleway/bicycle tags
    surface TEXT,                       -- asphalt, gravel, etc.
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_road_features_name ON road_features(name) WHERE name IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_road_features_class ON road_features(road_class);
CREATE INDEX IF NOT EXISTS idx_road_features_grade ON road_features(grade) WHERE grade IS NOT NULL;

COMMENT ON TABLE road_features IS 'Road metadata from OSM preprocessing';
COMMENT ON COLUMN road_features.osm_way_id IS 'OpenStreetMap way ID';
COMMENT ON COLUMN road_features.road_class IS 'OSM highway classification';
COMMENT ON COLUMN road_features.grade IS 'Average grade percentage (positive = uphill)';


-- =====================================================
-- TILE_FEATURES TABLE
-- H3 tile → road feature mapping (reverse index)
-- =====================================================

CREATE TABLE IF NOT EXISTS tile_features (
    tile_id TEXT NOT NULL,
    road_feature_id INTEGER NOT NULL REFERENCES road_features(id) ON DELETE CASCADE,
    PRIMARY KEY (tile_id, road_feature_id)
);

CREATE INDEX IF NOT EXISTS idx_tile_features_tile ON tile_features(tile_id);
CREATE INDEX IF NOT EXISTS idx_tile_features_road ON tile_features(road_feature_id);

COMMENT ON TABLE tile_features IS 'Maps H3 tiles to road features for ride attribution';
COMMENT ON COLUMN tile_features.tile_id IS 'H3 index (resolution 10)';
COMMENT ON COLUMN tile_features.road_feature_id IS 'Reference to road_features table';


-- =====================================================
-- TILE_ROAD_NAMES VIEW
-- Convenient view for quick tile → road name lookups
-- =====================================================

CREATE OR REPLACE VIEW tile_road_names AS
SELECT
    tf.tile_id,
    rf.name AS road_name,
    rf.road_class,
    rf.grade
FROM tile_features tf
JOIN road_features rf ON tf.road_feature_id = rf.id
WHERE rf.name IS NOT NULL;

COMMENT ON VIEW tile_road_names IS 'Convenience view: tile_id → road names for attribution';


-- =====================================================
-- FUNCTIONS FOR TILE ATTRIBUTION
-- =====================================================

-- Get all road names for a set of tiles
CREATE OR REPLACE FUNCTION get_tile_attribution(tile_ids TEXT[])
RETURNS TABLE (
    road_name TEXT,
    road_class TEXT,
    grade FLOAT,
    tile_count BIGINT,
    coverage_pct FLOAT
) AS $$
BEGIN
    RETURN QUERY
    WITH tile_input AS (
        SELECT unnest(tile_ids) AS tile_id
    ),
    total_tiles AS (
        SELECT COUNT(DISTINCT tile_id) AS total FROM tile_input
    ),
    matched AS (
        SELECT
            rf.name AS road_name,
            rf.road_class,
            rf.grade,
            COUNT(DISTINCT ti.tile_id) AS tile_count
        FROM tile_input ti
        JOIN tile_features tf ON ti.tile_id = tf.tile_id
        JOIN road_features rf ON tf.road_feature_id = rf.id
        WHERE rf.name IS NOT NULL
        GROUP BY rf.name, rf.road_class, rf.grade
    )
    SELECT
        m.road_name,
        m.road_class,
        m.grade,
        m.tile_count,
        (m.tile_count::FLOAT / NULLIF(t.total, 0) * 100)::FLOAT AS coverage_pct
    FROM matched m
    CROSS JOIN total_tiles t
    ORDER BY m.tile_count DESC;
END;
$$ LANGUAGE plpgsql;

COMMENT ON FUNCTION get_tile_attribution IS 'Returns road attribution for a set of H3 tiles with coverage percentages';


-- =====================================================
-- IMPORT HELPER: Bulk insert road features
-- =====================================================

-- This type helps with bulk imports
CREATE TYPE road_feature_import AS (
    osm_way_id BIGINT,
    name TEXT,
    road_class TEXT,
    grade FLOAT,
    length_m FLOAT,
    has_bike_infra BOOLEAN,
    surface TEXT,
    h3_cells TEXT[]  -- Array of H3 cell strings
);

COMMENT ON TYPE road_feature_import IS 'Type for bulk importing road features with their tiles';
