import type {
  LocalRideLifecycleInput,
  RideLifecycleAction,
  RideLifecyclePhase,
  RideLifecycleView,
  UploadQueueLifecycleInput,
} from './rideLifecycle';
import type { RideRow, UploadQueueRow } from '../services/database';
import type { MergedRide } from './rides';

export type RideLifecycleTone = 'neutral' | 'working' | 'success' | 'warning' | 'danger';

export interface RideLifecycleDisplayModel {
  phase: RideLifecyclePhase;
  tone: RideLifecycleTone;
  title: string;
  subtitle: string;
  stateLabel: string;
  failureMessage: string | null;
  qualityLabel: string | null;
  detailLines: string[];
  primaryAction: RideLifecycleAction | null;
  primaryActionLabel: string | null;
}

function titleForPhase(phase: RideLifecyclePhase): Pick<RideLifecycleDisplayModel, 'title' | 'subtitle' | 'stateLabel' | 'tone'> {
  switch (phase) {
    case 'recording':
      return {
        title: 'Recording in progress',
        subtitle: 'Keep the app open or save from Record.',
        stateLabel: 'Recording',
        tone: 'working',
      };
    case 'paused':
      return {
        title: 'Recording paused',
        subtitle: 'Resume or stop from Record.',
        stateLabel: 'Paused',
        tone: 'working',
      };
    case 'recoverable':
      return {
        title: 'Interrupted ride found',
        subtitle: 'Save it before starting another ride.',
        stateLabel: 'Recovery',
        tone: 'warning',
      };
    case 'ready_to_upload':
      return {
        title: 'Ready to upload',
        subtitle: 'Saved on this device. Upload to check climbs and CAL.',
        stateLabel: 'On device',
        tone: 'warning',
      };
    case 'upload_waiting':
      return {
        title: 'Waiting to upload',
        subtitle: 'Saved locally. The app will upload when it can.',
        stateLabel: 'Queued',
        tone: 'working',
      };
    case 'uploading':
      return {
        title: 'Saving ride',
        subtitle: 'Uploading from this device.',
        stateLabel: 'Uploading',
        tone: 'working',
      };
    case 'upload_retrying':
      return {
        title: 'Upload paused',
        subtitle: 'The ride is safe on this device. Retry when connection is back.',
        stateLabel: 'Retry upload',
        tone: 'warning',
      };
    case 'auth_required':
      return {
        title: 'Sign in needed',
        subtitle: 'The ride is safe on this device. Sign in again to upload it.',
        stateLabel: 'Auth needed',
        tone: 'warning',
      };
    case 'upload_failed':
      return {
        title: 'Upload failed',
        subtitle: 'The ride is still on this device. Retry the upload.',
        stateLabel: 'Upload failed',
        tone: 'danger',
      };
    case 'uploaded':
      return {
        title: 'Ride saved',
        subtitle: 'Checking climbs and stats.',
        stateLabel: 'Saved',
        tone: 'working',
      };
    case 'queued':
      return {
        title: 'Ride queued',
        subtitle: 'Waiting to check this ride.',
        stateLabel: 'Queued',
        tone: 'working',
      };
    case 'processing':
      return {
        title: 'Checking ride',
        subtitle: 'Building the ride stats and climb matches.',
        stateLabel: 'Checking',
        tone: 'working',
      };
    case 'scored':
      return {
        title: 'Ride ready',
        subtitle: 'Climbs and stats are ready. Verification is pending.',
        stateLabel: 'Ready',
        tone: 'success',
      };
    case 'under_review':
      return {
        title: 'Needs review',
        subtitle: 'This ride is saved but needs review before it counts.',
        stateLabel: 'Review',
        tone: 'warning',
      };
    case 'complete':
      return {
        title: 'Ride complete',
        subtitle: 'Climbs and stats are ready.',
        stateLabel: 'Complete',
        tone: 'success',
      };
    case 'failed':
      return {
        title: 'Ride check failed',
        subtitle: 'Boulder Roller could not finish checking this ride.',
        stateLabel: 'Failed',
        tone: 'danger',
      };
    case 'unknown':
    default:
      return {
        title: 'Ride state unknown',
        subtitle: 'Open again after the app refreshes.',
        stateLabel: 'Unknown',
        tone: 'neutral',
      };
  }
}

