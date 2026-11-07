import {climbStudies,parseClimbStudy,importClimbStudy,inspectClimb,type ClimbStudy,type ClimbViewer} from './climbModel';
import {cropScenario,climbResult} from '../scenario';
import {feedImports} from '../feed/feedModel';
import {v9RideHref} from '../feed/feedV9Model';
import {climbV3EffortHref} from './climbV3Navigation';

export type AllocationKey='leaderboard'|'positions'|'legend'|'pol'|'treasury';
export const allocationLabels:Record<AllocationKey,string>={leaderboard:'Leaderboard',positions:'Deposited CAL',legend:'Local Legend',pol:'Liquidity',treasury:'Treasury'};
export const allocationKeys:AllocationKey[]=['leaderboard','positions','legend','pol','treasury'];
export type VaultWeek={id:string;start:string;end:string;settledAt:string;allocations:Record<AllocationKey,number>;carry:Record<AllocationKey,number>};
export type ClimbV7Economy={source:string;climbId:string;asOf:string;lifetimeTributeCal:number;depositedPrincipalCal:number;weeks:VaultWeek[];account?:{viewerId:string;availableCal:number};position?:{viewerId:string;depositedCal:number;since:string;readyDung:number;availableCal:number};legend?:{riderId:string;name:string;completions:number;termEnd:string}};
export type ClimbV7Study=ClimbStudy&{candidate7?:{source:string;historyRecordings:{date:string;entryId:string}[];rowDates:Record<string,string>;economy?:ClimbV7Economy}};
export const amount=(n:number)=>n.toLocaleString('en-US',{maximumFractionDigits:2});
export const ordinal=(n:number)=>`${n}${n%100>=11&&n%100<=13?'th':({1:'st',2:'nd',3:'rd'} as Record<number,string>)[n%10]??'th'}`;
export const allocationShare=(value:number,total:number)=>total>0?value/total*100:0;
export const validDeposit=(value:string,available:number)=>value.trim()!==''&&Number.isInteger(Number(value))&&Number(value)>=100&&Number(value)<=available;
export const weekTotal=(week:VaultWeek)=>allocationKeys.reduce((sum,key)=>sum+week.allocations[key],0);
export const historyGap=(duration:number,reference:number)=>{const diff=(Math.round(duration*10)-Math.round(reference*10))/10;return diff===0?'0':`${diff<0?'−':'+'}${Math.abs(diff)}`;};
export function historySelection(selected:string|null,id:string){return selected===id?null:id;}
export function v7Effort(href:string){const p=new URLSearchParams(climbV3EffortHref(href).slice(2));p.set('climbOriginVariant','climb-v7');return `/?${p}`;}
const blankCarry=()=>({leaderboard:0,positions:0,legend:0,pol:0,treasury:0});
function exampleEconomy(s:ClimbStudy):ClimbV7Economy{
 const viewer=s.feed!.workshopV7!.riders.find(r=>r.viewer)!,legend=s.feed!.workshopV7!.riders.find(r=>r.name==='Jamie')!;
 // One eligible position unlocks 1% of the 27% bucket. The remainder goes to the Leaderboard.
 const week=(start:string,end:string,settledAt:string,total:number):VaultWeek=>({id:start,start,end,settledAt,allocations:{leaderboard:total*.8173,positions:total*.0027,legend:total*.03,pol:total*.05,treasury:total*.1},carry:blankCarry()});
 return {source:'Authored V7 layout data, not a chain capture: lifetime tribute and principal are separate supplied amounts; three settled weeks use one eligible position and the ratified 1% participation unlock. No transaction, real balance, payout or yield is asserted.',climbId:s.climbId,asOf:'2016-08-30T12:00:00Z',lifetimeTributeCal:18426.72,depositedPrincipalCal:5800,account:{viewerId:viewer.id,availableCal:486.24},weeks:[week('2016-08-22','2016-08-29','2016-08-30T12:00:00Z',1080),week('2016-08-15','2016-08-22','2016-08-23T12:00:00Z',960),week('2016-08-08','2016-08-15','2016-08-16T12:00:00Z',840)],position:s.personal?{viewerId:viewer.id,depositedCal:1200,since:'2016-08-01',readyDung:7.776,availableCal:486.24}:undefined,legend:{riderId:legend.id,name:legend.name,completions:18,termEnd:'2016-09-26'}};
}
function makeStudy(original:ClimbStudy):ClimbV7Study{
 const s=structuredClone(original) as ClimbV7Study;
 if(!s.feed||!['wises','first-visit','vault'].includes(s.id))return s;
 s.feed.id=`climb-v7-${s.id}`;
 const own=s.feed.entries.find(e=>e.owned)!,climb=own.ride.climbs.find(c=>c.id===s.climbId)!,board=s.feed.workshopV6!.leaderboards.find(b=>b.climbId===s.climbId)!;
 const metadata:NonNullable<ClimbV7Study['candidate7']>={source:'V7: complete ten-seat illustrative board. Historical effort links use explicitly synthetic timing examples over retained terrain, with power, cadence and heart rate omitted. These are not additional recorded rides. Economics are authored layout data, not chain evidence.',historyRecordings:[],rowDates:{}};
 const viewer=s.feed.workshopV7!.riders.find(r=>r.viewer)!;
 for(const [i,h] of (s.personal?climb.history:[]).entries()){
  const ride=cropScenario(own.ride,climb.start,climb.end),duration=climbResult(own.ride,climb).duration,factor=h.duration/duration;
  ride.id=`climb-v7-history-${s.climbId}-${i}`;ride.label=`${climb.name} · ${h.date.slice(0,10)} · history study`;
  ride.source={kind:'illustrative',history:'none',description:'Synthetic timing example over retained Wises Mill Road terrain. Date and duration are authored history fixtures; sensor channels are absent. Not a second real recording.'};
  ride.ride.title=climb.name;ride.ride.startedAt=`${h.date.slice(0,10)}T14:00:00Z`;
  ride.ride.samples=ride.ride.samples.map(p=>({...p,t:p.t*factor,power:null,cadence:null,heartRate:null,speed:null}));
  ride.climbs=ride.climbs.map(c=>({...c,start:c.start*factor,end:c.end*factor,history:[]}));
  const entry={...structuredClone(own),id:`climb-v7-history-entry-${s.id}-${i}`,ride,description:'',companions:[],comments:[],kudos:0};
  s.feed.entries.push(entry);viewer.entryIds.push(entry.id);metadata.historyRecordings.push({date:h.date,entryId:entry.id});
 }
 const inserted=[{rank:4,name:'Casey',duration:231},{rank:5,name:'Rowan',duration:233},{rank:6,name:'Taylor',duration:234},{rank:8,name:'Sam',duration:241},{rank:9,name:'Robin',duration:248},{rank:10,name:'Drew',duration:259}];
 for(const row of inserted){
  if(board.rows.some(r=>r.rank===row.rank))continue;
  const id=`climb-v7-place-${row.rank}`;board.rows.push({...row,id});
  s.feed.workshopV7!.riders.push({id:`climb-v7-rider-${row.rank}`,name:row.name,entryIds:[],boardRows:[`${s.climbId}:${id}`],commentKeys:[],companionKeys:[]});
 }
 board.rows.sort((a,b)=>a.rank-b.rank);
 board.rows.forEach((r,i)=>metadata.rowDates[r.id]=r.rideId===own.ride.id?own.ride.ride.startedAt:`2016-08-${String(27-i).padStart(2,'0')}`);
 metadata.economy=exampleEconomy(s);s.candidate7=metadata;s.vault=undefined;s.source=metadata.source;
 return parseV7Study(s);
}
export function parseV7Study(input:unknown):ClimbV7Study{
 const s=parseClimbStudy(input) as ClimbV7Study,v=s.candidate7;if(!v)return s;
 const ok=(condition:unknown,message:string)=>{if(!condition)throw Error(message);};
 const finite=(n:unknown)=>typeof n==='number'&&Number.isFinite(n)&&n>=0;
 ok(typeof v.source==='string'&&v.source.length>0&&Array.isArray(v.historyRecordings)&&v.historyRecordings.length<=100,'Include V7 provenance and bound history.');
 ok(v.rowDates&&typeof v.rowDates==='object'&&Object.values(v.rowDates).every(d=>typeof d==='string'&&Number.isFinite(Date.parse(d))),'Invalid leaderboard dates.');
 const data=inspectClimb(s,'rider');
 for(const h of v.historyRecordings){const e=s.feed?.entries.find(e=>e.id===h.entryId),c=e?.ride.climbs.find(c=>c.id===s.climbId),r=data.personal?.rows.find(r=>r.date===h.date);ok(e&&e.owned&&data.viewerRider?.entryIds.includes(e.id)&&c&&(!r||Math.abs(climbResult(e.ride,c).duration-r.duration)<.01)&&e.ride.ride.startedAt.slice(0,10)===h.date.slice(0,10),'History recording must match its date, climb and duration.');}
 const economy=v.economy;
 if(economy){
  ok(economy.climbId===s.climbId&&typeof economy.source==='string'&&economy.source.length>0&&Number.isFinite(Date.parse(economy.asOf))&&finite(economy.lifetimeTributeCal)&&finite(economy.depositedPrincipalCal)&&Array.isArray(economy.weeks)&&economy.weeks.length>0&&economy.weeks.length<=100,'Bind Vault economics to this climb and its source.');
  const ids=new Set<string>();
  for(const w of economy.weeks){ok(typeof w.id==='string'&&!ids.has(w.id)&&[w.start,w.end,w.settledAt].every(d=>Number.isFinite(Date.parse(d)))&&Date.parse(w.start)<Date.parse(w.end)&&Date.parse(w.end)<=Date.parse(w.settledAt)&&Date.parse(w.settledAt)<=Date.parse(economy.asOf)&&allocationKeys.every(k=>finite(w.allocations?.[k])&&finite(w.carry?.[k])),'Invalid settled week.');ids.add(w.id);}
  if(economy.account)ok(s.feed?.workshopV7?.riders.some(r=>r.viewer&&r.id===economy.account!.viewerId)&&finite(economy.account.availableCal),'Bind available CAL to its viewer.');
  if(economy.position)ok(s.feed?.workshopV7?.riders.some(r=>r.viewer&&r.id===economy.position!.viewerId)&&[economy.position.depositedCal,economy.position.readyDung,economy.position.availableCal].every(finite)&&Number.isFinite(Date.parse(economy.position.since)),'Bind the position to its viewer.');
  if(economy.legend)ok(s.feed?.workshopV7?.riders.some(r=>r.id===economy.legend!.riderId&&r.name===economy.legend!.name)&&Number.isInteger(economy.legend.completions)&&economy.legend.completions>0&&Number.isFinite(Date.parse(economy.legend.termEnd)),'Bind the Local Legend to a supplied rider.');
 }
 return s;
}
export const climbV7Studies=climbStudies.map(makeStudy);
// Register explicit V7 recordings before the ride workshop resolves an incoming URL.
for(const s of climbV7Studies)if(s.candidate7&&s.feed)feedImports.set(s.feed.id,s.feed);
export function v7Study(s:ClimbStudy):ClimbV7Study{
 return climbV7Studies.find(v=>v.id===s.id)??s;
}
export function importV7Study(input:unknown,key:string){parseV7Study(input);return parseV7Study(importClimbStudy(input,key));}
export function inspectV7(s:ClimbV7Study,viewer:ClimbViewer){
 const data=inspectClimb(s,viewer);
 if(data.personal&&s.feed&&s.candidate7){
  data.personal.rows=data.personal.rows.map(r=>{const binding=s.candidate7!.historyRecordings.find(h=>h.date===r.date),entry=binding&&s.feed!.entries.find(e=>e.id===binding.entryId);if(!entry)return r;
   const p=new URL(v9RideHref(entry,s.climbId,'analysis',s.feed!.id),'http://local.test').searchParams;p.set('climbOrigin',s.id);p.set('climbOriginViewer',viewer);p.set('viewer',viewer==='rider'&&entry.owned?'owner':'visitor');const href=`/?${p}`;return {...r,href,analysisHref:href};});
 }
 return data;
}
