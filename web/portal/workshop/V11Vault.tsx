import { useMemo, type RefObject } from 'react';
import { ArrowLeft, ArrowUpRight } from 'lucide-react';
import { climbResult, distanceLabel, integer, timeLabel, type Climb, type Scenario } from './scenario';
import { V11Relief } from './V11Relief';
import { V11Map } from './V11Map';
import { analysisSamples, rangeForClimb } from './v3Model';
import { V11CalAmount } from './V11Economics';
import type { ExampleEconomics } from './v11Example';

const date=(value:string)=>new Date(value).toLocaleDateString('en-US',{month:'short',day:'numeric',year:'numeric',timeZone:'America/New_York'});
export function V11Vault({scenario,climb,economics,pending,onEffort,onReturn,effortHref,focusTarget}:{scenario:Scenario;climb:Climb;economics:ExampleEconomics|null;pending:boolean;onEffort:()=>void;onReturn:()=>void;effortHref:string;focusTarget:RefObject<HTMLHeadingElement|null>}) {
 const result=useMemo(()=>climbResult(scenario,climb),[scenario,climb]);
 const points=useMemo(()=>scenario.ride.samples.filter(p=>p.t>=climb.start&&p.t<=climb.end),[scenario,climb]);
 const focus=useMemo(()=>({...rangeForClimb(analysisSamples(scenario.ride.samples),climb)!,kind:'climb' as const}),[scenario,climb]);
 const tribute=economics?.tributes.find(t=>t.climbId===climb.id);
 const history=[...climb.history].sort((a,b)=>Date.parse(b.date)-Date.parse(a.date));
 const fastest=Math.min(result.duration,...history.map(h=>h.duration)),slowest=Math.max(result.duration,...history.map(h=>h.duration));
 return <div className="v11-vault-page" aria-busy={pending}>
  <div className="v11-vault-bar"><button onClick={onReturn}><ArrowLeft size={14}/>Back to ride</button><span>Climb · Vault</span></div>
  <header className="v11-vault-identity"><div><p>{scenario.ride.location}</p><h1 ref={focusTarget} tabIndex={-1}>{climb.name}</h1><div className="v11-vault-dimensions"><span>{distanceLabel(result.distance)} <small>km</small></span>{result.gain!==null&&<span>{integer(result.gain)} <small>m elevation</small></span>}{result.grade!==null&&<span>{result.grade.toFixed(1)}<small>%</small></span>}</div></div><V11Relief points={points}/></header>
  <div className="v11-vault-composition"><div><div className="v11-vault-map"><V11Map visible scenario={scenario} focus={focus} cameraKey={`vault:${climb.id}`} scrub={null} onScrub={()=>{}} onLeave={()=>{}} onSelect={()=>{}} onClearSelection={()=>{}}/></div><section className="v11-vault-efforts"><header><h2>Your efforts</h2><span>{scenario.ride.rider?.displayName??'This recording'}</span></header>
   <a className="v11-vault-effort is-current" href={effortHref} target="_top" onClick={e=>{if(e.metaKey||e.ctrlKey||e.shiftKey||e.altKey)return;e.preventDefault();onEffort();}}><span><strong>{date(scenario.ride.startedAt)}</strong><small>{scenario.ride.title}</small></span><span className="v11-effort-bar" aria-hidden="true" data-pending={pending||undefined}><i style={{width:`${result.duration/slowest*100}%`}}/></span><strong className="v11-value" data-pending={pending||undefined}><span aria-hidden={pending||undefined}>{timeLabel(result.duration)}</span></strong><ArrowUpRight size={15}/></a>
   {history.map((h,i)=><div className="v11-vault-effort" key={`${h.date}:${i}`}><span><strong>{date(h.date)}</strong></span><span className="v11-effort-bar" aria-hidden="true" data-pending={pending||undefined}><i style={{width:`${h.duration/slowest*100}%`}}/></span><strong className="v11-value" data-pending={pending||undefined}><span aria-hidden={pending||undefined}>{timeLabel(h.duration)}</span></strong><span/></div>)}
  </section></div><aside className="v11-vault-aside"><section><span>Your best</span><strong className="v11-vault-best v11-value" data-pending={pending||undefined}><span aria-hidden={pending||undefined}>{timeLabel(fastest)}</span></strong><p>{pending?'—':fastest===result.duration?'This ride':date(history.find(h=>h.duration===fastest)!.date)}</p><a href={effortHref} target="_top" onClick={e=>{if(e.metaKey||e.ctrlKey||e.shiftKey||e.altKey)return;e.preventDefault();onEffort();}}>View this ride<ArrowUpRight size={13}/></a></section>{tribute&&<section className="v11-vault-tribute"><span>Tribute from this ride</span><V11CalAmount value={tribute.cal} pending={pending}/><p>{scenario.ride.title}</p></section>}</aside></div>
 </div>;
}
