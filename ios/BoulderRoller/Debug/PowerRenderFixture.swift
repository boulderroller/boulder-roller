#if DEBUG
import SwiftUI

/// Local, synthetic rendering evidence only. No session or network write.
enum PowerRenderFixtureMode: String {
    case leaderboard
    case privacy
    case privacyError = "privacy-error"

    static let launchArgument = "-BRPowerRenderFixture"

    init?(arguments: [String]) {
        guard arguments.filter({ $0 == Self.launchArgument }).count == 1,
              let index = arguments.firstIndex(of: Self.launchArgument),
              arguments.indices.contains(index + 1)
        else { return nil }
        self.init(rawValue: arguments[index + 1])
    }
}

@MainActor
struct PowerRenderFixtureRoot: View {
    let mode: PowerRenderFixtureMode
    @State private var model: PrivacyModel

    init(mode: PowerRenderFixtureMode) {
        self.mode = mode
        let model = PrivacyModel()
        var settings = Self.decode(PrivacySettings.self, Self.settingsJSON)
        let zones = PrivacyZonesList(zones: [], maxZones: 0)
        model.cachedSettings = { nil }
        model.cachedZones = { nil }
        model.fetchSettings = { settings }
        model.fetchZones = { zones }
        model.putShareWkg = { value in
            if mode == .privacyError {
                throw APIError.http(status: 503, code: nil, message: "Please retry.")
            }
            settings.shareWkg = value
            return settings
        }
        model.putDefaultVisibility = { _ in
            throw APIError.http(status: 503, code: nil, message: "Local render fixture.")
        }
        _model = State(initialValue: model)
    }

    var body: some View {
        Group {
            if mode == .leaderboard {
                NavigationStack {
                    LeaderboardView(
                        climbName: "Fixture Hill",
                        entries: Self.decode([RecordBoardEntry].self, Self.boardJSON),
                        myWallet: nil
                    )
                }
            } else {
                PrivacyView(renderModel: model)
            }
        }
        .safeAreaInset(edge: .bottom) {
            Text("LOCAL RENDER FIXTURE")
                .font(.caption2)
                .foregroundStyle(Theme.gray)
                .padding(8)
                .frame(maxWidth: .infinity)
                .background(Theme.sheet)
        }
    }

    private static func decode<T: Decodable>(_ type: T.Type, _ json: String) -> T {
        let decoder = JSONDecoder()
        decoder.keyDecodingStrategy = .convertFromSnakeCase
        return try! decoder.decode(type, from: Data(json.utf8))
    }

    private static let settingsJSON = """
    {"contractVersion":"privacy.v2","profileVisibility":"public",
     "defaultRideVisibility":"public","defaultMapVisibility":"hide_start_end",
     "defaultMapHideStartM":200,"defaultMapHideEndM":200,"privacyZoneCount":0,
     "privacyZonesLoaded":true,"shareWkg":false}
    """

    private static let boardJSON = """
    [
      {"rank":1,"wallet":"fixture-measured","display_name":"Alex Morgan",
       "best_time_seconds":268,"achieved_at":"2026-10-19T12:00:00Z",
       "avg_power_w":324,"power_kind":"measured","w_per_kg":4.05},
      {"rank":2,"wallet":"fixture-estimated","display_name":"Sam Rivera",
       "best_time_seconds":281,"achieved_at":"2026-10-18T12:00:00Z",
       "power_kind":"estimated","estimated_power_w":278,"estimated_power_range_w":[250,310]},
      {"rank":3,"wallet":"fixture-private-wkg","display_name":"Jordan Lee",
       "best_time_seconds":286,"achieved_at":"2026-10-17T12:00:00Z",
       "avg_power_w":301,"power_kind":"measured"},
      {"rank":4,"wallet":"fixture-no-power","display_name":"Avery Brooks",
       "best_time_seconds":302,"achieved_at":"2026-10-16T12:00:00Z"}
    ]
    """
}
#endif
