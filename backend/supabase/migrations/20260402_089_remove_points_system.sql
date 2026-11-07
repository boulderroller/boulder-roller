-- Migration: Remove points system
-- Date: 2026-04-02
-- Context: Points were a pre-TGE loyalty overlay (1 point per TSS). Real tokens
-- (CAL/DUNG) are live on devnet. Points system is fully removed from code.
--
-- NOTE: Apply AFTER verifying backend code is deployed without points imports.
-- Supabase project paused until 2026-04-09 — apply then.

-- ============================================================================
-- Drop functions first (they reference the tables)
-- ============================================================================

DROP FUNCTION IF EXISTS add_points(text, numeric, text, text, text, jsonb);
DROP FUNCTION IF EXISTS get_wallet_entitlements(text);
DROP FUNCTION IF EXISTS is_points_period_active();
DROP FUNCTION IF EXISTS get_points_per_dung();
DROP FUNCTION IF EXISTS sync_points_compat_from_ledger(text, text, numeric, text, text, text, jsonb);
DROP FUNCTION IF EXISTS points_wallet_balances_current();

-- ============================================================================
-- Drop points-specific tables
-- ============================================================================

DROP TABLE IF EXISTS tge_conversions;
DROP TABLE IF EXISTS points_events;
DROP TABLE IF EXISTS points_entitlement_config;
DROP TABLE IF EXISTS points_entitlement_tiers;
DROP TABLE IF EXISTS points_config;
DROP TABLE IF EXISTS wallet_points;

-- ============================================================================
-- Drop points columns from other tables (optional — safe to leave as dead columns)
-- Uncomment if you want a clean schema. Leave commented if you want to preserve
-- historical data until you're sure nothing reads these columns.
-- ============================================================================

-- ALTER TABLE rides DROP COLUMN IF EXISTS points_earned;
-- ALTER TABLE vault_stakes DROP COLUMN IF EXISTS points_staked;

-- NOTE: Keeping is_points_period on vault_distributions and epoch_distributions
-- as historical markers (all future rows will have is_points_period = false).
-- These columns are harmless and preserve distribution history context.

-- ============================================================================
-- Clean up economic_events with POINTS denomination (optional)
-- Uncomment to remove historical points ledger entries.
-- ============================================================================

-- DELETE FROM economic_events WHERE denomination = 'POINTS';
