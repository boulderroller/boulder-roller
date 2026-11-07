import { BeetleButton } from '../ui/beetle-button';
import {
  ResponsiveModal,
  ResponsiveModalHeader,
  ResponsiveModalTitle,
  ResponsiveModalDescription,
  ResponsiveModalBody,
  ResponsiveModalFooter,
} from '../ui/responsive-modal';
import { formatTokenAmount } from '../../lib/formatters';

interface Activity {
  id: string;
  title: string;
  date: string;
  distance: string;
  rewardValue: number;
  rewardAsset: 'CAL' | 'DUNG';
}

interface DeleteConfirmModalProps {
  activity: Activity;
  onClose: () => void;
  onConfirm: () => void;
}

export default function DeleteConfirmModal({ activity, onClose, onConfirm }: DeleteConfirmModalProps) {
  return (
    <ResponsiveModal open={true} onOpenChange={(open) => { if (!open) onClose(); }}>
      <ResponsiveModalHeader className="delete-confirm-modal-header">
        <div className="delete-confirm-modal-icon" aria-hidden="true">&#9888;&#65039;</div>
        <ResponsiveModalTitle className="delete-confirm-modal-title">
          Delete ride?
        </ResponsiveModalTitle>
        <ResponsiveModalDescription className="sr-only">
          Confirm permanent deletion for this ride.
        </ResponsiveModalDescription>
      </ResponsiveModalHeader>

      <ResponsiveModalBody className="delete-confirm-modal-body">
        <div className="delete-confirm-modal-preview">
          <div className="delete-confirm-modal-preview__title">
            {activity.title}
          </div>
          <div className="delete-confirm-modal-preview__meta">
            {activity.date} &bull; {activity.distance}
          </div>
          <div className="delete-confirm-modal-preview__reward">
            {formatTokenAmount(activity.rewardValue)} {activity.rewardAsset} counted
          </div>
        </div>

        <div className="delete-confirm-modal-warning">
          <p className="delete-confirm-modal-warning__copy">
            This action cannot be undone.
          </p>
          <p className="delete-confirm-modal-warning__loss">
            This removes {formatTokenAmount(activity.rewardValue)} counted {activity.rewardAsset}.
          </p>
        </div>
      </ResponsiveModalBody>

      <ResponsiveModalFooter className="delete-confirm-modal-footer">
        <BeetleButton
          variant="secondary"
          onClick={onClose}
          className="delete-confirm-modal-action"
        >
          Cancel
        </BeetleButton>
        <BeetleButton
          variant="secondary"
          onClick={onConfirm}
          className="delete-confirm-modal-action delete-confirm-modal-delete"
        >
          Delete
        </BeetleButton>
      </ResponsiveModalFooter>
    </ResponsiveModal>
  );
}
