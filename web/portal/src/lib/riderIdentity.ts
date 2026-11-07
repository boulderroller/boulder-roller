import type { SearchResult, User } from './api';
import { generateAnonName } from './anonNames';
import { formatInteger } from './formatters';

export type PortalProfileRank = 'C' | 'B' | 'A' | 'S' | 'SS';

type RiderIdentitySource = Pick<
  User,
  'id' | 'wallet' | 'username' | 'displayName' | 'beetleId' | 'beetleNumber' | 'rank'
> & {
  display_name?: string | null;
};

type PublicRiderSource = {
  id?: string | null;
  userId?: string | null;
  wallet?: string | null;
  username?: string | null;
  displayName?: string | null;
  display_name?: string | null;
};

export interface PortalRiderIdentity {
  displayName: string;
  handle: string | null;
  beetleIdLabel: string | null;
  beetleName: string;
  rank: PortalProfileRank;
}

export interface SearchRiderPresentation {
  displayName: string;
  subtitle: string;
  path: string;
}

const cleanText = (value: unknown): string | null => {
  if (typeof value !== 'string') return null;
  const trimmed = value.trim();
  return trimmed || null;
};

const normalizeBeetleNumber = (value: unknown): number | null => {
  if (typeof value === 'number' && Number.isFinite(value) && value > 0) {
    return Math.trunc(value);
  }

  if (typeof value !== 'string') return null;

  const digits = value.match(/\d+/g)?.join('');
  if (!digits) return null;

  const parsed = Number(digits);
  return Number.isFinite(parsed) && parsed > 0 ? Math.trunc(parsed) : null;
};

export const normalizeProfileRank = (rank: unknown): PortalProfileRank => {
  const normalized = cleanText(rank)?.toUpperCase();
  if (normalized === 'SS' || normalized === 'S' || normalized === 'A' || normalized === 'B' || normalized === 'C') {
    return normalized;
  }

  return 'C';
};

export const normalizeRiderHandle = (value: unknown, fallback?: string): string | null => {
  const normalized = cleanText(value)?.replace(/^@+/, '');
  if (normalized) return normalized;

  const fallbackHandle = cleanText(fallback)?.replace(/^@+/, '');
  return fallbackHandle || null;
};

export const getRiderInitials = (value: unknown, fallback = 'R'): string => {
  const normalized = cleanText(value)?.normalize('NFC');
  if (!normalized) return fallback;

  const parts = normalized
    .split(/[\s._-]+/)
    .map((part) => part.match(/[\p{L}\p{N}]/gu)?.join('') ?? '')
    .filter(Boolean);

  const firstCharacter = (part: string) => Array.from(part)[0] ?? '';

  if (parts.length > 1) {
    return `${firstCharacter(parts[0])}${firstCharacter(parts[1])}`.toUpperCase();
  }

  return parts[0] ? Array.from(parts[0]).slice(0, 2).join('').toUpperCase() : fallback;
};

export const getRiderHandle = (
  rider: Pick<RiderIdentitySource, 'id' | 'username' | 'displayName' | 'display_name'>,
  fallback?: string,
): string => {
  const generatedFallback = fallback ?? (rider.id ? `rider_${rider.id.slice(0, 6)}` : 'rider');
  return normalizeRiderHandle(rider.username ?? rider.displayName ?? rider.display_name, generatedFallback) ?? generatedFallback;
};

const getPublicRiderIdentifier = (rider: PublicRiderSource): string | null => {
  return normalizeRiderHandle(rider.username)
    ?? cleanText(rider.id)
    ?? cleanText(rider.userId)
    ?? cleanText(rider.wallet);
};

export const getPublicRiderPath = (rider: PublicRiderSource): string => {
  const identifier = getPublicRiderIdentifier(rider) ?? 'unknown';
  return `/rider/${encodeURIComponent(identifier)}`;
};

export const getPublicRiderDisplayName = (rider: PublicRiderSource): string => {
  const wallet = cleanText(rider.wallet);
  const userId = cleanText(rider.userId);
  const id = cleanText(rider.id);

  return cleanText(rider.displayName)
    ?? cleanText(rider.display_name)
    ?? normalizeRiderHandle(rider.username)
    ?? (wallet ? generateAnonName(wallet) : null)
    ?? (userId ? generateAnonName(userId) : null)
    ?? (id ? generateAnonName(id) : null)
    ?? 'Unknown rider';
};

const metadataText = (metadata: Record<string, unknown>, ...keys: string[]): string | null => {
  for (const key of keys) {
    const value = cleanText(metadata[key]);
    if (value) return value;
  }

  return null;
};

const extractSubtitleHandle = (subtitle: string): string | null => {
  return subtitle.match(/@([A-Za-z0-9_.-]+)/)?.[1] ?? null;
};

const looksWalletShaped = (value: string | null | undefined): boolean => {
  const compact = value?.replace(/[^A-Za-z0-9]/g, '') ?? '';
  return compact.length >= 24 && /\d/.test(compact) && /[A-Za-z]/.test(compact);
};

export const getSearchRiderPresentation = (
  result: Pick<SearchResult, 'type' | 'target' | 'title' | 'subtitle' | 'summary' | 'metadata'>,
): SearchRiderPresentation | null => {
  if (result.type !== 'rider') return null;

  const metadata = result.metadata ?? {};
  const username = normalizeRiderHandle(
    metadataText(metadata, 'username', 'handle') ?? extractSubtitleHandle(result.subtitle),
  );
  const displayName = metadataText(metadata, 'displayName', 'display_name', 'name')
    ?? (looksWalletShaped(result.title) ? null : result.title);
  const wallet = metadataText(metadata, 'wallet', 'walletAddress', 'wallet_address')
    ?? (looksWalletShaped(result.title) ? result.title : null);
  const rider = {
    id: result.target.id,
    userId: metadataText(metadata, 'userId', 'user_id', 'riderId', 'rider_id'),
    username,
    displayName,
    wallet,
  };
  const location = metadataText(metadata, 'location', 'city', 'homeLocation', 'home_location');
  const subtitleParts = [
    username ? `@${username}` : null,
    location && !looksWalletShaped(location) ? location : null,
  ].filter((item): item is string => Boolean(item));
  const fallbackSubtitle = result.summary && !looksWalletShaped(result.summary) ? result.summary : 'Public rider';

  return {
    displayName: getPublicRiderDisplayName(rider),
    subtitle: subtitleParts.length ? subtitleParts.join(' · ') : fallbackSubtitle,
    path: getPublicRiderPath(rider),
  };
};

const formatBeetleId = (value: unknown): string | null => {
  if (typeof value === 'number' && Number.isFinite(value) && value > 0) {
    return `BR-${Math.trunc(value)}`;
  }

  return cleanText(value);
};

export const getPortalRiderIdentity = (user: RiderIdentitySource | null | undefined): PortalRiderIdentity => {
  const beetleNumber = normalizeBeetleNumber(user?.beetleNumber) ?? normalizeBeetleNumber(user?.beetleId);
  const beetleIdLabel = formatBeetleId(user?.beetleId) ?? (beetleNumber ? `BR-${beetleNumber}` : null);
  const beetleName = beetleNumber ? `Beetle #${formatInteger(beetleNumber)}` : beetleIdLabel ?? 'Rider profile';
  const handle = user ? getRiderHandle(user, undefined) : null;
  const displayName = cleanText(user?.displayName) ?? cleanText(user?.username) ?? beetleName;

  return {
    displayName,
    handle,
    beetleIdLabel,
    beetleName,
    rank: normalizeProfileRank(user?.rank),
  };
};
