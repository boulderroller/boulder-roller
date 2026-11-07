# Protocol Alignment Fix Plan

**Status:** READY FOR EXECUTION — staged as Phase 1 coherence, then Phase 2 ontology lift
**Last revised:** 2026-04-15 — rewritten around canonical protocol truths
**Authors:** Claude + Tim + two external review passes
**Semantic authority:** [`docs/PROTOCOL_TRUTHS.md`](../PROTOCOL_TRUTHS.md) — if this plan and PROTOCOL_TRUTHS conflict, TRUTHS wins.

**Completion-evidence addendum (2026-07-14):** Unversioned
`record_climb_completion` references below describe the historical V1 shape.
V1 now fails closed. All live writers use `record_climb_completion_v2` and
`ClimbCompletionReceiptV2`, which bind exact tribute; V4-B must carry that V2
invariant forward rather than reviving V1 semantics.

---

## Executive Summary

Boulder Roller has accumulated drift across the stack. Two independent audits and one canonical protocol truths document now make the path forward clear: this is not a patch pass. It is a **staged V4 program**:

1. **Phase 1 — coherence redeploy:** fresh program ID, direct settlement, direct allocation, per-bucket carry, signer/config fixes, runtime hazard cleanup, and two green smoke gates.
2. **Phase 2 — ontology lift:** Climb/Vault/RiderSoul split, first-class RideAttestation PDA, and hard rename propagation once the coherent system is already green.

The semantic target state is large. The first critical-path redeploy must not try to land the whole ontology shift at once.

The root cause of the drift is that **the V3 security hardening landed in source and IDL but was never completed downstream.** The root cause of the architectural confusion is that **the existing codebase treats Vault as the primary object and epoch as protocol ontology, when Climb should be primary and epoch should be only the settlement clock.** PROTOCOL_TRUTHS fixes the latter; this plan resolves both.

**The protocol we are building, restated in one sentence:**

> Boulder Roller creates on-chain economic truth for cycling geography — a climb-first protocol where permanent records earn Record Royalty, rolling stewardship earns Local Legend, and capital participation earns staker bucket rewards, all settled on a weekly clock that the user never has to think about.

---

## Protocol Design Principles

These principles are canonical. Every workstream in this plan derives from them. If an implementation choice conflicts with a principle, the principle wins and the implementation is wrong.

### P1 — Climb-first, not Vault-first

> *"The Climb is primary. The Vault is attached."* — PROTOCOL_TRUTHS §2.2

The primary protocol object is the `Climb` — a permanent geographic identity, founder provenance, KOM, Record Board, lifetime metrics. A `Vault` is an *optional economic module attached to a Climb*, one-to-one, that holds reward reserves, staking state, the Local Legend seat, and carry balances. Climbs can exist without Vaults (future). Vaults cannot exist without Climbs.

**Implementation consequence:** the current `Vault` struct in `lib.rs` conflates two ontological objects into one account. It must be decomposed into `Climb` + `Vault` in the V4 redeploy.

### P2 — Record Royalty, not leaderboard reward

> *"The 55% leaderboard bucket is canonically the Record Royalty bucket. It pays the Climb's all-time Record Board."* — PROTOCOL_TRUTHS §8.1

The 55% bucket is not a per-epoch challenger board reward. It is a royalty stream paid to the **permanent all-time top 10** of each climb, split by fixed rank percentages (30/20/15/10/8/6/5/3/2/1). The Record Board changes only when a new ride posts a better time than an existing entry, which bumps that entry off and shifts lower ranks down.

> *"A climb can remain economically alive even when the record board is old."* — PROTOCOL_TRUTHS §9

Classic climbs with historic KOMs keep earning Record Royalty forever as long as riders continue to ascend them and tribute continues to flow. This is intentional. Permanent excellence is a feature.

**Product narrative:** "You crushed Old Baldy in 2026. Every rider who climbs it from then on pays you rent. You keep earning until someone beats your time."

### P3 — Three temporal truths, three clocks

> *"Permanent excellence through the Record Board, recent stewardship through Local Legend, capital support through staking."* — PROTOCOL_TRUTHS §6 distilled

- **Permanent Truth** — Climb identity, founder, KOM, Record Board, lifetime metrics, rider soul. Never expires, changes only when directly dethroned.
- **Rolling Truth** — Local Legend seat, recent activity, heat maps. Based on recent-participation windows, may go dormant.
- **Settled Truth** — DUNG distributions, staker entitlements, Record Royalty payouts, carry balances. Finalized on the settlement clock.

These three types of truth are not interchangeable. Each has its own temporal character and its own failure mode. The plan must preserve the distinction.

### P4 — Epoch is the settlement clock, not protocol ontology

> *"Epochs are not the ontology of the protocol. They are the settlement clock for economic state."* — PROTOCOL_TRUTHS §4

Epochs do not define Climb identity, KOM, Record Board, rider soul, or lifetime metrics. They define only the cadence on which economic state finalizes: DUNG distributions, staker entitlements, Record Royalty payouts, carry balance updates, Local Legend seat settlement.

User-facing language should prefer **"Settlement Week"** over "epoch." Internal code-level math variables stay as `epoch` for compact integer-period expression, but user-visible account field names, instruction names, and event names use `settlement_week` terminology where it clarifies meaning.

### P5 — Ride attestation is a first-class on-chain primitive

> *"A ride is attested once, every economic consequence is derived from that attestation once, every epoch is finalized once, and every claimable amount exists on-chain before anyone claims it."* — external review, 2026-04-15

Every economic consequence of a ride (CAL mint, vault completion, Record Board update, Local Legend participation) must be derived from a single `RideAttestation` PDA, created once, immutable, with structural replay protection via child receipts.

`ride_hash` is deterministic from a **canonicalized ride trace**, not raw file bytes. Canonicalization is versioned (`parser_version` field) so it can evolve without breaking old records.

**Child receipts** for structural replay protection:
- `ClimbCompletionReceipt` keyed by `(ride_attestation, climb_id)` — Anchor `init` prevents duplicates
- `CalMintReceipt` keyed by `(ride_attestation, rider)`
- `PatternAwardReceipt` keyed by `(ride_attestation, award_type)`

### P6 — Ride time is the economic clock

> **Superseded 2026-07-14:** P6 and P7 are superseded where they assign tribute
> or Record Board admission to the ride's historical week. `completed_at`
> remains immutable ride/KOM/Record Board provenance. `record_ride` applies the
> 30-day admission guard once and records `settled_at`; receipt-backed child
> effects revalidate against that admission clock. Accepted tribute enters the
> Vault's oldest open lifetime flow.

> *"The economically authoritative timestamp should be ride completion time, not upload time and not settlement time."* — external review, 2026-04-15

Ride evidence anchors on `RideAttestation.completed_at`, derived from the FIT/GPX file's metadata. The payout flow is selected by the Vault's oldest open Settlement Week after empty-week catch-up, not by the ride's historical week.

**Three distinct times:**
- `completed_at` — event time from the ride trace. Determines historical epoch, leaderboard ordering, and Legend provenance.
- `settled_at` — when the chain accepted the attestation and froze the 30-day admission decision.
- `finalized_at` — when one credited Settlement Week payout became immutable.

### P7 — 24-hour settlement finalization window

> *"Rides belong to the epoch in which they happened. Epochs finalize after the grace window. After finalization, nothing can retroactively rewrite that epoch's economic state."* — external review, 2026-04-15

A `SETTLEMENT_FINALIZATION_GRACE_SECONDS = 86400` window follows each wall-clock epoch boundary. Rides uploaded during the grace window that have `completed_at` in the outgoing epoch still update provisional state. At `wall_clock_epoch_end + 86400`, the chain **finalizes** the epoch via an explicit `finalize_settlement_week` instruction that freezes the Record Board updates for that window, distributes all buckets, updates carry, and emits the canonical settlement events.

Post-finalization: an accepted ride still records on-chain at original
`completed_at` and credits the oldest open lifetime tribute flow. Finalization
freezes that payout and its carry; it does not close the all-time Record Board
to otherwise valid delayed evidence. The receipt-less legacy
`record_vault_completion` entry point remains ABI-visible but fails closed.

### P8 — Discrete per-epoch settlement, not Synthetix accrual

> *"Replace continuous Synthetix staking with discrete epoch entitlements."* — external review, 2026-04-15

We abandon Synthetix-style `reward_rate / reward_per_token_stored / last_update_time` math entirely. It is the wrong shape for a protocol whose economics are already weekly and discrete.

**Discrete direct allocation:** at `finalize_settlement_week`, the chain iterates eligible stakers, computes each's pro-rata share of the unlocked staker bucket, credits directly to `VaultStake.unclaimed_rewards`, and emits a `StakerAllocation { epoch, vault, staker, amount, stake_at_distribution }` event per recipient. Harvest becomes "claim unclaimed_rewards to my ATA" — no accrual math, no rate calc, no quantization bug.

Eliminates the reward_rate quantization bug and the missing period_finish bug (external review F1) in one move.

### P9 — Full-epoch participation for staker eligibility

