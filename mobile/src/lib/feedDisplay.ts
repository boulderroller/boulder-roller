import type {
  FeedActivity,
  LinkTarget,
  RideMedia,
  RideVisibility,
} from './api';
import type { MergedRide } from './rides';
import type { RoutePreview } from './routePreview';
import type { StatClusterItem } from '../components/surfaces/StatCluster';
import { formatDistance } from './rideDisplay';
import { riderPublicLabel, type RiderIdentityFields } from './riderIdentity';
import { publicRiderIdentity } from './riderNavigation';
import { isIncompleteRide } from './rideCompletion';
import { deriveRideLifecycle } from './rideLifecycle';
import {
  buildRideLifecycleDisplayModel,
  localLifecycleInputFromMergedRide,
  uploadLifecycleInputFromMergedRide,
} from './rideLifecycleDisplay';
import { targetFromFeedActivity } from './targetActions';

export { targetFromFeedActivity } from './targetActions';

export type FeedSource = 'following' | 'mine' | 'global';

export interface FeedCardDisplayModel {
  actorIdentity: RiderIdentityFields | null;
  actorLabel: string;
  title: string;
  dateLabel: string;
  locationLabel?: string;
  summaryLine: string;
  statusLine: string;
  stats: StatClusterItem[];
  routePreview: RoutePreview | null;
  primaryMedia: RideMedia | null;
  mediaCount: number;
  impactItems: string[];
  kudosCount?: number | null;
  commentCount?: number | null;
  viewerHasKudos?: boolean;
  viewerReported?: boolean;
  visibility?: RideVisibility | null;
  target: LinkTarget | null;
}

export interface RideFeedCardInput {
  ride: MergedRide;
  viewer: RiderIdentityFields | null;
  authWallet?: string | null;
}

type FeedMetadata = NonNullable<FeedActivity['metadata']> & Record<string, unknown>;

function finiteNumber(value: number | null | undefined): number | null {
  return typeof value === 'number' && Number.isFinite(value) ? value : null;
}

function metadataNumber(metadata: FeedMetadata, ...keys: string[]): number | null {
  for (const key of keys) {
    const value = metadata[key];
    if (typeof value === 'number' && Number.isFinite(value)) return value;
  }
  return null;
}

function metadataString(metadata: FeedMetadata, ...keys: string[]): string | null {
  for (const key of keys) {
    const value = metadata[key];
    if (typeof value === 'string' && value.trim()) return value.trim();
  }
  return null;
}

function sentence(text: string): string {
  return /[.!?]$/.test(text) ? text : `${text}.`;
}

function formatSignedMetric(value: number): string {
  return `+${Math.round(value)}`;
}

function joinWithAnd(items: string[]): string {
  if (items.length <= 1) return items[0] ?? '';
  if (items.length === 2) return `${items[0]} and ${items[1]}`;
  return `${items.slice(0, -1).join(', ')}, and ${items[items.length - 1]}`;
}

function feedTrainingLoad(metadata: FeedMetadata): number | null {
  return metadataNumber(metadata, 'tss') ?? metadataNumber(metadata, 'points');
}

function feedMetricCopyItems(metadata: FeedMetadata): string[] {
  const cal = metadataNumber(metadata, 'calEarned');
  const dung = metadataNumber(metadata, 'dungEarned');
  const tss = feedTrainingLoad(metadata);
  const items: string[] = [];
  if (cal != null) items.push(`${formatSignedMetric(cal)} CAL`);
  if (dung != null) items.push(`${formatSignedMetric(dung)} DUNG`);
  if (tss != null) items.push(`${Math.round(tss)} TSS`);
  return items;
}

export function formatFeedDuration(seconds: number | null | undefined): string {
  const value = finiteNumber(seconds);
  if (value === null) return '—';
  const h = Math.floor(value / 3600);
  const m = Math.floor((value % 3600) / 60);
  const s = Math.floor(value % 60);
  if (h > 0) return `${h}:${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}`;
  return `${m}:${String(s).padStart(2, '0')}`;
}

