-- Align vault distribution config with TOKENOMICS_V2 (add POL share)

-- Add POL share to config
ALTER TABLE vault_distribution_config
    ADD COLUMN IF NOT EXISTS pol_share_bps INTEGER NOT NULL DEFAULT 500;

ALTER TABLE vault_distribution_config
    ADD COLUMN IF NOT EXISTS pol_account TEXT,
    ADD COLUMN IF NOT EXISTS protocol_treasury TEXT;

-- Update bps sum constraint
ALTER TABLE vault_distribution_config DROP CONSTRAINT IF EXISTS bps_sum;
DO $$
BEGIN
    IF EXISTS (
        SELECT 1
        FROM information_schema.columns
        WHERE table_schema = 'public'
          AND table_name = 'vault_distribution_config'
          AND column_name = 'local_legend_share_bps'
    ) THEN
        EXECUTE 'UPDATE vault_distribution_config SET leaderboard_share_bps = 5500, staker_share_bps = 2700, local_legend_share_bps = 300, pol_share_bps = 500, protocol_fee_bps = 1000, updated_at = now()';
    ELSE
        EXECUTE 'UPDATE vault_distribution_config SET leaderboard_share_bps = 5500, staker_share_bps = 2700, swanny_share_bps = 300, pol_share_bps = 500, protocol_fee_bps = 1000, updated_at = now()';
    END IF;
END $$;

DO $$
BEGIN
    IF EXISTS (
        SELECT 1
        FROM information_schema.columns
        WHERE table_schema = 'public'
          AND table_name = 'vault_distribution_config'
          AND column_name = 'local_legend_share_bps'
    ) THEN
        EXECUTE 'ALTER TABLE vault_distribution_config ADD CONSTRAINT bps_sum CHECK (leaderboard_share_bps + staker_share_bps + local_legend_share_bps + pol_share_bps + protocol_fee_bps = 10000)';
    ELSE
        EXECUTE 'ALTER TABLE vault_distribution_config ADD CONSTRAINT bps_sum CHECK (leaderboard_share_bps + staker_share_bps + swanny_share_bps + pol_share_bps + protocol_fee_bps = 10000)';
    END IF;
END $$;

-- Add POL amount to distribution records
ALTER TABLE vault_distributions
    ADD COLUMN IF NOT EXISTS pol_amount NUMERIC NOT NULL DEFAULT 0;

-- Allow POL receipt type
ALTER TABLE distribution_receipts DROP CONSTRAINT IF EXISTS chk_receipt_type;
ALTER TABLE distribution_receipts
    ADD CONSTRAINT chk_receipt_type
    CHECK (receipt_type IN ('LEADERBOARD', 'STAKE', 'SWANNY', 'POL', 'PROTOCOL'));
