-- Migration: 047_full_leaderboard.sql
-- Description: Store ALL completion times per user per vault for full leaderboard view
-- Date: 2025-01-26
--
-- Problem: Currently only top 10 is shown. Users outside top 10 can't see their rank.
-- Solution: Extend vault_completions to track personal bests and enable full ranking.

-- =============================================================================
-- EXTEND VAULT_COMPLETIONS TABLE
-- Add columns to track personal best times and completion counts
-- =============================================================================

-- Add best_time tracking columns (personal best per user per vault)
ALTER TABLE vault_completions
    ADD COLUMN IF NOT EXISTS best_time_seconds INTEGER,
    ADD COLUMN IF NOT EXISTS best_time_achieved_at TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS total_completions INTEGER DEFAULT 1,
    ADD COLUMN IF NOT EXISTS avg_power_w INTEGER;

-- Index for ranking queries (only rank users who have a valid best time)
CREATE INDEX IF NOT EXISTS idx_vault_completions_ranking
ON vault_completions(vault_signature, best_time_seconds)
WHERE best_time_seconds IS NOT NULL;

-- Index for wallet position lookups
CREATE INDEX IF NOT EXISTS idx_vault_completions_wallet_vault
ON vault_completions(wallet, vault_signature);

COMMENT ON COLUMN vault_completions.best_time_seconds IS 'Personal best time for this vault (fastest ever)';
COMMENT ON COLUMN vault_completions.best_time_achieved_at IS 'When the personal best was achieved';
COMMENT ON COLUMN vault_completions.total_completions IS 'Total number of times this user completed this vault';
COMMENT ON COLUMN vault_completions.avg_power_w IS 'Average power for the best effort';

-- =============================================================================
-- HELPER FUNCTIONS
-- =============================================================================

-- Function to get user's rank and percentile for a vault
CREATE OR REPLACE FUNCTION get_vault_user_rank(
    p_vault_signature TEXT,
    p_wallet TEXT
) RETURNS TABLE (
    user_rank INTEGER,
    total_riders INTEGER,
    percentile NUMERIC
) AS $$
DECLARE
    user_best_time INTEGER;
BEGIN
    -- Get user's best time
    SELECT vc.best_time_seconds INTO user_best_time
    FROM vault_completions vc
    WHERE vc.vault_signature = p_vault_signature
      AND vc.wallet = p_wallet
      AND vc.best_time_seconds IS NOT NULL;

    IF user_best_time IS NULL THEN
        RETURN;
    END IF;

    RETURN QUERY
    WITH ranked AS (
        SELECT
            vc.wallet,
            vc.best_time_seconds,
            ROW_NUMBER() OVER (ORDER BY vc.best_time_seconds ASC) as rnk
        FROM vault_completions vc
        WHERE vc.vault_signature = p_vault_signature
          AND vc.best_time_seconds IS NOT NULL
    ),
    totals AS (
        SELECT COUNT(*)::INTEGER as total_count FROM ranked
    )
    SELECT
        r.rnk::INTEGER as user_rank,
        t.total_count as total_riders,
        ROUND((r.rnk::NUMERIC / t.total_count) * 100, 1) as percentile
    FROM ranked r
    CROSS JOIN totals t
    WHERE r.wallet = p_wallet;
END;
$$ LANGUAGE plpgsql STABLE;

COMMENT ON FUNCTION get_vault_user_rank IS 'Get user rank, total riders, and percentile for a vault';

-- Function to get user's position with nearby riders (context)
CREATE OR REPLACE FUNCTION get_vault_position_with_context(
    p_vault_signature TEXT,
    p_wallet TEXT,
    p_context_size INTEGER DEFAULT 2
) RETURNS TABLE (
    rank INTEGER,
    wallet TEXT,
    best_time_seconds INTEGER,
    avg_power_w INTEGER,
    total_completions INTEGER,
    achieved_at TIMESTAMPTZ,
    gap_seconds INTEGER,
    is_user BOOLEAN
) AS $$
DECLARE
    user_rank INTEGER;
    user_time INTEGER;
    total_count INTEGER;
