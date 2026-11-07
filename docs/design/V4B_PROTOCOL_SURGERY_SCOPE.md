# V4-B Protocol Surgery Scope — `Vault` → `Climb` + `Vault` Split

**Status:** RESEARCH / SURGICAL MAP
**Date:** 2026-04-17
**LRWD addendum:** 2026-07-14. Lifetime tribute and the fail-closed legacy completion shell supersede the reward-field and instruction notes called out below.
**8346 addendum:** 2026-07-14. Tribute-unbound
`record_climb_completion` V1 also fails closed. The live V2 receipt binds exact
tribute at the same PDA with a distinct discriminator; the Climb/Vault split
must preserve that invariant.
**Audience:** Whoever executes `0uv8` — protocol agent on thaw (≈Apr 22), or mobile/backend agent with scaffolding-only authorization pending Tim's decision
**Author:** Mobile/backend agent acting as dispatcher during protocol-agent freeze
**Scope:** Research only. No code edits. No deploy/realloc plan. No full consumer inventory across backend/mobile (sibling agents own that).

**Anchoring decisions (locked, binding):**
- **D1:** `Climb { vault: Option<Pubkey> }` — Option A. Primary object holds pointer to optional attachment.
  (`docs/design/WWPTD_EPIC_PORTFOLIO_2026-04-17.md` §D1, PROTOCOL_TRUTHS §2.2.)
- **D2–D4:** TRUTHS trio ratified; M2 BLE full scope; backend Phase A unilateral.
- **P1, P10, P11, P15:** Climb-first, per-bucket carry preserved, on-chain auditable without indexer, hard rename on IDL-visible surface.
  (`docs/design/PROTOCOL_ALIGNMENT_FIX_PLAN.md` §Principles.)

**What the executor wants from this doc:** a field-by-field, instruction-by-instruction, event-by-event map they can walk down without having to re-derive scope from TRUTHS. Every number here is grounded in `protocol/anchor/programs/boulder_rollers/src/lib.rs` (5342 LOC, commit on `main` as of 2026-04-17, V4-A program ID `HsPhhMukUKu641e9hDJUJJW4chvF5EXYzuG2xBwMrnst`).

---

## Section Index

1. Current `Vault` struct audit — field-by-field categorization
2. Proposed `Climb` struct shape
3. Proposed retained `Vault` struct
4. Instruction-level changes (every instruction in the program)
5. Event-level changes (every `#[event]` in the program)
6. Account realloc math
7. D1 design consequences (hot-path access patterns, legacy handling)
8. Scope boundary with `wdvr.8` (cleanup + canonical naming)
9. Open questions for Tim

---

## 1. Current `Vault` struct audit

Source: `protocol/anchor/programs/boulder_rollers/src/lib.rs` lines 2986–3089 (`pub struct Vault` + `impl Vault::SIZE`).

Total current size: **413 bytes** (per `Vault::SIZE` at lib.rs:3052–3089; `8 disc + 8 + 64 + 32 + 32 + 8 + 8 + 32 + 4 + 8 + 64 + 46 + 128 + 8×15 + 4×2 + 4 + 2 + 8 + 1`).

