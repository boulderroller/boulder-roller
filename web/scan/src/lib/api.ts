import type {
  AccountResolutionResponse,
  AccountResponse,
  ClimbResponse,
  IndexerHealthResponse,
  ObservatoryResponse,
  TransactionResponse,
  VaultResponse,
} from '@/types';

type ApiError = Error & { status?: number };

const API_BASE = (import.meta.env.VITE_SCAN_API_URL || '/api').replace(/\/$/, '');
const USE_FIXTURES = String(import.meta.env.VITE_USE_SCAN_FIXTURES || '').toLowerCase() === 'true';
const ALLOW_FIXTURE_FALLBACK =
  String(import.meta.env.VITE_ALLOW_FIXTURE_FALLBACK || '').toLowerCase() === 'true';

function createApiError(message: string, status?: number): ApiError {
  const error = new Error(message) as ApiError;
  if (status) error.status = status;
  return error;
}

async function fetchJson<T>(path: string, acceptedStatuses: number[] = []): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`);
  let payload: unknown = null;

  try {
    payload = await response.json();
  } catch {
    payload = null;
  }

  if (!response.ok && !acceptedStatuses.includes(response.status)) {
    const message =
      payload && typeof payload === 'object' && 'error' in payload
        ? String((payload as { error?: unknown }).error || 'Request failed')
        : 'Request failed';
    throw createApiError(message, response.status);
  }

  return payload as T;
}

async function fixtureForPath<T>(path: string): Promise<T> {
  const { fixtureAccount, fixtureClimb, fixtureObservatory, fixtureTransaction, fixtureVault } = await import('@/fixtures/data');
  if (path.startsWith('/v1/observatory')) return (path.includes('events_offset') ? {...fixtureObservatory, recent_events: [], events_next_offset: null} : fixtureObservatory) as T;
  if (path.startsWith('/v1/climbs/')) {
    return (await import('@/fixtures/climb-page')).fixtureClimbPage as T;
  }
  if (path.startsWith('/v1/vaults/')) return fixtureVault as T;
  if (path.startsWith('/v1/transactions/')) { const {transactionFixture}=await import('@/fixtures/transaction-page'); const receipt=transactionFixture(path.split('/').pop()!); if(!receipt)throw createApiError('Not found',404);return receipt as T; }
  if (path.startsWith('/v1/proofs/')) { if(path.endsWith('/'+ 'a'.repeat(64)))return {signature:'A'.repeat(88)} as T; throw createApiError('Not found',404); }
  if (path.startsWith('/v1/accounts/')) { const {accountFixture}=await import('@/fixtures/account-page'); return accountFixture(path.split('/').pop()!) as T; }
  if (path === '/v1/climbs') {
    return {
      climbs: fixtureObservatory.top_vaults,
      vaults: fixtureObservatory.top_vaults,
      total: fixtureObservatory.top_vaults.length,
    } as T;
  }
  if (path === '/v1/vaults') {
    return {
      vaults: fixtureObservatory.top_vaults,
      total: fixtureObservatory.top_vaults.length,
    } as T;
  }
  throw createApiError(`No fixture for ${path}`);
}

async function readApi<T>(path: string): Promise<T> {
  if (USE_FIXTURES) {
    return fixtureForPath<T>(path);
  }

  try {
    return await fetchJson<T>(path);
  } catch (error) {
    if (import.meta.env.DEV && ALLOW_FIXTURE_FALLBACK) {
      return fixtureForPath<T>(path);
    }
    throw error;
  }
}

export function getObservatory(offset = 0): Promise<ObservatoryResponse> {
  const path = `/v1/observatory${offset ? `?events_offset=${offset}` : ""}`;
  // Explicit fixtures are available for review; failed live reads never borrow their figures.
  return USE_FIXTURES ? Promise.resolve(fixtureForPath<ObservatoryResponse>(path)) : fetchJson<ObservatoryResponse>(path);
}

export function getVault(id: string): Promise<VaultResponse> {
  return readApi<VaultResponse>(`/v1/vaults/${id}`);
}

export function getClimb(id: string): Promise<ClimbResponse> {
  const path = `/v1/climbs/${encodeURIComponent(id)}`;
  return USE_FIXTURES ? fixtureForPath<ClimbResponse>(path) : fetchJson<ClimbResponse>(path);
}

export function getTransaction(signature: string): Promise<TransactionResponse> {
  const path=`/v1/transactions/${encodeURIComponent(signature)}`;
  return USE_FIXTURES ? fixtureForPath<TransactionResponse>(path) : fetchJson<TransactionResponse>(path);
}

export function getAccount(pubkey: string): Promise<AccountResponse> {
  const path=`/v1/accounts/${encodeURIComponent(pubkey)}`;
  return USE_FIXTURES ? fixtureForPath<AccountResponse>(path) : fetchJson<AccountResponse>(path);
}

export function getIndexerHealth(): Promise<IndexerHealthResponse> {
  if (USE_FIXTURES) return import('@/fixtures/data').then(({fixtureIndexerHealth}) => fixtureIndexerHealth);
  return fetchJson<IndexerHealthResponse>('/health', [503]);
}

export async function resolveUsernameAccount(username: string): Promise<AccountResolutionResponse> {
  const normalized = username.trim().replace(/^@/, '').toLowerCase();
  if (!normalized) {
    throw createApiError('Username is required.');
  }
  return fetchJson<AccountResolutionResponse>(
    `/v1/accounts/resolve?username=${encodeURIComponent(normalized)}`
  );
}

export function getProof(id:string):Promise<{signature:string}> {
 const path=`/v1/proofs/${encodeURIComponent(id)}`;
 return USE_FIXTURES ? fixtureForPath<{signature:string}>(path) : fetchJson<{signature:string}>(path);
}
