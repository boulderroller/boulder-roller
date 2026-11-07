/**
 * GPS Recording Service
 *
 * Uses expo-location background task for GPS recording in both foreground
 * and background. A single location source (startLocationUpdatesAsync)
 * prevents duplicate samples.
 *
 * Per MOBILE_PHASE0_RESOLUTIONS.md FIX-6: expo-location, not Transistor ($300/yr).
 * GPS config per GPS_INTEGRITY spec Section 5.2, adapted for expo-location.
 *
 * --- Clock domains (MOBILE_TRUTHS §3) ---
 *
 * This file reasons about two clocks. Per MOBILE_TRUTHS §3, mobile must
 * never silently conflate them.
 *
 *   WALL-CLOCK MS — Date.now(). Authoritative for ride start/end, pause
 *     and resume events, ride duration, and UI elapsed display. Can jump
 *     across suspension or NTP correction. Domain carried by all module
 *     state ending in `Wallclock` and by `totalPausedMs` / `finalPausedMs`.
 *
 *   GPS-SAMPLE MS — location.timestamp from expo-location. Authoritative
 *     for ordering samples within a ride and for the external witness of
 *     when a reading was captured. Does not flow while GPS is dark.
 *
 * iOS and Android both return location.timestamp as Unix milliseconds
 * since epoch — the same unit as Date.now() — so the two can be
 * subtracted without conversion. That subtraction is DELIBERATE, not
 * silent: it is the one intentional cross-domain pattern and is wrapped
 * by `sampleOffsetMsFromRideStart()` below. Every arithmetic site either
 * stays inside a single domain or calls the helper.
 *
 * Monotonic (performance.now) was removed earlier because it freezes
 * during iOS background suspension and cannot survive a crash-recovery
 * timeline.
 */

import * as Location from 'expo-location';
import * as TaskManager from 'expo-task-manager';
import * as Sentry from '@sentry/react-native';

import { validateGPSSample, type GPSSample } from '../lib/gpsValidation';
import { computePreliminaryHash } from '../lib/preliminaryHash';
import {
  recordRideValidationEvent,
  rideHashBytesToHex,
} from '../lib/rideValidation';
import { useRecordingStore } from '../stores/recordingStore';
import {
  getDatabase,
  flushSampleBatch,
  insertPauseEvent,
  updateRide,
  deleteRide,
  type GPSSampleRow,
} from './database';
import { sensorRegistry } from './sensors/registry';

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const BACKGROUND_LOCATION_TASK = 'BR_BACKGROUND_LOCATION';
const BATCH_SIZE = 10;
const MOVING_SPEED_THRESHOLD_MPS = 0.5; // Below this = stationary
const AUTO_PAUSE_SAMPLES = 10; // 10 consecutive stationary samples = auto-pause
const AUTO_RESUME_SPEED_MPS = 1.0; // Above this = auto-resume from auto-pause

/** Watchdog: fire a Sentry breadcrumb if no GPS sample is accepted for this long. */
const GPS_STALE_GAP_MS = 30_000;
/** How often the watchdog inspects sample freshness. Cheap. */
const GPS_WATCHDOG_INTERVAL_MS = 5_000;
const LOCATION_UPDATES_OPTIONS = {
  accuracy: Location.Accuracy.BestForNavigation,
  timeInterval: 1000,
  distanceInterval: 0,
  showsBackgroundLocationIndicator: true,
  activityType: Location.ActivityType.Fitness,
  pausesUpdatesAutomatically: false,
  foregroundService: {
    notificationTitle: 'Recording ride',
    notificationBody: 'BoulderRoller is tracking your ride',
    notificationColor: '#c4a035',
  },
};

// ---------------------------------------------------------------------------
// Module-level state (not in Zustand — these are recording internals)
// ---------------------------------------------------------------------------

