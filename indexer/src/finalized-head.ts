import { Connection } from '@solana/web3.js';

export type HeadSample = { slot: number; sampledAt: number };
type Rpc = Pick<Connection, 'getSlot'> & { rpcEndpoint?: string };
type Entry = { settled: boolean; at: number; pending: Promise<HeadSample>; value?: HeadSample; high?: number };

/** One attempt per endpoint per 30 seconds, including failures and concurrent callers.
 * The original observation time survives reuse; a cache hit is not fresh evidence.
 */
export class FinalizedHeads {
  private entries = new Map<string | Rpc, Entry>();
  constructor(private now = () => Date.now()) {}
  read(connection: Rpc): Promise<HeadSample> {
    const key = connection.rpcEndpoint ?? connection, previous = this.entries.get(key), at = this.now();
    if (previous && (!previous.settled || at - previous.at < 30_000)) return previous.pending;
    const entry: Entry = { at, settled: false, value: previous?.value, high: previous?.high, pending: undefined! };
    entry.pending = Promise.resolve().then(async () => {
      const slot = await connection.getSlot('finalized');
      if (!Number.isSafeInteger(slot) || slot < 0 || slot < (entry.high ?? 0)) throw new Error('Finalized head unavailable or regressed');
      entry.high = slot;
      return entry.value = { slot, sampledAt: at };
    }).catch(error => { entry.value = undefined; throw error; }).finally(() => { entry.settled = true; });
    this.entries.set(key, entry);
    return entry.pending;
  }
  peek(connection: Rpc): HeadSample | undefined {
    const sample = this.entries.get(connection.rpcEndpoint ?? connection)?.value;
    return sample && this.now() - sample.sampledAt <= 90_000 ? sample : undefined;
  }
}
export const finalizedHeads = new FinalizedHeads();

// Scheduling clock only. Localnet's accelerated validator clock can drive the
// scheduler in the end-to-end harness; it never supplies chain evidence times.
export const boundaryClock = { now: () => Math.floor(Date.now() / 1000) };
export function inBoundaryWindow(time: number): boolean {
  const week = 604800, mondayNoon = 388800;
  return ((time - mondayNoon) % week + week) % week >= week - 90;
}

// Keep both the current head and older pagination/consumer fences. A bounded
// LRU avoids repeated H, H-1, H reads without retaining unlimited slot history.
const times = new Map<string | object, Map<number, Promise<number>>>();
export function finalizedHeadTime(connection: Connection, slot: number): Promise<number> {
  const key = connection.rpcEndpoint ?? connection;
  let cache = times.get(key);
  if (!cache) { cache = new Map(); times.set(key, cache); }
  const retained = cache.get(slot);
  if (retained) { cache.delete(slot); cache.set(slot, retained); return retained; }
  const slots = cache;
  const value = connection.getBlockTime(slot).then(time => {
    if (time === null) throw new Error('Missing finalized head time');
    return time;
  }).catch(error => { if (slots.get(slot) === value) slots.delete(slot); throw error; });
  slots.set(slot, value);
  if (slots.size > 64) slots.delete(slots.keys().next().value!);
  return value;
}
