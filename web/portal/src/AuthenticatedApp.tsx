import { useState, useEffect, Suspense, lazy, useRef, useCallback } from 'react';
import { Routes, Route, Navigate, Outlet, useNavigate, useLocation, useParams } from 'react-router-dom';
import { Info, Settings as SettingsIcon, X } from 'lucide-react';
import { useTheme, isThemeId } from './contexts/ThemeContext';
import { useAuth } from './contexts/AuthContext';
import ScrollToTop from './components/layout/ScrollToTop';
import AppBootScreen from './components/loading/AppBootScreen';
import AuthHandoffScreen from './components/loading/AuthHandoffScreen';
import { RouteLoadingFallback } from './components/loading/LoadingSystem';
import type { SessionErrorReason } from './components/auth/SessionRecoveryScreen';
import type { FirstRunDestination } from './components/auth/SetupModal';
import { PortalPanel, PortalPanelBody } from './components/portal/PortalSpine';
import { api, SESSION_EXPIRED_EVENT, NETWORK_ERROR_EVENT, NETWORK_RESTORED_EVENT } from './lib/api';
import { notify } from './lib/notify';
import { formatInteger } from './lib/formatters';
import { prefetchRoute, shouldPrefetchRouteModules } from './lib/routePrefetch';
import { clearAuthHandoffPending, hasAuthHandoffPending, normalizeReturnIntent } from './lib/authHandoff';
import {
  clearFirstRidePending,
  hasFirstRidePending,
  markFirstRidePending,
} from './lib/firstRunOnboarding';
import { loadOnboardingPage } from './lib/authenticatedAppLoader';
import { readUploadReturnTo } from './lib/uploadRoute';

const DashboardLayout = lazy(() => import('./components/layout/DashboardLayout'));
const Onboarding = lazy(loadOnboardingPage);
const ActivityFeed = lazy(() => import('./components/feed/ActivityFeed'));
import SessionRecoveryScreen from './components/auth/SessionRecoveryScreen';
const RideView = lazy(() => import('./pages/RideView'));
const PublicPreview = lazy(() => import('./pages/PublicPreview'));
const ClimbView = lazy(() => import('./pages/ClimbView'));
const LegacyVaultDetailRedirect = lazy(() => import('./pages/ClimbView').then((module) => ({
  default: module.LegacyVaultDetailRedirect,
})));
const CreateVaultView = lazy(() => import('./pages/CreateVaultView'));
const Upload = lazy(() => import('./pages/Upload'));
const Settings = lazy(() => import('./pages/Settings'));
const Profile = lazy(() => import('./pages/Profile'));
const Docs = lazy(() => import('./pages/Docs'));
const Climbs = lazy(() => import('./pages/Climbs'));
const AdminDashboard = lazy(() => import('./pages/AdminDashboard'));
const Notifications = lazy(() => import('./pages/Notifications'));
const NotFound = lazy(() => import('./pages/NotFound'));
const AccountDeletionTrackingBanner = lazy(() => import('./components/account/AccountDeletionTrackingBanner'));

const RETURN_URL_KEY = 'br_return_url';
const PREVIOUS_ROUTE_KEY = 'br_previous_route';
const SETUP_REPROMPT_DISMISSED_KEY = 'br_setup_reprompt_dismissed';

function getStoredReturnUrl() {
  const returnUrl = normalizeReturnIntent(sessionStorage.getItem(RETURN_URL_KEY));
  if (!returnUrl) sessionStorage.removeItem(RETURN_URL_KEY);
  return returnUrl;
}

function ReturnUrlHandler({ pause = false }: { pause?: boolean }) {
  const navigate = useNavigate();
  const location = useLocation();
  const { isAuthenticated, needsProfileSetup } = useAuth();
  const [hasRedirected, setHasRedirected] = useState(false);

  useEffect(() => {
    if (pause || !isAuthenticated || needsProfileSetup || hasRedirected || location.pathname !== '/') {
      return;
    }

    const returnUrl = getStoredReturnUrl();
    if (returnUrl) {
      setHasRedirected(true);
      sessionStorage.removeItem(RETURN_URL_KEY);
      navigate(returnUrl, { replace: true });
    }
  }, [pause, isAuthenticated, needsProfileSetup, hasRedirected, location.pathname, navigate]);

  return null;
}

