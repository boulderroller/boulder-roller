#if DEBUG
import Foundation
import SwiftUI

enum RideDetailRenderFixtureMode: String, CaseIterable, Sendable {
    case finished
    /// A GPS-only ride: no photos, streams, laps, weather, effort, or
    /// corrected elevation — the page most old imports actually produce.
    case sparse
    case hiddenEnds
    case hiddenMiddle
    case noMap

    static let launchArgument = "-BRRideDetailRenderFixture"

    init?(arguments: [String]) {
        guard arguments.filter({ $0 == Self.launchArgument }).count == 1,
              let index = arguments.firstIndex(of: Self.launchArgument),
              arguments.indices.contains(index + 1)
        else { return nil }
        self.init(rawValue: arguments[index + 1])
    }
}

@MainActor
struct EstimateCopyRenderFixtureRoot: View {
    @State private var showingDetails = false
    private let presentation = EstimatePresentation(
        value: 265, estimate: true, range: [252, 278], format: { Format.threshold(Int($0)) }
    )
    // Synthetic layout copy only. The production basis map remains unchanged.
    private let copyLines = [
        "Fixture copy for wrapping: this long sentence checks that the whole first line remains inside the estimate card.",
        "More fixture copy for wrapping: this long sentence checks scrolling so the complete second line can still be read.",
    ]

    var body: some View {
        ZStack(alignment: .bottomLeading) {
            Theme.screen.ignoresSafeArea()
            VStack(alignment: .leading, spacing: 20) {
                Text("Estimate copy fixture").font(.caption).foregroundStyle(Theme.gray)
                Button { showingDetails.toggle() } label: {
                    HStack(alignment: .firstTextBaseline, spacing: 0) {
                        Text("≈").foregroundStyle(Theme.gray)
                        Text(presentation.formattedValue).foregroundStyle(Theme.ink)
                    }
                    .font(.numeral(.body))
                }
                .accessibilityLabel(presentation.accessibilityLabel)
                .popover(isPresented: $showingDetails, attachmentAnchor: .rect(.bounds), arrowEdge: .bottom) {
                    EstimateDetailsCard(presentation: presentation, copyLines: copyLines)
                        .presentationCompactAdaptation(.popover)
                        .presentationBackground(Theme.sheet)
                        .accessibilityAction(.escape) { showingDetails = false }
                }
            }
            .padding(20)
            .padding(.bottom, 80)
        }
    }
}

@MainActor
struct RideDetailRenderFixtureRoot: View {
    let mode: RideDetailRenderFixtureMode
    @State private var session: AppSession

    init(mode: RideDetailRenderFixtureMode) {
        self.mode = mode
        // Session settings remain local fixture state; zones below come from the
        // explicit synthetic backend training payload.
        RiderPhysiologyStore.adoptServerWeight(
            weightKg: 73,
            weightSource: "manual",
            riderID: "debug-rider"
        )
        _ = RiderThresholdStore.save(
            ThresholdResponse(
                contractVersion: "threshold.v1",
                state: "established",
                currentW: 265,
                establishedAt: "2026-08-17T12:00:00Z",
                lastRaisedAt: nil,
                pendingMonday: nil,
                sealingInProgress: false
            ),
            riderID: "debug-rider",
            now: ISO8601DateFormatter().date(from: "2026-08-24T18:00:00Z")!
        )
        let session = AppSession()
        session.phase = .signedIn(User(
            id: "debug-rider",
            wallet: "debug-wallet",
            username: "avery",
            displayName: "Avery",
            avatarUrl: nil,
            email: nil,
            location: "Philadelphia, PA",
            preferredUnits: "imperial",
            totalRides: 24,
            totalDistanceKm: 1_208,
            totalElevationM: 16_420,
            weightKg: 73,
            weightKgSource: "manual"
        ))
        _session = State(initialValue: session)
    }

    var body: some View {
        NavigationStack { RideDetailView(
            rideId: fixture.ride.id,
            initialDetail: fixture,
            initialGPS: fixtureGPS,
            initialClimbs: fixtureClimbs,
            initialStreams: fixtureStreams
        ) }
        .environment(session)
        // Mirrors the production root's injection; -BRUnitsMetric renders
        // the same fixture in the metric system for visual verification.
        .environment(\.units, UnitSystem(
            preferredUnits: ProcessInfo.processInfo.arguments.contains("-BRUnitsMetric")
                ? "metric"
                : session.currentUser?.preferredUnits
        ))
    }

