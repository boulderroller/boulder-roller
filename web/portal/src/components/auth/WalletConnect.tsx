import { useState, useCallback, useEffect, useMemo, useRef } from 'react';
import { useWallet } from '@solana/wallet-adapter-react';
import { WalletName } from '@solana/wallet-adapter-base';
import { useAuth } from '../../contexts/AuthContext';
import { api } from '../../lib/api';
import { formatAuthError } from '../../lib/auth-errors';
import { AUTH_PHASES, type AuthPhase } from '../../lib/authState';
import { getPendingInviteCode } from '../../lib/authHandoff';
import type { AuthTransactionMethod, AuthTransactionStage } from '../../lib/authTransaction';
import bs58 from 'bs58';
import { BeetleButton } from '../ui/beetle-button';
import { ChevronRight, ExternalLink, Wallet } from 'lucide-react';
import { AuthHeading, AuthNavigation, AuthNotice, AuthPanel, AuthStatus } from './AuthSurface';

interface WalletConnectProps {
  authTransactionId?: string;
  authTransactionMethod?: AuthTransactionMethod;
  authTransactionStage?: AuthTransactionStage;
  onSuccess: () => void;
  onBack: () => void;
}

type Step = 'select' | 'connecting' | 'signing' | 'verifying';

const PREFERRED_WALLET_ORDER = ['Phantom', 'Backpack', 'Solflare'] as const;
const PHANTOM_ADAPTER_SETTLE_MS = 1500;
const WALLET_CONNECT_TIMEOUT_MS = 20000;

function getWalletPriority(walletName: string) {
  const index = PREFERRED_WALLET_ORDER.indexOf(walletName as typeof PREFERRED_WALLET_ORDER[number]);
  return index === -1 ? Number.POSITIVE_INFINITY : index;
}

