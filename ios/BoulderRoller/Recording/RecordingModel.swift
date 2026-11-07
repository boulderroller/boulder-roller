import CoreLocation
import CoreMotion
import Foundation
import Observation

enum RecordingCustodyOperation: Equatable, Sendable {
    case start
    case pause
    case resume
    case capture
    case suspend
}

enum RecordingCustodyFailurePolicy {
    static func clears(
        failed: RecordingCustodyOperation?,
        completed: RecordingCustodyOperation
    ) -> Bool {
        failed == completed
    }

    static func retainedFailure(
        current: RecordingCustodyOperation?,
        incoming: RecordingCustodyOperation
    ) -> RecordingCustodyOperation {
        if current == .suspend, incoming != .suspend {
            return .suspend
        }
        if incoming == .capture,
           let current,
           current != .capture
        {
            return current
        }
        return incoming
    }
}

enum RecordingControlTransition: Equatable, Sendable {
    case pause
    case resume
    case end
}

enum RecordingControlTransitionPolicy {
    static func begin(
        _ requested: RecordingControlTransition,
        current: inout RecordingControlTransition?
    ) -> Bool {
        guard current == nil else { return false }
        current = requested
        return true
    }

    static func complete(
        _ completed: RecordingControlTransition,
        current: inout RecordingControlTransition?
    ) {
        guard current == completed else { return }
        current = nil
    }
}

enum RecordingAuthorizationCustodyPolicy {
    static func requiresSuspension(
        status: CLAuthorizationStatus,
        state: RecordingSessionState,
        isStarting: Bool = false
    ) -> Bool {
        guard status == .denied || status == .restricted else { return false }
        return isStarting || (state != .idle && state != .ended)
    }
}

struct RecordingCaptureSensorSnapshot: Equatable, Sendable {
    let heartRateBpm: Int?
    let cadenceRpm: Int?
    let powerObservation: PowerObservation?
    /// Testimony times for the slow channels; production always sets them
    /// (SensorStreamPolicy bounds the recorded hold at capture time).
    var heartRateAt: Date? = nil
    var cadenceAt: Date? = nil
}

private struct RecordingCaptureAttempt {
    let sequence: UInt64
    let flowGeneration: UUID
    let location: CLLocation
    let fix: RecordingSessionFix
    let wallNow: Date
    let monotonicNowS: TimeInterval
}

struct RecordingControlIntent: Equatable {
    let transition: RecordingControlTransition
    let wallNow: Date
    let monotonicNowS: TimeInterval
    let captureCutoff: UInt64
}

struct RecordingSuspendIntent: Equatable {
    fileprivate let id = UUID()
    let wallNow: Date
    let monotonicNowS: TimeInterval
    let captureCutoff: UInt64
}

private struct RecordingSuspensionCompletion {
    let id: UUID
    let intent: RecordingSuspendIntent
    let task: Task<Void, Error>
}

/// Surface 13's engine: CoreLocation in, samples out. Pause keeps the GPS
/// warm but accumulates nothing (Apple Workout pattern). Sensor values are
/// merged per-sample from whatever the sensor room has live.
@MainActor
@Observable
final class RecordingModel: NSObject {
    typealias State = RecordingSessionState

    private(set) var state: State = .idle
    private(set) var authorization: CLAuthorizationStatus = .notDetermined
    /// True once at least one fix has arrived — before that the screen shows
    /// the waiting state rather than zeros pretending to be a ride.
    private(set) var hasFix = false
    private(set) var custodyErrorMessage: String?
    /// One-way handoff state once authorization loss has durably suspended the
    /// active ride. The production view must install recovery before leaving.
    private(set) var recoveryExitRequired = false

    private(set) var startedAt: Date?
    private(set) var elapsedS: TimeInterval = 0
    private(set) var distanceM: Double = 0
    private(set) var elevationGainM: Double?
    private(set) var speedMps: Double = 0
    private(set) var power3sW: Int?
    private(set) var power10sW: Int?
    /// Accepted-sample count mirrored from the session projection. Zero at
    /// End is the truth boundary for the empty-ride acknowledgment (bead
    /// c6l2l item 5): every admitted capture through the End cutoff syncs a
    /// projection before finalization returns.
    private(set) var sampleCount = 0
    private(set) var location: CLLocation?

    /// Fed every accepted fix while recording (the climb band's input).
    var onFix: ((CLLocation) -> Void)?
    /// Internal observation seam for deterministic callback-overlap tests.
    /// Production leaves this nil; it does not alter capture decisions.
    var onCaptureCallback: ((CLLocation) -> Void)?
    /// Internal observation seam proving a delegate drain reached an existing
    /// capture owner. Production leaves this nil and retains the same flow.
    var onCaptureDrainDeferred: (() -> Void)?
    /// Internal observation seam for a control result that has returned from
    /// the serialized runtime but has not necessarily been projected yet.
    var onControlProjectionReady: ((RecordingControlTransition) -> Void)?

