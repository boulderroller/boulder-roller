import MapKit
import SwiftUI
import UniformTypeIdentifiers

/// Surface 4 — Ride detail: Strava's mobile anatomy at 95%; the 5% is ours —
/// counted spans tinted blue, canon grade subtitles, per-climb CAL. The map
/// and photos lead (ratified 2026-08-17); the analysis stack below follows
/// Strava's anatomy through Apple's framework — elevation context band over
/// the metric chart, one distance axis, one native scrubber.
///
/// Pushed on the content spine (sheets are for tasks and rooms; drilling
/// into content is hierarchy — Tim, 2026-08-17). Task sheets it presents
/// (edit, privacy, export) stay sheets.
struct RideDetailView: View {
    let rideId: String
    private let loadsRemote: Bool
    @Environment(\.dismiss) private var dismiss
    @Environment(AppSession.self) private var session
    @Environment(\.dynamicTypeSize) private var dynamicTypeSize
    @Environment(\.units) private var units

    @State private var detail: RideDetailResponse?
    @State private var authoritativeSpine: RideSpineData?
    @State private var spineOwner: RecordingOwner?
    @State private var gps: GpsResponse?
    @State private var climbs: [ClimbPattern] = []
    @State private var streams: [RideStreamKind: RideStreamResponse] = [:]
    @State private var selectedStreamKind: RideStreamKind = .power
    @State private var selectedClimbId: String?
    @State private var showMapViewer = false
    @State private var showPrivacyEditor = false
    @State private var showRideEditor = false
    @State private var showDeleteConfirmation = false
    @State private var isDeleting = false
    @State private var isExporting = false
    @State private var exportDocument: RideFileDocument?
    @State private var exportFileName = "Ride.fit"
    @State private var exportFileType = "fit"
    @State private var showFileExporter = false
    @State private var alertMessage: String?
    @State private var dismissAfterAlert = false
    @State private var isInitialLoading: Bool
    @State private var loadFailed = false
    /// The analysis stack's one scrubber: selected distance in display
    /// units, set by the platform's chartXSelection while a finger is down
    /// on either chart.
    @State private var selectionX: Double?
    @State private var showShareCard = false
    /// Full-screen photo viewer: the tapped band index, nil when closed.
    @State private var lightboxIndex: Int?
    /// The metric plot's measured insets; the band matches them so the
    /// stacked plots stay flush and the shared cursor aligns exactly.
    @State private var plotInsets = AnalysisPlotInsets()

    init(
        rideId: String,
        initialDetail: RideDetailResponse? = nil,
        initialGPS: GpsResponse? = nil,
        initialClimbs: [ClimbPattern] = [],
        initialStreams: [RideStreamKind: RideStreamResponse] = [:]
    ) {
        self.rideId = rideId
        loadsRemote = initialDetail == nil
        _detail = State(initialValue: initialDetail)
        _gps = State(initialValue: initialGPS)
        _climbs = State(initialValue: initialClimbs)
        _streams = State(initialValue: initialStreams)
        _selectedStreamKind = State(initialValue: initialStreams[.power] != nil
            ? .power
            : initialStreams.keys.sorted { $0.rawValue < $1.rawValue }.first ?? .power)
        _isInitialLoading = State(initialValue: initialDetail == nil)
    }

    @ViewBuilder private var revealFigures: some View {
        if let ride, !loadsRemote || (isOwnRide && spineOwner != nil && spineOwner == session.currentUser.map(RecordingOwner.init(user:))) {
            VStack(spacing: 0) {
                if let cal = ride.calEarned, cal > 0 {
                    HStack {
                        Text("Ride CAL").foregroundStyle(Theme.gray)
                        Spacer()
                        Text("\(Format.amount(cal)) CAL").foregroundStyle(Theme.ink)
                        if ride.finalizedAt == nil { Text("pending").font(.caption).foregroundStyle(Theme.gray) }
                    }.font(.body).frame(minHeight: 44).accessibilityElement(children: .combine)
                }
                ForEach(climbs.filter { $0.vaultMatch?.yourRank != nil }, id: \.stableId) { climb in
                    if let rank = climb.vaultMatch?.yourRank, (1...10).contains(rank) {
                        HStack {
                            Text(climb.shownName).foregroundStyle(Theme.gray)
                            Spacer()
                            RankMark(rank: rank, size: 22)
                            if let time = climb.vaultMatch?.yourTime {
                                Text(Format.climbTime(time)).foregroundStyle(Theme.ink)
                            }
                        }.font(.body).frame(minHeight: 44).accessibilityElement(children: .combine)
                    }
                }
            }.padding(.horizontal, Theme.margin)
        }
    }

    private var rideSpine: RideSpineData {
        if loadsRemote {
            guard isOwnRide, let spineOwner,
                  spineOwner == session.currentUser.map(RecordingOwner.init(user:))
            else { return .empty }
            return authoritativeSpine ?? .empty
        }
        guard let ride else { return .empty }
        if let profile = ride.elevationProfile {
            return RideSpineData(runs: [profile], spans: ride.countedSpans ?? [])
        }
        guard let gps else { return .empty }
        return RideSpineData.from(gps: gps, startedAt: ride.startedAt, climbs: climbs)
    }

    private var ride: Ride? { detail?.ride }

    /// Owner-only truth for the audience row: the server's resolved decision,
    /// never inferred client-side.
    private var isOwnRide: Bool {
        ride?.privacy?.isOwner == true || ride?.isOwner == true
    }

