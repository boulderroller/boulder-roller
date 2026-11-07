-- Migration: 050_tiebreaker.sql
-- Description: Add explicit tie-breaking rules for vault leaderboards
-- Date: 2026-01-26
-- Tie-Breaking Rule: First achiever wins (earlier achieved_at timestamp gets higher rank)
--
-- This migration updates update_vault_leaderboard to:
-- 1. Add explicit tie-breaking based on achieved_at timestamp
-- 2. Accept an optional p_achieved_at parameter for backfills
-- 3. Preserve the time validation logic from migration 048

-- =============================================================================
-- INDEX FOR TIE-BREAKING QUERIES
-- Supports efficient ordering by time, then by achieved_at for ties
-- =============================================================================

CREATE INDEX IF NOT EXISTS idx_vault_leaderboards_tiebreak
ON vault_leaderboards(vault_signature, best_time_seconds, achieved_at);

-- =============================================================================
-- UPDATED LEADERBOARD FUNCTION WITH EXPLICIT TIE-BREAKING
-- Preserves time validation from 048_time_validation.sql
-- =============================================================================

CREATE OR REPLACE FUNCTION update_vault_leaderboard(
    p_vault_signature TEXT,
    p_wallet TEXT,
    p_time_seconds INTEGER,
    p_avg_power_w INTEGER DEFAULT NULL,
    p_completion_id UUID DEFAULT NULL,
    p_achieved_at TIMESTAMPTZ DEFAULT NULL
) RETURNS INTEGER AS $$
DECLARE
    v_min_time INTEGER;
    v_max_time INTEGER;
    v_validation_enabled BOOLEAN;
    v_new_rank INTEGER := NULL;
    v_existing_time INTEGER;
    v_existing_rank INTEGER;
    v_achieved_at TIMESTAMPTZ;