let sampleBuffer: GPSSampleRow[] = [];
let lastAcceptedSample: GPSSample | null = null;
/** WALL-CLOCK MS — Date.now() of last accepted sample. Drives the watchdog. */
let lastAcceptedAtWallclock = 0;
/** WALL-CLOCK MS — Date.now() at ride start. */
let rideStartWallclock = 0;
let elapsedTimerInterval: ReturnType<typeof setInterval> | null = null;
let gpsWatchdogInterval: ReturnType<typeof setInterval> | null = null;
let gpsWatchdogFiredForCurrentGap = false;
let gpsRecoveryInFlight = false;
/** WALL-CLOCK MS — Date.now() when paused. Wallclock survives iOS suspension. */
let pausedAtWallclock = 0;
/** WALL-CLOCK MS — accumulated pause duration (wall-to-wall subtractions). */
let totalPausedMs = 0;
/** Auto-pause is recorder-internal; Zustand stays `recording` so GPS cannot strand. */
let autoPauseActive = false;

// Running aggregates for batch flush
let cumulativeDistanceM = 0;
let cumulativeElevationGainM = 0;
let maxSpeedMps = 0;
/** WALL-CLOCK MS — accumulated moving time (computed from GPS-sample deltas, same-domain). */
let movingTimeMs = 0;
let lastLat: number | null = null;
let lastLon: number | null = null;
let lastAltitude: number | null = null;
/** GPS-SAMPLE MS — last sample.timestamp observed above the moving threshold. */
let lastMovingTimestamp = 0;
let stationaryCount = 0;

// ---------------------------------------------------------------------------
// Clock-domain helper (MOBILE_TRUTHS §3)
// ---------------------------------------------------------------------------

/**
 * The one intentional cross-domain subtraction in this file.
 *
 * Computes how far into the ride a GPS sample landed, in milliseconds
 * since ride start, with accumulated pause duration removed.
 *
 * Valid because iOS and Android both emit `location.timestamp` as Unix
 * milliseconds since epoch — the same domain Date.now() reports for
 * `rideStartWallclock`. The subtraction is semantically "external
 * witness time minus device wall time," but numerically both are Unix
 * ms, so the arithmetic holds.
 *
 * Every offset written to `gps_samples.t_offset_ms` and every pause
 * event's `t_offset_ms` flows through this helper. Any future additions
 * that need "offset from ride start for a sample" must call this helper,
 * not replicate the inline subtraction.
 *
 * @param sampleTimestampMs  GPS-SAMPLE MS from location.timestamp
 * @param rideStartMs        WALL-CLOCK MS from rideStartWallclock
 * @param pausedMs           WALL-CLOCK MS accumulated pause duration
 * @returns rounded ms offset from ride start, pause time removed
 */
function sampleOffsetMsFromRideStart(
  sampleTimestampMs: number,
  rideStartMs: number,
  pausedMs: number,
): number {
  return Math.round(sampleTimestampMs - rideStartMs - pausedMs);
}

/** Exported for testing. */
export { sampleOffsetMsFromRideStart };

// ---------------------------------------------------------------------------
// Haversine distance (meters) between two WGS84 points
// ---------------------------------------------------------------------------

function haversine(lat1: number, lon1: number, lat2: number, lon2: number): number {
  const R = 6371000; // Earth radius in meters
  const dLat = (lat2 - lat1) * Math.PI / 180;
  const dLon = (lon2 - lon1) * Math.PI / 180;
  const a =
    Math.sin(dLat / 2) * Math.sin(dLat / 2) +
    Math.cos(lat1 * Math.PI / 180) * Math.cos(lat2 * Math.PI / 180) *
    Math.sin(dLon / 2) * Math.sin(dLon / 2);
  const c = 2 * Math.atan2(Math.sqrt(a), Math.sqrt(1 - a));
  return R * c;
}

// ---------------------------------------------------------------------------
// Background task definition (must be at module scope per expo-task-manager)
// ---------------------------------------------------------------------------