function AuthenticatedSurfaceReady({ onReady }: { onReady: () => void }) {
  useEffect(onReady, [onReady]);

  return null;
}

function NotificationTargetRedirect({ queryKey, paramKey }: { queryKey: string; paramKey: string }) {
  const params = useParams();
  const value = params[paramKey];
  const search = value ? `?${queryKey}=${encodeURIComponent(value)}` : '';
  return <Navigate to={`/notifications${search}`} replace />;
}

function LegacyMapRedirect() {
  const location = useLocation();
  return <Navigate to={`/climbs${location.search}${location.hash}`} replace />;
}

function LegacyProfileTabRedirect({ tab }: { tab: 'rides' | 'training' | 'portfolio' }) {
  const location = useLocation();
  const params = new URLSearchParams(location.search);
  params.set('tab', tab);
  return (
    <Navigate
      to={{ pathname: '/profile', search: `?${params.toString()}`, hash: location.hash }}
      replace
    />
  );
}

function LegacyFindRidersRedirect() {
  const location = useLocation();
  const params = new URLSearchParams(location.search);
  params.set('search', 'riders');
  return (
    <Navigate
      to={{ pathname: '/', search: `?${params.toString()}`, hash: location.hash }}
      replace
    />
  );
}

function LegacyVaultsRedirect() {
  return <Navigate to="/climbs?hasVault=true" replace />;
}

