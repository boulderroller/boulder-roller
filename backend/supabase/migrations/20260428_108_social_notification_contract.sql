-- Social notifications must be readable through the same wallet-addressed
-- notification rail as leaderboard and payout notifications.

ALTER TABLE IF EXISTS notifications
    ADD COLUMN IF NOT EXISTS metadata JSONB DEFAULT '{}'::jsonb;

ALTER TABLE IF EXISTS notifications
    ADD COLUMN IF NOT EXISTS data JSONB DEFAULT '{}'::jsonb;

UPDATE notifications AS n
SET wallet = u.wallet
FROM users AS u
WHERE n.user_id = u.id
  AND n.wallet IS NULL;

UPDATE notifications
SET metadata = COALESCE(metadata, data, '{}'::jsonb),
    data = COALESCE(data, metadata, '{}'::jsonb)
WHERE metadata IS NULL
   OR data IS NULL;

CREATE INDEX IF NOT EXISTS idx_notifications_user_wallet
    ON notifications(user_id, wallet, created_at DESC);
