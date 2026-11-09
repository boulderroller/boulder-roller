import { useSystemStatus } from '../hooks/useSystemStatus';
import { balanceActionIsOpen } from '../lib/balanceActionAvailability';
import { StateRow } from '../components/portal/FailureSpecies';
import { Slot, SlotRows } from '../components/loading/Slot';
import { useEffect, useMemo, useState } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import { Link } from 'react-router-dom';
import { RefreshCw } from 'lucide-react';
import { toast } from 'sonner';
import { api, type DistributionGroup, type VaultPendingRewardsResponse } from '../lib/api';
import { usePortfolioSnapshot, collectionReadModel } from '../hooks/queries/usePortfolio';
import { useAuth } from '../contexts/AuthContext';
import { readSubjectStates } from '../lib/protocolStates';
import { queryKeys } from '../lib/queryKeys';
import {
  ABSENT_VALUE,
  calculateNetAmountBaseUnits,
  formatBasisPointsPercentage,
  formatDate,
  formatInteger,
} from '../lib/formatters';
import { useDeferredWalletTransactionSigner } from '../components/auth/useDeferredWalletTransactionSigner';
import { WalletTransactionSignerBridge } from '../components/auth/WalletTransactionSignerBridge';
import { formatBaseUnits, isPositiveBaseUnits, sumBaseUnits } from '../lib/tokenAmounts';
import { RankMark } from '../components/rankmarks/RankMark';
import { resolveRankMarkAsset } from '../assets/rankmarks';
import BalanceSheet, { type BalanceSheetMode } from '../components/portfolio/BalanceSheet';
import { Stage1Portfolio } from '../components/stage1/Stage1';

// Portfolio — the money room (Tim-ratified 2026-09-02). One hero: the
// wallet's CAL as a giant numeral, a read-only fact. Beside it the Balance
// sheet (Add funds in cobalt, Withdraw to wallet in gray, the wallet row).
// Positions as ledger rows with the rank mark, each opening its climb page,
// where Deposit and Withdraw live. Settlements on the right: Uncollected
// with one Collect and the fee stated, then History in gray. Economic
// surface: strict abstention — exact base units through the format path,
// never a sum across custody, never an estimate the chain did not confirm.

const RECEIPT_LABELS: Record<string, string> = {
  LEADERBOARD: 'Leaderboard',
  STAKE: 'Backer',
  LOCAL_LEGEND: 'Local Legend',
  POL: 'Reserve',
  PROTOCOL: 'Platform',
};

type PortfolioPositionSummary = {
  id: string;
  climbId?: string | null;
  climbName: string;
  vaultId?: string | number | null;
  vaultName?: string | null;
  calDepositedBaseUnits?: string | null;
  dungReadyBaseUnits?: string | null;
  recordRank?: number | null;
  localLegend?: boolean;
  status?: string | null;
};

type DistributionGroupWithObject = DistributionGroup & {
  climbId?: string | null;
  climbName?: string | null;
  vaultId?: string | number | null;
  vaultName?: string | null;
};

const formatAmountBaseUnits = (value: string | null | undefined) => (
  value == null ? '' : formatBaseUnits(value, 9, 2).replace(ABSENT_VALUE, '')
);

const isRecord = (value: unknown): value is Record<string, unknown> => (
  Boolean(value) && typeof value === 'object' && !Array.isArray(value)
);

const readString = (source: Record<string, unknown>, keys: string[]) => {
  for (const key of keys) {
    const value = source[key];
    if (typeof value === 'string' && value.trim()) return value.trim();
    if (typeof value === 'number' && Number.isFinite(value)) return String(value);
  }
  return null;
};

const readNumber = (source: Record<string, unknown>, keys: string[]) => {
  for (const key of keys) {
    const value = source[key];
    if (typeof value === 'number' && Number.isFinite(value)) return value;
    if (typeof value === 'string' && value.trim()) {
      const parsed = Number(value);
      if (Number.isFinite(parsed)) return parsed;
    }
  }
  return null;
};

