import SwiftUI

/// The ride/log trace species: one distance/elevation line with counted
/// sections clipped onto that same line. No decorative or substitute shape.
struct RideSpineData: Codable, Equatable, Sendable {
    struct Point: Codable, Equatable, Sendable {
        let distanceM: Double
        let elevationM: Double
    }
    struct Span: Codable, Equatable, Sendable {
        var climbID: String? = nil
        let startDistanceM: Double
        let endDistanceM: Double
        private enum CodingKeys: String, CodingKey {
            case climbID = "patternId"
            case startDistanceM, endDistanceM
        }
    }
    var runs: [[Point]]
    var spans: [Span]

    static let empty = RideSpineData(runs: [], spans: [])

    static func from(gps: GpsResponse, startedAt: String, climbs: [ClimbPattern]) -> Self {
        let points = gps.gpsPoints
        // A reset or missing distance axis cannot locate a counted span.
        let distances = points.compactMap(\.distanceM)
        guard distances.count == points.count, distances.allSatisfy({ $0.isFinite && $0 >= 0 }),
              zip(distances, distances.dropFirst()).allSatisfy({ $0 <= $1 }),
              (distances.last ?? 0) > 0 else { return .empty }
        let runs = ReliefChart.elevationSegments(points: points).map { run in
            run.filter { $0.x.isFinite && $0.elevation.isFinite }
                .map { Point(distanceM: $0.x, elevationM: $0.elevation) }
        }.filter { $0.count > 1 }
        guard let start = Format.date(from: startedAt)?.timeIntervalSince1970 else {
            return Self(runs: runs, spans: [])
        }
        // Never treat synthesized sample indexes as seconds or use the first
        // visible point as the ride's time origin.
        let timeline = points.compactMap { p -> (Double, Double)? in
            guard p.hasVisibleCoordinate, let t = p.timestamp, t > 100_000_000, t.isFinite, let d = p.distanceM else { return nil }
            return (t - start, d)
        }
        guard timeline.count == points.count,
              zip(timeline, timeline.dropFirst()).allSatisfy({ $0.0 < $1.0 }) else {
            return Self(runs: runs, spans: [])
        }
        func distance(at time: Double) -> Double? {
            guard let first = timeline.first, let last = timeline.last,
                  time >= first.0, time <= last.0 else { return nil }
            for (a, b) in zip(timeline, timeline.dropFirst()) where time <= b.0 {
                return a.1 + (b.1 - a.1) * (time - a.0) / (b.0 - a.0)
            }
            return last.1
        }
        let spans = climbs.compactMap { climb -> Span? in
            guard climb.vaultMatch?.isAuthoritativeCompletion == true,
                  let s = climb.effortStartS, let e = climb.effortEndS, e > s,
                  let d0 = distance(at: s), let d1 = distance(at: e), d1 > d0 else { return nil }
            return Span(climbID: climb.stableId, startDistanceM: d0, endDistanceM: d1)
        }.sorted { $0.startDistanceM < $1.startDistanceM }
        return Self(runs: runs, spans: spans)
    }

    func section(_ span: Span, in run: [Point]) -> [Point] {
        guard let first = run.first, let last = run.last else { return [] }
        let start = max(span.startDistanceM, first.distanceM)
        let end = min(span.endDistanceM, last.distanceM)
        guard start.isFinite, end.isFinite, end > start else { return [] }
        func at(_ d: Double) -> Point {
            for (a, b) in zip(run, run.dropFirst()) where b.distanceM >= d && b.distanceM > a.distanceM {
                return Point(distanceM: d, elevationM: a.elevationM + (b.elevationM - a.elevationM) * (d - a.distanceM) / (b.distanceM - a.distanceM))
            }
            return Point(distanceM: d, elevationM: last.elevationM)
        }
        return [at(start)] + run.filter { $0.distanceM > start && $0.distanceM < end } + [at(end)]
    }
}

struct RideSpine: View {
    let data: RideSpineData
    var drawProgress: Double = 1
    /// Colors are supplied only by the reveal; ordinary callers get cobalt.
    var spanColors: [Color]? = nil
    var spanProgress: [Double]? = nil

    var body: some View {
        GeometryReader { proxy in
            let points = data.runs.flatMap { $0 }
            let maxDistance = points.map(\.distanceM).max() ?? 0
            let low = points.map(\.elevationM).min() ?? 0
            let high = points.map(\.elevationM).max() ?? 0
            if maxDistance > 0 {
                let place: (RideSpineData.Point) -> CGPoint = { point in
                    CGPoint(x: point.distanceM / maxDistance * proxy.size.width,
                            y: proxy.size.height - 6 - (high > low ? (point.elevationM - low) / (high - low) * (proxy.size.height - 12) : 0))
                }
                ZStack {
                    ForEach(Array(data.runs.enumerated()), id: \.offset) { _, run in
                        let line = path(run, place: place)
                        Path { p in
                            p.addPath(line)
                            if let first = run.first, let last = run.last {
                                p.addLine(to: CGPoint(x: place(last).x, y: proxy.size.height))
                                p.addLine(to: CGPoint(x: place(first).x, y: proxy.size.height))
                                p.closeSubpath()
                            }
                        }.fill(Theme.reliefFill.opacity(0.45))
                        line.trim(from: 0, to: drawProgress)
                            .stroke(Theme.ink.opacity(0.8), style: StrokeStyle(lineWidth: 1.2, lineCap: .round, lineJoin: .round))
                        ForEach(Array(data.spans.enumerated()), id: \.offset) { i, span in
                            path(data.section(span, in: run), place: place)
                                .trim(from: 0, to: spanProgress?[safe: i] ?? 1)
                                .stroke(spanColors?[safe: i] ?? Theme.blue, style: StrokeStyle(lineWidth: 1.7, lineCap: .round, lineJoin: .round))
                        }
                    }
                }
            }
        }
        .accessibilityHidden(true)
    }

    private func path(_ points: [RideSpineData.Point], place: (RideSpineData.Point) -> CGPoint) -> Path {
        Path { path in
            for (index, point) in points.enumerated() {
                if index == 0 { path.move(to: place(point)) } else { path.addLine(to: place(point)) }
            }
        }
    }
}

private extension Array {
    subscript(safe index: Int) -> Element? { indices.contains(index) ? self[index] : nil }
}
