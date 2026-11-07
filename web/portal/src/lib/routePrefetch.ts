type RouteImporter = () => Promise<unknown>;
type PrefetchIntent = 'hover' | 'focus' | 'touch' | 'history';
type PrefetchWeight = 'standard' | 'heavy';

interface RoutePrefetchConfig {
  importer: RouteImporter;
  weight?: PrefetchWeight;
}

const SAVE_DATA_TYPES = new Set(['slow-2g', '2g']);
const HEAVY_ROUTE_HOVER_DELAY_MS = 120;
const STANDARD_ROUTE_HOVER_DELAY_MS = 80;
const prefetchedRoutes = new Set<string>();
const inflightPrefetches = new Map<string, Promise<unknown>>();

const ROUTE_PREFETCHERS: Record<string, RoutePrefetchConfig> = {
  '/': { importer: () => import('../components/feed/ActivityFeed') },
  '/profile': { importer: () => import('../pages/Profile') },
  '/map': { importer: () => import('../pages/Climbs'), weight: 'heavy' },
  '/climbs': { importer: () => import('../pages/Climbs'), weight: 'heavy' },
  '/vaults': { importer: () => import('../pages/Climbs'), weight: 'heavy' },
  '/settings': { importer: () => import('../pages/Settings'), weight: 'heavy' },
  '/notifications': { importer: () => import('../pages/Notifications') },
  '/admin': { importer: () => import('../pages/AdminDashboard'), weight: 'heavy' },
  '/docs': { importer: () => import('../pages/Docs') },
};

function normalizeRoute(path: string): string {
  const cleanPath = (path || '/').split('?')[0].split('#')[0] || '/';

  if (cleanPath.startsWith('/vaults/')) return '/climbs/view';
  if (cleanPath.startsWith('/activities/')) return '/activities/view';
  if (cleanPath.startsWith('/climbs/') && cleanPath.endsWith('/create-vault')) return '/climbs/create-vault';
  if (cleanPath.startsWith('/climbs/')) return '/climbs/view';
  // Back-compat alias: pre-rename `/segments/:id` still resolves. Retire in wdvr.8.
  if (cleanPath.startsWith('/segments/')) return '/climbs/view';
  if (cleanPath.startsWith('/athletes/')) return '/profile';
  if (['/training', '/my-activities', '/data', '/portfolio'].includes(cleanPath)) return '/profile';
  if (cleanPath === '/find-friends') return '/';

  return cleanPath === '' ? '/' : cleanPath;
}

function getRoutePrefetchConfig(path: string): RoutePrefetchConfig | null {
  const normalized = normalizeRoute(path);

  if (normalized === '/activities/view') {
    return {
      importer: () => import('../pages/RideView'),
      weight: 'heavy',
    };
  }

  if (normalized === '/climbs/view') {
    return {
      importer: () => import('../pages/ClimbView'),
      weight: 'heavy',
    };
  }

  if (normalized === '/climbs/create-vault') {
    return {
      importer: () => import('../pages/CreateVaultView'),
      weight: 'heavy',
    };
  }

  return ROUTE_PREFETCHERS[normalized] ?? null;
}

function canPrefetchRoute(path: string, intent: PrefetchIntent): boolean {
  const config = getRoutePrefetchConfig(path);
  if (!config) return false;

  if (config.weight === 'heavy') {
    return intent === 'touch';
  }

  return true;
}

export function shouldPrefetchRouteModules(): boolean {
  if (typeof navigator === 'undefined') return true;

  const connection = (navigator as Navigator & {
    connection?: { saveData?: boolean; effectiveType?: string };
  }).connection;

  if (!connection) return true;
  if (connection.saveData) return false;

  return !SAVE_DATA_TYPES.has(connection.effectiveType || '');
}

export function prefetchRoute(path: string, intent: PrefetchIntent = 'hover'): void {
  if (!shouldPrefetchRouteModules()) return;

  const normalized = normalizeRoute(path);
  if (!canPrefetchRoute(normalized, intent)) return;
  if (prefetchedRoutes.has(normalized)) return;

  const existingPrefetch = inflightPrefetches.get(normalized);
  if (existingPrefetch) return;

  const config = getRoutePrefetchConfig(normalized);
  if (!config) return;

  const prefetchPromise = config.importer()
    .then(() => {
      prefetchedRoutes.add(normalized);
    })
    .catch(() => {
      // Opportunistic prefetch failures should never affect navigation.
    })
    .finally(() => {
      inflightPrefetches.delete(normalized);
    });

  inflightPrefetches.set(normalized, prefetchPromise);
}

export function getRouteIntentPrefetchProps(path: string, disabled: boolean = false) {
  if (disabled) return {};

  let hoverTimer: number | null = null;
  const config = getRoutePrefetchConfig(path);
  const hoverDelayMs = config?.weight === 'heavy'
    ? HEAVY_ROUTE_HOVER_DELAY_MS
    : STANDARD_ROUTE_HOVER_DELAY_MS;

  const clearHoverTimer = () => {
    if (hoverTimer !== null) {
      window.clearTimeout(hoverTimer);
      hoverTimer = null;
    }
  };

  const schedulePrefetch = (intent: PrefetchIntent) => {
    if (intent === 'hover') {
      if (!canPrefetchRoute(path, intent)) return;
      clearHoverTimer();
      hoverTimer = window.setTimeout(() => {
        prefetchRoute(path, intent);
        hoverTimer = null;
      }, hoverDelayMs);
      return;
    }

    clearHoverTimer();
    prefetchRoute(path, intent);
  };

  const triggerPrefetch = () => {
    schedulePrefetch('hover');
  };

  return {
    onMouseEnter: triggerPrefetch,
    onMouseLeave: clearHoverTimer,
    onBlur: clearHoverTimer,
    onFocus: () => schedulePrefetch('focus'),
    onTouchStart: () => schedulePrefetch('touch'),
    onPointerDown: () => schedulePrefetch('touch'),
  };
}
