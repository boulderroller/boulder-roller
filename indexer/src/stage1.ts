import { boundaryClock, finalizedHeads, finalizedHeadTime } from './finalized-head';
/** Finalized Stage 1 projections and replay witnesses. No signer/submission path.
 * Program-stream cadence and provider-credit model: see indexer/README.md. */
import { createHash } from 'crypto';
import { Connection, PublicKey, VersionedTransactionResponse, EpochSchedule } from '@solana/web3.js';
import bs58 from 'bs58';
import { config } from './config';
import { decodeAccount, decodeEvents, decodeInstruction, getInstructionAccountMeta } from './decoder';
import { getClient, query } from './db';
import { programVersionWindow } from './program-version-window';
import { transientRpcErrorClass } from './rpc-retry';
import { accountParts } from './stage1-source';
import { persistProgramVersion } from './program-version-store';

export const epochSchedules = new Map<string, EpochSchedule>();

export const STAGE1_TABLES: Record<string, string> = {
  Stage1CityConfig: 'indexed_stage1_cities', Stage1AssetConfig: 'indexed_stage1_assets',
  Stage1HillBond: 'indexed_stage1_hills', Stage1PledgeLot: 'indexed_stage1_lots',
  Stage1WithdrawalRequest: 'indexed_stage1_withdrawals', Stage1WeekFunding: 'indexed_stage1_funding',
  Stage1Recipient: 'indexed_stage1_recipients', Stage1SettlementCursor: 'indexed_stage1_cursors',
  Stage1ClaimSet: 'indexed_stage1_claim_sets',
  Stage1CashConfig: 'indexed_stage1_cash', Stage1Boost: 'indexed_stage1_boosts',
  Stage1BoostHill: 'indexed_stage1_boost_hills', Stage1DungState: 'indexed_stage1_dung_state',
  Stage1DungMint: 'indexed_stage1_dung_mints', Stage1DungClaimSet: 'indexed_stage1_dung_claim_sets',
  Stage1TestPool: 'indexed_stage1_test_pools',
};

/** No byte-array guessing: a u64 array containing small values is still an array. */
export function encodeFields(value: any): any {
  if (value === null || value === undefined) return null;
  if (value.toBase58) return value.toBase58();
  if (typeof value === 'bigint' || value.constructor?.name === 'BN') return value.toString();
  if (Array.isArray(value) || Buffer.isBuffer(value) || value instanceof Uint8Array) return Array.from(value).map(encodeFields);
  if (typeof value === 'object') return Object.fromEntries(Object.entries(value).map(([k,v]) => [k,encodeFields(v)]));
  return value;
}
export function canonical(value: any): string {
  if (typeof value==='bigint') return value.toString();
  if (Array.isArray(value)) return '[' + value.map(canonical).join(',') + ']';
  if (value && typeof value === 'object') return '{' + Object.keys(value).sort().map(k => JSON.stringify(k)+':'+canonical(value[k])).join(',') + '}';
  return JSON.stringify(value);
}
export const digest = (value: any): string => createHash('sha256').update(canonical(value)).digest('hex');

export async function writeStage1Account(type: string, address: string, fields: any, slot: number, execute= query, allowSameSlot=true): Promise<void> {
  programVersionWindow.requireStage1();
  const table = STAGE1_TABLES[type];
  if (!table) throw new Error(`Unknown Stage 1 account ${type}`);
  const data = encodeFields(fields);
  await execute(`INSERT INTO ${table}(address,data,chain_slot) VALUES($1,stage1_indexer_filter_checkpoint($2::jsonb),$3)
    ON CONFLICT(address) DO UPDATE SET data=EXCLUDED.data,chain_slot=EXCLUDED.chain_slot,indexed_at=now(),closed=false
    WHERE EXCLUDED.chain_slot ${allowSameSlot?'>=':'>'} ${table}.chain_slot`, [address,JSON.stringify(data),slot]);
}

export interface Witness {
  signature: string; slot: number; block_time: number | null; success: boolean;
  writes: string[]; instructions: any[]; events: any[];
}

