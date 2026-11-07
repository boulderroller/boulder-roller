import { useQuery } from '@tanstack/react-query';
import { api, ApiError, Ride } from '../../lib/api';
import { queryKeys } from '../../lib/queryKeys';

const DEFAULT_RIDE_LIMIT = 50;
const RIDE_PAGE_LIMIT = 100;

type RideQueryOptions = {
  limit?: number;
  enabled?: boolean;
};

function normalizeRideLimit(limit?: number): number {
  if (limit == null || !Number.isFinite(limit)) return DEFAULT_RIDE_LIMIT;
  return Math.max(1, Math.floor(limit));
}

async function fetchRidePages(limit: number): Promise<Ride[]> {
  const rides: Ride[] = [];
  const seenRideIds = new Set<string>();
  let offset = 0;

  while (rides.length < limit) {
    const pageLimit = Math.min(RIDE_PAGE_LIMIT, limit - rides.length);
    const page = await api.getRides({ limit: pageLimit, offset });

    if (!Array.isArray(page) || page.length > pageLimit) {
      throw new ApiError('Ride history response was invalid.', 'server_error', 502);
    }

    for (const ride of page) {
      if (!ride || typeof ride.id !== 'string' || seenRideIds.has(ride.id)) {
        throw new ApiError('Ride history could not be reconciled.', 'server_error', 502);
      }
      seenRideIds.add(ride.id);
      rides.push(ride);
    }

    if (page.length < pageLimit) break;
    offset += page.length;
  }

  return rides;
}

export function useRides(options?: RideQueryOptions) {
  const limit = normalizeRideLimit(options?.limit);

  return useQuery<Ride[]>({
    queryKey: queryKeys.rides.list(limit),
    queryFn: () => fetchRidePages(limit),
    enabled: options?.enabled ?? true,
  });
}
