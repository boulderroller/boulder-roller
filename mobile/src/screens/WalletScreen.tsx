/**
 * WalletScreen — rider wallet approvals.
 *
 * This is the wallet approval surface. It is distinct from social rider
 * identity, but it can point at the same wallet behind login.
 *
 * Flows:
 *   1. Connect Wallet — MWA authorize handshake, displays pubkey
 *   2. Sign Test Memo — devnet Memo Program tx, signed via MWA,
 *      signature + Solscan link + copy-to-clipboard
 *
 * Android-only. On iOS the actions are disabled and the screen renders
 * a clear unsupported-platform note; the auth-identity section still
 * renders so the rider can see their own wallet regardless.
 */

import React, { useCallback, useState } from 'react';
import {
  View,
  Text,
  StyleSheet,
  TouchableOpacity,
  ActivityIndicator,
  ScrollView,
  Alert,
  Linking,
  SafeAreaView,
} from 'react-native';
import * as Clipboard from 'expo-clipboard';

import {
  connectWallet,
  signMemoTransaction,
  isMwaSupported,
  classifyMwaError,
  type ConnectResult,
  type SignResult,
  type MwaErrorKind,
} from '../services/wallet/mwaWallet';
import { isSeedVaultAvailable } from '../services/wallet/seedVaultWallet';
import { useAuthStore } from '../stores/authStore';
import { describeAuthAccessMethod } from '../lib/authState';
import { getCalBalance, type TokenBalance } from '../lib/chain';
import { useVerifiedValue } from '../lib/useVerifiedValue';
import { VerifyChip } from '../components/VerifyChip';

const TEST_MEMO_MESSAGE = 'Boulder Roller wallet check';

interface DisplayError {
  kind: MwaErrorKind;
  message: string;
}

