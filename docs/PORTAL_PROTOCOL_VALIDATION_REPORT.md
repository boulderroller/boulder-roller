# Portal <-> On-Chain Validation Report

**Date:** 2026-03-23
**Verdict:** If we flip `isActive` right now, the portal renders but **two critical bugs** cause wrong token amounts. Everything else is cosmetic or non-blocking.

**Confidence score: 7/10** -- structurally sound, two data bugs need backend fixes before real money flows.

> **April 2026 Update:** The points system and `ProtocolModeContext` have been removed from the codebase.
> The portal now operates exclusively in CAL/DUNG mode. References to "points mode", `isPointsMode`,
> `PROTOCOL_MODE`, and `points_config.is_active` below are historical context from the original audit.

---

## 1. ProtocolModeContext -- ~~Does TGE Mode Actually Work?~~ REMOVED

> **April 2026:** `ProtocolModeContext` has been removed. The points config endpoint (`GET /points/config`),
> `points_service.py`, `points.py` routes, and `PROTOCOL_MODE` env var have all been deleted.
> The portal now displays CAL/DUNG labels statically. The section below is historical.

### ~~PASS (with caveats)~~ — N/A (removed)

~~**Config endpoint verified.** `GET /points/config` is implemented in `backend/app/routes/points.py:117`. It reads from `PointsService.get_config()` which queries the `points_config` Supabase table. The `is_active` field controls the mode. The backend also supports `PROTOCOL_MODE=tge` env var override in `points_service.py:259` which force-returns `False` regardless of DB state.~~

~~**Fallback is dangerous.** If the config fetch fails, the backend returns a hardcoded fallback with `is_active=True` (points.py:126). The portal also has a fallback default of `isActive: true` (ProtocolModeContext.tsx:88). This means **any config fetch failure silently reverts the portal to points mode**. Not a bug per se, but worth knowing.~~

**TGE branches in every key screen verified:**

| Component | Points Branch | TGE Branch | Verdict |
|-----------|--------------|------------|---------|
| Portfolio.tsx | Shows points ledger, entitlements, multiplier | Shows CAL/DUNG balances, staked positions, distribution weeks | **PASS** -- both branches are fully implemented |
| Vaults.tsx | "Backed" / "Your Total Backed" | "Staked" / labels.staking | **PASS** -- uses ProtocolMode labels |
| VaultView.tsx | "Back" / points / no tx signing | "Stake" / CAL / prepares+signs transactions | **PASS** -- full prepare-sign-submit flow wired |
| RideView.tsx | VaultPanel shows matched vaults | Same + vault creation with payment methods | **PASS** |
| BeetleStore.tsx | Shows points balance | Shows DUNG balance from useTokenBalances | **PASS** |
| Leaderboard.tsx | Hardcoded text, no mode branch | Same -- leaderboard is mode-agnostic | **PASS** |
| ActivityFeedItem.tsx | `dungEarned` field displayed | Same field | **PASS** -- though the field name is misleading in points mode |

**No screens are points-only.** Every screen that touches economics has explicit `isPointsMode` / `mode === 'tge'` branching.

---

## 2. Token Display Accuracy

### FAIL -- CRITICAL: Backend returns raw atomic units for CAL balance in TGE mode

**The bug:** `backend/app/solana_direct.py:328` returns `int(balance.value.amount)` -- raw atomic units (lamports-equivalent for a 9-decimal SPL token). Both `cal.py:49-54` and `portfolio.py:52` pass this raw integer through `float()` without dividing by 10^9.

If a user has 1.5 CAL on-chain, the backend returns `calBalance: 1500000000.0`. The portal displays this as "1,500,000,000" CAL.

**Affected endpoints:**
- `GET /cal/onchain` (cal.py:49) -- used by `useCALBalance` hook
- `GET /portfolio` (portfolio.py:52) -- used by `usePortfolio` hook
- `POST /vaults/:id/stake` (vaults.py:1175-1187) -- balance check `on_chain_cal < stake_request.cal_amount` compares atomic vs human-readable

