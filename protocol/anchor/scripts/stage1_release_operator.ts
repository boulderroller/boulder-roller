// Exact-input operator for the composed release. No implicit account discovery,
// key discovery, root construction, timing changes, or retry after an ambiguous send.
import BN from 'bn.js';
import { AddressLookupTableAccount, AddressLookupTableProgram, PublicKey, SYSVAR_CLOCK_PUBKEY, SYSVAR_SLOT_HASHES_PUBKEY } from '@solana/web3.js';
import { TOKEN_PROGRAM_ID, unpackAccount, createAssociatedTokenAccountIdempotentInstruction, getAssociatedTokenAddressSync } from '@solana/spl-token';
import { resolve } from 'path';
import { fileURLToPath } from 'url';
import { Operator, Operation, pk, bn, requireThat, runOperator, args } from './stage1_operator.js';

import {splitClaimBatches} from './stage1_claim_batches.js';
import { CURRENT_PROGRAM_VERSION, PREVIOUS_PROGRAM_VERSION } from '../generated-program-version.js';

export function acceptedReleaseVersions(action: string): readonly number[] {
  requireThat(['execute', 'advance'].includes(action), 'Release action must be execute or advance');
  return action === 'advance' ? [PREVIOUS_PROGRAM_VERSION, CURRENT_PROGRAM_VERSION] : [CURRENT_PROGRAM_VERSION];
}

export const RELEASE_CALLS = new Set([
  'advanceProgramVersion', 'initCityConfig', 'configureAsset', 'refreshStage1Rate', 'registerStage1TestPool',
  'registerStage1Cash', 'setStage1Publisher', 'configureStage1Dung', 'setStage1Guardian', 'setStage1Registrar',
  'registerRatifiedClimb', 'initHillBond', 'registerStage1Recipient', 'initStage1Settlement', 'openStage1Week',
  'pledge', 'bond', 'harvestStage1', 'freezeStage1Snapshot', 'publishStage1ClaimSet', 'claimStage1',
  'prepareStage1ClaimSet', 'claimStage1Batch', 'prepareStage1DungClaimSet', 'claimStage1DungBatch',
  'closeStage1ClaimSet', 'closeStage1DungClaimSet',
  'closeStage1WeekFunding', 'closeStage1DungMint',
  'sponsorStage1', 'postStage1Boost', 'processStage1Boost',
  'publishStage1Dung', 'publishStage1DungClaimSet', 'claimStage1Dung',
  'requestWithdrawal', 'cancelWithdrawal', 'beginWithdrawal', 'completeWithdrawal',
  'materializeStage1Lot', 'prepareStage1Hold', 'expireStage1Hold', 'skipStage1EmptyWeeks', 'skipStage1DungWeeks',
  'cancelPledge', 'pauseStage1Intake', 'resumeStage1Intake', 'pauseStage1Settlement', 'resumeStage1Settlement',
]);

