# Pre-TGE Work Summary

> **STATUS: HISTORICAL — superseded by the July 2026 zero-start decision.**
> There is no TGE: no liquid market exists, is scheduled, or may be presented
> as a horizon. This checklist belongs to the points era (removed April 2026).
> Kept for visible history. Current truth: `docs/PROTOCOL_TRUTHS.md`,
> `docs/FRESHEST_SPEC.md`.

**Created:** January 21, 2026
**Status:** Partially complete — see updates below

> **April 2026 Update:** The points system has been **fully removed** from the codebase.
> `points_service.py`, `wallet_points`, `points_events`, `points_config`, `tge_conversions` tables
> all deleted. Pre-TGE entitlement gates removed. The protocol runs on CAL/DUNG directly (live on devnet).
> Items marked ~~strikethrough~~ below are resolved by this removal.

## What's Done

1. **FRESHEST_SPEC.md** created - authoritative internal spec
2. **CLAUDE.md** updated - source of truth hierarchy correct
3. **Issues created** in bd for all pre-TGE work
4. **Points system removed** (April 2026) - protocol is live CAL/DUNG on devnet

## Key Spec Decisions

- **CAL**: SPL token on Solana devnet (live)
- **Vesting**: NONE - 100% at TGE (Hyperliquid-style)
- ~~**Points period duration**: HIDDEN from public~~ (points system removed)
- **Exit fee**: 0.5% planned but not implemented
- ~~**Conversion UI**: DEFERRED (lowkey approach)~~ (no conversion needed — points removed)

## Critical Issues (P0)

### 1. CAL SPL Token Migration (`boulderroller-v2-6e3`)
- CAL is u64 in UserState PDA
- Needs to be real SPL token for DEX trading
- Requires: CalMintState PDA, migration instruction, update all CAL instructions

### 2. Exit Fee Implementation (`boulderroller-v2-8bx`)
- Add EXIT_FEE_BPS = 50 (0.5%)
- Deduct from unstake_cal_from_vault
- Fee to treasury or burn

### 3. Admin Authority Checks (`boulderroller-v2-f85`)
- admin_credit_cal, admin_debit_cal, record_vault_completion have NO auth
- Add ProgramConfig PDA with admin/backend_authority pubkeys
- Add has_one constraints

### ~~4. Backend TGE Conversion (`boulderroller-v2-kud`)~~ — RESOLVED (removed)
- ~~execute_tge_conversion() only updates DB~~
- ~~Need actual SPL DUNG minting~~
- ~~Batch endpoint for all users~~
- **Status:** Points system removed April 2026. No TGE conversion needed.

## High Priority Issues (P1)

### 5. Vault Leaderboard Update (`boulderroller-v2-009`)
- record_vault_completion doesn't call leaderboard.update_entry()
- Wire up the update

### 6. DUNG Mint Authority (`boulderroller-v2-5fp`)
- harvest_rewards uses Vault PDA as mint authority
- Should be unified through dung_mint program

### 7. Emission Rate / Halving (`boulderroller-v2-a7o`)
- apply_emission_rate() exists but never called
- Wire into distribution logic

### 8. ATA Pre-flight (`boulderroller-v2-pjg`)
- Distribution fails if ATAs don't exist
- Add checks before distribute_epoch_rewards

### ~~9. Frontend Dynamic Labels (`boulderroller-v2-b0s`)~~ — RESOLVED (removed)
- ~~50+ hardcoded "points" strings~~
- ~~Create useTokenPeriod hook~~
- **Status:** Points system removed. CAL/DUNG labels are now static. No ProtocolModeContext needed.

### ~~10. Frontend App Flows (`boulderroller-v2-7k8`)~~ — RESOLVED (removed)
- ~~Different tx paths for points vs CAL staking~~
- ~~Create FeatureFlagContext~~
- **Status:** Single code path for CAL/DUNG. No mode switching.

### 11. Token Balance Fetching (`boulderroller-v2-98a`)
- No on-chain SPL balance fetching
- Create useTokenBalances hook
- Add VITE_DUNG_MINT, VITE_CAL_MINT env vars

### 12. Security Audit Prep (`boulderroller-v2-u82`)
- Admin authority controls
- Re-entrancy review
- Freeze authority decisions

## Medium/Low Priority

### 13. Governance Config (`boulderroller-v2-dx7`)
- Make fees/terms configurable via ProtocolConfig PDA

### 14. Deprecated Code Cleanup (`boulderroller-v2-dt8`)
- Remove: mint_daily_cal, DUNG staking, process_vault_tribute, SwannySeat

## File Locations

- **Anchor**: `protocol/anchor/programs/boulder_rollers/src/lib.rs`
- **Backend**: `backend/app/services/`, `backend/app/routes/`
- **Frontend**: `web/portal/src/`
- **Spec**: `docs/FRESHEST_SPEC.md`

## Distribution Splits (Reference)

```
55% Leaderboard (top 10: 30/20/15/10/8/6/5/3/2/1%)
27% Stakers (unlock curve: 1/3/6/11/17/25/35/50/70/100%)
3%  Soigneur (elected, 8-epoch term)
5%  POL
10% Protocol Treasury
```

## Key Constants (Reference)

```rust
EXIT_FEE_BPS = 50           // 0.5% - TO IMPLEMENT
HARVEST_FEE_BPS = 500       // 5%
MINIMUM_STAKE = 100         // 100 CAL
LOCAL_LEGEND_TERM_EPOCHS = 8
MINTER_RIGHTS_EPOCHS = 12
EPOCHS_PER_HALVING = 26
```
