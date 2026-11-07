export interface RiderIdentityFields {
  contractVersion?: string;
  id?: string | null;
  displayName?: string | null;
  username?: string | null;
  wallet?: string | null;
  avatarUrl?: string | null;
  isPublic?: boolean | null;
  viewerRelationship?: 'self' | 'following' | 'none' | 'blocked' | null;
}

function cleanText(value: string | null | undefined): string | null {
  if (typeof value !== 'string') return null;
  const trimmed = value.trim();
  return trimmed.length > 0 ? trimmed : null;
}

export function formatShortWallet(
  wallet: string | null | undefined,
  leading = 4,
  trailing = 4,
): string | null {
  const value = cleanText(wallet);
  if (!value) return null;
  if (value.length <= leading + trailing + 3) return value;
  return `${value.slice(0, leading)}...${value.slice(-trailing)}`;
}

export function formatUsername(username: string | null | undefined): string | null {
  const value = cleanText(username);
  if (!value) return null;
  const withoutAt = value.startsWith('@') ? value.slice(1).trim() : value;
  return withoutAt.length > 0 ? `@${withoutAt}` : null;
}

export function riderPrimaryLabel(
  identity: RiderIdentityFields | null | undefined,
  fallback = 'Rider',
): string {
  const displayName = cleanText(identity?.displayName);
  if (displayName) return displayName;

  const username = formatUsername(identity?.username);
  if (username) return username;

  const wallet = formatShortWallet(identity?.wallet);
  if (wallet) return `Rider ${wallet}`;

  return fallback;
}

export function riderPublicLabel(
  identity: RiderIdentityFields | null | undefined,
  fallback = 'Rider',
): string {
  const displayName = cleanText(identity?.displayName);
  if (displayName) return displayName;

  const username = formatUsername(identity?.username);
  if (username) return username;

  return fallback;
}

export function riderSecondaryLabel(
  identity: RiderIdentityFields | null | undefined,
  options: { includeWallet?: boolean } = {},
): string | null {
  const displayName = cleanText(identity?.displayName);
  const username = formatUsername(identity?.username);
  if (displayName && username) return username;

  if (options.includeWallet) {
    return formatShortWallet(identity?.wallet);
  }

  return null;
}

export function riderInitial(identity: RiderIdentityFields | null | undefined): string {
  const displayName = cleanText(identity?.displayName);
  if (displayName) return displayName.charAt(0).toUpperCase();

  const username = formatUsername(identity?.username);
  if (username) return username.replace(/^@/, '').charAt(0).toUpperCase();

  const wallet = cleanText(identity?.wallet);
  if (wallet) return wallet.charAt(0).toUpperCase();

  return 'R';
}