> *"A stake position has effective_cal, effective_from_epoch... A staker counts toward unlock only if their effective stake has been active since at least epoch - 2."* — external review, 2026-04-15

Stakes become economically effective at the **next epoch boundary** after deposit. The unlock curve (1% → 100% across 1–10 eligible stakers) counts only stakers whose stake has been continuously active for ≥2 full epochs. Mid-epoch stake changes never affect the current epoch. Sockpuppet-swarm gaming is structurally prevented.

**On-chain state:** `VaultStake.effective_from_epoch` explicitly encodes eligibility. No derivation from timestamps. Auditable against restake/unstake boundary behavior.

### P10 — Per-bucket carry, bucket identity preserved

> *"Truth-first design says buckets keep their identity. Leaderboard money is always leaderboard money. Staker money is always staker money."* — external review, 2026-04-15

Carry-forward state is bucket-typed. `Vault` holds five explicit carry fields:
- `carry_record_royalty`
- `carry_stakers`
- `carry_local_legend`
- `carry_pol`
- `carry_treasury`

Stored carry remains bucket-typed. Empty Record Board and dormant Legend
amounts carry in their own buckets, and integer allocation dust retains its
bucket identity. The current week's policy-locked staker base is not carry: it
is reallocated to that same week's Record Royalty before rank allocation.
Prior `carry_stakers` is already-unlocked pro-rata dust and is never curved
again. Because deployed pre-policy Vaults used that field for both locked value
and dust, their first new-policy settlement reclassifies the entire legacy
balance to Record Royalty, emits the versioned policy marker event, and marks
the retired on-chain reward-rate slot. Historical projections use the event as
the interpretation boundary.

### P11 — On-chain truth is auditable without the indexer

> *"Transaction builders should read ProgramConfig by RPC and treat the indexer as a cache/UI projection only."* — external review, 2026-04-14

Transaction builders never read canonical config (POL token account, treasury token account, `backend_authority`, last_distribution markers) from the indexer. They read from on-chain `ProgramConfig` via RPC. The indexer is a read projection for dashboards and UX, never authoritative for transaction construction or settlement logic.

### P12 — Soulbound rider identity is separate from CAL

> *"Capital may buy exposure to a climb. Capital may not buy riderhood."* — PROTOCOL_TRUTHS §7.3

Rider identity — lifetime rides, lifetime TSS, beetle scores, rider class, effort history — lives in a non-transferable `RiderSoul` account separate from the SPL CAL token balance. CAL is transferable currency; RiderSoul is effort identity. BeetleCards derive from RiderSoul state. The two must never be conflated.

### P13 — Attester, not authority, backed by cryptographic commitment

The backend signs transactions but what it signs is cryptographically committed via `ride_hash` + `attestation_commitment`. A user with the original ride file can recompute the canonicalized hash and verify the backend attested correctly. This is not trusted issuance; it is **backend-attested with on-chain cryptographic commitment**.

**Product narrative:** "Here's my ride file. I can compute its canonical hash. The chain has a `RideAttestation` with that hash and my wallet. It shows I earned N CAL and hit seat 3 on Old Baldy's Record Board. I verified all of it myself."

### P14 — No dust, no handwaving, explicit economics

Every economic operation has an explicit state trail on-chain. Rounding dust carries forward within its bucket (P10). Quantized staker rewards carry forward (P8 eliminates quantization, but any residual handles the same way). Empty Local Legend seats carry forward within the Legend bucket. Nothing is burned silently, rerouted silently, or handwaved.

### P15 — Open-source naming discipline

The deployed Anchor program is effectively public (bytecode + IDL are queryable by any observer). Account struct names, instruction names, event names, and field names surface in BoulderScan, wallet explorers, and IDL-based clients. These names must match the PROTOCOL_TRUTHS vocabulary so external observers see a coherent protocol, not internal jargon.

**Naming propagation depth:**
- **Hard rename:** account struct names (`Vault` → `Climb` + `Vault`), instruction names (`record_vault_completion` → `record_climb_completion`), event names (`VaultCompleted` → `ClimbCompleted`), account field names where renaming improves clarity.
- **Preserve internal:** code-level math variables (`current_epoch: u64`), compact integer identifiers, Borsh serialization conventions.

---

## Execution Discipline (READ BEFORE WORKSTREAMS)

This plan contains both:
- the **semantic target state** defined by `PROTOCOL_TRUTHS.md`
- the **minimum executable order** required to reach coherence safely

Those are not the same thing.

The main correction from this review is:

> Do **not** couple fresh-program-ID coherence work, staking-model replacement,
> carry semantics, RideAttestation, Climb/Vault split, RiderSoul, and hard rename
> propagation into one first redeploy.

### Phase 1 — Coherence Redeploy (mandatory first)

The first redeploy should land only what is needed to make the protocol
economically correct, auditable, and smoketestable on devnet:

- fresh program ID
- delete Merkle allocation / claim path
- replace Synthetix accrual with direct discrete allocation
- add settlement-week finalization and grace window
- add per-bucket carry
- fix signer / RPC truth-boundary issues
- fix slot=0 / runtime hazard / silent stub issues
- keep the current Vault-centered account shape where that reduces blast radius

### Phase 2 — Ontology Lift (gated on green smoke)

Only after Phase 1 Gate 1 and Gate 2 are both green should execution continue to:

- split `Vault` into `Climb` + `Vault`
- introduce `RiderSoul`
- introduce first-class `RideAttestation` PDA + child receipts
- hard-rename the IDL-visible surface to canonical vocabulary

### Interpretation Rule

The `WS-1` section below describes the **target-state V4-B chain model**. It is
not the minimum scope of the first redeploy. Execution agents must follow the
sequencing section, not the target-state section, when deciding what lands first.

---

## Reference to Canonical Truth

All architectural decisions in this plan derive from:

1. **`docs/PROTOCOL_TRUTHS.md`** (2026-04-15) — canonical semantic source, authored by Tim. Defines Climb vs Vault, temporal truths, Record Royalty semantics, role separation, token meanings, bucket identity.
2. **`docs/design/LASERSTREAM_MIGRATION_BLUEPRINT.md`** — research output, filed as future work. Referenced for "architected for scale" positioning but NOT part of current scope.
3. **Phase A audit matrix** — the 36+ drift findings that triggered this plan.
4. **Two external review passes** (2026-04-14, 2026-04-15) — contributed the staker model, ride attestation model, temporal discipline, bucket carry model.

---

## The 7 Core Flows — Current Status

| Flow | Status | Notes under new ontology |
|---|---|---|
| 1. Climb founding (was "vault creation") | 🟡 Working (stale cruft + ontological collapse) | Climb and Vault are still one account. Must split in V4. |
| 2. Record climb completion (was "vault completion") | 🟢 Working | Will be rewritten to key on RideAttestation and emit ride-time events. |
| 3. CAL allocation pipeline | 🔴 **Broken** for 16 existing vaults | Clean slate fixes. Merkle path deleted entirely per external review. |
| 4. Settlement week finalization (was "epoch distribution") | 🔴 **Broken end-to-end** | Rewritten around discrete direct allocation, per-bucket carry, 24h finalization window. |
| 5. Staking / unstake / harvest | 🟡 Math wrong (Synthetix bugs) | Replaced with discrete epoch entitlement model. Harvest becomes claim. |
| 6. Local Legend rotation | 🟠 Bootstrap works, rotation **orphaned** | New scheduler lives in backend, derives winner from on-chain stats, submits at finalization. |
| 7. BeetleCard upgrades | 🟢 Working | Moves to derive from RiderSoul. |

---

## Root Cause

The drift has two compounding sources:

**1. V3 security hardening landed in source/IDL but was never completed downstream.** `last_distribution_epoch: u64` was added to `Vault`, `pol_token_account` and `treasury_token_account` were added to `ProgramConfig`, access control constraints were added to admin instructions, `create_vault_points_period` was renamed to `admin_create_vault`. The on-chain program was not redeployed, the 16 existing vaults were not migrated, the backend was not updated to pass `backend_authority`, the indexer was not updated to persist the V3 fields, and the migration script (`migrate_v3_security.ts`) was written as a warning-only reporter with a broken size threshold check.

**2. The codebase was built on pre-PROTOCOL_TRUTHS ontology.** Vault was treated as the primary object, epoch as protocol ontology, leaderboard as per-epoch, rider identity as a UserState field. PROTOCOL_TRUTHS (2026-04-15) inverts these assumptions: Climb is primary, epoch is only the settlement clock, Record Royalty is permanent, rider identity is a separate soulbound layer.

This plan addresses both root causes in staged form. Phase 1 restores
coherence. Phase 2 lands the fuller protocol shape described by
`PROTOCOL_TRUTHS.md`.

---

## Decisions Locked In

All decisions below have been ratified through the course of this design process (2026-04-13 to 2026-04-15). They are not open for further debate unless new information emerges.

