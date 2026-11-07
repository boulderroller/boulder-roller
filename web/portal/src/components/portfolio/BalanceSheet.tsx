import { useSystemStatus } from '../../hooks/useSystemStatus';
import { balanceActionIsOpen } from '../../lib/balanceActionAvailability';
import { useEffect, useId, useState } from 'react';
import { api, type BalanceAssetView, type BalanceLifecyclePlan, type PreparedBalanceAction } from '../../lib/api';
import { createClientRequestId } from '../../lib/clientRequestId';
import { baseUnitsToDecimalString, compareBaseUnits, decimalToBaseUnits, formatBaseUnits, isPositiveBaseUnits } from '../../lib/tokenAmounts';
import type { useDeferredWalletTransactionSigner } from '../auth/useDeferredWalletTransactionSigner';
import HoldCapsule from './HoldCapsule';

// The Balance sheets (Portfolio board, Tim-ratified 2026-09-02): the iOS
// deposit sheet on web. A giant numeral, the available amount and Max, a
// card stack that reads as a sentence (From, To), and one hold capsule —
// blue for money in, gray for money out. No gas, no approve, no slippage:
// Balance eats it. The prepare → sign → submit flows are unchanged.

export type BalanceSheetMode = 'add_funds' | 'withdraw_to_wallet';
type FundingAsset = 'CAL' | 'USDC';
type WalletAsset = 'CAL' | 'USDC' | 'DUNG';

const DECIMALS: Record<WalletAsset, number> = { CAL: 9, USDC: 6, DUNG: 9 };

interface BalanceSheetProps {
  mode: BalanceSheetMode;
  plan: BalanceLifecyclePlan;
  walletLabel: string | null;
  walletCalBaseUnits: string | null;
  signPreparedTransaction: ReturnType<typeof useDeferredWalletTransactionSigner>['signPreparedTransaction'];
  onActionComplete: () => Promise<void>;
  onClose: () => void;
}

