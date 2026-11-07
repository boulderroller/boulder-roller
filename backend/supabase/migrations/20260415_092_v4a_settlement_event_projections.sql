-- V4-A settlement event projections
--
-- The chain is now the source of truth for settlement outputs. These tables
-- project the live on-chain events into query-friendly rows so BoulderScan and
-- backend history routes do not rely on the retired shadow ledger tables.

CREATE TABLE IF NOT EXISTS indexed_epoch_distributions (
    tx_signature TEXT NOT NULL,
    event_index INTEGER NOT NULL,
    vault_id BIGINT NOT NULL,
    epoch BIGINT NOT NULL,
    total_distributed NUMERIC(39, 0) NOT NULL DEFAULT 0,
    leaderboard_distributed NUMERIC(39, 0) NOT NULL DEFAULT 0,
    staker_distributed NUMERIC(39, 0) NOT NULL DEFAULT 0,
    local_legend_distributed NUMERIC(39, 0) NOT NULL DEFAULT 0,
    pol_distributed NUMERIC(39, 0) NOT NULL DEFAULT 0,
    protocol_distributed NUMERIC(39, 0) NOT NULL DEFAULT 0,
    staker_count INTEGER NOT NULL DEFAULT 0,
    unlock_pct INTEGER NOT NULL DEFAULT 0,
    locked_staker_amount NUMERIC(39, 0) NOT NULL DEFAULT 0,
    slot BIGINT NOT NULL,
    block_time BIGINT,
    indexed_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (tx_signature, event_index)
);

CREATE INDEX IF NOT EXISTS idx_indexed_epoch_distributions_vault_epoch
    ON indexed_epoch_distributions(vault_id, epoch DESC);

CREATE INDEX IF NOT EXISTS idx_indexed_epoch_distributions_epoch
    ON indexed_epoch_distributions(epoch DESC);

COMMENT ON TABLE indexed_epoch_distributions IS
    'Projection of EpochRewardsDistributed on-chain events for V4-A settlement history.';

CREATE TABLE IF NOT EXISTS indexed_staker_allocations (
    tx_signature TEXT NOT NULL,
    event_index INTEGER NOT NULL,
    vault_id BIGINT NOT NULL,
    epoch BIGINT NOT NULL,
    staker TEXT NOT NULL,
    amount NUMERIC(39, 0) NOT NULL DEFAULT 0,
    lp_tokens NUMERIC(39, 0) NOT NULL DEFAULT 0,
    eligible_from_epoch BIGINT NOT NULL DEFAULT 0,
    slot BIGINT NOT NULL,
    block_time BIGINT,
    indexed_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (tx_signature, event_index)
);

CREATE INDEX IF NOT EXISTS idx_indexed_staker_allocations_staker_epoch
    ON indexed_staker_allocations(staker, epoch DESC, block_time DESC);

CREATE INDEX IF NOT EXISTS idx_indexed_staker_allocations_vault_epoch
    ON indexed_staker_allocations(vault_id, epoch DESC);

COMMENT ON TABLE indexed_staker_allocations IS
    'Projection of StakerAllocation on-chain events for V4-A payout history.';
