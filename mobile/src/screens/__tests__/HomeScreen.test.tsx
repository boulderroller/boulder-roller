import React from 'react';
import { fireEvent, render, waitFor, act } from '@testing-library/react-native';

import HomeScreen from '../HomeScreen';
import { useAuthStore } from '../../stores/authStore';
import { loadLocalRides, type LocalRideSummary } from '../../lib/rides';

let focusEffectCallback: (() => void | (() => void)) | null = null;
const mockNavigate = jest.fn();

jest.mock('@expo/vector-icons/Feather', () => {
  const React = require('react');
  const { Text } = require('react-native');
  return function FeatherMock({ name }: { name: string }) {
    return React.createElement(Text, null, name);
  };
});

jest.mock('react-native-svg', () => {
  const React = require('react');
  const { View } = require('react-native');
  const SvgMock = ({ children, testID }: { children?: React.ReactNode; testID?: string }) => (
    React.createElement(View, { testID }, children)
  );
  const NodeMock = ({ children }: { children?: React.ReactNode }) => React.createElement(View, null, children);
  return {
    __esModule: true,
    default: SvgMock,
    Circle: NodeMock,
    Line: NodeMock,
    Path: NodeMock,
  };
});

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
      focusEffectCallback = callback;
      React.useEffect(() => callback(), [callback]);
    },
  };
});

jest.mock('../../services/database', () => ({
  getDatabase: jest.fn(() => ({ kind: 'mock-db' })),
}));

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
      getMe: jest.fn(),
      getRides: jest.fn(),
      getFeed: jest.fn(),
      getGlobalFeed: jest.fn(),
      getHomeFeed: jest.fn(),
      getNotifications: jest.fn(),
    },
  };
});

jest.mock('../../lib/rides', () => {
  const actual = jest.requireActual('../../lib/rides');
  return {
    ...actual,
    loadLocalRides: jest.fn(),
  };
});

const mockLoadLocalRides = loadLocalRides as jest.MockedFunction<typeof loadLocalRides>;
const { api } = jest.requireMock('../../lib/api') as {
  api: {
    getMe: jest.Mock;
    getRides: jest.Mock;
    getFeed: jest.Mock;
    getGlobalFeed: jest.Mock;
    getHomeFeed: jest.Mock;
    getNotifications: jest.Mock;
  };
};

function makeLocalRide(id: string, startedAt: number, distanceM: number): LocalRideSummary {
  return {
    id,
    startedAt,
    status: 'uploaded',
    durationMs: 1_800_000,
    movingTimeMs: 1_700_000,
    distanceM,
    elevationGainM: 240,
    maxSpeedMps: 10,
    sampleCount: 120,
    uploadId: `upload-${id}`,
    serverRideId: null,
    uploaded: true,
    uploadStatus: 'uploaded',
    uploadLastError: null,
    uploadAttemptCount: 0,
    rejectedSamples: null,
    hadCrashRecovery: false,
    routePreview: {
      contractVersion: 'route_preview.v1',
      source: 'local_gps',
      points: [{ x: 0, y: 1 }, { x: 1, y: 0 }],
      pointCount: 2,
      placeLabel: null,
      fallbackReason: null,
      privacy: { redactedGps: false },
    },
  };
}

