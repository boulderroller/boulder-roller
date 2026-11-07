-- Rename swanny_share_bps to local_legend_share_bps in vault_distribution_config

DO $$
BEGIN
    IF EXISTS (
        SELECT 1
        FROM information_schema.columns
        WHERE table_name = 'vault_distribution_config'
          AND column_name = 'swanny_share_bps'
    ) AND NOT EXISTS (
        SELECT 1
        FROM information_schema.columns
        WHERE table_name = 'vault_distribution_config'
          AND column_name = 'local_legend_share_bps'
    ) THEN
        EXECUTE 'ALTER TABLE vault_distribution_config RENAME COLUMN swanny_share_bps TO local_legend_share_bps';
    END IF;
END $$;

ALTER TABLE vault_distribution_config DROP CONSTRAINT IF EXISTS bps_sum;
ALTER TABLE vault_distribution_config
    ADD CONSTRAINT bps_sum CHECK (
        leaderboard_share_bps + staker_share_bps + local_legend_share_bps + pol_share_bps + protocol_fee_bps = 10000
    );

COMMENT ON COLUMN vault_distribution_config.local_legend_share_bps IS '3% to Local Legend';