export default function AuthenticatedApp({ publicRoutesOnly = false }: { publicRoutesOnly?: boolean }) {
  const location = useLocation();
  const navigate = useNavigate();
  const { isAuthenticated, walletAddress, logout, user, refreshUser, needsProfileSetup } = useAuth();
  const { setThemeId, setDarkMode, themeId, isDarkMode } = useTheme();
  const [showSessionRecovery, setShowSessionRecovery] = useState(false);
  const [sessionErrorReason, setSessionErrorReason] = useState<SessionErrorReason>('token_expired');
  const [isOffline, setIsOffline] = useState(false);
  const [setupRepromptDismissed, setSetupRepromptDismissed] = useState(() => {
    return localStorage.getItem(SETUP_REPROMPT_DISMISSED_KEY) === 'true';
  });
  const [authHandoffActive, setAuthHandoffActive] = useState(hasAuthHandoffPending);
  const [firstRidePending, setFirstRidePending] = useState(() => hasFirstRidePending(user?.id));
  const previousPathRef = useRef(location.pathname);
  const lastWarningRef = useRef<number>(0);
  const postOnboardingDestinationRef = useRef<string | null>(null);

  useEffect(() => {
    const unsubscribe = api.onSessionEvent((event, data) => {
      if (event === 'session_warning' && data?.minutesRemaining) {
        const now = Date.now();
        if (now - lastWarningRef.current < 4 * 60 * 1000) return;
        lastWarningRef.current = now;

        notify.warning(`Session expires in ${formatInteger(data.minutesRemaining)} minutes`, {
          description: 'Your session will be automatically refreshed.',
          duration: 8000,
        });
        return;
      }

      if (event === 'session_expired') {
        notify.error('Session expired', {
          description: 'Please sign in again.',
          duration: 10000,
        });
        return;
      }

      if (event === 'session_restored') {
        notify.success('Session restored', {
          duration: 3000,
        });
      }
    });

    return unsubscribe;
  }, []);

  useEffect(() => {
    const handleSessionExpired = (event: Event) => {
      const customEvent = event as CustomEvent<{ reason?: string }>;
      const reason = customEvent.detail?.reason || 'token_expired';
      setSessionErrorReason(reason as SessionErrorReason);
      setShowSessionRecovery(true);
    };

    const handleNetworkError = () => {
      setIsOffline(true);
      if (isAuthenticated) {
        setSessionErrorReason('network_error');
        setShowSessionRecovery(true);
      }
    };

    const handleNetworkRestored = () => {
      setIsOffline(false);
      if (sessionErrorReason === 'network_error' && showSessionRecovery) {
        setShowSessionRecovery(false);
      }
    };

    window.addEventListener(SESSION_EXPIRED_EVENT, handleSessionExpired);
    window.addEventListener(NETWORK_ERROR_EVENT, handleNetworkError);
    window.addEventListener(NETWORK_RESTORED_EVENT, handleNetworkRestored);
    return () => {
      window.removeEventListener(SESSION_EXPIRED_EVENT, handleSessionExpired);
      window.removeEventListener(NETWORK_ERROR_EVENT, handleNetworkError);
      window.removeEventListener(NETWORK_RESTORED_EVENT, handleNetworkRestored);
    };
  }, [isAuthenticated, sessionErrorReason, showSessionRecovery]);

  const handleReLogin = () => {
    setShowSessionRecovery(false);
    logout();
  };

  const handleOnboardingIdentitySaved = async () => {
    const returnUrl = getStoredReturnUrl();
    if (returnUrl) {
      postOnboardingDestinationRef.current = returnUrl;
      await refreshUser();
      sessionStorage.removeItem(RETURN_URL_KEY);
      return 'redirected' as const;
    }

    if (!user?.id) {
      throw new Error('Missing rider identity');
    }

    markFirstRidePending(user.id);
    setFirstRidePending(true);
    return 'first_ride' as const;
  };

  const handleOnboardingComplete = async (destination: FirstRunDestination) => {
    postOnboardingDestinationRef.current = destination;
    await refreshUser();
    sessionStorage.removeItem(RETURN_URL_KEY);
    clearFirstRidePending(user?.id);
    setFirstRidePending(false);
  };

  const handleAuthenticatedSurfaceReady = useCallback(() => {
    if (!authHandoffActive) return;
    clearAuthHandoffPending();
    setAuthHandoffActive(false);
  }, [authHandoffActive]);

  useEffect(() => {
    if (isThemeId(user?.themeId) && user.themeId !== themeId) {
      setThemeId(user.themeId);
    }
    if (user?.isDarkMode !== undefined && user.isDarkMode !== isDarkMode) {
      setDarkMode(user.isDarkMode);
    }
  }, [user?.themeId, user?.isDarkMode]);

  useEffect(() => {
    const previousPath = previousPathRef.current;
    if (previousPath !== location.pathname) {
      sessionStorage.setItem(PREVIOUS_ROUTE_KEY, previousPath);
      previousPathRef.current = location.pathname;
    }
  }, [location.pathname]);

  useEffect(() => {
    if (location.pathname !== '/onboarding') {
      postOnboardingDestinationRef.current = null;
    }
  }, [location.pathname]);

  useEffect(() => {
    if (!isAuthenticated) return;
    if (!shouldPrefetchRouteModules()) return;

    const previousRoute = sessionStorage.getItem(PREVIOUS_ROUTE_KEY);
    if (!previousRoute || previousRoute === location.pathname) return;

    const idleWindow = window as Window & {
      requestIdleCallback?: (callback: () => void, options?: { timeout: number }) => number;
      cancelIdleCallback?: (id: number) => void;
    };

    const runPrefetch = () => {
      prefetchRoute(previousRoute, 'history');
    };

    if (typeof idleWindow.requestIdleCallback === 'function') {
      const idleHandle = idleWindow.requestIdleCallback(runPrefetch, { timeout: 1500 });
      return () => {
        if (typeof idleWindow.cancelIdleCallback === 'function') {
          idleWindow.cancelIdleCallback(idleHandle);
        }
      };
    }

    const timeoutHandle = window.setTimeout(runPrefetch, 350);
    return () => {
      window.clearTimeout(timeoutHandle);
    };
  }, [isAuthenticated, location.pathname]);

  if (!isAuthenticated && !publicRoutesOnly) {
    return null;
  }

  const needsOnboarding = !publicRoutesOnly && (needsProfileSetup || firstRidePending);
  const currentPath = location.pathname + location.search;
  const missingSetupFields = [
    user?.weightKg && user.weightKg > 0 ? null : 'Weight',
  ].filter((field): field is string => Boolean(field));
  const isFirstHome = (
    location.pathname === '/'
    || location.pathname === '/dashboard'
  ) && (user?.totalRides === 0 || user?.totalRides === undefined);
  const setupInlineSuppressed = (
    !isAuthenticated
    || !user?.username
    || setupRepromptDismissed
    || location.pathname === '/onboarding'
    || isFirstHome
    || location.pathname === '/climbs'
    || location.pathname === '/upload'
    || location.pathname === '/settings'
    || /^\/riders?\//.test(location.pathname)
  );
  const showInlineSetupPrompt = missingSetupFields.length > 0 && !setupInlineSuppressed;

  const dismissInlineSetupPrompt = () => {
    localStorage.setItem(SETUP_REPROMPT_DISMISSED_KEY, 'true');
    setSetupRepromptDismissed(true);
  };

  if (needsOnboarding && location.pathname !== '/onboarding') {
    if (currentPath !== '/' && currentPath !== '/onboarding') {
      const existingReturnUrl = sessionStorage.getItem(RETURN_URL_KEY);
      if (!existingReturnUrl || existingReturnUrl === '/' || existingReturnUrl === '/onboarding') {
        sessionStorage.setItem(RETURN_URL_KEY, currentPath);
      }
    }

    return <Navigate to="/onboarding" replace />;
  }

  const dashboardShell = (
    <>
      <DashboardLayout
        isConnected={isAuthenticated}
        walletAddress={walletAddress || ''}
        accountName={user?.displayName || user?.username || null}
        onDisconnect={logout}
      >

        <ScrollToTop />

        <div className="authenticated-app-outlet-shell">
          <div className="authenticated-app-outlet-shell__content">
            <Suspense fallback={null}>
              <AccountDeletionTrackingBanner />
            </Suspense>
            {showInlineSetupPrompt && (
              <PortalPanel className="authenticated-app-inline-setup" role="status">
                <PortalPanelBody className="authenticated-app-inline-setup__body">
                  <div className="authenticated-app-inline-setup__copy">
                    <Info size={18} aria-hidden="true" />
                    <div>
                      <strong>Training inputs need attention</strong>
                      <span>Missing: {missingSetupFields.join(', ')}. Add them when you want cleaner zones and load.</span>
                    </div>
                  </div>
                  <div className="authenticated-app-inline-setup__actions">
                    <button
                      type="button"
                      className="portal-action-button"
                      onClick={() => navigate('/settings?tab=performance')}
                    >
                      <SettingsIcon size={14} aria-hidden="true" />
                      <span>Add now</span>
                    </button>
                    <button
                      type="button"
                      className="portal-sort-button authenticated-app-inline-setup__dismiss"
                      onClick={dismissInlineSetupPrompt}
                      aria-label="Dismiss training inputs reminder"
                    >
                      <X size={14} aria-hidden="true" />
                    </button>
                  </div>
                </PortalPanelBody>
              </PortalPanel>
            )}
            <Suspense fallback={authHandoffActive ? null : <RouteLoadingFallback />}>
              <AuthenticatedSurfaceReady onReady={handleAuthenticatedSurfaceReady} />
              <Outlet />
            </Suspense>
          </div>
        </div>
      </DashboardLayout>

      {authHandoffActive && (
        <div className="auth-handoff-overlay">
          <AuthHandoffScreen />
        </div>
      )}
    </>
  );

  if (publicRoutesOnly) {
    return (
      <Suspense fallback={<AppBootScreen />}>
        <ScrollToTop />
        <Routes>
          <Route path="/activities/:rideId" element={<PublicPreview />} />
          <Route path="/rides/:rideId" element={<PublicPreview />} />
          <Route path="/ride/:rideId" element={<PublicPreview />} />
          <Route path="/climbs/:climbId" element={<PublicPreview />} />
          <Route path="/climb/:climbId" element={<PublicPreview />} />
          <Route path="/segments/:climbId" element={<PublicPreview />} />
          <Route path="/riders/:identifier" element={<PublicPreview />} />
          <Route path="/rider/:identifier" element={<PublicPreview />} />
          <Route path="/athletes/:identifier" element={<PublicPreview />} />
          <Route path="*" element={<NotFound />} />
        </Routes>
      </Suspense>
    );
  }

  return (
    <>
      <ReturnUrlHandler pause={needsOnboarding} />

      <Suspense fallback={authHandoffActive ? <AuthHandoffScreen /> : <AppBootScreen />}>
        <Routes location={location.pathname === '/upload' ? readUploadReturnTo(location.state) : location}>
          <Route
            path="/onboarding"
            element={needsOnboarding
              ? (
                <Onboarding
                  initialStep={firstRidePending ? 'first_ride' : 'identity'}
                  onComplete={handleOnboardingComplete}
                  onIdentitySaved={handleOnboardingIdentitySaved}
                  onReady={handleAuthenticatedSurfaceReady}
                />
              )
              : <Navigate to={postOnboardingDestinationRef.current ?? '/'} replace />
            }
          />

          <Route element={dashboardShell}>
            <Route path="/" element={<ActivityFeed isConnected />} />
            <Route path="/dashboard" element={<ActivityFeed isConnected />} />
            <Route path="/invite/:inviteCode" element={<Navigate to="/" replace />} />
            <Route path="/profile" element={<Profile />} />
            <Route path="/athletes/:beetleNumber" element={<Profile />} />

            <Route path="/training" element={<LegacyProfileTabRedirect tab="rides" />} />
            <Route path="/my-activities" element={<LegacyProfileTabRedirect tab="rides" />} />
            <Route path="/data" element={<LegacyProfileTabRedirect tab="training" />} />
            <Route path="/portfolio" element={<LegacyProfileTabRedirect tab="portfolio" />} />

            <Route path="/map" element={<LegacyMapRedirect />} />
            <Route path="/climbs" element={<Climbs />} />
            <Route path="/vaults" element={<LegacyVaultsRedirect />} />
            <Route path="/vaults/:vaultId" element={<LegacyVaultDetailRedirect />} />
            <Route path="/find-friends" element={<LegacyFindRidersRedirect />} />
            <Route path="/upload" element={<Upload />} />

            <Route path="/activities/:activityId/climbs/:climbId/analysis" element={<RideView />} />
            <Route path="/activities/:activityId/analysis" element={<RideView />} />
            <Route path="/activities/:activityId/log" element={<RideView />} />
            <Route path="/activities/:activityId" element={<RideView />} />
            <Route path="/rides/:activityId" element={<RideView />} />
            <Route path="/ride/:activityId" element={<RideView />} />
            <Route path="/climbs/:climbId/create-vault" element={<CreateVaultView />} />
            <Route path="/climbs/:climbId" element={<ClimbView />} />
            <Route path="/climbs/:climbId/leaderboard" element={<ClimbView />} />
            <Route path="/climbs/:climbId/local-legend" element={<ClimbView />} />
            <Route path="/climb/:climbId" element={<ClimbView />} />
            {/* Back-compat alias: keeps pre-rename bookmarks working. Retire in wdvr.8. */}
            <Route path="/segments/:climbId" element={<ClimbView />} />
            <Route path="/rider/:riderId" element={<Profile />} />
            <Route path="/riders/:riderId" element={<Profile />} />
            <Route path="/settings" element={<Settings />} />
            <Route path="/notifications" element={<Notifications />} />
            <Route
              path="/settings/reports/:reportId"
              element={<NotificationTargetRedirect queryKey="reportId" paramKey="reportId" />}
            />
            <Route
              path="/reports/:reportId"
              element={<NotificationTargetRedirect queryKey="reportId" paramKey="reportId" />}
            />
            <Route
              path="/proofs/:proofId"
              element={<NotificationTargetRedirect queryKey="proofId" paramKey="proofId" />}
            />
            <Route
              path="/proof/:proofId"
              element={<NotificationTargetRedirect queryKey="proofId" paramKey="proofId" />}
            />
            <Route
              path="/scan/tx/:txId"
              element={<NotificationTargetRedirect queryKey="scanTx" paramKey="txId" />}
            />
            <Route
              path="/scan/account/:accountId"
              element={<NotificationTargetRedirect queryKey="scanAccount" paramKey="accountId" />}
            />
            <Route path="/docs" element={<Docs />} />

            <Route path="/admin" element={<AdminDashboard />} />
            <Route path="/admin/significance" element={<Navigate to="/admin" replace />} />

            <Route path="*" element={<NotFound />} />
          </Route>
        </Routes>

        {location.pathname === '/upload' && <Upload />}

        {showSessionRecovery && (
          <Suspense fallback={null}>
            <SessionRecoveryScreen onReLogin={handleReLogin} reason={sessionErrorReason} />
          </Suspense>
        )}
      </Suspense>
    </>
  );
}
