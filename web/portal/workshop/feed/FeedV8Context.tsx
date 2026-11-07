import {RiderLink} from './FeedV8Riders';
import {useState} from 'react';
import {ChevronRight,ArrowUpRight} from 'lucide-react';
import {RankMark} from '../../src/components/rankmarks/RankMark';
import {FeedV2Avatar,FeedV2Dialog} from './FeedV2Context';
import {formatFeedCal} from './feedV2Model';
import {FeedV8Link as FeedV2Link} from './FeedV8Navigation';
import {distanceLabel,timeLabel,climbResult} from '../scenario';
import {FeedV8Network} from './FeedV8Network';
import {type FeedV8Scenario} from './feedV8Model';
import {FeedV8Activity} from './FeedV8Activity';
import {FeedV5WorldMap} from './FeedV5WorldMap';
import {personalDays,ridingSummary,worldPeriodLabel,type RidingDay,type WorldRegion,} from './feedV3Model';

const shortDate=(s:string)=>new Date(s.slice(0,10)+'T12:00:00Z').toLocaleDateString('en-US',{month:'short',day:'numeric',timeZone:'UTC'});
const hours=(s:number)=>`${Math.floor(s/3600)}h ${Math.floor(s%3600/60)}m`;
const period=(from:string,to:string)=>`${shortDate(from)}–${shortDate(to)}`;


export function PersonalContext({scenario,pending}:{scenario:FeedV8Scenario;pending:boolean}){
  const [span,setSpan]=useState<7|28>(28),[hover,setHover]=useState<RidingDay|null>(null),[detail,setDetail]=useState<RidingDay|'all'|null>(null);
  const personal=scenario.workshopV3?.personal;if(!personal)return null;
  const days=personalDays(personal,span),totals=ridingSummary(days),reading=hover??totals,max=Math.max(1,...days.map(d=>d.elevation));
  const portrait=scenario.entries.find(e=>e.owned)?.ride.ride.rider?.avatarDataUrl;
  return <>
    <div className="f3-person-identity f6-person-identity"><RiderLink className="f8-person-link" rider={scenario.workshopV7?.riders.find(r=>r.viewer)}><FeedV2Avatar name={scenario.viewer} portrait={portrait} large/><h2>{scenario.viewer}</h2></RiderLink></div>
    <section className="f3-riding f6-riding" data-pending={pending}>
      <div className="f3-context-title"><h2>Your riding</h2><div className="f3-period-switch" role="group" aria-label="Riding period"><button aria-pressed={span===7} onClick={()=>{setSpan(7);setHover(null);}}>Week</button><button aria-pressed={span===28} onClick={()=>{setSpan(28);setHover(null);}}>4 weeks</button></div></div>
      <span className="f3-riding-date">{hover?shortDate(hover.date):period(days[0].date,personal.through)}</span>
      <div className="f3-climbing-reading"><strong>{Math.round(reading.elevation).toLocaleString()}</strong><span>m climbed</span></div>
      <div className="f6-rhythm" role="slider" tabIndex={pending?-1:0} aria-label="Daily climbing" aria-valuemin={0} aria-valuemax={days.length-1} aria-valuenow={hover?days.findIndex(d=>d.date===hover.date):days.length-1} aria-valuetext={`${shortDate((hover??days.at(-1)!).date)}: ${(hover??days.at(-1)!).elevation} m climbed, ${(hover??days.at(-1)!).rides} rides`} onPointerMove={e=>{if(pending)return;const box=e.currentTarget.getBoundingClientRect();setHover(days[Math.min(days.length-1,Math.max(0,Math.floor((e.clientX-box.left)/box.width*days.length)))]);}} onPointerLeave={()=>setHover(null)} onFocus={()=>setHover(current=>current??days.at(-1)!)} onBlur={()=>setHover(null)} onClick={e=>{if(pending)return;const box=e.currentTarget.getBoundingClientRect();const day=e.detail===0?(hover??days.at(-1)!):days[Math.min(days.length-1,Math.max(0,Math.floor((e.clientX-box.left)/box.width*days.length)))];setHover(day);setDetail(day);}} onKeyDown={e=>{if(e.key==='Escape'){setHover(null);return;}if(e.key==='Enter'||e.key===' '){e.preventDefault();setDetail(hover??days.at(-1)!);return;}if(!['ArrowLeft','ArrowRight','Home','End'].includes(e.key))return;e.preventDefault();const current=hover?days.findIndex(d=>d.date===hover.date):days.length-1;setHover(days[e.key==='Home'?0:e.key==='End'?days.length-1:Math.max(0,Math.min(days.length-1,current+(e.key==='ArrowLeft'?-1:1)))]);}}>
       {days.map(d=><span key={d.date} className="f6-day" data-active={hover?.date===d.date} data-zero={d.rides===0}><i style={{height:`${Math.max(2,d.elevation/max*70)}px`}}/></span>)}
      </div>
      <div className="f3-rhythm-axis"><span>{shortDate(days[0].date)}</span><span>{shortDate(personal.through)}</span></div>
      <dl className="f3-riding-totals"><div><dt>Distance</dt><dd>{distanceLabel(reading.distance)}<small>km</small></dd></div><div><dt>Riding time</dt><dd>{hours(reading.duration)}</dd></div></dl>
      <button className="f3-context-link" disabled={pending} onClick={()=>setDetail('all')}><span>{totals.rides} rides</span><span>View riding <ChevronRight size={13}/></span></button>
    </section>
    {personal.standings.length>0&&<section className="f3-standings" data-pending={pending}><h2>Your leaderboards</h2>{personal.standings.map(s=>{const e=scenario.entries.find(e=>e.id===s.entryId)!,c=e.ride.climbs.find(c=>c.id===s.climbId)!;return <FeedV2Link className="f3-standing" entry={e} climb={c.id} view="vault" key={`${s.entryId}:${s.climbId}`}><span className="f5-standing-mark"><RankMark rank={s.rank} size={48}/></span><span><strong>{c.name}</strong><small><b>{timeLabel(climbResult(e.ride,c).duration)}</b><span>Top 10</span></small></span><ChevronRight size={12}/></FeedV2Link>;})}</section>}
    {detail&&!pending&&<FeedV2Dialog title={detail==='all'?'Your riding':shortDate(detail.date)} onClose={()=>{setDetail(null);setHover(null);}}><div className="f3-dialog-body"><p className="f3-subtle">{detail==='all'?period(days[0].date,personal.through):`${detail.rides} ${detail.rides===1?'ride':'rides'}`}</p><div className="f3-personal-table">{(detail==='all'?[...days].reverse():[detail]).map(d=><div key={d.date}><span>{shortDate(d.date)}<small>{d.rides} {d.rides===1?'ride':'rides'}</small></span><strong>{d.elevation.toLocaleString()}<small>m climbed</small></strong><span>{distanceLabel(d.distance)} km<small>{hours(d.duration)}</small></span></div>)}</div></div></FeedV2Dialog>}
  </>;
}

