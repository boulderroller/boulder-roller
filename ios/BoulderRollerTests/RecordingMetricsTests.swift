import XCTest
@testable import BoulderRoller

final class RecordingMetricsTests: XCTestCase {
    private let start = Date(timeIntervalSince1970: 1_700_000_000)

    func testPowerWindowsAverageOnlySourcedSamplesAndExpireOnDropout() {
        var windows = PowerWindowAccumulator()
        windows.ingest(PowerObservation(watts: 100, timestamp: time(0)))
        windows.ingest(PowerObservation(watts: 200, timestamp: time(1)))
        windows.ingest(PowerObservation(watts: 300, timestamp: time(2)))
        windows.ingest(PowerObservation(watts: 500, timestamp: time(4)))
        // Polling the same BLE notification must not manufacture another sample.
        windows.ingest(PowerObservation(watts: 500, timestamp: time(4)))

        let live = windows.snapshot(at: time(4))
        XCTAssertEqual(live.threeSecondW, 333)
        XCTAssertEqual(live.tenSecondW, 275)
        XCTAssertEqual(live.sourceSampleCount, 4)

        let dropped = windows.snapshot(at: time(7.1))
        XCTAssertNil(dropped.threeSecondW)
        XCTAssertNil(dropped.tenSecondW)
    }

    func testDistanceCountsMovingAcceptedEdgesButNotStationaryJitterOrGaps() {
        var distance = FilteredDistanceAccumulator()

        XCTAssertEqual(distance.ingest(point(second: 0, edgeM: nil, speedMps: 0)), 0)
        XCTAssertEqual(distance.ingest(point(second: 1, edgeM: 4, speedMps: 0)), 0)
        XCTAssertEqual(distance.ingest(point(second: 2, edgeM: 10, speedMps: 5)), 10)
        XCTAssertEqual(distance.ingest(point(second: 12, edgeM: nil, speedMps: 5)), 10)
        XCTAssertEqual(
            distance.ingest(
                point(second: 13, edgeM: 4, speedMps: 5, speedAccuracyMps: 9)
            ),
            10
        )
        XCTAssertEqual(
            distance.ingest(
                point(
                    second: 14,
                    edgeM: 12,
                    speedMps: nil,
                    speedAccuracyMps: nil,
                    evidencedEdgeM: 4
                )
            ),
            14
        )
    }

    func testAutoPauseUsesSeparateSustainedEntryAndExitThresholds() {
        var controller = AutoPauseController()

        XCTAssertEqual(controller.observe(speedMps: 4, at: time(0)), .none)
        XCTAssertEqual(controller.observe(speedMps: 0.2, at: time(1)), .none)
        XCTAssertEqual(controller.observe(speedMps: 0.3, at: time(5.9)), .none)
        XCTAssertEqual(controller.observe(speedMps: 0.2, at: time(6.1)), .autoPaused)
        XCTAssertEqual(controller.state, .autoPaused)

        // The neutral band cannot flap either state.
        XCTAssertEqual(controller.observe(speedMps: 0.9, at: time(7)), .none)
        XCTAssertEqual(controller.observe(speedMps: 2, at: time(8)), .none)
        XCTAssertEqual(controller.observe(speedMps: 2.1, at: time(9.9)), .none)
        XCTAssertEqual(controller.observe(speedMps: 2, at: time(10.1)), .autoResumed)
        XCTAssertEqual(controller.state, .moving)
    }

    func testManualPauseNeverAutoResumesFromMotion() {
        var controller = AutoPauseController()
        controller.manualPause()

        XCTAssertEqual(controller.observe(speedMps: 8, at: time(20)), .none)
        XCTAssertEqual(controller.state, .manualPaused)

        controller.manualResume()
        XCTAssertEqual(controller.state, .moving)
    }

    func testLowSpeedEvidenceSeparatedByAGPSGapDoesNotAutoPause() {
        var controller = AutoPauseController()

        XCTAssertEqual(controller.observe(speedMps: 0.2, at: time(0)), .none)
        // The second observation is after a GPS outage and must not complete
        // the five-second continuity clock begun by the first observation.
        XCTAssertEqual(
            controller.observe(
                speedMps: 0.2,
                at: time(10),
                startsNewSegment: true
            ),
            .none
        )
        XCTAssertEqual(controller.state, .moving)
    }

