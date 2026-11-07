import {useState} from 'react';
import {ChevronRight,ArrowUpRight} from 'lucide-react';
import {RankMark} from '../../src/components/rankmarks/RankMark';
import {FeedV2Avatar,FeedV2Dialog,FeedV2Link} from './FeedV2Context';
import {formatFeedCal} from './feedV2Model';
import {distanceLabel,timeLabel,climbResult} from '../scenario';
import {FeedV4Discovery} from './FeedV4Discovery';
import {type FeedV4Scenario} from './feedV4Model';
import {FeedV3WorldMap} from './FeedV3WorldMap';
import {personalDays,ridingSummary,worldPeriodLabel,type RidingDay,type WorldRegion,} from './feedV3Model';

const shortDate=(s:string)=>new Date(s.slice(0,10)+'T12:00:00Z').toLocaleDateString('en-US',{month:'short',day:'numeric',timeZone:'UTC'});
const hours=(s:number)=>`${Math.floor(s/3600)}h ${Math.floor(s%3600/60)}m`;
const period=(from:string,to:string)=>`${shortDate(from)}–${shortDate(to)}`;


export function PersonalContext({scenario,pending}:{scenario:FeedV4Scenario;pending:boolean}){
  const [span,setSpan]=useState<7|28>(28),[hover,setHover]=useState<RidingDay|null>(null),[detail,setDetail]=useState<RidingDay|'all'|null>(null);
  const personal=scenario.workshopV3?.personal;if(!personal)return null;
  const days=personalDays(personal,span),totals=ridingSummary(days),reading=hover??totals,max=Math.max(1,...days.map(d=>d.elevation));
  const portrait=scenario.entries.find(e=>e.owned)?.ride.ride.rider?.avatarDataUrl;
  return <>
    <div className="f3-person-identity"><FeedV2Avatar name={scenario.viewer} portrait={portrait} large/><h2>{scenario.viewer}</h2></div>
    <section className="f3-riding" data-pending={pending}>
      <div className="f3-context-title"><h2>Your riding</h2><div className="f3-period-switch" role="group" aria-label="Riding period"><button aria-pressed={span===7} onClick={()=>{setSpan(7);setHover(null);}}>Week</button><button aria-pressed={span===28} onClick={()=>{setSpan(28);setHover(null);}}>4 weeks</button></div></div>
      <span className="f3-riding-date">{hover?shortDate(hover.date):period(days[0].date,personal.through)}</span>
      <div className="f3-climbing-reading"><strong>{Math.round(reading.elevation).toLocaleString()}</strong><span>m climbed</span></div>
      <div className="f3-rhythm" role="group" aria-label="Daily climbing" onMouseLeave={()=>setHover(null)}>
        {days.map(d=><button key={d.date} disabled={pending} className="f3-day" data-active={hover?.date===d.date} data-zero={d.rides===0} style={{'--bar-height':`${Math.max(2,d.elevation/max*56)}px`} as React.CSSProperties} aria-label={`${shortDate(d.date)}: ${d.rides} rides, ${d.elevation} m climbed`} onMouseEnter={()=>setHover(d)} onFocus={()=>setHover(d)} onBlur={()=>setHover(null)} onClick={()=>setDetail(d)}><span/></button>)}
      </div>
      <div className="f3-rhythm-axis"><span>{shortDate(days[0].date)}</span><span>{shortDate(personal.through)}</span></div>
      <dl className="f3-riding-totals"><div><dt>Distance</dt><dd>{distanceLabel(reading.distance)}<small>km</small></dd></div><div><dt>Riding time</dt><dd>{hours(reading.duration)}</dd></div></dl>
      <button className="f3-context-link" disabled={pending} onClick={()=>setDetail('all')}><span>{totals.rides} rides</span><span>View riding <ChevronRight size={13}/></span></button>
    </section>
    {personal.standings.length>0&&<section className="f3-standings" data-pending={pending}><h2>Top 10</h2>{personal.standings.map(s=>{const e=scenario.entries.find(e=>e.id===s.entryId)!,c=e.ride.climbs.find(c=>c.id===s.climbId)!;return <FeedV2Link className="f3-standing" entry={e} climb={c.id} key={`${s.entryId}:${s.climbId}`}><RankMark rank={s.rank} size={29}/><span><strong>{c.name}</strong><small><b>{timeLabel(climbResult(e.ride,c).duration)}</b><span>{distanceLabel(climbResult(e.ride,c).distance)} km</span></small></span><ChevronRight size={12}/></FeedV2Link>;})}</section>}
    {detail&&!pending&&<FeedV2Dialog title={detail==='all'?'Your riding':shortDate(detail.date)} onClose={()=>{setDetail(null);setHover(null);}}><div className="f3-dialog-body"><p className="f3-subtle">{detail==='all'?period(days[0].date,personal.through):`${detail.rides} ${detail.rides===1?'ride':'rides'}`}</p><div className="f3-personal-table">{(detail==='all'?[...days].reverse():[detail]).map(d=><div key={d.date}><span>{shortDate(d.date)}<small>{d.rides} {d.rides===1?'ride':'rides'}</small></span><strong>{d.elevation.toLocaleString()}<small>m climbed</small></strong><span>{distanceLabel(d.distance)} km<small>{hours(d.duration)}</small></span></div>)}</div></div></FeedV2Dialog>}
  </>;
}

