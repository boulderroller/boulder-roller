// Shared, explicit-input Stage1 operator transport. No wallet discovery.
import * as anchor from '@coral-xyz/anchor';
import BN from 'bn.js';
import { createHash } from 'crypto';
import { readFileSync } from 'fs';
import { Connection, Keypair, PublicKey, TransactionInstruction, TransactionMessage,
  VersionedTransaction, ComputeBudgetProgram } from '@solana/web3.js';
import { CURRENT_PROGRAM_VERSION } from '../generated-program-version.js';

// Solana SDK ClusterType::get_genesis_hash (full hashes, not CAIP-2 prefixes):
// https://github.com/solana-labs/solana/blob/v1.18.26/sdk/src/genesis_config.rs#L56-L68
export const PUBLIC_GENESIS: Record<string, string> = {
  'mainnet-beta': '5eykt4UsFv8P8NJdTREpY1vzqKqZKvdpKuc147dw2N9d',
  devnet: 'EtWTRABZaYq6iMfeYKouRu166VU2xqa1wcaWoxPkrZBG',
  testnet: '4uhcVJyU9pJkvQyS88uRDiswHXSCkY3zQawwpjk2NsNY',
};

export function credentialFreeRpc(value: string): string {
  let url: URL;
  try { url = new URL(value); } catch { throw new Error('RPC must be a credential-free HTTP(S) origin'); }
  requireThat(['http:', 'https:'].includes(url.protocol) && !url.username && !url.password
    && !url.search && !url.hash && url.pathname === '/', 'RPC must be a credential-free HTTP(S) origin without userinfo, query, fragment or path');
  return url.origin;
}

export function assertDistinctRoleKeys(roles: Record<string, string>) {
  const seen = new Map<string, string>();
  for (const [role, value] of Object.entries(roles)) {
    const key = pk(value).toBase58(), previous = seen.get(key);
    requireThat(!previous, `${role} and ${previous} must be distinct`);
    seen.set(key, role);
  }
}

export const pk = (v: string) => new PublicKey(v);
export const bn = (v: string | number | bigint) => new BN(String(v));
export const u64 = (v: string | number | bigint) => {
  const value = bn(v);
  requireThat(!value.isNeg() && value.lte(new BN('18446744073709551615')), 'Unsigned 64-bit input out of range');
  return value.toArrayLike(Buffer, 'le', 8);
};
export const hash = (v: string | Buffer) => createHash('sha256').update(v).digest('hex');
export function requireThat(value: unknown, message: string): asserts value {
  if (!value) throw new Error(message);
}
export function args(argv = process.argv.slice(2)): Record<string, string> {
  const out: Record<string, string> = {};
  for (let i = 0; i < argv.length; i += 2) {
    requireThat(argv[i].startsWith('--') && argv[i + 1] && !argv[i + 1].startsWith('--'), 'Expected --name value');
    requireThat(!(argv[i].slice(2) in out), 'Duplicate option');
    out[argv[i].slice(2)] = argv[i + 1];
  }
  return out;
}
export function needed(o: Record<string, string>, name: string): string {
  requireThat(o[name], `Missing explicit --${name}`); return o[name];
}
export type Operation = {
  instructions: TransactionInstruction[];
  transactions?: TransactionInstruction[][];
  lookupTables?: import('@solana/web3.js').AddressLookupTableAccount[];
  assert: () => Promise<void>;
  description: string;
  report?: unknown;
};