| # | Decision | Ratified by |
|---|---|---|
| 1 | **Fresh program ID** for V4 redeploy. No in-place upgrade, no V3 migration script. | Tim 2026-04-14 |
| 2 | **Clean slate** for existing devnet state. The 16 vaults are test data; no preservation. | Tim 2026-04-14 |
| 3 | **Abandon Synthetix**, use discrete per-epoch direct allocation for stakers. | Tim 2026-04-15 |
| 4 | **Canonicalized ride hash** from canonicalized trace, versioned via `parser_version`. | Tim 2026-04-15 |
| 5 | **Child receipt PDAs** for structural replay protection (ClimbCompletionReceipt, CalMintReceipt). | Tim 2026-04-15 |
| 6 | **Per-bucket carry**, not pool-level. Five explicit carry fields on Vault. | Tim 2026-04-15 |
| 7 | **24-hour finalization grace window** after wall-clock epoch end. Explicit `finalize_settlement_week` instruction. | Tim 2026-04-15 |
| 8 | **Full-epoch participation rule** for staker eligibility (≥2 full epochs). `eligible_from_epoch` is explicit on-chain state. | Tim 2026-04-15 |
| 9 | **`VaultStake.unclaimed_rewards` running total** + event emission per allocation. Not dedicated `StakerEpochEntitlement` PDAs (rent cost not justified). | Claude, Tim ratified |
| 10 | **Record Royalty = all-time top 10, permanent.** Not per-epoch challenger board. | Tim 2026-04-15 via PROTOCOL_TRUTHS |
| 11 | **Climb-first ontology** — `Climb` and `Vault` are separate accounts. `RiderSoul` is a third account. | Tim 2026-04-15 via PROTOCOL_TRUTHS |
| 12 | **Hard rename** in the IDL-visible surface (account structs, instructions, events, public fields) to PROTOCOL_TRUTHS vocabulary. Internal math variables preserved. | Tim 2026-04-15 |
| 13 | **LaserStream migration deferred** until revenue justifies the $499/mo Business tier. Blueprint kept as committed doc for future execution. | Tim 2026-04-15 |
| 14 | **Key management** — 5-key architecture (Upgrade/Admin/Backend/FeePayer/Funding), Ledger for A/B, Doppler for C/D, no multisig pre-TGE. | Tim 2026-04-14, unchanged |
| 15 | **Staking exit fee stays pure burn** for now. Revisit before TGE. | Tim 2026-04-14 |
| 16 | **Dormant fields populated or removed.** `LocalLegend.total_earned` gets runtime increments. | Tim 2026-04-15 |
| 17 | **Empty-bucket rule:** carry within the same bucket to next settlement week. No redistribution to other buckets. | Tim 2026-04-15 |
| 18 | **Truth boundary:** chain owns token state + Climb + Vault + settlement + claim obligations; backend owns ride parsing + canonicalization + attestation generation; indexer owns read projections only; transaction builders read canonical config via RPC. | Tim 2026-04-15 via PROTOCOL_TRUTHS §12, §5 |

---

## Workstream Overview

Ten workstreams. Semantically, `WS-1` describes the target-state chain model. Operationally, execution is staged by the **Execution Discipline** section above: a narrower coherence redeploy lands first, and only then does the ontology lift proceed. WS-2a lands first as a safety net. WS-4 lands first as another safety net. WS-5 lands first as an immediate runtime hazard fix.

| # | Name | Scope | Depends on |
|---|---|---|---|
| WS-1 | V4 Chain Redeploy | Target-state chain model. Phase 1 lands the coherence subset; Phase 2 lands the ontology lift (Climb/Vault/RiderSoul split, RideAttestation PDA, hard rename). | WS-2a, WS-4, WS-5 (safety nets), WS-10 (spec) |
| WS-2a | Backend Decoder Alignment | Kill manual Vault decoder, drop archived program imports, replace with IDL-driven decoding | None — lands first |
| WS-2b | CAL → Ride Attestation Flow | Record_ride → credit_cal → record_climb_completion with child receipts; delete Merkle path | WS-1 |
| WS-3 | Backend Caller Fixes | Signer fixes (resolve_backend_authority), kill silent stubs, RPC reads for ProgramConfig | WS-1 |
| WS-4 | Indexer Slot Fixes | Fix slot=0 in snapshot/reconciliation; full slot+write_version guard deferred to post-LaserStream | None — lands first |
| WS-5 | distribution_receipts Cleanup + Record Royalty Projection | Immediate: delete runtime-broken table. Long: indexed projections for Record Royalty payouts + StakerAllocation events | None — lands first |
| WS-6 | Local Legend Rolling Stewardship | `LegendStewardshipService`, on-chain `VaultUserEpochStats` provisional PDAs, chain-derivable winner, finalization-integrated | WS-1 |
| WS-7 | Key Management Hardening | 5-key architecture (Ledger A/B, Doppler C/D), rotation drill, staged alongside coherence redeploy first and ontology lift later | Coordinated with WS-1 |
| WS-8 | Dead Code + Doc Cleanup | Stale references, CLAUDE.md/FRESHEST_SPEC updates, rename propagation tail | Tails WS-1 through WS-7 |
| WS-9 | RiderSoul Layer | New `RiderSoul` account, split from `UserState`, BeetleCard derivation | Phase 2 ontology lift after Gate 1 + Gate 2 |
| WS-10 | Ride Canonicalization Spec | Formal spec for canonical trace serialization, `parser_version`, `ride_hash` derivation | Must land before WS-1 implementation |

---

### WS-1 — V4 Chain Redeploy (CRITICAL PATH)

**Goal:** Land a complete V4 Anchor program to devnet with the Climb-first ontology, discrete settlement, attestation-native primitives, and per-bucket carry. Fresh program ID. Existing devnet state is wiped.

**Drift IDs resolved:** D001, D002, D006, D009, D015, D017, D025, D031, external F1, F3, F4, F5, F11, plus the entire category of "V3 half-landed" and "pre-PROTOCOL_TRUTHS ontology".

**New account structs (Anchor source):**

```
Climb {
    signature: [u8; 64],              // canonical climb identity
    signature_hash: [u8; 32],
    founder: Pubkey,                  // permanent provenance
    founded_at: i64,                  // ride-time of first KOM attempt, not settlement time
    founded_ride_attestation: Pubkey, // immutable link to the founding ride

    // Immutable geography
    vert_m: u32,
    distance_m: u32,
    avg_gradient_pct: u16,

    // Founder-editable metadata (until Local Legend seat active, then they edit)
    name: [u8; 64],
    avatar_ipfs: [u8; 46],
    slogan: [u8; 128],

    // Permanent KOM (all-time fastest)
    kom_holder: Pubkey,
    kom_time_s: u32,
    kom_set_at: i64,                  // ride-time
    kom_ride_attestation: Pubkey,

    // Permanent Record Board (all-time top 10, Record Royalty recipients)
    record_board: [RecordBoardEntry; 10],

    // Lifetime metrics (informational, monotonic)
    total_completions: u64,
    total_cal_committed: u64,         // lifetime CAL tributed to this climb
    total_dung_distributed: u64,      // lifetime DUNG paid out from this climb

    // Optional economic attachment
    vault: Option<Pubkey>,            // Some(vault_pda) if vault attached
    bump: u8,
}

RecordBoardEntry {
    rider: Pubkey,
    time_s: u32,
    completed_at: i64,                // ride-time, NOT Clock::get()
    ride_attestation: Pubkey,         // traceable proof
}

Vault {
    climb: Pubkey,                    // the Climb this vault wraps
    // Inflow (current settlement week)
    pending_rewards: u64,             // incoming DUNG-equivalent from CAL tribute

    // Per-bucket carry (P10 — bucket identity preserved)
    carry_record_royalty: u64,
    carry_stakers: u64,
    carry_local_legend: u64,
    carry_pol: u64,
    carry_treasury: u64,

    // Staking state
    total_cal_staked: u64,
    eligible_staker_count: u32,       // count of stakers with ≥2 full epochs active

    // Local Legend seat (rolling stewardship)
    local_legend: Pubkey,             // default if dormant
    local_legend_active: bool,
    local_legend_term_end_epoch: u64,

    // Settlement state
    last_finalized_epoch: u64,        // replaces last_distribution_epoch
    last_finalized_at: i64,           // when finalization happened

    bump: u8,
}

RiderSoul {
    rider: Pubkey,
    created_at: i64,                  // first ride attestation time

    // Lifetime effort metrics (monotonic, never decrement)
    total_rides: u64,
    total_tss: u64,
    total_distance_m: u64,
    total_vert_m: u64,
    total_cal_earned: u64,            // lifetime CAL earned (NOT current balance)

    // Rider class / archetype
    archetype: u8,                    // Sprinter/Puncheur/Breakaway/Rouleur/Climber/GC
    bio_score: u64,                   // effort-time aggregate

    // BeetleCard references (one per card type)
    climb_card: Option<Pubkey>,
    steady_card: Option<Pubkey>,
    explorer_card: Option<Pubkey>,

    bump: u8,
}

RideAttestation {
    rider: Pubkey,
    ride_hash: [u8; 32],              // SHA256 of canonicalized trace
    attestation_commitment: [u8; 32], // SHA256 of canonical summary
    parser_version: u32,              // canonicalization versioning
    source_kind: u8,                  // FIT / GPX / TCX / Strava / Garmin / etc
    completed_at: i64,                // ride-time (economic clock)
    started_at: i64,
    total_tss: u32,
    cal_earned: u64,
    climbs_crossed: u16,
    attester: Pubkey,                 // backend_authority pubkey at attestation time
    settled_at: i64,                  // Clock::get() when chain accepted (audit only)
    settled_slot: u64,                // settlement slot (audit only)
    economic_epoch: u64,              // derived: (completed_at - EPOCH_ANCHOR) / EPOCH_DURATION
    finalized: bool,                  // true if epoch has passed finalization grace
    bump: u8,
}

ClimbCompletionReceipt {
    ride_attestation: Pubkey,
    climb: Pubkey,
    // Anchor init prevents duplicate (ride_attestation, climb) pairs
    bump: u8,
}

CalMintReceipt {
    ride_attestation: Pubkey,
    rider: Pubkey,
    amount: u64,
    bump: u8,
}

VaultStake {
    vault: Pubkey,
    staker: Pubkey,
    effective_cal: u64,               // stake amount
    staked_at: i64,                   // informational
    effective_from_epoch: u64,        // P9: first epoch where stake counts
    unclaimed_rewards: u64,           // running total from direct allocations
    last_claimed_epoch: u64,          // for event-scan reconstruction
    bump: u8,
}

VaultUserEpochStats {
    vault: Pubkey,
    epoch: u64,                       // provisional window tracking
    user: Pubkey,
    completion_count: u32,
    best_time_s: u32,                 // best within this epoch window (for Legend)
    first_completed_at: i64,          // tiebreaker (ride-time)
    bump: u8,
}
// Closed after epoch finalization, rent refunded.

LocalLegend {
    vault: Pubkey,
    holder: Pubkey,                   // current seat holder
    term_start_epoch: u64,
    term_end_epoch: u64,
    elected_at_ride_completed_at: i64, // ride-time of the winning completion
    total_earned: u64,                 // populated at finalize_settlement_week (P16)
    bootstrap: bool,                   // true if this is a founder bootstrap seat
    bump: u8,
}
```

