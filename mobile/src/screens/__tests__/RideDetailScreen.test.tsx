import React from 'react';
import { Alert } from 'react-native';
import { fireEvent, render, waitFor } from '@testing-library/react-native';

import RideDetailScreen from '../RideDetailScreen';

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
      params: { rideId: 'ride-1', serverRideId: 'server-ride-1', backLabel: 'Home' },
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

jest.mock('../../services/database', () => ({
  getDatabase: jest.fn(),
  getRide: jest.fn(),
  getRideSamples: jest.fn(),
  getUploadEntryForRide: jest.fn(),
}));

jest.mock('../../services/authService', () => ({
  logout: jest.fn(),
}));

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

jest.mock('../../lib/api', () => ({
  api: {
    getRide: jest.fn(),
    getRideDetail: jest.fn(),
    getRideStatus: jest.fn(),
    getRideInteractions: jest.fn(),
    getRideComments: jest.fn(),
    addRideComment: jest.fn(),
    resolveLink: jest.fn(),
    giveRideKudos: jest.fn(),
    removeRideKudos: jest.fn(),
    updateRide: jest.fn(),
    reportSocialContent: jest.fn(),
    reprocessRide: jest.fn(),
  },
}));

jest.mock('../../lib/imageUpload', () => ({
  prepareNativeImageUpload: jest.fn(),
}));

const { getRide, getRideSamples, getUploadEntryForRide } = jest.requireMock('../../services/database') as {
  getRide: jest.Mock;
  getRideSamples: jest.Mock;
  getUploadEntryForRide: jest.Mock;
};

const { api } = jest.requireMock('../../lib/api') as {
  api: {
    getRide: jest.Mock;
    getRideDetail: jest.Mock;
    getRideStatus: jest.Mock;
    getRideInteractions: jest.Mock;
    getRideComments: jest.Mock;
    addRideComment: jest.Mock;
    resolveLink: jest.Mock;
    giveRideKudos: jest.Mock;
    removeRideKudos: jest.Mock;
    updateRide: jest.Mock;
    reportSocialContent: jest.Mock;
    reprocessRide: jest.Mock;
  };
};

