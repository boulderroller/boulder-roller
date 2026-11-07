import Foundation
import Testing
@testable import BoulderRoller

/// The units contract (granularity 10): exact base units internally, the
/// account's preference on every rider-visible numeral, and engines that
/// re-derive — never relabel — when the system changes.
struct UnitSystemTests {
    // MARK: Preference mapping

    @Test func preferenceMapsMetricAndDefaultsImperial() {
        #expect(UnitSystem(preferredUnits: "metric") == .metric)
        #expect(UnitSystem(preferredUnits: "imperial") == .imperial)
        #expect(UnitSystem(preferredUnits: nil) == .imperial)
        #expect(UnitSystem(preferredUnits: "furlongs") == .imperial)
    }

    // MARK: Conversions are exact arithmetic

    @Test func conversionsMatchDefinitions() {
        #expect(abs(UnitSystem.imperial.distanceValue(fromMeters: 1609.344) - 1) < 1e-12)
        #expect(abs(UnitSystem.metric.distanceValue(fromMeters: 1000) - 1) < 1e-12)
        #expect(abs(UnitSystem.imperial.elevationValue(fromMeters: 100) - 328.084) < 1e-9)
        #expect(UnitSystem.metric.elevationValue(fromMeters: 100) == 100)
        // 10 m/s = 22.369… mph = 36 km/h.
        #expect(abs(UnitSystem.imperial.speedValue(fromMps: 10) - 22.369_362_921) < 1e-9)
        #expect(abs(UnitSystem.metric.speedValue(fromMps: 10) - 36) < 1e-12)
        #expect(UnitSystem.imperial.temperatureValue(fromCelsius: 0) == 32)
        #expect(UnitSystem.metric.temperatureValue(fromCelsius: 21) == 21)
    }

    @Test func metersRoundTripsThroughDisplayValue() {
        for units in [UnitSystem.imperial, .metric] {
            let display = units.distanceValue(fromMeters: 12_345.6)
            #expect(abs(units.meters(fromDistanceValue: display) - 12_345.6) < 1e-9)
        }
    }

    // MARK: Format strings carry the preference

    @Test func formattingFollowsUnits() {
        #expect(Format.distance(fromMeters: 16_093.44, units: .imperial) == "10.0")
        #expect(Format.distance(fromMeters: 16_093.44, units: .metric) == "16.1")
        #expect(Format.elevation(fromMeters: 1000, units: .imperial) == "3,281")
        #expect(Format.elevation(fromMeters: 1000, units: .metric) == "1,000")
        #expect(Format.speed(fromMps: 10, units: .metric) == "36.0")
        // Absence stays a dash in both systems.
        #expect(Format.distance(fromMeters: nil, units: .metric) == "—")
        #expect(Format.elevation(fromMeters: nil, units: .imperial) == "—")
        #expect(Format.speed(fromMps: nil, units: .imperial) == "—")
    }

    @Test func unitLabelsFollowUnits() {
        #expect(UnitSystem.imperial.distanceUnit == "mi")
        #expect(UnitSystem.metric.distanceUnit == "km")
        #expect(UnitSystem.imperial.elevationUnit == "ft")
        #expect(UnitSystem.metric.elevationUnit == "m")
        #expect(UnitSystem.imperial.speedUnit == "mph")
        #expect(UnitSystem.metric.speedUnit == "km/h")
    }

    // MARK: Splits re-derive per system

    private func track(lengthM: Double, spacingM: Double) -> [GpsPoint] {
        stride(from: 0, through: lengthM, by: spacingM).map { d in
            GpsPoint(
                latitude: 40.0,
                longitude: -75.2,
                elevationM: 100 + d * 0.01,
                elevationCorrectedM: 100 + d * 0.01,
                distanceM: d,
                // 5 m/s steady, so split boundaries interpolate cleanly.
                timestamp: 1_700_000_000 + d / 5
            )
        }
    }

    @Test func splitsUseTheSystemsOwnBoundaries() {
        // 5 km at 5 m/s: three full miles (+ partial), five full kilometers.
        let points = track(lengthM: 5000, spacingM: 25)
        let mileSplits = SplitsEngine.splits(points: points, units: .imperial)
        let kmSplits = SplitsEngine.splits(points: points, units: .metric)

        #expect(mileSplits.filter { $0.distance >= 0.995 }.count == 3)
        #expect(kmSplits.filter { $0.distance >= 0.995 }.count == 5)

        // A full kilometer at 5 m/s takes exactly 200 s = 18 km/h.
        let firstKm = kmSplits[0]
        #expect(abs(firstKm.timeS - 200) < 1)
        #expect(abs((firstKm.speed ?? 0) - 18) < 0.2)
        // 1% grade over 1 km climbs 10 m — climb reads in meters.
        #expect(abs((firstKm.climb ?? 0) - 10) < 0.5)

        // The same ground in imperial: one mile climbs ~16.1 m = ~52.8 ft.
        let firstMile = mileSplits[0]
        #expect(abs((firstMile.climb ?? 0) - 52.8) < 1.5)
    }

    // MARK: Formatter inventory — no raw unit literals outside UnitSystem

    /// Every conversion constant and unit label lives in UnitSystem/Format;
    /// a surface hardcoding one would silently ignore the preference again.
    @Test func riderSurfacesCarryNoRawUnitLiterals() throws {
        let testsDirectory = URL(fileURLWithPath: #filePath).deletingLastPathComponent()
        let appDirectory = testsDirectory
            .deletingLastPathComponent()
            .appendingPathComponent("BoulderRoller", isDirectory: true)
        let roots = ["Surfaces", "Recording", "Components"].map {
            appDirectory.appendingPathComponent($0, isDirectory: true)
        }
        let forbidden = [
            "1609", "3.28084", "2.236", "2.23694", "* 9 / 5",
            "\"mi\"", "\"ft\"", "\"mph\"", "\"km\"", "\"km/h\"",
            " mi\"", " ft\"", " mph\"", " km\"",
        ]
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
                        "raw unit literal \(literal) in \(file.lastPathComponent)"
                    )
                }
            }
        }
    }

    // MARK: The scrub readout speaks the preference

    @Test func scrubFactsSpeakMetric() {
        let dense = (0...20).map { i in
            GpsPoint(
                latitude: 40.0,
                longitude: -75.2,
                elevationM: 100 + Double(i) * 0.6,
                elevationCorrectedM: 100 + Double(i) * 0.6,
                distanceM: Double(i) * 10,
                timestamp: 1_700_000_000 + Double(i)
            )
        }
        let facts = ScrubFacts.facts(
            points: dense,
            index: 10,
            powerSamples: [],
            heartRateSamples: [],
            units: .metric
        )
        #expect(facts.contains { $0.hasSuffix(" km") })
        #expect(facts.contains { $0.hasSuffix(" m") })
    }
}
