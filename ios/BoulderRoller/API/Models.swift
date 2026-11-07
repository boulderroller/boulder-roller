import Foundation

// Codable mirrors of the production API contracts used by slice one.
// Shapes follow web/portal/src/lib/api.ts (the portal client is the reference
// consumer). Decoding uses .convertFromSnakeCase; dates stay ISO-8601 strings
// and are parsed at display time.

/// Rider display-name fallback chain. Empty strings are absence: the
/// backend's identity clear persists "" (nulls are dropped server-side for
/// these fields), so rendering must never show an empty name.
func riderShownName(displayName: String?, username: String?, wallet: String) -> String {
    if let displayName, !displayName.trimmingCharacters(in: .whitespaces).isEmpty {
        return displayName
    }
    if let username, !username.trimmingCharacters(in: .whitespaces).isEmpty {
        return username
    }
    return "Rider \(wallet.prefix(4))"
}

// MARK: - Auth

struct AuthTokenResponse: Codable {
    let userId: String
    let wallet: String
    let accessToken: String
    let accessExpiresAt: String?
    let refreshToken: String
    let refreshExpiresAt: String?
}

/// `/auth/refresh` speaks tokens only — the server's RefreshResponse carries
/// wallet but no user id (identity was pinned at sign-in). A distinct type
/// so a successful rotation can never again be mistaken for weather by a
/// decoder expecting identity fields (the Aug 17 sign-out-on-every-refresh
/// defect).
struct RefreshTokenResponse: Codable {
    let wallet: String?
    let accessToken: String
    let accessExpiresAt: String?
    let refreshToken: String
    let refreshExpiresAt: String?
}

struct NonceResponse: Codable {
    let nonce: String
    let message: String
}

struct AuthBootstrapState: Codable {
    let authenticated: Bool
    let inviteRequired: Bool?
    let inviteValidated: Bool?
    let needsProfileSetup: Bool?
    let user: User?
}

struct InviteValidationResult: Codable {
    let valid: Bool
    let message: String?
}

// MARK: - Rider

/// Rider weight is honest-nullable. Threshold is a separate derived authority
/// read and is never accepted through the profile contract.
struct User: Codable, Identifiable, Sendable {
    let id: String
    let wallet: String
    var username: String?
    var displayName: String?
    var bio: String?
    var avatarUrl: String?
    var email: String?
    var location: String?
    var preferredUnits: String?
    var totalRides: Int?
    var totalDistanceKm: Double?
    var totalElevationM: Double?
    var weightKg: Double?
    var weightKgSource: String?

    var shownName: String {
        riderShownName(displayName: displayName, username: username, wallet: wallet)
    }
}

struct ThresholdPendingMondayResponse: Codable, Equatable, Sendable {
    let watts: Int
    let effectiveAt: String
}

struct ThresholdResponse: Codable, Equatable, Sendable {
    let contractVersion: String
    let state: String
    let currentW: Int?
    let establishedAt: String?
    let lastRaisedAt: String?
    let pendingMonday: ThresholdPendingMondayResponse?
    let sealingInProgress: Bool
}

struct PublicProfile: Codable {
    let id: String
    let wallet: String
    let username: String?
    let displayName: String?
    let bio: String?
    let avatarUrl: String?
    let totalRides: Int?
    let totalDistanceKm: Double?
    let totalElevationM: Double?

    var shownName: String {
        riderShownName(displayName: displayName, username: username, wallet: wallet)
    }
}

struct PublicRiderRideSummary: Codable, Identifiable {
    let id: String
    let title: String?
    let startedAt: String?
    let distanceM: Double?
    let elevationM: Double?
    let durationS: Double?
}

struct PublicRiderRecentRidesResponse: Codable {
    let isPublic: Bool?
    let rides: [PublicRiderRideSummary]?
}

struct PublicRiderProfileResponse: Codable {
    let profile: PublicProfile
    let recentRides: PublicRiderRecentRidesResponse?
}

struct UserLeaderboardStats: Codable {
    let totalPositions: Int?
    let komCount: Int?
    let top10Count: Int?
}

struct VaultPositionSummary: Codable, Identifiable {
    let vaultId: Int
    let canonClimbId: String?
    let vaultName: String?
    let rank: Int?
    let bestTimeSeconds: Double?
    let isKom: Bool?
    var id: Int { vaultId }
}