/** Message writability covers CPI, ALT and unlabeled remaining accounts. */
export function decodeTransactionWitness(signature: string, tx: VersionedTransactionResponse): Witness {
  const message: any = tx.transaction.message;
  const staticKeys: PublicKey[] = message.staticAccountKeys ?? message.accountKeys;
  const loaded = tx.meta?.loadedAddresses;
  const keys = [...staticKeys, ...(loaded?.writable ?? []), ...(loaded?.readonly ?? [])].map(k => k.toBase58());
  const h = message.header;
  const writable = (i: number): boolean => i < staticKeys.length
    ? (i < h.numRequiredSignatures ? i < h.numRequiredSignatures-h.numReadonlySignedAccounts : i < staticKeys.length-h.numReadonlyUnsignedAccounts)
    : i < staticKeys.length+(loaded?.writable.length ?? 0);
  const success = tx.meta !== null && tx.meta !== undefined && tx.meta.err === null;
  const instructions: any[] = [];
  const outer = message.compiledInstructions ?? message.instructions ?? [];
  for (let i=0;i<outer.length;i++) {
    const group = [outer[i], ...(tx.meta?.innerInstructions?.find(g => g.index===i)?.instructions ?? [])];
    for (let j=0;j<group.length;j++) {
      const ix = group[j];
      if (keys[ix.programIdIndex] !== config.programId) continue;
      const decoded = decodeInstruction(typeof ix.data==='string' ? Buffer.from(bs58.decode(ix.data)) : Buffer.from(ix.data));
      if (!decoded) throw new Error('Undecodable finalized program instruction');
      const indices: number[] = Array.from(ix.accountKeyIndexes ?? ix.accounts);
      if (indices.some(n => !keys[n])) throw new Error('Incomplete ALT account keys');
      const flatten = (rows:any[]):any[] => rows.flatMap(row => row.accounts ? flatten(row.accounts) : [row]);
      const meta = flatten(getInstructionAccountMeta(decoded.name) ?? []);
      instructions.push({index:`${i}:${j}`, name:decoded.name, args:encodeFields(decoded.data),
        accounts:Object.fromEntries(indices.map((n,k) => [meta[k]?.name ?? `remaining_${k-meta.length}`,keys[n]])),
        keys:indices.map(n => keys[n])});
    }
  }
  return {signature,slot:tx.slot,block_time:tx.blockTime ?? null,success,
    writes:success ? keys.filter((_,i) => writable(i)).sort() : [], instructions,
    events:success ? decodeEvents(tx.meta?.logMessages ?? []).map(e => ({name:e.name,fields:encodeFields(e.data)})) : []};
}

export function withoutProofs(value: any): any {
  if (Array.isArray(value)) return value.map(withoutProofs);
  if (value && typeof value === 'object') return Object.fromEntries(Object.entries(value).filter(([k]) => k!=='proof').map(([k,v]) => [k,withoutProofs(v)]));
  return value;
}

export async function projectTransaction(w: Witness, execute=query): Promise<void> {
  if (!w.success) return;
  for (let i=0;i<w.events.length;i++) {
    const e=w.events[i];
    if (!e.name.startsWith('Stage1')) continue;
    await execute(`INSERT INTO indexed_stage1_events(signature,event_index,name,data,chain_slot,block_time)
      VALUES($1,$2,$3,$4::jsonb,$5,$6) ON CONFLICT DO NOTHING`,[w.signature,i,e.name,JSON.stringify(e.fields),w.slot,w.block_time]);
    if (e.name==='Stage1CashPublished' || e.name==='Stage1DungRolePublished') {
      // A finalized snapshot includes every instruction in its bank. Earlier
      // publication events in that slot cannot reset its payment/close state.
      await writeStage1Account(e.name==='Stage1CashPublished'?'Stage1ClaimSet':'Stage1DungClaimSet',e.fields.claimSet,
        {...e.fields,paid:'0',claimedCount:0,sealed:true},w.slot,execute,false);
    }
    if (e.name==='Stage1DungPublished') await writeStage1Account('Stage1DungMint',e.fields.dung,e.fields,w.slot,execute,false);
  }
  for (const ix of w.instructions) {
    const a=ix.accounts, data=ix.args;
    if (/^(pause|resume)Stage1(Intake|Settlement)$/.test(ix.name)) {
      await execute(`INSERT INTO indexed_stage1_pauses(signature,instruction_index,city,kind,paused,chain_slot)
        VALUES($1,$2,$3,$4,$5,$6) ON CONFLICT DO NOTHING`,
      [w.signature,ix.index,a.city,ix.name.endsWith('Intake')?'intake':'settlement',ix.name.startsWith('pause'),w.slot]);
    }
    const closed: Record<string,string> = {closeStage1ClaimSet:'indexed_stage1_claim_sets',closeStage1DungClaimSet:'indexed_stage1_dung_claim_sets',closeStage1WeekFunding:'indexed_stage1_funding',closeStage1DungMint:'indexed_stage1_dung_mints'};
    if (closed[ix.name]) await execute(`UPDATE ${closed[ix.name]} SET closed=true,chain_slot=$2 WHERE address=$1 AND chain_slot<=$2`,[a.claimSet??a.funding??a.dung,w.slot]);
    if (!['claimStage1','claimStage1Batch','claimStage1Dung','claimStage1DungBatch'].includes(ix.name)) continue;
    // Erased claimants have no owner payout projection. Current writable
    // claim-set banks still carry the aggregate paid/count truth.
    if(typeof data.person==='string'&&data.person.startsWith('anonymous:'))continue;
    const dung=ix.name.includes('Dung'), batch=ix.name.endsWith('Batch');
    const leaves=batch?data.leaves:[data];
    const registration=await execute('SELECT data FROM indexed_stage1_recipients WHERE address=$1',[a.registration]);
    const recipient=registration.rows[0]?.data?.recipient;
    if (!recipient) throw new Error('Missing finalized recipient for payout projection');
    for (let i=0;i<leaves.length;i++) {
      const leaf=leaves[i];
      const set=batch ? a[`remaining_${dung?2*i+1:i}`] : a.claimSet;
      let metadata=await execute(`SELECT data FROM ${dung?'indexed_stage1_dung_claim_sets':'indexed_stage1_claim_sets'} WHERE address=$1`,[set]);
      let terms=metadata.rows[0]?.data;
      if (!terms) {
        const event=await execute(`SELECT data FROM indexed_stage1_events WHERE name=$1 AND data->>'claimSet'=$2 ORDER BY chain_slot LIMIT 1`,[dung?'Stage1DungRolePublished':'Stage1CashPublished',set]);
        terms=event.rows[0]?.data;
      }
      if (dung && terms) {
        metadata=await execute('SELECT data FROM indexed_stage1_dung_mints WHERE address=$1',[terms.dung]);
        if (!metadata.rows[0]) metadata=await execute("SELECT data FROM indexed_stage1_events WHERE name='Stage1DungPublished' AND data->>'dung'=$1 LIMIT 1",[terms.dung]);
        terms={...terms,...metadata.rows[0]?.data};
      }
      if (!terms?.hill || terms.week===undefined || !terms.mint) throw new Error('Missing finalized publication for payout projection');
      await execute(`INSERT INTO indexed_stage1_payouts(claim_set,leaf_index,signature,hill,week,mint,person,recipient,amount,kind,chain_slot)
        VALUES($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11) ON CONFLICT(claim_set,leaf_index) DO NOTHING`,
      [set,leaf.index,w.signature,terms.hill,terms.week,terms.mint,data.person,recipient,leaf.amount,dung?'dung':'cash',w.slot]);
      const table=dung?'indexed_stage1_dung_claim_sets':'indexed_stage1_claim_sets';
      await execute(`UPDATE ${table} SET data=data || jsonb_build_object('paid',
        GREATEST(COALESCE((data->>'paid')::numeric,0),(SELECT sum(amount) FROM indexed_stage1_payouts WHERE claim_set=$1))::text,
        'claimedCount',GREATEST(COALESCE((data->>'claimedCount')::bigint,0),(SELECT count(*) FROM indexed_stage1_payouts WHERE claim_set=$1)))
        WHERE address=$1`,[set]);
    }
  }
}

