-- Migration: 052_leaderboard_history.sql
-- Description: Track all leaderboard entries and exits for historical analysis
-- Date: 2025-01-26
--
-- Problem: When someone is bumped off leaderboard, their historical presence is lost.
-- No record of "was rank X from epoch Y to Z". Makes earning history and disputes
-- impossible to reconstruct.
--
-- Solution: Create leaderboard_history table that tracks:
-- - When users enter/exit the leaderboard
-- - Why they exited (bumped, improved own time, admin removed)
-- - Who bumped them and with what time
-- - How many epochs they held the position
-- - Total earnings during tenure

-- =============================================================================
-- LEADERBOARD HISTORY TABLE
-- =============================================================================

CREATE TABLE IF NOT EXISTS leaderboard_history (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    vault_signature TEXT NOT NULL,
    wallet TEXT NOT NULL,

    -- Position info
    rank INTEGER NOT NULL CHECK (rank >= 1 AND rank <= 10),
    best_time_seconds INTEGER NOT NULL,
    avg_power_w INTEGER,

    -- Tenure tracking
    entered_at TIMESTAMPTZ NOT NULL,
    entered_epoch INTEGER NOT NULL,
    exited_at TIMESTAMPTZ,  -- NULL if still on leaderboard
    exited_epoch INTEGER,
    epochs_held INTEGER DEFAULT 0,

    -- Exit details
    exit_reason TEXT,  -- 'bumped', 'improved_own_time', 'admin_removed', NULL if active
    bumped_by_wallet TEXT,  -- wallet that bumped them (if applicable)
    bumped_by_time INTEGER,  -- time that bumped them

    -- Earnings during tenure
    total_dung_earned NUMERIC(20,9) DEFAULT 0,
    total_points_earned NUMERIC(20,9) DEFAULT 0,

    created_at TIMESTAMPTZ DEFAULT now(),

    -- Constraints
    CONSTRAINT chk_exit_reason CHECK (
        exit_reason IS NULL OR exit_reason IN ('bumped', 'improved_own_time', 'admin_removed')
    ),
    CONSTRAINT chk_exit_consistency CHECK (
        (exited_at IS NULL AND exited_epoch IS NULL AND exit_reason IS NULL) OR
        (exited_at IS NOT NULL AND exited_epoch IS NOT NULL AND exit_reason IS NOT NULL)
    )
);

-- =============================================================================
-- INDEXES
-- =============================================================================

-- Primary lookup: vault + wallet history
CREATE INDEX IF NOT EXISTS idx_leaderboard_history_vault_wallet
ON leaderboard_history(vault_signature, wallet);

-- Active entries (currently on leaderboard)
CREATE INDEX IF NOT EXISTS idx_leaderboard_history_active
ON leaderboard_history(vault_signature, exited_at)
WHERE exited_at IS NULL;

-- User's leaderboard history across all vaults
CREATE INDEX IF NOT EXISTS idx_leaderboard_history_wallet
ON leaderboard_history(wallet, entered_at DESC);

-- Vault history timeline
CREATE INDEX IF NOT EXISTS idx_leaderboard_history_vault_timeline
ON leaderboard_history(vault_signature, entered_at DESC);

-- Epoch-based queries (for distribution calculations)
CREATE INDEX IF NOT EXISTS idx_leaderboard_history_epochs
ON leaderboard_history(entered_epoch, exited_epoch);

-- =============================================================================
-- COMMENTS
-- =============================================================================

COMMENT ON TABLE leaderboard_history IS 'Historical record of all leaderboard entries and exits';
COMMENT ON COLUMN leaderboard_history.rank IS 'Rank position (1-10) when user was on leaderboard';
COMMENT ON COLUMN leaderboard_history.entered_epoch IS 'Epoch number when user entered the leaderboard';
COMMENT ON COLUMN leaderboard_history.exited_at IS 'NULL if user is still on leaderboard';
COMMENT ON COLUMN leaderboard_history.exit_reason IS 'bumped = displaced by another user, improved_own_time = user beat their own time, admin_removed = manual removal';
COMMENT ON COLUMN leaderboard_history.bumped_by_wallet IS 'Wallet of user who displaced this entry (only for bumped exits)';
COMMENT ON COLUMN leaderboard_history.epochs_held IS 'Number of complete epochs user held this position';
COMMENT ON COLUMN leaderboard_history.total_dung_earned IS 'DUNG earned while on leaderboard (post-TGE)';
COMMENT ON COLUMN leaderboard_history.total_points_earned IS 'Points earned while on leaderboard (pre-TGE)';

-- =============================================================================
-- HELPER FUNCTIONS
-- =============================================================================

