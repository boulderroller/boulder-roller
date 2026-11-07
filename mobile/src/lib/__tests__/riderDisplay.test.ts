import type {
  PublicRiderRideSummary,
  ResolvedLink,
  UserLeaderboardSummary,
  UserPublic,
  VaultPosition,
} from '../api';
import {
  buildRiderDetailDisplayModel,
  buildRiderLeaderboardPositionDisplay,
  buildRiderRecentRideDisplay,
  formatRiderDistanceKm,
  formatRiderElevation,
  formatRiderTime,
} from '../riderDisplay';

const publicProfile: UserPublic = {
  id: 'target-user',
  wallet: 'WalletAAAA1111',
  username: 'tim',
  displayName: 'Tim',
  bio: 'Rolls hard.',
  avatarUrl: null,
  isPublic: true,
  createdAt: '2026-04-24T00:00:00Z',
  totalRides: 9,
  totalDistanceKm: 420.4,
  totalElevationM: 8000.2,
  totalDungEarned: 12,
  followerCount: 17,
  followingCount: 4,
};

const resolvedLink: ResolvedLink = {
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
  scanState: 'off_chain_only',
  scanTargets: [],
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
};

const leaderboard: UserLeaderboardSummary = {
  wallet: 'WalletAAAA1111',
  stats: {
    totalPositions: 3,
    komCount: 1,
    podiumCount: 2,
    top10Count: 3,
    totalVaultsCompleted: 3,
  },
  positions: [],
};

describe('buildRiderDetailDisplayModel', () => {
  test('summarizes public rider identity, stats, scan state, and climb standing', () => {
    const model = buildRiderDetailDisplayModel({
      profile: publicProfile,
      initialIdentity: { wallet: publicProfile.wallet },
      identifier: publicProfile.wallet,
      recentRideCount: 1,
      leaderboard,
      resolvedLink,
    });

    expect(model.title).toBe('Tim');
    expect(model.subtitle).toBe('@tim');
    expect(model.bio).toBe('Rolls hard.');
    expect(model.stats).toEqual([
      { label: 'Rides', value: '9' },
      { label: 'Distance', value: '420 km' },
      { label: 'Vert', value: '8,000 m' },
      { label: 'Followers', value: '17' },
      { label: 'Following', value: '4' },
    ]);
    expect(model.recentRidesSubtitle).toBe('1 public');
    expect(model.boulderScanSubtitle).toBe('App only');
    expect(model.boulderScanCtaLabel).toBeNull();
    expect(model.topClimbsSubtitle).toBe('1 KOMs • 2 podiums');
  });

  test('opens BoulderScan only when the rider link has an exact scan target', () => {
    const model = buildRiderDetailDisplayModel({
      profile: publicProfile,
      initialIdentity: { wallet: publicProfile.wallet },
      identifier: publicProfile.wallet,
      recentRideCount: 0,
      leaderboard: null,
      resolvedLink: {
        ...resolvedLink,
        scanState: 'recorded',
        scanTargets: [
          {
            contractVersion: 'scan.v1',
            type: 'wallet',
            id: publicProfile.wallet,
            state: 'recorded',
            label: 'Wallet account',
            url: `https://scan.boulderroller.xyz/account/${publicProfile.wallet}`,
            source: 'user.wallet',
          },
        ],
      },
    });

    expect(model.boulderScanSubtitle).toBe('BoulderScan ready');
    expect(model.boulderScanCtaLabel).toBe('Open BoulderScan');
  });

  test('keeps private rider display quiet and does not expose stats or bio', () => {
    const model = buildRiderDetailDisplayModel({
      profile: {
        ...publicProfile,
        displayName: null,
        username: null,
        bio: 'Hidden bio',
        isPublic: false,
        totalRides: 0,
        totalDistanceKm: 0,
        totalElevationM: 0,
      },
      initialIdentity: { username: 'from-route', wallet: 'WalletBBBB2222' },
      identifier: 'WalletBBBB2222',
      recentRideCount: 0,
      leaderboard: null,
      resolvedLink: null,
    });

    expect(model.title).toBe('@from-route');
    expect(model.subtitle).toBe('Private rider');
    expect(model.bio).toBeNull();
    expect(model.stats).toBeUndefined();
    expect(model.boulderScanSubtitle).toBeNull();
    expect(model.boulderScanCtaLabel).toBeNull();
    expect(model.topClimbsSubtitle).toBeNull();
  });
});

describe('rider display row helpers', () => {
  test('formats recent ride and leaderboard rows in rider-facing copy', () => {
    const ride: PublicRiderRideSummary = {
      id: 'ride-1',
      title: 'Rolling boulders',
      startedAt: '2026-04-24T12:00:00Z',
      distanceM: 40200,
      visibility: 'followers',
    };
    const position: VaultPosition = {
      vaultId: 7,
      vaultName: 'Manayunk Wall',
      vaultSignature: 'sig',
      rank: 1,
      bestTimeSeconds: 312,
      isKom: true,
      totalRiders: 42,
    };

    expect(buildRiderRecentRideDisplay(ride)).toEqual({
      title: 'Rolling boulders',
      meta: expect.stringMatching(/2026.*followers|followers.*2026/),
      distanceLabel: '40.2 km',
    });
    expect(buildRiderLeaderboardPositionDisplay(position)).toEqual({
      name: 'Manayunk Wall',
      meta: '#1 of 42',
      time: '5:12',
    });
  });

  test('uses placeholders for missing rider metrics instead of NaN', () => {
    expect(formatRiderDistanceKm(undefined)).toBe('—');
    expect(formatRiderElevation(Number.NaN)).toBe('—');
    expect(formatRiderTime(61)).toBe('1:01');
  });
});
