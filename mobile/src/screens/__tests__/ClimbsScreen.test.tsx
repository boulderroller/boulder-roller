import React from 'react';
import { fireEvent, render, waitFor } from '@testing-library/react-native';

import ClimbsScreen from '../ClimbsScreen';
import { useAuthStore } from '../../stores/authStore';

jest.mock('@expo/vector-icons/Feather', () => {
  const React = require('react');
  const { Text } = require('react-native');
  return function FeatherMock({ name }: { name: string }) {
    return React.createElement(Text, null, name);
  };
});

const mockNavigate = jest.fn();

jest.mock('@react-navigation/native', () => {
  const React = require('react');
  const actual = jest.requireActual('@react-navigation/native');
  return {
    ...actual,
    useNavigation: () => ({
      navigate: mockNavigate,
      goBack: jest.fn(),
      reset: jest.fn(),
    }),
    useFocusEffect: (callback: () => void | (() => void)) => {
      React.useEffect(() => callback(), [callback]);
    },
  };
});

jest.mock('../../lib/api', () => {
  class MockApiError extends Error {
    type: string;
    retryable: boolean;
    status?: number;

    constructor(message: string, type = 'unknown', status?: number) {
      super(message);
      this.name = 'ApiError';
      this.type = type;
      this.status = status;
      this.retryable = type === 'network' || type === 'timeout';
    }
  }

  return {
    ApiError: MockApiError,
    api: {
      getClimbs: jest.fn(),
      getPopularClimbs: jest.fn(),
    },
  };
});

const { api } = jest.requireMock('../../lib/api') as {
  api: { getClimbs: jest.Mock; getPopularClimbs: jest.Mock };
};

function makeClimb(overrides: Partial<{
  id: string;
  name: string;
  region: string | null;
  lengthM: number;
  elevGainM: number;
  avgGradientPct: number;
  hasVault: boolean;
  totalStaked: string;
  totalStakedBaseUnits: string;
  totalCompletions: number;
}> = {}) {
  return {
    id: overrides.id ?? 'climb-1',
    name: overrides.name ?? 'Manayunk Wall',
    region: overrides.region ?? 'Philadelphia',
    lengthM: overrides.lengthM ?? 1200,
    elevGainM: overrides.elevGainM ?? 140,
    avgGradientPct: overrides.avgGradientPct ?? 9.1,
    vaultId: overrides.hasVault ?? false ? 1 : null,
    vaultSignature: null,
    hasVault: overrides.hasVault ?? false,
    totalStaked: overrides.totalStaked ?? '0',
    totalStakedBaseUnits: overrides.totalStakedBaseUnits ?? '0',
    totalCalStaked: overrides.totalStaked ?? '0',
    totalCalStakedBaseUnits: overrides.totalStakedBaseUnits ?? '0',
    totalCompletions: overrides.totalCompletions ?? 0,
  };
}

describe('ClimbsScreen', () => {
  beforeEach(() => {
    jest.clearAllMocks();
    api.getPopularClimbs.mockResolvedValue([]);
    useAuthStore.getState().setAuthenticated({
      accessToken: 'token',
      tokenExpiresAt: Date.now() + 60_000,
      wallet: 'Wallet1111111111111111111111111111111111',
      authMethod: 'wallet',
    });
  });

  test('renders segmented filter controls, filters vault-live climbs, and navigates on press', async () => {
    const vaultClimb = makeClimb({
      id: 'climb-vault',
      name: 'Tough Climb',
      hasVault: true,
      totalStaked: '1420',
      totalStakedBaseUnits: '1420000000000',
      totalCompletions: 40,
    });
    const plainClimb = makeClimb({
      id: 'climb-plain',
      name: 'Quiet Hill',
      hasVault: false,
      totalCompletions: 3,
    });
    api.getPopularClimbs.mockResolvedValue([plainClimb, vaultClimb]);
    api.getClimbs.mockResolvedValue([
      vaultClimb,
      plainClimb,
    ]);

    const screen = render(<ClimbsScreen />);

    await waitFor(() => {
      expect(screen.getByText('Tough Climb')).toBeTruthy();
    });

    expect(api.getPopularClimbs).toHaveBeenCalledWith(20);
    expect(screen.getByTestId('segmented-popular')).toBeTruthy();
    expect(screen.getByTestId('segmented-vaultLive')).toBeTruthy();
    expect(screen.getByText('Tough Climb')).toBeTruthy();
    expect(screen.getByText('Balance • 1,420 CAL deposited')).toBeTruthy();
    expect(screen.getByText('Quiet Hill')).toBeTruthy();

    fireEvent.press(screen.getByText('Vaults'));

    await waitFor(() => {
      expect(screen.getByText('Tough Climb')).toBeTruthy();
    });
    expect(screen.queryByText('Quiet Hill')).toBeNull();

    fireEvent.press(screen.getByTestId('climb-card-climb-vault'));

    expect(mockNavigate).toHaveBeenCalledWith('ClimbDetail', { climbId: 'climb-vault' });
  });

  test('uses the popular climbs endpoint for the Popular tab', async () => {
    api.getPopularClimbs.mockResolvedValue([
      makeClimb({
        id: 'popular-vault',
        name: 'Actual Popular Climb',
        hasVault: true,
        totalCompletions: 99,
      }),
    ]);
    api.getClimbs.mockResolvedValue([
      makeClimb({
        id: 'vertical-vault',
        name: 'Tall But Quiet',
        hasVault: true,
        totalCompletions: 1,
      }),
    ]);

    const screen = render(<ClimbsScreen />);

    await waitFor(() => {
      expect(screen.getByText('Actual Popular Climb')).toBeTruthy();
    });

    expect(screen.queryByText('Tall But Quiet')).toBeNull();
  });

  test('keeps filter controls visible when vault-live filter has no results', async () => {
    const quietHill = makeClimb({
      id: 'climb-plain',
      name: 'Quiet Hill',
      hasVault: false,
      totalCompletions: 3,
    });
    api.getPopularClimbs.mockResolvedValue([quietHill]);
    api.getClimbs.mockResolvedValue([quietHill]);

    const screen = render(<ClimbsScreen />);

    await waitFor(() => {
      expect(screen.getByText('Quiet Hill')).toBeTruthy();
    });

    fireEvent.press(screen.getByText('Vaults'));

    await waitFor(() => {
      expect(screen.getByText('No vault-live climbs yet')).toBeTruthy();
    });

    expect(screen.getByText('Popular')).toBeTruthy();
    expect(screen.getByText('Vaults')).toBeTruthy();

    fireEvent.press(screen.getByText('Popular'));

    await waitFor(() => {
      expect(screen.getByText('Quiet Hill')).toBeTruthy();
    });
  });
});
