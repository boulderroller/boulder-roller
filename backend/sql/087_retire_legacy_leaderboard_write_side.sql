-- Migration: 087_retire_legacy_leaderboard_write_side.sql
-- Description: Retire legacy DB-as-truth Record Board writers.
-- Date: 2026-04-20
--
-- PROTOCOL_TRUTHS / BACKEND_TRUTHS alignment:
--   * The on-chain VaultLeaderboard / Record Board is authoritative.
--   * indexed_leaderboards is the chain-derived projection.
--   * vault_leaderboards is a legacy read cache, not a write-side truth source.
--   * Repair path is reindex-from-chain, never DB-to-chain or DB-native rank mutation.

-- Drop legacy RPC functions that could mutate leaderboard truth directly in DB.
DROP FUNCTION IF EXISTS record_vault_completion_with_best_time(TEXT, TEXT, TEXT, INTEGER, INTEGER);

DROP FUNCTION IF EXISTS update_vault_leaderboard(TEXT, TEXT, INTEGER, INTEGER, UUID);
DROP FUNCTION IF EXISTS update_vault_leaderboard(TEXT, TEXT, INTEGER, INTEGER, UUID, TIMESTAMPTZ);
DROP FUNCTION IF EXISTS update_vault_leaderboard(TEXT, TEXT, INTEGER, INTEGER, UUID, TIMESTAMPTZ, TEXT, UUID);
DROP FUNCTION IF EXISTS update_vault_leaderboard_with_notifications(TEXT, TEXT, INTEGER, INTEGER, UUID, TIMESTAMPTZ);

DROP FUNCTION IF EXISTS rebuild_vault_leaderboard(TEXT);
DROP FUNCTION IF EXISTS rebuild_all_vault_leaderboards();

-- Drop legacy epoch snapshot helpers that read DB-native leaderboard state for
-- distribution. Settlement projections now come from indexed chain events.
DROP FUNCTION IF EXISTS snapshot_vault_leaderboard(INTEGER, TEXT);
DROP FUNCTION IF EXISTS snapshot_all_leaderboards_for_epoch(INTEGER);
DROP FUNCTION IF EXISTS get_epoch_leaderboard_snapshot(INTEGER, TEXT);
DROP FUNCTION IF EXISTS link_snapshot_to_distribution(INTEGER, TEXT, UUID);
DROP FUNCTION IF EXISTS compare_snapshot_to_live(INTEGER, TEXT);
DROP FUNCTION IF EXISTS get_epoch_snapshot_summary(INTEGER);
DROP FUNCTION IF EXISTS cleanup_old_epoch_snapshots(INTEGER);

COMMENT ON TABLE vault_leaderboards IS
    'Legacy read cache for Record Board views. Not authoritative. Do not mutate from ride processing; rebuild only from on-chain/indexer projection.';

-- Runtime guard: fail closed if any forgotten path tries to mutate the legacy
-- table. A future operator/admin chain-derived rebuild may deliberately opt in
-- inside a single DB session:
--
--   SET LOCAL br.allow_legacy_leaderboard_projection_write = 'on';
--
-- That override is intentionally session-local so application runtime code
-- cannot accidentally keep the table writable.
CREATE OR REPLACE FUNCTION prevent_legacy_vault_leaderboards_write()
RETURNS trigger AS $$
BEGIN
    IF current_setting('br.allow_legacy_leaderboard_projection_write', true) = 'on' THEN
        IF TG_OP = 'DELETE' THEN
            RETURN OLD;
        END IF;
        RETURN NEW;
    END IF;

    RAISE EXCEPTION
        'vault_leaderboards is a legacy read cache; Record Board truth is on-chain and must be repaired by reindexing from chain'
        USING ERRCODE = '2F000';
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_prevent_legacy_vault_leaderboards_write ON vault_leaderboards;

CREATE TRIGGER trg_prevent_legacy_vault_leaderboards_write
BEFORE INSERT OR UPDATE OR DELETE ON vault_leaderboards
FOR EACH ROW
EXECUTE FUNCTION prevent_legacy_vault_leaderboards_write();

COMMENT ON FUNCTION prevent_legacy_vault_leaderboards_write IS
    'Blocks accidental DB-native Record Board writes. Use only session-local override for chain-derived legacy-cache rebuilds.';
