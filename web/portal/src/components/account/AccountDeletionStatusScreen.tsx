import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { CheckCircle2, Clock3, RefreshCw, ShieldAlert } from 'lucide-react';
import {
  ApiError,
  api,
  type AccountDeletionStatus,
  type AccountDeletionStatusName,
} from '../../lib/api';
import type { AccountDeletionCapability } from '../../lib/accountDeletionCapability';
import {
  accountDeletionBlockerLabel,
  accountDeletionFailureLabel,
  accountDeletionNeedsBalance,
  accountDeletionNeedsSupport,
} from '../../lib/accountDeletionPresentation';
import { formatDateTime, formatInteger } from '../../lib/formatters';
import { BeetleButton } from '../ui/beetle-button';
import { AuthNotice, AuthPanel, AuthTitleBand } from '../auth/AuthSurface';
import { PortalTruthPill } from '../portal/PortalSpine';

const SUPPORT_URL = 'https://docs.boulderroller.xyz/support/contact';
const ACTIVE_STATUSES = new Set<AccountDeletionStatusName>(['queued', 'processing']);
const POLL_BASE_DELAY_MS = 5000;
const POLL_MAX_DELAY_MS = 20_000;

function verifiedStatus(status: AccountDeletionStatus): AccountDeletionStatus {
  if (status.status === 'completed' && !status.completedAt) {
    return {
      ...status,
      status: 'legacy_unverified',
      completedAt: null,
      retryable: false,
    };
  }
  return status;
}

function viewForStatus(status: AccountDeletionStatus | null) {
  if (!status) {
    return {
      title: 'Checking account deletion',
      description: 'Checking the server for the current request state.',
      tone: 'muted' as const,
      label: 'Checking',
      icon: <Clock3 className="session-recovery-screen__title-icon" />,
    };
  }
  switch (status.status) {
    case 'queued':
    case 'processing':
      return {
        title: 'Account deletion in progress',
        description: 'The request is saved. Checking the server for its current state.',
        tone: 'warning' as const,
        label: status.status === 'queued' ? 'Queued' : 'Processing',
        icon: <Clock3 className="session-recovery-screen__title-icon" />,
      };
    case 'blocked':
      if (!status.retryable) {
        return {
          title: 'Account deletion needs support',
          description: 'The server cannot retry this blocked request automatically.',
          tone: 'warning' as const,
          label: 'Support review',
          icon: <ShieldAlert className="session-recovery-screen__title-icon" />,
        };
      }
      return {
        title: 'Account deletion blocked',
        description: 'The account check found actions that must be resolved.',
        tone: 'warning' as const,
        label: 'Blocked',
        icon: <ShieldAlert className="session-recovery-screen__title-icon" />,
      };
    case 'failed_retryable':
      if (!status.retryable) {
        return {
          title: 'Account deletion recovering',
          description: 'The request remains saved. The server will continue the authorized deletion work.',
          tone: 'warning' as const,
          label: 'Recovery queued',
          icon: <Clock3 className="session-recovery-screen__title-icon" />,
        };
      }
      return {
        title: 'Account deletion needs retry',
        description: 'The last attempt failed. The request remains saved.',
        tone: 'warning' as const,
        label: 'Retry available',
        icon: <RefreshCw className="session-recovery-screen__title-icon" />,
      };
    case 'needs_support':
      return {
        title: 'Account deletion needs support',
        description: 'The server routed this request to support review.',
        tone: 'warning' as const,
        label: 'Support review',
        icon: <ShieldAlert className="session-recovery-screen__title-icon" />,
      };
    case 'completed':
      return {
        title: 'Account deletion complete',
        description: `The server confirmed completion ${formatDateTime(status.completedAt)}.`,
        tone: 'verified' as const,
        label: 'Completed',
        icon: <CheckCircle2 className="session-recovery-screen__title-icon" />,
      };
    case 'legacy_unverified':
    default:
      return {
        title: 'Account deletion needs support',
        description: 'The server cannot verify completion for this request.',
        tone: 'warning' as const,
        label: 'Unverified',
        icon: <ShieldAlert className="session-recovery-screen__title-icon" />,
      };
  }
}

