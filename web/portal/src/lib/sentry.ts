import { scrubSentryEvent } from './sentryPrivacy';

interface CaptureContext {
  extra?: Record<string, unknown>;
}

const sentryDsn = import.meta.env.VITE_SENTRY_DSN;
let sentryInitialized = false;
let sentryModulePromise: Promise<typeof import('@sentry/react') | null> | null = null;

async function loadSentryModule() {
  if (!sentryDsn) return null;
  if (!sentryModulePromise) {
    sentryModulePromise = import('@sentry/react').catch(() => null);
  }
  return sentryModulePromise;
}

async function ensureSentryInitialized() {
  if (!sentryDsn) return null;
  const Sentry = await loadSentryModule();
  if (!Sentry) return null;
  if (!sentryInitialized) {
    Sentry.init({
      dsn: sentryDsn,
      environment: import.meta.env.MODE,
      tracesSampleRate: import.meta.env.PROD ? 0.1 : 1.0,
      enabled: import.meta.env.PROD || !!sentryDsn,
      sendDefaultPii: false,
      beforeSend: scrubSentryEvent,
      beforeSendTransaction: scrubSentryEvent,
    });
    sentryInitialized = true;
  }
  return Sentry;
}

export function scheduleSentryInit() {
  if (!sentryDsn) return;

  const start = () => {
    void ensureSentryInitialized();
  };

  if (typeof window !== 'undefined' && 'requestIdleCallback' in window) {
    const idleWindow = window as Window & {
      requestIdleCallback?: (callback: () => void, options?: { timeout: number }) => number;
    };
    idleWindow.requestIdleCallback?.(start, { timeout: 2000 });
    return;
  }

  globalThis.setTimeout(start, 1200);
}

export function captureException(error: unknown, context?: CaptureContext) {
  if (!sentryDsn) return;
  void ensureSentryInitialized().then((Sentry) => {
    if (!Sentry) return;
    Sentry.captureException(error, context);
  });
}
