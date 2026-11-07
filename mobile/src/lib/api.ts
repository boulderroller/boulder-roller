/**
 * BoulderRoller Mobile API Client
 *
 * Handles all backend communication. Mirrors patterns from the web portal
 * (web/portal/src/lib/api.ts) but adapted for React Native:
 *   - Reads access token from Zustand auth store (synchronous)
 *   - Automatic 401 -> refresh -> retry logic
 *   - Sends refresh token in request body (not cookies)
 *   - No browser-specific APIs
 */

import { API_URL } from '../constants/config';
import { useAuthStore } from '../stores/authStore';
import { clearTokens } from '../services/secureStorage';
import type { PreparedNativeImageUpload } from './imageUpload';
import type { RoutePreview } from './routePreview';

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export type RideVisibility = 'public' | 'followers' | 'private';

export type ViewerRelationship = 'self' | 'following' | 'none' | 'blocked';

export interface PublicRiderRef {
  contractVersion?: 'public_rider_ref.v1';
  id?: string | null;
  username?: string | null;
  displayName?: string | null;
  avatarUrl?: string | null;
  isPublic?: boolean | null;
  viewerRelationship?: ViewerRelationship;
}

export interface PrivacyState {
  visibility: RideVisibility;
  canView: boolean;
  isOwner: boolean;
  isFollower: boolean;
  redactGps: boolean;
  protocolPublic: boolean;
  protocolPublicFields: string[];
  reason: string;
}

export type LinkTargetType =
  | 'rider'
  | 'ride'
  | 'ride_media'
  | 'climb'
  | 'record_board'
  | 'local_legend'
  | 'proof'
  | 'scan_tx'
  | 'scan_account'
  | 'report'
  | 'comment'
  | 'feed_event';

export type PrimaryAction =
  | 'open_rider'
  | 'open_ride'
  | 'open_climb'
  | 'open_scan'
  | 'open_report'
  | 'open_comment'
  | 'open_feed_event'
  | 'unavailable';

export interface LinkTarget {
  contractVersion?: 'target_action.v1';
  type: LinkTargetType;
  id?: string | null;
  label?: string | null;
  source?: string | null;
  metadata?: Record<string, unknown>;
}

export interface ViewerCapabilities {
  contractVersion?: 'viewer_capabilities.v1';
  canView: boolean;
  canFollow?: boolean;
  canKudos?: boolean;
  canComment?: boolean;
  canShare?: boolean;
  canReport?: boolean;
  canEdit?: boolean;
  canOpenProof?: boolean;
  canOpenScan?: boolean;
}

export interface PrivacySettings {
  contractVersion: 'privacy.v1';
  profileVisibility: 'public' | 'private';
  defaultRideVisibility: RideVisibility;
  rideOverrideMode: 'optional';
  protocolPublicFields: string[];
}

export type FeedEventType =
  | 'ride_completed'
  | 'ride_under_review'
  | 'climb_completed'
  | 'record_rank_moved'
  | 'local_legend_moved'
  | 'achievement_unlocked'
  | 'comment_created'
  | 'follow_created'
  | 'report_resolved'
  | 'social';

export type FeedActor = PublicRiderRef;

export type FeedTarget = LinkTarget;

export interface FeedActivity {
  contractVersion?: 'feed.v1';
  id: string;
  type: string;
  eventType?: FeedEventType;
  title: string;
  createdAt: string;
  occurredAt?: string;
  status?: string | null;
  actor?: FeedActor | null;
  user?: FeedActor | null;
  target?: FeedTarget | null;
  primaryAction?: PrimaryAction;
  viewerCapabilities?: ViewerCapabilities;
  privacy?: PrivacyState | null;
  metadata?: {
    distanceM?: number | null;
    elevationM?: number | null;
    durationS?: number | null;
    durationSec?: number | null;
    climbCount?: number | null;
    climbs?: number | null;
    points?: number | null;
    tss?: number | null;
    location?: string | null;
    region?: string | null;
    climbName?: string | null;
    vaultName?: string | null;
    roadName?: string | null;
    rank?: number | null;
    recordBoardRank?: number | null;
    place?: number | null;
    achievementName?: string | null;
    milestoneName?: string | null;
    rideId?: string | null;
    climbId?: string | null;
    riderId?: string | null;
    userId?: string | null;
    routePreview?: RoutePreview | null;
    status?: string | null;
    dungEarned?: number | null;
    calEarned?: number | null;
    kudosCount?: number;
    commentCount?: number;
    viewerHasKudos?: boolean;
    viewerReported?: boolean;
    reportStatus?: string | null;
    visibility?: RideVisibility;
    privacy?: PrivacyState | null;
    media?: RideMedia[];
    primaryMedia?: RideMedia | null;
  };
}

export interface FeedResponse {
  contractVersion?: 'feed.v1';
  activities: FeedActivity[];
  hasMore?: boolean;
  nextCursor?: string | null;
  message?: string;
}

export interface HomeFeedResponse {
  contractVersion: 'feed_home.v1';
  scope: 'following' | 'global';
  viewer: {
    authenticated: boolean;
    userId?: string | null;
    wallet?: string | null;
  };
  feed: FeedResponse;
  suggestedRiders: unknown[];
  popularClimbs: ClimbSummary[];
  achievements: unknown[];
  socialCounts: {
    followerCount: number;
    followingCount: number;
  };
  notifications: {
    unreadCount: number;
  };
}

export interface LinkAccess {
  canView: boolean;
  reason: string;
  protocolPublic: boolean;
  requiresAuth: boolean;
}

export interface LinkSharePayload {
  title: string;
  text: string;
  url: string;
}

export interface LinkOpenGraphPayload extends LinkSharePayload {
  type: string;
}

export interface ResolvedLink {
  contractVersion: 'link.v1';
  status: 'resolved' | 'forbidden' | 'missing';
  target: LinkTarget;
  primaryAction?: PrimaryAction;
  webPath: string;
  canonicalUrl: string;
  appUrl: string;
  externalUrl?: string | null;
  title: string;
  description: string;
  access: LinkAccess;
  viewerCapabilities?: ViewerCapabilities;
  metadata: Record<string, unknown>;
  scanState?: 'pending' | 'recorded' | 'finalized' | 'missing' | 'failed' | 'off_chain_only' | 'private' | null;
  scanTargets?: ScanTarget[];
  share: LinkSharePayload;
  openGraph: LinkOpenGraphPayload;
}

