import { useMemo, type RefObject } from 'react';
import { ArrowLeft, ArrowUpRight } from 'lucide-react';
import { climbSamples, distanceLabel, integer, summarize, type Climb, type Scenario } from './scenario';
import { V12Relief } from './V12Relief';
import { V12Map } from './V12Map';
import { analysisSamples, rangeForClimb } from './v3Model';
import { V12CalAmount } from './V12Economics';
import type { ExampleEconomics } from './v12Example';
import type { V13ClimbContext } from './v13Context';
import { V13Effort, V13History, V13Leaderboard } from './V13ClimbDetails';
import { gradeLabel, selectedAverageGrade } from './v13Grade';
export function V13Vault({scenario,climb,context,owner,economics,pending,onEffort,onReturn,effortHref,focusTarget}:{scenario:Scenario;climb:Climb;context?:V13ClimbContext;owner:boolean;economics:ExampleEconomics|null;pending:boolean;onEffort:()=>void;onReturn:()=>void;effortHref:string;focusTarget:RefObject<HTMLHeadingElement|null>}){
 const points=useMemo(()=>climbSamples(scenario,climb),[scenario,climb]),totals=useMemo(()=>summarize(points),[points]),grade=selectedAverageGrade(points);
 const focus=useMemo(()=>({...rangeForClimb(analysisSamples(scenario.ride.samples),climb)!,kind:'climb' as const}),[scenario,climb]);
 const tribute=economics?.tributes.find(row=>row.climbId===climb.id);
 return <main className="v12-vault-page v13-climb-page" aria-busy={pending}><div className="v12-vault-bar"><button onClick={onReturn}><ArrowLeft size={14}/>Back to ride</button><span>Climb</span></div><header className="v12-vault-identity"><div><p>{scenario.ride.location}</p><h1 ref={focusTarget} tabIndex={-1}>{climb.name}</h1><div className="v12-vault-dimensions"><span>{distanceLabel(totals.distance)} <small>km</small></span>{totals.gain!==null&&<span>{integer(totals.gain)} <small>m elevation</small></span>}{grade!==null&&<span>{gradeLabel(grade)}<small>% avg grade</small></span>}</div></div><V12Relief points={points}/></header><div className="v12-vault-composition"><div><div className="v12-vault-map"><V12Map visible scenario={scenario} focus={focus} cameraKey={`climb:${climb.id}`} scrub={null} onScrub={()=>{}} onLeave={()=>{}} onSelect={()=>{}} onClearSelection={()=>{}}/></div><V13Leaderboard context={context} pending={pending}/><V13History {...{scenario,climb,pending,owner}} onCurrent={onEffort} currentHref={effortHref}/></div><aside className="v12-vault-aside"><section className="v13-climb-recording"><V13Effort {...{scenario,climb,context,pending,owner}}/><a href={effortHref} target="_top" onClick={e=>{if(e.metaKey||e.ctrlKey||e.shiftKey||e.altKey)return;e.preventDefault();onEffort();}}>View this ride<ArrowUpRight size={13}/></a></section>{tribute&&<section className="v12-vault-tribute"><span>Vault</span><V12CalAmount value={tribute.cal} pending={pending}/><p>Tribute from {scenario.ride.title}</p></section>}</aside></div></main>;
}
