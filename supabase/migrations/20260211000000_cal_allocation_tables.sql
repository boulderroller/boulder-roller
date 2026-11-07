-- CAL Allocation Refactor: New tables for Merkle-batched CAL distribution
-- Replaces direct on-chain admin_credit_cal with off-chain allocation pipeline

-- Batch records: one row per Merkle root submission
-- (Must be created first since cal_allocation_staging references it)
CREATE TABLE IF NOT EXISTS cal_allocation_batches (
    id BIGSERIAL PRIMARY KEY,
    batch_type TEXT NOT NULL CHECK (batch_type IN ('user_cal', 'vault_alloc')),
    epoch BIGINT NOT NULL,
    merkle_root TEXT NOT NULL,      -- 64-char hex
    tree_depth INT NOT NULL,
    leaf_count INT NOT NULL,
    tree_json JSONB NOT NULL,       -- Full tree for proof generation
    status TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'submitted', 'confirmed', 'failed')),
    solana_tx_signature TEXT,
    solana_slot BIGINT,
    on_chain_batch_id BIGINT,       -- batch_id used in submit_allocation_batch
    error_message TEXT,
    retry_count INT DEFAULT 0,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    submitted_at TIMESTAMPTZ,
    confirmed_at TIMESTAMPTZ
);

-- Staging table: rides waiting to be allocated
CREATE TABLE IF NOT EXISTS cal_allocation_staging (
    id BIGSERIAL PRIMARY KEY,
    activity_id TEXT NOT NULL,
    wallet TEXT NOT NULL,
    tss NUMERIC NOT NULL,
    cal_earned NUMERIC NOT NULL,
    -- Per-vault allocations (JSON array of {vault_id, vault_signature, cal_tribute, time_in_vault_s, intensity_factor})
    vault_allocations JSONB DEFAULT '[]'::jsonb,
    epoch BIGINT NOT NULL,
    staged_at TIMESTAMPTZ DEFAULT NOW(),
    allocated BOOLEAN DEFAULT FALSE,
    batch_id BIGINT REFERENCES cal_allocation_batches(id),
    UNIQUE(activity_id)
);

-- Individual leaves within a batch
CREATE TABLE IF NOT EXISTS cal_allocation_leaves (
    id BIGSERIAL PRIMARY KEY,
    batch_id BIGINT NOT NULL REFERENCES cal_allocation_batches(id),
    leaf_index INT NOT NULL,
    leaf_hash TEXT NOT NULL,         -- 64-char hex SHA256
    leaf_type TEXT NOT NULL CHECK (leaf_type IN ('user_cal', 'vault_alloc')),
    -- User CAL leaf fields
    wallet TEXT,
    total_cal_amount BIGINT,
    ride_count INT,
    -- Vault alloc leaf fields
    vault_id BIGINT,
    vault_signature TEXT,
    cal_amount BIGINT,
    -- Claim tracking
    epoch BIGINT NOT NULL,
    claimed BOOLEAN DEFAULT FALSE,
    claimed_at TIMESTAMPTZ,
    claim_tx_signature TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(batch_id, leaf_index)
);

-- Indexes for efficient querying
CREATE INDEX IF NOT EXISTS idx_cal_staging_not_allocated ON cal_allocation_staging(allocated) WHERE allocated = FALSE;
CREATE INDEX IF NOT EXISTS idx_cal_staging_epoch ON cal_allocation_staging(epoch);
CREATE INDEX IF NOT EXISTS idx_cal_batches_status ON cal_allocation_batches(status);
CREATE INDEX IF NOT EXISTS idx_cal_batches_epoch ON cal_allocation_batches(epoch);
CREATE INDEX IF NOT EXISTS idx_cal_leaves_batch ON cal_allocation_leaves(batch_id);
CREATE INDEX IF NOT EXISTS idx_cal_leaves_wallet ON cal_allocation_leaves(wallet);
CREATE INDEX IF NOT EXISTS idx_cal_leaves_vault ON cal_allocation_leaves(vault_id);
CREATE INDEX IF NOT EXISTS idx_cal_leaves_unclaimed ON cal_allocation_leaves(claimed) WHERE claimed = FALSE;
