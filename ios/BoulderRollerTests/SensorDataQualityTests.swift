import XCTest
@testable import BoulderRoller

/// Item 11 (bead boulderroller-v2-odmi6.11): trusted sensor data quality.
/// The state machines are pure and fully provable without radios — the
/// simulator has none; hardware verification is tracked on the bead.
final class SensorDataQualityTests: XCTestCase {
    private let start = Date(timeIntervalSince1970: 1_700_000_000)
    private let meterA = UUID(uuidString: "AAAAAAAA-0000-4000-8000-000000000001")!
    private let meterB = UUID(uuidString: "BBBBBBBB-0000-4000-8000-000000000002")!

    private func time(_ seconds: TimeInterval) -> Date {
        start.addingTimeInterval(seconds)
    }

    // MARK: Source resolution — deterministic, never last-callback-wins

    func testExplicitSelectionWinsWhileProviding() {
        XCTAssertEqual(
            SensorSourceResolver.resolve(
                explicitSelection: meterB,
                connectedProvidersInPairedOrder: [meterA, meterB]
            ),
            meterB
        )
    }

    func testDisconnectedSelectionFallsBackToPairedPriority() {
        XCTAssertEqual(
            SensorSourceResolver.resolve(
                explicitSelection: meterB,
                connectedProvidersInPairedOrder: [meterA]
            ),
            meterA
        )
    }

    func testNoSelectionResolvesToEarliestPairedProvider() {
        XCTAssertEqual(
            SensorSourceResolver.resolve(
                explicitSelection: nil,
                connectedProvidersInPairedOrder: [meterA, meterB]
            ),
            meterA
        )
        XCTAssertNil(
            SensorSourceResolver.resolve(
                explicitSelection: nil,
                connectedProvidersInPairedOrder: []
            )
        )
    }

    func testSelectionPersistsAndForgottenDevicesLoseTheirPick() {
        let suiteName = "sensor-selection-tests-\(UUID().uuidString)"
        let defaults = UserDefaults(suiteName: suiteName)!
        defer { defaults.removePersistentDomain(forName: suiteName) }

        var selection = SensorSourceSelection.load(defaults: defaults)
        XCTAssertNil(selection[.power])
        selection[.power] = meterB
        selection[.heartRate] = meterA
        selection.save(defaults: defaults)

        var reloaded = SensorSourceSelection.load(defaults: defaults)
        XCTAssertEqual(reloaded[.power], meterB)
        XCTAssertEqual(reloaded[.heartRate], meterA)

        reloaded.removeDevice(meterB)
        XCTAssertNil(reloaded[.power])
        XCTAssertEqual(reloaded[.heartRate], meterA)
    }

    // MARK: Calibration state machine (Cycling Power Control Point 0x2A66)

    func testCalibrationHappyPathReportsMeterOffset() {
        var flow = PowerCalibrationFlow()
        XCTAssertEqual(flow.state, .idle)

        XCTAssertEqual(flow.begin(), .enableIndications)
        XCTAssertEqual(flow.state, .preparing)
        // A second tap while in flight changes nothing.
        XCTAssertEqual(flow.begin(), PowerCalibrationFlow.Effect.none)
        XCTAssertEqual(flow.state, .preparing)

        XCTAssertEqual(flow.indicationsReady(), .writeStartOffsetCompensation)
        XCTAssertEqual(flow.state, .awaitingResponse)

        // Response Code / Start Offset Compensation / Success / sint16 -340.
        flow.indication(Data([0x20, 0x0C, 0x01, 0xAC, 0xFE]))
        XCTAssertEqual(flow.state, .succeeded(rawOffset: -340))
        XCTAssertFalse(flow.isInFlight)
    }

    func testCalibrationSuccessWithoutParameterIsStillTruthful() {
        var flow = PowerCalibrationFlow()
        _ = flow.begin()
        _ = flow.indicationsReady()
        flow.indication(Data([0x20, 0x0C, 0x01]))
        XCTAssertEqual(flow.state, .succeeded(rawOffset: nil))
    }

