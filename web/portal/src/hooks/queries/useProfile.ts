import { useQuery } from '@tanstack/react-query';
import { api, User, UserLeaderboardSummaryResponse } from '../../lib/api';
import { queryKeys } from '../../lib/queryKeys';

export function useProfile() {
  return useQuery<User>({
    queryKey: queryKeys.profile.me,
    queryFn: () => api.getMe(),
  });
}

export function useMyLeaderboardPositions(enabled = true) {
  return useQuery<UserLeaderboardSummaryResponse>({
    queryKey: queryKeys.leaderboardPositions.mine(),
    queryFn: () => api.getMyLeaderboardPositions(),
    enabled,
    staleTime: 60_000,
  });
}

export function useUserLeaderboardPositions(wallet: string | null | undefined, enabled = true) {
  return useQuery<UserLeaderboardSummaryResponse>({
    queryKey: queryKeys.leaderboardPositions.user(wallet ?? ''),
    queryFn: () => api.getUserLeaderboardPositions(wallet as string),
    enabled: enabled && Boolean(wallet),
    staleTime: 60_000,
  });
}
