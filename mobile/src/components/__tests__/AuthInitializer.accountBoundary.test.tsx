import React from 'react';
import { Text } from 'react-native';
import { act, render, waitFor } from '@testing-library/react-native';

jest.mock('../../services/authService', () => ({
  initializeAuth: jest.fn().mockResolvedValue(undefined),
}));

jest.mock('../../services/tokenRefreshManager', () => ({
  tokenRefreshManager: {
    isRefreshDue: jest.fn().mockReturnValue(false),
    refresh: jest.fn(),
    schedule: jest.fn(),
  },
}));

const mockDatabase = {
  getFirstSync: jest.fn().mockReturnValue({ t_offset_ms: 5_000 }),
};
jest.mock('../../services/database', () => ({
  initDatabase: jest.fn().mockResolvedValue(mockDatabase),
  getDatabase: jest.fn(() => mockDatabase),
}));

jest.mock('../../services/uploadQueue', () => ({
  startQueueProcessor: jest.fn(),
  retryAuthFailedUploads: jest.fn(),
  processQueue: jest.fn(),
}));

jest.mock('../../services/crashRecovery', () => ({
  detectInterruptedRide: jest.fn(),
  saveInterruptedRide: jest.fn(),
  discardInterruptedRide: jest.fn(),
}));

const mockReconnectKnown = jest.fn().mockResolvedValue(undefined);
const mockDisconnectAll = jest.fn().mockResolvedValue(undefined);
jest.mock('../../stores/pairingStore', () => ({
  usePairingStore: {
    getState: () => ({
      reconnectKnown: mockReconnectKnown,
      disconnectAll: mockDisconnectAll,
    }),
  },
}));

jest.mock('../../services/sensors/ble/manager', () => ({
  bleSensorManager: { auditStaleness: jest.fn() },
}));

jest.mock('../../services/gpsRecording', () => ({
  suspendRecordingForAccountBoundary: jest.fn().mockResolvedValue(undefined),
}));

jest.mock('../RideRecoveryModal', () => ({
  __esModule: true,
  default: ({ ride }: { ride: { id: string } }) => {
    // eslint-disable-next-line @typescript-eslint/no-require-imports
    const MockReact = require('react');
    // eslint-disable-next-line @typescript-eslint/no-require-imports
    const { Text: MockText } = require('react-native');
    return MockReact.createElement(
      MockText,
      { testID: `recovery-${ride.id}` },
      ride.id,
    );
  },
}));

import AuthInitializer from '../AuthInitializer';
import { detectInterruptedRide } from '../../services/crashRecovery';
import { suspendRecordingForAccountBoundary } from '../../services/gpsRecording';
import { useAuthStore } from '../../stores/authStore';

const WALLET_A = 'WalletAAAA111111111111111111111111111111';
const WALLET_B = 'WalletBBBB222222222222222222222222222222';

function signIn(wallet: string): void {
  useAuthStore.getState().setAuthenticated({
    accessToken: `token-${wallet}`,
    tokenExpiresAt: Date.now() + 60_000,
    wallet,
    authMethod: 'wallet',
  });
}

function interruptedRide(id: string) {
  return {
    id,
    owner_key: id === 'ride-a' ? `wallet:${WALLET_A}` : `wallet:${WALLET_B}`,
    status: 'recording',
    started_at: 1_700_000_000_000,
    ended_at: null,
    duration_ms: 1_000,
    moving_time_ms: 1_000,
    distance_m: 100,
    elevation_gain_m: 5,
    max_speed_mps: 4,
    sport_type: 'ride',
    clock_drift_ms: null,
    sample_count: 2,
    rejected_samples: null,
    upload_id: null,
    notes: null,
    preliminary_ride_hash: null,
    parser_version: null,
    had_crash_recovery: 1,
  };
}

describe('AuthInitializer local recovery account boundary', () => {
  beforeEach(() => {
    jest.clearAllMocks();
    mockReconnectKnown.mockResolvedValue(undefined);
    mockDisconnectAll.mockResolvedValue(undefined);
    (detectInterruptedRide as jest.Mock).mockImplementation(() => {
      const wallet = useAuthStore.getState().wallet;
      if (wallet === WALLET_A) return interruptedRide('ride-a');
      if (wallet === WALLET_B) return interruptedRide('ride-b');
      return null;
    });
    signIn(WALLET_A);
  });

  afterEach(() => {
    act(() => {
      useAuthStore.getState().setUnauthenticated();
    });
  });

  test('A recovery survives refresh but is cleared and replaced after logout to B', async () => {
    const screen = render(
      <AuthInitializer>
        <Text>App</Text>
      </AuthInitializer>,
    );

    await waitFor(() => {
      expect(screen.getByTestId('recovery-ride-a')).toBeTruthy();
    });

    act(() => {
      useAuthStore.getState().setRefreshing();
    });
    expect(screen.getByTestId('recovery-ride-a')).toBeTruthy();
    expect(suspendRecordingForAccountBoundary).not.toHaveBeenCalled();

    act(() => {
      useAuthStore.getState().setUnauthenticated();
    });
    await waitFor(() => {
      expect(screen.queryByTestId('recovery-ride-a')).toBeNull();
    });

    act(() => {
      signIn(WALLET_B);
    });
    await waitFor(() => {
      expect(screen.getByTestId('recovery-ride-b')).toBeTruthy();
    });

    expect(screen.queryByTestId('recovery-ride-a')).toBeNull();
    expect(suspendRecordingForAccountBoundary).toHaveBeenCalledTimes(1);
  });
});
