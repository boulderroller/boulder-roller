import { useQuery } from '@tanstack/react-query';
import { api, Portfolio, PortfolioSnapshot } from '../../lib/api';
import { compareBaseUnits } from '../../lib/tokenAmounts';
import { queryKeys } from '../../lib/queryKeys';

export function usePortfolio(enabled: boolean = true) {
  return useQuery<Portfolio>({
    queryKey: queryKeys.portfolio.all,
    placeholderData: undefined,
    queryFn: () => api.getPortfolio(),
    enabled,
  });
}

export function usePortfolioSnapshot(enabled: boolean = true) {
  return useQuery<PortfolioSnapshot>({
    queryKey: queryKeys.portfolio.snapshot,
    placeholderData: undefined,
    queryFn: () => api.getPortfolioSnapshot({ limit: 50, offset: 0 }),
    enabled,
    staleTime: 15_000,
  });
}

export function useCALBalance(enabled: boolean = true) {
  return useQuery({
    queryKey: queryKeys.portfolio.cal,
    placeholderData: undefined,
    queryFn: () => api.getCALBalance(),
    enabled,
  });
}

export function useDistributions(options?: { limit?: number; offset?: number }, enabled: boolean = true) {
  return useQuery({
    queryKey: queryKeys.portfolio.distributions,
    placeholderData: undefined,
    queryFn: () => api.getMyDistributions(options ?? { limit: 50, offset: 0 }),
    enabled,
  });
}

/** One producer revision supplies both readiness rows and its complete total. */
export function collectionReadModel(snapshot: PortfolioSnapshot | null) {
  const outer = snapshot?.collectionSnapshot;
  const inner = snapshot?.portfolio?.collectionSnapshot;
  const source = outer ?? inner;
  const rows = new Map<number, string | null>();
  const exact = (value: unknown): value is string => {
    if (typeof value !== 'string') return false;
    try { compareBaseUnits(value, '0'); return true; } catch { return false; }
  };
  if (!source || !Array.isArray(source.positions)) return { rows, total: null, supplied: Boolean(source) };
  const coherent = Boolean(typeof source.revision === 'string' && source.revision.trim()
    && typeof source.asOf === 'string' && Number.isFinite(Date.parse(source.asOf)))
    && (!outer || !inner || (outer.revision === inner.revision && outer.asOf === inner.asOf
      && JSON.stringify(outer) === JSON.stringify(inner)));
  let validRows = coherent;
  for (const row of source.positions) {
    if (!row || typeof row !== 'object' || Array.isArray(row)) { validRows = false; continue; }
    const revision = (row as typeof row & { revision?: string }).revision;
    if (!Number.isSafeInteger(row.vaultId) || row.vaultId <= 0 || rows.has(row.vaultId)
      || (revision != null && revision !== source.revision)) validRows = false;
    rows.set(row.vaultId, exact(row.dungReadyBaseUnits) ? row.dungReadyBaseUnits : null);
  }
  if (!validRows) rows.clear();
  const coverage = source.coverage;
  const complete = validRows && coverage?.completeness === 'complete' && Boolean(typeof coverage.population === 'string' && coverage.population.trim())
    && coverage.observedCount === source.positions.length && coverage.expectedCount === source.positions.length
    && source.positions.every(row => exact(row.dungReadyBaseUnits));
  return { rows, total: complete && exact(source.uncollectedDungBaseUnits) ? source.uncollectedDungBaseUnits : null, supplied: true };
}