    var body: some View {
        ZStack {
            Theme.sheet.ignoresSafeArea()
            if isInitialLoading, detail == nil {
                    ProgressView()
                        .controlSize(.large)
                        .accessibilityLabel("Loading ride")
                } else if loadFailed, detail == nil {
                    VStack {
                        UnavailableCard(text: "Boulder Roller couldn’t load this ride.") {
                            Task { await load() }
                        }
                        Spacer()
                    }
                    .padding(.horizontal, Theme.margin)
                    .padding(.top, 22)
                } else {
                    ScrollView {
                        VStack(alignment: .leading, spacing: 0) {
                            riderAndDate
                            RideSpine(data: rideSpine)
                                .frame(height: 84)
                                .padding(.horizontal, Theme.margin)
                                .padding(.bottom, 18)
                            revealFigures
                            mapBand
                            photoBand
                            stats
                            conditionsBlock
                            notesBlock
                            analysis
                            lapsBlock
                            splitsBlock
                            zonesBlock
                            bestEffortsBlock
                            climbList
                            privacyRows
                        }
                        .padding(.bottom, 30)
                    }
                }
            }
        .navigationTitle(displayTitle)
        .navigationBarTitleDisplayMode(.inline)
        .toolbar { toolbarContent }
        .navigationDestination(item: $selectedClimbId) { climbId in
            ClimbDetailView(climbId: climbId)
        }
        .fullScreenCover(item: Binding(
            get: { lightboxIndex.map(PhotoLightboxSelection.init(index:)) },
            set: { lightboxIndex = $0?.index }
        )) { selection in
            PhotoLightboxView(photos: sortedPhotos, initialIndex: selection.index)
        }
        .sheet(isPresented: $showShareCard) {
            ShareCardView(
                title: displayTitle,
                dateLine: Format.rideTimestamp(ride?.startedAt),
                distance: Format.distance(fromMeters: ride?.distanceM, units: units),
                speed: ride?.trainingMetrics?.avgSpeedMps.map { Format.speed(fromMps: $0, units: units) },
                climbing: Format.elevation(fromMeters: ride?.shownElevationM, units: units),
                time: Format.shortDuration(ride?.durationS),
                fragments: routeFragments,
                units: units
            )
            .presentationCornerRadius(Theme.crown)
        }
        .fullScreenCover(isPresented: $showMapViewer) {
            MapViewerView(
                fragments: routeFragments,
                title: Format.displayRideTitle(
                    ride?.title,
                    startedAtISO: ride?.startedAt,
                    placeLabel: ride?.routePreview?.placeLabel
                ),
                subtitle: nil,
                destinationClimbId: nil
            )
        }
        .sheet(isPresented: $showPrivacyEditor) {
            if let privacy = ride?.privacy,
               let publication = RidePublicationSettings(state: privacy)
            {
                RidePrivacyEditView(
                    initial: publication,
                    apply: { selected in await applyPrivacy(selected) }
                )
                .presentationCornerRadius(Theme.crown)
            }
        }
        .sheet(isPresented: $showRideEditor) {
            if let ride {
                RideEditView(ride: ride) {
                    await load()
                }
                .presentationCornerRadius(Theme.crown)
            }
        }
        .confirmationDialog(
            "Delete Ride?",
            isPresented: $showDeleteConfirmation,
            titleVisibility: .visible
        ) {
            Button("Delete Ride", role: .destructive) {
                Task { await deleteRide() }
            }
            Button("Cancel", role: .cancel) {}
        } message: {
            Text("This permanently deletes the ride, its photos, and Boulder Roller’s local copy on this iPhone.")
        }
        .fileExporter(
            isPresented: $showFileExporter,
            document: exportDocument,
            contentType: RideFileDocument.contentType(for: exportFileType),
            defaultFilename: exportFileName
        ) { result in
            if case let .failure(error) = result {
                alertMessage = error.localizedDescription
            }
            exportDocument = nil
        }
        .alert("Ride", isPresented: Binding(
            get: { alertMessage != nil },
            set: { if !$0 { alertMessage = nil } }
        )) {
            Button("OK") {
                alertMessage = nil
                if dismissAfterAlert {
                    dismissAfterAlert = false
                    dismiss()
                }
            }
        } message: {
            Text(alertMessage ?? "")
        }
        .task { await load() }
    }

    private var displayTitle: String {
        // No title until the ride exists: the hour-of-day fallback must not
        // invent "Lunch Ride" over a spinner (fresh-eyes 2026-08-21).
        guard let ride else { return "" }
        return Format.displayRideTitle(
            ride.title,
            startedAtISO: ride.startedAt,
            placeLabel: ride.routePreview?.placeLabel
        )
    }

    private var routeFragments: [[CLLocationCoordinate2D]] {
        if let gps { return RouteGeometry.fragments(from: gps) }
        return RouteGeometry.fragments(from: ride?.routePreview)
    }

    @ToolbarContentBuilder
    private var toolbarContent: some ToolbarContent {
        ToolbarItemGroup(placement: .topBarTrailing) {
            Menu {
                if let shareURL {
                    ShareLink(item: shareURL) {
                        Label("Share Ride", systemImage: "square.and.arrow.up")
                    }
                }
                if !routeFragments.isEmpty {
                    Button("Share Card", systemImage: "photo") {
                        showShareCard = true
                    }
                }
                if isOwnRide {
                    Button("Edit Ride", systemImage: "pencil") {
                        showRideEditor = true
                    }
                    Button("Ride Privacy", systemImage: "person.2") {
                        showPrivacyEditor = true
                    }
                    Button("Export Original File", systemImage: "arrow.down.doc") {
                        Task { await exportOriginalRide() }
                    }
                    .disabled(isExporting || isDeleting)
                    Divider()
                    Button("Delete Ride", systemImage: "trash", role: .destructive) {
                        showDeleteConfirmation = true
                    }
                    .disabled(isDeleting)
                }
            } label: {
                Label("Ride actions", systemImage: "ellipsis")
            }
        }
    }

    private var shareURL: URL? {
        guard ride?.privacy?.visibility != .onlyYou else { return nil }
        return URL(string: "\(AppConfig.portalBaseURL)/rides/\(rideId)")
    }

    /// Every ride page leads with its athlete (Strava's social header),
    /// privacy-projected server-side; own rides fall back to the session
    /// identity when the projection is unavailable.
    private var riderAndDate: some View {
        let rider = detail?.rider
        let name = rider?.shownName
            ?? (isOwnRide ? session.currentUser?.shownName : nil)
            ?? "Rider"
        return HStack(spacing: 10) {
            AvatarView(name: name, url: rider?.avatarURL, size: 34)
            VStack(alignment: .leading, spacing: 1) {
                Text(name)
                    .font(.subheadline.weight(.semibold))
                    .foregroundStyle(Theme.ink)
                Text(headerSubtitle)
                    .font(.caption)
                    .foregroundStyle(Theme.gray)
                    .lineLimit(dynamicTypeSize.isAccessibilitySize ? nil : 2)
            }
            Spacer(minLength: 0)
        }
        .padding(.horizontal, 20)
        .padding(.vertical, 12)
    }

