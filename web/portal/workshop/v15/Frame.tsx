import {Fragment,useEffect,useId,useRef,useState,type ReactNode} from 'react';
import {Activity,Bell,Map as MapIcon,Menu,Settings,Upload,User,X} from 'lucide-react';
import {Avatar} from './Avatar';
import {Medal} from './marks';
import {destinationHref,youItems} from './destinations';
export type FrameSection='feed'|'map'|'you'|'upload'|'notifications'|'settings';
export type RailItem={id:string;label:string;href:string;current?:boolean;rank?:number};
export type Crumb={label:string;href?:string};
export function Frame({section,items={},crumbs,phoneTitle,action,account,footer,children}:{section:FrameSection;items?:Partial<Record<FrameSection,RailItem[]>>;crumbs:Crumb[];phoneTitle:string;action?:ReactNode;account?:{name:string;href:string};footer?:ReactNode;children:ReactNode}) {
 const [open,setOpen]=useState(false),menu=useRef<HTMLButtonElement>(null),rail=useRef<HTMLElement>(null),body=useRef<HTMLDivElement>(null),railId=useId();
 const close=()=>{setOpen(false);menu.current?.focus();};
 useEffect(()=>{
  if(!open)return;
  const element=rail.current!,content=body.current!,previous=document.body.style.overflow;
  document.body.style.overflow='hidden';content.inert=true;element.querySelector<HTMLElement>('a,button')?.focus();
  const key=(e:KeyboardEvent)=>{if(e.key==='Escape'){e.preventDefault();close();}if(e.key!=='Tab')return;const nodes=[...element.querySelectorAll<HTMLElement>('a[href],button')].filter(n=>n.getClientRects().length),first=nodes[0],last=nodes.at(-1);if(e.shiftKey&&document.activeElement===first){e.preventDefault();last?.focus();}else if(!e.shiftKey&&document.activeElement===last){e.preventDefault();first?.focus();}};
  const wide=matchMedia('(min-width:701px)'),resize=()=>{if(wide.matches)setOpen(false);};
  document.addEventListener('keydown',key);wide.addEventListener('change',resize);
  return()=>{content.inert=false;document.body.style.overflow=previous;if(menu.current?.isConnected)menu.current.focus();document.removeEventListener('keydown',key);wide.removeEventListener('change',resize);};
 },[open]);
 const main=[{id:'feed',label:'Feed',icon:Activity,href:destinationHref('feed')},{id:'map',label:'Map',icon:MapIcon,href:destinationHref('map')},{id:'you',label:'You',icon:User,href:destinationHref('profile')}] as const;
 const groupItems=(id:'feed'|'map'|'you'):RailItem[]=>items[id]??(id==='you'?youItems:[]);
 const foot=[{id:'upload',label:'Upload',icon:Upload},{id:'notifications',label:'Notifications',icon:Bell},{id:'settings',label:'Settings',icon:Settings}] as const;
 return <div className="v15-shell" data-menu={open}>
  <div className="v15-band"><a className="v15-wordmark" href={destinationHref('feed')} target="_top">Boulder Roller</a>{account&&<a className="v15-account" href={account.href} target="_top"><Avatar name={account.name} tone="dark"/><span>{account.name}</span></a>}</div>
  <div className="v15-console"><aside className="v15-rail" id={railId} ref={rail} aria-label="Boulder Roller" role={open?'dialog':undefined} aria-modal={open||undefined}>
   <button className="v15-menu-close" aria-label="Close menu" onClick={close}><X/></button>
   <nav className="v15-navigation" aria-label="Main navigation">{main.map(group=><Fragment key={group.id}><a className="v15-nav-item" data-open={section===group.id} href={group.href} target="_top"><group.icon aria-hidden="true"/>{group.label}</a>{section===group.id&&<ul className="v15-nav-group">{groupItems(group.id).map(item=><li key={item.id}><a className="v15-nav-sub" href={item.href} target="_top" aria-current={item.current?'page':undefined}><span>{item.label}</span>{item.rank!==undefined&&<Medal rank={item.rank} size={20}/>}</a></li>)}</ul>}</Fragment>)}</nav>
   <nav className="v15-navigation-foot" aria-label="Account">{foot.map(item=><a key={item.id} className="v15-nav-item" href={destinationHref(item.id)} target="_top" aria-current={section===item.id?'page':undefined}><item.icon aria-hidden="true"/>{item.label}</a>)}</nav>
  </aside>{open&&<div className="v15-scrim" onClick={close} aria-hidden="true"/>}
  <div className="v15-main" ref={body}><header className="v15-topbar"><button ref={menu} className="v15-menu" aria-label="Menu" aria-controls={railId} aria-expanded={open} onClick={()=>setOpen(!open)}><Menu/></button><nav className="v15-crumbs" aria-label="Breadcrumb"><ol>{crumbs.map((crumb,i)=><Fragment key={i}>{i>0&&<li aria-hidden="true">/</li>}<li>{crumb.href?<a href={crumb.href} target="_top" aria-current={i===crumbs.length-1?'page':undefined}>{crumb.label}</a>:<span aria-current={i===crumbs.length-1?'page':undefined}>{crumb.label}</span>}</li></Fragment>)}</ol></nav><span className="v15-phone-title">{phoneTitle}</span>{action&&<div className="v15-actions">{action}</div>}</header>
   <main className="v15-sheet">{children}{footer&&<footer className="v15-footer">{footer}</footer>}</main>
  </div></div>
 </div>;
}
