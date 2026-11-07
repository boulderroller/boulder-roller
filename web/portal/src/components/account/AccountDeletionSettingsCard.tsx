import { useCallback, useEffect, useRef, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  ApiError,
  api,
  type AccountDeletionPreflight,
  type AccountDeletionStatus,
} from '../../lib/api';
import {
  activateAccountDeletionCapability,
  assertAccountDeletionStorageAvailable,
  clearUnconfirmedAccountDeletionCapability,
  createAccountDeletionCapability,
  getAccountDeletionCapabilitySnapshot,
  getUnconfirmedAccountDeletionCapability,
  persistAccountDeletionCapability,
  persistUnconfirmedAccountDeletionCapability,
  type AccountDeletionCapability,
  useAccountDeletionCapability,
  withAccountDeletionCapabilityLock,
} from '../../lib/accountDeletionCapability';
import {
  accountDeletionBlockerLabel,
  accountDeletionNeedsBalance,
  accountDeletionNeedsSupport,
} from '../../lib/accountDeletionPresentation';
import { useAuth } from '../../contexts/AuthContext';
import { notify } from '../../lib/notify';
import { PortalTruthPill } from '../portal/PortalSpine';
import {
  ResponsiveModal,
  ResponsiveModalBody,
  ResponsiveModalDescription,
  ResponsiveModalFooter,
  ResponsiveModalHeader,
  ResponsiveModalTitle,
} from '../ui/responsive-modal';