    private var sortedPhotos: [RideMedia] {
        (ride?.media ?? [])
            .filter { $0.moderationState == "visible" && $0.url != nil }
            .sorted { lhs, rhs in
                if lhs.role == "cover", rhs.role != "cover" { return true }
                if rhs.role == "cover", lhs.role != "cover" { return false }
                return lhs.sortOrder < rhs.sortOrder
            }
    }

    @ViewBuilder
    private var photoBand: some View {
        let photos = sortedPhotos
        if !photos.isEmpty {
            TabView {
                ForEach(Array(photos.enumerated()), id: \.element.id) { index, photo in
                    // Tap opens the photo full screen (Strava precedent);
                    // the band itself stays a paging strip.
                    Button {
                        lightboxIndex = index
                    } label: {
                        RideMediaImage(url: photo.url.flatMap(URL.init))
                            .frame(maxWidth: .infinity)
                            .frame(height: 248)
                            .clipped()
                            .contentShape(Rectangle())
                    }
                    .buttonStyle(.plain)
                    .accessibilityLabel(photo.role == "cover" ? "Cover photo" : "Ride photo")
                }
            }
            .frame(height: 248)
            .tabViewStyle(.page(indexDisplayMode: photos.count > 1 ? .automatic : .never))
        }
    }

    @ViewBuilder
    private var notesBlock: some View {
        if let notes = ride?.description?.trimmingCharacters(in: .whitespacesAndNewlines),
           !notes.isEmpty
        {
            Text(notes)
                .font(.body)
                .foregroundStyle(Theme.ink)
                .fixedSize(horizontal: false, vertical: true)
                .padding(.horizontal, 20)
                .padding(.vertical, 16)
                .frame(maxWidth: .infinity, alignment: .leading)
                .overlay(alignment: .bottom) {
                    Rectangle().fill(Theme.separator).frame(height: 0.5)
                }
        }
    }

    private var headerSubtitle: String {
        var parts = [Format.rideTimestamp(ride?.startedAt)]
        if let place = ride?.routePreview?.placeLabel, !place.isEmpty { parts.append(place) }
        return parts.filter { !$0.isEmpty }.joined(separator: " · ")
    }

    @ViewBuilder
    private var mapBand: some View {
        let fragments = routeFragments
        if !fragments.isEmpty {
            Button {
                showMapViewer = true
            } label: {
                RouteMapSnapshot(
                    fragments: fragments,
                    markerCoordinate: scrubCoordinate
                )
                .frame(height: 168)
            }
            .buttonStyle(.plain)
            .accessibilityLabel("Ride map")
        }
    }

    private struct RideMetric: Identifiable {
        let label: String
        let value: String
        let unit: String?
        var estimate: EstimatePresentation? = nil
        var id: String { label }
    }

    private var rideMetrics: [RideMetric] {
        guard let ride else { return [] }
        var values: [RideMetric] = []
        if let distance = ride.distanceM {
            values.append(.init(
                label: "Distance",
                value: Format.distance(fromMeters: distance, units: units),
                unit: units.distanceUnit
            ))
        }
        if let duration = ride.trainingMetrics?.movingS ?? ride.movingTimeS {
            values.append(.init(label: "Moving time", value: Format.clockDuration(duration), unit: nil))
        }
        if let speed = ride.trainingMetrics?.avgSpeedMps {
            values.append(.init(
                label: "Avg speed",
                value: Format.speed(fromMps: speed, units: units),
                unit: units.speedUnit
            ))
        }
        if let elevation = ride.shownElevationM {
            values.append(.init(
                label: "Elevation",
                value: Format.elevation(fromMeters: elevation, units: units),
                unit: units.elevationUnit
            ))
        }
        if let power = ride.avgPowerW {
            values.append(.init(label: "Avg power", value: Format.amount(power), unit: "W"))
        }
        if let weighted = ride.normalizedPowerW {
            values.append(.init(label: "Weighted power", value: Format.amount(weighted), unit: "W"))
        }
        if let heartRate = ride.avgHrBpm {
            values.append(.init(label: "Avg heart rate", value: Format.amount(heartRate), unit: "bpm"))
        }
        if let tss = ride.tss {
            values.append(.init(
                label: "Training stress",
                value: "\(Format.amount(tss))\(ride.thresholdTrainingState == "pending" ? " · Pending" : "")",
                unit: nil,
                estimate: ride.trainingMetrics?.loadDisclosure(value: tss, isPending: ride.thresholdTrainingState == "pending")
            ))
        }
        if let effort = ride.perceivedExertion {
            values.append(.init(label: "Effort", value: "\(effort)", unit: "/ 10"))
        }
        if let balance = ride.powerBalance,
           let left = balance.leftPct, let right = balance.rightPct
        {
            values.append(.init(
                label: "L/R balance",
                value: "\(Format.number(left, places: 0))/\(Format.number(right, places: 0))",
                unit: nil
            ))
        }
        return values
    }

    /// Conditions are context, not performance: one quiet gray line under
    /// the stat grid, never peer cells beside training numbers.
    private var conditionsLine: String? {
        var parts: [String] = []
        if let temp = ride?.weatherTempC {
            parts.append(
                Format.number(units.temperatureValue(fromCelsius: temp), places: Precision.temperature)
                    + units.temperatureUnit
            )
        }
        if let wind = ride?.weatherWindMps {
            parts.append(
                "\(Format.number(units.speedValue(fromMps: wind), places: 0)) \(units.speedUnit) wind"
            )
        }
        return parts.isEmpty ? nil : parts.joined(separator: " · ")
    }

    @ViewBuilder
    private var conditionsBlock: some View {
        if let line = conditionsLine {
            Text(line)
                .font(.caption)
                .monospacedDigit()
                .foregroundStyle(Theme.gray)
                .padding(.horizontal, 20)
                .padding(.top, 10)
        }
    }

