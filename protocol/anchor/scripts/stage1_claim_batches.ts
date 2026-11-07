import {AddressLookupTableAccount, ComputeBudgetProgram, PublicKey, TransactionInstruction, TransactionMessage, VersionedTransaction} from '@solana/web3.js';

/** Exact packet size, including every required signature and the real setup instructions. */
export function claimPacketBytes(payer:PublicKey,instructions:TransactionInstruction[],tables:AddressLookupTableAccount[]=[]):number {
  const message=new TransactionMessage({payerKey:payer,recentBlockhash:PublicKey.default.toBase58(),
    instructions:[ComputeBudgetProgram.setComputeUnitLimit({units:1_000_000}),...instructions]});
  try{return new VersionedTransaction(tables.length?message.compileToV0Message(tables):message.compileToLegacyMessage()).serialize().length;}
  catch(error:any){if(error instanceof RangeError||/encoding overruns|Transaction too large/.test(error.message))return Infinity;throw error;}
}
/** Each returned transaction is atomic. Submitted earlier chunks stay committed if a later one fails. */
export async function splitClaimBatches(count:number,build:(start:number,end:number)=>Promise<TransactionInstruction>,
  payer:PublicKey,setup:TransactionInstruction[]=[],tables:AddressLookupTableAccount[]=[]):Promise<TransactionInstruction[][]>{
  if(!Number.isInteger(count)||count<1)throw Error('Nonempty claim batch required');
  const transactions:TransactionInstruction[][]=[];
  for(let start=0;start<count;){
    let selected:TransactionInstruction[]|undefined,end=Math.min(count,start+4);
    for(;end>start;end--){
      let candidate:TransactionInstruction[];
      try{candidate=[...setup,await build(start,end)];}
      catch(error){if(error instanceof RangeError)continue;throw error;}
      if(claimPacketBytes(payer,candidate,tables)<=1232){selected=candidate;break;}
    }
    if(!selected)throw Error('Single claim plus token-account setup exceeds packet limit; supply explicit address lookup tables');
    transactions.push(selected);start=end;
  }
  return transactions;
}
