import { formatRelativeTime, formatTimestamp } from '@/lib/format';

type RelativeTimeProps = {
  value: unknown;
};

/**
 * Renders a relative time ("2h ago") with the absolute timestamp on hover.
 * Falls back to the absolute timestamp if relative formatting fails.
 */
export default function RelativeTime({ value }: RelativeTimeProps) {
  const relative = formatRelativeTime(value);
  const absolute = formatTimestamp(value);

  if (!relative || absolute === '\u2014') {
    return <span>{absolute}</span>;
  }

  return (
    <span title={absolute}>
      {relative}
    </span>
  );
}
