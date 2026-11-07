import {useEffect,useRef,useState} from 'react';
import {ArrowDownLeft,ArrowUpRight,Check,ChevronDown,ChevronRight,Info} from 'lucide-react';
import {FeedV2Dialog} from '../feed/FeedV2Context';
import {effortDate} from './climbV5Model';
import {amount,allocationShare,validDeposit,allocationKeys,allocationLabels,weekTotal,type ClimbV7Economy,type AllocationKey} from './climbV7Model';
import type {ClimbViewer} from './climbModel';

type Action='deposit'|'withdraw'|'collect';
export function ClimbV7VaultSummary({economy}:{economy:ClimbV7Economy}){
 return <section className="c7-vault-summary"><header><h2>Vault</h2><a href="#c7-vault" aria-label="View Vault"><ArrowUpRight size={16}/></a></header><div className="c7-summary-primary"><span>Lifetime CAL tribute</span><strong>{amount(economy.lifetimeTributeCal)}<small>CAL</small></strong></div><dl><div><dt>CAL deposited</dt><dd>{amount(economy.depositedPrincipalCal)}</dd></div></dl><a className="c7-summary-link" href="#c7-vault">DUNG history & position<ChevronRight size={14}/></a></section>;
}
export function ClimbV7Vault({economy,viewer,name,onSignIn}:{economy:ClimbV7Economy;viewer:ClimbViewer;name:string;onSignIn:()=>void}){
 const [weekId,setWeekId]=useState(economy.weeks[0].id),[allocation,setAllocation]=useState<AllocationKey|null>(null),[historyOpen,setHistoryOpen]=useState(false),[detailOpen,setDetailOpen]=useState(false),[action,setAction]=useState<Action|null>(null),[deposit,setDeposit]=useState(''),[review,setReview]=useState(false);
 const week=economy.weeks.find(w=>w.id===weekId)??economy.weeks[0],total=weekTotal(week),carry=allocationKeys.reduce((sum,key)=>sum+week.carry[key],0),position=viewer==='rider'?economy.position:undefined,account=viewer==='rider'?economy.account:undefined;
 const reviewExit=useRef<HTMLButtonElement>(null);
 useEffect(()=>{if(review)reviewExit.current?.focus();},[review]);
 const open=(next:Action)=>{setAction(next);setReview(false);setDeposit('');};
 const available=account?.availableCal??0,value=Number(deposit),valid=validDeposit(deposit,available);
 const actionTitle=action==='deposit'?'Deposit CAL':action==='withdraw'?'Withdraw CAL':'Collect DUNG';
 const exact=(n:number)=>n.toLocaleString('en-US',{maximumFractionDigits:9});
 return <section className="c7-vault-section" id="c7-vault">
  <header className="c7-section-heading"><h2>Vault</h2><span>As of {effortDate(economy.asOf)}</span></header>
  <div className="c7-vault-body"><div className="c7-settlements">
   <div className="c7-week-header"><label><span>Settlement Week</span><select aria-label="Settlement Week" value={weekId} onChange={e=>{setWeekId(e.target.value);setAllocation(null);}}>{economy.weeks.map(w=><option key={w.id} value={w.id}>{effortDate(w.start,true)} – {effortDate(w.end)}</option>)}</select></label><span className="c7-cleared"><Check size={12}/>Cleared</span></div>
   <div className="c7-week-total"><div><span>DUNG allocated</span><strong title={`${exact(total)} DUNG`}>{amount(total)}<small>DUNG</small></strong></div><span>Settled {effortDate(week.settledAt,true)}</span></div>
   <div className="c7-allocation-strip" role="group" aria-label="DUNG allocation">{allocationKeys.map(key=><button key={key} className={`c7-allocation-${key}`} style={{flexGrow:week.allocations[key],flexBasis:0}} aria-label={`${allocationLabels[key]}, ${exact(week.allocations[key])} DUNG`} title={`${allocationLabels[key]} · ${exact(week.allocations[key])} DUNG`} onPointerEnter={()=>setAllocation(key)} onPointerLeave={()=>setAllocation(null)} onFocus={()=>setAllocation(key)} onBlur={()=>setAllocation(null)} onClick={()=>{setAllocation(key);setDetailOpen(true);}}/>)}</div>
   <dl className="c7-allocation-list">{allocationKeys.map(key=><div key={key} data-active={allocation===key} onPointerEnter={()=>setAllocation(key)} onPointerLeave={()=>setAllocation(null)}><dt><i className={`c7-allocation-${key}`}/>{allocationLabels[key]}</dt><dd><span>{allocationShare(week.allocations[key],total).toLocaleString('en-US',{maximumFractionDigits:2})}%</span><strong title={`${exact(week.allocations[key])} DUNG`}>{amount(week.allocations[key])}</strong><small>DUNG</small></dd></div>)}</dl>
   <div className="c7-vault-links"><button onClick={()=>setHistoryOpen(!historyOpen)} aria-expanded={historyOpen}>DUNG history<ChevronDown size={14}/></button><button onClick={()=>setDetailOpen(!detailOpen)} aria-expanded={detailOpen}>Settlement details<Info size={13}/></button></div>
   {historyOpen&&<div className="c7-week-history"><table><thead><tr><th>Week ending</th><th>DUNG allocated</th><th>State</th></tr></thead><tbody>{economy.weeks.map(w=><tr key={w.id} data-active={week.id===w.id}><th><button onClick={()=>setWeekId(w.id)}>{effortDate(w.end)}</button></th><td>{amount(weekTotal(w))}</td><td>Cleared</td></tr>)}</tbody></table></div>}
   {detailOpen&&<div className="c7-settlement-detail"><dl><div><dt>Settled</dt><dd>{effortDate(week.settledAt)}</dd></div><div><dt>Carried forward</dt><dd>{exact(carry)} DUNG</dd></div></dl><p>Allocations follow this week’s eligible positions and leaderboard. Carried amounts stay in their own allocation until they can clear.</p><p>CAL tribute measures climb activity. It does not reduce the rider’s CAL.</p></div>}
  </div><aside className="c7-position" id="c7-position"><h3>Your position</h3>{position?<>
   <div className="c7-position-cal"><span>CAL deposited</span><strong>{amount(position.depositedCal)}<small>CAL</small></strong><time dateTime={position.since}>Since {effortDate(position.since)}</time></div>
   <div className="c7-position-controls">{account&&<button onClick={()=>open('deposit')}>Deposit CAL<ArrowDownLeft size={14}/></button>}<button onClick={()=>open('withdraw')}>Withdraw CAL<ArrowUpRight size={14}/></button></div>
   <div className="c7-position-dung"><span>DUNG ready</span><strong title={`${exact(position.readyDung)} DUNG`}>{amount(position.readyDung)}<small>DUNG</small></strong>{position.readyDung>0?<button className="c7-primary-button" onClick={()=>open('collect')}>Collect DUNG<ArrowUpRight size={14}/></button>:<span className="c7-waiting">Waiting</span>}</div>
  </>:<div className="c7-position-absent"><p>{viewer==='signed-out'?'Sign in to see your position.':'No position on this climb.'}</p>{account&&<button className="c7-primary-button" onClick={()=>open('deposit')}>Deposit CAL<ArrowDownLeft size={14}/></button>}{viewer==='signed-out'&&<button className="c7-primary-button" onClick={onSignIn}>Sign in<ArrowUpRight size={14}/></button>}</div>}</aside></div>
  {action&&(action==='deposit'?account:position)&&<FeedV2Dialog title={actionTitle} onClose={()=>setAction(null)}><div className="c7-action-view"><p className="c7-action-climb">{name}</p>
   {action==='deposit'&&!review?<form onSubmit={e=>{e.preventDefault();if(valid)setReview(true);}}><label className="c7-amount-input"><span>Amount</span><div><input aria-label="CAL to deposit" inputMode="numeric" value={deposit} onChange={e=>setDeposit(e.target.value)} placeholder="0"/><strong>CAL</strong></div></label><div className="c7-available"><span>Available {amount(Math.floor(available))} CAL</span><button type="button" onClick={()=>setDeposit(String(Math.floor(available)))}>Max</button></div>{deposit&&!valid&&<p className="c7-input-error" role="alert">Enter whole CAL, from 100 to {amount(Math.floor(available))} CAL.</p>}<button className="c7-primary-button" disabled={!valid}>Review deposit<ArrowUpRight size={14}/></button></form>:<>
    <span className="c7-action-label">{action==='deposit'?'Deposit':action==='withdraw'?'CAL deposited':'DUNG ready'}</span><strong className="c7-action-amount">{exact(action==='deposit'?value:action==='withdraw'?position!.depositedCal:position!.readyDung)}<small>{action==='collect'?'DUNG':'CAL'}</small></strong>
    <dl className="c7-action-facts"><div><dt>{action==='deposit'?'To':action==='collect'?'Destination':'Action'}</dt><dd>{action==='deposit'?name:action==='collect'?'Your wallet':'Withdraw full position'}</dd></div>{action==='deposit'&&<div><dt>Deposited CAL after</dt><dd>{exact((position?.depositedCal??0)+value)} CAL</dd></div>}{action==='withdraw'&&<div><dt>Withdrawal amount</dt><dd>Quote required</dd></div>}<div><dt>Fee & net amount</dt><dd>Shown before signing</dd></div></dl>
    <button ref={reviewExit} className="c7-primary-button" onClick={()=>setAction(null)}>Back to Vault<ChevronRight size={14}/></button>
   </>}
   <p className="c7-preview-note">Workshop preview · no transaction is submitted.</p>
  </div></FeedV2Dialog>}
 </section>;
}
