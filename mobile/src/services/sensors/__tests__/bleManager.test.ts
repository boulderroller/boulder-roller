// Minimal react-native mock scoped to this file. Only Platform and
// PermissionsAndroid are touched by bleSensorManager; other tests get the
// jest-expo default. Platform is mutable per-test via Object.defineProperty.
jest.mock('react-native', () => ({
  Platform: {
    OS: 'ios',
    Version: 17,
    select: (obj: Record<string, unknown>) => obj.ios ?? obj.default,
  },
  PermissionsAndroid: {
    PERMISSIONS: {
      BLUETOOTH_SCAN: 'android.permission.BLUETOOTH_SCAN',
      BLUETOOTH_CONNECT: 'android.permission.BLUETOOTH_CONNECT',
    },
    RESULTS: {
      GRANTED: 'granted',
      DENIED: 'denied',
      NEVER_ASK_AGAIN: 'never_ask_again',
    },
    requestMultiple: jest.fn().mockResolvedValue({
      'android.permission.BLUETOOTH_SCAN': 'granted',
      'android.permission.BLUETOOTH_CONNECT': 'granted',
    }),
  },
}));

import { BleManager } from 'react-native-ble-plx';
import { PermissionsAndroid, Platform } from 'react-native';
import * as Sentry from '@sentry/react-native';
import {
  bleSensorManager,
  base64ToUint8Array,
  uint8ArrayToBase64,
  CYCLING_POWER_SERVICE,
  HEART_RATE_SERVICE,
  CYCLING_SPEED_CADENCE_SERVICE,
} from '../ble/manager';
import { PowerMeterSource } from '../ble/powerMeterSource';
import { HeartRateSource } from '../ble/heartRateSource';
import { CadenceSource } from '../ble/cadenceSource';
import { sensorRegistry } from '../registry';

const MockedBleManager = BleManager as jest.MockedClass<typeof BleManager>;

/**
 * Retrieve the object returned by the most recent `new BleManager()` call.
 * We use `mock.results` (return values) rather than `mock.instances` because
 * our factory's mockImplementation returns a plain object — JS `new` replaces
 * `this` with that object for the caller, but `mock.instances` may still
 * record the original `this` rather than the replacement.
 */
function latestInstance() {
  const results = MockedBleManager.mock.results;
  const latest = results[results.length - 1];
  if (!latest || latest.type !== 'return') {
    throw new Error('No BleManager instance yet');
  }
  return latest.value as unknown as {
    state: jest.Mock;
    onStateChange: jest.Mock;
    startDeviceScan: jest.Mock;
    stopDeviceScan: jest.Mock;
    connectToDevice: jest.Mock;
    cancelDeviceConnection: jest.Mock;
    destroy: jest.Mock;
  };
}

