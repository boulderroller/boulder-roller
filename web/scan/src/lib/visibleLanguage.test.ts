import { readFileSync } from 'node:fs';
import { describe, expect, it } from 'vitest';

const transactionPage = readFileSync(
  new URL('../pages/TransactionPage.tsx', import.meta.url),
  'utf8'
);
const vaultPage = readFileSync(new URL('../pages/VaultPage.tsx', import.meta.url), 'utf8');

describe('BoulderScan visible language', () => {
  it('keeps legacy Record Board identifiers out of visible copy', () => {
    expect(transactionPage).not.toMatch(/Record (?:Board|Royalty)/);
    expect(vaultPage).not.toMatch(/Record (?:Board|Royalty)/);
  });

  it('uses the approved compact section and balance labels', () => {
    expect(transactionPage).toContain('title="On chain"');
    expect(transactionPage).not.toContain('Token Flow');
    expect(transactionPage).not.toContain('Protocol token movements');
    expect(transactionPage).toContain('title="Accounts"');
    expect(transactionPage).not.toContain('Overview');
    expect(transactionPage).not.toContain('Chain Details');
    expect(transactionPage).not.toContain('What this transaction touched');
    expect(transactionPage).not.toContain('Slot, fee, and decoded counts');

    for (const label of ['Leaderboard', 'Local Legend', 'Completions', 'Positions', 'Settlements', 'Registration']) {
      expect(vaultPage).toMatch(new RegExp(`name=["']${label}["']`));
    }
    expect(vaultPage).toContain('data-climb-identity');
    for (const retired of ['Vault Balances', 'CAL Tribute', 'DUNG Ready', 'Next Week', 'DUNG Carry', 'Distribution History']) {
      expect(vaultPage).not.toContain(retired);
    }
  });
});
