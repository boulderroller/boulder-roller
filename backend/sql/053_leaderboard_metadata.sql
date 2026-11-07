-- Migration: 052_leaderboard_metadata.sql
-- Description: Add metadata columns to leaderboards (device, PR, attempts)
-- Date: 2026-01-26
--
-- Adds useful context to leaderboard entries:
-- - device_name: What device was used (e.g., "Wahoo ELEMNT BOLT")
-- - is_personal_record: Was this the rider's PR at time of achievement?
-- - attempt_number: How many attempts has rider made on this vault?
-- - activity_id: Link to the ride that achieved this time

-- =============================================================================
-- ADD METADATA COLUMNS TO VAULT_LEADERBOARDS
-- =============================================================================

ALTER TABLE vault_leaderboards
    ADD COLUMN IF NOT EXISTS device_name TEXT,
    ADD COLUMN IF NOT EXISTS is_personal_record BOOLEAN DEFAULT false,
    ADD COLUMN IF NOT EXISTS attempt_number INTEGER DEFAULT 1,
    ADD COLUMN IF NOT EXISTS activity_id UUID;

COMMENT ON COLUMN vault_leaderboards.device_name IS 'Device used for this leaderboard time (e.g., Wahoo ELEMNT)';
COMMENT ON COLUMN vault_leaderboards.is_personal_record IS 'Whether this was a PR for the rider at time of achievement';
COMMENT ON COLUMN vault_leaderboards.attempt_number IS 'Which attempt number achieved this time';
COMMENT ON COLUMN vault_leaderboards.activity_id IS 'Reference to the ride/activity that achieved this time';

-- =============================================================================
-- ADD METADATA COLUMNS TO VAULT_COMPLETIONS
-- =============================================================================

ALTER TABLE vault_completions
    ADD COLUMN IF NOT EXISTS device_name TEXT,
    ADD COLUMN IF NOT EXISTS is_pr BOOLEAN DEFAULT false;

COMMENT ON COLUMN vault_completions.device_name IS 'Device used for this completion';
COMMENT ON COLUMN vault_completions.is_pr IS 'Whether this completion was a personal record';

-- =============================================================================
-- INDEX FOR PR QUERIES
-- Allows efficient queries like "show all PRs on this vault"
-- =============================================================================

CREATE INDEX IF NOT EXISTS idx_vault_leaderboards_pr
ON vault_leaderboards(vault_signature, is_personal_record)
WHERE is_personal_record = true;

-- =============================================================================
-- HELPER FUNCTION: Check if time is a personal record
-- =============================================================================

CREATE OR REPLACE FUNCTION is_personal_record(
    p_vault_signature TEXT,
    p_wallet TEXT,
    p_time_seconds INTEGER
) RETURNS BOOLEAN AS $$
DECLARE
    v_previous_best INTEGER;
BEGIN
    -- Get the user's previous best time on this vault
    SELECT MIN(best_time_seconds)
    INTO v_previous_best
    FROM vault_completions
    WHERE vault_signature = p_vault_signature
      AND wallet = p_wallet
      AND best_time_seconds IS NOT NULL;

    -- It's a PR if no previous time exists or this is faster
    RETURN v_previous_best IS NULL OR p_time_seconds < v_previous_best;
END;
$$ LANGUAGE plpgsql STABLE;

COMMENT ON FUNCTION is_personal_record IS 'Check if a time would be a PR for the user on this vault';

-- =============================================================================
-- HELPER FUNCTION: Get attempt count for user on vault
-- =============================================================================

CREATE OR REPLACE FUNCTION get_attempt_count(
    p_vault_signature TEXT,
    p_wallet TEXT
) RETURNS INTEGER AS $$
BEGIN
    RETURN COALESCE(
        (SELECT total_completions FROM vault_completions
         WHERE vault_signature = p_vault_signature AND wallet = p_wallet),
        0
    ) + 1;  -- +1 for current attempt (about to be recorded)
END;
$$ LANGUAGE plpgsql STABLE;

COMMENT ON FUNCTION get_attempt_count IS 'Get the current attempt count for user on vault (includes upcoming attempt)';

-- =============================================================================
-- UPDATED LEADERBOARD FUNCTION WITH METADATA
-- Extends update_vault_leaderboard to include device, PR, attempt tracking
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
    v_new_rank INTEGER := NULL;
    v_existing_time INTEGER;
    v_existing_rank INTEGER;
    v_achieved_at TIMESTAMPTZ;
    v_current_count INTEGER;
    v_is_pr BOOLEAN;
    v_attempt_number INTEGER;
BEGIN
    -- Use provided achieved_at or default to now()
    -- This allows backfills to use original completion timestamps
    v_achieved_at := COALESCE(p_achieved_at, now());

    -- Calculate if this is a PR (before recording the completion)
    v_is_pr := is_personal_record(p_vault_signature, p_wallet, p_time_seconds);

    -- Calculate attempt number (before recording the completion)
    v_attempt_number := get_attempt_count(p_vault_signature, p_wallet);

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

    -- Calculate new rank with explicit tie-breaking:
    -- 1. Count entries with strictly faster times
    -- 2. For entries with same time, count those with earlier achieved_at
    -- Tie-breaker: first achiever wins (earlier achieved_at = better rank)
    SELECT COUNT(*) + 1
    INTO v_new_rank
    FROM vault_leaderboards
    WHERE vault_signature = p_vault_signature
      AND (
          best_time_seconds < p_time_seconds
          OR (best_time_seconds = p_time_seconds AND achieved_at < v_achieved_at)
      );

    -- Check if we even qualify for top 10
    -- If rank > 10, check if user has existing entry we can improve
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

    -- Insert new entry with metadata
    INSERT INTO vault_leaderboards (
        vault_signature,
        rank,
        wallet,
        best_time_seconds,
        avg_power_w,
        completion_id,
        achieved_at,
        device_name,
        is_personal_record,
        attempt_number,
        activity_id
    )
    VALUES (
        p_vault_signature,
        v_new_rank,
        p_wallet,
        p_time_seconds,
        p_avg_power_w,
        p_completion_id,
        v_achieved_at,
        p_device_name,
        v_is_pr,
        v_attempt_number,
        p_activity_id
    );

    RETURN v_new_rank;
