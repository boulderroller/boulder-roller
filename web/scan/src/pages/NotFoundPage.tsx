import { useEffect } from 'react';
import { Link } from 'react-router-dom';
import { composeBrowserTitle } from '../../../portal/server/browser-title';

export default function NotFoundPage() {
  useEffect(() => {
    document.title = composeBrowserTitle(null, 'Not found', 'BoulderScan');
    return () => {
      document.title = 'BoulderScan';
    };
  }, []);
  return (
    <div className="state-card">
      <div className="state-card__eyebrow">Not Found</div>
      <h2>No BoulderScan page exists here.</h2>
      <p>The requested climb, transaction, account, or route could not be resolved.</p>
      <div className="state-card__actions">
        <Link className="search-button" to="/">
          Back to Observatory
        </Link>
      </div>
    </div>
  );
}
