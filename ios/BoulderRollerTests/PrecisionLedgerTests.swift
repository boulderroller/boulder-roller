import Foundation
import Testing
@testable import BoulderRoller

/// Metrics are sacred (Tim, 2026-08-21): one precision rule per concept,
/// one formatter path, and no surface may round the same value differently
/// from another. These bind the ledger and the drift cases the fresh-eyes
/// pass caught.
struct PrecisionLedgerTests {
    // MARK: The ledger itself

    @Test func ledgerRulesAreTheRatifiedOnes() {
        #expect(Precision.distance == 1)
        #expect(Precision.elevation == 0)
        #expect(Precision.speed == 1)
        #expect(Precision.grade == 1)
        #expect(Precision.power == 0)
        #expect(Precision.heartRate == 0)
        #expect(Precision.cal == 0)
        #expect(Precision.dung == 1)
    }

    /// The stat grid and the Analysis facts row render one speed the same
    /// way — the 14.5-vs-15 drift can't come back.
    @Test func statGridAndAnalysisAgreeOnSpeed() {
        let mps = 6.482  // 14.5 mph
        let stat = Format.speed(fromMps: mps, units: .imperial)
        let analysis = Format.number(
            RideStreamKind.speed.displayValue(mps, units: .imperial),
            places: RideStreamKind.speed.precision
        )
        #expect(stat == analysis)
        #expect(stat == "14.5")
    }

    @Test func gradeIsOneDecimalEverywhere() {
        #expect(Format.grade(6.74) == "6.7%")
        #expect(Format.grade(12.0) == "12.0%")
        #expect(Format.gradeValue(9.96) == "10.0")
        #expect(Format.grade(nil) == "—")
    }

    @Test func halfEvenRoundingIsTheOneRule() {
        // 240.5 W must not read 241 on one surface and 240 on another.
        #expect(Format.number(240.5, places: Precision.power) == "240")
        #expect(Format.number(241.5, places: Precision.power) == "242")
        #expect(Format.number(12.35, places: 1) == "12.4")  // binary 12.35 > half
        #expect(Format.number(1234.5, places: 0) == "1,234")
    }

    @Test func elevationGroupsThousands() {
        #expect(Format.elevation(fromMeters: 1000, units: .imperial) == "3,281")
        #expect(Format.number(1204, places: Precision.elevation) == "1,204")
    }

    @Test func nonFiniteNeverRendersAsANumber() {
        #expect(Format.number(.nan, places: 1) == "—")
        #expect(Format.number(.infinity, places: 0) == "—")
    }

    // MARK: Durations never lie by zero and roll hours

    @Test func shortDurationNeverShowsZeroForNonzero() {
        #expect(Format.shortDuration(45) == "45 s")
        #expect(Format.shortDuration(0.4) == "1 s")
        #expect(Format.shortDuration(90) == "1 min")
        #expect(Format.shortDuration(3_700) == "1:01")
        #expect(Format.shortDuration(0) == "—")
        #expect(Format.shortDuration(nil) == "—")
    }

    @Test func climbTimeRollsHoursAndKeepsWholeSeconds() {
        #expect(Format.climbTime(272.4) == "4:32")
        #expect(Format.climbTime(272.6) == "4:33")
        #expect(Format.climbTime(3_725) == "1:02:05")
        #expect(Format.clockDuration(3_725) == "1:02:05")
    }

    // MARK: Economic figures through Decimal

    @Test func baseUnitsRenderExactlyWithoutFloat() {
        #expect(Format.baseUnits("8100000001", decimals: Precision.dung) == "8.1")
        #expect(Format.baseUnits("104000000000") == "104")
        // A value binary float cannot hold at base-unit precision.
        #expect(Format.baseUnits("9007199254740993000000000", decimals: 0)
            == "9,007,199,254,740,993")
        #expect(Format.baseUnits(nil) == "0")
        #expect(Format.baseUnits("garbage") == "0")
    }

    // MARK: Source guard — no surface invents its own numeric format

    /// Every numeral with a precision rule goes through Format; an ad-hoc
    /// "%.1f" or a one-off fractionLength in a surface is how two rows end
    /// up rounding one value differently.
    @Test func riderSurfacesCarryNoAdHocNumericFormats() throws {
        let testsDirectory = URL(fileURLWithPath: #filePath).deletingLastPathComponent()
        let appDirectory = testsDirectory
            .deletingLastPathComponent()
            .appendingPathComponent("BoulderRoller", isDirectory: true)
        let roots = ["Surfaces", "Components"].map {
            appDirectory.appendingPathComponent($0, isDirectory: true)
        }
        let forbidden = ["String(format: \"%.", ".formatted(.number.precision"]
        for root in roots {
            let files = FileManager.default
                .enumerator(at: root, includingPropertiesForKeys: nil)?
                .compactMap { $0 as? URL }
                .filter { $0.pathExtension == "swift" } ?? []
            #expect(!files.isEmpty)
            for file in files {
                let source = try String(contentsOf: file, encoding: .utf8)
                for literal in forbidden {
                    #expect(
                        !source.contains(literal),
                        "ad-hoc numeric format \(literal) in \(file.lastPathComponent)"
                    )
                }
            }
        }
    }
}
