import React from 'react';
import { Alert } from 'react-native';
import { fireEvent, render, waitFor, act } from '@testing-library/react-native';

import RecordScreen from '../RecordScreen';
import { useRecordingStore } from '../../stores/recordingStore';
import { usePairingStore } from '../../stores/pairingStore';
import { sensorRegistry } from '../../services/sensors/registry';
import type { SensorKind, SensorSample } from '../../services/sensors/types';

const mockNavigate = jest.fn();

jest.mock('@expo/vector-icons/Feather', () => {
  const React = require('react');
  const { Text } = require('react-native');
  return function FeatherMock({ name }: { name: string }) {
    return React.createElement(Text, null, name);
  };
});

jest.mock('@react-navigation/native', () => ({
  useNavigation: () => ({
    navigate: mockNavigate,
  }),
}));

jest.mock('expo-location', () => ({
  Accuracy: {
    Balanced: 3,
  },
  getLastKnownPositionAsync: jest.fn(() => Promise.resolve({
    coords: {
      latitude: 40.001,
      longitude: -75.001,
    },
  })),
  getCurrentPositionAsync: jest.fn(),
}));

jest.mock('react-native-maps', () => {
  const React = require('react');
  const { View } = require('react-native');

  function MapViewMock({ children, testID }: { children?: React.ReactNode; testID?: string }) {
    return React.createElement(View, { testID }, children);
  }

  function PolylineMock() {
    return React.createElement(View, { testID: 'record-route-line' });
  }

  return {
    __esModule: true,
    default: MapViewMock,
    Polyline: PolylineMock,
  };
});

jest.mock('expo-crypto', () => ({
  randomUUID: jest.fn(() => 'ride-test-id'),
}));

jest.mock('../../services/database', () => ({
  getDatabase: jest.fn(),
  createRide: jest.fn(),
  deleteRide: jest.fn(),
  getRide: jest.fn(),
  updateRide: jest.fn(),
}));

jest.mock('../../services/uploadQueue', () => ({
  enqueueRide: jest.fn(),
}));

jest.mock('../../services/gpsRecording', () => ({
  getLocationPermissionBlocker: jest.fn((permissions, options) => {
    if (permissions.servicesEnabled === false) return 'services_disabled';
    if (!permissions.foreground) return 'foreground_permission';
    if (options?.requireBackground && !permissions.background) return 'background_permission';
    return null;
  }),
  requestLocationPermissions: jest.fn(() => Promise.resolve({ foreground: true })),
  startRecording: jest.fn(),
  stopRecording: jest.fn(),
  pauseRecording: jest.fn(),
  resumeRecording: jest.fn(),
  discardRecording: jest.fn(),
}));

const { requestLocationPermissions } = jest.requireMock('../../services/gpsRecording') as {
  requestLocationPermissions: jest.Mock;
};
const { startRecording, stopRecording } = jest.requireMock('../../services/gpsRecording') as {
  startRecording: jest.Mock;
  stopRecording: jest.Mock;
};
const { createRide, deleteRide, getDatabase, getRide, updateRide } = jest.requireMock('../../services/database') as {
  createRide: jest.Mock;
  deleteRide: jest.Mock;
  getDatabase: jest.Mock;
  getRide: jest.Mock;
  updateRide: jest.Mock;
};
const { enqueueRide } = jest.requireMock('../../services/uploadQueue') as {
  enqueueRide: jest.Mock;
};

function addSensorSource(kind: SensorKind, sample: SensorSample | null) {
  sensorRegistry.add({
    kind,
    deviceId: `${kind}-1`,
    deviceName: `${kind} sensor`,
    status: 'connected',
    start: jest.fn().mockResolvedValue(undefined),
    stop: jest.fn().mockResolvedValue(undefined),
    getLatest: jest.fn().mockReturnValue(sample),
    markLost: jest.fn(),
    isStale: jest.fn().mockReturnValue(false),
  } as never);
}

function locationReady(overrides: Record<string, unknown> = {}) {
  return {
    servicesEnabled: true,
    foreground: true,
    background: true,
    foregroundStatus: 'granted',
    backgroundStatus: 'granted',
    foregroundCanAskAgain: true,
    backgroundCanAskAgain: true,
    ...overrides,
  };
}

