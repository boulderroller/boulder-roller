-- ============================================================================
-- NUMERIC TOKEN COLUMNS (u64 precision fix)
-- ============================================================================
-- Converts all token/economic amount columns from BIGINT to NUMERIC.
--
-- WHY: Solana u64 max = 2^64 - 1 = ~1.8 * 10^19.
-- DUNG has 9 decimals, so 1B supply = 10^18 lamports.
-- PostgreSQL BIGINT max = 2^63 - 1 = ~9.2 * 10^18.
-- JavaScript Number (IEEE 754 double) safe max = 2^53 - 1 = ~9 * 10^15.
--
-- The indexer was using Number() to convert BN.js u64 values, which silently
-- rounds values > 2^53. Even with bnToString(), BIGINT columns would truncate
-- values > 2^63 - 1. NUMERIC has arbitrary precision and handles all u64 values.
--
-- Migration: 081 (2026-03-07)
-- ============================================================================

-- ============================================================================
-- 1. indexed_vaults
-- ============================================================================
ALTER TABLE indexed_vaults
    ALTER COLUMN cal_tribute_accumulated TYPE NUMERIC USING cal_tribute_accumulated::NUMERIC,
    ALTER COLUMN total_cal_burned        TYPE NUMERIC USING total_cal_burned::NUMERIC,
    ALTER COLUMN total_dung_emitted      TYPE NUMERIC USING total_dung_emitted::NUMERIC,
    ALTER COLUMN total_cal_staked        TYPE NUMERIC USING total_cal_staked::NUMERIC,
    ALTER COLUMN reward_per_token_stored  TYPE NUMERIC USING reward_per_token_stored::NUMERIC,
    ALTER COLUMN reward_rate             TYPE NUMERIC USING reward_rate::NUMERIC,
    ALTER COLUMN pending_rewards         TYPE NUMERIC USING pending_rewards::NUMERIC,
    ALTER COLUMN total_staked            TYPE NUMERIC USING total_staked::NUMERIC;

-- ============================================================================
-- 2. indexed_stakes
-- ============================================================================
ALTER TABLE indexed_stakes
    ALTER COLUMN cal_staked                  TYPE NUMERIC USING cal_staked::NUMERIC,
    ALTER COLUMN lp_tokens                   TYPE NUMERIC USING lp_tokens::NUMERIC,
    ALTER COLUMN user_reward_per_token_paid   TYPE NUMERIC USING user_reward_per_token_paid::NUMERIC,
    ALTER COLUMN rewards_earned              TYPE NUMERIC USING rewards_earned::NUMERIC,
    ALTER COLUMN amount                      TYPE NUMERIC USING amount::NUMERIC;

-- ============================================================================
-- 3. indexed_completions
-- ============================================================================
ALTER TABLE indexed_completions
    ALTER COLUMN total_cal_tributed TYPE NUMERIC USING total_cal_tributed::NUMERIC;

-- ============================================================================
-- 4. indexed_accounts
-- ============================================================================
ALTER TABLE indexed_accounts
    ALTER COLUMN cal_balance      TYPE NUMERIC USING cal_balance::NUMERIC,
    ALTER COLUMN cal_earned_today TYPE NUMERIC USING cal_earned_today::NUMERIC,
    ALTER COLUMN total_tss        TYPE NUMERIC USING total_tss::NUMERIC;

-- ============================================================================
-- 5. indexed_supply
-- ============================================================================
ALTER TABLE indexed_supply
    ALTER COLUMN max_supply                TYPE NUMERIC USING max_supply::NUMERIC,
    ALTER COLUMN total_minted              TYPE NUMERIC USING total_minted::NUMERIC,
    ALTER COLUMN total_burned              TYPE NUMERIC USING total_burned::NUMERIC,
    ALTER COLUMN community_minted          TYPE NUMERIC USING community_minted::NUMERIC,
    ALTER COLUMN treasury_minted           TYPE NUMERIC USING treasury_minted::NUMERIC,
    ALTER COLUMN team_minted               TYPE NUMERIC USING team_minted::NUMERIC,
    ALTER COLUMN investor_minted           TYPE NUMERIC USING investor_minted::NUMERIC,
    ALTER COLUMN pol_minted                TYPE NUMERIC USING pol_minted::NUMERIC,
    ALTER COLUMN current_emission_rate_bps TYPE NUMERIC USING current_emission_rate_bps::NUMERIC;

-- Add computed circulating supply column
ALTER TABLE indexed_supply
    ADD COLUMN IF NOT EXISTS circulating NUMERIC GENERATED ALWAYS AS (total_minted - total_burned) STORED;

-- ============================================================================
-- 6. indexed_beetle_cards
-- ============================================================================
ALTER TABLE indexed_beetle_cards
    ALTER COLUMN score TYPE NUMERIC USING score::NUMERIC;

-- ============================================================================
-- 7. indexed_legends
-- ============================================================================
ALTER TABLE indexed_legends
    ALTER COLUMN total_earned TYPE NUMERIC USING total_earned::NUMERIC;

-- ============================================================================
-- 8. indexed_program_config
-- ============================================================================
ALTER TABLE indexed_program_config
    ALTER COLUMN total_vault_cal_allocated TYPE NUMERIC USING total_vault_cal_allocated::NUMERIC;

-- ============================================================================
-- COMMENTS
-- ============================================================================
COMMENT ON COLUMN indexed_vaults.cal_tribute_accumulated IS 'u64 token amount (NUMERIC for full precision)';
COMMENT ON COLUMN indexed_supply.circulating IS 'Computed: total_minted - total_burned';
