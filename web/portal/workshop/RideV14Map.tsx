import {useEffect,useRef,useState} from 'react';
import {Map,Marker,LngLatBounds,type StyleSpecification,type LayerSpecification} from 'maplibre-gl';
import {Focus,Minus,Plus} from 'lucide-react';
import {CLIMB_MAP_STYLE_URL,cartoResourceUrl} from '../src/components/climb/climbMapStyle';
import {mastheadGround,hidden,routeLayers} from './climb/ClimbV15Map';
import {heroFitPadding15} from './climb/climbV15Model';
import {rideGeometry} from './rideV14Model';
import type {Scenario} from './scenario';
/** V15 A's ground and camera; V12's full recording, climb spans and numbered pins. */
export function RideV14Map({scenario,cursor,onCursor,onClimb,linked,expanded,onExpand}:{scenario:Scenario;cursor:number|null;onCursor:(index:number|null)=>void;onClimb:(id:string)=>void;linked:string[];expanded:boolean;onExpand:()=>void}){
 const host=useRef<HTMLDivElement>(null),instance=useRef<Map|null>(null),dot=useRef<Marker|null>(null),fitRef=useRef(()=>{}),callbacks=useRef({onCursor,onClimb});callbacks.current={onCursor,onClimb};
 const [ready,setReady]=useState(false),[failed,setFailed]=useState(false),quiet=useRef(!expanded);quiet.current=!expanded;
 const samples=scenario.ride.samples;
 useEffect(()=>{const map=instance.current;if(!map||!ready)return;for(const l of map.getStyle().layers)if(!l.id.startsWith('r14-'))map.setLayoutProperty(l.id,'visibility',hidden(l,!expanded,true)?'none':'visible');},[expanded,ready]);
 useEffect(()=>{const map=instance.current;if(!map||!ready)return;if(cursor===null){dot.current?.remove();dot.current=null;return;}const p=samples[cursor];if(!p)return;if(!dot.current){const el=document.createElement('span');el.className='c15-map-cursor';dot.current=new Marker({element:el}).setLngLat([p.lon,p.lat]).addTo(map);}else dot.current.setLngLat([p.lon,p.lat]);},[cursor,ready,samples]);
 useEffect(()=>{
  if(!host.current||!samples.length)return;const abort=new AbortController(),markers:Marker[]=[];let map:Map|null=null;
  setReady(false);setFailed(false);const key=(import.meta.env.VITE_CARTO_API_KEY??'').trim();
  const fit=()=>{const el=host.current;if(!map||!el?.clientWidth)return;map.resize();const bounds=new LngLatBounds();samples.forEach(p=>bounds.extend([p.lon,p.lat]));map.fitBounds(bounds,{padding:heroFitPadding15(el.clientWidth,el.clientHeight,window.matchMedia('(max-width:700px)').matches,'a'),maxZoom:16,duration:0});};
  fitRef.current=fit;const resize=new ResizeObserver(fit);resize.observe(host.current);
  void(async()=>{try{
   const response=await fetch(cartoResourceUrl(CLIMB_MAP_STYLE_URL,key),{signal:abort.signal});if(!response.ok)throw Error();const base=mastheadGround(await response.json());if(abort.signal.aborted||!host.current)return;
   const cap={'line-cap':'round','line-join':'round'} as const,css=getComputedStyle(host.current),colour=(name:string)=>css.getPropertyValue(name).trim();
   const style:StyleSpecification={...base,sources:{...base.sources,'r14-route':{type:'geojson',data:rideGeometry(samples)},'r14-climbs':{type:'geojson',data:{type:'FeatureCollection',features:scenario.climbs.map(c=>({...rideGeometry(samples.filter(p=>p.t>=c.start&&p.t<=c.end)),properties:{id:c.id}}))}}},layers:[...base.layers.map(l=>hidden(l,quiet.current,true)?{...l,layout:{...l.layout,visibility:'none'}} as LayerSpecification:l),
    ...routeLayers(false).filter(l=>l.id==='c15-route-halo'||l.id==='c15-route').map(l=>({...l,id:l.id.replace('c15-','r14-'),source:'r14-route'} as LayerSpecification)),
    {id:'r14-climbs',type:'line',source:'r14-climbs',layout:cap,paint:{'line-color':colour('--c15-route-strong'),'line-width':4.3}}]};
   map=new Map({container:host.current,style,attributionControl:false,center:[samples[0].lon,samples[0].lat],zoom:11,dragRotate:false,pitchWithRotate:false,transformRequest:url=>({url:cartoResourceUrl(url,key)})});instance.current=map;map.scrollZoom.disable();map.touchZoomRotate.disableRotation();
   scenario.climbs.forEach((c,i)=>{const p=samples.find(p=>p.t===c.start);if(!p)return;const el=document.createElement(linked.includes(c.id)?'button':'span');el.className='r14-pin';el.textContent=String(i+1);if(linked.includes(c.id)){el.setAttribute('aria-label',`Open ${c.name}`);el.onclick=()=>callbacks.current.onClimb(c.id);}markers.push(new Marker({element:el}).setLngLat([p.lon,p.lat]).addTo(map!));});
   [samples[0],samples.at(-1)!].forEach((p,i)=>{const el=document.createElement('button');el.className='r14-endpoint';el.dataset.finish=String(i===1);el.setAttribute('aria-label',i?'Ride finish':'Ride start');el.innerHTML=`<span>${i?'Finish':'Start'}</span>`;const inspect=()=>callbacks.current.onCursor(i?samples.length-1:0);el.onclick=inspect;el.onfocus=el.onmouseenter=inspect;el.onblur=el.onmouseleave=()=>callbacks.current.onCursor(null);markers.push(new Marker({element:el}).setLngLat([p.lon,p.lat]).addTo(map!));});
   map.on('load',()=>{fit();setReady(true);});map.on('mousemove',e=>{let best=0,delta=Infinity;samples.forEach((p,i)=>{const pixel=map!.project([p.lon,p.lat]),d=(pixel.x-e.point.x)**2+(pixel.y-e.point.y)**2;if(d<delta){delta=d;best=i;}});callbacks.current.onCursor(delta<6400?best:null);});map.on('mouseout',()=>callbacks.current.onCursor(null));map.on('dragstart',()=>callbacks.current.onCursor(null));map.on('error',e=>{if(!map?.isStyleLoaded()&&!(e as {sourceId?:string}).sourceId)setFailed(true);});
  }catch{if(!abort.signal.aborted)setFailed(true);}})();
  return()=>{abort.abort();resize.disconnect();markers.forEach(m=>m.remove());dot.current?.remove();dot.current=null;map?.remove();instance.current=null;};
 },[scenario,linked.join('|')]);
 return <div className="c15-map" data-ground="light" data-quiet={!expanded} role="region" aria-label={`${scenario.ride.title} route map`}><div className="c15-map-canvas" ref={host} data-map-ready={ready}/>{!ready&&<div className="c15-map-state" role="status">{failed?'Map unavailable':'Loading map'}</div>}<div className="c15-map-controls"><button aria-label="Fit ride" disabled={!ready} onClick={()=>fitRef.current()}><Focus/></button><button className="c15-map-zoom" aria-label="Zoom in" disabled={!ready} onClick={()=>instance.current?.zoomIn({duration:0})}><Plus/></button><button className="c15-map-zoom" aria-label="Zoom out" disabled={!ready} onClick={()=>instance.current?.zoomOut({duration:0})}><Minus/></button></div><div className="c15-map-foot"><span className="c15-map-attribution">© <a href="https://carto.com/about-carto/" target="_blank" rel="noreferrer">CARTO</a> · © <a href="https://www.openstreetmap.org/about/" target="_blank" rel="noreferrer">OpenStreetMap</a></span><button className="c15-map-size" onClick={onExpand} aria-expanded={expanded}>{expanded?'Compact map':'Expand map'}</button></div></div>;
}
