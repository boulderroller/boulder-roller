import Testing
@testable import BoulderRoller

/// Scrub-the-relief's abstention policy: facts render from dense evidence
/// and abstain over sparse evidence — the readout never smears.
struct ScrubFactsTests {
    private func point(
        d: Double?,
        e: Double?,
        t: Double? = nil
    ) -> GpsPoint {
        GpsPoint(
            latitude: 40.0,
            longitude: -75.2,
            elevationM: e,
            elevationCorrectedM: e,
            distanceM: d,
            timestamp: t
        )
    }

    /// Dense 10 m spacing: grade computes from the ±60 m window.
    @Test func gradientComputesOnDenseTrack() {
        let points = (0...20).map { i in
            point(d: Double(i) * 10, e: 100 + Double(i) * 0.6)
        }
        let grade = ScrubFacts.gradient(points: points, index: 10)
        #expect(grade != nil)
        // 0.6 m rise per 10 m run = 6%.
        #expect(abs(grade! - 6.0) < 0.01)
    }

    /// Kilometer-spaced samples (the render fixture's shape): the window
    /// can't span 20 m of adjacent evidence, so grade abstains.
    @Test func gradientAbstainsOnSparseTrack() {
        let points = (0...6).map { i in
            point(d: Double(i) * 4_000, e: 30 + Double(i) * 10)
        }
        #expect(ScrubFacts.gradient(points: points, index: 3) == nil)
    }

    /// A corrected-elevation gap inside the window truncates it rather than
    /// bridging across unknown ground.
    @Test func gradientStopsAtCorrectionGaps() {
        var points = (0...20).map { i in
            point(d: Double(i) * 10, e: 100 + Double(i) * 1.0)
        }
        points[8] = point(d: 80, e: nil)
        points[12] = point(d: 120, e: nil)
        // Window from index 10 is walled in by the two gaps: 90...110 m,
        // 20 m of ground — still computable, from inside the walls only.
        let grade = ScrubFacts.gradient(points: points, index: 10)
        #expect(grade != nil)
        #expect(abs(grade! - 10.0) < 0.01)
    }

    /// A ride with no correction anywhere reads from device elevation —
    /// the one-source rule (ratified 2026-08-18), never a dead readout.
    @Test func gradientFallsBackToDeviceElevationOnUncorrectedRides() {
        let points = (0...20).map { i in
            GpsPoint(
                latitude: 40.0,
                longitude: -75.2,
                elevationM: 100 + Double(i) * 0.6,
                elevationCorrectedM: nil,
                distanceM: Double(i) * 10,
                timestamp: nil
            )
        }
        let grade = ScrubFacts.gradient(points: points, index: 10)
        #expect(grade != nil)
        #expect(abs(grade! - 6.0) < 0.01)
    }

    /// Stream facts accept a sample within 15 s and refuse one beyond it.
    @Test func streamValueHonorsTolerance() {
        let samples = [
            RideAnalysisSample(elapsedMinutes: 10.0, value: 250),
            RideAnalysisSample(elapsedMinutes: 20.0, value: 180),
        ]
        // 10:10 into the ride — 10 s from a real sample.
        #expect(ScrubFacts.streamValue(samples: samples, offsetS: 610) == 250)
        // 15:00 — five minutes from anything. Abstain.
        #expect(ScrubFacts.streamValue(samples: samples, offsetS: 900) == nil)
    }

    /// The readout composes only the facts whose evidence exists.
    @Test func factsComposeFromAvailableEvidence() {
        let dense = (0...20).map { i in
            point(d: Double(i) * 10, e: 100 + Double(i) * 0.6, t: 1_700_000_000 + Double(i))
        }
        let power = [RideAnalysisSample(elapsedMinutes: 10.0 / 60, value: 240)]
        let facts = ScrubFacts.facts(
            points: dense,
            index: 10,
            powerSamples: power,
            heartRateSamples: [],
            units: .imperial
        )
        // distance, elevation, grade, power — no heart rate, no padding.
        #expect(facts.count == 4)
        #expect(facts[3] == "240 W")
    }

    /// Out-of-range index says nothing at all.
    @Test func factsRefuseOutOfRangeIndex() {
        #expect(ScrubFacts.facts(
            points: [],
            index: 0,
            powerSamples: [],
            heartRateSamples: [],
            units: .imperial
        ).isEmpty)
    }
}
