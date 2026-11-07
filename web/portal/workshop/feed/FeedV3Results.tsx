import { useState } from 'react';
import { ChevronRight, Medal, Mountain } from 'lucide-react';
import { FeedV2Link, FeedV2Dialog, FeedV2Cal, openFeedRide } from './FeedV2Context';
import { economicsFor, formatFeedCal } from './feedV2Model';
import { climbResult, distanceLabel, timeLabel, type Climb } from '../scenario';
import { rideHref, type FeedEntry } from './feedModel';
import { type FeedV3Scenario } from './feedV3Model';

export function FeedV3Results({entry,scenario,pending,featured,onHover,onFocus}:{entry:FeedEntry;scenario:FeedV3Scenario;pending:boolean;featured?:Climb;onHover:(v:boolean)=>void;onFocus:(v:boolean)=>void}){
  const [open,setOpen]=useState<'results'|'cal'|null>(null), economics=economicsFor(scenario,entry);
  const result=featured ? climbResult(entry.ride,featured):null, best=(result?.improvement??0)>0;
  if(!featured&&!economics) return null;
  return <>
    <div className="f3-results-row"><div className="f3-gifts" data-pending={pending} data-best={best}>
      {featured&&result&&<FeedV2Link className="f3-award" entry={entry} climb={featured.id} onMouseEnter={()=>onHover(true)} onMouseLeave={()=>onHover(false)} onFocus={()=>onFocus(true)} onBlur={()=>onFocus(false)}>
        <span className="f3-award-mark" aria-hidden="true">{best?<Medal size={30} strokeWidth={1.4}/>:<Mountain size={29} strokeWidth={1.3}/>}</span>
        <span className="f3-award-copy"><strong>{featured.name}</strong><small>{best?'New best':`${distanceLabel(result.distance)} km`}{best&&<span> · {Number(result.improvement!.toFixed(2))}s faster</span>}{!best&&result.gain!==null&&` · ${Math.round(result.gain)} m`}</small></span>
        <span className="f3-award-time"><strong>{timeLabel(result.duration)}</strong>{best&&<small>from {timeLabel(result.previousBest!)}</small>}</span><ChevronRight size={13}/>
      </FeedV2Link>}
      {economics&&<button className="f3-gift-cal" disabled={pending} onClick={()=>setOpen('cal')}><span>Ride CAL</span><strong>{formatFeedCal(economics.riderCal.amount)} <small>CAL</small></strong><small>{economics.riderCal.state==='pending'?'Pending':'Counted'}<ChevronRight size={11}/></small></button>}
    </div>
    {entry.ride.climbs.length>1&&<button className="f3-all-results" disabled={pending} onClick={()=>setOpen('results')}>All {entry.ride.climbs.length} climbs <ChevronRight size={12}/></button>}</div>
    {open==='cal'&&economics&&!pending&&<FeedV2Cal entry={entry} economics={economics} onClose={()=>setOpen(null)}/>}
    {open==='results'&&!pending&&<FeedV2Dialog title={entry.ride.ride.title} onClose={()=>setOpen(null)}><div className="f3-dialog-body"><p className="f3-subtle">Climb results</p>{entry.ride.climbs.map(c=>{const r=climbResult(entry.ride,c),improved=(r.improvement??0)>0;return <a className="f3-result-detail" key={c.id} href={rideHref(entry,c.id)} target="_top" onClick={e=>openFeedRide(e,rideHref(entry,c.id),()=>setOpen(null))}><span className="f3-award-mark">{improved?<Medal size={24}/>:<Mountain size={24}/>}</span><span><strong>{c.name}</strong><small>{distanceLabel(r.distance)} km{r.gain!==null&&` · ${Math.round(r.gain)} m`}</small></span><span><strong>{timeLabel(r.duration)}</strong>{improved&&<small>New best · {Number(r.improvement!.toFixed(2))}s faster</small>}</span><ChevronRight size={14}/></a>;})}</div></FeedV2Dialog>}
  </>;
}
