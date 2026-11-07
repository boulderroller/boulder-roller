# Mobile Architecture Production Readiness Review

**Date:** 2026-03-28
**Reviewer:** Senior Mobile Architect (automated review)
**Scope:** `mobile/` scaffold -- App.tsx, 4 screens, API client, config, navigation, package.json
**Context:** DePIN application on Solana where ride data drives real economic token distributions
**Verdict:** Early scaffold. Not production-ready. Significant structural gaps must be addressed before any real user or real economic value touches this code.

---

## Executive Summary

The mobile scaffold is exactly what it claims to be: a placeholder shell with 7 source files, 4 screens (1 functional list, 2 data-fetching lists, 1 static placeholder), and an API client. It is correctly structured for a React Native Expo project and demonstrates awareness of the right technologies (Privy, Solana MWA, expo-secure-store). However, it is missing virtually every layer required for a production DePIN application: no auth flow, no state management, no local persistence, no error handling, no tests, no CI/CD, no crash reporting, no security hardening, and no GPS recording infrastructure.

The gap between this scaffold and a shippable v1 is roughly 10-14 weeks of focused mobile development, consistent with the strategy document's estimates. The good news: the scaffold makes no catastrophically wrong decisions. The architecture is salvageable. The bad news: almost nothing here can be shipped as-is.

---

## 1. Architecture Pattern

### Current State: No Architecture

**Rating: Hobby-grade**

The scaffold has no architecture pattern. Each screen is a self-contained component that directly imports the API singleton, manages its own loading/error/data state via `useState`, and renders inline. This is acceptable for a 7-file scaffold but will collapse under the weight of real features.

**Specific issues:**

- **No separation of concerns.** UI rendering, data fetching, error handling, and business logic are interleaved in every screen component. `HomeScreen.tsx` fetches data, formats distances, formats durations, renders cards, and handles empty states -- all in one component.

- **No state management layer.** Auth state is buried inside the API client singleton (`this.accessToken`). There is no React context, no store, no way for components to reactively respond to auth state changes. When `api.clearTokens()` is called on 401, no component re-renders. The user sees stale UI until they manually navigate.

- **Singleton API client is untestable.** `export const api = new APIClient()` at module scope means every test file shares the same instance. Cannot mock, cannot isolate, cannot run tests in parallel.

- **No dependency injection.** Services are imported directly. Swapping implementations (e.g., mock API for testing, different storage backend) requires changing import paths throughout the codebase.

### Recommended Architecture

```
src/
  app/                    # App entry, providers, navigation
  screens/                # Screen components (thin -- delegate to hooks)
  components/             # Shared UI components
  hooks/                  # Custom hooks (useAuth, useRides, useVaults, useRecording)
  services/               # Business logic (api, auth, storage, recording, upload)
  stores/                 # Zustand stores (auth, recording, settings)
  lib/                    # Pure utilities (formatting, validation, crypto)
  types/                  # Shared TypeScript types
  constants/              # Config, theme, routes
```

**State management recommendation:**

| State type | Tool | Rationale |
|---|---|---|
| Server state (rides, vaults, points) | TanStack Query (React Query) | Cache, dedup, background refresh, offline persistence. Already used in portal. |
| Auth state | Zustand store + expo-secure-store | Persistent across app restarts, reactive, simple. |
| Recording state | Zustand store + SQLite | Complex state machine (idle/recording/paused/uploading). Needs persistence for crash recovery. |
| UI state (modals, tabs) | React local state | Ephemeral, component-scoped. Fine as-is. |
| Settings | Zustand store + AsyncStorage | Units, FTP, weight, notification prefs. |

**Priority: FIX NOW (scaffold phase).** Establishing the architecture pattern before writing feature code prevents expensive rewrites. Adding TanStack Query and Zustand to the dependency tree, creating the provider hierarchy, and wiring up one screen (HomeScreen) as the reference implementation takes 2-3 days and saves weeks later.

---

## 2. Security

### Current State: No Security

**Rating: Unshippable**

This is the most critical gap. BoulderRoller handles economic value -- points convert to tokens, staking involves real assets, vault completions trigger on-chain state changes. The security posture must match a financial application, not a social media app.

**Finding S1 (CRITICAL): Auth tokens stored in memory only**

