export const queryKeys = {
  threshold: {
    all: ['threshold'] as const,
    authority: (ownerKey: string) => ['threshold', 'authority', ownerKey] as const,
  },
  leaderboardPositions: {
    mine: () => ['leaderboard-positions', 'me'] as const,
    user: (wallet: string) => ['leaderboard-positions', 'user', wallet] as const,
  },
  analytics: {
    modelSnapshot: (ownerKey: string, revision: string, asOf: string) => ['analytics', 'model-snapshot', ownerKey, revision, asOf] as const,
    powerCurve: () => ['analytics', 'power-curve'] as const,
    ridingDays: (days: number = 182) => ['analytics', 'riding-days', days] as const,
    trainingData: (days: number = 28) => ['analytics', 'trainingData', days] as const,
  },
  feed: {
    global: (initialLimit: number = 15, pageSize: number = 10) => ['feed', 'global', initialLimit, pageSize] as const,
    list: (scope: 'global' | 'following', initialLimit: number = 15, pageSize: number = 10) => [
      'feed',
      scope,
      initialLimit,
      pageSize,
    ] as const,
    suggestedRiders: (limit: number = 4) => ['feed', 'suggestedRiders', limit] as const,
    popularClimbs: (limit: number = 6) => ['feed', 'popularClimbs', limit] as const,
    achievements: ['feed', 'achievements'] as const,
    socialCounts: (userId: string | null) => ['feed', 'socialCounts', userId] as const,
  },
  rides: {
    presentation: (ownerKey: string, id: string, revision: string, metricBasis: string) => ['rides', id, 'presentation', ownerKey, revision, metricBasis] as const,
    all: ['rides'] as const,
    list: (limit: number = 50) => ['rides', 'list', limit] as const,
    detail: (id: string) => ['rides', id] as const,
    status: (id: string) => ['rides', id, 'status'] as const,
    patterns: (id: string) => ['rides', id, 'patterns'] as const,
    telemetry: (id: string) => ['rides', id, 'telemetry'] as const,
    gps: (id: string) => ['rides', id, 'gps'] as const,
    tiles: (id: string) => ['rides', id, 'tiles'] as const,
  },
  vaults: {
    all: ['vaults'] as const,
    list: (options?: { limit?: number; offset?: number; search?: string }) => [
      'vaults',
      'list',
      options?.limit ?? null,
      options?.offset ?? 0,
      options?.search?.trim() ?? '',
    ] as const,
    myStakes: ['vaults', 'myStakes'] as const,
    detail: (id: number) => ['vaults', id] as const,
    leaderboard: (id: number) => ['vaults', id, 'leaderboard'] as const,
  },
  notifications: {
    all: ['notifications'] as const,
    lists: ['notifications', 'list'] as const,
    list: (limit: number = 20) => ['notifications', 'list', limit] as const,
    preferences: ['notifications', 'preferences'] as const,
  },
  search: {
    results: (q: string, type: 'all' | 'riders' | 'rides' | 'climbs' | 'proofs' = 'all', limit: number = 20) => [
      'search',
      q.trim(),
      type,
      limit,
    ] as const,
  },
  climbs: {
    all: ['climbs'] as const,
    list: (options?: { q?: string; bbox?: string; limit?: number }) => [
      'climbs',
      'list',
      options?.q ?? '',
      options?.bbox ?? '',
      options?.limit ?? null,
    ] as const,
    detail: (id: string) => ['climbs', 'detail', id] as const,
    effort: (id: string) => ['climbs', 'effort', id] as const,
    leaderboard: (id: string, epochNumber: number = 1, limit: number = 100) => [
      'climbs',
      'leaderboard',
      id,
      epochNumber,
      limit,
    ] as const,
  },
  publicPreview: {
    detail: (type: 'ride' | 'climb' | 'rider', id: string, endpoint: string) => [
      'publicPreview',
      type,
      id,
      endpoint,
    ] as const,
  },
  profile: {
    me: ['profile', 'me'] as const,
  },
  portfolio: {
    collectionSnapshot: (ownerKey: string, revision: string) => ['portfolio', 'collection-snapshot', ownerKey, revision] as const,
    all: ['portfolio'] as const,
    snapshot: ['portfolio', 'snapshot'] as const,
    cal: ['portfolio', 'cal'] as const,
    distributions: ['portfolio', 'distributions'] as const,
  },
} as const;
