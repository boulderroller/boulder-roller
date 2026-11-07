-- ============================================================================
-- V4-B RIDE ATTESTATION FIELDS
-- ============================================================================
-- Persists on-chain ride identity metadata on the canonical rides table so
-- backend/API surfaces can distinguish provisional vs attested rides without
-- querying indexer tables ad hoc.
-- ============================================================================

ALTER TABLE rides
    ADD COLUMN IF NOT EXISTS ride_hash_hex CHAR(64),
    ADD COLUMN IF NOT EXISTS attestation_commitment_hex CHAR(64),
    ADD COLUMN IF NOT EXISTS ride_parser_version INTEGER,
    ADD COLUMN IF NOT EXISTS ride_attestation_pda TEXT,
    ADD COLUMN IF NOT EXISTS ride_attestation_tx_signature TEXT,
    ADD COLUMN IF NOT EXISTS ride_attested_at TIMESTAMPTZ;

CREATE INDEX IF NOT EXISTS idx_rides_ride_hash_hex
    ON rides(ride_hash_hex);

CREATE INDEX IF NOT EXISTS idx_rides_ride_attestation_pda
    ON rides(ride_attestation_pda);