BEGIN
    -- Get user's rank and time
    SELECT vc.best_time_seconds, ur.user_rank, ur.total_riders
    INTO user_time, user_rank, total_count
    FROM vault_completions vc
    CROSS JOIN LATERAL get_vault_user_rank(p_vault_signature, p_wallet) ur
    WHERE vc.vault_signature = p_vault_signature
      AND vc.wallet = p_wallet;

    IF user_rank IS NULL THEN
        RETURN;
    END IF;

    RETURN QUERY
    WITH ranked AS (
        SELECT
            vc.wallet,
            vc.best_time_seconds,
            vc.avg_power_w,
            vc.total_completions,
            vc.best_time_achieved_at,
            ROW_NUMBER() OVER (ORDER BY vc.best_time_seconds ASC) as rnk
        FROM vault_completions vc
        WHERE vc.vault_signature = p_vault_signature
          AND vc.best_time_seconds IS NOT NULL
    )
    SELECT
        r.rnk::INTEGER as rank,
        r.wallet,
        r.best_time_seconds,
        r.avg_power_w,
        r.total_completions,
        r.best_time_achieved_at as achieved_at,
        (r.best_time_seconds - user_time)::INTEGER as gap_seconds,
        (r.wallet = p_wallet) as is_user
    FROM ranked r
    WHERE r.rnk >= GREATEST(1, user_rank - p_context_size)
      AND r.rnk <= LEAST(total_count, user_rank + p_context_size)
    ORDER BY r.rnk;
END;
$$ LANGUAGE plpgsql STABLE;

COMMENT ON FUNCTION get_vault_position_with_context IS 'Get user position with nearby riders for context display';

-- Function to get full leaderboard (paginated)
CREATE OR REPLACE FUNCTION get_vault_full_leaderboard(
    p_vault_signature TEXT,
    p_limit INTEGER DEFAULT 100,
    p_offset INTEGER DEFAULT 0
) RETURNS TABLE (
    rank INTEGER,
    wallet TEXT,
    best_time_seconds INTEGER,
    avg_power_w INTEGER,
    total_completions INTEGER,
    achieved_at TIMESTAMPTZ,
    is_top_10 BOOLEAN
) AS $$
BEGIN
    RETURN QUERY
    WITH ranked AS (
        SELECT
            vc.wallet,
            vc.best_time_seconds,
            vc.avg_power_w,
            vc.total_completions,
            vc.best_time_achieved_at,
            ROW_NUMBER() OVER (ORDER BY vc.best_time_seconds ASC) as rnk
        FROM vault_completions vc
        WHERE vc.vault_signature = p_vault_signature
          AND vc.best_time_seconds IS NOT NULL
    )
    SELECT
        r.rnk::INTEGER as rank,
        r.wallet,
        r.best_time_seconds,
        r.avg_power_w,
        r.total_completions,
        r.best_time_achieved_at as achieved_at,
        (r.rnk <= 10) as is_top_10
    FROM ranked r
    ORDER BY r.rnk
    LIMIT p_limit
    OFFSET p_offset;
END;
$$ LANGUAGE plpgsql STABLE;

COMMENT ON FUNCTION get_vault_full_leaderboard IS 'Get paginated full leaderboard for a vault';

-- Function to get total unique riders for a vault
CREATE OR REPLACE FUNCTION get_vault_total_riders(
    p_vault_signature TEXT
) RETURNS INTEGER AS $$
BEGIN
    RETURN (
        SELECT COUNT(*)::INTEGER
        FROM vault_completions
        WHERE vault_signature = p_vault_signature
          AND best_time_seconds IS NOT NULL
    );
END;
$$ LANGUAGE plpgsql STABLE;

COMMENT ON FUNCTION get_vault_total_riders IS 'Get count of unique riders who completed this vault with a valid time';

-- =============================================================================
-- UPDATE RECORD_COMPLETION TO TRACK PERSONAL BESTS
-- Enhanced version that maintains best_time_seconds
-- =============================================================================

