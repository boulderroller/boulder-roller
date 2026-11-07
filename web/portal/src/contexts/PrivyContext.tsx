/**
 * PrivyContext - Privy SDK provider and auth bridge
 *
 * Wraps the app with Privy for social login (Google, Apple, Email)
 * and embedded wallets. Bridges Privy auth state to our AuthContext.
 */

import {
  ReactNode,
  useCallback,
  useEffect,
  useRef,
  useState,
  createContext,
  useContext,
  useSyncExternalStore,
} from 'react';
import { PrivyProvider as BasePrivyProvider, useLoginWithEmail, usePrivy } from '@privy-io/react-auth';
import { useAuth } from './AuthContext';
import { clearPendingInviteCode, getPendingInviteCode } from '../lib/authHandoff';
import { getPrivySyncFailureState, type PrivySyncRecovery } from '../lib/privySyncRecovery';

// Privy App ID from environment
const PRIVY_APP_ID = import.meta.env.VITE_PRIVY_APP_ID || '';
const PRIVY_E2E_MOCK = import.meta.env.VITE_PRIVY_E2E_MOCK === 'true';
const E2E_MOCK_WALLET = 'e2ePrivyWallet11111111111111111111111111111';

type E2EEmailStatus = 'initial' | 'sending-code' | 'awaiting-code-input' | 'submitting-code' | 'done';

interface E2EPrivySnapshot {
  authenticated: boolean;
  emailStatus: E2EEmailStatus;
  syncError: string | null;
  syncRecovery: PrivySyncRecovery;
  syncRequested: boolean;
  syncing: boolean;
  walletPending: boolean;
}

const initialE2EPrivySnapshot: E2EPrivySnapshot = {
  authenticated: false,
  emailStatus: 'initial',
  syncError: null,
  syncRecovery: null,
  syncRequested: false,
  syncing: false,
  walletPending: false,
};

let e2ePrivySnapshot = initialE2EPrivySnapshot;
const e2ePrivyListeners = new Set<() => void>();

function getE2EPrivySnapshot() {
  return e2ePrivySnapshot;
}

function updateE2EPrivySnapshot(patch: Partial<E2EPrivySnapshot>) {
  e2ePrivySnapshot = { ...e2ePrivySnapshot, ...patch };
  e2ePrivyListeners.forEach((listener) => listener());
}

function useE2EPrivySnapshot() {
  return useSyncExternalStore(
    (listener) => {
      e2ePrivyListeners.add(listener);
      return () => e2ePrivyListeners.delete(listener);
    },
    getE2EPrivySnapshot,
    getE2EPrivySnapshot,
  );
}

function isE2EPrivyBridgeEnabled() {
  if (typeof window === 'undefined') return false;
  return Boolean((window as Window & { __brE2ESimulatePrivyBridge?: boolean })
    .__brE2ESimulatePrivyBridge);
}

// Context for sharing Privy bridge state (wallet pending, sync errors)
interface PrivyBridgeState {
  walletPending: boolean;
  syncError: string | null;
  syncRecovery: PrivySyncRecovery;
  retrySync: () => void;
  resetSyncError: () => void;
}

const PrivyBridgeContext = createContext<PrivyBridgeState>({
  walletPending: false,
  syncError: null,
  syncRecovery: null,
  retrySync: () => {},
  resetSyncError: () => {},
});

export interface PrivySolanaBridgeState {
  enabled: boolean;
  ready: boolean;
  signPreparedTransaction: (preparedTransaction: string, walletAddress: string, chain: string) => Promise<string>;
}

const defaultPrivySolanaBridgeState: PrivySolanaBridgeState = {
  enabled: false,
  ready: false,
  signPreparedTransaction: async () => {
    throw new Error('Embedded wallet signing is unavailable in this environment.');
  },
};

export const PrivySolanaBridgeContext = createContext<PrivySolanaBridgeState>(defaultPrivySolanaBridgeState);

// Retry configuration for token acquisition
const TOKEN_RETRY_ATTEMPTS = 3;
const TOKEN_RETRY_DELAY_MS = 1000;

// Wallet creation timeout (30 seconds)
const WALLET_CREATION_TIMEOUT_MS = 30000;
interface PrivyProviderProps {
  children: ReactNode;
}

