import CryptoKit
import Foundation

enum RideUploadPhase: String, Codable, Equatable, Sendable {
    case awaitingPrivacyReview
    case queued
    case waitingForAuthentication
    case initializing
    case transferring
    case completing
    case processing
    case underReview
    case retryable
    case failed
    case final
}

enum RideRevealState: String, Codable, Equatable, Sendable {
    case none
    case queued
    case consumed
}

struct LocalRideSummary: Codable, Equatable, Hashable, Sendable {
    let startedAt: Date
    let distanceM: Double?
    let elevationM: Double?
    let durationS: Double?
}

enum RidePhotoContract {
    static let maxPhotos = 6
    static let maxFileSizeBytes = 15 * 1024 * 1024
    static let allowedMimeTypes: Set<String> = [
        "image/jpeg", "image/png", "image/webp", "image/heic", "image/heif",
    ]

    static func normalizedMimeType(_ raw: String) -> String {
        let base = raw.split(separator: ";", maxSplits: 1)[0]
            .trimmingCharacters(in: .whitespaces)
            .lowercased()
        return base == "image/jpg" ? "image/jpeg" : base
    }

    static func fileExtension(for mimeType: String) -> String {
        switch normalizedMimeType(mimeType) {
        case "image/png": return "png"
        case "image/webp": return "webp"
        case "image/heic": return "heic"
        case "image/heif": return "heif"
        default: return "jpg"
        }
    }
}

struct RidePhotoDescriptor: Codable, Equatable, Identifiable, Sendable {
    let id: String
    let fileName: String
    let mimeType: String
    let byteCount: Int
    let fileHash: String
    let sortOrder: Int
    let role: String

    var storageFileName: String {
        "\(id).\(RidePhotoContract.fileExtension(for: mimeType))"
    }

    func placed(at index: Int) -> RidePhotoDescriptor {
        RidePhotoDescriptor(
            id: id,
            fileName: fileName,
            mimeType: mimeType,
            byteCount: byteCount,
            fileHash: fileHash,
            sortOrder: index,
            role: index == 0 ? "cover" : "photo"
        )
    }
}

struct RidePhotoSelection: Equatable, Identifiable, Sendable {
    let id: String
    let fileName: String
    let mimeType: String
    let data: Data

    init(
        id: String = UUID().uuidString.lowercased(),
        fileName: String,
        mimeType: String,
        data: Data
    ) throws {
        let normalized = RidePhotoContract.normalizedMimeType(mimeType)
        guard UUID(uuidString: id) != nil,
              RidePhotoContract.allowedMimeTypes.contains(normalized),
              !data.isEmpty,
              data.count <= RidePhotoContract.maxFileSizeBytes
        else { throw RideUploadStoreError.invalidPhoto }
        self.id = id.lowercased()
        let safeName = fileName
            .replacingOccurrences(of: "\\", with: "_")
            .replacingOccurrences(of: "/", with: "_")
            .replacingOccurrences(of: "\"", with: "_")
            .replacingOccurrences(of: "\r", with: "_")
            .replacingOccurrences(of: "\n", with: "_")
        self.fileName = safeName.isEmpty
            ? "ride-photo.\(RidePhotoContract.fileExtension(for: normalized))"
            : safeName
        self.mimeType = normalized
        self.data = data
    }

    var descriptor: RidePhotoDescriptor {
        RidePhotoDescriptor(
            id: id,
            fileName: fileName,
            mimeType: mimeType,
            byteCount: data.count,
            fileHash: FileRideUploadJobStore.sha256(data),
            sortOrder: 0,
            role: "cover"
        )
    }
}

/// Rider-authored fields captured at the same one-time boundary as privacy.
/// The descriptors are immutable after approval; their exact bytes live in
/// the owner-bound job directory and are verified before every upload.
struct RidePostRideDraft: Codable, Equatable, Sendable {
    let title: String?
    let notes: String?
    let photos: [RidePhotoDescriptor]

    init(title: String?, notes: String?, photos: [RidePhotoDescriptor]) {
        self.title = Self.normalized(title)
        self.notes = Self.normalized(notes)
        self.photos = photos.enumerated().map { index, photo in
            photo.placed(at: index)
        }
    }

    static let empty = RidePostRideDraft(title: nil, notes: nil, photos: [])

    private static func normalized(_ value: String?) -> String? {
        guard let trimmed = value?.trimmingCharacters(in: .whitespacesAndNewlines),
              !trimmed.isEmpty
        else { return nil }
        return trimmed
    }
}

struct RideUploadJob: Codable, Equatable, Identifiable, Sendable {
    let id: String
    let ownerID: String
    let ownerWallet: String
    let fileName: String
    let fileType: String
    let fileHash: String
    let fileSize: Int
    let sourceFileName: String
    let localSummary: LocalRideSummary
    let createdAt: Date
    /// Present together only for a first-party recorder stop. Legacy and
    /// manual-import jobs decode as nil and retry with that exact provenance.
    let parserVersion: UInt32?
    let preliminaryRideHash: String?

    /// Nil only before the rider's explicit publication review (or on a
    /// legacy job created by an older app). Once selected it is immutable for
    /// the entire server handoff and retry lifecycle.
    var publication: RidePublicationSettings?
    var postRideDraft: RidePostRideDraft?

    var updatedAt: Date
    var phase: RideUploadPhase
    var attemptedServerHandoff: Bool
    var signedURL: String?
    var signedURLExpiresAt: Date?
    var serverRideID: String?
    var authoritativeStatus: String?
    var attemptCount: Int
    var nextRetryAt: Date?
    var lastError: String?
    var canRetry: Bool
    var revealState: RideRevealState
    var reveal: RevealData?

    var isRevealEligible: Bool {
        phase == .final && revealState == .queued && reveal != nil
    }