    private var stats: some View {
        LazyVGrid(
            columns: [GridItem(.adaptive(
                minimum: dynamicTypeSize.isAccessibilitySize ? 220 : 96,
                maximum: .infinity
            ), alignment: .leading)],
            alignment: .leading,
            spacing: 16
        ) {
            ForEach(rideMetrics) { metric in
                VStack(alignment: .leading, spacing: 3) {
                    Text(metric.label)
                        .font(.caption)
                        .foregroundStyle(Theme.gray)
                    if let estimate = metric.estimate {
                        EstimatedValue(presentation: estimate) {
                            StatValueText(value: metric.value, unit: metric.unit, valueFont: .numeral(.body))
                        }
                    } else {
                        StatValueText(value: metric.value, unit: metric.unit, valueFont: .numeral(.body))
                    }
                }
                .accessibilityElement(children: metric.estimate?.isEstimate == true ? .contain : .combine)
            }
        }
        .padding(.horizontal, 20)
        .padding(.vertical, 16)
        .overlay(alignment: .bottom) {
            Rectangle().fill(Theme.separator).frame(height: 0.5)
        }
    }

    // MARK: The analysis stack — Strava's anatomy (elevation context band
    // above the metric chart, one distance axis, one scrubber) drawn with
    // Apple's framework (Swift Charts + chartXSelection).

    private var hasDistanceAxis: Bool {
        gps?.gpsPoints.contains { ($0.distanceM ?? 0) > 0 } == true
    }

    private var analysisDomain: ClosedRange<Double>? {
        guard let maxM = gps?.gpsPoints.compactMap(\.distanceM).max(), maxM > 0
        else { return nil }
        return 0...units.distanceValue(fromMeters: maxM)
    }

    /// Elevation runs on the shared axis (display units), drawn from the
    /// ride's chosen source (ReliefChart's rule). Gaps stay gaps.
    private var elevationRuns: [[AnalysisPoint]] {
        guard let gps, hasDistanceAxis else { return [] }
        return ReliefChart.elevationSegments(points: gps.gpsPoints)
            .map { run in
                run.map {
                    AnalysisPoint(
                        x: units.distanceValue(fromMeters: $0.x),
                        value: units.elevationValue(fromMeters: $0.elevation)
                    )
                }
            }
            .filter { $0.count >= 2 }
    }

    /// Climb-counted sections of the elevation runs, clipped so a data gap
    /// inside a climb stays a gap.
    private var countedRuns: [[AnalysisPoint]] {
        let runs = elevationRuns
        guard !runs.isEmpty else { return [] }
        let timeline = gpsTimeline
        var result: [[AnalysisPoint]] = []
        for climb in climbs {
            guard let s = climb.effortStartS, let e = climb.effortEndS, e > s,
                  let d0 = x(forOffsetS: s, timeline: timeline),
                  let d1 = x(forOffsetS: e, timeline: timeline),
                  d1 > d0
            else { continue }
            for run in runs {
                let section = run.filter { $0.x >= d0 && $0.x <= d1 }
                if section.count >= 2 { result.append(section) }
            }
        }
        return result
    }

    /// (elapsed seconds, display-unit distance) pairs from points carrying
    /// both evidences.
    private var gpsTimeline: [(offsetS: Double, x: Double)] {
        // These timelines interpolate adjacent samples. Abstain when privacy
        // removed any ground rather than interpolate across a hidden stretch.
        guard let gps, gps.gpsPoints.allSatisfy(\.hasVisibleCoordinate),
              let t0 = gps.gpsPoints.first?.timestamp else { return [] }
        return gps.gpsPoints.compactMap { point in
            guard let t = point.timestamp, let d = point.distanceM else { return nil }
            return (t - t0, units.distanceValue(fromMeters: d))
        }
    }

    private func x(
        forOffsetS offset: Double,
        timeline: [(offsetS: Double, x: Double)]
    ) -> Double? {
        guard let first = timeline.first else { return nil }
        if offset <= first.offsetS { return abs(offset - first.offsetS) <= 15 ? first.x : nil }
        for index in 1..<timeline.count {
            let a = timeline[index - 1], b = timeline[index]
            if offset <= b.offsetS {
                guard b.offsetS > a.offsetS else { return a.x }
                let f = (offset - a.offsetS) / (b.offsetS - a.offsetS)
                return a.x + f * (b.x - a.x)
            }
        }
        let last = timeline[timeline.count - 1]
        return abs(offset - last.offsetS) <= 15 ? last.x : nil
    }

    /// Stream samples mapped onto the distance axis (linear interpolation
    /// between adjacent GPS moments; samples beyond GPS evidence drop).
    private func metricPoints(kind: RideStreamKind) -> [AnalysisPoint] {
        guard let stream = streams[kind] else { return [] }
        let samples = stream.analysisSamples(kind: kind, units: units)
        let timeline = gpsTimeline
        guard !samples.isEmpty, timeline.count >= 2 else { return [] }
        var result: [AnalysisPoint] = []
        var cursor = 0
        for sample in samples {
            let target = sample.elapsedMinutes * 60
            while cursor < timeline.count - 2, timeline[cursor + 1].offsetS <= target {
                cursor += 1
            }
            let a = timeline[cursor], b = timeline[cursor + 1]
            if target >= a.offsetS, target <= b.offsetS, b.offsetS > a.offsetS {
                let f = (target - a.offsetS) / (b.offsetS - a.offsetS)
                result.append(AnalysisPoint(x: a.x + f * (b.x - a.x), value: sample.value))
            } else if abs(target - a.offsetS) <= 15 {
                result.append(AnalysisPoint(x: a.x, value: sample.value))
            } else if abs(target - b.offsetS) <= 15 {
                result.append(AnalysisPoint(x: b.x, value: sample.value))
            }
        }
        return result
    }

