import XCTest
@testable import BoulderRoller

/// The production ride contracts this wiring pass consumes (all live and
/// deployed 2026-08-11): DEM-corrected climbing totals + provenance on the
/// ride object, `elevation_corrected_m` per GPS point, canon `climbId` on
/// climb patterns, and server-generated default titles. Fixtures mirror the
/// exact wire casing each endpoint serves.
final class LiveRideContractTests: XCTestCase {
    /// The production client's decoder configuration.
    private let decoder: JSONDecoder = {
        let d = JSONDecoder()
        d.keyDecodingStrategy = .convertFromSnakeCase
        return d
    }()

    // MARK: Ride object — corrected climbing total + provenance (camelCase)

    func testRideDecodesCorrectedClimbingTotalAndProvenance() throws {
        let corrected = """
        {"id": "r1", "startedAt": "2026-08-11T12:00:00Z", "title": "Manayunk Ride",
         "elevationM": 512.0, "elevationCorrectedM": 431.5,
         "elevationCorrection": {"status": "corrected",
            "sourceVersion": "usgs3dep_delval_v1", "correctionVersion": "v2",
            "coverageBps": 10000, "reason": null}}
        """
        let ride = try decoder.decode(Ride.self, from: Data(corrected.utf8))
        XCTAssertEqual(ride.elevationCorrectedM, 431.5)
        XCTAssertEqual(ride.elevationCorrection?.status, "corrected")
        XCTAssertEqual(ride.elevationCorrection?.sourceVersion, "usgs3dep_delval_v1")
        XCTAssertEqual(ride.elevationCorrection?.correctionVersion, "v2")
        XCTAssertEqual(ride.elevationCorrection?.coverageBps, 10000)
        XCTAssertNil(ride.elevationCorrection?.reason)
        // The raw device total stays decoded and untouched — the server
        // never overwrites it; the client just stops rendering it as truth.
        XCTAssertEqual(ride.elevationM, 512.0)
    }

    func testRideDecodesTruthfulAbstentionAndLegacyAbsence() throws {
        // Abstention: correction ran and refused (e.g. outside the DEM grid).
        let abstained = """
        {"id": "r2", "startedAt": "2026-08-11T12:00:00Z",
         "elevationM": 512.0, "elevationCorrectedM": null,
         "elevationCorrection": {"status": "unavailable",
            "sourceVersion": null, "correctionVersion": "v2",
            "coverageBps": 120, "reason": "insufficient_coverage"}}
        """
        let ride = try decoder.decode(Ride.self, from: Data(abstained.utf8))
        XCTAssertNil(ride.elevationCorrectedM)
        XCTAssertEqual(ride.elevationCorrection?.status, "unavailable")
        XCTAssertEqual(ride.elevationCorrection?.reason, "insufficient_coverage")

        // Legacy absence: correction never attempted — object entirely absent.
        let legacy = """
        {"id": "r3", "startedAt": "2026-08-11T12:00:00Z", "elevationM": 512.0}
        """
        let legacyRide = try decoder.decode(Ride.self, from: Data(legacy.utf8))
        XCTAssertNil(legacyRide.elevationCorrectedM)
        XCTAssertNil(legacyRide.elevationCorrection)
    }

    // MARK: GPS points — per-point corrected elevation (snake_case)

    func testGpsPointsDecodePerPointCorrectedElevation() throws {
        let payload = """
        {"gps_points": [
            {"latitude": 40.03, "longitude": -75.22, "elevation_m": 30.0,
             "elevation_corrected_m": 28.4, "distance_m": 0.0, "timestamp": 1770000000},
            {"latitude": 40.031, "longitude": -75.221, "elevation_m": 33.0,
             "elevation_corrected_m": null, "distance_m": 25.0, "timestamp": 1770000005}
        ]}
        """
        let gps = try decoder.decode(GpsResponse.self, from: Data(payload.utf8))
        XCTAssertEqual(gps.gpsPoints[0].elevationCorrectedM, 28.4)
        XCTAssertNil(gps.gpsPoints[1].elevationCorrectedM)
        XCTAssertEqual(gps.gpsPoints[1].elevationM, 33.0)
    }

    // MARK: Patterns — canon climbId independent of completion (camelCase)

