import React from 'react';
import { render } from '@testing-library/react-native';

import PairingScreen from '../PairingScreen';
import { usePairingStore } from '../../stores/pairingStore';
import { sensorRegistry } from '../../services/sensors/registry';
import type { DiscoveredDevice } from '../../services/sensors/ble/manager';

describe('PairingScreen', () => {
  beforeEach(() => {
    usePairingStore.setState({
      discovered: {},
      known: [],
      connections: {},
      scanning: false,
      scanError: null,
    });
    sensorRegistry._clear();
  });

  test('renders paired sensors with rider-facing statuses', () => {
    usePairingStore.setState({
      known: [
        { id: 'p1', name: 'Stages Power', kind: 'power', lastConnectedAt: 1 },
        { id: 'h1', name: 'Garmin HRM', kind: 'heart_rate', lastConnectedAt: 1 },
        { id: 'c1', name: 'Wahoo Cadence', kind: 'cadence', lastConnectedAt: 1 },
        { id: 'old', name: 'Old Sensor', kind: 'power', lastConnectedAt: 1 },
      ],
      connections: {
        'p1|power': {
          deviceId: 'p1',
          kind: 'power',
          deviceName: 'Stages Power',
          status: 'connected',
        },
        'h1|heart_rate': {
          deviceId: 'h1',
          kind: 'heart_rate',
          deviceName: 'Garmin HRM',
          status: 'connecting',
        },
        'c1|cadence': {
          deviceId: 'c1',
          kind: 'cadence',
          deviceName: 'Wahoo Cadence',
          status: 'error',
        },
      },
    });

    const screen = render(<PairingScreen />);

    expect(screen.getByText('Stages Power')).toBeTruthy();
    expect(screen.getByText('Ready')).toBeTruthy();
    expect(screen.getByText('Connecting')).toBeTruthy();
    expect(screen.getByText('Needs attention')).toBeTruthy();
    expect(screen.getByText('Not nearby')).toBeTruthy();
  });

  test('translates scan errors instead of showing raw BLE text', () => {
    usePairingStore.setState({
      scanError: 'Bluetooth permission denied by native stack',
    });

    const screen = render(<PairingScreen />);

    expect(screen.getByText('Allow Bluetooth access in Settings, then try again.')).toBeTruthy();
    expect(screen.queryByText(/native stack/)).toBeNull();
  });

  test('renders nearby devices as pairable without hiding their kind', () => {
    const device: DiscoveredDevice = {
      id: 'tickr-1',
      name: 'Wahoo TICKR',
      rssi: -52,
      advertisedServiceUuids: [],
      kinds: ['heart_rate'],
    };
    usePairingStore.setState({
      discovered: { 'tickr-1': device },
      scanning: true,
    });

    const screen = render(<PairingScreen />);

    expect(screen.getByText('Wahoo TICKR')).toBeTruthy();
    expect(screen.getByText(/Heart Rate/)).toBeTruthy();
    expect(screen.getByText('Nearby')).toBeTruthy();
    expect(screen.getByText('Pair')).toBeTruthy();
  });
});
