# Portal UI/UX Gap Analysis for Protocol Activation

**Date:** 2026-03-23
**Scope:** Transition from points period (Supabase-as-truth, shadow mode) to real on-chain protocol (Solana chain-as-truth, Supabase-as-read-cache)

---

## 1. Current State: Screen-by-Screen Inventory

### 1.1 Route Map (from AuthenticatedApp.tsx)

| Route | Page Component | Data Sources | Status |
|-------|---------------|--------------|--------|
| `/` | ActivityFeed | `GET /feed/global` | Working |
| `/profile` | Profile | `GET /users/me`, `GET /users/:id` | Working |
| `/athletes/:beetleNumber` | Profile | Same | Working |
| `/my-activities` | MyActivities | `GET /rides` | Working |
| `/data` | Data | `GET /analytics/fitness`, `GET /analytics/training-load` | Working |
| `/portfolio` | Portfolio | Points + portfolio + distributions + CAL/token balances | **Dual-mode ready** |
| `/map` | Map | `GET /territory/tiles`, `GET /vaults` | Working |
| `/leaderboard` | Leaderboard | `GET /leaderboard/:type` | Working |
| `/vaults` | Vaults | `GET /vaults`, `GET /vaults/my/stakes` | **Dual-mode ready** |
| `/vaults/:vaultId` | VaultView | Vault detail + leaderboard + stake + harvest + distributions | **Dual-mode ready** |
| `/find-friends` | FindFriends | `GET /social/suggested` | Working |
| `/achievements` | Achievements | `GET /users/me/achievements` | Working |
| `/activities/:activityId` | RideView | Ride + GPS + telemetry + patterns + tiles | Working |
| `/activities/:activityId/analyze` | AnalyzeView | Same as RideView | Working |
| `/segments/:segmentId` | SegmentView | `GET /segments/:id`, `GET /segments/:id/leaderboard` | Working |
| `/settings` | Settings | User profile, sessions, privacy, Strava | Working |
| `/notifications` | Notifications | `GET /notifications` | Working |
| `/docs` | Docs | Static | Working |
| `/admin` | AdminDashboard | Multiple admin endpoints | Working |
| `/strava/callback` | StravaCallback | Strava OAuth | Working |
| `/onboarding` | Onboarding | Profile setup flow | Working |

### 1.2 ProtocolModeContext: The Mode Switch

The portal already has a `ProtocolModeContext` that determines behavior based on `config.isActive`:
- `isActive === true` => `mode: 'points'` (current)
- `isActive === false` => `mode: 'tge'` (protocol activation)

This context provides:
- **Dynamic labels:** `token` ("points" vs "CAL"), `valueToken` ("points" vs "DUNG"), `stake` ("back" vs "stake"), etc.
- **`usesOnChain` flag:** `false` for points, `true` for TGE
- Fetched from `GET /points/config` endpoint

**Key finding:** The mode switch infrastructure already exists. The primary remaining work is ensuring every UI surface handles `mode === 'tge'` correctly and that data flows from chain-indexed tables instead of Supabase-direct tables.

### 1.3 Wallet & Transaction Infrastructure

Already in place:
- **WalletContext:** Solana wallet adapter with `ConnectionProvider` pointing to configurable RPC
- **PrivyContext:** Embedded wallet signing for social-login users
- **useWalletTransactionSigner hook:** Handles both wallet-direct and Privy signing of prepared transactions
- **solana.ts:** Configurable program ID, mint addresses, RPC URL, explorer URL helper
- **useTokenBalances hook:** Reads CAL and DUNG ATA balances directly from Solana RPC (already live!)

### 1.4 Data Access Patterns

The portal **only** communicates through the backend API (`/api` proxy to FastAPI). It does NOT use Supabase client directly. All data flows through `lib/api.ts` APIClient class.

This is good news: the data source transition is entirely a backend concern. The portal just needs correct API contracts.

---

## 2. Protocol Requirements: What the Real Protocol Demands

### 2.1 Source of Truth Shift

