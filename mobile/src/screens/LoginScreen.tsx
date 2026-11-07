/**
 * LoginScreen — alpha flow
 *
 *   1. Email entry → the login provider sends a neutral one-time code.
 *   2. Existing riders sign in; refused signups recover into invite entry.
 *   3. Code entry → login provider resolves a rider wallet.
 *   4. The auth bridge exchanges the provider session for our backend session.
 *
 * The backend remains the authority that validates and consumes invites.
 */

import React, { useEffect, useRef, useState } from 'react';
import {
  View,
  Text,
  TextInput,
  TouchableOpacity,
  StyleSheet,
  ActivityIndicator,
  KeyboardAvoidingView,
  Platform,
  AccessibilityInfo,
} from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import { useLoginWithEmail, usePrivy } from '@privy-io/expo';

import { api } from '../lib/api';
import { useAuthStore } from '../stores/authStore';
import { AUTH_PHASES, type AuthPhase } from '../lib/authState';
import { loginWithExternalWallet } from '../services/authService';
import { classifyMwaError, isMwaSupported } from '../services/wallet/mwaWallet';

type Step = 'email' | 'code' | 'invite';
type ExchangeWaitState = 'normal' | 'slow' | 'stalled';

const SLOW_EXCHANGE_HELPER_MS = 6_000;
const STALLED_EXCHANGE_HELPER_MS = 15_000;
const CODE_FAILURE_AUTH_GRACE_MS = 300;
const PRIVY_NATIVE_APP_ID_MESSAGE = 'Sign-in is not enabled for this build.';

function getErrorCode(error: unknown): string | null {
  if (!error || typeof error !== 'object') return null;
  const coded = error as { code?: unknown; privyErrorCode?: unknown };
  if (typeof coded.code === 'string' && coded.code.trim()) return coded.code;
  if (typeof coded.privyErrorCode === 'string' && coded.privyErrorCode.trim()) {
    return coded.privyErrorCode;
  }
  return null;
}

function isSignupRefusedError(error: unknown): boolean {
  return getErrorCode(error) === 'allowlist_rejected';
}

function getEmailCodeFailureMessage(error: unknown): string {
  const code = getErrorCode(error);
  const message = error instanceof Error ? error.message : String(error);
  if (code === 'invalid_native_app_id' || message.includes('allowed app identifier')) {
    return PRIVY_NATIVE_APP_ID_MESSAGE;
  }
  return "Couldn't continue.";
}

function getWalletLoginFailure(error: unknown): { message: string; restartAtInvite: boolean; clearInvite: boolean } {
  const rawMessage = error instanceof Error ? error.message : String(error);
  if (rawMessage.includes('invite_required')) {
    return {
      message: 'Invite required.',
      restartAtInvite: true,
      clearInvite: true,
    };
  }
  if (rawMessage.includes('invite_invalid')) {
    return {
      message: 'That invite is not active.',
      restartAtInvite: true,
      clearInvite: true,
    };
  }
  if (rawMessage.includes('device_mismatch')) {
    return {
      message: 'Opened on another device.',
      restartAtInvite: false,
      clearInvite: false,
    };
  }
  if (rawMessage.includes('nonce')) {
    return {
      message: 'Challenge expired.',
      restartAtInvite: false,
      clearInvite: false,
    };
  }

  const walletError = classifyMwaError(error);
  return {
    message: walletError.message,
    restartAtInvite: false,
    clearInvite: false,
  };
}

