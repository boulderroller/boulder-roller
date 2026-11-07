import { useMemo, useState, type Ref } from 'react';
import { ArrowRight, BarChart3, X } from 'lucide-react';
import { V12Map } from './V12Map';
import { V13EffortProfile } from './V13EffortProfile';
import { V13Effort, V13History, V13Leaderboard } from './V13ClimbDetails';
import { analysisSamples, rangeForClimb } from './v3Model';
import { climbSamples, distanceLabel, summarize, type Climb, type Scenario } from './scenario';
import { gradeLabel, selectedAverageGrade } from './v13Grade';
import type { V13ClimbContext } from './v13Context';
export function V13ExpandedResult({sectionRef,scenario,climb,context,owner,pending,onClose,onAnalyze,onClimb,climbHref,analyzeHref}:{sectionRef:Ref<HTMLElement|null>;scenario:Scenario;climb:Climb;context?:V13ClimbContext;owner:boolean;pending:boolean;onClose:()=>void;onAnalyze:()=>void;onClimb:()=>void;climbHref:string;analyzeHref:string}){
 const [cursor,setCursor]=useState<number|null>(null);
 const points=useMemo(()=>climbSamples(scenario,climb),[scenario,climb]),totals=useMemo(()=>summarize(points),[points]);
 const samples=useMemo(()=>analysisSamples(scenario.ride.samples),[scenario]),range=useMemo(()=>rangeForClimb(samples,climb)!,[samples,climb]);
 const grade=selectedAverageGrade(points);
 return <section ref={sectionRef} tabIndex={-1} className="v13-expanded-result" aria-label={`${climb.name} result`} aria-busy={pending}>
  <header className="v13-expanded-heading"><div><span>Climb result</span><h2><a href={climbHref} target="_top" onClick={e=>{if(e.metaKey||e.ctrlKey||e.shiftKey||e.altKey)return;e.preventDefault();onClimb();}}>{climb.name}<ArrowRight size={16}/></a></h2><p>{distanceLabel(totals.distance)} km{totals.gain!==null&&<> · {Math.round(totals.gain)} m elevation</>}{grade!==null&&<> · {gradeLabel(grade)}% avg grade</>}</p></div><button className="v13-close-result" aria-label={`Close ${climb.name} result`} onClick={onClose}><X size={18}/></button></header>
  <div className="v13-expanded-top"><div className="v13-expanded-terrain"><div className="v13-expanded-map"><V12Map visible scenario={scenario} focus={{...range,kind:'climb'}} cameraKey={`result:${climb.id}`} scrub={cursor} onScrub={setCursor} onLeave={()=>setCursor(null)} onSelect={()=>{}} onClearSelection={()=>setCursor(null)}/></div><V13EffortProfile points={samples.slice(range.startIndex,range.endIndex+1)} cursor={cursor} onCursor={setCursor}/></div><aside className="v13-expanded-aside"><V13Effort {...{scenario,climb,context,pending,owner}}/><a className="v13-analyze-effort" href={analyzeHref} target="_top" onClick={e=>{if(e.metaKey||e.ctrlKey||e.shiftKey||e.altKey)return;e.preventDefault();onAnalyze();}}><BarChart3 size={15}/><span>Analyze effort</span><ArrowRight size={14}/></a></aside></div>
  <div className="v13-expanded-record"><V13History {...{scenario,climb,pending,owner}}/><V13Leaderboard {...{context,pending}} compact/></div>
 </section>;
}