/** Per-type discovery; only each hill's dependencies enter retained sources. */
const discriminator=(type:string)=>bs58.encode(createHash('sha256').update('account:'+type).digest().subarray(0,8));
async function filtered(connection:Connection,type:string,extra:any[]=[],minContextSlot?:number) {
  const response=await connection.getProgramAccounts(new PublicKey(config.programId),{commitment:'finalized',withContext:true,
    filters:[{memcmp:{offset:0,bytes:discriminator(type)}},...extra],...(minContextSlot?{minContextSlot}:{})});
  if(minContextSlot!==undefined&&response.context.slot<minContextSlot)throw new Error('Capture bank is behind finalized head');
  return response;
}
export function accountRow(item:any):any {
  const raw=Buffer.from(item.account.data),decoded=decodeAccount(raw);
  if(!decoded)throw new Error('Undecodable finalized dependency account');
  return {address:item.pubkey.toBase58(),type:decoded.type,fields:encodeFields(decoded.fields),...accountParts(decoded.type,raw),raw_digest:createHash('sha256').update(raw).digest('hex')};
}
export async function captureStage1(connection:Connection,genesis:string,floor?:{slot:number;time:number}):Promise<{checkpoints:any[];held:boolean}> {
  const {dependencies}=await import('./stage1-boundary');
  let schedule=epochSchedules.get(genesis);if(!schedule){schedule=await connection.getEpochSchedule();epochSchedules.set(genesis,schedule);}
  const discovered:any[]=[];let held=false;
  for(const type of ['ProgramConfig',...Object.keys(STAGE1_TABLES).filter(t=>t!=='Stage1PledgeLot')]) {
    const response=await filtered(connection,type,[],floor?.slot);
    for(const item of response.value) {
      try {const row=accountRow(item);discovered.push(row);
        if(STAGE1_TABLES[row.type])await writeStage1Account(row.type,row.address,row.fields,response.context.slot);
      } catch(error) {held=true;await sourceAlert('account_decode');if(type==='ProgramConfig')throw error;}
    }
    if(STAGE1_TABLES[type])await query(`UPDATE ${STAGE1_TABLES[type]} SET closed=true,chain_slot=$1 WHERE NOT closed AND chain_slot<=$1 AND NOT(address=ANY($2::text[]))`,[response.context.slot,response.value.map(i=>i.pubkey.toBase58())]);
  }
  const authority=discovered.find(a=>a.type==='ProgramConfig');
  if(!authority?.fields.initialized)throw new Error('Missing finalized ProgramConfig');
  programVersionWindow.observe(await persistProgramVersion(genesis,config.programId,authority.fields.programVersion));
  programVersionWindow.requireStage1();
  const checkpoints=[];
  for(const hill of discovered.filter(a=>a.type==='Stage1HillBond')) {
    try {
    const rows=[...discovered];
    const remember=async(items:readonly any[])=>{for(const item of items)await query('INSERT INTO stage1_indexer_dependencies(hill,address) VALUES($1,$2) ON CONFLICT DO NOTHING',[hill.address,item.pubkey.toBase58()]);};
    const lots=await filtered(connection,'Stage1PledgeLot',[{memcmp:{offset:41,bytes:hill.address}}],floor?.slot);
    await remember(lots.value);
    for(const item of lots.value) {const row=accountRow(item);rows.push(row);await writeStage1Account(row.type,row.address,row.fields,lots.context.slot);}
    await query("UPDATE indexed_stage1_lots SET closed=true,chain_slot=$1 WHERE NOT closed AND data->>'hill'=$2 AND chain_slot<=$1 AND NOT(address=ANY($3::text[]))",[lots.context.slot,hill.address,lots.value.map(i=>i.pubkey.toBase58())]);
    const climbs=await filtered(connection,'Climb',[{memcmp:{offset:104,bytes:bs58.encode(Buffer.from(hill.fields.canonId))}}],floor?.slot);
    await remember(climbs.value);
    for(const item of climbs.value)rows.push(accountRow(item));
    const vaultKeys=[...new Set(rows.filter(a=>a.type==='Climb').map(a=>a.fields.vault))].filter(a=>a!==PublicKey.default.toBase58());
    for(const address of vaultKeys) {
      await remember([{pubkey:new PublicKey(address)}]);
      const account=await connection.getAccountInfo(new PublicKey(address),{commitment:'finalized',minContextSlot:floor?.slot});
      if(!account)throw new Error('Missing canonical Vault');
      const vault=accountRow({pubkey:new PublicKey(address),account});rows.push(vault);
      const id=Buffer.alloc(8);id.writeBigUInt64LE(BigInt(vault.fields.id));
      for(const type of ['VaultLeaderboard','LocalLegend']) {
        const response=await filtered(connection,type,[{memcmp:{offset:8,bytes:bs58.encode(id)}}],floor?.slot);
        await remember(response.value);rows.push(...response.value.map(accountRow));
      }
    }
    for(const lot of rows.filter(a=>a.type==='Stage1PledgeLot')) {
      const required=PublicKey.findProgramAddressSync([Buffer.from('s1v1_asset'),new PublicKey(lot.fields.mint).toBuffer()],new PublicKey(config.programId))[0].toBase58();
      if(!rows.some(a=>a.address===required))throw new Error('Missing dependency asset');
    }
    if(!rows.some(a=>a.address===hill.fields.city))throw new Error('Missing dependency city');
    await remember([...dependencies(rows,hill.address,undefined,config.programId)].map(address=>({pubkey:new PublicKey(address)})));
    const selected=rows.filter(a=>dependencies(rows,hill.address).has(a.address)).sort((a,b)=>a.address.localeCompare(b.address));
    // A dependency snapshot must be one bank. Larger hills are split into
    // bounded reads, retaining each account's bank rather than claiming one.
    const accounts:any[]=[];let slot=Number.MAX_SAFE_INTEGER,latest=0;
    for(let i=0;i<selected.length;i+=100) {
      const batch=selected.slice(i,i+100),response=await connection.getMultipleAccountsInfoAndContext(batch.map(a=>new PublicKey(a.address)),{commitment:'finalized',minContextSlot:floor?.slot});
      if(floor&&response.context.slot<floor.slot)throw new Error('Capture bank is behind finalized head');
      const blockTime=await finalizedHeadTime(connection,response.context.slot);
      if(floor&&blockTime<floor.time)throw new Error('Capture bank time is behind finalized head');
      slot=Math.min(slot,response.context.slot);latest=Math.max(latest,response.context.slot);
      response.value.forEach((account,n)=>{
        if(!account)throw new Error('Dependency disappeared during capture');
        accounts.push({...accountRow({pubkey:new PublicKey(batch[n].address),account}),observed_slot:response.context.slot,observed_time:blockTime});
      });
    }
    const blockTime=await finalizedHeadTime(connection,slot);
    const complete={genesis,program:config.programId,hill:hill.address,slot,through_slot:latest,block_time:blockTime,epoch:schedule.getEpoch(slot),accounts};
    const againLots=await filtered(connection,'Stage1PledgeLot',[{memcmp:{offset:41,bytes:hill.address}}],latest);
    const againClimbs=await filtered(connection,'Climb',[{memcmp:{offset:104,bytes:bs58.encode(Buffer.from(hill.fields.canonId))}}],latest);
    const membership=(items:readonly any[])=>items.map(i=>i.pubkey.toBase58()).sort().join(',');
    const againAssets=await filtered(connection,'Stage1AssetConfig',[{memcmp:{offset:9,bytes:hill.fields.city}}],latest);
    if(membership(againAssets.value)!==rows.filter(a=>a.type==='Stage1AssetConfig'&&a.fields.city===hill.fields.city).map(a=>a.address).sort().join(','))throw new Error('Asset inventory changed during capture');
    if(membership(lots.value)!==membership(againLots.value)||membership(climbs.value)!==membership(againClimbs.value))throw new Error('Dependency inventory changed during capture');
    const client=await getClient();
    try {
      await client.query('BEGIN');
      const checkpoint=(await client.query('SELECT stage1_indexer_filter_checkpoint($1::jsonb) AS value',[canonical(complete)])).rows[0].value;
      await client.query(`INSERT INTO stage1_indexer_checkpoints(digest,genesis,program,hill,slot,block_time,checkpoint)
        VALUES($1,$2,$3,$4,$5,$6,$7::jsonb) ON CONFLICT DO NOTHING`,[digest(checkpoint),genesis,config.programId,hill.address,slot,blockTime,canonical(checkpoint)]);
      await client.query('COMMIT');checkpoints.push(checkpoint);
    }catch(error){await client.query('ROLLBACK');throw error;}finally{client.release();}
    }catch(error){if(transientRpcErrorClass(error))throw error;held=true;await sourceAlert('hill_source_unavailable');}
  }
  return {checkpoints,held};
}

