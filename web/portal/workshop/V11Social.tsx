import { useRef, useState } from 'react';
import { Heart, MessageCircle, X } from 'lucide-react';
import type { Scenario } from './scenario';
/** Local interaction prototype; neither a viewer identity nor provider activity is inferred. */
export function V11Social({ ride }: { ride: Scenario['ride'] }) {
  const trigger = useRef<HTMLButtonElement>(null), dialog = useRef<HTMLDialogElement>(null);
  const [kudos,setKudos] = useState(false), [open,setOpen] = useState(false), [text,setText] = useState(''), [comments,setComments] = useState<string[]>([]);
  const close = () => { dialog.current?.close(); setOpen(false); trigger.current?.focus(); };
  return <div className="v11-social"><button aria-label={kudos ? 'Remove kudos' : 'Give kudos'} aria-pressed={kudos} title="Kudos" onClick={() => setKudos(!kudos)}><Heart size={17} fill={kudos ? 'currentColor' : 'none'}/></button><button ref={trigger} aria-label="Comments" aria-haspopup="dialog" aria-expanded={open} onClick={() => { dialog.current?.showModal(); setOpen(true); }}><MessageCircle size={17}/>{comments.length > 0 && <span>{comments.length}</span>}</button>
    <dialog ref={dialog} className="v11-comments-dialog" aria-labelledby="v11-comments-title" onCancel={e => { e.preventDefault(); close(); }} onClick={e => { if (e.target === e.currentTarget) { const r=e.currentTarget.getBoundingClientRect(); if(e.clientX<r.left||e.clientX>r.right||e.clientY<r.top||e.clientY>r.bottom) close(); } }} onKeyDown={e => {
        if (e.key === 'Escape') { e.preventDefault(); close(); }
        if (e.key === 'Tab') {
          const targets = [...e.currentTarget.querySelectorAll<HTMLElement>('button:not(:disabled), textarea')];
          const first = targets[0], last = targets.at(-1);
          if (e.shiftKey && document.activeElement === first) { e.preventDefault(); last?.focus(); }
          else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first?.focus(); }
        }
      }}>
      <header><div className="v11-comments-identity">{ride.rider && <span className="v11-rider-avatar" aria-hidden="true">{ride.rider.displayName.split(/\s+/).slice(0,2).map(s=>s[0]).join('')}</span>}<div><h2 id="v11-comments-title">{ride.title}</h2>{ride.rider && <p>{ride.rider.displayName}</p>}</div></div><button autoFocus aria-label="Close comments" onClick={close}><X size={19}/></button></header>
      <div className="v11-comments-heading">Comments{comments.length > 0 && <span>{comments.length}</span>}</div>
      <div className="v11-comments-body" aria-live="polite">{comments.length ? comments.map((comment,i) => <article key={i}><small>You</small><p>{comment}</p></article>) : <p className="v11-comments-empty">No comments yet.</p>}</div>
      <form onSubmit={e => { e.preventDefault(); if (text.trim()) { setComments(current => [...current, text.trim()]); setText(''); } }}><label htmlFor="v11-comment">Add a comment</label><textarea id="v11-comment" rows={2} value={text} maxLength={1000} onChange={e => setText(e.target.value)}/><div><p>Local preview · Comments stay in this session and are not sent.</p><button type="submit" disabled={!text.trim()}>Add locally</button></div></form>
    </dialog>
  </div>;
}
