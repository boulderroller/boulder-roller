#if DEBUG
import SwiftUI

enum RecordingRecoveryRenderFixtureMode: String {
    case eligible = "eligible"
    case ineligible = "ineligible"
    case localSaved = "local-saved"

    init?(arguments: [String]) {
        guard let marker = arguments.firstIndex(of: "-BRRecordingRecoveryRenderFixture"),
              arguments.indices.contains(marker + 1)
        else { return nil }
        self.init(rawValue: arguments[marker + 1])
    }
}

enum RecordingRecoveryRenderFixtureData {
    static let rider = User(
        id: "local-offline-simulated-owner",
        wallet: "local-offline-simulated-wallet",
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
    static let owner = RecordingOwner(user: rider)

    static let eligibleRecovery = InterruptedRideRecovery(
        id: "77777777-7777-4777-8777-777777777777",
        ownerID: rider.id,
        startedAt: Date(timeIntervalSince1970: 1_800_000_000),
        state: .manuallyPaused,
        sampleCount: 842,
        durationS: 2_147,
        distanceM: 12_874,
        elevationGainM: 286
    )

    static let ineligibleRecovery = InterruptedRideRecovery(
        id: "77777777-7777-4777-8777-777777777778",
        ownerID: rider.id,
        startedAt: Date(timeIntervalSince1970: 1_800_000_120),
        state: .manuallyPaused,
        sampleCount: 12,
        durationS: 48,
        distanceM: 64,
        elevationGainM: nil
    )

    static let localSavedRide = LocalSavedRide(
        id: "77777777-7777-4777-8777-777777777779",
        ownerID: rider.id,
        ownerWallet: rider.wallet,
        summary: LocalRideSummary(
            startedAt: Date(timeIntervalSince1970: 1_800_000_120),
            distanceM: 64,
            elevationM: nil,
            durationS: 48
        ),
        fileHash: String(repeating: "a", count: 64),
        preliminaryRideHash: String(repeating: "b", count: 64),
        parserVersion: 1
    )
}

@MainActor
struct RecordingRecoveryRenderFixtureRoot: View {
    let mode: RecordingRecoveryRenderFixtureMode
    @State private var session: AppSession

    init(mode: RecordingRecoveryRenderFixtureMode) {
        self.mode = mode
        let session = AppSession()
        session.phase = .signedIn(RecordingRecoveryRenderFixtureData.rider)
        session.hasUncollectedSettlements = nil
        session.localSavedRides = mode == .localSaved
            ? [RecordingRecoveryRenderFixtureData.localSavedRide]
            : []
        _session = State(initialValue: session)
    }

    var body: some View {
        Group {
            switch mode {
            case .eligible:
                InterruptedRideRecoveryView(
                    recovery: RecordingRecoveryRenderFixtureData.eligibleRecovery,
                    onSave: {},
                    onDiscard: {}
                )
            case .ineligible:
                InterruptedRideRecoveryView(
                    recovery: RecordingRecoveryRenderFixtureData.ineligibleRecovery,
                    onSave: {},
                    onDiscard: {}
                )
            case .localSaved:
                FeedView(
                    debugItems: [],
                    owner: RecordingRecoveryRenderFixtureData.owner
                )
            }
        }
        .environment(session)
    }
}
#endif
