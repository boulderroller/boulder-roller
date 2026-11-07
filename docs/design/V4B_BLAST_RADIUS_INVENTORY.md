# V4-B Blast Radius Inventory — IDL Consumer Map for `0uv8` Cutover

**Status:** RESEARCH snapshot (2026-04-17); LRWD, 29rm, and 8346 safety addenda applied 2026-07-14.
**Audience:** Protocol agent executing `0uv8` (Climb-first surface split + IDL hard-rename), plus `wdvr.8` cleanup.
**Scope:** Map every IDL consumer across the stack so the cutover order is knowable and reversible.
**Parent docs:**
- [PROTOCOL_TRUTHS §11 Naming Conventions](../PROTOCOL_TRUTHS.md)
- [Protocol Agent Return Brief](./PROTOCOL_AGENT_RETURN_BRIEF.md) (D1 locked: `Climb { vault: Option<Pubkey> }`)
- [WWPTD Epic Portfolio](./WWPTD_EPIC_PORTFOLIO_2026-04-17.md)

---

## TL;DR

- The only real IDL consumers are: **backend (`solana_direct.py` + `tx_builder.py` + `leaderboard_sync_service.py`)** and **the TypeScript indexer**. Plus the four Anchor test suites in-repo.
- Portal, BoulderScan, and mobile do NOT read IDL types directly. Portal just knows the program ID. Mobile's `RideAttestationView` is a locally-defined interface, not an IDL import.
- Backend reads account state two ways: via `anchorpy.AccountsCoder.parse(...)` (IDL-driven) and via hand-rolled `struct.unpack(...)` byte parsers that duplicate the IDL layout. Both touchpoints break when fields move.
- The indexer is fully IDL-driven — `getAccountTypeNames()` returns `idl.accounts.map(a => a.name)`, and the writer dispatch table switches on that string. Renames require editing `indexer/src/writers/index.ts`.
- Live economic path today is `record_ride` ->
  `record_climb_completion_v2` -> `credit_cal`. Both
  `record_vault_completion` and tribute-unbound V1
  `record_climb_completion` remain in the ABI but fail closed. V1 receipt bytes
  remain readable as identity-only history. V4-B must preserve the V2 exact
  tribute hash/account contract even if it renames the surrounding Climb/Vault
  surface.

Consumer surfaces found: **10** (solana_direct.py, tx_builder.py, leaderboard_sync_service.py, projection_writer.py, ride_processor.py, ride_attester.py, ride_executor.py (skeleton), epoch_processor.py, vaults.py route, indexer). Plus 3 active Anchor test specs and 3 backend smoke scripts.

---

## 1. IDL surface inventory

Source: `protocol/anchor/programs/boulder_rollers/src/lib.rs` and the committed IDL at `protocol/anchor/idl/boulder_rollers.json` (identical to `target/idl/boulder_rollers.json`, `version: 0.1.0`).

### 1.1 Instructions (41 in IDL; lib.rs declares 4 additional Merkle-path Accounts structs without handlers — dead per V4-A)

| Wire name (IDL camelCase) | Rust fn | Args | TRUTHS-vocabulary status |
|---|---|---|---|
| `initializeUser` | `initialize_user` | — | neutral |
| `adminInitializeUser` | `admin_initialize_user` | — | neutral |
| `initializeProgramConfig` | `initialize_program_config` | `backendAuthority` | neutral |
| `updateProgramConfig` | `update_program_config` | `newAdmin, newBackend` | neutral |
| `migrateProgramConfig` | `migrate_program_config` | — | neutral |
| `migrateProgramConfigV3` | `migrate_program_config_v3` | — | neutral |
| `configureMints` | `configure_mints` | `calMint, dungMint` | neutral |
| `configureTreasuryAccounts` | `configure_treasury_accounts` | `polTokenAccount, treasuryTokenAccount` | neutral |
| `initializeVaultCalEscrow` | `initialize_vault_cal_escrow` | — | Vault-scoped (OK per D1 — Vault is the economic attachment) |
| `adminCreditCal` | `admin_credit_cal` | `amount` | neutral |
| `adminMintCal` | `admin_mint_cal` | `amount` | neutral |
| `recordRide` | `record_ride` | `rideHash, attestationCommitment, parserVersion, sourceKind, completedAt, startedAt, totalTss, totalDistanceM, totalVertM, calEarned, climbsCrossed` | ACTIVE attestation instruction |
| `creditCal` | `credit_cal` | `amount` | ACTIVE (attestation-tied CAL mint) |
| `recordClimbCompletion` | `record_climb_completion` | `completionTimeS, calTribute` | **ACTIVE / CANONICAL** for 0uv8 |
| `initializeBeetleCard` | `initialize_beetle_card` | `cardType, scopeId` | neutral |
| `incrementBeetleScore` | `increment_beetle_score` | `deltaScore` | neutral |
| `getBeetleCardStats` | `get_beetle_card_stats` | — | neutral (view-like) |
| `upgradeBeetleCard` | `upgrade_beetle_card` | — | neutral |
| `getUpgradeCost` | `get_upgrade_cost` | — | neutral |
| `initializeVaultCounter` | `initialize_vault_counter` | — | neutral |
| `createVault` | `create_vault` | `signature, name, vertM, distanceM, avgGradientPct` | Vault-scoped (OK per D1) |
| `adminCreateVault` | `admin_create_vault` | `signature, name, vertM, distanceM, avgGradientPct, calDeposited` | Vault-scoped (OK) |
| `createVaultWithUsdc` | `create_vault_with_usdc` | same as createVault | Vault-scoped (OK) |
| `recordVaultCompletion` | `record_vault_completion` | `completionTimeS, calTribute, completedAt, attestationHash` | **LEGACY ABI / FAILS CLOSED after LRWD / TO RETIRE under 0uv8** |
| `initializeVaultLpMint` | `initialize_vault_lp_mint` | — | Vault-scoped (OK) |
| `stakeCalInVault` | `stake_cal_in_vault` | `amount` | Vault-scoped (OK; D1 says Vault is attached to Climb, so staking-in-vault is correct) |
| `unstakeCalFromVault` | `unstake_cal_from_vault` | `lpAmount` | Vault-scoped (OK) |
| `harvestRewards` | `harvest_rewards` | — | neutral |
| `updateVaultMetadata` | `update_vault_metadata` | `name, avatarIpfs, slogan` | Vault-scoped (OK) |
| `initializeDungMintState` | `initialize_dung_mint_state` | — | neutral |
| `applyHalving` | `apply_halving` | — | neutral |
| `distributeEpochRewards` | `distribute_epoch_rewards` | `settlementWeek, config: DistributionConfig` | **Uses `epoch` in name** but `settlementWeek` in arg — partial drift per PROTOCOL_TRUTHS §12.3 (demote `epoch`) |
| `electLocalLegend` | `elect_local_legend` | `winnerCompletions, runnerUp, runnerUpCompletions` | OK |
| `resignLocalLegend` | `resign_local_legend` | — | OK |
| `adminSeedVaultCompletionSummary` | `admin_seed_vault_completion_summary` | `totalCompletions, bestTimeS, bestTimeHolder` | Legacy seeding |
| `adminReplaceVaultLeaderboard` | `admin_replace_vault_leaderboard` | `entries` | Legacy seeding |
| `adminActivateVault` | `admin_activate_vault` | — | Legacy seeding |
| `adminOverrideOpenSettlementWeek` | `admin_override_open_settlement_week` | `settlementWeek` | Admin override |
| `adminSeedPendingRewards` | `admin_seed_pending_rewards` | `settlementWeek, pendingRewards` | Admin override |
| `adminOverrideStakeEligibility` | `admin_override_stake_eligibility` | `eligibleFromEpoch` | uses `epoch` naming |
| `adminBackfillVaultActivation` | `admin_backfill_vault_activation` | `vaultId` | Admin migration |