TaskManager.defineTask(BACKGROUND_LOCATION_TASK, async ({ data, error }: { data: unknown; error: { message: string } | null }) => {
  if (error) {
    console.warn('[GPSRecording] Background task error:', error.message);
    return;
  }
  if (data) {
    const { locations } = data as { locations: Location.LocationObject[] };
    for (const location of locations) {
      processLocationUpdate(location);
    }
  }
});

// ---------------------------------------------------------------------------
// Core location processing
// ---------------------------------------------------------------------------

function processLocationUpdate(location: Location.LocationObject): void {
  const store = useRecordingStore.getState();
  // Accept samples only while actively recording. Auto-pause deliberately
  // keeps the shared status as `recording`; manual pause/stopped/idle reject.
  if (store.status !== 'recording') return;

  const rideId = store.rideId;
  if (!rideId) return;

  const sample: GPSSample = {
    timestamp: location.timestamp,
    latitude: location.coords.latitude,
    longitude: location.coords.longitude,
    altitude: location.coords.altitude,
    accuracy: location.coords.accuracy ?? 999,
    altitudeAccuracy: location.coords.altitudeAccuracy,
    speed: location.coords.speed,
    bearing: location.coords.heading,
  };

  // Android mock-location soft-suspect tagging.
  // Expo exposes `mocked?: boolean` on Android (maps to isFromMockProvider).
  // iOS CLLocationSourceInformation.isSimulatedBySoftware is NOT exposed by
  // expo-location — requires a native module (tracked for Phase B).
  // We tag but do NOT reject: the flag is bypassable on rooted devices
  // (Agent B research, KlaasNotFound 2016) — treat as one weak signal.
  if ((location as { mocked?: boolean }).mocked === true) {
    store.incrementRejection('mock_location_android');
  }

  // Validate
  const result = validateGPSSample(sample, lastAcceptedSample);
  if (!result.valid) {
    if (result.reason) {
      store.incrementRejection(result.reason);
    }
    return;
  }

  lastAcceptedSample = sample;
  lastAcceptedAtWallclock = Date.now();

  // t_offset_ms: rider-time-into-ride for this sample. Uses the one
  // intentional cross-domain subtraction (see sampleOffsetMsFromRideStart).
  const tOffsetMs = sampleOffsetMsFromRideStart(
    sample.timestamp,
    rideStartWallclock,
    totalPausedMs,
  );

  // Update running aggregates
  const speed = sample.speed ?? 0;
  if (speed > maxSpeedMps) {
    maxSpeedMps = speed;
  }

  // Distance (haversine from previous accepted sample)
  if (lastLat !== null && lastLon !== null) {
    const dist = haversine(lastLat, lastLon, sample.latitude, sample.longitude);
    // Cap per-step distance at 500m (per utils.rs MAX_STEP_DISTANCE_M)
    if (dist <= 500) {
      cumulativeDistanceM += dist;
    }
  }

  // Elevation gain (raw positive changes)
  if (lastAltitude !== null && sample.altitude !== null) {
    const elevDelta = sample.altitude - lastAltitude;
    if (elevDelta > 0) {
      cumulativeElevationGainM += elevDelta;
    }
  }

  // Moving time & auto-pause/resume logic
  if (speed > MOVING_SPEED_THRESHOLD_MPS) {
    if (lastMovingTimestamp > 0) {
      // GPS-to-GPS: both sample.timestamp and lastMovingTimestamp are
      // GPS-SAMPLE MS, so this subtraction is same-domain.
      movingTimeMs += Math.min(sample.timestamp - lastMovingTimestamp, 5000);
    }
    lastMovingTimestamp = sample.timestamp;
    stationaryCount = 0;

    // Auto-resume: rider started moving again after auto-pause
    if (autoPauseActive && speed > AUTO_RESUME_SPEED_MPS) {
      autoPauseActive = false;
      // Wall-to-wall: Date.now() minus pausedAtWallclock is same-domain.
      totalPausedMs += Date.now() - pausedAtWallclock;
      pausedAtWallclock = 0;

      const resumeOffsetMs = sampleOffsetMsFromRideStart(
        sample.timestamp,
        rideStartWallclock,
        totalPausedMs,
      );
      const db = getDatabase();
      insertPauseEvent(db, {
        ride_id: rideId,
        event_type: 'resume',
        t_offset_ms: resumeOffsetMs,
        reason: 'auto_resume',
      });

      startElapsedTimer();
    }
  } else {
    stationaryCount++;
    lastMovingTimestamp = 0;

    // Auto-pause after consecutive stationary samples.
    // This only affects the timer display — GPS recording continues.
    if (stationaryCount >= AUTO_PAUSE_SAMPLES && !autoPauseActive) {
      autoPauseActive = true;
      pausedAtWallclock = Date.now();
      stopElapsedTimer();

      const pauseOffsetMs = sampleOffsetMsFromRideStart(
        sample.timestamp,
        rideStartWallclock,
        totalPausedMs,
      );
      const db = getDatabase();
      // Flush pending samples before pause event
      flushBuffer(rideId);
      insertPauseEvent(db, {
        ride_id: rideId,
        event_type: 'pause',
        t_offset_ms: pauseOffsetMs,
        reason: 'auto_pause',
      });

      // DO NOT return — keep recording the sample below
    }
  }

  lastLat = sample.latitude;
  lastLon = sample.longitude;
  lastAltitude = sample.altitude;

  // Snapshot latest sensor values. getLatest* returns null when no connected
  // source of that kind — we persist null so the backend knows the data is
  // missing rather than silently zeroed.
  const power = sensorRegistry.getLatestPower();
  const hr = sensorRegistry.getLatestHeartRate();
  const cadence = sensorRegistry.getLatestCadence();

  // Build sample row for SQLite
  const sampleRow: GPSSampleRow = {
    ride_id: rideId,
    t_offset_ms: tOffsetMs,
    latitude: sample.latitude,
    longitude: sample.longitude,
    altitude_m: sample.altitude,
    accuracy_m: sample.accuracy,
    vert_accuracy_m: sample.altitudeAccuracy,
    speed_mps: sample.speed,
    bearing_deg: sample.bearing,
    source: 'fused',
    power_w: power ? Math.round(power.power_w) : null,
    heart_rate_bpm: hr ? Math.round(hr.heart_rate_bpm) : null,
    cadence_rpm: cadence ? Math.round(cadence.cadence_rpm) : null,
  };

  sampleBuffer.push(sampleRow);
  store.incrementBuffer();

  // Update live stats in Zustand (skip display update during auto-pause,
  // but still record the sample)
  if (!autoPauseActive) {
    store.updateLiveStats({
      elapsedMs: tOffsetMs,
      distanceM: cumulativeDistanceM,
      elevationGainM: cumulativeElevationGainM,
      currentSpeedMps: speed,
      maxSpeedMps,
      sampleCount: store.sampleCount + 1,
      currentLocation: {
        latitude: sample.latitude,
        longitude: sample.longitude,
      },
      routePoint: {
        latitude: sample.latitude,
        longitude: sample.longitude,
      },
    });
  }

  // Flush buffer when full
  if (sampleBuffer.length >= BATCH_SIZE) {
    flushBuffer(rideId);
  }
}

