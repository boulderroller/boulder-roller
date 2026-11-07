import { useCallback, useEffect, useRef, useState, type FormEvent } from 'react';
import { useAuth } from '../../contexts/AuthContext';
import { usePrivyBridgeState, usePrivyEmailAuth, usePrivySessionResume } from '../../contexts/PrivyContext';
import { formatAuthError, isSignupRefusedError } from '../../lib/auth-errors';
import { KeyRound, Mail } from 'lucide-react';
import { AuthEmailCodeForm, AuthHeading, AuthNavigation, AuthPanel, AuthStatus } from './AuthSurface';
import { AUTH_PHASES } from '../../lib/authState';
import type { AuthTransactionMethod, AuthTransactionStage } from '../../lib/authTransaction';

const E2E_MOCK_WALLET = 'e2ePrivyWallet11111111111111111111111111111';

interface SocialLoginRuntimeProps {
  authTransactionId?: string;
  authTransactionMethod?: AuthTransactionMethod;
  authTransactionStage?: AuthTransactionStage;
  autoSendCode?: boolean;
  hasValidatedInvite?: boolean;
  initialEmail?: string;
  onEmailChange?: (email: string) => void;
  inviteCode?: string | null;
  inviteRecoveryPending?: boolean;
  onBack: () => void;
  onAuthenticatedSessionResume?: () => void;
  onInviteRecovery: () => Promise<boolean>;
  onSignupRefused: () => void;
  onClose: () => void;
  resumeAuthenticatedSession?: boolean;
}

function describeFlowError(error: unknown, fallback: string): string {
  if (error instanceof Error) {
    return formatAuthError(error);
  }
  return fallback;
}