const readBaseUnits = (source: Record<string, unknown>, keys: string[]) => {
  for (const key of keys) {
    const value = source[key];
    if (typeof value !== 'string') continue;
    try {
      return sumBaseUnits([value]);
    } catch {
      // Ignore malformed compatibility fields and keep looking for an exact source.
    }
  }
  return null;
};

const readBoolean = (source: Record<string, unknown>, keys: string[]) => {
  for (const key of keys) {
    const value = source[key];
    if (typeof value === 'boolean') return value;
  }
  return false;
};

function positionFromUnknown(value: unknown, index: number): PortfolioPositionSummary | null {
  if (!isRecord(value)) return null;
  const climbId = readString(value, ['climbId', 'climb_id']);
  const vaultId = readString(value, ['vaultId', 'vault_id']);
  const climbName = readString(value, ['climbName', 'climb_name', 'segmentName', 'segment_name', 'name'])
    ?? readString(value, ['vaultName', 'vault_name'])
    ?? 'Climb vault';
  return {
    id: readString(value, ['id', 'positionId', 'position_id', 'stakeId', 'stake_id'])
      ?? `${climbId ?? vaultId ?? 'position'}-${formatInteger(index)}`,
    climbId,
    climbName,
    vaultId,
    vaultName: readString(value, ['vaultName', 'vault_name']),
    calDepositedBaseUnits: readBaseUnits(value, ['calDepositedBaseUnits', 'cal_deposited_base_units', 'calStaked', 'cal_staked']),
    dungReadyBaseUnits: readBaseUnits(value, ['dungReadyBaseUnits', 'dung_ready_base_units']),
    recordRank: readNumber(value, ['recordRank', 'record_rank', 'rank', 'leaderboardRank', 'leaderboard_rank']),
    localLegend: readBoolean(value, ['localLegend', 'local_legend', 'isLocalLegend', 'is_local_legend']),
    status: readSubjectStates(value.subjectStates).find(state => state.subject === 'position')?.label ?? null,
  };
}

const positionHref = (position: PortfolioPositionSummary) => {
  if (position.climbId) return `/climbs/${encodeURIComponent(position.climbId)}`;
  if (position.vaultId) return `/vaults/${encodeURIComponent(String(position.vaultId))}`;
  return null;
};

const positionKind = (rank?: number | null): 'Crown' | 'Seat' | null => {
  if (!rank || !Number.isFinite(rank) || rank < 1) return null;
  if (rank === 1) return 'Crown';
  if (rank <= 10) return 'Seat';
  return null;
};

const positionVaultId = (position: PortfolioPositionSummary): number | null => {
  const vaultId = typeof position.vaultId === 'number' ? position.vaultId : Number(position.vaultId);
  return Number.isSafeInteger(vaultId) && vaultId > 0 ? vaultId : null;
};

const shortWallet = (wallet: string | null | undefined): string | null => {
  if (!wallet || wallet.length < 10) return wallet || null;
  return `${wallet.slice(0, 4)}…${wallet.slice(-3)}`;
};

function balancePlanMeta(plan: { projectionStatus?: string; blockers: string[] } | null, error?: string | null) {
  if (error) return 'Paused';
  if (!plan) return null;
  if (plan.projectionStatus === 'delayed') return 'Delayed';
  if (plan.blockers.length > 0) return 'Needs setup';
  return 'Ready';
}

function Chevron() {
  return (
    <svg className="portfolio-row__chevron" width="8" height="12" viewBox="0 0 8 12" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <path d="M2 1.5 L6.5 6 L2 10.5" />
    </svg>
  );
}

// Per-vault pending-reward quotes back the Uncollected card. A quote counts
// only when the chain's fee and net estimates match the ledger's own
// arithmetic; anything else abstains rather than showing a guess.
function useVaultQuotes(vaultIds: number[]) {
  const key = vaultIds.join(',');
  const [quotes, setQuotes] = useState<Record<number, VaultPendingRewardsResponse>>({});
  const [version, setVersion] = useState(0);

  useEffect(() => {
    let cancelled = false;
    const ids = key ? key.split(',').map(Number) : [];
    if (ids.length === 0) {
      setQuotes({});
      return () => { cancelled = true; };
    }
    void Promise.all(ids.map((id) => api.getVaultPendingRewards(id)
      .then((quote) => [id, quote] as const)
      .catch(() => [id, null] as const)))
      .then((entries) => {
        if (cancelled) return;
        const next: Record<number, VaultPendingRewardsResponse> = {};
        for (const [id, quote] of entries) if (quote) next[id] = quote;
        setQuotes(next);
      });
    return () => { cancelled = true; };
  }, [key, version]);

  return { quotes, refresh: () => setVersion((value) => value + 1) };
}

