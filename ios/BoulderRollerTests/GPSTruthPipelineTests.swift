import CoreLocation
import XCTest
@testable import BoulderRoller

final class GPSTruthPipelineTests: XCTestCase {
    private let originLatitude = 40.0260
    private let originLongitude = -75.2230

    func testRejectsBadFixesPreservesStationaryJitterAndKeepsRejectedEdgesOutOfDistance() throws {
        var pipeline = GPSTruthPipeline()
        let start = Date(timeIntervalSince1970: 1_700_000_000)

        let first = observation(time: start, northM: 0)
        // Labeled stationary jitter: it is a real observed coordinate and may
        // remain in the line, but filtering must never move it elsewhere.
        let stationaryJitter = observation(
            time: start.addingTimeInterval(1), northM: 2, speedMps: 0
        )
        let second = observation(time: start.addingTimeInterval(2), northM: 9)
        let poorAccuracy = observation(
            time: start.addingTimeInterval(3), northM: 18, horizontalAccuracyM: 90
        )
        let teleport = observation(time: start.addingTimeInterval(4), northM: 900)
        let afterGap = observation(time: start.addingTimeInterval(15), northM: 27)

        XCTAssertNotNil(pipeline.ingest(first))
        XCTAssertNotNil(pipeline.ingest(stationaryJitter))
        XCTAssertNotNil(pipeline.ingest(second))
        XCTAssertNil(pipeline.ingest(poorAccuracy))
        XCTAssertNil(pipeline.ingest(teleport))
        let acceptedAfterGap = pipeline.ingest(afterGap)

        XCTAssertEqual(pipeline.accepted.count, 4)
        XCTAssertEqual(pipeline.fragments.map(\.count), [3, 1])
        XCTAssertEqual(acceptedAfterGap?.startsNewSegment, true)
        XCTAssertNil(acceptedAfterGap?.distanceFromPreviousM)
        XCTAssertEqual(pipeline.accepted.map(\.observation.latitude), [
            first.latitude, stationaryJitter.latitude, second.latitude, afterGap.latitude,
        ])
        let acceptedDistance = pipeline.accepted.compactMap(\.distanceFromPreviousM).reduce(0, +)
        let expectedDistance = first.vertex.distance(to: stationaryJitter.vertex)
            + stationaryJitter.vertex.distance(to: second.vertex)
        XCTAssertEqual(acceptedDistance, expectedDistance, accuracy: 0.01)
        XCTAssertLessThan(acceptedDistance, 10)

        let exportedSamples = pipeline.accepted.map { accepted in
            RecordedSample(
                time: accepted.observation.timestamp,
                latitude: accepted.observation.latitude,
                longitude: accepted.observation.longitude,
                elevationM: nil,
                speedMps: accepted.filteredSpeedMps,
                hrBpm: nil,
                cadenceRpm: nil,
                powerW: nil,
                startsNewSegment: accepted.startsNewSegment
            )
        }
        let xml = try XCTUnwrap(
            String(
                data: GPXWriter.gpx(samples: exportedSamples, startedAt: start),
                encoding: .utf8
            )
        )
        for accepted in [first, stationaryJitter, second, afterGap] {
            XCTAssertTrue(xml.contains(gpxCoordinate(accepted)))
        }
        XCTAssertFalse(xml.contains(gpxCoordinate(poorAccuracy)))
        XCTAssertFalse(xml.contains(gpxCoordinate(teleport)))
        XCTAssertEqual(xml.components(separatedBy: "<trkseg>").count - 1, 2)
        XCTAssertEqual(xml.components(separatedBy: "</trkseg>").count - 1, 2)
    }

    func testPauseBoundaryNeverJoinsTwoObservedLocations() {
        var pipeline = GPSTruthPipeline()
        let start = Date(timeIntervalSince1970: 1_700_000_000)

        _ = pipeline.ingest(observation(time: start, northM: 0))
        _ = pipeline.ingest(observation(time: start.addingTimeInterval(1), northM: 8))
        pipeline.requireSegmentBreak()
        let resumed = pipeline.ingest(observation(time: start.addingTimeInterval(2), northM: 16))

        XCTAssertEqual(resumed?.startsNewSegment, true)
        XCTAssertNil(resumed?.distanceFromPreviousM)
        XCTAssertEqual(pipeline.fragments.map(\.count), [2, 1])
    }

