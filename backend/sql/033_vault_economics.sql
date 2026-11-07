-- Migration: 033_vault_economics.sql
-- Description: Vault distribution redesign with leaderboard-heavy model
-- Date: 2024-12-24

-- =============================================================================
-- VAULT DISTRIBUTION CONFIG
-- Leaderboard-heavy model: 55% leaderboard, 27% stakers, 3% Local Legend, 5% POL, 10% protocol
-- =============================================================================

CREATE TABLE IF NOT EXISTS vault_distribution_config (
    id INTEGER PRIMARY KEY DEFAULT 1 CHECK (id = 1),
    -- Main splits (basis points, must sum to 10000)
    leaderboard_share_bps INTEGER NOT NULL DEFAULT 5500,
    staker_share_bps INTEGER NOT NULL DEFAULT 2700,
    local_legend_share_bps INTEGER NOT NULL DEFAULT 300,
    pol_share_bps INTEGER NOT NULL DEFAULT 500,
    protocol_fee_bps INTEGER NOT NULL DEFAULT 1000,
    -- Leaderboard breakdown (top 10, must sum to 100)
    leaderboard_pcts JSONB NOT NULL DEFAULT '[30, 20, 15, 10, 8, 6, 5, 3, 2, 1]',
    -- Epoch timing
    distribution_epoch_hours INTEGER NOT NULL DEFAULT 168,
    -- Token accounts (optional, for on-chain distributions)
    pol_account TEXT,
    protocol_treasury TEXT,
    -- Tracking
    updated_at TIMESTAMPTZ DEFAULT now(),
    -- Constraints
    CONSTRAINT bps_sum CHECK (
        leaderboard_share_bps + staker_share_bps + local_legend_share_bps + pol_share_bps + protocol_fee_bps = 10000
    )
);

INSERT INTO vault_distribution_config (id) VALUES (1) ON CONFLICT DO NOTHING;

COMMENT ON TABLE vault_distribution_config IS 'Singleton config for vault distribution splits';
COMMENT ON COLUMN vault_distribution_config.leaderboard_share_bps IS '55% to top 10 leaderboard';
COMMENT ON COLUMN vault_distribution_config.staker_share_bps IS '27% to vault stakers';
COMMENT ON COLUMN vault_distribution_config.local_legend_share_bps IS '3% to Local Legend';
COMMENT ON COLUMN vault_distribution_config.pol_share_bps IS '5% protocol-owned liquidity';
COMMENT ON COLUMN vault_distribution_config.protocol_fee_bps IS '10% protocol fee';
COMMENT ON COLUMN vault_distribution_config.leaderboard_pcts IS 'Distribution % per rank [1st, 2nd, ...10th]';
COMMENT ON COLUMN vault_distribution_config.pol_account IS 'Token account for protocol-owned liquidity';
COMMENT ON COLUMN vault_distribution_config.protocol_treasury IS 'Token account for protocol treasury';

-- =============================================================================
-- VAULT STAKING POSITIONS
-- Points during testing, converts to DUNG at TGE
-- =============================================================================

CREATE TABLE IF NOT EXISTS vault_stakes (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    vault_signature TEXT NOT NULL,
    wallet TEXT NOT NULL,
    -- Points staking (testing period)
    points_staked NUMERIC NOT NULL DEFAULT 0,
    -- DUNG staking (post-TGE, populated at conversion)
    dung_staked NUMERIC,
    -- LP tokens for proportional earnings
    lp_tokens NUMERIC NOT NULL DEFAULT 0,
    -- Timestamps
    staked_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    unstaked_at TIMESTAMPTZ,
    converted_at TIMESTAMPTZ,
    -- Constraints
    UNIQUE (vault_signature, wallet)
);

CREATE INDEX IF NOT EXISTS idx_vault_stakes_vault ON vault_stakes(vault_signature);
CREATE INDEX IF NOT EXISTS idx_vault_stakes_wallet ON vault_stakes(wallet);
CREATE INDEX IF NOT EXISTS idx_vault_stakes_active ON vault_stakes(vault_signature) WHERE unstaked_at IS NULL;

COMMENT ON TABLE vault_stakes IS 'Staking positions in vaults (points during testing, DUNG post-TGE)';
COMMENT ON COLUMN vault_stakes.points_staked IS 'Points staked during testing period';
COMMENT ON COLUMN vault_stakes.dung_staked IS 'DUNG value, populated at TGE conversion';
COMMENT ON COLUMN vault_stakes.lp_tokens IS 'Proportional share of vault earnings';

