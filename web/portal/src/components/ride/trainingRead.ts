import type { RideTrainingMetrics } from '../../lib/api';

/** Projection only: all time, boundaries, shares and curve watts come from the engine. */
export function trainingRead(metrics?: Partial<RideTrainingMetrics> | null) {
  return {
    moving: metrics?.movingS ?? null,
    curve: metrics?.powerCurveW ?? [],
    durations: metrics?.powerCurveS ?? [],
    zones: metrics?.powerZoneS && metrics?.powerZoneRangesW ? {
      times: metrics.powerZoneS.slice(0, 7),
      total: metrics.powerZoneTotalS ?? 0,
      ranges: metrics.powerZoneRangesW,
      shares: metrics.powerZonePct,
    } : null,
  };
}
