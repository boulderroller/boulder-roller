const test=require('node:test'),assert=require('node:assert/strict');
const {buildAccountRoom}=require('../dist/account-room');
const wallet='A'.repeat(32),sig='B'.repeat(88);
const fresh={account_slot:5,tx_slot:5,last_account_sync_at:'2026-09-08T00:00:00Z',last_tx_sync_at:'2026-09-08T00:00:00Z'};
const query=async sql=>({rows:sql.includes('account-room:profile')?[{username:'tim',is_public:true,moderation_state:'visible'}]:sql.includes('account-room:rides')?[{rides:'2'}]:[]});
test('Account abstains without indexed checkpoint but retains individual live custody',async()=>{
 const r=await buildAccountRoom(query,wallet,{},[],[{account:wallet,symbol:'CAL',amount:'3'}]);
 assert.equal(r.rides_attested,undefined);assert.deepEqual(r.positions,[]);assert.equal(r.balances.length,1);
});
test('Account requires one explicitly public visible identity',async()=>{
 const r=await buildAccountRoom(query,wallet,fresh,[],[]);assert.equal(r.handle,'@tim');assert.equal(r.rides_attested,2);
 const q=async sql=>({rows:sql.includes('profile')?[{username:'secret',is_public:false,moderation_state:'visible'}]:[]});
 assert.equal((await buildAccountRoom(q,wallet,fresh,[],[])).handle,undefined);
});
test('rider-only events and received custody do not collapse into generic user or allocation rows',async()=>{
 const calls=[];
 const q=async(sql)=>{calls.push(sql);return {rows:sql.includes('account-room:paid')?[{vault_id:7,tx_signature:sig,fields:{dung_received:'50'}}]:[]}};
 const r=await buildAccountRoom(q,wallet,fresh,[{id:'climb',vault_id:7,display_name:'Wises Mill Road'}],[]);
 assert.equal(r.settlements[0].dung,'50');assert.equal(r.settlements[0].week,undefined);
 for(const label of ['first','related','activity'])assert.match(calls.find(s=>s.includes('account-room:'+label)),/fields->>'rider'/);
 assert.match(calls.find(s=>s.includes('account-room:paid')),/RewardsHarvested/);
 assert.deepEqual(r.balances,[]);
});
test('an event without a vault never acquires an unrelated canon climb',async()=>{
 const q=async sql=>({rows:sql.includes('account-room:activity')?[{vault_id:null,event_name:'RideAttestationRecorded',tx_signature:sig,fields:{rider:wallet}}]:[]});
 const r=await buildAccountRoom(q,wallet,fresh,[{id:'wrong',vault_id:null,display_name:'Unrelated'}],[]);
 assert.equal(r.activity[0].object.type,'rider');assert.equal(r.activity[0].climb_id,undefined);
});
