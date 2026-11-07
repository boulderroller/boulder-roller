import { QueryClient, keepPreviousData } from '@tanstack/react-query';

function getErrorStatus(error: unknown): number | undefined {
  if (!error || typeof error !== 'object') return undefined;

  const maybeStatus = (error as { status?: number }).status;
  if (typeof maybeStatus === 'number') return maybeStatus;

  const statusCode = (error as { statusCode?: number }).statusCode;
  if (typeof statusCode === 'number') return statusCode;

  const responseStatus = (error as { response?: { status?: number } }).response?.status;
  if (typeof responseStatus === 'number') return responseStatus;

  return undefined;
}

export const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 45_000,
      gcTime: 600_000,
      placeholderData: keepPreviousData,
      refetchOnWindowFocus: false,
      refetchOnReconnect: true,
      retry: (failureCount, error) => {
        const status = getErrorStatus(error);

        // Don't retry on most client errors except rate limits.
        if (status && status >= 400 && status < 500 && status !== 429) return false;
        return failureCount < 2;
      },
    },
    mutations: {
      retry: (failureCount, error) => {
        const status = getErrorStatus(error);

        if (status && status >= 400 && status < 500 && status !== 429) return false;
        return failureCount < 1;
      },
    },
  },
});

export function clearViewerQueryCache(): void {
  queryClient.clear();
}
