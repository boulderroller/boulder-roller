import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { ApiError, api, NotificationsResponse } from '../../lib/api';
import { queryKeys } from '../../lib/queryKeys';
import { useSystemStatus } from '../useSystemStatus';
import { useStage1Mints } from './useStage1';
import { stage1Live } from '../../lib/stage1';

const DEFAULT_NOTIFICATIONS_LIMIT = 20;

function normalizeLimit(limit?: number): number {
  if (!Number.isFinite(limit)) {
    return DEFAULT_NOTIFICATIONS_LIMIT;
  }
  return Math.max(1, Math.floor(limit as number));
}

function isNotificationsResponse(data: unknown): data is NotificationsResponse {
  if (!data || typeof data !== 'object') return false;
  const candidate = data as Partial<NotificationsResponse>;
  return Array.isArray(candidate.notifications) && typeof candidate.unreadCount === 'number';
}

function shouldRetryNotifications(failureCount: number, error: Error): boolean {
  if (error instanceof ApiError && error.statusCode === 401) {
    return false;
  }
  return failureCount < 2;
}

function applyMarkRead(previous: NotificationsResponse, notificationId: string): NotificationsResponse {
  let unreadChanged = false;

  const notifications = previous.notifications.map((notification) => {
    if (notification.id !== notificationId || notification.read) {
      return notification;
    }

    unreadChanged = true;
    return {
      ...notification,
      read: true,
      readAt: notification.readAt ?? new Date().toISOString(),
    };
  });

  return unreadChanged
    ? {
        ...previous,
        unreadCount: Math.max(0, previous.unreadCount - 1),
        notifications,
      }
    : previous;
}

function applyMarkAllRead(previous: NotificationsResponse): NotificationsResponse {
  if (previous.unreadCount === 0) {
    return previous;
  }

  return {
    ...previous,
    unreadCount: 0,
    notifications: previous.notifications.map((notification) => (
      notification.read
        ? notification
        : { ...notification, read: true, readAt: notification.readAt ?? new Date().toISOString() }
    )),
  };
}

function updateNotificationCaches(
  queryClient: ReturnType<typeof useQueryClient>,
  updater: (previous: NotificationsResponse) => NotificationsResponse,
): void {
  queryClient.setQueriesData(
    { queryKey: queryKeys.notifications.lists },
    (current) => (isNotificationsResponse(current) ? updater(current) : current),
  );
}

export function useNotifications(options?: {
  limit?: number;
  refetchInterval?: number;
  enabled?: boolean;
}) {
  const limit = normalizeLimit(options?.limit);
  const enabled = options?.enabled ?? true;
  const { status } = useSystemStatus();
  useStage1Mints(stage1Live(status));

  const query = useQuery<NotificationsResponse>({
    queryKey: queryKeys.notifications.list(limit),
    queryFn: () => api.getNotifications({ limit }),
    enabled,
    refetchInterval: options?.refetchInterval,
    staleTime: 30_000,
    retry: shouldRetryNotifications,
  });

  const hidden = stage1Live(status) ? [] : query.data?.notifications.filter(n => n.metadata?.stage1 === true) ?? [];
  const data = query.data && hidden.length ? {
    ...query.data,
    notifications: query.data.notifications.filter(n => n.metadata?.stage1 !== true),
    // The API filters before LIMIT/count. If flag observations race, never
    // retain an unread count whose unseen rows may belong to the dark feature.
    unreadCount: query.data.notifications.filter(n => n.metadata?.stage1 !== true && !n.read).length,
  } : query.data;
  return {
    ...query,
    data,
    requestedLimit: limit,
  };
}

export function useMarkNotificationRead() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (notificationId: string) => api.markNotificationRead(notificationId),
    onMutate: async (notificationId) => {
      await queryClient.cancelQueries({ queryKey: queryKeys.notifications.lists });

      const previous = queryClient.getQueriesData<NotificationsResponse>({
        queryKey: queryKeys.notifications.lists,
      });

      updateNotificationCaches(queryClient, (current) => applyMarkRead(current, notificationId));

      return { previous };
    },
    onError: (_err, _id, context) => {
      if (context?.previous?.length) {
        context.previous.forEach(([key, data]) => {
          queryClient.setQueryData(key, data);
        });
      }
    },
  });
}

export function useMarkAllNotificationsRead() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: () => api.markAllNotificationsRead(),
    onMutate: async () => {
      await queryClient.cancelQueries({ queryKey: queryKeys.notifications.lists });

      const previous = queryClient.getQueriesData<NotificationsResponse>({
        queryKey: queryKeys.notifications.lists,
      });

      updateNotificationCaches(queryClient, applyMarkAllRead);

      return { previous };
    },
    onError: (_err, _variables, context) => {
      if (context?.previous?.length) {
        context.previous.forEach(([key, data]) => {
          queryClient.setQueryData(key, data);
        });
      }
    },
  });
}
