import {useState} from 'react';
import {ArrowUpRight,Trophy} from 'lucide-react';
import {V6_GEOGRAPHY,type HistoryRide} from './profileV6Model';
import hills from './assets/hills.png';
import coffee from '../v5/assets/coffee.png';
import creek from '../v4/assets/creek.png';
import portrait from '../v4/assets/portrait.png';
import {timeLabel} from '../../scenario';

export const rideImage=(src:string)=>src==='hills'?hills:src==='coffee'?coffee:src==='creek'?creek:src==='portrait'?portrait:src;
export function RideEntry({ride,onOpen,cal}:{ride:HistoryRide;onOpen:()=>void;cal?:number}){
 const [failed,setFailed]=useState<string|null>(null),photo=ride.photo&&failed!==ride.photo?rideImage(ride.photo):null;
 const names=ride.climbIds.map(id=>V6_GEOGRAPHY.find(c=>c.id===id)?.name).filter(Boolean).join(' · ');
 const duration=`${Math.floor(ride.durationS/3600)}h ${Math.floor(ride.durationS%3600/60)}m`;
 const hill=ride.moment&&V6_GEOGRAPHY.find(c=>c.id===ride.moment!.climbId);
 return <button className="p6-ride-entry" data-ride={ride.id} data-photo={!!photo} onClick={onOpen}>
  <div className="p6-entry-copy">
   <time dateTime={ride.date}>{new Intl.DateTimeFormat('en-US',{weekday:'short',month:'short',day:'numeric',timeZone:'UTC'}).format(new Date(ride.date))}</time>
   <h3>{ride.title}</h3>
   {(ride.note||names&&!ride.moment)&&<p className="p6-entry-note">{ride.note||names}</p>}
   <div className="p6-entry-measures"><span><b>{(ride.distanceM/1000).toFixed(1)}</b> km</span><span><b>{ride.gainM.toLocaleString()}</b> m</span><span>{duration}</span></div>
   {ride.moment&&hill&&<p className="p6-entry-moment"><Trophy size={13}/><span>Personal best <i>·</i> {hill.name}</span><strong>{timeLabel(ride.moment.timeSeconds)}</strong></p>}
   {cal!==undefined&&<p className="p6-entry-cal"><strong>{cal.toLocaleString()}</strong> CAL counted</p>}
  </div>
  {photo&&<img className="p6-entry-photo" src={photo} alt="Photograph from this illustrative ride" onError={()=>setFailed(ride.photo??null)}/>}
  <ArrowUpRight className="p6-entry-arrow" size={15}/>
 </button>;
}