function flushBuffer(rideId: string): void {
  if (sampleBuffer.length === 0) return;

  const store = useRecordingStore.getState();
  const currentElapsedMs = Math.round(Date.now() - rideStartWallclock - totalPausedMs);

  try {
    const db = getDatabase();
    flushSampleBatch(db, rideId, [...sampleBuffer], {
      durationMs: currentElapsedMs,
      distanceM: cumulativeDistanceM,
      elevationGainM: cumulativeElevationGainM,
      maxSpeedMps,
      movingTimeMs,
    });
  } catch (err) {
    console.error('[GPSRecording] Flush error:', err);
    // Keep buffer — will retry on next batch
    return;
  }

  sampleBuffer = [];
  store.resetBuffer();
}

// ---------------------------------------------------------------------------
// Elapsed time timer (updates UI every second)
// ---------------------------------------------------------------------------

function startElapsedTimer(): void {
  stopElapsedTimer();
  elapsedTimerInterval = setInterval(() => {
    const store = useRecordingStore.getState();
    if (store.status !== 'recording') return;
    const elapsed = Math.round(Date.now() - rideStartWallclock - totalPausedMs);
    store.updateLiveStats({ elapsedMs: elapsed });
  }, 1000);
}

function stopElapsedTimer(): void {
  if (elapsedTimerInterval) {
    clearInterval(elapsedTimerInterval);
    elapsedTimerInterval = null;
  }
}

