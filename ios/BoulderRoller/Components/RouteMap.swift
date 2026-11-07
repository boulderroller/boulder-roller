import MapKit
import SwiftUI

/// Saved-track render assembly policy (bead boulderroller-v2-zudgp) — the one
/// gap/credibility policy every route surface draws through. Deliberately
/// distinct from the live-capture `GPSTruthPolicy`: capture truth decides what
/// is *recorded*; this policy only decides which recorded edges may be
/// *drawn*. Saved wire tracks include imported files (Garmin smart recording
/// legitimately spaces samples up to ~15 s apart at low speed), so the
/// capture pipeline's 8 s outage rule would shatter credible imports.
struct RouteRenderPolicy: Equatable {
    /// An edge implying faster-than-credible travel drops the arriving point
    /// (a rejected point never anchors a later invented edge).
    var maximumCredibleSpeedMps: Double = 55
    /// Adjacent samples further apart in time than this are an outage.
    var gapIntervalS: TimeInterval = 60
    /// An outage whose endpoints moved no further than this still renders as
    /// one connected edge — the stationary pause (cafe, traffic light).
    /// Beyond it the run breaks: the path between is unknown, and an unknown
    /// path is never invented.
    var stationaryGapBridgeMaxM: Double = 100
    /// Singleton/short-fragment rule, explicit: runs with fewer points than
    /// this are skipped entirely — never drawn as stray dots. A lone point is
    /// not route evidence; the start dot is the only deliberate dot.
    static let minimumDrawableRunPoints = 2
}

enum RouteGeometry {
    /// Lat/lon path from a route preview (normalized x/y over bounds —
    /// portal parity: lat = maxLat − y·span, lon = minLon + x·span).
    static func fragments(from preview: RoutePreview?) -> [[CLLocationCoordinate2D]] {
        guard let preview, let bounds = preview.bounds else { return [] }
        let latSpan = bounds.maxLat - bounds.minLat
        let lonSpan = bounds.maxLon - bounds.minLon
        let rawFragments: [[RoutePreviewPoint]]
        if let points = preview.points, points.count >= 2 {
            rawFragments = [points]
        } else if let segments = preview.segments {
            rawFragments = segments
        } else {
            return []
        }
        return rawFragments.compactMap { raw -> [CLLocationCoordinate2D]? in
            let coordinates = raw
                .filter { $0.x >= 0 && $0.x <= 1 && $0.y >= 0 && $0.y <= 1 }
                .map {
                    CLLocationCoordinate2D(
                        latitude: bounds.maxLat - $0.y * latSpan,
                        longitude: bounds.minLon + $0.x * lonSpan
                    )
                }
            return coordinates.count >= RouteRenderPolicy.minimumDrawableRunPoints
                ? coordinates
                : nil
        }
    }

    static func coordinates(from preview: RoutePreview?) -> [CLLocationCoordinate2D] {
        fragments(from: preview).flatMap { $0 }
    }

    static func fragments(
        from gps: GpsResponse,
        policy: RouteRenderPolicy = RouteRenderPolicy()
    ) -> [[CLLocationCoordinate2D]] {
        var result: [[CLLocationCoordinate2D]] = []
        var previous: GpsPoint?
        for point in gps.gpsPoints {
            guard point.hasVisibleCoordinate, let latitude = point.latitude, let longitude = point.longitude
            else {
                previous = nil
                continue
            }
            let coordinate = CLLocationCoordinate2D(latitude: latitude, longitude: longitude)
            var startsNew = previous == nil
            if let previous, let previousLatitude = previous.latitude, let previousLongitude = previous.longitude {
                if
                    let before = previous.timestamp,
                    let after = point.timestamp,
                    before.isFinite,
                    after.isFinite
                {
                    let interval = after - before
                    guard interval > 0 else { continue }
                    let distance = RouteVertex(
                        latitude: previousLatitude,
                        longitude: previousLongitude
                    ).distance(to: RouteVertex(
                        latitude: latitude,
                        longitude: longitude
                    ))
                    if interval > policy.gapIntervalS {
                        // An outage. A rider who provably stayed put keeps a
                        // connected line; a rider who moved gets a break —
                        // the path between is never invented.
                        startsNew = distance > policy.stationaryGapBridgeMaxM
                    } else {
                        // Saved GPS has no accuracy radius to subtract. Raw
                        // distance therefore applies the same speed ceiling
                        // conservatively, and a rejected point never becomes
                        // the anchor for a later invented edge.
                        guard distance / interval <= policy.maximumCredibleSpeedMps else {
                            continue
                        }
                    }
                } else {
                    // Without adjacent time evidence, speed and outage length
                    // are unknowable. Preserve the point but invent no edge.
                    startsNew = true
                }
            }
            if startsNew { result.append([coordinate]) }
            else { result[result.count - 1].append(coordinate) }
            previous = point
        }
        return result.filter { $0.count >= RouteRenderPolicy.minimumDrawableRunPoints }
    }

