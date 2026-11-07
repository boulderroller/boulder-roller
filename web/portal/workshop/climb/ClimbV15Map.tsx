import {useEffect,useRef,useState,type ReactNode} from 'react';
import {Map,Marker,LngLatBounds,type PaddingOptions,type StyleSpecification,type LayerSpecification} from 'maplibre-gl';
import 'maplibre-gl/dist/maplibre-gl.css';
import {Minus,Plus,Focus} from 'lucide-react';
import {CLIMB_MAP_STYLE_URL,cartoResourceUrl,nightLedgerMapStyle} from '../../src/components/climb/climbMapStyle';
import {v12Ground} from '../v12Ground';
import {type DiscoveryV4} from '../feed/feedV4Model';
import {endLabelAnchor} from './climbV15Model';

/** Route on the night ground: production's cobalt (MAP_GROUND's canon route, ClimbMap.tsx '#5592E2'), on a ground-coloured halo with a soft glow.
 *  Kept local, never added to palette.ts, so the shared Palette toggle cannot re-map older candidates. */
const ROUTE_NIGHT='#5592e2',GROUND='#161917';
/** Voyager's own symbol layers (place, road and house labels). The ratified land names are ours and start with r-.
 *  Compact, all of Voyager's labels hide; expanded, road and water names return while place and POI names stay hidden,
 *  because they would read through the title on the masthead's left half. */
const voyagerLabel=(layer:LayerSpecification)=>layer.type==='symbol'&&!layer.id.startsWith('r-');
const hiddenLabel=(layer:LayerSpecification,quiet:boolean)=>voyagerLabel(layer)&&(quiet||['place','poi','housenumber'].includes((layer as {'source-layer'?:string})['source-layer']??''));
/** On A's compact masthead the land and water names hide too (park, peak and contour labels clip at the card's edges and ghost under the type);
 *  the parks still read from their cover, and the names return on Expand map. */
const landName=(layer:LayerSpecification)=>['r-park-name','r-peak-name','r-contour-label','r-waterway-name','r-water-name'].includes(layer.id);
export const hidden=(layer:LayerSpecification,quiet:boolean,lightMast:boolean)=>hiddenLabel(layer,quiet)||(lightMast&&quiet&&landName(layer));
export function routeLayers(night:boolean):LayerSpecification[]{
 const cap={'line-cap':'round','line-join':'round'} as const;
 return night?[
  {id:'c15-route-glow',type:'line',source:'c15-route',layout:cap,paint:{'line-color':ROUTE_NIGHT,'line-width':14,'line-blur':11,'line-opacity':.45}},
  {id:'c15-route-halo',type:'line',source:'c15-route',layout:cap,paint:{'line-color':GROUND,'line-width':6.2}},
  {id:'c15-route',type:'line',source:'c15-route',layout:cap,paint:{'line-color':ROUTE_NIGHT,'line-width':3.2}},
  {id:'c15-selection',type:'line',source:'c15-selection',layout:cap,paint:{'line-color':ROUTE_NIGHT,'line-width':5}},
  {id:'c15-route-ends',type:'circle',source:'c15-ends',paint:{'circle-radius':4.5,'circle-color':['case',['get','finish'],ROUTE_NIGHT,GROUND],'circle-stroke-color':ROUTE_NIGHT,'circle-stroke-width':2}},
 ]:[
  {id:'c15-route-halo',type:'line',source:'c15-route',layout:cap,paint:{'line-color':'#fcfff7','line-width':7}},
  {id:'c15-route',type:'line',source:'c15-route',layout:cap,paint:{'line-color':'#456ca0','line-width':3.5}},
  {id:'c15-selection',type:'line',source:'c15-selection',layout:cap,paint:{'line-color':'#225aad','line-width':5}},
  {id:'c15-route-ends',type:'circle',source:'c15-ends',paint:{'circle-radius':5,'circle-color':['case',['get','finish'],'#456ca0','#fcfff7'],'circle-stroke-color':'#456ca0','circle-stroke-width':2}},
 ];
}
/** The night masthead uses the Tim-ratified ground (nightLedgerMapStyle) with a stronger relief, so the hill reads under the title. */
/** A's masthead ground: V14's green ground (v12Ground) one step greener on the built-up land, with the hill's relief drawn in an olive shade
 *  and no highlight, so every climb carries the ground's colour and the slope itself shapes the picture. V13 and V14 keep v12Ground as is. */
