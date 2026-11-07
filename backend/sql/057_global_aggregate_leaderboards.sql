-- Migration: 057_global_aggregate_leaderboards.sql
-- Description: Global aggregate leaderboards for KOM counts and earnings rankings
-- Date: 2026-01-26
--
-- Provides platform-wide leaderboards:
-- 1. KOM Count Leaderboard - Users ranked by total number of top-1 positions held
-- 2. Earnings Leaderboard - Users ranked by total DUNG/points earned from leaderboards
--
-- Supports filtering by time period: all-time, this epoch, last 30 days

-- =============================================================================
-- FUNCTION: Global KOM Count Leaderboard
-- Users ranked by total number of rank-1 positions across all vaults
-- =============================================================================

CREATE OR REPLACE FUNCTION get_global_kom_leaderboard(
    p_time_filter TEXT DEFAULT 'all_time',  -- 'all_time', 'this_epoch', 'last_30_days'
    p_limit INTEGER DEFAULT 50,
    p_offset INTEGER DEFAULT 0
) RETURNS TABLE (
    rank BIGINT,
    wallet TEXT,
    kom_count BIGINT,
    podium_count BIGINT,
    top10_count BIGINT,
    total_vaults BIGINT,
    most_recent_kom_at TIMESTAMPTZ
) AS $$
BEGIN
    RETURN QUERY
    WITH filtered_entries AS (
        SELECT
            vl.wallet,
            vl.rank as lb_rank,
            vl.achieved_at
        FROM vault_leaderboards vl
        WHERE (
            p_time_filter = 'all_time'
            OR (p_time_filter = 'this_epoch' AND vl.achieved_at >= date_trunc('week', now()) - interval '1 day')
            OR (p_time_filter = 'last_30_days' AND vl.achieved_at >= now() - interval '30 days')
        )
    ),
    user_stats AS (
        SELECT
            fe.wallet,
            COUNT(*) FILTER (WHERE fe.lb_rank = 1) as kom_count,
            COUNT(*) FILTER (WHERE fe.lb_rank <= 3) as podium_count,
            COUNT(*) as top10_count,
            COUNT(DISTINCT fe.wallet) as total_vaults,
            MAX(fe.achieved_at) FILTER (WHERE fe.lb_rank = 1) as most_recent_kom_at
        FROM filtered_entries fe
        GROUP BY fe.wallet
    )
    SELECT
        ROW_NUMBER() OVER (ORDER BY us.kom_count DESC, us.podium_count DESC, us.top10_count DESC, us.most_recent_kom_at DESC NULLS LAST)::BIGINT as rank,
        us.wallet,
        us.kom_count,
        us.podium_count,
        us.top10_count,
        us.total_vaults,
        us.most_recent_kom_at
    FROM user_stats us
    WHERE us.kom_count > 0  -- Only users with at least one KOM
    ORDER BY us.kom_count DESC, us.podium_count DESC, us.top10_count DESC, us.most_recent_kom_at DESC NULLS LAST
    LIMIT p_limit
    OFFSET p_offset;
END;
$$ LANGUAGE plpgsql STABLE;

COMMENT ON FUNCTION get_global_kom_leaderboard IS
'Get global leaderboard of users ranked by KOM count.
Time filters: all_time, this_epoch, last_30_days.
Tie-breaking: podium_count > top10_count > most_recent_kom_at.';

-- =============================================================================
-- FUNCTION: Global Earnings Leaderboard
-- Users ranked by total points/DUNG earned from leaderboard distributions
-- =============================================================================

