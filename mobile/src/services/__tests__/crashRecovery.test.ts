/**
 * Crash Recovery service tests.
 *
 * detectInterruptedRide must stamp had_crash_recovery=1 — without that the
 * breadcrumb column stays 0 in production.
 *
 * saveInterruptedRide must compute and stamp preliminary_ride_hash +
 * parser_version BEFORE enqueueing — without that, recovered rides upload
 * with null preliminary provenance and the backend compare path has
 * nothing to check.
 */

import { getActiveRide, updateRide, deleteRide, type RideRow } from '../database';
import { enqueueRide } from '../uploadQueue';
import { computePreliminaryHash } from '../../lib/preliminaryHash';
import {
  detectInterruptedRide,
  saveInterruptedRide,
  discardInterruptedRide,
} from '../crashRecovery';

jest.mock('../database', () => ({
  getDatabase: jest.fn().mockReturnValue({}),
  getActiveRide: jest.fn(),
  createRide: jest.fn(),
  updateRide: jest.fn(),
  deleteRide: jest.fn(),
}));

jest.mock('../uploadQueue', () => ({
  enqueueRide: jest.fn(),
}));

jest.mock('../../lib/preliminaryHash', () => ({
  computePreliminaryHash: jest.fn(),
  CURRENT_PARSER_VERSION: 5,
}));

const mockGetActiveRide = getActiveRide as jest.MockedFunction<typeof getActiveRide>;
const mockUpdateRide = updateRide as jest.MockedFunction<typeof updateRide>;
const mockDeleteRide = deleteRide as jest.MockedFunction<typeof deleteRide>;
const mockEnqueueRide = enqueueRide as jest.MockedFunction<typeof enqueueRide>;
const mockComputePreliminaryHash = computePreliminaryHash as jest.MockedFunction<
  typeof computePreliminaryHash
>;

function rideRow(overrides: Partial<RideRow> = {}): RideRow {
  return {
    id: 'ride-crashed',
    status: 'recording',
    started_at: 1_000,
    ended_at: null,
    duration_ms: 2_700_000,
    moving_time_ms: 2_500_000,
    distance_m: 25_000,
    elevation_gain_m: 350,
    max_speed_mps: 15,
    sport_type: 'ride',
    clock_drift_ms: null,
    sample_count: 2_700,
    rejected_samples: null,
    upload_id: null,
    notes: null,
    preliminary_ride_hash: null,
    parser_version: null,
    had_crash_recovery: 0,
    ...overrides,
  };
}

describe('detectInterruptedRide', () => {
  beforeEach(() => {
    jest.clearAllMocks();
  });

  test('returns null when no active ride is pending recovery', () => {
    mockGetActiveRide.mockReturnValue(null);
    expect(detectInterruptedRide()).toBeNull();
    expect(mockUpdateRide).not.toHaveBeenCalled();
  });

  test('stamps had_crash_recovery=1 on the row before returning', () => {
    mockGetActiveRide.mockReturnValue(rideRow({ had_crash_recovery: 0 }));

    const result = detectInterruptedRide();

    expect(mockUpdateRide).toHaveBeenCalledWith(
      expect.any(Object),
      'ride-crashed',
      expect.objectContaining({ had_crash_recovery: 1 }),
    );
    // Returned row reflects the mutation so callers don't re-fetch
    expect(result?.had_crash_recovery).toBe(1);
    expect(result?.id).toBe('ride-crashed');
  });
});

describe('saveInterruptedRide', () => {
  beforeEach(() => {
    jest.clearAllMocks();
  });

  test('computes preliminary hash, stamps fields atomically with stop, then enqueues', async () => {
    const fakeHashBytes = new Uint8Array(32).fill(0xab);
    mockComputePreliminaryHash.mockResolvedValue({
      rideHash: fakeHashBytes,
      parserVersion: 2,
    });

    await saveInterruptedRide('ride-crashed');

    // Hash computed before updateRide
    expect(mockComputePreliminaryHash).toHaveBeenCalledWith('ride-crashed');
    // All four fields get stamped in a single updateRide call
    expect(mockUpdateRide).toHaveBeenCalledWith(
      expect.any(Object),
      'ride-crashed',
      expect.objectContaining({
        status: 'stopped',
        ended_at: expect.any(Number),
        preliminary_ride_hash: fakeHashBytes,
        parser_version: 2,
      }),
    );
    // Enqueue fires after the update
    expect(mockEnqueueRide).toHaveBeenCalledWith('ride-crashed');
    // Order check: hash → update → enqueue
    const hashOrder = mockComputePreliminaryHash.mock.invocationCallOrder[0];
    const updateOrder = mockUpdateRide.mock.invocationCallOrder[0];
    const enqueueOrder = mockEnqueueRide.mock.invocationCallOrder[0];
    expect(hashOrder).toBeLessThan(updateOrder);
    expect(updateOrder).toBeLessThan(enqueueOrder);
  });

  test('tolerates null hash (e.g., ride row missing) without crashing', async () => {
    mockComputePreliminaryHash.mockResolvedValue({
      rideHash: null,
      parserVersion: 2,
    });

    await expect(saveInterruptedRide('ghost-ride')).resolves.toBeUndefined();
    expect(mockUpdateRide).toHaveBeenCalledWith(
      expect.any(Object),
      'ghost-ride',
      expect.objectContaining({ preliminary_ride_hash: null, parser_version: 2 }),
    );
    // Still enqueues — backend treats a null preliminary stamp as legacy input.
    expect(mockEnqueueRide).toHaveBeenCalled();
  });
});

describe('discardInterruptedRide', () => {
  beforeEach(() => {
    jest.clearAllMocks();
  });

  test('deletes the ride row (samples cascade)', () => {
    discardInterruptedRide('ride-dead');
    expect(mockDeleteRide).toHaveBeenCalledWith(expect.any(Object), 'ride-dead');
  });
});