export function mastheadGround(source:StyleSpecification):StyleSpecification{
 const style=v12Ground(source);
 return {...style,layers:style.layers.map(l=>{
  if(l.type==='background')return {...l,paint:{...l.paint,'background-color':'#e9eedf'}};
  if(l.id==='r-landuse-residential')return {...l,paint:{...l.paint,'fill-color':'#e2e8d6','fill-outline-color':'#e2e8d6'}} as LayerSpecification;
  if(l.type==='hillshade')return {...l,paint:{...l.paint,'hillshade-exaggeration':['interpolate',['linear'],['zoom'],12,.7,16,.55],'hillshade-shadow-color':'#6d7a5c','hillshade-highlight-color':'rgba(0,0,0,0)'}};
  return l;
 })};
}
function nightGround(source:StyleSpecification,relief:boolean):StyleSpecification{
 const style=nightLedgerMapStyle(source);
 return relief?{...style,layers:style.layers.map(l=>l.type==='hillshade'?{...l,paint:{...l.paint,'hillshade-exaggeration':.8,'hillshade-highlight-color':'#596150'}}:l)}:style;
}
/** ClimbV14Map with a ground: light (V13 and V14's green ground, v12Ground) for A's masthead and B's map card, night for C's plate.
 *  Under a masthead's type (`masthead`), Voyager's labels hide on either ground. End labels name Start and Finish as production does. */