    init(
        id: String,
        ownerID: String,
        ownerWallet: String,
        fileName: String,
        fileType: String,
        fileHash: String,
        fileSize: Int,
        sourceFileName: String,
        localSummary: LocalRideSummary,
        createdAt: Date,
        updatedAt: Date,
        phase: RideUploadPhase,
        attemptedServerHandoff: Bool,
        signedURL: String?,
        signedURLExpiresAt: Date?,
        serverRideID: String?,
        authoritativeStatus: String?,
        attemptCount: Int,
        nextRetryAt: Date?,
        lastError: String?,
        canRetry: Bool,
        revealState: RideRevealState,
        reveal: RevealData?,
        parserVersion: UInt32? = nil,
        preliminaryRideHash: String? = nil,
        publication: RidePublicationSettings? = nil,
        postRideDraft: RidePostRideDraft? = nil
    ) {
        self.id = id
        self.ownerID = ownerID
        self.ownerWallet = ownerWallet
        self.fileName = fileName
        self.fileType = fileType
        self.fileHash = fileHash
        self.fileSize = fileSize
        self.sourceFileName = sourceFileName
        self.localSummary = localSummary
        self.createdAt = createdAt
        self.parserVersion = parserVersion
        self.preliminaryRideHash = preliminaryRideHash
        self.publication = publication
        self.postRideDraft = postRideDraft
        self.updatedAt = updatedAt
        self.phase = phase
        self.attemptedServerHandoff = attemptedServerHandoff
        self.signedURL = signedURL
        self.signedURLExpiresAt = signedURLExpiresAt
        self.serverRideID = serverRideID
        self.authoritativeStatus = authoritativeStatus
        self.attemptCount = attemptCount
        self.nextRetryAt = nextRetryAt
        self.lastError = lastError
        self.canRetry = canRetry
        self.revealState = revealState
        self.reveal = reveal
    }

    private enum CodingKeys: String, CodingKey {
        case id, ownerID, ownerWallet, fileName, fileType, fileHash, fileSize
        case sourceFileName, localSummary, createdAt, parserVersion, preliminaryRideHash
        case updatedAt, phase, attemptedServerHandoff, signedURL, signedURLExpiresAt
        case serverRideID, authoritativeStatus, attemptCount, nextRetryAt, lastError
        case canRetry, revealState, reveal, publication, postRideDraft
    }

    init(from decoder: Decoder) throws {
        let values = try decoder.container(keyedBy: CodingKeys.self)
        self.init(
            id: try values.decode(String.self, forKey: .id),
            ownerID: try values.decode(String.self, forKey: .ownerID),
            ownerWallet: try values.decode(String.self, forKey: .ownerWallet),
            fileName: try values.decode(String.self, forKey: .fileName),
            fileType: try values.decode(String.self, forKey: .fileType),
            fileHash: try values.decode(String.self, forKey: .fileHash),
            fileSize: try values.decode(Int.self, forKey: .fileSize),
            sourceFileName: try values.decode(String.self, forKey: .sourceFileName),
            localSummary: try values.decode(LocalRideSummary.self, forKey: .localSummary),
            createdAt: try values.decode(Date.self, forKey: .createdAt),
            updatedAt: try values.decode(Date.self, forKey: .updatedAt),
            phase: try values.decode(RideUploadPhase.self, forKey: .phase),
            attemptedServerHandoff: try values.decode(Bool.self, forKey: .attemptedServerHandoff),
            signedURL: try values.decodeIfPresent(String.self, forKey: .signedURL),
            signedURLExpiresAt: try values.decodeIfPresent(Date.self, forKey: .signedURLExpiresAt),
            serverRideID: try values.decodeIfPresent(String.self, forKey: .serverRideID),
            authoritativeStatus: try values.decodeIfPresent(String.self, forKey: .authoritativeStatus),
            attemptCount: try values.decode(Int.self, forKey: .attemptCount),
            nextRetryAt: try values.decodeIfPresent(Date.self, forKey: .nextRetryAt),
            lastError: try values.decodeIfPresent(String.self, forKey: .lastError),
            canRetry: try values.decode(Bool.self, forKey: .canRetry),
            revealState: try values.decode(RideRevealState.self, forKey: .revealState),
            reveal: try values.decodeIfPresent(RevealData.self, forKey: .reveal),
            parserVersion: try values.decodeIfPresent(UInt32.self, forKey: .parserVersion),
            preliminaryRideHash: try values.decodeIfPresent(
                String.self,
                forKey: .preliminaryRideHash
            ),
            publication: try values.decodeIfPresent(
                RidePublicationSettings.self,
                forKey: .publication
            ),
            postRideDraft: try values.decodeIfPresent(
                RidePostRideDraft.self,
                forKey: .postRideDraft
            )
        )
    }

    func encode(to encoder: Encoder) throws {
        var values = encoder.container(keyedBy: CodingKeys.self)
        try values.encode(id, forKey: .id)
        try values.encode(ownerID, forKey: .ownerID)
        try values.encode(ownerWallet, forKey: .ownerWallet)
        try values.encode(fileName, forKey: .fileName)
        try values.encode(fileType, forKey: .fileType)
        try values.encode(fileHash, forKey: .fileHash)
        try values.encode(fileSize, forKey: .fileSize)
        try values.encode(sourceFileName, forKey: .sourceFileName)
        try values.encode(localSummary, forKey: .localSummary)
        try values.encode(createdAt, forKey: .createdAt)
        try values.encodeIfPresent(parserVersion, forKey: .parserVersion)
        try values.encodeIfPresent(preliminaryRideHash, forKey: .preliminaryRideHash)
        try values.encode(updatedAt, forKey: .updatedAt)
        try values.encode(phase, forKey: .phase)
        try values.encode(attemptedServerHandoff, forKey: .attemptedServerHandoff)
        try values.encodeIfPresent(signedURL, forKey: .signedURL)
        try values.encodeIfPresent(signedURLExpiresAt, forKey: .signedURLExpiresAt)
        try values.encodeIfPresent(serverRideID, forKey: .serverRideID)
        try values.encodeIfPresent(authoritativeStatus, forKey: .authoritativeStatus)
        try values.encode(attemptCount, forKey: .attemptCount)
        try values.encodeIfPresent(nextRetryAt, forKey: .nextRetryAt)
        try values.encodeIfPresent(lastError, forKey: .lastError)
        try values.encode(canRetry, forKey: .canRetry)
        try values.encode(revealState, forKey: .revealState)
        try values.encodeIfPresent(reveal, forKey: .reveal)
        try values.encodeIfPresent(publication, forKey: .publication)
        try values.encodeIfPresent(postRideDraft, forKey: .postRideDraft)
    }
}

struct PendingRideReveal: Identifiable, Equatable, Sendable {
    let id: String
    let ownerID: String
    let claimID: String
    let authoritativeRideID: String
    let data: RevealData
}

