import {useEffect,useRef,useState} from 'react';
import {Map as VectorMap, ScaleControl, type GeoJSONSource, type ExpressionSpecification} from 'maplibre-gl';
import {Maximize2,Minus,Plus,RotateCcw} from 'lucide-react';
import {CLIMB_MAP_STYLE_URL,cartoResourceUrl} from '../../../src/components/climb/climbMapStyle';
import {mapV4Ground} from './mapV4Ground';
import {midpoint,surroundingBounds,type Bounds,type MapCamera,type MapClimb,type MapStudy} from '../mapModel';
import 'maplibre-gl/dist/maplibre-gl.css';
import {selectionMove} from './mapV4Model';
type Props={listOpen?:boolean;cameraControl?:{current:(()=>MapCamera|null)|null};study:MapStudy;originId?:string|null;detail?:boolean;climbs:MapClimb[];selectedId:string|null;hoveredId:string|null;camera:MapCamera|null;active:boolean;forceFailure?:boolean;focus:{id:string;nonce:number}|null;onCamera:(camera:MapCamera,bounds:Bounds)=>void;onSelect:(id:string)=>void;onHover:(id:string|null)=>void;onClear:()=>void;onRetry?:()=>void};
const boundsOf=(map:VectorMap):Bounds=>{const b=map.getBounds();return [b.getWest(),b.getSouth(),b.getEast(),b.getNorth()];};
const duration=()=>matchMedia('(prefers-reduced-motion: reduce)').matches?0:320;
export function MapCanvasV4(props:Props){
 const host=useRef<HTMLDivElement>(null),mapRef=useRef<VectorMap|null>(null),callbacks=useRef(props);callbacks.current=props;
 const [status,setStatus]=useState<'loading'|'ready'|'error'>('loading'),[retry,setRetry]=useState(0);
 const fitRef=useRef<()=>void>(()=>{}),fittedOrigin=useRef<string|null|undefined>(undefined),appliedFocus=useRef<number|null>(null);
 useEffect(()=>{
  if(!host.current)return;const element=host.current,controller=new AbortController();let map:VectorMap|null=null,disposed=false,mapReady=false;setStatus('loading');
  const key=(import.meta.env.VITE_CARTO_API_KEY??'').trim();
  const padding=()=>({top:84,left:40,right:40,bottom:props.detail?40:element.clientWidth<600?330:70});
  const save=()=>{if(!map||!mapReady||!element.clientWidth)return;const c=map.getCenter();const right:ExpressionSpecification=['>', ['get','lng'], c.lng];map.setLayoutProperty('m2-label','text-anchor',['case',right,'right','left']);map.setLayoutProperty('m2-label','text-offset',['case',right,['literal',[-1.1,0]],['literal',[1.1,0]]]);element.dataset.cameraCenter=JSON.stringify([c.lng,c.lat]);element.dataset.cameraZoom=String(map.getZoom());element.dataset.moving='false';const selected=callbacks.current.study.climbs.find(c=>c.id===callbacks.current.selectedId);if(selected){const p=map.project(midpoint(selected));element.dataset.selectedCenter=JSON.stringify([p.x,p.y]);}else delete element.dataset.selectedCenter;callbacks.current.onCamera({center:[c.lng,c.lat],zoom:map.getZoom()},boundsOf(map));};
  const fit=()=>{if(!map)return;map.fitBounds(surroundingBounds({...callbacks.current.study,originId:callbacks.current.originId??undefined}),{padding:padding(),maxZoom:props.detail?16:14.3,duration:duration()});};fitRef.current=fit;
  void(async()=>{try{
   if(props.forceFailure)throw Error('Map unavailable');
   const response=await fetch(cartoResourceUrl(CLIMB_MAP_STYLE_URL,key),{signal:controller.signal});if(!response.ok)throw Error('Map unavailable');
   const style=mapV4Ground(await response.json());if(disposed)return;
   const empty: {type:'FeatureCollection';features:[]}={type:'FeatureCollection',features:[]};
   style.sources['m2-routes']={type:'geojson',data:empty};style.sources['m2-markers']={type:'geojson',data:empty};
   const lit:ExpressionSpecification=['any',['==',['get','id'],props.selectedId??''],['==',['get','id'],props.hoveredId??'']];
   style.layers.push(
    {id:'m2-route-case',type:'line',source:'m2-routes',layout:{'line-cap':'round','line-join':'round'},paint:{'line-color':'#fcfff7','line-width':['case',lit,7,4.5],'line-opacity':.9}},
    {id:'m2-route',type:'line',source:'m2-routes',layout:{'line-cap':'round','line-join':'round'},paint:{'line-color':['case',lit,'#456ca0','#6b805b'],'line-width':['case',lit,3.8,2.4]}},
    {id:'m2-route-hit',type:'line',source:'m2-routes',paint:{'line-color':'#456ca0','line-width':22,'line-opacity':0}},
    {id:'m2-marker-halo',type:'circle',source:'m2-markers',paint:{'circle-radius':['case',lit,11,6],'circle-color':'#fcfff7','circle-opacity':.85}},
    {id:'m2-marker',type:'circle',source:'m2-markers',paint:{'circle-radius':['case',lit,5,3.5],'circle-color':['case',lit,'#456ca0','#647553']}},
    {id:'m2-marker-hit',type:'circle',source:'m2-markers',paint:{'circle-radius':16,'circle-opacity':0}},
    {id:'m2-label',type:'symbol',source:'m2-markers',minzoom:11,layout:{'text-field':['get','name'],'text-font':['Montserrat Medium','Open Sans Bold'],'text-size':['case',lit,13,11],'text-anchor':'left','text-offset':[1.1,0],'text-max-width':12,'text-allow-overlap':false,'symbol-sort-key':['case',lit,0,1]},paint:{'text-color':['case',lit,'#294c70','#41543a'],'text-halo-color':'#f4f7ed','text-halo-width':2}}
   );
   const saved=callbacks.current.camera;
   map=new VectorMap({container:element,style,center:saved?.center??midpoint(props.study.climbs.find(c=>c.id===props.originId)??props.study.climbs[0]??{bounds:[-75.26,40.03,-75.19,40.075]} as MapClimb),zoom:saved?.zoom??13,minZoom:3,maxZoom:19,attributionControl:false,pitchWithRotate:false,dragRotate:false,touchPitch:false,transformRequest:url=>({url:cartoResourceUrl(url,key)})});
   mapRef.current=map;map.touchZoomRotate.disableRotation();map.addControl(new ScaleControl({maxWidth:80,unit:'metric'}),'bottom-right');
   if(props.cameraControl)props.cameraControl.current=()=>{if(!map)return null;map.stop();const c=map.getCenter();return {center:[c.lng,c.lat],zoom:map.getZoom()};};
   map.on('load',()=>{if(disposed)return;mapReady=true;fittedOrigin.current=callbacks.current.originId;setStatus('ready');if(!saved){const arrival=callbacks.current.study.climbs.find(c=>c.id===callbacks.current.originId);if(!props.detail&&element.clientWidth<600&&arrival)map!.fitBounds(arrival.bounds,{padding:padding(),maxZoom:13.8,duration:duration()});else fit();}else save();});
   map.on('movestart',()=>{element.dataset.moving='true';});map.on('moveend',save);
   map.on('click',e=>{const f=map!.queryRenderedFeatures([[e.point.x-6,e.point.y-6],[e.point.x+6,e.point.y+6]],{layers:['m2-route-hit','m2-marker-hit']});const id=f[0]?.properties?.id;if(id)callbacks.current.onSelect(id);else callbacks.current.onClear();});
   map.on('mousemove',e=>{const f=map!.queryRenderedFeatures(e.point,{layers:['m2-route-hit','m2-marker-hit']});const id=f[0]?.properties?.id??null;map!.getCanvas().style.cursor=id?'pointer':'';callbacks.current.onHover(id);});
   map.on('mouseout',()=>callbacks.current.onHover(null));map.on('dragstart',()=>callbacks.current.onHover(null));
   map.on('error',e=>{if(!map?.isStyleLoaded()&&!(e as {sourceId?:string}).sourceId&&!disposed)setStatus('error');});
  }catch{if(!disposed&&!controller.signal.aborted)setStatus('error');}})();
  const resize=new ResizeObserver(()=>{if(element.clientWidth&&element.clientHeight)map?.resize();});resize.observe(element);
  return()=>{disposed=true;controller.abort();resize.disconnect();map?.remove();mapRef.current=null;if(props.cameraControl)props.cameraControl.current=null;};
 },[props.study.id,props.forceFailure,retry]);
 useEffect(()=>{const map=mapRef.current,c=props.camera;if(!map||!c||status!=='ready')return;const current=map.getCenter();if(Math.abs(current.lng-c.center[0])>1e-7||Math.abs(current.lat-c.center[1])>1e-7||Math.abs(map.getZoom()-c.zoom)>1e-7)map.jumpTo({center:c.center,zoom:c.zoom});},[props.camera,status]);
 useEffect(()=>{if(status==='ready'&&!props.camera&&fittedOrigin.current!==props.originId){fittedOrigin.current=props.originId;fitRef.current();}},[props.originId,status]);
 useEffect(()=>{const map=mapRef.current;if(!map||status!=='ready')return;
  const routeFeatures=props.climbs.filter(c=>c.geometry&&c.geometrySource==='canon_centerline').map(c=>({type:'Feature' as const,properties:{id:c.id,name:c.name},geometry:c.geometry!}));
  const markerFeatures=props.climbs.map(c=>{const point=c.geometry?.coordinates[0]??midpoint(c);return {type:'Feature' as const,properties:{id:c.id,name:c.name,lng:point[0]},geometry:{type:'Point' as const,coordinates:point}};});
  (map.getSource('m2-routes') as GeoJSONSource).setData({type:'FeatureCollection',features:routeFeatures});
  (map.getSource('m2-markers') as GeoJSONSource).setData({type:'FeatureCollection',features:markerFeatures});
 },[props.climbs,status]);
 useEffect(()=>{const map=mapRef.current;if(!map||status!=='ready')return;
  const selected:ExpressionSpecification=['==',['get','id'],props.selectedId??''],hovered:ExpressionSpecification=['==',['get','id'],props.hoveredId??''];
  const value=(normal:number,hover:number,active:number):ExpressionSpecification=>['case',selected,active,hovered,hover,normal];
  map.setPaintProperty('m2-route','line-color',['case',selected,'#456ca0','#6b805b']);map.setPaintProperty('m2-route','line-width',value(2.4,3,3.8));map.setPaintProperty('m2-route-case','line-width',value(4.5,5.7,7));
  map.setPaintProperty('m2-marker','circle-color',['case',selected,'#456ca0','#647553']);map.setPaintProperty('m2-marker','circle-radius',value(3.5,4.2,5));map.setPaintProperty('m2-marker-halo','circle-radius',value(6,8,11));
  map.setPaintProperty('m2-label','text-color',['case',selected,'#294c70','#41543a']);map.setLayoutProperty('m2-label','text-size',['case',selected,13,11]);map.setLayoutProperty('m2-label','symbol-sort-key',['case',selected,0,1]);
 },[props.selectedId,props.hoveredId,status]);
 useEffect(()=>{const map=mapRef.current,element=host.current;if(!map||!element||!props.focus||status!=='ready'||appliedFocus.current===props.focus.nonce)return;const climb=props.study.climbs.find(c=>c.id===props.focus!.id);if(!climb)return;
  appliedFocus.current=props.focus.nonce;const c=map.getCenter();map.stop();
  map.easeTo({...selectionMove(climb,{center:[c.lng,c.lat],zoom:map.getZoom()},{width:element.clientWidth,height:element.clientHeight,listOpen:callbacks.current.listOpen===true}),duration:duration()});
 },[props.focus,status]);
 useEffect(()=>{if(props.active)requestAnimationFrame(()=>mapRef.current?.resize());},[props.active]);
 return <div className="m2-map" aria-label="Climb discovery map" data-map-status={status} data-route-count={props.climbs.filter(c=>c.geometry&&c.geometrySource==='canon_centerline').length} data-marker-count={props.climbs.length}>
  <div className="m2-canvas" ref={host}/>
  {status!=='ready'&&<div className="m2-map-state" role="status"><span>{status==='error'?'Map unavailable':'Opening map'}</span>{status==='error'&&<button onClick={()=>props.forceFailure&&props.onRetry?props.onRetry():setRetry(r=>r+1)}><RotateCcw size={14}/>Try again</button>}</div>}
  <div className="m2-map-controls" aria-label="Map controls"><button aria-label="Fit surrounding climbs" disabled={status!=='ready'} onClick={()=>fitRef.current()}><Maximize2 size={17}/></button><button aria-label="Zoom in" disabled={status!=='ready'} onClick={()=>mapRef.current?.zoomIn({duration:duration()})}><Plus size={18}/></button><button aria-label="Zoom out" disabled={status!=='ready'} onClick={()=>mapRef.current?.zoomOut({duration:duration()})}><Minus size={18}/></button></div>
  <div className="m2-attribution"><a href="https://www.openstreetmap.org/copyright" target="_blank" rel="noreferrer">© OpenStreetMap contributors</a><a href="https://carto.com/attributions" target="_blank" rel="noreferrer">© CARTO</a><a href="https://registry.opendata.aws/terrain-tiles/" target="_blank" rel="noreferrer">Terrain: Mapzen</a></div>
 </div>;
}
