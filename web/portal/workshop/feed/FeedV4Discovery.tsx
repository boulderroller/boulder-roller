import {useState} from 'react';
import {ChevronRight} from 'lucide-react';
import {FeedV2Dialog} from './FeedV2Context';
import {FeedV4DiscoveryMap} from './FeedV4DiscoveryMap';
import {discoveryGrade,type DiscoveryV4} from './feedV4Model';
import {distanceLabel} from '../scenario';

function Profile({discovery,expanded=false}:{discovery:DiscoveryV4;expanded?:boolean}){
 const values=discovery.profile.map(p=>p.elevation),min=Math.min(...values),max=Math.max(...values),range=Math.max(1,max-min),floor=expanded?135:68,top=expanded?22:10;
 const x=(d:number)=>d/discovery.length*500,y=(e:number)=>floor-(e-min)/range*(floor-top);
 const path=discovery.profile.map((p,i)=>`${i?'L':'M'}${x(p.d).toFixed(2)},${y(p.elevation).toFixed(2)}`).join(' ');
 return <svg className={`f4-discovery-profile ${expanded?'expanded':''}`} viewBox={`0 0 500 ${expanded?160:72}`} preserveAspectRatio="none" role="img" aria-label={`${discovery.name} elevation profile`}>
  {expanded&&<path d="M0,22 H500 M0,135 H500" fill="none" stroke="#e4e8dc" strokeWidth=".6"/>}
  <path d={`${path} L${x(discovery.profile.at(-1)!.d)},${floor} L${x(discovery.profile[0].d)},${floor} Z`} fill="#dce1d2"/><path d={path} fill="none" stroke="#7c8c68" strokeWidth="1.2" vectorEffect="non-scaling-stroke"/>
 </svg>;
}
function Facts({discovery}:{discovery:DiscoveryV4}){const grade=discoveryGrade(discovery);return <dl className="f4-discovery-facts"><div><dt>Distance</dt><dd>{distanceLabel(discovery.length)}<small>km</small></dd></div><div><dt>Elevation</dt><dd>{Math.round(discovery.gain)}<small>m</small></dd></div><>{grade!==null&&<div><dt>Avg grade</dt><dd>{grade.toFixed(1)}<small>%</small></dd></div>}</></dl>;}
export function FeedV4Discovery({discovery,pending}:{discovery:DiscoveryV4;pending:boolean}){
 const [open,setOpen]=useState(false);
 return <><section className="f4-discovery" data-pending={pending}><h2>Discover a climb</h2><button className="f4-discovery-card" disabled={pending} onClick={()=>setOpen(true)}><span className="f4-discovery-identity">{discovery.locality&&<small>{discovery.locality}</small>}<strong>{discovery.name}<ChevronRight size={13}/></strong></span><Profile discovery={discovery}/><Facts discovery={discovery}/></button></section>
  {open&&!pending&&<FeedV2Dialog title={discovery.name} onClose={()=>setOpen(false)}><div className="f4-discovery-detail">{discovery.locality&&<p>{discovery.locality}</p>}<Facts discovery={discovery}/><FeedV4DiscoveryMap discovery={discovery}/><div className="f4-profile-detail"><span className="f4-profile-height">{Math.round(Math.max(...discovery.profile.map(p=>p.elevation)))} m</span><Profile discovery={discovery} expanded/><span className="f4-profile-axis"><span>0</span><span>{distanceLabel(discovery.length)} km</span></span></div></div></FeedV2Dialog>}
 </>;
}
