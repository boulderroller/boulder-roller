# Stage 1 production schema parity — 15 October 2026

Table-presence audit for keeper #94, indexer #97, transactions #98 and portal #99. The source is the user-supplied read-only production public-table list, preserved in [the committed inventory](../../backend/tests/sql/fixtures/stage1_production_tables_20261015.json). This proves table presence only, not production columns, grants, migration ledger state or deployment of this stack. The portal uses the backend API, not the database directly.

## Existing production dependencies

Every relation below is in that snapshot. The consumer names include existing indexer paths exercised alongside Stage 1.

| Relation | Consumer |
|---|---|
| `canon_climbs` | `indexer/src/api.ts` |
| `canon_indexer_pending` | `indexer/src/writers/vault.ts` |
| `canon_indexer_quarantine` | `indexer/src/writers/canon.ts` |
| `canon_traversal_evidence` | `backend/app/services/stage1_keeper_snapshot.py` |
| `canon_vault_activations` | `indexer/src/api.ts` |
| `deleted_account_tombstones` | `backend/sql/170_stage1_keeper.sql` |
| `deleted_wallets` | `backend/sql/170_stage1_keeper.sql` |
| `deletion_requests` | `backend/sql/170_stage1_keeper.sql` |
| `indexed_accounts` | `indexer/src/api.ts` |
| `indexed_beetle_cards` | `indexer/src/api.ts` |
| `indexed_cal_mint_receipts` | `indexer/src/writers/identity.ts` |
| `indexed_climb_completion_flows` | `indexer/src/modes/replay.ts` |
| `indexed_climb_completion_receipts` | `indexer/src/writers/identity.ts` |
| `indexed_climbs` | `indexer/src/api.ts` |
| `indexed_completions` | `indexer/src/api.ts` |
| `indexed_epoch_distributions` | `indexer/src/api.ts` |
| `indexed_events` | `indexer/src/api.ts` |
| `indexed_held_ride_release_authorities` | `indexer/src/releaseWeek.ts` |
| `indexed_leaderboards` | `indexer/src/api.ts` |
| `indexed_legends` | `indexer/src/api.ts` |
| `indexed_program_config` | `indexer/src/api.ts` |
| `indexed_ride_attestations` | `indexer/src/api.ts` |
| `indexed_rider_souls` | `indexer/src/api.ts` |
| `indexed_staker_allocations` | `indexer/src/modes/replay.ts` |
| `indexed_stakes` | `indexer/src/api.ts` |
| `indexed_supply` | `indexer/src/api.ts` |
| `indexed_transactions` | `indexer/src/api.ts` |
| `indexed_vault_activations` | `indexer/src/api.ts` |
| `indexed_vault_counter` | `indexer/src/writers/vault.ts` |
| `indexed_vaults` | `indexer/src/api.ts` |
| `indexer_sync_state` | `indexer/src/api.ts` |
| `notification_preferences` | `backend/app/repositories/notification.py` |
| `notifications` | `backend/app/repositories/notification.py` |
| `patterns_climb` | `backend/app/services/stage1_keeper_snapshot.py` |
| `proofs` | `indexer/src/api.ts` |
| `reconciliation_log` | `indexer/src/reconciliation.ts` |
| `ride_economic_plans` | `backend/app/services/stage1_keeper_snapshot.py` |
| `rides` | `indexer/src/api.ts` |
| `settlement_clock_program_lineage` | `indexer/src/api.ts` |
| `users` | `indexer/src/api.ts` |

## Canonical additions in this stack

Every relation below is absent from the snapshot and created by its stated canonical migration. Keeper consumers are `backend/app/services/stage1_keeper_store.py` and `stage1_keeper_payout.py`; boundary consumers are `backend/app/services/stage1_boundary.py` and `indexer/src/stage1*.ts`. Erasure and maintenance tables also have SQL function/trigger consumers.

