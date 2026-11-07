#if DEBUG
import Foundation
import SwiftUI

enum RideUploadRenderFixtureMode: String, CaseIterable {
    case processing
    case failed
    case held
    case reading
    case coin
    case mark
    case ledger
    case ledgerLarge
    case stone
    case after
    case ceremony
    case reduceMotion

    static let launchArgument = "-BRRideUploadRenderFixture"

    init?(arguments: [String]) {
        guard arguments.filter({ $0 == Self.launchArgument }).count == 1,
              let index = arguments.firstIndex(of: Self.launchArgument),
              arguments.indices.contains(index + 1)
        else { return nil }
        self.init(rawValue: arguments[index + 1])
    }
}

enum RideUploadRenderFixtureData {
    static let rider = User(
        id: "debug-upload-rider",
        wallet: "debug-upload-wallet",
        username: nil,
        displayName: "Rider",
        avatarUrl: nil,
        email: nil,
        location: nil,
        preferredUnits: "imperial",
        totalRides: nil,
        totalDistanceKm: nil,
        totalElevationM: nil
    )

    static func job(phase: RideUploadPhase) -> RideUploadJob {
        let isFailure = phase == .failed
        let id = isFailure
            ? "77777777-7777-4777-8777-777777777772"
            : "77777777-7777-4777-8777-777777777771"
        return RideUploadJob(
            id: id,
            ownerID: rider.id,
            ownerWallet: rider.wallet,
            fileName: "Sunday Ride.gpx",
            fileType: "gpx",
            fileHash: String(repeating: "a", count: 64),
            fileSize: 1_024,
            sourceFileName: "source.gpx",
            localSummary: LocalRideSummary(
                startedAt: Date(timeIntervalSince1970: 1_786_365_000),
                distanceM: isFailure ? nil : 20_116.8,
                elevationM: nil,
                durationS: isFailure ? nil : 3_180
            ),
            createdAt: Date(timeIntervalSince1970: 1_786_365_030),
            updatedAt: Date(timeIntervalSince1970: 1_786_365_060),
            phase: phase,
            attemptedServerHandoff: true,
            signedURL: nil,
            signedURLExpiresAt: nil,
            serverRideID: nil,
            authoritativeStatus: isFailure ? "failed" : "processing",
            attemptCount: 1,
            nextRetryAt: nil,
            lastError: isFailure ? "Processing failed" : nil,
            canRetry: isFailure,
            revealState: .none,
            reveal: nil
        )
    }
}

@MainActor
struct RideUploadRenderFixtureRoot: View {
    let mode: RideUploadRenderFixtureMode
    @State private var session: AppSession

    init(mode: RideUploadRenderFixtureMode) {
        self.mode = mode
        let session = AppSession()
        session.phase = .signedIn(RideUploadRenderFixtureData.rider)
        session.hasUncollectedSettlements = nil
        _session = State(initialValue: session)
    }

    @State private var showsVerification = false
    @State private var finished = false
    @State private var showsRide = false

    var body: some View {
        Group {
            if mode == .reading {
                ProcessingBeat(spine: RideUploadRenderFixtureData.reveal.spine ?? .empty, title: "In the bag", freezesMotion: true)
            } else if mode == .after || showsRide {
                NavigationStack { RideDetailView(rideId: "fixture-ride", initialDetail: RideUploadRenderFixtureData.detail, initialClimbs: RideUploadRenderFixtureData.patterns) }
            } else if finished {
                FeedView(debugItems: [], owner: RecordingOwner(user: RideUploadRenderFixtureData.rider))
            } else if [.held, .coin, .mark, .ledger, .ledgerLarge, .stone, .ceremony, .reduceMotion].contains(mode) {
                RevealView(data: mode == .held ? RideUploadRenderFixtureData.heldReveal : RideUploadRenderFixtureData.reveal,
                           initialBeat: mode == .coin || (mode == .ceremony || mode == .reduceMotion) ? .coin : mode == .mark ? .mark : .ledger,
                           freezesMotion: mode != .ceremony && mode != .reduceMotion,
                           drainSteps: mode == .stone || mode == .held || mode == .ledgerLarge ? 100 : mode == .ledger ? 5 : 0,
                           onDone: { finished = true }, onViewRide: { showsRide = true },
                           onVerification: { showsVerification = true })
                .dynamicTypeSize(mode == .ledgerLarge ? .accessibility2 : .large)
            } else {
                let phase: RideUploadPhase = mode == .processing ? .processing : .failed
                FeedView(debugItems: [RideFeedItem(id: RideUploadRenderFixtureData.job(phase: phase).id,
                    source: .local(RideUploadRenderFixtureData.job(phase: phase)))],
                    owner: RecordingOwner(user: RideUploadRenderFixtureData.rider))
            }
        }
        .environment(\.revealPreviewReduceMotion, mode == .reduceMotion)
        .environment(session)
        .environment(\.units, .metric)
        .sheet(isPresented: $showsVerification) {
            RevealVerificationView(verification: RideUploadRenderFixtureData.reveal.verification)
        }
    }
}