-- Function to get current epoch number (matches TOKENOMICS_V2 epoch calculation)
CREATE OR REPLACE FUNCTION get_current_epoch_for_history() RETURNS INTEGER AS $$
BEGIN
    -- Epoch anchor: Sun Dec 31 2023 12:00:00 UTC
    -- Epoch duration: 7 days (604800 seconds)
    RETURN FLOOR((EXTRACT(EPOCH FROM NOW()) - 1704020400) / 604800)::INTEGER;
END;
$$ LANGUAGE plpgsql STABLE;

-- Function to record a new leaderboard entry
CREATE OR REPLACE FUNCTION record_leaderboard_entry(
    p_vault_signature TEXT,
    p_wallet TEXT,
    p_rank INTEGER,
    p_time_seconds INTEGER,
    p_avg_power_w INTEGER DEFAULT NULL
) RETURNS UUID AS $$
DECLARE
    v_history_id UUID;
    v_current_epoch INTEGER;
BEGIN
    -- Calculate current epoch
    v_current_epoch := get_current_epoch_for_history();

    -- Close any existing active entry for this user on this vault
    -- (they improved their own time and are re-entering at a potentially different rank)
    UPDATE leaderboard_history
    SET exited_at = NOW(),
        exited_epoch = v_current_epoch,
        exit_reason = 'improved_own_time',
        epochs_held = v_current_epoch - entered_epoch
    WHERE vault_signature = p_vault_signature
      AND wallet = p_wallet
      AND exited_at IS NULL;

    -- Create new entry
    INSERT INTO leaderboard_history (
        vault_signature, wallet, rank, best_time_seconds, avg_power_w,
        entered_at, entered_epoch
    ) VALUES (
        p_vault_signature, p_wallet, p_rank, p_time_seconds, p_avg_power_w,
        NOW(), v_current_epoch
    )
    RETURNING id INTO v_history_id;

    RETURN v_history_id;
END;
$$ LANGUAGE plpgsql;

COMMENT ON FUNCTION record_leaderboard_entry IS 'Record a new leaderboard entry, closing any previous entry for the same user';

-- Function to record a bump (when user is displaced by another)
CREATE OR REPLACE FUNCTION record_leaderboard_bump(
    p_vault_signature TEXT,
    p_bumped_wallet TEXT,
    p_bumped_by_wallet TEXT,
    p_bumped_by_time INTEGER
) RETURNS VOID AS $$
DECLARE
    v_current_epoch INTEGER;
BEGIN
    v_current_epoch := get_current_epoch_for_history();

    UPDATE leaderboard_history
    SET exited_at = NOW(),
        exited_epoch = v_current_epoch,
        exit_reason = 'bumped',
        bumped_by_wallet = p_bumped_by_wallet,
        bumped_by_time = p_bumped_by_time,
        epochs_held = v_current_epoch - entered_epoch
    WHERE vault_signature = p_vault_signature
      AND wallet = p_bumped_wallet
      AND exited_at IS NULL;
END;
$$ LANGUAGE plpgsql;

COMMENT ON FUNCTION record_leaderboard_bump IS 'Record when a user is bumped off the leaderboard by another user';

-- Function to get leaderboard history for a vault
CREATE OR REPLACE FUNCTION get_vault_leaderboard_history(
    p_vault_signature TEXT,
    p_limit INTEGER DEFAULT 100
) RETURNS TABLE(
    wallet TEXT,
    rank INTEGER,
    best_time_seconds INTEGER,
    avg_power_w INTEGER,
    entered_at TIMESTAMPTZ,
    exited_at TIMESTAMPTZ,
    entered_epoch INTEGER,
    exited_epoch INTEGER,
    epochs_held INTEGER,
    exit_reason TEXT,
    bumped_by_wallet TEXT,
    bumped_by_time INTEGER,
    total_points_earned NUMERIC,
    total_dung_earned NUMERIC,
    is_active BOOLEAN
) AS $$
BEGIN
    RETURN QUERY
    SELECT
        h.wallet,
        h.rank,
        h.best_time_seconds,
        h.avg_power_w,
        h.entered_at,
        h.exited_at,
        h.entered_epoch,
        h.exited_epoch,
        h.epochs_held,
        h.exit_reason,
        h.bumped_by_wallet,
        h.bumped_by_time,
        h.total_points_earned,
        h.total_dung_earned,
        (h.exited_at IS NULL) AS is_active
    FROM leaderboard_history h
    WHERE h.vault_signature = p_vault_signature
    ORDER BY h.entered_at DESC
    LIMIT p_limit;
END;
$$ LANGUAGE plpgsql STABLE;

COMMENT ON FUNCTION get_vault_leaderboard_history IS 'Get historical leaderboard entries for a vault';