    func testCalibrationRejectionAndUnsupportedAreDistinct() {
        var flow = PowerCalibrationFlow()
        _ = flow.begin()
        _ = flow.indicationsReady()
        flow.indication(Data([0x20, 0x0C, 0x02]))
        XCTAssertEqual(flow.state, .failed(.notSupported))

        // Re-runnable from a settled state.
        XCTAssertEqual(flow.begin(), .enableIndications)
        _ = flow.indicationsReady()
        flow.indication(Data([0x20, 0x0C, 0x04]))
        XCTAssertEqual(flow.state, .failed(.rejected))
    }

    func testUnrelatedIndicationsAreIgnoredUntilTimeout() {
        var flow = PowerCalibrationFlow()
        _ = flow.begin()
        _ = flow.indicationsReady()

        // An answer to a question this flow did not ask (request op 0x01),
        // a malformed frame, and an early frame must not settle the flow.
        flow.indication(Data([0x20, 0x01, 0x01]))
        flow.indication(Data([0x20]))
        XCTAssertEqual(flow.state, .awaitingResponse)

        flow.timedOut()
        XCTAssertEqual(flow.state, .failed(.timedOut))
        // A late meter answer cannot rewrite a settled truthful result.
        flow.indication(Data([0x20, 0x0C, 0x01, 0x00, 0x00]))
        XCTAssertEqual(flow.state, .failed(.timedOut))
    }

    func testWriteFailureDisconnectAndEarlyIndicationPaths() {
        var flow = PowerCalibrationFlow()
        // Indications arriving before begin() are ignored.
        flow.indication(Data([0x20, 0x0C, 0x01]))
        XCTAssertEqual(flow.state, .idle)

        _ = flow.begin()
        // Indication while still preparing (write not sent) is ignored.
        flow.indication(Data([0x20, 0x0C, 0x01]))
        XCTAssertEqual(flow.state, .preparing)
        flow.indicationsFailed()
        XCTAssertEqual(flow.state, .failed(.writeFailed))

        var second = PowerCalibrationFlow()
        _ = second.begin()
        _ = second.indicationsReady()
        second.writeFailed()
        XCTAssertEqual(second.state, .failed(.writeFailed))

        var third = PowerCalibrationFlow()
        _ = third.begin()
        third.deviceDisconnected()
        XCTAssertEqual(third.state, .failed(.disconnected))
        // Terminal events on settled flows change nothing.
        third.timedOut()
        XCTAssertEqual(third.state, .failed(.disconnected))
    }

    func testPowerFeatureBitfieldParsing() {
        // Little-endian uint32 with bit 4 set.
        let bits = PowerCalibrationGATT.featureBits(Data([0x10, 0x00, 0x00, 0x00]))
        XCTAssertEqual(bits, 0x10)
        XCTAssertNotEqual(bits! & PowerCalibrationGATT.featureOffsetCompensationBit, 0)
        XCTAssertEqual(
            PowerCalibrationGATT.featureBits(Data([0x08, 0x00, 0x00, 0x00]))!
                & PowerCalibrationGATT.featureOffsetCompensationBit,
            0
        )
        XCTAssertNil(PowerCalibrationGATT.featureBits(Data([0x10, 0x00])))
    }

    // MARK: Recorded-stream policy — bounded holds, no zero-fill, provenance

    func testHeartRateAndCadenceHoldWindowsBoundRecordedSamples() {
        var session = RecordingSession()
        session.start(at: time(0), monotonicNowS: 0)

        // Testimony 4.9 s old at capture: inside the 5 s hold, recorded.
        XCTAssertEqual(
            session.ingest(
                fix(second: 1, heartRate: 148, heartRateAt: time(-3.9), cadence: 90, cadenceAt: time(-3.9)),
                wallNow: time(1),
                monotonicNowS: 1
            ),
            .recorded
        )
        // Testimony 5.1 s old at capture: outside the hold, absent — the
        // strap dropped out and the file says so.
        XCTAssertEqual(
            session.ingest(
                fix(second: 2, heartRate: 148, heartRateAt: time(-3.1), cadence: 90, cadenceAt: time(-3.1)),
                wallNow: time(2),
                monotonicNowS: 2
            ),
            .recorded
        )
        // Legacy journaled fixes without testimony times replay exactly as
        // originally recorded (grandfathered), and absent channels stay nil.
        XCTAssertEqual(
            session.ingest(
                fix(second: 3, heartRate: 151, heartRateAt: nil),
                wallNow: time(3),
                monotonicNowS: 3
            ),
            .recorded
        )

        let samples = session.end(at: time(4), monotonicNowS: 4)
        XCTAssertEqual(samples.count, 3)
        XCTAssertEqual(samples[0].hrBpm, 148)
        XCTAssertEqual(samples[0].cadenceRpm, 90)
        XCTAssertNil(samples[1].hrBpm)
        XCTAssertNil(samples[1].cadenceRpm)
        XCTAssertEqual(samples[2].hrBpm, 151)
    }

