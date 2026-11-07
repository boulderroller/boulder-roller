-- Strava OAuth connections for activity import
CREATE TABLE IF NOT EXISTS strava_connections (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    wallet TEXT NOT NULL,
    strava_athlete_id BIGINT NOT NULL,
    athlete_username TEXT,
    athlete_firstname TEXT,
    athlete_lastname TEXT,
    access_token TEXT NOT NULL,
    refresh_token TEXT NOT NULL,
    expires_at TIMESTAMPTZ NOT NULL,
    scope TEXT NOT NULL,
    connected_at TIMESTAMPTZ DEFAULT NOW(),
    last_sync_at TIMESTAMPTZ,
    is_active BOOLEAN DEFAULT TRUE,
    UNIQUE(wallet, strava_athlete_id)
);

CREATE INDEX IF NOT EXISTS idx_strava_connections_wallet ON strava_connections(wallet);
CREATE INDEX IF NOT EXISTS idx_strava_connections_athlete ON strava_connections(strava_athlete_id);

-- Track imported activities to avoid duplicates
CREATE TABLE IF NOT EXISTS strava_imported_activities (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    strava_connection_id UUID NOT NULL REFERENCES strava_connections(id) ON DELETE CASCADE,
    strava_activity_id BIGINT NOT NULL,
    activity_id UUID REFERENCES activities(id),
    imported_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(strava_connection_id, strava_activity_id)
);

CREATE INDEX IF NOT EXISTS idx_strava_imported_connection ON strava_imported_activities(strava_connection_id);

COMMENT ON TABLE strava_connections IS 'OAuth connections to Strava for activity import';
COMMENT ON TABLE strava_imported_activities IS 'Tracks which Strava activities have been imported to avoid duplicates';
