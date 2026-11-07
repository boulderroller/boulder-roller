import { QueryClient } from '@tanstack/react-query';

function getErrorStatus(error: unknown): number | undefined {
  if (!error || typeof error !== 'object') return undefined;
  if ('status' in error && typeof (error as { status?: unknown }).status === 'number') {
    return (error as { status: number }).status;
  }
  return undefined;
}

export const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 30_000,
      gcTime: 600_000,
      refetchOnWindowFocus: false,
      retry: (failureCount, error) => {
        const status = getErrorStatus(error);
        if (status && status >= 400 && status < 500 && status !== 429) return false;
        return failureCount < 2;
      },
    },
  },
});