    static func coordinates(from gps: GpsResponse) -> [CLLocationCoordinate2D] {
        fragments(from: gps).flatMap { $0 }
    }

    static func region(fitting coords: [CLLocationCoordinate2D], paddingFactor: Double = 1.35) -> MKCoordinateRegion? {
        guard let first = coords.first else { return nil }
        var minLat = first.latitude, maxLat = first.latitude
        var minLon = first.longitude, maxLon = first.longitude
        for c in coords {
            minLat = min(minLat, c.latitude); maxLat = max(maxLat, c.latitude)
            minLon = min(minLon, c.longitude); maxLon = max(maxLon, c.longitude)
        }
        let span = MKCoordinateSpan(
            latitudeDelta: max((maxLat - minLat) * paddingFactor, 0.004),
            longitudeDelta: max((maxLon - minLon) * paddingFactor, 0.004)
        )
        let center = CLLocationCoordinate2D(
            latitude: (minLat + maxLat) / 2, longitude: (minLon + maxLon) / 2
        )
        return MKCoordinateRegion(center: center, span: span)
    }
}

/// The one route stroke ledger: blue line over dark-blue casing, both ends
/// round. Every surface — static snapshot band or interactive viewer — draws
/// route geometry with exactly these colors; only the stroke scale differs
/// between the two renderer classes.
enum RouteMapStyle {
    static let casing = Theme.routeCasing
    static let line = Theme.blue
    /// Card/band snapshots (feed card, ride sheet band, climb map band).
    static let snapshotCasingWidth: CGFloat = 5.5
    static let snapshotLineWidth: CGFloat = 2.8
    /// The full-bleed interactive viewer.
    static let viewerCasingWidth: CGFloat = 8
    static let viewerLineWidth: CGFloat = 4
    static let startDotRadius: CGFloat = 3.4
}

/// The one cartography configuration (granularity 13): stock standard maps,
/// flat elevation, muted base emphasis so terrain and roads stay context,
/// no POI or business clutter — the route is the only saturated element.
/// Live SwiftUI maps and the snapshotter must read the same policy.
enum MapCartography {
    /// Every interactive `Map` surface.
    static var liveStyle: MapStyle {
        .standard(
            elevation: .flat,
            emphasis: .muted,
            pointsOfInterest: .excludingAll,
            showsTraffic: false
        )
    }

    /// The snapshotter's equivalent of `liveStyle`.
    static func snapshotConfiguration() -> MKStandardMapConfiguration {
        let config = MKStandardMapConfiguration(
            elevationStyle: .flat, emphasisStyle: .muted
        )
        config.pointOfInterestFilter = .excludingAll
        config.showsTraffic = false
        return config
    }
}

/// The one route-drawing path for interactive MapKit surfaces — identical
/// fragment geometry (RouteGeometry + RouteRenderPolicy) and stroke ledger as
/// RouteMapSnapshot, at viewer scale.
struct RouteMapContent: MapContent {
    let fragments: [[CLLocationCoordinate2D]]