BEGIN
    -- Use provided achieved_at or default to now()
    -- This allows backfills to use original completion timestamps
    v_achieved_at := COALESCE(p_achieved_at, now());

    -- =========================================================================
    -- TIME VALIDATION (preserved from 048_time_validation.sql)
    -- =========================================================================

    -- Get validation bounds from indexed_vaults
    SELECT min_valid_time_s, max_valid_time_s, validation_enabled
    INTO v_min_time, v_max_time, v_validation_enabled
    FROM indexed_vaults
    WHERE signature_hex = p_vault_signature;

    -- Validate time if enabled and bounds are set
    IF v_validation_enabled IS NOT FALSE AND v_min_time IS NOT NULL THEN
        IF p_time_seconds < v_min_time THEN
            RAISE EXCEPTION 'Time too fast: % seconds is below minimum % seconds for this vault',
                p_time_seconds, v_min_time
            USING ERRCODE = 'check_violation',
                  HINT = 'The submitted time appears impossibly fast for this climb.';
        END IF;

        IF p_time_seconds > v_max_time THEN
            RAISE EXCEPTION 'Time too slow: % seconds exceeds maximum % seconds for this vault',
                p_time_seconds, v_max_time
            USING ERRCODE = 'check_violation',
                  HINT = 'The submitted time exceeds the maximum allowed for this climb.';
        END IF;
    END IF;

    -- =========================================================================
    -- CHECK EXISTING ENTRY
    -- =========================================================================

    -- Check if user already has an entry
    SELECT best_time_seconds, rank
    INTO v_existing_time, v_existing_rank
    FROM vault_leaderboards
    WHERE vault_signature = p_vault_signature AND wallet = p_wallet;

    -- If user has existing entry with same or better time, no update needed
    -- (We don't update achieved_at for equal times - incumbent advantage)
    IF FOUND AND v_existing_time <= p_time_seconds THEN
        RETURN v_existing_rank;
    END IF;

    -- =========================================================================
    -- CALCULATE NEW RANK WITH TIE-BREAKING
    -- Tie-breaker: first achiever wins (earlier achieved_at = better rank)
    -- =========================================================================

    -- Count entries with:
    -- 1. Strictly faster times, OR
    -- 2. Same time but earlier achieved_at
    SELECT COUNT(*) + 1
    INTO v_new_rank
    FROM vault_leaderboards
    WHERE vault_signature = p_vault_signature
      AND (
          best_time_seconds < p_time_seconds
          OR (best_time_seconds = p_time_seconds AND achieved_at < v_achieved_at)
      );

    -- =========================================================================
    -- HANDLE RANK > 10
    -- =========================================================================

    -- Check if we even qualify for top 10
    IF v_new_rank > 10 THEN
        -- Check if user has existing entry with worse time (allowing self-improvement)
        IF v_existing_rank IS NOT NULL AND v_existing_time > p_time_seconds THEN
            -- User is improving their own time but still not in top 10
            -- Still update their entry since it's a personal best
            UPDATE vault_leaderboards
            SET best_time_seconds = p_time_seconds,
                avg_power_w = COALESCE(p_avg_power_w, avg_power_w),
                completion_id = COALESCE(p_completion_id, completion_id),
                achieved_at = v_achieved_at
            WHERE vault_signature = p_vault_signature AND wallet = p_wallet;
            RETURN v_existing_rank;
        END IF;

        -- No entry to update and not in top 10
        RETURN NULL;
    END IF;

    -- =========================================================================
    -- UPDATE LEADERBOARD
    -- =========================================================================

    -- Remove user's existing entry if they're moving up
    DELETE FROM vault_leaderboards
    WHERE vault_signature = p_vault_signature AND wallet = p_wallet;

    -- Bump everyone at or below new rank down by 1
    -- This includes ties that are now behind us
    UPDATE vault_leaderboards
    SET rank = rank + 1
    WHERE vault_signature = p_vault_signature
      AND rank >= v_new_rank;

    -- Remove anyone pushed past rank 10
    DELETE FROM vault_leaderboards
    WHERE vault_signature = p_vault_signature AND rank > 10;

    -- Insert new entry with explicit achieved_at
    INSERT INTO vault_leaderboards (
        vault_signature,
        rank,
        wallet,
        best_time_seconds,
        avg_power_w,
        completion_id,
        achieved_at
    )
    VALUES (
        p_vault_signature,
        v_new_rank,
        p_wallet,
        p_time_seconds,
        p_avg_power_w,
        p_completion_id,
        v_achieved_at
    );

    RETURN v_new_rank;
END;
$$ LANGUAGE plpgsql;

-- Update function comment to document tie-breaking behavior
COMMENT ON FUNCTION update_vault_leaderboard IS
'Update leaderboard after a completion. Returns new rank or NULL if not in top 10.
Validates time against vault bounds (raises exception if invalid).

Tie-Breaking Rules:
1. FIRST ACHIEVER WINS - when times are identical, earlier achieved_at timestamp gets higher rank
2. Times are compared in whole seconds (no sub-second precision)
3. Incumbent advantage - if a user already has an entry with the same time, it is preserved
4. Self-improvement - users can always improve their own time, even if outside top 10

Parameters:
- p_achieved_at: Optional timestamp for when the time was originally achieved.
  Use this for backfills to preserve original completion timestamps.
  Defaults to now() for real-time completions.';

-- =============================================================================
-- HELPER FUNCTION: Rebuild leaderboard with proper tie-breaking
-- Use this to fix any existing leaderboards with incorrect tie ordering
-- =============================================================================

CREATE OR REPLACE FUNCTION rebuild_vault_leaderboard(
    p_vault_signature TEXT
) RETURNS INTEGER AS $$
DECLARE
    v_entry RECORD;
    v_new_rank INTEGER := 1;
    v_count INTEGER := 0;
BEGIN
    -- Create temp table with correct ordering
    CREATE TEMP TABLE temp_leaderboard AS
    SELECT
        wallet,
        best_time_seconds,
        avg_power_w,
        completion_id,
        achieved_at
    FROM vault_leaderboards
    WHERE vault_signature = p_vault_signature
    ORDER BY best_time_seconds ASC, achieved_at ASC
    LIMIT 10;

    -- Delete all existing entries for this vault
    DELETE FROM vault_leaderboards
    WHERE vault_signature = p_vault_signature;

    -- Re-insert with correct ranks
    FOR v_entry IN
        SELECT * FROM temp_leaderboard
        ORDER BY best_time_seconds ASC, achieved_at ASC
    LOOP
        INSERT INTO vault_leaderboards (
            vault_signature,
            rank,
            wallet,
            best_time_seconds,
            avg_power_w,
            completion_id,
            achieved_at
        ) VALUES (
            p_vault_signature,
            v_new_rank,
            v_entry.wallet,
            v_entry.best_time_seconds,
            v_entry.avg_power_w,
            v_entry.completion_id,
            v_entry.achieved_at
        );
        v_new_rank := v_new_rank + 1;
        v_count := v_count + 1;
    END LOOP;

    DROP TABLE temp_leaderboard;

    RETURN v_count;
END;
$$ LANGUAGE plpgsql;

COMMENT ON FUNCTION rebuild_vault_leaderboard IS
'Rebuild a vault leaderboard with correct tie-breaking order (first achiever wins).
Use this to fix any existing leaderboards that may have incorrect ordering.
Returns the number of entries in the rebuilt leaderboard.';

-- =============================================================================
-- HELPER FUNCTION: Rebuild ALL leaderboards
-- Use this after migration to ensure all existing leaderboards are correct
-- =============================================================================

CREATE OR REPLACE FUNCTION rebuild_all_vault_leaderboards()
RETURNS TABLE(vault_signature TEXT, entries_count INTEGER) AS $$
DECLARE
    v_vault RECORD;
BEGIN
    FOR v_vault IN
        SELECT DISTINCT vl.vault_signature
        FROM vault_leaderboards vl
    LOOP
        entries_count := rebuild_vault_leaderboard(v_vault.vault_signature);
        vault_signature := v_vault.vault_signature;
        RETURN NEXT;
    END LOOP;
END;
$$ LANGUAGE plpgsql;

COMMENT ON FUNCTION rebuild_all_vault_leaderboards IS
'Rebuild all vault leaderboards with correct tie-breaking order.
Run this after migration to ensure existing data is consistent.
Returns a list of vaults and their entry counts.';
