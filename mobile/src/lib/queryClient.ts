/**
 * TanStack Query Client Configuration
 *
 * Central QueryClient for server state management.
 * Used for user profile, points balance, rides, feed, notifications, etc.
 */

import { QueryClient } from '@tanstack/react-query';

export const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 60_000,        // 1 minute before data is considered stale
      gcTime: 5 * 60_000,       // 5 minutes before inactive data is garbage collected
      retry: 2,                 // Retry failed requests twice
      retryDelay: (attempt) => Math.min(1000 * 2 ** attempt, 10_000),
      refetchOnWindowFocus: false, // Not applicable on mobile; use AppState instead
    },
    mutations: {
      retry: 0,                 // Don't auto-retry mutations
    },
  },
});
