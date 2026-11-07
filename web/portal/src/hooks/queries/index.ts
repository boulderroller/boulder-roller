export { useRides } from './useRides';
export { useRide, useRideStatus, useRidePatterns, useRideTelemetry, useRideTiles, useRideGps } from './useRide';
export { useTrainingData, usePowerCurve, useRidingDays } from './useAnalytics';
export { useNotifications, useMarkNotificationRead, useMarkAllNotificationsRead } from './useNotifications';
export { useClimbs, useClimbDetail, useClimbLeaderboard } from './useClimbs';
export { usePublicPreview } from './usePublicPreview';
export { useVaults, useMyVaultStakes, useVault, useVaultLeaderboard } from './useVaults';
export { useProfile, useMyLeaderboardPositions, useUserLeaderboardPositions } from './useProfile';
export { usePortfolio, usePortfolioSnapshot, useCALBalance, useDistributions } from './usePortfolio';
export { useUploadRide } from './useUploadRide';
export {
  useGlobalFeed,
  useSuggestedRiders,
  usePopularClimbs,
  useFeedSocialCounts,
  useFollowSuggestedRider,
} from './useFeed';

// Frozen shared read-model exports for the audit window; no new fetching hooks.
export type {
  ReadModelCoverage,
  CollectionSnapshot,
  RideMetricBasis,
  RidePresentation,
  TrainingModelSnapshot,
  ZoneShareDenominator,
  TraceReductionDescriptor,
  FeedItemResultSummary,
  NotificationTransition,
} from '../../lib/api';
