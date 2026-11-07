-- Migration: 055_leaderboard_notifications.sql
-- Description: Add wallet-based leaderboard notifications system
-- Date: 2025-01-26

-- =============================================================================
-- NOTIFICATIONS TABLE EXTENSION
-- Add wallet column and leaderboard-specific fields
-- The existing notifications table uses user_id (UUID), but we need wallet (TEXT)
-- for leaderboard notifications since vaults are wallet-based
-- =============================================================================

-- Add wallet column to existing notifications table (if not exists)
ALTER TABLE notifications
    ADD COLUMN IF NOT EXISTS wallet TEXT;

-- Add metadata column for structured notification data (if not exists)
ALTER TABLE notifications
    ADD COLUMN IF NOT EXISTS metadata JSONB DEFAULT '{}';

-- Add dismissed_at for soft dismissal
ALTER TABLE notifications
    ADD COLUMN IF NOT EXISTS dismissed_at TIMESTAMPTZ;

-- Add vault_signature for easy querying
ALTER TABLE notifications
    ADD COLUMN IF NOT EXISTS vault_signature TEXT;

-- Create indexes for wallet-based queries
CREATE INDEX IF NOT EXISTS idx_notifications_wallet
    ON notifications(wallet, created_at DESC)
    WHERE wallet IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_notifications_wallet_unread
    ON notifications(wallet, read)
    WHERE wallet IS NOT NULL AND read = FALSE;

CREATE INDEX IF NOT EXISTS idx_notifications_vault
    ON notifications(vault_signature, created_at DESC)
    WHERE vault_signature IS NOT NULL;

-- =============================================================================
-- LEADERBOARD NOTIFICATION HELPER FUNCTION
-- Creates notifications for leaderboard events
-- =============================================================================

CREATE OR REPLACE FUNCTION create_leaderboard_notification(
    p_wallet TEXT,
    p_type TEXT,
    p_vault_name TEXT,
    p_vault_signature TEXT DEFAULT NULL,
    p_rank INTEGER DEFAULT NULL,
    p_old_rank INTEGER DEFAULT NULL,
    p_bumped_by TEXT DEFAULT NULL,
    p_payout_amount NUMERIC DEFAULT NULL,
    p_time_seconds INTEGER DEFAULT NULL
) RETURNS UUID AS $$
DECLARE
    v_title TEXT;
    v_message TEXT;
    v_metadata JSONB;
    v_notification_id UUID;
BEGIN
    -- Build title and message based on type
    CASE p_type
        WHEN 'leaderboard_entered' THEN
            v_title := 'Leaderboard Entry!';
            v_message := format('You are now #%s on %s!', p_rank, p_vault_name);

        WHEN 'leaderboard_bumped' THEN
            v_title := 'Bumped from Leaderboard';
            v_message := format('You were bumped off the %s leaderboard', p_vault_name);
            IF p_bumped_by IS NOT NULL THEN
                v_message := format('You were bumped off %s by %s...', p_vault_name, LEFT(p_bumped_by, 8));
            END IF;

        WHEN 'rank_changed' THEN
            IF p_rank < p_old_rank THEN
                v_title := 'Rank Improved!';
                v_message := format('You moved from #%s to #%s on %s!', p_old_rank, p_rank, p_vault_name);
            ELSE
                v_title := 'Rank Changed';
                v_message := format('You moved from #%s to #%s on %s', p_old_rank, p_rank, p_vault_name);
            END IF;

        WHEN 'payout_received' THEN
            v_title := 'Leaderboard Payout!';
            v_message := format('You earned %s points from %s leaderboard', ROUND(p_payout_amount, 2), p_vault_name);

        WHEN 'kom_achieved' THEN
            v_title := 'KOM Achieved!';
            v_message := format('You are now the King of the Mountain on %s!', p_vault_name);
            IF p_time_seconds IS NOT NULL THEN
                v_message := format('%s Time: %s', v_message,
                    format('%s:%02s', p_time_seconds / 60, p_time_seconds % 60));
            END IF;

        WHEN 'stake_payout' THEN
            v_title := 'Staking Payout';
            v_message := format('You earned %s points from staking in %s', ROUND(p_payout_amount, 2), p_vault_name);

        WHEN 'legend_payout' THEN
            v_title := 'Local Legend Payout';
            v_message := format('You earned %s points as Local Legend of %s', ROUND(p_payout_amount, 2), p_vault_name);

        ELSE
            v_title := 'Leaderboard Update';
            v_message := format('Update on %s leaderboard', p_vault_name);
    END CASE;

    -- Build metadata
    v_metadata := jsonb_build_object(
        'vault_name', p_vault_name,
        'vault_signature', p_vault_signature,
        'rank', p_rank,
        'old_rank', p_old_rank,
        'bumped_by', p_bumped_by,
        'payout_amount', p_payout_amount,
        'time_seconds', p_time_seconds
    );

    -- Insert notification
    INSERT INTO notifications (
        wallet,
        notification_type,
        title,
        message,
        metadata,
        vault_signature,
        data
    )
    VALUES (
        p_wallet,
        p_type,
        v_title,
        v_message,
        v_metadata,
        p_vault_signature,
        v_metadata  -- Also populate legacy 'data' column
    )
    RETURNING id INTO v_notification_id;

    RETURN v_notification_id;
