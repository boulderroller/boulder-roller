import {useState} from 'react';
import {FeedV2Dialog} from './FeedV2Context';
import {formatFeedCal} from './feedV2Model';
import {distanceLabel} from '../scenario';
import {FeedV13Network} from './FeedV13Network';
import {type FeedV13Scenario} from './feedV13Model';
import {FeedV13Activity} from './FeedV13Activity';
import {personalDays,ridingSummary,worldPeriodLabel,type RidingDay} from './feedV3Model';
import {destinationHref} from '../frame/destinations';
import {Unit,Tight} from '../climb/ClimbV15Hero';
const shortDate=(s:string)=>new Date(s.slice(0,10)+'T12:00:00Z').toLocaleDateString('en-US',{month:'short',day:'numeric',timeZone:'UTC'});
const hours=(s:number)=>`${Math.floor(s/3600)}h ${Math.floor(s%3600/60)}m`;
const period=(from:string,to:string)=>`${shortDate(from)}–${shortDate(to)}`;

export function PersonalContext({scenario,pending}:{scenario:FeedV13Scenario;pending:boolean}){
  const [span,setSpan]=useState<7|28>(28),[hover,setHover]=useState<RidingDay|null>(null),[detail,setDetail]=useState<RidingDay|'all'|null>(null);
  const personal=scenario.workshopV3?.personal;if(!personal)return null;
  const days=personalDays(personal,span),totals=ridingSummary(days),reading=hover??totals,max=Math.max(1,...days.map(d=>d.elevation));
  if(!days.length)return null;
  return <>

    <section className="c15-card f13-riding" data-pending={pending}>
      <div className="f13-context-title"><h2 className="c15-kicker">Your riding</h2><div className="c15-segmented" role="group" aria-label="Riding period"><button aria-pressed={span===7} onClick={()=>{setSpan(7);setHover(null);}}>Week</button><button aria-pressed={span===28} onClick={()=>{setSpan(28);setHover(null);}}>4 weeks</button></div></div>
      <span className="f13-riding-date">{hover?shortDate(hover.date):period(days[0].date,personal.through)}</span>
      <dl className="c15-stat f13-climbing-reading"><dt>m climbed</dt><dd className="c15-stat-value">{pending?<span className="c15-bone"/>:Math.round(reading.elevation).toLocaleString()}</dd></dl>
      <div className="f13-rhythm" role="slider" tabIndex={pending?-1:0} aria-label="Daily climbing" aria-valuemin={0} aria-valuemax={days.length-1} aria-valuenow={hover?days.findIndex(d=>d.date===hover.date):days.length-1} aria-valuetext={`${shortDate((hover??days.at(-1)!).date)}: ${(hover??days.at(-1)!).elevation} m climbed, ${(hover??days.at(-1)!).rides} rides`} onPointerMove={e=>{if(pending)return;const box=e.currentTarget.getBoundingClientRect();setHover(days[Math.min(days.length-1,Math.max(0,Math.floor((e.clientX-box.left)/box.width*days.length)))]);}} onPointerLeave={()=>setHover(null)} onFocus={()=>setHover(current=>current??days.at(-1)!)} onBlur={()=>setHover(null)} onClick={e=>{if(pending)return;const box=e.currentTarget.getBoundingClientRect();const day=e.detail===0?(hover??days.at(-1)!):days[Math.min(days.length-1,Math.max(0,Math.floor((e.clientX-box.left)/box.width*days.length)))];setHover(day);setDetail(day);}} onKeyDown={e=>{if(e.key==='Escape'){setHover(null);return;}if(e.key==='Enter'||e.key===' '){e.preventDefault();setDetail(hover??days.at(-1)!);return;}if(!['ArrowLeft','ArrowRight','Home','End'].includes(e.key))return;e.preventDefault();const current=hover?days.findIndex(d=>d.date===hover.date):days.length-1;setHover(days[e.key==='Home'?0:e.key==='End'?days.length-1:Math.max(0,Math.min(days.length-1,current+(e.key==='ArrowLeft'?-1:1)))]);}}>
       {days.map(d=><span key={d.date} className="f13-day" data-active={hover?.date===d.date} data-zero={d.rides===0}><i style={{height:`${Math.max(2,d.elevation/max*70)}px`}}/></span>)}
      </div>
      <div className="f13-rhythm-axis"><span>{shortDate(days[0].date)}</span><span>{shortDate(personal.through)}</span></div>
      <dl className="f13-riding-totals"><div className="c15-stat"><dt>Distance</dt><dd className="c15-stat-value">{pending?<span className="c15-bone"/>:<>{distanceLabel(reading.distance)}<Unit>km</Unit></>}</dd></div><div className="c15-stat"><dt>Riding time</dt><dd className="c15-stat-value">{pending?<span className="c15-bone"/>:<>{Math.floor(reading.duration/3600)}<Tight>h</Tight> {Math.floor(reading.duration%3600/60)}<Tight>m</Tight></>}</dd></div></dl>
      <div className="f13-context-foot"><span>{pending?<span className="c15-bone"/>:`${totals.rides} rides`}</span><a className="c15-text-button" href={destinationHref('profile',{tab:'training'})} target="_top">View riding</a></div>
    </section>

    {detail&&!pending&&<FeedV2Dialog title={detail==='all'?'Your riding':shortDate(detail.date)} onClose={()=>{setDetail(null);setHover(null);}}><div className="f13-dialog-body"><p className="f13-subtle">{detail==='all'?period(days[0].date,personal.through):`${detail.rides} ${detail.rides===1?'ride':'rides'}`}</p><div className="f13-personal-table">{(detail==='all'?[...days].reverse():[detail]).map(d=><div key={d.date}><span>{shortDate(d.date)}<small>{d.rides} {d.rides===1?'ride':'rides'}</small></span><strong>{d.elevation.toLocaleString()}<small>m climbed</small></strong><span>{distanceLabel(d.distance)} km<small>{hours(d.duration)}</small></span></div>)}</div></div></FeedV2Dialog>}
  </>;
}
export function WorldContext({scenario,pending}:{scenario:FeedV13Scenario;pending:boolean}){
 const [detail,setDetail]=useState(false);
 const world=scenario.workshopV3?.world;if(!world)return null;
 const total=world.climbsRidden;
 return <section className="c15-card f13-world" data-pending={pending}>
  <div className="f13-context-title"><h2 className="c15-kicker">Boulder Roller</h2><span>{worldPeriodLabel(world.periodStart,world.periodEnd)}</span></div>
  {total!==undefined&&<dl className="c15-stat f13-world-reading"><dt>climbs ridden</dt><dd className="c15-stat-value">{pending?<span className="c15-bone"/>:total.toLocaleString()}</dd><dd className="f13-world-region">Across all regions</dd></dl>}
  <button className="c15-text-button f13-network-open" disabled={pending} onClick={()=>setDetail(true)}>View network activity</button>
  <FeedV13Network scenario={scenario} pending={pending}/>
  {(world.rideCal!==undefined||world.tributeCal!==undefined)&&<dl className="f13-world-cal">{world.rideCal!==undefined&&<div><dt>Ride CAL</dt><dd>{pending?<span className="c15-bone"/>:<>{formatFeedCal(world.rideCal)}<Unit>CAL</Unit></>}</dd></div>}{world.tributeCal!==undefined&&<div><dt>Climb tribute</dt><dd>{pending?<span className="c15-bone"/>:<>{formatFeedCal(world.tributeCal)}<Unit>CAL</Unit></>}</dd></div>}</dl>}
  {detail&&!pending&&<FeedV13Activity world={world} initialRegion={null} onClose={()=>setDetail(false)}/>}
 </section>;
}
