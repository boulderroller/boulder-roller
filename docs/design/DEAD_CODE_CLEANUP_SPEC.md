# Dead Code Cleanup Spec

**Created:** 2026-04-10
**Purpose:** Actionable spec for removing dead code identified by 3 independent audits across Python backend, TypeScript frontends, and Rust/Anchor codebases. Another agent will execute this — all details are included.

**Rules:**
- Run tests after each section to catch regressions
- Backend: `cd backend && pytest -v`
- Mobile: `cd mobile && npm test`
- Anchor: `cd protocol/anchor && anchor test` (if Rust files changed)
- Don't delete anything that's part of a deployed on-chain account struct (Anchor). Deprecated fields in account structs must stay for deserialization compatibility.
- Don't delete v1 signature code (`signature.rs`) — it coexists with v2

---

## SECTION 1: BUG FIXES (do these first)

### 1.1 economic_ledger.py — wrong default denomination
**File:** `backend/app/services/economic_ledger.py`
**Lines:** ~12, 151, 175, 302, 420 (multiple methods)
**Issue:** Multiple methods default `denomination: str = "POINTS"`. Points system was removed. Any new caller that doesn't specify a denomination silently uses the dead POINTS denomination.
**Fix:** Change all `denomination: str = "POINTS"` defaults to `denomination: str = "CAL"`.
**Risk:** Medium — verify no existing callers rely on the POINTS default.

### 1.2 Admin OverviewTab — reads nonexistent field
**File:** `web/portal/src/components/admin/OverviewTab.tsx`
**Lines:** 52-53
**Issue:** `overview.points?.circulating` and `overview.points?.lifetimeTotal` — the `PlatformOverview` interface has no `points` field. Always evaluates to 0/undefined. The KPI card labeled "CAL Circulating" shows nothing.
**Fix:** Check the `PlatformOverview` type in `web/portal/src/lib/api.ts` for the correct field path (likely `overview.supply?.calCirculating` or similar). Wire to the correct field.

### 1.3 Admin EconomyTab — wrong field name
**File:** `web/portal/src/components/admin/EconomyTab.tsx`
**Line:** 32
**Issue:** `overview.vaults?.totalStakedPoints ?? 0` — the field is `totalStakedCal` not `totalStakedPoints`. Always evaluates to 0.
**Fix:** Change `totalStakedPoints` to `totalStakedCal`.

### 1.4 Mobile api.test.ts — MSW v2 incompatible with jest-expo (THE REAL FIX)
**File:** `mobile/src/lib/__tests__/api.test.ts`
**Issue:** MSW v2.7+ uses ESM-only internals (`define-network.ts`) that crash under jest-expo's CJS transform. Currently SKIPPED in `package.json` testPathIgnorePatterns — this is a band-aid, not a fix.
**Fix:** Rewrite `api.test.ts` to use `jest.fn()` mocks (matching the pattern in the other 10 test files) instead of MSW. Steps:
1. Remove `import { server } from '../../__tests__/mocks/server'` and `import { http, HttpResponse } from 'msw'`
2. Mock the fetch function directly: `global.fetch = jest.fn()` with response factories
3. Port all `server.use(http.get(...))` overrides to `(fetch as jest.Mock).mockResolvedValueOnce(...)` patterns
4. Remove `server.listen()`, `server.resetHandlers()`, `server.close()` lifecycle
5. Remove `mobile/src/__tests__/mocks/server.ts` (dead once api.test.ts is migrated)
6. Consider removing `mobile/src/__tests__/mocks/handlers.ts` if nothing else uses it
7. Remove `msw` from `package.json` devDependencies if no other files import it
8. Remove the `testPathIgnorePatterns` skip for `api.test.ts` from `package.json`
9. Run `npm test` to verify all tests pass

---

## SECTION 2: DELETE DEAD FILES (Python)

These entire files are never imported by any module:

| File | What it is | Why it's dead |
|------|-----------|---------------|
| `backend/app/services/transactions.py` | `record_token_transaction()` | Never imported anywhere |
| `backend/app/indexed_tables.py` | `USE_INDEXED_TABLES: bool = True` | Migration flag, permanently True, never imported |
| `backend/app/rate_limiter.py` | slowapi Limiter instance | Replaced by `app/middleware/rate_limiter.py` |
| `backend/app/utils/anon_names.py` | `generate_anon_name()` | Never imported by any module |

