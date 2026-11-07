import type {StyleSpecification,FilterSpecification} from 'maplibre-gl';
import {mapV4Ground} from '../v4/mapV4Ground';

/** Keep V4's palette, contours and geography; gently strengthen real relief. */
export function mapV5Ground(source:StyleSpecification):StyleSpecification{
 const style=mapV4Ground(source);
 return {...style,layers:style.layers.map(layer=>{
  if(layer.type==='hillshade'&&layer.id==='r-hillshade')return {...layer,paint:{...layer.paint,'hillshade-exaggeration':['interpolate',['linear'],['zoom'],10,.74,14,.57,16,.40]}};
  // Viewpoints receive their own icon/name pair; preserve the remaining POI classes.
  if(layer.type==='symbol'&&layer.id==='poi_stadium')return {...layer,filter:['all',layer.filter??['all'],['!=','subclass','viewpoint']] as FilterSpecification};
  return layer;
 })};
}