END;
$$ LANGUAGE plpgsql;

-- Update function comment to document new parameters
COMMENT ON FUNCTION update_vault_leaderboard IS
'Update leaderboard after a completion with full metadata. Returns new rank or NULL if not in top 10.

Metadata tracked:
- device_name: Device used for this effort (e.g., "Wahoo ELEMNT BOLT")
- is_personal_record: Automatically calculated - true if this is/was rider PR
- attempt_number: Automatically calculated from total_completions + 1
- activity_id: Reference to the ride that achieved this time

Tie-Breaking Rules:
1. FIRST ACHIEVER WINS - when times are identical, earlier achieved_at timestamp gets higher rank
2. Times are compared in whole seconds (no sub-second precision)
3. Incumbent advantage - if a user already has an entry with the same time, it is preserved
4. Self-improvement - users can always improve their own time, even if outside top 10

Parameters:
- p_achieved_at: Optional timestamp for when the time was originally achieved.
  Use this for backfills to preserve original completion timestamps.
  Defaults to now() for real-time completions.
- p_device_name: Optional device name from the activity file.
- p_activity_id: Optional UUID linking to the rides table.';

-- =============================================================================
-- ENHANCED COMPLETION RECORDING WITH METADATA
-- Updates record_vault_completion_with_best_time to track device and PR
-- =============================================================================

CREATE OR REPLACE FUNCTION record_vault_completion_with_metadata(
    p_vault_signature TEXT,
    p_wallet TEXT,
    p_activity_id TEXT,
    p_time_seconds INTEGER DEFAULT NULL,
    p_avg_power_w INTEGER DEFAULT NULL,
    p_device_name TEXT DEFAULT NULL
) RETURNS TABLE (
    is_new_pr BOOLEAN,
    previous_best INTEGER,
    new_best INTEGER,
    total_completions INTEGER,
    attempt_number INTEGER
) AS $$
DECLARE
    existing_record RECORD;
    is_new_personal_best BOOLEAN := FALSE;
    prev_best INTEGER;
    v_attempt_number INTEGER;
BEGIN
    -- Get existing record for this user/vault combination
    SELECT vc.best_time_seconds, vc.total_completions
    INTO existing_record
    FROM vault_completions vc
    WHERE vc.vault_signature = p_vault_signature
      AND vc.wallet = p_wallet;

    IF FOUND THEN
        prev_best := existing_record.best_time_seconds;
        v_attempt_number := COALESCE(existing_record.total_completions, 0) + 1;

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
            device_name = CASE
                WHEN is_new_personal_best THEN p_device_name
                ELSE vault_completions.device_name
            END,
            is_pr = is_new_personal_best,
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
            v_attempt_number as total_completions,
            v_attempt_number as attempt_number;
    ELSE
        -- Insert new record (first attempt is always a PR if time provided)
        INSERT INTO vault_completions (
            vault_signature, wallet, activity_id, time_seconds, completed_at,
            best_time_seconds, best_time_achieved_at, total_completions, avg_power_w,
            device_name, is_pr
        ) VALUES (
            p_vault_signature, p_wallet, p_activity_id, p_time_seconds, now(),
            p_time_seconds, CASE WHEN p_time_seconds IS NOT NULL THEN now() ELSE NULL END, 1, p_avg_power_w,
            p_device_name, (p_time_seconds IS NOT NULL)
        );

        RETURN QUERY
        SELECT
            (p_time_seconds IS NOT NULL) as is_new_pr,
            NULL::INTEGER as previous_best,
            p_time_seconds as new_best,
            1 as total_completions,
            1 as attempt_number;
    END IF;
END;
$$ LANGUAGE plpgsql;

COMMENT ON FUNCTION record_vault_completion_with_metadata IS
'Record a vault completion with device metadata and PR tracking.
Returns PR status, previous/new best times, and attempt number.';

-- =============================================================================
-- UPDATE REBUILD FUNCTION TO PRESERVE METADATA
-- =============================================================================

CREATE OR REPLACE FUNCTION rebuild_vault_leaderboard(
    p_vault_signature TEXT
) RETURNS INTEGER AS $$
DECLARE
    v_entry RECORD;
    v_new_rank INTEGER := 1;
    v_count INTEGER := 0;
BEGIN
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
            vault_signature,
            rank,
            wallet,
            best_time_seconds,
            avg_power_w,
            completion_id,
            achieved_at,
            device_name,
            is_personal_record,
            attempt_number,
            activity_id
        ) VALUES (
            p_vault_signature,
            v_new_rank,
            v_entry.wallet,
            v_entry.best_time_seconds,
            v_entry.avg_power_w,
            v_entry.completion_id,
            v_entry.achieved_at,
            v_entry.device_name,
            v_entry.is_personal_record,
            v_entry.attempt_number,
            v_entry.activity_id
        );
        v_new_rank := v_new_rank + 1;
        v_count := v_count + 1;
    END LOOP;

    DROP TABLE temp_leaderboard;

    RETURN v_count;
END;
$$ LANGUAGE plpgsql;