/// One canon climb the rider has confirmed completions on (Your Climbs).
struct RiddenClimb: Codable, Identifiable {
    let canonClimbId: String?
    let vaultId: Int?
    let name: String?
    let attempts: Int?
    let bestTimeSeconds: Double?
    let lastRiddenAt: String?
    let lengthM: Double?
    let avgGradientPct: Double?
    var id: String { canonClimbId ?? String(vaultId ?? 0) }
}

struct RiddenClimbsResponse: Codable {
    let climbs: [RiddenClimb]?
}

struct UserLeaderboardSummaryResponse: Codable {
    let wallet: String?
    let stats: UserLeaderboardStats?
    let positions: [VaultPositionSummary]?
}

// MARK: - Rides

struct RoutePreviewPoint: Codable, Sendable {
    let x: Double
    let y: Double
}

struct RoutePreviewBounds: Codable, Sendable {
    let minLat: Double
    let minLon: Double
    let maxLat: Double
    let maxLon: Double
}

struct RoutePreview: Codable, Sendable {
    let source: String?
    let points: [RoutePreviewPoint]?
    let segments: [[RoutePreviewPoint]]?
    let bounds: RoutePreviewBounds?
    let placeLabel: String?
    let fallbackReason: String?
}

struct RideEarnings: Codable {
    let calEarned: Double?
    let dungEarned: Double?
}

struct RideMedia: Codable, Identifiable, Equatable, Sendable {
    let id: String
    let rideId: String
    let url: String?
    let fileName: String?
    let mimeType: String
    let sizeBytes: Int
    let width: Int?
    let height: Int?
    let sortOrder: Int
    let role: String
    let moderationState: String
    let createdAt: String?
}

struct RideMediaUploadInit: Codable, Equatable, Sendable {
    let mediaId: String
    let signedUrl: String
    let expiresIn: Int?
}

/// DEM elevation-correction provenance (bead `boulderroller-v2-odmi6.2.1`,
/// live in production 2026-08-11). `status` is `corrected` or `unavailable`;
/// the object is absent entirely on rides where correction was never
/// attempted. The ride's `elevationCorrectedM` carries the DEM climbing
/// total; display falls back to the device total through
/// `shownElevationM` when it is null (ratified 2026-08-18). The raw
/// `elevationM` and the frozen economic gain are never overwritten.
struct ElevationCorrection: Codable {
    let status: String
    let sourceVersion: String?
    let correctionVersion: String?
    let coverageBps: Int?
    let reason: String?
}

struct Ride: Codable, Identifiable {
    var trainingMetrics: RideTrainingMetrics? = nil
    var movingTimeS: Double? = nil
    var recordingTimeS: Double? = nil
    let id: String
    let title: String?
    var elevationProfile: [RideSpineData.Point]? = nil
    var countedSpans: [RideSpineData.Span]? = nil
    var rideHashHex: String? = nil
    var rideAttestationTxSignature: String? = nil
    var attestationStatus: String? = nil
    var finalizedAt: String? = nil
    var description: String? = nil
    let status: String?
    let startedAt: String
    let distanceM: Double?
    let elevationM: Double?
    /// Climbing total (meters) from the DEM correction; null where the
    /// grid abstains. Stats read `shownElevationM`, never this directly.
    let elevationCorrectedM: Double?
    let elevationCorrection: ElevationCorrection?
    let durationS: Double?
    let avgPowerW: Double?
    let normalizedPowerW: Double?
    let avgHrBpm: Double?
    let tss: Double?
    var thresholdTrainingState: String? = nil
    let calEarned: Double?
    let tributableCal: Double?
    let rewardableCal: Double?
    let routePreview: RoutePreview?
    let earnings: RideEarnings?
    let calItemization: CalItemization?
    let isOwner: Bool?
    /// Server-resolved state for provisional Threshold economics. This is
    /// separate from the immutable reward policy so a released ride no
    /// longer renders as held.
    var thresholdEconomyState: String? = nil
    /// Server-resolved visibility decision for this ride and viewer
    /// (`PrivacyState` on the wire). Clients render it; policy stays
    /// server-side.
    var privacy: RidePrivacyState? = nil
    var media: [RideMedia]? = nil
    /// Rider-entered effort, 1–10; absence is absence.
    var perceivedExertion: Int? = nil
    /// Device laps (the rider's own segmentation); nil or absent when the
    /// file carried no real segmentation.
    var laps: [RideLap]? = nil
    /// Power balance summary from per-sample L/R evidence.
    var powerBalance: RidePowerBalance? = nil
    /// Display-only weather captured at processing — never a CAL input.
    var weatherTempC: Double? = nil
    var weatherWindMps: Double? = nil
    var weatherWindDeg: Int? = nil

