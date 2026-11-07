import Charts
import SwiftUI

// The ride-literacy engines (Depth Ledger build order, Tim-ratified
// 2026-08-18): splits, time in zones, mean-max power, effort trend, weekly
// log. Every engine abstains over missing or too-sparse evidence — a table
// never smears what the samples can't support.

// MARK: - Splits

struct RideSplit: Identifiable {
    let index: Int
    /// Split length in display units — miles or kilometers (the last split
    /// is usually partial).
    let distance: Double
    let timeS: Double
    /// Climb over the split in display units (ft or m); nil on abstention.
    let climb: Double?
    var id: Int { index }

    /// Split speed in display units (mph or km/h).
    var speed: Double? {
        guard timeS > 0 else { return nil }
        return distance / (timeS / 3600)
    }
}

enum SplitsEngine {
    /// Per-mile or per-kilometer splits from the recorded track, matching
    /// the account's units. Requires the distance axis and per-point
    /// timestamps; returns [] rather than guessing. Climb per split sums
    /// positive corrected deltas only, and abstains (nil) for a split
    /// whose ground lacks corrected elevation.
    static func splits(points: [GpsPoint], units: UnitSystem) -> [RideSplit] {
        guard points.allSatisfy(\.hasVisibleCoordinate) else { return [] }
        let usable = points.filter { $0.distanceM != nil && $0.timestamp != nil }
        guard usable.count >= 2,
              let firstT = usable.first?.timestamp,
              let lastD = usable.last?.distanceM,
              lastD > 400
        else { return [] }

        let splitM = units.distanceUnitMeters
        let elevation = ReliefChart.elevationSource(points: usable)
        var splits: [RideSplit] = []
        var boundaryD = splitM
        var splitStartT = firstT
        var climb = 0.0
        var sawElevation = false
        var previous = usable[0]

        func close(index: Int, atD: Double, atT: Double, fullSplits: Double) {
            splits.append(RideSplit(
                index: index,
                distance: fullSplits,
                timeS: max(atT - splitStartT, 0),
                climb: sawElevation ? units.elevationValue(fromMeters: climb) : nil
            ))
            splitStartT = atT
            climb = 0
            sawElevation = false
        }

        for point in usable.dropFirst() {
            guard let d = point.distanceM, let t = point.timestamp,
                  let prevD = previous.distanceM, let prevT = previous.timestamp,
                  d >= prevD, t >= prevT
            else { continue }

            if let e0 = elevation(previous), let e1 = elevation(point) {
                sawElevation = true
                if e1 > e0 { climb += e1 - e0 }
            }

            while d >= boundaryD, d > prevD {
                // Interpolate the boundary crossing time inside this edge.
                let f = (boundaryD - prevD) / (d - prevD)
                let crossT = prevT + f * (t - prevT)
                close(index: splits.count + 1, atD: boundaryD, atT: crossT, fullSplits: 1)
                boundaryD += splitM
            }
            previous = point
        }

        // The partial tail, if it covers a meaningful tenth of a split.
        if let d = previous.distanceM, let t = previous.timestamp {
            let done = Double(splits.count) * splitM
            let tail = d - done
            if tail > splitM / 10 {
                close(index: splits.count + 1, atD: d, atT: t, fullSplits: tail / splitM)
            }
        }
        return splits
    }
}

/// Strava's split table through our ledger: numerals rounded, speed carried
/// by a quiet blue bar (value is luminance and length, never hue).
struct SplitsSection: View {
    let splits: [RideSplit]

    @Environment(\.units) private var units

