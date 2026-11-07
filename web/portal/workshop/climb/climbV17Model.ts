import geography from '../map/data/philadelphia.json';
import {boardRecords,clock,effortHref,fixtures,historyFor,personalBest,profileHref,signed,type BoardEffort,type Effort,type Gates,type Viewer} from '../effort/model';
import {elevationAt} from '../v15/charts/GradeStrip';
import type {BoardQuery,LeaderboardEntry,RouteGeometry,RowPower} from '../v15';

export type BondingState='prebond'|'bonded'|'stale'|'rehearsal';
export const scenarios=[{value:'wises',label:'Wises Mill'},{value:'black-rock',label:'Black Rock'},{value:'wall',label:'Levering / Lyceum'},{value:'andorra-road',label:'Andorra Road'},{value:'new-best',label:'Wises · replayed new best'},{value:'successor',label:'Version 2 · fresh leaderboard'},{value:'earlier-version',label:'Earlier version 1'},{value:'no-vault-rides',label:'No vault · leaderboard from rides'},{value:'no-vault-empty',label:'No vault · honest empty state'}];
export const periods=[{value:'all-time',label:'All time'},{value:'2016',label:'2016'},{value:'2015',label:'2015'}];
export const overallNote="Each rider's fastest ascent. Power with ⚡ was measured by a power meter. Power with ≈ is an estimate from the time and the climb, at a standard rider weight.";
export function climbState(search:string){
 const p=new URLSearchParams(search),scenario=scenarios.some(s=>s.value===p.get('scenario'))?p.get('scenario')!:'wises';
 const viewer:Viewer=p.get('viewer')==='visitor'?'visitor':p.get('viewer')==='anon'?'anon':'rider';
 const gates:Gates=scenario==='successor'||scenario==='new-best'?'v2':scenario==='earlier-version'?'v1':p.get('gates')==='v2'?'v2':'v1';
 const bonding:BondingState=['prebond','stale','rehearsal'].includes(p.get('bonding')??'')?p.get('bonding') as BondingState:'bonded';
 return {scenario,viewer,gates,bonding,compare:p.get('compare')==='none'?'none' as const:p.get('compare')==='fastest'?'fastest' as const:'best' as const};
}
export type ClimbState=ReturnType<typeof climbState>;
export function climbHref(state:Partial<ClimbState>={}){return `/?${new URLSearchParams({'climb-preview':'1',surface:'climb',variant:'climb-v17',...state})}`;}

/** Reuse the retained public OSM centerline. Slice at the supplied profile's
 * finish, interpolating on its paired distance samples; no ride track is added. */
export function climbGeometry(terrain:Effort):RouteGeometry{
 const source=geography.climbs.find(c=>c.name===terrain.name)!;
 const end=terrain.profile.at(-1)!.d,coordinates:[number,number][]=[];
 for(let i=0;i<source.profile.length;i++){
  const d=source.profile[i].distanceM,b=source.geometry.coordinates[i] as [number,number];
  if(d<=end){coordinates.push(b);continue;}
  const a=source.geometry.coordinates[i-1],from=source.profile[i-1].distanceM,t=(end-from)/(d-from);
  if(t>0)coordinates.push([a[0]+(b[0]-a[0])*t,a[1]+(b[1]-a[1])*t]);
  break;
 }
 return {type:'LineString',coordinates};
}
export function terrainSections(terrain:Effort){
 const profile=terrain.profile,end=profile.at(-1)!.d,sections=[];
 for(let from=0;from<end;from+=100){const to=Math.min(from+100,end),gain=elevationAt(profile,to)-elevationAt(profile,from);sections.push({from,to,gain,grade:gain/(to-from)*100});}
 return sections;
}
export function climbData(state:ClimbState){
 const slug=['black-rock','wall','andorra-road'].includes(state.scenario)?state.scenario:'wises';
 const matching=fixtures.efforts.filter(e=>e.climb===slug&&e.gates===state.gates);
 const terrain=matching.find(e=>e.source_index===0)??matching[0],fresh=state.scenario==='successor',hasVault=!state.scenario.startsWith('no-vault')&&!fresh;
 const available=!fresh&&state.scenario!=='no-vault-empty';
 const history=state.viewer==='rider'&&!fresh?historyFor(terrain):[];
 const best=history.length?personalBest(terrain):undefined;
 return {state,terrain,geometry:climbGeometry(terrain),version:terrain.canon_version,fresh,hasVault,available,history,best,sections:terrainSections(terrain)};
}
export type ClimbData=ReturnType<typeof climbData>;
export function climbPower(record:BoardEffort):RowPower|undefined{
 const m=record.metrics as Effort['metrics'];
 if(m.power_kind==='measured'&&Number.isFinite(m.avg_power_w))return {kind:'measured',watts:m.avg_power_w!,wkg:record.share_wkg?m.w_per_kg??null:null};
 if(m.power_kind==='estimated'&&Number.isFinite(m.estimated_power_w))return {kind:'estimated',watts:m.estimated_power_w!,wkg:null,range:m.estimated_power_range_w?.length===2?[m.estimated_power_range_w[0],m.estimated_power_range_w[1]]:undefined};
}
export function leaderboardRecords(data:ClimbData,query:BoardQuery){
 if(!data.available||query.tab==='qualified')return [];
 const candidates=boardRecords().filter(e=>e.gates===data.state.gates&&e.climb===data.terrain.climb&&(query.period==='all-time'||e.date.startsWith(query.period)))
  .sort((a,b)=>a.metrics.time_s-b.metrics.time_s||a.occurred_at.localeCompare(b.occurred_at)||a.id.localeCompare(b.id));
 return candidates.filter((e,i)=>candidates.findIndex(r=>r.rider_id===e.rider_id)===i);
}
export function leaderboardRows(data:ClimbData,query:BoardQuery):LeaderboardEntry[]{
 const records=leaderboardRecords(data,query);
 return records.map((e,i)=>{
  const own=data.state.viewer==='rider'&&e.rider_id===data.terrain.rider_id,viewer=data.state.viewer==='anon'?'anon':own?'rider':'visitor';
  return {id:e.id,name:e.rider_name,rank:records.findIndex(r=>r.metrics.time_s===e.metrics.time_s)+1,time:clock(e.metrics.time_s),gap:i===0?'Fastest':signed(e.metrics.time_s-records[0].metrics.time_s),current:own,verified:false,profileHref:profileHref(e,viewer),effortHref:effortHref(e,viewer),power:climbPower(e)};
 });
}
export const climbChoices=()=>[...new Map(fixtures.efforts.map(e=>[e.climb,e.name]))].map(([id,label])=>({id,label}));