`api.ts` line 132-133:
```typescript
private accessToken: string | null = null;
private refreshToken: string | null = null;
```

Tokens are lost on app backgrounding, app restart, or any process termination. The comment on line 138 acknowledges this: "In production, these would be persisted via expo-secure-store." This is the single highest-priority fix.

**Impact:** Users are logged out on every app restart. More critically, there is no token refresh flow -- when the access token expires, the user is silently logged out with no recovery path (line 186-188 clears tokens on any 401).

**Fix:** Use `expo-secure-store` (already in package.json) to persist tokens. Implement token refresh with the refresh token before clearing auth state.

**Finding S2 (CRITICAL): No certificate pinning**

The API client uses bare `fetch()` with no certificate pinning. On a mobile device connected to public WiFi (common for cyclists at coffee stops), a MITM attack can intercept auth tokens and ride data.

**Fix:** Use `expo-secure-store` for token storage AND implement certificate pinning via a custom `fetch` wrapper or `react-native-ssl-pinning`. At minimum, pin the leaf certificate for `api.boulderroller.org`.

**Finding S3 (HIGH): No biometric auth for sensitive operations**

Staking points (economic value), changing wallet associations, and viewing detailed financial data should require biometric confirmation. There is no `expo-local-authentication` integration.

**Fix:** Add biometric gating to: stake/unstake operations, profile changes that affect wallet, viewing seed phrase or private key material.

**Finding S4 (HIGH): Privy wallet key material protection unknown**

The Privy SDK handles embedded wallet creation and key sharding (MPC). The scaffold wraps Privy in a try/catch (App.tsx line 33-46) but does not configure any Privy security options. Questions that must be answered before launch:

- Is Privy configured to use device Secure Enclave / TEE for key storage?
- Is there a recovery flow if the device is lost?
- What happens to the embedded wallet if the user reinstalls the app?
- Is the Privy session token stored securely?

**Finding S5 (HIGH): No GPS data integrity validation**

When GPS recording is implemented, the recorded samples will become the economic truth that drives token distributions. There is currently no validation infrastructure:

- No check for impossible speeds (>120 km/h on a bicycle)
- No check for Null Island (0,0) or FIT sentinel values (-214.748)
- No check for time travel (samples with decreasing timestamps)
- No HMAC or signature on the sample payload to prevent tampering between recording and upload
- No device attestation (is this a real device or an emulator?)

**Fix (implement with Phase 1 recording):**
- Client-side: Validate each GPS sample against the same bounds used in `workout-parse/src/climb/utils.rs` (`is_valid_gps()`)
- Client-side: HMAC the serialized sample array with a device-specific key before upload
- Server-side: Validate uploaded samples match HMAC, reject impossible trajectories
- Consider: Device attestation via Apple DeviceCheck / Google Play Integrity API

**Finding S6 (MEDIUM): API URL hardcoded, no environment separation for secrets**

`config.ts` uses `__DEV__` for API URL switching, which is fine, but there is no `.env` management for secrets (Privy app ID is a placeholder string in source code). When real keys are added, they should not be committed to the repository.

**Fix:** Use `expo-constants` with `app.config.js` (not `app.json`) to inject secrets from environment variables at build time. Add `eas.json` profiles for development/staging/production.

---

## 3. Data Integrity

### Current State: No Data Layer

**Rating: Not Yet Applicable (no recording exists)**

The strategy document (`NATIVE_MOBILE_APP_STRATEGY.md` Section 3.3) defines a solid SQLite schema for local ride storage. None of it is implemented. When it is implemented, these concerns must be addressed:

**Finding D1 (CRITICAL): No crash recovery design**

The strategy document mentions crash recovery (Section 10.3) but the scaffold has no implementation. For a DePIN app where ride data = economic truth:

- SQLite writes must be journaled (WAL mode) with fsync after each batch of samples
- On app relaunch, check for `status='recording'` rides with no `ended_at`
- Offer resume or save-partial -- never silently discard
- Sample batching: write every 10 seconds (strategy doc) is correct, but each write must be atomic (BEGIN TRANSACTION / COMMIT)

**Finding D2 (CRITICAL): No upload idempotency**

The API client has no concept of idempotency keys. If a ride upload succeeds on the server but the response is lost (network timeout), the client will retry and potentially create a duplicate ride. The strategy document mentions dedup by `started_at` timestamp, but the client must also send an idempotency key (the local ride UUID) with every upload request.