**New / renamed instructions:**

- `found_climb(canonical_signature, geography, metadata, founding_ride_attestation)` — creates a Climb account, registers founder provenance, optionally attaches a Vault via a follow-up call.
- `attach_vault(climb, economic_config)` — creates the Vault economic module for an existing Climb, one-to-one.
- `record_ride(ride_hash, canonical_trace_summary, parser_version, source_kind, completed_at, started_at, total_tss, cal_earned, climbs_crossed_summary, attestation_commitment)` — creates the RideAttestation. Signed by `backend_authority`. Deterministic from canonicalized input; replay impossible via PDA key.
- `credit_cal(ride_attestation, rider, amount)` — takes RideAttestation as input, creates CalMintReceipt child PDA (Anchor init prevents replay), mints CAL SPL via `CAL_MINT_AUTH`. Replaces the Merkle-based claim path entirely.
- `record_climb_completion(ride_attestation, climb, vault, cal_tribute)` — creates ClimbCompletionReceipt child PDA, updates Climb.total_completions, checks KOM and Record Board for potential updates, credits Vault.pending_rewards with the CAL tribute converted to DUNG-equivalent, updates VaultUserEpochStats for the current provisional epoch.
- `update_record_board(climb, new_entry_candidate)` — called from within record_climb_completion if new_time beats any existing entry. Bumps lower entries down. Event emission per seat change.
- `stake_cal_in_vault(vault, amount)` — creates VaultStake, sets `effective_from_epoch = current_epoch + 1`, deposits CAL.
- `unstake_cal_from_vault(vault)` — burns exit fee, returns principal, closes position.
- `harvest_staker_rewards(vault_stake)` — trivially transfers `unclaimed_rewards` to staker's ATA, zeros the field. No rate math.
- `finalize_settlement_week(climb, vault, current_epoch)` — the canonical settlement instruction. Replaces `distribute_epoch_rewards`. Must be called after `wall_clock_epoch_end + 86400`. Operations:
  1. Assert `current_epoch > vault.last_finalized_epoch` (epoch guard).
  2. Assert `Clock::get() >= EPOCH_ANCHOR + (current_epoch + 1) * EPOCH_DURATION + SETTLEMENT_FINALIZATION_GRACE_SECONDS`.
  3. Pre-scan eligible stakers (`effective_from_epoch + 1 <= current_epoch`) and apply the participation curve only to the current week's base 27% maximum. Add the policy-locked difference to the same week's Record Royalty. Add prior `carry_stakers` only after the curve; it represents already-unlocked pro-rata integer dust.
  4. Record Royalty: iterate `climb.record_board`, split the base 55% amount plus `carry_record_royalty` plus the current week's locked staker amount by rank percentages, emit `RecordRoyaltyPayout { epoch, climb, rider, rank, amount }` per recipient, and mint DUNG to each ATA. Update only undistributed Record Royalty residue to `carry_record_royalty`.
  5. Staker bucket: allocate the current week's unlocked amount plus prior unlocked dust pro rata, credit `VaultStake.unclaimed_rewards`, and emit `StakerAllocation { epoch, vault, staker, amount, stake_at_distribution }`. Update `carry_stakers` with pro-rata integer dust only.
  6. Local Legend bucket: if `local_legend_active`, mint `0.03 * (pending_rewards + carry_local_legend)` to `local_legend` ATA, emit `LegendPayout`, increment `LocalLegend.total_earned` (P16). If dormant, entire amount to `carry_local_legend`.
  7. POL: mint `0.05 * (pending_rewards + carry_pol)` to `program_config.pol_token_account`, emit event. Residue to carry_pol.
  8. Treasury: mint `0.10 * (pending_rewards + carry_treasury)` to `program_config.treasury_token_account`, emit event. Residue to carry_treasury.
  9. Set `vault.pending_rewards = 0`.
  10. Set `vault.last_finalized_epoch = current_epoch`, `vault.last_finalized_at = Clock::get()`.
  11. Emit `SettlementWeekFinalized { epoch, climb, vault, record_royalty_paid, stakers_paid, legend_paid, pol_paid, treasury_paid, carry_after }`.

- `finalize_legend_election(vault, current_epoch)` — reads chain-native stats to elect the new Legend. Called before `finalize_settlement_week` during the same finalization pass. See WS-6.
- `close_provisional_stats(vault, epoch)` — after finalization, close the `VaultUserEpochStats` PDAs for the finalized epoch, refund rent. Can be called in batches by the backend.

**Deleted from V4 (bundle with rename):**

- Instructions: `submit_allocation_batch`, `claim_user_cal`, `claim_and_convert_vault_alloc`, `distribute_epoch_rewards` (replaced), `record_vault_completion` (renamed), `create_vault` DUNG-burn path (orphan), `create_vault_with_usdc` (orphan), the V2/V3 migration cruft.
- Account structs: `AllocationBatch`, `UserCalClaim`, `VaultAllocClaim`, old monolithic `Vault` (replaced), `UserState` (moved to `RiderSoul`).
- Fields: `cal_tribute_accumulated`, `total_staked`, Synthetix math fields (`reward_per_token_stored`, `last_update_time`, `reward_rate`), `pending_rewards` as a single bucket (replaced by pool + carry).
- Helpers: `compute_user_cal_leaf`, `compute_vault_alloc_leaf`, `verify_merkle_proof`, Merkle domain constants, Merkle seeds.
- `VaultPaymentMethod::Cal` variant (dead, now removed with `admin_create_vault` replacement).

**Rename surface (P15 hard-rename):**

- Struct: `Vault` (monolithic) → `Climb` + `Vault` (decomposed)
- Struct: `VaultLeaderboard` → removed (Record Board is a field on Climb)
- Struct: `VaultCompletion` → `ClimbCompletionReceipt` (now keyed by ride_attestation)
- Struct: `UserState` → `RiderSoul`
- Instruction: `record_vault_completion` → `record_climb_completion`
- Instruction: `distribute_epoch_rewards` → `finalize_settlement_week`
- Instruction: `create_vault` + `admin_create_vault` + `create_vault_with_usdc` → `found_climb` + `attach_vault`
- Event: `VaultCompleted` → `ClimbCompleted`
- Event: `EpochRewardsDistributed` → `SettlementWeekFinalized`
- Field: `last_distribution_epoch` → `last_finalized_epoch`
- Field: `minter` → `founder`

**Sub-tasks:**