    /// The diary's one climbing number: DEM-corrected when correction
    /// produced one, the device total otherwise (ratified 2026-08-18).
    /// Provenance stays in `elevationCorrection`; economics never read this.
    var shownElevationM: Double? { elevationCorrectedM ?? elevationM }
}

// MARK: - Home feed

enum FeedScope: String, Codable, CaseIterable, Hashable, Identifiable, Sendable {
    case following
    case global

    var id: String { rawValue }
    var title: String { self == .following ? "Following" : "Global" }
}

struct FeedActor: Codable, Sendable {
    let id: String?
    let username: String?
    let displayName: String?
    let avatarUrl: String?

    var shownName: String {
        if let displayName, !displayName.isEmpty { return displayName }
        if let username, !username.isEmpty { return username }
        return "Rider"
    }

    var avatarURL: URL? {
        guard let avatarUrl else { return nil }
        return URL(string: avatarUrl)
    }
}

struct FeedTarget: Codable, Sendable {
    let type: String
    let id: String?
}

struct FeedActivityMetadata: Codable, Sendable {
    let distanceM: Double?
    let elevationM: Double?
    let elevationCorrectedM: Double?

    /// Same one-number rule as `Ride.shownElevationM`.
    var shownElevationM: Double? { elevationCorrectedM ?? elevationM }
    let durationS: Double?
    let dungEarned: Double?
    let calEarned: Double?
    let status: String?
    let kudosCount: Int?
    let commentCount: Int?
    let viewerHasKudos: Bool?
    let media: [RideMedia]?
    let primaryMedia: RideMedia?
    let routePreview: RoutePreview?
}

struct FeedActivity: Codable, Identifiable, Sendable {
    let id: String
    let type: String
    let eventType: String?
    let title: String
    let createdAt: String
    let occurredAt: String?
    let status: String?
    let actor: FeedActor?
    let user: FeedActor?
    let target: FeedTarget?
    let metadata: FeedActivityMetadata?
    let privacy: RidePrivacyState?

    var rider: FeedActor? { actor ?? user }

    var rideID: String? {
        if target?.type == "ride" { return target?.id ?? id }
        return type == "ride" ? id : nil
    }

    var occurredDate: Date {
        Format.date(from: occurredAt ?? createdAt) ?? .distantPast
    }

    var deduplicationKey: String {
        rideID.map { "ride:\($0)" } ?? "\(type):\(id)"
    }
}

struct FeedPage: Codable, Sendable {
    let activities: [FeedActivity]
    let hasMore: Bool
    let nextCursor: String?

    init(activities: [FeedActivity], hasMore: Bool, nextCursor: String?) {
        self.activities = activities
        self.hasMore = hasMore
        self.nextCursor = nextCursor
    }
}

struct HomeFeedResponse: Codable, Sendable {
    let scope: FeedScope
    let feed: FeedPage
}

/// Ride-contract v1 (bead 71o2v): the ride's vault-tribute flow decomposition.
/// Present only when the ride's frozen economic plan is complete; base units
/// are exact u64 strings (invariant: climbs + everythingBetween == rideCal).
struct CalItemization: Codable {
    struct ClimbShare: Codable {
        let patternId: String?
        let vaultId: Int?
        let vaultSignature: String?
        let climbName: String?
        let calTributeBaseUnits: String?
        let completionTimeS: Double?
        let intensityBps: Int?
    }

    let contractVersion: String?
    let calDecimals: Int?
    let rideCalBaseUnits: String?
    let tributeBudgetBaseUnits: String?
    let climbs: [ClimbShare]?
    let everythingBetweenBaseUnits: String?
}

struct RideStatusMetrics: Codable {
    let tss: Double?
    var thresholdTrainingState: String? = nil
    let distanceM: Double?
    let elevationGainM: Double?
    let durationSec: Double?
    let avgPowerW: Double?
    let normalizedPowerW: Double?
}

struct RideEffortPolicy: Codable {
    let effortEvidenceTier: String?
    let rewardPolicy: String?
    var thresholdEconomyState: String? = nil
    let estimatedCal: Double?
    let rewardableCal: Double?
    let tributableCal: Double?
}

