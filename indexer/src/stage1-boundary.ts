/** Production boundary rebuild. The keeper's Python rebuild is a separate oracle. */
import { PublicKey } from '@solana/web3.js';
import { canonical, digest } from './stage1';
import { projectSettlementWeekStart } from './observatory';

const WEEK=604800, ZERO=PublicKey.default.toBase58();
const events:Record<string,string>={recordClimbCompletion:'ClimbCompleted',recordClimbCompletionV2:'ClimbCompletedV2',
  recordReleasedClimbCompletion:'ReleasedClimbCompleted',electLocalLegend:'LocalLegendElected',
  resignLocalLegend:'LocalLegendResigned',deactivateLocalLegend:'LocalLegendDormant'};
const fail=(reason:string):never=>{throw new Error(reason);};
const hex=(v:any):string=>typeof v==='string'?v:Buffer.from(v).toString('hex');
const num=(v:any):number=>{const n=Number(v);if(!Number.isSafeInteger(n))fail('unsafe_boundary_integer');return n;};
const integer=(v:any):bigint=>BigInt(v);
const clone=(v:any):any=>JSON.parse(canonical(v)); // Source u64/i64 fields are decimal strings.
function snake(v:any):any {
  if(Array.isArray(v))return v.map(snake);
  if(v&&typeof v==='object')return Object.fromEntries(Object.entries(v).map(([k,x])=>[k.replace(/[A-Z]/g,c=>'_'+c.toLowerCase()),snake(x)]));
  return typeof v==='string'&&v.length<32&&/^-?\d+$/.test(v)?integer(v):v;
}
function term(config:any,week:number,slot:number):number {
  const start=projectSettlementWeekStart({settlement_clock_version:config.settlementClockVersion,
    settlement_clock_v2_starts_at:config.settlementClockV2StartsAt,chain_slot:slot},week);
  if(start===undefined)fail('missing_settlement_clock_lineage');return start!;
}
const order=(a:any,b:any):number=>num(a.timeS)-num(b.timeS)||num(a.recordedAt)-num(b.recordedAt)||Buffer.compare(new PublicKey(a.user).toBuffer(),new PublicKey(b.user).toBuffer());