END;
$$ LANGUAGE plpgsql;

COMMENT ON FUNCTION create_leaderboard_notification IS
'Creates a notification for leaderboard events (entry, bump, rank change, payouts)';

-- =============================================================================
-- ENHANCED LEADERBOARD UPDATE FUNCTION
-- Returns bumped user info along with new rank
-- =============================================================================

CREATE OR REPLACE FUNCTION update_vault_leaderboard_with_notifications(
    p_vault_signature TEXT,
    p_wallet TEXT,
    p_time_seconds INTEGER,
    p_avg_power_w INTEGER DEFAULT NULL,
    p_completion_id UUID DEFAULT NULL,
    p_achieved_at TIMESTAMPTZ DEFAULT NULL
) RETURNS TABLE (
    new_rank INTEGER,
    is_kom BOOLEAN,
    previous_rank INTEGER,
    bumped_wallet TEXT,
    bumped_rank INTEGER
) AS $$
DECLARE
    v_new_rank INTEGER := NULL;
    v_previous_rank INTEGER := NULL;
    v_bumped_wallet TEXT := NULL;
    v_bumped_rank INTEGER := NULL;
    v_is_kom BOOLEAN := FALSE;
    v_achieved_at TIMESTAMPTZ;
BEGIN
    v_achieved_at := COALESCE(p_achieved_at, now());

    -- Check if user has existing entry
    SELECT rank INTO v_previous_rank
    FROM vault_leaderboards
    WHERE vault_signature = p_vault_signature AND wallet = p_wallet;

    -- Check if this time qualifies for top 10
    SELECT COUNT(*) + 1 INTO v_new_rank
    FROM vault_leaderboards
    WHERE vault_signature = p_vault_signature
      AND (best_time_seconds < p_time_seconds
           OR (best_time_seconds = p_time_seconds AND achieved_at < v_achieved_at));

    -- If not in top 10 based on position count, check if better than current entry
    IF v_new_rank > 10 THEN
        -- Check if user has existing entry with worse time
        IF v_previous_rank IS NOT NULL THEN
            -- User already on leaderboard - check if this is an improvement
            IF (SELECT best_time_seconds FROM vault_leaderboards
                WHERE vault_signature = p_vault_signature AND wallet = p_wallet) > p_time_seconds THEN
                v_new_rank := v_previous_rank;  -- Keep same rank, improve time
            ELSE
                -- Not an improvement
                RETURN QUERY SELECT NULL::INTEGER, FALSE, NULL::INTEGER, NULL::TEXT, NULL::INTEGER;
                RETURN;
            END IF;
        ELSE
            -- Not in top 10 and not an existing entry
            RETURN QUERY SELECT NULL::INTEGER, FALSE, NULL::INTEGER, NULL::TEXT, NULL::INTEGER;
            RETURN;
        END IF;
    END IF;

    -- Get the wallet that will be bumped (rank 10 if exists)
    IF v_new_rank <= 10 AND v_previous_rank IS NULL THEN
        SELECT wallet, rank INTO v_bumped_wallet, v_bumped_rank
        FROM vault_leaderboards
        WHERE vault_signature = p_vault_signature AND rank = 10;
    END IF;

    -- Remove user's existing entry if they're moving
    DELETE FROM vault_leaderboards
    WHERE vault_signature = p_vault_signature AND wallet = p_wallet;

    -- Bump everyone below new rank down by 1
    UPDATE vault_leaderboards SET rank = rank + 1
    WHERE vault_signature = p_vault_signature AND rank >= v_new_rank;

    -- Remove anyone pushed past rank 10
    DELETE FROM vault_leaderboards
    WHERE vault_signature = p_vault_signature AND rank > 10;

    -- Insert new entry
    INSERT INTO vault_leaderboards (
        vault_signature, rank, wallet, best_time_seconds,
        avg_power_w, completion_id, achieved_at
    )
    VALUES (
        p_vault_signature, v_new_rank, p_wallet, p_time_seconds,
        p_avg_power_w, p_completion_id, v_achieved_at
    );

    v_is_kom := (v_new_rank = 1);

    RETURN QUERY SELECT v_new_rank, v_is_kom, v_previous_rank, v_bumped_wallet, v_bumped_rank;
END;
$$ LANGUAGE plpgsql;

COMMENT ON FUNCTION update_vault_leaderboard_with_notifications IS
'Updates leaderboard and returns info needed for notifications (new rank, bumped user, etc.)';

-- =============================================================================
-- BATCH CREATE PAYOUT NOTIFICATIONS
-- Creates notifications for all payout recipients in a distribution
-- =============================================================================