    var body: some MapContent {
        ForEach(Array(fragments.enumerated()), id: \.offset) { _, fragment in
            MapPolyline(coordinates: fragment)
                .stroke(
                    RouteMapStyle.casing,
                    style: StrokeStyle(
                        lineWidth: RouteMapStyle.viewerCasingWidth,
                        lineCap: .round,
                        lineJoin: .round
                    )
                )
            MapPolyline(coordinates: fragment)
                .stroke(
                    RouteMapStyle.line,
                    style: StrokeStyle(
                        lineWidth: RouteMapStyle.viewerLineWidth,
                        lineCap: .round,
                        lineJoin: .round
                    )
                )
        }
    }
}

/// Static dark map snapshot with the route drawn over it — cards' map bands.
/// Real MapKit cartography; blue route over dark-blue casing (color ledger).
struct RouteMapSnapshot: View {
    let fragments: [[CLLocationCoordinate2D]]
    var showsStartDot = true
    /// Scrub marker: a coordinate pinned onto the rendered snapshot (the
    /// ride sheet's scrub-the-relief dot). nil = no marker.
    var markerCoordinate: CLLocationCoordinate2D?

    @State private var image: UIImage?
    @State private var snapshot: MKMapSnapshotter.Snapshot?

    init(
        coordinates: [CLLocationCoordinate2D],
        showsStartDot: Bool = true,
        markerCoordinate: CLLocationCoordinate2D? = nil
    ) {
        self.fragments = coordinates.isEmpty ? [] : [coordinates]
        self.showsStartDot = showsStartDot
        self.markerCoordinate = markerCoordinate
    }

    init(
        fragments: [[CLLocationCoordinate2D]],
        showsStartDot: Bool = true,
        markerCoordinate: CLLocationCoordinate2D? = nil
    ) {
        self.fragments = fragments.filter { $0.count >= 2 }
        self.showsStartDot = showsStartDot
        self.markerCoordinate = markerCoordinate
    }

    private var coordinates: [CLLocationCoordinate2D] { fragments.flatMap { $0 } }

    var body: some View {
        GeometryReader { proxy in
            ZStack(alignment: .topLeading) {
                Theme.mapBase
                if let image {
                    Image(uiImage: image)
                        .resizable()
                        .scaledToFill()
                }
                if let markerCoordinate, let snapshot {
                    let point = snapshot.point(for: markerCoordinate)
                    Circle()
                        .fill(Theme.ink)
                        .frame(width: 9, height: 9)
                        .overlay(Circle().stroke(Theme.routeCasing, lineWidth: 2))
                        .position(point)
                }
            }
            .task(id: Self.renderIdentity(
                size: proxy.size,
                fragments: fragments,
                showsStartDot: showsStartDot
            )) {
                await render(size: proxy.size)
            }
        }
        .clipped()
        .accessibilityHidden(true)
    }

    struct SnapKey: Hashable {
        let width: Int
        let height: Int
        let showsStartDot: Bool
        let fragments: [[CoordinateBits]]

        init(size: CGSize, showsStartDot: Bool, fragments: [[CoordinateBits]]) {
            width = Int(size.width.rounded())
            height = Int(size.height.rounded())
            self.showsStartDot = showsStartDot
            self.fragments = fragments
        }

        /// Process-stable 64-bit FNV-1a over the key's exact bits (Swift's
        /// `hashValue` is seeded per launch, so it cannot name a file).
        var stableHash: String {
            var hash: UInt64 = 0xcbf2_9ce4_8422_2325
            func mix(_ value: UInt64) {
                for shift in stride(from: 0, to: 64, by: 8) {
                    hash ^= (value >> UInt64(shift)) & 0xff
                    hash = hash &* 0x0000_0100_0000_01b3
                }
            }
            mix(UInt64(width))
            mix(UInt64(height))
            mix(showsStartDot ? 1 : 0)
            mix(UInt64(fragments.count))
            for fragment in fragments {
                mix(UInt64(fragment.count))
                for bits in fragment {
                    mix(bits.latitude)
                    mix(bits.longitude)
                }
            }
            return String(hash, radix: 16)
        }
    }