**Dead instruction shells (Accounts-struct-only, no `pub fn` handler):**
`SubmitAllocationBatch`, `ClaimUserCal`, `ClaimAndConvertVaultAlloc`, `SetAllocationSubmitter` — `lib.rs:4651`, `4697`, `4720`, `4773`. Merkle batch path, confirmed dead per V4-A direct-credit design. `merkle_proof.py` is also labeled DEAD. Retire under `wdvr.8`.

### 1.2 Accounts (15 in IDL)

| Name | PDA seed | Key fields (elided) | TRUTHS status |
|---|---|---|---|
| `UserState` | `[USER_SEED, owner]` | `owner, legacy_cal_*, total_rides, total_tss, bio_score, bump` | Legacy; coexists with RiderSoul per §12.4 |
| `RiderSoul` | `[RIDER_SOUL_SEED, rider]` | `rider, created_at, total_rides, total_tss, total_distance_m, total_vert_m, total_cal_earned, archetype, bio_score, climb_card, steady_card, explorer_card` | Primary identity going forward |
| `RideAttestation` | `[RIDE_ATTESTATION_SEED, rider, ride_hash]` | `rider, ride_hash, attestation_commitment, parser_version, source_kind, completed_at, started_at, total_tss, total_distance_m, total_vert_m, cal_earned, climbs_crossed, attester, settled_at, settled_slot, economic_epoch, finalized` | Canonical per §2.3 |
| `CalMintReceipt` | `[CAL_MINT_RECEIPT_SEED, ride_attestation, rider]` | `ride_attestation, rider, amount` | Idempotency |
| `ClimbCompletionReceipt` | `[CLIMB_COMPLETION_RECEIPT_SEED, ride_attestation, vault]` | `ride_attestation, vault` | Idempotency. **Field `vault` — D1 question: does Climb-as-parent want this renamed `climb` or stay `vault`?** |
| `VaultCounter` | — | `count, bump` | Legacy naming; Climb-counter would be TRUTHS-pure. |
| `DungMintState` | `[DUNG_MINT_STATE_SEED]` | 11 fields incl. caps + emission | neutral |
| `ProgramConfig` | `[PROGRAM_CONFIG_SEED]` | 12 fields incl. authorities + mints | neutral |
| `AllocationBatch` | `[ALLOC_BATCH_SEED, batch_id]` | Merkle batch | **DEAD path** — retire under `wdvr.8` |
| `UserCalClaim` | `[USER_CAL_CLAIM_SEED, batch_id, user]` | Merkle claim | DEAD |
| `VaultAllocClaim` | `[VAULT_ALLOC_CLAIM_SEED, batch_id, vault_id]` | Merkle claim | DEAD |
| `Vault` | `[VAULT_SEED, id]` | 30+ fields including signature, KOM state, economics, per-bucket carry | **Primary rename target under D1 — should become `Climb { vault: Option<Pubkey> }` per D1, with today's Vault economic fields factored into a child Vault account.** |
| `VaultCompletion` | `[VAULT_COMPLETION_SEED, user, vault_id]` | `user, vault_id, completions, best_time_s, last_completed_at, total_cal_tributed` | Per-user completion record. Rename target: `ClimbCompletion`. |
| `VaultStake` | `[VAULT_STAKE_SEED, user, vault_id]` | `user, vault_id, cal_staked, lp_tokens, staked_at, eligible_from_epoch, rewards_earned, ...` | Stays `VaultStake` per D1 (Vault is the economic attachment). |
| `VaultLeaderboard` | `[VAULT_LEADERBOARD_SEED, vault_id]` | `vault_id, entries: Vec<LeaderEntry>, last_updated` | Rename target: `ClimbLeaderboard` or `RecordBoard` (PROTOCOL_TRUTHS §11: "Record Board"). |
| `LocalLegend` | `[LOCAL_LEGEND_SEED, vault_id]` | holder, election_period, term_start_epoch, term_end_epoch, completions_at_election, runner_up, runner_up_completions, total_earned, is_active | Keyed by `vault_id` today; under D1, legend is attached to the Vault (the economic wrapper), so keying may stay. **Open question.** |
| `VaultActivation` | `[VAULT_ACTIVATION_SEED, vault_id]` | `vault_id, is_active, seed_completions_written, leaderboard_seeded, created_at, activated_at` | Legacy activation; may collapse under V4-B. |
| `BeetleCard` | `[BEETLE_CARD_SEED, owner, card_type, scope_id]` | `owner, card_type: CardType{Climb|Steady|Explorer}, scope_id, score, level, patterns_scored, last_updated, created_at` | Per §11, Beetle Score naming already aligned. |

