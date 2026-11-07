import {useEffect,useMemo,useRef,useState} from 'react';
import {ArrowUpRight,Check,ChevronLeft,ChevronRight,X} from 'lucide-react';
import {effortDate} from './climbV5Model';
import {amount,allocationKeys,allocationLabels,type ClimbV7Economy} from './climbV7Model';
import {settlementTotal} from './climbV9Model';
import {vaultNumber} from './climbV10Model';
import {ClimbV10Plate} from './ClimbV10Plate';
import type {ClimbViewer} from './climbModel';
import {ClimbV8Action,type VaultAction} from './ClimbV8Action';
function Figure({value}:{value:number}){
 const [whole,fraction]=vaultNumber(value).split('.');
 return <span className="c10-figure">{whole}{fraction&&<span>.{fraction}</span>}</span>;
}
export function ClimbV11VaultSummary({economy}:{economy:ClimbV7Economy}){
 return <ClimbV10Plate className="c10-vault-summary" title="Vault" action={<a href="#c10-vault" aria-label="View Vault"><ArrowUpRight size={16}/></a>}><div className="c7-summary-primary"><span>Lifetime CAL tribute</span><strong><Figure value={economy.lifetimeTributeCal}/><small>CAL</small></strong></div><dl><div><dt>CAL deposited</dt><dd>{amount(economy.depositedPrincipalCal)}</dd></div></dl><a className="c7-summary-link" href="#c10-vault">DUNG history & position<ChevronRight size={14}/></a></ClimbV10Plate>;
}
export function ClimbV11Vault({economy,viewer,name,onSignIn}:{economy:ClimbV7Economy;viewer:ClimbViewer;name:string;onSignIn:()=>void}){
 const weeks=useMemo(()=>[...economy.weeks].sort((a,b)=>Date.parse(a.end)-Date.parse(b.end)),[economy.weeks]);
 const [selected,setSelected]=useState<string|null>(null),[hover,setHover]=useState<string|null>(null),[action,setAction]=useState<VaultAction|null>(null);
 const plot=useRef<SVGSVGElement>(null),[width,setWidth]=useState(740);
 useEffect(()=>{const el=plot.current;if(!el)return;const observer=new ResizeObserver(e=>setWidth(e[0].contentRect.width));observer.observe(el);return()=>observer.disconnect();},[]);
 const active=weeks.find(w=>w.id===(hover??selected))??weeks.at(-1)!,activeIndex=weeks.indexOf(active),total=settlementTotal(active),position=viewer==='rider'?economy.position:undefined,account=viewer==='rider'?economy.account:undefined;
 const clear=()=>{setSelected(null);setHover(null);},choose=(id:string)=>{setSelected(s=>s===id?null:id);setHover(null);};
 const W=Math.max(280,width),H=196,L=44,R=14,T=16,B=34,span=W-L-R,start=Date.parse(weeks[0].start),end=Date.parse(weeks.at(-1)!.end),duration=end-start;
 const x=(date:string)=>L+(Date.parse(date)-start)/duration*span,mid=(w:typeof active)=>(x(w.start)+x(w.end))/2;
 const ceiling=Math.max(1,Math.ceil(Math.max(...weeks.map(settlementTotal))/3/10)*30),y=(value:number)=>T+(1-value/ceiling)*(H-T-B);

 return <section className="c10-vault" id="c10-vault" onKeyDown={e=>{if(e.key==='Escape')clear();}}>
  <header className="c7-section-heading"><h2>Vault</h2><span>As of {effortDate(economy.asOf)}</span></header>
  <div className="c10-vault-layout">
   <section className="c10-settlement" aria-label="DUNG settlement history">
    <header className="c10-settlement-reading"><div><span>DUNG allocated</span><strong><Figure value={total}/><small>DUNG</small></strong></div><div className="c10-period"><span>{selected===active.id?'Selected week':'Week'}</span><div><button aria-label="Previous settlement" disabled={activeIndex===0} onClick={()=>{setSelected(weeks[activeIndex-1].id);setHover(null);}}><ChevronLeft size={15}/></button><time dateTime={active.start}>{effortDate(active.start,true)} – {effortDate(active.end,true)}</time><button aria-label="Next settlement" disabled={activeIndex===weeks.length-1} onClick={()=>{setSelected(weeks[activeIndex+1].id);setHover(null);}}><ChevronRight size={15}/></button></div></div></header>
    <svg ref={plot} viewBox={`0 0 ${W} ${H}`} className="c10-settlement-plot" role="group" aria-label="Weekly DUNG allocations" onPointerLeave={()=>{setHover(null);}} onClick={()=>{if(selected)clear();else if(hover)setSelected(hover);}}>
     <rect width={W} height={H} fill="transparent"/>
     {[0,1,2,3].map(n=>{const value=ceiling*n/3;return <g key={n}><line x1={L} x2={W-R} y1={y(value)} y2={y(value)} className="c10-grid"/><text x={L-10} y={y(value)+4} textAnchor="end" className="c10-axis">{value.toLocaleString('en-US',{maximumFractionDigits:2})}</text></g>;})}
     {weeks.map((w,i)=>{const left=x(w.start),right=x(w.end),bar=Math.min(24,Math.max(2,(right-left)*.3));return <g key={w.id} role="button" tabIndex={i===activeIndex?0:-1} aria-label={`Inspect week ${effortDate(w.start,true)} to ${effortDate(w.end,true)}, ${settlementTotal(w)} DUNG`} aria-pressed={selected===w.id} className="c10-settlement-week" onPointerEnter={()=>setHover(w.id)} onPointerLeave={()=>setHover(null)} onFocus={()=>setHover(w.id)} onBlur={()=>setHover(null)} onClick={e=>{e.stopPropagation();selected?clear():choose(w.id);}} onKeyDown={e=>{if(e.key==='Enter'||e.key===' '){e.preventDefault();choose(w.id);}if(['ArrowLeft','ArrowRight','Home','End'].includes(e.key)){e.preventDefault();const next=e.key==='Home'?0:e.key==='End'?weeks.length-1:Math.max(0,Math.min(weeks.length-1,i+(e.key==='ArrowRight'?1:-1)));plot.current?.querySelectorAll<SVGGElement>('.c10-settlement-week')[next]?.focus();}}}>
      <rect x={left+.5} y={T-7} width={Math.max(0,right-left-1)} height={H-T-B+7} className="c10-week-band" data-selected={selected===w.id}/><rect x={mid(w)-bar/2} y={y(settlementTotal(w))} width={bar} height={Math.max(1,y(0)-y(settlementTotal(w)))} rx={2} className="c10-week-bar"/>
     </g>;})}
     {[...new Set([0,Math.floor((weeks.length-1)/2),weeks.length-1])].map(i=><text key={i} x={i===0?L:i===weeks.length-1?W-R:mid(weeks[i])} y={H-8} textAnchor={i===0?'start':i===weeks.length-1?'end':'middle'} className="c10-axis">{effortDate(weeks[i].end,true)}</text>)}
    </svg>
    <div className="c10-allocation-heading"><span>Allocation</span><span>DUNG</span></div>
    <dl className="c10-allocation">{allocationKeys.map(key=><div key={key}><dt>{allocationLabels[key]}</dt><dd><Figure value={active.allocations[key]}/></dd>{active.carry[key]>0&&<p><span>Carried forward</span><strong><Figure value={active.carry[key]}/></strong></p>}</div>)}</dl>
    <footer className="c10-settlement-foot"><span><Check size={13}/>Settled <time dateTime={active.settledAt}>{effortDate(active.settledAt)}</time></span>{selected?<button onClick={clear} aria-label="Clear settlement selection">Latest week<X size={13}/></button>:<span>{weeks.length} settled {weeks.length===1?'week':'weeks'}</span>}</footer>
   </section>
   <ClimbV10Plate className="c10-position" title="Your position" label="Your Vault position">{position?<>
    <div className="c10-ready"><span>DUNG ready</span><strong data-size={position.readyDung>=1000000?'compact':'normal'}><Figure value={position.readyDung}/><small>DUNG</small></strong>{position.readyDung>0?<button className="c10-primary-action" onClick={()=>setAction('collect')}>Collect DUNG<ArrowUpRight size={15}/></button>:<span className="c10-waiting">Waiting</span>}</div>
    <div className="c10-principal"><span>CAL deposited</span><strong><Figure value={position.depositedCal}/><small>CAL</small></strong><time dateTime={position.since}>Since {effortDate(position.since)}</time></div>
    <div className="c10-position-actions">{account&&<button onClick={()=>setAction('deposit')}>Deposit CAL</button>}<button onClick={()=>setAction('withdraw')}>Withdraw CAL</button></div>
   </>:<div className="c10-no-position"><p>{viewer==='signed-out'?'Sign in to see your position.':account?'No position on this climb.':'Position unavailable.'}</p>{account&&<button className="c10-primary-action" onClick={()=>setAction('deposit')}>Deposit CAL<ArrowUpRight size={15}/></button>}{viewer==='signed-out'&&<button className="c10-primary-action" onClick={onSignIn}>Sign in<ArrowUpRight size={15}/></button>}</div>}</ClimbV10Plate>
  </div>
  {action&&viewer==='rider'&&<ClimbV8Action key={action} action={action} economy={economy} name={name} onClose={()=>setAction(null)}/>}
 </section>;
}
