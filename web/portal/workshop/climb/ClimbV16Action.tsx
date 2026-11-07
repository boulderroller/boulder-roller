import {useEffect,useRef,useState} from 'react';
import {ChevronRight} from 'lucide-react';
import {FeedV2Dialog} from '../feed/FeedV2Context';
import {amount,validDeposit,type ClimbV7Economy} from './climbV7Model';
import type {VaultAction} from './ClimbV8Action';
/** ClimbV8Action's flow in V15 anatomy: eyebrow, vault-tier numeral, hairline ledger rows. Nothing here signs, so nothing here is filled: the only filled button on the room is Collect DUNG, which commits. */
export function ClimbV16Action({action,economy,name,onClose}:{action:VaultAction;economy:ClimbV7Economy;name:string;onClose:()=>void}){
 const position=economy.position,account=economy.account,available=account?.availableCal??0;
 const [deposit,setDeposit]=useState(''),[review,setReview]=useState(false);
 const reviewExit=useRef<HTMLButtonElement>(null);
 useEffect(()=>{if(review)reviewExit.current?.focus();},[review]);
 const value=Number(deposit),valid=validDeposit(deposit,available),exact=(n:number)=>n.toLocaleString('en-US',{maximumFractionDigits:9});
 const title=action==='deposit'?'Deposit CAL':action==='withdraw'?'Withdraw CAL':'Collect DUNG';
 if(!(action==='deposit'?account:position))return null;
 return <FeedV2Dialog title={title} onClose={onClose}><div className="c16-action"><p className="c16-kicker">{name}</p>
  {action==='deposit'&&!review?<form onSubmit={e=>{e.preventDefault();if(valid)setReview(true);}}>
   <label className="c16-amount"><span className="c16-label">Amount</span><span className="c16-amount-field"><input aria-label="CAL to deposit" inputMode="numeric" value={deposit} onChange={e=>setDeposit(e.target.value)} placeholder="0"/><span className="c16-unit">CAL</span></span></label>
   <div className="c16-available"><span>Available {amount(Math.floor(available))} CAL</span><button type="button" className="c16-text-button" onClick={()=>setDeposit(String(Math.floor(available)))}>Max</button></div>
   {deposit&&!valid&&<p className="c16-input-error" role="alert">{available<100?'At least 100 CAL is needed to deposit.':`Enter whole CAL, from 100 to ${amount(Math.floor(available))} CAL.`}</p>}
   <button className="c16-button c16-button-wide" disabled={!valid}>Review deposit<ChevronRight aria-hidden="true"/></button>
  </form>:<>
   <span className="c16-label">{action==='deposit'?'Deposit':action==='withdraw'?'CAL deposited':'DUNG ready'}</span>
   <strong className="c16-feature">{exact(action==='deposit'?value:action==='withdraw'?position!.depositedCal:position!.readyDung)}{' '}<span className="c16-unit">{action==='collect'?'DUNG':'CAL'}</span></strong>
   <dl className="c16-action-facts"><div><dt>{action==='deposit'?'To':action==='collect'?'Destination':'Action'}</dt><dd>{action==='deposit'?name:action==='collect'?'Your wallet':'Withdraw full position'}</dd></div>{action==='deposit'&&<div><dt>Deposited CAL after</dt><dd>{exact((position?.depositedCal??0)+value)} CAL</dd></div>}{action==='withdraw'&&<div><dt>Withdrawal amount</dt><dd>Quote required</dd></div>}<div><dt>Fee & net amount</dt><dd>Shown before signing</dd></div></dl>
   <div className="c16-card-actions"><button ref={reviewExit} className="c16-button" onClick={onClose}>Back to Vault<ChevronRight aria-hidden="true"/></button></div>
  </>}
  <p className="c16-preview-note">Workshop preview · no transaction is submitted.</p>
 </div></FeedV2Dialog>;
}
