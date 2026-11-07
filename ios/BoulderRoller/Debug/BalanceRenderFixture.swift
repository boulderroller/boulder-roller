#if DEBUG
import Foundation
import SwiftUI

/// Exact DEBUG-only launch modes used to capture deterministic Balance
/// surfaces without authentication, network reads, or signed actions.
enum BalanceRenderFixtureMode: String, CaseIterable {
    case climbDetail = "climb-detail"
    case climbRollout = "climb-rollout"
    case settlementsCollect = "settlements-collect"
    case settlementsNeedsReview = "settlements-needs-review"

    static let launchArgument = "-BRBalanceRenderFixture"

    init?(arguments: [String]) {
        guard arguments.filter({ $0 == Self.launchArgument }).count == 1,
              let argumentIndex = arguments.firstIndex(of: Self.launchArgument),
              arguments.indices.contains(argumentIndex + 1)
        else { return nil }
        self.init(rawValue: arguments[argumentIndex + 1])
    }
}

/// Deterministic local inputs for the actual post-change Balance surfaces.
/// The entire harness is excluded from release compilation by the file-level
/// DEBUG guard; no production account, API request, or signed action is used.
enum BalanceRenderFixtureData {
    static let currentRolloutAvailability = BalanceActionAvailability(
        status: SystemStatusResponse(
            balanceRollout: BalanceRolloutStatusResponse(
                stage: "deposit_cal",
                cohort: "internal",
                enabledActions: ["collect_dung", "deposit_cal"],
                actionOrder: ["collect_dung", "deposit_cal", "withdraw_cal"],
                enforced: true,
                orderValid: true,
                blockers: []
            ),
            mobileCapabilities: nil
        )
    )

    static let climb = BalanceClimbRenderFixture(
        climb: Climb(
            id: "debug-balance-the-wall",
            name: "The Wall",
            lengthM: nil,
            elevGainM: nil,
            avgGradientPct: nil,
            region: nil,
            hasVault: true,
            vaultId: 42,
            totalCalStaked: nil,
            vaultEconomy: VaultEconomy(
                hasVault: true,
                vaultId: 42,
                vaultSignature: nil,
                totalStaked: nil,
                totalCalStaked: nil,
                totalCompletions: nil
            ),
            recordBoard: nil,
            localLegend: nil,
            routePreview: nil,
            elevationProfile: nil
        ),
        positionTruth: ResolvedVaultPosition(
            stake: nil,
            depositPriorCalBaseUnits: "0"
        )
    )

