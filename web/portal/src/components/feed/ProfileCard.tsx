import { memo } from 'react';
import { useNavigate } from 'react-router-dom';

import { PortalPanel } from '../portal/PortalSpine';
import { cn } from '../ui/utils';
import { formatInteger } from '../../lib/formatters';

const BEETLE_EMOJI = '🪲';

interface StatButtonProps {
  label: string;
  value: string | number;
  onClick?: () => void;
  wide?: boolean;
}

const StatButton = memo(function StatButton({ label, value, onClick, wide = false }: StatButtonProps) {
  const className = cn('feed-profile-card__stat', wide && 'feed-profile-card__stat--wide');

  if (!onClick) {
    return (
      <div className={className} data-interactive="false">
        <strong>{value}</strong>
        <span>{label}</span>
      </div>
    );
  }

  return (
    <button
      type="button"
      className={className}
      data-interactive="true"
      onClick={onClick}
    >
      <strong>{value}</strong>
      <span>{label}</span>
    </button>
  );
});

interface ProfileCardProps {
  beetleLabel: string;
  rank: 'C' | 'B' | 'A' | 'S' | 'SS';
  userName?: string;
  avatarUrl?: string | null;
  following: number;
  followers: number;
  activities: number;
  latestActivity?: string;
  latestActivityId?: string;
  currentStreak: number;
}

function ProfileCard({
  beetleLabel,
  rank,
  userName = beetleLabel,
  avatarUrl,
  following,
  followers,
  activities,
  latestActivity,
  latestActivityId,
  currentStreak,
}: ProfileCardProps) {
  const navigate = useNavigate();

  return (
    <PortalPanel className="feed-profile-card" data-tier={rank}>
      <button
        type="button"
        className="feed-profile-card__identity"
        onClick={() => navigate('/profile')}
        aria-label={`Open ${userName} profile`}
      >
        <span className="feed-profile-card__avatar" aria-hidden="true">
          {avatarUrl ? <img src={avatarUrl} alt="" /> : <span>{BEETLE_EMOJI}</span>}
        </span>

        <span className="feed-profile-card__copy">
          <span className="feed-profile-card__name">{userName}</span>
          <span className="feed-profile-card__rank">{rank} Rank</span>
        </span>
      </button>

      <div className="feed-profile-card__stats">
        <StatButton label="Following" value={formatInteger(following)} />
        <StatButton label="Followers" value={formatInteger(followers)} />
        <StatButton label="Rides" value={formatInteger(activities)} onClick={() => navigate('/profile?tab=rides')} wide />
      </div>

      {latestActivity ? (
        <button
          type="button"
          className="feed-profile-card__latest feed-profile-card__latest--button"
          onClick={() => navigate(latestActivityId ? `/activities/${latestActivityId}` : '/profile?tab=rides')}
        >
          <span>Latest ride</span>
          <strong>{latestActivity}</strong>
        </button>
      ) : (
        <div className="feed-profile-card__latest">
          <span>Latest ride</span>
          <strong>{activities > 0 ? 'Latest ride unavailable' : 'No uploaded rides yet'}</strong>
        </div>
      )}

      <div className="feed-profile-card__streak">
        <span>Current streak</span>
        <strong>{formatInteger(currentStreak)}</strong>
      </div>
    </PortalPanel>
  );
}

export default memo(ProfileCard);
