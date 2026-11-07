import { useEffect, useState, Suspense, lazy } from 'react';
import { BrowserRouter as Router, useLocation, useNavigate } from 'react-router-dom';
import { QueryClientProvider } from '@tanstack/react-query';
import { queryClient } from './lib/queryClient';
import { ThemeProvider } from './contexts/ThemeContext';
import { AuthProvider, useAuth } from './contexts/AuthContext';
import AppBootScreen from './components/loading/AppBootScreen';
import AuthHandoffScreen from './components/loading/AuthHandoffScreen';
import { ErrorBoundary } from './components/ErrorBoundary';
import { ApiError, api } from './lib/api';
import {
  hasAccessSignInIntent,
  hasAuthHandoffPending,
  isInviteEntryLocation,
  registerAuthenticatedAppLoader,
  storeReturnIntent,
} from './lib/authHandoff';
import { AuthRuntimeBoundary, AuthRuntimeProvider, useAuthRuntime } from './contexts/AuthRuntimeContext';
import { isPublicPreviewPath } from './lib/publicPreviewRoutes';
import { loadAuthenticatedApp } from './lib/authenticatedAppLoader';
import InviteGate from './components/auth/InviteGate';
import AccountDeletionStatusScreen, {
  AccountDeletionCapabilityErrorScreen,
  AccountDeletionRecoveryScreen,
} from './components/account/AccountDeletionStatusScreen';
import {
  clearAccountDeletionCapability,
  clearUnconfirmedAccountDeletionCapability,
  getActiveUnconfirmedAccountDeletionCapability,
  persistAccountDeletionCapability,
  useAccountDeletionCapability,
} from './lib/accountDeletionCapability';

registerAuthenticatedAppLoader(loadAuthenticatedApp);

const AuthenticatedApp = lazy(loadAuthenticatedApp);
const QUERY_DEVTOOLS_ENABLED =
  import.meta.env.DEV && String(import.meta.env.VITE_ENABLE_QUERY_DEVTOOLS || '').toLowerCase() === 'true';

const QueryDevtools = QUERY_DEVTOOLS_ENABLED
  ? lazy(() => import('./components/dev/QueryDevtools'))
  : null;

const RETURN_URL_KEY = 'br_return_url';

function shouldPrefetchInitialBranch(): boolean {
  if (typeof navigator === 'undefined') return true;

  const connection = (navigator as Navigator & {
    connection?: { saveData?: boolean; effectiveType?: string };
  }).connection;

  if (!connection) return true;
  if (connection.saveData) return false;
  return connection.effectiveType !== 'slow-2g' && connection.effectiveType !== '2g';
}