**Fix:** Add `X-Idempotency-Key: {ride_uuid}` header to upload requests. Backend should check for existing ride with that key before processing.

**Finding D3 (HIGH): No upload queue with retry logic**

The strategy document specifies an upload queue with exponential backoff (Section 7.6). The current API client has no retry logic whatsoever. A failed upload is silently swallowed (empty catch blocks in every screen).

**Fix:** Implement an `UploadQueueService` backed by SQLite. Rides enter the queue on completion. A background worker processes the queue with exponential backoff (1s, 2s, 4s, 8s, ... max 1 hour). After 10 failures, surface to user.

**Finding D4 (HIGH): Device clock spoofing**

Timestamps in GPS samples come from the device clock, which the user controls. A malicious user could spoof timestamps to fake ride duration or overlap with other users' rides for economic advantage.

**Mitigation (defense in depth):**
- Server-side: Cross-reference upload timestamp with claimed ride time. Flag rides where `uploaded_at - ended_at > 48 hours` for review.
- Server-side: Validate sample frequency (1Hz expected, >5Hz or <0.1Hz is suspicious)
- Server-side: Cross-reference GPS trajectory against known road networks (already planned with OSM integration)
- Consider: NTP time check on device before ride start (not foolproof but raises the bar)

---

## 4. Testing

### Current State: No Tests

**Rating: Unshippable**

There are zero test files in the project. No Jest configuration. No React Native Testing Library. No test script in `package.json`. No E2E framework.

**Finding T1 (CRITICAL): No test infrastructure**

Missing from `devDependencies`:
- `jest` and `jest-expo`
- `@testing-library/react-native`
- `@testing-library/jest-native`
- `msw` (Mock Service Worker) for API mocking

Missing files:
- `jest.config.js`
- `__tests__/` directory
- Any `*.test.tsx` or `*.spec.tsx` file

**Recommended testing strategy for v1 launch:**

| Layer | Tool | Coverage target | Priority |
|---|---|---|---|
| Unit tests | Jest + jest-expo | API client, formatters, validators, stores | NOW |
| Component tests | React Native Testing Library | All screens, auth flows, error states | Phase 1 |
| Integration tests | RNTL + MSW | Full auth flow, ride list loading, vault display | Phase 1 |
| E2E tests | Detox or Maestro | Recording flow, upload flow, auth flow | Phase 2 |
| Snapshot tests | Jest snapshots | Regression detection for UI components | Phase 1 |

**Critical paths that MUST be tested before any user touches this:**

1. **Auth flow:** Login -> token storage -> token refresh -> logout -> token cleared from secure store
2. **Recording flow:** Start -> GPS samples collected -> pause/resume -> stop -> samples persisted to SQLite -> upload queued
3. **Upload flow:** Queue processing -> API call -> success (remove from queue) -> failure (retry with backoff) -> idempotency (no duplicates)
4. **Transaction signing:** Privy wallet creation -> transaction construction -> signing -> submission -> confirmation display
5. **Crash recovery:** Kill app during recording -> relaunch -> ride data not lost -> offer resume

**Priority: FIX NOW.** Add Jest + RNTL + MSW to devDependencies and write tests for the API client as the reference pattern. This takes 1 day and establishes the testing culture before feature code accumulates.

---

## 5. Error Handling

### Current State: Errors Silently Swallowed

**Rating: Unshippable**

**Finding E1 (CRITICAL): Every screen has empty catch blocks**

HomeScreen.tsx line 24: `catch { // Silently fail }`
VaultsScreen.tsx line 24: `catch { // Silently fail }`
ProfileScreen.tsx line 24: `catch { // Silently fail }`

When the API returns an error -- network timeout, server 500, malformed response, expired token -- the user sees no feedback. The screen shows a loading spinner forever or displays stale data.

**Fix:** Implement a global error boundary and per-screen error states:
- Network errors: Show "No connection" banner with retry button
- Auth errors: Redirect to login screen
- Server errors: Show "Something went wrong" with retry
- Never silently swallow. Log at minimum.

**Finding E2 (CRITICAL): No crash reporting**

No Sentry, Bugsnag, or any crash reporting SDK. In production, unhandled JS exceptions and native crashes will be invisible to the development team.

