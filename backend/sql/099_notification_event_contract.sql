-- Migration: 099_notification_event_contract.sql
-- Description: Add canonical notification.v1 contract fields and inbox prefs
-- Date: 2026-04-30

-- =============================================================================
-- NOTIFICATION EVENT CONTRACT
-- =============================================================================

ALTER TABLE notifications
    ADD COLUMN IF NOT EXISTS schema_version VARCHAR(40) DEFAULT 'notification.v1',
    ADD COLUMN IF NOT EXISTS event_type VARCHAR(80),
    ADD COLUMN IF NOT EXISTS actor_id UUID REFERENCES users(id) ON DELETE SET NULL,
    ADD COLUMN IF NOT EXISTS target_type VARCHAR(50),
    ADD COLUMN IF NOT EXISTS target_id TEXT,
    ADD COLUMN IF NOT EXISTS occurred_at TIMESTAMPTZ DEFAULT now(),
    ADD COLUMN IF NOT EXISTS delivery_status VARCHAR(40) DEFAULT 'in_app_delivered',
    ADD COLUMN IF NOT EXISTS delivery_channels JSONB DEFAULT '["in_app"]'::jsonb,
    ADD COLUMN IF NOT EXISTS dedupe_key TEXT;

UPDATE notifications
SET
    schema_version = COALESCE(schema_version, 'notification.v1'),
    event_type = COALESCE(event_type, notification_type),
    occurred_at = COALESCE(occurred_at, created_at, now()),
    delivery_status = COALESCE(delivery_status, 'in_app_delivered'),
    delivery_channels = COALESCE(delivery_channels, '["in_app"]'::jsonb)
WHERE
    schema_version IS NULL
    OR event_type IS NULL
    OR occurred_at IS NULL
    OR delivery_status IS NULL
    OR delivery_channels IS NULL;

ALTER TABLE notifications
    DROP CONSTRAINT IF EXISTS notifications_delivery_status_check;

ALTER TABLE notifications
    ADD CONSTRAINT notifications_delivery_status_check
    CHECK (delivery_status IN ('pending', 'in_app_delivered', 'suppressed', 'failed'));

CREATE INDEX IF NOT EXISTS idx_notifications_event_occurred
    ON notifications(event_type, occurred_at DESC);

CREATE INDEX IF NOT EXISTS idx_notifications_target
    ON notifications(target_type, target_id)
    WHERE target_type IS NOT NULL AND target_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_notifications_actor
    ON notifications(actor_id, occurred_at DESC)
    WHERE actor_id IS NOT NULL;

CREATE UNIQUE INDEX IF NOT EXISTS idx_notifications_dedupe_key
    ON notifications(dedupe_key)
    WHERE dedupe_key IS NOT NULL;

-- =============================================================================
-- NOTIFICATION PREFERENCES
-- =============================================================================

