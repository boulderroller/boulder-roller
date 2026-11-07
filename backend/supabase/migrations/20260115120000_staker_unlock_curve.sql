-- Add staker unlock curve columns to epoch_distributions
-- These track the unlock curve calculations per distribution:
-- - staker_count: Number of unique stakers at distribution time
-- - unlock_pct: Percentage unlocked (0-100) based on staker count
-- - locked_staker_amount: DUNG redirected from stakers to leaderboard

ALTER TABLE epoch_distributions
ADD COLUMN IF NOT EXISTS staker_count INT DEFAULT 0,
ADD COLUMN IF NOT EXISTS unlock_pct SMALLINT DEFAULT 0,
ADD COLUMN IF NOT EXISTS locked_staker_amount BIGINT DEFAULT 0;

-- Add same columns to vault_distributions for ledger records
ALTER TABLE vault_distributions
ADD COLUMN IF NOT EXISTS staker_count INT DEFAULT 0,
ADD COLUMN IF NOT EXISTS unlock_pct SMALLINT DEFAULT 0,
ADD COLUMN IF NOT EXISTS locked_staker_amount BIGINT DEFAULT 0;

COMMENT ON COLUMN epoch_distributions.staker_count IS 'Unique stakers with active stakes at distribution time';
COMMENT ON COLUMN epoch_distributions.unlock_pct IS 'Staker pool unlock percentage (0-100) from unlock curve';
COMMENT ON COLUMN epoch_distributions.locked_staker_amount IS 'DUNG redirected from stakers to leaderboard';

COMMENT ON COLUMN vault_distributions.staker_count IS 'Unique stakers with active stakes at distribution time';
COMMENT ON COLUMN vault_distributions.unlock_pct IS 'Staker pool unlock percentage (0-100) from unlock curve';
COMMENT ON COLUMN vault_distributions.locked_staker_amount IS 'DUNG redirected from stakers to leaderboard';