- [ ] **Provision fresh program keypair** — `solana-keygen new -o protocol/anchor/target/deploy/boulder_rollers-keypair.json` (new file). Capture pubkey.
- [ ] **Update `declare_id!`** in `protocol/anchor/programs/boulder_rollers/src/lib.rs`
- [ ] **Update `Anchor.toml`** `[programs.devnet]` entry
- [ ] **Update `addresses.devnet.json`** with new program ID
- [ ] **Update `backend/app/solana_env.py`** default fallback and any hardcoded references
- [ ] **Update `indexer/src/config.ts`** default program ID
- [ ] **Update `.env.example`** in all subprojects
- [ ] **Grep for retired devnet program IDs** and replace every active runtime/operator instance; keep historical references only behind an explicit allowlist
- [ ] **Rewrite the Vault struct** as two separate accounts (Climb + Vault)
- [ ] **Introduce RideAttestation account + `record_ride` instruction**
- [ ] **Introduce child receipt accounts** (ClimbCompletionReceipt, CalMintReceipt) with PDA keys that prevent replay
- [ ] **Introduce RiderSoul account** — fields per struct definition above
- [ ] **Introduce VaultUserEpochStats provisional account** for Legend derivation
- [ ] **Replace Synthetix fields with direct-allocation fields** (`VaultStake.unclaimed_rewards`, `effective_from_epoch`)
- [ ] **Introduce per-bucket carry fields on Vault** (5 u64 fields)
- [ ] **Rewrite `record_vault_completion` as `record_climb_completion`** — reads RideAttestation, creates ClimbCompletionReceipt, updates Climb, updates Record Board, credits Vault.pending_rewards
- [ ] **Rewrite `distribute_epoch_rewards` as `finalize_settlement_week`** — full implementation per the 10-step spec above
- [ ] **Implement `finalize_legend_election`** (hand-off to WS-6 for scheduler side)
- [ ] **Implement `close_provisional_stats`** batch-closing helper
- [ ] **Implement `update_record_board`** sort-and-bump logic with event emission
- [ ] **Implement `stake_cal_in_vault` / `unstake_cal_from_vault` / `harvest_staker_rewards`** with discrete allocation semantics
- [ ] **Implement `credit_cal`** with child receipt protection
- [ ] **Delete deprecated instructions** (Merkle path, old distribute, old record_vault_completion, old create_vault variants, V2/V3 migrations)
- [ ] **Add `SETTLEMENT_FINALIZATION_GRACE_SECONDS = 86400` constant**
- [ ] **Add ride-time canonicalization assertions** to `record_climb_completion` (KOM compare uses `ride_attestation.completed_at`, not `Clock::get()`)
- [ ] **Increment `LocalLegend.total_earned`** in `finalize_settlement_week` (P16 fix)
- [ ] **Add `update_program_config_admin_rotate` helper** for Key B admin signer path (coordinate with WS-7)
- [ ] **Regenerate IDL** via `anchor build && anchor idl build -o protocol/anchor/idl/boulder_rollers.json`
- [ ] **Rewrite Anchor test suite** — old tests against Merkle path, old distribute, old record_vault_completion get deleted. New tests against the V4 shape. Target: ≥60 passing tests post-rewrite.
- [ ] **Deploy program to devnet** via Ledger (Key A from WS-7), upgrade authority = Ledger
- [ ] **Initialize ProgramConfig V4** with `backend_authority = Key C`, `admin_authority = Key B`, `pol_token_account` and `treasury_token_account` from provisioned Squads wallets (or placeholder devnet ATAs)
- [ ] **Reseed climbs** via updated `backend/scripts/seed_climbs_onchain.py` (renamed from `seed_vaults_onchain.py`, rewritten for new ontology). Produces N fresh Climbs with optional attached Vaults.
- [ ] **Run Gate 1 direct-RPC smoke** to verify the chain layer. The direct and wallet-signed scripts now submit `record_ride` → `record_climb_completion` → `credit_cal`; the receipt-less compatibility instruction is not exposed by the Python client. Run the direct gate from the repository root with `python3 backend/scripts/smoke_devnet_economics.py`. This item remains open until the command succeeds against the intended devnet deployment. Passing Gate 1 proves the canonical receipt and retry lifecycle, not exact five-bucket payout math; exact balances, carries, supply, and conservation remain required under the `boulderroller-v2-klrj.8` math seaworthiness gate before the First Cohort settles.

**Blockers:** WS-2a, WS-4, WS-5 lands first as safety nets. WS-10 (canonicalization spec) must be written before V4 can be implemented in full.

---

### WS-2a — Backend Decoder Alignment (SAFETY NET, lands first)

**Goal:** Eliminate all hand-written Python decoders for on-chain accounts. After V4 lands, anything reading Climb/Vault/RideAttestation/etc from chain must use IDL-driven decoding.

**Drift IDs resolved:** the manual `get_vault_account()` landmine at `solana_direct.py:1684`, D028 (archived program imports).

**Sub-tasks:**

- [ ] **Audit `backend/app/` for all manual Borsh decoders.** Grep for `struct.unpack`, `int.from_bytes`, offset arithmetic against Solana account data. Catalog every instance.
- [ ] **Replace `get_vault_account()`** with an IDL-driven decoder using `anchorpy` or `solders.coders`. Plumb through the V4 IDL.
- [ ] **Drop archived program imports** — `dung_mint_program_id`, `proof_verifier_program_id` in `solana_direct.py:41-42` and `solana_env.py`. Fail closed if env vars are still set.
- [ ] **Add pre-commit hook** blocking manual Borsh decoder patterns in `backend/app/`. Scripts + tests + audit scripts are fine.
- [ ] **Update all Python decode call sites** to use the IDL decoder and the new account names (Climb, Vault, RiderSoul, RideAttestation)

**Blocker:** None. Lands first as a safety net.

---

### WS-2b — CAL → Ride Attestation Flow

**Goal:** Implement the new CAL issuance flow: backend produces canonical ride attestation → chain records RideAttestation → `record_climb_completion` credits vault tribute → `credit_cal` mints CAL to rider's ATA. Delete the Merkle batch pipeline entirely.

**Drift IDs resolved:** D006, D007 (CLAUDE.md instant-conversion claim), D008 (dead `total_cal_tributed`), D030 (orphan create_vault path).

**Sub-tasks:**

- [ ] **Update `backend/app/services/ride_processor.py`:**
  - Delete `CAL_ALLOCATION_MODE` env var and all batch-mode branches
  - Delete `_stage_cal_allocation` method
  - Call new `send_record_ride` to create RideAttestation on chain
  - For each matched climb, call `send_record_climb_completion`
  - After every completion receipt is confirmed, call `send_credit_cal` to mint CAL for the rider
  - All three take ride_attestation PDA as input
- [ ] **Add new transaction builders** in `backend/app/solana_direct.py`:
  - `make_record_ride_ix(ride_hash, canonical_summary, parser_version, source_kind, completed_at, started_at, total_tss, cal_earned, climbs_crossed, attestation_commitment)`
  - `make_credit_cal_ix(ride_attestation_pda, rider_ata, amount)`
  - `make_record_climb_completion_ix(ride_attestation_pda, climb_pda, vault_pda, cal_tribute)`
- [ ] **Update `backend/app/services/cal_allocator.py`** — DELETE (entire file)
- [ ] **Update `backend/app/services/allocation_batch_submitter.py`** — DELETE (entire file)
- [ ] **Update `backend/app/services/claim_executor.py`** — DELETE (entire file)
- [ ] **Update `backend/app/services/merkle_proof.py`** — DELETE (entire file)
- [ ] **Update `backend/app/main.py`** — delete allocation pipeline startup block (lines 184-209)
- [ ] **DB migration:** archive then drop `cal_allocation_staging`, `cal_allocation_batches`, `cal_allocation_leaves`
- [ ] **DB migration:** add `ride_attestations` projection table (indexer writes from chain events)
- [ ] **Add `vault_completions.cal_tribute_base_units` column** for indexer population from ClimbCompleted events

**Blocker:** WS-1 (needs V4 program deployed for the new instructions to exist).

---

### WS-3 — Backend Caller Fixes

**Goal:** Align backend transaction builders with the V4 access control model and truth boundary principles (P11, P13).

**Drift IDs resolved:** D003, D005, D027.

**Sub-tasks:**

- [ ] **`send_finalize_settlement_week` uses `resolve_backend_authority(config)`** as the authority signer. Mirror `send_record_climb_completion` pattern. Never use `config.payer.pubkey()` for admin operations.
- [ ] **Read ProgramConfig via RPC** in `tx_builder.py` for POL and treasury ATAs, not from indexed tables. P11.
- [ ] **Read `vault.last_finalized_epoch` via RPC** before submitting a finalize call. Skip if already finalized for this epoch. P11.
- [ ] **Replace silent stubs** in `solana_client.py:246` — raise on exception, don't return a stub response. Audit all callers for assumptions about the stub.
- [ ] **Decide on `cal_allocator.py:68` min-4-rides constraint** — delete entirely after cal_allocator is deleted; no constraint survives.
- [ ] **Remove `cal_tribute_accumulated` reads** from `epoch_processor.py:234` — field is deleted in V4, reader becomes dead code automatically, but grep and remove explicit references.
- [ ] **Update `epoch_processor.py`** to call `finalize_settlement_week` after the 86400s grace window (not immediately on wall-clock epoch boundary) and to iterate all Vaults with `pending_rewards > 0` in order.

**Blocker:** WS-1 (new instructions + accounts).

---

### WS-4 — Indexer Slot Fixes (SAFETY NET, lands first, SCOPE NARROWED)

**Goal:** Fix the slot=0 bugs in snapshot/reconciliation. The broader write_version hardening from the SOTA report is **deferred** — `write_version` is not available over `programSubscribe` (our current transport), only over LaserStream. Per decision #13, LaserStream is deferred.

