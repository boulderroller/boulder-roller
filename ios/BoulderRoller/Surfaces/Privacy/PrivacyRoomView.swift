import SwiftUI

/// The Privacy room — reached from the avatar sheet's Riding group.
///
/// Server-owned choices live here: W/kg sharing, the account's default audience
/// for future rides (the joer2-ratified exposure contract) and the rider's
/// circular privacy zones (the backend edge law hides shared rides inside
/// them; the owner's own view stays complete). The room renders server
/// truth only: an unavailable contract is an unavailable room — never a
/// guessed default, never zones silently shown as "none".
struct PrivacyRoomView: View {
    @Environment(\.units) private var units
    @Environment(\.dismiss) private var dismiss

    @State private var model = PrivacyRoomModel()
    @State private var showAudiencePicker = false
    @State private var editingZone: PrivacyZoneEditTarget?

    init() {}

    #if DEBUG
    init(renderModel: PrivacyRoomModel) {
        _model = State(initialValue: renderModel)
    }
    #endif

    static let shareWkgLabel = "Show my W/kg"
    static let shareWkgExplanation = "Other riders see your watts per kilo next to your power. Together they reveal your weight."

    var body: some View {
        ZStack {
            Theme.sheet.ignoresSafeArea()
            ScrollView {
                VStack(alignment: .leading, spacing: 0) {
                    SheetHeader(title: "Privacy") { dismiss() }
                        .padding(.top, 6)

                    VStack(alignment: .leading, spacing: 0) {
                        switch model.state {
                        case .loading:
                            loadingBlock
                        case let .unavailable(message):
                            unavailableBlock(message)
                        case let .loaded(settings, zonesList):
                            loadedBlock(settings: settings, zonesList: zonesList)
                        }
                    }
                    .padding(.horizontal, Theme.margin)
                    .padding(.top, 22)
                    .padding(.bottom, 32)
                }
            }
        }
        .task { await model.load() }
        .sheet(isPresented: $showAudiencePicker) {
            RideAudiencePicker(
                title: "Who can see",
                current: model.currentDefaultVisibility,
                apply: { visibility in await model.setDefaultVisibility(visibility) }
            )
            .presentationDetents([.medium])
            .presentationCornerRadius(Theme.crown)
        }
        .sheet(item: $editingZone) { target in
            PrivacyZoneEditor(
                zone: target.zone,
                onChanged: { Task { await model.load() } }
            )
            .presentationCornerRadius(Theme.crown)
        }
        .alert(
            "Couldn’t update",
            isPresented: Binding(
                get: { model.actionErrorMessage != nil },
                set: { if !$0 { model.actionErrorMessage = nil } }
            )
        ) {
            Button("OK") { model.actionErrorMessage = nil }
        } message: {
            Text(model.actionErrorMessage ?? "")
        }
    }

    // MARK: States

    private var loadingBlock: some View {
        HStack(spacing: 10) {
            ProgressView()
                .controlSize(.small)
                .tint(Theme.gray)
            Text("Loading…")
                .font(.body)
                .foregroundStyle(Theme.gray)
        }
        .padding(.horizontal, 14)
        .frame(minHeight: Theme.row)
        .accessibilityElement(children: .combine)
    }

    private func unavailableBlock(_ message: String) -> some View {
        VStack(alignment: .leading, spacing: 0) {
            GroupCard {
                GrammarRow(label: "Privacy is unavailable")
                RowSeparator()
                CenteredActionRow(label: "Retry") {
                    Task { await model.load() }
                }
            }
            GroupFooter(text: message)
        }
    }

