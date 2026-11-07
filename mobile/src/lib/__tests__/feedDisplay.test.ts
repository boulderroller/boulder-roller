import type { FeedActivity } from '../api';
import type { MergedRide } from '../rides';
import type { RoutePreview } from '../routePreview';
import {
  buildFeedActivityCardDisplay,
  buildRideFeedCardDisplay,
  formatFeedDuration,
  targetFromFeedActivity,
} from '../feedDisplay';

const routePreview: RoutePreview = {
  contractVersion: 'route_preview.v1',
  source: 'server_gps',
  points: [{ x: 0, y: 1 }, { x: 1, y: 0 }],
  pointCount: 2,
  placeLabel: 'Philadelphia, PA',
  fallbackReason: null,
  privacy: { redactedGps: false },
};

const mergedRide: MergedRide = {
  key: 'ride-1',
  source: 'local',
  localRideId: 'ride-1',
  serverRideId: null,
  startedAtMs: new Date('2026-04-30T12:00:00.000Z').getTime(),
  startedAtIso: '2026-04-30T12:00:00.000Z',
  distanceM: 121_300,
  elevationGainM: 1707,
  durationSec: 16_168,
  tss: null,
  localStatus: 'uploaded',
  localSampleCount: 120,
  localRejectedSamples: null,
  hadCrashRecovery: false,
  uploadStatus: 'uploaded',
  uploadLastError: null,
  uploadAttemptCount: 1,
  routePreview,
};

const rideActivity: FeedActivity = {
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
    routePreview,
    kudosCount: 3,
    commentCount: 2,
    viewerHasKudos: true,
  },
};

describe('buildRideFeedCardDisplay', () => {
  test('keeps local Mine rides in the Corey mock grammar', () => {
    const card = buildRideFeedCardDisplay({
      ride: mergedRide,
      viewer: { displayName: 'Dung-beetle-phoenix' },
    });

    expect(card.actorLabel).toBe('Dung-beetle-phoenix');
    expect(card.actorIdentity).toMatchObject({ displayName: 'Dung-beetle-phoenix' });
    expect(card.title).toBe('Rolling boulders');
    expect(card.summaryLine).toBe('121.3 km • 4:29:28');
    expect(card.stats).toEqual([
      { label: 'Climbs', value: '—' },
      { label: 'Total climbing', value: '1707 m' },
      { label: 'TSS', value: '—' },
    ]);
    expect(card.impactItems).toEqual(['recorded a ride on this device.']);
    expect(card.routePreview).toBe(routePreview);
  });

  test('labels incomplete ride artifacts instead of emitting NaN metrics', () => {
    const card = buildRideFeedCardDisplay({
      ride: {
        ...mergedRide,
        distanceM: undefined as unknown as number,
        durationSec: undefined as unknown as number,
        elevationGainM: undefined as unknown as number,
        localStatus: 'incomplete',
      },
      viewer: { username: 'tim' },
    });

    expect(card.actorLabel).toBe('@tim');
    expect(card.title).toBe('Incomplete recording');
    expect(card.summaryLine).toBe('Not enough movement to score');
    expect(card.stats.map((item) => item.value)).toEqual(['—', '—', '—']);
  });
});

describe('buildFeedActivityCardDisplay', () => {
  test('renders ride feed activities with stats, route, counts, and impact copy', () => {
    const card = buildFeedActivityCardDisplay(rideActivity);

    expect(card.actorLabel).toBe('@dung-beetle-phoenix');
    expect(card.actorIdentity).toEqual({
      id: 'rider-1',
      username: 'dung-beetle-phoenix',
      displayName: null,
      avatarUrl: null,
      isPublic: undefined,
    });
    expect(card.title).toBe('Rolling boulders');
    expect(card.locationLabel).toBe('Philadelphia, PA');
    expect(card.summaryLine).toBe('121.3 km • 4:29:28');
    expect(card.stats).toEqual([
      { label: 'Climbs', value: '8' },
      { label: 'CAL', value: '+45' },
      { label: 'DUNG', value: '+2' },
      { label: 'TSS', value: '82' },
    ]);
    expect(card.impactItems).toEqual(['finished a ride with 8 climbs, +45 CAL, +2 DUNG, and 82 TSS.']);
    expect(card.kudosCount).toBe(3);
    expect(card.commentCount).toBe(2);
    expect(card.viewerHasKudos).toBe(true);
    expect(card.target).toMatchObject({ type: 'ride', id: 'server-ride-1' });
  });

  test('uses athletic achievement copy for leaderboard, legend, and vault events', () => {
    expect(buildFeedActivityCardDisplay({
      ...rideActivity,
      id: 'rank-1',
      type: 'record',
      eventType: 'record_rank_moved',
      target: { type: 'climb', id: 'climb-1' },
      metadata: { rank: 3, climbName: 'Saw Mill Rd.' },
    }).impactItems).toEqual(['moved to #3 on Saw Mill Rd.']);

    expect(buildFeedActivityCardDisplay({
      ...rideActivity,
      id: 'legend-1',
      type: 'local_legend',
      eventType: 'local_legend_moved',
      target: { type: 'climb', id: 'climb-1' },
      metadata: { climbName: 'Rose Glen' },
    }).impactItems).toEqual(['became Local Legend on Rose Glen.']);

    expect(buildFeedActivityCardDisplay({
      ...rideActivity,
      id: 'vault-1',
      type: 'vault_created',
      eventType: undefined,
      target: { type: 'climb', id: 'climb-1' },
      metadata: { climbName: 'Saw Mill Rd.' },
    }).impactItems).toEqual(['created a new vault on Saw Mill Rd.']);
  });

  test('does not expose wallet fallback text on feed cards', () => {
    const card = buildRideFeedCardDisplay({
      ride: mergedRide,
      viewer: null,
      authWallet: 'WalletAAAA111111111111111111111111111111',
    });

    expect(card.actorLabel).toBe('Rider');
    expect(card.actorLabel).not.toContain('Wallet');
  });
});

describe('feed display helpers', () => {
  test('formats compact durations and resolves fallback targets', () => {
    expect(formatFeedDuration(312)).toBe('5:12');
    expect(formatFeedDuration(16_168)).toBe('4:29:28');
    expect(targetFromFeedActivity({
      ...rideActivity,
      target: null,
      metadata: { rideId: 'ride-from-metadata' },
    })).toMatchObject({ type: 'ride', id: 'ride-from-metadata' });
  });
});
