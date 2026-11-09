import React, { useState, useRef, useEffect, memo } from 'react';
import { ActivityFeedItem as ActivityFeedItemType } from '../../types';
import { Flag, MoreHorizontal, Link as LinkIcon } from 'lucide-react';
import { api } from '../../lib/api';
import { useFormatters } from '../../hooks/useFormatters';
import { ABSENT_VALUE, formatCappedInteger, formatDurationCompact, formatInteger, formatNumber, formatDuration, formatTokenAmount } from '../../lib/formatters';
import { toast } from 'sonner';
import RoutePreviewBand from './RoutePreviewBand';

// The feed card in the ratified anatomy (Feed board, 2026-09-01): header,
// title, stat pairs, the route band as the hero, then one footer carrying
// the social organs on the right. Feed whispers: only the viewer's own ride
// shows a CAL pair. A permitted feed result precedes the ride summary.

function KudosGlyph() {
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true">
      <path d="M7 11v9H4a1 1 0 0 1-1-1v-7a1 1 0 0 1 1-1h3z" />
      <path d="M7 11l4.2-7.5a1.6 1.6 0 0 1 2.9 1.1L13 9h5.3a2 2 0 0 1 2 2.4l-1.3 6.6A2.5 2.5 0 0 1 16.5 20H7" />
    </svg>
  );
}

function CommentGlyph() {
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true">
      <path d="M4 6.5A2.5 2.5 0 0 1 6.5 4h11A2.5 2.5 0 0 1 20 6.5v7a2.5 2.5 0 0 1-2.5 2.5H10l-4.5 4v-4h-1A2.5 2.5 0 0 1 4 13.5v-7z" />
    </svg>
  );
}