export default function Portfolio() {
  const queryClient = useQueryClient();
  const systemStatus = useSystemStatus();
  const addFundsOpen = balanceActionIsOpen(systemStatus, 'add_funds');
  const withdrawOpen = balanceActionIsOpen(systemStatus, 'withdraw_to_wallet');
  const { walletAddress } = useAuth();
  const { setSignerRef, signerEnabled, signPreparedTransaction } = useDeferredWalletTransactionSigner();
  const [sheet, setSheet] = useState<BalanceSheetMode | null>(null);
  const [collecting, setCollecting] = useState(false);

  const {
    data: snapshot = null,
    isLoading: loading,
    error: snapshotError,
    refetch: refetchPortfolio,
  } = usePortfolioSnapshot();

  const portfolio = snapshot?.portfolio ?? null;
  const distributions = snapshot?.distributions?.distributions ?? [];
  const error = snapshotError ? (snapshotError instanceof Error ? snapshotError.message : 'Could not load portfolio') : null;
  const chainPaused = snapshot?.freshness?.chainStatus === 'unavailable';
  const tokenSnapshotError = chainPaused ? 'One or more live balances are unavailable. Retry to refresh them.' : null;

  // Wallet facts: the on-chain wallet, named as such and never summed with Balance.
  // A live read with RPC account-existence evidence may show exact zero; a live
  // amount without that evidence shows only when positive (a missing ATA also reads 0).
  const walletCalLive = portfolio?.freshness?.calStatus === 'live';
  const walletCalExists = portfolio?.freshness?.calAccountExists === true;
  const walletCalBaseUnits = walletCalLive && (walletCalExists || isPositiveBaseUnits(portfolio?.calBalanceBaseUnits))
    ? portfolio?.calBalanceBaseUnits ?? null : null;
  const walletCal = walletCalBaseUnits == null ? '' : formatAmountBaseUnits(walletCalBaseUnits);
  const walletDung = portfolio?.walletDung?.status === 'unavailable' || portfolio?.walletDung?.status !== 'live'
    ? ''
    : formatAmountBaseUnits(portfolio?.walletDung?.amountBaseUnits);
  const balanceLifecycle = portfolio?.balanceLifecycle ?? null;

  const positions = useMemo(() => (portfolio?.stakedPositions ?? [])
    .map(positionFromUnknown)
    .filter((position): position is PortfolioPositionSummary => Boolean(position)), [portfolio?.stakedPositions]);
  const depositedBaseUnits = portfolio?.totalStakedBaseUnits;
  const collection = collectionReadModel(snapshot);
  const vaultIds = useMemo(() => positions
    .map(positionVaultId)
    .filter((id): id is number => id !== null), [positions]);
  const { quotes, refresh: refreshQuotes } = useVaultQuotes(vaultIds);

  // Uncollected: only quotes whose fee and net the ledger can reproduce.
  const uncollected = useMemo(() => {
    let pendingTotal = '0';
    let netTotal = '0';
    const collectable: number[] = [];
    let feeBps: string | null = null;
    let consistent = true;
    for (const id of vaultIds) {
      const quote = quotes[id];
      if (!quote || !isPositiveBaseUnits(quote.totalPendingBaseUnits)) continue;
      const preview = calculateNetAmountBaseUnits(quote.totalPendingBaseUnits, quote.harvestFeeBps);
      if (preview.feeBaseUnits !== quote.feeEstimateBaseUnits || preview.netBaseUnits !== quote.netEstimateBaseUnits) {
        consistent = false;
        continue;
      }
      if (feeBps == null) feeBps = quote.harvestFeeBps;
      else if (feeBps !== quote.harvestFeeBps) consistent = false;
      pendingTotal = sumBaseUnits([pendingTotal, quote.totalPendingBaseUnits]);
      netTotal = sumBaseUnits([netTotal, preview.netBaseUnits]);
      collectable.push(id);
    }
    return { pendingTotal, netTotal, collectable, feeBps, consistent };
  }, [quotes, vaultIds]);

  const refreshAfterAction = async () => {
    await Promise.all([
      queryClient.invalidateQueries({ queryKey: queryKeys.portfolio.all }),
      queryClient.invalidateQueries({ queryKey: queryKeys.portfolio.snapshot }),
      queryClient.invalidateQueries({ queryKey: queryKeys.portfolio.cal }),
    ]);
    refreshQuotes();
  };

  const collect = async () => {
    if (collecting || uncollected.collectable.length === 0) return;
    setCollecting(true);
    try {
      for (const id of uncollected.collectable) {
        await api.harvestVaultRewards(id);
      }
      toast.success('Collect DUNG pending');
      await refreshAfterAction();
    } catch (err) {
      toast.error(err instanceof Error ? err.message : 'Could not collect DUNG');
    } finally {
      setCollecting(false);
    }
  };

  const copyWallet = async () => {
    if (!walletAddress) return;
    try {
      await navigator.clipboard.writeText(walletAddress);
      toast.success('Address copied');
    } catch {
      toast.error('Could not copy address');
    }
  };

  const retryPortfolio = () => { void refetchPortfolio(); };
  const walletLabel = shortWallet(walletAddress);
  const plan = balanceLifecycle;
  const canUseActions = Boolean(plan) && plan?.projectionStatus !== 'delayed';
  const canAddFunds = addFundsOpen && Boolean(plan?.canAddFunds) && canUseActions;
  const canWithdraw = withdrawOpen && Boolean(plan?.canWithdrawToWallet) && canUseActions;
  const balanceAssets = plan?.assets ?? [];
  const pendingReady = isPositiveBaseUnits(uncollected.pendingTotal);
  const showUncollected = (positions.length > 0 || collection.total != null) && !loading && !error;

  return (
    <section
      className="portfolio-page"
      data-object-page="portfolio"
      aria-busy={loading}
      aria-live="polite"
    >
      {signerEnabled && (
        <WalletTransactionSignerBridge enabled onSignerReady={setSignerRef} />
      )}
      <h1 className="portfolio-page__title">Portfolio</h1>

      <div className="portfolio-hero">
        <div className="portfolio-hero__facts" aria-label="Portfolio summary">
          <span className="profile-eyebrow"><span>Wallet</span><span className="portfolio-sheet__meta"> · {error || tokenSnapshotError ? 'Last loaded' : 'Current'}</span></span>
          <div className="portfolio-hero__numeral" aria-label="Wallet CAL">
            <strong>{loading ? <Slot variant="number" /> : walletCal}</strong>
            <span>Wallet CAL</span>
          </div>
          <div className="portfolio-hero__pairs" aria-label="Wallet snapshot">
            {(loading || depositedBaseUnits != null) && <div className="profile-pair">
              <strong>{loading ? <Slot variant="number" /> : formatAmountBaseUnits(depositedBaseUnits)}</strong>
              <span>CAL deposited on climbs</span>
            </div>}
            <div className="profile-pair">
              <strong>{loading ? <Slot variant="number" /> : walletDung}</strong>
              <span>Wallet DUNG</span>
            </div>
          </div>
        </div>

        <div className="portfolio-sheet" aria-label="Boulder Roller Balance">
          <div className="portfolio-sheet__head">
            <span className="profile-eyebrow">Boulder Roller Balance</span>
            <span className="portfolio-sheet__meta">{balancePlanMeta(plan, error)}</span>
          </div>
          {balanceAssets.length > 0 ? (
            <div aria-label="Balance assets">
              {balanceAssets.map((asset) => {
                const decimals = asset.asset === 'USDC' ? 6 : 9;
                const amount = asset.exists && asset.sourceStatus === 'live' && asset.balanceBaseUnits != null
                  ? formatBaseUnits(asset.balanceBaseUnits, decimals, 2)
                  : '';
                return (
                  <div key={asset.asset} className="portfolio-row portfolio-row--static">
                    <span className="portfolio-row__asset">{asset.asset}</span>
                    <strong className="portfolio-row__amount" data-absent={amount === '' ? 'true' : 'false'}>{amount}</strong>
                  </div>
                );
              })}
            </div>
          ) : null}
          {(plan?.setupSteps ?? []).map((step) => (
            <div key={`${step.actionType}-${step.asset ?? 'balance'}`} className="portfolio-row portfolio-row--static portfolio-row--muted">
              <span className="portfolio-row__copy"><strong>{step.riderLabel}</strong></span>
            </div>
          ))}
          <button
            type="button"
            className="portfolio-action-row portfolio-action-row--in"
            disabled={!canAddFunds}
            onClick={() => setSheet('add_funds')}
          >
            <span>Add funds</span>{!addFundsOpen && <span className="balance-action-state">Not open yet</span>}
          </button>
          <button
            type="button"
            className="portfolio-action-row"
            disabled={!canWithdraw}
            onClick={() => setSheet('withdraw_to_wallet')}
          >
            <span>Withdraw to wallet</span>{!withdrawOpen && <span className="balance-action-state">Not open yet</span>}
          </button>
          {walletLabel ? (
            <button type="button" className="portfolio-row" onClick={() => void copyWallet()}>
              <span className="portfolio-row__asset">Wallet</span>
              <span className="portfolio-row__wallet">{walletLabel}<Chevron /></span>
            </button>
          ) : null}
          {plan?.riderDetail ? <div className="portfolio-sheet__footer">{plan.riderDetail}</div> : null}
        </div>
      </div>

      {(error || tokenSnapshotError) ? (
        <StateRow role="status" title="Live balance unavailable." description={error || tokenSnapshotError} action={<button type="button" onClick={retryPortfolio}>Try again</button>} />
      ) : null}

      <Stage1Portfolio />
      <div className="portfolio-columns">
        <section className="portfolio-sheet" data-object-layer="portfolio-positions" aria-label="Positions">
          <div className="portfolio-sheet__head">
            <span className="profile-eyebrow"><span>Positions</span><span className="portfolio-sheet__meta"> · {error ? 'Paused' : 'Current'}</span></span>
          </div>
          {positions.length > 0 ? positions.map((position) => {
            const href = positionHref(position);
            const kind = positionKind(position.recordRank);
            const sub = [kind, position.localLegend ? 'Local Legend' : null].filter(Boolean).join(' · ');
            const readyAmount = collection.rows.get(positionVaultId(position) ?? -1);
            const ready = readyAmount != null
              ? `${formatAmountBaseUnits(readyAmount)} DUNG ready`
              : null;
            const mark = position.recordRank != null && resolveRankMarkAsset(position.recordRank)
              ? <RankMark rank={position.recordRank} size={28} />
              : <span />;
            const body = (
              <>
                <span className="portfolio-row__mark">{mark}</span>
                <span className="portfolio-row__copy">
                  <strong>{position.climbName}</strong>
                  {sub ? <span>{sub}</span> : null}
                  {position.status ? <span data-state-subject="position">Position · {position.status}</span> : null}
                </span>
                <span className="portfolio-row__trail">
                  <strong>{position.calDepositedBaseUnits != null ? `${formatAmountBaseUnits(position.calDepositedBaseUnits)} CAL` : null}</strong>
                  <span data-absent={ready ? 'false' : 'true'}>{ready ?? ''}</span>
                </span>
                {href ? <Chevron /> : <span />}
              </>
            );
            return href ? (
              <Link key={position.id} to={href} className="portfolio-row portfolio-row--tall portfolio-row--position" data-object-row="climb-position">
                {body}
              </Link>
            ) : (
              <div key={position.id} className="portfolio-row portfolio-row--tall portfolio-row--position portfolio-row--static" data-object-row="climb-position">
                {body}
              </div>
            );
          }) : (
            loading ? <SlotRows count={6} /> : <StateRow title={error || 'No climb positions yet. Deposit CAL in a climb vault to see it here.'} action={error ? <button onClick={retryPortfolio}>Try again</button> : undefined} />
          )}
        </section>

        <div className="portfolio-columns__rail">
          {showUncollected ? (
            <section className="portfolio-sheet" aria-label="Uncollected">
              <div className="portfolio-sheet__head">
                <span className="profile-eyebrow">Uncollected</span>
              </div>
              {collection.total != null && <div className="portfolio-uncollected">
                <strong>{formatAmountBaseUnits(collection.total)}</strong>
                <span>DUNG ready</span>
              </div>}
              {pendingReady && uncollected.consistent ? (
                <>
                  <button
                    type="button"
                    className="portfolio-action-row portfolio-action-row--in"
                    disabled={collecting}
                    onClick={() => void collect()}
                  >
                    {collecting ? 'Collecting DUNG' : 'Collect DUNG'}
                  </button>
                  {collection.total != null && collection.total === uncollected.pendingTotal && uncollected.feeBps ? (
                    <div className="portfolio-sheet__footer">
                      {`Collecting takes a ${formatBasisPointsPercentage(uncollected.feeBps)} fee. `}
                      <strong>{`You receive ${formatAmountBaseUnits(uncollected.netTotal)} DUNG`}</strong>
                    </div>
                  ) : null}
                </>
              ) : null}
            </section>
          ) : null}

          <section className="portfolio-sheet" data-object-layer="portfolio-receipts" aria-label="History">
            <div className="portfolio-sheet__head">
              <span className="profile-eyebrow">History</span>
              <span className="portfolio-sheet__meta">Weekly DUNG</span>
            </div>
            {distributions.length > 0 ? distributions.map((group: DistributionGroup) => {
              const objectGroup = group as DistributionGroupWithObject;
              const total = sumBaseUnits(group.receipts.map((receipt) => receipt.amountBaseUnits));
              const weekLabel = `Week ${formatInteger(group.epoch)}`;
              return (
                <div key={group.distributionId} className="portfolio-history__group">
                  <div className="portfolio-row portfolio-row--static portfolio-row--muted">
                    <span className="portfolio-row__copy">
                      <strong>{objectGroup.climbName ?? objectGroup.vaultName ?? weekLabel}</strong>
                      <span>{`${weekLabel} · ${formatDate(group.distributedAt)}`}</span>
                    </span>
                    <span className="portfolio-row__trail">
                      <strong>{`+${formatBaseUnits(total, 9, 2)} DUNG`}</strong>
                    </span>
                  </div>
                  {group.receipts.map((receipt) => {
                    const label = RECEIPT_LABELS[receipt.receiptType] ?? receipt.receiptType;
                    const rankLabel = receipt.rank ? ` #${formatInteger(receipt.rank)}` : '';
                    return (
                      <div key={receipt.id} className="portfolio-row portfolio-row--receipt portfolio-row--static portfolio-row--muted" data-object-row="dung-receipt">
                        <span />
                        <span className="portfolio-row__copy"><span>{`${label}${rankLabel}`}</span></span>
                        <span className="portfolio-row__trail">
                          <strong>{`+${formatBaseUnits(receipt.amountBaseUnits, 9, 2)} DUNG`}</strong>
                        </span>
                      </div>
                    );
                  })}
                </div>
              );
            }) : (
              loading ? <SlotRows count={6} /> : <StateRow title={error || 'Weekly DUNG receipts will appear here after weekly settlement clears.'} action={error ? <button onClick={retryPortfolio}>Try again</button> : undefined} />
            )}
          </section>
        </div>
      </div>

      {sheet && plan ? (
        <BalanceSheet
          mode={sheet}
          plan={plan}
          walletLabel={walletLabel}
          walletCalBaseUnits={walletCalBaseUnits}
          signPreparedTransaction={signPreparedTransaction}
          onActionComplete={refreshAfterAction}
          onClose={() => setSheet(null)}
        />
      ) : null}
    </section>
  );
}
