import { useLocation, useNavigate } from 'react-router-dom';
import UploadActivitySurface from '../components/upload/UploadActivitySurface';
import { readUploadReturnTo } from '../lib/uploadRoute';

export default function Upload({ onClose }: { onClose?: () => void }) {
  const location = useLocation();
  const navigate = useNavigate();
  const returnTo = readUploadReturnTo(location.state);

  return (
    <UploadActivitySurface
      onClose={onClose ?? (() => navigate(returnTo, { replace: true }))}
      onOpenRide={(rideId) => {
        onClose?.();
        navigate(`/activities/${encodeURIComponent(rideId)}`, { replace: location.pathname === '/upload' });
      }}
    />
  );
}
