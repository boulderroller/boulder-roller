#if DEBUG
import Foundation
import SwiftUI

/// Exact DEBUG-only launch modes used to capture the physiology surfaces
/// (bead boulderroller-v2-odmi6.5, client half) deterministically: truthful
/// dashes when nothing was ever entered, real values when the rider set
/// them. No authentication, network write, or production account.
enum PhysiologyRenderFixtureMode: String, CaseIterable {
    case avatarUnset = "avatar-unset"
    case avatarSet = "avatar-set"
    case editWeightImperial = "edit-weight-imperial"

    static let launchArgument = "-BRPhysiologyRenderFixture"

    init?(arguments: [String]) {
        guard arguments.filter({ $0 == Self.launchArgument }).count == 1,
              let argumentIndex = arguments.firstIndex(of: Self.launchArgument),
              arguments.indices.contains(argumentIndex + 1)
        else { return nil }
        self.init(rawValue: arguments[argumentIndex + 1])
    }
}

enum PhysiologyRenderFixtureData {
    static let unsetRiderID = "debug-physiology-unset"
    static let setRiderID = "debug-physiology-set"

    static func rider(id: String) -> User {
        User(
            id: id,
            wallet: id,
            username: nil,
            displayName: "Render Fixture",
            avatarUrl: nil,
            email: nil,
            location: nil,
            preferredUnits: "imperial",
            totalRides: nil,
            totalDistanceKm: nil,
            totalElevationM: nil
        )
    }

    /// Idempotent local seeding: the unset rider is explicitly cleared so
    /// dashes are guaranteed truthful; the set rider carries manual facts.
    static func seed() {
        RiderPhysiologyStore.clearWeight(riderID: unsetRiderID)
        RiderPhysiologyStore.setWeight(kg: 81.4, riderID: setRiderID)
    }
}

@MainActor
struct PhysiologyRenderFixtureRoot: View {
    let mode: PhysiologyRenderFixtureMode
    @State private var session: AppSession

    init(mode: PhysiologyRenderFixtureMode) {
        self.mode = mode
        PhysiologyRenderFixtureData.seed()
        let riderID = mode == .avatarUnset
            ? PhysiologyRenderFixtureData.unsetRiderID
            : PhysiologyRenderFixtureData.setRiderID
        let session = AppSession()
        session.phase = .signedIn(PhysiologyRenderFixtureData.rider(id: riderID))
        _session = State(initialValue: session)
    }

    @ViewBuilder
    var body: some View {
        switch mode {
        case .avatarUnset, .avatarSet:
            AvatarSheet()
                .environment(session)
        case .editWeightImperial:
            PhysiologyEditSheet(
                riderID: PhysiologyRenderFixtureData.setRiderID,
                usesMetricWeight: false
            )
            .environment(session)
        }
    }
}
#endif