| Data | Current Source | Protocol Source | Impact |
|------|---------------|-----------------|--------|
| Vault list & metadata | `indexed_vaults` table (Supabase) | `indexed_vaults` populated by TS indexer from chain | **Backend swap only** - portal API unchanged |
| Vault completions | `vault_completions` (Supabase RPC) | Indexed from on-chain completion events | Backend swap |
| Vault stakes | `vault_stakes` (Supabase) | Indexed from on-chain stake events | Backend swap |
| Leaderboards | `vault_leaderboards` (Supabase) | Indexed from on-chain leaderboard state | Backend swap |
| Local Legend | `local_legends` (Supabase) | Indexed from on-chain LocalLegend PDA | Backend swap |
| CAL/DUNG balances | `GET /cal/onchain` + `GET /points/balance` | Direct RPC reads (already in useTokenBalances) | **Already works** |
| Epoch/distributions | `vault_distributions` + points_events | Indexed from on-chain epoch distributions | Backend swap |
| User profile/rides | Supabase tables | Stays in Supabase (off-chain data) | No change |

**Key finding:** Because the portal already goes through the backend API, the data source transition is almost entirely a backend concern. The portal's API contracts stay the same — the backend just changes where it reads from.

### 2.2 Transaction Flow Changes

Currently (points mode): User action => backend API call => Supabase write => done.

Protocol mode: User action => backend prepares transaction => portal signs => backend submits => chain confirms => indexer picks up => read cache updated.

The portal already has the `prepare + sign + submit` pattern wired for:
- `stakeInVault` / `unstakeFromVault`
- `harvestVaultRewards`
- `createVault`

These use `useWalletTransactionSigner` which handles both Phantom/Solflare (wallet adapter) and Privy (embedded wallet).

### 2.3 New Economic Primitives to Display

| Primitive | Currently Shown | Needed for Protocol |
|-----------|----------------|---------------------|
| CAL balance | Yes (on-chain PDA read + portfolio) | Same, but primary display |
| DUNG balance | Yes (ATA read in useTokenBalances) | Same, but primary display |
| CAL tribute per ride | No | New: show CAL tributed to each vault crossed |
| Vault pending DUNG rewards | Yes (VaultView) | Same |
| Epoch countdown timer | No | New: live countdown to next distribution |
| Staker unlock curve | No | New: show what % of staker pool is unlocked |
| Distribution share percentages | Partially (leaderboard payouts in VaultView) | Need explicit 55/27/3/5/10 breakdown |
| Transaction signatures | Partially (harvest shows tx link) | All economic actions need tx confirmation UX |
| Vault on-chain status | Yes (onChainActive, seedingStatus) | Same |

---

## 3. Gap Matrix: Current vs Needed

### Priority Legend
- **P0 (Day 1):** Must work at launch
- **P1 (Day 1-3):** Expected within first week
- **P2 (Day 3-6):** Nice to have for activation week
- **P3 (Post-activation):** Can follow later

### 3.1 Screens That Exist and Need Updates

| Screen | Gap | Priority | Effort |
|--------|-----|----------|--------|
| **Portfolio** | Already dual-mode. Points labels need removal when in TGE mode. "Points Period Active" banner should become "Protocol Live". Points ledger section should hide or transform to on-chain tx history. | P0 | S |
| **VaultView** | Already full-featured (leaderboard, stake, harvest, distributions, effort history, local legend). Main gap: no epoch countdown, no explicit distribution share percentages shown, no CAL tribute display. | P1 | S |
| **Vaults list** | Already works. No changes needed for protocol activation — VaultCard already shows completions, staked amount, gradient, KOM. Labels already dynamic. | P0 | XS |
| **Leaderboard** | Already functional (climb/steady/exploration tabs, period filters, user stats). No protocol-specific changes needed — data source change is backend-only. | P0 | XS |
| **RideView** | Vault creation is intentionally absent: detected ride climbs may nominate canon review but cannot supply economic identity. VaultPanel shows matched canonical vaults. Gap: should show CAL tribute per vault crossed on this ride. | P1 | S |
| **Map** | Shows territory tiles and vault markers. No protocol-specific changes needed. | P0 | XS |
| **ActivityFeed** | Shows rides with TSS/points earned. Gap: needs to show CAL earned instead of points when in TGE mode. | P1 | S |
| **Data (Training)** | Pure fitness analytics (CTL/ATL/TSB). No protocol interaction. No changes needed. | -- | -- |
| **Profile** | Shows user stats, streak, rides. Gap: should show BeetleCard summary and vault completions count in protocol mode. | P2 | M |
| **Settings** | Auth, sessions, privacy, Strava. No protocol changes needed. | -- | -- |
| **Achievements** | Currently hardcoded achievement list with API integration. Works as-is. | -- | -- |
| **BeetleStore** | Shows "Coming Soon" placeholder. No changes needed for Day 1. | P3 | -- |

### 3.2 Screens That DON'T Exist Yet

