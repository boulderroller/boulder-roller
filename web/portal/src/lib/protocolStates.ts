export type RideProofUiState = 'counting' | 'stamped' | 'finalized' | 'needs_review' | 'not_counted';

export interface RideProofStateInput {
  attestationStatus?: string | null;
  status?: string | null;
  canonicalMatch?: boolean | null;
  reviewReason?: string | null;
  coveredEffortSeconds?: number | null;
  paidEffortSeconds?: number | null;
  rewardPolicy?: string | null;
  errorMessage?: string | null;
  finalizedAt?: string | null;
}

export interface RideProofStateCopy {
  label: string;
  detail: string;
}

export const RIDE_PROOF_STATE_COPY: Record<RideProofUiState, RideProofStateCopy> = {
  counting: {
    label: 'Counting',
    detail: 'Reading the ride data now.',
  },
  stamped: {
    label: '',
    detail: '',
  },
  finalized: {
    label: 'Finalized',
    detail: 'Verification complete. CAL finalized.',
  },
  needs_review: {
    label: 'Needs review',
    detail: 'Logged. We need one more check before CAL.',
  },
  not_counted: {
    label: 'Not counted',
    detail: 'Logged. No CAL was counted.',
  },
};

// Tim S1/S2: empty until ratified.
export const PARTLY_COUNTED_COPY = "";
export const ALREADY_COUNTED_COPY = "";

const ROUTE_ESTIMATE_REVIEW_REASON = 'effort_source_route_estimate_only';

export function getRideProofUiState(input: RideProofStateInput): RideProofUiState {
  const status = (input.status || '').toLowerCase();
  const attestationStatus = (input.attestationStatus || '').toLowerCase();

  if (
    (input.coveredEffortSeconds ?? 0) > 0 &&
    input.paidEffortSeconds === 0 &&
    input.rewardPolicy === 'not_counted'
  ) {
    return 'not_counted';
  }

  if (input.finalizedAt) {
    return 'finalized';
  }

  if (
    input.canonicalMatch === false ||
    Boolean(input.reviewReason) ||
    status === 'under_review' ||
    status === 'needs_review' ||
    attestationStatus === 'needs_review'
  ) {
    return 'needs_review';
  }

  if (
    Boolean(input.errorMessage) ||
    status === 'failed' ||
    status === 'rejected' ||
    attestationStatus === 'failed' ||
    attestationStatus === 'rejected'
  ) {
    return 'not_counted';
  }

  if (attestationStatus === 'attested' || attestationStatus === 'stamped') {
    return 'stamped';
  }

  return 'counting';
}

export function getRideEffortTrimCopy(input: RideProofStateInput): string {
  if ((input.coveredEffortSeconds ?? 0) <= 0 || input.paidEffortSeconds == null) return '';
  if (input.paidEffortSeconds === 0 && input.rewardPolicy === 'not_counted') return ALREADY_COUNTED_COPY;
  if (input.paidEffortSeconds > 0) return PARTLY_COUNTED_COPY;
  return '';
}

export function getRideProofStateCopy(input: RideProofStateInput): RideProofStateCopy {
  const trimCopy = getRideEffortTrimCopy(input);
  if (trimCopy) return { ...RIDE_PROOF_STATE_COPY[getRideProofUiState(input)], detail: trimCopy };
  if (
    input.reviewReason === ROUTE_ESTIMATE_REVIEW_REASON ||
    input.rewardPolicy === 'estimated_only'
  ) {
    return {
      label: 'Saved',
      detail: 'Logged. Effort data needed before CAL.',
    };
  }

  return RIDE_PROOF_STATE_COPY[getRideProofUiState(input)];
}

// Each entry is a producer fact about one subject, never a ride-wide rung.
export const SUBJECT_STATE_LABELS = ['Counting', 'Finalized', 'Needs review', 'Not counted'] as const;
export const STATE_SUBJECTS = ['storage', 'matching', 'cal', 'position', 'collection'] as const;
export type StateSubject = typeof STATE_SUBJECTS[number];
export interface SubjectState {
  subject: StateSubject;
  label: string;
  reason: string | null;
}
const SUBJECT_STATE_COPY: Record<string, string> = {
  counting: SUBJECT_STATE_LABELS[0],
  finalized: SUBJECT_STATE_LABELS[1],
  needs_review: SUBJECT_STATE_LABELS[2],
  not_counted: SUBJECT_STATE_LABELS[3],
};

export function readSubjectStates(projection: unknown): SubjectState[] {
  if (!projection || typeof projection !== 'object' || Array.isArray(projection)) return [];
  return STATE_SUBJECTS.flatMap((subject) => {
    const fact = (projection as Record<string, unknown>)[subject];
    if (!fact || typeof fact !== 'object' || Array.isArray(fact)) return [];
    const { state, reason } = fact as Record<string, unknown>;
    const label = subject === 'storage' && state === 'saved' ? 'Saved'
      : typeof state === 'string' && Object.hasOwn(SUBJECT_STATE_COPY, state) ? SUBJECT_STATE_COPY[state] : null;
    return label ? [{ subject, label, reason: typeof reason === 'string' && reason.trim() ? reason : null }] : [];
  });
}
