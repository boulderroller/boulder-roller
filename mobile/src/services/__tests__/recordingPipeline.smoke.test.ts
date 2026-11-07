/**
 * Recording pipeline smoke test.
 *
 * Drives the full recording flow end-to-end using MockBleSource:
 *   mock sensors → SensorRegistry → processLocationUpdate (via captured
 *   TaskManager callback) → flushSampleBatch → mocked SQLite INSERT
 *
 * Validates that sensor data is correctly snapshotted on each GPS tick
 * and persisted into the wide sample row. This is the foundation for
 * the BLE work — if the merge here is broken, no amount of parser
 * correctness saves the ride.
 */

import * as TaskManager from 'expo-task-manager';
import * as Sentry from '@sentry/react-native';
import * as Location from 'expo-location';

// Importing gpsRecording triggers TaskManager.defineTask at module load,
// which is how we capture the location callback for manual invocation.
import * as GPS from '../gpsRecording';
import { sensorRegistry } from '../sensors/registry';
import { MockBleSource } from '../sensors/mock/mockBleSource';
import type { PowerSample, HeartRateSample, CadenceSample } from '../sensors/types';
import { useRecordingStore } from '../../stores/recordingStore';
import { useAuthStore } from '../../stores/authStore';
import { getDatabase } from '../database';

type LocationBatch = {
  data: { locations: unknown[] } | null;
  error: { message: string } | null;
};
type LocationCallback = (payload: LocationBatch) => Promise<void>;

