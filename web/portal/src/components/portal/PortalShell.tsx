import { BackgroundFetchIndicator } from '../loading/LoadingSystem';
import { RetainedPage } from './FailureSpecies';
import * as React from 'react';
import { Link, useLocation } from 'react-router-dom';
import {
  ArrowLeft,
  Bell,
  ChevronDown,
  LogOut,
  Menu,
  Search,
  Settings,
  Shield,
  Upload,
  UserCircle,
  Wallet,
  X,
} from 'lucide-react';
import { useAuth } from '../../contexts/AuthContext';
import { useAdminCheck } from '../../hooks/useAdminCheck';
import { useMarkAllNotificationsRead, useMarkNotificationRead, useNotifications, usePortfolio } from '../../hooks/queries';
import type { Notification as PortalNotification } from '../../lib/api';
import { getRiderInitials } from '../../lib/riderIdentity';
import { ABSENT_VALUE, formatInteger } from '../../lib/formatters';
import { describePush, pushStamp } from '../../lib/notificationLedger';
import { PushGlyph } from '../notifications/PushGlyph';
import { getRouteIntentPrefetchProps } from '../../lib/routePrefetch';
import { formatCompactBaseUnits } from '../../lib/tokenAmounts';
import { cn } from '../ui/utils';
import { PortalUtilityLinks } from './PortalUtilityLinks';

type PortalNavItem = {
  title: string;
  href: string;
  match: (pathname: string) => boolean;
};

const PORTAL_TOP_NAV_ITEMS: PortalNavItem[] = [
  {
    title: 'Feed',
    href: '/',
    match: (pathname) => pathname === '/' || pathname === '/dashboard',
  },
  {
    title: 'Map',
    href: '/climbs',
    match: (pathname) => (
      pathname === '/climbs'
      || pathname.startsWith('/climbs/')
      || pathname.startsWith('/climb/')
      || pathname.startsWith('/segments/')
      || pathname === '/vaults'
      || pathname.startsWith('/vaults/')
    ),
  },
];

type PortalShellProps = {
  children: React.ReactNode;
  title: string;
  isConnected: boolean;
  walletAddress: string | null;
  accountName?: string | null;
  showBackButton?: boolean;
  onBack?: () => void;
  onDisconnect: () => void;
  onSearch: () => void;
  onSearchIntent?: () => void;
  onNotifications: () => void;
  onUpload: () => void;
  onUploadIntent?: () => void;
};

function isNavActive(pathname: string, item: PortalNavItem) {
  return item.match(pathname);
}

type ShellBalanceState = 'ready' | 'loading' | 'unavailable';

function AccountBalanceSummary({
  calBalanceBaseUnits,
  dungBalanceBaseUnits,
  state,
}: {
  calBalanceBaseUnits: string | null;
  dungBalanceBaseUnits: string | null;
  state: ShellBalanceState;
}) {
  const calDisplay = state === 'ready' && calBalanceBaseUnits != null
    ? formatCompactBaseUnits(calBalanceBaseUnits, 9)
    : ABSENT_VALUE;
  const dungDisplay = state === 'ready' && dungBalanceBaseUnits != null
    ? formatCompactBaseUnits(dungBalanceBaseUnits, 9)
    : ABSENT_VALUE;
  const stateLabel = state === 'ready' ? 'Account balance' : state === 'loading' ? 'Checking balances' : 'Balances unavailable';

  return (
    <div className="portal-shell-popover__economy" data-state={state} aria-label={stateLabel}>
      <div>
        <span>CAL</span>
        <strong>{calDisplay}</strong>
      </div>
      <div>
        <span>DUNG</span>
        <strong>{dungDisplay}</strong>
      </div>
    </div>
  );
}

function PortalPrimaryNav({
  pathname,
  onNavigate,
  className,
  itemClassName,
}: {
  pathname: string;
  onNavigate?: () => void;
  className?: string;
  itemClassName?: string;
}) {
  return (
    <nav className={cn('portal-shell-primary-nav', className)} aria-label="Primary navigation">
      {PORTAL_TOP_NAV_ITEMS.map((item) => {
        const active = isNavActive(pathname, item);

        return (
          <Link
            key={item.title}
            className={cn('portal-shell-primary-nav__item', itemClassName, active && 'portal-shell-primary-nav__item--active')}
            to={item.href}
            aria-current={active ? 'page' : undefined}
            onClick={onNavigate}
            {...getRouteIntentPrefetchProps(item.href, active)}
          >
            {item.title}
          </Link>
        );
      })}
    </nav>
  );
}