-- Function to get user's leaderboard history across all vaults
CREATE OR REPLACE FUNCTION get_user_leaderboard_history(
    p_wallet TEXT,
    p_limit INTEGER DEFAULT 100
) RETURNS TABLE(
    vault_signature TEXT,
    vault_name TEXT,
    rank INTEGER,
    best_time_seconds INTEGER,
    entered_at TIMESTAMPTZ,
    exited_at TIMESTAMPTZ,
    epochs_held INTEGER,
    exit_reason TEXT,
    bumped_by_wallet TEXT,
    total_points_earned NUMERIC,
    total_dung_earned NUMERIC,
    is_active BOOLEAN
) AS $$
BEGIN
    RETURN QUERY
    SELECT
        h.vault_signature,
        COALESCE(v.name, 'Unknown Vault') as vault_name,
        h.rank,
        h.best_time_seconds,
        h.entered_at,
        h.exited_at,
        h.epochs_held,
        h.exit_reason,
        h.bumped_by_wallet,
        h.total_points_earned,
        h.total_dung_earned,
        (h.exited_at IS NULL) AS is_active
    FROM leaderboard_history h
    LEFT JOIN indexed_vaults v ON v.signature_hex = h.vault_signature
    WHERE h.wallet = p_wallet
    ORDER BY h.entered_at DESC
    LIMIT p_limit;
END;
$$ LANGUAGE plpgsql STABLE;

COMMENT ON FUNCTION get_user_leaderboard_history IS 'Get user leaderboard history across all vaults';

-- Update epochs_held for all active entries at each epoch close
CREATE OR REPLACE FUNCTION update_leaderboard_tenure() RETURNS INTEGER AS $$
DECLARE
    v_current_epoch INTEGER;
    v_updated_count INTEGER;
BEGIN
    v_current_epoch := get_current_epoch_for_history();

    UPDATE leaderboard_history
    SET epochs_held = v_current_epoch - entered_epoch
    WHERE exited_at IS NULL;

    GET DIAGNOSTICS v_updated_count = ROW_COUNT;
    RETURN v_updated_count;
END;
$$ LANGUAGE plpgsql;

COMMENT ON FUNCTION update_leaderboard_tenure IS 'Update epochs_held for all active leaderboard entries (call at epoch close)';

-- Function to update earnings for active leaderboard entries
CREATE OR REPLACE FUNCTION update_leaderboard_earnings(
    p_vault_signature TEXT,
    p_rank INTEGER,
    p_points_earned NUMERIC DEFAULT 0,
    p_dung_earned NUMERIC DEFAULT 0
) RETURNS VOID AS $$
BEGIN
    UPDATE leaderboard_history
    SET total_points_earned = total_points_earned + COALESCE(p_points_earned, 0),
        total_dung_earned = total_dung_earned + COALESCE(p_dung_earned, 0)
    WHERE vault_signature = p_vault_signature
      AND rank = p_rank
      AND exited_at IS NULL;
END;
$$ LANGUAGE plpgsql;

COMMENT ON FUNCTION update_leaderboard_earnings IS 'Add earnings to active leaderboard entry for a rank';

-- =============================================================================
-- UPDATE update_vault_leaderboard TO TRACK HISTORY
-- This replaces the existing function from 033_vault_economics.sql
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
    new_rank INTEGER := NULL;
    current RECORD;
    bump_rank INTEGER;
    bumped_wallet TEXT;
    history_id UUID;
    actual_achieved_at TIMESTAMPTZ;
