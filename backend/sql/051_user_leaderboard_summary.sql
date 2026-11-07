-- Migration: 051_user_leaderboard_summary.sql
-- Description: Add functions for cross-vault leaderboard summary per user
-- Date: 2025-01-26
--
-- Provides efficient queries to:
-- 1. Get all leaderboard positions for a user across all vaults
-- 2. Get aggregated stats (KOM count, podium count, etc.)

-- =============================================================================
-- FUNCTION: Get all leaderboard positions for a user
-- =============================================================================

CREATE OR REPLACE FUNCTION get_user_leaderboard_positions(p_wallet TEXT)
RETURNS TABLE(
    vault_id BIGINT,
    vault_name TEXT,
    vault_signature TEXT,
    rank INTEGER,
    best_time_seconds INTEGER,
    is_kom BOOLEAN,
    total_riders BIGINT,
    percentile NUMERIC,
    last_achieved_at TIMESTAMPTZ
) AS $$
BEGIN
    RETURN QUERY
    SELECT
        v.id AS vault_id,
        v.name AS vault_name,
        l.vault_signature,
        l.rank,
        l.best_time_seconds,
        (l.rank = 1) AS is_kom,
        (SELECT COUNT(DISTINCT vc.wallet) FROM vault_completions vc
         WHERE vc.vault_signature = l.vault_signature) AS total_riders,
        ROUND((1 - (l.rank::NUMERIC / NULLIF(
            (SELECT COUNT(DISTINCT vc.wallet) FROM vault_completions vc
             WHERE vc.vault_signature = l.vault_signature), 0
        ))) * 100, 1) AS percentile,
        l.achieved_at AS last_achieved_at
    FROM vault_leaderboards l
    JOIN indexed_vaults v ON v.signature_hex = l.vault_signature
    WHERE l.wallet = p_wallet
    ORDER BY l.rank ASC, l.achieved_at DESC;
END;
$$ LANGUAGE plpgsql STABLE;

COMMENT ON FUNCTION get_user_leaderboard_positions IS 'Get all top-10 leaderboard positions for a user across all vaults';

-- =============================================================================
-- FUNCTION: Get aggregated leaderboard stats for a user
-- =============================================================================

CREATE OR REPLACE FUNCTION get_user_leaderboard_stats(p_wallet TEXT)
RETURNS TABLE(
    total_positions INTEGER,
    kom_count INTEGER,
    podium_count INTEGER,
    top10_count INTEGER,
    total_vaults_completed INTEGER,
    best_percentile NUMERIC
) AS $$
BEGIN
    RETURN QUERY
    SELECT
        (SELECT COUNT(*) FROM vault_leaderboards WHERE wallet = p_wallet)::INTEGER AS total_positions,
        (SELECT COUNT(*) FROM vault_leaderboards WHERE wallet = p_wallet AND rank = 1)::INTEGER AS kom_count,
        (SELECT COUNT(*) FROM vault_leaderboards WHERE wallet = p_wallet AND rank <= 3)::INTEGER AS podium_count,
        (SELECT COUNT(*) FROM vault_leaderboards WHERE wallet = p_wallet AND rank <= 10)::INTEGER AS top10_count,
        (SELECT COUNT(DISTINCT vault_signature) FROM vault_completions WHERE wallet = p_wallet)::INTEGER AS total_vaults_completed,
        (SELECT MIN(sub.percentile)
         FROM (
             SELECT
                 l.rank::NUMERIC / NULLIF(
                     (SELECT COUNT(DISTINCT vc.wallet) FROM vault_completions vc
                      WHERE vc.vault_signature = l.vault_signature), 0
                 ) * 100 AS percentile
             FROM vault_leaderboards l
             WHERE l.wallet = p_wallet
         ) sub
        ) AS best_percentile;
END;
$$ LANGUAGE plpgsql STABLE;

COMMENT ON FUNCTION get_user_leaderboard_stats IS 'Get aggregated leaderboard statistics for a user (KOMs, podiums, etc.)';

-- =============================================================================
-- INDEX: Optimize leaderboard queries by wallet
-- (Index already exists from 033_vault_economics.sql: idx_vault_leaderboards_wallet)
-- =============================================================================

-- Ensure index exists on vault_completions for wallet lookups
CREATE INDEX IF NOT EXISTS idx_vault_completions_wallet_signature
    ON vault_completions(wallet, vault_signature);
