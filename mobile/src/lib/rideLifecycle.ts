import type { RideStatus } from './api';

export type LocalRideLifecycleStatus =
  | 'recording'
  | 'paused'
  | 'stopped'
  | 'uploaded'
  | string;

export type UploadQueueLifecycleStatus =
  | 'pending'
  | 'uploading'
  | 'failed_retryable'
  | 'failed_auth'
  | 'failed_permanent'
  | 'uploaded'
  | string;

export type RideLifecyclePhase =
  | 'recording'
  | 'paused'
  | 'recoverable'
  | 'ready_to_upload'
  | 'upload_waiting'
  | 'uploading'
  | 'upload_retrying'
  | 'auth_required'
  | 'upload_failed'
  | 'uploaded'
  | 'queued'
  | 'processing'
  | 'scored'
  | 'under_review'
  | 'complete'
  | 'failed'
  | 'unknown';

export type RideLifecycleAction =
  | 'save_interrupted_ride'
  | 'discard_interrupted_ride'
  | 'retry_upload'
  | 'reauthenticate'
  | 'retry_processing'
  | 'open_ride';

export type RideLifecycleQualityStatus = 'unknown' | 'clean' | 'degraded' | 'invalid';
export type RideLifecycleSensorDataState = 'unknown' | 'absent' | 'partial' | 'present';
export type RideLifecycleFailurePhase =
  | 'upload'
  | 'queue'
  | 'metrics'
  | 'enrichment'
  | 'settlement'
  | 'processing'
  | 'unknown';

export interface LocalRideLifecycleInput {
  id: string;
  status: LocalRideLifecycleStatus;
  sample_count: number;
  rejected_samples: string | null;
  had_crash_recovery: number | boolean;
}

export interface UploadQueueLifecycleInput {
  status: UploadQueueLifecycleStatus;
  server_ride_id: string | null;
  last_error?: string | null;
  attempt_count?: number | null;
}

export interface RideLifecycleQuality {
  status: RideLifecycleQualityStatus;
  sensorDataState: RideLifecycleSensorDataState;
  sampleCount: number | null;
  hadCrashRecovery: boolean;
  degradationReasons: string[];
}

export interface RideLifecycleFailure {
  phase: RideLifecycleFailurePhase;
  message: string;
  retryable: boolean;
}

export interface RideLifecycleView {
  phase: RideLifecyclePhase;
  actions: RideLifecycleAction[];
  serverRideId: string | null;
  failure: RideLifecycleFailure | null;
  quality: RideLifecycleQuality;
  dataLossRisk: boolean;
}

export interface DeriveRideLifecycleArgs {
  localRide: LocalRideLifecycleInput | null;
  uploadEntry: UploadQueueLifecycleInput | null;
  serverStatus: RideStatus | null;
}

function isRecovered(localRide: LocalRideLifecycleInput | null): boolean {
  return !!localRide?.had_crash_recovery;
}

function parseRejectedSamples(value: string | null): string[] {
  if (!value) return [];
  try {
    const parsed = JSON.parse(value);
    if (Array.isArray(parsed)) {
      return parsed.map((item) => String(item)).filter(Boolean);
    }
    if (parsed && typeof parsed === 'object') {
      return Object.entries(parsed)
        .filter(([, count]) => Number(count) > 0)
        .map(([reason, count]) => `${reason}:${count}`);
    }
  } catch {
    // Fall through to delimiter parsing below.
  }
  return value
    .split(/[,\n]/)
    .map((item) => item.trim())
    .filter(Boolean);
}

function dedupe(values: Array<string | null | undefined>): string[] {
  return Array.from(new Set(values.filter((v): v is string => !!v)));
}

function deriveQuality(
  localRide: LocalRideLifecycleInput | null,
  serverStatus: RideStatus | null,
): RideLifecycleQuality {
  const serverQuality = serverStatus?.inputQuality;
  const localRejected = parseRejectedSamples(localRide?.rejected_samples ?? null);
  const hadCrashRecovery = isRecovered(localRide);
  const degradationReasons = dedupe([
    ...(serverQuality?.degradationReasons ?? []),
    ...localRejected,
    hadCrashRecovery ? 'RECOVERY:interrupted_recording' : null,
  ]);

  let status: RideLifecycleQualityStatus = serverQuality?.status ?? 'unknown';
  const sampleCount = serverQuality?.sampleCount ?? localRide?.sample_count ?? null;

  if (status === 'unknown' && localRide) {
    status = 'clean';
  }
  if (status === 'clean' && degradationReasons.length > 0) {
    status = 'degraded';
  }
  if (localRide && localRide.status !== 'recording' && sampleCount === 0) {
    status = 'invalid';
  }

  return {
    status,
    sensorDataState: serverQuality?.sensorDataState ?? 'unknown',
    sampleCount,
    hadCrashRecovery,
    degradationReasons,
  };
}

