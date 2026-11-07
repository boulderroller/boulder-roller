-- Migration: 047_leaderboard_sync.sql
-- Description: Track leaderboard synchronization between DB and on-chain state
-- Date: 2025-01-26

-- =============================================================================
-- LEADERBOARD SYNC TRACKING
-- Tracks sync state between DB vault_leaderboards and on-chain VaultLeaderboard PDAs
-- =============================================================================

-- Add sync tracking columns to indexed_vaults
ALTER TABLE indexed_vaults
    ADD COLUMN IF NOT EXISTS last_onchain_sync_at TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS onchain_sync_tx TEXT,
    ADD COLUMN IF NOT EXISTS onchain_sync_status TEXT DEFAULT 'pending';

COMMENT ON COLUMN indexed_vaults.last_onchain_sync_at IS 'Last time DB leaderboard was synced to on-chain';
COMMENT ON COLUMN indexed_vaults.onchain_sync_tx IS 'Transaction signature of last sync';
COMMENT ON COLUMN indexed_vaults.onchain_sync_status IS 'pending, synced, failed, or skipped';

-- Create index for finding vaults needing sync
CREATE INDEX IF NOT EXISTS idx_indexed_vaults_sync_status
    ON indexed_vaults(onchain_sync_status)
    WHERE onchain_sync_status != 'synced';

-- =============================================================================
-- LEADERBOARD SYNC LOG
-- Audit trail of all sync operations
-- =============================================================================

CREATE TABLE IF NOT EXISTS leaderboard_sync_log (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    vault_id BIGINT NOT NULL,
    vault_signature TEXT NOT NULL,
    epoch INTEGER,
    -- Snapshot of state at sync time
    db_state JSONB,          -- DB leaderboard entries at sync time
    onchain_state JSONB,     -- On-chain state before sync (if readable)
    -- Sync result
    tx_signature TEXT,
    status TEXT NOT NULL,    -- synced, failed, skipped, mismatch_detected
    error_message TEXT,
    entries_synced INTEGER DEFAULT 0,
    -- Metadata
    sync_type TEXT DEFAULT 'epoch',  -- epoch, manual, verification
    triggered_by TEXT,       -- system, admin:<user_id>, api
    created_at TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_leaderboard_sync_log_vault
    ON leaderboard_sync_log(vault_id);
CREATE INDEX IF NOT EXISTS idx_leaderboard_sync_log_epoch
    ON leaderboard_sync_log(epoch);
CREATE INDEX IF NOT EXISTS idx_leaderboard_sync_log_status
    ON leaderboard_sync_log(status);
CREATE INDEX IF NOT EXISTS idx_leaderboard_sync_log_created
    ON leaderboard_sync_log(created_at DESC);

COMMENT ON TABLE leaderboard_sync_log IS 'Audit trail of DB to on-chain leaderboard sync operations';
COMMENT ON COLUMN leaderboard_sync_log.db_state IS 'Snapshot of vault_leaderboards at sync time';
COMMENT ON COLUMN leaderboard_sync_log.onchain_state IS 'VaultLeaderboard PDA state before sync';
COMMENT ON COLUMN leaderboard_sync_log.sync_type IS 'epoch=automatic at epoch end, manual=admin triggered, verification=check only';

-- =============================================================================
-- HELPER FUNCTIONS
-- =============================================================================

-- Get vaults that need sync (have activity since last sync)
CREATE OR REPLACE FUNCTION get_vaults_needing_sync(
    p_since TIMESTAMPTZ DEFAULT NULL
) RETURNS TABLE (
    vault_id BIGINT,
    vault_signature TEXT,
    leaderboard_updated_at TIMESTAMPTZ,
    last_sync_at TIMESTAMPTZ
) AS $$
BEGIN
    RETURN QUERY
    SELECT DISTINCT
        iv.id AS vault_id,
        iv.signature_hex AS vault_signature,
        MAX(vl.achieved_at) AS leaderboard_updated_at,
        iv.last_onchain_sync_at AS last_sync_at
    FROM indexed_vaults iv
    INNER JOIN vault_leaderboards vl ON vl.vault_signature = iv.signature_hex
    WHERE
        -- Either never synced or synced before latest leaderboard update
        (iv.last_onchain_sync_at IS NULL
         OR iv.last_onchain_sync_at < (
             SELECT MAX(vl2.achieved_at)
             FROM vault_leaderboards vl2
             WHERE vl2.vault_signature = iv.signature_hex
         ))
        -- Optional: only vaults with activity since a certain time
        AND (p_since IS NULL OR vl.achieved_at >= p_since)
    GROUP BY iv.id, iv.signature_hex, iv.last_onchain_sync_at
    ORDER BY MAX(vl.achieved_at) DESC;
END;
$$ LANGUAGE plpgsql STABLE;

COMMENT ON FUNCTION get_vaults_needing_sync IS 'Find vaults where DB leaderboard is newer than last on-chain sync';

-- Mark vault as synced
CREATE OR REPLACE FUNCTION mark_vault_synced(
    p_vault_id BIGINT,
    p_tx_signature TEXT DEFAULT NULL
) RETURNS VOID AS $$
BEGIN
    UPDATE indexed_vaults
    SET
        last_onchain_sync_at = now(),
        onchain_sync_tx = COALESCE(p_tx_signature, onchain_sync_tx),
        onchain_sync_status = 'synced'
    WHERE id = p_vault_id;
END;
$$ LANGUAGE plpgsql;

-- Get leaderboard as JSON for sync logging
CREATE OR REPLACE FUNCTION get_leaderboard_snapshot(
    p_vault_signature TEXT
) RETURNS JSONB AS $$
BEGIN
    RETURN (
        SELECT COALESCE(jsonb_agg(
            jsonb_build_object(
                'rank', rank,
                'wallet', wallet,
                'best_time_seconds', best_time_seconds,
                'avg_power_w', avg_power_w,
                'achieved_at', achieved_at
            ) ORDER BY rank
        ), '[]'::jsonb)
        FROM vault_leaderboards
        WHERE vault_signature = p_vault_signature
    );
END;
$$ LANGUAGE plpgsql STABLE;

COMMENT ON FUNCTION get_leaderboard_snapshot IS 'Get vault leaderboard as JSON for sync logging';