export function ClimbV15Map({discovery,index,onInspect,range,onClear,fitPadding,ground,quiet,relief=false,masthead=false,children}:{discovery:DiscoveryV4;index:number|null;onInspect:(index:number|null)=>void;range:[number,number]|null;onClear:()=>void;fitPadding:(width:number,height:number)=>PaddingOptions;ground:'night'|'light';quiet:boolean;relief?:boolean;masthead?:boolean;children?:ReactNode}){
 const host=useRef<HTMLDivElement>(null),instance=useRef<Map|null>(null),fitRef=useRef<()=>void>(()=>{}),padding=useRef(fitPadding);padding.current=fitPadding;
 const [ready,setReady]=useState(false),[failed,setFailed]=useState(false),night=ground==='night',hush=night||masthead,lightMast=masthead&&!night,quietRef=useRef(quiet);quietRef.current=quiet;
 const geometry=discovery.geometry;const clear=useRef(onClear);clear.current=onClear;
 useEffect(()=>{const map=instance.current;if(!map||!ready||!geometry)return;const source=map.getSource('c15-selection') as import('maplibre-gl').GeoJSONSource;source?.setData({type:'FeatureCollection',features:range?[{type:'Feature',properties:{},geometry:{type:'LineString',coordinates:geometry.coordinates.slice(range[0],range[1]+1)}}]:[]});map.setPaintProperty('c15-route','line-opacity',range ? .5 : 1);},[range,ready,geometry]);
 useEffect(()=>{const map=instance.current;if(!map||!ready||!hush)return;for(const layer of map.getStyle().layers)if(voyagerLabel(layer)||(lightMast&&landName(layer)))map.setLayoutProperty(layer.id,'visibility',hidden(layer,quiet,lightMast)?'none':'visible');},[quiet,ready,hush,lightMast]);
 const inspect=useRef(onInspect);inspect.current=onInspect;const cursor=useRef<Marker|null>(null);
 useEffect(()=>{const map=instance.current;if(!map||!geometry||!ready)return;
  if(index===null){cursor.current?.remove();cursor.current=null;return;}
  if(!cursor.current){const dot=document.createElement('span');dot.className='c15-map-cursor';cursor.current=new Marker({element:dot}).setLngLat(geometry.coordinates[index]).addTo(map);}
  else cursor.current.setLngLat(geometry.coordinates[index]);
 },[index,ready,geometry]);
 useEffect(()=>{
  if(!host.current||!geometry)return;
  const controller=new AbortController();let map:Map|null=null;const labels:Marker[]=[];
  setReady(false);setFailed(false);
  const key=(import.meta.env.VITE_CARTO_API_KEY??'').trim();
  const fit=()=>{const el=host.current;if(!map||!el?.clientWidth)return;map.resize();const bounds=new LngLatBounds();geometry.coordinates.forEach(p=>bounds.extend(p));map.fitBounds(bounds,{padding:padding.current(el.clientWidth,el.clientHeight),maxZoom:16,duration:0});};
  fitRef.current=fit;const resize=new ResizeObserver(fit);resize.observe(host.current);
  void(async()=>{try{
   const response=await fetch(cartoResourceUrl(CLIMB_MAP_STYLE_URL,key),{signal:controller.signal});if(!response.ok)throw Error();
   const json=await response.json(),base=night?nightGround(json,relief):lightMast?mastheadGround(json):v12Ground(json);if(controller.signal.aborted||!host.current)return;
   const ends=[geometry.coordinates[0],geometry.coordinates.at(-1)!];
   const style:StyleSpecification={...base,sources:{...base.sources,'c15-route':{type:'geojson',data:{type:'Feature',properties:{},geometry}},'c15-ends':{type:'geojson',data:{type:'FeatureCollection',features:ends.map((coordinates,i)=>({type:'Feature',properties:{finish:i===1},geometry:{type:'Point',coordinates}}))}},'c15-selection':{type:'geojson',data:{type:'FeatureCollection',features:[]}}},
    layers:[...base.layers.map(l=>hush&&hidden(l,quietRef.current,lightMast)?{...l,layout:{...l.layout,visibility:'none'}} as LayerSpecification:l),...routeLayers(night)]};
   map=new Map({container:host.current,style,attributionControl:false,center:geometry.coordinates[0],zoom:14,transformRequest:url=>({url:cartoResourceUrl(url,key)})});instance.current=map;map.scrollZoom.disable();
   const reach=Math.max(1,Math.round(geometry.coordinates.length*.04));
   ends.forEach((point,i)=>{const neighbour=geometry.coordinates[i===0?Math.min(reach,geometry.coordinates.length-1):Math.max(0,geometry.coordinates.length-1-reach)],{anchor,offset}=endLabelAnchor(point,neighbour);
    const label=document.createElement('span');label.className='c15-end-label';label.dataset.tone=ground;label.textContent=i===0?'Start':'Finish';
    labels.push(new Marker({element:label,anchor,offset}).setLngLat(point).addTo(map!));});
   map.on('load',()=>{fit();setReady(true);});
   map.on('mousemove',e=>{let best=0,delta=Infinity;geometry.coordinates.forEach((p,i)=>{const pixel=map!.project(p),d=(pixel.x-e.point.x)**2+(pixel.y-e.point.y)**2;if(d<delta){delta=d;best=i;}});inspect.current(delta<6400?best:null);});
   map.on('click',()=>clear.current());map.on('mouseout',()=>inspect.current(null));map.on('dragstart',()=>inspect.current(null));map.on('error',e=>{if(!map?.isStyleLoaded()&&!(e as {sourceId?:string}).sourceId)setFailed(true);});
  }catch{if(!controller.signal.aborted)setFailed(true);}})();
  return()=>{controller.abort();resize.disconnect();cursor.current?.remove();cursor.current=null;labels.forEach(l=>l.remove());map?.remove();instance.current=null;};
 },[geometry,night,relief,ground,hush,lightMast]);
 if(!geometry)return null;
 return <div className="c15-map" data-ground={ground} data-quiet={quiet} role="region" aria-label={`${discovery.name} route map`}>
  <div className="c15-map-canvas" ref={host} data-map-ready={ready}/>
  {!ready&&<div className="c15-map-state" role="status">{failed?'Map unavailable':'Loading map'}</div>}
  <div className="c15-map-controls"><button aria-label="Fit climb" disabled={!ready} onClick={()=>fitRef.current()}><Focus/></button><button className="c15-map-zoom" aria-label="Zoom in" disabled={!ready} onClick={()=>instance.current?.zoomIn({duration:0})}><Plus/></button><button className="c15-map-zoom" aria-label="Zoom out" disabled={!ready} onClick={()=>instance.current?.zoomOut({duration:0})}><Minus/></button></div>
  <div className="c15-map-foot"><span className="c15-map-attribution">© <a href="https://carto.com/about-carto/" target="_blank" rel="noreferrer">CARTO</a> · © <a href="https://www.openstreetmap.org/about/" target="_blank" rel="noreferrer">OpenStreetMap</a></span>{children}</div>
 </div>;
}
