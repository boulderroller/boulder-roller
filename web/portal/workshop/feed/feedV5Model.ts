import {climbResult,cropScenario,type Climb} from '../scenario';
import {feedScenarios,feedImports,mixedFeed,parseFeed,type FeedEntry,type FeedScenario} from './feedModel';
import {withV4Example,parseFeedV4,feedV4Scenarios,feedV4ById,feedV4Ride,type FeedV4Scenario,type DiscoveryV4} from './feedV4Model';

export type LeaderboardPlace={rank:number;tied?:boolean};
export type ResultFact={entryId:string;climbId:string;leaderboard?:LeaderboardPlace;personalHistoryComplete?:boolean};
export type NetworkEffort={source:string;regionId:string;entry:FeedEntry;climbId:string;leaderboard:LeaderboardPlace};
export type FeedV5Scenario=FeedV4Scenario&{workshopV5?:{source:string;results:ResultFact[];network?:NetworkEffort}};
const examples=new WeakMap<FeedScenario,FeedV5Scenario>();
const hasText=(v:unknown):v is string=>typeof v==='string'&&!!v.trim();
function check(v:unknown,message:string):asserts v {if(!v)throw Error(message);}
function validPlace(p:LeaderboardPlace){return p&&Number.isInteger(p.rank)&&p.rank>=1&&p.rank<=10&&(p.tied===undefined||typeof p.tied==='boolean');}

const networkSource=(()=>{
 const original=mixedFeed.entries[0],climb=original.ride.climbs[1];
 const ride=cropScenario(original.ride,climb.start,climb.end);
 ride.id='feed-v5-network-black-rock';ride.label='Black Rock Road';
 ride.source={...ride.source,history:'none',description:ride.source.description+' Network feature: retained Black Rock interval; rider identity and first-place result are illustrative.'};
 ride.ride={...ride.ride,title:'Black Rock Road',rider:{displayName:'Alex',source:'illustrative'}};
 ride.climbs=ride.climbs.map(c=>({...c,history:[]}));
 return {source:'Retained Black Rock Road interval, with explicitly illustrative rider identity and first-place result. Independent of the visible feed.',regionId:'philadelphia',entry:{id:'network-black-rock',ride,owned:false,followed:false,description:'',companions:[],kudos:0,comments:[]},climbId:climb.id,leaderboard:{rank:1}} satisfies NetworkEffort;
})();

