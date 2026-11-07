import MapKit
import SwiftUI

/// The canon, on the map — every ratified climb in the viewport, drawn with
/// the one route stroke ledger, each tappable into its climb. Pushed from
/// the feed (content, not a ceremony). Un-deferred by Tim 2026-08-18.
struct CanonMapView: View {
    @State private var climbs: [Climb] = []
    @State private var selectedClimbId: String?
    @State private var visibleRegion: MKCoordinateRegion?
    @State private var loadFailed = false
    /// Philadelphia is the product; the map opens on the spine of it.
    @State private var camera: MapCameraPosition = .region(
        MKCoordinateRegion(
            center: CLLocationCoordinate2D(latitude: 40.01, longitude: -75.21),
            span: MKCoordinateSpan(latitudeDelta: 0.14, longitudeDelta: 0.14)
        )
    )

    /// Pin clustering: past city zoom, nearby starts merge into one counted
    /// cluster; tapping a cluster zooms toward it. Centerlines draw at
    /// every zoom — the canon's shape is the map's substance.
    private struct Cluster: Identifiable {
        let id: String
        let coordinate: CLLocationCoordinate2D
        let climbs: [Climb]
    }

    private var clusteringActive: Bool {
        (visibleRegion?.span.latitudeDelta ?? camera.region?.span.latitudeDelta ?? 0) > 0.045
    }

    private var clusters: [Cluster] {
        let span = visibleRegion?.span.latitudeDelta
            ?? camera.region?.span.latitudeDelta ?? 0.14
        let cell = span / 7
        var buckets: [String: [(Climb, CLLocationCoordinate2D)]] = [:]
        for climb in climbs {
            guard let start = RouteGeometry.fragments(from: climb.routePreview).first?.first
            else { continue }
            let key = "\(Int(start.latitude / cell))/\(Int(start.longitude / cell))"
            buckets[key, default: []].append((climb, start))
        }
        return buckets.map { key, members in
            let lat = members.map(\.1.latitude).reduce(0, +) / Double(members.count)
            let lon = members.map(\.1.longitude).reduce(0, +) / Double(members.count)
            return Cluster(
                id: key,
                coordinate: CLLocationCoordinate2D(latitude: lat, longitude: lon),
                climbs: members.map(\.0)
            )
        }
    }

    var body: some View {
        Map(position: $camera, interactionModes: [.pan, .zoom]) {
            ForEach(climbs) { climb in
                let fragments = RouteGeometry.fragments(from: climb.routePreview)
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
                if !clusteringActive, let start = fragments.first?.first {
                    Annotation(
                        climb.name ?? "Climb",
                        coordinate: start,
                        anchor: .bottom
                    ) {
                        Button {
                            selectedClimbId = climb.id
                        } label: {
                            Image(systemName: "mountain.2.fill")
                                .font(.caption2)
                                .foregroundStyle(Theme.ink)
                                .frame(width: 26, height: 26)
                                .background(Circle().fill(Theme.blue))
                                .overlay(Circle().stroke(Theme.routeCasing, lineWidth: 2))
                        }
                        .buttonStyle(.plain)
                        .accessibilityLabel("Open \(climb.name ?? "climb")")
                    }
                }
            }
            if clusteringActive {
                ForEach(clusters) { cluster in
                    Annotation("", coordinate: cluster.coordinate, anchor: .center) {
                        Button {
                            if cluster.climbs.count == 1, let only = cluster.climbs.first {
                                selectedClimbId = only.id
                            } else {
                                withAnimation {
                                    camera = .region(MKCoordinateRegion(
                                        center: cluster.coordinate,
                                        span: MKCoordinateSpan(
                                            latitudeDelta: 0.035, longitudeDelta: 0.035
                                        )
                                    ))
                                }
                            }
                        } label: {
                            if cluster.climbs.count == 1 {
                                Image(systemName: "mountain.2.fill")
                                    .font(.caption2)
                                    .foregroundStyle(Theme.ink)
                                    .frame(width: 26, height: 26)
                                    .background(Circle().fill(Theme.blue))
                                    .overlay(Circle().stroke(Theme.routeCasing, lineWidth: 2))
                            } else {
                                Text("\(cluster.climbs.count)")
                                    .font(.numeral(.caption, weight: .semibold))
                                    .monospacedDigit()
                                    .foregroundStyle(Theme.ink)
                                    .frame(width: 30, height: 30)
                                    .background(Circle().fill(Theme.blue))
                                    .overlay(Circle().stroke(Theme.routeCasing, lineWidth: 2))
                            }
                        }
                        .buttonStyle(.plain)
                        .accessibilityLabel(
                            cluster.climbs.count == 1
                                ? "Open \(cluster.climbs.first?.name ?? "climb")"
                                : "\(cluster.climbs.count) climbs — zoom in"
                        )
                    }
                }
            }
        }
        .mapStyle(MapCartography.liveStyle)
        .preferredColorScheme(.dark)
        .onMapCameraChange(frequency: .onEnd) { context in
            visibleRegion = context.region
            Task { await load(region: context.region) }
        }
        .navigationTitle("Climbs")
        .navigationBarTitleDisplayMode(.inline)
        .navigationDestination(item: $selectedClimbId) { climbId in
            ClimbDetailView(climbId: climbId)
        }
        .safeAreaInset(edge: .bottom) {
            HStack {
                if loadFailed {
                    Text("Climbs are unavailable")
                        .font(.caption2)
                        .foregroundStyle(Theme.gray)
                } else {
                    Text("Climb data © OpenStreetMap contributors")
                        .font(.caption2)
                        .foregroundStyle(Theme.gray)
                }
            }
            .padding(.vertical, 6)
            .frame(maxWidth: .infinity)
            .background(.ultraThinMaterial)
        }
        .task {
            if let region = visibleRegion ?? camera.region {
                await load(region: region)
            }
        }
    }

    private func load(region: MKCoordinateRegion) async {
        let bbox = String(
            format: "%.5f,%.5f,%.5f,%.5f",
            region.center.longitude - region.span.longitudeDelta / 2,
            region.center.latitude - region.span.latitudeDelta / 2,
            region.center.longitude + region.span.longitudeDelta / 2,
            region.center.latitude + region.span.latitudeDelta / 2
        )
        // Cached-first: a region seen this session paints at once, then the
        // fresh read replaces it (grout pass, 2026-08-21).
        if let cached = try? await APIClient.shared.climbs(bbox: bbox, limit: 100, policy: .cacheOnly) {
            climbs = cached.climbs ?? []
            loadFailed = false
        }
        do {
            let response = try await APIClient.shared.climbs(bbox: bbox, limit: 100)
            climbs = response.climbs ?? []
            loadFailed = false
        } catch {
            loadFailed = climbs.isEmpty
        }
    }
}
