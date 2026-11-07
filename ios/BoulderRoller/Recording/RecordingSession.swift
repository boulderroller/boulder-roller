import Foundation

/// One recorded track point (1 Hz nominal). Sensor fields are present only
/// when a paired sensor testified at capture—never synthesized.
struct RecordedSample: Codable, Equatable, Sendable {
    let time: Date
    let latitude: Double
    let longitude: Double
    let elevationM: Double?
    let speedMps: Double?
    var hrBpm: Int?
    var cadenceRpm: Int?
    var powerW: Int?
    var elevationSource: ElevationSource? = nil
    var elevationConfidence: ElevationConfidence? = nil
    var rawGPSAltitudeM: Double? = nil
    var relativeBarometerM: Double? = nil
    /// True when no observed edge connects this sample to the prior one.
    var startsNewSegment = false
    var horizontalAccuracyM: Double? = nil
    var courseDegrees: Double? = nil
    /// The identified device whose notification supplied `powerW`. Recorded
    /// so source switches are visible in the file, never silent.
    var powerSourceID: UUID? = nil
}

enum RecordingSessionState: String, Codable, Equatable, Sendable {
    case idle
    case recording
    case autoPaused
    case manuallyPaused
    case ended

    /// The exact control grammar consumed by RecordingView. Auto-pause is a
    /// physical state and deliberately has no manual Resume action.
    var controlMode: RecordingControlMode {
        switch self {
        case .recording: return .pause
        case .autoPaused: return .endOnly
        case .manuallyPaused: return .endAndResume
        case .idle, .ended: return .unavailable
        }
    }
}

enum RecordingControlMode: Equatable, Sendable {
    case unavailable
    case pause
    case endOnly
    case endAndResume
}

struct RecordingSessionFix: Codable, Equatable, Sendable {
    let gps: GPSObservation
    let gpsAltitudeM: Double?
    let gpsVerticalAccuracyM: Double?
    let relativeBarometerM: Double?
    let barometerTimestamp: Date?
    let heartRateBpm: Int?
    let cadenceRpm: Int?
    let powerObservation: PowerObservation?
    /// When the strap/crank last testified. Bounds the recorded hold windows
    /// (SensorStreamPolicy) at the sample's capture time. Optional so fixes
    /// journaled before this policy still decode; their values replay
    /// exactly as they were originally recorded.
    var heartRateAt: Date? = nil
    var cadenceAt: Date? = nil
}

enum RecordingSessionIngestOutcome: Equatable, Sendable {
    case ignored
    case rejected
    case recorded
    case autoPaused
    case autoResumed
}

/// Pure, clock-injected recording core used by RecordingModel and the focused
/// session tests. System managers supply observations; this type owns every
/// state transition and every value that can enter a RecordedSample.
struct RecordingSession {
    private(set) var state: RecordingSessionState = .idle
    private(set) var samples: [RecordedSample] = []
    private(set) var startedAt: Date?
    private(set) var elapsedS: TimeInterval = 0
    private(set) var distanceM: Double = 0
    private(set) var elevationGainM: Double?
    private(set) var speedMps: Double = 0
    private(set) var power3sW: Int?
    private(set) var power10sW: Int?

    private var lastResumedMonotonicS: TimeInterval?
    private var elapsedBeforePause: TimeInterval = 0
    private var gpsPipeline = GPSTruthPipeline()
    private var elevationPipeline = ElevationTruthPipeline()
    private var elevationGain = ElevationGainAccumulator()
    private var distanceAccumulator = FilteredDistanceAccumulator()
    private var powerWindows = PowerWindowAccumulator()
    private var autoPause = AutoPauseController()
    private var lastRecordedPowerTimestamp: Date?
    private var lastRecordedPowerSourceID: UUID?
    private var powerEvidenceBoundaryAt: Date?

    var controlMode: RecordingControlMode { state.controlMode }

    var projection: RecordingSessionProjection {
        RecordingSessionProjection(
            state: state,
            startedAt: startedAt,
            elapsedS: elapsedS,
            distanceM: distanceM,
            elevationGainM: elevationGainM,
            speedMps: speedMps,
            power3sW: power3sW,
            power10sW: power10sW,
            sampleCount: samples.count,
            lastSample: samples.last
        )
    }

