import {expect} from 'chai';
import * as anchor from '@coral-xyz/anchor';
import BN from 'bn.js';
import {readFileSync} from 'fs';
import {PublicKey, Keypair, SystemProgram, AddressLookupTableAccount} from '@solana/web3.js';
import {createAssociatedTokenAccountIdempotentInstruction,getAssociatedTokenAddressSync,TOKEN_PROGRAM_ID} from '@solana/spl-token';
import {submitPlannedBatches} from '../scripts/stage1_operator.js';
import {claimPacketBytes,splitClaimBatches} from '../scripts/stage1_claim_batches.js';
const idl=JSON.parse(readFileSync(new URL('../idl/boulder_rollers.json',import.meta.url),'utf8'));
const key=()=>PublicKey.unique(),payer=key(),person=key(),mint=key(),owner=key(),programId=key();
const program:any=new anchor.Program(idl,programId,{connection:{},wallet:{publicKey:payer}} as any);
const destination=getAssociatedTokenAddressSync(mint,owner,true);
const accounts={city:key(),asset:key(),registration:key(),earnings:key(),destination,tokenProgram:TOKEN_PROGRAM_ID};
const sets=Array.from({length:9},key);
const setup=[createAssociatedTokenAccountIdempotentInstruction(payer,destination,owner,mint)];
function builder(depth:number){return async(start:number,end:number)=>program.methods.claimStage1Batch(person,sets.slice(start,end).map((_,i)=>({index:start+i,amount:new BN(1),
  proof:Array.from({length:depth},()=>({hash:Array(32).fill(1),sum:new BN(1)})),terms:{cap:new BN(1),frozenAt:new BN(1),auditHash:Array(32).fill(2)}})))
  .accounts(accounts).remainingAccounts(sets.slice(start,end).map(pubkey=>({pubkey,isSigner:false,isWritable:true}))).instruction();}
describe('claim batches fit exact packets with setup and signatures',()=>{
  for(const depth of [0,4,8,12])it(`splits nine depth-${depth} claims without changing order or dropping leaves`,async()=>{
    const tables=depth>=12?[new AddressLookupTableAccount({key:key(),state:{deactivationSlot:BigInt('18446744073709551615'),lastExtendedSlot:1,lastExtendedSlotStartIndex:0,authority:payer,addresses:[...Object.values(accounts),...sets,mint,owner,setup[0].programId,programId]}})]:[];
    const batches=await splitClaimBatches(sets.length,builder(depth),payer,setup,tables);
    const indices:number[]=[];
    for(const instructions of batches){
      expect(instructions[0]).eq(setup[0]);expect(claimPacketBytes(payer,instructions,tables)).at.most(1232);
      const decoded:any=program.coder.instruction.decode(instructions[1].data);
      expect(decoded.data.leaves.length).within(1,4);indices.push(...decoded.data.leaves.map((v:any)=>v.index));
    }
    expect(indices).deep.eq(sets.map((_,i)=>i));
    console.log(`    cash depth ${depth}: ${batches.map(b=>(program.coder.instruction.decode(b[1].data) as any).data.leaves.length).join('+')} claims, max ${Math.max(...batches.map(b=>claimPacketBytes(payer,b,tables)))} bytes with ATA${tables.length?' and ALT':''}`);
  });
  it('fits a maximum-depth single with an explicit lookup table; refuses unsplittable setup',async()=>{
    const addresses=[...Object.values(accounts),...sets,mint,owner,setup[0].programId,programId];
    const table=new AddressLookupTableAccount({key:key(),state:{deactivationSlot:BigInt('18446744073709551615'),lastExtendedSlot:1,lastExtendedSlotStartIndex:0,authority:payer,addresses}});
    const batches=await splitClaimBatches(2,builder(16),payer,setup,[table]);expect(batches).length(2);
    expect(batches.every(b=>claimPacketBytes(payer,b,[table])<=1232)).eq(true);
    let error='';try{await splitClaimBatches(1,builder(16),payer,Array(20).fill(setup[0]));}catch(e:any){error=e.message;}
    expect(error).include('Single claim');
  });
  it('retains the first submitted signature and stops after a later chunk fails',async()=>{
    const wallet=Keypair.generate(),ix=SystemProgram.transfer({fromPubkey:wallet.publicKey,toPubkey:key(),lamports:1});
    let simulated=0,sent=0,completed=false;const reports:any[]=[];
    const connection:any={getLatestBlockhash:async()=>({blockhash:PublicKey.default.toBase58()}),
      simulateTransaction:async()=>({value:{err:++simulated===2?{InstructionError:[0,'Custom']}:null,logs:[]}}),
      sendRawTransaction:async()=>`signature-${++sent}`,confirmTransaction:async()=>({value:{err:null}})};
    let error='';try{await submitPlannedBatches(connection,wallet.publicKey,[[ix],[ix],[ix]],[],()=>wallet,(...entry)=>reports.push(entry));completed=true;}catch(e:any){error=e.message;}
    expect(error).include('Simulation failed');expect(simulated).eq(2);expect(sent).eq(1);
    expect(reports).deep.eq([['signature-1',1,3]]);expect(completed).eq(false);
  });

});
