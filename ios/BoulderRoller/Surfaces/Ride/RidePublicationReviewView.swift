import Observation
import PhotosUI
import SwiftUI
import UIKit

/// The committed local ride's one publication checkpoint. The summary is
/// visible immediately; only the two server-owned privacy rows wait on the
/// privacy contract. No upload may begin from this screen until Save persists
/// all four fields together.
struct RidePublicationReviewView: View {
    let job: RideUploadJob
    let loadSettings: @Sendable () async throws -> PrivacySettings
    let onSave: @MainActor (
        RidePublicationSettings,
        RidePostRideDraft,
        [String: Data]
    ) async throws -> Void
    let onLater: @MainActor () -> Void

    @State private var model = RidePublicationReviewModel()
    @State private var title = ""
    @State private var notes = ""
    @State private var photos: [RidePhotoSelection] = []
    @State private var pickedPhoto: PhotosPickerItem?
    @State private var photoErrorMessage: String?
    @State private var editMode: EditMode = .inactive
    @Environment(\.dynamicTypeSize) private var dynamicTypeSize
    @Environment(\.units) private var units

    init(
        job: RideUploadJob,
        loadSettings: @escaping @Sendable () async throws -> PrivacySettings = {
            try await APIClient.shared.privacySettings()
        },
        initialTitle: String = "",
        initialNotes: String = "",
        initialPhotos: [RidePhotoSelection] = [],
        onSave: @escaping @MainActor (
            RidePublicationSettings,
            RidePostRideDraft,
            [String: Data]
        ) async throws -> Void,
        onLater: @escaping @MainActor () -> Void
    ) {
        self.job = job
        self.loadSettings = loadSettings
        self.onSave = onSave
        self.onLater = onLater
        _title = State(initialValue: initialTitle)
        _notes = State(initialValue: initialNotes)
        _photos = State(initialValue: initialPhotos)
    }

