import {useMemo,useState} from 'react';
import {ArrowUpRight,ChevronRight} from 'lucide-react';
import {RankMark} from '../../src/components/rankmarks/RankMark';
import {FeedV2Avatar,FeedV2Dialog} from './FeedV2Context';
import {FeedV5TerrainMap} from './FeedV5TerrainMap';
import {placeLabel,type NetworkEffort} from './feedV5Model';
import {type DiscoveryV4,discoveryGrade} from './feedV4Model';
import {v6Entries,v6NetworkTerrain as networkDiscovery,type FeedV6Scenario} from './feedV6Model';
import type {WorldRegion} from './feedV3Model';
import {useV6Destination} from './FeedV6Navigation';
import {distanceLabel,timeLabel,climbResult} from '../scenario';
function Profile({data,index=null,onInspect}:{data:DiscoveryV4;index?:number|null;onInspect?:(i:number|null)=>void}){
 const values=data.profile.map(p=>p.elevation),min=Math.min(...values),range=Math.max(1,Math.max(...values)-min),expanded=!!onInspect;
 const x=(d:number)=>d/data.length*500,y=(e:number)=>125-(e-min)/range*100;
 const path=data.profile.map((p,i)=>`${i?'L':'M'}${x(p.d).toFixed(2)},${y(p.elevation).toFixed(2)}`).join(' '),p=index===null?null:data.profile[index];
 return <svg className="f5-network-profile" data-expanded={expanded} viewBox="0 0 500 145" preserveAspectRatio="none" role={expanded?'slider':'img'} tabIndex={expanded?0:undefined} aria-label={`${data.name} elevation profile`} aria-valuemin={expanded?0:undefined} aria-valuemax={expanded?data.profile.length-1:undefined} aria-valuenow={expanded?index??0:undefined} aria-valuetext={expanded?`${Math.round(data.profile[index??0].d)} m along climb, ${Math.round(data.profile[index??0].elevation)} m elevation`:undefined} onPointerMove={onInspect?e=>{const rect=e.currentTarget.getBoundingClientRect(),distance=Math.max(0,Math.min(1,(e.clientX-rect.left)/rect.width))*data.length;let i=0;data.profile.forEach((p,k)=>{if(Math.abs(p.d-distance)<Math.abs(data.profile[i].d-distance))i=k;});onInspect(i);}:undefined} onPointerLeave={()=>onInspect?.(null)} onFocus={()=>onInspect?.(index??0)} onBlur={()=>onInspect?.(null)} onKeyDown={e=>{if(!onInspect)return;if(e.key==='Escape'){onInspect(null);return;}if(!['ArrowLeft','ArrowRight','Home','End'].includes(e.key))return;e.preventDefault();onInspect(e.key==='Home'?0:e.key==='End'?data.profile.length-1:Math.max(0,Math.min(data.profile.length-1,(index??0)+(e.key==='ArrowRight'?1:-1))));}}>
  {expanded&&<path d="M0,25 H500 M0,125 H500" fill="none" stroke="#e5e9de" strokeWidth=".7"/>}<path d={`${path} L500,145 L0,145 Z`} fill="#dce1d2"/><path d={path} fill="none" stroke="#7c8c68" strokeWidth="1.2" vectorEffect="non-scaling-stroke"/>{p&&<><path d={`M${x(p.d)},0 V145`} stroke="#7b886a" strokeWidth=".8" vectorEffect="non-scaling-stroke"/><circle cx={x(p.d)} cy={y(p.elevation)} r="3" fill="#456ca0" stroke="#fff" strokeWidth="1.5"/></>}
 </svg>;
}