/**
 * GPS watchdog — emits a Sentry breadcrumb when the GPS sample stream
 * stalls during recording. iOS may silently kill our background task under
 * memory pressure, leaving recording 'live' but producing no samples; this
 * is the empirical signal that catches it. Fires once per gap (resets when
 * samples flow again) so we don't spam Sentry through a long dropout.
 */
function startGpsWatchdog(rideId: string): void {
  stopGpsWatchdog();
  gpsWatchdogFiredForCurrentGap = false;
  gpsWatchdogInterval = setInterval(() => {
    const store = useRecordingStore.getState();
    if (store.status !== 'recording') return;
    if (lastAcceptedAtWallclock === 0) return; // pre-first-sample, not stale yet
    const gapMs = Date.now() - lastAcceptedAtWallclock;
    if (gapMs > GPS_STALE_GAP_MS) {
      if (!gpsWatchdogFiredForCurrentGap) {
        Sentry.captureMessage(
          'GPS watchdog: no accepted samples for ' + GPS_STALE_GAP_MS + 'ms+',
          { level: 'warning', extra: { rideId, gapMs } },
        );
        void restartBackgroundLocationUpdates(rideId, gapMs);
        gpsWatchdogFiredForCurrentGap = true;
      }
    } else {
      // Stream recovered — re-arm so the next dropout fires once
      gpsWatchdogFiredForCurrentGap = false;
    }
  }, GPS_WATCHDOG_INTERVAL_MS);
}

function stopGpsWatchdog(): void {
  if (gpsWatchdogInterval) {
    clearInterval(gpsWatchdogInterval);
    gpsWatchdogInterval = null;
  }
  gpsWatchdogFiredForCurrentGap = false;
}

async function hasLocationUpdatesStarted(): Promise<boolean> {
  try {
    return await Location.hasStartedLocationUpdatesAsync(BACKGROUND_LOCATION_TASK);
  } catch {
    // Older/native-mocked Expo surfaces may not expose the Location-specific
    // check. Fall back to TaskManager registration, which is less exact but
    // still better than assuming the task is stopped.
    return TaskManager.isTaskRegisteredAsync(BACKGROUND_LOCATION_TASK);
  }
}

async function startBackgroundLocationUpdates(): Promise<void> {
  await Location.startLocationUpdatesAsync(
    BACKGROUND_LOCATION_TASK,
    LOCATION_UPDATES_OPTIONS,
  );
}

async function restartBackgroundLocationUpdates(rideId: string, gapMs: number): Promise<void> {
  if (gpsRecoveryInFlight) return;
  gpsRecoveryInFlight = true;
  try {
    const wasStarted = await hasLocationUpdatesStarted();
    const store = useRecordingStore.getState();
    if (store.status !== 'recording' || store.rideId !== rideId) return;

    if (wasStarted) {
      try {
        await Location.stopLocationUpdatesAsync(BACKGROUND_LOCATION_TASK);
      } catch {
        // Best-effort restart: if stop fails because native state drifted,
        // still try start below.
      }
    }

    const currentStore = useRecordingStore.getState();
    if (currentStore.status !== 'recording' || currentStore.rideId !== rideId) return;

    await startBackgroundLocationUpdates();

    const db = getDatabase();
    recordRideValidationEvent(db, rideId, 'gps_watchdog_restarted', {
      gapMs,
      wasStarted,
    });
  } catch (err) {
    Sentry.captureException(err);
  } finally {
    gpsRecoveryInFlight = false;
  }
}

