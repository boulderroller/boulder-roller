import PhotosUI
import SwiftUI

/// Owner-only profile editor behind the avatar sheet's pencil (bead
/// `boulderroller-v2-f4acp.1.9`): display name, neighborhood, photo.
///
/// Truth rules: the photo goes through the signed avatar lane (init →
/// storage PUT → complete) and appears only after `complete` returns the
/// refreshed profile — a storage PUT alone is never success. Failed writes
/// leave the previous profile standing and say so. Server responses are the
/// only state adopted; nothing renders optimistically.
struct ProfileEditSheet: View {
    @Environment(AppSession.self) private var session
    @Environment(\.dismiss) private var dismiss

    @State private var name: String = ""
    @State private var neighborhood: String = ""
    @State private var bio: String = ""
    @State private var loadedFromUser = false
    @State private var saving = false
    @State private var saveErrorMessage: String?
    @State private var pickedItem: PhotosPickerItem?
    @State private var confirmingPhotoRemoval = false
    @State private var avatarUpload = AvatarUploadModel()

    var body: some View {
        ZStack {
            Theme.sheet.ignoresSafeArea()
            ScrollView {
                VStack(alignment: .leading, spacing: 0) {
                    SheetHeader(
                        title: "Profile",
                        doneEnabled: !saving && !avatarUpload.isUploading,
                        onDone: save
                    )
                    .padding(.top, 6)

                    VStack(alignment: .leading, spacing: 0) {
                        photoBlock
                        fieldsBlock

                        if let saveErrorMessage {
                            GroupFooter(text: saveErrorMessage)
                        }
                    }
                    .padding(.horizontal, Theme.margin)
                    .padding(.top, 18)
                    .padding(.bottom, 32)
                }
            }
        }
        .onAppear(perform: prefill)
        .onChange(of: pickedItem) { _, item in
            guard let item else { return }
            handlePickedPhoto(item)
        }
        .confirmationDialog(
            "Remove photo?",
            isPresented: $confirmingPhotoRemoval,
            titleVisibility: .visible
        ) {
            Button("Remove Photo", role: .destructive) { removePhoto() }
            Button("Cancel", role: .cancel) {}
        }
        .interactiveDismissDisabled(saving || avatarUpload.isUploading)
    }

    // MARK: Photo (signed avatar lane; states, never fake success)

    private var photoBlock: some View {
        VStack(spacing: 8) {
            PhotosPicker(
                selection: $pickedItem,
                matching: .images,
                photoLibrary: .shared()
            ) {
                ZStack(alignment: .bottomTrailing) {
                    AvatarView(
                        name: session.currentUser?.shownName,
                        url: session.currentUser?.avatarUrl.flatMap(URL.init),
                        size: 72
                    )
                    Image(systemName: "camera.fill")
                        .font(.caption2)
                        .foregroundStyle(Theme.ink)
                        .frame(width: 22, height: 22)
                        .background(Circle().fill(Theme.card))
                        .overlay(Circle().stroke(Theme.sheet, lineWidth: 2))
                        .accessibilityHidden(true)
                }
            }
            .disabled(avatarUpload.isUploading || saving)
            .accessibilityLabel(
                session.currentUser?.avatarUrl == nil ? "Add photo" : "Change photo"
            )

            switch avatarUpload.phase {
            case .uploading:
                HStack(spacing: 8) {
                    ProgressView()
                        .controlSize(.small)
                        .tint(Theme.gray)
                    Text("Uploading…")
                        .font(.caption2)
                        .foregroundStyle(Theme.gray)
                }
                .accessibilityElement(children: .combine)
            case let .failed(message):
                Text(message)
                    .font(.caption2)
                    .foregroundStyle(Theme.gray)
                    .multilineTextAlignment(.center)
            case .idle:
                if session.currentUser?.avatarUrl != nil {
                    Button {
                        confirmingPhotoRemoval = true
                    } label: {
                        Text("Remove Photo")
                            .font(.caption)
                            .foregroundStyle(Theme.gray)
                            .frame(minHeight: 30)
                    }
                    .buttonStyle(.plain)
                    .disabled(saving)
                }
            }
        }
        .frame(maxWidth: .infinity)
        .padding(.bottom, 18)
    }