    var body: some View {
        NavigationStack {
            List {
                Section {
                    rideSummary
                }
                .listRowBackground(Theme.card)

                Section {
                    TextField(
                        "",
                        text: $title,
                        prompt: Text(defaultTitle).foregroundStyle(Theme.gray2)
                    )
                    .textInputAutocapitalization(.sentences)
                    .accessibilityLabel("Ride title")

                    ZStack(alignment: .topLeading) {
                        if notes.isEmpty {
                            Text("Add ride notes")
                                .foregroundStyle(Theme.gray2)
                                .padding(.top, 8)
                                .padding(.leading, 5)
                                .allowsHitTesting(false)
                        }
                        TextEditor(text: $notes)
                            .scrollContentBackground(.hidden)
                            .frame(minHeight: 82)
                            .accessibilityLabel("Ride notes")
                    }
                }
                .listRowBackground(Theme.card)

                Section {
                    ForEach(photos) { photo in
                        photoRow(photo)
                    }
                    .onMove(perform: movePhotos)
                    .onDelete(perform: deletePhotos)

                    if photos.count < RidePhotoContract.maxPhotos {
                        PhotosPicker(
                            selection: $pickedPhoto,
                            matching: .images,
                            photoLibrary: .shared()
                        ) {
                            Label(
                                photos.isEmpty ? "Add Photos" : "Add Another Photo",
                                systemImage: "photo.badge.plus"
                            )
                            .foregroundStyle(Theme.blue)
                            .frame(minHeight: 44)
                        }
                        .disabled(model.isSaving)
                    }
                } header: {
                    HStack {
                        Text("Photos")
                        Spacer()
                        if photos.count > 1 { EditButton() }
                    }
                } footer: {
                    if let photoErrorMessage {
                        Text(photoErrorMessage)
                    } else if photos.count == RidePhotoContract.maxPhotos {
                        Text("Six photos added.")
                    } else if photos.count > 1 {
                        Text("Move a photo to the top to make it the cover.")
                    }
                }
                .listRowBackground(Theme.card)

                Section {
                    privacyRows
                } footer: {
                    if let errorMessage = model.errorMessage {
                        Text(errorMessage)
                    } else if let zoneCount = model.zoneCount {
                        Text(zoneDescription(zoneCount))
                    } else if model.isUnavailable {
                        Text("Your ride is still saved on this iPhone.")
                    }
                }
                .listRowBackground(Theme.card)
            }
            .scrollContentBackground(.hidden)
            .background(Theme.screen)
            .navigationTitle("Save Ride")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) {
                    Button("Later", action: onLater)
                }
                ToolbarItem(placement: .confirmationAction) {
                    if model.isSaving {
                        ProgressView()
                            .controlSize(.small)
                            .accessibilityLabel("Saving ride")
                    } else {
                        Button("Save") { save() }
                            .fontWeight(.semibold)
                            .disabled(model.publication?.isValid != true)
                    }
                }
            }
            .task { await model.load(using: loadSettings) }
            .onChange(of: pickedPhoto) { _, item in
                guard let item else { return }
                loadPhoto(item)
            }
            .interactiveDismissDisabled()
            .environment(\.editMode, $editMode)
        }
        .tint(Theme.blue)
    }

    private var rideSummary: some View {
        VStack(alignment: .leading, spacing: 14) {
            VStack(alignment: .leading, spacing: 3) {
                Text(defaultTitle)
                    .font(.title3.weight(.semibold))
                    .foregroundStyle(Theme.ink)
                Text(Format.rideTimestamp(Format.isoParser.string(from: job.localSummary.startedAt)))
                    .font(.subheadline)
                    .foregroundStyle(Theme.gray)
            }

            if dynamicTypeSize.isAccessibilitySize {
                VStack(alignment: .leading, spacing: 12) {
                    summaryValue("Distance", Format.distance(fromMeters: job.localSummary.distanceM, units: units), units.distanceUnit)
                    summaryValue("Time", Format.shortDuration(job.localSummary.durationS), nil)
                    summaryValue("Elevation", Format.elevation(fromMeters: job.localSummary.elevationM, units: units), units.elevationUnit)
                }
            } else {
                HStack(alignment: .firstTextBaseline) {
                    summaryValue("Distance", Format.distance(fromMeters: job.localSummary.distanceM, units: units), units.distanceUnit)
                    Spacer()
                    summaryValue("Time", Format.shortDuration(job.localSummary.durationS), nil)
                    Spacer()
                    summaryValue("Elevation", Format.elevation(fromMeters: job.localSummary.elevationM, units: units), units.elevationUnit)
                }
            }
        }
        .padding(.vertical, 6)
        .accessibilityElement(children: .combine)
    }

    private var defaultTitle: String {
        Format.displayRideTitle(
            nil,
            startedAtISO: Format.isoParser.string(from: job.localSummary.startedAt),
            placeLabel: nil
        )
    }

    private func photoRow(_ photo: RidePhotoSelection) -> some View {
        let index = photos.firstIndex(where: { $0.id == photo.id }) ?? 0
        return HStack(spacing: 12) {
            Group {
                if let image = UIImage(data: photo.data) {
                    Image(uiImage: image)
                        .resizable()
                        .scaledToFill()
                } else {
                    Image(systemName: "photo")
                        .foregroundStyle(Theme.gray)
                }
            }
            .frame(width: 54, height: 54)
            .background(Theme.sheet)
            .clipShape(RoundedRectangle(cornerRadius: 8, style: .continuous))
            .clipped()

            VStack(alignment: .leading, spacing: 2) {
                Text(index == 0 ? "Cover" : "Photo \(index + 1)")
                    .foregroundStyle(Theme.ink)
                Text(photo.fileName)
                    .font(.caption)
                    .foregroundStyle(Theme.gray)
                    .lineLimit(1)
            }
            Spacer()
        }
        .accessibilityElement(children: .combine)
        .accessibilityLabel(index == 0 ? "Cover photo" : "Photo \(index + 1)")
    }

    private func loadPhoto(_ item: PhotosPickerItem) {
        Task {
            defer { pickedPhoto = nil }
            guard photos.count < RidePhotoContract.maxPhotos,
                  let data = try? await item.loadTransferable(type: Data.self)
            else {
                photoErrorMessage = "Couldn’t read that photo."
                return
            }
            let mimeType = item.supportedContentTypes
                .compactMap(\.preferredMIMEType)
                .first ?? "image/jpeg"
            let ext = RidePhotoContract.fileExtension(for: mimeType)
            do {
                let selected = try RidePhotoSelection(
                    fileName: "ride-photo-\(photos.count + 1).\(ext)",
                    mimeType: mimeType,
                    data: data
                )
                photos.append(selected)
                photoErrorMessage = nil
            } catch {
                photoErrorMessage = data.count > RidePhotoContract.maxFileSizeBytes
                    ? "Photos must be 15 MB or smaller."
                    : "Use a JPEG, PNG, WebP, HEIC, or HEIF photo."
            }
        }
    }

    private func movePhotos(from source: IndexSet, to destination: Int) {
        photos.move(fromOffsets: source, toOffset: destination)
    }

    private func deletePhotos(at offsets: IndexSet) {
        photos.remove(atOffsets: offsets)
        if photos.count < 2 { editMode = .inactive }
        photoErrorMessage = nil
    }

    private func summaryValue(_ label: String, _ value: String, _ unit: String?) -> some View {
        VStack(alignment: .leading, spacing: 2) {
            Text(label)
                .font(.caption)
                .foregroundStyle(Theme.gray)
            HStack(alignment: .firstTextBaseline, spacing: 3) {
                Text(value)
                    .font(.numeral(.body))
                    .monospacedDigit()
                    .foregroundStyle(Theme.ink)
                if let unit {
                    Text(unit)
                        .font(.caption)
                        .foregroundStyle(Theme.gray)
                }
            }
        }
    }

    @ViewBuilder
    private var privacyRows: some View {
        if let publication = model.publication {
            NavigationLink {
                RideVisibilitySelectionView(selection: model.visibilityBinding)
            } label: {
                privacyLabel(
                    systemImage: "person.2",
                    title: "Who can see",
                    value: publication.visibility.label
                )
            }

            NavigationLink {
                RideMapPrivacySelectionView(publication: model.publicationBinding)
            } label: {
                privacyLabel(
                    systemImage: "map",
                    title: "Map",
                    value: publication.mapLabel
                )
            }
        } else if model.isUnavailable {
            // Fact row + centered action row — no verb links (§4).
            VStack(spacing: 0) {
                HStack(spacing: 12) {
                    Image(systemName: "lock.trianglebadge.exclamationmark")
                        .foregroundStyle(Theme.gray)
                        .frame(width: 24)
                    Text("Privacy unavailable")
                        .foregroundStyle(Theme.ink)
                    Spacer()
                }
                .frame(minHeight: 44)
                CenteredActionRow(label: "Retry") {
                    Task { await model.load(using: loadSettings) }
                }
            }
        } else {
            HStack(spacing: 12) {
                ProgressView()
                    .controlSize(.small)
                Text("Loading privacy")
                    .foregroundStyle(Theme.gray)
            }
            .frame(minHeight: 44)
            .accessibilityElement(children: .combine)
        }
    }

    private func privacyLabel(
        systemImage: String,
        title: String,
        value: String
    ) -> some View {
        Label {
            Group {
                if dynamicTypeSize.isAccessibilitySize {
                    VStack(alignment: .leading, spacing: 3) {
                        Text(title)
                            .foregroundStyle(Theme.ink)
                        Text(value)
                            .font(.subheadline)
                            .foregroundStyle(Theme.gray)
                    }
                } else {
                    HStack {
                        Text(title)
                            .foregroundStyle(Theme.ink)
                        Spacer()
                        Text(value)
                            .foregroundStyle(Theme.gray)
                    }
                }
            }
            .fixedSize(horizontal: false, vertical: true)
        } icon: {
            Image(systemName: systemImage)
                .foregroundStyle(Theme.gray)
        }
    }

    private func zoneDescription(_ count: Int) -> String {
        switch count {
        case 0: return "No privacy zones are active."
        case 1: return "1 privacy zone is active."
        default: return "\(count) privacy zones are active."
        }
    }

    private func save() {
        guard let publication = model.publication else { return }
        let draft = RidePostRideDraft(
            title: title,
            notes: notes,
            photos: photos.map(\.descriptor)
        )
        let bytes = Dictionary(uniqueKeysWithValues: photos.map { ($0.id, $0.data) })
        Task {
            await model.save(publication, draft: draft, photoBytes: bytes, using: onSave)
        }
    }
}

