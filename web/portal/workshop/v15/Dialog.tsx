import {useEffect,useId,useRef,type ReactNode} from 'react';
import {X} from 'lucide-react';
import {IconButton} from './Controls';
export type DialogWidth='compact'|'wide';
export function Dialog({open,title,width='compact',onClose,children}:{open:boolean;title:string;width?:DialogWidth;onClose:()=>void;children:ReactNode}) {
 const ref=useRef<HTMLDialogElement>(null),id=useId();
 useEffect(()=>{
  if(!open)return;
  const trigger=document.activeElement as HTMLElement|null,dialog=ref.current!,overflow=document.body.style.overflow;
  document.body.style.overflow='hidden';dialog.showModal();
  return()=>{dialog.close();document.body.style.overflow=overflow;trigger?.focus();};
 },[open]);
 return <dialog ref={ref} className="v15-dialog" data-width={width} aria-labelledby={id} onCancel={event=>{event.preventDefault();onClose();}} onClick={event=>{if(event.target===event.currentTarget){const r=event.currentTarget.getBoundingClientRect();if(event.clientX<r.left||event.clientX>r.right||event.clientY<r.top||event.clientY>r.bottom)onClose();}}}>
  <header className="v15-dialog-head"><h2 id={id}>{title}</h2><IconButton label="Close" onClick={onClose}><X/></IconButton></header><div className="v15-dialog-content">{children}</div>
 </dialog>;
}
