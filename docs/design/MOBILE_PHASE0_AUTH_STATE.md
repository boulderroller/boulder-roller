# Mobile Phase 0: Auth, State Management, and Security

**Date:** 2026-03-28
**Status:** Implementation Spec (ready for dev agents)
**Scope:** Secure token storage, state management architecture, Privy integration, certificate pinning, biometric auth
**Prerequisites:** None. This is the foundation layer that must land before any feature code.

---

## Table of Contents

1. [Backend Blocker: Token Refresh for Mobile](#1-backend-blocker-token-refresh-for-mobile)
2. [Secure Token Storage](#2-secure-token-storage)
3. [State Management Architecture](#3-state-management-architecture)
4. [Privy Integration](#4-privy-integration)
5. [Certificate Pinning](#5-certificate-pinning)
6. [Biometric Auth](#6-biometric-auth)
7. [New Dependencies](#7-new-dependencies)
8. [Provider Hierarchy](#8-provider-hierarchy)
9. [File Manifest](#9-file-manifest)

---

## 1. Backend Blocker: Token Refresh for Mobile

### Problem

`POST /auth/refresh` reads the refresh token exclusively from an HttpOnly cookie:

```python
# backend/app/routes/auth.py, line 613
refresh_token = request.cookies.get("refresh_token")
if not refresh_token:
    raise AuthError("refresh_missing", "No refresh token provided", ...)
```

React Native cannot send HttpOnly cookies. The mobile app stores tokens in `expo-secure-store` and sends them via headers/body. Without this fix, the mobile app cannot refresh expired access tokens and users will be logged out every 15 minutes (the `access_token_minutes` default).

### Fix

In `backend/app/routes/auth.py`, the `refresh_tokens` function (line 603-713), replace the single cookie read on line 613 with a three-source fallback:

```python
# Replace line 613:
#   refresh_token = request.cookies.get("refresh_token")
# With:
refresh_token = (
    request.cookies.get("refresh_token")            # 1. Cookie (web browsers)
    or payload.refresh_token                         # 2. Request body (mobile apps)
    or _extract_bearer(request.headers.get("X-Refresh-Token"))  # 3. Custom header (fallback)
)
```

The `RefreshRequest` schema already has a `refresh_token` field (file `backend/app/schemas.py`, line 95-99) but it is marked deprecated. Restore it to active use:

```python
# backend/app/schemas.py, line 95-99: change description
refresh_token: Optional[str] = Field(
    None,
    min_length=1,
    description="Refresh token. Required for mobile clients that cannot send HttpOnly cookies.",
    validation_alias=AliasChoices("refresh_token", "refreshToken"),
)
```

Add the `_extract_bearer` helper near the existing `_wallet_from_authorization` helper (line 1018):

```python
def _extract_bearer(header_value: Optional[str]) -> Optional[str]:
    """Extract token from 'Bearer <token>' format, or return raw value."""
    if not header_value:
        return None
    if header_value.lower().startswith("bearer "):
        return header_value.split(" ", 1)[1].strip()
    return header_value.strip()
```

Similarly, the `logout` endpoint (line 716-749) reads `refresh_token` from cookies only (line 727). Apply the same three-source fallback there, reading from `payload` (which is `Optional[LogoutRequest]`) and the `X-Refresh-Token` header.

### Security Note

The cookie-based flow for web clients is unchanged. The body/header fallback only activates when the cookie is absent. Token replay detection (line 638-647) still applies regardless of how the token is delivered.

### Token Lifetime Reference

From `backend/app/config.py` lines 196-197:
- **Access token:** 15 minutes (env: `AUTH_ACCESS_TOKEN_MINUTES`, default 15)
- **Refresh token:** 14 days (env: `AUTH_REFRESH_TOKEN_DAYS`, default 14)

---

## 2. Secure Token Storage

### Library

`expo-secure-store` (already in `mobile/package.json` at `~14.0.0`). Uses iOS Keychain and Android EncryptedSharedPreferences.

### Storage Keys

| Key | Value | Notes |
|-----|-------|-------|
| `br_access_token` | JWT string | 15-minute TTL |
| `br_refresh_token` | JWT string | 14-day TTL |
| `br_token_expires_at` | ISO 8601 string | Parsed from JWT `exp` claim |
| `br_device_id` | UUID v4 string | Generated once on first launch, never changes |
| `br_wallet` | Solana pubkey string | Last authenticated wallet |
| `br_auth_method` | `"privy"` or `"wallet"` | Which auth method was used |

### Service: `mobile/src/services/secureStorage.ts`

```typescript
import * as SecureStore from 'expo-secure-store';
import { Platform } from 'react-native';

const KEYS = {
  ACCESS_TOKEN: 'br_access_token',
  REFRESH_TOKEN: 'br_refresh_token',
  TOKEN_EXPIRES_AT: 'br_token_expires_at',
  DEVICE_ID: 'br_device_id',
  WALLET: 'br_wallet',
  AUTH_METHOD: 'br_auth_method',
} as const;

// expo-secure-store options: require device authentication for sensitive keys
const SECURE_OPTIONS: SecureStore.SecureStoreOptions = {
  keychainAccessible: SecureStore.WHEN_UNLOCKED_THIS_DEVICE_ONLY,
};

export async function getAccessToken(): Promise<string | null> {
  return SecureStore.getItemAsync(KEYS.ACCESS_TOKEN, SECURE_OPTIONS);
}

export async function getRefreshToken(): Promise<string | null> {
  return SecureStore.getItemAsync(KEYS.REFRESH_TOKEN, SECURE_OPTIONS);
}

export async function getTokenExpiresAt(): Promise<number | null> {
  const raw = await SecureStore.getItemAsync(KEYS.TOKEN_EXPIRES_AT, SECURE_OPTIONS);
  return raw ? parseInt(raw, 10) : null;
}

export async function storeTokens(params: {
  accessToken: string;
  refreshToken: string;
  expiresAtMs: number;
  wallet: string;
  authMethod: 'privy' | 'wallet';
}): Promise<void> {
  await Promise.all([
    SecureStore.setItemAsync(KEYS.ACCESS_TOKEN, params.accessToken, SECURE_OPTIONS),
    SecureStore.setItemAsync(KEYS.REFRESH_TOKEN, params.refreshToken, SECURE_OPTIONS),
    SecureStore.setItemAsync(KEYS.TOKEN_EXPIRES_AT, String(params.expiresAtMs), SECURE_OPTIONS),
    SecureStore.setItemAsync(KEYS.WALLET, params.wallet, SECURE_OPTIONS),
    SecureStore.setItemAsync(KEYS.AUTH_METHOD, params.authMethod, SECURE_OPTIONS),
  ]);
}

export async function clearTokens(): Promise<void> {
  await Promise.all([
    SecureStore.deleteItemAsync(KEYS.ACCESS_TOKEN),
    SecureStore.deleteItemAsync(KEYS.REFRESH_TOKEN),
    SecureStore.deleteItemAsync(KEYS.TOKEN_EXPIRES_AT),
    SecureStore.deleteItemAsync(KEYS.WALLET),
    SecureStore.deleteItemAsync(KEYS.AUTH_METHOD),
  ]);
  // Note: DEVICE_ID is intentionally NOT cleared on logout.
  // It persists across sessions for refresh token binding.
}

export async function getDeviceId(): Promise<string> {
  let deviceId = await SecureStore.getItemAsync(KEYS.DEVICE_ID);
  if (!deviceId) {
    // crypto.randomUUID() is available in React Native Hermes
    deviceId = crypto.randomUUID();
    await SecureStore.setItemAsync(KEYS.DEVICE_ID, deviceId);
  }
  return deviceId;
}

export async function getStoredWallet(): Promise<string | null> {
  return SecureStore.getItemAsync(KEYS.WALLET);
}

export async function getStoredAuthMethod(): Promise<'privy' | 'wallet' | null> {
  const method = await SecureStore.getItemAsync(KEYS.AUTH_METHOD);
  if (method === 'privy' || method === 'wallet') return method;
  return null;
}
```

### Key Decisions

1. **`WHEN_UNLOCKED_THIS_DEVICE_ONLY`**: Tokens are only accessible when the device is unlocked and cannot be restored from backups to other devices. This is the right level for auth tokens (not `ALWAYS` which would allow access from lock screen).

2. **Device ID persists across logout**: The backend binds refresh tokens to `device_id`. If we regenerated it on logout, the user would appear as a new device every time, triggering new-device notifications.

3. **No `expo-secure-store` size limit concern**: Each JWT is ~500-800 bytes. `expo-secure-store` has a 2048-byte limit per key on some Android versions, but JWTs fit well within this.

4. **Expiry stored as epoch milliseconds**: Parsed once from the JWT `exp` claim at storage time. Avoids repeated JWT parsing on every auth check.

---

## 3. State Management Architecture

### New Dependencies

| Package | Version | Purpose |
|---------|---------|---------|
| `zustand` | `^4.5` | Local/app state (auth, settings, recording) |
| `@tanstack/react-query` | `^5.x` | Server state (rides, feed, points, notifications) |

### What Goes Where

| Data | Tool | Why |
|------|------|-----|
| Auth state (tokens, wallet, isAuthenticated) | **Zustand** `authStore` | Must be synchronous for navigation guards. Persisted to SecureStore. |
| User profile (`/users/me`) | **TanStack Query** | Server-owned data. Cache 5 min. Invalidated on profile update. |
| Points balance (`/points/balance`) | **TanStack Query** | Server-owned. Cache 1 min. Invalidated after ride upload. |
| Ride list (`/rides`) | **TanStack Query** | Server-owned. Paginated. Invalidated after upload. |
| Feed (`/feed/global`) | **TanStack Query** | Server-owned. Pull-to-refresh. |
| Notifications (`/notifications`) | **TanStack Query** | Server-owned. Poll every 60s when app is foregrounded. |
| Ride processing status (`/rides/{id}/status`) | **TanStack Query** with `refetchInterval` | Polling server. Stop polling when `status === 'completed'`. |
| Recording state (GPS, timer, paused) | **Zustand** `recordingStore` | Local state machine. Backed by SQLite (Phase 1). |
| Settings (units, FTP, weight) | **Zustand** `settingsStore` | Persisted to AsyncStorage. Synced from server on login. |
| UI state (modals, selected tab) | **React local state** | Ephemeral. No store needed. |

### 3.1 Auth Store: `mobile/src/stores/authStore.ts`

```typescript
import { create } from 'zustand';

type AuthStatus = 'loading' | 'unauthenticated' | 'authenticated' | 'refreshing';

interface AuthState {
  status: AuthStatus;
  wallet: string | null;
  authMethod: 'privy' | 'wallet' | null;
  accessToken: string | null;
  tokenExpiresAt: number | null;  // epoch ms

  // Actions
  setAuthenticated: (params: {
    accessToken: string;
    tokenExpiresAt: number;
    wallet: string;
    authMethod: 'privy' | 'wallet';
  }) => void;
  setRefreshing: () => void;
  setUnauthenticated: () => void;
  setLoading: () => void;
}

export const useAuthStore = create<AuthState>((set) => ({
  status: 'loading',
  wallet: null,
  authMethod: null,
  accessToken: null,
  tokenExpiresAt: null,

  setAuthenticated: (params) =>
    set({
      status: 'authenticated',
      accessToken: params.accessToken,
      tokenExpiresAt: params.tokenExpiresAt,
      wallet: params.wallet,
      authMethod: params.authMethod,
    }),

  setRefreshing: () =>
    set((state) => ({
      ...state,
      status: 'refreshing',
    })),

  setUnauthenticated: () =>
    set({
      status: 'unauthenticated',
      wallet: null,
      authMethod: null,
      accessToken: null,
      tokenExpiresAt: null,
    }),

  setLoading: () =>
    set((state) => ({
      ...state,
      status: 'loading',
    })),
}));
```

**Why Zustand and not Context for auth?** Navigation guards (`isAuthenticated ? TabNavigator : AuthStack`) must read auth state synchronously. Zustand's `getState()` provides this without async Context resolution. TanStack Query cannot do this because `useQuery` is inherently async.

**Why no Zustand persist middleware for auth?** Because `expo-secure-store` is async and `zustand/middleware/persist` expects synchronous storage adapters. Instead, we manually hydrate the Zustand store from SecureStore on app startup (see Section 3.3).

### 3.2 TanStack Query Configuration: `mobile/src/lib/queryClient.ts`

```typescript
import { QueryClient } from '@tanstack/react-query';

export const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 60_000,        // 1 minute before data is considered stale
      gcTime: 5 * 60_000,       // 5 minutes before inactive data is garbage collected
      retry: 2,                 // Retry failed requests twice
      retryDelay: (attempt) => Math.min(1000 * 2 ** attempt, 10_000),
      refetchOnWindowFocus: false, // Not applicable on mobile; use AppState instead
    },
    mutations: {
      retry: 0,                 // Don't auto-retry mutations
    },
  },
});
```

### 3.3 Auth Lifecycle: `mobile/src/services/authService.ts`

This service orchestrates the full auth lifecycle. It bridges SecureStore (persistence), Zustand (reactive state), and the API client (network).

```typescript
// Pseudocode — exact implementation follows this contract

/**
 * Called once on app startup (in App.tsx useEffect).
 * Hydrates Zustand from SecureStore and validates the session.
 */
async function initializeAuth(): Promise<void> {
  // 1. Read tokens from SecureStore
  const [accessToken, refreshToken, expiresAt, wallet, authMethod] = await Promise.all([
    getAccessToken(),
    getRefreshToken(),
    getTokenExpiresAt(),
    getStoredWallet(),
    getStoredAuthMethod(),
  ]);

  // 2. No stored tokens → unauthenticated
  if (!accessToken || !refreshToken || !wallet) {
    useAuthStore.getState().setUnauthenticated();
    return;
  }

  // 3. Access token not expired → hydrate store, verify with bootstrap
  const now = Date.now();
  if (expiresAt && expiresAt > now + 60_000) {
    // Token still valid (with 1-min buffer)
    useAuthStore.getState().setAuthenticated({
      accessToken,
      tokenExpiresAt: expiresAt,
      wallet,
      authMethod: authMethod ?? 'wallet',
    });

    // Background: validate session is still good server-side
    try {
      await apiClient.getBootstrap();
    } catch {
      // If bootstrap fails (e.g., token revoked server-side), try refresh
      await attemptRefresh();
    }
    return;
  }

  // 4. Access token expired → attempt refresh
  await attemptRefresh();
}

/**
 * Attempt to refresh the access token using the stored refresh token.
 * On success: updates SecureStore + Zustand.
 * On failure: clears everything, user must re-login.
 */
async function attemptRefresh(): Promise<boolean> {
  useAuthStore.getState().setRefreshing();

  const refreshToken = await getRefreshToken();
  const deviceId = await getDeviceId();

  if (!refreshToken) {
    useAuthStore.getState().setUnauthenticated();
    await clearTokens();
    return false;
  }

  try {
    const result = await apiClient.refreshTokens(refreshToken, deviceId);
    const expiresAtMs = parseJwtExpiry(result.accessToken);

    await storeTokens({
      accessToken: result.accessToken,
      refreshToken: result.refreshToken,
      expiresAtMs,
      wallet: result.wallet,
      authMethod: (await getStoredAuthMethod()) ?? 'wallet',
    });

    useAuthStore.getState().setAuthenticated({
      accessToken: result.accessToken,
      tokenExpiresAt: expiresAtMs,
      wallet: result.wallet,
      authMethod: (await getStoredAuthMethod()) ?? 'wallet',
    });

    return true;
  } catch {
    useAuthStore.getState().setUnauthenticated();
    await clearTokens();
    return false;
  }
}
```

### 3.4 Token Refresh Strategy for Long Rides

A ride can last 4+ hours. The access token expires in 15 minutes. The app must refresh tokens in the background without interrupting recording.

**Strategy: Proactive refresh with AppState monitoring.**

```
Timeline for a 4-hour ride:
  0:00  - Start ride. Access token valid.
  0:10  - Proactive refresh fires (5 min before 0:15 expiry).
          New access token (expires 0:25). New refresh token stored.
  0:20  - Proactive refresh fires again.
          ...repeats every ~10 minutes...
  4:00  - Stop ride. Upload begins. Token is fresh.
```

Implementation in `mobile/src/services/tokenRefreshManager.ts`:

```typescript
// Pseudocode contract

const REFRESH_BUFFER_MS = 5 * 60 * 1000; // 5 minutes before expiry

class TokenRefreshManager {
  private timer: ReturnType<typeof setTimeout> | null = null;
  private refreshPromise: Promise<boolean> | null = null;

  /**
   * Schedule the next proactive refresh based on token expiry.
   * Called after every successful login or refresh.
   */
  schedule(): void {
    this.cancel();

    const expiresAt = useAuthStore.getState().tokenExpiresAt;
    if (!expiresAt) return;

    const msUntilRefresh = expiresAt - Date.now() - REFRESH_BUFFER_MS;

    if (msUntilRefresh <= 0) {
      // Already due — refresh immediately
      this.refresh();
      return;
    }

    this.timer = setTimeout(() => this.refresh(), msUntilRefresh);
  }

  /**
   * Execute refresh. Deduplicates concurrent calls.
   */
  async refresh(): Promise<boolean> {
    if (this.refreshPromise) return this.refreshPromise;

    this.refreshPromise = attemptRefresh()
      .then((success) => {
        if (success) this.schedule(); // Schedule next refresh
        return success;
      })
      .finally(() => {
        this.refreshPromise = null;
      });

    return this.refreshPromise;
  }

  cancel(): void {
    if (this.timer) {
      clearTimeout(this.timer);
      this.timer = null;
    }
  }
}

export const tokenRefreshManager = new TokenRefreshManager();
```

**AppState handling** (in the auth initialization hook):

```typescript
import { AppState, AppStateStatus } from 'react-native';

// When app comes to foreground after being backgrounded:
AppState.addEventListener('change', (nextState: AppStateStatus) => {
  if (nextState === 'active') {
    const { status, tokenExpiresAt } = useAuthStore.getState();
    if (status === 'authenticated' && tokenExpiresAt) {
      const remaining = tokenExpiresAt - Date.now();
      if (remaining < REFRESH_BUFFER_MS) {
        // Token expired or about to expire while backgrounded
        tokenRefreshManager.refresh();
      } else {
        // Reschedule — timer may have been killed by OS
        tokenRefreshManager.schedule();
      }
    }
  }
});
```

### 3.5 API Client Modifications

The existing `mobile/src/lib/api.ts` singleton pattern must be replaced with a service that reads tokens from the Zustand store (in-memory, synchronous) and falls back to refresh on 401.

**Key changes to `APIClient`:**

1. Remove `private accessToken` and `private refreshToken` fields (lines 132-133).
2. Read access token from `useAuthStore.getState().accessToken` in the `request()` method.
3. On 401 response, attempt one refresh before failing:

```typescript
// In the request() method, replace lines 186-188:
if (response.status === 401) {
  // Attempt refresh before giving up
  const refreshed = await tokenRefreshManager.refresh();
  if (refreshed) {
    // Retry the original request with new token
    const newToken = useAuthStore.getState().accessToken;
    headers['Authorization'] = `Bearer ${newToken}`;
    const retryResponse = await fetch(url, { method, headers, body: /* ... */ });
    if (retryResponse.ok) {
      return toCamelCase(await retryResponse.json()) as T;
    }
  }
  // Refresh failed or retry failed — clear auth
  useAuthStore.getState().setUnauthenticated();
  await clearTokens();
  throw new ApiError('Session expired', 'session_expired', 401);
}
```

4. The `refreshTokens` method sends the refresh token in the request body (not a cookie):

```typescript
async refreshTokens(refreshToken: string, deviceId: string): Promise<RefreshResponse> {
  const response = await fetch(`${API_URL}/auth/refresh`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      refresh_token: refreshToken,
      device_id: deviceId,
    }),
  });
  if (!response.ok) throw new ApiError('Refresh failed', 'session_expired', response.status);
  return toCamelCase(await response.json()) as RefreshResponse;
}
```

### 3.6 Auth State Flow Diagram

```
App Launch
    |
    v
[status: loading]
    |
    +--- Read SecureStore ---+
    |                        |
    | no tokens              | has tokens
    v                        v
[unauthenticated]     Check expiry
    |                   |         |
    |            valid  |         | expired
    |                   v         v
    |          [authenticated]  Attempt refresh
    |               |              |         |
    |               |         success      failure
    |               |              |         |
    |               |              v         v
    |               |      [authenticated]  [unauthenticated]
    |               |
    v               v
[AuthStack]    [TabNavigator]
 (Login)        (Home, Record, Vaults, Profile)
    |
    | Privy login / wallet connect
    v
POST /auth/privy/verify
    |
    | success: store tokens, hydrate store
    v
[authenticated] --> [TabNavigator]
    |
    | 401 during API call
    v
[refreshing] --> attempt refresh
    |                |         |
    |           success      failure
    |                |         |
    v                v         v
[authenticated]   [auth...]  [unauthenticated] --> [AuthStack]
```

---

## 4. Privy Integration

### Library

`@privy-io/expo` (already in `mobile/package.json` at `^0.63.0`).

### Privy App ID

`cmjp145cl008xl70clr2ho821` (update `mobile/src/constants/config.ts` line 14).

### Architecture

The mobile Privy integration mirrors the portal pattern from `web/portal/src/contexts/PrivyContext.tsx` but adapted for React Native:

```
[PrivyProvider]  (from @privy-io/expo)
    |
    v
[PrivyAuthBridge]  (our component)
    |
    | Watches: privy.authenticated, privy.user
    | On Privy login:
    |   1. Extract wallet from privy user
    |   2. Get Privy access token
    |   3. POST /auth/privy/verify (wallet + privyToken + deviceId)
    |   4. Receive our JWT tokens
    |   5. Store in SecureStore
    |   6. Hydrate Zustand authStore
    |
    v
[Rest of app]  (reads auth from Zustand, not Privy)
```

### Service: `mobile/src/services/privyBridge.ts`

This is the mobile equivalent of the portal's `PrivyAuthBridge` component.

```typescript
// Contract — the bridge must implement:

interface PrivyBridgeConfig {
  maxTokenRetries: 3;
  tokenRetryDelayMs: 1000;
  walletCreationTimeoutMs: 30_000;
}

/**
 * Called when Privy reports authentication.
 * Bridges Privy session → our backend JWT → SecureStore → Zustand.
 */
async function syncPrivyAuth(
  privyUser: PrivyUser,
  getAccessToken: () => Promise<string | null>,
): Promise<void> {
  // 1. Extract wallet address from Privy user
  //    Prefer embedded wallet (walletClientType === 'privy')
  //    Fall back to first linked wallet
  const wallet = extractWalletAddress(privyUser);
  if (!wallet) {
    // Wallet not yet created (embedded wallet creation in progress)
    // Set walletPending flag, start timeout
    return;
  }

  // 2. Get Privy access token with retry
  const privyToken = await getAccessTokenWithRetry(getAccessToken, 3, 1000);
  if (!privyToken) {
    throw new Error('Failed to get Privy access token');
  }

  // 3. Exchange Privy token for our JWT
  const deviceId = await getDeviceId();
  const result = await apiClient.verifyPrivyToken(wallet, privyToken, deviceId);

  // 4. Persist tokens
  const expiresAtMs = parseJwtExpiry(result.accessToken);
  await storeTokens({
    accessToken: result.accessToken,
    refreshToken: result.refreshToken,
    expiresAtMs,
    wallet: result.wallet,
    authMethod: 'privy',
  });

  // 5. Hydrate Zustand
  useAuthStore.getState().setAuthenticated({
    accessToken: result.accessToken,
    tokenExpiresAt: expiresAtMs,
    wallet: result.wallet,
    authMethod: 'privy',
  });

  // 6. Start proactive refresh timer
  tokenRefreshManager.schedule();
}
```

### Wallet Extraction Logic

Ported from the portal (`extractPrivyWalletAddress` in `PrivyContext.tsx` lines 55-94):

```typescript
function extractWalletAddress(user: PrivyUser): string | null {
  // 1. Prefer embedded Solana wallet (created by Privy for social login users)
  const embedded = user.linkedAccounts?.find(
    (a) => a.type === 'wallet' && a.walletClientType === 'privy' && a.chainType === 'solana'
  );
  if (embedded?.address) return embedded.address;

  // 2. Fall back to any linked Solana wallet
  const anyWallet = user.linkedAccounts?.find(
    (a) => a.type === 'wallet' && a.chainType === 'solana'
  );
  if (anyWallet?.address) return anyWallet.address;

  // 3. Fall back to user.wallet (legacy)
  if (user.wallet?.address) return user.wallet.address;

  return null;
}
```

### PrivyAuthBridge Component: `mobile/src/components/PrivyAuthBridge.tsx`

```typescript
// This is a React component that wraps children and runs the sync effect.
// It mirrors web/portal/src/contexts/PrivyContext.tsx lines 99-208.

function PrivyAuthBridge({ children }: { children: React.ReactNode }) {
  const { authenticated, user, ready, getAccessToken } = usePrivy();
  const authStatus = useAuthStore((s) => s.status);
  const syncingRef = useRef(false);
  const [walletPending, setWalletPending] = useState(false);

  useEffect(() => {
    if (!ready || syncingRef.current) return;

    // Privy authenticated but our store is not → sync
    if (authenticated && user && authStatus !== 'authenticated') {
      const wallet = extractWalletAddress(user);
      if (!wallet) {
        setWalletPending(true);
        return;
      }
      setWalletPending(false);
      syncingRef.current = true;
      syncPrivyAuth(user, getAccessToken)
        .catch(console.error)
        .finally(() => { syncingRef.current = false; });
    }

    // Privy logged out but our store is authenticated with privy → sync logout
    if (!authenticated && authStatus === 'authenticated') {
      const method = useAuthStore.getState().authMethod;
      if (method === 'privy') {
        useAuthStore.getState().setUnauthenticated();
        clearTokens();
        tokenRefreshManager.cancel();
      }
    }
  }, [authenticated, user, ready, authStatus, getAccessToken]);

  // Wallet creation timeout (30s)
  useEffect(() => {
    if (!walletPending) return;
    const timeout = setTimeout(() => {
      setWalletPending(false);
      // Surface error to user
    }, 30_000);
    return () => clearTimeout(timeout);
  }, [walletPending]);

  return <>{children}</>;
}
```

### Privy SDK Configuration in App.tsx

Replace the current `PrivyWrapper` (App.tsx lines 26-47) with:

```typescript
import { PrivyProvider } from '@privy-io/expo';
import { PRIVY_APP_ID, SOLANA_RPC_URL } from './src/constants/config';

// In App.tsx:
<PrivyProvider
  appId={PRIVY_APP_ID}
  config={{
    loginMethods: ['google', 'apple', 'email'],
    embeddedWallets: {
      createOnLogin: 'users-without-wallets',
    },
    solanaClusters: [
      { name: 'devnet', rpcUrl: SOLANA_RPC_URL },
    ],
  }}
>
  <PrivyAuthBridge>
    {/* rest of app */}
  </PrivyAuthBridge>
</PrivyProvider>
```

### Invite Code Flow

For new users (gated alpha), the mobile login screen collects the invite code before triggering Privy login. The code is passed through the bridge:

1. User enters invite code on login screen.
2. App validates via `POST /auth/invite/validate`.
3. On success, store invite code in local state (not SecureStore -- it is ephemeral).
4. Trigger Privy social login (Google/Apple/Email).
5. In `syncPrivyAuth`, pass invite code to `POST /auth/privy/verify`.
6. Backend validates invite code during signup (auth.py line 477-501).

---

## 5. Certificate Pinning

### Recommendation: Defer to Phase 1 (P1-6)

**Rationale:**

1. Expo's managed workflow does not support native certificate pinning without a custom dev client. The app already uses `expo prebuild` (script in package.json), so a custom dev client is viable, but it adds build complexity during scaffold phase.

2. The primary MITM risk is public WiFi interception of auth tokens. With tokens in SecureStore (not cookies), the attack surface is limited to active requests.

3. The Phase 0 priority is getting auth working correctly. Pinning is a hardening measure for Phase 1.

### Phase 1 Implementation Plan

**Library:** `react-native-ssl-pinning` (or `expo-certificate-transparency` when available).

Since `expo-secure-store` already protects tokens at rest, the pinning target is the TLS connection to `api.boulderroller.org`.

**Approach: Public key pinning (not certificate pinning).**

Pin the SPKI hash of the leaf certificate's public key. This survives certificate renewals (Let's Encrypt renews every 90 days) as long as the same key pair is used.

```typescript
// Phase 1 implementation sketch
const PINNED_DOMAINS = {
  'api.boulderroller.org': {
    // SHA-256 hash of the Subject Public Key Info (SPKI)
    // Extract: openssl s_client -connect api.boulderroller.org:443 | openssl x509 -pubkey | openssl pkey -pubin -outform der | openssl dgst -sha256
    includeSubDomains: true,
    publicKeyHashes: [
      'sha256/AAAA...primary...',  // Current key
      'sha256/BBBB...backup...',   // Backup key (rotate in advance)
    ],
  },
};
```

**Key rotation procedure:** Before rotating the TLS certificate key pair, add the new key's hash to the app and ship an update. Old app versions have a 90-day grace period before the pin fails.

**Alternative for Expo managed workflow:** Use a custom `fetch` interceptor that validates the server's certificate chain against known public keys using `expo-crypto` for SHA-256 hashing. This is a pure-JS approach that works without native modules but only validates after TLS handshake (defense in depth, not true pinning).

---

## 6. Biometric Auth

### Library

`expo-local-authentication` (not yet in package.json, must be added).

### When to Require Biometrics

**v1 (Phase 0): Do not implement biometric auth.**

Rationale: The app does not yet have any financial operations on mobile. Staking, deposits, and withdrawals are web-only (per `MOBILE_DATA_CONTRACTS.md` Part 4). The mobile app is a recording device that shows points. There is no operation that requires biometric gating in v1.

**Phase 2 (when financial operations come to mobile):**

| Operation | Biometric Required | Rationale |
|-----------|-------------------|-----------|
| App open | No | Friction kills daily recording. Phone already has its own lock screen. |
| View points balance | No | Not sensitive enough. |
| View ride history | No | Not sensitive enough. |
| Start/stop recording | No | Must be frictionless for "record before coffee" UX. |
| Stake points in vault | Yes | Economic action. Irreversible during epoch. |
| Unstake / withdraw | Yes | Economic action. |
| Change wallet association | Yes | Identity-critical. |
| Export private key | Yes | Security-critical. |
| View seed phrase | Yes | Security-critical. |

### Phase 2 Implementation Sketch

```typescript
import * as LocalAuthentication from 'expo-local-authentication';

async function requireBiometric(reason: string): Promise<boolean> {
  const hasHardware = await LocalAuthentication.hasHardwareAsync();
  const isEnrolled = await LocalAuthentication.isEnrolledAsync();

  if (!hasHardware || !isEnrolled) {
    // Device doesn't support biometrics or none enrolled.
    // Fall back to device passcode (PIN/pattern).
    // Do NOT skip the gate entirely — that defeats the purpose.
    const result = await LocalAuthentication.authenticateAsync({
      promptMessage: reason,
      disableDeviceCredentialFallback: false,  // Allow PIN fallback
    });
    return result.success;
  }

  const result = await LocalAuthentication.authenticateAsync({
    promptMessage: reason,
    cancelLabel: 'Cancel',
    disableDeviceCredentialFallback: false,
  });

  return result.success;
}

// Usage:
const confirmed = await requireBiometric('Confirm stake of 500 points');
if (!confirmed) return; // User cancelled or failed
await api.stakePoints(vaultId, amount);
```

---

## 7. New Dependencies

Add to `mobile/package.json`:

```json
{
  "dependencies": {
    "zustand": "^4.5.0",
    "@tanstack/react-query": "^5.62.0"
  }
}
```

Do NOT add yet (Phase 1+):
- `react-native-ssl-pinning` (certificate pinning, Phase 1)
- `expo-local-authentication` (biometrics, Phase 2)

Both `zustand` and `@tanstack/react-query` are pure JavaScript with no native modules. They work in Expo managed workflow without `expo prebuild`.

---

## 8. Provider Hierarchy

Update `mobile/App.tsx` to establish the correct provider nesting:

```
<SafeAreaProvider>
  <QueryClientProvider client={queryClient}>
    <PrivyProvider appId={PRIVY_APP_ID} config={...}>
      <PrivyAuthBridge>
        <AuthInitializer>
          <NavigationContainer>
            <StatusBar style="light" />
            <RootNavigator />
          </NavigationContainer>
        </AuthInitializer>
      </PrivyAuthBridge>
    </PrivyProvider>
  </QueryClientProvider>
</SafeAreaProvider>
```

**Provider responsibilities:**

| Provider | What it does |
|----------|-------------|
| `SafeAreaProvider` | Device inset measurements |
| `QueryClientProvider` | TanStack Query cache + client |
| `PrivyProvider` | Privy SDK initialization |
| `PrivyAuthBridge` | Syncs Privy auth → our backend → Zustand |
| `AuthInitializer` | On mount: hydrate Zustand from SecureStore, start refresh timer |
| `NavigationContainer` | React Navigation root |
| `RootNavigator` | Reads `useAuthStore` to render `AuthStack` or `TabNavigator` |

### AuthInitializer Component

```typescript
function AuthInitializer({ children }: { children: React.ReactNode }) {
  const [initialized, setInitialized] = useState(false);

  useEffect(() => {
    initializeAuth().finally(() => setInitialized(true));
  }, []);

  // Show splash/loading screen until auth state is resolved
  if (!initialized) {
    return <SplashScreen />;  // Or ActivityIndicator
  }

  return <>{children}</>;
}
```

### RootNavigator

```typescript
function RootNavigator() {
  const status = useAuthStore((s) => s.status);

  if (status === 'loading') {
    return <SplashScreen />;
  }

  if (status === 'unauthenticated') {
    return <AuthStack />;  // Login screen, invite code screen
  }

  // 'authenticated' or 'refreshing' — show the app
  // 'refreshing' still shows the app (don't flash login screen during refresh)
  return <TabNavigator />;
}
```

---

## 9. File Manifest

### New Files to Create

| File | Purpose |
|------|---------|
| `mobile/src/services/secureStorage.ts` | SecureStore wrapper (Section 2) |
| `mobile/src/services/authService.ts` | Auth lifecycle orchestration (Section 3.3) |
| `mobile/src/services/tokenRefreshManager.ts` | Proactive refresh timer (Section 3.4) |
| `mobile/src/services/privyBridge.ts` | Privy → backend JWT bridge logic (Section 4) |
| `mobile/src/stores/authStore.ts` | Zustand auth store (Section 3.1) |
| `mobile/src/lib/queryClient.ts` | TanStack Query client config (Section 3.2) |
| `mobile/src/components/PrivyAuthBridge.tsx` | React component wrapping Privy sync (Section 4) |
| `mobile/src/components/AuthInitializer.tsx` | Hydrates auth on mount (Section 8) |
| `mobile/src/navigation/RootNavigator.tsx` | Auth-gated navigation root (Section 8) |
| `mobile/src/navigation/AuthStack.tsx` | Login/invite screens stack (Section 8) |
| `mobile/src/screens/LoginScreen.tsx` | Privy login + invite code entry |
| `mobile/src/lib/jwtUtils.ts` | `parseJwtExpiry()` helper |

### Files to Modify

| File | Change |
|------|--------|
| `mobile/App.tsx` | Replace PrivyWrapper with full provider hierarchy (Section 8) |
| `mobile/src/lib/api.ts` | Remove in-memory tokens, read from Zustand, add 401 refresh retry (Section 3.5) |
| `mobile/src/constants/config.ts` | Set real Privy app ID `cmjp145cl008xl70clr2ho821` (line 14) |
| `mobile/package.json` | Add `zustand`, `@tanstack/react-query` (Section 7) |
| `backend/app/routes/auth.py` | Add body/header fallback for refresh token (Section 1, lines 613 and 727) |
| `backend/app/schemas.py` | Restore `refresh_token` field description (Section 1, line 95-99) |

### Files NOT to Create

- No `AuthContext.tsx` — Zustand replaces React Context for auth state.
- No `TokenProvider.tsx` — token management is a service, not a provider.
- No certificate pinning files — deferred to Phase 1.
- No biometric auth files — deferred to Phase 2.

---

## Appendix: JWT Expiry Parsing

The access token is a standard JWT. The `exp` claim is a Unix timestamp in seconds.

```typescript
// mobile/src/lib/jwtUtils.ts

export function parseJwtExpiry(token: string): number {
  try {
    const payload = JSON.parse(atob(token.split('.')[1]));
    if (typeof payload.exp === 'number') {
      return payload.exp * 1000; // Convert to milliseconds
    }
  } catch {
    // Invalid JWT format
  }
  // Fallback: assume 15 minutes from now
  return Date.now() + 15 * 60 * 1000;
}
```

Note: `atob` is available in React Native's Hermes engine (Expo SDK 52+). If not available, use a base64 polyfill or `Buffer.from(str, 'base64').toString()` from the `buffer` package.

---

## Appendix: Sequence Diagram — Full Login Flow

```
User                 Mobile App              Privy SDK           Backend
  |                      |                      |                   |
  |  tap "Sign in"       |                      |                   |
  |--------------------->|                      |                   |
  |                      |  login()             |                   |
  |                      |--------------------->|                   |
  |                      |                      |                   |
  |  <Google/Apple UI>   |                      |                   |
  |<---------------------|                      |                   |
  |                      |                      |                   |
  |  authenticate        |                      |                   |
  |--------------------->|                      |                   |
  |                      |  onAuth callback     |                   |
  |                      |<---------------------|                   |
  |                      |                      |                   |
  |                      |  getAccessToken()    |                   |
  |                      |--------------------->|                   |
  |                      |  privyToken          |                   |
  |                      |<---------------------|                   |
  |                      |                      |                   |
  |                      |  POST /auth/privy/verify                 |
  |                      |  { wallet, privyToken, deviceId }        |
  |                      |----------------------------------------->|
  |                      |                      |                   |
  |                      |  { accessToken, refreshToken, wallet }   |
  |                      |<-----------------------------------------|
  |                      |                      |                   |
  |                      |  SecureStore.set(tokens)                 |
  |                      |  authStore.setAuthenticated()            |
  |                      |  tokenRefreshManager.schedule()          |
  |                      |                      |                   |
  |  [TabNavigator]      |                      |                   |
  |<---------------------|                      |                   |
```