/** Durable bounded discovery of the 0x4D advance. Never replay older program history. */
export async function activation(connection:Connection,genesis:string,configAddress:string,floor:any):Promise<number> {
  const saved=(await query('SELECT * FROM stage1_indexer_activation WHERE genesis=$1 AND program=$2',[genesis,config.programId])).rows[0];
  if(saved?.slot!==null&&saved?.slot!==undefined)return Number(saved.slot);
  const page=await connection.getSignaturesForAddress(new PublicKey(configAddress),{limit:1000,...(saved?.before?{before:saved.before}:{})},'finalized');
  for(const info of page) {
    if(info.err){await query(`INSERT INTO stage1_indexer_activation(genesis,program,before) VALUES($1,$2,$3) ON CONFLICT(genesis,program) DO UPDATE SET before=EXCLUDED.before`,[genesis,config.programId,info.signature]);continue;}
    const tx=await connection.getTransaction(info.signature,{commitment:'finalized',maxSupportedTransactionVersion:0});
    if(!tx)throw new Error('Missing activation transaction');
    const w=decodeTransactionWitness(info.signature,tx);
    if(!w.success)throw new Error('Incomplete activation transaction');
    // Successful execution proves the version write even with truncated logs.
    const advanced=w.instructions.some(i=>i.name==='advanceProgramVersion'&&i.accounts.programConfig===configAddress&&
      Number(i.args.expectedCurrentVersion)===76&&Number(i.args.newVersion)===77);
    const initialized=w.instructions.some(i=>i.name==='initializeProgramConfig');
    if(advanced) {
      await query(`INSERT INTO stage1_indexer_activation(genesis,program,slot,kind) VALUES($1,$2,$3,$4)
        ON CONFLICT(genesis,program) DO UPDATE SET slot=EXCLUDED.slot,kind=EXCLUDED.kind`,[genesis,config.programId,info.slot,'version_advance']);
      return info.slot;
    }
    if(initialized)throw new Error('Stage1 initialization version unproven');
    await query(`INSERT INTO stage1_indexer_activation(genesis,program,before) VALUES($1,$2,$3)
      ON CONFLICT(genesis,program) DO UPDATE SET before=EXCLUDED.before`,[genesis,config.programId,info.signature]);
  }
  if(!page.length&&!saved&&process.env.STAGE1_LOCALNET==='1'&&['127.0.0.1','localhost','[::1]'].includes(new URL(config.rpcUrl).hostname)) {
    // Snapshot-seeded local genesis has no activation transaction. Coverage
    // starts at our observation; no earlier boundary is certified.
    await query("INSERT INTO stage1_indexer_activation(genesis,program,slot,kind) VALUES($1,$2,$3,'observed_genesis')",[genesis,config.programId,floor.slot]);
    return floor.slot;
  }
  throw new Error('Stage1 activation discovery pending');
}

