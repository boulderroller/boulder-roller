-- Migration: 088_fix_leaderboard_sync_notifications.sql
-- Description: Repair post-smoke projection sync and wallet notification drift
-- Date: 2026-04-20

-- =============================================================================
-- LEADERBOARD SYNC READ MODEL
-- =============================================================================
-- `get_vaults_needing_sync` is a projection-audit helper only. It must not be
-- used to push DB state back on-chain, but admin/background verification still
-- needs it to return a stable shape. Some live schemas expose `signature_hex`
-- as CHAR/VARCHAR, while the function declares TEXT; cast explicitly so
-- Supabase RPC does not fail with a return-type mismatch.

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
        iv.id::BIGINT AS vault_id,
        iv.signature_hex::TEXT AS vault_signature,
        MAX(vl.achieved_at)::TIMESTAMPTZ AS leaderboard_updated_at,
        iv.last_onchain_sync_at::TIMESTAMPTZ AS last_sync_at
    FROM indexed_vaults iv
    INNER JOIN vault_leaderboards vl ON vl.vault_signature = iv.signature_hex
    WHERE
        (iv.last_onchain_sync_at IS NULL
         OR iv.last_onchain_sync_at < (
             SELECT MAX(vl2.achieved_at)
             FROM vault_leaderboards vl2
             WHERE vl2.vault_signature = iv.signature_hex
         ))
        AND (p_since IS NULL OR vl.achieved_at >= p_since)
    GROUP BY iv.id, iv.signature_hex, iv.last_onchain_sync_at
    ORDER BY MAX(vl.achieved_at) DESC;
END;
$$ LANGUAGE plpgsql STABLE;

COMMENT ON FUNCTION get_vaults_needing_sync IS
'Projection-audit helper: finds legacy leaderboard cache rows that need chain/indexer verification; never a DB-to-chain repair source';

-- =============================================================================
-- WALLET NOTIFICATIONS
-- =============================================================================
-- Leaderboard/payout notifications are wallet-addressed. The original social
-- table required user_id, but migration 055 added wallet-based notifications
-- without relaxing that NOT NULL constraint. That caused RPC inserts with a
-- wallet and no user_id to fail. Keep the row valid if either identity is set.

ALTER TABLE IF EXISTS notifications
    ALTER COLUMN user_id DROP NOT NULL;

ALTER TABLE IF EXISTS notifications
    DROP CONSTRAINT IF EXISTS notifications_user_or_wallet_check;

ALTER TABLE IF EXISTS notifications
    ADD CONSTRAINT notifications_user_or_wallet_check
    CHECK (user_id IS NOT NULL OR wallet IS NOT NULL);
