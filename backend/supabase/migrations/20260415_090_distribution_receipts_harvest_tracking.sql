-- Add harvest-tracking columns expected by the live vault harvest routes.
--
-- Current backend code reads distribution_receipts.harvested_at and
-- distribution_receipts.tx_signature, but the original table definition never
-- added those columns. That mismatch causes the harvest routes to fail at
-- runtime. This migration aligns the schema with the currently deployed route
-- contract so the safety-net pass can eliminate the immediate crash path.

ALTER TABLE distribution_receipts
    ADD COLUMN IF NOT EXISTS harvested_at TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS tx_signature TEXT;

CREATE INDEX IF NOT EXISTS idx_dist_receipts_pending_wallet
    ON distribution_receipts(wallet, distribution_id)
    WHERE harvested_at IS NULL;
