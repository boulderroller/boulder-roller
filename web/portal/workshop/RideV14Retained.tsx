import {useLayoutEffect,useRef,useState,type ReactNode} from 'react';
import {createPortal} from 'react-dom';
/** A style boundary for the retained rooms: V15's element resets and icon rules must never restyle V13's components. */
export function RideV14Retained({children}:{children:ReactNode}){
 const host=useRef<HTMLDivElement>(null),[mount,setMount]=useState<HTMLDivElement|null>(null);
 useLayoutEffect(()=>{
  const node=host.current;if(!node)return;const root=node.shadowRoot??node.attachShadow({mode:'open'}),style=document.createElement('style');
  const rules=(sheet:CSSStyleSheet):string=>{try{return Array.from(sheet.cssRules).map(rule=>rule instanceof CSSImportRule&&rule.styleSheet?rules(rule.styleSheet):rule.cssText).join('\n');}catch{return '';}};
  style.textContent=Array.from(document.styleSheets).map(rules).join('\n');
  const content=document.createElement('div');content.className='rider-preview candidate-v13';content.style.minHeight='0';root.append(style,content);setMount(content);
  // Retained controls use document.activeElement; within this boundary the
  // document sees the host, so restore their original focus behavior here.
  const restorePowerFocus=(event:Event)=>{
   const button=(event.target as Element)?.closest('button'),room=button?.closest('.v12-power-room');
   if(!room)return;
   if(event.type==='keydown'&&(event as KeyboardEvent).key!=='Escape')return;
   if(event.type==='click'&&!['Show all power','Show all'].includes(button?.textContent?.trim()??''))return;
   requestAnimationFrame(()=>room.querySelector<SVGSVGElement>('svg[role="slider"]')?.focus());
  };
  root.addEventListener('click',restorePowerFocus,true);root.addEventListener('keydown',restorePowerFocus,true);
  return()=>{root.removeEventListener('click',restorePowerFocus,true);root.removeEventListener('keydown',restorePowerFocus,true);style.remove();content.remove();};
 },[]);
 return <div className="r14-retained" ref={host}>{mount&&createPortal(children,mount)}</div>;
}
