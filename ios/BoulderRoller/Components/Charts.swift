import Charts
import SwiftUI

struct RideAnalysisSample: Equatable, Identifiable {
    let elapsedMinutes: Double
    let value: Double
    var id: Double { elapsedMinutes }
}

extension RideStreamResponse {
    func analysisSamples(kind: RideStreamKind, units: UnitSystem) -> [RideAnalysisSample] {
        guard hasSamples else { return [] }
        let dates = timestamps.compactMap { Format.date(from: $0) }
        guard dates.count == timestamps.count, let first = dates.first else { return [] }

        var previous = -Double.infinity
        var samples: [RideAnalysisSample] = []
        for (date, rawValue) in zip(dates, values) {
            let elapsed = date.timeIntervalSince(first) / 60
            guard elapsed.isFinite, rawValue.isFinite, elapsed >= 0, elapsed >= previous else {
                return []
            }
            previous = elapsed
            samples.append(.init(
                elapsedMinutes: elapsed,
                value: kind.displayValue(rawValue, units: units)
            ))
        }
        return samples
    }
}

/// The relief's truth policy, kept as data logic: one elevation source per
/// ride — DEM-corrected wherever any correction exists, the device's own
/// recording otherwise (ratified 2026-08-18: the diary draws its best
/// honest number; strict abstention stays on economic surfaces). Within
/// the chosen source, gaps stay gaps — raw never splices a corrected run.
enum ReliefChart {
    /// One drawable sample: an x-axis value paired with an elevation.
    struct Sample: Equatable {
        let x: Double
        let elevation: Double
    }

    /// The ride's one elevation accessor: corrected when any point carries
    /// a correction, device elevation when none does. Shared by the band,
    /// the scrub readout, and the split climb column so they never disagree.
    static func elevationSource(points: [GpsPoint]) -> (GpsPoint) -> Double? {
        let corrected = points.contains { $0.hasVisibleCoordinate && $0.elevationCorrectedM != nil }
        return { point in
            guard point.hasVisibleCoordinate else { return nil }
            return corrected ? point.elevationCorrectedM : point.elevationM
        }
    }

    /// Contiguous runs of the ride's chosen elevation source. A run breaks
    /// wherever that source is absent, so the drawn line truthfully gaps
    /// instead of splicing across unknown ground.
    static func elevationSegments(points: [GpsPoint]) -> [[Sample]] {
        let axis = xAxis(for: points)
        let elevation = elevationSource(points: points)
        var segments: [[Sample]] = []
        var run: [Sample] = []
        for (x, point) in zip(axis, points) {
            if let value = elevation(point) {
                run.append(Sample(x: x, elevation: value))
            } else if !run.isEmpty {
                segments.append(run)
                run = []
            }
        }
        if !run.isEmpty { segments.append(run) }
        return segments
    }

    /// Monotonic x values per sample: distance, else time offset, else index.
    static func xAxis(for points: [GpsPoint]) -> [Double] {
        let hasDistance = points.contains { ($0.distanceM ?? 0) > 0 }
        if hasDistance {
            var last = 0.0
            return points.map { p in
                if let d = p.distanceM, d > 0 { last = d }
                return last
            }
        }
        let times = points.map { $0.timestamp }
        if let first = times.first ?? nil, times.compactMap({ $0 }).count == points.count {
            return times.map { ($0 ?? first) - first }
        }
        return (0..<points.count).map(Double.init)
    }
}

/// One sample on the analysis stack's shared axis: distance in the
/// account's display units (miles or kilometers).
struct AnalysisPoint: Identifiable {
    let x: Double
    let value: Double
    var id: Double { x }
}

/// The metric chart's plot-area insets (its leading y-axis takes width the
/// band doesn't have). Published so the band above can match — stacked
/// plots must be flush or the shared cursor lies by a few points.
struct AnalysisPlotInsets: Equatable {
    var leading: CGFloat = 0
    var trailing: CGFloat = 0
}