    private let user: User
    private let owner: RecordingOwner
    @ObservationIgnored private let runtime: RideRecordingRuntime
    @ObservationIgnored private let authorizationStatusOverride: CLAuthorizationStatus?
    @ObservationIgnored private let locationHardwareEnabled: Bool
    @ObservationIgnored private let wallNow: @Sendable () -> Date
    @ObservationIgnored private let monotonicNow: @Sendable () -> TimeInterval
    @ObservationIgnored private let captureSensorSnapshot: () -> RecordingCaptureSensorSnapshot
    @ObservationIgnored private let beforeCaptureProjectionApply: @Sendable () async -> Void
    @ObservationIgnored private let beforeCaptureFailureApply: @Sendable () async -> Void
    @ObservationIgnored private let beforeControlProjectionApply: @Sendable () async -> Void
    private let manager = CLLocationManager()
    private var timer: Timer?
    private let altimeter = CMAltimeter()
    private var latestBarometer: (relativeAltitudeM: Double, timestamp: Date)?
    private var isStarting = false
    private var ownerSurfaceActive = true
    private var startTask: Task<Void, Never>?
    private var generation = UUID()
    private var captureFlowGeneration = UUID()
    private var failedOperation: RecordingCustodyOperation?
    private(set) var controlTransitionInFlight: RecordingControlTransition?
    private var pendingControlIntent: RecordingControlIntent?
    private var endCompletionInFlight = false
    private var pendingSuspendAndLeaveIntent: RecordingSuspendIntent?
    private var pendingAuthorizationSuspendIntent: RecordingSuspendIntent?
    @ObservationIgnored private var suspensionCompletion: RecordingSuspensionCompletion?
    private var authorizationSuspensionRequired = false
    private(set) var custodySuspensionCompleted = false
    /// Testable logical boundary around the real Core Location/barometer/timer
    /// lifecycle. It changes only when the production hardware boundary would
    /// start or stop, even when tests deliberately disable physical managers.
    private(set) var captureHardwareActive = false
    private(set) var captureHardwareStartCount = 0
    private var pendingCaptureAttempt: RecordingCaptureAttempt?
    private var captureRetryInFlight = false
    private var captureIngestionInFlight = false
    private var captureIngestionWaiters: [CheckedContinuation<Void, Never>] = []
    private var captureRecoveryWaiters: [CheckedContinuation<Bool, Never>] = []
    private var queuedCaptureAttempts: [RecordingCaptureAttempt] = []
    private var queuedCaptureReadIndex = 0
    private var nextCaptureSequence: UInt64 = 1
    private var lastCompletedCaptureSequence: UInt64 = 0

    init(
        user: User,
        runtime: RideRecordingRuntime = .shared,
        authorizationStatus: CLAuthorizationStatus? = nil,
        locationHardwareEnabled: Bool = true,
        wallNow: @escaping @Sendable () -> Date = { .now },
        monotonicNow: @escaping @Sendable () -> TimeInterval = {
            ProcessInfo.processInfo.systemUptime
        },
        captureSensorSnapshot: (() -> RecordingCaptureSensorSnapshot)? = nil,
        beforeCaptureProjectionApply: @escaping @Sendable () async -> Void = {},
        beforeCaptureFailureApply: @escaping @Sendable () async -> Void = {},
        beforeControlProjectionApply: @escaping @Sendable () async -> Void = {}
    ) {
        self.user = user
        self.owner = RecordingOwner(user: user)
        self.runtime = runtime
        self.authorizationStatusOverride = authorizationStatus
        self.locationHardwareEnabled = locationHardwareEnabled
        self.wallNow = wallNow
        self.monotonicNow = monotonicNow
        self.captureSensorSnapshot = captureSensorSnapshot ?? {
            // Resolved-source readings only (SensorSourceResolver): one
            // deterministic device per channel, with testimony times so the
            // recorded stream can enforce its hold windows.
            let sensors = SensorManager.shared
            return RecordingCaptureSensorSnapshot(
                heartRateBpm: sensors.liveHeartRateReading?.value,
                cadenceRpm: sensors.liveCadenceReading?.value,
                powerObservation: sensors.livePowerObservation,
                heartRateAt: sensors.liveHeartRateReading?.timestamp,
                cadenceAt: sensors.liveCadenceReading?.timestamp
            )
        }
        self.beforeCaptureProjectionApply = beforeCaptureProjectionApply
        self.beforeCaptureFailureApply = beforeCaptureFailureApply
        self.beforeControlProjectionApply = beforeControlProjectionApply
        super.init()
        if locationHardwareEnabled {
            manager.delegate = self
        }
        manager.desiredAccuracy = kCLLocationAccuracyBestForNavigation
        manager.activityType = .fitness
        manager.distanceFilter = kCLDistanceFilterNone
        authorization = authorizationStatus ?? manager.authorizationStatus
    }

    var authorizationDenied: Bool {
        authorization == .denied || authorization == .restricted
    }

    var controlMode: RecordingControlMode {
        recoveryExitRequired ? .unavailable : state.controlMode
    }

    func requestAndStart() {
        guard ownerSurfaceActive else { return }
        let status = authorizationStatusOverride ?? manager.authorizationStatus
        switch status {
        case .notDetermined:
            manager.requestWhenInUseAuthorization()
        case .authorizedWhenInUse, .authorizedAlways:
            start()
        default:
            authorization = status
        }
    }

