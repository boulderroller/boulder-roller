import { useQuery } from '@tanstack/react-query';
import { api, VaultsListResponse, VaultDetail, VaultStake, VaultLeaderboardResponse } from '../../lib/api';
import { queryKeys } from '../../lib/queryKeys';

export function useVaults(options?: { limit?: number; offset?: number; search?: string }) {
  const normalizedOptions = {
    limit: options?.limit,
    offset: options?.offset,
    search: options?.search?.trim() || undefined,
  };

  return useQuery<VaultsListResponse>({
    queryKey: queryKeys.vaults.list(normalizedOptions),
    placeholderData: undefined,
    queryFn: () => api.getVaults(normalizedOptions),
    staleTime: 60_000,
  });
}

export function useMyVaultStakes(enabled: boolean = true) {
  return useQuery<{ stakes: VaultStake[] }>({
    queryKey: queryKeys.vaults.myStakes,
    placeholderData: undefined,
    queryFn: () => api.getMyVaultStakes(),
    enabled,
    staleTime: 60_000,
  });
}

export function useVault(id: number | undefined) {
  return useQuery<VaultDetail>({
    queryKey: queryKeys.vaults.detail(id!),
    placeholderData: undefined,
    queryFn: () => api.getVault(id!),
    enabled: id != null,
  });
}

export function useVaultLeaderboard(id: number | undefined, enabled: boolean = true) {
  return useQuery<VaultLeaderboardResponse>({
    queryKey: queryKeys.vaults.leaderboard(id!),
    placeholderData: undefined,
    queryFn: () => api.getVaultLeaderboard(id!),
    retry: false,
    enabled: id != null && enabled,
    staleTime: 60_000,
  });
}