CREATE OR REPLACE FUNCTION get_global_earnings_leaderboard(
    p_time_filter TEXT DEFAULT 'all_time',  -- 'all_time', 'this_epoch', 'last_30_days'
    p_limit INTEGER DEFAULT 50,
    p_offset INTEGER DEFAULT 0
) RETURNS TABLE (
    rank BIGINT,
    wallet TEXT,
    total_earnings NUMERIC,
    leaderboard_earnings NUMERIC,
    staking_earnings NUMERIC,
    legend_earnings NUMERIC,
    vaults_with_earnings BIGINT,
    last_earning_at TIMESTAMPTZ
) AS $$
BEGIN
    RETURN QUERY
    WITH filtered_events AS (
        SELECT
            pe.wallet,
            pe.points_delta,
            pe.event_type,
            pe.created_at,
            pe.reference_id
        FROM points_events pe
        WHERE pe.event_type IN ('LEADERBOARD_PAYOUT', 'STAKE_EARNINGS', 'LOCAL_LEGEND_EARNINGS')
          AND pe.points_delta > 0
          AND (
              p_time_filter = 'all_time'
              OR (p_time_filter = 'this_epoch' AND pe.created_at >= date_trunc('week', now()) - interval '1 day')
              OR (p_time_filter = 'last_30_days' AND pe.created_at >= now() - interval '30 days')
          )
    ),
    user_earnings AS (
        SELECT
            fe.wallet,
            SUM(fe.points_delta) as total_earnings,
            SUM(fe.points_delta) FILTER (WHERE fe.event_type = 'LEADERBOARD_PAYOUT') as leaderboard_earnings,
            SUM(fe.points_delta) FILTER (WHERE fe.event_type = 'STAKE_EARNINGS') as staking_earnings,
            SUM(fe.points_delta) FILTER (WHERE fe.event_type = 'LOCAL_LEGEND_EARNINGS') as legend_earnings,
            COUNT(DISTINCT fe.reference_id) as vaults_with_earnings,
            MAX(fe.created_at) as last_earning_at
        FROM filtered_events fe
        GROUP BY fe.wallet
    )
    SELECT
        ROW_NUMBER() OVER (ORDER BY ue.total_earnings DESC, ue.leaderboard_earnings DESC NULLS LAST, ue.last_earning_at DESC NULLS LAST)::BIGINT as rank,
        ue.wallet,
        COALESCE(ue.total_earnings, 0) as total_earnings,
        COALESCE(ue.leaderboard_earnings, 0) as leaderboard_earnings,
        COALESCE(ue.staking_earnings, 0) as staking_earnings,
        COALESCE(ue.legend_earnings, 0) as legend_earnings,
        ue.vaults_with_earnings,
        ue.last_earning_at
    FROM user_earnings ue
    WHERE ue.total_earnings > 0
    ORDER BY ue.total_earnings DESC, ue.leaderboard_earnings DESC NULLS LAST, ue.last_earning_at DESC NULLS LAST
    LIMIT p_limit
    OFFSET p_offset;
END;
$$ LANGUAGE plpgsql STABLE;

COMMENT ON FUNCTION get_global_earnings_leaderboard IS
'Get global leaderboard of users ranked by total vault earnings.
Includes leaderboard payouts, staking earnings, and Local Legend rewards.
Time filters: all_time, this_epoch, last_30_days.';

-- =============================================================================
-- FUNCTION: Count total KOM leaderboard entries
-- =============================================================================

CREATE OR REPLACE FUNCTION count_global_kom_leaderboard(
    p_time_filter TEXT DEFAULT 'all_time'
) RETURNS BIGINT AS $$
DECLARE
    result BIGINT;
BEGIN
    SELECT COUNT(DISTINCT wallet) INTO result
    FROM vault_leaderboards vl
    WHERE vl.rank = 1
      AND (
          p_time_filter = 'all_time'
          OR (p_time_filter = 'this_epoch' AND vl.achieved_at >= date_trunc('week', now()) - interval '1 day')
          OR (p_time_filter = 'last_30_days' AND vl.achieved_at >= now() - interval '30 days')
      );
    RETURN COALESCE(result, 0);
END;
$$ LANGUAGE plpgsql STABLE;

