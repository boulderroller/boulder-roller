// Fresh-state cutover gate. Only the city has a historical layout migration;
// immutable recipient registration is unchanged. Never filter by current size.
import { BorshAccountsCoder, utils } from '@coral-xyz/anchor';
import { PublicKey } from '@solana/web3.js';
import { pathToFileURL } from 'url';
import { CURRENT_PROGRAM_VERSION, PREVIOUS_PROGRAM_VERSION } from '../generated-program-version.js';
import { Operator, Operation, args, requireThat, runOperator } from './stage1_operator.js';
import { readCity } from './stage1_governance.js';

export const FRESH_STATE_TYPES = [
  'Stage1ClaimSet', 'Stage1DungClaimSet', 'Stage1AssetConfig', 'Stage1HillBond',
  'Stage1PledgeLot', 'Stage1WithdrawalRequest', 'Stage1SettlementCursor', 'Stage1WeekFunding',
  'Stage1DungMint', 'Stage1DungState', 'Stage1Boost', 'Stage1BoostHill', 'Stage1CashConfig',
  // Include every historical discriminator, even if absent from the selected IDL.
  'Stage1TestPool', 'Stage1ClaimReceipt', 'Stage1ClaimIndex',
] as const;

export async function freshStage1Inventory(r: Operator) {
  const before=await readCity(r);
  requireThat(!before || before.decoded.publisher.equals(PublicKey.default), 'Disable the publisher at finalized commitment before claim inventory');
  const report:Record<string,number>={};
  for(const name of FRESH_STATE_TYPES) {
    const requestedFloor=r.floor;
    const response=await r.connection.getProgramAccounts(r.programId,{commitment:'finalized',minContextSlot:requestedFloor,withContext:true,
      filters:[{memcmp:{offset:0,bytes:utils.bytes.bs58.encode(BorshAccountsCoder.accountDiscriminator(name))}}]});
    requireThat(response.context.slot>=requestedFloor && Array.isArray(response.value),'Incomplete finalized claim inventory');
    r.floor=Math.max(r.floor,response.context.slot);
    report[name]=response.value.length;
    requireThat(response.value.length===0, `Existing ${name} state or entitlements block this fresh-state cutover; compatible migration required`);
  }
  const after=await readCity(r);
  requireThat(!after || after.decoded.publisher.equals(PublicKey.default),'Publisher changed during claim inventory');
  return report;
}

export async function cutoverOperation(r:Operator,input:any):Promise<Operation>{
  requireThat(input && Object.keys(input).length===0,'Cutover takes an explicit empty input object');
  if(r.options.action==='check-upgrade-inventory') {
    const report=await freshStage1Inventory(r);
    return {instructions:[],report,description:'Finalized publisher disabled and complete historical Stage1 inventory is empty except city/recipient',assert:async()=>{await freshStage1Inventory(r);}};
  }
  requireThat(r.options.action==='disable-publisher','Unknown cutover action');
  const city=await readCity(r);
  if(city && !city.decoded.publisher.equals(PublicKey.default))
    requireThat(PublicKey.isOnCurve(r.admin.toBytes()),'An active publisher after vault handoff requires a separately reviewed legacy-compatible delayed operation');
  return {instructions:city && !city.decoded.publisher.equals(PublicKey.default)
    ? [await r.program.methods.setStage1Publisher(PublicKey.default).accounts({city:r.pda('s1v1_city'),programConfig:r.pda('program_config'),admin:r.admin}).instruction()] : [],
    description:'Current admin disables Stage1 publication before the cutover inventory',
    assert:async()=>{const current=await readCity(r);requireThat(!current || current.decoded.publisher.equals(PublicKey.default),'Publisher disable not finalized');}};
}

if(process.argv[1]&&import.meta.url===pathToFileURL(process.argv[1]).href)
  runOperator('stage1-cutover',cutoverOperation,args(),[PREVIOUS_PROGRAM_VERSION,CURRENT_PROGRAM_VERSION]).catch(error=>{console.error(error.message);process.exitCode=1;});
