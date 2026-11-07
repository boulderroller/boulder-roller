import { describe, expect, it } from 'vitest';
import { solanaExplorerUrl } from '@/lib/solanaExplorer';

describe('solanaExplorerUrl', () => {
  it('builds devnet transaction links with an explicit cluster parameter', () => {
    expect(solanaExplorerUrl('tx', 'abc123', 'devnet')).toBe(
      'https://explorer.solana.com/tx/abc123?cluster=devnet',
    );
  });

  it('builds mainnet account links without a cluster parameter', () => {
    expect(solanaExplorerUrl('account', 'acct123', 'mainnet-beta')).toBe(
      'https://explorer.solana.com/address/acct123',
    );
  });
});
