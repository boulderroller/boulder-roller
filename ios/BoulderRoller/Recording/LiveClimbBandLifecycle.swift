import Foundation

/// Local recording-band policy only. These tolerances control when the live
/// UI appears and retires; they do not adjudicate a D11 canon traversal.
struct LiveClimbBandPolicy: Equatable {
    var entryToleranceM: Double = 35
    var exitToleranceM: Double = 60
    var maximumEntryProgress: Double = 0.25
    var requiredExitFixes: Int = 5
}

struct LiveClimbBandSample: Equatable {
    let climbID: String
    /// Normalized progress on the canon response's existing ordered centerline.
    let progress: Double
    let distanceFromCenterlineM: Double
    /// Straight-line distance from the existing ordered centerline's final
    /// vertex. This lets a completed out-and-back retire while descending on
    /// the centerline; it does not move or reinterpret the canon finish gate.
    let distanceFromFinishM: Double
    let capturedAt: Date
}

struct LiveClimbBandActiveState: Equatable {
    let climbID: String
    let startedAt: Date
    let capturedAt: Date
    let progress: Double
}

struct LocalBandAscent: Equatable {
    let climbID: String
    let startedAt: Date
    let finishedAt: Date

    var durationS: TimeInterval {
        max(0, finishedAt.timeIntervalSince(startedAt))
    }
}

enum LiveClimbBandEvent: Equatable {
    case finished(LocalBandAscent)
}

/// Pure, clock- and data-injected lifecycle used by the recording band.
/// Candidate direction, active progress, completion lockout, and exit/reset
/// are kept as constant-size state; no per-fix history is retained or copied.
struct LiveClimbBandLifecycle {
    let policy: LiveClimbBandPolicy
    private(set) var trackedClimbID: String?
    private(set) var active: LiveClimbBandActiveState?
    private(set) var completedAscents: [LocalBandAscent] = []

    private enum Phase {
        case idle
        case candidate(lastProgress: Double)
        case active(lastProgress: Double, backwardFixes: Int)
        /// A finish unlocks only after leaving the existing finish endpoint.
        case awaitingFinishExit
        /// Invalid direction requires an explicit off-centerline reset.
        case awaitingInvalidExit
    }

    private var phase: Phase = .idle
    private var enteredAt: Date?
    private var offBandFixes = 0
    /// Numerical comparison guard only, not a rider-visible distance policy.
    private static let progressEpsilon = 1e-9

    init(policy: LiveClimbBandPolicy = LiveClimbBandPolicy()) {
        self.policy = policy
    }

    @discardableResult
    mutating func observe(_ sample: LiveClimbBandSample) -> LiveClimbBandEvent? {
        let progress = min(max(sample.progress, 0), 1)
        guard
            sample.progress.isFinite,
            sample.distanceFromCenterlineM.isFinite,
            sample.distanceFromCenterlineM >= 0,
            sample.distanceFromFinishM.isFinite,
            sample.distanceFromFinishM >= 0
        else { return nil }

        guard let trackedClimbID else {
            beginCandidateIfEligible(sample, progress: progress)
            return nil
        }

        guard trackedClimbID == sample.climbID else { return nil }
        switch phase {
        case .awaitingFinishExit:
            handleExit(
                distanceM: sample.distanceFromFinishM,
                sample: sample,
                progress: progress
            )
            return nil
        case .awaitingInvalidExit:
            handleExit(
                distanceM: sample.distanceFromCenterlineM,
                sample: sample,
                progress: progress
            )
            return nil
        case .idle, .candidate, .active:
            break
        }

        if sample.distanceFromCenterlineM > policy.exitToleranceM {
            handleExit(
                distanceM: sample.distanceFromCenterlineM,
                sample: sample,
                progress: progress
            )
            return nil
        }
        offBandFixes = 0

        switch phase {
        case .idle:
            // trackedClimbID and idle are restored together by releaseTrack.
            releaseTrack()
        case .candidate(let lastProgress):
            if isMeaningfullyBehind(progress, lastProgress) {
                // A descending rider may be returning to the start for a
                // repeat. Keep lowering the candidate anchor; the band still
                // remains hidden until progress turns strictly forward.
                enteredAt = sample.capturedAt
                phase = .candidate(lastProgress: progress)
                return nil
            }
            guard isMeaningfullyAhead(progress, lastProgress) else { return nil }
            phase = .active(lastProgress: progress, backwardFixes: 0)
            updateActive(with: sample, progress: progress)
            if progress >= 1 { return finish(with: sample) }
        case .active(let lastProgress, let backwardFixes):
            if isMeaningfullyBehind(progress, lastProgress) {
                if backwardFixes == 0 {
                    // One nearest-vertex regression is ordinary projection
                    // wobble. Hold the prior high-water progress; a second
                    // consecutive regression is sustained reverse evidence.
                    phase = .active(lastProgress: lastProgress, backwardFixes: 1)
                    updateActive(with: sample, progress: lastProgress)
                } else {
                    invalidateUntilExit()
                }
                return nil
            }
            let monotonicProgress = max(progress, lastProgress)
            phase = .active(lastProgress: monotonicProgress, backwardFixes: 0)
            updateActive(with: sample, progress: monotonicProgress)
            if monotonicProgress >= 1 { return finish(with: sample) }
        case .awaitingFinishExit, .awaitingInvalidExit:
            return nil
        }
        return nil
    }

