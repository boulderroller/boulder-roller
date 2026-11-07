-- Deprecate wrong CAL daily budget and scoring tables
-- The "Score for DUNG" model was incorrect.
-- Correct model: CAL earned from TSS, tributed to vaults, 1000 CAL = 1 DUNG
--
-- These tables are deprecated and will be dropped in a future migration.

-- Mark tables as deprecated
COMMENT ON TABLE scored_patterns IS 'DEPRECATED: Wrong CAL model. CAL tributes to vaults automatically, not via manual scoring.';
COMMENT ON TABLE cal_daily_balances IS 'DEPRECATED: Wrong CAL model. No daily budget - CAL comes from TSS earned on rides.';

-- Drop indexes to reduce overhead (tables still exist for data recovery if needed)
DROP INDEX IF EXISTS idx_scored_patterns_activity;
DROP INDEX IF EXISTS idx_scored_patterns_wallet;
DROP INDEX IF EXISTS idx_scored_patterns_status;
DROP INDEX IF EXISTS idx_scored_patterns_type;
DROP INDEX IF EXISTS idx_scored_patterns_created;
DROP INDEX IF EXISTS idx_scored_patterns_unique;
DROP INDEX IF EXISTS idx_cal_balances_date;
