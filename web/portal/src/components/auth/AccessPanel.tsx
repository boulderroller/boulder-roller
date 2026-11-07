import {
  lazy,
  Suspense,
  useCallback,
  useEffect,
  useReducer,
  useRef,
  useState,
  type FormEvent,
  type Ref,
} from 'react';
import { Check, KeyRound, LogIn, Mail, Wallet } from 'lucide-react';
import { useAuth } from '../../contexts/AuthContext';
import { AuthRuntimeBoundary, useAuthRuntime } from '../../contexts/AuthRuntimeContext';
import { formatAuthError } from '../../lib/auth-errors';
import { api } from '../../lib/api';
import { AUTH_PHASES } from '../../lib/authState';
import {
  clearAccessSignInIntent,
  clearPendingInviteCode,
  markAccessSignInIntent,
  setPendingInviteCode,
} from '../../lib/authHandoff';
import { authTransactionReducer, createAuthTransaction } from '../../lib/authTransaction';
import { BeetleButton } from '../ui/beetle-button';
import { BeetleInput } from '../ui/beetle-input';
import { AuthHeading, AuthNavigation, AuthNotice, AuthPanel, AuthStatus } from './AuthSurface';

const WalletConnectFlow = lazy(() => import('./WalletConnectFlow'));
const SocialLoginLauncher = lazy(() => import('./SocialLoginLauncher'));
const preloadWalletConnectFlow = () => import('./WalletConnectFlow');
const preloadSocialLoginFlow = () => import('./SocialLoginLauncher');

const PRIVY_ENABLED = !!import.meta.env.VITE_PRIVY_APP_ID;
const PRIVY_BLOCKED_ORIGIN = typeof window !== 'undefined' && window.location.hostname === '127.0.0.1';
const PRIVY_SOCIAL_ENABLED = PRIVY_ENABLED && !PRIVY_BLOCKED_ORIGIN;
const LOCAL_PORT = typeof window !== 'undefined' ? window.location.port || '5173' : '5173';
const RECOMMENDED_LOCALHOST_ORIGIN = `http://localhost:${LOCAL_PORT}`;
const BLOCKED_127_ORIGIN = `http://127.0.0.1:${LOCAL_PORT}`;

function shouldPrefetchAuthChunks(): boolean {
  if (typeof navigator === 'undefined') return true;

  const connection = (navigator as Navigator & {
    connection?: { saveData?: boolean; effectiveType?: string };
  }).connection;

  if (!connection) return true;
  if (connection.saveData) return false;
  if (connection.effectiveType === 'slow-2g' || connection.effectiveType === '2g') return false;
  return true;
}

interface AccessPanelProps {
  initialInviteCode?: string | null;
  initialInviteValidated?: boolean;
  initialShowLoginOptions?: boolean;
  onRetrySessionCheck?: () => void;
  sessionCheckError?: string | null;
  sessionPending?: boolean;
}


interface EntryEmailFormProps {
  email: string;
  fieldError?: string | null;
  helperText?: string;
  inputRef?: Ref<HTMLInputElement>;
  loadingLabel?: string;
  notice?: string | null;
  onChange: (email: string) => void;
  onRetry?: () => void;
  onSubmit: (event: FormEvent<HTMLFormElement>) => void;
  pending?: boolean;
  statusId?: string;
  inviteAccepted?: boolean;
}

