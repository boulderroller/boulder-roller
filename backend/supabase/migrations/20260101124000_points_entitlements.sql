-- Points entitlements and lifetime points tracking

ALTER TABLE wallet_points
    ADD COLUMN IF NOT EXISTS lifetime_points_earned NUMERIC NOT NULL DEFAULT 0;

COMMENT ON COLUMN wallet_points.lifetime_points_earned IS 'Total lifetime points earned (non-decreasing)';

-- Backfill lifetime points for existing wallets (best-effort)
UPDATE wallet_points
SET lifetime_points_earned = total_points
WHERE lifetime_points_earned = 0;

-- Entitlement config (singleton)
CREATE TABLE IF NOT EXISTS points_entitlement_config (
    id INTEGER PRIMARY KEY DEFAULT 1 CHECK (id = 1),
    per_vault_stake_cap NUMERIC NOT NULL DEFAULT 1000,
    updated_at TIMESTAMPTZ DEFAULT now()
);

INSERT INTO points_entitlement_config (id) VALUES (1) ON CONFLICT DO NOTHING;

COMMENT ON TABLE points_entitlement_config IS 'Config for points entitlements and staking caps';
COMMENT ON COLUMN points_entitlement_config.per_vault_stake_cap IS 'Max points stake per vault (default 1,000)';