    /// GPS index nearest the scrubbed distance — the readout's and map
    /// marker's one lookup.
    private var selectionGpsIndex: Int? {
        guard let selectionX, let gps else { return nil }
        let targetM = units.meters(fromDistanceValue: selectionX)
        var best: Int?
        var bestDelta = Double.greatestFiniteMagnitude
        for (index, point) in gps.gpsPoints.enumerated() {
            guard let d = point.distanceM else { continue }
            let delta = abs(d - targetM)
            if delta < bestDelta {
                bestDelta = delta
                best = index
            }
        }
        return best
    }

    private var scrubCoordinate: CLLocationCoordinate2D? {
        guard let gps, let index = selectionGpsIndex,
              gps.gpsPoints.indices.contains(index)
        else { return nil }
        let point = gps.gpsPoints[index]
        guard point.hasVisibleCoordinate, let latitude = point.latitude, let longitude = point.longitude
        else { return nil }
        return CLLocationCoordinate2D(latitude: latitude, longitude: longitude)
    }

    /// Speed derived from the recorded track when no sensor stream exists —
    /// distance over time is arithmetic, not a model (ratified 2026-08-18).
    /// Real recorded edges only: no smearing across pauses or signal gaps,
    /// GPS-artifact velocities dropped. Values in display units, matching
    /// stream-backed analysis samples.
    private var derivedSpeedPoints: [AnalysisPoint] {
        guard streams[.speed] == nil, let gps,
              gps.gpsPoints.allSatisfy(\.hasVisibleCoordinate) else { return [] }
        let track = gps.gpsPoints.compactMap { point -> (d: Double, t: Double)? in
            guard let d = point.distanceM, let t = point.timestamp else { return nil }
            return (d, t)
        }
        guard track.count >= 3 else { return [] }
        var edges: [AnalysisPoint] = []
        for i in 1..<track.count {
            let dd = track[i].d - track[i - 1].d
            let dt = track[i].t - track[i - 1].t
            guard dt > 0, dt <= 120, dd >= 0 else { continue }
            let v = dd / dt
            guard v.isFinite, v < 40 else { continue }
            edges.append(AnalysisPoint(
                x: units.distanceValue(fromMeters: track[i - 1].d + dd / 2),
                value: RideStreamKind.speed.displayValue(v, units: units)
            ))
        }
        guard edges.count >= 2 else { return [] }
        // Centered rolling mean over 5 edges steadies 1 Hz GPS jitter.
        return edges.indices.map { i in
            let lo = max(0, i - 2), hi = min(edges.count - 1, i + 2)
            let mean = edges[lo...hi].map(\.value).reduce(0, +) / Double(hi - lo + 1)
            return AnalysisPoint(x: edges[i].x, value: mean)
        }
    }

    private var availableStreamKinds: [RideStreamKind] {
        RideStreamKind.allCases.filter { kind in
            if let stream = streams[kind],
               !stream.analysisSamples(kind: kind, units: units).isEmpty
            {
                return true
            }
            return kind == .speed && !derivedSpeedPoints.isEmpty
        }
    }

    @ViewBuilder
    private var analysis: some View {
        let runs = elevationRuns
        let kinds = availableStreamKinds
        let effectiveKind = kinds.contains(selectedStreamKind)
            ? selectedStreamKind
            : (kinds.first ?? selectedStreamKind)
        let derived = effectiveKind == .speed && streams[.speed] == nil
        let metricSamples: [AnalysisPoint] = kinds.isEmpty
            ? []
            : (derived ? derivedSpeedPoints : metricPoints(kind: effectiveKind))
        if let domain = analysisDomain, !runs.isEmpty || !metricSamples.isEmpty {
            VStack(alignment: .leading, spacing: 12) {
                HStack {
                    Text("Analysis").sectionHeaderStyle()
                    Spacer()
                    if !kinds.isEmpty {
                        Picker("Metric", selection: Binding(
                            get: { effectiveKind },
                            set: { selectedStreamKind = $0 }
                        )) {
                            ForEach(kinds) { kind in
                                Text(kind.title).tag(kind)
                            }
                        }
                        .pickerStyle(.menu)
                    }
                }

                // Strava's facts row: averages at rest, the moment's facts
                // under the scrubber.
                if selectionX != nil, let gps, let index = selectionGpsIndex {
                    Text(scrubFacts(gps: gps, index: index).joined(separator: " · "))
                        .font(.numeral(.footnote, weight: .medium))
                        .monospacedDigit()
                        .foregroundStyle(Theme.ink)
                        .lineLimit(1)
                        .minimumScaleFactor(0.7)
                        .frame(minHeight: 34)
                } else {
                    HStack(spacing: 20) {
                        if let training = ride?.trainingMetrics {
                            let values: (Double?, Double?) = switch effectiveKind {
                            case .power: (training.avgPowerW, training.maxPowerW)
                            case .heartRate: (training.avgHrBpm, training.maxHrBpm)
                            case .cadence: (training.avgCadenceRpm, training.maxCadenceRpm)
                            case .speed: (training.avgSpeedMps, training.maxSpeedMps)
                            }
                            if let average = values.0 {
                                analysisFact("Average", effectiveKind.displayValue(average, units: units),
                                             unit: effectiveKind.unit(units), places: effectiveKind.precision)
                            }
                            if let maximum = values.1 {
                                analysisFact("Maximum", effectiveKind.displayValue(maximum, units: units),
                                             unit: effectiveKind.unit(units), places: effectiveKind.precision)
                            }
                        }
                    }
                    .frame(minHeight: 34)
                }

                if !runs.isEmpty {
                    ElevationBandChart(
                        runs: runs,
                        countedRuns: countedRuns,
                        domain: domain,
                        selection: $selectionX
                    )
                    .frame(height: 64)
                    .padding(.leading, metricSamples.isEmpty ? 0 : plotInsets.leading)
                    .padding(.trailing, metricSamples.isEmpty ? 0 : plotInsets.trailing)
                }

                if !metricSamples.isEmpty {
                    AnalysisMetricChart(
                        kind: effectiveKind,
                        samples: metricSamples,
                        domain: domain,
                        selection: $selectionX
                    )
                    .frame(height: 170)
                    .onPreferenceChange(AnalysisPlotInsetsKey.self) { plotInsets = $0 }
                }
            }
            .padding(.horizontal, 20)
            .padding(.top, 28)
        }
    }

