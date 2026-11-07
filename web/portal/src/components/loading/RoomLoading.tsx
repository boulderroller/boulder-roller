import { lazy, Suspense, type ReactNode } from 'react';
import { useLocation } from 'react-router-dom';
import { Slot, SlotRows } from './Slot';
import { RideRoomGeography } from '../ride/RideRoom';
import ClimbGeography from '../climb/ClimbGeography';
import '../../styles/portal-profile-room.css';

const ProfileGroundMap = lazy(() => import('../profile/ProfileGroundMap'));
const empty: never[] = [];
const noop = () => {};

export function IdentitySlots({ climb = false, rider = false }: { climb?: boolean; rider?: boolean }) {
  return <>
    {!climb && <div className="ride-room-card-head"><Slot variant="avatar" /><span className="ledger-slot-copy"><Slot width="12ch" /><Slot width="20ch" /></span></div>}
    <h1><Slot width="13ch" /></h1><Slot variant="glyph" />
    <dl className={climb ? 'climb-summary' : 'ride-room-stats'}>{(rider ? ['Rides', 'Seats', 'Crowns'] : climb ? ['Distance', 'Elevation', 'Grade'] : ['Distance', 'Time', 'Elevation']).map(label => <div key={label}><dt>{label}</dt><dd><Slot variant="number" width="6ch" /></dd></div>)}</dl>
  </>;
}

export function RideAnalysisSlots() {
  return <div className="ride-analysis-room" aria-busy="true">
    <div className="ride-analysis-back"><Slot width="18ch" /><Slot width="16ch" /></div>
    <header className="ride-analysis-head"><h1>Ride analysis</h1></header>
    <div className="ride-analysis-scope">Whole ride</div>
    <dl className="ride-room-stats ride-analysis-stats">{['Distance', 'Elevation', 'Time', 'Power'].map(label => <div key={label}><dt>{label}</dt><dd><Slot variant="number" /></dd></div>)}</dl>
    <div className="ride-instruments">{['Elevation', 'Power', 'Heart rate', 'Cadence', 'Speed'].map(label => <div className="ride-analysis-loading-instrument" key={label}><span>{label}</span><Slot variant="number" /></div>)}</div>
    <div className="ride-analysis-columns">{['Power curve', 'Time in zones'].map(label => <section className="ride-analysis-column" key={label}><header className="ride-room-heading">{label}</header><SlotRows count={5} /></section>)}</div>
    <span className="sr-only" role="status">Loading ride analysis</span>
  </div>;
}

/** URL-only composition: these are the same ground, card, band and row containers. */
export function RoomLoading({ failure }: { failure?: ReactNode } = {}) {
  const { pathname, search } = useLocation();
  const tab = new URLSearchParams(search).get('tab') || 'overview';
  if (pathname.endsWith('/analysis')) return <RideAnalysisSlots />;
  const ride = /^\/(activities|rides)\//.test(pathname);
  const climb = /^\/(climbs|segments)\//.test(pathname);
  const profile = pathname === '/profile' || /^\/(riders|athletes)\//.test(pathname);
  const kind = ride ? 'ride' : climb ? 'climb' : profile ? 'rider' : pathname.slice(1) || 'feed';
  return <div data-loading-room={kind} aria-busy={!failure}>
    {ride ? <div className="portal-object-page portal-object-page--ride" data-object-page="ride"><RideRoomGeography samples={empty} spans={empty} power={empty} identity={failure ? null : <IdentitySlots />}>{failure || <SlotRows count={6} />}</RideRoomGeography></div>
      : climb ? <div className="climb-detail-page portal-object-page portal-object-page--climb" data-object-page="climb"><ClimbGeography identity={failure ? null : <IdentitySlots climb />}><div className="climb-detail-columns">{failure || <><section><h2>Leaderboard</h2><SlotRows count={10} /></section><section><h2>Vault</h2><SlotRows count={4} /></section></>}</div></ClimbGeography></div>
      : profile ? <div className="profile-page portal-object-page portal-object-page--rider" data-object-page="rider"><div className="portal-frame">
        <div className={tab === 'overview' ? 'profile-ground' : 'profile-ground profile-ground--masthead'} data-object-layer="rider-ground"><Suspense fallback={null}><ProfileGroundMap ground={empty} onOpenClimb={noop} compact={tab !== 'overview'} /></Suspense><div className="profile-ground__fade" />
          <div className={tab === 'overview' ? 'profile-ledger-layer' : 'profile-masthead'}><div className="loading-rider-identity">{!failure && <IdentitySlots rider />}</div></div>
        </div><div className="profile-tabs">{['Overview', 'Rides', 'Training', 'Portfolio'].map(word => <span key={word} className="profile-tabs__tab">{word}</span>)}</div>{failure || <SlotRows count={6} />}
      </div></div>
      : <div className={kind === 'feed' ? 'feed-page portal-page' : 'portal-page'}><div className="portal-frame">
        {kind === 'feed' && <div className="feed-lens"><span>Everyone</span><span>Following</span></div>}
        <SlotRows count={kind === 'feed' ? 10 : 6} />
      </div></div>}
    {!failure && <span className="sr-only" role="status">Loading page content.</span>}
  </div>;
}
