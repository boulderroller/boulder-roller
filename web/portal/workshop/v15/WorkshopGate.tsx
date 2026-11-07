import {useState,type FormEvent,type ReactNode} from 'react';

// A courtesy gate, shared by the workshop and standalone kit previews. No CSS
// or candidate imports: each entry owns its presentation.
const gate=(import.meta.env.VITE_WORKSHOP_GATE_SHA256 as string|undefined)||'';
export function WorkshopGate({children,className='workshop-gate'}:{children:ReactNode;className?:string}){
 const [open,setOpen]=useState(()=>{if(!gate)return true;try{return sessionStorage.getItem('br-workshop-gate')===gate;}catch{return false;}});
 const [value,setValue]=useState(''),[wrong,setWrong]=useState(false);
 if(open)return <>{children}</>;
 const submit=async(event:FormEvent)=>{
  event.preventDefault();
  const bytes=new TextEncoder().encode(value.trim().toLowerCase()),hash=[...new Uint8Array(await crypto.subtle.digest('SHA-256',bytes))].map(byte=>byte.toString(16).padStart(2,'0')).join('');
  if(hash===gate){try{sessionStorage.setItem('br-workshop-gate',gate);}catch{/* Session only. */}setOpen(true);}else setWrong(true);
 };
 return <form className={className} onSubmit={submit}><strong>Boulder Roller workshop</strong><label htmlFor="workshop-gate">Passphrase</label><input id="workshop-gate" type="password" autoComplete="off" autoFocus value={value} onChange={event=>{setValue(event.target.value);setWrong(false);}}/><button type="submit">Open</button>{wrong&&<p role="alert">Not recognized.</p>}</form>;
}