**Fix:** Add `@sentry/react-native` (free tier: 5K events/month, sufficient for alpha). Wire into App.tsx error boundary. Include device info, user wallet (anonymized), and app version in crash reports.

**Finding E3 (HIGH): No global error boundary**

React error boundaries catch component render errors. Without one, any unhandled error in any component crashes the entire app with a white screen.

**Fix:** Wrap the app in an `ErrorBoundary` component that catches errors, reports to Sentry, and shows a "restart app" screen.

**Finding E4 (HIGH): 401 handling clears tokens without redirect**

`api.ts` line 186-188: On 401, tokens are cleared and an error is thrown. But no component catches this error to redirect to a login screen. The user is silently logged out and sees stale authenticated UI until they navigate.

**Fix:** Auth state changes should be reactive (Zustand store). When `isAuthenticated` becomes false, the navigation root should switch from the authenticated tab navigator to a login/onboarding screen.

---

## 6. CI/CD

### Current State: No CI/CD

**Rating: Not yet needed, but must be in place before TestFlight/Play Store submission**

**Finding C1: No EAS Build configuration**

No `eas.json` file. EAS Build is the standard for Expo apps:
- Development builds for testing on real devices
- Preview builds for TestFlight/internal testing
- Production builds for App Store/Play Store submission

**Finding C2: No code signing setup**

No Apple provisioning profiles, no Android keystore referenced. These are required for:
- TestFlight distribution
- Play Store internal testing
- Production App Store/Play Store submission

**Finding C3: No automated builds**

No GitHub Actions workflow, no EAS Build triggers on push.

**Recommended CI/CD pipeline:**

```
Push to feature branch:
  -> Lint (ESLint + TypeScript)
  -> Unit tests (Jest)
  -> Component tests (RNTL)

Push to main:
  -> All above +
  -> EAS Build (development profile)
  -> Deploy to TestFlight / Play Console internal testing

Tag release:
  -> EAS Build (production profile)
  -> Submit to App Store Connect / Play Console
```

**Priority: Can wait until Phase 1 feature code exists.** But must be in place before first TestFlight build (~week 4 of Phase 1).

---

## 7. Performance

### Current State: Not Yet Relevant (no recording)

**Rating: Cannot evaluate without recording implementation**

The strategy document addresses battery optimization well (Section 3.2: adaptive accuracy, distance filtering, 8% per 30min target). Implementation concerns:

**Finding P1 (HIGH): No background task management**

`app.json` correctly declares `UIBackgroundModes: ["location"]` for iOS and `FOREGROUND_SERVICE` permission for Android. But there is no implementation. When recording is built:

- iOS: Must use `expo-location` with `startLocationUpdatesAsync()` and a proper background task
- Android: Must use a foreground service with persistent notification (standard pattern, handled by `react-native-background-geolocation`)
- Both: Must handle OS killing the background process gracefully (save state to SQLite, resume on relaunch)

**Finding P2 (HIGH): Memory management for long rides**

A 4-hour ride at 1Hz = 14,400 GPS samples. With sensor data (HR, power, cadence), each sample is ~40 bytes = ~576KB. This fits in memory, but:

- Do NOT accumulate all samples in a JS array. Write to SQLite in batches (every 10s = 10 samples). Only keep the most recent batch in memory for live display.
- FlatList in HomeScreen and VaultsScreen should use `getItemLayout` for performance with long lists
- Large ride uploads should use the presigned upload flow (strategy doc Section 7.2), not inline POST body

**Finding P3 (MEDIUM): Bundle size**

Current dependencies are reasonable. `@solana/web3.js` is the largest at ~500KB (minified). This is acceptable but should be monitored. When adding mapping (`react-native-maps`), BLE (`react-native-ble-plx`), and background location, the bundle will grow significantly. Use `npx expo-doctor` to identify unnecessary dependencies.

**Finding P4 (MEDIUM): No MapView lazy loading**

When maps are added (Phase 1), they should be lazy-loaded. Importing `react-native-maps` in a non-map screen adds to the initial bundle load time.

---

## 8. Scalability / Extensibility

### Current State: Adequate for Scaffold

**Rating: Acceptable**

**Finding X1 (GOOD): Navigation structure is extensible**

