import {useMemo,useState} from 'react';
import {RankMark} from '../../src/components/rankmarks/RankMark';
import {FeedV2Avatar,FeedV2Dialog} from './FeedV2Context';
import {ClimbV15Map} from '../climb/ClimbV15Map';
import {type DiscoveryV4,discoveryGrade} from './feedV4Model';
import {placeLabel} from './feedV5Model';
import {v6Entries} from './feedV6Model';
import {v12NetworkItems,riderForBoard,type FeedV12Scenario} from './feedV12Model';
import {FeedV12Link,useV12Destination} from './FeedV12Navigation';
import {RiderLink} from './FeedV12Riders';
import {distanceLabel,timeLabel} from '../scenario';
function Profile({data,index=null,onInspect}:{data:DiscoveryV4;index?:number|null;onInspect?:(i:number|null)=>void}){
 const values=data.profile.map(p=>p.elevation),min=Math.min(...values),range=Math.max(1,Math.max(...values)-min),expanded=!!onInspect;
 const x=(d:number)=>d/data.length*500,y=(e:number)=>125-(e-min)/range*100;
 const path=data.profile.map((p,i)=>`${i?'L':'M'}${x(p.d).toFixed(2)},${y(p.elevation).toFixed(2)}`).join(' '),p=index===null?null:data.profile[index];
 return <svg className="f12-network-profile" data-expanded={expanded} viewBox="0 0 500 145" preserveAspectRatio="none" role={expanded?'slider':'img'} tabIndex={expanded?0:undefined} aria-label={`${data.name} elevation profile`} aria-valuemin={expanded?0:undefined} aria-valuemax={expanded?data.profile.length-1:undefined} aria-valuenow={expanded?index??0:undefined} aria-valuetext={expanded?`${Math.round(data.profile[index??0].d)} m along climb, ${Math.round(data.profile[index??0].elevation)} m elevation`:undefined} onPointerMove={onInspect?e=>{const rect=e.currentTarget.getBoundingClientRect(),distance=Math.max(0,Math.min(1,(e.clientX-rect.left)/rect.width))*data.length;let i=0;data.profile.forEach((p,k)=>{if(Math.abs(p.d-distance)<Math.abs(data.profile[i].d-distance))i=k;});onInspect(i);}:undefined} onPointerLeave={()=>onInspect?.(null)} onFocus={()=>onInspect?.(index??0)} onBlur={()=>onInspect?.(null)} onKeyDown={e=>{if(!onInspect)return;if(e.key==='Escape'){onInspect(null);return;}if(!['ArrowLeft','ArrowRight','Home','End'].includes(e.key))return;e.preventDefault();onInspect(e.key==='Home'?0:e.key==='End'?data.profile.length-1:Math.max(0,Math.min(data.profile.length-1,(index??0)+(e.key==='ArrowRight'?1:-1))));}}>
  {expanded&&<path d="M0,25 H500 M0,125 H500" fill="none" stroke="var(--c15-line)" strokeWidth=".7"/>}<path d={`${path} L500,145 L0,145 Z`} fill="var(--c15-data-soft)"/><path d={path} fill="none" stroke="var(--c15-data)" strokeWidth="1.2" vectorEffect="non-scaling-stroke"/>{p&&<><path d={`M${x(p.d)},0 V145`} stroke="var(--c15-accent)" strokeWidth=".8" vectorEffect="non-scaling-stroke"/><circle cx={x(p.d)} cy={y(p.elevation)} r="3" fill="var(--c15-route)" stroke="var(--c15-card)" strokeWidth="1.5"/></>}
 </svg>;
}