export function formatFeedDate(iso: string | undefined, fallbackMs?: number): string {
  const parsed = iso ? new Date(iso) : null;
  const resolved = parsed && !Number.isNaN(parsed.getTime())
    ? parsed
    : fallbackMs != null
      ? new Date(fallbackMs)
      : null;
  if (!resolved || Number.isNaN(resolved.getTime())) return '';

  const now = new Date();
  const time = resolved.toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' }).toLowerCase();
  if (resolved.toDateString() === now.toDateString()) return `Today at ${time}`;
  return `${resolved.toLocaleDateString()} at ${time}`;
}

export function isIncompleteRideArtifact(ride: MergedRide): boolean {
  return isIncompleteRide({
    status: ride.localStatus,
    distanceM: finiteNumber(ride.distanceM),
    durationSec: finiteNumber(ride.durationSec),
    elevationGainM: finiteNumber(ride.elevationGainM),
    points: finiteNumber(ride.tss),
  });
}

function rideTitleForRide(ride: MergedRide): string {
  if (isIncompleteRideArtifact(ride)) return 'Incomplete recording';
  return 'Rolling boulders';
}

function summaryLineForRide(ride: MergedRide): string {
  if (isIncompleteRideArtifact(ride)) return 'Not enough movement to score';
  return `${formatDistance(ride.distanceM)} • ${formatFeedDuration(ride.durationSec)}`;
}

function contextLineForRide(ride: MergedRide): string {
  if (isIncompleteRideArtifact(ride)) {
    return 'Kept for review • no climb or TSS score';
  }
  const lifecycle = deriveRideLifecycle({
    localRide: localLifecycleInputFromMergedRide(ride),
    uploadEntry: uploadLifecycleInputFromMergedRide(ride),
    serverStatus: null,
  });
  const lifecycleDisplay = buildRideLifecycleDisplayModel(lifecycle);
  if (
    lifecycle.phase === 'upload_retrying' ||
    lifecycle.phase === 'auth_required' ||
    lifecycle.phase === 'upload_failed' ||
    lifecycle.phase === 'ready_to_upload'
  ) {
    return `${lifecycleDisplay.stateLabel} • ${lifecycleDisplay.subtitle}`;
  }
  if (ride.source === 'local') {
    return 'On this device • upload to see climbs and CAL';
  }
  if (ride.source === 'server') {
    return 'Synced from another device • open for full detail';
  }
  return 'Synced ride • open for climbs, leaderboard changes, and CAL';
}

function impactItemsForRide(ride: MergedRide): string[] {
  if (isIncompleteRideArtifact(ride)) {
    return ['has an incomplete recording that needs review.'];
  }
  const lifecycle = deriveRideLifecycle({
    localRide: localLifecycleInputFromMergedRide(ride),
    uploadEntry: uploadLifecycleInputFromMergedRide(ride),
    serverStatus: null,
  });
  const lifecycleDisplay = buildRideLifecycleDisplayModel(lifecycle);
  if (
    lifecycle.phase === 'upload_retrying' ||
    lifecycle.phase === 'auth_required' ||
    lifecycle.phase === 'upload_failed' ||
    lifecycle.phase === 'ready_to_upload'
  ) {
    return [`has a ride waiting: ${lifecycleDisplay.stateLabel.toLowerCase()}.`];
  }
  if (ride.source === 'local') {
    return ['recorded a ride on this device.'];
  }
  if (ride.source === 'server') {
    return ['synced a ride from another device.'];
  }
  return ['finished a ride with climbs and results ready.'];
}

function cardStatsForRide(ride: MergedRide): StatClusterItem[] {
  if (isIncompleteRideArtifact(ride)) {
    return [
      { label: 'Climbs', value: '—' },
      { label: 'Total climbing', value: '—' },
      { label: 'TSS', value: '—' },
    ];
  }
  const elevation = finiteNumber(ride.elevationGainM);
  return [
    { label: 'Climbs', value: '—' },
    { label: 'Total climbing', value: elevation != null ? `${Math.round(elevation)} m` : '—' },
    { label: 'TSS', value: ride.tss != null ? String(Math.round(ride.tss)) : '—' },
  ];
}