    @ViewBuilder
    private func loadedBlock(settings: PrivacySettings, zonesList: PrivacyZonesList) -> some View {
        GroupCard {
            Toggle(Self.shareWkgLabel, isOn: Binding(
                get: { model.currentShareWkg ?? false },
                set: { value in
                    Task { model.actionErrorMessage = await model.setShareWkg(value) }
                }
            ))
            .font(.body)
            .foregroundStyle(Theme.ink)
            .tint(Theme.blue)
            .padding(.horizontal, 14)
            .padding(.vertical, 10)
            .frame(minHeight: Theme.row)
            .disabled(model.isSavingSettings)
            .accessibilityHint(Self.shareWkgExplanation)
            .accessibilityIdentifier("privacy.share-wkg")
        }
        GroupFooter(text: Self.shareWkgExplanation)

        SectionHeader(title: "New Rides")
            .padding(.top, 26)
        GroupCard {
            GrammarRow(
                icon: "eye",
                label: "Who can see",
                value: settings.defaultRideVisibility.label,
                chevron: true
            ) {
                showAudiencePicker = true
            }
            .disabled(model.isSavingSettings)
        }
        GroupFooter(text: "Applies to new rides.")

        SectionHeader(title: "Privacy Zones")
            .padding(.top, 26)
        GroupCard {
            ForEach(Array(zonesList.zones.enumerated()), id: \.element.id) { index, zone in
                if index > 0 { RowSeparator(inset: 48) }
                GrammarRow(
                    icon: "mappin.slash",
                    label: zoneLabel(zone),
                    value: zoneRadiusLabel(zone),
                    chevron: true
                ) {
                    editingZone = PrivacyZoneEditTarget(zone: zone)
                }
            }
            if model.canAddZone {
                if !zonesList.zones.isEmpty { RowSeparator() }
                CenteredActionRow(label: "Add Zone") {
                    editingZone = PrivacyZoneEditTarget(zone: nil)
                }
            }
        }
        GroupFooter(text: "Rides you share hide inside your zones.")
    }

    private func zoneLabel(_ zone: PrivacyZone) -> String {
        if let label = zone.label, !label.isEmpty { return label }
        return "Zone"
    }

    /// Contract radii read as the rider's ladder; an off-ladder radius (legacy
    /// row) converts honestly in the rider's distance unit.
    private func zoneRadiusLabel(_ zone: PrivacyZone) -> String {
        if let radius = PrivacyZoneRadius(rawValue: zone.radiusM) { return radius.label(units: units) }
        switch units {
        case .metric: return "\(zone.radiusM) m"
        case .imperial:
            return "\(Format.distance(fromMeters: Double(zone.radiusM), units: units)) \(units.distanceUnit)"
        }
    }
}

/// Sheet-item wrapper so both "add" (nil zone) and "edit" present through
/// one identifiable target.
struct PrivacyZoneEditTarget: Identifiable {
    let zone: PrivacyZone?
    var id: String { zone?.id ?? "new" }
}

// MARK: - Audience picker (shared by the room default and the ride sheet)

/// Three checkmark rows — the whole audience vocabulary. Selection applies
/// through the injected closure; the sheet closes only after the server
/// write succeeds, and a failure leaves the previous truth standing.
struct RideAudiencePicker: View {
    let title: String
    let current: RideVisibility?
    /// Performs the server write; returns an error message or nil.
    let apply: (RideVisibility) async -> String?

    @Environment(\.dismiss) private var dismiss
    @State private var inFlight: RideVisibility?
    @State private var errorMessage: String?

    var body: some View {
        ZStack {
            Theme.sheet.ignoresSafeArea()
            ScrollView {
                VStack(alignment: .leading, spacing: 0) {
                    SheetHeader(title: title) { dismiss() }
                        .padding(.top, 6)

                    VStack(alignment: .leading, spacing: 0) {
                        GroupCard {
                            ForEach(Array(RideVisibility.allCases.enumerated()), id: \.element) { index, option in
                                if index > 0 { RowSeparator() }
                                row(for: option)
                            }
                        }
                        if let errorMessage {
                            GroupFooter(text: errorMessage)
                        }
                    }
                    .padding(.horizontal, Theme.margin)
                    .padding(.top, 22)
                    .padding(.bottom, 32)
                }
            }
        }
    }

    @ViewBuilder
    private func row(for option: RideVisibility) -> some View {
        if inFlight == option {
            HStack(spacing: 12) {
                Text(option.label)
                    .font(.body)
                    .foregroundStyle(Theme.ink)
                Spacer(minLength: 8)
                ProgressView()
                    .controlSize(.small)
                    .tint(Theme.gray)
            }
            .padding(.horizontal, 14)
            .frame(minHeight: Theme.row)
            .accessibilityElement(children: .combine)
            .accessibilityLabel("\(option.label), updating")
        } else {
            GrammarRow(
                label: option.label,
                trailingSystemImage: current == option ? "checkmark" : nil
            ) {
                select(option)
            }
            .disabled(inFlight != nil)
        }
    }

    private func select(_ option: RideVisibility) {
        guard inFlight == nil else { return }
        guard option != current else {
            dismiss()
            return
        }
        errorMessage = nil
        inFlight = option
        Task {
            let failure = await apply(option)
            inFlight = nil
            if let failure {
                errorMessage = failure
            } else {
                dismiss()
            }
        }
    }
}

// MARK: - Room model