interface AccountDeletionStatusScreenProps {
  capability: AccountDeletionCapability;
  onFinish: () => void;
  onDiscard: () => void;
  onOpenPortfolio: () => void;
}

export default function AccountDeletionStatusScreen({
  capability,
  onFinish,
  onDiscard,
  onOpenPortfolio,
}: AccountDeletionStatusScreenProps) {
  const [status, setStatus] = useState<AccountDeletionStatus | null>(null);
  const [statusError, setStatusError] = useState<string | null>(null);
  const [statusNotFound, setStatusNotFound] = useState(false);
  const [retryNeedsSupport, setRetryNeedsSupport] = useState(false);
  const [isChecking, setIsChecking] = useState(false);
  const [isRetrying, setIsRetrying] = useState(false);
  const [pollFailureCount, setPollFailureCount] = useState(0);
  const [isPageVisible, setIsPageVisible] = useState(() => (
    typeof document === 'undefined' || document.visibilityState !== 'hidden'
  ));
  const timerRef = useRef<number | null>(null);

  const checkStatus = useCallback(async () => {
    setIsChecking(true);
    setStatusError(null);
    setStatusNotFound(false);
    try {
      const nextStatus = verifiedStatus(await api.getAccountDeletionStatus(capability));
      if (nextStatus.requestId !== capability.requestId) {
        throw new Error('Deletion status did not match the saved request.');
      }
      setStatus(nextStatus);
      setRetryNeedsSupport((needsSupport) => (
        needsSupport
        && (nextStatus.status === 'failed_retryable' || nextStatus.status === 'blocked')
      ));
      setPollFailureCount(0);
    } catch (error) {
      if (error instanceof ApiError && error.statusCode === 404) {
        setStatus(null);
        setStatusNotFound(true);
        setStatusError('The server has no request for the saved request status.');
        setPollFailureCount(0);
      } else {
        setStatusError('Account deletion status could not be checked.');
        setPollFailureCount((count) => Math.min(count + 1, 4));
      }
    } finally {
      setIsChecking(false);
    }
  }, [capability]);

  useEffect(() => {
    void checkStatus();
  }, [checkStatus]);

  useEffect(() => {
    const handleVisibilityChange = () => setIsPageVisible(document.visibilityState !== 'hidden');
    document.addEventListener('visibilitychange', handleVisibilityChange);
    return () => document.removeEventListener('visibilitychange', handleVisibilityChange);
  }, []);

  useEffect(() => {
    const shouldPoll = status
      ? ACTIVE_STATUSES.has(status.status)
        || (status.status === 'failed_retryable' && !status.retryable)
      : Boolean(statusError && !statusNotFound);
    if (!isPageVisible || isChecking || !shouldPoll) return;
    const pollDelay = Math.min(
      POLL_BASE_DELAY_MS * (2 ** pollFailureCount),
      POLL_MAX_DELAY_MS,
    );
    timerRef.current = window.setTimeout(() => void checkStatus(), pollDelay);
    return () => {
      if (timerRef.current !== null) window.clearTimeout(timerRef.current);
    };
  }, [checkStatus, isChecking, isPageVisible, pollFailureCount, status, statusError, statusNotFound]);

  const handleRetry = useCallback(async () => {
    setIsRetrying(true);
    setStatusError(null);
    try {
      const nextStatus = verifiedStatus(await api.retryAccountDeletion(capability));
      if (nextStatus.requestId !== capability.requestId) {
        throw new Error('Deletion status did not match the saved request.');
      }
      setStatus(nextStatus);
      setRetryNeedsSupport(false);
      setPollFailureCount(0);
    } catch (error) {
      if (
        error instanceof ApiError
        && error.statusCode === 409
        && error.detail?.code === 'retry_requires_support'
      ) {
        setStatusError('This request needs support before it can be retried.');
        setRetryNeedsSupport(true);
      } else {
        setStatusError('Account deletion could not be retried.');
      }
    } finally {
      setIsRetrying(false);
    }
  }, [capability]);

  const view = useMemo(() => (
    retryNeedsSupport
      ? {
          title: 'Account deletion needs support',
          description: 'The server requires support review before this request can be retried.',
          tone: 'warning' as const,
          label: 'Support review',
          icon: <ShieldAlert className="session-recovery-screen__title-icon" />,
        }
      : viewForStatus(status)
  ), [retryNeedsSupport, status]);

  return (
    <section className="session-recovery-screen account-deletion-status-screen" aria-labelledby="account-deletion-status-title">
      <div className="session-recovery-screen__glow" aria-hidden="true" />
      <div className="session-recovery-screen__frame account-deletion-status-screen__frame">
        <AuthPanel
          role="status"
          titleId="account-deletion-status-title"
          descriptionId="account-deletion-status-description"
          bodyClassName="session-recovery-screen__body account-deletion-status-screen__body"
          header={<AuthTitleBand titleId="account-deletion-status-title" title={view.title} icon={view.icon} />}
        >
          <div className="account-deletion-status-screen__state-line">
            <PortalTruthPill tone={view.tone}>{view.label}</PortalTruthPill>
            {status ? <span>Attempt {formatInteger(status.attemptCount)}</span> : null}
          </div>
          <p id="account-deletion-status-description" className="session-recovery-screen__primary-copy">
            {view.description}
          </p>

          {status?.blockers.length ? (
            <ul className="account-deletion-status-screen__blockers" aria-label="Account deletion requirements">
              {status.blockers.map((blocker, index) => (
                <li key={`${blocker.code}-${index}`}>{accountDeletionBlockerLabel(blocker)}</li>
              ))}
            </ul>
          ) : null}

          {status?.failureCode ? (
            <p className="account-deletion-status-screen__failure-code">
              {accountDeletionFailureLabel(status.failureCode)}
            </p>
          ) : null}

          {statusError ? (
            <AuthNotice tone="error" className="session-recovery-screen__notice">
              {statusError} The saved request remains on this device.
            </AuthNotice>
          ) : null}

          <div className="session-recovery-screen__actions account-deletion-status-screen__actions">
            {status?.status === 'completed' && status.completedAt ? (
              <BeetleButton onClick={onFinish} className="session-recovery-screen__button--full">
                Finish
              </BeetleButton>
            ) : null}
            {status?.status === 'failed_retryable' && status.retryable && !retryNeedsSupport ? (
              <BeetleButton
                onClick={handleRetry}
                isLoading={isRetrying}
                loadingLabel="Retrying"
                className="session-recovery-screen__button--full"
              >
                Retry deletion
              </BeetleButton>
            ) : null}
            {status?.status === 'blocked' ? (
              <>
                {accountDeletionNeedsBalance(status.blockers) ? (
                  <BeetleButton onClick={onOpenPortfolio} className="session-recovery-screen__button--full">
                    Open Portfolio
                  </BeetleButton>
                ) : null}
                {status.retryable && !retryNeedsSupport ? (
                  <BeetleButton
                    variant="secondary"
                    onClick={handleRetry}
                    isLoading={isRetrying}
                    loadingLabel="Retrying"
                    className="session-recovery-screen__button--full"
                  >
                    Retry deletion
                  </BeetleButton>
                ) : null}
              </>
            ) : null}
            {statusError
              || status?.status === 'needs_support'
              || retryNeedsSupport
              || (status?.status === 'blocked' && !status.retryable) ? (
              <BeetleButton
                variant="secondary"
                onClick={() => void checkStatus()}
                isLoading={isChecking}
                loadingLabel="Checking"
                className="session-recovery-screen__button--full"
              >
                Refresh status
              </BeetleButton>
            ) : null}
            {status?.status === 'needs_support'
              || status?.status === 'legacy_unverified'
              || statusNotFound
              || retryNeedsSupport
              || Boolean(status && accountDeletionNeedsSupport(status.blockers))
              || (status?.status === 'blocked' && !status.retryable) ? (
              <a className="beetle-button account-deletion-status-screen__support" href={SUPPORT_URL}>
                Contact support
              </a>
            ) : null}
          </div>

          <div className="account-deletion-status-screen__discard">
            <p>Removing the saved status from this device does not cancel the server request.</p>
            <BeetleButton variant="secondary" onClick={onDiscard}>
              Remove saved status from this device
            </BeetleButton>
          </div>
        </AuthPanel>
      </div>
    </section>
  );
}