    static let climbDetail: BalanceClimbRenderFixture = {
        let board = [
            RecordBoardEntry(
                rank: 1, wallet: "debug-rider-avery", bestTimeSeconds: 268,
                achievedAt: "2026-08-02T12:10:00Z", username: "avery",
                displayName: "Avery Brooks", position: 1, competitionRank: 1,
                tieSize: 2, isTied: true, avgPowerW: 331,
                completionId: "completion-1", avatarUrl: nil
            ),
            RecordBoardEntry(
                rank: 2, wallet: "debug-rider-jordan", bestTimeSeconds: 268,
                achievedAt: "2026-08-09T13:05:00Z", username: "jordan",
                displayName: "Jordan Lee", position: 2, competitionRank: 1,
                tieSize: 2, isTied: true, avgPowerW: 318,
                completionId: "completion-2", avatarUrl: nil
            ),
            RecordBoardEntry(
                rank: 3, wallet: "debug-rider-sam", bestTimeSeconds: 271,
                achievedAt: "2026-07-26T11:42:00Z", username: "sam",
                displayName: "Sam Rivera", position: 3, competitionRank: 3,
                tieSize: 1, isTied: false, avgPowerW: 304,
                completionId: "completion-3", avatarUrl: nil
            ),
            RecordBoardEntry(
                rank: 4, wallet: "debug-balance-rider", bestTimeSeconds: 272,
                achievedAt: "2026-08-12T18:24:00Z", username: nil,
                displayName: "Gabe", position: 4, competitionRank: 4,
                tieSize: 1, isTied: false, avgPowerW: 298,
                completionId: "completion-4", avatarUrl: nil
            ),
        ]
        let legend = LocalLegendStatus(
            wallet: "debug-rider-jordan",
            electedAt: "2026-07-19T12:00:00Z",
            termEndsAt: "2026-09-13T12:00:00Z",
            completionsCount: 9,
            isActive: true,
            isBootstrap: false,
            seatStatus: "elected"
        )
        return BalanceClimbRenderFixture(
            climb: Climb(
                id: "debug-barren-hill-road",
                name: "Barren Hill Road",
                lengthM: 840,
                elevGainM: 62,
                avgGradientPct: 7.4,
                region: "Manayunk, Philadelphia",
                hasVault: true,
                vaultId: 42,
                totalCalStaked: "184500",
                vaultEconomy: VaultEconomy(
                    hasVault: true,
                    vaultId: 42,
                    vaultSignature: "debug-vault",
                    totalStaked: "184500",
                    totalCalStaked: "184500",
                    totalCompletions: 37
                ),
                recordBoard: RecordBoard(
                    entries: board,
                    komHolder: "debug-rider-avery",
                    komTimeS: 268
                ),
                localLegend: legend,
                routePreview: RoutePreview(
                    source: "debug",
                    points: [
                        .init(x: 0.08, y: 0.88), .init(x: 0.20, y: 0.76),
                        .init(x: 0.36, y: 0.69), .init(x: 0.48, y: 0.55),
                        .init(x: 0.62, y: 0.47), .init(x: 0.75, y: 0.30),
                        .init(x: 0.93, y: 0.12),
                    ],
                    segments: nil,
                    bounds: .init(
                        minLat: 40.061, minLon: -75.244,
                        maxLat: 40.071, maxLon: -75.232
                    ),
                    placeLabel: "Manayunk, Philadelphia",
                    fallbackReason: nil
                ),
                elevationProfile: [
                    .init(distanceM: 0, elevationM: 48),
                    .init(distanceM: 130, elevationM: 54),
                    .init(distanceM: 270, elevationM: 66),
                    .init(distanceM: 410, elevationM: 73),
                    .init(distanceM: 560, elevationM: 88),
                    .init(distanceM: 700, elevationM: 101),
                    .init(distanceM: 840, elevationM: 110),
                ]
            ),
            positionTruth: ResolvedVaultPosition(
                stake: VaultStake(
                    vaultSignature: "debug-vault",
                    vaultId: 42,
                    vaultName: "Barren Hill Road",
                    climbId: "debug-barren-hill-road",
                    calStaked: "2000",
                    calStakedBaseUnits: "2000000000000",
                    lpTokens: "2000",
                    lpTokensBaseUnits: "2000000000000"
                ),
                depositPriorCalBaseUnits: "2000000000000"
            ),
            vaultDetail: VaultClimbDetail(
                id: 42,
                name: "Barren Hill Road",
                totalCompletions: 37,
                leaderboard: board,
                totalCalStaked: "184500",
                localLegend: legend
            ),
            results: VaultEffortHistoryResponse(
                vaultId: 42,
                vaultName: "Barren Hill Road",
                efforts: [
                    .init(
                        id: "effort-3", rideId: "debug-ride-3",
                        timeSeconds: 272, avgPowerW: 298,
                        achievedAt: "2026-08-12T18:24:00Z",
                        isPR: true, improvement: 4
                    ),
                    .init(
                        id: "effort-2", rideId: "debug-ride-2",
                        timeSeconds: 276, avgPowerW: 291,
                        achievedAt: "2026-08-05T17:55:00Z",
                        isPR: true, improvement: 6
                    ),
                    .init(
                        id: "effort-1", rideId: "debug-ride-1",
                        timeSeconds: 282, avgPowerW: 284,
                        achievedAt: "2026-07-29T18:02:00Z",
                        isPR: true, improvement: nil
                    ),
                ],
                totalCount: 6,
                bestTimeSeconds: 272,
                totalPrs: 3
            ),
            legendName: "Jordan Lee"
        )
    }()