    private func start() {
        guard ownerSurfaceActive,
              state == .idle,
              !isStarting,
              !recoveryExitRequired,
              !authorizationSuspensionRequired,
              pendingControlIntent?.transition != .end
        else { return }
        isStarting = true
        let expectedGeneration = generation
        startTask = Task { @MainActor [weak self] in
            guard let self else { return }
            defer { self.isStarting = false }
            do {
                let projection = try await runtime.start(user: user, at: wallNow())
                guard generation == expectedGeneration,
                      ownerSurfaceActive,
                      !recoveryExitRequired,
                      !authorizationSuspensionRequired
                else { return }
                sync(projection, completing: .start)
                startHardware()
            } catch {
                stopHardware()
                guard ownerSurfaceActive else { return }
                // Diagnostic identity of the real failure (rider-facing
                // message stays generic; the console keeps the cause).
                print("[Custody] start failed: \(error)")
                presentCustodyError(for: .start)
            }
        }
    }

    func pause() {
        guard let intent = beginControlIntent(.pause) else { return }
        performNonterminalControl(intent)
    }

    func resume() {
        // A Resume tap expresses rider intent and therefore applies only to a
        // manually paused session. Physical auto-pause leaves through sourced
        // sustained-motion evidence in RecordingSession.
        guard let intent = beginControlIntent(.resume) else { return }
        performNonterminalControl(intent)
    }

    /// Finalize and persist the exact GPX/stamp before the existing upload job
    /// can exist. This method performs no network request.
    func end() async throws -> FinalizedRecording? {
        let intent: RecordingControlIntent
        if let pendingControlIntent {
            guard pendingControlIntent.transition == .end else { return nil }
            intent = pendingControlIntent
        } else {
            guard let created = reserveEndIntent() else { return nil }
            intent = created
        }
        return try await completeEnd(intent)
    }

    /// Synchronous rider-control boundary used by RecordingView. It freezes
    /// the End wall/monotonic time and callback cutoff before returning to the
    /// run loop; asynchronous finalization can only consume this exact intent.
    func reserveEndIntent() -> RecordingControlIntent? {
        guard let intent = beginControlIntent(.end) else { return nil }
        // End owns the terminal cutoff immediately. Core Location can still
        // deliver a queued callback, but admission is now closed before the
        // button action returns and no later hardware testimony can enter.
        stopHardware()
        return intent
    }

    func completeEnd(_ intent: RecordingControlIntent) async throws -> FinalizedRecording? {
        guard pendingControlIntent == intent,
              intent.transition == .end,
              !endCompletionInFlight
        else { return nil }
        if controlTransitionInFlight == nil {
            guard RecordingControlTransitionPolicy.begin(
                .end,
                current: &controlTransitionInFlight
            ) else { return nil }
        } else {
            guard controlTransitionInFlight == .end else { return nil }
        }
        endCompletionInFlight = true
        defer {
            endCompletionInFlight = false
            RecordingControlTransitionPolicy.complete(
                .end,
                current: &controlTransitionInFlight
            )
        }
        if let startTask {
            await startTask.value
            self.startTask = nil
        }
        stopHardware()
        do {
            try await prepareCaptures(for: intent)
            guard pendingControlIntent == intent else {
                throw CancellationError()
            }
            let result = try await runtime.stop(
                at: intent.wallNow,
                monotonicNowS: intent.monotonicNowS,
                owner: owner
            )
            guard pendingControlIntent == intent,
                  ownerSurfaceActive,
                  !authorizationSuspensionRequired,
                  !recoveryExitRequired
            else { throw CancellationError() }
            onControlProjectionReady?(.end)
            pendingControlIntent = nil
            queuedCaptureAttempts.removeAll()
            queuedCaptureReadIndex = 0
            state = .ended
            return result
        } catch {
            throw error
        }
    }

    private func beginControlIntent(
        _ transition: RecordingControlTransition
    ) -> RecordingControlIntent? {
        guard pendingControlIntent == nil,
              ownerSurfaceActive,
              !authorizationSuspensionRequired,
              !recoveryExitRequired,
              RecordingControlTransitionPolicy.begin(
                transition,
                current: &controlTransitionInFlight
              )
        else { return nil }
        let intent = RecordingControlIntent(
            transition: transition,
            wallNow: wallNow(),
            monotonicNowS: monotonicNow(),
            captureCutoff: nextCaptureSequence - 1
        )
        pendingControlIntent = intent
        return intent
    }

    private func retryPendingControl(_ transition: RecordingControlTransition) {
        guard let intent = pendingControlIntent,
              intent.transition == transition,
              RecordingControlTransitionPolicy.begin(
                transition,
                current: &controlTransitionInFlight
              )
        else { return }
        performNonterminalControl(intent)
    }