export interface ScanTarget {
  contractVersion?: 'scan.v1';
  type: 'transaction' | 'account' | 'vault' | 'proof' | 'wallet' | string;
  id: string;
  state: 'pending' | 'recorded' | 'finalized' | 'missing' | 'failed' | 'off_chain_only' | 'private' | string;
  label: string;
  url: string;
  source: string;
  metadata?: Record<string, unknown>;
}

export interface LinkSchemaTarget {
  type: LinkTargetType;
  webPathTemplate: string;
  aliases: string[];
}

export interface LinkSchemaResponse {
  contractVersion: 'link.v1';
  webOrigin: string;
  scanOrigin: string;
  scanContractVersion?: 'scan.v1';
  targets: LinkSchemaTarget[];
}

export type SearchType = 'all' | 'riders' | 'rides' | 'climbs' | 'proofs';
export type SearchResultType = 'rider' | 'ride' | 'climb' | 'proof';

export interface SearchStat {
  label: string;
  value: string;
}

export interface SearchImage {
  kind: 'avatar' | 'route' | 'climb' | string;
  url?: string | null;
}

export interface SearchResult {
  contractVersion: 'search.v1';
  id: string;
  type: SearchResultType;
  title: string;
  subtitle: string;
  summary?: string | null;
  target: LinkTarget;
  primaryAction?: PrimaryAction;
  viewerCapabilities?: ViewerCapabilities;
  webPath: string;
  source: 'backend' | 'indexer' | string;
  privacy?: PrivacyState | null;
  stats: SearchStat[];
  image?: SearchImage | null;
  score: number;
  matchedFields: string[];
  scanState?: ResolvedLink['scanState'];
  scanTargets?: ScanTarget[];
  metadata: Record<string, unknown> & {
    rider?: PublicRiderRef | null;
    owner?: PublicRiderRef | null;
  };
}

export interface SearchResponse {
  contractVersion: 'search.v1';
  query: string;
  normalizedQuery: string;
  type: SearchType;
  results: SearchResult[];
  hasMore: boolean;
}

export interface SearchSuggestionSection {
  id: string;
  title: string;
  results: SearchResult[];
}

export interface SearchSuggestionsResponse {
  contractVersion: 'search.v1';
  sections: SearchSuggestionSection[];
}

export interface SearchSchemaResponse {
  contractVersion: 'search.v1';
  types: SearchType[];
  resultTypes: SearchResultType[];
  targetContractVersion: 'link.v1';
  targets: LinkTargetType[];
  capabilities?: string[];
}

export type NotificationEventType =
  | 'comment_created'
  | 'follow_created'
  | 'kudos_created'
  | 'ride_completed'
  | 'ride_finalized'
  | 'ride_failed'
  | 'leaderboard_entered'
  | 'leaderboard_bumped'
  | 'record_rank_moved'
  | 'rank_changed'
  | 'kom_achieved'
  | 'local_legend_moved'
  | 'achievement_unlocked'
  | 'payout_received'
  | 'stake_payout'
  | 'legend_payout'
  | 'report_resolved'
  | 'proof_updated'
  | 'settlement_finalized'
  | 'tier_unlocked'
  | 'login_new_device'
  | 'session_revoked'
  | 'strava_revoked'
  | 'system';

export type NotificationActor = PublicRiderRef;

export type NotificationTarget = LinkTarget;

export interface AppNotification {
  contractVersion?: 'notification.v1';
  id: string;
  notificationType: NotificationEventType;
  legacyType?: string | null;
  eventType?: NotificationEventType;
  title: string;
  message: string;
  actor?: NotificationActor | null;
  target?: NotificationTarget | null;
  primaryAction?: PrimaryAction;
  viewerCapabilities?: ViewerCapabilities;
  metadata?: Record<string, unknown>;
  deliveryStatus?: 'pending' | 'in_app_delivered' | 'suppressed' | 'failed' | string;
  deliveryChannels?: string[];
  dedupeKey?: string | null;
  vaultSignature?: string | null;
  read: boolean;
  readAt?: string | null;
  createdAt: string;
  occurredAt?: string;
  actionUrl?: string | null;
}

export interface NotificationsResponse {
  contractVersion?: 'notification.v1';
  notifications: AppNotification[];
  unreadCount: number;
}

export interface NotificationPreferences {
  emailEnabled?: boolean;
  pushEnabled?: boolean;
  inAppEnabled?: boolean;
  newFollower?: boolean;
  rideCompleted?: boolean;
  achievementUnlocked?: boolean;
  komBeaten?: boolean;
  stakingReward?: boolean;
  socialActivity?: boolean;
  leaderboardUpdates?: boolean;
  payoutAlerts?: boolean;
  systemAnnouncements?: boolean;
  securityAlerts?: boolean;
  connectedAppAlerts?: boolean;
  rideUpdates?: boolean;
  followCreated?: boolean;
  commentCreated?: boolean;
  kudosCreated?: boolean;
  rideFinalized?: boolean;
  rideFailed?: boolean;
  leaderboardEntered?: boolean;
  leaderboardBumped?: boolean;
  rankChanged?: boolean;
  recordRankMoved?: boolean;
  komAchieved?: boolean;
  localLegendMoved?: boolean;
  payoutReceived?: boolean;
  stakePayout?: boolean;
  legendPayout?: boolean;
  reportResolved?: boolean;
  proofUpdated?: boolean;
  settlementFinalized?: boolean;
  tierUnlocked?: boolean;
  loginNewDevice?: boolean;
  sessionRevoked?: boolean;
  stravaRevoked?: boolean;
}

export interface User {
  id?: string;
  wallet: string;
  username?: string | null;
  displayName: string | null;
  bio: string | null;
  avatarUrl: string | null;
  isPublic?: boolean;
  privacy?: PrivacyState | null;
  defaultRideVisibility?: RideVisibility;
  createdAt: string;
  totalRides: number;
  totalDistanceKm?: number;
  totalElevationM?: number;
  totalDungEarned?: number;
  totalKcals?: number;
  totalDurationSec?: number;
  calEarnedToday?: number;
  dungEarnedToday?: number;
  location?: string | null;
  level?: number;
}

export interface UserPublic {
  id: string;
  wallet: string;
  rider?: PublicRiderRef | null;
  username?: string | null;
  displayName: string | null;
  bio: string | null;
  avatarUrl: string | null;
  isPublic: boolean;
  privacy?: PrivacyState | null;
  createdAt: string | null;
  totalRides: number;
  totalDistanceKm: number;
  totalElevationM: number;
  totalDungEarned: number;
  followerCount?: number;
  followingCount?: number;
}

