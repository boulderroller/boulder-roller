-- ============================================================================
-- B3 — `finalized_at` first-class timestamp (bead mfab.2)
-- ============================================================================
-- Surfaces BACKEND_TRUTHS §3.3 at the DB / API boundary. `finalized_at` is the
-- wall-clock time the settlement week containing the relevant record became
-- immutable on-chain. It is authoritative for economic truth.
--
-- Source-of-truth arrow per BACKEND_TRUTHS §4:
--   on-chain event (block_time)  →  indexed_epoch_distributions
--                                →  epoch_distributions (legacy queue)
--                                →  rides (ride's settlement-week finalization)
--
-- `finalized_at` is NEVER fabricated by the backend. It is derived from the
-- `EpochRewardsDistributed` event's cluster `block_time`. NULL means "epoch
-- not yet finalized" (honest), never "missing data".
--
-- NOTE: this migration is additive. The propagation trigger that joins rides
-- to settlement-week distributions lands in the follow-up 097 migration.
-- Until that trigger observes chain distribution events, `rides.finalized_at`
-- remains NULL, which is the honest pending state.
-- ============================================================================

-- ----------------------------------------------------------------------------
-- 1) rides.finalized_at — per-ride immutability timestamp.
--    Populated when the settlement week containing `completed_at` is
--    finalized on-chain. Until populated, NULL signals "earnings not yet
--    locked" to downstream readers (mobile UI, BoulderScan, demo surface).
-- ----------------------------------------------------------------------------

ALTER TABLE rides
    ADD COLUMN IF NOT EXISTS finalized_at TIMESTAMPTZ NULL;

CREATE INDEX IF NOT EXISTS idx_rides_finalized_at
    ON rides(finalized_at)
    WHERE finalized_at IS NOT NULL;

COMMENT ON COLUMN rides.finalized_at IS
    'BACKEND_TRUTHS §3.3. Time the settlement week containing this ride''s '
    'completed_at became immutable on-chain. Derived from the '
    'EpochRewardsDistributed cluster block_time. NULL means the ride''s '
    'settlement week has not yet finalized. Never fabricated.';

-- ----------------------------------------------------------------------------
-- 2) indexed_epoch_distributions.finalized_at — generated column derived
--    directly from the chain event's cluster block_time. This is the
--    canonical source of finalization time for any vault+epoch settlement;
--    everything else on the backend flows downstream from here.
-- ----------------------------------------------------------------------------

ALTER TABLE indexed_epoch_distributions
    ADD COLUMN IF NOT EXISTS finalized_at TIMESTAMPTZ
    GENERATED ALWAYS AS (
        CASE WHEN block_time IS NOT NULL
             THEN to_timestamp(block_time)
             ELSE NULL
        END
    ) STORED;

CREATE INDEX IF NOT EXISTS idx_indexed_epoch_distributions_finalized_at
    ON indexed_epoch_distributions(finalized_at DESC)
    WHERE finalized_at IS NOT NULL;

COMMENT ON COLUMN indexed_epoch_distributions.finalized_at IS
    'BACKEND_TRUTHS §3.3 / §7.3. Settlement-week finalization time, derived '
    'from the on-chain EpochRewardsDistributed event''s cluster block_time. '
    'GENERATED ALWAYS — cannot be written by backend code.';

-- ----------------------------------------------------------------------------
-- 3) epoch_distributions.finalized_at — legacy queue table (backend-driven).
--    `processed_at` here is wall-clock time we submitted the tx; it conflates
--    settlement time with submit time. `finalized_at` separates the chain
--    truth from the submit time, and must be populated by a reconciliation
--    hook that reads `indexed_epoch_distributions` (chain projection) — never
--    from datetime.utcnow().
--
--    Until the reconciliation hook lands, `finalized_at` is NULL here.
-- ----------------------------------------------------------------------------

ALTER TABLE epoch_distributions
    ADD COLUMN IF NOT EXISTS finalized_at TIMESTAMPTZ NULL;

CREATE INDEX IF NOT EXISTS idx_epoch_distributions_finalized_at
    ON epoch_distributions(finalized_at)
    WHERE finalized_at IS NOT NULL;

COMMENT ON COLUMN epoch_distributions.finalized_at IS
    'BACKEND_TRUTHS §3.3. Settlement finalization time from the on-chain '
    'EpochRewardsDistributed event. Populated by reconciliation against '
    'indexed_epoch_distributions — never from datetime.utcnow(). NULL means '
    'the chain-side event has not yet been observed.';
