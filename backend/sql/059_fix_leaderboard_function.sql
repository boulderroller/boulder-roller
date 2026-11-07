-- Migration: 059_fix_leaderboard_function.sql
-- Description: Consolidate update_vault_leaderboard with ALL features that were lost
--              due to multiple CREATE OR REPLACE across migrations 048, 050, 052
-- Date: 2026-01-26
--
-- This migration fixes a critical bug where the update_vault_leaderboard function
-- was defined 5 times across different migrations, with each new definition
-- overwriting the previous one. The final version (052_leaderboard_metadata.sql)
-- was missing:
--   - Time validation (from 048_time_validation.sql)
--   - History tracking (from 052_leaderboard_history.sql)
--
-- This consolidated version includes ALL features:
--   1. Time validation (min/max bounds checking)
--   2. Tie-breaking (first achiever wins)
--   3. History tracking (record_leaderboard_entry, record_leaderboard_bump)
--   4. Metadata (device_name, is_personal_record, attempt_number, activity_id)
--   5. Advisory locking (prevents race conditions on concurrent updates)

-- =============================================================================
-- ADD MISSING INDEX ON LEADERBOARD_HISTORY
-- Required for efficient update_leaderboard_earnings queries
-- =============================================================================

CREATE INDEX IF NOT EXISTS idx_leaderboard_history_vault_rank
    ON leaderboard_history(vault_signature, rank)
    WHERE exited_at IS NULL;

COMMENT ON INDEX idx_leaderboard_history_vault_rank IS
'Supports update_leaderboard_earnings queries by vault_signature and rank for active entries';

-- =============================================================================
-- CONSOLIDATED UPDATE_VAULT_LEADERBOARD FUNCTION
-- Combines: time validation + tie-breaking + history tracking + metadata
-- =============================================================================

CREATE OR REPLACE FUNCTION update_vault_leaderboard(
    p_vault_signature TEXT,
    p_wallet TEXT,
    p_time_seconds INTEGER,
    p_avg_power_w INTEGER DEFAULT NULL,
    p_completion_id UUID DEFAULT NULL,
    p_achieved_at TIMESTAMPTZ DEFAULT NULL,
    p_device_name TEXT DEFAULT NULL,
    p_activity_id UUID DEFAULT NULL
) RETURNS INTEGER AS $$
DECLARE
    -- Time validation variables (from 048)
    v_min_time INTEGER;
    v_max_time INTEGER;
    v_validation_enabled BOOLEAN;

    -- Core leaderboard variables
    v_new_rank INTEGER := NULL;
    v_existing_time INTEGER;
    v_existing_rank INTEGER;
    v_achieved_at TIMESTAMPTZ;

    -- Metadata variables (from 052_metadata)
    v_is_pr BOOLEAN;
    v_attempt_number INTEGER;

    -- History tracking variables (from 052_history)
    v_bumped_wallet TEXT;
    v_bumped_rank INTEGER;
