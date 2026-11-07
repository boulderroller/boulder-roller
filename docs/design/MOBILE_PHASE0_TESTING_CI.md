# Mobile Phase 0: Testing, Error Handling, and CI/CD Implementation Spec

**Date:** 2026-03-28
**Status:** Implementation spec for dev agents
**Prerequisite:** Read `MOBILE_ARCHITECTURE_REVIEW.md` for context on findings T1, E1-E4, C1-C3
**Scope:** Testing infrastructure, error handling, crash reporting, CI/CD, production monitoring

---

## Table of Contents

1. [Test Infrastructure](#1-test-infrastructure)
2. [Error Handling Strategy](#2-error-handling-strategy)
3. [Crash Reporting (Sentry)](#3-crash-reporting-sentry)
4. [CI/CD Pipeline](#4-cicd-pipeline)
5. [Production Monitoring](#5-production-monitoring)
6. [Dependency Summary](#6-dependency-summary)
7. [File Manifest](#7-file-manifest)

---

## 1. Test Infrastructure

### 1.1 Dependencies to Install

```bash
cd mobile

# Test runner + Expo preset
npx expo install -- --save-dev jest-expo

# React Native Testing Library
npm install --save-dev @testing-library/react-native@^12.9.0 @testing-library/jest-native@^5.4.3

# MSW for API mocking (v2 — ESM-first, works with RN)
npm install --save-dev msw@^2.7.0

# Jest types
npm install --save-dev @types/jest@^29.5.0
```

Final `devDependencies` addition:
```json
{
  "devDependencies": {
    "@testing-library/jest-native": "^5.4.3",
    "@testing-library/react-native": "^12.9.0",
    "@types/jest": "^29.5.0",
    "@types/react": "~18.3.0",
    "jest-expo": "~52.0.0",
    "msw": "^2.7.0",
    "typescript": "~5.3.0"
  }
}
```

**Note on `jest-expo` version:** Must match the Expo SDK major version (`~52.0.0` for SDK 52). The `npx expo install` command handles this automatically.

### 1.2 Jest Configuration

Add to `mobile/package.json`:

```json
{
  "scripts": {
    "start": "expo start",
    "android": "expo run:android",
    "ios": "expo run:ios",
    "lint": "expo lint",
    "prebuild": "expo prebuild",
    "test": "jest",
    "test:watch": "jest --watch",
    "test:coverage": "jest --coverage"
  },
  "jest": {
    "preset": "jest-expo",
    "transformIgnorePatterns": [
      "node_modules/(?!((jest-)?react-native|@react-native(-community)?)|expo(nent)?|@expo(nent)?/.*|@expo-google-fonts/.*|react-navigation|@react-navigation/.*|@solana/web3.js|@solana-mobile/.*|@privy-io/.*|react-native-safe-area-context|react-native-screens)"
    ],
    "setupFilesAfterSetup": [
      "@testing-library/jest-native/extend-expect"
    ],
    "moduleNameMapper": {
      "^@/(.*)$": "<rootDir>/src/$1"
    },
    "collectCoverageFrom": [
      "src/**/*.{ts,tsx}",
      "!src/**/*.d.ts",
      "!src/**/types.ts"
    ],
    "coverageThresholds": {
      "global": {
        "branches": 40,
        "functions": 40,
        "lines": 50,
        "statements": 50
      }
    }
  }
}
```

### 1.3 Setup File

Create `mobile/jest.setup.ts`:

```typescript
// Jest setup — runs before each test suite

// Silence the React Native warning noise in test output
jest.mock('react-native/Libraries/Animated/NativeAnimatedHelper');

// Mock expo-secure-store (used by auth token persistence)
jest.mock('expo-secure-store', () => ({
  getItemAsync: jest.fn().mockResolvedValue(null),
  setItemAsync: jest.fn().mockResolvedValue(undefined),
  deleteItemAsync: jest.fn().mockResolvedValue(undefined),
}));

// Mock expo-constants
jest.mock('expo-constants', () => ({
  default: {
    expoConfig: {
      extra: {
        apiUrl: 'http://localhost:8080',
        sentryDsn: '',
      },
    },
  },
}));

// Mock @react-navigation/native
jest.mock('@react-navigation/native', () => {
  const actual = jest.requireActual('@react-navigation/native');
  return {
    ...actual,
    useNavigation: () => ({
      navigate: jest.fn(),
      goBack: jest.fn(),
      reset: jest.fn(),
    }),
    useRoute: () => ({
      params: {},
    }),
  };
});
```

Reference this in the jest config:
```json
{
  "jest": {
    "setupFilesAfterSetup": [
      "@testing-library/jest-native/extend-expect",
      "./jest.setup.ts"
    ]
  }
}
```

### 1.4 MSW Server Setup

Create `mobile/src/__tests__/mocks/server.ts`:

```typescript
import { setupServer } from 'msw/node';
import { handlers } from './handlers';

export const server = setupServer(...handlers);
```

Create `mobile/src/__tests__/mocks/handlers.ts`:

```typescript
import { http, HttpResponse } from 'msw';

const API_URL = 'http://localhost:8080';

// Default happy-path handlers — override per test as needed
export const handlers = [
  // Health
  http.get(`${API_URL}/health`, () => {
    return HttpResponse.json({ status: 'ok' });
  }),

  // Auth
  http.post(`${API_URL}/auth/privy/verify`, () => {
    return HttpResponse.json({
      access_token: 'test-access-token',
      refresh_token: 'test-refresh-token',
      expires_in: 3600,
    });
  }),

  http.post(`${API_URL}/auth/nonce`, () => {
    return HttpResponse.json({ nonce: 'test-nonce-123' });
  }),

  http.post(`${API_URL}/auth/logout`, () => {
    return new HttpResponse(null, { status: 204 });
  }),

  // User
  http.get(`${API_URL}/users/me`, () => {
    return HttpResponse.json({
      wallet: '3boUdoRSqJKMn1sNFMoc8WLDFjzZELQEMQabV2hVnsWu',
      display_name: 'TestRider',
      bio: null,
      avatar_url: null,
      created_at: '2026-01-01T00:00:00Z',
      total_points: 12500,
      total_rides: 42,
      total_tss: 8400,
      level: 3,
    });
  }),

  // Points
  http.get(`${API_URL}/points/balance`, () => {
    return HttpResponse.json({
      total_points: 12500,
      points_from_tss: 8400,
      points_from_creation: 1000,
      points_from_referral: 500,
      points_from_leaderboard: 2600,
      points_from_staking: 0,
    });
  }),

  // Rides
  http.get(`${API_URL}/rides`, () => {
    return HttpResponse.json([
      {
        id: 'ride-001',
        activity_id: 'act-001',
        started_at: '2026-03-27T14:30:00Z',
        duration_sec: 3600,
        distance_m: 42000,
        elevation_gain_m: 650,
        tss: 120,
        np: 220,
        avg_power_w: 195,
        source: 'native',
      },
    ]);
  }),

  // Vaults
  http.get(`${API_URL}/vaults`, () => {
    return HttpResponse.json([
      {
        signature_hex: 'ab'.repeat(64),
        name: 'Manayunk Wall',
        vert_m: 85,
        distance_m: 950,
        avg_gradient_pct: 8.9,
        total_staked: 5000,
        staker_count: 12,
        kom_holder: '3boUdoRSqJKMn1sNFMoc8WLDFjzZELQEMQabV2hVnsWu',
        kom_time_s: 142,
      },
    ]);
  }),
];
```

### 1.5 What to Test First (Priority Order)

Tests are ordered by economic criticality — ride data = money in this system.

#### Tier 1: Before any more code is written (Phase 0)

| Test file | What it covers | Why critical |
|-----------|---------------|-------------|
| `src/lib/__tests__/api.test.ts` | API client: request construction, auth header injection, case conversion, error classification, 401 handling, token lifecycle | This is the single conduit for all server communication. Every bug here affects every feature. |
| `src/lib/__tests__/api-errors.test.ts` | Network errors, server 500, malformed JSON, timeout behavior, retryable classification | Empty catch blocks are the #1 finding. These tests enforce that errors propagate correctly. |

#### Tier 2: With Phase 1 feature code

| Test file | What it covers | Why critical |
|-----------|---------------|-------------|
| `src/stores/__tests__/auth-store.test.ts` | Zustand auth store: login, logout, token refresh, secure store persistence, reactive state changes | Auth state drives the entire app. A bug here logs users out or shows stale authenticated UI. |
| `src/services/__tests__/upload-queue.test.ts` | Queue processing: enqueue, retry with backoff, success removes from queue, idempotency key, persistent across restart | Upload failures = lost rides = lost economic value. |
| `src/services/__tests__/recording-service.test.ts` | GPS sample collection, SQLite batch write, pause/resume, crash recovery (status='recording' on relaunch) | Recording is the economic truth engine. A bug here corrupts token distributions. |
| `src/screens/__tests__/HomeScreen.test.tsx` | Renders ride list, empty state, unauthenticated state, pull-to-refresh, error state display | Reference pattern for all screen tests. |
| `src/screens/__tests__/ProfileScreen.test.tsx` | Profile data display, points display, logout flow, loading states | Exercises the auth + data fetch pattern. |

#### Tier 3: Before App Store submission

| Test file | What it covers |
|-----------|---------------|
| `src/screens/__tests__/RecordScreen.test.tsx` | Start/pause/stop controls, live metric display, GPS permission handling |
| `src/screens/__tests__/VaultsScreen.test.tsx` | Vault list rendering, staking interaction, error states |
| `src/components/__tests__/ErrorBoundary.test.tsx` | Catches render errors, displays recovery UI, reports to Sentry |
| `src/lib/__tests__/validators.test.ts` | GPS sample validation (impossible speed, null island, sentinels) |

### 1.6 Test Patterns for React Native

#### Mocking Native Modules

Native modules that need mocks in `jest.setup.ts` (add as needed):

```typescript
// expo-location (Phase 1)
jest.mock('expo-location', () => ({
  requestForegroundPermissionsAsync: jest.fn().mockResolvedValue({ status: 'granted' }),
  requestBackgroundPermissionsAsync: jest.fn().mockResolvedValue({ status: 'granted' }),
  getCurrentPositionAsync: jest.fn().mockResolvedValue({
    coords: { latitude: 39.9526, longitude: -75.1652, altitude: 15, accuracy: 5 },
    timestamp: Date.now(),
  }),
  watchPositionAsync: jest.fn().mockReturnValue({ remove: jest.fn() }),
  startLocationUpdatesAsync: jest.fn().mockResolvedValue(undefined),
  stopLocationUpdatesAsync: jest.fn().mockResolvedValue(undefined),
  Accuracy: { High: 4, BestForNavigation: 6 },
}));

// expo-sqlite (Phase 1)
jest.mock('expo-sqlite', () => ({
  openDatabaseAsync: jest.fn().mockResolvedValue({
    execAsync: jest.fn().mockResolvedValue(undefined),
    runAsync: jest.fn().mockResolvedValue({ lastInsertRowId: 1, changes: 1 }),
    getFirstAsync: jest.fn().mockResolvedValue(null),
    getAllAsync: jest.fn().mockResolvedValue([]),
  }),
}));

// @react-native-async-storage/async-storage
jest.mock('@react-native-async-storage/async-storage', () =>
  require('@react-native-async-storage/async-storage/jest/async-storage-mock')
);
```

#### Testing Async Data Fetching (Screen Pattern)

```typescript
// Example: HomeScreen.test.tsx
import { render, screen, waitFor } from '@testing-library/react-native';
import { NavigationContainer } from '@react-navigation/native';
import { server } from '../mocks/server';
import { http, HttpResponse } from 'msw';
import HomeScreen from '../../screens/HomeScreen';

// Wrap screens in NavigationContainer for testing
function renderWithNav(component: React.ReactElement) {
  return render(
    <NavigationContainer>{component}</NavigationContainer>
  );
}

beforeAll(() => server.listen());
afterEach(() => server.resetHandlers());
afterAll(() => server.close());

test('shows ride list when authenticated', async () => {
  // MSW handlers return default data (see handlers.ts)
  renderWithNav(<HomeScreen />);
  await waitFor(() => {
    expect(screen.getByText('42.0 km')).toBeTruthy();
  });
});

test('shows empty state when not authenticated', async () => {
  renderWithNav(<HomeScreen />);
  await waitFor(() => {
    expect(screen.getByText('Welcome to BoulderRoller')).toBeTruthy();
  });
});

test('shows error banner on network failure', async () => {
  server.use(
    http.get('http://localhost:8080/rides', () => {
      return HttpResponse.error();
    }),
  );
  renderWithNav(<HomeScreen />);
  await waitFor(() => {
    expect(screen.getByText(/unable to load/i)).toBeTruthy();
  });
});
```

#### Testing Zustand Stores

```typescript
// Zustand stores are plain JS — test without React rendering
import { useAuthStore } from '../../stores/auth-store';
import * as SecureStore from 'expo-secure-store';

beforeEach(() => {
  useAuthStore.getState().reset(); // Add a reset action for tests
  jest.clearAllMocks();
});

test('login persists tokens to secure store', async () => {
  await useAuthStore.getState().login({
    accessToken: 'at-123',
    refreshToken: 'rt-456',
    expiresIn: 3600,
  });

  expect(SecureStore.setItemAsync).toHaveBeenCalledWith(
    'br_access_token', 'at-123'
  );
  expect(useAuthStore.getState().isAuthenticated).toBe(true);
});

test('401 response clears auth state', async () => {
  // Set up authenticated state
  useAuthStore.setState({ isAuthenticated: true, accessToken: 'old-token' });

  // Trigger 401 handler
  await useAuthStore.getState().handleSessionExpired();

  expect(useAuthStore.getState().isAuthenticated).toBe(false);
  expect(SecureStore.deleteItemAsync).toHaveBeenCalledWith('br_access_token');
});
```

### 1.7 Coverage Targets

| Milestone | Lines | Branches | Functions | Rationale |
|-----------|-------|----------|-----------|-----------|
| Phase 0 complete | 50% | 40% | 40% | Covers API client, stores, utilities |
| Phase 1 complete (alpha users) | 65% | 50% | 55% | Adds recording, upload, auth flow coverage |
| App Store submission | 75% | 60% | 65% | Full screen coverage, error paths |

These are achievable targets. Do not aim for 90%+ on a React Native app — native module boundaries, navigation integration, and animation code have diminishing returns above 75%.

**Minimum test count before v1 launch:** 80-100 tests across unit, component, and integration layers.

### 1.8 E2E Testing: Maestro (Phase 2, not Phase 0)

**Decision: Use Maestro, skip Detox.**

Rationale:
- Detox requires native build toolchain setup, is brittle with Expo managed workflow, and has a steep learning curve
- Maestro uses declarative YAML flows, works with any running app (simulator or device), and has a free cloud CI tier
- Maestro is better suited to a small team that needs E2E confidence without a dedicated QA engineer

**When to add:** After Phase 1 recording is functional. E2E tests on placeholder screens have no value.

**What to cover with Maestro (4-6 flows):**
1. Login via social auth -> see profile
2. Navigate to ride list -> pull to refresh
3. Start recording -> see GPS status -> stop -> see upload progress
4. View vault -> see leaderboard
5. Logout -> redirected to login screen
6. Offline: start recording -> airplane mode -> stop -> queued for upload

Maestro config file: `mobile/.maestro/config.yaml`
```yaml
# Installed via: curl -Ls "https://get.maestro.mobile.dev" | bash
# Run: maestro test .maestro/flows/
```

Example flow (`mobile/.maestro/flows/login-and-profile.yaml`):
```yaml
appId: com.boulderroller.app
---
- launchApp
- tapOn: "Sign In"
- tapOn: "Continue with Google"
# Maestro handles Google OAuth via device account
- assertVisible: "Profile"
- assertVisible: "Total Points"
```

**Do not implement Maestro in Phase 0.** Just reserve the directory structure.

---

## 2. Error Handling Strategy

### 2.1 Error Classification

Every error in the app falls into one of four categories. This classification determines what the user sees and what the system does.

| Classification | User sees | System does | Example |
|----------------|-----------|-------------|---------|
| **TRANSIENT** | Toast/banner: "Connection issue, retrying..." | Auto-retry with backoff. Log to Sentry breadcrumb. | Network timeout, 502, 503 |
| **RECOVERABLE** | Inline error state with "Retry" button | Log to Sentry breadcrumb. No auto-retry. | 400 bad request, empty response, parse failure |
| **AUTH** | Redirect to login screen | Clear tokens, navigate to auth root. Sentry breadcrumb. | 401, 403, token refresh failure |
| **FATAL** | Full-screen error boundary: "Something went wrong. Restart the app." | Report to Sentry as exception (not breadcrumb). Include component stack. | Unhandled JS exception, render error, SQLite corruption |

### 2.2 Replace Empty Catch Blocks

**Current pattern (every screen):**
```typescript
// BAD — errors silently swallowed
try {
  const data = await api.getRides(20, 0);
  setRides(data);
} catch {
  // Silently fail
}
```

**Replacement pattern:**
```typescript
// GOOD — errors classified and surfaced
const [error, setError] = useState<ApiError | null>(null);

const fetchRides = async () => {
  setError(null);
  try {
    if (!authStore.isAuthenticated) return;
    const data = await api.getRides(20, 0);
    setRides(data);
  } catch (err) {
    if (err instanceof ApiError) {
      if (err.type === 'session_expired') {
        authStore.handleSessionExpired(); // Reactive redirect
        return;
      }
      setError(err);
    } else {
      setError(new ApiError('Unexpected error', 'unknown'));
      Sentry.captureException(err);
    }
  } finally {
    setLoading(false);
    setRefreshing(false);
  }
};

// In render:
{error && (
  <ErrorBanner
    message={error.retryable ? 'Connection issue' : 'Unable to load rides'}
    onRetry={error.retryable ? fetchRides : undefined}
  />
)}
```

When TanStack Query is wired (P0-2), this pattern simplifies significantly — TanStack Query handles loading/error/retry state internally. The explicit `try/catch` pattern above is the interim solution for Phase 0 and remains useful for non-query operations (logout, form submissions, transaction signing).

### 2.3 Global Error Boundary

Create `mobile/src/components/ErrorBoundary.tsx`:

```typescript
import React, { Component, ErrorInfo, ReactNode } from 'react';
import { View, Text, TouchableOpacity, StyleSheet } from 'react-native';
import * as Sentry from '@sentry/react-native';

interface Props {
  children: ReactNode;
  fallback?: ReactNode;
}

interface State {
  hasError: boolean;
  error: Error | null;
}

export class ErrorBoundary extends Component<Props, State> {
  constructor(props: Props) {
    super(props);
    this.state = { hasError: false, error: null };
  }

  static getDerivedStateFromError(error: Error): State {
    return { hasError: true, error };
  }

  componentDidCatch(error: Error, errorInfo: ErrorInfo) {
    Sentry.captureException(error, {
      contexts: {
        react: { componentStack: errorInfo.componentStack },
      },
    });
  }

  handleReset = () => {
    this.setState({ hasError: false, error: null });
  };

  render() {
    if (this.state.hasError) {
      if (this.props.fallback) return this.props.fallback;

      return (
        <View style={styles.container}>
          <Text style={styles.title}>Something went wrong</Text>
          <Text style={styles.message}>
            The app encountered an unexpected error. Tap below to try again.
          </Text>
          <TouchableOpacity style={styles.button} onPress={this.handleReset}>
            <Text style={styles.buttonText}>Restart</Text>
          </TouchableOpacity>
        </View>
      );
    }

    return this.props.children;
  }
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
    backgroundColor: '#0a0a0a',
    justifyContent: 'center',
    alignItems: 'center',
    paddingHorizontal: 40,
  },
  title: {
    fontSize: 20,
    fontWeight: '700',
    color: '#e5e5e5',
    marginBottom: 12,
  },
  message: {
    fontSize: 14,
    color: '#888',
    textAlign: 'center',
    lineHeight: 20,
    marginBottom: 24,
  },
  button: {
    backgroundColor: '#1a1a1a',
    borderRadius: 12,
    paddingVertical: 14,
    paddingHorizontal: 32,
    borderWidth: 1,
    borderColor: '#333',
  },
  buttonText: {
    fontSize: 15,
    fontWeight: '600',
    color: '#e5e5e5',
  },
});
```

**Wire into App.tsx:** Wrap after `PrivyWrapper`, before `NavigationContainer`:

```typescript
export default function App() {
  return (
    <SafeAreaProvider>
      <PrivyWrapper>
        <ErrorBoundary>
          <NavigationContainer theme={navigationTheme}>
            <StatusBar style="light" />
            <TabNavigator />
          </NavigationContainer>
        </ErrorBoundary>
      </PrivyWrapper>
    </SafeAreaProvider>
  );
}
```

### 2.4 Error Banner Component

Create `mobile/src/components/ErrorBanner.tsx`:

```typescript
import React from 'react';
import { View, Text, TouchableOpacity, StyleSheet } from 'react-native';

interface ErrorBannerProps {
  message: string;
  onRetry?: () => void;
  onDismiss?: () => void;
}

export function ErrorBanner({ message, onRetry, onDismiss }: ErrorBannerProps) {
  return (
    <View style={styles.container}>
      <Text style={styles.message}>{message}</Text>
      <View style={styles.actions}>
        {onRetry && (
          <TouchableOpacity onPress={onRetry}>
            <Text style={styles.retryText}>Retry</Text>
          </TouchableOpacity>
        )}
        {onDismiss && (
          <TouchableOpacity onPress={onDismiss}>
            <Text style={styles.dismissText}>Dismiss</Text>
          </TouchableOpacity>
        )}
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  container: {
    backgroundColor: '#2a1a1a',
    borderRadius: 8,
    padding: 12,
    marginHorizontal: 16,
    marginBottom: 12,
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    borderWidth: 1,
    borderColor: '#442222',
  },
  message: {
    fontSize: 13,
    color: '#cc8888',
    flex: 1,
  },
  actions: {
    flexDirection: 'row',
    gap: 12,
    marginLeft: 12,
  },
  retryText: {
    fontSize: 13,
    fontWeight: '600',
    color: '#e5e5e5',
  },
  dismissText: {
    fontSize: 13,
    color: '#666',
  },
});
```

### 2.5 Network Error Handling

**Offline detection:** Use `@react-native-community/netinfo` (add to dependencies).

```typescript
// In a useNetworkStatus hook:
import NetInfo from '@react-native-community/netinfo';

export function useNetworkStatus() {
  const [isConnected, setIsConnected] = useState(true);

  useEffect(() => {
    const unsubscribe = NetInfo.addEventListener(state => {
      setIsConnected(state.isConnected ?? true);
    });
    return unsubscribe;
  }, []);

  return { isConnected };
}
```

When `isConnected === false`:
- Show a persistent top banner: "No internet connection"
- Queue all write operations (uploads, profile updates, staking)
- Allow read from TanStack Query cache (stale data is better than no data)
- When connection returns: flush write queue, refetch stale queries

### 2.6 Transaction Signing Errors

When a Solana transaction fails, the user should see context-appropriate messaging:

| Solana error | User sees | Action |
|-------------|-----------|--------|
| Insufficient SOL for fee | "Not enough SOL for transaction fees. You need ~0.005 SOL." | Link to SOL faucet (devnet) or funding guide |
| Transaction simulation failed | "Transaction could not be processed. Please try again." | Retry button. Log full error to Sentry. |
| User rejected signing (MWA) | "Transaction cancelled." | Dismiss. No Sentry report (user action). |
| Timeout / blockhash expired | "Transaction timed out. No funds were moved." | Reassure user nothing happened. Retry button. |
| Program error (custom code) | "Operation failed. Error code: {code}" | Log to Sentry with program logs. Retry button. |

**Key principle:** Always tell the user whether funds were affected. "Nothing happened" or "Your funds are safe" is more important than the technical error.

### 2.7 Ride Recording Errors

| Scenario | Detection | User sees | System does |
|----------|----------|-----------|-------------|
| GPS signal lost (>30s no fix) | Location callback not firing | Yellow banner: "GPS signal weak" | Continue recording with last known position. Mark gap in sample data. |
| GPS accuracy degraded (>50m) | `coords.accuracy > 50` | Yellow banner: "GPS accuracy low" | Continue recording. Samples flagged `low_accuracy=true`. |
| BLE sensor disconnected | BLE disconnect event | Toast: "Power meter disconnected" | Continue recording without sensor data. Auto-reconnect in background. |
| Storage full | SQLite write fails with SQLITE_FULL | Red banner: "Storage full. Ride saved up to this point." | Force-stop recording. Save what we have. Do NOT discard. |
| App backgrounded (iOS) | `AppState` change to `background` | Nothing (recording continues in background) | Switch to background location mode. Reduce sample rate to 1Hz. |
| App killed by OS | Process termination | On relaunch: "You have an unfinished ride. Resume or save?" | Detect `status='recording'` in SQLite on launch. Offer resume or save-partial. |

### 2.8 Error Handling Decision Tree

```
Error occurs
  |
  +-- Is it a render error (caught by ErrorBoundary)?
  |     YES -> Show restart screen. Report to Sentry as exception.
  |
  +-- Is it an ApiError?
  |     |
  |     +-- type === 'session_expired'
  |     |     -> Clear tokens. Navigate to login. Sentry breadcrumb.
  |     |
  |     +-- type === 'network_error'
  |     |     -> Show "Connection issue" banner. Auto-retry if online.
  |     |
  |     +-- type === 'server_error' (5xx)
  |     |     -> Show "Service unavailable" banner. Retry button.
  |     |
  |     +-- Other (4xx, parse error)
  |           -> Show inline error. Retry button if retryable.
  |
  +-- Is it a transaction error (Solana)?
  |     -> Show transaction-specific message (see 2.6). Always state fund safety.
  |
  +-- Is it a recording error?
  |     -> Never stop recording silently. Degrade gracefully (see 2.7).
  |
  +-- Unknown error
        -> Sentry.captureException(). Show generic "Something went wrong."
```

---

## 3. Crash Reporting (Sentry)

### 3.1 Setup

```bash
npx expo install @sentry/react-native
```

This installs the Expo-compatible version. As of SDK 52, `@sentry/react-native` version `~6.5.0` is the compatible range.

Add to `app.json` plugins array:

```json
{
  "expo": {
    "plugins": [
      "expo-secure-store",
      [
        "@sentry/react-native/expo",
        {
          "organization": "boulderroller",
          "project": "mobile",
          "url": "https://sentry.io/"
        }
      ]
    ]
  }
}
```

### 3.2 Sentry Initialization

Create `mobile/src/lib/sentry.ts`:

```typescript
import * as Sentry from '@sentry/react-native';
import Constants from 'expo-constants';
import { APP_VERSION } from '../constants/config';

const SENTRY_DSN = Constants.expoConfig?.extra?.sentryDsn ?? '';

export function initSentry() {
  if (!SENTRY_DSN) {
    console.warn('[Sentry] No DSN configured — crash reporting disabled');
    return;
  }

  Sentry.init({
    dsn: SENTRY_DSN,
    release: `com.boulderroller.app@${APP_VERSION}`,
    dist: Constants.expoConfig?.extra?.buildNumber ?? '1',
    environment: __DEV__ ? 'development' : 'production',

    // Performance monitoring
    tracesSampleRate: __DEV__ ? 1.0 : 0.2, // 20% of transactions in production
    profilesSampleRate: __DEV__ ? 1.0 : 0.1, // 10% of profiled transactions

    // Don't send in development by default (toggle with env var for testing)
    enabled: !__DEV__,

    // Breadcrumbs
    enableAutoSessionTracking: true,
    sessionTrackingIntervalMillis: 30_000,

    // Before send: scrub wallet addresses from error messages
    beforeSend(event) {
      if (event.message) {
        // Redact full Solana addresses (base58, 32-44 chars)
        event.message = event.message.replace(
          /[1-9A-HJ-NP-Za-km-z]{32,44}/g,
          '[WALLET]'
        );
      }
      return event;
    },

    // Before breadcrumb: redact auth tokens from network breadcrumbs
    beforeBreadcrumb(breadcrumb) {
      if (breadcrumb.category === 'fetch' || breadcrumb.category === 'xhr') {
        if (breadcrumb.data?.headers) {
          delete breadcrumb.data.headers['Authorization'];
        }
      }
      return breadcrumb;
    },
  });
}
```

Call `initSentry()` at the top of `App.tsx`, before any React rendering:

```typescript
import { initSentry } from './src/lib/sentry';
initSentry();

export default function App() { ... }
```

### 3.3 Custom Context

Attach to Sentry whenever state changes:

```typescript
// After successful login:
Sentry.setUser({
  id: walletAddress.slice(0, 8), // Abbreviated, not full address
});
Sentry.setContext('session', {
  authMethod: 'privy_social', // or 'wallet_siws'
  level: user.level,
  totalRides: user.totalRides,
});

// During ride recording:
Sentry.setContext('recording', {
  rideId: localRideUuid,
  startedAt: rideStartTime,
  sampleCount: currentSampleCount,
  gpsAccuracy: lastAccuracy,
  sensorsConnected: ['power', 'hr'], // or []
});

// On logout:
Sentry.setUser(null);
Sentry.setContext('recording', null);
Sentry.setContext('session', null);
```

### 3.4 Breadcrumbs to Track

Sentry auto-captures navigation, network, and console breadcrumbs. Add these manual breadcrumbs:

```typescript
// Auth events
Sentry.addBreadcrumb({ category: 'auth', message: 'Login started', level: 'info' });
Sentry.addBreadcrumb({ category: 'auth', message: 'Login success', level: 'info' });
Sentry.addBreadcrumb({ category: 'auth', message: 'Token refresh', level: 'info' });
Sentry.addBreadcrumb({ category: 'auth', message: 'Session expired', level: 'warning' });

// Recording lifecycle
Sentry.addBreadcrumb({ category: 'recording', message: 'Ride started', level: 'info' });
Sentry.addBreadcrumb({ category: 'recording', message: 'Ride paused', level: 'info' });
Sentry.addBreadcrumb({ category: 'recording', message: 'Ride resumed', level: 'info' });
Sentry.addBreadcrumb({ category: 'recording', message: 'Ride stopped', level: 'info' });
Sentry.addBreadcrumb({ category: 'recording', message: 'GPS signal lost', level: 'warning' });
Sentry.addBreadcrumb({ category: 'recording', message: 'GPS signal regained', level: 'info' });
Sentry.addBreadcrumb({ category: 'recording', message: 'Sensor disconnected', level: 'warning', data: { sensor: 'power' } });

// Upload lifecycle
Sentry.addBreadcrumb({ category: 'upload', message: 'Upload queued', level: 'info', data: { rideId } });
Sentry.addBreadcrumb({ category: 'upload', message: 'Upload success', level: 'info', data: { rideId } });
Sentry.addBreadcrumb({ category: 'upload', message: 'Upload failed, retrying', level: 'warning', data: { rideId, attempt } });
Sentry.addBreadcrumb({ category: 'upload', message: 'Upload permanently failed', level: 'error', data: { rideId, attempts } });

// Transaction signing
Sentry.addBreadcrumb({ category: 'solana', message: 'Transaction submitted', level: 'info', data: { type: 'stake' } });
Sentry.addBreadcrumb({ category: 'solana', message: 'Transaction confirmed', level: 'info' });
Sentry.addBreadcrumb({ category: 'solana', message: 'Transaction failed', level: 'error', data: { error: errorCode } });
```

### 3.5 Performance Monitoring

```typescript
// Wrap slow screens with Sentry profiling
import * as Sentry from '@sentry/react-native';

// In navigation — automatically tracks screen transitions
export default Sentry.wrap(App);

// For custom spans (e.g., ride upload):
const transaction = Sentry.startTransaction({ name: 'ride.upload', op: 'task' });
const span = transaction.startChild({ op: 'serialize', description: 'Serialize GPS samples' });
// ... serialize ...
span.finish();
const uploadSpan = transaction.startChild({ op: 'http.client', description: 'POST /rides/native-upload' });
// ... upload ...
uploadSpan.finish();
transaction.finish();
```

### 3.6 Source Maps

EAS Build automatically uploads source maps to Sentry when the plugin is configured in `app.json`. No manual source map upload step needed.

For local development builds, add to `.env`:
```
SENTRY_AUTH_TOKEN=<your-sentry-auth-token>
```

Add to `eas.json` (see Section 4.3):
```json
{
  "build": {
    "production": {
      "env": {
        "SENTRY_AUTH_TOKEN": "<set-in-eas-secrets>"
      }
    }
  }
}
```

Store the Sentry auth token in EAS Secrets:
```bash
eas secret:create --name SENTRY_AUTH_TOKEN --value <token> --scope project
```

### 3.7 Cost

Sentry free tier: 5,000 errors/month, 10,000 performance transactions/month. This is sufficient through alpha and early beta. Upgrade to Team ($26/mo) if needed at >1,000 DAU.

---

## 4. CI/CD Pipeline

### 4.1 EAS Configuration

Create `mobile/eas.json`:

```json
{
  "$schema": "https://raw.githubusercontent.com/expo/eas-cli/main/packages/eas-json/schema/eas.schema.json",
  "cli": {
    "version": ">= 13.0.0",
    "appVersionSource": "remote"
  },
  "build": {
    "development": {
      "developmentClient": true,
      "distribution": "internal",
      "ios": {
        "simulator": true
      },
      "env": {
        "APP_ENV": "development",
        "API_URL": "http://localhost:8080"
      }
    },
    "preview": {
      "distribution": "internal",
      "ios": {
        "simulator": false
      },
      "env": {
        "APP_ENV": "staging",
        "API_URL": "http://203.0.113.10:8080"
      },
      "channel": "preview"
    },
    "production": {
      "autoIncrement": true,
      "env": {
        "APP_ENV": "production",
        "API_URL": "https://api.boulderroller.org"
      },
      "channel": "production"
    }
  },
  "submit": {
    "production": {
      "ios": {
        "appleId": "REPLACE_WITH_APPLE_ID",
        "ascAppId": "REPLACE_WITH_ASC_APP_ID",
        "appleTeamId": "REPLACE_WITH_TEAM_ID"
      },
      "android": {
        "serviceAccountKeyPath": "./google-services.json",
        "track": "internal"
      }
    }
  }
}
```

### 4.2 App Config Migration

Convert `mobile/app.json` to `mobile/app.config.ts` to support environment variables:

```typescript
import { ExpoConfig, ConfigContext } from 'expo/config';

export default ({ config }: ConfigContext): ExpoConfig => ({
  ...config,
  name: 'BoulderRoller',
  slug: 'boulderroller',
  version: '0.1.0',
  orientation: 'portrait',
  icon: './assets/icon.png',
  userInterfaceStyle: 'dark',
  newArchEnabled: true,
  splash: {
    image: './assets/splash-icon.png',
    resizeMode: 'contain',
    backgroundColor: '#0a0a0a',
  },
  ios: {
    supportsTablet: false,
    bundleIdentifier: 'com.boulderroller.app',
    infoPlist: {
      NSLocationWhenInUseUsageDescription:
        'BoulderRoller uses your location to record cycling rides and detect climbs.',
      NSLocationAlwaysAndWhenInUseUsageDescription:
        'BoulderRoller needs background location access to record your ride while the screen is off.',
      UIBackgroundModes: ['location'],
    },
  },
  android: {
    adaptiveIcon: {
      foregroundImage: './assets/adaptive-icon.png',
      backgroundColor: '#0a0a0a',
    },
    package: 'com.boulderroller.app',
    permissions: [
      'ACCESS_FINE_LOCATION',
      'ACCESS_COARSE_LOCATION',
      'ACCESS_BACKGROUND_LOCATION',
      'FOREGROUND_SERVICE',
      'BLUETOOTH',
      'BLUETOOTH_CONNECT',
      'BLUETOOTH_SCAN',
    ],
  },
  plugins: [
    'expo-secure-store',
    [
      '@sentry/react-native/expo',
      {
        organization: 'boulderroller',
        project: 'mobile',
        url: 'https://sentry.io/',
      },
    ],
  ],
  extra: {
    apiUrl: process.env.API_URL ?? 'http://localhost:8080',
    sentryDsn: process.env.SENTRY_DSN ?? '',
    privyAppId: process.env.PRIVY_APP_ID ?? 'REPLACE_WITH_PRIVY_APP_ID',
    buildNumber: process.env.EAS_BUILD_NUMBER ?? '1',
    eas: {
      projectId: 'REPLACE_WITH_EAS_PROJECT_ID',
    },
  },
});
```

Then update `mobile/src/constants/config.ts` to read from Constants:

```typescript
import Constants from 'expo-constants';

const extra = Constants.expoConfig?.extra ?? {};

export const API_URL: string = extra.apiUrl ?? 'http://localhost:8080';
export const PRIVY_APP_ID: string = extra.privyAppId ?? 'REPLACE_WITH_PRIVY_APP_ID';
export const SENTRY_DSN: string = extra.sentryDsn ?? '';

// These are static — no env override needed
export const SOLANA_RPC_URL = __DEV__
  ? 'https://api.devnet.solana.com'
  : 'https://api.devnet.solana.com'; // stays devnet until mainnet

export const SOLANA_PROGRAM_ID = '6ciJ4u4BHEb51jswh6qLwU7fksTNxwC8fKk4AumPBE4X';
export const CAL_MINT = 'B9u8L5pkWTce2SXJCKvNSKTrSukvWoajEdzy9STLNh6K';
export const DUNG_MINT = 'AnPJmvr1HK36DwWNQpdwW2vBd7Qq7AtAerU9kuqA9Sfn';
export const H3_RESOLUTION = 10;
export const APP_VERSION = '0.1.0';
export const APP_NAME = 'BoulderRoller';
```

### 4.3 GitHub Actions Workflow

Create `.github/workflows/mobile-ci.yml`:

```yaml
name: Mobile CI

on:
  push:
    paths:
      - 'mobile/**'
      - '.github/workflows/mobile-ci.yml'
  pull_request:
    paths:
      - 'mobile/**'
      - '.github/workflows/mobile-ci.yml'

jobs:
  lint-and-test:
    runs-on: ubuntu-latest
    defaults:
      run:
        working-directory: mobile

    steps:
      - name: Checkout
        uses: actions/checkout@v4

      - name: Setup Node.js
        uses: actions/setup-node@v4
        with:
          node-version: '20'
          cache: 'npm'
          cache-dependency-path: mobile/package-lock.json

      - name: Install dependencies
        run: npm ci

      - name: TypeScript type check
        run: npx tsc --noEmit

      - name: Lint
        run: npx expo lint

      - name: Run tests
        run: npm test -- --coverage --ci --forceExit

      - name: Upload coverage
        if: always()
        uses: actions/upload-artifact@v4
        with:
          name: mobile-coverage
          path: mobile/coverage/
          retention-days: 7

  eas-build-preview:
    needs: lint-and-test
    if: github.ref == 'refs/heads/main'
    runs-on: ubuntu-latest
    defaults:
      run:
        working-directory: mobile

    steps:
      - name: Checkout
        uses: actions/checkout@v4

      - name: Setup Node.js
        uses: actions/setup-node@v4
        with:
          node-version: '20'
          cache: 'npm'
          cache-dependency-path: mobile/package-lock.json

      - name: Setup EAS
        uses: expo/expo-github-action@v8
        with:
          eas-version: latest
          token: ${{ secrets.EXPO_TOKEN }}

      - name: Install dependencies
        run: npm ci

      - name: Build preview (iOS + Android)
        run: eas build --platform all --profile preview --non-interactive
        env:
          SENTRY_AUTH_TOKEN: ${{ secrets.SENTRY_AUTH_TOKEN }}
          SENTRY_DSN: ${{ secrets.SENTRY_DSN }}
          API_URL: http://203.0.113.10:8080
          PRIVY_APP_ID: ${{ secrets.PRIVY_APP_ID }}
```

### 4.4 Code Signing

#### iOS

EAS Build manages code signing automatically via `credentials.json` or interactive setup.

First-time setup:
```bash
cd mobile
eas credentials --platform ios
# Follow prompts: let EAS manage signing (recommended for small teams)
# This generates App Store Connect API key, provisioning profiles, and certificates
```

EAS stores credentials securely. No provisioning profiles in the repo.

For manual management (if needed later):
```bash
eas credentials --platform ios
# Choose "Download certificates and profiles"
# Store in a secure vault, NOT in git
```

#### Android

Generate a keystore for production signing:
```bash
keytool -genkeypair -v -storetype JKS \
  -keyalg RSA -keysize 2048 -validity 10000 \
  -storepass <password> -keypass <password> \
  -alias boulderroller \
  -keystore boulderroller-release.jks \
  -dname "CN=BoulderRoller, O=BoulderRoller, L=Philadelphia, ST=PA, C=US"
```

Upload to EAS:
```bash
eas credentials --platform android
# Choose "Upload existing keystore"
```

**NEVER commit keystores or provisioning profiles to git.** Add to `.gitignore`:
```
*.jks
*.keystore
*.mobileprovision
*.p12
google-services.json
```

### 4.5 App Store Submission

#### TestFlight (iOS Beta)

```bash
# Build production profile
eas build --platform ios --profile production

# Submit to App Store Connect
eas submit --platform ios --profile production
```

This requires Apple Developer account ($99/year) and App Store Connect API key.

#### Google Play Internal Testing

```bash
# Build production profile
eas build --platform android --profile production

# Submit to Google Play Console
eas submit --platform android --profile production
```

This requires Google Play Developer account ($25 one-time) and a service account JSON key.

### 4.6 Over-the-Air (OTA) Updates

EAS Update allows shipping JS bundle changes without App Store review. This is for bug fixes and UI changes only — native code changes still require a full build.

```bash
# Publish an update to the preview channel
eas update --branch preview --message "Fix ride list empty state"

# Publish to production
eas update --branch production --message "Fix points display rounding"
```

Configure in `app.config.ts`:
```typescript
{
  updates: {
    url: 'https://u.expo.dev/REPLACE_WITH_EAS_PROJECT_ID',
    fallbackToCacheTimeout: 0, // Show cached version immediately, update in background
  },
  runtimeVersion: {
    policy: 'appVersion', // New native build = new runtime version
  },
}
```

**OTA safety rule:** Never ship economic logic changes (points calculation, vault matching, upload payload format) via OTA. These must go through a full build + App Store review cycle so the version is traceable.

---

## 5. Production Monitoring

### 5.1 Analytics Events

Use Sentry breadcrumbs as the analytics layer for v1. Do NOT add a separate analytics SDK until >5,000 users. Rationale: Sentry is already integrated, free tier is sufficient, and adding another SDK increases bundle size and compliance surface.

Events to track via Sentry breadcrumbs (category: `analytics`):

| Event | Data | Purpose |
|-------|------|---------|
| `app_opened` | `{ cold: boolean }` | DAU, cold vs warm start |
| `auth_method_used` | `{ method: 'privy_google' \| 'privy_apple' \| 'privy_email' \| 'wallet_siws' }` | Which auth methods users prefer |
| `ride_started` | `{ source: 'native' }` | Recording adoption |
| `ride_completed` | `{ duration_sec, distance_m, sample_count }` | Ride completion rate |
| `ride_upload_success` | `{ ride_id, duration_ms }` | Upload success rate and latency |
| `ride_upload_failed` | `{ ride_id, attempt, error_type }` | Upload reliability |
| `vault_viewed` | `{ vault_signature: abbreviated }` | Vault engagement |
| `stake_initiated` | `{ vault_signature: abbreviated }` | Staking funnel entry |
| `stake_confirmed` | `{ vault_signature: abbreviated }` | Staking funnel completion |
| `screen_viewed` | `{ screen_name }` | Navigation patterns |
| `pull_to_refresh` | `{ screen_name }` | Engagement signal |

Implementation pattern:
```typescript
// src/lib/analytics.ts
import * as Sentry from '@sentry/react-native';

export function trackEvent(name: string, data?: Record<string, unknown>) {
  Sentry.addBreadcrumb({
    category: 'analytics',
    message: name,
    level: 'info',
    data,
  });
}

// Usage:
trackEvent('ride_completed', { duration_sec: 3600, distance_m: 42000, sample_count: 3600 });
```

When the project outgrows Sentry breadcrumbs (>5K users), migrate to PostHog (self-hostable, free tier, GDPR-friendly). PostHog can be self-hosted on the existing DO droplet if needed.

### 5.2 Health Dashboard

Do NOT set up a separate Grafana/Prometheus stack for the mobile app. Instead, leverage what exists:

1. **Sentry dashboard** — Crash-free rate, error frequency, performance (screen load times, API latency)
2. **Backend API logs** — Already deployed. Mobile requests are visible via `source=native` in ride uploads.
3. **Staging health** — The existing `staging-ops.sh health` command covers backend health.

For a lightweight mobile-specific dashboard, create a Sentry alert:
- **Alert 1:** Crash-free session rate drops below 99% -> Slack notification
- **Alert 2:** API error rate (from mobile user-agent) exceeds 5% over 5 minutes -> Slack notification
- **Alert 3:** Upload failure rate exceeds 10% -> Slack notification

These are configured in Sentry web UI, not in code.

### 5.3 User-Agent Header

Add a custom User-Agent to all API requests so the backend can distinguish mobile from web:

```typescript
// In APIClient.request():
headers['User-Agent'] = `BoulderRoller-Mobile/${APP_VERSION} (${Platform.OS} ${Platform.Version})`;
```

This enables backend-side filtering of mobile traffic in logs and metrics without any new infrastructure.

---

## 6. Dependency Summary

All new dependencies with exact version constraints:

### Production Dependencies

```json
{
  "@react-native-community/netinfo": "^11.4.0",
  "@sentry/react-native": "~6.5.0"
}
```

Install command:
```bash
cd mobile
npx expo install @sentry/react-native @react-native-community/netinfo
```

Use `npx expo install` (not `npm install`) to ensure version compatibility with Expo SDK 52.

### Dev Dependencies

```json
{
  "@testing-library/jest-native": "^5.4.3",
  "@testing-library/react-native": "^12.9.0",
  "@types/jest": "^29.5.0",
  "jest-expo": "~52.0.0",
  "msw": "^2.7.0"
}
```

Install command:
```bash
npx expo install -- --save-dev jest-expo
npm install --save-dev @testing-library/react-native@^12.9.0 @testing-library/jest-native@^5.4.3 @types/jest@^29.5.0 msw@^2.7.0
```

### CLI Tools (not in package.json)

```bash
# EAS CLI (global)
npm install -g eas-cli@latest

# Maestro (Phase 2 only)
curl -Ls "https://get.maestro.mobile.dev" | bash
```

---

## 7. File Manifest

Complete list of files to create or modify, in implementation order.

### Phase 0A: Test Infrastructure (Day 1)

| Action | File | Description |
|--------|------|-------------|
| MODIFY | `mobile/package.json` | Add scripts (test, test:watch, test:coverage), jest config, devDependencies |
| CREATE | `mobile/jest.setup.ts` | Native module mocks, navigation mocks |
| CREATE | `mobile/src/__tests__/mocks/handlers.ts` | MSW request handlers (happy path defaults) |
| CREATE | `mobile/src/__tests__/mocks/server.ts` | MSW server setup |
| CREATE | `mobile/src/lib/__tests__/api.test.ts` | API client unit tests |
| CREATE | `mobile/src/lib/__tests__/api-errors.test.ts` | Error classification tests |

### Phase 0B: Error Handling (Day 2)

| Action | File | Description |
|--------|------|-------------|
| CREATE | `mobile/src/components/ErrorBoundary.tsx` | Global React error boundary |
| CREATE | `mobile/src/components/ErrorBanner.tsx` | Inline error banner with retry |
| CREATE | `mobile/src/components/__tests__/ErrorBoundary.test.tsx` | Error boundary tests |
| MODIFY | `mobile/App.tsx` | Wrap with ErrorBoundary, init Sentry |
| MODIFY | `mobile/src/screens/HomeScreen.tsx` | Replace empty catch with error state |
| MODIFY | `mobile/src/screens/VaultsScreen.tsx` | Replace empty catch with error state |
| MODIFY | `mobile/src/screens/ProfileScreen.tsx` | Replace empty catch with error state |

### Phase 0C: Crash Reporting (Day 2-3)

| Action | File | Description |
|--------|------|-------------|
| CREATE | `mobile/src/lib/sentry.ts` | Sentry init, scrubbing, config |
| CREATE | `mobile/src/lib/analytics.ts` | `trackEvent()` wrapper over Sentry breadcrumbs |
| MODIFY | `mobile/App.tsx` | Call `initSentry()` before render, wrap with `Sentry.wrap()` |
| MODIFY | `mobile/src/lib/api.ts` | Add User-Agent header, add Sentry breadcrumbs on auth events |

### Phase 0D: CI/CD (Day 3)

| Action | File | Description |
|--------|------|-------------|
| CREATE | `mobile/eas.json` | EAS build profiles (dev, preview, production) |
| CREATE | `mobile/app.config.ts` | Dynamic config with env vars |
| DELETE | `mobile/app.json` | Replaced by app.config.ts |
| MODIFY | `mobile/src/constants/config.ts` | Read from Constants.expoConfig.extra |
| CREATE | `.github/workflows/mobile-ci.yml` | Lint + typecheck + test + EAS build |
| MODIFY | `mobile/.gitignore` | Add *.jks, *.keystore, *.mobileprovision, google-services.json |

### Phase 0E: Screen Tests (Day 4)

| Action | File | Description |
|--------|------|-------------|
| CREATE | `mobile/src/screens/__tests__/HomeScreen.test.tsx` | Ride list, empty state, error state |
| CREATE | `mobile/src/screens/__tests__/ProfileScreen.test.tsx` | Profile display, logout |
| CREATE | `mobile/src/screens/__tests__/VaultsScreen.test.tsx` | Vault list, empty state |
| CREATE | `mobile/src/screens/__tests__/RecordScreen.test.tsx` | Placeholder renders correctly |

### Phase 2 (reserved, not Phase 0)

| Action | File | Description |
|--------|------|-------------|
| CREATE | `mobile/.maestro/config.yaml` | Maestro configuration |
| CREATE | `mobile/.maestro/flows/login-and-profile.yaml` | E2E login flow |
| CREATE | `mobile/.maestro/flows/ride-recording.yaml` | E2E recording flow |

---

## Appendix A: API Client Test Reference

This is the highest-priority test file. Write this first.

`mobile/src/lib/__tests__/api.test.ts`:

```typescript
import { server } from '../../__tests__/mocks/server';
import { http, HttpResponse } from 'msw';
import { api, ApiError } from '../api';

const API_URL = 'http://localhost:8080';

beforeAll(() => server.listen());
afterEach(() => {
  server.resetHandlers();
  api.clearTokens();
});
afterAll(() => server.close());

describe('APIClient', () => {
  describe('authentication', () => {
    test('isAuthenticated returns false initially', () => {
      expect(api.isAuthenticated()).toBe(false);
    });

    test('setTokens makes isAuthenticated return true', () => {
      api.setTokens({
        accessToken: 'test-token',
        refreshToken: 'test-refresh',
        expiresIn: 3600,
      });
      expect(api.isAuthenticated()).toBe(true);
    });

    test('clearTokens makes isAuthenticated return false', () => {
      api.setTokens({
        accessToken: 'test-token',
        refreshToken: 'test-refresh',
        expiresIn: 3600,
      });
      api.clearTokens();
      expect(api.isAuthenticated()).toBe(false);
    });

    test('verifyPrivyToken stores tokens on success', async () => {
      const tokens = await api.verifyPrivyToken('wallet123', 'privy-token');
      expect(tokens.accessToken).toBe('test-access-token');
      expect(api.isAuthenticated()).toBe(true);
    });
  });

  describe('request headers', () => {
    test('sends Authorization header when authenticated', async () => {
      let capturedAuth: string | null = null;
      server.use(
        http.get(`${API_URL}/users/me`, ({ request }) => {
          capturedAuth = request.headers.get('Authorization');
          return HttpResponse.json({
            wallet: 'test', display_name: null, bio: null,
            avatar_url: null, created_at: '2026-01-01T00:00:00Z',
            total_points: 0, total_rides: 0, total_tss: 0, level: 1,
          });
        }),
      );

      api.setTokens({ accessToken: 'my-token', refreshToken: 'r', expiresIn: 3600 });
      await api.getMe();
      expect(capturedAuth).toBe('Bearer my-token');
    });
  });

  describe('case conversion', () => {
    test('converts snake_case response to camelCase', async () => {
      const user = await api.getMe();
      // Handler returns display_name, total_points etc.
      // Client should convert to displayName, totalPoints
      expect(user).toHaveProperty('displayName');
      expect(user).toHaveProperty('totalPoints');
      expect(user).not.toHaveProperty('display_name');
    });
  });

  describe('error handling', () => {
    test('throws ApiError with type=network_error on fetch failure', async () => {
      server.use(
        http.get(`${API_URL}/health`, () => {
          return HttpResponse.error();
        }),
      );

      await expect(api.healthCheck()).rejects.toThrow(ApiError);
      try {
        await api.healthCheck();
      } catch (err) {
        expect(err).toBeInstanceOf(ApiError);
        expect((err as ApiError).type).toBe('network_error');
        expect((err as ApiError).retryable).toBe(true);
      }
    });

    test('throws ApiError with type=session_expired on 401', async () => {
      server.use(
        http.get(`${API_URL}/users/me`, () => {
          return new HttpResponse(null, { status: 401 });
        }),
      );

      api.setTokens({ accessToken: 'expired', refreshToken: 'r', expiresIn: 0 });

      await expect(api.getMe()).rejects.toThrow(ApiError);
      try {
        await api.getMe();
      } catch (err) {
        expect((err as ApiError).type).toBe('session_expired');
        expect((err as ApiError).statusCode).toBe(401);
      }
      // Tokens should be cleared after 401
      expect(api.isAuthenticated()).toBe(false);
    });

    test('throws ApiError with type=server_error on 500', async () => {
      server.use(
        http.get(`${API_URL}/rides`, () => {
          return new HttpResponse('Internal Server Error', { status: 500 });
        }),
      );

      api.setTokens({ accessToken: 'token', refreshToken: 'r', expiresIn: 3600 });
      try {
        await api.getRides();
      } catch (err) {
        expect((err as ApiError).type).toBe('server_error');
        expect((err as ApiError).retryable).toBe(true);
      }
    });

    test('handles 204 No Content response', async () => {
      server.use(
        http.post(`${API_URL}/auth/logout`, () => {
          return new HttpResponse(null, { status: 204 });
        }),
      );

      api.setTokens({ accessToken: 'token', refreshToken: 'r', expiresIn: 3600 });
      // Should not throw
      await api.logout();
      expect(api.isAuthenticated()).toBe(false);
    });
  });
});
```

---

## Appendix B: Cost Summary

| Item | Cost | Notes |
|------|------|-------|
| Sentry free tier | $0 | 5K errors/mo, 10K transactions/mo |
| EAS Build free tier | $0 | 30 builds/mo (iOS + Android, sufficient for alpha) |
| EAS Update free tier | $0 | 1,000 monthly updating users |
| Apple Developer Program | $99/year | Required for TestFlight + App Store |
| Google Play Developer | $25 one-time | Required for Play Store |
| GitHub Actions | $0 | Free for public repos; 2,000 min/mo for private |
| Maestro Cloud (Phase 2) | $0 free tier | 100 flows/mo |
| **Total Phase 0** | **$0** | Assumes Apple/Google accounts already exist |

---

## Appendix C: Implementation Checklist

For the implementing agent, check these off in order:

- [ ] Install test dependencies (`jest-expo`, RNTL, MSW, types)
- [ ] Add jest config to `package.json`, add `test` script
- [ ] Create `jest.setup.ts` with native module mocks
- [ ] Create MSW server + handlers
- [ ] Write `api.test.ts` (reference pattern) — verify tests pass
- [ ] Write `api-errors.test.ts` — verify tests pass
- [ ] Create `ErrorBoundary.tsx` component
- [ ] Create `ErrorBanner.tsx` component
- [ ] Write `ErrorBoundary.test.tsx` — verify tests pass
- [ ] Install Sentry (`npx expo install @sentry/react-native`)
- [ ] Create `sentry.ts` init file
- [ ] Create `analytics.ts` trackEvent wrapper
- [ ] Wire Sentry into `App.tsx` (init + wrap + ErrorBoundary)
- [ ] Replace empty catch blocks in all 3 screens
- [ ] Install netinfo (`npx expo install @react-native-community/netinfo`)
- [ ] Create `eas.json`
- [ ] Convert `app.json` to `app.config.ts`
- [ ] Update `config.ts` to read from Constants
- [ ] Create `.github/workflows/mobile-ci.yml`
- [ ] Write screen tests (Home, Profile, Vaults, Record)
- [ ] Run full test suite, verify all pass
- [ ] Run `npx tsc --noEmit`, verify zero type errors
- [ ] Verify CI workflow passes on push