export interface FollowState {
  isFollowing: boolean;
  isFollowedBy: boolean;
  isMutualFollow: boolean;
}

export interface BeetleCard {
  id: string;
  wallet: string;
  cardType: string;
  scopeId: string;
  scopeName?: string | null;
  score: number;
  level: number;
  patternsScored: number;
  createdAt: string;
  updatedAt: string;
}

export interface PublicRiderRideSummary {
  id: string;
  title: string;
  status?: string | null;
  startedAt?: string | null;
  createdAt?: string | null;
  distanceM?: number | null;
  elevationGainM?: number | null;
  durationSec?: number | null;
  dungMinted?: number | null;
  visibility?: RideVisibility;
  privacy?: PrivacyState | null;
}

export interface PublicRiderRecentRidesResponse {
  isPublic: boolean;
  rides: PublicRiderRideSummary[];
  count: number;
  privacy?: PrivacyState;
}

export interface PublicRiderBeetleCardsResponse {
  isPublic: boolean;
  cards: BeetleCard[];
  count: number;
  privacy?: PrivacyState;
}

export interface PublicRiderViewerCapabilities {
  contractVersion?: 'viewer_capabilities.v1';
  canView: boolean;
  canFollow: boolean;
  canKudos?: boolean;
  canComment?: boolean;
  canReport: boolean;
  canShare: boolean;
  canEdit?: boolean;
  canOpenProof?: boolean;
  canOpenScan?: boolean;
  viewerRelationship: ViewerRelationship;
}

export type ProfileModuleState = 'present' | 'empty' | 'hidden' | 'unavailable';

export interface PublicRiderProfileModule {
  contractVersion?: 'public_profile_module.v1';
  id: string;
  state: ProfileModuleState;
  title: string;
  reason?: string | null;
  count?: number | null;
}

export interface PublicRiderProfileResponse {
  contractVersion: 'public_rider_profile.v1';
  rider: PublicRiderRef | null;
  profile: UserPublic;
  privacy?: PrivacyState | null;
  viewerCapabilities: PublicRiderViewerCapabilities;
  modules?: PublicRiderProfileModule[];
  followState?: FollowState | null;
  recentRides: PublicRiderRecentRidesResponse;
  beetleCards: PublicRiderBeetleCardsResponse;
  leaderboard?: UserLeaderboardSummary | null;
}

export interface SocialReport {
  contractVersion?: 'moderation.v1';
  id: string;
  reporterId: string;
  targetType: 'ride' | 'comment' | 'user' | 'ride_media';
  targetId: string;
  target?: LinkTarget | null;
  primaryAction?: PrimaryAction;
  viewerCapabilities?: ViewerCapabilities;
  reason: string;
  details?: string | null;
  status: 'open' | 'reviewing' | 'resolved' | 'dismissed';
  createdAt: string;
  updatedAt?: string | null;
  reviewedAt?: string | null;
  reviewedBy?: string | null;
  resolutionNote?: string | null;
  resolutionAction?: 'review_started' | 'leave_visible' | 'hide' | 'remove' | 'unsupported' | null;
  reporterOutcome?: string | null;
  reporterMessage?: string | null;
  moderationMetadata?: Record<string, unknown>;
  actionHistory?: ModerationAction[];
}

export interface ModerationAction {
  id: string;
  reportId?: string | null;
  actorId?: string | null;
  actionType: 'review_started' | 'leave_visible' | 'hide' | 'remove' | 'unsupported' | string;
  actionStatus: 'applied' | 'deferred' | 'unsupported' | 'failed' | string;
  targetType: string;
  targetId: string;
  note?: string | null;
  metadata?: Record<string, unknown>;
  createdAt?: string | null;
}

export interface MyReportsResponse {
  reports: SocialReport[];
  count: number;
}

export interface RideInteractions {
  rideId: string;
  kudosCount: number;
  commentCount: number;
  viewerHasKudos: boolean;
  viewerReported?: boolean;
  reportStatus?: string | null;
  commentsEnabled: boolean;
  canComment: boolean;
}

export interface Comment {
  id: string;
  userId: string;
  author?: PublicRiderRef | null;
  targetType?: string;
  targetId?: string;
  username?: string | null;
  displayName?: string | null;
  avatarUrl?: string | null;
  content: string;
  createdAt: string;
  updatedAt?: string | null;
  parentId?: string | null;
  viewerReported?: boolean;
  reportStatus?: string | null;
}

export interface VaultPosition {
  vaultId: number;
  canonClimbId?: string | null;
  vaultName: string;
  vaultSignature: string;
  rank: number;
  bestTimeSeconds: number;
  isKom: boolean;
  totalRiders: number;
  percentile?: number | null;
  achievedAt?: string | null;
}

export interface UserLeaderboardStats {
  totalPositions: number;
  komCount: number;
  podiumCount: number;
  top10Count: number;
  totalVaultsCompleted: number;
  bestPercentile?: number | null;
}

export interface UserLeaderboardSummary {
  wallet: string;
  stats: UserLeaderboardStats;
  positions: VaultPosition[];
}

export interface PrivateRiderProfileResponse {
  contractVersion: 'private_rider_profile.v1';
  profile: User;
  beetleCards: {
    cards: BeetleCard[];
    count: number;
  };
  leaderboard: UserLeaderboardSummary;
  notifications: {
    unreadCount: number;
  };
  modules?: PublicRiderProfileModule[];
}

export interface UserProfile {
  username?: string;
  displayName?: string;
  bio?: string;
  avatarUrl?: string;
  unitPreference?: 'metric' | 'imperial';
  weight_kg?: number;
  defaultRideVisibility?: RideVisibility;
}

export interface RideSummary {
  id: string;
  activityId: string;
  startedAt: string;
  durationSec: number;
  distanceM: number;
  elevationGainM: number;
  tss: number | null;
  np: number | null;
  avgPowerW: number | null;
  source: string;
  visibility?: RideVisibility;
  privacy?: PrivacyState | null;
  commentsEnabled?: boolean;
  thresholdTrainingState?: 'pending' | null;
  thresholdEconomyState?: 'held' | 'counted' | 'lapsed' | 'review' | 'not_counted' | null;
  routePreview?: RoutePreview | null;
  media?: RideMedia[];
}