### 1.3 Events (31 in IDL)

| Event | Payload fields (elided) | TRUTHS status |
|---|---|---|
| `ProgramConfigInitialized` | admin, backend, timestamp | neutral |
| `ProgramConfigUpdated` | admin, backend, timestamp | neutral |
| `RideAttestationRecorded` | rider, ride_hash, parser_version, economic_epoch, cal_earned, completed_at, timestamp | Canonical |
| `CalCredited` | rider, ride_attestation, amount, timestamp | Canonical |
| `ClimbCompleted` | vault_id, ride_attestation, rider, time_s, cal_tributed, is_new_kom, completed_at, timestamp | **CANONICAL for 0uv8.** Still carries `vault_id` — D1 question: rename to `climb_id`? |
| `VaultCompleted` | vault_id, user, time_s, cal_tributed, is_new_kom, timestamp | **LEGACY — emitted in parallel with ClimbCompleted today**. Retire under 0uv8 Step N+k. |
| `VaultCreated` | id, minter, signature_hash, vert_m, payment_method, timestamp | Vault-scoped (OK per D1). |
| `VaultMetadataUpdated` | vault_id, updated_by, timestamp | OK |
| `LocalLegendElected` | vault_id, winner, winner_completions, runner_up, ... | OK |
| `LocalLegendResigned` | vault_id, holder, timestamp | OK |
| `HalvingApplied` | new_rate_bps, epoch, timestamp | neutral |
| `DungMinted` | amount, allocation, recipient, total_minted, timestamp | neutral |
| `EpochRewardsDistributed` | vault_id, epoch, total_distributed, leaderboard_distributed, staker_distributed, local_legend_distributed, pol_distributed, protocol_distributed, staker_count, unlock_pct, locked_staker_amount, timestamp | **TRUTHS drift**: name uses `Epoch`, payload has `epoch` but semantics are Settlement Week. `epoch` demotion per §12.3. Rename candidate: `SettlementWeekFinalized` with `settlement_week` field. |
| `CalStaked` | vault_id, staker, amount, lp_minted, timestamp | OK |
| `CalUnstaked` | vault_id, staker, cal_returned, lp_burned, timestamp | OK |
| `UnstakeWithFee` | user, vault_id, cal_returned, fee_amount, timestamp | OK |
| `RewardsHarvested` | vault_id, staker, dung_earned, harvest_fee, dung_received, timestamp | OK |
| `StakerAllocation` | vault_id, epoch, staker, amount, lp_tokens, eligible_from_epoch, timestamp | `epoch` drift |
| `ProgramConfigMigrated` | admin, new_size, timestamp | neutral |
| `MintsConfigured` | cal_mint, dung_mint, cal_mint_auth_bump, dung_mint_auth_bump, timestamp | neutral |
| `TreasuryAccountsConfigured` | pol_token_account, treasury_token_account, timestamp | neutral |
| `AllocationSubmitterSet` | submitter, timestamp | DEAD path (Merkle) |
| `AllocationBatchSubmitted` | batch_id, root, leaf_count, tree_depth, epoch, submitter, timestamp | DEAD |
| `UserCalClaimed` | batch_id, user, amount, ride_count, epoch, timestamp | DEAD |
| `VaultAllocClaimed` | batch_id, vault_id, cal_amount, dung_converted, epoch, timestamp | DEAD |
| `VaultActivated` | vault_id, seed_completions_written, leaderboard_seeded, timestamp | Legacy seeding |
| `BeetleCardCreated` | owner, card_type, scope_id, timestamp | OK |
| `BeetleScoreIncremented` | owner, card_type, scope_id, delta_score, new_score, new_level, leveled_up, timestamp | OK |
| `BeetleCardStats` | owner, card_type, scope_id, score, level, patterns_scored, created_at, last_updated | OK |
| `BeetleCardUpgraded` | owner, card_type, scope_id, old_level, new_level, dung_burned, timestamp | OK |
| `BeetleUpgradeCost` | owner, card_type, current_level, upgrade_cost, can_upgrade | OK |

### 1.4 Error enum variants (61 in IDL)

Stable public surface; renames not required unless semantic drift. Variants referencing `epoch`: `AlreadyDistributed`, `EpochNotEnded`, `InvalidEpoch`, `EpochAlreadyDistributed`. Candidate demote under §12.3. `SettlementWeekNotFinalizable` and `SettlementWeekOutOfSync` remain live. `RideOutsideSettlementWindow` is a deprecated ABI slot after LRWD: retain its ordinal/message in generated IDLs, but production instructions must not emit it. Variant `InvalidName` carries msg `"Invalid segment name"` — message drift (rename msg only, variant name OK).

---

## 2. Backend consumers — `backend/app/`

### 2.1 `backend/app/solana_direct.py` — **PRIMARY WIRE LAYER**

Single source of all Anchor tx-building Python-side. `anchorpy.AccountsCoder` loaded once from the committed IDL (`solana_direct.py:155-167`).

