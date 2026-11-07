import { useInfiniteQuery, useQuery } from '@tanstack/react-query';
import { useAuth } from '../../contexts/AuthContext';
import { registerStage1TestMint } from '../../lib/stage1';
import { api } from '../../lib/api';

// These hooks mount only inside the live gate. Owner keys also separate accounts
// even during auth transitions; no previous-owner placeholder data is retained.
export function useStage1Owner(hill?: string, actionsEnabled = false) {
  const { user } = useAuth();
  const scope = ['stage1', user?.id, user?.wallet, hill ?? null];
  const registration = useQuery({ queryKey: [...scope, 'registration'], queryFn: () => api.getStage1Registration(hill), enabled: !!user, retry: false, staleTime: 0 });
  const pay = useStage1Payments('pay', hill);
  const dung = useStage1Payments('dung', hill);
  const pledges = useInfiniteQuery({
    queryKey: [...scope, 'pledges'], initialPageParam: 0,
    queryFn: ({ pageParam }) => api.getStage1Pledges(hill, pageParam), enabled: !!user, retry: false, staleTime: 0,
    getNextPageParam: (last, _pages, offset) => last.pledges.length === 50 ? offset + 50 : undefined,
  });
  const claims = useInfiniteQuery({ queryKey: [...scope, 'claims'], initialPageParam: 0,
    queryFn: ({ pageParam }) => api.getStage1Claims(pageParam), enabled: !!user && actionsEnabled, retry: false, staleTime: 0,
    getNextPageParam: last => last.nextOffset ?? undefined });
  return { registration, pay, dung, pledges, claims };
}

function useStage1Payments(kind: 'pay' | 'dung', hill?: string) {
  const { user } = useAuth();
  return useInfiniteQuery({
    queryKey: ['stage1', user?.id, user?.wallet, hill ?? null, kind], initialPageParam: 0,
    queryFn: ({ pageParam }) => api.getStage1Pay(kind, hill, pageParam), enabled: !!user, retry: false, staleTime: 0,
    getNextPageParam: (last, _pages, offset) => (last.hasMore ?? Math.max(last.paid.length, last.pending.length) === 50) ? offset + 50 : undefined,
  });
}

export function useStage1Mints(enabled: boolean) {
  return useQuery({ queryKey: ['stage1-mints'], enabled, retry: false, staleTime: 60_000,
    queryFn: async () => { const data = await api.get<{ testPoolMint: string | null }>('/stage1/mints', { skipAuth: true }); registerStage1TestMint(data.testPoolMint); return data; } });
}