export class Operator {
  connection: Connection;
  program: anchor.Program;
  programId: PublicKey;
  admin: PublicKey;
  feePayer: PublicKey;
  interface: string;
  idlHash: string;
  before = new Map<string, string | null>();
  floor = 0;
  constructor(public options: Record<string, string>) {
    this.programId = pk(needed(options, 'program-id'));
    this.admin = pk(needed(options, 'admin'));
    this.feePayer = pk(needed(options, 'fee-payer'));
    requireThat(!this.admin.equals(this.feePayer), 'Admin and fee payer must be distinct');
    const rpc = credentialFreeRpc(needed(options, 'rpc'));
    this.options = { ...options, rpc };
    const cluster = needed(options, 'cluster');
    requireThat(['localnet', 'devnet', 'mainnet-beta'].includes(cluster), 'Unknown cluster');
    this.interface = options['program-interface'] ?? (cluster === 'devnet' ? 'devnet' : 'mainnet');
    requireThat(['mainnet', 'devnet'].includes(this.interface), 'Unknown program interface');
    requireThat(cluster !== 'mainnet-beta' || this.interface === 'mainnet', 'Devnet interface cannot target mainnet');
    if (cluster === 'localnet') requireThat(['localhost', '127.0.0.1', '[::1]'].includes(new URL(rpc).hostname), 'Localnet requires loopback RPC');
    this.connection = new Connection(rpc, 'finalized');
    const wallet = { publicKey: this.feePayer,
      signTransaction: async () => { throw new Error('Use exact-input transport'); },
      signAllTransactions: async () => { throw new Error('Use exact-input transport'); } };
    const rawIdl = readFileSync(new URL(this.interface === 'devnet' ? '../idl/boulder_rollers.devnet.json' : '../idl/boulder_rollers.json', import.meta.url), 'utf8');
    this.idlHash = hash(rawIdl);
    const idl = JSON.parse(rawIdl);
    this.program = new anchor.Program(idl, this.programId, new anchor.AnchorProvider(this.connection, wallet, { commitment: 'finalized' }));
  }
  pda(seed: string, ...parts: Buffer[]) {
    return PublicKey.findProgramAddressSync([Buffer.from(seed), ...parts], this.programId)[0];
  }
  validateRoles(input: any) {
    const roles: Record<string, string> = { admin: this.admin.toBase58(), 'fee-payer': this.feePayer.toBase58() };
    for (const role of ['publisher', 'operator', 'guardian', 'registrar', 'testOwner', 'poolManager', 'poolStaker', 'pool', 'mint',
      'validatorList', 'reserve', 'validatorIdentity', 'validatorVote']) {
      if (input[role] !== undefined) roles[role] = input[role];
    }
    assertDistinctRoleKeys(roles);
  }
  async read(key: PublicKey, track = true, trackLamports = false) {
    const requestedFloor = this.floor;
    const response = await this.connection.getAccountInfoAndContext(key, { commitment: 'finalized', minContextSlot: requestedFloor });
    requireThat(response.context.slot >= requestedFloor, 'RPC returned state below finalized floor');
    this.floor = Math.max(this.floor, response.context.slot);
    const a = response.value;
    const digest = a ? hash(Buffer.concat([a.owner.toBuffer(), Buffer.from([Number(a.executable)]), a.data])) : null;
    if (!track) return a;
    const previous = this.before.get(key.toBase58());
    requireThat(previous === undefined || previous === digest, 'State changed during planning; retry');
    this.before.set(key.toBase58(), digest);
    if(trackLamports){
      const name=`${key}:lamports`,balance=a?String(a.lamports):null;
      const prior=this.before.get(name);
      requireThat(prior===undefined||prior===balance,'Lamport balance changed during planning; retry');
      this.before.set(name,balance);
    }
    return a;
  }
  async fetch(type: string, key: PublicKey): Promise<any | null> {
    const a = await this.read(key);
    if (!a) return null;
    requireThat(a.owner.equals(this.programId) && !a.executable, `Invalid ${type} owner`);
    return this.program.coder.accounts.decode(type, a.data);
  }
  async start(acceptedVersions: readonly number[] = [CURRENT_PROGRAM_VERSION]) {
    const genesis = await this.connection.getGenesisHash();
    if (this.options.cluster === 'localnet') requireThat(!Object.values(PUBLIC_GENESIS).includes(genesis), 'Public cluster is not localnet');
    else requireThat(genesis === PUBLIC_GENESIS[this.options.cluster], 'RPC genesis does not match explicit cluster');
    this.floor = await this.connection.getSlot('finalized');
    const executable = await this.read(this.programId);
    requireThat(executable?.executable, 'Program is not executable');
    const config = await this.fetch('ProgramConfig', this.pda('program_config'));
    requireThat(config?.initialized && acceptedVersions.includes(config.programVersion) && config.adminAuthority.equals(this.admin), 'ProgramConfig version/admin mismatch');
  }
  async finalizedAssert(check: () => Promise<void>) {
    this.before.clear(); this.floor = Math.max(this.floor, await this.connection.getSlot('finalized')); await check();
  }
}

export function instructionJson(ix: TransactionInstruction) {
  return { program: ix.programId.toBase58(), keys: ix.keys.map(k => ({ key: k.pubkey.toBase58(), signer: k.isSigner, writable: k.isWritable })), data: ix.data.toString('base64') };
}
export function planFor(r: Operator, tool: string, input: unknown, op: Operation) {
  return { schema: 1, tool, action: r.options.action, cluster: r.options.cluster,
    rpc: r.options.rpc, interface: r.interface, idlHash: r.idlHash,
    programId: r.programId.toBase58(), admin: r.admin.toBase58(), feePayer: r.feePayer.toBase58(),
    input, description: op.description, ...(op.report === undefined ? {} : { report: op.report }), before: [...r.before].sort(([a], [b]) => a.localeCompare(b)),
    instructions: op.instructions.map(instructionJson),
    ...(op.transactions ? {transactions:op.transactions.map(batch=>batch.map(instructionJson))} : {}),
    ...(op.lookupTables?.length ? {lookupTables:op.lookupTables.map(table=>table.key.toBase58())} : {}) };
}

