import { ShieldAlert } from 'lucide-react';
import { useNavigate } from 'react-router-dom';
import { PortalPanel, PortalPanelBody } from '../portal/PortalSpine';
import {
  activateAccountDeletionCapability,
  useAccountDeletionCapability,
} from '../../lib/accountDeletionCapability';
import { useAuth } from '../../contexts/AuthContext';
import { notify } from '../../lib/notify';

export default function AccountDeletionTrackingBanner() {
  const navigate = useNavigate();
  const { walletAddress } = useAuth();
  const deletionCapability = useAccountDeletionCapability(walletAddress);

  const openDeletionStatus = () => {
    if (!walletAddress) {
      notify.error('Your wallet is not available');
      return;
    }
    try {
      activateAccountDeletionCapability(walletAddress);
      navigate('/account-deletion');
    } catch (error) {
      notify.error(
        error instanceof Error
          ? error.message
          : 'Saved account deletion status could not be opened.',
      );
    }
  };

  if (deletionCapability.kind === 'none' || deletionCapability.kind === 'unavailable') return null;

  return (
    <PortalPanel className="authenticated-app-inline-setup authenticated-app-deletion-status" role="status">
      <PortalPanelBody className="authenticated-app-inline-setup__body">
        <div className="authenticated-app-inline-setup__copy">
          <ShieldAlert size={18} aria-hidden="true" />
          <div>
            <strong>Account deletion request</strong>
            <span>
              {deletionCapability.kind === 'valid'
                ? 'A saved request has server status available.'
                : 'The saved request status is invalid.'}
            </span>
          </div>
        </div>
        <div className="authenticated-app-inline-setup__actions">
          <button
            type="button"
            className="portal-action-button"
            onClick={openDeletionStatus}
          >
            View status
          </button>
        </div>
      </PortalPanelBody>
    </PortalPanel>
  );
}
