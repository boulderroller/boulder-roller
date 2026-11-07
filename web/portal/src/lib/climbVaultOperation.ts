import type { RiderBalanceOperationStatus, VaultStake } from './api';
import { compareBaseUnits, decimalToBaseUnits } from './tokenAmounts.ts';

export type ClimbVaultAction = 'deposit' | 'withdraw' | 'collect';
export type ClimbVaultOperation = { action: ClimbVaultAction; clientRequestId: string; operationId?: string; priorBaseUnits?: string };
export const CLIMB_ACTION_TYPES = { deposit: 'deposit_cal', withdraw: 'withdraw_cal', collect: 'collect_dung' } as const;
export function validBaseUnits(value: unknown): value is string {
  return typeof value === 'string' && decimalToBaseUnits(value, 0) !== null;
}

/** Do not promote an ambiguous or unresolved position to a proven zero. */
export function climbPosition(stakes: VaultStake[], vaultId: number, signature?: string): VaultStake | null {
  if (stakes.some((row) => row.vaultId == null && (!signature || row.vaultSignature !== signature))) throw new Error('Position identity unavailable');
  const matches = stakes.filter((row) => row.vaultId != null ? row.vaultId === vaultId : row.vaultSignature === signature);
  if (matches.length > 1) throw new Error('Position identity unavailable');
  const position = matches[0] ?? null;
  if (position && (!validBaseUnits(position.calStakedBaseUnits) || !validBaseUnits(position.lpTokensBaseUnits))) throw new Error('Position amounts unavailable');
  return position;
}

export function operationPhase(operation: ClimbVaultOperation, status: RiderBalanceOperationStatus, vaultId: number): 'review' | 'delayed' | 'recorded' | 'pending' {
  if (status.actionType !== CLIMB_ACTION_TYPES[operation.action] || status.referenceType !== 'vault' || status.referenceId !== String(vaultId)) return 'review';
  if (status.needsReview || status.readState === 'needs_review') return 'review';
  if (status.delayed || status.readState === 'delayed') return 'delayed';
  if (status.recorded && status.readState === 'recorded') return 'recorded';
  return status.pending && status.readState === 'pending' ? 'pending' : 'review';
}

export function positionReflectsOperation(operation: ClimbVaultOperation, current: VaultStake | null, pendingBaseUnits?: string): boolean {
  if (operation.action === 'collect') return validBaseUnits(pendingBaseUnits) && compareBaseUnits(pendingBaseUnits, '0') === 0;
  if (!validBaseUnits(operation.priorBaseUnits)) return false;
  if (operation.action === 'withdraw' && !current) return true;
  if (!current) return false;
  const value = operation.action === 'deposit' ? current.calStakedBaseUnits : current.lpTokensBaseUnits;
  if (!validBaseUnits(value)) return false;
  return operation.action === 'deposit' ? compareBaseUnits(value, operation.priorBaseUnits) > 0 : compareBaseUnits(value, operation.priorBaseUnits) < 0;
}