export async function sourceAlert(kind:string){console.warn(JSON.stringify({event:'stage1_source_held',kind}));await query(`INSERT INTO stage1_indexer_alerts(kind,attempts) VALUES($1,1) ON CONFLICT(kind) DO UPDATE SET attempts=stage1_indexer_alerts.attempts+1,last_seen=now()`,[kind]);}

export async function orderStage1Pending(connection:Connection,pending:any[],alert=sourceAlert):Promise<any[]> {
  const ordered:any[]=[];
  for(const slot of [...new Set<number>(pending.map(p=>Number(p.slot)))].sort((a,b)=>a-b)) {
    try {
      const same=pending.filter(p=>Number(p.slot)===slot);
      // The whole discovered slot count includes peers already ingested on a
      // prior attempt. Retain verified positions; singleton means no position.
      if(same.every(p=>Number.isInteger(p.block_index))) {ordered.push(...same.sort((a,b)=>a.block_index-b.block_index));continue;}
      if(Math.max(same.length,...same.map(p=>Number(p.slot_count??1)))===1) {ordered.push(same[0]);continue;}
      const block=await connection.getBlockSignatures(slot,'finalized');
      if(!block)throw new Error('Missing finalized block order');
      const rows=pending.filter(p=>Number(p.slot)===slot).map(p=>({...p,block_index:block.signatures.indexOf(p.signature)}));
      if(rows.some(p=>p.block_index<0))throw new Error('Missing finalized transaction position');
      ordered.push(...rows.sort((a,b)=>a.block_index-b.block_index));
    }catch(error){if(transientRpcErrorClass(error))throw error;await alert('block_order_unavailable');break;}
  }
  return ordered;
}