struct AnalysisPlotInsetsKey: PreferenceKey {
    static let defaultValue = AnalysisPlotInsets()
    static func reduce(value: inout AnalysisPlotInsets, nextValue: () -> AnalysisPlotInsets) {
        value = nextValue()
    }
}

/// The analysis stack's context band — Strava's anatomy (elevation above
/// the metric, never a lone hero) drawn with Apple's framework. Counted
/// spans stay blue; corrected-data gaps stay gaps; the platform's
/// chartXSelection is the one scrubber both charts share.
struct ElevationBandChart: View {
    /// Contiguous corrected runs, x and y in display units.
    let runs: [[AnalysisPoint]]
    /// Climb-counted sections of those runs, same axes.
    let countedRuns: [[AnalysisPoint]]
    let domain: ClosedRange<Double>
    @Binding var selection: Double?

    private var yDomain: ClosedRange<Double> {
        let values = runs.flatMap { $0 }.map(\.value)
        guard let lo = values.min(), let hi = values.max(), hi > lo else { return 0...1 }
        let pad = (hi - lo) * 0.08
        return (lo - pad)...(hi + pad)
    }

    var body: some View {
        Chart {
            ForEach(Array(runs.enumerated()), id: \.offset) { index, run in
                ForEach(run) { p in
                    AreaMark(
                        x: .value("Distance", p.x),
                        y: .value("Elevation", p.value),
                        series: .value("Run", "base-\(index)"),
                        stacking: .unstacked
                    )
                    .foregroundStyle(Theme.reliefFill)
                    LineMark(
                        x: .value("Distance", p.x),
                        y: .value("Elevation", p.value),
                        series: .value("Run", "line-\(index)")
                    )
                    .foregroundStyle(Theme.gray3)
                    .lineStyle(.init(lineWidth: 1.5, lineJoin: .round))
                }
            }
            ForEach(Array(countedRuns.enumerated()), id: \.offset) { index, run in
                ForEach(run) { p in
                    AreaMark(
                        x: .value("Distance", p.x),
                        y: .value("Elevation", p.value),
                        series: .value("Run", "counted-\(index)"),
                        stacking: .unstacked
                    )
                    .foregroundStyle(Theme.countedFill)
                    LineMark(
                        x: .value("Distance", p.x),
                        y: .value("Elevation", p.value),
                        series: .value("Run", "counted-line-\(index)")
                    )
                    .foregroundStyle(Theme.blue)
                    .lineStyle(.init(lineWidth: 2.5, lineCap: .round, lineJoin: .round))
                }
            }
            if let selection {
                RuleMark(x: .value("Distance", selection))
                    .foregroundStyle(Theme.gray)
                    .lineStyle(.init(lineWidth: 1))
            }
        }
        .chartXSelection(value: $selection)
        .chartXScale(domain: domain)
        .chartYScale(domain: yDomain)
        .chartXAxis(.hidden)
        .chartYAxis(.hidden)
        .accessibilityLabel("Elevation")
    }
}

/// The analysis stack's metric chart — same distance axis, same scrubber
/// as the elevation band above it.
struct AnalysisMetricChart: View {
    let kind: RideStreamKind
    let samples: [AnalysisPoint]
    let domain: ClosedRange<Double>
    @Binding var selection: Double?

    @Environment(\.units) private var units

