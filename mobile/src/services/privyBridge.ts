/**
 * Privy Auth Bridge Logic
 *
 * Bridges Privy authentication to our backend JWT system.
 * When Privy reports a successful login, this service:
 *   1. Extracts the wallet address from the Privy user
 *   2. Gets a Privy access token
 *   3. Exchanges it for our backend JWT via POST /auth/privy/verify
 *   4. Persists tokens in SecureStore
 *   5. Hydrates the Zustand auth store
 *   6. Starts the proactive refresh timer
 */

import type { User as PrivyUser, LinkedAccount } from '@privy-io/expo';

import { useAuthStore } from '../stores/authStore';
import { parseJwtExpiry } from '../lib/jwtUtils';
import { api } from '../lib/api';
import { tokenRefreshManager } from './tokenRefreshManager';
import { storeTokens, getDeviceId } from './secureStorage';

export type { PrivyUser };

/**
 * Extract wallet address from a Privy user object.
 * Prefers the embedded Solana wallet (created by Privy for social login users).
 * Falls back to any linked Solana wallet.
 */
export function extractWalletAddress(user: PrivyUser): string | null {
  const accounts = user.linked_accounts;
  if (!accounts) return null;

  // 1. Prefer embedded Solana wallet (created by Privy for social login users)
  const embedded = accounts.find(
    (a: LinkedAccount) =>
      a.type === 'wallet' &&
      'wallet_client_type' in a &&
      a.wallet_client_type === 'privy' &&
      'chain_type' in a &&
      a.chain_type === 'solana'
  );
  if (embedded && 'address' in embedded) return embedded.address;

  // 2. Fall back to any linked Solana wallet
  const anyWallet = accounts.find(
    (a: LinkedAccount) =>
      a.type === 'wallet' &&
      'chain_type' in a &&
      a.chain_type === 'solana'
  );
  if (anyWallet && 'address' in anyWallet) return anyWallet.address;

  return null;
}

/**
 * Retry getting the Privy access token with exponential backoff.
 * Privy sometimes needs a moment after authentication before the
 * token is available.
 */
async function getAccessTokenWithRetry(
  getAccessToken: () => Promise<string | null>,
  maxRetries: number,
  delayMs: number,
): Promise<string | null> {
  for (let i = 0; i < maxRetries; i++) {
    const token = await getAccessToken();
    if (token) return token;
    if (i < maxRetries - 1) {
      await new Promise((resolve) => setTimeout(resolve, delayMs * (i + 1)));
    }
  }
  return null;
}

/**
 * Called when Privy reports authentication.
 * Bridges Privy session -> our backend JWT -> SecureStore -> Zustand.
 */
export async function syncPrivyAuth(
  privyUser: PrivyUser,
  getAccessToken: () => Promise<string | null>,
  inviteCode?: string,
  walletOverride?: string,
): Promise<void> {
  // 1. Resolve wallet address — prefer explicit override (from embedded wallet hook),
  //    fall back to scanning linked_accounts
  const wallet = walletOverride ?? extractWalletAddress(privyUser);
  if (!wallet) {
    throw new Error('No wallet address found in Privy user');
  }

  // 2. Get Privy access token with retry
  const privyToken = await getAccessTokenWithRetry(getAccessToken, 3, 1000);
  if (!privyToken) {
    throw new Error('Failed to get Privy access token');
  }

  // 3. Exchange Privy token for our JWT
  const deviceId = await getDeviceId();
  const result = await api.verifyPrivyToken(wallet, privyToken, deviceId, inviteCode);

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