export default function WalletScreen() {
  const [connected, setConnected] = useState<ConnectResult | null>(null);
  const [lastSignature, setLastSignature] = useState<SignResult | null>(null);
  const [busy, setBusy] = useState<'connect' | 'sign' | null>(null);
  const [error, setError] = useState<DisplayError | null>(null);
  const [seedVaultAvailable, setSeedVaultAvailable] = useState<boolean | null>(null);

  const authWallet = useAuthStore((s) => s.wallet);
  const accessMethod = useAuthStore((s) => s.accessMethod);

  const platformSupported = isMwaSupported();
  const identityMatches =
    connected && authWallet && connected.publicKey === authWallet;
  const fetchCalBalance = useCallback(async () => {
    if (!authWallet) return null;
    return getCalBalance(authWallet);
  }, [authWallet]);
  const calBalance = useVerifiedValue<TokenBalance>({
    key: authWallet ? `cal-balance:${authWallet}` : 'cal-balance:none',
    enabled: !!authWallet,
    fetchOnchain: fetchCalBalance,
  });

  React.useEffect(() => {
    let cancelled = false;
    isSeedVaultAvailable().then((available) => {
      if (!cancelled) setSeedVaultAvailable(available);
    });
    return () => {
      cancelled = true;
    };
  }, []);

  const handleConnect = async () => {
    setBusy('connect');
    setError(null);
    try {
      const result = await connectWallet();
      setConnected(result);
    } catch (e) {
      const classified = classifyMwaError(e);
      // Silent failures are a TRUTHS violation — log the cause even when we
      // soften the surface message to the rider.
      if (classified.kind === 'unknown') {
        console.warn('[WalletScreen] connect failed:', classified.cause);
      }
      setError({ kind: classified.kind, message: classified.message });
    } finally {
      setBusy(null);
    }
  };

  const handleSign = async () => {
    setBusy('sign');
    setError(null);
    try {
      const result = await signMemoTransaction(TEST_MEMO_MESSAGE);
      setLastSignature(result);
      // signMemoTransaction authorizes inline — once the sign succeeds, we
      // also have a confirmed connected pubkey. Reflect that in the UI so
      // the rider doesn't see a stale "not connected" state.
      if (!connected) {
        setConnected({ publicKey: result.signer });
      }
    } catch (e) {
      const classified = classifyMwaError(e);
      if (classified.kind === 'unknown') {
        console.warn('[WalletScreen] sign failed:', classified.cause);
      }
      setError({ kind: classified.kind, message: classified.message });
    } finally {
      setBusy(null);
    }
  };

  const handleOpenSolscan = (url: string) => {
    Linking.openURL(url).catch(() => {
      Alert.alert('Could not open transaction link');
    });
  };

  const handleCopySignature = async (signature: string) => {
    try {
      await Clipboard.setStringAsync(signature);
      Alert.alert('Copied', 'Signature copied to clipboard.');
    } catch {
      Alert.alert('Copy failed');
    }
  };

  return (
    <SafeAreaView style={styles.container}>
      <ScrollView contentContainerStyle={styles.scroll}>
        <Text style={styles.title}>Wallet</Text>
        <Text style={styles.subtitle}>
          Connect your rider wallet and view CAL.
        </Text>

        {!platformSupported && (
          <View style={styles.warningBox}>
            <Text style={styles.warningText}>
              Wallet signing is currently available on Android. iOS wallet
              support is not ready yet.
            </Text>
          </View>
        )}

        {error && (
          <View
            style={
              error.kind === 'user_cancelled'
                ? styles.infoBox
                : styles.errorBox
            }
          >
            <Text
              style={
                error.kind === 'user_cancelled'
                  ? styles.infoText
                  : styles.errorText
              }
            >
              {error.message}
            </Text>
          </View>
        )}

        {/* Account wallet resolved by the authenticated rider session. */}
        {authWallet && (
          <View style={styles.section}>
            <Text style={styles.sectionLabel}>Rider Wallet</Text>
            <View style={styles.row}>
              <Text style={styles.label}>{describeAuthAccessMethod(accessMethod)}</Text>
              <Text style={styles.mono}>{shortPubkey(authWallet)}</Text>
            </View>
            <View style={styles.row}>
              <View style={styles.balanceHeader}>
                <Text style={styles.label}>CAL Balance</Text>
                <VerifyChip state={calBalance.state} />
              </View>
              <Text style={styles.mono}>
                {formatCalBalance(calBalance.onchain, calBalance.state)}
              </Text>
              {calBalance.error && (
                <Text style={styles.helpText}>{calBalance.error}</Text>
              )}
            </View>
          </View>
        )}

        {/* Wallet used for signed actions. */}
        <View style={styles.section}>
          <Text style={styles.sectionLabel}>Signing Wallet</Text>
          {seedVaultAvailable === true && (
            <Text style={styles.helpText}>
              Secure signing is available on this device.
            </Text>
          )}
          {connected ? (
            <View style={styles.row}>
              <Text style={styles.label}>
                {connected.walletLabel ?? 'Connected'}
              </Text>
              <Text style={styles.mono}>{shortPubkey(connected.publicKey)}</Text>
              {authWallet && (
                <Text
                  style={
                    identityMatches ? styles.matchOk : styles.matchWarn
                  }
                >
                  {identityMatches
                    ? 'Matches your rider wallet.'
                    : 'Different from your rider wallet. Signed actions use this address.'}
                </Text>
              )}
            </View>
          ) : (
            <Text style={styles.empty}>Not connected.</Text>
          )}
          <TouchableOpacity
            style={[styles.button, !platformSupported && styles.buttonDisabled]}
            onPress={handleConnect}
            disabled={busy !== null || !platformSupported}
            accessibilityRole="button"
            accessibilityLabel={
              connected ? 'Reconnect wallet' : 'Connect wallet'
            }
          >
            {busy === 'connect' ? (
              <ActivityIndicator color="#0a0a0a" />
            ) : (
              <Text style={styles.buttonText}>
                {connected ? 'Reconnect Wallet' : 'Connect Wallet'}
              </Text>
            )}
          </TouchableOpacity>
        </View>

        {/* Signing check surface. */}
        <View style={styles.section}>
          <Text style={styles.sectionLabel}>Wallet Check</Text>
          <Text style={styles.helpText}>
            Confirms this wallet can sign for Boulder Roller. No funds move.
          </Text>
          <View style={styles.memoPreview}>
            <Text style={styles.memoLabel}>Check message</Text>
            <Text style={styles.mono}>{TEST_MEMO_MESSAGE}</Text>
          </View>
          {lastSignature && (
            <View style={styles.row}>
              <Text style={styles.label}>Last check</Text>
              <Text style={styles.mono} numberOfLines={1}>
                {lastSignature.signature.slice(0, 16)}…
              </Text>
              <View style={styles.linkRow}>
                <TouchableOpacity
                  onPress={() => handleCopySignature(lastSignature.signature)}
                  accessibilityRole="button"
                  accessibilityLabel="Copy wallet check"
                >
                  <Text style={styles.link}>Copy</Text>
                </TouchableOpacity>
                <TouchableOpacity
                  onPress={() => handleOpenSolscan(lastSignature.solscanUrl)}
                  accessibilityRole="button"
                  accessibilityLabel="View transaction"
                >
                  <Text style={styles.link}>View transaction ›</Text>
                </TouchableOpacity>
              </View>
            </View>
          )}
          <TouchableOpacity
            style={[
              styles.button,
              styles.secondaryButton,
              !platformSupported && styles.buttonDisabled,
            ]}
            onPress={handleSign}
            disabled={busy !== null || !platformSupported}
            accessibilityRole="button"
            accessibilityLabel="Run wallet approval check"
          >
            {busy === 'sign' ? (
              <ActivityIndicator color="#e5e5e5" />
            ) : (
              <Text style={styles.secondaryButtonText}>Run Wallet Check</Text>
            )}
          </TouchableOpacity>
        </View>
      </ScrollView>
    </SafeAreaView>
  );
}