    private func handlePickedPhoto(_ item: PhotosPickerItem) {
        let mimeType = item.supportedContentTypes
            .compactMap(\.preferredMIMEType)
            .first ?? "image/jpeg"
        Task {
            defer { pickedItem = nil }
            guard let data = try? await item.loadTransferable(type: Data.self) else {
                avatarUpload.presentLocalFailure("Couldn’t read that photo.")
                return
            }
            if let updated = await avatarUpload.upload(data: data, mimeType: mimeType) {
                session.adoptUpdatedUser(updated)
            }
        }
    }

    private func removePhoto() {
        Task {
            if let updated = await avatarUpload.remove() {
                session.adoptUpdatedUser(updated)
            }
        }
    }

    // MARK: Identity fields (server limits mirrored exactly)

    private var fieldsBlock: some View {
        GroupCard {
            TextField(
                "",
                text: $name,
                prompt: Text("Name").foregroundStyle(Theme.gray2)
            )
            .font(.body)
            .foregroundStyle(Theme.ink)
            .textInputAutocapitalization(.words)
            .padding(.horizontal, 14)
            .frame(minHeight: Theme.row)
            .onChange(of: name) { _, new in
                if new.count > ProfileEditContract.maxDisplayNameLength {
                    name = String(new.prefix(ProfileEditContract.maxDisplayNameLength))
                }
            }
            .accessibilityLabel("Name")

            RowSeparator()

            TextField(
                "",
                text: $neighborhood,
                prompt: Text("Neighborhood").foregroundStyle(Theme.gray2)
            )
            .font(.body)
            .foregroundStyle(Theme.ink)
            .textInputAutocapitalization(.words)
            .padding(.horizontal, 14)
            .frame(minHeight: Theme.row)
            .onChange(of: neighborhood) { _, new in
                if new.count > ProfileEditContract.maxLocationLength {
                    neighborhood = String(new.prefix(ProfileEditContract.maxLocationLength))
                }
            }
            .accessibilityLabel("Neighborhood")

            RowSeparator()

            TextField(
                "",
                text: $bio,
                prompt: Text("Bio").foregroundStyle(Theme.gray2),
                axis: .vertical
            )
            .font(.body)
            .foregroundStyle(Theme.ink)
            .lineLimit(2...6)
            .padding(.horizontal, 14)
            .padding(.vertical, 12)
            .frame(minHeight: Theme.row)
            .onChange(of: bio) { _, new in
                if new.count > ProfileEditContract.maxBioLength {
                    bio = String(new.prefix(ProfileEditContract.maxBioLength))
                }
            }
            .accessibilityLabel("Bio")
        }
    }

    private func prefill() {
        guard !loadedFromUser, let user = session.currentUser else { return }
        loadedFromUser = true
        name = user.displayName ?? ""
        neighborhood = user.location ?? ""
        bio = user.bio ?? ""
    }

    /// Done: write only what changed; adopt the server's returned profile;
    /// a failure keeps the sheet open with the edits and the prior profile
    /// intact. Nothing changed = plain close.
    private func save() {
        guard !saving, !avatarUpload.isUploading else { return }
        guard let user = session.currentUser else {
            dismiss()
            return
        }
        let trimmedName = name.trimmingCharacters(in: .whitespacesAndNewlines)
        let trimmedNeighborhood = neighborhood.trimmingCharacters(in: .whitespacesAndNewlines)
        let trimmedBio = bio.trimmingCharacters(in: .whitespacesAndNewlines)
        let nameChanged = trimmedName != (user.displayName ?? "")
        let neighborhoodChanged = trimmedNeighborhood != (user.location ?? "")
        let bioChanged = trimmedBio != (user.bio ?? "")
        guard nameChanged || neighborhoodChanged || bioChanged else {
            dismiss()
            return
        }

        saveErrorMessage = nil
        saving = true
        Task {
            do {
                let updated = try await APIClient.shared.updateProfile(
                    displayName: nameChanged ? .some(trimmedName.isEmpty ? nil : trimmedName) : nil,
                    location: neighborhoodChanged
                        ? .some(trimmedNeighborhood.isEmpty ? nil : trimmedNeighborhood)
                        : nil,
                    bio: bioChanged ? .some(trimmedBio.isEmpty ? nil : trimmedBio) : nil
                )
                saving = false
                session.adoptUpdatedUser(updated)
                dismiss()
            } catch {
                saving = false
                saveErrorMessage = PrivacyModel.message(for: error)
            }
        }
    }
}

