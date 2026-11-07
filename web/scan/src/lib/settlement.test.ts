import { describe, expect, it } from 'vitest';
import { stakerCarryLabel } from './settlement';

describe('staker carry policy labels', () => {
  it('fails closed to the prior staker balance until the on-chain policy marker is projected', () => {
    expect(stakerCarryLabel(undefined)).toBe('Prior staker balance');
    expect(stakerCarryLabel(0)).toBe('Prior staker balance');
  });

  it('labels marked carry as the already-unlocked rounding remainder', () => {
    expect(stakerCarryLabel(1)).toBe('Staker rounding remainder');
  });
});
