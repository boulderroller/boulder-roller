import CoreLocation
import MapKit
import SwiftUI

/// Address-free circular privacy-zone editor: the zone is wherever the rider
/// drags the map — the circle stays pinned to the camera center, so no
/// address is ever typed or geocoded. Radius comes from the backend's exact
/// allowed set; Done writes through the zone CRUD contract and the room
/// re-reads server truth. Deleting is a confirmed, owner-only server call.
struct PrivacyZoneEditor: View {
    @Environment(\.units) private var units
    /// nil = creating a new zone.
    let zone: PrivacyZone?
    var onChanged: () -> Void = {}

    @Environment(\.dismiss) private var dismiss

    @State private var camera: MapCameraPosition
    @State private var centerCoordinate: CLLocationCoordinate2D
    @State private var latitudeSpanDegrees: Double
    @State private var radius: PrivacyZoneRadius
    @State private var label: String
    @State private var saving = false
    @State private var deleting = false
    @State private var confirmingDelete = false
    @State private var errorMessage: String?

    // Injected endpoints (render/unit seams; production = API client).
    var createZone: (
        _ latitude: Double, _ longitude: Double, _ radiusM: Int, _ label: String?
    ) async throws -> PrivacyZone = {
        try await APIClient.shared.createPrivacyZone(
            latitude: $0, longitude: $1, radiusM: $2, label: $3
        )
    }
    var updateZone: (
        _ id: String, _ latitude: Double, _ longitude: Double, _ radiusM: Int, _ label: String?
    ) async throws -> PrivacyZone = {
        try await APIClient.shared.updatePrivacyZone(
            id: $0, latitude: $1, longitude: $2, radiusM: $3, label: $4
        )
    }
    var deleteZone: (_ id: String) async throws -> Void = {
        try await APIClient.shared.deletePrivacyZone(id: $0)
    }

    init(zone: PrivacyZone?, onChanged: @escaping () -> Void = {}) {
        self.zone = zone
        self.onChanged = onChanged

        let center = Self.initialCenter(for: zone)
        let initialRadius = zone.flatMap { PrivacyZoneRadius(rawValue: $0.radiusM) } ?? .m200
        // Frame the circle with room to breathe (~4× the radius tall).
        let spanDegrees = Double(initialRadius.rawValue) * 4 / Self.metersPerDegreeLatitude
        _centerCoordinate = State(initialValue: center)
        _latitudeSpanDegrees = State(initialValue: spanDegrees)
        _radius = State(initialValue: initialRadius)
        _label = State(initialValue: zone?.label ?? "")
        _camera = State(initialValue: .region(
            MKCoordinateRegion(
                center: center,
                span: MKCoordinateSpan(latitudeDelta: spanDegrees, longitudeDelta: spanDegrees)
            )
        ))
    }

    private static let metersPerDegreeLatitude = 111_320.0

    /// Existing zones open on themselves. A new zone opens on the device's
    /// current location only when location is already authorized (reading
    /// state never prompts — the location ask belongs to Record); otherwise
    /// on the product's home region (Philadelphia).
    static func initialCenter(for zone: PrivacyZone?) -> CLLocationCoordinate2D {
        if let zone {
            return CLLocationCoordinate2D(latitude: zone.latitude, longitude: zone.longitude)
        }
        let manager = CLLocationManager()
        let status = manager.authorizationStatus
        if status == .authorizedWhenInUse || status == .authorizedAlways,
           let location = manager.location {
            return location.coordinate
        }
        // Philadelphia City Hall — the First Cohort's home ground.
        return CLLocationCoordinate2D(latitude: 39.9526, longitude: -75.1652)
    }

    var body: some View {
        ZStack {
            Theme.sheet.ignoresSafeArea()
            ScrollView {
                VStack(alignment: .leading, spacing: 0) {
                    SheetHeader(
                        title: zone == nil ? "New Zone" : "Zone",
                        doneEnabled: !saving && !deleting,
                        onDone: save
                    )
                    .padding(.top, 6)

                    VStack(alignment: .leading, spacing: 0) {
                        mapBlock
                        radiusBlock
                        labelBlock

                        if let errorMessage {
                            GroupFooter(text: errorMessage)
                        }

                        if zone != nil {
                            GroupCard {
                                if deleting {
                                    HStack(spacing: 10) {
                                        ProgressView()
                                            .controlSize(.small)
                                            .tint(Theme.gray)
                                        Text("Deleting…")
                                            .font(.body)
                                            .foregroundStyle(Theme.gray)
                                    }
                                    .frame(maxWidth: .infinity, minHeight: Theme.row)
                                    .accessibilityElement(children: .combine)
                                } else {
                                    CenteredActionRow(label: "Delete Zone", color: Theme.blue) {
                                        confirmingDelete = true
                                    }
                                }
                            }
                            .padding(.top, 20)
                        }
                    }
                    .padding(.horizontal, Theme.margin)
                    .padding(.top, 22)
                    .padding(.bottom, 32)
                }
            }
        }
        .confirmationDialog(
            "Delete this zone?",
            isPresented: $confirmingDelete,
            titleVisibility: .visible
        ) {
            Button("Delete Zone", role: .destructive) { performDelete() }
            Button("Cancel", role: .cancel) {}
        }
        .interactiveDismissDisabled(saving || deleting)
    }