    private func performNonterminalControl(_ intent: RecordingControlIntent) {
        Task { @MainActor [weak self] in
            guard let self else { return }
            do {
                try await prepareCaptures(for: intent)
                guard pendingControlIntent == intent else {
                    throw CancellationError()
                }
                let projection: RecordingSessionProjection
                switch intent.transition {
                case .pause:
                    projection = try await runtime.manualPause(
                        at: intent.wallNow,
                        monotonicNowS: intent.monotonicNowS,
                        owner: owner
                    )
                case .resume:
                    projection = try await runtime.manualResume(
                        at: intent.wallNow,
                        monotonicNowS: intent.monotonicNowS,
                        owner: owner
                    )
                case .end:
                    throw LiveRideCustodyError.corruptEvidence
                }
                await beforeControlProjectionApply()
                guard pendingControlIntent == intent,
                      ownerSurfaceActive,
                      !authorizationSuspensionRequired,
                      !recoveryExitRequired
                else { return }
                onControlProjectionReady?(intent.transition)
                sync(
                    projection,
                    completing: intent.transition == .pause ? .pause : .resume
                )
                pendingControlIntent = nil
                RecordingControlTransitionPolicy.complete(
                    intent.transition,
                    current: &controlTransitionInFlight
                )
                startHardware()
                await drainQueuedCaptureAttempts()
            } catch {
                stopHardware()
                RecordingControlTransitionPolicy.complete(
                    intent.transition,
                    current: &controlTransitionInFlight
                )
                guard pendingControlIntent == intent,
                      !authorizationSuspensionRequired,
                      !recoveryExitRequired
                else { return }
                presentCustodyError(for: intent.transition == .pause ? .pause : .resume)
            }
        }
    }

    private func prepareCaptures(for intent: RecordingControlIntent) async throws {
        // A timer projection has no capture sequence, but it is still older
        // than the rider's control intent when already in flight.
        await waitForCaptureIngestionToFinish()
        while lastCompletedCaptureSequence < intent.captureCutoff {
            guard pendingControlIntent == intent,
                  !authorizationSuspensionRequired,
                  !recoveryExitRequired
            else { throw CancellationError() }

            await waitForCaptureIngestionToFinish()
            if pendingCaptureAttempt != nil {
                guard await waitForCaptureRecovery() else {
                    throw CancellationError()
                }
                continue
            }

            guard lastCompletedCaptureSequence < intent.captureCutoff else { break }
            await drainQueuedCaptureAttempts(through: intent.captureCutoff)
        }
    }

    /// Leave an unavailable recorder without deleting or finalizing evidence.
    /// Runtime deactivation durably suspends any owner-bound active session;
    /// if startup never created one, it is a safe no-op.
    func suspendAndLeave() async throws {
        guard let intent = reserveSuspendAndLeaveIntent() else {
            throw LiveRideCustodyError.corruptEvidence
        }
        try await completeSuspendAndLeave(intent)
    }

    /// Synchronous Cancel boundary. Production capture/control testimony is
    /// closed before this method returns, while the exact tap clocks remain
    /// available for a later durable suspend or retry.
    func reserveSuspendAndLeaveIntent() -> RecordingSuspendIntent? {
        guard ownerSurfaceActive else { return pendingSuspendAndLeaveIntent }
        if let pendingSuspendAndLeaveIntent { return pendingSuspendAndLeaveIntent }
        let intent = pendingAuthorizationSuspendIntent ?? RecordingSuspendIntent(
            wallNow: wallNow(),
            monotonicNowS: monotonicNow(),
            captureCutoff: nextCaptureSequence - 1
        )
        pendingSuspendAndLeaveIntent = intent
        ownerSurfaceActive = false
        closeControlsForSuspensionPreservingCaptures()
        stopHardware()
        return intent
    }

    func completeSuspendAndLeave(_ intent: RecordingSuspendIntent) async throws {
        guard pendingSuspendAndLeaveIntent == intent else {
            throw LiveRideCustodyError.corruptEvidence
        }
        try await awaitSuspensionCompletion(for: intent)
    }

    private func suspendForAuthorizationLoss(_ intent: RecordingSuspendIntent) async {
        stopHardware()
        closeControlsForSuspensionPreservingCaptures()
        do {
            try await awaitSuspensionCompletion(for: intent)
        } catch {
            // The shared completion owner records the retryable local error.
            // Authorization callbacks do not dismiss or reinterpret it.
        }
    }

