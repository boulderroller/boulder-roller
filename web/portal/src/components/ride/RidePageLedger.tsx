import { lazy, Suspense, type RefObject } from 'react';
import { Link } from 'react-router-dom';
import { Heart, MessageCircle, ImagePlus, Star, Trash2, Flag } from 'lucide-react';
import type { ClimbData } from './climbData';
import type { Ride, RideInteractions, RideMedia, ClimbPattern } from '../../lib/api';
import type { useFormatters } from '../../hooks/useFormatters';
import { ABSENT_VALUE, formatInteger, formatOrdinal } from '../../lib/formatters';
import { formatBaseUnits } from '../../lib/tokenAmounts';
import { cn } from '../ui/utils';
import { RidePageRow, RidePageTribute } from './RidePageComponents';
import { ridePageModel } from './ridePageModel';
import ClimbShapeGlyph from '../climbs/ClimbShapeGlyph';
import { ClimbPower, climbPowerValue } from '../climb/ClimbPower';

const CommsLog = lazy(() => import('./CommsLog'));

interface RidePageLedgerProps {
  climbRead: string;
  setClimbRead: (value: string) => void;
  climbs: ClimbData[];
  getClimbObjectHref: (climb: ClimbData) => string | null;
  pageModel: ReturnType<typeof ridePageModel>;
  climbPatterns: ClimbPattern[];
  formatDistance: ReturnType<typeof useFormatters>['distance'];
  formatElevation: ReturnType<typeof useFormatters>['elevation'];
  formatClimbGrade: (climb: ClimbData) => string;
  formatDuration: ReturnType<typeof useFormatters>['duration'];
  formatWatts: ReturnType<typeof useFormatters>['watts'];
  formatIntegerLabel: ReturnType<typeof useFormatters>['integer'];
  rideInteractions: RideInteractions | null;
  kudosBusy: boolean;
  isOwner: boolean;
  toggleKudos: () => Promise<void>;
  activityId: string | undefined;
  refreshInteractions: () => void;
  mediaFileInputRef: RefObject<HTMLInputElement | null>;
  isMediaBusy: boolean;
  rideMedia: RideMedia[];
  selectedMedia: RideMedia | null | undefined;
  setLightboxMediaIndex: (index: number) => void;
  selectedMediaIndex: number;
  ride: Ride;
  setSelectedMediaIndex: (index: number) => void;
  handleSetRideMediaCover: (id: string) => Promise<void>;
  handleDeleteRideMedia: (id: string) => Promise<void>;
  handleReportRideMedia: (id: string) => Promise<void>;
  pageCalText: string;
  pageCal: number | null | undefined;
}