export default function LoginScreen() {
  const [step, setStep] = useState<Step>('email');
  const [inviteCode, setInviteCode] = useState('');
  const [email, setEmail] = useState('');
  const [code, setCode] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [exchangeWaitState, setExchangeWaitState] = useState<ExchangeWaitState>('normal');
  const authStatus = useAuthStore((s) => s.status);
  const authError = useAuthStore((s) => s.authError);
  const authRecovery = useAuthStore((s) => s.authRecovery);
  const pendingInviteCode = useAuthStore((s) => s.pendingInviteCode);
  const sessionExchangeRequested = useAuthStore((s) => s.sessionExchangeRequested);
  const setPendingInviteCode = useAuthStore((s) => s.setPendingInviteCode);
  const clearPendingInviteCode = useAuthStore((s) => s.clearPendingInviteCode);
  const requestSessionExchange = useAuthStore((s) => s.requestSessionExchange);
  const clearSessionExchangeRequest = useAuthStore((s) => s.clearSessionExchangeRequest);
  const clearAuthError = useAuthStore((s) => s.clearAuthError);

  const { user: privyUser, isReady: privyReady, logout: privyLogout } = usePrivy();
  const privyAuthenticated = privyReady && privyUser !== null;
  const latestCodeAuthStateRef = useRef({ privyAuthenticated: false, authenticated: false });
  const codeFailureTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const inviteCodeInputRef = useRef<TextInput>(null);
  const previousStepRef = useRef<Step>(step);
  const activeSessionExchange = privyAuthenticated && sessionExchangeRequested;
  const activeInviteRecovery = authRecovery === 'invite_required' || authRecovery === 'invite_invalid';
  const inviteRequiredRecovery = authRecovery === 'invite_required';
  const stalePrivySession = privyAuthenticated && !sessionExchangeRequested && step === 'email' && !activeInviteRecovery;
  const visibleAuthError = inviteRequiredRecovery ? null : authError;
  const visibleError = error || visibleAuthError;
  const authPhase: AuthPhase = step === 'invite' || activeInviteRecovery
    ? AUTH_PHASES.inviteGate
    : authError || error
      ? AUTH_PHASES.recoverableError
      : activeSessionExchange
        ? AUTH_PHASES.sessionExchange
        : step === 'email'
          ? AUTH_PHASES.chooseAccessMethod
          : AUTH_PHASES.providerPending;
  const walletLoginSupported = isMwaSupported();

  const recoverToInviteEntry = () => {
    clearSessionExchangeRequest();
    clearPendingInviteCode();
    setInviteCode('');
    setCode('');
    setStep('invite');
    setError('Invite required to continue. Enter your invite code.');
    setBusy(false);
  };

  const scheduleInvalidCodeError = () => {
    if (codeFailureTimerRef.current) {
      clearTimeout(codeFailureTimerRef.current);
    }
    codeFailureTimerRef.current = setTimeout(() => {
      codeFailureTimerRef.current = null;
      const latest = latestCodeAuthStateRef.current;
      const storeState = useAuthStore.getState();
      if (latest.privyAuthenticated || latest.authenticated || storeState.status === 'authenticated') {
        setBusy(false);
        return;
      }
      clearSessionExchangeRequest();
      setError('Invalid or expired code');
      setBusy(false);
    }, CODE_FAILURE_AUTH_GRACE_MS);
  };

  const { sendCode, loginWithCode } = useLoginWithEmail();

  useEffect(() => {
    latestCodeAuthStateRef.current = {
      privyAuthenticated,
      authenticated: authStatus === 'authenticated',
    };
    if (!privyAuthenticated && authStatus !== 'authenticated') return;
    if (codeFailureTimerRef.current) {
      clearTimeout(codeFailureTimerRef.current);
      codeFailureTimerRef.current = null;
      setBusy(false);
    }
    setError((current) => (current === 'Invalid or expired code' ? null : current));
  }, [authStatus, privyAuthenticated]);

  useEffect(() => () => {
    if (codeFailureTimerRef.current) {
      clearTimeout(codeFailureTimerRef.current);
      codeFailureTimerRef.current = null;
    }
  }, []);

  useEffect(() => {
    const previousStep = previousStepRef.current;
    previousStepRef.current = step;
    if (step !== 'invite' || previousStep === 'invite') return;

    const focusTimer = setTimeout(() => {
      inviteCodeInputRef.current?.focus();
      AccessibilityInfo.announceForAccessibility(
        'Invite code. Enter your invite code to continue.',
      );
    }, 0);
    return () => clearTimeout(focusTimer);
  }, [step]);

  useEffect(() => {
    if (!authError) return;
    if (activeInviteRecovery) {
      setBusy(false);
      setCode('');
      setStep('invite');
      return;
    }
    if (privyAuthenticated) return;
    setBusy(false);
    setCode('');
    clearSessionExchangeRequest();
    setStep('email');
  }, [authError, activeInviteRecovery, privyAuthenticated, clearSessionExchangeRequest]);

  useEffect(() => {
    if (!activeSessionExchange) {
      setExchangeWaitState('normal');
      return undefined;
    }

    const slowTimer = setTimeout(() => setExchangeWaitState('slow'), SLOW_EXCHANGE_HELPER_MS);
    const stalledTimer = setTimeout(() => setExchangeWaitState('stalled'), STALLED_EXCHANGE_HELPER_MS);
    return () => {
      clearTimeout(slowTimer);
      clearTimeout(stalledTimer);
    };
  }, [activeSessionExchange]);

  const exchangeHelper =
    exchangeWaitState === 'stalled'
      ? 'Taking longer than usual.'
      : exchangeWaitState === 'slow'
        ? 'Still signing in.'
        : null;

  const resetPrivySession = async () => {
    setBusy(true);
    setError(null);
    clearAuthError();
    clearPendingInviteCode();
    clearSessionExchangeRequest();
    try {
      await privyLogout();
    } catch (err) {
      console.warn('[LoginScreen] Privy logout failed:', err);
    } finally {
      setCode('');
      setStep('email');
      setBusy(false);
    }
  };

  const sendEmailCode = async (normalizedEmail: string) => {
    await sendCode({ email: normalizedEmail });
    setStep('code');
  };

  const submitInvite = async () => {
    const normalizedInviteCode = inviteCode.trim();
    if (!normalizedInviteCode) {
      setError('Invite code required.');
      return;
    }
    const normalizedEmail = email.trim().toLowerCase();
    if (!privyAuthenticated && !normalizedEmail) {
      setStep('email');
      return;
    }
    setBusy(true);
    setError(null);
    clearAuthError();
    try {
      const inviteResult = await api.validateInviteCode(normalizedInviteCode);
      if (!inviteResult.valid) {
        clearPendingInviteCode();
        setError('That invite is not active.');
        return;
      }
      setPendingInviteCode(normalizedInviteCode);
      if (privyAuthenticated) {
        requestSessionExchange();
      } else {
        try {
          await sendEmailCode(normalizedEmail);
        } catch (err) {
          console.info('[LoginScreen] sendCode after invite error:', err);
          const message = getEmailCodeFailureMessage(err);
          setError(message === PRIVY_NATIVE_APP_ID_MESSAGE ? message : "Invite accepted. Couldn't send code.");
        }
      }
    } catch (err) {
      console.info('[LoginScreen] invite validation error:', err);
      clearPendingInviteCode();
      setError("Couldn't check invite.");
    } finally {
      setBusy(false);
    }
  };

  const submitWalletLogin = async () => {
    if (!walletLoginSupported) {
      setError('Wallet sign-in is Android-only.');
      return;
    }
    setBusy(true);
    setError(null);
    clearAuthError();
    try {
      await loginWithExternalWallet(pendingInviteCode ?? undefined);
      clearPendingInviteCode();
    } catch (err) {
      const failure = getWalletLoginFailure(err);
      if (failure.clearInvite) {
        clearPendingInviteCode();
      }
      setError(failure.message);
      setStep(failure.restartAtInvite ? 'invite' : 'email');
    } finally {
      setBusy(false);
    }
  };

  const submitEmail = async () => {
    const trimmed = email.trim().toLowerCase();
    if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(trimmed)) {
      setError('Invalid email.');
      return;
    }
    setBusy(true);
    setError(null);
    clearAuthError();
    clearPendingInviteCode();
    try {
      setEmail(trimmed);
      await sendEmailCode(trimmed);
    } catch (err) {
      console.info('[LoginScreen] send code error:', err);
      setError(getEmailCodeFailureMessage(err));
    } finally {
      setBusy(false);
    }
  };

  const submitCode = async () => {
    const trimmed = code.trim();
    if (trimmed.length < 4) {
      setError('Code required.');
      return;
    }
    setBusy(true);
    setError(null);
    clearAuthError();
    requestSessionExchange();
    let deferredCodeFailure = false;
    try {
      await loginWithCode({
        code: trimmed,
        email: email.trim().toLowerCase(),
      });
      // The auth bridge handles the backend session exchange.
    } catch (err) {
      console.info('[LoginScreen] loginWithCode error:', err);
      if (isSignupRefusedError(err) && !pendingInviteCode) {
        recoverToInviteEntry();
        return;
      }
      if (isSignupRefusedError(err)) {
        clearSessionExchangeRequest();
        setError('Account setup is unavailable. Try again.');
        setBusy(false);
        return;
      }
      deferredCodeFailure = true;
      scheduleInvalidCodeError();
    } finally {
      if (!deferredCodeFailure) {
        setBusy(false);
      }
    }
  };

  return (
    <SafeAreaView style={styles.container} testID={`auth-phase-${authPhase}`}>
      <KeyboardAvoidingView
        style={styles.content}
        behavior={Platform.OS === 'ios' ? 'padding' : 'height'}
      >
        <View style={styles.header}>
          <Text style={styles.title}>Boulder Roller</Text>
        </View>

        {activeSessionExchange ? (
          <View style={styles.form}>
            <ActivityIndicator color="#e5e5e5" style={{ marginBottom: 16 }} />
            <Text style={styles.label}>Signing in…</Text>
            {exchangeHelper && <Text style={styles.helper}>{exchangeHelper}</Text>}
            {exchangeWaitState === 'stalled' && (
              <TouchableOpacity
                style={[styles.button, styles.secondaryButton]}
                onPress={resetPrivySession}
                disabled={busy}
              >
                {busy ? (
                  <ActivityIndicator color="#e5e5e5" />
                ) : (
                  <Text style={styles.secondaryButtonText}>Start over</Text>
                )}
              </TouchableOpacity>
            )}
          </View>
        ) : (
          <>
        {step === 'invite' && (
          <View style={styles.form}>
            <Text style={styles.label}>Invite code</Text>
            <Text style={styles.helper}>
              {authRecovery === 'invite_invalid'
                ? 'Invite required.'
                : email
                  ? `Enter your invite code to continue with ${email}.`
                  : 'Invite required.'}
            </Text>
            <TextInput
              ref={inviteCodeInputRef}
              style={styles.input}
              value={inviteCode}
              onChangeText={setInviteCode}
              placeholder="Invite code"
              placeholderTextColor="#a3a3a3"
              autoCapitalize="none"
              autoCorrect={false}
              returnKeyType="go"
              onSubmitEditing={submitInvite}
              editable={!busy}
              accessibilityLabel="Invite code"
              accessibilityHint="Enter the invite code for this account"
            />
            <TouchableOpacity
              style={[styles.button, styles.primaryButton]}
              onPress={submitInvite}
              disabled={busy}
            >
              {busy ? (
                <ActivityIndicator color="#0a0a0a" />
              ) : (
                <Text style={styles.primaryButtonText}>Continue</Text>
              )}
            </TouchableOpacity>
            <TouchableOpacity
              style={styles.backLink}
              onPress={privyAuthenticated
                ? resetPrivySession
                : () => {
                    setStep('email');
                    setError(null);
                    clearAuthError();
                    clearPendingInviteCode();
                    clearSessionExchangeRequest();
                  }}
              disabled={busy}
            >
              <Text style={styles.backLinkText}>Use a different email</Text>
            </TouchableOpacity>
          </View>
        )}

        {step === 'email' && (
          <View style={styles.form}>
            <Text style={styles.label}>Email</Text>
            <TextInput
              style={styles.input}
              value={email}
              onChangeText={setEmail}
              placeholder="you@example.com"
              placeholderTextColor="#a3a3a3"
              autoCapitalize="none"
              autoCorrect={false}
              keyboardType="email-address"
              returnKeyType="go"
              onSubmitEditing={submitEmail}
              editable={!busy}
              accessibilityLabel="Email"
              accessibilityHint="Enter your email address"
            />
            <TouchableOpacity
              style={[styles.button, styles.primaryButton]}
              onPress={submitEmail}
              disabled={busy}
            >
              {busy ? <ActivityIndicator color="#0a0a0a" /> : <Text style={styles.primaryButtonText}>Continue</Text>}
            </TouchableOpacity>
            {walletLoginSupported && (
              <TouchableOpacity
                style={[styles.button, styles.secondaryButton]}
                onPress={submitWalletLogin}
                disabled={busy}
              >
                {busy ? (
                  <ActivityIndicator color="#e5e5e5" />
                ) : (
                  <Text style={styles.secondaryButtonText}>Use wallet</Text>
                )}
              </TouchableOpacity>
            )}
            {stalePrivySession && (
              <Text style={styles.helper}>Sign in again.</Text>
            )}
          </View>
        )}

        {step === 'code' && (
          <View style={styles.form}>
            <Text style={styles.label}>Code</Text>
            <Text style={styles.helper}>Sent to {email}</Text>
            <TextInput
              style={styles.input}
              value={code}
              onChangeText={setCode}
              placeholder="123456"
              placeholderTextColor="#a3a3a3"
              autoCapitalize="none"
              autoCorrect={false}
              keyboardType="number-pad"
              returnKeyType="go"
              onSubmitEditing={submitCode}
              editable={!busy}
              accessibilityLabel="Email code"
              accessibilityHint="Enter the code sent to your email address"
            />
            <TouchableOpacity
              style={[styles.button, styles.primaryButton]}
              onPress={submitCode}
              disabled={busy}
            >
              {busy ? <ActivityIndicator color="#0a0a0a" /> : <Text style={styles.primaryButtonText}>Continue</Text>}
            </TouchableOpacity>
            <TouchableOpacity
              style={styles.backLink}
              onPress={() => {
                setStep('email');
                setCode('');
                setError(null);
                clearAuthError();
                clearSessionExchangeRequest();
              }}
            >
              <Text style={styles.backLinkText}>Use a different email</Text>
            </TouchableOpacity>
          </View>
        )}
          </>
        )}

        {visibleError && (
          <View
            style={styles.errorContainer}
            accessibilityRole="alert"
            accessibilityLiveRegion="assertive"
          >
            <Text style={styles.errorText}>{visibleError}</Text>
          </View>
        )}

        <View style={styles.footer}>
          <Text style={styles.footerText}>Pre-alpha</Text>
        </View>
      </KeyboardAvoidingView>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: '#0a0a0a' },
  content: { flex: 1, paddingHorizontal: 24, justifyContent: 'center' },
  header: { marginBottom: 48, alignItems: 'center' },
  title: { fontSize: 32, fontWeight: '700', color: '#e5e5e5', letterSpacing: -0.5 },
  form: { gap: 12 },
  label: { fontSize: 13, fontWeight: '600', color: '#888', textTransform: 'uppercase', letterSpacing: 1, marginBottom: 4 },
  helper: { fontSize: 13, color: '#a3a3a3', marginBottom: 4 },
  input: {
    backgroundColor: '#1a1a1a',
    borderRadius: 10,
    borderWidth: 1,
    borderColor: '#333',
    paddingHorizontal: 16,
    paddingVertical: 14,
    fontSize: 16,
    color: '#e5e5e5',
  },
  button: { borderRadius: 10, paddingVertical: 16, alignItems: 'center', justifyContent: 'center', minHeight: 52 },
  primaryButton: { backgroundColor: '#e5e5e5' },
  primaryButtonText: { fontSize: 16, fontWeight: '600', color: '#0a0a0a' },
  secondaryButton: { backgroundColor: '#1a1a1a', borderWidth: 1, borderColor: '#333' },
  secondaryButtonText: { fontSize: 16, fontWeight: '600', color: '#e5e5e5' },
  disabledButton: { opacity: 0.45 },
  backLink: { alignItems: 'center', paddingVertical: 8 },
  backLinkText: { fontSize: 14, color: '#a3a3a3' },
  errorContainer: {
    marginTop: 16,
    paddingHorizontal: 16,
    paddingVertical: 12,
    backgroundColor: 'rgba(204, 68, 68, 0.1)',
    borderRadius: 8,
    borderWidth: 1,
    borderColor: 'rgba(204, 68, 68, 0.3)',
  },
  errorText: { fontSize: 14, color: '#ff8a8a', textAlign: 'center' },
  footer: { position: 'absolute', bottom: 24, left: 0, right: 0, alignItems: 'center' },
  footerText: { fontSize: 12, color: '#888' },
});