    struct CoordinateBits: Hashable {
        let latitude: UInt64
        let longitude: UInt64
    }

    /// Rendered snapshots keyed by exact geometry+size, so a feed scroll-back
    /// or a ride revisit paints the map with the text instead of a beat after
    /// (grout pass, 2026-08-21). Byte-cost limited and emptied under memory
    /// pressure by NSCache; the composed PNG also lives under Caches
    /// (`SnapshotDisk`), so a purge or a relaunch reads it back in
    /// milliseconds instead of re-running the snapshotter.
    @MainActor
    final class SnapshotCache {
        static let shared = SnapshotCache()

        private final class Entry {
            let image: UIImage
            /// Nil when the image came back from disk — the live projection
            /// is only needed to place a marker, and a render restores it.
            let snapshot: MKMapSnapshotter.Snapshot?
            init(image: UIImage, snapshot: MKMapSnapshotter.Snapshot?) {
                self.image = image
                self.snapshot = snapshot
            }
        }

        private let cache: NSCache<NSNumber, Entry> = {
            let c = NSCache<NSNumber, Entry>()
            c.totalCostLimit = 48 * 1024 * 1024
            return c
        }()

        func value(
            for key: SnapKey,
            at accountBoundary: Int
        ) -> (UIImage, MKMapSnapshotter.Snapshot?)? {
            guard SnapshotDisk.permitsWork(at: accountBoundary) else { return nil }
            guard let hit = cache.object(forKey: NSNumber(value: key.hashValue)) else { return nil }
            return (hit.image, hit.snapshot)
        }

        @discardableResult
        func store(
            _ image: UIImage,
            _ snapshot: MKMapSnapshotter.Snapshot?,
            for key: SnapKey,
            at accountBoundary: Int
        ) -> Bool {
            SnapshotDisk.performIfPermitted(at: accountBoundary) {
                let cost = Int(image.size.width * image.size.height * image.scale * image.scale * 4)
                cache.setObject(
                    Entry(image: image, snapshot: snapshot),
                    forKey: NSNumber(value: key.hashValue),
                    cost: cost
                )
            }
        }

        func removeAll() {
            cache.removeAllObjects()
        }
    }

    /// On-disk layer under Caches/MapSnapshots. File names hash the exact
    /// geometry with a stable (per-build, not per-process) function and carry
    /// a style version, so a cartography or route-style change never paints a
    /// stale look. iOS may clear Caches under storage pressure — that is the
    /// contract: a miss only costs a render.
    enum SnapshotDisk {
        /// Bump when MapCartography or RouteMapStyle changes how a snapshot looks.
        static let styleVersion = "v1"
        static let maxFiles = 320
        private static let accountBoundaryKey = "br.map_snapshot.account_boundary.v1"
        private static let accountBoundaryLock = NSLock()

        nonisolated static func captureAccountBoundary() -> Int {
            accountBoundaryLock.withLock {
                UserDefaults.standard.integer(forKey: accountBoundaryKey)
            }
        }

        /// Invalidates renders already in flight. The generation is advanced
        /// both when a deletion capability appears and when it is cleared, so
        /// work started on either side cannot write across the account edge.
        nonisolated static func advanceAccountBoundary() {
            accountBoundaryLock.withLock {
                let defaults = UserDefaults.standard
                defaults.set(defaults.integer(forKey: accountBoundaryKey) &+ 1, forKey: accountBoundaryKey)
            }
        }

        nonisolated static func permitsWork(at boundary: Int) -> Bool {
            accountBoundaryLock.withLock { permitsWorkWithoutLock(at: boundary) }
        }

