import type { AccountDeletionBlocker } from './api';

const BLOCKER_LABELS: Readonly<Record<string, string>> = Object.freeze({
  balance_remains: 'Balance remains',
  stake_remains: 'Vault position remains',
  claim_remains: 'Pending claim remains',
  unuploaded_rides_unacknowledged: 'Unuploaded rides review',
  policy_review_required: 'Support review',
  preflight_unavailable: 'Account check unavailable',
});

export const ACCOUNT_DELETION_ACTIONS = Object.freeze({
  contactSupport: 'contact_support',
  openBalance: 'open_balance',
  retry: 'retry',
  reviewRecordings: 'review_recordings',
});

export function accountDeletionBlockerLabel(blocker: AccountDeletionBlocker): string {
  if (blocker.code === 'balance_remains' && blocker.asset) {
    return `${blocker.asset} balance`;
  }
  return BLOCKER_LABELS[blocker.code] ?? 'Account requirement';
}

export function accountDeletionFailureLabel(failureCode?: string | null): string | null {
  if (!failureCode) return null;
  return BLOCKER_LABELS[failureCode] ?? 'The previous attempt could not finish';
}

export function accountDeletionNeedsBalance(blockers: AccountDeletionBlocker[]): boolean {
  return blockers.some((blocker) => blocker.action === ACCOUNT_DELETION_ACTIONS.openBalance);
}

export function accountDeletionNeedsSupport(blockers: AccountDeletionBlocker[]): boolean {
  return blockers.some((blocker) => blocker.action === ACCOUNT_DELETION_ACTIONS.contactSupport);
}
