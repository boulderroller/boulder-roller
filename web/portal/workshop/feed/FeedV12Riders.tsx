import {createContext,useContext,useEffect,useState,type ReactNode} from 'react';
import {FeedV2Avatar,FeedV2Dialog} from './FeedV2Context';
import {FeedV12Link,useV12Destination} from './FeedV12Navigation';
import {v6Entries} from './feedV6Model';
import {v12RiderHref,type FeedV12Scenario,type V12Rider} from './feedV12Model';
import {distanceLabel,summarize,timeLabel} from '../scenario';
import {RankMark} from '../../src/components/rankmarks/RankMark';
const RiderContext=createContext<{scenario:FeedV12Scenario|null;filter:string;open:(id:string)=>void}>({scenario:null,filter:'everyone',open:()=>{}});
export function RiderLink({rider,children,className='',label,onOpen}:{rider?:V12Rider;children:ReactNode;className?:string;label?:string;onOpen?:()=>void}){
 const c=useContext(RiderContext);if(!rider||!c.scenario)return <span className={className}>{children}</span>;
 return <a className={`f12-rider-link ${className}`} href={v12RiderHref(c.scenario,rider.id,c.filter)} target="_top" aria-label={label} data-rider={rider.id} onClick={e=>{if(e.button||e.metaKey||e.ctrlKey||e.shiftKey||e.altKey)return;e.preventDefault();onOpen?.();c.open(rider.id);}}>{children}</a>;
}
function RiderDetail({rider:r,scenario,onClose}:{rider:V12Rider;scenario:FeedV12Scenario;onClose:()=>void}){
 const entries=v6Entries(scenario).filter(e=>r.entryIds.includes(e.id)),portrait=entries.find(e=>e.ride.ride.rider?.avatarDataUrl)?.ride.ride.rider?.avatarDataUrl;
 const rows=(scenario.workshopV6?.leaderboards??[]).flatMap(b=>b.rows.filter(row=>r.boardRows.includes(`${b.climbId}:${row.id}`)).map(row=>({board:b,row})));
 const destination=useV12Destination();
 return <FeedV2Dialog title={r.name} onClose={onClose}><div className="f12-rider-detail">
  <div className="f12-rider-intro"><FeedV2Avatar name={r.name} portrait={portrait} large/><div><strong>{r.name}</strong>{entries[0]?.ride.ride.location&&<span>{entries[0].ride.ride.location}</span>}</div></div>
  {entries.length>0&&<section className="f12-rider-rides"><h3>Rides</h3>{entries.map(e=>{const totals=summarize(e.ride.ride.samples),href=destination.href(e);return <a className="f12-rider-ride" href={href} target="_top" key={e.id} onClick={ev=>destination.open(ev,href)}><div><time dateTime={e.ride.ride.startedAt}>{new Date(e.ride.ride.startedAt).toLocaleDateString('en-US',{month:'short',day:'numeric',timeZone:'America/New_York'})}</time><strong>{e.ride.ride.title}</strong><span>{distanceLabel(totals.distance)} km<span>·</span>{totals.gain===null?timeLabel(totals.duration):`${Math.round(totals.gain).toLocaleString()} m climbed`}</span></div></a>;})}</section>}
  {rows.length>0&&<section className="f12-rider-boards"><h3>Leaderboards</h3>{rows.map(({board,row})=>{const terrain=v6Entries(scenario).find(e=>e.ride.climbs.some(c=>c.id===board.climbId)),climb=terrain?.ride.climbs.find(c=>c.id===board.climbId),recording=v6Entries(scenario).find(e=>e.ride.id===row.rideId);if(!terrain||!climb)return null;return <div className="f12-rider-standing" key={`${board.climbId}:${row.id}`}><RankMark rank={row.rank} size={24}/><FeedV12Link entry={terrain} climb={climb.id} view="vault"><strong>{climb.name}</strong><small>{row.rank===1?'1st':row.rank===2?'2nd':row.rank===3?'3rd':`${row.rank}th`} on leaderboard</small></FeedV12Link>{recording?<FeedV12Link className="f12-time-link" entry={recording} climb={climb.id}>{timeLabel(row.duration)}</FeedV12Link>:<b>{timeLabel(row.duration)}</b>}</div>;})}</section>}
  {!entries.length&&!rows.length&&<p className="f12-rider-empty">No rides to show.</p>}
 </div></FeedV2Dialog>;
}
export function RiderProvider({scenario,filter,riderId,onRider,children}:{scenario:FeedV12Scenario;filter:string;riderId?:string|null;onRider?:(id:string|null)=>void;children:ReactNode}){
 const [open,setOpen]=useState<string|null>(riderId??null);
 useEffect(()=>{setOpen(riderId??null);},[riderId]);
 const rider=scenario.workshopV7?.riders.find(r=>r.id===open);
 const change=(id:string|null)=>{setOpen(id);onRider?.(id);};
 return <RiderContext.Provider value={{scenario,filter,open:change}}>{children}{rider&&<RiderDetail rider={rider} scenario={scenario} onClose={()=>change(null)}/>}</RiderContext.Provider>;
}
