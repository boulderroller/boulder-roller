// Localnet-only bridge. The runner supplies an isolated copy with exactly the
// program/sponsor public keys replaced; production validator logic is unchanged.
import { readFileSync } from 'node:fs';
import { pathToFileURL } from 'node:url';
import { Connection, VersionedTransaction } from '@solana/web3.js';

const input = JSON.parse(readFileSync(0, 'utf8'));
if (new URL(input.rpc).hostname !== '127.0.0.1') throw new Error('Localnet only');
const policy = await import(pathToFileURL(process.env.STAGE1_PORTAL_POLICY!).href);
const connection = new Connection(input.rpc, 'finalized');
const lookups: object[] = [];
const resolve = async (address: any) => {
  const table = (await connection.getAddressLookupTable(address)).value;
  if (table && !lookups.length) lookups.push({ address: table.key.toBase58(), authority: table.state.authority?.toBase58(),
    active: table.isActive(), addresses: table.state.addresses.map(k => k.toBase58()) });
  return table;
};
const versioned = VersionedTransaction.deserialize(Buffer.from(input.prepared.transaction, 'base64')).version === 0;
const validate = (wallet: string, intent: any) => versioned
  ? policy.validateStage1VersionedTransaction(input.prepared, intent, wallet, resolve)
  : policy.validatePreparedTransactionIntent(input.prepared, intent, wallet);
await validate(input.wallet, input.intent);
let rejected = false;
try { await validate('11111111111111111111111111111111', input.intent); } catch { rejected = true; }
if (!rejected) throw new Error('Wrong owner passed the client check');
if (input.intent.kind === 'stage1_pledge') {
  rejected = false;
  try { await validate(input.wallet, { ...input.intent, amountBaseUnits: String(BigInt(input.intent.amountBaseUnits) + 1n) }); }
  catch { rejected = true; }
  if (!rejected) throw new Error('Changed person input passed the client check');
}
process.stdout.write(JSON.stringify({ portal: true, lookups }));