-- =============================================================================
-- VAULT LEADERBOARD (CACHED)
-- Top 10 per vault, updated on completion
-- =============================================================================

CREATE TABLE IF NOT EXISTS vault_leaderboards (
    vault_signature TEXT NOT NULL,
    rank INTEGER NOT NULL CHECK (rank >= 1 AND rank <= 10),
    wallet TEXT NOT NULL,
    best_time_seconds INTEGER NOT NULL,
    avg_power_w INTEGER,
    completion_id UUID,
    achieved_at TIMESTAMPTZ NOT NULL,
    PRIMARY KEY (vault_signature, rank)
);

CREATE INDEX IF NOT EXISTS idx_vault_leaderboards_wallet ON vault_leaderboards(wallet);

COMMENT ON TABLE vault_leaderboards IS 'Cached top 10 for each vault';
COMMENT ON COLUMN vault_leaderboards.rank IS '1 = KOM, 2-10 = rest of podium';

-- =============================================================================
-- VAULT DISTRIBUTION EVENTS
-- Track what was distributed each epoch
-- =============================================================================

CREATE TABLE IF NOT EXISTS vault_distributions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    vault_signature TEXT NOT NULL,
    epoch INTEGER NOT NULL,
    is_points_period BOOLEAN NOT NULL DEFAULT true,
    -- Total distributed (points or DUNG)
    total_amount NUMERIC NOT NULL,
    -- Breakdown
    leaderboard_amount NUMERIC NOT NULL,
    staker_amount NUMERIC NOT NULL,
    local_legend_amount NUMERIC NOT NULL,
    pol_amount NUMERIC NOT NULL DEFAULT 0,
    protocol_amount NUMERIC NOT NULL,
    -- Leaderboard breakdown (JSON of rank → wallet → amount)
    leaderboard_details JSONB,
    -- Timestamps
    distributed_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    -- Unique per vault/epoch/period
    UNIQUE (vault_signature, epoch, is_points_period)
);

CREATE INDEX IF NOT EXISTS idx_vault_dist_vault ON vault_distributions(vault_signature);
CREATE INDEX IF NOT EXISTS idx_vault_dist_epoch ON vault_distributions(epoch);

COMMENT ON TABLE vault_distributions IS 'Distribution events per vault per epoch';
COMMENT ON COLUMN vault_distributions.is_points_period IS 'true = points, false = DUNG';
COMMENT ON COLUMN vault_distributions.pol_amount IS 'POL share of distribution (DUNG)';

-- =============================================================================
-- INDIVIDUAL DISTRIBUTION RECEIPTS
-- What each wallet received from each distribution
-- =============================================================================

CREATE TABLE IF NOT EXISTS distribution_receipts (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    distribution_id UUID NOT NULL REFERENCES vault_distributions(id),
    wallet TEXT NOT NULL,
    receipt_type TEXT NOT NULL,
    amount NUMERIC NOT NULL,
    rank INTEGER,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Add constraint for receipt types
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'chk_receipt_type'
    ) THEN
        ALTER TABLE distribution_receipts
            ADD CONSTRAINT chk_receipt_type
            CHECK (receipt_type IN ('LEADERBOARD', 'STAKE', 'LOCAL_LEGEND', 'POL', 'PROTOCOL'));
    END IF;
END $$;

CREATE INDEX IF NOT EXISTS idx_dist_receipts_dist ON distribution_receipts(distribution_id);
CREATE INDEX IF NOT EXISTS idx_dist_receipts_wallet ON distribution_receipts(wallet);
CREATE UNIQUE INDEX IF NOT EXISTS idx_dist_receipts_unique
    ON distribution_receipts(distribution_id, wallet, receipt_type);

COMMENT ON TABLE distribution_receipts IS 'Per-wallet breakdown of distributions';
COMMENT ON COLUMN distribution_receipts.rank IS 'Leaderboard rank (1-10) if receipt_type = LEADERBOARD';

-- =============================================================================
-- HELPER FUNCTIONS
-- =============================================================================

-- Function to calculate LP tokens for a stake
CREATE OR REPLACE FUNCTION calculate_lp_tokens(
    p_vault_signature TEXT,
    p_amount NUMERIC
) RETURNS NUMERIC AS $$
DECLARE
    total_staked NUMERIC;
    total_lp NUMERIC;
