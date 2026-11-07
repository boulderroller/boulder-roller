-- ============================================================================
-- 086: Track on-chain vault seeding status
-- ============================================================================
-- The vault replay pipeline seeds historical data into on-chain vaults via a
-- multi-step lifecycle: pending -> seeding -> seeded -> activating -> active.
-- Each step records its transaction signature so we can verify on-chain and
-- resume after partial failures. The status column lets us query for vaults
-- that still need seeding or have failed and need retry.
--
-- Migration: 086 (2026-03-13)
-- ============================================================================

-- 1. Add seeding lifecycle columns
ALTER TABLE indexed_vaults
    ADD COLUMN IF NOT EXISTS on_chain_seeding_status TEXT DEFAULT 'pending',
    ADD COLUMN IF NOT EXISTS on_chain_seed_tx TEXT,
    ADD COLUMN IF NOT EXISTS on_chain_leaderboard_tx TEXT,
    ADD COLUMN IF NOT EXISTS on_chain_activate_tx TEXT,
    ADD COLUMN IF NOT EXISTS on_chain_seeded_at TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS on_chain_activated_at TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS on_chain_seeding_error TEXT;

-- 2. Constrain status to valid lifecycle values
ALTER TABLE indexed_vaults
    ADD CONSTRAINT chk_on_chain_seeding_status
    CHECK (on_chain_seeding_status IN (
        'pending', 'seeding', 'seeded', 'activating', 'active', 'failed'
    ));

-- 3. Column documentation
COMMENT ON COLUMN indexed_vaults.on_chain_seeding_status IS
    'Vault seeding lifecycle: pending -> seeding -> seeded -> activating -> active (or failed)';
COMMENT ON COLUMN indexed_vaults.on_chain_seed_tx IS
    'Solana transaction signature for the seed summary instruction';
COMMENT ON COLUMN indexed_vaults.on_chain_leaderboard_tx IS
    'Solana transaction signature for the leaderboard seed instruction';
COMMENT ON COLUMN indexed_vaults.on_chain_activate_tx IS
    'Solana transaction signature for the activation instruction';
COMMENT ON COLUMN indexed_vaults.on_chain_seeded_at IS
    'Timestamp when vault seeding completed (status became seeded)';
COMMENT ON COLUMN indexed_vaults.on_chain_activated_at IS
    'Timestamp when vault activation completed (status became active)';
COMMENT ON COLUMN indexed_vaults.on_chain_seeding_error IS
    'Error message if seeding failed — null on success';

-- 4. Index for querying vaults that need seeding or have failed
CREATE INDEX IF NOT EXISTS idx_indexed_vaults_seeding_status
    ON indexed_vaults (on_chain_seeding_status)
    WHERE on_chain_seeding_status IN ('pending', 'seeding', 'seeded', 'activating', 'failed');

-- Refresh PostgREST schema cache so the new columns are writable
-- immediately through the Supabase REST API.
NOTIFY pgrst, 'reload schema';
