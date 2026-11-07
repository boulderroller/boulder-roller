import type {
  ResolvedLink,
  RideClimbEarning,
  RideInteractions,
  RideStatus,
  RideSummary,
} from './api';
import type { RoutePreview } from './routePreview';
import type { RideRow } from '../services/database';
import { bestScanTarget } from './linkActions';
import { recordStateLabelFromScanState, rideRecordStatusLabel } from './recordDisplay';

export interface RideDisplayStat {
  label: string;
  value: string;
}

export interface RideDisplayFact {
  label: 'Route' | 'Visibility' | 'Verification' | 'Social';
  value: string;
}

export interface RideDisplayModel {
  title: string;
  subtitle: string;
  routeLabel: string;
  routePreview: RoutePreview | null;
  summaryStats: RideDisplayStat[];
  facts: RideDisplayFact[];
}

export interface RideDisplayInput {
  localRide: RideRow | null;
  localRoutePreview: RoutePreview | null;
  serverRide: RideSummary | null;
  serverStatus: RideStatus | null;
  resolvedLink: ResolvedLink | null;
  rideInteractions: RideInteractions | null;
  targetServerRideId: string | null;
}

export function formatDurationMs(ms: number): string {
  const totalSeconds = Math.floor(ms / 1000);
  return formatDurationSec(totalSeconds);
}

export function formatDurationSec(totalSeconds: number): string {
  const hours = Math.floor(totalSeconds / 3600);
  const minutes = Math.floor((totalSeconds % 3600) / 60);
  const seconds = totalSeconds % 60;
  if (hours > 0) return `${hours}h ${minutes}m ${seconds}s`;
  return `${minutes}m ${seconds}s`;
}

export function formatDistance(meters: number): string {
  return `${(meters / 1000).toFixed(1)} km`;
}

export function formatAvgSpeed(meters: number, ms: number): string {
  if (ms <= 0) return '0.0 km/h';
  const hours = ms / 3_600_000;
  return `${(meters / 1000 / hours).toFixed(1)} km/h`;
}

export function formatDate(input: number | string | null): string {
  if (input === null) return '—';
  const d = typeof input === 'number' ? new Date(input) : new Date(input);
  if (Number.isNaN(d.getTime())) return '—';
  return d.toLocaleString();
}

export function rideTitleFromTimestamp(input: number | string | null): string {
  if (input === null) return 'Ride';
  const date = typeof input === 'number' ? new Date(input) : new Date(input);
  if (Number.isNaN(date.getTime())) return 'Ride';
  const hour = date.getHours();
  if (hour >= 5 && hour < 12) return 'Morning Ride';
  if (hour >= 12 && hour < 17) return 'Afternoon Ride';
  if (hour >= 17 && hour < 22) return 'Evening Ride';
  return 'Night Ride';
}

export function buildLocalSummaryStats(localRide: RideRow): RideDisplayStat[] {
  return [
    { label: 'Distance', value: formatDistance(localRide.distance_m) },
    { label: 'Duration', value: formatDurationMs(localRide.duration_ms) },
    { label: 'Elevation', value: `${Math.round(localRide.elevation_gain_m)} m` },
    {
      label: 'Avg Speed',
      value: formatAvgSpeed(localRide.distance_m, localRide.moving_time_ms),
    },
  ];
}

export function buildServerSummaryStats(status: RideStatus): RideDisplayStat[] {
  return [
    {
      label: 'Distance',
      value: status.metrics?.distanceM != null ? formatDistance(status.metrics.distanceM) : '—',
    },
    {
      label: 'Duration',
      value: status.metrics?.durationSec != null ? formatDurationSec(status.metrics.durationSec) : '—',
    },
    {
      label: 'Elevation',
      value: status.metrics?.elevationGainM != null ? `${Math.round(status.metrics.elevationGainM)} m` : '—',
    },
    {
      label: 'TSS',
      value: status.metrics?.tss != null
        ? `${Math.round(status.metrics.tss)}${status.metrics.thresholdTrainingState === 'pending' ? ' · Pending' : ''}`
        : '—',
    },
  ];
}

export function climbConsequenceLine(climb: RideClimbEarning): string {
  if (climb.isNewKom) return 'New KOM';
  if (climb.recordBoardRank != null) return `Top ${climb.recordBoardRank}`;
  if (climb.tributeBound && climb.calTribute != null && climb.calTribute > 0) {
    return `+${Math.round(climb.calTribute)} CAL`;
  }
  if (climb.vaultId != null) return 'Vault';
  return 'Open climb';
}

