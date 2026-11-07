-- ============================================================================
-- INDEXER TABLES (A2: Solana Indexer & Reconciliation)
-- ============================================================================
-- Creates the full read model for the boulder_rollers Solana indexer.
-- Extends indexed_vaults with economics fields and creates new tables
-- for all other account types, transactions, events, and operational state.
--
-- Migration: 080 (2026-03-06)
-- Design: history/A2_INDEXER_RECONCILIATION_DESIGN_2026-03-06.md
-- ============================================================================

-- ============================================================================
-- 1. EXTEND indexed_vaults WITH ECONOMICS + STAKING FIELDS
-- ============================================================================
-- The existing table has: id, signature_hex, signature_hash_hex, minter, name,
-- vert_m, distance_m, avg_gradient_pct, total_completions, total_staked,
-- kom_holder, kom_time_s, pda, created_at, vault_pot, indexed_at, last_synced_at

ALTER TABLE indexed_vaults
    ADD COLUMN IF NOT EXISTS mint_epoch          BIGINT NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS rights_expires_epoch BIGINT NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS kom_set_epoch       BIGINT NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS avatar_ipfs         TEXT,
    ADD COLUMN IF NOT EXISTS slogan              TEXT,
    ADD COLUMN IF NOT EXISTS cal_tribute_accumulated BIGINT NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS total_cal_burned    BIGINT NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS total_dung_emitted  BIGINT NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS total_cal_staked    BIGINT NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS staker_count        INTEGER NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS reward_per_token_stored BIGINT NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS last_update_time    BIGINT NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS reward_rate         BIGINT NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS pending_rewards     BIGINT NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS chain_slot          BIGINT,
    ADD COLUMN IF NOT EXISTS bump                SMALLINT;

-- Indexes for the new economics fields
CREATE INDEX IF NOT EXISTS idx_vaults_cal_staked ON indexed_vaults(total_cal_staked DESC);
CREATE INDEX IF NOT EXISTS idx_vaults_completions_desc ON indexed_vaults(total_completions DESC);
CREATE INDEX IF NOT EXISTS idx_vaults_created_desc ON indexed_vaults(created_at DESC);

-- ============================================================================
-- 2. indexed_leaderboards
-- ============================================================================
CREATE TABLE IF NOT EXISTS indexed_leaderboards (
    vault_id        BIGINT PRIMARY KEY,
    entries         JSONB NOT NULL DEFAULT '[]',
    -- entries: [{ "user": "pubkey", "time_s": 161, "recorded_at": 1709654400 }]
    last_updated    BIGINT NOT NULL DEFAULT 0,
    pda             TEXT,
    chain_slot      BIGINT,
    indexed_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    bump            SMALLINT
);

-- ============================================================================
-- 3. indexed_legends (LocalLegend)
-- ============================================================================
CREATE TABLE IF NOT EXISTS indexed_legends (
    vault_id                BIGINT PRIMARY KEY,
    holder                  TEXT,
    election_period         BIGINT NOT NULL DEFAULT 0,
    term_start_epoch        BIGINT NOT NULL DEFAULT 0,
    term_end_epoch          BIGINT NOT NULL DEFAULT 0,
    completions_at_election INTEGER NOT NULL DEFAULT 0,
    runner_up               TEXT,
    runner_up_completions   INTEGER NOT NULL DEFAULT 0,
    total_earned            BIGINT NOT NULL DEFAULT 0,
    is_active               BOOLEAN NOT NULL DEFAULT false,
    chain_slot              BIGINT,
    indexed_at              TIMESTAMPTZ NOT NULL DEFAULT now(),
    bump                    SMALLINT
);

CREATE INDEX IF NOT EXISTS idx_legends_holder
    ON indexed_legends(holder) WHERE holder IS NOT NULL;

-- ============================================================================
-- 4. indexed_stakes (VaultStake)
-- ============================================================================
CREATE TABLE IF NOT EXISTS indexed_stakes (
    user_pubkey             TEXT NOT NULL,
    vault_id                BIGINT NOT NULL,
    cal_staked              BIGINT NOT NULL DEFAULT 0,
    lp_tokens               BIGINT NOT NULL DEFAULT 0,
    staked_at               BIGINT NOT NULL DEFAULT 0,
    user_reward_per_token_paid BIGINT NOT NULL DEFAULT 0,
    rewards_earned          BIGINT NOT NULL DEFAULT 0,
    amount                  BIGINT NOT NULL DEFAULT 0,
    pda                     TEXT NOT NULL,
    chain_slot              BIGINT,
    indexed_at              TIMESTAMPTZ NOT NULL DEFAULT now(),
    bump                    SMALLINT,
    PRIMARY KEY (user_pubkey, vault_id)
);

