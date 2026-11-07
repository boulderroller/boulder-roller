/**
 * Auth Lifecycle Service
 *
 * Orchestrates the full auth lifecycle:
 *   - initializeAuth(): Hydrate Zustand from SecureStore on app startup
 *   - attemptRefresh(): Refresh expired access tokens
 *   - login(): Privy and wallet login flows
 *   - logout(): Clear all auth state
 *
 * Bridges SecureStore (persistence), Zustand (reactive state),
 * and the API client (network).
 */

import { useAuthStore } from '../stores/authStore';
import { parseJwtExpiry } from '../lib/jwtUtils';
import { api, setApiRefreshHandler } from '../lib/api';
import { tokenRefreshManager, setRefreshHandler } from './tokenRefreshManager';
import {
  getAccessToken,
  getRefreshToken,
  getTokenExpiresAt,
  getStoredWallet,
  getStoredAuthMethod,
  getDeviceId,
  storeTokens,
  clearTokens,
} from './secureStorage';
import { signWalletAuthMessage } from './wallet/mwaWallet';
import { suspendRecordingForAccountBoundary } from './gpsRecording';

const STARTUP_REFRESH_TIMEOUT_MS = 8_000;
const STARTUP_SESSION_VALIDATION_TIMEOUT_MS = 8_000;

function withTimeout<T>(promise: Promise<T>, timeoutMs: number, label: string): Promise<T> {
  return new Promise((resolve, reject) => {
    const timeout = setTimeout(() => {
      reject(new Error(`${label} timed out after ${timeoutMs}ms`));
    }, timeoutMs);

    promise
      .then(resolve, reject)
      .finally(() => clearTimeout(timeout));
  });
}

async function validateStoredSessionInBackground(): Promise<void> {
  try {
    await withTimeout(
      api.getMe(),
      STARTUP_SESSION_VALIDATION_TIMEOUT_MS,
      'Stored session validation',
    );
  } catch (err) {
    console.warn(
      '[auth] Stored session validation skipped:',
      err instanceof Error ? err.message : err,
    );
  }
}

/**
 * Attempt to refresh the access token using the stored refresh token.
 * On success: updates SecureStore + Zustand.
 * On failure: clears everything, user must re-login.
 */
export async function attemptRefresh(): Promise<boolean> {
  useAuthStore.getState().setRefreshing();

  const refreshToken = await getRefreshToken();
  const deviceId = await getDeviceId();

  if (!refreshToken) {
    await suspendRecordingForAccountBoundary();
    useAuthStore.getState().setUnauthenticated();
    await clearTokens();
    return false;
  }

  try {
    const result = await withTimeout(
      api.refreshTokens(refreshToken, deviceId),
      STARTUP_REFRESH_TIMEOUT_MS,
      'Token refresh',
    );
    const expiresAtMs = parseJwtExpiry(result.accessToken);
    const authMethod = (await getStoredAuthMethod()) ?? 'wallet';

    await storeTokens({
      accessToken: result.accessToken,
      refreshToken: result.refreshToken,
      expiresAtMs,
      wallet: result.wallet,
      authMethod,
    });

    useAuthStore.getState().setAuthenticated({
      accessToken: result.accessToken,
      tokenExpiresAt: expiresAtMs,
      wallet: result.wallet,
      authMethod,
    });

    return true;
  } catch {
    await suspendRecordingForAccountBoundary();
    useAuthStore.getState().setUnauthenticated();
    await clearTokens();
    return false;
  }
}

// Wire the refresh handler into the token refresh manager
setRefreshHandler(attemptRefresh);

// Wire the refresh handler into the API client for 401 auto-retry
setApiRefreshHandler(() => tokenRefreshManager.refresh());

/**
 * Called once on app startup (in AuthInitializer).
 * Hydrates Zustand from SecureStore and validates the session.
 */
export async function initializeAuth(): Promise<void> {
  // 1. Read tokens from SecureStore
  const [accessToken, refreshToken, expiresAt, wallet, authMethod] = await Promise.all([
    getAccessToken(),
    getRefreshToken(),
    getTokenExpiresAt(),
    getStoredWallet(),
    getStoredAuthMethod(),
  ]);

  // 2. No stored tokens -> unauthenticated
  if (!accessToken || !refreshToken || !wallet) {
    await suspendRecordingForAccountBoundary();
    useAuthStore.getState().setUnauthenticated();
    return;
  }

  // 3. Access token not expired -> hydrate store
  const now = Date.now();
  if (expiresAt && expiresAt > now + 60_000) {
    // Token still valid (with 1-min buffer)
    useAuthStore.getState().setAuthenticated({
      accessToken,
      tokenExpiresAt: expiresAt,
      wallet,
      authMethod: authMethod ?? 'wallet',
    });

    // Start proactive refresh timer
    tokenRefreshManager.schedule();

    // Background: validate session is still good server-side without
    // blocking app launch on weak or captive mobile networks. The API
    // client still handles a 401 by attempting refresh and clearing auth
    // only when the refresh path truly fails.
    void validateStoredSessionInBackground();
    return;
  }

  // 4. Access token expired -> attempt refresh
  const refreshed = await attemptRefresh();
  if (refreshed) {
    tokenRefreshManager.schedule();
  }
}

/**
 * Authenticate with an external Solana wallet through Mobile Wallet Adapter.
 * This is the mobile SIWS path matching portal wallet login.
 */
export async function loginWithExternalWallet(inviteCode?: string): Promise<void> {
  useAuthStore.getState().setLoading();

  try {
    const deviceId = await getDeviceId();
    const signed = await signWalletAuthMessage((wallet) => api.getNonce(wallet, deviceId));
    const result = await api.verifySignature(
      signed.signer,
      signed.signature,
      signed.nonce,
      deviceId,
      inviteCode,
    );
    const expiresAtMs = parseJwtExpiry(result.accessToken);

    await storeTokens({
      accessToken: result.accessToken,
      refreshToken: result.refreshToken,
      expiresAtMs,
      wallet: result.wallet,
      authMethod: 'wallet',
    });

    useAuthStore.getState().setAuthenticated({
      accessToken: result.accessToken,
      tokenExpiresAt: expiresAtMs,
      wallet: result.wallet,
      authMethod: 'wallet',
    });

    tokenRefreshManager.schedule();
  } catch (err) {
    await suspendRecordingForAccountBoundary();
    useAuthStore.getState().setUnauthenticated();
    throw err;
  }
}

/**
 * Full logout: clear tokens, cancel refresh timer, call backend logout.
 */
export async function logout(): Promise<void> {
  tokenRefreshManager.cancel();

  // Flush under the departing account's owner key, then synchronously clear
  // live route state before another account can authenticate on this device.
  await suspendRecordingForAccountBoundary();

  try {
    const refreshToken = await getRefreshToken();
    const deviceId = await getDeviceId();
    await api.logout(refreshToken, deviceId);
  } catch {
    // Force clear even on error
  }

  await clearTokens();
  useAuthStore.getState().setUnauthenticated();
}
