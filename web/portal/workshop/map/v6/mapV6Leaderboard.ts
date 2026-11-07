import {parseMapStudy,type MapClimb,type MapStudy} from '../mapModel';

type PublicEntry={wallet:string;position:number;competition_rank:number;best_time_seconds:number;tie_size:number;is_tied:boolean};
export type PublicLeaderboardSnapshot={
 sourceUrl:string;capturedAt:string;
 response:{climb_id:string;kom_holder:string|null;kom_time_s:number|null;entries:PublicEntry[]};
};
export type MapV6Climb=MapClimb & {publicLeaderboard?:PublicLeaderboardSnapshot};
export type MapV6Study=MapStudy & {climbs:MapV6Climb[]};
export type PublicLeader={wallet:string;name:string;timeSeconds:number;tied:boolean;capturedAt:string;sourceUrl:string};
const seconds=(n:unknown):n is number=>typeof n==='number'&&Number.isInteger(n)&&n>0;
const text=(s:unknown):s is string=>typeof s==='string'&&s.trim().length>0&&s.length<=600;
function check(ok:unknown,message:string):asserts ok{if(!ok)throw Error(message);}

/** An import is a retained public snapshot, never a claim of current leaderboard state. */
function validateBoard(climb:MapV6Climb){
 const s=climb.publicLeaderboard;if(s===undefined)return;
 check(s&&typeof s==='object','Supply a public leaderboard snapshot.');
 const url=new URL(s.sourceUrl);
 check(url.origin==='https://api.boulderroller.xyz'&&!url.username&&!url.password&&url.pathname===`/climbs/${climb.id}/leaderboard`&&!url.search&&!url.hash,'Use the public leaderboard source for the same canonical climb.');
 check(typeof s.capturedAt==='string'&&/^\d{4}-\d{2}-\d{2}T/.test(s.capturedAt)&&Number.isFinite(Date.parse(s.capturedAt)),'Include the public leaderboard capture time.');
 const b=s.response;
 check(b&&b.climb_id===climb.id,'The public leaderboard must belong to the same canonical climb.');
 check(Array.isArray(b.entries)&&b.entries.length<=1000,'Include the original public leaderboard entries.');
 check(new Set(b.entries.map(e=>e.wallet)).size===b.entries.length,'Public leaderboard wallets must be unique.');
 for(const e of b.entries){
  check(text(e.wallet)&&Number.isInteger(e.position)&&e.position>0&&Number.isInteger(e.competition_rank)&&e.competition_rank>0&&seconds(e.best_time_seconds),'Preserve public positions, competition ranks and integer times.');
  check(Number.isInteger(e.tie_size)&&e.tie_size>=1&&e.is_tied===(e.tie_size>1),'Preserve the supplied tie size and tie flag together.');
  const identity=e as PublicEntry & {display_name?:unknown;username?:unknown;avatar_url?:unknown};
  check(identity.display_name==null&&identity.username==null&&identity.avatar_url==null,'This canonical leaderboard source does not supply rider names or portraits.');
 }
 if(b.kom_holder===null){check(b.kom_time_s===null,'Withheld or absent holder time must also be absent.');return;}
 check(text(b.kom_holder)&&seconds(b.kom_time_s),'Include an explicit public holder and integer time, or null for both.');
 const holder=b.entries.find(e=>e.wallet===b.kom_holder);
 check(holder&&holder.competition_rank===1&&holder.best_time_seconds===b.kom_time_s,'The public holder must match a supplied first-place result.');
}

export function parseMapV6Study(input:unknown):MapV6Study{
 const s=parseMapStudy(input) as MapV6Study;
 for(const climb of s.climbs)validateBoard(climb);
 return s;
}
export function importMapV6Study(input:unknown,key:string){const s=parseMapV6Study(input);s.id=`map-import-${key}`;return s;}

/** Also fails closed for scenarios imported while an older candidate was selected. */
export function publicLeader(climb:MapClimb):PublicLeader|null{
 const c=climb as MapV6Climb;
 try{validateBoard(c);}catch{return null;}
 const s=c.publicLeaderboard,b=s?.response;
 if(!s||!b?.kom_holder)return null;
 const e=b.entries.find(e=>e.wallet===b.kom_holder)!;
 return {wallet:e.wallet,name:`${e.wallet.slice(0,4)}…${e.wallet.slice(-4)}`,timeSeconds:b.kom_time_s!,tied:e.is_tied,capturedAt:s.capturedAt,sourceUrl:s.sourceUrl};
}
