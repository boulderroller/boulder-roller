const test=require('node:test');
const assert=require('node:assert/strict');
const vectors=require('./fixtures/stage1-boundaries.json');
const {materializeBoundary}=require('../dist/stage1-boundary');
for(const name of ['pledge','bond'])test(`another hill's ${name} cannot hold this hill's week`,()=>{
  const v=structuredClone(vectors[0]);
  const city=v.checkpoint.accounts.find(a=>a.type==='Stage1CityConfig').address;
  const asset=v.checkpoint.accounts.find(a=>a.type==='Stage1AssetConfig').address;
  const tx={signature:'foreign-deposit',slot:101,block_time:v.boundary-1,writes:[city,asset,'foreign-hill','foreign-lot'],
    instructions:[{name,accounts:{hill:'foreign-hill',city,asset},keys:['foreign-hill',city,asset]}],events:[]};
  assert.deepEqual(materializeBoundary(v.checkpoint,v.coverage,[tx],v.hill,v.boundary).records,
    materializeBoundary(v.checkpoint,v.coverage,[],v.hill,v.boundary).records);
  tx.instructions[0].accounts.hill=v.hill;tx.instructions[0].keys.push(v.hill);tx.writes.push(v.hill);
  assert.throws(()=>materializeBoundary(v.checkpoint,v.coverage,[tx],v.hill,v.boundary),/unrecoverable_boundary_mutation/);
});
test('same-slot record writes use block position and hold when position is absent',()=>{
  const v=structuredClone(vectors[0]),board=v.checkpoint.accounts.find(a=>a.type==='VaultLeaderboard');
  const txs=board.fields.entries.map((entry,i)=>({signature:'same-slot-'+i,slot:101,block_index:i,block_time:v.boundary-1,
    writes:[board.address],instructions:[{name:'recordClimbCompletionV2'}],
    events:[{name:'ClimbCompletedV2',fields:{vaultId:board.fields.vaultId,rider:entry.user,timeS:40+i,completedAt:String(v.boundary-1)}}]}));
  assert.deepEqual(materializeBoundary(v.checkpoint,v.coverage,txs.reverse(),v.hill,v.boundary).records.board.map(e=>e.time_s),[40,41]);
  delete txs[0].block_index;
  assert.throws(()=>materializeBoundary(v.checkpoint,v.coverage,txs,v.hill,v.boundary),/ambiguous_same_slot_record_order/);
});
test('first Legend election cannot freeze absence from the earlier checkpoint',()=>{
  const {PublicKey}=require('@solana/web3.js');
  const v=structuredClone(vectors[0]),vault=v.checkpoint.accounts.find(a=>a.type==='Vault');
  const id=Buffer.alloc(8);id.writeBigUInt64LE(BigInt(vault.fields.id));
  const address=PublicKey.findProgramAddressSync([Buffer.from('local_legend'),id],new PublicKey(v.checkpoint.program))[0].toBase58();
  const elected=v.checkpoint.accounts.find(a=>a.type==='LocalLegend');
  v.checkpoint.accounts=v.checkpoint.accounts.filter(a=>a.type!=='LocalLegend');
  const tx={signature:'first-legend',slot:101,block_time:v.boundary-1,writes:[address],
    instructions:[{name:'electLocalLegend',accounts:{vault:vault.address,localLegend:address},keys:[vault.address,address]}],
    events:[{name:'LocalLegendElected',fields:{...elected.fields,winner:elected.fields.holder}}]};
  assert.throws(()=>materializeBoundary(v.checkpoint,v.coverage,[tx],v.hill,v.boundary),/missing_record_legend/);
  v.checkpoint.slot=150;v.checkpoint.block_time=v.boundary+1;
  v.checkpoint.accounts.push({...elected,address});
  assert.equal(materializeBoundary(v.checkpoint,v.coverage,[tx],v.hill,v.boundary).records.legend.person,elected.fields.holder);
});
test('another hill deposit holds only if shared provider rate can change',()=>{
  const v=structuredClone(vectors[0]),asset=v.checkpoint.accounts.find(a=>a.type==='Stage1AssetConfig');
  Object.assign(asset.fields,{adapter:2,admittedEpoch:'0'});
  const tx={signature:'provider-deposit',slot:101,epoch:0,block_time:v.boundary-1,writes:[asset.address],
    instructions:[{name:'pledge',accounts:{hill:'foreign',asset:asset.address},keys:[asset.address,'foreign']}],events:[]};
  assert.ok(materializeBoundary(v.checkpoint,v.coverage,[tx],v.hill,v.boundary).opening);
  tx.epoch=1;
  assert.throws(()=>materializeBoundary(v.checkpoint,v.coverage,[tx],v.hill,v.boundary),/unrecoverable_boundary_mutation/);
  asset.observed_slot=150;asset.observed_time=v.boundary+1;tx.epoch=0;tx.block_time=v.boundary;
  assert.throws(()=>materializeBoundary(v.checkpoint,v.coverage,[tx],v.hill,v.boundary),/unrecoverable_boundary_mutation/);
});
for(const name of ['updateVaultMetadata','stakeCalInVault'])test(`${name} does not alter hill settlement inputs`,()=>{
  const v=structuredClone(vectors[0]),vault=v.checkpoint.accounts.find(a=>a.type==='Vault');
  const tx={signature:'unrelated-vault',slot:101,block_time:v.boundary-1,writes:[vault.address],instructions:[{name,accounts:{vault:vault.address},keys:[vault.address]}],events:[]};
  assert.deepEqual(materializeBoundary(v.checkpoint,v.coverage,[tx],v.hill,v.boundary).records,materializeBoundary(v.checkpoint,v.coverage,[],v.hill,v.boundary).records);
});
for(const v of vectors)test(`independent Python/TypeScript vector: ${v.name}`,()=>{
  const result=materializeBoundary(v.checkpoint,v.coverage,v.transactions,v.hill,v.boundary);
  assert.equal(result.digest,v.digest);
  assert.equal(result.records_digest,v.records_digest);
});
test('later account slice cannot backdate a post-boundary record after pruning',()=>{
  const v=structuredClone(vectors[0]),cp=v.checkpoint;
  cp.slot=180;cp.block_time=v.boundary+1;cp.through_slot=200;
  const board=cp.accounts.find(a=>a.type==='VaultLeaderboard');board.observed_slot=200;board.observed_time=v.boundary+2;
  const tx={signature:'post',slot:190,block_time:v.boundary,writes:[board.address],instructions:[{name:'recordClimbCompletionV2'}],events:[]};
  assert.throws(()=>materializeBoundary(cp,v.coverage,[tx],v.hill,v.boundary),/unrecoverable_boundary_mutation/);
});
test('failed capture retains a newly discovered own-hill lot mutation',()=>{
  const {transactionHills}=require('../dist/stage1-boundary');
  const v=vectors[0],lot='new-lot';
  const tx={writes:[lot],instructions:[{name:'convertExcludedPledge',keys:[lot,v.hill],accounts:{hill:v.hill}}],events:[]};
  assert.deepEqual(transactionHills(tx,[{...v.checkpoint,hill:v.hill}],[{hill:v.hill,address:lot}]),[v.hill]);
  assert.deepEqual(transactionHills(tx,[{...v.checkpoint,hill:'other'}],[{hill:'other',address:'unrelated'}]),[]);
});
test('atomic completions on two hills replay only this hill record',()=>{
 const v=structuredClone(vectors[0]),board=v.checkpoint.accounts.find(a=>a.type==='VaultLeaderboard'),vault=v.checkpoint.accounts.find(a=>a.type==='Vault'),config=v.checkpoint.accounts.find(a=>a.type==='ProgramConfig');
 const tx={signature:'mixed',slot:101,block_time:v.boundary-1,block_index:0,writes:[board.address,'foreign-board'],
  instructions:[{name:'recordClimbCompletionV2',keys:[vault.address,config.address],accounts:{vault:vault.address}},{name:'recordClimbCompletionV2',keys:['foreign-vault',config.address],accounts:{vault:'foreign-vault'}}],
  events:[{name:'ClimbCompletedV2',fields:{vaultId:vault.fields.id,rider:board.fields.entries[1].user,timeS:30,completedAt:String(v.boundary-1)}},{name:'ClimbCompletedV2',fields:{vaultId:'99',rider:board.fields.entries[0].user,timeS:20,completedAt:String(v.boundary-1)}}]};
 assert.equal(materializeBoundary(v.checkpoint,v.coverage,[tx],v.hill,v.boundary).records.board[0].time_s,30);
});
test('anonymous existing seat does not block an unambiguous survivor improvement',()=>{
 const v=structuredClone(vectors[0]),a=v.checkpoint.accounts.find(a=>a.type==='VaultLeaderboard');
 const before=a.fields.entries[0],other=a.fields.entries[1].user;before.user='anonymous:fixture';delete before.recordedAt;
 a.record_order=[before.user,other];a.record_not_before=v.boundary;
 const tx={signature:'better',slot:101,block_time:v.boundary-1,block_index:0,writes:[a.address],instructions:[{name:'recordClimbCompletionV2'}],events:[{name:'ClimbCompletedV2',fields:{vaultId:a.fields.vaultId,rider:other,timeS:50,completedAt:String(v.boundary-1)}}]};
 const result=materializeBoundary(v.checkpoint,v.coverage,[tx],v.hill,v.boundary);
 assert.equal(result.records.seats[0],other);assert.equal(result.records.board[0].time_s,50);
});