export function dependencies(rows:any[],hillAddress:string,admission?:any,program?:string):Set<string> {
  const hill=rows.find(a=>a.address===hillAddress)?.fields??admission?.accounts.find((a:any)=>a.address===hillAddress)?.fields;
  if(!hill)return new Set([hillAddress]);
  const climbs=rows.filter(a=>a.type==='Climb'&&hex(a.fields.canonId)===hex(hill.canonId));
  const vaults=rows.filter(a=>a.type==='Vault'&&climbs.some(c=>c.fields.vault===a.address));
  const ids=new Set(vaults.map(v=>String(v.fields.id)));
  const optional=program?vaults.flatMap(v=>{const id=Buffer.alloc(8);id.writeBigUInt64LE(BigInt(v.fields.id));return ['vault_leaderboard','local_legend'].map(seed=>PublicKey.findProgramAddressSync([Buffer.from(seed),id],new PublicKey(program))[0].toBase58());}):[];
  return new Set([hillAddress,hill.city,...optional,...rows.filter(a=>a.type==='ProgramConfig'||climbs.includes(a)||vaults.includes(a)||
    a.type==='Stage1AssetConfig'&&a.fields.city===hill.city||a.type==='Stage1PledgeLot'&&a.fields.hill===hillAddress||
    ['VaultLeaderboard','LocalLegend'].includes(a.type)&&ids.has(String(a.fields.vaultId))).map(a=>a.address)]);
}
export function inputMutation(tx:any,deps:Set<string>,hill:string,rows?:any[],checkpointSlot?:number):any|null {
  if(!tx.writes?.some((a:string)=>deps.has(a)))return null;
  const instructions=(tx.instructions??[]).filter((ix:any)=>{
    const recordTarget=events[ix.name]&&(ix.accounts?.vault??ix.accounts?.localLegend);
    if(recordTarget&&!deps.has(recordTarget))return false;
    if(ix.keys?.length&&!ix.keys.some((a:string)=>deps.has(a)))return false;
    if(['recordRide','creditCal','creditReleasedCal','distributeEpochRewards','updateVaultMetadata','stakeCalInVault','depositCalFromBalance','unstakeCalFromVault','withdrawCalToBalance','harvestRewards','collectStakeRewardsFor','sponsorStage1','postStage1Boost','processStage1Boost','expireStage1Hold','publishStage1ClaimSet','claimStage1','claimStage1Batch'].includes(ix.name))return false;
    if(ix.accounts?.hill&&ix.accounts.hill!==hill&&['pledge','bond'].includes(ix.name)&&rows) {
      // Deposits change shared cap counters, but provider rates are immutable
      // only within an already-admitted epoch. A later bank cannot prove that.
      const assets=rows.filter(a=>a.type==='Stage1AssetConfig'&&tx.writes.includes(a.address));
      if(assets.every(a=>num(a.fields.adapter)===1||
        (a.observed_slot??checkpointSlot)<tx.slot&&integer(a.fields.admittedDenominator)>0n&&tx.epoch===num(a.fields.admittedEpoch)))return false;
    }
    if(ix.accounts?.hill&&ix.accounts.hill!==hill&&['refreshCampaignLot','materializeStage1Lot','convertExcludedPledge','cancelPledge',
      'withdrawPrebond','requestWithdrawal','beginWithdrawal','completeWithdrawal','harvestStage1'].includes(ix.name))return false;
    return true;
  });
  return tx.instructions?.length&&!instructions.length?null:{...tx,instructions};
}
/** Include discoveries retained before a partially failed checkpoint. */
export function transactionHills(tx:any,checkpoints:any[],discovered:{hill:string,address:string}[]):string[] {
  const hills=new Set([...checkpoints.map(p=>p.hill),...discovered.map(r=>r.hill)]);
  return [...hills].filter(hill=>{
    const p=checkpoints.find(p=>p.hill===hill),deps=dependencies(p?.accounts??[],hill,undefined,p?.program);
    for(const row of discovered)if(row.hill===hill)deps.add(row.address);
    return Boolean(inputMutation(tx,deps,hill));
  });
}
function replay(rows:any[],txs:any[]) {
  for(const tx of [...txs].sort((a,b)=>a.slot-b.slot||(a.block_index??0)-(b.block_index??0))) {
    if(!tx.instructions.length||tx.instructions.some((i:any)=>!events[i.name]))fail('unrecoverable_boundary_mutation');
    const vaults=new Set(rows.filter(a=>['VaultLeaderboard','LocalLegend'].includes(a.type)).map(a=>String(a.fields.vaultId)));
    const scopedEvents=tx.events.filter((e:any)=>vaults.has(String(e.fields.vaultId)));
    for(const name of new Set(tx.instructions.map((i:any)=>events[i.name]))) {
      if(tx.instructions.filter((i:any)=>events[i.name]===name).length!==scopedEvents.filter((e:any)=>e.name===name).length)fail('missing_record_events');
    }
    for(const e of scopedEvents) {
      const f=e.fields,vault=String(f.vaultId);
      if(['ClimbCompleted','ClimbCompletedV2','ReleasedClimbCompleted'].includes(e.name)) {
        const row=rows.find(a=>a.type==='VaultLeaderboard'&&String(a.fields.vaultId)===vault)?.fields;
        if(!row)continue;
        if((rows.find(a=>a.fields===row)?.observed_slot??-1)>=tx.slot)continue;
        const next={user:f.rider,timeS:num(f.timeS),recordedAt:String(f.completedAt)};
        const original=[...row.entries],source=rows.find(a=>a.fields===row);
        const compare=(a:any,b:any):number=>{
          if(num(a.timeS)!==num(b.timeS))return num(a.timeS)-num(b.timeS);
          if(!a.user.startsWith('anonymous:')&&!b.user.startsWith('anonymous:'))return order(a,b);
          const unchanged=(v:any)=>original.some(e=>e.user===v.user&&e.timeS===v.timeS&&e.recordedAt===v.recordedAt);
          if(!unchanged(a)||!unchanged(b)||!source.record_order)fail('anonymous_record_tie_order_unavailable');
          return source.record_order.indexOf(a.user)-source.record_order.indexOf(b.user);
        };
        const old=row.entries.find((a:any)=>a.user===next.user);
        if(!old||compare(next,old)<0) {
          row.entries=[...row.entries.filter((a:any)=>a.user!==next.user),next].sort(compare).slice(0,10);
          if(source.record_order)source.record_order=row.entries.map((e:any)=>e.user);
        }
      } else if(['LocalLegendElected','LocalLegendResigned','LocalLegendDormant'].includes(e.name)) {
        const row=rows.find(a=>a.type==='LocalLegend'&&String(a.fields.vaultId)===vault)?.fields;
        if(!row)fail('missing_record_legend');
        if((rows.find(a=>a.fields===row)?.observed_slot??-1)>=tx.slot)continue;
        if(e.name==='LocalLegendElected')Object.assign(row,{holder:f.winner,isActive:true,isBootstrap:f.isBootstrap,termStartEpoch:f.termStartEpoch,termEndEpoch:f.termEndEpoch});
        else if(e.name==='LocalLegendDormant')Object.assign(row,{isActive:false,isBootstrap:false,termStartEpoch:f.termStartEpoch,termEndEpoch:f.termEndEpoch});
        else row.isActive=false;
      }
    }
  }
}
function records(rows:any[],hill:any,boundary:number,slot:number):any {
  const climbs=rows.filter(a=>a.type==='Climb'&&hex(a.fields.canonId)===hex(hill.canonId)&&(a.fields.registeredAt?num(a.fields.registeredAt)<boundary:num(a.registered_before)<=boundary))
    .sort((a,b)=>num(b.fields.canonVersion)-num(a.fields.canonVersion));
  if(!climbs.length)fail('missing_canon_at_boundary');
  const climb=climbs[0],vaults=rows.filter(a=>a.type==='Vault'&&a.address===climb.fields.vault&&a.fields.climb===climb.address);
  if(climb.fields.vault!==ZERO&&vaults.length!==1)fail('missing_record_vault_binding');
  let board:any[]=[],legend:any=null,anonymous=false;
  if(vaults.length) {
    const vault=String(vaults[0].fields.id),boards=rows.filter(a=>a.type==='VaultLeaderboard'&&String(a.fields.vaultId)===vault);
    if(boards.length!==1)fail('missing_record_board');
    const source=boards[0],entries=[...source.fields.entries];
    anonymous=entries.some(e=>e.user.startsWith('anonymous:'));
    if(anonymous) {
      if(!source.record_order||source.record_not_before>boundary||new Set(source.record_order).size!==entries.length)fail('missing_anonymous_record_order');
      entries.sort((a,b)=>source.record_order.indexOf(a.user)-source.record_order.indexOf(b.user));
    }else entries.sort(order);
    if(entries.length>10||new Set(entries.map(e=>e.user)).size!==entries.length||entries.some(e=>num(e.timeS)<=0||!e.user.startsWith('anonymous:')&&(num(e.recordedAt)<=0||num(e.recordedAt)>=boundary)))fail('invalid_record_provenance');
    board=entries.map(e=>({person:e.user,time_s:num(e.timeS),...(!e.user.startsWith('anonymous:')?{recorded_at:num(e.recordedAt)}:{})}));
    const row=rows.find(a=>a.type==='LocalLegend'&&String(a.fields.vaultId)===vault)?.fields;
    if(row&&row.holder!==ZERO) {
      const config=rows.find(a=>a.type==='ProgramConfig')?.fields;if(!config)fail('missing_settlement_clock_lineage');
      const retained=rows.find(a=>a.fields===row)?.record_term;
      legend={person:row.holder,active:row.isActive,bootstrap:row.isBootstrap,term_start:term(config,num(row.termStartEpoch??retained?.[0]),slot),term_end:term(config,num(row.termEndEpoch??retained?.[1]),slot)};
      anonymous ||= row.holder.startsWith('anonymous:');
    }
  }
  const earned=legend&&legend.active&&!legend.bootstrap&&legend.term_start<boundary&&boundary<=legend.term_end?legend.person:null;
  if(legend?.person.startsWith('anonymous:')){delete legend.term_start;delete legend.term_end;}
  return {record_climb:climb.address,record_version:num(climb.fields.canonVersion),board,legend,...(anonymous?{seats:board.map(r=>r.person),earned_legend:earned}:{})};
}
function backing(opening:any,program:string,city:string,hillAddress:string):bigint {
  const {hill,lots,rates}=opening.dung;
  if(!hill.bonded||hill.bonded_at>=BigInt(opening.boundary))return 0n;
  let result=0n;const seen=new Set<string>();
  for(const l of lots) {
    if(l.city!==city||l.hill!==hillAddress)fail('foreign historical DUNG lot');
    let identity:string;
    if(l.owner.startsWith('anonymous:')) {
      if(!['identity_digest','source_digest'].every(k=>/^[0-9a-f]{64}$/.test(l[k]))||!Number.isInteger(l.owner_rank))fail('missing erased lot validation witness');
      identity=l.identity_digest;
    }else {
      const id=Buffer.alloc(8);if(!l.exiting)id.writeBigUInt64LE(integer(l.deposit_id));
      const seeds=l.exiting?[Buffer.from('s1v1_exit'),new PublicKey(l.exit_request).toBuffer()]:[Buffer.from('s1v1_lot'),new PublicKey(l.owner).toBuffer(),id];
      const address=PublicKey.findProgramAddressSync(seeds,new PublicKey(program))[0].toBase58();
      if(address!==l.address)fail('foreign historical DUNG lot');
      identity=digest(['stage1-lot-identity-v1',program,address]);
    }
    if(seen.has(identity))fail('duplicate historical DUNG lot');seen.add(identity);
    if(l.cancelled||l.exiting)continue;
    const slot=num(l.asset_slot),sequence=integer(l.sequence),cutoff=integer(hill.founding_cutoff);
    const founding=!l.converted&&sequence>0n&&sequence<=cutoff&&slot<32&&Boolean(integer(hill.founding_fresh_slots)&(1n<<BigInt(slot)));
    if(!founding&&!l.converted&&sequence<=cutoff)continue;
    let units=integer(l.units);const amount=integer(l.basis_lamports);
    if(founding&&!l.founding) {
      const n=integer(hill.quoted_numerators[slot]),d=integer(hill.quoted_denominators[slot]);
      if(n<=0n||d<=0n)fail('missing immutable founding quote');
      const quoted=(amount*d+n-1n)/n;if(quoted<units)units=quoted;
    }
    const lockEnd=founding?integer(hill.bonded_at)+26n*BigInt(WEEK):integer(l.lock_end);
    const lock=BigInt(opening.boundary)<lockEnd?(founding?26:num(l.lock_weeks)):0;
    if(![0,13,26,52].includes(lock))fail('invalid historical lock');
    const rate=rates[l.mint],expected=PublicKey.findProgramAddressSync([Buffer.from('s1v1_asset'),new PublicKey(l.mint).toBuffer()],new PublicKey(program))[0].toBase58();
    if(!rate||rate.city!==city||rate.mint!==l.mint||rate.asset!==expected||rate.slot<=0||rate.slot>opening.slot||rate.boundary!==opening.boundary||!rate.evidence)fail('invalid historical rate namespace');
    const n=integer(rate.numerator),d=integer(rate.denominator);if(n<=0n||d<=0n)fail('missing historical opening rate');
    const value=units*n/d;result+=value<amount?value:amount;
  }
  return result;
}

