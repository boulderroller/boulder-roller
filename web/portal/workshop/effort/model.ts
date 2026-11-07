import data from './fixtures.json';
import type {EffortPoint,ComparisonPoint,GradeBand,RowPower,LeaderboardEntry} from '../v15';
import {formatNumber} from '../../src/lib/formatters';

export type Viewer='rider'|'visitor'|'anon';
export type Gates='v2'|'v1';
export type Compare='best'|'fastest'|'none';
export type Metrics={engine_version:number;time_s:number;moving_s:number;distance_m:number;net_gain_m:number;avg_speed_mps:number;vam_m_per_hour:number;power_kind:'measured'|'estimated';avg_power_w?:number;estimated_power_w?:number;estimated_power_range_w?:number[];power_estimate_basis?:string;np_w?:number;intensity_factor?:number;load?:number;variability_index?:number;max_power_w?:number;best_30s_w?:number;best_60s_w?:number;w_per_kg?:number;avg_cadence_rpm?:number;avg_hr_bpm?:number;max_hr_bpm?:number;avg_torque_nm?:number;max_torque_nm?:number;threshold?:{value:number;estimate:boolean;basis:string};power_zone_tops_w?:number[];power_zone_s?:number[];stops:{start_s:number;end_s:number;duration_s:number;start_m?:number;end_m?:number;cost?:{estimate:boolean;basis:string;seconds:number;range_s:number[]}}[]};
export type Effort={id:string;gates:Gates;climb:string;name:string;date:string;occurred_at:string;source_index:number;rider_id:string;rider_name:string;share_wkg:boolean;recording:boolean;canon_version:number;start_s:number;end_s:number;metrics:Metrics;profile:{d:number;elevation:number}[];bands:GradeBand[];samples:EffortPoint[];sections:(GradeBand&{start_s:number;end_s:number;metrics:Metrics})[];comparisons:Record<string,{points:ComparisonPoint[];section_gaps_s:number[]}>};
export type BoardEffort=Pick<Effort,'id'|'gates'|'climb'|'name'|'date'|'occurred_at'|'rider_id'|'rider_name'|'share_wkg'|'recording'>&{metrics:Pick<Metrics,'time_s'|'power_kind'|'avg_power_w'|'estimated_power_w'|'w_per_kg'>};
export const fixtures=data as unknown as {provenance:typeof data.provenance;efforts:Effort[];board_efforts:BoardEffort[];cross_check:typeof data.cross_check};
export const clock=(seconds:number)=>{const n=Math.round(seconds);return `${Math.floor(n/60)}:${String(n%60).padStart(2,'0')}`;};
export const signed=(seconds:number)=>`${seconds<0?'−':seconds>0?'+':''}${formatNumber(Math.abs(seconds),1,1)} s`;
export const dateLabel=(date:string)=>new Date(`${date}T12:00:00Z`).toLocaleDateString('en-US',{month:'short',day:'numeric',year:'numeric',timeZone:'UTC'});
export function queryState(search:string){
 const p=new URLSearchParams(search),viewer=p.get('viewer'),gate=p.get('gates'),compare=p.get('compare');
 return {viewer:(viewer==='anon'||viewer==='visitor'?viewer:'rider') as Viewer,gates:(gate==='v1'?'v1':'v2') as Gates,effort:p.get('effort')??'wises',compare:(compare==='none'||compare==='fastest'?compare:'best') as Compare};
}
export function findEffort(id:string,gates:Gates):Effort{
 const available=fixtures.efforts.filter(e=>e.gates===gates);
 return available.find(e=>e.id===id)??(id==='estimated'?available.find(e=>e.metrics.power_kind==='estimated'):id==='interior'?available.find(e=>e.climb==='andorra-road'&&e.metrics.stops.length):available.find(e=>e.climb===id&&e.source_index===0))??available.find(e=>e.climb==='wises'&&e.source_index===0)!;
}
export function historyFor(effort:Effort){return fixtures.efforts.filter(e=>e.gates===effort.gates&&e.climb===effort.climb&&e.rider_id===effort.rider_id).sort((a,b)=>b.date.localeCompare(a.date)||b.start_s-a.start_s);}
export function personalBest(effort:Effort){return historyFor(effort).filter(e=>e.recording).sort((a,b)=>a.metrics.time_s-b.metrics.time_s||a.occurred_at.localeCompare(b.occurred_at))[0];}
export function previousBest(effort:Effort){return historyFor(effort).filter(e=>e.recording&&e.occurred_at<effort.occurred_at).sort((a,b)=>a.metrics.time_s-b.metrics.time_s)[0];}
export function isNewBest(effort:Effort){const previous=previousBest(effort);return personalBest(effort)?.id===effort.id&&!!previous&&effort.metrics.time_s<previous.metrics.time_s;}
export function comparisonFor(effort:Effort,mode:Compare):Effort|undefined{
 if(mode==='none'||!effort.recording)return;
 if(mode==='best')return personalBest(effort)?.id===effort.id?previousBest(effort):historyFor(effort).filter(e=>e.id!==effort.id&&e.recording).sort((a,b)=>a.metrics.time_s-b.metrics.time_s)[0];
 const candidate=rankedRiders(effort)[0];
 return candidate?.id===effort.id?undefined:fixtures.efforts.find(e=>e.gates===effort.gates&&e.id===candidate?.id);
}
const ownerOnly=['threshold','intensity_factor','load','power_zone_s','power_zone_tops_w','max_hr_bpm'] as const;
export function visibleMetrics(metrics:Metrics,viewer:Viewer,shareWkg:boolean):Metrics{
 const value={...metrics};
 if(viewer!=='rider')for(const key of ownerOnly)delete value[key];
 if(viewer!=='rider'&&!shareWkg)delete value.w_per_kg;
 return value;
}
export function visibleEffort(effort:Effort,viewer:Viewer):Effort{
 // A public raw HR series would reconstruct the owner-only maximum.
 const samples=viewer==='rider'?effort.samples:effort.samples.map(({hr_bpm:_,...sample})=>sample);
 return {...effort,samples,metrics:visibleMetrics(effort.metrics,viewer,effort.share_wkg),sections:effort.sections.map(s=>({...s,metrics:visibleMetrics(s.metrics,viewer,effort.share_wkg)}))};
}
export function rowPower(metrics:BoardEffort['metrics']):RowPower|undefined{
 const watts=metrics.power_kind==='measured'?metrics.avg_power_w:metrics.estimated_power_w;
 return watts===undefined?undefined:{kind:metrics.power_kind,watts,wkg:metrics.w_per_kg??null};
}
export function effortHref(effort:BoardEffort,viewer:Viewer='rider',extra:Record<string,string>={}){
 return `/?${new URLSearchParams({'effort-preview':'1',surface:'effort',variant:'effort-v1',effort:effort.id,gates:effort.gates,viewer,...(!effort.recording?{view:'aggregate'}:{}),...extra})}`;
}
export function profileHref(effort:BoardEffort,viewer:Viewer='visitor'){return effortHref(effort,viewer,{view:'profile'});}
export function boardRecords(){return [...fixtures.efforts,...fixtures.board_efforts];}
export function rankedRiders(effort:BoardEffort){
 const records=boardRecords().filter(e=>e.gates===effort.gates&&e.climb===effort.climb).sort((a,b)=>a.metrics.time_s-b.metrics.time_s||a.occurred_at.localeCompare(b.occurred_at)||a.id.localeCompare(b.id));
 return records.filter((e,i)=>records.findIndex(r=>r.rider_id===e.rider_id)===i);
}
export function standingFor(effort:BoardEffort){
 const records=rankedRiders(effort),best=records.find(e=>e.rider_id===effort.rider_id)!;
 return {best,rank:records.findIndex(e=>e.metrics.time_s===best.metrics.time_s)+1,total:records.length,fastest:records[0]};
}
/** Stable fixture rider identities; the numerical rows are generated, recorded efforts.
 * This is explicitly labelled on screen. It cannot establish a rider's live place.
 */
export function boardFor(effort:Effort,viewer:Viewer):LeaderboardEntry[]{
 const records=rankedRiders(effort);
 return records.slice(0,10).map((e,i)=>({id:e.id,name:e.rider_name,rank:records.findIndex(r=>r.metrics.time_s===e.metrics.time_s)+1,time:clock(e.metrics.time_s),gap:i===0?'Fastest':signed(e.metrics.time_s-records[0].metrics.time_s),current:e.id===effort.id&&viewer==='rider',verified:false,profileHref:profileHref(e,e.rider_id===effort.rider_id||viewer==='anon'?viewer:'visitor'),effortHref:effortHref(e,e.rider_id===effort.rider_id||viewer==='anon'?viewer:'visitor'),power:rowPower({...e.metrics,w_per_kg:e.share_wkg||(e.rider_id===effort.rider_id&&viewer==='rider')?e.metrics.w_per_kg:undefined})}));
}
