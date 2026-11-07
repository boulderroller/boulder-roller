import {climbResult,type Scenario} from '../scenario';
import type {V13Context} from '../v13Context';
import {economicsFor} from './feedV2Model';
import {feedScenarios,feedImports,type FeedScenario,type FeedEntry} from './feedModel';
import {withV6Example,feedV6Scenarios,feedV6ById,parseFeedV6,v6Entries,v6RideHref,v6NetworkTerrain,type FeedV6Scenario} from './feedV6Model';

export type V7Feature={climbId:string;rowId:string;regionId:string;terrainRideId:string};
export type V7Rider={id:string;name:string;entryIds:string[];boardRows:string[];commentKeys:string[];companionKeys:string[];viewer?:boolean};
export type FeedV7Scenario=FeedV6Scenario&{workshopV7?:{source:string;features:V7Feature[];riders:V7Rider[]}};
const cache=new WeakMap<FeedScenario,FeedV7Scenario>();
const key=(climb:string,row:string)=>`${climb}:${row}`;
export function v7NetworkItems(s:FeedV7Scenario){
 return (s.workshopV7?.features??[]).flatMap(feature=>{
  const board=s.workshopV6?.leaderboards.find(b=>b.climbId===feature.climbId),row=board?.rows.find(r=>r.id===feature.rowId);
  const terrainEntry=v6Entries(s).find(e=>e.ride.id===feature.terrainRideId),climb=terrainEntry?.ride.climbs.find(c=>c.id===feature.climbId);
  const region=s.workshopV3?.world?.regions.find(r=>r.id===feature.regionId);
  if(!board||!row||row.rank>10||!terrainEntry||!climb||!region)return [];
  const recording=v6Entries(s).find(e=>e.ride.id===row.rideId);
  const terrain=v6NetworkTerrain({entry:terrainEntry,climbId:climb.id,regionId:region.id,leaderboard:{rank:row.rank},source:s.workshopV7!.source});
  return [{feature,board,row,terrainEntry,climb,region,recording,terrain}];
 });
}
export function withV7Example(source:FeedScenario):FeedV7Scenario{
 if((source as FeedV7Scenario).workshopV7)return source;
 if(![...feedScenarios,...feedV6Scenarios].includes(source))return source;
 const saved=cache.get(source);if(saved)return saved;
 const s=structuredClone(withV6Example(source)) as FeedV7Scenario;
 if(source.id==='long-feed'){
  const base=structuredClone(withV6Example(feedScenarios[0]));
  s.workshopV3=base.workshopV3;s.workshopV6=base.workshopV6;
  for(const standing of s.workshopV3?.personal?.standings??[])standing.entryId=s.entries[0].id;
  for(const board of s.workshopV6?.leaderboards??[])for(const row of board.rows)if(row.rideId===base.entries[0].ride.id)row.rideId=s.entries[0].ride.id;
 }
 const features:V7Feature[]=[];
 for(const n of s.workshopV6?.features??[]){
  let board=s.workshopV6!.leaderboards.find(b=>b.climbId===n.climbId);
  if(!board){
   const c=n.entry.ride.climbs.find(c=>c.id===n.climbId)!;
   board={climbId:c.id,asOf:n.entry.ride.ride.startedAt,rows:[{id:`v7-${n.entry.id}`,name:n.entry.ride.ride.rider!.displayName,rank:n.leaderboard.rank,duration:climbResult(n.entry.ride,c).duration,rideId:n.entry.ride.id}]};
   s.workshopV6!.leaderboards.push(board);
  }
  // Feature an actual row. Terrain may be supplied by another traversal; it never lends its time to the featured rider.
  const row=board.rows[0];if(!row)continue;
  const terrain=board.rows.flatMap(r=>v6Entries(s).filter(e=>e.ride.id===r.rideId))[0]??n.entry;
  features.push({climbId:n.climbId,rowId:row.id,regionId:n.regionId,terrainRideId:terrain.ride.id});
 }
 // The crown study uses its own first-place result, rather than an unrelated legacy feature.
 if(source.id==='leaderboard-10'){
  const board=s.workshopV6?.leaderboards.find(b=>b.rows.some(r=>r.rank===1&&r.rideId));
  const row=board?.rows.find(r=>r.rank===1&&r.rideId);
  if(board&&row)features.splice(0,features.length,{climbId:board.climbId,rowId:row.id,regionId:'philadelphia',terrainRideId:row.rideId!});
 }
 const riders:V7Rider[]=[];
 // These name bindings are authored for the bundled examples only. Imported people require explicit references.
 const rider=(name:string)=>{let r=riders.find(r=>r.name===name);if(!r){r={id:`rider-${riders.length+1}`,name,entryIds:[],boardRows:[],commentKeys:[],companionKeys:[]};riders.push(r);}return r;};
 rider(s.viewer).viewer=true;
 for(const e of v6Entries(s)){
  if(e.ride.ride.rider)rider(e.ride.ride.rider.displayName).entryIds.push(e.id);
  e.comments.forEach(c=>rider(c.name).commentKeys.push(`${e.id}:${c.id}`));
  e.companions.forEach((name,i)=>rider(name).companionKeys.push(`${e.id}:${i}`));
 }
 for(const b of s.workshopV6?.leaderboards??[])for(const r of b.rows)rider(r.name).boardRows.push(key(b.climbId,r.id));
 s.workshopV7={source:'V7 uses one supplied leaderboard row for each featured rider, time and placement. Terrain can come from a different retained traversal; effort links appear only for a supplied matching recording. Rider identity bindings are explicit workshop examples. No profile totals or missing rides are inferred.',features,riders};
 cache.set(source,s);return s;
}
export const feedV7Scenarios=feedV6Scenarios.map(withV7Example);
export function feedV7ById(id:string|null):FeedV7Scenario{
 const extra=feedV6Scenarios.find(s=>s.id===id),base=feedScenarios.find(s=>s.id===id);
 return extra?withV7Example(extra):base?withV7Example(base):feedImports.get(id??'')??withV7Example(feedScenarios[0]);
}
export function allV7Scenarios(){return [...feedScenarios.map(withV7Example),...feedV7Scenarios,...feedImports.values()] as FeedV7Scenario[];}
export function v7RideHref(entry:FeedEntry,climb?:string,view:'overview'|'analysis'|'vault'='overview',feedId?:string,filter='everyone'){
 const p=new URLSearchParams(v6RideHref(entry,climb,view,feedId,filter).slice(2));p.set('feedVariant','feed-v7');return `/?${p}`;
}
export function v7RiderHref(s:FeedV7Scenario,riderId:string,filter='everyone'){
 return `/?${new URLSearchParams({surface:'feed',variant:'feed-v7',scenario:s.id,filter:filter==='following'?'following':'everyone',rider:riderId})}`;
}
export function riderForEntry(s:FeedV7Scenario,id:string){return s.workshopV7?.riders.find(r=>r.entryIds.includes(id));}
export function riderForBoard(s:FeedV7Scenario,climbId:string,rowId:string){return s.workshopV7?.riders.find(r=>r.boardRows.includes(key(climbId,rowId)));}
export function parseFeedV7(value:unknown):FeedV7Scenario{
 const s=parseFeedV6(value) as FeedV7Scenario,v=s.workshopV7;if(v===undefined)return s;
 const check=(ok:unknown,message:string)=>{if(!ok)throw Error(message);};
 check(v&&typeof v.source==='string'&&v.source.trim()&&Array.isArray(v.features)&&v.features.length<=3&&Array.isArray(v.riders)&&v.riders.length<=1000,'V7 requires its source, features and rider identities.');
 const entries=v6Entries(s),boards=s.workshopV6?.leaderboards??[];
 check(new Set(entries.map(e=>e.id)).size===entries.length,'V7 rider references require unique entry IDs.');
 const featureKeys=new Set<string>();
 for(const f of v.features){check(f&&typeof f.climbId==='string'&&!featureKeys.has(f.climbId)&&typeof f.rowId==='string'&&typeof f.terrainRideId==='string'&&typeof f.regionId==='string','Invalid V7 feature reference.');featureKeys.add(f.climbId);}
 check(v7NetworkItems(s).length===v.features.length,'Featured climbs must resolve to their leaderboard row, region and terrain recording.');
 const ids=new Set<string>(),bindings=new Set<string>();
 for(const r of v.riders){
  check(r&&typeof r.id==='string'&&r.id.trim()&&!ids.has(r.id)&&typeof r.name==='string'&&r.name.trim()&&['entryIds','boardRows','commentKeys','companionKeys'].every(k=>Array.isArray(r[k as keyof V7Rider])),'Invalid rider identity.');ids.add(r.id);
  for(const [kind,values] of Object.entries({entry:r.entryIds,board:r.boardRows,comment:r.commentKeys,companion:r.companionKeys}))for(const ref of values){check(typeof ref==='string'&&!bindings.has(`${kind}:${ref}`),'Rider references must be unique.');bindings.add(`${kind}:${ref}`);}
  check(r.entryIds.every(id=>entries.some(e=>e.id===id&&e.ride.ride.rider?.displayName===r.name)),'Rider recording must match its supplied identity.');
  check(r.boardRows.every(k=>boards.some(b=>b.rows.some(row=>key(b.climbId,row.id)===k&&row.name===r.name))),'Rider leaderboard reference does not match.');
  check(r.commentKeys.every(k=>entries.some(e=>e.comments.some(c=>`${e.id}:${c.id}`===k&&c.name===r.name))),'Rider comment reference does not match.');
  check(r.companionKeys.every(k=>entries.some(e=>e.companions.some((n,i)=>`${e.id}:${i}`===k&&n===r.name))),'Rider companion reference does not match.');
  check(!r.viewer||r.name===s.viewer,'Viewer identity does not match.');
 }
 check(v.riders.filter(r=>r.viewer).length<=1,'Only one viewer identity can be supplied.');
 return s;
}
export function v7RideContext(rideId:string,feedId?:string|null,filter='everyone'):V13Context|undefined{
 const s=allV7Scenarios().find(s=>(!feedId||s.id===feedId)&&v6Entries(s).some(e=>e.ride.id===rideId));
 if(!s?.workshopV6)return undefined;const entry=v6Entries(s).find(e=>e.ride.id===rideId)!;
 return {source:s.workshopV6.sourceKind,economics:economicsFor(s,entry),climbs:entry.ride.climbs.map(c=>({climbId:c.id,resultRank:s.workshopV5?.results.find(f=>f.entryId===entry.id&&f.climbId===c.id)?.leaderboard?.rank,leaderboardAsOf:s.workshopV6?.leaderboards.find(b=>b.climbId===c.id)?.asOf,leaderboard:(s.workshopV6?.leaderboards.find(b=>b.climbId===c.id)?.rows??[]).map(row=>({id:row.id,name:row.name,rank:row.rank,duration:row.duration,isCurrentRider:row.name===entry.ride.ride.rider?.displayName,...(row.rideId?{href:v7RideHref(v6Entries(s).find(e=>e.ride.id===row.rideId)!,c.id,'overview',s.id,filter)}:{})}))}))};
}