describe('HomeScreen', () => {
  beforeEach(() => {
    jest.clearAllMocks();
    focusEffectCallback = null;
    useAuthStore.getState().setUnauthenticated();
    api.getFeed.mockResolvedValue({ activities: [], unreadCount: 0 });
    api.getGlobalFeed.mockResolvedValue({ activities: [], unreadCount: 0 });
    api.getHomeFeed.mockResolvedValue({
      feed: { activities: [] },
      notifications: { unreadCount: 0 },
    });
    api.getNotifications.mockResolvedValue({ notifications: [], unreadCount: 0 });
  });

  test('frames the authenticated empty Mine tab as first-ride readiness', async () => {
    useAuthStore.getState().setAuthenticated({
      wallet: 'wallet-1',
      accessToken: 'access-token',
      tokenExpiresAt: new Date('2026-04-23T12:00:00.000Z').getTime(),
      authMethod: 'privy',
    });
    mockLoadLocalRides.mockReturnValue([]);
    api.getMe.mockResolvedValue({
      wallet: 'wallet-1',
      username: null,
      displayName: 'Local Rider',
      bio: null,
      avatarUrl: null,
      createdAt: '2026-04-23T00:00:00.000Z',
      totalRides: 0,
      totalTss: 0,
      level: 1,
    });
    api.getRides.mockResolvedValue([]);

    const screen = render(<HomeScreen />);

    await waitFor(() => {
      expect(screen.getByText('Following')).toBeTruthy();
    });
    fireEvent.press(screen.getByText('Mine'));

    expect(screen.getByText('Ready for your first ride')).toBeTruthy();
    expect(screen.getByText('Open Record when you are ready. Your rides stay on this device until they sync.')).toBeTruthy();
  });

  test('preserves local ride history under the Mine source when the screen regains focus', async () => {
    useAuthStore.getState().setAuthenticated({
      wallet: 'wallet-1',
      accessToken: 'access-token',
      tokenExpiresAt: new Date('2026-04-23T12:00:00.000Z').getTime(),
      authMethod: 'privy',
    });
    const firstRideStartedAt = new Date(2026, 3, 23, 9, 0, 0).getTime();
    const secondRideStartedAt = new Date(2026, 3, 23, 18, 30, 0).getTime();

    mockLoadLocalRides
      .mockReturnValueOnce([makeLocalRide('ride-0', firstRideStartedAt, 1111)])
      .mockReturnValueOnce([makeLocalRide('ride-1', firstRideStartedAt, 1234)])
      .mockReturnValueOnce([makeLocalRide('ride-2', secondRideStartedAt, 2456)]);
    api.getMe.mockResolvedValue({
      wallet: 'wallet-1',
      username: null,
      displayName: 'Local Rider',
      bio: null,
      avatarUrl: null,
      createdAt: '2026-04-23T00:00:00.000Z',
      totalRides: 1,
      totalTss: 0,
      level: 1,
    });
    api.getRides.mockResolvedValue([]);

    const screen = render(<HomeScreen />);

    await waitFor(() => {
      expect(screen.getByText('Following')).toBeTruthy();
    });
    expect(screen.getByTestId('segmented-following').props.accessibilityState).toMatchObject({
      selected: true,
    });
    fireEvent.press(screen.getByText('Mine'));

    await waitFor(() => {
      expect(screen.getByText('1.2 km • 30:00')).toBeTruthy();
    });

    expect(screen.getByText('Home')).toBeTruthy();
    expect(screen.getByTestId('home-utility-search')).toBeTruthy();
    expect(screen.getByTestId('home-utility-alerts')).toBeTruthy();
    expect(screen.getByText('Rolling boulders')).toBeTruthy();
    expect(screen.getAllByText('Local Rider').length).toBeGreaterThan(0);
    expect(screen.getByText('Mine')).toBeTruthy();
    expect(screen.getByText(/recorded a ride on this device/)).toBeTruthy();
    expect(screen.getByText('Total climbing')).toBeTruthy();
    expect(screen.getByText('TSS')).toBeTruthy();
    expect(screen.getAllByTestId('route-preview-svg').length).toBeGreaterThan(0);
    expect(screen.getByText('Route preview')).toBeTruthy();

    expect(screen.queryByText('2.5 km • 30:00')).toBeNull();
    expect(focusEffectCallback).not.toBeNull();

    await act(async () => {
      focusEffectCallback?.();
    });

    await waitFor(() => {
      expect(screen.getByText('2.5 km • 30:00')).toBeTruthy();
    });
  });

  test('surfaces stuck local uploads as repairable ride cards', async () => {
    useAuthStore.getState().setAuthenticated({
      wallet: 'wallet-1',
      accessToken: 'access-token',
      tokenExpiresAt: new Date('2026-04-23T12:00:00.000Z').getTime(),
      authMethod: 'privy',
    });
    const localRide = makeLocalRide('ride-failed', new Date(2026, 3, 23, 9, 0, 0).getTime(), 1800);
    mockLoadLocalRides.mockReturnValue([{
      ...localRide,
      status: 'stopped',
      uploaded: false,
      uploadStatus: 'failed_retryable',
      uploadLastError: 'Network dropped during upload',
      uploadAttemptCount: 2,
    }]);
    api.getMe.mockResolvedValue({
      wallet: 'wallet-1',
      username: null,
      displayName: 'Local Rider',
      bio: null,
      avatarUrl: null,
      createdAt: '2026-04-23T00:00:00.000Z',
      totalRides: 1,
      totalTss: 0,
      level: 1,
    });
    api.getRides.mockResolvedValue([]);

    const screen = render(<HomeScreen />);

    await waitFor(() => {
      expect(screen.getByText('Following')).toBeTruthy();
    });
    fireEvent.press(screen.getByText('Mine'));

    await waitFor(() => {
      expect(screen.getByText(/has a ride waiting: retry upload/i)).toBeTruthy();
    });
  });

  test('renders Following feed cards from the canonical activity display model', async () => {
    useAuthStore.getState().setAuthenticated({
      wallet: 'wallet-1',
      accessToken: 'access-token',
      tokenExpiresAt: new Date('2026-04-23T12:00:00.000Z').getTime(),
      authMethod: 'privy',
    });
    mockLoadLocalRides.mockReturnValue([]);
    api.getMe.mockResolvedValue({
      wallet: 'wallet-1',
      username: null,
      displayName: 'Viewer',
      bio: null,
      avatarUrl: null,
      createdAt: '2026-04-23T00:00:00.000Z',
      totalRides: 0,
      totalTss: 0,
      level: 1,
    });
    api.getHomeFeed.mockResolvedValue({
      feed: {
        activities: [
        {
          contractVersion: 'feed.v1',
          id: 'feed-ride-1',
          type: 'ride',
          eventType: 'ride_completed',
          title: 'Morning Ride',
          createdAt: '2026-04-30T12:00:00.000Z',
          occurredAt: '2026-04-30T12:00:00.000Z',
          actor: {
            id: 'rider-1',
            username: 'dung-beetle-phoenix',
            displayName: null,
            avatarUrl: null,
          },
          target: { type: 'ride', id: 'server-ride-1' },
          metadata: {
            distanceM: 121_300,
            durationS: 16_168,
            climbCount: 8,
            elevationM: 1707,
            calEarned: 45,
            dungEarned: 2,
            tss: 82,
            kudosCount: 3,
            commentCount: 2,
            viewerHasKudos: true,
            routePreview: {
              contractVersion: 'route_preview.v1',
              source: 'server_gps',
              points: [{ x: 0, y: 1 }, { x: 1, y: 0 }],
              pointCount: 2,
              placeLabel: 'Philadelphia, PA',
              fallbackReason: null,
              privacy: { redactedGps: false },
            },
          },
        },
        ],
      },
      notifications: { unreadCount: 0 },
    });

    const screen = render(<HomeScreen />);

    await waitFor(() => {
      expect(screen.getByTestId('feed-event-feed-ride-1')).toBeTruthy();
    });

    expect(screen.getByText('Rolling boulders')).toBeTruthy();
    expect(screen.getAllByText('@dung-beetle-phoenix').length).toBeGreaterThan(0);
    expect(screen.getByText('121.3 km • 4:29:28')).toBeTruthy();
    expect(screen.getByText('8')).toBeTruthy();
    expect(screen.getByText('CAL')).toBeTruthy();
    expect(screen.getByText('DUNG')).toBeTruthy();
    expect(screen.getByText('TSS')).toBeTruthy();
    expect(screen.getByText('+45')).toBeTruthy();
    expect(screen.getByText('+2')).toBeTruthy();
    expect(screen.getByText('82')).toBeTruthy();
    expect(screen.getByText(/finished a ride with 8 climbs, \+45 CAL, \+2 DUNG, and 82 TSS/)).toBeTruthy();
    expect(screen.getByText('Philadelphia, PA')).toBeTruthy();
    expect(screen.getByText('3')).toBeTruthy();
    expect(screen.getByText('2')).toBeTruthy();

    fireEvent.press(screen.getByTestId('feed-event-feed-ride-1-actor'));
    expect(mockNavigate).toHaveBeenCalledWith('RiderDetail', {
      identifier: 'dung-beetle-phoenix',
      initialIdentity: {
        id: 'rider-1',
        username: 'dung-beetle-phoenix',
        displayName: null,
        avatarUrl: null,
        isPublic: undefined,
      },
      backLabel: 'Home',
    });

    mockNavigate.mockClear();
    fireEvent.press(screen.getByTestId('feed-event-feed-ride-1-body'));
    expect(mockNavigate).toHaveBeenCalledWith('RideDetail', {
      serverRideId: 'server-ride-1',
      backLabel: 'Home',
    });
  });

  test('clears prior Following feed cards when auth becomes unauthenticated', async () => {
    useAuthStore.getState().setAuthenticated({
      wallet: 'wallet-1',
      accessToken: 'access-token',
      tokenExpiresAt: new Date('2026-04-23T12:00:00.000Z').getTime(),
      authMethod: 'privy',
    });
    mockLoadLocalRides.mockReturnValue([]);
    api.getMe.mockResolvedValue({
      wallet: 'wallet-1',
      username: null,
      displayName: 'Viewer',
      bio: null,
      avatarUrl: null,
      createdAt: '2026-04-23T00:00:00.000Z',
      totalRides: 0,
      totalTss: 0,
      level: 1,
    });
    api.getHomeFeed.mockResolvedValueOnce({
      feed: {
        activities: [
        {
          contractVersion: 'feed.v1',
          id: 'feed-stale-1',
          type: 'ride',
          eventType: 'ride_completed',
          title: 'Morning Ride',
          createdAt: '2026-04-30T12:00:00.000Z',
          occurredAt: '2026-04-30T12:00:00.000Z',
          actor: {
            id: 'rider-1',
            username: 'dung-beetle-phoenix',
            displayName: null,
            avatarUrl: null,
          },
          target: { type: 'ride', id: 'server-ride-1' },
          metadata: {
            distanceM: 121_300,
            durationS: 16_168,
            climbCount: 8,
            elevationM: 1707,
            calEarned: 45,
          },
        },
        ],
      },
      notifications: { unreadCount: 0 },
    });

    const screen = render(<HomeScreen />);

    await waitFor(() => {
      expect(screen.getByTestId('feed-event-feed-stale-1')).toBeTruthy();
    });

    await act(async () => {
      useAuthStore.getState().setUnauthenticated();
    });

    await waitFor(() => {
      expect(screen.getByText('Welcome to Boulder Roller')).toBeTruthy();
    });
    expect(screen.queryByTestId('feed-event-feed-stale-1')).toBeNull();
    expect(screen.queryByText('Rolling boulders')).toBeNull();
  });

  test('does not render NaN when server ride metrics are missing', async () => {
    useAuthStore.getState().setAuthenticated({
      wallet: 'wallet-1',
      accessToken: 'access-token',
      tokenExpiresAt: new Date('2026-04-23T12:00:00.000Z').getTime(),
      authMethod: 'privy',
    });
    mockLoadLocalRides.mockReturnValue([]);
    api.getMe.mockResolvedValue({
      id: 'viewer-user-1',
      wallet: 'wallet-1',
      username: 'tim',
      displayName: null,
      bio: null,
      avatarUrl: null,
      createdAt: '2026-04-23T00:00:00.000Z',
      totalRides: 1,
      totalTss: 0,
      level: 1,
    });
    api.getHomeFeed.mockResolvedValue({ feed: { activities: [] }, notifications: { unreadCount: 0 } });
    api.getRides.mockResolvedValue([
      {
        id: 'server-ride-1',
        activityId: 'activity-1',
        startedAt: '2026-04-23T14:15:00.000Z',
        durationSec: undefined,
        distanceM: 0,
        elevationGainM: undefined,
        tss: undefined,
        np: null,
        avgPowerW: null,
        source: 'strava',
      },
    ]);

    const screen = render(<HomeScreen />);

    await waitFor(() => {
      expect(screen.getByText('Following')).toBeTruthy();
    });
    fireEvent.press(screen.getByText('Mine'));

    await waitFor(() => {
      expect(screen.getByText('Incomplete recording')).toBeTruthy();
    });

    expect(screen.queryByText(/NaN/)).toBeNull();
    expect(screen.queryByText('Rolling boulders')).toBeNull();
    expect(screen.getByText('Not enough movement to score')).toBeTruthy();
    expect(screen.getByText(/incomplete recording/)).toBeTruthy();
    expect(screen.getAllByText('@tim').length).toBeGreaterThan(0);
    expect(screen.getAllByText('—').length).toBeGreaterThan(0);

    fireEvent.press(screen.getByTestId('ride-card-srv:server-ride-1-actor'));
    expect(mockNavigate).toHaveBeenCalledWith('RiderDetail', {
      identifier: 'tim',
      initialIdentity: {
        id: 'viewer-user-1',
        username: 'tim',
        displayName: null,
        avatarUrl: null,
        isPublic: undefined,
      },
      backLabel: 'Home',
    });
  });
});