describe('RideDetailScreen', () => {
  beforeEach(() => {
    jest.clearAllMocks();
    getUploadEntryForRide.mockReturnValue({
      id: 'upload-ride-1',
      ride_id: 'ride-1',
      status: 'uploaded',
      file_hash: null,
      attempt_count: 1,
      max_attempts: 3,
      next_retry_at: null,
      last_error: null,
      server_ride_id: 'server-ride-1',
      created_at: 0,
      updated_at: 0,
    });
    getRideSamples.mockReturnValue([
      { ride_id: 'ride-1', latitude: 39.95, longitude: -75.17 },
      { ride_id: 'ride-1', latitude: 39.96, longitude: -75.16 },
      { ride_id: 'ride-1', latitude: 39.97, longitude: -75.15 },
    ]);
    api.getRide.mockResolvedValue({
      id: 'server-ride-1',
      activityId: 'activity-1',
      startedAt: '2026-04-23T08:15:00.000Z',
      durationSec: 3600,
      distanceM: 40200,
      elevationGainM: 520,
      tss: 82,
      np: null,
      avgPowerW: null,
      source: 'native',
      visibility: 'public',
      privacy: { isOwner: false, visibility: 'public' },
      commentsEnabled: true,
      routePreview: {
        contractVersion: 'route_preview.v1',
        source: 'server_gps',
        points: [{ x: 0, y: 1 }, { x: 1, y: 0 }],
        pointCount: 2,
        placeLabel: 'Philadelphia, PA',
        fallbackReason: null,
        privacy: { redactedGps: false },
      },
    });
    api.getRideDetail.mockRejectedValue(new Error('legacy detail contract unavailable'));
    api.resolveLink.mockResolvedValue({
      contractVersion: 'link.v1',
      status: 'resolved',
      target: { type: 'ride', id: 'server-ride-1' },
      webPath: '/rides/server-ride-1',
      canonicalUrl: 'https://boulderroller.app/rides/server-ride-1',
      appUrl: 'boulderroller://rides/server-ride-1',
      title: 'Ride',
      description: 'Ride on Boulder Roller',
      access: { canView: true, reason: 'public', protocolPublic: true, requiresAuth: false },
      metadata: {},
      scanState: 'finalized',
      scanTargets: [
        {
          contractVersion: 'scan.v1',
          type: 'transaction',
          id: 'tx-server-ride-1',
          state: 'finalized',
          label: 'Transaction',
          url: 'https://scan.boulderroller.xyz/tx/tx-server-ride-1',
          source: 'ride.tx',
        },
      ],
      share: {
        title: 'Ride',
        text: 'Ride on Boulder Roller',
        url: 'https://boulderroller.app/rides/server-ride-1',
      },
      openGraph: {
        title: 'Ride',
        text: 'Ride on Boulder Roller',
        url: 'https://boulderroller.app/rides/server-ride-1',
        type: 'ride',
      },
    });
    api.getRideInteractions.mockResolvedValue({
      rideId: 'server-ride-1',
      kudosCount: 0,
      commentCount: 0,
      viewerHasKudos: false,
      viewerReported: false,
      reportStatus: null,
      commentsEnabled: true,
      canComment: true,
    });
    api.getRideComments.mockResolvedValue({ comments: [] });
  });

  test('renders climb matches and routes into climb detail', async () => {
    getRide.mockReturnValue({
      id: 'ride-1',
      status: 'completed',
      started_at: new Date('2026-04-23T08:15:00.000Z').getTime(),
      ended_at: null,
      duration_ms: 3_600_000,
      moving_time_ms: 3_300_000,
      distance_m: 40200,
      elevation_gain_m: 520,
      max_speed_mps: 15.2,
      sport_type: 'ride',
      clock_drift_ms: null,
      sample_count: 812,
      rejected_samples: null,
      upload_id: 'server-ride-1',
      notes: null,
      preliminary_ride_hash: null,
      parser_version: 1,
      had_crash_recovery: 0,
    });

    api.getRideStatus.mockResolvedValue({
      rideId: 'server-ride-1',
      status: 'completed',
      attestationStatus: 'attested',
      rideHashHex: 'abcdef0123456789',
      attestationCommitmentHex: '0123456789abcdef',
      rideAttestationTxSignature: 'txsig123456789',
      finalizedAt: '2026-04-23T09:00:00.000Z',
      hasPatterns: true,
      hasLeaderboards: true,
      hasAchievements: true,
      metrics: {
        tss: 82,
        distanceM: 40200,
        elevationGainM: 520,
        durationSec: 3600,
        avgPowerW: 241,
        normalizedPowerW: 258,
      },
      earnings: {
        contractVersion: 'client.v1',
        truthSource: 'projected',
        rideId: 'server-ride-1',
        calEarned: 47,
        finalizedAt: '2026-04-23T09:00:00.000Z',
      },
      climbEarnings: [
        {
          contractVersion: 'client.v1',
          truthSource: 'projected',
          rideId: 'server-ride-1',
          climbId: 'climb-1',
          climbName: 'Manayunk Wall',
          recordBoardRank: 6,
          completionTimeS: 312,
          calTribute: 47,
        },
      ],
    });

    const screen = render(<RideDetailScreen />);

    await waitFor(() => {
      expect(screen.getByText('Manayunk Wall')).toBeTruthy();
    });

    expect(screen.getAllByText('Ride').length).toBeGreaterThanOrEqual(1);
    expect(screen.getByTestId('ride-detail-route-preview')).toBeTruthy();
    expect(screen.getAllByText('Philadelphia, PA').length).toBeGreaterThanOrEqual(1);
    expect(screen.getAllByText('Status').length).toBeGreaterThanOrEqual(1);
    expect(screen.getAllByText('Verification').length).toBeGreaterThanOrEqual(1);
    expect(screen.getByText('Kudos, comments, share')).toBeTruthy();
    expect(screen.getAllByText('Climbs').length).toBeGreaterThanOrEqual(1);
    expect(screen.getByText('5m 12s')).toBeTruthy();
    expect(screen.getByText('Top 6')).toBeTruthy();
    expect(screen.getAllByText('Verified ride').length).toBeGreaterThanOrEqual(1);
    expect(screen.getByText('Verification complete.')).toBeTruthy();
    expect(screen.getAllByText('BoulderScan ready').length).toBeGreaterThanOrEqual(1);
    expect(screen.getByText('Open BoulderScan')).toBeTruthy();
    expect(screen.queryByText(/Proof account/i)).toBeNull();
    expect(screen.queryByText(/Ride proof/i)).toBeNull();
    expect(screen.queryByText(/on-chain/i)).toBeNull();

    fireEvent.press(screen.getByText('Manayunk Wall'));

    expect(mockNavigate).toHaveBeenCalledWith('ClimbDetail', {
      climbId: 'climb-1',
      backLabel: 'Ride',
    });
  });

  test('renders a held Threshold ride without counted-zero CAL', async () => {
    getRide.mockReturnValue({
      id: 'ride-1',
      status: 'completed',
      started_at: new Date('2026-04-23T08:15:00.000Z').getTime(),
      ended_at: null,
      duration_ms: 3_600_000,
      moving_time_ms: 3_300_000,
      distance_m: 40200,
      elevation_gain_m: 520,
      max_speed_mps: 15.2,
      sport_type: 'ride',
      clock_drift_ms: null,
      sample_count: 812,
      rejected_samples: null,
      upload_id: 'server-ride-1',
      notes: null,
      preliminary_ride_hash: null,
      parser_version: 1,
      had_crash_recovery: 0,
    });
    api.getRideStatus.mockResolvedValue({
      rideId: 'server-ride-1',
      status: 'completed',
      effortPolicy: {
        rewardPolicy: 'threshold_provisional_hold_v1',
        thresholdEconomyState: 'held',
      },
      metrics: {
        tss: null,
        distanceM: 40200,
        elevationGainM: 520,
        durationSec: 3600,
        avgPowerW: 241,
        normalizedPowerW: 258,
      },
      calEarned: null,
      earnings: null,
      climbEarnings: [],
    });

    const screen = render(<RideDetailScreen />);

    await waitFor(() => {
      expect(screen.getByText('Held — clears when your Threshold is established.')).toBeTruthy();
    });

    expect(screen.getAllByText('Held').length).toBeGreaterThanOrEqual(1);
    expect(screen.queryByText('Counted CAL')).toBeNull();
    expect(screen.queryByText('+0')).toBeNull();
  });

  test('marks scheduled-denominator ride TSS as Pending', async () => {
    getRide.mockReturnValue(null);
    api.getRideStatus.mockResolvedValue({
      rideId: 'server-ride-1',
      status: 'completed',
      metrics: {
        tss: 82,
        thresholdTrainingState: 'pending',
        distanceM: 40200,
        elevationGainM: 520,
        durationSec: 3600,
        avgPowerW: 241,
        normalizedPowerW: 258,
      },
      climbEarnings: [],
    });

    const screen = render(<RideDetailScreen />);

    await waitFor(() => {
      expect(screen.getByText('82 · Pending')).toBeTruthy();
    });
  });

  test('reports a server-backed ride and renders report state', async () => {
    const alertSpy = jest.spyOn(Alert, 'alert').mockImplementation((_title, _message, buttons) => {
      buttons?.find((button) => button.text === 'Report')?.onPress?.();
    });

    getRide.mockReturnValue({
      id: 'ride-1',
      status: 'completed',
      started_at: new Date('2026-04-23T08:15:00.000Z').getTime(),
      ended_at: null,
      duration_ms: 3_600_000,
      moving_time_ms: 3_300_000,
      distance_m: 40200,
      elevation_gain_m: 520,
      max_speed_mps: 15.2,
      sport_type: 'ride',
      clock_drift_ms: null,
      sample_count: 812,
      rejected_samples: null,
      upload_id: 'server-ride-1',
      notes: null,
      preliminary_ride_hash: null,
      parser_version: 1,
      had_crash_recovery: 0,
    });
    api.getRideStatus.mockResolvedValue({
      rideId: 'server-ride-1',
      status: 'completed',
      hasPatterns: false,
      hasLeaderboards: false,
      hasAchievements: false,
    });
    api.reportSocialContent.mockResolvedValue({
      id: 'report-1',
      reporterId: 'viewer-1',
      targetType: 'ride',
      targetId: 'server-ride-1',
      reason: 'other',
      status: 'open',
      createdAt: '2026-04-29T12:00:00Z',
    });

    const screen = render(<RideDetailScreen />);

    await waitFor(() => {
      expect(screen.getByTestId('ride-detail-report')).toBeTruthy();
    });

    fireEvent.press(screen.getByTestId('ride-detail-report'));

    await waitFor(() => {
      expect(api.reportSocialContent).toHaveBeenCalledWith(
        'ride',
        'server-ride-1',
        'other',
        'Reported from mobile ride detail',
      );
      expect(screen.getByText('Reported • open')).toBeTruthy();
    });

    alertSpy.mockRestore();
  });

  test('reports a ride comment and renders report state', async () => {
    const alertSpy = jest.spyOn(Alert, 'alert').mockImplementation((_title, _message, buttons) => {
      buttons?.find((button) => button.text === 'Report')?.onPress?.();
    });

    getRide.mockReturnValue({
      id: 'ride-1',
      status: 'completed',
      started_at: new Date('2026-04-23T08:15:00.000Z').getTime(),
      ended_at: null,
      duration_ms: 3_600_000,
      moving_time_ms: 3_300_000,
      distance_m: 40200,
      elevation_gain_m: 520,
      max_speed_mps: 15.2,
      sport_type: 'ride',
      clock_drift_ms: null,
      sample_count: 812,
      rejected_samples: null,
      upload_id: 'server-ride-1',
      notes: null,
      preliminary_ride_hash: null,
      parser_version: 1,
      had_crash_recovery: 0,
    });
    api.getRideStatus.mockResolvedValue({
      rideId: 'server-ride-1',
      status: 'completed',
      hasPatterns: false,
      hasLeaderboards: false,
      hasAchievements: false,
    });
    api.getRideComments.mockResolvedValue({
      comments: [
        {
	          id: 'comment-1',
	          userId: 'user-2',
	          author: {
	            contractVersion: 'public_rider_ref.v1',
	            id: 'user-2',
	            username: 'rider-two',
	            displayName: 'Rider',
	            avatarUrl: null,
	            isPublic: true,
	            viewerRelationship: 'none',
	          },
	          displayName: 'Rider',
          content: 'Nice climb',
          createdAt: '2026-04-29T12:00:00Z',
          viewerReported: false,
          reportStatus: null,
        },
      ],
    });
    api.reportSocialContent.mockResolvedValue({
      id: 'report-2',
      reporterId: 'viewer-1',
      targetType: 'comment',
      targetId: 'comment-1',
      reason: 'other',
      status: 'open',
      createdAt: '2026-04-29T12:00:00Z',
    });

    const screen = render(<RideDetailScreen />);

    await waitFor(() => {
      expect(screen.getByTestId('comment-report-comment-1')).toBeTruthy();
    });

    fireEvent.press(screen.getByTestId('comment-author-comment-1'));
    expect(mockNavigate).toHaveBeenCalledWith('RiderDetail', {
	      identifier: 'rider-two',
	      initialIdentity: {
	        contractVersion: 'public_rider_ref.v1',
	        id: 'user-2',
	        username: 'rider-two',
	        displayName: 'Rider',
	        avatarUrl: null,
	        isPublic: true,
	        viewerRelationship: 'none',
	      },
      backLabel: 'Ride',
    });

    fireEvent.press(screen.getByTestId('comment-report-comment-1'));

    await waitFor(() => {
      expect(api.reportSocialContent).toHaveBeenCalledWith(
        'comment',
        'comment-1',
        'other',
        'Reported from mobile ride comments',
      );
      expect(screen.getByText('Reported • open')).toBeTruthy();
    });

    alertSpy.mockRestore();
  });

  test('offers backend reprocessing when ride processing failed retryably', async () => {
    getRide.mockReturnValue({
      id: 'ride-1',
      status: 'uploaded',
      started_at: new Date('2026-04-23T08:15:00.000Z').getTime(),
      ended_at: null,
      duration_ms: 3_600_000,
      moving_time_ms: 3_300_000,
      distance_m: 40200,
      elevation_gain_m: 520,
      max_speed_mps: 15.2,
      sport_type: 'ride',
      clock_drift_ms: null,
      sample_count: 812,
      rejected_samples: null,
      upload_id: 'server-ride-1',
      notes: null,
      preliminary_ride_hash: null,
      parser_version: 1,
      had_crash_recovery: 0,
    });
    api.getRideStatus.mockResolvedValue({
      rideId: 'server-ride-1',
      status: 'failed',
      processingStage: 'failed',
      errorMessage: 'Processing queue timed out',
      canRetryProcessing: true,
      failure: {
        phase: 'processing',
        message: 'Processing queue timed out',
        retryable: true,
      },
      hasPatterns: false,
      hasLeaderboards: false,
      hasAchievements: false,
    });
    api.reprocessRide.mockResolvedValue({
      status: 'reprocessing',
      rideId: 'server-ride-1',
      message: 'Ride queued for reprocessing',
    });

    const screen = render(<RideDetailScreen />);

    await waitFor(() => {
      expect(screen.getByText('Processing queue timed out')).toBeTruthy();
    });

    fireEvent.press(screen.getByTestId('ride-detail-lifecycle-action'));

    await waitFor(() => {
      expect(api.reprocessRide).toHaveBeenCalledWith('server-ride-1');
    });
  });
});
