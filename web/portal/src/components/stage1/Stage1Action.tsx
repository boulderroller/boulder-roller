import { PublicKey, VersionedTransaction } from '@solana/web3.js';
import { Buffer } from 'buffer';
import bs58 from 'bs58';
import { useEffect, useRef, useState } from 'react';
import * as Dialog from '@radix-ui/react-dialog';
import { useQueryClient } from '@tanstack/react-query';
import { useAuth } from '../../contexts/AuthContext';
import { api, ApiError, type PreparedVaultTransaction } from '../../lib/api';
import { claimPlan, claimTransportPlan, lotPlan, pledgePlan, type Stage1Action as Action, type Stage1Claim, type Stage1Plan } from '../../lib/stage1Actions';
import { formatInteger } from '../../lib/formatters';
import { stage1Copy as copy } from '../../lib/stage1Copy';
import { STAGE1_MINTS, stage1Amount, stage1StakingAssets, type Stage1Bonding, type Stage1Pledge, type Stage1Withdrawal } from '../../lib/stage1';
import { decimalToBaseUnits, formatBaseUnits } from '../../lib/tokenAmounts';
import { validatePreparedTransactionIntent, validateStage1VersionedTransaction, type Stage1LockWeeks } from '../../lib/portalTransactionIntent';
import { resolveStage1Lookup, stage1Rpc, stage1Settlement, stage1TestPoolFor } from '../../lib/stage1Rpc';
import { createClientRequestId } from '../../lib/clientRequestId';
import { clearClaimLookup, saveLookup, lookupStorageKey } from '../../lib/stage1Lookups';
import { StateRow } from '../portal/FailureSpecies';
import HoldCapsule from '../portfolio/HoldCapsule';
import { WalletTransactionSignerBridge } from '../auth/WalletTransactionSignerBridge';
import { useDeferredWalletTransactionSigner } from '../auth/useDeferredWalletTransactionSigner';

