import {useMemo,useState} from 'react';
import {ChevronRight,Medal,Mountain} from 'lucide-react';
import {RankMark} from '../../src/components/rankmarks/RankMark';
import {FeedV2Dialog} from './FeedV2Context';
import {V12Economics} from '../V12Economics';
import {economicsFor,formatFeedCal,type FeedEconomics} from './feedV2Model';
import {v5Collection,personalLabel,placeLabel,type ResultV5} from './feedV5Model';
import {type FeedEntry} from './feedModel';
import type {FeedV9Scenario} from './feedV9Model';
import {useV9Destination} from './FeedV9Navigation';
import {distanceLabel,timeLabel} from '../scenario';

function FeedV9Cal({entry,economics,onClose}:{entry:FeedEntry;economics:FeedEconomics;onClose:()=>void}){
 const destination=useV9Destination(),href=(id:string)=>destination.href(entry,id,'vault');
 return <FeedV2Dialog title={entry.ride.ride.title} onClose={onClose}><div className="f2-cal-detail"><V12Economics scenario={entry.ride} economics={economics} pending={false} vaultHref={href} onVault={id=>{destination.save();onClose();window.parent.postMessage({type:'feed-open-ride',href:href(id)},location.origin);}}/></div></FeedV2Dialog>;
}
function Mark({result:r}:{result:ResultV5}){
 return <span className="f5-result-mark" aria-hidden="true">{r.leaderboard?<RankMark rank={r.leaderboard.rank} size={54}/>:r.personalRank===1?<Medal size={29} strokeWidth={1.3}/>:r.personalRank?<span className="f5-personal-place">{r.personalRank}<small>PB</small></span>:<Mountain size={22} strokeWidth={1.3}/>}</span>;
}
function Result({r,entry,detail=false,onClose,onHover,onFocus}:{r:ResultV5;entry:FeedEntry;detail?:boolean;onClose?:()=>void;onHover?:(id:string|null)=>void;onFocus?:(id:string|null)=>void}){
 const destination=useV9Destination(),rideHref=destination.href,openFeedRide=destination.open;
 const personal=personalLabel(r),placement=r.leaderboard?`${placeLabel(r.leaderboard)} on leaderboard`:null;
 return <a className="f5-result" data-achievement={r.achievement} data-detail={detail} href={rideHref(entry,r.climb.id)} target="_top" onClick={e=>openFeedRide(e,rideHref(entry,r.climb.id),onClose)} onMouseEnter={()=>onHover?.(r.climb.id)} onMouseLeave={()=>onHover?.(null)} onFocus={()=>onFocus?.(r.climb.id)} onBlur={()=>onFocus?.(null)}>
  <Mark result={r}/><span className="f5-result-copy"><strong>{r.climb.name}</strong><small>{placement??personal??`${distanceLabel(r.result.distance)} km`}{placement&&personal&&<><span className="f5-dot">·</span><span>{personal}</span></>}{detail&&!placement&&!personal&&r.result.gain!==null&&` · ${Math.round(r.result.gain)} m`}</small></span>
  <span className="f5-result-time"><strong>{timeLabel(r.result.duration)}</strong>{r.newBest&&r.improvement!==null&&<small>{r.improvement}s faster</small>}</span><ChevronRight size={12}/>
 </a>;
}
export function FeedV9Results({entry,scenario,pending,onHover,onFocus}:{entry:FeedEntry;scenario:FeedV9Scenario;pending:boolean;onHover:(id:string|null)=>void;onFocus:(id:string|null)=>void}){
 const c=useMemo(()=>v5Collection(entry,scenario),[entry,scenario]),economics=economicsFor(scenario,entry),[open,setOpen]=useState<'results'|'cal'|null>(null);
 if(!c.results.length&&!economics)return null;
 return <>
  <div className="f5-collection" data-multiple={c.visible.length>1} data-achievement={c.achievementCount>0} data-pending={pending}>
   <div className="f5-result-items">{c.visible.map(r=><Result key={r.climb.id} r={r} entry={entry} onHover={onHover} onFocus={onFocus}/>)}</div>
   {(c.results.length>1||economics)&&<div className="f5-collection-foot">{c.results.length>1&&<button disabled={pending} onClick={()=>setOpen('results')}>All {c.results.length} climbs <ChevronRight size={12}/></button>}{economics&&<button className="f5-ride-cal" disabled={pending} onClick={()=>setOpen('cal')}><span>Ride CAL</span><strong>{formatFeedCal(economics.riderCal.amount)}<small>CAL</small></strong><span>{economics.riderCal.state==='pending'?'Pending':'Counted'}</span><ChevronRight size={12}/></button>}</div>}
  </div>
  {open==='cal'&&economics&&!pending&&<FeedV9Cal entry={entry} economics={economics} onClose={()=>setOpen(null)}/>}
  {open==='results'&&!pending&&<FeedV2Dialog title={entry.ride.ride.title} onClose={()=>setOpen(null)}><div className="f5-results-dialog"><div className="f5-results-summary"><span>Climb results</span><span>{c.results.length} climbs</span></div>{c.results.map(r=><Result key={r.climb.id} r={r} entry={entry} detail onClose={()=>setOpen(null)}/>)}</div></FeedV2Dialog>}
 </>;
}
