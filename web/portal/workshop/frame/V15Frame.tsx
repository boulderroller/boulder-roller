import {Fragment,useEffect,useRef,useState,type MouseEventHandler,type ReactNode} from 'react';
import {Activity,Bell,Map as MapIcon,Menu,Settings,Upload,User} from 'lucide-react';
import {destinationHref,youItems as defaultYouItems} from './destinations';
import '../climb/climb-v15.css';
import './v15-frame.css';
export type V15Section='feed'|'map'|'you'|'upload'|'notifications'|'settings';
export type V15Item={id:string;label:string;href?:string;onClick?:MouseEventHandler<HTMLAnchorElement>;onSelect?:()=>void;current?:boolean;meta?:ReactNode};
export type V15Crumb={label:string;href?:string};
type Props={section:V15Section;hrefs?:{feed?:string;map?:string;you?:string;wordmark?:string};feedItems?:V15Item[];mapItems?:V15Item[];youItems?:V15Item[];crumbs:V15Crumb[];phoneTitle:string;action?:ReactNode;account:ReactNode;children:ReactNode};
function Items({items,label,onSelect}:{items:V15Item[];label:string;onSelect:()=>void}){
 return <ul className="c15-nav-group" aria-label={label}>{items.map(item=>{
  const content=<><span className="c15-nav-sub-name">{item.label}</span>{item.meta!==undefined&&<span className="c15-nav-sub-place">{item.meta}</span>}</>;
  return <li key={item.id}>{item.href?<a className="c15-nav-sub" href={item.href} onClick={item.onClick} target="_top" aria-current={item.current?'page':undefined}>{content}</a>:item.onSelect?<button className="c15-nav-sub" aria-current={item.current?'page':undefined} onClick={()=>{item.onSelect!();onSelect();}}>{content}</button>:<span className="c15-nav-sub">{content}</span>}</li>;
 })}</ul>;
}
/** V15's band, rail, breadcrumb and menu sheet. Room content supplies the facts and actions. */
export function V15Frame({section,hrefs={},feedItems=[],mapItems=[],youItems=defaultYouItems,crumbs,phoneTitle,action,account,children}:Props){
 const [open,setOpen]=useState(false),sidebar=useRef<HTMLElement>(null),menu=useRef<HTMLButtonElement>(null);
 const close=()=>{setOpen(false);menu.current?.focus();};
 useEffect(()=>{if(!open)return;const el=sidebar.current;el?.querySelector<HTMLElement>('a,button')?.focus();
  const key=(e:KeyboardEvent)=>{if(e.key==='Escape'){setOpen(false);menu.current?.focus();return;}if(e.key!=='Tab'||!el)return;const items=[...el.querySelectorAll<HTMLElement>('a[href],button:not(:disabled)')];if(!items.length)return;const first=items[0],last=items.at(-1)!;if(e.shiftKey&&document.activeElement===first){e.preventDefault();last.focus();}else if(!e.shiftKey&&document.activeElement===last){e.preventDefault();first.focus();}};
  document.addEventListener('keydown',key);return()=>document.removeEventListener('keydown',key);},[open]);
 const groups=[{id:'feed',label:'Feed',icon:Activity,href:hrefs.feed??destinationHref('feed'),items:feedItems},{id:'map',label:'Map',icon:MapIcon,href:hrefs.map??destinationHref('map'),items:mapItems},{id:'you',label:'You',icon:User,href:hrefs.you??destinationHref('profile'),items:section==='you'?youItems:[]}];
 return <div className="c15-shell" data-menu={open}>
  <div className="c15-band"><a className="c15-wordmark" href={hrefs.wordmark??destinationHref('feed')} target="_top">Boulder Roller</a>{account&&<div className="c15-band-account">{account}</div>}</div>
  <div className="c15-console">
   <aside className="c15-sidebar" ref={sidebar} aria-label="Boulder Roller" onClick={e=>{if((e.target as HTMLElement).closest('a'))setOpen(false);}}>
    <nav className="v15-main-nav" aria-label="Main navigation">{groups.map(group=><Fragment key={group.id}><a className="c15-nav-item" href={group.href} target="_top" data-open={section===group.id?'true':undefined}><group.icon aria-hidden="true"/>{group.label}</a>{group.items.length>0&&<Items items={group.items} label={group.label} onSelect={close}/>}</Fragment>)}</nav>
    <nav className="v15-rail-foot">{([{id:'upload',label:'Upload',icon:Upload},{id:'notifications',label:'Notifications',icon:Bell},{id:'settings',label:'Settings',icon:Settings}] as const).map(item=><a className="c15-nav-item" key={item.id} href={destinationHref(item.id)} target="_top" data-open={section===item.id?'true':undefined} aria-current={section===item.id?'page':undefined}><item.icon aria-hidden="true"/>{item.label}</a>)}</nav>
   </aside>
   {open&&<button className="c15-scrim" aria-label="Close menu" onClick={close}/>}
   <div className="c15-frame-main">
    <header className="c15-topbar"><button ref={menu} className="c15-menu" aria-label="Menu" aria-expanded={open} onClick={()=>setOpen(!open)}><Menu aria-hidden="true"/></button>
     <nav className="c15-crumbs" aria-label="Breadcrumb"><ol>{crumbs.map((crumb,i)=><Fragment key={`${crumb.label}:${i}`}>{i>0&&<li aria-hidden="true">/</li>}<li>{crumb.href?<a href={crumb.href} target="_top" aria-current={i===crumbs.length-1?'page':undefined}>{crumb.label}</a>:<span aria-current={i===crumbs.length-1?'page':undefined}>{crumb.label}</span>}</li></Fragment>)}</ol></nav>
     <span className="c15-phone-title">{phoneTitle}</span>{action&&<div className="v15-topbar-action">{action}</div>}
    </header>
    <main className="c15-sheet">{children}</main>
   </div>
  </div>
 </div>;
}
