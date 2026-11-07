import { useQuery } from '@tanstack/react-query';
import { api, type LeaderboardResponse, type Climb } from '../../lib/api';
import { queryKeys } from '../../lib/queryKeys';

export function useClimbs(options?: { q?: string; bbox?: string; limit?: number; enabled?: boolean }) {
  const normalizedOptions = {
    q: options?.q?.trim() || undefined,
    bbox: options?.bbox || undefined,
    limit: options?.limit,
  };

  return useQuery<{ climbs: Climb[] }>({
    queryKey: queryKeys.climbs.list(normalizedOptions),
    placeholderData: undefined,
    queryFn: () => api.getClimbs(normalizedOptions),
    enabled: options?.enabled ?? true,
    staleTime: 5 * 60_000,
  });
}

export function useClimbDetail(climbId: string | undefined) {
  return useQuery<Climb | null>({
    queryKey: queryKeys.climbs.detail(climbId || ''),
    enabled: Boolean(climbId),
    staleTime: 5 * 60_000,
    placeholderData: undefined,
    queryFn: async () => {
      if (!climbId) return null;

      return api.getClimb(climbId);
    },
  });
}

export function useClimbLeaderboard(
  climbId: string | undefined,
  options?: { epochNumber?: number; limit?: number },
) {
  const epochNumber = options?.epochNumber ?? 1;
  const limit = options?.limit ?? 100;

  return useQuery<LeaderboardResponse>({
    queryKey: queryKeys.climbs.leaderboard(climbId || '', epochNumber, limit),
    enabled: Boolean(climbId),
    placeholderData: undefined,
    queryFn: () => api.getLeaderboard(climbId!, epochNumber, limit),
    staleTime: 60_000,
  });
}