        /// The final cache/disk mutation shares the same lock as boundary
        /// advance. A write finishes before advance (and is then cleared), or
        /// observes the new generation and is refused.
        @discardableResult
        nonisolated static func performIfPermitted(
            at boundary: Int,
            _ work: () -> Void
        ) -> Bool {
            accountBoundaryLock.withLock {
                guard permitsWorkWithoutLock(at: boundary) else { return false }
                work()
                return true
            }
        }

        private nonisolated static func permitsWorkWithoutLock(at boundary: Int) -> Bool {
            guard boundary == UserDefaults.standard.integer(forKey: accountBoundaryKey) else {
                return false
            }
            return AccountDeletionLocalFence.permitsCachedOwnerAccountWork
        }

        nonisolated static var directory: URL {
            let base = FileManager.default.urls(for: .cachesDirectory, in: .userDomainMask)[0]
            return base.appendingPathComponent("MapSnapshots", isDirectory: true)
        }

        nonisolated static func url(for key: SnapKey) -> URL {
            directory.appendingPathComponent("\(styleVersion)-\(key.stableHash).png")
        }

        nonisolated static func read(_ key: SnapKey, at boundary: Int) -> UIImage? {
            guard permitsWork(at: boundary) else { return nil }
            guard let data = try? Data(contentsOf: url(for: key)),
                  let image = UIImage(data: data)
            else { return nil }
            return image.preparingForDisplay() ?? image
        }

        nonisolated static func write(_ image: UIImage, for key: SnapKey, at boundary: Int) {
            guard let data = image.pngData() else { return }
            performIfPermitted(at: boundary) {
                let manager = FileManager.default
                try? manager.createDirectory(at: directory, withIntermediateDirectories: true)
                try? data.write(to: url(for: key), options: .atomic)
            }
        }

        /// Oldest files beyond the cap go first; a wrong style version goes
        /// regardless. Runs once per launch off the main actor.
        nonisolated static func prune() {
            let manager = FileManager.default
            guard let urls = try? manager.contentsOfDirectory(
                at: directory,
                includingPropertiesForKeys: [.contentModificationDateKey],
                options: [.skipsHiddenFiles]
            ) else { return }
            var dated: [(URL, Date)] = []
            for url in urls {
                if !url.lastPathComponent.hasPrefix("\(styleVersion)-") {
                    try? manager.removeItem(at: url)
                    continue
                }
                let date = (try? url.resourceValues(forKeys: [.contentModificationDateKey]))?
                    .contentModificationDate ?? .distantPast
                dated.append((url, date))
            }
            guard dated.count > maxFiles else { return }
            dated.sort { $0.1 < $1.1 }
            for (url, _) in dated.prefix(dated.count - maxFiles) {
                try? manager.removeItem(at: url)
            }
        }


        nonisolated static func removeAll() throws {
            try accountBoundaryLock.withLock {
                let manager = FileManager.default
                if manager.fileExists(atPath: directory.path) {
                    try manager.removeItem(at: directory)
                }
                guard !manager.fileExists(atPath: directory.path) else {
                    throw AccountDeletionLocalCleanupError.verificationFailed
                }
            }
        }
    }

    static func renderIdentity(
        size: CGSize,
        fragments: [[CLLocationCoordinate2D]],
        showsStartDot: Bool
    ) -> SnapKey {
        SnapKey(
            size: size,
            showsStartDot: showsStartDot,
            fragments: fragments.map { fragment in
                fragment.map {
                    CoordinateBits(
                        latitude: $0.latitude.bitPattern,
                        longitude: $0.longitude.bitPattern
                    )
                }
            }
        )
    }