export default function BalanceSheet({
  mode,
  plan,
  walletLabel,
  walletCalBaseUnits,
  signPreparedTransaction,
  onActionComplete,
  onClose,
}: BalanceSheetProps) {
  const actionOpen = balanceActionIsOpen(useSystemStatus(), mode);
  const titleId = useId();
  const [selectedAsset, setSelectedAsset] = useState<WalletAsset>('CAL');
  const [amount, setAmount] = useState('');
  const [actionError, setActionError] = useState<string | null>(null);
  const [actionResult, setActionResult] = useState<PreparedBalanceAction | null>(null);
  const [submitting, setSubmitting] = useState(false);

  const assets = plan.assets ?? [];
  const addFundsAssets = assets.filter((asset): asset is BalanceAssetView & { asset: FundingAsset } => (
    (asset.asset === 'CAL' || asset.asset === 'USDC') && asset.exists
  ));
  const withdrawAssets = assets.filter((asset): asset is BalanceAssetView & { asset: WalletAsset } => (
    (asset.asset === 'CAL' || asset.asset === 'USDC' || asset.asset === 'DUNG')
    && asset.exists
    && isPositiveBaseUnits(asset.balanceBaseUnits)
  ));
  const canUseActions = plan.projectionStatus !== 'delayed';
  const canAddFunds = plan.canAddFunds && canUseActions && addFundsAssets.length > 0;
  const canReviewWithdraw = canUseActions && plan.canWithdrawToWallet && withdrawAssets.length > 0;
  const ready = mode === 'add_funds' ? canAddFunds : canReviewWithdraw;

  const actionAssets: Array<BalanceAssetView & { asset: WalletAsset }> = mode === 'add_funds' ? addFundsAssets : withdrawAssets;
  const activeAsset: WalletAsset = actionAssets.some((asset) => asset.asset === selectedAsset)
    ? selectedAsset
    : actionAssets[0]?.asset ?? 'CAL';
  const activeAssetView = actionAssets.find((asset) => asset.asset === activeAsset) ?? null;
  const decimals = DECIMALS[activeAsset];
  const baseUnits = decimalToBaseUnits(amount, decimals);
  const availableBaseUnits = mode === 'withdraw_to_wallet'
    ? activeAssetView?.balanceBaseUnits ?? null
    : activeAsset === 'CAL' ? walletCalBaseUnits : null;
  const exceedsAvailable = mode === 'withdraw_to_wallet'
    && Boolean(baseUnits)
    && Boolean(availableBaseUnits)
    && compareBaseUnits(baseUnits as string, availableBaseUnits as string) > 0;
  const amountInvalid = amount.trim().length > 0 && (!baseUnits || exceedsAvailable);
  const positive = isPositiveBaseUnits(baseUnits);
  const amountLabel = positive ? formatBaseUnits(baseUnits as string, decimals, 2) : null;

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape' && !submitting) onClose();
    };
    document.addEventListener('keydown', onKey);
    return () => document.removeEventListener('keydown', onKey);
  }, [onClose, submitting]);

  const commit = async () => {
    if (!actionOpen) return;
    if (!ready || !baseUnits || !positive || exceedsAvailable) {
      setActionError(mode === 'add_funds'
        ? (canAddFunds ? 'Enter a supported amount.' : 'Set up Balance before adding funds.')
        : (canReviewWithdraw ? 'Enter an available amount.' : 'Add funds before withdrawing.'));
      return;
    }
    const riderLabel = mode === 'add_funds' ? 'Add funds' : 'Withdraw to wallet';
    setSubmitting(true);
    setActionError(null);
    setActionResult({
      contractVersion: 'portfolio_balance_action.v2',
      actionType: mode,
      riderLabel,
      asset: activeAsset,
      amountBaseUnits: baseUnits,
      riderState: 'Pending',
      riderDetail: 'Preparing wallet confirmation.',
      nextStep: 'confirm_wallet',
      blockers: [],
    });
    try {
      const prepared = mode === 'add_funds'
        ? await api.prepareBalanceAddFunds({ asset: activeAsset as FundingAsset, amountBaseUnits: baseUnits })
        : await api.prepareBalanceWithdrawToWallet({ asset: activeAsset, amountBaseUnits: baseUnits });
      if (!prepared.preparedTransaction) {
        setActionResult(prepared);
        setActionError(prepared.riderDetail);
        return;
      }
      const signedTransaction = await signPreparedTransaction(
        prepared.preparedTransaction,
        mode === 'add_funds'
          ? { kind: 'balance_add_funds', asset: activeAsset as FundingAsset, amountBaseUnits: baseUnits }
          : { kind: 'balance_withdraw', asset: activeAsset, amountBaseUnits: baseUnits },
      );
      const submission = {
        amountBaseUnits: baseUnits,
        signedTransaction,
        lastValidBlockHeight: prepared.preparedTransaction.lastValidBlockHeight,
        clientRequestId: createClientRequestId(),
      };
      const result = mode === 'add_funds'
        ? await api.submitBalanceAddFunds({ asset: activeAsset as FundingAsset, ...submission })
        : await api.submitBalanceWithdrawToWallet({ asset: activeAsset, ...submission });
      setActionResult(result);
      setAmount('');
      await onActionComplete();
    } catch (err) {
      const message = err instanceof Error ? err.message : `Boulder Roller could not finish ${riderLabel}.`;
      setActionError(message);
      setActionResult({
        contractVersion: 'portfolio_balance_action.v2',
        actionType: mode,
        riderLabel,
        asset: activeAsset,
        amountBaseUnits: baseUnits,
        riderState: 'Needs review',
        riderDetail: message,
        nextStep: 'needs_review',
        blockers: [],
      });
    } finally {
      setSubmitting(false);
    }
  };

  const title = mode === 'add_funds' ? 'Add funds' : 'Withdraw';
  const verb = mode === 'add_funds' ? 'Add' : 'Withdraw';
  const capsuleLabel = submitting
    ? 'Pending'
    : amountLabel
      ? `Hold to ${verb} ${amountLabel} ${activeAsset}`
      : mode === 'add_funds' ? 'Hold to Add funds' : 'Hold to Withdraw';
  const available = (mode !== 'withdraw_to_wallet' || activeAssetView?.sourceStatus === 'live') && availableBaseUnits != null
    ? formatBaseUnits(availableBaseUnits, decimals, 2) : null;
  const note = actionError
    ?? (actionResult ? `${actionResult.riderState}. ${actionResult.riderDetail}` : null)
    ?? (!ready
      ? (mode === 'add_funds' ? 'Set up Balance before adding funds.' : 'Add funds to Balance before withdrawing.')
      : amountInvalid ? 'Use an available amount.' : null);

  return (
    <div
      className="portfolio-dialog"
      role="dialog"
      aria-modal="true"
      aria-labelledby={titleId}
      onMouseDown={(event) => {
        if (event.target === event.currentTarget && !submitting) onClose();
      }}
    >
      <div className="portfolio-dialog__sheet">
        <div className="portfolio-dialog__head">
          <h2 id={titleId}>{title}</h2>
          <button type="button" className="portfolio-dialog__close" onClick={onClose} disabled={submitting}>Cancel</button>
        </div>

        {!actionOpen ? <p role="status">Not open yet</p> : <>
        <div className="portfolio-sheet__entry">
          <label className="portfolio-sheet__amount">
            <input
              value={amount}
              onChange={(event) => {
                setAmount(event.target.value);
                setActionError(null);
              }}
              inputMode="decimal"
              placeholder="0"
              size={Math.max(1, amount.length)}
              aria-label={`${title} amount`}
              disabled={!ready || submitting}
              autoFocus
            />
            <span>{activeAsset}</span>
          </label>
          <div className="portfolio-sheet__available">
            <span>
              {mode === 'add_funds' ? 'Wallet ' : 'Balance '}
              <strong>{available ?? ''}</strong>
            </span>
            {mode === 'withdraw_to_wallet' && availableBaseUnits ? (
              <button
                type="button"
                className="portfolio-sheet__max"
                disabled={!ready || submitting}
                onClick={() => setAmount(baseUnitsToDecimalString(availableBaseUnits, decimals))}
              >
                Max
              </button>
            ) : null}
          </div>
          {actionAssets.length > 1 ? (
            <div className="portfolio-sheet__assets" role="group" aria-label="Asset">
              {actionAssets.map((asset) => (
                <button
                  key={asset.asset}
                  type="button"
                  className="portfolio-sheet__asset"
                  aria-pressed={asset.asset === activeAsset}
                  disabled={submitting}
                  onClick={() => {
                    setSelectedAsset(asset.asset);
                    setActionError(null);
                  }}
                >
                  {asset.asset}
                </button>
              ))}
            </div>
          ) : null}
        </div>

        <div className="portfolio-sheet__stack">
          <div>
            <span>From</span>
            {mode === 'add_funds'
              ? <strong>Wallet{walletLabel ? <i>{walletLabel}</i> : null}</strong>
              : <strong>Balance</strong>}
          </div>
          <div>
            <span>To</span>
            {mode === 'add_funds'
              ? <strong>Balance</strong>
              : <strong>Wallet{walletLabel ? <i>{walletLabel}</i> : null}</strong>}
          </div>
        </div>

        {note ? (
          <p className="portfolio-sheet__note" data-tone={actionError || amountInvalid ? 'warning' : 'state'}>{note}</p>
        ) : null}

        <div className="portfolio-sheet__commit">
          <HoldCapsule
            label={capsuleLabel}
            tone={mode === 'add_funds' ? 'in' : 'out'}
            disabled={!ready || !positive || exceedsAvailable}
            busy={submitting}
            onCommit={() => void commit()}
          />
        </div>
        </>}
      </div>
    </div>
  );
}
