import type { SQLiteDatabase } from 'expo-sqlite';
import * as Location from 'expo-location';
import * as TaskManager from 'expo-task-manager';

import { loadLocalRides } from '../../lib/rides';
import { useRecordingStore } from '../../stores/recordingStore';
import { useAuthStore } from '../../stores/authStore';
import {
  createRide,
  getDatabase,
  getNextUploadEntry,
  getRide,
  getRideSamples,
  getUploadEntryForRide,
} from '../database';
import {
  BACKGROUND_TASK_NAME,
  startRecording,
  suspendRecordingForAccountBoundary,
} from '../gpsRecording';

const WALLET_A = 'WalletAAAA111111111111111111111111111111';
const WALLET_B = 'WalletBBBB222222222222222222222222222222';

function signIn(wallet: string): void {
  useAuthStore.getState().setAuthenticated({
    accessToken: `token-${wallet}`,
    tokenExpiresAt: Date.now() + 60_000,
    wallet,
    authMethod: 'wallet',
  });
}

function localRideRow(id: string, ownerKey: string | null, startedAt: number) {
  return {
    id,
    owner_key: ownerKey,
    status: 'stopped',
    started_at: startedAt,
    ended_at: startedAt + 60_000,
    duration_ms: 60_000,
    moving_time_ms: 58_000,
    distance_m: 1_000,
    elevation_gain_m: 20,
    max_speed_mps: 8,
    sport_type: 'ride',
    clock_drift_ms: null,
    sample_count: 2,
    rejected_samples: null,
    upload_id: null,
    notes: null,
    preliminary_ride_hash: null,
    parser_version: null,
    had_crash_recovery: 0,
    server_ride_id: null,
    upload_status: null,
    upload_last_error: null,
    upload_attempt_count: null,
  };
}

function ownerKeyFromParams(params: unknown[] | undefined): string | null {
  return (
    params?.find(
      (value): value is string =>
        typeof value === 'string' && value.startsWith('wallet:'),
    ) ?? null
  );
}

function accountBoundaryDatabase(): SQLiteDatabase {
  const rides = [
    localRideRow('ride-a', `wallet:${WALLET_A}`, 300),
    localRideRow('ride-b', `wallet:${WALLET_B}`, 200),
    localRideRow('ride-legacy', null, 100),
  ];
  const samples = [
    { ride_id: 'ride-a', t_offset_ms: 0, latitude: 39.95, longitude: -75.17 },
    { ride_id: 'ride-a', t_offset_ms: 1_000, latitude: 39.96, longitude: -75.16 },
    { ride_id: 'ride-b', t_offset_ms: 0, latitude: 40.0, longitude: -75.2 },
    { ride_id: 'ride-legacy', t_offset_ms: 0, latitude: 41.0, longitude: -76.0 },
  ];
  const uploads = rides.map((ride) => ({
    id: `upload-${ride.id}`,
    ride_id: ride.id,
    status: 'pending',
    file_hash: null,
    attempt_count: 0,
    max_attempts: 10,
    next_retry_at: null,
    last_error: null,
    server_ride_id: null,
    created_at: ride.started_at,
    updated_at: ride.started_at,
  }));

  const getFirstSync = jest.fn((sql: string, params?: unknown[]) => {
    if (/FROM\s+upload_queue/i.test(sql)) {
      const ownerKey = ownerKeyFromParams(params);
      const requestedRideId = params?.find(
        (value): value is string =>
          typeof value === 'string' && value.startsWith('ride-'),
      );
      const visibleRideIds = new Set(
        /owner_key/i.test(sql)
          ? rides
              .filter((ride) => ride.owner_key === ownerKey)
              .map((ride) => ride.id)
          : rides.map((ride) => ride.id),
      );
      return (
        uploads.find(
          (entry) =>
            (!requestedRideId || entry.ride_id === requestedRideId) &&
            visibleRideIds.has(entry.ride_id),
        ) ?? null
      );
    }
    if (!/FROM\s+rides/i.test(sql)) return null;
    const rideId = params?.find(
      (value): value is string =>
        typeof value === 'string' && value.startsWith('ride-'),
    );
    const row = rides.find((candidate) => candidate.id === rideId) ?? null;
    if (!/owner_key/i.test(sql)) return row;
    return row?.owner_key === ownerKeyFromParams(params) ? row : null;
  });

  const getAllSync = jest.fn((sql: string, params?: unknown[]) => {
    const ownerKey = ownerKeyFromParams(params);
    if (/FROM\s+rides\s+r/i.test(sql)) {
      return /owner_key/i.test(sql)
        ? rides.filter((ride) => ride.owner_key === ownerKey)
        : rides;
    }
    if (/FROM\s+gps_samples/i.test(sql)) {
      const requestedRideIds = new Set(
        (params ?? []).filter(
          (value): value is string =>
            typeof value === 'string' && value.startsWith('ride-'),
        ),
      );
      const visibleRideIds = new Set(
        /owner_key/i.test(sql)
          ? rides
              .filter((ride) => ride.owner_key === ownerKey)
              .map((ride) => ride.id)
          : rides.map((ride) => ride.id),
      );
      return samples.filter(
        (sample) =>
          (!requestedRideIds.size || requestedRideIds.has(sample.ride_id)) &&
          visibleRideIds.has(sample.ride_id),
      );
    }
    return [];
  });

  return {
    getFirstSync,
    getAllSync,
    runSync: jest.fn().mockReturnValue({ changes: 1 }),
  } as unknown as SQLiteDatabase;
}

