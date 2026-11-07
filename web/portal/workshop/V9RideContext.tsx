import { useRef, useState } from 'react';
import { LockKeyhole, Plus, Users, X } from 'lucide-react';

export type V9Companion={id:string;name:string;initials:string;matched?:boolean};
const examples:V9Companion[]=[{id:'example-alex',name:'Alex',initials:'A'},{id:'example-jamie',name:'Jamie',initials:'J'},{id:'example-morgan',name:'Morgan',initials:'M'}];
export function V9RideContext({bundled,group}:{bundled:boolean;group:boolean}) {
 const [description,setDescription]=useState(''),[note,setNote]=useState(''),[editing,setEditing]=useState<'description'|'note'|null>(null),[draft,setDraft]=useState('');
 const [companions,setCompanions]=useState<V9Companion[]>(()=>bundled&&group?examples.slice(0,2):[]),[search,setSearch]=useState('');
 const dialog=useRef<HTMLDialogElement>(null),trigger=useRef<HTMLButtonElement>(null),descriptionTrigger=useRef<HTMLButtonElement>(null),noteTrigger=useRef<HTMLButtonElement>(null),input=useRef<HTMLTextAreaElement>(null);
 const start=(kind:'description'|'note')=>{setEditing(kind);setDraft(kind==='description'?description:note);requestAnimationFrame(()=>input.current?.focus());};
 const finish=(save:boolean)=>{if(save){if(editing==='description')setDescription(draft.trim());else setNote(draft.trim());}setEditing(null);requestAnimationFrame(()=>(editing==='description'?descriptionTrigger:noteTrigger).current?.focus());};
 const close=()=>{dialog.current?.close();trigger.current?.focus();};
 return <div className="v9-ride-context">
  {editing ? <form className="v9-context-editor" onSubmit={e=>{e.preventDefault();finish(true);}} onKeyDown={e=>{if(e.key==='Escape'){e.preventDefault();finish(false);}}}><label htmlFor="v9-context-copy">{editing==='description'?'Ride description':'Private note'}</label><textarea ref={input} id="v9-context-copy" value={draft} maxLength={1000} rows={3} onChange={e=>setDraft(e.target.value)}/><div><button type="submit">Save</button><button type="button" onClick={()=>finish(false)}>Cancel</button></div></form> : <>
   <button ref={descriptionTrigger} className={`v9-description ${description?'has-copy':''}`} onClick={()=>start('description')} aria-label={description?'Edit ride description':'Add a ride description'}>{description||'Add a description'}</button>
   <button ref={noteTrigger} className="v9-private-note" onClick={()=>start('note')} aria-label={note?'Edit private note':'Add a private note'}><LockKeyhole size={12}/><span>{note||'Private note'}</span></button>
  </>}
  <div className="v9-companions"><Users size={15}/><div>{companions.map((person,i)=><span className="v9-companion" key={person.id} title={`${person.name}${person.matched?' · Matched ride':''}`}><i data-tone={i%3}>{person.initials}</i><span>{person.name}</span></span>)}</div><button ref={trigger} aria-label="Add or edit riders" aria-haspopup="dialog" onClick={()=>dialog.current?.showModal()}><Plus size={13}/>{companions.length?'':'Add riders'}</button></div>
  <dialog ref={dialog} className="v9-context-dialog" aria-labelledby="v9-riders-title" onCancel={e=>{e.preventDefault();close();}} onKeyDown={e=>{if(e.key==='Escape'){e.preventDefault();close();}if(e.key==='Tab'){const targets=[...e.currentTarget.querySelectorAll<HTMLElement>('button,input')];const first=targets[0],last=targets.at(-1);if(e.shiftKey&&document.activeElement===first){e.preventDefault();last?.focus();}else if(!e.shiftKey&&document.activeElement===last){e.preventDefault();first?.focus();}}}}><header><h2 id="v9-riders-title">Riders on this ride</h2><button aria-label="Close riders" onClick={close}><X size={18}/></button></header><label className="sr-only" htmlFor="v9-find-rider">Find a rider</label><input id="v9-find-rider" autoFocus value={search} onChange={e=>setSearch(e.target.value)} placeholder="Find a rider"/>
   <div>{(bundled?examples:[]).filter(p=>p.name.toLowerCase().includes(search.toLowerCase())).map(p=><label className="v9-rider-option" key={p.id}><span className="v9-rider-avatar">{p.initials}</span><span>{p.name}</span><input type="checkbox" checked={companions.some(c=>c.id===p.id)} onChange={e=>setCompanions(current=>e.target.checked?[...current,p]:current.filter(c=>c.id!==p.id))}/></label>)}{!bundled&&<p>No rider directory is connected to this imported ride.</p>}</div><footer><button onClick={close}>Done</button></footer>
  </dialog>
 </div>;
}
