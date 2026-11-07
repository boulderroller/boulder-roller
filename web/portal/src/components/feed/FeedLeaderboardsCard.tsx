import { memo, useMemo } from 'react';
import { useNavigate } from 'react-router-dom';
import type { VaultPositionSummary } from '../../lib/api';
import { formatDate, formatRaceTime } from '../../lib/formatters';
import { RankMark } from '../rankmarks/RankMark';

// Your leaderboards (ratified Feed board 2026-09-01): the seats and crowns
// the rider holds — rank mark, climb, when it was set, the time trailing.
// Monuments, so ink; nothing here is money. With no positions the card
// renders nothing (a surface with no footing renders no empty object).

const ROWS = 3;

interface FeedLeaderboardsCardProps {
  positions: VaultPositionSummary[] | undefined;
}

function FeedLeaderboardsCardImpl({ positions }: FeedLeaderboardsCardProps) {
  const navigate = useNavigate();
  const rows = useMemo(() => {
    return (positions ?? [])
      .filter((p) => Number.isFinite(p.rank) && p.rank >= 1)
      .sort((a, b) => a.rank - b.rank || (a.bestTimeSeconds ?? 0) - (b.bestTimeSeconds ?? 0))
      .slice(0, ROWS);
  }, [positions]);

  if (rows.length === 0) return null;

  return (
    <section className="feed-box" aria-label="Your leaderboards">
      <div className="feed-box__head">
        <span className="feed-box__title">Your leaderboards</span>
        <button type="button" className="feed-box__more" onClick={() => navigate('/profile')}>See All</button>
      </div>
      {rows.map((position) => {
        const when = position.achievedAt ? formatDate(position.achievedAt) : null;
        const kind = position.isKom || position.rank === 1 ? 'Crown' : 'Seat';
        return (
          <button
            key={`${position.vaultId}-${position.rank}`}
            type="button"
            className="feed-row feed-row--tap feed-row--tall"
            onClick={() => navigate(`/vaults/${position.vaultId}`)}
          >
            <span className="feed-row__lead">
              <span className="feed-row__mark"><RankMark rank={position.rank} size={28} /></span>
              <span className="feed-row__copy">
                <span className="feed-row__label feed-row__label--ink">{position.vaultName}</span>
                <span className="feed-row__sub">{when ? `${kind} · ${when}` : kind}</span>
              </span>
            </span>
            <span className="feed-row__trail">
              <span className="feed-row__value feed-row__value--mono">{formatRaceTime(position.bestTimeSeconds)}</span>
            </span>
          </button>
        );
      })}
    </section>
  );
}

export const FeedLeaderboardsCard = memo(FeedLeaderboardsCardImpl);
export default FeedLeaderboardsCard;