BEGIN
    -- Use provided achieved_at or default to now()
    actual_achieved_at := COALESCE(p_achieved_at, NOW());

    -- Calculate what rank this time would achieve
    -- Count how many entries have a faster time
    SELECT COUNT(*) + 1 INTO new_rank
    FROM vault_leaderboards
    WHERE vault_signature = p_vault_signature
      AND (best_time_seconds < p_time_seconds
           OR (best_time_seconds = p_time_seconds AND achieved_at < actual_achieved_at));

    -- Check if user already has an entry
    SELECT rank, best_time_seconds INTO current
    FROM vault_leaderboards
    WHERE vault_signature = p_vault_signature AND wallet = p_wallet;

    IF FOUND THEN
        -- User already on leaderboard
        IF p_time_seconds >= current.best_time_seconds THEN
            -- New time is not better, no change
            RETURN current.rank;
        END IF;

        -- User improved their own time - record in history (entry function handles the exit)
        -- Calculate their new rank (accounting for their current position)
        SELECT COUNT(*) + 1 INTO new_rank
        FROM vault_leaderboards
        WHERE vault_signature = p_vault_signature
          AND wallet != p_wallet
          AND (best_time_seconds < p_time_seconds
               OR (best_time_seconds = p_time_seconds AND achieved_at < actual_achieved_at));

        -- Remove their current entry
        DELETE FROM vault_leaderboards WHERE vault_signature = p_vault_signature AND wallet = p_wallet;

        -- Shift ranks for those between old and new rank
        IF current.rank > new_rank THEN
            UPDATE vault_leaderboards SET rank = rank + 1
            WHERE vault_signature = p_vault_signature AND rank >= new_rank AND rank < current.rank;
        ELSIF current.rank < new_rank THEN
            UPDATE vault_leaderboards SET rank = rank - 1
            WHERE vault_signature = p_vault_signature AND rank > current.rank AND rank <= new_rank;
        END IF;

        -- Insert new entry at new rank
        INSERT INTO vault_leaderboards (vault_signature, rank, wallet, best_time_seconds, avg_power_w, completion_id, achieved_at)
        VALUES (p_vault_signature, new_rank, p_wallet, p_time_seconds, p_avg_power_w, p_completion_id, actual_achieved_at);

        -- Record in history (this will close the old entry and create a new one)
        PERFORM record_leaderboard_entry(p_vault_signature, p_wallet, new_rank, p_time_seconds, p_avg_power_w);

        RETURN new_rank;
    END IF;

    -- User not on leaderboard yet
    IF new_rank > 10 THEN
        RETURN NULL; -- Doesn't qualify for top 10
    END IF;

    -- Check if someone gets bumped off (rank 10)
    SELECT wallet INTO bumped_wallet
    FROM vault_leaderboards
    WHERE vault_signature = p_vault_signature AND rank = 10;

    IF bumped_wallet IS NOT NULL THEN
        -- Record the bump in history before removing
        PERFORM record_leaderboard_bump(p_vault_signature, bumped_wallet, p_wallet, p_time_seconds);

        -- Remove the bumped entry
        DELETE FROM vault_leaderboards
        WHERE vault_signature = p_vault_signature AND rank = 10;
    END IF;

    -- Bump everyone at or below new rank down by 1
    UPDATE vault_leaderboards SET rank = rank + 1
    WHERE vault_signature = p_vault_signature AND rank >= new_rank;

    -- Insert new entry
    INSERT INTO vault_leaderboards (vault_signature, rank, wallet, best_time_seconds, avg_power_w, completion_id, achieved_at)
    VALUES (p_vault_signature, new_rank, p_wallet, p_time_seconds, p_avg_power_w, p_completion_id, actual_achieved_at);

    -- Record in history
    PERFORM record_leaderboard_entry(p_vault_signature, p_wallet, new_rank, p_time_seconds, p_avg_power_w);

    RETURN new_rank;
END;
$$ LANGUAGE plpgsql;

COMMENT ON FUNCTION update_vault_leaderboard IS 'Update leaderboard after a completion, tracking history of entries and exits. Returns new rank or NULL if not in top 10.';

-- =============================================================================
-- BACKFILL EXISTING LEADERBOARD ENTRIES INTO HISTORY
-- Creates history records for all current leaderboard entries
-- =============================================================================

INSERT INTO leaderboard_history (
    vault_signature,
    wallet,
    rank,
    best_time_seconds,
    avg_power_w,
    entered_at,
    entered_epoch,
    exited_at,
    exited_epoch,
    exit_reason
)
SELECT
    vl.vault_signature,
    vl.wallet,
    vl.rank,
    vl.best_time_seconds,
    vl.avg_power_w,
    COALESCE(vl.achieved_at, NOW()) as entered_at,
    FLOOR((EXTRACT(EPOCH FROM COALESCE(vl.achieved_at, NOW())) - 1704020400) / 604800)::INTEGER as entered_epoch,
    NULL as exited_at,
    NULL as exited_epoch,
    NULL as exit_reason
FROM vault_leaderboards vl
WHERE NOT EXISTS (
    SELECT 1 FROM leaderboard_history lh
    WHERE lh.vault_signature = vl.vault_signature
      AND lh.wallet = vl.wallet
      AND lh.exited_at IS NULL
);

-- =============================================================================
-- VIEW FOR ACTIVE LEADERBOARD WITH TENURE
-- =============================================================================

CREATE OR REPLACE VIEW v_leaderboard_with_tenure AS
SELECT
    vl.vault_signature,
    vl.rank,
    vl.wallet,
    vl.best_time_seconds,
    vl.avg_power_w,
    vl.achieved_at,
    lh.entered_at,
    lh.entered_epoch,
    lh.epochs_held,
    lh.total_points_earned,
    lh.total_dung_earned,
    v.name as vault_name
FROM vault_leaderboards vl
LEFT JOIN leaderboard_history lh ON
    lh.vault_signature = vl.vault_signature
    AND lh.wallet = vl.wallet
    AND lh.exited_at IS NULL
LEFT JOIN indexed_vaults v ON v.signature_hex = vl.vault_signature
ORDER BY vl.vault_signature, vl.rank;

COMMENT ON VIEW v_leaderboard_with_tenure IS 'Current leaderboard entries with tenure information from history';