**Portal side is fine.** The `useTokenBalances` hook in `usePortfolio.ts:23-27` reads directly from Solana RPC using `getTokenAccountBalance()` which returns `uiAmount` (already divided by decimals). This path works correctly. But the `useCALBalance` hook calls `GET /cal/onchain` which returns the wrong number.

**Impact:** In TGE mode, the Portfolio page's "On-Chain Snapshot" section and the VaultView staking balance display will show inflated numbers (10^9 too large) for any data coming through the backend API.

**Fix required in:** `backend/app/solana_direct.py` -- `get_cal_balance()` should return human-readable amounts (divide by 10^9), or the callers should divide. Same pattern needed for any DUNG balance reads through the backend.

**Severity:** CRITICAL -- users would see "1,500,000,000 CAL" instead of "1.5 CAL" and staking amount validation would break.

---

### PASS: Portal direct RPC reads handle decimals correctly

`useTokenBalances` (usePortfolio.ts:23) uses Solana's `getTokenAccountBalance()` which returns `uiAmount` as a pre-divided float. The portal correctly uses this value. This is the TGE-mode primary balance source.

### PASS: No hardcoded mock balances in production code

No placeholder/mock/dummy values found in Portfolio, Vaults, or VaultView. The only mock is `mockAchievement` in AuthenticatedApp.tsx:225 which is a demo achievement for the unlock modal -- not displayed in normal flow.

---

## 3. Vault Data Contract

### PASS: Vault list shape matches

Backend `VaultSummary` (vaults.py:38-54) returns all fields the portal `Vault` type (api.ts:2073-2093) expects, with automatic snake_case to camelCase conversion. Field mapping verified:

| Backend | Portal | Match |
|---------|--------|-------|
| `id`, `signature_hex`, `name` | Same | OK |
| `vert_m`, `distance_m`, `avg_gradient_pct` | Same | OK |
| `total_completions`, `total_staked` | Same | OK |
| `kom_holder`, `kom_time_s`, `minter` | Same | OK |
| `start_lat`, `start_lon` | Same | OK |
| `on_chain_active`, `on_chain_seeding_status` | Same | OK |

### FAIL (Minor): Portal expects `endLat`/`endLon` but backend doesn't return them

Portal type `Vault` (api.ts:2089-2090) has `endLat?: number | null` and `endLon?: number | null`. Backend `VaultSummary` (vaults.py:38-54) does not include `end_lat` or `end_lon`. These fields are optional (`?`) so this doesn't crash anything, but the portal can never display vault end coordinates.

**Impact:** Nice-to-have, not blocking. The portal doesn't actually display these fields in any UI component today.

### FAIL (Medium): LocalLegend field names mismatch between backend and portal

The portal expects (api.ts:2099-2104):
```typescript
localLegend: {
  wallet: string;
  electedEpoch: number;    // <-- expects epoch number
  termEndEpoch: number;    // <-- expects epoch number
  completionsCount: number;
}
```

The backend returns (vaults.py:68-76, via swanny_seats table):
```python
LocalLegendResponse:
  wallet: str
  elected_at: Optional[str]    # <-- returns ISO timestamp string
  term_ends_at: Optional[str]  # <-- returns ISO timestamp string
  completions_count: Optional[int]
```

After camelCase conversion: `electedAt` (string) vs portal's `electedEpoch` (number). `termEndsAt` (string) vs portal's `termEndEpoch` (number).

**Impact:** The VaultView (VaultView.tsx:681) only accesses `vault.localLegend.wallet` and `vault.localLegend.completionsCount`. It does NOT display `electedEpoch` or `termEndEpoch`. So the mismatch exists in the type definition but doesn't cause a runtime error or display bug. The `completionsCount` field works because the backend returns `completions_count` which camelCases to `completionsCount`.

**Severity:** Medium -- type definition is wrong, but no visible bug because the mismatched fields aren't used in rendering.

### PASS: Leaderboard data shape matches

Backend `LeaderboardEntryResponse` (vaults.py:57-65) maps correctly to portal `VaultLeaderboardEntry` (api.ts:2107-2115) after camelCase conversion.