| # | Field (current `Vault`) | Size | Category | Post-split home | Notes |
|---|---|---|---|---|---|
| 1 | `id: u64` | 8 | Ambiguous | **Vault** | Auto-increment counter surface. Climb identity is the 64-byte signature (per TRUTHS §2.1). Keeping `id` on Vault preserves VaultCounter seed compatibility, but see §9 Open Q1. |
| 2 | `signature: [u8; 64]` | 64 | Climb identity | **Climb** | Canonical climb identity per TRUTHS §2.1. Immutable. Source of `signature_hash`. |
| 3 | `signature_hash: [u8; 32]` | 32 | Climb identity | **Climb** | SHA256(signature), used for indexing. Derives from #2. |
| 4 | `minter: Pubkey` | 32 | Climb identity | **Climb** (renamed `founder`) | P1 + FIX_PLAN rename: `minter` → `founder` (founder provenance is climb-permanent, per TRUTHS §6.1). |
| 5 | `mint_epoch: u64` | 8 | Climb identity | **Climb** (renamed `founded_at_epoch` or drop) | "Epoch when minted" — but TRUTHS §4 says epoch is settlement clock, not ontology. FIX_PLAN replaces with `founded_at: i64` (ride-time or chain-time) and `founded_ride_attestation: Pubkey`. See §9 Q2. |
| 6 | `rights_expires_epoch: u64` | 8 | Ambiguous | **Climb** (under review) | Controls metadata-edit rights via `Vault::rights_holder()` (lib.rs:3120). Semantics survive Climb/Vault split, but rights-period concept is Vault-era (minter as provisional curator); TRUTHS hands long-term curation to Local Legend. See §9 Q3. |
| 7 | `kom_holder: Pubkey` | 32 | Climb identity (permanent) | **Climb** | TRUTHS §6.2: KOM is permanent record truth. Never expires until dethroned. |
| 8 | `kom_time_s: u32` | 4 | Climb identity (permanent) | **Climb** | Permanent KOM best time. |
| 9 | `kom_set_epoch: u64` | 8 | Climb identity | **Climb** (rename to `kom_set_at: i64` per FIX_PLAN) | FIX_PLAN line 324 changes this to `kom_set_at: i64` (ride-time) + adds `kom_ride_attestation: Pubkey` (traceable proof per P5/P6). |
| 10 | `name: [u8; 64]` | 64 | Climb identity | **Climb** | Display name. |
| 11 | `avatar_ipfs: [u8; 46]` | 46 | Climb identity | **Climb** | IPFS CID for avatar. |
| 12 | `slogan: [u8; 128]` | 128 | Climb identity | **Climb** | Short tagline. |
| 13 | `cal_tribute_accumulated: u64` | 8 | Economic state | **Vault** | CAL dust for the current open settlement week. Per TRUTHS §5.1, on-chain economic state. |
| 14 | `cal_tribute_accumulated_next: u64` | 8 | Economic state | **Vault** | CAL dust staged for next settlement week (P10 per-bucket carry machinery). |
| 15 | `total_cal_burned: u64` | 8 | Lifetime metric | **Climb** (see §9 Q4) | "Lifetime CAL burned" on climb — TRUTHS §3.1 lifetime CAL committed to a climb is permanent truth. But it flows through Vault economics. Putting it on Climb matches TRUTHS; on Vault matches operational flow. FIX_PLAN line 332 puts `total_cal_committed` on Climb. |
| 16 | `total_dung_emitted: u64` | 8 | Lifetime metric | **Climb** | FIX_PLAN line 333 `total_dung_distributed` on Climb. Permanent aggregate of what the climb has paid out. |
| 17 | `total_completions: u64` | 8 | Climb identity (lifetime) | **Climb** | Number of times the climb has been ridden. Permanent lifetime metric per TRUTHS §3.1. |
| 18 | `total_cal_staked: u64` | 8 | Economic state | **Vault** | Principal staked in the economic module. Vault-only. |
| 19 | `staker_count: u32` | 4 | Economic state | **Vault** | Unique active stakers (unlock curve). Vault-only. |
| 20 | `reward_per_token_stored: u64` | 8 | **Dormant Synthetix** | **RETIRE** | Explicitly dormant per lib.rs:3019 "Legacy Synthetix fields (deprecated)". P8 abandoned Synthetix. Retire in this pass. |
| 21 | `last_update_time: i64` | 8 | **Dormant Synthetix** | **RETIRE** | Same. |
| 22 | `reward_rate: u64` | 8 | **Dormant Synthetix** | **RETIRE** | Same. |
| 23 | `pending_rewards: u64` | 8 | Economic state | **Vault** | DUNG staged for current open settlement week. Vault-only. |
| 24 | `pending_rewards_next_week: u64` | 8 | Economic state | **Vault** | DUNG staged for next settlement week. Vault-only. |
| 25 | `open_settlement_week: u64` | 8 | Settlement clock | **Vault** | Oldest unsettled week. P4: settlement clock lives on the economic module. |
| 26 | `carry_record_royalty: u64` | 8 | Settlement clock / P10 | **Vault** | Per-bucket carry (P10). Vault-only. |
| 27 | `carry_stakers: u64` | 8 | P10 carry | **Vault** | Per-bucket carry (P10). |
| 28 | `carry_local_legend: u64` | 8 | P10 carry | **Vault** | Per-bucket carry (P10). |
| 29 | `carry_pol: u64` | 8 | P10 carry | **Vault** | Per-bucket carry (P10). |
| 30 | `carry_treasury: u64` | 8 | P10 carry | **Vault** | Per-bucket carry (P10). |
| 31 | `total_staked: u64` | 8 | **Dormant legacy** | **RETIRE** | Marked DEPRECATED in lib.rs:3037 ("was DUNG staked, now unused"). Retire. |
| 32 | `last_distribution_epoch: u64` | 8 | Settlement clock | **Vault** (renamed `last_finalized_epoch` per FIX_PLAN L369/L510) | P15 hard rename. |
| 33 | `vert_m: u32` | 4 | Climb identity (geography) | **Climb** | Immutable climb geography. |
| 34 | `distance_m: u32` | 4 | Climb identity (geography) | **Climb** | Immutable. |
| 35 | `avg_gradient_pct: u16` | 2 | Climb identity (geography) | **Climb** | Immutable. |
| 36 | `created_at: i64` | 8 | Ambiguous | **Climb** | Creation timestamp — belongs to the permanent object. Rename in step with FIX_PLAN `founded_at: i64`. |
| 37 | `bump: u8` | 1 | Infra | **Both** | Each account has its own bump. |

**Summary of categories:**
- Climb identity: 17 fields, **398 bytes** (plus discriminator) → migrate to new Climb account
- Economic state (Vault): 8 fields, **56 bytes** (current-week inflow + staking state)
- Settlement clock / P10 carry (Vault): 7 fields, **56 bytes**
- **Retire (dormant Synthetix + legacy):** 4 fields, **32 bytes** reclaimed
- Ambiguous (flagged for Tim): `id`, `rights_expires_epoch`, `mint_epoch`/`founded_at` semantics

### Canonical reward/economics projection inventory

For V3/V4 explorer and indexer surfaces, the canonical active Vault reward fields are:

| Surface | Canonical fields | Status |
|---|---|---|
| Open-flow reward staging | `pending_rewards` | Active DUNG in the oldest open lifetime tribute flow. |
| Legacy next-week reward staging | `pending_rewards_next_week` | Deprecated layout field after LRWD; no new completion writes, and normal rollover drains existing values into the open flow. |
| Settlement clock | `open_settlement_week`, `last_distribution_epoch` | Active on the Vault economic module. |
| Per-bucket carry | `carry_record_royalty`, `carry_stakers`, `carry_local_legend`, `carry_pol`, `carry_treasury` | Active P10 carry buckets; explorer totals are derived by summing these fields when no nested economy object is provided. |
| Staking state | `total_cal_staked`, `staker_count` | Active Vault state used for sorting and economic context. |
| Lifetime economics | `cal_tribute_accumulated`, `cal_tribute_accumulated_next`, `total_cal_burned`, `total_dung_emitted` | `cal_tribute_accumulated` is the sub-DUNG remainder in the oldest open lifetime flow. The `_next` field is deprecated and only drains legacy state. Lifetime totals remain active aggregate/projection fields. |

The dormant Synthetix fields `reward_per_token_stored`, `last_update_time`, and `reward_rate` are retained only where legacy account/table compatibility still requires decoding or storage. They are not active protocol economics and must not be rendered as live reward state in BoulderScan.

---

## 2. Proposed `Climb` struct shape

Following D1 (`Climb { vault: Option<Pubkey> }`) + TRUTHS §2.1 + FIX_PLAN lines 304–338 target-state.

### PDA seed derivation

TRUTHS §2.1: Climb is identified by the 64-byte canonical signature. Best option for Climb PDA:

**Recommended:** `[CLIMB_SEED, &signature_hash]` where `signature_hash = SHA256(signature)` (32 bytes).

