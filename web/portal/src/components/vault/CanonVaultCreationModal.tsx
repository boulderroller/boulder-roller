import type {
  CreateVaultResponse,
  VaultCreationPaymentMethod,
} from '../../lib/api';
import {
  ResponsiveModal,
  ResponsiveModalBody,
  ResponsiveModalDescription,
  ResponsiveModalHeader,
  ResponsiveModalTitle,
} from '../ui/responsive-modal';
import { CanonVaultCreationForm } from './CanonVaultCreationForm';
import type { CanonVaultCreationPhase } from './useCanonVaultCreation';

interface CanonVaultCreationModalProps {
  climbName: string;
  error: string | null;
  onClose: () => void;
  onConfirm: (paymentMethod: VaultCreationPaymentMethod) => Promise<void>;
  onOpenVault: (vaultId: number) => void;
  paymentMethods: VaultCreationPaymentMethod[];
  phase: CanonVaultCreationPhase;
  result: CreateVaultResponse | null;
}

export function CanonVaultCreationModal({
  climbName,
  error,
  onClose,
  onConfirm,
  onOpenVault,
  paymentMethods,
  phase,
  result,
}: CanonVaultCreationModalProps) {
  const isBusy = phase === 'preparing'
    || phase === 'wallet_confirmation'
    || phase === 'submitting';

  return (
    <ResponsiveModal
      open={true}
      onOpenChange={(open) => {
        if (!open && !isBusy) onClose();
      }}
    >
      <ResponsiveModalHeader className="canon-vault-creation__header">
        <ResponsiveModalTitle>Create Vault</ResponsiveModalTitle>
        <ResponsiveModalDescription>
          Choose a cost for the Vault attached to {climbName}.
        </ResponsiveModalDescription>
      </ResponsiveModalHeader>

      <ResponsiveModalBody className="canon-vault-creation__body">
        <CanonVaultCreationForm
          climbName={climbName}
          error={error}
          onBack={onClose}
          onConfirm={onConfirm}
          onOpenVault={onOpenVault}
          paymentMethods={paymentMethods}
          phase={phase}
          result={result}
        />
      </ResponsiveModalBody>
    </ResponsiveModal>
  );
}