### PASS: Staking flow calls the right endpoints

VaultView.tsx stake flow traced:
1. `api.prepareStakeInVault(vault.id, amount)` -> `POST /vaults/:id/stake/prepare` with `{cal_amount}` -- matches backend `StakeRequest`
2. `signPreparedTransaction(prepared)` -> signs the `transaction` field from `PreparedTransactionResponse` -- correct
3. `api.stakeInVault(vault.id, amount, signedTransaction)` -> `POST /vaults/:id/stake` with `{cal_amount, signed_transaction}` -- matches

### FAIL (Minor): Stake/Unstake response shape mismatch -- not used

Portal types `VaultStakeResponse` (api.ts:2170-2173) expects `{stake: VaultStake, newTotalStaked: number}`.
Backend returns `StakeResponse` (vaults.py:178-186) with `{vault_signature, cal_staked, lp_tokens_received, total_position, tx_signature, stake, new_total_staked}`.

The portal IGNORES the stake/unstake return values entirely. VaultView.tsx:363-371 immediately calls `toast.success()` and then `queryClient.invalidateQueries()` to refetch fresh data. So the shape mismatch doesn't matter.

**Severity:** Low -- type is wrong but unused.

---

## 4. Transaction Flow Integrity

### PASS: Prepare-sign-submit flow is correct

Full trace of VaultView stake flow:

1. **UI initiates:** `handleStake()` at VaultView.tsx:335
2. **Mode check:** `if (mode === 'tge')` -- enters prepare-sign branch
3. **Prepare:** `api.prepareStakeInVault(vault.id, amount)` calls `POST /vaults/:id/stake/prepare`
4. **Backend builds tx:** `get_tx_builder().build_stake_tx()` creates unsigned tx with correct accounts
5. **Portal signs:** `signPreparedTransaction(prepared)` deserializes base64 tx, routes to wallet adapter or Privy
6. **Submit:** `api.stakeInVault(vault.id, amount, signedTransaction)` sends signed tx back
7. **Backend validates:** `_decode_signed_transaction_or_400()` + `_assert_signed_transaction_matches()` verifies message bytes match
8. **Backend submits:** `builder.submit_signed_transaction()` sends to Solana
9. **DB update:** `stake_cal_with_cap` atomic RPC

### PASS: Error handling doesn't leave broken state

On tx failure:
- Backend catches exceptions and returns HTTP errors with clean messages
- Portal catches in try/catch, calls `toast.error(err.message)`, resets loading state
- React Query caches are only invalidated on SUCCESS (after toast.success)
- No partial state corruption possible

### PASS: Partial signing handled correctly

Backend signs as authority/fee-payer, user signs as staker. The `PreparedTransactionResponse.transaction` contains a partially-signed tx (backend has already signed its part). The user's wallet adapter adds the second signature. `_assert_signed_transaction_matches` verifies the message bytes haven't been tampered with.

### No pending/confirming/confirmed state machine

The portal uses a simple loading boolean (`isStaking`, `isUnstaking`, `isHarvesting`). There is no pending->confirming->confirmed state machine. The API call blocks until the transaction is confirmed on-chain, then returns. This means the loading spinner covers the entire ~1-5s confirmation time. For a first version this is acceptable -- the user sees "Staking..." then "Staked!". No intermediate "Confirming on chain..." state exists.

**Impact:** UX improvement opportunity, not a bug.

---

## 5. Wallet and Address Alignment

### PASS: All three systems use the same addresses

| Address | Registry (addresses.devnet.json) | Backend (solana_env.py) | Portal (solana.ts) |
|---------|----------------------------------|------------------------|--------------------|
| Program | `EVjP2Vdz9buHNphywPhoybf213poa8EiSW6FGbXWFqYH` | Same (via registry loader) | Same (hardcoded default) |
| CAL Mint | `4bxTCxEQp993cXs5nqhfWthRCPSTDv5K6PMgsfunEaJh` | Same | Same |
| DUNG Mint | `CqDFJWLpr49tB8xjHegy5JR5jwMCfmhicjuWawtKLeCk` | Same | Same |

