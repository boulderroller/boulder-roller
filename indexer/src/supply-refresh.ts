import { Connection } from '@solana/web3.js';
import { config } from './config';
import {
  DungMintSupplyObservation,
  refreshDungMintSupply,
} from './supply';

export const MAX_DUNG_SUPPLY_STALE_MS = 5 * 60 * 1000;
export const DEFAULT_DUNG_SUPPLY_REFRESH_INTERVAL_MS = 4 * 60 * 1000;
export const MAX_DUNG_SUPPLY_REFRESH_INTERVAL_MS = DEFAULT_DUNG_SUPPLY_REFRESH_INTERVAL_MS;

type TimerHandle = ReturnType<typeof setInterval> | { unref?: () => void };
type RefreshLogger = Pick<Console, 'log' | 'warn' | 'error'>;

export type DungSupplyRefreshLoop = {
  runNow: () => Promise<DungMintSupplyObservation>;
  stop: () => void;
};

type DungSupplyRefreshOptions = {
  intervalMs?: number;
  refresh?: () => Promise<DungMintSupplyObservation>;
  schedule?: (callback: () => Promise<void>, intervalMs: number) => TimerHandle;
  cancel?: (handle: TimerHandle) => void;
  logger?: RefreshLogger;
};

export function requireBoundedDungSupplyRefreshInterval(intervalMs: number): number {
  if (
    !Number.isSafeInteger(intervalMs)
    || intervalMs <= 0
    || intervalMs > MAX_DUNG_SUPPLY_REFRESH_INTERVAL_MS
  ) {
    throw new Error(
      `DUNG supply refresh interval must be a positive integer no greater than ${MAX_DUNG_SUPPLY_REFRESH_INTERVAL_MS} ms`
    );
  }
  return intervalMs;
}

/**
 * Refresh SPL supply independently of WebSocket state and the daily full
 * reconciliation. Concurrent ticks share one finalized RPC observation.
 */
export function startDungSupplyRefreshLoop(
  options: DungSupplyRefreshOptions = {}
): DungSupplyRefreshLoop {
  const intervalMs = requireBoundedDungSupplyRefreshInterval(
    options.intervalMs ?? config.dungSupplyRefreshIntervalMs
  );
  const logger = options.logger ?? console;
  const connection = options.refresh
    ? null
    : new Connection(config.rpcUrl, 'finalized');
  const refresh = options.refresh
    ?? (() => refreshDungMintSupply(connection as Connection));
  const schedule = options.schedule
    ?? ((callback, delay) => setInterval(callback, delay));
  const cancel = options.cancel
    ?? ((handle) => clearInterval(handle as ReturnType<typeof setInterval>));

  let active: Promise<DungMintSupplyObservation> | null = null;
  let stopped = false;

  const runNow = (): Promise<DungMintSupplyObservation> => {
    if (active) return active;
    active = refresh().finally(() => {
      active = null;
    });
    return active;
  };

  const tick = async (): Promise<void> => {
    if (stopped) return;
    try {
      const observation = await runNow();
      if (observation.written) {
        logger.log(
          `[Supply] Finalized periodic refresh ${observation.amount} at slot ${observation.slot}`
        );
      } else {
        logger.warn(
          `[Supply] Ignored non-advancing periodic observation at slot ${observation.slot}`
        );
      }
    } catch (err) {
      logger.error('[Supply] Periodic finalized refresh failed:', err);
    }
  };

  const timer = schedule(tick, intervalMs);
  timer.unref?.();

  return {
    runNow,
    stop: () => {
      if (stopped) return;
      stopped = true;
      cancel(timer);
    },
  };
}
