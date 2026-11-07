/**
 * Shared mobile ride completion gates.
 *
 * These thresholds protect the rider-facing flow from treating accidental
 * taps, stationary GPS noise, or simulator smoke checks as scored rides.
 */

export const MIN_SCORABLE_DISTANCE_M = 100;
export const MIN_SCORABLE_DURATION_MS = 120_000;
export const MIN_SCORABLE_SAMPLE_COUNT = 5;

export interface RideCompletionMetrics {
  status?: string | null;
  distanceM?: number | null;
  durationMs?: number | null;
  durationSec?: number | null;
  elevationGainM?: number | null;
  points?: number | null;
  sampleCount?: number | null;
}

function finiteNumber(value: number | null | undefined): number | null {
  return typeof value === 'number' && Number.isFinite(value) ? value : null;
}

function durationMsFor(metrics: RideCompletionMetrics): number | null {
  const durationMs = finiteNumber(metrics.durationMs);
  if (durationMs != null) return durationMs;
  const durationSec = finiteNumber(metrics.durationSec);
  return durationSec != null ? durationSec * 1000 : null;
}

export function rideMeetsScorableMinimums(metrics: RideCompletionMetrics): boolean {
  const distanceM = finiteNumber(metrics.distanceM);
  const durationMs = durationMsFor(metrics);
  const sampleCount = finiteNumber(metrics.sampleCount);

  if (distanceM == null || distanceM < MIN_SCORABLE_DISTANCE_M) return false;
  if (durationMs == null || durationMs < MIN_SCORABLE_DURATION_MS) return false;
  if (sampleCount != null && sampleCount < MIN_SCORABLE_SAMPLE_COUNT) return false;
  return true;
}

export function incompleteRideReason(metrics: RideCompletionMetrics): string | null {
  if (metrics.status === 'incomplete') {
    return 'Not enough movement to score.';
  }

  if (rideMeetsScorableMinimums(metrics)) return null;

  const distanceM = finiteNumber(metrics.distanceM) ?? 0;
  const durationMs = durationMsFor(metrics) ?? 0;
  const sampleCount = finiteNumber(metrics.sampleCount);

  if (distanceM < MIN_SCORABLE_DISTANCE_M && durationMs < MIN_SCORABLE_DURATION_MS) {
    return 'Not enough movement to score.';
  }
  if (sampleCount != null && sampleCount < MIN_SCORABLE_SAMPLE_COUNT) {
    return 'Not enough GPS samples to score.';
  }
  if (distanceM < MIN_SCORABLE_DISTANCE_M) {
    return 'Distance is too short to score.';
  }
  return 'Recording is too short to score.';
}

export function isIncompleteRide(metrics: RideCompletionMetrics): boolean {
  return incompleteRideReason(metrics) != null;
}