@MainActor
@Observable
final class RidePublicationReviewModel {
    var publication: RidePublicationSettings?
    var zoneCount: Int?
    var isUnavailable = false
    var isSaving = false
    var errorMessage: String?

    var visibilityBinding: Binding<RideVisibility> {
        Binding(
            get: { self.publication?.visibility ?? .onlyYou },
            set: { visibility in
                self.publication = self.publication?.changingVisibility(visibility)
            }
        )
    }

    var publicationBinding: Binding<RidePublicationSettings> {
        Binding(
            get: {
                self.publication ?? RidePublicationSettings(
                    visibility: .onlyYou,
                    mapVisibility: .hideEntire,
                    mapHideStartM: 0,
                    mapHideEndM: 0
                )
            },
            set: { self.publication = $0 }
        )
    }

    func load(
        using operation: @Sendable () async throws -> PrivacySettings
    ) async {
        guard !isSaving else { return }
        isUnavailable = false
        errorMessage = nil
        do {
            let settings = try await operation()
            let selected = RidePublicationSettings(settings: settings)
            guard settings.privacyZonesLoaded == true, selected.isValid else {
                throw RidePublicationReviewError.unavailable
            }
            publication = selected
            zoneCount = settings.privacyZoneCount
        } catch {
            publication = nil
            zoneCount = nil
            isUnavailable = true
        }
    }