interface AccountDeletionRecoveryScreenProps {
  checking: boolean;
  onRetry: () => void;
  onDiscard: () => void;
}

export function AccountDeletionRecoveryScreen({
  checking,
  onRetry,
  onDiscard,
}: AccountDeletionRecoveryScreenProps) {
  return (
    <section className="session-recovery-screen account-deletion-status-screen" aria-labelledby="account-deletion-recovery-title">
      <div className="session-recovery-screen__glow" aria-hidden="true" />
      <div className="session-recovery-screen__frame account-deletion-status-screen__frame">
        <AuthPanel
          role="status"
          titleId="account-deletion-recovery-title"
          bodyClassName="session-recovery-screen__body account-deletion-status-screen__body"
          header={(
            <AuthTitleBand
              titleId="account-deletion-recovery-title"
              title="Account deletion recovery"
              icon={checking
                ? <Clock3 className="session-recovery-screen__title-icon" />
                : <ShieldAlert className="session-recovery-screen__title-icon" />}
            />
          )}
        >
          <PortalTruthPill tone={checking ? 'muted' : 'warning'}>
            {checking ? 'Checking' : 'Confirmation unavailable'}
          </PortalTruthPill>
          <p className="session-recovery-screen__primary-copy">
            {checking
              ? 'Checking whether the saved recovery request reached the server.'
              : 'The server could not confirm the saved recovery request. The recovery token remains on this device.'}
          </p>
          {!checking ? (
            <BeetleButton onClick={onRetry} className="session-recovery-screen__button--full">
              Check again
            </BeetleButton>
          ) : null}
          <div className="account-deletion-status-screen__discard">
            <p>Removing this saved recovery does not cancel a server request.</p>
            <BeetleButton variant="secondary" onClick={onDiscard}>
              Remove saved recovery request
            </BeetleButton>
          </div>
        </AuthPanel>
      </div>
    </section>
  );
}