**Drift IDs resolved:** the slot=0 race conditions (D023, D024). D022 (full slot-guard) moves to the post-LaserStream scope.

**Sub-tasks:**

- [ ] **Fix `indexer/src/modes/snapshot.ts:101`** — fetch `getSlot()` BEFORE `getProgramAccounts()` and pass it to `routeAccount` instead of slot=0.
- [ ] **Fix `indexer/src/reconciliation.ts:99`** — same pattern.
- [ ] **Add unit test** ensuring no writer call site passes slot=0 (lint rule or pre-commit grep).
- [ ] **DB migration:** add `chain_slot BIGINT NOT NULL DEFAULT 0` to every `indexed_*` table if not already present. Default 0 is fine for existing rows since new writes will overwrite.
- [ ] **Add `indexer_writes_total{account_type, outcome}` counter.** Observable even without slot-guard — tells us when writers fire.

**Deferred:** full conditional `ON CONFLICT ... WHERE excluded.chain_slot > t.chain_slot` upsert predicate. Cannot land without write_version from LaserStream. Documented in `LASERSTREAM_MIGRATION_BLUEPRINT.md` as post-migration work.

**Also corrected from earlier plan:** `EpochRewardsDistributed` is NOT currently dropped — it's already indexed via `indexer/src/modes/replay.ts:232` and served at `indexer/src/api.ts:463` (confirmed by external review). No new writer needed; just rename the event to `SettlementWeekFinalized` in the indexer-side handler when V4 lands.

**Blocker:** None. Lands first as a safety net.

---

### WS-5 — `distribution_receipts` Cleanup + Record Royalty Projection (IMMEDIATE cleanup)

**Goal:** Stop the live runtime crash in the harvest route, and replace the deleted `distribution_receipts` table with indexer-projected tables that mirror the new chain events (RecordRoyaltyPayout, StakerAllocation, LegendPayout, etc).

**Drift IDs resolved:** external F3 (runtime schema/code mismatch in `distribution_receipts`), external F6 (staker history reproducibility), F8 cleanup.

**Immediate hazard (historical):** the old `distribution_receipts`-backed harvest path was runtime-broken because it read columns that did not exist. The live harvest path has now been moved onto on-chain `VaultStake.rewards_earned`, but the stale table and any remaining readers/writers still need to be deleted so future agents do not rebuild around it.

**Sub-tasks:**

- [ ] **IMMEDIATE:** Finish deleting the old `distribution_receipts` accounting surface and any remaining readers/writers. The live harvest route no longer depends on it; canonical pending harvest state is read directly from on-chain `VaultStake.rewards_earned` in V4-A.
- [ ] **DB migration** — drop `distribution_receipts` table (after archiving for 30 days if Tim wants a safety backup).
- [ ] **Remove all remaining `distribution_receipts` references** from any non-harvest consumer (`epoch_processor.py`, stale reconciliation paths, old admin/reporting surfaces).
- [ ] **New indexer projection tables:**
  - `indexed_ride_attestations` — from RideAttestationRecorded events; keyed by (rider, ride_hash); source of truth for "has this ride been processed"
  - `indexed_climb_completions` — from ClimbCompleted events; keyed by (ride_attestation, climb); includes cal_tribute, ride_time_completed_at
  - `indexed_record_royalty_payouts` — from RecordRoyaltyPayout events; keyed by (epoch, climb, rider); full historical royalty tracking
  - `indexed_staker_allocations` — from StakerAllocation events; keyed by (epoch, vault, staker); full historical staker allocation tracking and payout history, not the live source of truth for claimable harvest balance
  - `indexed_legend_payouts` — from LegendPayout events; keyed by (epoch, vault); current legend earned history
  - `indexed_settlement_week_finalizations` — from SettlementWeekFinalized events; vault-level settlement audit trail
- [ ] **New indexer writers** under `indexer/src/writers/` for each new event type.
- [ ] **BoulderScan API endpoints** for historical queries — "what did wallet X earn from climb C?" returns joined projections.
- [ ] **Delete all off-chain redistribution logic** for empty leaderboard in `epoch_processor.py:759`. P10 rule: empty buckets carry within their bucket, and that carry is handled on-chain in `finalize_settlement_week`, not in Python.

**Blocker:** First part (immediate hazard fix) — NONE, lands first. Second part (indexer projections) — WS-1 for the new events to exist.

---

### WS-6 — Local Legend Rolling Stewardship

**Goal:** Implement the Local Legend election scheduler, derived from on-chain `VaultUserEpochStats`, integrated with finalization.

**Drift IDs resolved:** D017 (bootstrap/elected distinction), D018 (orphaned scheduler), D035 (no escape hatch).

**Architecture:**

- Scheduler lives in `backend/app/services/legend_stewardship_service.py` (renamed from the earlier `legend_election_service.py` proposal to match P3 vocabulary).
- Runs as a background task alongside `EpochProcessor`, polling every 60s.
- Only does work during the 24-hour grace window after wall-clock epoch end.
- Reads `VaultUserEpochStats` from chain (or via indexed projection) for the outgoing epoch window to determine winner.
- Submits `finalize_legend_election(vault, current_epoch)` → chain reads its own top-stats and sets the holder + term_end_epoch.
- Then `finalize_settlement_week` is invoked for the same vault, which pays the (just-elected) Legend.

**Winner determination (chain-native):**

`VaultUserEpochStats` PDAs are created by `record_climb_completion` when a user records their first completion in the provisional epoch for a given vault. They accumulate `completion_count`, `best_time_s`, `first_completed_at` (ride-time). At term end, the user with the highest `completion_count` wins. Tiebreaker: `first_completed_at ASC` (earliest completion in the term wins). Deterministic, chain-auditable.

The backend scheduler iterates `VaultUserEpochStats` for the outgoing term's 8-epoch window, identifies the winner, and submits `finalize_legend_election(winner_pubkey, term_stats_attestation)`. The chain can optionally verify by querying the stats PDAs itself, or trust the backend submission and emit an event.

**Sub-tasks:**

- [ ] **New `backend/app/services/legend_stewardship_service.py`** — mirroring `EpochProcessor` pattern, with `BackgroundJobLock` on "legend_stewardship".
- [ ] **Query VaultUserEpochStats via indexer projection** (`indexed_vault_user_epoch_stats`) for winner determination.
- [ ] **New DB migration** — `legend_elections` audit table with `UNIQUE(vault_id, new_epoch)` for idempotency.
- [ ] **New tx builder** `send_finalize_legend_election` in `solana_direct.py`.
- [ ] **Wire into `EpochProcessor._process_epoch_end()`** — calls legend election BEFORE `finalize_settlement_week` so the new Legend earns this epoch's 3%.
- [ ] **Wire into `main.py`** — start the service task alongside existing ones.
- [ ] **Metrics:** `legend_elections_total{outcome}`, `legend_election_errors_total{reason}`, `legend_vaults_in_bootstrap` gauge, `legend_stewardship_last_scanned_epoch` gauge.
- [ ] **Ops admin endpoints** for `run-now` and `status` (behind existing admin auth).
- [ ] **Tests:** unit + integration (devnet-gated) + smoke.
- [ ] **Kill switch:** `LEGEND_STEWARDSHIP_ENABLED` env var.
- [ ] **Bootstrap → elected transition:** scheduler treats a bootstrap Legend the same as elected — if their term_end_epoch has passed and they're still the top completer, they get re-elected seamlessly.
- [ ] **Zero-completions handling:** if no eligible completions in the term window, dormant the seat (`local_legend_active = false`), legend share carries within `carry_local_legend` (P10).

**Blocker:** WS-1 (VaultUserEpochStats PDAs must exist; LocalLegend account must have new fields).

---

### WS-7 — Key Management Hardening

**Goal:** Implement the 5-key architecture (Upgrade A, Admin B, Backend C, FeePayer D, Funding E) as part of the V4 redeploy. No plan changes from previous design iteration.

**Drift IDs resolved:** key management blast radius correction (external F3 from the first review).

Full sub-task list is unchanged from previous revision. Key points:

- Ledger Nano S Plus for Keys A and B (paths 0 and 1)
- Doppler free tier for Keys C and D (secret storage on droplet)
- The coherence redeploy is the first forcing function: deploy the fresh program ID with Ledger as upgrade authority; initialize ProgramConfig with `backend_authority = Key C`, `admin_authority = Key B`, then preserve that authority split through the later ontology lift
- **Rotation drill required** immediately after migration on devnet — rotate Key C from Ledger (Key B) as the critical validation step
- Multisig (Squads) deferred to TGE

**Framing correction (P13):** the backend key C has direct CAL mint power via `credit_cal` and direct climb reward influence via `record_climb_completion`. The blast radius is not "cannot mint outside intended flow" — it's "every mint is cryptographically committed to a RideAttestation, which is cryptographically committed to a canonicalized ride hash, which is reproducible from the source ride file." Attack requires forging both the attestation AND a valid-looking ride file that canonicalizes to the same hash. The combination is auditable end-to-end via the indexer projection of RideAttestation events.

**Blocker:** Coordinates with the coherence redeploy first, then with the later ontology lift.

