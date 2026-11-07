import {useEffect,useRef,useState,type MouseEvent,type ReactNode} from 'react';
import {Activity,Map as MapIcon,Menu} from 'lucide-react';
import {ordinal} from './climb/climbV7Model';
import type {RideV14Mode} from './rideV14Navigation';
type RailClimb={climbId:string;name:string;number:number;href:string|null;rank?:number};
/** Match V13's parent workshop navigation while retaining ordinary modified-click anchors. */
function visit(e:MouseEvent<HTMLAnchorElement>){if(e.button||e.metaKey||e.ctrlKey||e.shiftKey||e.altKey)return;e.preventDefault();window.parent.postMessage({type:'workshop-open-climb',href:e.currentTarget.getAttribute('href')},location.origin);}
function feedVisit(e:MouseEvent<HTMLAnchorElement>){if(e.button||e.metaKey||e.ctrlKey||e.shiftKey||e.altKey)return;e.preventDefault();window.parent.postMessage({type:'workshop-open-feed',href:e.currentTarget.getAttribute('href')},location.origin);}
const mapFallback='http://localhost:4320/?surface=map&variant=map-v2&scenario=area';
/** Boulder Roller's band frames the console as Standard's banner frames its app: the wordmark and the account on the band, then one light console
 *  holding the rail, the breadcrumb topbar and the sheet. The rail does work: Map opens onto the climbs the data holds, each with the rider's place
 *  as plain text (the marks stay with the standing and the board). The phone topbar names the section, as the breadcrumb does. */
export function RideV14Shell({name,exploreHref,feedHref,account,climbs,views,mode,onView,social,options,children}:{name?:string;exploreHref:string|null;feedHref:string;account:ReactNode;climbs:RailClimb[];views:{mode:RideV14Mode;label:string}[];mode:RideV14Mode;onView:(mode:RideV14Mode)=>void;social:ReactNode;options:ReactNode;children:ReactNode}){
 const [open,setOpen]=useState(false),sidebar=useRef<HTMLElement>(null),menu=useRef<HTMLButtonElement>(null),mapHref=exploreHref??mapFallback;
 useEffect(()=>{if(!open)return;const el=sidebar.current;el?.querySelector<HTMLElement>('a,button')?.focus();
  const key=(e:KeyboardEvent)=>{if(e.key==='Escape'){setOpen(false);menu.current?.focus();return;}if(e.key!=='Tab'||!el)return;const items=[...el.querySelectorAll<HTMLElement>('a,button')];if(!items.length)return;const first=items[0],last=items.at(-1)!;if(e.shiftKey&&document.activeElement===first){e.preventDefault();last.focus();}else if(!e.shiftKey&&document.activeElement===last){e.preventDefault();first.focus();}};
  document.addEventListener('keydown',key);return()=>document.removeEventListener('keydown',key);},[open]);
 return <div className="c15-shell" data-menu={open}>
  <div className="c15-band"><a target="_top" onClick={feedVisit} className="c15-wordmark" href={feedHref}>Boulder Roller</a>{account&&<div className="c15-band-account">{account}</div>}</div>
  <div className="c15-console">
   <aside className="c15-sidebar" ref={sidebar} aria-label="Boulder Roller" onClick={e=>{if((e.target as HTMLElement).closest('a'))setOpen(false);}}>
    <nav aria-label="Main navigation">
     <a target="_top" onClick={feedVisit} className="c15-nav-item" data-open="true" href={feedHref}><Activity aria-hidden="true"/>Feed</a>
     {views.length>0&&<ul className="c15-nav-group" aria-label="Ride sections">{views.map(v=><li key={v.mode}><button className="c15-nav-sub" aria-current={mode===v.mode?'page':undefined} onClick={()=>{onView(v.mode);setOpen(false);}}>{v.label}</button></li>)}</ul>}
     <a className="c15-nav-item" href={mapHref} target="_top" data-open="true"><MapIcon aria-hidden="true"/>Map</a>
     {climbs.length>0&&<ul className="c15-nav-group" aria-label="Climbs">{climbs.map(c=><li key={c.climbId}>{c.href?<a className="c15-nav-sub" href={c.href!} target="_top" onClick={visit}><span className="r14-rail-number">{c.number}</span><span className="c15-nav-sub-name">{c.name}</span>{c.rank!==undefined&&<span className="c15-nav-sub-place">{ordinal(c.rank)}</span>}</a>:<span className="c15-nav-sub"><span className="r14-rail-number">{c.number}</span><span className="c15-nav-sub-name">{c.name}</span></span>}</li>)}</ul>}
    </nav>
   </aside>
   {open&&<button className="c15-scrim" aria-label="Close menu" onClick={()=>{setOpen(false);menu.current?.focus();}}/>}
   <div className="c15-frame-main">
    <header className="c15-topbar">
     <button ref={menu} className="c15-menu" aria-label="Menu" aria-expanded={open} onClick={()=>setOpen(!open)}><Menu/></button>
     <nav className="c15-crumbs" aria-label="Breadcrumb"><ol><li><a target="_top" onClick={feedVisit} href={feedHref}>Feed</a></li>{name&&<><li aria-hidden="true">/</li><li><span aria-current="page">{name}</span></li></>}</ol></nav>
     <span className="c15-phone-title">Feed</span>
     <div className="r14-topbar-actions">{social}{options}</div>
    </header>
    {children}
   </div>
  </div>
 </div>;
}