export function withV5Example(source:FeedScenario):FeedV5Scenario{
 if(![...feedScenarios,...feedV4Scenarios].includes(source))return source;
 const cached=examples.get(source);if(cached)return cached;
 const base=withV4Example(source),owner=base.entries.find(e=>e.owned);
 const results:ResultFact[]=owner&&source.id!=='achievements-10'?[{entryId:owner.id,climbId:owner.ride.climbs[0].id,leaderboard:{rank:7}}]:[];
 const next:FeedV5Scenario={...base,workshopV5:{source:'V5 design inputs: historical ride placements are supplied separately from current standings. Personal second/third requires a complete comparable history; times are compared at the displayed whole-second precision. Network rider and placement are illustrative, on unchanged retained geography.',results,network:networkSource}};
 examples.set(source,next);return next;
}
export function parseFeedV5(value:unknown):FeedV5Scenario{
 const feed=parseFeedV4(value) as FeedV5Scenario,c=feed.workshopV5;if(c===undefined)return feed;
 check(c&&hasText(c.source)&&Array.isArray(c.results)&&c.results.length<=5000,'V5 needs an explicit source and result facts.');
 const seen=new Set<string>();
 c.results.forEach(f=>{
  const entry=feed.entries.find(e=>e.id===f?.entryId),key=`${f?.entryId}:${f?.climbId}`;
  check(entry&&entry.ride.climbs.some(c=>c.id===f.climbId)&&!seen.has(key),'Result facts need a unique matching ride and climb.');seen.add(key);
  check(f.leaderboard===undefined||validPlace(f.leaderboard),'Invalid leaderboard placement; only ranks 1–10 are supported.');
  check(f.personalHistoryComplete===undefined||typeof f.personalHistoryComplete==='boolean','Personal history completeness must be explicit.');
 });
 const n=c.network;let networkEntry:FeedEntry|undefined;
 if(n!==undefined){
  check(n&&hasText(n.source)&&feed.workshopV3?.world?.regions.some(r=>r.id===n.regionId),'Network feature needs a supplied world region and source.');
  networkEntry=parseFeed({...feed,entries:[n.entry]}).entries[0];
  check(networkEntry,'Network feature needs one ride.');
  check(networkEntry.ride.climbs.some(c=>c.id===n.climbId),'Network feature needs its matching climb.');
  check(validPlace(n.leaderboard),'Invalid network leaderboard placement.');
  check(!feed.entries.some(e=>e.ride.id===networkEntry!.ride.id),'Network feature needs its own ride identity.');
 }
 return {...feed,workshopV5:{...c,results:c.results.map(f=>({...f})),network:n?{...n,entry:networkEntry!}:undefined}};
}
export function personalResult(entry:FeedEntry,climb:Climb,complete:boolean){
 const result=climbResult(entry.ride,climb),time=Math.round(result.duration),prior=climb.history.map(h=>Math.round(h.duration));
 const improvement=prior.length?Math.min(...prior)-time:null,newBest=improvement!==null&&improvement>0;
 const rank=prior.length&&complete?1+prior.filter(t=>t<time).length:null;
 return {newBest,improvement,personalRank:newBest?1:rank!==null&&rank<=3?rank:null,personalTied:rank!==null&&rank<=3&&prior.includes(time)};
}
export function v5Collection(entry:FeedEntry,scenario:FeedV5Scenario){
 const results=entry.ride.climbs.map(climb=>{
  const fact=scenario.workshopV5?.results.find(f=>f.entryId===entry.id&&f.climbId===climb.id);
  const p=personalResult(entry,climb,fact?.personalHistoryComplete===true);
  return {climb,result:climbResult(entry.ride,climb),...p,leaderboard:fact?.leaderboard,achievement:!!fact?.leaderboard||p.personalRank!==null};
 });
 const special=results.filter(r=>r.achievement).sort((a,b)=>(a.leaderboard?.rank??10+(a.personalRank??4))-(b.leaderboard?.rank??10+(b.personalRank??4)));
 const ordered=[...special,...results.filter(r=>!r.achievement)];
 return {results:ordered,visible:special.length?special.slice(0,2):ordered.slice(0,1),achievementCount:special.length};
}
export type ResultV5=ReturnType<typeof v5Collection>['results'][number];
export const ordinal=(n:number)=>`${n}${n===1?'st':n===2?'nd':n===3?'rd':'th'}`;
export function placeLabel(p:LeaderboardPlace){return p.tied?`T-${p.rank}`:ordinal(p.rank);}
export function personalLabel(r:Pick<ResultV5,'newBest'|'personalRank'|'personalTied'>){return r.newBest?'New best':r.personalRank===1?'Equal best':r.personalRank?`${r.personalTied?'Joint ':''}${ordinal(r.personalRank)} best time`:null;}
export function networkDiscovery(n:NetworkEffort):DiscoveryV4|null{
 const c=n.entry.ride.climbs.find(c=>c.id===n.climbId)!,points=n.entry.ride.ride.samples.filter(p=>p.t>=c.start&&p.t<=c.end),result=climbResult(n.entry.ride,c),origin=points[0];
 if(points.length<2||result.gain===null||points.some((p,i)=>p.elevation===null||(i>0&&(p.d<=points[i-1].d||p.t-points[i-1].t>30))))return null;
 return {name:c.name,locality:n.entry.ride.ride.location,source:n.source,length:result.distance,gain:result.gain,profile:points.filter(p=>p.elevation!==null).filter((p,i,all)=>i===0||p.d>all[i-1].d).map(p=>({d:p.d-origin.d,elevation:p.elevation!})),geometry:{type:'LineString',coordinates:points.filter(p=>p.elevation!==null).filter((p,i,all)=>i===0||p.d>all[i-1].d).map(p=>[p.lon,p.lat])}};
}
function podiumStudy():FeedV5Scenario{
 const s=structuredClone(withV5Example(mixedFeed)),e=s.entries[0];s.id='personal-podium';s.label='Personal bests · 1st, 2nd, 3rd';
 e.ride.id='feed-v5-personal-podium';e.ride.source.history='illustrative';
 e.ride.climbs.forEach((c,i)=>{const t=climbResult(e.ride,c).duration;c.history=[10,-4,-8].slice(0,i+1).map((delta,j)=>({date:`2016-08-${20-j}`,duration:t+delta}));});
 s.workshopV5!.results=e.ride.climbs.map(c=>({entryId:e.id,climbId:c.id,personalHistoryComplete:true}));
 s.workshopV3!.personal!.standings=[];
 s.workshopV2!.rideEconomics=s.workshopV2!.rideEconomics.map(x=>({...x,rideId:e.ride.id}));
 s.source+=' Complete illustrative personal history for the proposed personal podium; recorded measurements are unchanged.';return parseFeedV5(s);
}
function leaderboardStudy():FeedV5Scenario{
 const s=structuredClone(withV5Example(feedV4Scenarios[1])),e=s.entries[0];s.id='leaderboard-10';s.label='Leaderboard places · 1st–10th';e.ride.id='feed-v5-leaderboard-10';
 e.ride.climbs=e.ride.climbs.map(c=>({...c,history:[]}));e.ride.source.history='none';
 s.workshopV5!.results=e.ride.climbs.map((c,i)=>({entryId:e.id,climbId:c.id,leaderboard:{rank:i+1}}));
 s.workshopV3!.personal!.standings=e.ride.climbs.slice(0,3).map((c,i)=>({entryId:e.id,climbId:c.id,rank:i+1}));
 s.source+=' Explicit 1st–10th placement study on ten illustrative windows; no additional detected/canonical climbs or economics are asserted.';return parseFeedV5(s);
}
export const feedV5Scenarios=[...feedV4Scenarios.map(withV5Example),podiumStudy(),leaderboardStudy()];
export const feedV5ById=(id:string|null)=>feedV5Scenarios.find(s=>s.id===id)??feedV4ById(id);
export function feedV5Ride(id:string|null){
 for(const s of [...feedScenarios.map(withV5Example),...feedV5Scenarios,...feedImports.values()] as FeedV5Scenario[]){
  const ride=s.entries.find(e=>e.ride.id===id)?.ride??(s.workshopV5?.network?.entry.ride.id===id?s.workshopV5.network.entry.ride:undefined);if(ride)return ride;
 }return feedV4Ride(id);
}
