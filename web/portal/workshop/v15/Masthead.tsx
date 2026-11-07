import {useEffect,useRef,useState,type ReactNode} from 'react';
import {Focus,Plus,Minus} from 'lucide-react';
import {IconButton} from './Controls';
import {Unit} from './Stat';
import type {RouteGeometry,MapControls} from './mapGround';
export type MastheadStat={label:string;value:ReactNode;unit?:string};
export function Masthead({title,kicker,stats,art,kind='map',tone='dark',size='page',long=false,layout='split',subtitle,summary}:{title:string;kicker:string;stats:readonly MastheadStat[];art:ReactNode;size?:'page'|'card';long?:boolean;subtitle?:ReactNode;summary?:ReactNode}&({kind?:'map';layout?:'split';tone?:'dark'|'light'}|{kind:'figure';layout?:'split';tone?:'dark'}|{kind:'figure';layout:'stacked';tone?:'dark'|'light'})) {
 const Title=size==='page'?'h1':'h2';
 if(layout==='stacked')return <section className="v15-masthead" data-kind="figure" data-tone={tone} data-size={size} data-layout="stacked"><div className="v15-figure-heading"><p className="v15-kicker">{kicker}</p><Title className="v15-title" data-long={long}>{title}</Title>{subtitle&&<p className="v15-figure-subtitle">{subtitle}</p>}</div>{summary}<div className="v15-figure-content">{art}</div></section>;
 return <section className="v15-masthead" data-kind={kind} data-tone={tone} data-size={size}><div className="v15-masthead-art">{art}</div><div className="v15-masthead-copy"><div><p className="v15-kicker">{kicker}</p><Title className="v15-title" data-long={long}>{title}</Title></div><dl className="v15-masthead-stats">{stats.map(stat=><div key={stat.label}><dt>{stat.label}</dt><dd>{stat.value}{stat.unit&&<>{stat.unit==='%'?'':' '}<Unit>{stat.unit}</Unit></>}</dd></div>)}</dl></div></section>;
}
export function MapArt({geometry,name,state='ready',controls=false}:{geometry:RouteGeometry;name:string;state?:'ready'|'loading'|'error';controls?:boolean}) {
 const host=useRef<HTMLDivElement>(null),api=useRef<MapControls|null>(null),[status,setStatus]=useState<'ready'|'loading'|'error'>('loading');
 useEffect(()=>{
  if(state!=='ready')return;
  const element=host.current!,controller=new AbortController();let dispose:(()=>void)|undefined,started=false;
  const observer=new IntersectionObserver(entries=>{if(!entries.some(e=>e.isIntersecting)||started)return;started=true;void import('./mapGround').then(async({mountMap})=>{if(controller.signal.aborted)return;const mounted=await mountMap(element,geometry,controller.signal,setStatus);api.current=mounted;dispose=mounted.dispose;}).catch(()=>{if(!controller.signal.aborted)setStatus('error');});},{rootMargin:'200px'});observer.observe(element);
  return()=>{controller.abort();observer.disconnect();dispose?.();api.current=null;};
 },[geometry,state]);
 const display=state==='ready'?status:state;
 return <div className="v15-map" data-controls={controls} role="region" aria-label={`${name} route map`}><div className="v15-map-canvas" ref={host}/>{display!=='ready'&&<span className="v15-map-state" role="status">{display==='loading'?'Loading map':'Map unavailable'}</span>}{controls&&<div className="v15-map-controls"><IconButton size="map" label="Fit climb" disabled={display!=='ready'} onClick={()=>api.current?.fit()}><Focus/></IconButton><IconButton size="map" label="Zoom in" disabled={display!=='ready'} onClick={()=>api.current?.zoomIn()}><Plus/></IconButton><IconButton size="map" label="Zoom out" disabled={display!=='ready'} onClick={()=>api.current?.zoomOut()}><Minus/></IconButton></div>}<span className="v15-map-attribution">© <a href="https://carto.com/about-carto/" target="_blank" rel="noreferrer">CARTO</a> · © <a href="https://www.openstreetmap.org/about/" target="_blank" rel="noreferrer">OpenStreetMap</a></span></div>;
}
