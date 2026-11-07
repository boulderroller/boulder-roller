import type { MouseEvent } from 'react';
import { ArrowUpRight, Trophy } from 'lucide-react';
import { RankMark } from '../src/components/rankmarks/RankMark';
import { climbResult, timeLabel, type Climb, type Scenario } from './scenario';
import type { V13ClimbContext } from './v13Context';

export const v13Date=(value:string)=>new Date(value).toLocaleDateString('en-US',{month:'short',day:'numeric',year:'numeric',timeZone:'America/New_York'});
export function v13OpenRide(event:MouseEvent<HTMLAnchorElement>,href:string){
 if(event.button||event.metaKey||event.ctrlKey||event.shiftKey||event.altKey)return;
 event.preventDefault();window.parent.postMessage({type:'feed-open-ride',href},location.origin);
}
export function V13Leaderboard({context,pending,compact=false}:{context?:V13ClimbContext;pending:boolean;compact?:boolean}){
 if(!context?.leaderboard.length)return null;
 const all=context.leaderboard;
 const rows=compact&&all.length>5?[...all.slice(0,3),...all.filter(row=>row.isCurrentRider&&!all.slice(0,3).includes(row))].sort((a,b)=>a.rank-b.rank):all;
 return <section className="v13-leaderboard" aria-label="Current leaderboard"><header><h3>Current leaderboard</h3>{context.leaderboardAsOf&&<time dateTime={context.leaderboardAsOf}>{v13Date(context.leaderboardAsOf)}</time>}</header><ol>{rows.map(row=>{
  const contents=<><span className="v13-leaderboard-rank">{row.rank<=10?<RankMark rank={row.rank} size={36}/>:<span>{row.rank}</span>}</span><span className="v13-leaderboard-rider"><strong>{row.name}</strong>{row.date&&<small>{v13Date(row.date)}</small>}</span><strong className="v13-leaderboard-time v12-value" data-pending={pending||undefined}><span aria-hidden={pending||undefined}>{timeLabel(row.duration)}</span></strong><span className="v13-leaderboard-link">{row.href&&<ArrowUpRight size={13}/>}</span></>;
  return <li key={row.id} data-current={row.isCurrentRider||undefined}>{row.href?<a aria-label={`${row.name}, place ${row.rank}, ${timeLabel(row.duration)}, open ride`} href={row.href} target="_top" onClick={e=>v13OpenRide(e,row.href!)}>{contents}</a>:<div>{contents}</div>}</li>;
 })}</ol></section>;
}
export function V13History({scenario,climb,pending,owner,onCurrent,currentHref}:{scenario:Scenario;climb:Climb;pending:boolean;owner:boolean;onCurrent?:()=>void;currentHref?:string}){
 const result=climbResult(scenario,climb),history=[...climb.history].sort((a,b)=>Date.parse(b.date)-Date.parse(a.date));
 const slowest=Math.max(result.duration,...history.map(row=>row.duration));
 const current=<><span><strong>{v13Date(scenario.ride.startedAt)}</strong><small>This ride</small></span><span className="v12-effort-bar" aria-hidden="true" data-pending={pending||undefined}><i style={{width:`${result.duration/slowest*100}%`}}/></span><strong className="v12-value" data-pending={pending||undefined}><span aria-hidden={pending||undefined}>{timeLabel(result.duration)}</span></strong>{onCurrent?<ArrowUpRight size={13}/>:<span/>}</>;
 return <section className="v13-history"><header><h3>{owner?'Your efforts':`${scenario.ride.rider?.displayName??'Rider'}’s efforts`}</h3><span>{history.length+1} {history.length===0?'ride':'rides'}</span></header><div className="v13-history-list">{onCurrent&&currentHref?<a className="v12-vault-effort is-current" href={currentHref} target="_top" onClick={e=>{if(e.metaKey||e.ctrlKey||e.shiftKey||e.altKey)return;e.preventDefault();onCurrent();}}>{current}</a>:<div className="v12-vault-effort is-current">{current}</div>}{history.map((row,index)=><div className="v12-vault-effort" key={`${row.date}:${index}`}><span><strong>{v13Date(row.date)}</strong></span><span className="v12-effort-bar" aria-hidden="true" data-pending={pending||undefined}><i style={{width:`${row.duration/slowest*100}%`}}/></span><strong className="v12-value" data-pending={pending||undefined}><span aria-hidden={pending||undefined}>{timeLabel(row.duration)}</span></strong><span/></div>)}</div></section>;
}
export function V13Effort({scenario,climb,context,pending,owner}:{scenario:Scenario;climb:Climb;context?:V13ClimbContext;pending:boolean;owner:boolean}){
 const result=climbResult(scenario,climb),best=Math.min(result.duration,...climb.history.map(row=>row.duration));
 const improved=result.improvement!==null&&result.improvement>0;
 return <div className="v13-effort"><div className="v13-effort-identity">{context?.resultRank&&context.resultRank<=10&&<RankMark rank={context.resultRank} size={60}/>}<div><span>{owner?'Your result':scenario.ride.rider?.displayName??'This ride'}</span><strong className="v12-value" data-pending={pending||undefined}><span aria-hidden={pending||undefined}>{timeLabel(result.duration)}</span></strong>{context?.resultRank&&<small>{context.resultRank}{context.resultRank%100>=11&&context.resultRank%100<=13?'th':context.resultRank%10===1?'st':context.resultRank%10===2?'nd':context.resultRank%10===3?'rd':'th'} on leaderboard · this ride</small>}</div></div>{improved&&<p className="v13-effort-best"><Trophy size={13}/><strong>New best</strong><span className="v12-value" data-pending={pending||undefined}><span aria-hidden={pending||undefined}>{timeLabel(result.improvement!)} faster</span></span></p>}<dl className="v13-effort-facts">{result.power!==null&&<div><dt>Avg power</dt><dd className="v12-value" data-pending={pending||undefined}><span aria-hidden={pending||undefined}>{Math.round(result.power)} <small>W</small></span></dd></div>}{climb.history.length>0&&<div><dt>{owner?'Your best':'Personal best'}</dt><dd className="v12-value" data-pending={pending||undefined}><span aria-hidden={pending||undefined}>{timeLabel(best)}</span></dd></div>}</dl></div>;
}
