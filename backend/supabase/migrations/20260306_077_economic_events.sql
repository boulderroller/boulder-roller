-- =============================================================================
-- 077: Canonical Append-Only Economic Ledger
--
-- Implements A5's Deliverable 2: an append-only economic event ledger with
-- bi-temporal timestamps, causality chains, hash-chain integrity, and
-- immutability enforcement via triggers.
--
-- Supersedes points_events as the source of truth for all value flows.
-- During migration, both tables are written to (dual-write period).
--
-- Creates:
--   1. economic_events: Append-only ledger table
--   2. prevent_ledger_mutation(): Trigger function blocking UPDATE/DELETE
--   3. wallet_balance_at(): Point-in-time balance reconstruction
--
-- See: output/A5_VERIFICATION_DATA_PLATFORM_DESIGN.md, Section 3
-- =============================================================================


-- =============================================================================
-- 1. economic_events: Canonical append-only economic ledger
-- =============================================================================

CREATE TABLE IF NOT EXISTS economic_events (
    -- Identity
    id              BIGSERIAL PRIMARY KEY,          -- Monotonic sequence
    event_uuid      UUID NOT NULL DEFAULT gen_random_uuid(),  -- For external references

    -- What happened
    event_type      TEXT NOT NULL,                   -- From event taxonomy (see A5 design doc)

    -- Who
    wallet          TEXT NOT NULL,                   -- Affected wallet address
    counterparty    TEXT,                            -- Other party (e.g., vault signature for tribute)

    -- How much
    amount          NUMERIC NOT NULL,                -- Positive = credit, negative = debit
    denomination    TEXT NOT NULL DEFAULT 'POINTS',  -- 'POINTS', 'CAL', 'DUNG', 'LP'

    -- Running balance (denormalized for fast lookups)
    balance_after   NUMERIC NOT NULL,                -- Wallet balance in this denomination after event

    -- Causality chain
    caused_by_id    BIGINT REFERENCES economic_events(id),  -- Parent event (NULL for root events)
    batch_id        UUID,                            -- Groups related events (e.g., epoch distribution batch)

    -- Provenance: what produced this event
    pipeline_version_id  INTEGER REFERENCES pipeline_versions(id),

    -- Reference to source entity
    reference_type  TEXT,                            -- 'activity', 'vault', 'epoch', 'admin', 'tge'
    reference_id    TEXT,                            -- ID of the referenced entity

    -- Bi-temporal timestamps
    valid_at        TIMESTAMPTZ NOT NULL,            -- When the event occurred in the real world
    recorded_at     TIMESTAMPTZ NOT NULL DEFAULT now(),  -- When BR recorded it (system time)

    -- For corrections
    reversal_of_id  BIGINT REFERENCES economic_events(id),  -- If REVERSAL, points to original
    is_reversed     BOOLEAN NOT NULL DEFAULT FALSE,          -- TRUE if a later REVERSAL cancels this

    -- Evidence
    evidence        JSONB,                           -- Additional context (match_trace, tx hash, etc.)

    -- Integrity: hash chain for tamper detection
    prev_hash       CHAR(64),                        -- SHA256 of previous event for this wallet+denomination
    event_hash      CHAR(64) NOT NULL                -- SHA256 of this event's canonical fields
);

COMMENT ON TABLE economic_events IS
    'Canonical append-only economic ledger. Source of truth for all value flows. '
    'Never UPDATE or DELETE. Corrections via REVERSAL events only.';

COMMENT ON COLUMN economic_events.event_hash IS
    'Chain hash: SHA256 of canonical event fields + prev_hash. '
    'Enables tamper detection by verifying the hash chain.';

COMMENT ON COLUMN economic_events.valid_at IS
    'Bi-temporal valid time: when the event happened in the real world '
    '(e.g., ride completion time, epoch close time).';

COMMENT ON COLUMN economic_events.recorded_at IS
    'Bi-temporal system time: when BR recorded the event in the database.';


-- =============================================================================
-- 2. Indexes for common query patterns
-- =============================================================================