| Relation | Source in `backend/sql/` |
|---|---|
| `balance_operations` | `172_balance_operations.sql` |
| `indexed_stage1_assets` | `171_stage1_indexer.sql` |
| `indexed_stage1_boost_hills` | `171_stage1_indexer.sql` |
| `indexed_stage1_boosts` | `171_stage1_indexer.sql` |
| `indexed_stage1_cash` | `171_stage1_indexer.sql` |
| `indexed_stage1_cities` | `171_stage1_indexer.sql` |
| `indexed_stage1_claim_sets` | `171_stage1_indexer.sql` |
| `indexed_stage1_cursors` | `171_stage1_indexer.sql` |
| `indexed_stage1_dung_claim_sets` | `171_stage1_indexer.sql` |
| `indexed_stage1_dung_mints` | `171_stage1_indexer.sql` |
| `indexed_stage1_dung_state` | `171_stage1_indexer.sql` |
| `indexed_stage1_events` | `171_stage1_indexer.sql` |
| `indexed_stage1_funding` | `171_stage1_indexer.sql` |
| `indexed_stage1_hills` | `171_stage1_indexer.sql` |
| `indexed_stage1_lots` | `171_stage1_indexer.sql` |
| `indexed_stage1_pauses` | `171_stage1_indexer.sql` |
| `indexed_stage1_payouts` | `171_stage1_indexer.sql` |
| `indexed_stage1_recipients` | `171_stage1_indexer.sql` |
| `indexed_stage1_test_pools` | `171_stage1_indexer.sql` |
| `indexed_stage1_withdrawals` | `171_stage1_indexer.sql` |
| `program_version_observations` | `169_stage1_program_version_window.sql` |
| `stage1_boundary_alerts` | `171_stage1_indexer.sql` |
| `stage1_boundary_checks` | `171_stage1_indexer.sql` |
| `stage1_boundary_exports` | `171_stage1_indexer.sql` |
| `stage1_boundary_failures` | `171_stage1_indexer.sql` |
| `stage1_boundary_redactions` | `171_stage1_indexer.sql` |
| `stage1_boundary_tasks` | `171_stage1_indexer.sql` |
| `stage1_boundary_witnesses` | `171_stage1_indexer.sql` |
| `stage1_indexer_activation` | `171_stage1_indexer.sql` |
| `stage1_indexer_alerts` | `171_stage1_indexer.sql` |
| `stage1_indexer_checkpoints` | `171_stage1_indexer.sql` |
| `stage1_indexer_dependencies` | `171_stage1_indexer.sql` |
| `stage1_indexer_hill_coverage` | `171_stage1_indexer.sql` |
| `stage1_indexer_links` | `171_stage1_indexer.sql` |
| `stage1_indexer_maintenance` | `171_stage1_indexer.sql` |
| `stage1_indexer_namespace` | `171_stage1_indexer.sql` |
| `stage1_indexer_network` | `171_stage1_indexer.sql` |
| `stage1_indexer_pending` | `171_stage1_indexer.sql` |
| `stage1_indexer_stream` | `171_stage1_indexer.sql` |
| `stage1_indexer_transaction_hills` | `171_stage1_indexer.sql` |
| `stage1_indexer_transactions` | `171_stage1_indexer.sql` |
| `stage1_keeper_alerts` | `170_stage1_keeper.sql` |
| `stage1_keeper_attempts` | `170_stage1_keeper.sql` |
| `stage1_keeper_boundaries` | `170_stage1_keeper.sql` |
| `stage1_keeper_erasure_exports` | `170_stage1_keeper.sql` |
| `stage1_keeper_erasure_sessions` | `170_stage1_keeper.sql` |
| `stage1_keeper_jobs` | `170_stage1_keeper.sql` |
| `stage1_keeper_lookup_tables` | `170_stage1_keeper.sql` |
| `stage1_keeper_measurements` | `170_stage1_keeper.sql` |
| `stage1_keeper_network` | `170_stage1_keeper.sql` |
| `stage1_keeper_payout_actions` | `170_stage1_keeper.sql` |
| `stage1_keeper_proofs` | `170_stage1_keeper.sql` |
| `stage1_keeper_reconciliations` | `170_stage1_keeper.sql` |
| `stage1_keeper_scopes` | `170_stage1_keeper.sql` |
| `stage1_keeper_token_accounts` | `170_stage1_keeper.sql` |
| `stage1_source_redactions` | `171_stage1_indexer.sql` |
| `stage1_wallet_rows` | `171_stage1_indexer.sql` |