export async function simulateThenSubmit(connection: Connection, tx: VersionedTransaction) {
  const bytes = tx.serialize();
  const simulation = await connection.simulateTransaction(tx, { sigVerify: true, replaceRecentBlockhash: false, commitment: 'finalized' });
  requireThat(!simulation.value.err, `Simulation failed: ${JSON.stringify(simulation.value.err)}\n${simulation.value.logs?.join('\n')}`);
  requireThat(Buffer.from(bytes).equals(Buffer.from(tx.serialize())), 'Transaction changed after simulation');
  // The byte-identical signed transaction is submitted; never rebuild or retry
  // with a fresh blockhash after an ambiguous send. Re-plan from finalized state.
  const signature = await connection.sendRawTransaction(bytes, { skipPreflight: false, preflightCommitment: 'finalized', maxRetries: 3 });
  const result = await connection.confirmTransaction(signature, 'finalized');
  requireThat(!result.value.err, `Finalized transaction failed: ${JSON.stringify(result.value.err)}`);
  return signature;
}

export async function submitPlannedBatches(connection:Connection,feePayer:PublicKey,batches:TransactionInstruction[][],
  tables:import('@solana/web3.js').AddressLookupTableAccount[],signerFor:(key:PublicKey)=>Keypair,
  report:(signature:string,index:number,total:number)=>void):Promise<string[]> {
  const signatures:string[]=[];
  for(const instructions of batches){
    const latest=await connection.getLatestBlockhash('finalized');
    const message=new TransactionMessage({payerKey:feePayer,recentBlockhash:latest.blockhash,
      instructions:[ComputeBudgetProgram.setComputeUnitLimit({units:1_000_000}),...instructions]});
    const tx=new VersionedTransaction(tables.length?message.compileToV0Message(tables):message.compileToLegacyMessage());
    tx.sign(tx.message.staticAccountKeys.slice(0,tx.message.header.numRequiredSignatures).map(signerFor));
    requireThat(tx.serialize().length<=1232,'Transaction exceeds packet limit');
    const signature=await simulateThenSubmit(connection,tx);
    signatures.push(signature);report(signature,signatures.length,batches.length);
  }
  return signatures;
}

export async function runOperator(tool: string, build: (r: Operator, input: any) => Promise<Operation>, supplied = args(), acceptedVersions: readonly number[] = [CURRENT_PROGRAM_VERSION]) {
  const mode = needed(supplied, 'mode');
  requireThat(['plan', 'submit'].includes(mode), 'Mode must be plan or submit');
  needed(supplied, 'action');
  const input = JSON.parse(readFileSync(needed(supplied, 'input'), 'utf8'));
  const r = new Operator(supplied); r.validateRoles(input); await r.start(acceptedVersions);
  const op = await build(r, input);
  const plan = planFor(r, tool, input, op), digest = hash(JSON.stringify(plan));
  if (mode === 'plan') { console.log(JSON.stringify({ digest, plan }, null, 2)); return; }
  const approved = JSON.parse(readFileSync(needed(supplied, 'plan'), 'utf8'));
  requireThat(needed(supplied, 'digest') === digest && approved.digest === digest && hash(JSON.stringify(approved.plan)) === digest,
    'Plan/input/finalized state changed; make and review a new plan');
  const batches=op.transactions??(op.instructions.length?[op.instructions]:[]);
  if (!batches.length) { await r.finalizedAssert(op.assert); console.log('Already satisfied at finalized commitment'); return; }
  const roles:Record<string,string>={admin:r.admin.toBase58(),'fee-payer':r.feePayer.toBase58(),operator:input.operator,publisher:input.publisher,guardian:input.guardian,registrar:input.registrar,
    member:input.member,creator:input.creator,'create-key':input.createKey};
  const signerFor=(key:PublicKey)=>{
    const role=Object.keys(roles).find(role=>roles[role]===key.toBase58()&&supplied[`${role}-keypair`]);
    requireThat(role,`Explicit keypair path missing for signer ${key}`);
    const signer=Keypair.fromSecretKey(Uint8Array.from(JSON.parse(readFileSync(supplied[`${role}-keypair`],'utf8'))));
    requireThat(signer.publicKey.equals(key),`Signer does not match explicit ${role}`);return signer;
  };
  const signatures=await submitPlannedBatches(r.connection,r.feePayer,batches,op.lookupTables??[],signerFor,
    (signature,transaction,totalTransactions)=>console.log(JSON.stringify({signature,transaction,totalTransactions,commitment:'finalized',digest})));
  await r.finalizedAssert(op.assert);
  console.log(JSON.stringify({signatures,commitment:'finalized',digest,outcome:op.description}));
}
