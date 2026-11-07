import { sensorRegistry } from '../registry';
import { MockBleSource } from '../mock/mockBleSource';
import type { PowerSample, HeartRateSample, CadenceSample } from '../types';

describe('SensorRegistry', () => {
  beforeEach(() => {
    sensorRegistry._clear();
  });

  describe('add/remove/get', () => {
    test('registers and retrieves sources by deviceId', () => {
      const src = new MockBleSource<PowerSample>({
        kind: 'power',
        deviceId: 'stages-001',
        deviceName: 'Stages Left',
        samples: [],
        intervalMs: 1000,
      });
      sensorRegistry.add(src);
      expect(sensorRegistry.get('stages-001', 'power')).toBe(src);
      expect(sensorRegistry.all()).toHaveLength(1);
    });

    test('remove drops the source', () => {
      const src = new MockBleSource<PowerSample>({
        kind: 'power',
        deviceId: 'stages-001',
        deviceName: 'Stages Left',
        samples: [],
        intervalMs: 1000,
      });
      sensorRegistry.add(src);
      sensorRegistry.remove('stages-001', 'power');
      expect(sensorRegistry.get('stages-001', 'power')).toBeUndefined();
    });

    test('byKind filters by sensor kind', () => {
      sensorRegistry.add(
        new MockBleSource<PowerSample>({
          kind: 'power',
          deviceId: 'p1',
          deviceName: 'Power',
          samples: [],
          intervalMs: 1000,
        }),
      );
      sensorRegistry.add(
        new MockBleSource<HeartRateSample>({
          kind: 'heart_rate',
          deviceId: 'h1',
          deviceName: 'HRM',
          samples: [],
          intervalMs: 1000,
        }),
      );
      expect(sensorRegistry.byKind('power')).toHaveLength(1);
      expect(sensorRegistry.byKind('heart_rate')).toHaveLength(1);
      expect(sensorRegistry.byKind('cadence')).toHaveLength(0);
    });

    test('connected filters by status', async () => {
      const p = new MockBleSource<PowerSample>({
        kind: 'power',
        deviceId: 'p1',
        deviceName: 'Power',
        samples: [],
        intervalMs: 10_000,
      });
      const h = new MockBleSource<HeartRateSample>({
        kind: 'heart_rate',
        deviceId: 'h1',
        deviceName: 'HRM',
        samples: [],
        intervalMs: 10_000,
      });
      sensorRegistry.add(p);
      sensorRegistry.add(h);
      await p.start();
      expect(sensorRegistry.connected()).toHaveLength(1);
      expect(sensorRegistry.connected()[0].deviceId).toBe('p1');
      await p.stop();
    });
  });

  describe('getLatest*', () => {
    test('returns null when no sources registered', () => {
      expect(sensorRegistry.getLatestPower()).toBeNull();
      expect(sensorRegistry.getLatestHeartRate()).toBeNull();
      expect(sensorRegistry.getLatestCadence()).toBeNull();
    });

    test('getLatestPower returns the power source sample', () => {
      const sample: PowerSample = { power_w: 250, timestamp_ms: 1000 };
      const src = new MockBleSource<PowerSample>({
        kind: 'power',
        deviceId: 'p1',
        deviceName: 'Stages',
        samples: [sample],
        intervalMs: 1000,
      });
      sensorRegistry.add(src);
      src.advance();
      expect(sensorRegistry.getLatestPower()).toEqual(sample);
    });

    test('getLatestHeartRate returns the HR source sample', () => {
      const sample: HeartRateSample = {
        heart_rate_bpm: 152,
        rr_intervals_ms: [400, 398],
        timestamp_ms: 1000,
      };
      const src = new MockBleSource<HeartRateSample>({
        kind: 'heart_rate',
        deviceId: 'h1',
        deviceName: 'Garmin HRM',
        samples: [sample],
        intervalMs: 1000,
      });
      sensorRegistry.add(src);
      src.advance();
      expect(sensorRegistry.getLatestHeartRate()).toEqual(sample);
    });

    test('getLatestCadence prefers power source over dedicated CSC', () => {
      const powerWithCadence: PowerSample = {
        power_w: 220,
        cadence_rpm: 88,
        timestamp_ms: 1000,
      };
      const cscSample: CadenceSample = {
        cadence_rpm: 92, // different value; power source should win
        timestamp_ms: 1100,
      };
      const powerSrc = new MockBleSource<PowerSample>({
        kind: 'power',
        deviceId: 'p1',
        deviceName: 'Stages',
        samples: [powerWithCadence],
        intervalMs: 1000,
      });
      const cscSrc = new MockBleSource<CadenceSample>({
        kind: 'cadence',
        deviceId: 'c1',
        deviceName: 'Wahoo CSC',
        samples: [cscSample],
        intervalMs: 1000,
      });
      sensorRegistry.add(powerSrc);
      sensorRegistry.add(cscSrc);
      powerSrc.advance();
      cscSrc.advance();

      const cadence = sensorRegistry.getLatestCadence();
      expect(cadence?.cadence_rpm).toBe(88);
    });

    test('getLatestCadence falls back to CSC when power source has no cadence', () => {
      const powerNoCadence: PowerSample = { power_w: 250, timestamp_ms: 1000 };
      const cscSample: CadenceSample = { cadence_rpm: 92, timestamp_ms: 1100 };
      const powerSrc = new MockBleSource<PowerSample>({
        kind: 'power',
        deviceId: 'p1',
        deviceName: 'Quarq',
        samples: [powerNoCadence],
        intervalMs: 1000,
      });
      const cscSrc = new MockBleSource<CadenceSample>({
        kind: 'cadence',
        deviceId: 'c1',
        deviceName: 'Wahoo CSC',
        samples: [cscSample],
        intervalMs: 1000,
      });
      sensorRegistry.add(powerSrc);
      sensorRegistry.add(cscSrc);
      powerSrc.advance();
      cscSrc.advance();

      expect(sensorRegistry.getLatestCadence()?.cadence_rpm).toBe(92);
    });

    test('getLatestCadence returns null when nothing has fired', () => {
      const src = new MockBleSource<PowerSample>({
        kind: 'power',
        deviceId: 'p1',
        deviceName: 'Stages',
        samples: [{ power_w: 250, timestamp_ms: 1000 }],
        intervalMs: 1000,
      });
      sensorRegistry.add(src);
      // don't advance
      expect(sensorRegistry.getLatestCadence()).toBeNull();
    });
  });
});
