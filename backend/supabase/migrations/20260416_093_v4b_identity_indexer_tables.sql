-- ============================================================================
-- V4-B IDENTITY / ATTESTATION INDEXER TABLES
-- ============================================================================
-- Adds indexed read-model tables for the new ontology-lift accounts:
--   RiderSoul, RideAttestation, CalMintReceipt, ClimbCompletionReceipt.
--
-- Migration: 093 (2026-04-16)
-- ============================================================================

CREATE TABLE IF NOT EXISTS indexed_rider_souls (
    rider_pubkey        TEXT PRIMARY KEY,
    created_at          BIGINT NOT NULL DEFAULT 0,
    total_rides         NUMERIC NOT NULL DEFAULT 0,
    total_tss           NUMERIC NOT NULL DEFAULT 0,
    total_distance_m    NUMERIC NOT NULL DEFAULT 0,
    total_vert_m        NUMERIC NOT NULL DEFAULT 0,
    total_cal_earned    NUMERIC NOT NULL DEFAULT 0,
    archetype           SMALLINT NOT NULL DEFAULT 0,
    bio_score           NUMERIC NOT NULL DEFAULT 0,
    climb_card          TEXT,
    steady_card         TEXT,
    explorer_card       TEXT,
    pda                 TEXT NOT NULL,
    chain_slot          BIGINT,
    indexed_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    bump                SMALLINT
);

CREATE INDEX IF NOT EXISTS idx_indexed_rider_souls_total_tss
    ON indexed_rider_souls(total_tss DESC);

CREATE TABLE IF NOT EXISTS indexed_ride_attestations (
    rider_pubkey                TEXT NOT NULL,
    ride_hash_hex               CHAR(64) NOT NULL,
    attestation_commitment_hex  CHAR(64) NOT NULL,
    parser_version              INTEGER NOT NULL DEFAULT 0,
    source_kind                 SMALLINT NOT NULL DEFAULT 0,
    completed_at                BIGINT NOT NULL DEFAULT 0,
    started_at                  BIGINT NOT NULL DEFAULT 0,
    total_tss                   INTEGER NOT NULL DEFAULT 0,
    total_distance_m            INTEGER NOT NULL DEFAULT 0,
    total_vert_m                INTEGER NOT NULL DEFAULT 0,
    cal_earned                  NUMERIC NOT NULL DEFAULT 0,
    climbs_crossed              INTEGER NOT NULL DEFAULT 0,
    attester                    TEXT NOT NULL,
    settled_at                  BIGINT NOT NULL DEFAULT 0,
    settled_slot                NUMERIC NOT NULL DEFAULT 0,
    economic_epoch              NUMERIC NOT NULL DEFAULT 0,
    finalized                   BOOLEAN NOT NULL DEFAULT false,
    pda                         TEXT NOT NULL UNIQUE,
    chain_slot                  BIGINT,
    indexed_at                  TIMESTAMPTZ NOT NULL DEFAULT now(),
    bump                        SMALLINT,
    PRIMARY KEY (rider_pubkey, ride_hash_hex)
);

CREATE INDEX IF NOT EXISTS idx_indexed_ride_attestations_hash
    ON indexed_ride_attestations(ride_hash_hex);

CREATE INDEX IF NOT EXISTS idx_indexed_ride_attestations_completed
    ON indexed_ride_attestations(completed_at DESC, chain_slot DESC);

CREATE TABLE IF NOT EXISTS indexed_cal_mint_receipts (
    pda                     TEXT PRIMARY KEY,
    ride_attestation_pda    TEXT NOT NULL,
    rider_pubkey            TEXT NOT NULL,
    amount                  NUMERIC NOT NULL DEFAULT 0,
    chain_slot              BIGINT,
    indexed_at              TIMESTAMPTZ NOT NULL DEFAULT now(),
    bump                    SMALLINT,
    UNIQUE (ride_attestation_pda, rider_pubkey)
);

CREATE INDEX IF NOT EXISTS idx_indexed_cal_mint_receipts_rider
    ON indexed_cal_mint_receipts(rider_pubkey);

CREATE TABLE IF NOT EXISTS indexed_climb_completion_receipts (
    pda                     TEXT PRIMARY KEY,
    ride_attestation_pda    TEXT NOT NULL,
    vault_pda               TEXT NOT NULL,
    chain_slot              BIGINT,
    indexed_at              TIMESTAMPTZ NOT NULL DEFAULT now(),
    bump                    SMALLINT,
    UNIQUE (ride_attestation_pda, vault_pda)
);

CREATE INDEX IF NOT EXISTS idx_indexed_climb_completion_receipts_vault
    ON indexed_climb_completion_receipts(vault_pda);
