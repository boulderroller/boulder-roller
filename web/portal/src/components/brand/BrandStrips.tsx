import type { ReactNode } from 'react';

/**
 * The public root's transferable forms, decomposed into data-driven
 * components. These are the SAME visual objects the root and app entry
 * render as fixture artwork — portal surfaces render them with live data.
 * Source of the grammar: web/org Hero.tsx (receipt-strip, leaderboard-strip).
 * One code path per form; no prose re-inventions.
 */

export function ReceiptStrip({
  label,
  value,
  variant = 'cal',
  className = '',
}: {
  label: ReactNode;
  value: ReactNode;
  variant?: 'cal' | 'record' | 'context';
  className?: string;
}) {
  return (
    <div className={`br-receipt-strip br-receipt-strip--${variant} ${className}`.trim()}>
      <span>{label}</span>
      <strong>{value}</strong>
    </div>
  );
}

export interface LeaderboardStripRow {
  rank: ReactNode;
  rider: ReactNode;
  time: ReactNode;
  highlight?: boolean;
  key?: string | number;
}

export function LeaderboardStrip({
  title,
  subtitle,
  rows,
  className = '',
}: {
  /** Object name, e.g. the climb — small line above the strong title. */
  title: ReactNode;
  /** Strong line, e.g. "Leaderboard" or "#2 of 42". */
  subtitle: ReactNode;
  rows: LeaderboardStripRow[];
  className?: string;
}) {
  return (
    <div className={`br-leaderboard-strip ${className}`.trim()}>
      <div className="br-leaderboard-strip__title">
        <span>{title}</span>
        <strong>{subtitle}</strong>
      </div>
      {rows.map((row, index) => (
        <div
          className={`br-leaderboard-strip__row${row.highlight ? ' br-leaderboard-strip__row--highlight' : ''}`}
          key={row.key ?? index}
        >
          <span>{row.rank}</span>
          <span>{row.rider}</span>
          <strong>{row.time}</strong>
        </div>
      ))}
    </div>
  );
}
