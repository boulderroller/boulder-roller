import {
  incompleteRideReason,
  isIncompleteRide,
  rideMeetsScorableMinimums,
} from '../rideCompletion';

describe('rideCompletion', () => {
  test('rejects accidental short recordings before upload or scoring', () => {
    const metrics = {
      distanceM: 0,
      durationMs: 4_000,
      sampleCount: 2,
    };

    expect(rideMeetsScorableMinimums(metrics)).toBe(false);
    expect(isIncompleteRide(metrics)).toBe(true);
    expect(incompleteRideReason(metrics)).toBe('Not enough movement to score.');
  });

  test('accepts a real ride without requiring elevation', () => {
    expect(rideMeetsScorableMinimums({
      distanceM: 12_000,
      durationMs: 1_800_000,
      elevationGainM: 0,
      sampleCount: 300,
    })).toBe(true);
  });

  test('honors persisted incomplete status even if metrics are later present', () => {
    expect(isIncompleteRide({
      status: 'incomplete',
      distanceM: 12_000,
      durationMs: 1_800_000,
      sampleCount: 300,
    })).toBe(true);
  });
});
