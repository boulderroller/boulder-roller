// Dedicated operator wallets and explicitly synthetic one-person allocation.
// Funding and rates remain real; no balance injection or rate setter exists.
import { SystemProgram, SYSVAR_RENT_PUBKEY, SYSVAR_CLOCK_PUBKEY, TransactionInstruction } from '@solana/web3.js';
import { TOKEN_PROGRAM_ID, unpackAccount, createAssociatedTokenAccountIdempotentInstruction, getAssociatedTokenAddressSync } from '@solana/spl-token';
import { fileURLToPath } from 'url';
import { resolve } from 'path';
import {cashClaimTerms,cashTermsCommitment} from './stage1_claim_metadata.js';
import { Operator, Operation, bn, u64, pk, hash, requireThat, runOperator } from './stage1_operator.js';

export async function smoke(r: Operator, input: any): Promise<Operation> {
  r.validateRoles(input);
  requireThat(r.interface === 'devnet', 'Smoke requires devnet program interface');
  requireThat(r.options.cluster !== 'mainnet-beta' && input.allocationKind === 'synthetic operator rehearsal', 'Smoke requires an explicit test allocation on devnet/localnet');
  const m: any = r.program.methods, city = r.pda('s1v1_city'), mint = pk(input.mint), hill = pk(input.hill), operator = pk(input.operator);
  requireThat(!operator.equals(r.admin) && !operator.equals(r.feePayer), 'Use a distinct operator wallet');
  const asset = r.pda('s1v1_asset', mint.toBuffer()), earnings = r.pda('s1v1_earnings', mint.toBuffer());
  const [c, a, h, registration] = await Promise.all([
    r.fetch('Stage1CityConfig', city), r.fetch('Stage1AssetConfig', asset), r.fetch('Stage1HillBond', hill),
    r.fetch('Stage1TestPool', r.pda('s1v1_test_pool')),
  ]);
  requireThat(c && a?.adapter === 5 && a.enabled && h?.city.equals(city) && registration?.mint.equals(mint) &&
    registration.provider.equals(a.providerAccount), 'Registered, enabled SPL test asset and admitted hill required');
  requireThat(c.publisher.equals(pk(input.publisher)), 'Publisher mismatch');
  const provider = a.providerAccount;
  await r.read(provider); await r.read(mint);
  const pair = [provider, mint].map(pubkey => ({ pubkey, isWritable: false, isSigner: false }));
  const id = bn(input.depositId), lot = r.pda('s1v1_lot', operator.toBuffer(), u64(input.depositId));
  const custody = r.pda('s1v1_custody', lot.toBuffer()), ownerReserve = r.pda('s1v1_owner', lot.toBuffer());
  const clock = await r.read(SYSVAR_CLOCK_PUBKEY, false);
  const now = clock!.data.readBigInt64LE(32), week = BigInt(input.week);
  const funding = r.pda('s1v1_funding', hill.toBuffer(), mint.toBuffer(), u64(week));
  const cursor = r.pda('s1v1_cursor', hill.toBuffer(), mint.toBuffer());
  const claimSet = r.pda('s1v1_claims', hill.toBuffer(), mint.toBuffer(), u64(week));
  const source = pk(input.source), destination = pk(input.destination);
  const action = r.options.action;
  const instructions: TransactionInstruction[] = [];
  let check: () => Promise<void>;
  if (action === 'pledge' || action === 'bond') {
    const units = bn(input.units);
    u64(input.units);
    requireThat(units.gt(bn(0)) && [0, 13, 26, 52].includes(input.lockWeeks), 'Positive units and explicit valid lockWeeks required');
    const existing = await r.fetch('Stage1PledgeLot', lot);
    const token = await r.read(source);
    requireThat(token, 'Missing operator token source');
    const decoded = unpackAccount(source, token, TOKEN_PROGRAM_ID);
    requireThat(decoded.owner.equals(operator) && decoded.mint.equals(mint), 'Operator token source mismatch');
    if (!existing) {
      requireThat(!h.bonded || action === 'pledge', 'Bond smoke requires an unbonded test hill');
      let remaining = pair;
      if (!h.bonded) {
        // Fetch the complete bounded registry, never a caller-selected subset.
        const configs: any[] = await (r.program.account as any).stage1AssetConfig.all();
        // Sponsor cash (adapter 254) keeps slot 0 without a staking slot; the program refuses it here.
        const backed = configs.filter(x => x.account.city.equals(city) && x.account.adapter !== 254 && (h.assetLots[x.account.slot].gt(bn(0)) || x.publicKey.equals(asset)))
          .sort((x, y) => x.account.slot - y.account.slot);
        remaining = [];
        for (const entry of backed) {
          requireThat(entry.account.adapter !== 1, 'Synthetic adapter is forbidden');
          await r.fetch('Stage1AssetConfig', entry.publicKey); await r.read(entry.account.providerAccount); await r.read(entry.account.mint);
          remaining.push({ pubkey: entry.publicKey, isWritable: true, isSigner: false },
            ...[entry.account.providerAccount, entry.account.mint].map(pubkey => ({ pubkey, isWritable: false, isSigner: false })));
        }
      }
      instructions.push(await m[action](id, units, input.lockWeeks).accounts({ city, hillAccount: { hill }, climb: h.climb,
        asset, mint, lot, custody, ownerReserve, source, owner: operator, tokenProgram: TOKEN_PROGRAM_ID,
        systemProgram: SystemProgram.programId, rent: SYSVAR_RENT_PUBKEY }).remainingAccounts(remaining).instruction());
    }
    check = async () => {
      const l = await r.fetch('Stage1PledgeLot', lot);
      requireThat(l?.owner.equals(operator) && l.hill.equals(hill) && l.mint.equals(mint) && l.units.eq(units) && !l.cancelled && l.depositId.eq(id) && l.city.equals(city) && l.lockWeeks === (l.founding ? 26 : input.lockWeeks), 'Finalized lot differs from requested deposit');
      if (action === 'bond') { const finalHill = await r.fetch('Stage1HillBond', hill); requireThat(finalHill.bonded && finalHill.founder.equals(operator) && l.sequence.eq(finalHill.foundingCutoff), 'Operator did not bond the hill'); }
    };
  } else if (action === 'harvest') {
    requireThat((now - BigInt(c.seasonAnchor.toString())) / 604800n === week, 'Harvest week must be the current chain week');
    const l = await r.fetch('Stage1PledgeLot', lot), units = bn(input.harvestUnits), target = bn(input.harvestedUnitsAfter);
    requireThat(input.fundingNetAfter !== undefined, 'Explicit fundingNetAfter checkpoint required');
    const netTarget = bn(input.fundingNetAfter), book = await r.fetch('Stage1WeekFunding', funding);
    if (l?.harvestedUnits.eq(target)) requireThat(book?.harvestedNet.eq(netTarget), 'Harvest is not credited to this week');
    requireThat(l?.hill.equals(hill) && l.mint.equals(mint) && l.owner.equals(operator), 'Harvest lot mismatch');
    requireThat(units.gt(bn(0)) && units.lte(bn(1_000_000)), 'Smoke harvest must be 1..1000000 base units');
    requireThat(l.harvestedUnits.eq(target) || l.harvestedUnits.add(units).eq(target), 'Harvest checkpoint mismatch');
    if (!l.harvestedUnits.eq(target)) {
      const fee = a.harvestedUnits.add(units).div(bn(10)).sub(a.feesAssessed);
      requireThat(netTarget.eq((book?.harvestedNet ?? bn(0)).add(units).sub(fee)), 'Funding checkpoint differs from exact harvest credit');
      await r.fetch('Stage1SettlementCursor', cursor);
      instructions.push(await m.initStage1Settlement().accounts({city, hillAccount: {hill}, asset, cursor,
        payer: r.feePayer, systemProgram: SystemProgram.programId}).instruction());
      instructions.push(await m.openStage1Week(bn(week)).accounts({ city, hillAccount: { hill }, asset, funding, payer: r.feePayer, systemProgram: SystemProgram.programId, cursor }).instruction());
      instructions.push(await m.harvestStage1(units).accounts({ city, hill, lot, asset, custody, ownerReserve,
        earnings, tokenProgram: TOKEN_PROGRAM_ID }).remainingAccounts([...pair, { pubkey: funding, isWritable: true, isSigner: false }]).instruction());
    }
    check = async () => { requireThat((await r.fetch('Stage1PledgeLot', lot)).harvestedUnits.eq(target) &&
      (await r.fetch('Stage1WeekFunding', funding))?.harvestedNet.eq(netTarget), 'Harvest and week funding checkpoints not finalized'); };
  } else if (action === 'skip') {
    const state = await r.fetch('Stage1SettlementCursor', cursor);
    const start = BigInt((state?.nextWeek ?? h.admittedWeek).toString());
    if (state && start === week + 1n) return {instructions: [], description: 'Requested weeks already processed',
      assert: async () => { requireThat((await r.fetch('Stage1SettlementCursor', cursor))?.nextWeek.eq(bn(week + 1n)), 'Processed cursor changed'); }};
    requireThat(week >= start && week - start < 16n, 'Skip 1..16 consecutive weeks from the cursor');
    requireThat(!state || state.holds.every((v: any) => v.isZero()), 'Outstanding holds require weekly settlement');
    requireThat(now >= BigInt(c.seasonAnchor.toString()) + (week + 1n) * 604800n + 86400n, 'Skipped weeks must be closed plus grace');
    if (!state) instructions.push(await m.initStage1Settlement().accounts({city, hillAccount: {hill}, asset, cursor,
      payer: r.feePayer, systemProgram: SystemProgram.programId}).instruction());
    const witnesses = [];
    for (let w = start; w <= week; w++) {
      const pubkey = r.pda('s1v1_funding', hill.toBuffer(), mint.toBuffer(), u64(w));
      await r.read(pubkey);
      witnesses.push({pubkey, isSigner: false, isWritable: false});
    }
    await r.read(earnings);
    instructions.push(await m.skipStage1EmptyWeeks(bn(week)).accounts({city, hill, asset, cursor, earnings,
      publisher: pk(input.publisher)}).remainingAccounts(witnesses).instruction());
    check = async () => { requireThat((await r.fetch('Stage1SettlementCursor', cursor))?.nextWeek.eq(bn(week + 1n)), 'Skip cursor not finalized'); };
  } else if (action === 'recipient') {
    const key = r.pda('s1v1_recipient', operator.toBuffer()), existing = await r.fetch('Stage1Recipient', key);
    if (!existing) instructions.push(await m.registerStage1Recipient(operator).accounts({ registration: key, person: operator, payer:r.feePayer, systemProgram: SystemProgram.programId }).instruction());
    check = async () => { requireThat((await r.fetch('Stage1Recipient', key))?.recipient.equals(operator), 'Fixed recipient mismatch'); };
  } else if (action === 'publish' || action === 'claim') {
    const amount = bn(input.allocationUnits);
    const recipient = await r.fetch('Stage1Recipient', r.pda('s1v1_recipient', operator.toBuffer()));
    requireThat(recipient?.person.equals(operator) && recipient.recipient.equals(operator), 'Register the fixed operator recipient before publication');
    requireThat(amount.gt(bn(0)) && amount.lte(bn(1_000_000)), 'Tiny rehearsal allocation required');
    const context = JSON.stringify([r.programId.toBase58(), city.toBase58(), hill.toBase58(), Number(week), mint.toBase58()]);
    const root = Buffer.from(hash(`BR-stage1-v1:leaf\0[${context},0,"${operator}","${operator}",${amount}]`), 'hex');
    const book = await r.fetch('Stage1WeekFunding', funding), set = await r.fetch('Stage1ClaimSet', claimSet);
    requireThat(book, 'No realized earnings funding this week');
    if (!Buffer.from(book.snapshot).every(x => x === 0)) requireThat(recipient.registeredAt.lte(book.frozenAt), 'Recipient registered after the immutable snapshot');
    if (set?.sealed) requireThat(Buffer.from(set.root).equals(root) && set.total.eq(amount) && set.leafCount === 1, 'Immutable claim set differs');
    if (action === 'publish') {
      requireThat(now >= BigInt(c.seasonAnchor.toString()) + (week + 1n) * 604800n + 86400n, 'Wait until this week closes plus 24h grace');
      const snapshot = Buffer.from(hash(`synthetic operator rehearsal:${context}:${operator}:${amount}`), 'hex');
      if (!set?.sealed) {
        requireThat(book.available.gte(amount), 'Allocation is not fully funded');
        const progress = await r.fetch('Stage1SettlementCursor', cursor);
        requireThat(progress?.nextWeek.eq(bn(week)), 'Settle or prove empty prior weeks using the cursor first');
        if (Buffer.from(book.snapshot).every(x => x === 0)) instructions.push(await m.freezeStage1Snapshot([...snapshot], amount).accounts({ city, hill, asset, funding, previous: null, publisher: pk(input.publisher), cursor }).instruction());
        else requireThat(Buffer.from(book.snapshot).equals(snapshot) && book.cap.eq(amount), 'Frozen snapshot differs');
        instructions.push(await m.prepareStage1ClaimSet(1).accounts({city,asset,funding,claimSet,publisher:pk(input.publisher),systemProgram:SystemProgram.programId}).instruction());
        instructions.push(await m.publishStage1ClaimSet([...root], amount, 1, [book.available.sub(amount), bn(0), bn(0), bn(0), bn(0)])
          .accounts({ city, hillAccount: { hill }, asset, funding, claimSet, earnings, publisher: pk(input.publisher), systemProgram: SystemProgram.programId, cursor }).instruction());
      }
      check = async () => { const s = await r.fetch('Stage1ClaimSet', claimSet); requireThat(s?.sealed && s.total.eq(amount) && Buffer.from(s.root).equals(root), 'Publication not finalized'); };
    } else {
      requireThat(set?.sealed && set.storageVersion===2, 'Publish the allocation first');
      requireThat(destination.equals(getAssociatedTokenAddressSync(mint,operator)), 'Use the registered recipient associated token account');
      const dest = await r.read(destination);
      const token = dest?unpackAccount(destination,dest,TOKEN_PROGRAM_ID):null;
      requireThat(!token || token.owner.equals(operator) && token.mint.equals(mint), 'Fixed destination mismatch');
      const terms=cashClaimTerms(book,book.holds,Buffer.alloc(32));
      requireThat(cashTermsCommitment(claimSet,terms).equals(Buffer.from(set.metadataHash)), 'Exact retained publication witness required');
      const header = r.program.account.stage1ClaimSet.size;
      const previous = ((await r.read(claimSet))!.data[header]&1)!==0;
      requireThat(set.claimedCount===(previous?1:0) && set.paid.eq(previous?amount:bn(0)), 'Claim progress differs');
      if (!previous) {
        instructions.push(createAssociatedTokenAccountIdempotentInstruction(r.feePayer,destination,operator,mint));
        instructions.push(await m.claimStage1(0, operator, amount, [],terms).accounts({ city, asset, claimSet,
          registration: r.pda('s1v1_recipient', operator.toBuffer()), earnings, destination,
          tokenProgram: TOKEN_PROGRAM_ID }).instruction());
      }
      const balance = token?.amount??0n;
      check = async () => {
        const paid = await r.fetch('Stage1ClaimSet', claimSet);
        requireThat(paid?.paid.eq(amount) && paid.claimedCount===1 && (((await r.read(claimSet))!.data[header]&1)!==0), 'Claim bitmap/progress mismatch');
        if (!previous) { const after = unpackAccount(destination, (await r.read(destination))!, TOKEN_PROGRAM_ID); requireThat(after.amount === balance + BigInt(amount.toString()), 'Exact claim transfer not observed'); }
      };
    }
  } else throw new Error('Unknown smoke action');
  if (!instructions.length) await check!();
  return { instructions, assert: check!, description: `${action}: synthetic operator rehearsal using real SPL pool units` };
}

if (process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  runOperator('stage1-smoke', smoke).catch(e => { console.error(e.message); process.exitCode = 1; });
}
