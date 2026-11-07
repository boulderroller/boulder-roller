-- =============================================================================
-- 078: User Profile Snapshots
--
-- Captures a snapshot of user's non-immutable processing inputs (weight, FTP)
-- at the time each ride is processed. Without this, replaying a ride months
-- later would use the user's CURRENT weight/FTP, producing different TSS/IF/kcals.
--
-- Creates:
--   1. user_profile_snapshots: Snapshot table with FK to pipeline_versions
--   2. Indexes for lookup by reference and by wallet
--
-- See: E1 Phase 2 — User Profile Snapshots at Processing Time
-- =============================================================================

CREATE TABLE IF NOT EXISTS user_profile_snapshots (
    id              BIGSERIAL PRIMARY KEY,
    wallet          TEXT NOT NULL,

    -- Snapshot of non-immutable inputs at processing time
    weight_kg       NUMERIC,
    ftp_watts       INTEGER,

    -- What triggered this snapshot
    reference_type  TEXT NOT NULL,       -- 'ride' for ride processing
    reference_id    TEXT NOT NULL,        -- ride_id / activity_id

    -- Timestamp
    captured_at     TIMESTAMPTZ NOT NULL DEFAULT now(),

    -- Pipeline version at time of capture
    pipeline_version_id INTEGER REFERENCES pipeline_versions(id)
);

CREATE INDEX IF NOT EXISTS idx_profile_snapshots_ref
    ON user_profile_snapshots(reference_type, reference_id);
CREATE INDEX IF NOT EXISTS idx_profile_snapshots_wallet
    ON user_profile_snapshots(wallet, captured_at DESC);

COMMENT ON TABLE user_profile_snapshots IS
    'Snapshots of user profile inputs (weight, FTP) captured at ride processing time. '
    'Enables deterministic replay: re-processing a ride uses the snapshot values, '
    'not the user''s current profile.';