**Verification:** Before deleting each file, run `grep -r "from.*{module_name}" backend/app/ --include="*.py"` and `grep -r "import.*{module_name}" backend/app/ --include="*.py"` to confirm no imports exist.

---

## SECTION 3: STALE POINTS SYSTEM CODE (Python)

The points system was removed April 2026. CAL/DUNG are the sole currencies. Clean up these remnants:

### 3.1 epoch_processor.py — dead `is_points_period` filters
**File:** `backend/app/services/epoch_processor.py`
**Lines:** ~297, 320, 575, 698, 848, 866
**Issue:** Six `.eq("is_points_period", False)` filters. Since points removal, every epoch is non-points. These filters are always true.
**Fix:** Remove all `is_points_period` filter clauses. The queries should work the same without them.

### 3.2 distributions.py — dead `is_points_period` column
**File:** `backend/app/routes/distributions.py`
**Lines:** ~92, 211
**Fix:** Remove `is_points_period` from select column lists.

### 3.3 replay_service.py — points references throughout
**File:** `backend/app/services/replay_service.py`
**Lines:** 15, 422, 448-450, 473, 661, 766-771, 1073, 1127
**Fix:** Remove `wallet_points` table reference in docstring. Remove `total_points_delta` aggregation. Remove `"points_earned"` key handling. Remove "Points delta" narrative text generation.

### 3.4 nats_consumer.py — points logging
**File:** `backend/app/services/nats_consumer.py`
**Lines:** 120, 522
**Fix:** Remove `points={result.get('points_awarded')}` and `points={payload.get('points_awarded')}` from log format strings.

### 3.5 notification_service.py — dead points tier system
**File:** `backend/app/services/notification_service.py`
**Lines:** 57-62, 219, 250-251, 274-315, 366-378, 381-393
**Fix:** Delete `TIER_THRESHOLDS` dict, `check_and_notify_tier_threshold()`, `get_tier_for_points()`, `check_tier_crossing()`. These are never called.

### 3.6 admin_platform.py — points_events fallback
**File:** `backend/app/routes/admin_platform.py`
**Lines:** 340-358
**Fix:** Remove the `fetch_points_events()` fallback that queries the legacy `points_events` table. Keep only the `economic_events` path.

### 3.7 schemas.py — points wallet mismatch types
**File:** `backend/app/schemas.py`
**Lines:** 713-725
**Fix:** Remove `LedgerWalletMismatch` and `LedgerConsistencyResponse` classes (reference `wallet_points` table). Check if they're used by any route — if so, update the route too.

### 3.8 dev.py — wallet_points query
**File:** `backend/app/routes/dev.py`
**Lines:** 1643-1663
**Fix:** Remove the dev endpoint that queries `wallet_points` table, or update it to query `economic_events`.

### 3.9 vault.py — stale naming
**File:** `backend/app/repositories/vault.py`
**Lines:** 79, 91, 158, 215, 1038, 1096
**Fix:** Rename `points_staked` → `cal_staked`, `total_points_staked` → `total_cal_staked`, remove `dung_staked: Optional[float]` (always None). Update the API response model in `routes/vaults.py` line 160 too.

### 3.10 tasks.py — stale comments
**File:** `backend/app/tasks.py`
**Lines:** 79, 332, 360
**Fix:** Update comments from "Points, achievements, on-chain" to "CAL, achievements, on-chain".

---

## SECTION 4: UNUSED IMPORTS (Python)

Remove these unused imports. Run `pytest` after to verify nothing breaks.

