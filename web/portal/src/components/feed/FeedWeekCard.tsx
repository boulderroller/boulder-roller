import { memo, useMemo } from 'react';
import type { Ride } from '../../lib/api';
import { useFormatters } from '../../hooks/useFormatters';
import { formatFixed, formatInteger } from '../../lib/formatters';

// This week (ratified Feed board 2026-09-01): rides, distance and climbing
// for the current week as stacked pairs, with seven day-bars beneath. A
// reading surface: sums over the rider's own recorded rides, nothing
// modelled. Weeks run Monday to Sunday.

interface FeedWeekCardProps {
  rides: Ride[] | undefined;
  loading?: boolean;
}

function startOfWeek(now: Date): Date {
  const d = new Date(now.getFullYear(), now.getMonth(), now.getDate());
  const day = (d.getDay() + 6) % 7; // Monday = 0
  d.setDate(d.getDate() - day);
  return d;
}

function FeedWeekCardImpl({ rides, loading = false }: FeedWeekCardProps) {
  const { distanceValue, elevationValue, distanceUnit, elevationUnit } = useFormatters();

  const model = useMemo(() => {
    const now = new Date();
    const start = startOfWeek(now);
    const end = new Date(start);
    end.setDate(start.getDate() + 7);
    const todayIndex = (now.getDay() + 6) % 7;
    const days = Array.from({ length: 7 }, () => 0);
    let count = 0;
    let distanceM = 0;
    let elevationM = 0;
    for (const ride of rides ?? []) {
      const when = new Date(ride.startedAt);
      if (Number.isNaN(when.getTime()) || when < start || when >= end) continue;
      count += 1;
      distanceM += ride.distanceM ?? 0;
      elevationM += ride.elevationM ?? 0;
      days[(when.getDay() + 6) % 7] += ride.durationS ?? 0;
    }
    const peak = Math.max(...days);
    return {
      count,
      distanceM,
      elevationM,
      bars: days.map((seconds, index) => ({
        index,
        ratio: peak > 0 ? seconds / peak : 0,
        today: index === todayIndex,
        rode: seconds > 0,
      })),
    };
  }, [rides]);

  if (loading && !rides) return null;

  return (
    <section className="feed-box" aria-label="This week">
      <div className="feed-box__head">
        <span className="feed-box__title">This week</span>
      </div>
      <div className="feed-week__pairs" role="list">
        <div className="feed-pair" role="listitem">
          <strong>{formatInteger(model.count)}</strong>
          <span>{model.count === 1 ? 'ride' : 'rides'}</span>
        </div>
        <div className="feed-pair" role="listitem">
          <strong>{model.count > 0 ? distanceValue(model.distanceM) : formatInteger(0)}</strong>
          <span>{distanceUnit}</span>
        </div>
        <div className="feed-pair" role="listitem">
          <strong>{model.count > 0 ? elevationValue(model.elevationM) : formatInteger(0)}</strong>
          <span>{elevationUnit} climbed</span>
        </div>
      </div>
      <div className="feed-week__bars" aria-hidden="true">
        {model.bars.map((bar) => (
          <span
            key={bar.index}
            className="feed-week__bar"
            data-rode={bar.rode ? 'true' : 'false'}
            data-today={bar.today ? 'true' : 'false'}
            style={{ height: `${formatFixed(8 + bar.ratio * 20, 0)}px` }}
          />
        ))}
      </div>
    </section>
  );
}

export const FeedWeekCard = memo(FeedWeekCardImpl);
export default FeedWeekCard;