// MARK: - Avatar upload lifecycle (init → storage PUT → complete)

/// The avatar media lane's client state machine, kept view-free so the
/// contract is unit-testable: preflight mirrors the server's allowed types
/// and 15 MB cap; success exists only when `complete` returns the refreshed
/// profile; every failure is a standing, stated state.
@MainActor
@Observable
final class AvatarUploadModel {
    enum Phase: Equatable {
        case idle
        case uploading
        case failed(String)
    }

    private(set) var phase: Phase = .idle

    var isUploading: Bool { phase == .uploading }

    // Injected endpoints (tests swap these; production = API client).
    @ObservationIgnored var initUpload: (
        _ mimeType: String, _ fileName: String?, _ fileSize: Int
    ) async throws -> AvatarUploadInit = {
        try await APIClient.shared.avatarUploadInit(
            mimeType: $0, fileName: $1, fileSize: $2
        )
    }
    @ObservationIgnored var putToStorage: (
        _ signedUrl: String, _ data: Data, _ fileName: String
    ) async throws -> Void = {
        try await APIClient.shared.uploadToStorage(signedUrl: $0, data: $1, fileName: $2)
    }
    @ObservationIgnored var completeUpload: (_ uploadId: String) async throws -> User = {
        try await APIClient.shared.avatarUploadComplete(uploadId: $0)
    }
    @ObservationIgnored var deleteAvatar: () async throws -> User = {
        try await APIClient.shared.deleteAvatar()
    }

    /// Client-side mirror of the server's media contract, checked before any
    /// network call. Returns the truthful refusal, or nil when acceptable.
    nonisolated static func preflightFailure(mimeType: String, byteCount: Int) -> String? {
        if !AvatarMediaContract.isAllowed(mimeType: mimeType) {
            return "Avatar must be a JPEG, PNG, WebP, HEIC, or HEIF image."
        }
        if byteCount <= 0 {
            return "Couldn’t read that photo."
        }
        if byteCount > AvatarMediaContract.maxFileSizeBytes {
            return "Avatar must be 15 MB or smaller."
        }
        return nil
    }

    /// Runs the full lane. Returns the server's refreshed profile on
    /// success; otherwise sets a standing failed phase and returns nil.
    func upload(data: Data, mimeType: String, fileName: String? = nil) async -> User? {
        guard phase != .uploading else { return nil }
        let normalized = AvatarMediaContract.normalizedMimeType(mimeType)
        if let refusal = Self.preflightFailure(mimeType: normalized, byteCount: data.count) {
            phase = .failed(refusal)
            return nil
        }
        phase = .uploading
        do {
            let handle = try await initUpload(normalized, fileName, data.count)
            try await putToStorage(
                handle.signedUrl,
                data,
                fileName ?? "avatar.\(Self.fileExtension(for: normalized))"
            )
            let updated = try await completeUpload(handle.uploadId)
            phase = .idle
            return updated
        } catch {
            phase = .failed(PrivacyModel.message(for: error))
            return nil
        }
    }

    /// Removes the avatar server-side; the caller adopts the returned
    /// profile. Failure is a standing failed phase, never a cleared photo.
    func remove() async -> User? {
        guard phase != .uploading else { return nil }
        phase = .uploading
        do {
            let updated = try await deleteAvatar()
            phase = .idle
            return updated
        } catch {
            phase = .failed(PrivacyModel.message(for: error))
            return nil
        }
    }

    /// A local (pre-network) failure surfaced through the same phase state.
    func presentLocalFailure(_ message: String) {
        guard phase != .uploading else { return }
        phase = .failed(message)
    }

    nonisolated static func fileExtension(for mimeType: String) -> String {
        switch AvatarMediaContract.normalizedMimeType(mimeType) {
        case "image/png": return "png"
        case "image/webp": return "webp"
        case "image/heic": return "heic"
        case "image/heif": return "heif"
        default: return "jpg"
        }
    }
}