CREATE INDEX IF NOT EXISTS idx_stakes_user
    ON indexed_stakes(user_pubkey) WHERE cal_staked > 0;
CREATE INDEX IF NOT EXISTS idx_stakes_vault
    ON indexed_stakes(vault_id) WHERE cal_staked > 0;

-- ============================================================================
-- 5. indexed_completions (VaultCompletion)
-- ============================================================================
CREATE TABLE IF NOT EXISTS indexed_completions (
    user_pubkey             TEXT NOT NULL,
    vault_id                BIGINT NOT NULL,
    completions             INTEGER NOT NULL DEFAULT 0,
    best_time_s             INTEGER NOT NULL DEFAULT 0,
    last_completed_at       BIGINT NOT NULL DEFAULT 0,
    total_cal_tributed      BIGINT NOT NULL DEFAULT 0,
    pda                     TEXT NOT NULL,
    chain_slot              BIGINT,
    indexed_at              TIMESTAMPTZ NOT NULL DEFAULT now(),
    bump                    SMALLINT,
    PRIMARY KEY (user_pubkey, vault_id)
);

CREATE INDEX IF NOT EXISTS idx_completions_user
    ON indexed_completions(user_pubkey);
CREATE INDEX IF NOT EXISTS idx_completions_vault
    ON indexed_completions(vault_id);

-- ============================================================================
-- 6. indexed_accounts (UserState)
-- ============================================================================
CREATE TABLE IF NOT EXISTS indexed_accounts (
    owner_pubkey    TEXT PRIMARY KEY,
    cal_balance     BIGINT NOT NULL DEFAULT 0,
    cal_earned_today BIGINT NOT NULL DEFAULT 0,
    last_cal_mint   BIGINT NOT NULL DEFAULT 0,
    total_rides     BIGINT NOT NULL DEFAULT 0,
    total_tss       BIGINT NOT NULL DEFAULT 0,
    bio_score       SMALLINT NOT NULL DEFAULT 1000,
    pda             TEXT NOT NULL,
    chain_slot      BIGINT,
    indexed_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    bump            SMALLINT
);

-- ============================================================================
-- 7. indexed_beetle_cards (BeetleCard)
-- ============================================================================
CREATE TABLE IF NOT EXISTS indexed_beetle_cards (
    owner_pubkey    TEXT NOT NULL,
    card_type       SMALLINT NOT NULL,
    scope_id_hex    CHAR(64) NOT NULL,
    score           BIGINT NOT NULL DEFAULT 0,
    level           SMALLINT NOT NULL DEFAULT 0,
    patterns_scored INTEGER NOT NULL DEFAULT 0,
    total_dung_burned BIGINT NOT NULL DEFAULT 0,
    last_updated    BIGINT NOT NULL DEFAULT 0,
    created_at      BIGINT NOT NULL DEFAULT 0,
    pda             TEXT NOT NULL,
    chain_slot      BIGINT,
    indexed_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    bump            SMALLINT,
    PRIMARY KEY (owner_pubkey, card_type, scope_id_hex)
);

CREATE INDEX IF NOT EXISTS idx_beetle_owner
    ON indexed_beetle_cards(owner_pubkey);

-- ============================================================================
-- 8. indexed_supply (DungMintState singleton)
-- ============================================================================
CREATE TABLE IF NOT EXISTS indexed_supply (
    id                          INTEGER PRIMARY KEY DEFAULT 1 CHECK (id = 1),
    authority                   TEXT NOT NULL,
    max_supply                  BIGINT NOT NULL,
    total_minted                BIGINT NOT NULL DEFAULT 0,
    total_burned                BIGINT NOT NULL DEFAULT 0,
    community_minted            BIGINT NOT NULL DEFAULT 0,
    treasury_minted             BIGINT NOT NULL DEFAULT 0,
    team_minted                 BIGINT NOT NULL DEFAULT 0,
    investor_minted             BIGINT NOT NULL DEFAULT 0,
    pol_minted                  BIGINT NOT NULL DEFAULT 0,
    current_emission_rate_bps   BIGINT NOT NULL DEFAULT 10000,
    last_halving_epoch          BIGINT NOT NULL DEFAULT 0,
    pda                         TEXT NOT NULL,
    chain_slot                  BIGINT,
    indexed_at                  TIMESTAMPTZ NOT NULL DEFAULT now(),
    bump                        SMALLINT
);