function serverPhase(status: RideStatus): RideLifecyclePhase {
  const stage = status.processingStage ?? status.status;
  switch (stage) {
    case 'queued':
    case 'pending':
      return 'queued';
    case 'uploading':
      return 'uploading';
    case 'processing':
      return 'processing';
    case 'metrics_ready':
    case 'enriched':
      return 'scored';
    case 'under_review':
      return 'under_review';
    case 'completed':
      return 'complete';
    case 'failed':
      return 'failed';
    default:
      return 'unknown';
  }
}

function serverFailure(status: RideStatus | null): RideLifecycleFailure | null {
  if (status?.failure) {
    return {
      phase: status.failure.phase,
      message: status.failure.message,
      retryable: status.failure.retryable,
    };
  }
  if (status?.errorMessage) {
    return {
      phase: 'unknown',
      message: status.errorMessage,
      retryable: !!status.canRetryProcessing,
    };
  }
  return null;
}

function uploadFailure(entry: UploadQueueLifecycleInput): RideLifecycleFailure | null {
  if (!entry.last_error) return null;
  return {
    phase: 'upload',
    message: entry.last_error,
    retryable: entry.status === 'failed_retryable',
  };
}

function actionsFor(
  phase: RideLifecyclePhase,
  serverStatus: RideStatus | null,
): RideLifecycleAction[] {
  switch (phase) {
    case 'recoverable':
      return ['save_interrupted_ride', 'discard_interrupted_ride'];
    case 'ready_to_upload':
    case 'upload_retrying':
    case 'upload_failed':
      return ['retry_upload'];
    case 'auth_required':
      return ['reauthenticate'];
    case 'failed':
      return serverStatus?.canRetryProcessing ? ['retry_processing'] : [];
    case 'uploaded':
    case 'queued':
    case 'processing':
    case 'scored':
    case 'under_review':
    case 'complete':
      return ['open_ride'];
    default:
      return [];
  }
}

export function deriveRideLifecycle({
  localRide,
  uploadEntry,
  serverStatus,
}: DeriveRideLifecycleArgs): RideLifecycleView {
  const quality = deriveQuality(localRide, serverStatus);
  let phase: RideLifecyclePhase = 'unknown';
  let failure: RideLifecycleFailure | null = serverFailure(serverStatus);
  const serverRideId = uploadEntry?.server_ride_id ?? serverStatus?.rideId ?? null;

  if (localRide?.status === 'recording' || localRide?.status === 'paused') {
    phase = isRecovered(localRide)
      ? 'recoverable'
      : localRide.status === 'paused'
        ? 'paused'
        : 'recording';
  } else if (uploadEntry) {
    switch (uploadEntry.status) {
      case 'pending':
        phase = 'upload_waiting';
        break;
      case 'uploading':
        phase = 'uploading';
        break;
      case 'failed_retryable':
        phase = 'upload_retrying';
        failure = uploadFailure(uploadEntry);
        break;
      case 'failed_auth':
        phase = 'auth_required';
        failure = uploadFailure(uploadEntry);
        break;
      case 'failed_permanent':
        phase = 'upload_failed';
        failure = uploadFailure(uploadEntry);
        break;
      case 'uploaded':
        phase = serverStatus ? serverPhase(serverStatus) : 'uploaded';
        break;
      default:
        phase = serverStatus ? serverPhase(serverStatus) : 'unknown';
    }
  } else if (localRide?.status === 'stopped') {
    phase = 'ready_to_upload';
  } else if (localRide?.status === 'uploaded') {
    phase = serverStatus ? serverPhase(serverStatus) : 'uploaded';
  } else if (serverStatus) {
    phase = serverPhase(serverStatus);
  }

  return {
    phase,
    actions: actionsFor(phase, serverStatus),
    serverRideId,
    failure,
    quality,
    dataLossRisk: phase === 'recording' || phase === 'paused' || phase === 'recoverable',
  };
}
