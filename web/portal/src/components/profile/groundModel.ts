import type {
  Climb,
  PublicRiderRideSummary,
  Ride,
  RideMedia,
  RoutePreview,
  RoutePreviewPoint,
  VaultPositionSummary,
} from '../../lib/api';

// The Profile — Ground model (Tim-ratified 2026-09-02). Pure functions that
// turn the API's climbs, leaderboard positions and rides into what the page
// draws: every canon climb on the ground by tier, the rider's photos, and
// the year's rides. Times are public, money is private — nothing economic
// enters this model.

export interface ProfileRide {
  id: string;
  title?: string;
  startedAt: string;
  distanceM?: number;
  elevationM?: number;
  durationS?: number;
  media?: RideMedia[];
  primaryMedia?: RideMedia | null;
}

export function rideFromOwn(ride: Ride): ProfileRide {
  return {
    id: ride.id,
    title: ride.title,
    startedAt: ride.startedAt,
    distanceM: ride.distanceM,
    elevationM: ride.elevationM,
    durationS: ride.durationS,
    media: ride.media,
    primaryMedia: ride.primaryMedia,
  };
}

export function rideFromPublic(ride: PublicRiderRideSummary): ProfileRide {
  return {
    id: ride.id,
    title: ride.title,
    startedAt: ride.startedAt || ride.createdAt || '',
    distanceM: ride.distanceM,
    elevationM: ride.elevationGainM,
    durationS: ride.durationSec,
    media: ride.media,
    primaryMedia: ride.primaryMedia,
  };
}

function rideTime(ride: ProfileRide): number {
  const time = new Date(ride.startedAt).getTime();
  return Number.isNaN(time) ? 0 : time;
}

export function sortRidesNewestFirst(rides: ProfileRide[]): ProfileRide[] {
  return [...rides].sort((a, b) => rideTime(b) - rideTime(a));
}

export function ridesThisYear(rides: ProfileRide[], now: Date = new Date()): ProfileRide[] {
  const year = now.getFullYear();
  return rides.filter((ride) => {
    const when = new Date(ride.startedAt);
    return !Number.isNaN(when.getTime()) && when.getFullYear() === year && when <= now;
  });
}

// ---- the ground ------------------------------------------------------

export type GroundTier = 'faint' | 'ridden' | 'seat' | 'crown';

export interface GroundClimb {
  climb: Climb;
  tier: GroundTier;
  position: VaultPositionSummary | null;
}

export function tierForPosition(position: VaultPositionSummary): GroundTier {
  if (position.isKom || position.rank === 1) return 'crown';
  if (position.rank >= 2 && position.rank <= 10) return 'seat';
  return 'ridden';
}

export function positionKind(position: VaultPositionSummary): 'Crown' | 'Seat' | null {
  const tier = tierForPosition(position);
  if (tier === 'crown') return 'Crown';
  if (tier === 'seat') return 'Seat';
  return null;
}

export function bestPositionsByVault(positions: VaultPositionSummary[] | undefined): Map<number, VaultPositionSummary> {
  const byVault = new Map<number, VaultPositionSummary>();
  for (const position of positions ?? []) {
    if (!Number.isFinite(position.vaultId) || !Number.isFinite(position.rank) || position.rank < 1) continue;
    const current = byVault.get(position.vaultId);
    if (!current || position.rank < current.rank) byVault.set(position.vaultId, position);
  }
  return byVault;
}

export function buildGround(climbs: Climb[], positions: VaultPositionSummary[] | undefined): GroundClimb[] {
  const byVault = bestPositionsByVault(positions);
  return climbs.map((climb) => {
    const position = climb.vaultId != null ? byVault.get(climb.vaultId) ?? null : null;
    return {
      climb,
      tier: position ? tierForPosition(position) : 'faint',
      position,
    };
  });
}

const isPoint = (point: RoutePreviewPoint | null | undefined): point is RoutePreviewPoint => (
  typeof point?.x === 'number' && Number.isFinite(point.x) && point.x >= 0 && point.x <= 1
  && typeof point?.y === 'number' && Number.isFinite(point.y) && point.y >= 0 && point.y <= 1
);

/**
 * A canon climb's centerline as [lat, lon] segments, projected from the
 * normalized route preview (x runs west→east, y runs north→south). Empty
 * when the preview is a fallback or carries no usable geometry.
 */
export function groundRouteSegments(preview: RoutePreview | null | undefined): Array<Array<[number, number]>> {
  const bounds = preview?.bounds;
  if (
    !preview
    || preview.fallbackReason
    || !bounds
    || !Number.isFinite(bounds.minLat) || !Number.isFinite(bounds.maxLat)
    || !Number.isFinite(bounds.minLon) || !Number.isFinite(bounds.maxLon)
    || bounds.maxLat < bounds.minLat || bounds.maxLon < bounds.minLon
  ) {
    return [];
  }
  const latSpan = bounds.maxLat - bounds.minLat;
  const lonSpan = bounds.maxLon - bounds.minLon;
  const rawSegments = (preview.segments && preview.segments.length > 0)
    ? preview.segments
    : (preview.points ? [preview.points] : []);
  return rawSegments
    .map((segment) => segment
      .filter(isPoint)
      .map((point): [number, number] => [bounds.maxLat - point.y * latSpan, bounds.minLon + point.x * lonSpan]))
    .filter((segment) => segment.length >= 2);
}

// ---- photos ----------------------------------------------------------

export interface ProfilePhoto {
  key: string;
  url: string;
  rideId: string;
  title?: string;
  startedAt: string;
  width?: number | null;
  height?: number | null;
}

export function collectPhotos(rides: ProfileRide[], limit = 5): ProfilePhoto[] {
  const seen = new Set<string>();
  const photos: ProfilePhoto[] = [];
  for (const ride of sortRidesNewestFirst(rides)) {
    const candidates = [ride.primaryMedia, ...(ride.media ?? [])]
      .filter((item): item is RideMedia => Boolean(item?.url))
      .sort((left, right) => {
        if (left.role === right.role) return left.sortOrder - right.sortOrder;
        return left.role === 'cover' ? -1 : 1;
      });
    for (const media of candidates) {
      const key = media.id || media.url || '';
      if (!key || seen.has(key)) continue;
      seen.add(key);
      photos.push({
        key,
        url: media.url as string,
        rideId: ride.id,
        title: ride.title,
        startedAt: ride.startedAt,
        width: media.width,
        height: media.height,
      });
      if (photos.length >= limit) return photos;
    }
  }
  return photos;
}