-- ============================================================================
-- 9. indexed_program_config (ProgramConfig singleton)
-- ============================================================================
CREATE TABLE IF NOT EXISTS indexed_program_config (
    id                      INTEGER PRIMARY KEY DEFAULT 1 CHECK (id = 1),
    admin_authority         TEXT NOT NULL,
    backend_authority       TEXT NOT NULL,
    initialized             BOOLEAN NOT NULL DEFAULT false,
    cal_mint                TEXT,
    dung_mint               TEXT,
    cal_mint_auth_bump      SMALLINT,
    dung_mint_auth_bump     SMALLINT,
    allocation_submitter    TEXT,
    total_vault_cal_allocated BIGINT NOT NULL DEFAULT 0,
    pda                     TEXT NOT NULL,
    chain_slot              BIGINT,
    indexed_at              TIMESTAMPTZ NOT NULL DEFAULT now(),
    bump                    SMALLINT
);

-- ============================================================================
-- 10. indexed_vault_counter (VaultCounter singleton)
-- ============================================================================
CREATE TABLE IF NOT EXISTS indexed_vault_counter (
    id          INTEGER PRIMARY KEY DEFAULT 1 CHECK (id = 1),
    count       BIGINT NOT NULL DEFAULT 0,
    pda         TEXT NOT NULL,
    chain_slot  BIGINT,
    indexed_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    bump        SMALLINT
);

-- ============================================================================
-- 11. indexed_alloc_batches (AllocationBatch)
-- ============================================================================
CREATE TABLE IF NOT EXISTS indexed_alloc_batches (
    batch_id        BIGINT PRIMARY KEY,
    root_hex        CHAR(64) NOT NULL,
    leaf_count      INTEGER NOT NULL,
    tree_depth      SMALLINT NOT NULL,
    epoch           BIGINT NOT NULL,
    submitted_at    BIGINT NOT NULL,
    submitter       TEXT NOT NULL,
    pda             TEXT NOT NULL,
    chain_slot      BIGINT,
    indexed_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    bump            SMALLINT
);

CREATE INDEX IF NOT EXISTS idx_alloc_batch_epoch
    ON indexed_alloc_batches(epoch);

-- ============================================================================
-- 12. indexed_transactions
-- ============================================================================
CREATE TABLE IF NOT EXISTS indexed_transactions (
    signature           TEXT NOT NULL,
    slot                BIGINT NOT NULL,
    block_time          BIGINT,
    status              TEXT NOT NULL,
    error_message       TEXT,
    fee_lamports        BIGINT NOT NULL DEFAULT 0,
    compute_units       INTEGER,
    instruction_index   SMALLINT NOT NULL DEFAULT 0,
    instruction_name    TEXT NOT NULL,
    instruction_args    JSONB NOT NULL DEFAULT '{}',
    instruction_accounts JSONB NOT NULL DEFAULT '{}',
    indexed_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (signature, instruction_index)
);

CREATE INDEX IF NOT EXISTS idx_tx_slot ON indexed_transactions(slot DESC);
CREATE INDEX IF NOT EXISTS idx_tx_block_time ON indexed_transactions(block_time DESC);
CREATE INDEX IF NOT EXISTS idx_tx_instruction ON indexed_transactions(instruction_name);

