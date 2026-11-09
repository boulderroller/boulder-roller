import Observation
import PhotosUI
import SwiftUI

/// Owner editor for the ordinary athletic record. Every media mutation adopts
/// a server reread; a storage PUT alone never becomes a visible photo.
struct RideEditView: View {
    let ride: Ride
    let onChanged: @MainActor () async -> Void

    @Environment(\.dismiss) private var dismiss
    @State private var title: String
    @State private var notes: String
    /// Rider-entered effort 1–10; 0 renders as unset.
    @State private var effort: Int
    @State private var media: [RideMedia]
    @State private var pickedPhoto: PhotosPickerItem?
    @State private var model = RideEditModel()

    init(ride: Ride, onChanged: @escaping @MainActor () async -> Void) {
        self.ride = ride
        self.onChanged = onChanged
        _title = State(initialValue: ride.title ?? "")
        _notes = State(initialValue: ride.description ?? "")
        _effort = State(initialValue: ride.perceivedExertion ?? 0)
        _media = State(initialValue: Self.sorted(ride.media ?? []))
    }

    var body: some View {
        NavigationStack {
            List {
                Section {
                    TextField("Ride title", text: $title)
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
                            .frame(minHeight: 96)
                            .accessibilityLabel("Ride notes")
                    }
                }
                .listRowBackground(Theme.card)

                Section {
                    Stepper(value: $effort, in: 0...10) {
                        HStack {
                            Text("Effort")
                                .foregroundStyle(Theme.ink)
                            Spacer()
                            Text(effort == 0 ? "—" : "\(effort) / 10")
                                .font(.numeral(.body))
                                .monospacedDigit()
                                .foregroundStyle(effort == 0 ? Theme.gray2 : Theme.ink)
                        }
                    }
                    .accessibilityLabel("Perceived effort")
                } footer: {
                    Text("How hard it felt, 1–10.")
                }
                .listRowBackground(Theme.card)

                Section {
                    ForEach(Array(media.enumerated()), id: \.element.id) { index, photo in
                        mediaRow(photo, index: index)
                    }

                    if media.count < RidePhotoContract.maxPhotos {
                        PhotosPicker(
                            selection: $pickedPhoto,
                            matching: .images,
                            photoLibrary: .shared()
                        ) {
                            Label(
                                media.isEmpty ? "Add Photos" : "Add Another Photo",
                                systemImage: "photo.badge.plus"
                            )
                            .foregroundStyle(Theme.blue)
                            .frame(minHeight: 44)
                        }
                        .disabled(model.isBusy)
                    }
                } header: {
                    Text("Photos")
                } footer: {
                    if let message = model.errorMessage { Text(message) }
                }
                .listRowBackground(Theme.card)
            }
            .scrollContentBackground(.hidden)
            .background(Theme.screen)
            .navigationTitle("Edit Ride")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) {
                    Button("Cancel") { dismiss() }
                        .disabled(model.isBusy)
                }
                ToolbarItem(placement: .confirmationAction) {
                    if model.isSaving {
                        ProgressView()
                            .controlSize(.small)
                            .accessibilityLabel("Saving ride")
                    } else {
                        Button("Save") { save() }
                            .fontWeight(.semibold)
                            .disabled(model.isBusy)
                    }
                }
            }
            .onChange(of: pickedPhoto) { _, item in
                guard let item else { return }
                addPhoto(item)
            }
            .interactiveDismissDisabled(model.isBusy)
        }
        .tint(Theme.blue)
    }

    private func mediaRow(_ photo: RideMedia, index: Int) -> some View {
        HStack(spacing: 12) {
            RideMediaImage(url: photo.url.flatMap(URL.init))
            .frame(width: 54, height: 54)
            .clipShape(RoundedRectangle(cornerRadius: 8, style: .continuous))
            .clipped()

            VStack(alignment: .leading, spacing: 2) {
                Text(photo.role == "cover" ? "Cover" : "Photo \(index + 1)")
                    .foregroundStyle(Theme.ink)
                if let fileName = photo.fileName {
                    Text(fileName)
                        .font(.caption)
                        .foregroundStyle(Theme.gray)
                        .lineLimit(1)
                }
            }
            Spacer()
            Menu {
                if photo.role != "cover" {
                    Button("Make Cover", systemImage: "photo.fill") {
                        setCover(photo)
                    }
                }
                if index > 0 {
                    Button("Move Earlier", systemImage: "arrow.up") {
                        move(photo, to: index - 1)
                    }
                }
                if index + 1 < media.count {
                    Button("Move Later", systemImage: "arrow.down") {
                        move(photo, to: index + 1)
                    }
                }
                Button("Remove Photo", systemImage: "trash", role: .destructive) {
                    remove(photo)
                }
            } label: {
                Image(systemName: "ellipsis")
                    .frame(width: 44, height: 44)
            }
            .disabled(model.isBusy)
            .accessibilityLabel("Actions for photo \(index + 1)")
        }
        .accessibilityElement(children: .contain)
    }

    private func addPhoto(_ item: PhotosPickerItem) {
        Task {
            defer { pickedPhoto = nil }
            guard media.count < RidePhotoContract.maxPhotos,
                  let data = try? await item.loadTransferable(type: Data.self)
            else {
                model.present("Couldn’t read that photo.")
                return
            }
            let mime = item.supportedContentTypes.compactMap(\.preferredMIMEType).first
                ?? "image/jpeg"
            do {
                let selection = try RidePhotoSelection(
                    fileName: "ride-photo-\(media.count + 1).\(RidePhotoContract.fileExtension(for: mime))",
                    mimeType: mime,
                    data: data
                )
                if let refreshed = await model.add(
                    rideID: ride.id,
                    selection: selection,
                    sortOrder: media.count
                ) {
                    media = Self.sorted(refreshed)
                    await onChanged()
                }
            } catch {
                model.present(data.count > RidePhotoContract.maxFileSizeBytes
                    ? "Photos must be 15 MB or smaller."
                    : "Use a JPEG, PNG, WebP, HEIC, or HEIF photo.")
            }
        }
    }

    private func setCover(_ photo: RideMedia) {
        Task {
            if let refreshed = await model.setCover(rideID: ride.id, mediaID: photo.id) {
                media = Self.sorted(refreshed)
                await onChanged()
            }
        }
    }

    private func remove(_ photo: RideMedia) {
        Task {
            if let refreshed = await model.remove(rideID: ride.id, mediaID: photo.id) {
                media = Self.sorted(refreshed)
                await onChanged()
            }
        }
    }

    private func move(_ photo: RideMedia, to destination: Int) {
        var reordered = media
        guard let source = reordered.firstIndex(where: { $0.id == photo.id }),
              reordered.indices.contains(destination)
        else { return }
        let item = reordered.remove(at: source)
        reordered.insert(item, at: destination)
        Task {
            if let refreshed = await model.reorder(rideID: ride.id, media: reordered) {
                media = Self.sorted(refreshed)
                await onChanged()
            }
        }
    }

    private func save() {
        Task {
            if await model.save(
                rideID: ride.id,
                title: title,
                notes: notes,
                effort: effort == 0 ? nil : effort,
                effortChanged: (effort == 0 ? nil : effort) != ride.perceivedExertion
            ) {
                await onChanged()
                dismiss()
            }
        }
    }

    private static func sorted(_ media: [RideMedia]) -> [RideMedia] {
        media.sorted { lhs, rhs in
            if lhs.role == "cover", rhs.role != "cover" { return true }
            if rhs.role == "cover", lhs.role != "cover" { return false }
            return lhs.sortOrder < rhs.sortOrder
        }
    }
}

