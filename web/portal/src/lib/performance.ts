import { formatFixed } from './formatters';

const API_URL = (import.meta.env.VITE_API_URL || '/api').replace(/\/$/, '');
const LOADING_METRIC_EVENT = 'br:loading:metric';
const FLUSH_INTERVAL_MS = 15_000;
const MAX_BATCH_SIZE = 60;
const MAX_QUEUE_SIZE = 120;
const ROUTE_LOAD_MIN_MS = 120;

type VitalMetricName =
  | 'lcp'
  | 'inp'
  | 'cls'
  | 'fcp'
  | 'ttfb'
  | 'tbt'
  | 'route_load'
  | 'background_fetch';

type DeviceClass = 'mobile' | 'tablet' | 'desktop' | 'unknown';
type VitalRating = 'good' | 'needs_improvement' | 'poor';

interface VitalSample {
  metric: VitalMetricName;
  value: number;
  rating: VitalRating;
  route: string;
  device: DeviceClass;
  timestamp: string;
  source: string;
  visibility_state: DocumentVisibilityState;
  navigation_type?: string;
  pending_count?: number;
}

interface LoadingMetricDetail {
  surface?: string;
  durationMs?: number;
  pendingCount?: number;
}

interface RumEnvelope {
  sampled: boolean;
  metrics: VitalSample[];
}

let initialized = false;
let sampleEnabled = false;
let flushTimerId: number | null = null;
let queue: VitalSample[] = [];
let pendingLcp: number | null = null;
let lcpReported = false;
let clsValue = 0;
let clsReported = false;
let inpValue: number | null = null;
let inpReported = false;
let fcpReported = false;
let ttfbReported = false;
let currentRoute = '/';
let currentRouteStartedAt = 0;
let currentRouteBlockingTimeMs = 0;

function normalizeRoute(value: string): string {
  const route = (value || '/').split('?')[0].trim() || '/';
  return route.startsWith('/') ? route : `/${route}`;
}

function getDeviceClass(): DeviceClass {
  if (typeof window === 'undefined' || typeof navigator === 'undefined') return 'unknown';

  const width = window.innerWidth || 0;
  const ua = navigator.userAgent.toLowerCase();
  const isTabletUa = /\b(ipad|tablet)\b/.test(ua);
  const isMobileUa = /\b(mobi|android|iphone)\b/.test(ua);

  if (isTabletUa || (width >= 768 && width < 1024)) return 'tablet';
  if (isMobileUa || (width > 0 && width < 768)) return 'mobile';
  if (width >= 1024) return 'desktop';
  return 'unknown';
}

function getNavigationType(): string | undefined {
  if (typeof performance === 'undefined') return undefined;
  const navigationEntries = performance.getEntriesByType('navigation') as PerformanceNavigationTiming[];
  if (!navigationEntries.length) return undefined;
  return navigationEntries[0].type;
}

function classifyRating(metric: VitalMetricName, value: number): VitalRating {
  switch (metric) {
    case 'lcp':
      if (value <= 2500) return 'good';
      if (value <= 4000) return 'needs_improvement';
      return 'poor';
    case 'inp':
      if (value <= 200) return 'good';
      if (value <= 500) return 'needs_improvement';
      return 'poor';
    case 'cls':
      if (value <= 0.1) return 'good';
      if (value <= 0.25) return 'needs_improvement';
      return 'poor';
    case 'fcp':
      if (value <= 1800) return 'good';
      if (value <= 3000) return 'needs_improvement';
      return 'poor';
    case 'ttfb':
      if (value <= 800) return 'good';
      if (value <= 1800) return 'needs_improvement';
      return 'poor';
    case 'tbt':
      if (value <= 200) return 'good';
      if (value <= 600) return 'needs_improvement';
      return 'poor';
    case 'route_load':
      if (value <= 1200) return 'good';
      if (value <= 2500) return 'needs_improvement';
      return 'poor';
    case 'background_fetch':
      if (value <= 700) return 'good';
      if (value <= 1600) return 'needs_improvement';
      return 'poor';
    default:
      return 'poor';
  }
}