const labels: Record<Action, string> = { registration: copy.registerAction, pledge: copy.depositAction, 'cancel-pledge': copy.cancelPledgeAction, 'withdrawal-notice': copy.noticeAction, 'cancel-notice': copy.cancelNoticeAction, 'begin-withdrawal': copy.beginAction, 'complete-withdrawal': copy.completeAction, 'convert-pledge': copy.convertAction, 'self-claim': copy.collectAction, 'claim-transport': copy.transport };
type Pending = { plan: Stage1Plan; clientRequestId: string; reference: string; operationId?: string; signature?: string; blockhash?: string; conflict?: boolean };
function randomId() { const bytes = crypto.getRandomValues(new Uint32Array(2)); return ((BigInt(bytes[0]) << 32n) | BigInt(bytes[1])).toString(); }
export default function Stage1Action({ action, surface, bonding, lot, withdrawal, claim, transport }: { action: Action; surface: 'climb' | 'portfolio'; bonding?: Stage1Bonding; lot?: Stage1Pledge; withdrawal?: Stage1Withdrawal; claim?: Stage1Claim; transport?: Stage1Plan }) {
  const { user } = useAuth();
  const queryClient = useQueryClient();
  const signer = useDeferredWalletTransactionSigner();
  const [open, setOpen] = useState(false), [busy, setBusy] = useState(false), [state, setState] = useState('');
  const [pausedUntil, setPausedUntil] = useState<string | null>(null);
  const [amount, setAmount] = useState(''), [mint, setMint] = useState(''), [lock, setLock] = useState<Stage1LockWeeks>(0);
  const [checked, setChecked] = useState<{ plan: Stage1Plan; prepared: PreparedVaultTransaction } | null>(null);
  const isWithdrawal = action === 'begin-withdrawal' || action === 'complete-withdrawal';
  const failureState = (error: unknown) => error instanceof ApiError && error.detail?.code === 'stage1_withdrawal_paused' ? copy.withdrawalsPaused : 'Needs review';
  const storage = ['br-stage1-operation', user?.id, user?.wallet, action,
    lot?.address ?? bonding?.hill ?? claim?.reference.jobId ?? (transport?.intent.kind === 'stage1_claim_transport' ? transport.intent.lookupTable + transport.intent.mode : ''),
    withdrawal?.address ?? (claim ? [claim.reference.role, claim.reference.index].join(':') : '')].join(':');
  const tableKey = `${storage}:lookup`;
  const label = transport?.intent.kind === 'stage1_claim_transport' ? transport.intent.mode === 'close' ? copy.closeTransport : copy.deactivateTransport : labels[action];
  const [pending, setPending] = useState<Pending | null>(() => { try { return JSON.parse(sessionStorage.getItem(storage) ?? 'null'); } catch { return null; } });
  const mounted = useRef(true), busyRef = useRef(false);
  useEffect(() => { mounted.current = true; return () => { mounted.current = false; }; }, []);
  const tokens = stage1StakingAssets(bonding);
  const selectedMint = mint || tokens[0]?.mint || '';
  const units = decimalToBaseUnits(amount, STAGE1_MINTS[selectedMint]?.decimals ?? 9);
  const invalidate = () => Promise.all([queryClient.invalidateQueries({ queryKey: ['stage1'] }), queryClient.invalidateQueries({ queryKey: ['stage1-bonding'] })]);
  useEffect(() => {
    if (!pausedUntil) return;
    const timer = setTimeout(() => setPausedUntil(null), Math.max(0, Number(pausedUntil) * 1000 - Date.now()));
    return () => clearTimeout(timer);
  }, [pausedUntil]);
  useEffect(() => {
    if (!pending) return;
    let cancelled = false, timer: ReturnType<typeof setTimeout>;
    const finish = async (confirmed: boolean) => {
      if (confirmed && !pending.conflict && pending.plan.intent.kind === 'stage1_claim_transport' && user) {
        const { mode, lookupTable: table } = pending.plan.intent;
        if (mode === 'create') {
          sessionStorage.setItem(tableKey, table);
          saveLookup(lookupStorageKey(user.id, user.wallet), table);
        } else {
          clearClaimLookup(user.id, user.wallet, table);
          if (mode === 'close') saveLookup(lookupStorageKey(user.id, user.wallet), table, true);
        }
        window.dispatchEvent(new Event('stage1-lookups'));
      }
      sessionStorage.removeItem(storage); setPending(null); setChecked(null);
      setPausedUntil(null);
      setState(confirmed ? 'Confirmed' : 'Needs review');
      await invalidate();
    };
    const checkReceipt = async () => {
      if (!pending.signature || !pending.blockhash) return false;
      const result = await stage1Settlement(pending.signature, pending.blockhash);
      if (cancelled || result === 'pending') return false;
      await finish(result === 'confirmed'); return true;
    };
    const reconcile = async () => {
      try {
        const result = await api.stage1Operation(pending.plan.action, pending.reference, pending.clientRequestId, pending.operationId);
        if (cancelled) return;
        if (result.recorded && !result.pending && !result.needsReview) {
          await finish(true); return;
        }
        if (result.stage1TerminalFailure === true) { await finish(false); return; }
        if (result.needsReview && await checkReceipt()) return;
        setState(result.needsReview ? 'Needs review' : result.delayed ? 'Delayed' : 'Pending');
      } catch {
        try { if (await checkReceipt()) return; } catch { /* Unknown remains blocked. */ }
        if (!cancelled) setState('Needs review');
      }
      if (!cancelled) timer = setTimeout(() => void reconcile(), 4000);
    };
    void reconcile();
    return () => { cancelled = true; clearTimeout(timer); };
  }, [pending, storage, tableKey]);
  const prepare = async () => {
    if (!user || busyRef.current || pending) return;
    busyRef.current = true; setBusy(true); setState('Pending'); setChecked(null);
    try {
      let plan: Stage1Plan;
      if (transport) plan = transport;
      else if (action === 'registration') plan = { action, request: {}, intent: { kind: 'stage1_registration' } };
      else if (action === 'pledge' && bonding && units && BigInt(units) > 0n) plan = pledgePlan(bonding, selectedMint, units, lock, randomId());
      else if (claim) {
        let lookup = sessionStorage.getItem(tableKey) ?? '';
        if (lookup) {
          const { value } = await stage1Rpc().getAddressLookupTable(new PublicKey(lookup), { commitment: 'finalized' });
          if (!value || value.state.authority?.toBase58() !== user.wallet) throw new Error('Unavailable');
          if (!value.isActive()) { clearClaimLookup(user.id, user.wallet, lookup); lookup = ''; }
        }
        plan = claim.requiresLookup && !lookup
          ? claimTransportPlan(claim, user.wallet, await stage1Rpc().getSlot('finalized')) : claimPlan(claim, lookup || undefined);
      }
      else if (lot) {
        const eligibility = await api.getStage1Eligibility(lot.address);
        if (isWithdrawal && eligibility.withdrawalsPausedUntil) { setState(copy.withdrawalsPaused); return; }
        plan = lotPlan({ ...lot, chainTime: eligibility.chainTime, eligibilityWeek: eligibility.week, eligibility: eligibility.actions }, action, lock, randomId(), withdrawal);
      }
      else throw new Error('Unavailable');
      // Freeze before contacting prepare; the response's echoed intent is never read.
      plan = structuredClone(plan);
      const response = await api.prepareStage1(plan);
      if (!response.preparedTransaction || !mounted.current) throw new Error('Unavailable');
      const prepared = response.preparedTransaction;
      const testPool = await stage1TestPoolFor(plan.intent);
      if (plan.intent.kind === 'stage1_self_claim' && plan.intent.single) await validateStage1VersionedTransaction(prepared, plan.intent, user.wallet, resolveStage1Lookup, testPool);
      else await validatePreparedTransactionIntent(prepared, plan.intent, user.wallet, testPool);
      if (!mounted.current) return;
      setChecked({ plan, prepared }); setState('');
    } catch (error) { if (mounted.current) setState(failureState(error)); }
    finally { busyRef.current = false; if (mounted.current) setBusy(false); }
  };
  const commit = async () => {
    if (!checked || !user || busyRef.current || pending) return;
    busyRef.current = true; setBusy(true); setState('Pending');
    let saved: Pending | null = null;
    try {
      // A hold opened before noon must not sign through the brief pause.
      if (isWithdrawal && lot) {
        const eligibility = await api.getStage1Eligibility(lot.address);
        if (!mounted.current) return;
        if (eligibility.withdrawalsPausedUntil) { setChecked(null); setState(copy.withdrawalsPaused); return; }
      }
      const signed = await signer.signPreparedTransaction(checked.prepared, checked.plan.intent);
      if (!mounted.current) return;
      if (!checked.prepared.pda) throw new Error('Unavailable');
      saved = { plan: checked.plan, clientRequestId: createClientRequestId('stage1'), reference: checked.prepared.pda, blockhash: checked.prepared.blockhash, signature: bs58.encode(VersionedTransaction.deserialize(Buffer.from(signed, 'base64')).signatures[0]) };
      sessionStorage.setItem(storage, JSON.stringify(saved)); // Save before send; lost replies reconcile, never re-sign.
      setPending(saved); setChecked(null);
      const result = await api.submitStage1(checked.plan, signed, checked.prepared.lastValidBlockHeight, saved.clientRequestId);
      if (!mounted.current) return;
      if (result.withdrawalsPausedUntil) setPausedUntil(result.withdrawalsPausedUntil);
      if (result.operation?.operationId) { saved.operationId = result.operation.operationId; sessionStorage.setItem(storage, JSON.stringify(saved)); setPending({ ...saved }); }
    } catch (error) {
      if (mounted.current) {
        if (error instanceof ApiError && error.statusCode === 409 && error.detail?.code === 'stage1_operation_pending' && typeof error.detail.operation_id === 'string' && saved) {
          // The other tab's operation owns this intent. Poll that operation;
          // this rejected signature must never be sent or checked as a receipt.
          saved = { ...saved, operationId: error.detail.operation_id, reference: String(error.detail.reference_id), signature: undefined, blockhash: undefined, conflict: true };
          sessionStorage.setItem(storage, JSON.stringify(saved)); setPending(saved); setState('Pending'); return;
        }
        // These responses are emitted before a durable operation or send exists.
        if (error instanceof ApiError && [400, 409, 422].includes(error.statusCode ?? 0)) { sessionStorage.removeItem(storage); setPending(null); setChecked(null); }
        setState(failureState(error));
      }
    }
    finally { busyRef.current = false; if (mounted.current) setBusy(false); }
  };
  return <>
    <WalletTransactionSignerBridge enabled={signer.signerEnabled} onSignerReady={signer.setSignerRef} />
    <Dialog.Root open={open} onOpenChange={v => { if (!busy) { setOpen(v); if (!v && !pending) { setChecked(null); setState(''); } } }}>
      <Dialog.Trigger asChild><button type="button" data-stage1-action={action} className={surface === 'climb' ? 'climb-action-row' : 'portfolio-action-row'}>{label}</button></Dialog.Trigger>
      <Dialog.Portal><Dialog.Overlay className="portfolio-dialog" /><Dialog.Content className="portfolio-dialog__sheet stage1-dialog" aria-describedby={undefined}>
        <div className="portfolio-dialog__head"><Dialog.Title>{label}</Dialog.Title><Dialog.Close className="portfolio-dialog__close" disabled={busy}>Close</Dialog.Close></div>
        {lot?.climbName && <p>{lot.climbName}</p>}
        {action === 'registration' && <div className="portfolio-sheet__stack"><span>Wallet</span><strong className="stage1-address">{user?.wallet}</strong></div>}
        {!checked && !pending && <>
          {action === 'pledge' && <div className="portfolio-sheet__entry">
            <label>{copy.token}<select aria-label={copy.token} value={selectedMint} disabled={busy} onChange={e => setMint(e.target.value)}>{tokens.map(a => <option key={a.mint} value={a.mint}>{STAGE1_MINTS[a.mint].symbol}</option>)}</select></label>
            <label className="portfolio-sheet__amount"><input aria-label={copy.amount} value={amount} inputMode="decimal" disabled={busy} onChange={e => setAmount(e.target.value)} /><span>{STAGE1_MINTS[selectedMint]?.symbol}</span></label>
          </div>}
          {(action === 'pledge' || action === 'convert-pledge') && <label>{copy.lock}<select aria-label={copy.lock} value={lock} disabled={busy} onChange={e => setLock(Number(e.target.value) as Stage1LockWeeks)}>{[0,13,26,52].map(n => <option key={n} value={n}>{formatInteger(n)}</option>)}</select></label>}
          <button type="button" className="portfolio-action-row" onClick={() => void prepare()} disabled={busy || (action === 'pledge' && (!units || BigInt(units) === 0n || !tokens.length))}>{state === 'Needs review' ? 'Try again' : 'Continue'}</button>
        </>}
        {checked && <div data-stage1-hold={checked.plan.action}>
          <p>{copy.confirmation}</p>
          {'mint' in checked.plan.intent && !['begin-withdrawal','complete-withdrawal'].includes(checked.plan.action) && <p>{stage1Amount({ mint: checked.plan.intent.mint, amount: checked.plan.intent.kind === 'stage1_pledge' ? checked.plan.intent.amountBaseUnits : claim?.intent.claims[0].amountBaseUnits ?? lot?.units })}</p>}
          {'hill' in checked.plan.intent && <p className="stage1-address">{checked.plan.intent.hill}</p>}
          {checked.plan.intent.kind === 'stage1_pledge' && checked.plan.intent.providerMode === 'prebond' && <p>{copy.foundingLock}: {formatInteger(26)}</p>}
          {['withdrawal-notice','begin-withdrawal','complete-withdrawal'].includes(checked.plan.action) && <p>{copy.basis}: {formatBaseUnits(withdrawal?.data.basisLamports ?? lot!.basisLamports!, 9, 9)} SOL</p>}
          {'lockWeeks' in checked.plan.intent && <p>{copy.lock}: {formatInteger(checked.plan.intent.lockWeeks)}</p>}
          {checked.plan.action === 'claim-transport' && <p>{copy.transport}<span className="stage1-address">{'lookupTable' in checked.plan.intent ? checked.plan.intent.lookupTable : ''}</span></p>}
          <HoldCapsule label={copy.hold} tone={action === 'pledge' ? 'in' : 'out'} disabled={!!pending} busy={busy} onCommit={() => void commit()} />
        </div>}
        {pausedUntil && <StateRow role="status" title={copy.withdrawalsPaused} />}
        {(state || pending) && <StateRow role="status" title={`${label} · ${state || 'Pending'}`} />}
      </Dialog.Content></Dialog.Portal>
    </Dialog.Root>
  </>;
}
