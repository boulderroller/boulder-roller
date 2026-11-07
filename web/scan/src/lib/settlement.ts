import type { NumericValue } from '@/types';

export function stakerCarryLabel(policyVersion: NumericValue | undefined): string {
  const version = Number(policyVersion ?? 0);
  return Number.isFinite(version) && version >= 1
    ? 'Staker rounding remainder'
    : 'Prior staker balance';
}