@MainActor
@Observable
final class RideEditModel {
    private(set) var isSaving = false
    private(set) var isUploadingPhoto = false
    private(set) var errorMessage: String?
    var isBusy: Bool { isSaving || isUploadingPhoto }

    func present(_ message: String) { errorMessage = message }

    func save(
        rideID: String,
        title: String,
        notes: String,
        effort: Int? = nil,
        effortChanged: Bool = false
    ) async -> Bool {
        guard !isBusy else { return false }
        isSaving = true
        errorMessage = nil
        defer { isSaving = false }
        do {
            try await APIClient.shared.updateRideMetadata(
                rideId: rideID,
                title: title.trimmingCharacters(in: .whitespacesAndNewlines),
                notes: notes.trimmingCharacters(in: .whitespacesAndNewlines)
            )
            if effortChanged {
                try await APIClient.shared.updateRidePerceivedExertion(
                    rideId: rideID, value: effort
                )
            }
            return true
        } catch {
            errorMessage = PrivacyModel.message(for: error)
            return false
        }
    }

    func add(
        rideID: String,
        selection: RidePhotoSelection,
        sortOrder: Int
    ) async -> [RideMedia]? {
        guard !isBusy else { return nil }
        isUploadingPhoto = true
        errorMessage = nil
        defer { isUploadingPhoto = false }
        let descriptor = selection.descriptor.placed(at: sortOrder)
        do {
            let handle = try await APIClient.shared.rideMediaUploadInit(
                rideId: rideID,
                photo: descriptor
            )
            try await APIClient.shared.uploadToStorage(
                signedUrl: handle.signedUrl,
                data: selection.data,
                fileName: descriptor.fileName
            )
            _ = try await APIClient.shared.rideMediaUploadComplete(
                rideId: rideID,
                mediaId: descriptor.id
            )
            return try await APIClient.shared.rideMedia(rideId: rideID)
        } catch {
            errorMessage = PrivacyModel.message(for: error)
            return nil
        }
    }

    func setCover(rideID: String, mediaID: String) async -> [RideMedia]? {
        await mediaMutation {
            _ = try await APIClient.shared.setRideMediaCover(
                rideId: rideID,
                mediaId: mediaID
            )
            return try await APIClient.shared.rideMedia(rideId: rideID)
        }
    }

    func remove(rideID: String, mediaID: String) async -> [RideMedia]? {
        await mediaMutation {
            try await APIClient.shared.deleteRideMedia(rideId: rideID, mediaId: mediaID)
            return try await APIClient.shared.rideMedia(rideId: rideID)
        }
    }

    func reorder(rideID: String, media: [RideMedia]) async -> [RideMedia]? {
        await mediaMutation {
            let reordered = try await APIClient.shared.reorderRideMedia(
                rideId: rideID,
                media: media
            )
            if let first = reordered.first, first.role != "cover" {
                _ = try await APIClient.shared.setRideMediaCover(
                    rideId: rideID,
                    mediaId: first.id
                )
            }
            return try await APIClient.shared.rideMedia(rideId: rideID)
        }
    }

    private func mediaMutation(
        _ operation: () async throws -> [RideMedia]
    ) async -> [RideMedia]? {
        guard !isBusy else { return nil }
        isUploadingPhoto = true
        errorMessage = nil
        defer { isUploadingPhoto = false }
        do {
            return try await operation()
        } catch {
            errorMessage = PrivacyModel.message(for: error)
            return nil
        }
    }
}