export function buildRideFeedCardDisplay(input: RideFeedCardInput): FeedCardDisplayModel {
  const { ride, viewer, authWallet } = input;
  const actorIdentity = publicRiderIdentity(viewer ?? (authWallet ? { wallet: authWallet } : null));
  const actorLabel = riderPublicLabel(actorIdentity);
  const media = ride.media ?? [];
  const primaryMedia = media.find((item) => item.role === 'cover' && item.url) ?? media.find((item) => item.url) ?? null;

  return {
    actorIdentity,
    actorLabel,
    title: rideTitleForRide(ride),
    dateLabel: formatFeedDate(ride.startedAtIso, ride.startedAtMs),
    summaryLine: summaryLineForRide(ride),
    statusLine: contextLineForRide(ride),
    stats: cardStatsForRide(ride),
    routePreview: ride.routePreview,
    primaryMedia,
    mediaCount: media.length,
    impactItems: impactItemsForRide(ride),
    target: ride.serverRideId
      ? { type: 'ride', id: ride.serverRideId }
      : ride.localRideId
        ? { type: 'ride', id: ride.localRideId }
        : null,
  };
}

function eventType(activity: FeedActivity): string {
  return activity.eventType ?? activity.type;
}

function titleForActivity(activity: FeedActivity): string {
  const kind = eventType(activity);
  const metadata = (activity.metadata ?? {}) as FeedMetadata;
  if (kind === 'ride_completed') return 'Rolling boulders';
  if (kind === 'ride_under_review') return 'Ride under review';
  if (kind === 'record_rank_moved') return 'Leaderboard move';
  if (kind === 'local_legend_moved') return 'Local Legend';
  if (kind === 'climb_completed') return metadataString(metadata, 'climbName', 'vaultName') ?? 'Climb completed';
  if (kind === 'achievement_unlocked') return metadataString(metadata, 'achievementName', 'milestoneName') ?? activity.title;
  return activity.title || 'Ride update';
}

function impactItemsForActivity(activity: FeedActivity): string[] {
  const kind = eventType(activity);
  const metadata = (activity.metadata ?? {}) as FeedMetadata;
  const climbName = metadataString(metadata, 'climbName', 'vaultName', 'roadName', 'name');
  const rank = metadataNumber(metadata, 'rank', 'recordBoardRank', 'place');
  const achievementName = metadataString(metadata, 'achievementName', 'milestoneName');

  if (kind === 'vault_created') {
    return [sentence(`created a new vault${climbName ? ` on ${climbName}` : ''}`)];
  }
  if (kind === 'record_rank_moved') {
    if (rank != null && climbName) return [sentence(`moved to #${Math.round(rank)} on ${climbName}`)];
    if (rank != null) return [sentence(`moved to #${Math.round(rank)} on a leaderboard`)];
    return ['moved up a leaderboard.'];
  }
  if (kind === 'local_legend_moved') {
    return [sentence(`became Local Legend${climbName ? ` on ${climbName}` : ''}`)];
  }
  if (kind === 'achievement_unlocked') {
    return [sentence(`unlocked ${achievementName ?? 'a milestone'}`)];
  }
  if (kind === 'climb_completed') {
    return [sentence(`finished ${climbName ?? 'a climb'}`)];
  }
  if (kind === 'ride_completed') {
    const climbCount = metadataNumber(metadata, 'climbCount', 'climbs');
    const details: string[] = [];
    if (climbCount != null) details.push(`${Math.round(climbCount)} climb${climbCount === 1 ? '' : 's'}`);
    details.push(...feedMetricCopyItems(metadata));
    return [sentence(details.length ? `finished a ride with ${joinWithAnd(details)}` : 'finished a ride')];
  }
  if (kind === 'ride_under_review') return ['sent a ride for review.'];
  if (kind === 'comment_created') return ['commented on a ride.'];
  if (kind === 'follow_created') return ['followed a rider.'];
  if (kind === 'report_resolved') return ['had a report reviewed.'];
  return ['made a ride update.'];
}

