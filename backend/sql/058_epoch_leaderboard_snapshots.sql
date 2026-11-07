-- Migration: 058_epoch_leaderboard_snapshots.sql
-- Description: Snapshot leaderboard state at epoch boundary for distribution
-- Date: 2025-01-26
--
-- Problem: Race conditions during epoch distribution. If leaderboard changes
-- while processing distributions, different vaults may see inconsistent state.
--
-- Solution: Capture a point-in-time snapshot of all vault leaderboards at epoch
-- close. Distribution calculations use the snapshot, not live vault_leaderboards.

-- =============================================================================
-- EPOCH LEADERBOARD SNAPSHOTS
-- Point-in-time capture of vault_leaderboards at epoch close
-- =============================================================================

CREATE TABLE IF NOT EXISTS epoch_leaderboard_snapshots (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    epoch INTEGER NOT NULL,
    vault_signature TEXT NOT NULL,
    -- Top 10 entries at snapshot time (immutable)
    entries JSONB NOT NULL,
    -- Snapshot metadata
    snapshot_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    entry_count INTEGER NOT NULL DEFAULT 0,
    -- Reference to distribution for traceability
    distribution_id UUID,
    -- Constraints
    UNIQUE (epoch, vault_signature)
);

CREATE INDEX IF NOT EXISTS idx_epoch_lb_snap_epoch
    ON epoch_leaderboard_snapshots(epoch);
CREATE INDEX IF NOT EXISTS idx_epoch_lb_snap_vault
    ON epoch_leaderboard_snapshots(vault_signature);
CREATE INDEX IF NOT EXISTS idx_epoch_lb_snap_created
    ON epoch_leaderboard_snapshots(snapshot_at DESC);

COMMENT ON TABLE epoch_leaderboard_snapshots IS 'Point-in-time leaderboard state for epoch distributions';
COMMENT ON COLUMN epoch_leaderboard_snapshots.entries IS 'JSON array: [{rank, wallet, best_time_seconds, avg_power_w, achieved_at}]';
COMMENT ON COLUMN epoch_leaderboard_snapshots.distribution_id IS 'Links to vault_distributions for this epoch/vault';

-- =============================================================================
-- SNAPSHOT FUNCTIONS
-- =============================================================================

-- Snapshot a single vault's leaderboard for an epoch
CREATE OR REPLACE FUNCTION snapshot_vault_leaderboard(
    p_epoch INTEGER,
    p_vault_signature TEXT
) RETURNS UUID AS $$
DECLARE
    v_entries JSONB;
    v_count INTEGER;
    v_snapshot_id UUID;
BEGIN
    -- Get current leaderboard state
    SELECT
        COALESCE(jsonb_agg(
            jsonb_build_object(
                'rank', rank,
                'wallet', wallet,
                'best_time_seconds', best_time_seconds,
                'avg_power_w', avg_power_w,
                'achieved_at', achieved_at,
                'completion_id', completion_id
            ) ORDER BY rank
        ), '[]'::jsonb),
        COUNT(*)
    INTO v_entries, v_count
    FROM vault_leaderboards
    WHERE vault_signature = p_vault_signature;

    -- Insert or update snapshot
    INSERT INTO epoch_leaderboard_snapshots (
        epoch, vault_signature, entries, entry_count, snapshot_at
    ) VALUES (
        p_epoch, p_vault_signature, v_entries, v_count, now()
    )
    ON CONFLICT (epoch, vault_signature) DO UPDATE SET
        entries = EXCLUDED.entries,
        entry_count = EXCLUDED.entry_count,
        snapshot_at = now()
    RETURNING id INTO v_snapshot_id;

    RETURN v_snapshot_id;
END;
$$ LANGUAGE plpgsql;

COMMENT ON FUNCTION snapshot_vault_leaderboard IS 'Capture point-in-time leaderboard for epoch distribution';