| File | Line | Import | Why dead |
|------|------|--------|----------|
| `backend/app/services/ride_processor.py` | 60 | `NotificationService`, `create_notification_service` | Only `NotificationRepository` used |
| `backend/app/services/ride_processor.py` | 21 | `from decimal import Decimal` | Never used |
| `backend/app/services/ride_processor.py` | 51 | `resolve_backend_authority` | Never called |
| `backend/app/routes/rides.py` | 18 | `FileStorageService` | Only factory used |
| `backend/app/routes/strava.py` | 35 | `FileStorageService` | Only factory used |
| `backend/app/routes/mint.py` | 8 | `rate_limit` | Never used as decorator |
| `backend/app/routes/users.py` | 34 | `rate_limit` | Never used |
| `backend/app/routes/users.py` | 39 | `NotificationService` | Only factory used |
| `backend/app/routes/auth.py` | 1 | `import asyncio` | Never used |
| `backend/app/routes/beetles.py` | 14, 20 | `UUID`, `PatternType` | Never used |
| `backend/app/routes/admin.py` | 2 | `from decimal import Decimal` | Never used |
| `backend/app/routes/dev.py` | 10, 22, 26, 27 | `io`, `Annotated`, `PatternResults`, `RejectedSegment` | Never used |
| `backend/app/services/leaderboard_sync_service.py` | 37, 39 | `AccountMeta`, `Instruction`, `Transaction` | Never used |
| `backend/app/services/tx_builder.py` | 36 | `SYS_PROGRAM_ID` | Never used |
| `backend/app/services/merkle_proof.py` | 16 | `import math` | Never used |
| `backend/app/solana_direct.py` | 15 | `import asyncio` | Never used |
| `backend/app/solana_client.py` | 9 | `from decimal import Decimal` | Never used |

---

## SECTION 5: DEAD SERVICE/REPOSITORY FUNCTIONS (Python)

These functions are defined but never called. Delete them. Run `pytest` after each batch.

### Dead service functions:
| File | Function | Line |
|------|----------|------|
| `climb_vault.py` | `create_attestation()` | 407 |
| `climb_vault.py` | `get_pending_attestations()` | 479 |
| `climb_vault.py` | `match_signature_sync()` | 365 |
| `climb_vault.py` | `VaultClimb.contains_point()` | 83 |
| `fitness_analytics.py` | `get_fitness_history()` | 71 |
| `fitness_analytics.py` | `summarize_weekly_loads()` | 145 |
| `zones.py` | `calculate_power_zones()` | 63 |
| `zones.py` | `calculate_hr_zones()` | 135 |
| `zones.py` | `calculate_hr_zone_distribution()` | 199 |
| `tile_service.py` | `is_valid_tile()` | 465 |
| `tile_service.py` | `tiles_are_neighbors()` | 440 |
| `tile_service.py` | `TileAttributionService.get_road_for_tiles()` | 731 |
| `tx_builder.py` | `build_upgrade_beetle_card_tx()` | 485 |
| `vault_indexer.py` | `force_reindex()` | 250 |
| `vault_indexer.py` | `VaultSignatureCache.add_vault()` | 360 |
| `vault_indexer.py` | `VaultSignatureCache.find_by_signature_hash()` | 412 |
| `merkle_proof.py` | `get_pending_batch_count()` | 457 |
| `merkle_proof.py` | `get_stats()` | 468 |
| `patterns/climb_signature.py` | `cross_version_similarity()` | 384 |
| `patterns/climb_signature.py` | `generate_climb_signature()` (standalone fn) | 399 |
| `terrain_bootstrap.py` | `store_terrain_cell()` | 1219 |
| `strava_rate_limiter.py` | `usage_summary()` | 300 |
| `workout_parse_adapter.py` | `is_rust_parser_available()` | 374 |

### Dead repository functions:
| File | Function | Line |
|------|----------|------|
| `vault.py` | `get_completions_for_vault()` | 771 |
| `vault.py` | `count_completions_for_wallet_vault()` | 858 |
| `vault.py` | `get_full_leaderboard()` | 1376 |
| `vault.py` | `get_user_position()` | 1398 |
| `vault.py` | `record_completion_with_best_time()` | 1485 |
| `vault.py` | `record_completion_with_metadata()` | 1526 |
| `vault.py` | `get_active_leaderboard_positions_with_tenure()` | 1631 |
| `vault.py` | `update_leaderboard_history_earnings()` | 1663 |
| `vault.py` | `update_all_leaderboard_tenure()` | 1686 |
| `vault.py` | `can_flag_leaderboard()` | 1700 |
| `vault.py` | `flag_leaderboard_entry()` | 1717 |
| `vault.py` | `get_vault_disputes()` | 1825 |
| `vault.py` | `get_pending_disputes()` | 1851 |
| `vault.py` | `resolve_dispute()` | 1864 |
| `vault.py` | `remove_leaderboard_entry()` | 2057 |
| `auth.py` | `is_current_session()` | 339 |
| `auth.py` | `update_session_last_used()` | 357 |
| `notification.py` | `create_payout_notifications_batch()` | 324 |
| `notification.py` | `dismiss_notification()` | 228 |
| `detection_profile.py` | `list_profiles()` | 216 |
| `detection_profile.py` | `clear_cache()` | 228 |