export const ActivityFeedItem = memo(({
  activity,
  onClick,
  onRiderClick,
}: {
  activity: ActivityFeedItemType;
  onClick: () => void;
  onRiderClick?: (path: string) => void;
}) => {
    const { distanceValue, elevationValue, distanceUnit, elevationUnit } = useFormatters();
    const hasRoute = Boolean(
      activity.routePreview
      && ((activity.routePreview.points?.length ?? 0) > 1 || (activity.routePreview.segments?.length ?? 0) > 0),
    );
    const hasPhoto = !hasRoute && activity.visualType === 'image' && Boolean(activity.visualUrl);
    const visualType = hasRoute ? 'map' : hasPhoto ? 'image' : 'none';

    const [isLiked, setIsLiked] = useState(Boolean(activity.viewerHasKudos));
    const [likeCount, setLikeCount] = useState(activity.claps ?? 0);
    const [commentCount, setCommentCount] = useState(activity.comments ?? 0);
    const [isLikePending, setIsLikePending] = useState(false);
    const [isCommentOpen, setIsCommentOpen] = useState(false);
    const [isMenuOpen, setIsMenuOpen] = useState(false);
    const [commentText, setCommentText] = useState('');
    const [isPostingComment, setIsPostingComment] = useState(false);
    const [viewerReported, setViewerReported] = useState(Boolean(activity.viewerReported));
    const [reportStatus, setReportStatus] = useState<string | null>(activity.reportStatus ?? null);
    const [isReporting, setIsReporting] = useState(false);
    const menuRef = useRef<HTMLDivElement>(null);
    const cardRef = useRef<HTMLDivElement>(null);

    useEffect(() => {
        setIsLiked(Boolean(activity.viewerHasKudos));
        setLikeCount(activity.claps ?? 0);
        setCommentCount(activity.comments ?? 0);
        setViewerReported(Boolean(activity.viewerReported));
        setReportStatus(activity.reportStatus ?? null);
    }, [activity.id, activity.viewerHasKudos, activity.claps, activity.comments, activity.viewerReported, activity.reportStatus]);

    useEffect(() => {
        const handleClickOutside = (event: MouseEvent) => {
            const target = event.target as Node;
            if (isMenuOpen && menuRef.current && !menuRef.current.contains(target)) {
                setIsMenuOpen(false);
            }
            if (isCommentOpen && cardRef.current && !cardRef.current.contains(target)) {
                setIsCommentOpen(false);
            }
        };
        if (isMenuOpen || isCommentOpen) {
            document.addEventListener('mousedown', handleClickOutside);
        }
        return () => document.removeEventListener('mousedown', handleClickOutside);
    }, [isMenuOpen, isCommentOpen]);

    const handleRideClick = (event: React.MouseEvent<HTMLAnchorElement>) => {
        // Keep native new-tab/window gestures while routing ordinary activation.
        if (event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
        event.preventDefault();
        onClick();
    };

    const handleRiderClick = (e: React.MouseEvent) => {
        e.stopPropagation();
        if (activity.riderPath) {
            onRiderClick?.(activity.riderPath);
        }
    };

    const handleLike = async (e: React.MouseEvent) => {
        e.stopPropagation();
        if (isLikePending) return;
        const nextLiked = !isLiked;
        setIsLikePending(true);
        setIsLiked(nextLiked);
        setLikeCount(count => Math.max(0, count + (nextLiked ? 1 : -1)));
        try {
            if (nextLiked) {
                await api.giveKudos(activity.id);
            } else {
                await api.removeKudos(activity.id);
            }
        } catch {
            setIsLiked(!nextLiked);
            setLikeCount(count => Math.max(0, count + (nextLiked ? -1 : 1)));
            toast.error(nextLiked ? 'Could not give kudos' : 'Could not remove kudos');
        } finally {
            setIsLikePending(false);
        }
    };

    const handleCommentToggle = (e: React.MouseEvent) => {
        e.stopPropagation();
        setIsCommentOpen(!isCommentOpen);
    };

    const handleMenuToggle = (e: React.MouseEvent) => {
        e.stopPropagation();
        setIsMenuOpen(!isMenuOpen);
    };

    const handleCopyLink = (e: React.MouseEvent) => {
        e.stopPropagation();
        navigator.clipboard.writeText(`${window.location.origin}/activities/${activity.id}`);
        setIsMenuOpen(false);
    };

    const handleReportRide = async (e: React.MouseEvent) => {
        e.stopPropagation();
        if (isReporting || viewerReported) return;
        try {
            setIsReporting(true);
            const report = await api.reportSocialContent('ride', activity.id, 'other', 'Reported from feed');
            setViewerReported(true);
            setReportStatus(report.status);
            setIsMenuOpen(false);
            toast.success('Report sent');
        } catch {
            toast.error('Could not report ride');
        } finally {
            setIsReporting(false);
        }
    };

    const handlePostComment = async (e?: React.MouseEvent | React.KeyboardEvent) => {
        e?.stopPropagation();
        const content = commentText.trim();
        if (!content || isPostingComment) return;
        try {
            setIsPostingComment(true);
            await api.addRideComment(activity.id, content);
            setCommentCount(count => count + 1);
            setCommentText('');
            setIsCommentOpen(false);
            toast.success('Comment posted');
        } catch {
            toast.error('Could not post comment');
        } finally {
            setIsPostingComment(false);
        }
    };

    const when = [activity.date, activity.placeLabel].filter(Boolean).join(' · ');
    const showCal = Boolean(activity.isOwn) && activity.calEarned != null && activity.calEarned > 0;
    const result = activity.resultSummary;
    // Whole-second times use the shared Ride page duration formatter. Smaller measurements
    // keep a separate seconds unit and never round a positive value to zero.
    const resultSeconds = result?.timeSeconds ?? null;
    const resultExponent = resultSeconds !== null && resultSeconds > 0 && resultSeconds < 1e-20
      ? Math.ceil(Math.log10(resultSeconds)) : 0;
    const resultTime = resultSeconds === null ? null : resultSeconds >= 1
      ? formatDuration(resultSeconds)
      : formatNumber(resultSeconds / (10 ** resultExponent), 20);
    const initials = activity.user.substring(0, 2).toUpperCase();

  return (
    <div
      ref={cardRef}
      className="feed-activity-card feed-card"
      data-activity-type={activity.displayType.toLowerCase()}
      data-visual-type={visualType}
      data-own={activity.isOwn ? 'true' : 'false'}
    >
      <div className="feed-card__header">
        <div className="feed-card__identity">
          <span className="feed-card__avatar" aria-hidden="true">
            {activity.avatarUrl ? <img src={activity.avatarUrl} alt="" /> : <span>{initials}</span>}
          </span>
          <div className="feed-card__copy">
            {activity.riderPath ? (
              <button
                type="button"
                className="feed-activity-card__user-button"
                data-rider-path={activity.riderPath}
                onClick={handleRiderClick}
              >
                {activity.handle ? `@${activity.handle}` : ABSENT_VALUE}
              </button>
            ) : (
              <span className="feed-card__user">{activity.handle ? `@${activity.handle}` : ABSENT_VALUE}</span>
            )}
            <span className="feed-card__when">{when}</span>
          </div>
        </div>
        <div className="feed-card__menu" ref={menuRef}>
          <button
            type="button"
            className="feed-card__menu-trigger"
            data-state={isMenuOpen ? 'open' : 'closed'}
            aria-label="Open ride menu"
            aria-expanded={isMenuOpen}
            onClick={handleMenuToggle}
          >
            <MoreHorizontal size={18} />
          </button>
          {isMenuOpen && (
            <div className="feed-card__menu-content">
              <button type="button" className="feed-card__menu-action" onClick={handleCopyLink}>
                <LinkIcon size={14} />
                Copy link
              </button>
              <button
                type="button"
                className="feed-card__menu-action feed-card__menu-action--danger"
                disabled={viewerReported || isReporting}
                onClick={handleReportRide}
              >
                <Flag size={14} />
                {viewerReported ? 'Reported' : isReporting ? 'Reporting' : 'Report ride'}
              </button>
            </div>
          )}
        </div>
      </div>

      <div className="feed-card__body">
        <h3 className="feed-card__title">
          <a className="feed-card__ride-link" href={`/activities/${activity.id}`} onClick={handleRideClick}>
            {activity.title}
          </a>
        </h3>
        {result && resultTime !== null ? (
          <div className="feed-card__result" data-climb-id={result.climbId}>
            <a href={`/climbs/${encodeURIComponent(result.climbId)}`}>
              <span>Climb</span>
              <span className="feed-pair">
                <strong>{resultTime}{resultExponent !== 0 ? <>e{formatInteger(resultExponent)}</> : null}</strong>
                <span>Time{resultSeconds !== null && resultSeconds < 1 ? ' · s' : ''}</span>
              </span>
            </a>
          </div>
        ) : null}
        <div className="feed-card__pairs" aria-label="Ride summary">
          {activity.distanceM != null && activity.distanceM > 0 ? (
            <div className="feed-pair">
              <strong>{distanceValue(activity.distanceM)}</strong>
              <span>{distanceUnit}</span>
            </div>
          ) : null}
          {activity.elevationM != null && activity.elevationM > 0 ? (
            <div className="feed-pair">
              <strong>{elevationValue(activity.elevationM)}</strong>
              <span>{elevationUnit} climbed</span>
            </div>
          ) : null}
          {activity.durationS != null && activity.durationS > 0 ? (
            <div className="feed-pair">
              <strong>{formatDurationCompact(activity.durationS)}</strong>
              <span>time</span>
            </div>
          ) : null}
          {showCal ? (
            <div className="feed-pair feed-pair--end feed-card__cal">
              <strong>{formatTokenAmount(activity.calEarned)}</strong>
              <span>CAL</span>
            </div>
          ) : null}
        </div>
      </div>

      {hasRoute ? (
        <div className="feed-card__band">
          <RoutePreviewBand preview={activity.routePreview} />
        </div>
      ) : hasPhoto ? (
        <div className="feed-card__band">
          <img src={activity.visualUrl} className="feed-card__photo" alt="" />
        </div>
      ) : null}

      <div className="feed-card__footer">
        {viewerReported && (
          <span className="feed-card__reported">{reportStatus || 'Reported'}</span>
        )}
        <button
          type="button"
          className="feed-card__organ feed-card__organ--kudos"
          data-state={isLiked ? 'active' : 'idle'}
          aria-label={isLiked ? 'Remove kudos' : 'Give kudos'}
          disabled={isLikePending}
          onClick={handleLike}
        >
          <KudosGlyph />
          {likeCount > 0 ? <strong>{formatCappedInteger(likeCount)}</strong> : null}
        </button>
        <button
          type="button"
          className="feed-card__organ feed-card__organ--comment"
          data-state={isCommentOpen ? 'active' : 'idle'}
          aria-label={isCommentOpen ? 'Close comments' : 'Open comments'}
          onClick={handleCommentToggle}
        >
          <CommentGlyph />
          {commentCount > 0 ? <strong>{formatInteger(commentCount)}</strong> : null}
        </button>
      </div>

      {isCommentOpen && (
        <div className="feed-card__comment-box" onClick={(e) => e.stopPropagation()}>
          <input
            type="text"
            value={commentText}
            onChange={(e) => setCommentText(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter') {
                e.preventDefault();
                handlePostComment(e);
              }
            }}
            placeholder="Add a comment..."
            className="feed-card__comment-input"
            autoComplete="off"
            autoFocus
          />
          <button
            type="button"
            className="feed-card__comment-submit"
            disabled={!commentText.trim() || isPostingComment}
            onClick={handlePostComment}
          >
            Post
          </button>
        </div>
      )}
    </div>
  );
});

ActivityFeedItem.displayName = 'ActivityFeedItem';
