import { AddressLookupTableProgram, PublicKey } from '@solana/web3.js';
import { Buffer } from 'buffer';
import type { Stage1TransactionIntent, Stage1LockWeeks } from './portalTransactionIntent';
import { exactUnits, stage1StakingAssets, type Stage1Pledge, type Stage1Bonding, type Stage1Withdrawal } from './stage1';
export type Stage1Action = 'registration' | 'pledge' | 'cancel-pledge' | 'withdrawal-notice' | 'cancel-notice' | 'begin-withdrawal' | 'complete-withdrawal' | 'convert-pledge' | 'self-claim' | 'claim-transport';
export type Stage1Claim = { reference: { jobId: string; role: number; index: number }; intent: Extract<Stage1TransactionIntent, { kind: 'stage1_self_claim' }>; requiresLookup: boolean };
export type Stage1Plan = { action: Stage1Action; request: Record<string, unknown>; intent: Stage1TransactionIntent };
const ZERO = '11111111111111111111111111111111';
// Sponsor cash has no staking slot; its zero `slot` is not a provider (as in the backend's pledge_providers).
const SPONSOR_CASH_ADAPTER = 254;
const positive = (v: unknown): v is string => exactUnits(v) && BigInt(v) > 0n;
export function pledgeActions(p: Stage1Pledge): Array<{ action: Stage1Action; withdrawal?: Stage1Withdrawal }> {
  if (p.cancelled !== false || !positive(p.basisLamports) || !p.hillState || !exactUnits(p.chainTime)) return [];
  const h = p.hillState, now = BigInt(p.chainTime);
  const active = h.bonded && (p.exiting === true || p.converted === true || (exactUnits(p.sequence) && BigInt(p.sequence) > BigInt(h.foundingCutoff)) || p.founding === true);
  const none = p.pendingRequest === ZERO;
  const result: Array<{ action: Stage1Action; withdrawal?: Stage1Withdrawal }> = [];
  if (!active && p.exiting === false) {
    result.push({ action: 'cancel-pledge' });
    if (h.bonded && none && p.eligibility?.['convert-pledge'] && p.cityState?.intakePaused === false) result.push({ action: 'convert-pledge' });
  }
  if (active && p.exiting === false && none && exactUnits(p.lockEnd) && now >= BigInt(p.lockEnd)) result.push({ action: 'withdrawal-notice' });
  for (const withdrawal of p.withdrawals) {
    const r = withdrawal.data;
    if (r.status === 0 && p.pendingRequest === withdrawal.address && p.exiting === false) {
      result.push({ action: 'cancel-notice', withdrawal });
      if (active && p.eligibility?.['begin-withdrawal'] && exactUnits(r.eligibleAt) && now >= BigInt(r.eligibleAt)) result.push({ action: 'begin-withdrawal', withdrawal });
    }
    if (r.status === 1 && p.exiting === true && p.exitRequest === withdrawal.address && r.exitLot === p.address && p.eligibility?.['complete-withdrawal']) result.push({ action: 'complete-withdrawal', withdrawal });
  }
  return result;
}
export function pledgePlan(data: Stage1Bonding, mint: string, amountBaseUnits: string, lockWeeks: Stage1LockWeeks, depositId: string): Stage1Plan {
  if (!data.climb || !data.hillState || !data.cityState || data.cityState.intakePaused !== false || !positive(amountBaseUnits)) throw new Error('Unavailable');
  const config = stage1StakingAssets(data).find(a => a.mint === mint)?.config;
  if (!config?.enabled) throw new Error('Unavailable');
  const backingMints = data.bonded ? [] : data.assets.filter(a => a.config && a.config.adapter !== SPONSOR_CASH_ADAPTER && (data.cityState!.providerSlots & (1 << a.config.slot)) && (BigInt(data.hillState!.assetLots[a.config.slot]) > 0n || a.mint === mint)).sort((a,b) => a.config!.slot-b.config!.slot).map(a => a.mint);
  return { action: 'pledge', request: { hill: data.hill, mint, depositId, amountBaseUnits, lockWeeks }, intent: { kind: 'stage1_pledge', hill: data.hill, climb: data.climb, mint, depositId, amountBaseUnits, lockWeeks, providerMode: data.bonded ? 'bonded' : 'prebond', backingMints } };
}
export function lotPlan(p: Stage1Pledge, action: Stage1Action, lockWeeks: Stage1LockWeeks, requestId: string, withdrawal?: Stage1Withdrawal): Stage1Plan {
  if (!pledgeActions(p).some(a => a.action === action && a.withdrawal?.address === withdrawal?.address) || !exactUnits(p.depositId)) throw new Error('Unavailable');
  const base = { hill: p.hill, mint: p.mint, depositId: p.depositId };
  if (action === 'cancel-pledge') return { action, request: { lot: p.address }, intent: { kind: 'stage1_cancel_pledge', ...base } };
  if (action === 'convert-pledge') return { action, request: { lot: p.address, lockWeeks, refreshRate: p.eligibility?.[action]?.refreshRate ?? false }, intent: { kind: 'stage1_convert_pledge', ...base, lockWeeks, refreshRate: p.eligibility?.[action]?.refreshRate ?? false } };
  if (action === 'withdrawal-notice') return { action, request: { lot: p.address, requestId, basisLamports: p.basisLamports }, intent: { kind: 'stage1_withdrawal_notice', hill: p.hill, depositId: p.depositId, requestId, basisLamports: p.basisLamports! } };
  if (!withdrawal || !exactUnits(withdrawal.data.requestId)) throw new Error('Unavailable');
  const request = { lot: p.address, request: withdrawal.address, refreshRate: p.eligibility?.[action]?.refreshRate ?? false };
  const depositId = action === 'complete-withdrawal' ? withdrawal.parentDepositId : p.depositId;
  if (!exactUnits(depositId)) throw new Error('Unavailable');
  if (action === 'cancel-notice') return { action, request, intent: { kind: 'stage1_cancel_notice', depositId, requestId: withdrawal.data.requestId } };
  if (!exactUnits(p.eligibilityWeek)) throw new Error('Unavailable');
  const week = p.eligibilityWeek;
  if (action !== 'begin-withdrawal' && action !== 'complete-withdrawal') throw new Error('Unavailable');
  return { action, request, intent: { kind: action === 'begin-withdrawal' ? 'stage1_begin_withdrawal' : 'stage1_complete_withdrawal', ...base, depositId, requestId: withdrawal.data.requestId, week, refreshRate: request.refreshRate } };
}
export function claimPlan(claim: Stage1Claim, lookupTable?: string): Stage1Plan {
  // This descriptor came from the owner read the rider selected, before prepare.
  return { action: 'self-claim', request: { claims: [claim.reference], ...(lookupTable ? { lookupTable } : {}) }, intent: { ...structuredClone(claim.intent), ...(lookupTable ? { single: true } : {}) } };
}
export function claimTransportPlan(claim: Stage1Claim, wallet: string, recentSlot: number): Stage1Plan {
  const program = new PublicKey('EVjP2Vdz9buHNphywPhoybf213poa8EiSW6FGbXWFqYH');
  const owner = new PublicKey(wallet), mint = new PublicKey(claim.intent.mint);
  const pda = (seed: string, ...parts: Uint8Array[]) => PublicKey.findProgramAddressSync([Buffer.from(seed), ...parts], program)[0];
  const leaf = claim.intent.claims[0];
  if (claim.intent.claims.length !== 1 || !Number.isSafeInteger(recentSlot)) throw new Error('Unavailable');
  const week = Buffer.alloc(8); week.writeBigUInt64LE(BigInt(leaf.week));
  const token = new PublicKey('TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA');
  const ata = PublicKey.findProgramAddressSync([owner.toBuffer(), token.toBuffer(), mint.toBuffer()], new PublicKey('ATokenGPvbdGVxr1b2hvZbsiqW5xWH25efTNsLJA8knL'))[0];
  const keys = [pda('s1v1_city'), pda('s1v1_recipient', owner.toBytes()), mint, ata, token, new PublicKey(ZERO)];
  const hill = new PublicKey(leaf.hill);
  if (claim.intent.claimType === 'cash') keys.push(pda('s1v1_asset', mint.toBytes()), pda('s1v1_earnings', mint.toBytes()), pda('s1v1_claims', hill.toBytes(), mint.toBytes(), week));
  else {
    const dung = pda('s1v1_dung', hill.toBytes(), week);
    keys.push(dung, pda('s1v1_dung_claims', dung.toBytes(), Buffer.from([(leaf as { role: number }).role])), pda('s1v1_dung_state'), pda('program_config'), pda('dung_mint_auth'));
  }
  const addresses = [...new Map(keys.map(k => [k.toBase58(), k])).values()].sort((a,b) => Buffer.compare(a.toBuffer(), b.toBuffer())).map(k => k.toBase58());
  const [, table] = AddressLookupTableProgram.createLookupTable({ authority: owner, payer: owner, recentSlot });
  return { action: 'claim-transport', request: { mode: 'create', claims: [claim.reference], recentSlot: String(recentSlot) }, intent: { kind: 'stage1_claim_transport', mode: 'create', lookupTable: table.toBase58(), recentSlot: String(recentSlot), addresses } };
}