The bottom tab navigator with 4 tabs (Home, Record, Vaults, Profile) matches the strategy document. Each tab can host a stack navigator for drill-down screens (ride detail, vault detail, settings). React Navigation supports this well. No rework needed.

**Finding X2 (GOOD): API client is reasonably structured**

The `APIClient` class with typed methods per endpoint is a clean starting point. The case conversion utilities (`toSnakeCase`/`toCamelCase`) match the portal pattern. This can evolve into a TanStack Query integration without major restructuring.

**Finding X3 (MEDIUM): No shared component library**

All screens duplicate styling (same background color, header style, card style, stat layout). Before adding more screens, extract:
- `Card` component
- `StatRow` / `StatBox` components
- `EmptyState` component
- `ScreenHeader` component
- Shared theme constants (colors, spacing, typography)

**Finding X4 (MEDIUM): No BLE sensor architecture**

Phase 2 adds BLE sensors (HR, power, cadence). The architecture should plan for this now:
- `SensorService` abstraction with pluggable providers
- Connection state management (scanning, connecting, connected, disconnected, reconnecting)
- Data stream that feeds into both live display and SQLite storage
- This is a significant subsystem. Architect it before Phase 2 starts.

**Finding X5 (GOOD): TypeScript strict mode enabled**

`tsconfig.json` has `"strict": true`. This is correct and should not be relaxed.

---

## 9. Comparison to Standards

### vs Production Cycling Apps (Strava, Wahoo)

| Capability | Strava iOS | Wahoo ELEMNT | BoulderRoller Scaffold |
|---|---|---|---|
| GPS recording | Full (CoreLocation native) | Full (hardware + phone) | Placeholder only |
| Background recording | Robust (years of iteration) | Robust | Not implemented |
| BLE sensors | HR, power, cadence, speed | Full (proprietary + standard) | Not implemented |
| Offline support | Full recording, queued upload | Full | Not implemented |
| Crash recovery | Seamless (CoreData journal) | Hardware handles it | Not implemented |
| Auth | Email/Google/Apple + OAuth | Wahoo account | Privy placeholder |
| Error handling | Graceful degradation | Hardware status LEDs | Silent swallow |
| Testing | Extensive (internal CI) | Hardware + software CI | Zero tests |
| Certificate pinning | Yes | Yes | No |
| Biometric auth | No (not financial) | No | No (but should -- financial app) |

**Gap:** The scaffold is roughly 95% away from parity with production cycling apps on recording, and roughly 80% away on the data display side.

### What a Solana Foundation Technical Reviewer Would Flag

1. **No on-chain integration implemented.** The scaffold imports `@solana/web3.js` and `@solana-mobile/mobile-wallet-adapter-protocol` but never uses them. A grant reviewer wants to see at least one working on-chain interaction (even read-only, like fetching vault state from devnet).

2. **No transaction signing flow.** The entire point of the mobile app from a Solana perspective is mobile-native transaction signing. This is completely absent.

3. **Privy not configured.** The `REPLACE_WITH_PRIVY_APP_ID` placeholder means the reviewer cannot test auth at all.

4. **No dApp Store readiness.** Solana dApp Store listing requires MWA integration, which exists in `package.json` but is not wired.

### What Apple App Store Review Would Reject

1. **Placeholder screens.** RecordScreen says "Coming in Phase 1" -- Apple rejects apps with non-functional core features.

2. **No login flow.** There is no way to actually authenticate. The Profile screen shows "Not signed in" with no login button.

3. **Location permission without implementation.** `app.json` requests Always location permission but no code uses it. Apple will reject for requesting unnecessary permissions.

4. **No privacy policy or terms of service.** Required for any app that collects user data.

5. **Crypto/token references.** If "points," "vaults," or "staking" language appears without careful framing, Apple may flag as crypto and require additional review. Follow Coinbase/Phantom precedent: describe as "cycling rewards" not "tokens."

---

## 10. Production Checklist

### Phase 0: Fix Now (Scaffold Phase) -- Before Writing Feature Code

These are architectural decisions that become exponentially more expensive to change later.

