import type {
  PublicRiderRideSummary,
  ResolvedLink,
  UserLeaderboardSummary,
  UserPublic,
  VaultPosition,
} from './api';
import type { RiderIdentityFields } from './riderIdentity';
import { riderPublicLabel, riderSecondaryLabel } from './riderIdentity';
import type { StatClusterItem } from '../components/surfaces/StatCluster';
import { hasResolvedBoulderScanTarget } from './linkActions';
import { recordStateLabelFromLink } from './recordDisplay';

export interface RiderDetailDisplayModel {
  identity: RiderIdentityFields;
  title: string;
  subtitle: string;
  bio: string | null | undefined;
  stats?: StatClusterItem[];
  recentRidesSubtitle: string;
  boulderScanSubtitle: string | null;
  boulderScanCtaLabel: string | null;
  topClimbsSubtitle: string | null;
}

export interface RiderRecentRideDisplay {
  title: string;
  meta: string;
  distanceLabel: string;
}

export interface RiderLeaderboardPositionDisplay {
  name: string;
  meta: string;
  time: string;
}

export function formatRiderDistanceKm(km: number | null | undefined): string {
  if (km == null || !Number.isFinite(km)) return '—';
  return `${Math.round(km).toLocaleString()} km`;
}

export function formatRiderElevation(meters: number | null | undefined): string {
  if (meters == null || !Number.isFinite(meters)) return '—';
  return `${Math.round(meters).toLocaleString()} m`;
}

export function formatRiderRideDate(iso?: string | null): string {
  if (!iso) return '—';
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return '—';
  return date.toLocaleDateString();
}

export function formatRiderTime(seconds: number): string {
  const minutes = Math.floor(seconds / 60);
  const remaining = seconds % 60;
  return `${minutes}:${String(remaining).padStart(2, '0')}`;
}

export function identityFromRiderProfile(
  profile: UserPublic | null,
  initial: RiderIdentityFields | undefined,
): RiderIdentityFields {
  return {
    id: profile?.rider?.id ?? profile?.id ?? initial?.id,
    wallet: profile?.wallet ?? initial?.wallet,
    username: profile?.rider?.username ?? profile?.username ?? initial?.username,
    displayName: profile?.rider?.displayName ?? profile?.displayName ?? initial?.displayName,
    avatarUrl: profile?.rider?.avatarUrl ?? profile?.avatarUrl ?? initial?.avatarUrl,
    isPublic: profile?.rider?.isPublic ?? profile?.isPublic ?? initial?.isPublic,
  };
}

export function buildRiderHeaderStats(profile: UserPublic | null): StatClusterItem[] | undefined {
  if (!profile || profile.isPublic === false) return undefined;
  return [
    { label: 'Rides', value: String(profile.totalRides ?? 0) },
    { label: 'Distance', value: formatRiderDistanceKm(profile.totalDistanceKm) },
    { label: 'Vert', value: formatRiderElevation(profile.totalElevationM) },
    { label: 'Followers', value: String(profile.followerCount ?? 0) },
    { label: 'Following', value: String(profile.followingCount ?? 0) },
  ];
}

export function buildRiderDetailDisplayModel(input: {
  profile: UserPublic | null;
  initialIdentity?: RiderIdentityFields;
  identifier: string;
  recentRideCount: number;
  leaderboard: UserLeaderboardSummary | null;
  resolvedLink: ResolvedLink | null;
}): RiderDetailDisplayModel {
  const identity = identityFromRiderProfile(
    input.profile,
    input.initialIdentity ?? { id: input.identifier },
  );
  const isPrivate = input.profile?.isPublic === false;
  const canOpenScan = hasResolvedBoulderScanTarget(input.resolvedLink);

  return {
    identity,
    title: riderPublicLabel(identity),
    subtitle: riderSecondaryLabel(identity) ?? (isPrivate ? 'Private rider' : 'Rider'),
    bio: isPrivate ? null : input.profile?.bio,
    stats: buildRiderHeaderStats(input.profile),
    recentRidesSubtitle: `${input.recentRideCount} public`,
    boulderScanSubtitle: recordStateLabelFromLink(input.resolvedLink),
    boulderScanCtaLabel: canOpenScan ? 'Open BoulderScan' : null,
    topClimbsSubtitle: input.leaderboard
      ? `${input.leaderboard.stats.komCount} KOMs • ${input.leaderboard.stats.podiumCount} podiums`
      : null,
  };
}

export function buildRiderRecentRideDisplay(ride: PublicRiderRideSummary): RiderRecentRideDisplay {
  return {
    title: ride.title || 'Ride',
    meta: `${formatRiderRideDate(ride.startedAt ?? ride.createdAt)} • ${ride.visibility ?? 'public'}`,
    distanceLabel: ride.distanceM != null ? `${(ride.distanceM / 1000).toFixed(1)} km` : 'Ride',
  };
}

export function buildRiderLeaderboardPositionDisplay(
  position: VaultPosition,
): RiderLeaderboardPositionDisplay {
  return {
    name: position.vaultName,
    meta: `#${position.rank} of ${position.totalRiders.toLocaleString()}`,
    time: formatRiderTime(position.bestTimeSeconds),
  };
}