| File:line | Depends on | Breakage | Required change |
|---|---|---|---|
| `solana_direct.py:30-31` | `anchorpy.Idl.from_json` | IDL JSON shape | rebuild IDL after rename; AccountsCoder re-initializes |
| `solana_direct.py:155-167` | `idl/boulder_rollers.json` path | Renamed account types | Name-only; accessor map regenerates |
| `solana_direct.py:222-282` | account name `"Vault"` + field names (`komHolder`, `calTributeAccumulated`, `carryRecordRoyalty`, etc.) | Struct shape + camelCase name change | **Hard-edit**: rename `"Vault"` → `"Climb"`; add `vault: Option<Pubkey>` field read; handle case where `vault` is None; most economic fields move to child Vault account |
| `solana_direct.py:285-307` | account name `"VaultStake"` + fields | Name only (D1: Stake stays on Vault) | No-op if D1 keeps `VaultStake` |
| `solana_direct.py:310-339` | account name `"ProgramConfig"` | no change | no-op |
| `solana_direct.py:342-477` | Legacy byte-layout fallback (545-byte pre-V3 Vault) | Struct shape | Retire entirely under `wdvr.8` — already obsolete |
| `solana_direct.py:479, 486, 493` | `AllocationBatch`, `UserCalClaim`, `VaultAllocClaim` PDA seeds | DEAD | Retire |
| `solana_direct.py:1212-1358` | Vault seeds constants (`VAULT_SEED`, `CLIMB_COMPLETION_RECEIPT_SEED`, etc.) | Seed bytes may change | If seeds change, old PDAs are unreachable — **one-way door** |
| `solana_direct.py:1299-1352` | RiderSoul, RideAttestation, CalMintReceipt, ClimbCompletionReceipt PDA derivation | no change under D1 | no-op |
| Historical `solana_direct.py:1358-1476` | `make_record_vault_completion_ix` + `send_record_vault_completion` | **Retired under `29rm`** | No executable Python client remains; delete the fail-closed Anchor ABI entry under `0uv8` |
| `solana_direct.py:1479-1547` | `admin_credit_cal` discriminator | no change | no-op |
| `solana_direct.py:1660-1754` | `credit_cal` discriminator + accounts | no change | no-op |
| `solana_direct.py:1756-1844` | **`make_record_climb_completion_ix` + `send_record_climb_completion`** | Account order for `RecordClimbCompletion` | **CANONICAL going forward**; account order must track any `Vault` → `Climb` PDA rename |
| `solana_direct.py:2099-2197` | stake/unstake/harvest instruction builders | no change under D1 | no-op |
| `solana_direct.py:2680-3101` | `make_create_vault_ix`, `make_admin_create_vault_ix`, `make_create_vault_with_usdc_ix`, and sends | Account struct for `CreateVault` likely adds a Climb PDA account under D1 | **Schema shape change**: now a Climb account is created alongside Vault, OR Vault creation implicitly creates the parent Climb first |
| `solana_direct.py:3245-3305` | `VaultLeaderboardEntry`, `LocalLegendData` hand-rolled byte parsers | Struct shape | **Hand-edit**: mirror new layouts if leaderboard account is renamed |
| `solana_direct.py:3329-3580` | `distribute_epoch_rewards` discriminator + accounts | Rename candidate | Rename to `finalize_settlement_week` (per PROTOCOL_TRUTHS §12.3) — compat alias for one release |

### 2.2 `backend/app/services/tx_builder.py`

Builds user-signed wallet transactions. Imports directly from `solana_direct`.

| File:line | Depends on | Breakage | Required change |
|---|---|---|---|
| `tx_builder.py:52-63` | `_discriminator`, `make_create_vault_ix`, `make_stake_cal_in_vault_ix`, `make_unstake_cal_from_vault_ix` | Name only | Follows `solana_direct` renames |
| `tx_builder.py:205-261` | `build_stake_tx` → `make_stake_cal_in_vault_ix` | D1-neutral | no-op |
| `tx_builder.py:289-320` | `build_unstake_tx` → `make_unstake_cal_from_vault_ix` | D1-neutral | no-op |
| `tx_builder.py:347-389` | `build_harvest_tx` → `_discriminator("harvest_rewards")` | name | no-op |
| `tx_builder.py:423-513` | `build_create_vault_tx` → `make_create_vault_ix` | Schema shape | New account(s) if Climb is parent |
| `tx_builder.py:513-585` | `build_create_vault_with_usdc_tx` | same as above | same |

### 2.3 `backend/app/services/ride_processor.py` — **primary caller of executor flow**

| File:line | Depends on | Breakage | Required change |
|---|---|---|---|
| `ride_processor.py:53-56` | imports `send_admin_credit_cal, send_credit_cal, send_record_climb_completion, send_record_ride` | Name only | no-op |
| `ride_processor.py:451` | `send_record_ride(...)` call | no change | no-op |
| `ride_processor.py:531` | `send_credit_cal(...)` call | no change | no-op |
| `ride_processor.py:986` | docstring references `record_vault_completion` | text | housekeeping |
| `ride_processor.py:1154` | `send_record_climb_completion(...)` call | account shape may shift | update accounts list |
| `ride_processor.py:1293-1323` | internal `_record_vault_completion` method calls projector RPC | Rename to `_record_climb_completion` | housekeeping |
| `ride_processor.py:1939` | `send_admin_credit_cal(...)` | no change | no-op |

Note: `ride_processor.py` is slated for decomposition (bead `mfab.1` — B2 Role decomposition), but the executor calls move to `ride_executor.py` regardless of rename.

### 2.4 `backend/app/services/ride_attester.py`

Docstring-heavy role-separation file. Imports used by tests but not `solana_direct` executor entry points. Grep hits (`ride_attester.py:2, 13, 14, 15, 30, 68, 103, 122, 304`) are references to RideAttestation in docstrings and type-level code. No direct instruction-building. Breakage: **docstring only**.

### 2.5 `backend/app/services/ride_executor.py`

Skeleton file, 59 lines, no logic yet. Docstrings cite `send_record_ride`, `send_credit_cal`, `send_record_climb_completion`. Breakage: **docstring only**.

### 2.6 `backend/app/services/projection_writer.py`

DB projector. Does not call `solana_direct`. The historical inventory below
predates migration 128; `increment_vault_completions` was retired by
`boulderroller-v2-dyhn` so completion evidence can no longer mutate a
chain-owned indexed Vault total.

| File:line | Depends on | Breakage | Required change |
|---|---|---|---|
| `projection_writer.py:25, 38, 145-200` | DB RPC names referencing `vault_completion` | DB RPC names — not IDL | **DB migration** (separate from IDL). Rename `record_vault_completion_with_best_time` → `record_climb_completion_with_best_time` at DB layer under `wdvr.8`. |
| `projection_writer.py:219-252` | `record_vault_completion_with_best_time` Python wrapper | name | no-op until DB migration |

### 2.7 `backend/app/services/epoch_processor.py`

Calls finalization on-chain.

