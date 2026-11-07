import {memo} from 'react';
import type {MapClimb} from '../mapModel';

/** A shape with honest horizontal and vertical scales, using only supplied samples. */
export const MapProfileV5=memo(function MapProfileV5({climb}:{climb:MapClimb}){
 const profile=climb.profile;
 if(!profile)return null;
 let low=Infinity,high=-Infinity;
 for(const point of profile){low=Math.min(low,point.elevationM);high=Math.max(high,point.elevationM);}
 const floor=Math.floor(low/10)*10,ceiling=Math.max(floor+10,Math.ceil(high/10)*10),width=304,height=96;
 const points=profile.map(p=>`${(p.distanceM/climb.lengthM*width).toFixed(2)},${(height-4-(p.elevationM-floor)/(ceiling-floor)*(height-12)).toFixed(2)}`).join(' ');
 return <figure className="m5-profile" aria-label={`${climb.name} elevation profile, ${Math.round(low)} to ${Math.round(high)} metres`}>
  <div className="m5-profile-axis"><span>{ceiling} m</span><span>{floor} m</span></div>
  <svg viewBox={`0 0 ${width} ${height}`} preserveAspectRatio="none" role="img" aria-label="Elevation along the climb">
   <path d={`M0 8H${width}M0 ${height-4}H${width}`} className="m5-profile-grid"/>
   <polygon points={`0,${height} ${points} ${width},${height}`} fill="currentColor" opacity=".08"/>
   <polyline points={points} fill="none" stroke="currentColor" strokeWidth="1.8" vectorEffect="non-scaling-stroke"/>
  </svg>
  <figcaption><span>0</span><span>{(climb.lengthM/1000).toFixed(2)} km</span></figcaption>
 </figure>;
});
