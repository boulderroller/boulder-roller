import { describe, expect, it } from 'vitest';
import {
  formatAtomic,
  formatStatus,
  formatTimestamp,
  humanizeEventName,
  humanizeLabel,
} from './format';

describe('formatTimestamp', () => {
  it('formats epoch seconds', () => {
    expect(formatTimestamp(1709654400)).toContain('2024');
  });

  it('formats ISO timestamps from the live API', () => {
    expect(formatTimestamp('2025-12-30T16:06:38.000Z')).not.toBe('—');
  });
});

describe('label formatting helpers', () => {
  it('humanizes snake case and camel case labels', () => {
    expect(humanizeLabel('VaultCreated')).toBe('Vault Created');
    expect(humanizeLabel('record_vault_completion')).toBe('Record Vault Completion');
  });

  it('formats status labels consistently', () => {
    expect(formatStatus('recordVaultCompletion')).toBe('Record Vault Completion');
    expect(formatStatus('vault_completed')).toBe('Vault Completed');
  });

  it('keeps V2 completion events on the stable explorer labels', () => {
    expect(humanizeEventName('VaultCompletedV2')).toBe('Climb Completed');
    expect(humanizeEventName('ClimbCompletedV2')).toBe('Climb Completed');
    expect(humanizeEventName('ClimbCompletionFlowAssignedV2')).toBe(
      'Settlement Flow Assigned'
    );
  });
});

describe('formatAtomic', () => {
  it('shows more precision for sub-unit token amounts', () => {
    expect(formatAtomic('7500', 'CAL')).toBe('0.000007 CAL');
  });

  it('uses threshold notation for dust values smaller than the visible precision', () => {
    expect(formatAtomic('1', 'DUNG')).toBe('< 0.000001 DUNG');
  });
});
