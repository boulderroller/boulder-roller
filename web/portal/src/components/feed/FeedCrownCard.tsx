import { memo } from 'react';
import { useNavigate } from 'react-router-dom';
import { formatDate, formatInteger } from '../../lib/formatters';
import { Slot } from '../loading/Slot';

// The feed's capstone (ratified Feed board 2026-09-01): the rider's round
// avatar, name and handle, the Rides / Seats / Crowns trio as stacked pairs,
// then two ledger rows. Times are public, money is private — nothing
// economic lives here.

interface FeedCrownCardProps {
  name: string;
  handle?: string | null;
  location?: string | null;
  avatarUrl?: string | null;
  rides: number;
  seats: number | null;
  crowns: number | null;
  /** The standing request is still held: the value's space, never a dash or a zero. */
  standingPending?: boolean;
  latestRideDate?: string | null;
  latestRideId?: string | null;
}

function Chevron() {
  return (
    <svg width="8" height="12" viewBox="0 0 8 12" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <path d="M2 1.5 L6.5 6 L2 10.5" />
    </svg>
  );
}

function FeedCrownCardImpl({
  name,
  handle,
  location,
  avatarUrl,
  rides,
  seats,
  crowns,
  standingPending = false,
  latestRideDate,
  latestRideId,
}: FeedCrownCardProps) {
  const navigate = useNavigate();
  const initial = name.trim().slice(0, 1).toUpperCase();
  const meta = [handle ? `@${handle}` : null, location || null].filter(Boolean).join(' · ');
  const latestLabel = latestRideDate ? formatDate(latestRideDate) : null;

  return (
    <section className="feed-crown" aria-label="Your profile">
      <button type="button" className="feed-crown__identity" onClick={() => navigate('/profile')}>
        <span className="feed-crown__avatar" aria-hidden="true">
          {avatarUrl ? <img src={avatarUrl} alt="" /> : <span>{initial}</span>}
        </span>
        <span className="feed-crown__name">{name}</span>
        {meta ? <span className="feed-crown__meta">{meta}</span> : null}
      </button>
      <div className="feed-crown__trio" role="list">
        <div className="feed-pair feed-pair--center" role="listitem">
          <strong>{formatInteger(rides)}</strong>
          <span>Rides</span>
        </div>
        <div className="feed-pair feed-pair--center" role="listitem">
          <strong>{standingPending ? <Slot variant="number" width="2ch" /> : seats == null ? null : formatInteger(seats)}</strong>
          <span>Seats</span>
        </div>
        <div className="feed-pair feed-pair--center" role="listitem">
          <strong>{standingPending ? <Slot variant="number" width="2ch" /> : crowns == null ? null : formatInteger(crowns)}</strong>
          <span>Crowns</span>
        </div>
      </div>
      {latestLabel ? (
        <button
          type="button"
          className="feed-row feed-row--tap"
          onClick={() => navigate(latestRideId ? `/activities/${latestRideId}` : '/profile?tab=rides')}
        >
          <span className="feed-row__label">Latest ride</span>
          <span className="feed-row__trail">
            <span className="feed-row__value">{latestLabel}</span>
            <span className="feed-row__chevron"><Chevron /></span>
          </span>
        </button>
      ) : null}
      <button type="button" className="feed-row feed-row--tap" onClick={() => navigate('/profile?tab=rides')}>
        <span className="feed-row__label">Your rides</span>
        <span className="feed-row__trail"><span className="feed-row__chevron"><Chevron /></span></span>
      </button>
    </section>
  );
}

export const FeedCrownCard = memo(FeedCrownCardImpl);
export default FeedCrownCard;
