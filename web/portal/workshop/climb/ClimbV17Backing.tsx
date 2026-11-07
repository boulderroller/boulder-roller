import {useState} from 'react';
import {Button,Card,Dialog,ListRow,MenuSelect,Note,Section,Segmented,Stat,Stats,Unit} from '../v15';
import type {BondingState} from './climbV17Model';

// Exact amounts and state proposals from stage1-words BondingMock/DepositMock,
// 19 Oct. Local layout evidence only; this module has no wallet/provider path.
export function ClimbV17Backing({state,name}:{state:BondingState;name:string}){
 const prebond=state==='prebond',stale=state==='stale';
 const [open,setOpen]=useState(false),[ready,setReady]=useState(false),[unit,setUnit]=useState('jitoSOL');
 const sol=unit==='SOL',amount=prebond?'4':sol?'3':'2.5';
 return <Section title="Bonding" aside={prebond?'Not bonded yet · 3 founding deposits':'Bonded Oct 18 · 1 founding deposit'}>
  <Card flush><Stats><Stat label={prebond?'Counted toward the line':"This week's pool"} value={prebond?<>8.75 <Unit>of 10 SOL</Unit></>:<>0.0123 <Unit>jitoSOL</Unit></>} basis={prebond?'1.25 SOL to bond':'Week 1 · closes Mon, Oct 26, 8:00 AM'}/><Stat label={prebond?"This week's pool":'Counted toward the line'} value={prebond?<>5 <Unit>USDC</Unit></>:<>{stale?'≈ ':''}10.05 <Unit>SOL</Unit></>} basis={prebond?'Week 1 · closes Mon, Oct 26, 8:00 AM':stale?"At last epoch's rate":undefined}/></Stats>
   <ListRow name="Every rider, by ascents" figure="65%"/><ListRow name="Leaderboard pool" figure="25%"/><ListRow name="Local Legend" figure="10%"/>
   <div className="climb-actions">{state==='rehearsal'?<Note>Deposits are closed during the test</Note>:<Button variant="primary" onClick={()=>{setOpen(true);setReady(false);setUnit('jitoSOL');}}>Deposit</Button>}</div>
  </Card>
  <Note>Workshop · stage 1 proposals · illustrative amounts from the Shawmont design pass.</Note>
  <Dialog open={open} title="Deposit" onClose={()=>setOpen(false)}>
   <Stats><Stat label="Amount" value={<>{amount} <Unit>{unit}</Unit></>}/><Stat label="Wallet" value={sol?'12.4':'6.2'}/></Stats>
   <MenuSelect label="Token" value={unit} options={[{value:'jitoSOL',label:'jitoSOL'},{value:'SOL',label:'SOL',disabled:prebond},{value:'mSOL',label:'mSOL',disabled:true},{value:'JupSOL',label:'JupSOL',disabled:true}]} onChange={setUnit}/>
   <ListRow name="Climb" figure={name}/>{sol&&<ListRow name="Staked as" figure="2.52 jitoSOL" meta="via Jito"/>}
   {prebond?<><ListRow name="Counted toward the line" figure="8.75 of 10 SOL"/><ListRow name="Founding deposit" meta="Locked 26 weeks after it bonds"/><ListRow name="Earliest back" meta="30 weeks after it bonds"/><ListRow name="Before it bonds" figure="Cancel any time"/></>:<><Note>Lock (weeks)</Note><Segmented label="Lock (weeks)" options={[0,13,26,52].map(n=>({value:String(n),label:String(n)}))} value="26" onChange={()=>{}} disabled/><ListRow name="Earliest back" figure="May 17, 2027" meta="after 4 weeks' notice"/></>}
   <ListRow name="Staking yield" meta={prebond?"To this hill's riders once it bonds":"To this hill's riders"} figure="10% fee"/><ListRow name="Account cost" figure="0.0053 SOL" meta="not refunded"/>
   <Note>{sol?'Your SOL is staked as jitoSOL first. ':''}You get back its SOL value in fewer jitoSOL, or less if jitoSOL falls against SOL.</Note>
   <Note>Workshop preview · no transaction is sent.</Note>
   {ready?<Button variant="primary" disabled>Hold to confirm</Button>:<Button variant="primary" onClick={()=>setReady(true)}>Continue</Button>}
  </Dialog>
 </Section>;
}
