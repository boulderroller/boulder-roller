import {useMemo,useState,type RefObject,type MouseEvent} from 'react';
import {ArrowRight} from 'lucide-react';
import {RankMark} from '../src/components/rankmarks/RankMark';
import {RideV14Shell} from './RideV14Shell';
import {RideV14Map} from './RideV14Map';
import {RideV14Profile} from './RideV14Profile';
import {RideV14Views} from './RideV14Views';
import {RideV14Retained} from './RideV14Retained';
import {RideV14Social} from './RideV14Social';
import {RideV14Context} from './RideV14Context';
import {Unit} from './climb/ClimbV15Hero';
import {ordinal} from './climb/climbV7Model';
import {climbStudies} from './climb/climbModel';
import {rideClimbs,rideFacts,rideFeedHref} from './rideV14Model';
import {useRideV14Navigation,type RideV14Mode} from './rideV14Navigation';
import {v12Economics} from './v12Example';
import {analysisSamples,type SampleRange} from './v3Model';
import {climbResult,distanceLabel,integer,summarize,timeLabel,type Scenario} from './scenario';
import {v13Date} from './V13ClimbDetails';
import type {V13Context} from './v13Context';
import type {PreviewState} from './Preview';
import './climb/climb-v15.css';
import './candidate-v14.css';
function Avatar({scenario}:{scenario:Scenario}){const rider=scenario.ride.rider,[failed,setFailed]=useState(false);if(!rider)return null;return <span className="r14-avatar" aria-hidden="true">{rider.avatarDataUrl&&!failed?<img src={rider.avatarDataUrl} alt="" onError={()=>setFailed(true)}/>:rider.displayName.split(/\s+/).filter(Boolean).map(s=>s[0]).filter((_,i,a)=>i===0||i===a.length-1).join('').toLocaleUpperCase()}</span>;}
export function CandidateV14({scenario,context,owner,bundled,state,recover,focusTarget}:{scenario:Scenario;context?:V13Context;owner:boolean;bundled:boolean;state:PreviewState;recover:()=>void;focusTarget:RefObject<HTMLHeadingElement|null>}){
 const nav=useRideV14Navigation(scenario),{mode,axis}=nav.location,pending=state==='loading',unavailable=state==='empty'||state==='error';
 const [expanded,setExpanded]=useState(false),[cursor,setCursor]=useState<number|null>(null),[draft,setDraft]=useState<SampleRange|null>(null),[menuHost,setMenuHost]=useState<HTMLDivElement|null>(null),[copyHost,setCopyHost]=useState<HTMLDivElement|null>(null);
 const samples=useMemo(()=>analysisSamples(scenario.ride.samples),[scenario]),totals=useMemo(()=>summarize(samples),[samples]);
 const economics=useMemo(()=>owner?context?.economics??v12Economics(scenario,bundled):null,[scenario,context,bundled,owner]);
 const [kudos,setKudos]=useState(false),[comments,setComments]=useState<string[]>([]);
 const feedHref=rideFeedHref(new URLSearchParams(window.parent.location.search));
 const facts=rideFacts(scenario,bundled,economics),rows=rideClimbs(scenario,context,owner,new URLSearchParams(window.parent.location.search),climbStudies,pending);
 const views:{mode:RideV14Mode;label:string}[]=[{mode:'overview',label:'Overview'},{mode:'analysis',label:'Analysis'},...(samples.some(p=>p.power!==null)?[{mode:'power' as const,label:'Power'}]:[]),...(samples.some(p=>p.heartRate!==null)?[{mode:'heartRate' as const,label:'Heart rate'}]:[]),...(economics?[{mode:'economics' as const,label:'CAL'}]:[])];
 const switchView=(next:RideV14Mode)=>{if(next===mode)return;if(mode==='overview')nav.visit({overview:{sourceId:scenario.id,listScroll:0,pageScroll:window.scrollY,climbId:null,desktop:window.matchMedia('(min-width:801px)').matches}},false);setCursor(null);setDraft(null);nav.visit({mode:next,climbId:null,range:null,scroll:next==='overview'?nav.location.overview?.pageScroll??0:0});};
 const openClimb=(id:string)=>{const href=rows.find(r=>r.climb.id===id)?.href;if(href)window.parent.postMessage({type:'workshop-open-climb',href},location.origin);};
 const visitClimb=(e:MouseEvent<HTMLAnchorElement>,id:string)=>{if(e.button||e.metaKey||e.ctrlKey||e.shiftKey||e.altKey)return;e.preventDefault();openClimb(id);};
 const inspected=cursor===null?null:samples[cursor],subject={startIndex:0,endIndex:samples.length-1};
 const bone=<span className="c15-bone c15-bone-wide" aria-hidden="true" style={{width:96}}/>;
 const bests=scenario.climbs.filter(c=>(climbResult(scenario,c).improvement??0)>0);
 return <div className="c15-page r14-page" data-state={state} data-viewer={owner?'owner':'visitor'} data-mode={mode}>
  <RideV14Shell name={unavailable?undefined:scenario.ride.title} exploreHref={null} feedHref={feedHref} account={scenario.ride.rider&&<span className="c15-account"><Avatar scenario={scenario}/><span>{scenario.ride.rider.displayName}</span></span>} climbs={unavailable?[]:rows.map(r=>({climbId:r.climb.id,name:r.climb.name,number:r.number,href:r.href,rank:r.railRank}))} views={unavailable?[]:views} mode={mode} onView={switchView} social={!unavailable&&<RideV14Social ride={scenario.ride} kudos={kudos} onKudos={setKudos} comments={comments} onComments={setComments}/>} options={owner&&!unavailable&&<div className="r14-options" ref={setMenuHost}/>}>
   <RideV14Context copyHost={copyHost} menuHost={menuHost} visible={mode==='overview'&&!unavailable} bundled={bundled} group={scenario.source.history==='illustrative'} owner={owner}/>
   <main className="c15-sheet" aria-busy={pending}>
    {unavailable?<section className="c15-card r14-unavailable" role={state==='error'?'alert':'status'}><h1>{state==='empty'?'No ride selected':'Ride unavailable'}</h1><p>{state==='empty'?'Choose a ride to see its route and climbs.':'The ride could not be loaded.'}</p><button className="c15-button" onClick={recover}>{state==='empty'?'Open ride':'Try again'}</button></section>:mode!=='overview'?<RideV14Retained><RideV14Views scenario={scenario} context={context} owner={owner} bundled={bundled} nav={nav} pending={pending} focusTarget={focusTarget}/></RideV14Retained>:<>
     <section className="c15-hero" data-hero="a" data-expanded={expanded} aria-label="Ride"><div className="c15-hero-art">
      <RideV14Map scenario={scenario} cursor={pending?null:cursor} onCursor={pending?()=>{}:setCursor} onClimb={openClimb} linked={rows.filter(r=>r.href).map(r=>r.climb.id)} expanded={expanded} onExpand={()=>setExpanded(!expanded)}/>
      <div className="c15-hero-scrim" aria-hidden="true"/><header className="c15-hero-copy"><div className="c15-hero-title"><p className="c15-kicker r14-kicker">{scenario.ride.rider&&<><Avatar scenario={scenario}/><span>{scenario.ride.rider.displayName}</span><span>·</span></>}<span><time dateTime={scenario.ride.startedAt}>{v13Date(scenario.ride.startedAt)}</time> · {scenario.ride.location}</span></p><h1 ref={focusTarget} tabIndex={-1} data-long={scenario.ride.title.length>24}>{scenario.ride.title}</h1>{bests.length>0&&<button className="r14-bests" onClick={()=>openClimb(bests[0].id)}>{pending?bone:`${bests.length} new ${bests.length===1?'best':'bests'}`}</button>}<div ref={setCopyHost}/></div>
       <dl className="c15-hero-stats"><div><dt>Distance</dt><dd>{pending?bone:<>{distanceLabel(totals.distance)}<Unit>km</Unit></>}</dd></div><div><dt>Elapsed time</dt><dd>{pending?bone:timeLabel(totals.duration)}</dd></div>{totals.gain!==null&&<div><dt>Elevation</dt><dd>{pending?bone:<>{integer(totals.gain)}<Unit>m</Unit></>}</dd></div>}</dl>
      </header></div></section>
     <div className="c15-first r14-first" data-hero="a">
      <section className="c15-card c15-elevation" aria-label="Ride elevation"><div className="c15-elevation-head"><span className="c15-kicker">Elevation</span><span className="c15-readout-line" aria-live="polite">{inspected&&<>{(inspected.d/1000).toFixed(2)}<Unit>km</Unit>{inspected.elevation!==null&&<> · {Math.round(inspected.elevation)}<Unit>m</Unit></>}{axis==='time'&&<> · {timeLabel(inspected.t)}</>}</>}</span><div className="c15-segmented" role="group" aria-label="Horizontal axis">{(['distance','time'] as const).map(a=><button key={a} aria-pressed={axis===a} onClick={()=>{setCursor(null);nav.visit({axis:a},false);}}>{a==='distance'?'Distance':'Time'}</button>)}</div></div>
       {pending?<div className="r14-profile-loading">{bone}</div>:samples.length>1&&samples.some(p=>p.elevation!==null)?<RideV14Profile samples={samples} climbs={scenario.climbs} subject={subject} selection={null} draft={draft} axis={axis} cursor={cursor} onHover={setCursor} onDraft={setDraft} onSelect={range=>nav.visit({mode:'analysis',climbId:null,range,scroll:0})} onClearSelection={()=>{setCursor(null);setDraft(null);}}/>:null}
      </section>
      <section className="c15-card c15-standing r14-facts" data-odd={facts.length%2===1} aria-label="Ride facts">{facts.map(f=><dl className="c15-stat" key={f.label}><dt>{f.label}</dt><dd className="c15-stat-value">{pending?bone:<>{f.label==='Ride CAL'?<button onClick={()=>switchView('economics')}>{f.value}{f.unit&&<Unit>{f.unit}</Unit>}</button>:<>{f.value}{f.unit&&<Unit>{f.unit}</Unit>}</>}</>}</dd>{f.state&&<dd className="c15-basis">{pending?bone:f.state}</dd>}</dl>)}</section>
     </div>
     {rows.length>0&&<section className="c15-section r14-climbs"><div className="c15-section-head"><h2>Climbs on this ride</h2><span className="c15-rule"/>{!pending&&<span>{rows.length}</span>}</div><div className="c15-card r14-board">{rows.map(r=>{const result=climbResult(scenario,r.climb),content=<><span className="r14-pin">{r.number}</span><span className="r14-climb-copy"><strong>{r.climb.name}</strong><span>{distanceLabel(result.distance)} km{result.gain!==null&&<> · {integer(result.gain)} m</>}{result.grade!==null&&<> · {result.grade.toFixed(1)}%</>}</span></span>{(r.rank||pending&&context?.climbs.find(c=>c.climbId===r.climb.id)?.resultRank||(result.improvement??0)>0)&&<span className="r14-result-basis">{!pending&&r.rank&&r.rank<=10&&<RankMark rank={r.rank} size={24}/>}<span>{pending?bone:<>{r.rank&&<>{ordinal(r.rank)} on leaderboard · this ride</>}{(result.improvement??0)>0&&<>{r.rank&&' · '}New best</>}</>}</span></span>}<span className="r14-result-time"><strong>{pending?bone:timeLabel(result.duration)}</strong>{result.power!==null&&<span>{pending?bone:<>{integer(result.power)}<Unit>W</Unit></>}</span>}</span></>;return r.href?<a className="r14-result-row" key={r.climb.id} href={r.href} target="_top" onClick={e=>visitClimb(e,r.climb.id)}>{content}</a>:<div className="r14-result-row" key={r.climb.id}>{content}</div>;})}</div></section>}
     <a className="c15-card r14-analyze" href={nav.href({mode:'analysis',climbId:null,range:null})} target="_top" onClick={e=>{if(e.button||e.metaKey||e.ctrlKey||e.shiftKey||e.altKey)return;e.preventDefault();switchView('analysis');}}><span>Analyze ride<small>Inspect your recorded measurements</small></span><ArrowRight/></a>
    </>}
   </main>
  </RideV14Shell>
 </div>;
}
