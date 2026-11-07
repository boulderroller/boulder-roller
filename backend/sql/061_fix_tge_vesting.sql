-- Migration: 061_fix_tge_vesting.sql
-- Description: Fix TGE vesting config from 25/75 to 100/0 (no vesting)
-- Date: 2025-02-13
--
-- The spec says "100% at TGE, no vesting (Hyperliquid-style approach)"
-- but 031_points_period.sql defaulted to 25% unlock / 75% vested over 12 months.
-- This is a critical misconfiguration: if TGE fires with the old defaults,
-- users would only receive 25% of their DUNG immediately instead of 100%.

UPDATE points_config
SET tge_unlock_pct = 100,
    vesting_months = 0,
    updated_at = now()
WHERE id = 1;

-- Update stale comments on tge_conversions columns
COMMENT ON COLUMN tge_conversions.vested_amount IS 'Vested DUNG amount (0 under current no-vesting policy)';
COMMENT ON COLUMN tge_conversions.unlocked_amount IS '100% of DUNG unlocked at TGE (no vesting)';
