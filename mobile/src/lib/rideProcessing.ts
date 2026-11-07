/**
 * Ride processing stages — UI-layer scaffolding.
 *
 * Derives a structured "which steps have finished" view from whatever
 * signals the RideStatus response currently carries. Everything returned
 * here is already in the existing RideStatus shape; no backend contract
 * is invented.
 *
 * The keys mirror server signals, but labels stay rider-facing. The detail
 * screen should say what is ready, not expose backend job names.
 */

import type { RideStatus } from './api';

export type ProcessingStageKey =
  | 'processed'
  | 'climbs'
  | 'leaderboards'
  | 'achievements';

export interface ProcessingStage {
  key: ProcessingStageKey;
  label: string;
  complete: boolean;
}

export function deriveProcessingStages(
  status: RideStatus | null,
): ProcessingStage[] {
  return [
    {
      key: 'processed',
      label: 'Ride',
      complete: !!status?.metrics,
    },
    {
      key: 'climbs',
      label: 'Climbs',
      complete: !!status?.hasPatterns,
    },
    {
      key: 'leaderboards',
      label: 'Standings',
      complete: !!status?.hasLeaderboards,
    },
    {
      key: 'achievements',
      label: 'Milestones',
      complete: !!status?.hasAchievements,
    },
  ];
}

/** True when every stage is complete — useful for "all done" affordances. */
export function allStagesComplete(stages: ProcessingStage[]): boolean {
  return stages.every((s) => s.complete);
}