    /// Authorization loss, Cancel, and Retry may converge on the same exact
    /// Suspend intent. Only one task may advance its capture cursor or publish
    /// its durable boundary; every concurrent caller observes that same result.
    private func awaitSuspensionCompletion(
        for intent: RecordingSuspendIntent
    ) async throws {
        guard pendingSuspendAndLeaveIntent == intent ||
                pendingAuthorizationSuspendIntent == intent
        else {
            throw LiveRideCustodyError.corruptEvidence
        }
        if custodySuspensionCompleted {
            if pendingAuthorizationSuspendIntent == intent {
                recoveryExitRequired = true
            }
            clearCustodyFailure(completing: .suspend)
            return
        }
        if let suspensionCompletion {
            guard suspensionCompletion.intent == intent else {
                throw LiveRideCustodyError.corruptEvidence
            }
            try await suspensionCompletion.task.value
            return
        }

        let completionID = UUID()
        let task = Task { @MainActor [self] in
            do {
                if let startTask {
                    await startTask.value
                    self.startTask = nil
                }
                try await persistAdmittedCapturesBeforeSuspension(
                    through: intent.captureCutoff
                )
                try await runtime.suspendActive(
                    at: intent.wallNow,
                    monotonicNowS: intent.monotonicNowS,
                    owner: owner
                )
                custodySuspensionCompleted = true
                finishCaptureStateAfterSuspension()
                clearCustodyFailure(completing: .suspend)
                if pendingAuthorizationSuspendIntent == intent {
                    recoveryExitRequired = true
                }
            } catch {
                presentCustodyError(for: .suspend)
                throw error
            }
        }
        suspensionCompletion = RecordingSuspensionCompletion(
            id: completionID,
            intent: intent,
            task: task
        )

        do {
            try await task.value
            clearSuspensionCompletion(id: completionID)
        } catch {
            clearSuspensionCompletion(id: completionID)
            throw error
        }
    }

    private func clearSuspensionCompletion(id: UUID) {
        guard suspensionCompletion?.id == id else { return }
        suspensionCompletion = nil
    }

    func stopHardware() {
        captureHardwareActive = false
        generation = UUID()
        manager.stopUpdatingLocation()
        RecordingLocationHardwarePolicy.configureForIdle(manager)
        altimeter.stopRelativeAltitudeUpdates()
        timer?.invalidate()
        timer = nil
    }

    /// Invalidate every local continuation when this exact owner-bound surface
    /// leaves. Durable runtime custody remains untouched and recoverable.
    func leaveOwnerSurface() {
        let suspensionOwnsCaptureCutoff = !custodySuspensionCompleted && (
            pendingSuspendAndLeaveIntent != nil ||
                pendingAuthorizationSuspendIntent != nil ||
                suspensionCompletion != nil
        )
        ownerSurfaceActive = false
        if suspensionOwnsCaptureCutoff {
            closeControlsForSuspensionPreservingCaptures()
        } else {
            abortCaptureAndControlForExit()
        }
        stopHardware()
    }

    func presentFinalizationError() {
        custodyErrorMessage = LiveRideCustodyError.corruptEvidence.localizedDescription
    }

    func retryCustodyOperation() {
        guard ownerSurfaceActive else { return }
        let operation = failedOperation
        switch operation {
        case .start:
            requestAndStart()
        case .pause:
            retryPendingControl(.pause)
        case .resume:
            retryPendingControl(.resume)
        case .capture:
            guard !captureRetryInFlight else { return }
            captureRetryInFlight = true
            Task { @MainActor [weak self] in
                guard let self else { return }
                defer { self.captureRetryInFlight = false }
                guard authorization == .authorizedWhenInUse || authorization == .authorizedAlways,
                      ownerSurfaceActive,
                      !authorizationSuspensionRequired,
                      !recoveryExitRequired
                else { return }
                do {
                    guard let attempt = pendingCaptureAttempt else {
                        throw LiveRideCustodyError.corruptEvidence
                    }
                    let (outcome, projection) = try await runtime.retryPendingCapture(
                        expectedFix: attempt.fix,
                        wallNow: attempt.wallNow,
                        owner: owner
                    )
                    guard attempt.flowGeneration == captureFlowGeneration else {
                        throw CancellationError()
                    }
                    sync(projection, completing: .capture)
                    if outcome == .recorded {
                        onFix?(attempt.location)
                    }
                    lastCompletedCaptureSequence = max(
                        lastCompletedCaptureSequence,
                        attempt.sequence
                    )
                    pendingCaptureAttempt = nil
                    resolveCaptureRecovery(success: true)
                    if controlTransitionInFlight == nil {
                        startHardware()
                        guard captureHardwareActive else {
                            presentCustodyError(for: .capture)
                            return
                        }
                        await drainQueuedCaptureAttempts()
                    }
                } catch {
                    stopHardware()
                    guard ownerSurfaceActive,
                          !authorizationSuspensionRequired
                    else { return }
                    presentCustodyError(for: .capture)
                }
            }
        case .suspend:
            Task { @MainActor [weak self] in
                guard let self else { return }
                if authorizationSuspensionRequired {
                    guard let intent = pendingAuthorizationSuspendIntent else {
                        presentCustodyError(for: .suspend)
                        return
                    }
                    await suspendForAuthorizationLoss(intent)
                } else {
                    stopHardware()
                    do {
                        try await runtime.suspendActive(at: wallNow(), owner: owner)
                        clearCustodyFailure(completing: .suspend)
                    } catch {
                        presentCustodyError(for: .suspend)
                    }
                }
            }
        case nil:
            break
        }
    }

