import dotenv from 'dotenv';
import fs from 'fs';
import path from 'path';

dotenv.config({ path: path.resolve(__dirname, '../.env') });

export type IndexerMode = 'snapshot' | 'stream' | 'replay';

const FALLBACK_PROGRAM_ID = 'EVjP2Vdz9buHNphywPhoybf213poa8EiSW6FGbXWFqYH';

type AddressRegistry = {
  programs?: {
    boulder_rollers?: string;
  };
  mints?: {
    dung_mint?: {
      address?: string;
    };
  };
};

function loadDevnetRegistry(): AddressRegistry {
  const candidates = [
    process.env.ADDRESS_REGISTRY_PATH,
    path.resolve(process.cwd(), 'protocol/anchor/addresses.devnet.json'),
    path.resolve(process.cwd(), '../protocol/anchor/addresses.devnet.json'),
    path.resolve(__dirname, '../../../protocol/anchor/addresses.devnet.json'),
  ].filter((candidate): candidate is string => Boolean(candidate));

  for (const candidate of candidates) {
    try {
      return JSON.parse(fs.readFileSync(candidate, 'utf8')) as AddressRegistry;
    } catch {
      continue;
    }
  }

  return {};
}

const devnetAddresses = loadDevnetRegistry();

function positiveIntegerEnv(name: string, fallback: number): number {
  const raw = process.env[name];
  if (!raw) return fallback;
  const parsed = Number(raw);
  if (!Number.isSafeInteger(parsed) || parsed <= 0) {
    throw new Error(`${name} must be a positive integer`);
  }
  return parsed;
}

function resolveIdlPath(): string {
  const candidates = [
    process.env.IDL_PATH,
    path.resolve(process.cwd(), 'protocol/anchor/idl/boulder_rollers.json'),
    path.resolve(process.cwd(), '../protocol/anchor/idl/boulder_rollers.json'),
    path.resolve(__dirname, '../../protocol/anchor/idl/boulder_rollers.json'),
    path.resolve(process.cwd(), 'protocol/anchor/target/idl/boulder_rollers.json'),
    path.resolve(process.cwd(), '../protocol/anchor/target/idl/boulder_rollers.json'),
    path.resolve(__dirname, '../../protocol/anchor/target/idl/boulder_rollers.json'),
  ].filter((candidate): candidate is string => Boolean(candidate));

  for (const candidate of candidates) {
    if (fs.existsSync(candidate)) {
      return candidate;
    }
  }

  return process.env.IDL_PATH || path.resolve(__dirname, '../../protocol/anchor/idl/boulder_rollers.json');
}

export const config = {
  // Solana
  programId: process.env.PROGRAM_ID || devnetAddresses.programs?.boulder_rollers || FALLBACK_PROGRAM_ID,
  dungMintAddress:
    process.env.DUNG_MINT_ADDRESS
    || devnetAddresses.mints?.dung_mint?.address
    || 'CqDFJWLpr49tB8xjHegy5JR5jwMCfmhicjuWawtKLeCk',
  rpcUrl: process.env.SOLANA_RPC_URL || 'https://api.devnet.solana.com',
  wsUrl: process.env.SOLANA_WS_URL || 'wss://api.devnet.solana.com',

  // Postgres
  databaseUrl: process.env.DATABASE_URL || '',

  // Indexer behavior
  mode: (process.env.INDEXER_MODE || 'snapshot') as IndexerMode,
  pollIntervalMs: parseInt(process.env.POLL_INTERVAL_MS || '30000', 10),
  reconciliationIntervalMs: parseInt(process.env.RECONCILIATION_INTERVAL_MS || '86400000', 10),
  dungSupplyRefreshIntervalMs: positiveIntegerEnv(
    'DUNG_SUPPLY_REFRESH_INTERVAL_MS',
    240_000
  ),

  // Health check
  healthPort: parseInt(process.env.HEALTH_PORT || '3001', 10),

  // Default to the committed IDL artifact rather than target/idl, which may
  // be stale or absent on deployed hosts.
  idlPath: resolveIdlPath(),
};

/** Endpoint for logs: origin only. RPC providers carry the API key in the path or query. */
export function redactEndpoint(url: string | undefined): string {
  if (!url) return '(NOT SET)';
  try {
    const parsed = new URL(url);
    return `${parsed.protocol}//${parsed.host}`;
  } catch {
    return '(unparseable endpoint)';
  }
}
