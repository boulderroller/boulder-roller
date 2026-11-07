// Local Squads execution evidence. These generated members are disposable fixtures.
import * as anchor from '@coral-xyz/anchor';
import * as squads from '@sqds/multisig';
import BN from 'bn.js';
import { expect } from 'chai';
import { ComputeBudgetProgram, Keypair, PublicKey, SystemProgram, TransactionMessage, VersionedTransaction } from '@solana/web3.js';
import { Operator } from '../scripts/stage1_operator.js';
import { buildGovernance, vaultFor } from '../scripts/stage1_governance.js';
if(process.env.STAGE1_GUARDIAN_RUNTIME==='1') describe('no-delay guardian, real Squads and release ELF on LOCALNET',()=>{
  const provider=anchor.AnchorProvider.env();anchor.setProvider(provider);
  const program:any=anchor.workspace.BoulderRollers,wallet=provider.wallet as anchor.Wallet;
  const fee=Keypair.generate(),createKey=Keypair.generate(),members=[Keypair.generate(),Keypair.generate()];
  const multisig=squads.getMultisigPda({createKey:createKey.publicKey})[0],vault=vaultFor(multisig);
  const pda=(seed:string)=>PublicKey.findProgramAddressSync([Buffer.from(seed)],program.programId)[0];
  let serial=0;
  async function send(ixs:any[],keys:Keypair[]=[]) {
    const latest=await provider.connection.getLatestBlockhash('finalized');
    const tx=new VersionedTransaction(new TransactionMessage({payerKey:fee.publicKey,recentBlockhash:latest.blockhash,
      instructions:[ComputeBudgetProgram.setComputeUnitLimit({units:1_400_000}),ComputeBudgetProgram.setComputeUnitPrice({microLamports:++serial}),
        ...await Promise.all(ixs.map(ix=>ix.instruction?ix.instruction():ix))]}).compileToLegacyMessage());
    const required=tx.message.staticAccountKeys.slice(0,tx.message.header.numRequiredSignatures);
    tx.sign([fee,wallet.payer,...keys].filter((s,i,all)=>required.some(k=>k.equals(s.publicKey)) && all.findIndex(x=>x.publicKey.equals(s.publicKey))===i));
    const signature=await provider.connection.sendRawTransaction(tx.serialize(),{preflightCommitment:'finalized'});
    expect((await provider.connection.confirmTransaction({...latest,signature},'finalized')).value.err).eq(null);
  }
  async function plan(action:string,input:any) {
    const r=new Operator({role:'guardian',action,cluster:'localnet',rpc:provider.connection.rpcEndpoint,
      'program-id':program.programId.toBase58(),'program-interface':process.env.STAGE1_GOVERNANCE_BUILD==='devnet'?'devnet':'mainnet',
      admin:wallet.publicKey.toBase58(),'fee-payer':fee.publicKey.toBase58()});
    await r.start();const op=await buildGovernance(r,{multisig:multisig.toBase58(),...input});return {r,op};
  }
  async function execute(action:string,input:any,keys:Keypair[]=[]) {
    const {r,op}=await plan(action,input);if(op.instructions.length)await send(op.instructions,keys);
    await r.finalizedAssert(op.assert);return op;
  }
  before(async()=>{
    expect(new URL(provider.connection.rpcEndpoint).hostname).eq('127.0.0.1');
    const airdrop=await provider.connection.requestAirdrop(fee.publicKey,5e9);await provider.connection.confirmTransaction(airdrop,'finalized');
    const executable=(await provider.connection.getAccountInfo(program.programId,'finalized'))!;
    await send([program.methods.initializeProgramConfig(wallet.publicKey).accounts({programConfig:pda('program_config'),program:program.programId,
      programData:new PublicKey(executable.data.subarray(4,36)),admin:wallet.publicKey,systemProgram:SystemProgram.programId}),
      program.methods.initCityConfig(new BN(1791201600)).accounts({city:pda('s1v1_city'),programConfig:pda('program_config'),admin:wallet.publicKey,systemProgram:SystemProgram.programId})]);
    await send(members.map(member=>SystemProgram.transfer({fromPubkey:wallet.publicKey,toPubkey:member.publicKey,lamports:1e9})));
    await execute('create',{createKey:createKey.publicKey.toBase58(),creator:members[0].publicKey.toBase58(),
      members:members.map(k=>k.publicKey.toBase58()),threshold:2},[createKey,members[0]]);
    await send([program.methods.setStage1Guardian(vault).accounts({city:pda('s1v1_city'),programConfig:pda('program_config'),admin:wallet.publicKey})]);
  });
  for(const [i,call] of ['pauseStage1Intake','resumeStage1Intake','pauseStage1Settlement','resumeStage1Settlement'].entries())
    it(`executes ${call} after two votes, without advancing the clock`,async()=>{
      const input:any={transactionIndex:String(i+1),call,member:members[0].publicKey.toBase58()};
      await execute('propose',input,[members[0]]);
      const reviewed=await execute('check',input);input.transactionSha256=(reviewed.report as any).transactionSha256;
      await execute('approve',input,[members[0]]);
      let error='';try{await plan('execute',input);}catch(e:any){error=e.message;}expect(error).include('threshold');
      await execute('approve',{...input,member:members[1].publicKey.toBase58()},[members[1]]);
      await execute('execute',input,[members[0]]);
      const city=await program.account.stage1CityConfig.fetch(pda('s1v1_city'));
      expect(city[call.endsWith('Intake')?'intakePaused':'settlementPaused']).eq(call.startsWith('pause'));
      expect(city.guardian.equals(vault)).eq(true);
    });
});