BEGIN
    -- Get current totals
    SELECT
        COALESCE(SUM(points_staked), 0),
        COALESCE(SUM(lp_tokens), 1)
    INTO total_staked, total_lp
    FROM vault_stakes
    WHERE vault_signature = p_vault_signature AND unstaked_at IS NULL;

    -- If first stake, 1:1 ratio
    IF total_staked = 0 THEN
        RETURN p_amount;
    END IF;

    -- Proportional LP tokens
    RETURN (p_amount * total_lp) / total_staked;
END;
$$ LANGUAGE plpgsql STABLE;

-- Function to stake points into vault
CREATE OR REPLACE FUNCTION stake_points(
    p_vault_signature TEXT,
    p_wallet TEXT,
    p_amount NUMERIC
) RETURNS BOOLEAN AS $$
DECLARE
    lp_tokens NUMERIC;
    min_stake NUMERIC;
BEGIN
    -- Get minimum stake from config (10,000 points = 10 DUNG equiv)
    min_stake := get_points_per_dung() * 10;

    IF p_amount < min_stake THEN
        RETURN FALSE;
    END IF;

    -- Calculate LP tokens
    lp_tokens := calculate_lp_tokens(p_vault_signature, p_amount);

    -- Upsert stake
    INSERT INTO vault_stakes (vault_signature, wallet, points_staked, lp_tokens)
    VALUES (p_vault_signature, p_wallet, p_amount, lp_tokens)
    ON CONFLICT (vault_signature, wallet) DO UPDATE SET
        points_staked = vault_stakes.points_staked + p_amount,
        lp_tokens = vault_stakes.lp_tokens + lp_tokens,
        unstaked_at = NULL;

    -- Record stake event (no points deducted during points period)
    PERFORM add_points(p_wallet, 0, 'STAKE_DEPOSIT', 'vault', p_vault_signature);

    RETURN TRUE;
END;
$$ LANGUAGE plpgsql;

-- Function to get leaderboard payout percentages
CREATE OR REPLACE FUNCTION get_leaderboard_pcts() RETURNS JSONB AS $$
BEGIN
    RETURN (SELECT leaderboard_pcts FROM vault_distribution_config WHERE id = 1);
END;
$$ LANGUAGE plpgsql STABLE;

-- Function to update leaderboard after completion
CREATE OR REPLACE FUNCTION update_vault_leaderboard(
    p_vault_signature TEXT,
    p_wallet TEXT,
    p_time_seconds INTEGER,
    p_avg_power_w INTEGER DEFAULT NULL,
    p_completion_id UUID DEFAULT NULL
) RETURNS INTEGER AS $$
DECLARE
    new_rank INTEGER := NULL;
    current RECORD;
    bump_wallet TEXT;
BEGIN
    -- Check if this time qualifies for top 10
    SELECT COUNT(*) + 1 INTO new_rank
    FROM vault_leaderboards
    WHERE vault_signature = p_vault_signature AND best_time_seconds < p_time_seconds;

    -- If not in top 10, check if we beat existing entry
    IF new_rank > 10 THEN
        -- Check if user has existing entry with worse time
        SELECT rank INTO new_rank
        FROM vault_leaderboards
        WHERE vault_signature = p_vault_signature AND wallet = p_wallet AND best_time_seconds > p_time_seconds;

        IF new_rank IS NULL THEN
            RETURN NULL; -- No leaderboard change
        END IF;
    END IF;

    -- Remove user's existing entry if they're moving up
    DELETE FROM vault_leaderboards WHERE vault_signature = p_vault_signature AND wallet = p_wallet;

    -- Bump everyone below new rank down by 1
    UPDATE vault_leaderboards SET rank = rank + 1
    WHERE vault_signature = p_vault_signature AND rank >= new_rank;

    -- Remove anyone pushed past rank 10
    DELETE FROM vault_leaderboards WHERE vault_signature = p_vault_signature AND rank > 10;

    -- Insert new entry
    INSERT INTO vault_leaderboards (vault_signature, rank, wallet, best_time_seconds, avg_power_w, completion_id, achieved_at)
    VALUES (p_vault_signature, new_rank, p_wallet, p_time_seconds, p_avg_power_w, p_completion_id, now());

    RETURN new_rank;
END;
$$ LANGUAGE plpgsql;

COMMENT ON FUNCTION update_vault_leaderboard IS 'Update leaderboard after a completion, returns new rank or NULL if not in top 10';