    var body: some View {
        Chart {
            ForEach(samples) { sample in
                AreaMark(
                    x: .value("Distance", sample.x),
                    y: .value(kind.title, sample.value),
                    stacking: .unstacked
                )
                .foregroundStyle(
                    .linearGradient(
                        colors: [Theme.blue.opacity(0.28), Theme.blue.opacity(0.02)],
                        startPoint: .top,
                        endPoint: .bottom
                    )
                )
                .interpolationMethod(.linear)
                LineMark(
                    x: .value("Distance", sample.x),
                    y: .value(kind.title, sample.value)
                )
                .foregroundStyle(Theme.blue)
                .lineStyle(.init(lineWidth: 2, lineCap: .round, lineJoin: .round))
                .interpolationMethod(.linear)
            }
            if let selection {
                RuleMark(x: .value("Distance", selection))
                    .foregroundStyle(Theme.gray)
                    .lineStyle(.init(lineWidth: 1))
            }
        }
        .chartXSelection(value: $selection)
        .chartXScale(domain: domain)
        .chartXAxis {
            AxisMarks(values: .automatic(desiredCount: 3)) { value in
                AxisGridLine().foregroundStyle(Theme.separator)
                AxisValueLabel {
                    if let x = value.as(Double.self) {
                        Text("\(Format.number(x, places: 0)) \(units.distanceUnit)")
                    }
                }
                .foregroundStyle(Theme.gray)
            }
        }
        .chartYAxis {
            AxisMarks(position: .leading, values: .automatic(desiredCount: 3)) { value in
                AxisGridLine().foregroundStyle(Theme.separator)
                AxisValueLabel {
                    if let number = value.as(Double.self) {
                        Text(Format.number(number, places: 0))
                    }
                }
                .foregroundStyle(Theme.gray)
            }
        }
        .chartOverlay { proxy in
            GeometryReader { geo in
                Color.clear.preference(
                    key: AnalysisPlotInsetsKey.self,
                    value: proxy.plotFrame.map { anchor in
                        let frame = geo[anchor]
                        return AnalysisPlotInsets(
                            leading: frame.minX,
                            trailing: max(geo.size.width - frame.maxX, 0)
                        )
                    } ?? AnalysisPlotInsets()
                )
            }
        }
        .accessibilityElement(children: .ignore)
        .accessibilityLabel("\(kind.title) over distance")
    }
}

/// The climb sheet's canon profile — the climb's identity object, ratified
/// 2026-09-01 with the portal twin: steepness bands in ladder rungs only
/// (value is luminance, never hue; steeper = brighter), ink silhouette,
/// permanent elevation grid, comparable 4.5x exaggeration so the same
/// gradient is the same visual slope on every climb, content-driven height
/// (the card's shape is the climb's identity), cobalt reserved for the
/// scrub. Terrain personality is the beauty; no smoothing, no invention.
struct CanonProfileView: View {
    let profile: [ElevationProfilePoint]
    /// Compact: bands, silhouette, baseline only — the face without
    /// furniture, for bands and strips. Same comparable slope.
    var compact = false
    /// Live position along the profile (meters from its start). Drawn as the
    /// cobalt marker — you, on the wall — when present.
    var cursorM: Double? = nil

    @Environment(\.units) private var units
    @State private var width: CGFloat = 0
    @State private var scrubX: CGFloat? = nil

    private static let exaggeration: CGFloat = 4.5
    private static let maxPlotHeight: CGFloat = 420
    private static let minPlotHeight: CGFloat = 40
    private static let margin = (top: CGFloat(24), trailing: CGFloat(48), bottom: CGFloat(28), leading: CGFloat(16))

    /// Steepness classes over the ratified ladder, brightest = steepest.
    private static let bandSteps: [(minPct: Double, fill: Color, labelInk: Color)] = [
        (12, Theme.ink, Theme.sheet),
        (9, Theme.gray, Theme.sheet),
        (6, Theme.gray2, Theme.ink),
        (3, Theme.gray3, Theme.ink),
        (-.infinity, Theme.card, Theme.gray),
    ]

    var body: some View {
        Canvas { context, size in
            guard let model = Self.model(profile: profile, width: size.width, units: units, compact: compact) else { return }
            draw(model: model, context: &context, size: size)
        }
        .frame(height: Self.model(profile: profile, width: max(width, 160), units: units, compact: compact)?.viewHeight ?? (compact ? 40 : 112))
        .background(
            GeometryReader { geometry in
                Color.clear
                    .onAppear { width = geometry.size.width }
                    .onChange(of: geometry.size.width) { _, next in width = next }
            }
        )
        .gesture(
            DragGesture(minimumDistance: 0)
                .onChanged { value in if !compact { scrubX = value.location.x } }
                .onEnded { _ in scrubX = nil }
        )
        .accessibilityLabel("Climb profile")
    }

    // MARK: geometry