export function WorldContext({scenario,pending}:{scenario:FeedV4Scenario;pending:boolean}){
  const [hover,setHover]=useState<WorldRegion|null>(null),[detail,setDetail]=useState<WorldRegion|'all'|null>(null);
  const world=scenario.workshopV3?.world;if(!world)return null;
  const discovery=world.discovery,range=worldPeriodLabel(world.periodStart,world.periodEnd);
  return <>
    <section className="f3-world" data-pending={pending}>
      <div className="f3-context-title"><h2>Boulder Roller</h2><span>{range}</span></div>
      <div className="f3-world-reading"><strong>{(hover?.climbsRidden??world.climbsRidden)?.toLocaleString()??'—'}</strong><span>climbs ridden<small>{hover?.name??'Across all regions'}</small></span></div>
      <FeedV3WorldMap regions={world.regions} onInspect={setHover} onOpen={setDetail}/>
      <dl className="f3-world-cal">{world.rideCal!==undefined&&<div><dt>Ride CAL</dt><dd>{formatFeedCal(world.rideCal)}<small>CAL</small></dd></div>}{world.tributeCal!==undefined&&<div><dt>Climb tribute</dt><dd>{formatFeedCal(world.tributeCal)}<small>CAL</small></dd></div>}</dl>
      <button className="f3-context-link" disabled={pending} onClick={()=>setDetail('all')}><span>Activity details</span><ChevronRight size={13}/></button>
    </section>
    {discovery&&<FeedV4Discovery discovery={discovery} pending={pending}/>}
    {detail&&!pending&&<FeedV2Dialog title={detail==='all'?'Boulder Roller':detail.name} onClose={()=>{setDetail(null);setHover(null);}}><div className="f3-dialog-body">
      {<><p className="f3-subtle">{range} · Climbs ridden</p><div className="f3-region-list">{(detail==='all'?world.regions:[detail as WorldRegion]).map(r=><div key={r.id}><span>{r.name}</span><strong>{r.climbsRidden.toLocaleString()}</strong></div>)}</div>{detail==='all'&&<dl className="f3-world-cal">{world.rideCal!==undefined&&<div><dt>Ride CAL</dt><dd>{formatFeedCal(world.rideCal)}<small>CAL</small></dd></div>}{world.tributeCal!==undefined&&<div><dt>Climb tribute</dt><dd>{formatFeedCal(world.tributeCal)}<small>CAL</small></dd></div>}</dl>}<p className="f3-subtle f3-asof">Through {new Date(world.asOf).toLocaleString('en-US',{month:'short',day:'numeric',hour:'numeric',minute:'2-digit',timeZone:'America/New_York',timeZoneName:'short'})}</p></>}
    </div></FeedV2Dialog>}
  </>;
}