    private var maxSpeed: Double {
        splits.compactMap(\.speed).max() ?? 1
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            Text("Splits").sectionHeaderStyle()
            VStack(spacing: 0) {
                HStack {
                    Text(units.distanceUnit.uppercased())
                        .frame(width: 34, alignment: .leading)
                    Text("SPEED")
                    Spacer()
                    Text("TIME").frame(width: 52, alignment: .trailing)
                    Text("CLIMB").frame(width: 56, alignment: .trailing)
                }
                .font(.caption2)
                .kerning(0.6)
                .foregroundStyle(Theme.gray2)
                .padding(.bottom, 6)

                ForEach(splits) { split in
                    HStack(spacing: 8) {
                        Text(split.distance >= 0.995
                            ? "\(split.index)"
                            : Format.number(split.distance, places: Precision.distance))
                            .font(.numeral(.footnote, weight: .medium))
                            .monospacedDigit()
                            .foregroundStyle(Theme.gray)
                            .frame(width: 34, alignment: .leading)

                        GeometryReader { proxy in
                            let fraction = (split.speed ?? 0) / maxSpeed
                            ZStack(alignment: .leading) {
                                Capsule().fill(Theme.reliefFill)
                                Capsule()
                                    .fill(Theme.blue.opacity(0.75))
                                    .frame(width: max(proxy.size.width * fraction, 3))
                            }
                        }
                        .frame(height: 7)

                        Text(Format.climbTime(split.timeS))
                            .font(.numeral(.footnote, weight: .regular))
                            .monospacedDigit()
                            .foregroundStyle(Theme.ink)
                            .frame(width: 52, alignment: .trailing)
                        Text(split.climb.map {
                            "\(Format.number($0, places: Precision.elevation)) \(units.elevationUnit)"
                        } ?? "—")
                            .font(.numeral(.footnote, weight: .regular))
                            .monospacedDigit()
                            .foregroundStyle(split.climb == nil ? Theme.gray2 : Theme.gray)
                            .frame(width: 56, alignment: .trailing)
                    }
                    .frame(minHeight: 26)
                    .accessibilityElement(children: .combine)
                    .accessibilityLabel(
                        "\(units.splitWord) \(split.index): \(Format.climbTime(split.timeS))"
                    )
                }
            }
        }
    }
}

// MARK: - Time in zones

struct PowerZoneShare: Identifiable {
    let zone: Int
    let label: String
    let rangeLabel: String
    let seconds: Double
    var id: Int { zone }
}

extension RideTrainingMetrics {
    var powerZones: [PowerZoneShare] {
        let labels = ["Recovery", "Endurance", "Tempo", "Threshold", "VO2", "Anaerobic", "Sprint"]
        guard let times = powerZoneS, let ranges = powerZoneRangesW else { return [] }
        return zip(times.prefix(7), ranges).enumerated().compactMap { index, row in
            let (seconds, bounds) = row
            guard bounds.count == 2, let lower = bounds[0] else { return nil }
            let range = bounds[1].map { "\(Int(lower))–\(Int($0)) W" } ?? "\(Int(lower))+ W"
            return PowerZoneShare(zone: index + 1, label: labels[index], rangeLabel: range, seconds: seconds)
        }
    }
}

struct ZonesSection: View {
    let zones: [PowerZoneShare]
    let threshold: TrainingEstimate
    let isPending: Bool