describe('local ride account boundary', () => {
  afterEach(() => {
    useAuthStore.getState().setUnauthenticated();
  });

  test('account switch hides A rides from B and restores them for A', () => {
    const db = accountBoundaryDatabase();

    signIn(WALLET_A);
    expect(loadLocalRides(db).map((ride) => ride.id)).toEqual(['ride-a']);

    signIn(WALLET_B);
    expect(loadLocalRides(db).map((ride) => ride.id)).toEqual(['ride-b']);

    signIn(WALLET_A);
    expect(loadLocalRides(db).map((ride) => ride.id)).toEqual(['ride-a']);
  });

  test('detail and exact GPS reads require the matching owner', () => {
    const db = accountBoundaryDatabase();

    signIn(WALLET_B);
    expect(getRide(db, 'ride-a')).toBeNull();
    expect(getRideSamples(db, 'ride-a')).toEqual([]);

    signIn(WALLET_A);
    expect(getRide(db, 'ride-a')?.id).toBe('ride-a');
    expect(getRideSamples(db, 'ride-a')).toHaveLength(2);
  });

  test('legacy rows without an owner remain quarantined for every account', () => {
    const db = accountBoundaryDatabase();

    signIn(WALLET_A);
    expect(getRide(db, 'ride-legacy')).toBeNull();
    expect(getRideSamples(db, 'ride-legacy')).toEqual([]);

    signIn(WALLET_B);
    expect(getRide(db, 'ride-legacy')).toBeNull();
    expect(getRideSamples(db, 'ride-legacy')).toEqual([]);
  });

  test('upload selection cannot cross accounts or pick a legacy ride', () => {
    const db = accountBoundaryDatabase();

    signIn(WALLET_A);
    expect(getNextUploadEntry(db)?.ride_id).toBe('ride-a');
    expect(getUploadEntryForRide(db, 'ride-b')).toBeNull();
    expect(getUploadEntryForRide(db, 'ride-legacy')).toBeNull();

    signIn(WALLET_B);
    expect(getNextUploadEntry(db)?.ride_id).toBe('ride-b');
    expect(getUploadEntryForRide(db, 'ride-a')).toBeNull();
  });

  test('new rides bind to the authenticated wallet owner key', () => {
    const db = accountBoundaryDatabase();
    const runSync = db.runSync as jest.Mock;
    signIn(WALLET_A);

    createRide(db, 'ride-new', 1_700_000_000_000);

    const [sql, params] = runSync.mock.calls[0] as [string, unknown[]];
    expect(sql).toMatch(/owner_key/i);
    expect(params).toEqual([
      'ride-new',
      `wallet:${WALLET_A}`,
      1_700_000_000_000,
    ]);
  });

  test('mid-recording logout stops A route state before B coordinates arrive', async () => {
    const db = getDatabase();
    const runSync = db.runSync as jest.Mock;
    runSync.mockClear();
    const defineTask = TaskManager.defineTask as jest.Mock;
    const taskCall = defineTask.mock.calls.find(
      (call) => call[0] === BACKGROUND_TASK_NAME,
    );
    expect(taskCall).toBeDefined();
    const locationCallback = taskCall[1] as (payload: {
      data: { locations: unknown[] };
      error: null;
    }) => Promise<void>;

    signIn(WALLET_A);
    useRecordingStore.getState().startRide('ride-a');
    await startRecording('ride-a');
    await locationCallback({
      data: {
        locations: [
          {
            timestamp: Date.now(),
            coords: {
              latitude: 39.95,
              longitude: -75.17,
              altitude: 20,
              accuracy: 5,
              altitudeAccuracy: 3,
              speed: 4,
              heading: 90,
            },
          },
        ],
      },
      error: null,
    });

    (Location.hasStartedLocationUpdatesAsync as jest.Mock).mockResolvedValueOnce(true);
    await suspendRecordingForAccountBoundary();
    useAuthStore.getState().setUnauthenticated();
    signIn(WALLET_B);

    const insertsAfterLogout = runSync.mock.calls.filter(
      (call) =>
        typeof call[0] === 'string' && call[0].includes('INSERT INTO gps_samples'),
    );
    expect(insertsAfterLogout).toHaveLength(1);
    expect(insertsAfterLogout[0][1]).toContain(`wallet:${WALLET_A}`);
    expect(useRecordingStore.getState()).toMatchObject({
      status: 'idle',
      rideId: null,
      routePoints: [],
    });
    expect(Location.stopLocationUpdatesAsync).toHaveBeenCalledWith(
      BACKGROUND_TASK_NAME,
    );

    // A native callback already in flight after logout must see the idle
    // store and never persist B's position under A's retained ride id.
    await locationCallback({
      data: {
        locations: [
          {
            timestamp: Date.now() + 1_000,
            coords: {
              latitude: 40.75,
              longitude: -73.98,
              altitude: 10,
              accuracy: 5,
              altitudeAccuracy: 3,
              speed: 5,
              heading: 180,
            },
          },
        ],
      },
      error: null,
    });

    const insertsAfterAccountB = runSync.mock.calls.filter(
      (call) =>
        typeof call[0] === 'string' && call[0].includes('INSERT INTO gps_samples'),
    );
    expect(insertsAfterAccountB).toHaveLength(1);
    expect(insertsAfterAccountB[0][1]).not.toContain(`wallet:${WALLET_B}`);
  });
});
