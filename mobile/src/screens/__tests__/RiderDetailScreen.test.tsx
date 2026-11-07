import React from 'react';
import { Alert } from 'react-native';
import { fireEvent, render, screen, waitFor } from '@testing-library/react-native';

import RiderDetailScreen from '../RiderDetailScreen';
import { useAuthStore } from '../../stores/authStore';

const mockGoBack = jest.fn();
const mockNavigate = jest.fn();
let mockRouteParams: any = {
  identifier: 'WalletAAAA1111',
  initialIdentity: { wallet: 'WalletAAAA1111' },
  backLabel: 'Leaderboard',
};

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
      params: mockRouteParams,
    }),
  };
});

jest.mock('../../lib/api', () => {
  class MockApiError extends Error {
    type: string;
    retryable: boolean;
    statusCode?: number;

    constructor(message: string, type = 'unknown', statusCode?: number) {
      super(message);
      this.name = 'ApiError';
      this.type = type;
      this.statusCode = statusCode;
      this.retryable = type === 'network_error' || type === 'timeout';
    }
  }

  return {
    ApiError: MockApiError,
    api: {
      getUser: jest.fn(),
      getPublicRiderProfile: jest.fn(),
      getMe: jest.fn(),
      getUserLeaderboardPositions: jest.fn(),
      getPublicRiderRecentRides: jest.fn(),
      getPublicRiderBeetleCards: jest.fn(),
      resolveLink: jest.fn(),
      getFollowState: jest.fn(),
      followUser: jest.fn(),
      unfollowUser: jest.fn(),
      reportSocialContent: jest.fn(),
    },
  };
});

const { api, ApiError } = jest.requireMock('../../lib/api') as {
  ApiError: new (message: string, type?: string, statusCode?: number) => Error;
  api: {
    getUser: jest.Mock;
    getPublicRiderProfile: jest.Mock;
    getMe: jest.Mock;
    getUserLeaderboardPositions: jest.Mock;
    getPublicRiderRecentRides: jest.Mock;
    getPublicRiderBeetleCards: jest.Mock;
    resolveLink: jest.Mock;
    getFollowState: jest.Mock;
    followUser: jest.Mock;
    unfollowUser: jest.Mock;
    reportSocialContent: jest.Mock;
  };
};

const PUBLIC_RIDER = {
  id: 'target-user',
  wallet: 'WalletAAAA1111',
  username: 'tim',
  displayName: 'Tim',
  bio: 'Rolls hard.',
  avatarUrl: null,
  isPublic: true,
  createdAt: '2026-04-24T00:00:00Z',
  totalRides: 9,
  totalDistanceKm: 420,
  totalElevationM: 8000,
  totalDungEarned: 0,
};

function publicProfileBundle(
  profileOverrides: Record<string, any> = {},
  bundleOverrides: Record<string, any> = {},
) {
  const profile: Record<string, any> = { ...PUBLIC_RIDER, ...profileOverrides };
  return {
    contractVersion: 'public_rider_profile.v1',
    rider: profile.rider ?? {
      contractVersion: 'public_rider_ref.v1',
      id: profile.id,
      username: profile.username,
      displayName: profile.displayName,
      avatarUrl: profile.avatarUrl,
      isPublic: profile.isPublic,
      viewerRelationship: 'none',
    },
    profile,
    privacy: profile.privacy ?? { visibility: 'public', canView: true, isOwner: false, isFollower: false, redactGps: false, protocolPublic: false, protocolPublicFields: [], reason: 'public' },
    viewerCapabilities: {
      canView: true,
      canFollow: true,
      canReport: true,
      canShare: true,
      viewerRelationship: 'none',
    },
    followState: null,
    recentRides: { isPublic: profile.isPublic, rides: [], count: 0 },
    beetleCards: { isPublic: profile.isPublic, cards: [], count: 0 },
    leaderboard: null,
    ...bundleOverrides,
  };
}