function extractPrivyWalletAddress(user: unknown): string | null {
  if (!user || typeof user !== 'object') return null;

  const userRecord = user as Record<string, unknown>;
  const linkedAccounts = Array.isArray(userRecord.linkedAccounts)
    ? userRecord.linkedAccounts
    : [];

  const extractAddress = (account: unknown): string | null => {
    if (!account || typeof account !== 'object') return null;
    const record = account as Record<string, unknown>;
    return typeof record.address === 'string' ? record.address : null;
  };

  const embedded = linkedAccounts.find((account) => {
    if (!account || typeof account !== 'object') return false;
    const record = account as Record<string, unknown>;
    return record.type === 'wallet' && record.walletClientType === 'privy' && typeof record.address === 'string';
  });
  const embeddedAddress = extractAddress(embedded);
  if (embeddedAddress) return embeddedAddress;

  const firstWallet = linkedAccounts.find((account) => {
    if (!account || typeof account !== 'object') return false;
    const record = account as Record<string, unknown>;
    return record.type === 'wallet' && typeof record.address === 'string';
  });
  const firstWalletAddress = extractAddress(firstWallet);
  if (firstWalletAddress) return firstWalletAddress;

  const wallet = userRecord.wallet;
  if (wallet && typeof wallet === 'object') {
    const walletRecord = wallet as Record<string, unknown>;
    if (typeof walletRecord.address === 'string') {
      return walletRecord.address;
    }
  }

  return null;
}

function E2EPrivyAuthBridge({ children }: { children: ReactNode }) {
  const snapshot = useE2EPrivySnapshot();
  const { loginWithPrivy } = useAuth();

  useEffect(() => {
    if (!snapshot.authenticated || !snapshot.syncRequested || snapshot.syncing) return;

    updateE2EPrivySnapshot({
      syncError: null,
      syncRecovery: null,
      syncing: true,
      walletPending: false,
    });

    void loginWithPrivy(
      E2E_MOCK_WALLET,
      'e2e-provider-access-token',
      getPendingInviteCode() ?? undefined,
    ).then(() => {
      updateE2EPrivySnapshot({
        syncError: null,
        syncRecovery: null,
        syncRequested: false,
        syncing: false,
      });
    }).catch((error) => {
      const failure = getPrivySyncFailureState(error);
      if (failure.clearInvite) {
        clearPendingInviteCode();
      }
      updateE2EPrivySnapshot({
        authenticated: failure.shouldLogout ? false : e2ePrivySnapshot.authenticated,
        syncError: failure.message,
        syncRecovery: failure.recovery,
        syncRequested: false,
        syncing: false,
      });
    });

  }, [loginWithPrivy, snapshot.authenticated, snapshot.syncRequested, snapshot.syncing]);

  return <>{children}</>;
}

/**
 * PrivyAuthBridge - Syncs Privy authentication with our AuthContext
 */