-- Snapshot all active vaults for an epoch
-- "Active" = has leaderboard entries OR has pending distribution
CREATE OR REPLACE FUNCTION snapshot_all_leaderboards_for_epoch(
    p_epoch INTEGER
) RETURNS TABLE (
    vault_signature TEXT,
    snapshot_id UUID,
    entry_count INTEGER
) AS $$
DECLARE
    v_vault TEXT;
    v_snap_id UUID;
    v_count INTEGER;
BEGIN
    -- Get all vaults with leaderboard entries or pending distributions
    FOR v_vault IN
        SELECT DISTINCT vl.vault_signature
        FROM vault_leaderboards vl
        UNION
        SELECT DISTINCT ed.vault_signature
        FROM epoch_distributions ed
        WHERE ed.epoch = p_epoch AND ed.status = 'pending'
    LOOP
        v_snap_id := snapshot_vault_leaderboard(p_epoch, v_vault);
        SELECT els.entry_count INTO v_count
        FROM epoch_leaderboard_snapshots els
        WHERE els.id = v_snap_id;

        vault_signature := v_vault;
        snapshot_id := v_snap_id;
        entry_count := COALESCE(v_count, 0);
        RETURN NEXT;
    END LOOP;
END;
$$ LANGUAGE plpgsql;

COMMENT ON FUNCTION snapshot_all_leaderboards_for_epoch IS 'Capture all vault leaderboards for epoch distribution';

-- Get snapshot entries for a vault/epoch (for distribution calculations)
CREATE OR REPLACE FUNCTION get_epoch_leaderboard_snapshot(
    p_epoch INTEGER,
    p_vault_signature TEXT
) RETURNS TABLE (
    rank INTEGER,
    wallet TEXT,
    best_time_seconds INTEGER,
    avg_power_w INTEGER,
    achieved_at TIMESTAMPTZ
) AS $$
BEGIN
    RETURN QUERY
    SELECT
        (entry->>'rank')::INTEGER AS rank,
        entry->>'wallet' AS wallet,
        (entry->>'best_time_seconds')::INTEGER AS best_time_seconds,
        (entry->>'avg_power_w')::INTEGER AS avg_power_w,
        (entry->>'achieved_at')::TIMESTAMPTZ AS achieved_at
    FROM epoch_leaderboard_snapshots els,
         jsonb_array_elements(els.entries) AS entry
    WHERE els.epoch = p_epoch
      AND els.vault_signature = p_vault_signature
    ORDER BY (entry->>'rank')::INTEGER;
END;
$$ LANGUAGE plpgsql STABLE;

COMMENT ON FUNCTION get_epoch_leaderboard_snapshot IS 'Get snapshotted leaderboard entries for distribution';

-- Link snapshot to distribution (call after distribution is created)
CREATE OR REPLACE FUNCTION link_snapshot_to_distribution(
    p_epoch INTEGER,
    p_vault_signature TEXT,
    p_distribution_id UUID
) RETURNS VOID AS $$
BEGIN
    UPDATE epoch_leaderboard_snapshots
    SET distribution_id = p_distribution_id
    WHERE epoch = p_epoch AND vault_signature = p_vault_signature;
END;
$$ LANGUAGE plpgsql;

-- =============================================================================
-- EPOCH DISTRIBUTION TRACKING COLUMNS
-- Add snapshot reference to epoch_distributions
-- =============================================================================

ALTER TABLE epoch_distributions
    ADD COLUMN IF NOT EXISTS leaderboard_snapshot_id UUID;

COMMENT ON COLUMN epoch_distributions.leaderboard_snapshot_id IS 'Reference to epoch_leaderboard_snapshots used for this distribution';

-- =============================================================================
-- VALIDATION / AUDIT FUNCTIONS
-- =============================================================================

