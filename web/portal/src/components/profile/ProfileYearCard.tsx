import { useMemo } from 'react';
import { useFormatters } from '../../hooks/useFormatters';
import { formatInteger, formatRaceTime } from '../../lib/formatters';
import ConsistencyHeatmap from '../training/ConsistencyHeatmap';
import type { ProfileRide } from './groundModel';

// This year (Profile — Ground, Tim-ratified 2026-09-02): rides, distance
// and climbing for the calendar year as stacked pairs, with the year laid
// out beneath. The strip is the same species as the Training heatmap (one
// calendar, ratified 2026-09-03): here it reads presence only — a day you
// rode, a day you didn't — January to December. A reading surface: sums
// over recorded rides, nothing modelled. The page only mounts this when it
// holds every ride of the year.

interface ProfileYearCardProps {
  rides: ProfileRide[];
  now?: Date;
}

function isoDay(date: Date): string {
  return date.toISOString().slice(0, 10);
}

export default function ProfileYearCard({ rides, now = new Date() }: ProfileYearCardProps) {
  const { distanceValue, elevationValue, distanceUnit, elevationUnit } = useFormatters();

  const model = useMemo(() => {
    const year = now.getFullYear();
    const byDay = new Map<string, { date: string; value: number; rides: number }>();
    let distanceM = 0;
    let elevationM = 0;
    for (const ride of rides) {
      const when = new Date(ride.startedAt);
      if (Number.isNaN(when.getTime())) continue;
      const day = isoDay(new Date(Date.UTC(when.getFullYear(), when.getMonth(), when.getDate())));
      const entry = byDay.get(day) ?? { date: day, value: 0, rides: 0 };
      entry.value += ride.durationS ?? 0;
      entry.rides += 1;
      byDay.set(day, entry);
      distanceM += ride.distanceM ?? 0;
      elevationM += ride.elevationM ?? 0;
    }
    const today = isoDay(new Date(Date.UTC(now.getFullYear(), now.getMonth(), now.getDate())));
    return {
      count: rides.length,
      distanceM,
      elevationM,
      days: Array.from(byDay.values()),
      startDate: isoDay(new Date(Date.UTC(year, 0, 1))),
      endDate: isoDay(new Date(Date.UTC(year, 11, 31))),
      today,
    };
  }, [now, rides]);

  return (
    <section className="profile-box profile-year" aria-label="This year">
      <span className="profile-eyebrow">This year</span>
      <div className="profile-year__pairs">
        <div className="profile-pair">
          <strong>{formatInteger(model.count)}</strong>
          <span>rides</span>
        </div>
        <div className="profile-pair">
          <strong>{distanceValue(model.distanceM)}</strong>
          <span>{distanceUnit}</span>
        </div>
        <div className="profile-pair">
          <strong>{elevationValue(model.elevationM)}</strong>
          <span>{`${elevationUnit} climbed`}</span>
        </div>
      </div>
      <div className="profile-year__heatmap">
        <ConsistencyHeatmap
          days={model.days}
          startDate={model.startDate}
          endDate={model.endDate}
          today={model.today}
          read="presence"
          formatValue={(value) => formatRaceTime(value)}
        />
      </div>
    </section>
  );
}
