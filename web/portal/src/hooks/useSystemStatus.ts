/**
 * useSystemStatus - Hook for fetching system status and feature flags
 *
 * Fetches once on mount and caches the result.
 * Used to display warnings like stub mode banner.
 */

import { useState, useEffect } from 'react';
import { api, SystemStatus } from '../lib/api';

export interface SystemStatusState {
  isLoading: boolean;
  error: string | null;
  status: SystemStatus | null;
  isStubMode: boolean;
  isDev: boolean;
}

export function useSystemStatus(): SystemStatusState {
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [status, setStatus] = useState<SystemStatus | null>(null);

  useEffect(() => {
    let mounted = true;

    const fetchStatus = async () => {
      try {
        const result = await api.getStatus();
        if (mounted) {
          setStatus(result);
          setError(null);
        }
      } catch (err) {
        if (mounted) {
          setError(err instanceof Error ? err.message : 'Failed to load status');
        }
      } finally {
        if (mounted) {
          setIsLoading(false);
        }
      }
    };

    fetchStatus();

    return () => {
      mounted = false;
    };
  }, []);

  return {
    isLoading,
    error,
    status,
    isStubMode: status?.solanaStubMode ?? false,
    isDev: status?.environment === 'development',
  };
}

export default useSystemStatus;
