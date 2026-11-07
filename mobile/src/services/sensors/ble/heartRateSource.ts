/**
 * HeartRateSource — concrete SensorSource for Heart Rate Service (0x180D).
 *
 * Simpler than PowerMeterSource: one subscription to HR Measurement, no
 * control point, no derived values. RR intervals pass through for later
 * HRV analysis.
 */

import type { Device, Subscription } from 'react-native-ble-plx';

import type { SensorSource, SensorStatus, HeartRateSample } from '../types';
import { parseHeartRateMeasurement } from './parsers/heartRateMeasurement';
import {
  HEART_RATE_SERVICE,
  HR_MEASUREMENT_CHAR,
  base64ToUint8Array,
} from './manager';

/** HR straps typically notify at ~1 Hz, so a 3 s gap = 3 missed beats. */
const STALE_TTL_MS = 3_000;

export class HeartRateSource implements SensorSource<HeartRateSample> {
  readonly kind = 'heart_rate' as const;
  readonly deviceId: string;
  readonly deviceName: string;
  status: SensorStatus = 'connected';

  private device: Device;
  private sub: Subscription | null = null;
  private disconnectSub: Subscription | null = null;
  private latest: HeartRateSample | null = null;
  private lastReceivedAtMs = 0;

  constructor(device: Device) {
    this.device = device;
    this.deviceId = device.id;
    this.deviceName = device.name ?? device.localName ?? 'Heart Rate Strap';
  }

  async start(): Promise<void> {
    this.sub = this.device.monitorCharacteristicForService(
      HEART_RATE_SERVICE,
      HR_MEASUREMENT_CHAR,
      (error, char) => {
        if (error || !char?.value) return;
        try {
          const parsed = parseHeartRateMeasurement(base64ToUint8Array(char.value));
          this.latest = {
            heart_rate_bpm: parsed.heart_rate_bpm,
            sensor_contact: parsed.sensor_contact,
            energy_expended_kj: parsed.energy_expended_kj,
            rr_intervals_ms: parsed.rr_intervals_ms,
            timestamp_ms: Date.now(),
          };
          this.lastReceivedAtMs = Date.now();
        } catch (e) {
          console.warn('[HeartRateSource] Parse error:', e);
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
  }

  markLost(): void {
    this.latest = null;
    this.lastReceivedAtMs = 0;
    this.status = 'disconnected';
    this.sub?.remove();
    this.sub = null;
  }

  getLatest(): HeartRateSample | null {
    if (!this.latest) return null;
    if (Date.now() - this.lastReceivedAtMs > STALE_TTL_MS) return null;
    return this.latest;
  }

  isStale(): boolean {
    if (this.lastReceivedAtMs === 0) return false;
    return Date.now() - this.lastReceivedAtMs > STALE_TTL_MS;
  }
}