function PrivyAuthBridge({ children }: { children: ReactNode }) {
  const { authenticated, user: privyUser, logout: privyLogout, ready, getAccessToken } = usePrivy();
  const { isAuthenticated, logout: authLogout, loginWithPrivy, authMethod } = useAuth();
  const syncingRef = useRef(false);
  const backendPrivySessionRef = useRef(false);
  const [syncError, setSyncError] = useState<string | null>(null);
  const [syncRecovery, setSyncRecovery] = useState<PrivyBridgeState['syncRecovery']>(null);
  const [syncAttempt, setSyncAttempt] = useState(0);
  const [syncRequested, setSyncRequested] = useState(false);
  const [walletPending, setWalletPending] = useState(false);

  const walletAddress = extractPrivyWalletAddress(privyUser);

  const resetSyncError = useCallback(() => {
    setSyncError(null);
    setSyncRecovery(null);
  }, []);

  const retrySync = useCallback(() => {
    setSyncError(null);
    setSyncRecovery(null);
    setSyncRequested(true);
    setSyncAttempt((attempt) => attempt + 1);
  }, []);

  // Retry helper for token acquisition with exponential backoff
  const getAccessTokenWithRetry = useCallback(async (): Promise<string | null> => {
    for (let attempt = 0; attempt < TOKEN_RETRY_ATTEMPTS; attempt++) {
      try {
        const token = await getAccessToken();
        if (token) {
          return token;
        }
        // Token was null, wait and retry
        if (attempt < TOKEN_RETRY_ATTEMPTS - 1) {
          await new Promise((resolve) => setTimeout(resolve, TOKEN_RETRY_DELAY_MS * (attempt + 1)));
        }
      } catch (err) {
        console.warn(`getAccessToken attempt ${attempt + 1} failed:`, err);
        if (attempt < TOKEN_RETRY_ATTEMPTS - 1) {
          await new Promise((resolve) => setTimeout(resolve, TOKEN_RETRY_DELAY_MS * (attempt + 1)));
        }
      }
    }
    return null;
  }, [getAccessToken]);

  // Sync Privy auth state to our AuthContext
  useEffect(() => {
    if (!ready || syncingRef.current) return;

    const syncAuth = async () => {
      if (authenticated && privyUser && !isAuthenticated && syncRequested) {
        if (!walletAddress) {
          setWalletPending(true);
          return;
        }

        setWalletPending(false);
        setSyncError(null);
        syncingRef.current = true;

        try {
          // Get Privy access token with retry logic
          const privyToken = await getAccessTokenWithRetry();

          if (privyToken) {
            const inviteCode = getPendingInviteCode() ?? undefined;
            await loginWithPrivy(walletAddress, privyToken, inviteCode);
            setSyncError(null);
            setSyncRecovery(null);
            setSyncRequested(false);
          } else {
            setSyncError('Could not verify email login. Try again.');
            setSyncRecovery(null);
            setSyncRequested(false);
            await privyLogout();
          }
        } catch (err) {
          const failure = getPrivySyncFailureState(err);
          if (failure.clearInvite) {
            clearPendingInviteCode();
          }
          setSyncError(failure.message);
          setSyncRecovery(failure.recovery);
          setSyncRequested(false);
          if (failure.shouldLogout) {
            await privyLogout();
          }
        } finally {
          syncingRef.current = false;
        }
      } else if (!authenticated && isAuthenticated && authMethod === 'privy') {
        // User logged out of Privy, sync logout (only if they were using Privy auth)
        authLogout();
        setWalletPending(false);
        setSyncError(null);
        setSyncRecovery(null);
        setSyncRequested(false);
      }
    };

    syncAuth();
  }, [authenticated, privyUser, isAuthenticated, ready, walletAddress, loginWithPrivy, authLogout, getAccessTokenWithRetry, authMethod, privyLogout, syncAttempt, syncRequested]);

  useEffect(() => {
    if (isAuthenticated && authMethod === 'privy') {
      backendPrivySessionRef.current = true;
    }
  }, [authMethod, isAuthenticated]);

  useEffect(() => {
    if (!isAuthenticated && authenticated && backendPrivySessionRef.current && !syncingRef.current) {
      backendPrivySessionRef.current = false;
      void privyLogout();
    }
    if (!authenticated) {
      backendPrivySessionRef.current = false;
    }
  }, [isAuthenticated, authenticated, privyLogout]);

  // Timeout for wallet creation - show error if it takes too long
  useEffect(() => {
    if (!walletPending) return;

    const timeoutId = setTimeout(() => {
      if (walletPending) {
        setSyncError('Wallet creation timed out.');
        setSyncRecovery(null);
        setSyncRequested(false);
        setWalletPending(false);
        privyLogout();
      }
    }, WALLET_CREATION_TIMEOUT_MS);

    return () => clearTimeout(timeoutId);
  }, [walletPending, privyLogout]);

  // Note: syncError is now exposed via PrivyBridgeContext for UI consumption

  return (
    <PrivyBridgeContext.Provider value={{ walletPending, syncError, syncRecovery, retrySync, resetSyncError }}>
      {children}
    </PrivyBridgeContext.Provider>
  );
}

/**
 * PrivyProvider - Configures and provides Privy SDK
 */
