import {useEffect,useMemo,useRef,useState} from 'react';
import {Medal} from '../marks/Medal';
import {FeedV2Dialog} from './FeedV2Context';
import {V12Economics} from '../V12Economics';
import {economicsFor,formatFeedCal,type FeedEconomics} from './feedV2Model';
import {v5Collection,personalLabel,placeLabel,type ResultV5} from './feedV5Model';
import {type FeedEntry} from './feedModel';
import type {FeedV13Scenario} from './feedV13Model';
import {useV13Destination} from './FeedV13Navigation';
import {distanceLabel,timeLabel} from '../scenario';

function FeedV13Cal({entry,economics,onNavigate}:{entry:FeedEntry;economics:FeedEconomics;onNavigate:()=>void}){
 const destination=useV13Destination(),href=(id:string)=>destination.href(entry,id,'vault'),content=useRef<HTMLDivElement>(null);
 useEffect(()=>{content.current?.closest('dialog')?.querySelector<HTMLButtonElement>('header button')?.focus({preventScroll:true});},[]);
 return <div ref={content} className="f2-cal-detail"><V12Economics scenario={entry.ride} economics={economics} pending={false} vaultHref={href} onVault={id=>{destination.save();onNavigate();window.parent.postMessage({type:'feed-open-ride',href:href(id)},location.origin);}}/></div>;
}
function Mark({result:r}:{result:ResultV5}){
 return r.leaderboard?<span className="f13-result-mark" aria-hidden="true"><Medal rank={r.leaderboard.rank} size={24}/></span>:r.personalRank&&r.personalRank!==1?<span className="f13-personal-place">{r.personalRank}<small>PB</small></span>:null;
}
function Result({r,entry,detail=false,onClose,onHover,onFocus}:{r:ResultV5;entry:FeedEntry;detail?:boolean;onClose?:()=>void;onHover?:(id:string|null)=>void;onFocus?:(id:string|null)=>void}){
 const destination=useV13Destination(),rideHref=destination.href,openFeedRide=destination.open;
 const personal=personalLabel(r),placement=r.leaderboard?`${placeLabel(r.leaderboard)} on leaderboard`:null;
 return <a className="f13-result" data-achievement={r.achievement} data-detail={detail} href={rideHref(entry,r.climb.id)} target="_top" onClick={e=>openFeedRide(e,rideHref(entry,r.climb.id),onClose)} onMouseEnter={()=>onHover?.(r.climb.id)} onMouseLeave={()=>onHover?.(null)} onFocus={()=>onFocus?.(r.climb.id)} onBlur={()=>onFocus?.(null)}>
  <Mark result={r}/><span className="f13-result-copy"><strong>{r.climb.name}</strong><small>{placement??personal??`${distanceLabel(r.result.distance)} km`}{placement&&personal&&<><span className="f13-dot">·</span><span>{personal}</span></>}{detail&&!placement&&!personal&&r.result.gain!==null&&` · ${Math.round(r.result.gain)} m`}</small></span>
  <span className="f13-result-time"><strong>{timeLabel(r.result.duration)}</strong>{r.newBest&&r.improvement!==null&&<small>{r.improvement}s faster</small>}</span>
 </a>;
}
export function FeedV13Results({entry,scenario,pending,onHover,onFocus}:{entry:FeedEntry;scenario:FeedV13Scenario;pending:boolean;onHover:(id:string|null)=>void;onFocus:(id:string|null)=>void}){
 const c=useMemo(()=>v5Collection(entry,scenario),[entry,scenario]),economics=economicsFor(scenario,entry),[open,setOpen]=useState<'results'|'cal'|null>(null);
 const calTrigger=useRef<HTMLButtonElement>(null),previous=useRef(open);
 useEffect(()=>{if(open==='results'&&previous.current==='cal')calTrigger.current?.focus({preventScroll:true});previous.current=open;},[open]);
 if(!c.results.length&&!economics)return null;
 return <>
  <div className="f13-collection" data-achievement={c.achievementCount>0} data-pending={pending}>
   <div className="f13-result-items">{c.visible.slice(0,1).map(r=><Result key={r.climb.id} r={r} entry={entry} onHover={onHover} onFocus={onFocus}/>)}</div>
   <div className="f13-collection-foot"><button disabled={pending} onClick={()=>setOpen(c.results.length?'results':'cal')}>{c.results.length>1?`All ${c.results.length} climbs`:c.results.length===1?'Climb results':'Ride CAL'}</button></div>
  </div>
  {/* One dialog owns the scroll lock; returning from CAL restores its row after it remounts. */}
  {open!==null&&!pending&&<FeedV2Dialog title={entry.ride.ride.title} onClose={()=>setOpen(open==='cal'&&c.results.length?'results':null)}>{open==='cal'&&economics?<FeedV13Cal entry={entry} economics={economics} onNavigate={()=>setOpen(null)}/>:<div className="f13-results-dialog"><div className="f13-results-summary"><span>Climb results</span><span>{c.results.length} {c.results.length===1?'climb':'climbs'}</span></div>{c.results.map(r=><Result key={r.climb.id} r={r} entry={entry} detail onClose={()=>setOpen(null)}/>)}{economics&&<button ref={calTrigger} className="f13-ride-cal" onClick={()=>setOpen('cal')}><span>Ride CAL</span><strong>{formatFeedCal(economics.riderCal.amount)}<span className="c15-unit"> CAL</span></strong><span className="c15-tag">{economics.riderCal.state==='pending'?'Pending':'Counted'}</span></button>}</div>}</FeedV2Dialog>}
 </>;
}
