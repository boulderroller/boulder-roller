import CoreLocation
import SwiftUI
import UniformTypeIdentifiers

/// The detail surface for a ride that truthfully lives only on this iPhone.
/// Built purely from local custody — route from recorded fixes, stats from
/// the finalized summary, export of the exact artifact bytes — and never
/// pretends a server ride exists. Deletion runs the owner-safe discard saga.
struct LocalRideView: View {
    let ride: LocalSavedRide

    @Environment(\.dismiss) private var dismiss
    @Environment(AppSession.self) private var session
    @Environment(\.dynamicTypeSize) private var dynamicTypeSize
    @Environment(\.units) private var units

    @State private var evidence: LocalSavedRideEvidence?
    @State private var loadFailed = false
    @State private var showDeleteConfirmation = false
    @State private var isDeleting = false
    @State private var exportDocument: RideFileDocument?
    @State private var showFileExporter = false
    @State private var errorMessage: String?

    var body: some View {
        ZStack {
                Theme.sheet.ignoresSafeArea()
                if let evidence {
                    content(evidence)
                } else if loadFailed {
                    // Fact row + centered action row — no verb links (§4).
                    VStack(alignment: .leading, spacing: 0) {
                        GroupCard {
                            GrammarRow(
                                icon: "lock.trianglebadge.exclamationmark",
                                label: "Ride evidence is unavailable"
                            )
                            RowSeparator(inset: 0)
                            CenteredActionRow(label: "Retry") {
                                Task { await load() }
                            }
                        }
                        Spacer()
                    }
                    .padding(.horizontal, Theme.margin)
                    .padding(.top, 22)
                } else {
                    ProgressView()
                        .controlSize(.large)
                        .accessibilityLabel("Loading ride")
                }
            }
        .navigationTitle(title)
        .navigationBarTitleDisplayMode(.inline)
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
            Text("This permanently deletes the ride data from this iPhone.")
        }
        .fileExporter(
            isPresented: $showFileExporter,
            document: exportDocument,
            contentType: RideFileDocument.contentType(for: "gpx"),
            defaultFilename: evidence?.artifact.fileName ?? "Ride.gpx"
        ) { result in
            if case let .failure(error) = result {
                errorMessage = error.localizedDescription
            }
            exportDocument = nil
        }
        .alert("Ride", isPresented: Binding(
            get: { errorMessage != nil },
            set: { if !$0 { errorMessage = nil } }
        )) {
            Button("OK") { errorMessage = nil }
        } message: {
            Text(errorMessage ?? "")
        }
        .task { await load() }
    }

    private var title: String {
        Format.displayRideTitle(
            nil,
            startedAtISO: Format.isoParser.string(from: ride.summary.startedAt),
            placeLabel: nil
        )
    }

    private func content(_ evidence: LocalSavedRideEvidence) -> some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 0) {
                HStack(spacing: 10) {
                    Text(Format.rideTimestamp(
                        Format.isoParser.string(from: ride.summary.startedAt)
                    ))
                    .font(.subheadline)
                    .foregroundStyle(Theme.gray)
                    Spacer(minLength: 0)
                }
                .padding(.horizontal, 20)
                .padding(.vertical, 12)

                let route = routeCoordinates(evidence)
                if route.count >= 2 {
                    RouteMapSnapshot(coordinates: route)
                        .frame(height: 168)
                }

                statsGrid
                    .padding(.horizontal, 20)
                    .padding(.vertical, 16)

                GroupCard {
                    CenteredActionRow(label: "Export Ride File") {
                        exportDocument = RideFileDocument(data: evidence.artifact.gpxBytes)
                        showFileExporter = true
                    }
                    RowSeparator(inset: 0)
                    CenteredActionRow(label: "Delete Ride", color: .red) {
                        showDeleteConfirmation = true
                    }
                }
                .padding(.horizontal, Theme.margin)
                .padding(.top, 8)
                .disabled(isDeleting)

                GroupFooter(text: "Saved on this iPhone. It stayed under the upload floor.")
                    .padding(.horizontal, Theme.margin)
            }
            .padding(.bottom, 30)
        }
    }

    private var statsGrid: some View {
        // Same anatomy and order as the server ride page — one ride-page
        // grammar, wherever the ride lives.
        var facts: [(String, String, String?)] = [
            (
                "Distance",
                Format.distance(fromMeters: ride.summary.distanceM, units: units),
                units.distanceUnit
            ),
            ("Elapsed", Format.clockDuration(ride.summary.durationS), nil),
        ]
        facts.append((
            "Elevation",
            Format.elevation(fromMeters: ride.summary.elevationM, units: units),
            units.elevationUnit
        ))
        return LazyVGrid(
            columns: [GridItem(.adaptive(
                minimum: dynamicTypeSize.isAccessibilitySize ? 220 : 96,
                maximum: .infinity
            ), alignment: .leading)],
            alignment: .leading,
            spacing: 16
        ) {
            ForEach(facts, id: \.0) { label, value, unit in
                VStack(alignment: .leading, spacing: 3) {
                    Text(label)
                        .font(.caption)
                        .foregroundStyle(Theme.gray)
                    StatValueText(value: value, unit: unit)
                }
                .accessibilityElement(children: .combine)
            }
        }
    }

    /// Route drawn only from recorded, capture-accepted fixes.
    private func routeCoordinates(
        _ evidence: LocalSavedRideEvidence
    ) -> [CLLocationCoordinate2D] {
        evidence.fixes.compactMap { fix in
            let gps = fix.gps
            guard gps.latitude.isFinite, gps.longitude.isFinite,
                  (-90...90).contains(gps.latitude),
                  (-180...180).contains(gps.longitude)
            else { return nil }
            return CLLocationCoordinate2D(latitude: gps.latitude, longitude: gps.longitude)
        }
    }

    private func load() async {
        loadFailed = false
        do {
            evidence = try await session.localSavedRideEvidence(ride)
        } catch {
            loadFailed = true
        }
    }

    private func deleteRide() async {
        guard !isDeleting, let evidence else { return }
        isDeleting = true
        defer { isDeleting = false }
        do {
            try await session.discardLocalSavedRide(ride, artifact: evidence.artifact)
            dismiss()
        } catch {
            errorMessage = error.localizedDescription
        }
    }
}
