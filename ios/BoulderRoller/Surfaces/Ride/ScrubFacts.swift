import Foundation

/// Scrub-the-relief's fact lookup, as pure functions: what may truthfully be
/// said about one moment of a ride. Every fact abstains over sparse or
/// missing evidence — a readout never smears a value across ground it can't
/// see. Extracted from the ride sheet so the abstention policy is testable.
enum ScrubFacts {
    /// Local grade at a point: rise over run across a ±60 m window of the
    /// ride's chosen elevation source (corrected when any exists, device
    /// otherwise — ReliefChart's rule). nil off the distance axis, over
    /// data gaps, or when the window spans less than 20 m of real ground.
    static func gradient(points: [GpsPoint], index: Int) -> Double? {
        guard points.indices.contains(index), points[index].hasVisibleCoordinate,
              let centerD = points[index].distanceM
        else { return nil }
        let elevation = ReliefChart.elevationSource(points: points)
        var lo = index, hi = index
        while lo > 0,
              let d = points[lo - 1].distanceM,
              centerD - d < 60,
              elevation(points[lo - 1]) != nil { lo -= 1 }
        while hi < points.count - 1,
              let d = points[hi + 1].distanceM,
              d - centerD < 60,
              elevation(points[hi + 1]) != nil { hi += 1 }
        guard let d0 = points[lo].distanceM, let d1 = points[hi].distanceM,
              let e0 = elevation(points[lo]),
              let e1 = elevation(points[hi]),
              d1 - d0 >= 20
        else { return nil }
        return (e1 - e0) / (d1 - d0) * 100
    }

    /// Stream value (power, heart rate) at an elapsed offset, accepted only
    /// within 15 s of a real sample — never a value from somewhere else.
    static func streamValue(samples: [RideAnalysisSample], offsetS: Double) -> Double? {
        guard !samples.isEmpty else { return nil }
        let targetMin = offsetS / 60
        var best: RideAnalysisSample?
        var bestDelta = Double.greatestFiniteMagnitude
        for sample in samples {
            let delta = abs(sample.elapsedMinutes - targetMin)
            if delta < bestDelta { bestDelta = delta; best = sample }
        }
        guard bestDelta <= 0.25 else { return nil }
        return best?.value
    }

    /// The readout line: distance, elevation, grade, power, heart rate —
    /// each present only when its evidence is.
    static func facts(
        points: [GpsPoint],
        index: Int,
        powerSamples: [RideAnalysisSample],
        heartRateSamples: [RideAnalysisSample],
        units: UnitSystem
    ) -> [String] {
        guard points.indices.contains(index) else { return [] }
        let point = points[index]
        guard point.hasVisibleCoordinate else { return [] }
        let elevation = ReliefChart.elevationSource(points: points)
        var facts: [String] = []
        if let d = point.distanceM {
            facts.append("\(Format.distance(fromMeters: d, units: units)) \(units.distanceUnit)")
        }
        if let e = elevation(point) {
            facts.append("\(Format.elevation(fromMeters: e, units: units)) \(units.elevationUnit)")
        }
        if let grade = gradient(points: points, index: index) {
            facts.append(Format.grade(grade))
        }
        if let t0 = points.first?.timestamp, let t = point.timestamp {
            let offset = t - t0
            if let power = streamValue(samples: powerSamples, offsetS: offset) {
                facts.append("\(Format.number(power, places: Precision.power)) W")
            }
            if let hr = streamValue(samples: heartRateSamples, offsetS: offset) {
                facts.append("\(Format.number(hr, places: Precision.heartRate)) bpm")
            }
        }
        return facts
    }
}