export interface RideMedia {
  id: string;
  rideId: string;
  url?: string | null;
  fileName?: string | null;
  mimeType: string;
  sizeBytes: number;
  width?: number | null;
  height?: number | null;
  sortOrder: number;
  role: 'photo' | 'cover';
  moderationState: string;
  createdAt?: string | null;
}

export interface RideMediaInitResponse {
  mediaId: string;
  signedUrl: string;
  expiresIn: number;
}

export interface AvatarUploadInitResponse {
  uploadId: string;
  signedUrl: string;
  expiresIn: number;
}

export interface RideUpdatePayload {
  title?: string;
  description?: string;
  activityType?: string;
  visibility?: RideVisibility;
  commentsEnabled?: boolean;
  hideFromLeaderboards?: boolean;
}

export type TruthSource = 'onchain' | 'attested' | 'projected' | 'compatibility';

export interface CarryBuckets {
  recordRoyalty: string;
  recordRoyaltyBaseUnits: string;
  stakers: string;
  stakersBaseUnits: string;
  localLegend: string;
  localLegendBaseUnits: string;
  pol: string;
  polBaseUnits: string;
  treasury: string;
  treasuryBaseUnits: string;
  total: string;
  totalBaseUnits: string;
}

export interface VaultEconomy {
  contractVersion: 'client.v1';
  truthSource: TruthSource;
  hasVault: boolean;
  vaultId: number | null;
  vaultSignature: string | null;
  totalStaked: string;
  totalStakedBaseUnits: string;
  totalCalStaked: string;
  totalCalStakedBaseUnits: string;
  totalCompletions: number;
  currentCarry?: CarryBuckets | null;
}

export interface RecordBoardEntry {
  position?: number | null;
  rank: number;
  competitionRank?: number | null;
  tieSize?: number | null;
  isTied?: boolean;
  wallet: string;
  userId?: string | null;
  username?: string | null;
  displayName?: string | null;
  avatarUrl?: string | null;
  bestTimeSeconds?: number | null;
  avgPowerW?: number | null;
  completionId?: string | null;
  achievedAt?: string | null;
  vaultSignature?: string | null;
}

export interface RecordBoard {
  contractVersion: 'client.v1';
  truthSource: TruthSource;
  climbId: string;
  climbName?: string | null;
  vaultId?: number | null;
  entries: RecordBoardEntry[];
  leaderboard: RecordBoardEntry[];
  komHolder?: string | null;
  komTimeS: number | null;
}

export interface LocalLegendStatus {
  contractVersion: 'client.v1';
  truthSource: TruthSource;
  climbId: string;
  vaultId?: number | null;
  wallet?: string | null;
  attemptsInWindow: number;
  electedAt?: string | null;
  founderWallet?: string | null;
  founderResidualRecipient?: string | null;
}

export interface ClimbSummary {
  contractVersion?: 'client.v1';
  truthSource?: TruthSource;
  id: string;
  name: string;
  lengthM: number;
  elevGainM: number;
  avgGradientPct: number;
  region: string | null;
  vaultId: number | null;
  vaultSignature: string | null;
  hasVault: boolean;
  totalStaked: string;
  totalStakedBaseUnits: string;
  totalCalStaked: string;
  totalCalStakedBaseUnits: string;
  totalCompletions: number;
  vaultEconomy?: VaultEconomy;
  recordBoard?: RecordBoard | null;
  localLegend?: LocalLegendStatus | null;
  routePreview?: RoutePreview | null;
}

export type VaultSummary = ClimbSummary;

interface ClimbListResponse {
  climbs: ClimbSummary[];
}

interface PopularClimbResponseItem {
  id: string | number;
  name: string;
  region?: string | null;
  length_m?: number;
  lengthM?: number;
  elev_gain_m?: number;
  elevGainM?: number;
  avg_gradient_pct?: number;
  avgGradientPct?: number;
  route_preview?: RoutePreview | null;
  routePreview?: RoutePreview | null;
  vault_id?: number | null;
  vaultId?: number | null;
  vault_signature?: string | null;
  vaultSignature?: string | null;
  has_vault?: boolean;
  hasVault?: boolean;
  completions?: number;
  total_completions?: number;
  totalCompletions?: number;
  staked?: string;
  staked_base_units?: string;
  stakedBaseUnits?: string;
  total_staked?: string;
  totalStaked?: string;
  total_staked_base_units?: string;
  totalStakedBaseUnits?: string;
}

interface PopularClimbsResponse {
  climbs: PopularClimbResponseItem[];
}

export interface RideStatus {
  contractVersion?: 'client.v1';
  truthSource?: TruthSource;
  rideId: string;
  status: string;
  errorMessage: string | null;
  processingStage?:
    | 'uploading'
    | 'queued'
    | 'processing'
    | 'metrics_ready'
    | 'enriched'
    | 'under_review'
    | 'completed'
    | 'failed'
    | 'unknown';
  canRetryProcessing?: boolean;
  failure?: {
    phase:
      | 'upload'
      | 'queue'
      | 'metrics'
      | 'enrichment'
      | 'settlement'
      | 'processing'
      | 'unknown';
    message: string;
    retryable: boolean;
    code?: string | null;
  } | null;
  inputQuality?: {
    status: 'unknown' | 'clean' | 'degraded' | 'invalid';
    sensorDataState: 'unknown' | 'absent' | 'partial' | 'present';
    integrityScore?: number | null;
    sampleCount?: number | null;
    flags: string[];
    degradationReasons: string[];
    gpsCoverage?: number | null;
    elevationCoverage?: number | null;
    samplingRegularity?: number | null;
    maxGapS?: number | null;
    powerCoverage?: number | null;
    heartRateCoverage?: number | null;
    speedCoverage?: number | null;
    importQualityTier?: string | null;
  };
  calEarned?: number | null;
  attestationStatus?: 'pending' | 'provisional' | 'attested' | 'under_review' | string;
  rideHashHex?: string | null;
  attestationCommitmentHex?: string | null;
  parserVersion?: number | null;
  preliminaryRideHashHex?: string | null;
  preliminaryParserVersion?: number | null;
  canonicalMatch?: boolean | null;
  reviewReason?: string | null;
  rideAttestationPda?: string | null;
  rideAttestationTxSignature?: string | null;
  rideAttestedAt?: string | null;
  finalizedAt?: string | null;
  phase1Error?: string | null;
  phase2Error?: string | null;
  phase3Error?: string | null;
  phase1CompletedAt?: string | null;
  phase2CompletedAt?: string | null;
  phase3CompletedAt?: string | null;
  phase1DurationMs?: number | null;
  phase2DurationMs?: number | null;
  phase3DurationMs?: number | null;
  hasGps?: boolean;
  hasPatterns?: boolean;
  hasLeaderboards?: boolean;
  hasAchievements?: boolean;
  dungMinted?: number | null;
  txSignature?: string | null;
  earnings?: {
    contractVersion: 'client.v1';
    truthSource: TruthSource;
    rideId: string;
    calEarned?: number | null;
    dungEarned?: number | null;
    finalizedAt?: string | null;
  } | null;
  effortPolicy?: {
    effortEvidenceTier?: string | null;
    rewardPolicy?: string | null;
    estimatedCal?: number | null;
    rewardableCal?: number | null;
    tributableCal?: number | null;
    thresholdEconomyState?: 'held' | 'counted' | 'lapsed' | 'review' | 'not_counted' | null;
  } | null;
  climbEarnings?: RideClimbEarning[];
  progression?: RideProgression | null;
  metrics?: {
    tss?: number | null;
    thresholdTrainingState?: 'pending' | null;
    kcals?: number | null;
    distanceM?: number | null;
    elevationGainM?: number | null;
    durationSec?: number | null;
    avgPowerW: number | null;
    normalizedPowerW: number | null;
  } | null;
}

