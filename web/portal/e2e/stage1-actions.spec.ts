import { test, expect, type Page } from '@playwright/test';
import fs from 'node:fs';
import path from 'node:path';
import { PublicKey } from '@solana/web3.js';
import { stage1Copy } from '../src/lib/stage1Copy';
const vectors = JSON.parse(fs.readFileSync(path.resolve('scripts/fixtures/prepared-stage1-transactions.json'), 'utf8'));
const vector = (name: string) => vectors.find((v: any) => v.name === name);
const base = vector('pledge_bonded'), wallet = base.wallet, hill = base.intent.hill, climb = '00000000-0000-0000-0000-000000000001';
const lotAddress = vector('notice').request.lot, requestAddress = vector('cancel-notice').request.request;
const zero = '11111111111111111111111111111111';
const asset = { mint: base.intent.mint, slot: 0, adapter: 2, enabled: true, admittedEpoch: '40', admittedNumerator: '1', admittedDenominator: '1' };
const city = { seasonAnchor: '0', intakePaused: false, providerSlots: 7, assetCount: 3 };
const hillState = { bonded: true, foundingCutoff: '1', foundingFreshSlots: 0, assetLots: ['1','1','1'] };
const evidence = process.env.STAGE1_PORTAL_EVIDENCE;
// cash_claim_1 in the devnet city's cash mint: the backend bytes with each mint-derived account swapped in place.
{
  const v = vector('cash_claim_1'), mint = '932CwEMTWHDY1BEkV66DKDgngeEypU3JmybWBu4vMh1e', program = new PublicKey('EVjP2Vdz9buHNphywPhoybf213poa8EiSW6FGbXWFqYH');
  const accounts = (value: string) => { const key = new PublicKey(value), pda = (seed: string, ...parts: Uint8Array[]) => PublicKey.findProgramAddressSync([Buffer.from(seed), ...parts], program)[0];
    const ata = PublicKey.findProgramAddressSync([new PublicKey(v.wallet).toBytes(), new PublicKey('TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA').toBytes(), key.toBytes()], new PublicKey('ATokenGPvbdGVxr1b2hvZbsiqW5xWH25efTNsLJA8knL'))[0];
    return [key, pda('s1v1_asset', key.toBytes()), pda('s1v1_earnings', key.toBytes()), ata, ...v.intent.claims.map((leaf: any) => { const week = Buffer.alloc(8); week.writeBigUInt64LE(BigInt(leaf.week)); return pda('s1v1_claims', new PublicKey(leaf.hill).toBytes(), key.toBytes(), week); })]; };
  const wire = Buffer.from(v.prepared.transaction, 'base64'), swapped = accounts(mint);
  accounts(v.intent.mint).forEach((key, i) => { const at = wire.indexOf(key.toBuffer()); if (at < 0 || wire.indexOf(key.toBuffer(), at + 1) >= 0) throw new Error('Fixture account is not a unique static key'); swapped[i].toBuffer().copy(wire, at); });
  vectors.push({ ...v, name: 'cash_claim_devnet', prepared: { ...v.prepared, transaction: wire.toString('base64') }, intent: { ...v.intent, mint } });
}
async function setup(page: Page, name: string, mode = 'eligible') {
  const v = vector(name === 'cash_transport' ? 'cash_lookup_create' : name), calls: Array<{ path: string; body: any }> = [];
  await page.addInitScript(({ requestId }) => {
    localStorage.setItem('br_authenticated','true'); localStorage.setItem('br_setup_reprompt_dismissed','true');
    (window as any).__stage1SignCalls = 0;
    const original = crypto.getRandomValues.bind(crypto);
    crypto.getRandomValues = ((a: any) => { if (a instanceof Uint32Array && a.length === 2) { a[0]=0;a[1]=requestId;return a; } return original(a); }) as typeof crypto.getRandomValues;
  }, { requestId: name === 'notice' ? 8 : 7 });
  // Wallet fixture boundary only. Real production intent validation runs before this bridge mounts/signs.
  await page.route('**/src/components/auth/WalletTransactionSignerBridge.tsx*', async route => {
    const response = await route.fetch(); const source = await response.text();
    const react = source.match(/from ["']([^"']*react\.js[^"']*)["']/)?.[1];
    if (!react) throw new Error('Fixture could not resolve the existing React module');
    await route.fulfill({ contentType: 'text/javascript', body: `import React from '${react}'; const {useEffect}=React; export function WalletTransactionSignerBridge({enabled,onSignerReady}) {useEffect(()=>{if(enabled)onSignerReady(async(p)=>{window.__stage1SignCalls++;return p.transaction});return()=>onSignerReady(null)},[enabled,onSignerReady]);return null;}` });
  });
  let transportMode = 'create', lookupReads = 0, durableLookup = mode === 'durable';
  await page.route('**/*', async route => {
    const req=route.request(), url=new URL(req.url());
    if (!['fetch','xhr'].includes(req.resourceType()) || url.pathname.startsWith('/src/') || url.pathname.startsWith('/node_modules/')) return route.fallback();
    const rpc = req.method() === 'POST' ? req.postDataJSON() : null;
    if (rpc?.jsonrpc) {
      const source=vector('cash_claim_depth16');
      const raw=Buffer.alloc(56 + source.lookup.addresses.length * 32); raw.writeUInt32LE(1,0);raw.writeBigUInt64LE(transportMode==='create' ? (1n<<64n)-1n : 1234n,4);raw.writeBigUInt64LE(1n,12);raw[21]=1;new PublicKey(wallet).toBuffer().copy(raw,22);source.lookup.addresses.forEach((a:string,i:number)=>new PublicKey(a).toBuffer().copy(raw,56+i*32));
      const result=rpc.method==='getSignatureStatuses' ? {context:{slot:2345},value:[mode==='transport-recovered' ? {slot:1234,confirmations:null,confirmationStatus:'finalized',err:null} : null]} : rpc.method==='isBlockhashValid' ? {context:{slot:2345},value:mode==='unknown-response'||mode.startsWith('duplicate-')} : rpc.method==='getSlot' ? (transportMode==='create' ? 1234 : 2345) : {context:{slot:2345},value: {owner:'AddressLookupTab1e1111111111111111111111111',executable:false,lamports:1,rentEpoch:0,data:[raw.toString('base64'),'base64']}};
      return route.fulfill({json:{jsonrpc:'2.0',id:rpc.id,result}});
    }
    const p=url.pathname.replace(/^\/api/,''); let body: any = {};
    if (p.startsWith('/stage1/')) {
      if (p === '/stage1/me/lookups') body={ tables:durableLookup && transportMode !== 'close' ? [{address:vector('cash_lookup_create').intent.lookupTable,state:mode==='finality-lag' && lookupReads++===0 ? 'missing' : transportMode === 'create' ? 'active' : 'closeable'}]:[],nextOffset:null };
      else if (p === '/stage1/me/eligibility') body={ chainTime:mode==='stale-clock' ? String(1791201600+40*604800+60) : '24192010',week:'40',actions:{ 'convert-pledge':{refreshRate:true},'begin-withdrawal':{refreshRate:true},'complete-withdrawal':{refreshRate:true} } };
      else if (req.method()==='POST') {
        calls.push({ path:p, body:req.postDataJSON() });
        if (!p.endsWith('/prepare') && mode === 'pause-during-submit') return route.fulfill({ json: {
          operation: { operationId: 'fixture-operation' }, withdrawalsPausedUntil: String(Math.floor(Date.now() / 1000) + 60),
        } });
        if (!p.endsWith('/prepare') && mode.startsWith('duplicate-')) return route.fulfill({status:409,json:{detail:{code:'stage1_operation_pending',operation_id:'other-tab-operation',reference_id:v.prepared.pda}}});
        if (!p.endsWith('/prepare') && mode === 'submit-rejected') return route.fulfill({status:409,json:{detail:'unavailable'}});
        if (!p.endsWith('/prepare') && ['lost-response','unknown-response','transport-recovered'].includes(mode)) { if(mode==='transport-recovered')durableLookup=true;return route.abort('failed'); }
        if (mode==='unavailable') return route.fulfill({ status:503, json:{ detail:'unavailable' } });
        const preparedVector = name === 'cash_transport' ? vector(p.includes('/self-claim') ? 'cash_claim_depth16' : `cash_lookup_${req.postDataJSON().mode}`) : v;
        if(name==='cash_transport' && !p.endsWith('/prepare') && req.postDataJSON().mode) {transportMode=req.postDataJSON().mode;durableLookup=true;}
        body=p.endsWith('/prepare') ? { preparedTransaction: mode==='mismatch' ? vector('pledge_prebond_52').prepared : preparedVector.prepared, intent: mode==='mismatch' ? vector('pledge_prebond_52').intent : v.intent } : { operation: { operationId:'fixture-operation' } };
      } else if (p.endsWith('/hill')) body={ hill };
      else if (p.endsWith('/bonding')) body={ hill, climb:base.intent.climb, bonded:true, hillState, cityState:city, week:40, chainTime:'24192010', chainEpoch:'40', assets:[{ mint:asset.mint, config:asset, backingLamports:'1000000000' }, {mint:vector('cash_claim_1').intent.mint,config:{...asset,mint:vector('cash_claim_1').intent.mint,adapter:255}}] };
      else if (p.endsWith('/registration')) body={ registration:name==='registration' ? null : { person:wallet,recipient:wallet }, held:[] };
      else if (p.endsWith('/pay') || p.endsWith('/dung')) body={ paid:[],pending:[] };
      else if (p.endsWith('/claims') && name==='cash_transport') { const source=vector('cash_claim_depth16');const {single,...intent}=source.intent;body={claims:[{reference:source.request.claims[0],intent,requiresLookup:true}],nextOffset:null}; }
      else if (p.endsWith('/claims')) body={ claims:name.startsWith('cash_claim')||name.startsWith('dung_claim') ? [{ reference:v.request.claims[0], intent:v.intent,requiresLookup:false }] : [],nextOffset:null };
      else if (p.endsWith('/pledges')) {
        const pending=['cancel-notice','begin-withdrawal','complete-withdrawal'].includes(name);
        const excluded=name==='cancel-pledge'||name.startsWith('convert');
        const lot:any={ address:lotAddress, depositId:'7',hill,climbName:'Fixture canonical hill',mint:asset.mint,units:'123',basisLamports:name==='notice'?'100':'200',lockWeeks:0,lockEnd:'0',pendingRequest:pending?requestAddress:zero,sequence:excluded?'1':'2',cancelled:false,exiting:false,converted:false,founding:false,hillState,cityState:city,assetState:asset,chainTime:'24192010',chainEpoch:'40',withdrawals:pending?[{address:requestAddress,parentDepositId:'7',data:{requestId:'8',lot:lotAddress,exitLot:vector('complete-withdrawal').request.lot,basisLamports:'100',eligibleAt:'100',status:0}}]:[] };
        if(name==='complete-withdrawal'){lot.address=v.request.lot;lot.depositId='0';lot.exiting=true;lot.exitRequest=requestAddress;lot.withdrawals[0].data.status=1;}
        if(mode==='stale-clock'){lot.cityState={...city,seasonAnchor:'1791201600'};lot.chainTime=String(1791201600+40*604800-10800);lot.lockEnd=String(1791201600+40*604800);if(lot.withdrawals.length)lot.withdrawals[0].data.eligibleAt=String(1791201600+40*604800);}
        if(mode==='locked')lot.lockEnd='99999999';
        if(mode==='returned'){lot.units='0';lot.basisLamports='0';lot.returnedUnits='123';}
        if(mode==='cancelled')lot.cancelled=true;
        if(mode==='not-due')lot.withdrawals[0].data.eligibleAt='99999999';
        body={pledges:name==='registration'||name.startsWith('pledge')||(name.includes('claim')||name==='cash_transport')?[]:[lot]};
      }
    } else if(p.startsWith('/auth/'))body={ authenticated:true,authMethodHint:'wallet',invite_required:false,invite_validated:true,needs_profile_setup:false,user:{id:'action-rider',wallet,username:'fixture',preferred_units:'metric',theme_id:'hoo-breddin',is_dark_mode:false}};
    else if(p==='/status')body={stage1:{live:true,actions:mode!=='actions-off'},balanceRollout:{enforced:true,orderValid:true,enabledActions:[],blockers:[]}};
    else if(p.startsWith('/balance/operations/') && mode==='pause-during-submit')body={operationId:'fixture-operation',recorded:false,pending:true,needsReview:false,readState:'pending'};
    else if(p.startsWith('/balance/operations/') && mode.startsWith('duplicate-')) { if(!p.endsWith('/other-tab-operation'))return route.fulfill({status:404,json:{}});body={operationId:'other-tab-operation',recorded:false,pending:false,needsReview:true,readState:'needs_review',stage1TerminalFailure:mode==='duplicate-failed'}; }
    else if(p.startsWith('/balance/operations/') && ['lost-response','unknown-response','transport-recovered'].includes(mode))return route.fulfill({status:404,json:{}});
    else if(p.startsWith('/balance/operations/'))body={operationId:'fixture-operation',recorded:true,pending:false,needsReview:false,readState:'recorded'};
    else if(p==='/portfolio/snapshot')body={portfolio:{stakedPositions:[]},distributions:{distributions:[]}};
    else if(p===`/climbs/${climb}`)body={id:climb,canonId:climb,name:'Fixture canonical hill',hasVault:false,vaultCreation:{state:'unavailable',paymentMethods:[]}};
    else if(p.endsWith('/leaderboard'))body={leaderboard:[]};
    else if(p==='/users/me/leaderboard-positions')body={positions:[],stats:{}};
    else if(p==='/notifications')body={notifications:[],unreadCount:0};
    else if(p.startsWith('/compliance/deletion'))return route.fulfill({status:404,json:{}});
    else if(p==='/rides')body=[];
    return route.fulfill({json:body});
  });
  await page.goto(name.startsWith('pledge') ? `/climbs/${climb}` : '/profile?tab=portfolio');
  return calls;
}
async function hold(page:Page) { const b=page.getByRole('button',{name:stage1Copy.hold,exact:true});await b.focus();await page.keyboard.down(' ');await page.waitForTimeout(700);await page.keyboard.up(' '); }
test('pledge picker offers only configured staking assets',async({page})=>{
  await setup(page,'pledge_bonded');await page.locator('[data-stage1-action="pledge"]').click();
  await expect(page.getByLabel(stage1Copy.token).locator('option')).toHaveText(['jitoSOL']);
});
for(const name of ['registration','pledge_bonded','notice','cancel-notice','begin-withdrawal','complete-withdrawal','cancel-pledge','convert_13','cash_claim_1','dung_claim_1']) for(const width of [1440,390]) test(`${name} checked hold and operation ${width}`,async({page})=>{
  await page.setViewportSize({width,height:900});const v=vector(name), calls=await setup(page,name);
  if (['notice','cancel-notice','begin-withdrawal','complete-withdrawal','cancel-pledge','convert_13'].includes(name)) await page.getByRole('button',{name:stage1Copy.pledgeActions,exact:true}).click();
  if(evidence)await page.screenshot({path:path.join(evidence,`phase3-actions-${name}-${width}.png`),fullPage:true});
  await page.locator(`[data-stage1-action="${v.action}"]`).click();
  if(name==='pledge_bonded')await page.getByLabel(stage1Copy.amount,{exact:true}).fill('0.000000123');
  if(name==='pledge_bonded'||name==='convert_13')await page.getByLabel(stage1Copy.lock,{exact:true}).selectOption('13');
  await page.getByRole('button',{name:'Continue',exact:true}).click();
  await expect(page.locator(`[data-stage1-hold="${v.action}"]`)).toBeVisible();
  expect(await page.evaluate(()=>(window as any).__stage1SignCalls)).toBe(0);
  if(evidence)await page.screenshot({path:path.join(evidence,`phase3-hold-${name}-${width}.png`),fullPage:true});
  await hold(page);
  await expect.poll(() => page.evaluate(()=>(window as any).__stage1SignCalls)).toBe(1);
  await expect(page.getByRole('status').filter({hasText:'Confirmed'})).toBeVisible();
  expect(await page.evaluate(()=>(window as any).__stage1SignCalls)).toBe(1);
  expect(calls.filter(c=>!c.path.endsWith('/prepare'))).toHaveLength(1);
  expect(calls[0].body).toMatchObject(Object.fromEntries(Object.entries(v.request).filter(([k,v])=>k!=='refresh_rate' && v != null)));
});
test('devnet city cash claim shows USDC and signs once without a test-pool read',async({page})=>{
  // The harness answers any account read with a non-pool account, so a test-pool read would refuse this claim.
  await setup(page,'cash_claim_devnet');await page.locator('[data-stage1-action="self-claim"]').click();
  await page.getByRole('button',{name:'Continue',exact:true}).click();
  await expect(page.locator('[data-stage1-hold="self-claim"]')).toContainText('0.0001 USDC');
  await hold(page);await expect(page.getByRole('status').filter({hasText:'Confirmed'})).toBeVisible();
  expect(await page.evaluate(()=>(window as any).__stage1SignCalls)).toBe(1);
});
for(const mode of ['mismatch','unavailable'])test(`refuse ${mode} before signing`,async({page})=>{
 const calls=await setup(page,'pledge_bonded',mode);await page.locator('[data-stage1-action="pledge"]').click();await page.getByLabel(stage1Copy.amount,{exact:true}).fill('0.000000123');await page.getByLabel(stage1Copy.lock,{exact:true}).selectOption('13');await page.getByRole('button',{name:'Continue',exact:true}).click();await expect(page.getByRole('status').filter({hasText:'Needs review'})).toBeVisible();expect(await page.evaluate(()=>(window as any).__stage1SignCalls)).toBe(0);expect(calls).toHaveLength(1);await expect(page.locator('[data-stage1-hold]')).toHaveCount(0);
});
for(const mode of ['locked','returned','cancelled'])test(`${mode} lot has no notice`,async({page})=>{await setup(page,'notice',mode);await expect(page.locator('[data-stage1-pledge]')).toBeVisible();if(mode==='locked')await page.getByRole('button',{name:stage1Copy.pledgeActions,exact:true}).click();await expect(page.locator('[data-stage1-action]')).toHaveCount(0);});
test('notice before due can only cancel',async({page})=>{await setup(page,'begin-withdrawal','not-due');await page.getByRole('button',{name:stage1Copy.pledgeActions,exact:true}).click();await expect(page.locator('[data-stage1-action="cancel-notice"]')).toBeVisible();await expect(page.locator('[data-stage1-action="begin-withdrawal"]')).toHaveCount(0);});

for(const width of [1440,390])test(`oversized claim transport creation claim and rent recovery ${width}`,async({page})=>{
  await page.setViewportSize({width,height:900});await setup(page,'cash_transport');
  await page.locator('[data-stage1-action="self-claim"]').click();
  for(const action of ['claim-transport','self-claim']) {
    await page.getByRole('button',{name:'Continue',exact:true}).click();
    await expect(page.locator(`[data-stage1-hold="${action}"]`)).toBeVisible();
    if(evidence)await page.screenshot({path:path.join(evidence,`phase3-hold-${action}-oversized-${width}.png`),fullPage:true});
    await hold(page);await expect(page.getByRole('status').filter({hasText:'Confirmed'})).toBeVisible();
  }
  await page.getByRole('button',{name:'Close',exact:true}).click();
  for(const mode of ['deactivate','close']) {
    await page.getByRole('button',{name:mode==='deactivate'?stage1Copy.deactivateTransport:stage1Copy.closeTransport,exact:true}).click();
    await page.getByRole('button',{name:'Continue',exact:true}).click();await expect(page.locator('[data-stage1-hold="claim-transport"]')).toBeVisible();
    if(evidence)await page.screenshot({path:path.join(evidence,`phase3-hold-transport-${mode}-${width}.png`),fullPage:true});
    await hold(page);
    // The completed cleanup component disappears when its indexed/chain state changes.
    await expect(page.getByRole('button',{name:mode==='deactivate'?stage1Copy.deactivateTransport:stage1Copy.closeTransport,exact:true})).toHaveCount(0);
    expect(await page.evaluate(() => Object.keys(sessionStorage).filter(k => k.startsWith('br-stage1-operation:') && k.endsWith(':lookup')))).toEqual([]);
  }
  expect(await page.evaluate(()=>(window as any).__stage1SignCalls)).toBe(4);
});

for(const mode of ['transport-recovered','finality-lag'])test(`lookup inventory survives ${mode}`,async({page})=>{
  await setup(page,'cash_transport',mode);await page.locator('[data-stage1-action="self-claim"]').click();await page.getByRole('button',{name:'Continue',exact:true}).click();await expect(page.locator('[data-stage1-hold="claim-transport"]')).toBeVisible();await hold(page);await expect(page.getByRole('status').filter({hasText:'Confirmed'})).toBeVisible();
  await expect.poll(() => page.evaluate(() => JSON.parse(sessionStorage.getItem(Object.keys(sessionStorage).find(k=>k.startsWith('br-stage1-lookups:')) ?? '') ?? '[]').length)).toBe(1);
  await page.getByRole('button',{name:'Close',exact:true}).click();
  if(mode==='finality-lag')await page.getByRole('button',{name:'Try again',exact:true}).click();
  await expect(page.getByRole('button',{name:stage1Copy.deactivateTransport,exact:true})).toBeVisible();
});

for(const mode of ['submit-rejected','lost-response','unknown-response'])test(`submission recovery ${mode} never resubmits automatically`,async({page})=>{
  const calls=await setup(page,'registration',mode);await page.locator('[data-stage1-action="registration"]').click();await page.getByRole('button',{name:'Continue',exact:true}).click();await expect(page.locator('[data-stage1-hold]')).toBeVisible();await hold(page);
  await expect(page.getByRole('status').filter({hasText:'Needs review'})).toBeVisible();
  if(mode==='unknown-response')await expect(page.getByRole('button',{name:'Try again',exact:true})).toHaveCount(0);
  else await expect(page.getByRole('button',{name:'Try again',exact:true})).toBeVisible();
  expect(calls.filter(c=>!c.path.endsWith('/prepare'))).toHaveLength(1);expect(await page.evaluate(()=>(window as any).__stage1SignCalls)).toBe(1);
});

for (const name of ['registration','pledge_bonded','notice','cash_transport']) test(`actions gate off hides ${name}`,async({page})=>{
  let eligibility=0; page.on('request', r=>{if(r.url().includes('/me/eligibility'))eligibility++;});
  await setup(page,name,'actions-off');await expect(page.locator('[data-stage1]')).toBeVisible();
  await expect(page.locator('[data-stage1-action]')).toHaveCount(0);
  await expect(page.getByRole('button',{name:stage1Copy.pledgeActions,exact:true})).toHaveCount(0);
  expect(eligibility).toBe(0);
});
test('pledge simulation starts only when its actions open and reuses the brief cache',async({page})=>{
  let eligibility=0;page.on('request',r=>{if(r.url().includes('/me/eligibility'))eligibility++;});
  await setup(page,'notice');await expect(page.locator('[data-stage1-pledge]')).toBeVisible();
  expect(eligibility).toBe(0);
  const control=page.getByRole('button',{name:stage1Copy.pledgeActions,exact:true});await control.click();
  await expect(page.locator('[data-stage1-action="withdrawal-notice"]')).toBeVisible();expect(eligibility).toBe(1);
  await control.click();await control.click();expect(eligibility).toBe(1);
});
for(const name of ['notice','begin-withdrawal'])test(`hours-stale index time uses post-pause Monday clock for ${name}`,async({page})=>{
  const calls=await setup(page,name,'stale-clock');
  await page.getByRole('button',{name:stage1Copy.pledgeActions,exact:true}).click();
  await page.locator(`[data-stage1-action="${vector(name).action}"]`).click();
  await page.getByRole('button',{name:'Continue',exact:true}).click();
  await expect(page.locator('[data-stage1-hold]')).toBeVisible();
  await hold(page);await expect(page.getByRole('status').filter({hasText:'Confirmed'})).toBeVisible();
  expect(calls.filter(c=>!c.path.endsWith('/prepare'))).toHaveLength(1);
});
test('owner transport cleanup returns after storage is cleared and the page reloads',async({page})=>{
  await setup(page,'cash_transport','durable');
  await page.evaluate(()=>sessionStorage.clear());await page.reload();
  await page.getByRole('button',{name:stage1Copy.deactivateTransport,exact:true}).click();
  await page.getByRole('button',{name:'Continue',exact:true}).click();await hold(page);
  await expect(page.getByRole('button',{name:stage1Copy.closeTransport,exact:true})).toBeVisible();
  expect(await page.evaluate(()=>(window as any).__stage1SignCalls)).toBe(1);
  await page.evaluate(()=>sessionStorage.clear());await page.reload();
  await expect(page.getByRole('button',{name:stage1Copy.closeTransport,exact:true})).toBeVisible();
});

for(const mode of ['duplicate-pending','duplicate-failed'])test(`other tab operation ${mode} permits retry only after terminal failure`,async({page})=>{
  const calls=await setup(page,'registration',mode);
  await page.locator('[data-stage1-action="registration"]').click();
  await page.getByRole('button',{name:'Continue',exact:true}).click();await hold(page);
  await expect(page.getByRole('status').filter({hasText:'Needs review'})).toBeVisible();
  if(mode==='duplicate-failed')await expect(page.getByRole('button',{name:'Try again',exact:true})).toBeVisible();
  else await expect(page.getByRole('button',{name:'Try again',exact:true})).toHaveCount(0);
  expect(calls.filter(c=>!c.path.endsWith('/prepare'))).toHaveLength(1);
});

for (const action of ['begin-withdrawal', 'complete-withdrawal']) for (const width of [1440, 390]) test(`Monday pause explains unavailable ${action} ${width}`, async ({ page }) => {
  await page.setViewportSize({ width, height: 900 });
  const calls = await setup(page, action);
  let paused = true;
  await page.route('**/stage1/me/eligibility', route => route.fulfill({ json: {
    chainTime: '24192010', week: '40', actions: paused ? {} : { [action]: { refreshRate: true } },
    ...(paused ? { withdrawalsPausedUntil: String(Math.floor(Date.now() / 1000) + 2) } : {}),
  } }));
  await page.getByRole('button', { name: stage1Copy.pledgeActions, exact: true }).click();
  await expect(page.getByRole('status').filter({ hasText: stage1Copy.withdrawalsPaused })).toBeVisible();
  await expect(page.locator(`[data-stage1-action="${action}"]`)).toHaveCount(0);
  if (action === 'begin-withdrawal') await expect(page.locator('[data-stage1-action="cancel-notice"]')).toBeVisible();
  expect(calls).toHaveLength(0);
  expect(await page.evaluate(() => (window as any).__stage1SignCalls)).toBe(0);
  if (process.env.STAGE1_PHASE31_EVIDENCE) await page.screenshot({ path: path.join(process.env.STAGE1_PHASE31_EVIDENCE, `phase3.1-pause-${action}-${width}.png`), fullPage: true });
  paused = false;
  await expect(page.locator(`[data-stage1-action="${action}"]`)).toBeVisible();
  await expect(page.getByRole('status').filter({ hasText: stage1Copy.withdrawalsPaused })).toHaveCount(0);
});

for (const action of ['begin-withdrawal', 'complete-withdrawal']) test(`Monday rollover during hold refuses ${action} before signing`, async ({ page }) => {
  const calls = await setup(page, action);
  await page.getByRole('button', { name: stage1Copy.pledgeActions, exact: true }).click();
  await page.locator(`[data-stage1-action="${action}"]`).click();
  await page.getByRole('button', { name: 'Continue', exact: true }).click();
  await expect(page.locator('[data-stage1-hold]')).toBeVisible();
  await page.route('**/stage1/me/eligibility', route => route.fulfill({ json: {
    chainTime: '24192010', week: '40', actions: {}, withdrawalsPausedUntil: String(Math.floor(Date.now() / 1000) + 60),
  } }));
  await hold(page);
  await expect(page.getByRole('status').filter({ hasText: stage1Copy.withdrawalsPaused })).toBeVisible();
  await expect(page.locator('[data-stage1-hold]')).toHaveCount(0);
  expect(await page.evaluate(() => (window as any).__stage1SignCalls)).toBe(0);
  expect(calls.filter(c => !c.path.endsWith('/prepare'))).toHaveLength(0);
});

test('Monday rollover during submission retains its pending operation and pause explanation', async ({ page }) => {
  const calls = await setup(page, 'begin-withdrawal', 'pause-during-submit');
  await page.getByRole('button', { name: stage1Copy.pledgeActions, exact: true }).click();
  await page.locator('[data-stage1-action="begin-withdrawal"]').click();
  await page.getByRole('button', { name: 'Continue', exact: true }).click();
  await expect(page.locator('[data-stage1-hold]')).toBeVisible();
  await hold(page);
  await expect(page.getByRole('status').filter({ hasText: stage1Copy.withdrawalsPaused })).toBeVisible();
  await expect(page.getByRole('button', { name: 'Try again', exact: true })).toHaveCount(0);
  await expect.poll(() => page.evaluate(() => Object.values(sessionStorage).some(value => value.includes('fixture-operation')))).toBe(true);
  expect(calls.filter(c => !c.path.endsWith('/prepare'))).toHaveLength(1);
});