    func testHighSpeedEvidenceSeparatedByAGPSGapDoesNotAutoResume() {
        var controller = AutoPauseController()
        XCTAssertEqual(controller.observe(speedMps: 0.2, at: time(0)), .none)
        XCTAssertEqual(controller.observe(speedMps: 0.2, at: time(5)), .autoPaused)

        XCTAssertEqual(controller.observe(speedMps: 2, at: time(6)), .none)
        // This observation follows a GPS outage and must begin a new physical
        // resume clock instead of completing the clock from second 6.
        XCTAssertEqual(
            controller.observe(
                speedMps: 2,
                at: time(20),
                startsNewSegment: true
            ),
            .none
        )
        XCTAssertEqual(controller.state, .autoPaused)
    }

    func testSpeedlessDistanceNeverAmplifiesOneMeterOfEvidenceIntoTheRawEdge() {
        var distance = FilteredDistanceAccumulator()

        XCTAssertEqual(
            distance.ingest(
                point(
                    second: 1,
                    edgeM: 81,
                    speedMps: nil,
                    speedAccuracyMps: nil,
                    evidencedEdgeM: 1
                )
            ),
            1
        )
    }

    func testIneligibleSpeedBreaksScalarContinuityBeforeAStoppedFix() throws {
        var pipeline = GPSTruthPipeline()
        var distance = FilteredDistanceAccumulator()
        var controller = AutoPauseController()
        let moving = try XCTUnwrap(
            pipeline.ingest(
                observation(
                    second: 0,
                    latitude: 40,
                    speedMps: 10,
                    speedAccuracyMps: 0.5
                )
            )
        )
        let ineligible = try XCTUnwrap(
            pipeline.ingest(
                observation(
                    second: 1,
                    latitude: 40,
                    speedMps: 10,
                    speedAccuracyMps: 9
                )
            )
        )
        let stopped = try XCTUnwrap(
            pipeline.ingest(
                observation(
                    second: 2,
                    latitude: 40.0000045,
                    speedMps: 0,
                    speedAccuracyMps: 0.5
                )
            )
        )
        let sustainedStop = try XCTUnwrap(
            pipeline.ingest(
                observation(
                    second: 7,
                    latitude: 40.0000045,
                    speedMps: 0,
                    speedAccuracyMps: 0.5
                )
            )
        )

        XCTAssertEqual(moving.filteredSpeedMps, 10)
        XCTAssertNil(ineligible.filteredSpeedMps)
        XCTAssertEqual(stopped.filteredSpeedMps, 0)
        XCTAssertEqual(distance.ingest(stopped), 0)

        XCTAssertEqual(
            controller.observe(
                speedMps: moving.filteredSpeedMps,
                at: moving.observation.timestamp,
                startsNewSegment: moving.startsNewSegment
            ),
            .none
        )
        XCTAssertEqual(
            controller.observe(
                speedMps: ineligible.filteredSpeedMps,
                at: ineligible.observation.timestamp,
                startsNewSegment: ineligible.startsNewSegment
            ),
            .none
        )
        XCTAssertEqual(
            controller.observe(
                speedMps: stopped.filteredSpeedMps,
                at: stopped.observation.timestamp,
                startsNewSegment: stopped.startsNewSegment
            ),
            .none
        )
        XCTAssertEqual(
            controller.observe(
                speedMps: sustainedStop.filteredSpeedMps,
                at: sustainedStop.observation.timestamp,
                startsNewSegment: sustainedStop.startsNewSegment
            ),
            .autoPaused
        )
    }

    func testMissingAndQualityIneligibleSpeedRestartAutoPauseContinuity() throws {
        var pipeline = GPSTruthPipeline()
        var controller = AutoPauseController()

        let first = try XCTUnwrap(
            pipeline.ingest(
                observation(second: 0, latitude: 40, speedMps: 0.2, speedAccuracyMps: 0.5)
            )
        )
        XCTAssertEqual(
            controller.observe(
                speedMps: first.filteredSpeedMps,
                at: first.observation.timestamp,
                startsNewSegment: first.startsNewSegment
            ),
            .none
        )

        let ineligible = try XCTUnwrap(
            pipeline.ingest(
                observation(second: 4, latitude: 40, speedMps: 0.2, speedAccuracyMps: 9)
            )
        )
        XCTAssertNil(ineligible.filteredSpeedMps)
        XCTAssertEqual(
            controller.observe(
                speedMps: ineligible.filteredSpeedMps,
                at: ineligible.observation.timestamp,
                startsNewSegment: ineligible.startsNewSegment
            ),
            .none
        )

        XCTAssertEqual(controller.observe(speedMps: nil, at: time(4.5)), .none)
        XCTAssertEqual(controller.observe(speedMps: 0.2, at: time(5)), .none)
        XCTAssertEqual(controller.observe(speedMps: 0.2, at: time(9.9)), .none)
        XCTAssertEqual(controller.observe(speedMps: 0.2, at: time(10)), .autoPaused)
    }

