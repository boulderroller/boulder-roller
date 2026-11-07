-- =============================================================================
-- 099: Project governance-configurable ProgramConfig protocol parameters
--
-- ProgramConfig now stores the live economic parameters that were previously
-- hardcoded in the Anchor program. The indexer mirrors them so read surfaces can
-- explain current economics without treating source constants as truth.
-- =============================================================================

ALTER TABLE IF EXISTS indexed_program_config
    ADD COLUMN IF NOT EXISTS vault_creation_dung NUMERIC NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS vault_creation_cal NUMERIC NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS harvest_fee_bps NUMERIC NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS minter_rights_epochs NUMERIC NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS local_legend_term_epochs NUMERIC NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS epochs_per_halving NUMERIC NOT NULL DEFAULT 0;

COMMENT ON COLUMN indexed_program_config.vault_creation_dung IS
    'Live DUNG burn required for DUNG-only vault creation';
COMMENT ON COLUMN indexed_program_config.vault_creation_cal IS
    'Live CAL burn/deposit threshold for CAL-backed vault creation paths';
COMMENT ON COLUMN indexed_program_config.harvest_fee_bps IS
    'Live harvest fee in basis points';
COMMENT ON COLUMN indexed_program_config.minter_rights_epochs IS
    'Live founder metadata/culture rights duration in settlement weeks';
COMMENT ON COLUMN indexed_program_config.local_legend_term_epochs IS
    'Live Local Legend term duration in settlement weeks';
COMMENT ON COLUMN indexed_program_config.epochs_per_halving IS
    'Live settlement-week interval between emission halvings';
