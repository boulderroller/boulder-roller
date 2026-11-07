import XCTest
@testable import BoulderRoller

final class ClimbPowerTests: XCTestCase {
    private func decode<T: Decodable>(_ type: T.Type, _ json: String) throws -> T {
        let decoder = JSONDecoder()
        decoder.keyDecodingStrategy = .convertFromSnakeCase
        return try decoder.decode(type, from: Data(json.utf8))
    }

    func testLeaderboardRetainsPowerProvenanceRangeAndOptedInWkg() throws {
        let row = try decode(RecordBoardEntry.self, """
        {"rank":1,"wallet":"fixture-rider","power_kind":"estimated",
         "estimated_power_w":278,"estimated_power_range_w":[250,310],"w_per_kg":3.62}
        """)
        let encoded = try XCTUnwrap(JSONSerialization.jsonObject(with: JSONEncoder().encode(row)) as? [String: Any])
        XCTAssertEqual(encoded["powerKind"] as? String, "estimated")
        XCTAssertEqual(encoded["estimatedPowerW"] as? Double, 278)
        XCTAssertEqual(encoded["estimatedPowerRangeW"] as? [Double], [250, 310])
        XCTAssertEqual(encoded["wPerKg"] as? Double, 3.62)
    }

    func testPrivacyRetainsExplicitWkgOptIn() throws {
        let settings = try decode(PrivacySettings.self, """
        {"profileVisibility":"public","defaultRideVisibility":"public",
         "defaultMapVisibility":"hide_start_end","defaultMapHideStartM":200,
         "defaultMapHideEndM":200,"privacyZoneCount":0,"shareWkg":true}
        """)
        let encoded = try XCTUnwrap(JSONSerialization.jsonObject(with: JSONEncoder().encode(settings)) as? [String: Any])
        XCTAssertEqual(encoded["shareWkg"] as? Bool, true)
    }

    private func row(_ fields: String = "") throws -> RecordBoardEntry {
        try decode(RecordBoardEntry.self, "{\"rank\":1,\"wallet\":\"fixture-rider\"\(fields)}")
    }

    func testMeasuredPowerUsesBoltAndLedgerRounding() throws {
        let power = try XCTUnwrap(Format.climbPower(row(
            #", "power_kind":"measured", "avg_power_w":240.5"#
        )))
        XCTAssertEqual(power.text, "⚡ 240 W")
        XCTAssertFalse(power.isEstimated)
        XCTAssertEqual(power.accessibilityLabel, "Measured 240 watts")
        XCTAssertNil(power.range)
        XCTAssertNil(power.wattsPerKg)
    }

    func testEstimateUsesOnlyEstimatedWattsAndSpeaksItsRange() throws {
        let power = try XCTUnwrap(Format.climbPower(row(
            #", "power_kind":"estimated", "avg_power_w":999, "estimated_power_w":278, "estimated_power_range_w":[250.5,309.5]"#
        )))
        XCTAssertEqual(power.text, "≈ 278 W")
        XCTAssertTrue(power.isEstimated)
        XCTAssertFalse(power.text.contains("⚡"))
        XCTAssertEqual(power.range, "250–310 W")
        XCTAssertEqual(power.accessibilityLabel, "Estimated 278 watts, range 250 to 310 watts")
    }

    func testExplicitMeasuredKindNeverFallsBackToAnEstimate() throws {
        XCTAssertNil(Format.climbPower(try row(
            #", "power_kind":"measured", "estimated_power_w":278"#
        )))
        XCTAssertNil(Format.climbPower(try row(
            #", "power_kind":"estimated", "avg_power_w":324"#
        )))
    }

