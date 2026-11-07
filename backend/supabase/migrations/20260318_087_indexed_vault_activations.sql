-- ============================================================================
-- 087: Index raw VaultActivation chain state
-- ============================================================================
-- The current on-chain VaultActivation account stores activation booleans,
-- seed counters, and timestamps, but not the richer backend lifecycle mirror
-- columns already present on indexed_vaults. Persist the raw chain account in a
-- dedicated table so the indexer can project it without inventing missing
-- fields or depending on account write order matching indexed_vaults inserts.
--
-- Migration: 087 (2026-03-18)
-- ============================================================================

CREATE TABLE IF NOT EXISTS indexed_vault_activations (
    vault_id                     BIGINT PRIMARY KEY,
    pda                          TEXT NOT NULL,
    is_active                    BOOLEAN NOT NULL DEFAULT false,
    seed_completions_written     INTEGER NOT NULL DEFAULT 0,
    leaderboard_seeded           BOOLEAN NOT NULL DEFAULT false,
    created_at                   BIGINT NOT NULL DEFAULT 0,
    activated_at                 BIGINT NOT NULL DEFAULT 0,
    last_seed_at                 BIGINT NOT NULL DEFAULT 0,
    chain_slot                   BIGINT,
    indexed_at                   TIMESTAMPTZ NOT NULL DEFAULT now(),
    bump                         SMALLINT
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_indexed_vault_activations_pda
    ON indexed_vault_activations (pda);

CREATE INDEX IF NOT EXISTS idx_indexed_vault_activations_active
    ON indexed_vault_activations (is_active, activated_at DESC);

COMMENT ON TABLE indexed_vault_activations IS
    'Raw VaultActivation account projection from chain. Joined with indexed_vaults for BoulderScan activation UX.';
COMMENT ON COLUMN indexed_vault_activations.seed_completions_written IS
    'Absolute completion-summary count written during historical seeding.';
COMMENT ON COLUMN indexed_vault_activations.leaderboard_seeded IS
    'Whether the historical leaderboard seed has been written on-chain.';
COMMENT ON COLUMN indexed_vault_activations.created_at IS
    'VaultActivation.created_at unix timestamp from chain.';
COMMENT ON COLUMN indexed_vault_activations.activated_at IS
    'VaultActivation.activated_at unix timestamp from chain.';
COMMENT ON COLUMN indexed_vault_activations.last_seed_at IS
    'VaultActivation.last_seed_at unix timestamp from chain.';

NOTIFY pgrst, 'reload schema';