| # | Item | Effort | Priority |
|---|---|---|---|
| P0-1 | Add Zustand for auth + settings state | 0.5 day | CRITICAL |
| P0-2 | Add TanStack Query for server state | 0.5 day | CRITICAL |
| P0-3 | Wire `expo-secure-store` for token persistence | 0.5 day | CRITICAL |
| P0-4 | Add token refresh flow in API client | 1 day | CRITICAL |
| P0-5 | Add Sentry crash reporting | 0.5 day | CRITICAL |
| P0-6 | Add global ErrorBoundary component | 0.5 day | HIGH |
| P0-7 | Add Jest + RNTL + MSW test infrastructure | 1 day | HIGH |
| P0-8 | Create shared component library (Card, EmptyState, StatRow, theme) | 1 day | HIGH |
| P0-9 | Add `app.config.js` for env-based config (replace `app.json`) | 0.5 day | HIGH |
| P0-10 | Add `eas.json` with dev/preview/production profiles | 0.5 day | MEDIUM |
| P0-11 | Write API client tests as reference pattern | 0.5 day | MEDIUM |
| P0-12 | Add react-native-reanimated for animations | 0.5 day | MEDIUM |
| P0-13 | Replace text tab icons with @expo/vector-icons | 0.25 day | LOW |

**Total Phase 0: ~7.5 days (1.5 weeks)**

### Phase 1: Must Have Before Alpha Users

| # | Item | Effort | Priority |
|---|---|---|---|
| P1-1 | Implement Privy auth flow (login screen, social login, wallet connect) | 3 days | CRITICAL |
| P1-2 | GPS recording service with SQLite persistence | 5 days | CRITICAL |
| P1-3 | Crash recovery for interrupted rides | 2 days | CRITICAL |
| P1-4 | Upload queue with retry and idempotency | 2 days | CRITICAL |
| P1-5 | GPS sample validation (impossible speed, null island, sentinels) | 1 day | CRITICAL |
| P1-6 | Certificate pinning for API calls | 0.5 day | HIGH |
| P1-7 | Screen-level error states (not empty catch blocks) | 1 day | HIGH |
| P1-8 | Reactive auth state (auto-redirect on logout/expiry) | 1 day | HIGH |
| P1-9 | Recording screen with start/pause/stop/map | 5 days | HIGH |
| P1-10 | Post-ride summary screen | 2 days | HIGH |
| P1-11 | Background location handling (iOS + Android) | 3 days | HIGH |
| P1-12 | Unit + integration tests for recording + upload | 3 days | HIGH |
| P1-13 | Upload payload HMAC signing | 1 day | MEDIUM |
| P1-14 | Biometric auth for staking/financial operations | 1 day | MEDIUM |

**Total Phase 1: ~30.5 days (~6 weeks)**

### Phase 2: Must Have Before App Store Submission

| # | Item | Effort |
|---|---|---|
| P2-1 | E2E test suite (Detox or Maestro) | 3 days |
| P2-2 | Privacy policy + terms of service screens | 1 day |
| P2-3 | Apple/Google code signing + provisioning | 1 day |
| P2-4 | EAS Build CI pipeline (GitHub Actions) | 1 day |
| P2-5 | App Store screenshots + metadata | 1 day |
| P2-6 | Remove all placeholder/coming soon screens | 1 day |
| P2-7 | Accessibility audit (VoiceOver, TalkBack) | 2 days |
| P2-8 | Device attestation (DeviceCheck / Play Integrity) | 2 days |
| P2-9 | Deep linking setup (ride share links, push notification routing) | 1 day |
| P2-10 | Analytics (anonymous, GDPR-compliant) | 1 day |

### Phase 3: Should Have Before Public Launch

| # | Item | Effort |
|---|---|---|
| P3-1 | BLE sensor integration (HR, power, cadence) | 5 days |
| P3-2 | On-chain transaction signing UI (vault completions) | 3 days |
| P3-3 | Push notification infrastructure | 2 days |
| P3-4 | Strava push integration (GPX export) | 2 days |
| P3-5 | Performance profiling on 4+ hour recording | 2 days |
| P3-6 | OTA update strategy (EAS Update) | 1 day |
| P3-7 | Rate limiting + abuse detection client-side | 1 day |

---

## 11. Specific Library Recommendations

