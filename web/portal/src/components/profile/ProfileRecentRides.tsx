import { useFormatters } from '../../hooks/useFormatters';
import { formatDate, formatDurationCompact } from '../../lib/formatters';
import { sortRidesNewestFirst, type ProfileRide } from './groundModel';

// Recent rides (Profile — Ground, Tim-ratified 2026-09-02): the three most
// recent rides as ledger rows — title, date · distance · climbing, the
// moving time trailing. Each opens its ride.

const ROWS = 3;

interface ProfileRecentRidesProps {
  rides: ProfileRide[];
  viewer?: 'owner' | 'stranger';
  limit?: number;
  title?: 'Recent rides' | 'Rides';
  onOpenRide: (rideId: string) => void;
}

export default function ProfileRecentRides({
  rides,
  viewer = 'owner',
  onOpenRide,
  limit = ROWS,
  title = 'Recent rides',
}: ProfileRecentRidesProps) {
  const { distance, elevation } = useFormatters();
  const rows = sortRidesNewestFirst(rides).slice(0, limit);
  if (rows.length === 0) return null;

  return (
    <section className="profile-box profile-recent" aria-label={title}>
      <span className="profile-eyebrow">{title}</span>
      {rows.map((ride) => {
        const when =
          viewer === 'stranger' &&
          (!ride.startedAt || !Number.isFinite(Date.parse(ride.startedAt)))
            ? ''
            : formatDate(ride.startedAt);
        const sub = [
          when,
          ride.distanceM != null && ride.distanceM > 0
            ? distance(ride.distanceM)
            : null,
          ride.elevationM != null && ride.elevationM > 0
            ? elevation(ride.elevationM)
            : null,
        ]
          .filter(Boolean)
          .join(' · ');
        return (
          <button
            key={ride.id}
            type="button"
            className="profile-recent__row"
            onClick={() => onOpenRide(ride.id)}
          >
            <span className="profile-recent__copy">
              <strong>{ride.title || when}</strong>
              <span>{sub}</span>
            </span>
            {ride.durationS != null && ride.durationS > 0 ? (
              <strong className="profile-recent__time">
                {formatDurationCompact(ride.durationS)}
              </strong>
            ) : null}
          </button>
        );
      })}
    </section>
  );
}
