import { useQuery } from '@tanstack/react-query';
import { api, type PublicPreview } from '../../lib/api';
import { queryKeys } from '../../lib/queryKeys';
import type { PublicPreviewRoute } from '../../lib/publicPreviewRoutes';

export function usePublicPreview(route: PublicPreviewRoute | null) {
  return useQuery<PublicPreview | null>({
    queryKey: queryKeys.publicPreview.detail(route?.type ?? 'ride', route?.id ?? '', route?.endpoint ?? ''),
    enabled: Boolean(route),
    staleTime: 0,
    gcTime: 0,
    refetchOnMount: 'always',
    refetchOnWindowFocus: 'always',
    placeholderData: undefined,
    retry: 1,
    queryFn: async () => {
      if (!route) return null;

      if (route.type === 'ride') {
        return api.getRidePublicPreview(route.id, route.endpoint === 'activities' ? 'activities' : 'rides');
      }

      if (route.type === 'climb') {
        return api.getClimbPublicPreview(route.id);
      }

      return api.getRiderPublicPreview(route.id);
    },
  });
}
