-- Cleanup: Rename remaining swanny references to local_legend

-- 1. Rename swanny_amount to local_legend_amount in vault_distributions
DO $$
BEGIN
    IF EXISTS (
        SELECT 1
        FROM information_schema.columns
        WHERE table_name = 'vault_distributions'
          AND column_name = 'swanny_amount'
    ) AND NOT EXISTS (
        SELECT 1
        FROM information_schema.columns
        WHERE table_name = 'vault_distributions'
          AND column_name = 'local_legend_amount'
    ) THEN
        EXECUTE 'ALTER TABLE vault_distributions RENAME COLUMN swanny_amount TO local_legend_amount';
    END IF;
END $$;

COMMENT ON COLUMN vault_distributions.local_legend_amount IS '3% to Local Legend';

-- 2. Update receipt_type constraint to use LOCAL_LEGEND instead of SWANNY
ALTER TABLE distribution_receipts DROP CONSTRAINT IF EXISTS chk_receipt_type;
ALTER TABLE distribution_receipts
    ADD CONSTRAINT chk_receipt_type
    CHECK (receipt_type IN ('LEADERBOARD', 'STAKE', 'LOCAL_LEGEND', 'POL', 'PROTOCOL'));

-- 3. Migrate existing SWANNY receipts to LOCAL_LEGEND
UPDATE distribution_receipts SET receipt_type = 'LOCAL_LEGEND' WHERE receipt_type = 'SWANNY';