| File:line | Depends on | Breakage | Required change |
|---|---|---|---|
| `epoch_processor.py:18, 47, 549, 600` | `send_distribute_epoch_rewards(...)` | **Name drift** (§12.3: demote `epoch`) | Rename call site after `solana_direct` exposes compat alias |

### 2.8 `backend/app/services/leaderboard_sync_service.py`

Observational verifier only. Hand-rolled byte parser **duplicates IDL shape** for `VaultLeaderboard`.

| File:line | Depends on | Breakage | Required change |
|---|---|---|---|
| `leaderboard_sync_service.py:137-184` | `_parse_vault_leaderboard` — hand-rolled struct.unpack | Struct layout of `VaultLeaderboard` account | **Hard-edit**: mirror new account layout if VaultLeaderboard → ClimbLeaderboard/RecordBoard. File docstring already names this as the repair point (§`leaderboard_sync_service.py:48-51`). |
| `leaderboard_sync_service.py:30, 267, 429-430` | references `record_climb_completion` + `record_vault_completion` + `admin_replace_vault_leaderboard` in docstrings | text | housekeeping |

### 2.9 `backend/app/services/merkle_proof.py`

**DEAD CODE per V4-A.** Docstring already says so (header rewritten in `mfab.5`). Retire under `wdvr.8`. No live consumer.

### 2.10 `backend/app/routes/vaults.py`

| File:line | Depends on | Breakage | Required change |
|---|---|---|---|
| `vaults.py:23` | `from .. import solana_direct` | no change | no-op |
| `vaults.py:1083` | `solana_direct.send_stake_cal_in_vault(...)` | no change under D1 | no-op |
| `vaults.py:1251` | `solana_direct.send_unstake_cal_from_vault(...)` | no change | no-op |

Route already mounted on both `/vaults` (canonical under D1: Vault is economic attachment) and should NOT alias to `/climbs` — Climb resources are already split onto `routes/climbs.py` (per `mfab.5`). Confirm scope with protocol agent.

### 2.11 `backend/app/routes/admin.py`

| File:line | Depends on | Breakage | Required change |
|---|---|---|---|
| `admin.py:199` | `from ..solana_direct import get_current_epoch` | `epoch` naming (could expose `get_current_settlement_week`) | Add alias |

### 2.12 `backend/app/repositories/vault.py`

Names `VaultStakeDict`, `VaultCompletionDict`, `LocalLegendDict`, `VaultStake`, `VaultCompletion` class types. These are **domain types reflecting DB tables**, not IDL imports. Breakage is independent of IDL (DB schema migration, not IDL change). Flagged for `wdvr.8`.

### 2.13 Backend smoke scripts — `backend/scripts/`

- `smoke_full_stack.py:71, 626` → `send_admin_create_vault`
- `smoke_devnet_economics.py:57, 406` → `send_admin_create_vault`
- `seed_vaults_onchain.py:114, 136` → `send_admin_create_vault`

All three reference `send_admin_create_vault`. Breakage: **CreateVault accounts shape change** (if D1 requires creating a parent Climb). Update once `solana_direct` exposes the V4-B builder.

### 2.14 Backend tests

- `backend/tests/test_solana_direct_completion.py`
- `backend/tests/test_solana_direct_attestation.py`
- `backend/tests/test_solana_direct_credit.py`
- `backend/tests/test_onchain_completion_wiring.py`
- `backend/tests/services/test_ride_processor_preliminary_review_flow.py`
- `backend/tests/truths/test_backend_truths_gate1.py`
- `backend/tests/truths/alignment/test_protocol_truths_alignment_gate.py`

All mock `solana_direct` wire functions. Breakage: **mock symbol rename** once `send_record_vault_completion` is deprecated.

---

## 3. Indexer consumers — `indexer/src/`

The indexer is a separate Node.js service with its own IDL loader (`indexer/src/config.ts:40-77`). Fully IDL-driven.

| File:line | Depends on | Breakage | Required change |
|---|---|---|---|
| `indexer/src/config.ts:40-55` | IDL path resolution | none | no-op |
| `indexer/src/decoder.ts:1, 44-73, 79-95, 108-168` | `BorshCoder`, `BorshAccountsCoder`, `EventParser`, `getAccountTypeNames`, `getDiscriminatorMap`, `decodeAccount`, `decodeEvents` | IDL-driven; regenerates from new IDL | no-op (regenerates automatically) |
| `indexer/src/decoder.ts:10-14` | Docstring listing account names | text | housekeeping |
| `indexer/src/modes/snapshot.ts:53-107` | `getAccountTypeNames()` + `coder.accounts.decode(typeName, data)` | Name-driven | Account rename propagates automatically IF writer dispatch table is updated |
| `indexer/src/modes/replay.ts:223-250` | `decodeEvents(tx.meta.logMessages)` + event-name switch at `projectEventProjection` | Event names | **Hard-edit**: update `projectEventProjection` at `replay.ts:341` (`EpochRewardsDistributed` hardcoded); add handlers for any new event names |
| `indexer/src/modes/replay.ts:261-283` | `extractVaultId`, `extractUserPubkey` — hardcoded field names (`vaultId`, `id`, `user`, `staker`, `minter`, etc.) | Event payload shape | **Hard-edit**: rename to `extractClimbId` or extend fallback list |
| `indexer/src/writers/index.ts:41-111` | **Account name → writer dispatch (switch statement)** | Renamed account names | **Hard-edit**: every `case 'Vault':`, `case 'VaultLeaderboard':`, etc. must be updated to new IDL name. Only mechanical touchpoint. |
| `indexer/src/writers/vault.ts` | field names `calTributeAccumulated`, `carryRecordRoyalty`, etc. | Renamed fields | Follow |
| `indexer/src/writers/activation.ts` | VaultActivation fields | Possibly retired | Follow / delete |
| `indexer/src/writers/leaderboard.ts:5-15` | `VaultLeaderboard` field names (`entries[].user`, `entries[].timeS`) | Struct may rename to `ClimbLeaderboard` / `RecordBoard` | Follow |
| `indexer/src/writers/legend.ts:5-62, 93-100, 244` | LocalLegend, UserState, BeetleCard, AllocationBatch fields | field names | Follow; retire `AllocationBatch` under `wdvr.8` |
| `indexer/src/writers/stake.ts:5-53` | `VaultStake`, `VaultCompletion` fields | name + fields | Follow (rename `writeCompletion` → `writeClimbCompletion` if VaultCompletion renames) |
| `indexer/src/writers/identity.ts` | RideAttestation, RiderSoul, CalMintReceipt, ClimbCompletionReceipt | no change under D1 | no-op |
| `indexer/src/reconciliation.ts` | — | mostly DB-side | Follow table renames |
| `indexer/src/api.ts:203-218, 412` | `event_name` column + hardcoded `'EpochRewardsDistributed'` | Event rename | **Hard-edit** API filter strings |