struct RideProcessingFailure: Codable {
    let phase: String?
    let message: String?
    let retryable: Bool?
    let code: String?
}

struct RideStatus: Codable {
    let rideId: String
    let status: String
    var attestationStatus: String? = nil
    var canonicalMatch: Bool? = nil
    var processingStage: String? = nil
    var canRetryProcessing: Bool? = nil
    var failure: RideProcessingFailure? = nil
    let calEarned: Double?
    let metrics: RideStatusMetrics?
    let effortPolicy: RideEffortPolicy?
    let hasPatterns: Bool?
    let errorMessage: String?
    let phase1Error: String?
    let phase2Error: String?
    let phase3Error: String?
}

struct RideDetailResponse: Codable {
    let ride: Ride
    let status: RideStatus?
    /// The ride's athlete, privacy-projected server-side.
    var rider: FeedActor? = nil
}

struct GpsPoint: Codable {
    let latitude: Double?
    let longitude: Double?
    let elevationM: Double?
    /// DEM-corrected elevation for this point (wire `elevation_corrected_m`).
    /// Null on individual points means no trustworthy value there — clients
    /// gap the relief line, never bridge or zero-fill. All-null when the
    /// ride's correction status is not `corrected`.
    let elevationCorrectedM: Double?
    let distanceM: Double?
    /// Numeric epoch seconds (backend delta-decoded track).
    let timestamp: Double?
    var redacted: Bool? = nil
}

extension GpsPoint {
    var hasVisibleCoordinate: Bool {
        guard redacted != true, let latitude, let longitude else { return false }
        return latitude.isFinite && longitude.isFinite &&
            (-90...90).contains(latitude) && (-180...180).contains(longitude)
    }
}

struct GpsResponse: Codable {
    let gpsPoints: [GpsPoint]
}

enum RideStreamKind: String, CaseIterable, Identifiable, Sendable {
    case power
    case heartRate = "heart_rate"
    case cadence
    case speed

    var id: String { rawValue }

    var title: String {
        switch self {
        case .power: "Power"
        case .heartRate: "Heart rate"
        case .cadence: "Cadence"
        case .speed: "Speed"
        }
    }

    func unit(_ units: UnitSystem) -> String {
        switch self {
        case .power: "W"
        case .heartRate: "bpm"
        case .cadence: "rpm"
        case .speed: units.speedUnit
        }
    }

    /// Display decimals from the precision ledger.
    var precision: Int {
        switch self {
        case .power: Precision.power
        case .heartRate: Precision.heartRate
        case .cadence: Precision.cadence
        case .speed: Precision.speed
        }
    }

    /// Streams arrive in base units (speed in m/s); display converts.
    func displayValue(_ raw: Double, units: UnitSystem) -> Double {
        self == .speed ? units.speedValue(fromMps: raw) : raw
    }
}

struct RideStreamResponse: Codable, Sendable {
    let id: String?
    let rideId: String
    let streamType: String
    let timestamps: [String]
    let values: [Double]
    let sampleCount: Int
    let minValue: Double?
    let maxValue: Double?
    let avgValue: Double?
    let redacted: Bool?

    var hasSamples: Bool {
        redacted != true && timestamps.count == values.count && values.count >= 2
    }
}

struct RideOriginalFile: Codable, Sendable {
    let signedUrl: String
    let fileName: String
    let fileType: String
    let mimeType: String
    let expiresIn: Int
}

struct RideDeleteResponse: Codable, Sendable {
    let status: String
    let rideId: String
}

// MARK: - Patterns (per-ride climbs)

/// Vault-match truth on a climb pattern. Ride-contract v1 (bead 71o2v) emits
/// this only where the ride produced an authoritative vault completion:
/// yourTime/isPR/yourBestTime/yourRank are chain-projection facts, never
/// guesses. vaultClimbId (canon registry UUID) remains the climb-sheet key.
struct VaultMatch: Codable {
    let id: String?
    let vaultId: Int?
    let vaultClimbId: String?
    let name: String?
    let yourTime: Double?
    let isPR: Bool?
    let yourBestTime: Double?
    let yourRank: Int?
    let komTime: Double?
    let komHolder: String?

    private enum CodingKeys: String, CodingKey {
        case id
        case vaultId
        case vaultClimbId
        case name
        case yourTime
        // `convertFromSnakeCase` normalizes the production `is_pr` key to
        // `isPr`; Swift's acronym spelling would otherwise leave `isPR` nil.
        case isPR = "isPr"
        case yourBestTime
        case yourRank
        case komTime
        case komHolder
    }
}