describe('BleSensorManager', () => {
  beforeEach(() => {
    bleSensorManager._resetForTests();
    MockedBleManager.mockClear();
  });

  describe('init', () => {
    test('constructs BleManager once on first use', () => {
      bleSensorManager.init();
      bleSensorManager.init();
      expect(MockedBleManager).toHaveBeenCalledTimes(1);
    });
  });

  describe('startScan', () => {
    test('filters on our three service UUIDs', async () => {
      const onDiscovered = jest.fn();
      await bleSensorManager.startScan(onDiscovered);
      const instance = latestInstance();
      expect(instance.startDeviceScan).toHaveBeenCalledWith(
        [CYCLING_POWER_SERVICE, HEART_RATE_SERVICE, CYCLING_SPEED_CADENCE_SERVICE],
        null,
        expect.any(Function),
      );
    });

    test('emits kinds derived from advertised services', async () => {
      const onDiscovered = jest.fn();
      await bleSensorManager.startScan(onDiscovered);
      const instance = latestInstance();
      const scanCallback = instance.startDeviceScan.mock.calls[0][2] as (
        err: unknown,
        dev: unknown,
      ) => void;

      scanCallback(null, {
        id: 'aa:bb:cc',
        name: 'Stages LR',
        rssi: -62,
        serviceUUIDs: [CYCLING_POWER_SERVICE.toUpperCase()],
      });

      expect(onDiscovered).toHaveBeenCalledWith(
        expect.objectContaining({
          id: 'aa:bb:cc',
          name: 'Stages LR',
          rssi: -62,
          kinds: ['power'],
        }),
      );
    });

    test('ignores devices with none of our services', async () => {
      const onDiscovered = jest.fn();
      await bleSensorManager.startScan(onDiscovered);
      const scanCallback = latestInstance().startDeviceScan.mock.calls[0][2] as (
        err: unknown,
        dev: unknown,
      ) => void;

      scanCallback(null, {
        id: 'random',
        name: 'Smart Lightbulb',
        rssi: -80,
        serviceUUIDs: ['0000aaaa-0000-1000-8000-00805f9b34fb'],
      });

      expect(onDiscovered).not.toHaveBeenCalled();
    });

    test('propagates scan errors through onError callback', async () => {
      const onDiscovered = jest.fn();
      const onError = jest.fn();
      await bleSensorManager.startScan(onDiscovered, onError);
      const scanCallback = latestInstance().startDeviceScan.mock.calls[0][2] as (
        err: unknown,
        dev: unknown,
      ) => void;

      scanCallback({ message: 'Bluetooth off' }, null);

      expect(onError).toHaveBeenCalledWith(expect.any(Error));
      expect(onDiscovered).not.toHaveBeenCalled();
    });

    test('second startScan is a no-op while already active', async () => {
      await bleSensorManager.startScan(jest.fn());
      await bleSensorManager.startScan(jest.fn());
      expect(latestInstance().startDeviceScan).toHaveBeenCalledTimes(1);
    });
  });

  describe('stopScan', () => {
    test('stops an active scan', async () => {
      await bleSensorManager.startScan(jest.fn());
      bleSensorManager.stopScan();
      expect(latestInstance().stopDeviceScan).toHaveBeenCalledTimes(1);
    });

    test('no-op when not scanning', () => {
      bleSensorManager.init();
      bleSensorManager.stopScan();
      expect(latestInstance().stopDeviceScan).not.toHaveBeenCalled();
    });
  });

  describe('connect', () => {
    function mockDevice(id = 'device-1') {
      return {
        id,
        name: 'Stages LR',
        localName: null,
        monitorCharacteristicForService: jest.fn(() => ({ remove: jest.fn() })),
        writeCharacteristicWithResponseForService: jest.fn().mockResolvedValue({}),
        discoverAllServicesAndCharacteristics: jest.fn().mockResolvedValue({}),
        onDisconnected: jest.fn(() => ({ remove: jest.fn() })),
      };
    }

    test('returns PowerMeterSource for kind=power', async () => {
      bleSensorManager.init();
      const device = mockDevice();
      (latestInstance().connectToDevice as jest.Mock).mockResolvedValue(
        Object.assign(device, {
          discoverAllServicesAndCharacteristics: jest.fn().mockResolvedValue(device),
        }),
      );
      const source = await bleSensorManager.connect('device-1', 'power');
      expect(source).toBeInstanceOf(PowerMeterSource);
    });

    test('passes a timeout option to connectToDevice', async () => {
      bleSensorManager.init();
      const device = mockDevice();
      const connectMock = latestInstance().connectToDevice as jest.Mock;
      connectMock.mockResolvedValue(
        Object.assign(device, {
          discoverAllServicesAndCharacteristics: jest.fn().mockResolvedValue(device),
        }),
      );
      await bleSensorManager.connect('device-1', 'power');
      // Second arg should include a timeout — we don't pin the exact ms
      // value here so the test doesn't churn if we tune the default.
      expect(connectMock).toHaveBeenCalledWith(
        'device-1',
        expect.objectContaining({ timeout: expect.any(Number) }),
      );
    });

    test('returns HeartRateSource for kind=heart_rate', async () => {
      bleSensorManager.init();
      const device = mockDevice();
      (latestInstance().connectToDevice as jest.Mock).mockResolvedValue(
        Object.assign(device, {
          discoverAllServicesAndCharacteristics: jest.fn().mockResolvedValue(device),
        }),
      );
      const source = await bleSensorManager.connect('device-1', 'heart_rate');
      expect(source).toBeInstanceOf(HeartRateSource);
    });

    test('returns CadenceSource for kind=cadence', async () => {
      bleSensorManager.init();
      const device = mockDevice();
      (latestInstance().connectToDevice as jest.Mock).mockResolvedValue(
        Object.assign(device, {
          discoverAllServicesAndCharacteristics: jest.fn().mockResolvedValue(device),
        }),
      );
      const source = await bleSensorManager.connect('device-1', 'cadence');
      expect(source).toBeInstanceOf(CadenceSource);
    });
  });

  describe('disconnect', () => {
    test('cancels connection', async () => {
      bleSensorManager.init();
      await bleSensorManager.disconnect('device-1');
      expect(latestInstance().cancelDeviceConnection).toHaveBeenCalledWith('device-1');
    });

    test('silently swallows already-disconnected error', async () => {
      bleSensorManager.init();
      (latestInstance().cancelDeviceConnection as jest.Mock).mockRejectedValueOnce(
        new Error('Device not connected'),
      );
      await expect(bleSensorManager.disconnect('device-1')).resolves.toBeUndefined();
    });
  });

  describe('destroy', () => {
    test('stops scan and destroys manager', async () => {
      await bleSensorManager.startScan(jest.fn());
      const instance = latestInstance();
      bleSensorManager.destroy();
      expect(instance.stopDeviceScan).toHaveBeenCalled();
      expect(instance.destroy).toHaveBeenCalled();
    });
  });

  describe('auditStaleness', () => {
    test('marks connected-but-stale sources as lost; leaves fresh ones alone', () => {
      bleSensorManager.init();

      const stale = {
        kind: 'power',
        deviceId: 'p1',
        deviceName: 'P1',
        status: 'connected',
        start: jest.fn(),
        stop: jest.fn(),
        getLatest: jest.fn().mockReturnValue(null),
        markLost: jest.fn(),
        isStale: jest.fn().mockReturnValue(true),
      };
      const fresh = {
        kind: 'heart_rate',
        deviceId: 'h1',
        deviceName: 'H1',
        status: 'connected',
        start: jest.fn(),
        stop: jest.fn(),
        getLatest: jest.fn().mockReturnValue({ heart_rate_bpm: 150 }),
        markLost: jest.fn(),
        isStale: jest.fn().mockReturnValue(false),
      };
      sensorRegistry.add(stale as never);
      sensorRegistry.add(fresh as never);

      bleSensorManager.auditStaleness();

      expect(stale.markLost).toHaveBeenCalled();
      expect(fresh.markLost).not.toHaveBeenCalled();

      sensorRegistry._clear();
    });

    test('emits a Sentry breadcrumb when audit actually marks sources lost', async () => {
      bleSensorManager.init();
      (Sentry.captureMessage as jest.Mock).mockClear();

      const stale = {
        kind: 'power',
        deviceId: 'p1',
        deviceName: 'P1',
        status: 'connected',
        start: jest.fn(),
        stop: jest.fn(),
        getLatest: jest.fn(),
        markLost: jest.fn(),
        isStale: jest.fn().mockReturnValue(true),
      };
      sensorRegistry.add(stale as never);

      bleSensorManager.auditStaleness();

      expect(Sentry.captureMessage).toHaveBeenCalledWith(
        'BLE staleness audit marked sources lost',
        expect.objectContaining({
          level: 'info',
          extra: expect.objectContaining({
            lost: ['p1|power'],
          }),
        }),
      );
      sensorRegistry._clear();
    });

    test('does not emit Sentry breadcrumb when no sources were marked', async () => {
      bleSensorManager.init();
      (Sentry.captureMessage as jest.Mock).mockClear();

      const fresh = {
        kind: 'power',
        deviceId: 'p1',
        deviceName: 'P1',
        status: 'connected',
        start: jest.fn(),
        stop: jest.fn(),
        getLatest: jest.fn(),
        markLost: jest.fn(),
        isStale: jest.fn().mockReturnValue(false),
      };
      sensorRegistry.add(fresh as never);

      bleSensorManager.auditStaleness();

      expect(Sentry.captureMessage).not.toHaveBeenCalled();
      sensorRegistry._clear();
    });

    test('skips sources whose status is not connected', () => {
      bleSensorManager.init();
      const errored = {
        kind: 'power',
        deviceId: 'p1',
        deviceName: 'P1',
        status: 'error',
        start: jest.fn(),
        stop: jest.fn(),
        getLatest: jest.fn(),
        markLost: jest.fn(),
        isStale: jest.fn().mockReturnValue(true),
      };
      sensorRegistry.add(errored as never);

      bleSensorManager.auditStaleness();

      expect(errored.markLost).not.toHaveBeenCalled();
      expect(errored.isStale).not.toHaveBeenCalled();

      sensorRegistry._clear();
    });
  });

  describe('Android 12+ runtime permissions', () => {
    let originalOS: string;
    let originalVersion: number | string;

    beforeEach(() => {
      originalOS = Platform.OS;
      originalVersion = Platform.Version;
      (PermissionsAndroid.requestMultiple as jest.Mock).mockClear();
    });

    afterEach(() => {
      Object.defineProperty(Platform, 'OS', { value: originalOS, configurable: true });
      Object.defineProperty(Platform, 'Version', { value: originalVersion, configurable: true });
    });

    test('skips perm request on iOS', async () => {
      Object.defineProperty(Platform, 'OS', { value: 'ios', configurable: true });
      await bleSensorManager.startScan(jest.fn());
      expect(PermissionsAndroid.requestMultiple).not.toHaveBeenCalled();
    });

    test('skips perm request on Android < 12 (API 30)', async () => {
      Object.defineProperty(Platform, 'OS', { value: 'android', configurable: true });
      Object.defineProperty(Platform, 'Version', { value: 30, configurable: true });
      await bleSensorManager.startScan(jest.fn());
      expect(PermissionsAndroid.requestMultiple).not.toHaveBeenCalled();
    });

    test('requests both BT perms on Android 12+ (API 33)', async () => {
      Object.defineProperty(Platform, 'OS', { value: 'android', configurable: true });
      Object.defineProperty(Platform, 'Version', { value: 33, configurable: true });
      await bleSensorManager.startScan(jest.fn());
      expect(PermissionsAndroid.requestMultiple).toHaveBeenCalledWith([
        PermissionsAndroid.PERMISSIONS.BLUETOOTH_SCAN,
        PermissionsAndroid.PERMISSIONS.BLUETOOTH_CONNECT,
      ]);
    });

    test('startScan calls onError and skips startDeviceScan when perms denied', async () => {
      Object.defineProperty(Platform, 'OS', { value: 'android', configurable: true });
      Object.defineProperty(Platform, 'Version', { value: 33, configurable: true });
      (PermissionsAndroid.requestMultiple as jest.Mock).mockResolvedValueOnce({
        [PermissionsAndroid.PERMISSIONS.BLUETOOTH_SCAN]:
          PermissionsAndroid.RESULTS.DENIED,
        [PermissionsAndroid.PERMISSIONS.BLUETOOTH_CONNECT]:
          PermissionsAndroid.RESULTS.DENIED,
      });

      const onError = jest.fn();
      await bleSensorManager.startScan(jest.fn(), onError);

      expect(onError).toHaveBeenCalledWith(expect.any(Error));
      expect(onError.mock.calls[0][0].message).toMatch(/permission denied/i);
      // startDeviceScan should NOT have been reached
      const instance = latestInstance();
      expect(instance.startDeviceScan).not.toHaveBeenCalled();
    });

    test('connect throws when perms denied', async () => {
      Object.defineProperty(Platform, 'OS', { value: 'android', configurable: true });
      Object.defineProperty(Platform, 'Version', { value: 33, configurable: true });
      (PermissionsAndroid.requestMultiple as jest.Mock).mockResolvedValueOnce({
        [PermissionsAndroid.PERMISSIONS.BLUETOOTH_SCAN]:
          PermissionsAndroid.RESULTS.DENIED,
        [PermissionsAndroid.PERMISSIONS.BLUETOOTH_CONNECT]:
          PermissionsAndroid.RESULTS.DENIED,
      });

      await expect(bleSensorManager.connect('device-1', 'power')).rejects.toThrow(
        /permission denied/i,
      );
    });

    test('connect proceeds when only one perm granted (treated as denied)', async () => {
      Object.defineProperty(Platform, 'OS', { value: 'android', configurable: true });
      Object.defineProperty(Platform, 'Version', { value: 33, configurable: true });
      (PermissionsAndroid.requestMultiple as jest.Mock).mockResolvedValueOnce({
        [PermissionsAndroid.PERMISSIONS.BLUETOOTH_SCAN]:
          PermissionsAndroid.RESULTS.GRANTED,
        [PermissionsAndroid.PERMISSIONS.BLUETOOTH_CONNECT]:
          PermissionsAndroid.RESULTS.DENIED,
      });

      await expect(bleSensorManager.connect('device-1', 'power')).rejects.toThrow(
        /permission denied/i,
      );
    });
  });

  describe('adapter state monitor', () => {
    test('init subscribes to onStateChange without emitting current state', () => {
      bleSensorManager.init();
      const instance = latestInstance();
      expect(instance.onStateChange).toHaveBeenCalledTimes(1);
      // Second arg is `emitCurrentState` — we only care about transitions.
      expect(instance.onStateChange.mock.calls[0][1]).toBe(false);
    });

    test('marks all registered sources as lost when adapter goes non-PoweredOn', async () => {
      bleSensorManager.init();
      const instance = latestInstance();
      const stateCallback = instance.onStateChange.mock.calls[0][0] as (
        state: string,
      ) => void;

      // Register two fake sources
      const markLost1 = jest.fn();
      const markLost2 = jest.fn();
      sensorRegistry.add({
        kind: 'power',
        deviceId: 'p1',
        deviceName: 'P1',
        status: 'connected',
        start: jest.fn(),
        stop: jest.fn(),
        getLatest: jest.fn().mockReturnValue(null),
        markLost: markLost1,
      } as never);
      sensorRegistry.add({
        kind: 'heart_rate',
        deviceId: 'h1',
        deviceName: 'H1',
        status: 'connected',
        start: jest.fn(),
        stop: jest.fn(),
        getLatest: jest.fn().mockReturnValue(null),
        markLost: markLost2,
      } as never);

      // Fire the adapter-state change callback with a non-PoweredOn state
      stateCallback('PoweredOff');

      expect(markLost1).toHaveBeenCalled();
      expect(markLost2).toHaveBeenCalled();

      // PoweredOn (recovery) should NOT re-trigger markLost
      markLost1.mockClear();
      markLost2.mockClear();
      stateCallback('PoweredOn');
      expect(markLost1).not.toHaveBeenCalled();
      expect(markLost2).not.toHaveBeenCalled();

      sensorRegistry._clear();
    });
  });
});

describe('base64 helpers', () => {
  test('round-trips bytes', () => {
    const bytes = new Uint8Array([0x00, 0xff, 0x42, 0x80, 0x01]);
    const b64 = uint8ArrayToBase64(bytes);
    const back = base64ToUint8Array(b64);
    expect(Array.from(back)).toEqual(Array.from(bytes));
  });
});