    // MARK: Map (drag the map; the circle holds the center)

    private var mapBlock: some View {
        GeometryReader { proxy in
            ZStack {
                Map(position: $camera, interactionModes: [.pan, .zoom])
                    .mapStyle(MapCartography.liveStyle)
                    .onMapCameraChange(frequency: .continuous) { context in
                        centerCoordinate = context.region.center
                        latitudeSpanDegrees = context.region.span.latitudeDelta
                    }

                // The zone, in screen space: exact meters at the current
                // zoom, always centered — dragging the map positions it.
                let diameter = circleDiameterPoints(mapHeight: proxy.size.height)
                Circle()
                    .fill(Color.white.opacity(0.07))
                    .overlay(Circle().stroke(Color.white.opacity(0.65), lineWidth: 1.5))
                    .frame(width: diameter, height: diameter)
                    .allowsHitTesting(false)
                Circle()
                    .fill(Theme.ink)
                    .frame(width: 5, height: 5)
                    .allowsHitTesting(false)
            }
        }
        .frame(height: 260)
        .clipShape(RoundedRectangle(cornerRadius: Theme.cardRadius, style: .continuous))
        .accessibilityElement(children: .ignore)
        .accessibilityLabel("Zone map")
        .accessibilityHint("Drag the map to position the zone.")
    }

    private func circleDiameterPoints(mapHeight: CGFloat) -> CGFloat {
        guard mapHeight > 0, latitudeSpanDegrees > 0 else { return 0 }
        let metersTall = latitudeSpanDegrees * Self.metersPerDegreeLatitude
        let metersPerPoint = metersTall / Double(mapHeight)
        guard metersPerPoint > 0 else { return 0 }
        return CGFloat(Double(radius.rawValue) * 2 / metersPerPoint)
    }

    // MARK: Radius (the backend's exact allowed set)

    private var radiusBlock: some View {
        VStack(alignment: .leading, spacing: 0) {
            SectionHeader(title: "Radius")
                .padding(.top, 22)
            GroupCard {
                ForEach(Array(PrivacyZoneRadius.allCases.enumerated()), id: \.element) { index, option in
                    if index > 0 { RowSeparator() }
                    GrammarRow(
                        label: option.label(units: units),
                        trailingSystemImage: radius == option ? "checkmark" : nil
                    ) {
                        radius = option
                    }
                }
            }
        }
    }

    // MARK: Label (optional, server max 50)

    private var labelBlock: some View {
        VStack(alignment: .leading, spacing: 0) {
            SectionHeader(title: "Label")
                .padding(.top, 22)
            GroupCard {
                TextField(
                    "",
                    text: $label,
                    prompt: Text("Optional").foregroundStyle(Theme.gray2)
                )
                .font(.body)
                .foregroundStyle(Theme.ink)
                .padding(.horizontal, 14)
                .frame(minHeight: Theme.row)
                .onChange(of: label) { _, new in
                    if new.count > PrivacyZoneRadius.maxLabelLength {
                        label = String(new.prefix(PrivacyZoneRadius.maxLabelLength))
                    }
                }
                .accessibilityLabel("Zone label, optional")
            }
        }
    }

    // MARK: Mutations (server truth or a standing error — nothing optimistic)

    private func save() {
        guard !saving, !deleting else { return }
        errorMessage = nil
        saving = true
        let trimmed = label.trimmingCharacters(in: .whitespacesAndNewlines)
        let finalLabel = trimmed.isEmpty ? nil : trimmed
        Task {
            do {
                if let zone {
                    _ = try await updateZone(
                        zone.id,
                        centerCoordinate.latitude,
                        centerCoordinate.longitude,
                        radius.rawValue,
                        finalLabel
                    )
                } else {
                    _ = try await createZone(
                        centerCoordinate.latitude,
                        centerCoordinate.longitude,
                        radius.rawValue,
                        finalLabel
                    )
                }
                saving = false
                onChanged()
                dismiss()
            } catch {
                saving = false
                errorMessage = PrivacyModel.message(for: error)
            }
        }
    }

    private func performDelete() {
        guard let zone, !deleting, !saving else { return }
        errorMessage = nil
        deleting = true
        Task {
            do {
                try await deleteZone(zone.id)
                deleting = false
                onChanged()
                dismiss()
            } catch {
                deleting = false
                errorMessage = PrivacyModel.message(for: error)
            }
        }
    }
}
