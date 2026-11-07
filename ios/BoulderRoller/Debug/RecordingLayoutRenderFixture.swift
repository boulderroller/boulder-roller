#if DEBUG
import CoreLocation
import Foundation
import SwiftUI

/// Recording-surface render seam (bead c6l2l item 1/5 evidence). Drives the
/// production RecordingView + RecordingModel + RideRecordingRuntime with
/// synthetic Core Location fixes and sensor snapshots — no BLE hardware on a
/// simulator can produce a live power meter, so the power-hero state is
/// reachable only through this data seam. Every rendering and custody code
/// path is the production one; custody writes land in a throwaway directory.
enum RecordingLayoutRenderFixtureMode: String, CaseIterable {
    /// Power meter + HR + cadence live → POWER hero numeral.
    case power
    /// GPS only → TIME hero, truthful dashes for absent channels.
    case gpsOnly
    /// One accuracy-rejected fix: recording surface with zero accepted
    /// samples — End must show the empty-ride acknowledgment.
    case empty

    static let launchArgument = "-BRRecordingLayoutRenderFixture"

    init?(arguments: [String]) {
        guard arguments.filter({ $0 == Self.launchArgument }).count == 1,
              let index = arguments.firstIndex(of: Self.launchArgument),
              arguments.indices.contains(index + 1)
        else { return nil }
        self.init(rawValue: arguments[index + 1])
    }
}

private struct RecordingLayoutNullQueue: FirstPartyRideUploadQueuing {
    func enqueueFirstParty(
        owner: RecordingOwner,
        jobID: String,
        fileName: String,
        sourceBytes: Data,
        summary: LocalRideSummary,
        parserVersion: UInt32,
        preliminaryRideHash: String
    ) async throws -> RideUploadJob {
        throw LiveRideCustodyError.noActiveRide
    }
}

@MainActor
struct RecordingLayoutRenderFixtureRoot: View {
    let mode: RecordingLayoutRenderFixtureMode

    @State private var session: AppSession
    @State private var model: RecordingModel
    @State private var runtime: RideRecordingRuntime
    @State private var activated = false
    @State private var feeder: Task<Void, Never>?

    private static let user = RideUploadRenderFixtureData.rider
    private static let origin = CLLocationCoordinate2D(
        latitude: 40.0260, longitude: -75.2230
    )

    init(mode: RecordingLayoutRenderFixtureMode) {
        self.mode = mode
        let session = AppSession()
        session.phase = .signedIn(Self.user)
        _session = State(initialValue: session)

        let custodyRoot = FileManager.default.temporaryDirectory
            .appendingPathComponent(
                "RecordingLayoutRenderFixture-\(UUID().uuidString)",
                isDirectory: true
            )
        let key = Data(repeating: 7, count: 32)
        let runtime = RideRecordingRuntime(
            custody: FileLiveRideCustodyStore(
                rootURL: custodyRoot,
                keyLoader: { _ in key }
            ),
            uploadQueue: RecordingLayoutNullQueue()
        )
        _runtime = State(initialValue: runtime)
        let powerStart = Date()
        var powerTick = 0
        let sensorSnapshot: () -> RecordingCaptureSensorSnapshot
        switch mode {
        case .power:
            sensorSnapshot = {
                powerTick += 1
                let at = powerStart.addingTimeInterval(Double(powerTick))
                return RecordingCaptureSensorSnapshot(
                    heartRateBpm: 172,
                    cadenceRpm: 91,
                    powerObservation: PowerObservation(
                        watts: 241, timestamp: at, sourceID: UUID()
                    ),
                    heartRateAt: at,
                    cadenceAt: at
                )
            }
        case .gpsOnly, .empty:
            sensorSnapshot = {
                RecordingCaptureSensorSnapshot(
                    heartRateBpm: nil,
                    cadenceRpm: nil,
                    powerObservation: nil
                )
            }
        }
        _model = State(initialValue: RecordingModel(
            user: Self.user,
            runtime: runtime,
            authorizationStatus: .authorizedWhenInUse,
            locationHardwareEnabled: false,
            captureSensorSnapshot: sensorSnapshot
        ))
    }

    var body: some View {
        Group {
            if activated {
                RecordingView(user: Self.user, debugModel: model)
                    .environment(session)
                    .onAppear { startFeeding() }
                    .onDisappear { feeder?.cancel() }
            } else {
                Color.black.ignoresSafeArea()
            }
        }
        .task {
            // The production session activates the runtime for the signed-in
            // owner before the recorder can start; the fixture does the same.
            _ = try? await runtime.activate(user: Self.user)
            activated = true
        }
    }

    private func startFeeding() {
        guard feeder == nil else { return }
        let mode = mode
        feeder = Task { @MainActor [weak model] in
            // Let the production start boundary land first.
            try? await Task.sleep(for: .milliseconds(600))
            var second = 0
            while !Task.isCancelled {
                guard let model else { return }
                let location: CLLocation
                switch mode {
                case .empty:
                    // Accuracy-ineligible: admitted, truthfully rejected —
                    // the surface runs with zero accepted samples.
                    location = CLLocation(
                        coordinate: Self.origin,
                        altitude: 30,
                        horizontalAccuracy: 90,
                        verticalAccuracy: 12,
                        timestamp: .now
                    )
                case .power, .gpsOnly:
                    // ~8.9 m/s (20 mph) northbound, riding-shaped.
                    location = CLLocation(
                        coordinate: CLLocationCoordinate2D(
                            latitude: Self.origin.latitude + Double(second) * 8.9 / 111_111,
                            longitude: Self.origin.longitude
                        ),
                        altitude: 30 + Double(second) * 0.4,
                        horizontalAccuracy: 3,
                        verticalAccuracy: 8,
                        course: 0,
                        courseAccuracy: 5,
                        speed: 8.9,
                        speedAccuracy: 0.4,
                        timestamp: .now
                    )
                }
                await model.handleLocations([location])
                // Production's 0.5 s capture timer is hardware-gated; the
                // fixture drives the same tick boundary explicitly so the
                // elapsed clock advances between fixes.
                await model.handleCaptureTick()
                second += 1
                try? await Task.sleep(for: .seconds(1))
            }
        }
    }
}
#endif
