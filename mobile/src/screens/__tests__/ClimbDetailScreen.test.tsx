import React from 'react';
import { fireEvent, render, waitFor } from '@testing-library/react-native';

import ClimbDetailScreen from '../ClimbDetailScreen';

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
      params: { climbId: 'climb-1' },
    }),
  };
});

jest.mock('@expo/vector-icons/Feather', () => {
  const React = require('react');
  const { Text } = require('react-native');
  return function MockFeather({ name }: { name: string }) {
    return React.createElement(Text, null, name);
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
      getClimb: jest.fn(),
      getClimbLeaderboard: jest.fn(),
      getUser: jest.fn(),
      resolveLink: jest.fn(),
    },
  };
});

const { api } = jest.requireMock('../../lib/api') as {
  api: {
    getClimb: jest.Mock;
    getClimbLeaderboard: jest.Mock;
    getUser: jest.Mock;
    resolveLink: jest.Mock;
  };
};

describe('ClimbDetailScreen', () => {
  beforeEach(() => {
    jest.clearAllMocks();
    api.resolveLink.mockResolvedValue({
      contractVersion: 'link.v1',
      status: 'resolved',
      target: { type: 'climb', id: 'climb-1' },
      webPath: '/climbs/climb-1',
      canonicalUrl: 'https://boulderroller.app/climbs/climb-1',
      appUrl: 'boulderroller://climbs/climb-1',
      title: 'Manayunk Wall',
      description: 'Canonical climb on Boulder Roller.',
      access: { canView: true, reason: 'protocol_public', protocolPublic: true, requiresAuth: false },
      metadata: {},
      scanState: 'recorded',
      scanTargets: [
        {
          contractVersion: 'scan.v1',
          type: 'vault',
          id: '77',
          state: 'recorded',
          label: 'Vault 77',
          url: 'https://scan.boulderroller.xyz/vault/77',
          source: 'climb.vault',
        },
      ],
      share: {
        title: 'Manayunk Wall',
        text: 'Canonical climb on Boulder Roller.',
        url: 'https://boulderroller.app/climbs/climb-1',
      },
      openGraph: {
        title: 'Manayunk Wall',
        text: 'Canonical climb on Boulder Roller.',
        url: 'https://boulderroller.app/climbs/climb-1',
        type: 'climb',
      },
    });
  });

  test('renders climb identity and routes to full leaderboard', async () => {
    api.getClimb.mockResolvedValue({
      id: 'climb-1',
      name: 'Manayunk Wall',
      region: 'Philadelphia',
      lengthM: 1200,
      elevGainM: 140,
      avgGradientPct: 9.1,
      vaultId: 77,
      vaultSignature: 'abc',
      hasVault: true,
      totalStaked: '1700',
      totalStakedBaseUnits: '1700000000000',
      totalCalStaked: '1700',
      totalCalStakedBaseUnits: '1700000000000',
      totalCompletions: 44,
      localLegend: null,
    });
    api.getClimbLeaderboard.mockResolvedValue({
      climbId: 'climb-1',
      climbName: 'Manayunk Wall',
      entries: [
        { rank: 1, wallet: 'WalletAAAA1111', bestTimeSeconds: 300 },
        { rank: 2, wallet: 'WalletBBBB2222', bestTimeSeconds: 320 },
        { rank: 3, wallet: 'WalletCCCC3333', bestTimeSeconds: 340 },
      ],
      leaderboard: [],
      komHolder: 'WalletAAAA1111',
      komTimeS: 300,
    });
    api.getUser.mockImplementation(async (wallet: string) => ({
      id: `user-${wallet}`,
      wallet,
      username: wallet === 'WalletAAAA1111' ? 'tim' : null,
      displayName: wallet === 'WalletAAAA1111' ? null : `Rider ${wallet.slice(-4)}`,
      bio: null,
      avatarUrl: null,
      isPublic: true,
      createdAt: '2026-04-24T00:00:00Z',
      totalRides: 3,
      totalDistanceKm: 100,
      totalElevationM: 1000,
      totalDungEarned: 0,
    }));

    const screen = render(<ClimbDetailScreen />);

    await waitFor(() => {
      expect(screen.getByText('Manayunk Wall')).toBeTruthy();
    });

    expect(screen.getByText('Philadelphia')).toBeTruthy();
    expect(screen.getAllByText('Vault').length).toBeGreaterThanOrEqual(1);
    expect(screen.getAllByText('Leaderboard').length).toBeGreaterThanOrEqual(1);
    expect(screen.getByText('BoulderScan')).toBeTruthy();
    expect(screen.getByText('Your best')).toBeTruthy();
    expect(screen.getByText('#1')).toBeTruthy();
    await waitFor(() => {
      expect(screen.getByText('@tim')).toBeTruthy();
    });

    fireEvent.press(screen.getByTestId('climb-detail-rider-1'));
    expect(mockNavigate).toHaveBeenCalledWith('RiderDetail', {
      identifier: 'tim',
      initialIdentity: expect.objectContaining({
        wallet: 'WalletAAAA1111',
        username: 'tim',
      }),
      backLabel: 'Climb',
    });

    fireEvent.press(screen.getByText('See Top 10'));

    expect(mockNavigate).toHaveBeenCalledWith('ClimbLeaderboard', {
      climbId: 'climb-1',
      climbName: 'Manayunk Wall',
      backLabel: 'Climb',
    });
  });
});
