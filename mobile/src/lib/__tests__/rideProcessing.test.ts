import {
  deriveProcessingStages,
  allStagesComplete,
  type ProcessingStage,
} from '../rideProcessing';
import type { RideStatus } from '../api';

function statusWith(overrides: Partial<RideStatus>): RideStatus {
  return {
    rideId: 'r1',
    status: 'processing',
    errorMessage: null,
    ...overrides,
  };
}

describe('deriveProcessingStages', () => {
  test('null status returns all four stages, all pending', () => {
    const stages = deriveProcessingStages(null);
    expect(stages.map((s) => s.key)).toEqual([
      'processed',
      'climbs',
      'leaderboards',
      'achievements',
    ]);
    expect(stages.every((s) => !s.complete)).toBe(true);
  });

  test('metrics present flips processed stage', () => {
    const stages = deriveProcessingStages(
      statusWith({
        metrics: {
          tss: 100,
          kcals: 1000,
          distanceM: 20_000,
          elevationGainM: 100,
          durationSec: 3_600,
          avgPowerW: null,
          normalizedPowerW: null,
        },
      }),
    );
    expect(stages.find((s) => s.key === 'processed')?.complete).toBe(true);
    expect(stages.find((s) => s.key === 'climbs')?.complete).toBe(false);
  });

  test('each hasX flag flips its own stage independently', () => {
    const stages = deriveProcessingStages(
      statusWith({ hasPatterns: true, hasLeaderboards: true }),
    );
    const byKey = Object.fromEntries(stages.map((s) => [s.key, s.complete]));
    expect(byKey.processed).toBe(false);
    expect(byKey.climbs).toBe(true);
    expect(byKey.leaderboards).toBe(true);
    expect(byKey.achievements).toBe(false);
  });

  test('all flags true → all stages complete', () => {
    const stages = deriveProcessingStages(
      statusWith({
        metrics: {
          tss: 100,
          kcals: 1000,
          distanceM: 20_000,
          elevationGainM: 100,
          durationSec: 3_600,
          avgPowerW: null,
          normalizedPowerW: null,
        },
        hasPatterns: true,
        hasLeaderboards: true,
        hasAchievements: true,
      }),
    );
    expect(stages.every((s) => s.complete)).toBe(true);
    expect(allStagesComplete(stages)).toBe(true);
  });

  test('labels are human-readable and consistent', () => {
    const stages = deriveProcessingStages(null);
    const labels = stages.map((s) => s.label);
    expect(labels).toEqual([
      'Ride',
      'Climbs',
      'Standings',
      'Milestones',
    ]);
  });
});

describe('allStagesComplete', () => {
  test('true only when every stage is complete', () => {
    const build = (all: boolean): ProcessingStage[] =>
      (['processed', 'climbs', 'leaderboards', 'achievements'] as const).map(
        (key) => ({ key, label: key, complete: all }),
      );
    expect(allStagesComplete(build(true))).toBe(true);
    expect(allStagesComplete(build(false))).toBe(false);
  });

  test('false when even one stage is pending', () => {
    const stages: ProcessingStage[] = [
      { key: 'processed', label: 'p', complete: true },
      { key: 'climbs', label: 'c', complete: true },
      { key: 'leaderboards', label: 'l', complete: false },
      { key: 'achievements', label: 'a', complete: true },
    ];
    expect(allStagesComplete(stages)).toBe(false);
  });
});