COMMENT ON FUNCTION count_global_kom_leaderboard IS
'Count total unique users with at least one KOM for pagination.';

-- =============================================================================
-- FUNCTION: Count total earnings leaderboard entries
-- =============================================================================

CREATE OR REPLACE FUNCTION count_global_earnings_leaderboard(
    p_time_filter TEXT DEFAULT 'all_time'
) RETURNS BIGINT AS $$
DECLARE
    result BIGINT;
BEGIN
    SELECT COUNT(DISTINCT wallet) INTO result
    FROM points_events pe
    WHERE pe.event_type IN ('LEADERBOARD_PAYOUT', 'STAKE_EARNINGS', 'LOCAL_LEGEND_EARNINGS')
      AND pe.points_delta > 0
      AND (
          p_time_filter = 'all_time'
          OR (p_time_filter = 'this_epoch' AND pe.created_at >= date_trunc('week', now()) - interval '1 day')
          OR (p_time_filter = 'last_30_days' AND pe.created_at >= now() - interval '30 days')
      );
    RETURN COALESCE(result, 0);
END;
$$ LANGUAGE plpgsql STABLE;

COMMENT ON FUNCTION count_global_earnings_leaderboard IS
'Count total unique users with vault earnings for pagination.';

-- =============================================================================
-- FUNCTION: Get user's rank on global KOM leaderboard
-- =============================================================================

CREATE OR REPLACE FUNCTION get_user_global_kom_rank(
    p_wallet TEXT,
    p_time_filter TEXT DEFAULT 'all_time'
) RETURNS TABLE (
    user_rank BIGINT,
    total_users BIGINT,
    kom_count BIGINT,
    podium_count BIGINT,
    top10_count BIGINT,
    percentile NUMERIC
) AS $$
BEGIN
    RETURN QUERY
    WITH filtered_entries AS (
        SELECT
            vl.wallet,
            vl.rank as lb_rank,
            vl.achieved_at
        FROM vault_leaderboards vl
        WHERE (
            p_time_filter = 'all_time'
            OR (p_time_filter = 'this_epoch' AND vl.achieved_at >= date_trunc('week', now()) - interval '1 day')
            OR (p_time_filter = 'last_30_days' AND vl.achieved_at >= now() - interval '30 days')
        )
    ),
    user_stats AS (
        SELECT
            fe.wallet,
            COUNT(*) FILTER (WHERE fe.lb_rank = 1) as kom_count,
            COUNT(*) FILTER (WHERE fe.lb_rank <= 3) as podium_count,
            COUNT(*) as top10_count
        FROM filtered_entries fe
        GROUP BY fe.wallet
    ),
    ranked AS (
        SELECT
            us.wallet,
            us.kom_count,
            us.podium_count,
            us.top10_count,
            ROW_NUMBER() OVER (ORDER BY us.kom_count DESC, us.podium_count DESC, us.top10_count DESC) as rnk
        FROM user_stats us
        WHERE us.kom_count > 0
    ),
    total AS (
        SELECT COUNT(*) as cnt FROM ranked
    )
    SELECT
        r.rnk::BIGINT as user_rank,
        t.cnt::BIGINT as total_users,
        r.kom_count,
        r.podium_count,
        r.top10_count,
        ROUND((1 - r.rnk::NUMERIC / NULLIF(t.cnt, 0)) * 100, 1) as percentile
    FROM ranked r, total t
    WHERE r.wallet = p_wallet;
END;
$$ LANGUAGE plpgsql STABLE;

COMMENT ON FUNCTION get_user_global_kom_rank IS
'Get a user''s rank on the global KOM leaderboard with their stats.';

-- =============================================================================
-- FUNCTION: Get user's rank on global earnings leaderboard
-- =============================================================================