function AppContent() {
  const {
    isAuthenticated,
    isLoading,
    authMethod,
    logout,
    retrySessionCheck,
    sessionCheckError,
  } = useAuth();
  const {
    ensureRuntime,
    status: authRuntimeStatus,
    error: authRuntimeError,
    retryRuntime,
  } = useAuthRuntime();
  const location = useLocation();
  const navigate = useNavigate();
  const deletionCapability = useAccountDeletionCapability();
  const [recoveryCapability, setRecoveryCapability] = useState(() => {
    try {
      return getActiveUnconfirmedAccountDeletionCapability();
    } catch {
      return null;
    }
  });
  const [recoveryCheckState, setRecoveryCheckState] = useState<'checking' | 'unavailable' | 'not_found'>('checking');
  const [recoveryAttempt, setRecoveryAttempt] = useState(0);
  const showAuthHandoff = isAuthenticated && hasAuthHandoffPending();
  const publicPreviewPath = isPublicPreviewPath(location.pathname);
  const deletionStatusPath = location.pathname === '/account-deletion';
  const deletionLifecycleBranch = deletionCapability.kind === 'valid'
    && deletionStatusPath
    && !isLoading;

  useEffect(() => {
    if (!recoveryCapability || deletionCapability.kind !== 'none') return;
    let cancelled = false;
    setRecoveryCheckState('checking');
    void api.getAccountDeletionStatus(recoveryCapability).then(() => {
      if (cancelled) return;
      // A recovery envelope is promoted only after the server proves that its
      // request/token pair exists. Until this point it never owns the global
      // account-deletion route.
      persistAccountDeletionCapability(recoveryCapability);
      try {
        clearUnconfirmedAccountDeletionCapability(recoveryCapability.wallet);
      } catch {
        // The accepted capability remains authoritative and the stale recovery
        // envelope can be cleaned on a later confirmed load.
      }
      setRecoveryCapability(null);
      sessionStorage.removeItem(RETURN_URL_KEY);
      navigate('/account-deletion', { replace: true });
    }).catch((error) => {
      if (cancelled) return;
      // A 404 still needs the identical authenticated re-submit. A transient
      // failure keeps a visible, retryable recovery surface before auth.
      setRecoveryCheckState(
        error instanceof ApiError && error.statusCode === 404
          ? 'not_found'
          : 'unavailable',
      );
    });
    return () => {
      cancelled = true;
    };
  }, [deletionCapability.kind, navigate, recoveryAttempt, recoveryCapability]);

  useEffect(() => {
    if (deletionLifecycleBranch) return;
    if (!shouldPrefetchInitialBranch()) return;

    let hasStoredAuthHint = false;
    try {
      hasStoredAuthHint = localStorage.getItem('br_authenticated') === 'true';
    } catch {
      // Prefetch is optional; unavailable browser storage must not break the portal.
    }
    const likelyAuthenticated = isAuthenticated
      || api.isAuthenticated()
      || hasStoredAuthHint;
    const publicPreviewEntry = isPublicPreviewPath(window.location.pathname);
    const preload = likelyAuthenticated || publicPreviewEntry ? loadAuthenticatedApp : null;
    if (!preload) return;
    const idleWindow = window as Window & {
      requestIdleCallback?: (callback: () => void) => number;
      cancelIdleCallback?: (id: number) => void;
    };

    if (typeof idleWindow.requestIdleCallback === 'function') {
      const idleId = idleWindow.requestIdleCallback(() => {
        void preload();
      });
      return () => {
        if (typeof idleWindow.cancelIdleCallback === 'function') {
          idleWindow.cancelIdleCallback(idleId);
        }
      };
    }

    const timeout = window.setTimeout(() => {
      void preload();
    }, 120);

    return () => {
      window.clearTimeout(timeout);
    };
  }, [deletionLifecycleBranch, isAuthenticated]);

  useEffect(() => {
    if (deletionLifecycleBranch) return;
    if (!hasAccessSignInIntent() && authRuntimeStatus === 'idle') return;
    void loadAuthenticatedApp();
  }, [authRuntimeStatus, deletionLifecycleBranch]);

  useEffect(() => {
    if (deletionLifecycleBranch) return;
    if (isAuthenticated && authMethod === 'privy') {
      ensureRuntime();
    }
  }, [authMethod, deletionLifecycleBranch, ensureRuntime, isAuthenticated]);

  useEffect(() => {
    if (deletionStatusPath) {
      sessionStorage.removeItem(RETURN_URL_KEY);
      return;
    }
    if (!isLoading && !isAuthenticated) {
      const currentPath = window.location.pathname + window.location.search;
      if (
        currentPath !== '/'
        && currentPath !== '/onboarding'
        && !isInviteEntryLocation(location)
        && !publicPreviewPath
      ) {
        storeReturnIntent(currentPath);
      }
    }
  }, [deletionStatusPath, isLoading, isAuthenticated, location, publicPreviewPath]);

  if (
    recoveryCapability
    && deletionCapability.kind === 'none'
    && recoveryCheckState !== 'not_found'
  ) {
    return (
      <AccountDeletionRecoveryScreen
        checking={recoveryCheckState === 'checking'}
        onRetry={() => setRecoveryAttempt((attempt) => attempt + 1)}
        onDiscard={() => {
          try {
            clearUnconfirmedAccountDeletionCapability(recoveryCapability.wallet);
            setRecoveryCapability(null);
            sessionStorage.removeItem(RETURN_URL_KEY);
            navigate('/', { replace: true });
          } catch {
            setRecoveryCheckState('unavailable');
          }
        }}
      />
    );
  }

  if (deletionStatusPath && isLoading) {
    return <AppBootScreen />;
  }

  if (
    (deletionCapability.kind === 'invalid' || deletionCapability.kind === 'unavailable')
    && deletionStatusPath
  ) {
    return (
      <AccountDeletionCapabilityErrorScreen
        kind={deletionCapability.kind}
        onDiscard={() => {
          clearAccountDeletionCapability();
          sessionStorage.removeItem(RETURN_URL_KEY);
          navigate('/', { replace: true });
        }}
      />
    );
  }

  if (deletionCapability.kind === 'valid' && deletionLifecycleBranch) {
    return (
      <AccountDeletionStatusScreen
        key={deletionCapability.capability.requestId}
        capability={deletionCapability.capability}
        onFinish={() => {
          clearAccountDeletionCapability(deletionCapability.capability.wallet);
          sessionStorage.removeItem(RETURN_URL_KEY);
          logout();
          window.location.assign('/');
        }}
        onDiscard={() => {
          clearAccountDeletionCapability(deletionCapability.capability.wallet);
          sessionStorage.removeItem(RETURN_URL_KEY);
          navigate('/', { replace: true });
        }}
        onOpenPortfolio={() => window.location.assign('/profile?tab=portfolio')}
      />
    );
  }

  if (!publicPreviewPath && (isLoading || !isAuthenticated)) {
    return (
      <InviteGate
        onRetrySessionCheck={retrySessionCheck}
        sessionCheckError={isLoading ? null : sessionCheckError}
        sessionPending={isLoading}
      />
    );
  }

  if (isLoading) {
    return <AppBootScreen />;
  }

  if (!isAuthenticated) {
    return (
      <Suspense fallback={<AppBootScreen />}>
        <AuthenticatedApp publicRoutesOnly />
      </Suspense>
    );
  }

  const authenticatedFallback = authRuntimeStatus === 'failed'
    ? (
      <AppBootScreen
        description={authRuntimeError ?? 'Sign-in failed to load.'}
        onRetry={retryRuntime}
        title="Sign-in failed to load"
      />
    )
    : showAuthHandoff
      ? <AuthHandoffScreen />
      : <AppBootScreen />;
  const authenticatedApp = (
    <Suspense fallback={showAuthHandoff ? <AuthHandoffScreen /> : <AppBootScreen />}>
      <AuthenticatedApp />
    </Suspense>
  );

  if (authMethod === 'privy') {
    return (
      <AuthRuntimeBoundary fallback={authenticatedFallback}>
        {authenticatedApp}
      </AuthRuntimeBoundary>
    );
  }

  return authenticatedApp;
}

export default function App() {
  return (
    <ThemeProvider>
      <ErrorBoundary>
        <QueryClientProvider client={queryClient}>
          <Router>
            <AuthProvider>
              <AuthRuntimeProvider>
                <AppContent />
              </AuthRuntimeProvider>
            </AuthProvider>
            {QueryDevtools && (
              <Suspense fallback={null}>
                <QueryDevtools />
              </Suspense>
            )}
          </Router>
        </QueryClientProvider>
      </ErrorBoundary>
    </ThemeProvider>
  );
}
