import React from 'react';
import { fireEvent, render, screen, waitFor } from '@testing-library/react-native';

import ProfileScreen from '../ProfileScreen';
import { useAuthStore } from '../../stores/authStore';

const mockNavigate = jest.fn();

jest.mock('@expo/vector-icons/Feather', () => {
  const React = require('react');
  const { Text } = require('react-native');
  return function FeatherMock({ name }: { name: string }) {
    return React.createElement(Text, null, name);
  };
});

jest.mock('@react-navigation/native', () => {
  const React = require('react');
  return {
    useFocusEffect: (effect: () => void) => React.useEffect(effect, [effect]),
    useNavigation: () => ({
      navigate: mockNavigate,
      goBack: jest.fn(),
      reset: jest.fn(),
    }),
  };
});

jest.mock('@privy-io/expo', () => ({
  usePrivy: () => ({
    logout: jest.fn(),
  }),
}));

jest.mock('../../lib/api', () => {
  class MockApiError extends Error {
    type: string;
    retryable: boolean;

    constructor(message: string, type = 'unknown') {
      super(message);
      this.name = 'ApiError';
      this.type = type;
      this.retryable = type === 'network' || type === 'timeout';
    }
  }

  return {
    ApiError: MockApiError,
    setApiRefreshHandler: jest.fn(),
    api: {
      getMe: jest.fn(),
      getMyBeetleCards: jest.fn(),
      getMyLeaderboardPositions: jest.fn(),
      getMyProfileBootstrap: jest.fn(),
      getNotifications: jest.fn(),
    },
  };
});

const { api } = jest.requireMock('../../lib/api') as {
  api: {
    getMe: jest.Mock;
    getMyBeetleCards: jest.Mock;
    getMyLeaderboardPositions: jest.Mock;
    getMyProfileBootstrap: jest.Mock;
    getNotifications: jest.Mock;
  };
};

describe('ProfileScreen', () => {
  beforeEach(() => {
    jest.clearAllMocks();
    useAuthStore.getState().setAuthenticated({
      wallet: 'WalletAAAA1111',
      accessToken: 'access-token',
      tokenExpiresAt: new Date('2026-04-24T12:00:00.000Z').getTime(),
      authMethod: 'privy',
    });
    api.getNotifications.mockResolvedValue({ notifications: [], unreadCount: 0 });
  });

  test('renders owner-mode rider detail with BeetleCard and top climbs', async () => {
    const profile = {
      id: 'user-1',
      wallet: 'WalletAAAA1111',
      username: 'tim',
      displayName: 'Tim',
      bio: 'Rolls hard.',
      avatarUrl: null,
      isPublic: true,
      createdAt: '2026-04-24T00:00:00Z',
      totalRides: 9,
      totalTss: 777,
      totalElevationM: 8000,
    };
    const cards = [
      {
        id: 'card-1',
        wallet: 'WalletAAAA1111',
        cardType: 'CLIMB',
        scopeId: 'scope-1',
        scopeName: 'Manayunk Wall',
        score: 420,
        level: 3,
        patternsScored: 12,
        createdAt: '2026-04-24T00:00:00Z',
        updatedAt: '2026-04-24T00:00:00Z',
      },
    ];
    const leaderboard = {
      wallet: 'WalletAAAA1111',
      stats: {
        totalPositions: 1,
        komCount: 1,
        podiumCount: 1,
        top10Count: 1,
        totalVaultsCompleted: 1,
        bestPercentile: 1,
      },
      positions: [
        {
          vaultId: 7,
          canonClimbId: '11111111-1111-4111-8111-111111111111',
          vaultName: 'Manayunk Wall',
          vaultSignature: 'sig',
          rank: 1,
          bestTimeSeconds: 312,
          isKom: true,
          totalRiders: 42,
        },
        {
          vaultId: 8,
          canonClimbId: null,
          vaultName: 'Legacy Vault',
          vaultSignature: 'legacy-sig',
          rank: 4,
          bestTimeSeconds: 390,
          isKom: false,
          totalRiders: 42,
        },
      ],
    };
    api.getMyProfileBootstrap.mockResolvedValue({
      contractVersion: 'private_rider_profile.v1',
      profile,
      beetleCards: { cards, count: cards.length },
      leaderboard,
      notifications: { unreadCount: 0 },
    });

    render(<ProfileScreen />);

    await waitFor(() => {
      expect(screen.getByText('Tim')).toBeTruthy();
    });

    expect(screen.getByText('@tim')).toBeTruthy();
    expect(screen.getByText('BeetleCard')).toBeTruthy();
    expect(screen.getByText('Manayunk Wall Climb')).toBeTruthy();
    expect(screen.getByText('Top Climbs')).toBeTruthy();
    expect(screen.getByText('Wallet')).toBeTruthy();
    expect(screen.queryByText('Total TSS')).toBeNull();
    expect(screen.queryByText('777')).toBeNull();

    fireEvent.press(screen.getByTestId('profile-climb-7'));

    expect(mockNavigate).toHaveBeenCalledWith('ClimbDetail', {
      climbId: '11111111-1111-4111-8111-111111111111',
      backLabel: 'Profile',
    });

    fireEvent.press(screen.getByTestId('profile-climb-8'));
    expect(mockNavigate).toHaveBeenCalledTimes(1);
  });
});