-- ============================================================================
-- 13. indexed_events
-- ============================================================================
CREATE TABLE IF NOT EXISTS indexed_events (
    id                  BIGSERIAL PRIMARY KEY,
    tx_signature        TEXT NOT NULL,
    event_index         SMALLINT NOT NULL DEFAULT 0,
    event_name          TEXT NOT NULL,
    fields              JSONB NOT NULL DEFAULT '{}',
    slot                BIGINT NOT NULL,
    block_time          BIGINT,
    vault_id            BIGINT,
    user_pubkey         TEXT,
    indexed_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_events_vault_time
    ON indexed_events(vault_id, block_time DESC) WHERE vault_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_events_user_time
    ON indexed_events(user_pubkey, block_time DESC) WHERE user_pubkey IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_events_name_time
    ON indexed_events(event_name, block_time DESC);
CREATE INDEX IF NOT EXISTS idx_events_tx
    ON indexed_events(tx_signature);

-- Prevent duplicate events
CREATE UNIQUE INDEX IF NOT EXISTS idx_events_unique
    ON indexed_events(tx_signature, event_index);

-- ============================================================================
-- 14. indexer_sync_state (operational singleton)
-- ============================================================================
CREATE TABLE IF NOT EXISTS indexer_sync_state (
    id                      INTEGER PRIMARY KEY DEFAULT 1 CHECK (id = 1),
    last_account_slot       BIGINT NOT NULL DEFAULT 0,
    last_account_sync_at    TIMESTAMPTZ,
    last_tx_signature       TEXT,
    last_tx_slot            BIGINT NOT NULL DEFAULT 0,
    last_tx_sync_at         TIMESTAMPTZ,
    last_snapshot_at        TIMESTAMPTZ,
    last_snapshot_slot      BIGINT,
    snapshot_account_count  INTEGER,
    stream_connected        BOOLEAN NOT NULL DEFAULT false,
    stream_connected_since  TIMESTAMPTZ,
    stream_disconnects      INTEGER NOT NULL DEFAULT 0,
    updated_at              TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ============================================================================
-- 15. reconciliation_log
-- ============================================================================
CREATE TABLE IF NOT EXISTS reconciliation_log (
    id                  BIGSERIAL PRIMARY KEY,
    run_at              TIMESTAMPTZ NOT NULL DEFAULT now(),
    run_type            TEXT NOT NULL,
    accounts_checked    INTEGER NOT NULL DEFAULT 0,
    discrepancies_found INTEGER NOT NULL DEFAULT 0,
    discrepancies       JSONB,
    auto_corrected      INTEGER NOT NULL DEFAULT 0,
    chain_slot          BIGINT,
    vault_count_chain   INTEGER,
    vault_count_indexed INTEGER,
    duration_ms         INTEGER,
    status              TEXT NOT NULL DEFAULT 'completed'
);

CREATE INDEX IF NOT EXISTS idx_reconciliation_run
    ON reconciliation_log(run_at DESC);

-- NOTE: tx_lifecycle table already exists from migration 073 (atomic_financial_ops).
-- The A2 design specifies a different schema with intent-based tracking.
-- That schema extension will be handled in a future migration when the
-- backend workflow layer (A1) is ready to adopt the new lifecycle model.

-- ============================================================================
-- COMMENTS
-- ============================================================================
COMMENT ON TABLE indexed_leaderboards IS 'Vault top-10 leaderboard entries (JSONB), synced from VaultLeaderboard PDA';
COMMENT ON TABLE indexed_legends IS 'Local Legend (elected curator) per vault, synced from LocalLegend PDA';
COMMENT ON TABLE indexed_stakes IS 'User staking positions per vault, synced from VaultStake PDA';
COMMENT ON TABLE indexed_completions IS 'User completion records per vault, synced from VaultCompletion PDA';
COMMENT ON TABLE indexed_accounts IS 'User on-chain state (legacy CAL snapshots, rides, TSS), synced from UserState PDA';
COMMENT ON TABLE indexed_beetle_cards IS 'Soulbound BeetleCard NFTs, synced from BeetleCard PDA';
COMMENT ON TABLE indexed_supply IS 'Global DUNG supply state singleton, synced from DungMintState PDA';
COMMENT ON TABLE indexed_program_config IS 'Program config singleton, synced from ProgramConfig PDA';
COMMENT ON TABLE indexed_vault_counter IS 'Vault counter singleton, synced from VaultCounter PDA';
COMMENT ON TABLE indexed_alloc_batches IS 'Merkle allocation batches for CAL claiming, synced from AllocationBatch PDA';
COMMENT ON TABLE indexed_transactions IS 'Decoded boulder_rollers program transactions from replay processor';
COMMENT ON TABLE indexed_events IS 'Decoded Anchor events from boulder_rollers program transaction logs';
COMMENT ON TABLE indexer_sync_state IS 'Indexer operational state: sync cursors, stream health';
COMMENT ON TABLE reconciliation_log IS 'Reconciliation run history: chain vs indexed state comparisons';