type Item=ReturnType<typeof v12NetworkItems>[number];
function NetworkDetail({item,scenario,onClose}:{item:Item;scenario:FeedV12Scenario;onClose:()=>void}){
 const [index,setIndex]=useState<number|null>(null),{row,board,terrain,terrainEntry,climb,region,recording}=item;
 const destination=useV12Destination(),rider=riderForBoard(scenario,climb.id,row.id),point=index===null?null:terrain?.profile[index];
 const portrait=recording?.ride.ride.rider?.avatarDataUrl,grade=terrain?discoveryGrade(terrain):null;
 const vault=destination.href(terrainEntry,climb.id,'vault');
 return <FeedV2Dialog title={climb.name} onClose={onClose}><div className="f12-network-detail">
  <div className="f12-climb-meta"><span>{region.name}</span>{terrain&&<span>{distanceLabel(terrain.length)} km{grade!==null&&` · ${grade.toFixed(1)}%`}</span>}</div>
  <div className="f12-feature-summary"><RiderLink className="f12-feature-person" rider={rider} onOpen={onClose}><FeedV2Avatar name={row.name} portrait={portrait}/><span><strong>{row.name}</strong><small>{placeLabel({rank:row.rank})} on leaderboard</small></span></RiderLink><div className="f12-feature-time"><RankMark rank={row.rank} size={24}/>{recording?<FeedV12Link entry={recording} climb={climb.id}>{timeLabel(row.duration)}</FeedV12Link>:<strong>{timeLabel(row.duration)}</strong>}</div></div>
  {terrain&&<div className="f12-network-terrain"><ClimbV15Map discovery={terrain} index={index} onInspect={setIndex} range={null} onClear={()=>setIndex(null)} fitPadding={()=>({left:42,right:42,top:35,bottom:35})} ground="light" quiet masthead/><div className="f12-profile-reading"><span>{point?`${Math.round(point.d)} m along climb`:'Elevation'}</span><strong>{point?`${Math.round(point.elevation)} m`:`${Math.round(Math.min(...terrain.profile.map(p=>p.elevation)))}–${Math.round(Math.max(...terrain.profile.map(p=>p.elevation)))} m`}</strong></div><Profile data={terrain} index={index} onInspect={setIndex}/></div>}
  <div className="f12-network-board"><div className="f12-board-heading"><h3>Leaderboard</h3><time dateTime={board.asOf}>{new Date(board.asOf).toLocaleDateString('en-US',{month:'short',day:'numeric',timeZone:'America/New_York'})}</time></div>
   {board.rows.slice(0,5).map(r=>{const entry=v6Entries(scenario).find(e=>e.ride.id===r.rideId),person=riderForBoard(scenario,climb.id,r.id);return <div className="f12-board-row" data-featured={row.id===r.id} key={r.id}><span>{r.rank}</span><RiderLink rider={person} onOpen={onClose}>{r.name}</RiderLink>{entry?<FeedV12Link className="f12-time-link" entry={entry} climb={climb.id}>{timeLabel(r.duration)}</FeedV12Link>:<b>{timeLabel(r.duration)}</b>}</div>;})}
  </div>
  <footer className="f12-network-actions">{recording&&<a href={destination.href(recording,climb.id,'analysis')} target="_top" onClick={e=>destination.open(e,destination.href(recording,climb.id,'analysis'),onClose)}>Analyze effort </a>}<a className="f12-open-climb" href={vault} target="_top" onClick={e=>destination.open(e,vault,onClose)}>Open climb </a></footer>
 </div></FeedV2Dialog>;
}
export function FeedV12Network({scenario,pending}:{scenario:FeedV12Scenario;pending:boolean}){
 const items=useMemo(()=>v12NetworkItems(scenario),[scenario]),[open,setOpen]=useState<string|null>(null);
 const destination=useV12Destination(),selected=items.find(i=>i.climb.id===open);if(!items.length)return null;
 return <><section className="f12-network" data-pending={pending}><h2>Across Boulder Roller</h2><div className="f12-network-shelf">{items.map(({row,climb,terrainEntry,terrain,region},i)=>{
  const href=destination.href(terrainEntry,climb.id,'vault');
  return <article className="f12-network-card" data-secondary={i>0} key={climb.id}>
   <a className="f12-climb-target" href={href} target="_top" aria-label={`Open ${climb.name} climb`} aria-disabled={pending||undefined} tabIndex={pending?-1:undefined} onClick={e=>{if(pending){e.preventDefault();return;}destination.open(e,href);}}>
    <span className="f12-network-heading"><span><small>{region.name}</small><strong>{climb.name}</strong></span></span>
    {terrain&&<span className="f12-feature-terrain"><Profile data={terrain}/></span>}
   </a>
   <button className="f12-network-result" disabled={pending} aria-haspopup="dialog" aria-label={`View ${row.name} on ${climb.name}, ${placeLabel({rank:row.rank})}, ${timeLabel(row.duration)}`} onClick={()=>setOpen(climb.id)}>
    <RankMark rank={row.rank} size={24}/><span><strong className="f12-result-rider">{row.name}</strong><small>{placeLabel({rank:row.rank})} on leaderboard</small></span><span className="f12-network-time">{timeLabel(row.duration)}</span>
   </button>
  </article>;
 })}</div></section>{selected&&!pending&&<NetworkDetail item={selected} scenario={scenario} onClose={()=>setOpen(null)}/>}</>;
}
