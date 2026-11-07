import { storeReturnIntent } from '../../lib/authHandoff';
import { type ReactNode } from 'react';
import { Link, useLocation, useNavigate } from 'react-router-dom';
import { BackgroundFetchIndicator } from '../loading/LoadingSystem';
import { RetainedRoom } from '../portal/FailureSpecies';
import '../../styles/portal-public-door.css';

export function PublicRoom({
  children,
}: {
  children: (openDoor: () => void) => ReactNode;
}) {
  const location = useLocation();
  const navigate = useNavigate();
  const openDoor = () => {
    try {
      storeReturnIntent(
        `${location.pathname}${location.search}${location.hash}`,
      );
    } catch {
      /* Storage may be unavailable. */
    }
    navigate('/', { state: { fromPublicPreview: true } });
  };
  return (
    <div className="public-room portal-shell">
      <header className="portal-shell__header">
        <Link className="portal-shell__brand" to="/">
          <span className="portal-shell__brand-mark" aria-hidden="true" />
          Boulder Roller
        </Link>
        <button
          className="public-room-sign-in"
          type="button"
          onClick={openDoor}
        >
          Sign in
        </button>
        <BackgroundFetchIndicator />
      </header>
      <main><RetainedRoom>{children(openDoor)}</RetainedRoom></main>
    </div>
  );
}
