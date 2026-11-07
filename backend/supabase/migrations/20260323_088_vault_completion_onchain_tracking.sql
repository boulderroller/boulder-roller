-- ============================================================================
-- VAULT COMPLETIONS: On-chain transaction tracking
-- ============================================================================
-- Tracks on-chain record_vault_completion tx status for reconciliation.
-- When on-chain tx fails, the error is stored here so a reconciliation
-- job can retry later.
-- ============================================================================

ALTER TABLE vault_completions
    ADD COLUMN IF NOT EXISTS on_chain_tx TEXT,
    ADD COLUMN IF NOT EXISTS on_chain_tx_error TEXT;

COMMENT ON COLUMN vault_completions.on_chain_tx IS
'Solana tx signature from record_vault_completion. NULL if not yet submitted or vault not active.';

COMMENT ON COLUMN vault_completions.on_chain_tx_error IS
'Error message if on-chain tx failed. Used by reconciliation to retry. NULL on success.';

-- Index for finding completions that need on-chain retry
CREATE INDEX IF NOT EXISTS idx_vault_completions_onchain_retry
ON vault_completions (on_chain_tx_error)
WHERE on_chain_tx_error IS NOT NULL;