CREATE OR REPLACE FUNCTION record_vault_completion_with_best_time(
    p_vault_signature TEXT,
    p_wallet TEXT,
    p_activity_id TEXT,
    p_time_seconds INTEGER DEFAULT NULL,
    p_avg_power_w INTEGER DEFAULT NULL
) RETURNS TABLE (
    is_new_pr BOOLEAN,
    previous_best INTEGER,
    new_best INTEGER,
    total_completions INTEGER
) AS $$
DECLARE
    existing_record RECORD;
    is_new_personal_best BOOLEAN := FALSE;
    prev_best INTEGER;
BEGIN
    -- Get existing record for this user/vault combination
    SELECT vc.best_time_seconds, vc.total_completions
    INTO existing_record
    FROM vault_completions vc
    WHERE vc.vault_signature = p_vault_signature
      AND vc.wallet = p_wallet;

    IF FOUND THEN
        prev_best := existing_record.best_time_seconds;

        -- Check if this is a new personal best
        IF p_time_seconds IS NOT NULL AND
           (existing_record.best_time_seconds IS NULL OR p_time_seconds < existing_record.best_time_seconds) THEN
            is_new_personal_best := TRUE;
        END IF;

        -- Update existing record
        UPDATE vault_completions
        SET
            total_completions = COALESCE(vault_completions.total_completions, 1) + 1,
            best_time_seconds = CASE
                WHEN is_new_personal_best THEN p_time_seconds
                ELSE vault_completions.best_time_seconds
            END,
            best_time_achieved_at = CASE
                WHEN is_new_personal_best THEN now()
                ELSE vault_completions.best_time_achieved_at
            END,
            avg_power_w = CASE
                WHEN is_new_personal_best THEN p_avg_power_w
                ELSE vault_completions.avg_power_w
            END,
            -- Also update most recent completion info
            activity_id = p_activity_id,
            time_seconds = p_time_seconds,
            completed_at = now()
        WHERE vault_completions.vault_signature = p_vault_signature
          AND vault_completions.wallet = p_wallet;

        RETURN QUERY
        SELECT
            is_new_personal_best as is_new_pr,
            prev_best as previous_best,
            CASE WHEN is_new_personal_best THEN p_time_seconds ELSE prev_best END as new_best,
            existing_record.total_completions + 1 as total_completions;
    ELSE
        -- Insert new record
        INSERT INTO vault_completions (
            vault_signature, wallet, activity_id, time_seconds, completed_at,
            best_time_seconds, best_time_achieved_at, total_completions, avg_power_w
        ) VALUES (
            p_vault_signature, p_wallet, p_activity_id, p_time_seconds, now(),
            p_time_seconds, CASE WHEN p_time_seconds IS NOT NULL THEN now() ELSE NULL END, 1, p_avg_power_w
        );

        RETURN QUERY
        SELECT
            (p_time_seconds IS NOT NULL) as is_new_pr,
            NULL::INTEGER as previous_best,
            p_time_seconds as new_best,
            1 as total_completions;
    END IF;
END;
$$ LANGUAGE plpgsql;

COMMENT ON FUNCTION record_vault_completion_with_best_time IS 'Record completion and track personal best time';

-- =============================================================================
-- BACKFILL EXISTING DATA
-- Populate best_time_seconds from existing time_seconds for users without it
-- =============================================================================

-- Backfill: Set best_time_seconds to time_seconds for records that don't have it
UPDATE vault_completions
SET
    best_time_seconds = time_seconds,
    best_time_achieved_at = COALESCE(completed_at, created_at),
    total_completions = 1
WHERE best_time_seconds IS NULL
  AND time_seconds IS NOT NULL;

-- For users with multiple completions, calculate the actual best time
WITH best_times AS (
    SELECT
        wallet,
        vault_signature,
        MIN(time_seconds) as actual_best,
        COUNT(*) as completion_count
    FROM vault_completions
    WHERE time_seconds IS NOT NULL
    GROUP BY wallet, vault_signature
    HAVING COUNT(*) > 1
)
UPDATE vault_completions vc
SET
    best_time_seconds = bt.actual_best,
    total_completions = bt.completion_count
FROM best_times bt
WHERE vc.wallet = bt.wallet
  AND vc.vault_signature = bt.vault_signature;