    func testPowerDropoutIsAbsenceNeverZeroFillNorHold() {
        var session = RecordingSession()
        session.start(at: time(0), monotonicNowS: 0)

        let observation = PowerObservation(watts: 250, timestamp: time(1), sourceID: meterA)
        XCTAssertEqual(
            session.ingest(
                fix(second: 1, power: observation),
                wallNow: time(1),
                monotonicNowS: 1
            ),
            .recorded
        )
        // The same notification still live 4.1 s later: outside the
        // association window and already recorded once — absent, not held,
        // not zeroed.
        XCTAssertEqual(
            session.ingest(
                fix(second: 5.1, power: observation),
                wallNow: time(5.1),
                monotonicNowS: 5.1
            ),
            .recorded
        )

        let samples = session.end(at: time(6), monotonicNowS: 6)
        XCTAssertEqual(samples[0].powerW, 250)
        XCTAssertEqual(samples[0].powerSourceID, meterA)
        XCTAssertNil(samples[1].powerW)
        XCTAssertNil(samples[1].powerSourceID)
    }

    func testPowerSourceSwitchIsRecordedPerSampleAndInGPX() {
        var session = RecordingSession()
        session.start(at: time(0), monotonicNowS: 0)

        _ = session.ingest(
            fix(second: 1, power: PowerObservation(watts: 240, timestamp: time(1), sourceID: meterA)),
            wallNow: time(1),
            monotonicNowS: 1
        )
        _ = session.ingest(
            fix(second: 2, power: PowerObservation(watts: 242, timestamp: time(2), sourceID: meterA)),
            wallNow: time(2),
            monotonicNowS: 2
        )
        // Two meters can legally share a notification timestamp; a different
        // source at the same instant is new testimony, and the switch is
        // recorded rather than silent.
        _ = session.ingest(
            fix(second: 3, power: PowerObservation(watts: 260, timestamp: time(2), sourceID: meterB)),
            wallNow: time(3),
            monotonicNowS: 3
        )

        let samples = session.end(at: time(4), monotonicNowS: 4)
        XCTAssertEqual(samples.map(\.powerSourceID), [meterA, meterA, meterB])

        let gpx = String(decoding: GPXWriter.gpx(samples: samples, startedAt: time(0)), as: UTF8.self)
        // Annotated on the first powered sample and on the switch — twice,
        // not three times.
        XCTAssertEqual(
            occurrences(of: "<br:power-source>", in: gpx),
            2
        )
        XCTAssertEqual(
            occurrences(of: "<br:power-source>\(meterA.uuidString.lowercased())</br:power-source>", in: gpx),
            1
        )
        XCTAssertEqual(
            occurrences(of: "<br:power-source>\(meterB.uuidString.lowercased())</br:power-source>", in: gpx),
            1
        )
    }

    // MARK: Fixtures

    private func fix(
        second: TimeInterval,
        heartRate: Int? = nil,
        heartRateAt: Date? = nil,
        cadence: Int? = nil,
        cadenceAt: Date? = nil,
        power: PowerObservation? = nil
    ) -> RecordingSessionFix {
        RecordingSessionFix(
            gps: GPSObservation(
                timestamp: time(second),
                latitude: 39.95 + second * 0.0001,
                longitude: -75.16,
                horizontalAccuracyM: 0.1,
                speedMps: 5,
                speedAccuracyMps: 0.2,
                courseDegrees: 0
            ),
            gpsAltitudeM: 100,
            gpsVerticalAccuracyM: 2,
            relativeBarometerM: nil,
            barometerTimestamp: nil,
            heartRateBpm: heartRate,
            cadenceRpm: cadence,
            powerObservation: power,
            heartRateAt: heartRateAt,
            cadenceAt: cadenceAt
        )
    }

    private func occurrences(of needle: String, in value: String) -> Int {
        value.components(separatedBy: needle).count - 1
    }
}