export interface RideDetailResponse {
  contractVersion: 'ride_detail.v1';
  ride: RideSummary;
  status: RideStatus;
  interactions: RideInteractions;
  comments: {
    comments: Comment[];
    count: number;
    hasMore: boolean;
  };
  link: ResolvedLink;
  freshness?: {
    source: string;
    loadedAt: string;
    status?: string;
  };
}

export interface RideClimbEarning {
  contractVersion: 'client.v1';
  truthSource: TruthSource;
  rideId: string;
  climbId: string;
  climbName?: string | null;
  vaultId?: number | null;
  vaultSignature?: string | null;
  calTribute?: number | null;
  tributeTruthSource?: TruthSource;
  completionEvidenceVersion?: number | null;
  tributeBound?: boolean;
  completionTimeS?: number | null;
  recordBoardRank?: number | null;
  recordBoardBestTimeS?: number | null;
  isNewPersonalBest?: boolean | null;
  isNewKom?: boolean | null;
  txSignature?: string | null;
  completedAt?: string | null;
}

export interface RideProgression {
  contractVersion: 'client.v1';
  truthSource: TruthSource;
  rideId: string;
  tssDelta?: number | null;
}

export interface AuthTokens {
  accessToken: string;
  refreshToken: string;
  expiresIn: number;
  wallet: string;
}

export interface RefreshResponse {
  accessToken: string;
  refreshToken: string;
  wallet: string;
  accessExpiresAt: string;
  refreshExpiresAt: string;
}

// ---------------------------------------------------------------------------
// Case conversion (matches portal)
// ---------------------------------------------------------------------------

const toSnakeCase = (obj: unknown): unknown => {
  if (Array.isArray(obj)) return obj.map(toSnakeCase);
  if (obj instanceof Date) return obj.toISOString();
  if (obj && typeof obj === 'object') {
    return Object.entries(obj).reduce<Record<string, unknown>>((acc, [key, val]) => {
      const snakeKey = key.replace(/([A-Z])/g, '_$1').toLowerCase();
      acc[snakeKey] = toSnakeCase(val);
      return acc;
    }, {});
  }
  return obj;
};

const toCamelCase = (obj: unknown): unknown => {
  if (Array.isArray(obj)) return obj.map(toCamelCase);
  if (obj && typeof obj === 'object') {
    return Object.entries(obj).reduce<Record<string, unknown>>((acc, [key, val]) => {
      const camelKey = key.replace(/_([a-z])/g, (_, c: string) => c.toUpperCase());
      acc[camelKey] = toCamelCase(val);
      return acc;
    }, {});
  }
  return obj;
};

// ---------------------------------------------------------------------------
// API Error
// ---------------------------------------------------------------------------

export type ApiErrorType = 'session_expired' | 'auth_rejected' | 'network_error' | 'server_error' | 'unknown';

export class ApiError extends Error {
  type: ApiErrorType;
  statusCode?: number;
  retryable: boolean;

  constructor(message: string, type: ApiErrorType, statusCode?: number) {
    super(message);
    this.name = 'ApiError';
    this.type = type;
    this.statusCode = statusCode;
    this.retryable = type === 'network_error' || (statusCode !== undefined && statusCode >= 500);
  }
}

// ---------------------------------------------------------------------------
// API Client
// ---------------------------------------------------------------------------

// Forward declaration for tokenRefreshManager.refresh()
// Set via setRefreshHandler() to avoid circular imports
let _refreshFn: (() => Promise<boolean>) | null = null;

export function setApiRefreshHandler(fn: () => Promise<boolean>): void {
  _refreshFn = fn;
}

class APIClient {
  // -------------------------------------------------------------------------
  // Core fetch wrapper
  // -------------------------------------------------------------------------