CREATE INDEX IF NOT EXISTS idx_econ_events_wallet_denom
    ON economic_events (wallet, denomination, id DESC);

CREATE INDEX IF NOT EXISTS idx_econ_events_type
    ON economic_events (event_type, recorded_at DESC);

CREATE INDEX IF NOT EXISTS idx_econ_events_batch
    ON economic_events (batch_id) WHERE batch_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_econ_events_reference
    ON economic_events (reference_type, reference_id);

CREATE INDEX IF NOT EXISTS idx_econ_events_caused_by
    ON economic_events (caused_by_id) WHERE caused_by_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_econ_events_valid_at
    ON economic_events (valid_at DESC);

CREATE INDEX IF NOT EXISTS idx_econ_events_reversed
    ON economic_events (wallet, denomination) WHERE is_reversed = FALSE;

CREATE INDEX IF NOT EXISTS idx_econ_events_event_uuid
    ON economic_events (event_uuid);


-- =============================================================================
-- 3. Immutability enforcement via triggers
-- =============================================================================

CREATE OR REPLACE FUNCTION prevent_ledger_mutation()
RETURNS TRIGGER AS $$
BEGIN
    IF TG_OP = 'UPDATE' THEN
        -- Allow ONLY setting is_reversed = TRUE (for marking reversed events)
        -- All other fields must remain unchanged
        IF NEW.id = OLD.id
           AND NEW.is_reversed = TRUE
           AND OLD.is_reversed = FALSE
           AND NEW.event_type = OLD.event_type
           AND NEW.amount = OLD.amount
           AND NEW.wallet = OLD.wallet
           AND NEW.denomination = OLD.denomination
           AND NEW.balance_after = OLD.balance_after
           AND NEW.event_hash = OLD.event_hash THEN
            RETURN NEW;
        END IF;
        RAISE EXCEPTION 'UPDATE on economic_events is forbidden. Use REVERSAL events for corrections.';
    END IF;
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'DELETE on economic_events is forbidden. Ledger is append-only.';
    END IF;
    RETURN NULL;
END;
$$ LANGUAGE plpgsql;

-- Drop existing trigger if present (idempotent)
DROP TRIGGER IF EXISTS trg_ledger_immutable ON economic_events;

CREATE TRIGGER trg_ledger_immutable
    BEFORE UPDATE OR DELETE ON economic_events
    FOR EACH ROW
    EXECUTE FUNCTION prevent_ledger_mutation();


-- =============================================================================
-- 4. Point-in-time balance reconstruction function
-- =============================================================================

CREATE OR REPLACE FUNCTION wallet_balance_at(
    p_wallet TEXT,
    p_denomination TEXT,
    p_at TIMESTAMPTZ
) RETURNS NUMERIC AS $$
    SELECT COALESCE(
        (SELECT balance_after
         FROM economic_events
         WHERE wallet = p_wallet
           AND denomination = p_denomination
           AND recorded_at <= p_at
           AND is_reversed = FALSE
         ORDER BY id DESC
         LIMIT 1),
        0
    );
$$ LANGUAGE sql STABLE;

COMMENT ON FUNCTION wallet_balance_at IS
    'Reconstruct wallet balance at any point in time by finding the most recent '
    'non-reversed event before the given timestamp. Returns 0 if no events exist.';


-- =============================================================================
-- 5. Current balance helper (convenience shortcut)
-- =============================================================================

CREATE OR REPLACE FUNCTION wallet_balance_current(
    p_wallet TEXT,
    p_denomination TEXT
) RETURNS NUMERIC AS $$
    SELECT COALESCE(
        (SELECT balance_after
         FROM economic_events
         WHERE wallet = p_wallet
           AND denomination = p_denomination
           AND is_reversed = FALSE
         ORDER BY id DESC
         LIMIT 1),
        0
    );
$$ LANGUAGE sql STABLE;

COMMENT ON FUNCTION wallet_balance_current IS
    'Get current wallet balance for a denomination from the economic ledger.';