The 16 account tables created by the dynamic loop in 171 match `STAGE1_TABLES` in `indexer/src/stage1.ts`. `stage1_boundary_banks` is a function. Balance consumers are `stage1_actions.py`, `stage1_operation_status.py` and `balance_transaction_coordinator.py`.

## Inherited deletion dependencies

Migration 170 delegates to the existing 152 account-deletion workflow. Its residue, actor and foreign-key scans discover relations through the catalog, potentially across public relations; the committed inventory lists all 196 supplied names. Their common consumer is `backend/sql/152_account_deletion_lifecycle.sql`; the inventory records presence for every name. Absent legacy `gps_points` and `export_requests` paths are guarded by `to_regclass` and remain optional. Private tables `br_private.account_deletion_keyring` and `br_private.account_deletion_identity_policy` are created by canonical 152; the public-only snapshot does not independently verify their production presence.

## Balance mirror reconciliation

Canonical 172 preserves the complete columns, checks, indexes, RLS and comments of `20260611_119_balance_operations.sql`. That historical mirror stays unchanged. It has no explicit grants; the repair preserves default ACL behavior and adds no client policy. A new byte-identical 172 mirror precedes 173/174 in CLI order and safely reapplies where the historical mirror already created the table. Canonical 119 remains the settlement-clock migration.

Notifications move from 172 to 173; the pending-intent index moves from 173 to 174, including mirrors and test references. Creation uses a five-second lock timeout and ten-second statement timeout. It also attaches the existing 152 account-deletion write fence if absent: 152 could not attach it to a table that did not exist. No Balance rollout setting changes.

## Whole-stack schema rehearsal (Phase 3.3)

The supplied public schema export and migration ledger now provide the missing pre-102 baseline. On local PostgreSQL **17.10**, the actual deployment runner applied exactly **169–174**, preserved all 156 historical ledger rows, and made no new baseline entries. A second run applied nothing and left the complete ledger unchanged. The actual invariant checker passed: **10 critical migrations ledgered; 34 schema requirements present**. This is local schema-only evidence, not a production deployment or a test with production data.

Validation: the migration-namespace and inherited-routing failures passed after correction; missing exports produced a clean test skip. The full backend suite passed under `LC_ALL=en_US.UTF-8`: **3,570 passed, 21 skipped**, with the export test enabled, a disposable local keeper database, and the required indexer build. Independent review found no remaining material defects. A startup-failure probe also confirmed owned-server shutdown and directory cleanup. No production access, devnet transactions, program changes or merge to main occurred.

The exports remain outside Git. Input fingerprints for this rehearsal:

| Input | SHA-256 |
|---|---|
| `prod_schema_public.sql` | `0f640d3e0a6ea60abd9d1a0f1ab80d2a36ff91b0dd7e7054ff114ba4c04ba0db` |
| `prod_migration_ledger.json` | `e717f9791bc9524bbd22c6b6d4aab1f2b51af275a9efa73a9535e9fc10670161` |

The schema was exported from PostgreSQL 17.6. The ledger contains 156 rows through 168, including 90 baseline rows. Although its header lists seven columns, each supplied row contains only `filename`, `checksum`, and `baseline`. Those fields are seeded exactly. Absent historical `applied_at`, `execution_ms`, `applied_by`, and `host` use the restored table's local defaults; they are not recovered production history. All seven resulting fields are compared before/after application and after the no-op rerun. Historical checksums match canonical SQL; migration 153 is already ledgered and its approval gate is not bypassed.

### Local prerequisites and stubs

