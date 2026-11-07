-- Road features from OpenStreetMap for climb detection boundary enrichment.
-- Indexed by H3 resolution-10 tile for fast spatial lookup.
-- Populated by: tools/osm/extract_road_features.py → CSV → COPY

CREATE TABLE IF NOT EXISTS road_features (
    id              BIGSERIAL PRIMARY KEY,
    tile_id         TEXT NOT NULL,
    feature_type    TEXT NOT NULL,  -- 'intersection', 'bridge', 'tunnel', 'road_segment'
    osm_id          BIGINT NOT NULL,
    name            TEXT,
    highway_class   TEXT,
    lat             DOUBLE PRECISION NOT NULL,
    lon             DOUBLE PRECISION NOT NULL,
    road_names      TEXT[],
    degree          SMALLINT,
    tags            JSONB DEFAULT '{}',
    created_at      TIMESTAMPTZ DEFAULT NOW()
);

-- Primary lookup: features in a specific tile
CREATE INDEX idx_road_features_tile ON road_features(tile_id);

-- Filtered lookup: specific feature type in a tile
CREATE INDEX idx_road_features_type_tile ON road_features(feature_type, tile_id);

-- Dedup check: prevent re-importing same OSM data
CREATE UNIQUE INDEX idx_road_features_dedup ON road_features(tile_id, feature_type, osm_id);

-- Feature type constraint
ALTER TABLE road_features ADD CONSTRAINT chk_road_features_type
    CHECK (feature_type IN ('intersection', 'bridge', 'tunnel', 'road_segment'));

COMMENT ON TABLE road_features IS 'OSM road features for climb detection boundary enrichment. See docs/rfcs/CLIMB_DETECTION_V3_ARCHITECTURE.md';
