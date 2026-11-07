/**
 * SensorSource abstraction — GPS and each BLE service implement this.
 *
 * The recording surface queries `SensorRegistry.getLatest*()` on every
 * GPS sample tick and snapshots values into the wide sample row written
 * to SQLite. Each source maintains its own latest-value cache.
 */

export type SensorStatus =
  | 'disconnected'
  | 'scanning'
  | 'connecting'
  | 'connected'
  | 'error';

export type SensorKind = 'power' | 'heart_rate' | 'cadence';

export interface PowerSample {
  /** Instantaneous power in watts (int16, signed per CPS spec). */
  power_w: number;
  /** Left-pedal balance as a percentage (0-100), when supported. */
  pedal_balance_pct?: number;
  /** Cadence in RPM — some power meters expose this via Power Measurement. */
  cadence_rpm?: number;
  /** Accumulated energy in kilojoules, when supported. */
  accumulated_energy_kj?: number;
  /** Wallclock ms when the parser produced this sample. */
  timestamp_ms: number;
}

export interface HeartRateSample {
  heart_rate_bpm: number;
  /** RR intervals in ms — older-first order per HRM spec. HRV input. */
  rr_intervals_ms?: number[];
  /** Sensor contact status: true if the strap reports good contact. */
  sensor_contact?: boolean;
  /** Accumulated energy expended in kilojoules, when supported. */
  energy_expended_kj?: number;
  timestamp_ms: number;
}

export interface CadenceSample {
  cadence_rpm: number;
  /** Wheel-based speed in m/s — present when a CSC sensor exposes wheel data. */
  wheel_speed_mps?: number;
  timestamp_ms: number;
}

export type SensorSample = PowerSample | HeartRateSample | CadenceSample;

export type SensorCommand =
  | { type: 'start_offset_compensation' }
  | { type: 'request_sensor_location' }
  | { type: 'start_enhanced_offset_compensation' };

export interface SensorCommandResponse {
  success: boolean;
  /** Raw result code from the Response Code op (0x01 = success). */
  resultCode?: number;
  /** Parameter data from the response (e.g., offset int16, sensor location enum). */
  data?: unknown;
  error?: string;
}

export interface SensorSource<T extends SensorSample> {
  readonly kind: SensorKind;
  readonly deviceId: string;
  readonly deviceName: string;
  readonly status: SensorStatus;

  start(): Promise<void>;
  stop(): Promise<void>;
  /**
   * Return the freshest sample, or null if none has arrived or the most
   * recent one is older than the source's staleness TTL. Callers (the
   * snapshot-on-tick merge in processLocationUpdate) rely on this contract
   * to avoid writing phantom values from a dead sensor.
   */
  getLatest(): T | null;

  /**
   * Drop any cached sample and flip status to 'disconnected'. Invoked when
   * the underlying BLE reality breaks: device disconnect event from ble-plx,
   * adapter state change to non-PoweredOn, or an error we cannot recover
   * from. Subscriptions are cleaned up here too; caller does not need to
   * follow up with stop(). Idempotent.
   */
  markLost(): void;

  /**
   * True when the source has received at least one sample but the most
   * recent one is older than its staleness TTL. False when no samples have
   * arrived yet (still connecting / freshly subscribed) — that case is
   * "no data" rather than "lost data".
   */
  isStale(): boolean;

  /** Optional: sources that expose a Control Point (e.g., Power CP) implement this. */
  sendCommand?(cmd: SensorCommand): Promise<SensorCommandResponse>;
}
