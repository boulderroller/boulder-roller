import { ridePresentationFacts, formatRidePresentation } from '../../../server/ride-card-shape';
import { useEffect, useState } from 'react';
import { api, type Ride, type RideStatus } from '../../lib/api';
import { getRideEffortTrimCopy, readSubjectStates, type StateSubject } from '../../lib/protocolStates';
import { ABSENT_VALUE, formatDate, formatDateTime, formatInteger } from '../../lib/formatters';
import { useFormatters } from '../../hooks/useFormatters';
import ClimbShapeGlyph from '../climbs/ClimbShapeGlyph';

export default function UploadSavedRide({ rideId, duplicate = false, status, onOpenRide }: {
  rideId: string;
  duplicate?: boolean;
  status?: RideStatus | null;
  onOpenRide: (rideId: string) => void;
}) {
  const formatters = useFormatters();
  const [ride, setRide] = useState<Ride | null>(null);

  useEffect(() => {
    let active = true;
    setRide(null);
    // The owner list owns the compact spine and counted spans. Detail owns
    // the title and results. Do not invent a shape or fetch raw ride streams.
    void Promise.allSettled([api.getRide(rideId), api.getRides({ limit: 100 })]).then(([detail, log]) => {
      if (!active) return;
      const row = log.status === 'fulfilled' ? log.value.find((item) => item.id === rideId) : undefined;
      const result = detail.status === 'fulfilled' ? detail.value : row;
      setRide(result ? { ...result, elevationProfile: row?.elevationProfile, countedSpans: row?.countedSpans } : null);
    });
    return () => { active = false; };
  }, [rideId]);

  const metrics = ride ? formatRidePresentation(ridePresentationFacts(ride, rideId, 'owner'), formatters) : null;
  const date = ride ? formatDateTime(ride.startedAt) : ABSENT_VALUE;
  const climbs = ride?.calItemization?.climbs?.length
    ?? (ride?.patterns?.length ? ride.patterns.filter((pattern) => pattern.type === 'climb').length : null);
  const projection = (status as (RideStatus & { subjectStates?: unknown }) | null)?.subjectStates
    ?? (ride as (Ride & { subjectStates?: unknown }) | null)?.subjectStates;
  const states = readSubjectStates(projection);
  // Tim S1/S2; S3 numeric caption remains empty until Tim supplies the words.
  const overlapCopy = getRideEffortTrimCopy({
    coveredEffortSeconds: status?.coveredEffortSeconds ?? ride?.coveredEffortSeconds,
    paidEffortSeconds: status?.paidEffortSeconds ?? ride?.paidEffortSeconds,
    rewardPolicy: status?.effortPolicy?.rewardPolicy ?? ride?.rewardPolicy,
  });
  // This component is mounted only after storage succeeded. No other subject
  // can inherit that success or the generic processing enum.
  if (!states.some(state => state.subject === 'storage')) states.unshift({ subject: 'storage', label: 'Saved', reason: null });
  const subjects: Record<StateSubject, string> = { storage: 'Ride', matching: 'Climbs', cal: 'CAL', position: 'Position', collection: 'DUNG' };

  return <>
    {!duplicate && <p className="upload-sheet__saved" role="status">Ride saved</p>}
    <div className="upload-sheet__group">
      <button type="button" className="rides-log__row upload-sheet__ride" data-ride-id={rideId} onClick={() => onOpenRide(rideId)} aria-label={ride?.title || (duplicate ? 'Open saved ride' : 'Open ride')}>
        <span className="rides-log__spine" aria-hidden="true">
          <ClimbShapeGlyph profile={ride?.elevationProfile ?? undefined} width={120} height={28} spans={ride?.countedSpans ?? undefined} />
        </span>
        <span className="rides-log__identity">
          <strong className="rides-log__name">{ride?.title ?? ''}</strong>
          {date !== ABSENT_VALUE && <time className="rides-log__sub" dateTime={ride?.startedAt}>
            <span className="upload-sheet__ride-date--desktop">{date}</span>
            <span className="upload-sheet__ride-date--phone">{formatDate(ride?.startedAt)}</span>
          </time>}
        </span>
        <strong className="rides-log__value">{metrics?.distance ?? ''}<span className="upload-sheet__chevron" aria-hidden="true">›</span></strong>
      </button>
    </div>
    {overlapCopy && <p className="upload-sheet__saved" role="status">{overlapCopy}</p>}
    {!duplicate && <>
      <div className="upload-sheet__group">
        <div className="upload-sheet__kv"><span>Climbs on this ride</span><span className="upload-sheet__value">{climbs == null ? '' : formatInteger(climbs)}</span></div>
        {states.map(state => <div key={state.subject} className="upload-sheet__kv upload-sheet__status" data-state-subject={state.subject}>
          <span>{subjects[state.subject]}</span><span className="upload-sheet__value">{state.label}</span>
        </div>)}
      </div>
    </>}
  </>;
}