    func handleCaptureTick(expectedGeneration: UUID? = nil) async {
        guard state != .ended,
              ownerSurfaceActive,
              !authorizationSuspensionRequired,
              !recoveryExitRequired,
              pendingSuspendAndLeaveIntent == nil,
              pendingAuthorizationSuspendIntent == nil,
              pendingCaptureAttempt == nil,
              failedOperation == nil,
              controlTransitionInFlight == nil,
              pendingControlIntent?.transition != .end,
              !captureIngestionInFlight,
              expectedGeneration == nil || expectedGeneration == generation
        else { return }
        let expectedFlowGeneration = captureFlowGeneration
        captureIngestionInFlight = true
        var tickOwnsCaptureIngestion = true
        defer {
            if tickOwnsCaptureIngestion {
                finishCaptureIngestion(removingProcessedLocations: false)
            }
        }
        do {
            let projection = try await runtime.tick(
                at: wallNow(),
                powerObservation: SensorManager.shared.livePowerObservation,
                owner: owner
            )
            await beforeCaptureProjectionApply()
            guard expectedFlowGeneration == captureFlowGeneration,
                  ownerSurfaceActive,
                  !authorizationSuspensionRequired,
                  !recoveryExitRequired,
                  pendingSuspendAndLeaveIntent == nil,
                  pendingAuthorizationSuspendIntent == nil,
                  state != .ended,
                  pendingCaptureAttempt == nil,
                  pendingControlIntent?.transition != .end,
                  expectedGeneration == nil || expectedGeneration == generation
            else { return }
            sync(projection, completing: .capture)
            // A production delegate callback can be admitted while Tick owns
            // this boundary. Its first drain correctly defers; release Tick
            // and immediately drain that immutable callback evidence exactly
            // once without requiring another callback or rider control.
            finishCaptureIngestion(removingProcessedLocations: false)
            tickOwnsCaptureIngestion = false
            await drainQueuedCaptureAttempts()
        } catch {
            guard expectedFlowGeneration == captureFlowGeneration else { return }
            if let expectedGeneration, expectedGeneration != generation { return }
            stopHardware()
            guard !authorizationSuspensionRequired else { return }
            presentCustodyError(for: .capture)
        }
    }

    private func startHardware() {
        guard authorization == .authorizedWhenInUse || authorization == .authorizedAlways,
              ownerSurfaceActive,
              !authorizationSuspensionRequired,
              !recoveryExitRequired,
              pendingSuspendAndLeaveIntent == nil,
              pendingAuthorizationSuspendIntent == nil,
              !captureHardwareActive
        else { return }
        captureHardwareActive = true
        captureHardwareStartCount += 1
        guard locationHardwareEnabled else { return }
        RecordingLocationHardwarePolicy.configureForActiveCapture(manager)
        manager.startUpdatingLocation()
        startBarometer()
        guard timer == nil else { return }
        let timerGeneration = generation
        timer = Timer.scheduledTimer(withTimeInterval: 0.5, repeats: true) {
            [weak self] _ in
            Task { @MainActor [weak self] in
                await self?.handleCaptureTick(expectedGeneration: timerGeneration)
            }
        }
    }

    private func presentCustodyError(for operation: RecordingCustodyOperation) {
        failedOperation = RecordingCustodyFailurePolicy.retainedFailure(
            current: failedOperation,
            incoming: operation
        )
        custodyErrorMessage = LiveRideCustodyError.corruptEvidence.localizedDescription
    }

    private func startBarometer() {
        guard CMAltimeter.isRelativeAltitudeAvailable() else { return }
        altimeter.startRelativeAltitudeUpdates(to: .main) { [weak self] data, _ in
            guard let data else { return }
            let relativeAltitudeM = data.relativeAltitude.doubleValue
            guard relativeAltitudeM.isFinite else { return }
            Task { @MainActor [weak self] in
                self?.latestBarometer = (relativeAltitudeM, .now)
            }
        }
    }

    private func makeCaptureAttempt(_ location: CLLocation) -> RecordingCaptureAttempt {
        let sensor = captureSensorSnapshot()
        let sequence = nextCaptureSequence
        nextCaptureSequence += 1
        return RecordingCaptureAttempt(
            sequence: sequence,
            flowGeneration: captureFlowGeneration,
            location: location,
            fix: RecordingSessionFix(
                gps: GPSObservation(location: location),
                gpsAltitudeM: location.altitude.isFinite ? location.altitude : nil,
                gpsVerticalAccuracyM: (
                    location.verticalAccuracy.isFinite && location.verticalAccuracy >= 0
                ) ? location.verticalAccuracy : nil,
                relativeBarometerM: latestBarometer?.relativeAltitudeM,
                barometerTimestamp: latestBarometer?.timestamp,
                heartRateBpm: sensor.heartRateBpm,
                cadenceRpm: sensor.cadenceRpm,
                powerObservation: sensor.powerObservation,
                heartRateAt: sensor.heartRateAt,
                cadenceAt: sensor.cadenceAt
            ),
            wallNow: wallNow(),
            monotonicNowS: monotonicNow()
        )
    }