export function rekeyV7Feed(input:FeedV7Scenario,sourceKey:string):FeedV7Scenario{
 const s=structuredClone(input),rideIds=new Map(s.entries.map((e,i)=>[e.ride.id,`feed-local-${sourceKey}-${i}`]));
 s.workshopV6?.features.forEach((n,i)=>rideIds.set(n.entry.ride.id,`feed-local-${sourceKey}-feature-${i}`));
 const legacy=s.workshopV5?.network;if(legacy&&!rideIds.has(legacy.entry.ride.id))rideIds.set(legacy.entry.ride.id,`feed-local-${sourceKey}-network`);
 const entry=(e:FeedEntry)=>({...e,ride:{...e.ride,id:rideIds.get(e.ride.id)!}});
 s.id=`feed-import-${sourceKey}`;s.entries=s.entries.map(entry);
 if(s.workshopV2)s.workshopV2.rideEconomics=s.workshopV2.rideEconomics.map(e=>({...e,rideId:s.entries.find(x=>x.id===e.entryId)!.ride.id}));
 if(legacy)s.workshopV5={...s.workshopV5!,network:{...legacy,entry:entry(legacy.entry)}};
 if(s.workshopV6)s.workshopV6={...s.workshopV6,features:s.workshopV6.features.map(n=>({...n,entry:entry(n.entry)})),leaderboards:s.workshopV6.leaderboards.map(b=>({...b,rows:b.rows.map(r=>({...r,...(r.rideId?{rideId:rideIds.get(r.rideId)!}:{})}))}))};
 if(s.workshopV7)s.workshopV7={...s.workshopV7,features:s.workshopV7.features.map(f=>({...f,terrainRideId:rideIds.get(f.terrainRideId)!}))};
 return parseFeedV7(s);
}