    /// The facts row uses the same ledger precision as the stat grid —
    /// speed to a tenth, power/heart rate whole — so the two rows can never
    /// disagree about one value.
    private func analysisFact(
        _ label: String, _ value: Double, unit: String, places: Int
    ) -> some View {
        VStack(alignment: .leading, spacing: 2) {
            Text(label)
                .font(.caption)
                .foregroundStyle(Theme.gray)
            Text("\(Format.number(value, places: places)) \(unit)")
                .font(.numeral(.subheadline))
                .monospacedDigit()
                .foregroundStyle(Theme.ink)
        }
        .accessibilityElement(children: .combine)
    }

    /// Device laps — the rider's own segmentation, shown only when the
    /// file carries real structure (two or more).
    @ViewBuilder
    private var lapsBlock: some View {
        if let laps = ride?.laps, laps.count >= 2 {
            VStack(alignment: .leading, spacing: 10) {
                Text("Laps").sectionHeaderStyle()
                VStack(spacing: 0) {
                    HStack {
                        Text("LAP").frame(width: 34, alignment: .leading)
                        Spacer()
                        Text("DISTANCE").frame(width: 74, alignment: .trailing)
                        Text("TIME").frame(width: 56, alignment: .trailing)
                        Text("POWER").frame(width: 60, alignment: .trailing)
                    }
                    .font(.caption2)
                    .kerning(0.6)
                    .foregroundStyle(Theme.gray2)
                    .padding(.bottom, 6)
                    ForEach(Array(laps.enumerated()), id: \.element.id) { index, lap in
                        HStack {
                            Text("\(index + 1)")
                                .font(.numeral(.footnote, weight: .medium))
                                .monospacedDigit()
                                .foregroundStyle(Theme.gray)
                                .frame(width: 34, alignment: .leading)
                            Spacer()
                            Text(lap.totalDistanceM.map {
                                "\(Format.distance(fromMeters: $0, units: units)) \(units.distanceUnit)"
                            } ?? "—")
                                .frame(width: 74, alignment: .trailing)
                            Text(Format.climbTime(lap.totalTimerS ?? lap.totalElapsedS))
                                .frame(width: 56, alignment: .trailing)
                            Text(lap.avgPowerW.map { "\($0) W" } ?? "—")
                                .frame(width: 60, alignment: .trailing)
                        }
                        .font(.numeral(.footnote, weight: .regular))
                        .monospacedDigit()
                        .foregroundStyle(Theme.ink)
                        .frame(minHeight: 26)
                        .accessibilityElement(children: .combine)
                    }
                }
            }
            .padding(.horizontal, 20)
            .padding(.top, 28)
        }
    }

    // MARK: Ride literacy (Depth Ledger 1–4, Tim-ratified 2026-08-18)

    @ViewBuilder
    private var splitsBlock: some View {
        if let gps {
            let splits = SplitsEngine.splits(points: gps.gpsPoints, units: units)
            if splits.count >= 2 {
                SplitsSection(splits: splits)
                    .padding(.horizontal, 20)
                    .padding(.top, 28)
            }
        }
    }

    @ViewBuilder
    private var zonesBlock: some View {
        if isOwnRide, let training = ride?.trainingMetrics,
           let threshold = training.threshold, !training.powerZones.isEmpty {
            ZonesSection(zones: training.powerZones, threshold: threshold, isPending: false)
                .padding(.horizontal, 20)
                .padding(.top, 28)
        }
    }

    @ViewBuilder
    private var bestEffortsBlock: some View {
        if isOwnRide, let training = ride?.trainingMetrics, !training.bestEfforts.isEmpty {
            BestEffortsRow(efforts: training.bestEfforts)
                .padding(.horizontal, 20)
                .padding(.top, 28)
        }
    }

    /// The moment's facts for the scrubbed GPS index (pure lookup —
    /// ScrubFacts abstains over sparse or missing evidence).
    private func scrubFacts(gps: GpsResponse, index: Int) -> [String] {
        ScrubFacts.facts(
            points: gps.gpsPoints,
            index: index,
            powerSamples: streams[.power]?.analysisSamples(kind: .power, units: units) ?? [],
            heartRateSamples: streams[.heartRate]?.analysisSamples(kind: .heartRate, units: units) ?? [],
            units: units
        )
    }

    @ViewBuilder
    private var climbList: some View {
        if !climbs.isEmpty {
            // The ride page speaks one grammar (Strava anatomy): Climbs is a
            // full-width page section with hairline rows, like laps and
            // splits — never the sheet-layer grouped card (Tim, 2026-08-21).
            VStack(alignment: .leading, spacing: 0) {
                Text("Climbs").sectionHeaderStyle()
                    .padding(.bottom, 6)
                ForEach(Array(climbs.enumerated()), id: \.element.stableId) { index, climb in
                    if index > 0 {
                        Rectangle().fill(Theme.separator).frame(height: 0.5)
                    }
                    climbRow(index: index + 1, climb: climb)
                }
                // The un-attributed remainder — sheet speaks (Law 2) — in
                // the same row grammar as the climbs: one gray, no tint.
                if let between = ride?.calItemization?.everythingBetweenBaseUnits {
                    Rectangle().fill(Theme.separator).frame(height: 0.5)
                    HStack(spacing: 12) {
                        Text("Everything between")
                            .font(.body)
                            .foregroundStyle(Theme.gray)
                        Spacer(minLength: 8)
                        Text("\(Format.baseUnits(between)) CAL")
                            .font(.numeral(.caption, weight: .medium))
                            .monospacedDigit()
                            .foregroundStyle(Theme.gray)
                    }
                    .frame(minHeight: Theme.row)
                    .accessibilityElement(children: .combine)
                }
            }
            .padding(.horizontal, 20)
            .padding(.top, 28)
        }
    }

    /// CAL tribute attributed to this climb pattern, joined by patternId
    /// (ride-contract v1). nil until the itemization exists for the ride.
    private func tributeCal(for climb: ClimbPattern) -> String? {
        guard let shares = ride?.calItemization?.climbs, let patternId = climb.id else { return nil }
        return shares.first { $0.patternId == patternId }?.calTributeBaseUnits
    }

