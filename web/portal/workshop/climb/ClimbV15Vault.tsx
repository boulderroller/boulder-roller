import {useEffect,useMemo,useRef,useState,type ReactNode} from 'react';
import {ChevronLeft,ChevronRight,X} from 'lucide-react';
import {effortDate} from './climbV5Model';
import {allocationKeys,allocationLabels,amount,type ClimbV7Economy} from './climbV7Model';
import {settlementTotal} from './climbV9Model';
import {vaultNumber} from './climbV10Model';
import type {ClimbViewer} from './climbModel';
import type {VaultAction} from './ClimbV8Action';
import {ClimbV15Action} from './ClimbV15Action';
const Unit=({children}:{children:ReactNode})=><>{' '}<span className="c15-unit">{children}</span></>;
/** V14's Vault, closing the page. The settled week reads as a pill with an olive dot. V11's Vault logic in one hairline-card grammar. The settlement card sits beside a column of two cards: Your position holds only the viewer's
 *  facts and is sized to them; the climb's own totals take a card of their own under the climb's name and take up the rest of the height,
 *  so the pair closes on the settlement card's bottom line and no CAL deposited of the climb's sits under Your position. */
export function ClimbV15Vault({economy,viewer,name,onSignIn}:{economy:ClimbV7Economy;viewer:ClimbViewer;name:string;onSignIn:()=>void}){
 const weeks=useMemo(()=>[...economy.weeks].sort((a,b)=>Date.parse(a.end)-Date.parse(b.end)),[economy.weeks]);
 const [selected,setSelected]=useState<string|null>(null),[hover,setHover]=useState<string|null>(null),[action,setAction]=useState<VaultAction|null>(null);
 const plot=useRef<SVGSVGElement>(null),[width,setWidth]=useState(740),[height,setHeight]=useState(164);
 useEffect(()=>{const el=plot.current;if(!el)return;const observer=new ResizeObserver(e=>{setWidth(e[0].contentRect.width);setHeight(e[0].contentRect.height);});observer.observe(el);return()=>observer.disconnect();},[]);
 const active=weeks.find(w=>w.id===(hover??selected))??weeks.at(-1)!,activeIndex=weeks.indexOf(active),total=settlementTotal(active),position=viewer==='rider'?economy.position:undefined,account=viewer==='rider'?economy.account:undefined;
 const clear=()=>{setSelected(null);setHover(null);},choose=(id:string)=>{setSelected(s=>s===id?null:id);setHover(null);};
 const W=Math.max(280,width),H=Math.max(164,Math.round(height)),L=44,R=14,T=14,B=30,span=W-L-R,start=Date.parse(weeks[0].start),end=Date.parse(weeks.at(-1)!.end),duration=end-start;
 const x=(date:string)=>L+(Date.parse(date)-start)/duration*span,mid=(w:typeof active)=>(x(w.start)+x(w.end))/2;
 const ceiling=Math.max(1,Math.ceil(Math.max(...weeks.map(settlementTotal))/3/10)*30),y=(value:number)=>T+(1-value/ceiling)*(H-T-B);
 return <section className="c15-section" id="c15-vault" aria-labelledby="c15-vault-title" onKeyDown={e=>{if(e.key==='Escape')clear();}}>
  <header className="c15-section-head"><h2 id="c15-vault-title">Vault</h2><span className="c15-rule"/><time dateTime={economy.asOf}>As of {effortDate(economy.asOf)}</time></header>
  <div className="c15-two-up">
   <section className="c15-card c15-settlement" aria-label="DUNG settlement history">
    <div className="c15-card-top"><span className="c15-kicker">{selected===active.id?'Selected week':'Week'}</span><div className="c15-period"><button aria-label="Previous settlement" disabled={activeIndex===0} onClick={()=>{setSelected(weeks[activeIndex-1].id);setHover(null);}}><ChevronLeft/></button><time dateTime={active.start}>{effortDate(active.start,true)} – {effortDate(active.end,true)}</time><button aria-label="Next settlement" disabled={activeIndex===weeks.length-1} onClick={()=>{setSelected(weeks[activeIndex+1].id);setHover(null);}}><ChevronRight/></button></div></div>
    <div className="c15-reading"><span className="c15-label">DUNG allocated</span><strong className="c15-feature">{vaultNumber(total)}<Unit>DUNG</Unit></strong></div>
    <svg ref={plot} viewBox={`0 0 ${W} ${H}`} className="c15-settlement-plot" role="group" aria-label="Weekly DUNG allocations" onPointerLeave={()=>{setHover(null);}} onClick={()=>{if(selected)clear();else if(hover)setSelected(hover);}}>
     <rect width={W} height={H} fill="transparent"/>
     {[0,1,2,3].map(n=>{const value=ceiling*n/3;return <g key={n}><line x1={L} x2={W-R} y1={y(value)} y2={y(value)} className="c15-grid"/><text x={L-10} y={y(value)+4} textAnchor="end" className="c15-axis">{value.toLocaleString('en-US',{maximumFractionDigits:2})}</text></g>;})}
     {weeks.map((w,i)=>{const left=x(w.start),right=x(w.end),bar=Math.min(24,Math.max(2,(right-left)*.3));return <g key={w.id} role="button" tabIndex={i===activeIndex?0:-1} aria-label={`Inspect week ${effortDate(w.start,true)} to ${effortDate(w.end,true)}, ${settlementTotal(w)} DUNG`} aria-pressed={selected===w.id} className="c15-week" data-active={active.id===w.id} onPointerEnter={()=>setHover(w.id)} onPointerLeave={()=>setHover(null)} onFocus={()=>setHover(w.id)} onBlur={()=>setHover(null)} onClick={e=>{e.stopPropagation();selected?clear():choose(w.id);}} onKeyDown={e=>{if(e.key==='Enter'||e.key===' '){e.preventDefault();choose(w.id);}if(['ArrowLeft','ArrowRight','Home','End'].includes(e.key)){e.preventDefault();const next=e.key==='Home'?0:e.key==='End'?weeks.length-1:Math.max(0,Math.min(weeks.length-1,i+(e.key==='ArrowRight'?1:-1)));plot.current?.querySelectorAll<SVGGElement>('.c15-week')[next]?.focus();}}}>
      <rect x={left+.5} y={T-7} width={Math.max(0,right-left-1)} height={H-T-B+7} className="c15-week-band" data-selected={selected===w.id}/><rect x={mid(w)-bar/2} y={y(settlementTotal(w))} width={bar} height={Math.max(1,y(0)-y(settlementTotal(w)))} rx={2} className="c15-week-bar"/>
     </g>;})}
     {[...new Set([0,Math.floor((weeks.length-1)/2),weeks.length-1])].map(i=><text key={i} x={i===0?L:i===weeks.length-1?W-R:mid(weeks[i])} y={H-6} textAnchor={i===0?'start':i===weeks.length-1?'end':'middle'} className="c15-axis">{effortDate(weeks[i].end,true)}</text>)}
    </svg>
    <div className="c15-allocation-head"><span className="c15-kicker">Allocation</span></div>
    <dl className="c15-allocation">{allocationKeys.map(key=><div key={key} data-key={key}><dt>{allocationLabels[key]}</dt><dd>{vaultNumber(active.allocations[key])}<Unit>DUNG</Unit></dd>{active.carry[key]>0&&<p>Carried forward {vaultNumber(active.carry[key])}</p>}</div>)}</dl>
    <footer className="c15-settlement-foot"><span className="c15-settled"><i aria-hidden="true"/>Settled <time dateTime={active.settledAt}>{effortDate(active.settledAt)}</time></span>{selected?<button className="c15-text-button" onClick={clear} aria-label="Clear settlement selection">Latest week<X aria-hidden="true"/></button>:<span>{weeks.length} settled {weeks.length===1?'week':'weeks'}</span>}</footer>
   </section>
   <div className="c15-vault-column">
   <section className="c15-card c15-position" aria-label="Your Vault position">
    <div className="c15-card-top"><p className="c15-kicker">Your position</p></div>
    {position?<>
     <div className="c15-reading"><span className="c15-label">DUNG ready</span><strong className="c15-feature" data-size={position.readyDung>=1000000?'compact':'normal'}>{vaultNumber(position.readyDung)}<Unit>DUNG</Unit></strong></div>
     {position.readyDung>0?<button className="c15-primary" onClick={()=>setAction('collect')}>Collect DUNG</button>:<span className="c15-waiting">Waiting</span>}
     <div className="c15-ledger-row"><span>CAL deposited</span><strong>{vaultNumber(position.depositedCal)}<Unit>CAL</Unit></strong><time dateTime={position.since}>Since {effortDate(position.since)}</time></div>
     <div className="c15-card-actions">{account&&<button className="c15-button" onClick={()=>setAction('deposit')}>Deposit CAL</button>}<button className="c15-button" onClick={()=>setAction('withdraw')}>Withdraw CAL</button></div>
    </>:<><p className="c15-body-muted">{viewer==='signed-out'?'Sign in to see your position.':account?'No position on this climb.':'Position unavailable.'}</p>{(account||viewer==='signed-out')&&<div className="c15-card-actions">{account&&<button className="c15-button" onClick={()=>setAction('deposit')}>Deposit CAL</button>}{viewer==='signed-out'&&<button className="c15-button" onClick={onSignIn}>Sign in</button>}</div>}</>}
   </section>
   <section className="c15-card c15-vault-climb" aria-label={`${name} Vault`}>
    <div className="c15-card-top"><p className="c15-kicker">{name}</p></div>
    <div className="c15-vault-climb-figures">
     <div className="c15-reading"><span className="c15-label">Lifetime CAL tribute</span><strong className="c15-feature">{vaultNumber(economy.lifetimeTributeCal)}<Unit>CAL</Unit></strong></div>
     <div className="c15-ledger-row"><span>CAL deposited</span><strong>{amount(economy.depositedPrincipalCal)}<Unit>CAL</Unit></strong></div>
    </div>
   </section>
   </div>
  </div>
  {action&&viewer==='rider'&&<ClimbV15Action key={action} action={action} economy={economy} name={name} onClose={()=>setAction(null)}/>}
 </section>;
}
