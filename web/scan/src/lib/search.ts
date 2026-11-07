export type SearchMatch =
  | { type: 'climb'; value: string }
  | { type: 'transaction'; value: string }
  | { type: 'account'; value: string }
  | { type: 'username'; value: string }
  | null;

const BASE58_RE = /^[1-9A-HJ-NP-Za-km-z]+$/;
const USERNAME_RE = /^@?[a-z0-9_]{3,20}$/i;

function unwrapExplorerPath(input: string): string {
  const value = input.trim();
  if (!value) return value;

  try {
    const parsed = new URL(value);
    return `${parsed.pathname}${parsed.search}`.trim();
  } catch {
    return value;
  }
}

function classifyRouteLikeValue(value: string): SearchMatch {
  const normalized = unwrapExplorerPath(value).replace(/\?.*$/, '').replace(/\/+$/, '');

  const vaultMatch = normalized.match(/^\/?(?:climb|climbs|vault|vaults)\/(\d+)$/i);
  if (vaultMatch) {
    return { type: 'climb', value: vaultMatch[1] };
  }

  const transactionMatch = normalized.match(/^\/?(?:tx|transaction|transactions)\/([1-9A-HJ-NP-Za-km-z]{43,90})$/i);
  if (transactionMatch) {
    return { type: 'transaction', value: transactionMatch[1] };
  }

  const accountMatch = normalized.match(/^\/?(?:account|accounts)\/([1-9A-HJ-NP-Za-km-z]{32,44})$/i);
  if (accountMatch) {
    return { type: 'account', value: accountMatch[1] };
  }

  return null;
}

function classifyPrefixedValue(value: string): SearchMatch {
  const vaultMatch = value.match(/^(?:vault|vaults|climb)\s*[:#/\- ]\s*(\d+)$/i);
  if (vaultMatch) {
    return { type: 'climb', value: vaultMatch[1] };
  }

  const transactionMatch = value.match(
    /^(?:tx|transaction|signature|sig)\s*[:#/\- ]\s*([1-9A-HJ-NP-Za-km-z]{43,90})$/i
  );
  if (transactionMatch) {
    return { type: 'transaction', value: transactionMatch[1] };
  }

  const accountMatch = value.match(
    /^(?:account|acct|address|wallet)\s*[:#/\- ]\s*([1-9A-HJ-NP-Za-km-z]{32,44})$/i
  );
  if (accountMatch) {
    return { type: 'account', value: accountMatch[1] };
  }

  const riderAccountMatch = value.match(/^rider\s*[:#/\- ]\s*([1-9A-HJ-NP-Za-km-z]{32,44})$/i);
  if (riderAccountMatch) {
    return { type: 'account', value: riderAccountMatch[1] };
  }

  const usernameMatch = value.match(/^(?:@|user\s*[:#/\- ]|username\s*[:#/\- ]|rider\s*[:#/\- ])([a-z0-9_]{3,20})$/i);
  if (usernameMatch) {
    return { type: 'username', value: usernameMatch[1].toLowerCase() };
  }

  return null;
}

export function classifySearchInput(input: string): SearchMatch {
  const value = input.trim();
  if (!value) return null;

  const routeLikeMatch = classifyRouteLikeValue(value);
  if (routeLikeMatch) return routeLikeMatch;

  const prefixedMatch = classifyPrefixedValue(value);
  if (prefixedMatch) return prefixedMatch;

  if (/^\d+$/.test(value)) {
    return { type: 'climb', value };
  }

  if (value.startsWith('#') && /^\d+$/.test(value.slice(1))) {
    return { type: 'climb', value: value.slice(1) };
  }

  if (USERNAME_RE.test(value)) {
    const normalized = value.replace(/^@/, '');
    if (!BASE58_RE.test(normalized) || normalized.length < 32 || normalized.length > 44) {
      return { type: 'username', value: normalized.toLowerCase() };
    }
  }

  if (!BASE58_RE.test(value)) {
    return null;
  }

  if (value.length > 44) {
    return { type: 'transaction', value };
  }

  if (value.length >= 32 && value.length <= 44) {
    return { type: 'account', value };
  }

  return null;
}

export function isUsernameSearch(match: SearchMatch): match is { type: 'username'; value: string } {
  return Boolean(match && match.type === 'username');
}

export function searchFailureMessage(error: unknown, match: SearchMatch): string {
  const status =
    error && typeof error === 'object' && 'status' in error
      ? Number((error as { status?: unknown }).status)
      : null;
  const message = error instanceof Error ? error.message : '';

  if (isUsernameSearch(match)) {
    const handle = `@${match.value}`;
    if (status === 404) return `No public rider found for ${handle}.`;
    if (status === 400) return 'Usernames can use 3-20 letters, numbers, or underscores.';
    return `Could not resolve ${handle}. Try a wallet address or check the rider name.`;
  }

  return message || 'Search failed. Try a climb id, account, transaction, or rider username.';
}

export function searchTarget(input: string): string | null {
  const match = classifySearchInput(input);
  if (!match || match.type === 'username') return null;
  if (match.type === 'climb') return `/climb/${match.value}`;
  if (match.type === 'transaction') return `/tx/${match.value}`;
  return `/account/${match.value}`;
}