    private struct Band {
        var startM: Double
        var endM: Double
        var bins: Int
        var gradientPct: Double
        var stepIndex: Int
    }

    private struct Model {
        let points: [ElevationProfilePoint]
        let originM: Double
        let lengthM: Double
        let minElevation: Double
        let plotWidth: CGFloat
        let plotHeight: CGFloat
        let viewHeight: CGFloat
        let baselineY: CGFloat
        let xScale: CGFloat
        let yScale: CGFloat
        let bands: [Band]
        let gridlines: [(y: CGFloat, label: String)]
        let ticks: [(x: CGFloat, label: String)]
        let summit: (x: CGFloat, y: CGFloat, label: String, trailing: Bool)
        let compact: Bool
        let leading: CGFloat

        func x(_ d: Double) -> CGFloat { Self.x(d, originM: originM, xScale: xScale, leading: leading) }
        func y(_ e: Double) -> CGFloat { baselineY - CGFloat(e - minElevation) * yScale }
        static func x(_ d: Double, originM: Double, xScale: CGFloat, leading: CGFloat) -> CGFloat {
            leading + CGFloat(d - originM) * xScale
        }
    }

    private static func interpolate(_ points: [ElevationProfilePoint], at distanceM: Double) -> Double {
        guard let first = points.first, let last = points.last else { return 0 }
        if distanceM <= first.distanceM { return first.elevationM }
        for index in 1..<points.count where points[index].distanceM >= distanceM {
            let a = points[index - 1]
            let b = points[index]
            let span = b.distanceM - a.distanceM
            guard span > 0 else { return b.elevationM }
            let t = (distanceM - a.distanceM) / span
            return a.elevationM + t * (b.elevationM - a.elevationM)
        }
        return last.elevationM
    }

    private static func stepIndex(forGradient pct: Double) -> Int {
        bandSteps.firstIndex { pct >= $0.minPct } ?? (bandSteps.count - 1)
    }

    private static func pickStep(span: Double, candidates: [Double], maxCount: Int) -> Double {
        candidates.first { span / $0 <= Double(maxCount) } ?? candidates[candidates.count - 1]
    }

