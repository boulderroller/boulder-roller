import {baselineScenario,baselineRooms} from '../baseline/model';
import {responseFor} from '../baseline/fixtures/portal';
export const PROFILE_SCENARIOS=baselineRooms.find(r=>r.id==='profile')!.scenarios;
export type ProfileScenario={version:1;room:'profile';candidate:'profile-v2';id:string;label:string;viewer:'owner'|'public';route:string;source:{kind:'supplied-fixture';revision:string;file:string;capturedAt:string|null};responses:Record<string,unknown>};
type Row=Record<string,unknown>;
const object=(v:unknown):Row=>v&&typeof v==='object'&&!Array.isArray(v)?v as Row:{};
const rows=(v:unknown):Row[]=>Array.isArray(v)?v.map(object):[];
const text=(v:unknown)=>typeof v==='string'&&v.trim()?v.trim():null;
const number=(v:unknown)=>typeof v==='number'&&Number.isFinite(v)&&v>=0?v:null;
const date=(v:unknown)=>typeof v==='string'&&Number.isFinite(Date.parse(v))?new Date(v).toISOString():null;
export type ProfileRide={id:string;name:string;date:string|null;distance:number|null;elevation:number|null;duration:number|null};
export type ProfileStanding={id:string|null;name:string;time:number|null;date:string|null;place:number|null;length:number|null;gradient:number|null};
export type ProfileView={private:boolean;identity:{name:string;handle:string|null;bio:string|null;since:string|null;followers:number|null;following:number|null}|null;totalRides:number|null;rides:ProfileRide[];standings:ProfileStanding[];standingAvailable:boolean;historyAvailable:boolean};
export function profileScenario(id='owner'):ProfileScenario{
 const baseline=baselineScenario('profile',id),owner=baseline.viewer==='owner';
 const options={darkMode:false,withRideMedia:true,...(id==='empty'?{rideListTotal:0,profileRideTotal:0}:{})};
 const paths=owner?['/users/me','/rides?limit=400','/users/me/leaderboard-positions','/climbs/list']:id==='private'?[]:['/users/tim/profile','/users/tim/leaderboard-positions','/climbs/list'];
 return {...baseline,room:'profile',candidate:'profile-v2',viewer:owner?'owner':'public',responses:Object.fromEntries(paths.map(path=>['GET '+path,responseFor(new URL(path,'http://workshop.local'),'GET',options)]))};
}
export function parseProfileImport(value:unknown):ProfileScenario{
 const v=object(value),id=text(v.id);if(!id||!PROFILE_SCENARIOS.some(s=>s.id===id))throw Error('Choose a supplied Profile scenario.');
 const expected=profileScenario(id);
 if(v.version!==1||v.room!=='profile'||v.candidate!=='profile-v2'||v.viewer!==expected.viewer||v.route!==expected.route)throw Error('The Profile room, V2 candidate, scenario, viewer and route must match.');
 const source=object(v.source);if(source.kind!=='supplied-fixture'||!text(source.file)||!text(source.revision))throw Error('Include supplied-data provenance. Imports are never live evidence.');
 const response=object(v.responses),allowed=Object.keys(expected.responses);
 if(!v.responses||Array.isArray(v.responses)||Object.keys(response).some(k=>!allowed.includes(k)))throw Error('Only the exact GET responses for this Profile viewer are allowed.');
 if(JSON.stringify(v).length>5*1024*1024)throw Error('Choose a Profile scenario smaller than 5 MB.');
 return structuredClone(value) as ProfileScenario;
}
export function profileView(s:ProfileScenario):ProfileView{
 const owner=s.viewer==='owner',response=s.responses,bootstrap=object(response['GET /users/tim/profile']);
 const profile=object(owner?response['GET /users/me']:bootstrap.profile),privacy=object(bootstrap.privacy),capability=object(bootstrap.viewer_capabilities);
 const hidden=!owner&&(s.id==='private'||privacy.can_view!==true||capability.can_view!==true||profile.is_public!==true||object(profile.privacy).can_view!==true||rows(bootstrap.modules).some(m=>(m.key==='profile'||m.id==='profile')&&m.state!=='present')||object(bootstrap.rider).id!==profile.id);
 const empty:ProfileView={private:hidden,identity:null,totalRides:null,rides:[],standings:[],standingAvailable:false,historyAvailable:false};if(hidden)return empty;
 if(!text(profile.id))return empty;
 const recent=object(bootstrap.recent_rides),modules=rows(bootstrap.modules),hiddenModule=(key:string)=>modules.some(m=>(m.key===key||m.id===key)&&m.state!=='present');
 const rideInput=owner?response['GET /rides?limit=400']:recent.is_public===true&&object(recent.privacy).can_view!==false&&object(recent.privacy).visibility!=='private'&&!hiddenModule('recent_rides')?recent.rides:undefined;
 const identity={name:text(profile.display_name)??text(profile.username)??'Rider',handle:text(profile.username),bio:text(profile.bio),since:date(profile.created_at),followers:number(profile.follower_count),following:number(profile.following_count)};
 const rides=rows(rideInput).filter(r=>text(r.id)&&text(r.title)&&(owner?r.rider_id===profile.id:r.visibility==='public')).filter(r=>object(r.privacy).can_view!==false).map(r=>({id:String(r.id),name:String(r.title),date:date(r.started_at),distance:number(r.distance_m),elevation:number(owner?r.elevation_m:r.elevation_gain_m),duration:number(owner?r.duration_s:r.duration_sec)})).sort((a,b)=>Date.parse(b.date??'')-Date.parse(a.date??''));
 const board=object(response[owner?'GET /users/me/leaderboard-positions':'GET /users/tim/leaderboard-positions']);
 // Wildcard fixtures can belong to another wallet. Never borrow that rider's standing.
 const bound=!!text(profile.wallet)&&board.wallet===profile.wallet&&!hiddenModule('leaderboard');
 const climbs=rows(object(response['GET /climbs/list']).climbs);
 const standings=bound?rows(board.positions).filter(p=>Number.isInteger(p.vault_id)&&Number(p.vault_id)>0).map(p=>{const matching=climbs.filter(c=>c.vault_id===p.vault_id),climb=matching.length===1?matching[0]:{};return {id:text(climb.id),name:text(climb.name)??text(p.vault_name)??'Climb',time:number(p.best_time_seconds),date:date(p.achieved_at),place:Number.isInteger(p.competition_rank)&&Number(p.competition_rank)>0?Number(p.competition_rank):null,length:number(climb.length_m),gradient:number(climb.avg_gradient_pct)};}):[];
 return {private:false,identity,totalRides:number(profile.total_rides),rides,standings,standingAvailable:bound&&Array.isArray(board.positions),historyAvailable:Array.isArray(rideInput)};
}
export function historyMonths(rides:ProfileRide[]){return [...new Set(rides.flatMap(r=>r.date?[r.date.slice(0,7)]:[]))].sort().reverse();}
export function historyRows(rides:ProfileRide[],month:string){return month==='all'?rides:rides.filter(r=>r.date?.startsWith(month));}
export function profileStorageKey(s:ProfileScenario){return `br-profile-v2:${s.id}:${s.viewer}`;}
export const raceTime=(seconds:number)=>`${Math.floor(seconds/60)}:${String(Math.floor(seconds%60)).padStart(2,'0')}`;
export const duration=(seconds:number)=>`${Math.floor(seconds/3600)}h ${Math.floor(seconds%3600/60)}m`;
export const profileDate=(value:string)=>new Intl.DateTimeFormat('en-US',{month:'short',day:'numeric',year:'numeric',timeZone:'UTC'}).format(new Date(value));
export const monthLabel=(value:string)=>new Intl.DateTimeFormat('en-US',{month:'long',year:'numeric',timeZone:'UTC'}).format(new Date(value+'-01T12:00:00Z'));
export function retainProfileScenario(previous:ProfileScenario|null,next:ProfileScenario){return previous&&JSON.stringify(previous)===JSON.stringify(next)?previous:next;}
export function compatibleProfileDetail(scenario:ProfileScenario,href:string){
 const match=/^\/(rides|climbs)\/([^/?#]+)$/.exec(href);if(!match)return true;
 if(scenario.viewer!=='owner')return false;
 const current=profileView(scenario),original=profileView(profileScenario(scenario.id));
 let id:string;try{id=decodeURIComponent(match[2]);}catch{return false;}
 const before=match[1]==='rides'?original.rides.find(r=>r.id===id):original.standings.find(r=>r.id===id);
 const after=match[1]==='rides'?current.rides.find(r=>r.id===id):current.standings.find(r=>r.id===id);
 if(!before||!after||JSON.stringify(before)!==JSON.stringify(after))return false;
 if(match[1]==='climbs'){const target=object(responseFor(new URL(href,'http://workshop.local'),'GET',{darkMode:false,withClimbViewSpecimen:true,withRideMedia:true}));const climb=after as ProfileStanding;return target.id===id&&target.name===climb.name&&target.length_m===climb.length&&target.avg_gradient_pct===climb.gradient;}
 return true;
}
