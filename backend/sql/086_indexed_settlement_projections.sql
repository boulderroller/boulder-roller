-- ============================================================================
-- V4 Settlement Projection Tables
-- ============================================================================
-- Chain-derived read models for Settlement Week finalization. The indexer is
-- the only writer; backend routes read these tables directly and do not fall
-- back to legacy queue/current-stake tables.
-- ============================================================================

ALTER TABLE indexed_vaults
    ADD COLUMN IF NOT EXISTS total_cal_staked NUMERIC NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS pending_rewards NUMERIC NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS pending_rewards_next_week NUMERIC NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS open_settlement_week BIGINT NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS carry_record_royalty NUMERIC NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS carry_stakers NUMERIC NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS carry_local_legend NUMERIC NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS carry_pol NUMERIC NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS carry_treasury NUMERIC NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS last_distribution_epoch BIGINT NOT NULL DEFAULT 0;

CREATE TABLE IF NOT EXISTS indexed_epoch_distributions (
    tx_signature TEXT NOT NULL,
    event_index INTEGER NOT NULL,
    vault_id BIGINT NOT NULL,
    epoch BIGINT NOT NULL,
    total_distributed NUMERIC NOT NULL DEFAULT 0,
    leaderboard_distributed NUMERIC NOT NULL DEFAULT 0,
    staker_distributed NUMERIC NOT NULL DEFAULT 0,
    local_legend_distributed NUMERIC NOT NULL DEFAULT 0,
    pol_distributed NUMERIC NOT NULL DEFAULT 0,
    protocol_distributed NUMERIC NOT NULL DEFAULT 0,
    staker_count INTEGER NOT NULL DEFAULT 0,
    unlock_pct INTEGER NOT NULL DEFAULT 0,
    locked_staker_amount NUMERIC NOT NULL DEFAULT 0,
    slot BIGINT NOT NULL DEFAULT 0,
    block_time BIGINT,
    finalized_at TIMESTAMPTZ GENERATED ALWAYS AS (
        CASE WHEN block_time IS NOT NULL
             THEN to_timestamp(block_time)
             ELSE NULL
        END
    ) STORED,
    indexed_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (tx_signature, event_index)
);

CREATE INDEX IF NOT EXISTS idx_epoch_distributions_vault_epoch
    ON indexed_epoch_distributions (vault_id, epoch DESC);

CREATE INDEX IF NOT EXISTS idx_epoch_distributions_block_time
    ON indexed_epoch_distributions (block_time DESC NULLS LAST);

CREATE TABLE IF NOT EXISTS indexed_staker_allocations (
    tx_signature TEXT NOT NULL,
    event_index INTEGER NOT NULL,
    vault_id BIGINT NOT NULL,
    epoch BIGINT NOT NULL,
    staker TEXT NOT NULL,
    amount NUMERIC NOT NULL DEFAULT 0,
    lp_tokens NUMERIC NOT NULL DEFAULT 0,
    eligible_from_epoch BIGINT NOT NULL DEFAULT 0,
    slot BIGINT NOT NULL DEFAULT 0,
    block_time BIGINT,
    indexed_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (tx_signature, event_index)
);

CREATE INDEX IF NOT EXISTS idx_staker_allocations_staker_epoch
    ON indexed_staker_allocations (staker, epoch DESC);

CREATE INDEX IF NOT EXISTS idx_staker_allocations_vault_epoch
    ON indexed_staker_allocations (vault_id, epoch DESC);

COMMENT ON TABLE indexed_epoch_distributions IS
'Chain-derived Settlement Week finalization events. The indexer is the only writer.';

COMMENT ON TABLE indexed_staker_allocations IS
'Chain-derived per-staker DUNG settlement allocations. The indexer is the only writer.';

COMMENT ON COLUMN indexed_vaults.carry_record_royalty IS
'Undistributed Record Board bucket carry, preserved within bucket.';

COMMENT ON COLUMN indexed_vaults.carry_stakers IS
'Undistributed staker bucket carry, preserved within bucket.';

COMMENT ON COLUMN indexed_vaults.carry_local_legend IS
'Undistributed Local Legend bucket carry, preserved within bucket.';

COMMENT ON COLUMN indexed_vaults.carry_pol IS
'Undistributed POL bucket carry, preserved within bucket.';

COMMENT ON COLUMN indexed_vaults.carry_treasury IS
'Undistributed treasury bucket carry, preserved within bucket.';
