import { useRef, useState } from 'react';
import { Heart, MessageCircle, X } from 'lucide-react';
/** Explicit local interaction prototype: no social provider, viewer identity, or counts are inferred. */
export function V6Social() {
 const commentsButton=useRef<HTMLButtonElement>(null);
 const close=()=>{setOpen(false);commentsButton.current?.focus();};
 const [kudos,setKudos]=useState(false),[open,setOpen]=useState(false),[text,setText]=useState(''),[comments,setComments]=useState<string[]>([]);
 return <div className="v6-social"><small>Local preview</small><button aria-label={kudos?'Remove local kudos':'Give local kudos'} aria-pressed={kudos} title="Local kudos preview" onClick={()=>setKudos(!kudos)}><Heart size={17} fill={kudos?'currentColor':'none'}/></button><button ref={commentsButton} aria-label="Comments" aria-expanded={open} onClick={()=>setOpen(!open)}><MessageCircle size={17}/>{comments.length>0&&<span>{comments.length}</span>}</button>
 {open&&<div className="v6-comment-panel" onKeyDown={e=>{if(e.key==='Escape'){e.preventDefault();close();}}}><header><strong>Comments</strong><button aria-label="Close comments" onClick={close}><X size={16}/></button></header><p>Local workshop preview. Comments stay in this session and are not sent.</p>{comments.map((comment,i)=><blockquote key={i}>{comment}</blockquote>)}<form onSubmit={e=>{e.preventDefault();if(text.trim()){setComments([...comments,text.trim()]);setText('');}}}><label htmlFor="v6-comment">Add a comment</label><textarea id="v6-comment" rows={3} value={text} maxLength={1000} onChange={e=>setText(e.target.value)}/><button type="submit" disabled={!text.trim()}>Add locally</button></form></div>}
 </div>;
}
