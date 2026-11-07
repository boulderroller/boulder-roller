/**
 * Mobile Wallet Adapter (MWA) wallet service.
 *
 * Wraps @solana-mobile/mobile-wallet-adapter-protocol-web3js's transact()
 * for connect + sign flows. Android-only — MWA 2.0 spec defers iOS to a
 * future version; iOS today uses Phantom/Solflare universal-link
 * deeplinks (not wired in this module yet).
 *
 * Cluster pinned to devnet for the v1 demo. Memo Program transactions
 * are the cheapest way to demonstrate signing without preconditions on
 * the wallet's SOL balance.
 *
 * Per MOBILE_TRUTHS §2.5 + §10.2: the wallet surface is the rider's
 * Solana protocol identity. It is not the ride recorder, and it is
 * distinct from the authentication identity (which may be a Privy
 * embedded wallet or a SIWS-connected wallet). The MWA-connected
 * wallet may or may not match the auth wallet — callers surface that
 * distinction to the rider.
 */

import { Buffer } from 'buffer';
import { Platform } from 'react-native';
import {
  Connection,
  PublicKey,
  Transaction,
  TransactionInstruction,
} from '@solana/web3.js';

import { SOLANA_RPC_URL } from '../../constants/config';

/** Solana Memo Program v2. Stores arbitrary UTF-8 in a tx, free signers. */
const MEMO_PROGRAM_ID = new PublicKey(
  'MemoSq4gqABAXKb96qnH8TysNcWxMyWCqXgDLGmfcHr',
);

/** App identity surfaced to the wallet during the auth handshake. */
const APP_IDENTITY = {
  name: 'Boulder Roller',
  uri: 'https://boulderroller.xyz',
} as const;

const CLUSTER = 'devnet';

const MWA_ERROR = {
  WALLET_NOT_FOUND: 'ERROR_WALLET_NOT_FOUND',
  ASSOCIATION_CANCELLED: 'ERROR_ASSOCIATION_CANCELLED',
  SESSION_CLOSED: 'ERROR_SESSION_CLOSED',
  SESSION_TIMEOUT: 'ERROR_SESSION_TIMEOUT',
  AUTHORIZATION_FAILED: -1,
  NOT_SIGNED: -3,
} as const;

type MwaTransactWallet = {
  authorize(args: {
    cluster: typeof CLUSTER;
    identity: typeof APP_IDENTITY;
  }): Promise<{
    accounts: Array<{ address: string; label?: string }>;
  }>;
  signMessages(args: {
    addresses: string[];
    payloads: Uint8Array[];
  }): Promise<Uint8Array[]>;
  signAndSendTransactions(args: {
    transactions: Transaction[];
  }): Promise<string[]>;
};

type MwaTransact = <T>(
  callback: (wallet: MwaTransactWallet) => T | Promise<T>,
) => Promise<T>;

export class MwaUnsupportedError extends Error {
  constructor(message: string) {
    super(message);
    this.name = 'MwaUnsupportedError';
  }
}

export interface ConnectResult {
  /** Base58-encoded Solana public key. */
  publicKey: string;
  /** Wallet's self-reported display label, if provided during authorize. */
  walletLabel?: string;
}

export interface SignResult {
  /** Base58-encoded transaction signature. */
  signature: string;
  /** Solscan URL for the user / judge to verify on-chain. */
  solscanUrl: string;
  /** The public key that signed the memo (base58). Useful when the caller
   * needs to show which wallet produced the signature — e.g., to reassure
   * the rider that it matched their auth identity. */
  signer: string;
}

export interface AuthChallenge {
  nonce: string;
  message: string;
}

export interface AuthSignResult {
  nonce: string;
  signature: string;
  signer: string;
  walletLabel?: string;
}

/** Human-facing error kinds surfaced by {@link classifyMwaError}. */
export type MwaErrorKind =
  | 'unsupported_platform'
  | 'user_cancelled'
  | 'no_wallet'
  | 'session'
  | 'authorization'
  | 'unknown';

export interface ClassifiedMwaError {
  kind: MwaErrorKind;
  /** Copy suitable for a rider-facing alert or inline banner. */
  message: string;
  /** Raw cause preserved for Sentry / console. */
  cause?: unknown;
}

