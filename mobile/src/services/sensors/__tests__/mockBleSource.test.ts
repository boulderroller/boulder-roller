import { MockBleSource } from '../mock/mockBleSource';
import type { PowerSample } from '../types';

describe('MockBleSource', () => {
  const sample = (power_w: number, timestamp_ms: number): PowerSample => ({
    power_w,
    timestamp_ms,
  });

  describe('lifecycle', () => {
    test('starts disconnected', () => {
      const src = new MockBleSource<PowerSample>({
        kind: 'power',
        deviceId: 'test',
        deviceName: 'Test',
        samples: [],
        intervalMs: 1000,
      });
      expect(src.status).toBe('disconnected');
      expect(src.getLatest()).toBeNull();
    });

    test('start sets status to connected', async () => {
      const src = new MockBleSource<PowerSample>({
        kind: 'power',
        deviceId: 'test',
        deviceName: 'Test',
        samples: [sample(250, 1000)],
        intervalMs: 10_000, // long interval so timer doesn't fire in test
      });
      await src.start();
      expect(src.status).toBe('connected');
      await src.stop();
    });

    test('stop sets status to disconnected and clears timer', async () => {
      const src = new MockBleSource<PowerSample>({
        kind: 'power',
        deviceId: 'test',
        deviceName: 'Test',
        samples: [],
        intervalMs: 10_000,
      });
      await src.start();
      await src.stop();
      expect(src.status).toBe('disconnected');
    });
  });

  describe('advance (deterministic stepping)', () => {
    test('emits samples in order', () => {
      const src = new MockBleSource<PowerSample>({
        kind: 'power',
        deviceId: 'test',
        deviceName: 'Test',
        samples: [sample(200, 1000), sample(250, 2000), sample(300, 3000)],
        intervalMs: 1000,
      });
      expect(src.advance()?.power_w).toBe(200);
      expect(src.advance()?.power_w).toBe(250);
      expect(src.advance()?.power_w).toBe(300);
    });

    test('stops emitting when samples exhausted (loop=false)', () => {
      const src = new MockBleSource<PowerSample>({
        kind: 'power',
        deviceId: 'test',
        deviceName: 'Test',
        samples: [sample(200, 1000)],
        intervalMs: 1000,
        loop: false,
      });
      src.advance();
      const afterExhaust = src.advance();
      expect(afterExhaust?.power_w).toBe(200); // latest stays at final sample
    });

    test('loops when loop=true', () => {
      const src = new MockBleSource<PowerSample>({
        kind: 'power',
        deviceId: 'test',
        deviceName: 'Test',
        samples: [sample(200, 1000), sample(250, 2000)],
        intervalMs: 1000,
        loop: true,
      });
      expect(src.advance()?.power_w).toBe(200);
      expect(src.advance()?.power_w).toBe(250);
      expect(src.advance()?.power_w).toBe(200); // looped
      expect(src.advance()?.power_w).toBe(250);
    });
  });

  describe('sendCommand (control point mock)', () => {
    test('start_offset_compensation returns success with offset', async () => {
      const src = new MockBleSource<PowerSample>({
        kind: 'power',
        deviceId: 'test',
        deviceName: 'Test',
        samples: [],
        intervalMs: 1000,
      });
      const resp = await src.sendCommand({ type: 'start_offset_compensation' });
      expect(resp.success).toBe(true);
      expect(resp.resultCode).toBe(0x01);
    });

    test('logs commands for test inspection', async () => {
      const src = new MockBleSource<PowerSample>({
        kind: 'power',
        deviceId: 'test',
        deviceName: 'Test',
        samples: [],
        intervalMs: 1000,
      });
      await src.sendCommand({ type: 'start_offset_compensation' });
      await src.sendCommand({ type: 'request_sensor_location' });
      expect(src.commandLog).toHaveLength(2);
      expect(src.commandLog[0].type).toBe('start_offset_compensation');
      expect(src.commandLog[1].type).toBe('request_sensor_location');
    });
  });
});
