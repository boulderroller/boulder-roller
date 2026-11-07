import { FailureSheet } from './portal/FailureSpecies';
import { Slot } from './loading/Slot';
import { Component, ErrorInfo, ReactNode } from 'react';
import { TriangleAlert } from 'lucide-react';
import { captureException } from '../lib/sentry';
import {
  PortalFrame,
  PortalPage,
  PortalPanel,
  PortalPanelBody,
} from './portal/PortalSpine';
import {
  hasAttemptedStaleChunkRecovery,
  isDynamicImportFetchError,
  recoverFromDynamicImportError,
} from '../lib/staleChunkRecovery';

interface Props {
  children: ReactNode;
  fallback?: ReactNode;
}

interface State {
  hasError: boolean;
  error: Error | null;
}

function FallbackButton({
  children,
  onClick,
  variant = 'primary',
}: {
  children: ReactNode;
  onClick: () => void;
  variant?: 'primary' | 'secondary';
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={`error-boundary-button ${variant === 'primary' ? 'portal-action-button' : 'portal-sort-button'}`}
    >
      {children}
    </button>
  );
}

/**
 * ErrorBoundary - Catches React errors and shows fallback UI
 * Prevents entire app from crashing when a component fails
 */
export class ErrorBoundary extends Component<Props, State> {
  public state: State = {
    hasError: false,
    error: null,
  };

  public static getDerivedStateFromError(error: Error): State {
    return { hasError: true, error };
  }

  public componentDidCatch(error: Error, errorInfo: ErrorInfo) {
    console.error('ErrorBoundary caught an error:', error, errorInfo);
    captureException(error, {
      extra: {
        componentStack: errorInfo.componentStack,
      },
    });
    recoverFromDynamicImportError(error);
  }

  private handleReset = () => {
    if (isDynamicImportFetchError(this.state.error)) {
      window.location.reload();
      return;
    }
    this.setState({ hasError: false, error: null });
  };

  public render() {
    if (this.state.hasError) {
      if (this.props.fallback) {
        return this.props.fallback;
      }

      const staleChunkError = isDynamicImportFetchError(this.state.error);
      const staleChunkRecoveryAttempted = staleChunkError && hasAttemptedStaleChunkRecovery();

      return <FailureSheet shell title={staleChunkRecoveryAttempted ? 'Portal update needed' : <Slot width="12ch" />}
        description={staleChunkRecoveryAttempted ? 'The portal changed while this tab was open. Refresh to load the latest version.' : 'The portal hit an unexpected error. Your data is safe.'}
        action={<button type="button" onClick={this.handleReset}>{staleChunkRecoveryAttempted ? 'Refresh' : 'Try again'}</button>}
        doors={[{ label: 'Feed', href: '/' }, { label: 'Map', href: '/climbs' }, { label: 'Rides', href: '/profile?tab=rides' }]} />;

    }

    return this.props.children;
  }
}
