import type {StyleSpecification} from 'maplibre-gl';
import {v12Ground} from '../../v12Ground';

/** V4 tunes hierarchy within the accepted ground and existing DEM sources. */
export function mapV4Ground(source:StyleSpecification):StyleSpecification{
 const style=v12Ground(source);
 return {...style,layers:style.layers.map(layer=>{
  if(layer.type==='line'&&layer.id==='r-contour')return {...layer,paint:{...layer.paint,'line-opacity':['interpolate',['linear'],['zoom'],11,.18,13,.30,15,.48]}};
  if(layer.type==='line'&&layer.id==='r-contour-index')return {...layer,paint:{...layer.paint,'line-opacity':['interpolate',['linear'],['zoom'],11,.36,13,.56,15,.70]}};
  if(layer.type==='symbol'&&layer.id==='r-contour-label')return {...layer,layout:{...layer.layout,'symbol-spacing':550}};
  if(layer.id==='roadname_sec')return {...layer,minzoom:14.5};
  if(layer.id==='roadname_minor')return {...layer,minzoom:15};
  return layer;
 })};
}
