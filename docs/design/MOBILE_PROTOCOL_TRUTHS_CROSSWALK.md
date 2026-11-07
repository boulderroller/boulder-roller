# Mobile ↔ PROTOCOL_TRUTHS Crosswalk

**Status:** DRAFT
**Last revised:** 2026-04-15
**Completion addendum:** 2026-07-14. The canonical receipt-backed path is
`record_climb_completion_v2`; both the tribute-unbound V1 instruction and the
retained `record_vault_completion` ABI shell fail closed. Mobile may display an
exact climb tribute only when the API reports `tributeBound`.
**Author:** Claude + Tim
**Semantic authority:** [`docs/PROTOCOL_TRUTHS.md`](../PROTOCOL_TRUTHS.md)
**Applies to:** Figma file `PUq5mp1WnFPMqcCuJfgQaP`, `docs/design/MOBILE_DATA_CONTRACTS.md`, `docs/rfcs/RIDER_ARCHETYPES.md`, `mobile/src/**`
**Related:** [`docs/design/LANGUAGE_SPEC.md`](./LANGUAGE_SPEC.md) (chain↔UX language rules this doc extends)

---

## 0. Purpose

`PROTOCOL_TRUTHS.md` was authored 2026-04-15, after most mobile and Figma work was already in flight. This doc is the translation layer. It says:

- where mobile surfaces are already aligned with TRUTHS
- where they drift and how to fix them without re-breaking shipped frames
- which terms are **chain-canonical** (must match TRUTHS in code, schemas, events) and which are **UX-surface** (can keep a more culturally legible label)
- what the mobile scaffolding owes the `wdvr` protocol alignment epic and vice versa

If this doc conflicts with `PROTOCOL_TRUTHS.md`, TRUTHS wins. If it conflicts with a shipped Figma frame that Tim has approved, the frame wins and this doc gets updated to match.

---

## 1. The language split: canonical vs UX

Tim's rule (2026-04-15): *"we should keep leaderboard. it IS a Record Board. but leaderboard is the cultural fit."*

This is the core crosswalk principle. Some TRUTHS terms are **chain-canonical** — they belong in account struct names, instruction names, event names, schemas, IDL, and internal docs. Others are **UX-surface** — the cultural fit for riders, used in screen copy, tab labels, and toast text.

**Chain-canonical terms** (use exactly as written in `lib.rs`, indexer, API types, CLAUDE.md, FRESHEST_SPEC):

| Term | Definition |
|---|---|
| `Climb` | Primary permanent geographic object. Founder, KOM, Record Board, lifetime metrics. |
| `Vault` | Optional economic module attached to a Climb. Holds pending rewards, staker state, carry, Local Legend seat. |
| `Record Board` | All-time top 10 on a Climb. Permanent record truth. |
| `Record Royalty` | The 55% bucket that pays the Record Board permanently. |
| `Local Legend` | Rolling stewardship seat (3% bucket). |
| `Settlement Week` | Economic settlement clock (7-day cadence). |
| `Founder` | Wallet that first brought the Climb into protocol form. Replaces `minter`. |
| `RiderSoul` / `Beetle Score` | Soulbound effort identity layer, separate from CAL balance. |
| `CAL` | Transferable work/currency token. |
| `DUNG` | Reward/value token. |
| `RideAttestation` | First-class protocol commitment that a ride happened once. |

**UX-surface terms** (what riders see — may diverge from canonical when the cultural fit is clearer):

| Canonical | UX-surface label | Rationale |
|---|---|---|
| Record Board | **Leaderboard** | Riders understand "leaderboard." Tim 2026-04-15: *"leaderboard is the cultural fit."* Internal semantics stay Record Board. |
| Record Royalty | **Leaderboard earnings**, or just **Earnings** if space-constrained | Same reason. "Record Royalty" is the *explainer* you say once in onboarding, not the tab label. |
| Settlement Week | **This week / last week** | The clock is invisible to the rider. Labels refer to time windows, not the mechanism. |
| Climb (object) | **Climb** (kept — already the cultural term) | Chain and UX converge. |
| Vault (economic module) | **Vault** (kept, same reason) | Chain and UX converge. |
| Local Legend | **Local Legend** (kept) | Already culturally readable. |
| Founder | **Founder** | Replace `minter` wherever it surfaces in copy. |
| RiderSoul (account) | **BeetleCard** (visual), **your rider** (copy) | BeetleCard is the display artifact, RiderSoul is the underlying account. |
| CAL / DUNG | **CAL / DUNG** | Tokens keep their names. |

**Rule of thumb:** if a rider would be confused, use the UX-surface label. If a developer would be confused, use the canonical term. Both layers exist intentionally.

---

## 2. Where mobile is already aligned (keep)

These choices pre-dated TRUTHS but landed on the right shape. Don't churn them.

- **`BeetleCard_v5` (frame `37:2`)** is the RiderSoul surface. PROTOCOL_TRUTHS §7.3 names the soulbound effort layer "Beetle Score / Soul" — BeetleCard matches. Level = lifetime TSS, archetype derived from power profile, curve as evidence — exactly the shape TRUTHS wants.
- **`ClimbDetail_*_v6` frame naming** (not `VaultDetail`). Climb is already primary in the mobile vocabulary, Vault is already the attached economic view inside the Climb detail screen. TRUTHS §2 locked in, frames already correct.
- **`docs/rfcs/RIDER_ARCHETYPES.md` §Matchup:** *"Matchup is purely cosmetic. Zero effect on CAL allocation, vault rewards, leaderboard sorting."* This matches TRUTHS §7.3's hard invariant *"Capital may buy exposure to a climb. Capital may not buy riderhood."* The archetype is effort-derived, non-transferable, decorative — exactly right.
- **`BoulderRolled_v5` (frame `34:2`) hero celebrates the ride-as-a-whole, not a single climb.** The ride-level framing is what lets post-ride present *multiple* climbs in the Tribute Cascade below the hero. Locked, don't touch.
- **"CAL Tribute Cascade"** in BoulderRolled. TRUTHS P1 flow: CAL earned from TSS → tribute flows to each Climb's Vault → gets bucketed into the 5-way carry. The Cascade visualizes tribute, which is correct. Keep.
- **Mobile API read shape (`VaultSummary` in `mobile/src/lib/api.ts:53`)** — the *fields* are all TRUTHS-compatible (`name`, `komHolder`, `komTimeS`, `totalStaked`, `stakerCount`, `vertM`, `distanceM`, `avgGradientPct`). Only the *container name* will change in V4-B.

---

## 3. Live drift — specific fixes

### 3.1 `ClimbDetail_Economy_v6` is missing the Leaderboard-earnings stream (frame `46:2`)

**The problem.** The v6 Economy body models exactly one income stream: staker yield on `YOUR STAKE`. Structure today:

```
STAKE card        YOUR STAKE  1,000 CAL  10% APY    [Withdraw] [+ Add]
PENDING card      +23.4 CAL                          [Collect]
WALLET card       150,959 CAL available              (info only)
STAKERS row       STAKERS 47          YOUR SHARE 0.1%
```

Under PROTOCOL_TRUTHS §8 there are **three** DUNG income streams a rider can see on a single climb:

