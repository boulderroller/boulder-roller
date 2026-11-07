import { Connection, PublicKey } from '@solana/web3.js';
import { SOLANA_RPC_URL } from './solana';
import { STAGE1_CASH_MINT } from './stage1';
// Read-only transport metadata comes from the portal RPC configuration, never prepare.
export const stage1Rpc = () => new Connection(SOLANA_RPC_URL, 'finalized');
export async function resolveStage1Lookup(address: PublicKey) {
  const result = await stage1Rpc().getAddressLookupTable(address, { commitment: 'finalized' });
  if (!result.value || result.value.state.lastExtendedSlot >= result.context.slot) return null;
  return result.value;
}
export async function stage1Settlement(signature: string, blockhash: string): Promise<'confirmed' | 'failed' | 'pending'> {
  const rpc = stage1Rpc();
  const read = async () => (await rpc.getSignatureStatuses([signature], { searchTransactionHistory: true })).value[0];
  const status = await read();
  if (status?.confirmationStatus === 'finalized') return status.err ? 'failed' : 'confirmed';
  if (status) return 'pending';
  const finalized = await rpc.isBlockhashValid(blockhash, { commitment: 'finalized' });
  const confirmed = await rpc.isBlockhashValid(blockhash, { commitment: 'confirmed' });
  if (finalized.value || confirmed.value) return 'pending';
  // Absence is only final after both banks reject the hash and history is rechecked.
  const last = await read();
  if (!last) return 'failed';
  return last.confirmationStatus === 'finalized' ? last.err ? 'failed' : 'confirmed' : 'pending';
}


export async function stage1TestPoolFor(intent: import('./portalTransactionIntent').PreparedTransactionIntent) {
  if (!intent.kind.startsWith('stage1_') || !('mint' in intent)) return undefined;
  const pinned = ['J1toso1uCk3RLmjorhTtrVwY9HJ7X8V9yYac6Y7kGCPn','mSoLzYCxHdYgdzU16g5QSh3i5K3z3KZK7ytfqcJm7So','jupSoLaHXQiZZTSfEWMTRRgpnyFm8f6sZdosWBjx93v','DpLPBaRuLnBsR3P3meU1tmiNUxreXwskXBebTYKvNGne',STAGE1_CASH_MINT,'CqDFJWLpr49tB8xjHegy5JR5jwMCfmhicjuWawtKLeCk'];
  if (pinned.includes(intent.mint) && (intent.kind !== 'stage1_pledge' || intent.backingMints.every(m => pinned.includes(m)))) return undefined;
  const program = new PublicKey('EVjP2Vdz9buHNphywPhoybf213poa8EiSW6FGbXWFqYH');
  const address = PublicKey.findProgramAddressSync([new TextEncoder().encode('s1v1_test_pool')], program)[0];
  const rpc = stage1Rpc(), account = await rpc.getAccountInfo(address, 'finalized');
  const discriminator = new Uint8Array(await crypto.subtle.digest('SHA-256', new TextEncoder().encode('account:Stage1TestPool'))).slice(0,8);
  if (!account || !account.owner.equals(program) || account.executable || account.data.length !== 74 || !discriminator.every((b,i) => account.data[i] === b) || account.data[8] !== 1) throw new Error('Unavailable');
  const provider = new PublicKey(account.data.subarray(9,41)), mint = new PublicKey(account.data.subarray(41,73));
  const token = await rpc.getAccountInfo(mint, 'finalized');
  if (!token || token.owner.toBase58() !== 'TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA' || token.data.length !== 82 || token.data[44] !== 9 || token.data[45] !== 1) throw new Error('Unavailable');
  return { provider: provider.toBase58(), mint: mint.toBase58() };
}
