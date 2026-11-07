-- Tile-based attestation infrastructure
-- Phase 1: Activity tile samples and wallet tile history

-- Activity tile samples: GPS samples quantized to H3 tiles with metrics
CREATE TABLE IF NOT EXISTS activity_tile_samples (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    activity_id UUID NOT NULL,
    t INTEGER NOT NULL,
    tile_id TEXT NOT NULL,
    elevation_m FLOAT,
    power_w FLOAT,
    hr_bpm INTEGER,
    speed_mps FLOAT,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    CONSTRAINT fk_activity_tile_samples_ride
        FOREIGN KEY (activity_id) REFERENCES rides(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_tile_samples_activity ON activity_tile_samples(activity_id, t);
CREATE INDEX IF NOT EXISTS idx_tile_samples_tile ON activity_tile_samples(tile_id);

COMMENT ON TABLE activity_tile_samples IS 'GPS samples quantized to H3 tiles with performance metrics';
COMMENT ON COLUMN activity_tile_samples.activity_id IS 'Reference to the ride/activity';
COMMENT ON COLUMN activity_tile_samples.t IS 'Seconds since ride start';
COMMENT ON COLUMN activity_tile_samples.tile_id IS 'H3 index as string representing geographic tile';
COMMENT ON COLUMN activity_tile_samples.elevation_m IS 'Elevation in meters at this sample';
COMMENT ON COLUMN activity_tile_samples.power_w IS 'Power in watts at this sample';
COMMENT ON COLUMN activity_tile_samples.hr_bpm IS 'Heart rate in beats per minute at this sample';
COMMENT ON COLUMN activity_tile_samples.speed_mps IS 'Speed in meters per second at this sample';

-- Wallet tile history: Track which tiles each wallet has visited
CREATE TABLE IF NOT EXISTS wallet_tile_history (
    wallet TEXT NOT NULL,
    tile_id TEXT NOT NULL,
    first_visited_at TIMESTAMPTZ DEFAULT NOW(),
    visit_count INTEGER DEFAULT 1,
    last_visited_at TIMESTAMPTZ,
    PRIMARY KEY (wallet, tile_id)
);

CREATE INDEX IF NOT EXISTS idx_wallet_tile_history_wallet ON wallet_tile_history(wallet);

COMMENT ON TABLE wallet_tile_history IS 'Tracks unique tiles visited by each wallet for territory claims';
COMMENT ON COLUMN wallet_tile_history.wallet IS 'Solana wallet address';
COMMENT ON COLUMN wallet_tile_history.tile_id IS 'H3 index as string representing geographic tile';
COMMENT ON COLUMN wallet_tile_history.first_visited_at IS 'First time this wallet visited this tile';
COMMENT ON COLUMN wallet_tile_history.visit_count IS 'Number of times this wallet has visited this tile';
COMMENT ON COLUMN wallet_tile_history.last_visited_at IS 'Most recent time this wallet visited this tile';