describe('RecordScreen', () => {
  beforeEach(() => {
    jest.clearAllMocks();
    getDatabase.mockReturnValue({ kind: 'mock-db' });
    requestLocationPermissions.mockResolvedValue(locationReady());
    useRecordingStore.getState().reset();
    usePairingStore.setState({
      discovered: {},
      known: [],
      connections: {},
      scanning: false,
      scanError: null,
    });
    sensorRegistry._clear();
  });

  test('renders the ready-to-ride cockpit', async () => {
    const screen = render(<RecordScreen />);

    expect(screen.getByText('Record')).toBeTruthy();
    expect(screen.getByText('Ready')).toBeTruthy();
    expect(screen.queryByText(/Record creates the ride evidence/)).toBeNull();
    expect(screen.getByText('No sensors')).toBeTruthy();
    expect(screen.getByText('GPS-only ride')).toBeTruthy();
    await waitFor(() => {
      expect(screen.getByText('GPS ready')).toBeTruthy();
    });
    expect(screen.getByText('Start ride')).toBeTruthy();
    await waitFor(() => {
      expect(screen.getByTestId('record-map')).toBeTruthy();
    });
  });

  test('rechecks stale location state when starting a ride', async () => {
    requestLocationPermissions
      .mockResolvedValueOnce(locationReady({
        foreground: false,
        foregroundStatus: 'denied',
        foregroundCanAskAgain: false,
      }))
      .mockResolvedValueOnce(locationReady());

    const screen = render(<RecordScreen />);

    await waitFor(() => {
      expect(screen.getByText('Location permission needed')).toBeTruthy();
    });

    await act(async () => {
      fireEvent.press(screen.getByText('Check location'));
    });

    await waitFor(() => {
      expect(createRide).toHaveBeenCalledWith(expect.anything(), expect.any(String), expect.any(Number));
    });
    const rideId = createRide.mock.calls[0][1];
    expect(startRecording).toHaveBeenCalledWith(rideId);
  });

  test('asks for Always Location before creating a ride row', async () => {
    const alertSpy = jest.spyOn(Alert, 'alert').mockImplementation(() => {});
    requestLocationPermissions.mockResolvedValue(locationReady({
      background: false,
      backgroundStatus: 'denied',
      backgroundCanAskAgain: false,
    }));

    const screen = render(<RecordScreen />);

    await waitFor(() => {
      expect(screen.getByText('Always Location needed')).toBeTruthy();
    });

    await act(async () => {
      fireEvent.press(screen.getByText('Start ride'));
    });

    await waitFor(() => {
      expect(alertSpy).toHaveBeenCalledWith(
        'Always Location Needed',
        expect.stringContaining('Always'),
        expect.any(Array),
      );
    });
    expect(createRide).not.toHaveBeenCalled();
    expect(startRecording).not.toHaveBeenCalled();
    expect(deleteRide).not.toHaveBeenCalled();
  });

  test('renders live ride stats in recording state', () => {
    requestLocationPermissions.mockReturnValueOnce(new Promise(() => {}));

    useRecordingStore.setState({
      status: 'recording',
      rideId: 'ride-123456789',
      elapsedMs: 3_723_000,
      distanceM: 12_340,
      elevationGainM: 235,
      currentSpeedMps: 8,
      sampleCount: 42,
      currentLocation: { latitude: 40.002, longitude: -75.002 },
      routePoints: [
        { latitude: 40.001, longitude: -75.001 },
        { latitude: 40.002, longitude: -75.002 },
      ],
    });

    const screen = render(<RecordScreen />);

    expect(screen.getByText('Recording')).toBeTruthy();
    expect(screen.getByText('GPS locked')).toBeTruthy();
    expect(screen.getByText('01:02:03')).toBeTruthy();
    expect(screen.getByText('12.3 km')).toBeTruthy();
    expect(screen.getByText('28.8 km/h')).toBeTruthy();
    expect(screen.getByText('235 m')).toBeTruthy();
    expect(screen.getByText('Tracking')).toBeTruthy();
    expect(screen.getByText('On device')).toBeTruthy();
    expect(screen.getByTestId('record-map')).toBeTruthy();
    expect(screen.getByTestId('record-route-line')).toBeTruthy();
  });

  test('renders live connected sensor values in the recording cockpit', () => {
    requestLocationPermissions.mockReturnValueOnce(new Promise(() => {}));

    usePairingStore.setState({
      known: [
        { id: 'power-1', name: 'Stages Power', kind: 'power', lastConnectedAt: 1 },
        { id: 'heart_rate-1', name: 'Garmin HRM', kind: 'heart_rate', lastConnectedAt: 1 },
      ],
      connections: {
        'power-1|power': {
          deviceId: 'power-1',
          kind: 'power',
          deviceName: 'Stages Power',
          status: 'connected',
        },
        'heart_rate-1|heart_rate': {
          deviceId: 'heart_rate-1',
          kind: 'heart_rate',
          deviceName: 'Garmin HRM',
          status: 'connected',
        },
      },
    });
    addSensorSource('power', {
      power_w: 214,
      cadence_rpm: 91,
      timestamp_ms: 1,
    });
    addSensorSource('heart_rate', {
      heart_rate_bpm: 148,
      timestamp_ms: 1,
    });
    useRecordingStore.setState({
      status: 'recording',
      rideId: 'ride-sensors',
      elapsedMs: 12_000,
      distanceM: 500,
      elevationGainM: 12,
      currentSpeedMps: 6,
      sampleCount: 3,
      currentLocation: { latitude: 40.002, longitude: -75.002 },
      routePoints: [
        { latitude: 40.001, longitude: -75.001 },
        { latitude: 40.002, longitude: -75.002 },
      ],
    });

    const screen = render(<RecordScreen />);

    expect(screen.getByText('Power · HR ready')).toBeTruthy();
    expect(screen.getByTestId('record-live-sensors')).toBeTruthy();
    expect(screen.getByTestId('record-live-sensor-power').props.children).toBe('214');
    expect(screen.getByTestId('record-live-sensor-heart').props.children).toBe('148');
    expect(screen.getByTestId('record-live-sensor-cadence').props.children).toBe('91');
  });

  test('keeps accidental short recordings local instead of enqueueing upload', async () => {
    jest.spyOn(Alert, 'alert').mockImplementation((title, message, buttons) => {
      buttons?.find((button) => button.text === 'End Ride')?.onPress?.();
    });
    requestLocationPermissions.mockReturnValueOnce(new Promise(() => {}));
    stopRecording.mockResolvedValue('ride-short');
    getRide.mockReturnValue({
      id: 'ride-short',
      status: 'stopped',
      started_at: Date.now() - 4_000,
      ended_at: Date.now(),
      duration_ms: 4_000,
      moving_time_ms: 4_000,
      distance_m: 0,
      elevation_gain_m: 0,
      max_speed_mps: 0,
      sport_type: 'ride',
      clock_drift_ms: null,
      sample_count: 2,
      rejected_samples: null,
      upload_id: null,
      notes: null,
      preliminary_ride_hash: null,
      parser_version: null,
      had_crash_recovery: 0,
    });
    useRecordingStore.setState({
      status: 'recording',
      rideId: 'ride-short',
      elapsedMs: 4_000,
      distanceM: 0,
      elevationGainM: 0,
      currentSpeedMps: 0,
      sampleCount: 2,
      currentLocation: { latitude: 40.002, longitude: -75.002 },
      routePoints: [
        { latitude: 40.002, longitude: -75.002 },
      ],
    });

    const screen = render(<RecordScreen />);
    await act(async () => {
      fireEvent.press(screen.getByText('Stop'));
    });

    await waitFor(() => {
      expect(updateRide).toHaveBeenCalledWith(expect.anything(), 'ride-short', expect.objectContaining({
        status: 'incomplete',
      }));
    });
    expect(enqueueRide).not.toHaveBeenCalled();
    expect(mockNavigate).toHaveBeenCalledWith('PostRide', { rideId: 'ride-short' });
  });
});
