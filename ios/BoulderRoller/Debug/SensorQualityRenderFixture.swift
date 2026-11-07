#if DEBUG
import Foundation
import SwiftUI

/// Exact DEBUG-only launch modes for the sensor-quality surfaces (bead
/// boulderroller-v2-odmi6.11): the two-power-meter source picker and the
/// device room's calibration states. The simulator has no radios, so
/// SensorManager is seeded frozen (no CoreBluetooth activation) and every
/// screenshot is labeled simulated; hardware verification stays on the bead.
enum SensorQualityRenderFixtureMode: String, CaseIterable {
    case sourceConflict = "source-conflict"
    case detailCalibrate = "detail-calibrate"
    case detailCalibrated = "detail-calibrated"
    case detailTimeout = "detail-timeout"

    static let launchArgument = "-BRSensorRenderFixture"

    init?(arguments: [String]) {
        guard arguments.filter({ $0 == Self.launchArgument }).count == 1,
              let argumentIndex = arguments.firstIndex(of: Self.launchArgument),
              arguments.indices.contains(argumentIndex + 1)
        else { return nil }
        self.init(rawValue: arguments[argumentIndex + 1])
    }
}

@MainActor
enum SensorQualityRenderFixtureData {
    static let meterA = UUID(uuidString: "AAAAAAAA-0000-4000-8000-00000000000A")!
    static let meterB = UUID(uuidString: "BBBBBBBB-0000-4000-8000-00000000000B")!
    static let strap = UUID(uuidString: "CCCCCCCC-0000-4000-8000-00000000000C")!

    static func seed(mode: SensorQualityRenderFixtureMode) {
        // Names shaped like real BLE advertisements; the devices are
        // simulated (labeled as such in evidence).
        let pedalMeter = Sensor(
            id: meterA,
            name: "ASSIOMA 12894",
            kinds: [.power, .cadence],
            isConnected: true
        )
        let crankMeter = Sensor(
            id: meterB,
            name: "STAGES 4721",
            kinds: [.power, .cadence],
            isConnected: true
        )
        let heartStrap = Sensor(
            id: strap,
            name: "TICKR 8811",
            kinds: [.heartRate],
            isConnected: true
        )

        switch mode {
        case .sourceConflict:
            SensorManager.shared.debugSeedRenderFixture(
                devices: [pedalMeter, crankMeter, heartStrap],
                calibrationSupport: [meterA]
            )
        case .detailCalibrate:
            SensorManager.shared.debugSeedRenderFixture(
                devices: [pedalMeter],
                calibrationSupport: [meterA]
            )
        case .detailCalibrated:
            // States are reached by replaying the machine's real events —
            // the fixture cannot fabricate a state the flow cannot reach.
            var flow = PowerCalibrationFlow()
            _ = flow.begin()
            _ = flow.indicationsReady()
            flow.indication(Data([0x20, 0x0C, 0x01, 0xAC, 0xFE]))
            SensorManager.shared.debugSeedRenderFixture(
                devices: [pedalMeter],
                calibrationFlows: [meterA: flow],
                calibrationSupport: [meterA]
            )
        case .detailTimeout:
            var flow = PowerCalibrationFlow()
            _ = flow.begin()
            flow.timedOut()
            SensorManager.shared.debugSeedRenderFixture(
                devices: [pedalMeter],
                calibrationFlows: [meterA: flow],
                calibrationSupport: [meterA]
            )
        }
    }
}

@MainActor
struct SensorQualityRenderFixtureRoot: View {
    let mode: SensorQualityRenderFixtureMode
    @State private var session: AppSession

    init(mode: SensorQualityRenderFixtureMode) {
        self.mode = mode
        SensorQualityRenderFixtureData.seed(mode: mode)
        let session = AppSession()
        session.phase = .signedIn(
            PhysiologyRenderFixtureData.rider(id: "debug-sensor-quality")
        )
        _session = State(initialValue: session)
    }

    @ViewBuilder
    var body: some View {
        switch mode {
        case .sourceConflict:
            SensorPairingView()
                .environment(session)
        case .detailCalibrate, .detailCalibrated, .detailTimeout:
            SensorDetailView(sensorID: SensorQualityRenderFixtureData.meterA)
                .environment(session)
        }
    }
}
#endif