| Missing Screen | What It Needs | Priority | Effort |
|----------------|---------------|----------|--------|
| **Epoch Dashboard** | Current epoch number, countdown timer to next distribution (Sun 12:00 UTC), pending rewards summary across all user's vaults, recent distribution history | P1 | M |
| **Transaction History** | User's on-chain transaction log (completions, stakes, unstakes, harvests, vault creations). Filter by type. Link to Solana Explorer for each. | P2 | M |
| **BeetleCard Detail View** | Full-screen view of a BeetleCard with upgrade path, DUNG burn cost, level thresholds, gate requirements (L4, L6, L7, L9). Upgrade button with tx signing. | P2 | L |
| **Vault Creation from Climb** | Implemented on the exact ratified Climb page. The action appears only when that immutable Climb revision is available and has no Vault. | -- | -- |

### 3.3 Components That Exist and Need Updates

| Component | Gap | Priority | Effort |
|-----------|-----|----------|--------|
| **ProtocolModeContext** | Default fallback is `isActive: true` (points mode). For protocol activation, the backend `GET /points/config` must return `isActive: false`. No code change needed — this is a backend config change. | P0 | XS |
| **TopNav / AppSidebar** | Currently shows "Points Period" indicator somewhere. Needs to show "Protocol Live" or similar when activated. | P0 | XS |
| **PointsCounter** | Animated golden counter. Works for any number. Can be reused for CAL/DUNG displays. | -- | -- |
| **BeetleCard component** | Already fully built (Pokemon-card style with type, level, score, progress bar, rarity, upgrade cost). Used in Profile page. | -- | -- |
| **InlineStakeWidget** | Compact stake/unstake UI. Already handles `onChainActive` flag. Already uses protocol mode labels. | -- | -- |
| **CanonVaultCreationModal** | Exact Climb-page payment selection and wallet signing. It accepts only the server-offered DUNG or CAL+USDC methods; identity and route fields are not rider-editable. | -- | -- |
| **EntitlementGate** | Gates vault creation based on points/tier entitlements. In protocol mode, should be removed or replaced with balance check (100 DUNG to create). | P1 | S |

### 3.4 "Points Period" / "Simulation" Language in UI

Locations where points-era language is baked in and needs conditional or removal:

| Location | Current Text | Protocol Text | File |
|----------|-------------|---------------|------|
| Portfolio header | "Points ledger, entitlements, and distribution history" | "Live token balances, vault economics, and distribution receipts" | Portfolio.tsx (already dual-mode) |
| Portfolio overview | "Points Period Active" | "Protocol Live" or "TGE Mode Active" | Portfolio.tsx (already handled) |
| Portfolio ledger | "POINTS LEDGER" | "POINTS-PERIOD LEDGER" (historical) | Portfolio.tsx (already handled) |
| Portfolio how-it-works | "How Points Work" | "How Live Vault Economics Work" | Portfolio.tsx (already handled) |
| Vaults page subtitle | "Back climbs you believe in" | Same (works for both modes) | Vaults.tsx |
| VaultView stake button | "Back" vs "Stake" | Already dynamic via `labels.stake` | VaultView.tsx |
| Feed items | `dungEarned` / `pointsEarned` | Need to show CAL earned | ActivityFeedItem.tsx |
| Ride type `pointsEarned` field | Type includes `pointsEarned?: number` | Should also show `calEarned` | api.ts types |

**Key finding:** The Portal already has excellent dual-mode support via ProtocolModeContext. Most screens already branch on `mode === 'points'` vs `mode === 'tge'`. The remaining gaps are small.

---

## 4. API Gaps

### 4.1 Existing Endpoints (No Changes Needed)

These endpoints exist and serve the portal correctly. The backend may need to change its data source (Supabase -> indexed tables), but the API contract stays the same:

- `GET /vaults` — Vault list
- `GET /vaults/:id` — Vault detail with leaderboard, local legend, stakes
- `POST /vaults/:id/stake/prepare` + `POST /vaults/:id/stake` — Stake flow
- `POST /vaults/:id/unstake/prepare` + `POST /vaults/:id/unstake` — Unstake flow
- `POST /vaults/:id/harvest/prepare` + `POST /vaults/:id/harvest` — Harvest flow
- `GET /vaults/:id/pending-rewards` — Pending rewards
- `GET /vaults/my/stakes` — User's stakes
- `GET /vaults/my/completions` — User's completions
- `GET /vaults/:id/my-completions` — User's effort history on a vault
- `POST /vaults/create/prepare` + `POST /vaults/create` — Vault creation
- `GET /distributions/my` — User's distribution receipts
- `GET /distributions/vault/:id` — Vault distribution history
- `GET /distributions/epoch/current` — Current epoch info
- `GET /cal/onchain` — CAL balance from on-chain
- `GET /portfolio` — Aggregated portfolio
- `GET /leaderboard/:type` — Global leaderboards
- All ride/activity/social/auth endpoints — unchanged

