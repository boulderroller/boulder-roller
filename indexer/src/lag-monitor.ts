import { Connection, PublicKey } from '@solana/web3.js';
import { finalizedHeads, HeadSample } from './finalized-head';

export type ReplayLag = {
  status: 'current' | 'behind' | 'unknown';
  lag_slots: number | null;
  checked_through_slot: number | null;
  sampled_head: number | null;
};
type Coverage = { head: HeadSample; signature: string; slot: number };
const coverage = new Map<string, Coverage>();
const key = (connection: Connection, program: PublicKey) => `${connection.rpcEndpoint}:${program}`;
export function recordReplayCoverage(connection: Connection, program: PublicKey, value?: Coverage): void {
  const id = key(connection, program);
  if (value) coverage.set(id, value); else coverage.delete(id);
}

/** Coverage is published only after the replay's own complete signature range
 * and all legacy transactions succeed. Reading health never probes signatures.
 */
export function readReplayLag(connection: Connection, program: PublicKey, sync: Record<string, any> | null | undefined): ReplayLag {
  const head = finalizedHeads.peek(connection), proof = coverage.get(key(connection, program));
  const unknown: ReplayLag = { status: 'unknown', lag_slots: null, checked_through_slot: null, sampled_head: head?.slot ?? null };
  if (!head || !proof || !sync?.last_tx_signature || Date.now() - proof.head.sampledAt > 90_000 || head.slot < proof.head.slot) return unknown;
  if (proof.signature !== sync.last_tx_signature || proof.slot !== Number(sync.last_tx_slot)) return { ...unknown, status: 'behind' };
  return { status: 'current', lag_slots: head.slot - proof.head.slot, checked_through_slot: proof.head.slot, sampled_head: head.slot };
}
export async function measureReplayLag(connection: Connection, program: PublicKey, sync: Record<string, any> | null | undefined): Promise<ReplayLag> {
  try { await finalizedHeads.read(connection); } catch { /* Failed samples make peek unavailable. */ }
  return readReplayLag(connection, program, sync);
}
export const REPLAY_LAG_ALERT_SLOTS = 1000;
export function replayLagNeedsAlert(result: ReplayLag): boolean {
  return result.status !== 'current' || result.lag_slots === null || result.lag_slots >= REPLAY_LAG_ALERT_SLOTS;
}
