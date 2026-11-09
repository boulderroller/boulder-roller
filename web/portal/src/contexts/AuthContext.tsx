import { flushSync } from 'react-dom';
import { createContext, useContext, useState, useEffect, useCallback, ReactNode, useMemo, useRef } from 'react';
import { api, ApiError, isDogfoodAutoLogoutDisabled, User, UserProfile } from '../lib/api';
import { clearAdminCache } from '../hooks/useAdminCheck';
import {
  clearAccessSignInIntent,
  clearAuthHandoffPending,
  clearPendingInviteCode,
  ensureAuthenticatedAppLoaded,
  markAuthHandoffPending,
} from '../lib/authHandoff';
import {
  authAccessMethodFromBackend,
  type AuthAccessMethod,
  type BackendAuthMethod,
} from '../lib/authState';
import { clearViewerQueryCache } from '../lib/queryClient';

interface AuthContextType {
  isAuthenticated: boolean;
  isLoading: boolean;
  user: User | null;
  walletAddress: string | null;
  authMethod: BackendAuthMethod | null;
  accessMethod: AuthAccessMethod | null;
  needsProfileSetup: boolean;
  sessionCheckError: string | null;
  login: (wallet: string, signature: string, nonce: string, inviteCode?: string) => Promise<void>;
  loginWithPrivy: (wallet: string, privyToken: string, inviteCode?: string) => Promise<void>;
  logout: () => void;
  refreshUser: () => Promise<void>;
  updatePreferences: (updates: Partial<UserProfile>) => Promise<void>;
  retrySessionCheck: () => void;
}

const AuthContext = createContext<AuthContextType | undefined>(undefined);

function normalizeAuthMethodHint(value: unknown): BackendAuthMethod | null {
  if (value === 'wallet' || value === 'privy') {
    return value;
  }
  return null;
}

interface CheckAuthOptions {
  forceRemote?: boolean;
  signal?: AbortSignal;
}

const SESSION_CHECK_TIMEOUT_MS = 6000;

