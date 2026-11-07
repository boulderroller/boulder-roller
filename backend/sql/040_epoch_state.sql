-- Epoch State: Track epoch transitions and vault distributions
-- Per spec: Weekly epochs where CAL→DUNG conversion happens

-- Epoch state tracking
CREATE TABLE IF NOT EXISTS epoch_state (
    id SERIAL PRIMARY KEY,
    current_epoch INTEGER NOT NULL DEFAULT 0,
    last_transition_at TIMESTAMPTZ DEFAULT NOW(),
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- Ensure only one epoch state row (singleton pattern)
INSERT INTO epoch_state (current_epoch) VALUES (0) ON CONFLICT DO NOTHING;

-- Pending epoch distributions (queued for on-chain processing)
CREATE TABLE IF NOT EXISTS epoch_distributions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    epoch INTEGER NOT NULL,
    vault_signature CHAR(128) NOT NULL,
    vault_id INTEGER,
    is_points_period BOOLEAN NOT NULL DEFAULT true,
    cal_to_convert NUMERIC(12, 6) NOT NULL,
    dung_to_mint INTEGER NOT NULL,  -- floor(cal_to_convert / 1000)

    -- Distribution breakdown (in DUNG, calculated from dung_to_mint)
    leaderboard_amount INTEGER DEFAULT 0,  -- 55%
    staker_amount INTEGER DEFAULT 0,       -- 27%
    local_legend_amount INTEGER DEFAULT 0, -- 3%
    pol_amount INTEGER DEFAULT 0,          -- 5%
    protocol_amount INTEGER DEFAULT 0,     -- 10%

    -- Processing state
    status TEXT DEFAULT 'pending',  -- pending, processing, completed, failed
    tx_signature TEXT,              -- On-chain transaction if completed
    error_message TEXT,

    attempt_count INTEGER NOT NULL DEFAULT 0,
    last_attempted_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    processed_at TIMESTAMPTZ,
    UNIQUE (epoch, vault_signature, is_points_period)
);

CREATE INDEX IF NOT EXISTS idx_epoch_distributions_epoch ON epoch_distributions(epoch);
CREATE INDEX IF NOT EXISTS idx_epoch_distributions_vault ON epoch_distributions(vault_signature);
CREATE INDEX IF NOT EXISTS idx_epoch_distributions_status ON epoch_distributions(status);

-- Track epoch history
CREATE TABLE IF NOT EXISTS epoch_history (
    epoch INTEGER PRIMARY KEY,
    started_at TIMESTAMPTZ NOT NULL,
    ended_at TIMESTAMPTZ,
    total_vaults_processed INTEGER DEFAULT 0,
    total_cal_converted NUMERIC(20, 6) DEFAULT 0,
    total_dung_minted INTEGER DEFAULT 0,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Function to get current epoch number
-- Epochs run Sunday 12:00 UTC to Sunday 12:00 UTC (per TOKENOMICS_V2.md line 234)
CREATE OR REPLACE FUNCTION get_current_epoch()
RETURNS INTEGER AS $$
DECLARE
    epoch_anchor BIGINT := 1704020400;  -- Sun Dec 31 2023 12:00:00 UTC
    epoch_duration INTEGER := 604800;    -- 7 days in seconds
    current_epoch INTEGER;
BEGIN
    current_epoch := FLOOR((EXTRACT(EPOCH FROM NOW()) - epoch_anchor) / epoch_duration);
    RETURN current_epoch;
END;
$$ LANGUAGE plpgsql;

-- Function to queue vault distribution for an epoch
CREATE OR REPLACE FUNCTION queue_vault_distribution(
    p_epoch INTEGER,
    p_vault_signature CHAR(128),
    p_vault_id INTEGER,
    p_cal_amount NUMERIC
) RETURNS UUID AS $$
DECLARE
    v_dung_to_mint INTEGER;
    v_distribution_id UUID;
BEGIN
    -- Calculate DUNG to mint (1000 CAL = 1 DUNG)
    v_dung_to_mint := FLOOR(p_cal_amount / 1000);

    IF v_dung_to_mint < 1 THEN
        RETURN NULL;  -- Not enough CAL
    END IF;

    INSERT INTO epoch_distributions (
        epoch, vault_signature, vault_id, cal_to_convert, dung_to_mint,
        leaderboard_amount, staker_amount, local_legend_amount, pol_amount, protocol_amount
    ) VALUES (
        p_epoch, p_vault_signature, p_vault_id, v_dung_to_mint * 1000, v_dung_to_mint,
        FLOOR(v_dung_to_mint * 0.55),  -- 55% leaderboard
        FLOOR(v_dung_to_mint * 0.27),  -- 27% stakers
        FLOOR(v_dung_to_mint * 0.03),  -- 3% local legend
        FLOOR(v_dung_to_mint * 0.05),  -- 5% POL
        FLOOR(v_dung_to_mint * 0.10)   -- 10% protocol
    )
    RETURNING id INTO v_distribution_id;

    RETURN v_distribution_id;
END;
$$ LANGUAGE plpgsql;

COMMENT ON TABLE epoch_state IS 'Singleton table tracking current epoch for distribution processing';
COMMENT ON TABLE epoch_distributions IS 'Queued vault distributions for each epoch, processed on-chain';
COMMENT ON TABLE epoch_history IS 'Historical record of completed epochs and their totals';