**Before deleting:** Verify each with `grep -r "function_name" backend/app/ --include="*.py"` to confirm no callers exist.

---

## SECTION 6: DEAD TYPESCRIPT COMPONENTS + PAGES

### 6.1 Dead pages (not routed in AuthenticatedApp.tsx)
Delete these files:
- `web/portal/src/pages/VaultFlowDemo.tsx`
- `web/portal/src/pages/BeetleStore.tsx`
- `web/portal/src/pages/MySegments.tsx`

Also remove any lazy-load imports for them in `AuthenticatedApp.tsx` if present.

### 6.2 Dead ride components (never imported)
Delete these files:
- `web/portal/src/components/ride/KudosCard.tsx`
- `web/portal/src/components/ride/MapPlaceholder.tsx`
- `web/portal/src/components/ride/PowerCurvePlaceholder.tsx`
- `web/portal/src/components/ride/WeatherCard.tsx`
- `web/portal/src/components/ride/MachineManifest.tsx`
- `web/portal/src/components/ride/LapsTable.tsx`
- `web/portal/src/components/ride/StatsPanel.tsx`
- `web/portal/src/components/ride/SegmentRow.tsx`

### 6.3 Dead UI components (never imported)
- `web/portal/src/components/ui/AchievementBadge.tsx`
- `web/portal/src/components/ui/LeaderboardTable.tsx`
- `web/portal/src/components/layout/DashboardHeader.tsx`
- `web/portal/src/components/figma/ImageWithFallback.tsx`

### 6.4 Dead beetle components + barrel
- `web/portal/src/components/beetle/BeetleCardDisplay.tsx`
- `web/portal/src/components/beetle/UpgradeModal.tsx`
- `web/portal/src/components/beetle/index.ts` (barrel — nothing imports from it)

### 6.5 Dead hooks
- `web/portal/src/hooks/useFocusTrap.ts`
- `web/portal/src/hooks/useEscapeKey.ts`
- `web/portal/src/hooks/useScrollLock.ts`
- `web/scan/src/hooks/useDocumentTitle.ts`

### 6.6 Dead mobile exports (unused)
- `mobile/src/lib/analytics.ts` — `trackEvent` never imported. Remove the function (keep the file if `initAnalytics` is used).
- `mobile/src/lib/sentry.ts` — `setSentryUser`, `clearSentryUser` never imported. Remove those two functions.
- `mobile/src/services/uploadQueue.ts` line 262 — Remove `queryClient.invalidateQueries({ queryKey: ['points'] })`.
- `mobile/src/screens/ProfileScreen.tsx` lines 203-218 — Remove unused styles `pointsCard`, `pointsTotal`, `pointsLabel`.
- `mobile/src/__tests__/mocks/handlers.ts` lines 37, 44-54, 96 — Remove `total_points`, `/points/balance` mock handler, `points_earned` from mock data.

### 6.7 Mobile points remnants in mock test data
- `mobile/src/__tests__/mocks/handlers.ts` — Remove the `/points/balance` endpoint handler and `total_points` from user mock. Update `points_earned` to `calEarned` in ride status mock.

### 6.8 Stale admin component references
- `web/portal/src/components/admin/ActivityFeed.tsx` line 17 — Remove `points_award: Zap` from icon map (event type no longer fires).
- `web/scan/src/lib/format.test.ts` line 21 — Remove or update test for `createVaultPointsPeriod` status.

---

## SECTION 7: DEAD RUST CODE (workout-parse)

### 7.1 Dead functions
- `workout-parse/src/climb/persistence.rs:2496` — `fn dedup_effort_bounds` (non-indexed variant). Only used in a test. The indexed variant `dedup_effort_bounds_indexed` (line 2533) is the production one. Delete the function and its test at line 3545.
- `workout-parse/src/climb/signature_v2.rs:155` — `fn dct_ii_f32`. Never called. Delete.