export default function WalletConnect({
  authTransactionId,
  authTransactionMethod,
  authTransactionStage,
  onSuccess,
  onBack,
}: WalletConnectProps) {
  const { wallets, select, connect, connecting, publicKey, signMessage, connected, disconnect, wallet } = useWallet();
  const { login } = useAuth();
  const [step, setStep] = useState<Step>('select');
  const [error, setError] = useState<string | null>(null);
  const [selectedWalletName, setSelectedWalletName] = useState<string | null>(null);
  const [showOtherWallets, setShowOtherWallets] = useState(false);
  const phantomFallbackTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const connectTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const attemptRef = useRef(0);

  const clearPhantomFallbackTimer = useCallback(() => {
    if (phantomFallbackTimerRef.current) {
      clearTimeout(phantomFallbackTimerRef.current);
      phantomFallbackTimerRef.current = null;
    }
  }, []);

  const clearConnectTimeout = useCallback(() => {
    if (connectTimeoutRef.current) {
      clearTimeout(connectTimeoutRef.current);
      connectTimeoutRef.current = null;
    }
  }, []);

  const clearProgressTimers = useCallback(() => {
    clearPhantomFallbackTimer();
    clearConnectTimeout();
  }, [clearConnectTimeout, clearPhantomFallbackTimer]);

  const isCurrentAttempt = useCallback((attempt: number) => attempt === attemptRef.current, []);

  // Filter to only installed/detected wallets
  const detectedWallets = useMemo(
    () => wallets
      .filter((candidate) => candidate.readyState === 'Installed' || candidate.readyState === 'Loadable')
      .sort((left, right) => {
        const priorityDelta = getWalletPriority(left.adapter.name) - getWalletPriority(right.adapter.name);
        if (priorityDelta !== 0) return priorityDelta;
        return left.adapter.name.localeCompare(right.adapter.name);
      }),
    [wallets],
  );
  const recommendedWallets = detectedWallets.filter((candidate) => getWalletPriority(candidate.adapter.name) !== Number.POSITIVE_INFINITY);
  const otherDetectedWallets = detectedWallets.filter((candidate) => getWalletPriority(candidate.adapter.name) === Number.POSITIVE_INFINITY);
  const activeWalletName = wallet?.adapter.name ?? selectedWalletName;
  const activeWallet = detectedWallets.find((candidate) => candidate.adapter.name === activeWalletName);
  const authPhase: AuthPhase = error
    ? AUTH_PHASES.recoverableError
    : step === 'select'
      ? AUTH_PHASES.chooseAccessMethod
      : step === 'verifying'
        ? AUTH_PHASES.sessionExchange
        : AUTH_PHASES.providerPending;

  // Define handleSignIn BEFORE the useEffects that reference it
  const handleSignIn = useCallback(async () => {
    const attempt = attemptRef.current;
    if (!publicKey || !signMessage) {
      if (!isCurrentAttempt(attempt)) return;
      setError('Selected wallet cannot sign messages. Choose another wallet to continue.');
      await disconnect();
      setSelectedWalletName(null);
      setStep('select');
      return;
    }

    const walletAddress = publicKey.toBase58();

    try {
      // 1. Get nonce and message from backend
      const { nonce, message } = await api.getNonce(walletAddress);

      // 2. Encode the backend's SIWS message for signing
      const encodedMessage = new TextEncoder().encode(message);

      // 3. Sign with wallet
      const signatureBytes = await signMessage(encodedMessage);
      if (!isCurrentAttempt(attempt)) return;
      const signature = bs58.encode(signatureBytes);
      setStep('verifying');

      // 4. Verify with backend and get JWT
      const inviteCode = getPendingInviteCode() ?? undefined;
      await login(walletAddress, signature, nonce, inviteCode);
      if (!isCurrentAttempt(attempt)) return;

      // 5. Success!
      clearProgressTimers();
      onSuccess();
    } catch (err) {
      if (!isCurrentAttempt(attempt)) return;
      clearProgressTimers();
      setError(formatAuthError(err));
      await disconnect();
      setSelectedWalletName(null);
      setStep('select');
    }
  }, [clearProgressTimers, disconnect, isCurrentAttempt, login, onSuccess, publicKey, signMessage]);


  // When wallet is selected but not connected, try to connect
  useEffect(() => {
    if (wallet && !connected && !connecting && step === 'connecting') {
      const attempt = attemptRef.current;
      connect().catch(async () => {
        if (!isCurrentAttempt(attempt)) return;
        // Fallback: try direct Phantom connection if available
        const phantomProvider = (window as unknown as { phantom?: { solana?: { connect: () => Promise<{ publicKey: { toString: () => string } }> } } }).phantom?.solana;
        if (phantomProvider && wallet.adapter.name === 'Phantom') {
          try {
            await phantomProvider.connect();
            if (!isCurrentAttempt(attempt)) return;
            clearPhantomFallbackTimer();
            phantomFallbackTimerRef.current = setTimeout(() => {
              if (!isCurrentAttempt(attempt)) return;
              setStep((currentStep) => {
                if (currentStep !== 'connecting') return currentStep;
                setError('Phantom approved, but connection did not finish.');
                setSelectedWalletName(null);
                void disconnect();
                return 'select';
              });
            }, PHANTOM_ADAPTER_SETTLE_MS);
            return;
          } catch {
            // Direct Phantom connection also failed
          }
        }

        if (!isCurrentAttempt(attempt)) return;
        setError('Wallet did not connect.');
        setSelectedWalletName(null);
        setStep('select');
      });
    }
  }, [wallet, connected, connecting, step, connect, clearPhantomFallbackTimer, disconnect, isCurrentAttempt]);

  useEffect(() => {
    clearConnectTimeout();
    if (step !== 'connecting') return undefined;

    const attempt = attemptRef.current;
    connectTimeoutRef.current = setTimeout(() => {
      if (!isCurrentAttempt(attempt)) return;
      clearPhantomFallbackTimer();
      setError('Wallet did not respond.');
      setSelectedWalletName(null);
      setStep('select');
      void disconnect();
    }, WALLET_CONNECT_TIMEOUT_MS);

    return clearConnectTimeout;
  }, [clearConnectTimeout, clearPhantomFallbackTimer, disconnect, isCurrentAttempt, step]);

  // When connected, start sign-in flow
  useEffect(() => {
    if (connected && publicKey && step === 'connecting') {
      clearProgressTimers();
      setStep('signing');
      handleSignIn();
    }
  }, [connected, publicKey, step, handleSignIn, clearProgressTimers]);

  useEffect(() => () => {
    attemptRef.current += 1;
    clearProgressTimers();
  }, [clearProgressTimers]);

  const handleSelectWallet = (walletName: string) => {
    attemptRef.current += 1;
    clearProgressTimers();
    setError(null);
    setSelectedWalletName(walletName);
    setStep('connecting');

    try {
      select(walletName as WalletName);
    } catch {
      setError('Failed to select wallet');
      setSelectedWalletName(null);
      setStep('select');
    }
  };

  const handleClose = () => {
    attemptRef.current += 1;
    clearProgressTimers();
    setSelectedWalletName(null);
    void disconnect();
    onBack();
  };

  const handleCancelProgress = () => {
    attemptRef.current += 1;
    clearProgressTimers();
    setError(null);
    setSelectedWalletName(null);
    setStep('select');
    void disconnect();
  };

  const statusTitle = step === 'connecting' ? 'Approve wallet connection'
    : step === 'signing' ? 'Sign login message' : 'Opening account session';
  const statusBody = step === 'connecting' ? 'Approve the browser prompt so Boulder Roller can check account access.'
    : step === 'signing' ? 'This proves wallet ownership for account access only.'
    : 'Checking account access and opening your session.';

  return (
    <AuthPanel role="region" titleId="wallet-connect-title" className="wallet-connect-inline"
      bodyClassName="wallet-connect-modal__body"
      header={<AuthHeading title="Use your wallet" onBack={handleClose} />}
      data-auth-phase={authPhase} data-auth-transaction-id={authTransactionId}
      data-auth-transaction-stage={authTransactionStage} data-auth-transaction-method={authTransactionMethod ?? ''}
      data-auth-step={step} data-auth-recovery={error ? 'wallet_connect' : ''}>
      <h2 id="wallet-connect-title" className="access-panel__sr-title">Use your wallet</h2>
      <AuthStatus>{step === 'select' ? '' : statusTitle}</AuthStatus>
      {step === 'select' ? (
        <>
          <div className="auth-entry-sheet">
            {error && <AuthNotice tone="error">{error}</AuthNotice>}
            <div role="group" aria-label="Detected Solana wallets">
              {recommendedWallets.length > 0 ? recommendedWallets.map((candidate) => (
                <AuthNavigation key={candidate.adapter.name} className="wallet-connect-card"
                  icon={<img src={candidate.adapter.icon} alt="" className="auth-entry-wallet-icon" />}
                  onClick={() => handleSelectWallet(candidate.adapter.name)}>
                  {candidate.adapter.name}
                </AuthNavigation>
              )) : (
                <>
                  <div className="auth-entry-status">No Solana wallet detected yet</div>
                  {[['Phantom', 'https://phantom.app/'], ['Solflare', 'https://solflare.com/'], ['Backpack', 'https://backpack.app/']].map(([name, href]) => (
                    <a key={href} className="auth-entry-row" href={href} target="_blank" rel="noopener noreferrer">
                      <ExternalLink aria-hidden="true" /><span className="auth-entry-row__copy">{name}</span><ChevronRight className="auth-entry-chevron" aria-hidden="true" />
                    </a>
                  ))}
                  <BeetleButton type="button" className="auth-entry-action" onClick={() => window.location.reload()}>Refresh after installing</BeetleButton>
                </>
              )}
            </div>
          </div>
          <p className="auth-entry-footer">This verifies wallet ownership for account access only. CAL and custody actions stay separate.</p>
          {otherDetectedWallets.length > 0 && (
            <>
              <div className="auth-entry-sheet">
                <AuthNavigation onClick={() => setShowOtherWallets((current) => !current)} aria-expanded={showOtherWallets}>
                  {showOtherWallets ? 'Hide other detected extensions' : 'Show other detected extensions'}
                </AuthNavigation>
                {showOtherWallets && otherDetectedWallets.map((candidate) => (
                  <AuthNavigation key={candidate.adapter.name} icon={<img src={candidate.adapter.icon} alt="" className="auth-entry-wallet-icon" />}
                    onClick={() => handleSelectWallet(candidate.adapter.name)} helper="Detected in your browser. Continue only if it supports Solana signing.">
                    {candidate.adapter.name}
                  </AuthNavigation>
                ))}
              </div>
              <p className="auth-entry-footer">Boulder Roller is tuned for native Solana wallets first. Use these only if you know they support Solana signing in your browser.</p>
            </>
          )}
        </>
      ) : (
        <>
          <div className="auth-entry-sheet">
            <div className="auth-entry-fact"><Wallet aria-hidden="true" /><span>{activeWallet?.adapter.name ?? selectedWalletName}</span></div>
            <div className="auth-entry-status"><p>{statusTitle}</p><p id="wallet-connect-status" className="auth-entry-copy">{statusBody}</p></div>
            <button type="button" className="auth-entry-row auth-entry-cancel" onClick={handleCancelProgress}>Cancel</button>
          </div>
          <p className="auth-entry-footer">If the prompt opened elsewhere, finish it there. Otherwise cancel and try another wallet.</p>
        </>
      )}
    </AuthPanel>
  );
}
