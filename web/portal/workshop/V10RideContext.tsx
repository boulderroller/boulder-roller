import { useEffect, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import { LockKeyhole, MoreHorizontal, Users, X } from 'lucide-react';

type Companion={id:string;name:string;initials:string};
const examples:Companion[]=[{id:'example-alex',name:'Alex',initials:'A'},{id:'example-jamie',name:'Jamie',initials:'J'},{id:'example-morgan',name:'Morgan',initials:'M'}];
export function V10RideContext({bundled,group,owner,menuHost,visible}:{bundled:boolean;group:boolean;owner:boolean;menuHost:HTMLElement|null;visible:boolean}) {
 const [description,setDescription]=useState(''),[note,setNote]=useState(''),[editing,setEditing]=useState<'description'|'note'|'riders'|null>(null),[draft,setDraft]=useState(''),[menu,setMenu]=useState(false);
 const [companions,setCompanions]=useState<Companion[]>(()=>bundled&&group?examples.slice(0,2):[]),[search,setSearch]=useState('');
 const dialog=useRef<HTMLDialogElement>(null),trigger=useRef<HTMLButtonElement>(null),menuRef=useRef<HTMLDivElement>(null),input=useRef<HTMLTextAreaElement>(null);
 const closeMenu=(focus=false)=>{setMenu(false);if(focus)trigger.current?.focus();};
 const start=(kind:NonNullable<typeof editing>)=>{if(!owner)return;setMenu(false);setEditing(kind);setDraft(kind==='description'?description:note);setSearch('');};
 const close=()=>{dialog.current?.close();setEditing(null);trigger.current?.focus();};
 useEffect(()=>{if(editing&&owner){dialog.current?.showModal();requestAnimationFrame(()=>{if(editing!=='riders')input.current?.focus();});}},[editing,owner]);
 useEffect(()=>{if(!owner){setMenu(false);setEditing(null);dialog.current?.close();}},[owner]);
 useEffect(()=>{if(!menu)return;menuRef.current?.querySelector<HTMLButtonElement>('button')?.focus();const outside=(e:PointerEvent)=>{if(!menuRef.current?.contains(e.target as Node)&&!trigger.current?.contains(e.target as Node))setMenu(false);};document.addEventListener('pointerdown',outside);return()=>document.removeEventListener('pointerdown',outside);},[menu]);
 return <>
  {visible&&(description||owner&&note||companions.length>0)&&<div className="v10-ride-context">
   {description&&<p className="v10-description has-copy">{description}</p>}
   {owner&&note&&<div className="v10-private-note"><LockKeyhole size={12}/><span>{note}</span></div>}
   {companions.length>0&&<div className="v10-companions"><Users size={15}/><div>{companions.map((p,i)=><span className="v10-companion" key={p.id}><i data-tone={i%3}>{p.initials}</i><span>{p.name}</span></span>)}</div></div>}
  </div>}
  {owner&&menuHost&&createPortal(<div className="v10-ride-options"><button ref={trigger} aria-label="Ride options" aria-haspopup="menu" aria-expanded={menu} onClick={()=>setMenu(v=>!v)} onKeyDown={e=>{if(e.key==='ArrowDown'){e.preventDefault();setMenu(true);}}}><MoreHorizontal size={21}/></button>{menu&&<div ref={menuRef} role="menu" aria-label="Ride options" onBlur={e=>{if(!e.currentTarget.contains(e.relatedTarget))setMenu(false);}} onKeyDown={e=>{if(e.key==='Escape'){e.preventDefault();e.stopPropagation();closeMenu(true);}if(['ArrowDown','ArrowUp','Home','End'].includes(e.key)){e.preventDefault();const items=[...e.currentTarget.querySelectorAll<HTMLButtonElement>('button')],at=items.indexOf(document.activeElement as HTMLButtonElement);items[e.key==='Home'?0:e.key==='End'?items.length-1:(at+(e.key==='ArrowDown'?1:-1)+items.length)%items.length]?.focus();}}}><button role="menuitem" onClick={()=>start('description')}>Edit description</button><button role="menuitem" onClick={()=>start('note')}>Private note</button><button role="menuitem" onClick={()=>start('riders')}>Manage riders</button></div>}</div>,menuHost)}
  {owner&&<dialog ref={dialog} className="v10-context-dialog" aria-labelledby="v10-context-title" onCancel={e=>{e.preventDefault();close();}} onKeyDown={e=>{if(e.key==='Escape'){e.preventDefault();e.stopPropagation();close();}}}>
   <header><h2 id="v10-context-title">{editing==='description'?'Ride description':editing==='note'?'Private note':'Riders on this ride'}</h2><button aria-label="Close ride editor" onClick={close}><X size={18}/></button></header>
   {editing==='riders'?<><label className="sr-only" htmlFor="v10-find-rider">Find a rider</label><input id="v10-find-rider" autoFocus value={search} onChange={e=>setSearch(e.target.value)} placeholder="Find a rider"/><div>{(bundled?examples:[]).filter(p=>p.name.toLowerCase().includes(search.toLowerCase())).map(p=><label className="v10-rider-option" key={p.id}><span className="v10-rider-avatar">{p.initials}</span><span>{p.name}</span><input type="checkbox" checked={companions.some(c=>c.id===p.id)} onChange={e=>setCompanions(current=>e.target.checked?[...current,p]:current.filter(c=>c.id!==p.id))}/></label>)}{!bundled&&<p>No rider directory is connected to this imported ride.</p>}</div><footer><button onClick={close}>Done</button></footer></>:<form onSubmit={e=>{e.preventDefault();if(editing==='description')setDescription(draft.trim());else setNote(draft.trim());close();}}><label className="sr-only" htmlFor="v10-context-copy">{editing==='description'?'Ride description':'Private note'}</label><textarea ref={input} id="v10-context-copy" value={draft} maxLength={1000} rows={5} onChange={e=>setDraft(e.target.value)}/><footer><button type="button" onClick={close}>Cancel</button><button type="submit">Save</button></footer></form>}
  </dialog>}
 </>;
}
