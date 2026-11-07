import {useMemo,useState} from 'react';
import {ArrowUpRight,Check,ChevronDown,ChevronRight} from 'lucide-react';
import {effortDate} from './climbV5Model';
import {amount,allocationKeys,allocationLabels,weekTotal,type ClimbV7Economy} from './climbV7Model';
import type {ClimbViewer} from './climbModel';
import {ClimbV8Action,type VaultAction} from './ClimbV8Action';

function Figure({value,places=3}:{value:number;places?:number}){
 const [whole,fraction]=value.toLocaleString('en-US',{minimumFractionDigits:places,maximumFractionDigits:9}).split('.');
 return <span className="c8-figure" title={value.toLocaleString('en-US',{maximumFractionDigits:9})}>{whole}{fraction&&<span>.{fraction}</span>}</span>;
}
export function ClimbV8VaultSummary({economy}:{economy:ClimbV7Economy}){
 return <section className="c7-vault-summary c8-vault-summary"><header><h2>Vault</h2><a href="#c8-vault" aria-label="View Vault"><ArrowUpRight size={16}/></a></header><div className="c7-summary-primary"><span>Lifetime CAL tribute</span><strong><Figure value={economy.lifetimeTributeCal} places={2}/><small>CAL</small></strong></div><dl><div><dt>CAL deposited</dt><dd>{amount(economy.depositedPrincipalCal)}</dd></div></dl><a className="c7-summary-link" href="#c8-vault">DUNG history & position<ChevronRight size={14}/></a></section>;
}
export function ClimbV8Vault({economy,viewer,name,onSignIn}:{economy:ClimbV7Economy;viewer:ClimbViewer;name:string;onSignIn:()=>void}){
 const weeks=useMemo(()=>[...economy.weeks].sort((a,b)=>Date.parse(b.end)-Date.parse(a.end)),[economy.weeks]);
 const [selected,setSelected]=useState<string|null>(weeks[0].id),[action,setAction]=useState<VaultAction|null>(null);
 const position=viewer==='rider'?economy.position:undefined,account=viewer==='rider'?economy.account:undefined;
 return <section className="c8-vault" id="c8-vault">
  <header className="c7-section-heading"><h2>Vault</h2><span>As of {effortDate(economy.asOf)}</span></header>
  <div className="c8-vault-layout">
   <section className="c8-history" aria-label="DUNG settlement history">
    <header className="c8-ledger-labels"><h3>DUNG history</h3><span>DUNG allocated</span></header>
    <div className="c8-weeks">{weeks.map(w=>{const open=selected===w.id;return <section key={w.id} className="c8-week" data-open={open}>
     <button className="c8-week-heading" aria-expanded={open} aria-controls={`c8-week-${encodeURIComponent(w.id)}`} onClick={()=>setSelected(open?null:w.id)}>
      <span className="c8-week-date"><i aria-hidden="true"/><time dateTime={w.start}>{effortDate(w.start,true)} – {effortDate(w.end)}</time></span>
      <strong><Figure value={weekTotal(w)} places={0}/></strong><ChevronDown size={15}/>
     </button>
     <div className="c8-week-reveal" id={`c8-week-${encodeURIComponent(w.id)}`} data-open={open} aria-hidden={!open}><div><div className="c8-receipt">
      <dl>{allocationKeys.map(key=><div key={key}><dt>{allocationLabels[key]}</dt><dd><Figure value={w.allocations[key]}/></dd>{w.carry[key]>0&&<div className="c8-carry"><span>Carried forward</span><span>{amount(w.carry[key])} DUNG</span></div>}</div>)}</dl>
      <footer><Check size={12}/><span>Settled <time dateTime={w.settledAt}>{effortDate(w.settledAt)}</time></span></footer>
     </div></div></div>
    </section>;})}</div>
   </section>
   <aside className="c8-position" aria-label="Your Vault position"><header><h3>Your position</h3></header>{position?<>
    <div className="c8-ready"><span>DUNG ready</span><strong data-size={position.readyDung>=1000000?'compact':'normal'}><Figure value={position.readyDung}/><small>DUNG</small></strong>{position.readyDung>0?<button className="c8-collect" onClick={()=>setAction('collect')}>Collect DUNG<ArrowUpRight size={15}/></button>:<span className="c8-waiting">Waiting</span>}</div>
    <div className="c8-principal"><div><span>CAL deposited</span><strong><Figure value={position.depositedCal} places={Number.isInteger(position.depositedCal)?0:2}/><small>CAL</small></strong></div><time dateTime={position.since}>Since {effortDate(position.since)}</time></div>
    <div className="c8-position-actions">{account&&<button onClick={()=>setAction('deposit')}>Deposit CAL</button>}<button onClick={()=>setAction('withdraw')}>Withdraw CAL</button></div>
   </>:<div className="c8-no-position"><p>{viewer==='signed-out'?'Sign in to see your position.':account?'No position on this climb.':'Position unavailable.'}</p>{account&&<button className="c8-collect" onClick={()=>setAction('deposit')}>Deposit CAL<ArrowUpRight size={15}/></button>}{viewer==='signed-out'&&<button className="c8-collect" onClick={onSignIn}>Sign in<ArrowUpRight size={15}/></button>}</div>}</aside>
  </div>
  {action&&viewer==='rider'&&<ClimbV8Action key={action} action={action} economy={economy} name={name} onClose={()=>setAction(null)}/>}
 </section>;
}