### 7.2 Dead struct fields
- `workout-parse/src/climb/persistence.rs:944-946` — `SegmentWindow.time_s` and `SegmentWindow.descent_m`. Written but never read. Remove fields and their assignments (~line 990-992).
- `workout-parse/src/climb/persistence.rs:954-955` — `WindowCluster.start_window_idx` and `WindowCluster.end_window_idx`. Written but never read. Remove fields and their assignments (~line 1051-1052).

### 7.3 Dead variables
- `workout-parse/src/lib.rs:329` — `in_trkpt` in `parse_gpx`. Assigned but never read. Prefix with `_` or remove.
- `workout-parse/src/lib.rs:502` — `in_trackpoint` in `parse_tcx`. Same fix.

### 7.4 Stale constants (12 total, all in `workout-parse/src/climb/constants.rs`)
All superseded by `ClimbDetectorConfig` struct fields:
- Line 47: `GRADIENT_START_THRESHOLD`
- Line 50: `GRADIENT_END_THRESHOLD`
- Line 56: `GRADIENT_END_PERSISTENCE`
- Lines 63-81: `MOMENTUM_CLIMB_RATE`, `MOMENTUM_DRAIN_RATE`, `MOMENTUM_DECAY_RATE`, `MOMENTUM_START_THRESHOLD`, `MOMENTUM_END_THRESHOLD`, `MOMENTUM_MAX`, `MOMENTUM_GRADIENT_NEUTRAL`

Also in `workout-parse/src/constants.rs`:
- Line 34: `MAX_TILE_ZOOM` — never used
- Line 38: `FIT_EPOCH_OFFSET_S` — never used

**Before deleting:** Grep for each constant name to confirm zero usage outside constants.rs.

### 7.5 Dead signature method
- `workout-parse/src/climb/signature.rs:39` — `ClimbSignature::gradient_profile_hash`. Not used in Rust or exposed via PyO3. Delete.

**After all Rust changes:** Run `cargo build --release` and `cargo test` in workout-parse/. Run `maturin develop` to rebuild Python bindings.

---

## SECTION 8: DEAD ANCHOR CODE (protocol/anchor)

**IMPORTANT:** Removing events and error codes changes the IDL. After changes, run `anchor build` and regenerate TypeScript client types. Verify the indexer still compiles.

### 8.1 Never-emitted events (safe to remove)
- Line 4197: `CalMinted` — never `emit!`'d
- Line 4292: `VaultDungEmitted` — legacy instant-conversion event
- Line 4341: `DungMinted` — never `emit!`'d
- Line 4379: `CalUnstaked` — replaced by `UnstakeWithFee`

### 8.2 Never-used error codes (15 total, safe to remove)
`AlreadyMintedToday`, `InsufficientCal`, `InvalidDistance`, `AlreadyDistributed`, `EpochNotEnded`, `SeatOccupied`, `CardAlreadyExists`, `SupplyCapExceeded`, `AllocationCapExceeded`, `MissingProtocolTreasury`, `InsufficientDungForUpgrade`, `EliteGateNotMet`, `BatchNotFound`, `NotOwner`, `EscrowNotInitialized`

**Before removing:** Grep each name across the entire `programs/boulder_rollers/src/` to confirm zero usage in `require!()` or error returns.

### 8.3 Dead method
- `DistributionConfig::default_config()` — line 114. Never called. Delete.

### 8.4 Stale size constant
- `ProgramConfig::SIZE` (V1) — line 2481. All code uses `SIZE_V2` or `SIZE_V3`. Delete.

### 8.5 DO NOT DELETE (deprecated but required for deserialization)
These fields MUST stay in the account structs — removing them would break deserialization of existing on-chain accounts:
- `Vault.total_staked` (line 2729)
- `VaultStake.amount` (line 2884)
- `UserState.legacy_cal_snapshot`, `legacy_cal_earned_today`, `legacy_last_cal_mint` (lines 2277-2281)

---

## EXECUTION ORDER

1. Section 1 (bug fixes) — highest impact, fixes broken UI
2. Section 3 (points cleanup) — largest surface area of stale code
3. Section 2 (dead files) — quick wins
4. Section 4 (unused imports) — quick wins
5. Section 5 (dead functions) — medium effort, large LOC reduction
6. Section 6 (TypeScript) — medium effort
7. Section 7 (Rust) — requires rebuild + test
8. Section 8 (Anchor) — requires IDL regen, do last

Run tests between each section. Commit after each section with a descriptive message.
