/**
 * Ride archive tests.
 *
 * Covers the offline-first contract from MOBILE_TRUTHS §9.1:
 * local rides are always visible; server projections decorate but
 * never replace the local row; only-local and only-server edge cases
 * do not crash the merge.
 */

import { openDatabaseSync } from 'expo-sqlite';

import {
  loadLocalRides,
  mergeRideSources,
  type LocalRideSummary,
} from '../rides';
import type { RideSummary } from '../api';
import { useAuthStore } from '../../stores/authStore';

const TEST_WALLET = 'WalletRideArchive1111111111111111111111111';

beforeEach(() => {
  useAuthStore.getState().setAuthenticated({
    accessToken: 'test-token',
    tokenExpiresAt: Date.now() + 60_000,
    wallet: TEST_WALLET,
    authMethod: 'wallet',
  });
});

afterEach(() => {
  useAuthStore.getState().setUnauthenticated();
});

// ---------------------------------------------------------------------------
// Fixtures
// ---------------------------------------------------------------------------

function makeLocal(overrides: Partial<LocalRideSummary> = {}): LocalRideSummary {
  return {
    id: 'local-1',
    startedAt: Date.parse('2026-04-16T10:00:00Z'),
    status: 'stopped',
    durationMs: 3_600_000,
    movingTimeMs: 3_500_000,
    distanceM: 30_000,
    elevationGainM: 450,
    maxSpeedMps: 14,
    sampleCount: 3_600,
    uploadId: null,
    serverRideId: null,
    uploaded: false,
    uploadStatus: null,
    uploadLastError: null,
    uploadAttemptCount: null,
    rejectedSamples: null,
    hadCrashRecovery: false,
    routePreview: null,
    ...overrides,
  };
}

function makeServer(overrides: Partial<RideSummary> = {}): RideSummary {
  return {
    id: 'srv-1',
    activityId: 'act-1',
    startedAt: '2026-04-16T10:00:00Z',
    durationSec: 3_600,
    distanceM: 31_000,
    elevationGainM: 470,
    tss: 120,
    np: 220,
    avgPowerW: 195,
    source: 'native',
    routePreview: null,
    ...overrides,
  };
}

// ---------------------------------------------------------------------------
// loadLocalRides — SQL shape contract
// ---------------------------------------------------------------------------

describe('loadLocalRides', () => {
  test('queries rides WHERE status IN (stopped, uploaded, incomplete) and joins upload_queue', () => {
    const db = openDatabaseSync('test');
    const getAllSync = db.getAllSync as jest.Mock;
    getAllSync.mockClear();
    getAllSync.mockReturnValueOnce([]);

    loadLocalRides(db);

    expect(getAllSync).toHaveBeenCalledTimes(1);
    const sql = getAllSync.mock.calls[0][0] as string;
    expect(sql).toMatch(/FROM\s+rides\s+r/i);
    expect(sql).toMatch(/LEFT\s+JOIN\s+upload_queue\s+u/i);
    expect(sql).toMatch(/WHERE\s+r\.owner_key\s*=\s*\?/i);
    expect(sql).toMatch(/r\.status\s+IN\s+\(\s*'stopped'\s*,\s*'uploaded'\s*,\s*'incomplete'\s*\)/i);
    expect(sql).toMatch(/ORDER\s+BY\s+r\.started_at\s+DESC/i);
    expect(getAllSync.mock.calls[0][1]).toEqual([`wallet:${TEST_WALLET}`]);
  });

  test('maps upload_status=uploaded onto the uploaded flag', () => {
    const db = openDatabaseSync('test');
    const getAllSync = db.getAllSync as jest.Mock;
    getAllSync
      .mockReturnValueOnce([
        {
          id: 'r-1',
          status: 'stopped',
          started_at: 1_700_000_000_000,
          duration_ms: 1000,
          moving_time_ms: 1000,
          distance_m: 0,
          elevation_gain_m: 0,
          max_speed_mps: 0,
          sample_count: 0,
          rejected_samples: null,
          had_crash_recovery: 0,
          upload_id: 'u-1',
          server_ride_id: 'srv-xyz',
          upload_status: 'uploaded',
          upload_last_error: null,
          upload_attempt_count: 1,
        },
      ])
      .mockReturnValueOnce([]);

    const [ride] = loadLocalRides(db);

    expect(ride.uploaded).toBe(true);
    expect(ride.serverRideId).toBe('srv-xyz');
  });

  test('null upload_queue join still returns a usable row', () => {
    const db = openDatabaseSync('test');
    const getAllSync = db.getAllSync as jest.Mock;
    getAllSync
      .mockReturnValueOnce([
        {
          id: 'r-2',
          status: 'stopped',
          started_at: 1_700_000_000_000,
          duration_ms: 1000,
          moving_time_ms: 1000,
          distance_m: 0,
          elevation_gain_m: 0,
          max_speed_mps: 0,
          sample_count: 0,
          rejected_samples: null,
          had_crash_recovery: 0,
          upload_id: null,
          server_ride_id: null,
          upload_status: null,
          upload_last_error: null,
          upload_attempt_count: null,
        },
      ])
      .mockReturnValueOnce([]);

    const [ride] = loadLocalRides(db);

    expect(ride.uploaded).toBe(false);
    expect(ride.serverRideId).toBeNull();
  });

  test('builds normalized local route previews from gps_samples', () => {
    const db = openDatabaseSync('test');
    const getAllSync = db.getAllSync as jest.Mock;
    getAllSync
      .mockReturnValueOnce([
        {
          id: 'r-3',
          status: 'stopped',
          started_at: 1_700_000_000_000,
          duration_ms: 1000,
          moving_time_ms: 1000,
          distance_m: 500,
          elevation_gain_m: 20,
          max_speed_mps: 5,
          sample_count: 3,
          rejected_samples: null,
          had_crash_recovery: 0,
          upload_id: null,
          server_ride_id: null,
          upload_status: null,
          upload_last_error: null,
          upload_attempt_count: null,
        },
      ])
      .mockReturnValueOnce([
        { ride_id: 'r-3', latitude: 39.95, longitude: -75.17 },
        { ride_id: 'r-3', latitude: 39.96, longitude: -75.16 },
        { ride_id: 'r-3', latitude: 39.97, longitude: -75.15 },
      ]);

    const [ride] = loadLocalRides(db);

    expect(ride.routePreview?.contractVersion).toBe('route_preview.v1');
    expect(ride.routePreview?.source).toBe('local_gps');
    expect(ride.routePreview?.pointCount).toBe(3);
    expect(ride.routePreview?.points[0]).toEqual({ x: 0, y: 1 });
    expect(ride.routePreview?.points[2]).toEqual({ x: 1, y: 0 });
  });
});

