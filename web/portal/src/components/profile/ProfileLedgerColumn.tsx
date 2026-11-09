import { Slot, SlotRows } from '../loading/Slot';
import { useEffect, useRef, useState, type ReactNode } from 'react';
import { Flag, Link as LinkIcon, MoreHorizontal, Settings } from 'lucide-react';
import { ABSENT_VALUE, formatDate, formatInteger, formatMonthYear, formatRaceTime } from '../../lib/formatters';
import { RankMark } from '../rankmarks/RankMark';

// The ledger column (Profile — Ground, Tim-ratified 2026-09-02): floats on
// the ground at its own height. Identity, the follow line, the Rides /
// Seats / Crowns trio, the leaderboards the rider stands on, and the
// ridden-count line. Times are public, money is private — nothing economic here.

export interface LedgerRow {
  key: string;
  rank: number;
  name: string;
  sub: string | null;
  timeSeconds: number | null;
  achievedAt?: string | null;
  onOpen?: () => void;
}

export interface LedgerMenu {
  onCopyLink: () => void;
  copied: boolean;
  onEdit?: () => void;
  onReport?: () => void;
  reportStatus?: string | null;
  reporting?: boolean;
}

interface ProfileLedgerColumnProps {
  displayName: string;
  handle: string | null;
  location: string | null;
  bio: string | null;
  avatarUrl: string | null;
  createdAt: string | null;
  followerCount: number | null;
  followingCount: number | null;
  follow: { isFollowing: boolean; pending: boolean; onToggle: () => void } | null;
  menu: LedgerMenu | null;
  viewer?: 'owner' | 'stranger';
  rides: number | null;
  seats: number | null;
  crowns: number | null;
  rows: LedgerRow[];
  riddenCount: { ridden: number; total: number } | null;
  positionsState: 'ready' | 'loading' | 'unavailable';
  retryingPositions: boolean;
  onRetryPositions: () => void;
  children?: ReactNode;
}