---

### WS-8 — Dead Code + Doc Cleanup (tails WS-1 through WS-7)

**Goal:** Strip stale references, fix docs, rename at the API surface, propagate PROTOCOL_TRUTHS vocabulary.

**Drift IDs resolved:** D011 (dead indexer writer references), D013 (stale comments), D014 (50 vs 100 DUNG docstring), D019-D021 (BeetleCard doc drift), D028 (archived imports), D029 (smoke script updates), D033 (init_if_needed rent documentation), D034 (CAL batch brittleness note), D036 (BeetleCard access asymmetry documentation).

**Sub-tasks:**

- [ ] **Indexer dead list cleanup** — remove `Segment`, `SegmentCounter`, `Claim`, `MerkleBatch` references in `writers/index.ts:82-89` and `decoder.ts:10-13`.
- [ ] **CLAUDE.md full rewrite of the key flows section** — rewrite around PROTOCOL_TRUTHS ontology (Climb-first, Settlement Weeks, Record Royalty, etc). Quote the principles section.
- [ ] **docs/FRESHEST_SPEC.md rewrite** — align with V4 chain state, new account structs, new instructions.
- [ ] **docs/DETECTOR_PARAMS.md** — no changes expected, detector is orthogonal.
- [ ] **BoulderScan UI copy** — update from "leaderboard" to "Record Board", "epoch" to "Settlement Week", "Vault" to "Climb (with Vault)" where it improves clarity. P15.
- [ ] **Remove stale `VaultPaymentMethod::Cal` references** — already deleted in WS-1, cleanup any backend references.
- [ ] **BeetleCard doc fixes** — off-by-one in CLAUDE.md upgrade cost table, hybrid-model status update, elite gate enforcement status.
- [ ] **Backend stale comments** — points-period language in `solana_direct.py` around old admin_create_vault, `send_create_vault` 50-DUNG docstring fix.
- [ ] **Smoke script updates** — `smoke_devnet_economics.py` rewritten for V4 shape (new account names, new instructions, new event names).
- [ ] **Archive `migrate_v3_security.ts`** — delete, reference in git history only. It was a warning-only reporter with a broken size check that would have missed the target vaults.

**Blocker:** Tails all other workstreams.

---

### WS-9 — RiderSoul Layer (NEW)

**Goal:** Implement the soulbound rider identity account, split from `UserState`. P12.

**Drift IDs resolved:** none directly (new surface).

**Sub-tasks:**

- [ ] **New `RiderSoul` account struct** defined in the Phase 2 ontology lift. Fields: total_rides, total_tss, total_distance_m, total_vert_m, total_cal_earned, archetype, bio_score, BeetleCard references.
- [ ] **New `initialize_rider_soul` instruction** — created on first `record_ride` call for a new rider. Idempotent via PDA seed `[b"rider_soul", rider_pubkey]`.
- [ ] **Increment fields in `record_ride`** — `total_rides += 1`, `total_tss += ride.total_tss`, etc. Monotonic.
- [ ] **BeetleCard derivation** — `climb_card`, `steady_card`, `explorer_card` become references from RiderSoul to BeetleCard PDAs. `increment_beetle_score` reads RiderSoul for context.
- [ ] **Delete `UserState` account** in the ontology lift once RiderSoul is live and projections have been cut over.
- [ ] **Update backend services** to read RiderSoul where they previously read UserState.
- [ ] **Update indexer writer** — new `indexed_rider_souls` projection table, writes from RiderSoul account events.
- [ ] **BoulderScan API** — `/v1/riders/:pubkey` returns RiderSoul projection instead of old UserState.

**Blocker:** Phase 2 ontology lift, after the coherence redeploy and both smoke gates are green.

---

### WS-10 — Ride Canonicalization Spec (NEW, must land before V4 implementation)

**Goal:** Formalize the canonicalization rules for `ride_hash` derivation. P5.

**Drift IDs resolved:** none directly (new surface). Enables WS-1 and WS-2b.

**Spec contents (to be written as `docs/design/RIDE_CANONICALIZATION_SPEC.md`):**

- What fields are part of the canonical trace (GPS points quantized to 6 decimal places, sensor samples at 1s intervals, elevation from ride file, power/HR/cadence where present)
- What fields are NOT part of the canonical trace (metadata, comments, device serial numbers, timestamps in metadata headers)
- Serialization format (canonical JSON with sorted keys, or protobuf-serialized)
- `parser_version` — an integer that increments when the canonicalization rules change
- Backwards compatibility — old parser_versions remain queryable; new rides use the current version
- Migration strategy when canonicalization evolves
- The hash: `ride_hash = SHA256(canonical_serialized_bytes)`
- Test vectors — a set of known input files and their expected canonical hashes, for cross-implementation validation

**Sub-tasks:**

- [ ] **Write the spec** in `docs/design/RIDE_CANONICALIZATION_SPEC.md`
- [ ] **Implement canonicalization in `workout-parse` Rust crate** — add `canonicalize(activity: &Activity, version: u32) -> Vec<u8>` function
- [ ] **Expose via PyO3 binding** — `workout_parse.canonicalize_trace(activity, parser_version=1)`
- [ ] **Call from `backend/app/services/ride_processor.py`** — compute `ride_hash` before creating RideAttestation
- [ ] **Add test vectors** — 5-10 known FIT files with expected canonical hashes, committed to `workout-parse/tests/fixtures/`
- [ ] **CI test** — canonicalization tests run on every Rust change

**Blocker:** None. Must land before WS-1 implementation begins.

---

## Sequencing

```
Phase 0: Safety nets (can land in parallel)
    ├── WS-2a Backend Decoder Alignment
    ├── WS-4  Indexer slot=0 fixes
    └── WS-5  distribution_receipts immediate cleanup

Phase 1: Specs and prerequisites
    ├── WS-10 Ride Canonicalization Spec (required before WS-1 impl)
    └── WS-7  Ledger + Doppler provisioning (coordinated with WS-1)

Phase 2: V4-A Coherence Redeploy (critical path)
    └── Subset of WS-1 only
        ├── Fresh program ID
        ├── Delete Merkle path
        ├── Replace Synthetix accrual with direct allocation
        ├── Add settlement-week finalization + 24h grace window
        ├── Add per-bucket carry
        └── Keep Vault-centered account compatibility where that reduces blast radius

Phase 3: Backend alignment + coherence validation
    ├── WS-2b CAL flow rewrite against V4-A chain shape
    ├── WS-3  Backend caller fixes
    ├── WS-6  Local Legend Stewardship service (compatibility version)
    ├── WS-5  (part 2) Indexer projection tables for new events
    ├── Gate 1 — Direct-RPC chain smoke
    └── Gate 2 — Full-stack smoke

Phase 4: V4-B Ontology Lift (only after both gates are green)
    ├── Remaining WS-1 target-state items
    ├── WS-9  RiderSoul layer
    ├── First-class RideAttestation PDA + child receipts
    └── Hard rename propagation to canonical vocabulary

Phase 5: Cleanup and doc propagation
    └── WS-8  Dead code + doc cleanup

Phase 6 (future, not in current scope):
    └── Tier 2 — LaserStream migration (blueprint filed, revenue-gated)
```

---

## Gate Criteria

**Alignment is not complete until both smoke gates pass.**

### Gate 1 — Direct-RPC Chain Smoke

**Script:** `backend/scripts/smoke_devnet_economics.py` (run from the repository root with `python3 backend/scripts/smoke_devnet_economics.py`)

**What it exercises:**
1. Create or resume one deterministic active vault bound to an exact finalizable Settlement Week.
2. Decode and validate the finalized RideAttestation, ClimbCompletionReceipt, and CalMintReceipt prefix before mutation.
3. Submit only the missing suffix of `record_ride` → `record_climb_completion` → `credit_cal` and verify the exact expected pending-reward and CAL-remainder state.
4. Create or resume one exact first-staker CAL/LP position and reject foreign, fractional, missing, or zero-reward settlement states.
5. Distribute the bound Settlement Week and verify that exact flow advances and the staker receives a positive claim.
6. Withdraw the exact remaining LP amount, harvest the claim, and verify the persistent stake account reaches the durable zero-principal, zero-claim state.

**What it proves:** The V4 receipt-backed chain lifecycle is internally consistent, retryable at every persisted prefix, and runnable via direct RPC.

**What it does not prove:** Exact five-bucket payout balances, carry conservation, supply accounting, or multi-week composition. Those are launch requirements of `boulderroller-v2-klrj.8`, not claims made by this smoke.

### Gate 2 — Full-Stack Smoke

**Script:** `backend/scripts/smoke_full_stack.py` (NEW — must be written)

