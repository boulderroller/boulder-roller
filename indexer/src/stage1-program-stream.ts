/** One durable finalized program feed; legacy and Stage 1 consume the same RPC response. */
import { Connection, PublicKey, ConfirmedSignatureInfo, VersionedTransactionResponse } from '@solana/web3.js';
import { finalizedHeads, finalizedHeadTime, boundaryClock, inBoundaryWindow } from './finalized-head';
import { recordReplayCoverage } from './lag-monitor';
import { config } from './config';
import { getClient, query } from './db';
import { decodeAccount } from './decoder';
import { persistProgramVersion } from './program-version-store';
import { programVersionWindow } from './program-version-window';
import { transientRpcErrorClass } from './rpc-retry';
import { getSyncState, updateSyncState } from './writers/common';
import { activation, canonical, decodeTransactionWitness, digest, encodeFields, epochSchedules, orderStage1Pending, sourceAlert, withoutProofs } from './stage1';

type Legacy = (connection:Connection, info:ConfirmedSignatureInfo, tx:VersionedTransactionResponse)=>Promise<{processed:boolean;events:number}>;
const identities=new WeakMap<Connection,string>();
let sharedConnection:Connection;
export const stage1Connection=():Connection=>sharedConnection??=new Connection(config.rpcUrl, 'finalized');
export async function stage1Identity(connection:Connection):Promise<string> {
  let genesis=identities.get(connection);
  if(!genesis){genesis=await connection.getGenesisHash();identities.set(connection,genesis);}
  await query('INSERT INTO stage1_indexer_namespace(singleton,genesis,program) VALUES(true,$1,$2) ON CONFLICT DO NOTHING',[genesis,config.programId]);
  const bound=(await query('SELECT * FROM stage1_indexer_namespace WHERE singleton')).rows[0];
  if(bound.genesis!==genesis||bound.program!==config.programId)throw new Error('Stage1 indexer namespace mismatch');
  if(!epochSchedules.has(genesis))epochSchedules.set(genesis,await connection.getEpochSchedule());
  return genesis;
}

/** A lower bound from actual chain evidence, never an extrapolated wall clock.
 * The local test-pool adapter additionally needs an exact time for rate expiry.
 */
export async function stage1CoverageTime(connection:Connection,slot:number,known:number|null=null):Promise<number|null> {
  const value=(await query(`SELECT greatest($2::bigint,
    (SELECT covered_time FROM stage1_indexer_stream WHERE singleton AND covered_slot<=$1),
    (SELECT max(block_time) FROM stage1_indexer_transactions WHERE slot<=$1),
    (SELECT max(block_time) FROM stage1_indexer_checkpoints WHERE (checkpoint->>'through_slot')::bigint<=$1)) AS time`,[slot,known])).rows[0].time;
  const lower=value===null?null:Number(value);
  const timedRate=(await query(`SELECT 1 FROM indexed_stage1_assets a WHERE NOT a.closed AND a.data->>'adapter'='1'
    AND (a.data->>'admittedNumerator')::numeric>0 AND (a.data->>'admittedDenominator')::numeric>0
    AND (a.data->>'lastFreshUntil')::bigint>coalesce($1::bigint,0)
    AND EXISTS(SELECT 1 FROM indexed_stage1_hills h WHERE NOT h.closed AND h.data->>'city'=a.data->>'city') LIMIT 1`,[lower])).rows.length;
  if(!timedRate)return lower;
  const exact=await finalizedHeadTime(connection,slot);
  if(lower!==null&&exact<lower)throw new Error('Finalized program time regressed');
  return exact;
}