describe('RiderDetailScreen', () => {
  beforeEach(() => {
    jest.clearAllMocks();
    mockRouteParams = {
      identifier: 'WalletAAAA1111',
      initialIdentity: { wallet: 'WalletAAAA1111' },
      backLabel: 'Leaderboard',
    };
    useAuthStore.getState().setAuthenticated({
      wallet: 'ViewerWallet1111',
      accessToken: 'access-token',
      tokenExpiresAt: new Date('2026-04-24T12:00:00.000Z').getTime(),
      authMethod: 'privy',
    });
    api.reportSocialContent.mockResolvedValue({
      id: 'report-1',
      reporterId: 'viewer-user',
      targetType: 'user',
      targetId: 'target-user',
      reason: 'other',
      status: 'open',
      createdAt: '2026-04-29T12:00:00Z',
    });
    api.getPublicRiderProfile.mockResolvedValue(publicProfileBundle());
    api.getPublicRiderRecentRides.mockResolvedValue({
      isPublic: true,
      rides: [],
      count: 0,
    });
    api.getPublicRiderBeetleCards.mockResolvedValue({
      isPublic: true,
      cards: [],
      count: 0,
    });
    api.resolveLink.mockResolvedValue({
      contractVersion: 'link.v1',
      status: 'resolved',
      target: { type: 'rider', id: 'tim' },
      webPath: '/riders/tim',
      canonicalUrl: 'https://boulderroller.app/riders/tim',
      appUrl: 'boulderroller://riders/tim',
      title: 'Tim',
      description: 'Rider profile on Boulder Roller.',
      access: { canView: true, reason: 'public', protocolPublic: true, requiresAuth: false },
      metadata: {},
      scanState: 'recorded',
      scanTargets: [
        {
          contractVersion: 'scan.v1',
          type: 'wallet',
          id: 'WalletAAAA1111',
          state: 'recorded',
          label: 'Wallet account',
          url: 'https://scan.boulderroller.xyz/account/WalletAAAA1111',
          source: 'user.wallet',
        },
      ],
      share: {
        title: 'Tim',
        text: 'Rider profile on Boulder Roller.',
        url: 'https://boulderroller.app/riders/tim',
      },
      openGraph: {
        title: 'Tim',
        text: 'Rider profile on Boulder Roller.',
        url: 'https://boulderroller.app/riders/tim',
        type: 'rider',
      },
    });
  });

  test('renders public rider identity, follow state, and top climbs', async () => {
    api.getPublicRiderProfile.mockResolvedValue(publicProfileBundle({}, {
      followState: {
        isFollowing: false,
        isFollowedBy: false,
        isMutualFollow: false,
      },
      leaderboard: {
        wallet: PUBLIC_RIDER.wallet,
        stats: {
          totalPositions: 2,
          komCount: 1,
          podiumCount: 2,
          top10Count: 2,
          totalVaultsCompleted: 2,
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
        ],
      },
    }));
    api.getMe.mockResolvedValue({
      id: 'viewer-user',
      wallet: 'ViewerWallet1111',
      username: 'viewer',
      displayName: 'Viewer',
      bio: null,
      avatarUrl: null,
      createdAt: '2026-04-24T00:00:00Z',
      totalRides: 1,
      totalTss: 10,
      level: 1,
    });
    api.followUser.mockResolvedValue({ status: 'followed', followingId: 'target-user' });

    render(<RiderDetailScreen />);

    await waitFor(() => {
      expect(screen.getAllByText('Tim').length).toBeGreaterThan(0);
    });

    expect(screen.getAllByText('@tim').length).toBeGreaterThan(0);
    expect(screen.getByText('Rolls hard.')).toBeTruthy();
    expect(screen.getByText('BoulderScan')).toBeTruthy();
    expect(screen.getByText('BoulderScan ready')).toBeTruthy();
    expect(screen.getByText('Open BoulderScan')).toBeTruthy();
    expect(screen.queryByText(/Open proof/i)).toBeNull();
    expect(screen.getByText('Top Climbs')).toBeTruthy();
    expect(screen.getByText('Manayunk Wall')).toBeTruthy();

    fireEvent.press(screen.getByText('Follow'));

    await waitFor(() => {
      expect(api.followUser).toHaveBeenCalledWith('target-user');
    });

    fireEvent.press(screen.getByTestId('rider-detail-climb-7'));

    expect(mockNavigate).toHaveBeenCalledWith('ClimbDetail', {
      climbId: '11111111-1111-4111-8111-111111111111',
      backLabel: 'Rider',
    });
  });

  test('reports a public rider profile', async () => {
    const alertSpy = jest.spyOn(Alert, 'alert').mockImplementation((_title, _message, buttons) => {
      buttons?.find((button) => button.text === 'Report')?.onPress?.();
    });

    api.getPublicRiderProfile.mockResolvedValue(publicProfileBundle({}, {
      followState: {
        isFollowing: false,
        isFollowedBy: false,
        isMutualFollow: false,
      },
      leaderboard: {
        wallet: PUBLIC_RIDER.wallet,
        stats: {
          totalPositions: 0,
          komCount: 0,
          podiumCount: 0,
          top10Count: 0,
          totalVaultsCompleted: 0,
        },
        positions: [],
      },
    }));
    api.getMe.mockResolvedValue({
      id: 'viewer-user',
      wallet: 'ViewerWallet1111',
      username: 'viewer',
      displayName: 'Viewer',
      bio: null,
      avatarUrl: null,
      createdAt: '2026-04-24T00:00:00Z',
      totalRides: 1,
      totalTss: 10,
    });
    render(<RiderDetailScreen />);

    await waitFor(() => {
      expect(screen.getByTestId('rider-detail-report')).toBeTruthy();
    });

    fireEvent.press(screen.getByTestId('rider-detail-report'));

    await waitFor(() => {
      expect(api.reportSocialContent).toHaveBeenCalledWith(
        'user',
        'target-user',
        'other',
        'Reported from mobile rider profile',
      );
      expect(screen.getByText('Reported • open')).toBeTruthy();
    });

    alertSpy.mockRestore();
  });

  test('renders private profile without social modules', async () => {
    api.getPublicRiderProfile.mockResolvedValue(publicProfileBundle({
        displayName: null,
        bio: null,
        avatarUrl: null,
        isPublic: false,
        totalRides: 0,
        totalDistanceKm: 0,
        totalElevationM: 0,
      },
      {
        rider: {
          contractVersion: 'public_rider_ref.v1',
          id: PUBLIC_RIDER.id,
          username: PUBLIC_RIDER.username,
          displayName: null,
          avatarUrl: null,
          isPublic: false,
          viewerRelationship: 'none',
        },
        viewerCapabilities: {
          canView: false,
          canFollow: false,
          canReport: false,
          canShare: false,
          viewerRelationship: 'none',
        },
      },
    ));

    render(<RiderDetailScreen />);

    await waitFor(() => {
      expect(screen.getByText('Private Rider')).toBeTruthy();
    });

    expect(screen.getByText('This rider keeps their profile private.')).toBeTruthy();
    expect(api.getUserLeaderboardPositions).not.toHaveBeenCalled();
    expect(api.getFollowState).not.toHaveBeenCalled();
  });

  test('clears prior rider modules when the next profile load fails', async () => {
    api.getPublicRiderProfile
      .mockResolvedValueOnce(publicProfileBundle({}, {
        followState: {
          isFollowing: false,
          isFollowedBy: false,
          isMutualFollow: false,
        },
        leaderboard: {
          wallet: PUBLIC_RIDER.wallet,
          stats: {
            totalPositions: 1,
            komCount: 1,
            podiumCount: 1,
            top10Count: 1,
            totalVaultsCompleted: 1,
          },
          positions: [
            {
              vaultId: 7,
              vaultName: 'Manayunk Wall',
              vaultSignature: 'sig',
              rank: 1,
              bestTimeSeconds: 312,
              isKom: true,
              totalRiders: 42,
            },
          ],
        },
      }))
      .mockRejectedValueOnce(new ApiError('Missing rider', 'unknown', 404));
    api.getMe.mockResolvedValue({
      id: 'viewer-user',
      wallet: 'ViewerWallet1111',
      username: 'viewer',
      displayName: 'Viewer',
      bio: null,
      avatarUrl: null,
      createdAt: '2026-04-24T00:00:00Z',
      totalRides: 1,
      totalTss: 10,
    });
    const view = render(<RiderDetailScreen />);

    await waitFor(() => {
      expect(screen.getByText('Manayunk Wall')).toBeTruthy();
    });

    mockRouteParams = {
      identifier: 'MissingWallet2222',
      initialIdentity: { wallet: 'MissingWallet2222' },
      backLabel: 'Search',
    };
    view.rerender(<RiderDetailScreen />);

    await waitFor(() => {
      expect(screen.getByText('Rider profile not found')).toBeTruthy();
    });

    expect(screen.queryByText('Rolls hard.')).toBeNull();
    expect(screen.queryByText('Manayunk Wall')).toBeNull();
    expect(screen.queryByText('Record')).toBeNull();
  });

  test('clears prior top climbs when a later profile bundle omits leaderboard', async () => {
    const secondRider = {
      ...PUBLIC_RIDER,
      id: 'target-user-2',
      wallet: 'WalletBBBB2222',
      username: 'jane',
      displayName: 'Jane',
      bio: 'Fresh rider.',
    };

    api.getPublicRiderProfile
      .mockResolvedValueOnce(publicProfileBundle({}, {
        followState: {
          isFollowing: false,
          isFollowedBy: false,
          isMutualFollow: false,
        },
        leaderboard: {
          wallet: PUBLIC_RIDER.wallet,
          stats: {
            totalPositions: 1,
            komCount: 1,
            podiumCount: 1,
            top10Count: 1,
            totalVaultsCompleted: 1,
          },
          positions: [
            {
              vaultId: 7,
              vaultName: 'Manayunk Wall',
              vaultSignature: 'sig',
              rank: 1,
              bestTimeSeconds: 312,
              isKom: true,
              totalRiders: 42,
            },
          ],
        },
      }))
      .mockResolvedValueOnce(publicProfileBundle(secondRider, {
        followState: {
          isFollowing: false,
          isFollowedBy: false,
          isMutualFollow: false,
        },
        leaderboard: null,
      }));
    api.getMe.mockResolvedValue({
      id: 'viewer-user',
      wallet: 'ViewerWallet1111',
      username: 'viewer',
      displayName: 'Viewer',
      bio: null,
      avatarUrl: null,
      createdAt: '2026-04-24T00:00:00Z',
      totalRides: 1,
      totalTss: 10,
    });
    const view = render(<RiderDetailScreen />);

    await waitFor(() => {
      expect(screen.getByText('Manayunk Wall')).toBeTruthy();
    });

    mockRouteParams = {
      identifier: 'WalletBBBB2222',
      initialIdentity: { wallet: 'WalletBBBB2222' },
      backLabel: 'Search',
    };
    view.rerender(<RiderDetailScreen />);

    await waitFor(() => {
      expect(screen.getAllByText('Jane').length).toBeGreaterThan(0);
    });

    expect(screen.queryByText('Manayunk Wall')).toBeNull();
    expect(screen.queryByText('Top Climbs')).toBeNull();
  });
});
