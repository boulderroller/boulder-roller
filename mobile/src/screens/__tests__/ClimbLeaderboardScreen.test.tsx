import React from 'react';
import { fireEvent, render, screen, waitFor } from '@testing-library/react-native';

import ClimbLeaderboardScreen from '../ClimbLeaderboardScreen';

const mockNavigate = jest.fn();
const mockGoBack = jest.fn();

jest.mock('@react-navigation/native', () => {
  const actual = jest.requireActual('@react-navigation/native');
  return {
    ...actual,
    useNavigation: () => ({
      navigate: mockNavigate,
      goBack: mockGoBack,
      reset: jest.fn(),
    }),
    useRoute: () => ({
      params: { climbId: 'climb-1', climbName: 'Manayunk Wall' },
    }),
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
      getClimbLeaderboard: jest.fn(),
      getUser: jest.fn(),
    },
  };
});

const { api } = jest.requireMock('../../lib/api') as {
  api: {
    getClimbLeaderboard: jest.Mock;
    getUser: jest.Mock;
  };
};

describe('ClimbLeaderboardScreen', () => {
  beforeEach(() => {
    jest.clearAllMocks();
  });

  test('renders rider rows and opens RiderDetail', async () => {
    api.getClimbLeaderboard.mockResolvedValue({
      climbId: 'climb-1',
      climbName: 'Manayunk Wall',
      entries: [
        { rank: 1, wallet: 'WalletAAAA1111', bestTimeSeconds: 312 },
        { rank: 2, wallet: 'WalletBBBB2222', bestTimeSeconds: 340 },
      ],
      leaderboard: [],
      komHolder: 'WalletAAAA1111',
      komTimeS: 312,
    });
    api.getUser.mockImplementation(async (wallet: string) => ({
      id: `user-${wallet}`,
      wallet,
      username: wallet === 'WalletAAAA1111' ? 'tim' : 'sam',
      displayName: wallet === 'WalletAAAA1111' ? 'Tim' : null,
      bio: null,
      avatarUrl: null,
      isPublic: true,
      createdAt: '2026-04-24T00:00:00Z',
      totalRides: 1,
      totalDistanceKm: 10,
      totalElevationM: 100,
      totalDungEarned: 0,
    }));

    render(<ClimbLeaderboardScreen />);

    await waitFor(() => {
      expect(screen.getByText('Tim')).toBeTruthy();
    });

    fireEvent.press(screen.getByTestId('leaderboard-rider-1'));

    expect(mockNavigate).toHaveBeenCalledWith('RiderDetail', {
      identifier: 'tim',
      initialIdentity: expect.objectContaining({
        wallet: 'WalletAAAA1111',
        username: 'tim',
        displayName: 'Tim',
      }),
      backLabel: 'Leaderboard',
    });
  });
});
