import {Map,LngLatBounds,setWorkerUrl,type StyleSpecification,type LayerSpecification} from 'maplibre-gl';
import workerUrl from 'maplibre-gl/dist/maplibre-gl-worker.mjs?worker&url';
setWorkerUrl(workerUrl);
import {CLIMB_MAP_STYLE_URL,cartoResourceUrl,nightLedgerMapStyle} from '../../src/components/climb/climbMapStyle';
export type RouteGeometry={type:'LineString';coordinates:[number,number][]};
/** Geometry and relief stay with the shared geographic recipe. All kit paint comes from tokens. */
export function mapGround(source:StyleSpecification,token:(name:string)=>string):StyleSpecification {
 const number=(name:string)=>Number.parseFloat(token(name));
 const base=nightLedgerMapStyle(source,{quiet:true});
 const fills:Record<string,string>={'r-landuse-residential':'map-residential','r-landuse-commercial':'map-commercial','r-landuse-industrial':'map-industrial','r-landuse-school':'map-school','r-landuse-cemetery':'map-cemetery','r-landuse-pitch':'map-pitch','r-landcover-farmland':'map-farmland','r-landcover-grass':'map-grass','r-landcover-wood':'map-wood','r-landcover-wetland':'map-wetland','r-landcover-sand':'map-sand','r-landcover-ice':'map-ice','r-park':'map-park','r-building':'map-building'};
 return {...base,layers:base.layers.map((layer):LayerSpecification=>{
  if(layer.type==='symbol')return {...layer,layout:{...layer.layout,visibility:'none'}};
  if(layer.type==='background')return {...layer,paint:{...layer.paint,'background-color':token('map-land')}};
  if(layer.type==='fill'){
   const color=token(fills[layer.id]??(/water/.test(layer.id)?'map-water':'map-fill'));
   return {...layer,paint:{...layer.paint,'fill-color':color,'fill-outline-color':layer.id==='r-building'?token('map-building-outline'):color,...(layer.id==='r-park'?{'fill-opacity':number('map-park-opacity')}:{})}};
  }
  if(layer.type==='hillshade')return {...layer,paint:{...layer.paint,'hillshade-shadow-color':token('map-shadow'),'hillshade-highlight-color':token('clear'),'hillshade-accent-color':token('map-accent'),'hillshade-exaggeration':['interpolate',['linear'],['zoom'],number('map-relief-zoom-low'),number('map-relief-low'),number('map-relief-zoom-high'),number('map-relief-high')]}};
  if(layer.type==='line'){
   const id=layer.id,color=id==='r-contour-index'?'map-contour-index':id==='r-contour'?'map-contour':/water/.test(id)?'map-water-edge':/boundary/.test(id)?'map-boundary':/rail/.test(id)?'map-rail':id==='r-park-line'?'map-park-line':/case/.test(id)?'map-road-case':/path|track/.test(id)?'map-path':/motorway|trunk|primary/.test(id)?'map-major-road':'map-road';
   return {...layer,paint:{...layer.paint,'line-color':token(color)}};
  }
  if(layer.type==='circle')return {...layer,paint:{...layer.paint,'circle-color':token('map-peak'),'circle-stroke-color':token('map-halo')}};
  return layer;
 })};
}
export type MapControls={dispose:()=>void;fit:()=>void;zoomIn:()=>void;zoomOut:()=>void};
const mountedMaps=new WeakMap<HTMLElement,{map:Map;geometry:RouteGeometry}>();
/** Read the rendered route in host pixels for the workshop's clearance probe. */
export function projectedRoute(host:HTMLElement){
 const mounted=mountedMaps.get(host);
 return mounted?.geometry.coordinates.map(coordinate=>{const point=mounted.map.project(coordinate);return {x:point.x,y:point.y};})??[];
}
export const fatalMapError=(styleLoaded:boolean,sourceId?:string)=>!styleLoaded&&!sourceId;
export async function mountMap(host:HTMLElement,geometry:RouteGeometry,signal:AbortSignal,onState:(state:'ready'|'error')=>void):Promise<MapControls> {
 const key=(import.meta.env.VITE_CARTO_API_KEY??'').trim(),token=(name:string)=>getComputedStyle(host).getPropertyValue(`--v15-${name}`).trim();
 const number=(name:string)=>Number.parseFloat(token(name));
 const response=await fetch(cartoResourceUrl(CLIMB_MAP_STYLE_URL,key),{signal});if(!response.ok)throw Error('Map unavailable');
 const source=await response.json();if(signal.aborted)throw new DOMException('Aborted','AbortError');
 const base=mapGround(source,token),style:StyleSpecification={...base,sources:{...base.sources,'kit-route':{type:'geojson',data:{type:'Feature',properties:{},geometry}}},layers:[...base.layers,{id:'kit-route-halo',type:'line',source:'kit-route',layout:{'line-cap':'round','line-join':'round'},paint:{'line-color':token('card'),'line-width':number('map-route-halo-width')}},{id:'kit-route',type:'line',source:'kit-route',layout:{'line-cap':'round','line-join':'round'},paint:{'line-color':token('route'),'line-width':number('map-route-width')}}]};
 const map=new Map({container:host,style,attributionControl:false,interactive:false,transformRequest:url=>({url:cartoResourceUrl(url,key)})});
 mountedMaps.set(host,{map,geometry});
 const masthead=host.closest('.v15-masthead'),copy=masthead?.querySelector('.v15-masthead-copy'),controls=masthead?.querySelector('.v15-map-controls'),attribution=masthead?.querySelector('.v15-map-attribution');
 let disposed=false;
 const fit=()=>{
  if(disposed||!host.clientWidth)return;
  map.resize();
  const box=host.getBoundingClientRect(),copyBox=copy?.getBoundingClientRect(),controlBox=controls?.getBoundingClientRect(),attributionBox=attribution?.getBoundingClientRect(),phone=matchMedia('(max-width:700px)').matches;
  const edge=number(phone?'space-24':'space-32'),clearance=number('space-12');
  const padding={top:edge,bottom:edge,left:edge,right:Math.max(edge,controlBox?box.right-controlBox.left+clearance:number('space-48'))};
  if(copyBox){
   const fade=getComputedStyle(copy!,'::before');
   if(phone)padding.bottom=Math.max(edge,box.bottom-copyBox.top-Math.min(0,parseFloat(fade.top))+clearance);
   else padding.left=copyBox.right-box.left-Math.min(0,parseFloat(fade.right))+clearance;
  }
  if(attributionBox&&attributionBox.top<box.top+box.height/2)padding.top=Math.max(edge,attributionBox.bottom-box.top+clearance);
  const bounds=new LngLatBounds();geometry.coordinates.forEach(point=>bounds.extend(point));
  map.fitBounds(bounds,{padding,duration:0,maxZoom:number('map-max-zoom')});
 };
 map.on('load',()=>{fit();onState('ready');});
 map.on('error',event=>{if(fatalMapError(!!map.isStyleLoaded(),(event as {sourceId?:string}).sourceId))onState('error');});
 const observer=new ResizeObserver(fit);observer.observe(host);if(copy)observer.observe(copy);if(controls)observer.observe(controls);
 void document.fonts.ready.then(fit);
 const dispose=()=>{if(disposed)return;disposed=true;observer.disconnect();mountedMaps.delete(host);map.remove();signal.removeEventListener('abort',dispose);};signal.addEventListener('abort',dispose,{once:true});
 return {dispose,fit,zoomIn:()=>map.zoomIn({duration:0}),zoomOut:()=>map.zoomOut({duration:0})};
}