    private func ingest(_ attempt: RecordingCaptureAttempt) async -> Bool {
        guard ownerSurfaceActive,
              pendingCaptureAttempt == nil,
              failedOperation != .capture
        else { return false }
        location = attempt.location
        hasFix = true
        do {
            let (outcome, projection) = try await runtime.ingest(
                attempt.fix,
                wallNow: attempt.wallNow,
                monotonicNowS: attempt.monotonicNowS,
                owner: owner
            )
            await beforeCaptureProjectionApply()
            guard attempt.flowGeneration == captureFlowGeneration,
                  ownerSurfaceActive,
                  !authorizationSuspensionRequired,
                  !recoveryExitRequired
            else { return false }
            sync(projection, completing: .capture)
            if outcome == .recorded { onFix?(attempt.location) }
            lastCompletedCaptureSequence = max(
                lastCompletedCaptureSequence,
                attempt.sequence
            )
            return true
        } catch {
            await beforeCaptureFailureApply()
            guard attempt.flowGeneration == captureFlowGeneration,
                  ownerSurfaceActive,
                  !authorizationSuspensionRequired,
                  !recoveryExitRequired
            else { return false }
            if pendingCaptureAttempt == nil { pendingCaptureAttempt = attempt }
            stopHardware()
            presentCustodyError(for: .capture)
            return false
        }
    }

    /// Freeze callback order, timing, and sensor testimony synchronously at
    /// the production Core Location boundary, before a later rider control can
    /// establish its capture cutoff.
    @discardableResult
    private func admitLocations(_ locations: [CLLocation]) -> Bool {
        guard !authorizationSuspensionRequired,
              ownerSurfaceActive,
              !recoveryExitRequired,
              state != .ended,
              pendingControlIntent?.transition != .end
        else { return false }
        for location in locations {
            onCaptureCallback?(location)
            queuedCaptureAttempts.append(makeCaptureAttempt(location))
        }
        return !locations.isEmpty
    }

    func handleLocations(_ locations: [CLLocation]) async {
        guard admitLocations(locations) else { return }
        await drainQueuedCaptureAttempts()
    }

    private func drainQueuedCaptureAttempts(through cutoff: UInt64? = nil) async {
        if captureIngestionInFlight {
            onCaptureDrainDeferred?()
            return
        }
        guard pendingSuspendAndLeaveIntent == nil,
              pendingAuthorizationSuspendIntent == nil
        else {
            onCaptureDrainDeferred?()
            return
        }
        guard pendingCaptureAttempt == nil,
              failedOperation == nil || controlTransitionInFlight != nil,
              cutoff != nil || (
                controlTransitionInFlight == nil &&
                    pendingControlIntent?.transition != .end
              )
        else { return }
        captureIngestionInFlight = true
        defer { finishCaptureIngestion(removingProcessedLocations: true) }

        while queuedCaptureReadIndex < queuedCaptureAttempts.count,
              pendingCaptureAttempt == nil,
              (failedOperation == nil || controlTransitionInFlight != nil)
        {
            let attempt = queuedCaptureAttempts[queuedCaptureReadIndex]
            if let cutoff, attempt.sequence > cutoff { break }
            if cutoff == nil,
               controlTransitionInFlight != nil || pendingControlIntent?.transition == .end
            {
                break
            }
            queuedCaptureReadIndex += 1
            guard await ingest(attempt) else { break }
        }
    }

    private func waitForCaptureIngestionToFinish() async {
        guard captureIngestionInFlight else { return }
        await withCheckedContinuation { continuation in
            captureIngestionWaiters.append(continuation)
        }
    }

    private func finishCaptureIngestion(removingProcessedLocations: Bool) {
        if removingProcessedLocations, queuedCaptureReadIndex > 0 {
            queuedCaptureAttempts.removeFirst(queuedCaptureReadIndex)
            queuedCaptureReadIndex = 0
        }
        captureIngestionInFlight = false
        let waiters = captureIngestionWaiters
        captureIngestionWaiters.removeAll()
        waiters.forEach { $0.resume() }
    }

    private func waitForCaptureRecovery() async -> Bool {
        guard pendingCaptureAttempt != nil else { return true }
        return await withCheckedContinuation { continuation in
            captureRecoveryWaiters.append(continuation)
        }
    }

    private func resolveCaptureRecovery(success: Bool) {
        let waiters = captureRecoveryWaiters
        captureRecoveryWaiters.removeAll()
        waiters.forEach { $0.resume(returning: success) }
    }

    private func abortCaptureAndControlForExit() {
        captureFlowGeneration = UUID()
        pendingCaptureAttempt = nil
        queuedCaptureAttempts.removeAll()
        queuedCaptureReadIndex = 0
        pendingControlIntent = nil
        if let transition = controlTransitionInFlight {
            RecordingControlTransitionPolicy.complete(
                transition,
                current: &controlTransitionInFlight
            )
        }
        resolveCaptureRecovery(success: false)
    }

    /// Stop all competing rider/UI control continuations while retaining the
    /// immutable CLLocation attempts admitted before a terminal Suspend
    /// cutoff. The suspension transaction owns their exact persistence now.
    private func closeControlsForSuspensionPreservingCaptures() {
        pendingControlIntent = nil
        if let transition = controlTransitionInFlight {
            RecordingControlTransitionPolicy.complete(
                transition,
                current: &controlTransitionInFlight
            )
        }
        resolveCaptureRecovery(success: false)
    }