### 4.2 Endpoints That Need Updates (Backend Work)

| Endpoint | Current Behavior | Needed Behavior | Priority |
|----------|-----------------|-----------------|----------|
| `GET /points/config` | Returns `isActive: true` | Must return `isActive: false` to trigger TGE mode in portal | P0 |
| `GET /portfolio` | Mixes points + on-chain data | Should return chain-derived data when in protocol mode | P0 |
| `GET /distributions/epoch/current` | Returns epoch info | Should include precise `endsAt` ISO timestamp for countdown | P1 |
| `GET /rides/:id` | Returns `pointsEarned` | Should also return `calEarned`, `calTributed` (per vault) | P1 |
| `GET /rides/:id/patterns` | Returns climb patterns with vault matches | Should include `calTributed` per matched vault | P1 |

### 4.3 New Endpoints Needed

| Endpoint | Purpose | Priority | Effort |
|----------|---------|----------|--------|
| `GET /users/me/transactions` | On-chain transaction history for user (completions, stakes, harvests, creations). Paginated. Filter by type. | P2 | M |
| `GET /vaults/:id/staker-curve` | Returns current staker count and unlock percentage (for staker unlock curve display) | P2 | S |
| `GET /beetles/my-cards/:type/upgrade/prepare` | Prepare BeetleCard upgrade transaction | P2 | M |
| `POST /beetles/my-cards/:type/upgrade` | Execute BeetleCard upgrade (burn DUNG) | P2 | M |
| `GET /protocol/stats` | Protocol-wide stats: total CAL staked, total DUNG distributed, total vaults, active epoch, etc. (for a protocol health banner) | P3 | S |

### 4.4 Endpoints That Can Be Removed Post-Activation

| Endpoint | Reason |
|----------|--------|
| `GET /points/balance` | Replaced by on-chain CAL/DUNG balances |
| `GET /points/events` | Replaced by on-chain transaction history |
| `GET /points/leaderboard` | Replaced by on-chain leaderboard |
| `GET /points/tiers` | Entitlements no longer points-gated |
| `GET /points/tge/preview` | TGE is live, no preview needed |
| `POST /points/tge/convert` | Conversion happens at TGE, one-time |

Note: These should be kept read-only for historical audit purposes, but removed from active UI.

---

## 5. UX Recommendations for Chain-Native Interactions

### 5.1 Transaction Confirmation Flow

The portal already has the prepare-sign-submit pattern. Recommended UX:

1. **User initiates action** (stake, unstake, harvest, create vault)
2. **Show inline loading state** ("Preparing transaction...") — already done via `BeetleButton` `isLoading` + `loadingLabel`
3. **Wallet popup appears** for signing (Phantom/Solflare) or auto-sign (Privy embedded)
4. **Show "Confirming on chain..."** state after signature
5. **Success toast with Explorer link** — already implemented in VaultView harvest flow
6. **Invalidate relevant React Query caches** — already implemented with `queryClient.invalidateQueries`

**Gap:** Steps 4 is implicit (the API call blocks until confirmed). For better UX, the API could return immediately with a tx signature, and the portal could poll for confirmation. However, this is an optimization — the current synchronous flow works.

### 5.2 Wallet Connection State

Already well-handled:
- **Privy:** Social login users get embedded Solana wallets automatically. Signing is seamless.
- **Wallet adapter:** Phantom/Solflare users connect at login. `useWalletTransactionSigner` handles reconnection.
- **Auth handoff:** `AuthHandoffScreen` shows during Privy token exchange.

**Gap:** No explicit "wallet not connected" state on staking pages. If a user somehow loses wallet connection mid-session, the error handling in `useWalletTransactionSigner` throws descriptive errors, but there's no proactive reconnect prompt.

**Recommendation:** Add a subtle banner on VaultView/Portfolio when `canSignTransactions` is false: "Reconnect wallet to stake/harvest."

### 5.3 Real Token Amounts vs Points Display

The `useFormatters` hook and `formatNumber` utilities handle display formatting. The `ProtocolModeContext` labels handle naming.