| Object | Local treatment |
|---|---|
| `anon`, `authenticated` | Empty `NOLOGIN` roles for exported/migration role references |
| `service_role` | Empty `NOLOGIN BYPASSRLS` role |
| `public` | Created by the supplied dump; every original dump statement is retained |
| `extensions` | Empty platform namespace created locally |
| PostGIS 3.6.4, pg_trgm 1.6 | Real extensions in `public`, required by exported geometry/index definitions |
| btree_gist 1.7 | Real extension in `extensions`, as in canonical 164; required by UUID GiST indexes |
| pgcrypto 1.3 | Real extension in `extensions`, the default platform location in canonical 152 |
| `auth.*` functions | None required or stubbed |

The dump excludes owners, ACLs, default grants and non-public schemas. No private account-deletion tables, keys or helpers are fabricated. Existing function bodies can reference omitted private objects; restoring them does not prove those paths execute. This rehearsal therefore does not certify production permissions, private-schema behavior, populated-table performance, or rider/chain outcomes. The earlier focused tests separately cover service/client privileges and the real 152 late-created-table deletion fence.

### Migration correction, timing and locks

The first stack application failed at 171 because `public.digest` did not exist. All six SHA-256 calls in **171 and its byte-identical mirror** now use `pg_catalog.sha256`, following canonical 143. Byte inputs, hashes and surrounding behavior are unchanged; no public pgcrypto shim was added. No other migration needed changing in Phase 3.3.

| Canonical migration | Local runner `execution_ms` |
|---|---:|
| 169 program version window | 2 |
| 170 keeper | 24 |
| 171 indexer | 57 |
| 172 Balance operations | 5 |
| 173 notifications | 0 |
| 174 pending intents | 0 |

These are the runner's integer-millisecond measurements before ledger insertion/commit, with normal fsync enabled and no application rows. Zero means below its one-millisecond reporting precision. They are not production duration estimates.

A separate fresh restore uses a DDL event trigger to capture actual transaction-held relation locks, including newly created relation OIDs. It does not alter migration SQL or add observer overhead to the timed run. On `balance_operations`, 172 took **AccessExclusiveLock, ShareLock, ShareRowExclusiveLock and ShareUpdateExclusiveLock**; its created indexes took AccessExclusiveLock. Migration 174 took **ShareLock** on the table and AccessExclusiveLock on its new index. The table ShareLock blocks ordinary writes while allowing ordinary reads; AccessExclusiveLock conflicts with reads and writes. In this baseline 172 creates a new, empty table. Both migrations retain 5-second lock-wait and 10-second per-statement limits. Populated-table or concurrent-writer behavior is not inferred from the empty restore; a concurrent-index prebuild remains the documented fallback for 174 if needed, requiring separate definition and `indisvalid` verification before retrying. That fallback was not exercised in this rehearsal.

### Run locally

Use a backend Python environment with its requirements installed and local PostgreSQL 17 binaries with PostGIS, pg_trgm, btree_gist and pgcrypto available. The harness owns a temporary cluster with TCP disabled and a private Unix socket. It accepts file paths, never a database URL; inherited `PG*` and `DATABASE_URL` settings are removed in its worker. The regression also proves hostile routing settings cannot redirect it. Shutdown precedes directory removal, including startup failures; an unconfirmed shutdown retains the owned directory.

From `backend/`:

```sh
python scripts/rehearse_stage1_migrations.py \
  --schema-file /absolute/path/outside/git/prod_schema_public.sql \
  --ledger-file /absolute/path/outside/git/prod_migration_ledger.json
```

Use `--postgres-bin /absolute/path/to/postgresql17/bin` if automatic discovery does not find the binaries. The harness invokes `scripts/apply_sql_migrations.py --sql-dir sql --baseline-through 101 --reload-postgrest` against canonical SQL, as `scripts/deploy-backend-release.sh` does, then repeats the runner and invokes `scripts/check_schema_invariants.py`. JSON output records input hashes, supplied/absent ledger fields, local prerequisites, timings, locks and assertions. No PostgREST server is started; the runner issues its normal reload notification locally.

```sh
LC_ALL=en_US.UTF-8 \
STAGE1_PROD_SCHEMA_FILE=/absolute/path/outside/git/prod_schema_public.sql \
STAGE1_PROD_LEDGER_FILE=/absolute/path/outside/git/prod_migration_ledger.json \
python -m pytest tests/sql/test_stage1_production_migrations.py -q
```