**Rationale:** The raw 64-byte signature exceeds the 32-byte seed slice convention used elsewhere (vault seed uses 8-byte `id`). `signature_hash` is deterministic and already stored on Vault today. Downstream consumers (backend `climb` routes) index on `signature_hex` — that alias works identically against `signature_hash_hex`.

**Alternative:** `[CLIMB_SEED, &climb_id.to_le_bytes()]` mirroring VaultCounter pattern. Preserves monotonic id but decouples PDA from identity. See §9 Q1.

**New seed constant to add:** `pub const CLIMB_SEED: &[u8] = b"climb";`

### Field layout

```rust
/// A permanent geographic climb object.
/// PDA: [CLIMB_SEED, &signature_hash]   (or [CLIMB_SEED, &climb_id.to_le_bytes()] — see §9 Q1)
#[account]
pub struct Climb {
    // --- Identity (immutable, climb-permanent) ---
    pub signature: [u8; 64],           // canonical climb identity
    pub signature_hash: [u8; 32],      // SHA256(signature), PDA seed

    pub founder: Pubkey,               // former `minter`, P15 hard rename
    pub founded_at: i64,               // ride-time of first KOM attempt (P6)
    pub founded_ride_attestation: Pubkey, // traceable proof (P5)

    // --- Immutable geography ---
    pub vert_m: u32,
    pub distance_m: u32,
    pub avg_gradient_pct: u16,

    // --- Metadata (founder-editable while rights active, then Local Legend) ---
    pub name: [u8; 64],
    pub avatar_ipfs: [u8; 46],
    pub slogan: [u8; 128],
    pub rights_expires_epoch: u64,     // keep if we keep the minter-rights concept (see §9 Q3)

    // --- Permanent KOM (TRUTHS §6.2) ---
    pub kom_holder: Pubkey,
    pub kom_time_s: u32,
    pub kom_set_at: i64,               // ride-time (P6), former `kom_set_epoch`
    pub kom_ride_attestation: Pubkey,  // P5 traceability

    // --- Lifetime metrics (monotonic, permanent truth per TRUTHS §3.1) ---
    pub total_completions: u64,
    pub total_cal_committed: u64,      // former `total_cal_burned`
    pub total_dung_distributed: u64,   // former `total_dung_emitted`

    // --- D1: optional economic attachment ---
    pub vault: Option<Pubkey>,         // Some(vault_pda) if Vault attached

    pub bump: u8,
}
```

**Not included here** (FIX_PLAN carries these but they escalate scope beyond the split):
- `record_board: [RecordBoardEntry; 10]` — subsumes today's `VaultLeaderboard` account. **This is a separate surgery** (see §9 Q5). Scoping strict V→C+V split leaves `VaultLeaderboard` unchanged and renames the PDA seed / IDL-visible name separately. Protocol agent to decide whether to fold Record Board into Climb in the same pass.

### Byte sizes

| Chunk | Bytes |
|---|---|
| discriminator | 8 |
| signature | 64 |
| signature_hash | 32 |
| founder | 32 |
| founded_at | 8 |
| founded_ride_attestation | 32 |
| vert_m | 4 |
| distance_m | 4 |
| avg_gradient_pct | 2 |
| name | 64 |
| avatar_ipfs | 46 |
| slogan | 128 |
| rights_expires_epoch | 8 |
| kom_holder | 32 |
| kom_time_s | 4 |
| kom_set_at | 8 |
| kom_ride_attestation | 32 |
| total_completions | 8 |
| total_cal_committed | 8 |
| total_dung_distributed | 8 |
| vault (Option<Pubkey>) | 1 + 32 = 33 |
| bump | 1 |
| **Total** | **566 bytes** |

Rent reservation at current devnet rent (~0.00000348 SOL/byte/year proportional; rent-exempt = ~0.00203928 SOL + per-byte term): **~0.00408 SOL per Climb** for rent exemption (match-order with current Vault, see §6).

### Owner / authority / mutability

- Owner: `boulder_rollers` program (Anchor `#[account]` default).
- `founder` has edit authority on metadata until `rights_expires_epoch`; thereafter the active Local Legend does (same pattern as current `Vault::rights_holder()` at lib.rs:3120).
- `vault: Option<Pubkey>` is mutated once by `attach_vault` (new instruction, see §4) from `None` → `Some(vault_pda)`. Detach is out of scope unless Tim directs.

### Does it replace anything else?

- **Additive relative to current Vault** — most climb-identity fields move from Vault to Climb.
- `UserState` → `RiderSoul` is a parallel migration (P12/WS-9 in FIX_PLAN), not in this doc's scope.
- `VaultLeaderboard` may or may not fold into Climb depending on §9 Q5.

---

## 3. Proposed retained `Vault` struct

After the split, Vault is an optional economic module attached to a Climb. Per TRUTHS §2.2 and FIX_PLAN lines 347–373.

### PDA seed

Keep `[VAULT_SEED, &vault_id.to_le_bytes()]` — preserves VaultCounter pattern and keeps realloc-less addressability for VaultStake/VaultCompletion PDAs which also use `vault_id`.

Alternative: `[VAULT_SEED, climb_pda.as_ref()]` — more TRUTHS-pure (Vault is *the* Vault of this Climb), but breaks existing seed discipline. See §9 Q6.

### Field layout

```rust
/// Optional economic module attached to a Climb. One-to-one.
/// PDA: [VAULT_SEED, &vault_id.to_le_bytes()]
#[account]
pub struct Vault {
    // --- Identity linkage ---
    pub id: u64,                       // preserved for PDA compatibility
    pub climb: Pubkey,                 // required parent Climb PDA

    // --- Current-week inflow (P10 per-bucket machinery) ---
    pub cal_tribute_accumulated: u64,
    pub cal_tribute_accumulated_next: u64,
    pub pending_rewards: u64,
    pub pending_rewards_next_week: u64,

    // --- Settlement clock (P4) ---
    pub open_settlement_week: u64,
    pub last_finalized_epoch: u64,     // renamed from last_distribution_epoch (P15)

    // --- Per-bucket carry (P10 — bucket identity preserved) ---
    pub carry_record_royalty: u64,
    pub carry_stakers: u64,
    pub carry_local_legend: u64,
    pub carry_pol: u64,
    pub carry_treasury: u64,

    // --- Staking state ---
    pub total_cal_staked: u64,
    pub staker_count: u32,
    pub eligible_staker_count: u32,    // P9 — count of stakers ≥2 full epochs active

    pub created_at: i64,               // vault attachment time (distinct from climb founded_at)
    pub bump: u8,
}
```

