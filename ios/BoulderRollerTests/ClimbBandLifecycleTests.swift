import XCTest
@testable import BoulderRoller

final class ClimbBandLifecycleTests: XCTestCase {
    private let start = Date(timeIntervalSince1970: 1_700_000_000)

    func testWallOutAndBackRequiresExitResetAndRecordsTwoForwardAscents() {
        var lifecycle = LiveClimbBandLifecycle()

        lifecycle.observe(sample(second: 0, progress: 0, distanceM: 10))
        XCTAssertNil(lifecycle.active, "Direction is not established by one entry fix")
        lifecycle.observe(sample(second: 1, progress: 0.1, distanceM: 10))
        XCTAssertEqual(lifecycle.active?.progress, 0.1)
        lifecycle.observe(sample(second: 5, progress: 0.6, distanceM: 10))

        let firstFinish = lifecycle.observe(
            sample(second: 10, progress: 1, distanceM: 10)
        )
        XCTAssertEqual(
            firstFinish,
            .finished(
                LocalBandAscent(
                    climbID: "wall",
                    startedAt: time(0),
                    finishedAt: time(10)
                )
            )
        )
        XCTAssertEqual(lifecycle.completedAscents.count, 1)
        XCTAssertEqual(lifecycle.trackedClimbID, "wall", "Finish remains locked until exit")
        XCTAssertNil(lifecycle.active)

        // The true repeat shape descends the same ordered centerline. Finish
        // stays locked until five fixes are more than 60 m from the existing
        // finish endpoint; there is no artificial lateral corridor detour.
        XCTAssertNil(lifecycle.observe(sample(second: 11, progress: 1, distanceM: 10)))
        lifecycle.observe(sample(second: 12, progress: 0.8, distanceM: 10))
        lifecycle.observe(sample(second: 13, progress: 0.6, distanceM: 10))
        lifecycle.observe(sample(second: 14, progress: 0.35, distanceM: 10))
        lifecycle.observe(sample(second: 15, progress: 0.3, distanceM: 10))
        lifecycle.observe(sample(second: 16, progress: 0.2, distanceM: 10))
        lifecycle.observe(sample(second: 17, progress: 0.1, distanceM: 10))
        XCTAssertEqual(lifecycle.completedAscents.count, 1)
        XCTAssertEqual(lifecycle.trackedClimbID, "wall")
        lifecycle.observe(sample(second: 18, progress: 0, distanceM: 10))
        XCTAssertEqual(lifecycle.trackedClimbID, "wall")
        XCTAssertNil(lifecycle.active)

        lifecycle.observe(sample(second: 19, progress: 0.1, distanceM: 10))
        lifecycle.observe(sample(second: 25, progress: 0.7, distanceM: 10))
        let secondFinish = lifecycle.observe(
            sample(second: 29, progress: 1, distanceM: 10)
        )

        XCTAssertEqual(lifecycle.completedAscents.count, 2)
        XCTAssertEqual(
            secondFinish,
            .finished(
                LocalBandAscent(
                    climbID: "wall",
                    startedAt: time(18),
                    finishedAt: time(29)
                )
            )
        )
        XCTAssertEqual(lifecycle.completedAscents.map(\.startedAt), [time(0), time(18)])
        XCTAssertEqual(lifecycle.completedAscents.map(\.durationS), [10, 11])
    }

    func testReverseAndPartialPathsDoNotFinish() {
        var lifecycle = LiveClimbBandLifecycle()

        // Reverse traversal reaches the early entry region while descending.
        lifecycle.observe(sample(second: 0, progress: 0.2, distanceM: 20))
        lifecycle.observe(sample(second: 1, progress: 0.1, distanceM: 20))
        lifecycle.observe(sample(second: 2, progress: 0, distanceM: 20))
        XCTAssertNil(lifecycle.active)
        XCTAssertTrue(lifecycle.completedAscents.isEmpty)

        releaseTrack(&lifecycle, startingAt: 3)

        // A direction-valid partial pass that exits before the endpoint is
        // retained as no local ascent.
        lifecycle.observe(sample(second: 10, progress: 0, distanceM: 20))
        lifecycle.observe(sample(second: 11, progress: 0.2, distanceM: 20))
        lifecycle.observe(sample(second: 12, progress: 0.8, distanceM: 20))
        releaseTrack(&lifecycle, startingAt: 13)
        XCTAssertTrue(lifecycle.completedAscents.isEmpty)
    }

    func testOneFixProgressWobbleStaysActiveButSustainedUTurnInvalidates() {
        var wobble = LiveClimbBandLifecycle()
        wobble.observe(sample(second: 0, progress: 0, distanceM: 20))
        wobble.observe(sample(second: 1, progress: 0.2, distanceM: 20))
        wobble.observe(sample(second: 2, progress: 0.5, distanceM: 20))

        wobble.observe(sample(second: 3, progress: 0.49, distanceM: 20))
        XCTAssertEqual(wobble.active?.progress, 0.5)
        wobble.observe(sample(second: 4, progress: 0.51, distanceM: 20))
        XCTAssertEqual(wobble.active?.progress, 0.51)
        XCTAssertNotNil(wobble.observe(sample(second: 8, progress: 1, distanceM: 20)))
        XCTAssertEqual(wobble.completedAscents.count, 1)

        var uTurn = LiveClimbBandLifecycle()
        uTurn.observe(sample(second: 10, progress: 0, distanceM: 20))
        uTurn.observe(sample(second: 11, progress: 0.2, distanceM: 20))
        uTurn.observe(sample(second: 12, progress: 0.7, distanceM: 20))
        uTurn.observe(sample(second: 13, progress: 0.5, distanceM: 20))
        XCTAssertNotNil(uTurn.active)
        uTurn.observe(sample(second: 14, progress: 0.4, distanceM: 20))
        XCTAssertNil(uTurn.active)
        uTurn.observe(sample(second: 15, progress: 1, distanceM: 20))
        XCTAssertTrue(uTurn.completedAscents.isEmpty)
    }