    private func render(size: CGSize) async {
        let accountBoundary = SnapshotDisk.captureAccountBoundary()
        guard SnapshotDisk.permitsWork(at: accountBoundary) else {
            image = nil
            snapshot = nil
            return
        }
        let key = Self.renderIdentity(size: size, fragments: fragments, showsStartDot: showsStartDot)
        if let cached = SnapshotCache.shared.value(for: key, at: accountBoundary) {
            image = cached.0
            snapshot = cached.1
            // A disk-restored entry has no projection; only a marker needs one.
            if cached.1 != nil || markerCoordinate == nil { return }
        } else {
            image = nil
            snapshot = nil
        }
        guard size.width > 10, size.height > 10, coordinates.count >= 2,
              let region = RouteGeometry.region(fitting: coordinates)
        else { return }

        if image == nil {
            // Disk layer: a purge or a relaunch paints the composed PNG back
            // in milliseconds; the snapshotter only runs on a true miss.
            let diskKey = key
            if let restored = await Task.detached(priority: .userInitiated, operation: {
                SnapshotDisk.read(diskKey, at: accountBoundary)
            }).value {
                guard SnapshotDisk.permitsWork(at: accountBoundary) else { return }
                guard SnapshotCache.shared.store(
                    restored,
                    nil,
                    for: key,
                    at: accountBoundary
                ) else { return }
                image = restored
                if markerCoordinate == nil { return }
            }
        }

        let options = MKMapSnapshotter.Options()
        options.region = region
        options.size = size
        options.traitCollection = UITraitCollection(userInterfaceStyle: .dark)
        options.showsBuildings = false
        options.preferredConfiguration = MapCartography.snapshotConfiguration()

        let snapshotter = MKMapSnapshotter(options: options)
        guard let snapshot = try? await snapshotter.start() else { return }

        // Compose off the main actor: the route stroke over a 3x snapshot is
        // real drawing work, and a feed scroll must never wait on it.
        let fragmentsCopy = fragments
        let showsDot = showsStartDot
        let rendered: UIImage = await Task.detached(priority: .userInitiated) {
            UIGraphicsImageRenderer(size: size).image { ctx in
                snapshot.image.draw(at: .zero)
                let zoomLevel = Self.estimatedZoomLevel(region: region, pixelWidth: size.width)
                for fragment in fragmentsCopy {
                    let vertices = fragment.map { RouteVertex(latitude: $0.latitude, longitude: $0.longitude) }
                    let simplified = ZoomRouteSimplifier.simplify(vertices, zoomLevel: zoomLevel)
                    let points = simplified.map {
                        snapshot.point(for: CLLocationCoordinate2D(latitude: $0.latitude, longitude: $0.longitude))
                    }
                    guard points.count >= 2 else { continue }
                    let path = UIBezierPath()
                    path.move(to: points[0])
                    for point in points.dropFirst() { path.addLine(to: point) }
                    path.lineJoinStyle = .round
                    path.lineCapStyle = .round

                    UIColor(RouteMapStyle.casing).setStroke()
                    path.lineWidth = RouteMapStyle.snapshotCasingWidth
                    path.stroke()
                    UIColor(RouteMapStyle.line).setStroke()
                    path.lineWidth = RouteMapStyle.snapshotLineWidth
                    path.stroke()
                }
                if showsDot, let first = fragmentsCopy.first?.first {
                    let center = snapshot.point(for: first)
                    let dot = UIBezierPath(
                        arcCenter: center,
                        radius: RouteMapStyle.startDotRadius,
                        startAngle: 0,
                        endAngle: .pi * 2,
                        clockwise: true
                    )
                    UIColor.white.setFill()
                    dot.fill()
                }
                _ = ctx
            }
        }.value
        guard SnapshotDisk.permitsWork(at: accountBoundary) else { return }
        guard SnapshotCache.shared.store(
            rendered,
            snapshot,
            for: key,
            at: accountBoundary
        ) else { return }
        let diskKey = key
        Task.detached(priority: .utility) {
            SnapshotDisk.write(rendered, for: diskKey, at: accountBoundary)
        }
        image = rendered
        self.snapshot = snapshot
    }

    private static func estimatedZoomLevel(region: MKCoordinateRegion, pixelWidth: CGFloat) -> Double {
        guard region.span.longitudeDelta > 0, pixelWidth > 0 else { return 16 }
        return log2(360 * Double(pixelWidth) / (256 * region.span.longitudeDelta))
    }
}
