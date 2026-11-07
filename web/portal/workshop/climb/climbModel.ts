import {feedV7ById,parseFeedV7,rekeyV7Feed,riderForBoard,riderForEntry,type FeedV7Scenario} from '../feed/feedV7Model';
import {v6Entries,v6NetworkTerrain} from '../feed/feedV6Model';
import {v9RideHref,v9RiderHref} from '../feed/feedV9Model';
import {climbResult} from '../scenario';
import type {DiscoveryV4} from '../feed/feedV4Model';
import live from './data/live-climb.json';
export type ClimbViewer='rider'|'visitor'|'signed-out';
export type ClimbStudy={version:1;id:string;label:string;source:string;climbId:string;terrainRideId?:string;feed?:FeedV7Scenario;terrain?:DiscoveryV4;personal:boolean;emptyLeaderboard?:boolean;noVault?:boolean;vault?:{source:string;climbId:string;viewerId:string;depositedCal:number;settlement:'waiting'}};
export const climbImports=new Map<string,ClimbStudy>();
const feed=feedV7ById('mixed'),entry=feed.entries.find(e=>e.owned)!;
const base:ClimbStudy={version:1,id:'wises',label:'Wises Mill Road · returning rider',source:'Retained ride traversal. People, leaderboard excerpt and prior efforts are illustrative, explicitly bound examples; only supplied recordings have ride links. No canonical Vault binding is inferred.',climbId:'43f15658',terrainRideId:entry.ride.id,feed,personal:true};
const bounds=live.climb.routePreview.bounds;
const canonical:DiscoveryV4={name:live.climb.name,source:`Public canonical geography captured ${live.freshness.loadedAt}. ${live.climb.geographicData.attribution.text}. Elevation: USGS. ${live.climb.geographicData.manifest_url}`,length:live.climb.lengthM,gain:live.climb.elevGainM,profile:live.climb.elevationProfile.map(p=>({d:p.distance_m,elevation:p.elevation_m})),geometry:{type:'LineString',coordinates:live.climb.routePreview.points.map(p=>[bounds.minLon+p.x*(bounds.maxLon-bounds.minLon),bounds.maxLat-p.y*(bounds.maxLat-bounds.minLat)])}};
export const climbStudies:ClimbStudy[]=[base,
 {...base,id:'black-rock',label:'Black Rock Road · leaderboard',climbId:'b51920f8',personal:false},
 {...base,id:'sprague',label:'Sprague Road · recorded comparison',feed:feedV7ById('network-3'),climbId:'4fd1981e',personal:false},
 {...base,id:'first-visit',label:'Wises Mill Road · first visit',personal:false},
 {...base,id:'vault',label:'Vault · example position',source:base.source+' Separate illustrative Vault position: 1,200 CAL, supplied Waiting state; no total deposits, DUNG, eligibility or live account asserted.',vault:{source:'Illustrative position layout, using the 1.2K CAL example from PROOF_ECONOMY_PRIMITIVES. No transaction is submitted.',climbId:base.climbId,viewerId:feed.workshopV7!.riders.find(r=>r.viewer)!.id,depositedCal:1200,settlement:'waiting'}},
 {version:1,id:'live-geography',label:'Jefferson / North Woodbine · public geography',climbId:live.climb.id,source:canonical.source,terrain:canonical,personal:false,emptyLeaderboard:live.climb.recordBoard.entries.length===0,noVault:live.climb.vaultEconomy.has_vault===false}
];
export const climbById=(id:string|null)=>climbImports.get(id??'')??climbStudies.find(s=>s.id===id)??climbStudies[0];
export const selectedTerrain=(profile:DiscoveryV4['profile'],range:[number,number]|null)=>{
 if(!range)return null;const [a,b]=range.map(i=>profile[i]);if(!a||!b||b.d-a.d<50)return null;
 return {distance:b.d-a.d,rise:b.elevation-a.elevation,grade:(b.elevation-a.elevation)/(b.d-a.d)*100};
};
export function inspectClimb(s:ClimbStudy,viewer:ClimbViewer){
 const entries=s.feed?v6Entries(s.feed):[],terrainEntry=entries.find(e=>e.ride.id===s.terrainRideId),climb=terrainEntry?.ride.climbs.find(c=>c.id===s.climbId);
 const terrain=s.terrain??(terrainEntry&&climb?v6NetworkTerrain({entry:terrainEntry,climbId:s.climbId,regionId:'',leaderboard:{rank:1},source:s.source}):null);
 const viewerRider=viewer==='rider'?s.feed?.workshopV7?.riders.find(r=>r.viewer):undefined;
 const ownEntry=s.personal&&viewerRider?entries.find(e=>e.owned&&viewerRider.entryIds.includes(e.id)&&e.ride.climbs.some(c=>c.id===s.climbId)):undefined;
 const ownClimb=ownEntry?.ride.climbs.find(c=>c.id===s.climbId);
 const sourceBoard=s.feed?.workshopV6?.leaderboards.find(b=>b.climbId===s.climbId);
 const href=(ride:typeof entries[number],view:'overview'|'analysis'='overview')=>{
  const u=new URL(v9RideHref(ride,s.climbId,view,s.feed!.id),'http://workshop.local');u.searchParams.set('viewer',viewer==='rider'&&ride.owned?'owner':'visitor');u.searchParams.set('climbOrigin',s.id);u.searchParams.set('climbOriginViewer',viewer);return u.pathname+u.search;
 };
 const board=sourceBoard?{asOf:sourceBoard.asOf,rows:[...sourceBoard.rows].sort((a,b)=>a.rank-b.rank).map(row=>{
  const rider=s.feed?riderForBoard(s.feed,s.climbId,row.id):undefined,recording=entries.find(e=>e.ride.id===row.rideId);
  return {...row,current:!!viewerRider&&rider?.id===viewerRider.id,href:recording?href(recording):undefined,riderHref:s.feed&&rider?v9RiderHref(s.feed,rider.id):undefined};
 })}:undefined;
 const personal=ownEntry&&ownClimb&&viewerRider?(()=>{const result=climbResult(ownEntry.ride,ownClimb),rows=[{date:ownEntry.ride.ride.startedAt,duration:result.duration,href:href(ownEntry),analysisHref:href(ownEntry,'analysis'),current:true},...ownClimb.history.map(h=>({...h,href:undefined,analysisHref:undefined,current:false}))].sort((a,b)=>Date.parse(b.date)-Date.parse(a.date));return {name:viewerRider.name,riderHref:v9RiderHref(s.feed!,viewerRider.id),rows,best:Math.min(...rows.map(r=>r.duration)),latest:rows[0],power:result.power,rank:board?.rows.find(r=>r.current)?.rank};})():undefined;
 const vault=viewerRider&&s.vault?.viewerId===viewerRider.id?s.vault:undefined;
 return {terrain,board,personal,vault,viewerRider,recordings:entries.filter(e=>e.ride.climbs.some(c=>c.id===s.climbId)).map(e=>({entry:e,rider:s.feed?riderForEntry(s.feed,e.id):undefined,href:href(e)}))};
}
function ensure(ok:unknown,message:string):asserts ok{if(!ok)throw Error(message);}
export function parseClimbStudy(input:unknown):ClimbStudy{
 ensure(input&&typeof input==='object','Choose an exported climb scenario.');const s=structuredClone(input) as ClimbStudy;
 ensure(s.version===1&&typeof s.id==='string'&&s.id.length>0&&s.id.length<=200&&typeof s.label==='string'&&s.label.length<=300&&typeof s.source==='string'&&s.source.length>0&&typeof s.climbId==='string'&&typeof s.personal==='boolean','Include climb identity, source and personal-context policy.');
 if(s.feed){s.feed=parseFeedV7(s.feed);ensure(v6Entries(s.feed).some(e=>e.ride.id===s.terrainRideId&&e.ride.climbs.some(c=>c.id===s.climbId)),'Terrain recording must contain this climb.');}
 if(s.terrain){const t=s.terrain;ensure(typeof t.name==='string'&&t.name.length<=600&&typeof t.source==='string'&&Number.isFinite(t.length)&&t.length>0&&Number.isFinite(t.gain)&&t.gain>=0&&Array.isArray(t.profile)&&t.profile.length>=2&&t.profile.length<=100000,'Include valid terrain measurements.');ensure(t.geometry?.type==='LineString'&&t.geometry.coordinates.length===t.profile.length,'Geometry and profile must share sample positions.');ensure(t.profile.every((p,i)=>Number.isFinite(p.d)&&Number.isFinite(p.elevation)&&(i===0?p.d===0:p.d>t.profile[i-1].d))&&Math.abs(t.profile.at(-1)!.d-t.length)<.1,'Profile distances must cover the climb.');ensure(t.geometry.coordinates.every(p=>Array.isArray(p)&&p.length===2&&Number.isFinite(p[0])&&Math.abs(p[0])<=180&&Number.isFinite(p[1])&&Math.abs(p[1])<=85),'Invalid terrain coordinates.');}
 ensure(!!inspectClimb(s,'visitor').terrain,'This climb requires a continuous terrain profile.');
 if(s.vault)ensure(s.vault.climbId===s.climbId&&typeof s.vault.source==='string'&&s.vault.source.length>0&&Number.isFinite(s.vault.depositedCal)&&s.vault.depositedCal>=0&&s.vault.settlement==='waiting'&&s.feed?.workshopV7?.riders.some(r=>r.id===s.vault!.viewerId&&r.viewer),'Vault position must be supplied and bound to this climb and viewer.');
 const own=inspectClimb(s,'rider');if(own.personal){const row=own.board?.rows.find(r=>r.current);ensure(!row||row.duration<=own.personal.best+.01,'Personal best and current all-time leaderboard need consistent eligibility.');}
 return s;
}
export function importClimbStudy(input:unknown,key:string){const s=parseClimbStudy(input);s.id=`climb-import-${key}`;if(s.feed){const old=s.feed;s.feed=rekeyV7Feed(old,key);s.terrainRideId=v6Entries(s.feed)[v6Entries(old).findIndex(e=>e.ride.id===s.terrainRideId)]?.ride.id;}return parseClimbStudy(s);}
