/**
 * Pairing store tests — drive through the BLE manager mock defined in
 * jest.setup.ts. The store orchestrates scan/connect/disconnect and
 * pumps state into sensorRegistry.
 */

import * as Sentry from '@sentry/react-native';

import {
  usePairingStore,
  selectHasConnectedSensors,
  selectConnectedKinds,
  selectConnectedCount,
} from '../pairingStore';
import { bleSensorManager } from '../../services/sensors/ble/manager';
import { sensorRegistry } from '../../services/sensors/registry';
import type { DiscoveredDevice } from '../../services/sensors/ble/manager';
import type { PowerSample } from '../../services/sensors/types';

// Minimal stub SensorSource that records start/stop without any BLE side-effects.
function makeStubSource(kind: 'power' | 'heart_rate' | 'cadence', deviceId: string, name = 'Stub') {
  return {
    kind,
    deviceId,
    deviceName: name,
    status: 'connected' as const,
    start: jest.fn().mockResolvedValue(undefined),
    stop: jest.fn().mockResolvedValue(undefined),
    getLatest: jest.fn().mockReturnValue(null),
    sendCommand: jest.fn().mockResolvedValue({ success: true, resultCode: 0x01, data: { offset: 10 } }),
  };
}

describe('pairingStore', () => {
  beforeEach(() => {
    // Wipe runtime state between tests; `known` persists across sessions
    // intentionally, so reset it explicitly here.
    usePairingStore.setState({
      discovered: {},
      known: [],
      connections: {},
      scanning: false,
      scanError: null,
    });
    sensorRegistry._clear();
    jest.restoreAllMocks();
  });

  describe('scan lifecycle', () => {
    test('startScan flips scanning=true and clears prior discovered', async () => {
      jest.spyOn(bleSensorManager, 'startScan').mockImplementation(async () => {});
      usePairingStore.setState({ discovered: { stale: { id: 'stale' } as DiscoveredDevice } });

      await usePairingStore.getState().startScan();

      expect(usePairingStore.getState().scanning).toBe(true);
      expect(usePairingStore.getState().discovered).toEqual({});
    });

    test('onDiscovered callback populates discovered', async () => {
      let capturedOnDiscovered: ((d: DiscoveredDevice) => void) | null = null;
      jest.spyOn(bleSensorManager, 'startScan').mockImplementation(async (onDiscovered) => {
        capturedOnDiscovered = onDiscovered;
      });

      await usePairingStore.getState().startScan();
      capturedOnDiscovered!({
        id: 'stages-001',
        name: 'Stages LR',
        rssi: -62,
        advertisedServiceUuids: [],
        kinds: ['power'],
      });

      expect(usePairingStore.getState().discovered['stages-001']).toBeDefined();
      expect(usePairingStore.getState().discovered['stages-001'].name).toBe('Stages LR');
    });

    test('scan error populates scanError', async () => {
      let capturedOnError: ((e: Error) => void) | null = null;
      jest.spyOn(bleSensorManager, 'startScan').mockImplementation(async (_ok, onError) => {
        capturedOnError = onError ?? null;
      });

      await usePairingStore.getState().startScan();
      capturedOnError!(new Error('Bluetooth off'));

      expect(usePairingStore.getState().scanError).toBe('Bluetooth off');
      expect(usePairingStore.getState().scanning).toBe(false);
    });

    test('stopScan clears scanning flag', async () => {
      jest.spyOn(bleSensorManager, 'startScan').mockImplementation(async () => {});
      jest.spyOn(bleSensorManager, 'stopScan').mockImplementation(() => {});
      await usePairingStore.getState().startScan();

      usePairingStore.getState().stopScan();
      expect(usePairingStore.getState().scanning).toBe(false);
    });

    test('double startScan is a no-op (already scanning)', async () => {
      const spy = jest.spyOn(bleSensorManager, 'startScan').mockImplementation(async () => {});
      await usePairingStore.getState().startScan();
      await usePairingStore.getState().startScan();
      expect(spy).toHaveBeenCalledTimes(1);
    });
  });

  describe('connect', () => {
    test('adds source to registry and marks known', async () => {
      const stub = makeStubSource('power', 'stages-001', 'Stages LR');
      jest.spyOn(bleSensorManager, 'connect').mockResolvedValue(stub as unknown as Awaited<ReturnType<typeof bleSensorManager.connect>>);

      await usePairingStore.getState().connect('stages-001', 'power', 'Stages LR');

      expect(stub.start).toHaveBeenCalled();
      expect(sensorRegistry.get('stages-001', 'power')).toBe(stub);

      const state = usePairingStore.getState();
      expect(state.connections['stages-001|power'].status).toBe('connected');
      expect(state.known).toHaveLength(1);
      expect(state.known[0]).toEqual(
        expect.objectContaining({ id: 'stages-001', kind: 'power', name: 'Stages LR' }),
      );
    });

    test('updates lastConnectedAt for existing known device', async () => {
      const stub = makeStubSource('power', 'stages-001');
      jest.spyOn(bleSensorManager, 'connect').mockResolvedValue(stub as unknown as Awaited<ReturnType<typeof bleSensorManager.connect>>);

      usePairingStore.setState({
        known: [{ id: 'stages-001', name: 'Old Name', kind: 'power', lastConnectedAt: 100 }],
      });

      await usePairingStore.getState().connect('stages-001', 'power', 'New Name');

      const state = usePairingStore.getState();
      expect(state.known).toHaveLength(1);
      expect(state.known[0].name).toBe('New Name');
      expect(state.known[0].lastConnectedAt!).toBeGreaterThan(100);
    });

    test('marks connection as error and rethrows on connect failure', async () => {
      jest.spyOn(bleSensorManager, 'connect').mockRejectedValue(new Error('Connection lost'));

      await expect(
        usePairingStore.getState().connect('bad-device', 'power', 'Bad'),
      ).rejects.toThrow('Connection lost');
      expect(usePairingStore.getState().connections['bad-device|power'].status).toBe('error');
    });
  });

  describe('disconnect', () => {
    test('stops source, removes from registry, cancels BLE connection', async () => {
      const stub = makeStubSource('power', 'stages-001');
      sensorRegistry.add(stub as never);
      usePairingStore.setState({
        connections: {
          'stages-001|power': {
            deviceId: 'stages-001',
            kind: 'power',
            deviceName: 'Stages',
            status: 'connected',
          },
        },
      });
      const disconnectSpy = jest
        .spyOn(bleSensorManager, 'disconnect')
        .mockResolvedValue(undefined);

      await usePairingStore.getState().disconnect('stages-001', 'power');

      expect(stub.stop).toHaveBeenCalled();
      expect(sensorRegistry.get('stages-001', 'power')).toBeUndefined();
      expect(disconnectSpy).toHaveBeenCalledWith('stages-001');
      expect(usePairingStore.getState().connections['stages-001|power']).toBeUndefined();
    });

    test('does NOT cancel BLE connection when another kind for same device is still connected', async () => {
      const powerStub = makeStubSource('power', 'kickr-001');
      const cscStub = makeStubSource('cadence', 'kickr-001');
      sensorRegistry.add(powerStub as never);
      sensorRegistry.add(cscStub as never);
      usePairingStore.setState({
        connections: {
          'kickr-001|power': {
            deviceId: 'kickr-001',
            kind: 'power',
            deviceName: 'Kickr',
            status: 'connected',
          },
          'kickr-001|cadence': {
            deviceId: 'kickr-001',
            kind: 'cadence',
            deviceName: 'Kickr',
            status: 'connected',
          },
        },
      });
      const disconnectSpy = jest
        .spyOn(bleSensorManager, 'disconnect')
        .mockResolvedValue(undefined);

      await usePairingStore.getState().disconnect('kickr-001', 'power');

      expect(powerStub.stop).toHaveBeenCalled();
      expect(disconnectSpy).not.toHaveBeenCalled();
      expect(usePairingStore.getState().connections['kickr-001|cadence']).toBeDefined();
    });
  });

  describe('forget', () => {
    test('disconnects and removes from known', async () => {
      const stub = makeStubSource('power', 'stages-001');
      sensorRegistry.add(stub as never);
      usePairingStore.setState({
        connections: {
          'stages-001|power': {
            deviceId: 'stages-001',
            kind: 'power',
            deviceName: 'Stages',
            status: 'connected',
          },
        },
        known: [{ id: 'stages-001', name: 'Stages', kind: 'power', lastConnectedAt: 0 }],
      });
      jest.spyOn(bleSensorManager, 'disconnect').mockResolvedValue(undefined);

      await usePairingStore.getState().forget('stages-001', 'power');

      expect(usePairingStore.getState().known).toHaveLength(0);
      expect(usePairingStore.getState().connections['stages-001|power']).toBeUndefined();
    });
  });

  describe('reconnectKnown', () => {
    test('connects each known device; swallows per-device failures', async () => {
      const good = makeStubSource('power', 'good-1');
      usePairingStore.setState({
        known: [
          { id: 'good-1', name: 'Good', kind: 'power', lastConnectedAt: 0 },
          { id: 'missing-1', name: 'Missing', kind: 'heart_rate', lastConnectedAt: 0 },
        ],
      });
      jest.spyOn(bleSensorManager, 'connect').mockImplementation(async (id) => {
        if (id === 'good-1') return good as unknown as Awaited<ReturnType<typeof bleSensorManager.connect>>;
        throw new Error('Not in range');
      });

      await usePairingStore.getState().reconnectKnown();

      expect(usePairingStore.getState().connections['good-1|power']?.status).toBe('connected');
      // Missing device gets an error entry but does not throw
      expect(usePairingStore.getState().connections['missing-1|heart_rate']?.status).toBe('error');
    });

    test('is a no-op when known list is empty', async () => {
      const spy = jest.spyOn(bleSensorManager, 'connect');
      usePairingStore.setState({ known: [] });

      await usePairingStore.getState().reconnectKnown();

      expect(spy).not.toHaveBeenCalled();
    });

    test('emits Sentry breadcrumb when ALL known devices fail to reconnect', async () => {
      (Sentry.captureMessage as jest.Mock).mockClear();

      usePairingStore.setState({
        known: [
          { id: 'd1', name: 'D1', kind: 'power', lastConnectedAt: 0 },
          { id: 'd2', name: 'D2', kind: 'heart_rate', lastConnectedAt: 0 },
        ],
      });
      jest.spyOn(bleSensorManager, 'connect').mockRejectedValue(new Error('BLE off'));

      await usePairingStore.getState().reconnectKnown();

      expect(Sentry.captureMessage).toHaveBeenCalledWith(
        'Sensor reconnect failed for all known devices',
        expect.objectContaining({
          level: 'warning',
          extra: expect.objectContaining({ knownCount: 2 }),
        }),
      );
    });

    test('does not emit Sentry breadcrumb when at least one device reconnects', async () => {
      (Sentry.captureMessage as jest.Mock).mockClear();

      const ok = makeStubSource('power', 'good-1');
      usePairingStore.setState({
        known: [
          { id: 'good-1', name: 'Good', kind: 'power', lastConnectedAt: 0 },
          { id: 'bad-1', name: 'Bad', kind: 'heart_rate', lastConnectedAt: 0 },
        ],
      });
      jest.spyOn(bleSensorManager, 'connect').mockImplementation(async (id) => {
        if (id === 'good-1') return ok as unknown as Awaited<ReturnType<typeof bleSensorManager.connect>>;
        throw new Error('Not in range');
      });

      await usePairingStore.getState().reconnectKnown();

      expect(Sentry.captureMessage).not.toHaveBeenCalled();
    });
  });

  describe('disconnectAll', () => {
    test('disconnects every active connection and clears runtime state', async () => {
      const power = makeStubSource('power', 'p1');
      const hr = makeStubSource('heart_rate', 'h1');
      sensorRegistry.add(power as never);
      sensorRegistry.add(hr as never);
      usePairingStore.setState({
        connections: {
          'p1|power': {
            deviceId: 'p1',
            kind: 'power',
            deviceName: 'Power',
            status: 'connected',
          },
          'h1|heart_rate': {
            deviceId: 'h1',
            kind: 'heart_rate',
            deviceName: 'HRM',
            status: 'connected',
          },
        },
        scanning: true,
        discovered: {
          stale: {
            id: 'stale',
            name: 'Stale Advert',
            rssi: -80,
            advertisedServiceUuids: [],
            kinds: ['power'],
          } as DiscoveredDevice,
        },
      });
      jest.spyOn(bleSensorManager, 'disconnect').mockResolvedValue(undefined);

      await usePairingStore.getState().disconnectAll();

      expect(power.stop).toHaveBeenCalled();
      expect(hr.stop).toHaveBeenCalled();
      const state = usePairingStore.getState();
      expect(state.connections).toEqual({});
      expect(state.discovered).toEqual({});
      expect(state.scanning).toBe(false);
    });

    test('swallows per-connection failures so one bad source does not block others', async () => {
      const power = makeStubSource('power', 'p1');
      const hr = makeStubSource('heart_rate', 'h1');
      // Second source throws on stop
      hr.stop = jest.fn().mockRejectedValue(new Error('Already gone'));
      sensorRegistry.add(power as never);
      sensorRegistry.add(hr as never);
      usePairingStore.setState({
        connections: {
          'p1|power': {
            deviceId: 'p1',
            kind: 'power',
            deviceName: 'Power',
            status: 'connected',
          },
          'h1|heart_rate': {
            deviceId: 'h1',
            kind: 'heart_rate',
            deviceName: 'HRM',
            status: 'connected',
          },
        },
      });
      jest.spyOn(bleSensorManager, 'disconnect').mockResolvedValue(undefined);

      await expect(usePairingStore.getState().disconnectAll()).resolves.toBeUndefined();
      expect(power.stop).toHaveBeenCalled();
    });
  });

  describe('calibratePower', () => {
    test('sends start_offset_compensation to the matching power source', async () => {
      const stub = makeStubSource('power', 'stages-001');
      sensorRegistry.add(stub as never);

      const result = await usePairingStore.getState().calibratePower('stages-001');

      expect(stub.sendCommand).toHaveBeenCalledWith({ type: 'start_offset_compensation' });
      expect(result.success).toBe(true);
    });

    test('throws when no power source is connected for that device', async () => {
      await expect(
        usePairingStore.getState().calibratePower('missing'),
      ).rejects.toThrow('No power meter connected');
    });
  });

  describe('setWheelCircumference', () => {
    test('persists value to the known-device entry', () => {
      usePairingStore.setState({
        known: [
          { id: 'csc-1', name: 'Wahoo CSC', kind: 'cadence', lastConnectedAt: 0 },
        ],
      });

      usePairingStore.getState().setWheelCircumference('csc-1', 2.25);

      const updated = usePairingStore.getState().known.find((k) => k.id === 'csc-1');
      expect(updated?.wheelCircumferenceM).toBe(2.25);
    });

    test('rejects values outside physical range (0.5m, 5m, NaN, Infinity)', () => {
      usePairingStore.setState({
        known: [
          { id: 'csc-1', name: 'Wahoo CSC', kind: 'cadence', lastConnectedAt: 0 },
        ],
      });
      const api = usePairingStore.getState();

      api.setWheelCircumference('csc-1', 0.5);
      api.setWheelCircumference('csc-1', 5);
      api.setWheelCircumference('csc-1', NaN);
      api.setWheelCircumference('csc-1', Infinity);
      api.setWheelCircumference('csc-1', -1);

      const known = usePairingStore.getState().known.find((k) => k.id === 'csc-1');
      expect(known?.wheelCircumferenceM).toBeUndefined();
    });

    test('only updates the cadence kind entry, leaves other kinds untouched', () => {
      usePairingStore.setState({
        known: [
          { id: 'shared-device', name: 'Kickr', kind: 'power', lastConnectedAt: 0 },
          { id: 'shared-device', name: 'Kickr', kind: 'cadence', lastConnectedAt: 0 },
        ],
      });

      usePairingStore.getState().setWheelCircumference('shared-device', 2.15);

      const power = usePairingStore
        .getState()
        .known.find((k) => k.id === 'shared-device' && k.kind === 'power');
      const cadence = usePairingStore
        .getState()
        .known.find((k) => k.id === 'shared-device' && k.kind === 'cadence');
      expect(power?.wheelCircumferenceM).toBeUndefined();
      expect(cadence?.wheelCircumferenceM).toBe(2.15);
    });
  });

  describe('selectors', () => {
    test('selectHasConnectedSensors is false when empty', () => {
      expect(selectHasConnectedSensors(usePairingStore.getState())).toBe(false);
    });

    test('selectHasConnectedSensors true when at least one is connected', () => {
      usePairingStore.setState({
        connections: {
          'p1|power': {
            deviceId: 'p1',
            kind: 'power',
            deviceName: 'Power',
            status: 'connected',
          },
        },
      });
      expect(selectHasConnectedSensors(usePairingStore.getState())).toBe(true);
    });

    test('selectHasConnectedSensors ignores connecting/error states', () => {
      usePairingStore.setState({
        connections: {
          'p1|power': {
            deviceId: 'p1',
            kind: 'power',
            deviceName: 'Power',
            status: 'connecting',
          },
          'h1|heart_rate': {
            deviceId: 'h1',
            kind: 'heart_rate',
            deviceName: 'HRM',
            status: 'error',
          },
        },
      });
      expect(selectHasConnectedSensors(usePairingStore.getState())).toBe(false);
    });

    test('selectConnectedKinds de-duplicates across multiple devices of same kind', () => {
      usePairingStore.setState({
        connections: {
          'p1|power': {
            deviceId: 'p1',
            kind: 'power',
            deviceName: 'Stages',
            status: 'connected',
          },
          'p2|power': {
            deviceId: 'p2',
            kind: 'power',
            deviceName: 'Quarq (test)',
            status: 'connected',
          },
          'h1|heart_rate': {
            deviceId: 'h1',
            kind: 'heart_rate',
            deviceName: 'Garmin',
            status: 'connected',
          },
        },
      });
      const kinds = selectConnectedKinds(usePairingStore.getState()).sort();
      expect(kinds).toEqual(['heart_rate', 'power']);
    });

    test('selectConnectedCount counts only connected entries', () => {
      usePairingStore.setState({
        connections: {
          'p1|power': {
            deviceId: 'p1',
            kind: 'power',
            deviceName: 'Power',
            status: 'connected',
          },
          'h1|heart_rate': {
            deviceId: 'h1',
            kind: 'heart_rate',
            deviceName: 'HRM',
            status: 'connecting',
          },
        },
      });
      expect(selectConnectedCount(usePairingStore.getState())).toBe(1);
    });
  });
});
