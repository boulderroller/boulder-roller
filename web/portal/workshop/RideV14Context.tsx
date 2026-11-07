import {useLayoutEffect,useRef,useState} from 'react';
import {createPortal} from 'react-dom';
import {V12RideContext} from './V12RideContext';
/** Keep V13's local edits alive across sheets; the copy follows the masthead while the editor remains available from the topbar. */
export function RideV14Context({copyHost,menuHost,visible,bundled,group,owner}:{copyHost:HTMLDivElement|null;menuHost:HTMLDivElement|null;visible:boolean;bundled:boolean;group:boolean;owner:boolean}){
 const fallback=useRef<HTMLDivElement>(null),[target]=useState(()=>document.createElement('div'));
 useLayoutEffect(()=>{(copyHost??fallback.current)?.appendChild(target);return()=>target.remove();},[copyHost,target]);
 return <div className="r14-context-fallback" ref={fallback}>{createPortal(<V12RideContext {...{visible,bundled,group,owner,menuHost}}/>,target)}</div>;
}