    mutating func start(at now: Date, monotonicNowS: TimeInterval? = nil) {
        guard state == .idle else { return }
        state = .recording
        startedAt = now
        lastResumedMonotonicS = monotonicNowS ?? now.timeIntervalSince1970
        powerEvidenceBoundaryAt = now
        elapsedS = 0
    }

    @discardableResult
    mutating func manualPause(at now: Date, monotonicNowS: TimeInterval? = nil) -> Bool {
        guard state == .recording else { return false }
        elapsedBeforePause = currentElapsed(
            monotonicNowS: monotonicNowS ?? now.timeIntervalSince1970
        )
        elapsedS = elapsedBeforePause
        lastResumedMonotonicS = nil
        state = .manuallyPaused
        autoPause.manualPause()
        gpsPipeline.requireSegmentBreak()
        return true
    }

    @discardableResult
    mutating func manualResume(at now: Date, monotonicNowS: TimeInterval? = nil) -> Bool {
        guard state == .manuallyPaused else { return false }
        autoPause.manualResume()
        let monotonic = monotonicNowS ?? now.timeIntervalSince1970
        lastResumedMonotonicS = monotonic
        powerEvidenceBoundaryAt = now
        powerWindows.reset()
        power3sW = nil
        power10sW = nil
        state = .recording
        gpsPipeline.requireSegmentBreak()
        elapsedS = currentElapsed(monotonicNowS: monotonic)
        return true
    }

    mutating func end(at now: Date, monotonicNowS: TimeInterval? = nil) -> [RecordedSample] {
        elapsedS = currentElapsed(
            monotonicNowS: monotonicNowS ?? now.timeIntervalSince1970
        )
        state = .ended
        lastResumedMonotonicS = nil
        return samples
    }

    mutating func tick(
        at now: Date,
        monotonicNowS: TimeInterval? = nil,
        powerObservation: PowerObservation?
    ) {
        if state == .recording {
            elapsedS = currentElapsed(
                monotonicNowS: monotonicNowS ?? now.timeIntervalSince1970
            )
        }
        refreshPower(observation: powerObservation, at: now)
    }

    @discardableResult
    mutating func ingest(
        _ fix: RecordingSessionFix,
        wallNow: Date,
        monotonicNowS: TimeInterval? = nil
    ) -> RecordingSessionIngestOutcome {
        let monotonic = monotonicNowS ?? wallNow.timeIntervalSince1970
        guard state != .idle, state != .ended else { return .ignored }
        refreshPower(observation: fix.powerObservation, at: wallNow)
        guard state != .manuallyPaused else { return .ignored }

        guard let accepted = gpsPipeline.ingest(fix.gps) else {
            // A rejected or absent fix is not continuous physical evidence.
            autoPause.resetContinuity()
            return .rejected
        }
        speedMps = accepted.filteredSpeedMps ?? 0

        switch autoPause.observe(
            speedMps: accepted.filteredSpeedMps,
            at: fix.gps.timestamp,
            startsNewSegment: accepted.startsNewSegment
        ) {
        case .autoPaused:
            elapsedBeforePause = currentElapsed(monotonicNowS: monotonic)
            elapsedS = elapsedBeforePause
            lastResumedMonotonicS = nil
            state = .autoPaused
            return .autoPaused
        case .autoResumed:
            lastResumedMonotonicS = monotonic
            powerEvidenceBoundaryAt = wallNow
            powerWindows.reset()
            power3sW = nil
            power10sW = nil
            state = .recording
            // The fixes used to establish physical resume are evidence of the
            // transition, not a route edge. The next recorded point must start
            // a new GPX segment.
            gpsPipeline.requireSegmentBreak()
            elapsedS = currentElapsed(monotonicNowS: monotonic)
            return .autoResumed
        case .none:
            break
        }
        guard state == .recording else { return .ignored }

        distanceM = distanceAccumulator.ingest(accepted)
        let elevation = elevationPipeline.ingest(
            ElevationObservation(
                timestamp: fix.gps.timestamp,
                gpsAltitudeM: fix.gpsAltitudeM,
                gpsVerticalAccuracyM: fix.gpsVerticalAccuracyM,
                relativeBarometerM: fix.relativeBarometerM,
                barometerTimestamp: fix.barometerTimestamp
            )
        )
        elevationGainM = elevationGain.ingest(
            elevation,
            startsNewSegment: accepted.startsNewSegment
                || elevation?.beginsNewEvidenceSegment == true
        )

        let recordedPower = powerForRecordedSample(
            fix.powerObservation,
            captureTime: fix.gps.timestamp,
            wallNow: wallNow
        )
        samples.append(
            RecordedSample(
                time: fix.gps.timestamp,
                latitude: fix.gps.latitude,
                longitude: fix.gps.longitude,
                elevationM: elevation?.elevationM,
                speedMps: fix.gps.speedMps,
                hrBpm: heldChannelValue(
                    fix.heartRateBpm,
                    testifiedAt: fix.heartRateAt,
                    captureTime: fix.gps.timestamp,
                    holdMaxS: SensorStreamPolicy.heartRateHoldMaxS
                ),
                cadenceRpm: heldChannelValue(
                    fix.cadenceRpm,
                    testifiedAt: fix.cadenceAt,
                    captureTime: fix.gps.timestamp,
                    holdMaxS: SensorStreamPolicy.cadenceHoldMaxS
                ),
                powerW: recordedPower?.watts,
                elevationSource: elevation?.source,
                elevationConfidence: elevation?.confidence,
                rawGPSAltitudeM: fix.gpsAltitudeM,
                relativeBarometerM: fix.relativeBarometerM,
                startsNewSegment: accepted.startsNewSegment,
                horizontalAccuracyM: fix.gps.horizontalAccuracyM,
                courseDegrees: accepted.filteredCourseDegrees,
                powerSourceID: recordedPower?.sourceID
            )
        )
        return .recorded
    }