    mutating func reset() {
        releaseTrack()
        completedAscents.removeAll(keepingCapacity: true)
    }

    /// Reconciles local band state after a successful canon-track replacement.
    /// Returns true when the previously tracked climb is no longer available.
    @discardableResult
    mutating func reconcileAvailableClimbIDs(
        _ availableClimbIDs: Set<String>
    ) -> Bool {
        guard
            let trackedClimbID,
            !availableClimbIDs.contains(trackedClimbID)
        else { return false }
        // A successful replacement retires only the now-unavailable live
        // lifecycle. Per-ascent session evidence remains append-only.
        releaseTrack()
        return true
    }

    private func isMeaningfullyAhead(_ progress: Double, _ prior: Double) -> Bool {
        progress > prior + Self.progressEpsilon
    }

    private func isMeaningfullyBehind(_ progress: Double, _ prior: Double) -> Bool {
        progress + Self.progressEpsilon < prior
    }

    private mutating func updateActive(
        with sample: LiveClimbBandSample,
        progress: Double
    ) {
        active = LiveClimbBandActiveState(
            climbID: sample.climbID,
            startedAt: enteredAt ?? sample.capturedAt,
            capturedAt: sample.capturedAt,
            progress: progress
        )
    }

    private mutating func finish(
        with sample: LiveClimbBandSample
    ) -> LiveClimbBandEvent {
        let ascent = LocalBandAscent(
            climbID: sample.climbID,
            startedAt: enteredAt ?? sample.capturedAt,
            finishedAt: sample.capturedAt
        )
        completedAscents.append(ascent)
        active = nil
        phase = .awaitingFinishExit
        offBandFixes = 0
        return .finished(ascent)
    }

    private mutating func invalidateUntilExit() {
        active = nil
        phase = .awaitingInvalidExit
        offBandFixes = 0
    }

    private mutating func beginCandidateIfEligible(
        _ sample: LiveClimbBandSample,
        progress: Double
    ) {
        guard
            sample.distanceFromCenterlineM <= policy.entryToleranceM,
            progress <= policy.maximumEntryProgress
        else { return }
        trackedClimbID = sample.climbID
        enteredAt = sample.capturedAt
        offBandFixes = 0
        phase = .candidate(lastProgress: progress)
        active = nil
    }

    private mutating func handleExit(
        distanceM: Double,
        sample: LiveClimbBandSample,
        progress: Double
    ) {
        guard distanceM > policy.exitToleranceM else {
            offBandFixes = 0
            return
        }
        offBandFixes += 1
        guard offBandFixes >= policy.requiredExitFixes else { return }
        releaseTrack()
        // The boundary-confirming fix may also be the turnaround at the
        // ordered start. Reset happens first; only then can it arm a repeat.
        beginCandidateIfEligible(sample, progress: progress)
    }

    private mutating func releaseTrack() {
        trackedClimbID = nil
        active = nil
        phase = .idle
        enteredAt = nil
        offBandFixes = 0
    }
}

/// Constant-size nearest-point cursor coupled to successful canon replacement
/// reconciliation. Production and deterministic tests exercise the same seam.
struct LiveClimbBandProjectionCursor {
    private(set) var lastNearIndex = 0

    mutating func record(_ nearIndex: Int) {
        lastNearIndex = max(0, nearIndex)
    }

    @discardableResult
    mutating func applySuccessfulCanonReplacement(
        availableClimbIDs: Set<String>,
        lifecycle: inout LiveClimbBandLifecycle
    ) -> Bool {
        // Even a surviving ID may now have a shorter or differently sampled
        // centerline, so every successful replacement restarts projection.
        lastNearIndex = 0
        return lifecycle.reconcileAvailableClimbIDs(availableClimbIDs)
    }

    mutating func reset() {
        lastNearIndex = 0
    }
}