export async function runStage1ProgramStream(connection:Connection,legacy?:Legacy):Promise<{processed:number;events:number}> {
  programVersionWindow.requireStage1();
  const client=await getClient();let locked=false,legacyAttested=false,processed=0,events=0;
  try {
    locked=(await client.query("SELECT pg_try_advisory_lock(hashtextextended('stage1_program_stream',0)) AS locked")).rows[0].locked;
    if(!locked)return {processed,events};
    const genesis=await stage1Identity(connection);
    await query('INSERT INTO stage1_indexer_stream(singleton) VALUES(true) ON CONFLICT DO NOTHING');
    let state=(await query('SELECT * FROM stage1_indexer_stream WHERE singleton')).rows[0];
    // Do not keep hitting a limited/unavailable provider. The last observation
    // remains usable by the independent boundary-capture scheduler.
    if(new Date(state.retry_at).getTime()>Date.now())return {processed,events};
    const sample=await finalizedHeads.read(connection),head=sample.slot;
    const time=await stage1CoverageTime(connection,head,inBoundaryWindow(boundaryClock.now())?await finalizedHeadTime(connection,head):null);
    if(head<Number(state.observed_slot??0)||head<Number(state.covered_slot??0)||time!==null&&time<Number(state.covered_time??0))throw new Error('Finalized program head regressed');
    await query('UPDATE stage1_indexer_stream SET observed_slot=$1,observed_time=$2,observed_at=$3 WHERE singleton',[head,time,new Date(sample.sampledAt)]);
    let start=(await query('SELECT slot FROM stage1_indexer_activation WHERE genesis=$1 AND program=$2',[genesis,config.programId])).rows[0]?.slot;
    if(start===null||start===undefined) {
      const address=PublicKey.findProgramAddressSync([Buffer.from('program_config')],new PublicKey(config.programId))[0];
      const response=await connection.getAccountInfoAndContext(address,{commitment:'finalized',minContextSlot:head});
      const account=response.value,decoded=account&&account.owner.equals(new PublicKey(config.programId))?decodeAccount(account.data):null;
      if(decoded?.type!=='ProgramConfig'||!decoded.fields.initialized)throw new Error('Missing finalized ProgramConfig');
      programVersionWindow.observe(await persistProgramVersion(genesis,config.programId,Number(encodeFields(decoded.fields).programVersion)));
      programVersionWindow.requireStage1();
      start=await activation(connection,genesis,address.toBase58(),{slot:head});
    }
    if(!legacy&&state.legacy_attached) {
      await query('UPDATE stage1_indexer_stream SET legacy_attached=false WHERE singleton');
      state.legacy_attached=false;
    }
    if(legacy&&!state.legacy_attached) {
      // A handoff may begin with a legacy cursor older than Stage 1 activation,
      // or after standalone Stage 1 ingestion. Re-discover that bounded range;
      // standalone consumption never claims legacy processing occurred.
      const old=await getSyncState();
      const lower=old?.last_tx_signature?Math.min(Number(start),Number(old.last_tx_slot)):0;
      await query(`UPDATE stage1_indexer_stream SET cursor=NULL,cursor_slot=NULL,before=NULL,pending_head=NULL,pending_slot=NULL,
        history_start=$1,legacy_attached=true,covered_at=NULL WHERE singleton`,[lower]);
      state=(await query('SELECT * FROM stage1_indexer_stream WHERE singleton')).rows[0];
    }
    const historyStart=state.history_start===null?Number(start):Number(state.history_start);
    // Persist a page and its original head/fence together. A crash may repeat a
    // page, but cannot skip one. No consumption before the whole range closes.
    const fence=state.before?Number(state.fence_slot):head;
    const fenceTime=state.before?(state.fence_time===null?null:Number(state.fence_time)):time;
    const fenceAt=state.before?state.fence_at:new Date(sample.sampledAt);
    if(!state.cursor&&await connection.getFirstAvailableBlock()>historyStart)throw new Error('Finalized program history no longer covers activation');
    const page=await connection.getSignaturesForAddress(new PublicKey(config.programId),{
      limit:1000,minContextSlot:fence,...(state.before?{before:state.before}:{})},'finalized');
    if(legacy&&(state.before||page[0]?.signature!==state.cursor))recordReplayCoverage(connection,new PublicKey(config.programId));
    const newest=state.pending_head??page[0]?.signature??state.cursor??null;
    const newestSlot=state.pending_slot??page[0]?.slot??state.cursor_slot??null;
    let reached=false;
    await client.query('BEGIN');
    try {
      for(const info of page) {
        if(info.signature===state.cursor){reached=true;break;}
        if(info.slot<historyStart){if(state.cursor)throw new Error('Finalized program cursor missing');reached=true;break;}
        // Failed transactions belong to the common stream too (legacy receipts).
        await client.query(`INSERT INTO stage1_indexer_pending(signature,slot,block_time,legacy_required) VALUES($1,$2,$3,$4)
          ON CONFLICT(signature) DO UPDATE SET legacy_required=stage1_indexer_pending.legacy_required OR EXCLUDED.legacy_required`,[info.signature,info.slot,info.blockTime,Boolean(legacy)]);
      }
      if(page.length<1000&&!reached){if(state.cursor)throw new Error('Finalized program cursor missing');reached=true;}
      await client.query(`UPDATE stage1_indexer_stream SET cursor=$1,cursor_slot=$2,before=$3,pending_head=$4,pending_slot=$5,
        fence_slot=$6,fence_time=$7,fence_at=$8 WHERE singleton`,[reached?newest:state.cursor,reached?newestSlot:state.cursor_slot,
        reached?null:page[page.length-1].signature,reached?null:newest,reached?null:newestSlot,fence,fenceTime,fenceAt]);
      await client.query('COMMIT');
    }catch(error){await client.query('ROLLBACK');throw error;}
    if(!reached)return {processed,events};
    const pending=(await query(`SELECT * FROM (SELECT p.*,count(*) OVER(PARTITION BY slot) AS slot_count FROM stage1_indexer_pending p) p
      WHERE NOT ingested OR ($1 AND NOT legacy_done) ORDER BY slot,signature`,[Boolean(legacy)])).rows;
    // Resolve whole slots before saving immutable witnesses. Bound transaction
    // work at a slot boundary; the durable queue carries any remaining backlog.
    const limit=pending.length>2000?Number(pending[1999].slot):Infinity;
    const batch=pending.filter(p=>Number(p.slot)<=limit);
    const ordered=await orderStage1Pending(connection,batch);
    let sourceHeld=ordered.length!==batch.length,legacyHeld=false;
    for(const info of ordered) {
      let tx:VersionedTransactionResponse|null=null;
      if(!info.ingested||legacy&&!info.legacy_done) {
        tx=await connection.getTransaction(info.signature,{commitment:'finalized',maxSupportedTransactionVersion:0});
        if(!tx||tx.slot!==Number(info.slot)||tx.blockTime===null||!tx.meta)throw new Error('Missing finalized program transaction');
      }
      // Stage 1 decode/account failures do not stop otherwise healthy legacy work.
      if(legacy&&!info.legacy_done) {
        try {
          const result=await legacy(connection,{signature:info.signature,slot:Number(info.slot),blockTime:Number(info.block_time),err:tx!.meta!.err,memo:null},tx!);
          if(!result.processed)throw new Error('Legacy transaction pending');
          await query('UPDATE stage1_indexer_pending SET legacy_done=true WHERE signature=$1',[info.signature]);events+=result.events;processed++;
        }catch{legacyHeld=true;await sourceAlert('legacy_transaction_unavailable');}
      }
      if(Number(info.slot)<Number(start)) {
        await query('UPDATE stage1_indexer_pending SET ingested=true,done=true WHERE signature=$1',[info.signature]);
        continue; // Pre-activation history belongs exclusively to legacy replay.
      }
      if(info.ingested)continue;
      try {
        const witness={...decodeTransactionWitness(info.signature,tx!),epoch:epochSchedules.get(genesis)!.getEpoch(tx!.slot),...(info.block_index==null?{}:{block_index:info.block_index})};
        await client.query('BEGIN');
        try {
          const retained=(await client.query('SELECT stage1_indexer_filter_checkpoint($1::jsonb) AS value',[canonical(withoutProofs(witness))])).rows[0].value;
          await client.query(`INSERT INTO stage1_indexer_transactions(signature,slot,block_time,witness,digest) VALUES($1,$2,$3,$4::jsonb,$5) ON CONFLICT DO NOTHING`,[info.signature,tx!.slot,tx!.blockTime,canonical(retained),digest(retained)]);
          await client.query('UPDATE stage1_indexer_pending SET ingested=true,block_index=$2 WHERE signature=$1',[info.signature,info.block_index]);
          await client.query('COMMIT');
        }catch(error){await client.query('ROLLBACK');throw error;}
      }catch{sourceHeld=true;await sourceAlert('transaction_decode_unavailable');}
    }
    const gaps=(await query('SELECT bool_or(NOT ingested) AS source,bool_or(legacy_required AND NOT legacy_done) AS legacy FROM stage1_indexer_pending')).rows[0];
    if(legacy&&!gaps.legacy&&!legacyHeld) {
      await updateSyncState({...(newest?{last_tx_signature:newest,last_tx_slot:Number(newestSlot)}:{}),last_tx_sync_at:new Date()});
      if(newest){recordReplayCoverage(connection,new PublicKey(config.programId),{head:{slot:fence,sampledAt:new Date(fenceAt).getTime()},signature:newest,slot:Number(newestSlot)});legacyAttested=true;}
    }
    if(!gaps.source&&!sourceHeld) {
      const coveredTime=await stage1CoverageTime(connection,fence,fenceTime);
      await query('UPDATE stage1_indexer_stream SET covered_slot=$1,covered_time=$2,covered_at=$3,observed_time=greatest(observed_time,$2) WHERE singleton',[fence,coveredTime,fenceAt]);
    }
    if(sourceHeld||legacyHeld)throw new Error('Program stream source pending');
    await query('UPDATE stage1_indexer_stream SET attempts=0,retry_at=now() WHERE singleton');
    return {processed,events};
  }catch(error) {
    if(legacy&&!legacyAttested)recordReplayCoverage(connection,new PublicKey(config.programId));
    const kind=transientRpcErrorClass(error)??'program_stream_unavailable';
    await sourceAlert(kind);
    await query(`UPDATE stage1_indexer_stream SET attempts=attempts+1,retry_at=now()+
      (least($1::double precision,$2::double precision*power(2,least(attempts,16)))*(0.5+random()/2))*interval '1 millisecond' WHERE singleton`,
      kind==='rate_limit'?[21_600_000,900_000]:[900_000,1_000]);
    await query('UPDATE stage1_indexer_network SET ready=false WHERE singleton');
    throw error;
  }finally{if(locked)await client.query("SELECT pg_advisory_unlock(hashtextextended('stage1_program_stream',0))");client.release();}
}