    func testClimbPatternDecodesCanonClimbIdWithoutCompletion() throws {
        let payload = """
        {"rideId": "r1", "patterns": {"climb_patterns": [
            {"id": "p1", "name": "Shawmont Avenue",
             "climbId": "1f0770a4-0000-4000-8000-000000000001",
             "startOffsetS": 100, "endOffsetS": 272},
            {"id": "p2", "name": "Unmatched rise",
             "startOffsetS": 400, "endOffsetS": 460}
        ]}}
        """
        let response = try decoder.decode(PatternsResponse.self, from: Data(payload.utf8))
        let climbs = try XCTUnwrap(response.patterns?.climbPatterns)
        XCTAssertEqual(climbs[0].climbId, "1f0770a4-0000-4000-8000-000000000001")
        XCTAssertNil(climbs[1].climbId)
    }

    func testCanonClimbIdPrefersVaultMatchThenPatternClimbId() throws {
        let payload = """
        {"climb_patterns": [
            {"id": "p1", "climbId": "canon-from-pattern",
             "vaultMatch": {"vaultClimbId": "canon-from-completion"}},
            {"id": "p2", "climbId": "canon-from-pattern"},
            {"id": "p3"}
        ]}
        """
        let patterns = try decoder.decode(PatternsPayload.self, from: Data(payload.utf8))
        let climbs = try XCTUnwrap(patterns.climbPatterns)
        // Completion projection wins where the ride produced one…
        XCTAssertEqual(climbs[0].canonClimbId, "canon-from-completion")
        // …the pattern's own authoritative traversal id carries otherwise…
        XCTAssertEqual(climbs[1].canonClimbId, "canon-from-pattern")
        // …and no canon identity means nowhere to go (row stays inert).
        XCTAssertNil(climbs[2].canonClimbId)
    }

    func testVaultMatchDecodesProductionPRAndRankFacts() throws {
        let payload = """
        {"climb_patterns":[{"id":"p1","vault_match":{
          "vault_climb_id":"climb-1","your_time":2275,"is_pr":true,
          "your_best_time":2275,"your_rank":2}}]}
        """
        let patterns = try decoder.decode(PatternsPayload.self, from: Data(payload.utf8))
        let match = try XCTUnwrap(patterns.climbPatterns?.first?.vaultMatch)
        XCTAssertEqual(match.isPR, true)
        XCTAssertEqual(match.yourRank, 2)
        XCTAssertEqual(match.yourBestTime, 2275)
    }

    // MARK: Relief — one elevation source per ride, gaps never bridged
    // (ratified 2026-08-18: corrected wherever any correction exists,
    // device elevation otherwise; raw never splices a corrected run)

    func testReliefKeepsCorrectionGapsWhenAnyCorrectionExists() {
        func point(_ d: Double, corrected: Double?) -> GpsPoint {
            GpsPoint(
                latitude: 40, longitude: -75,
                elevationM: 999, // raw present everywhere; it must not leak in
                elevationCorrectedM: corrected,
                distanceM: d, timestamp: nil
            )
        }
        let points = [
            point(0, corrected: 10),
            point(10, corrected: 12),
            point(20, corrected: nil), // correction gap
            point(30, corrected: 14),
            point(40, corrected: 15),
        ]
        let segments = ReliefChart.elevationSegments(points: points)
        XCTAssertEqual(segments.count, 2)
        XCTAssertEqual(
            segments[0],
            [ReliefChart.Sample(x: 0, elevation: 10), ReliefChart.Sample(x: 10, elevation: 12)]
        )
        XCTAssertEqual(
            segments[1],
            [ReliefChart.Sample(x: 30, elevation: 14), ReliefChart.Sample(x: 40, elevation: 15)]
        )
    }

    func testReliefDrawsDeviceElevationWhenNoCorrectionExists() {
        let rawOnly = (0..<5).map { i in
            GpsPoint(
                latitude: 40, longitude: -75,
                elevationM: Double(100 + i),
                elevationCorrectedM: nil,
                distanceM: Double(i * 10), timestamp: nil
            )
        }
        let segments = ReliefChart.elevationSegments(points: rawOnly)
        XCTAssertEqual(segments.count, 1)
        XCTAssertEqual(
            segments[0].map(\.elevation),
            [100, 101, 102, 103, 104]
        )
    }

