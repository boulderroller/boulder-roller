import {wisesStudy} from '../../map/mapScenarios';
export const V5_TABS=['overview','rides','training','portfolio'] as const;
export type V5Tab=typeof V5_TABS[number];
export type V5Viewer='owner'|'visitor';
export type V5Availability='ready'|'loading'|'error'|'offline';
export type Person={id:string;name:string;handle:string;bio:string;location:string;since:string;portrait:string|null;cover:string|null;followers:number|null;following:number|null};
export type HistoryRide={id:string;riderId:string;title:string;date:string;distanceM:number;gainM:number;durationS:number;climbIds:string[];photo?:string|null;note?:string;moment?:{kind:'personal-best';climbId:string;timeSeconds:number}};
export type Standing={riderId:string;climbId:string;competitionRank:number|null;bestSeconds:number;achievedAt:string;asOf:string};
export type ProfileV5Study={version:1;candidate:'profile-v5';id:string;label:string;source:{kind:'illustrative';description:string};private:boolean;person:Person|null;rides:HistoryRide[];standings:Standing[];history:{from:string;to:string;complete:boolean}};
export type V5State={tab:V5Tab;query:string;onlyClimbs:boolean;selectedDay:string|null;detailId:string|null;metric:'distance'|'climbing'|'time';followed:boolean};
export const V5_SCENARIOS=[['rider','Alex · complete profile'],['sparse','Alex · limited history'],['new-rider','New rider'],['private','Private profile']] as const;
export const V5_GEOGRAPHY=wisesStudy.climbs.filter(c=>['43f15658','b51920f8','4fd1981e'].some(id=>c.id.startsWith(id)));
const ids=['43f15658','b51920f8','4fd1981e'].map(id=>V5_GEOGRAPHY.find(c=>c.id.startsWith(id))!.id);
const dateAt=(offset:number)=>new Date(Date.UTC(2026,8,13-offset,8)).toISOString();
export function profileV5Study(id='rider'):ProfileV5Study{
 const person:Person={id:'alex-rivera',name:'Alex Rivera',handle:'alexr',bio:'Early starts, familiar hills, and usually the long way home.',location:'Philadelphia, PA',since:'2024-04-06',portrait:'portrait',cover:'creek',followers:38,following:24};
 const titles=['Sunday through the hills','After work, before dark','Wises Mill repeats','Coffee and the long way home','A quick river loop','Back up Black Rock','Sunday with friends','Up Sprague, home by the river','A little time before work','The usual hills','An easy spin','A morning in the valley'];
 const offsets=[0,2,5,7,9,12,14,16,19,21,23,26],distances=[68200,26300,32200,84100,17400,42600,71600,48200,28100,65400,22400,51700],gain=[840,210,720,920,120,630,780,620,260,950,140,580];
 const rides:HistoryRide[]=titles.map((title,i)=>({id:`alex-ride-${i+1}`,riderId:person.id,title,date:dateAt(offsets[i]),distanceM:distances[i],gainM:gain[i],durationS:Math.round(distances[i]/7.3),climbIds:i===4||i===10?[]:[ids[i%3]]}));
 const s:ProfileV5Study={version:1,candidate:'profile-v5',id,label:V5_SCENARIOS.find(r=>r[0]===id)?.[1]??'Alex · complete profile',source:{kind:'illustrative',description:'Fictional rider, generated photographs, authored ride summaries, individual personal bests and sporting standings for this Profile design study. These are not live records. Climb geography is the separately sourced canonical Philadelphia collection retained by Map V7.'},private:false,person,rides,standings:ids.map((climbId,i)=>({climbId,riderId:person.id,competitionRank:[1,3,7][i],bestSeconds:[212,84,249][i],achievedAt:dateAt([5,12,16][i]),asOf:'2026-09-14T12:00:00Z'})),history:{from:'2026-08-17',to:'2026-09-13',complete:true}};
 s.rides[0].photo='coffee';s.rides[0].note='Coffee stop on the way home.';
 for(const [rideIndex,climbIndex] of [[2,0],[5,1],[7,2]]){s.rides[rideIndex].climbIds=[ids[climbIndex]];s.rides[rideIndex].moment={kind:'personal-best',climbId:ids[climbIndex],timeSeconds:[212,84,249][climbIndex]};}
 if(id==='sparse'){s.rides=rides.slice(0,3).map(({photo,note,moment,...ride})=>ride);s.standings=[];s.history.complete=false;s.person={...person,portrait:null,cover:null,followers:null,following:null};}
 if(id==='new-rider'){s.rides=[];s.standings=[];s.history.complete=false;s.person={...person,since:'2026-09-14',bio:'',portrait:null,cover:null,followers:0,following:0};}
 if(id==='private'){s.private=true;s.person=null;s.rides=[];s.standings=[];s.history.complete=false;}
 return s;
}
const text=(v:unknown,max=2000)=>typeof v==='string'&&v.length<=max;
const finite=(v:unknown)=>typeof v==='number'&&Number.isFinite(v)&&v>=0;
const validDate=(v:unknown)=>text(v,40)&&Number.isFinite(Date.parse(v as string));
const media=(v:unknown)=>v===null||v==='portrait'||v==='creek'||v==='coffee'||typeof v==='string'&&/^data:image\/(png|jpeg|webp);base64,[A-Za-z0-9+/=]+$/.test(v);
function check(v:unknown,message:string):asserts v{if(!v)throw Error(message);}
const exactKeys=(value:object,keys:string[])=>check(Object.keys(value).every(key=>keys.includes(key)),'Remove unsupported fields from the scenario.');
export function parseProfileV5(value:unknown):ProfileV5Study{
 const s=value as ProfileV5Study;
 check(s&&s.version===1&&s.candidate==='profile-v5'&&text(s.id,100)&&s.id.length>0&&text(s.label,200),'Choose a Profile V5 scenario.');
 exactKeys(s,['version','candidate','id','label','source','private','person','rides','standings','history']);
 check(s.source?.kind==='illustrative'&&text(s.source.description)&&s.source.description.trim(),'Keep the illustrative source declaration.');
 check(typeof s.private==='boolean'&&Array.isArray(s.rides)&&s.rides.length<=400&&Array.isArray(s.standings)&&s.standings.length<=50,'Include bounded ride and standing collections.');
 check(JSON.stringify(value).length<=8*1024*1024,'Choose a scenario smaller than 8 MB.');
 check(s.history&&validDate(s.history.from)&&validDate(s.history.to)&&s.history.from<=s.history.to&&/^\d{4}-\d{2}-\d{2}$/.test(s.history.from)&&/^\d{4}-\d{2}-\d{2}$/.test(s.history.to)&&Date.parse(s.history.to)-Date.parse(s.history.from)===27*86400000&&typeof s.history.complete==='boolean','Include a 28-day history period and its completeness.');
 exactKeys(s.source,['kind','description']);exactKeys(s.history,['from','to','complete']);
 if(s.private){check(s.person===null&&s.rides.length===0&&s.standings.length===0,'A private scenario must not contain hidden personal data.');return structuredClone(s);}
 const p=s.person;check(p&&text(p.id,100)&&p.id&&text(p.name,120)&&p.name.trim()&&text(p.handle,100)&&text(p.bio)&&text(p.location,200)&&validDate(p.since),'Include a coherent rider identity.');
 exactKeys(p,['id','name','handle','bio','location','since','portrait','cover','followers','following']);
 check(media(p.portrait)&&media(p.cover),'Use a supplied image or a PNG, JPEG or WebP data image.');
 check([p.followers,p.following].every(n=>n===null||finite(n)&&Number.isInteger(n)),'Social counts must be nonnegative whole numbers or absent.');
 const rideIds=new Set<string>();for(const r of s.rides){check(r&&text(r.id,100)&&r.id&&!rideIds.has(r.id)&&r.riderId===p.id&&text(r.title,250)&&r.title.trim()&&validDate(r.date)&&finite(r.distanceM)&&finite(r.gainM)&&finite(r.durationS)&&Array.isArray(r.climbIds)&&new Set(r.climbIds).size===r.climbIds.length&&r.climbIds.every(id=>ids.includes(id)),'Rides need unique IDs, this rider and valid supplied measurements.');exactKeys(r,['id','riderId','title','date','distanceM','gainM','durationS','climbIds','photo','note','moment']);check(r.photo===undefined||media(r.photo),'Use a supplied ride photo or safe data image.');check(r.note===undefined||text(r.note,500),'Keep ride notes under 500 characters.');if(r.moment){exactKeys(r.moment,['kind','climbId','timeSeconds']);check(r.moment.kind==='personal-best'&&r.climbIds.includes(r.moment.climbId)&&finite(r.moment.timeSeconds)&&r.moment.timeSeconds>0&&r.moment.timeSeconds<=r.durationS,'Bind each supplied personal best to this ride and climb.');}rideIds.add(r.id);}
 const climbed=new Set<string>();for(const r of s.standings){check(r&&r.riderId===p.id&&ids.includes(r.climbId)&&!climbed.has(r.climbId)&&finite(r.bestSeconds)&&r.bestSeconds>0&&validDate(r.achievedAt)&&validDate(r.asOf)&&Date.parse(r.achievedAt)<=Date.parse(r.asOf)&&(r.competitionRank===null||Number.isInteger(r.competitionRank)&&r.competitionRank>0&&r.competitionRank<=50),'Standings need this rider, a supplied climb and a current competition rank or absence.');exactKeys(r,['riderId','climbId','competitionRank','bestSeconds','achievedAt','asOf']);climbed.add(r.climbId);}
 const normalized=structuredClone(s);
 normalized.person!.since=new Date(p.since).toISOString().slice(0,10);
 normalized.rides=normalized.rides.map(r=>({...r,date:new Date(r.date).toISOString()}));
 normalized.standings=normalized.standings.map(r=>({...r,achievedAt:new Date(r.achievedAt).toISOString(),asOf:new Date(r.asOf).toISOString()}));
 return normalized;
}
export const initialV5State=():V5State=>({tab:'overview',query:'',onlyClimbs:false,selectedDay:null,detailId:null,metric:'distance',followed:false});
export function projectV5(s:ProfileV5Study,_viewer:V5Viewer){
 const person=s.private?null:s.person,rides=person?[...s.rides].sort((a,b)=>Date.parse(b.date)-Date.parse(a.date)):[],standings=person?s.standings:[];
 const range=rides.filter(r=>r.date.slice(0,10)>=s.history.from&&r.date.slice(0,10)<=s.history.to);
 const days=Array.from({length:Math.min(366,Math.max(0,Math.round((Date.parse(s.history.to)-Date.parse(s.history.from))/86400000)+1))},(_,i)=>{const date=new Date(Date.parse(s.history.from)+i*86400000).toISOString().slice(0,10);return {date,rides:range.filter(r=>r.date.startsWith(date))};});
 const summary=person&&s.history.complete?range.reduce((a,r)=>({count:a.count+1,distance:a.distance+r.distanceM,climbing:a.climbing+r.gainM,time:a.time+r.durationS}),{count:0,distance:0,climbing:0,time:0}):null;
 return {person,rides,standings,summary,days};
}
export function restoreV5State(s:ProfileV5Study,viewer:V5Viewer,raw:Partial<V5State>):V5State{
 const p=projectV5(s,viewer);return {...initialV5State(),tab:viewer==='owner'&&V5_TABS.includes(raw.tab as V5Tab)?raw.tab!:'overview',query:typeof raw.query==='string'?raw.query:'',onlyClimbs:raw.onlyClimbs===true,selectedDay:p.days.some(d=>d.date===raw.selectedDay)?raw.selectedDay!:null,detailId:p.rides.some(r=>r.id===raw.detailId)?raw.detailId!:null,metric:raw.metric==='climbing'||raw.metric==='time'?raw.metric:'distance',followed:raw.followed===true};
}
export const v5Key=(id:string)=>`br-profile-v5:${id}`;
export function resolveV5Study(id:string){try{const stored=sessionStorage.getItem(v5Key(id));if(stored){const s=parseProfileV5(JSON.parse(stored));if(s.id!==id)throw Error('Mismatched scenario ID.');return s;}}catch(e){throw e;}
 if(!V5_SCENARIOS.some(s=>s[0]===id))throw Error('Imported Profile scenario unavailable.');return profileV5Study(id);
}
