-- Migration: 031_points_period.sql
-- Description: Points period infrastructure for pre-TGE testing
-- Date: 2024-12-24

-- =============================================================================
-- POINTS PERIOD INFRASTRUCTURE
-- Off-chain points during testing phase, converted to DUNG at TGE
-- Everything is denominated in points (not DUNG) during testing
-- =============================================================================

-- Wallet point balances
CREATE TABLE IF NOT EXISTS wallet_points (
    wallet TEXT PRIMARY KEY,
    total_points NUMERIC NOT NULL DEFAULT 0,
    points_from_tss NUMERIC NOT NULL DEFAULT 0,
    points_from_creation NUMERIC NOT NULL DEFAULT 0,
    points_from_referral NUMERIC NOT NULL DEFAULT 0,
    points_from_leaderboard NUMERIC NOT NULL DEFAULT 0,
    points_from_staking NUMERIC NOT NULL DEFAULT 0,
    lifetime_points_earned NUMERIC NOT NULL DEFAULT 0,
    referred_by TEXT REFERENCES wallet_points(wallet),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

COMMENT ON TABLE wallet_points IS 'Point balances during pre-TGE testing period';
COMMENT ON COLUMN wallet_points.total_points IS 'Sum of all point sources';
COMMENT ON COLUMN wallet_points.points_from_tss IS 'Points earned from TSS (1:1 ratio)';
COMMENT ON COLUMN wallet_points.points_from_creation IS 'Deprecated: vault creation does not spend points';
COMMENT ON COLUMN wallet_points.points_from_leaderboard IS 'Points earned from leaderboard payouts';
COMMENT ON COLUMN wallet_points.points_from_staking IS 'Points earned from staking distributions';
COMMENT ON COLUMN wallet_points.lifetime_points_earned IS 'Total lifetime points earned (non-decreasing)';

-- Point earning events (audit trail)
CREATE TABLE IF NOT EXISTS points_events (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    wallet TEXT NOT NULL REFERENCES wallet_points(wallet),
    event_type TEXT NOT NULL,
    points_delta NUMERIC NOT NULL,
    points_after NUMERIC NOT NULL,
    reference_type TEXT,
    reference_id TEXT,
    metadata JSONB DEFAULT '{}',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Add constraint for event types
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'chk_points_event_type'
    ) THEN
        ALTER TABLE points_events
            ADD CONSTRAINT chk_points_event_type
            CHECK (event_type IN (
                'TSS_EARN',              -- Ride upload
                'VAULT_COMPLETION',      -- Vault completion bonus
                'LEADERBOARD_PAYOUT',    -- Leaderboard distribution
                'LOCAL_LEGEND_EARNINGS', -- Local legend distribution
                'REFERRAL_BONUS',        -- Referral bonus
                'STAKE_EARNINGS',        -- Staker distribution
                'STAKE_DEPOSIT',         -- Stake allocation (no points spent)
                'STAKE_WITHDRAW',        -- Unstake allocation (no points spent)
                'TGE_CONVERT',           -- Conversion to DUNG at TGE
                'ADMIN_ADJUST'           -- Admin adjustment
            ));
    END IF;
END $$;

CREATE INDEX IF NOT EXISTS idx_points_events_wallet ON points_events(wallet);
CREATE INDEX IF NOT EXISTS idx_points_events_type ON points_events(event_type);
CREATE INDEX IF NOT EXISTS idx_points_events_created ON points_events(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_points_events_ref ON points_events(reference_type, reference_id);

COMMENT ON TABLE points_events IS 'Full audit trail of all point changes';
COMMENT ON COLUMN points_events.event_type IS 'Type of event that caused point change';
COMMENT ON COLUMN points_events.reference_type IS 'Type of related entity (activity, vault, user)';
COMMENT ON COLUMN points_events.reference_id IS 'ID of related entity';

-- TGE conversion tracking (when we flip the switch)
CREATE TABLE IF NOT EXISTS tge_conversions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    wallet TEXT NOT NULL REFERENCES wallet_points(wallet),
    points_converted NUMERIC NOT NULL,
    dung_received NUMERIC NOT NULL,
    conversion_tier TEXT NOT NULL,
    conversion_ratio NUMERIC NOT NULL,
    vested_amount NUMERIC NOT NULL,
    unlocked_amount NUMERIC NOT NULL,
    tx_signature TEXT,
    converted_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Add constraint for conversion tiers
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'chk_tge_conversion_tier'
    ) THEN
        ALTER TABLE tge_conversions
            ADD CONSTRAINT chk_tge_conversion_tier
            CHECK (conversion_tier IN ('TIER_1', 'TIER_2', 'TIER_3', 'TIER_4'));
    END IF;
END $$;

CREATE INDEX IF NOT EXISTS idx_tge_conversions_wallet ON tge_conversions(wallet);

COMMENT ON TABLE tge_conversions IS 'Records of points→DUNG conversions at TGE';
COMMENT ON COLUMN tge_conversions.vested_amount IS '75% of DUNG vested over 12 months';
COMMENT ON COLUMN tge_conversions.unlocked_amount IS '25% of DUNG unlocked at TGE';

-- Points period config (singleton)
CREATE TABLE IF NOT EXISTS points_config (
    id INTEGER PRIMARY KEY DEFAULT 1 CHECK (id = 1),
    is_active BOOLEAN NOT NULL DEFAULT true,
    tge_date TIMESTAMPTZ,
    -- Points per DUNG equivalent (for staking/vault costs)
    points_per_dung NUMERIC NOT NULL DEFAULT 1000,
    -- Tiered conversion ratios
    tier_1_limit NUMERIC NOT NULL DEFAULT 10000,
    tier_1_ratio NUMERIC NOT NULL DEFAULT 1000,
    tier_2_limit NUMERIC NOT NULL DEFAULT 50000,
    tier_2_ratio NUMERIC NOT NULL DEFAULT 1500,
    tier_3_limit NUMERIC NOT NULL DEFAULT 200000,
    tier_3_ratio NUMERIC NOT NULL DEFAULT 2000,
    tier_4_ratio NUMERIC NOT NULL DEFAULT 3000,
    -- Vesting split
    tge_unlock_pct NUMERIC NOT NULL DEFAULT 25,
    vesting_months INTEGER NOT NULL DEFAULT 12,
    updated_at TIMESTAMPTZ DEFAULT now()
);

INSERT INTO points_config (id) VALUES (1) ON CONFLICT DO NOTHING;

COMMENT ON TABLE points_config IS 'Singleton config for points period parameters';
COMMENT ON COLUMN points_config.is_active IS 'Whether points mode is active (false = CAL mode)';
COMMENT ON COLUMN points_config.points_per_dung IS 'Points equivalent for 1 DUNG (e.g., 1000 pts = 1 DUNG equiv)';
COMMENT ON COLUMN points_config.tier_1_ratio IS 'First 10K points convert at 1000:1';

-- =============================================================================
-- HELPER FUNCTIONS
-- =============================================================================

-- Function to add points with audit trail
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

COMMENT ON FUNCTION add_points IS 'Add/subtract points with full audit trail';

-- =============================================================================
-- ENTITLEMENTS
-- =============================================================================

CREATE TABLE IF NOT EXISTS points_entitlement_config (
    id INTEGER PRIMARY KEY DEFAULT 1 CHECK (id = 1),
    per_vault_stake_cap NUMERIC NOT NULL DEFAULT 1000,
    updated_at TIMESTAMPTZ DEFAULT now()
);

INSERT INTO points_entitlement_config (id) VALUES (1) ON CONFLICT DO NOTHING;

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

INSERT INTO points_entitlement_tiers (min_points, vaults_unlocked, stake_cap_points, stake_multiplier)
SELECT * FROM (
    VALUES
        (0, 0, 0, 1.00),
        (5000, 1, 1000, 1.05),
        (25000, 5, 5000, 1.10),
        (100000, 10, 10000, 1.15)
) AS v(min_points, vaults_unlocked, stake_cap_points, stake_multiplier)
WHERE NOT EXISTS (SELECT 1 FROM points_entitlement_tiers);

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

-- Function to check if points period is active
CREATE OR REPLACE FUNCTION is_points_period_active() RETURNS BOOLEAN AS $$
BEGIN
    RETURN (SELECT is_active FROM points_config WHERE id = 1);
END;
$$ LANGUAGE plpgsql STABLE;

-- Function to get points-per-dung conversion rate
CREATE OR REPLACE FUNCTION get_points_per_dung() RETURNS NUMERIC AS $$
BEGIN
    RETURN (SELECT points_per_dung FROM points_config WHERE id = 1);
END;
$$ LANGUAGE plpgsql STABLE;