The committed test skips when either export path is unset or missing. It fails on an invalid supplied export or unavailable required local tooling. The CLI requires both files. Never commit either export, including with `git add -f`; the exact basenames are also ignored.

### Refresh before release

An authorized operator must supply fresh exports from the same database during a window without schema/migration changes. This harness does not fetch them or connect to production. Request:

1. A schema-only dump using `pg_dump --schema-only --no-owner --no-privileges --schema=public`, with a PostgreSQL 17 client; record source server and extension versions/namespaces separately.
2. The migration ledger as named-column JSON, retaining all seven fields when available. The read-only export query is:

   ```sql
   SELECT jsonb_build_object(
     'columns', ARRAY['filename','checksum','applied_at','execution_ms','applied_by','host','baseline'],
     'rows', jsonb_agg(to_jsonb(m) ORDER BY m.filename)
   )
   FROM (
     SELECT filename, checksum, applied_at, execution_ms, applied_by, host, baseline
     FROM public.br_sql_migrations
   ) AS m;
   ```

3. Store the two files outside the checkout, retain their hashes, and rerun the harness against the exact proposed release SQL. Its expected additions remain 169–174; a ledger already containing these migrations or a different pending stack must fail and be reconciled explicitly.

A refreshed successful rehearsal is a release input. It does not authorize deployment, enable Stage 1, or replace live permissions, migration-lock, provider or rider checks.

## Phase 3.4: terminal Stage 1 operations and account deletion

Canonical 172 and its identical mirror now keep terminal `stage1_` operations out of the legacy Balance deletion blockers. `confirmed`, `finalized`, `failed` and `expired` are terminal regardless of projection status. `prepared` and `submitted` remain retryable processing blockers until their durable confirmation status changes; row age and metadata timestamps cannot declare chain expiry. Prefix matching is literal (`left(action_type, 7) = 'stage1_'`). Ordinary Balance rows retain the exact 152 checks and counts, including in mixed histories.

The guarded function patch reaches the real 152 body, named `br_account_deletion_db_blockers_pre_threshold` after 154, beneath the 155/170/171 wrappers. Focused older installations fall back to its pre-keeper or original name. The wrappers, keeper erasure rules, function identity, owner, ACL, security-definer setting and empty search path are preserved. The new processing blocker is appended after the legacy policy fallback, so it cannot suppress a Balance support blocker. Unexpected source drift aborts the migration. The existing 5-second lock timeout and 10-second statement timeout still cover 172.

A blocker-only correction failed the real finalizer's personal-residue check. Following [the ratified anonymous-retention contract](../PROTOCOL_TRUTHS.md#101-account-deletion-and-retained-authority) and 152's token-transaction precedent, 172 also patches the original finalizer. After its lease, storage, wallet fence and blocker checks, terminal Stage 1 operation records move to the newly created anonymous actor. Action, asset, amount, status and history dates remain private under existing table permissions. Record/idempotency identifiers are replaced, and personal metadata, signature, address, failure and reference fields are cleared. Other riders, Balance rows, pending operations and the final residue check are unchanged; no deletion gate is enabled.

Local PostgreSQL evidence: the 23 new real-152 regressions first failed, then passed; the full focused deletion/migration suite passed 97 cases. Six existing keeper lifecycle cases were expanded with terminal Stage 1 history: all six reproduced the blocker against committed pre-fix 172, then passed with this patch, including verified completion, retained anonymous facts, unchanged wrapper permissions, and late-blocker refusal before anonymization. Independent review found no remaining material defects. The full backend suite under `LC_ALL=en_US.UTF-8` passed **3,593 tests, 21 skipped**, including the export-backed rehearsal.

The same external exports were rerun through the Phase 3.3 harness: 169–174 apply, all historical rows remain unchanged, rerun is a clean no-op, and the actual invariant checker passes 10 critical migrations / 34 schema requirements. Runner timings for 169–174 were **1/20/58/8/0/0 ms**. The 172/174 relation-lock modes remain those listed above. These remain local empty-schema observations; no production access or deployment occurred, and neither export is committed.