    func testZoomSimplificationSelectsOnlyObservedVertices() {
        let points = (0..<21).map { index in
            RouteVertex(
                latitude: originLatitude + Double(index) * 0.00005,
                longitude: originLongitude + (index.isMultiple(of: 2) ? 0.00002 : -0.00002)
            )
        }

        let close = ZoomRouteSimplifier.simplify(points, zoomLevel: 18)
        let far = ZoomRouteSimplifier.simplify(points, zoomLevel: 11)
        let observed = Set(points)

        XCTAssertGreaterThan(close.count, far.count)
        XCTAssertTrue(close.allSatisfy(observed.contains))
        XCTAssertTrue(far.allSatisfy(observed.contains))
        XCTAssertEqual(close.first, points.first)
        XCTAssertEqual(close.last, points.last)
        XCTAssertEqual(far.first, points.first)
        XCTAssertEqual(far.last, points.last)
    }

    func testServerPreviewPrivacySegmentsRemainDisconnected() {
        let preview = RoutePreview(
            source: "privacy_filtered",
            points: nil,
            segments: [
                [.init(x: 0.0, y: 0.0), .init(x: 0.2, y: 0.2)],
                [.init(x: 0.8, y: 0.8), .init(x: 1.0, y: 1.0)],
            ],
            bounds: .init(minLat: 40, minLon: -75.3, maxLat: 40.1, maxLon: -75.2),
            placeLabel: nil,
            fallbackReason: nil
        )

        let fragments = RouteGeometry.fragments(from: preview)

        XCTAssertEqual(fragments.map(\.count), [2, 2])
        XCTAssertEqual(RouteGeometry.coordinates(from: preview).count, 4)
    }

    func testSavedGPSTeleportDropsThePointUnderTheRenderPolicySpeedCeiling() {
        let start = 1_700_000_000.0
        let gps = GpsResponse(gpsPoints: [
            gpsPoint(second: start, northM: 0),
            gpsPoint(second: start + 1, northM: 200),
            gpsPoint(second: start + 2, northM: 10),
        ])

        let fragments = RouteGeometry.fragments(from: gps)

        XCTAssertEqual(fragments.map(\.count), [2])
        XCTAssertEqual(fragments[0].map(\.latitude), [
            originLatitude,
            originLatitude + 10 / 111_111,
        ])
    }

    /// Garmin smart recording legitimately spaces samples ~15 s apart at low
    /// speed. The render policy must keep such credible imports continuous —
    /// the dotted-route regression (bead boulderroller-v2-zudgp).
    func testSavedGPSSmartRecordingIntervalsStayContinuous() {
        let start = 1_700_000_000.0
        let gps = GpsResponse(gpsPoints: [
            gpsPoint(second: start, northM: 0),
            gpsPoint(second: start + 15, northM: 70),
            gpsPoint(second: start + 29, northM: 140),
            gpsPoint(second: start + 45, northM: 220),
        ])

        XCTAssertEqual(RouteGeometry.fragments(from: gps).map(\.count), [4])
    }

    func testSavedGPSMovingOutageBreaksButStationaryPauseBridges() {
        let start = 1_700_000_000.0
        // Rider vanished for 90 s and reappeared 300 m away: the path between
        // is unknown and never invented.
        let movingOutage = GpsResponse(gpsPoints: [
            gpsPoint(second: start, northM: 0),
            gpsPoint(second: start + 1, northM: 8),
            gpsPoint(second: start + 91, northM: 300),
            gpsPoint(second: start + 92, northM: 308),
        ])
        // Rider stood still for five minutes (cafe): endpoints moved ~20 m,
        // the line stays connected.
        let stationaryPause = GpsResponse(gpsPoints: [
            gpsPoint(second: start, northM: 0),
            gpsPoint(second: start + 1, northM: 8),
            gpsPoint(second: start + 301, northM: 28),
            gpsPoint(second: start + 302, northM: 36),
        ])
        let unknownTime = GpsResponse(gpsPoints: [
            gpsPoint(second: nil, northM: 0),
            gpsPoint(second: nil, northM: 8),
        ])

        XCTAssertEqual(RouteGeometry.fragments(from: movingOutage).map(\.count), [2, 2])
        XCTAssertEqual(RouteGeometry.fragments(from: stationaryPause).map(\.count), [4])
        XCTAssertTrue(RouteGeometry.fragments(from: unknownTime).isEmpty)
    }

    /// Singleton rule, explicit: a fragment that ends up with a single point
    /// is skipped — never drawn as a stray dot.
    func testSavedGPSSingletonFragmentsAreSkippedNotDrawnAsDots() {
        let start = 1_700_000_000.0
        let gps = GpsResponse(gpsPoints: [
            gpsPoint(second: start, northM: 0),
            gpsPoint(second: start + 1, northM: 8),
            // Isolated point after a moving outage on both sides.
            gpsPoint(second: start + 121, northM: 500),
            gpsPoint(second: start + 241, northM: 1_000),
            gpsPoint(second: start + 242, northM: 1_008),
        ])

        XCTAssertEqual(RouteGeometry.fragments(from: gps).map(\.count), [2, 2])
    }

