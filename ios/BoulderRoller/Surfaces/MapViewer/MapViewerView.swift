import MapKit
import SwiftUI

/// Surface 9 — Map viewer: full-bleed dark map, glass ✕, bottom glass card.
/// The card is the tap, the chevron is the hint — no verb links.
struct MapViewerView: View {
    let fragments: [[CLLocationCoordinate2D]]
    let title: String?
    let subtitle: String?
    /// When set, tapping the bottom card opens this climb's sheet.
    let destinationClimbId: String?
    /// Canon geometry is OSM-derived; attribution is required on canon
    /// surfaces (ODbL). Ride GPS traces are the rider's own — no line.
    var showsCanonAttribution = false

    @Environment(\.dismiss) private var dismiss
    @State private var showClimbSheet = false

    init(
        coordinates: [CLLocationCoordinate2D],
        title: String?,
        subtitle: String?,
        destinationClimbId: String?,
        showsCanonAttribution: Bool = false
    ) {
        self.fragments = coordinates.isEmpty ? [] : [coordinates]
        self.title = title
        self.subtitle = subtitle
        self.destinationClimbId = destinationClimbId
        self.showsCanonAttribution = showsCanonAttribution
    }

    init(
        fragments: [[CLLocationCoordinate2D]],
        title: String?,
        subtitle: String?,
        destinationClimbId: String?,
        showsCanonAttribution: Bool = false
    ) {
        self.fragments = fragments.filter {
            $0.count >= RouteRenderPolicy.minimumDrawableRunPoints
        }
        self.title = title
        self.subtitle = subtitle
        self.destinationClimbId = destinationClimbId
        self.showsCanonAttribution = showsCanonAttribution
    }

    private var coordinates: [CLLocationCoordinate2D] { fragments.flatMap { $0 } }

    var body: some View {
        ZStack(alignment: .topLeading) {
            map.ignoresSafeArea()

            Button {
                dismiss()
            } label: {
                Image(systemName: "xmark")
                    .font(.subheadline)
                    .foregroundStyle(Theme.ink)
                    .frame(width: 34, height: 34)
                    // Glass ✕ — chrome layer, platform glass API.
                    .glassEffect(.regular.interactive(), in: .circle)
            }
            .buttonStyle(.plain)
            .padding(.leading, 16)
            .padding(.top, 12)
            .accessibilityLabel("Close map")

            VStack(spacing: 0) {
                Spacer()
                bottomCard
                if showsCanonAttribution {
                    Text("Climb data © OpenStreetMap contributors")
                        .font(.caption2)
                        .foregroundStyle(Theme.gray)
                        .padding(.bottom, 8)
                }
            }
        }
        .preferredColorScheme(.dark)
        .sheet(isPresented: $showClimbSheet) {
            if let destinationClimbId {
                NavigationStack { ClimbDetailView(climbId: destinationClimbId) }
                    .presentationCornerRadius(Theme.crown)
            }
        }
    }

    private var map: some View {
        // Route geometry and stroke ledger are the shared RouteMap pipeline
        // (bead boulderroller-v2-zudgp): same fragments, same casing/line
        // colors as the snapshot bands — the viewer only changes scale.
        Map(initialPosition: mapPosition, interactionModes: [.pan, .zoom]) {
            RouteMapContent(fragments: fragments)
        }
        .mapStyle(MapCartography.liveStyle)
    }

    private var mapPosition: MapCameraPosition {
        if let region = RouteGeometry.region(fitting: coordinates, paddingFactor: 1.5) {
            return .region(region)
        }
        return .automatic
    }

    @ViewBuilder
    private var bottomCard: some View {
        if let title, !title.isEmpty {
            let card = HStack(spacing: 12) {
                VStack(alignment: .leading, spacing: 2) {
                    Text(title)
                        .font(.subheadline.weight(.semibold))
                        .foregroundStyle(Theme.ink)
                    if let subtitle {
                        Text(subtitle)
                            .font(.caption2)
                            .foregroundStyle(Theme.gray)
                    }
                }
                Spacer()
                if destinationClimbId != nil {
                    Image(systemName: "chevron.right")
                        .font(.subheadline)
                        .foregroundStyle(Theme.gray3)
                }
            }
            .padding(.horizontal, 15)
            .padding(.vertical, 13)
            // Bottom glass card — chrome layer, platform glass API.
            .glassEffect(.regular, in: .rect(cornerRadius: 18, style: .continuous))
            .padding(.horizontal, 16)
            .padding(.bottom, 20)

            if destinationClimbId != nil {
                Button {
                    showClimbSheet = true
                } label: {
                    card
                }
                .buttonStyle(.plain)
                .accessibilityElement(children: .combine)
            } else {
                card
            }
        }
    }
}
