import {climbResult,cropScenario,type Scenario} from '../scenario';
import {economicsFor} from './feedV2Model';
import type {DiscoveryV4} from './feedV4Model';
import {feedImports,feedScenarios,mixedFeed,parseFeed,type FeedEntry,type FeedScenario} from './feedModel';
import {feedV5Scenarios,feedV5ById,feedV5Ride,withV5Example,parseFeedV5,type FeedV5Scenario,type NetworkEffort} from './feedV5Model';

export type V6BoardRow={id:string;name:string;rank:number;duration:number;rideId?:string};
export type V6Board={climbId:string;asOf:string;rows:V6BoardRow[]};
export type FeedV6Scenario=FeedV5Scenario&{workshopV6?:{source:string;sourceKind:'provided'|'illustrative';features:NetworkEffort[];leaderboards:V6Board[]}};
const cache=new WeakMap<FeedScenario,FeedV6Scenario>();
export function withV6Example(source:FeedScenario):FeedV6Scenario{
 if(![...feedScenarios,...feedV5Scenarios].includes(source))return source;
 const saved=cache.get(source);if(saved)return saved;
 const base=withV5Example(source),owner=base.entries.find(e=>e.owned);
 const leaderboards:V6Board[]=(base.workshopV3?.personal?.standings??[]).map(s=>{
  const entry=base.entries.find(e=>e.id===s.entryId)!,climb=entry.ride.climbs.find(c=>c.id===s.climbId)!,duration=climbResult(entry.ride,climb).duration;
  const preceding=Array.from({length:Math.min(3,s.rank-1)},(_,i)=>({id:`${climb.id}-comparison-${i}`,name:['Morgan','Jamie','Alex'][i],rank:i+1,duration:Math.max(1,duration-(s.rank-i)*1.3)}));
  return {climbId:climb.id,asOf:'2016-08-28T22:00:00Z',rows:[...preceding,{id:`${climb.id}-owner`,name:source.viewer,rank:s.rank,duration,rideId:entry.ride.id}]};
 });
 const next:FeedV6Scenario={...base,workshopV6:{source:'V6: current leaderboard excerpts and rider identities are illustrative, separately supplied from historical ride achievements. Comparison rows without a recording stay unlinked. Black Rock uses its retained Philadelphia interval; Boulder and Nice have regional activity only. No geography or economic state is inferred.',sourceKind:'illustrative',features:base.workshopV5?.network?[base.workshopV5.network]:[],leaderboards}};
 if(!owner)next.workshopV6!.leaderboards=[];
 cache.set(source,next);return next;
}
export function v6RideHref(entry:FeedEntry,climb?:string,view:'overview'|'analysis'|'vault'='overview',feedId?:string,filter='everyone'){
 const p=new URLSearchParams({surface:'ride',variant:'candidate-v13',scenario:entry.ride.id,viewer:entry.owned?'owner':'visitor',view});
 if(climb)p.set('climb',climb);
 if(feedId){p.set('feedScenario',feedId);p.set('feedFilter',filter==='following'?'following':'everyone');}
 return `/?${p}`;
}
export function pageAfter(entries:FeedEntry[],cursor:string|null,limit=8){
 const index=cursor===null?-1:entries.findIndex(e=>e.id===cursor);
 if(cursor!==null&&index<0)throw Error('The feed cursor is no longer available.');
 const items=entries.slice(index+1,index+1+Math.max(1,limit));
 return {items,nextCursor:index+1+items.length<entries.length?items.at(-1)!.id:null};
}
export function v6Entries(s:FeedV6Scenario){const entries=[...s.entries,...(s.workshopV6?.features??[]).map(n=>n.entry)],legacy=s.workshopV5?.network?.entry;return legacy&&!entries.some(e=>e.ride.id===legacy.ride.id)?[...entries,legacy]:entries;}
export function parseFeedV6(value:unknown):FeedV6Scenario{
 const feed=parseFeedV5(value) as FeedV6Scenario,v=feed.workshopV6;if(v===undefined)return feed;
 const check=(ok:unknown,message:string)=>{if(!ok)throw Error(message);};
 check(v&&typeof v.source==='string'&&v.source.trim()&&['provided','illustrative'].includes(v.sourceKind),'V6 needs its source and source kind.');
 check(Array.isArray(v.features)&&v.features.length<=3&&Array.isArray(v.leaderboards)&&v.leaderboards.length<=500,'V6 supports up to three supplied network climbs and leaderboard excerpts.');
 const features=v.features.map(n=>{
  check(n&&typeof n.source==='string'&&n.source.trim()&&feed.workshopV3?.world?.regions.some(r=>r.id===n.regionId),'Network climbs need a source and supplied region.');
  const entry=parseFeed({...feed,entries:[n.entry]}).entries[0];
  check(entry?.ride.climbs.some(c=>c.id===n.climbId)&&Number.isInteger(n.leaderboard?.rank)&&n.leaderboard.rank>=1&&n.leaderboard.rank<=10,'Network climb needs a matching climb and placement.');
  return {...n,entry};
 });
 const entries=[...feed.entries,...features.map(f=>f.entry)],rides=new Map(entries.map(e=>[e.ride.id,e]));
 check(rides.size===entries.length,'Feed and network recordings need unique ride identities.');
 const seen=new Set<string>();
 for(const board of v.leaderboards){
  check(board&&typeof board.climbId==='string'&&!seen.has(board.climbId)&&entries.some(e=>e.ride.climbs.some(c=>c.id===board.climbId)),'Leaderboard needs a unique supplied climb.');seen.add(board.climbId);
  check(typeof board.asOf==='string'&&Number.isFinite(Date.parse(board.asOf))&&Array.isArray(board.rows)&&board.rows.length<=100,'Leaderboard needs its date and rows.');
  const rowIds=new Set<string>();
  for(const row of board.rows){
   check(row&&typeof row.id==='string'&&!rowIds.has(row.id)&&typeof row.name==='string'&&row.name.trim()&&Number.isInteger(row.rank)&&row.rank>0&&Number.isFinite(row.duration)&&row.duration>0,'Invalid leaderboard row.');rowIds.add(row.id);
   if(row.rideId!==undefined){const entry=rides.get(row.rideId),climb=entry?.ride.climbs.find(c=>c.id===board.climbId);check(entry&&climb&&Math.abs(climbResult(entry.ride,climb).duration-row.duration)<.01&&entry.ride.ride.rider?.displayName===row.name,'Leaderboard recording must match the climb, rider and duration.');}
  }
 }
 return {...feed,workshopV6:{...v,features}};
}
function longFeed():FeedV6Scenario{
 const s=structuredClone(withV6Example(mixedFeed));s.id='long-feed';s.label='Long feed · 32 rides';
 s.entries=Array.from({length:32},(_,i)=>{const e=mixedFeed.entries[i%3];return {...e,id:`scroll-${i}`,ride:{...e.ride,id:`feed-v6-scroll-${i}`,source:{...e.ride.source,description:e.ride.source.description+' Repeated retained recording for the 32-card scrolling study.'}},owned:i===0,comments:e.comments.map(c=>({...c,id:`${i}-${c.id}`}))};});
 s.workshopV2=undefined;s.workshopV3=undefined;s.workshopV5=undefined;s.workshopV6=undefined;
 s.source+=' 32 repeated presentations of retained recordings for pagination and return-position review, not 32 independent activities.';return s;
}
function threeFeatures():FeedV6Scenario{
 const s=structuredClone(withV6Example(mixedFeed));s.id='network-3';s.label='Three featured climbs · layout';
 const original=mixedFeed.entries[0];s.workshopV6!.features=original.ride.climbs.map((climb,i)=>{
  const ride=cropScenario(original.ride,climb.start,climb.end);ride.id=`feed-v6-network-${i}`;ride.label=climb.name;ride.ride.rider={displayName:['Alex','Jamie','Morgan'][i],source:'illustrative'};ride.ride.title=climb.name;ride.source={...ride.source,history:'none',description:ride.source.description+' Explicit illustrative network rider and placement on retained Philadelphia terrain.'};ride.climbs=ride.climbs.map(c=>({...c,history:[]}));
  return {source:ride.source.description,regionId:'philadelphia',entry:{id:`network-v6-${i}`,ride,owned:false,followed:false,description:'',companions:[],kudos:0,comments:[]},climbId:climb.id,leaderboard:{rank:i+1}};
 });return s;
}
export const feedV6Scenarios=[...feedV5Scenarios.map(withV6Example),longFeed(),threeFeatures()];
export function feedV6ById(id:string|null):FeedV6Scenario{return feedV6Scenarios.find(s=>s.id===id)??withV6Example(feedV5ById(id));}
export function allV6Scenarios(){return [...feedScenarios.map(withV6Example),...feedV6Scenarios,...feedImports.values()] as FeedV6Scenario[];}
export function feedV6Ride(id:string|null):Scenario|undefined{return allV6Scenarios().flatMap(v6Entries).find(e=>e.ride.id===id)?.ride??feedV5Ride(id);}
export function v6RideContext(rideId:string,feedId?:string|null,filter='everyone'){
 const s=allV6Scenarios().find(s=>(!feedId||s.id===feedId)&&v6Entries(s).some(e=>e.ride.id===rideId));
 if(!s?.workshopV6)return undefined;
 const entry=v6Entries(s).find(e=>e.ride.id===rideId)!;
 return {source:s.workshopV6.sourceKind,economics:economicsFor(s,entry),climbs:entry.ride.climbs.map(c=>({climbId:c.id,resultRank:s.workshopV5?.results.find(f=>f.entryId===entry.id&&f.climbId===c.id)?.leaderboard?.rank??s.workshopV6?.features.find(n=>n.entry.ride.id===rideId&&n.climbId===c.id)?.leaderboard.rank,leaderboardAsOf:s.workshopV6?.leaderboards.find(b=>b.climbId===c.id)?.asOf,leaderboard:(s.workshopV6?.leaderboards.find(b=>b.climbId===c.id)?.rows??[]).map(row=>({id:row.id,name:row.name,rank:row.rank,duration:row.duration,isCurrentRider:row.name===entry.ride.ride.rider?.displayName,...(row.rideId?{href:v6RideHref(v6Entries(s).find(e=>e.ride.id===row.rideId)!,c.id,'overview',s.id,filter)}:{})}))}))};
}

export function v6NetworkTerrain(n:NetworkEffort):DiscoveryV4|null {
 const climb=n.entry.ride.climbs.find(c=>c.id===n.climbId);if(!climb)return null;
 const points=n.entry.ride.ride.samples.filter(p=>p.t>=climb.start&&p.t<=climb.end),result=climbResult(n.entry.ride,climb),origin=points[0];
 if(points.length<2||result.distance<=0||result.gain===null||points.some((p,i)=>p.elevation===null||(i>0&&(p.d<points[i-1].d||p.t-points[i-1].t>30))))return null;
 // Stationary samples retain their timing in the recording; a terrain profile needs one point per distance.
 const terrain=points.filter((p,i)=>i===0||p.d>points[i-1].d);
 return {name:climb.name,locality:n.entry.ride.ride.location,source:n.source,length:result.distance,gain:result.gain,profile:terrain.map(p=>({d:p.d-origin.d,elevation:p.elevation!})),geometry:{type:'LineString',coordinates:terrain.map(p=>[p.lon,p.lat])}};
}