// ---------------------------------------------------------------------------
// mergeRideSources — offline-first behavior
// ---------------------------------------------------------------------------

describe('mergeRideSources', () => {
  test('null server input returns local rides unchanged', () => {
    const locals = [makeLocal()];
    const merged = mergeRideSources(locals, null);

    expect(merged).toHaveLength(1);
    expect(merged[0].source).toBe('local');
    expect(merged[0].localRideId).toBe('local-1');
    expect(merged[0].tss).toBeNull();
    expect(merged[0].routePreview).toBeNull();
  });

  test('empty local + empty server produces empty list without throwing', () => {
    expect(mergeRideSources([], [])).toEqual([]);
    expect(mergeRideSources([], null)).toEqual([]);
  });

  test('local ride without serverRideId is kept as local source', () => {
    const locals = [makeLocal({ serverRideId: null })];
    const servers = [makeServer({ id: 'srv-999' })];

    const merged = mergeRideSources(locals, servers);

    // Both rows survive: a local orphan and an unmatched server ride.
    expect(merged).toHaveLength(2);
    expect(merged.find((m) => m.source === 'local')?.localRideId).toBe('local-1');
    expect(merged.find((m) => m.source === 'server')?.serverRideId).toBe('srv-999');
  });

  test('local ride with matching serverRideId dedupes to merged row', () => {
    const locals = [makeLocal({ serverRideId: 'srv-1', uploaded: true })];
    const servers = [makeServer({ id: 'srv-1', tss: 180 })];

    const merged = mergeRideSources(locals, servers);

    expect(merged).toHaveLength(1);
    expect(merged[0].source).toBe('merged');
    expect(merged[0].localRideId).toBe('local-1');
    expect(merged[0].serverRideId).toBe('srv-1');
    // Server-derived fields win on merge.
    expect(merged[0].tss).toBe(180);
    expect(merged[0].distanceM).toBe(31_000);
  });

  test('server route previews decorate merged rows without losing local fallback', () => {
    const localPreview = {
      contractVersion: 'route_preview.v1' as const,
      source: 'local_gps',
      points: [{ x: 0, y: 1 }, { x: 1, y: 0 }],
      pointCount: 2,
    };
    const serverPreview = {
      contractVersion: 'route_preview.v1' as const,
      source: 'server_gps',
      points: [{ x: 0.2, y: 0.8 }, { x: 0.8, y: 0.2 }],
      pointCount: 20,
      placeLabel: 'Philadelphia, PA',
    };

    const merged = mergeRideSources(
      [makeLocal({ serverRideId: 'srv-1', routePreview: localPreview })],
      [makeServer({ id: 'srv-1', routePreview: serverPreview })],
    );

    expect(merged[0].routePreview).toBe(serverPreview);
  });

  test('server-only rides (no local counterpart) are still shown', () => {
    const merged = mergeRideSources(
      [],
      [makeServer({ id: 'srv-only' })],
    );

    expect(merged).toHaveLength(1);
    expect(merged[0].source).toBe('server');
    expect(merged[0].localRideId).toBeNull();
    expect(merged[0].serverRideId).toBe('srv-only');
  });

  test('results are ordered newest-first by startedAt', () => {
    const older = makeLocal({
      id: 'local-older',
      startedAt: Date.parse('2026-04-10T10:00:00Z'),
    });
    const newer = makeLocal({
      id: 'local-newer',
      startedAt: Date.parse('2026-04-16T10:00:00Z'),
    });
    const serverMid = makeServer({
      id: 'srv-mid',
      startedAt: '2026-04-13T10:00:00Z',
    });

    const merged = mergeRideSources([older, newer], [serverMid]);

    expect(merged.map((m) => m.key)).toEqual([
      'local-newer',
      'srv:srv-mid',
      'local-older',
    ]);
  });

  test('unparseable server timestamp falls back to local wall-clock on merge', () => {
    const local = makeLocal({ serverRideId: 'srv-1' });
    const server = makeServer({ id: 'srv-1', startedAt: 'not-a-date' });

    const merged = mergeRideSources([local], [server]);

    expect(merged[0].startedAtMs).toBe(local.startedAt);
  });
});
