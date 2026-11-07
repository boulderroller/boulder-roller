-- Migration: 032_supply_emissions.sql
-- Description: DUNG supply cap and halving emission schedule
-- Date: 2024-12-24

-- =============================================================================
-- DUNG SUPPLY CAP & HALVING EMISSIONS
-- On-chain enforcement of 1B max supply with Bitcoin-style halving
-- This table mirrors on-chain state for quick queries
-- =============================================================================

-- Supply state (singleton, mirrors on-chain)
CREATE TABLE IF NOT EXISTS dung_supply_state (
    id INTEGER PRIMARY KEY DEFAULT 1 CHECK (id = 1),
    -- Hard cap
    max_supply NUMERIC NOT NULL DEFAULT 1000000000,
    -- Current state
    total_minted NUMERIC NOT NULL DEFAULT 0,
    total_burned NUMERIC NOT NULL DEFAULT 0,
    -- Allocation caps (from TOKENOMICS_V2)
    community_minted NUMERIC NOT NULL DEFAULT 0,
    community_cap NUMERIC NOT NULL DEFAULT 400000000,
    treasury_minted NUMERIC NOT NULL DEFAULT 0,
    treasury_cap NUMERIC NOT NULL DEFAULT 250000000,
    team_minted NUMERIC NOT NULL DEFAULT 0,
    team_cap NUMERIC NOT NULL DEFAULT 200000000,
    investor_minted NUMERIC NOT NULL DEFAULT 0,
    investor_cap NUMERIC NOT NULL DEFAULT 100000000,
    pol_minted NUMERIC NOT NULL DEFAULT 0,
    pol_cap NUMERIC NOT NULL DEFAULT 50000000,
    -- Tracking
    updated_at TIMESTAMPTZ DEFAULT now(),
    -- Constraints
    CONSTRAINT supply_cap_check CHECK (total_minted <= max_supply),
    CONSTRAINT community_cap_check CHECK (community_minted <= community_cap),
    CONSTRAINT treasury_cap_check CHECK (treasury_minted <= treasury_cap),
    CONSTRAINT team_cap_check CHECK (team_minted <= team_cap),
    CONSTRAINT investor_cap_check CHECK (investor_minted <= investor_cap),
    CONSTRAINT pol_cap_check CHECK (pol_minted <= pol_cap)
);

-- Generated column for circulating supply
ALTER TABLE dung_supply_state
    ADD COLUMN IF NOT EXISTS circulating_supply NUMERIC
    GENERATED ALWAYS AS (total_minted - total_burned) STORED;

INSERT INTO dung_supply_state (id) VALUES (1) ON CONFLICT DO NOTHING;

COMMENT ON TABLE dung_supply_state IS 'Singleton tracking DUNG supply (mirrors on-chain)';
COMMENT ON COLUMN dung_supply_state.max_supply IS '1B hard cap, enforced on-chain';
COMMENT ON COLUMN dung_supply_state.community_cap IS '400M (40%) for community/points conversion';
COMMENT ON COLUMN dung_supply_state.treasury_cap IS '250M (25%) for treasury operations';
COMMENT ON COLUMN dung_supply_state.team_cap IS '200M (20%) for founder/team vesting';
COMMENT ON COLUMN dung_supply_state.investor_cap IS '100M (10%) for investors';
COMMENT ON COLUMN dung_supply_state.pol_cap IS '50M (5%) for protocol-owned liquidity';

-- =============================================================================
-- HALVING EMISSION SCHEDULE
-- Bitcoin-style halving every ~6 months
-- =============================================================================

CREATE TABLE IF NOT EXISTS emission_schedule (
    id INTEGER PRIMARY KEY DEFAULT 1 CHECK (id = 1),
    current_epoch INTEGER NOT NULL DEFAULT 1,
    epoch_start_date TIMESTAMPTZ NOT NULL DEFAULT now(),
    epoch_duration_days INTEGER NOT NULL DEFAULT 180,
    -- Emission rate (basis points, 10000 = 100%)
    base_emission_rate_bps INTEGER NOT NULL DEFAULT 10000,
    current_emission_rate_bps INTEGER NOT NULL DEFAULT 10000,
    -- Halving config
    halving_factor_bps INTEGER NOT NULL DEFAULT 5000,
    next_halving_at TIMESTAMPTZ,
    -- History
    total_halvings INTEGER NOT NULL DEFAULT 0,
    updated_at TIMESTAMPTZ DEFAULT now()
);

INSERT INTO emission_schedule (id, next_halving_at)
VALUES (1, now() + INTERVAL '180 days')
ON CONFLICT DO NOTHING;

COMMENT ON TABLE emission_schedule IS 'Singleton tracking emission halving schedule';
COMMENT ON COLUMN emission_schedule.current_emission_rate_bps IS 'Current rate as % of base (10000 = 100%, 5000 = 50%)';
COMMENT ON COLUMN emission_schedule.halving_factor_bps IS 'Rate reduction per halving (5000 = 50%)';

-- =============================================================================
-- MINT EVENTS (AUDIT TRAIL)
-- =============================================================================

CREATE TABLE IF NOT EXISTS dung_mint_events (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    amount NUMERIC NOT NULL,
    allocation_type TEXT NOT NULL,
    recipient TEXT NOT NULL,
    reason TEXT NOT NULL,
    tx_signature TEXT,
    emission_rate_at_mint INTEGER,
    epoch_at_mint INTEGER,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Add constraint for allocation types
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'chk_mint_allocation_type'
    ) THEN
        ALTER TABLE dung_mint_events
            ADD CONSTRAINT chk_mint_allocation_type
            CHECK (allocation_type IN ('community', 'treasury', 'team', 'investor', 'pol'));
    END IF;
