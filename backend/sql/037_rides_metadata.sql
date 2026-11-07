-- Add ride metadata columns for social features
-- These columns support ride editing after upload

ALTER TABLE rides
    ADD COLUMN IF NOT EXISTS description TEXT,
    ADD COLUMN IF NOT EXISTS activity_type VARCHAR(50) DEFAULT 'ride',
    ADD COLUMN IF NOT EXISTS visibility VARCHAR(20) DEFAULT 'public',
    ADD COLUMN IF NOT EXISTS comments_enabled BOOLEAN DEFAULT true,
    ADD COLUMN IF NOT EXISTS hide_from_leaderboards BOOLEAN DEFAULT false;

-- Index for visibility filtering
CREATE INDEX IF NOT EXISTS idx_rides_visibility ON rides(visibility);

-- Comments on new columns
COMMENT ON COLUMN rides.description IS 'User-provided ride description';
COMMENT ON COLUMN rides.activity_type IS 'Activity type: ride, virtual_ride, e_ride, etc.';
COMMENT ON COLUMN rides.visibility IS 'Visibility: public, followers, private';
COMMENT ON COLUMN rides.comments_enabled IS 'Whether comments are enabled on this ride';
COMMENT ON COLUMN rides.hide_from_leaderboards IS 'Hide this ride from vault leaderboards';