    private static func model(profile: [ElevationProfilePoint], width: CGFloat, units: UnitSystem, compact: Bool = false) -> Model? {
        let points = profile.filter { $0.distanceM.isFinite && $0.elevationM.isFinite }
        guard points.count >= 2, width >= (compact ? 80 : 160) else { return nil }
        let margin = compact
            ? (top: CGFloat(4), trailing: CGFloat(0), bottom: CGFloat(2), leading: CGFloat(0))
            : Self.margin
        let maxPlot = compact ? CGFloat(56) : maxPlotHeight
        let minPlot = compact ? CGFloat(12) : minPlotHeight
        let originM = points[0].distanceM
        let lengthM = points[points.count - 1].distanceM - originM
        guard lengthM > 0 else { return nil }

        let elevations = points.map(\.elevationM)
        let minElevation = elevations.min()!
        let maxElevation = elevations.max()!
        let elevationSpan = max(maxElevation - minElevation, 1)
        let headroom = max(elevationSpan * 0.05, 2)
        let paddedSpan = elevationSpan + headroom

        let plotWidth = width - margin.leading - margin.trailing
        let xScale = plotWidth / CGFloat(lengthM)
        let yScale = min(exaggeration * xScale, maxPlot / CGFloat(paddedSpan))
        let plotHeight = max(CGFloat(paddedSpan) * yScale, minPlot)
        let viewHeight = margin.top + plotHeight + margin.bottom
        let baselineY = margin.top + plotHeight

        func grade(_ d0: Double, _ d1: Double) -> Double {
            (interpolate(points, at: d1) - interpolate(points, at: d0)) / (d1 - d0) * 100
        }

        // Fixed-distance bins classify steepness; same-class neighbors merge,
        // then single-bin slivers fold into the gradient-closer neighbor so
        // banding reads as real terrain changes, not bin noise.
        let binWidth: Double = lengthM <= 1500 ? 50 : 100
        var bands: [Band] = []
        var d0 = originM
        while d0 < originM + lengthM - 1e-6 {
            let d1 = min(d0 + binWidth, originM + lengthM)
            let pct = grade(d0, d1)
            let step = stepIndex(forGradient: pct)
            if var previous = bands.last, previous.stepIndex == step {
                previous.endM = d1
                previous.bins += 1
                previous.gradientPct = grade(previous.startM, d1)
                bands[bands.count - 1] = previous
            } else {
                bands.append(Band(startM: d0, endM: d1, bins: 1, gradientPct: pct, stepIndex: step))
            }
            d0 = d1
        }
        var guardCount = 0
        while guardCount < 40, bands.count > 1, let sliverIndex = bands.firstIndex(where: { $0.bins == 1 }) {
            guardCount += 1
            let sliver = bands[sliverIndex]
            let leftIndex = sliverIndex > 0 ? sliverIndex - 1 : nil
            let rightIndex = sliverIndex + 1 < bands.count ? sliverIndex + 1 : nil
            let hostIndex: Int
            if let leftIndex, let rightIndex {
                hostIndex = abs(bands[leftIndex].gradientPct - sliver.gradientPct)
                    <= abs(bands[rightIndex].gradientPct - sliver.gradientPct) ? leftIndex : rightIndex
            } else if let leftIndex {
                hostIndex = leftIndex
            } else if let rightIndex {
                hostIndex = rightIndex
            } else {
                break
            }
            bands[hostIndex].startM = min(bands[hostIndex].startM, sliver.startM)
            bands[hostIndex].endM = max(bands[hostIndex].endM, sliver.endM)
            bands[hostIndex].bins += sliver.bins
            bands[hostIndex].gradientPct = grade(bands[hostIndex].startM, bands[hostIndex].endM)
            bands.remove(at: sliverIndex)
            var merged: [Band] = []
            for band in bands {
                if var previous = merged.last, previous.stepIndex == band.stepIndex {
                    previous.endM = band.endM
                    previous.bins += band.bins
                    previous.gradientPct = grade(previous.startM, band.endM)
                    merged[merged.count - 1] = previous
                } else {
                    merged.append(band)
                }
            }
            bands = merged
        }

        // Recessive paper furniture in display units through the one ledger.
        let metersPerElevationUnit = 1 / units.elevationValue(fromMeters: 1)
        let elevationSpanDisplay = units.elevationValue(fromMeters: elevationSpan)
        let elevationStep = pickStep(span: elevationSpanDisplay, candidates: [10, 20, 25, 50, 100, 200, 500], maxCount: 5)
        var gridlines: [(y: CGFloat, label: String)] = []
        var gridValue = (units.elevationValue(fromMeters: minElevation) / elevationStep).rounded(.up) * elevationStep
        while gridValue <= units.elevationValue(fromMeters: maxElevation) {
            let meters = gridValue * metersPerElevationUnit
            let y = baselineY - CGFloat(meters - minElevation) * yScale
            if y > margin.top - 2, y < baselineY - 6 {
                gridlines.append((y, "\(Format.elevation(fromMeters: meters, units: units)) \(units.elevationUnit)"))
            }
            gridValue += elevationStep
        }

        let lengthDisplay = units.distanceValue(fromMeters: lengthM)
        let tickStep = pickStep(span: lengthDisplay, candidates: [0.1, 0.2, 0.25, 0.5, 1, 2, 5], maxCount: 7)
        var ticks: [(x: CGFloat, label: String)] = []
        var tickValue = 0.0
        while tickValue <= lengthDisplay + 1e-9 {
            let xPosition = Model.x(originM + units.meters(fromDistanceValue: tickValue), originM: originM, xScale: xScale, leading: margin.leading)
            let isLast = tickValue + tickStep > lengthDisplay
            let label = tickValue == 0 ? "0" : Format.number(tickValue, places: Precision.distance)
            ticks.append((xPosition, isLast ? "\(label) \(units.distanceUnit)" : label))
            tickValue += tickStep
        }

        let summitIsEnd = points[points.count - 1].elevationM >= points[0].elevationM
        let summitPoint = summitIsEnd ? points[points.count - 1] : points[0]
        let summitX = Model.x(summitPoint.distanceM, originM: originM, xScale: xScale, leading: margin.leading)
        let summit = (
            x: summitX,
            y: baselineY - CGFloat(summitPoint.elevationM - minElevation) * yScale,
            label: "\(Format.elevation(fromMeters: summitPoint.elevationM, units: units)) \(units.elevationUnit)",
            trailing: summitX > margin.leading + plotWidth * 0.8
        )

        return Model(
            points: points,
            originM: originM,
            lengthM: lengthM,
            minElevation: minElevation,
            plotWidth: plotWidth,
            plotHeight: plotHeight,
            viewHeight: viewHeight,
            baselineY: baselineY,
            xScale: xScale,
            yScale: yScale,
            bands: bands,
            gridlines: gridlines,
            ticks: ticks,
            summit: summit,
            compact: compact,
            leading: margin.leading
        )
    }