function EntryEmailForm({
  email,
  fieldError = null,
  helperText = "We'll send a sign-in code.",
  inputRef,
  loadingLabel = 'Preparing sign-in',
  notice = null,
  onChange,
  onRetry,
  onSubmit,
  pending = false,
  statusId,
  inviteAccepted = false,
}: EntryEmailFormProps) {
  const fieldErrorId = fieldError ? 'access-email-error' : undefined;
  const noticeId = notice ? 'access-email-notice' : undefined;
  const descriptionId = [fieldErrorId, noticeId, statusId, 'access-email-helper'].filter(Boolean).join(' ');
  const handleSubmit = (event: FormEvent<HTMLFormElement>) => {
    if (!onRetry) {
      onSubmit(event);
      return;
    }

    event.preventDefault();
    onRetry();
  };

  return (
    <>
    <form noValidate className="auth-entry-sheet access-panel__form access-panel__email-form" onSubmit={handleSubmit}>
      {inviteAccepted && <div id="access-invite-status" className="auth-entry-fact"><Check aria-hidden="true" />Invite accepted</div>}
      <div className="auth-entry-field">
        <label className="access-panel__label" htmlFor="access-sign-in-email">
          Email
        </label>
        <BeetleInput
          ref={inputRef}
          id="access-sign-in-email"
          type="email"
          value={email}
          onChange={(event) => onChange(event.target.value)}
          placeholder="you@example.com"
          autoComplete="username"
          autoCapitalize="none"
          name="email"
          spellCheck={false}
          aria-describedby={descriptionId}
          error={!!fieldError}
          disabled={pending}
        />
      </div>

      {fieldError && (
        <AuthNotice id={fieldErrorId} role="alert" tone="error">
          {fieldError}
        </AuthNotice>
      )}

      {notice && (
        <AuthNotice id={noticeId} role="alert" tone="error">
          {notice}
        </AuthNotice>
      )}

      {onRetry ? (
        <BeetleButton
          type="submit"
          variant="primary"
          className="access-panel__full-action auth-entry-action"
        >
          Retry session check
        </BeetleButton>
      ) : (
        <BeetleButton
          type="submit"
          variant="primary"
          className="access-panel__full-action auth-entry-action"
          isLoading={pending}
          loadingLabel={loadingLabel}
        >
          Send code
        </BeetleButton>
      )}

    </form>
      <p id="access-email-helper" className="access-panel__email-helper">
        {helperText}
      </p>
    </>
  );
}