    func testAbsentNullAndUnknownPowerRenderNothing() throws {
        let legacy = try row()
        XCTAssertNil(legacy.powerKind)
        XCTAssertNil(legacy.estimatedPowerW)
        XCTAssertNil(legacy.estimatedPowerRangeW)
        XCTAssertNil(legacy.wPerKg)
        XCTAssertNil(Format.climbPower(legacy))
        XCTAssertNil(Format.climbPower(try row(
            #", "avg_power_w":null, "power_kind":null, "estimated_power_w":null, "estimated_power_range_w":null, "w_per_kg":null"#
        )))
        XCTAssertNil(Format.climbPower(try row(
            #", "power_kind":"future-kind", "avg_power_w":324"#
        )))
        XCTAssertNil(Format.climbPower(try row(#", "avg_power_w":324, "w_per_kg":4.05"#)))
        XCTAssertNil(Format.climbPower(try row(#", "estimated_power_w":278, "estimated_power_range_w":[250,310]"#)))
    }

    func testWkgAppearsOnlyFromTheApiAndNeverFromWeight() throws {
        let shared = try XCTUnwrap(Format.climbPower(row(
            #", "power_kind":"measured", "avg_power_w":324, "w_per_kg":4.05"#
        )))
        XCTAssertEqual(shared.wattsPerKg, "4.05 W/kg")
        XCTAssertEqual(shared.accessibilityLabel, "Measured 324 watts, 4.05 watts per kilogram")
        let unshared = try XCTUnwrap(Format.climbPower(row(
            #", "power_kind":"measured", "avg_power_w":324, "weight_kg":80"#
        )))
        XCTAssertNil(unshared.wattsPerKg)
        XCTAssertFalse(unshared.accessibilityLabel.contains("kilogram"))
        XCTAssertNil(Format.climbPower(try row(#", "w_per_kg":4.05"#)))
        XCTAssertEqual(Precision.wattsPerKg, 2)
    }

    func testInvalidNumbersAndRangesDoNotBecomeDisplayedFacts() throws {
        var invalid = try row(#", "power_kind":"measured", "avg_power_w":324, "w_per_kg":4.05"#)
        invalid.avgPowerW = .infinity
        XCTAssertNil(Format.climbPower(invalid))
        invalid.avgPowerW = -1
        XCTAssertNil(Format.climbPower(invalid))
        invalid.avgPowerW = 324
        invalid.wPerKg = .nan
        XCTAssertNil(Format.climbPower(invalid)?.wattsPerKg)
        for bounds in ["[]", "[250]", "[310,250]", "[-1,310]", "[250,278,310]"] {
            let power = try XCTUnwrap(Format.climbPower(row(
                ", \"power_kind\":\"estimated\", \"estimated_power_w\":278, \"estimated_power_range_w\":\(bounds)"
            )))
            XCTAssertEqual(power.text, "≈ 278 W")
            XCTAssertNil(power.range)
        }
    }

    func testVaultEffortHistorySharesTheSamePowerPresentation() throws {
        let old = try decode(VaultEffortHistoryEntry.self, """
        {"id":"old","time_seconds":281,"avg_power_w":324,"is_pr":false}
        """)
        XCTAssertNil(Format.climbPower(old))
        let measured = try decode(VaultEffortHistoryEntry.self, """
        {"id":"measured","time_seconds":281,"avg_power_w":324,"is_pr":false,"power_kind":"measured","w_per_kg":4.05}
        """)
        XCTAssertEqual(Format.climbPower(measured)?.text, "⚡ 324 W")
        XCTAssertEqual(Format.climbPower(measured)?.wattsPerKg, "4.05 W/kg")
        let estimated = try decode(VaultEffortHistoryEntry.self, """
        {"id":"estimated","time_seconds":281,"is_pr":false,"power_kind":"estimated",
         "estimated_power_w":278,"estimated_power_range_w":[250,310]}
        """)
        XCTAssertEqual(Format.climbPower(estimated)?.text, "≈ 278 W")
        XCTAssertEqual(Format.climbPower(estimated)?.range, "250–310 W")
        let absent = try decode(VaultEffortHistoryEntry.self, """
        {"id":"absent","time_seconds":281,"is_pr":false}
        """)
        XCTAssertNil(Format.climbPower(absent))
    }
}
