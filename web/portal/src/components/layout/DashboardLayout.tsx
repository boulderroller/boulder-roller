import { BrowserTitleProvider } from '../../contexts/BrowserTitleContext';
import { useEffect, useState, lazy, Suspense, type ReactNode } from 'react';
import { useLocation, useNavigate } from 'react-router-dom';
import StubModeBanner from './StubModeBanner';
import { PortalShell } from '../portal/PortalShell';

const SearchModal = lazy(() => import('../modals/SearchModal'));
const Upload = lazy(() => import('../../pages/Upload'));

const preloadUploadFlow = () => import('../../pages/Upload');
const preloadSearchModal = () => import('../modals/SearchModal');
const PORTAL_TOP_LEVEL_ROUTES = new Set([
  '/',
  '/dashboard',
  '/climbs',
  '/map',
]);

function getShellHeading(pathname: string, search: string) {
  if (pathname === '/' || pathname === '/dashboard') return 'Feed';
  if (pathname === '/settings') return 'Settings';
  if (pathname === '/profile') {
    const profileTab = new URLSearchParams(search).get('tab');
    if (profileTab === 'rides') return 'My rides';
    if (profileTab === 'training') return 'Training';
    if (profileTab === 'portfolio') return 'Portfolio';
    return 'Profile';
  }
  if (
    pathname.startsWith('/activities/')
    || pathname.startsWith('/rides/')
    || pathname.startsWith('/ride/')
  ) return 'Ride';
  if (pathname === '/map' || pathname === '/climbs') return 'Climbs';
  if (pathname === '/vaults') return 'Vaults';
  if (
    pathname.startsWith('/climbs/')
    || pathname.startsWith('/climb/')
    || pathname.startsWith('/segments/')
  ) return 'Climb';
  if (pathname.startsWith('/vaults/')) return 'Vault';
  if (pathname === '/notifications') return 'Notifications';
  if (pathname === '/upload') return 'Upload ride';
  if (pathname === '/docs') return 'Docs';
  if (pathname === '/admin') return 'Admin';
  if (pathname.startsWith('/rider/')) return 'Rider';
  return 'Not Found';
}

interface DashboardLayoutProps {
  children: ReactNode;
  isConnected: boolean;
  walletAddress: string | null;
  accountName?: string | null;
  onDisconnect: () => void;
}

export default function DashboardLayout({ 
  children, 
  isConnected, 
  walletAddress, 
  accountName,
  onDisconnect 
}: DashboardLayoutProps) {
  const location = useLocation();
  const navigate = useNavigate();
  const routeSearchCategory = new URLSearchParams(location.search).get('search') === 'riders'
    ? 'riders'
    : null;
  const shellHeading = getShellHeading(location.pathname, location.search);
  
  // Modal States
  const [showSearchModal, setShowSearchModal] = useState(false);
  const [showUploadSheet, setShowUploadSheet] = useState(false);

  useEffect(() => {
    setShowUploadSheet(false);
  }, [location.key]);

  // Handlers
  const handleUpload = () => {
    setShowUploadSheet(true);
  };
  const handleUploadIntent = () => {
    void preloadUploadFlow();
  };

  const handleSearch = () => setShowSearchModal(true);
  const handleSearchClose = () => {
    setShowSearchModal(false);
    if (!routeSearchCategory) return;

    const params = new URLSearchParams(location.search);
    params.delete('search');
    const search = params.toString();
    navigate(
      { pathname: location.pathname, search: search ? `?${search}` : '', hash: location.hash },
      { replace: true },
    );
  };
  const handleSearchIntent = () => {
    void preloadSearchModal();
  };
  
  const handleNotifications = () => {
    navigate('/notifications');
  };

  const showBackButton = !PORTAL_TOP_LEVEL_ROUTES.has(location.pathname);

  return (
    <BrowserTitleProvider>
      <PortalShell
        title={shellHeading}
        isConnected={isConnected}
        walletAddress={walletAddress}
        accountName={accountName}
        showBackButton={showBackButton}
        onBack={() => navigate(-1)}
        onDisconnect={onDisconnect}
        onSearch={handleSearch}
        onSearchIntent={handleSearchIntent}
        onNotifications={handleNotifications}
        onUpload={handleUpload}
        onUploadIntent={handleUploadIntent}
      >
        <StubModeBanner />
        {children}

        <Suspense fallback={null}>
          {showUploadSheet && <Upload onClose={() => setShowUploadSheet(false)} />}
          {(showSearchModal || routeSearchCategory) && (
            <SearchModal
              initialCategory={routeSearchCategory ?? 'all'}
              onClose={handleSearchClose}
            />
          )}
        </Suspense>
      </PortalShell>
    </BrowserTitleProvider>
  );
}
