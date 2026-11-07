/**
 * CadenceSource — concrete SensorSource for Cycling Speed and Cadence (0x1816).
 *
 * Used for standalone CSC sensors (older Garmin GSC-10, cadence-only pods,
 * and some wheel-magnet hubs). Power meters typically expose cadence through
 * Power Measurement's crank revolution fields, so a dedicated CSC sensor is
 * only registered when no power source is providing cadence.
 *
 * Cadence and wheel-speed are derived from revolution deltas across two
 * successive packets (same uint16 wraparound handling as PowerMeterSource).
 */

import type { Device, Subscription } from 'react-native-ble-plx';

import type { SensorSource, SensorStatus, CadenceSample } from '../types';
import {
  parseCSCMeasurement,
  computeCadenceRpm,
  computeWheelSpeedMps,
} from './parsers/cscMeasurement';
import {
  CYCLING_SPEED_CADENCE_SERVICE,
  CSC_MEASUREMENT_CHAR,
  base64ToUint8Array,
} from './manager';

// Default road-tire wheel circumference (700x25c). Rider can override via
// pairingStore.setWheelCircumference when the known-device entry has a
// custom value (gravel, CX, MTB, TT bikes).
export const DEFAULT_WHEEL_CIRCUMFERENCE_M = 2.105;

/** CSC sensors vary (crank-event-driven vs periodic) — 5 s is safe without being sluggish. */
const STALE_TTL_MS = 5_000;

interface CSCRawState {
  crank_revolution_count?: number;
  last_crank_event_time_s?: number;
  wheel_revolution_count?: number;
  last_wheel_event_time_s?: number;
}

export class CadenceSource implements SensorSource<CadenceSample> {
  readonly kind = 'cadence' as const;
  readonly deviceId: string;
  readonly deviceName: string;
  status: SensorStatus = 'connected';

  private device: Device;
  private sub: Subscription | null = null;
  private disconnectSub: Subscription | null = null;
  private latest: CadenceSample | null = null;
  private lastReceivedAtMs = 0;
  private prev: CSCRawState | null = null;
  private wheelCircumferenceM = DEFAULT_WHEEL_CIRCUMFERENCE_M;

  constructor(device: Device) {
    this.device = device;
    this.deviceId = device.id;
    this.deviceName = device.name ?? device.localName ?? 'Cadence Sensor';
  }

  /**
   * Override the wheel circumference used for speed math. Orchestrator
   * (pairingStore) calls this with the known-device value at connect time.
   * Meters, typical range 2.0 (small road) to 2.3 (29er MTB).
   */
  setWheelCircumference(meters: number): void {
    this.wheelCircumferenceM = meters;
  }

  async start(): Promise<void> {
    this.sub = this.device.monitorCharacteristicForService(
      CYCLING_SPEED_CADENCE_SERVICE,
      CSC_MEASUREMENT_CHAR,
      (error, char) => {
        if (error || !char?.value) return;
        try {
          const parsed = parseCSCMeasurement(base64ToUint8Array(char.value));
          this.updateFromParsed(parsed);
        } catch (e) {
          console.warn('[CadenceSource] Parse error:', e);
        }
      },
    );
    this.disconnectSub = this.device.onDisconnected(() => {
      this.markLost();
    });
    this.status = 'connected';
  }

  async stop(): Promise<void> {
    this.markLost();
    this.disconnectSub?.remove();
    this.disconnectSub = null;
    this.prev = null;
  }

  markLost(): void {
    this.latest = null;
    this.lastReceivedAtMs = 0;
    this.status = 'disconnected';
    this.sub?.remove();
    this.sub = null;
  }

  getLatest(): CadenceSample | null {
    if (!this.latest) return null;
    if (Date.now() - this.lastReceivedAtMs > STALE_TTL_MS) return null;
    return this.latest;
  }

  isStale(): boolean {
    if (this.lastReceivedAtMs === 0) return false;
    return Date.now() - this.lastReceivedAtMs > STALE_TTL_MS;
  }

  private updateFromParsed(parsed: CSCRawState): void {
    let cadence_rpm: number | null = null;
    let wheel_speed_mps: number | undefined;

    if (this.prev) {
      if (
        parsed.crank_revolution_count != null &&
        parsed.last_crank_event_time_s != null &&
        this.prev.crank_revolution_count != null &&
        this.prev.last_crank_event_time_s != null
      ) {
        cadence_rpm = computeCadenceRpm(
          {
            crank_revolution_count: this.prev.crank_revolution_count,
            last_crank_event_time_s: this.prev.last_crank_event_time_s,
          },
          {
            crank_revolution_count: parsed.crank_revolution_count,
            last_crank_event_time_s: parsed.last_crank_event_time_s,
          },
        );
      }
      if (
        parsed.wheel_revolution_count != null &&
        parsed.last_wheel_event_time_s != null &&
        this.prev.wheel_revolution_count != null &&
        this.prev.last_wheel_event_time_s != null
      ) {
        const speed = computeWheelSpeedMps(
          {
            wheel_revolution_count: this.prev.wheel_revolution_count,
            last_wheel_event_time_s: this.prev.last_wheel_event_time_s,
          },
          {
            wheel_revolution_count: parsed.wheel_revolution_count,
            last_wheel_event_time_s: parsed.last_wheel_event_time_s,
          },
          this.wheelCircumferenceM,
        );
        if (speed != null) wheel_speed_mps = speed;
      }
    }

    this.prev = { ...parsed };

    if (cadence_rpm != null) {
      this.latest = {
        cadence_rpm,
        wheel_speed_mps,
        timestamp_ms: Date.now(),
      };
      this.lastReceivedAtMs = Date.now();
    }
  }
}
