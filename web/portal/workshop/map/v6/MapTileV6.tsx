import {memo} from 'react';
import {ChevronRight} from 'lucide-react';
import type {MapClimb} from '../mapModel';
import {MapProfileV6} from './MapProfileV6';
import {MapLeaderV6} from './MapLeaderV6';

export const MapTileContentsV6=memo(function MapTileContentsV6({climb:c}:{climb:MapClimb}){
 return <>
  <span className="m6-tile-title"><strong>{c.name}</strong><ChevronRight size={13}/></span>
  <MapProfileV6 climb={c} compact/>
  <span className="m6-tile-facts">
   <span><span className="sr-only">Distance </span>{(c.lengthM/1000).toFixed(2)}<small>km</small></span>
   <span><span className="sr-only">Elevation rise </span>{Math.round(c.riseM).toLocaleString()}<small>m rise</small></span>
   <span><span className="sr-only">Average grade </span>{c.gradePct.toFixed(1)}<small>%</small></span>
  </span>
  <MapLeaderV6 climb={c} compact/>
 </>;
});