export default function ProfileLedgerColumn({
  displayName,
  viewer = 'owner',
  handle,
  location,
  bio,
  avatarUrl,
  createdAt,
  followerCount,
  followingCount,
  follow,
  menu,
  rides,
  seats,
  crowns,
  rows,
  riddenCount,
  positionsState,
  retryingPositions,
  onRetryPositions,
  children,
}: ProfileLedgerColumnProps) {
  const [menuOpen, setMenuOpen] = useState(false);
  const menuRef = useRef<HTMLDivElement>(null);
  const initial = displayName.trim().slice(0, 1).toUpperCase();
  const meta = [handle ? `@${handle}` : null, location].filter(Boolean).join(' · ');
  const since = createdAt ? formatMonthYear(createdAt) : null;

  useEffect(() => {
    if (!menuOpen) return undefined;
    const close = (event: MouseEvent) => {
      if (menuRef.current && !menuRef.current.contains(event.target as Node)) setMenuOpen(false);
    };
    document.addEventListener('mousedown', close);
    return () => document.removeEventListener('mousedown', close);
  }, [menuOpen]);

  return (
    <section className="profile-ledger" aria-label="Rider">
      <div className="profile-ledger__identity">
        <span className="profile-ledger__avatar" aria-hidden="true">
          {avatarUrl ? <img src={avatarUrl} alt="" /> : <span>{initial}</span>}
        </span>
        <div className="profile-ledger__copy">
          <h1 className="profile-ledger__name">{displayName}</h1>
          {meta ? <span className="profile-ledger__meta">{meta}</span> : null}
          {since ? <span className="profile-ledger__since">{`Since ${since}`}</span> : null}
        </div>
        {menu && <div className="profile-ledger__menu" ref={menuRef}>
          <button
            type="button"
            className="profile-ledger__menu-trigger"
            aria-label="Open profile menu"
            aria-expanded={menuOpen}
            onClick={() => setMenuOpen((open) => !open)}
          >
            <MoreHorizontal size={18} aria-hidden="true" />
          </button>
          {menuOpen ? (
            <div className="profile-ledger__menu-content" role="menu">
              <button
                type="button"
                role="menuitem"
                className="profile-ledger__menu-action"
                onClick={() => { menu.onCopyLink(); setMenuOpen(false); }}
              >
                <LinkIcon size={14} aria-hidden="true" />
                {menu.copied ? 'Copied' : 'Copy link'}
              </button>
              {menu.onEdit ? (
                <button type="button" role="menuitem" className="profile-ledger__menu-action" onClick={menu.onEdit}>
                  <Settings size={14} aria-hidden="true" />
                  Edit profile
                </button>
              ) : null}
              {menu.onReport ? (
                <button
                  type="button"
                  role="menuitem"
                  className="profile-ledger__menu-action profile-ledger__menu-action--danger"
                  disabled={Boolean(menu.reportStatus) || Boolean(menu.reporting)}
                  onClick={() => { menu.onReport?.(); setMenuOpen(false); }}
                >
                  <Flag size={14} aria-hidden="true" />
                  {menu.reportStatus ? `Reported ${menu.reportStatus}` : menu.reporting ? 'Reporting' : 'Report'}
                </button>
              ) : null}
            </div>
          ) : null}
        </div>}
      </div>

      {bio ? <p className="profile-ledger__bio">{bio}</p> : null}

      {(viewer === 'owner' || followerCount != null || followingCount != null || follow) && <div className="profile-ledger__social">
        {followerCount != null || followingCount != null ? (
          <span className="profile-ledger__follows">
            {viewer === 'stranger' ? <>
              {followerCount != null && <><strong>{formatInteger(followerCount)}</strong>{' followers'}</>}
              {followingCount != null && <>{followerCount != null ? ' · ' : ''}<strong>{formatInteger(followingCount)}</strong>{' following'}</>}
            </> : <>            <strong>{followerCount == null ? ABSENT_VALUE : formatInteger(followerCount)}</strong>
            {' followers · '}
            <strong>{followingCount == null ? ABSENT_VALUE : formatInteger(followingCount)}</strong>
            {' following'}</>}
          </span>
        ) : <span />}
        {follow ? (
          <button
            type="button"
            className="profile-ledger__follow"
            aria-pressed={follow.isFollowing}
            disabled={follow.pending}
            onClick={follow.onToggle}
          >
            {follow.isFollowing ? 'Following' : 'Follow'}
          </button>
        ) : null}
      </div>}

      {(viewer === 'owner' || rides != null || seats != null || crowns != null) && <div className="profile-ledger__trio" role="list" aria-label="Rides, seats and crowns">
        {(viewer === 'owner' || rides != null) && <div className="profile-pair" role="listitem">
          <strong>{formatInteger(rides)}</strong>
          <span>Rides</span>
        </div>}
        {(viewer === 'owner' || seats != null) && <div className="profile-pair" role="listitem">
          <strong>{positionsState === 'loading' ? <Slot variant="number" /> : seats == null ? ABSENT_VALUE : formatInteger(seats)}</strong>
          <span>Seats</span>
        </div>}
        {(viewer === 'owner' || crowns != null) && <div className="profile-pair" role="listitem">
          <strong>{positionsState === 'loading' ? <Slot variant="number" /> : crowns == null ? ABSENT_VALUE : formatInteger(crowns)}</strong>
          <span>Crowns</span>
        </div>}
      </div>}

      {viewer !== 'stranger' && positionsState !== 'ready' ? (
        <div className="profile-ledger__availability" role="status" aria-busy={positionsState === 'loading' || retryingPositions}>
          {positionsState === 'loading' ? <><SlotRows count={5} /><span className="sr-only">Loading positions</span></> : <span>Positions unavailable.</span>}
          {positionsState === 'unavailable' ? (
            <button type="button" onClick={onRetryPositions} disabled={retryingPositions} aria-label="Retry positions">
              {retryingPositions ? 'Retrying' : 'Try again'}
            </button>
          ) : null}
        </div>
      ) : null}

      {rows.length > 0 ? (
        <div className="profile-ledger__standings" aria-label="Leaderboards">
          <span className="profile-eyebrow">Leaderboards</span>
          {rows.map((row) => (
            <LedgerStanding key={row.key} onOpen={row.onOpen}>
              <span className="profile-ledger__row-mark"><RankMark rank={row.rank} size={28} /></span>
              <span className="profile-ledger__row-copy">
                <strong>{row.name}</strong>
                {row.sub ? <span>{row.sub}</span> : null}
              </span>
              <span className="profile-ledger__row-trail">
                {(viewer === 'owner' || row.timeSeconds != null) && <strong>{row.timeSeconds == null ? ABSENT_VALUE : formatRaceTime(row.timeSeconds)}</strong>}
                {row.achievedAt ? <span>{formatDate(row.achievedAt)}</span> : null}
              </span>
            </LedgerStanding>
          ))}
        </div>
      ) : null}

      {riddenCount ? (
        <div className="profile-ledger__ridden-count">
          <strong>{formatInteger(riddenCount.ridden)}</strong>
          <span>{`of ${formatInteger(riddenCount.total)} climbs ridden`}</span>
        </div>
      ) : null}

      {children}
    </section>
  );
}

function LedgerStanding({onOpen, children}: {onOpen?: () => void; children: ReactNode}) {
  return onOpen ? <button type="button" className="profile-ledger__row" onClick={onOpen}>{children}</button> : <div className="profile-ledger__row">{children}</div>;
}