-- Compare snapshot to live state (for debugging/auditing)
CREATE OR REPLACE FUNCTION compare_snapshot_to_live(
    p_epoch INTEGER,
    p_vault_signature TEXT
) RETURNS TABLE (
    rank INTEGER,
    snapshot_wallet TEXT,
    snapshot_time INTEGER,
    live_wallet TEXT,
    live_time INTEGER,
    status TEXT
) AS $$
BEGIN
    RETURN QUERY
    WITH snapshot AS (
        SELECT
            (entry->>'rank')::INTEGER AS rank,
            entry->>'wallet' AS wallet,
            (entry->>'best_time_seconds')::INTEGER AS best_time_seconds
        FROM epoch_leaderboard_snapshots els,
             jsonb_array_elements(els.entries) AS entry
        WHERE els.epoch = p_epoch
          AND els.vault_signature = p_vault_signature
    ),
    live AS (
        SELECT
            vl.rank,
            vl.wallet,
            vl.best_time_seconds
        FROM vault_leaderboards vl
        WHERE vl.vault_signature = p_vault_signature
    )
    SELECT
        COALESCE(s.rank, l.rank) AS rank,
        s.wallet AS snapshot_wallet,
        s.best_time_seconds AS snapshot_time,
        l.wallet AS live_wallet,
        l.best_time_seconds AS live_time,
        CASE
            WHEN s.wallet IS NULL THEN 'NEW_IN_LIVE'
            WHEN l.wallet IS NULL THEN 'REMOVED_FROM_LIVE'
            WHEN s.wallet != l.wallet THEN 'WALLET_CHANGED'
            WHEN s.best_time_seconds != l.best_time_seconds THEN 'TIME_CHANGED'
            ELSE 'UNCHANGED'
        END AS status
    FROM snapshot s
    FULL OUTER JOIN live l ON s.rank = l.rank
    ORDER BY COALESCE(s.rank, l.rank);
END;
$$ LANGUAGE plpgsql STABLE;

COMMENT ON FUNCTION compare_snapshot_to_live IS 'Compare epoch snapshot to current leaderboard state for auditing';

-- Get epoch snapshot summary stats
CREATE OR REPLACE FUNCTION get_epoch_snapshot_summary(
    p_epoch INTEGER
) RETURNS TABLE (
    total_vaults INTEGER,
    total_entries INTEGER,
    snapshot_range TSTZRANGE,
    vaults_with_full_top10 INTEGER
) AS $$
BEGIN
    RETURN QUERY
    SELECT
        COUNT(*)::INTEGER AS total_vaults,
        SUM(entry_count)::INTEGER AS total_entries,
        tstzrange(MIN(snapshot_at), MAX(snapshot_at)) AS snapshot_range,
        COUNT(*) FILTER (WHERE entry_count = 10)::INTEGER AS vaults_with_full_top10
    FROM epoch_leaderboard_snapshots
    WHERE epoch = p_epoch;
END;
$$ LANGUAGE plpgsql STABLE;

COMMENT ON FUNCTION get_epoch_snapshot_summary IS 'Get summary stats for epoch leaderboard snapshots';

-- =============================================================================
-- CLEANUP / RETENTION
-- =============================================================================

-- Delete old snapshots (retention policy: keep 52 weeks)
CREATE OR REPLACE FUNCTION cleanup_old_epoch_snapshots(
    p_retain_epochs INTEGER DEFAULT 52
) RETURNS INTEGER AS $$
DECLARE
    v_current_epoch INTEGER;
    v_deleted INTEGER;
BEGIN
    SELECT get_current_epoch() INTO v_current_epoch;

    DELETE FROM epoch_leaderboard_snapshots
    WHERE epoch < (v_current_epoch - p_retain_epochs);

    GET DIAGNOSTICS v_deleted = ROW_COUNT;
    RETURN v_deleted;
END;
$$ LANGUAGE plpgsql;

COMMENT ON FUNCTION cleanup_old_epoch_snapshots IS 'Remove snapshots older than retention period (default 52 epochs/1 year)';
