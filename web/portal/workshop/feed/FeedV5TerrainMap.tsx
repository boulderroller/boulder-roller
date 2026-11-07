import {useEffect,useRef,useState} from 'react';
import {Map,Marker,LngLatBounds} from 'maplibre-gl';
import {Minus,Plus,Maximize2} from 'lucide-react';
import {CLIMB_MAP_STYLE_URL,cartoResourceUrl} from '../../src/components/climb/climbMapStyle';
import {v12Ground} from '../v12Ground';
import {type DiscoveryV4} from './feedV4Model';

export function FeedV5TerrainMap({discovery,index,onInspect}:{discovery:DiscoveryV4;index:number|null;onInspect:(index:number|null)=>void}){
 const host=useRef<HTMLDivElement>(null),instance=useRef<Map|null>(null),fitRef=useRef<()=>void>(()=>{});
 const [ready,setReady]=useState(false),[failed,setFailed]=useState(false);
 const geometry=discovery.geometry;
 const inspect=useRef(onInspect);inspect.current=onInspect;const cursor=useRef<Marker|null>(null);
 useEffect(()=>{const map=instance.current;if(!map||!geometry||!ready)return;
  if(index===null){cursor.current?.remove();cursor.current=null;return;}
  if(!cursor.current){const dot=document.createElement('span');dot.className='f5-map-cursor';cursor.current=new Marker({element:dot}).setLngLat(geometry.coordinates[index]).addTo(map);}
  else cursor.current.setLngLat(geometry.coordinates[index]);
 },[index,ready,geometry]);
 useEffect(()=>{
  if(!host.current||!geometry)return;
  const controller=new AbortController();let map:Map|null=null;
  setReady(false);setFailed(false);
  const key=(import.meta.env.VITE_CARTO_API_KEY??'').trim();
  const fit=()=>{if(!map||!host.current?.clientWidth)return;map.resize();const bounds=new LngLatBounds();geometry.coordinates.forEach(p=>bounds.extend(p));map.fitBounds(bounds,{padding:{left:42,right:42,top:35,bottom:35},maxZoom:16,duration:0});};
  fitRef.current=fit;const resize=new ResizeObserver(fit);resize.observe(host.current);
  void(async()=>{try{
   const response=await fetch(cartoResourceUrl(CLIMB_MAP_STYLE_URL,key),{signal:controller.signal});if(!response.ok)throw Error();
   const style=v12Ground(await response.json());if(controller.signal.aborted||!host.current)return;
   style.sources={...style.sources,'f4-discovery-route':{type:'geojson',data:{type:'Feature',properties:{},geometry}},'f4-discovery-ends':{type:'geojson',data:{type:'FeatureCollection',features:[geometry.coordinates[0],geometry.coordinates.at(-1)!].map((coordinates,i)=>({type:'Feature',properties:{finish:i===1},geometry:{type:'Point',coordinates}}))}}};
   style.layers.push({id:'f4-route-case',type:'line',source:'f4-discovery-route',layout:{'line-cap':'round','line-join':'round'},paint:{'line-color':'#fcfff7','line-width':7}}, {id:'f4-route',type:'line',source:'f4-discovery-route',layout:{'line-cap':'round','line-join':'round'},paint:{'line-color':'#456ca0','line-width':3.5}}, {id:'f4-route-ends',type:'circle',source:'f4-discovery-ends',paint:{'circle-radius':5,'circle-color':['case',['get','finish'],'#456ca0','#fcfff7'],'circle-stroke-color':'#456ca0','circle-stroke-width':2}});
   map=new Map({container:host.current,style,attributionControl:false,center:geometry.coordinates[0],zoom:14,transformRequest:url=>({url:cartoResourceUrl(url,key)})});instance.current=map;map.scrollZoom.disable();
   map.on('load',()=>{fit();setReady(true);});
   map.on('mousemove',e=>{let best=0,delta=Infinity;geometry.coordinates.forEach((p,i)=>{const pixel=map!.project(p),d=(pixel.x-e.point.x)**2+(pixel.y-e.point.y)**2;if(d<delta){delta=d;best=i;}});inspect.current(delta<6400?best:null);});
   map.on('mouseout',()=>inspect.current(null));map.on('dragstart',()=>inspect.current(null));map.on('error',e=>{if(!map?.isStyleLoaded()&&!(e as {sourceId?:string}).sourceId)setFailed(true);});
  }catch{if(!controller.signal.aborted)setFailed(true);}})();
  return()=>{controller.abort();resize.disconnect();cursor.current?.remove();cursor.current=null;map?.remove();instance.current=null;};
 },[geometry]);
 if(!geometry)return null;
 return <div className="f4-discovery-map" role="region" aria-label={`${discovery.name} route map`}><div className="f4-discovery-canvas" ref={host} data-map-ready={ready}/>{!ready&&<div className="f4-discovery-map-state" role="status">{failed?'Map unavailable':'Loading map'}</div>}<div className="f4-map-controls"><button aria-label="Fit climb" disabled={!ready} onClick={()=>fitRef.current()}><Maximize2 size={15}/></button><button aria-label="Zoom in" disabled={!ready} onClick={()=>instance.current?.zoomIn({duration:0})}><Plus size={16}/></button><button aria-label="Zoom out" disabled={!ready} onClick={()=>instance.current?.zoomOut({duration:0})}><Minus size={16}/></button></div><div className="f4-map-attribution">© <a href="https://carto.com/about-carto/" target="_blank" rel="noreferrer">CARTO</a> · © <a href="https://www.openstreetmap.org/about/" target="_blank" rel="noreferrer">OpenStreetMap</a></div></div>;
}
