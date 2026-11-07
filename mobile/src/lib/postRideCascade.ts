/**
 * Post-ride cascade derivation.
 *
 * This is the single mobile-facing model for the post-ride sequence:
 * saved -> checked -> verified/review. It only consumes local upload state plus
 * the RideStatus response. Visual animation can change; the rider-facing state
 * model should not.
 */

import type { RideClimbEarning, RideStatus, TruthSource } from './api';
import { deriveAttestationView } from './attestation';
import type { PostRideUploadState } from './postRideProgress';

export type PostRideCascadePhase =
  | 'uploading'
  | 'uploaded'
  | 'provisional'
  | 'attested'
  | 'under_review'
  | 'incomplete'
  | 'failed';

export type PostRideCascadeLineState = 'pending' | 'complete' | 'review' | 'failed';

export type PostRideCascadeTruthSource = 'device' | 'attested' | 'onchain';

type KnownPostRideCascadeLineKey =
  | 'uploaded'
  | 'fingerprint'
  | 'metrics'
  | 'progression'
  | 'climbs'
  | 'record_board'
  | 'earnings'
  | 'chain_record';

export type PostRideCascadeLineKey =
  | KnownPostRideCascadeLineKey
  | `climb_earning:${string}`;

export interface PostRideCascadeLine {
  key: PostRideCascadeLineKey;
  label: string;
  state: PostRideCascadeLineState;
  truthSource: PostRideCascadeTruthSource;
  value?: string;
}

export interface PostRideCascadeHero {
  label: string;
  value: string;
  truthSource: PostRideCascadeTruthSource;
  verified: boolean;
}

export interface PostRideCascadeView {
  phase: PostRideCascadePhase;
  title: string;
  subtitle: string;
  hero: PostRideCascadeHero | null;
  lines: PostRideCascadeLine[];
}

interface Params {
  uploadState: PostRideUploadState;
  status: RideStatus | null;
  isIncomplete?: boolean;
  incompleteReason?: string;
}

function hasText(value: string | null | undefined): value is string {
  return typeof value === 'string' && value.trim().length > 0;
}

function formatNumber(value: number): string {
  if (Number.isInteger(value)) return value.toLocaleString('en-US');
  return value.toFixed(1);
}

function derivePhase(
  uploadState: PostRideUploadState,
  status: RideStatus | null,
  isIncomplete = false,
): PostRideCascadePhase {
  if (isIncomplete) return 'incomplete';
  if (uploadState === 'failed') return 'failed';
  if (uploadState === 'uploading') return 'uploading';
  return deriveAttestationView(status).state;
}

function hasHashSignal(status: RideStatus | null): boolean {
  return (
    hasText(status?.rideHashHex) ||
    hasText(status?.preliminaryRideHashHex) ||
    status?.canonicalMatch != null
  );
}

function hasEarnings(status: RideStatus | null): boolean {
  return (
    status?.effortPolicy?.thresholdEconomyState === 'held' ||
    status?.earnings?.calEarned != null ||
    status?.calEarned != null
  );
}

function earningsValue(status: RideStatus | null): string | undefined {
  if (status?.effortPolicy?.thresholdEconomyState === 'held') return 'Held';
  const cal = status?.earnings?.calEarned ?? status?.calEarned;
  if (cal != null) return `+${formatNumber(cal)} CAL`;
  return undefined;
}

function mapTruthSource(source: TruthSource | null | undefined): PostRideCascadeTruthSource {
  return source === 'onchain' ? 'onchain' : 'attested';
}

function formatProgressionValue(status: RideStatus | null): string | undefined {
  const progression = status?.progression;
  if (!progression) return undefined;

  const parts: string[] = [];
  if (progression.tssDelta != null) {
    parts.push(
      `+${formatNumber(progression.tssDelta)} TSS${status?.metrics?.thresholdTrainingState === 'pending' ? ' · Pending' : ''}`,
    );
  }

  return parts.length ? parts.join(' · ') : undefined;
}

function formatSeconds(seconds: number | null | undefined): string | undefined {
  if (seconds == null) return undefined;
  const minutes = Math.floor(seconds / 60);
  const remaining = seconds % 60;
  return `${minutes}:${String(remaining).padStart(2, '0')}`;
}

function formatClimbEarningValue(earning: RideClimbEarning): string | undefined {
  const parts: string[] = [];
  if (earning.tributeBound && earning.calTribute != null) {
    parts.push(`+${formatNumber(earning.calTribute)} CAL`);
  }
  if (earning.recordBoardRank != null) {
    parts.push(`#${earning.recordBoardRank}`);
  }
  const time = formatSeconds(earning.completionTimeS);
  if (time) {
    parts.push(time);
  }
  return parts.length ? parts.join(' · ') : undefined;
}

