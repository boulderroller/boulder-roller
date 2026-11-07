import { useQuery } from '@tanstack/react-query';
import { api, Ride, RideStatus, PatternsResponse, TelemetryData, TilesResponse } from '../../lib/api';
import { queryKeys } from '../../lib/queryKeys';

export function useRide(id: string | undefined) {
  return useQuery<Ride>({
    queryKey: queryKeys.rides.detail(id!),
    queryFn: () => api.getRide(id!),
    enabled: !!id,
  });
}

export function useRideStatus(id: string | undefined) {
  return useQuery<RideStatus>({
    queryKey: queryKeys.rides.status(id!),
    queryFn: () => api.getRideStatus(id!),
    enabled: !!id,
    retry: false,
  });
}

export function useRidePatterns(id: string | undefined) {
  return useQuery<PatternsResponse>({
    queryKey: queryKeys.rides.patterns(id!),
    queryFn: () => api.getRidePatterns(id!),
    enabled: !!id,
    retry: false,
  });
}

export function useRideTelemetry(id: string | undefined, enabled: boolean = true) {
  return useQuery<TelemetryData>({
    queryKey: queryKeys.rides.telemetry(id!),
    queryFn: () => api.getRideTelemetry(id!, { includeGps: false }),
    enabled: !!id && enabled,
  });
}

export function useRideTiles(id: string | undefined, enabled: boolean = true) {
  return useQuery<TilesResponse>({
    queryKey: queryKeys.rides.tiles(id!),
    queryFn: () => api.getRideTiles(id!),
    enabled: !!id && enabled,
    retry: false,
  });
}

export function useRideGps(id: string | undefined, enabled: boolean = true) {
  return useQuery({
    queryKey: queryKeys.rides.gps(id!),
    queryFn: () => api.getRideGps(id!),
    enabled: !!id && enabled,
    retry: false,
  });
}
