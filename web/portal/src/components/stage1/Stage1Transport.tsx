import { useInfiniteQuery } from '@tanstack/react-query';
import { useAuth } from '../../contexts/AuthContext';
import { api } from '../../lib/api';
import { stage1Copy as copy } from '../../lib/stage1Copy';
import Stage1Action from './Stage1Action';
import { StateRow } from '../portal/FailureSpecies';

export default function Stage1Transport({ surface }: { surface: 'climb' | 'portfolio' }) {
  const { user } = useAuth();
  const query = useInfiniteQuery({ queryKey: ['stage1', user?.id, user?.wallet, 'lookups'],
    queryFn: ({ pageParam }) => api.getStage1Lookups(pageParam), initialPageParam: 0,
    getNextPageParam: page => page.nextOffset ?? undefined,
    enabled: !!user, retry: false, staleTime: 15_000, refetchOnWindowFocus: false });
  const tables = query.data?.pages.flatMap(p => p.tables) ?? [];
  return <>{query.isError ? <StateRow title={copy.unavailable} action={<button onClick={() => void query.refetch()}>Try again</button>} /> : tables.map(t => {
    const mode = t.state === 'active' ? 'deactivate' : t.state === 'closeable' ? 'close' : null;
    return <div key={t.address}>{mode
      ? <Stage1Action key={`${t.address}:${mode}`} surface={surface} action="claim-transport" transport={{ action: 'claim-transport', request: { mode, lookupTable: t.address }, intent: { kind: 'stage1_claim_transport', mode, lookupTable: t.address } }} />
      : <StateRow title={`${copy.transport} · Pending`} action={<button onClick={() => void query.refetch()}>Try again</button>} />}</div>;
  })}{!query.isError && query.hasNextPage && <button disabled={query.isFetchingNextPage} onClick={() => void query.fetchNextPage()}>Load more</button>}</>;
}