function deriveClimbEarningLines(status: RideStatus | null): PostRideCascadeLine[] {
  return (status?.climbEarnings ?? []).map((earning, index) => ({
    key: `climb_earning:${earning.climbId || index}`,
    label: earning.climbName ?? `Climb ${index + 1}`,
    state: 'complete',
    truthSource: mapTruthSource(earning.truthSource),
    value: formatClimbEarningValue(earning),
  }));
}

function deriveHero(status: RideStatus | null, phase: PostRideCascadePhase): PostRideCascadeHero | null {
  const tss = status?.metrics?.tss;
  if (tss == null) return null;

  return {
    label: 'Ride TSS',
    value: `${formatNumber(tss)}${status?.metrics?.thresholdTrainingState === 'pending' ? ' · Pending' : ''}`,
    truthSource: phase === 'attested' ? 'onchain' : 'attested',
    verified: phase === 'attested' && status?.metrics?.thresholdTrainingState !== 'pending',
  };
}

function completeWhen(
  condition: boolean,
  truthSource: PostRideCascadeTruthSource,
  value?: string,
): Omit<PostRideCascadeLine, 'key' | 'label'> {
  return {
    state: condition ? 'complete' : 'pending',
    truthSource,
    value,
  };
}

function titleForPhase(
  phase: PostRideCascadePhase,
  incompleteReason?: string,
): Pick<PostRideCascadeView, 'title' | 'subtitle'> {
  switch (phase) {
    case 'uploading':
      return {
        title: 'Ride saved',
        subtitle: 'Saving your ride.',
      };
    case 'uploaded':
      return {
        title: 'Ride saved',
        subtitle: 'Saved. Checking climbs and CAL.',
      };
    case 'provisional':
      return {
        title: 'Ride ready',
        subtitle: 'Climbs and stats are ready. Verification is pending.',
      };
    case 'attested':
      return {
        title: 'Ride ready',
        subtitle: 'Verification complete.',
      };
    case 'under_review':
      return {
        title: 'Needs review',
        subtitle: 'This ride needs a review before it counts.',
      };
    case 'incomplete':
      return {
        title: 'Recording saved',
        subtitle: incompleteReason ?? 'Not enough movement to score.',
      };
    case 'failed':
      return {
        title: 'Upload Waiting',
        subtitle: 'The app will retry automatically when it can.',
      };
  }
}

export function derivePostRideCascade(params: Params): PostRideCascadeView {
  const { uploadState, status, isIncomplete = false, incompleteReason } = params;
  const phase = derivePhase(uploadState, status, isIncomplete);
  const titles = titleForPhase(phase, incompleteReason);
  const uploaded = uploadState === 'uploaded';
  const review = phase === 'under_review';
  const attested = phase === 'attested';
  const climbEarningLines = deriveClimbEarningLines(status);
  const incomplete = phase === 'incomplete';

  const lines: PostRideCascadeLine[] = [
    {
      key: 'uploaded',
      label: 'Ride saved',
      state: incomplete ? 'complete' : uploadState === 'failed' ? 'failed' : uploaded ? 'complete' : 'pending',
      truthSource: 'device',
    },
    {
      key: 'fingerprint',
      label: 'Ride checked',
      ...(incomplete ? {
        state: 'review' as const,
        truthSource: 'device' as const,
        value: 'Not counted',
      } : completeWhen(hasHashSignal(status), 'attested')),
    },
    {
      key: 'metrics',
      label: 'Ride metrics',
      ...(incomplete ? {
        state: 'review' as const,
        truthSource: 'device' as const,
      } : completeWhen(!!status?.metrics, 'attested')),
    },
    {
      key: 'progression',
      label: 'Progress',
      ...completeWhen(
        !!status?.progression,
        mapTruthSource(status?.progression?.truthSource),
        formatProgressionValue(status),
      ),
    },
    {
      key: 'climbs',
      label: 'Climbs matched',
      ...completeWhen(!!status?.hasPatterns || climbEarningLines.length > 0, 'attested'),
    },
    ...climbEarningLines,
    {
      key: 'record_board',
      label: 'Top times',
      ...completeWhen(!!status?.hasLeaderboards, 'attested'),
    },
    {
      key: 'earnings',
      label: 'CAL',
      ...completeWhen(hasEarnings(status), 'onchain', earningsValue(status)),
    },
    {
      key: 'chain_record',
      label: 'Verification',
      state: review ? 'review' : attested ? 'complete' : 'pending',
      truthSource: 'onchain',
    },
  ];

  return {
    phase,
    ...titles,
    hero: deriveHero(status, phase),
    lines,
  };
}