function enqueueMetric(
  metric: VitalMetricName,
  rawValue: number,
  options: {
    route?: string;
    source?: string;
    navigationType?: string;
    pendingCount?: number;
  } = {},
): void {
  if (!sampleEnabled) return;
  if (!Number.isFinite(rawValue) || rawValue < 0) return;

  const value = metric === 'cls'
    ? Number(formatFixed(rawValue, 4))
    : Math.round(rawValue);
  const route = normalizeRoute(options.route ?? currentRoute ?? window.location.pathname);

  const sample: VitalSample = {
    metric,
    value,
    rating: classifyRating(metric, value),
    route,
    device: getDeviceClass(),
    timestamp: new Date().toISOString(),
    source: options.source ?? 'web-vitals',
    visibility_state: document.visibilityState,
    navigation_type: options.navigationType ?? getNavigationType(),
    pending_count: options.pendingCount,
  };

  queue.push(sample);
  if (queue.length > MAX_QUEUE_SIZE) {
    queue = queue.slice(queue.length - MAX_QUEUE_SIZE);
  }
}

function sendRumPayload(payload: RumEnvelope): void {
  const endpoint = `${API_URL}/metadata/web-vitals`;
  const body = JSON.stringify(payload);

  if (typeof navigator !== 'undefined' && typeof navigator.sendBeacon === 'function') {
    const sent = navigator.sendBeacon(endpoint, new Blob([body], { type: 'application/json' }));
    if (sent) return;
  }

  void fetch(endpoint, {
    method: 'POST',
    credentials: 'include',
    keepalive: true,
    headers: { 'Content-Type': 'application/json' },
    body,
  }).catch(() => {
    // Drop metrics silently when offline or endpoint is unavailable.
  });
}

function flushMetrics(): void {
  if (!sampleEnabled || !queue.length) return;

  while (queue.length > 0) {
    const payload: RumEnvelope = {
      sampled: true,
      metrics: queue.splice(0, MAX_BATCH_SIZE),
    };
    sendRumPayload(payload);
  }
}

function finalizeCurrentRouteMetrics(): void {
  if (!sampleEnabled || currentRouteStartedAt <= 0) return;

  const now = performance.now();
  const routeDuration = now - currentRouteStartedAt;
  if (routeDuration >= ROUTE_LOAD_MIN_MS) {
    enqueueMetric('route_load', routeDuration, {
      route: currentRoute,
      source: 'route-lifecycle',
      navigationType: 'spa',
    });
  }

  if (currentRouteBlockingTimeMs > 0) {
    enqueueMetric('tbt', currentRouteBlockingTimeMs, {
      route: currentRoute,
      source: 'longtask',
      navigationType: 'spa',
    });
  }

  currentRouteStartedAt = now;
  currentRouteBlockingTimeMs = 0;
}

function setupRouteTracking(): void {
  if (typeof window === 'undefined') return;

  const onRouteChanged = () => {
    const nextRoute = normalizeRoute(window.location.pathname);
    if (nextRoute === currentRoute) return;
    finalizeCurrentRouteMetrics();
    currentRoute = nextRoute;
  };

  const originalPushState = history.pushState;
  const originalReplaceState = history.replaceState;

  history.pushState = function patchedPushState(...args: Parameters<History['pushState']>) {
    originalPushState.apply(this, args);
    onRouteChanged();
  };

  history.replaceState = function patchedReplaceState(...args: Parameters<History['replaceState']>) {
    originalReplaceState.apply(this, args);
    onRouteChanged();
  };

  window.addEventListener('popstate', onRouteChanged);
  window.addEventListener('hashchange', onRouteChanged);
}

function setupLoadingMetricForwarding(): void {
  window.addEventListener(LOADING_METRIC_EVENT, (event: Event) => {
    const detail = (event as CustomEvent<LoadingMetricDetail>).detail;
    if (!detail || typeof detail.durationMs !== 'number') return;

    enqueueMetric('background_fetch', detail.durationMs, {
      route: currentRoute,
      source: detail.surface || 'background_fetch',
      pendingCount: detail.pendingCount,
    });
  });
}