BEGIN
    -- =========================================================================
    -- ADVISORY LOCK: Prevent race conditions on concurrent updates
    -- Uses vault signature hash as lock key
    -- =========================================================================
    PERFORM pg_advisory_xact_lock(hashtext(p_vault_signature));

    -- =========================================================================
    -- SETUP: Calculate achieved_at and metadata
    -- =========================================================================

    -- Use provided achieved_at or default to now()
    -- This allows backfills to use original completion timestamps
    v_achieved_at := COALESCE(p_achieved_at, now());

    -- Calculate if this is a PR (before recording the completion)
    v_is_pr := is_personal_record(p_vault_signature, p_wallet, p_time_seconds);

    -- Calculate attempt number (before recording the completion)
    v_attempt_number := get_attempt_count(p_vault_signature, p_wallet);

    -- =========================================================================
    -- TIME VALIDATION (from 048_time_validation.sql)
    -- Reject impossibly fast or slow times
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
    -- CALCULATE NEW RANK WITH TIE-BREAKING (from 050_tiebreaker.sql)
    -- Tie-breaker: first achiever wins (earlier achieved_at = better rank)
    -- =========================================================================

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

    IF v_new_rank > 10 THEN
        -- Check if user has existing entry with worse time (allowing self-improvement)
        IF v_existing_rank IS NOT NULL AND v_existing_time > p_time_seconds THEN
            -- User is improving their own time but still not in top 10
            -- Still update their entry since it's a personal best
            UPDATE vault_leaderboards
            SET best_time_seconds = p_time_seconds,
                avg_power_w = COALESCE(p_avg_power_w, avg_power_w),
                completion_id = COALESCE(p_completion_id, completion_id),
                achieved_at = v_achieved_at,
                device_name = COALESCE(p_device_name, device_name),
                is_personal_record = v_is_pr,
                attempt_number = v_attempt_number,
                activity_id = COALESCE(p_activity_id, activity_id)
            WHERE vault_signature = p_vault_signature AND wallet = p_wallet;

            RETURN v_existing_rank;
        END IF;

        -- No entry to update and not in top 10
        RETURN NULL;
    END IF;

    -- =========================================================================
    -- HANDLE USER IMPROVING THEIR OWN TIME (still in top 10)
    -- =========================================================================

    IF v_existing_rank IS NOT NULL THEN
        -- User already on leaderboard and improving their time
        -- Record history entry for the improvement
        PERFORM record_leaderboard_entry(
            p_vault_signature, p_wallet, v_new_rank, p_time_seconds, p_avg_power_w
        );

        -- Remove their current entry
        DELETE FROM vault_leaderboards
        WHERE vault_signature = p_vault_signature AND wallet = p_wallet;

        -- Shift ranks appropriately
        IF v_existing_rank > v_new_rank THEN
            -- Moving up: bump entries between new and old rank down
            UPDATE vault_leaderboards
            SET rank = rank + 1
            WHERE vault_signature = p_vault_signature
              AND rank >= v_new_rank
              AND rank < v_existing_rank;
        ELSIF v_existing_rank < v_new_rank THEN
            -- Moving down (shouldn't happen with faster time, but handle it)
            UPDATE vault_leaderboards
            SET rank = rank - 1
            WHERE vault_signature = p_vault_signature
              AND rank > v_existing_rank
              AND rank <= v_new_rank;
        END IF;

        -- Insert updated entry
        INSERT INTO vault_leaderboards (
            vault_signature, rank, wallet, best_time_seconds, avg_power_w,
            completion_id, achieved_at, device_name, is_personal_record,
            attempt_number, activity_id
        ) VALUES (
            p_vault_signature, v_new_rank, p_wallet, p_time_seconds, p_avg_power_w,
            p_completion_id, v_achieved_at, p_device_name, v_is_pr,
            v_attempt_number, p_activity_id
        );

        RETURN v_new_rank;
    END IF;

    -- =========================================================================
    -- NEW ENTRY: Check for bump and record history
    -- =========================================================================

    -- Check if someone gets bumped off (rank 10)
    SELECT wallet INTO v_bumped_wallet
    FROM vault_leaderboards
    WHERE vault_signature = p_vault_signature AND rank = 10;

    IF v_bumped_wallet IS NOT NULL THEN
        -- Record the bump in history before removing (from 052_history)
        PERFORM record_leaderboard_bump(
            p_vault_signature, v_bumped_wallet, p_wallet, p_time_seconds
        );

        -- Remove the bumped entry
        DELETE FROM vault_leaderboards
        WHERE vault_signature = p_vault_signature AND rank = 10;
    END IF;

    -- Bump everyone at or below new rank down by 1
    UPDATE vault_leaderboards
    SET rank = rank + 1
    WHERE vault_signature = p_vault_signature
      AND rank >= v_new_rank;

    -- Insert new entry with all metadata
    INSERT INTO vault_leaderboards (
        vault_signature, rank, wallet, best_time_seconds, avg_power_w,
        completion_id, achieved_at, device_name, is_personal_record,
        attempt_number, activity_id
    ) VALUES (
        p_vault_signature, v_new_rank, p_wallet, p_time_seconds, p_avg_power_w,
        p_completion_id, v_achieved_at, p_device_name, v_is_pr,
        v_attempt_number, p_activity_id
    );

    -- Record new entry in history (from 052_history)
    PERFORM record_leaderboard_entry(
        p_vault_signature, p_wallet, v_new_rank, p_time_seconds, p_avg_power_w
    );

    RETURN v_new_rank;
END;
$$ LANGUAGE plpgsql;

COMMENT ON FUNCTION update_vault_leaderboard IS
'CONSOLIDATED leaderboard update function with ALL features:

1. TIME VALIDATION: Rejects times outside vault min/max bounds
2. TIE-BREAKING: First achiever wins when times are identical
3. HISTORY TRACKING: Records entry/exit via record_leaderboard_entry/bump
4. METADATA: Tracks device_name, is_personal_record, attempt_number, activity_id
5. RACE PROTECTION: Uses advisory lock to prevent concurrent update corruption

Parameters:
- p_vault_signature: 128-char hex signature of the vault
- p_wallet: User wallet address
- p_time_seconds: Completion time in seconds
- p_avg_power_w: Optional average power in watts
- p_completion_id: Optional UUID linking to vault_completions
- p_achieved_at: Optional timestamp (defaults to now(), use for backfills)
- p_device_name: Optional device name from activity file
- p_activity_id: Optional UUID linking to rides table

Returns: New rank (1-10) or NULL if not in top 10

Raises: check_violation exception if time fails validation';

-- =============================================================================
-- ALSO FIX rebuild_vault_leaderboard TO HANDLE EXCEPTIONS
-- Ensures temp table is cleaned up on error
-- =============================================================================

CREATE OR REPLACE FUNCTION rebuild_vault_leaderboard(
    p_vault_signature TEXT
) RETURNS INTEGER AS $$
DECLARE
    v_entry RECORD;
    v_new_rank INTEGER := 1;
    v_count INTEGER := 0;
BEGIN
    -- Acquire advisory lock for this vault
    PERFORM pg_advisory_xact_lock(hashtext(p_vault_signature));

    -- Drop temp table if it exists from a previous failed run
    DROP TABLE IF EXISTS temp_leaderboard;

    -- Create temp table with correct ordering, preserving metadata
    CREATE TEMP TABLE temp_leaderboard AS
    SELECT
        wallet,
        best_time_seconds,
        avg_power_w,
        completion_id,
        achieved_at,
        device_name,
        is_personal_record,
        attempt_number,
        activity_id
    FROM vault_leaderboards
    WHERE vault_signature = p_vault_signature
    ORDER BY best_time_seconds ASC, achieved_at ASC
    LIMIT 10;

    -- Delete all existing entries for this vault
    DELETE FROM vault_leaderboards
    WHERE vault_signature = p_vault_signature;

    -- Re-insert with correct ranks, preserving metadata
    FOR v_entry IN
        SELECT * FROM temp_leaderboard
        ORDER BY best_time_seconds ASC, achieved_at ASC
    LOOP
        INSERT INTO vault_leaderboards (
            vault_signature, rank, wallet, best_time_seconds, avg_power_w,
            completion_id, achieved_at, device_name, is_personal_record,
            attempt_number, activity_id
        ) VALUES (
            p_vault_signature, v_new_rank, v_entry.wallet, v_entry.best_time_seconds,
            v_entry.avg_power_w, v_entry.completion_id, v_entry.achieved_at,
            v_entry.device_name, v_entry.is_personal_record, v_entry.attempt_number,
            v_entry.activity_id
        );
        v_new_rank := v_new_rank + 1;
        v_count := v_count + 1;
    END LOOP;

    DROP TABLE IF EXISTS temp_leaderboard;

    RETURN v_count;
EXCEPTION
    WHEN OTHERS THEN
        -- Clean up temp table on any error
        DROP TABLE IF EXISTS temp_leaderboard;
        RAISE;
END;
$$ LANGUAGE plpgsql;

COMMENT ON FUNCTION rebuild_vault_leaderboard IS
'Rebuild a vault leaderboard with correct tie-breaking order (first achiever wins).
Includes advisory locking and proper temp table cleanup on exceptions.
Returns the number of entries in the rebuilt leaderboard.';

-- =============================================================================
-- FIX: Atomic LP token staking calculation
-- Prevents race condition where two concurrent stakes could both receive
-- incorrect LP token allocations
-- =============================================================================

CREATE OR REPLACE FUNCTION stake_cal_atomic(
    p_vault_signature TEXT,
    p_wallet TEXT,
    p_cal_amount NUMERIC
) RETURNS TABLE (
    stake_id UUID,
    lp_tokens_issued NUMERIC,
    total_staked_after NUMERIC,
    total_lp_after NUMERIC
) AS $$
DECLARE
    v_stake_id UUID;
    v_total_staked NUMERIC;
    v_total_lp NUMERIC;
    v_lp_tokens NUMERIC;
    v_existing_stake RECORD;
BEGIN
    -- Acquire advisory lock for this vault's staking operations
    PERFORM pg_advisory_xact_lock(hashtext('stake:' || p_vault_signature));

    -- Get current totals (within the lock)
    SELECT
        COALESCE(SUM(points_staked), 0),
        COALESCE(SUM(lp_tokens), 0)
    INTO v_total_staked, v_total_lp
    FROM vault_stakes
    WHERE vault_signature = p_vault_signature
      AND unstaked_at IS NULL;

    -- Calculate LP tokens
    -- First staker gets 1:1, subsequent stakers get proportional
    IF v_total_staked = 0 THEN
        v_lp_tokens := p_cal_amount;
    ELSE
        v_lp_tokens := (p_cal_amount / v_total_staked) * v_total_lp;
    END IF;

    -- Check for existing stake from this wallet
    SELECT id, points_staked, lp_tokens
    INTO v_existing_stake
    FROM vault_stakes
    WHERE vault_signature = p_vault_signature
      AND wallet = p_wallet
      AND unstaked_at IS NULL;

    IF FOUND THEN
        -- Add to existing stake
        UPDATE vault_stakes
        SET points_staked = points_staked + p_cal_amount,
            lp_tokens = lp_tokens + v_lp_tokens,
            updated_at = now()
        WHERE id = v_existing_stake.id
        RETURNING id INTO v_stake_id;
    ELSE
        -- Create new stake
        INSERT INTO vault_stakes (
            vault_signature, wallet, points_staked, lp_tokens, staked_at
        ) VALUES (
            p_vault_signature, p_wallet, p_cal_amount, v_lp_tokens, now()
        )
        RETURNING id INTO v_stake_id;
    END IF;

    RETURN QUERY SELECT
        v_stake_id,
        v_lp_tokens,
        v_total_staked + p_cal_amount,
        v_total_lp + v_lp_tokens;
END;
$$ LANGUAGE plpgsql;

COMMENT ON FUNCTION stake_cal_atomic IS
'Atomically stake CAL/points in a vault with proper LP token calculation.
Uses advisory locking to prevent race conditions where concurrent stakes
could receive incorrect LP token allocations.';

-- =============================================================================
-- FIX: Handle empty leaderboard distributions
-- Redistributes unclaimed leaderboard allocation instead of losing it
-- =============================================================================

CREATE OR REPLACE FUNCTION calculate_distribution_with_fallback(
    p_total_dung INTEGER,
    p_leaderboard_entries INTEGER,
    p_staker_count INTEGER,
    p_has_legend BOOLEAN
) RETURNS TABLE (
    leaderboard_amount INTEGER,
    staker_amount INTEGER,
    local_legend_amount INTEGER,
    pol_amount INTEGER,
    protocol_amount INTEGER
) AS $$
DECLARE
    -- Standard splits (basis points)
    v_leaderboard_bps INTEGER := 5500;  -- 55%
    v_staker_bps INTEGER := 2700;       -- 27%
    v_legend_bps INTEGER := 300;        -- 3%
    v_pol_bps INTEGER := 500;           -- 5%
    v_protocol_bps INTEGER := 1000;     -- 10%

    -- Calculated amounts
    v_leaderboard INTEGER;
    v_staker INTEGER;
    v_legend INTEGER;
    v_pol INTEGER;
    v_protocol INTEGER;
    v_unclaimed INTEGER := 0;
BEGIN
    -- Calculate base amounts
    v_leaderboard := (p_total_dung * v_leaderboard_bps) / 10000;
    v_staker := (p_total_dung * v_staker_bps) / 10000;
    v_legend := (p_total_dung * v_legend_bps) / 10000;
    v_pol := (p_total_dung * v_pol_bps) / 10000;
    v_protocol := (p_total_dung * v_protocol_bps) / 10000;

    -- Handle empty leaderboard: redistribute to stakers and protocol
    IF p_leaderboard_entries = 0 THEN
        v_unclaimed := v_unclaimed + v_leaderboard;
        v_leaderboard := 0;
    END IF;

    -- Handle no stakers: redistribute to protocol
    IF p_staker_count = 0 THEN
        v_unclaimed := v_unclaimed + v_staker;
        v_staker := 0;
    END IF;

    -- Handle no legend: redistribute to protocol
    IF NOT p_has_legend THEN
        v_unclaimed := v_unclaimed + v_legend;
        v_legend := 0;
    END IF;

    -- Redistribute unclaimed: 70% to stakers (if any), 30% to protocol
    IF v_unclaimed > 0 THEN
        IF p_staker_count > 0 THEN
            v_staker := v_staker + (v_unclaimed * 70 / 100);
            v_protocol := v_protocol + (v_unclaimed * 30 / 100);
        ELSE
            -- No stakers, all to protocol
            v_protocol := v_protocol + v_unclaimed;
        END IF;
    END IF;

    RETURN QUERY SELECT v_leaderboard, v_staker, v_legend, v_pol, v_protocol;
END;
$$ LANGUAGE plpgsql IMMUTABLE;

COMMENT ON FUNCTION calculate_distribution_with_fallback IS
'Calculate epoch distribution amounts with fallback for empty buckets.
Unclaimed leaderboard/staker/legend amounts are redistributed:
- 70% to stakers (if any exist)
- 30% to protocol treasury
This prevents rewards from being lost when a bucket has no recipients.';
