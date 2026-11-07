import {useRef,useState,type KeyboardEvent} from 'react';
import {type HistoryRide} from './profileV5Model';

const dateLabel=(date:string)=>new Intl.DateTimeFormat('en-US',{month:'short',day:'numeric',timeZone:'UTC'}).format(new Date(date));
const duration=(seconds:number)=>`${Math.floor(seconds/3600)}h ${Math.floor(seconds%3600/60)}m`;
type Day={date:string;rides:HistoryRide[]};
type Props={days:Day[];summary:{count:number;distance:number;climbing:number;time:number};selectedDay:string|null;onSelect:(date:string|null)=>void};

export function RidingRhythm({days,summary,selectedDay,onSelect}:Props){
 const [peek,setPeek]=useState<string|null>(null),[focusIndex,setFocusIndex]=useState(0),buttons=useRef<(HTMLButtonElement|null)[]>([]);
 const inspected=days.find(d=>d.date===(peek??selectedDay));
 const total=(rides:HistoryRide[])=>rides.reduce((s,r)=>({distance:s.distance+r.distanceM,time:s.time+r.durationS}),{distance:0,time:0});
 const inspection=inspected?total(inspected.rides):null;
 const key=(e:KeyboardEvent<HTMLButtonElement>,i:number)=>{
  if(e.key==='Escape'){e.preventDefault();setPeek(null);onSelect(null);return;}
  const next=e.key==='ArrowRight'?Math.min(days.length-1,i+1):e.key==='ArrowLeft'?Math.max(0,i-1):e.key==='ArrowDown'?Math.min(days.length-1,i+7):e.key==='ArrowUp'?Math.max(0,i-7):e.key==='Home'?0:e.key==='End'?days.length-1:null;
  if(next!==null){e.preventDefault();setFocusIndex(next);buttons.current[next]?.focus();}
 };
 return <div className="p5-rhythm">
  <div className="p5-rhythm-title"><span>Last 4 weeks</span><span><b>{summary.count}</b> rides</span></div>
  <div className="p5-rhythm-body">
   <div className="p5-calendar" aria-label="Riding days" onMouseLeave={()=>{const i=buttons.current.findIndex(b=>b===document.activeElement);setPeek(i>=0?days[i].date:null);}} onBlur={e=>{if(!e.currentTarget.contains(e.relatedTarget))setPeek(null);}}>
    <span/>{days.slice(0,7).map(d=><span key={`day-${d.date}`} className="p5-weekday">{new Intl.DateTimeFormat('en-US',{weekday:'narrow',timeZone:'UTC'}).format(new Date(d.date))}</span>)}
    {Array.from({length:4},(_,week)=><div className="p5-calendar-week" key={week}><time className="p5-week-label" dateTime={days[week*7].date}>{dateLabel(days[week*7].date)}</time>{days.slice(week*7,week*7+7).map((d,j)=>{const i=week*7+j,value=total(d.rides),label=`${dateLabel(d.date)}: ${d.rides.length?`${d.rides.length} ride${d.rides.length===1?'':'s'} · ${(value.distance/1000).toFixed(1)} km · ${duration(value.time)}`:'no rides'}`;return <button key={d.date} ref={el=>{buttons.current[i]=el;}} aria-label={label} aria-pressed={selectedDay===d.date} tabIndex={focusIndex===i?0:-1} onFocus={()=>{setFocusIndex(i);setPeek(d.date);}} onMouseEnter={()=>setPeek(d.date)} onKeyDown={e=>key(e,i)} onClick={()=>onSelect(selectedDay===d.date?null:d.date)} data-empty={!d.rides.length}><span style={{width:d.rides.length?Math.min(13,5+value.time/1400):2,height:d.rides.length?Math.min(13,5+value.time/1400):2}}/></button>;})}</div>)}
   </div>
   <div className="p5-rhythm-measures"><span><b>{(summary.distance/1000).toFixed(1)}</b> km</span><span><b>{summary.climbing.toLocaleString()}</b> m climbed</span><span>{duration(summary.time)}</span></div>
  </div>
  <div className="p5-day-reading" role="status">{inspected&&inspection?<><time>{dateLabel(inspected.date)}</time><span>{inspected.rides.length?`${(inspection.distance/1000).toFixed(1)} km · ${duration(inspection.time)}`:'No rides'}</span></>:<><span>{dateLabel(days[0].date)} – {dateLabel(days[days.length-1].date)}</span><span>{days.filter(d=>d.rides.length).length} riding days</span></>}</div>
 </div>;
}
