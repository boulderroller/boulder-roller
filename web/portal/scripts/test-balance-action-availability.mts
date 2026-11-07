import { test } from 'node:test';
import assert from 'node:assert/strict';
import { balanceActionIsOpen } from '../src/lib/balanceActionAvailability.ts';
const actionOrder = ['collect_dung', 'deposit_cal', 'withdraw_cal', 'add_funds', 'withdraw_to_wallet'];
const status = { balanceRollout: { enabledActions: actionOrder, actionOrder, enforced: true, orderValid: true, blockers: [] } };
for (const action of ['withdraw_cal', 'add_funds', 'withdraw_to_wallet'] as const) {
  test(`${action}: enabled`, () => assert.equal(balanceActionIsOpen({ status, isLoading: false, error: null }, action), true));
  test(`${action}: disabled`, () => assert.equal(balanceActionIsOpen({ status: { balanceRollout: { ...status.balanceRollout, enabledActions: actionOrder.slice(0, 2) } }, isLoading: false, error: null }, action), false));
  test(`${action}: loading fails closed even with cached status`, () => assert.equal(balanceActionIsOpen({ status, isLoading: true, error: null }, action), false));
  test(`${action}: error fails closed even with cached status`, () => assert.equal(balanceActionIsOpen({ status, isLoading: false, error: 'unavailable' }, action), false));
  test(`${action}: missing status fails closed`, () => assert.equal(balanceActionIsOpen({ status: null, isLoading: false, error: null }, action), false));
}
