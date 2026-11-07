import type { RideRow } from '../services/database';

export const ECONOMY_START_UNIX_SECONDS = 1_704_020_400;
export const ECONOMY_START_MS = ECONOMY_START_UNIX_SECONDS * 1000;
export const PRE_ECONOMY_REVIEW_REASON = 'activity_before_economy_start';

export function isPreEconomyTimestampMs(timestampMs: number | null | undefined): boolean {
  return typeof timestampMs === 'number' && Number.isFinite(timestampMs) && timestampMs < ECONOMY_START_MS;
}

export function rideCompletedAtMs(ride: Pick<RideRow, 'started_at' | 'ended_at' | 'duration_ms'>): number | null {
  if (typeof ride.ended_at === 'number' && Number.isFinite(ride.ended_at)) {
    return ride.ended_at;
  }
  if (
    typeof ride.started_at === 'number' &&
    Number.isFinite(ride.started_at) &&
    typeof ride.duration_ms === 'number' &&
    Number.isFinite(ride.duration_ms) &&
    ride.duration_ms > 0
  ) {
    return ride.started_at + ride.duration_ms;
  }
  return typeof ride.started_at === 'number' && Number.isFinite(ride.started_at)
    ? ride.started_at
    : null;
}

export function isPreEconomyRide(ride: Pick<RideRow, 'started_at' | 'ended_at' | 'duration_ms'>): boolean {
  return isPreEconomyTimestampMs(rideCompletedAtMs(ride));
}