interface AccountDeletionCapabilityErrorScreenProps {
  kind: 'invalid' | 'unavailable';
  onDiscard: () => void;
}

export function AccountDeletionCapabilityErrorScreen({
  kind,
  onDiscard,
}: AccountDeletionCapabilityErrorScreenProps) {
  return (
    <section className="session-recovery-screen account-deletion-status-screen" aria-labelledby="account-deletion-capability-title">
      <div className="session-recovery-screen__glow" aria-hidden="true" />
      <div className="session-recovery-screen__frame account-deletion-status-screen__frame">
        <AuthPanel
          role="alert"
          titleId="account-deletion-capability-title"
          bodyClassName="session-recovery-screen__body"
          header={(
            <AuthTitleBand
              titleId="account-deletion-capability-title"
              title="Account deletion status unavailable"
              icon={<ShieldAlert className="session-recovery-screen__title-icon" />}
            />
          )}
        >
          <AuthNotice tone="error" className="session-recovery-screen__notice">
            {kind === 'unavailable'
              ? 'This browser cannot read saved request status.'
              : 'The saved request status is invalid. Remove it from this device or contact support.'}
          </AuthNotice>
          {kind === 'invalid' ? (
            <BeetleButton variant="secondary" onClick={onDiscard}>
              Remove saved status from this device
            </BeetleButton>
          ) : null}
          <a className="beetle-button account-deletion-status-screen__support" href={SUPPORT_URL}>Contact support</a>
        </AuthPanel>
      </div>
    </section>
  );
}