    func testExactEntryAndExitToleranceHysteresisDoesNotFlicker() {
        var lifecycle = LiveClimbBandLifecycle()

        lifecycle.observe(sample(second: 0, progress: 0, distanceM: 35))
        XCTAssertEqual(lifecycle.trackedClimbID, "wall")
        XCTAssertNil(lifecycle.active)
        lifecycle.observe(sample(second: 1, progress: 0.1, distanceM: 35))
        XCTAssertNotNil(lifecycle.active)

        lifecycle.observe(sample(second: 2, progress: 0.2, distanceM: 60))
        lifecycle.observe(sample(second: 3, progress: 0.3, distanceM: 60.1))
        lifecycle.observe(sample(second: 4, progress: 0.4, distanceM: 60))
        XCTAssertNotNil(lifecycle.active)

        for second in 5...8 {
            lifecycle.observe(
                sample(second: TimeInterval(second), progress: 0.4, distanceM: 60.1)
            )
        }
        XCTAssertNotNil(lifecycle.active)
        lifecycle.observe(sample(second: 9, progress: 0.4, distanceM: 60.1))
        XCTAssertNil(lifecycle.trackedClimbID)
        XCTAssertNil(lifecycle.active)

        lifecycle.observe(sample(second: 10, progress: 0, distanceM: 35.1))
        XCTAssertNil(lifecycle.trackedClimbID)
    }

    func testSuccessfulCanonReplacementRetiresOnlyUnavailableBandAndPreservesCompletedAscents() {
        var lifecycle = LiveClimbBandLifecycle()
        var projectionCursor = LiveClimbBandProjectionCursor()

        lifecycle.observe(sample(second: 0, progress: 0, distanceM: 10))
        lifecycle.observe(sample(second: 1, progress: 0.2, distanceM: 10))
        XCTAssertNotNil(
            lifecycle.observe(sample(second: 5, progress: 1, distanceM: 10))
        )
        for offset in 0..<5 {
            lifecycle.observe(
                sample(
                    second: TimeInterval(10 + offset),
                    progress: 0,
                    distanceM: 10,
                    distanceFromFinishM: 61
                )
            )
        }
        lifecycle.observe(sample(second: 15, progress: 0.2, distanceM: 10))
        XCTAssertEqual(lifecycle.completedAscents.count, 1)
        XCTAssertEqual(lifecycle.active?.climbID, "wall")
        projectionCursor.record(87)

        let retired = projectionCursor.applySuccessfulCanonReplacement(
            availableClimbIDs: ["replacement"],
            lifecycle: &lifecycle
        )

        XCTAssertTrue(retired)
        XCTAssertEqual(projectionCursor.lastNearIndex, 0)
        XCTAssertNil(lifecycle.trackedClimbID)
        XCTAssertNil(lifecycle.active)
        XCTAssertEqual(
            lifecycle.completedAscents.count,
            1,
            "A canon refresh retires only live local-band state"
        )

        var retained = LiveClimbBandLifecycle()
        var retainedCursor = LiveClimbBandProjectionCursor()
        retained.observe(sample(second: 20, progress: 0, distanceM: 10))
        retained.observe(sample(second: 21, progress: 0.2, distanceM: 10))
        retainedCursor.record(143)
        XCTAssertFalse(
            retainedCursor.applySuccessfulCanonReplacement(
                availableClimbIDs: ["wall", "other"],
                lifecycle: &retained
            )
        )
        XCTAssertEqual(
            retainedCursor.lastNearIndex,
            0,
            "Every successful replacement restarts projection search"
        )
        XCTAssertEqual(retained.active?.climbID, "wall")

        retainedCursor.record(55)
        XCTAssertTrue(
            retainedCursor.applySuccessfulCanonReplacement(
                availableClimbIDs: [],
                lifecycle: &retained
            )
        )
        XCTAssertEqual(retainedCursor.lastNearIndex, 0)
        XCTAssertNil(retained.trackedClimbID)
        XCTAssertNil(retained.active)
    }

    private func releaseTrack(
        _ lifecycle: inout LiveClimbBandLifecycle,
        startingAt second: Int
    ) {
        for offset in 0..<5 {
            lifecycle.observe(
                sample(
                    second: TimeInterval(second + offset),
                    progress: 0,
                    distanceM: 61
                )
            )
        }
        XCTAssertNil(lifecycle.trackedClimbID)
    }

    private func sample(
        second: TimeInterval,
        progress: Double,
        distanceM: Double,
        distanceFromFinishM: Double? = nil
    ) -> LiveClimbBandSample {
        LiveClimbBandSample(
            climbID: "wall",
            progress: progress,
            distanceFromCenterlineM: distanceM,
            distanceFromFinishM: distanceFromFinishM ?? abs(1 - progress) * 100,
            capturedAt: time(second)
        )
    }

    private func time(_ seconds: TimeInterval) -> Date {
        start.addingTimeInterval(seconds)
    }
}
