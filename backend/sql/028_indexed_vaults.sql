-- ============================================================================
-- INDEXED VAULTS (On-Chain Cache)
-- ============================================================================
-- Cache of on-chain Vault accounts from the boulder_rollers Solana program.
-- The chain is the source of truth; this is a read-through cache for fast queries.
--
-- Synced by VaultIndexer background service.
-- Used by VaultSignatureCache for fast climb signature matching.
-- ============================================================================

CREATE TABLE IF NOT EXISTS indexed_vaults (
    -- Primary key matches on-chain vault ID (u64)
    id BIGINT PRIMARY KEY,

    -- ========================================
    -- SIGNATURE (from on-chain Vault account)
    -- ========================================
    signature_hex CHAR(128) NOT NULL,       -- 64-byte signature as hex
    signature_hash_hex CHAR(64) NOT NULL,   -- SHA256 of signature (for PDA)

    -- ========================================
    -- CREATOR & OWNERSHIP
    -- ========================================
    minter TEXT NOT NULL,                   -- Pubkey of first claimer
    name TEXT NOT NULL,                     -- Display name (max 64 chars)

    -- ========================================
    -- CLIMB METRICS (from signature)
    -- ========================================
    vert_m DOUBLE PRECISION NOT NULL,       -- Vertical gain in meters
    distance_m INTEGER NOT NULL,            -- Distance in meters
    avg_gradient_pct DOUBLE PRECISION NOT NULL,  -- Average gradient percentage

    -- ========================================
    -- ON-CHAIN ECONOMICS
    -- ========================================
    total_completions INTEGER DEFAULT 0,    -- Number of verified completions
    total_staked BIGINT DEFAULT 0,          -- DUNG staked in vault

    -- ========================================
    -- KOM (King of Mountain)
    -- ========================================
    kom_holder TEXT,                        -- Pubkey of current KOM holder
    kom_time_s INTEGER DEFAULT 0,           -- Best completion time in seconds

    -- ========================================
    -- CHAIN DATA
    -- ========================================
    pda TEXT NOT NULL,                      -- Vault account PDA address
    created_at TIMESTAMPTZ NOT NULL,        -- On-chain creation timestamp
    vault_pot TEXT,                         -- DUNG token account used for staker rewards

    -- ========================================
    -- INDEXER METADATA
    -- ========================================
    indexed_at TIMESTAMPTZ DEFAULT NOW(),   -- When we last synced this vault
    last_synced_at TIMESTAMPTZ              -- Last full refresh
);

-- ============================================================================
-- INDEXES
-- ============================================================================

-- Signature hash for exact lookups (used in vault matching)
CREATE UNIQUE INDEX IF NOT EXISTS idx_indexed_vaults_sig_hash
ON indexed_vaults (signature_hash_hex);

-- Minter queries (find vaults created by a user)
CREATE INDEX IF NOT EXISTS idx_indexed_vaults_minter
ON indexed_vaults (minter);

-- KOM holder queries
CREATE INDEX IF NOT EXISTS idx_indexed_vaults_kom
ON indexed_vaults (kom_holder)
WHERE kom_holder IS NOT NULL;

-- PDA lookups
CREATE UNIQUE INDEX IF NOT EXISTS idx_indexed_vaults_pda
ON indexed_vaults (pda);

-- Recently indexed (for sync monitoring)
CREATE INDEX IF NOT EXISTS idx_indexed_vaults_indexed_at
ON indexed_vaults (indexed_at DESC);

-- ============================================================================
-- COMMENTS
-- ============================================================================

COMMENT ON TABLE indexed_vaults IS
'Cache of on-chain Vault accounts from boulder_rollers program. Chain is source of truth.';

COMMENT ON COLUMN indexed_vaults.id IS
'On-chain vault ID (u64). Auto-incremented by VaultCounter on chain.';

COMMENT ON COLUMN indexed_vaults.signature_hex IS
'64-byte climb signature: SHA256 gradient profile (32) + metrics (16) + checksum (16)';

COMMENT ON COLUMN indexed_vaults.vert_m IS
'Vertical gain in meters. Stored on-chain as u32 * 10 for precision.';

COMMENT ON COLUMN indexed_vaults.avg_gradient_pct IS
'Average gradient percentage. Stored on-chain as u16 * 100 for precision.';

COMMENT ON COLUMN indexed_vaults.vault_pot IS
'Token account for vault stakers (ATA for vault PDA and DUNG mint).';