CREATE OR REPLACE FUNCTION create_payout_notifications(
    p_vault_name TEXT,
    p_vault_signature TEXT,
    p_epoch INTEGER,
    p_receipts JSONB  -- Array of {wallet, receipt_type, amount, rank}
) RETURNS INTEGER AS $$
DECLARE
    v_receipt JSONB;
    v_wallet TEXT;
    v_type TEXT;
    v_amount NUMERIC;
    v_rank INTEGER;
    v_notification_type TEXT;
    v_count INTEGER := 0;
BEGIN
    FOR v_receipt IN SELECT * FROM jsonb_array_elements(p_receipts)
    LOOP
        v_wallet := v_receipt->>'wallet';
        v_type := v_receipt->>'receipt_type';
        v_amount := (v_receipt->>'amount')::NUMERIC;
        v_rank := (v_receipt->>'rank')::INTEGER;

        -- Skip POL and PROTOCOL receipts (they're not user wallets)
        IF v_type IN ('POL', 'PROTOCOL') THEN
            CONTINUE;
        END IF;

        -- Map receipt type to notification type
        CASE v_type
            WHEN 'LEADERBOARD' THEN v_notification_type := 'payout_received';
            WHEN 'STAKE' THEN v_notification_type := 'stake_payout';
            WHEN 'LOCAL_LEGEND' THEN v_notification_type := 'legend_payout';
            ELSE v_notification_type := 'payout_received';
        END CASE;

        -- Create notification
        PERFORM create_leaderboard_notification(
            p_wallet := v_wallet,
            p_type := v_notification_type,
            p_vault_name := p_vault_name,
            p_vault_signature := p_vault_signature,
            p_rank := v_rank,
            p_payout_amount := v_amount
        );

        v_count := v_count + 1;
    END LOOP;

    RETURN v_count;
END;
$$ LANGUAGE plpgsql;

COMMENT ON FUNCTION create_payout_notifications IS
'Creates payout notifications for all recipients in a vault distribution';

-- =============================================================================
-- GET WALLET NOTIFICATIONS
-- Retrieves notifications for a wallet with optional filtering
-- =============================================================================

CREATE OR REPLACE FUNCTION get_wallet_notifications(
    p_wallet TEXT,
    p_limit INTEGER DEFAULT 50,
    p_unread_only BOOLEAN DEFAULT FALSE,
    p_notification_types TEXT[] DEFAULT NULL
) RETURNS TABLE (
    id UUID,
    notification_type TEXT,
    title TEXT,
    message TEXT,
    metadata JSONB,
    vault_signature TEXT,
    read BOOLEAN,
    read_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ
) AS $$
BEGIN
    RETURN QUERY
    SELECT
        n.id,
        n.notification_type,
        n.title,
        n.message,
        n.metadata,
        n.vault_signature,
        n.read,
        n.read_at,
        n.created_at
    FROM notifications n
    WHERE n.wallet = p_wallet
      AND (NOT p_unread_only OR n.read = FALSE)
      AND (p_notification_types IS NULL OR n.notification_type = ANY(p_notification_types))
      AND n.dismissed_at IS NULL
    ORDER BY n.created_at DESC
    LIMIT p_limit;
END;
$$ LANGUAGE plpgsql STABLE;

COMMENT ON FUNCTION get_wallet_notifications IS
'Retrieves notifications for a wallet with optional filtering';

-- =============================================================================
-- MARK NOTIFICATIONS READ BY WALLET
-- =============================================================================

CREATE OR REPLACE FUNCTION mark_wallet_notifications_read(
    p_wallet TEXT,
    p_notification_ids UUID[] DEFAULT NULL
) RETURNS INTEGER AS $$
DECLARE
    v_count INTEGER;
BEGIN
    IF p_notification_ids IS NULL THEN
        -- Mark all unread notifications as read
        UPDATE notifications
        SET read = TRUE, read_at = now()
        WHERE wallet = p_wallet AND read = FALSE;
    ELSE
        -- Mark specific notifications as read
        UPDATE notifications
        SET read = TRUE, read_at = now()
        WHERE wallet = p_wallet
          AND id = ANY(p_notification_ids)
          AND read = FALSE;
    END IF;

    GET DIAGNOSTICS v_count = ROW_COUNT;
    RETURN v_count;
END;
$$ LANGUAGE plpgsql;

COMMENT ON FUNCTION mark_wallet_notifications_read IS
'Marks notifications as read for a wallet (all or specific IDs)';

-- =============================================================================
-- GET UNREAD COUNT BY WALLET
-- =============================================================================

CREATE OR REPLACE FUNCTION get_wallet_unread_count(p_wallet TEXT)
RETURNS INTEGER AS $$
BEGIN
    RETURN (
        SELECT COUNT(*)::INTEGER
        FROM notifications
        WHERE wallet = p_wallet
          AND read = FALSE
          AND dismissed_at IS NULL
    );
END;
$$ LANGUAGE plpgsql STABLE;

COMMENT ON FUNCTION get_wallet_unread_count IS
'Returns count of unread notifications for a wallet';
