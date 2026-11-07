const test = require('node:test');
const assert = require('node:assert/strict');
const { encodeFields, decodeTransactionWitness } = require('../dist/stage1');
const { PublicKey } = require('@solana/web3.js');
const { BN } = require('@coral-xyz/anchor');

test('ABI serialization retains numeric arrays and full unsigned integers', () => {
  assert.deepEqual(encodeFields({units:new BN('18446744073709551615'), values:[0,1,2], key:PublicKey.default}),
    {units:'18446744073709551615', values:[0,1,2], key:PublicKey.default.toBase58()});
});
test('activation resumes discovery and recognizes successful version advance without logs',async(t)=>{
  const db=require('../dist/db'),{activation}=require('../dist/stage1');
  const {config}=require('../dist/config'),{getCoder}=require('../dist/decoder');
  const address=new PublicKey(Buffer.alloc(32,1)),admin=new PublicKey(Buffer.alloc(32,2));
  let saved,missing=true,reads=[];
  t.mock.method(db,'query',async(sql,params)=>{
    if(sql.startsWith('SELECT'))return {rows:saved?[saved]:[]};
    saved=sql.includes('(genesis,program,slot,kind)')?{slot:params[2],kind:params[3]}:{before:params[2]};
    return {rows:[]};
  });
  const transaction=name=>({slot:name==='advanceProgramVersion'?120:130,blockTime:100,
    transaction:{message:{staticAccountKeys:[address,admin,new PublicKey(config.programId)],header:{numRequiredSignatures:1,numReadonlySignedAccounts:0,numReadonlyUnsignedAccounts:1},
      compiledInstructions:[{programIdIndex:2,accountKeyIndexes:[0,1],data:getCoder().instruction.encode(name,name==='advanceProgramVersion'?{expectedCurrentVersion:76,newVersion:77}:{backendAuthority:admin})}]}},meta:{err:null,logMessages:[]}});
  const rpc={getSignaturesForAddress:async(_a,options)=>options.before?[{signature:'advance',slot:120,err:null}]:[{signature:'update',slot:130,err:null},{signature:'advance',slot:120,err:null}],
    getTransaction:async(signature)=>{reads.push(signature);if(signature==='advance'&&missing)return null;return transaction(signature==='advance'?'advanceProgramVersion':'updateProgramConfig');}};
  await assert.rejects(()=>activation(rpc,'genesis',address.toBase58(),{slot:200}),/Missing activation transaction/);
  assert.equal(saved.before,'update');missing=false;
  assert.equal(await activation(rpc,'genesis',address.toBase58(),{slot:200}),120);
  assert.deepEqual(reads,['update','advance','advance']);
  assert.equal(await activation(rpc,'genesis',address.toBase58(),{slot:300}),120);
  assert.equal(reads.length,3);
});
test('same-slot projections follow block order before publication, payment and closure',async()=>{
  const {orderStage1Pending}=require('../dist/stage1');
  const pending=['claim','close','publish'].map(signature=>({signature,slot:42}));
  const rpc={getBlockSignatures:async()=>({signatures:['publish','claim','close']})};
  const ordered=await orderStage1Pending(rpc,pending,async()=>assert.fail('unexpected missing block'));
  assert.deepEqual(ordered.map(r=>[r.signature,r.block_index]),[['publish',0],['claim',1],['close',2]]);
});

test('finalized witness includes ALT writable keys, CPI and remaining accounts', () => {
  const keys = [1,2,3,4].map(n => new PublicKey(Buffer.alloc(32,n)));
  const tx = {slot:42,blockTime:100,transaction:{message:{staticAccountKeys:keys.slice(0,2),
    header:{numRequiredSignatures:1,numReadonlySignedAccounts:0,numReadonlyUnsignedAccounts:1},compiledInstructions:[]}},
    meta:{err:null,loadedAddresses:{writable:[keys[2]],readonly:[keys[3]]},innerInstructions:[],logMessages:[]}};
  const result = decodeTransactionWitness('sig',tx);
  assert.deepEqual(result.writes,[keys[0].toBase58(),keys[2].toBase58()].sort());
  tx.meta.err = {InstructionError:[0,'Custom']};
  assert.deepEqual(decodeTransactionWitness('failed',tx).writes,[]);
});

test('nested CPI batch maps ALT remaining claim sets and full-width leaf amounts', () => {
  const { config }=require('../dist/config');
  const { getCoder }=require('../dist/decoder');
  require('../dist/program-version-window').programVersionWindow.observe(0x4d);
  const bs58=require('bs58');
  const keys=[new PublicKey(Buffer.alloc(32,7)),new PublicKey(Buffer.alloc(32,8)),new PublicKey(config.programId)];
  const loaded=Array.from({length:8},(_,i)=>new PublicKey(Buffer.alloc(32,20+i)));
  const person=new PublicKey(Buffer.alloc(32,9));
  const data=getCoder().instruction.encode('claimStage1Batch',{person,leaves:[{index:0,amount:new BN('18446744073709551615'),proof:[]},{index:1,amount:new BN(4),proof:[]}]});
  const tx={slot:43,blockTime:101,transaction:{message:{staticAccountKeys:keys,header:{numRequiredSignatures:1,numReadonlySignedAccounts:0,numReadonlyUnsignedAccounts:2},compiledInstructions:[{programIdIndex:1,accountKeyIndexes:[],data:Buffer.alloc(0)}]}},
    meta:{err:null,loadedAddresses:{writable:loaded,readonly:[]},logMessages:[],innerInstructions:[{index:0,instructions:[{programIdIndex:2,accounts:[3,4,5,6,7,8,9,10],data:bs58.encode(data)}]}]}};
  const witness=decodeTransactionWitness('nested',tx),ix=witness.instructions[0];
  assert.equal(ix.name,'claimStage1Batch');assert.equal(ix.args.person,person.toBase58());
  assert.equal(ix.args.leaves[0].amount,'18446744073709551615');
  assert.equal(ix.accounts.remaining_0,loaded[6].toBase58());assert.equal(ix.accounts.remaining_1,loaded[7].toBase58());
});

test('an unknown block position holds its slot and every later slot',async()=>{
  const {orderStage1Pending}=require('../dist/stage1');
  const rpc={getBlockSignatures:async slot=>({signatures:slot===42?[]:['later']})};
  const ordered=await orderStage1Pending(rpc,[{signature:'missing',slot:42},{signature:'peer',slot:42},{signature:'later',slot:43}],async()=>{});
  assert.deepEqual(ordered,[]);
});

test('singleton program slots do not fetch or invent absolute block positions',async()=>{
  const {orderStage1Pending}=require('../dist/stage1');let reads=0;
  const result=await orderStage1Pending({getBlockSignatures:async()=>{reads++;return {signatures:['only']};}},[{signature:'only',slot:42}],async()=>{});
  assert.equal(reads,0);assert.equal(result.length,1);assert.equal(result[0].block_index,undefined);
});
