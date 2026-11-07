import { useSystemStatus } from '../hooks/useSystemStatus';
import { balanceActionIsOpen } from '../lib/balanceActionAvailability';
import { StateRow } from '../components/portal/FailureSpecies';
import { LoadingRows } from '../components/loading/LoadingSystem';
import { Slot } from '../components/loading/Slot';
import { useEffect, useRef, useState, type ReactNode } from 'react';
import { Stage1ClimbSection } from '../components/stage1/Stage1';
import { Link } from 'react-router-dom';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { useAuth } from '../contexts/AuthContext';
import { WalletTransactionSignerBridge } from '../components/auth/WalletTransactionSignerBridge';
import { useDeferredWalletTransactionSigner } from '../components/auth/useDeferredWalletTransactionSigner';
import HoldCapsule from '../components/portfolio/HoldCapsule';
import { ClimbNavigationRow, useClimbPanelPath } from '../components/climb/ClimbNavigation';
import { api, type RiderBalanceOperationStatus } from '../lib/api';
import { createClientRequestId } from '../lib/clientRequestId';
import { vaultWithdrawalIntent } from '../lib/portalTransactionIntent';
import { queryKeys } from '../lib/queryKeys';
import { ABSENT_VALUE, calculateNetAmountBaseUnits, formatBasisPointsPercentage, formatDate, formatInteger } from '../lib/formatters';
import { compareBaseUnits, decimalToBaseUnits, formatBaseUnits, isPositiveBaseUnits } from '../lib/tokenAmounts';
import { useMyVaultStakes, usePortfolio, useVault } from '../hooks/queries';

import { CLIMB_ACTION_TYPES as ACTION_TYPES, climbPosition, operationPhase, positionReflectsOperation, validBaseUnits, type ClimbVaultAction as Action, type ClimbVaultOperation as SavedOperation } from '../lib/climbVaultOperation';
type Phase = 'pending' | 'saved' | 'refreshed' | 'failure' | 'review' | 'delayed';
type Notice = { action: Action; phase: Phase };
const ACTION_LABELS = { deposit: 'Deposit CAL', withdraw: 'Withdraw CAL', collect: 'Collect DUNG' } as const;
const STATUS_LABELS: Record<Phase, string> = { pending: 'Pending', saved: 'Saved', refreshed: 'Refreshed', failure: 'Failed', review: 'Needs review', delayed: 'Delayed' };
const MESSAGES: Record<Action, Record<Phase, string>> = {
  deposit: { pending: 'Boulder Roller is preparing this climb position.', saved: 'Deposit saved. The climb position is refreshing.', refreshed: 'Deposit saved.', failure: 'Could not deposit CAL', review: 'Boulder Roller could not finish this deposit.', delayed: 'This deposit is taking longer than expected.' },
  withdraw: { pending: 'Boulder Roller is preparing this withdrawal.', saved: 'Withdrawal saved. The climb position is refreshing.', refreshed: 'Withdrawal saved.', failure: 'Could not withdraw CAL', review: 'Boulder Roller could not finish this withdrawal.', delayed: 'This withdrawal is taking longer than expected.' },
  collect: { pending: 'Boulder Roller is collecting DUNG from this climb.', saved: 'DUNG is collected and the climb view is catching up.', refreshed: 'DUNG received in your wallet.', failure: 'Could not collect DUNG', review: 'Boulder Roller could not finish this collection.', delayed: 'This collection is taking longer than expected.' },
};

function readSaved(key: string): { operation: SavedOperation | null; invalid: boolean } {
  try {
    const raw = sessionStorage.getItem(key);
    if (!raw) return { operation: null, invalid: false };
    const saved = JSON.parse(raw);
    const valid = saved && Object.prototype.hasOwnProperty.call(ACTION_TYPES, saved.action)
      && typeof saved.clientRequestId === 'string' && saved.clientRequestId.length > 0 && saved.clientRequestId.length <= 200
      && (!saved.operationId || typeof saved.operationId === 'string')
      && (saved.priorBaseUnits == null || validBaseUnits(saved.priorBaseUnits));
    return { operation: valid ? saved : null, invalid: !valid };
  } catch { return { operation: null, invalid: true }; }
}

