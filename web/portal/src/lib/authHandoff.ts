const AUTH_HANDOFF_KEY = 'br_auth_handoff';
const PENDING_INVITE_KEY = 'br_pending_invite_code';
const ACCESS_SIGN_IN_INTENT_KEY = 'br_access_sign_in_intent';
const PENDING_INVITE_TTL_MS = 15 * 60 * 1000;
const ACCESS_SIGN_IN_INTENT_TTL_MS = 15 * 60 * 1000;
const INVITE_ENTRY_PATH_RE = /^\/invite\/([^/?#]+)/i;

interface InviteLocationLike {
  pathname: string;
  search: string;
}

interface PendingInviteState {
  code: string;
  createdAt: number;
}

interface AccessSignInIntentState {
  createdAt: number;
}

type AuthenticatedAppLoader = () => Promise<unknown>;

let authenticatedAppLoader: AuthenticatedAppLoader | null = null;

export function registerAuthenticatedAppLoader(loader: AuthenticatedAppLoader) {
  authenticatedAppLoader = loader;
}

export async function ensureAuthenticatedAppLoaded() {
  await authenticatedAppLoader?.();
}

function normalizeInviteCode(value: string | null | undefined) {
  if (!value) return null;

  let decodedValue = value;
  try {
    decodedValue = decodeURIComponent(value);
  } catch {
    decodedValue = value;
  }

  const code = decodedValue.trim().toLowerCase();
  return code || null;
}

function withSessionStorage(action: (storage: Storage) => void) {
  if (typeof window === 'undefined') return;

  try {
    action(window.sessionStorage);
  } catch {
    // Ignore storage access failures in restrictive browsing environments.
  }
}

export function markAuthHandoffPending() {
  withSessionStorage((storage) => {
    storage.setItem(AUTH_HANDOFF_KEY, 'pending');
  });
}

export function hasAuthHandoffPending() {
  if (typeof window === 'undefined') return false;

  try {
    return window.sessionStorage.getItem(AUTH_HANDOFF_KEY) === 'pending';
  } catch {
    return false;
  }
}

export function clearAuthHandoffPending() {
  withSessionStorage((storage) => {
    storage.removeItem(AUTH_HANDOFF_KEY);
  });
}

export function markAccessSignInIntent() {
  withSessionStorage((storage) => {
    const state: AccessSignInIntentState = {
      createdAt: Date.now(),
    };
    storage.setItem(ACCESS_SIGN_IN_INTENT_KEY, JSON.stringify(state));
  });
}

export function hasAccessSignInIntent() {
  if (typeof window === 'undefined') return false;

  try {
    const raw = window.sessionStorage.getItem(ACCESS_SIGN_IN_INTENT_KEY);
    if (!raw) return false;

    const parsed = JSON.parse(raw) as Partial<AccessSignInIntentState>;
    if (typeof parsed.createdAt !== 'number') {
      window.sessionStorage.removeItem(ACCESS_SIGN_IN_INTENT_KEY);
      return false;
    }

    if (Date.now() - parsed.createdAt > ACCESS_SIGN_IN_INTENT_TTL_MS) {
      window.sessionStorage.removeItem(ACCESS_SIGN_IN_INTENT_KEY);
      return false;
    }

    return true;
  } catch {
    return false;
  }
}

export function clearAccessSignInIntent() {
  withSessionStorage((storage) => {
    storage.removeItem(ACCESS_SIGN_IN_INTENT_KEY);
  });
}

export function getInviteCodeFromLocation(location?: InviteLocationLike) {
  const pathname = location?.pathname ?? (typeof window !== 'undefined' ? window.location.pathname : '');
  const search = location?.search ?? (typeof window !== 'undefined' ? window.location.search : '');

  const pathMatch = pathname.match(INVITE_ENTRY_PATH_RE);
  if (pathMatch?.[1]) {
    return normalizeInviteCode(pathMatch[1]);
  }

  if (!search) return null;
  const params = new URLSearchParams(search);
  return normalizeInviteCode(params.get('invite') ?? params.get('invite_code'));
}

export function isInviteEntryLocation(location?: Pick<InviteLocationLike, 'pathname'>) {
  const pathname = location?.pathname ?? (typeof window !== 'undefined' ? window.location.pathname : '');
  return pathname === '/invite' || pathname.startsWith('/invite/');
}

export function setPendingInviteCode(code: string) {
  const trimmedCode = code.trim().toLowerCase();
  if (!trimmedCode) {
    clearPendingInviteCode();
    return;
  }

  withSessionStorage((storage) => {
    const state: PendingInviteState = {
      code: trimmedCode,
      createdAt: Date.now(),
    };
    storage.setItem(PENDING_INVITE_KEY, JSON.stringify(state));
  });
}

export function getPendingInviteCode() {
  if (typeof window === 'undefined') return null;

  try {
    const raw = window.sessionStorage.getItem(PENDING_INVITE_KEY);
    if (!raw) return null;

    const parsed = JSON.parse(raw) as Partial<PendingInviteState>;
    if (typeof parsed.code !== 'string' || typeof parsed.createdAt !== 'number') {
      window.sessionStorage.removeItem(PENDING_INVITE_KEY);
      return null;
    }

    if (Date.now() - parsed.createdAt > PENDING_INVITE_TTL_MS) {
      window.sessionStorage.removeItem(PENDING_INVITE_KEY);
      return null;
    }

    return parsed.code;
  } catch {
    return null;
  }
}

export function clearPendingInviteCode() {
  withSessionStorage((storage) => {
    storage.removeItem(PENDING_INVITE_KEY);
  });
}

// Validate both at the door and when consuming storage, which may be stale or tampered with.
export function normalizeReturnIntent(destination: string | null): string | null {
  if (!destination) return null;
  try {
    const url = new URL(destination, window.location.origin);
    if (
      url.origin !== window.location.origin
      || url.protocol !== window.location.protocol
      || url.username
      || url.password
      || url.pathname.startsWith('//')
    ) return null;
    if (url.pathname === '/' || url.pathname === '/onboarding') return null;
    return `${url.pathname}${url.search}${url.hash}`;
  } catch {
    return null;
  }
}

// Shared door/router write; callers retain their existing timing and storage-error policy.
export function storeReturnIntent(destination: string) {
  const returnUrl = normalizeReturnIntent(destination);
  if (returnUrl) sessionStorage.setItem('br_return_url', returnUrl);
  else sessionStorage.removeItem('br_return_url');
}
