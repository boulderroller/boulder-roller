import { Link } from 'react-router-dom';
import type { RoomViewer } from '../ride/RideRoom';

export function RideRoomDoor({
  onOpen,
  href,
  viewer = 'owner',
}: {
  onOpen?: () => void;
  href?: string;
  viewer?: RoomViewer;
}) {
  const content = (
    <>
      <span>Ride analysis</span>
      {viewer === 'stranger' ? (
        <span>Sign in</span>
      ) : (
        <span aria-hidden="true">›</span>
      )}
    </>
  );
  return (
    <div className="ride-room-door">
      {href ? (
        <Link className="ride-room-kv" to={href}>
          {content}
        </Link>
      ) : (
        <button type="button" className="ride-room-kv" onClick={onOpen}>
          {content}
        </button>
      )}
    </div>
  );
}
