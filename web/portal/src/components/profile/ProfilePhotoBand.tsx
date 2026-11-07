import { formatDate } from '../../lib/formatters';
import type { ProfilePhoto } from './groundModel';

// The photo band (Profile — Ground, third pass, Tim-ratified 2026-09-02):
// the rider's five most recent ride photos, eight pixels apart, no label,
// no count. Each opens its ride. Fewer fill from the left; none means the
// band is absent, never an empty object.

interface ProfilePhotoBandProps {
  photos: ProfilePhoto[];
  onOpenRide: (rideId: string) => void;
}

export default function ProfilePhotoBand({ photos, onOpenRide }: ProfilePhotoBandProps) {
  if (photos.length === 0) return null;
  return (
    <div className="profile-photos" data-photo-count={photos.length}>
      {photos.map((photo) => {
        const when = formatDate(photo.startedAt);
        return (
          <button
            key={photo.key}
            type="button"
            className="profile-photos__tile"
            aria-label={photo.title ? `${photo.title}, ${when}` : when}
            onClick={() => onOpenRide(photo.rideId)}
          >
            <img src={photo.url} alt="" loading="lazy" />
            <span className="profile-photos__caption" aria-hidden="true">
              {photo.title ? <b>{photo.title}</b> : <b>{when}</b>}
              {photo.title ? <i>{when}</i> : null}
            </span>
          </button>
        );
      })}
    </div>
  );
}