    func save(
        _ selected: RidePublicationSettings,
        draft: RidePostRideDraft,
        photoBytes: [String: Data],
        using operation: @MainActor (
            RidePublicationSettings,
            RidePostRideDraft,
            [String: Data]
        ) async throws -> Void
    ) async {
        guard !isSaving, selected.isValid else { return }
        isSaving = true
        errorMessage = nil
        defer { isSaving = false }
        do {
            try await operation(selected, draft, photoBytes)
        } catch {
            errorMessage = "Couldn’t save this ride. Try again."
        }
    }
}

private enum RidePublicationReviewError: Error {
    case unavailable
}

struct RideVisibilitySelectionView: View {
    @Binding var selection: RideVisibility
    @Environment(\.dismiss) private var dismiss

    var body: some View {
        List(RideVisibility.allCases, id: \.self) { option in
            selectionButton(option.label, selected: selection == option) {
                selection = option
                dismiss()
            }
        }
        .navigationTitle("Who can see")
        .navigationBarTitleDisplayMode(.inline)
    }
}

struct RideMapPrivacySelectionView: View {
    @Binding var publication: RidePublicationSettings

    private let endpointDistances = [0, 200, 400, 800, 1600]

    var body: some View {
        List {
            Section {
                ForEach(RideMapVisibility.allCases, id: \.self) { option in
                    Button {
                        publication = publication.changingMapVisibility(option)
                    } label: {
                        HStack {
                            Text(option.label)
                                .foregroundStyle(Theme.ink)
                            Spacer()
                            if publication.mapVisibility == option {
                                Image(systemName: "checkmark")
                                    .fontWeight(.semibold)
                                    .foregroundStyle(Theme.blue)
                            }
                        }
                        .contentShape(Rectangle())
                    }
                    .buttonStyle(.plain)
                    .accessibilityAddTraits(
                        publication.mapVisibility == option ? .isSelected : []
                    )
                }
            }

            if publication.mapVisibility == .hideStartEnd {
                Section {
                    Picker("Start", selection: startDistance) {
                        ForEach(endpointDistances, id: \.self) { meters in
                            Text(distanceLabel(meters)).tag(meters)
                        }
                    }
                    Picker("End", selection: endDistance) {
                        ForEach(endpointDistances, id: \.self) { meters in
                            Text(distanceLabel(meters)).tag(meters)
                        }
                    }
                } header: {
                    Text("Endpoint distance")
                } footer: {
                    Text("Saved privacy zones are also applied.")
                }
            } else {
                Section {
                    Text("Saved privacy zones are also applied.")
                        .foregroundStyle(Theme.gray)
                }
            }
        }
        .navigationTitle("Map")
        .navigationBarTitleDisplayMode(.inline)
    }

