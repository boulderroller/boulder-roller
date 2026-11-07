-- =============================================================================
-- 098: Drop retired ProgramConfig allocation fields from the indexer read model
--
-- The on-chain ProgramConfig compact layout removed allocation_submitter and
-- total_vault_cal_allocated after the Merkle allocation path was retired.
-- Keeping these columns in the singleton projection would preserve a stale
-- public surface for a flow the protocol no longer supports.
-- =============================================================================

ALTER TABLE IF EXISTS indexed_program_config
    DROP COLUMN IF EXISTS allocation_submitter,
    DROP COLUMN IF EXISTS total_vault_cal_allocated;
