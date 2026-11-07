import type { ResolvedLink, RideStatus } from './api';
import { hasResolvedBoulderScanTarget } from './linkActions';
import {
  PRE_ECONOMY_REVIEW_REASON,
  isPreEconomyRide,
} from './economyWindow';
import type { PostRideUploadState } from './postRideProgress';
import { recordStateLabelFromLink } from './recordDisplay';
import type { RideRow } from '../services/database';

export type PostRideUploadMessageTone = 'default' | 'success' | 'failed';

export interface PostRideSummaryStat {
  label: string;
  value: string;
}

export interface PostRideUploadMessage {
  text: string;
  tone: PostRideUploadMessageTone;
  showSpinner: boolean;
}

export interface PostRideEarningsDisplay {
  value: string;
  label: string;
}

export interface PostRideActionDisplay {
  title: string;
  boulderScanCtaLabel: string | null;
}

export interface PostRideDisplayModel {
  headerTitle: string;
  uploadMessage: PostRideUploadMessage | null;
  summaryRows: PostRideSummaryStat[][];
  earnings: PostRideEarningsDisplay | null;
  action: PostRideActionDisplay | null;
}

export function formatPostRideDuration(ms: number): string {
  const totalSeconds = Math.max(0, Math.floor(ms / 1000));
  const hours = Math.floor(totalSeconds / 3600);
  const minutes = Math.floor((totalSeconds % 3600) / 60);
  const seconds = totalSeconds % 60;
  if (hours > 0) {
    return `${hours}h ${minutes}m ${seconds}s`;
  }
  return `${minutes}m ${seconds}s`;
}

export function formatPostRideDistance(meters: number): string {
  return `${(Math.max(0, meters) / 1000).toFixed(1)} km`;
}

export function formatPostRideSpeed(meters: number, ms: number): string {
  if (ms <= 0) return '0.0 km/h';
  const hours = ms / 3_600_000;
  return `${(Math.max(0, meters) / 1000 / hours).toFixed(1)} km/h`;
}

export function formatPostRideElevation(meters: number): string {
  return `${Math.round(Math.max(0, meters)).toLocaleString()} m`;
}

export function buildPostRideSummaryRows(localRide: RideRow): PostRideSummaryStat[][] {
  return [
    [
      { label: 'Distance', value: formatPostRideDistance(localRide.distance_m) },
      { label: 'Duration', value: formatPostRideDuration(localRide.duration_ms) },
    ],
    [
      { label: 'Elevation', value: formatPostRideElevation(localRide.elevation_gain_m) },
      { label: 'Avg Speed', value: formatPostRideSpeed(localRide.distance_m, localRide.moving_time_ms) },
    ],
    [
      { label: 'Max Speed', value: `${(Math.max(0, localRide.max_speed_mps) * 3.6).toFixed(1)} km/h` },
      { label: 'GPS', value: String(localRide.sample_count) },
    ],
  ];
}

export function buildPostRideUploadMessage(input: {
  localRide: RideRow;
  isIncomplete: boolean;
  incompleteReason?: string | null;
  uploadState: PostRideUploadState;
  serverStatus: RideStatus | null;
}): PostRideUploadMessage | null {
  if (input.isIncomplete) {
    return {
      text: `${input.incompleteReason ?? 'Not enough movement to score.'} Kept on this device and not counted.`,
      tone: 'default',
      showSpinner: false,
    };
  }

  const isHistoricalImport = (
    isPreEconomyRide(input.localRide) ||
    input.serverStatus?.reviewReason === PRE_ECONOMY_REVIEW_REASON
  );
  if (isHistoricalImport && input.uploadState === 'uploading') {
    return {
      text: 'Saving for analysis. This activity predates live CAL and can be imported, but CAL and DUNG will not count.',
      tone: 'default',
      showSpinner: true,
    };
  }
  if (isHistoricalImport && input.uploadState === 'uploaded') {
    return {
      text: 'Saved for analysis. This activity predates live CAL and can be imported, but CAL and DUNG will not count.',
      tone: 'success',
      showSpinner: false,
    };
  }

  if (input.uploadState === 'uploading') {
    return {
      text: 'Saving ride...',
      tone: 'default',
      showSpinner: true,
    };
  }

  if (input.uploadState === 'uploaded') {
    return {
      text: input.serverStatus?.status === 'completed' ? 'Ride ready' : 'Saved. Checking climbs and CAL.',
      tone: 'success',
      showSpinner: false,
    };
  }

  if (input.uploadState === 'failed') {
    return {
      text: 'Upload paused. The app will retry automatically.',
      tone: 'failed',
      showSpinner: false,
    };
  }

  return null;
}

export function buildPostRideEarningsDisplay(status: RideStatus | null): PostRideEarningsDisplay | null {
  if (
    status?.status === 'completed'
    && status.effortPolicy?.thresholdEconomyState === 'held'
  ) {
    return {
      value: 'Held',
      label: 'Held — clears when your Threshold is established.',
    };
  }
  const calEarned = status?.earnings?.calEarned ?? status?.calEarned;
  if (calEarned == null || status?.status !== 'completed') return null;
  return {
    value: `+${calEarned}`,
    label: 'Counted CAL',
  };
}

export function buildPostRideActionDisplay(input: {
  serverRideId: string | null;
  resolvedLink: ResolvedLink | null;
}): PostRideActionDisplay | null {
  if (!input.serverRideId) return null;
  const canOpenScan = hasResolvedBoulderScanTarget(input.resolvedLink);
  return {
    title: recordStateLabelFromLink(input.resolvedLink) ?? 'Ride saved',
    boulderScanCtaLabel: canOpenScan ? 'Open BoulderScan' : null,
  };
}

export function buildPostRideDisplayModel(input: {
  localRide: RideRow;
  serverStatus: RideStatus | null;
  uploadState: PostRideUploadState;
  serverRideId: string | null;
  resolvedLink: ResolvedLink | null;
  isIncomplete: boolean;
  incompleteReason?: string | null;
}): PostRideDisplayModel {
  return {
    headerTitle: input.isIncomplete ? 'Recording Saved' : 'Ride Complete',
    uploadMessage: buildPostRideUploadMessage(input),
    summaryRows: buildPostRideSummaryRows(input.localRide),
    earnings: buildPostRideEarningsDisplay(input.serverStatus),
    action: buildPostRideActionDisplay({
      serverRideId: input.serverRideId,
      resolvedLink: input.resolvedLink,
    }),
  };
}