extension RideUploadRenderFixtureData {
    /// Board-shaped, offline fixture. These sample amounts/seats are not API evidence.
    static var reveal: RevealData {
        let profile = try! JSONDecoder().decode([RideSpineData.Point].self,
            from: Data(contentsOf: Bundle.main.url(forResource: "BoulderRolledProfile", withExtension: "json")!))
        return RevealData(title: "In the bag", subtitle: "Sunday 9:07 AM", calEarned: 84,
            distanceM: 128_700, elevationM: 1_013, durationS: 16_066,
            climbs: [
                .init(name: "Wises Mill Road", timeS: 235, isLeaderboardEntry: false, patternID: "wises", isNewBest: false),
                .init(name: "Black Rock Road", timeS: 82, isLeaderboardEntry: true, patternID: "black", isNewBest: true, previousBestTimeS: 86),
                .init(name: "Sprague Road", timeS: 251, isLeaderboardEntry: false, patternID: "sprague", isNewBest: false)
            ], tributeCal: nil,
            leaderboardEntry: .init(rank: 3, climbName: "Black Rock Road", timeS: 82, wasTimeS: nil,
                previousBestTimeS: 86, neighboringSeats: [
                    .init(rank: 1, name: "Marcus Reid", timeS: 75),
                    .init(rank: 2, name: "Priya Anand", timeS: 79),
                    .init(rank: 4, name: "Jordan Lee", timeS: 84, previousRank: 3)
                ]),
            tributeLines: [
                .init(patternID: "wises", climbName: "Wises Mill Road", baseUnits: "6000000000", decimals: 9),
                .init(patternID: "black", climbName: "Black Rock Road", baseUnits: "3000000000", decimals: 9),
                .init(patternID: "sprague", climbName: "Sprague Road", baseUnits: "5000000000", decimals: 9)
            ], spine: RideSpineData(runs: [profile], spans: [
                .init(climbID: "wises", startDistanceM: 42_000, endDistanceM: 45_000),
                .init(climbID: "black", startDistanceM: 89_000, endDistanceM: 92_000),
                .init(climbID: "sprague", startDistanceM: 108_000, endDistanceM: 111_000)
            ]), verification: .init(status: "attested", rideHash: String(repeating: "a", count: 64), transaction: nil))
    }
    static var heldReveal: RevealData {
        var data = reveal
        data.thresholdEconomyState = "held"
        data.tributeLines = nil
        return data
    }
    static var patterns: [ClimbPattern] {
        try! JSONDecoder().decode([ClimbPattern].self, from: Data("""
        [{"id":"wises","name":"Wises Mill Road","climbId":"wises","durationS":235},
         {"id":"black","name":"Black Rock Road","climbId":"black","durationS":82,
          "vaultMatch":{"vaultId":3,"vaultClimbId":"black","yourRank":3,"yourTime":82,"isPR":true}},
         {"id":"sprague","name":"Sprague Road","climbId":"sprague","durationS":251}]
        """.utf8))
    }
    static var detail: RideDetailResponse {
        let detail = try! JSONDecoder().decode(RideDetailResponse.self, from: Data("""
        {"ride":{"id":"fixture-ride","title":"In the bag","startedAt":"2026-09-06T13:07:00Z",
        "isOwner":true,"status":"completed","distanceM":128700,"elevationM":1013,"durationS":16066,"calEarned":84}}
        """.utf8))
        var ride = detail.ride
        ride.elevationProfile = reveal.spine?.runs.first
        ride.countedSpans = reveal.spine?.spans
        return RideDetailResponse(ride: ride, status: nil)
    }
}
#endif