export default function RidePageLedger({
  climbRead,
  setClimbRead,
  climbs,
  getClimbObjectHref,
  pageModel,
  climbPatterns,
  formatDistance,
  formatElevation,
  formatClimbGrade,
  formatDuration,
  formatWatts,
  formatIntegerLabel,
  rideInteractions,
  kudosBusy,
  isOwner,
  toggleKudos,
  activityId,
  refreshInteractions,
  mediaFileInputRef,
  isMediaBusy,
  rideMedia,
  selectedMedia,
  setLightboxMediaIndex,
  selectedMediaIndex,
  ride,
  setSelectedMediaIndex,
  handleSetRideMediaCover,
  handleDeleteRideMedia,
  handleReportRideMedia,
  pageCalText,
  pageCal,
}: RidePageLedgerProps) {
  return (
    <div className="ride-page-ledger">
      <div className="ride-page-ledger-left">
        <section className="ride-page-climbs">
          <header className="ride-page-heading">
            <h2>Climbs on this ride</h2>
            <div
              className="ride-words"
              role="group"
              aria-label="Climb values"
            >
              {['Time', 'Power', 'Place'].map((word) => (
                <button
                  key={word}
                  aria-pressed={climbRead === word}
                  onClick={() => setClimbRead(word)}
                >
                  {word}
                </button>
              ))}
            </div>
          </header>
          <div className="ride-page-ledger-card">
            {climbs.map((climb, index) => {
              const href = getClimbObjectHref(climb);
              const points = pageModel.samples.filter(
                (p) =>
                  p.t >= (climb.startOffsetS ?? Infinity) &&
                  p.t <= (climb.endOffsetS ?? -Infinity),
              );
              const power = climbPatterns[index];
              const hasPower = power && climbPowerValue(power) !== null;
              const profile = points
                .filter((p) => p.elevation !== null)
                .map((p) => ({
                  distanceM: p.d - (points[0]?.d ?? 0),
                  elevationM: p.elevation!,
                }));
              return (
                <RidePageRow
                  key={climb.id}
                  href={href}
                  profile={profile}
                  name={climb.name}
                  detail={[
                    climbPatterns[index]?.distanceM == null
                      ? ABSENT_VALUE
                      : formatDistance(climb.distanceM),
                    climbPatterns[index]?.vertM == null
                      ? ABSENT_VALUE
                      : formatElevation(climb.elevationM),
                    climbPatterns[index]?.avgGradientPct == null
                      ? ABSENT_VALUE
                      : formatClimbGrade(climb),
                  ].join(' · ')}
                  value={
                    climbRead === 'Time'
                      ? formatDuration(
                          climb.vaultMatch?.yourTime ??
                            climbPatterns[index]?.durationS,
                        )
                      : climbRead === 'Place'
                        ? climb.vaultMatch?.yourRank
                          ? formatOrdinal(climb.vaultMatch.yourRank)
                          : ABSENT_VALUE
                        : hasPower ? <ClimbPower power={power} /> : null
                  }
                  sub={<>
                    {climbRead === 'Time' && hasPower ? <ClimbPower power={power} /> : null}
                    <span>{[
                      climbRead !== 'Place' && climb.vaultMatch?.yourRank ? formatOrdinal(climb.vaultMatch.yourRank) : '',
                      climb.vaultMatch?.isPR ? 'New best' : '',
                    ].filter(Boolean).join(' · ')}</span>
                  </>}
                />
              );
            })}
          </div>
        </section>
        <section
          id="ride-social"
          className="ride-page-social ride-page-ledger-card"
        >
          <button
            className="ride-page-kv"
            aria-pressed={rideInteractions?.viewerHasKudos ?? false}
            disabled={!rideInteractions || kudosBusy || isOwner}
            onClick={() => void toggleKudos()}
          >
            <Heart size={18} aria-hidden="true" />
            <span className="ride-social-label">
              <b>Give kudos</b>
              <small>
                {rideInteractions
                  ? `${formatIntegerLabel(rideInteractions.kudosCount)} kudos`
                  : ABSENT_VALUE}
              </small>
            </span>
          </button>
          <div className="ride-page-kv">
            <MessageCircle size={18} aria-hidden="true" />
            <span className="ride-social-label">
              <b>Comments</b>
            </span>
            <b>
              {rideInteractions
                ? formatInteger(rideInteractions.commentCount)
                : ABSENT_VALUE}
            </b>
          </div>
          {activityId && rideInteractions?.commentsEnabled && (
            <Suspense fallback={null}>
              <CommsLog
                rideId={activityId}
                ledger
                canComment={rideInteractions.canComment}
                onChange={refreshInteractions}
              />
            </Suspense>
          )}
        </section>
        <section className="ride-page-photos">
          <header className="ride-page-heading">
            <h2>Ride photos</h2>
            {isOwner && (
              <button
                className="ride-text-button"
                onClick={() => mediaFileInputRef.current?.click()}
                disabled={isMediaBusy || rideMedia.length >= 6}
              >
                Add photos
              </button>
            )}
          </header>{' '}
          {selectedMedia ? (
            <div className="ride-detail-overview__photo-gallery">
              <div className="ride-detail-overview__photo-stage">
                <button
                  type="button"
                  className="ride-detail-overview__photo-stage-button"
                  onClick={() =>
                    setLightboxMediaIndex(selectedMediaIndex)
                  }
                  title="Open photo"
                  aria-label="Open photo"
                >
                  <img
                    src={selectedMedia.url || ''}
                    alt={
                      selectedMedia.fileName ||
                      `${ride.title || 'Ride'} photo`
                    }
                    className="ride-detail-overview__photo"
                  />
                </button>
              </div>
              {rideMedia.length > 1 && (
                <div
                  className="ride-detail-overview__photo-thumbs"
                  aria-label="Ride photos"
                >
                  {rideMedia.map((media, index) => (
                    <button
                      key={media.id}
                      type="button"
                      className={cn(
                        'ride-detail-overview__photo-thumb',
                        index === selectedMediaIndex &&
                          'ride-detail-overview__photo-thumb--active',
                      )}
                      onClick={() => setSelectedMediaIndex(index)}
                      aria-label={`Photo ${formatInteger(index + 1)}`}
                      aria-current={
                        index === selectedMediaIndex ? 'true' : undefined
                      }
                    >
                      <img src={media.url || ''} alt="" />
                    </button>
                  ))}
                </div>
              )}
              <div className="ride-detail-overview__photo-actions">
                {isOwner ? (
                  <>
                    <button
                      type="button"
                      className="ride-detail-overview__photo-action"
                      onClick={() => mediaFileInputRef.current?.click()}
                      disabled={isMediaBusy || rideMedia.length >= 6}
                      title="Add photos"
                    >
                      <ImagePlus size={14} aria-hidden="true" />
                      <span>Add</span>
                    </button>
                    <button
                      type="button"
                      className="ride-detail-overview__photo-action"
                      onClick={() =>
                        handleSetRideMediaCover(selectedMedia.id)
                      }
                      disabled={
                        isMediaBusy || selectedMedia.role === 'cover'
                      }
                      title="Set cover"
                    >
                      <Star size={14} aria-hidden="true" />
                      <span>Cover</span>
                    </button>
                    <button
                      type="button"
                      className="ride-detail-overview__photo-action ride-detail-overview__photo-action--danger"
                      onClick={() =>
                        handleDeleteRideMedia(selectedMedia.id)
                      }
                      disabled={isMediaBusy}
                      title="Delete photo"
                    >
                      <Trash2 size={14} aria-hidden="true" />
                      <span>Delete</span>
                    </button>
                  </>
                ) : (
                  <button
                    type="button"
                    className="ride-detail-overview__photo-action"
                    onClick={() =>
                      handleReportRideMedia(selectedMedia.id)
                    }
                    disabled={isMediaBusy}
                    title="Report photo"
                  >
                    <Flag size={14} aria-hidden="true" />
                    <span>Report</span>
                  </button>
                )}
              </div>
            </div>
          ) : null}
        </section>
      </div>
      <div
        className="ride-page-ledger-right"
        data-object-layer="ride-record-proof"
      >
        <section>
          <h2>Ride CAL</h2>
          <div className="ride-page-ledger-card">
            <div className="ride-page-cal">
              <strong>
                {pageCalText}
                {pageCal == null ? '' : ' CAL'}
              </strong>
              <span>{pageCal == null ? 'CAL pending' : ''}</span>
            </div>
            <RidePageTribute hasItemization={Boolean(ride.calItemization?.climbs.length)} />
            {ride.calItemization?.climbs.map((item) => {
              const span = pageModel.spans.find(
                (s) => s.pattern.vaultMatch?.vaultId === item.vaultId,
              );
              const points = span
                ? pageModel.samples.filter(
                    (p) => p.t >= span.start && p.t <= span.end,
                  )
                : [];
              return (
                <div className="ride-page-kv" key={item.patternId}>
                  <ClimbShapeGlyph
                    profile={points
                      .filter((p) => p.elevation !== null)
                      .map((p) => ({
                        distanceM: p.d - (points[0]?.d ?? 0),
                        elevationM: p.elevation!,
                      }))}
                  />
                  <span className="ride-page-tribute-name">
                    {item.climbName ?? ''}
                  </span>
                  <b>
                    {formatBaseUnits(
                      item.calTributeBaseUnits,
                      ride.calItemization!.calDecimals,
                      2,
                    )}{' '}
                    CAL
                  </b>
                </div>
              );
            })}
            <Link
              className="ride-page-kv"
              to={`/activities/${activityId}/log`}
            >
              <span>Verification</span>
              <span aria-hidden="true">›</span>
            </Link>
          </div>
        </section>
      </div>
    </div>
  );
}