    /// Bounded hold (SensorStreamPolicy): a slow channel's value may appear
    /// on a recorded sample only while its testimony is no older than the
    /// policy window at the sample's capture time. Fixes journaled before
    /// testimony timestamps existed replay exactly as originally recorded.
    private func heldChannelValue(
        _ value: Int?,
        testifiedAt: Date?,
        captureTime: Date,
        holdMaxS: TimeInterval
    ) -> Int? {
        guard let value else { return nil }
        guard let testifiedAt else { return value }
        guard captureTime.timeIntervalSince(testifiedAt) <= holdMaxS else { return nil }
        return value
    }

    private func currentElapsed(monotonicNowS: TimeInterval) -> TimeInterval {
        guard let lastResumedMonotonicS else { return elapsedBeforePause }
        return elapsedBeforePause + max(0, monotonicNowS - lastResumedMonotonicS)
    }

    private mutating func refreshPower(
        observation: PowerObservation?,
        at now: Date
    ) {
        if
            let observation,
            observation.timestamp >= (powerEvidenceBoundaryAt ?? .distantPast)
        {
            powerWindows.ingest(observation)
        }
        let snapshot = powerWindows.snapshot(at: now)
        power3sW = snapshot.threeSecondW
        power10sW = snapshot.tenSecondW
    }

    /// Power is never zero-filled and never held: one BLE notification can
    /// enter at most one recorded sample, and only within the association
    /// window (SensorStreamPolicy.powerAssociationMaxAgeS) on both the
    /// capture and delivery clocks. Two meters can legally share a
    /// timestamp, so the once-only guard keys on source and time together.
    private mutating func powerForRecordedSample(
        _ observation: PowerObservation?,
        captureTime: Date,
        wallNow: Date
    ) -> PowerObservation? {
        guard let observation else { return nil }
        let captureAge = captureTime.timeIntervalSince(observation.timestamp)
        let deliveryAge = wallNow.timeIntervalSince(observation.timestamp)
        guard
            observation.timestamp >= (powerEvidenceBoundaryAt ?? .distantPast),
            captureAge >= 0,
            captureAge <= powerWindows.policy.dropoutAgeS,
            deliveryAge >= 0,
            deliveryAge <= powerWindows.policy.dropoutAgeS,
            observation.timestamp != lastRecordedPowerTimestamp
                || observation.sourceID != lastRecordedPowerSourceID
        else { return nil }
        lastRecordedPowerTimestamp = observation.timestamp
        lastRecordedPowerSourceID = observation.sourceID
        return observation
    }
}

/// Scalar, observation-safe projection of the recorder's single owned sample
/// buffer. RecordingModel never mirrors the full history on each fix.
struct RecordingSessionProjection: Equatable, Sendable {
    let state: RecordingSessionState
    let startedAt: Date?
    let elapsedS: TimeInterval
    let distanceM: Double
    let elevationGainM: Double?
    let speedMps: Double
    let power3sW: Int?
    let power10sW: Int?
    let sampleCount: Int
    let lastSample: RecordedSample?
}