export function AuthProvider({ children }: { children: ReactNode }) {
  const [isAuthenticated, setIsAuthenticated] = useState(false);
  const [isLoading, setIsLoading] = useState(true);
  const [user, setUser] = useState<User | null>(null);
  const [walletAddress, setWalletAddress] = useState<string | null>(null);
  const [authMethod, setAuthMethod] = useState<BackendAuthMethod | null>(null);
  const [needsProfileSetup, setNeedsProfileSetup] = useState(false);
  const [sessionCheckError, setSessionCheckError] = useState<string | null>(null);
  const activeSessionCheckRef = useRef<AbortController | null>(null);
  const authCheckIdRef = useRef(0);
  const sessionRunIdRef = useRef(0);
  const viewerIdentityRef = useRef<string | null>(null);
  const accessMethod = authAccessMethodFromBackend(authMethod);

  const transitionViewer = useCallback((nextUser: User | null) => {
    const nextIdentity = nextUser ? `${nextUser.id}:${nextUser.wallet}` : null;
    if (viewerIdentityRef.current !== nextIdentity) {
      clearViewerQueryCache();
      viewerIdentityRef.current = nextIdentity;
    }
  }, []);

  const invalidateSessionChecks = useCallback(() => {
    authCheckIdRef.current += 1;
    sessionRunIdRef.current += 1;
    activeSessionCheckRef.current?.abort();
    activeSessionCheckRef.current = null;
  }, []);

  // Check auth helper - extracted for reuse
  const checkAuth = useCallback(async ({ forceRemote = false, signal }: CheckAuthOptions = {}) => {
    const checkId = ++authCheckIdRef.current;
    const checkIsStale = () => signal?.aborted || checkId !== authCheckIdRef.current;
    let hasLocalAuthHint = false;

    try {
      hasLocalAuthHint = api.isAuthenticated() || localStorage.getItem('br_authenticated') === 'true';
      if (!forceRemote && !hasLocalAuthHint) {
        return false;
      }

      const bootstrap = await api.getAuthBootstrap({
        forceRemote,
        signal,
        useAuthHeader: hasLocalAuthHint,
      });
      if (checkIsStale()) return null;
      if (!bootstrap.authenticated) {
        if (isDogfoodAutoLogoutDisabled() && hasLocalAuthHint) {
          api.setAuthenticated(true);
          setIsAuthenticated(true);
          return true;
        }

        api.clearTokens();
        clearAdminCache();
        clearAuthHandoffPending();
        if (hasLocalAuthHint) {
          clearAccessSignInIntent();
          clearPendingInviteCode();
        }
        transitionViewer(null);
        setUser(null);
        setWalletAddress(null);
        setIsAuthenticated(false);
        setAuthMethod(null);
        setNeedsProfileSetup(false);
        return false;
      }

      const userData = bootstrap.user ?? await api.getMe({ signal });
      if (checkIsStale()) return null;
      // Re-sync local markers only after the complete response is still current.
      api.setAuthenticated(true);
      clearPendingInviteCode();
      clearAccessSignInIntent();
      transitionViewer(userData);
      setUser(userData);
      setWalletAddress(userData.wallet);
      setIsAuthenticated(true);
      setAuthMethod(normalizeAuthMethodHint(bootstrap.authMethodHint));
      setNeedsProfileSetup(bootstrap.needsProfileSetup);
      return true;
    } catch (error) {
      const sessionIsAuthoritativelyExpired = error instanceof ApiError
        && (error.type === 'session_expired' || error.statusCode === 401);
      if (sessionIsAuthoritativelyExpired) {
        if (isDogfoodAutoLogoutDisabled() && hasLocalAuthHint) {
          api.setAuthenticated(true);
          setIsAuthenticated(true);
          return true;
        }

        api.clearTokens();
        clearAdminCache();
        clearAuthHandoffPending();
        if (hasLocalAuthHint) {
          clearAccessSignInIntent();
          clearPendingInviteCode();
        }
        transitionViewer(null);
        setUser(null);
        setWalletAddress(null);
        setIsAuthenticated(false);
        setAuthMethod(null);
        setNeedsProfileSetup(false);
        return false;
      }

      if (checkIsStale() || (error instanceof ApiError && error.statusCode === 499)) {
        return null;
      }

      // Network or transient failure: preserve old behavior as fallback.
      if (api.isAuthenticated()) {
        try {
          const userData = await api.getMe({ signal });
          if (checkIsStale()) return null;
          clearAccessSignInIntent();
          transitionViewer(userData);
          setUser(userData);
          setWalletAddress(userData.wallet);
          setIsAuthenticated(true);
          return true;
        } catch (meError) {
          if (checkIsStale() || (meError instanceof ApiError && meError.statusCode === 499)) {
            return null;
          }

          if (isDogfoodAutoLogoutDisabled() && hasLocalAuthHint) {
            api.setAuthenticated(true);
            setIsAuthenticated(true);
            return true;
          }

          const sessionIsAuthoritativelyExpired = meError instanceof ApiError
            && (meError.type === 'session_expired' || meError.statusCode === 401);
          if (sessionIsAuthoritativelyExpired) {
            api.clearTokens();
            clearAdminCache();
            clearAuthHandoffPending();
            clearAccessSignInIntent();
            clearPendingInviteCode();
            transitionViewer(null);
            setUser(null);
            setWalletAddress(null);
            setIsAuthenticated(false);
            setAuthMethod(null);
            setNeedsProfileSetup(false);
            return false;
          }
        }
      }
    }
    return null;
  }, [transitionViewer]);

  const runSessionCheck = useCallback(async () => {
    const runId = ++sessionRunIdRef.current;
    activeSessionCheckRef.current?.abort();

    const controller = new AbortController();
    activeSessionCheckRef.current = controller;
    setIsLoading(true);
    setSessionCheckError(null);

    const timeoutId = window.setTimeout(() => controller.abort(), SESSION_CHECK_TIMEOUT_MS);
    let result: boolean | null = null;
    try {
      result = await checkAuth({ forceRemote: true, signal: controller.signal });
    } catch {
      result = null;
    } finally {
      window.clearTimeout(timeoutId);
    }

    if (runId !== sessionRunIdRef.current) return;
    activeSessionCheckRef.current = null;
    setIsLoading(false);

    if (result === null) {
      setSessionCheckError('Could not check your session.');
    }
  }, [checkAuth]);

  const retrySessionCheck = useCallback(() => {
    void runSessionCheck();
  }, [runSessionCheck]);

  // Check for an existing cookie session without replacing the entry shell.
  useEffect(() => {
    void runSessionCheck();

    return () => {
      invalidateSessionChecks();
    };
  }, [invalidateSessionChecks, runSessionCheck]);

  // Multi-tab sync: listen for auth state changes in other tabs
  useEffect(() => {
    const handleStorageChange = (e: StorageEvent) => {
      if (e.key === 'br_authenticated') {
        if (e.newValue === 'true' && !isAuthenticated) {
          // Another tab logged in - refresh our state
          checkAuth();
        } else if (e.newValue !== 'true' && isAuthenticated) {
          // Another tab logged out - sync logout
          // Retire the owner page before cache notifications can restart its reads.
          flushSync(() => {
            invalidateSessionChecks();
            clearAuthHandoffPending();
            clearAccessSignInIntent();
            clearPendingInviteCode();
            transitionViewer(null);
            setUser(null);
            setWalletAddress(null);
            setIsAuthenticated(false);
            setAuthMethod(null);
            setNeedsProfileSetup(false);
            setIsLoading(false);
            setSessionCheckError(null);
          });
        }
      }
    };

    window.addEventListener('storage', handleStorageChange);
    return () => window.removeEventListener('storage', handleStorageChange);
  }, [checkAuth, invalidateSessionChecks, isAuthenticated, transitionViewer]);

  useEffect(() => api.onSessionEvent((event) => {
    if (event !== 'session_expired') return;
    invalidateSessionChecks();
    clearAuthHandoffPending();
    clearAccessSignInIntent();
    clearPendingInviteCode();
    transitionViewer(null);
    setUser(null);
    setWalletAddress(null);
    setIsAuthenticated(false);
    setAuthMethod(null);
    setNeedsProfileSetup(false);
    setIsLoading(false);
    setSessionCheckError(null);
    clearAdminCache();
  }), [invalidateSessionChecks, transitionViewer]);

  const login = useCallback(async (wallet: string, signature: string, nonce: string, inviteCode?: string) => {
    await api.verifySignature(wallet, signature, nonce, inviteCode);
    const bootstrap = await api.getAuthBootstrap({ useAuthHeader: true });
    const userData = bootstrap.user ?? await api.getMe();
    await ensureAuthenticatedAppLoaded();
    markAuthHandoffPending();
    clearPendingInviteCode();
    clearAccessSignInIntent();
    transitionViewer(userData);
    setUser(userData);
    setWalletAddress(wallet);
    setIsAuthenticated(true);
    setAuthMethod('wallet');
    setNeedsProfileSetup(bootstrap.needsProfileSetup);
  }, [transitionViewer]);

  const loginWithPrivy = useCallback(async (wallet: string, privyToken: string, inviteCode?: string) => {
    // Verify Privy token with our backend and get our JWT
    await api.verifyPrivyToken(wallet, privyToken, inviteCode);
    const bootstrap = await api.getAuthBootstrap({ useAuthHeader: true });
    const userData = bootstrap.user ?? await api.getMe();
    await ensureAuthenticatedAppLoaded();
    markAuthHandoffPending();
    clearPendingInviteCode();
    clearAccessSignInIntent();
    transitionViewer(userData);
    setUser(userData);
    setWalletAddress(wallet);
    setIsAuthenticated(true);
    setAuthMethod('privy');
    setNeedsProfileSetup(bootstrap.needsProfileSetup);
  }, [transitionViewer]);

  const logout = useCallback(() => {
    invalidateSessionChecks();
    void api.logout().catch(() => {
      api.clearTokens();
    });
    clearAuthHandoffPending();
    clearAccessSignInIntent();
    clearPendingInviteCode();
    transitionViewer(null);
    setUser(null);
    setWalletAddress(null);
    setIsAuthenticated(false);
    setAuthMethod(null);
    setNeedsProfileSetup(false);
    setIsLoading(false);
    setSessionCheckError(null);
    clearAdminCache();
  }, [invalidateSessionChecks, transitionViewer]);

  const refreshUser = useCallback(async () => {
    if (api.isAuthenticated()) {
      const bootstrap = await api.getAuthBootstrap({ useAuthHeader: true });
      const userData = bootstrap.user ?? await api.getMe();
      transitionViewer(userData);
      setUser(userData);
      setNeedsProfileSetup(bootstrap.needsProfileSetup);
      setAuthMethod(normalizeAuthMethodHint(bootstrap.authMethodHint));
    }
  }, [transitionViewer]);

  const updatePreferences = useCallback(async (updates: Partial<UserProfile>) => {
    if (!api.isAuthenticated()) return;

    try {
      const updatedUser = await api.updateProfile(updates);
      transitionViewer(updatedUser);
      if (updates.isPublic !== undefined) {
        clearViewerQueryCache();
      }
      setUser(updatedUser);
    } catch (err) {
      throw err;
    }
  }, [transitionViewer]);

  // Memoize context value to prevent unnecessary re-renders
  const contextValue = useMemo(() => ({
    isAuthenticated,
    isLoading,
    user,
    walletAddress,
    authMethod,
    accessMethod,
    needsProfileSetup,
    sessionCheckError,
    login,
    loginWithPrivy,
    logout,
    refreshUser,
    retrySessionCheck,
    updatePreferences,
  }), [
    isAuthenticated,
    isLoading,
    user,
    walletAddress,
    authMethod,
    accessMethod,
    needsProfileSetup,
    sessionCheckError,
    login,
    loginWithPrivy,
    logout,
    refreshUser,
    retrySessionCheck,
    updatePreferences,
  ]);

  return (
    <AuthContext.Provider value={contextValue}>
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth() {
  const context = useContext(AuthContext);
  if (!context) {
    throw new Error('useAuth must be used within an AuthProvider');
  }
  return context;
}
