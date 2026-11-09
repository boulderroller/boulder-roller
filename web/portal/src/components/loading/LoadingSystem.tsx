import { useEffect, useRef, useState } from 'react';
import { useIsFetching, useIsMutating } from '@tanstack/react-query';
import { cn } from '../ui/utils';
import { SlotRows } from './Slot';
import { useOffline } from '../portal/FailureSpecies';

type LoadingMetricSurface = 'background_fetch';

interface LoadingMetricDetail {
  surface: LoadingMetricSurface;
  durationMs: number;
  pendingCount: number;
  timestamp: string;
}

const LOADING_METRIC_EVENT = 'br:loading:metric';

interface DelayedVisibilityOptions {
  delayMs?: number;
  minVisibleMs?: number;
}

export function usePrefersReducedMotion() {
  const [prefersReducedMotion, setPrefersReducedMotion] = useState(false);

  useEffect(() => {
    if (typeof window === 'undefined' || !window.matchMedia) return;

    const mediaQuery = window.matchMedia('(prefers-reduced-motion: reduce)');
    const updatePreference = () => setPrefersReducedMotion(mediaQuery.matches);
    updatePreference();

    mediaQuery.addEventListener('change', updatePreference);
    return () => mediaQuery.removeEventListener('change', updatePreference);
  }, []);

  return prefersReducedMotion;
}

export function useDelayedVisibility(
  isActive: boolean,
  options: DelayedVisibilityOptions = {},
) {
  const { delayMs = 160, minVisibleMs = 420 } = options;
  const [isVisible, setIsVisible] = useState(false);
  const visibleSinceRef = useRef<number | null>(null);

  useEffect(() => {
    let timer: ReturnType<typeof setTimeout> | undefined;

    if (isActive) {
      if (!isVisible) {
        timer = setTimeout(() => {
          visibleSinceRef.current = performance.now();
          setIsVisible(true);
        }, delayMs);
      }
      return () => {
        if (timer) clearTimeout(timer);
      };
    }

    if (!isVisible) return;

    const visibleFor = visibleSinceRef.current
      ? performance.now() - visibleSinceRef.current
      : minVisibleMs;
    const remaining = Math.max(0, minVisibleMs - visibleFor);

    timer = setTimeout(() => {
      visibleSinceRef.current = null;
      setIsVisible(false);
    }, remaining);

    return () => {
      if (timer) clearTimeout(timer);
    };
  }, [delayMs, isActive, isVisible, minVisibleMs]);

  return isVisible;
}

function emitLoadingMetric(detail: LoadingMetricDetail) {
  if (typeof window === 'undefined') return;
  window.dispatchEvent(new CustomEvent(LOADING_METRIC_EVENT, { detail }));
}

export { PageLoading as RouteLoadingFallback } from './PageLoading';

export function LoadingRows({ label, description, rows = 4 }: { label: string; description?: string; rows?: number }) {
  return <div aria-busy="true"><SlotRows count={rows} /><span className="sr-only" role="status">{label}{description ? ` ${description}` : ''}</span></div>;
}

interface InlinePendingStateProps {
  label: string;
  className?: string;
}

export function InlinePendingState({ label, className }: InlinePendingStateProps) {
  return (
    <span role="status" aria-live="polite" className={cn('inline-pending-state', className)}>
      <span className="inline-pending-state__label">{label}</span>
    </span>
  );
}

export function BackgroundFetchIndicator() {
  const pendingQueries = useIsFetching();
  const pendingMutations = useIsMutating();
  const pendingCount = pendingQueries + pendingMutations;
  const isActive = pendingCount > 0;
  const isVisible = useDelayedVisibility(isActive);
  const visibleSinceRef = useRef<number | null>(null);

  useEffect(() => {
    if (isVisible && visibleSinceRef.current === null) {
      visibleSinceRef.current = performance.now();
      return;
    }

    if (!isVisible && visibleSinceRef.current !== null) {
      const durationMs = Math.round(performance.now() - visibleSinceRef.current);
      visibleSinceRef.current = null;

      emitLoadingMetric({
        surface: 'background_fetch',
        durationMs,
        pendingCount,
        timestamp: new Date().toISOString(),
      });
    }
  }, [isVisible, pendingCount]);

  const offline = useOffline();

  return (
    <>
      <div className="shell-live-rule" data-live={isVisible} data-offline={offline} aria-hidden="true" />
      <div className="sr-only" role="status" aria-live="polite">
        {isVisible && !offline ? 'Refreshing data in the background.' : ''}
      </div>
    </>
  );
}