| Purpose | Library | Rationale |
|---|---|---|
| Server state | `@tanstack/react-query` | Used in portal, proven pattern, offline persistence via `persistQueryClient` |
| Local state | `zustand` | Minimal API, no boilerplate, works great with RN, supports persist middleware |
| Token storage | `expo-secure-store` | Already in package.json, uses iOS Keychain / Android Keystore |
| Crash reporting | `@sentry/react-native` | Free tier sufficient, source maps, breadcrumbs, performance monitoring |
| GPS recording | `react-native-background-geolocation` (Transistor Software) | Battle-tested across 50K+ sessions, handles iOS/Android background correctly |
| BLE sensors | `react-native-ble-plx` | Most mature RN BLE library, supports cycling power/HR/cadence profiles |
| Local DB | `expo-sqlite` | Already in Expo, sufficient for ride storage, WAL mode for crash safety |
| Maps | `react-native-maps` | Standard, Google Maps on Android, Apple Maps on iOS |
| Animations | `react-native-reanimated` | Required for smooth ride recording UI, post-ride reveal animations |
| Icons | `@expo/vector-icons` | Bundled with Expo, includes Ionicons/MaterialIcons/Feather |
| Certificate pinning | `react-native-ssl-pinning` or custom fetch wrapper | MITM protection for API calls |
| Biometric | `expo-local-authentication` | Face ID, Touch ID, fingerprint gating |
| E2E testing | `maestro` | Simpler setup than Detox, good for RN, declarative YAML flows |
| API mocking (tests) | `msw` (Mock Service Worker) | Intercepts fetch at network level, works in Jest + RN |

---

## 12. Language Spec Compliance

The `LANGUAGE_SPEC.md` defines specific terminology rules. The scaffold has some violations:

| Found in scaffold | Should be (per Language Spec) | File |
|---|---|---|
| "Stakers" (VaultsScreen stat label) | Acceptable as concept word | VaultsScreen.tsx line 61 |
| "Sign in" / "Sign Out" | Acceptable | HomeScreen.tsx, ProfileScreen.tsx |
| "Points" | Correct for points period | ProfileScreen.tsx |

**Verdict:** The scaffold is broadly compliant. When vault detail screens are added, ensure CTAs say "Deposit CAL" not "Stake," and "Collect rewards" not "Harvest."

---

## 13. Summary of Findings by Severity

### CRITICAL (must fix before any user)

1. **S1:** Auth tokens stored in memory only -- lost on app restart
2. **S5:** No GPS data integrity validation (when recording is built)
3. **D1:** No crash recovery design for interrupted rides
4. **D2:** No upload idempotency
5. **T1:** Zero test infrastructure
6. **E1:** All errors silently swallowed
7. **E2:** No crash reporting

### HIGH (must fix before alpha)

1. **S2:** No certificate pinning
2. **S3:** No biometric auth for financial operations
3. **S4:** Privy wallet key material protection unverified
4. **D3:** No upload retry queue
5. **D4:** Device clock spoofing unaddressed
6. **E3:** No global error boundary
7. **E4:** 401 handling does not redirect to login
8. **P1:** No background task management for recording
9. **P2:** Memory management plan needed for long rides

### MEDIUM (fix before App Store submission)

1. **S6:** No environment separation for secrets
2. **P3:** Bundle size monitoring needed
3. **X3:** No shared component library (code duplication)
4. **X4:** No BLE sensor architecture planned
5. **C1-C3:** No CI/CD pipeline

### LOW (fix before public launch)

1. **P4:** No MapView lazy loading
2. Tab icons are text characters, not proper icons
3. No accessibility attributes on interactive elements
4. No analytics

---

## 14. Final Assessment

**Is this scaffold production-ready?** No. It is a correctly-structured starting point for a React Native Expo project with reasonable technology choices, but it contains zero production infrastructure.

**Is the architecture salvageable?** Yes. The scaffold makes no irreversible mistakes. The navigation structure, API client shape, and screen organization are all reasonable starting points. The architectural gaps (state management, security, testing) are additive -- they can be layered on without rewriting what exists.

**What is the most efficient path to production?** Execute Phase 0 (1.5 weeks) immediately to establish architecture patterns, then execute Phase 1 (6 weeks) as described in the strategy document. A senior React Native developer with GPS/fitness app experience should lead. The Phase 0 investment pays for itself many times over by preventing architectural debt during feature development.

**Bottom line:** This is a scaffold, not an app. The distance to production is significant but well-understood. The strategy document (`NATIVE_MOBILE_APP_STRATEGY.md`) is excellent and covers most of what needs to be built. The scaffold simply has not started building it yet.