1. **Staker yield** — pro-rata of the 27% bucket. You opt in by staking. (Already modeled.)
2. **Leaderboard earnings** (= Record Royalty, canonical) — the 55% bucket, permanent, paid to the all-time top 10. You opt in by *riding fast*. (Missing.)
3. **Local Legend yield** — 3% bucket, rolling seat. You hold it by being the most active rider in the term. (Missing from Economy, but it's visible on the Leaderboards tab in other ways.)

A rider who holds Leaderboard seat 3 on Hill Rd. has no way to see their Leaderboard earnings stream on the Economy tab today. That is the core drift.

**The fix — ULTRA CAREFUL, minimum structural change.** Insert a **conditional card above the Stake card**, shown only when the viewing rider is currently holding a Leaderboard seat on this climb. Card design reuses existing tokens exactly — no new visual language.

Proposed structure (cream/olive, no gold — Tim's gold budget is reserved for BoulderRolled "you broke into the Leaderboard" hero moment per §3.3):

```
LEADERBOARD card      ┌─────────────────────────────────────┐  ← y=~460, above Stake
(conditional)         │ YOUR SEAT  #3 of 10       │ 8.2% cut │   micro-label + rank chip inline
                      │ +47.1 CAL  earned this week          │   Inter Bold 24pt cream + olive caption
                      │                            [Claim]   │   chip only, no primary button
                      └─────────────────────────────────────┘
```

- **Micro label** `LEADERBOARD` (not `RECORD BOARD` — cultural fit rule from §1). 9pt Bold olive, letterSpacing 1.44px (matches v6 header grammar).
- **Rank chip** `#3 of 10` right-aligned, uses existing chip spec from handoff (80w × 34h, cornerRadius 17, cream @ 8% fill, cream @ 22% stroke).
- **Cut caption** `8.2% cut` — the fixed rank split percentage (30/20/15/10/8/6/5/3/2/1 from TRUTHS §8.1). Inter Semi Bold 11pt olive.
- **Big number** `+47.1 CAL earned this week` — Inter Bold 24pt cream for the number, 12pt Semi Bold olive inline for the `CAL earned this week` suffix. Matches Pending card grammar from v6.
- **`[Claim]` chip** — same chip spec as Withdraw/Add/Collect. Positioned right-aligned at (281, ~500).
- **Hairline separator** at y=~548 between this card and Stake. Same 329w × 1h cream @ 6% — matches existing card separators.

**Critical visual rules to preserve (Tim's "ULTRA careful"):**

1. **No gold.** The gold budget stays at BoulderRolled hero moment (breaking into the Leaderboard is the gold moment; earning royalty on it is chrome). The card is pure cream/olive.
2. **Conditional rendering.** Riders not on any Leaderboard seat never see this card. The v6 Economy frame for a non-seated rider is *unchanged*. This is additive, not destructive.
3. **Chip-only interaction.** No full-width primary button. `[Claim]` follows the same chip-on-card pattern as `[Collect]` on Pending. This preserves Tim's rule: *"context-anchored chips, no full-width buttons."*
4. **The Pending card stays.** Pending = staker yield waiting to collect. Leaderboard card = royalty waiting to claim. Two separate streams, two separate cards, two separate verbs (Collect vs Claim). Don't merge them — that collapses semantic distinction TRUTHS §3 explicitly wants preserved (*"Permanent Truth through the Record Board, recent stewardship through Local Legend, capital support through staking"*).
5. **Vertical order:** Leaderboard (conditional, topmost if shown) → Stake → Pending → Wallet → Stakers row. Permanent-first, then opt-in staking, then informational. This matches the economic-priority order in TRUTHS §8.

**What this fix does NOT touch:**
- Header (frame-shared, locked at v6 "faithful v3 restoration" per 2026-04-15 handoff)
- Tab toggle (still `Leaderboard | Economy`)
- Stake / Pending / Wallet / Stakers rows (exact v6 spec preserved)
- Any existing hairlines, chips, or tokens
- BoulderRolled (§3.3 has separate treatment)

**Rider-needs-no-explanation test.** The card answers the question *"what am I earning from holding a seat?"* without ever saying "Record Royalty" in the copy. A rider sees `YOUR SEAT #3` and `+47.1 CAL earned this week` and understands. The canonical name is in TRUTHS and CLAUDE.md for developers; the UX says what the rider needs.

### 3.2 Tab label stays `Leaderboard` (NOT `Record Board`)

Per Tim 2026-04-15: keep `Leaderboard` as the tab label on ClimbDetail. It's the cultural fit. Internally the chain and docs call it the Record Board; the tab toggle says Leaderboard. That's fine — it's the same language split §1 locks in.

**What that means concretely:**
- `ClimbDetail_Leaderboards_v6` frame `42:2` — tab label stays `Leaderboard` (singular — Tim's v6 uses plural, singular is cleaner; minor patch if rebuilding).
- `backend/app/routes/vaults.py` endpoint `GET /vaults/{id}/leaderboard` — name stays (UX-facing route).
- `lib.rs` account field currently `VaultLeaderboard` — **this one renames** to `record_board` as a field on `Climb` in V4-B per WS-1 spec. Chain-canonical.
- `indexer/src/writers/*` — chain-canonical names in code, UX-surface in API response field names.

**Recommended patch when BeetleCard/Map v6 pass happens:** if the ClimbDetail frames get re-touched for any reason, tighten `Leaderboards` → `Leaderboard` (singular) on the tab toggle. Don't open the frames just for this.

### 3.3 BoulderRolled: "Best Placings" ambiguity

**Current `BoulderRolled_v5` (frame `34:2`)** has a "Best Placings" card listing per-vault rank badges. TRUTHS §3.1 makes a distinction the current design blurs:

- **Permanent Truth** — entering the all-time Leaderboard (e.g. `You broke into Hill Rd. Leaderboard — seat 3`). This is the economically meaningful moment. It unlocks Leaderboard earnings forever until dethroned.
- **Rolling Truth** — your rank this week (`You finished #7 on Hill Rd. this week`). Informational, cosmetic, no permanent economic consequence.

The v5 "Best Placings" inline row reads both events as the same shape, collapsing them into one chrome list.

**The fix (proposal, not committed):**

1. **Promote Leaderboard entries to their own gold moment.** A rider who broke into the top 10 on any climb during the ride gets a standalone mini-hero above the Tribute Cascade — gold ring, gold rank number, cream climb name. E.g. `LEADERBOARD · Hill Rd. · SEAT 3`. This is a *permanent* unlock and deserves the gold budget allocation.
2. **Demote weekly placings to olive chrome inside the Cascade rows.** Each climb row in the Tribute Cascade can show weekly-rank caption `#7 this week` in olive, 11pt, right-aligned. No badge, no gold, no hero treatment.
3. **Gold budget for BoulderRolled** — currently "level number + tribute total" (2 moments). The new Leaderboard entry moment is conditional (only on rides where a seat was broken), and when it triggers, it *replaces* one of the existing gold moments — probably tribute total, which can drop to cream. Never exceed 2 gold moments per screen.

This fix is **lower priority than §3.1** because it only affects rides that break into a Leaderboard, which are rare. §3.1 affects every Economy tab view for any seated rider. Queue §3.3 as a polish pass, not a ship-blocker.

### 3.4 `Map_v5` preview sheet `APY` is a lossy collapse

The Map climb preview shows `POOL / APY / STAKERS`. APY collapses three streams (Leaderboard 55% + Staker 27% + Legend 3%) into one DeFi number.

**The fix:** `APY` stays on Map (Map is discovery — summary-level is correct, single number is right). The detail unpacking happens one tap deeper, on ClimbDetail Economy. Map is fine as-is. **No change needed to `Map_v5`.** Just flag in the crosswalk so future agents don't "fix" it unnecessarily.

### 3.5 `docs/design/MOBILE_DATA_CONTRACTS.md` (951 lines, 2026-03-28)

Uses pre-TRUTHS vocabulary heavily: `vault` as primary, `minter`, `leaderboard` 56× without the chain/UX split. The API routes themselves don't change until V4-B, but the *framing* of this doc will mislead any future mobile-feature implementer who reads it.

**Proposed fix (NOT urgent):** add a header pointing to this crosswalk doc + TRUTHS. Don't rewrite 951 lines. When V4-B hard rename lands, regenerate from the new backend route handlers (the doc was auto-generated from route handlers in the first place). Until then, crosswalk is the bridge.

---

## 4. Chain-vs-UX term dictionary (quick reference)

For developer grep. When writing code or copy, use the column that matches your context.

| Context | Use |
|---|---|
| `lib.rs` account struct, field, instruction, event name | Chain-canonical |
| `indexer/src/writers/*` handler names | Chain-canonical |
| API route path | UX-surface (V3 routes preserved through V4-A, renamed in V4-B alongside chain) |
| API response JSON field names | Chain-canonical (`founder`, not `minter`) |
| Mobile/portal copy, tab labels, button text | UX-surface |
| Mobile/portal TypeScript type names | Chain-canonical (`ClimbSummary`, not `VaultSummary`) — rename alongside V4-B |
| Docs in `docs/design/*`, `docs/rfcs/*`, `CLAUDE.md`, `FRESHEST_SPEC.md` | Chain-canonical + note when UX diverges |
| TRUTHS quotes | Verbatim from TRUTHS (don't paraphrase) |

Specific mappings riders will never see (developer-only):

| V3 / current name | V4-B canonical |
|---|---|
| `minter` | `founder` |
| `VaultLeaderboard` (struct) | Record Board (field `record_board` on `Climb`) |
| `distribute_epoch_rewards` | `finalize_settlement_week` |
| `record_vault_completion` | `record_climb_completion` |
| `VaultCompleted` (event) | `ClimbCompleted` |
| `UserState` (account) | `RiderSoul` |
| `last_distribution_epoch` | `last_finalized_epoch` |
| `VaultSummary` (TS) | `ClimbSummary` (with nested `vault?: VaultEconomics`) |
| `getVaults()` (TS API client) | `getClimbs()` |

---

## 5. Mobile scaffolding ↔ `wdvr` epic compatibility

### V4-A (beads `wdvr.5` + `wdvr.6`) — mobile unaffected

At original drafting, V4-A still exposed `record_vault_completion` as the live completion path. That is superseded: the live path is receipt-backed `record_climb_completion`, while the retained legacy ABI entry rejects atomically. The remaining V4-A account names and `distribute_epoch_rewards(settlement_week, ...)` wire shape continue until the coordinated V4-B rename. The mobile app reads backend/indexer DTOs rather than submitting either completion instruction, so LRWD does not change the mobile contract.

**Action:** none. Mobile dev can proceed in parallel with V4-A.

### V4-B (beads `wdvr.7` + `wdvr.8`) — coordinated rename

V4-B lands the ontology lift: Climb/Vault split, RiderSoul, RideAttestation, hard IDL rename. If backend routes rename in lockstep (likely, per "no TGE defensive coding"), mobile needs a coordinated find-and-replace:

- `mobile/src/lib/api.ts`: `VaultSummary` → `ClimbSummary`, `komHolder/komTimeS` move to climb level, add nested `vault?: VaultEconomics`, `getVaults()` → `getClimbs()`.
- `mobile/src/screens/VaultsScreen.tsx`: rename file to `ClimbsScreen.tsx`, style selectors `vaultCard/vaultName/vaultStats` → `climbCard/climbName/climbStats`. **Note:** this screen is already queued for replacement by a Map screen in the next mobile sprint (Tim's whiteboard is `Home/Map/Record/You`). The rename may be moot if Map lands first.
- `mobile/src/navigation/TabNavigator.tsx`: if tab label currently says `Vaults`, consider whether it becomes `Map` (sketch) or `Climbs` (current scaffolding continued). Sketch wins per `figma_mobile_design_file_2026-04-13.md`.
- Any `hasLeaderboards` field on `RideStatus` — stays as-is (UX-surface term, cultural fit rule §1).
- Any `minter` references — rename to `founder`.

**Action:** when `wdvr.8` (cleanup workstream) starts, include mobile in the rename sweep. Track as a sub-issue under `wdvr.8` or spawn a dedicated `wdvr.8.mobile` child. No need to act before V4-B lands.

### What mobile owes `wdvr`

Nothing on the critical path. The mobile app doesn't block protocol work.

### What `wdvr` owes mobile

- **Preserve `GET /vaults` and `GET /vaults/{sig}` read shape through V4-A.** This is a P11 truth-boundary commitment: the indexer is a read projection, the backend serves a stable JSON contract, V4-A's chain changes don't propagate to the JSON surface. WS-2a (IDL-driven decoders) already delivers this if the existing field names are kept.
- **Coordinate V4-B's backend route rename with mobile's rename pass.** Same commit sequence, not staggered. A 48-hour window where mobile points at renamed routes with stale code is a recipe for broken post-ride flows.

---

## 6. Read-layer architecture — mobile mapped to TRUTHS §5

This is the structural answer to Tim's question *"seems like our mobile app is just querying sql? that doesn't follow protocol truths."*

TRUTHS §5 defines three representation layers. A TRUTHS-aligned mobile app reads from all three, not just the third. Today's mobile reads only projected truth (SQL via backend REST), and that is the drift. The fix is not "move everything to RPC" — projections exist for a reason. The fix is **classifying each read surface by layer and wiring the right path for each**. "Engineer through the complexity" per Tim 2026-04-15.

### 6.1 The three layers, applied to mobile

| Layer | TRUTHS §5 definition | Mobile read path | Authority |
|---|---|---|---|
| **On-chain truth** | Binding economic state: Climb, Vault, Record Board, KOM, Local Legend, RideAttestation, staker positions, carry balances, SPL token balances | Solana RPC via Privy-embedded wallet | **Authoritative** |
| **Attested truth** | Reproducible off-chain: canonical ride trace, `parser_version`, `ride_hash`, TSS derivation inputs, geographic matching | Local canonicalization + compare against on-chain RideAttestation | **Verifiable** (user can reproduce) |
| **Projected truth** | Read-only dashboards, discovery, rankings, historical stats, heatmaps | Backend REST → SQL (`indexed_*` tables) | **Cached, non-authoritative** |

The key rule: **binding numbers the rider cares about (their CAL balance, their Leaderboard seat, their unclaimed rewards) are authoritative from on-chain truth.** Projections can *accelerate* the read (SQL is faster than RPC for lists), but they never *authorize* it. The rider always has a path to chain.

### 6.2 Surface-by-surface classification

Every mobile surface is classified into one or more layers. Read from primary layer; fall back to projection with a stale-data affordance if RPC times out.

| Surface | Primary layer | Fallback | Notes |
|---|---|---|---|
| **My CAL balance** (HomeScreen header, Economy Wallet card) | On-chain (SPL token account) | Projection with "last updated" timestamp | Authoritative. Cache 30s. |
| **My DUNG balance** | On-chain (SPL token account) | Projection | Same. |
| **My Leaderboard seat on Climb X** | On-chain (`Climb.record_board[]` scan for rider pubkey) | Projection (`indexed_record_royalty_payouts`) | Seat membership is authoritative economic state per TRUTHS §6.3. |
| **My pending Leaderboard earnings** | On-chain-derived estimate from current Vault state + Record Board seat | Projection | Treat as an estimate until the Settlement Week finalizes; the settled payout history becomes authoritative after finalization. |
| **My stake position** (Economy Stake card) | On-chain (`VaultStake` PDA for (vault, staker)) | Projection | `VaultStake.cal_staked` is the V4-A authoritative field; mobile can expose a normalized `effectiveCal` view-model without implying a chain rename yet. |
| **My unclaimed staker rewards** (Economy Pending card) | On-chain (`VaultStake.rewards_earned` in V4-A) | Projection (`indexed_staker_allocations` history once wdvr.6 lands) | Per P8 this is literally a single u64 on-chain — trivial RPC read. |
| **My Local Legend status** | On-chain (`LocalLegend` PDA holder field) | Projection | Binary read, cheap. |
| **RideAttestation for my ride** | On-chain + attestation reproduction | — | See §6.4 verifiability. V4-B dependent. |
| **My ride's CAL credit receipt** | On-chain (`CalMintReceipt` PDA) | — | Structural replay proof. V4-B dependent. |
| **Climb geo data** (vert, distance, gradient) | Projection (`indexed_climbs.vert_m` etc.) | — | Immutable once founded; SQL is correct primary. |
| **Climb name, founder, KOM holder/time** | Projection | Verify chip → RPC on demand | Changes rarely; SQL cache is fine. |
| **Climb list for map discovery** | Projection | — | §5.3 explicit use case. Pure discovery UI. |
| **Leaderboard list display** (names, times, ranks 1–10) | Projection | Per-row verify chip | Scrolling a 10-row list via 10 RPC calls is wrong. Projection is primary; verify-on-tap for any specific row. |
| **Archetype match hint on Climb card** | Projection (derived from aggregate) | — | §7.3 archetype is soulbound but the *match calculation* is a UX aggregate over projected stats. |
| **Historical ride list** | Projection | — | Browsing history, §5.3. |
| **Lifetime stats** (total rides, total TSS, lifetime CAL) | Projection | Verify chip on the profile screen for summary numbers | V4-B: RiderSoul account on-chain holds these as monotonic u64s. Pre-V4-B: projection only. |
| **Stakers list for a vault** | Projection | — | Social/discovery. Non-authoritative. |
| **Carry balances for a vault** (5 bucket fields) | On-chain (`Vault.carry_*`) | Projection | V4-A lands these on-chain. `carry_stakers` is already-unlocked allocation dust, not the current week's locked amount; the settlement event reports the amount reallocated to Record Royalty. `StakerRemainderPolicyApplied` marks the old-versus-new historical boundary and any one-time legacy carry cutover. |
| **Post-ride reveal numbers** (CAL earned, climbs crossed) | Projection initially, replaced by on-chain confirmation when indexed | Polling | Ride is "provisional" until RideAttestation appears on-chain; UI shows a state badge (see §6.4). |

**Pattern that emerges:** ~70% of the surfaces are legitimate §5.3 projections (discovery, browsing, lists, historical). ~20% are binding economic reads that should hit chain (balances, your seat, your stake, your rewards). ~10% are attestation reads that require the RideAttestation PDA + local canonicalization (post-ride reveal verify, ride history verify). The current mobile uses projection for 100%. The gap is the middle 30%.

### 6.3 The three read paths — what they cost and where they live

**Path 1: RPC chain reads (new surface).**

New module: `mobile/src/lib/chain.ts`. Uses Privy-embedded wallet's Solana connection. Functions:

```ts
// Balances
getCalBalance(wallet: PublicKey): Promise<bigint>
getDungBalance(wallet: PublicKey): Promise<bigint>

// My economic position on a climb
getVaultStake(vault: PublicKey, staker: PublicKey): Promise<VaultStakeAccount | null>
getMyRecordBoardSeat(climb: PublicKey, rider: PublicKey): Promise<{ rank: number; timeS: number } | null>
getLocalLegend(vault: PublicKey): Promise<LocalLegendAccount | null>

// Carry + pending
getVaultCarry(vault: PublicKey): Promise<{ recordRoyalty: bigint; stakers: bigint; localLegend: bigint; pol: bigint; treasury: bigint }>

// Attestations (V4-B)
getRideAttestation(rider: PublicKey, rideHash: Uint8Array): Promise<RideAttestationAccount | null>
getCalMintReceipt(rideAttestation: PublicKey, rider: PublicKey): Promise<CalMintReceiptAccount | null>
```

**Real costs:**
- Depends on `@solana/web3.js` + Anchor IDL deserialization. ~200KB added to bundle, acceptable for a Solana-native app.
- Needs the V4 IDL from `protocol/anchor/idl/boulder_rollers.json` bundled into the app. Add to Metro/Expo asset list.
- Devnet RPC is already Helius; mobile should use the same endpoint. Reuse `SOLANA_RPC_URL` pattern from backend.
- Each read is ~150ms on Helius devnet. Cache aggressively with React Query (5s stale-while-revalidate for balances, 30s for seat/stake, 60s for carry).
- Rate limits: our Tier 1 Helius is ~50 RPS — plenty for a single-user mobile app.
- PDA derivation needs to match `lib.rs` seeds exactly. Hard-to-test landmine. Mitigation: generate PDA derivation helpers from the IDL at build time, don't hand-roll seeds.
- **Anchor client TS in React Native is known-flaky** — the `@coral-xyz/anchor` package has Node.js-isms (Buffer, crypto) that don't ship with Metro. Mitigation: use `@solana/web3.js` raw `getAccountInfo` + manual Borsh deserialization via the IDL. More code, fewer surprises.

**Path 2: Attested truth — local canonicalization + RideAttestation compare.**

The verifiability path. This is the harder one.

The `workout-parse` Rust crate already has `canonicalize(activity, parser_version)` shipped (committed in `df58b14a` per the handoff). It produces canonical bytes + `ride_hash`. The mobile app needs to be able to run this locally against a ride file the user has on their phone, then compare the computed `ride_hash` against on-chain `RideAttestation.ride_hash`.

Three ways to ship canonicalization to mobile:

- **(a) Native module binding.** Compile `workout-parse` for iOS (xcframework) and Android (JNI/AAR). Add as a native module to Expo via a config plugin. Exposes `canonicalizeRide(bytes: Uint8Array, version: number): Promise<{ canonical: Uint8Array; hash: Uint8Array }>`. Pros: maximum fidelity, reuses chain-side Rust code directly. Cons: rebuilds the mobile binary, breaks Expo Go dev workflow (already broken per memory — Sentry stubbed, Privy stripped for dev), requires prebuild pipeline.
- **(b) WASM compile.** Target `wasm32-unknown-unknown`, load in React Native via `react-native-webview` or a WASM runtime. Pros: portable, no native module per platform. Cons: React Native WASM is not first-class, performance penalty on larger rides, canonicalization on a 1000-point trace is non-trivial work.
- **(c) Backend computes canonical bytes, mobile hashes.** Backend exposes `GET /rides/{id}/canonical-bytes` that returns the exact serialized bytes it canonicalized (not the hash — the bytes). Mobile hashes them locally (SHA-256 is trivial in JS) and compares against on-chain. The bytes are deterministic so this works *if* the backend is honest about which bytes it canonicalized. To catch a lying backend, mobile also needs to independently verify the bytes represent the ride file the user uploaded — which requires running the canonicalization itself, which puts us back at (a) or (b).

**Tim's rule says engineer through the complexity.** The honest choice is **(a) native module binding** as the target, with **(c) backend canonical bytes endpoint** as a bridge in the interim. (c) lets the mobile app show a verify chip today ("backend says this ride hashes to `0xabcd...`, chain says the same") without solving the full trust chain. (a) closes the trust chain when we do the mobile prebuild work anyway (already needed for Privy + Sentry re-integration).

Order: (c) first as the bridge, (a) later as the real answer. Don't build (b) — WASM in RN is a sideshow.

**Path 3: Projected truth (existing surface).**

Current `mobile/src/lib/api.ts`. No changes needed. Stays as-is for all §5.3 surfaces listed in §6.2. Keeps the discovery/browsing/history UX fast and cheap.

### 6.4 Verifiability affordances — what the rider sees

This is where the three layers become *visible* in the UI. TRUTHS §10: *"The protocol's public objects should be sufficient to explain outcomes without forcing raw ride privacy onto the chain."* The affordance is a small, consistent **Verify chip** attached to any economic-critical number.

**The VerifyChip component.** New file `mobile/src/components/VerifyChip.tsx`. States:

| State | Visual | Meaning |
|---|---|---|
| `unchecked` | olive dot, `verify` | SQL value shown, RPC not yet called. Tap to trigger. |
| `checking` | olive spinner | RPC in flight. |
| `verified` | cream check, `on chain` | SQL matches chain. Fresh within 30s. |
| `stale` | olive check, `on chain · 2m ago` | Verified earlier, cache past TTL, not re-fetched. |
| `diverged` | gold warning, `mismatch` | SQL and chain disagree. This is a bug somewhere — crash-report + surface. |
| `error` | olive warning, `offline` | RPC unreachable. Show projected value, tell the rider chain is unavailable. |

**Where the chip appears:**
- Economy tab: next to `YOUR STAKE`, next to `PENDING +23.4 CAL`, next to the new Leaderboard earnings card (§3.1).
- Home/header: next to `CAL balance`.
- Post-ride reveal: next to `CAL earned` after the ride enriches.
- Ride history detail: next to each past ride's CAL earned number.
- BoulderRolled hero (level delta, tribute total): chip appears after the gold cascade animation completes, so verification doesn't interrupt the celebration.

**Default behavior:**
- First view: `unchecked`. Don't auto-RPC every number — that's ~8 RPC calls per Economy tab open. Wasteful.
- Tap to verify one number: `checking` → `verified` / `diverged` / `error`.
- Profile screen has a "Verify all" button that runs the full set in parallel. For the obsessive rider.
- Economy tab gets auto-verify on mount for the **one** card that represents the rider's immediate action intent (the Stake card, because they may tap Withdraw). Others stay `unchecked` until tapped.

**Diverged state is load-bearing.** If the SQL projection diverges from on-chain state, something is broken — indexer lag, stale cache, indexer writer bug, or worse. Mobile surfaces this instead of hiding it. The rider sees the chain number, a "mismatch" chip, and a "report this" button that sends diagnostic info. This is the TRUTHS §10 promise in action.

### 6.5 New mobile modules — what gets added

Concrete list of files/modules to build, scoped to Phase A (post-V4-A, pre-V4-B):

- `mobile/src/lib/chain.ts` — RPC client module per §6.3 Path 1. Depends on `@solana/web3.js` + IDL bundle. No `@coral-xyz/anchor` (see §6.3 note on React Native flakiness).
- `mobile/src/lib/pda.ts` — PDA derivation helpers. Generated from IDL at build time, not hand-rolled. Matches `lib.rs` seeds exactly.
- `mobile/src/lib/borsh.ts` — Borsh deserialization for account types we need (VaultStake, LocalLegend, Climb, Vault). Generated from IDL. Small, targeted — don't try to deserialize everything.
- `mobile/src/lib/verify.ts` — Orchestrator. Compares SQL claims (from `api.ts`) against chain reality (from `chain.ts`). Returns `VerifyResult { state, chainValue, projectedValue, timestamp }`.
- `mobile/src/components/VerifyChip.tsx` — The UI component per §6.4.
- `mobile/src/hooks/useVerifiedValue.ts` — React hook that wraps `verify.ts` for component use. Handles caching, debouncing, state transitions.

Phase B (after V4-B lands the RideAttestation ontology):

- `mobile/src/lib/canonicalize.ts` — Canonicalization interface. Initially wraps backend `/rides/{id}/canonical-bytes` endpoint (Path 2c). Later swapped for native module (Path 2a) without changing the interface.
- `mobile/src/native/canonicalize/` — iOS + Android native module wrapping `workout-parse::canonicalize`. xcframework + AAR. Triggered by Expo prebuild config plugin. Unblocks Phase B's real verification path.
- `mobile/src/hooks/useRideVerification.ts` — Hook for post-ride reveal + history screen. Runs canonicalization, compares against on-chain RideAttestation.

**IDL bundling.** The V4-A IDL lives at `protocol/anchor/idl/boulder_rollers.json`. Mobile needs a build-time copy. Add to Metro config as a static asset. Regenerate on every `anchor build`. Version-pin in mobile so a new chain deploy doesn't silently break mobile (mobile refuses to start if IDL version doesn't match compiled-in expectation).

**What this is NOT:** `@coral-xyz/anchor` client. That package is Node-flavored, Metro chokes on it, and we don't need its instruction builders (mobile never submits transactions directly — Privy handles that). We only need read + decode, which `@solana/web3.js` + a hand-targeted Borsh decoder covers.

### 6.6 Phasing (when each piece lands)

Gated by what's on-chain. Don't build against an ontology that's about to change.

**Phase A — after V4-A ships (wdvr.5 + wdvr.6 green):**
1. `chain.ts` + `pda.ts` + `borsh.ts` for V4-A account shapes (Vault, VaultStake, LocalLegend, ProgramConfig, SPL balances).
2. Add a tiny compatibility adapter layer so app-facing names can stay stable while chain names differ:
   - `rewards_earned` → `unclaimedRewards`
   - `eligible_from_epoch` → `eligibleFromEpoch`
   - `cal_staked` → `effectiveCal` (view-model only; do not imply a chain rename yet)
3. `verify.ts` + `VerifyChip.tsx` + `useVerifiedValue.ts`.
4. Wire VerifyChip into: CAL/DUNG balance (HomeScreen), Economy Stake/Pending/Wallet/Stakers numbers, new Leaderboard card (§3.1 conditional).
5. No RideAttestation yet (doesn't exist on-chain until V4-B).
6. Chain reads: ~5 account types, ~6 surface numbers. Bounded scope.

**Phase B — after V4-B ships (wdvr.7 + wdvr.8 green):**
6. Rename `VaultSummary` → `ClimbSummary` in mobile (coordinated with V4-B backend rename pass).
7. Add `canonicalize.ts` with Path 2c (backend canonical-bytes endpoint). Add `/rides/{id}/canonical-bytes` to backend.
8. Wire ride verification chip into post-ride reveal + ride history detail.
9. Plan native canonicalization module (Path 2a). Build decision: is mobile prebuild happening for Privy/Sentry re-integration anyway? If yes, include canonicalization native module in the same prebuild. If not, defer.

**Phase C — polish (when the major ontology is stable):**
10. Native canonicalization module (Path 2a), replacing the Path 2c backend bridge.
11. "Verify all" profile button.
12. Diverged-state crash reporting hooked into Sentry (assumes Sentry is un-stubbed by then).
13. Lifetime metric verification against RiderSoul (only meaningful after RiderSoul lands in V4-B).

**What does NOT land in any phase:**
- Mobile never submits instructions directly. Transaction submission stays backend-attested per P13. Mobile reads chain, mobile does not write chain. Privy wallet can sign, but signing the wrong thing is a footgun we're not opening.
- Mobile never decodes arbitrary chain accounts. Only the ~8 account types we explicitly need. Growth is deliberate, not open-ended.
- Mobile never becomes a second indexer. If a surface needs aggregate data across many accounts, it uses the projection. The RPC path is for single-account authoritative reads of the rider's own position.

### 6.7 What this architecture buys us

Plain-language summary of why this is worth the complexity:

1. **TRUTHS §10 compliance.** *"Sufficient to explain outcomes without forcing raw ride privacy onto the chain."* The rider holds their own ride file, computes the canonical hash themselves, and verifies the chain attested to exactly that. No backend trust required for the core economic claim.
2. **Diverged-state detection.** When the indexer has a bug, when the backend serves stale data, when a race condition skips a writer call — the mobile app *notices*, because it holds both values and compares them. Today, a silent failure in the pipeline goes unnoticed. Tomorrow it's a gold-chipped warning on the screen.
3. **Onchain narrative.** Tim's core pitch is *"economic truth for cycling geography."* A mobile app that only queries SQL is a Strava clone with token branding. A mobile app that reads chain for the binding numbers and offers verification affordances *is* a blockchain-native cycling protocol. The difference is visible on the screen.
4. **V4-B ontology lift gets a target.** When Climb/Vault/RiderSoul split and RideAttestation becomes first-class, there's already a mobile client that knows how to consume them. V4-B isn't building toward an abstraction; it's unblocking a concrete mobile feature.
5. **Doesn't throw out what works.** Projections stay. Discovery, browsing, map, history — all SQL-backed, fast, unchanged. The RPC layer is additive, scoped, and only appears where the rider's economic truth demands it.

### 6.8 Engineering the hard parts

Tim's rule: *"do not overcomplicate to cut complexity. work and engineer thru complexity."* And: *"we should code defensively we are pushing for completion."* Each item below is a real problem and a real solution, not a cost to accept. The defensive posture is: **every read path has a timeout, every cache has an explicit TTL, every state machine has a terminal state, every decoder has a fixture test, every shipped feature has a kill switch.** No infinite spinners, no "unknown what's happening," no hope-based code.

#### 6.8.1 Borsh deserialization without hand-rolling

**The problem:** hand-writing Borsh decoders from an IDL is where drift bugs live. The first one works, the fourth one has an off-by-one on a `Vec<u8>` length prefix.

**The solution: IDL-driven codegen, not handwriting.**

- Add a build script `mobile/scripts/gen-chain-types.ts` that consumes `protocol/anchor/idl/boulder_rollers.json` and emits `mobile/src/lib/chain/generated/{accounts,pdas,instructions}.ts`.
- The script uses Anchor's IDL schema (public, stable) to walk account definitions and emit typed TS decoders + PDA derivation functions + `getAccountInfo`-to-typed-struct adapters. ~300 lines of script, ~1500 lines of generated code.
- `mobile/src/lib/chain.ts` imports from `generated/` and wraps it with app-specific caching, error handling, telemetry. The RN-facing surface is hand-written and small; the bytes-to-struct machinery is codegen.
- `protocol/anchor/` CI step emits the new IDL on every `anchor build`; a second CI step runs `gen-chain-types.ts` and commits any changes in the same PR. Mobile codegen is never stale.
- Fixture-based decoder tests: committed `.bin` blobs dumped from real devnet accounts (`Vault`, `VaultStake`, `LocalLegend`, `ProgramConfig`, `Climb`) + expected decoded JSON. Test harness: `decodeVault(fixtureBytes) === fixtureJson`. CI fails on any drift between codegen, fixture, and IDL.
- Dev helper: `mobile/src/lib/chain/debug.ts` exports `dumpAccount(pubkey)` that writes the raw bytes + decoded struct to console for regression seeding. Zero-cost addition, buys forever-future-proofing.

**Precedent:** this is the Anchor ecosystem's normal pattern. `@coral-xyz/anchor-cli` ships similar codegen for Node; we're replicating it targeted and bundler-friendly for React Native. We are not inventing a new technique.

#### 6.8.2 PDA seed compatibility — codegen + version gate

**The problem:** if `lib.rs` PDA seeds change between V4-A and V4-B and mobile doesn't know, reads return `null` silently and the verify chip goes `error` with no explanation.

**The solution: codegen the PDA derivation + runtime version gate.**

- Anchor 0.30+ IDLs include `pda` definitions on each account — seed byte strings, referenced args, bump rules. The codegen script in §6.8.1 consumes these and emits `derivePda(accountType, args) → PublicKey` functions that match `lib.rs` byte-for-byte because they're derived from the same source of truth.
- Add `program_version: u8` to `ProgramConfig` in V4-A (one-line chain change, folds into `wdvr.5`). Initialize to `0x40` for V4-A, bump to `0x4B` for V4-B.
- Mobile startup: `getAccountInfo(ProgramConfig)` → check `program_version`. Compare against `EXPECTED_PROGRAM_VERSION` constant compiled into the app. On mismatch, mobile sets `verifyEnabled = false` and shows a non-dismissible banner: *"Please update the app to verify your rides on-chain."* Projected reads keep working; chain reads are gated.
- Cross-surface PDA test: CI script generates ~20 PDAs in the mobile codebase and the same 20 in a Python script that imports from `backend/app/solana_direct.py`. Asserts equality. Catches drift at the language boundary *before* it ships.
- Defensive: never deploy a new chain program without also bumping `program_version`. Add to the anchor deploy runbook + a pre-deploy git hook that fails if `lib.rs` changed without `program_version` also changing.

#### 6.8.3 Native canonicalization — UniFFI, not bespoke bindings

**The problem:** hand-writing iOS Swift bindings + Android JNI/Kotlin bindings for the `workout-parse` Rust crate is a multi-week project that produces fragile glue code.

**The solution: UniFFI.**

- [UniFFI](https://github.com/mozilla/uniffi-rs) is Mozilla's production-grade tool for generating Swift, Kotlin, and Python bindings from a Rust crate automatically. Used in Firefox, Firefox Sync, Focus, Signal. Not experimental.
- Workflow:
  1. Annotate the target functions in `workout-parse/src/canonicalize.rs` with `#[uniffi::export]`.
  2. Write a `canonicalize.udl` interface file (~20 lines for our surface area: `canonicalizeRide(bytes: Vec<u8>, version: u32) -> CanonicalResult { canonical_bytes: Vec<u8>, ride_hash: [u8; 32] }`).
  3. `cargo uniffi-bindgen generate` produces `Canonicalize.swift` + `Canonicalize.kt`.
  4. Cargo builds an xcframework for iOS (ARM64 + sim) and an AAR for Android (armeabi-v7a, arm64-v8a, x86_64).
  5. Expo config plugin (~80 lines) drops the framework/AAR into the prebuild template and registers the native module with React Native's bridge.
- Result: TS code calls `import { canonicalizeRide } from 'boulder-canonicalize'` and gets the exact same bytes + hash the backend produces. Zero bridging code written by hand.
- Bundle: iOS framework ~600KB, Android AAR ~800KB. Acceptable.
- **Fold into the already-queued prebuild work.** Per memory, mobile already needs Expo prebuild for Privy native + Sentry re-integration. Adding canonicalization to that same prebuild is +1 module, +~2 days of work, not a greenfield pipeline. The mobile team ships all three native dependencies in one prebuild event.
- Alternative if UniFFI hits a blocker: `expo-module-sdk` (Expo's own native-module scaffold, stable since SDK 50). Same shape, more framework-coupled. UniFFI is the first choice because it reuses Rust code without language-bridge rewrites.

#### 6.8.4 RPC latency — optimistic projection + persistent chain cache

**The problem:** a rider on 3G at a col du mountain pass opens the Economy tab. RPC timeout at 5s. Do they wait? Do they see blank numbers?

**The solution: optimistic projection + persistent chain cache + background re-verify. Rider never waits, never sees blanks.**

- **Read path:** projected value shows immediately (from SQL API, already cached in React Query). Chain RPC kicks off in parallel. Two outcomes:
  - RPC succeeds within timeout (default 3s): chip transitions `unchecked` → `verified`, value updated if chain differs from projection (with divergence logged).
  - RPC exceeds timeout: chip shows last-known chain value with a timestamp. `on chain · 14h ago`. If no prior chain read exists, chip shows `offline`.
- **Persistent chain cache:** every successful chain read is written to a SQLite table `chain_cache { account_pubkey, account_type, raw_bytes, decoded_json, fetched_at, program_version }`. Reads hit the cache first on cold start, get a stale value immediately, then re-verify in background.
- **Background sync service:** new file `mobile/src/services/chainSync.ts`. Runs as a background task when the app wakes from background or network returns. Iterates all cached accounts relevant to the rider (their VaultStake positions, their Climb.record_board memberships, their balances) and re-verifies in parallel batches of 5. Updates happen silently; chip states transition from `stale` → `verified` without user action.
- **Defensive:** every RPC call in `chain.ts` has a hard 5s timeout. No call can hang. Every cache entry has `fetched_at`, UI explicitly distinguishes "fresh (< 30s)" / "recent (< 5min)" / "stale (< 24h)" / "ancient (> 24h)" via the chip visual. "Ancient" is still shown but with an explicit timestamp — the rider knows exactly how old the data is.
- **Net behavior:** offline rider opens Economy tab, sees their cached stake position + "on chain · 14h ago" chip. They tap Withdraw — the withdraw flow itself requires fresh chain state (enforced at transaction submission, which hits backend anyway), so the 14h-old view can't cause a bad write. Read UX is smooth, write safety is unaffected.

#### 6.8.5 Verification state — state machine, not `useState`

**The problem:** 6 chip states × 8 simultaneous chips × React re-renders = the kind of bug where a chip gets stuck in `checking` forever because a cleanup fired out of order.

**The solution: explicit state machine, single derived-state hook.**

- **No `useState` for chip state.** All state lives in a Zustand slice `verifyStore` keyed by `cacheKey` (e.g. `vaultStake:${vault}:${staker}`). Each entry holds `{ projectedValue, chainValue, fetchedAt, lastError, inflightRequestId }`. That's 5 fields.
- **The 6 chip states are *derived*, not stored.** A single pure function `deriveState(entry, now) → ChipState` computes the current state from the 5 fields + current time. Tested as a pure function with tableized inputs. Zero state sync bugs because there's no duplicated state to sync.
- **`useVerifiedValue(cacheKey, onChainReader, fallback)`** is a hook that subscribes to the store slice for that key, derives current state, returns `{ value, state, verify: () => void }`. Components call `const { value, state } = useVerifiedValue(...)` and render accordingly.
- **Inflight request coalescing:** if two chips want the same account simultaneously (e.g. opening Economy triggers Stake + Pending + Wallet chips all for the same `VaultStake` PDA), only one RPC fires. The store tracks `inflightRequestId` and deduplicates.
- **Kill switch:** remote config flag `verify_enabled: boolean`. When false, every `useVerifiedValue` returns `{ value: projected, state: 'disabled' }` with no RPC. We can disable all verification instantly via a remote config push if a systemic bug appears post-ship, without waiting for an App Store update.
- **Defensive terminal states:** every chip state has a definite end. `checking` transitions to `verified`/`diverged`/`error` within 5s or it transitions to `error` via the timeout path. A chip can never be stuck in `checking` forever. Tested with a `fakeTimers` harness.

#### 6.8.6 Post-ride race window — explicit phase UI, not hidden spinners

**The problem:** ride uploaded at t=0. Backend processes at t=3s. Indexer catches up at t=8s. Chain settles at t=15s. SQL sees `CAL +47` at t=5s. RideAttestation exists on-chain at t=15s. Mobile opens post-ride reveal at t=4s. What does the verify chip say?

**The solution: three explicit phases, each with a defined transition event and a visible chip state. Tim's "don't simplify to cut complexity" — we model all three phases, don't hide them.**

- **Phase 1: `uploaded`** — ride reached backend, processing started. Chip state: `processing`, spinner. Transition trigger: backend `ride_processed` event via polling `GET /rides/{id}/status?status=processed`. Timeout: 30s, then `error`.
- **Phase 2: `provisional`** — backend computed CAL/climbs/TSS, SQL projections are live, but chain has not yet confirmed the RideAttestation. Chip state: `provisional` (new state, olive tint, clock icon, label `provisional`). This is a first-class state, not hidden under `unchecked`. Transition trigger: indexer writes `indexed_ride_attestations` row. Timeout: 120s, then `error` with retry.
- **Phase 3: `attested`** — RideAttestation PDA exists on-chain, indexed. Mobile can now derive the PDA and do the direct RPC read. Chip upgrades `provisional` → `verified`. Rider sees their ride is fully on-chain.
- **Polling implementation:** `mobile/src/hooks/useRideLifecycle.ts`. Polls `GET /rides/{id}/status` every 3s until status transitions to `attested` or timeout fires. Linear backoff to 10s after 30s. Exponential after 60s. Explicit end state, never infinite.
- **Visible in UI:** post-ride reveal shows the numbers the whole time, with the chip telling the rider which phase they're in. *"+47 CAL · provisional"* for 12 seconds then *"+47 CAL · on chain"* is a better UX than a 15-second opaque spinner.
- **Defensive:** if the transition from `provisional` → `attested` never happens (indexer broken, chain fork, whatever), the chip eventually times out to `error` with a "report this" action. Rider is never left hanging.

#### 6.8.7 IDL drift — strict version gate + runtime feature detection

**The problem:** mobile ships with V4-A IDL. A hotfix redeploys the chain with V4-A.1. Mobile's decoders assume the old layout. Silent decode failures.

**The solution: version-gate on startup + runtime feature detection for new fields.**

- **Strict gate:** see §6.8.2. `EXPECTED_PROGRAM_VERSION` compiled into the app. On mismatch, verify is disabled, banner shown. **Defensive default:** if we can't read `ProgramConfig.program_version` at startup for any reason (RPC fail, decode fail, whatever), verify is disabled by default — fail closed. Rider sees projected values with `unchecked` chips; the app still works, just without verification.
- **Semver convention:** chain program uses `MAJOR.MINOR.PATCH` where MAJOR changes break mobile decoders, MINOR adds new fields non-breakingly, PATCH is internal. Mobile checks `major == expected_major && minor >= expected_minor`. PATCH is ignored (cosmetic).
- **Runtime feature detection:** for account fields that might be added in a minor upgrade (e.g. "we added a `beetle_score: u64` field to `RiderSoul` in V4-B.1"), decoders use the account's on-disk size to conditionally decode. If `account.data.len() == V4B_RIDER_SOUL_SIZE`, decode the extra field; if it matches the older size, leave it `null`. This makes MINOR upgrades non-breaking.
- **Release gating:** chain upgrades and mobile App Store pushes are coordinated via the same deploy runbook. Chain deploy doc includes "check mobile release cadence before bumping MAJOR." Defensive: if we must bump MAJOR unexpectedly, the remote kill switch (§6.8.5) disables verify until the app update propagates.

#### 6.8.8 Validation before ship — dev flag + telemetry + kill switch

**The problem:** a broken verify chip is worse than no chip. A rider seeing `mismatch` where there's no real mismatch loses trust.

**The solution: three-layer rollout with progressive gates.**

- **Layer 1: dev-only flag.** `VERIFY_CHIP_ENABLED` defaults to false in production, true in dev. All verify infrastructure is built, none of it is visible to real users until the flag flips.
- **Layer 2: telemetry first.** Every chip state transition fires a Sentry/analytics event: `chip_verified`, `chip_diverged`, `chip_error`, `chip_offline`. Labels include account type, program version, network latency bucket. We run in production with the chip *invisible* but the store computing states and firing events for a week. Dashboards show: how often would a chip be shown, what states would it be in, how many divergences across the user base. If divergences are 0.01%, the chain/indexer pipeline is healthy and we flip the flag. If they're 5%, we have an indexer bug to fix first.
- **Layer 3: progressive flag flip.** Remote config flag gradually enabled: 1% → 10% → 100% of users. Same pattern as a staged rollout. Any spike in `chip_diverged` or `chip_error` rolls back automatically via a threshold alarm.
- **Defensive: kill switch always on.** The remote flag can revert 100% → 0% in seconds. We never need an emergency App Store update to hide a bad chip. The chip is additive; disabling it returns the app to today's UI.

#### 6.8.9 Decoder / writer drift between mobile, backend, indexer

**The problem I hadn't explicitly named yet:** three codebases now decode the same chain accounts — mobile `chain.ts`, backend `solana_direct.py`, indexer `decoder.ts`. If they drift from each other, the divergence chip fires for reasons that aren't really divergence.

**The solution: single source of truth (IDL) + cross-surface test.**

- All three decoders are codegen from the same `boulder_rollers.json` IDL. Not written separately.
- Cross-surface test in CI: take a known devnet account snapshot, decode it with all three implementations, assert the decoded JSON matches across all three. Any drift fails CI.
- When the IDL changes (every anchor build), all three codegen targets rerun and commit in the same PR. A chain change that breaks one surface breaks all three in the same commit, caught in CI, fixed before merge.
- **This is already partially covered by WS-2a** (backend IDL-driven decoders). Expanding it to mobile + indexer is incremental consistency work, not a new paradigm.

---

### 6.9 The recording surface — where attested truth begins

Reading chain is half the story. The other half is **the ride recording function, where attested truth is produced in the first place.** A mobile app that verifies chain reads but records rides sloppily is still untruthful — the chain is only as honest as the attestation input.

The recording function is currently shipped (Phase 1 mobile, committed): `mobile/src/services/gpsRecording.ts`, `mobile/src/services/database.ts`, `mobile/src/services/gpxExporter.ts`, `mobile/src/services/uploadQueue.ts`, `mobile/src/stores/recordingStore.ts`, `mobile/src/lib/gpsValidation.ts`, plus `RecordScreen.tsx`. It does the core work: capture GPS, handle pause/resume, survive crashes, export GPX, queue for upload. What it does not yet do is make the chain-side promise that the recorded file is bit-for-bit what produced the eventual `ride_hash`.

#### 6.9.1 Recording in the three-layer model

A ride lives in distinct phases, each at a different layer:

| Phase | Layer | State |
|---|---|---|
| Recording in progress | Local-only | GPS samples flowing into SQLite, not yet a "ride" |
| Recording stopped, not uploaded | Local-only + pre-attestation | File exists, has preliminary hash, queued for upload |
| Upload in flight | Transitioning | Bytes on the wire, attestation not yet committed |
| Processing on backend | Attested (provisional) | Backend running `workout-parse::canonicalize()`, preparing RideAttestation |
| RideAttestation on chain | Attested (confirmed) + On-chain | Chain has committed to `ride_hash`, `parser_version`, economic consequences |

The recording function owns phases 1–3. It hands off to the attested layer at phase 4. **The thing that matters for TRUTHS compliance: phases 1–3 must produce a file that, when canonicalized by any honest implementation of the current parser version, yields the same bytes and same hash.** Any violation of that invariant is a fraud vector or a bug.

#### 6.9.2 What recording owes TRUTHS

Five concrete obligations, each with an engineering implementation.

**Obligation 1: Bit-for-bit reproducibility of the canonical serialization.**

The canonical serialization from `workout-parse::canonicalize()` is defined over a specific set of fields (GPS points quantized to 6 decimal places, sensor samples at 1s intervals, elevation, power/HR/cadence where present). Anything in the recorded file that isn't in that set must not affect the hash. Two recordings of the same ride on two devices must produce the same `ride_hash` if the underlying data is identical.

**Implementation:**
- `gpxExporter.ts` produces the GPX file. It must not inject device identifiers, app version, timestamps-of-export, random UUIDs, or any metadata not present in the canonical slice.
- Audit `gpxExporter.ts` for non-canonical inclusions. Known offenders to check: `<metadata>` blocks with export timestamps, `<extensions>` with device-specific fields, comment/description fields.
- Add a unit test: record two identical synthetic rides with different device IDs + different wall-clock export times → call `gpxExporter` → call `workout-parse::canonicalize()` → assert the hashes match.
- Defensive: during recording stop, run the canonicalization against the in-memory trace and store the resulting `ride_hash` in SQLite alongside the ride. This becomes the rider's own record of what they recorded, independent of backend processing.

**Obligation 2: Tamper-evident local storage.**

Between "ride stopped" and "upload succeeded," the ride file sits in the phone's storage. A malicious user, a buggy app update, or a file system corruption could modify it. If the modified file is then uploaded and attested, the chain commits to data the rider never actually produced.

**Implementation:**
- Compute the preliminary `ride_hash` at ride-stop time via native canonicalization (§6.8.3) and store it in the `rides` SQLite table as `preliminary_ride_hash BLOB(32)`.
- Upload queue sends both the file and the preliminary hash. Backend re-canonicalizes from the received bytes and compares against the preliminary hash.
- If they differ, the upload is flagged for investigation, not auto-attested. Rider sees a "ride under review" state. This is an explicit non-silent failure path.
- Local storage is in SQLite (not flat files), which gets some tamper protection via the database's transaction layer. Not cryptographic, but not nothing.
- Defensive: SQLite database file is in the app's sandboxed storage (already is, iOS default). A malicious user on a jailbroken device can still tamper, but the preliminary-hash-vs-uploaded-hash compare catches any post-stop modification. Jailbreak-level tampering is out of scope for alpha (no realistic fraud motivation pre-TGE).
- Pre-Phase-B: since native canonicalization doesn't exist yet, use the **backend canonical-bytes bridge** (§6.3 Path 2c). At ride stop, mobile uploads the file immediately to a `POST /rides/preliminary-hash` endpoint that returns the canonical hash. Mobile stores it. Not as secure as local hashing (backend is in the loop), but still provides the tamper-evident property against post-stop modification. Upgraded to truly local at Phase C.

**Obligation 3: Parser version pinning.**

A ride recorded today under parser_version=1 but canonicalized a year from now under parser_version=2 would produce a different hash — the canonicalization rules changed. The ride file must carry metadata saying which parser it was recorded under.

**Implementation:**
- Add `parser_version INTEGER NOT NULL` to the `rides` SQLite schema. Stamped at ride stop time with the current `workout-parse::CURRENT_PARSER_VERSION` constant (exported from the Rust crate via UniFFI).
- Upload queue sends `parser_version` as a header/field. Backend canonicalizes using that specific version, not the latest. Past rides remain valid against their own recording-time parser.
- Backend supports multiple parser versions for canonicalization (WS-10's versioning requirement). Mobile always uses the latest at recording time.
- Defensive: if mobile's `parser_version` doesn't match any version the backend knows about (e.g. mobile is too new), backend returns a clear error and mobile shows "please update the backend" — this is the inverse of §6.8.7's app-update banner.

**Obligation 4: GPS integrity at recording time.**

`gpsValidation.ts` already exists and filters obviously-bogus samples (teleports, impossible speeds, stale timestamps). This is the first line of defense against fraudulent attestations — a fake recording with teleported GPS produces a valid-looking ride file that the chain would attest to if the backend didn't filter.

**Implementation:**
- Audit `gpsValidation.ts` against the current checks in `workout-parse::gpsValidation` (backend side). They must agree on what is a valid sample. If mobile accepts a sample that backend rejects, the canonical trace differs, the hash differs, upload fails re-canonicalization compare (§6.9.2 Obligation 2). That's not a disaster but it's noise. Better to pre-filter identically.
- The validation rules are defensible from physics: max speed (cyclist, not car), max acceleration, max GPS jump distance, min time between samples, min HDOP. These should be shared constants between Rust and TS (codegen from a constants file, or duplicate with a test that asserts they match).
- Defensive: on validation failure, mobile drops the sample silently (already does). Validation dropping logs a counter to telemetry. If a device has a high drop rate, that's a GPS hardware issue, not a recording bug, and we can identify it.
- Adversarial robustness: a motivated attacker can write a fake GPX file and upload via the API. `gpsValidation.ts` runs on *recording input*, not on upload input. Backend-side validation on upload is a separate concern (exists, WS-10). Mobile validation is about honest recordings, not fraud prevention at the API layer.

**Obligation 5: Crash recovery must preserve canonical integrity.**

`mobile/src/services/database.ts` already handles crash recovery — on app crash mid-ride, the SQLite `recording_sessions` table holds the in-progress state and the ride can be resumed. But the recovery path must not introduce non-canonical differences (e.g. a crash gap that later gets interpolated with synthetic samples would produce a different hash than a clean recording).

**Implementation:**
- Audit `database.ts` recovery path. Check: does it interpolate missing samples across the crash window? If yes, interpolation must be deterministic and documented (canonical spec must know about it). If no, the crash window just has a gap in the trace, which is honest.
- Preferred: no interpolation. A crash during recording produces a ride with an honest gap. Backend canonicalization handles gaps the same as any other non-continuous trace (WS-10 spec).
- Defensive: after a crash recovery, the ride carries a `had_crash_recovery: BOOLEAN` flag in SQLite. On upload, backend logs this and can investigate if needed. Not a rejection, just a breadcrumb.
- Test: unit test that records 30s of samples, force-kills the recording store mid-session, reloads, records 30s more, stops. The final exported GPX should contain 60s of samples (not interpolated), and the canonical hash should equal a clean 60s recording with the same GPS points (modulo the gap).

#### 6.9.3 New mobile modules for recording alignment

Concrete files to add or modify. Scoped to make recording TRUTHS-compliant without rewriting the recording pipeline.

**Modify:**
- `mobile/src/services/gpxExporter.ts` — audit non-canonical fields, strip device IDs, strip export timestamps, add unit test for cross-device reproducibility.
- `mobile/src/services/database.ts` — add `preliminary_ride_hash BLOB(32)` and `parser_version INTEGER` columns to `rides`. Migration.
- `mobile/src/services/uploadQueue.ts` — send `preliminary_ride_hash` + `parser_version` with each upload. Handle backend's re-canonicalization mismatch response as a first-class error state.
- `mobile/src/lib/gpsValidation.ts` — reconcile constants with backend-side validation. Shared constants file or asserted-equal test.
- `mobile/src/stores/recordingStore.ts` — on stop-recording, trigger preliminary hash computation before marking ride as "ready to upload." New state: `hashing` between `stopped` and `queued`.

**Add:**
- `mobile/src/lib/preliminaryHash.ts` — module that computes the preliminary hash. Phase A: calls backend `POST /rides/preliminary-hash` with the file bytes, gets hash back. Phase C: calls native UniFFI canonicalization module directly. Interface is the same; only implementation swaps.
- Backend endpoint `POST /rides/preliminary-hash` — takes ride bytes, returns canonical bytes + ride_hash + parser_version used. Pure compute, no DB write, no side effects. Adds a ~5ms backend call per ride stop. Trivial.
- `mobile/src/components/RideReviewBanner.tsx` — the UI surface for a "ride under review" state when backend re-canonicalization diverges from preliminary hash. Explains to the rider what happened and offers a "report" action.
- `mobile/src/hooks/useRideAttestationStatus.ts` — already partially covered by `useRideLifecycle` (§6.8.6), but specifically tracks the preliminary-hash-vs-chain-hash comparison once RideAttestation lands. Upgrades chip state when they match.

#### 6.9.4 Recording obligations fold into the phased rollout

- **Phase A:** Obligations 1, 3, 4, 5 (reproducibility audit, parser version column, GPS constant reconciliation, crash recovery audit). No native canonicalization yet — these are audit/migration/test tasks against existing code.
- **Phase B:** Obligation 2 via backend `/preliminary-hash` bridge (§6.3 Path 2c). Wires tamper-evident check without requiring the native module. Also wires the `useRideLifecycle` phase UI (§6.8.6) to show explicit processing/provisional/attested states.
- **Phase C:** Obligation 2 upgraded to local native canonicalization via UniFFI (§6.8.3). Closes the trust chain. Rider can verify entirely locally.

---

## 7. Fix priority (what to do first)

**Language / Figma drift (near-term, UI-only):**
1. **§3.1 — ClimbDetail_Economy Leaderboard card.** The one structural semantic gap. Design spec in this doc, implementation when the other agent thaws or Tim queues it. Minimum-invasive patch — conditional additive card, no existing element changes.
2. **§3.3 — BoulderRolled Leaderboard-entry gold moment.** Polish pass. Do after BeetleCard + Map v6 ship. Ties into Tim's existing gold budget rule.
3. **§2 confirmations** — nothing to do, just don't churn BeetleCard / `ClimbDetail_*` frame naming / BoulderRolled hero.
4. **§3.2 — `Leaderboards` → `Leaderboard` tab label tightening.** Drive-by fix only if frames are re-touched. Not worth opening the file for.
5. **§3.5 — `MOBILE_DATA_CONTRACTS.md` header pointer.** One-line addition. 2 minutes of work. Do whenever convenient.

**Read-layer architecture (Phase A, after V4-A green):**
6. **§6.5 + §6.8.1/.2 codegen pipeline** — `mobile/scripts/gen-chain-types.ts` generating `chain/generated/{accounts,pdas}.ts` from IDL. Cross-surface decoder test in CI. New beads issue under `wdvr.6` tail or a fresh epic `mobile-read-layer`.
7. **§6.5 Phase A runtime modules** — `chain.ts`, `verify.ts`, `VerifyChip.tsx`, `useVerifiedValue.ts`, Zustand `verifyStore`, persistent `chain_cache` SQLite table, `chainSync.ts` background service.
8. **§6.2 Priority wiring** — Economy tab verify chips first (Stake, Pending, Wallet), then HomeScreen balance chip, then new Leaderboard card verify chip.
9. **§6.8.2 version gate** — add `program_version: u8` to `ProgramConfig` in V4-A (one-line chain change, fold into `wdvr.5`). Deploy runbook updated to require version bump on every chain change.
10. **§6.8.8 telemetry-first rollout** — ship chip infrastructure behind dev flag, run telemetry-only for a week on real devnet traffic, then progressive flag flip.

**Recording-surface alignment (Phase A, parallel with read-layer):**
11. **§6.9.2 Obligation 1** — audit `gpxExporter.ts` for non-canonical fields. Add cross-device reproducibility unit test.
12. **§6.9.2 Obligation 3** — add `parser_version INTEGER` column to mobile `rides` SQLite schema. Stamp at ride stop. Send with upload. Backend supports versioned canonicalization (WS-10 requirement).
13. **§6.9.2 Obligation 4** — reconcile `gpsValidation.ts` constants with backend-side validation. Asserted-equal test.
14. **§6.9.2 Obligation 5** — audit `database.ts` crash recovery for canonical integrity. Add `had_crash_recovery` breadcrumb. Unit test for cross-recording reproducibility.

**Read-layer architecture (Phase B, after V4-B green):**
15. **§6.5 Phase B modules** — `canonicalize.ts` interface + backend `POST /rides/preliminary-hash` endpoint (Path 2c bridge, also serves §6.9.2 Obligation 2).
16. **§6.8.6 post-ride phase UI** — `useRideLifecycle.ts` with explicit `uploaded` → `provisional` → `attested` state machine. `RideReviewBanner.tsx` for tamper-evident divergence.
17. **§5 rename sweep** — coordinated with V4-B backend route rename. `VaultSummary` → `ClimbSummary`, etc. Track under `wdvr.8`.
18. **Ride verification chip** on post-ride reveal + ride history.

**Phase C (polish, tamper-evident closure):**
19. **§6.8.3 UniFFI canonicalization** — `workout-parse` gets `#[uniffi::export]` on `canonicalize()`. iOS xcframework + Android AAR. Expo config plugin. Bundled with Privy/Sentry prebuild work.
20. **§6.9.2 Obligation 2 local** — `preliminaryHash.ts` swaps backend bridge for native UniFFI call. Tamper-evident chain closes end-to-end.
21. **Profile "Verify all" button** + background-sync re-verify.
22. **Diverged-state Sentry integration** (requires Sentry un-stubbed from Expo dev workarounds).

**Explicitly deferred:**
- `MOBILE_DATA_CONTRACTS.md` full rewrite — defer until V4-B backend routes rename, then regenerate from handlers.
- WASM canonicalization path (§6.3 Path 2b) — not building, not a real option.
- Mobile instruction submission — never. P13 rule, mobile reads chain only.

---

## 8. What this doc is NOT

- **Not a redesign.** Everything in §3 is additive or non-destructive to shipped v6 frames. Tim's "ULTRA careful" rule is the binding constraint.
- **Not a chain-side spec.** Those live in `PROTOCOL_TRUTHS.md`, `PROTOCOL_ALIGNMENT_FIX_PLAN.md`, `FRESHEST_SPEC.md`. This doc only handles the translation layer between chain truth and what the rider sees.
- **Not a tab rework.** The `Feed/Vaults/Profile` vs `Home/Map/Record/You` tab drift is flagged in `figma_mobile_design_file_2026-04-13.md` already. Not re-opened here.
- **Not a LANGUAGE_SPEC replacement.** `docs/design/LANGUAGE_SPEC.md` defines Deposit/Withdraw/Collect CTAs and portal-facing copy. This doc extends that framework specifically for mobile + PROTOCOL_TRUTHS alignment. They complement each other; neither supersedes.
- **Not a mobile instruction-submission plan.** Per §6.6, mobile reads chain, mobile never writes chain. Transaction submission stays backend-attested per P13.

---

## 9. Open questions for Tim

1. **Leaderboard card visibility for rank 11+.** When a rider is on the Leaderboard bubble but not in the top 10 (e.g. their time is 11th, one bump away from seat 10), does the Economy tab hint at it? Proposed: no — the card is binary (seated or not). Reading "you are rank 11, one seat away from earnings" adds engagement but also adds FOMO energy Tim has pushed back on elsewhere.
2. **Claim verb vs Harvest.** Staker yield already uses `Collect` in v6. Leaderboard earnings in §3.1 uses `Claim`. Both fit semantically (you collect accruals, you claim royalty). Is the verb differentiation worth the extra vocabulary load, or should both be `Collect`?
3. **Local Legend earnings surface.** The 3% bucket. It's visible on the Leaderboards tab (the rider holds the seat, seat-holder is shown), but not on the Economy tab. Do we add a fourth conditional card for Legend holders? The card count climbs fast — Leaderboard (cond) + Stake + Pending + Legend (cond) + Wallet + Stakers row = 6 zones. Might be too dense. Proposal: Local Legend yield folds into the *existing* Pending card as an additional line for seat holders. One card, two-line Pending when applicable: `+23.4 CAL · staker` / `+5.1 CAL · legend seat`. Lighter structural change than a fourth card.

Tim decisions needed on these three before §3.1 moves to implementation.

---

**End of crosswalk.** Sibling doc to `PROTOCOL_TRUTHS.md`. Lives with the mobile design work. Updated when frames ship, TRUTHS revises, or `wdvr` lands the ontology lift.
