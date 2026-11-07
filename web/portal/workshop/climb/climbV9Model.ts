import {climbStudies,type ClimbStudy} from './climbModel';
import {v7Study,parseV7Study,importV7Study,allocationKeys,type ClimbV7Study,type VaultWeek} from './climbV7Model';
import {v8Effort,v8Ride} from './climbV8Model';
import {climbResult} from '../scenario';

/** Explicit candidate evidence: independent qualifying attempts, never a watts-derived filter. */
export type VaultAttempt={id:string;rowId:string;duration:number;date:string;entryId?:string};
export type ClimbV9Study=ClimbV7Study&{candidate9?:{source:string;attempts:VaultAttempt[]}};
export function vaultAttempts(attempts:VaultAttempt[]){
 const best=new Map<string,VaultAttempt>();
 for(const a of attempts){const old=best.get(a.rowId);if(!old||a.duration<old.duration||(a.duration===old.duration&&Date.parse(a.date)<Date.parse(old.date)))best.set(a.rowId,a);}
 const sorted=[...best.values()].sort((a,b)=>a.duration-b.duration||Date.parse(a.date)-Date.parse(b.date)||a.id.localeCompare(b.id));
 return sorted.map(a=>({...a,rank:sorted.findIndex(b=>b.duration===a.duration)+1}));
}
export const v9Effort=(href:string)=>v8Effort(href).replace('climbOriginVariant=climb-v8','climbOriginVariant=climb-v9');
export const v9Ride=(href:string)=>v8Ride(href).replace('climbOriginVariant=climb-v8','climbOriginVariant=climb-v9');
// Candidate decimal amounts are added in nanounits, so inspection never exposes binary float tails.
export function settlementTotal(week:Pick<VaultWeek,'allocations'>){return allocationKeys.reduce((n,k)=>n+Math.round(week.allocations[k]*1e9),0)/1e9;}
function makeStudy(base:ClimbStudy):ClimbV9Study{
 const s=structuredClone(v7Study(base)) as ClimbV9Study;
 const e=s.candidate7?.economy,board=s.feed?.workshopV6?.leaderboards.find(b=>b.climbId===s.climbId);
 if(!e||!board)return s;
 s.candidate9={source:'V9 authored design study: independently supplied qualifying attempts, not a qualification computed from watts or a live paid leaderboard. Twelve settled weeks are layout fixtures. Existing retained recordings and missing sensor channels remain unchanged. No historical personal entitlement or on-chain claim is inferred.',attempts:board.rows.filter(r=>![1,4,6].includes(r.rank)).map(r=>({id:`v9-qualified-${r.id}`,rowId:r.id,duration:r.duration,date:s.candidate7!.rowDates[r.id],entryId:s.feed!.entries.find(e=>e.ride.id===r.rideId)?.id}))};
 const overallLeader=board.rows.find(r=>r.rank===1);
 if(overallLeader)s.candidate9.attempts.push({id:'v9-qualified-earlier-leader',rowId:overallLeader.id,duration:239,date:'2016-08-17'});
 s.source=s.candidate9.source;
 const older=[360,480,420,600,540,720,660,780,720];
 const iso=(ms:number)=>new Date(ms).toISOString();
 const first=Date.parse('2016-06-06T12:00:00Z'),weekMs=7*86400000;
 const weeks=older.map((total,i):VaultWeek=>({id:`v9-week-${i}`,start:iso(first+i*weekMs),end:iso(first+(i+1)*weekMs),settledAt:iso(first+(i+1)*weekMs+86400000),allocations:{leaderboard:total*.82,positions:0,legend:total*.03,pol:total*.05,treasury:total*.1},carry:{leaderboard:0,positions:0,legend:0,pol:0,treasury:0}}));
 e.weeks=[...weeks,...e.weeks.map(w=>({...w,start:`${w.start}T12:00:00Z`,end:`${w.end}T12:00:00Z`}))];
 e.weeks.forEach(w=>allocationKeys.forEach(k=>w.allocations[k]=Math.round(w.allocations[k]*1e9)/1e9));
 e.source=s.candidate9.source;
 return parseV9Study(s);
}
export function parseV9Study(input:unknown):ClimbV9Study{
 const s=parseV7Study(input) as ClimbV9Study,v=s.candidate9;if(!v)return s;
 const ok=(value:unknown,message:string)=>{if(!value)throw Error(message);};
 ok(typeof v.source==='string'&&v.source.length>0&&Array.isArray(v.attempts)&&v.attempts.length<=1000,'Include V9 qualification provenance and attempts.');
 const board=s.feed?.workshopV6?.leaderboards.find(b=>b.climbId===s.climbId),ids=new Set<string>();
 for(const a of v.attempts){
  const row=board?.rows.find(r=>r.id===a.rowId);
  ok(typeof a.id==='string'&&a.id.length>0&&!ids.has(a.id)&&row&&Number.isFinite(a.duration)&&a.duration>0&&a.duration>=row.duration-.01&&Number.isFinite(Date.parse(a.date)),'Bind each qualifying attempt to its rider and a valid date and duration.');ids.add(a.id);
  if(a.entryId){const entry=s.feed?.entries.find(e=>e.id===a.entryId),climb=entry?.ride.climbs.find(c=>c.id===s.climbId),rider=s.feed?.workshopV7?.riders.find(r=>r.boardRows.includes(`${s.climbId}:${a.rowId}`));
   ok(entry&&climb&&rider?.entryIds.includes(entry.id)&&Math.abs(climbResult(entry.ride,climb).duration-a.duration)<.01&&entry.ride.ride.startedAt.slice(0,10)===a.date.slice(0,10),'Qualifying recording must match its rider, climb, date and time.');
  }
 }
 const weeks=[...(s.candidate7?.economy?.weeks??[])].sort((a,b)=>Date.parse(a.start)-Date.parse(b.start));
 weeks.forEach((w,i)=>{ok(!i||Date.parse(weeks[i-1].end)<=Date.parse(w.start),'Settlement periods must not overlap.');ok(allocationKeys.every(k=>Number.isSafeInteger(Math.round(w.allocations[k]*1e9))&&Number.isSafeInteger(Math.round(w.carry[k]*1e9)))&&Number.isSafeInteger(Math.round(settlementTotal(w)*1e9)),'Settlement amount exceeds candidate precision.');});
 return s;
}
const studies=climbStudies.map(makeStudy);
export function v9Study(input:ClimbStudy):ClimbV9Study{return studies.find(s=>s.id===input.id)??input;}
export function importV9Study(input:unknown,key:string){parseV9Study(input);return parseV9Study(importV7Study(input,key));}
