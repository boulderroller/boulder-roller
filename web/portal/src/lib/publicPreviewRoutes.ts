export type PublicPreviewObjectType = 'ride' | 'climb' | 'rider';

export type PublicPreviewEndpoint = 'rides' | 'activities' | 'climbs' | 'riders';

export interface PublicPreviewRoute {
  type: PublicPreviewObjectType;
  id: string;
  endpoint: PublicPreviewEndpoint;
  canonicalPath: string;
  sourcePath: string;
  isCompatibilityPath: boolean;
}

const EXACT_OBJECT_PATH_RE = /^\/([^/?#]+)\/([^/?#]+)\/?$/;

function safeDecodePathSegment(value: string): string {
  try {
    return decodeURIComponent(value);
  } catch {
    return value;
  }
}

function encodePathSegment(value: string): string {
  return encodeURIComponent(value).replace(/%40/g, '@');
}

function normalizeRiderIdentifier(value: string): string {
  return value.replace(/^@+/, '').trim() || value;
}

export function getPublicPreviewRoute(pathname: string): PublicPreviewRoute | null {
  const match = pathname.match(EXACT_OBJECT_PATH_RE);
  if (!match) return null;

  const [, rawPrefix, rawId] = match;
  const prefix = rawPrefix.toLowerCase();
  const decodedId = safeDecodePathSegment(rawId).trim();
  if (!decodedId) return null;

  const encodedId = encodePathSegment(decodedId);
  const sourcePath = `/${prefix}/${rawId}`;

  if (prefix === 'activities') {
    return {
      type: 'ride',
      id: decodedId,
      endpoint: 'activities',
      canonicalPath: `/rides/${encodedId}`,
      sourcePath,
      isCompatibilityPath: true,
    };
  }

  if (prefix === 'rides' || prefix === 'ride') {
    return {
      type: 'ride',
      id: decodedId,
      endpoint: 'rides',
      canonicalPath: `/rides/${encodedId}`,
      sourcePath,
      isCompatibilityPath: prefix !== 'rides',
    };
  }

  if (prefix === 'climbs' || prefix === 'climb' || prefix === 'segments') {
    return {
      type: 'climb',
      id: decodedId,
      endpoint: 'climbs',
      canonicalPath: `/climbs/${encodedId}`,
      sourcePath,
      isCompatibilityPath: prefix !== 'climbs',
    };
  }

  if (prefix === 'riders' || prefix === 'rider' || prefix === 'athletes') {
    const riderId = normalizeRiderIdentifier(decodedId);
    return {
      type: 'rider',
      id: riderId,
      endpoint: 'riders',
      canonicalPath: `/riders/${encodePathSegment(riderId)}`,
      sourcePath,
      isCompatibilityPath: prefix !== 'riders',
    };
  }

  return null;
}

export function isPublicPreviewPath(pathname: string): boolean {
  return getPublicPreviewRoute(pathname) !== null;
}
