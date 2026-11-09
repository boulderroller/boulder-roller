import { Link } from 'react-router-dom';
import type { PageViewer } from '../ride/RidePageComponents';

export function RideAnalysisLink({
  onOpen,
  href,
  viewer = 'owner',
}: {
  onOpen?: () => void;
  href?: string;
  viewer?: PageViewer;
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
    <div className="ride-analysis-link">
      {href ? (
        <Link className="ride-page-kv" to={href}>
          {content}
        </Link>
      ) : (
        <button type="button" className="ride-page-kv" onClick={onOpen}>
          {content}
        </button>
      )}
    </div>
  );
}