    private var fixture: RideDetailResponse {
        if mode == .finished || mode == .sparse {
            return decode(mode == .sparse ? Self.sparseFixtureJSON : Self.fixtureJSON,
                          as: RideDetailResponse.self)
        }
        var root = try! JSONSerialization.jsonObject(with: Data(Self.sparseFixtureJSON.utf8)) as! [String: Any]
        var ride = root["ride"] as! [String: Any]
        ride["is_owner"] = false
        ride.removeValue(forKey: "route_preview")
        var privacy = ride["privacy"] as! [String: Any]
        privacy["is_owner"] = false
        privacy["reason"] = "public"
        privacy["map_visibility"] = mode == .noMap ? RideMapVisibility.hideEntire.rawValue : RideMapVisibility.hideStartEnd.rawValue
        ride["privacy"] = privacy
        root["ride"] = ride
        return decode(String(data: try! JSONSerialization.data(withJSONObject: root), encoding: .utf8)!, as: RideDetailResponse.self)
    }

    /// The dense fixture with every key a GPS-only import genuinely lacks
    /// removed — sensors, correction, structure, conditions, media.
    private static var sparseFixtureJSON: String {
        var root = try! JSONSerialization.jsonObject(
            with: Data(fixtureJSON.utf8)
        ) as! [String: Any]
        var ride = root["ride"] as! [String: Any]
        for key in [
            "description", "media", "perceived_exertion",
            "weather_temp_c", "weather_wind_mps", "weather_source",
            "laps", "power_balance", "avg_power_w", "normalized_power_w",
            "avg_hr_bpm", "tss", "elevation_corrected_m",
        ] {
            ride.removeValue(forKey: key)
        }
        root["ride"] = ride
        let data = try! JSONSerialization.data(withJSONObject: root)
        return String(data: data, encoding: .utf8)!
    }

    private var fixtureGPS: GpsResponse? {
        let gps = decode(Self.gpsJSON, as: GpsResponse.self)
        // Densified to real-recording cadence so route rendering, the
        // derived-speed path, and the relief render the way an actual
        // file does. Sparse mode strips correction: raw elevation only,
        // like most old imports.
        let sparse = mode == .sparse
        var points: [GpsPoint] = []
        let anchors = gps.gpsPoints
        for i in 0..<anchors.count {
            let a = anchors[i]
            func lerped(_ f: Double, _ b: GpsPoint) -> GpsPoint {
                GpsPoint(
                    latitude: zip(a.latitude, b.latitude).map { $0 + f * ($1 - $0) },
                    longitude: zip(a.longitude, b.longitude).map { $0 + f * ($1 - $0) },
                    elevationM: zip(a.elevationM, b.elevationM).map { $0 + f * ($1 - $0) },
                    elevationCorrectedM: sparse
                        ? nil
                        : zip(a.elevationCorrectedM, b.elevationCorrectedM)
                            .map { $0 + f * ($1 - $0) },
                    distanceM: zip(a.distanceM, b.distanceM).map { $0 + f * ($1 - $0) },
                    timestamp: zip(a.timestamp, b.timestamp).map { $0 + f * ($1 - $0) }
                )
            }
            if i + 1 < anchors.count {
                let b = anchors[i + 1]
                let steps = (mode == .finished || mode == .sparse) ? 10 : 100
                for step in 0..<steps { points.append(lerped(Double(step) / Double(steps), b)) }
            } else {
                points.append(lerped(0, a))
            }
        }
        guard mode != .finished && mode != .sparse else { return GpsResponse(gpsPoints: points) }
        let encoder = JSONEncoder()
        encoder.keyEncodingStrategy = .convertToSnakeCase
        var rows = try! JSONSerialization.jsonObject(with: encoder.encode(points)) as! [[String: Any]]
        let lastDistance = points.last!.distanceM!
        for i in rows.indices {
            let distance = points[i].distanceM!
            if mode == .noMap || distance < 200 || distance > lastDistance - 200 ||
                (mode == .hiddenMiddle && distance > 12000 && distance < 17000) {
                for key in ["latitude", "longitude", "elevation_m", "elevation_corrected_m", "timestamp"] {
                    rows[i][key] = NSNull()
                }
                rows[i]["redacted"] = true
            }
        }
        let decoder = JSONDecoder()
        decoder.keyDecodingStrategy = .convertFromSnakeCase
        // Same decode failure behavior as the production optional GPS load.
        return try? decoder.decode(GpsResponse.self, from: JSONSerialization.data(withJSONObject: ["gps_points": rows]))
    }

