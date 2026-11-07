#if DEBUG
import Foundation
import SwiftUI

enum ThresholdRenderFixtureMode: String, CaseIterable {
    case establishing
    case established
    case pendingMonday = "pending-monday"

    static let launchArgument = "-BRThresholdRenderFixture"

    init?(arguments: [String]) {
        guard arguments.filter({ $0 == Self.launchArgument }).count == 1,
              let index = arguments.firstIndex(of: Self.launchArgument),
              arguments.indices.contains(index + 1)
        else { return nil }
        self.init(rawValue: arguments[index + 1])
    }
}

struct ThresholdRenderFixtureRoot: View {
    let mode: ThresholdRenderFixtureMode
    private let fixtureNow = ISO8601DateFormatter().date(
        from: "2026-08-24T18:00:00Z"
    )!

    var body: some View {
        ThresholdSheet(display: display, now: fixtureNow)
    }

    private var display: ThresholdDisplay {
        let decoder = JSONDecoder()
        decoder.keyDecodingStrategy = .convertFromSnakeCase
        let response = try! decoder.decode(
            ThresholdResponse.self,
            from: Data(responseJSON.utf8)
        )
        return RiderThresholdStore.display(
            response: response,
            now: fixtureNow
        )!
    }

    private var responseJSON: String {
        switch mode {
        case .establishing:
            return #"{"contract_version":"threshold.v1","state":"establishing","current_w":null,"established_at":null,"last_raised_at":null,"pending_monday":null,"sealing_in_progress":false}"#
        case .established:
            return #"{"contract_version":"threshold.v1","state":"established","current_w":245,"established_at":"2026-08-17T12:00:00Z","last_raised_at":null,"pending_monday":null,"sealing_in_progress":false}"#
        case .pendingMonday:
            return #"{"contract_version":"threshold.v1","state":"established","current_w":245,"established_at":"2026-08-10T12:00:00Z","last_raised_at":"2026-08-17T12:00:00Z","pending_monday":{"watts":251,"effective_at":"2026-08-31T12:00:00Z"},"sealing_in_progress":false}"#
        }
    }
}
#endif