    private var maxSeconds: Double { zones.map(\.seconds).max() ?? 1 }

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            ViewThatFits(in: .horizontal) {
                HStack {
                    Text("Power zones").sectionHeaderStyle()
                    Spacer()
                    thresholdLabel
                }
                VStack(alignment: .leading, spacing: 8) {
                    Text("Power zones").sectionHeaderStyle()
                    thresholdLabel
                }
            }
            VStack(spacing: 7) {
                ForEach(zones) { zone in
                    HStack(spacing: 10) {
                        VStack(alignment: .leading, spacing: 0) {
                            Text("Z\(zone.zone) \(zone.label)")
                                .font(.caption)
                                .foregroundStyle(Theme.ink)
                            Text(zone.rangeLabel)
                                .font(.caption2)
                                .monospacedDigit()
                                .foregroundStyle(Theme.gray2)
                        }
                        .frame(width: 118, alignment: .leading)

                        GeometryReader { proxy in
                            ZStack(alignment: .leading) {
                                Capsule().fill(Theme.reliefFill)
                                Capsule()
                                    .fill(Theme.blue.opacity(0.35 + 0.65 * (zone.seconds / maxSeconds)))
                                    .frame(width: max(proxy.size.width * (zone.seconds / maxSeconds), 3))
                            }
                        }
                        .frame(height: 9)

                        Text(Format.shortDuration(zone.seconds))
                            .font(.numeral(.caption, weight: .regular))
                            .monospacedDigit()
                            .foregroundStyle(Theme.gray)
                            .frame(width: 52, alignment: .trailing)
                    }
                    .accessibilityElement(children: .combine)
                }
            }
        }
    }

    private var thresholdLabel: some View {
        Group {
            if threshold.estimate {
                HStack(alignment: .firstTextBaseline, spacing: 0) {
                    Text("Threshold ")
                    EstimatedValue(
                        presentation: EstimatePresentation(
                            value: threshold.value,
                            estimate: threshold.estimate,
                            basis: threshold.basis,
                            range: threshold.range,
                            valueSuffix: isPending ? " · Pending" : "",
                            format: { Format.threshold(Int($0)) }
                        ),
                        markFont: .numeral(.caption, weight: .regular),
                        markColor: Theme.gray2
                    ) {
                        Text("\(Format.threshold(Int(threshold.value)))\(isPending ? " · Pending" : "")")
                    }
                }
            } else {
                Text("Threshold \(Format.threshold(Int(threshold.value)))\(isPending ? " · Pending" : "")")
            }
        }
        .font(.numeral(.caption, weight: .regular))
        .monospacedDigit()
        .foregroundStyle(Theme.gray2)
    }
}

// MARK: - Mean-max power

struct MeanMaxPoint: Identifiable {
    let durationS: Double
    let label: String
    let watts: Double
    var id: Double { durationS }
}

extension RideTrainingMetrics {
    var bestEfforts: [MeanMaxPoint] {
        guard let durations = powerCurveS, let watts = powerCurveW else { return [] }
        return [(60.0, "1 min"), (300.0, "5 min"), (1200.0, "20 min")].compactMap { duration, label in
            guard let index = durations.firstIndex(of: duration), index < watts.count,
                  let power = watts[index] else { return nil }
            return MeanMaxPoint(durationS: duration, label: label, watts: power)
        }
    }
}

struct BestEffortsRow: View {
    let efforts: [MeanMaxPoint]

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            Text("Best efforts").sectionHeaderStyle()
            HStack(spacing: 22) {
                ForEach(efforts) { effort in
                    VStack(alignment: .leading, spacing: 2) {
                        Text(effort.label)
                            .font(.caption)
                            .foregroundStyle(Theme.gray)
                        StatValueText(
                            value: Format.number(effort.watts, places: Precision.power),
                            unit: "W"
                        )
                    }
                    .accessibilityElement(children: .combine)
                }
            }
        }
    }
}

// MARK: - Climb effort trend

/// Your times on this hill, drawn — lower is better, so the axis is
/// reversed and the best effort carries the one blue point.
struct EffortTrendChart: View {
    struct Point: Identifiable {
        let date: Date
        let timeS: Double
        let isPR: Bool
        var id: Date { date }
    }

    let points: [Point]

    private var domain: [Double] {
        let values = points.map(\.timeS)
        let lo = values.min() ?? 0
        let hi = values.max() ?? 1
        let pad = max((hi - lo) * 0.15, 1)
        return [hi + pad, max(lo - pad, 0)] // reversed: faster sits higher
    }

    var body: some View {
        Chart {
            ForEach(points) { point in
                LineMark(
                    x: .value("Date", point.date),
                    y: .value("Time", point.timeS)
                )
                .foregroundStyle(Theme.gray3)
                .lineStyle(.init(lineWidth: 1.5, lineJoin: .round))
                PointMark(
                    x: .value("Date", point.date),
                    y: .value("Time", point.timeS)
                )
                .foregroundStyle(point.isPR ? Theme.blue : Theme.gray)
                .symbolSize(point.isPR ? 52 : 26)
            }
        }
        .chartYScale(domain: domain)
        .chartYAxis {
            AxisMarks(position: .leading, values: .automatic(desiredCount: 3)) { value in
                AxisGridLine().foregroundStyle(Theme.separator)
                AxisValueLabel {
                    if let seconds = value.as(Double.self) {
                        Text(Format.climbTime(seconds))
                    }
                }
                .foregroundStyle(Theme.gray)
            }
        }
        .chartXAxis {
            AxisMarks(values: .automatic(desiredCount: 3)) { _ in
                AxisGridLine().foregroundStyle(Theme.separator)
                AxisValueLabel()
                    .foregroundStyle(Theme.gray)
            }
        }
        .accessibilityLabel("Your times on this climb over time")
    }
}