    func testSnapshotRenderIdentityChangesWhenCoordinatesChangeAtTheSameCounts() {
        let size = CGSize(width: 320, height: 140)
        let first = [[
            CLLocationCoordinate2D(latitude: 40.0, longitude: -75.0),
            CLLocationCoordinate2D(latitude: 40.1, longitude: -75.1),
        ]]
        let second = [[
            CLLocationCoordinate2D(latitude: 41.0, longitude: -76.0),
            CLLocationCoordinate2D(latitude: 41.1, longitude: -76.1),
        ]]

        XCTAssertNotEqual(
            RouteMapSnapshot.renderIdentity(
                size: size, fragments: first, showsStartDot: true
            ),
            RouteMapSnapshot.renderIdentity(
                size: size, fragments: second, showsStartDot: true
            )
        )
    }

    func testMapSnapshotWorkStartedBeforeAccountBoundaryIsRefused() {
        let prior = RouteMapSnapshot.SnapshotDisk.captureAccountBoundary()

        RouteMapSnapshot.SnapshotDisk.advanceAccountBoundary()

        XCTAssertFalse(RouteMapSnapshot.SnapshotDisk.permitsWork(at: prior))
    }

    @MainActor
    func testMapSnapshotCacheCannotStoreAcrossAccountBoundary() {
        let key = RouteMapSnapshot.renderIdentity(
            size: CGSize(width: 320, height: 140),
            fragments: [[
                CLLocationCoordinate2D(latitude: 40.0, longitude: -75.0),
                CLLocationCoordinate2D(latitude: 40.1, longitude: -75.1),
            ]],
            showsStartDot: true
        )
        let prior = RouteMapSnapshot.SnapshotDisk.captureAccountBoundary()

        RouteMapSnapshot.SnapshotDisk.advanceAccountBoundary()
        let stored = RouteMapSnapshot.SnapshotCache.shared.store(
            UIImage(),
            nil,
            for: key,
            at: prior
        )

        XCTAssertFalse(stored)
        XCTAssertNil(
            RouteMapSnapshot.SnapshotCache.shared.value(
                for: key,
                at: RouteMapSnapshot.SnapshotDisk.captureAccountBoundary()
            )
        )
    }

    func testGPXWriterStartsANewTrackSegmentAtEveryEvidenceGap() throws {
        let start = Date(timeIntervalSince1970: 1_700_000_000)
        let samples = [
            sample(time: start, northM: 0),
            sample(time: start.addingTimeInterval(1), northM: 8),
            sample(time: start.addingTimeInterval(12), northM: 40, startsNewSegment: true),
            sample(time: start.addingTimeInterval(13), northM: 48),
        ]

        let xml = try XCTUnwrap(String(data: GPXWriter.gpx(samples: samples, startedAt: start), encoding: .utf8))

        XCTAssertEqual(xml.components(separatedBy: "<trkseg>").count - 1, 2)
        XCTAssertEqual(xml.components(separatedBy: "</trkseg>").count - 1, 2)
    }

    private func observation(
        time: Date,
        northM: Double,
        horizontalAccuracyM: Double = 4,
        speedMps: Double? = 8
    ) -> GPSObservation {
        GPSObservation(
            timestamp: time,
            latitude: originLatitude + northM / 111_111,
            longitude: originLongitude,
            horizontalAccuracyM: horizontalAccuracyM,
            speedMps: speedMps,
            speedAccuracyMps: 0.5,
            courseDegrees: 0
        )
    }

    private func sample(time: Date, northM: Double, startsNewSegment: Bool = false) -> RecordedSample {
        RecordedSample(
            time: time,
            latitude: originLatitude + northM / 111_111,
            longitude: originLongitude,
            elevationM: nil,
            speedMps: 8,
            hrBpm: nil,
            cadenceRpm: nil,
            powerW: nil,
            startsNewSegment: startsNewSegment
        )
    }

    private func gpsPoint(second: Double?, northM: Double) -> GpsPoint {
        GpsPoint(
            latitude: originLatitude + northM / 111_111,
            longitude: originLongitude,
            elevationM: nil,
            elevationCorrectedM: nil,
            distanceM: northM,
            timestamp: second
        )
    }

    private func gpxCoordinate(_ observation: GPSObservation) -> String {
        String(
            format: "<trkpt lat=\"%.7f\" lon=\"%.7f\">",
            observation.latitude,
            observation.longitude
        )
    }
}
