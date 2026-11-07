import { expect } from 'chai';
import * as anchor from '@coral-xyz/anchor';
import { Keypair, PublicKey } from '@solana/web3.js';
import { readFileSync } from 'fs';
import { freshStage1Inventory, cutoverOperation, FRESH_STATE_TYPES } from '../scripts/stage1_cutover.js';
import { Operator } from '../scripts/stage1_operator.js';

function fixture(length=963){
  const programId=PublicKey.unique(),city=PublicKey.unique(),admin=PublicKey.unique();
  const program:any=new anchor.Program(JSON.parse(readFileSync(new URL('../idl/boulder_rollers.json',import.meta.url),'utf8')),programId,{connection:{},wallet:{publicKey:admin}} as any);
  const data=Buffer.alloc(length);anchor.BorshAccountsCoder.accountDiscriminator('Stage1CityConfig').copy(data);
  const account={owner:programId,executable:false,data};let queries=0,match:any[]=[];
  const r:any={programId,program,admin,floor:100,options:{action:'check-upgrade-inventory'},pda:()=>city,read:async()=>account,
    connection:{getProgramAccounts:async(_:any,config:any)=>{queries++;expect(config).include({commitment:'finalized',minContextSlot:100,withContext:true});expect(config.filters).length(1);expect(config.filters[0]).keys('memcmp');return {context:{slot:100},value:match};}}};
  return {r,account,setMatches:(value:any[])=>match=value,queries:()=>queries};
}
async function refuses(action:Promise<any>,text:string){let error='';try{await action;}catch(e:any){error=e.message;}expect(error).include(text);}
describe('fresh Stage1 state cutover inventory',()=>{
  for(const length of [881,897,914,915,931,963])it(`checks legacy/current city ${length} with no layout-size filter`,async()=>{
    const f=fixture(length);expect(await freshStage1Inventory(f.r)).deep.eq(Object.fromEntries(FRESH_STATE_TYPES.map(name=>[name,0])));expect(f.queries()).eq(FRESH_STATE_TYPES.length);
  });
  it('refuses active publication before scanning any claim accounts',async()=>{
    const f=fixture();const decoded=f.r.program.coder.accounts.decode('Stage1CityConfig',f.account.data);decoded.publisher=PublicKey.unique();f.account.data=await f.r.program.coder.accounts.encode('Stage1CityConfig',decoded);
    await refuses(freshStage1Inventory(f.r),'Disable the publisher');expect(f.queries()).eq(0);
  });
  it('refuses any receipt-era or undecodable claim-set match',async()=>{
    for(const length of [0,106,361,393]){const f=fixture();f.setMatches([{pubkey:PublicKey.unique(),account:{owner:f.r.programId,data:Buffer.alloc(length)}}]);await refuses(freshStage1Inventory(f.r),'entitlements block');}
  });
  it('does not treat RPC failure or stale context as an empty inventory',async()=>{
    const f=fixture();f.r.connection.getProgramAccounts=async()=>{throw Error('provider unavailable');};await refuses(freshStage1Inventory(f.r),'provider unavailable');
    f.r.connection.getProgramAccounts=async()=>({context:{slot:99},value:[]});await refuses(freshStage1Inventory(f.r),'Incomplete');
  });
  it('rejects inventory older than the finalized publisher-disable observation',async()=>{
    const f=fixture();f.r.before=new Map();f.r.read=Operator.prototype.read.bind(f.r);
    f.r.connection.getAccountInfoAndContext=async()=>({context:{slot:120},value:f.account});
    f.r.connection.getProgramAccounts=async()=>({context:{slot:110},value:[]});
    await refuses(freshStage1Inventory(f.r),'Incomplete');
  });
  it('carries each inventory response slot into the next scan',async()=>{
    const f=fixture();let calls=0;
    f.r.connection.getProgramAccounts=async(_:any,config:any)=>{
      expect(config.minContextSlot).eq(calls ? 120 : 100);calls++;
      return {context:{slot:120},value:[]};
    };
    await freshStage1Inventory(f.r);expect(calls).eq(FRESH_STATE_TYPES.length);
  });
  it('checks the finalized empty inventory again on an idempotent operation',async()=>{
    const f=fixture();const operation=await cutoverOperation(f.r,{});expect(operation.instructions).length(0);f.setMatches([{}]);await refuses(operation.assert(),'entitlements block');
  });
  it('refuses older financial/configuration state even with no published claims',async()=>{
    for(const name of ['Stage1AssetConfig','Stage1HillBond','Stage1PledgeLot','Stage1WithdrawalRequest',
      'Stage1SettlementCursor','Stage1WeekFunding','Stage1DungMint','Stage1DungState','Stage1Boost',
      'Stage1BoostHill','Stage1CashConfig','Stage1TestPool','Stage1ClaimReceipt','Stage1ClaimIndex']) {
      const f=fixture();const discriminator=anchor.utils.bytes.bs58.encode(anchor.BorshAccountsCoder.accountDiscriminator(name));
      f.r.connection.getProgramAccounts=async(_:any,config:any)=>({context:{slot:100},value:
        config.filters[0].memcmp.bytes===discriminator ? [{pubkey:PublicKey.unique(),account:{data:Buffer.alloc(351)}}] : []});
      await refuses(freshStage1Inventory(f.r),name);
    }
  });
  it('refuses an impossible direct-signature disable after legacy vault handoff',async()=>{
    const f=fixture();f.r.options.action='disable-publisher';
    f.r.admin=PublicKey.findProgramAddressSync([Buffer.from('vault')],f.r.programId)[0];
    const decoded=f.r.program.coder.accounts.decode('Stage1CityConfig',f.account.data);decoded.publisher=Keypair.generate().publicKey;
    f.account.data=await f.r.program.coder.accounts.encode('Stage1CityConfig',decoded);
    await refuses(cutoverOperation(f.r,{}),'legacy-compatible delayed operation');
  });
});
