import type { BalanceRolloutStatus } from './api';

export type GatedBalanceAction = 'withdraw_cal' | 'add_funds' | 'withdraw_to_wallet';
type RolloutRead = {
  isLoading: boolean;
  error: string | null;
  status: { balanceRollout?: Pick<BalanceRolloutStatus, 'enabledActions' | 'actionOrder' | 'enforced' | 'orderValid' | 'blockers'> } | null;
};

// Match native BalanceActionAvailability: unavailable or invalid status closes actions.
export function balanceActionIsOpen({ isLoading, error, status }: RolloutRead, action: GatedBalanceAction): boolean {
  const rollout = status?.balanceRollout;
  if (isLoading || error !== null || !rollout || rollout.enforced !== true || rollout.orderValid !== true
    || !Array.isArray(rollout.blockers) || rollout.blockers.length !== 0
    || !Array.isArray(rollout.enabledActions) || !Array.isArray(rollout.actionOrder)
    || rollout.enabledActions.length > rollout.actionOrder.length
    || !rollout.enabledActions.every((key, index) => key === rollout.actionOrder[index])) return false;
  return rollout.enabledActions.includes(action);
}
