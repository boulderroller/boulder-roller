import { BeetleButton } from '../ui/beetle-button';
import { formatInteger } from '../../lib/formatters';
import {
  ResponsiveModal,
  ResponsiveModalHeader,
  ResponsiveModalTitle,
  ResponsiveModalDescription,
  ResponsiveModalBody,
  ResponsiveModalFooter,
} from '../ui/responsive-modal';

interface StoreItem {
  id: string;
  emoji: string;
  name: string;
  description: string;
  price: number;
}

interface StoreConfirmModalProps {
  item: StoreItem;
  currentBalance: number;
  onClose: () => void;
  onConfirm: () => void;
}

export default function StoreConfirmModal({ item, currentBalance, onClose, onConfirm }: StoreConfirmModalProps) {
  const afterBalance = currentBalance - item.price;
  const hasEnoughFunds = afterBalance >= 0;

  return (
    <ResponsiveModal open={true} onOpenChange={(open) => { if (!open) onClose(); }}>
      <ResponsiveModalHeader className="store-confirm-modal-header">
        <ResponsiveModalTitle className="store-confirm-modal-title">
          Confirm Purchase
        </ResponsiveModalTitle>
        <ResponsiveModalDescription className="sr-only">
          Review the item cost and confirm whether to spend your balance.
        </ResponsiveModalDescription>
      </ResponsiveModalHeader>

      <ResponsiveModalBody className="store-confirm-modal-body">
        <div className="store-confirm-modal-preview">
          <div className="store-confirm-modal-preview__emoji" aria-hidden="true">
            {item.emoji}
          </div>
          <div className="store-confirm-modal-preview__name">
            {item.name}
          </div>
          <div className="store-confirm-modal-preview__description">
            {item.description}
          </div>
        </div>

        <div className="store-confirm-modal-price-panel">
          <div className="store-confirm-modal-price-summary">
            <div className="store-confirm-modal-label">
              Price
            </div>
            <div
              className={`store-confirm-modal-price-value ${hasEnoughFunds ? 'store-confirm-modal-price-value--ready' : ''}`}
            >
              {formatInteger(item.price)}
              <span className="store-confirm-modal-price-unit">
                DUNG
              </span>
            </div>
          </div>

          <div className="store-confirm-modal-balance-list">
            <div className="store-confirm-modal-balance-row">
              <span className="store-confirm-modal-label">
                Your Balance
              </span>
              <span className="store-confirm-modal-balance-value">
                {formatInteger(currentBalance)}
              </span>
            </div>

            <div className="store-confirm-modal-balance-row">
              <span className="store-confirm-modal-label">
                After Purchase
              </span>
              <span
                className={`store-confirm-modal-balance-value store-confirm-modal-balance-value--after ${hasEnoughFunds ? '' : 'store-confirm-modal-balance-value--danger'}`}
              >
                {formatInteger(afterBalance)}
                {!hasEnoughFunds && <span className="store-confirm-modal-warning-icon" aria-hidden="true">&#9888;&#65039;</span>}
              </span>
            </div>
          </div>
        </div>

        {!hasEnoughFunds && (
          <div className="store-confirm-modal-insufficient">
            <p className="store-confirm-modal-insufficient__copy">
              Insufficient DUNG. Ride more to earn!
            </p>
          </div>
        )}
      </ResponsiveModalBody>

      <ResponsiveModalFooter className="store-confirm-modal-footer">
        <BeetleButton
          variant="secondary"
          onClick={onClose}
          className="store-confirm-modal-action"
        >
          Cancel
        </BeetleButton>
        <BeetleButton
          onClick={onConfirm}
          disabled={!hasEnoughFunds}
          className="store-confirm-modal-action"
        >
          {hasEnoughFunds ? 'Confirm' : 'Can\'t Afford'}
        </BeetleButton>
      </ResponsiveModalFooter>
    </ResponsiveModal>
  );
}