/**
 * True when the current platform can run MWA at all. iOS path (Phantom /
 * Solflare deeplinks) is deferred; when iOS lands, this returns true.
 */
export function isMwaSupported(): boolean {
  return Platform.OS === 'android';
}

function ensureSupported(): void {
  if (!isMwaSupported()) {
    throw new MwaUnsupportedError(
      'Mobile Wallet Adapter requires Android. iOS path (Phantom/Solflare ' +
        'deeplinks) is not wired yet.',
    );
  }
}

async function transactWithWallet<T>(
  callback: (wallet: MwaTransactWallet) => T | Promise<T>,
): Promise<T> {
  ensureSupported();
  const { transact } = require(
    '@solana-mobile/mobile-wallet-adapter-protocol-web3js'
  ) as { transact: MwaTransact };
  return transact(callback);
}

function addressToBase58(address: string): string {
  // ble-plx returns addresses as base64 strings; web3js PublicKey wants bytes.
  return new PublicKey(Buffer.from(address, 'base64')).toBase58();
}

const BASE58_ALPHABET = '123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz';

function encodeBase58(bytes: Uint8Array): string {
  if (bytes.length === 0) return '';

  const digits = [0];
  for (const byte of bytes) {
    let carry = byte;
    for (let i = 0; i < digits.length; i++) {
      const value = digits[i] * 256 + carry;
      digits[i] = value % 58;
      carry = Math.floor(value / 58);
    }
    while (carry > 0) {
      digits.push(carry % 58);
      carry = Math.floor(carry / 58);
    }
  }

  let leadingZeroes = 0;
  for (const byte of bytes) {
    if (byte !== 0) break;
    leadingZeroes++;
  }

  if (leadingZeroes === bytes.length) {
    return '1'.repeat(leadingZeroes);
  }

  return '1'.repeat(leadingZeroes) + digits.reverse().map((digit) => BASE58_ALPHABET[digit]).join('');
}

/**
 * Classify an arbitrary error from the MWA call stack into a rider-facing
 * kind + message. Never throws. Falls through to 'unknown' for anything
 * unrecognized — the caller displays the message and logs the raw cause.
 *
 * Keep this a pure function so it's trivially unit-testable without a
 * native bridge.
 */
export function classifyMwaError(err: unknown): ClassifiedMwaError {
  if (err instanceof MwaUnsupportedError) {
    return {
      kind: 'unsupported_platform',
      message: err.message,
      cause: err,
    };
  }

  const code = typeof err === 'object' && err !== null && 'code' in err
    ? (err as { code?: unknown }).code
    : undefined;

  if (code !== undefined) {
    switch (code) {
      case MWA_ERROR.WALLET_NOT_FOUND:
        return {
          kind: 'no_wallet',
          message:
            'No MWA-compatible wallet found on this device. Install Phantom, ' +
            'Solflare, or Backpack — or use a Seeker (Seed Vault is built in).',
          cause: err,
        };
      case MWA_ERROR.ASSOCIATION_CANCELLED:
      case MWA_ERROR.SESSION_CLOSED:
        return {
          kind: 'user_cancelled',
          message: 'Wallet connection cancelled.',
          cause: err,
        };
      case MWA_ERROR.SESSION_TIMEOUT:
        return {
          kind: 'session',
          message:
            'Wallet session timed out. Try again — keep the wallet app in ' +
            'the foreground when it opens.',
          cause: err,
        };
      case MWA_ERROR.AUTHORIZATION_FAILED:
        return {
          kind: 'authorization',
          message:
            'Wallet declined to authorize this app. Re-try and approve the ' +
            'connection prompt.',
          cause: err,
        };
      case MWA_ERROR.NOT_SIGNED:
        return {
          kind: 'user_cancelled',
          message: 'Transaction signing cancelled by wallet.',
          cause: err,
        };
      default:
        return {
          kind: 'unknown',
          message:
            err instanceof Error
              ? err.message
              : 'Wallet error. Check the console for details.',
          cause: err,
        };
    }
  }

  // Any string-matched hint as a last-ditch classifier. MWA throws plain
  // Errors from some code paths; the wire message is the only signal.
  if (err instanceof Error) {
    const m = err.message.toLowerCase();
    if (m.includes('cancel') || m.includes('dismiss') || m.includes('user reject')) {
      return { kind: 'user_cancelled', message: 'Cancelled.', cause: err };
    }
    if (m.includes('no wallet') || m.includes('wallet not found')) {
      return {
        kind: 'no_wallet',
        message:
          'No MWA-compatible wallet found on this device. Install Phantom, ' +
          'Solflare, or Backpack — or use a Seeker (Seed Vault is built in).',
        cause: err,
      };
    }
    return { kind: 'unknown', message: err.message, cause: err };
  }

  return {
    kind: 'unknown',
    message: 'Unknown wallet error.',
    cause: err,
  };
}