function statsForActivity(activity: FeedActivity): StatClusterItem[] {
  const metadata = (activity.metadata ?? {}) as FeedMetadata;
  const climbCount = metadataNumber(metadata, 'climbCount', 'climbs');
  const elevationM = metadataNumber(metadata, 'elevationM', 'elevationGainM', 'totalElevationM');
  const cal = metadataNumber(metadata, 'calEarned');
  const dung = metadataNumber(metadata, 'dungEarned');
  const tss = feedTrainingLoad(metadata);
  const stats: StatClusterItem[] = [
    { label: 'Climbs', value: climbCount != null ? String(Math.round(climbCount)) : '—' },
  ];
  if (cal != null) stats.push({ label: 'CAL', value: formatSignedMetric(cal) });
  if (dung != null) stats.push({ label: 'DUNG', value: formatSignedMetric(dung) });
  if (tss != null) stats.push({ label: 'TSS', value: String(Math.round(tss)) });
  if (stats.length < 3) {
    stats.splice(1, 0, { label: 'Total climbing', value: elevationM != null ? `${Math.round(elevationM)} m` : '—' });
  }
  if (stats.length < 3) stats.push({ label: 'TSS', value: '—' });
  return stats;
}

function summaryLineForActivity(activity: FeedActivity): string {
  const metadata = (activity.metadata ?? {}) as FeedMetadata;
  const distanceM = metadataNumber(metadata, 'distanceM');
  const durationS = metadataNumber(metadata, 'durationS', 'durationSec');
  const distance = distanceM != null ? formatDistance(distanceM) : '—';
  const duration = formatFeedDuration(durationS);
  if (distance === '—' && duration === '—') return eventType(activity);
  return `${distance} • ${duration}`;
}

function locationForActivity(activity: FeedActivity): string | undefined {
  const metadata = (activity.metadata ?? {}) as FeedMetadata;
  const routePreview = metadata.routePreview && typeof metadata.routePreview === 'object'
    ? metadata.routePreview as { placeLabel?: unknown }
    : null;
  const value = metadata.location ?? metadata.region ?? routePreview?.placeLabel;
  return typeof value === 'string' && value.trim() ? value.trim() : undefined;
}

function routePreviewForActivity(activity: FeedActivity): RoutePreview | null {
  const preview = activity.metadata?.routePreview;
  return preview ?? null;
}

function primaryMediaForActivity(activity: FeedActivity): RideMedia | null {
  const metadata = (activity.metadata ?? {}) as FeedMetadata;
  const primary = metadata.primaryMedia;
  if (primary && typeof primary === 'object' && typeof (primary as RideMedia).url === 'string') {
    return primary as RideMedia;
  }
  const media = metadata.media;
  if (Array.isArray(media)) {
    return (media.find((item) => item && typeof item === 'object' && typeof (item as RideMedia).url === 'string') as RideMedia | undefined) ?? null;
  }
  return null;
}

export function buildFeedActivityCardDisplay(activity: FeedActivity): FeedCardDisplayModel {
  const actor = activity.actor ?? activity.user ?? null;
  const actorIdentity = publicRiderIdentity(actor);
  const metadata = (activity.metadata ?? {}) as FeedMetadata;
  const primaryMedia = primaryMediaForActivity(activity);
  const mediaCount = Array.isArray(metadata.media) ? metadata.media.length : primaryMedia ? 1 : 0;

  return {
    actorIdentity,
    actorLabel: riderPublicLabel(actorIdentity, 'Boulder Roller'),
    title: titleForActivity(activity),
    dateLabel: formatFeedDate(activity.occurredAt ?? activity.createdAt),
    locationLabel: locationForActivity(activity),
    summaryLine: summaryLineForActivity(activity),
    statusLine: eventType(activity),
    stats: statsForActivity(activity),
    routePreview: routePreviewForActivity(activity),
    primaryMedia,
    mediaCount,
    impactItems: impactItemsForActivity(activity),
    kudosCount: metadataNumber(metadata, 'kudosCount'),
    commentCount: metadataNumber(metadata, 'commentCount'),
    viewerHasKudos: metadata.viewerHasKudos === true,
    viewerReported: metadata.viewerReported === true,
    visibility: (metadata.visibility ?? activity.privacy?.visibility ?? null) as RideVisibility | null,
    target: targetFromFeedActivity(activity),
  };
}
