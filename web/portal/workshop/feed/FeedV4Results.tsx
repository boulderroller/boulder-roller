import {useMemo,useState} from 'react';
import {ChevronRight,Medal,Mountain} from 'lucide-react';
import {FeedV2Dialog,FeedV2Cal,openFeedRide} from './FeedV2Context';
import {economicsFor,formatFeedCal} from './feedV2Model';
import {achievementCollection,type FeedAchievement,type FeedV4Scenario} from './feedV4Model';
import {rideHref,type FeedEntry} from './feedModel';
import {distanceLabel,timeLabel} from '../scenario';

const improvement=(r:FeedAchievement)=>`${Number(r.result.improvement!.toFixed(2))}s faster`;
export function FeedV4Results({entry,scenario,pending,onHover,onFocus}:{entry:FeedEntry;scenario:FeedV4Scenario;pending:boolean;onHover:(id:string|null)=>void;onFocus:(id:string|null)=>void}){
 const collection=useMemo(()=>achievementCollection(entry),[entry]),economics=economicsFor(scenario,entry),[open,setOpen]=useState<'results'|'cal'|null>(null);
 const count=collection.bests.length;
 if(!collection.results.length&&!economics)return null;
 const title=count?`${count>1?count+' ':''}${count===1?'New best':'new bests'}`:'Climb result';
 return <>
  <div className="f4-collection" data-multiple={collection.visible.length>1} data-pending={pending}>
   {collection.results.length>0&&<div className="f4-results">
    <div className="f4-collection-heading"><span>{count?<Medal size={17} strokeWidth={1.5}/>:<Mountain size={17} strokeWidth={1.5}/>}<strong>{title}</strong></span>{collection.results.length>1&&<button disabled={pending} onClick={()=>setOpen('results')}>All {collection.results.length} climbs <ChevronRight size={12}/></button>}</div>
    <div className="f4-result-items">{collection.visible.map(r=><a key={r.climb.id} className="f4-result-item" href={rideHref(entry,r.climb.id)} target="_top" onClick={e=>openFeedRide(e,rideHref(entry,r.climb.id))} onMouseEnter={()=>onHover(r.climb.id)} onMouseLeave={()=>onHover(null)} onFocus={()=>onFocus(r.climb.id)} onBlur={()=>onFocus(null)}>
     <strong className="f4-result-name">{r.climb.name}</strong><span className="f4-result-reading"><strong>{timeLabel(r.result.duration)}</strong>{r.result.improvement!==null&&r.result.improvement>0?<span>{improvement(r)}<small>from {timeLabel(r.result.previousBest!)}</small></span>:<span>{distanceLabel(r.result.distance)} km{r.result.gain!==null&&<small>{Math.round(r.result.gain)} m elevation</small>}</span>}<ChevronRight size={12}/></span>
    </a>)}</div>
   </div>}
   {economics&&<button className="f4-ride-cal" disabled={pending} onClick={()=>setOpen('cal')}><span>Ride CAL</span><strong>{formatFeedCal(economics.riderCal.amount)}<small>CAL</small></strong><span>{economics.riderCal.state==='pending'?'Pending':'Counted'}<ChevronRight size={11}/></span></button>}
  </div>
  {open==='cal'&&economics&&!pending&&<FeedV2Cal entry={entry} economics={economics} onClose={()=>setOpen(null)}/>}
  {open==='results'&&!pending&&<FeedV2Dialog title={entry.ride.ride.title} onClose={()=>setOpen(null)}><div className="f4-results-dialog"><div className="f4-results-summary"><span>{count>0?`${count} ${count===1?'new best':'new bests'}`:'Climb results'}</span><span>{collection.results.length} climbs</span></div>{collection.results.map(r=><a key={r.climb.id} className="f4-detail-result" href={rideHref(entry,r.climb.id)} target="_top" onClick={e=>openFeedRide(e,rideHref(entry,r.climb.id),()=>setOpen(null))}><span className="f4-detail-mark" aria-hidden="true">{(r.result.improvement??0)>0?<Medal size={25} strokeWidth={1.5}/>:<Mountain size={24} strokeWidth={1.5}/>}</span><span className="f4-detail-name"><strong>{r.climb.name}</strong><small>{distanceLabel(r.result.distance)} km{r.result.gain!==null&&` · ${Math.round(r.result.gain)} m`}</small></span><span className="f4-detail-time"><strong>{timeLabel(r.result.duration)}</strong>{(r.result.improvement??0)>0&&<small>{improvement(r)}</small>}</span><ChevronRight size={13}/></a>)}</div></FeedV2Dialog>}
 </>;
}
