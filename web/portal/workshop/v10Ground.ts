import type { StyleSpecification } from 'maplibre-gl';
import { v3Ground } from './v3Ground';
/** V10-only vegetation, preserving the geographic recipe and prior generations. */
export function v10Ground(source: StyleSpecification): StyleSpecification {
 const style = v3Ground(source);
 const fills: Record<string,string> = { 'r-landuse-residential':'#e9ece5', 'r-landcover-wood':'#9fc489', 'r-landcover-grass':'#c1dca5', 'r-park':'#b3d595', 'r-landuse-pitch':'#aad18f', 'r-landuse-cemetery':'#c1d5ae', 'r-landcover-farmland':'#e1e5bd', 'r-landcover-wetland':'#b5d2bc' };
 return { ...style, layers: style.layers.map(layer => {
  if (layer.type === 'background') return {...layer,paint:{...layer.paint,'background-color':'#f0f1eb'}};
  if (layer.type === 'fill' && (fills[layer.id] || /water/.test(layer.id))) {
   const color = fills[layer.id] ?? '#b0d6e5';
   return {...layer,paint:{...layer.paint,'fill-color':color,'fill-outline-color':color,...(layer.id === 'r-park' ? {'fill-opacity':.35} : {})}};
  }
  if (layer.type === 'hillshade') return {...layer,paint:{...layer.paint,'hillshade-shadow-color':'#7b976a','hillshade-highlight-color':'#fcfff5','hillshade-accent-color':'#a4bf8a'}};
  return layer;
 }) };
}