enum RideUploadStoreError: LocalizedError, Equatable {
    case invalidOwner
    case invalidIdentifier
    case missingSource
    case sourceHashChanged
    case immutableMetadataChanged
    case invalidRevealClaim
    case invalidAttestationStamp
    case invalidPhoto

    var errorDescription: String? {
        switch self {
        case .invalidOwner, .invalidIdentifier:
            return "Ride storage is unavailable"
        case .missingSource, .sourceHashChanged, .immutableMetadataChanged:
            return "Ride evidence changed"
        case .invalidRevealClaim:
            return "Ride reveal is unavailable"
        case .invalidAttestationStamp:
            return "Ride attestation is unavailable"
        case .invalidPhoto:
            return "That photo can’t be added"
        }
    }
}

protocol RideUploadJobStoring: Sendable {
    func create(_ job: RideUploadJob, sourceBytes: Data) async throws
    func job(id: String, ownerID: String) async throws -> RideUploadJob?
    func jobs(ownerID: String) async throws -> [RideUploadJob]
    func save(_ job: RideUploadJob) async throws
    func saveApproval(
        _ job: RideUploadJob,
        photoBytes: [String: Data]
    ) async throws
    func sourceURL(for job: RideUploadJob) async throws -> URL
    func photoURL(
        for photo: RidePhotoDescriptor,
        job: RideUploadJob
    ) async throws -> URL
    func claimNextReveal(owner: RecordingOwner) async throws -> PendingRideReveal?
    func acknowledgeReveal(
        id: String,
        owner: RecordingOwner,
        claimID: String,
        authoritativeRideID: String
    ) async throws
}

private struct ActiveRevealClaim: Codable, Equatable, Sendable {
    let version: Int
    let claimID: String
    let jobID: String
    let authoritativeKeyHash: String
    /// Nil only for a claim written by an older app. Its immutable job row is
    /// then the exact-wallet authority.
    let ownerWallet: String?
}

private struct RevealAcknowledgement: Codable, Equatable, Sendable {
    let version: Int
    let claimID: String
    let jobID: String
    let authoritativeKeyHash: String
    /// Optional so existing durable acknowledgement markers remain readable.
    let ownerWallet: String?
}