**Critical note:** The indexer writes to `indexed_vaults`, `indexed_leaderboards`, `indexed_stakes`, `indexed_completions`, `indexed_legends`, `indexed_events`, `indexed_epoch_distributions`, etc. Table renames are a separate DB migration concern (touches `wdvr.8` / `mfab.3`) but the indexer is the only writer, so a single atomic DB+indexer deploy can coordinate.

---

## 4. Mobile consumers — `mobile/`

**No direct IDL consumers.** Grep for `@coral-xyz/anchor | BorshCoder | accountDiscriminator | boulder_rollers | VaultLeaderboard | VaultStake | LocalLegend` across `mobile/` returns:

- `mobile/src/services/wallet/mwaWallet.ts:35` → imports `@solana/web3.js` only (Pubkey / Transaction). Not Anchor.
- `mobile/src/components/RideReviewBanner.tsx:12-15` → imports local `RideAttestationView` type from `../lib/attestation`.
- `mobile/src/lib/attestation.ts:25-49` → `RideAttestationView` is a locally-defined interface, **not** an IDL type. Purely UI state.

**Breakage:** none from IDL rename. The mobile read layer (`wdvr.6`) that will eventually consume chain state does not exist yet. When it lands, it will import through the backend API, not raw IDL — per MOBILE_TRUTHS §4.

---

## 5. Portal consumers — `web/portal/src/`

**No direct IDL consumers.** Grep hits (`web/portal/src/lib/solana.ts:3, 16`) are program ID only.

Portal talks exclusively to backend FastAPI. `kaol` bead is tracking client-side vocabulary rename in 20+ portal files — all of those rename references to `/vaults` → `/climbs` endpoints and UI copy, none touch IDL shape.

**Breakage:** none from IDL rename. Portal migration is a separate bead (`kaol`) scoped to endpoint + copy.

---

## 6. BoulderScan consumers — `web/scan/src/`

**No direct IDL consumers.** Grep for `@coral-xyz/anchor | BorshCoder | accountDiscriminator | idl.` returns zero matches. BoulderScan reads chain-indexed data via backend API.

**Breakage:** none from IDL rename. UI copy may drift (separate concern).

---

## 7. Backend adapter shape for dual-IDL rollout

Design the `solana_direct.py` adapter to let Step N+1 (backend emits new instruction) overlap with Step N+2 (indexer reads both event types) without forcing a single atomic flip.

### 7.1 Current shape (V4-A)

```python
# backend/app/solana_direct.py
_BOULDER_COORDER = AccountsCoder(Idl.from_json(IDL_PATH.read_text()))
# One globally-cached coder, one IDL path.

def make_record_climb_completion_ix(...): ...
def send_record_climb_completion(...): ...
# The fail-closed legacy instruction remains in the Anchor ABI only; 29rm
# removed its executable Python builder and sender.
```

### 7.2 Proposed dual-IDL adapter interface

Pattern modeled on the preliminary-attestation handshake (schemas accept both old and new wire names transparently).

```python
# backend/app/solana_direct.py  (design, not code)

class IDLSurface:
    """Named surface — each knows its IDL, its discriminator prefixes, its coder."""
    name: str            # "v4a" | "v4b"
    idl_path: Path
    program_id: Pubkey
    coder: AccountsCoder  # lazy
    instructions: dict[str, InstructionSpec]
    accounts: dict[str, AccountSpec]
    events: dict[str, EventSpec]

_V4A = IDLSurface(name="v4a", idl_path=IDL_V4A, program_id=PROGRAM_ID_V4A, ...)
_V4B = IDLSurface(name="v4b", idl_path=IDL_V4B, program_id=PROGRAM_ID_V4B, ...)

def active_surface() -> IDLSurface:
    # Feature flag: `BOULDER_IDL_SURFACE` env var. Default: "v4a" pre-cutover, "v4b" post.
    return _V4B if _flag_v4b_active() else _V4A
```

All existing functions become dispatch wrappers:

```python
async def send_record_climb_completion(...):
    s = active_surface()
    if s.name == "v4a":
        # current code path
        ...
    else:
        # V4-B: possibly different accounts list, possibly requires a Climb PDA
        ...

# New functions — accept both wire names, route correctly:
def resolve_completion_instruction(s: IDLSurface, use_climb: bool) -> InstructionSpec:
    if use_climb and "recordClimbCompletion" in s.instructions:
        return s.instructions["recordClimbCompletion"]
    return s.instructions["recordVaultCompletion"]  # back-compat

# Account decoder accepts both names, normalizes to canonical internal shape:
def decode_climb_or_vault_account(data: bytes, pda: Pubkey) -> dict:
    """Decode either 'Vault' (V4-A) or 'Climb' (V4-B, with 'vault' child) to the same Python dict."""
    s = active_surface()
    decoded = s.coder.parse(data)
    if decoded.name in ("Vault", "Climb"):
        return _normalize_climb_fields(decoded.data, version=s.name)
    raise ValueError(f"Expected Climb/Vault, got {decoded.name}")
```

### 7.3 Zero-surface-breakage rules during flip

- `send_record_climb_completion` remains the only Python completion sender across both surfaces. Callers do not branch to the fail-closed legacy ABI.
- Account decoders return the same Python dict shape (`_normalize_climb_fields`) regardless of which IDL produced the bytes. Callers read `result["id"], result["signature_hex"], ...` blindly.
- Field-name normalization is already pattern-matched in current code via `_field(fields, "camelCase", "snake_case", default=...)` — extend it to accept `vault_id` or `climb_id` in V4-B-emitted events.
- Feature flag gates the `active_surface()` switch so rollback is an env var flip.