  private async request<T>(
    method: string,
    path: string,
    body?: unknown,
    skipAuth?: boolean,
  ): Promise<T> {
    const url = `${API_URL}${path}`;
    const headers: Record<string, string> = {
      'Content-Type': 'application/json',
      'Accept': 'application/json',
    };

    // Read access token from Zustand store (synchronous)
    if (!skipAuth) {
      const accessToken = useAuthStore.getState().accessToken;
      if (accessToken) {
        headers['Authorization'] = `Bearer ${accessToken}`;
      }
    }

    let response: Response;
    try {
      response = await fetch(url, {
        method,
        headers,
        body: body ? JSON.stringify(toSnakeCase(body)) : undefined,
      });
    } catch (err) {
      throw new ApiError(
        `Network error: ${err instanceof Error ? err.message : 'unknown'}`,
        'network_error',
      );
    }

    // On 401: attempt one refresh before failing
    if (response.status === 401 && !skipAuth && _refreshFn) {
      const refreshed = await _refreshFn();
      if (refreshed) {
        // Retry the original request with new token
        const newToken = useAuthStore.getState().accessToken;
        if (newToken) {
          headers['Authorization'] = `Bearer ${newToken}`;
        }
        try {
          const retryResponse = await fetch(url, {
            method,
            headers,
            body: body ? JSON.stringify(toSnakeCase(body)) : undefined,
          });
          if (retryResponse.ok) {
            if (retryResponse.status === 204) return undefined as T;
            const json = await retryResponse.json();
            return toCamelCase(json) as T;
          }
          // Retry also failed
          if (retryResponse.status === 401) {
            useAuthStore.getState().setUnauthenticated();
            await clearTokens();
            throw new ApiError('Session expired', 'session_expired', 401);
          }
          const text = await retryResponse.text().catch(() => '');
          throw new ApiError(
            `API error ${retryResponse.status}: ${text}`,
            retryResponse.status >= 500 ? 'server_error' : 'unknown',
            retryResponse.status,
          );
        } catch (retryErr) {
          if (retryErr instanceof ApiError) throw retryErr;
          throw new ApiError(
            `Network error on retry: ${retryErr instanceof Error ? retryErr.message : 'unknown'}`,
            'network_error',
          );
        }
      }
      // Refresh failed — clear auth
      useAuthStore.getState().setUnauthenticated();
      await clearTokens();
      throw new ApiError('Session expired', 'session_expired', 401);
    }

    if (response.status === 401) {
      // Preserve the backend's real error body — callers of login endpoints
      // (/auth/privy/verify, /auth/verify) need to see *why* their credentials
      // were rejected, not a generic "session expired" that also clobbers state.
      const body = await response.text().catch(() => '');
      if (skipAuth) {
        throw new ApiError(
          `Auth rejected (401): ${body || 'no body'}`,
          'auth_rejected',
          401,
        );
      }
      useAuthStore.getState().setUnauthenticated();
      await clearTokens();
      throw new ApiError(`Session expired: ${body}`, 'session_expired', 401);
    }

    if (!response.ok) {
      const text = await response.text().catch(() => '');
      throw new ApiError(
        `API error ${response.status}: ${text}`,
        response.status >= 500 ? 'server_error' : 'unknown',
        response.status,
      );
    }

    // Handle 204 No Content
    if (response.status === 204) {
      return undefined as T;
    }

    const json = await response.json();
    return toCamelCase(json) as T;
  }

  // -------------------------------------------------------------------------
  // Auth endpoints
  // -------------------------------------------------------------------------

  /** Verify a Privy token with the backend and receive our JWT */
  async verifyPrivyToken(
    wallet: string,
    privyToken: string,
    deviceId: string,
    inviteCode?: string,
  ): Promise<AuthTokens> {
    return this.request<AuthTokens>('POST', '/auth/privy/verify', {
      wallet,
      privyToken,
      deviceId,
      ...(inviteCode && { inviteCode }),
    }, true);
  }

  /** Verify a wallet signature (SIWS) */
  async verifySignature(
    wallet: string,
    signature: string,
    nonce: string,
    deviceId: string,
    inviteCode?: string,
  ): Promise<AuthTokens> {
    return this.request<AuthTokens>('POST', '/auth/verify', {
      wallet,
      signature,
      nonce,
      deviceId,
      ...(inviteCode && { inviteCode }),
    }, true);
  }

  /** Request a wallet-ownership nonce. */
  async getNonce(wallet: string, deviceId: string): Promise<{ nonce: string; message: string; expiresAt: string }> {
    return this.request('POST', '/auth/nonce', { wallet, deviceId }, true);
  }

