/** Incremental task planner and TypeScript witness producer. No keeper code. */
import { query } from './db';
import { canonical } from './stage1';
import { materializeBoundary } from './stage1-boundary';
const WEEK=604800;
export async function produceBoundaries():Promise<void> {
  const network=(await query('SELECT * FROM stage1_indexer_network WHERE singleton AND ready')).rows[0];if(!network)return;
  const globalCoverage={genesis:network.genesis,program:network.program,from_slot:Number(network.from_slot),from_time:Number(network.from_time),
    through_slot:Number(network.through_slot),through_time:Number(network.through_time),through_epoch:Number(network.through_epoch),cursor:network.cursor};
  const hills=(await query(`SELECT h.address,h.data,c.data AS city FROM indexed_stage1_hills h
    JOIN indexed_stage1_cities c ON c.address=h.data->>'city' WHERE NOT h.closed`)).rows;
  for(const h of hills) {
    const raw=(await query('SELECT * FROM stage1_indexer_hill_coverage WHERE genesis=$1 AND program=$2 AND hill=$3',[network.genesis,network.program,h.address])).rows[0];if(!raw)continue;
    const coverage={...globalCoverage,through_time:Number(raw.through_time)};
    const launch=Number(h.city.seasonAnchor),current=Math.floor((coverage.through_time-launch)/WEEK);
    const last=Number((await query('SELECT max(week) AS week FROM stage1_boundary_tasks WHERE genesis=$1 AND program=$2 AND hill=$3',[network.genesis,network.program,h.address])).rows[0].week??Number(h.data.admittedWeek)-1);
    for(let week=Math.max(last+1,Number(h.data.admittedWeek));week<=current;week++)await query(
      'INSERT INTO stage1_boundary_tasks(genesis,program,hill,week) VALUES($1,$2,$3,$4) ON CONFLICT DO NOTHING',[network.genesis,network.program,h.address,week]);
  }
  const tasks=(await query("SELECT * FROM stage1_boundary_tasks WHERE state<>'complete' AND imported_at IS NULL AND retry_at<=now() ORDER BY updated_at,week,hill LIMIT 100")).rows;
  for(const task of tasks) {
    await query("UPDATE stage1_boundary_tasks SET updated_at=now() WHERE genesis=$1 AND program=$2 AND hill=$3 AND week=$4",[task.genesis,task.program,task.hill,task.week]);
    const h=hills.find(r=>r.address===task.hill);if(!h)continue;
    const raw=(await query('SELECT * FROM stage1_indexer_hill_coverage WHERE genesis=$1 AND program=$2 AND hill=$3',[task.genesis,task.program,task.hill])).rows[0];if(!raw)continue;
    const coverage={...globalCoverage,...Object.fromEntries(['from_slot','from_time','through_slot','through_time','through_epoch'].map(k=>[k,Number(raw[k])]))} as typeof globalCoverage;
    const launch=Number(h.city.seasonAnchor);
    for(const boundary of [launch+Number(task.week)*WEEK,launch+(Number(task.week)+1)*WEEK]) {
      if(boundary>coverage.through_time)continue;
      if((await query('SELECT 1 FROM stage1_boundary_witnesses WHERE genesis=$1 AND program=$2 AND hill=$3 AND boundary=$4',[task.genesis,task.program,task.hill,boundary])).rows.length)continue;
      const params=[task.genesis,task.program,task.hill,boundary];
      const banks=(await query('SELECT checkpoint FROM stage1_boundary_banks($1,$2,$3,$4) ORDER BY block_time,slot',params)).rows.map(r=>r.checkpoint);
      const after=banks.find(p=>p.block_time>=boundary);if(!after)continue;
      const before=banks.filter(p=>p.block_time<boundary);
      const admission=after;
      const lower=before.length?Math.min(...before.map(p=>p.slot)):coverage.from_slot;
      const txs=(await query(`SELECT t.witness FROM stage1_indexer_transactions t JOIN stage1_indexer_transaction_hills h USING(signature)
        WHERE h.hill=$1 AND t.slot>=$2 AND t.slot<=$3 ORDER BY t.slot,(t.witness->>'block_index')::integer`,[task.hill,lower,after.through_slot??after.slot])).rows.map(r=>r.witness);
      const fence={...coverage,through_slot:after.through_slot??after.slot,through_time:after.block_time,through_epoch:after.epoch};
      let value:any,error='historical_boundary_unavailable';
      for(const checkpoint of [...before,after])try {
        const candidate=materializeBoundary(checkpoint,fence,txs,task.hill,boundary,admission);
        value=candidate;if(candidate.opening!==null)break;
      }catch(e){error=(e as Error).message;}
      if(value)await query('INSERT INTO stage1_boundary_witnesses(digest,genesis,program,hill,boundary,witness) VALUES($1,$2,$3,$4,$5,$6::jsonb) ON CONFLICT DO NOTHING',
        [value.digest,task.genesis,task.program,task.hill,boundary,canonical(value)]);
      else {
        await query("UPDATE stage1_boundary_tasks SET state='held',error=$5,attempts=attempts+1,retry_at=now()+interval '15 minutes',updated_at=now() WHERE genesis=$1 AND program=$2 AND hill=$3 AND week=$4",[task.genesis,task.program,task.hill,task.week,error]);
        await query('INSERT INTO stage1_boundary_alerts(genesis,program,hill,week,kind) VALUES($1,$2,$3,$4,$5) ON CONFLICT(genesis,program,hill,week,kind) DO UPDATE SET last_seen=now()',[task.genesis,task.program,task.hill,task.week,error]);
      }
    }
  }
  await query('SELECT stage1_indexer_prune_sources()');
}
