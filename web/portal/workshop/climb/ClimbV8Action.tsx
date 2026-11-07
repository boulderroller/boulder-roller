import {useEffect,useRef,useState} from 'react';
import {ArrowUpRight,ChevronRight} from 'lucide-react';
import {FeedV2Dialog} from '../feed/FeedV2Context';
import {amount,validDeposit,type ClimbV7Economy} from './climbV7Model';
export type VaultAction='deposit'|'withdraw'|'collect';
export function ClimbV8Action({action,economy,name,onClose}:{action:VaultAction;economy:ClimbV7Economy;name:string;onClose:()=>void}){
 const position=economy.position,account=economy.account,available=account?.availableCal??0;
 const [deposit,setDeposit]=useState(''),[review,setReview]=useState(false);
 const reviewExit=useRef<HTMLButtonElement>(null);
 useEffect(()=>{if(review)reviewExit.current?.focus();},[review]);
 const value=Number(deposit),valid=validDeposit(deposit,available),exact=(n:number)=>n.toLocaleString('en-US',{maximumFractionDigits:9});
 const actionTitle=action==='deposit'?'Deposit CAL':action==='withdraw'?'Withdraw CAL':'Collect DUNG';
 return <>{action&&(action==='deposit'?account:position)&&<FeedV2Dialog title={actionTitle} onClose={onClose}><div className="c7-action-view"><p className="c7-action-climb">{name}</p>
   {action==='deposit'&&!review?<form onSubmit={e=>{e.preventDefault();if(valid)setReview(true);}}><label className="c7-amount-input"><span>Amount</span><div><input aria-label="CAL to deposit" inputMode="numeric" value={deposit} onChange={e=>setDeposit(e.target.value)} placeholder="0"/><strong>CAL</strong></div></label><div className="c7-available"><span>Available {amount(Math.floor(available))} CAL</span><button type="button" onClick={()=>setDeposit(String(Math.floor(available)))}>Max</button></div>{deposit&&!valid&&<p className="c7-input-error" role="alert">{available<100?'At least 100 CAL is needed to deposit.':`Enter whole CAL, from 100 to ${amount(Math.floor(available))} CAL.`}</p>}<button className="c7-primary-button" disabled={!valid}>Review deposit<ArrowUpRight size={14}/></button></form>:<>
    <span className="c7-action-label">{action==='deposit'?'Deposit':action==='withdraw'?'CAL deposited':'DUNG ready'}</span><strong className="c7-action-amount">{exact(action==='deposit'?value:action==='withdraw'?position!.depositedCal:position!.readyDung)}<small>{action==='collect'?'DUNG':'CAL'}</small></strong>
    <dl className="c7-action-facts"><div><dt>{action==='deposit'?'To':action==='collect'?'Destination':'Action'}</dt><dd>{action==='deposit'?name:action==='collect'?'Your wallet':'Withdraw full position'}</dd></div>{action==='deposit'&&<div><dt>Deposited CAL after</dt><dd>{exact((position?.depositedCal??0)+value)} CAL</dd></div>}{action==='withdraw'&&<div><dt>Withdrawal amount</dt><dd>Quote required</dd></div>}<div><dt>Fee & net amount</dt><dd>Shown before signing</dd></div></dl>
    <button ref={reviewExit} className="c7-primary-button" onClick={onClose}>Back to Vault<ChevronRight size={14}/></button>
   </>}
   <p className="c7-preview-note">Workshop preview · no transaction is submitted.</p>
  </div></FeedV2Dialog>}</>;
}
