import {useState} from 'react';
import {X} from 'lucide-react';
import overview from '../references/strava-climb.png';
import history from './references/strava-climb-history.png';
import leaderboard from './references/strava-climb-leaderboard.png';
const captures=[{label:'Overview',image:overview},{label:'History',image:history},{label:'Leaderboard',image:leaderboard}];
export function ClimbV5Reference({squint,onClose}:{squint:boolean;onClose:()=>void}){
 const [index,setIndex]=useState(0),capture=captures[index];
 return <aside className="reference-panel"><div className="reference-heading"><strong>Strava · Climb</strong><button aria-label="Close reference" onClick={onClose}><X size={16}/></button></div><div className="c5-reference-tabs" role="group" aria-label="Strava reference section">{captures.map((c,i)=><button key={c.label} aria-pressed={i===index} onClick={()=>setIndex(i)}>{c.label}</button>)}</div><figure className="reference-frame"><div className="reference-image" data-squint={squint}><a href={capture.image} target="_blank" rel="noreferrer"><img src={capture.image} alt={`Strava Manayunk Wall · ${capture.label.toLowerCase()} retained desktop capture`}/></a></div></figure><p>Retained desktop capture · 9 Sep 2026 · different climb data. History and some filters show the free-account subscription state.</p></aside>;
}