**Remaining concern:** CAL and DUNG are SPL tokens with 9 decimals. The `useTokenBalances` hook already reads `uiAmount` (human-readable) from Solana RPC. However, amounts coming from the backend API (e.g., stake amounts, distribution amounts) may need decimal handling if the backend returns raw lamport-style values.

**Recommendation:** Ensure all backend API responses return human-readable token amounts (divide by 10^9 on the backend), not raw u64 values. The portal should never do decimal conversion.

### 5.4 Gas/Rent Cost Visibility

**Current state:** Gas costs are invisible to users. The backend pays for transaction fees using `SOLANA_PAYER_SECRET`.

**Recommendation for protocol activation:** Keep backend-sponsored gas for core actions (stake, unstake, harvest, complete). Show a small note: "Transaction fees sponsored by the protocol." This avoids friction while being transparent.

**Future consideration:** If/when gas sponsorship is removed, add a small "Est. fee: 0.000005 SOL" line before transaction signing.

### 5.5 Error Handling for Chain Congestion

The `api.ts` client already handles:
- Network errors with retry (3 retries, exponential backoff)
- 500 errors with retry
- Session expiry with token refresh
- Offline detection with network restored events

**Gap:** No specific handling for Solana-specific errors:
- `TransactionExpiredBlockheightExceeded` — transaction timed out
- `InsufficientFundsForRent` — account below rent-exempt minimum
- `ProgramError` — on-chain program returned an error

**Recommendation:** The backend should translate Solana errors into user-friendly messages before returning them to the portal. The portal already shows `toast.error(err.message)` — the message just needs to be good.

### 5.6 Epoch Countdown UX

**Not built yet.** Recommended approach:

Add to VaultView and Portfolio pages:
```
Current Epoch: 47
Next Distribution: 2d 14h 32m
```

Implementation: `GET /distributions/epoch/current` should return `endsAt` ISO timestamp. Portal renders a countdown timer component. This is a small, high-impact feature for engagement.

---

## 6. Design System & Component Inventory

### 6.1 Framework & Stack

| Layer | Technology |
|-------|-----------|
| Framework | React 18 SPA, Vite 6, react-router-dom |
| Styling | Tailwind CSS v4 + inline styles via `useTheme()` |
| Components | shadcn/ui (Radix) + custom "Beetle" components |
| State | React Query (TanStack) for server state, React context for app state |
| Maps | Leaflet + react-leaflet + h3-js |
| Charts | Recharts |
| Icons | lucide-react |
| Wallet | @solana/wallet-adapter + Privy |

### 6.2 Design Quality Assessment

**Strengths (preserve these):**
- "Brutalist Beetle" aesthetic is distinctive and consistent: zero radius, hard shadows, mechanical interactions
- Inter + Cousine dual-font system works well (UI text vs data values)
- 6-theme system with dark mode is novel
- SEMANTIC_COLORS (DUNG gold, CAL blue, crown gold) are well-defined
- Loading states are comprehensive (skeletons, inline pending indicators, background fetch indicators)
- Error states are well-handled (retry buttons, stale data fallback, error messages)

**Weaknesses (known debt, per DESIGN_SYSTEM_RULES.md):**
- Hardcoded hex values in some components (Hoo-Breddin theme leaking)
- No formal type scale (13+ ad-hoc sizes)
- shadcn vs Beetle component boundary unclear
- Mobile responsiveness is minimal (desktop-first, sidebar collapse only)

### 6.3 Reusable Components for Protocol Features

These existing components can be directly reused:

| Component | Reuse For |
|-----------|-----------|
| `BeetleButton` (with `isLoading`, `loadingLabel`) | All transaction CTAs |
| `BeetleCard` | Epoch dashboard cards, transaction history cards |
| `StatPill` / `PointsCounter` | Token balance displays |
| `InlineStakeWidget` | Compact staking anywhere |
| `LeaderboardRow` | Vault leaderboard, BeetleCard leaderboard |
| `LoadingSkeleton` (multi-variant) | Any new loading states |
| `InlinePendingState` | Background refresh indicators |
| `SectionLoadingState` | Full section loading |
| `VaultCard` (in Vaults.tsx) | Vault grid items |
| `LeaderboardRow` (in VaultView) | Per-vault top 10 |
| `BeetleCard` component | BeetleCard display (already Pokemon-card style) |
| `VaultModalShell` | Modal frame for vault interactions |

### 6.4 Mobile Responsiveness

