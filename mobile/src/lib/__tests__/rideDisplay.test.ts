import type {
  ResolvedLink,
  RideInteractions,
  RideStatus,
  RideSummary,
} from '../api';
import type { RoutePreview } from '../routePreview';
import type { RideRow } from '../../services/database';
import {
  buildRideDisplayModel,
  climbConsequenceLine,
  formatDurationSec,
  routeDisplayLabel,
  statusStepState,
} from '../rideDisplay';

const mappedRoute: RoutePreview = {
  contractVersion: 'route_preview.v1',
  source: 'server_gps',
  points: [{ x: 0, y: 1 }, { x: 1, y: 0 }],
  pointCount: 2,
  placeLabel: 'Philadelphia, PA',
  fallbackReason: null,
  privacy: { redactedGps: false },
};

const localRide: RideRow = {
  id: 'local-ride-1',
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

const serverRide: RideSummary = {
  id: 'server-ride-1',
  activityId: 'activity-1',
  startedAt: '2026-04-23T12:15:00.000Z',
  durationSec: 3_600,
  distanceM: 40_200,
  elevationGainM: 520,
  tss: 82,
  np: null,
  avgPowerW: null,
  source: 'native',
  visibility: 'followers',
  privacy: {
    visibility: 'followers',
    canView: true,
    isOwner: false,
    isFollower: true,
    redactGps: false,
    protocolPublic: true,
    protocolPublicFields: [],
    reason: 'followers',
  },
  commentsEnabled: true,
  routePreview: mappedRoute,
};

const serverStatus: RideStatus = {
  rideId: 'server-ride-1',
  status: 'completed',
  errorMessage: null,
  attestationStatus: 'attested',
  finalizedAt: '2026-04-23T13:20:00.000Z',
  hasPatterns: true,
  hasLeaderboards: true,
  metrics: {
    distanceM: 40_200,
    durationSec: 3_600,
    elevationGainM: 520,
    tss: 82,
    avgPowerW: 241,
    normalizedPowerW: 258,
  },
  earnings: {
    contractVersion: 'client.v1',
    truthSource: 'projected',
    rideId: 'server-ride-1',
    calEarned: 47,
    finalizedAt: '2026-04-23T13:20:00.000Z',
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
  description: 'Ride on Boulder Roller',
  access: { canView: true, reason: 'followers', protocolPublic: true, requiresAuth: false },
  metadata: {},
  scanState: 'pending',
  scanTargets: [
    {
      contractVersion: 'scan.v1',
      type: 'proof',
      id: 'proof-1',
      state: 'finalized',
      label: 'Ride proof',
      url: 'https://scan.boulderroller.xyz/proof/proof-1',
      source: 'backend',
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
};

const interactions: RideInteractions = {
  rideId: 'server-ride-1',
  kudosCount: 3,
  commentCount: 2,
  viewerHasKudos: false,
  commentsEnabled: true,
  canComment: true,
};

function factValue(model: ReturnType<typeof buildRideDisplayModel>, label: string): string {
  const fact = model.facts.find((item) => item.label === label);
  if (!fact) throw new Error(`Missing fact ${label}`);
  return fact.value;
}

describe('buildRideDisplayModel', () => {
  test('summarizes a server ride with route, privacy, status, and social state', () => {
    const model = buildRideDisplayModel({
      localRide: null,
      localRoutePreview: null,
      serverRide,
      serverStatus,
      resolvedLink,
      rideInteractions: interactions,
      targetServerRideId: 'server-ride-1',
    });

    expect(model.title).toMatch(/Ride$/);
    expect(model.subtitle).toContain('Philadelphia, PA');
    expect(model.routeLabel).toBe('Philadelphia, PA');
    expect(model.routePreview).toBe(mappedRoute);
    expect(factValue(model, 'Visibility')).toBe('Followers');
    expect(factValue(model, 'Verification')).toBe('BoulderScan ready');
    expect(factValue(model, 'Social')).toBe('Kudos, comments, share');
    expect(model.summaryStats).toEqual([
      { label: 'Distance', value: '40.2 km' },
      { label: 'Duration', value: '1h 0m 0s' },
      { label: 'Elevation', value: '520 m' },
      { label: 'TSS', value: '82' },
    ]);
  });

  test('preserves device-only rides and labels non-server actions honestly', () => {
    const model = buildRideDisplayModel({
      localRide,
      localRoutePreview: { ...mappedRoute, placeLabel: null },
      serverRide: null,
      serverStatus: null,
      resolvedLink: null,
      rideInteractions: null,
      targetServerRideId: null,
    });

    expect(model.routeLabel).toBe('Mapped route');
    expect(factValue(model, 'Visibility')).toBe('Device only');
    expect(factValue(model, 'Verification')).toBe('Device only');
    expect(factValue(model, 'Social')).toBe('Device only');
    expect(model.summaryStats).toContainEqual({ label: 'Avg Speed', value: '43.9 km/h' });
  });

  test('uses server route preview over local preview when both are present', () => {
    const localRoute = { ...mappedRoute, placeLabel: 'Local route' };
    const model = buildRideDisplayModel({
      localRide,
      localRoutePreview: localRoute,
      serverRide,
      serverStatus,
      resolvedLink: null,
      rideInteractions: null,
      targetServerRideId: 'server-ride-1',
    });

    expect(model.routePreview).toBe(mappedRoute);
    expect(model.routeLabel).toBe('Philadelphia, PA');
  });
});

describe('ride display copy helpers', () => {
  test('labels route preview fallbacks for privacy and missing GPS', () => {
    expect(routeDisplayLabel({
      ...mappedRoute,
      points: [],
      pointCount: 0,
      placeLabel: null,
      fallbackReason: 'privacy_redacted',
    })).toBe('Private route');

    expect(routeDisplayLabel({
      ...mappedRoute,
      points: [],
      pointCount: 0,
      placeLabel: null,
      fallbackReason: 'missing_gps',
    })).toBe('No GPS preview');
  });

  test('keeps climb and status grammar deterministic', () => {
    expect(formatDurationSec(312)).toBe('5m 12s');
    expect(climbConsequenceLine({
      contractVersion: 'client.v1',
      truthSource: 'projected',
      rideId: 'server-ride-1',
      climbId: 'climb-1',
      recordBoardRank: 6,
    })).toBe('Top 6');

    expect(climbConsequenceLine({
      contractVersion: 'client.v1',
      truthSource: 'onchain',
      rideId: 'server-ride-1',
      climbId: 'climb-v2',
      calTribute: 104,
      completionEvidenceVersion: 2,
      tributeBound: true,
    })).toBe('+104 CAL');

    expect(climbConsequenceLine({
      contractVersion: 'client.v1',
      truthSource: 'onchain',
      rideId: 'server-ride-1',
      climbId: 'climb-v1',
      calTribute: 104,
      completionEvidenceVersion: 1,
      tributeBound: false,
    })).toBe('Open climb');

    expect(statusStepState(null, 'saved')).toBe('done');
    expect(statusStepState(serverStatus, 'climbs')).toBe('done');
    expect(statusStepState(serverStatus, 'paid')).toBe('done');

    const heldStatus: RideStatus = {
      ...serverStatus,
      calEarned: null,
      earnings: null,
      effortPolicy: {
        rewardPolicy: 'threshold_provisional_hold_v1',
        thresholdEconomyState: 'held',
      },
      metrics: {
        ...serverStatus.metrics!,
        thresholdTrainingState: 'pending',
      },
    };
    expect(statusStepState(heldStatus, 'paid')).toBe('pending');
    expect(buildRideDisplayModel({
      localRide: null,
      localRoutePreview: null,
      serverRide,
      serverStatus: heldStatus,
      resolvedLink,
      rideInteractions: interactions,
      targetServerRideId: serverRide.id,
    }).summaryStats.find((stat) => stat.label === 'TSS')?.value).toBe('82 · Pending');
  });
});