### PASS: No old mint addresses in portal

Searched for `B9u8L5pkWTce2SXJCKvNSKTrSukvWoajEdzy9STLNh6K` (old CAL from MEMORY.md) and `AnPJmvr1HK36DwWNQpdwW2vBd7Qq7AtAerU9kuqA9Sfn` (old DUNG) in the portal codebase. Zero matches.

### PASS: Portal does not derive PDAs

The portal never derives PDAs. All PDA derivation happens on the backend (tx_builder, solana_direct). The portal just receives prepared transactions with PDAs baked in.

### NOTE: MEMORY.md addresses are stale

MEMORY.md references different addresses (B9u8..., AnPJ...) for CAL and DUNG mints. The actual registry and all code has moved to the 2EG8.../8eUu... addresses. MEMORY.md is outdated but this doesn't affect the codebase.

---

## 6. Missing Error States

### PASS: Vault activation status handled

VaultView.tsx:561-603 shows a prominent banner when `vault.onChainActive === false`, with seeding status messages:
- "Queued for activation"
- "Seeding in progress"
- "Data seeded, awaiting activation"
- "Activating on-chain"
- "Activation pending retry"

Staking UI is disabled with "Vault not yet activated" message (VaultView.tsx:1126-1162).

### PASS: Missing CAL ATA handled gracefully

`useTokenBalances` hook (usePortfolio.ts:17-30) wraps RPC calls in try/catch and returns 0 on any error, including missing ATA. The `readAtaBalance` function catches all errors silently.

For the backend API path (`GET /cal/onchain`), if the ATA doesn't exist, `get_cal_balance()` returns 0 (solana_direct.py:324-325).

### PASS: Empty distribution state handled

VaultView.tsx:1467-1477 shows "No distributions yet" with "Rewards are distributed weekly on Sundays" when no distributions exist. Portfolio.tsx:1212-1225 shows "No Distributions Yet" similarly.

### No handling for stale indexed data

If the TS indexer falls behind, indexed tables will show stale data. There is no staleness indicator in the portal. The portal has no way to know if data is stale because the backend doesn't report indexer lag.

**Impact:** Low risk for Day 1 (indexer is not yet the primary read path for most endpoints). Becomes important when fully migrated to indexed tables.

---

## 7. API Contract Gaps

### FAIL -- CRITICAL: Backend CAL balance returns raw atomic units in TGE mode