    // MARK: Titles — server generates; client fallback covers legacy nulls only

    func testServerGeneratedTitlesPassThroughUntouched() {
        // New rides carry a server-side title; the client must not re-derive
        // even when place or hour would produce a different string.
        XCTAssertEqual(
            Format.displayRideTitle(
                "Morning Ride",
                startedAtISO: "2026-08-11T19:30:00Z", // an evening hour
                placeLabel: "Manayunk, Philadelphia"  // a different place
            ),
            "Morning Ride"
        )
        XCTAssertEqual(
            Format.displayRideTitle(
                "Hill repeats with the cohort",
                startedAtISO: "2026-08-11T12:00:00Z",
                placeLabel: nil
            ),
            "Hill repeats with the cohort"
        )
    }

    func testClientFallbackFiresOnlyOnLegacyUnnamedRides() {
        // Wire "Ride" is the backend's legacy final fallback
        // (title ?? file_name ?? "Ride") — the only unnamed shape left.
        XCTAssertEqual(
            Format.displayRideTitle(
                "Ride",
                startedAtISO: "2026-08-11T12:00:00Z",
                placeLabel: "Manayunk, Philadelphia"
            ),
            "Manayunk Ride"
        )
        let noon = DateComponents(
            calendar: .current, timeZone: .current,
            year: 2026, month: 8, day: 11, hour: 12
        ).date!
        XCTAssertEqual(
            Format.displayRideTitle(
                nil,
                startedAtISO: Format.isoParser.string(from: noon),
                placeLabel: nil
            ),
            "Lunch Ride"
        )
    }

    // MARK: Climb destination — sporting rank and rider-result truth

    func testVaultClimbDetailDecodesCompetitionRanksAndLegend() throws {
        let payload = """
        {
          "id": 42,
          "name": "Barren Hill Road",
          "total_completions": 37,
          "total_cal_staked": "184500",
          "leaderboard": [
            {
              "position": 1, "rank": 1, "competition_rank": 1,
              "tie_size": 2, "is_tied": true,
              "wallet": "rider-a", "display_name": "Avery Brooks",
              "avatar_url": "https://example.com/a.jpg",
              "best_time_seconds": 268, "achieved_at": "2026-08-02T12:10:00Z"
            },
            {
              "position": 2, "rank": 2, "competition_rank": 1,
              "tie_size": 2, "is_tied": true,
              "wallet": "rider-b", "display_name": "Jordan Lee",
              "best_time_seconds": 268, "achieved_at": "2026-08-09T13:05:00Z"
            }
          ],
          "local_legend": {
            "wallet": "rider-b", "completions_count": 9,
            "is_active": true, "is_bootstrap": false, "seat_status": "elected"
          }
        }
        """
        let detail = try decoder.decode(VaultClimbDetail.self, from: Data(payload.utf8))
        XCTAssertEqual(detail.totalCompletions, 37)
        XCTAssertEqual(detail.leaderboard.map(\.sportingRankLabel), ["T-1", "T-1"])
        XCTAssertTrue(detail.leaderboard.allSatisfy { $0.sportingRank == 1 })
        XCTAssertEqual(detail.leaderboard.first?.avatarURL?.host, "example.com")
        XCTAssertEqual(detail.localLegend?.completionsCount, 9)
        XCTAssertEqual(detail.localLegend?.seatStatus, "elected")
    }

    func testVaultEffortHistoryDecodesRideLinksAndPRFacts() throws {
        let payload = """
        {
          "vault_id": 42,
          "vault_name": "Barren Hill Road",
          "efforts": [{
            "id": "effort-1", "ride_id": "ride-1", "time_seconds": 272,
            "avg_power_w": 298, "achieved_at": "2026-08-12T18:24:00Z",
            "is_pr": true, "improvement": 4
          }],
          "total_count": 6,
          "best_time_seconds": 272,
          "total_prs": 3
        }
        """
        let history = try decoder.decode(
            VaultEffortHistoryResponse.self,
            from: Data(payload.utf8)
        )
        XCTAssertEqual(history.totalCount, 6)
        XCTAssertEqual(history.efforts.first?.rideId, "ride-1")
        XCTAssertEqual(history.efforts.first?.isPR, true)
        XCTAssertEqual(history.efforts.first?.improvement, 4)
    }
}