function exactObject(value: any, names: string[], label: string) {
  requireThat(value && typeof value === 'object' && !Array.isArray(value)
    && Object.keys(value).length === names.length && names.every(n => Object.hasOwn(value, n)), `Exact ${label} fields required`);
}
export function typedValue(type: any, value: any, idl: any): any {
  if (typeof type === 'string') {
    if (type === 'publicKey') return pk(value);
    if (/^[ui](8|16|32|64|128)$/.test(type)) {
      requireThat(typeof value === 'string' && /^-?\d+$/.test(value), 'Integer arguments must be explicit decimal strings');
      const bits = Number(type.slice(1)), signed = type[0] === 'i', n = BigInt(value);
      requireThat(n >= (signed ? -(1n << BigInt(bits - 1)) : 0n)
        && n < (1n << BigInt(signed ? bits - 1 : bits)), 'Integer argument out of range');
      return bits > 32 ? bn(value) : Number(n);
    }
    requireThat((type === 'bool' && typeof value === 'boolean') || (type === 'string' && typeof value === 'string'), 'Unsupported scalar argument');
    return value;
  }
  if ('option' in type) return value === null ? null : typedValue(type.option, value, idl);
  if ('array' in type || 'vec' in type) {
    requireThat(Array.isArray(value) && (!type.array || value.length === type.array[1]), 'Invalid argument array length');
    return value.map(v => typedValue(type.array ? type.array[0] : type.vec, v, idl));
  }
  const definition = idl.types?.find((t: any) => t.name === type.defined)?.type;
  requireThat(definition, 'Unknown argument type');
  if (definition.kind === 'struct') {
    exactObject(value, definition.fields.map((f: any) => f.name), type.defined);
    return Object.fromEntries(definition.fields.map((f: any) => [f.name, typedValue(f.type, value[f.name], idl)]));
  }
  requireThat(definition.kind === 'enum' && typeof value === 'string', 'Explicit unit enum variant required');
  const variant = definition.variants.find((v: any) => v.name === value && !v.fields?.length);
  requireThat(variant, 'Unsupported enum variant');
  return {[value[0].toLowerCase() + value.slice(1)]: {}};
}
function accountValues(definitions: any[], values: any): any {
  exactObject(values, definitions.map(d => d.name), 'instruction account');
  return Object.fromEntries(definitions.map(d => [d.name, d.accounts ? accountValues(d.accounts, values[d.name])
    : d.isOptional && values[d.name] === null ? null : pk(values[d.name])]));
}
function plain(value: any): any {
  if (value instanceof PublicKey) return value.toBase58();
  if (BN.isBN(value) || typeof value === 'bigint') return value.toString();
  if (Buffer.isBuffer(value) || value instanceof Uint8Array) return [...value];
  if (Array.isArray(value)) return value.map(plain);
  if (value && typeof value === 'object') return Object.fromEntries(Object.entries(value).map(([k, v]) => [k, plain(v)]));
  return value;
}
function validateOutcome(assertion: any, idl: any) {
  pk(assertion.account);
  requireThat(assertion.fields && Object.keys(assertion.fields).length > 0, 'Nonempty outcome fields required');
  const tokenFields: Record<string, any> = {amount:'u64',mint:'publicKey',owner:'publicKey',isInitialized:'bool',
    isFrozen:'bool',isNative:'bool',delegatedAmount:'u64',delegate:{option:'publicKey'},closeAuthority:{option:'publicKey'}};
  if(assertion.type==='account-state'){
    const names=Object.keys(assertion.fields);requireThat(names.every(k=>['exists','lamports'].includes(k)) && typeof assertion.fields.exists==='boolean','Explicit account existence outcome required');
    if('lamports' in assertion.fields){requireThat(assertion.fields.exists,'Absent accounts have no lamport balance');typedValue('u64',assertion.fields.lamports,idl);}
    return;
  }
  const definition = assertion.type === 'spl-token'
    ? {kind:'struct',fields:Object.entries(tokenFields).map(([name,type])=>({name,type}))}
    : idl.accounts.find((a: any)=>a.name===assertion.type)?.type;
  requireThat(definition, 'Unknown outcome account type');
  const defined = (t: any): any => t?.defined ? idl.types.find((v: any)=>v.name===t.defined)?.type : t;
  const check = (type: any, value: any) => {
    type=defined(type);
    requireThat(type, 'Unknown outcome field type');
    if (type.option) { if(value!==null) check(type.option,value); return; }
    if (type.array || type.vec) {
      requireThat(Array.isArray(value) && (!type.array || value.length===type.array[1]), 'Invalid outcome array');
      value.forEach((v: any)=>check(type.array ? type.array[0] : type.vec,v)); return;
    }
    if(type==='publicKey') { requireThat(typeof value==='string' && pk(value).toBase58()===value,'Canonical outcome public key required'); return; }
    if(typeof type==='string' && /^[ui](8|16|32|64|128)$/.test(type)) {
      const bits=Number(type.slice(1));
      requireThat(bits>32 ? typeof value==='string' : Number.isInteger(value), 'Invalid outcome integer representation');
      requireThat(String(value)===BigInt(value).toString(),'Canonical outcome integer required');
      typedValue(type,String(value),idl); return;
    }
    requireThat(type==='bool' && typeof value==='boolean' || type==='string' && typeof value==='string', 'Unsupported outcome field value');
  };
  for(const [path,value] of Object.entries(assertion.fields)) {
    let type=definition;
    for(const key of path.split('.')) {
      type=defined(type);
      if(type?.array || type?.vec) {
        requireThat(/^(0|[1-9]\d*)$/.test(key) && (!type.array || Number(key)<type.array[1]), 'Invalid outcome array index');
        type=type.array ? type.array[0] : type.vec;
      } else type=type?.fields?.find((f: any)=>f.name===key)?.type;
      requireThat(type, 'Unknown outcome field');
    }
    check(type,value);
  }
}