function SocialLoginRuntimeInner({
  authTransactionId,
  authTransactionMethod,
  authTransactionStage,
  autoSendCode = false,
  hasValidatedInvite = false,
  initialEmail = '',
  onEmailChange,
  inviteCode = null,
  inviteRecoveryPending = false,
  onBack,
  onAuthenticatedSessionResume,
  onInviteRecovery,
  onSignupRefused,
  onClose,
  resumeAuthenticatedSession = false,
}: SocialLoginRuntimeProps) {
  const auth = useAuth();
  const { isAuthenticated } = auth;
  const { authenticated, active: resumeSyncActive } = usePrivySessionResume(
    resumeAuthenticatedSession,
    onAuthenticatedSessionResume,
  );
  const { sendCode, loginWithCode, state: emailState } = usePrivyEmailAuth();
  const { walletPending, syncError, syncRecovery, retrySync, resetSyncError } = usePrivyBridgeState();
  const [email, setEmail] = useState(initialEmail);
  const [sentEmail, setSentEmail] = useState('');
  const [code, setCode] = useState('');
  const [requestPending, setRequestPending] = useState(false);
  const [verifyPending, setVerifyPending] = useState(false);
  const requestEpochRef = useRef(0);
  const verifyingRef = useRef(false);
  useEffect(() => () => { requestEpochRef.current++; }, []);
  const [flowError, setFlowError] = useState<string | null>(null);
  const [autoSendActive, setAutoSendActive] = useState(
    autoSendCode && Boolean(initialEmail) && !resumeAuthenticatedSession,
  );
  const autoSendStartedRef = useRef(false);
  const codeRequestRef = useRef<{ email: string; promise: Promise<void> } | null>(null);
  const codeInputRef = useRef<HTMLInputElement>(null);
  const emailInputRef = useRef<HTMLInputElement>(null);
  const pendingInviteCode = inviteCode?.trim() || null;
  // A provider may retain its previous code-input status after Back. Only this
  // screen's completed request establishes its email receipt and code form.
  const codeRequested = sentEmail.length > 0;
  const isSendingCode = emailState.status === 'sending-code' || requestPending;
  const isCodeRequestPending = isSendingCode || autoSendActive;
  const isSubmittingCode = emailState.status === 'submitting-code' || verifyPending;
  const authPhase = syncError || flowError
    ? AUTH_PHASES.recoverableError
    : walletPending
      ? AUTH_PHASES.walletResolution
      : authenticated || isSubmittingCode
        ? AUTH_PHASES.sessionExchange
        : AUTH_PHASES.providerPending;

  useEffect(() => {
    if (isAuthenticated) {
      onClose();
    }
  }, [isAuthenticated, onClose]);

  const handleBack = () => {
    requestEpochRef.current++;
    resetSyncError();
    setFlowError(null);
    onBack();
  };

  const handleInviteRecovery = async () => {
    resetSyncError();
    setFlowError(null);
    try {
      const recovered = await onInviteRecovery();
      if (!recovered) {
        setFlowError('Could not clear this invite. Try again.');
      }
    } catch {
      setFlowError('Could not clear this invite. Try again.');
    }
  };

  const handleProviderError = useCallback((error: unknown, fallback: string) => {
    if (!isSignupRefusedError(error)) {
      setFlowError(describeFlowError(error, fallback));
      return;
    }
    resetSyncError();
    if (hasValidatedInvite) {
      setFlowError('Account setup is unavailable. Try again.');
    } else {
      setFlowError(null);
      onSignupRefused();
    }
  }, [hasValidatedInvite, onSignupRefused, resetSyncError]);

  const requestEmailCode = useCallback(async (emailAddress: string) => {
    const normalizedEmail = emailAddress.trim().toLowerCase();
    if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(normalizedEmail)) {
      setFlowError('Enter a valid email.');
      return;
    }

    if (codeRequestRef.current?.email === normalizedEmail) {
      return codeRequestRef.current.promise;
    }

    const requestEpoch = ++requestEpochRef.current;
    const request = {
      email: normalizedEmail,
      promise: Promise.resolve(),
    };
    request.promise = (async () => {
      resetSyncError();
      setFlowError(null);
      setCode('');
      setRequestPending(true);

      try {
        await sendCode({ email: normalizedEmail });
        if (requestEpoch !== requestEpochRef.current) return;
        setSentEmail(normalizedEmail);
      } catch (error) {
        if (requestEpoch !== requestEpochRef.current) return;
        handleProviderError(error, 'Could not send a sign-in code.');
      } finally {
        if (requestEpoch === requestEpochRef.current) setRequestPending(false);
        if (codeRequestRef.current === request) {
          codeRequestRef.current = null;
        }
      }
    })();
    codeRequestRef.current = request;
    return request.promise;
  }, [handleProviderError, resetSyncError, sendCode]);

  const handleEmailSubmit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    await requestEmailCode(email);
  };

  useEffect(() => {
    if (
      resumeSyncActive
      || !autoSendActive
      || autoSendStartedRef.current
      || !initialEmail
    ) return;
    autoSendStartedRef.current = true;
    void requestEmailCode(initialEmail).finally(() => setAutoSendActive(false));
  }, [autoSendActive, initialEmail, requestEmailCode, resumeSyncActive]);

  useEffect(() => {
    if (isCodeRequestPending || isSubmittingCode) return;
    (codeRequested ? codeInputRef : emailInputRef).current?.focus();
  }, [codeRequested, isCodeRequestPending, isSubmittingCode, flowError, syncError]);

  const handleCodeSubmit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (verifyingRef.current || isCodeRequestPending || walletPending || inviteRecoveryPending) return;

    const trimmedCode = code.trim();
    if (!trimmedCode) {
      setFlowError('Enter the code.');
      return;
    }

    resetSyncError();
    setFlowError(null);
    retrySync();
    verifyingRef.current = true;
    setVerifyPending(true);
    const requestEpoch = requestEpochRef.current;

    try {
      if (
        import.meta.env.VITE_PRIVY_E2E_MOCK === 'true'
        && !(window as Window & { __brE2EUseProviderCodeExchange?: boolean })
          .__brE2EUseProviderCodeExchange
      ) {
        await auth.loginWithPrivy(E2E_MOCK_WALLET, `e2e-email-code:${trimmedCode}`, pendingInviteCode ?? undefined);
        return;
      }

      await loginWithCode({ code: trimmedCode });
    } catch (error) {
      if (requestEpoch === requestEpochRef.current) handleProviderError(error, 'Could not verify the code.');
    } finally {
      verifyingRef.current = false;
      if (requestEpoch === requestEpochRef.current) setVerifyPending(false);
    }
  };

  const handleChangeEmail = () => {
    // Returning to the entry form also preserves a validated invite and the
    // current email, without relying on a reset API the provider does not expose.
    onEmailChange?.(email);
    handleBack();
  };

  const hasInviteRecovery = syncRecovery === 'invite_required'
    || syncRecovery === 'invite_invalid';


  const status = inviteRecoveryPending ? 'Checking' : walletPending ? 'Creating wallet' : resumeSyncActive && !syncError ? 'Finishing sign in.' : isSubmittingCode ? 'Checking' : isCodeRequestPending ? 'Sending' : '';
  const finishing = !inviteRecoveryPending && !syncError && !flowError && (walletPending || resumeSyncActive || authenticated);

  return (
    <AuthPanel
      role="region"
      titleId="social-login-title"
      className="social-login-inline"
      bodyClassName="social-login-modal__body"
      header={<AuthHeading title="Sign in" onBack={handleBack} backDisabled={inviteRecoveryPending} />}
      data-auth-phase={authPhase}
      data-auth-recovery={syncRecovery ?? ''}
      data-auth-transaction-id={authTransactionId}
      data-auth-transaction-stage={authTransactionStage}
      data-auth-transaction-method={authTransactionMethod ?? ''}
      data-auth-email-state={emailState.status}
    >
      <h2 id="social-login-title" className="access-panel__sr-title">Account sign in</h2>
      <AuthStatus>{status}</AuthStatus>
      {finishing ? (
        <div className="auth-entry-sheet">
          <div className="auth-entry-receipt"><Mail aria-hidden="true" /><span>{sentEmail || email}</span></div>
          <div className="auth-entry-status">
            <p>{walletPending ? 'Creating wallet' : 'Finishing sign in.'}</p>
            <p className="auth-entry-copy">{walletPending ? 'Creating rider wallet in the background.' : 'Checking account access and opening your session.'}</p>
          </div>
        </div>
      ) : (
        <>
          <AuthEmailCodeForm
            codeRequested={codeRequested} email={codeRequested ? sentEmail : email} code={code}
            hasValidatedInvite={hasValidatedInvite} error={syncError || flowError} pending={isCodeRequestPending || isSubmittingCode || walletPending || inviteRecoveryPending}
            status={status} inputRef={codeRequested ? codeInputRef : emailInputRef}
            onSubmit={codeRequested ? handleCodeSubmit : handleEmailSubmit}
            onChange={(value) => {
              setFlowError(null);
              if (codeRequested) setCode(value);
              else { setEmail(value); onEmailChange?.(value); }
            }}
          />
          {!codeRequested && <p id="social-login-email-helper" className="auth-entry-footer">{hasValidatedInvite ? "We'll send a code to finish your account." : "We'll send a sign-in code."}</p>}
          {hasInviteRecovery ? (
            <div className="auth-entry-sheet"><AuthNavigation icon={<KeyRound aria-hidden="true" />} onClick={handleInviteRecovery} disabled={inviteRecoveryPending}>Invite code</AuthNavigation></div>
          ) : codeRequested && (
            <div className="auth-entry-sheet auth-entry-recovery-actions">
              <button type="button" className="auth-entry-row" onClick={handleChangeEmail} disabled={isSubmittingCode || isCodeRequestPending}>Change email</button>
              <button type="button" className="auth-entry-row" onClick={() => void requestEmailCode(sentEmail)} disabled={isSubmittingCode || isCodeRequestPending}>Send code</button>
            </div>
          )}
        </>
      )}
    </AuthPanel>
  );
}

export default function SocialLoginRuntime(props: SocialLoginRuntimeProps) {
  return <SocialLoginRuntimeInner {...props} />;
}