@MainActor
@Observable
final class PrivacyRoomModel {
    enum State {
        case loading
        case unavailable(String)
        case loaded(PrivacySettings, PrivacyZonesList)
    }

    var state: State = .loading
    var actionErrorMessage: String?
    private(set) var isSavingSettings = false
    @ObservationIgnored private var settingsRevision = 0
    @ObservationIgnored private var loadRevision = 0

    // Injected endpoints (tests swap these; production uses the API client).
    @ObservationIgnored var fetchSettings: () async throws -> PrivacySettings = {
        try await APIClient.shared.privacySettings()
    }
    @ObservationIgnored var fetchZones: () async throws -> PrivacyZonesList = {
        try await APIClient.shared.privacyZones()
    }
    /// Session-cache reads for the cached-first paint (nil on a miss).
    @ObservationIgnored var cachedSettings: () async -> PrivacySettings? = {
        try? await APIClient.shared.privacySettings(policy: .cacheOnly)
    }
    @ObservationIgnored var cachedZones: () async -> PrivacyZonesList? = {
        try? await APIClient.shared.privacyZones(policy: .cacheOnly)
    }
    @ObservationIgnored var putDefaultVisibility: (RideVisibility) async throws -> PrivacySettings = {
        try await APIClient.shared.updateDefaultRideVisibility($0)
    }
    @ObservationIgnored var putShareWkg: (Bool) async throws -> PrivacySettings = {
        try await APIClient.shared.updateShareWkg($0)
    }

    var currentShareWkg: Bool? {
        if case let .loaded(settings, _) = state { return settings.shareWkg }
        return nil
    }

    var currentDefaultVisibility: RideVisibility? {
        if case let .loaded(settings, _) = state { return settings.defaultRideVisibility }
        return nil
    }

    /// Add gating mirrors the server-declared cap — never a compiled copy,
    /// and never shown while the contract is unavailable.
    var canAddZone: Bool {
        guard case let .loaded(_, zonesList) = state else { return false }
        return zonesList.zones.count < zonesList.maxZones
    }

    /// Both halves load together and fail closed together: a room that can
    /// show the audience default but not the zones would misrepresent the
    /// rider's protection, so any failure is the unavailable state.
    func load() async {
        loadRevision += 1
        let request = loadRevision
        let revision = settingsRevision
        // Cached-first: a re-opened room paints its last known settings at
        // once (no spinner), then the fresh read replaces them. A failed
        // refresh keeps the cached paint; only a cold miss is unavailable.
        var paintedFromCache = false
        if case .loading = state,
           let settings = await cachedSettings(),
           let zones = await cachedZones()
        {
            guard request == loadRevision else { return }
            state = .loaded(settings, zones)
            paintedFromCache = true
        }
        if case .loaded = state {} else { state = .loading }
        do {
            async let settings = fetchSettings()
            async let zones = fetchZones()
            let (loadedSettings, loadedZones) = try await (settings, zones)
            guard request == loadRevision else { return }
            if settingsRevision == revision {
                state = .loaded(loadedSettings, loadedZones)
            } else if case let .loaded(current, _) = state {
                // A refresh begun before a successful save cannot undo it.
                state = .loaded(current, loadedZones)
            }
        } catch {
            guard request == loadRevision else { return }
            if !paintedFromCache, case .loaded = state {} else if !paintedFromCache {
                state = .unavailable(Self.message(for: error))
            }
        }
    }

    /// Returns an error message on failure; on success the room re-renders
    /// from the server's response (the authoritative settings row).
    func setDefaultVisibility(_ visibility: RideVisibility) async -> String? {
        await saveSettings { try await self.putDefaultVisibility(visibility) }
    }

    func setShareWkg(_ shareWkg: Bool) async -> String? {
        await saveSettings { try await self.putShareWkg(shareWkg) }
    }

    private func saveSettings(_ update: () async throws -> PrivacySettings) async -> String? {
        guard case .loaded = state else {
            return "Privacy is unavailable."
        }
        guard !isSavingSettings else { return nil }
        isSavingSettings = true
        defer { isSavingSettings = false }
        do {
            let updated = try await update()
            settingsRevision += 1
            if case let .loaded(_, zonesList) = state {
                state = .loaded(updated, zonesList)
            }
            return nil
        } catch {
            return Self.message(for: error)
        }
    }

    static func message(for error: Error) -> String {
        if let apiError = error as? APIError,
           let description = apiError.errorDescription {
            return description
        }
        return "Something went wrong. Please retry."
    }
}