Current state: Desktop-first with minimal mobile support. Sidebar collapses to sheet overlay at 768px. Some grid layouts use `md:grid-cols-*` breakpoints. Many components have no responsive adjustments.

**For protocol activation:** Mobile is likely secondary (power users riding bikes will primarily use desktop). However, the Portfolio and VaultView pages should be usable on mobile since riders may check earnings from their phones.

**Recommendation:** Focus responsive work on Portfolio, Vaults list, and VaultView. These are the most protocol-relevant screens. Effort: M.

---

## 7. Effort Summary

### Day 1 (P0) — Protocol Goes Live

| Task | Effort | Description |
|------|--------|-------------|
| Backend: Set `isActive: false` in points config | XS | Flips the mode switch |
| Backend: Ensure portfolio endpoint returns chain-derived data | S | Data source swap |
| Portal: Verify all screens render correctly in TGE mode | S | QA pass with mode toggled |
| Portal: Remove/hide points-era banners/labels | XS | Already mostly conditional |
| **Total P0** | **S** | ~1-2 days |

### Day 1-3 (P1) — Core Protocol UX

| Task | Effort | Description |
|------|--------|-------------|
| Epoch countdown component + wiring | S | Timer on VaultView + Portfolio |
| Backend: Add `endsAt` to epoch endpoint | XS | One field |
| Backend: Add `calTributed` to ride patterns | S | Per-vault tribute display |
| Update ride view to show CAL tribute per vault | S | New section in VaultPanel |
| Update activity feed to show CAL earned | S | Conditional label swap |
| EntitlementGate: Replace points-tier gate with DUNG balance check | S | Simplification |
| Wallet reconnect banner on staking pages | XS | Small UX improvement |
| **Total P1** | **M** | ~3-4 days |

### Day 3-6 (P2) — Protocol Depth

| Task | Effort | Description |
|------|--------|-------------|
| Transaction history page | M | New page with on-chain tx log |
| Backend: `GET /users/me/transactions` endpoint | M | Indexed tx query |
| BeetleCard upgrade flow (prepare + sign + burn) | L | New UI + 2 new endpoints |
| Staker unlock curve display on VaultView | S | Visual + new endpoint |
| Profile page: BeetleCard summary, vault stats | M | Enhancement |
| Distribution share percentage breakdown (55/27/3/5/10) | S | Visual on VaultView |
| Mobile responsiveness for Portfolio + VaultView | M | Responsive CSS |
| **Total P2** | **L** | ~5-7 days |

### Post-Activation (P3)

| Task | Effort | Description |
|------|--------|-------------|
| Protocol stats dashboard (total staked, distributed, etc.) | M | New section or page |
| BeetleStore with real DUNG redemptions | XL | Major feature |
| Vault creation standalone page | S | New route |
| BoulderScan integration (link to public explorer) | S | External links |
| Remove dead points-era code paths | S | Cleanup |

---

## 8. Key Findings Summary

1. **The portal is significantly more protocol-ready than expected.** The `ProtocolModeContext` with dual-mode labels, the `useWalletTransactionSigner` hook, the prepare-sign-submit transaction pattern, and the `useTokenBalances` direct RPC reads are all already built and working.

2. **The data source transition is a backend-only concern.** The portal communicates exclusively through the backend API — no Supabase client. When the backend swaps from Supabase tables to indexed chain tables, the portal doesn't need to change.

3. **The biggest UI gaps are additive, not corrective.** The main missing pieces are: epoch countdown, transaction history page, CAL tribute display per ride, BeetleCard upgrade flow, and staker unlock curve visualization. None of these block launch.

4. **The "points period" language is already gated.** Almost every screen that shows points-era text already branches on `mode === 'points'` vs `mode === 'tge'`. Setting `isActive: false` on the backend config is the primary switch.

5. **Transaction UX is already solved.** VaultView already handles stake, unstake, and harvest with wallet signing, loading states, success toasts with Explorer links, and React Query cache invalidation. This pattern just needs to be replicated for new actions (BeetleCard upgrades).

6. **Solana address configuration needs updating for mainnet.** The `solana.ts` file has hardcoded devnet addresses as defaults. For mainnet deployment, the environment variables `VITE_BOULDER_ROLLERS_PROGRAM_ID`, `VITE_CAL_MINT_ADDRESS`, `VITE_DUNG_MINT_ADDRESS`, `VITE_SOLANA_RPC`, and `VITE_SOLANA_NETWORK` must be set correctly in the Vercel deployment.
