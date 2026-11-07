import XCTest
@testable import BoulderRoller

final class ElevationTruthPipelineTests: XCTestCase {
    private let start = Date(timeIntervalSince1970: 1_700_000_000)

    func testHealthyBarometerRejectsGPSAltitudeNoiseAndRecordsProvenance() throws {
        var pipeline = ElevationTruthPipeline()

        let first = pipeline.ingest(observation(second: 0, gps: 100, accuracy: 4, barometer: 0))
        let second = pipeline.ingest(observation(second: 1, gps: 128, accuracy: 4, barometer: 1.5))

        XCTAssertEqual(try XCTUnwrap(first?.elevationM), 100, accuracy: 0.01)
        XCTAssertEqual(try XCTUnwrap(second?.elevationM), 101.5, accuracy: 0.01)
        XCTAssertEqual(second?.source, .barometerFused)
        XCTAssertEqual(second?.confidence, .high)
        XCTAssertEqual(second?.rawGPSAltitudeM, 128)
        XCTAssertEqual(second?.relativeBarometerM, 1.5)
    }

    func testPressureDiscontinuityFallsBackToQualifiedGPSWithoutInventingGain() {
        var pipeline = ElevationTruthPipeline()
        var gain = ElevationGainAccumulator()

        let first = pipeline.ingest(observation(second: 0, gps: 100, accuracy: 4, barometer: 0))
        let second = pipeline.ingest(observation(second: 1, gps: 100.5, accuracy: 4, barometer: 45))

        XCTAssertEqual(second?.source, .gps)
        XCTAssertEqual(second?.confidence, .medium)
        XCTAssertNil(gain.ingest(first, startsNewSegment: true))
        XCTAssertNil(
            gain.ingest(
                second,
                startsNewSegment: second?.beginsNewEvidenceSegment == true
            )
        )
    }

    func testStaleBarometerBreaksTheGainChainBeforeNoisyGPSFallback() {
        var pipeline = ElevationTruthPipeline()
        var gain = ElevationGainAccumulator()

        let first = pipeline.ingest(
            observation(second: 0, gps: 100, accuracy: 4, barometer: 0)
        )
        let staleFallback = pipeline.ingest(
            observation(
                second: 4,
                gps: 140,
                accuracy: 4,
                barometer: 0,
                barometerSecond: 0
            )
        )

        XCTAssertEqual(staleFallback?.source, .gps)
        XCTAssertEqual(staleFallback?.beginsNewEvidenceSegment, true)
        XCTAssertNil(gain.ingest(first, startsNewSegment: true))
        XCTAssertNil(
            gain.ingest(
                staleFallback,
                startsNewSegment: staleFallback?.beginsNewEvidenceSegment == true
            )
        )
    }

    func testRepeatedTimestampReusesIdenticalFreshPressureEvidence() throws {
        var pipeline = ElevationTruthPipeline()
        var gain = ElevationGainAccumulator()

        let first = pipeline.ingest(
            observation(second: 0, gps: 100, accuracy: 4, barometer: 0)
        )
        let repeated = pipeline.ingest(
            observation(
                second: 1,
                gps: 130,
                accuracy: 4,
                barometer: 0,
                barometerSecond: 0
            )
        )

        XCTAssertEqual(repeated?.source, .barometerFused)
        XCTAssertEqual(try XCTUnwrap(repeated?.elevationM), 100, accuracy: 0.01)
        XCTAssertEqual(repeated?.beginsNewEvidenceSegment, false)
        XCTAssertNil(gain.ingest(first, startsNewSegment: true))
        XCTAssertEqual(gain.ingest(repeated, startsNewSegment: false), 0)
    }

    func testInsufficientElevationEvidenceStaysUnavailableRatherThanZero() {
        var pipeline = ElevationTruthPipeline()
        var gain = ElevationGainAccumulator()

        let missing = pipeline.ingest(
            observation(second: 0, gps: 92, accuracy: 80, barometer: nil)
        )

        XCTAssertNil(missing)
        XCTAssertNil(gain.ingest(missing, startsNewSegment: true))
        XCTAssertNil(gain.valueM)
    }

    func testGPXPreservesFusedElevationAndItsRawEvidence() throws {
        let sample = RecordedSample(
            time: start,
            latitude: 40.026,
            longitude: -75.223,
            elevationM: 101.5,
            speedMps: 8,
            hrBpm: nil,
            cadenceRpm: nil,
            powerW: nil,
            elevationSource: .barometerFused,
            elevationConfidence: .high,
            rawGPSAltitudeM: 128,
            relativeBarometerM: 1.5
        )

        let xml = try XCTUnwrap(
            String(data: GPXWriter.gpx(samples: [sample], startedAt: start), encoding: .utf8)
        )

        XCTAssertTrue(xml.contains("<ele>101.5</ele>"))
        XCTAssertTrue(xml.contains("<br:elevation-source>barometer_fused</br:elevation-source>"))
        XCTAssertTrue(xml.contains("<br:elevation-confidence>high</br:elevation-confidence>"))
        XCTAssertTrue(xml.contains("<br:raw-gps-altitude-m>128.0</br:raw-gps-altitude-m>"))
        XCTAssertTrue(xml.contains("<br:relative-barometer-m>1.5</br:relative-barometer-m>"))
    }

    private func observation(
        second: TimeInterval,
        gps: Double?,
        accuracy: Double?,
        barometer: Double?,
        barometerSecond: TimeInterval? = nil
    ) -> ElevationObservation {
        ElevationObservation(
            timestamp: start.addingTimeInterval(second),
            gpsAltitudeM: gps,
            gpsVerticalAccuracyM: accuracy,
            relativeBarometerM: barometer,
            barometerTimestamp: barometer == nil
                ? nil
                : start.addingTimeInterval(barometerSecond ?? second)
        )
    }
}