export async function releaseOperation(r: Operator, input: any): Promise<Operation> {
  requireThat(Array.isArray(input.calls) && input.calls.length > 0 && input.calls.length <= 8, 'One to eight explicit calls required');
  requireThat(Array.isArray(input.assertions) && input.assertions.length > 0, 'Finalized outcome assertions required');
  acceptedReleaseVersions(r.options.action);
  if (r.options.action === 'advance') {
    const call = input.calls[0], config = r.pda('program_config').toBase58();
    requireThat(input.calls.length === 1 && call.name === 'advanceProgramVersion'
      && Object.keys(call.args ?? {}).length === 2
      && call.args.expectedCurrentVersion === String(PREVIOUS_PROGRAM_VERSION)
      && call.args.newVersion === String(CURRENT_PROGRAM_VERSION)
      && Object.keys(call.accounts ?? {}).length === 2 && call.accounts.programConfig === config
      && call.accounts.admin === r.admin.toBase58() && !(call.remainingAccounts?.length)
      && input.assertions.length === 1 && input.assertions[0].account === config
      && input.assertions[0].type === 'ProgramConfig'
      && Object.keys(input.assertions[0].fields ?? {}).length === 1
      && input.assertions[0].fields.programVersion === CURRENT_PROGRAM_VERSION,
      'Exact single release advance and finalized version assertion required');
  } else requireThat(input.calls.every((c: any) => c.name !== 'advanceProgramVersion'), 'Version mutation requires the advance action');
  const idl: any = r.program.idl;
  input.assertions.forEach((a: any)=>validateOutcome(a,idl));
  const instructions = [];
  let transactions:import('@solana/web3.js').TransactionInstruction[][]|undefined;
  const lookupTables:AddressLookupTableAccount[]=[];
  for(const address of input.lookupTables??[]){
    const key=pk(address),account=await r.read(key);requireThat(account?.owner.equals(AddressLookupTableProgram.programId)&&!account.executable,'Invalid lookup table owner');
    const table=new AddressLookupTableAccount({key,state:AddressLookupTableAccount.deserialize(account!.data)});
    requireThat(table.isActive(),'Lookup table is deactivated');lookupTables.push(table);
  }
  const setup=[];
  for(const entry of input.tokenAccounts??[]){
    exactObject(entry,['mint','owner'],'token account');const mint=pk(entry.mint),owner=pk(entry.owner);
    const address=getAssociatedTokenAddressSync(mint,owner,true);await r.read(mint);await r.read(address);
    setup.push(createAssociatedTokenAccountIdempotentInstruction(r.feePayer,address,owner,mint));
  }
  if(setup.length)requireThat(input.calls.every((c:any)=>['claimStage1','claimStage1Batch','claimStage1Dung','claimStage1DungBatch'].includes(c.name)),'Token setup is only for payout calls');
  for (const call of input.calls) {
    requireThat(RELEASE_CALLS.has(call.name), 'Instruction outside the composed release interface');
    const definition = idl.instructions.find((i: any) => i.name === call.name);
    requireThat(definition, 'Instruction unavailable in the selected program interface');
    exactObject(call.args, definition.args.map((a: any) => a.name), 'instruction argument');
    const args = definition.args.map((a: any) => typedValue(a.type, call.args[a.name], idl));
    const remaining = (call.remainingAccounts ?? []).map((a: any) => {
      requireThat(typeof a.writable === 'boolean' && typeof a.signer === 'boolean', 'Explicit remaining-account privileges required');
      return {pubkey: pk(a.key), isWritable: a.writable, isSigner: a.signer};
    });
    const accounts=accountValues(definition.accounts,call.accounts);
    if(['claimStage1Batch','claimStage1DungBatch'].includes(call.name)){
      requireThat(input.calls.length===1,'Batch splitting requires exactly one claim-batch call');
      const leaves=args[1],width=call.name==='claimStage1Batch'?1:2;
      requireThat(remaining.length===leaves.length*width,'Ordered remaining accounts must match every claim');
      transactions=await splitClaimBatches(leaves.length,async(start,end)=>(r.program.methods as any)[call.name](args[0],leaves.slice(start,end))
        .accountsStrict(accounts).remainingAccounts(remaining.slice(start*width,end*width)).instruction(),r.feePayer,setup,lookupTables);
      for(const ix of transactions.flat())for(const account of ix.keys)await r.read(account.pubkey);
      continue;
    }
    const ix = await (r.program.methods as any)[call.name](...args)
      .accountsStrict(accounts).remainingAccounts(remaining).instruction();
    for (const account of ix.keys) await r.read(account.pubkey,
      !account.pubkey.equals(SYSVAR_CLOCK_PUBKEY) && !account.pubkey.equals(SYSVAR_SLOT_HASHES_PUBKEY));
    instructions.push(ix);
  }
  for (const assertion of input.assertions) await r.read(pk(assertion.account),true,assertion.type==='account-state');
  const check = async () => {
    for (const assertion of input.assertions) {
      requireThat(assertion.fields && Object.keys(assertion.fields).length > 0, 'Nonempty outcome fields required');
      const address = pk(assertion.account);
      const account=assertion.type==='account-state'?await r.read(address,true,true):undefined;
      const value = assertion.type==='account-state'?{exists:account!==null,...(account?{lamports:String(account.lamports)}:{})}:assertion.type === 'spl-token'
        ? unpackAccount(address, await r.read(address), TOKEN_PROGRAM_ID)
        : await r.fetch(assertion.type, address);
      requireThat(value, 'Expected finalized account is missing');
      for (const [field, expected] of Object.entries(assertion.fields)) {
        const observed = field.split('.').reduce((v, key) => v?.[key], value);
        requireThat(JSON.stringify(plain(observed)) === JSON.stringify(expected), `Finalized outcome differs: ${assertion.account}.${field}`);
      }
    }
  };
  if (r.options.action === 'advance' && (await r.fetch('ProgramConfig', r.pda('program_config')))?.programVersion === CURRENT_PROGRAM_VERSION) instructions.length = 0;
  return {instructions:[...setup,...instructions],transactions,lookupTables, assert: check, description: `Composed release: ${input.calls.map((c: any) => c.name).join(', ')}; explicit finalized account outcomes`};
}

if (process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  const supplied = args();
  runOperator('stage1-release', releaseOperation, supplied, acceptedReleaseVersions(supplied.action)).catch(e => { console.error(e.message); process.exitCode = 1; });
}