/// Owner-scoped local ride custody. Each immutable source file and its job
/// metadata use iOS Data Protection while remaining readable after first
/// unlock so an eligible background transfer can continue. The exact source
/// bytes are never rewritten during retry or reconciliation.
actor FileRideUploadJobStore: RideUploadJobStoring {
    private let rootURL: URL
    private let fileManager: FileManager
    private let encoder: JSONEncoder
    private let decoder: JSONDecoder
    private let beforePublish: @Sendable () throws -> Void

    init(
        rootURL: URL? = nil,
        fileManager: FileManager = .default,
        beforePublish: @escaping @Sendable () throws -> Void = {}
    ) {
        self.fileManager = fileManager
        self.beforePublish = beforePublish
        if let rootURL {
            self.rootURL = rootURL
        } else {
            let applicationSupport = fileManager.urls(
                for: .applicationSupportDirectory,
                in: .userDomainMask
            )[0]
            // Default root is rider evidence; test processes are walled into
            // an isolated temp root (ProcessSandbox).
            self.rootURL = ProcessSandbox.isolatedIfTesting(
                applicationSupport.appendingPathComponent(
                    "RideUploads",
                    isDirectory: true
                ),
                label: "RideUploads"
            )
        }

        let encoder = JSONEncoder()
        encoder.outputFormatting = [.sortedKeys]
        encoder.dateEncodingStrategy = .iso8601
        self.encoder = encoder

        let decoder = JSONDecoder()
        decoder.dateDecodingStrategy = .iso8601
        self.decoder = decoder
    }

    func create(_ job: RideUploadJob, sourceBytes: Data) throws {
        try validateIdentifier(job.id)
        guard !job.ownerID.isEmpty else { throw RideUploadStoreError.invalidOwner }
        guard Self.sha256(sourceBytes) == job.fileHash, sourceBytes.count == job.fileSize else {
            throw RideUploadStoreError.sourceHashChanged
        }
        try validateAttestationStamp(job)

        let directory = jobDirectory(id: job.id, ownerID: job.ownerID)
        let ownerDirectory = directory.deletingLastPathComponent()
        try protectDirectory(ownerDirectory)
        guard !fileManager.fileExists(atPath: directory.path) else {
            throw RideUploadStoreError.immutableMetadataChanged
        }

        // Publish source + metadata as one directory rename. A suspension or
        // process kill can leave, at worst, an ignored staging directory;
        // it can never expose evidence without the persisted job that owns it.
        let staging = ownerDirectory.appendingPathComponent(
            ".\(job.id).\(UUID().uuidString.lowercased()).staging",
            isDirectory: true
        )
        try protectDirectory(staging)
        do {
            let sourceURL = staging.appendingPathComponent(job.sourceFileName)
            try sourceBytes.write(
                to: sourceURL,
                options: [.atomic, .completeFileProtectionUntilFirstUserAuthentication]
            )
            try write(job, to: staging.appendingPathComponent("job.json"))
            try beforePublish()
            try fileManager.moveItem(at: staging, to: directory)
        } catch {
            // `staging` is an exact, validated child created by this call.
            // Never remove an existing published job on a failed create.
            try? fileManager.removeItem(at: staging)
            throw error
        }
    }

    func job(id: String, ownerID: String) throws -> RideUploadJob? {
        try validateIdentifier(id)
        guard !ownerID.isEmpty else { throw RideUploadStoreError.invalidOwner }
        let metadata = jobDirectory(id: id, ownerID: ownerID)
            .appendingPathComponent("job.json")
        guard fileManager.fileExists(atPath: metadata.path) else { return nil }
        let decoded = try decoder.decode(RideUploadJob.self, from: Data(contentsOf: metadata))
        guard decoded.id == id, decoded.ownerID == ownerID else {
            throw RideUploadStoreError.invalidOwner
        }
        try validateAttestationStamp(decoded)
        return decoded
    }

    func jobs(ownerID: String) throws -> [RideUploadJob] {
        guard !ownerID.isEmpty else { throw RideUploadStoreError.invalidOwner }
        let ownerDirectory = rootURL.appendingPathComponent(Self.ownerKey(ownerID), isDirectory: true)
        guard fileManager.fileExists(atPath: ownerDirectory.path) else { return [] }
        let directories = try fileManager.contentsOfDirectory(
            at: ownerDirectory,
            includingPropertiesForKeys: [.isDirectoryKey],
            options: [.skipsHiddenFiles]
        )
        return try directories.compactMap { directory in
            let metadata = directory.appendingPathComponent("job.json")
            guard fileManager.fileExists(atPath: metadata.path) else { return nil }
            let decoded = try decoder.decode(RideUploadJob.self, from: Data(contentsOf: metadata))
            guard decoded.ownerID == ownerID else { throw RideUploadStoreError.invalidOwner }
            try validateAttestationStamp(decoded)
            return decoded
        }
        .sorted { $0.createdAt < $1.createdAt }
    }

    func accountDeletionRecords(owner: RecordingOwner) throws -> [AccountDeletionUploadRecord] {
        guard !owner.id.isEmpty, !owner.wallet.isEmpty else {
            throw RideUploadStoreError.invalidOwner
        }
        try validateAccountDeletionRevealArtifacts(owner: owner)
        let artifacts = try accountDeletionArtifacts(owner: owner)
            .filter { $0.job.ownerWallet == owner.wallet }
        guard Set(artifacts.map { $0.job.id }).count == artifacts.count else {
            throw RideUploadStoreError.immutableMetadataChanged
        }
        return artifacts.map { artifact in
            let job = artifact.job
            return AccountDeletionUploadRecord(
                id: job.id,
                fileName: job.fileName,
                startedAt: job.localSummary.startedAt,
                phase: job.phase
            )
        }
    }

    /// Resolve only the multipart body IDs presented by the transfer layer.
    /// Published jobs and crash-left staging directories are both accepted
    /// only when their metadata is intact and their owner-directory hash
    /// agrees. A body without exactly one such row remains unattributed.
    func accountDeletionKnownJobIDs(_ candidates: Set<String>) throws -> Set<String> {
        guard !candidates.isEmpty else { return [] }
        guard candidates.allSatisfy({ UUID(uuidString: $0) != nil }) else {
            throw RideUploadStoreError.invalidIdentifier
        }
        guard fileManager.fileExists(atPath: rootURL.path) else { return [] }
        let ownerDirectories = try fileManager.contentsOfDirectory(
            at: rootURL,
            includingPropertiesForKeys: [.isDirectoryKey],
            options: []
        )
        var matches: [String: RideUploadJob] = [:]
        for ownerDirectory in ownerDirectories {
            guard (try ownerDirectory.resourceValues(forKeys: [.isDirectoryKey])).isDirectory == true else {
                continue
            }
            let children = try fileManager.contentsOfDirectory(
                at: ownerDirectory,
                includingPropertiesForKeys: [.isDirectoryKey],
                options: []
            )
            for child in children {
                let name = child.lastPathComponent
                let candidate = candidates.first { id in
                    name == id || (name.hasPrefix(".\(id).") && name.hasSuffix(".staging"))
                }
                guard let candidate else { continue }
                guard (try child.resourceValues(forKeys: [.isDirectoryKey])).isDirectory == true else {
                    throw RideUploadStoreError.missingSource
                }
                let metadata = child.appendingPathComponent("job.json")
                guard fileManager.fileExists(atPath: metadata.path) else {
                    throw RideUploadStoreError.missingSource
                }
                let job = try decoder.decode(RideUploadJob.self, from: Data(contentsOf: metadata))
                guard job.id == candidate,
                      Self.ownerKey(job.ownerID) == ownerDirectory.lastPathComponent
                else { throw RideUploadStoreError.invalidOwner }
                try validateAttestationStamp(job)
                guard matches[candidate] == nil else {
                    throw RideUploadStoreError.immutableMetadataChanged
                }
                matches[candidate] = job
            }
        }
        return Set(matches.keys)
    }

    /// Account deletion is the only aggregate purge. Every visible job row is
    /// decoded first, then only directories whose immutable ID+wallet match
    /// the ratified owner are removed. A reused user ID with another wallet
    /// remains untouched.
    func purgeAccount(owner: RecordingOwner) throws {
        guard !owner.id.isEmpty, !owner.wallet.isEmpty else {
            throw RideUploadStoreError.invalidOwner
        }
        try validateAccountDeletionRevealArtifacts(owner: owner)
        let artifacts = try accountDeletionArtifacts(owner: owner)
        for artifact in artifacts where artifact.job.ownerWallet == owner.wallet {
            if fileManager.fileExists(atPath: artifact.directory.path) {
                try fileManager.removeItem(at: artifact.directory)
            }
        }
        let revealDirectory = revealOwnerDirectory(owner)
        if fileManager.fileExists(atPath: revealDirectory.path) {
            try fileManager.removeItem(at: revealDirectory)
        }
        let remaining = try accountDeletionArtifacts(owner: owner)
        guard !remaining.contains(where: { $0.job.ownerWallet == owner.wallet }),
              !fileManager.fileExists(atPath: revealDirectory.path)
        else { throw AccountDeletionLocalCleanupError.verificationFailed }
    }

    /// Account deletion cannot inherit the normal list view's hidden-file
    /// filter. A process kill may leave a `.staging` directory containing
    /// source bytes. Every child must carry decodable immutable owner
    /// metadata; an orphan that cannot be attributed to this exact wallet is
    /// a support state, never permission for a broad owner-ID purge.
    private func accountDeletionArtifacts(
        owner: RecordingOwner
    ) throws -> [(directory: URL, job: RideUploadJob)] {
        let ownerDirectory = rootURL.appendingPathComponent(Self.ownerKey(owner.id), isDirectory: true)
        guard fileManager.fileExists(atPath: ownerDirectory.path) else { return [] }
        let directories = try fileManager.contentsOfDirectory(
            at: ownerDirectory,
            includingPropertiesForKeys: [.isDirectoryKey],
            options: []
        )
        return try directories.compactMap { directory in
            switch directory.lastPathComponent {
            case ".reveal-owners":
                guard (try directory.resourceValues(forKeys: [.isDirectoryKey])).isDirectory == true else {
                    throw RideUploadStoreError.invalidRevealClaim
                }
                return nil
            case ".reveal-consumption", "active-reveal-claim.json":
                // These pre-wallet paths cannot be attributed to one exact
                // wallet. Support must reconcile them before deletion; the
                // exact-owner purge may never erase them by inference.
                throw RideUploadStoreError.invalidRevealClaim
            default:
                break
            }
            let values = try directory.resourceValues(forKeys: [.isDirectoryKey])
            guard values.isDirectory == true else {
                throw RideUploadStoreError.immutableMetadataChanged
            }
            let metadata = directory.appendingPathComponent("job.json")
            guard fileManager.fileExists(atPath: metadata.path) else {
                throw RideUploadStoreError.missingSource
            }
            let job = try decoder.decode(
                RideUploadJob.self,
                from: Data(contentsOf: metadata)
            )
            guard job.ownerID == owner.id else {
                throw RideUploadStoreError.invalidOwner
            }
            try validateIdentifier(job.id)
            try validateAttestationStamp(job)
            return (directory, job)
        }
    }

    /// The wallet-scoped reveal container is known account data, but it is
    /// not a ride job directory. Validate every exact-wallet child before the
    /// purge and leave sibling wallet hashes untouched. Legacy owner-ID-only
    /// reveal artifacts are rejected by `accountDeletionArtifacts` because
    /// they cannot safely be assigned to this wallet.
    private func validateAccountDeletionRevealArtifacts(owner: RecordingOwner) throws {
        let exactDirectory = revealOwnerDirectory(owner)
        guard fileManager.fileExists(atPath: exactDirectory.path) else { return }
        guard (try exactDirectory.resourceValues(forKeys: [.isDirectoryKey])).isDirectory == true else {
            throw RideUploadStoreError.invalidRevealClaim
        }
        let children = try fileManager.contentsOfDirectory(
            at: exactDirectory,
            includingPropertiesForKeys: [.isDirectoryKey],
            options: []
        )
        for child in children {
            switch child.lastPathComponent {
            case "active-reveal-claim.json":
                guard (try child.resourceValues(forKeys: [.isDirectoryKey])).isDirectory != true else {
                    throw RideUploadStoreError.invalidRevealClaim
                }
                let claim = try decodeActiveRevealClaim(at: child)
                guard claim.ownerWallet == nil || claim.ownerWallet == owner.wallet else {
                    throw RideUploadStoreError.invalidRevealClaim
                }
            case ".reveal-consumption":
                guard (try child.resourceValues(forKeys: [.isDirectoryKey])).isDirectory == true else {
                    throw RideUploadStoreError.invalidRevealClaim
                }
                let markers = try fileManager.contentsOfDirectory(
                    at: child,
                    includingPropertiesForKeys: [.isDirectoryKey],
                    options: []
                )
                for marker in markers {
                    guard (try marker.resourceValues(forKeys: [.isDirectoryKey])).isDirectory != true,
                          marker.lastPathComponent.hasSuffix(".consumed")
                    else { throw RideUploadStoreError.invalidRevealClaim }
                    let acknowledgement = try decodeRevealAcknowledgement(at: marker)
                    guard acknowledgement.ownerWallet == nil
                            || acknowledgement.ownerWallet == owner.wallet
                    else { throw RideUploadStoreError.invalidRevealClaim }
                }
            default:
                throw RideUploadStoreError.invalidRevealClaim
            }
        }
    }

    /// Remove Boulder Roller's exact, finalized local source after the owner
    /// has permanently deleted its server ride. A rebound wallet, unfinished
    /// upload, or merely similar identifier can never erase custody.
    func deleteFinalizedRide(
        serverRideID: String,
        owner: RecordingOwner
    ) throws -> Bool {
        guard !owner.id.isEmpty, !owner.wallet.isEmpty else {
            throw RideUploadStoreError.invalidOwner
        }
        let matches = try jobs(ownerID: owner.id).filter { job in
            job.ownerWallet == owner.wallet
                && job.phase == .final
                && job.serverRideID?.caseInsensitiveCompare(serverRideID) == .orderedSame
        }
        guard !matches.isEmpty else { return false }
        for job in matches {
            let directory = jobDirectory(id: job.id, ownerID: job.ownerID)
            try fileManager.removeItem(at: directory)
        }
        return true
    }

    func save(_ job: RideUploadJob) throws {
        guard let existing = try self.job(id: job.id, ownerID: job.ownerID) else {
            throw RideUploadStoreError.missingSource
        }
        guard existing.id == job.id,
              existing.ownerID == job.ownerID,
              existing.ownerWallet == job.ownerWallet,
              existing.fileName == job.fileName,
              existing.fileType == job.fileType,
              existing.fileHash == job.fileHash,
              existing.fileSize == job.fileSize,
              existing.sourceFileName == job.sourceFileName,
              existing.localSummary == job.localSummary,
              existing.createdAt == job.createdAt,
              existing.parserVersion == job.parserVersion,
              existing.preliminaryRideHash == job.preliminaryRideHash
        else {
            throw RideUploadStoreError.immutableMetadataChanged
        }
        guard existing.postRideDraft == job.postRideDraft else {
            throw RideUploadStoreError.immutableMetadataChanged
        }
        switch (existing.publication, job.publication) {
        case (nil, nil):
            break
        case let (selected?, current?):
            guard selected == current else {
                throw RideUploadStoreError.immutableMetadataChanged
            }
        case (nil, .some):
            guard existing.phase == .awaitingPrivacyReview,
                  !existing.attemptedServerHandoff,
                  existing.serverRideID == nil,
                  job.phase == .queued
            else { throw RideUploadStoreError.immutableMetadataChanged }
        case (.some, nil):
            throw RideUploadStoreError.immutableMetadataChanged
        }
        _ = try sourceURL(for: existing)
        try write(job, to: metadataURL(for: job))
    }

    /// Approval publishes exact photo bytes first and the queued job last.
    /// A crash can leave ignored orphan bytes, but can never expose a queued
    /// job whose selected photo is missing or changed.
    func saveApproval(
        _ job: RideUploadJob,
        photoBytes: [String: Data]
    ) throws {
        guard let existing = try self.job(id: job.id, ownerID: job.ownerID),
              existing.id == job.id,
              existing.ownerID == job.ownerID,
              existing.ownerWallet == job.ownerWallet,
              existing.fileName == job.fileName,
              existing.fileType == job.fileType,
              existing.fileHash == job.fileHash,
              existing.fileSize == job.fileSize,
              existing.sourceFileName == job.sourceFileName,
              existing.localSummary == job.localSummary,
              existing.createdAt == job.createdAt,
              existing.parserVersion == job.parserVersion,
              existing.preliminaryRideHash == job.preliminaryRideHash,
              existing.phase == .awaitingPrivacyReview,
              existing.publication == nil,
              existing.postRideDraft == nil,
              !existing.attemptedServerHandoff,
              existing.serverRideID == nil,
              job.phase == .queued,
              job.publication?.isValid == true,
              let draft = job.postRideDraft,
              draft.photos.count <= RidePhotoContract.maxPhotos,
              Set(draft.photos.map(\.id)).count == draft.photos.count,
              draft.photos.allSatisfy(Self.isValidPhotoDescriptor),
              Set(photoBytes.keys) == Set(draft.photos.map(\.id))
        else { throw RideUploadStoreError.immutableMetadataChanged }

        let photoDirectory = jobDirectory(id: job.id, ownerID: job.ownerID)
            .appendingPathComponent("photos", isDirectory: true)
        try protectDirectory(photoDirectory)
        for photo in draft.photos {
            guard let bytes = photoBytes[photo.id],
                  bytes.count == photo.byteCount,
                  FileRideUploadJobStore.sha256(bytes) == photo.fileHash,
                  RidePhotoContract.allowedMimeTypes.contains(photo.mimeType)
            else { throw RideUploadStoreError.invalidPhoto }
            let target = photoDirectory.appendingPathComponent(photo.storageFileName)
            if fileManager.fileExists(atPath: target.path) {
                let existingBytes = try Data(contentsOf: target, options: [.mappedIfSafe])
                guard existingBytes == bytes else {
                    throw RideUploadStoreError.immutableMetadataChanged
                }
                continue
            }
            try bytes.write(
                to: target,
                options: [.atomic, .completeFileProtectionUntilFirstUserAuthentication]
            )
        }
        try write(job, to: metadataURL(for: job))
    }

    func photoURL(for photo: RidePhotoDescriptor, job: RideUploadJob) throws -> URL {
        guard Self.isValidPhotoDescriptor(photo),
              let stored = try self.job(id: job.id, ownerID: job.ownerID),
              stored.postRideDraft?.photos.contains(photo) == true
        else { throw RideUploadStoreError.invalidPhoto }
        let url = jobDirectory(id: job.id, ownerID: job.ownerID)
            .appendingPathComponent("photos", isDirectory: true)
            .appendingPathComponent(photo.storageFileName)
        guard fileManager.fileExists(atPath: url.path) else {
            throw RideUploadStoreError.missingSource
        }
        let bytes = try Data(contentsOf: url, options: [.mappedIfSafe])
        guard bytes.count == photo.byteCount,
              FileRideUploadJobStore.sha256(bytes) == photo.fileHash
        else { throw RideUploadStoreError.sourceHashChanged }
        return url
    }

    private static func isValidPhotoDescriptor(_ photo: RidePhotoDescriptor) -> Bool {
        UUID(uuidString: photo.id) != nil
            && photo.id == photo.id.lowercased()
            && RidePhotoContract.allowedMimeTypes.contains(photo.mimeType)
            && photo.byteCount > 0
            && photo.byteCount <= RidePhotoContract.maxFileSizeBytes
            && photo.fileHash.count == 64
            && photo.fileHash.allSatisfy(\.isHexDigit)
            && photo.fileHash == photo.fileHash.lowercased()
            && photo.sortOrder >= 0
            && ["cover", "photo"].contains(photo.role)
    }

    private func validateAttestationStamp(_ job: RideUploadJob) throws {
        switch (job.parserVersion, job.preliminaryRideHash) {
        case (nil, nil):
            return
        case let (version?, hash?):
            guard version > 0,
                  hash.count == 64,
                  hash.allSatisfy({ $0.isHexDigit }),
                  hash == hash.lowercased()
            else { throw RideUploadStoreError.invalidAttestationStamp }
        default:
            throw RideUploadStoreError.invalidAttestationStamp
        }
    }

    func sourceURL(for job: RideUploadJob) throws -> URL {
        guard let stored = try self.job(id: job.id, ownerID: job.ownerID),
              stored.fileHash == job.fileHash,
              stored.sourceFileName == job.sourceFileName,
              stored.parserVersion == job.parserVersion,
              stored.preliminaryRideHash == job.preliminaryRideHash
        else {
            throw RideUploadStoreError.missingSource
        }
        let source = jobDirectory(id: job.id, ownerID: job.ownerID)
            .appendingPathComponent(job.sourceFileName)
        guard fileManager.fileExists(atPath: source.path) else {
            throw RideUploadStoreError.missingSource
        }
        let bytes = try Data(contentsOf: source, options: [.mappedIfSafe])
        guard bytes.count == job.fileSize, Self.sha256(bytes) == job.fileHash else {
            throw RideUploadStoreError.sourceHashChanged
        }
        return source
    }

    func claimNextReveal(owner: RecordingOwner) throws -> PendingRideReveal? {
        let allOwnerJobs = try jobs(ownerID: owner.id)
        let ownerJobs = allOwnerJobs.filter { $0.ownerWallet == owner.wallet }

        if let claim = try activeRevealClaim(owner: owner) {
            if try revealAcknowledgement(
                owner: owner,
                authoritativeKeyHash: claim.authoritativeKeyHash
            ) != nil {
                consumeRevealSiblings(
                    ownerJobs,
                    authoritativeKeyHash: claim.authoritativeKeyHash
                )
                try removeActiveRevealClaim(owner: owner)
            } else {
                guard let selected = ownerJobs.first(where: { $0.id == claim.jobID }),
                      selected.isRevealEligible,
                      let reveal = selected.reveal,
                      authoritativeRevealKeyHash(for: selected) == claim.authoritativeKeyHash
                else {
                    throw RideUploadStoreError.invalidRevealClaim
                }
                return pendingReveal(for: selected, claimID: claim.claimID, reveal: reveal)
            }
        }

        for selected in ownerJobs where selected.isRevealEligible {
            guard let reveal = selected.reveal else { continue }
            let authoritativeKey = authoritativeRevealKey(for: selected)
            let authoritativeKeyHash = Self.sha256(Data(authoritativeKey.utf8))
            if try revealAcknowledgement(
                owner: owner,
                authoritativeKeyHash: authoritativeKeyHash
            ) != nil {
                consumeRevealSiblings(
                    ownerJobs,
                    authoritativeKeyHash: authoritativeKeyHash
                )
                continue
            }

            let claim = ActiveRevealClaim(
                version: 1,
                claimID: UUID().uuidString.lowercased(),
                jobID: selected.id,
                authoritativeKeyHash: authoritativeKeyHash,
                ownerWallet: owner.wallet
            )
            try writeActiveRevealClaim(claim, owner: owner)
            return pendingReveal(for: selected, claimID: claim.claimID, reveal: reveal)
        }
        return nil
    }

    func acknowledgeReveal(
        id: String,
        owner: RecordingOwner,
        claimID: String,
        authoritativeRideID: String
    ) throws {
        try validateIdentifier(id)
        guard !owner.id.isEmpty, !owner.wallet.isEmpty else {
            throw RideUploadStoreError.invalidOwner
        }

        let authoritativeKey = authoritativeRideID.lowercased()
        let authoritativeKeyHash = Self.sha256(Data(authoritativeKey.utf8))
        let allOwnerJobs = try jobs(ownerID: owner.id)
        let ownerJobs = allOwnerJobs.filter { $0.ownerWallet == owner.wallet }

        if let acknowledgement = try revealAcknowledgement(
            owner: owner,
            authoritativeKeyHash: authoritativeKeyHash
        ) {
            guard acknowledgement.claimID == claimID,
               acknowledgement.jobID == id,
               acknowledgement.authoritativeKeyHash == authoritativeKeyHash,
               ownerJobs.contains(where: { $0.id == id })
            else {
                throw RideUploadStoreError.invalidRevealClaim
            }
            consumeRevealSiblings(
                ownerJobs,
                authoritativeKeyHash: authoritativeKeyHash
            )
            try? removeActiveRevealClaim(owner: owner)
            return
        }

        guard let claim = try activeRevealClaim(owner: owner),
              claim.claimID == claimID,
              claim.jobID == id,
              claim.authoritativeKeyHash == authoritativeKeyHash,
              claim.ownerWallet == nil || claim.ownerWallet == owner.wallet,
              let selected = ownerJobs.first(where: { $0.id == id }),
              selected.isRevealEligible,
              authoritativeRevealKey(for: selected) == authoritativeKey
        else {
            throw RideUploadStoreError.invalidRevealClaim
        }

        let acknowledgement = RevealAcknowledgement(
            version: 1,
            claimID: claimID,
            jobID: id,
            authoritativeKeyHash: authoritativeKeyHash,
            ownerWallet: owner.wallet
        )
        try writeRevealAcknowledgement(acknowledgement, owner: owner)

        // This marker is the durable acknowledgement boundary. Metadata and
        // active-claim cleanup follow it so a crash cannot re-enable a reveal.
        consumeRevealSiblings(
            ownerJobs,
            authoritativeKeyHash: authoritativeKeyHash
        )
        try? removeActiveRevealClaim(owner: owner)
    }

    private func consumeRevealSiblings(
        _ ownerJobs: [RideUploadJob],
        authoritativeKeyHash: String
    ) {
        for var job in ownerJobs
        where job.revealState == .queued
            && self.authoritativeRevealKeyHash(for: job) == authoritativeKeyHash {
            job.revealState = .consumed
            job.updatedAt = .now
            // The marker is the durable at-most-once authority. Metadata is
            // updated for truthful local projection, but a failed secondary
            // write cannot re-enable a reveal.
            try? save(job)
        }
    }

    private func authoritativeRevealKey(for job: RideUploadJob) -> String {
        (job.serverRideID ?? job.id).lowercased()
    }

    private func authoritativeRevealKeyHash(for job: RideUploadJob) -> String {
        Self.sha256(Data(authoritativeRevealKey(for: job).utf8))
    }

    private func pendingReveal(
        for job: RideUploadJob,
        claimID: String,
        reveal: RevealData
    ) -> PendingRideReveal {
        PendingRideReveal(
            id: job.id,
            ownerID: job.ownerID,
            claimID: claimID,
            authoritativeRideID: authoritativeRevealKey(for: job),
            data: reveal
        )
    }

    private func revealConsumptionMarker(
        owner: RecordingOwner,
        authoritativeKeyHash: String
    ) -> URL {
        revealOwnerDirectory(owner)
            .appendingPathComponent(".reveal-consumption", isDirectory: true)
            .appendingPathComponent(
                "\(authoritativeKeyHash).consumed",
                isDirectory: false
            )
    }

    private func legacyRevealConsumptionMarker(
        ownerID: String,
        authoritativeKeyHash: String
    ) -> URL {
        rootURL
            .appendingPathComponent(Self.ownerKey(ownerID), isDirectory: true)
            .appendingPathComponent(".reveal-consumption", isDirectory: true)
            .appendingPathComponent(
                "\(authoritativeKeyHash).consumed",
                isDirectory: false
            )
    }

    private func revealAcknowledgement(
        owner: RecordingOwner,
        authoritativeKeyHash: String
    ) throws -> RevealAcknowledgement? {
        let exactURL = revealConsumptionMarker(
            owner: owner,
            authoritativeKeyHash: authoritativeKeyHash
        )
        if fileManager.fileExists(atPath: exactURL.path) {
            let acknowledgement = try decodeRevealAcknowledgement(at: exactURL)
            guard acknowledgement.authoritativeKeyHash == authoritativeKeyHash,
                  acknowledgement.ownerWallet == nil || acknowledgement.ownerWallet == owner.wallet,
                  let stored = try job(id: acknowledgement.jobID, ownerID: owner.id),
                  stored.ownerWallet == owner.wallet
            else {
                throw RideUploadStoreError.invalidRevealClaim
            }
            return acknowledgement
        }

        let legacyURL = legacyRevealConsumptionMarker(
            ownerID: owner.id,
            authoritativeKeyHash: authoritativeKeyHash
        )
        guard fileManager.fileExists(atPath: legacyURL.path) else { return nil }
        let legacy = try decodeRevealAcknowledgement(at: legacyURL)
        guard legacy.authoritativeKeyHash == authoritativeKeyHash,
              let stored = try job(id: legacy.jobID, ownerID: owner.id)
        else {
            throw RideUploadStoreError.invalidRevealClaim
        }
        guard (legacy.ownerWallet == nil || legacy.ownerWallet == owner.wallet),
              stored.ownerWallet == owner.wallet
        else {
            // A valid legacy marker belonging to another wallet must neither
            // consume nor block this exact owner's independent reveal queue.
            return nil
        }

        let migrated = RevealAcknowledgement(
            version: legacy.version,
            claimID: legacy.claimID,
            jobID: legacy.jobID,
            authoritativeKeyHash: legacy.authoritativeKeyHash,
            ownerWallet: owner.wallet
        )
        try writeRevealAcknowledgement(migrated, owner: owner)
        try fileManager.removeItem(at: legacyURL)
        return migrated
    }

    private func decodeRevealAcknowledgement(at url: URL) throws -> RevealAcknowledgement {
        guard let acknowledgement = try? decoder.decode(
            RevealAcknowledgement.self,
            from: Data(contentsOf: url)
        ), acknowledgement.version == 1,
           UUID(uuidString: acknowledgement.claimID) != nil,
           UUID(uuidString: acknowledgement.jobID) != nil,
           !acknowledgement.authoritativeKeyHash.isEmpty
        else {
            throw RideUploadStoreError.invalidRevealClaim
        }
        return acknowledgement
    }

    private func writeRevealAcknowledgement(
        _ acknowledgement: RevealAcknowledgement,
        owner: RecordingOwner
    ) throws {
        let url = revealConsumptionMarker(
            owner: owner,
            authoritativeKeyHash: acknowledgement.authoritativeKeyHash
        )
        try protectDirectory(url.deletingLastPathComponent())
        try encoder.encode(acknowledgement).write(
            to: url,
            options: [.atomic, .completeFileProtectionUntilFirstUserAuthentication]
        )
    }

    private func activeRevealClaim(owner: RecordingOwner) throws -> ActiveRevealClaim? {
        let exactURL = activeRevealClaimURL(owner: owner)
        if fileManager.fileExists(atPath: exactURL.path) {
            let claim = try decodeActiveRevealClaim(at: exactURL)
            guard claim.ownerWallet == nil || claim.ownerWallet == owner.wallet else {
                throw RideUploadStoreError.invalidRevealClaim
            }
            return claim
        }

        let legacyURL = legacyActiveRevealClaimURL(ownerID: owner.id)
        guard fileManager.fileExists(atPath: legacyURL.path) else { return nil }
        let legacy = try decodeActiveRevealClaim(at: legacyURL)
        guard let stored = try job(id: legacy.jobID, ownerID: owner.id)
        else {
            throw RideUploadStoreError.invalidRevealClaim
        }
        guard (legacy.ownerWallet == nil || legacy.ownerWallet == owner.wallet),
              stored.ownerWallet == owner.wallet
        else {
            // Another exact wallet may keep its legacy claim without blocking
            // this owner's independent queue.
            return nil
        }

        let migrated = ActiveRevealClaim(
            version: legacy.version,
            claimID: legacy.claimID,
            jobID: legacy.jobID,
            authoritativeKeyHash: legacy.authoritativeKeyHash,
            ownerWallet: owner.wallet
        )
        try writeActiveRevealClaim(migrated, owner: owner)
        try fileManager.removeItem(at: legacyURL)
        return migrated
    }

    private func decodeActiveRevealClaim(at url: URL) throws -> ActiveRevealClaim {
        guard let claim = try? decoder.decode(
            ActiveRevealClaim.self,
            from: Data(contentsOf: url)
        ), claim.version == 1,
           UUID(uuidString: claim.claimID) != nil,
           UUID(uuidString: claim.jobID) != nil,
           !claim.authoritativeKeyHash.isEmpty
        else {
            throw RideUploadStoreError.invalidRevealClaim
        }
        return claim
    }

    private func writeActiveRevealClaim(
        _ claim: ActiveRevealClaim,
        owner: RecordingOwner
    ) throws {
        let url = activeRevealClaimURL(owner: owner)
        try protectDirectory(url.deletingLastPathComponent())
        try encoder.encode(claim).write(
            to: url,
            options: [.atomic, .completeFileProtectionUntilFirstUserAuthentication]
        )
    }

    private func removeActiveRevealClaim(owner: RecordingOwner) throws {
        let url = activeRevealClaimURL(owner: owner)
        guard fileManager.fileExists(atPath: url.path) else { return }
        try fileManager.removeItem(at: url)
    }

    private func activeRevealClaimURL(owner: RecordingOwner) -> URL {
        revealOwnerDirectory(owner)
            .appendingPathComponent("active-reveal-claim.json", isDirectory: false)
    }

    private func legacyActiveRevealClaimURL(ownerID: String) -> URL {
        rootURL
            .appendingPathComponent(Self.ownerKey(ownerID), isDirectory: true)
            .appendingPathComponent("active-reveal-claim.json", isDirectory: false)
    }

    private func revealOwnerDirectory(_ owner: RecordingOwner) -> URL {
        rootURL
            .appendingPathComponent(Self.ownerKey(owner.id), isDirectory: true)
            .appendingPathComponent(".reveal-owners", isDirectory: true)
            .appendingPathComponent(Self.revealOwnerKey(owner), isDirectory: true)
    }

    private func metadataURL(for job: RideUploadJob) -> URL {
        jobDirectory(id: job.id, ownerID: job.ownerID).appendingPathComponent("job.json")
    }

    private func jobDirectory(id: String, ownerID: String) -> URL {
        rootURL
            .appendingPathComponent(Self.ownerKey(ownerID), isDirectory: true)
            .appendingPathComponent(id, isDirectory: true)
    }

    private func write(_ job: RideUploadJob, to url: URL) throws {
        let data = try encoder.encode(job)
        try data.write(
            to: url,
            options: [.atomic, .completeFileProtectionUntilFirstUserAuthentication]
        )
    }

    private func protectDirectory(_ url: URL) throws {
        try fileManager.createDirectory(at: url, withIntermediateDirectories: true)
        try fileManager.setAttributes(
            [.protectionKey: FileProtectionType.completeUntilFirstUserAuthentication],
            ofItemAtPath: url.path
        )
    }

    private func validateIdentifier(_ value: String) throws {
        guard UUID(uuidString: value) != nil else { throw RideUploadStoreError.invalidIdentifier }
    }

    private static func ownerKey(_ ownerID: String) -> String {
        sha256(Data(ownerID.utf8))
    }

    private static func revealOwnerKey(_ owner: RecordingOwner) -> String {
        sha256(Data("\(owner.id)\u{0}\(owner.wallet)".utf8))
    }

    static func sha256(_ data: Data) -> String {
        SHA256.hash(data: data).map { String(format: "%02x", $0) }.joined()
    }
}