    func testSessionDedupeDropoutAndManualPauseFlowIntoRecordedSamplesAndGPX() throws {
        var session = RecordingSession()
        session.start(at: time(0))
        let firstPower = PowerObservation(watts: 250, timestamp: time(1))

        XCTAssertEqual(
            session.ingest(
                sessionFix(second: 1, latitude: 40, speedMps: 5, power: firstPower),
                wallNow: time(1)
            ),
            .recorded
        )
        XCTAssertEqual(
            session.ingest(
                sessionFix(second: 2, latitude: 40.00009, speedMps: 5, power: firstPower),
                wallNow: time(2)
            ),
            .recorded
        )
        XCTAssertEqual(session.samples.map(\.powerW), [250, nil])
        XCTAssertGreaterThan(session.distanceM, 9)

        session.tick(at: time(4.1), powerObservation: firstPower)
        XCTAssertNil(session.power3sW)
        XCTAssertNil(session.power10sW)

        session.tick(at: time(5), powerObservation: nil)
        XCTAssertTrue(session.manualPause(at: time(5)))
        XCTAssertEqual(session.controlMode, .endAndResume)
        let pausedElapsed = session.elapsedS
        let pausedDistance = session.distanceM
        let pausedSampleCount = session.samples.count
        let secondPower = PowerObservation(watts: 300, timestamp: time(5.5))

        XCTAssertEqual(
            session.ingest(
                sessionFix(second: 6, latitude: 40.00018, speedMps: 5, power: secondPower),
                wallNow: time(6)
            ),
            .ignored
        )
        session.tick(at: time(6), powerObservation: secondPower)
        XCTAssertEqual(session.elapsedS, pausedElapsed)
        XCTAssertEqual(session.distanceM, pausedDistance)
        XCTAssertEqual(session.samples.count, pausedSampleCount)

        XCTAssertTrue(session.manualResume(at: time(7)))
        XCTAssertEqual(session.controlMode, .pause)
        XCTAssertEqual(
            session.ingest(
                sessionFix(second: 8, latitude: 40.00027, speedMps: 5, power: secondPower),
                wallNow: time(8)
            ),
            .recorded
        )
        // Power observed while paused cannot testify at a resumed coordinate.
        XCTAssertNil(session.samples.last?.powerW)

        let postResumePower = PowerObservation(watts: 300, timestamp: time(8.5))
        XCTAssertEqual(
            session.ingest(
                sessionFix(
                    second: 8.25,
                    latitude: 40.00030,
                    speedMps: 5,
                    power: postResumePower
                ),
                wallNow: time(9)
            ),
            .recorded
        )
        // A batched GPS fix captured before the BLE notification cannot be
        // relabeled with that newer observation.
        XCTAssertNil(session.samples.last?.powerW)
        XCTAssertEqual(
            session.ingest(
                sessionFix(
                    second: 9,
                    latitude: 40.00036,
                    speedMps: 5,
                    power: postResumePower
                ),
                wallNow: time(9)
            ),
            .recorded
        )
        XCTAssertEqual(session.samples.map(\.powerW), [250, nil, nil, nil, 300])
        XCTAssertEqual(
            session.samples.map(\.startsNewSegment),
            [true, false, true, false, false]
        )

        let xml = try XCTUnwrap(
            String(
                data: GPXWriter.gpx(samples: session.samples, startedAt: time(0)),
                encoding: .utf8
            )
        )
        XCTAssertEqual(occurrences(of: "<br:power>250</br:power>", in: xml), 1)
        XCTAssertEqual(occurrences(of: "<br:power>300</br:power>", in: xml), 1)
        XCTAssertEqual(occurrences(of: "<trkseg>", in: xml), 2)
    }

