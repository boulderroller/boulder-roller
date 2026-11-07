import {memo} from 'react';
import type {MapClimb} from '../mapModel';

/** Profiles fill their inset; explicit elevation limits disclose each local scale. */
export const MapProfileV6=memo(function MapProfileV6({climb,compact=false}:{climb:MapClimb;compact?:boolean}){
 const p=climb.profile;if(!p?.length)return null;
 let low=Infinity,high=-Infinity;
 for(const point of p){low=Math.min(low,point.elevationM);high=Math.max(high,point.elevationM);}
 const floor=Math.floor(low/10)*10,ceiling=Math.max(floor+10,Math.ceil(high/10)*10),w=260,h=compact?44:80;
 const points=p.map(p=>`${(p.distanceM/climb.lengthM*w).toFixed(2)},${(h-(p.elevationM-floor)/(ceiling-floor)*h).toFixed(2)}`).join(' ');
 return <span className="m6-relief" data-compact={compact} role="img" aria-label={`${climb.name} elevation profile; ${floor} to ${ceiling} metres over ${(climb.lengthM/1000).toFixed(2)} kilometres`}>
  <svg viewBox={`0 0 ${w} ${h}`} preserveAspectRatio="none" aria-hidden="true">
   <path className="m6-relief-grid" d={`M0 0H${w}M0 ${h/2}H${w}M0 ${h}H${w}`}/>
   <polygon className="m6-relief-fill" points={`0,${h} ${points} ${w},${h}`}/>
   <polyline className="m6-relief-line" points={points} vectorEffect="non-scaling-stroke"/>
  </svg>
  <span className="m6-relief-limits" aria-hidden="true"><span>{ceiling}<small>m</small></span><span>{floor}<small>m</small></span></span>
 </span>;
});