// ---------------------------------------------------------------------------
// Public API
// ---------------------------------------------------------------------------

/**
 * Request location permissions.
 * Returns true if foreground permission was granted.
 */
export type LocationPermissionBlocker =
  | 'services_disabled'
  | 'foreground_permission'
  | 'background_permission';

export interface LocationPermissionState {
  servicesEnabled: boolean;
  foreground: boolean;
  background: boolean;
  foregroundStatus: Location.PermissionStatus;
  backgroundStatus: Location.PermissionStatus;
  foregroundCanAskAgain: boolean;
  backgroundCanAskAgain: boolean;
}

interface LocationPermissionOptions {
  requestBackground?: boolean;
}

/**
 * Request/check location permissions.
 * Foreground permission may be requested immediately; background permission is
 * requested only when the caller is actively starting a ride.
 */
export async function requestLocationPermissions(
  options: LocationPermissionOptions = {},
): Promise<LocationPermissionState> {
  const servicesEnabled = await Location.hasServicesEnabledAsync();
  let fg = await Location.getForegroundPermissionsAsync();

  if (servicesEnabled && fg.status !== 'granted' && fg.canAskAgain !== false) {
    fg = await Location.requestForegroundPermissionsAsync();
  }

  let bg = await Location.getBackgroundPermissionsAsync();
  if (
    servicesEnabled &&
    options.requestBackground &&
    fg.status === 'granted' &&
    bg.status !== 'granted' &&
    bg.canAskAgain !== false
  ) {
    bg = await Location.requestBackgroundPermissionsAsync();
  }

  return {
    servicesEnabled,
    foreground: fg.status === 'granted',
    background: bg.status === 'granted',
    foregroundStatus: fg.status,
    backgroundStatus: bg.status,
    foregroundCanAskAgain: fg.canAskAgain !== false,
    backgroundCanAskAgain: bg.canAskAgain !== false,
  };
}

export function getLocationPermissionBlocker(
  permissions: LocationPermissionState,
  options: { requireBackground?: boolean } = {},
): LocationPermissionBlocker | null {
  if (!permissions.servicesEnabled) return 'services_disabled';
  if (!permissions.foreground) return 'foreground_permission';
  if (options.requireBackground && !permissions.background) return 'background_permission';
  return null;
}

/**
 * Start recording a ride.
 * Initializes GPS tracking via background location task only.
 * The background task works in BOTH foreground and background,
 * avoiding duplicate samples from dual subscriptions.
 */
export async function startRecording(rideId: string): Promise<void> {
  // Reset module state
  sampleBuffer = [];
  lastAcceptedSample = null;
  lastAcceptedAtWallclock = 0;
  rideStartWallclock = Date.now();
  totalPausedMs = 0;
  pausedAtWallclock = 0;
  autoPauseActive = false;
  gpsRecoveryInFlight = false;
  cumulativeDistanceM = 0;
  cumulativeElevationGainM = 0;
  maxSpeedMps = 0;
  movingTimeMs = 0;
  lastLat = null;
  lastLon = null;
  lastAltitude = null;
  lastMovingTimestamp = 0;
  stationaryCount = 0;

  // Use ONLY the background location task for GPS updates.
  // It fires in both foreground and background, preventing duplicate samples
  // that occurred when watchPositionAsync and startLocationUpdatesAsync
  // were both active simultaneously.
  const updatesStarted = await hasLocationUpdatesStarted();
  if (updatesStarted) {
    try {
      await Location.stopLocationUpdatesAsync(BACKGROUND_LOCATION_TASK);
    } catch {
      // The exact native state can drift after app suspension or a crash.
      // Starting below is the authoritative repair step.
    }
  }
  await startBackgroundLocationUpdates();

  // Start elapsed time timer for UI updates
  startElapsedTimer();
  // Start watchdog after we know rideId is fixed
  startGpsWatchdog(rideId);
}