    /// Persist every callback synchronously admitted before the suspension
    /// claimant. This path intentionally applies no live projection or onFix:
    /// the surface is terminal, while replayed custody remains authoritative.
    private func persistAdmittedCapturesBeforeSuspension(
        through cutoff: UInt64
    ) async throws {
        await waitForCaptureIngestionToFinish()

        if let pending = pendingCaptureAttempt,
           pending.sequence <= cutoff
        {
            _ = try await runtime.retryPendingCapture(
                expectedFix: pending.fix,
                wallNow: pending.wallNow,
                owner: owner
            )
            lastCompletedCaptureSequence = max(
                lastCompletedCaptureSequence,
                pending.sequence
            )
            pendingCaptureAttempt = nil
        }

        while queuedCaptureReadIndex < queuedCaptureAttempts.count {
            let attempt = queuedCaptureAttempts[queuedCaptureReadIndex]
            guard attempt.sequence <= cutoff else { break }
            _ = try await runtime.ingest(
                attempt.fix,
                wallNow: attempt.wallNow,
                monotonicNowS: attempt.monotonicNowS,
                owner: owner
            )
            queuedCaptureReadIndex += 1
            lastCompletedCaptureSequence = max(
                lastCompletedCaptureSequence,
                attempt.sequence
            )
        }
    }

    private func finishCaptureStateAfterSuspension() {
        captureFlowGeneration = UUID()
        pendingCaptureAttempt = nil
        queuedCaptureAttempts.removeAll()
        queuedCaptureReadIndex = 0
        resolveCaptureRecovery(success: false)
    }

    private func sync(
        _ projection: RecordingSessionProjection,
        completing operation: RecordingCustodyOperation
    ) {
        clearCustodyFailure(completing: operation)
        state = projection.state
        startedAt = projection.startedAt
        elapsedS = projection.elapsedS
        distanceM = projection.distanceM
        elevationGainM = projection.elevationGainM
        speedMps = projection.speedMps
        power3sW = projection.power3sW
        power10sW = projection.power10sW
        sampleCount = projection.sampleCount
    }

    private func clearCustodyFailure(completing operation: RecordingCustodyOperation) {
        if RecordingCustodyFailurePolicy.clears(
            failed: failedOperation,
            completed: operation
        ) {
            failedOperation = nil
            custodyErrorMessage = nil
        }
    }

#if DEBUG
    var captureRetryPendingForTesting: Bool { pendingCaptureAttempt != nil }
    var queuedCaptureCountForTesting: Int {
        queuedCaptureAttempts.count - queuedCaptureReadIndex
    }
    var suspensionCompletionInFlightForTesting: Bool {
        suspensionCompletion != nil
    }
    var failedCustodyOperationForTesting: RecordingCustodyOperation? { failedOperation }
    func waitForStartForTesting() async { await startTask?.value }
#endif
}

extension RecordingModel: CLLocationManagerDelegate {
    nonisolated func locationManagerDidChangeAuthorization(_ manager: CLLocationManager) {
        let managerStatus = manager.authorizationStatus
        Task { @MainActor in
            let status = self.authorizationStatusOverride ?? managerStatus
            await self.handleAuthorizationChange(status)
        }
    }

    /// Production delegate seam kept internal so authorization-loss custody
    /// ordering can be proven without changing simulator permission state.
    func handleAuthorizationChange(_ status: CLAuthorizationStatus) async {
        authorization = status
        guard ownerSurfaceActive else { return }
        if status == .authorizedWhenInUse || status == .authorizedAlways {
            // A rider-owned End is already terminal and needs no location
            // permission. Restoration cannot restart hardware across it.
            guard pendingControlIntent?.transition != .end else { return }
            guard !recoveryExitRequired, !authorizationSuspensionRequired else { return }
            authorizationSuspensionRequired = false
            start()
        } else if RecordingAuthorizationCustodyPolicy.requiresSuspension(
            status: status,
            state: state,
            isStarting: isStarting
        ) {
            // First terminal claimant wins: End has already frozen its exact
            // cutoff and stopped hardware. A later permission callback may
            // update displayed authorization, but cannot replace End with a
            // shifted Suspend boundary.
            guard pendingControlIntent?.transition != .end else { return }
            authorizationSuspensionRequired = true
            let intent = pendingAuthorizationSuspendIntent ?? RecordingSuspendIntent(
                wallNow: wallNow(),
                monotonicNowS: monotonicNow(),
                captureCutoff: nextCaptureSequence - 1
            )
            pendingAuthorizationSuspendIntent = intent
            stopHardware()
            closeControlsForSuspensionPreservingCaptures()
            await suspendForAuthorizationLoss(intent)
        }
    }

    nonisolated func locationManager(_ manager: CLLocationManager, didUpdateLocations locations: [CLLocation]) {
        MainActor.assumeIsolated {
            guard self.admitLocations(locations) else { return }
            Task { @MainActor [weak self] in
                await self?.drainQueuedCaptureAttempts()
            }
        }
    }

    nonisolated func locationManager(_ manager: CLLocationManager, didFailWithError error: Error) {}
}
