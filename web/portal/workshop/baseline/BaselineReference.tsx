import {useState} from 'react';
import {X} from 'lucide-react';
import {stravaReferencesFor,referenceTitle,referenceContext} from './referenceModel';
const images=import.meta.glob('./references/*.png',{eager:true,query:'?url',import:'default'}) as Record<string,string>;
export const historicalImage=(file:string)=>images['./references/'+file];
export function BaselineReference({room,squint,onClose}:{room:string;squint:boolean;onClose:()=>void}){
 const captures=stravaReferencesFor(room),[index,setIndex]=useState(0),capture=captures[index]??captures[0];
 if(!capture)return null;
 return <aside className="reference-panel baseline-reference" aria-label="Strava reference">
  <div className="reference-heading"><strong>Strava · {referenceTitle(room)}</strong><button aria-label="Close reference" onClick={onClose}><X size={16}/></button></div>
  <div className="view-switch baseline-reference-tabs" role="group" aria-label="Strava reference section">{captures.map((c,i)=><button key={c.file} aria-pressed={i===index} onClick={()=>setIndex(i)}>{c.title}</button>)}</div>
  <figure className="reference-frame"><figcaption>Historical Strava · 9 Sep 2026 · {capture.viewportWidth} px {capture.viewportWidth===430?'phone':'desktop'} source</figcaption><div className="reference-image" data-squint={squint}><a href={historicalImage(capture.file)} target="_blank" rel="noreferrer"><img src={historicalImage(capture.file)} width={capture.pixelWidth} height={capture.pixelHeight} alt={`Strava ${referenceTitle(room)} · ${capture.title} · retained ${capture.viewportWidth} px capture`}/></a></div></figure>
  <p>Retained {capture.viewportWidth===430?'phone':'desktop'} capture · 9 Sep 2026 · {capture.viewportWidth} px source viewport, captured at 2×.<br/>{capture.viewer}. {capture.note} {referenceContext(room)}<br/><a href={capture.url} target="_blank" rel="noreferrer">Open Strava source page</a> · <a href={historicalImage(capture.file)} target="_blank" rel="noreferrer">Open full capture</a></p>
 </aside>;
}