  /**
   * Refresh tokens — sends refresh token in body (not cookie).
   * This is the mobile-specific refresh flow.
   */
  async refreshTokens(refreshToken: string, deviceId: string): Promise<RefreshResponse> {
    const response = await fetch(`${API_URL}/auth/refresh`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        refresh_token: refreshToken,
        device_id: deviceId,
      }),
    });
    if (!response.ok) {
      throw new ApiError('Refresh failed', 'session_expired', response.status);
    }
    const json = await response.json();
    return toCamelCase(json) as RefreshResponse;
  }

  /** Validate an invite code (pre-login) */
  async validateInviteCode(code: string): Promise<{ valid: boolean }> {
    return this.request('POST', '/auth/invite/validate', { code }, true);
  }

  /** Logout — sends refresh token in body for mobile clients */
  async logout(refreshToken: string | null, deviceId: string): Promise<void> {
    try {
      await this.request('POST', '/auth/logout', {
        ...(refreshToken && { refreshToken }),
        deviceId,
      });
    } catch {
      // Swallow logout errors — we always clear local state
    }
  }

  // -------------------------------------------------------------------------
  // User endpoints
  // -------------------------------------------------------------------------

  async getMe(): Promise<User> {
    return this.request('GET', '/users/me');
  }

  async getMyProfileBootstrap(): Promise<PrivateRiderProfileResponse> {
    return this.request('GET', '/users/me/profile');
  }

  async getUser(identifier: string): Promise<UserPublic> {
    return this.request('GET', `/users/${encodeURIComponent(identifier)}`);
  }

  async getPublicRiderProfile(identifier: string, limit = 5): Promise<PublicRiderProfileResponse> {
    return this.request(
      'GET',
      `/users/${encodeURIComponent(identifier)}/profile?limit=${limit}`,
    );
  }

  async getPublicRiderRecentRides(identifier: string, limit = 10): Promise<PublicRiderRecentRidesResponse> {
    return this.request(
      'GET',
      `/users/${encodeURIComponent(identifier)}/recent-rides?limit=${limit}`,
    );
  }

  async getPublicRiderBeetleCards(identifier: string): Promise<PublicRiderBeetleCardsResponse> {
    return this.request('GET', `/users/${encodeURIComponent(identifier)}/beetle-cards`);
  }

  async getFeed(limit = 20, before?: string): Promise<FeedResponse> {
    const query = `limit=${encodeURIComponent(String(limit))}${
      before ? `&before=${encodeURIComponent(before)}` : ''
    }`;
    return this.request('GET', `/feed?${query}`);
  }

  async getGlobalFeed(limit = 20, before?: string): Promise<FeedResponse> {
    const query = `limit=${encodeURIComponent(String(limit))}${
      before ? `&before=${encodeURIComponent(before)}` : ''
    }`;
    return this.request('GET', `/feed/global?${query}`);
  }

  async getHomeFeed(
    scope: 'following' | 'global' = 'following',
    limit = 20,
  ): Promise<HomeFeedResponse> {
    const params = new URLSearchParams({
      scope,
      limit: String(limit),
    });
    return this.request('GET', `/feed/home?${params.toString()}`);
  }

  async getLinkSchema(): Promise<LinkSchemaResponse> {
    return this.request('GET', '/links/schema');
  }

  async resolveLink(targetType: LinkTargetType, targetId: string): Promise<ResolvedLink> {
    const params = new URLSearchParams({
      target_type: targetType,
      target_id: targetId,
    });
    return this.request('GET', `/links/resolve?${params.toString()}`);
  }

  async resolveLinkUrl(url: string): Promise<ResolvedLink> {
    const params = new URLSearchParams({ url });
    return this.request('GET', `/links/resolve?${params.toString()}`);
  }

  async search(options: { q: string; type?: SearchType; limit?: number }): Promise<SearchResponse> {
    const params = new URLSearchParams();
    params.set('q', options.q);
    if (options.type) params.set('type', options.type);
    if (options.limit) params.set('limit', String(options.limit));
    return this.request('GET', `/search?${params.toString()}`);
  }

  async getSearchSuggestions(options?: { limit?: number }): Promise<SearchSuggestionsResponse> {
    const params = new URLSearchParams();
    if (options?.limit) params.set('limit', String(options.limit));
    const query = params.toString();
    return this.request('GET', `/search/suggestions${query ? `?${query}` : ''}`);
  }

  async getSearchSchema(): Promise<SearchSchemaResponse> {
    return this.request('GET', '/search/schema');
  }

  async getNotifications(options?: {
    limit?: number;
    unreadOnly?: boolean;
  }): Promise<NotificationsResponse> {
    const params = new URLSearchParams();
    if (options?.limit) params.set('limit', String(options.limit));
    if (options?.unreadOnly) params.set('unread_only', 'true');
    const query = params.toString();
    return this.request('GET', `/notifications${query ? `?${query}` : ''}`);
  }

  async markNotificationRead(notificationId: string): Promise<{ status: string }> {
    return this.request('POST', `/notifications/${encodeURIComponent(notificationId)}/read`);
  }

  async markAllNotificationsRead(): Promise<{ status: string; count: number }> {
    return this.request('POST', '/notifications/read-all');
  }

  async getNotificationPreferences(): Promise<NotificationPreferences> {
    return this.request('GET', '/notifications/preferences');
  }

  async updateNotificationPreferences(
    preferences: NotificationPreferences,
  ): Promise<NotificationPreferences> {
    return this.request('PUT', '/notifications/preferences', preferences);
  }

  async updateProfile(updates: Partial<UserProfile>): Promise<User> {
    const {
      username,
      displayName,
      bio,
      avatarUrl,
      unitPreference,
      weight_kg,
      defaultRideVisibility,
    } = updates;

    return this.request('PUT', '/users/me', {
      username,
      displayName,
      bio,
      avatarUrl,
      units: unitPreference,
      weight_kg,
      defaultRideVisibility,
    });
  }

  async initAvatarUpload(file: PreparedNativeImageUpload): Promise<AvatarUploadInitResponse> {
    return this.request('POST', '/users/me/avatar/init', {
      fileName: file.name,
      mimeType: file.mimeType,
      fileSize: file.size,
    });
  }

  async completeAvatarUpload(uploadId: string): Promise<User> {
    return this.request('POST', '/users/me/avatar/complete', { uploadId });
  }

  async uploadAvatar(file: PreparedNativeImageUpload): Promise<User> {
    const initResult = await this.initAvatarUpload(file);
    const formData = new FormData();
    formData.append('file', {
      uri: file.uri,
      name: file.name,
      type: file.mimeType,
    } as unknown as Blob);

    const response = await fetch(initResult.signedUrl, {
      method: 'PUT',
      body: formData,
      headers: { 'x-upsert': 'false' },
    });
    if (!response.ok) {
      throw new ApiError(
        `Avatar upload failed: ${response.status}`,
        response.status >= 500 ? 'server_error' : 'unknown',
        response.status,
      );
    }
    return this.completeAvatarUpload(initResult.uploadId);
  }

  async deleteAvatar(): Promise<User> {
    return this.request('DELETE', '/users/me/avatar');
  }

  async getPrivacySettings(): Promise<PrivacySettings> {
    return this.request('GET', '/privacy/settings');
  }

  async updatePrivacySettings(updates: {
    isPublic?: boolean;
    defaultRideVisibility?: RideVisibility;
  }): Promise<PrivacySettings> {
    return this.request('PUT', '/privacy/settings', updates);
  }

  async getFollowState(userId: string): Promise<FollowState> {
    return this.request('GET', `/social/is-following/${encodeURIComponent(userId)}`);
  }

  async followUser(userId: string): Promise<{ status: string; followingId: string }> {
    return this.request('POST', `/social/follow/${encodeURIComponent(userId)}`);
  }

  async unfollowUser(userId: string): Promise<{ status: string; unfollowedId: string }> {
    return this.request('DELETE', `/social/follow/${encodeURIComponent(userId)}`);
  }

  async reportSocialContent(
    targetType: 'ride' | 'comment' | 'user' | 'ride_media',
    targetId: string,
    reason: string,
    details?: string,
  ): Promise<SocialReport> {
    return this.request('POST', '/social/reports', { targetType, targetId, reason, details });
  }

  async getMySocialReports(limit = 50, offset = 0): Promise<MyReportsResponse> {
    return this.request('GET', `/social/reports/me?limit=${limit}&offset=${offset}`);
  }

  async getMySocialReport(reportId: string): Promise<SocialReport> {
    return this.request('GET', `/social/reports/${encodeURIComponent(reportId)}`);
  }

  async getMyBeetleCards(): Promise<BeetleCard[]> {
    return this.request('GET', '/beetles/my-cards');
  }

  async getMyLeaderboardPositions(): Promise<UserLeaderboardSummary> {
    return this.request('GET', '/users/me/leaderboard-positions');
  }

  async getUserLeaderboardPositions(wallet: string): Promise<UserLeaderboardSummary> {
    return this.request('GET', `/users/${encodeURIComponent(wallet)}/leaderboard-positions`);
  }

  // -------------------------------------------------------------------------
  // Rides
  // -------------------------------------------------------------------------

  async getRides(limit = 20, offset = 0): Promise<RideSummary[]> {
    return this.request('GET', `/rides?limit=${limit}&offset=${offset}`);
  }

  async getRide(id: string): Promise<RideSummary> {
    return this.request('GET', `/rides/${id}`);
  }

  async getRideDetail(id: string, commentsLimit = 20): Promise<RideDetailResponse> {
    return this.request('GET', `/rides/${id}/detail?comments_limit=${commentsLimit}`);
  }

  async updateRide(id: string, updates: RideUpdatePayload): Promise<{ status: string; rideId: string }> {
    return this.request('PATCH', `/rides/${id}`, updates);
  }

  async initRideMediaUpload(
    rideId: string,
    file: PreparedNativeImageUpload,
    sortOrder: number,
  ): Promise<RideMediaInitResponse> {
    return this.request('POST', `/rides/${rideId}/media/init`, {
      fileName: file.name,
      mimeType: file.mimeType,
      fileSize: file.size,
      sortOrder,
      role: sortOrder === 0 ? 'cover' : 'photo',
    });
  }

  async completeRideMediaUpload(rideId: string, mediaId: string): Promise<RideMedia> {
    return this.request('POST', `/rides/${rideId}/media/complete`, { mediaId });
  }

  async uploadRideMedia(
    rideId: string,
    file: PreparedNativeImageUpload,
    sortOrder = 0,
  ): Promise<RideMedia> {
    const initResult = await this.initRideMediaUpload(rideId, file, sortOrder);
    const formData = new FormData();
    formData.append('file', {
      uri: file.uri,
      name: file.name,
      type: file.mimeType,
    } as unknown as Blob);

    const response = await fetch(initResult.signedUrl, {
      method: 'PUT',
      body: formData,
      headers: { 'x-upsert': 'false' },
    });
    if (!response.ok) {
      throw new ApiError(
        `Photo upload failed: ${response.status}`,
        response.status >= 500 ? 'server_error' : 'unknown',
        response.status,
      );
    }
    return this.completeRideMediaUpload(rideId, initResult.mediaId);
  }

  async updateRideMedia(
    rideId: string,
    mediaId: string,
    updates: { role?: 'photo' | 'cover'; sortOrder?: number },
  ): Promise<RideMedia> {
    return this.request('PATCH', `/rides/${rideId}/media/${mediaId}`, updates);
  }

  async reorderRideMedia(
    rideId: string,
    items: Array<{ mediaId: string; sortOrder: number }>,
  ): Promise<RideMedia[]> {
    return this.request('PATCH', `/rides/${rideId}/media/reorder`, { items });
  }

  async deleteRideMedia(rideId: string, mediaId: string): Promise<{ status: string; mediaId: string }> {
    return this.request('DELETE', `/rides/${rideId}/media/${mediaId}`);
  }

  async getRideStatus(rideId: string): Promise<RideStatus> {
    return this.request('GET', `/rides/${rideId}/status`);
  }

  async reprocessRide(rideId: string): Promise<{ status: string; rideId: string; message?: string }> {
    return this.request('POST', `/rides/${rideId}/reprocess`);
  }

  async getRideInteractions(rideId: string): Promise<RideInteractions> {
    return this.request('GET', `/rides/${rideId}/interactions`);
  }

  async getRideComments(rideId: string): Promise<{ comments: Comment[] }> {
    return this.request('GET', `/rides/${rideId}/comments`);
  }

  async addRideComment(rideId: string, content: string, parentId?: string): Promise<Comment> {
    return this.request('POST', `/rides/${rideId}/comments`, { content, parentId });
  }

  async updateRideComment(rideId: string, commentId: string, content: string): Promise<Comment> {
    return this.request('PATCH', `/rides/${rideId}/comments/${commentId}`, { content });
  }

  async deleteRideComment(rideId: string, commentId: string): Promise<{ status: string; commentId: string }> {
    return this.request('DELETE', `/rides/${rideId}/comments/${commentId}`);
  }

  async giveRideKudos(rideId: string): Promise<{ status: string }> {
    return this.request('POST', `/rides/${rideId}/kudos`);
  }

  async removeRideKudos(rideId: string): Promise<{ status: string }> {
    return this.request('DELETE', `/rides/${rideId}/kudos`);
  }

  // -------------------------------------------------------------------------
  // Climbs
  // -------------------------------------------------------------------------

  async getClimbs(limit = 20, _offset = 0): Promise<ClimbSummary[]> {
    const response = await this.request<ClimbListResponse>('GET', `/climbs/list?limit=${limit}`);
    return response.climbs;
  }

  async getPopularClimbs(limit = 20): Promise<ClimbSummary[]> {
    const response = await this.request<PopularClimbsResponse>('GET', `/climbs/popular?limit=${limit}`);
    return response.climbs.map((climb) => {
      const id = String(climb.id);
      const totalCompletions = climb.totalCompletions ?? climb.total_completions ?? climb.completions ?? 0;
      const totalStaked = climb.totalStaked ?? climb.total_staked ?? climb.staked ?? '0';
      const totalStakedBaseUnits = climb.totalStakedBaseUnits
        ?? climb.total_staked_base_units
        ?? climb.stakedBaseUnits
        ?? climb.staked_base_units
        ?? '0';
      const vaultId = climb.vaultId ?? climb.vault_id ?? (/^\d+$/.test(id) ? Number(id) : null);
      return {
        id,
        name: climb.name,
        lengthM: climb.lengthM ?? climb.length_m ?? 0,
        elevGainM: climb.elevGainM ?? climb.elev_gain_m ?? 0,
        avgGradientPct: climb.avgGradientPct ?? climb.avg_gradient_pct ?? 0,
        region: climb.region ?? null,
        vaultId,
        vaultSignature: climb.vaultSignature ?? climb.vault_signature ?? null,
        hasVault: climb.hasVault
          ?? climb.has_vault
          ?? (vaultId !== null || BigInt(totalStakedBaseUnits) > 0n || totalCompletions > 0),
        totalStaked,
        totalStakedBaseUnits,
        totalCalStaked: totalStaked,
        totalCalStakedBaseUnits: totalStakedBaseUnits,
        totalCompletions,
        routePreview: climb.routePreview ?? climb.route_preview ?? null,
      };
    });
  }

  async getClimb(id: string): Promise<ClimbSummary> {
    return this.request('GET', `/climbs/${id}`);
  }

  async getClimbLeaderboard(id: string): Promise<RecordBoard> {
    return this.request('GET', `/climbs/${id}/leaderboard`);
  }

  // Compatibility aliases for callers not yet renamed. These intentionally
  // route through the canonical Climb API surface.
  async getVaults(limit = 20, offset = 0): Promise<ClimbSummary[]> {
    return this.getClimbs(limit, offset);
  }

  async getVault(id: string): Promise<ClimbSummary> {
    return this.getClimb(id);
  }

  // -------------------------------------------------------------------------
  // Health
  // -------------------------------------------------------------------------

  async healthCheck(): Promise<{ status: string }> {
    return this.request('GET', '/health', undefined, true);
  }
}

/** Singleton API client instance */
export const api = new APIClient();