function actionLabel(action: RideLifecycleAction): string {
  switch (action) {
    case 'save_interrupted_ride':
      return 'Save ride';
    case 'discard_interrupted_ride':
      return 'Discard ride';
    case 'retry_upload':
      return 'Retry upload';
    case 'reauthenticate':
      return 'Sign in again';
    case 'retry_processing':
      return 'Retry processing';
    case 'open_ride':
      return 'Open ride';
  }
}

function choosePrimaryAction(actions: RideLifecycleAction[]): RideLifecycleAction | null {
  return (
    actions.find((action) => action === 'retry_upload') ??
    actions.find((action) => action === 'reauthenticate') ??
    actions.find((action) => action === 'retry_processing') ??
    actions.find((action) => action === 'save_interrupted_ride') ??
    actions.find((action) => action === 'open_ride') ??
    null
  );
}

function qualityLabel(view: RideLifecycleView): string | null {
  if (view.quality.status === 'invalid') return 'Invalid recording';
  if (view.quality.status === 'degraded') return 'Recording degraded';
  if (view.quality.hadCrashRecovery) return 'Recovered recording';
  return null;
}

function sensorDataLabel(state: RideLifecycleView['quality']['sensorDataState']): string | null {
  switch (state) {
    case 'absent':
      return 'Sensor data missing';
    case 'partial':
      return 'Sensor data partial';
    case 'present':
      return 'Sensor data present';
    case 'unknown':
    default:
      return null;
  }
}

function qualityReasonLabel(reason: string): string | null {
  const normalized = reason.trim();
  if (!normalized) return null;
  if (normalized.includes('RECOVERY') || normalized.includes('interrupted_recording')) {
    return 'Recording recovered';
  }
  if (normalized.includes(':')) return null;
  return normalized
    .replace(/[_-]+/g, ' ')
    .replace(/\s+/g, ' ')
    .trim()
    .replace(/^\w/, (char) => char.toUpperCase());
}

export function buildRideLifecycleDisplayModel(view: RideLifecycleView): RideLifecycleDisplayModel {
  const base = titleForPhase(view.phase);
  const primaryAction = choosePrimaryAction(view.actions);
  const detailLines = [
    view.quality.sampleCount != null ? `${view.quality.sampleCount.toLocaleString()} GPS points` : null,
    sensorDataLabel(view.quality.sensorDataState),
    ...view.quality.degradationReasons
      .map(qualityReasonLabel)
      .filter((line): line is string => !!line)
      .slice(0, 2),
  ].filter((line): line is string => !!line);

  return {
    phase: view.phase,
    ...base,
    failureMessage: view.failure?.message ?? null,
    qualityLabel: qualityLabel(view),
    detailLines,
    primaryAction,
    primaryActionLabel: primaryAction ? actionLabel(primaryAction) : null,
  };
}

export function localLifecycleInputFromRide(ride: RideRow | null): LocalRideLifecycleInput | null {
  if (!ride) return null;
  return {
    id: ride.id,
    status: ride.status,
    sample_count: ride.sample_count,
    rejected_samples: ride.rejected_samples,
    had_crash_recovery: ride.had_crash_recovery,
  };
}

export function uploadLifecycleInputFromEntry(
  entry: UploadQueueRow | UploadQueueLifecycleInput | null,
): UploadQueueLifecycleInput | null {
  if (!entry) return null;
  return {
    status: entry.status,
    server_ride_id: entry.server_ride_id,
    last_error: 'last_error' in entry ? entry.last_error : null,
    attempt_count: 'attempt_count' in entry ? entry.attempt_count : null,
  };
}

export function localLifecycleInputFromMergedRide(ride: MergedRide): LocalRideLifecycleInput | null {
  if (!ride.localRideId || !ride.localStatus) return null;
  return {
    id: ride.localRideId,
    status: ride.localStatus,
    sample_count: ride.localSampleCount ?? 0,
    rejected_samples: ride.localRejectedSamples ?? null,
    had_crash_recovery: ride.hadCrashRecovery ? 1 : 0,
  };
}

export function uploadLifecycleInputFromMergedRide(ride: MergedRide): UploadQueueLifecycleInput | null {
  if (!ride.uploadStatus) return null;
  return {
    status: ride.uploadStatus,
    server_ride_id: ride.serverRideId,
    last_error: ride.uploadLastError ?? null,
    attempt_count: ride.uploadAttemptCount ?? null,
  };
}