### Full-epoch eligibility state

Preserved. `eligible_staker_count: u32` is added as explicit state per P9; `VaultStake.eligible_from_epoch` remains on the stake account (unchanged from current lib.rs:3300).

### Per-bucket carry state

Preserved in full — five fields, one per bucket, per P10.

### Dormant fields retired in this pass

- `reward_per_token_stored: u64` (Synthetix residue) — **RETIRE**
- `last_update_time: i64` (Synthetix residue) — **RETIRE**
- `reward_rate: u64` (Synthetix residue) — **RETIRE**
- `total_staked: u64` (explicitly DEPRECATED at lib.rs:3037) — **RETIRE**
- `minter` / `mint_epoch` / `rights_expires_epoch` — **MOVE to Climb** (founder + rights-period are climb-permanent, not economic)
- `signature` / `signature_hash` / `kom_*` / `name` / `avatar_ipfs` / `slogan` / `vert_m` / `distance_m` / `avg_gradient_pct` — **MOVE to Climb**

### Byte sizes

| Chunk | Bytes |
|---|---|
| discriminator | 8 |
| id | 8 |
| climb | 32 |
| cal_tribute_accumulated | 8 |
| cal_tribute_accumulated_next | 8 |
| pending_rewards | 8 |
| pending_rewards_next_week | 8 |
| open_settlement_week | 8 |
| last_finalized_epoch | 8 |
| carry_record_royalty | 8 |
| carry_stakers | 8 |
| carry_local_legend | 8 |
| carry_pol | 8 |
| carry_treasury | 8 |
| total_cal_staked | 8 |
| staker_count | 4 |
| eligible_staker_count | 4 |
| created_at | 8 |
| bump | 1 |
| **Total** | **161 bytes** |

---

## 4. Instruction-level changes

Source: every `pub fn` inside `#[program] mod boulder_rollers` in lib.rs. Grouped by category. The table includes new instructions introduced by the split.

**Legend for columns:**
- **Shape change:** Does the instruction's account context add/remove accounts?
- **Rename:** P15 hard rename in IDL-visible surface.
- **Retire:** Instruction deleted or superseded.
- **Climb param:** Gains a Climb PDA in its account context.
- **Backend callsites:** Lines in `backend/app/solana_direct.py` that construct/send this ix.

### 4.1 Program init / config (lib.rs lines 155–356)