/**
 * Open MWA, run the auth handshake, return the user's pubkey. Throws
 * MwaUnsupportedError on iOS, and propagates the wallet's "user dismissed"
 * error if the user backs out. Callers that want a rider-facing message
 * should wrap the catch with {@link classifyMwaError}.
 */
export async function connectWallet(): Promise<ConnectResult> {
  const result = await transactWithWallet(async (wallet) => {
    return wallet.authorize({ cluster: CLUSTER, identity: APP_IDENTITY });
  });
  const account = result.accounts[0];
  return {
    publicKey: addressToBase58(account.address),
    walletLabel: account.label,
  };
}

/**
 * Run the mobile wallet SIWS flow for authentication:
 * authorize wallet -> fetch backend challenge for that wallet -> sign message.
 *
 * The backend owns nonce construction and message text. This wrapper only
 * ensures the wallet address used for nonce issuance is the same address that
 * signs the payload inside the MWA session.
 */
export async function signWalletAuthMessage(
  loadChallenge: (walletAddress: string) => Promise<AuthChallenge>,
): Promise<AuthSignResult> {
  return transactWithWallet(async (wallet) => {
    const auth = await wallet.authorize({
      cluster: CLUSTER,
      identity: APP_IDENTITY,
    });
    const account = auth.accounts[0];
    if (!account?.address) {
      throw new Error('Wallet did not return a Solana account.');
    }
    const signer = addressToBase58(account.address);
    const challenge = await loadChallenge(signer);
    const payload = new TextEncoder().encode(challenge.message);
    const signatures = await wallet.signMessages({
      addresses: [account.address],
      payloads: [payload],
    });
    const signature = signatures[0];
    if (!signature) {
      throw new Error('Wallet did not return a signature.');
    }

    return {
      nonce: challenge.nonce,
      signature: encodeBase58(signature),
      signer,
      walletLabel: account.label,
    };
  });
}

/**
 * Build a Memo Program transaction with the given message, sign and send
 * via MWA. Returns the signature, signer pubkey, and a Solscan link.
 *
 * The authorize call inside transact() is idempotent — if the rider has
 * already connected, the wallet reuses the existing auth token rather
 * than prompting again. This means "Sign Test Memo" works as a
 * self-contained demo without requiring a separate "Connect" tap.
 */
export async function signMemoTransaction(message: string): Promise<SignResult> {
  ensureSupported();
  const conn = new Connection(SOLANA_RPC_URL, 'confirmed');
  const { blockhash } = await conn.getLatestBlockhash();

  const { signature, signer } = await transactWithWallet(async (wallet) => {
    const auth = await wallet.authorize({
      cluster: CLUSTER,
      identity: APP_IDENTITY,
    });
    const account = auth.accounts[0];
    const pubkey = new PublicKey(Buffer.from(account.address, 'base64'));

    const tx = new Transaction().add(
      new TransactionInstruction({
        keys: [{ pubkey, isSigner: true, isWritable: false }],
        programId: MEMO_PROGRAM_ID,
        data: Buffer.from(message, 'utf8'),
      }),
    );
    tx.recentBlockhash = blockhash;
    tx.feePayer = pubkey;

    const signatures = await wallet.signAndSendTransactions({
      transactions: [tx],
    });
    // signAndSendTransactions returns base58-encoded signatures (per
    // @solana-mobile/mobile-wallet-adapter-protocol-web3js).
    return {
      signature: signatures[0],
      signer: pubkey.toBase58(),
    };
  });

  return {
    signature,
    signer,
    solscanUrl: `https://solscan.io/tx/${signature}?cluster=${CLUSTER}`,
  };
}
