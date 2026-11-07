# V4-B Migration Plan and Test Fixtures

**Status:** RESEARCH — not executable as-is. Plan + fixture catalog to de-risk execution of `0uv8` (Climb-first surface split).
**Date:** 2026-04-17
**Owner:** Protocol agent on return; mobile/backend dispatcher as fallback per Tim's call.
**Semantic authority:** `docs/PROTOCOL_TRUTHS.md` — TRUTHS wins on any conflict.
**Execution plan it derives from:** `docs/design/PROTOCOL_ALIGNMENT_FIX_PLAN.md` (WS-1 Phase 2 ontology lift, WS-9 RiderSoul, WS-10 canonicalization spec).
**Scope — OUT:** no actual script code, no actual test code, no deploy execution, no choice of Option A vs Option B.
**Done-when:** all eight sections below, every invariant-level test cites a PROTOCOL_TRUTHS section, migration outlines enumerate inputs/outputs/preconditions/failure modes.

**Completion-evidence addendum (2026-07-14):** The starting-state inventory
predates `record_climb_completion_v2`. V1 now fails closed and remains readable
only as identity evidence. Every V4-B migration/test below that names a live
completion receipt must preserve V2's exact tribute field/hash, distinct
discriminator, and same-PDA replay guard.

---

## 0. Starting-State Inventory (audit snapshot 2026-04-17)

The picture the executor will inherit is **not** a green-field V4-A program.
Significant V4-B scaffolding has already landed in the V4-A redeploy. This
section keeps both options honest about what is already there.

### What V4-A already contains on devnet (`HsPhhMukUKu641e9hDJUJJW4chvF5EXYzuG2xBwMrnst`)

From `protocol/anchor/programs/boulder_rollers/src/lib.rs`:

**V4-B primitives already landed:**
- `RiderSoul` account + `RIDER_SOUL_SEED` (`b"rider_soul"`) — full field set: total_rides, total_tss, total_distance_m, total_vert_m, total_cal_earned, archetype, bio_score, card refs
- `RideAttestation` account + `RIDE_ATTESTATION_SEED` — full field set including `parser_version`, `attestation_commitment`, `completed_at`, `settled_at`, `economic_epoch`, `finalized`
- `CalMintReceipt` + `CLIMB_COMPLETION_RECEIPT_SEED` + `CAL_MINT_RECEIPT_SEED` child-receipt PDAs
- `ClimbCompletionReceipt` account
- `record_ride` instruction
- `credit_cal` instruction
- `record_climb_completion` instruction
- Per-bucket carry fields on `Vault` (`carry_record_royalty`, `carry_stakers`, `carry_local_legend`, `carry_pol`, `carry_treasury`)
- Settlement-week finalization plumbing (`open_settlement_week`, `last_distribution_epoch`, `SETTLEMENT_FINALIZATION_GRACE_SECONDS = 86_400`)

