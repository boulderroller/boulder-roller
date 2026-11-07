import { type InfiniteData, useInfiniteQuery, useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Activity, FeedResponse, HomeFeedResponse, PopularClimb, SuggestedRider, api } from '../../lib/api';
import { queryKeys } from '../../lib/queryKeys';

interface FeedPageParam {
  before?: string;
  limit: number;
}

interface FeedPage {
  activities: Activity[];
  hasMore: boolean;
  nextCursor?: string;
  home?: HomeFeedResponse;
}

interface FeedSocialCounts {
  followerCount: number;
  followingCount: number;
}

function normalizeFeedPage(
  response: FeedResponse,
  fallbackLimit: number,
  home?: HomeFeedResponse,
): FeedPage {
  const activities = response.activities ?? [];
  const hasMore = response.hasMore ?? response.has_more ?? activities.length >= fallbackLimit;
  const nextCursor = response.nextCursor ?? response.next_cursor ?? (
    hasMore && activities.length > 0
      ? activities[activities.length - 1].occurredAt ?? activities[activities.length - 1].createdAt
      : undefined
  );

  const resolvedCursor = hasMore && nextCursor
    ? nextCursor
    : undefined;

  return {
    activities,
    hasMore,
    nextCursor: resolvedCursor,
    home,
  };
}

export function useGlobalFeed(options?: {
  scope?: 'global' | 'following';
  initialLimit?: number;
  pageSize?: number;
  enabled?: boolean;
}) {
  const scope = options?.scope ?? 'global';
  const initialLimit = options?.initialLimit ?? 15;
  const pageSize = options?.pageSize ?? 10;

  return useInfiniteQuery<FeedPage, Error, InfiniteData<FeedPage>, ReturnType<typeof queryKeys.feed.list>, FeedPageParam>({
    queryKey: queryKeys.feed.list(scope, initialLimit, pageSize),
    placeholderData: undefined,
    initialPageParam: { limit: initialLimit },
    queryFn: async ({ pageParam }) => {
      const feedOptions = pageParam.before
        ? { before: pageParam.before, limit: pageParam.limit }
        : { limit: pageParam.limit };
      if (!pageParam.before) {
        const home = await api.getHomeFeed({
          scope,
          limit: pageParam.limit,
          sidecarLimit: 6,
        });
        return normalizeFeedPage(home.feed, pageParam.limit, home);
      }

      const response = scope === 'following'
        ? await api.getFeed(feedOptions)
        : await api.getGlobalFeed(feedOptions);

      return normalizeFeedPage(response, pageParam.limit);
    },
    getNextPageParam: (lastPage) => (
      lastPage.hasMore && lastPage.nextCursor
        ? { before: lastPage.nextCursor, limit: pageSize }
        : undefined
    ),
    enabled: options?.enabled ?? true,
    staleTime: 30_000,
  });
}

export function useSuggestedRiders(limit: number = 4, enabled: boolean = true) {
  return useQuery<SuggestedRider[]>({
    queryKey: queryKeys.feed.suggestedRiders(limit),
    queryFn: async () => {
      const response = await api.getSuggestedRiders(limit);
      return response.suggestions ?? [];
    },
    enabled,
    staleTime: 60_000,
  });
}

export function usePopularClimbs(limit: number = 6, enabled: boolean = true) {
  return useQuery<PopularClimb[]>({
    queryKey: queryKeys.feed.popularClimbs(limit),
    queryFn: async () => {
      const response = await api.getPopularClimbs(limit);
      return response.climbs ?? [];
    },
    enabled,
    staleTime: 60_000,
  });
}

export function useFeedSocialCounts(userId: string | null, enabled: boolean = true) {
  return useQuery<FeedSocialCounts>({
    queryKey: queryKeys.feed.socialCounts(userId),
    queryFn: async () => {
      if (!userId) {
        return { followerCount: 0, followingCount: 0 };
      }

      const [followers, following] = await Promise.all([
        api.getFollowers(userId),
        api.getFollowing(userId),
      ]);

      return {
        followerCount: followers?.length ?? 0,
        followingCount: following?.length ?? 0,
      };
    },
    enabled: enabled && !!userId,
    staleTime: 60_000,
  });
}

export function useFollowSuggestedRider(userId: string | null) {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: async ({ riderId }: { riderId: string }) => {
      await api.followUser(riderId);
      return riderId;
    },
    onMutate: async ({ riderId }) => {
      await Promise.all([
        queryClient.cancelQueries({ queryKey: ['feed', 'suggestedRiders'] }),
        userId
          ? queryClient.cancelQueries({ queryKey: queryKeys.feed.socialCounts(userId) })
          : Promise.resolve(),
      ]);

      const previousSuggestions = queryClient.getQueriesData<SuggestedRider[]>({
        queryKey: ['feed', 'suggestedRiders'],
      });
      const previousCounts = userId
        ? queryClient.getQueryData<FeedSocialCounts>(queryKeys.feed.socialCounts(userId))
        : undefined;

      queryClient.setQueriesData(
        { queryKey: ['feed', 'suggestedRiders'] },
        (current) => Array.isArray(current)
          ? current.map((rider) => (
              rider.id === riderId
                ? { ...rider, isFollowing: true }
                : rider
            ))
          : current,
      );

      if (userId) {
        queryClient.setQueryData<FeedSocialCounts | undefined>(
          queryKeys.feed.socialCounts(userId),
          (current) => current
            ? {
                ...current,
                followingCount: current.followingCount + 1,
              }
            : current,
        );
      }

      return {
        previousSuggestions,
        previousCounts,
      };
    },
    onError: (_error, _variables, context) => {
      context?.previousSuggestions?.forEach(([key, data]) => {
        queryClient.setQueryData(key, data);
      });

      if (userId && context?.previousCounts) {
        queryClient.setQueryData(queryKeys.feed.socialCounts(userId), context.previousCounts);
      }
    },
    onSettled: () => {
      void queryClient.invalidateQueries({ queryKey: ['feed', 'suggestedRiders'] });
      if (userId) {
        void queryClient.invalidateQueries({ queryKey: queryKeys.feed.socialCounts(userId) });
      }
    },
  });
}
