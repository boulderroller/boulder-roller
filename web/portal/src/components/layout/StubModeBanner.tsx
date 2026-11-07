/**
 * StubModeBanner - Warning banner shown when Solana is in stub mode
 *
 * Displays a prominent warning at the top of the app when SOLANA_STUB=true.
 * This ensures developers know they're not making real blockchain transactions.
 */

import { AlertTriangle, X } from 'lucide-react';
import { useState } from 'react';
import { useSystemStatus } from '../../hooks/useSystemStatus';

export function StubModeBanner() {
  const { isStubMode, isDev, isLoading, status } = useSystemStatus();
  const [isDismissed, setIsDismissed] = useState(false);

  // Don't show if not in stub mode, or loading, or dismissed
  if (isLoading || !isStubMode || isDismissed) {
    return null;
  }

  return (
    <div
      className="portal-stub-banner"
      role="status"
    >
      <AlertTriangle className="portal-stub-banner__icon" aria-hidden="true" />
      <span className="portal-stub-banner__message">
        Stub Mode Active - Solana transactions are simulated
        {isDev && ' (dev environment)'}
      </span>
      {status?.version && (
        <span className="portal-stub-banner__version"> v{status.version}</span>
      )}
      <button
        type="button"
        onClick={() => setIsDismissed(true)}
        className="portal-stub-banner__dismiss"
        aria-label="Dismiss stub mode banner"
        title="Dismiss"
      >
        <X className="portal-stub-banner__dismiss-icon" aria-hidden="true" />
      </button>
    </div>
  );
}

export default StubModeBanner;