    private func zip<A, B>(_ a: A?, _ b: B?) -> (A, B)? {
        guard let a, let b else { return nil }
        return (a, b)
    }

    private var fixtureClimbs: [ClimbPattern] {
        mode != .finished
            ? []
            : decode(Self.patternsJSON, as: PatternsResponse.self).patterns?.climbPatterns ?? []
    }

    private var fixtureStreams: [RideStreamKind: RideStreamResponse] {
        guard mode == .finished else { return [:] }
        return [
            .power: decode(Self.powerJSON, as: RideStreamResponse.self),
            .heartRate: decode(Self.heartRateJSON, as: RideStreamResponse.self),
            .cadence: decode(Self.cadenceJSON, as: RideStreamResponse.self),
            .speed: decode(Self.speedJSON, as: RideStreamResponse.self),
        ]
    }

    private func decode<T: Decodable>(_ json: String, as type: T.Type) -> T {
        let decoder = JSONDecoder()
        decoder.keyDecodingStrategy = .convertFromSnakeCase
        return try! decoder.decode(T.self, from: Data(json.utf8))
    }

    private static let fixtureJSON = #"""
    {
      "ride": {
        "id": "99999999-9999-4999-8999-999999999999",
        "title": "Barren Hill before lunch",
        "description": "Quiet roads, a steady north wind, and one clean run up the hill.",
        "status": "completed",
        "started_at": "2026-08-14T11:05:00Z",
        "distance_m": 28485.2,
        "elevation_m": 460.0,
        "elevation_corrected_m": 472.4,
        "duration_s": 4382,
        "training_metrics": {
          "engine_version": 2, "elapsed_s": 4382, "recording_s": 4210, "moving_s": 4020,
          "avg_speed_mps": 7.1, "max_speed_mps": 12.0, "avg_power_w": 211, "max_power_w": 700,
          "avg_hr_bpm": 148, "max_hr_bpm": 180, "avg_cadence_rpm": 87, "max_cadence_rpm": 102, "load": 82, "load_estimate": true,
          "threshold": {"value":265,"estimate":true,"basis":"threshold_cp_3_7_15_v1","range":[252,278]},
          "estimates": {"load":{"value":82,"estimate":true,"basis":"power"}},
          "power_zone_s": [700,1000,1500,600,150,50,20],
          "power_zone_ranges_w": [[0,145],[146,198],[199,238],[239,278],[279,318],[319,397],[398,null]],
          "power_curve_s": [5,60,180,420,900,3600],
          "power_curve_w": [700,450,350,293,270,230]
        },
        "avg_power_w": 211,
        "normalized_power_w": 236,
        "avg_hr_bpm": 148,
        "tss": 82,
        "perceived_exertion": 7,
        "weather_temp_c": 24.5,
        "weather_wind_mps": 3.6,
        "weather_source": "device",
        "power_balance": {"left_pct": 48.4, "right_pct": 51.6, "sample_count": 4210},
        "laps": [
          {"started_at_ms": 1786705500000, "total_timer_s": 1180.0, "total_distance_m": 9100.0, "avg_power_w": 232},
          {"started_at_ms": 1786706680000, "total_timer_s": 1425.0, "total_distance_m": 9600.0, "avg_power_w": 245},
          {"started_at_ms": 1786708105000, "total_timer_s": 1710.0, "total_distance_m": 9785.0, "avg_power_w": 214}
        ],
        "route_preview": {
          "source": "fixture",
          "segments": [[
            {"x": -75.236, "y": 40.032},
            {"x": -75.245, "y": 40.045},
            {"x": -75.258, "y": 40.052},
            {"x": -75.271, "y": 40.046},
            {"x": -75.278, "y": 40.058}
          ]],
          "place_label": "Philadelphia, PA"
        },
        "is_owner": true,
        "privacy": {
          "visibility": "public",
          "can_view": true,
          "is_owner": true,
          "map_visibility": "hide_start_end",
          "map_hide_start_m": 200,
          "map_hide_end_m": 200,
          "reason": "owner"
        },
        "media": [
          {
            "id": "11111111-1111-4111-8111-111111111111",
            "ride_id": "99999999-9999-4999-8999-999999999999",
            "url": "br-fixture://warm/cover",
            "file_name": "barren-hill.jpg",
            "mime_type": "image/jpeg",
            "size_bytes": 182400,
            "sort_order": 0,
            "role": "cover",
            "moderation_state": "visible"
          },
          {
            "id": "22222222-2222-4222-8222-222222222222",
            "ride_id": "99999999-9999-4999-8999-999999999999",
            "url": "br-fixture://cool/road",
            "file_name": "river-road.jpg",
            "mime_type": "image/jpeg",
            "size_bytes": 164200,
            "sort_order": 1,
            "role": "photo",
            "moderation_state": "visible"
          }
        ]
      },
      "status": {
        "ride_id": "99999999-9999-4999-8999-999999999999",
        "status": "completed"
      }
    }
    """#

    private static let gpsJSON = #"""
    {
      "gps_points": [
        {"latitude":40.032,"longitude":-75.236,"elevation_m":34,"elevation_corrected_m":35,"distance_m":0,"timestamp":1786705500},
        {"latitude":40.039,"longitude":-75.241,"elevation_m":39,"elevation_corrected_m":40,"distance_m":4200,"timestamp":1786706230},
        {"latitude":40.045,"longitude":-75.245,"elevation_m":53,"elevation_corrected_m":55,"distance_m":8200,"timestamp":1786706960},
        {"latitude":40.052,"longitude":-75.258,"elevation_m":91,"elevation_corrected_m":94,"distance_m":12600,"timestamp":1786707690},
        {"latitude":40.046,"longitude":-75.271,"elevation_m":46,"elevation_corrected_m":48,"distance_m":17200,"timestamp":1786708420},
        {"latitude":40.058,"longitude":-75.278,"elevation_m":112,"elevation_corrected_m":116,"distance_m":22100,"timestamp":1786709150},
        {"latitude":40.032,"longitude":-75.236,"elevation_m":36,"elevation_corrected_m":37,"distance_m":28485,"timestamp":1786709880}
      ]
    }
    """#

    private static let patternsJSON = #"""
    {
      "ride_id":"99999999-9999-4999-8999-999999999999",
      "patterns":{"climb_patterns":[
        {
          "id":"pattern-barren","name":"Barren Hill Road","climb_id":"climb-barren",
          "distance_m":1240,"avg_gradient_pct":6.7,"duration_s":2275,"start_offset_s":900,"end_offset_s":3175,
          "vault_match":{"vault_climb_id":"climb-barren","your_time":2275,"is_pr":true,"your_best_time":2275,"your_rank":2}
        },
        {
          "id":"pattern-river","name":"River Road Rise","climb_id":"climb-river",
          "distance_m":680,"avg_gradient_pct":4.2,"duration_s":188,"start_offset_s":3300,"end_offset_s":3488,
          "vault_match":{"vault_climb_id":"climb-river","your_time":188,"is_pr":false,"your_best_time":181,"your_rank":8}
        }
      ]}
    }
    """#

    private static let powerJSON = streamJSON(
        type: "power",
        values: [172, 205, 246, 219, 288, 251, 198, 232, 266, 211]
    )
    private static let heartRateJSON = streamJSON(
        type: "heart_rate",
        values: [119, 132, 144, 148, 162, 158, 149, 153, 165, 148]
    )
    private static let cadenceJSON = streamJSON(
        type: "cadence",
        values: [82, 87, 91, 89, 78, 84, 92, 88, 80, 86]
    )
    private static let speedJSON = streamJSON(
        type: "speed",
        values: [7.1, 8.4, 9.2, 7.8, 5.6, 6.4, 10.1, 9.4, 6.1, 8.0]
    )

    private static func streamJSON(type: String, values: [Double]) -> String {
        let timestamps = (0..<values.count).map { index in
            "\"2026-08-14T\(String(format: "%02d", 11 + (index * 8) / 60)):\(String(format: "%02d", (index * 8) % 60)):00Z\""
        }.joined(separator: ",")
        let valuesJSON = values.map { String($0) }.joined(separator: ",")
        let average = values.reduce(0, +) / Double(values.count)
        return """
        {"id":"stream-\(type)","ride_id":"99999999-9999-4999-8999-999999999999","stream_type":"\(type)","timestamps":[\(timestamps)],"values":[\(valuesJSON)],"sample_count":\(values.count),"min_value":\(values.min()!),"max_value":\(values.max()!),"avg_value":\(average),"redacted":false}
        """
    }
}
#endif
