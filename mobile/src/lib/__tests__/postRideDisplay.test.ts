import type { ResolvedLink, RideStatus } from '../api';
import type { RideRow } from '../../services/database';
import {
  buildPostRideDisplayModel,
  buildPostRideUploadMessage,
  formatPostRideSpeed,
} from '../postRideDisplay';

const localRide: RideRow = {
  id: 'ride-1',
  status: 'completed',
  started_at: new Date('2026-04-23T12:15:00.000Z').getTime(),
  ended_at: null,
  duration_ms: 3_600_000,
  moving_time_ms: 3_300_000,
  distance_m: 40_200,
  elevation_gain_m: 520,
  max_speed_mps: 15.2,
  sport_type: 'ride',
  clock_drift_ms: null,
  sample_count: 812,
  rejected_samples: null,
  upload_id: null,
  notes: null,
  preliminary_ride_hash: null,
  parser_version: 1,
  had_crash_recovery: 0,
};

const completedStatus: RideStatus = {
  rideId: 'server-ride-1',
  status: 'completed',
  errorMessage: null,
  attestationStatus: 'attested',
  metrics: {
    tss: 82,
    kcals: null,
    distanceM: 40_200,
    elevationGainM: 520,
    durationSec: 3_600,
    avgPowerW: null,
    normalizedPowerW: null,
  },
  earnings: {
    contractVersion: 'client.v1',
    truthSource: 'onchain',
    rideId: 'server-ride-1',
    calEarned: 47,
  },
};

const resolvedLink: ResolvedLink = {
  contractVersion: 'link.v1',
  status: 'resolved',
  target: { type: 'ride', id: 'server-ride-1' },
  webPath: '/rides/server-ride-1',
  canonicalUrl: 'https://boulderroller.app/rides/server-ride-1',
  appUrl: 'boulderroller://rides/server-ride-1',
  title: 'Ride',
  description: 'Ride on Boulder Roller.',
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
    text: 'Ride on Boulder Roller.',
    url: 'https://boulderroller.app/rides/server-ride-1',
  },
  openGraph: {
    title: 'Ride',
    text: 'Ride on Boulder Roller.',
    url: 'https://boulderroller.app/rides/server-ride-1',
    type: 'ride',
  },
};

describe('buildPostRideDisplayModel', () => {
  test('summarizes a completed post-ride state without proof copy', () => {
    const model = buildPostRideDisplayModel({
      localRide,
      serverStatus: completedStatus,
      uploadState: 'uploaded',
      serverRideId: 'server-ride-1',
      resolvedLink,
      isIncomplete: false,
    });

    expect(model.headerTitle).toBe('Ride Complete');
    expect(model.uploadMessage).toEqual({
      text: 'Ride ready',
      tone: 'success',
      showSpinner: false,
    });
    expect(model.summaryRows).toEqual([
      [
        { label: 'Distance', value: '40.2 km' },
        { label: 'Duration', value: '1h 0m 0s' },
      ],
      [
        { label: 'Elevation', value: '520 m' },
        { label: 'Avg Speed', value: '43.9 km/h' },
      ],
      [
        { label: 'Max Speed', value: '54.7 km/h' },
        { label: 'GPS', value: '812' },
      ],
    ]);
    expect(model.earnings).toEqual({
      value: '+47',
      label: 'Counted CAL',
    });
    expect(model.action).toEqual({
      title: 'BoulderScan ready',
      boulderScanCtaLabel: 'Open BoulderScan',
    });
  });

  test('shows the approved Held state instead of dropping completed CAL', () => {
    const model = buildPostRideDisplayModel({
      localRide,
      serverStatus: {
        ...completedStatus,
        earnings: null,
        calEarned: null,
        effortPolicy: {
          rewardPolicy: 'threshold_provisional_hold_v1',
          thresholdEconomyState: 'held',
        },
      },
      uploadState: 'uploaded',
      serverRideId: 'server-ride-1',
      resolvedLink,
      isIncomplete: false,
    });

    expect(model.earnings).toEqual({
      value: 'Held',
      label: 'Held — clears when your Threshold is established.',
    });
  });

  test('keeps incomplete recordings as device-only display state', () => {
    const model = buildPostRideDisplayModel({
      localRide,
      serverStatus: null,
      uploadState: 'uploading',
      serverRideId: null,
      resolvedLink: null,
      isIncomplete: true,
      incompleteReason: 'Not enough movement to score.',
    });

    expect(model.headerTitle).toBe('Recording Saved');
    expect(model.uploadMessage).toEqual({
      text: 'Not enough movement to score. Kept on this device and not counted.',
      tone: 'default',
      showSpinner: false,
    });
    expect(model.earnings).toBeNull();
    expect(model.action).toBeNull();
  });

  test('does not show a BoulderScan button without an exact scan target', () => {
    const model = buildPostRideDisplayModel({
      localRide,
      serverStatus: completedStatus,
      uploadState: 'uploaded',
      serverRideId: 'server-ride-1',
      resolvedLink: {
        ...resolvedLink,
        scanTargets: [],
      },
      isIncomplete: false,
    });

    expect(model.action).toEqual({
      title: 'BoulderScan ready',
      boulderScanCtaLabel: null,
    });
  });
});

describe('post-ride display helpers', () => {
  test('formats upload status and speed without unit loss', () => {
    expect(buildPostRideUploadMessage({
      localRide,
      isIncomplete: false,
      uploadState: 'uploading',
      serverStatus: null,
    })).toEqual({
      text: 'Saving ride...',
      tone: 'default',
      showSpinner: true,
    });
    expect(buildPostRideUploadMessage({
      localRide,
      isIncomplete: false,
      uploadState: 'failed',
      serverStatus: null,
    })?.text).toBe('Upload paused. The app will retry automatically.');
    expect(formatPostRideSpeed(1000, 0)).toBe('0.0 km/h');
  });

  test('shows pre-economy import copy before live CAL processing', () => {
    const historicalRide: RideRow = {
      ...localRide,
      started_at: new Date('2015-06-26T09:00:00.000Z').getTime(),
      ended_at: new Date('2015-06-26T12:00:00.000Z').getTime(),
    };

    expect(buildPostRideUploadMessage({
      localRide: historicalRide,
      isIncomplete: false,
      uploadState: 'uploading',
      serverStatus: null,
    })).toEqual({
      text: 'Saving for analysis. This activity predates live CAL and can be imported, but CAL and DUNG will not count.',
      tone: 'default',
      showSpinner: true,
    });
  });
});