function shortPubkey(pk: string): string {
  return `${pk.slice(0, 6)}…${pk.slice(-4)}`;
}

function formatCalBalance(
  balance: TokenBalance | null,
  state: 'unchecked' | 'checking' | 'verified' | 'diverged' | 'unavailable',
): string {
  if (balance) return `${balance.uiAmountString} CAL`;
  if (state === 'checking') return 'Checking chain...';
  if (state === 'unchecked') return 'Connect or sign in to check';
  return 'Unavailable';
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: '#0a0a0a' },
  scroll: { padding: 16, paddingBottom: 48 },
  title: {
    fontSize: 28,
    fontWeight: '700',
    color: '#e5e5e5',
    marginBottom: 6,
  },
  subtitle: {
    fontSize: 13,
    color: '#888',
    marginBottom: 24,
    lineHeight: 18,
  },
  warningBox: {
    backgroundColor: '#2a2210',
    borderColor: '#5a4a20',
    borderWidth: 1,
    borderRadius: 6,
    padding: 12,
    marginBottom: 16,
  },
  warningText: { color: '#e5d090', fontSize: 13 },
  errorBox: {
    backgroundColor: '#2a1010',
    borderColor: '#5a2020',
    borderWidth: 1,
    borderRadius: 6,
    padding: 12,
    marginBottom: 16,
  },
  errorText: { color: '#e5aaaa', fontSize: 13 },
  infoBox: {
    backgroundColor: '#1a1a1a',
    borderColor: '#333',
    borderWidth: 1,
    borderRadius: 6,
    padding: 12,
    marginBottom: 16,
  },
  infoText: { color: '#aaa', fontSize: 13 },
  section: { marginBottom: 28 },
  sectionLabel: {
    fontSize: 13,
    fontWeight: '600',
    color: '#999',
    textTransform: 'uppercase',
    letterSpacing: 1,
    marginBottom: 12,
  },
  row: {
    paddingVertical: 12,
    borderBottomColor: '#222',
    borderBottomWidth: StyleSheet.hairlineWidth,
    marginBottom: 12,
  },
  balanceHeader: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    gap: 12,
    marginBottom: 4,
  },
  label: { fontSize: 13, color: '#888', marginBottom: 4 },
  mono: { fontFamily: 'Courier', fontSize: 14, color: '#e5e5e5' },
  empty: { color: '#666', fontSize: 14, fontStyle: 'italic', paddingVertical: 12 },
  helpText: { fontSize: 13, color: '#888', marginBottom: 12, lineHeight: 18 },
  memoPreview: {
    backgroundColor: '#111',
    borderColor: '#222',
    borderWidth: 1,
    borderRadius: 6,
    padding: 12,
    marginBottom: 12,
  },
  memoLabel: {
    fontSize: 11,
    color: '#666',
    textTransform: 'uppercase',
    letterSpacing: 1,
    marginBottom: 6,
  },
  link: { color: '#c4a035', fontSize: 13, marginTop: 8, marginRight: 16 },
  linkRow: { flexDirection: 'row', alignItems: 'center' },
  matchOk: { fontSize: 12, color: '#6e9460', marginTop: 6, fontStyle: 'italic' },
  matchWarn: { fontSize: 12, color: '#c4a035', marginTop: 6, fontStyle: 'italic' },
  button: {
    backgroundColor: '#c4a035',
    paddingVertical: 14,
    borderRadius: 6,
    alignItems: 'center',
  },
  buttonText: { color: '#0a0a0a', fontSize: 15, fontWeight: '600' },
  secondaryButton: {
    backgroundColor: '#1a1a1a',
    borderColor: '#333',
    borderWidth: 1,
  },
  secondaryButtonText: { color: '#e5e5e5', fontSize: 15, fontWeight: '500' },
  buttonDisabled: { opacity: 0.4 },
});