// The patterns response preserves camelCase `isPR`; older snake-case
// responses normalize to `isPr`. Both are the same authoritative fact.
extension VaultMatch {
    var isAuthoritativeCompletion: Bool {
        vaultId != nil && yourTime.map { $0.isFinite && $0 > 0 } == true
    }

    init(from decoder: Decoder) throws {
        enum CamelKeys: String, CodingKey { case isPR }
        let values = try decoder.container(keyedBy: CodingKeys.self)
        let camel = try decoder.container(keyedBy: CamelKeys.self)
        id = try values.decodeIfPresent(String.self, forKey: .id)
        vaultId = try values.decodeIfPresent(Int.self, forKey: .vaultId)
        vaultClimbId = try values.decodeIfPresent(String.self, forKey: .vaultClimbId)
        name = try values.decodeIfPresent(String.self, forKey: .name)
        yourTime = try values.decodeIfPresent(Double.self, forKey: .yourTime)
        isPR = try values.decodeIfPresent(Bool.self, forKey: .isPR)
            ?? camel.decodeIfPresent(Bool.self, forKey: .isPR)
        yourBestTime = try values.decodeIfPresent(Double.self, forKey: .yourBestTime)
        yourRank = try values.decodeIfPresent(Int.self, forKey: .yourRank)
        komTime = try values.decodeIfPresent(Double.self, forKey: .komTime)
        komHolder = try values.decodeIfPresent(String.self, forKey: .komHolder)
    }
}

struct ClimbPattern: Codable {
    let id: String?
    let name: String?
    let roadName: String?
    /// Canon registry UUID (same key space as `vaultMatch.vaultClimbId` and
    /// `GET /climbs/{id}`), present exactly when the stored pattern is an
    /// authoritative canon traversal — independent of completion state
    /// (live contract 2026-08-11, bead `boulderroller-v2-nrbu5`). Absent
    /// means no authoritative canon identity; the row then has nowhere to go.
    let climbId: String?
    let vertM: Double?
    let timeS: Double?
    let durationS: Double?
    let distanceM: Double?
    let avgGradientPct: Double?
    let startOffsetS: Double?
    let endOffsetS: Double?
    let startTimeOffsetS: Double?
    let endTimeOffsetS: Double?
    let startIdx: Int?
    let endIdx: Int?
    let vaultMatch: VaultMatch?

    var stableId: String { id ?? "\(shownName)-\(startOffsetS ?? startTimeOffsetS ?? 0)" }
    var shownName: String { name ?? roadName ?? vaultMatch?.name ?? "Climb" }
    var effortDurationS: Double? { durationS ?? timeS }
    var effortStartS: Double? { startOffsetS ?? startTimeOffsetS }
    var effortEndS: Double? { endOffsetS ?? endTimeOffsetS }
    /// The climb sheet key: the vault-completion projection when the ride
    /// produced one, else the pattern's own authoritative canon traversal id.
    var canonClimbId: String? { vaultMatch?.vaultClimbId ?? climbId }
}

struct PatternsPayload: Codable {
    let climbPatterns: [ClimbPattern]?
}

struct PatternsResponse: Codable {
    let rideId: String?
    let patterns: PatternsPayload?
}

// MARK: - Climbs

struct ElevationProfilePoint: Codable {
    let distanceM: Double
    let elevationM: Double
}

struct RecordBoardEntry: Codable, Identifiable, ClimbPowerSource {
    let rank: Int
    let wallet: String
    let bestTimeSeconds: Double?
    let achievedAt: String?
    let username: String?
    let displayName: String?
    var position: Int?
    var competitionRank: Int?
    var tieSize: Int?
    var isTied: Bool?
    var avgPowerW: Double?
    var powerKind: String?
    var estimatedPowerW: Double?
    var estimatedPowerRangeW: [Double]?
    var wPerKg: Double?
    var completionId: String?
    var avatarUrl: String?
    var id: String { "\(position ?? rank)-\(wallet)" }

    var shownName: String {
        riderShownName(displayName: displayName, username: username, wallet: wallet)
    }

    var sportingRank: Int { competitionRank ?? rank }
    var isCoKOM: Bool { sportingRank == 1 && (isTied == true || (tieSize ?? 1) > 1) }
    var sportingRankLabel: String { isCoKOM ? "T-1" : "#\(sportingRank)" }
    var avatarURL: URL? { avatarUrl.flatMap(URL.init) }
}

