-- Privacy Zones: GPS redaction areas (Strava-clone approach)
-- Users can define zones where GPS data is hidden from public view.
-- Radius options: 200m, 400m, 800m, 1600m (matching Strava)

CREATE TABLE IF NOT EXISTS privacy_zones (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    -- Center point of the privacy zone
    latitude DOUBLE PRECISION NOT NULL,
    longitude DOUBLE PRECISION NOT NULL,
    -- Radius in meters (200, 400, 800, 1600)
    radius_m INTEGER NOT NULL CHECK (radius_m IN (200, 400, 800, 1600)),
    -- Optional label for user reference (e.g., "Home", "Office")
    label TEXT,
    -- Metadata
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- Indexes
CREATE INDEX IF NOT EXISTS idx_privacy_zones_user ON privacy_zones(user_id);
CREATE INDEX IF NOT EXISTS idx_privacy_zones_location ON privacy_zones(latitude, longitude);

-- Update timestamp trigger
CREATE OR REPLACE FUNCTION update_privacy_zone_timestamp()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS privacy_zone_update_timestamp ON privacy_zones;
CREATE TRIGGER privacy_zone_update_timestamp
    BEFORE UPDATE ON privacy_zones
    FOR EACH ROW
    EXECUTE FUNCTION update_privacy_zone_timestamp();

-- RLS Policies
ALTER TABLE privacy_zones ENABLE ROW LEVEL SECURITY;

-- Service role can do everything (backend uses service role)
CREATE POLICY privacy_zones_service_all ON privacy_zones
    FOR ALL USING (true) WITH CHECK (true);

COMMENT ON TABLE privacy_zones IS 'GPS redaction zones for user privacy (like Strava)';
COMMENT ON COLUMN privacy_zones.radius_m IS 'Zone radius: 200, 400, 800, or 1600 meters';
COMMENT ON COLUMN privacy_zones.label IS 'User-friendly label (Home, Office, etc.)';
