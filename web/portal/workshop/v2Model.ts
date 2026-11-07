import type { Climb } from './scenario';

/** Every bar occupies a fraction of the same track, measured from zero. */
export function historyComparison(date: string, duration: number, history: Climb['history']) {
  if (!history.length) return [];
  const slowest = Math.max(duration, ...history.map(row => row.duration));
  return [
    { date, duration, current: true },
    ...[...history].sort((a, b) => Date.parse(b.date) - Date.parse(a.date)).map(row => ({ ...row, current: false })),
  ].map(row => ({ ...row, percent: row.duration / slowest * 100 }));
}