export default function AccessPanel({
  initialInviteCode = null,
  initialInviteValidated = false,
  initialShowLoginOptions = false,
  onRetrySessionCheck,
  sessionCheckError = null,
  sessionPending = false,
}: AccessPanelProps) {
  const [transaction, dispatchTransaction] = useReducer(
    authTransactionReducer,
    {
      showLoginOptions: initialShowLoginOptions,
      inviteValidated: initialInviteValidated,
    },
    createAuthTransaction,
  );
  const [waitlistEmail, setWaitlistEmail] = useState('');
  const [waitlistSubmittedEmail, setWaitlistSubmittedEmail] = useState('');
  const [waitlistError, setWaitlistError] = useState<string | null>(null);
  const [waitlistSuccess, setWaitlistSuccess] = useState(false);
  const [isJoiningWaitlist, setIsJoiningWaitlist] = useState(false);
  const [isClearingInvite, setIsClearingInvite] = useState(false);
  const [signInEmail, setSignInEmail] = useState('');
  const [resumeEmailSessionAfterInvite, setResumeEmailSessionAfterInvite] = useState(false);
  const appliedInviteBootstrapRef = useRef(initialShowLoginOptions);
  const appliedInviteCodeRef = useRef(false);
  const emailInputRef = useRef<HTMLInputElement>(null);
  const inviteCodeInputRef = useRef<HTMLInputElement>(null);
  const requestEmailInputRef = useRef<HTMLInputElement>(null);
  const submittedHeadingRef = useRef<HTMLHeadingElement>(null);
  const requestEpochRef = useRef(0);
  const requestPendingRef = useRef(false);
  useEffect(() => () => { requestEpochRef.current++; }, []);
  const cancelPendingRequest = () => { requestEpochRef.current++; requestPendingRef.current = false; };
  const { isAuthenticated } = useAuth();
  const {
    status: authRuntimeStatus,
    error: authRuntimeError,
    ensureRuntime,
    retryRuntime,
  } = useAuthRuntime();
  const inviteCode = transaction.inviteCode;
  const hasActiveInvite = transaction.inviteValidated;
  const validatedInviteCode = transaction.inviteValidated && transaction.inviteCode
    ? transaction.inviteCode
    : null;
  const stage = transaction.stage;
  const showsAcceptedInvite = hasActiveInvite && stage === 'method_choice';
  const showWalletConnect = stage === 'wallet_provider';
  const showSocialLogin = stage === 'email_provider';
  const error = transaction.error;
  const emailValidationError = error === 'Enter a valid email.' ? error : null;
  const isValidating = transaction.isInviteValidating;
  const entryPending = sessionPending;
  const canShowBack = (stage !== 'entry' && stage !== 'method_choice') || showsAcceptedInvite;
  const authRuntimeUnavailable = authRuntimeStatus === 'failed';
  const authRuntimeMessage = authRuntimeUnavailable
    ? authRuntimeError ?? 'Sign-in failed to load.'
    : 'Preparing sign-in.';
  const accessPanelTitle = stage === 'invite_entry'
    ? 'Invite code'
    : stage === 'request_invite'
      ? 'Request invite'
      : stage === 'waitlist_submitted'
        ? 'Request received'
        : 'Account entry';
  const hasVisibleTitle = stage === 'waitlist_submitted';
  const pageHeading = stage === 'waitlist_submitted' ? 'Request received' : stage === 'request_invite'
    ? 'Request access'
    : stage === 'invite_entry' || showsAcceptedInvite
      ? 'Start your account'
      : 'Sign in';

  const validateInviteCode = useCallback(async (code: string) => {
    try {
      return await api.validateInviteCode(code);
    } catch {
      return {
        valid: false,
        message: 'network_error',
      };
    }
  }, []);

  const previousStageRef = useRef(stage);
  useEffect(() => {
    const previousStage = previousStageRef.current;
    previousStageRef.current = stage;
    if (previousStage === stage) return;

    const nextFocus = stage === 'invite_entry'
      ? inviteCodeInputRef.current
      : stage === 'request_invite'
        ? requestEmailInputRef.current
        : stage === 'entry' || stage === 'method_choice'
          ? emailInputRef.current
          : stage === 'waitlist_submitted'
            ? submittedHeadingRef.current
            : null;
    if (!nextFocus) return;

    const frame = window.requestAnimationFrame(() => nextFocus.focus());
    return () => window.cancelAnimationFrame(frame);
  }, [stage]);

  useEffect(() => {
    if (!initialShowLoginOptions || appliedInviteBootstrapRef.current) return;
    if (stage !== 'entry' && stage !== 'method_choice') {
      appliedInviteBootstrapRef.current = true;
      return;
    }

    appliedInviteBootstrapRef.current = true;
    dispatchTransaction({
      type: 'bootstrap',
      showLoginOptions: true,
      inviteValidated: initialInviteValidated,
    });
  }, [initialInviteValidated, initialShowLoginOptions, stage]);

  useEffect(() => {
    if (appliedInviteCodeRef.current || !initialInviteCode || initialShowLoginOptions) return;
    if (stage !== 'entry') {
      appliedInviteCodeRef.current = true;
      return;
    }

    appliedInviteCodeRef.current = true;
    const code = initialInviteCode.trim().toLowerCase();
    dispatchTransaction({ type: 'prefill_invite', code });

    if (!code) {
      dispatchTransaction({ type: 'validate_invite_failure', error: 'Invite code required.' });
      return;
    }

    let cancelled = false;
    const requestEpoch = ++requestEpochRef.current;
    dispatchTransaction({ type: 'validate_invite_start' });
    void validateInviteCode(code).then((result) => {
      if (cancelled || requestEpoch !== requestEpochRef.current) return;
      if (!result.valid) {
        dispatchTransaction({
          type: 'validate_invite_failure',
          error: formatAuthError(new Error(result.message || 'invite_invalid')),
        });
        return;
      }

      clearAccessSignInIntent();
      setPendingInviteCode(code);
      dispatchTransaction({ type: 'validate_invite_success', code });
    });

    return () => {
      cancelled = true;
    };
  }, [initialInviteCode, initialShowLoginOptions, validateInviteCode]);

  useEffect(() => {
    if (stage !== 'request_invite') {
      setWaitlistError(null);
      setIsJoiningWaitlist(false);
    }
    if (stage !== 'request_invite' && stage !== 'waitlist_submitted') {
      setWaitlistSuccess(false);
    }
  }, [stage]);

  const warmWalletFlow = () => {
    if (!shouldPrefetchAuthChunks()) return;
    void preloadWalletConnectFlow();
  };

  const warmSocialFlow = () => {
    if (!PRIVY_SOCIAL_ENABLED || !shouldPrefetchAuthChunks()) return;
    void preloadSocialLoginFlow();
  };

  const handleInviteSubmit = async (e: FormEvent) => {
    e.preventDefault();
    if (requestPendingRef.current) return;
    const email = signInEmail.trim().toLowerCase();
    if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email)) {
      dispatchTransaction({ type: 'surface_error', recovery: 'provider_exchange', error: 'Enter a valid email.' });
      emailInputRef.current?.focus();
      return;
    }

    const code = inviteCode.trim().toLowerCase();
    if (!code) {
      dispatchTransaction({ type: 'validate_invite_failure', error: 'Invite code required.' });
      return;
    }

    requestPendingRef.current = true;
    const requestEpoch = ++requestEpochRef.current;
    dispatchTransaction({ type: 'validate_invite_start' });
    const result = await validateInviteCode(code);
    if (requestEpoch !== requestEpochRef.current) return;
    requestPendingRef.current = false;

    if (!result.valid) {
      dispatchTransaction({
        type: 'validate_invite_failure',
        error: formatAuthError(new Error(result.message || 'invite_invalid')),
      });
      return;
    }

    clearAccessSignInIntent();
    setPendingInviteCode(code);
    dispatchTransaction({ type: 'validate_invite_success', code });
    setSignInEmail(email);
    if (resumeEmailSessionAfterInvite) {
      dispatchTransaction({ type: 'choose_email' });
      ensureRuntime();
    } else {
      startEmailSignIn(email);
    }
  };

  const handleWaitlistSubmit = async (e: FormEvent) => {
    e.preventDefault();
    if (requestPendingRef.current) return;

    const email = waitlistEmail.trim().toLowerCase();
    if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email)) {
      setWaitlistSuccess(false);
      setWaitlistError('Enter a valid email.');
      return;
    }

    requestPendingRef.current = true;
    const requestEpoch = ++requestEpochRef.current;
    setIsJoiningWaitlist(true);
    setWaitlistError(null);
    setWaitlistSuccess(false);

    try {
      const result = await api.joinWaitlist(email, 'portal_access');
      if (requestEpoch !== requestEpochRef.current) return;
      const submittedEmail = result.email || email;
      setWaitlistSubmittedEmail(submittedEmail);
      setWaitlistEmail(submittedEmail);
      setWaitlistSuccess(true);
      dispatchTransaction({ type: 'show_waitlist_submitted' });
    } catch {
      if (requestEpoch !== requestEpochRef.current) return;
      setWaitlistError('Could not request invite.');
    } finally {
      if (requestEpoch === requestEpochRef.current) {
        requestPendingRef.current = false;
        setIsJoiningWaitlist(false);
      }
    }
  };

  const handleDirectEmailChange = (email: string) => {
    setSignInEmail(email);
    if (error) {
      dispatchTransaction({ type: 'clear_error' });
    }
  };

  const startEmailSignIn = (emailValue: string) => {

    if (!PRIVY_ENABLED) {
      dispatchTransaction({
        type: 'surface_error',
        recovery: 'provider_exchange',
        error: 'Email sign-in is unavailable.',
      });
      return;
    }

    if (PRIVY_BLOCKED_ORIGIN) {
      dispatchTransaction({
        type: 'surface_error',
        recovery: 'email_origin_blocked',
        error: `Email login is blocked on ${BLOCKED_127_ORIGIN}. Use ${RECOMMENDED_LOCALHOST_ORIGIN} or allow this origin in the login provider dashboard.`,
      });
      return;
    }

    const email = emailValue.trim().toLowerCase();
    if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email)) {
      dispatchTransaction({
        type: 'surface_error',
        recovery: 'provider_exchange',
        error: 'Enter a valid email.',
      });
      return;
    }

    setSignInEmail(email);
    dispatchTransaction({ type: 'clear_error' });

    markAccessSignInIntent();
    dispatchTransaction({ type: 'choose_email' });
    warmSocialFlow();

    if (authRuntimeUnavailable) {
      retryRuntime();
    } else {
      ensureRuntime();
    }
  };

  const handleDirectEmailSubmit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!entryPending && !isClearingInvite) startEmailSignIn(signInEmail);
  };

  const handleWalletLogin = () => {
    cancelPendingRequest();
    warmWalletFlow();
    dispatchTransaction({ type: 'choose_wallet' });
  };

  const handleBackToEntry = () => {
    cancelPendingRequest();
    clearAccessSignInIntent();
    setResumeEmailSessionAfterInvite(false);
    dispatchTransaction({ type: 'show_entry' });
  };

  const handleInviteEntry = () => {
    cancelPendingRequest();
    if (stage === 'request_invite' || stage === 'waitlist_submitted') setSignInEmail(waitlistSubmittedEmail || waitlistEmail);
    clearAccessSignInIntent();
    setResumeEmailSessionAfterInvite(false);
    dispatchTransaction({ type: 'show_invite_entry' });
  };

  const handleSignupRefused = () => {
    cancelPendingRequest();
    clearAccessSignInIntent();
    clearPendingInviteCode();
    setResumeEmailSessionAfterInvite(false);
    dispatchTransaction({ type: 'show_invite_entry' });
    dispatchTransaction({ type: 'surface_error', recovery: 'invite_validation', error: 'Invite required to continue. Enter your invite code.' });
  };

  const clearInviteAndShowEntry = async (resumeEmailSession: boolean): Promise<boolean> => {
    if (isClearingInvite) return false;

    setIsClearingInvite(true);
    dispatchTransaction({ type: 'clear_error' });
    try {
      await api.clearInviteState();
      clearAccessSignInIntent();
      clearPendingInviteCode();
      setResumeEmailSessionAfterInvite(resumeEmailSession);
      dispatchTransaction({ type: 'show_invite_entry' });
      return true;
    } catch {
      dispatchTransaction({
        type: 'surface_error',
        recovery: 'invite_validation',
        error: 'Could not clear this invite. Try again.',
      });
      return false;
    } finally {
      setIsClearingInvite(false);
    }
  };

  const handleProviderInviteRecovery = () => clearInviteAndShowEntry(true);
  const handleDifferentInvite = () => clearInviteAndShowEntry(false);

  const handleRequestAccess = () => {
    cancelPendingRequest();
    setResumeEmailSessionAfterInvite(false);
    if (!waitlistEmail && signInEmail) {
      setWaitlistEmail(signInEmail);
    }
    dispatchTransaction({ type: waitlistSuccess && waitlistSubmittedEmail
      ? 'show_waitlist_submitted'
      : 'show_request_invite' });
  };

  const handleDifferentWaitlistEmail = () => {
    cancelPendingRequest();
    setWaitlistEmail('');
    setWaitlistSubmittedEmail('');
    setWaitlistError(null);
    setWaitlistSuccess(false);
    dispatchTransaction({ type: 'show_request_invite' });
  };

  if (showWalletConnect) {
    return (
      <Suspense fallback={(
        <AuthPanel
          role="region"
          titleId="wallet-connect-loading-title"
          className="wallet-connect-inline"
          bodyClassName="wallet-connect-modal__body"
          header={<AuthHeading title="Use your wallet" onBack={handleBackToEntry} />}
          data-auth-phase={AUTH_PHASES.providerPending}
          data-auth-transaction-id={transaction.id}
          data-auth-transaction-stage={transaction.stage}
          data-auth-transaction-method="wallet"
        >
          <h2 id="wallet-connect-loading-title" className="access-panel__sr-title">
            Use your wallet
          </h2>
          <p className="wallet-connect-modal__intro-copy">
            Preparing wallet sign-in.
          </p>
          <AuthStatus>Preparing wallet sign-in.</AuthStatus>
        </AuthPanel>
      )}>
        <WalletConnectFlow
          authTransactionId={transaction.id}
          authTransactionMethod="wallet"
          authTransactionStage={transaction.stage}
          onSuccess={() => {}}
          onBack={() => dispatchTransaction({ type: 'back_to_methods' })}
        />
      </Suspense>
    );
  }

  if (showSocialLogin) {
    const emailRuntimeFallback = (
      <AuthPanel
        role="region"
        titleId="access-panel-title"
        className="access-panel"
        bodyClassName="access-panel__body"
        header={<AuthHeading title="Sign in" onBack={handleBackToEntry} />}
        data-auth-phase={AUTH_PHASES.providerPending}
        data-auth-transaction-id={transaction.id}
        data-auth-transaction-stage={transaction.stage}
        data-auth-transaction-method="email"
        data-auth-runtime={authRuntimeStatus}
      >
        <h2 id="access-panel-title" className="access-panel__sr-title">
          Account sign in
        </h2>
        <EntryEmailForm
          email={signInEmail}
          fieldError={emailValidationError}
          inputRef={emailInputRef}
          loadingLabel="Preparing sign-in"
          notice={authRuntimeUnavailable ? authRuntimeMessage : null}
          onChange={handleDirectEmailChange}
          onRetry={authRuntimeUnavailable ? retryRuntime : undefined}
          onSubmit={handleDirectEmailSubmit}
          pending={!authRuntimeUnavailable}
        />
      </AuthPanel>
    );

    return (
      <AuthRuntimeBoundary fallback={emailRuntimeFallback}>
        <Suspense fallback={emailRuntimeFallback}>
          <SocialLoginLauncher
            authTransactionId={transaction.id}
            authTransactionMethod="email"
            authTransactionStage={transaction.stage}
            autoSendCode
            hasValidatedInvite={transaction.inviteValidated}
            initialEmail={signInEmail}
            onEmailChange={setSignInEmail}
            inviteRecoveryPending={isClearingInvite}
            inviteCode={validatedInviteCode}
            onBack={() => dispatchTransaction({ type: hasActiveInvite ? 'back_to_methods' : 'show_entry' })}
            onAuthenticatedSessionResume={() => setResumeEmailSessionAfterInvite(false)}
            onInviteRecovery={handleProviderInviteRecovery}
            onSignupRefused={handleSignupRefused}
            onClose={() => {}}
            resumeAuthenticatedSession={resumeEmailSessionAfterInvite}
          />
        </Suspense>
      </AuthRuntimeBoundary>
    );
  }

  return (
    <AuthPanel
      role="region"
      titleId="access-panel-title"
      className="access-panel"
      bodyClassName="access-panel__body"
      header={<AuthHeading title={pageHeading} backDisabled={isClearingInvite} headingRef={submittedHeadingRef} onBack={canShowBack ? (stage === 'request_invite' || stage === 'waitlist_submitted' ? handleInviteEntry : handleBackToEntry) : undefined} />}
      data-auth-phase={transaction.phase}
      data-auth-transaction-id={transaction.id}
      data-auth-transaction-stage={transaction.stage}
      data-auth-transaction-method={transaction.method ?? ''}
      data-auth-transaction-recovery={transaction.recovery ?? ''}
      data-auth-runtime={authRuntimeStatus}
      data-authenticated={isAuthenticated ? 'true' : 'false'}
    >
      {!hasVisibleTitle && (
        <h2 id="access-panel-title" className="access-panel__sr-title">
          {accessPanelTitle}
        </h2>
      )}

      <AuthStatus>{isValidating || isClearingInvite ? 'Checking' : isJoiningWaitlist ? 'Sending' : entryPending ? 'Checking session' : ''}</AuthStatus>

      {(stage === 'entry' || stage === 'method_choice') && (
        <>
          <EntryEmailForm
            email={signInEmail}
            fieldError={sessionCheckError ? null : emailValidationError}
            helperText={showsAcceptedInvite
              ? "We'll send a code to finish your account."
              : "We'll send a sign-in code."}
            inputRef={emailInputRef}
            loadingLabel={isClearingInvite ? 'Checking' : 'Checking session'}
            notice={sessionCheckError || (error && error !== emailValidationError ? error : null)}
            onChange={handleDirectEmailChange}
            onRetry={sessionCheckError ? onRetrySessionCheck : undefined}
            onSubmit={handleDirectEmailSubmit}
            pending={entryPending || isClearingInvite}
            statusId={showsAcceptedInvite ? 'access-invite-status' : undefined}
            inviteAccepted={showsAcceptedInvite}
          />

          {!entryPending && !sessionCheckError && (
            <div className="auth-entry-sheet">
              {showsAcceptedInvite ? (
                <AuthNavigation icon={<KeyRound aria-hidden="true" />} onClick={handleDifferentInvite} disabled={isClearingInvite}>Use a different invite</AuthNavigation>
              ) : (
                <>
                  <AuthNavigation icon={<KeyRound aria-hidden="true" />} onClick={handleInviteEntry}>Enter invite code</AuthNavigation>
                  <AuthNavigation icon={<Wallet aria-hidden="true" />} onClick={handleWalletLogin} onMouseEnter={warmWalletFlow} onFocus={warmWalletFlow} helper="For riders who signed up with a wallet.">Use wallet instead</AuthNavigation>
                </>
              )}
            </div>
          )}
        </>
      )}

      {stage === 'invite_entry' && (
        <>
          <form noValidate onSubmit={handleInviteSubmit} className="auth-entry-sheet access-panel__form">
            <div className="auth-entry-field">
              <label className="access-panel__label" htmlFor="access-sign-in-email">Email</label>
              <BeetleInput ref={emailInputRef} id="access-sign-in-email" name="email" type="email" value={signInEmail}
                onChange={(event) => handleDirectEmailChange(event.target.value)} placeholder="you@example.com"
                autoComplete="username" autoCapitalize="none" spellCheck={false} disabled={isValidating || resumeEmailSessionAfterInvite}
                error={!!emailValidationError} aria-describedby={emailValidationError ? 'access-invite-error' : 'access-invite-helper'} />
            </div>
            <div className="auth-entry-field">
              <label className="access-panel__label" htmlFor="access-invite-code">Invite code</label>
              <BeetleInput ref={inviteCodeInputRef} id="access-invite-code" name="invite" type="text" value={inviteCode}
                onChange={(event) => dispatchTransaction({ type: 'edit_invite', code: event.target.value })}
                placeholder="Invite code" error={!!error && !emailValidationError} disabled={isValidating}
                autoComplete="off" autoCapitalize="none" spellCheck={false}
                aria-describedby={error && !emailValidationError ? 'access-invite-helper access-invite-error' : 'access-invite-helper'} />
            </div>
            {error && <AuthNotice id="access-invite-error" tone="error">{error}</AuthNotice>}
            <BeetleButton type="submit" variant="primary" className="auth-entry-action" isLoading={isValidating} loadingLabel="Checking">
              {resumeEmailSessionAfterInvite ? 'Continue' : 'Send code'}
            </BeetleButton>
          </form>
          <p id="access-invite-helper" className="auth-entry-footer">Enter your invite code to continue.</p>
          <div className="auth-entry-sheet">
            <AuthNavigation icon={<Mail aria-hidden="true" />} onClick={handleRequestAccess}>Request access</AuthNavigation>
            <AuthNavigation icon={<LogIn aria-hidden="true" />} onClick={handleBackToEntry}>Sign in</AuthNavigation>
          </div>
        </>
      )}

      {stage === 'request_invite' && (
        <>
          <form noValidate className="auth-entry-sheet access-panel__form" onSubmit={handleWaitlistSubmit}>
            <div className="auth-entry-field">
              <label className="access-panel__label" htmlFor="access-waitlist-email">
                Email
              </label>
              <BeetleInput
                ref={requestEmailInputRef}
                id="access-waitlist-email"
                className="beetle-input"
                type="email"
                value={waitlistEmail}
                onChange={(e) => setWaitlistEmail(e.target.value)}
                placeholder="you@example.com"
                error={!!waitlistError}
                disabled={isJoiningWaitlist}
                autoComplete="email"
                autoCapitalize="none"
                aria-describedby={waitlistError
                  ? 'access-request-helper access-request-error'
                  : 'access-request-helper'}
              />
            </div>

            {waitlistError && (
              <AuthNotice id="access-request-error" role="alert" tone="error">
                {waitlistError}
              </AuthNotice>
            )}

            <BeetleButton
              type="submit"
              variant="primary"
              className="access-panel__full-action auth-entry-action"
              isLoading={isJoiningWaitlist}
              loadingLabel="Sending"
            >
              <span>Request invite</span>
            </BeetleButton>
          </form>
          <p id="access-request-helper" className="auth-entry-footer">Enter your email to join the alpha waitlist.</p>
        </>
      )}

      {stage === 'waitlist_submitted' && (
        <>
          <div className="auth-entry-sheet auth-entry-status">
            <h2 id="access-panel-title" className="access-panel__sr-title" aria-hidden="true">Request received</h2>
            <div className="auth-entry-fact"><Check aria-hidden="true" /><span>{waitlistSubmittedEmail}</span></div>
            <p className="auth-entry-footer">You are on the alpha waitlist.</p>
          </div>
          <div className="auth-entry-sheet">
            <AuthNavigation icon={<KeyRound aria-hidden="true" />} onClick={handleInviteEntry}>I have an invite</AuthNavigation>
            <AuthNavigation icon={<Mail aria-hidden="true" />} onClick={handleDifferentWaitlistEmail}>Use another email</AuthNavigation>
          </div>
        </>
      )}
    </AuthPanel>
  );
}