export default function AccountDeletionSettingsCard() {
  const navigate = useNavigate();
  const { walletAddress } = useAuth();
  const deletionCapability = useAccountDeletionCapability(walletAddress);
  const [showDeleteModal, setShowDeleteModal] = useState(false);
  const [isDeleting, setIsDeleting] = useState(false);
  const [deleteConfirmText, setDeleteConfirmText] = useState('');
  const [unuploadedRidesReviewed, setUnuploadedRidesReviewed] = useState(false);
  const [deletionPreflight, setDeletionPreflight] = useState<AccountDeletionPreflight | null>(null);
  const [deletionPreflightState, setDeletionPreflightState] = useState<'idle' | 'checking' | 'ready' | 'error'>('idle');
  const [deletionRequestError, setDeletionRequestError] = useState<string | null>(null);
  const [deletionRequestNeedsSupport, setDeletionRequestNeedsSupport] = useState(false);
  const [pendingCapability, setPendingCapability] = useState<AccountDeletionCapability | null>(null);
  const [invalidRecovery, setInvalidRecovery] = useState(false);
  const deletionPreflightRequestRef = useRef(0);

  useEffect(() => {
    if (!walletAddress) {
      setPendingCapability(null);
      setInvalidRecovery(false);
      return;
    }
    try {
      setPendingCapability(getUnconfirmedAccountDeletionCapability(walletAddress));
      setInvalidRecovery(false);
    } catch {
      // Keep malformed recovery data visible and removable. It must never be
      // replaced by a newly generated request capability.
      setPendingCapability(null);
      setInvalidRecovery(true);
    }
  }, [walletAddress]);

  const loadDeletionPreflight = useCallback(async () => {
    const requestNumber = ++deletionPreflightRequestRef.current;
    setDeletionPreflight(null);
    setDeletionPreflightState('checking');
    setDeletionRequestError(null);
    setDeletionRequestNeedsSupport(false);
    try {
      const preflight = await api.getAccountDeletionPreflight();
      if (deletionPreflightRequestRef.current !== requestNumber) return;
      setDeletionPreflight(preflight);
      setDeletionPreflightState('ready');
    } catch {
      if (deletionPreflightRequestRef.current !== requestNumber) return;
      setDeletionPreflightState('error');
    }
  }, []);

  const openDeleteAccount = useCallback(() => {
    setDeleteConfirmText('');
    setUnuploadedRidesReviewed(false);
    setDeletionRequestError(null);
    setDeletionRequestNeedsSupport(false);
    if (walletAddress) {
      try {
        setPendingCapability(getUnconfirmedAccountDeletionCapability(walletAddress));
        setInvalidRecovery(false);
      } catch (error) {
        setPendingCapability(null);
        setInvalidRecovery(true);
        setDeletionRequestError(
          error instanceof Error
            ? error.message
            : 'The saved account deletion recovery request could not be read.',
        );
      }
    } else {
      setPendingCapability(null);
      setInvalidRecovery(false);
    }
    setShowDeleteModal(true);
    void loadDeletionPreflight();
  }, [loadDeletionPreflight, walletAddress]);

  const closeDeleteAccount = useCallback(() => {
    deletionPreflightRequestRef.current += 1;
    setShowDeleteModal(false);
    setDeleteConfirmText('');
    setUnuploadedRidesReviewed(false);
    setDeletionPreflight(null);
    setDeletionPreflightState('idle');
    setDeletionRequestError(null);
    setDeletionRequestNeedsSupport(false);
    setPendingCapability(null);
  }, []);

  const removeSavedRecovery = useCallback(() => {
    if (!walletAddress) {
      setDeletionRequestError('Your wallet is not available.');
      return;
    }
    if (pendingCapability && pendingCapability.wallet !== walletAddress) {
      setDeletionRequestError('The saved recovery request belongs to another wallet.');
      return;
    }
    try {
      clearUnconfirmedAccountDeletionCapability(walletAddress);
      setInvalidRecovery(false);
      closeDeleteAccount();
    } catch (error) {
      setDeletionRequestError(
        error instanceof Error
          ? error.message
          : 'The saved account deletion recovery request could not be removed.',
      );
    }
  }, [closeDeleteAccount, pendingCapability, walletAddress]);

  const openDeletionStatus = useCallback(() => {
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
  }, [navigate, walletAddress]);

  const handleDeleteAccount = useCallback(async () => {
    if (deleteConfirmText !== 'DELETE') {
      notify.error('Type DELETE to confirm');
      return;
    }
    if (!unuploadedRidesReviewed) {
      notify.error('Review unuploaded rides first');
      return;
    }
    if (!deletionPreflight?.available) {
      notify.error('The account check must be available first');
      return;
    }
    if (!walletAddress) {
      notify.error('Your wallet is not available');
      return;
    }
    if (invalidRecovery) {
      setDeletionRequestError('Remove the invalid saved recovery before filing another request.');
      return;
    }

    setIsDeleting(true);
    setDeletionRequestError(null);
    setDeletionRequestNeedsSupport(false);
    let existingCapabilityFound = false;
    try {
      await withAccountDeletionCapabilityLock(walletAddress, async () => {
        const latestCapability = getAccountDeletionCapabilitySnapshot(walletAddress);
        if (latestCapability.kind === 'valid') {
          existingCapabilityFound = true;
          throw new Error('An account deletion request is already saved.');
        }
        if (latestCapability.kind === 'unavailable') {
          throw new Error('This browser cannot save account deletion status.');
        }
        if (latestCapability.kind === 'invalid') {
          throw new Error('Remove the invalid saved request status before filing another request.');
        }

        assertAccountDeletionStorageAvailable(walletAddress);
        if (pendingCapability && pendingCapability.wallet !== walletAddress) {
          throw new Error('The saved recovery request belongs to another wallet.');
        }
        const capability = pendingCapability ?? createAccountDeletionCapability(walletAddress);
        // This envelope is deliberately not an accepted capability and does
        // not activate the global status route. It only makes an ambiguous
        // committing response recoverable across reloads and tab crashes.
        persistUnconfirmedAccountDeletionCapability(capability);
        setPendingCapability(capability);
        let requestStatus: AccountDeletionStatus;
        try {
          requestStatus = await api.requestAccountDeletion({
            ...capability,
            unuploadedRidesAcknowledged: true,
          });
        } catch (error) {
          const conflictCode = error instanceof ApiError && error.statusCode === 409
            ? error.detail?.code
            : null;
          if (
            conflictCode === 'request_already_active'
            || conflictCode === 'account_unavailable'
            || conflictCode === 'request_id_conflict'
          ) {
            clearUnconfirmedAccountDeletionCapability(capability.wallet);
            setPendingCapability(null);
            setInvalidRecovery(false);
            setDeletionRequestNeedsSupport(true);
            setDeletionRequestError(
              conflictCode === 'request_already_active'
                ? 'An account deletion request is already active.'
                : conflictCode === 'account_unavailable'
                  ? 'This account cannot file a new deletion request.'
                  : 'The deletion request identifier conflicts with an existing request.',
            );
            return;
          }
          try {
            requestStatus = await api.getAccountDeletionStatus(capability);
          } catch {
            setPendingCapability(capability);
            setDeletionRequestError('The request was not confirmed. You can reload or try again with the same saved request.');
            return;
          }
        }
        if (requestStatus.requestId !== capability.requestId) {
          throw new Error('Deletion status did not match the saved request.');
        }
        try {
          persistAccountDeletionCapability(capability);
        } catch {
          setPendingCapability(capability);
          setDeletionRequestError('The request was accepted, but this browser could not save its status. Try again.');
          return;
        }
        clearUnconfirmedAccountDeletionCapability(capability.wallet);
        setPendingCapability(null);
        setInvalidRecovery(false);
        openDeletionStatus();
      });
    } catch (error) {
      if (existingCapabilityFound) {
        openDeletionStatus();
      } else {
        setDeletionRequestError(
          error instanceof Error
            ? error.message
            : 'Account deletion could not be requested.',
        );
      }
    } finally {
      setIsDeleting(false);
    }
  }, [
    deleteConfirmText,
    deletionPreflight,
    invalidRecovery,
    openDeletionStatus,
    pendingCapability,
    unuploadedRidesReviewed,
    walletAddress,
  ]);

  return (
    <>
      <div className="settings-v2-section-break settings-v2-section-break--danger">
        <h4 className="settings-v2-danger-heading">Account deletion</h4>
        <div className="settings-v2-danger-panel">
          <div className="settings-v2-danger-panel__content">
            <h5 className="settings-v2-danger-panel__title">Delete account</h5>
            <p className="settings-v2-danger-panel__copy">
              {deletionCapability.kind === 'valid'
                ? 'A saved deletion request has server status available.'
                : deletionCapability.kind === 'invalid'
                  ? 'The saved request status is invalid.'
                  : deletionCapability.kind === 'unavailable'
                  ? 'Browser storage is unavailable. No deletion request can be read or safely filed.'
                    : pendingCapability
                      ? 'An unconfirmed deletion request is saved for recovery.'
                      : invalidRecovery
                        ? 'The saved account deletion recovery request is invalid.'
                        : 'An account check is required.'}
            </p>
          </div>
          <button
            type="button"
            className="settings-v2-panel-danger-button"
            disabled={deletionCapability.kind === 'unavailable'}
            onClick={() => {
              if (deletionCapability.kind === 'valid' || deletionCapability.kind === 'invalid') {
                openDeletionStatus();
              } else if (deletionCapability.kind === 'none') {
                openDeleteAccount();
              }
            }}
          >
            {deletionCapability.kind === 'valid' || deletionCapability.kind === 'invalid'
              ? 'View deletion status'
              : deletionCapability.kind === 'unavailable'
                ? 'Browser storage unavailable'
                : pendingCapability
                  ? 'Continue deletion request'
                  : invalidRecovery
                    ? 'Review saved recovery'
                    : 'Delete account'}
          </button>
        </div>
      </div>

      <ResponsiveModal
        open={showDeleteModal}
        onOpenChange={(open) => {
          if (!open && !isDeleting && !pendingCapability) closeDeleteAccount();
        }}
      >
        <ResponsiveModalHeader className="settings-v2-account-deletion-modal__header">
          <ResponsiveModalTitle>Delete account</ResponsiveModalTitle>
          <ResponsiveModalDescription>
            Your identity and personal data will be removed. Your climb times, leaderboard history, and settled economics will remain linked to an anonymous account.
          </ResponsiveModalDescription>
        </ResponsiveModalHeader>

        <ResponsiveModalBody className="settings-v2-account-deletion-modal__body">
          {deletionPreflightState === 'checking' ? (
            <div className="settings-v2-account-deletion-modal__loading" role="status">
              Checking account requirements
            </div>
          ) : null}

          {deletionPreflightState === 'error' || (deletionPreflightState === 'ready' && !deletionPreflight?.available) ? (
            <div className="settings-v2-account-deletion-modal__state" role="alert">
              <h4>Account check unavailable</h4>
              <button type="button" className="portal-sort-button" onClick={() => void loadDeletionPreflight()}>
                Check again
              </button>
            </div>
          ) : null}

          {deletionPreflightState === 'ready' && deletionPreflight?.available && !deletionPreflight.allowed ? (
            <div className="settings-v2-account-deletion-modal__state" role="status">
              <h4>Account deletion blocked</h4>
              <ul aria-label="Account deletion requirements">
                {deletionPreflight.blockers.map((blocker, index) => (
                  <li key={`${blocker.code}-${index}`}>{accountDeletionBlockerLabel(blocker)}</li>
                ))}
              </ul>
              {accountDeletionNeedsBalance(deletionPreflight.blockers) ? (
                <button
                  type="button"
                  className="portal-sort-button"
                  onClick={() => {
                    closeDeleteAccount();
                    navigate('/profile?tab=portfolio');
                  }}
                >
                  Open Portfolio
                </button>
              ) : null}
              {accountDeletionNeedsSupport(deletionPreflight.blockers) ? (
                <a
                  className="portal-sort-button"
                  href="https://docs.boulderroller.xyz/support/contact"
                >
                  Contact support
                </a>
              ) : null}
            </div>
          ) : null}

          {deletionPreflightState === 'ready' && deletionPreflight?.available ? (
            <div className="settings-v2-account-deletion-modal__confirmation">
              <PortalTruthPill tone={deletionPreflight.allowed ? 'verified' : 'warning'}>
                {deletionPreflight.allowed ? 'Account check passed' : 'Ready to file'}
              </PortalTruthPill>
              {!deletionPreflight.allowed ? (
                <p>The request can still be filed. Its current requirements will remain visible in status.</p>
              ) : null}
              <label className="settings-v2-account-deletion-modal__checkbox">
                <input
                  type="checkbox"
                  checked={unuploadedRidesReviewed}
                  onChange={(event) => setUnuploadedRidesReviewed(event.target.checked)}
                />
                <span>Unuploaded rides reviewed</span>
              </label>
              <div className="settings-v2-confirm-modal__field">
                <label htmlFor="settings-delete-account-confirm" className="settings-v2-confirm-modal__label">
                  Type DELETE to confirm
                </label>
                <input
                  id="settings-delete-account-confirm"
                  type="text"
                  value={deleteConfirmText}
                  onChange={(event) => setDeleteConfirmText(event.target.value.toUpperCase())}
                  className="settings-v2-confirm-modal__input"
                  placeholder="DELETE"
                  autoComplete="off"
                />
              </div>
            </div>
          ) : null}

          {deletionRequestError ? (
            <p className="settings-v2-account-deletion-modal__error" role="alert">{deletionRequestError}</p>
          ) : null}
          {deletionRequestNeedsSupport ? (
            <a className="portal-sort-button" href="https://docs.boulderroller.xyz/support/contact">
              Contact support
            </a>
          ) : null}
          {pendingCapability || invalidRecovery ? (
            <div className="account-deletion-status-screen__discard">
              {invalidRecovery ? (
                <p>The saved account deletion recovery request is invalid.</p>
              ) : null}
              <p>Removing this saved recovery does not cancel a server request.</p>
              <button
                type="button"
                className="portal-sort-button"
                onClick={removeSavedRecovery}
                disabled={isDeleting}
              >
                Remove saved recovery request
              </button>
            </div>
          ) : null}
        </ResponsiveModalBody>

        <ResponsiveModalFooter className="settings-v2-account-deletion-modal__footer">
          <button
            type="button"
            className="portal-sort-button settings-v2-modal-action"
            onClick={closeDeleteAccount}
            disabled={isDeleting || Boolean(pendingCapability)}
          >
            Cancel
          </button>
          {deletionPreflightState === 'ready' && deletionPreflight?.available ? (
            <button
              type="button"
              className="settings-v2-danger-button settings-v2-modal-action"
              onClick={handleDeleteAccount}
              disabled={
                deleteConfirmText !== 'DELETE'
                || !unuploadedRidesReviewed
                || isDeleting
                || deletionRequestNeedsSupport
                || invalidRecovery
              }
            >
              {isDeleting
                ? 'Requesting'
                : pendingCapability
                  ? 'Try request again'
                  : 'Request account deletion'}
            </button>
          ) : null}
        </ResponsiveModalFooter>
      </ResponsiveModal>
    </>
  );
}