function setupPerformanceObservers(): void {
  const observerList: PerformanceObserver[] = [];
  const observe = (
    type: string,
    callback: (list: PerformanceObserverEntryList) => void,
    init?: PerformanceObserverInit,
  ) => {
    try {
      const observer = new PerformanceObserver((list) => callback(list));
      observer.observe({ type, buffered: true, ...init } as PerformanceObserverInit);
      observerList.push(observer);
    } catch {
      // Ignore unsupported entry types.
    }
  };

  observe('paint', (list) => {
    if (fcpReported) return;
    for (const entry of list.getEntries()) {
      if (entry.name === 'first-contentful-paint') {
        fcpReported = true;
        enqueueMetric('fcp', entry.startTime, { route: currentRoute });
      }
    }
  });

  observe('largest-contentful-paint', (list) => {
    const entries = list.getEntries();
    const lastEntry = entries[entries.length - 1];
    if (lastEntry) {
      pendingLcp = lastEntry.startTime;
    }
  });

  observe('layout-shift', (list) => {
    for (const entry of list.getEntries()) {
      const shift = entry as PerformanceEntry & { hadRecentInput?: boolean; value?: number };
      if (shift.hadRecentInput) continue;
      if (typeof shift.value === 'number') {
        clsValue += shift.value;
      }
    }
  });

  observe('event', (list) => {
    for (const entry of list.getEntries()) {
      const interaction = entry as PerformanceEntry & { interactionId?: number };
      if (!interaction.interactionId) continue;
      inpValue = Math.max(inpValue ?? 0, entry.duration);
    }
  }, { durationThreshold: 40 } as PerformanceObserverInit);

  observe('longtask', (list) => {
    for (const entry of list.getEntries()) {
      const blockingTime = Math.max(0, entry.duration - 50);
      if (blockingTime <= 0) continue;
      currentRouteBlockingTimeMs += blockingTime;
    }
  });

  if (!ttfbReported) {
    const navigationEntries = performance.getEntriesByType('navigation') as PerformanceNavigationTiming[];
    if (navigationEntries.length) {
      const ttfb = navigationEntries[0].responseStart;
      ttfbReported = true;
      enqueueMetric('ttfb', ttfb, { route: currentRoute });
    }
  }

  const flushAndDisconnect = () => {
    finalizeAndFlush();
    observerList.forEach((observer) => observer.disconnect());
  };

  window.addEventListener('pagehide', flushAndDisconnect, { once: true });
}

function finalizeAndFlush(): void {
  if (!sampleEnabled) return;

  if (!lcpReported && pendingLcp !== null) {
    lcpReported = true;
    enqueueMetric('lcp', pendingLcp, { route: currentRoute });
  }

  if (!clsReported) {
    clsReported = true;
    enqueueMetric('cls', clsValue, { route: currentRoute });
  }

  if (!inpReported && inpValue !== null) {
    inpReported = true;
    enqueueMetric('inp', inpValue, { route: currentRoute });
  }

  finalizeCurrentRouteMetrics();
  flushMetrics();
}

export function installPerformanceMonitoring(): void {
  if (initialized || typeof window === 'undefined' || typeof document === 'undefined') return;
  initialized = true;

  const forceEnable = String(import.meta.env.VITE_ENABLE_RUM || '').toLowerCase() === 'true';
  const configuredSampleRate = Number(import.meta.env.VITE_RUM_SAMPLE_RATE || '0.25');
  const safeSampleRate = Number.isFinite(configuredSampleRate)
    ? Math.min(1, Math.max(0, configuredSampleRate))
    : 0.25;

  if (!import.meta.env.PROD && !forceEnable) return;
  if (safeSampleRate <= 0) return;

  sampleEnabled = Math.random() <= safeSampleRate;
  if (!sampleEnabled) return;

  currentRoute = normalizeRoute(window.location.pathname);
  currentRouteStartedAt = performance.now();

  flushTimerId = window.setInterval(() => {
    flushMetrics();
  }, FLUSH_INTERVAL_MS);

  setupRouteTracking();
  setupLoadingMetricForwarding();
  setupPerformanceObservers();

  document.addEventListener('visibilitychange', () => {
    if (document.visibilityState === 'hidden') {
      finalizeAndFlush();
    }
  });
}

export function flushPerformanceMetrics(): void {
  finalizeAndFlush();
  if (flushTimerId !== null) {
    window.clearInterval(flushTimerId);
    flushTimerId = null;
  }
}
