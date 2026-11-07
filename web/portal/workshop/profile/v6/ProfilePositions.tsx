import {ArrowUpRight,ArrowLeft} from 'lucide-react';
import {V6_GEOGRAPHY,type OwnerEconomy} from './profileV6Model';
import {amount} from './ClimbStanding';

export function ProfilePositions({economy,selected,onSelect,onNavigate,onBack}:{economy:OwnerEconomy|null;selected:string|null;onSelect:(id:string)=>void;onNavigate:(href:string)=>void;onBack:()=>void}){
 return <section className="p6-portfolio">
  <header className="p6-section-heading"><h2 tabIndex={-1}>Portfolio</h2><button onClick={onBack}><ArrowLeft size={13}/>Overview</button></header>
  {economy&&economy.positions.length>0?<>
   <div className="p6-position-heading"><h3>My positions</h3><span>As of {new Intl.DateTimeFormat('en-US',{month:'short',day:'numeric',timeZone:'UTC'}).format(new Date(economy.asOf))}</span></div>
   <div className="p6-position-layout"><div className="p6-position-picker" role="group" aria-label="Climb positions">{economy.positions.map(p=><button key={p.climbId} aria-pressed={selected===p.climbId} onClick={()=>onSelect(p.climbId)}>{V6_GEOGRAPHY.find(c=>c.id===p.climbId)!.name}<span>{amount(p.calDeposited)} CAL deposited</span></button>)}</div>
    {(()=>{const position=economy.positions.find(p=>p.climbId===selected)??economy.positions[0],hill=V6_GEOGRAPHY.find(c=>c.id===position.climbId)!;return <section className="p6-position-detail" aria-label={`My position on ${hill.name}`}><h3>{hill.name}</h3><dl><div><dt>CAL deposited</dt><dd>{amount(position.calDeposited)} <small>CAL</small></dd></div>{position.dung&&<div><dt>DUNG {position.dung.state}</dt><dd>{amount(position.dung.amount)} <small>DUNG</small></dd></div>}</dl><a href={`/?surface=map&variant=map-v7&scenario=wises&viewer=visitor&climb=${hill.id}&origin=${hill.id}`} onClick={e=>{if(e.metaKey||e.ctrlKey||e.shiftKey||e.altKey)return;e.preventDefault();onNavigate(e.currentTarget.getAttribute('href')!);}}>Open climb<ArrowUpRight size={14}/></a></section>;})()}
   </div>
  </>:<p className="p6-empty">No positions are supplied for this rider.</p>}
  <div className="p6-balance-absence"><h3>Balance unavailable</h3><p>No balance is supplied for this rider.</p></div>
 </section>;
}
