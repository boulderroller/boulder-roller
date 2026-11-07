-- ============================================================================
-- V4-A settlement indexer alignment
-- ============================================================================
-- Extends indexed read-model tables to the current V4-A chain layout so the
-- backend/indexer can read settlement-week state without reconstructing it.

ALTER TABLE indexed_vaults
    ADD COLUMN IF NOT EXISTS cal_tribute_accumulated_next BIGINT NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS pending_rewards_next_week BIGINT NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS open_settlement_week BIGINT NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS carry_record_royalty BIGINT NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS carry_stakers BIGINT NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS carry_local_legend BIGINT NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS carry_pol BIGINT NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS carry_treasury BIGINT NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS last_distribution_epoch BIGINT NOT NULL DEFAULT 0;

ALTER TABLE indexed_stakes
    ADD COLUMN IF NOT EXISTS eligible_from_epoch BIGINT NOT NULL DEFAULT 0;

ALTER TABLE indexed_program_config
    ADD COLUMN IF NOT EXISTS program_version SMALLINT NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS pol_token_account TEXT,
    ADD COLUMN IF NOT EXISTS treasury_token_account TEXT;

COMMENT ON COLUMN indexed_vaults.cal_tribute_accumulated_next IS
    'CAL dust staged for the next open settlement week';
COMMENT ON COLUMN indexed_vaults.pending_rewards_next_week IS
    'DUNG staged for the next settlement week';
COMMENT ON COLUMN indexed_vaults.open_settlement_week IS
    'Oldest unsettled settlement week for this vault';
COMMENT ON COLUMN indexed_vaults.carry_record_royalty IS
    'Unpaid Record Royalty carry preserved inside the record bucket';
COMMENT ON COLUMN indexed_vaults.carry_stakers IS
    'Unpaid staker carry preserved inside the staker bucket';
COMMENT ON COLUMN indexed_vaults.carry_local_legend IS
    'Unpaid Local Legend carry preserved inside the legend bucket';
COMMENT ON COLUMN indexed_vaults.carry_pol IS
    'Unpaid POL carry preserved inside the POL bucket';
COMMENT ON COLUMN indexed_vaults.carry_treasury IS
    'Unpaid treasury carry preserved inside the treasury bucket';
COMMENT ON COLUMN indexed_stakes.eligible_from_epoch IS
    'First settlement week in which this stake counts toward unlock/allocation';
COMMENT ON COLUMN indexed_program_config.program_version IS
    'Program/IDL compatibility version gate (V4-A = 0x40)';
