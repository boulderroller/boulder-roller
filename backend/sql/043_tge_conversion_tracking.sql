-- Migration: 043_tge_conversion_tracking.sql
-- Description: Add tracking columns for TGE SPL token minting
-- Date: 2025-01-21

-- =============================================================================
-- TGE CONVERSION TRACKING ENHANCEMENTS
-- Add columns to track on-chain minting status for TGE conversions
-- =============================================================================

-- Rename tx_signature to mint_signature for clarity
-- (Only if the old column exists and new one doesn't)
DO $$
BEGIN
    -- Add mint_signature if tx_signature exists (rename scenario)
    IF EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'tge_conversions' AND column_name = 'tx_signature'
    ) AND NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'tge_conversions' AND column_name = 'mint_signature'
    ) THEN
        ALTER TABLE tge_conversions RENAME COLUMN tx_signature TO mint_signature;
    END IF;

    -- Add mint_signature if it doesn't exist (fresh install)
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'tge_conversions' AND column_name = 'mint_signature'
    ) THEN
        ALTER TABLE tge_conversions ADD COLUMN mint_signature TEXT;
    END IF;

    -- Add mint_error column to track failed minting attempts
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'tge_conversions' AND column_name = 'mint_error'
    ) THEN
        ALTER TABLE tge_conversions ADD COLUMN mint_error TEXT;
    END IF;

    -- Add minted_at timestamp to track when tokens were actually minted
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'tge_conversions' AND column_name = 'minted_at'
    ) THEN
        ALTER TABLE tge_conversions ADD COLUMN minted_at TIMESTAMPTZ;
    END IF;

    -- Add retry_count to track minting retry attempts
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'tge_conversions' AND column_name = 'retry_count'
    ) THEN
        ALTER TABLE tge_conversions ADD COLUMN retry_count INTEGER DEFAULT 0;
    END IF;
END $$;

-- Add comments for new columns
COMMENT ON COLUMN tge_conversions.mint_signature IS 'Solana transaction signature for SPL token mint';
COMMENT ON COLUMN tge_conversions.mint_error IS 'Error message if minting failed';
COMMENT ON COLUMN tge_conversions.minted_at IS 'Timestamp when tokens were successfully minted on-chain';
COMMENT ON COLUMN tge_conversions.retry_count IS 'Number of minting retry attempts';

-- Create index for finding failed conversions that need retry
CREATE INDEX IF NOT EXISTS idx_tge_conversions_failed
    ON tge_conversions(wallet)
    WHERE mint_signature IS NULL AND mint_error IS NOT NULL;

-- Create index for finding pending (not yet minted) conversions
CREATE INDEX IF NOT EXISTS idx_tge_conversions_pending
    ON tge_conversions(wallet)
    WHERE mint_signature IS NULL AND mint_error IS NULL;

-- =============================================================================
-- HELPER FUNCTION: Retry failed TGE minting
-- =============================================================================

CREATE OR REPLACE FUNCTION get_failed_tge_conversions()
RETURNS TABLE (
    id UUID,
    wallet TEXT,
    dung_received NUMERIC,
    unlocked_amount NUMERIC,
    mint_error TEXT,
    retry_count INTEGER,
    converted_at TIMESTAMPTZ
) AS $$
BEGIN
    RETURN QUERY
    SELECT
        c.id,
        c.wallet,
        c.dung_received,
        c.unlocked_amount,
        c.mint_error,
        c.retry_count,
        c.converted_at
    FROM tge_conversions c
    WHERE c.mint_signature IS NULL
      AND c.mint_error IS NOT NULL
    ORDER BY c.converted_at ASC;
END;
$$ LANGUAGE plpgsql STABLE;

COMMENT ON FUNCTION get_failed_tge_conversions IS 'Get all TGE conversions that failed minting (for retry)';

-- =============================================================================
-- HELPER FUNCTION: Update minting status after successful mint
-- =============================================================================

CREATE OR REPLACE FUNCTION update_tge_mint_status(
    p_wallet TEXT,
    p_mint_signature TEXT,
    p_mint_error TEXT DEFAULT NULL
) RETURNS BOOLEAN AS $$
DECLARE
    updated_count INTEGER;
BEGIN
    UPDATE tge_conversions
    SET
        mint_signature = p_mint_signature,
        mint_error = p_mint_error,
        minted_at = CASE WHEN p_mint_signature IS NOT NULL THEN now() ELSE NULL END,
        retry_count = retry_count + 1
    WHERE wallet = p_wallet
      AND mint_signature IS NULL
    RETURNING 1 INTO updated_count;

    RETURN updated_count > 0;
END;
$$ LANGUAGE plpgsql;

COMMENT ON FUNCTION update_tge_mint_status IS 'Update TGE conversion with minting result';