**What it must do:**
1. Start from clean devnet state (fresh reseeded climbs)
2. Upload a synthetic FIT file via the real API `/rides/upload` endpoint
3. Verify `RideProcessor` produces a canonical ride hash matching the spec
4. Verify backend submits `record_ride` → `record_climb_completion` → `credit_cal` to chain
5. Verify RideAttestation PDA exists with expected fields
6. Verify ClimbCompletionReceipt child PDA exists (replay protection)
7. Verify indexer populates `indexed_ride_attestations`, `indexed_climb_completions`, `indexed_rider_souls`
8. Advance wall-clock to epoch boundary, wait grace period
9. Verify `legend_stewardship_service` runs and submits `finalize_legend_election`
10. Verify `epoch_processor` calls `finalize_settlement_week`
11. Verify all events indexed and queryable via BoulderScan API: `/v1/accounts/:rider` shows CAL + DUNG balance, `/v1/climbs/:id/record-board` shows top-10, `/v1/climbs/:id/history` shows settlement payouts per week
12. Verify a user can harvest staker rewards via the production `/vaults/:id/harvest` route (not the runtime-crashing old path)

**What it proves:** the full production service graph is coherent end-to-end and can drive the full tokenomics loop without manual intervention.

**Both gates must be green on devnet before any handoff to mainnet or TGE work.**

---

## Rollback

**If WS-1 redeploy fails:**
1. **Fresh program ID** means the old program + old accounts are still deployed and running (stale but intact). We can roll back by pointing backend/indexer/frontend configs at the old program ID. Backend services keep functioning in the "pre-alignment" state.
2. **New V4 program becomes dead weight** — can be abandoned or re-upgraded via Ledger once the issue is fixed.
3. **No data loss** — old devnet state is test data, new V4 state is also test data, nothing economically significant.

**If Gate 2 smoke fails after Gate 1 passes:**
- Chain layer is correct, backend/indexer integration has a bug. Diagnose + fix in place, re-run Gate 2. No rollback needed.

**If a specific workstream hits an unknown blocker:**
- Revert the workstream's commits via git. Other workstreams that don't depend on it continue.
- Document the blocker in this file under a new "Known Blockers" section, triage with Tim, iterate.

---

## Appendices

### A — Files Expected to Be Touched (estimated)

**Rust / Anchor (V4 redeploy):**
- `protocol/anchor/programs/boulder_rollers/src/lib.rs` — substantial rewrite (account structs, instructions, event names)
- `protocol/anchor/idl/boulder_rollers.json` — regenerated
- `protocol/anchor/Anchor.toml` — new program ID
- `protocol/anchor/addresses.devnet.json` — new program ID
- `protocol/anchor/tests/*.ts` — rewritten for V4 shape
- `protocol/anchor/scripts/migrate_v3_security.ts` — DELETE
- `protocol/anchor/scripts/wipe_devnet_vaults.ts` — NOT NEEDED (fresh program ID, no wipe required)

**Rust (canonicalization):**
- `workout-parse/src/canonicalize.rs` — NEW
- `workout-parse/src/lib.rs` — PyO3 binding for canonicalize
- `workout-parse/tests/fixtures/` — test vectors

**Python backend:**
- `backend/app/solana_direct.py` — new tx builders, deleted old ones, IDL-driven decoders
- `backend/app/solana_client.py` — silent stub removal
- `backend/app/solana_env.py` — new program ID defaults, archived import removal
- `backend/app/services/ride_processor.py` — canonical hash integration, new tx flow
- `backend/app/services/epoch_processor.py` — finalize_settlement_week integration, grace-window awareness
- `backend/app/services/legend_stewardship_service.py` — NEW
- `backend/app/services/cal_allocator.py` — DELETE
- `backend/app/services/allocation_batch_submitter.py` — DELETE
- `backend/app/services/claim_executor.py` — DELETE
- `backend/app/services/merkle_proof.py` — DELETE
- `backend/app/services/tx_builder.py` — RPC-based ProgramConfig reads
- `backend/app/routes/vaults.py` — harvest route rewrite, distribution_receipts removal
- `backend/app/repositories/vault.py` — V4 decode
- `backend/app/main.py` — delete allocation pipeline block, add legend stewardship service
- `backend/scripts/seed_climbs_onchain.py` — RENAMED from seed_vaults_onchain.py, rewritten for V4
- `backend/scripts/smoke_devnet_economics.py` — rewritten for V4
- `backend/scripts/smoke_full_stack.py` — NEW

**TypeScript indexer:**
- `indexer/src/config.ts` — new program ID
- `indexer/src/decoder.ts` — V4 account decoding, dead references removed
- `indexer/src/writers/` — new writers for Climb, RideAttestation, RiderSoul, VaultUserEpochStats, all new event types
- `indexer/src/modes/snapshot.ts` — slot=0 fix
- `indexer/src/reconciliation.ts` — slot=0 fix, V4 account checks

**SQL migrations:**
- `backend/sql/...` — drop distribution_receipts, new projection tables, ride_attestations indexing, staker_allocations indexing, record_royalty_payouts indexing
- Archive cal_allocation_staging/batches/leaves

**Docs:**
- `CLAUDE.md` — key flows rewrite, PROTOCOL_TRUTHS quoting
- `docs/FRESHEST_SPEC.md` — V4 alignment
- `docs/design/PROTOCOL_ALIGNMENT_FIX_PLAN.md` — this file
- `docs/design/RIDE_CANONICALIZATION_SPEC.md` — NEW
- `docs/design/LASERSTREAM_MIGRATION_BLUEPRINT.md` — referenced, not currently modified

### B — Drift Matrix Reference

The original Phase A audit produced a 36-entry drift matrix at `docs/design/PROTOCOL_ALIGNMENT_AUDIT.md` (to be extracted from the Phase A agent transcript and committed). This plan supersedes it — every drift resolved by one or more workstream sub-tasks above. Cross-reference table:

| Drift | Workstream | Status |
|---|---|---|
| D001 (Vault struct size) | WS-1 | Resolved via fresh program ID |
| D002 (dead vault_pot) | WS-1 | Removed in V4 rewrite |
| D003 (signer fix) | WS-3 | Addressed |
| D004 (indexer last_distribution_epoch) | WS-4/WS-5 | Resolved via new event projection |
| D005 (check on-chain guard) | WS-3 | RPC-based pre-check |
| D006 (pending_rewards vs cal_tribute_accumulated) | WS-2b | Refactor deleted entirely |
| D007 (CLAUDE.md doc drift) | WS-8 | Rewrite |
| D008 (dead total_cal_tributed) | WS-1 | Removed |
| D009 (dead total_staked) | WS-1 | Removed |
| D010 (claims not indexed) | WS-2b | Merkle path deleted entirely |
| D011 (dead indexer references) | WS-8 | Cleanup |
| D012 (vault creation init inconsistency) | WS-1 | Rewrite (found_climb + attach_vault) |
| D013 (stale comments) | WS-8 | Cleanup |
| D014 (docstring 50 vs 100 DUNG) | WS-8 | Doc fix |
| D015 (dead VaultPaymentMethod::Cal) | WS-1 | Removed |
| D016 (staking exit fee burn vs spec) | WS-8 | Doc update (pure burn per decision 15) |
| D017 (bootstrap vs elected distinction) | WS-6 | `bootstrap: bool` on LocalLegend |
| D018 (orphaned elect_local_legend) | WS-6 | Scheduler implemented |
| D019-D021 (BeetleCard doc drift) | WS-8 | Doc fixes |
| D022 (writer slot-guard) | WS-4 (partial) | Deferred to post-LaserStream for full guard |
| D023 (snapshot slot=0) | WS-4 | Fixed |
| D024 (reconciliation slot=0) | WS-4 | Fixed |
| D025 (indexer V3 fields) | WS-4/WS-5 | New projection tables |
| D026 (ProgramConfig decode drift) | WS-1 | Resolved via fresh redeploy |
| D027 (silent stub) | WS-3 | Raise instead |
| D028 (archived program imports) | WS-2a | Removed |
| D029 (smoke script inheritance) | WS-8 | Scripts rewritten |
| D030 (orphan create_vault) | WS-1 | Deleted |
| D031 (broken migration script) | WS-1 | N/A (fresh program ID) |
| D032 (EpochRewardsDistributed indexing) | WS-4 | Already indexed, rename on V4 |
| D033 (init_if_needed rent) | WS-8 | Documented |
| D034 (CAL batch brittleness) | WS-2b | Merkle path deleted entirely |
| D035 (no escape hatch) | WS-6 | Dormant seat + carry forward |
| D036 (BeetleCard access asymmetry) | WS-8 | Documented |

External review additions:
- F1 (staking Synthetix math) → WS-1 (discrete allocation replaces reward_rate math entirely)
- F2 (attestation idempotency) → WS-1 (child receipt PDAs)
- F3 (trust model framing) → P13, WS-7 framing
- F4 (fresh program ID) → WS-1 decision #1
- F5 (Legend time basis) → WS-6, P6 ride-time anchoring
- F6 (staker history) → WS-5 projection, P8 discrete allocation
- F7 (RPC vs indexer for writes) → P11, WS-3
- F8 (write_version unavailable) → WS-4 narrowed scope
- F9 (internal contradictions) → WS-8 cleanup
- F10 (dust policy) → P10 per-bucket carry
- F11 (staker unlock gaming) → P9 full-epoch participation

---

**End of plan.**

This document is stable and ready for handoff to a fresh execution agent, with
the explicit instruction to honor the Execution Discipline section above:
coherence first, ontology lift second.