export function WorldContext({scenario,pending}:{scenario:FeedV8Scenario;pending:boolean}){
 const [hover,setHover]=useState<WorldRegion|null>(null),[detail,setDetail]=useState<WorldRegion|'all'|null>(null);
 const world=scenario.workshopV3?.world;if(!world)return null;
 const range=worldPeriodLabel(world.periodStart,world.periodEnd),total=world.climbsRidden;
 const open=(r:WorldRegion|'all')=>{setDetail(r);};
 const cal=<dl className="f3-world-cal">{world.rideCal!==undefined&&<div><dt>Ride CAL</dt><dd>{formatFeedCal(world.rideCal)}<small>CAL</small></dd></div>}{world.tributeCal!==undefined&&<div><dt>Climb tribute</dt><dd>{formatFeedCal(world.tributeCal)}<small>CAL</small></dd></div>}</dl>;
 return <>
  <section className="f3-world" data-pending={pending}><div className="f3-context-title"><h2>Boulder Roller</h2><span>{range}</span></div><div className="f3-world-reading"><strong>{(hover?.climbsRidden??total)?.toLocaleString()??'—'}</strong><span>climbs ridden<small>{hover?.name??'Across all regions'}</small></span></div><FeedV5WorldMap regions={world.regions} activeId={hover?.id} onInspect={setHover} onOpen={open}/>{cal}<button className="f3-context-link" disabled={pending} onClick={()=>open('all')}><span>View network activity</span><ChevronRight size={13}/></button></section>
  {<FeedV8Network scenario={scenario} pending={pending}/>}
  {detail&&!pending&&<FeedV8Activity world={world} initialRegion={detail==='all'?null:detail.id} onClose={()=>{setDetail(null);setHover(null);}}/>}
 </>;
}
