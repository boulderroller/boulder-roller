import type { RiderIdentityFields } from './riderIdentity';

export interface RiderProfileRouteParams {
  identifier: string;
  initialIdentity: RiderIdentityFields;
  backLabel?: string;
}

interface RiderRouteOptions {
  backLabel?: string;
  allowWalletFallback?: boolean;
}

function cleanText(value: string | null | undefined): string | null {
  if (typeof value !== 'string') return null;
  const trimmed = value.trim();
  return trimmed.length > 0 ? trimmed : null;
}

function cleanUsername(value: string | null | undefined): string | null {
  const cleaned = cleanText(value);
  if (!cleaned) return null;
  return cleaned.startsWith('@') ? cleanText(cleaned.slice(1)) : cleaned;
}

export function publicRiderIdentity(
  identity: RiderIdentityFields | null | undefined,
): RiderIdentityFields {
  const publicIdentity: RiderIdentityFields = {
    id: cleanText(identity?.id),
    displayName: cleanText(identity?.displayName),
    username: cleanUsername(identity?.username),
    avatarUrl: cleanText(identity?.avatarUrl),
    isPublic: identity?.isPublic,
  };
  if (identity?.contractVersion) publicIdentity.contractVersion = identity.contractVersion;
  if (identity?.viewerRelationship) publicIdentity.viewerRelationship = identity.viewerRelationship;
  return publicIdentity;
}

export function riderRouteIdentifier(
  identity: RiderIdentityFields | null | undefined,
  options: { allowWalletFallback?: boolean } = {},
): string | null {
  const username = cleanUsername(identity?.username);
  if (username) return username;

  const id = cleanText(identity?.id);
  if (id) return id;

  if (options.allowWalletFallback) {
    return cleanText(identity?.wallet);
  }

  return null;
}

export function riderProfileRouteParams(
  identity: RiderIdentityFields | null | undefined,
  options: RiderRouteOptions = {},
): RiderProfileRouteParams | null {
  const initialIdentity = options.allowWalletFallback
    ? { ...publicRiderIdentity(identity), wallet: cleanText(identity?.wallet) }
    : publicRiderIdentity(identity);
  const identifier = riderRouteIdentifier(
    { ...identity, ...initialIdentity },
    { allowWalletFallback: options.allowWalletFallback },
  );

  if (!identifier) return null;

  return {
    identifier,
    initialIdentity,
    ...(options.backLabel ? { backLabel: options.backLabel } : {}),
  };
}

export function riderProfileRouteParamsFromIdentifier(
  identifier: string | null | undefined,
  identity: RiderIdentityFields | null | undefined = null,
  options: RiderRouteOptions = {},
): RiderProfileRouteParams | null {
  const cleaned = cleanText(identifier);
  if (!cleaned) return null;

  const route = riderProfileRouteParams(identity, options);
  if (route) return route;

  return {
    identifier: cleaned,
    initialIdentity: publicRiderIdentity(identity),
    ...(options.backLabel ? { backLabel: options.backLabel } : {}),
  };
}
