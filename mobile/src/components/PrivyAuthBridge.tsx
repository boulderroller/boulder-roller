/**
 * PrivyAuthBridge
 *
 * Drives the Privy → backend JWT handoff. Three steps:
 *
 *   1. Wait for `usePrivy().user !== null` (email OTP completed).
 *   2. Ensure an embedded Solana wallet exists. If `useEmbeddedSolanaWallet()`
 *      reports `not-created`, call `create()` to trigger Privy's wallet-creation
 *      flow (opens an in-app webview). If it fails or times out, log out of
 *      Privy so the user can retry from a clean slate.
 *   3. Once the wallet is `connected`, exchange the Privy access token for our
 *      backend JWT via `syncPrivyAuth`, persist tokens, hydrate Zustand.
 *
 * The Expo SDK does NOT populate `user.linked_accounts` with the embedded
 * wallet reliably — the wallet only shows up through the
 * `useEmbeddedSolanaWallet` hook. That's why we drive creation/address
 * extraction from the hook rather than from `user`.
 */

import React, { useEffect, useRef } from 'react';
import { usePrivy, useEmbeddedSolanaWallet } from '@privy-io/expo';

import { useAuthStore } from '../stores/authStore';
import { syncPrivyAuth } from '../services/privyBridge';

const WALLET_CREATION_TIMEOUT_MS = 60_000;

interface PrivyAuthBridgeProps {
  children: React.ReactNode;
}

const debugLog = (...args: unknown[]) => {
  if (__DEV__) console.warn(...args);
};

export function getPrivySyncFailureState(error: unknown): {
  message: string;
  clearInvite: boolean;
  recovery?: 'invite_required' | 'invite_invalid';
  shouldLogout: boolean;
} {
  const rawMessage = error instanceof Error ? error.message : String(error);
  if (rawMessage.includes('invite_required')) {
    return {
      message: 'Invite required.',
      clearInvite: true,
      recovery: 'invite_required',
      shouldLogout: false,
    };
  }
  if (rawMessage.includes('invite_invalid')) {
    return {
      message: 'That invite is not active.',
      clearInvite: true,
      recovery: 'invite_invalid',
      shouldLogout: false,
    };
  }
  if (rawMessage.includes('Network error') || rawMessage.includes('timeout')) {
    return {
      message: 'Connection issue.',
      clearInvite: false,
      shouldLogout: true,
    };
  }
  if (rawMessage.includes('server_error') || rawMessage.includes('API error 5')) {
    return {
      message: 'Try again in a moment.',
      clearInvite: false,
      shouldLogout: true,
    };
  }
  return {
    message: "Couldn't finish sign-in.",
    clearInvite: false,
    shouldLogout: true,
  };
}

export default function PrivyAuthBridge({ children }: PrivyAuthBridgeProps) {
  const { user, isReady, getAccessToken, logout } = usePrivy();
  const solanaWallet = useEmbeddedSolanaWallet();
  const authStatus = useAuthStore((s) => s.status);
  const pendingInviteCode = useAuthStore((s) => s.pendingInviteCode);
  const sessionExchangeRequested = useAuthStore((s) => s.sessionExchangeRequested);

  const syncingRef = useRef(false);
  const syncFailedRef = useRef(false);
  const createCalledRef = useRef(false);
  const timeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const privyAuthenticated = isReady && user !== null;

  // Clear any pending timeout on unmount
  useEffect(() => {
    return () => {
      if (timeoutRef.current) clearTimeout(timeoutRef.current);
    };
  }, []);

  // Step 1 & 2: drive embedded wallet creation when Privy is authenticated
  useEffect(() => {
    if (!isReady || !privyAuthenticated || !sessionExchangeRequested || authStatus === 'authenticated') {
      return;
    }

    const status = solanaWallet.status;
    debugLog('[PrivyAuthBridge] Privy user ready. solanaWallet.status=', status);

    if (status === 'not-created') {
      if (createCalledRef.current) return;
      createCalledRef.current = true;
      debugLog('[PrivyAuthBridge] Wallet not created — calling solanaWallet.create()');

      // Safety timeout: if creation never resolves, log out
      timeoutRef.current = setTimeout(async () => {
        debugLog('[PrivyAuthBridge] Wallet creation timed out — logging out');
        try {
          await logout();
        } catch (err) {
          debugLog('[PrivyAuthBridge] logout after timeout failed:', err);
        }
      }, WALLET_CREATION_TIMEOUT_MS);

      solanaWallet
        .create?.()
        .then((provider) => {
          debugLog('[PrivyAuthBridge] solanaWallet.create() resolved:', provider ? 'provider' : 'null');
        })
        .catch(async (err) => {
          debugLog('[PrivyAuthBridge] solanaWallet.create() FAILED:', err?.message ?? err);
          if (timeoutRef.current) clearTimeout(timeoutRef.current);
          try {
            await logout();
          } catch (_) { /* ignore */ }
        });
    }
  }, [isReady, privyAuthenticated, sessionExchangeRequested, authStatus, solanaWallet.status, solanaWallet, logout]);

  // Step 3: once wallet is connected, exchange Privy token for backend JWT
  useEffect(() => {
    if (!isReady || !privyAuthenticated || !sessionExchangeRequested || authStatus === 'authenticated') {
      return;
    }
    if (syncingRef.current) return;
    if (syncFailedRef.current) return;
    if (solanaWallet.status !== 'connected') return;

    const wallets = solanaWallet.wallets;
    if (!wallets || wallets.length === 0) {
      debugLog('[PrivyAuthBridge] Wallet connected but wallets array empty');
      return;
    }
    const address = wallets[0].address;
    debugLog('[PrivyAuthBridge] Wallet connected:', address, '— starting backend sync');

    if (timeoutRef.current) {
      clearTimeout(timeoutRef.current);
      timeoutRef.current = null;
    }

    syncingRef.current = true;
    syncPrivyAuth(user!, getAccessToken, pendingInviteCode ?? undefined, address)
      .then(() => {
        useAuthStore.getState().clearPendingInviteCode();
        useAuthStore.getState().clearSessionExchangeRequest();
        useAuthStore.getState().clearAuthError();
        debugLog('[PrivyAuthBridge] Backend sync succeeded');
      })
      .catch(async (err) => {
        const failure = getPrivySyncFailureState(err);
        syncFailedRef.current = failure.shouldLogout;
        if (failure.clearInvite) {
          useAuthStore.getState().clearPendingInviteCode();
        }
        useAuthStore.getState().clearSessionExchangeRequest();
        useAuthStore.getState().setAuthError(failure.message, failure.recovery);
        debugLog(
          failure.shouldLogout
            ? '[PrivyAuthBridge] Backend sync FAILED — logging out to recover:'
            : '[PrivyAuthBridge] Backend sync needs rider recovery:',
          err?.message ?? err,
        );
        if (failure.shouldLogout) {
          try {
            await logout();
          } catch (_) { /* ignore */ }
        }
      })
      .finally(() => {
        syncingRef.current = false;
      });
  }, [isReady, privyAuthenticated, sessionExchangeRequested, authStatus, solanaWallet.status, solanaWallet.wallets, user, getAccessToken, logout, pendingInviteCode]);

  // Reset transient Privy bridge guards once the provider session is gone.
  useEffect(() => {
    if (!isReady) return;
    if (!privyAuthenticated) {
      createCalledRef.current = false;
      syncFailedRef.current = false;
    }
  }, [privyAuthenticated, isReady]);

  return <>{children}</>;
}