// MARK: - Weekly training log

struct TrainingWeek: Decodable, Identifiable, Sendable {
    let weekStart: Date
    let distanceM: Double?
    let durationS: Double?
    let climbM: Double?
    let partial: Bool
    var id: Date { weekStart }

    enum CodingKeys: String, CodingKey { case weekStart, distanceM, durationS, climbM, partial }
    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        let raw = try c.decode(String.self, forKey: .weekStart)
        let format = DateFormatter()
        format.locale = Locale(identifier: "en_US_POSIX")
        format.dateFormat = "yyyy-MM-dd"
        guard let date = format.date(from: raw) else {
            throw DecodingError.dataCorruptedError(forKey: .weekStart, in: c, debugDescription: "Invalid training week")
        }
        weekStart = date
        distanceM = try c.decodeIfPresent(Double.self, forKey: .distanceM)
        durationS = try c.decodeIfPresent(Double.self, forKey: .durationS)
        climbM = try c.decodeIfPresent(Double.self, forKey: .climbM)
        partial = try c.decode(Bool.self, forKey: .partial)
    }
}

struct TrainingLogSection: View {
    let weeks: [TrainingWeek]

    @Environment(\.units) private var units

    private var thisWeek: TrainingWeek? { weeks.last }

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            SectionHeader(title: weeks.contains(where: \.partial) ? "Last 12 Weeks ≈" : "Last 12 Weeks")
            VStack(alignment: .leading, spacing: 12) {
                if let week = thisWeek {
                    HStack(spacing: 20) {
                        fact(
                            "This week",
                            Format.distance(fromMeters: week.distanceM, units: units),
                            units.distanceUnit
                        )
                        fact("Time", Format.shortDuration(week.durationS), nil)
                        fact(
                            "Climbing",
                            Format.elevation(fromMeters: week.climbM, units: units),
                            units.elevationUnit
                        )
                    }
                }
                Chart(weeks) { week in
                    if let distance = week.distanceM {
                    BarMark(
                        x: .value("Week", week.weekStart, unit: .weekOfYear),
                        y: .value(
                            units.distanceWord,
                            units.distanceValue(fromMeters: distance)
                        )
                    )
                    .foregroundStyle(
                        week.id == thisWeek?.id ? Theme.blue : Theme.blue.opacity(0.45)
                    )
                    .cornerRadius(2)
                    }
                }
                .chartXAxis {
                    AxisMarks(values: .automatic(desiredCount: 3)) { _ in
                        AxisValueLabel(format: .dateTime.month(.abbreviated).day())
                            .foregroundStyle(Theme.gray)
                    }
                }
                .chartYAxis {
                    AxisMarks(position: .leading, values: .automatic(desiredCount: 3)) { value in
                        AxisGridLine().foregroundStyle(Theme.separator)
                        AxisValueLabel().foregroundStyle(Theme.gray)
                    }
                }
                .frame(height: 110)
            }
            .padding(14)
            .background(Theme.card)
            .clipShape(RoundedRectangle(cornerRadius: Theme.cardRadius, style: .continuous))
        }
    }

    private func fact(_ label: String, _ value: String, _ unit: String?) -> some View {
        VStack(alignment: .leading, spacing: 2) {
            Text(label)
                .font(.caption)
                .foregroundStyle(Theme.gray)
            StatValueText(value: value, unit: unit, valueFont: .numeral(.subheadline))
        }
        .accessibilityElement(children: .combine)
    }
}
