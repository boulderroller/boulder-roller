/**
 * Database module — contract tests for SQL shape that callers depend on.
 *
 * These verify SQL strings that have to stay a particular shape for
 * correctness reasons that wouldn't be caught by a runtime mock that
 * accepts any SQL.
 */

import { openDatabaseSync } from 'expo-sqlite';

import {
  createUploadEntry,
  flushSampleBatch,
  getRideValidationEvents,
  initDatabase,
  getDatabase,
  insertPauseEvent,
  insertRideValidationEvent,
  _resetDatabaseForTests,
} from '../database';
import { useAuthStore } from '../../stores/authStore';

const TEST_WALLET = 'WalletDatabase111111111111111111111111111';
const TEST_OWNER_KEY = `wallet:${TEST_WALLET}`;

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

describe('createUploadEntry', () => {
  test('uses INSERT OR IGNORE so re-enqueue of the same ride is a no-op', () => {
    const db = openDatabaseSync('test');
    const runSync = db.runSync as jest.Mock;
    runSync.mockClear();

    createUploadEntry(db, 'ride-1');

    expect(runSync).toHaveBeenCalledTimes(1);
    const sql = runSync.mock.calls[0][0] as string;
    expect(sql).toMatch(/INSERT\s+OR\s+IGNORE\s+INTO\s+upload_queue/i);
  });

  test('passes rideId for both id and ride_id columns (PK == ride_id by design)', () => {
    const db = openDatabaseSync('test');
    const runSync = db.runSync as jest.Mock;
    runSync.mockClear();

    createUploadEntry(db, 'ride-7');

    expect(runSync.mock.calls[0][1]).toEqual([
      'ride-7',
      'ride-7',
      'ride-7',
      TEST_OWNER_KEY,
    ]);
  });
});

describe('ride validation events', () => {
  test('insertRideValidationEvent persists event evidence with JSON metadata', () => {
    const db = openDatabaseSync('test');
    const runSync = db.runSync as jest.Mock;
    runSync.mockClear();

    insertRideValidationEvent(db, 'ride-1', 'upload_accepted', {
      stopToUploadedMs: 750,
      hashPresent: true,
    }, 12_345);

    expect(runSync).toHaveBeenCalledTimes(1);
    const [sql, params] = runSync.mock.calls[0];
    expect(sql).toMatch(/INSERT\s+INTO\s+ride_validation_events/i);
    expect(params).toEqual([
      'ride-1',
      'upload_accepted',
      12_345,
      JSON.stringify({ stopToUploadedMs: 750, hashPresent: true }),
      'ride-1',
      TEST_OWNER_KEY,
    ]);
  });

  test('getRideValidationEvents returns events in ride timeline order', () => {
    const db = openDatabaseSync('test');
    const getAllSync = db.getAllSync as jest.Mock;
    getAllSync.mockClear();

    getRideValidationEvents(db, 'ride-1');

    const [sql, params] = getAllSync.mock.calls[0];
    expect(sql).toMatch(/FROM\s+ride_validation_events/i);
    expect(sql).toMatch(/ORDER\s+BY\s+v\.occurred_at\s+ASC,\s+v\.id\s+ASC/i);
    expect(params).toEqual(['ride-1', TEST_OWNER_KEY]);
  });
});

describe('owner-guarded local writes', () => {
  test('GPS batches, aggregates, pause events, and validation events bind writes to owner', () => {
    const db = openDatabaseSync('test');
    const runSync = db.runSync as jest.Mock;
    runSync.mockClear();

    flushSampleBatch(
      db,
      'ride-1',
      [
        {
          ride_id: 'ride-1',
          t_offset_ms: 1_000,
          latitude: 39.95,
          longitude: -75.17,
          altitude_m: 20,
          accuracy_m: 5,
          vert_accuracy_m: 3,
          speed_mps: 4,
          bearing_deg: 90,
          source: 'fused',
        },
      ],
      {
        durationMs: 1_000,
        distanceM: 10,
        elevationGainM: 1,
        maxSpeedMps: 4,
        movingTimeMs: 1_000,
      },
    );
    insertPauseEvent(db, {
      ride_id: 'ride-1',
      event_type: 'pause',
      t_offset_ms: 1_000,
      reason: 'manual',
    });
    insertRideValidationEvent(db, 'ride-1', 'owner-check');

    const guardedCalls = runSync.mock.calls.filter((call) =>
      /gps_samples|UPDATE rides|pause_events|ride_validation_events/i.test(call[0]),
    );
    expect(guardedCalls).toHaveLength(4);
    for (const [sql, params] of guardedCalls) {
      expect(sql).toMatch(/owner_key/i);
      expect(params).toContain(TEST_OWNER_KEY);
    }
  });
});

describe('initDatabase / getDatabase (encrypted singleton)', () => {
  test('schema v5 quarantines legacy rides and scopes active rows by owner', async () => {
    _resetDatabaseForTests();
    const db = openDatabaseSync('test');
    const getFirstSync = db.getFirstSync as jest.Mock;
    const execSync = db.execSync as jest.Mock;
    getFirstSync.mockReset().mockReturnValueOnce({ user_version: 4 });
    execSync.mockClear();

    await initDatabase();

    const migrationSql = execSync.mock.calls.map((call) => call[0] as string);
    expect(migrationSql.some((sql) => /ALTER TABLE rides ADD COLUMN owner_key/i.test(sql))).toBe(true);
    expect(migrationSql.some((sql) => /ON rides\(owner_key\)/i.test(sql))).toBe(true);
    expect(migrationSql.some((sql) => /UPDATE rides SET owner_key/i.test(sql))).toBe(false);
    getFirstSync.mockReset().mockReturnValue(null);
  });

  test('initDatabase runs PRAGMA key with the secure-store-fetched passphrase', async () => {
    _resetDatabaseForTests();
    const db = openDatabaseSync('test');
    const execSync = db.execSync as jest.Mock;
    execSync.mockClear();

    await initDatabase();

    const allCalls = execSync.mock.calls.map((c) => c[0] as string);
    expect(allCalls.some((sql) => /^PRAGMA\s+key\s*=/i.test(sql))).toBe(true);
    // Standard pragmas still run after key
    expect(allCalls.some((sql) => /journal_mode\s*=\s*WAL/i.test(sql))).toBe(true);
  });

  test('initDatabase is idempotent — second call returns the same singleton', async () => {
    _resetDatabaseForTests();
    const first = await initDatabase();
    const second = await initDatabase();
    expect(first).toBe(second);
  });

  test('getDatabase throws when called before init', () => {
    _resetDatabaseForTests();
    expect(() => getDatabase()).toThrow(/not initialized/i);
  });

  test('getDatabase returns the singleton after init', async () => {
    _resetDatabaseForTests();
    const initd = await initDatabase();
    expect(getDatabase()).toBe(initd);
  });
});
