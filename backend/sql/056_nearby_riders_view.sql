-- Migration: 056_nearby_riders_view.sql
-- Description: Enhanced nearby riders view for leaderboard motivation context
-- Date: 2026-01-26
--
-- Provides configurable window for showing riders above/below a user's position.
-- Useful for motivation: "You're 5 seconds behind rank 42, and 2 seconds ahead of rank 44"

-- =============================================================================
-- ENHANCED NEARBY RIDERS FUNCTION
-- Separate counts for above/below the user
-- =============================================================================

CREATE OR REPLACE FUNCTION get_nearby_riders(
    p_vault_signature TEXT,
    p_wallet TEXT,
    p_above INTEGER DEFAULT 3,
    p_below INTEGER DEFAULT 3
) RETURNS TABLE (
    rank INTEGER,
    wallet TEXT,
    best_time_seconds INTEGER,
    avg_power_w INTEGER,
    total_completions INTEGER,
    achieved_at TIMESTAMPTZ,
    gap_seconds INTEGER,
    is_user BOOLEAN,
    time_behind_user INTEGER,
    time_ahead_of_user INTEGER
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
      AND vc.wallet = p_wallet
      AND vc.best_time_seconds IS NOT NULL;

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
        (r.wallet = p_wallet) as is_user,
        -- time_behind_user: positive means user needs to improve by this many seconds to beat them
        -- Only set for riders ahead of user (negative gap)
        CASE
            WHEN r.best_time_seconds < user_time THEN (user_time - r.best_time_seconds)::INTEGER
            ELSE NULL
        END as time_behind_user,
        -- time_ahead_of_user: positive means user is faster by this many seconds
        -- Only set for riders behind user (positive gap)
        CASE
            WHEN r.best_time_seconds > user_time THEN (r.best_time_seconds - user_time)::INTEGER
            ELSE NULL
        END as time_ahead_of_user
    FROM ranked r
    WHERE r.rnk >= GREATEST(1, user_rank - p_above)
      AND r.rnk <= LEAST(total_count, user_rank + p_below)
    ORDER BY r.rnk;
END;
$$ LANGUAGE plpgsql STABLE;

COMMENT ON FUNCTION get_nearby_riders IS
'Get riders near a user''s position with configurable window.
Returns gap_seconds (time difference from user), time_behind_user (how much faster
the other rider is), and time_ahead_of_user (how much slower the other rider is).';

-- =============================================================================
-- MOTIVATION CONTEXT FUNCTION
-- Returns a single row with user rank + motivation message
-- =============================================================================

CREATE OR REPLACE FUNCTION get_leaderboard_motivation(
    p_vault_signature TEXT,
    p_wallet TEXT
) RETURNS TABLE (
    user_rank INTEGER,
    total_riders INTEGER,
    percentile NUMERIC,
    best_time_seconds INTEGER,
    is_top_10 BOOLEAN,
    time_to_next_rank INTEGER,
    time_gap_from_behind INTEGER,
    next_rank_wallet TEXT,
    behind_rank_wallet TEXT,
    motivation_message TEXT
) AS $$
DECLARE
    v_user_rank INTEGER;
    v_user_time INTEGER;
    v_total INTEGER;
    v_percentile NUMERIC;
    v_next_time INTEGER;
    v_behind_time INTEGER;
    v_next_wallet TEXT;
    v_behind_wallet TEXT;
    v_message TEXT;
BEGIN
    -- Get user's rank and time
    SELECT ur.user_rank, ur.total_riders, ur.percentile
    INTO v_user_rank, v_total, v_percentile
    FROM get_vault_user_rank(p_vault_signature, p_wallet) ur;

    IF v_user_rank IS NULL THEN
        RETURN;
    END IF;

    -- Get user's best time
    SELECT vc.best_time_seconds INTO v_user_time
    FROM vault_completions vc
    WHERE vc.vault_signature = p_vault_signature
      AND vc.wallet = p_wallet;

    -- Get the rider immediately ahead (lower rank)
    IF v_user_rank > 1 THEN
        SELECT vc.wallet, vc.best_time_seconds
        INTO v_next_wallet, v_next_time
        FROM vault_completions vc
        WHERE vc.vault_signature = p_vault_signature
          AND vc.best_time_seconds IS NOT NULL
          AND vc.best_time_seconds < v_user_time
        ORDER BY vc.best_time_seconds DESC
        LIMIT 1;
    END IF;

    -- Get the rider immediately behind (higher rank)
    SELECT vc.wallet, vc.best_time_seconds
    INTO v_behind_wallet, v_behind_time
    FROM vault_completions vc
    WHERE vc.vault_signature = p_vault_signature
      AND vc.best_time_seconds IS NOT NULL
      AND vc.best_time_seconds > v_user_time
    ORDER BY vc.best_time_seconds ASC
    LIMIT 1;

    -- Build motivation message
    IF v_user_rank = 1 THEN
        -- User has KOM
        IF v_behind_time IS NOT NULL THEN
            v_message := format('You hold the KOM! Your lead: %s seconds', v_behind_time - v_user_time);
        ELSE
            v_message := 'You hold the KOM!';
        END IF;
    ELSIF v_user_rank <= 10 THEN
        -- User in top 10 (earning rewards)
        IF v_next_time IS NOT NULL THEN
            v_message := format('Rank #%s - %s seconds behind #%s',
                v_user_rank, v_user_time - v_next_time, v_user_rank - 1);
        ELSE
            v_message := format('Rank #%s', v_user_rank);
        END IF;
    ELSE
        -- User outside top 10
        IF v_next_time IS NOT NULL AND v_behind_time IS NOT NULL THEN
            v_message := format('%s seconds behind #%s, %s seconds ahead of #%s',
                v_user_time - v_next_time, v_user_rank - 1,
                v_behind_time - v_user_time, v_user_rank + 1);
        ELSIF v_next_time IS NOT NULL THEN
            v_message := format('%s seconds behind #%s',
                v_user_time - v_next_time, v_user_rank - 1);
        ELSIF v_behind_time IS NOT NULL THEN
            v_message := format('%s seconds ahead of #%s',
                v_behind_time - v_user_time, v_user_rank + 1);
        ELSE
            v_message := format('Rank #%s', v_user_rank);
        END IF;
    END IF;

    RETURN QUERY SELECT
        v_user_rank as user_rank,
        v_total as total_riders,
        v_percentile as percentile,
        v_user_time as best_time_seconds,
        (v_user_rank <= 10) as is_top_10,
        CASE WHEN v_next_time IS NOT NULL THEN v_user_time - v_next_time ELSE NULL END as time_to_next_rank,
        CASE WHEN v_behind_time IS NOT NULL THEN v_behind_time - v_user_time ELSE NULL END as time_gap_from_behind,
        v_next_wallet as next_rank_wallet,
        v_behind_wallet as behind_rank_wallet,
        v_message as motivation_message;
END;
$$ LANGUAGE plpgsql STABLE;

COMMENT ON FUNCTION get_leaderboard_motivation IS
'Get user''s rank with motivational context showing gaps to nearby riders.';