    /// Effort rows carry the blessed two-value trailing stack — time over
    /// tribute CAL — the one ratified exception to the single-trailing-value
    /// row grammar (Tim, 2026-08-17; see Rows.swift).
    private func climbRow(index: Int, climb: ClimbPattern) -> some View {
        let canonId = climb.canonClimbId
        let tribute = tributeCal(for: climb)
        return Button {
            if let canonId { selectedClimbId = canonId }
        } label: {
            HStack(spacing: 12) {
                Text("\(index)")
                    .font(.caption2)
                    .foregroundStyle(Theme.ink)
                    .frame(width: 20, height: 20)
                    .overlay(Circle().stroke(Theme.blue, lineWidth: 1))
                VStack(alignment: .leading, spacing: 1) {
                    Text(climb.shownName)
                        .font(.body)
                        .foregroundStyle(Theme.ink)
                        .lineLimit(2)
                    Text(Format.climbSubtitle(
                        distanceM: climb.distanceM,
                        gradientPct: climb.avgGradientPct,
                        units: units
                    ))
                        .font(.caption2)
                        .foregroundStyle(Theme.gray)
                    if let result = climbResult(climb) {
                        Text(result)
                            .font(.caption2.weight(.medium))
                            .foregroundStyle(Theme.blue)
                    }
                }
                Spacer(minLength: 8)
                VStack(alignment: .trailing, spacing: 3) {
                    Text(Format.climbTime(climb.vaultMatch?.yourTime ?? climb.effortDurationS))
                        .font(.numeral(.body, weight: .regular))
                        .monospacedDigit()
                        .foregroundStyle(Theme.ink)
                    if let tribute {
                        Text("\(Format.baseUnits(tribute)) CAL")
                            .font(.numeral(.caption, weight: .medium))
                            .monospacedDigit()
                            .foregroundStyle(Theme.gray)
                    }
                }
                if canonId != nil {
                    Image(systemName: "chevron.right")
                        .font(.footnote.weight(.semibold))
                        .foregroundStyle(Theme.gray3)
                }
            }
            .frame(minHeight: Theme.row)
            .contentShape(Rectangle())
        }
        .buttonStyle(.plain)
        .disabled(canonId == nil)
        .accessibilityElement(children: .combine)
    }

    private func climbResult(_ climb: ClimbPattern) -> String? {
        guard let match = climb.vaultMatch else { return nil }
        var facts: [String] = []
        if match.isPR == true { facts.append("New best") }
        if let rank = match.yourRank { facts.append("Rank #\(rank)") }
        if match.isPR != true, let best = match.yourBestTime {
            facts.append("Best \(Format.climbTime(best))")
        }
        return facts.isEmpty ? nil : facts.joined(separator: " · ")
    }

    /// The owner's per-ride audience control (joer2 contract: later edit uses
    /// the same three-value vocabulary as upload). Rendered only when the
    /// server's resolved privacy names this viewer the owner; the value is
    /// the ride's current server truth.
    @ViewBuilder
    private var privacyRows: some View {
        if isOwnRide {
            if let privacy = ride?.privacy,
               let publication = RidePublicationSettings(state: privacy)
            {
                GroupCard {
                    ridePrivacyRow(
                        icon: "person.2",
                        label: "Who can see",
                        value: publication.visibility.label
                    ) {
                        showPrivacyEditor = true
                    }
                    RowSeparator(inset: 46)
                    ridePrivacyRow(
                        icon: "map",
                        label: "Map",
                        value: publication.mapLabel
                    ) {
                        showPrivacyEditor = true
                    }
                }
                .padding(.horizontal, 20)
                .padding(.top, 28)
            } else {
                // Fact row + centered action row — no verb in the value
                // slot (§4).
                GroupCard {
                    GrammarRow(
                        icon: "lock.trianglebadge.exclamationmark",
                        label: "Privacy unavailable"
                    )
                    RowSeparator(inset: 0)
                    CenteredActionRow(label: "Retry") {
                        Task { await load() }
                    }
                }
                .padding(.horizontal, 20)
                .padding(.top, 28)
            }
        }
    }

    private func ridePrivacyRow(
        icon: String,
        label: String,
        value: String,
        action: @escaping () -> Void
    ) -> some View {
        Button(action: action) {
            Group {
                if dynamicTypeSize.isAccessibilitySize {
                    VStack(alignment: .leading, spacing: 5) {
                        HStack(spacing: 10) {
                            Image(systemName: icon)
                                .foregroundStyle(Theme.ink)
                                .frame(width: 24)
                            Text(label)
                                .foregroundStyle(Theme.ink)
                            Spacer(minLength: 8)
                            Image(systemName: "chevron.right")
                                .font(.footnote.weight(.semibold))
                                .foregroundStyle(Theme.gray3)
                        }
                        Text(value)
                            .font(.subheadline)
                            .foregroundStyle(Theme.gray)
                            .padding(.leading, 34)
                    }
                } else {
                    HStack(spacing: 10) {
                        Image(systemName: icon)
                            .foregroundStyle(Theme.gray)
                            .frame(width: 24)
                        Text(label)
                            .foregroundStyle(Theme.ink)
                        Spacer(minLength: 8)
                        Text(value)
                            .foregroundStyle(Theme.gray)
                            .multilineTextAlignment(.trailing)
                        Image(systemName: "chevron.right")
                            .font(.footnote.weight(.semibold))
                            .foregroundStyle(Theme.gray3)
                    }
                }
            }
            .padding(.horizontal, 14)
            .padding(.vertical, 6)
            .frame(minHeight: Theme.row)
            .contentShape(Rectangle())
        }
        .buttonStyle(.plain)
        .accessibilityElement(children: .combine)
        .accessibilityLabel("\(label), \(value)")
        .accessibilityHint("Opens ride privacy settings")
    }

    /// PATCH the audience, then re-read the ride so the row shows the
    /// authoritative result — never an optimistic value.
    private func applyPrivacy(_ publication: RidePublicationSettings) async -> String? {
        do {
            try await APIClient.shared.updateRidePrivacy(
                rideId: rideId,
                publication: publication
            )
        } catch {
            return PrivacyRoomModel.message(for: error)
        }
        do {
            detail = try await APIClient.shared.rideDetail(id: rideId)
            return nil
        } catch {
            return PrivacyRoomModel.message(for: error)
        }
    }

