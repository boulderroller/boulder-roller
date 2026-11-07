/**
 * SensorRegistry — singleton of active SensorSource instances.
 *
 * Queried by the recording surface on every GPS tick to snapshot latest
 * values into the wide sample row. Reactivity (status change events) is
 * handled by a Zustand pairing store — not this registry.
 */

import type {
  SensorSource,
  SensorKind,
  SensorSample,
  PowerSample,
  HeartRateSample,
  CadenceSample,
} from './types';

class SensorRegistry {
  private sources = new Map<string, SensorSource<SensorSample>>();

  private key(deviceId: string, kind: SensorKind): string {
    return `${deviceId}|${kind}`;
  }

  add(source: SensorSource<SensorSample>): void {
    this.sources.set(this.key(source.deviceId, source.kind), source);
  }

  remove(deviceId: string, kind: SensorKind): void {
    this.sources.delete(this.key(deviceId, kind));
  }

  get(deviceId: string, kind: SensorKind): SensorSource<SensorSample> | undefined {
    return this.sources.get(this.key(deviceId, kind));
  }

  all(): SensorSource<SensorSample>[] {
    return Array.from(this.sources.values());
  }

  byKind(kind: SensorKind): SensorSource<SensorSample>[] {
    return this.all().filter((s) => s.kind === kind);
  }

  connected(): SensorSource<SensorSample>[] {
    return this.all().filter((s) => s.status === 'connected');
  }

  /**
   * First non-null power sample from any connected power source.
   * Multiple power meters at once is rare but tolerated (first wins).
   */
  getLatestPower(): PowerSample | null {
    for (const s of this.byKind('power')) {
      const sample = s.getLatest() as PowerSample | null;
      if (sample) return sample;
    }
    return null;
  }

  getLatestHeartRate(): HeartRateSample | null {
    for (const s of this.byKind('heart_rate')) {
      const sample = s.getLatest() as HeartRateSample | null;
      if (sample) return sample;
    }
    return null;
  }

  /**
   * Power meters often expose cadence via Power Measurement (crank rev data).
   * Prefer that over a dedicated CSC sensor so we don't double-count sources.
   */
  getLatestCadence(): CadenceSample | null {
    for (const s of this.byKind('power')) {
      const sample = s.getLatest() as PowerSample | null;
      if (sample?.cadence_rpm !== undefined) {
        return {
          cadence_rpm: sample.cadence_rpm,
          timestamp_ms: sample.timestamp_ms,
        };
      }
    }
    for (const s of this.byKind('cadence')) {
      const sample = s.getLatest() as CadenceSample | null;
      if (sample) return sample;
    }
    return null;
  }

  /** Test-only: drop all registered sources. */
  _clear(): void {
    this.sources.clear();
  }
}

export const sensorRegistry = new SensorRegistry();