CREATE OR REPLACE FUNCTION get_user_global_earnings_rank(
    p_wallet TEXT,
    p_time_filter TEXT DEFAULT 'all_time'
) RETURNS TABLE (
    user_rank BIGINT,
    total_users BIGINT,
    total_earnings NUMERIC,
    leaderboard_earnings NUMERIC,
    staking_earnings NUMERIC,
    legend_earnings NUMERIC,
    percentile NUMERIC
) AS $$
BEGIN
    RETURN QUERY
    WITH filtered_events AS (
        SELECT
            pe.wallet,
            pe.points_delta,
            pe.event_type
        FROM points_events pe
        WHERE pe.event_type IN ('LEADERBOARD_PAYOUT', 'STAKE_EARNINGS', 'LOCAL_LEGEND_EARNINGS')
          AND pe.points_delta > 0
          AND (
              p_time_filter = 'all_time'
              OR (p_time_filter = 'this_epoch' AND pe.created_at >= date_trunc('week', now()) - interval '1 day')
              OR (p_time_filter = 'last_30_days' AND pe.created_at >= now() - interval '30 days')
          )
    ),
    user_earnings AS (
        SELECT
            fe.wallet,
            SUM(fe.points_delta) as total_earnings,
            SUM(fe.points_delta) FILTER (WHERE fe.event_type = 'LEADERBOARD_PAYOUT') as leaderboard_earnings,
            SUM(fe.points_delta) FILTER (WHERE fe.event_type = 'STAKE_EARNINGS') as staking_earnings,
            SUM(fe.points_delta) FILTER (WHERE fe.event_type = 'LOCAL_LEGEND_EARNINGS') as legend_earnings
        FROM filtered_events fe
        GROUP BY fe.wallet
    ),
    ranked AS (
        SELECT
            ue.wallet,
            COALESCE(ue.total_earnings, 0) as total_earnings,
            COALESCE(ue.leaderboard_earnings, 0) as leaderboard_earnings,
            COALESCE(ue.staking_earnings, 0) as staking_earnings,
            COALESCE(ue.legend_earnings, 0) as legend_earnings,
            ROW_NUMBER() OVER (ORDER BY ue.total_earnings DESC) as rnk
        FROM user_earnings ue
        WHERE ue.total_earnings > 0
    ),
    total AS (
        SELECT COUNT(*) as cnt FROM ranked
    )
    SELECT
        r.rnk::BIGINT as user_rank,
        t.cnt::BIGINT as total_users,
        r.total_earnings,
        r.leaderboard_earnings,
        r.staking_earnings,
        r.legend_earnings,
        ROUND((1 - r.rnk::NUMERIC / NULLIF(t.cnt, 0)) * 100, 1) as percentile
    FROM ranked r, total t
    WHERE r.wallet = p_wallet;
END;
$$ LANGUAGE plpgsql STABLE;

COMMENT ON FUNCTION get_user_global_earnings_rank IS
'Get a user''s rank on the global earnings leaderboard with their stats.';

-- =============================================================================
-- INDEXES: Optimize leaderboard queries
-- =============================================================================

-- Index for KOM queries (rank = 1)
CREATE INDEX IF NOT EXISTS idx_vault_leaderboards_kom
    ON vault_leaderboards(wallet) WHERE rank = 1;

-- Index for podium queries (rank <= 3)
CREATE INDEX IF NOT EXISTS idx_vault_leaderboards_podium
    ON vault_leaderboards(wallet, rank) WHERE rank <= 3;

-- Index for time-filtered queries
CREATE INDEX IF NOT EXISTS idx_vault_leaderboards_achieved_at
    ON vault_leaderboards(achieved_at DESC);

-- Index for points_events earnings queries
CREATE INDEX IF NOT EXISTS idx_points_events_earnings
    ON points_events(wallet, event_type, created_at DESC)
    WHERE event_type IN ('LEADERBOARD_PAYOUT', 'STAKE_EARNINGS', 'LOCAL_LEGEND_EARNINGS');