    private func exportOriginalRide() async {
        guard !isExporting else { return }
        isExporting = true
        defer { isExporting = false }
        do {
            let (original, data) = try await APIClient.shared.downloadOriginalRide(id: rideId)
            exportDocument = RideFileDocument(data: data)
            exportFileName = original.fileName
            exportFileType = original.fileType
            showFileExporter = true
        } catch {
            alertMessage = error.localizedDescription
        }
    }

    private func deleteRide() async {
        guard !isDeleting else { return }
        isDeleting = true
        defer { isDeleting = false }
        do {
            try await APIClient.shared.deleteRide(id: rideId)
        } catch {
            alertMessage = error.localizedDescription
            return
        }

        if let user = session.currentUser {
            do {
                _ = try await RideUploadRuntime.shared.deleteLocalCopy(
                    serverRideID: rideId,
                    owner: RecordingOwner(user: user)
                )
            } catch {
                dismissAfterAlert = true
                alertMessage = "Ride deleted from Boulder Roller, but its local source file could not be removed from this iPhone."
                return
            }
        }
        dismiss()
    }

    private func load() async {
        guard loadsRemote else {
            isInitialLoading = false
            return
        }
        loadFailed = false
        let requestedOwner = session.currentUser.map(RecordingOwner.init(user:))

        // Stale-while-revalidate: a revisit paints from the session cache
        // at once, then the fresh read replaces it (Tim, 2026-08-21).
        if detail == nil,
           let cachedDetail = try? await APIClient.shared.rideDetail(id: rideId, policy: .cacheOnly)
        {
            detail = cachedDetail
            gps = try? await APIClient.shared.rideGps(id: rideId, policy: .cacheOnly)
            if let cachedPatterns = try? await APIClient.shared.ridePatterns(id: rideId, policy: .cacheOnly) {
                climbs = cachedPatterns.patterns?.climbPatterns ?? []
            }
            for kind in RideStreamKind.allCases {
                if let stream = try? await APIClient.shared.rideStream(id: rideId, kind: kind, policy: .cacheOnly) {
                    streams[kind] = stream
                }
            }
            isInitialLoading = false
        }

        async let loadedDetail: RideDetailResponse? = try? await APIClient.shared.rideDetail(id: rideId)
        async let loadedGPS: GpsResponse? = try? await APIClient.shared.rideGps(id: rideId)
        async let loadedPatterns: PatternsResponse? = try? await APIClient.shared.ridePatterns(id: rideId)
        async let loadedThreshold: ThresholdResponse? = try? await APIClient.shared.threshold()
        let (nextDetail, nextGPS, nextPatterns, nextThreshold) = await (
            loadedDetail, loadedGPS, loadedPatterns, loadedThreshold
        )

        if let user = session.currentUser, let nextThreshold,
           RiderThresholdStore.save(nextThreshold, riderID: user.id) {
            // Stored for the zones projection below.
        } else if let user = session.currentUser {
            RiderThresholdStore.clear(riderID: user.id)
        }

        let nextClimbs = nextPatterns?.patterns?.climbPatterns
        if let nextClimbs {
            // Warm the climb sheets this page links to, so the first tap
            // is as instant as a revisit (reads only; nothing renders here).
            let canonIds = nextClimbs.prefix(6).compactMap(\.canonClimbId)
            Task.detached(priority: .utility) {
                for id in canonIds {
                    guard let climb = try? await APIClient.shared.climb(id: id) else { continue }
                    if let vaultId = climb.vaultEconomy?.vaultId ?? climb.vaultId {
                        _ = try? await APIClient.shared.climbVaultDetail(vaultId: vaultId)
                        _ = try? await APIClient.shared.myClimbResults(vaultId: vaultId)
                    }
                }
            }
        }

        let ownerRide = nextDetail?.ride.privacy?.isOwner == true
            || nextDetail?.ride.isOwner == true
            || isOwnRide
        var nextStreams: [RideStreamKind: RideStreamResponse] = [:]
        var nextSpine: RideSpineData?
        if ownerRide {
            nextSpine = try? await APIClient.shared.rideSpine(id: rideId)
            async let power: RideStreamResponse? = try? await APIClient.shared.rideStream(
                id: rideId, kind: .power
            )
            async let heartRate: RideStreamResponse? = try? await APIClient.shared.rideStream(
                id: rideId, kind: .heartRate
            )
            async let cadence: RideStreamResponse? = try? await APIClient.shared.rideStream(
                id: rideId, kind: .cadence
            )
            async let speed: RideStreamResponse? = try? await APIClient.shared.rideStream(
                id: rideId, kind: .speed
            )
            let loaded = await (power, heartRate, cadence, speed)
            let pairs: [(RideStreamKind, RideStreamResponse?)] = [
                (.power, loaded.0),
                (.heartRate, loaded.1),
                (.cadence, loaded.2),
                (.speed, loaded.3),
            ]
            for (kind, stream) in pairs where stream?.hasSamples == true {
                nextStreams[kind] = stream
            }
        }

        // One reveal: detail, map, climbs, and analysis streams land together
        // (Tim, 2026-08-21) — never the page first and the analysis a beat
        // later. On a cached revisit this is a silent refresh.
        guard requestedOwner == session.currentUser.map(RecordingOwner.init(user:)) else { return }
        authoritativeSpine = ownerRide ? nextSpine : nil
        spineOwner = nextDetail == nil ? nil : requestedOwner
        if let nextDetail { detail = nextDetail }
        if let nextGPS { gps = nextGPS }
        if let nextClimbs { climbs = nextClimbs }
        for (kind, stream) in nextStreams { streams[kind] = stream }
        if !availableStreamKinds.contains(selectedStreamKind),
           let first = availableStreamKinds.first
        {
            selectedStreamKind = first
        }

        loadFailed = detail == nil
        isInitialLoading = false
    }
}

extension String: @retroactive Identifiable {
    public var id: String { self }
}
