import { useQuery } from '@tanstack/react-query';

import { api, type ThresholdResponse } from '../lib/api';
import { queryKeys } from '../lib/queryKeys';

export function useThresholdAuthority(ownerKey: string | null) {
  return useQuery<ThresholdResponse>({
    queryKey: queryKeys.threshold.authority(ownerKey ?? 'signed-out'),
    queryFn: () => api.getThreshold(),
    enabled: Boolean(ownerKey),
    retry: false,
    staleTime: 60_000,
    refetchInterval: (query) => (
      query.state.data?.sealingInProgress ? 5_000 : false
    ),
  });
}
