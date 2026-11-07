import Foundation

struct PowerObservation: Codable, Equatable, Sendable {
    let watts: Int
    let timestamp: Date
    /// The identified device this notification came from. Optional for
    /// decode compatibility with fixes journaled before source provenance
    /// existed; production always sets it.
    var sourceID: UUID? = nil
}

struct PowerWindowSnapshot: Equatable {
    let threeSecondW: Int?
    let tenSecondW: Int?
    let sourceSampleCount: Int
}

struct PowerWindowPolicy: Equatable {
    var shortWindowS: TimeInterval = 3
    var longWindowS: TimeInterval = 10
    /// The power association window: one shared number for live windows,
    /// recorded samples, and display staleness (SensorStreamPolicy).
    var dropoutAgeS: TimeInterval = SensorStreamPolicy.powerAssociationMaxAgeS
}

/// Clocked windows over actual BLE notifications. Repeated UI/GPS polling is
/// deduplicated by source timestamp and cannot manufacture power samples.
struct PowerWindowAccumulator {
    let policy: PowerWindowPolicy
    private var samples: [PowerObservation] = []

    init(policy: PowerWindowPolicy = PowerWindowPolicy()) {
        self.policy = policy
    }

    mutating func ingest(_ observation: PowerObservation) {
        guard observation.watts >= 0 else { return }
        if let index = samples.firstIndex(where: { $0.timestamp == observation.timestamp }) {
            samples[index] = observation
        } else {
            samples.append(observation)
            samples.sort { $0.timestamp < $1.timestamp }
        }
        let retentionStart = observation.timestamp.addingTimeInterval(-policy.longWindowS)
        samples.removeAll { $0.timestamp < retentionStart }
    }

    mutating func snapshot(at now: Date) -> PowerWindowSnapshot {
        let retentionStart = now.addingTimeInterval(-policy.longWindowS)
        samples.removeAll { $0.timestamp < retentionStart }
        let eligible = samples.filter { $0.timestamp <= now }
        guard
            let newest = eligible.last,
            now.timeIntervalSince(newest.timestamp) <= policy.dropoutAgeS
        else {
            return PowerWindowSnapshot(
                threeSecondW: nil,
                tenSecondW: nil,
                sourceSampleCount: eligible.count
            )
        }
        return PowerWindowSnapshot(
            threeSecondW: average(
                eligible.filter { $0.timestamp >= now.addingTimeInterval(-policy.shortWindowS) }
            ),
            tenSecondW: average(eligible),
            sourceSampleCount: eligible.count
        )
    }

    mutating func reset() {
        samples.removeAll(keepingCapacity: true)
    }

    private func average(_ values: [PowerObservation]) -> Int? {
        guard !values.isEmpty else { return nil }
        return Int(
            (Double(values.reduce(0) { $0 + $1.watts }) / Double(values.count)).rounded()
        )
    }
}

struct FilteredDistancePolicy: Equatable {
    var minimumMovingSpeedMps: Double = 0.8
    var maximumSpeedAccuracyMps: Double = 2.5
    var minimumEvidencedDistanceM: Double = 1
}

/// Qualified sourced speed may admit the raw accepted edge. Without it, only
/// the portion outside both GPS accuracy envelopes may count; uncertainty can
/// never be amplified into the full raw edge.
struct FilteredDistanceAccumulator {
    let policy: FilteredDistancePolicy
    private(set) var valueM: Double = 0

    init(policy: FilteredDistancePolicy = FilteredDistancePolicy()) {
        self.policy = policy
    }

    @discardableResult
    mutating func ingest(_ point: AcceptedGPSPoint) -> Double {
        guard
            let edge = point.distanceFromPreviousM,
            edge.isFinite,
            edge >= 0
        else { return valueM }

        if speedIsQualified(point) {
            valueM += edge
        } else if
            let evidenced = point.evidencedDistanceFromPreviousM,
            evidenced.isFinite,
            evidenced >= policy.minimumEvidencedDistanceM
        {
            // Without independent speed evidence, the accuracy envelope is
            // the upper bound on what may be counted—not a license to add the
            // entire raw coordinate edge.
            valueM += min(edge, evidenced)
        }
        return valueM
    }

    private func speedIsQualified(_ point: AcceptedGPSPoint) -> Bool {
        if
            let speed = point.filteredSpeedMps,
            speed.isFinite,
            speed >= policy.minimumMovingSpeedMps,
            let speedAccuracy = point.observation.speedAccuracyMps,
            speedAccuracy <= policy.maximumSpeedAccuracyMps
        {
            return true
        }
        return false
    }
}

enum AutoPauseState: Equatable {
    case moving
    case autoPaused
    case manualPaused
}

enum AutoPauseTransition: Equatable {
    case none
    case autoPaused
    case autoResumed
}

struct AutoPausePolicy: Equatable {
    var enterAtOrBelowMps: Double = 0.5
    var enterDurationS: TimeInterval = 5
    var exitAtOrAboveMps: Double = 1.5
    var exitDurationS: TimeInterval = 2
}

/// Separate thresholds and sustained clocks form a neutral hysteresis band.
/// Manual pause is a different state and can only leave through manualResume.
struct AutoPauseController {
    let policy: AutoPausePolicy
    private(set) var state: AutoPauseState = .moving
    private var belowThresholdSince: Date?
    private var aboveThresholdSince: Date?

    init(policy: AutoPausePolicy = AutoPausePolicy()) {
        self.policy = policy
    }

    mutating func observe(
        speedMps: Double?,
        at timestamp: Date,
        startsNewSegment: Bool = false
    ) -> AutoPauseTransition {
        guard state != .manualPaused else { return .none }
        if startsNewSegment { resetContinuity() }
        guard let speedMps, speedMps.isFinite, speedMps >= 0 else {
            resetContinuity()
            return .none
        }

        switch state {
        case .moving:
            aboveThresholdSince = nil
            guard speedMps <= policy.enterAtOrBelowMps else {
                belowThresholdSince = nil
                return .none
            }
            if belowThresholdSince == nil { belowThresholdSince = timestamp }
            if timestamp.timeIntervalSince(belowThresholdSince!) >= policy.enterDurationS {
                state = .autoPaused
                belowThresholdSince = nil
                return .autoPaused
            }
        case .autoPaused:
            belowThresholdSince = nil
            guard speedMps >= policy.exitAtOrAboveMps else {
                aboveThresholdSince = nil
                return .none
            }
            if aboveThresholdSince == nil { aboveThresholdSince = timestamp }
            if timestamp.timeIntervalSince(aboveThresholdSince!) >= policy.exitDurationS {
                state = .moving
                aboveThresholdSince = nil
                return .autoResumed
            }
        case .manualPaused:
            return .none
        }
        return .none
    }

    mutating func manualPause() {
        state = .manualPaused
        belowThresholdSince = nil
        aboveThresholdSince = nil
    }

    mutating func manualResume() {
        state = .moving
        resetContinuity()
    }

    mutating func resetContinuity() {
        belowThresholdSince = nil
        aboveThresholdSince = nil
    }
}
