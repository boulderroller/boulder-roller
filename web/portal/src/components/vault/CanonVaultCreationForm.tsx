import { useEffect, useMemo, useState } from 'react';
import {
  ArrowRight,
  CheckCircle2,
  CircleDollarSign,
  Clock3,
  Flag,
  RefreshCw,
  WalletCards,
} from 'lucide-react';
import type {
  CreateVaultResponse,
  VaultCreationPaymentMethod,
} from '../../lib/api';
import { formatTokenAmount } from '../../lib/formatters';
import { BeetleButton } from '../ui/beetle-button';
import type { CanonVaultCreationPhase } from './useCanonVaultCreation';

interface PaymentOption {
  label: string;
  method: VaultCreationPaymentMethod;
  value: string;
}

export const CANON_VAULT_PAYMENT_OPTIONS: Record<VaultCreationPaymentMethod, PaymentOption> = {
  dung: {
    method: 'dung',
    label: 'Use DUNG',
    value: `${formatTokenAmount(100)} DUNG`,
  },
  cal_usdc: {
    method: 'cal_usdc',
    label: 'Use CAL + USDC',
    value: `${formatTokenAmount(1_000)} CAL + ${formatTokenAmount(2)} USDC`,
  },
};

interface CanonVaultCreationFormProps {
  climbName: string;
  error: string | null;
  onBack: () => void;
  onConfirm: (paymentMethod: VaultCreationPaymentMethod) => Promise<void>;
  onOpenVault: (vaultId: number) => void;
  paymentMethods: VaultCreationPaymentMethod[];
  phase: CanonVaultCreationPhase;
  result: CreateVaultResponse | null;
}

const BUSY_PHASES: CanonVaultCreationPhase[] = [
  'preparing',
  'wallet_confirmation',
  'submitting',
];

export function CanonVaultCreationForm({
  climbName,
  error,
  onBack,
  onConfirm,
  onOpenVault,
  paymentMethods,
  phase,
  result,
}: CanonVaultCreationFormProps) {
  const options = useMemo(
    () => paymentMethods.map((method) => CANON_VAULT_PAYMENT_OPTIONS[method]),
    [paymentMethods],
  );
  const [paymentMethod, setPaymentMethod] = useState<VaultCreationPaymentMethod>(
    options[0]?.method ?? 'dung',
  );
  const isBusy = BUSY_PHASES.includes(phase);
  const isComplete = phase === 'success' || phase === 'pending';
  const selectedOption = CANON_VAULT_PAYMENT_OPTIONS[paymentMethod];

  useEffect(() => {
    if (!paymentMethods.includes(paymentMethod) && options[0]) {
      setPaymentMethod(options[0].method);
    }
  }, [options, paymentMethod, paymentMethods]);

  return (
    <div className="canon-vault-creation-form" data-creation-phase={phase}>
      <fieldset className="canon-vault-creation__payments" disabled={isBusy || isComplete}>
        <legend>Cost</legend>
        {options.map((option) => {
          const selected = option.method === paymentMethod;
          return (
            <button
              key={option.method}
              type="button"
              className="canon-vault-creation__payment"
              data-selected={selected ? 'true' : undefined}
              aria-pressed={selected}
              onClick={() => setPaymentMethod(option.method)}
            >
              <span className="canon-vault-creation__payment-choice">
                <span className="canon-vault-creation__radio" aria-hidden="true">
                  {selected ? <span /> : null}
                </span>
                <span>{option.label}</span>
              </span>
              <strong>{option.value}</strong>
            </button>
          );
        })}
      </fieldset>

      <div className="canon-vault-creation__summary" aria-label="Vault creation summary">
        <div>
          <Flag size={16} aria-hidden="true" />
          <span>Climb</span>
          <strong>{climbName}</strong>
        </div>
        <div>
          <CircleDollarSign size={16} aria-hidden="true" />
          <span>Selected cost</span>
          <strong>{selectedOption.value}</strong>
        </div>
        <div>
          <ArrowRight size={16} aria-hidden="true" />
          <span>What happens next</span>
          <strong>The Vault is attached to this climb.</strong>
        </div>
      </div>

      {phase === 'wallet_confirmation' ? (
        <div className="canon-vault-creation__status" data-tone="wallet" role="status">
          <WalletCards size={20} aria-hidden="true" />
          <div>
            <strong>Confirm in your wallet</strong>
            <span>Review the selected cost, then approve the prepared transaction.</span>
          </div>
        </div>
      ) : null}

      {phase === 'submitting' ? (
        <div className="canon-vault-creation__status" data-tone="pending" role="status">
          <Clock3 size={20} aria-hidden="true" />
          <div>
            <strong>Creating Vault</strong>
            <span>Your approved transaction is being attached to this climb.</span>
          </div>
        </div>
      ) : null}

      {phase === 'pending' ? (
        <div className="canon-vault-creation__status" data-tone="pending" role="status">
          <Clock3 size={20} aria-hidden="true" />
          <div>
            <strong>Creation submitted</strong>
            <span>{result?.message || 'The Vault is being attached to this climb. Do not retry.'}</span>
          </div>
        </div>
      ) : null}

      {phase === 'success' ? (
        <div className="canon-vault-creation__status" data-tone="success" role="status">
          <CheckCircle2 size={20} aria-hidden="true" />
          <div>
            <strong>Vault created</strong>
            <span>{result?.message || 'The Vault is ready to open.'}</span>
          </div>
        </div>
      ) : null}

      {error ? (
        <div className="portal-inline-alert canon-vault-creation__error" role="alert">
          <strong>Could not create Vault.</strong>
          <span>{error}</span>
        </div>
      ) : null}

      <div className="canon-vault-creation__actions">
        {phase === 'success' && result ? (
          <>
            <BeetleButton variant="secondary" onClick={onBack}>Back to climb</BeetleButton>
            <BeetleButton variant="primary" onClick={() => onOpenVault(result.vaultId)}>
              Open climb
            </BeetleButton>
          </>
        ) : phase === 'pending' ? (
          <BeetleButton variant="primary" onClick={onBack}>Back to climb</BeetleButton>
        ) : (
          <>
            <BeetleButton variant="secondary" onClick={onBack} disabled={isBusy}>
              Cancel
            </BeetleButton>
            <BeetleButton
              variant="primary"
              isLoading={isBusy}
              loadingLabel={
                phase === 'wallet_confirmation'
                  ? 'Waiting for wallet'
                  : phase === 'submitting'
                    ? 'Creating Vault'
                    : 'Preparing Vault'
              }
              disabled={options.length === 0}
              onClick={() => void onConfirm(paymentMethod)}
            >
              {phase === 'error' ? (
                <span className="canon-vault-creation__retry-label">
                  <RefreshCw size={14} aria-hidden="true" />
                  Try again
                </span>
              ) : 'Create Vault'}
            </BeetleButton>
          </>
        )}
      </div>
    </div>
  );
}