    private var startDistance: Binding<Int> {
        Binding(
            get: { publication.mapHideStartM },
            set: { publication = publication.changingMapHideStartM($0) }
        )
    }

    private var endDistance: Binding<Int> {
        Binding(
            get: { publication.mapHideEndM },
            set: { publication = publication.changingMapHideEndM($0) }
        )
    }

    private func distanceLabel(_ meters: Int) -> String {
        meters == 0 ? "Choose" : "\(meters) m"
    }
}

/// Later owner edit uses the exact same complete snapshot as first Save.
/// Changes are submitted together and the caller re-reads server truth before
/// this sheet closes.
struct RidePrivacyEditView: View {
    let initial: RidePublicationSettings
    let apply: @MainActor (RidePublicationSettings) async -> String?

    @Environment(\.dismiss) private var dismiss
    @State private var selected: RidePublicationSettings
    @State private var isSaving = false
    @State private var errorMessage: String?

    init(
        initial: RidePublicationSettings,
        apply: @escaping @MainActor (RidePublicationSettings) async -> String?
    ) {
        self.initial = initial
        self.apply = apply
        _selected = State(initialValue: initial)
    }

    var body: some View {
        NavigationStack {
            List {
                Section {
                    NavigationLink {
                        RideVisibilitySelectionView(
                            selection: Binding(
                                get: { selected.visibility },
                                set: { selected = selected.changingVisibility($0) }
                            )
                        )
                    } label: {
                        editRow("Who can see", value: selected.visibility.label)
                    }

                    NavigationLink {
                        RideMapPrivacySelectionView(
                            publication: Binding(
                                get: { selected },
                                set: { selected = $0 }
                            )
                        )
                    } label: {
                        editRow("Map", value: selected.mapLabel)
                    }
                } footer: {
                    if let errorMessage { Text(errorMessage) }
                }
            }
            .navigationTitle("Ride Privacy")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) {
                    Button("Cancel") { dismiss() }
                        .disabled(isSaving)
                }
                ToolbarItem(placement: .confirmationAction) {
                    if isSaving {
                        ProgressView()
                            .controlSize(.small)
                            .accessibilityLabel("Saving ride privacy")
                    } else {
                        Button("Save") { save() }
                            .fontWeight(.semibold)
                            .disabled(selected == initial || !selected.isValid)
                    }
                }
            }
            .interactiveDismissDisabled(isSaving)
        }
        .tint(Theme.blue)
    }

    private func editRow(_ title: String, value: String) -> some View {
        HStack {
            Text(title)
            Spacer()
            Text(value)
                .foregroundStyle(Theme.gray)
        }
    }

    private func save() {
        guard !isSaving, selected.isValid else { return }
        isSaving = true
        errorMessage = nil
        Task {
            let failure = await apply(selected)
            isSaving = false
            if let failure {
                errorMessage = failure
            } else {
                dismiss()
            }
        }
    }
}

@ViewBuilder
private func selectionButton(
    _ label: String,
    selected: Bool,
    action: @escaping () -> Void
) -> some View {
    Button(action: action) {
        HStack {
            Text(label)
                .foregroundStyle(Theme.ink)
            Spacer()
            if selected {
                Image(systemName: "checkmark")
                    .fontWeight(.semibold)
                    .foregroundStyle(Theme.blue)
            }
        }
        .contentShape(Rectangle())
    }
    .buttonStyle(.plain)
    .accessibilityAddTraits(selected ? .isSelected : [])
}