export function PortalShell({
  children,
  title,
  isConnected,
  walletAddress,
  accountName,
  showBackButton = false,
  onBack,
  onDisconnect,
  onSearch,
  onSearchIntent,
  onNotifications,
  onUpload,
  onUploadIntent,
}: PortalShellProps) {
  const location = useLocation();
  const { isAuthenticated, isLoading: authLoading } = useAuth();
  const { isAdmin } = useAdminCheck();
  const notificationsEnabled = isConnected && isAuthenticated && !authLoading;
  const { data: notificationsData } = useNotifications({
    limit: 20,
    refetchInterval: 60_000,
    enabled: notificationsEnabled,
  });
  const markNotificationRead = useMarkNotificationRead();
  const markAllNotificationsRead = useMarkAllNotificationsRead();
  const portfolioQuery = usePortfolio(isConnected);
  const [notificationsOpen, setNotificationsOpen] = React.useState(false);
  const [accountMenuOpen, setAccountMenuOpen] = React.useState(false);
  const [mobileNavOpen, setMobileNavOpen] = React.useState(false);
  const mobileNavButtonRef = React.useRef<HTMLButtonElement>(null);
  const mobileNavPanelRef = React.useRef<HTMLDivElement>(null);
  const unreadCount = notificationsData?.unreadCount ?? 0;
  const notifications = notificationsData?.notifications ?? [];
  const portfolio = portfolioQuery.data;
  const balanceState: ShellBalanceState = portfolio
    ? 'ready'
    : portfolioQuery.isLoading || portfolioQuery.isFetching
      ? 'loading'
      : 'unavailable';
  const accountIdentity = accountName?.trim() || 'Rider account';
  const accountInitials = getRiderInitials(accountName);
  const accountState = isConnected ? 'Signed in' : walletAddress ? 'Account pending' : 'Signed out';
  const showHomeUtilityLinks = location.pathname === '/' || location.pathname === '/dashboard';

  React.useEffect(() => {
    setNotificationsOpen(false);
    setAccountMenuOpen(false);
    setMobileNavOpen(false);
  }, [location.pathname]);

  React.useEffect(() => {
    if (!notificationsOpen && !accountMenuOpen && !mobileNavOpen) return undefined;

    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        setNotificationsOpen(false);
        setAccountMenuOpen(false);
        setMobileNavOpen(false);
      }
    };

    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [notificationsOpen, accountMenuOpen, mobileNavOpen]);

  React.useEffect(() => {
    if (!mobileNavOpen) return undefined;

    const panel = mobileNavPanelRef.current;
    const focusable = panel?.querySelectorAll<HTMLElement>('a[href], button:not(:disabled)');
    const first = focusable?.[0];
    const last = focusable?.[focusable.length - 1];
    const priorOverflow = document.body.style.overflow;
    const focusFrame = window.requestAnimationFrame(() => first?.focus());
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key !== 'Tab' || !first || !last) return;
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first.focus();
      }
    };

    document.body.style.overflow = 'hidden';
    document.addEventListener('keydown', handleKeyDown);
    return () => {
      window.cancelAnimationFrame(focusFrame);
      document.body.style.overflow = priorOverflow;
      document.removeEventListener('keydown', handleKeyDown);
      mobileNavButtonRef.current?.focus();
    };
  }, [mobileNavOpen]);

  const closeActionMenus = React.useCallback(() => {
    setNotificationsOpen(false);
    setAccountMenuOpen(false);
    setMobileNavOpen(false);
  }, []);

  const handleNotificationClick = React.useCallback((notification: PortalNotification) => {
    if (!notification.read) {
      markNotificationRead.mutate(notification.id);
    }
    closeActionMenus();
  }, [closeActionMenus, markNotificationRead]);

  const handleMarkAllNotificationsRead = React.useCallback(() => {
    if (unreadCount > 0) {
      markAllNotificationsRead.mutate();
    }
  }, [markAllNotificationsRead, unreadCount]);

  return (
    <div className="portal-shell">
      <div className="portal-shell__body">
        <header className="portal-shell__header">
          <div className="portal-shell__topbar">
            <div className="portal-shell__topnav-left">
              <Link className="portal-shell__brand" to="/" {...getRouteIntentPrefetchProps('/', location.pathname === '/')}>
                <span className="portal-shell__brand-mark" aria-hidden="true" />
                <span className="portal-shell__brand-name">Boulder Roller</span>
              </Link>

              <button
                className="portal-shell__icon-button portal-shell__search-button"
                type="button"
                onClick={onSearch}
                onMouseEnter={onSearchIntent}
                onFocus={onSearchIntent}
                aria-label="Search"
              >
                <Search className="portal-shell__icon" />
              </button>

              {showBackButton ? (
                <div className="portal-shell__mobile-current">
                  <button className="portal-shell__back-button" type="button" onClick={onBack} aria-label="Return to previous page">
                    <ArrowLeft className="portal-shell__icon" />
                  </button>
                  <span className="portal-shell__title">{title}</span>
                </div>
              ) : (
                <div className="portal-shell__mobile-current">
                  <span className="portal-shell__title">{title}</span>
                </div>
              )}
            </div>

            <PortalPrimaryNav pathname={location.pathname} />

            <div className="portal-shell__actions">
              <button
                ref={mobileNavButtonRef}
                className="portal-shell__icon-button portal-shell__mobile-menu-button"
                type="button"
                onClick={() => {
                  setMobileNavOpen((current) => !current);
                  setNotificationsOpen(false);
                  setAccountMenuOpen(false);
                }}
                aria-label={mobileNavOpen ? 'Close navigation' : 'Open navigation'}
                aria-controls="portal-mobile-navigation"
                aria-expanded={mobileNavOpen}
              >
                {mobileNavOpen ? <X className="portal-shell__icon" /> : <Menu className="portal-shell__icon" />}
              </button>

              <button
                className="portal-shell__icon-button portal-shell__upload-button"
                type="button"
                onClick={onUpload}
                onMouseEnter={onUploadIntent}
                onFocus={onUploadIntent}
                aria-label="Upload ride"
                title="Upload ride"
              >
                <Upload className="portal-shell__icon" />
                <span className="portal-shell__upload-label">Upload ride</span>
              </button>

              <div className="portal-shell__action-menu">
                <button
                  className="portal-shell__icon-button portal-shell__notification-button"
                  type="button"
                  onClick={() => {
                    setNotificationsOpen((current) => !current);
                    setAccountMenuOpen(false);
                    setMobileNavOpen(false);
                  }}
                  aria-label="Open notifications"
                  aria-expanded={notificationsOpen}
                >
                  <Bell className="portal-shell__icon" />
                  {unreadCount > 0 ? (
                    <span className="portal-shell__badge" aria-hidden="true" />
                  ) : null}
                </button>

                {notificationsOpen ? (
                  <div className="portal-shell-popover portal-shell-popover--notifications" role="dialog" aria-label="Notifications">
                    <div className="portal-shell-popover__header">
                      <div>
                        <strong>Notifications</strong>
                        {unreadCount > 0 ? <span>{`${formatInteger(unreadCount)} unread`}</span> : null}
                      </div>
                      {unreadCount > 0 ? (
                        <button
                          type="button"
                          className="portal-shell-popover__word"
                          onClick={handleMarkAllNotificationsRead}
                          disabled={markAllNotificationsRead.isPending}
                        >
                          Clear unread
                        </button>
                      ) : null}
                    </div>

                    <div className="portal-shell-notification-list">
                      {notifications.length > 0 ? (
                        notifications.slice(0, 5).map((notification) => {
                          const push = describePush(notification, pushStamp(notification.createdAt));
                          return (
                            <Link
                              key={notification.id}
                              className="portal-shell-notification"
                              data-state={notification.read ? 'read' : 'unread'}
                              data-kind={push.kind}
                              data-stage1={notification.metadata?.stage1 === true ? 'notification' : undefined}
                              to={push.path}
                              onClick={() => handleNotificationClick(notification)}
                            >
                              <span className="portal-shell-notification__glyph" aria-hidden="true">
                                <PushGlyph kind={push.kind} />
                              </span>
                              <span className="portal-shell-notification__identity">
                                <span className="portal-shell-notification__title">{push.noun}</span>
                                <span className="portal-shell-notification__sub">{push.sub}</span>
                              </span>
                              {push.value ? (
                                <span className="portal-shell-notification__value" title={push.valueTitle}>{push.value}</span>
                              ) : null}
                            </Link>
                          );
                        })
                      ) : (
                        <div className="portal-shell-popover__empty">
                          No notifications yet.
                        </div>
                      )}
                    </div>

                    <button
                      type="button"
                      className="portal-shell-popover__view-all"
                      onClick={() => {
                        closeActionMenus();
                        onNotifications();
                      }}
                    >
                      View all notifications
                    </button>
                  </div>
                ) : null}
              </div>

              <div className="portal-shell__action-menu">
                <button
                  className="portal-shell__account-button"
                  type="button"
                  onClick={() => {
                    setAccountMenuOpen((current) => !current);
                    setNotificationsOpen(false);
                    setMobileNavOpen(false);
                  }}
                  aria-label={`Open account menu for ${accountIdentity}`}
                  aria-expanded={accountMenuOpen}
                >
                  <span className="portal-shell__account-mini-mark" aria-hidden="true">{accountInitials}</span>
                  <ChevronDown className="portal-shell__account-chevron" aria-hidden="true" />
                </button>

                {accountMenuOpen ? (
                  <div className="portal-shell-popover portal-shell-popover--account" role="menu" aria-label="Account menu">
                    <div className="portal-shell-popover__account">
                      <span className="portal-shell__account-mini-mark" aria-hidden="true">{accountInitials}</span>
                      <div>
                        <strong>{accountIdentity}</strong>
                        <span>{accountState}</span>
                      </div>
                    </div>
                    {isConnected ? (
                      <AccountBalanceSummary
                        calBalanceBaseUnits={portfolio?.calBalanceBaseUnits ?? null}
                        dungBalanceBaseUnits={portfolio?.dungBalanceBaseUnits ?? null}
                        state={balanceState}
                      />
                    ) : null}
                    <Link className="portal-shell-popover__menu-item" to="/profile" role="menuitem" onClick={closeActionMenus}>
                      <UserCircle className="portal-shell__icon" />
                      <span>Profile</span>
                    </Link>
                    <Link className="portal-shell-popover__menu-item" to="/profile?tab=portfolio" role="menuitem" onClick={closeActionMenus}>
                      <Wallet className="portal-shell__icon" />
                      <span>Portfolio</span>
                    </Link>
                    <button className="portal-shell-popover__menu-item" type="button" role="menuitem" onClick={() => { closeActionMenus(); onUpload(); }}>
                      <span>Upload ride</span>
                    </button>
                    <Link className="portal-shell-popover__menu-item" to="/settings" role="menuitem" onClick={closeActionMenus}>
                      <Settings className="portal-shell__icon" />
                      <span>Settings</span>
                    </Link>
                    {isAdmin ? (
                      <Link className="portal-shell-popover__menu-item" to="/admin" role="menuitem" onClick={closeActionMenus}>
                        <Shield className="portal-shell__icon" />
                        <span>Admin</span>
                      </Link>
                    ) : null}
                    {isConnected ? (
                      <button
                        type="button"
                        className="portal-shell-popover__menu-item"
                        role="menuitem"
                        onClick={() => {
                          closeActionMenus();
                          onDisconnect();
                        }}
                      >
                        <LogOut className="portal-shell__icon" />
                        <span>Sign out</span>
                      </button>
                    ) : null}
                    {showHomeUtilityLinks ? (
                      <PortalUtilityLinks placement="account" onNavigate={closeActionMenus} />
                    ) : null}
                  </div>
                ) : null}
              </div>
            </div>
          </div>

          {mobileNavOpen ? (
            <>
              <button
                className="portal-shell-mobile-menu__backdrop"
                type="button"
                onClick={() => setMobileNavOpen(false)}
                aria-label="Dismiss navigation"
              />
              <div
                ref={mobileNavPanelRef}
                id="portal-mobile-navigation"
                className="portal-shell-mobile-menu"
                role="dialog"
                aria-modal="true"
                aria-label="Navigation"
              >
                <PortalPrimaryNav
                  pathname={location.pathname}
                  onNavigate={() => setMobileNavOpen(false)}
                  className="portal-shell-primary-nav--mobile-menu"
                  itemClassName="portal-shell-primary-nav__item--mobile-menu"
                />
                <div className="portal-shell-mobile-menu__utilities">
                  <button
                    type="button"
                    className="portal-shell-mobile-menu__utility"
                    onClick={() => {
                      setMobileNavOpen(false);
                      onSearch();
                    }}
                    onMouseEnter={onSearchIntent}
                    onFocus={onSearchIntent}
                  >
                    <Search className="portal-shell__icon" />
                    <span>Search</span>
                  </button>
                </div>
              </div>
            </>
          ) : null}
        <BackgroundFetchIndicator />
        </header>

        <main className="portal-shell__content">
          <RetainedPage>{children}</RetainedPage>
        </main>
      </div>
    </div>
  );
}