export function PrivyProvider({ children }: PrivyProviderProps) {
  if (PRIVY_E2E_MOCK) {
    return isE2EPrivyBridgeEnabled()
      ? <E2EPrivyAuthBridge>{children}</E2EPrivyAuthBridge>
      : <>{children}</>;
  }

  // Skip Privy if no app ID configured
  if (!PRIVY_APP_ID) {
    console.warn('VITE_PRIVY_APP_ID not configured - Privy login disabled');
    return <>{children}</>;
  }

  return (
    <BasePrivyProvider
      appId={PRIVY_APP_ID}
      config={{
        // Appearance - match Boulder Roller aesthetic
        appearance: {
          theme: 'light',
          accentColor: '#8b6f47',
          logo: '/logo.svg',
          landingHeader: 'Sign in to Boulder Roller',
          showWalletLoginFirst: false,
          walletChainType: 'solana-only',
        },
        // Login methods - social only. External wallet login is handled by
        // WalletConnect so Phantom/Solflare never appear inside the Privy UI.
        loginMethods: ['google', 'apple', 'email'],
        externalWallets: {
          disableAllExternalWallets: true,
          walletConnect: {
            enabled: false,
          },
        },
        // Embedded wallet config - create Solana wallet for social users.
        // Privy v3 scopes creation by chain; do not request an Ethereum wallet.
        embeddedWallets: {
          solana: {
            createOnLogin: 'users-without-wallets',
          },
          showWalletUIs: false,
        },
      }}
    >
      <PrivyAuthBridge>{children}</PrivyAuthBridge>
    </BasePrivyProvider>
  );
}

/**
 * usePrivyBridgeState - Hook for accessing Privy bridge state (wallet pending, sync errors)
 */
export function usePrivyBridgeState() {
  if (PRIVY_E2E_MOCK && isE2EPrivyBridgeEnabled()) {
    const snapshot = useE2EPrivySnapshot();
    return {
      walletPending: snapshot.walletPending,
      syncError: snapshot.syncError,
      syncRecovery: snapshot.syncRecovery,
      retrySync: () => updateE2EPrivySnapshot({
        syncError: null,
        syncRecovery: null,
        syncRequested: true,
      }),
      resetSyncError: () => updateE2EPrivySnapshot({
        syncError: null,
        syncRecovery: null,
      }),
    };
  }
  return useContext(PrivyBridgeContext);
}

export function usePrivySolanaBridge() {
  return useContext(PrivySolanaBridgeContext);
}

/**
 * usePrivyAuth - Hook for Privy-specific auth actions
 */
export function usePrivyAuth() {
  if (PRIVY_E2E_MOCK) {
    const snapshot = useE2EPrivySnapshot();
    return {
      login: () => {},
      logout: async () => updateE2EPrivySnapshot(initialE2EPrivySnapshot),
      authenticated: snapshot.authenticated,
      ready: true,
      user: snapshot.authenticated ? { wallet: { address: E2E_MOCK_WALLET } } : null,
      walletAddress: snapshot.authenticated ? E2E_MOCK_WALLET : null,
    };
  }

  const { login, logout, authenticated, ready, user } = usePrivy();

  return {
    login,
    logout,
    authenticated,
    ready,
    user,
    walletAddress: extractPrivyWalletAddress(user),
  };
}

export function usePrivySessionResume(
  requested: boolean,
  onStarted?: () => void,
) {
  const { authenticated, ready } = usePrivyAuth();
  const { syncError, retrySync, resetSyncError } = usePrivyBridgeState();
  const [active, setActive] = useState(requested);
  const startedRef = useRef(false);

  useEffect(() => {
    if (!requested) return;
    setActive(true);
  }, [requested]);

  useEffect(() => {
    if (!active || !authenticated || startedRef.current) return;
    startedRef.current = true;
    resetSyncError();
    retrySync();
    onStarted?.();
  }, [active, authenticated, onStarted, resetSyncError, retrySync]);

  useEffect(() => {
    if (syncError || (active && ready && !authenticated)) {
      setActive(false);
    }
  }, [active, authenticated, ready, syncError]);

  return { authenticated, active };
}

export function usePrivyEmailAuth() {
  if (PRIVY_E2E_MOCK) {
    const snapshot = useE2EPrivySnapshot();
    return {
      sendCode: async (options: { email: string; disableSignup?: boolean }) => {
        updateE2EPrivySnapshot({ emailStatus: 'awaiting-code-input' });
        window.dispatchEvent(new CustomEvent('br:e2e:privy-email-code-requested', {
          detail: options,
        }));
      },
      loginWithCode: async () => {
        updateE2EPrivySnapshot({
          authenticated: true,
          emailStatus: 'done',
        });
      },
      state: { status: snapshot.emailStatus },
    };
  }

  return useLoginWithEmail();
}

export default PrivyProvider;