/**
 * Pause recording (manual only). Stops accumulating time but GPS
 * continues recording for crash safety.
 *
 * Auto-pause is handled inside processLocationUpdate() and does NOT
 * call this function — it keeps GPS samples flowing while only
 * freezing the timer display.
 */
export function pauseRecording(reason: string = 'manual'): void {
  const store = useRecordingStore.getState();
  if (store.status !== 'recording') return;

  pausedAtWallclock = Date.now();
  stopElapsedTimer();
  // Clear auto-pause state if manually pausing
  autoPauseActive = false;

  const rideId = store.rideId;
  if (rideId) {
    // Flush any pending samples
    flushBuffer(rideId);

    // Record pause event
    const tOffsetMs = Math.round(Date.now() - rideStartWallclock - totalPausedMs);
    const db = getDatabase();
    insertPauseEvent(db, {
      ride_id: rideId,
      event_type: 'pause',
      t_offset_ms: tOffsetMs,
      reason,
    });
  }

  store.pauseRide();
}

/**
 * Resume recording after a manual pause.
 */
export function resumeRecording(): void {
  const store = useRecordingStore.getState();
  if (store.status !== 'paused') return;

  // Wall-to-wall: Date.now() minus pausedAtWallclock is same-domain.
  totalPausedMs += Date.now() - pausedAtWallclock;
  pausedAtWallclock = 0;
  stationaryCount = 0;
  autoPauseActive = false;

  const rideId = store.rideId;
  if (rideId) {
    // Wall-only: Date.now() minus rideStartWallclock minus totalPausedMs — all wall-clock.
    const tOffsetMs = Math.round(Date.now() - rideStartWallclock - totalPausedMs);
    const db = getDatabase();
    insertPauseEvent(db, {
      ride_id: rideId,
      event_type: 'resume',
      t_offset_ms: tOffsetMs,
      reason: 'manual',
    });
  }

  store.resumeRide();
  startElapsedTimer();
}

/**
 * Stop recording. Flushes buffer, finalizes ride row, stops GPS tracking.
 * Returns the ride ID for the post-ride flow.
 */
export async function stopRecording(): Promise<string | null> {
  const store = useRecordingStore.getState();
  if (store.status !== 'recording' && store.status !== 'paused') return null;

  const wasPaused = store.status === 'paused' || autoPauseActive;
  const rideId = store.rideId;
  store.stopRide();

  // Stop timers
  stopElapsedTimer();
  stopGpsWatchdog();
  autoPauseActive = false;
  gpsRecoveryInFlight = false;

  // Flush remaining samples
  if (rideId) {
    flushBuffer(rideId);

    // If stopped while paused, account for the current pause duration
    let finalPausedMs = totalPausedMs;
    if (wasPaused && pausedAtWallclock > 0) {
      finalPausedMs += Date.now() - pausedAtWallclock;
    }

    // Compute preliminary canonical hash + stamp parser version
    const { rideHash, parserVersion } = await computePreliminaryHash(rideId);

    // Finalize ride row in SQLite using wallclock for reliability
    const db = getDatabase();
    const finalElapsed = Math.round(Date.now() - rideStartWallclock - finalPausedMs);
    updateRide(db, rideId, {
      status: 'stopped',
      ended_at: Date.now(),
      duration_ms: Math.max(0, finalElapsed),
      moving_time_ms: movingTimeMs,
      distance_m: cumulativeDistanceM,
      elevation_gain_m: cumulativeElevationGainM,
      max_speed_mps: maxSpeedMps,
      rejected_samples: JSON.stringify(store.rejectedSamples),
      preliminary_ride_hash: rideHash,
      parser_version: parserVersion,
    });
    recordRideValidationEvent(db, rideId, 'recording_stopped', {
      parserVersion,
      parserVersionPresent: parserVersion != null,
      preliminaryRideHashPresent: rideHash != null,
      preliminaryRideHashHex: rideHashBytesToHex(rideHash),
      rejectedSamples: store.rejectedSamples,
      wasPaused,
      sampleCount: store.sampleCount,
      distanceM: cumulativeDistanceM,
      elevationGainM: cumulativeElevationGainM,
    });
  }

  // Stop location tracking (background task only — no foreground watcher)
  try {
    const updatesStarted = await hasLocationUpdatesStarted();
    if (updatesStarted) {
      await Location.stopLocationUpdatesAsync(BACKGROUND_LOCATION_TASK);
    }
  } catch {
    // Ignore errors stopping background task
  }

  return rideId;
}

