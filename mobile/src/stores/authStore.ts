/**
 * Auth State Store (Zustand)
 *
 * Four states: loading -> unauthenticated -> authenticated -> refreshing
 *
 * Zustand is used instead of React Context because navigation guards
 * must read auth state synchronously via getState(). TanStack Query
 * cannot provide this because useQuery is inherently async.
 *
 * No Zustand persist middleware — expo-secure-store is async and the
 * persist middleware expects synchronous storage. Instead, we manually
 * hydrate from SecureStore on app startup via authService.initializeAuth().
 */

import { create } from 'zustand';
import {
  authAccessMethodFromBackend,
  type AuthAccessMethod,
  type BackendAuthMethod,
} from '../lib/authState';

export type AuthStatus = 'loading' | 'unauthenticated' | 'authenticated' | 'refreshing';
export type AuthRecovery = 'invite_required' | 'invite_invalid';

interface AuthState {
  status: AuthStatus;
  wallet: string | null;
  authMethod: BackendAuthMethod | null;
  accessMethod: AuthAccessMethod | null;
  accessToken: string | null;
  tokenExpiresAt: number | null; // epoch ms
  pendingInviteCode: string | null;
  sessionExchangeRequested: boolean;
  authError: string | null;
  authRecovery: AuthRecovery | null;

  // Actions
  setAuthenticated: (params: {
    accessToken: string;
    tokenExpiresAt: number;
    wallet: string;
    authMethod: BackendAuthMethod;
  }) => void;
  setRefreshing: () => void;
  setUnauthenticated: () => void;
  setLoading: () => void;
  setPendingInviteCode: (inviteCode: string) => void;
  clearPendingInviteCode: () => void;
  requestSessionExchange: () => void;
  clearSessionExchangeRequest: () => void;
  setAuthError: (message: string, recovery?: AuthRecovery) => void;
  clearAuthError: () => void;
}

export const useAuthStore = create<AuthState>((set) => ({
  status: 'loading',
  wallet: null,
  authMethod: null,
  accessMethod: null,
  accessToken: null,
  tokenExpiresAt: null,
  pendingInviteCode: null,
  sessionExchangeRequested: false,
  authError: null,
  authRecovery: null,

  setAuthenticated: (params) =>
    set({
      status: 'authenticated',
      accessToken: params.accessToken,
      tokenExpiresAt: params.tokenExpiresAt,
      wallet: params.wallet,
      authMethod: params.authMethod,
      accessMethod: authAccessMethodFromBackend(params.authMethod),
      pendingInviteCode: null,
      sessionExchangeRequested: false,
      authError: null,
      authRecovery: null,
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
      accessMethod: null,
      accessToken: null,
      tokenExpiresAt: null,
      pendingInviteCode: null,
      sessionExchangeRequested: false,
      authError: null,
      authRecovery: null,
    }),

  setLoading: () =>
    set((state) => ({
      ...state,
      status: 'loading',
      sessionExchangeRequested: false,
      authError: null,
      authRecovery: null,
    })),

  setPendingInviteCode: (inviteCode) =>
    set({
      pendingInviteCode: inviteCode.trim(),
      authError: null,
      authRecovery: null,
    }),

  clearPendingInviteCode: () =>
    set({
      pendingInviteCode: null,
    }),

  requestSessionExchange: () =>
    set({
      sessionExchangeRequested: true,
      authError: null,
      authRecovery: null,
    }),

  clearSessionExchangeRequest: () =>
    set({
      sessionExchangeRequested: false,
    }),

  setAuthError: (message, recovery = undefined) =>
    set({
      authError: message,
      authRecovery: recovery ?? null,
    }),

  clearAuthError: () =>
    set({
      authError: null,
      authRecovery: null,
    }),
}));

/**
 * Stable account namespace for encrypted, device-local ride data.
 *
 * Solana addresses are case-sensitive, so the wallet bytes are preserved
 * exactly after trimming transport whitespace. Prefixing the key makes the
 * persisted format explicit and leaves room for another stable backend user
 * identifier without silently colliding with historical wallet ownership.
 */
export function localRideOwnerKeyForWallet(
  wallet: string | null | undefined,
): string | null {
  if (typeof wallet !== 'string') return null;
  const stableWallet = wallet.trim();
  return stableWallet ? `wallet:${stableWallet}` : null;
}

/**
 * Return the owner allowed to access local rides in the current auth state.
 * Loading, logged-out, and malformed sessions deliberately resolve to null;
 * SQLite equality against null matches neither owned nor legacy-null rows.
 */
export function getCurrentLocalRideOwnerKey(): string | null {
  const { status, wallet } = useAuthStore.getState();
  if (status !== 'authenticated' && status !== 'refreshing') return null;
  return localRideOwnerKeyForWallet(wallet);
}

/** New local rides must never be created without a stable account owner. */
export function requireCurrentLocalRideOwnerKey(): string {
  const ownerKey = getCurrentLocalRideOwnerKey();
  if (!ownerKey) {
    throw new Error('Authenticated rider identity unavailable for local ride');
  }
  return ownerKey;
}