    func testPhysicalAutoResumeHasNoManualResumeAndStartsANewRecordedSegment() throws {
        var session = RecordingSession()
        session.start(at: time(0))

        XCTAssertEqual(
            session.ingest(
                sessionFix(second: 0, latitude: 40, speedMps: 0.2),
                wallNow: time(0)
            ),
            .recorded
        )
        XCTAssertEqual(
            session.ingest(
                sessionFix(second: 5, latitude: 40, speedMps: 0.2),
                wallNow: time(5)
            ),
            .autoPaused
        )
        XCTAssertEqual(session.state, .autoPaused)
        XCTAssertEqual(session.controlMode, .endOnly)
        XCTAssertFalse(session.manualResume(at: time(5.1)))
        XCTAssertEqual(session.state, .autoPaused)

        XCTAssertEqual(
            session.ingest(
                sessionFix(second: 6, latitude: 40, speedMps: 2),
                wallNow: time(6)
            ),
            .ignored
        )
        // The 14-second GPS gap resets the physical resume clock.
        XCTAssertEqual(
            session.ingest(
                sessionFix(second: 20, latitude: 40, speedMps: 2),
                wallNow: time(20)
            ),
            .ignored
        )
        XCTAssertEqual(session.state, .autoPaused)
        XCTAssertEqual(
            session.ingest(
                sessionFix(second: 21, latitude: 40, speedMps: 2),
                wallNow: time(21)
            ),
            .ignored
        )
        XCTAssertEqual(
            session.ingest(
                sessionFix(second: 22, latitude: 40, speedMps: 2),
                wallNow: time(22)
            ),
            .autoResumed
        )
        XCTAssertEqual(session.state, .recording)
        XCTAssertEqual(session.controlMode, .pause)

        XCTAssertEqual(
            session.ingest(
                sessionFix(second: 23, latitude: 40.00009, speedMps: 2),
                wallNow: time(23)
            ),
            .recorded
        )
        XCTAssertEqual(session.samples.map(\.startsNewSegment), [true, true])
        let xml = try XCTUnwrap(
            String(
                data: GPXWriter.gpx(samples: session.samples, startedAt: time(0)),
                encoding: .utf8
            )
        )
        XCTAssertEqual(occurrences(of: "<trkseg>", in: xml), 2)
    }

    private func time(_ seconds: TimeInterval) -> Date {
        start.addingTimeInterval(seconds)
    }

    private func point(
        second: TimeInterval,
        edgeM: Double?,
        speedMps: Double?,
        speedAccuracyMps: Double? = 0.5,
        evidencedEdgeM: Double? = nil
    ) -> AcceptedGPSPoint {
        AcceptedGPSPoint(
            observation: GPSObservation(
                timestamp: time(second),
                latitude: 40.026,
                longitude: -75.223,
                horizontalAccuracyM: 4,
                speedMps: speedMps,
                speedAccuracyMps: speedAccuracyMps,
                courseDegrees: 0
            ),
            filteredSpeedMps: speedMps,
            filteredCourseDegrees: 0,
            startsNewSegment: edgeM == nil,
            distanceFromPreviousM: edgeM,
            evidencedDistanceFromPreviousM: evidencedEdgeM
        )
    }

    private func observation(
        second: TimeInterval,
        latitude: Double,
        speedMps: Double?,
        speedAccuracyMps: Double?
    ) -> GPSObservation {
        GPSObservation(
            timestamp: time(second),
            latitude: latitude,
            longitude: -75,
            horizontalAccuracyM: 0.1,
            speedMps: speedMps,
            speedAccuracyMps: speedAccuracyMps,
            courseDegrees: 0
        )
    }

    private func sessionFix(
        second: TimeInterval,
        latitude: Double,
        speedMps: Double?,
        speedAccuracyMps: Double? = 0.5,
        power: PowerObservation? = nil
    ) -> RecordingSessionFix {
        RecordingSessionFix(
            gps: observation(
                second: second,
                latitude: latitude,
                speedMps: speedMps,
                speedAccuracyMps: speedAccuracyMps
            ),
            gpsAltitudeM: 100,
            gpsVerticalAccuracyM: 3,
            relativeBarometerM: nil,
            barometerTimestamp: nil,
            heartRateBpm: nil,
            cadenceRpm: nil,
            powerObservation: power
        )
    }

    private func occurrences(of needle: String, in value: String) -> Int {
        value.components(separatedBy: needle).count - 1
    }
}