(Same as finding #2 above. Repeating for completeness.)

- `GET /cal/onchain` returns raw `int(balance.value.amount)` without dividing by 10^9
- `GET /portfolio` does the same for `cal_balance` in non-points-period mode
- The portal `useCALBalance` hook consumes this value directly
- Fix: divide by 10^9 in `solana_direct.get_cal_balance()` or in the route handlers

### FAIL (Medium): Backend stake endpoint checks atomic-unit balance against human-readable request

In `vaults.py:1175-1187`:
```python
on_chain_cal = await solana_direct.get_cal_balance(current_user.wallet)  # returns atomic units
if on_chain_cal < stake_request.cal_amount:  # cal_amount is human-readable (e.g., 100)
```

This comparison is broken. If user has 150 CAL (= 150,000,000,000 atomic), `on_chain_cal` is `150000000000` which is always > any reasonable `cal_amount`. So the balance check never fails -- it accidentally passes. If someone requests to stake 10^12 CAL, this would also pass the check incorrectly.

**Impact:** The check is functionally a no-op (always passes), which means there's no balance validation in TGE mode for staking. The on-chain program itself will reject insufficient funds, so it's not exploitable, but the error message would be a confusing Solana program error instead of a clean HTTP 400.

### Portal field the backend doesn't return (non-blocking):

| Portal Field | Portal Type | Backend Provides | Impact |
|---|---|---|---|
| `Vault.endLat` | `number \| null` | Not in VaultSummary | None -- not displayed |
| `Vault.endLon` | `number \| null` | Not in VaultSummary | None -- not displayed |
| `Vault.pda` | `string?` | Not in VaultSummary (only in VaultDetail) | None -- only used in detail view |
| `Vault.signatureHashHex` | `string?` | Not in VaultSummary (only in VaultDetail) | None -- only used in detail view |
| `VaultDetail.localLegend.electedEpoch` | `number` | Returns `elected_at: string` | Mismatch but field not rendered |
| `VaultDetail.localLegend.termEndEpoch` | `number` | Returns `term_ends_at: string` | Mismatch but field not rendered |

### Backend returns fields the portal ignores (non-blocking):

| Backend Field | Endpoint | Portal Action |
|---|---|---|
| `StakeResponse.cal_staked` | POST /vaults/:id/stake | Ignored -- portal refetches via invalidateQueries |
| `StakeResponse.lp_tokens_received` | Same | Ignored |
| `StakeResponse.total_position` | Same | Ignored |
| ~~`HarvestResponse.is_points_period`~~ | POST /vaults/:id/harvest | ~~Used for display label~~ (points field removed) |
| `on_chain_tx` field on completions | Various | Not displayed -- could link to explorer |

### Epoch endpoint already returns `endsAt`

The `GET /distributions/epoch/current` endpoint (distributions.py:258-286) already returns `ends_at` as ISO timestamp. The portal type `CurrentEpochResponse` (api.ts:1892-1896) expects `endsAt`. After camelCase conversion this matches. The data is there; the portal just doesn't have a countdown component yet.

---

## Summary

### Critical (Must fix before activation)

| # | Area | File | Issue | Fix |
|---|------|------|-------|-----|
| C1 | Token display | `backend/app/solana_direct.py:328` | `get_cal_balance()` returns raw atomic units (not divided by 10^9) | Divide by `10**9` before returning, or create a `get_cal_balance_ui()` wrapper |
| C2 | Token display | `backend/app/routes/cal.py:49`, `backend/app/routes/portfolio.py:52` | Callers pass raw atomic int through `float()` without decimal conversion | Use the fixed `get_cal_balance()` or divide in the route handler |
| C3 | Balance check | `backend/app/routes/vaults.py:1183` | TGE-mode stake balance check compares atomic units vs human-readable amount | After fixing C1, this comparison becomes correct |

### Medium (Should fix but won't crash)

| # | Area | File | Issue |
|---|------|------|-------|
| M1 | Type contract | `web/portal/src/lib/api.ts:2101-2102` | `electedEpoch`/`termEndEpoch` should be `electedAt`/`termEndsAt` (string timestamps) -- field not rendered so no visible bug |
| M2 | Type contract | `web/portal/src/lib/api.ts:2170-2173` | `VaultStakeResponse` shape doesn't match backend `StakeResponse` -- return value is ignored |

### Nice-to-have (Post-activation)

| # | Area | Issue |
|---|------|-------|
| N1 | UX | No pending->confirming->confirmed state machine for tx flows (loading boolean only) |
| N2 | Data | No indexer staleness indicator |
| N3 | Type | Portal `Vault` type includes `endLat`/`endLon` that backend doesn't provide |
| ~~N4~~ | ~~UX~~ | ~~Config fetch failure silently falls back to points mode~~ (points mode removed) |
| N5 | Mock | `mockAchievement` in AuthenticatedApp.tsx is harmless but should be removed |
| N6 | Display | `on_chain_tx` from vault completions not shown as explorer link |

### What works perfectly right now

- ~~ProtocolModeContext mode switch and all label/verb replacements~~ (removed — static CAL/DUNG labels now)
- Wallet signing flow (Phantom, Solflare, Privy) for stake/unstake/harvest/create
- Direct-from-RPC token balance reads (useTokenBalances) with correct decimal handling
- Vault list/detail/leaderboard/local legend display
- Distribution receipts and history
- Epoch endpoint with `endsAt` timestamp
- Address alignment across all three systems (portal, backend, chain)
- Error states for vault activation, empty distributions, network errors
- Session management, refresh, expiry handling