type VaultSectionProps = { vaultId: number; panel?: Action | 'history' };
export default function ClimbVaultSection(props: Omit<VaultSectionProps, 'vaultId'> & { vaultId?: number | null; climbId?: string; fallback?: ReactNode }) {
  const { user } = useAuth();
  return <Stage1ClimbSection climbId={props.climbId} fallback={props.vaultId != null
    ? user ? <VaultSurface key={`${user.id}:${user.wallet}:${props.vaultId}`} vaultId={props.vaultId} panel={props.panel} /> : null
    : props.fallback} />;
}
function VaultSurface({ vaultId, panel }: VaultSectionProps) {
  const { user } = useAuth();
  const path = useClimbPanelPath();
  const withdrawOpen = balanceActionIsOpen(useSystemStatus(), 'withdraw_cal');
  const { setSignerRef, signerEnabled, signPreparedTransaction } = useDeferredWalletTransactionSigner();
  const queryClient = useQueryClient();
  const vaultQuery = useVault(vaultId);
  const stakesQuery = useMyVaultStakes(Boolean(user));
  const portfolioQuery = usePortfolio(Boolean(user));
  const vault = vaultQuery.data;
  let stake = null;
  let positionAvailable = stakesQuery.isSuccess && !stakesQuery.isError;
  try { if (positionAvailable) stake = climbPosition(stakesQuery.data!.stakes, vaultId, vault?.signatureHex); }
  catch { positionAvailable = false; }
  const balance = !portfolioQuery.isError && user ? portfolioQuery.data?.calBalanceBaseUnits ?? null : null;
  const rewardsQuery = useQuery({ placeholderData: undefined, queryKey: ['climb-vault-quote', vaultId, user?.id], queryFn: () => api.getVaultPendingRewards(vaultId), enabled: Boolean(user && stake), staleTime: 0 });
  const rewards = !positionAvailable || !stake || rewardsQuery.isError ? null : rewardsQuery.data;
  const history = useQuery({ placeholderData: undefined, queryKey: ['climb-dung-history', vaultId, user?.id], queryFn: () => api.getVaultDistributionHistory(vaultId), enabled: Boolean(user && panel === 'history'), staleTime: 60_000 });
  const [amount, setAmount] = useState('');
  const [busy, setBusy] = useState(false);
  const busyRef = useRef(false);
  const [notice, setNotice] = useState<Notice | null>(null);
  const storageKey = `br-climb-operation:${user?.id}:${user?.wallet}:${vaultId}`;
  const [stored] = useState(() => readSaved(storageKey));
  const [saved, setSaved] = useState<SavedOperation | null>(stored.operation);
  const mounted = useRef(true);
  useEffect(() => { mounted.current = true; return () => { mounted.current = false; }; }, []);
  const recoveryStarted = useRef(false);

  const refreshPosition = async (operation: SavedOperation) => {
    if (!mounted.current) return;
    setNotice({ action: operation.action, phase: 'saved' });
    try {
      const freshStakes = await api.getMyVaultStakes();
      const current = climbPosition(freshStakes.stakes, vaultId, vault?.signatureHex);
      const pending = operation.action === 'collect' ? await api.getVaultPendingRewards(vaultId) : null;
      if (!mounted.current) return;
      queryClient.setQueryData(queryKeys.vaults.myStakes, freshStakes);
      if (pending) queryClient.setQueryData(['climb-vault-quote', vaultId, user?.id], pending);
      if (!positionReflectsOperation(operation, current, pending?.totalPendingBaseUnits)) return;
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: queryKeys.vaults.detail(vaultId) }, { throwOnError: true }),
        queryClient.invalidateQueries({ queryKey: queryKeys.portfolio.all }, { throwOnError: true }),
      ]);
      if (!mounted.current) return;
      sessionStorage.removeItem(storageKey);
      setSaved(null);
      setNotice({ action: operation.action, phase: 'refreshed' });
    } catch { if (mounted.current) setNotice({ action: operation.action, phase: 'saved' }); }
  };

  const acceptStatus = async (operation: SavedOperation, status: RiderBalanceOperationStatus) => {
    if (!mounted.current) return;
    const phase = operationPhase(operation, status, vaultId);
    if (phase === 'recorded') await refreshPosition(operation);
    else setNotice({ action: operation.action, phase });
  };

  const recover = async (operation: SavedOperation) => {
    if (busyRef.current) return;
    busyRef.current = true; setBusy(true);
    try {
      const status = await api.lookupVaultOperation(vaultId, ACTION_TYPES[operation.action], operation.clientRequestId, operation.operationId);
      if (!mounted.current) return;
      if (status.operationId && operationPhase(operation, status, vaultId) !== 'review') {
        operation = { ...operation, operationId: status.operationId };
        sessionStorage.setItem(storageKey, JSON.stringify(operation)); setSaved(operation);
      }
      await acceptStatus(operation, status);
    } catch {
      // A missing/unavailable operation read never proves that a sent action failed.
      setNotice({ action: operation.action, phase: 'review' });
    } finally { busyRef.current = false; setBusy(false); }
  };

  useEffect(() => {
    if (saved && vault && !recoveryStarted.current && user) { recoveryStarted.current = true; void recover(saved); }
  }, [saved, user, vault]);

  const recoveryDeadline = useRef<number | null>(null);
  useEffect(() => {
    if (!saved || busy || (notice?.phase !== 'pending' && notice?.phase !== 'saved')) return;
    // Match the native MoneyModel's one-second reconciliation cadence and 20-second window.
    recoveryDeadline.current ??= Date.now() + 20_000;
    if (Date.now() >= recoveryDeadline.current) {
      if (notice.phase === 'pending') setNotice({ action: saved.action, phase: 'delayed' });
      return;
    }
    const timer = window.setTimeout(() => void recover(saved), 1000);
    return () => window.clearTimeout(timer);
  }, [saved, busy, notice?.phase]);

  const amountBaseUnits = decimalToBaseUnits(amount || '0', 9);
  const wholeAmount = /^[0-9]+$/.test(amount) && Number.isSafeInteger(Number(amount)) ? Number(amount) : null;
  const invalidAmount = Boolean(amount) && (wholeAmount === null || !amountBaseUnits);
  const tooLow = Boolean(amount) && wholeAmount !== null && wholeAmount < 100;
  const exceedsBalance = amountBaseUnits != null && balance != null && compareBaseUnits(amountBaseUnits, balance) > 0;
  const amountError = invalidAmount ? 'Use a whole CAL amount' : tooLow ? 'Minimum: 100 CAL' : exceedsBalance ? `Exceeds balance (${formatBaseUnits(balance!, 9, 2)} available)` : null;
  const exitMath = rewards?.withdrawalAmountBaseUnits ? calculateNetAmountBaseUnits(rewards.withdrawalAmountBaseUnits, rewards.exitFeeBps) : null;
  const exitQuote = exitMath && exitMath.feeBaseUnits === rewards?.withdrawalFeeBaseUnits && exitMath.netBaseUnits === rewards?.withdrawalNetBaseUnits
    && rewards.lpTokensBaseUnits === stake?.lpTokensBaseUnits ? exitMath : null;
  const collectMath = rewards ? calculateNetAmountBaseUnits(rewards.totalPendingBaseUnits, rewards.harvestFeeBps) : null;
  const collectQuote = collectMath && collectMath.feeBaseUnits === rewards?.feeEstimateBaseUnits && collectMath.netBaseUnits === rewards?.netEstimateBaseUnits ? collectMath : null;
  const canDeposit = Boolean(user && vault?.onChainActive === true && !vaultQuery.isError && balance != null && positionAvailable && !stakesQuery.isFetching && !portfolioQuery.isFetching && wholeAmount != null && wholeAmount >= 100 && !amountError);
  const canWithdraw = Boolean(withdrawOpen && user && positionAvailable && stake && isPositiveBaseUnits(stake.lpTokensBaseUnits) && exitQuote && !rewardsQuery.isFetching && !vaultQuery.isError);
  const canCollect = Boolean(user && positionAvailable && stake && collectQuote && isPositiveBaseUnits(rewards?.totalPendingBaseUnits) && !rewardsQuery.isFetching && !vaultQuery.isError);
  const locked = busy || Boolean(saved) || stored.invalid;

  const commit = async (action: Action) => {
    if (busyRef.current || saved || stored.invalid || !mounted.current || !user || !vault || (action === 'deposit' ? !canDeposit : action === 'withdraw' ? !canWithdraw : !canCollect)) return;
    busyRef.current = true; setBusy(true); setNotice({ action, phase: 'pending' });
    const operation: SavedOperation = { action, clientRequestId: createClientRequestId(ACTION_TYPES[action]) };
    let submitted = false;
    try {
      let signed: string | undefined;
      let blockHeight: number | undefined;
      const prior = climbPosition((await api.getMyVaultStakes()).stakes, vaultId, vault.signatureHex);
      if (!mounted.current) return;
      if (action === 'deposit') operation.priorBaseUnits = prior?.calStakedBaseUnits ?? '0';
      else if (action === 'withdraw') {
        if (!prior || prior.lpTokensBaseUnits !== stake?.lpTokensBaseUnits) throw new Error('Position changed');
        operation.priorBaseUnits = prior.lpTokensBaseUnits;
      } else if (!prior) throw new Error('Position unavailable');
      if (action === 'deposit') {
        const prepared = await api.prepareStakeInVault(vaultId, wholeAmount!);
        if (!mounted.current) return;
        signed = await signPreparedTransaction(prepared, { kind: 'stake', vaultId, amountBaseUnits: amountBaseUnits! });
        blockHeight = prepared.lastValidBlockHeight;
      } else if (action === 'withdraw') {
        const prepared = await api.prepareUnstakeFromVault(vaultId, { withdrawAll: true });
        if (!mounted.current) return;
        signed = await signPreparedTransaction(prepared, vaultWithdrawalIntent(vaultId, stake!.lpTokensBaseUnits));
        blockHeight = prepared.lastValidBlockHeight;
      }
      if (!mounted.current) return;
      // Owner-scoped, ephemeral recovery baseline; no signed transaction is stored.
      sessionStorage.setItem(storageKey, JSON.stringify(operation));
      recoveryStarted.current = true;
      setSaved(operation); submitted = true;
      const result = action === 'deposit' ? await api.stakeInVault(vaultId, wholeAmount!, signed, blockHeight, operation.clientRequestId)
        : action === 'withdraw' ? await api.unstakeFromVault(vaultId, { withdrawAll: true }, signed, blockHeight, operation.clientRequestId)
          : await api.harvestVaultRewards(vaultId, { clientRequestId: operation.clientRequestId });
      if (!mounted.current) return;
      if (result.operationId) { operation.operationId = result.operationId; sessionStorage.setItem(storageKey, JSON.stringify(operation)); setSaved({ ...operation }); }
      const status = await api.lookupVaultOperation(vaultId, ACTION_TYPES[action], operation.clientRequestId, operation.operationId);
      await acceptStatus(operation, status);
    } catch {
      if (submitted && mounted.current) {
        try { await acceptStatus(operation, await api.lookupVaultOperation(vaultId, ACTION_TYPES[action], operation.clientRequestId, operation.operationId)); }
        catch { if (mounted.current) setNotice({ action, phase: 'review' }); }
      } else if (mounted.current) setNotice({ action, phase: 'failure' });
    } finally { busyRef.current = false; setBusy(false); }
  };

  if (!user) return null;
  const operationStatus = stored.invalid ? <div className="climb-ledger-card climb-operation-status" role="status"><strong>Needs review</strong><p>Operation details unavailable.</p></div> : notice ? <div className="climb-ledger-card climb-operation-status" role="status" aria-live="polite" data-operation-phase={notice.phase}>
    <strong>{notice.phase === 'refreshed' ? notice.action === 'collect' ? 'Collected' : notice.action === 'deposit' ? 'Deposited' : 'Withdrawn' : STATUS_LABELS[notice.phase]}</strong>
    <p>{MESSAGES[notice.action][notice.phase]}</p>
    {saved && !busy && <button className="climb-text-button" onClick={() => void recover(saved)}>Refresh</button>}
    {notice.phase === 'failure' && !busy && <button className="climb-text-button" onClick={() => setNotice(null)}>Try again</button>}
  </div> : null;
  const kv = (label: string, value: string) => <div className="climb-kv"><span>{label}</span><strong>{value}</strong></div>;

  if (panel === 'history') return <section aria-label="DUNG history" aria-busy={history.isFetching}>
    {history.isPending ? <LoadingRows label="Loading DUNG history" rows={4} /> : history.isError ? <StateRow title="DUNG history unavailable" action={<button onClick={() => void history.refetch()}>Try again</button>} />
      : !history.data?.distributions.length ? <div className="climb-ledger-card climb-ledger-empty">No DUNG weeks yet</div> : history.data.distributions.map((dist) => <div key={dist.distributionId} className="climb-history-list"><h2>Week of {formatDate(dist.distributedAt)}</h2><div className="climb-ledger-card">
        {kv('Total', `${formatBaseUnits(dist.totalAmountBaseUnits, 9, 2)} DUNG`)}{kv('Top 10', `${formatBaseUnits(dist.leaderboardAmountBaseUnits, 9, 2)} DUNG`)}{kv('Backers', `${formatBaseUnits(dist.stakerAmountBaseUnits, 9, 2)} DUNG`)}{kv('Legend', `${formatBaseUnits(dist.localLegendAmountBaseUnits, 9, 2)} DUNG`)}{kv('POL', `${formatBaseUnits(dist.polAmountBaseUnits, 9, 2)} DUNG`)}{kv('Treasury', `${formatBaseUnits(dist.protocolAmountBaseUnits, 9, 2)} DUNG`)}
      </div></div>)}
  </section>;

  if (panel === 'withdraw' && !withdrawOpen) return <section aria-label="Withdraw CAL">
    <StateRow title="Not open yet" />
    {operationStatus}
  </section>;

  if (panel) return <section aria-label={ACTION_LABELS[panel]}>
    <WalletTransactionSignerBridge enabled={signerEnabled} onSignerReady={setSignerRef} />
    {operationStatus || <>
      {panel === 'deposit' ? <><div className="climb-ledger-card">{kv('Available CAL', balance == null ? ABSENT_VALUE : `${formatBaseUnits(balance, 9, 2)} CAL`)}
        <label className="climb-amount-field">CAL<input type="text" inputMode="numeric" autoComplete="off" value={amount} onChange={(event) => setAmount(event.target.value)} aria-invalid={Boolean(amountError)} aria-describedby="climb-amount-note" /></label>
      </div><p className="climb-ledger-note" id="climb-amount-note">{amountError || 'Minimum: 100 CAL'}</p></>
        : panel === 'withdraw' ? <div className="climb-ledger-card">{kv('Total', rewards?.withdrawalAmountBaseUnits && exitQuote ? `${formatBaseUnits(rewards.withdrawalAmountBaseUnits, 9, 2)} CAL` : ABSENT_VALUE)}{kv('Exit fee', exitQuote ? `−${formatBaseUnits(exitQuote.feeBaseUnits, 9, 2)} CAL` : ABSENT_VALUE)}{kv('You receive', exitQuote ? `${formatBaseUnits(exitQuote.netBaseUnits, 9, 2)} CAL` : ABSENT_VALUE)}</div>
          : <><div className="climb-ledger-card">{kv('Total', rewards && collectQuote ? `${formatBaseUnits(rewards.totalPendingBaseUnits, 9, 2)} DUNG` : ABSENT_VALUE)}{kv('Collection fee', collectQuote ? `−${formatBaseUnits(collectQuote.feeBaseUnits, 9, 2)} DUNG` : ABSENT_VALUE)}{kv('You receive', collectQuote ? `${formatBaseUnits(collectQuote.netBaseUnits, 9, 2)} DUNG` : ABSENT_VALUE)}</div>{rewards && collectQuote && <p className="climb-ledger-note">Collecting takes a {formatBasisPointsPercentage(rewards.harvestFeeBps)} fee.</p>}</>}
      {portfolioQuery.isError && panel === 'deposit' && <p className="climb-ledger-note">Balance unavailable<button className="climb-text-button" onClick={() => void portfolioQuery.refetch()}>Try again</button></p>}
      {panel !== 'deposit' && !rewardsQuery.isPending && (rewardsQuery.isError || (panel === 'withdraw' ? !exitQuote : !collectQuote)) && <p className="climb-ledger-note">Could not load vault<button className="climb-text-button" onClick={() => void rewardsQuery.refetch()}>Try again</button></p>}
      <HoldCapsule label={`Hold to ${panel === 'deposit' ? `Deposit ${amountBaseUnits && !amountError ? formatBaseUnits(amountBaseUnits, 9, 0) : ABSENT_VALUE} CAL` : panel === 'withdraw' ? `Withdraw ${exitQuote && rewards?.withdrawalAmountBaseUnits ? formatBaseUnits(rewards.withdrawalAmountBaseUnits, 9, 2) : ABSENT_VALUE} CAL` : `Collect ${collectQuote ? formatBaseUnits(collectQuote.netBaseUnits, 9, 2) : ABSENT_VALUE} DUNG`}`} tone={panel === 'withdraw' ? 'out' : 'in'} busy={busy} disabled={locked || !(panel === 'deposit' ? canDeposit : panel === 'withdraw' ? canWithdraw : canCollect)} onCommit={() => void commit(panel)} />
    </>}
  </section>;

  return <div className="climb-vault-stack" data-object-layer="climb-economy">
    <section id="climb-position" aria-label="Your position">
      <div className="profile-eyebrow"><div className="climb-section-heading"><h3>Your position</h3></div></div>
      <div className="climb-ledger-card">
        <div className="climb-position-numeral">{positionAvailable ? `${formatBaseUnits(stake?.calStakedBaseUnits ?? '0', 9, 2)} CAL` : ABSENT_VALUE}</div>
        {kv('Since', positionAvailable && stake ? formatDate(stake.stakedAt) : ABSENT_VALUE)}
        {canCollect ? <ClimbNavigationRow label="DUNG ready" to={path('collect')} value={`${formatBaseUnits(rewards!.totalPendingBaseUnits, 9, 2)} DUNG`} /> : kv('DUNG ready', rewards ? `${formatBaseUnits(rewards.totalPendingBaseUnits, 9, 2)} DUNG` : ABSENT_VALUE)}
        {vault && vault.onChainActive === true && !vaultQuery.isError && <Link className="climb-action-row" to={path('deposit')}>Deposit CAL</Link>}
        {positionAvailable && stake && (withdrawOpen
          ? <Link className="climb-action-row" data-tone="out" to={path('withdraw')}>Withdraw CAL</Link>
          : <button type="button" className="climb-action-row" disabled><span>Withdraw CAL</span><span className="balance-action-state">Not open yet</span></button>)}
      </div>
      {operationStatus}
    </section>
    <section id="climb-vault" aria-label="Vault">
      <div className="profile-eyebrow"><div className="climb-section-heading"><h2>Vault</h2>{vaultQuery.isPending ? <Slot /> : !vaultQuery.isError && vault && vault.onChainActive !== true ? <span>Initializing</span> : null}</div></div>
      {vaultQuery.isPending ? <LoadingRows label="Loading vault details" rows={4} /> : vaultQuery.isError || !vault ? <StateRow title="Vault unavailable" action={<button onClick={() => void vaultQuery.refetch()}>Try again</button>} /> : <>
        <div className="climb-ledger-card climb-vault-summary" aria-label="Vault metrics">
          {kv('Completions', formatInteger(vault.totalCompletions))}
          {kv('CAL deposited', `${formatBaseUnits(vault.totalStakedBaseUnits, 9, 2)} CAL`)}
          {kv('Leaderboard pool', ABSENT_VALUE)}
          <ClimbNavigationRow label="DUNG history" to={path('history')} />
        </div>
        {vault.onChainActive !== true && <div className="climb-ledger-card climb-ledger-empty"><strong>This vault is still opening.</strong><p>Deposits open when the climb is ready.</p></div>}
      </>}
    </section>
  </div>;
}