/** Monday 12:00 UTC; bootstrap once, then one bank on each side of the boundary. */
export function boundaryCaptureDue(last:number|null,time:number):boolean {
  const week=604800,mondayNoon=388800; // 1970-01-05 12:00 UTC
  const boundary=Math.floor((time-mondayNoon)/week)*week+mondayNoon;
  return last===null||last<boundary||time>=boundary+week-90&&last<boundary+week-90;
}

async function rememberInputs(rows:any[]):Promise<void> {
  const {dependencies}=await import('./stage1-boundary');
  const fields:Record<string,string[]>={Climb:['canonId','vault'],Vault:['id','climb'],
    Stage1HillBond:['city','canonId','climb'],Stage1AssetConfig:['city']};
  for(const row of rows) {
    if(fields[row.type])await query(`INSERT INTO stage1_indexer_links(address,type,fields) VALUES($1,$2,$3::jsonb)
      ON CONFLICT(address) DO UPDATE SET fields=EXCLUDED.fields`,[row.address,row.type,canonical(Object.fromEntries(fields[row.type].map(k=>[k,row.fields[k]])))]);
    if(row.type==='Stage1PledgeLot')await query('INSERT INTO stage1_indexer_dependencies(hill,address) VALUES($1,$2) ON CONFLICT DO NOTHING',[row.fields.hill,row.address]);
  }
  const links=(await query('SELECT address,type,fields FROM stage1_indexer_links')).rows;
  const programConfig=PublicKey.findProgramAddressSync([Buffer.from('program_config')],new PublicKey(config.programId))[0].toBase58();
  for(const hill of links.filter(r=>r.type==='Stage1HillBond')) {
    const deps=dependencies(links,hill.address,undefined,config.programId);deps.add(programConfig);
    if(hill.fields.climb)deps.add(hill.fields.climb);
    for(const vault of links.filter(r=>r.type==='Vault'&&r.fields.climb===hill.fields.climb)) {
      deps.add(vault.address);const id=Buffer.alloc(8);id.writeBigUInt64LE(BigInt(vault.fields.id));
      for(const seed of ['vault_leaderboard','local_legend'])deps.add(PublicKey.findProgramAddressSync([Buffer.from(seed),id],new PublicKey(config.programId))[0].toBase58());
    }
    // A newly linked Climb already names its Vault, even if the Vault was not
    // written in this refresh. Board/Legend PDAs follow once its id is known.
    for(const climb of links.filter(r=>r.type==='Climb'&&canonical(r.fields.canonId)===canonical(hill.fields.canonId)))if(climb.fields.vault!==PublicKey.default.toBase58())deps.add(climb.fields.vault);
    for(const address of deps)await query('INSERT INTO stage1_indexer_dependencies(hill,address) VALUES($1,$2) ON CONFLICT DO NOTHING',[hill.address,address]);
  }
}

/** Refresh only writable message keys, including CPI and ALT; never poll accounts. */
export async function refreshStage1Writes(connection:Connection,genesis:string,witnesses:Witness[]):Promise<void> {
  const addresses=[...new Set(witnesses.flatMap(w=>w.writes))].filter(a=>!a.startsWith('anonymous:'));
  const minContextSlot=Math.max(0,...witnesses.map(w=>w.slot));
  const rows:any[]=[];
  for(let i=0;i<addresses.length;i+=100) {
    const batch=addresses.slice(i,i+100),response=await connection.getMultipleAccountsInfoAndContext(batch.map(a=>new PublicKey(a)),{commitment:'finalized',minContextSlot});
    if(response.context.slot<minContextSlot)throw new Error('Written account bank is behind transaction');
    for(let n=0;n<batch.length;n++) {
      const address=batch[n],account=response.value[n];
      if(!account) {
        for(const table of Object.values(STAGE1_TABLES))await query(`UPDATE ${table} SET closed=true,chain_slot=$2,indexed_at=now() WHERE address=$1 AND chain_slot<=$2`,[address,response.context.slot]);
        continue;
      }
      if(!account.owner.equals(new PublicKey(config.programId)))continue;
      const decoded=decodeAccount(account.data);if(!decoded)throw new Error('Undecodable written program account');
      const fields=encodeFields(decoded.fields),type=decoded.type;
      if(type==='ProgramConfig') {
        if(!fields.initialized)throw new Error('Uninitialized ProgramConfig');
        programVersionWindow.observe(await persistProgramVersion(genesis,config.programId,fields.programVersion));
        programVersionWindow.requireStage1();
      }
      if(STAGE1_TABLES[type])await writeStage1Account(type,address,fields,response.context.slot);
      rows.push({address,type,fields});
    }
  }
  await rememberInputs(rows);
}