-- Entitlement tiers
CREATE TABLE IF NOT EXISTS points_entitlement_tiers (
    id SERIAL PRIMARY KEY,
    min_points NUMERIC NOT NULL,
    vaults_unlocked INTEGER NOT NULL,
    stake_cap_points NUMERIC NOT NULL,
    stake_multiplier NUMERIC NOT NULL,
    updated_at TIMESTAMPTZ DEFAULT now()
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_points_entitlement_tiers_min_points
    ON points_entitlement_tiers(min_points);

COMMENT ON TABLE points_entitlement_tiers IS 'Lifetime points tiers for vault/stake entitlements';

-- Default tiers (only insert if empty)
INSERT INTO points_entitlement_tiers (min_points, vaults_unlocked, stake_cap_points, stake_multiplier)
SELECT * FROM (
    VALUES
        (0, 0, 0, 1.00),
        (5000, 1, 1000, 1.05),
        (25000, 5, 5000, 1.10),
        (100000, 10, 10000, 1.15)
) AS v(min_points, vaults_unlocked, stake_cap_points, stake_multiplier)
WHERE NOT EXISTS (SELECT 1 FROM points_entitlement_tiers);

-- Update points event types to include staking and stake earnings
ALTER TABLE points_events DROP CONSTRAINT IF EXISTS chk_points_event_type;
ALTER TABLE points_events
    ADD CONSTRAINT chk_points_event_type
    CHECK (event_type IN (
        'TSS_EARN',
        'VAULT_COMPLETION',
        'LEADERBOARD_PAYOUT',
        'LOCAL_LEGEND_EARNINGS',
        'REFERRAL_BONUS',
        'STAKE_EARNINGS',
        'STAKE_DEPOSIT',
        'STAKE_WITHDRAW',
        'TGE_CONVERT',
        'ADMIN_ADJUST'
    ));

-- Update add_points to track lifetime points and new event types
CREATE OR REPLACE FUNCTION add_points(
    p_wallet TEXT,
    p_amount NUMERIC,
    p_event_type TEXT,
    p_reference_type TEXT DEFAULT NULL,
    p_reference_id TEXT DEFAULT NULL,
    p_metadata JSONB DEFAULT '{}'
) RETURNS NUMERIC AS $$
DECLARE
    new_total NUMERIC;
BEGIN
    -- Upsert wallet_points
    INSERT INTO wallet_points (wallet, total_points)
    VALUES (p_wallet, p_amount)
    ON CONFLICT (wallet) DO UPDATE SET
        total_points = wallet_points.total_points + p_amount,
        updated_at = now()
    RETURNING total_points INTO new_total;

    -- Update category-specific column based on event type
    IF p_event_type = 'TSS_EARN' THEN
        UPDATE wallet_points SET points_from_tss = points_from_tss + p_amount WHERE wallet = p_wallet;
    ELSIF p_event_type = 'VAULT_COMPLETION' THEN
        UPDATE wallet_points SET points_from_tss = points_from_tss + p_amount WHERE wallet = p_wallet;
    ELSIF p_event_type = 'STAKE_EARNINGS' THEN
        UPDATE wallet_points SET points_from_staking = points_from_staking + p_amount WHERE wallet = p_wallet;
    ELSIF p_event_type = 'LEADERBOARD_PAYOUT' THEN
        UPDATE wallet_points SET points_from_leaderboard = points_from_leaderboard + p_amount WHERE wallet = p_wallet;
    ELSIF p_event_type = 'LOCAL_LEGEND_EARNINGS' THEN
        UPDATE wallet_points SET points_from_leaderboard = points_from_leaderboard + p_amount WHERE wallet = p_wallet;
    ELSIF p_event_type = 'REFERRAL_BONUS' THEN
        UPDATE wallet_points SET points_from_referral = points_from_referral + p_amount WHERE wallet = p_wallet;
    END IF;

    -- Track lifetime points earned (only on positive earning events)
    IF p_amount > 0 AND p_event_type IN (
        'TSS_EARN',
        'VAULT_COMPLETION',
        'LEADERBOARD_PAYOUT',
        'LOCAL_LEGEND_EARNINGS',
        'REFERRAL_BONUS',
        'STAKE_EARNINGS'
    ) THEN
        UPDATE wallet_points
        SET lifetime_points_earned = lifetime_points_earned + p_amount
        WHERE wallet = p_wallet;
    END IF;

    -- Record event
    INSERT INTO points_events (wallet, event_type, points_delta, points_after, reference_type, reference_id, metadata)
    VALUES (p_wallet, p_event_type, p_amount, new_total, p_reference_type, p_reference_id, p_metadata);

    RETURN new_total;
END;
$$ LANGUAGE plpgsql;

COMMENT ON FUNCTION add_points IS 'Add/subtract points with full audit trail and lifetime tracking';

-- Helper: entitlements snapshot for a wallet
CREATE OR REPLACE FUNCTION get_wallet_entitlements(
    p_wallet TEXT
) RETURNS TABLE (
    lifetime_points_earned NUMERIC,
    vaults_unlocked INTEGER,
    vaults_used INTEGER,
    stake_cap_points NUMERIC,
    stake_used_points NUMERIC,
    stake_multiplier NUMERIC,
    per_vault_stake_cap NUMERIC
) AS $$
BEGIN
    RETURN QUERY
    WITH wp AS (
        SELECT lifetime_points_earned
        FROM wallet_points
        WHERE wallet = p_wallet
    ),
    tier AS (
        SELECT *
        FROM points_entitlement_tiers
        WHERE min_points <= COALESCE((SELECT lifetime_points_earned FROM wp), 0)
        ORDER BY min_points DESC
        LIMIT 1
    ),
    vaults_used AS (
        SELECT COUNT(*)::INT AS count
        FROM indexed_vaults
        WHERE minter = p_wallet
    ),
    stake_used AS (
        SELECT COALESCE(SUM(points_staked), 0) AS total
        FROM vault_stakes
        WHERE wallet = p_wallet
          AND unstaked_at IS NULL
    ),
    cfg AS (
        SELECT per_vault_stake_cap
        FROM points_entitlement_config
        WHERE id = 1
    )
    SELECT
        COALESCE((SELECT lifetime_points_earned FROM wp), 0),
        COALESCE((SELECT vaults_unlocked FROM tier), 0),
        COALESCE((SELECT count FROM vaults_used), 0),
        COALESCE((SELECT stake_cap_points FROM tier), 0),
        COALESCE((SELECT total FROM stake_used), 0),
        COALESCE((SELECT stake_multiplier FROM tier), 1.00),
        COALESCE((SELECT per_vault_stake_cap FROM cfg), 1000);
END;
$$ LANGUAGE plpgsql STABLE;

COMMENT ON FUNCTION get_wallet_entitlements IS 'Get lifetime points entitlements, vault usage, and staking caps';
