import Foundation

enum ElevationSource: String, Codable, Equatable, Sendable {
    case barometerFused = "barometer_fused"
    case gps
}

enum ElevationConfidence: String, Codable, Equatable, Sendable {
    case high
    case medium
}

struct ElevationObservation: Equatable {
    let timestamp: Date
    let gpsAltitudeM: Double?
    let gpsVerticalAccuracyM: Double?
    let relativeBarometerM: Double?
    let barometerTimestamp: Date?
}

struct TrustedElevation: Equatable {
    let elevationM: Double
    let source: ElevationSource
    let confidence: ElevationConfidence
    let rawGPSAltitudeM: Double?
    let relativeBarometerM: Double?
    let beginsNewEvidenceSegment: Bool
}

struct ElevationTruthPolicy: Equatable {
    var maximumGPSVerticalAccuracyM: Double = 25
    var maximumBarometerAgeS: TimeInterval = 3
    var maximumBarometerRateMps: Double = 8
    var minimumDiscontinuityAllowanceM: Double = 12
    var maximumAnchorDisagreementM: Double = 12
    var anchorDriftFraction: Double = 0.02
}

/// Fuses pressure-relative change with an accuracy-qualified GPS anchor.
/// Pressure can change the altitude only after an observed GPS anchor exists;
/// an invalid pressure jump is discarded rather than becoming apparent gain.
struct ElevationTruthPipeline {
    let policy: ElevationTruthPolicy

    private var barometerAnchorOffsetM: Double?
    private var lastRelativeBarometerM: Double?
    private var lastBarometerTimestamp: Date?
    private var needsEvidenceSegmentBreak = false

    init(policy: ElevationTruthPolicy = ElevationTruthPolicy()) {
        self.policy = policy
    }

    mutating func ingest(_ observation: ElevationObservation) -> TrustedElevation? {
        let gpsAltitude = qualifiedGPSAltitude(observation)
        let relativeBarometer = qualifiedRelativeBarometer(observation)

        if let relativeBarometer {
            if barometerAnchorOffsetM == nil, let gpsAltitude {
                barometerAnchorOffsetM = gpsAltitude - relativeBarometer
            } else if let gpsAltitude, let anchor = barometerAnchorOffsetM {
                let observedOffset = gpsAltitude - relativeBarometer
                if abs(observedOffset - anchor) <= policy.maximumAnchorDisagreementM {
                    barometerAnchorOffsetM = anchor
                        + (observedOffset - anchor) * policy.anchorDriftFraction
                }
            }

            if let anchor = barometerAnchorOffsetM {
                return TrustedElevation(
                    elevationM: anchor + relativeBarometer,
                    source: .barometerFused,
                    confidence: .high,
                    rawGPSAltitudeM: finite(observation.gpsAltitudeM),
                    relativeBarometerM: relativeBarometer,
                    beginsNewEvidenceSegment: consumeEvidenceSegmentBreak()
                )
            }
        }

        guard let gpsAltitude else { return nil }
        return TrustedElevation(
            elevationM: gpsAltitude,
            source: .gps,
            confidence: .medium,
            rawGPSAltitudeM: gpsAltitude,
            relativeBarometerM: finite(observation.relativeBarometerM),
            beginsNewEvidenceSegment: consumeEvidenceSegmentBreak()
        )
    }

    private func qualifiedGPSAltitude(_ observation: ElevationObservation) -> Double? {
        guard
            let altitude = finite(observation.gpsAltitudeM),
            let accuracy = finite(observation.gpsVerticalAccuracyM),
            accuracy >= 0,
            accuracy <= policy.maximumGPSVerticalAccuracyM
        else { return nil }
        return altitude
    }

    private mutating func qualifiedRelativeBarometer(
        _ observation: ElevationObservation
    ) -> Double? {
        guard
            let relative = finite(observation.relativeBarometerM),
            let timestamp = observation.barometerTimestamp
        else {
            invalidateBarometerEvidence()
            return nil
        }
        guard
            abs(observation.timestamp.timeIntervalSince(timestamp))
                <= policy.maximumBarometerAgeS
        else {
            invalidateBarometerEvidence()
            return nil
        }

        if let previous = lastRelativeBarometerM, let previousTimestamp = lastBarometerTimestamp {
            let interval = timestamp.timeIntervalSince(previousTimestamp)
            if interval == 0, abs(relative - previous) <= 0.01 {
                // GPS callbacks can outnumber pressure callbacks. Reusing the
                // exact still-fresh pressure observation preserves the anchor
                // without manufacturing a new pressure sample.
                return previous
            }
            guard interval > 0 else {
                invalidateBarometerEvidence()
                return nil
            }
            let allowedChange = max(
                policy.minimumDiscontinuityAllowanceM,
                interval * policy.maximumBarometerRateMps
            )
            if abs(relative - previous) > allowedChange {
                invalidateBarometerEvidence()
                return nil
            }
        }

        lastRelativeBarometerM = relative
        lastBarometerTimestamp = timestamp
        return relative
    }

    private func finite(_ value: Double?) -> Double? {
        value.flatMap { $0.isFinite ? $0 : nil }
    }

    private mutating func consumeEvidenceSegmentBreak() -> Bool {
        defer { needsEvidenceSegmentBreak = false }
        return needsEvidenceSegmentBreak
    }

    private mutating func invalidateBarometerEvidence() {
        if barometerAnchorOffsetM != nil
            || lastRelativeBarometerM != nil
            || lastBarometerTimestamp != nil
        {
            needsEvidenceSegmentBreak = true
        }
        barometerAnchorOffsetM = nil
        lastRelativeBarometerM = nil
        lastBarometerTimestamp = nil
    }
}

/// Produces a total only after at least one confidence-qualified edge exists.
/// Segment boundaries never create an elevation edge, matching GPS truth.
struct ElevationGainAccumulator {
    private(set) var valueM: Double?
    private var lastElevationM: Double?

    @discardableResult
    mutating func ingest(
        _ elevation: TrustedElevation?,
        startsNewSegment: Bool
    ) -> Double? {
        guard let elevation else {
            lastElevationM = nil
            return valueM
        }
        if startsNewSegment || lastElevationM == nil {
            lastElevationM = elevation.elevationM
            return valueM
        }

        let delta = elevation.elevationM - lastElevationM!
        if valueM == nil { valueM = 0 }
        if delta > 2 {
            valueM! += delta
            lastElevationM = elevation.elevationM
        } else if delta < 0 {
            lastElevationM = elevation.elevationM
        }
        return valueM
    }
}
