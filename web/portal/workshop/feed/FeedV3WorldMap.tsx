import {useEffect,useRef,useState} from 'react';
import {Map,Marker,LngLatBounds} from 'maplibre-gl';
import {CLIMB_MAP_STYLE_URL,cartoResourceUrl} from '../../src/components/climb/climbMapStyle';
import {v12Ground} from '../v12Ground';
import {type WorldRegion} from './feedV3Model';

export function FeedV3WorldMap({regions,onInspect,onOpen}:{regions:WorldRegion[];onInspect:(r:WorldRegion|null)=>void;onOpen:(r:WorldRegion)=>void}){
  const host=useRef<HTMLDivElement>(null),callbacks=useRef({onInspect,onOpen});callbacks.current={onInspect,onOpen};
  const [ready,setReady]=useState(false),[failed,setFailed]=useState(false);
  useEffect(()=>{
    if(!host.current||!regions.length)return;
    let map:Map|undefined;const abort=new AbortController(),markers:Marker[]=[];
    setReady(false);setFailed(false);
    const key=(import.meta.env.VITE_CARTO_API_KEY??'').trim();
    const fit=()=>{if(!map||!host.current?.clientWidth)return;map.resize();const bounds=new LngLatBounds();regions.forEach(r=>bounds.extend([r.lon,r.lat]));map.fitBounds(bounds,{padding:{top:32,bottom:30,left:28,right:28},maxZoom:6,duration:0});};
    const observer=new ResizeObserver(fit);observer.observe(host.current);
    void(async()=>{try{
      const response=await fetch(cartoResourceUrl(CLIMB_MAP_STYLE_URL,key),{signal:abort.signal});if(!response.ok)throw Error();
      const style=v12Ground(await response.json());if(abort.signal.aborted||!host.current)return;
      // Keep the small world view calm enough for its activity marks to read.
      style.layers=style.layers.filter(l=>l.type!=='symbol');
      map=new Map({container:host.current,style,interactive:false,attributionControl:false,center:[-45,35],zoom:1,transformRequest:url=>({url:cartoResourceUrl(url,key)})});
      map.on('load',()=>{
        if(abort.signal.aborted)return;fit();
        const max=Math.max(1,...regions.map(r=>r.climbsRidden));
        regions.forEach(r=>{
          const button=document.createElement('button');button.type='button';button.className='f3-world-dot';button.setAttribute('aria-label',`${r.name}: ${r.climbsRidden.toLocaleString()} climbs ridden`);
          button.title=r.name;button.style.setProperty('--mark-size',`${8+Math.sqrt(r.climbsRidden/max)*18}px`);
          button.dataset.zero=String(r.climbsRidden===0);
          button.onmouseenter=()=>callbacks.current.onInspect(r);button.onmouseleave=()=>callbacks.current.onInspect(null);
          button.onfocus=()=>callbacks.current.onInspect(r);button.onblur=()=>callbacks.current.onInspect(null);button.onclick=()=>callbacks.current.onOpen(r);
          markers.push(new Marker({element:button}).setLngLat([r.lon,r.lat]).addTo(map!));
        });setReady(true);
      });
      map.on('error',e=>{if(!map?.isStyleLoaded()&&!(e as {sourceId?:string}).sourceId)setFailed(true);});
    }catch{if(!abort.signal.aborted)setFailed(true);}})();
    return()=>{abort.abort();observer.disconnect();markers.forEach(m=>m.remove());map?.remove();};
  },[regions]);
  if(!regions.length)return null;
  return <div className="f3-world-map"><div ref={host} className="f3-world-map-canvas" data-map-ready={ready}/>{!ready&&<span className="f3-world-map-state">{failed?'Map unavailable':'Loading map'}</span>}<div className="f3-world-attribution">© <a href="https://carto.com/about-carto/" target="_blank" rel="noreferrer">CARTO</a> · © <a href="https://www.openstreetmap.org/about/" target="_blank" rel="noreferrer">OpenStreetMap</a></div></div>;
}
