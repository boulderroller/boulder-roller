-- Deprecate legacy Synthetix reward accrual mirrors.
--
-- The current protocol uses discrete Settlement Week allocation and per-bucket
-- carry fields. These columns remain only as deploy-order/table-layout
-- compatibility slots for historical indexed_vaults schemas.

ALTER TABLE indexed_vaults
    ALTER COLUMN reward_per_token_stored SET DEFAULT 0,
    ALTER COLUMN last_update_time SET DEFAULT 0,
    ALTER COLUMN reward_rate SET DEFAULT 0;

COMMENT ON COLUMN indexed_vaults.reward_per_token_stored IS
    'DEPRECATED legacy Synthetix accrual mirror. Not active Boulder Rollers economics; use pending_rewards, pending_rewards_next_week, and carry_* fields.';
COMMENT ON COLUMN indexed_vaults.last_update_time IS
    'DEPRECATED legacy Synthetix accrual timestamp. Not active Boulder Rollers economics; retained only for indexed_vaults compatibility.';
COMMENT ON COLUMN indexed_vaults.reward_rate IS
    'DEPRECATED legacy Synthetix accrual rate. Not active Boulder Rollers economics; use discrete Settlement Week distribution fields.';