**V4-A deferred surface still present (the V4-B work):**
- Monolithic `Vault` struct still carries Climb identity: `signature`, `kom_holder`, `name`, `avatar_ipfs`, `slogan`, `total_completions`, `minter`, geography fields. **No separate `Climb` account exists yet.**
- `VaultLeaderboard` account still separate (should collapse into `Climb.record_board`).
- `distribute_epoch_rewards` still present (should rename to `finalize_settlement_week`).
- `record_vault_completion` still present (should rename to `record_climb_completion` — name already taken in V4-A by the new ride-attestation-keyed instruction; this is a **naming collision the executor must resolve**, see Open Questions §8).
- Merkle pipeline still live: `AllocationBatch`, `UserCalClaim`, `VaultAllocClaim`, `submit_allocation_batch`, `claim_user_cal`, `claim_and_convert_vault_alloc`, `verify_merkle_proof`, `compute_user_cal_leaf`, `compute_vault_alloc_leaf`, `USER_CAL_LEAF_DOMAIN`, `VAULT_ALLOC_LEAF_DOMAIN`. Decision #1 from PROTOCOL_ALIGNMENT_FIX_PLAN says these are deleted in V4-B.
- `UserState` still exists alongside `RiderSoul` (WS-9 says kill UserState after projections cut over).
- Synthetix fields still on `Vault` (`reward_per_token_stored`, `last_update_time`, `reward_rate`) marked legacy "to minimize Phase 1 blast radius."
- `create_vault` / `admin_create_vault` / `create_vault_with_usdc` still present; no `found_climb` / `attach_vault` split.
- 16+ devnet vaults exist under this program (source: PROTOCOL_ALIGNMENT_FIX_PLAN §WS-1). Clean-slate posture already ratified (Decision #2) for Phase 1; Phase 2 reopens the question for Phase B consumers.

### D1 pointer-direction lock (2026-04-17)

Climb holds `Option<Pubkey>` to Vault. Vault holds a Pubkey back to Climb.
Climb is the primary account. Climb-without-Vault is a well-formed state
(future Route/Zone attach the same way). Economic instructions resolve Vault
from Climb. Source: `docs/design/WWPTD_EPIC_PORTFOLIO_2026-04-17.md` D1, ratified by Tim.

### What's already downstream of V4-A that Phase B consumers now depend on

- Backend reads `indexed_vaults`, `vault_stakes`, `vault_leaderboards`, `vault_distributions` (all four reflect V4-A monolithic Vault).
- Indexer writers target the V4-A account shape.
- `backend/app/routes/climbs.py` exists (surfaces climb-ish reads) but underlying accounts are still V4-A Vault rows.
- Mobile + BoulderScan UI copy still says "Vault" in most places; `mfab.5` Phase A nomenclature slice landed some rename but not all.
- `mfab.3` (leaderboard truth inversion) and `mfab.4` (per-bucket carry API) are **blocked on 0uv8** — those two beads need the Climb/Vault split to land before they can be executed meaningfully.

### Implication

Both Option A (fresh program ID, wdvr.5 pattern) and Option B (realloc
existing program) must reason about a program that is already partially V4-B.
The delta to land V4-B is smaller than a naive read of PROTOCOL_ALIGNMENT_FIX_PLAN
would suggest. The **ontological** split (Climb as its own account) and the
**Merkle-path deletion** are the two biggest remaining surgeries.

---

## 1. Deploy Option Analysis

Two canonical options. Tim / protocol agent chooses — this research does not.

### Option A: Fresh program ID (wdvr.5 pattern)

**Approach:**
- Generate new `boulder_rollers-keypair.json` (capture pubkey).
- Update `declare_id!`, `Anchor.toml` `[programs.devnet]`, `addresses.devnet.json`, backend `solana_env.py`, indexer `config.ts`, mobile env, portal `.env.*`.
- `anchor build && anchor deploy --provider.cluster devnet`.
- Initialize ProgramConfig V4-B with `backend_authority = Key C` (Doppler), `admin_authority = Key B` (Ledger), `pol_token_account` + `treasury_token_account` from provisioned ATAs (carry forward from V4-A or re-provision).
- Seed initial state per §2.1 below.
- Point backend + indexer + portal + mobile at the new program ID via env var (no hardcoding).
- Old V4-A accounts strand on the old program ID — they exist forever as historical state. That is fine; V4-A's 16 vaults are test data.

**Upgrade authority handling:**
- Deploy signed by Ledger (Key A). Upgrade authority = Ledger.
- Ledger holder is Tim. This makes the fresh-program deploy a one-way door that requires Tim's hardware signing session.
- After deploy, immediately run WS-7 rotation drill on devnet: rotate Key C (backend_authority) from Ledger (Key B) as the critical validation step.

**Pros:**
- **Clean slate, zero migration risk.** No in-place realloc, no per-account surgery.
- **Rollback is free.** Old V4-A program keeps running. Point env vars back; backend services function as before.
- **Matches precedent.** wdvr.5 (V4-A) used this exact pattern; infra, scripts, and institutional memory are aligned.
- **Honors Decision #2 (2026-04-14):** "Clean slate for existing devnet state. 16 vaults are test data; no preservation."
- **Enables full rename without backwards-compat burden.** Hard rename P15 vocabulary lands in one shot (IDL, event names, field names).
- **Smallest blast radius on source code.** No realloc instructions, no admin migration helpers, no size-gate checks.
- **Simplest CI story.** Anchor tests run against a fresh program; no "old shape vs new shape" branching.

**Cons:**
- **Two program IDs in the wild on devnet.** V4-A stays live. Observers and stale test scripts may hit the wrong one.
- **Requires coordinated cutover.** Backend, indexer, portal, mobile, and any test harness all flip in lockstep. Miss one → silent dual-write or dual-read.
- **Env-var drift risk.** Old program ID hardcoded in any script or doc that missed the grep → slow-failing test.
- **Loses V4-A audit trail continuity.** The `indexed_settlement_week_finalizations` rows from V4-A do not join cleanly to V4-B rows. Phase B backend epics (`mfab.3`, `mfab.4`) need to decide if they want V4-A history at all.
- **Indexer runs two backfills or one.** Either point the indexer at only V4-B going forward (simple), or run it against both IDs and union (complex).

**Rollback story:**
- Point `BOULDER_ROLLERS_PROGRAM_ID` env vars back at `37odBJvV…` V4-A.
- Restart backend, indexer, portal, mobile build pipelines.
- V4-B program becomes dead weight; can abandon or re-upgrade via Ledger once the issue is fixed.
- **No data loss.** V4-A data still there. V4-B data is also test data on devnet.
- Rollback SLA: minutes (single env var + service restart), not hours.

**Cost estimate:**
- SOL: ~3-5 SOL for program deploy + ProgramConfig init + initial climb seeding (based on V4-A redeploy costs).
- Human time: ~half a day for deploy + smoke + downstream cutover if WS-10 canonicalization spec and Anchor source are already written.
- Coordination: requires Tim hardware signing session (Ledger Key A).

**Blast radius if something goes wrong:**
- **During deploy:** deploy fails, old program still live, zero blast. Retry.
- **During seeding:** seeding script fails mid-way, new program is in partial state. Worst case: redeploy. Old program untouched.
- **During cutover:** backend pointed at new ID, indexer still on old ID → indexer stops seeing writes. Catches within 1 epoch of inactivity. Fix: fix indexer env var, resume.
- **Post-cutover integrity bug:** V4-B deployed with buggy instruction. Roll back env vars. V4-A resumes. Ship fix, redeploy V4-B-v2 with another fresh ID (this is cheap by design).

---

### Option B: Realloc existing program

**Approach:**
- Deploy new bytecode to existing program ID (`37odBJvV…`) via `anchor upgrade`.
- Write `admin_realloc_vault_to_climb_and_vault` instruction that reads a V4-A Vault and initializes a paired `Climb` account + rewrites the existing Vault account with only the V4-B Vault fields.
- Run per-account migration script to walk all 16 V4-A vaults, call the realloc instruction for each.
- Preserve signatures, KOM holder + time, leaderboard via `admin_replace_vault_leaderboard`-style helper for seeding Record Board.
- Preserve per-bucket carry balances (already present on V4-A Vault).
- Delete Merkle path instructions from program, but account structs (AllocationBatch, UserCalClaim, VaultAllocClaim) stay as dead accounts unless explicitly closed via a cleanup instruction.
- Keep program ID constant: `addresses.devnet.json`, backend, indexer, mobile, portal do not change.

**Upgrade authority handling:**
- Program upgrade authority must be the current holder. Per V4-A deploy, that's `~/.config/solana/id.json`. WS-7 migration to Ledger already planned; this must happen **before** the upgrade (can't run realloc with a keypair that's about to be deprecated).
- If WS-7 Ledger migration done: upgrade signed by Ledger Key A.

**Pros:**
- **Single program ID.** No downstream env var flip. Existing consumers keep working across the cutover (subject to IDL update).
- **Preserves audit trail continuity.** V4-A history joins cleanly to V4-B going forward. Phase B consumers can query historic settlement across the boundary.
- **Preserves V4-A devnet test data if anyone cares.** (Tim said Decision #2: they don't. This is a pro only if that decision is reopened.)
- **Forces cleanup discipline.** Realloc path makes the team confront every per-account field change. Catches sloppy rename mistakes that a fresh deploy would paper over.

**Cons:**
- **Highest migration risk.** Realloc failures mid-walk leave accounts in half-migrated state. If the realloc instruction has a bug and has already touched N accounts, those N are corrupted and need an unstuck-er.
- **No clean rollback.** Once you've reallocated a Vault to split it, you cannot un-split. The only rollback is fix-forward: deploy another upgrade that patches the issue.
- **Requires writing + testing a non-trivial realloc instruction.** Anchor's realloc pattern with `init` for the new paired account, while preserving field values on the existing account, is fiddle-prone. Wrong seed, wrong size, wrong field ordering → brick.
- **Account-size math is unforgiving.** Current `Vault::SIZE ≈ 484 bytes` (counted from lib.rs impl). V4-B `Vault` (economic-only) is smaller (~200 bytes). V4-B `Climb` is larger (~400+ bytes with record_board array). Anchor can shrink by trimming but can't do "shrink this + create new sibling" in a single atomic instruction without careful SystemProgram dance.
- **Merkle path cleanup leaves debris.** AllocationBatch and claim accounts become orphans. Either close them via a cleanup instruction (more work) or accept account-explorer noise (bad ergonomics).
- **Backwards-compat weight.** IDL has both old and new account names during the transition period. Indexer decoder needs conditional logic keyed on account size or discriminator. Ugly.
- **Ties the deploy window to 16 successful sub-migrations.** A single failed migration on vault 12 of 16 keeps the system in dual-shape until resolved.

**Rollback story:**
- **Cannot un-realloc.** Fix-forward only.
- If bytecode upgrade fails but no migrations have run: revert to prior bytecode via `anchor upgrade` with old binary. Program behavior reverts. No data changes.
- If migrations have run: no rollback. Only fix-forward. Worst case → data loss for any account touched by a buggy migration.
- This is **actually a one-way door** in a way Option A is not.

**Cost estimate:**
- SOL: ~2 SOL for bytecode upgrade + ~0.02 SOL/vault for realloc rent + per-account Climb account creation. Total ~3 SOL for 16 vaults.
- Human time: ~2-3 days for realloc instruction design + testing on localnet + migration walker script + dry-run on devnet + real run.
- Coordination: requires Tim hardware signing session AND debug availability during the walker script run in case of failure mid-walk.

**Blast radius if something goes wrong:**
- **Bytecode upgrade fails:** revert via prior binary. Zero blast.
- **Realloc instruction bug, discovered before walker run:** patch bytecode, redeploy. Zero blast.
- **Realloc instruction bug, discovered mid-walker run:** N vaults corrupted, N remaining unmigrated. Need unstuck-er instruction; Tim's call on whether to give up and fresh-deploy.
- **Realloc succeeds but indexer can't decode new shape:** indexer stops seeing writes. Backfills broken until IDL + decoder aligned.
- **Size math wrong:** single realloc call panics, walker halts at that account. Debug + patch + resume.

---

### Option comparison summary

| Dimension | Option A (Fresh) | Option B (Realloc) |
|---|---|---|
| Migration risk | Low | High |
| Rollback | Free (env flip) | Fix-forward only |
| Downstream cutover | All services at once | None (same ID) |
| Audit continuity | Broken across boundary | Preserved |
| Decision #2 alignment | Matches (clean slate) | Reopens |
| SOL cost | ~3-5 | ~3 |
| Human time | ~0.5 day | ~2-3 days |
| wdvr.5 precedent | Matches | Does not match |
| One-way door | No | Yes |
| Best for hackathon sprint | **Yes** | No |

**Research-author lean (non-binding):** Option A. The PROTOCOL_ALIGNMENT_FIX_PLAN
already ratified Decision #1 (fresh program ID) and Decision #2 (clean slate)
for V4-A, and those decisions apply equally here. The incremental value of
Option B's audit-continuity pro is low on devnet test data and high on
realloc risk. Hackathon sprint with protocol agent iced argues for the lowest
one-way-door risk path.

Tim / protocol agent on return: pick. This doc stays neutral.

---

## 2. Detailed Migration Script Outline

### Option A (fresh program ID) — scripts under `protocol/anchor/scripts/`

Follow the archived `migrate_v3_security.ts` structure:
- `import` block matching existing style (`@solana/web3.js`, `anchor`, `addresses.devnet.json`).
- `loadAdminKeypair()` helper (Ledger path when WS-7 lands; `~/.config/solana/id.json` until then).
- PDA helpers mirror existing seed constants from `lib.rs`.
- Discriminator helper: `sha256("global:<instruction_name>").slice(0,8)`.
- Top-level `main()` with numbered steps, explicit `console.log`, `try/catch` on each step with exit on error.

#### `scripts/deploy_v4b.ts`

**Responsibility:** Deploy the V4-B program bytecode and initialize `ProgramConfig`.

**Inputs:**
- `BOULDER_ROLLERS_PROGRAM_ID` (from fresh keypair, written into `addresses.devnet.json` before run)
- `ADMIN_KEYPAIR_PATH` (Ledger when WS-7 landed)
- `BACKEND_AUTHORITY_PUBKEY` (Key C, Doppler-sourced)
- `POL_TOKEN_ACCOUNT` (from provisioned devnet ATA or placeholder)
- `TREASURY_TOKEN_ACCOUNT` (same)
- `CAL_MINT_ADDRESS` (from `addresses.devnet.json` — can reuse V4-A mints since mints are SPL tokens independent of program)
- `DUNG_MINT_ADDRESS` (same)
- `CLUSTER` (devnet)

**Outputs:**
- `ProgramConfig` PDA initialized with V4-B shape.
- CAL + DUNG mint authorities transferred to new program's mint-auth PDAs (if different from V4-A auths — often they are, because mint-auth PDA derivation depends on program ID).
- Confirmation tx signatures logged.
- `addresses.devnet.json` updated atomically at end (or written by human and checked in separately).

**Preconditions:**
- `anchor build` produces target artifact matching fresh keypair.
- Admin keypair has ≥2 SOL.
- `anchor deploy --provider.cluster devnet` has run (can be inlined in script or pre-run).
- V4-A mint authorities are transferable (script `transfer_mint_authorities.ts` pattern).
- If reusing CAL+DUNG mints: V4-A mint authorities must be under Tim's control to transfer to V4-B PDAs.

**Failure modes:**
- Deploy fails (insufficient SOL, program ID collision, bytecode too large). Abort, fix, retry.
- `initialize_program_config` fails (already initialized). Means program was deployed before; abort, check state, decide.
- Mint authority transfer fails (authority keypair missing, permissions wrong). Abort; mint authority lockup can brick the whole program until resolved.
- `configure_treasury_accounts` fails (POL or treasury account doesn't exist). Abort; script must bail before any state change.

#### `scripts/seed_v4b_state.ts`

**Responsibility:** Initialize program state that must exist before any rider-facing interactions.

**Inputs:**
- `BOULDER_ROLLERS_PROGRAM_ID` (V4-B)
- `ADMIN_KEYPAIR_PATH`
- Optional: `SEED_CLIMBS_FROM` (path to a JSON file of climb signatures to bootstrap)

**Outputs:**
- `VaultCounter` (or `ClimbCounter`) PDA initialized to 0.
- `DungMintState` PDA initialized with caps (1B / 400M / 250M / 200M / 100M / 50M) and epoch 0.
- Optionally N seed Climb accounts with placeholder metadata (for smoke testing).

**Preconditions:**
- `deploy_v4b.ts` completed.
- `ProgramConfig` exists.

**Failure modes:**
- `initialize_vault_counter` already-initialized → idempotent; log and continue.
- `initialize_dung_mint_state` already-initialized → idempotent.
- Seed climb file malformed → abort before any write.

#### `scripts/migrate_existing_vaults_v4b.ts` (OPTIONAL under Decision #2)

**Responsibility:** Walk V4-A vaults (read-only), create corresponding V4-B Climb + Vault pairs on V4-B. **Only runs if Tim reopens Decision #2.**

**Default recommendation per existing decisions:** **Do not run this script.** Decision #2 says 16 V4-A vaults are test data, no preservation. Include this script in the scripts directory as a **commented-out template** so future V4-B-on-mainnet work has a starting point.

**Inputs:**
- V4-A `BOULDER_ROLLERS_PROGRAM_ID` (`37odBJvV…`)
- V4-B `BOULDER_ROLLERS_PROGRAM_ID` (new)
- `ADMIN_KEYPAIR_PATH`
- `VAULT_IDS` (list of V4-A vault IDs to migrate, default: all from VaultCounter)

**Outputs per vault:**
- `Climb` PDA on V4-B seeded from V4-A Vault: signature, signature_hash, founder (=V4-A minter), kom_holder, kom_time_s, kom_set_at, vert_m, distance_m, avg_gradient_pct, name, avatar_ipfs, slogan, total_completions, total_cal_committed, total_dung_distributed.
- `Vault` PDA on V4-B linked to Climb via Climb.vault = Some(vault_pda): carry balances preserved, pending_rewards preserved, staker_count preserved, last_finalized_epoch = V4-A last_distribution_epoch.
- `VaultLeaderboard` → seeded into `Climb.record_board` via `admin_seed_record_board` helper (must be added to V4-B program explicitly).
- `LocalLegend` PDA preserved.

**Preconditions:**
- Both V4-A and V4-B programs exist and are deployable.
- Admin keypair has authority on both.
- `admin_seed_*` helpers exist on V4-B to backfill state (see Tim/protocol agent decision — these exist today on V4-A as `admin_seed_vault_completion_summary`, `admin_replace_vault_leaderboard`, etc).

**Failure modes:**
- Read of V4-A vault fails (account not found) → skip, log, continue.
- V4-B Climb account already exists (re-run or collision) → idempotent guard required.
- V4-A VaultLeaderboard has fewer than 10 entries → copy what's there, leave rest empty.
- Per-bucket carry on V4-A has value but V4-B flow hasn't fully wired carry-distribution → set carry, trust V4-B finalize_settlement_week to drain correctly in next settlement.
- Staker positions on V4-A → **out of scope for this script.** Stakers must unstake from V4-A before V4-B migration. Document in script header.

---

### Option B (realloc) — scripts under `protocol/anchor/scripts/`

Follow `migrate_v3_security.ts` structure even more closely since Option B is fundamentally a realloc pattern.

#### `scripts/realloc_program_config_v4b.ts`

**Responsibility:** Extend `ProgramConfig` if the V4-B shape needs new fields (e.g., added `climb_counter_pda` or a V4-B marker).

**Inputs:**
- `BOULDER_ROLLERS_PROGRAM_ID` (unchanged)
- `ADMIN_KEYPAIR_PATH`

**Outputs:**
- `ProgramConfig` account resized to V4-B shape. New fields zeroed.
- `configure_v4b_fields` follow-up call to populate any new fields.

**Preconditions:**
- V4-B bytecode deployed via `anchor upgrade`.
- V4-B program has `realloc_program_config_v4b` instruction available.
- Admin keypair has ≥0.1 SOL.

**Failure modes:**
- ProgramConfig already at V4-B size → idempotent, skip.
- Size-threshold check wrong → script silently skips when it should migrate (this is what killed `migrate_v3_security.ts`). Use discriminator-byte probe or version-byte field, not size check.
- Realloc fails (insufficient rent, admin signer wrong) → abort, fix.

#### `scripts/realloc_and_split_vaults_v4b.ts`

**Responsibility:** For each V4-A `Vault` account, invoke `admin_realloc_vault_to_climb_and_vault` which:
1. Reads current Vault account data.
2. Creates a paired `Climb` PDA (seeds `[b"climb", signature_hash]` or `[b"climb", vault_id_as_bytes]` — protocol agent chooses).
3. Populates Climb with geographic / identity fields (signature, founder, KOM, etc).
4. Shrinks Vault account to V4-B Vault shape, preserving economic fields (carry, pending_rewards, staker_count, etc).
5. Writes Vault.climb = climb_pda. Writes Climb.vault = Some(vault_pda).

**Inputs:**
- `BOULDER_ROLLERS_PROGRAM_ID` (unchanged)
- `ADMIN_KEYPAIR_PATH`
- Optional: `START_AT_VAULT_ID` (to resume interrupted migration)
- Optional: `STOP_AT_VAULT_ID` (for canary migration of first 1-2 vaults)

**Outputs per vault:**
- `Climb` PDA created.
- `Vault` PDA reshaped, pointing at Climb.
- Migration log line: `vault_id, climb_pda, vault_pda, tx_sig, pre_size, post_size`.
- Exit code 0 on full success, 1 on any partial failure with halt-at-first-error semantics.

**Preconditions:**
- Option B bytecode deployed (`anchor upgrade` succeeded).
- `realloc_program_config_v4b.ts` has run.
- Localnet dry-run completed successfully against a test harness of 16 fabricated V4-A vaults.
- Admin keypair has ≥3 SOL.

**Failure modes:**
- Size math wrong → single-vault realloc panics → walker halts, partial migration. Need recovery plan documented in script header.
- Signer wrong → instruction-level error → halt, fix, resume from `START_AT_VAULT_ID`.
- Climb PDA collision (seed already taken) → only possible if script was partially run before. Idempotent guard: read existing Climb first, skip if present and consistent.
- Source Vault already migrated (already smaller than V4-A size) → skip, log.
- `VaultLeaderboard` separate account → need companion walker to fold leaderboard into Climb.record_board. Separate sub-script `fold_leaderboards_v4b.ts`.
- `LocalLegend` account → stays in place, no change needed.
- `VaultStake` accounts → stays in place, must update `vault_stake.vault` ref if Vault PDA address changed (it shouldn't, since we're reshaping same account).

---

## 3. Test Fixture Harvest from TRUTHS

Rust Anchor tests. Each test citation traces to exactly one PROTOCOL_TRUTHS
section. Test names use `test_` prefix per Rust convention; Anchor TS tests
use `describe/it` but same semantic names apply.

Format: **test name** (TRUTHS citation) — setup → assertion.

### §2 Core Objects

- **`test_climb_identity_is_permanent_on_init`** (§2.1) —
  Setup: found a Climb with signature X. Assertion: Climb.signature is immutable via any subsequent instruction; no instruction exists that mutates `signature` or `signature_hash`.

- **`test_climb_exists_without_vault`** (§2.1, §2.2) —
  Setup: call `found_climb` but not `attach_vault`. Assertion: Climb account exists, Climb.vault == None, economic instructions (record_climb_completion) fail cleanly with `VaultNotAttached` error — not panic, not silent no-op.

- **`test_vault_requires_climb`** (§2.2) —
  Setup: try to `attach_vault` with a non-existent Climb PDA. Assertion: rejected with account-does-not-exist error. **Note:** the proposed test name in the user's spec ("test_vault_can_exist_without_climb") indeed should NOT pass — a Vault without a Climb is a violation of §2.2. The correct assertion is that the inverse is forbidden.

- **`test_vault_points_at_its_climb`** (§2.2) —
  Setup: found + attach. Assertion: Vault.climb == Climb.key(), Climb.vault == Some(Vault.key()). Bidirectional pointer consistency.

- **`test_ride_attestation_immutable_after_init`** (§2.3) —
  Setup: `record_ride` creates a RideAttestation. Attempt subsequent write. Assertion: no instruction mutates `ride_hash`, `completed_at`, `started_at`, `attestation_commitment`, `parser_version` after creation. (Existing `RideAttestation.finalized` bool is the only mutable-after-init field and only flips once, settlement-driven.)

- **`test_ride_attestation_pda_uniqueness`** (§2.3) —
  Setup: `record_ride(rider, ride_hash_X)` succeeds. Attempt `record_ride(rider, ride_hash_X)` again. Assertion: second call fails with AccountAlreadyInitialized — structural replay protection via Anchor init + PDA seed.

### §3 Temporal Truths

- **`test_kom_persists_across_epochs`** (§3.1) —
  Setup: set KOM in epoch N. Advance clock to epoch N+5. Assertion: Climb.kom_holder + kom_time_s + kom_set_at unchanged. No epoch-finalization instruction mutates KOM.

- **`test_founder_persists_across_epochs`** (§3.1) —
  Setup: found climb as rider A. Advance epochs. Assertion: Climb.founder == rider_A, never mutates.

- **`test_record_board_persists_across_epochs`** (§3.1) —
  Setup: post 10 record board entries in epoch N. Finalize multiple epochs. Assertion: record_board entries preserve their rider, time_s, completed_at across finalizations. Only new-time-beats-existing causes a change.

- **`test_lifetime_cal_monotonic`** (§3.1) —
  Setup: tribute CAL across 5 settlement weeks. Assertion: Climb.total_cal_committed is monotonically increasing; no decrement path anywhere in the program.

- **`test_local_legend_can_go_dormant`** (§3.2) —
  Setup: elect legend in epoch N with term_end_epoch = N+8. Advance to N+9 without electing successor. Assertion: Vault.local_legend_active == false OR LocalLegend.is_term_expired(current_epoch) == true. Legend bucket carry grows next settlement.

- **`test_settlement_finalizes_only_once_per_epoch`** (§3.3) —
  Setup: finalize epoch N. Attempt finalize epoch N again. Assertion: rejected with EpochAlreadyFinalized. `vault.last_finalized_epoch` guard holds.

- **`test_settlement_blocked_before_grace_window`** (§3.3) —
  Setup: try finalize at `epoch_end + 0s`. Assertion: rejected with GracePeriodActive. Try at `epoch_end + 86_400 - 1s`. Still rejected. Try at `epoch_end + 86_400 + 1s`. Accepted.

### §4 Settlement Clock

- **`test_epoch_is_not_ontology_for_climb`** (§4) —
  Setup: climb found in epoch N. Read climb in epoch N+100. Assertion: no field on Climb tracks "current epoch"; Climb identity is epoch-free. `Vault.current_epoch()` is a helper, not stored on Climb.

- **`test_epoch_only_gates_settlement_instructions`** (§4) —
  Setup: attempt non-settlement instructions (found_climb, stake_cal_in_vault, record_climb_completion) at an arbitrary block time. Assertion: none reject on epoch boundary. Only `finalize_settlement_week` has an epoch-gate.

### §5 Representation Layers

- **`test_on_chain_holds_binding_state_only`** (§5.1) —
  Setup: call all state-mutating instructions with their minimum inputs. Assertion (structural, not per-test): on-chain account sizes compiled from `impl AccountType { const SIZE }` stay within the inventory documented in PROTOCOL_TRUTHS §5.1 (Climb, Vault, RiderSoul, LocalLegend, RideAttestation, receipts, staking, settlement) — no raw GPS points, no parsed FIT metadata.

- **`test_raw_ride_data_not_on_chain`** (§5.2) —
  Setup: pass a RideAttestation with `attestation_commitment` field. Assertion: RideAttestation has no `gps_points`, no `power_samples`, no `elevation_samples` fields. Only the commitment hash and summary metrics.

### §6 Protocol Roles

- **`test_founder_set_at_found_climb_immutable`** (§6.1) —
  Setup: found climb. Assertion: Climb.founder set to signer, no instruction mutates it.

- **`test_founder_gets_first_legend_bootstrap`** (§6.1) —
  Setup: found climb. Assertion: LocalLegend.holder == founder, LocalLegend.bootstrap == true, term_end_epoch == current + 8.

- **`test_founder_is_not_kom`** (§6.1, §6.2) —
  Setup: found climb with founder A. Post fastest-time ride by rider B. Assertion: Climb.kom_holder == B, Climb.founder == A. Separate roles.

- **`test_kom_is_current_all_time_fastest`** (§6.2) —
  Setup: post times T1=500, T2=450, T3=480 in sequence. Assertion: after each, kom_time_s == min(all posted). Final kom == 450 (rider of T2).

- **`test_kom_strict_less_than_required_to_unseat`** (§6.2, mirror TRUTH_CONTRACT INV-ECON-5) —
  Setup: post T1=500 (KOM). Post T2=500 (equal). Assertion: KOM holder unchanged. Equal time does not dethrone.

- **`test_kom_separate_from_stewardship`** (§6.2, §6.4) —
  Setup: KOM held by rider A. Elect LocalLegend B. Assertion: kom_holder and local_legend are independent Pubkey fields; neither rotation affects the other.

- **`test_kom_separate_from_capital`** (§6.2, §6.5) —
  Setup: KOM held by rider A, no stake. Rider B stakes max CAL in vault. Assertion: kom_holder still A. Staking never touches KOM.

- **`test_record_board_top_10_all_time`** (§6.3) —
  Setup: post 15 completions with increasing speeds (time_s descending). Assertion: record_board contains the 10 fastest, sorted by time_s asc. Ranks 11-15 absent from record_board but present in their individual ClimbCompletionReceipt.

- **`test_record_board_bumps_lower_entries_on_new_top`** (§6.3) —
  Setup: record_board full with times [100..200]. Post time 90. Assertion: 90 inserts at rank 1, ranks 1-9 shift to 2-10, old rank 10 (time=200) evicted from board.

- **`test_local_legend_rolling_term`** (§6.4) —
  Setup: elect legend A with term_end_epoch = N+8. Advance to N+8. Elect legend B. Assertion: LocalLegend.holder == B, term_end_epoch == N+16. A removed from seat (but payout history preserved via events).

- **`test_local_legend_based_on_recent_completions`** (§6.4) —
  Setup: rider A completes 5 times in current term, rider B completes 10. Call finalize_legend_election. Assertion: legend == B.

- **`test_staker_capital_does_not_impersonate_effort`** (§6.5) —
  Setup: rider A stakes 10_000 CAL. Assertion: Climb.kom_holder does not change; record_board does not gain rider A entry; RiderSoul.total_rides for A unchanged; staking is economically effective only via VaultStake pro-rata in settlement bucket.

### §7 Token Meanings

- **`test_cal_is_spl_transferable`** (§7.1) —
  Setup: credit_cal mints to rider A ATA. Rider A SPL-transfers to rider B. Assertion: succeeds via standard SPL token CPI. CAL has no custom transfer gate.

- **`test_cal_earned_not_equal_to_cal_balance`** (§7.1, §7.3) —
  Setup: credit_cal 100 to rider. Transfer 50 out. Assertion: RiderSoul.total_cal_earned == 100 (monotonic lifetime); SPL balance == 50 (spot).

- **`test_cal_stakeable_into_vault`** (§7.1) —
  Setup: credit_cal to rider. stake_cal_in_vault. Assertion: VaultStake created, Vault.total_cal_staked increments, rider SPL CAL balance decrements.

- **`test_dung_emitted_from_settlement_not_from_cal_transfer`** (§7.2) —
  Setup: credit_cal to rider. Assertion: no DUNG minted as a direct consequence. DUNG minting requires `finalize_settlement_week` path or `upgrade_beetle_card` (burn path reverse).

- **`test_rider_soul_not_transferable`** (§7.3) —
  Setup: rider A has RiderSoul. Assertion: no instruction exists that reassigns RiderSoul.rider; PDA seed `[b"rider_soul", rider]` prevents creating a soul for a different rider under someone else's control.

- **`test_capital_does_not_buy_riderhood`** (§7.3) —
  Setup: rider A stakes CAL. Assertion: RiderSoul.total_rides unchanged for A as a consequence of staking. Only record_ride increments total_rides.

### §8 Canonical Economic Buckets

- **`test_record_royalty_55_percent`** (§8.1) —
  Setup: 1000 DUNG pending_rewards. Record board has 10 entries. Finalize. Assertion: total minted to record_board recipients across all 10 ranks == 550 DUNG (allowing for rounding dust flowing to carry_record_royalty).

- **`test_record_royalty_rank_split_30_20_15_10_8_6_5_3_2_1`** (§8.1) —
  Setup: 10_000 DUNG to record royalty bucket. Finalize. Assertion: rank 1 receives 3000, rank 2 receives 2000, rank 3 receives 1500, ... rank 10 receives 100. Sum = 10_000. `LEADERBOARD_RANK_PCTS` constant unchanged.

- **`test_staker_27_percent`** (§8.2) —
  Setup: 1000 DUNG pending_rewards. 10 eligible stakers all stake equal amounts. Finalize. Assertion: total allocated across VaultStake.unclaimed_rewards == 270 DUNG (staker_unlock_pct = 100% at 10 stakers).

- **`test_staker_unlock_curve`** (§8.2, from FRESHEST_SPEC STAKER_UNLOCK_PCTS) —
  Setup: parameterize staker_count in {0, 1, 2, ..., 10}. Finalize each case. Assertion: the current week's base staker maximum follows STAKER_UNLOCK_PCTS exactly; its locked difference joins the same week's Record Royalty, while only already-unlocked pro-rata integer dust remains in `carry_stakers`.

- **`test_legacy_staker_carry_cutover`** (§8.2) —
  Setup: an unmarked V4-A Vault with nonzero legacy `carry_stakers`. Finalize once, then again. Assertion: the first settlement moves the full legacy value to Record Royalty, emits `StakerRemainderPolicyApplied`, and writes the policy marker; no legacy value enters staker allocation. The second settlement treats only newly produced pro-rata dust as staker carry.

- **`test_local_legend_3_percent`** (§8.3) —
  Setup: 1000 DUNG pending, legend active. Finalize. Assertion: 30 DUNG minted to legend ATA, LocalLegend.total_earned += 30.

- **`test_protocol_10_percent`** (§8.4) —
  Setup: 1000 DUNG pending. Finalize. Assertion: 100 DUNG minted to ProgramConfig.treasury_token_account.

- **`test_pol_5_percent`** (§8.4) —
  Setup: 1000 DUNG pending. Finalize. Assertion: 50 DUNG minted to ProgramConfig.pol_token_account.

- **`test_distribution_shares_sum_to_100`** (§8 composite, TRUTH_CONTRACT style) —
  Setup: read constants. Assertion: `LEADERBOARD_SHARE_BPS + STAKER_SHARE_BPS + LOCAL_LEGEND_SHARE_BPS + POL_SHARE_BPS + PROTOCOL_FEE_BPS == 10_000`. Already tested in current `boulder_rollers_e2e.spec.ts`.

### §9 Economic Meaning of Quiet Climbs

- **`test_quiet_climb_still_earns_record_royalty`** (§9) —
  Setup: Climb with old record_board (kom set 10 epochs ago). Rider tributes CAL in current epoch. Finalize. Assertion: record_royalty paid to existing record_board entries despite stale KOM.

- **`test_empty_bucket_carries_within_bucket`** (§9, also P10) —
  Setup: record_board empty (no completions ever), with 10 eligible stakers so the current staker base is fully unlocked. Pending_rewards > 0. Finalize. Assertion: 0 DUNG minted to record_board; `carry_record_royalty` increments by its base share; other buckets still pay normally.

- **`test_dormant_legend_carries_within_legend_bucket`** (§9, P10) —
  Setup: Vault.local_legend_active == false. Pending_rewards > 0. Finalize. Assertion: 0 DUNG to legend; `carry_local_legend` += 3% of pending; other buckets paid.

- **`test_per_bucket_carry_never_leaks_between_buckets`** (§9, P10 — critical invariant) —
  Setup: record_board empty + legend dormant + 0 stakers. Pending_rewards = 10_000. Finalize. Assertion: `carry_record_royalty += 8200` (5500 base plus the same-week 2700 locked staker amount), prior unlocked `carry_stakers` remains unchanged, `carry_local_legend += 300`, treasury pays 1000, and POL pays 500. The explicit policy reallocation occurs before carry; no stored carry leaks between buckets.

### §10 Privacy Boundary

- **`test_on_chain_has_no_raw_gps`** (§10) —
  Setup: structural. Assertion: no account field of type `[u8; >1024]` for GPS traces, no `lat_points: Vec<i32>`, no `elevation_samples`. Only signature (64 bytes, compressed) and summary metrics.

---

## 4. Existing Anchor Tests — Porting Inventory

Existing test files: `boulder_rollers_cal.spec.ts` (86 lines), `boulder_rollers_cal_alloc.spec.ts` (1221 lines), `boulder_rollers_e2e.spec.ts` (1304 lines), `boulder_rollers_synthetix_stake.spec.ts` (788 lines).

### `boulder_rollers_cal.spec.ts`

| Test | Action |
|---|---|
| `mint_daily_cal instruction was removed` | **Retire** — already testing a removed thing; under V4-B this test has no meaning since the instruction stays removed. |
| `admin_credit_cal instruction was removed` | **Retire** — same reason. |
| `admin_debit_cal instruction was removed` | **Retire** — same. |
| `burn_cal_for_segment instruction was removed` | **Retire** — same. |
| `user PDA is deterministic` | **Needs rename** — `user` → `rider_soul`; seed change from USER_SEED to RIDER_SOUL_SEED. |
| `different owners produce different user PDAs` | **Needs rename** — same. |
| `segment PDA is deterministic` | **Retire** — `Segment` is dead code (external review noted in indexer writers), V4-B has no segment concept. |
| `different segment IDs produce different PDAs` | **Retire** — same. |

### `boulder_rollers_cal_alloc.spec.ts`

**All tests in this file are against the Merkle allocation pipeline** (AllocationBatch, UserCalClaim, VaultAllocClaim, submit_allocation_batch, claim_user_cal, claim_and_convert_vault_alloc, verify_merkle_proof, domain-separated leaf hashes).

**Action: retire the entire file.** Per Decision #1 the Merkle path is deleted in V4-B. All ~30 tests go. Replace with new file `boulder_rollers_ride_attestation.spec.ts` containing the `credit_cal`/`record_ride`/`record_climb_completion`/child-receipt tests (see §3 above for test names).

### `boulder_rollers_e2e.spec.ts`

| Test | Action |
|---|---|
| `should have DUNG mint authority set to dung_mint_auth PDA` | **Passes unchanged** — account-agnostic mint auth check. PDA seed still `dung_mint_auth`. |
| `should have CAL mint authority set to cal_mint_auth PDA` | **Passes unchanged** — same. |
| `should submit batch and claim user CAL with valid Merkle proof` | **Retire** — Merkle pipeline deletion. |
| `should submit batch and claim vault allocation, incrementing pending_rewards` | **Retire** — same. |
| `should stake CAL and receive LP tokens` | **Structural rewrite** — VaultStake semantics change (discrete allocation, `effective_from_epoch`), LP token concept may be retired under discrete allocation. |
| `should record completions for 3 users and populate leaderboard` | **Rename + structural** — `record_vault_completion` → `record_climb_completion`; leaderboard → record_board (field on Climb, not separate account). Verify ride_attestation child receipt. |
| `distributeEpochRewards should distribute DUNG to leaderboard, POL, and treasury` | **Rename + expand** — instruction rename to `finalize_settlement_week`; also assert staker + legend buckets + carry correctness per §8 tests above. |
| `harvestRewards should handle harvest` | **Structural rewrite** — under discrete allocation, harvest = claim unclaimed_rewards to ATA; zero time-delta math. |
| `should reject harvest from non-staker` | **Passes with rename** — same access control, instruction renamed but semantics identical. |
| `distribution shares summing to 100%` | **Passes unchanged** — constant check. |
| `leaderboard rank percentages summing to 100%` | **Passes unchanged** — constant check. Test description string should update `leaderboard` → `record board`. |

### `boulder_rollers_synthetix_stake.spec.ts`

**All Synthetix-accrual tests are retired by P8 / Decision #3 (abandon Synthetix).**

| Test | Action |
|---|---|
| `stakes CAL and receives LP tokens 1:1 for first staker` | **Structural rewrite** — LP token concept likely retired; replace with `stake_cal_in_vault` asserts VaultStake.effective_from_epoch == current+1, Vault.total_cal_staked increments. |
| `rejects stake below minimum (100 CAL)` | **Passes with minor rename** — CAL_MIN_STAKE unchanged. |
| `rejects stake when CAL balance insufficient` | **Passes unchanged** — SPL-level check. |
| `unstakes CAL and returns principal proportionally` | **Structural rewrite** — under discrete model, unstake returns principal less exit fee; no proportional-LP math. |
| `stake_in_vault instruction was removed (DUNG staking deprecated)` | **Retire** — already testing a removed thing. |
| `unstake_from_vault instruction was removed (DUNG staking deprecated)` | **Retire** — same. |
| `updates reward checkpoints when staking` | **Retire** — Synthetix reward_per_token_stored removed in V4-B. |
| `accumulates rewards in stake record` | **Structural rewrite** — rewards accumulate via direct allocation at finalize_settlement_week, not continuous. Test becomes "finalize_settlement_week credits unclaimed_rewards for eligible staker." |
| `allocates LP tokens proportionally for second staker` | **Structural rewrite** — LP concept retired. New test: multiple stakers each get pro-rata share of 27% bucket. |
| `rejects harvest when no rewards available` | **Passes with rename** — same semantics. |
| `distribution shares sum to 100%` | **Passes unchanged** — duplicate with e2e file. |
| `leaderboard rank percentages sum to 100%` | **Passes unchanged** — same. |
| `verifies harvest fee is 5%` | **Passes unchanged** — HARVEST_FEE_BPS constant. |

### Porting summary

| Category | Count |
|---|---|
| Passes unchanged | ~10 |
| Needs rename only | ~5 |
| Needs Climb parameter added / field access rename | ~8 |
| Structural rewrite | ~10 |
| Retires | ~40 (bulk of cal_alloc.spec.ts + Synthetix-accrual tests + removed-instruction regressions) |

Target per FIX_PLAN: ≥60 passing tests post-rewrite. Current count pre-rewrite: 55. After retirement of ~40, plus ~30 new tests from §3 harvest + §5 regression + §6 migration (Option B), net should comfortably exceed 60.

---

## 5. Economic Regression Test Design

**Goal:** prove that the 55/27/3/10/5 split and per-bucket carry produce
**bit-identical** bucket amounts on the V4-A monolithic Vault shape and the
V4-B Climb+Vault shape, for the same pending_rewards + staker_count +
record_board state.

### Oracle strategy

V4-A devnet is the oracle. For a snapshot of a live V4-A vault with non-zero
pending_rewards and a populated leaderboard, we have the post-finalization
state via `indexed_vault_distributions` rows. Those rows are our ground
truth.

### Test construction

**Test: `test_economic_regression_v4a_oracle_match`** (spans §8, §9, §P10)

**Setup:**
1. Read V4-A devnet vault state (via indexer or direct RPC) at a known pre-finalization moment: `pending_rewards_V = X`, `staker_count_V = K`, `record_board_V = [...]`, `carry_* = [...]`, `local_legend_active_V = L`.
2. Read the V4-A post-finalization `indexed_vault_distributions` row: `leaderboard_paid = A, staker_paid = B, legend_paid = C, pol_paid = D, protocol_paid = E, carry_after = [...]`.
3. In Anchor test harness (localnet), construct a V4-B Climb + Vault with identical input state: same pending_rewards, same staker_count, same record_board entries, same carry values, same local_legend_active flag.
4. Run `finalize_settlement_week` on V4-B in the test.

**Assertion:**
- Sum of DUNG minted to record_board recipients (across 10 ranks) == A.
- Sum of DUNG allocated to VaultStake.unclaimed_rewards across all eligible stakers == B.
- DUNG minted to LocalLegend ATA == C.
- DUNG minted to POL ATA == D.
- DUNG minted to treasury ATA == E.
- Post-finalization carry_record_royalty, carry_stakers, carry_local_legend, carry_pol, carry_treasury on V4-B == carry_after on V4-A.
- V4-B Vault.last_finalized_epoch == V4-A Vault.last_distribution_epoch + 1 (since oracle captured pre-state).

**What this proves:** the split math, the carry math, and the staker-unlock curve all translate faithfully through the ontology split. The economic invariants survive the Climb/Vault decomposition.

**Dataset:** need ≥3 V4-A oracle snapshots covering: (a) typical case, full leaderboard + stakers + active legend; (b) dormant legend case; (c) empty leaderboard case. If V4-A devnet doesn't have these cases in its history, construct them by admin-seeding V4-A state before the oracle capture. **Tim decision: is 3 snapshots enough or do we want N=10+?**

---

## 6. Data Migration Verification Tests (Option B only)

Only applicable if Tim chooses Option B. If Option A, these tests are moot
(no migration, no preservation).

### Test suite: `boulder_rollers_v4b_migration.spec.ts`

#### `test_post_migration_climb_fields_match_source_vault`
Setup: pre-migration, read V4-A vault 0 fields into a JSON snapshot. Run migration. Read V4-B Climb PDA derived from vault 0. Assertion: Climb.signature, signature_hash, founder, kom_holder, kom_time_s, kom_set_at, vert_m, distance_m, avg_gradient_pct, name, avatar_ipfs, slogan all byte-equal the V4-A source.

#### `test_post_migration_vault_fields_preserve_economics`
Setup: same as above. Assertion: V4-B Vault.pending_rewards, carry_record_royalty, carry_stakers, carry_local_legend, carry_pol, carry_treasury, total_cal_staked, staker_count, last_finalized_epoch equal the V4-A values.

#### `test_no_fields_lost_during_migration`
Setup: V4-A account field inventory (from serialized snapshot). V4-B post-migration field inventory (Climb + Vault union). Assertion: every V4-A field appears in the union, excluding explicitly deleted fields (reward_per_token_stored, last_update_time, reward_rate, total_staked, cal_tribute_accumulated, cal_tribute_accumulated_next, pending_rewards_next_week). Fail if a non-deleted field is absent.

#### `test_no_fields_fabricated_during_migration`
Setup: V4-B fields that did not have a source on V4-A (e.g., a new field added post-split). Assertion: every such field has a documented default-value policy in PROTOCOL_ALIGNMENT_FIX_PLAN or is zero. Fail if a random field has a non-zero value with no documented source.

#### `test_signature_preserves_through_migration`
Setup: V4-A vault signature X. Migrate. Assertion: V4-B Climb.signature == X byte-for-byte; Climb PDA derivation with X produces same address as expected; signature_hash == SHA256(signature) still holds.

#### `test_kom_preserves_through_migration`
Setup: V4-A vault with kom_holder = pubkey_Y, kom_time_s = 450, kom_set_epoch = 200. Migrate. Assertion: V4-B Climb.kom_holder == pubkey_Y, kom_time_s == 450, kom_set_at == expected ride_time translated from kom_set_epoch (or preserved directly if migration stores both).

#### `test_record_board_preserves_through_migration`
Setup: V4-A VaultLeaderboard with 10 entries at (rider_i, time_i, set_at_i). Migrate + fold. Assertion: V4-B Climb.record_board[0..10] contains the same 10 entries with same (rider, time, completed_at). Rank order preserved.

#### `test_per_bucket_carry_preserves_through_migration`
Setup: a policy-marked V4-A vault with carry_record_royalty = X1, carry_stakers = X2, carry_local_legend = X3, carry_pol = X4, carry_treasury = X5. Migrate. Assertion: V4-B Vault has identical carry values and preserves the marker. An unmarked legacy Vault must complete the explicit staker-carry cutover before V4-B migration. **Critical** — any unclassified or cross-bucket leakage here poisons all future settlements.

#### `test_migration_is_idempotent`
Setup: run migration twice on same V4-A vault. Assertion: second run is a no-op, doesn't corrupt state, returns a "already migrated" signal. (Protects against walker-script resume after partial failure.)

#### `test_local_legend_preserves_through_migration`
Setup: V4-A LocalLegend PDA with holder = H, term_start = S, term_end = E, total_earned = T, bootstrap = B. Migrate. Assertion: V4-B LocalLegend PDA unchanged (assuming seed derivation does not depend on reshaped Vault size).

---

## 7. Proposed Rollout Verification Checklist

Before hard cutover of `record_vault_completion` → `record_climb_completion`
(and the full V4-B surface) on devnet:

- [ ] New instruction `record_climb_completion` exists on deployed program and is callable from backend tx builder.
- [ ] Backend ride execution emits `record_ride` → `record_climb_completion` → `credit_cal` for every new ride upload, not the V4-A path.
- [ ] Old instruction `record_vault_completion` is removed from the program or fails closed for every caller; there is no admin replay exception.
- [ ] Merkle pipeline is deleted from program source, from backend services (`cal_allocator.py`, `allocation_batch_submitter.py`, `claim_executor.py`, `merkle_proof.py`), and from indexer writers.
- [ ] New instruction works for at least **one full settlement week on devnet** — found_climb → record_ride → record_climb_completion → credit_cal → stake_cal_in_vault → advance 2 epochs → finalize_legend_election → finalize_settlement_week → harvest. End-to-end.
- [ ] Indexer consumes new events (`RideAttestationRecorded`, `ClimbCompleted`, `RecordRoyaltyPayout`, `StakerAllocation`, `LegendPayout`, `SettlementWeekFinalized`) and populates projection tables without drift. Verify via SQL count: N events in = N rows out.
- [ ] Portal renders new Climb names correctly (not "Vault 0" or "Vault 12"). Verify via BoulderScan visual check.
- [ ] Mobile renders new Climb names correctly. Verify via device build + manual screen walk.
- [ ] Old indexed tables (`indexed_vaults`, `vault_leaderboards`, `distribution_receipts`) are either dropped or marked read-only-legacy, with the V4-B projection tables as canonical.
- [ ] Test harness runs V4-A-oracle-vs-V4-B comparison for N ≥ 100 rides — econ regression test (§5) expanded to a batched form, with all 100 producing matching bucket amounts. Any mismatch blocks cutover.
- [ ] Anchor test suite ≥ 60 passing on V4-B.
- [ ] Gate 1 smoke (`smoke_devnet_economics.py` V4-B version) green.
- [ ] Gate 2 smoke (`smoke_full_stack.py`) green.
- [ ] All hardcoded references to V4-A program ID `37odBJvV…` grep-clean from backend, indexer, portal, mobile, and scripts.
- [ ] `addresses.devnet.json` updated with V4-B program ID and comment noting "V4-B Climb-first, supersedes V4-A 37odBJvV…" (per Tim's one request in PROTOCOL_AGENT_RETURN_BRIEF).
- [ ] Mobile + portal env vars flipped to V4-B.
- [ ] Rollback plan rehearsed: env var flip back to V4-A tested on a staging clone of the droplet.
- [ ] Runbook for "V4-B bug discovered N days post-cutover" documented and linked from CLAUDE.md.

---

## 8. Open Questions for Tim

1. **Option A vs Option B.** This doc stays neutral. Protocol agent lean (if thaw happens) + Tim signoff required. Research-author non-binding lean: Option A.

2. **Naming collision on `record_climb_completion`.** V4-A already has an instruction named `record_climb_completion` (landed as part of the partial V4-B scaffolding). It accepts RideAttestation + vault (not yet split). Options:
   - (a) V4-B keeps the name; semantics change from "vault completion keyed by attestation" to "climb completion keyed by attestation and resolved to vault via Climb.vault pointer." IDL breaks.
   - (b) V4-B uses a different name (`settle_climb_completion`, `apply_climb_completion`, etc) to keep V4-A clients partially functional during transition.
   - **Recommended:** (a) for clean IDL, consistent with PROTOCOL_ALIGNMENT_FIX_PLAN P15. Tim confirm.

3. **What happens to the 16 V4-A vaults?** Decision #2 says clean slate. Does Phase B demo want to point at V4-A vaults (with a compat shim) for the hackathon demo narrative? If yes, we need a one-way-read shim in BoulderScan that queries both programs. If no, fresh V4-B state + demo reseeding is needed.

4. **Canonicalization spec (WS-10).** PROTOCOL_ALIGNMENT_FIX_PLAN says WS-10 must land before V4-B implementation. It exists at `docs/design/RIDE_CANONICALIZATION_SPEC.md`. Is that doc complete enough to freeze, or does protocol agent want another pass? If not complete, V4-B ride_hash may end up with a canonicalization that later changes, invalidating all V4-B RideAttestation PDAs.

5. **Staker unlock curve preservation.** `STAKER_UNLOCK_PCTS = [1, 3, 6, 11, 17, 25, 35, 50, 70, 100]` is unchanged by TRUTHS. Confirm V4-B keeps these exact values. (Research assumes yes.)

6. **Econ regression oracle snapshots count.** §5 proposes N=3. Is that sufficient for Tim's comfort? N=10+ would require admin-seeding cases that don't exist on V4-A devnet history.

7. **Mint authority continuity.** Reuse V4-A CAL (`9ez2FMBrfAap…`) + DUNG (`33HgZWeqDbGY…`) mints with authority transfer to V4-B mint-auth PDAs, or deploy fresh mints? Fresh mints are cleaner but require all downstream consumers (portal wallet displays, mobile balance reads, BoulderScan) to flip their mint addresses too. Research assumes reuse with transfer.

8. **VaultStake migration (Option B only).** If Option B: existing V4-A stakers have VaultStake accounts under V4-A shape. Do those accounts need re-init under V4-B's `effective_from_epoch`-based shape? If stakers are on devnet test accounts (likely), just close them and ask stakers to re-stake. If real: need in-place conversion. Tim confirm.

9. **Hard rename scope in Option B.** If Option B, IDL has to support both old and new account names during transition. How many transition days? If this is hackathon timeline: zero transition days, rename atomic. If this is post-hackathon: 2-week transition window for downstream consumers. Research assumes Option A makes this question moot.

10. **`VaultUserEpochStats` provisional account.** PROTOCOL_ALIGNMENT_FIX_PLAN WS-6 introduces this for Legend election. Not yet in V4-A code. Does V4-B deploy include it, or is it a follow-on (Phase 3)? If follow-on, Legend election uses indexer-side backend derivation rather than chain-native. Impacts §3 test "test_local_legend_based_on_recent_completions" — assertion source changes.

11. **Founder Legend-bootstrap preservation.** Does V4-B found_climb automatically create the 8-epoch bootstrap LocalLegend for the founder (per P16 / existing V4-A behavior)? Or is that a separate `bootstrap_founder_legend` instruction? §6 test "test_founder_gets_first_legend_bootstrap" assumes the former.

---

## Appendix A — PROTOCOL_TRUTHS section citation map for tests

Every test in §3 carries an explicit PROTOCOL_TRUTHS section in parentheses.
Quick reference:

- §2.1 Climb permanence — 2 tests
- §2.2 Vault optional / attached — 3 tests
- §2.3 Ride attestation immutability — 2 tests
- §3.1 Permanent truth — 4 tests
- §3.2 Rolling truth — 1 test
- §3.3 Settled truth — 2 tests
- §4 Epoch = settlement clock — 2 tests
- §5.1 On-chain binding state — 1 test
- §5.2 Attested truth (off-chain) — 1 test
- §6.1 Founder — 3 tests
- §6.2 KOM — 4 tests
- §6.3 Record Board — 2 tests
- §6.4 Local Legend — 2 tests
- §6.5 Staker — 1 test
- §7.1 CAL transferable — 3 tests
- §7.2 DUNG rewards — 1 test
- §7.3 RiderSoul non-transferable — 2 tests
- §8 Economic buckets — 7 tests
- §9 Quiet climbs / per-bucket carry — 4 tests
- §10 Privacy boundary — 1 test

**Total: 48 TRUTHS-anchored test fixtures** specified.

Plus:
- §4 porting table: ~10 passes, ~5 renames, ~8 field adds, ~10 rewrites, ~40 retires.
- §5 econ regression: 1 parameterized oracle comparison test (minimum N=3 cases).
- §6 migration verification: 9 tests (Option B only).

Grand total if all implemented: **~95 tests** post-V4-B. Target ≥60 per FIX_PLAN easily exceeded.

---

## Appendix B — Files the executor will touch

Derived from PROTOCOL_ALIGNMENT_FIX_PLAN Appendix A, filtered to V4-B scope only:

**Rust/Anchor:**
- `protocol/anchor/programs/boulder_rollers/src/lib.rs` — split Vault into Climb + Vault; delete Merkle path; rename `distribute_epoch_rewards` → `finalize_settlement_week`; add `found_climb` + `attach_vault`; clean up legacy Synthetix fields; introduce `VaultUserEpochStats` (pending Tim decision on Open Q 10).
- `protocol/anchor/idl/boulder_rollers.json` — regenerated.
- `protocol/anchor/Anchor.toml` — Option A: new program ID. Option B: unchanged.
- `protocol/anchor/addresses.devnet.json` — Option A: new program ID + comment. Option B: unchanged.
- `protocol/anchor/tests/*.spec.ts` — per §4 porting inventory.
- `protocol/anchor/scripts/deploy_v4b.ts` — NEW (Option A).
- `protocol/anchor/scripts/seed_v4b_state.ts` — NEW (Option A).
- `protocol/anchor/scripts/migrate_existing_vaults_v4b.ts` — NEW commented template (Option A).
- `protocol/anchor/scripts/realloc_program_config_v4b.ts` — NEW (Option B).
- `protocol/anchor/scripts/realloc_and_split_vaults_v4b.ts` — NEW (Option B).
- `protocol/anchor/scripts/fold_leaderboards_v4b.ts` — NEW (Option B).

**Python backend:** per PROTOCOL_ALIGNMENT_FIX_PLAN Appendix A — `solana_direct.py`, `solana_env.py`, `ride_processor.py`, `epoch_processor.py`, `legend_stewardship_service.py`, DELETE `cal_allocator.py` / `allocation_batch_submitter.py` / `claim_executor.py` / `merkle_proof.py`, `tx_builder.py`, `routes/climbs.py` (already exists — wire to V4-B accounts), `repositories/vault.py` (rename to `climb.py`), `scripts/smoke_devnet_economics.py` (rewrite), `scripts/smoke_full_stack.py` (NEW).

**TypeScript indexer:** `config.ts`, `decoder.ts`, `writers/` (new writers for Climb and attested events), `modes/snapshot.ts`, `reconciliation.ts`.

**SQL migrations:** drop `distribution_receipts`, archive `cal_allocation_staging/batches/leaves`, add `indexed_climbs`, `indexed_ride_attestations`, `indexed_climb_completions`, `indexed_record_royalty_payouts`, `indexed_staker_allocations`, `indexed_legend_payouts`, `indexed_settlement_week_finalizations`, `indexed_rider_souls`, `indexed_vault_user_epoch_stats` (pending Q 10).

**Docs:** `CLAUDE.md` (key flows rewrite), `docs/FRESHEST_SPEC.md` (V4-B alignment), `docs/design/PROTOCOL_ALIGNMENT_FIX_PLAN.md` (update execution status).

---

**End of plan.** Execution-ready. Protocol agent on return should find the decision space pre-collapsed to a single Tim choice (Option A vs Option B) and all downstream scripting + testing + rollout scaffolded. Every test fixture traces to a PROTOCOL_TRUTHS section by explicit citation. Every migration script outline enumerates inputs / outputs / preconditions / failure modes.
