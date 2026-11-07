-- Harden epoch queue idempotency and distribution constraints

ALTER TABLE epoch_distributions
    ADD COLUMN IF NOT EXISTS is_points_period BOOLEAN NOT NULL DEFAULT true;

ALTER TABLE epoch_distributions
    ADD COLUMN IF NOT EXISTS attempt_count INTEGER NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS last_attempted_at TIMESTAMPTZ;

UPDATE epoch_distributions
SET is_points_period = true
WHERE is_points_period IS NULL;

WITH ranked AS (
    SELECT
        id,
        ROW_NUMBER() OVER (
            PARTITION BY epoch, vault_signature, is_points_period
            ORDER BY
                CASE WHEN status = 'completed' THEN 1 ELSE 0 END DESC,
                processed_at DESC NULLS LAST,
                created_at DESC
        ) AS rn
    FROM epoch_distributions
)
DELETE FROM epoch_distributions
WHERE id IN (SELECT id FROM ranked WHERE rn > 1);

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'epoch_distributions_epoch_vault_points_key'
    ) THEN
        ALTER TABLE epoch_distributions
            ADD CONSTRAINT epoch_distributions_epoch_vault_points_key
            UNIQUE (epoch, vault_signature, is_points_period);
    END IF;
END $$;

ALTER TABLE vault_distributions DROP CONSTRAINT IF EXISTS vault_distributions_vault_signature_epoch_key;
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'vault_distributions_vault_signature_epoch_points_key'
    ) THEN
        ALTER TABLE vault_distributions
            ADD CONSTRAINT vault_distributions_vault_signature_epoch_points_key
            UNIQUE (vault_signature, epoch, is_points_period);
    END IF;
END $$;

WITH ranked AS (
    SELECT
        id,
        ROW_NUMBER() OVER (
            PARTITION BY distribution_id, wallet, receipt_type
            ORDER BY created_at DESC
        ) AS rn
    FROM distribution_receipts
)
DELETE FROM distribution_receipts
WHERE id IN (SELECT id FROM ranked WHERE rn > 1);

CREATE UNIQUE INDEX IF NOT EXISTS idx_dist_receipts_unique
    ON distribution_receipts(distribution_id, wallet, receipt_type);