function NetworkDetail({network:n,scenario,region,onClose}:{network:NetworkEffort;scenario:FeedV6Scenario;region:string;onClose:()=>void}){
 const [index,setIndex]=useState<number|null>(null),data=useMemo(()=>networkDiscovery(n),[n]),destination=useV6Destination();
 const climb=n.entry.ride.climbs.find(c=>c.id===n.climbId)!,result=climbResult(n.entry.ride,climb),name=n.entry.ride.ride.rider?.displayName??'Rider',analysis=destination.href(n.entry,climb.id,'analysis'),vault=destination.href(n.entry,climb.id,'vault'),point=index===null?null:data?.profile[index],grade=data?discoveryGrade(data):null;
 const board=scenario.workshopV6?.leaderboards.find(b=>b.climbId===climb.id);
 return <FeedV2Dialog title={climb.name} onClose={onClose}><div className="f6-network-detail">
  <div className="f6-climb-location">{region}<span>{distanceLabel(result.distance)} km{grade!==null&&` · ${grade.toFixed(1)}%`}</span></div>
  {data&&<div className="f6-network-terrain"><FeedV5TerrainMap discovery={data} index={index} onInspect={setIndex}/><div className="f5-profile-reading"><span>{point?`${Math.round(point.d)} m along climb`:'Elevation'}</span><strong>{point?`${Math.round(point.elevation)} m`:`${Math.round(Math.min(...data.profile.map(p=>p.elevation)))}–${Math.round(Math.max(...data.profile.map(p=>p.elevation)))} m`}</strong></div><Profile data={data} index={index} onInspect={setIndex}/></div>}
  <div className="f6-network-bottom"><div className="f6-feature-result"><span className="f6-caption">This effort</span><div><RankMark rank={n.leaderboard.rank} size={46}/><strong>{timeLabel(result.duration)}</strong></div><span>{placeLabel(n.leaderboard)} on leaderboard</span><div className="f6-feature-rider"><FeedV2Avatar name={name} portrait={n.entry.ride.ride.rider?.avatarDataUrl}/><span><strong>{name}</strong><small>{new Date(n.entry.ride.ride.startedAt).toLocaleDateString('en-US',{month:'short',day:'numeric',year:'numeric',timeZone:'America/New_York'})}</small></span></div><a href={analysis} target="_top" onClick={e=>destination.open(e,analysis,onClose)}>Analyze effort <ArrowUpRight size={12}/></a></div>
   {board&&board.rows.length>0&&<div className="f6-board"><div className="f6-board-heading"><h3>Current leaderboard</h3><span>{new Date(board.asOf).toLocaleDateString('en-US',{month:'short',day:'numeric',timeZone:'America/New_York'})}</span></div>{board.rows.slice(0,4).map(row=>{const entry=v6Entries(scenario).find(e=>e.ride.id===row.rideId),href=entry?destination.href(entry,climb.id):null,body=<><span>{row.rank}</span><strong>{row.name}</strong><b>{timeLabel(row.duration)}</b></>;return href?<a className="f6-board-row" key={row.id} href={href} target="_top" onClick={e=>destination.open(e,href,onClose)}>{body}</a>:<div className="f6-board-row" key={row.id}>{body}</div>;})}<a className="f6-board-open" href={vault} target="_top" onClick={e=>destination.open(e,vault,onClose)}>Open climb <ChevronRight size={13}/></a></div>}
  </div>
  {(!board||!board.rows.length)&&<a className="f6-board-open" href={vault} target="_top" onClick={e=>destination.open(e,vault,onClose)}>Open climb <ChevronRight size={13}/></a>}
 </div></FeedV2Dialog>;
}
export function FeedV6Network({scenario,features,regions,pending,onRegion}:{scenario:FeedV6Scenario;features:NetworkEffort[];regions:WorldRegion[];pending:boolean;onRegion:(r:WorldRegion)=>void}){
 const [open,setOpen]=useState<NetworkEffort|null>(null),main=features[0],data=useMemo(()=>main?networkDiscovery(main):null,[main]);
 const n=main,climb=n?.entry.ride.climbs.find(c=>c.id===n.climbId),result=n&&climb?climbResult(n.entry.ride,climb):null;
 const remaining=regions.filter(r=>!features.some(f=>f.regionId===r.id)).slice(0,Math.max(0,3-features.length));
 return <><section className="f5-network f6-network" data-pending={pending}><h2>Across Boulder Roller</h2><div className="f6-network-shelf">
  {n&&climb&&result&&<button className="f5-network-card" disabled={pending} onClick={()=>setOpen(n)}><span className="f5-network-identity"><small>{regions.find(r=>r.id===n.regionId)?.name}</small><strong>{climb.name}<ChevronRight size={13}/></strong></span>{data&&<Profile data={data}/>}<span className="f5-network-effort"><RankMark rank={n.leaderboard.rank} size={36}/><span><strong>{n.entry.ride.ride.rider?.displayName??'Rider'}</strong><small>{placeLabel(n.leaderboard)} on leaderboard</small></span><b>{timeLabel(result.duration)}</b></span></button>}
  {features.slice(1,3).map(n=>{const c=n.entry.ride.climbs.find(c=>c.id===n.climbId)!;return <button className="f6-network-row" key={n.entry.id} disabled={pending} onClick={()=>setOpen(n)}><span><small>{regions.find(r=>r.id===n.regionId)?.name}</small><strong>{c.name}</strong></span><b>{timeLabel(climbResult(n.entry.ride,c).duration)}</b><ChevronRight size={12}/></button>;})}
  {remaining.map(r=><button className="f6-network-row" key={r.id} disabled={pending} onClick={()=>onRegion(r)}><span><strong>{r.name}</strong><small>climbs ridden</small></span><b>{r.climbsRidden.toLocaleString()}</b><ChevronRight size={12}/></button>)}
 </div></section>{open&&!pending&&<NetworkDetail network={open} scenario={scenario} region={regions.find(r=>r.id===open.regionId)?.name??''} onClose={()=>setOpen(null)}/>}</>;
}
