import React from 'react';
import { createRoot } from 'react-dom/client';
import './index.css';
import './styles/portal-spine.css';
import './styles/portal-surface-polish.css';
import './styles/portal-feed-room.css';
import './styles/portal-profile-room.css';
import './styles/portal-portfolio-room.css';
import './styles/portal-settings-room.css';
import './styles/portal-climbs-room.css';
import './styles/portal-rides-room.css';
import './styles/portal-training-room.css';
import './styles/portal-notifications-room.css';
import './styles/portal-guide-room.css';
import './styles/portal-search-sheet.css';
import './styles/portal-access-room.css';
import './styles/loading-system.css';
import { scheduleSentryInit } from './lib/sentry';
import {
  clearStaleChunkRecoveryGuardAfterBoot,
  installStaleChunkRecoveryHandlers,
} from './lib/staleChunkRecovery';

const DISABLE_LOCALHOST_CANONICAL_REDIRECT =
  String(import.meta.env.VITE_DISABLE_LOCALHOST_REDIRECT || '').toLowerCase() === 'true';

function redirect127ToLocalhostIfNeeded(): boolean {
  if (DISABLE_LOCALHOST_CANONICAL_REDIRECT) return false;
  if (typeof window === 'undefined') return false;
  if (window.location.hostname !== '127.0.0.1') return false;

  const port = window.location.port ? `:${window.location.port}` : '';
  const target = `${window.location.protocol}//localhost${port}${window.location.pathname}${window.location.search}${window.location.hash}`;
  window.location.replace(target);
  return true;
}

function schedulePerformanceMonitoring(): void {
  const forceEnable = String(import.meta.env.VITE_ENABLE_RUM || '').toLowerCase() === 'true';
  if (!import.meta.env.PROD && !forceEnable) return;

  const start = () => {
    void import('./lib/performance')
      .then((module) => {
        module.installPerformanceMonitoring();
      })
      .catch(() => {
        // Metrics collection should never block app boot.
      });
  };

  const idleWindow = window as Window & {
    requestIdleCallback?: (callback: () => void, options?: { timeout: number }) => number;
  };

  if (typeof idleWindow.requestIdleCallback === 'function') {
    idleWindow.requestIdleCallback(start, { timeout: 2500 });
    return;
  }

  window.setTimeout(start, 1400);
}

installStaleChunkRecoveryHandlers();
clearStaleChunkRecoveryGuardAfterBoot();

scheduleSentryInit();
schedulePerformanceMonitoring();

const redirected = redirect127ToLocalhostIfNeeded();

async function bootApp(): Promise<void> {
  const { default: App } = await import('./App');

  const appRoot = import.meta.env.DEV ? (
    <App />
  ) : (
    <React.StrictMode>
      <App />
    </React.StrictMode>
  );

  createRoot(document.getElementById('root')!).render(appRoot);
}

if (!redirected) {
  void bootApp();
}