/** Independently supervised consumer of the common program feed. */
export async function runStage1Replay(connection:Connection,options:{shared?:boolean}={}):Promise<{processed:number;events:number}> {
  programVersionWindow.requireStage1();const client=await getClient();let locked=false,healthyCaptureHold=false;
  try {
    locked=(await client.query("SELECT pg_try_advisory_lock(hashtextextended('stage1_indexer_replay',0)) AS locked")).rows[0].locked;
    if(!locked)return {processed:0,events:0};
    const {runStage1ProgramStream,stage1Identity,stage1CoverageTime}=await import('./stage1-program-stream');
    let streamError:unknown;
    if(!options.shared)try{await runStage1ProgramStream(connection);}catch(error){streamError=error;}
    const genesis=await stage1Identity(connection);
    const stream=(await query('SELECT * FROM stage1_indexer_stream WHERE singleton')).rows[0];
    if(stream?.observed_slot==null){if(streamError)throw streamError;return {processed:0,events:0};}
    // Capture even during transaction holds. A missed Monday bank cannot be
    // recovered by pretending a later account read happened before the boundary.
    let captured:{checkpoints:any[];held:boolean}|undefined;
    const wall=boundaryClock.now();
    // Wall time requests a check, never an expensive capture of a bank still on
    // the previous side. Exact head time is shared/cached even during feed holds.
    const last=stream.last_capture_time??stream.last_capture_wall;
    const wallDue=boundaryCaptureDue(last===null?null:Number(last),wall);
    const chainDue=stream.observed_time!==null&&boundaryCaptureDue(last===null?null:Number(last),Number(stream.observed_time));
    if(wallDue||chainDue) {
      const head=await finalizedHeads.read(connection),time=await finalizedHeadTime(connection,head.slot);
      if(boundaryCaptureDue(last===null?null:Number(last),time)) {
        captured=await captureStage1(connection,genesis,{slot:head.slot,time});
        await rememberInputs(captured.checkpoints.flatMap(p=>p.accounts));
        // A valid captured bank completes its phase durably. Empty inventory
        // keeps only a scheduling marker from the authorized head, not wall time;
        // that marker never participates in coverage or boundary evidence.
        if(!captured.held)await query('UPDATE stage1_indexer_stream SET last_capture_time=$1,last_capture_wall=$2 WHERE singleton',[
          captured.checkpoints.length?Math.min(...captured.checkpoints.map(p=>p.block_time)):null,time]);
      }
    }
    const checkpoints=(await query(`SELECT DISTINCT ON(hill) checkpoint FROM stage1_indexer_checkpoints
      WHERE genesis=$1 AND program=$2 ORDER BY hill,slot DESC`,[genesis,config.programId])).rows.map(r=>r.checkpoint);
    if(stream.before){await query('UPDATE stage1_indexer_network SET ready=false WHERE singleton');return {processed:0,events:0};}
    // No tail of an unresolved slot may be consumed, even if its response was
    // already fetched. The first incomplete source holds every subsequent slot.
    const pending=(await query(`SELECT x.witness FROM stage1_indexer_pending p JOIN stage1_indexer_transactions x USING(signature)
      WHERE NOT p.done AND p.ingested AND p.slot<coalesce((SELECT min(slot) FROM stage1_indexer_pending WHERE NOT ingested),9223372036854775807)
      ORDER BY p.slot,p.block_index`)).rows.map(r=>r.witness);
    await refreshStage1Writes(connection,genesis,pending);
    const discovered=(await query('SELECT hill,address FROM stage1_indexer_dependencies')).rows;
    const {transactionHills}=await import('./stage1-boundary');
    for(const witness of pending) {
      await client.query('BEGIN');
      try {
        // Lock/re-read the retained row: an erasure after refresh must not let
        // an in-memory pre-erasure witness recreate personal projections.
        const retained=(await client.query('SELECT witness FROM stage1_indexer_transactions WHERE signature=$1 FOR UPDATE',[witness.signature])).rows[0]?.witness;
        if(!retained)throw new Error('Queued source missing');
        for(const hill of transactionHills(retained,checkpoints,discovered))await client.query('INSERT INTO stage1_indexer_transaction_hills(signature,hill) VALUES($1,$2) ON CONFLICT DO NOTHING',[retained.signature,hill]);
        await projectTransaction(retained,client.query.bind(client));
        await client.query('UPDATE stage1_indexer_pending SET done=true WHERE signature=$1',[retained.signature]);
        await client.query('COMMIT');
      }catch(error){await client.query('ROLLBACK');throw error;}
    }
    const knownTime=await stage1CoverageTime(connection,Number(stream.covered_slot??stream.observed_slot),stream.covered_time===null?null:Number(stream.covered_time));
    if(knownTime===null){if(captured?.held)throw new Error('Stage1 source capture pending');return {processed:pending.length,events:0};}
    stream.covered_time=knownTime;
    await query('UPDATE stage1_indexer_stream SET covered_time=$1,observed_time=greatest(observed_time,$1) WHERE singleton',[knownTime]);
    if(!(await query('SELECT 1 FROM stage1_indexer_network WHERE singleton')).rows.length) {
      // Initialization needs an actual slot/time pair, not a newer head paired
      // with a conservative historical time. An empty inventory waits for its
      // first source; it cannot manufacture an observation floor.
      const first=(await query('SELECT slot,block_time FROM stage1_indexer_checkpoints ORDER BY slot LIMIT 1')).rows[0]??
        (await query('SELECT slot,block_time FROM stage1_indexer_transactions ORDER BY slot LIMIT 1')).rows[0];
      if(!first){if(captured?.held)throw new Error('Stage1 source capture pending');return {processed:pending.length,events:0};}
      await query(`INSERT INTO stage1_indexer_network(singleton,genesis,program,from_slot,from_time,through_slot,through_time,through_epoch,ready)
        VALUES(true,$1,$2,$3,$4,$3,$4,$5,false) ON CONFLICT DO NOTHING`,[genesis,config.programId,first.slot,first.block_time,epochSchedules.get(genesis)!.getEpoch(Number(first.slot))]);
    }
    const incomplete=(await query('SELECT 1 FROM stage1_indexer_pending WHERE NOT done LIMIT 1')).rows.length;
    if(incomplete||streamError||stream.covered_slot===null||stream.attempts>0||!stream.covered_at||Date.now()-new Date(stream.covered_at).getTime()>90_000) {
      await query('UPDATE stage1_indexer_network SET ready=false WHERE singleton');
      if(captured?.held)throw new Error('Stage1 source capture pending');
      return {processed:pending.length,events:0};
    }
    const slot=Number(stream.covered_slot),time=Number(stream.covered_time),epoch=epochSchedules.get(genesis)!.getEpoch(slot);
    // Failed captures hold only their hills. Successful hills and an idle,
    // contiguous stream can still move forward without another full snapshot.
    const ready=captured?.held?captured.checkpoints:checkpoints;
    for(const p of ready) {
      const initial=(await query('SELECT slot,block_time FROM stage1_indexer_checkpoints WHERE hill=$1 ORDER BY slot LIMIT 1',[p.hill])).rows[0];
      if(slot<Number(initial.slot))continue;
      await query(`INSERT INTO stage1_indexer_hill_coverage(genesis,program,hill,from_slot,from_time,through_slot,through_time,through_epoch)
        VALUES($1,$2,$3,$4,$5,$6,$7,$8) ON CONFLICT(genesis,program,hill) DO UPDATE SET
        through_slot=greatest(stage1_indexer_hill_coverage.through_slot,EXCLUDED.through_slot),
        through_time=greatest(stage1_indexer_hill_coverage.through_time,EXCLUDED.through_time),through_epoch=EXCLUDED.through_epoch`,[genesis,config.programId,p.hill,initial.slot,initial.block_time,slot,time,epoch]);
    }
    await query(`UPDATE stage1_indexer_network SET through_slot=greatest(through_slot,$1),through_time=greatest(through_time,$2),
      through_epoch=greatest(through_epoch,$3),ready=true,updated_at=s.covered_at FROM stage1_indexer_stream s WHERE stage1_indexer_network.singleton AND stage1_indexer_network.from_slot<=$1
      AND s.attempts=0 AND s.covered_slot=$1 AND s.covered_time=$2 AND s.before IS NULL
      AND s.covered_at>now()-interval '90 seconds' AND NOT EXISTS(SELECT 1 FROM stage1_indexer_pending WHERE NOT done)`,[slot,time,epoch]);
    const {produceBoundaries}=await import('./stage1-producer');await produceBoundaries();
    if(captured?.held){healthyCaptureHold=ready.length>0;throw new Error('Stage1 source capture pending');}
    return {processed:pending.length,events:0};
  }catch(error){if(!healthyCaptureHold)await query('UPDATE stage1_indexer_network SET ready=false WHERE singleton');throw error;}
  finally{if(locked)await client.query("SELECT pg_advisory_unlock(hashtextextended('stage1_indexer_replay',0))");client.release();}
}