/**
 * Discard the current recording. Deletes all data from SQLite.
 */
export async function discardRecording(): Promise<void> {
  const rideId = useRecordingStore.getState().rideId;

  // Stop GPS first
  stopElapsedTimer();
  stopGpsWatchdog();
  autoPauseActive = false;
  gpsRecoveryInFlight = false;

  try {
    const updatesStarted = await hasLocationUpdatesStarted();
    if (updatesStarted) {
      await Location.stopLocationUpdatesAsync(BACKGROUND_LOCATION_TASK);
    }
  } catch {
    // Ignore
  }

  // Delete ride data from SQLite
  if (rideId) {
    const db = getDatabase();
    deleteRide(db, rideId);
  }

  // Reset store
  sampleBuffer = [];
  useRecordingStore.getState().reset();
}

/**
 * Stop the live recorder at an authentication boundary without deleting the
 * owning rider's encrypted rows. Explicit logout calls this while the old
 * account is still authenticated, allowing its final in-memory samples to
 * flush under the correct owner. Unexpected expiry/account replacement may
 * call it after auth changed; owner-guarded database writes then no-op while
 * the reset still prevents any new account's coordinates reaching that ride.
 *
 * The row deliberately stays `recording`/`paused`: when its owner returns,
 * normal crash recovery offers Save & Upload or Discard instead of silently
 * losing an offline ride.
 */
export async function suspendRecordingForAccountBoundary(): Promise<void> {
  const store = useRecordingStore.getState();
  const rideId = store.rideId;
  const wasRecording = store.status === 'recording' || store.status === 'paused';

  stopElapsedTimer();
  stopGpsWatchdog();
  gpsRecoveryInFlight = false;

  if (rideId && wasRecording) {
    flushBuffer(rideId);
  }

  // Reset synchronously before awaiting native teardown. A late location task
  // delivery sees `idle` and is rejected even if stopLocationUpdates is slow.
  sampleBuffer = [];
  lastAcceptedSample = null;
  lastAcceptedAtWallclock = 0;
  rideStartWallclock = 0;
  pausedAtWallclock = 0;
  totalPausedMs = 0;
  autoPauseActive = false;
  cumulativeDistanceM = 0;
  cumulativeElevationGainM = 0;
  maxSpeedMps = 0;
  movingTimeMs = 0;
  lastLat = null;
  lastLon = null;
  lastAltitude = null;
  lastMovingTimestamp = 0;
  stationaryCount = 0;
  store.reset();

  try {
    const updatesStarted = await hasLocationUpdatesStarted();
    if (updatesStarted) {
      await Location.stopLocationUpdatesAsync(BACKGROUND_LOCATION_TASK);
    }
  } catch {
    // The synchronous idle reset remains the authority even if native task
    // state was already torn down or temporarily unavailable.
  }
}

/** Get the background task name (for testing). */
export const BACKGROUND_TASK_NAME = BACKGROUND_LOCATION_TASK;

/** Exported for testing. */
export { AUTO_RESUME_SPEED_MPS };