export function rideConsequenceLine(
  localRide: RideRow | null,
  status: RideStatus | null,
): string {
  const climbCount = status?.climbEarnings?.length ?? 0;
  const calEarned = status?.earnings?.calEarned ?? status?.calEarned;

  if (!status) {
    return localRide
      ? 'On this device'
      : 'Checking ride';
  }

  const pieces: string[] = [];
  if (climbCount > 0) pieces.push(`${climbCount} climb${climbCount === 1 ? '' : 's'} matched`);
  if (calEarned != null) pieces.push(`+${Math.round(calEarned)} CAL`);
  if (status.attestationStatus === 'attested') pieces.push('Verified');
  if (pieces.length > 0) return pieces.join(' • ');
  if (status.hasPatterns) return 'No climbs on this ride';
  return 'Checking ride';
}

export function statusStepState(
  status: RideStatus | null,
  step: 'saved' | 'uploaded' | 'climbs' | 'verified' | 'paid',
): 'done' | 'pending' {
  if (step === 'saved') return 'done';
  if (!status) return 'pending';
  if (step === 'uploaded') return 'done';
  if (step === 'climbs') return status.hasPatterns || status.hasLeaderboards ? 'done' : 'pending';
  if (step === 'verified') return status.attestationStatus === 'attested' ? 'done' : 'pending';
  if (status.effortPolicy?.thresholdEconomyState === 'held') return 'pending';
  return status.finalizedAt || status.earnings?.finalizedAt ? 'done' : 'pending';
}

export function boulderScanSubtitle(status: RideStatus): string {
  if (status.attestationStatus === 'attested') {
    return 'Verification ready';
  }
  if (status.canonicalMatch === false) {
    return 'Needs review';
  }
  return 'Still checking';
}

export function routeDisplayLabel(preview: RoutePreview | null): string {
  if (!preview) return 'No route preview';
  if ((preview.points?.length ?? 0) >= 2) return preview.placeLabel || 'Mapped route';
  if (preview.fallbackReason === 'privacy_redacted') return 'Private route';
  if (preview.fallbackReason === 'missing_gps') return 'No GPS preview';
  return 'Route preview pending';
}

export function visibilityDisplayLabel(ride: RideSummary | null): string {
  if (!ride) return 'Device only';
  const visibility = ride.visibility ?? ride.privacy?.visibility;
  if (visibility === 'followers') return 'Followers';
  if (visibility === 'private') return 'Private';
  return 'Public';
}

export function boulderScanDisplayLabel(link: ResolvedLink | null, status: RideStatus | null): string {
  if (link) return recordStateLabelFromScanState(bestScanTarget(link)?.state ?? link.scanState);
  if (status) return rideRecordStatusLabel(status, true);
  return 'Device only';
}

export function actionDisplayLabel(
  targetServerRideId: string | null,
  interactions: RideInteractions | null,
): string {
  if (!targetServerRideId) return 'Device only';
  if (interactions?.canComment === false) return 'Kudos and share';
  return 'Kudos, comments, share';
}

export function buildRideDisplayModel(input: RideDisplayInput): RideDisplayModel {
  const routePreview = input.serverRide?.routePreview ?? input.localRoutePreview;
  const titleSource = input.localRide?.started_at ?? input.serverRide?.startedAt ?? null;
  const title = rideTitleFromTimestamp(titleSource);
  const routeLabel = routeDisplayLabel(routePreview);
  const rideDateLabel = titleSource !== null ? formatDate(titleSource) : 'Checking ride';
  const subtitle = routePreview?.placeLabel ? `${rideDateLabel} • ${routePreview.placeLabel}` : rideDateLabel;
  const summaryStats = input.localRide
    ? buildLocalSummaryStats(input.localRide)
    : (input.serverStatus ? buildServerSummaryStats(input.serverStatus) : []);

  return {
    title,
    subtitle,
    routeLabel,
    routePreview,
    summaryStats,
    facts: [
      { label: 'Route', value: routeLabel },
      { label: 'Visibility', value: visibilityDisplayLabel(input.serverRide) },
      { label: 'Verification', value: boulderScanDisplayLabel(input.resolvedLink, input.serverStatus) },
      { label: 'Social', value: actionDisplayLabel(input.targetServerRideId, input.rideInteractions) },
    ],
  };
}