### 7.4 Where the preliminary-attestation-handshake pattern applies

That pattern accepts both old and new wire names at parse time. For `VaultCompleted` vs `ClimbCompleted`:

```python
# In event consumer (indexer-side mirror, if backend ingests events):
def handle_completion_event(event_name: str, data: dict):
    if event_name in ("VaultCompleted", "ClimbCompleted"):
        normalized_id = data.get("vaultId") or data.get("climbId")
        ...
```

---

## 8. Proposed cutover order

Each step leaves a working system.

### Step N — Ship V4-B IDL additively on-chain (fresh program ID)

**Artifacts:**
- New `lib.rs` with both instruction names. `record_climb_completion` is canonical; `record_vault_completion` is a fail-closed legacy ABI shell.
- Add parent `Climb { vault: Option<Pubkey>, ... }` account type per D1.
- Legacy `Vault` account kept; new `Climb` account co-exists. For existing Vaults, a migration instruction back-fills the parent Climb PDA. (If protocol agent prefers fresh start on new program ID: skip migration, just deploy fresh.)
- `record_climb_completion` emits the completion events. The fail-closed legacy instruction emits nothing.
- IDL regenerates with both account types and both events visible.
- `addresses.devnet.json` gets new program ID with comment per Return Brief: `"V4-B Climb-first, supersedes V4-A 37odBJvV..."`.

**Invariant:** old clients can still resolve the legacy wire shape, but a legacy completion transaction is rejected atomically. Behavioral compatibility is intentionally not preserved for a replayable value-bearing write.

### Step N+1 — Backend `solana_direct.py` adapter dual-surface

**Artifacts:**
- Add `IDLSurface` type + `active_surface()` as §7.2.
- `send_record_climb_completion` is the canonical code path. `29rm` removed the legacy Python builder/sender and migrated both deployment smokes.
- The fail-closed legacy instruction remains only in the Anchor ABI until the coordinated `0uv8` hard deletion.
- Feature flag `BOULDER_IDL_SURFACE=v4b` gates V4-B send path; default `v4a` keeps current shape.
- Account decoder `_decode_anchor_vault_account` adds branch to also accept `"Climb"` name; `_normalize_climb_fields` bridges field names.
- Legacy `VaultCompleted` event and `ClimbCompleted` event both understood.

**Invariant:** backend still ingests against V4-A program. Flip `BOULDER_IDL_SURFACE=v4b` + point at new program ID to migrate.

### Step N+2 — Indexer reads both event types, writes canonical tables

**Artifacts:**
- `indexer/src/writers/index.ts` switch statement: add `case 'Climb':` alongside `case 'Vault':` — both route to `writeVault` (or new `writeClimb` that subsumes it).
- `indexer/src/modes/replay.ts:261-283` `extractVaultId` renames internally to `extractClimbOrVaultId`, checks both field names.
- `indexer/src/modes/replay.ts:341` adds projection for `ClimbCompleted` alongside `VaultCompleted` (both populate same DB table).
- IDL swap via `IDL_PATH` env var. Indexer restart picks up new discriminator map automatically (per `decoder.ts:79-95`).

**Invariant:** indexer still processes V4-A transactions. When pointed at V4-B program, it processes both.

### Step N+3 — Portal + mobile consume new backend surface

**Artifacts:**
- Portal `kaol` bead lands rename: `/vaults` UI becomes `/climbs`-parented; Vault remains a visible sub-object.
- Mobile read layer (`wdvr.6`) lands on V4-B-aware backend responses; no IDL-side work on mobile.
- BoulderScan copy update (cross-reference with `wdvr.8`).

**Invariant:** UIs see TRUTHS-aligned vocabulary. Backend back-compat aliases still honored.

### Step N+4 — Retire `record_vault_completion` instruction + `VaultCompleted` event on-chain

**Artifacts:**
- Verify all callers exclusively use `send_record_climb_completion` (grep `backend/ indexer/ protocol/anchor/tests/` for `record_vault_completion`, expect zero hits outside archived / docstrings).
- Delete `record_vault_completion` instruction handler in `lib.rs`.
- Delete `VaultCompleted` event emission from `record_climb_completion`.
- **ONE-WAY DOOR** — this is the hard cutover. Past this step, old clients fail.

### Step N+5 — Retire legacy paths in backend

**Artifacts:**
- Keep `send_record_vault_completion` and `make_record_vault_completion_ix` absent from executable Python (removed under `boulderroller-v2-29rm`); retire the legacy Vault byte parser (`_decode_legacy_vault_account`) with the remaining V4-A read path.
- Drop `BOULDER_IDL_SURFACE` feature flag (always V4-B).
- Delete Merkle-path dead code: `merkle_proof.py`, `AllocationBatch`/`UserCalClaim`/`VaultAllocClaim` PDA derivation, `SubmitAllocationBatch`/`ClaimUserCal`/`ClaimAndConvertVaultAlloc` in `lib.rs`.
- Clean legacy DB tables (separate `wdvr.8` concern).

### Step N+6 — Rename backend internal types, DB RPCs, table names

**Artifacts:**
- `record_vault_completion_with_best_time` DB RPC → `record_climb_completion_with_best_time` (projection_writer.py:237).
- `indexed_vaults` DB table stays (Vault remains an attached economic object) OR becomes `indexed_climbs` depending on D1 downstream rename scope (open question — see §10).
- `VaultCompletion` Python class → `ClimbCompletion`.
- `repositories/vault.py` split or rename accordingly.

---

## 9. Risk matrix

