-- Vault CAL Pots: Track CAL accumulation per vault for DUNG conversion
-- Per spec: CAL distributed to vaults crossed during rides → 1000 CAL = 1 DUNG minted to pot

-- Main pot tracking table
CREATE TABLE IF NOT EXISTS vault_cal_pots (
    vault_signature CHAR(128) PRIMARY KEY,  -- 64-byte signature as hex
    cal_balance NUMERIC(20, 6) DEFAULT 0,   -- Current CAL in pot (allows fractional)
    total_cal_received NUMERIC(20, 6) DEFAULT 0,  -- Lifetime CAL received
    total_dung_minted INTEGER DEFAULT 0,    -- Total DUNG minted from this pot
    last_distribution_at TIMESTAMPTZ,       -- Last time pot was distributed
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- Track individual CAL contributions to vaults (for audit/analytics)
CREATE TABLE IF NOT EXISTS vault_cal_contributions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    vault_signature CHAR(128) NOT NULL,
    wallet TEXT NOT NULL,                   -- Who contributed
    activity_id UUID NOT NULL,              -- Which ride
    cal_amount NUMERIC(12, 6) NOT NULL,     -- Amount contributed
    time_weight NUMERIC(6, 4),              -- Time spent on vault as % of ride
    intensity_factor NUMERIC(6, 4),         -- IF for this segment
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Index for querying contributions by vault
CREATE INDEX IF NOT EXISTS idx_vault_cal_contributions_vault
    ON vault_cal_contributions(vault_signature);
CREATE INDEX IF NOT EXISTS idx_vault_cal_contributions_wallet
    ON vault_cal_contributions(wallet);
CREATE INDEX IF NOT EXISTS idx_vault_cal_contributions_activity
    ON vault_cal_contributions(activity_id);

-- Track DUNG minting events from vault pots
CREATE TABLE IF NOT EXISTS vault_dung_mints (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    vault_signature CHAR(128) NOT NULL,
    cal_converted NUMERIC(12, 6) NOT NULL,  -- CAL consumed (should be 1000 per DUNG)
    dung_minted INTEGER NOT NULL,           -- DUNG minted
    epoch INTEGER,                          -- Which epoch this occurred in
    tx_signature TEXT,                      -- On-chain transaction
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_vault_dung_mints_vault
    ON vault_dung_mints(vault_signature);
CREATE INDEX IF NOT EXISTS idx_vault_dung_mints_epoch
    ON vault_dung_mints(epoch);

-- Function to add CAL to a vault pot
CREATE OR REPLACE FUNCTION add_cal_to_vault(
    p_vault_signature CHAR(128),
    p_cal_amount NUMERIC
) RETURNS NUMERIC AS $$
DECLARE
    v_new_balance NUMERIC;
BEGIN
    INSERT INTO vault_cal_pots (vault_signature, cal_balance, total_cal_received, updated_at)
    VALUES (p_vault_signature, p_cal_amount, p_cal_amount, NOW())
    ON CONFLICT (vault_signature) DO UPDATE SET
        cal_balance = vault_cal_pots.cal_balance + p_cal_amount,
        total_cal_received = vault_cal_pots.total_cal_received + p_cal_amount,
        updated_at = NOW()
    RETURNING cal_balance INTO v_new_balance;

    RETURN v_new_balance;
END;
$$ LANGUAGE plpgsql;

-- Function to convert CAL to DUNG in a vault pot (1000 CAL = 1 DUNG)
CREATE OR REPLACE FUNCTION convert_vault_cal_to_dung(
    p_vault_signature CHAR(128),
    p_epoch INTEGER DEFAULT NULL
) RETURNS INTEGER AS $$
DECLARE
    v_cal_balance NUMERIC;
    v_dung_to_mint INTEGER;
    v_cal_to_consume NUMERIC;
BEGIN
    -- Get current balance
    SELECT cal_balance INTO v_cal_balance
    FROM vault_cal_pots
    WHERE vault_signature = p_vault_signature
    FOR UPDATE;

    IF v_cal_balance IS NULL OR v_cal_balance < 1000 THEN
        RETURN 0;
    END IF;

    -- Calculate how many DUNG to mint (floor division)
    v_dung_to_mint := FLOOR(v_cal_balance / 1000);
    v_cal_to_consume := v_dung_to_mint * 1000;

    -- Update pot balance
    UPDATE vault_cal_pots SET
        cal_balance = cal_balance - v_cal_to_consume,
        total_dung_minted = total_dung_minted + v_dung_to_mint,
        updated_at = NOW()
    WHERE vault_signature = p_vault_signature;

    -- Record the mint event
    INSERT INTO vault_dung_mints (vault_signature, cal_converted, dung_minted, epoch)
    VALUES (p_vault_signature, v_cal_to_consume, v_dung_to_mint, p_epoch);

    RETURN v_dung_to_mint;
END;
$$ LANGUAGE plpgsql;

-- Comments
COMMENT ON TABLE vault_cal_pots IS 'Tracks CAL accumulation per vault. CAL is distributed to vaults crossed during rides.';
COMMENT ON TABLE vault_cal_contributions IS 'Audit trail of CAL contributions to vaults from individual rides.';
COMMENT ON TABLE vault_dung_mints IS 'Record of DUNG minting events when vault pots reach 1000 CAL threshold.';
COMMENT ON FUNCTION add_cal_to_vault IS 'Add CAL to a vault pot, creating if needed. Returns new balance.';
COMMENT ON FUNCTION convert_vault_cal_to_dung IS 'Convert accumulated CAL to DUNG (1000:1 ratio). Returns DUNG minted.';