ALTER TABLE notification_preferences
    ADD COLUMN IF NOT EXISTS in_app_enabled BOOLEAN DEFAULT TRUE,
    ADD COLUMN IF NOT EXISTS social_activity BOOLEAN DEFAULT TRUE,
    ADD COLUMN IF NOT EXISTS leaderboard_updates BOOLEAN DEFAULT TRUE,
    ADD COLUMN IF NOT EXISTS payout_alerts BOOLEAN DEFAULT TRUE,
    ADD COLUMN IF NOT EXISTS system_announcements BOOLEAN DEFAULT TRUE,
    ADD COLUMN IF NOT EXISTS security_alerts BOOLEAN DEFAULT TRUE,
    ADD COLUMN IF NOT EXISTS connected_app_alerts BOOLEAN DEFAULT TRUE,
    ADD COLUMN IF NOT EXISTS ride_updates BOOLEAN DEFAULT TRUE,
    ADD COLUMN IF NOT EXISTS follow_created BOOLEAN DEFAULT TRUE,
    ADD COLUMN IF NOT EXISTS comment_created BOOLEAN DEFAULT TRUE,
    ADD COLUMN IF NOT EXISTS kudos_created BOOLEAN DEFAULT TRUE,
    ADD COLUMN IF NOT EXISTS ride_finalized BOOLEAN DEFAULT TRUE,
    ADD COLUMN IF NOT EXISTS ride_failed BOOLEAN DEFAULT TRUE,
    ADD COLUMN IF NOT EXISTS leaderboard_entered BOOLEAN DEFAULT TRUE,
    ADD COLUMN IF NOT EXISTS leaderboard_bumped BOOLEAN DEFAULT TRUE,
    ADD COLUMN IF NOT EXISTS rank_changed BOOLEAN DEFAULT TRUE,
    ADD COLUMN IF NOT EXISTS record_rank_moved BOOLEAN DEFAULT TRUE,
    ADD COLUMN IF NOT EXISTS kom_achieved BOOLEAN DEFAULT TRUE,
    ADD COLUMN IF NOT EXISTS local_legend_moved BOOLEAN DEFAULT TRUE,
    ADD COLUMN IF NOT EXISTS payout_received BOOLEAN DEFAULT TRUE,
    ADD COLUMN IF NOT EXISTS stake_payout BOOLEAN DEFAULT TRUE,
    ADD COLUMN IF NOT EXISTS legend_payout BOOLEAN DEFAULT TRUE,
    ADD COLUMN IF NOT EXISTS report_resolved BOOLEAN DEFAULT TRUE,
    ADD COLUMN IF NOT EXISTS proof_updated BOOLEAN DEFAULT TRUE,
    ADD COLUMN IF NOT EXISTS settlement_finalized BOOLEAN DEFAULT TRUE,
    ADD COLUMN IF NOT EXISTS tier_unlocked BOOLEAN DEFAULT TRUE,
    ADD COLUMN IF NOT EXISTS login_new_device BOOLEAN DEFAULT TRUE,
    ADD COLUMN IF NOT EXISTS session_revoked BOOLEAN DEFAULT TRUE,
    ADD COLUMN IF NOT EXISTS strava_revoked BOOLEAN DEFAULT TRUE;

-- =============================================================================
-- WALLET NOTIFICATION RPC
-- =============================================================================

DROP FUNCTION IF EXISTS get_wallet_notifications(TEXT, INTEGER, BOOLEAN, TEXT[]);

CREATE OR REPLACE FUNCTION get_wallet_notifications(
    p_wallet TEXT,
    p_limit INTEGER DEFAULT 50,
    p_unread_only BOOLEAN DEFAULT FALSE,
    p_notification_types TEXT[] DEFAULT NULL
) RETURNS TABLE (
    id UUID,
    user_id UUID,
    wallet TEXT,
    notification_type TEXT,
    schema_version TEXT,
    event_type TEXT,
    actor_id UUID,
    target_type TEXT,
    target_id TEXT,
    title TEXT,
    message TEXT,
    data JSONB,
    metadata JSONB,
    delivery_status TEXT,
    delivery_channels JSONB,
    dedupe_key TEXT,
    vault_signature TEXT,
    read BOOLEAN,
    read_at TIMESTAMPTZ,
    occurred_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ
) AS $$
BEGIN
    RETURN QUERY
    SELECT
        n.id,
        n.user_id,
        n.wallet,
        n.notification_type::TEXT,
        COALESCE(n.schema_version, 'notification.v1')::TEXT,
        COALESCE(n.event_type, n.notification_type)::TEXT,
        n.actor_id,
        n.target_type::TEXT,
        n.target_id::TEXT,
        n.title,
        n.message,
        n.data,
        COALESCE(n.metadata, n.data, '{}'::jsonb),
        COALESCE(n.delivery_status, 'in_app_delivered')::TEXT,
        COALESCE(n.delivery_channels, '["in_app"]'::jsonb),
        n.dedupe_key,
        n.vault_signature,
        n.read,
        n.read_at,
        COALESCE(n.occurred_at, n.created_at),
        n.created_at
    FROM notifications n
    WHERE n.wallet = p_wallet
      AND (NOT p_unread_only OR n.read = FALSE)
      AND (
        p_notification_types IS NULL
        OR n.notification_type = ANY(p_notification_types)
        OR n.event_type = ANY(p_notification_types)
      )
      AND n.dismissed_at IS NULL
    ORDER BY COALESCE(n.occurred_at, n.created_at) DESC
    LIMIT p_limit;
END;
$$ LANGUAGE plpgsql STABLE;

COMMENT ON FUNCTION get_wallet_notifications IS
'Retrieves notification.v1 inbox rows for a wallet with optional filtering';