struct RecordBoard: Codable {
    let entries: [RecordBoardEntry]?
    let komHolder: String?
    let komTimeS: Double?
}

struct VaultEconomy: Codable {
    let hasVault: Bool?
    let vaultId: Int?
    let vaultSignature: String?
    let totalStaked: String?
    let totalCalStaked: String?
    let totalCompletions: Int?
}

struct LocalLegendStatus: Codable {
    let wallet: String?
    var electedAt: String?
    var termEndsAt: String?
    var completionsCount: Int?
    var isActive: Bool?
    var isBootstrap: Bool?
    var seatStatus: String?
}

struct Climb: Codable, Identifiable {
    let id: String
    let name: String?
    let lengthM: Double?
    let elevGainM: Double?
    let avgGradientPct: Double?
    let region: String?
    let hasVault: Bool?
    let vaultId: Int?
    let totalCalStaked: String?
    let vaultEconomy: VaultEconomy?
    let recordBoard: RecordBoard?
    let localLegend: LocalLegendStatus?
    let routePreview: RoutePreview?
    let elevationProfile: [ElevationProfilePoint]?
}

struct ClimbListResponse: Codable {
    let climbs: [Climb]?
}

/// Public sporting and stewardship truth attached to an active Climb Vault.
/// This is not the Balance position model; it powers the Climb destination.
struct VaultClimbDetail: Codable {
    let id: Int
    let name: String
    let totalCompletions: Int
    let leaderboard: [RecordBoardEntry]
    let totalCalStaked: String
    let localLegend: LocalLegendStatus?
}

struct VaultEffortHistoryEntry: Codable, Identifiable, ClimbPowerSource {
    let id: String
    let rideId: String?
    let timeSeconds: Double
    let avgPowerW: Double?
    let achievedAt: String?
    let isPR: Bool
    let improvement: Int?
    var powerKind: String?
    var estimatedPowerW: Double?
    var estimatedPowerRangeW: [Double]?
    var wPerKg: Double?

    private enum CodingKeys: String, CodingKey {
        case id
        case rideId
        case timeSeconds
        case avgPowerW
        case powerKind, estimatedPowerW, estimatedPowerRangeW, wPerKg
        case achievedAt
        // The production decoder normalizes `is_pr` to `isPr` before
        // matching CodingKeys; preserve the product acronym in Swift.
        case isPR = "isPr"
        case improvement
    }
}

struct VaultEffortHistoryResponse: Codable {
    let vaultId: Int
    let vaultName: String
    let efforts: [VaultEffortHistoryEntry]
    let totalCount: Int
    let bestTimeSeconds: Double?
    let totalPrs: Int
}

struct PopularClimb: Codable, Identifiable {
    let id: String
    let name: String?
}

struct PopularClimbsResponse: Codable {
    let climbs: [PopularClimb]?
}

// MARK: - Money (read-only in slice one)

struct CalOnchainResponse: Codable {
    let calBalance: String?
    let calBalanceBaseUnits: String?
}

/// One of the rider's allocation rows inside a settled week.
struct DistributionReceiptRow: Codable, Hashable, Identifiable, Sendable {
    let id: String
    let receiptType: String?
    let amount: String?
    let amountBaseUnits: String?
    let rank: Int?
    let createdAt: String?
    let txSignature: String?
}

/// Undistributed carry by settlement bucket — exact decimal strings.
struct CarryBucketsResponse: Codable, Hashable, Sendable {
    let recordRoyalty: String?
    let stakers: String?
    let localLegend: String?
    let pol: String?
    let treasury: String?
}

/// One settled week (vault + epoch) with the canonical itemized amounts.
/// Every amount is the server's exact decimal string; display never routes
/// them through binary float (L2.10).
struct DistributionGroup: Codable, Hashable, Identifiable {
    let distributionId: String
    let vaultSignature: String?
    let vaultName: String?
    let climbName: String?
    let epoch: Int?
    let totalAmount: String?
    let leaderboardAmount: String?
    let stakerAmount: String?
    let localLegendAmount: String?
    let polAmount: String?
    let protocolAmount: String?
    let distributedAt: String?
    /// Empty or absent until the chain finalization event is observed.
    let finalizedAt: String?
    let currentCarry: CarryBucketsResponse?
    let receipts: [DistributionReceiptRow]?
    var id: String { distributionId }
}

