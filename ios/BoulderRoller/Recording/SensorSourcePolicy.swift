import Foundation

/// Recorded-stream and live-display truth policy for BLE sensor channels.
/// One place, one set of numbers: the recorded GPX reflects policy, never
/// callback-timing accidents (bead boulderroller-v2-odmi6.11).
enum SensorStreamPolicy {
    /// Heart rate moves slowly; a strap that last testified within this
    /// window may hold its value in live display and recorded samples.
    /// Beyond it the channel is absent — never carried forward.
    static let heartRateHoldMaxS: TimeInterval = 5
    /// Crank cadence: the same bounded hold as heart rate.
    static let cadenceHoldMaxS: TimeInterval = 5
    /// Power varies too fast to hold. A recorded sample may carry the
    /// latest observation only while it is at most this old, each BLE
    /// notification is recorded at most once, and a dropout is recorded as
    /// absence — power is never zero-filled and never held.
    static let powerAssociationMaxAgeS: TimeInterval = 3
    /// Zero-offset calibration: how long the meter has to answer the
    /// control-point write before the flow reports a truthful timeout.
    static let calibrationTimeoutS: TimeInterval = 10
}

/// One timed testimony from one identified device.
struct TimedSensorReading: Equatable, Sendable {
    let value: Int
    let timestamp: Date
    let sourceID: UUID
}

/// Deterministic source-of-truth choice when several connected devices
/// provide the same channel. The rider's explicit selection wins while that
/// device is connected and providing; otherwise the earliest-paired
/// connected provider (persisted pairing order is the persisted priority).
/// Never an average, never whichever callback happened last.
enum SensorSourceResolver {
    static func resolve(
        explicitSelection: UUID?,
        connectedProvidersInPairedOrder providers: [UUID]
    ) -> UUID? {
        if let explicitSelection, providers.contains(explicitSelection) {
            return explicitSelection
        }
        return providers.first
    }
}

/// The rider's explicit per-channel source picks, persisted across launches.
struct SensorSourceSelection: Codable, Equatable, Sendable {
    var heartRate: UUID?
    var power: UUID?
    var cadence: UUID?

    subscript(kind: Sensor.Kind) -> UUID? {
        get {
            switch kind {
            case .heartRate: return heartRate
            case .power: return power
            case .cadence: return cadence
            }
        }
        set {
            switch kind {
            case .heartRate: heartRate = newValue
            case .power: power = newValue
            case .cadence: cadence = newValue
            }
        }
    }

    mutating func removeDevice(_ id: UUID) {
        if heartRate == id { heartRate = nil }
        if power == id { power = nil }
        if cadence == id { cadence = nil }
    }

    static let storeKey = "br_sensor_source_selection_v1"

    static func load(defaults: UserDefaults = .standard) -> SensorSourceSelection {
        guard
            let data = defaults.data(forKey: storeKey),
            let decoded = try? JSONDecoder().decode(SensorSourceSelection.self, from: data)
        else { return SensorSourceSelection() }
        return decoded
    }

    func save(defaults: UserDefaults = .standard) {
        guard let data = try? JSONEncoder().encode(self) else { return }
        defaults.set(data, forKey: Self.storeKey)
    }
}
