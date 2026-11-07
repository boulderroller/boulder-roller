-- 072_strava_webhooks.sql
-- Strava webhook subscriptions and backfill tracking

-- Webhook subscription management
CREATE TABLE IF NOT EXISTS strava_webhook_subscriptions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    subscription_id BIGINT UNIQUE,
    verify_token TEXT NOT NULL,
    callback_url TEXT NOT NULL,
    created_at TIMESTAMPTZ DEFAULT now(),
    is_active BOOLEAN DEFAULT true
);

-- Add webhook/backfill columns to strava_connections
ALTER TABLE strava_connections ADD COLUMN IF NOT EXISTS last_webhook_at TIMESTAMPTZ;
ALTER TABLE strava_connections ADD COLUMN IF NOT EXISTS backfill_status TEXT DEFAULT 'none';
ALTER TABLE strava_connections ADD COLUMN IF NOT EXISTS backfill_cursor INTEGER DEFAULT 0;
ALTER TABLE strava_connections ADD COLUMN IF NOT EXISTS total_activities_synced INTEGER DEFAULT 0;
