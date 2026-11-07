import type { Scenario } from './scenario';
import type {ExampleEconomics} from './v12Example';

export type V13LeaderboardRow={id:string;name:string;rank:number;duration:number;isCurrentRider?:boolean;date?:string;href?:string};
export type V13ClimbContext={climbId:string;resultRank?:number;leaderboardAsOf?:string;leaderboard:V13LeaderboardRow[]};
export type V13Context={source:'provided'|'illustrative';economics?:ExampleEconomics;climbs:V13ClimbContext[]};
const object=(value:unknown):value is Record<string,unknown>=>!!value&&typeof value==='object'&&!Array.isArray(value);
const text=(value:unknown)=>typeof value==='string'&&value.trim().length>0&&value.length<=600;
const rank=(value:unknown):value is number=>typeof value==='number'&&Number.isInteger(value)&&value>0&&value<=1000000;
const date=(value:unknown):value is string=>typeof value==='string'&&Number.isFinite(Date.parse(value));
/** Context is separate from recording data; absent leaderboard truth stays absent. */
export function parseV13Context(input:unknown,scenario:Scenario):V13Context|undefined {
 if(!object(input)||!['provided','illustrative'].includes(String(input.source))||!Array.isArray(input.climbs))return undefined;
 const climbs:V13ClimbContext[]=[];
 for(const value of input.climbs){
  if(!object(value)||typeof value.climbId!=='string'||!scenario.climbs.some(c=>c.id===value.climbId)||climbs.some(c=>c.climbId===value.climbId)||!Array.isArray(value.leaderboard))continue;
  const leaderboard:V13LeaderboardRow[]=[];
  for(const row of value.leaderboard){
   if(!object(row)||!text(row.id)||!text(row.name)||!rank(row.rank)||typeof row.duration!=='number'||!Number.isFinite(row.duration)||row.duration<=0||leaderboard.some(r=>r.id===row.id))continue;
   // Same-workshop destinations only. Unlinked history never gets a fabricated ride.
   const href=typeof row.href==='string'&&/^\/\?(?!.*[\r\n])/.test(row.href)&&row.href.length<=2000?row.href:undefined;
   leaderboard.push({id:row.id as string,name:row.name as string,rank:row.rank,duration:row.duration,...(row.isCurrentRider===true?{isCurrentRider:true}:{}),...(date(row.date)?{date:row.date}:{}),...(href?{href}:{})});
  }
  climbs.push({climbId:value.climbId,...(rank(value.resultRank)?{resultRank:value.resultRank}:{}),...(date(value.leaderboardAsOf)?{leaderboardAsOf:value.leaderboardAsOf}:{}),leaderboard:leaderboard.sort((a,b)=>a.rank-b.rank)});
 }
 const supplied=input.economics;
 const cal=(value:unknown)=>object(value)&&typeof value.amount==='number'&&Number.isFinite(value.amount)&&value.amount>=0&&['pending','counted'].includes(String(value.state));
 const economics=object(supplied)&&supplied.source==='illustrative'&&cal(supplied.riderCal)&&Array.isArray(supplied.tributes)&&supplied.tributes.every(t=>object(t)&&cal(t.cal)&&scenario.climbs.some(c=>c.id===t.climbId))?supplied as ExampleEconomics:undefined;
 return {source:input.source as V13Context['source'],climbs,...(economics?{economics}: {})};
}