    static let collectAvailable = BalanceSettlementsRenderFixture(
        uncollected: 12,
        history: [settledWeek],
        status: .idle
    )

    /// One itemized settled week (L2.10) — exact decimal strings as the
    /// wire carries them.
    static let settledWeek = DistributionGroup(
        distributionId: "v4a:16:131",
        vaultSignature: "debug-signature",
        vaultName: nil,
        climbName: nil,
        epoch: 131,
        totalAmount: "60.000000001",
        leaderboardAmount: "33.0",
        stakerAmount: "16.200000001",
        localLegendAmount: "1.8",
        polAmount: "6.0",
        protocolAmount: "3.0",
        distributedAt: "2026-08-17T12:00:00Z",
        finalizedAt: "2026-08-18T12:00:00Z",
        currentCarry: CarryBucketsResponse(
            recordRoyalty: "0", stakers: "2.5", localLegend: "0",
            pol: "0", treasury: "0"
        ),
        receipts: [
            DistributionReceiptRow(
                id: "alloc-1", receiptType: "staker_allocation",
                amount: "8.100000001", amountBaseUnits: "8100000001",
                rank: nil, createdAt: "2026-08-17T12:00:05Z", txSignature: nil
            ),
            DistributionReceiptRow(
                id: "alloc-2", receiptType: "staker_allocation",
                amount: "4.2", amountBaseUnits: "4200000000",
                rank: 2, createdAt: "2026-08-17T12:00:06Z", txSignature: nil
            ),
        ]
    )

    static let needsReview = BalanceSettlementsRenderFixture(
        uncollected: 12,
        history: [],
        status: .needsReview
    )

    static let rider = User(
        id: "debug-balance-rider",
        wallet: "debug-balance-rider",
        username: nil,
        displayName: nil,
        avatarUrl: nil,
        email: nil,
        location: nil,
        preferredUnits: "imperial",
        totalRides: nil,
        totalDistanceKm: nil,
        totalElevationM: nil
    )
}

struct BalanceClimbRenderFixture {
    let climb: Climb
    let positionTruth: ResolvedVaultPosition?
    let vaultDetail: VaultClimbDetail?
    let results: VaultEffortHistoryResponse?
    let legendName: String?

    init(
        climb: Climb,
        positionTruth: ResolvedVaultPosition?,
        vaultDetail: VaultClimbDetail? = nil,
        results: VaultEffortHistoryResponse? = nil,
        legendName: String? = nil
    ) {
        self.climb = climb
        self.positionTruth = positionTruth
        self.vaultDetail = vaultDetail
        self.results = results
        self.legendName = legendName
    }
}

struct BalanceSettlementsRenderFixture {
    let uncollected: Double?
    let history: [DistributionGroup]
    let status: MoneyModel.Status
}

@MainActor
struct BalanceRenderFixtureRoot: View {
    let mode: BalanceRenderFixtureMode
    @State private var session: AppSession

    init(mode: BalanceRenderFixtureMode) {
        self.mode = mode
        let session = AppSession()
        session.phase = .signedIn(BalanceRenderFixtureData.rider)
        session.balanceActions = BalanceRenderFixtureData.currentRolloutAvailability
        session.hasUncollectedSettlements = nil
        _session = State(initialValue: session)
    }

    @ViewBuilder
    var body: some View {
        switch mode {
        case .climbDetail:
            NavigationStack { ClimbDetailView(renderFixture: BalanceRenderFixtureData.climbDetail) }
                .environment(session)
        case .climbRollout:
            NavigationStack { ClimbDetailView(renderFixture: BalanceRenderFixtureData.climb) }
                .environment(session)
        case .settlementsCollect:
            SettlementsView(renderFixture: BalanceRenderFixtureData.collectAvailable)
                .environment(session)
        case .settlementsNeedsReview:
            SettlementsView(renderFixture: BalanceRenderFixtureData.needsReview)
                .environment(session)
        }
    }
}
#endif