export function materializeBoundary(checkpoint:any,coverage:any,transactions:any[],hillAddress:string,boundary:number,admission?:any):any {
  if(['genesis','program'].some(k=>checkpoint[k]!==coverage[k]))fail('foreign_replay_namespace');
  if(!(coverage.from_slot<=checkpoint.slot&&checkpoint.slot<=coverage.through_slot)||coverage.through_time<boundary)fail('finalized_replay_not_through_boundary');
  if((coverage.from_time??checkpoint.block_time)>=boundary&&checkpoint.block_time>=boundary)fail('missing_opening_history');
  if(checkpoint.erased)fail('erased_checkpoint');
  const rows=clone(checkpoint.accounts);
  if(rows.some((a:any)=>a.omitted))fail('erased_checkpoint_account');
  const deps=dependencies(rows,hillAddress,admission,checkpoint.program);
  const interval=(t:any)=>checkpoint.block_time<boundary?checkpoint.slot<t.slot&&t.slot<=coverage.through_slot&&t.block_time<boundary:
    coverage.from_slot<=t.slot&&t.slot<=checkpoint.slot&&t.block_time>=boundary;
  if(transactions.some(t=>interval(t)&&t.erased))fail('erased_replay_gap');
  const mutations:any[]=[];
  const route=(address:string)=>{
    const erased='anonymous:lot:'+digest(['stage1-lot-identity-v1',checkpoint.program,address]);
    return deps.has(erased)?erased:address;
  };
  for(const original of transactions) {
    const tx={...original,writes:original.writes?.map(route),instructions:original.instructions?.map((ix:any)=>({...ix,...(ix.keys?{keys:ix.keys.map(route)}:{})}))};
    const mutation=inputMutation(tx,deps,hillAddress,rows,checkpoint.slot);if(!mutation)continue;
    let needed=false;
    for(const address of tx.writes.filter((a:string)=>deps.has(a))) {
      const row=rows.find((a:any)=>a.address===address),slot=row?.observed_slot??checkpoint.slot,at=row?.observed_time??checkpoint.block_time;
      if(at>=boundary&&coverage.from_slot<=tx.slot&&tx.slot<=slot&&tx.block_time>=boundary)fail('unrecoverable_boundary_mutation');
      if(at<boundary&&slot<tx.slot&&tx.slot<=coverage.through_slot&&tx.block_time<boundary)needed=true;
    }
    if(needed)mutations.push(mutation);
  }
  if(mutations.length) {
    if(mutations.some(t=>mutations.filter(x=>x.slot===t.slot).length>1&&!Number.isInteger(t.block_index))||new Set(mutations.map(t=>`${t.slot}:${t.block_index}`)).size!==mutations.length)fail('ambiguous_same_slot_record_order');
    replay(rows,mutations);
  }
  let hill=rows.find((a:any)=>a.type==='Stage1HillBond'&&a.address===hillAddress)?.fields;
  const absent=!hill;
  if(absent) {
    if(!admission||admission.genesis!==checkpoint.genesis||admission.program!==checkpoint.program||admission.block_time<boundary||admission.erased)fail('missing_hill_admission');
    hill=admission.accounts.find((a:any)=>a.type==='Stage1HillBond'&&a.address===hillAddress)?.fields;if(!hill)fail('missing_hill_admission');
  }
  const city=(absent?admission.accounts:rows).find((a:any)=>a.type==='Stage1CityConfig'&&a.address===hill.city)?.fields;
  if(!city)fail('missing_city');
  const launch=num(city.seasonAnchor),date=new Date(launch*1000);
  if(date.getUTCDay()!==1||date.getUTCHours()!==12||date.getUTCMinutes()||date.getUTCSeconds()||(boundary-launch)%WEEK||boundary<launch)fail('invalid_week_boundary');
  if(absent&&num(hill.admittedWeek)!==(boundary-launch)/WEEK)fail('missing_hill_before_admission_week');
  const assets=rows.filter((a:any)=>a.type==='Stage1AssetConfig'&&a.fields.city===hill.city);
  const lots=absent?[]:rows.filter((a:any)=>a.type==='Stage1PledgeLot'&&a.fields.hill===hillAddress).map((a:any)=>({...snake(Object.fromEntries(Object.entries(a.fields).filter(([k])=>['city','hill','mint','owner','depositId','exitRequest','units','basisLamports','lockWeeks','lockEnd','sequence','assetSlot','converted','cancelled','exiting','founding'].includes(k)))),
    ...(a.fields.owner.startsWith('anonymous:')?{identity_digest:a.lot_identity_digest,source_digest:a.lot_source_digest}:{address:a.address}),
    ...(a.lot_owner_rank!==undefined?{owner_rank:a.lot_owner_rank}:{})}));
  const rates:Record<string,any>={};let openingError:string|undefined;
  for(const asset of assets) {
    const f=asset.fields;if(num(f.adapter)===254)continue;
    const fresh=num(f.adapter)===1?boundary<num(f.lastFreshUntil):checkpoint.epoch===(coverage.through_epoch??checkpoint.epoch)&&checkpoint.epoch===num(f.admittedEpoch);
    const relevant=!absent&&hill.bonded&&num(hill.bondedAt)<boundary&&lots.some((l:any)=>l.mint===f.mint&&!l.cancelled&&!l.exiting&&(l.converted||integer(l.sequence)>integer(hill.foundingCutoff)||integer(l.sequence)>0n&&Boolean(integer(hill.foundingFreshSlots)&(1n<<integer(l.asset_slot)))));
    if(relevant&&(!fresh||integer(f.admittedNumerator)<=0n||integer(f.admittedDenominator)<=0n))openingError='missing_fresh_opening_rate';
    rates[f.mint]={mint:f.mint,city:f.city,asset:asset.address,slot:checkpoint.slot,numerator:integer(f.admittedNumerator),denominator:integer(f.admittedDenominator),boundary,evidence:digest(asset)};
  }
  const openingHill=absent?{city:hill.city,climb:hill.climb,canon_id:hex(hill.canonId),bonded:false,bonded_at:0}:snake(Object.fromEntries(Object.entries(hill).filter(([k])=>['city','climb','canonId','bonded','bondedAt','foundingCutoff','foundingFreshSlots','quotedNumerators','quotedDenominators'].includes(k))));
  let opening:any={boundary,slot:checkpoint.slot,commitment:'finalized',evidence:digest(checkpoint),dung:{hill:openingHill,lots,rates}};
  if(openingError)opening=null;
  else {const amount=backing(opening,checkpoint.program,hill.city,hillAddress);Object.assign(opening,{backing:amount,live:!absent&&hill.bonded&&num(hill.bondedAt)<boundary&&amount>=integer(city.liveLamports)});}
  if(absent)opening.absent=true;
  const board=absent?{record_climb:null,record_version:null,board:[],legend:null}:records(rows,hill,boundary,checkpoint.slot),canon=hex(hill.canonId);
  const source:any={checkpoint,coverage,transactions};if(absent)source.admission=admission;
  const result:any={schema:1,genesis:checkpoint.genesis,program:checkpoint.program,hill:hillAddress,boundary,city:hill.city,
    canon_id:`${canon.slice(0,8)}-${canon.slice(8,12)}-${canon.slice(12,16)}-${canon.slice(16,20)}-${canon.slice(20)}`,
    launch,slot:checkpoint.slot,opening,records:board,records_digest:digest(board),assets:assets.map((a:any)=>a.fields.mint).sort(),source};
  if(openingError)result.opening_error=openingError;
  let frozenOpening:any=null;
  if(opening) {
    const owners=[...new Set<string>(lots.map((l:any)=>l.owner))].sort();
    const frozenLots=lots.map((lot:any)=>({...lot,identity_digest:lot.identity_digest??digest(['stage1-lot-identity-v1',checkpoint.program,lot.address]),source_digest:lot.source_digest??digest(lot),owner_rank:lot.owner_rank??owners.indexOf(lot.owner)}));
    frozenOpening={...opening,dung:{...opening.dung,lots:frozenLots}};
  }
  const legend=board.legend;
  result.erasure_basis={opening:frozenOpening,records:{boundary,...board,seats:board.board.map((r:any)=>r.person),
    earned_legend:board.seats?board.earned_legend:legend&&legend.active&&!legend.bootstrap&&legend.term_start<boundary&&boundary<=legend.term_end?legend.person:null}};
  result.source_digest=digest(source);result.digest=digest(result);return result;
}
