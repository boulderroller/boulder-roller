-- ============================================================================
-- V4-B Vault activation audit state
-- ============================================================================
-- Extends the chain-derived activation projection with the canonical historical
-- seed boundary committed by admin_activate_vault. The backend job columns on
-- indexed_vaults remain an operational mirror; these fields are the durable
-- economic-truth audit surface.
-- ============================================================================

ALTER TABLE indexed_vault_activations
    ADD COLUMN IF NOT EXISTS seed_generation BIGINT NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS seed_cutoff_at BIGINT NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS economics_start_epoch BIGINT NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS matched_users INTEGER NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS matched_completions INTEGER NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS evidence_hash CHAR(64);

ALTER TABLE indexed_vaults
    ADD COLUMN IF NOT EXISTS activation_seed_generation BIGINT NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS activation_seed_cutoff_at BIGINT NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS activation_economics_start_epoch BIGINT NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS activation_matched_users INTEGER NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS activation_matched_completions INTEGER NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS activation_evidence_hash CHAR(64);

CREATE INDEX IF NOT EXISTS idx_indexed_vault_activations_seed_generation
    ON indexed_vault_activations (seed_generation, seed_cutoff_at DESC);

CREATE INDEX IF NOT EXISTS idx_indexed_vaults_activation_evidence_hash
    ON indexed_vaults (activation_evidence_hash)
    WHERE activation_evidence_hash IS NOT NULL;

COMMENT ON COLUMN indexed_vault_activations.seed_generation IS
    'Canonical historical seed generation committed on-chain during activation.';
COMMENT ON COLUMN indexed_vault_activations.seed_cutoff_at IS
    'Ride-time unix cutoff used to build the historical seed bundle.';
COMMENT ON COLUMN indexed_vault_activations.economics_start_epoch IS
    'First settlement epoch allowed to receive live post-activation economics.';
COMMENT ON COLUMN indexed_vault_activations.evidence_hash IS
    'SHA-256 activation bundle hash over historical seed evidence.';
COMMENT ON COLUMN indexed_vaults.activation_evidence_hash IS
    'Operational mirror of the on-chain VaultActivation.evidence_hash for API filtering.';

NOTIFY pgrst, 'reload schema';