    // MARK: drawing

    private func draw(model: Model, context: inout GraphicsContext, size: CGSize) {
        let margin = Self.margin
        let plotLeading = model.leading

        for gridline in model.compact ? [] : model.gridlines {
            var line = Path()
            line.move(to: CGPoint(x: margin.leading, y: gridline.y))
            line.addLine(to: CGPoint(x: margin.leading + model.plotWidth, y: gridline.y))
            context.stroke(line, with: .color(Theme.gray2.opacity(0.28)), lineWidth: 1)
            context.draw(
                Text(gridline.label).font(.system(size: 10, design: .monospaced)).foregroundStyle(Theme.gray),
                at: CGPoint(x: margin.leading + model.plotWidth + 6, y: gridline.y),
                anchor: .leading
            )
        }

        for band in model.bands {
            let step = Self.bandSteps[band.stepIndex]
            var fill = Path()
            fill.move(to: CGPoint(x: model.x(band.startM), y: model.baselineY))
            fill.addLine(to: CGPoint(x: model.x(band.startM), y: model.y(Self.interpolate(model.points, at: band.startM))))
            for point in model.points where point.distanceM > band.startM && point.distanceM < band.endM {
                fill.addLine(to: CGPoint(x: model.x(point.distanceM), y: model.y(point.elevationM)))
            }
            fill.addLine(to: CGPoint(x: model.x(band.endM), y: model.y(Self.interpolate(model.points, at: band.endM))))
            fill.addLine(to: CGPoint(x: model.x(band.endM), y: model.baselineY))
            fill.closeSubpath()
            context.fill(fill, with: .color(step.fill))
        }

        for band in model.bands.dropFirst() {
            var seam = Path()
            seam.move(to: CGPoint(x: model.x(band.startM), y: model.y(Self.interpolate(model.points, at: band.startM))))
            seam.addLine(to: CGPoint(x: model.x(band.startM), y: model.baselineY))
            context.stroke(seam, with: .color(Theme.sheet), lineWidth: 1)
        }

        for band in model.bands where !model.compact && CGFloat(band.endM - band.startM) * model.xScale >= 44 {
            let step = Self.bandSteps[band.stepIndex]
            context.draw(
                Text("\(Format.gradeValue(band.gradientPct))%")
                    .font(.system(size: 11, weight: .semibold, design: .monospaced))
                    .foregroundStyle(step.labelInk),
                at: CGPoint(x: model.x((band.startM + band.endM) / 2), y: model.baselineY - 12),
                anchor: .center
            )
        }

        var silhouette = Path()
        silhouette.move(to: CGPoint(x: model.x(model.points[0].distanceM), y: model.y(model.points[0].elevationM)))
        for point in model.points.dropFirst() {
            silhouette.addLine(to: CGPoint(x: model.x(point.distanceM), y: model.y(point.elevationM)))
        }
        context.stroke(
            silhouette, with: .color(Theme.ink),
            style: StrokeStyle(lineWidth: 2, lineCap: .round, lineJoin: .round)
        )

        var baseline = Path()
        baseline.move(to: CGPoint(x: plotLeading, y: model.baselineY))
        baseline.addLine(to: CGPoint(x: plotLeading + model.plotWidth, y: model.baselineY))
        context.stroke(baseline, with: .color(Theme.gray3), lineWidth: 1)

        if let cursorM {
            let clamped = min(max(cursorM, 0), model.lengthM)
            let cx = model.x(model.originM + clamped)
            let cy = model.y(Self.interpolate(model.points, at: model.originM + clamped))
            var hairline = Path()
            hairline.move(to: CGPoint(x: cx, y: cy))
            hairline.addLine(to: CGPoint(x: cx, y: model.baselineY))
            context.stroke(hairline, with: .color(Theme.blue.opacity(0.85)), lineWidth: 1)
            let dot = CGRect(x: cx - 4, y: cy - 4, width: 8, height: 8)
            context.fill(Path(ellipseIn: dot), with: .color(Theme.blue))
            context.stroke(Path(ellipseIn: dot), with: .color(Theme.sheet), lineWidth: 1.5)
        }

        for tick in model.compact ? [] : model.ticks {
            var mark = Path()
            mark.move(to: CGPoint(x: tick.x, y: model.baselineY))
            mark.addLine(to: CGPoint(x: tick.x, y: model.baselineY + 4))
            context.stroke(mark, with: .color(Theme.gray3), lineWidth: 1)
            context.draw(
                Text(tick.label).font(.system(size: 10, design: .monospaced)).foregroundStyle(Theme.gray),
                at: CGPoint(x: tick.x, y: model.baselineY + 14),
                anchor: .center
            )
        }

        if !model.compact {
            context.draw(
                Text(model.summit.label)
                    .font(.system(size: 12, weight: .semibold, design: .monospaced))
                    .foregroundStyle(Theme.ink),
                at: CGPoint(x: model.summit.x, y: model.summit.y - 12),
                anchor: model.summit.trailing ? .trailing : .center
            )
        }

        if !model.compact, let scrubX, scrubX >= margin.leading, scrubX <= margin.leading + model.plotWidth {
            let distance = model.originM + Double((scrubX - margin.leading) / model.xScale)
            let elevation = Self.interpolate(model.points, at: distance)
            let windowStart = max(distance - 25, model.originM)
            let windowEnd = min(distance + 25, model.originM + model.lengthM)
            let localPct = windowEnd > windowStart
                ? (Self.interpolate(model.points, at: windowEnd) - Self.interpolate(model.points, at: windowStart))
                    / (windowEnd - windowStart) * 100
                : 0

            var hairline = Path()
            hairline.move(to: CGPoint(x: scrubX, y: margin.top - 4))
            hairline.addLine(to: CGPoint(x: scrubX, y: model.baselineY))
            context.stroke(hairline, with: .color(Theme.blue.opacity(0.85)), lineWidth: 1)

            let dot = CGRect(x: scrubX - 3.5, y: model.y(elevation) - 3.5, width: 7, height: 7)
            context.fill(Path(ellipseIn: dot), with: .color(Theme.blue))
            context.stroke(Path(ellipseIn: dot), with: .color(Theme.sheet), lineWidth: 1.5)

            let flip = scrubX > margin.leading + model.plotWidth * 0.72
            let readout = Text("\(Format.gradeValue(localPct))%  ")
                .font(.system(size: 11, weight: .semibold, design: .monospaced))
                .foregroundStyle(Theme.ink)
                + Text("\(Format.elevation(fromMeters: elevation, units: units)) \(units.elevationUnit)  ")
                .font(.system(size: 11, design: .monospaced))
                .foregroundStyle(Theme.gray)
                + Text("\(Format.distance(fromMeters: distance - model.originM, units: units)) \(units.distanceUnit)")
                .font(.system(size: 11, design: .monospaced))
                .foregroundStyle(Theme.gray)
            context.draw(
                readout,
                at: CGPoint(x: flip ? scrubX - 8 : scrubX + 8, y: margin.top + 2),
                anchor: flip ? .topTrailing : .topLeading
            )
        }
    }
}