struct MyDistributionsResponse: Codable {
    let distributions: [DistributionGroup]?
    let receiptCount: Int?
}

struct Portfolio: Codable {
    let calBalance: String?
    let dungBalance: String?
    let totalStaked: String?
}

struct VaultStake: Codable, Identifiable {
    let vaultSignature: String
    let vaultId: Int?
    let vaultName: String?
    let climbId: String?
    let calStaked: String?
    let calStakedBaseUnits: String?
    let lpTokens: String?
    let lpTokensBaseUnits: String?
    var id: String { vaultSignature }
}

struct MyVaultStakesResponse: Codable {
    let stakes: [VaultStake]?
}

/// Vault list row — the signature → vault id directory (stake rows carry
/// only the signature on the wire).
struct VaultSummary: Codable, Identifiable {
    let id: Int
    let signatureHex: String
    let name: String?
}

struct VaultListResponse: Codable {
    let vaults: [VaultSummary]?
    let total: Int?
}

struct VaultPendingRewardsResponse: Codable {
    let vaultSignature: String?
    let vaultName: String?
    let totalPending: String?
}

// MARK: - Money (Balance writes)

/// Backend-prepared Solana transaction awaiting the rider's signature
/// (`PreparedTransactionResponse` in backend/app/routes/vaults.py).
struct PreparedVaultTransaction: Codable {
    let transaction: String
    let blockhash: String?
    let lastValidBlockHeight: Int
    let message: String?
    let vaultId: Int?
    let pda: String?
}

struct StakeSubmitResponse: Codable {
    let vaultSignature: String?
    let calStaked: String?
    let totalPosition: String?
    let txSignature: String?
    let operationId: String?
    let projectionStatus: String?
    let confirmationStatus: String?
    let riderState: String?
    let message: String?
}

struct UnstakeSubmitResponse: Codable {
    let vaultSignature: String?
    let calReturned: String?
    let txSignature: String?
    let operationId: String?
    let projectionStatus: String?
    let confirmationStatus: String?
    let riderState: String?
    let message: String?
}

struct HarvestSubmitResponse: Codable {
    let vaultSignature: String?
    let vaultName: String?
    let totalHarvested: String?
    let feeAmount: String?
    let netReceived: String?
    let receiptsCount: Int?
    let operationId: String?
    let projectionStatus: String?
    let confirmationStatus: String?
    let riderState: String?
    let message: String?
}

/// Public `/status` subset used to fail Balance controls closed without
/// copying rollout policy into the app.
struct SystemStatusResponse: Codable {
    let balanceRollout: BalanceRolloutStatusResponse
    /// Absent on servers predating the mobile-capabilities contract.
    let mobileCapabilities: MobileCapabilitiesResponse?
}

struct BalanceRolloutStatusResponse: Codable {
    let stage: String
    let cohort: String
    let enabledActions: [String]
    let actionOrder: [String]
    let enforced: Bool
    let orderValid: Bool
    let blockers: [String]
}

/// Authenticated rider-safe projection of one durable Balance operation.
/// Support-only ledger fields intentionally have no representation here.
struct BalanceOperationStatusResponse: Codable, Equatable {
    let operationId: String
    let actionType: String
    let asset: String
    let amount: String
    let referenceType: String?
    let referenceId: String?
    let riderState: String?
    let readState: String
    let pending: Bool
    let delayed: Bool
    let needsReview: Bool
    let recorded: Bool
    var stage1TerminalFailure: Bool? = nil
}

// MARK: - Upload

struct UploadInitResponse: Codable {
    let uploadId: String
    let signedUrl: String
    let expiresIn: Int?
}

struct UploadCompleteResponse: Codable {
    let rideId: String
    let status: String
}

/// One device lap — the rider's own segmentation of the ride.
struct RideLap: Codable, Identifiable {
    let startedAtMs: Int64?
    let totalElapsedS: Double?
    let totalTimerS: Double?
    let totalDistanceM: Double?
    let totalAscentM: Double?
    let avgPowerW: Int?
    let maxPowerW: Int?
    let avgHrBpm: Int?
    let avgCadenceRpm: Int?
    var id: Int64 { startedAtMs ?? 0 }
}

/// Power balance summary from per-sample left/right evidence.
struct RidePowerBalance: Codable {
    let leftPct: Double?
    let rightPct: Double?
    let sampleCount: Int?
}
