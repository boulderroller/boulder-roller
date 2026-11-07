-- Ensure the legacy settlement queue/ledger tables have the V4 settlement
-- bookkeeping fields used by the runtime queue writer and rollout
-- compatibility paths.

ALTER TABLE epoch_distributions
    ADD COLUMN IF NOT EXISTS staker_count INTEGER NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS unlock_pct SMALLINT NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS locked_staker_amount NUMERIC(39, 0) NOT NULL DEFAULT 0;

ALTER TABLE vault_distributions
    ADD COLUMN IF NOT EXISTS staker_count INTEGER NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS unlock_pct SMALLINT NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS locked_staker_amount NUMERIC(39, 0) NOT NULL DEFAULT 0;

UPDATE epoch_distributions
SET
    staker_count = COALESCE(staker_count, 0),
    unlock_pct = COALESCE(unlock_pct, 0),
    locked_staker_amount = COALESCE(locked_staker_amount, 0);

UPDATE vault_distributions
SET
    staker_count = COALESCE(staker_count, 0),
    unlock_pct = COALESCE(unlock_pct, 0),
    locked_staker_amount = COALESCE(locked_staker_amount, 0);

COMMENT ON COLUMN epoch_distributions.staker_count IS
    'Unique stakers eligible for this settlement queue row.';
COMMENT ON COLUMN epoch_distributions.unlock_pct IS
    'Staker pool unlock percentage captured for compatibility queue visibility.';
COMMENT ON COLUMN epoch_distributions.locked_staker_amount IS
    'DUNG amount not unlocked to stakers, preserved for compatibility queue visibility.';

COMMENT ON COLUMN vault_distributions.staker_count IS
    'Unique stakers eligible for this legacy settlement ledger row.';
COMMENT ON COLUMN vault_distributions.unlock_pct IS
    'Staker pool unlock percentage captured for legacy ledger compatibility.';
COMMENT ON COLUMN vault_distributions.locked_staker_amount IS
    'DUNG amount not unlocked to stakers, preserved for legacy ledger compatibility.';

NOTIFY pgrst, 'reload schema';