describe('Recording pipeline smoke test', () => {
  let locationCallback: LocationCallback;
  let mockDb: ReturnType<typeof getDatabase>;

  beforeAll(() => {
    // gpsRecording.ts calls TaskManager.defineTask(TASK_NAME, callback) at
    // module scope. Grab that callback from the jest.fn() mock.
    const defineTaskMock = TaskManager.defineTask as jest.Mock;
    const calls = defineTaskMock.mock.calls;
    expect(calls.length).toBeGreaterThan(0);
    locationCallback = calls[0][1] as LocationCallback;
    mockDb = getDatabase();
  });

  beforeEach(async () => {
    sensorRegistry._clear();
    useRecordingStore.getState().reset();
    useAuthStore.getState().setAuthenticated({
      accessToken: 'recording-test-token',
      tokenExpiresAt: Date.now() + 60_000,
      wallet: 'WalletRecording11111111111111111111111111',
      authMethod: 'wallet',
    });
    jest.clearAllMocks();

    // The mock SQLite db's withTransactionSync invokes its fn arg, which
    // needs runSync to exist. clearAllMocks keeps the mockReturnValue
    // baked in at jest.setup.ts time.
    (mockDb.runSync as jest.Mock).mockReturnValue({ changes: 0 });

    useRecordingStore.getState().startRide('ride-smoke');
    await GPS.startRecording('ride-smoke');
  });

  afterEach(async () => {
    // Stop sensor source timers.
    for (const source of sensorRegistry.all()) {
      await source.stop();
    }
    // startRecording() started a real setInterval for the elapsed timer.
    // discardRecording() stops it cleanly; without this Jest hangs forever.
    await GPS.discardRecording();
    useAuthStore.getState().setUnauthenticated();
  });

  /** Build 10 valid GPS samples, strictly increasing time, constant speed. */
  function makeLocations(startTime = 1_700_000_000_000): unknown[] {
    const fixtureStart = 1_700_000_000_000;
    const sequenceOffset =
      Math.abs(startTime - fixtureStart) < 60 * 60 * 1000
        ? Math.max(0, Math.round((startTime - fixtureStart) / 1000))
        : 0;
    return Array.from({ length: 10 }, (_, i) => ({
      timestamp: startTime + i * 1000,
      coords: {
        latitude: 39.95 + (sequenceOffset + i) * 0.0001,
        longitude: -75.16 + (sequenceOffset + i) * 0.0001,
        altitude: 10 + i * 0.5,
        accuracy: 5,
        altitudeAccuracy: 3,
        heading: 45,
        speed: 5, // above auto-pause threshold, well under max
      },
    }));
  }

  function makeStationaryLocations(startTime = 1_700_000_000_000): unknown[] {
    return Array.from({ length: 10 }, (_, i) => ({
      timestamp: startTime + i * 1000,
      coords: {
        latitude: 39.95,
        longitude: -75.16,
        altitude: 10,
        accuracy: 5,
        altitudeAccuracy: 3,
        heading: 45,
        speed: 0,
      },
    }));
  }

  function makeMovingLocation(timestamp: number): unknown {
    return {
      timestamp,
      coords: {
        latitude: 39.95,
        longitude: -75.16,
        altitude: 10,
        accuracy: 5,
        altitudeAccuracy: 3,
        heading: 45,
        speed: 2,
      },
    };
  }

  /** Extract INSERT params from the mock db's runSync call log. */
  function extractInsertParams(): unknown[][] {
    const runSyncMock = mockDb.runSync as jest.Mock;
    return runSyncMock.mock.calls
      .filter(
        (call): call is [string, unknown[]] =>
          typeof call[0] === 'string' && call[0].includes('INSERT INTO gps_samples'),
      )
      .map((call) => call[1] as unknown[]);
  }

  function extractPauseEventParams(): unknown[][] {
    const runSyncMock = mockDb.runSync as jest.Mock;
    return runSyncMock.mock.calls
      .filter(
        (call): call is [string, unknown[]] =>
          typeof call[0] === 'string' && call[0].includes('INSERT INTO pause_events'),
      )
      .map((call) => call[1] as unknown[]);
  }

  // Column order in the INSERT (from database.ts flushSampleBatch):
  //   0: ride_id, 1: t_offset_ms, 2: latitude, 3: longitude, 4: altitude_m,
  //   5: accuracy_m, 6: vert_accuracy_m, 7: speed_mps, 8: bearing_deg,
  //   9: source, 10: power_w, 11: heart_rate_bpm, 12: cadence_rpm
  const COL_POWER = 10;
  const COL_HR = 11;
  const COL_CADENCE = 12;

  test('GPS-only ride writes null for every sensor column', async () => {
    await locationCallback({ data: { locations: makeLocations() }, error: null });

    const inserts = extractInsertParams();
    expect(inserts.length).toBeGreaterThan(0);
    for (const params of inserts) {
      expect(params[COL_POWER]).toBeNull();
      expect(params[COL_HR]).toBeNull();
      expect(params[COL_CADENCE]).toBeNull();
    }
  });

  test('auto-pause keeps recording state active and resumes from the next moving sample', async () => {
    const start = 1_700_000_050_000;
    (mockDb.runSync as jest.Mock).mockClear();

    await locationCallback({
      data: { locations: makeStationaryLocations(start) },
      error: null,
    });

    expect(useRecordingStore.getState().status).toBe('recording');
    expect(extractPauseEventParams()).toEqual(
      expect.arrayContaining([
        expect.arrayContaining(['ride-smoke', 'pause', expect.any(Number), 'auto_pause']),
      ]),
    );

    (mockDb.runSync as jest.Mock).mockClear();
    await locationCallback({
      data: { locations: [makeMovingLocation(start + 10_000)] },
      error: null,
    });

    expect(useRecordingStore.getState().status).toBe('recording');
    expect(extractPauseEventParams()).toEqual(
      expect.arrayContaining([
        expect.arrayContaining(['ride-smoke', 'resume', expect.any(Number), 'auto_resume']),
      ]),
    );
  });

  test('power meter with embedded cadence populates power + cadence', async () => {
    const src = new MockBleSource<PowerSample>({
      kind: 'power',
      deviceId: 'stages-001',
      deviceName: 'Stages',
      samples: [{ power_w: 245, cadence_rpm: 92, timestamp_ms: 1_000 }],
      intervalMs: 100_000,
    });
    sensorRegistry.add(src);
    src.advance();

    await locationCallback({ data: { locations: makeLocations() }, error: null });

    const inserts = extractInsertParams();
    expect(inserts.length).toBeGreaterThan(0);
    const first = inserts[0];
    expect(first[COL_POWER]).toBe(245);
    expect(first[COL_HR]).toBeNull();
    expect(first[COL_CADENCE]).toBe(92);
  });

  test('power + HR sources merge into the wide row', async () => {
    const power = new MockBleSource<PowerSample>({
      kind: 'power',
      deviceId: 'p1',
      deviceName: 'Stages',
      samples: [{ power_w: 250, cadence_rpm: 88, timestamp_ms: 1_000 }],
      intervalMs: 100_000,
    });
    const hr = new MockBleSource<HeartRateSample>({
      kind: 'heart_rate',
      deviceId: 'h1',
      deviceName: 'Garmin HRM',
      samples: [
        { heart_rate_bpm: 152, rr_intervals_ms: [400, 395], timestamp_ms: 1_000 },
      ],
      intervalMs: 100_000,
    });
    sensorRegistry.add(power);
    sensorRegistry.add(hr);
    power.advance();
    hr.advance();

    await locationCallback({ data: { locations: makeLocations() }, error: null });

    const inserts = extractInsertParams();
    expect(inserts.length).toBeGreaterThan(0);
    const first = inserts[0];
    expect(first[COL_POWER]).toBe(250);
    expect(first[COL_HR]).toBe(152);
    expect(first[COL_CADENCE]).toBe(88);
  });

  test('power-embedded cadence wins over a dedicated CSC source', async () => {
    const power = new MockBleSource<PowerSample>({
      kind: 'power',
      deviceId: 'p1',
      deviceName: 'Stages',
      samples: [{ power_w: 250, cadence_rpm: 88, timestamp_ms: 1_000 }],
      intervalMs: 100_000,
    });
    const csc = new MockBleSource<CadenceSample>({
      kind: 'cadence',
      deviceId: 'c1',
      deviceName: 'Wahoo CSC',
      samples: [{ cadence_rpm: 95, timestamp_ms: 1_000 }],
      intervalMs: 100_000,
    });
    sensorRegistry.add(power);
    sensorRegistry.add(csc);
    power.advance();
    csc.advance();

    await locationCallback({ data: { locations: makeLocations() }, error: null });

    const inserts = extractInsertParams();
    expect(inserts[0][COL_CADENCE]).toBe(88);
  });

  test('CSC-only source provides cadence when no power meter connected', async () => {
    const csc = new MockBleSource<CadenceSample>({
      kind: 'cadence',
      deviceId: 'c1',
      deviceName: 'Wahoo CSC',
      samples: [{ cadence_rpm: 95, timestamp_ms: 1_000 }],
      intervalMs: 100_000,
    });
    sensorRegistry.add(csc);
    csc.advance();

    await locationCallback({ data: { locations: makeLocations() }, error: null });

    const inserts = extractInsertParams();
    expect(inserts[0][COL_CADENCE]).toBe(95);
    expect(inserts[0][COL_POWER]).toBeNull();
    expect(inserts[0][COL_HR]).toBeNull();
  });

  test('Math.rounds non-integer cadence from CSC computation', async () => {
    const csc = new MockBleSource<CadenceSample>({
      kind: 'cadence',
      deviceId: 'c1',
      deviceName: 'Wahoo CSC',
      samples: [{ cadence_rpm: 92.7, timestamp_ms: 1_000 }],
      intervalMs: 100_000,
    });
    sensorRegistry.add(csc);
    csc.advance();

    await locationCallback({ data: { locations: makeLocations() }, error: null });

    const inserts = extractInsertParams();
    expect(inserts[0][COL_CADENCE]).toBe(93);
  });

  describe('GPS watchdog', () => {
    beforeEach(() => {
      (Sentry.captureMessage as jest.Mock).mockClear();
    });

    test('fires Sentry breadcrumb when no samples accepted for 30s+', async () => {
      jest.useFakeTimers();
      const nowSpy = jest.spyOn(Date, 'now');
      let now = 2_000_000_000_000;
      nowSpy.mockImplementation(() => now);

      // Re-start recording inside this test so the watchdog uses the spied Date.now
      useRecordingStore.getState().reset();
      useRecordingStore.getState().startRide('ride-watchdog');
      await GPS.startRecording('ride-watchdog');

      // Feed one sample so lastAcceptedAtWallclock is set (otherwise watchdog
      // treats it as "still connecting" and stays silent forever).
      await locationCallback({
        data: { locations: makeLocations(now) },
        error: null,
      });
      (Sentry.captureMessage as jest.Mock).mockClear();

      // Advance wallclock past the 30s threshold and run the watchdog tick
      now += 35_000;
      jest.advanceTimersByTime(5_000);

      expect(Sentry.captureMessage).toHaveBeenCalledWith(
        expect.stringMatching(/GPS watchdog/),
        expect.objectContaining({
          level: 'warning',
          extra: expect.objectContaining({
            rideId: 'ride-watchdog',
            gapMs: expect.any(Number),
          }),
        }),
      );

      // Throttle: another tick within the same gap should NOT re-fire
      (Sentry.captureMessage as jest.Mock).mockClear();
      now += 5_000;
      jest.advanceTimersByTime(5_000);
      expect(Sentry.captureMessage).not.toHaveBeenCalled();

      nowSpy.mockRestore();
      jest.useRealTimers();
    });

    test('restarts background location updates once when a live ride goes stale', async () => {
      jest.useFakeTimers();
      const nowSpy = jest.spyOn(Date, 'now');
      let now = 2_100_000_000_000;
      nowSpy.mockImplementation(() => now);

      useRecordingStore.getState().reset();
      useRecordingStore.getState().startRide('ride-stale-restart');
      await GPS.startRecording('ride-stale-restart');

      const hasStartedMock = Location.hasStartedLocationUpdatesAsync as jest.Mock;
      const stopUpdatesMock = Location.stopLocationUpdatesAsync as jest.Mock;
      const startUpdatesMock = Location.startLocationUpdatesAsync as jest.Mock;
      hasStartedMock.mockResolvedValueOnce(true);
      stopUpdatesMock.mockClear();
      startUpdatesMock.mockClear();

      await locationCallback({
        data: { locations: makeLocations(now) },
        error: null,
      });

      now += 35_000;
      jest.advanceTimersByTime(5_000);
      await Promise.resolve();
      await Promise.resolve();
      await Promise.resolve();

      expect(Sentry.captureMessage).toHaveBeenCalledWith(
        expect.stringMatching(/GPS watchdog/),
        expect.objectContaining({
          level: 'warning',
          extra: expect.objectContaining({
            rideId: 'ride-stale-restart',
            gapMs: expect.any(Number),
          }),
        }),
      );
      expect(stopUpdatesMock).toHaveBeenCalledWith(GPS.BACKGROUND_TASK_NAME);
      expect(startUpdatesMock).toHaveBeenCalledWith(
        GPS.BACKGROUND_TASK_NAME,
        expect.objectContaining({
          accuracy: Location.Accuracy.BestForNavigation,
          pausesUpdatesAutomatically: false,
        }),
      );

      stopUpdatesMock.mockClear();
      startUpdatesMock.mockClear();
      now += 5_000;
      jest.advanceTimersByTime(5_000);
      await Promise.resolve();
      await Promise.resolve();
      expect(stopUpdatesMock).not.toHaveBeenCalled();
      expect(startUpdatesMock).not.toHaveBeenCalled();

      nowSpy.mockRestore();
      jest.useRealTimers();
    });

    test('does not fire before any samples have been accepted', async () => {
      jest.useFakeTimers();
      const nowSpy = jest.spyOn(Date, 'now');
      let now = 2_000_000_000_000;
      nowSpy.mockImplementation(() => now);

      useRecordingStore.getState().reset();
      useRecordingStore.getState().startRide('ride-no-samples');
      await GPS.startRecording('ride-no-samples');
      (Sentry.captureMessage as jest.Mock).mockClear();

      // Advance way past threshold without any samples — watchdog should
      // treat as "still connecting", not as "stale data"
      now += 60_000;
      jest.advanceTimersByTime(5_000);

      expect(Sentry.captureMessage).not.toHaveBeenCalled();

      nowSpy.mockRestore();
      jest.useRealTimers();
    });
  });

  describe('stopRecording finalize', () => {
    test('stamps preliminary_ride_hash + parser_version onto the rides row', async () => {
      useRecordingStore.getState().reset();
      useRecordingStore.getState().startRide('ride-stop-stamp');
      await GPS.startRecording('ride-stop-stamp');

      // Feed at least one sample so the ride row has some data
      await locationCallback({
        data: { locations: makeLocations(1_700_000_030_000) },
        error: null,
      });

      (mockDb.runSync as jest.Mock).mockClear();
      await GPS.stopRecording();

      const runSyncMock = mockDb.runSync as jest.Mock;
      const updateRidesCall = runSyncMock.mock.calls.find(
        (call): call is [string, unknown[]] =>
          typeof call[0] === 'string' && call[0].startsWith('UPDATE rides'),
      );
      expect(updateRidesCall).toBeDefined();
      const [sql] = updateRidesCall!;
      // updateRide builds an UPDATE from the truthy-defined keys of the
      // updates object; both attestation columns must appear in the SET list
      expect(sql).toContain('preliminary_ride_hash = ?');
      expect(sql).toContain('parser_version = ?');
      expect(sql).toContain("status = ?");
      expect(sql).toContain('ended_at = ?');
    });

    test('zero-sample ride still stamps hash (start then immediate stop)', async () => {
      // Ride started but user stopped before any GPS sample arrived (common
      // real-world case: permission dialog delays, cold GPS lock, accidental
      // tap). The attestation lineage must still land — hash of the empty
      // canonical form is deterministic, not null.
      useRecordingStore.getState().reset();
      useRecordingStore.getState().startRide('ride-zero-sample');
      await GPS.startRecording('ride-zero-sample');

      // computePreliminaryHash reads the ride row via getFirstSync. The
      // global mock returns null by default; stub it here so the hash
      // path exercises the full canonicalize → SHA256 chain.
      (mockDb.getFirstSync as jest.Mock).mockReturnValueOnce({
        id: 'ride-zero-sample',
        status: 'recording',
        started_at: 1_700_000_000_000,
        ended_at: null,
        duration_ms: 0,
        moving_time_ms: 0,
        distance_m: 0,
        elevation_gain_m: 0,
        max_speed_mps: 0,
        sport_type: 'ride',
        clock_drift_ms: null,
        sample_count: 0,
        rejected_samples: null,
        upload_id: null,
        notes: null,
        preliminary_ride_hash: null,
        parser_version: null,
        had_crash_recovery: 0,
      });

      (mockDb.runSync as jest.Mock).mockClear();
      await GPS.stopRecording();

      const runSyncMock = mockDb.runSync as jest.Mock;
      const updateRidesCall = runSyncMock.mock.calls.find(
        (call): call is [string, unknown[]] =>
          typeof call[0] === 'string' && call[0].startsWith('UPDATE rides'),
      );
      expect(updateRidesCall).toBeDefined();
      const [sql, params] = updateRidesCall!;
      expect(sql).toContain('preliminary_ride_hash = ?');
      expect(sql).toContain('parser_version = ?');

      // Find the preliminary_ride_hash param by walking the SET list.
      // updateRide's SET list mirrors the order fields appear in the
      // updates object passed by stopRecording.
      const setList = sql
        .replace(/^UPDATE rides SET /, '')
        .replace(/ WHERE.*$/, '')
        .split(', ')
        .map((s) => s.split(' = ')[0]);
      const hashIdx = setList.indexOf('preliminary_ride_hash');
      const parserIdx = setList.indexOf('parser_version');
      expect(hashIdx).toBeGreaterThanOrEqual(0);
      expect(parserIdx).toBeGreaterThanOrEqual(0);
      // The hash must be a non-empty Uint8Array, not null — even without samples.
      // Length is driven by the expo-crypto mock, not real SHA256 (covered in
      // preliminaryHash.test.ts with the real-crypto override).
      expect(params[hashIdx]).toBeInstanceOf(Uint8Array);
      expect((params[hashIdx] as Uint8Array).byteLength).toBeGreaterThan(0);
      // parser_version is a positive integer
      expect(typeof params[parserIdx]).toBe('number');
      expect(params[parserIdx] as number).toBeGreaterThan(0);
    });

    test('stop while paused subtracts the in-flight pause from duration', async () => {
      // Pause-duration math at stopRecording:
      //   finalPausedMs = totalPausedMs + (Date.now() - pausedAtWallclock)
      //   finalElapsed  = Date.now() - rideStartWallclock - finalPausedMs
      // If the stop path forgot the in-flight pause window, riders who
      // tap Stop from the paused screen would bank phantom elapsed time.
      jest.useFakeTimers();
      const nowSpy = jest.spyOn(Date, 'now');
      let now = 1_800_000_000_000;
      nowSpy.mockImplementation(() => now);

      useRecordingStore.getState().reset();
      useRecordingStore.getState().startRide('ride-stop-paused');
      await GPS.startRecording('ride-stop-paused'); // captures rideStartWallclock = now

      // Feed a sample at T+5s so the ride has something to stamp
      now += 5_000;
      await locationCallback({
        data: { locations: makeLocations(now) },
        error: null,
      });

      // Pause at T+10s
      now += 5_000;
      GPS.pauseRecording('manual');

      // Rider sits paused for 7 seconds, then taps Stop at T+17s
      now += 7_000;

      // Stub the ride row read so computePreliminaryHash can hash
      (mockDb.getFirstSync as jest.Mock).mockReturnValueOnce({
        id: 'ride-stop-paused',
        status: 'paused',
        started_at: 1_800_000_000_000,
        ended_at: null,
        duration_ms: 0,
        moving_time_ms: 0,
        distance_m: 0,
        elevation_gain_m: 0,
        max_speed_mps: 0,
        sport_type: 'ride',
        clock_drift_ms: null,
        sample_count: 1,
        rejected_samples: null,
        upload_id: null,
        notes: null,
        preliminary_ride_hash: null,
        parser_version: null,
        had_crash_recovery: 0,
      });

      (mockDb.runSync as jest.Mock).mockClear();
      await GPS.stopRecording();

      const runSyncMock = mockDb.runSync as jest.Mock;
      const updateCall = runSyncMock.mock.calls.find(
        (call): call is [string, unknown[]] =>
          typeof call[0] === 'string' && call[0].startsWith('UPDATE rides'),
      );
      expect(updateCall).toBeDefined();
      const [sql, params] = updateCall!;
      const setList = sql
        .replace(/^UPDATE rides SET /, '')
        .replace(/ WHERE.*$/, '')
        .split(', ')
        .map((s) => s.split(' = ')[0]);
      const durationIdx = setList.indexOf('duration_ms');
      expect(durationIdx).toBeGreaterThanOrEqual(0);

      // Elapsed = 17s total - 7s paused = 10s. Accept ±100ms for rounding.
      const duration = params[durationIdx] as number;
      expect(duration).toBeGreaterThanOrEqual(9_900);
      expect(duration).toBeLessThanOrEqual(10_100);

      nowSpy.mockRestore();
      jest.useRealTimers();
    });

    test('flushes pending sample buffer before finalize (no data left in memory)', async () => {
      useRecordingStore.getState().reset();
      useRecordingStore.getState().startRide('ride-stop-flush');
      await GPS.startRecording('ride-stop-flush');

      // Feed fewer than BATCH_SIZE (10) samples so they stay in the buffer
      await locationCallback({
        data: {
          locations: [
            {
              timestamp: 1_700_000_040_000,
              coords: {
                latitude: 39.95,
                longitude: -75.16,
                altitude: 10,
                accuracy: 5,
                altitudeAccuracy: 3,
                heading: 45,
                speed: 5,
              },
            },
          ],
        },
        error: null,
      });

      const runSyncMock = mockDb.runSync as jest.Mock;
      runSyncMock.mockClear();
      await GPS.stopRecording();

      // stopRecording calls flushBuffer first; there must be at least one
      // INSERT alongside the UPDATE for the stamped metadata
      const hasInsert = runSyncMock.mock.calls.some(
        (call) =>
          typeof call[0] === 'string' && call[0].includes('INSERT INTO gps_samples'),
      );
      expect(hasInsert).toBe(true);
    });
  });

  test('sensors stopped mid-ride drop out of subsequent rows', async () => {
    const power = new MockBleSource<PowerSample>({
      kind: 'power',
      deviceId: 'p1',
      deviceName: 'Stages',
      samples: [{ power_w: 250, cadence_rpm: 88, timestamp_ms: 1_000 }],
      intervalMs: 100_000,
    });
    sensorRegistry.add(power);
    power.advance();

    // First batch: power present
    await locationCallback({ data: { locations: makeLocations(1_700_000_000_000) }, error: null });

    // Disconnect the sensor
    await power.stop();

    // Second batch: power cleared, samples should have null power
    await locationCallback({
      data: { locations: makeLocations(1_700_000_010_000) },
      error: null,
    });

    const inserts = extractInsertParams();
    // At least 2 inserts expected (one per batch's flush)
    expect(inserts.length).toBeGreaterThanOrEqual(2);
    // First batch inserts had power
    expect(inserts[0][COL_POWER]).toBe(250);
    // Last batch inserts have null (stop() cleared latest)
    const lastInsert = inserts[inserts.length - 1];
    expect(lastInsert[COL_POWER]).toBeNull();
  });

  // MOBILE_TRUTHS §4.2: "If no power meter was paired, the ride's power
  // field is empty — not zero." These assertions pin the contract end-to-end.
  describe('MOBILE_TRUTHS §4.2 absence-vs-zero (power-first)', () => {
    test('mid-ride markLost path writes null, never 0', async () => {
      // markLost is the path BLE disconnect events take (device.onDisconnected,
      // adapter state change, staleness audit). Distinct from stop() which
      // the pairing UI path uses. Both must converge on null, not 0.
      const power = new MockBleSource<PowerSample>({
        kind: 'power',
        deviceId: 'p1',
        deviceName: 'Stages',
        samples: [{ power_w: 230, cadence_rpm: 90, timestamp_ms: 1_000 }],
        intervalMs: 100_000,
      });
      sensorRegistry.add(power);
      power.advance();

      // First batch: sensor alive
      await locationCallback({
        data: { locations: makeLocations(1_700_000_000_000) },
        error: null,
      });

      // Simulate BLE drop event — calls markLost directly, bypassing stop()
      power.markLost();

      // Second batch: every row must have null power, never 0
      await locationCallback({
        data: { locations: makeLocations(1_700_000_010_000) },
        error: null,
      });

      const inserts = extractInsertParams();
      expect(inserts.length).toBeGreaterThanOrEqual(2);
      // First batch has power
      expect(inserts[0][COL_POWER]).toBe(230);
      // Every post-drop row: strictly null, strictly not 0
      const postDropRows = inserts.slice(inserts.findIndex(
        (row) => row[COL_POWER] === null,
      ));
      expect(postDropRows.length).toBeGreaterThan(0);
      for (const row of postDropRows) {
        expect(row[COL_POWER]).toBeNull();
        expect(row[COL_POWER]).not.toBe(0);
      }
    });

    test('sensor removed from registry (logout path) writes null', async () => {
      // pairingStore.disconnectAll() removes the source from the registry
      // after source.stop(). Subsequent GPS ticks must see an empty registry
      // for this kind and write null — not read a stale cached value from
      // anywhere downstream.
      const power = new MockBleSource<PowerSample>({
        kind: 'power',
        deviceId: 'p1',
        deviceName: 'Stages',
        samples: [{ power_w: 190, timestamp_ms: 1_000 }],
        intervalMs: 100_000,
      });
      sensorRegistry.add(power);
      power.advance();

      await locationCallback({
        data: { locations: makeLocations(1_700_000_000_000) },
        error: null,
      });

      // Simulate the logout path: stop and explicit remove from registry.
      await power.stop();
      sensorRegistry.remove('p1', 'power');

      await locationCallback({
        data: { locations: makeLocations(1_700_000_010_000) },
        error: null,
      });

      const inserts = extractInsertParams();
      expect(inserts[0][COL_POWER]).toBe(190);
      const last = inserts[inserts.length - 1];
      expect(last[COL_POWER]).toBeNull();
      expect(last[COL_POWER]).not.toBe(0);
      // Registry sanity: no power source remains
      expect(sensorRegistry.byKind('power')).toHaveLength(0);
    });

    test('genuine zero power sample (coasting) is preserved, not laundered to null', async () => {
      // Edge case in the §4.2 contract: a power meter actively reporting
      // power_w=0 is evidence that the rider is coasting (real zero power
      // produced by the meter), which is different from absence. The wide
      // row must record 0, not null, when the meter is alive and reports 0.
      const power = new MockBleSource<PowerSample>({
        kind: 'power',
        deviceId: 'p1',
        deviceName: 'Stages',
        samples: [{ power_w: 0, timestamp_ms: 1_000 }],
        intervalMs: 100_000,
      });
      sensorRegistry.add(power);
      power.advance();

      await locationCallback({
        data: { locations: makeLocations(1_700_000_000_000) },
        error: null,
      });

      const inserts = extractInsertParams();
      expect(inserts.length).toBeGreaterThan(0);
      // Zero is a valid measurement. It must appear on the row, not be coerced to null.
      expect(inserts[0][COL_POWER]).toBe(0);
      expect(inserts[0][COL_POWER]).not.toBeNull();
    });
  });

  // -----------------------------------------------------------------------
  // HR + CSC parity with the power-slice. These close §5.2 / §5.3 of the
  // M2 audit and pin the §4.2 absence-vs-zero contract for every source.
  // -----------------------------------------------------------------------

  describe('HR-only ride', () => {
    test('HR strap paired alone populates heart_rate_bpm, leaves power/cadence null', async () => {
      const hr = new MockBleSource<HeartRateSample>({
        kind: 'heart_rate',
        deviceId: 'hrm-1',
        deviceName: 'Polar H10',
        samples: [
          { heart_rate_bpm: 148, rr_intervals_ms: [415, 410], timestamp_ms: 1_000 },
        ],
        intervalMs: 100_000,
      });
      sensorRegistry.add(hr);
      hr.advance();

      await locationCallback({ data: { locations: makeLocations() }, error: null });

      const inserts = extractInsertParams();
      expect(inserts.length).toBeGreaterThan(0);
      for (const row of inserts) {
        expect(row[COL_HR]).toBe(148);
        expect(row[COL_POWER]).toBeNull();
        expect(row[COL_CADENCE]).toBeNull();
      }
    });

    test('HR disconnect mid-ride writes null to subsequent rows', async () => {
      const hr = new MockBleSource<HeartRateSample>({
        kind: 'heart_rate',
        deviceId: 'hrm-1',
        deviceName: 'Garmin HRM-Dual',
        samples: [{ heart_rate_bpm: 162, timestamp_ms: 1_000 }],
        intervalMs: 100_000,
      });
      sensorRegistry.add(hr);
      hr.advance();

      // First batch: strap alive
      await locationCallback({
        data: { locations: makeLocations(1_700_000_000_000) },
        error: null,
      });

      // BLE drop event on the strap — markLost directly (not stop()).
      hr.markLost();

      await locationCallback({
        data: { locations: makeLocations(1_700_000_010_000) },
        error: null,
      });

      const inserts = extractInsertParams();
      expect(inserts.length).toBeGreaterThanOrEqual(2);
      // First batch: HR populated.
      expect(inserts[0][COL_HR]).toBe(162);
      // Every post-drop row: strictly null, never 0.
      const postDropRows = inserts.slice(
        inserts.findIndex((row) => row[COL_HR] === null),
      );
      expect(postDropRows.length).toBeGreaterThan(0);
      for (const row of postDropRows) {
        expect(row[COL_HR]).toBeNull();
        expect(row[COL_HR]).not.toBe(0);
      }
    });

    test('HR source removed from registry writes null (logout path)', async () => {
      const hr = new MockBleSource<HeartRateSample>({
        kind: 'heart_rate',
        deviceId: 'hrm-1',
        deviceName: 'Wahoo TICKR',
        samples: [{ heart_rate_bpm: 140, timestamp_ms: 1_000 }],
        intervalMs: 100_000,
      });
      sensorRegistry.add(hr);
      hr.advance();

      await locationCallback({
        data: { locations: makeLocations(1_700_000_000_000) },
        error: null,
      });

      await hr.stop();
      sensorRegistry.remove('hrm-1', 'heart_rate');

      await locationCallback({
        data: { locations: makeLocations(1_700_000_010_000) },
        error: null,
      });

      const inserts = extractInsertParams();
      expect(inserts[0][COL_HR]).toBe(140);
      const last = inserts[inserts.length - 1];
      expect(last[COL_HR]).toBeNull();
      expect(last[COL_HR]).not.toBe(0);
      expect(sensorRegistry.byKind('heart_rate')).toHaveLength(0);
    });

    test('genuine zero bpm from HR device (contact lost) is preserved', async () => {
      // Some straps report 0 bpm when contact drops (firmware reports 0 rather
      // than stopping notifications). That 0 is evidence and must not be
      // laundered to null. Upper layers use sensor_contact to disambiguate.
      const hr = new MockBleSource<HeartRateSample>({
        kind: 'heart_rate',
        deviceId: 'hrm-1',
        deviceName: 'Cheap strap',
        samples: [
          { heart_rate_bpm: 0, sensor_contact: false, timestamp_ms: 1_000 },
        ],
        intervalMs: 100_000,
      });
      sensorRegistry.add(hr);
      hr.advance();

      await locationCallback({ data: { locations: makeLocations() }, error: null });

      const inserts = extractInsertParams();
      expect(inserts.length).toBeGreaterThan(0);
      expect(inserts[0][COL_HR]).toBe(0);
      expect(inserts[0][COL_HR]).not.toBeNull();
    });
  });

  describe('CSC-only ride (no power meter paired)', () => {
    test('CSC sensor paired alone populates cadence_rpm, leaves power/HR null', async () => {
      const csc = new MockBleSource<CadenceSample>({
        kind: 'cadence',
        deviceId: 'csc-1',
        deviceName: 'Wahoo RPM',
        samples: [{ cadence_rpm: 88, timestamp_ms: 1_000 }],
        intervalMs: 100_000,
      });
      sensorRegistry.add(csc);
      csc.advance();

      await locationCallback({ data: { locations: makeLocations() }, error: null });

      const inserts = extractInsertParams();
      expect(inserts.length).toBeGreaterThan(0);
      for (const row of inserts) {
        expect(row[COL_CADENCE]).toBe(88);
        expect(row[COL_POWER]).toBeNull();
        expect(row[COL_HR]).toBeNull();
      }
    });

    test('CSC disconnect mid-ride writes null to subsequent rows', async () => {
      const csc = new MockBleSource<CadenceSample>({
        kind: 'cadence',
        deviceId: 'csc-1',
        deviceName: 'Garmin GSC-10',
        samples: [{ cadence_rpm: 95, timestamp_ms: 1_000 }],
        intervalMs: 100_000,
      });
      sensorRegistry.add(csc);
      csc.advance();

      await locationCallback({
        data: { locations: makeLocations(1_700_000_000_000) },
        error: null,
      });

      csc.markLost();

      await locationCallback({
        data: { locations: makeLocations(1_700_000_010_000) },
        error: null,
      });

      const inserts = extractInsertParams();
      expect(inserts.length).toBeGreaterThanOrEqual(2);
      expect(inserts[0][COL_CADENCE]).toBe(95);
      const postDropRows = inserts.slice(
        inserts.findIndex((row) => row[COL_CADENCE] === null),
      );
      expect(postDropRows.length).toBeGreaterThan(0);
      for (const row of postDropRows) {
        expect(row[COL_CADENCE]).toBeNull();
        expect(row[COL_CADENCE]).not.toBe(0);
      }
    });

    test('CSC source removed from registry writes null (logout path)', async () => {
      const csc = new MockBleSource<CadenceSample>({
        kind: 'cadence',
        deviceId: 'csc-1',
        deviceName: 'Wahoo RPM',
        samples: [{ cadence_rpm: 92, timestamp_ms: 1_000 }],
        intervalMs: 100_000,
      });
      sensorRegistry.add(csc);
      csc.advance();

      await locationCallback({
        data: { locations: makeLocations(1_700_000_000_000) },
        error: null,
      });

      await csc.stop();
      sensorRegistry.remove('csc-1', 'cadence');

      await locationCallback({
        data: { locations: makeLocations(1_700_000_010_000) },
        error: null,
      });

      const inserts = extractInsertParams();
      expect(inserts[0][COL_CADENCE]).toBe(92);
      const last = inserts[inserts.length - 1];
      expect(last[COL_CADENCE]).toBeNull();
      expect(last[COL_CADENCE]).not.toBe(0);
      expect(sensorRegistry.byKind('cadence')).toHaveLength(0);
    });

    test('genuine zero cadence (coasting) is preserved', async () => {
      // Rider coasting but sensor still live — 0 rpm is a real measurement,
      // distinct from sensor absence. Mirrors the power-zero case.
      const csc = new MockBleSource<CadenceSample>({
        kind: 'cadence',
        deviceId: 'csc-1',
        deviceName: 'Wahoo RPM',
        samples: [{ cadence_rpm: 0, timestamp_ms: 1_000 }],
        intervalMs: 100_000,
      });
      sensorRegistry.add(csc);
      csc.advance();

      await locationCallback({ data: { locations: makeLocations() }, error: null });

      const inserts = extractInsertParams();
      expect(inserts.length).toBeGreaterThan(0);
      expect(inserts[0][COL_CADENCE]).toBe(0);
      expect(inserts[0][COL_CADENCE]).not.toBeNull();
    });
  });

  describe('all three sources (power + HR + CSC)', () => {
    test('all connected: power+HR populate and power-embedded cadence wins', async () => {
      const power = new MockBleSource<PowerSample>({
        kind: 'power',
        deviceId: 'p1',
        deviceName: 'Stages',
        samples: [{ power_w: 260, cadence_rpm: 90, timestamp_ms: 1_000 }],
        intervalMs: 100_000,
      });
      const hr = new MockBleSource<HeartRateSample>({
        kind: 'heart_rate',
        deviceId: 'h1',
        deviceName: 'Polar H10',
        samples: [{ heart_rate_bpm: 155, timestamp_ms: 1_000 }],
        intervalMs: 100_000,
      });
      const csc = new MockBleSource<CadenceSample>({
        kind: 'cadence',
        deviceId: 'c1',
        deviceName: 'Wahoo RPM',
        samples: [{ cadence_rpm: 95, timestamp_ms: 1_000 }],
        intervalMs: 100_000,
      });
      sensorRegistry.add(power);
      sensorRegistry.add(hr);
      sensorRegistry.add(csc);
      power.advance();
      hr.advance();
      csc.advance();

      await locationCallback({ data: { locations: makeLocations() }, error: null });

      const inserts = extractInsertParams();
      expect(inserts.length).toBeGreaterThan(0);
      const first = inserts[0];
      expect(first[COL_POWER]).toBe(260);
      expect(first[COL_HR]).toBe(155);
      // Power-embedded cadence (90) wins over CSC (95).
      expect(first[COL_CADENCE]).toBe(90);
    });

    test('all three drop in sequence: rows reflect each absence honestly', async () => {
      const power = new MockBleSource<PowerSample>({
        kind: 'power',
        deviceId: 'p1',
        deviceName: 'Stages',
        samples: [{ power_w: 240, cadence_rpm: 88, timestamp_ms: 1_000 }],
        intervalMs: 100_000,
      });
      const hr = new MockBleSource<HeartRateSample>({
        kind: 'heart_rate',
        deviceId: 'h1',
        deviceName: 'TICKR',
        samples: [{ heart_rate_bpm: 150, timestamp_ms: 1_000 }],
        intervalMs: 100_000,
      });
      const csc = new MockBleSource<CadenceSample>({
        kind: 'cadence',
        deviceId: 'c1',
        deviceName: 'Wahoo RPM',
        samples: [{ cadence_rpm: 92, timestamp_ms: 1_000 }],
        intervalMs: 100_000,
      });
      sensorRegistry.add(power);
      sensorRegistry.add(hr);
      sensorRegistry.add(csc);
      power.advance();
      hr.advance();
      csc.advance();

      // Batch 1: all three alive.
      await locationCallback({
        data: { locations: makeLocations(1_700_000_000_000) },
        error: null,
      });

      // Drop HR first.
      hr.markLost();
      await locationCallback({
        data: { locations: makeLocations(1_700_000_010_000) },
        error: null,
      });

      // Drop power next. CSC remains, so cadence fills from CSC now that
      // there is no power-embedded cadence.
      power.markLost();
      await locationCallback({
        data: { locations: makeLocations(1_700_000_020_000) },
        error: null,
      });

      // Drop CSC finally — no sensors left, every column null.
      csc.markLost();
      await locationCallback({
        data: { locations: makeLocations(1_700_000_030_000) },
        error: null,
      });

      const inserts = extractInsertParams();
      expect(inserts.length).toBeGreaterThanOrEqual(4);

      // Batch 1: all populated.
      expect(inserts[0][COL_POWER]).toBe(240);
      expect(inserts[0][COL_HR]).toBe(150);
      expect(inserts[0][COL_CADENCE]).toBe(88);

      // After HR drop: power + cadence still populated, HR null.
      const afterHrDrop = inserts.find((r) => r[COL_HR] === null && r[COL_POWER] === 240);
      expect(afterHrDrop).toBeDefined();
      expect(afterHrDrop![COL_HR]).toBeNull();
      expect(afterHrDrop![COL_POWER]).toBe(240);
      expect(afterHrDrop![COL_CADENCE]).toBe(88);

      // After power drop: HR null, power null, cadence from CSC fallback.
      const afterPowerDrop = inserts.find(
        (r) => r[COL_HR] === null && r[COL_POWER] === null && r[COL_CADENCE] === 92,
      );
      expect(afterPowerDrop).toBeDefined();
      expect(afterPowerDrop![COL_CADENCE]).toBe(92);

      // Final batch: every sensor dropped, every column null.
      const finalBatchNullRows = inserts.filter(
        (r) => r[COL_POWER] === null && r[COL_HR] === null && r[COL_CADENCE] === null,
      );
      expect(finalBatchNullRows.length).toBeGreaterThan(0);
      for (const row of finalBatchNullRows) {
        expect(row[COL_POWER]).toBeNull();
        expect(row[COL_HR]).toBeNull();
        expect(row[COL_CADENCE]).toBeNull();
      }
    });

    test('HR + CSC only (no power) populates HR + CSC cadence', async () => {
      // Common setup for riders without a power meter: chest strap + cadence
      // pod. Power column stays null; cadence comes from CSC because no
      // power-embedded cadence exists.
      const hr = new MockBleSource<HeartRateSample>({
        kind: 'heart_rate',
        deviceId: 'h1',
        deviceName: 'Polar H10',
        samples: [{ heart_rate_bpm: 142, timestamp_ms: 1_000 }],
        intervalMs: 100_000,
      });
      const csc = new MockBleSource<CadenceSample>({
        kind: 'cadence',
        deviceId: 'c1',
        deviceName: 'Wahoo RPM',
        samples: [{ cadence_rpm: 85, timestamp_ms: 1_000 }],
        intervalMs: 100_000,
      });
      sensorRegistry.add(hr);
      sensorRegistry.add(csc);
      hr.advance();
      csc.advance();

      await locationCallback({ data: { locations: makeLocations() }, error: null });

      const inserts = extractInsertParams();
      expect(inserts.length).toBeGreaterThan(0);
      for (const row of inserts) {
        expect(row[COL_POWER]).toBeNull();
        expect(row[COL_HR]).toBe(142);
        expect(row[COL_CADENCE]).toBe(85);
      }
    });
  });
});