| Consumer surface | Rollback cost | Coordination | One-way door? | Notes |
|---|---|---|---|---|
| `solana_direct.py` — wire functions | **easy** (feature flag) | solo | no | Adapter pattern makes it safe |
| `solana_direct.py` — byte layout fallback parsers (`_decode_legacy_vault_account`) | **easy** | solo | no | Already legacy — retire any time |
| `solana_direct.py` — PDA seeds | **hard** | solo | **if seeds change**, existing PDAs unreachable | **Do not change seeds unless fresh program ID** |
| `tx_builder.py` | **easy** | solo | no | Transaction builders are rebuild-per-call |
| `ride_processor.py` | **easy** | solo | no | Executor call sites |
| `leaderboard_sync_service.py` hand-rolled parser | **easy** | solo | no | Observational only; repair when layout drifts |
| `projection_writer.py` + DB RPCs | **hard** | backend | **if DB function renamed atomically** | DB migrations are rollback-expensive |
| `epoch_processor.py` | **easy** | solo | no | One call site |
| Indexer writer dispatch (`writers/index.ts`) | **easy** | indexer | no | Switch statement update |
| Indexer `replay.ts` event hardcoding | **easy** | indexer | no | Event name strings |
| Indexer DB tables (`indexed_*`) | **hard** | indexer + backend | **if renamed** | Coordinated deploy |
| Portal | **easy** | portal | no | Backend-mediated |
| BoulderScan | **easy** | scan | no | Backend-mediated |
| Mobile | **easy** (no dependency yet) | mobile | no | Read layer doesn't exist |
| Anchor tests (`protocol/anchor/tests/*.spec.ts`) | **easy** | solo | no | Update camelCase names |
| Backend smoke scripts | **easy** | solo | no | Three files, same function |
| Fresh program ID deploy | **hard** | protocol | **one-way after grace period** | Existing Vault PDAs orphaned unless migrated |
| `record_vault_completion` retirement (Step N+4) | **impossible once merged** | all | **YES** | Hard cutover — past this, old clients break |
| `VaultCompleted` event retirement (Step N+4) | **impossible once merged** | all | **YES** | Same |

---

## 10. Open questions for Tim

Decisions that aren't locked and aren't obvious. Do not pre-answer; flag only.

1. **Rename `ClimbCompleted` event's `vault_id` field → `climb_id`?** D1 says Climb is primary; `ClimbCompleted` is the canonical event; but its `vault_id` payload still points to the economic attachment. Is the event about the Climb (rename to `climb_id`, add optional `vault_id`) or the Vault (leave `vault_id`)? Affects indexer and downstream event consumers.

2. **Rename `VaultLeaderboard` account → `ClimbLeaderboard` or `RecordBoard`?** PROTOCOL_TRUTHS §11 names "Record Board" as canonical. This is a user-visible account. Rename to `RecordBoard` (matches §11 exactly) or `ClimbLeaderboard` (matches D1 pointer-direction)?

3. **Rename `distributeEpochRewards` → `finalizeSettlementWeek`?** §12.3 demotes `epoch` to settlement clock. The arg is already `settlementWeek`. Instruction name still says `epoch`. Fold into `0uv8` or defer to `wdvr.8`?

4. **Does `LocalLegend` stay keyed by `vault_id`?** D1 says Legend is stewardship of the economic wrapper (Vault). Keep seed `[LOCAL_LEGEND_SEED, vault_id]` or flip to `[LOCAL_LEGEND_SEED, climb_id]`? Affects PDA compatibility with existing elected legends.

5. **`ClimbCompletionReceipt` field `vault: Pubkey` — rename to `climb: Pubkey`?** Today the receipt is keyed by `[CLIMB_COMPLETION_RECEIPT_SEED, ride_attestation, vault]`. D1 inverts: receipt should bind to the Climb. Break receipt PDA backward compat?

6. **Fresh program ID vs on-chain migration instruction?** Fresh program ID matches V4-A precedent (per Return Brief "When you cut the fresh `0uv8` program ID..."). Existing devnet Vaults on V4-A program `37odBJvV...` are throwaway test data. Confirm: no migration needed, fresh deploy, update `addresses.devnet.json`?

7. **Does `0uv8` retire the Merkle-path dead code in the same slice, or is that `wdvr.8`?** `AllocationBatch`, `UserCalClaim`, `VaultAllocClaim` + `SubmitAllocationBatch`/`ClaimUserCal`/`ClaimAndConvertVaultAlloc` Accounts structs + `merkle_proof.py`. Either way, they come out before the Step N+5 legacy-retirement.

8. **Backend table renames `indexed_vaults` → `indexed_climbs`?** If Vault is a sub-object, `indexed_vaults` may still be correct as "indexed economic wrappers." Or rename to `indexed_climbs` (with optional `vault_pda` column) to match TRUTHS primacy. Affects indexer writer + DB migration scope.

9. **`VaultActivation` account — retire, or keep as `ClimbActivation`?** Originally a seeding lifecycle account for historical Strava imports. After V4-A, its use is narrow. Fold into `0uv8` scope or leave alone?

10. **`UserState` vs `RiderSoul` — retire `UserState` in `0uv8`, or wait?** Both co-exist. §12.4 says soulbound identity is a prepare-for item, not a require. Leaving `UserState` as-is is a cheap legacy keep; retiring it in the same slice amplifies blast radius.

---

## Appendix: files grepped

Scan methodology:
1. `protocol/anchor/programs/boulder_rollers/src/lib.rs` — lib.rs:155-2459 (instructions), 2463-3512 (accounts), 4845-5147 (events), 5151-5342 (errors).
2. `protocol/anchor/idl/boulder_rollers.json` + `target/idl/boulder_rollers.json` — identical, 41 instructions / 15 accounts / 31 events / 61 errors.
3. Backend grep for {IDL names}: 21 files hit. `solana_direct.py`, `tx_builder.py`, `ride_processor.py`, `ride_attester.py`, `ride_executor.py`, `projection_writer.py`, `leaderboard_sync_service.py`, `epoch_processor.py`, `merkle_proof.py`, `routes/vaults.py`, `routes/admin.py`, `repositories/vault.py`, plus tests.
4. Indexer grep for {IDL names}: 10 TS files hit. `decoder.ts`, `writers/index.ts`, all writers, both modes, `api.ts`, `reconciliation.ts`.
5. Portal grep: `web/portal/src/lib/solana.ts:3,16` only (program ID).
6. BoulderScan grep: zero hits on IDL types.
7. Mobile grep: `@coral-xyz/anchor` zero hits; `RideAttestation` only as local type.
8. Anchor tests: 4 specs, 62 total IDL-name occurrences.