| Line | Instruction | Shape | Rename | Retire | Climb param | Backend callsites |
|---|---|---|---|---|---|---|
| 155 | `initialize_user` | No | No (may fold into `initialize_rider_soul` — WS-9, out of 0uv8 scope) | No | No | N/A (client-initiated) |
| 170 | `admin_initialize_user` | No | (see above) | No | No | not used for split |
| 186 | `initialize_program_config` | No | No | No | No | one-time setup |
| 210 | `update_program_config` | No | No | No | No | ops script |
| 236 | `migrate_program_config` | No | No | **Retire** (V2 → V4-B is clean slate per Decision #1–#2) | No | `migrate_program_config_*` paths |
| 251 | `migrate_program_config_v3` | No | No | **Retire** | No | same |
| 298 | `configure_mints` | No | No | No | No | one-time |
| 333 | `configure_treasury_accounts` | No | No | No | No | one-time |
| 353 | `initialize_vault_cal_escrow` | No | No | No | Yes (optional: ATA is per-Vault today; stays per-Vault) | |

### 4.2 CAL / Ride attestation (lib.rs lines 360–526)

| Line | Instruction | Shape | Rename | Retire | Climb param | Backend callsites |
|---|---|---|---|---|---|---|
| 360 | `admin_credit_cal` | No | No | No | No | `solana_direct.py:1479–1549` |
| 384 | `admin_mint_cal` | No | No (already legacy alias) | No | No | not directly used |
| 389 | `record_ride` | No | No | No | No (ride-level, not climb-level) | `solana_direct.py:1552–1655` |
| 484 | `credit_cal` | No | No | No | No | `solana_direct.py:1660–1751` |

These are already aligned with TRUTHS §5.2 + P5. Leave as-is.

### 4.3 Climb completion (lib.rs line 531)

| Line | Instruction | Shape | Rename | Retire | Climb param | Backend callsites |
|---|---|---|---|---|---|---|
| 531 | `record_climb_completion` | **YES — add Climb PDA** | No (already canonical name) | No | **YES** | `solana_direct.py:1756–1844` |
| 1270 | `record_vault_completion` | N/A | — | **Retire** (was the pre-V4-A name; `record_climb_completion` at line 531 is the canonical replacement) | — | `solana_direct.py:1358–1476` (legacy path; purge as part of split) |

**Current context** `RecordClimbCompletion` (lib.rs:3720) already takes Vault, VaultCompletion, VaultLeaderboard, RideAttestation. **Split requires** adding the Climb PDA as a new required account (mutated for KOM update + lifetime metrics). The instruction body currently mutates Vault fields like `kom_holder`, `kom_time_s`, `kom_set_epoch`, `total_completions`, `total_cal_burned` (lib.rs:576–609) — all of these move to Climb after the split. Instruction body rewrites accordingly.

**`record_vault_completion` (historical line 1270) is a vestigial pre-V4-A compatibility surface. After LRWD it fails closed before any Vault mutation or event; delete the ABI shell as part of `0uv8` after clients migrate.**

### 4.4 Beetle Card (lib.rs lines 640–849)

| Line | Instruction | Shape | Rename | Retire | Climb param | Backend callsites |
|---|---|---|---|---|---|---|
| 640 | `initialize_beetle_card` | No | No | No | No | backend |
| 687 | `increment_beetle_score` | No | No | No | No | backend |
| 727 | `get_beetle_card_stats` | No | No | No | No | read-only helper |
| 759 | `upgrade_beetle_card` | No | No | No | No | user-initiated |
| 827 | `get_upgrade_cost` | No | No | No | No | read-only |

Unaffected by Climb/Vault split. BeetleCard migration ties to RiderSoul (WS-9), separate work.

### 4.5 Vault / Climb creation (lib.rs lines 856–1265)

| Line | Instruction | Shape | Rename | Retire | Climb param | Backend callsites |
|---|---|---|---|---|---|---|
| 856 | `initialize_vault_counter` | No | No | No | No | one-time |
| 866 | `create_vault` | **YES — becomes 2-instruction flow** | **`found_climb` + `attach_vault`** | **Retire** (replaced by split) | New ix creates Climb | `solana_direct.py:2680–3001` |
| 1003 | `admin_create_vault` | **YES** | Replaced by `admin_found_climb` + `admin_attach_vault` | **Retire** | Yes | `solana_direct.py:2796–3101` |
| 1123 | `create_vault_with_usdc` | **YES** | Replaced by `found_climb_with_usdc` + `attach_vault` | **Retire** | Yes | `solana_direct.py:2746–2794` |

**Two new instructions** (per FIX_PLAN lines 467–468, aligned with D1):

- `found_climb(signature, name, vert_m, distance_m, avg_gradient_pct, [founded_at, founded_ride_attestation])` — creates Climb account, sets founder, registers geography and KOM-pending state. Does NOT create a Vault. Climb exists standalone with `vault: None`.
- `attach_vault(climb, economic_config, payment_method)` — creates the Vault PDA, sets `climb = climb_pda`, mutates Climb's `vault: Option<Pubkey>` from `None` → `Some(vault_pda)`. Preserves the three payment surfaces (DUNG-burn, CAL+USDC, admin-free) via an enum or parallel instructions.

**Backend impact:** every `send_create_vault*` path in `solana_direct.py` splits into `send_found_climb` + `send_attach_vault`. Backend orchestrates the two as an atomic pair during initial climb founding. Indexer picks up both events.

### 4.6 Staking + settlement (lib.rs lines 1361–1779)

| Line | Instruction | Shape | Rename | Retire | Climb param | Backend callsites |
|---|---|---|---|---|---|---|
| 1361 | `initialize_vault_lp_mint` | No | No | No | No | one-time per vault |
| 1372 | `stake_cal_in_vault` | Add optional Climb read-through for D1 check | No | No | **Advisory** (stake mutates Vault, Climb not mutated) | `solana_direct.py:2099–2392` |
| 1477 | `unstake_cal_from_vault` | No | No | No | No | `solana_direct.py:2133–2433` |
| 1592 | `harvest_rewards` | No | No | No | No | `solana_direct.py:2165–2553` |
| 1673 | `update_vault_metadata` | **YES — moves to Climb** | Rename to `update_climb_metadata`; account context changes from Vault → Climb | No | N/A — operates on Climb | none mapped in solana_direct yet |
| 1729 | `initialize_dung_mint_state` | No | No | No | No | one-time |
| 1752 | `apply_halving` | No | No | No | No | admin |

**`update_vault_metadata` is the load-bearing rename** — current instruction at lib.rs:1673–1721 mutates `vault.name`, `vault.avatar_ipfs`, `vault.slogan`, all of which move to Climb. The instruction must be renamed and retargeted at the Climb account. The access-control check (`vault.rights_holder(current_epoch)`) operates on the same data but against Climb fields after split.

### 4.7 Distribution (lib.rs line 1794)

| Line | Instruction | Shape | Rename | Retire | Climb param | Backend callsites |
|---|---|---|---|---|---|---|
| 1794 | `distribute_epoch_rewards` | **YES — adds Climb** (for Record Board read, lifetime metric update) | Canonical FIX_PLAN L506 rename: **`finalize_settlement_week`** | Semantically same but fully renamed | **YES** | `solana_direct.py:3329–3580` |

The current instruction at 1794 reads `VaultLeaderboard` (which per §9 Q5 may fold into Climb). Regardless of that decision, after split it needs Climb to update `total_dung_distributed`.

### 4.8 Local Legend (lib.rs lines 2177–2247)

| Line | Instruction | Shape | Rename | Retire | Climb param | Backend callsites |
|---|---|---|---|---|---|---|
| 2177 | `elect_local_legend` | No (operates on Vault economic module) | No | No | No (Legend is a Vault concept per TRUTHS §6.4) | backend-only |
| 2229 | `resign_local_legend` | No | No | No | No | backend |

Local Legend is explicitly a **Vault-side rolling-stewardship seat** per TRUTHS §6.4. No Climb plumbing needed.

### 4.9 Admin / activation / seeding (lib.rs lines 2256–2458)

These are devnet smoke + historical seeding surfaces. They all mutate Vault state today.

| Line | Instruction | Shape | Rename | Retire | Climb param | Backend callsites |
|---|---|---|---|---|---|---|
| 2256 | `admin_seed_vault_completion_summary` | **YES** (touches `total_completions`, `kom_holder`, `kom_time_s`) | Rename → `admin_seed_climb_completion_summary` | No | **YES** — operates on Climb now | smoke harness |
| 2288 | `admin_replace_vault_leaderboard` | Depends on §9 Q5 resolution | Rename → `admin_replace_record_board` per P2 vocabulary | No | Depends on Q5 | smoke harness |
| 2324 | `admin_activate_vault` | No | No (activation is a Vault concept) | No | No | smoke |
| 2346 | `admin_override_open_settlement_week` | No | No | No | No | smoke |
| 2372 | `admin_seed_pending_rewards` | No | No | No | No | smoke |
| 2399 | `admin_override_stake_eligibility` | No | No | No | No | smoke |
| 2421 | `admin_backfill_vault_activation` | No | No | No (clean slate deploy deprecates backfill) | No | **Retire candidate** after redeploy |

**Cumulative instruction count currently:** 38 (from the grep at lib.rs lines 155–2421).
**Post-split new count:** ~42 (retire 5, add `found_climb`, `attach_vault`, admin variants, `update_climb_metadata`).

---

## 5. Event-level changes

Source: every `#[event] pub struct` in lib.rs (lines 4845–5142).

| Line | Event | Action | Notes |
|---|---|---|---|
| 4846 | `ProgramConfigInitialized` | Keep | |
| 4853 | `ProgramConfigUpdated` | Keep | |
| 4860 | `RideAttestationRecorded` | Keep | Already canonical. |
| 4871 | `CalCredited` | Keep | Already canonical. |
| 4879 | `ClimbCompleted` | **Keep + expand** | Already emitted at lib.rs:611. Add `climb: Pubkey` alongside `vault_id`. |
| 4891 | `BeetleCardCreated` | Keep | |
| 4899 | `BeetleScoreIncremented` | Keep | |
| 4911 | `BeetleCardStats` | Keep | |
| 4923 | `BeetleCardUpgraded` | Keep | |
| 4934 | `BeetleUpgradeCost` | Keep | |
| 4945 | `VaultCreated` | **Split** | Becomes `ClimbFounded` (founder, geography, signature) + `VaultAttached` (vault_id, climb, payment_method). |
| 4955 | `VaultCompleted` | **Retire** | Dual-emitted today alongside `ClimbCompleted` (see lib.rs:622 next to 611). Drop on hard cutover per FIX_PLAN L508. Record Board consumers all move to `ClimbCompleted`. |
| 4965 | `VaultMetadataUpdated` | **Rename** | `ClimbMetadataUpdated`. Load-bearing for indexer. |
| 4974 | `LocalLegendElected` | Keep | Vault-side. |
| 4987 | `LocalLegendResigned` | Keep | Vault-side. |
| 4996 | `HalvingApplied` | Keep | |
| 5003 | `DungMinted` | Keep | |
| 5014 | `EpochRewardsDistributed` | **Rename** | `SettlementWeekFinalized` per P15 + FIX_PLAN L509. |
| 5032 | `CalStaked` | Keep | |
| 5041 | `CalUnstaked` | Keep | Keep (even though `UnstakeWithFee` is what's emitted today — see lib.rs:1579). |
| 5050 | `UnstakeWithFee` | Keep | |
| 5059 | `RewardsHarvested` | Keep | |
| 5069 | `StakerAllocation` | Keep | |
| 5082 | `ProgramConfigMigrated` | **Retire** | Migration path retires on clean deploy. |
| 5089 | `MintsConfigured` | Keep | |
| 5098 | `TreasuryAccountsConfigured` | Keep | |
| 5105 | `AllocationSubmitterSet` | **Retire** (Merkle path dead per WS-2b) | |
| 5111 | `AllocationBatchSubmitted` | **Retire** | |
| 5122 | `UserCalClaimed` | **Retire** | |
| 5132 | `VaultAllocClaimed` | **Retire** | |
| 5142 | `VaultActivated` | Keep or rename → `ClimbActivated` if the activation concept binds to Climb (see §9 Q7) | |

**Indexer impact:** every event that renames requires a corresponding `indexer/src/writers/*` update; `wdvr.8` owns that propagation per §8.

---

## 6. Account realloc math

Every account whose shape changes needs consideration. Decisions #1–#2 (`docs/design/PROTOCOL_ALIGNMENT_FIX_PLAN.md` §Decisions) establish **fresh program ID, clean slate** — no existing account is realloc'd in-place; all 16 existing devnet vaults are test data and get wiped.

However, the size math still matters for rent estimates and future Anchor account declarations.

| Account | Current size | New size | Delta | Realloc needed? | Rent payer |
|---|---|---|---|---|---|
| `Vault` (current monolith) | 413 B | → split | — | Fresh deploy, no realloc | — |
| `Climb` (new) | — | **566 B** | +566 | Fresh init per Climb | Founder (or backend if admin-path) |
| `Vault` (new lean) | — | **161 B** | — | Fresh init per Vault attach | Same payer as `attach_vault` |
| `VaultCompletion` | 69 B (lib.rs:3286) | 69 B (unchanged; rename to `ClimbCompletion` is semantic) | 0 | No | — |
| `VaultLeaderboard` | ~514 B (lib.rs:3359: `8+8+4+(10×44)+8+1`) | Depends on §9 Q5 | TBD | If folds into Climb, Climb size rises; see Q5 | — |
| `VaultStake` | 77 B (lib.rs:3313) | 77 B (one field rename; shape unchanged) | 0 | No | — |
| `LocalLegend` | 104 B (lib.rs:3412) | 104 B | 0 | No | — |
| `VaultActivation` | 39 B | Keep or fold into Climb (Q7) | TBD | — | — |
| `RideAttestation` | 206 B (lib.rs:2543) | 206 B | 0 | No | — |
| `CalMintReceipt` / `ClimbCompletionReceipt` | 81 B / 73 B | same | 0 | No | — |
| `RiderSoul` | 171 B (lib.rs:2502) | Unchanged by this split (WS-9 owns its migration) | 0 | — | — |

**Fresh-deploy rent (devnet, approximate):**
- Current Vault account rent-exempt ≈ 0.00407 SOL per Vault (413 B @ ~0.00000348 SOL/byte).
- Post-split: Climb 0.00539 SOL + Vault 0.00171 SOL = **0.00710 SOL per Climb+Vault pair**, a net increase of ~0.00303 SOL per founding.
- Exact rent varies by active cluster rent params; anchor prints actual at init.

**Who pays:**
- `found_climb`: founder pays Climb rent (0.00539 SOL).
- `attach_vault`: in `create_vault` path the creator pays; in `admin_create_vault` backend fee payer pays. Same pattern as today — just two init transactions instead of one.

---

## 7. D1 design consequences

D1 = `Climb { vault: Option<Pubkey> }` (primary holds pointer to optional attachment).

### 7.1 Hot-path access patterns

Operations that read/write both Climb and Vault require both PDAs in the Anchor account context. Concretely:

| Operation | Needs Climb? | Needs Vault? | Resolution pattern |
|---|---|---|---|
| `record_climb_completion` | YES (KOM, total_completions, lifetime metrics) | YES (pending_rewards, tribute, open_settlement_week) | Client passes both PDAs; Anchor constraint can verify `vault.climb == climb.key()` and `climb.vault == Some(vault.key())` |
| `stake_cal_in_vault` | Advisory (read-only, to verify climb exists) | YES | Can omit Climb context if Vault.climb check is sufficient |
| `unstake_cal_from_vault` | No | YES | Vault-only |
| `harvest_rewards` | No | YES | Vault-only |
| `finalize_settlement_week` | YES (Record Board, total_dung_distributed) | YES | Both required |
| `update_climb_metadata` | YES | No (metadata is climb-permanent) | Climb-only |
| `elect_local_legend` | No | YES (legend seat lives on Vault) | Vault-only |
| `found_climb` | YES (init) | No | Climb-only |
| `attach_vault` | YES (mutate vault: Option) | YES (init) | Both |
| BoulderScan reads (KOM, record board) | YES | No | Climb-only for display |

**Anchor constraint to enforce bidirectional linkage:**
```rust
#[account(
    constraint = vault.climb == climb.key() @ ErrorCode::ClimbVaultMismatch,
    constraint = climb.vault == Some(vault.key()) @ ErrorCode::ClimbVaultMismatch,
)]
```
This catches wrong-climb / wrong-vault pairings at the edge.

### 7.2 Climb-without-Vault is legal

A Climb with `vault: None` is a well-formed account. Legal operations on it:

- **Read:** founder, KOM, Record Board, geography, lifetime metrics. BoulderScan can display.
- **Founder ops:** `update_climb_metadata` (while `rights_expires_epoch` unspent).
- **Future:** additional asset graph types (Route, Zone, Arena per TRUTHS §2.1) can attach similarly via an `Option<Pubkey>` without redesigning Climb.

Illegal operations:
- Any staking or tribute flow (requires Vault).
- Any distribution (no economic module to distribute from).

### 7.3 Legacy Vaults without Climb parents — migration order

Per Decision #1 and #2, existing devnet state is wiped. But on fresh deploy, creation order matters:

- `found_climb` must precede `attach_vault`.
- Backend seed scripts (`backend/scripts/seed_vaults_onchain.py`, to be renamed `seed_climbs_onchain.py` per FIX_PLAN L546) call the two in sequence and commit atomically.
- If Tim decides to preserve any legacy vault state as part of a testnet→mainnet bridge (not current plan), a one-shot `admin_backfill_climb_from_vault` migration instruction would be required. **Out of scope for 0uv8** unless Tim opens that door.

---

## 8. Scope boundary with `wdvr.8`

**`0uv8`:** Climb-first surface split. On-chain Anchor program changes + IDL regeneration. This is the surgical split that makes Climb a first-class account.

**`wdvr.8`:** Propagate cleanup + canonical naming. Non-program work downstream of `0uv8`: docs, BoulderScan copy, migration scripts, portal, backend response-field renames (beyond what `mfab.5` already landed), stale references.

**Proposed clean boundary (honest — we can't query beads DB from this worktree; see note below):**

Per `docs/design/PROTOCOL_AGENT_RETURN_BRIEF.md` lines 101–102:
- `wdvr.8` is "Phase 2 tail work — propagate cleanup + canonical naming; mfab.5 feeds into this"
- `0uv8` is "Climb-first surface split; D1 design consequence noted" (in progress)

And per `WWPTD_EPIC_PORTFOLIO_2026-04-17.md` line 91–93:
- `0uv8` = "Make Climb the primary public object; propagate canonical naming across backend/API/BoulderScan/mobile; retire compatibility aliases after consumers migrate" — IN_PROGRESS
- `wdvr.8` = "Dead-code cleanup, doc updates, BoulderScan/API copy, retire stale migration and compatibility surfaces" — OPEN

**Reading those two together — proposed split:**

| Work item | 0uv8 | wdvr.8 |
|---|---|---|
| Rewrite `lib.rs` with Climb + Vault structs | ✓ | |
| Rename instructions/events in Anchor source | ✓ | |
| Regenerate IDL | ✓ | |
| Rewrite Anchor tests against new shape | ✓ | |
| Deploy fresh program ID to devnet + capture in `addresses.devnet.json` | ✓ | |
| Update `backend/app/solana_direct.py` to use new IDL / ix names | ✓ (first pass) | finish stale strings |
| Backend API response-field renames (`vault_*` → `climb_*` where applicable) | (some) | ✓ (tail) |
| Portal + mobile consumer renames (bead `kaol` portal, mobile read layer) | | ✓ |
| Docs: FRESHEST_SPEC, CLAUDE.md updates | starter | ✓ (primary) |
| Retire stale migration scripts (e.g., `migrate_v3_security.ts` already archived) | | ✓ |
| Retire backend compat aliases (`/segments` alias from mfab.5) | | ✓ — **after** consumers migrate |

**Proposed rule of thumb:** if it's inside `protocol/anchor/` or the direct `solana_direct.py` instruction builders, it's `0uv8`. If it's naming in docs, portal, mobile read layer, stale scripts, or compat alias retirement — `wdvr.8`.

**Note to executor:** cross-check with `bd show 0uv8` and `bd show wdvr.8` from the canonical repo worktree. This doc lives in `BoulderRoller-v2` but the beads daemon is attached to `boulderroller-v2` — not accessible from research context. Tim or protocol agent should confirm the boundary before execution.

---

## 9. Open questions for Tim

**Q1 — Climb PDA seed: signature_hash or climb_id?**
- **Option A (recommended):** `[CLIMB_SEED, &signature_hash]`. Ties PDA directly to canonical identity. Matches TRUTHS §2.1 "canonical identity for a real hill." Breaks VaultCounter parallel but Climbs don't need monotonic IDs.
- **Option B:** `[CLIMB_SEED, &climb_id.to_le_bytes()]` with a new ClimbCounter. Mirrors Vault addressing but decouples PDA from identity.
- **Implication:** Backend lookup shifts from `climb_id` → `signature_hash_hex` with Option A. A-route keeps identity-first addressing.

**Q2 — Replace `mint_epoch`/`rights_expires_epoch` with `founded_at: i64`?**
FIX_PLAN L324 lists `founded_at: i64` + `founded_ride_attestation: Pubkey` (ride-time + traceable). Keep the epoch-based `rights_expires_epoch`, or also convert it to an `i64`/`ride-time` boundary? Current lib.rs uses `rights_expires_epoch: u64` = `mint_epoch + MINTER_RIGHTS_EPOCHS`; flipping to ride-time boundary respects P6 ("Ride time is the economic clock") but complicates the rights-holder check at `Vault::rights_holder()` lib.rs:3120.

**Q3 — Does the `minter rights period` concept survive V4-B?**
TRUTHS §6.1 says founder rights are *permanent provenance + metadata authorship + bootstrap Legend stint.* The current `rights_expires_epoch` (MINTER_RIGHTS_EPOCHS = 12 epochs ~= 3 months) is a bespoke Vault-era concept not named in TRUTHS. Options:
- Keep the concept on Climb (retain `rights_expires_epoch`).
- Fold founder metadata rights under "until first Local Legend elected" (aligned with TRUTHS §6.1 bootstrap stint language).
- Make founder rights permanent per TRUTHS wording.

**Q4 — Lifetime aggregates (`total_cal_burned`, `total_dung_emitted`, `total_completions`): Climb or Vault?**
TRUTHS §3.1 lists "lifetime CAL committed to a climb" as permanent truth (→ Climb). Operationally, they flow through Vault economics. FIX_PLAN line 332–333 puts them on Climb. Recommendation stands, but explicit Tim sign-off requested because this inverts the data flow: today they're incremented from inside Vault-mutating instructions.

**Q5 — `VaultLeaderboard` (a.k.a. Record Board): fold into Climb, or keep separate account?**
Per TRUTHS §6.3 the Record Board is permanent Climb truth (→ Climb). FIX_PLAN L328 shows it as a Climb field: `record_board: [RecordBoardEntry; 10]`. Two paths:
- **Fold:** embed `[RecordBoardEntry; 10]` directly in Climb. +440 bytes (10 × 44 B). Climb total = ~1006 B. Simpler reads, no separate PDA.
- **Keep separate:** rename `VaultLeaderboard` → `ClimbRecordBoard`, keep its own PDA. Smaller Climb, extra account load on hot reads.

This is the biggest architectural decision not yet settled by D1–D4. FIX_PLAN folds it; I surface it here because it meaningfully changes the Climb surface.

**Q6 — Vault PDA seed: keep `[VAULT_SEED, &id.to_le_bytes()]` or re-seed off Climb?**
- **Option A (compatibility):** keep vault_id-seeded Vault PDAs. VaultStake/VaultCompletion child PDAs keep their seed layout.
- **Option B (TRUTHS-pure):** `[VAULT_SEED, climb_pda.as_ref()]`. Vault is *the* Vault of *this* Climb. One-to-one bijection at the seed level.
- Option B makes Vault more TRUTHS-literal but breaks child-PDA discipline and the VaultCounter bootstrap.

**Q7 — `VaultActivation` account: keep on Vault, fold into Climb, or drop after fresh deploy?**
Activation is a devnet-era seeding gate. Post fresh-deploy under V4-B, the concept may be moot (no legacy vaults to seed). If kept, it could live on Climb (since seeding touches Climb KOM/leaderboard data), on Vault (economic lifecycle), or be split into `ClimbActivation` + `VaultActivation`.

**Q8 — Record Board event emission on update?**
If Record Board folds into Climb, `record_climb_completion` may emit a new `RecordBoardUpdated { climb, rider, old_rank, new_rank, seat_changes }` event when the top 10 changes. FIX_PLAN L472 hints at this (`update_record_board(climb, new_entry_candidate)` with "event emission per seat change"). Scope confirmation requested.

---

## Gift-posture self-check

*Would the protocol agent return, read this, and smile at a surgical map they can execute against?*

Claims in this doc that I specifically grounded in lib.rs line numbers so the executor can trust them:
- Every field in §1 maps to exact lib.rs lines (struct at 2987–3049, SIZE at 3052–3089).
- Every instruction in §4 maps to exact lib.rs `pub fn` lines.
- Every event in §5 maps to exact `#[event]` lines (4846–5142).
- Backend callsites cite `solana_direct.py` line numbers from grep.
- Every byte count is additive from the cited field sizes (discriminator 8 + type sizes per Anchor serialization rules).

What I did NOT do (explicit cuts per "scope OUT" in the brief):
- No code edits.
- No deploy/realloc execution plan (sibling agent's territory).
- No full consumer inventory across backend/indexer/mobile (sibling agent).
- No resolving Q1–Q8 — they are explicitly surfaced for Tim.

Where I'm making recommendations (not facts), they are called out as "recommended" with the alternative path and trade-off stated.

---

## References

- `docs/PROTOCOL_TRUTHS.md` — §§2, 4, 6, 7, 11
- `docs/design/PROTOCOL_ALIGNMENT_FIX_PLAN.md` — Principles P1, P2, P4, P5, P6, P8, P9, P10, P11, P15; WS-1 target-state L295–552; Decisions #1–#18
- `docs/design/WWPTD_EPIC_PORTFOLIO_2026-04-17.md` — D1 at §Decisions, bead IDs at §Bead map
- `docs/design/PROTOCOL_AGENT_RETURN_BRIEF.md` — Return brief with open-bead status
- `protocol/anchor/programs/boulder_rollers/src/lib.rs` — 5342 LOC, lines cited throughout
- `protocol/anchor/addresses.devnet.json` — current V4-A program `HsPhhMukUKu641e9hDJUJJW4chvF5EXYzuG2xBwMrnst`
- `backend/app/solana_direct.py` — instruction builder callsites cited in §4
