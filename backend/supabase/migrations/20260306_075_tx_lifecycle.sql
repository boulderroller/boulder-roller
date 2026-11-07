-- Migration 075: Transaction lifecycle tracking table
--
-- Provides a durable record of every Solana transaction the backend submits.
-- Used by submit_and_confirm() to track pending/submitted/confirmed/failed states,
-- detect blockhash expiry, and correlate on-chain events with application entities.
--
-- This is a CRITICAL mainnet readiness item: without lifecycle tracking,
-- failed transactions silently disappear and DB state diverges from on-chain state.

CREATE TABLE IF NOT EXISTS tx_lifecycle (
    id                      BIGSERIAL PRIMARY KEY,
    signature               TEXT UNIQUE,            -- base58 tx signature (NULL until submitted)
    tx_type                 TEXT NOT NULL,           -- e.g. 'vault_create', 'epoch_distribute', 'cal_claim', 'stake', 'unstake'
    status                  TEXT NOT NULL DEFAULT 'pending',
                                                     -- pending, submitted, landed, confirmed, finalized, failed, expired, replaced

    -- Submission details
    instructions            JSONB,                  -- Serialized instruction summary (for debugging, not replay)
    blockhash               TEXT,                   -- Recent blockhash used
    last_valid_block_height BIGINT,                 -- Blockhash expiry height
    priority_fee_lamports   BIGINT DEFAULT 0,
    compute_units           INTEGER,

    -- Lifecycle timestamps
    created_at              TIMESTAMPTZ NOT NULL DEFAULT now(),
    submitted_at            TIMESTAMPTZ,
    landed_at               TIMESTAMPTZ,            -- First seen in a block
    confirmed_at            TIMESTAMPTZ,
    finalized_at            TIMESTAMPTZ,
    failed_at               TIMESTAMPTZ,

    -- Error tracking
    error_message           TEXT,
    retry_count             INTEGER DEFAULT 0,
    max_retries             INTEGER DEFAULT 3,

    -- References (link tx to application entity)
    reference_type          TEXT,                   -- 'ride', 'vault', 'epoch', etc.
    reference_id            TEXT,                   -- The ride_id, vault_id, epoch_id, etc.
    wallet                  TEXT,                   -- The wallet this tx is for

    -- On-chain context
    slot                    BIGINT                  -- Solana slot where tx landed
);

-- Partial index on active transactions (pending/submitted) for the confirmation poller
CREATE INDEX IF NOT EXISTS idx_tx_lifecycle_status
    ON tx_lifecycle(status)
    WHERE status IN ('pending', 'submitted');

-- Lookup by wallet for user-facing transaction history
CREATE INDEX IF NOT EXISTS idx_tx_lifecycle_wallet
    ON tx_lifecycle(wallet);

-- Lookup by application entity (e.g. "show me all txs for vault 42")
CREATE INDEX IF NOT EXISTS idx_tx_lifecycle_ref
    ON tx_lifecycle(reference_type, reference_id);

-- Lookup by on-chain signature (non-null only)
CREATE INDEX IF NOT EXISTS idx_tx_lifecycle_signature
    ON tx_lifecycle(signature)
    WHERE signature IS NOT NULL;

-- Lookup by tx_type for operational dashboards
CREATE INDEX IF NOT EXISTS idx_tx_lifecycle_type
    ON tx_lifecycle(tx_type);

-- Add CHECK constraint on status to prevent typos
ALTER TABLE tx_lifecycle
    ADD CONSTRAINT chk_tx_lifecycle_status
    CHECK (status IN ('pending', 'submitted', 'landed', 'confirmed', 'finalized', 'failed', 'expired', 'replaced'));