END $$;

CREATE INDEX IF NOT EXISTS idx_mint_events_type ON dung_mint_events(allocation_type);
CREATE INDEX IF NOT EXISTS idx_mint_events_recipient ON dung_mint_events(recipient);
CREATE INDEX IF NOT EXISTS idx_mint_events_created ON dung_mint_events(created_at DESC);

COMMENT ON TABLE dung_mint_events IS 'Full audit trail of all DUNG minting';
COMMENT ON COLUMN dung_mint_events.emission_rate_at_mint IS 'Emission rate when minted (for historical analysis)';

-- =============================================================================
-- BURN EVENTS
-- =============================================================================

CREATE TABLE IF NOT EXISTS dung_burn_events (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    amount NUMERIC NOT NULL,
    burner TEXT NOT NULL,
    reason TEXT NOT NULL,
    tx_signature TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_burn_events_burner ON dung_burn_events(burner);
CREATE INDEX IF NOT EXISTS idx_burn_events_created ON dung_burn_events(created_at DESC);

COMMENT ON TABLE dung_burn_events IS 'Full audit trail of all DUNG burning';

-- =============================================================================
-- HELPER FUNCTIONS
-- =============================================================================

-- Function to get current emission multiplier
CREATE OR REPLACE FUNCTION get_emission_multiplier() RETURNS NUMERIC AS $$
DECLARE
    rate_bps INTEGER;
BEGIN
    SELECT current_emission_rate_bps INTO rate_bps FROM emission_schedule WHERE id = 1;
    RETURN rate_bps::NUMERIC / 10000.0;
END;
$$ LANGUAGE plpgsql STABLE;

-- Function to check if minting would exceed supply cap
CREATE OR REPLACE FUNCTION can_mint(
    p_amount NUMERIC,
    p_allocation_type TEXT
) RETURNS BOOLEAN AS $$
DECLARE
    state RECORD;
    allocation_remaining NUMERIC;
BEGIN
    SELECT * INTO state FROM dung_supply_state WHERE id = 1;

    -- Check overall supply cap
    IF state.total_minted + p_amount > state.max_supply THEN
        RETURN FALSE;
    END IF;

    -- Check allocation-specific cap
    CASE p_allocation_type
        WHEN 'community' THEN allocation_remaining := state.community_cap - state.community_minted;
        WHEN 'treasury' THEN allocation_remaining := state.treasury_cap - state.treasury_minted;
        WHEN 'team' THEN allocation_remaining := state.team_cap - state.team_minted;
        WHEN 'investor' THEN allocation_remaining := state.investor_cap - state.investor_minted;
        WHEN 'pol' THEN allocation_remaining := state.pol_cap - state.pol_minted;
        ELSE RETURN FALSE;
    END CASE;

    RETURN p_amount <= allocation_remaining;
END;
$$ LANGUAGE plpgsql STABLE;

-- Function to record a mint
CREATE OR REPLACE FUNCTION record_mint(
    p_amount NUMERIC,
    p_allocation_type TEXT,
    p_recipient TEXT,
    p_reason TEXT,
    p_tx_signature TEXT DEFAULT NULL
) RETURNS BOOLEAN AS $$
DECLARE
    schedule RECORD;
BEGIN
    -- Verify mint is allowed
    IF NOT can_mint(p_amount, p_allocation_type) THEN
        RETURN FALSE;
    END IF;

    -- Get current emission state
    SELECT * INTO schedule FROM emission_schedule WHERE id = 1;

    -- Update supply state
    UPDATE dung_supply_state SET
        total_minted = total_minted + p_amount,
        updated_at = now(),
        community_minted = CASE WHEN p_allocation_type = 'community' THEN community_minted + p_amount ELSE community_minted END,
        treasury_minted = CASE WHEN p_allocation_type = 'treasury' THEN treasury_minted + p_amount ELSE treasury_minted END,
        team_minted = CASE WHEN p_allocation_type = 'team' THEN team_minted + p_amount ELSE team_minted END,
        investor_minted = CASE WHEN p_allocation_type = 'investor' THEN investor_minted + p_amount ELSE investor_minted END,
        pol_minted = CASE WHEN p_allocation_type = 'pol' THEN pol_minted + p_amount ELSE pol_minted END
    WHERE id = 1;

    -- Record event
    INSERT INTO dung_mint_events (amount, allocation_type, recipient, reason, tx_signature, emission_rate_at_mint, epoch_at_mint)
    VALUES (p_amount, p_allocation_type, p_recipient, p_reason, p_tx_signature, schedule.current_emission_rate_bps, schedule.current_epoch);

    RETURN TRUE;
END;
$$ LANGUAGE plpgsql;

-- Function to apply halving (admin only, called periodically)
CREATE OR REPLACE FUNCTION apply_halving() RETURNS BOOLEAN AS $$
DECLARE
    schedule RECORD;
BEGIN
    SELECT * INTO schedule FROM emission_schedule WHERE id = 1;

    -- Check if halving is due
    IF schedule.next_halving_at > now() THEN
        RETURN FALSE;
    END IF;

    -- Apply halving
    UPDATE emission_schedule SET
        current_emission_rate_bps = (current_emission_rate_bps * halving_factor_bps) / 10000,
        current_epoch = current_epoch + 1,
        epoch_start_date = now(),
        next_halving_at = now() + (epoch_duration_days || ' days')::INTERVAL,
        total_halvings = total_halvings + 1,
        updated_at = now()
    WHERE id = 1;

    RETURN TRUE;
END;
$$ LANGUAGE plpgsql;

COMMENT ON FUNCTION apply_halving IS 'Applies halving to emission rate (should be called by cron/admin)';
