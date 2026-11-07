import {useEffect,useRef,useState,type ReactNode} from 'react';
import {Activity,ArrowUpRight,ChevronRight,Map as MapIcon,Menu} from 'lucide-react';
import {ClimbV7Link as Link} from './ClimbV7Link';
const mapFallback='http://localhost:4320/?surface=map&variant=map-v2&scenario=area';
/** Standard's frame: a white rail with the Boulder Roller wordmark and the rooms that exist, a breadcrumb topbar with one action, and the sheet.
 *  It never changes between states; the breadcrumb (or the phone title) names where you are, so the rail does not repeat the climb. */
export function ClimbV14Shell({name,exploreHref,feedHref,account,children}:{name?:string;exploreHref:string|null;feedHref:string;account:ReactNode;children:ReactNode}){
 const [open,setOpen]=useState(false),sidebar=useRef<HTMLElement>(null),menu=useRef<HTMLButtonElement>(null),mapHref=exploreHref??mapFallback;
 useEffect(()=>{if(!open)return;const el=sidebar.current;el?.querySelector<HTMLElement>('a,button')?.focus();
  const key=(e:KeyboardEvent)=>{if(e.key==='Escape'){setOpen(false);menu.current?.focus();return;}if(e.key!=='Tab'||!el)return;const items=[...el.querySelectorAll<HTMLElement>('a,button')];if(!items.length)return;const first=items[0],last=items.at(-1)!;if(e.shiftKey&&document.activeElement===first){e.preventDefault();last.focus();}else if(!e.shiftKey&&document.activeElement===last){e.preventDefault();first.focus();}};
  document.addEventListener('keydown',key);return()=>document.removeEventListener('keydown',key);},[open]);
 return <div className="c14-shell" data-menu={open}>
  <aside className="c14-sidebar" ref={sidebar} aria-label="Boulder Roller" onClick={e=>{if((e.target as HTMLElement).closest('a'))setOpen(false);}}>
   <div className="c14-brand"><Link href={feedHref}>Boulder Roller</Link></div>
   <nav aria-label="Main navigation"><Link className="c14-nav-item" href={feedHref}><Activity aria-hidden="true"/>Feed</Link><a className="c14-nav-item" href={mapHref} target="_top" data-active="true"><MapIcon aria-hidden="true"/>Map</a></nav>
   {account&&<div className="c14-sidebar-foot">{account}</div>}
  </aside>
  {open&&<button className="c14-scrim" aria-label="Close menu" onClick={()=>{setOpen(false);menu.current?.focus();}}/>}
  <div className="c14-frame-main">
   <header className="c14-topbar">
    <button ref={menu} className="c14-menu" aria-label="Menu" aria-expanded={open} onClick={()=>setOpen(!open)}><Menu/></button>
    <nav className="c14-crumbs" aria-label="Breadcrumb"><ol><li><a href={mapHref} target="_top">Map</a></li>{name&&<><li aria-hidden="true"><ChevronRight/></li><li><span aria-current="page">{name}</span></li></>}</ol></nav>
    <span className="c14-phone-title">{name??'Map'}</span>
    {exploreHref&&<a className="c14-button c14-explore" href={exploreHref} target="_top">Explore climbs</a>}
   </header>
   {children}
  </div>
 </div>;
}
export function ClimbV14SignIn({onClick}:{onClick:()=>void}){return <button className="c14-account" onClick={onClick}><span>Sign in</span><ArrowUpRight aria-hidden="true"/></button>;}
