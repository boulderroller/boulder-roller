import CryptoKit
import Darwin
import Foundation
import WorkoutParse

struct RecordingOwner: Codable, Equatable, Hashable, Sendable {
    let id: String
    let wallet: String

    init(id: String, wallet: String) {
        self.id = id
        self.wallet = wallet
    }

    init(user: User) {
        id = user.id
        wallet = user.wallet
    }
}

struct InterruptedRideRecovery: Codable, Equatable, Identifiable, Sendable {
    let id: String
    let ownerID: String
    let startedAt: Date
    let state: RecordingSessionState
    let sampleCount: Int
    let durationS: TimeInterval
    let distanceM: Double
    let elevationGainM: Double?

    var canSaveAndUpload: Bool {
        RecordingUploadEligibility.allows(
            sampleCount: sampleCount,
            distanceM: distanceM
        )
    }
}

private enum RecordingUploadEligibility {
    static let minimumSampleCount = 30
    static let minimumDistanceM = 100.0

    static func allows(sampleCount: Int, distanceM: Double) -> Bool {
        sampleCount >= minimumSampleCount && distanceM >= minimumDistanceM
    }
}

/// Internal, production-derived proof seam for recovery fidelity. UI receives
/// only the scalar summary; tests can compare every accepted coordinate,
/// segment boundary, sensor value, and provenance field after reconstruction.
struct InterruptedRideRecoveryEvidence: Equatable, Sendable {
    let recovery: InterruptedRideRecovery
    let samples: [RecordedSample]
}

struct FinalizedRecording: Equatable, Sendable {
    let id: String
    let ownerID: String
    let gpxBytes: Data
    let fileHash: String
    let preliminaryRideHash: String
    let parserVersion: UInt32
    let uploadJobID: String?
    let uploadEligible: Bool
}

/// Everything local custody can truthfully show for one saved-on-device
/// ride: the exact finalized artifact plus the recorded fixes (for a route
/// drawn from evidence, never invention).
struct LocalSavedRideEvidence: Sendable {
    let artifact: RecordingFinalArtifact
    let fixes: [RecordingSessionFix]
}

/// A finalized ride that truthfully remains local because it did not meet the
/// existing upload evidence threshold. The encrypted custody store retains the
/// immutable GPX and attestation; the feed receives only this owner-bound
/// summary projection.
struct LocalSavedRide: Equatable, Hashable, Identifiable, Sendable {
    let id: String
    let ownerID: String
    let ownerWallet: String
    let summary: LocalRideSummary
    let fileHash: String
    let preliminaryRideHash: String
    let parserVersion: UInt32
}

enum LiveRideCustodyError: LocalizedError, Equatable {
    case invalidOwner
    case invalidIdentifier
    case activeRideExists
    case noActiveRide
    case ownerMismatch
    case keyUnavailable
    case corruptEvidence
    case unsupportedVersion
    case immutableEvidenceChanged

    var errorDescription: String? {
        switch self {
        case .invalidOwner, .ownerMismatch:
            return "Ride owner is unavailable"
        case .invalidIdentifier, .activeRideExists, .noActiveRide:
            return "Ride storage is unavailable"
        case .keyUnavailable, .corruptEvidence, .unsupportedVersion,
             .immutableEvidenceChanged:
            return "Ride evidence is unavailable"
        }
    }
}

struct RecordingCustodyManifest: Codable, Equatable, Sendable {
    let schemaVersion: Int
    let truthPolicyVersion: Int
    let id: String
    let uploadJobID: String
    let ownerID: String
    let ownerWallet: String
    let startedAt: Date
}

struct RecordingFinalArtifact: Codable, Equatable, Sendable {
    let gpxBytes: Data
    let fileName: String
    let fileHash: String
    let preliminaryRideHash: String
    let parserVersion: UInt32
    let localSummary: LocalRideSummary
    let uploadEligible: Bool
}

enum RecordingCustodyEventKind: String, Codable, Sendable {
    case start
    case fix
    case manualPause
    case manualResume
    case stop
    case suspend
    case finalized
    case handedOff
}

struct RecordingCustodyEvent: Codable, Equatable, Sendable {
    let schemaVersion: Int
    let sequence: UInt64
    let kind: RecordingCustodyEventKind
    let occurredAt: Date
    /// Forward-only awake-session offset. It is never used as a wall or GPS
    /// timestamp and is not continued after process reconstruction.
    let monotonicOffsetS: TimeInterval
    let fix: RecordingSessionFix?
    let stateAtBoundary: RecordingSessionState?
    let finalArtifact: RecordingFinalArtifact?

    static func start(at: Date) -> Self {
        Self(
            schemaVersion: 1,
            sequence: 1,
            kind: .start,
            occurredAt: at,
            monotonicOffsetS: 0,
            fix: nil,
            stateAtBoundary: nil,
            finalArtifact: nil
        )
    }
}

struct PersistedRecording: Sendable {
    let manifest: RecordingCustodyManifest
    let events: [RecordingCustodyEvent]

    var finalArtifact: RecordingFinalArtifact? {
        events.last(where: { $0.kind == .finalized })?.finalArtifact
    }

    var isHandedOff: Bool { events.contains(where: { $0.kind == .handedOff }) }
    var isFinalized: Bool { finalArtifact != nil }
    var isRecoverable: Bool { !isFinalized && !isHandedOff }
    var lastBoundaryAt: Date { events.last?.occurredAt ?? manifest.startedAt }
}

protocol FirstPartyRideUploadQueuing: Sendable {
    func enqueueFirstParty(
        owner: RecordingOwner,
        jobID: String,
        fileName: String,
        sourceBytes: Data,
        summary: LocalRideSummary,
        parserVersion: UInt32,
        preliminaryRideHash: String
    ) async throws -> RideUploadJob
}

private struct LiveRideCustodyKeyProvider: Sendable {
    func load(existingStore: Bool) throws -> Data {
        do {
            return try KeychainStore.liveRideCustodyMasterKey(existingStore: existingStore)
        } catch {
            throw LiveRideCustodyError.keyUnavailable
        }
    }
}

/// AES-GCM owner-bound append-only journal. Every raw fix and lifecycle intent
/// is durably published before RecordingSession mutates. A restart replays the
/// same versioned inputs through the existing truth pipelines; it never stores
/// or rewrites a full-history snapshot on each observation.
actor FileLiveRideCustodyStore {
    static let schemaVersion = 1
    static let truthPolicyVersion = 1

    nonisolated let rootURL: URL

    private let fileManager: FileManager
    private let keyLoader: @Sendable (Bool) throws -> Data
    private let keyAbsenceProbe: @Sendable () -> Bool
    private let beforeEventPublish: @Sendable (RecordingCustodyEventKind, UInt64) throws -> Void
    private let beforeDirectorySync: @Sendable (URL) throws -> Void
    private let beforeDiscardRemove: @Sendable (URL) throws -> Void
    private var cachedMasterKey: Data?
    private var nextSequences: [String: UInt64] = [:]

    init(
        rootURL: URL? = nil,
        fileManager: FileManager = .default,
        keyLoader: @escaping @Sendable (Bool) throws -> Data = { existingStore in
            // Test processes never touch the rider's keychain (ProcessSandbox).
            if ProcessSandbox.isTestProcess {
                return ProcessSandbox.ephemeralTestCustodyKey
            }
            return try LiveRideCustodyKeyProvider().load(existingStore: existingStore)
        },
        keyAbsenceProbe: @escaping @Sendable () -> Bool = {
            KeychainStore.custodyKeyPositivelyAbsent()
        },
        beforeEventPublish: @escaping @Sendable (
            RecordingCustodyEventKind,
            UInt64
        ) throws -> Void = { _, _ in },
        beforeDirectorySync: @escaping @Sendable (URL) throws -> Void = { _ in },
        beforeDiscardRemove: @escaping @Sendable (URL) throws -> Void = { _ in }
    ) {
        self.fileManager = fileManager
        self.keyLoader = keyLoader
        self.keyAbsenceProbe = keyAbsenceProbe
        self.beforeEventPublish = beforeEventPublish
        self.beforeDirectorySync = beforeDirectorySync
        self.beforeDiscardRemove = beforeDiscardRemove
        if let rootURL {
            self.rootURL = rootURL
        } else {
            // The default (shared-singleton) root is rider evidence; test
            // processes are walled into an isolated temp root (ProcessSandbox).
            self.rootURL = ProcessSandbox.isolatedIfTesting(
                fileManager.urls(
                    for: .applicationSupportDirectory,
                    in: .userDomainMask
                )[0].appendingPathComponent("LiveRideCustody", isDirectory: true),
                label: "LiveRideCustody"
            )
        }
    }

    func create(owner: RecordingOwner, rideID: String, startedAt: Date) throws {
        try validate(owner: owner, rideID: rideID)
        try quarantineKnownOwnerlessLegacy()
        guard try recoverable(owner: owner) == nil else {
            throw LiveRideCustodyError.activeRideExists
        }

        let master = try masterKey()
        let ownerTag = Self.ownerTag(owner, master: master)
        let ownerDirectory = rootURL.appendingPathComponent(ownerTag, isDirectory: true)
        try protectDirectory(rootURL)
        try protectDirectory(ownerDirectory)

        let published = ownerDirectory.appendingPathComponent(rideID, isDirectory: true)
        guard !fileManager.fileExists(atPath: published.path) else {
            throw LiveRideCustodyError.immutableEvidenceChanged
        }
        let staging = ownerDirectory.appendingPathComponent(
            ".\(rideID).\(UUID().uuidString.lowercased()).staging",
            isDirectory: true
        )
        try protectDirectory(staging)
        try protectDirectory(staging.appendingPathComponent("events", isDirectory: true))

        let manifest = RecordingCustodyManifest(
            schemaVersion: Self.schemaVersion,
            truthPolicyVersion: Self.truthPolicyVersion,
            id: rideID,
            uploadJobID: rideID,
            ownerID: owner.id,
            ownerWallet: owner.wallet,
            startedAt: startedAt
        )
        let start = RecordingCustodyEvent.start(at: startedAt)
        do {
            try writeSealed(
                manifest,
                to: staging.appendingPathComponent("manifest.sealed"),
                owner: owner,
                rideID: rideID,
                sequence: 0,
                kind: "manifest",
                master: master
            )
            try beforeEventPublish(.start, 1)
            try writeSealed(
                start,
                to: eventURL(in: staging, sequence: 1),
                owner: owner,
                rideID: rideID,
                sequence: 1,
                kind: RecordingCustodyEventKind.start.rawValue,
                master: master
            )
            try fileManager.moveItem(at: staging, to: published)
            try synchronizeDirectory(ownerDirectory)
            nextSequences[rideID] = 2
        } catch {
            try? fileManager.removeItem(at: staging)
            throw error
        }
    }

    func append(
        owner: RecordingOwner,
        rideID: String,
        kind: RecordingCustodyEventKind,
        occurredAt: Date,
        monotonicOffsetS: TimeInterval,
        fix: RecordingSessionFix? = nil,
        stateAtBoundary: RecordingSessionState? = nil,
        finalArtifact: RecordingFinalArtifact? = nil
    ) throws {
        guard !owner.id.isEmpty, !owner.wallet.isEmpty else {
            throw LiveRideCustodyError.invalidOwner
        }
        try validateIdentifier(rideID)
        let sequence: UInt64
        if let cached = nextSequences[rideID] {
            sequence = cached
        } else {
            // First mutation after reconstruction performs the full integrity
            // scan once and seeds the append cursor. Steady-state 1 Hz fixes
            // then publish one bounded encrypted event without rereading ride
            // history.
            let persisted = try recording(owner: owner, rideID: rideID)
            sequence = UInt64(persisted.events.count + 1)
        }
        let event = RecordingCustodyEvent(
            schemaVersion: Self.schemaVersion,
            sequence: sequence,
            kind: kind,
            occurredAt: occurredAt,
            monotonicOffsetS: monotonicOffsetS,
            fix: fix,
            stateAtBoundary: stateAtBoundary,
            finalArtifact: finalArtifact
        )
        let master = try masterKey()
        let directory = recordingDirectory(owner: owner, rideID: rideID, master: master)
        let previousEvent = eventURL(in: directory, sequence: sequence - 1)
        guard fileManager.fileExists(
            atPath: directory.appendingPathComponent("manifest.sealed").path
        ), fileManager.fileExists(atPath: previousEvent.path) else {
            try? quarantineOwnedDirectory(
                directory,
                ownerDirectory: directory.deletingLastPathComponent(),
                rideID: rideID
            )
            nextSequences.removeValue(forKey: rideID)
            throw LiveRideCustodyError.corruptEvidence
        }
        let destination = eventURL(in: directory, sequence: sequence)
        if fileManager.fileExists(atPath: destination.path) {
            let matchesIntendedEvent: Bool
            do {
                let persistedPlaintext = try authenticatedPlaintext(
                    Data(contentsOf: destination),
                    owner: owner,
                    rideID: rideID,
                    sequence: sequence,
                    kind: kind.rawValue,
                    master: master
                )
                matchesIntendedEvent = persistedPlaintext == (try canonicalPlaintext(event))
            } catch {
                try quarantine(owner: owner, rideID: rideID)
                throw LiveRideCustodyError.corruptEvidence
            }
            guard matchesIntendedEvent else {
                try quarantine(owner: owner, rideID: rideID)
                throw LiveRideCustodyError.corruptEvidence
            }

            // A rename can be visible even when the following directory fsync
            // reported failure. Authenticate the exact intended event, then
            // retry the durability boundary before advancing the in-memory
            // cursor. Another fsync failure stays retryable and never
            // quarantines authentic evidence.
            try synchronizeDirectory(destination.deletingLastPathComponent())
            nextSequences[rideID] = sequence + 1
            return
        }
        try beforeEventPublish(kind, sequence)
        try writeSealed(
            event,
            to: destination,
            owner: owner,
            rideID: rideID,
            sequence: sequence,
            kind: kind.rawValue,
            master: master
        )
        nextSequences[rideID] = sequence + 1
    }

    func recoverable(owner: RecordingOwner) throws -> PersistedRecording? {
        let records = try recordings(owner: owner).filter(\.isRecoverable)
        guard records.count <= 1 else {
            for record in records {
                try? quarantine(owner: owner, rideID: record.manifest.id)
            }
            throw LiveRideCustodyError.corruptEvidence
        }
        return records.first
    }

    func finalizedPendingUpload(owner: RecordingOwner) throws -> [PersistedRecording] {
        try recordings(owner: owner).filter {
            $0.finalArtifact?.uploadEligible == true && !$0.isHandedOff
        }
    }

    func locallySaved(owner: RecordingOwner) throws -> [LocalSavedRide] {
        try recordings(owner: owner).compactMap { recording in
            guard recording.manifest.ownerID == owner.id,
                  recording.manifest.ownerWallet == owner.wallet
            else { throw LiveRideCustodyError.ownerMismatch }
            guard let artifact = recording.finalArtifact,
                  !artifact.uploadEligible,
                  !recording.isHandedOff
            else { return nil }
            return LocalSavedRide(
                id: recording.manifest.id,
                ownerID: recording.manifest.ownerID,
                ownerWallet: recording.manifest.ownerWallet,
                summary: artifact.localSummary,
                fileHash: artifact.fileHash,
                preliminaryRideHash: artifact.preliminaryRideHash,
                parserVersion: artifact.parserVersion
            )
        }
        .sorted { $0.summary.startedAt > $1.summary.startedAt }
    }

    func accountDeletionRecords(owner: RecordingOwner) throws -> [AccountDeletionCustodyRecord] {
        try assertNoUnattributedAccountDeletionEvidence()
        return try recordings(owner: owner).map { recording in
            AccountDeletionCustodyRecord(
                rideID: recording.manifest.id,
                uploadJobID: recording.manifest.uploadJobID,
                startedAt: recording.manifest.startedAt,
                handedOff: recording.isHandedOff
            )
        }
    }

    /// Remove only the HMAC directory for this exact ID+wallet pair. The
    /// install-wide custody key remains because another owner on this phone
    /// may still have recoverable evidence encrypted by it.
    func purgeAccount(owner: RecordingOwner) throws {
        try assertNoUnattributedAccountDeletionEvidence()
        let records = try recordings(owner: owner)
        let master = try masterKey()
        let directory = rootURL.appendingPathComponent(
            Self.ownerTag(owner, master: master),
            isDirectory: true
        )
        guard fileManager.fileExists(atPath: directory.path) else { return }
        try beforeDiscardRemove(directory)
        try fileManager.removeItem(at: directory)
        try synchronizeDirectory(rootURL)
        guard !fileManager.fileExists(atPath: directory.path) else {
            throw AccountDeletionLocalCleanupError.verificationFailed
        }
        for record in records {
            nextSequences.removeValue(forKey: record.manifest.id)
        }
    }

    func persisted(owner: RecordingOwner, rideID: String) throws -> PersistedRecording {
        try recording(owner: owner, rideID: rideID)
    }

    func discard(owner: RecordingOwner, rideID: String) throws {
        _ = try recording(owner: owner, rideID: rideID)
        try discardValidated(owner: owner, rideID: rideID)
    }

    /// Completes an exact-owner delete that the runtime already validated.
    /// A prior remove may be visible even though its parent-directory fsync
    /// failed; retrying that same in-memory intent re-fsyncs the parent and is
    /// therefore idempotent without attributing any missing row to a new rider.
    func discardValidated(owner: RecordingOwner, rideID: String) throws {
        let master = try masterKey()
        let directory = recordingDirectory(owner: owner, rideID: rideID, master: master)
        if fileManager.fileExists(atPath: directory.path) {
            try beforeDiscardRemove(directory)
            try fileManager.removeItem(at: directory)
        }
        try synchronizeDirectory(directory.deletingLastPathComponent())
        nextSequences.removeValue(forKey: rideID)
    }

    private func recordings(owner: RecordingOwner) throws -> [PersistedRecording] {
        guard !owner.id.isEmpty, !owner.wallet.isEmpty else {
            throw LiveRideCustodyError.invalidOwner
        }
        try quarantineKnownOwnerlessLegacy()
        let master = try masterKey()
        let directory = rootURL.appendingPathComponent(
            Self.ownerTag(owner, master: master),
            isDirectory: true
        )
        guard fileManager.fileExists(atPath: directory.path) else { return [] }
        let unavailable = directory.appendingPathComponent("Unavailable", isDirectory: true)
        if fileManager.fileExists(atPath: unavailable.path) {
            throw LiveRideCustodyError.corruptEvidence
        }
        let allChildren = try fileManager.contentsOfDirectory(
            at: directory,
            includingPropertiesForKeys: [.isDirectoryKey],
            options: []
        )
        guard !allChildren.contains(where: { $0.lastPathComponent.hasPrefix(".") }) else {
            throw LiveRideCustodyError.corruptEvidence
        }
        let children = try fileManager.contentsOfDirectory(
            at: directory,
            includingPropertiesForKeys: [.isDirectoryKey],
            options: [.skipsHiddenFiles]
        )
        var result: [PersistedRecording] = []
        for child in children {
            guard (try? child.resourceValues(forKeys: [.isDirectoryKey]).isDirectory) == true else {
                throw LiveRideCustodyError.corruptEvidence
            }
            do {
                result.append(try readRecording(owner: owner, directory: child, master: master))
            } catch {
                try? quarantineOwnedDirectory(
                    child,
                    ownerDirectory: directory,
                    rideID: child.lastPathComponent
                )
                throw error
            }
        }
        return result.sorted { $0.manifest.startedAt < $1.manifest.startedAt }
    }

    /// Root quarantine has deliberately lost exact-owner authority. Deletion
    /// must route to support while any bytes remain there; it may neither
    /// attribute them to the current wallet nor erase them globally.
    private func assertNoUnattributedAccountDeletionEvidence() throws {
        try quarantineKnownOwnerlessLegacy()
        for name in ["Quarantine", "KeylessQuarantine"] {
            let directory = rootURL.appendingPathComponent(name, isDirectory: true)
            guard fileManager.fileExists(atPath: directory.path) else { continue }
            let entries = try fileManager.contentsOfDirectory(atPath: directory.path)
            if !entries.isEmpty { throw LiveRideCustodyError.corruptEvidence }
        }
    }

    private func recording(owner: RecordingOwner, rideID: String) throws -> PersistedRecording {
        let master = try masterKey()
        let directory = recordingDirectory(owner: owner, rideID: rideID, master: master)
        guard fileManager.fileExists(atPath: directory.path) else {
            throw LiveRideCustodyError.noActiveRide
        }
        do {
            return try readRecording(owner: owner, directory: directory, master: master)
        } catch {
            try? quarantineOwnedDirectory(
                directory,
                ownerDirectory: directory.deletingLastPathComponent(),
                rideID: rideID
            )
            throw error
        }
    }

    private func readRecording(
        owner: RecordingOwner,
        directory: URL,
        master: Data
    ) throws -> PersistedRecording {
        let rideID = directory.lastPathComponent
        try validateIdentifier(rideID)
        let manifest: RecordingCustodyManifest = try readSealed(
            from: directory.appendingPathComponent("manifest.sealed"),
            owner: owner,
            rideID: rideID,
            sequence: 0,
            kind: "manifest",
            master: master
        )
        guard manifest.schemaVersion == Self.schemaVersion,
              manifest.truthPolicyVersion == Self.truthPolicyVersion
        else { throw LiveRideCustodyError.unsupportedVersion }
        guard manifest.id == rideID,
              manifest.uploadJobID == rideID,
              manifest.ownerID == owner.id,
              manifest.ownerWallet == owner.wallet
        else { throw LiveRideCustodyError.ownerMismatch }

        let eventsDirectory = directory.appendingPathComponent("events", isDirectory: true)
        let eventURLs = try fileManager.contentsOfDirectory(
            at: eventsDirectory,
            includingPropertiesForKeys: nil,
            options: [.skipsHiddenFiles]
        ).sorted { $0.lastPathComponent < $1.lastPathComponent }
        guard !eventURLs.isEmpty else { throw LiveRideCustodyError.corruptEvidence }

        var events: [RecordingCustodyEvent] = []
        for (index, url) in eventURLs.enumerated() {
            let expected = UInt64(index + 1)
            guard url.lastPathComponent == Self.eventFileName(expected) else {
                throw LiveRideCustodyError.corruptEvidence
            }
            let envelope = try Data(contentsOf: url)
            let event = try decryptEvent(
                envelope,
                owner: owner,
                rideID: rideID,
                sequence: expected,
                master: master
            )
            guard event.schemaVersion == Self.schemaVersion,
                  event.sequence == expected,
                  event.kind == (expected == 1 ? .start : event.kind),
                  (expected != 1 || event.occurredAt == manifest.startedAt)
            else { throw LiveRideCustodyError.corruptEvidence }
            events.append(event)
        }
        guard events.first?.kind == .start else { throw LiveRideCustodyError.corruptEvidence }
        nextSequences[rideID] = UInt64(events.count + 1)
        return PersistedRecording(manifest: manifest, events: events)
    }

    private func decryptEvent(
        _ envelope: Data,
        owner: RecordingOwner,
        rideID: String,
        sequence: UInt64,
        master: Data
    ) throws -> RecordingCustodyEvent {
        for kind in [
            RecordingCustodyEventKind.start,
            .fix, .manualPause, .manualResume, .stop, .suspend, .finalized, .handedOff,
        ] {
            if let event: RecordingCustodyEvent = try? open(
                envelope,
                owner: owner,
                rideID: rideID,
                sequence: sequence,
                kind: kind.rawValue,
                master: master
            ), event.kind == kind {
                return event
            }
        }
        throw LiveRideCustodyError.corruptEvidence
    }

    private func masterKey() throws -> Data {
        if let cachedMasterKey { return cachedMasterKey }
        let existing: Bool
        do {
            existing = try hasEncryptedRecordingStore()
        } catch {
            throw LiveRideCustodyError.keyUnavailable
        }
        let loaded: Data
        do {
            loaded = try keyLoader(existing)
        } catch {
            // MOBILE_TRUTHS §9.1 amendment (2026-08-18, demonstrated on the
            // founder's device): sealed evidence whose key is POSITIVELY
            // absent from the keychain is permanently unreadable — refusing
            // a new key forever bricks recording without protecting anything
            // readable. The unreadable records move intact into a keyless
            // quarantine (never deleted, never decrypted by any later key)
            // and a fresh key governs only new evidence. Any error status
            // from the keychain stays fail-closed exactly as before.
            guard existing, keyAbsenceProbe() else { throw error }
            try quarantineKeylessEvidence()
            loaded = try keyLoader(false)
        }
        guard loaded.count == 32 else { throw LiveRideCustodyError.keyUnavailable }
        cachedMasterKey = loaded
        return loaded
    }

    /// Move every sealed owner-tag directory into a keyless quarantine.
    /// Bytes are preserved exactly; nothing is deleted, and the quarantine
    /// name never reads as an owner tag so the store is fresh afterwards.
    private func quarantineKeylessEvidence() throws {
        let entries = try fileManager.contentsOfDirectory(
            at: rootURL,
            includingPropertiesForKeys: [.isDirectoryKey],
            options: []
        )
        let sealed = entries.filter { entry in
            entry.lastPathComponent.count == 64
                && entry.lastPathComponent.allSatisfy { $0.isHexDigit }
                && entry.lastPathComponent == entry.lastPathComponent.lowercased()
        }
        guard !sealed.isEmpty else { return }
        let stamp = UInt64(Date().timeIntervalSince1970)
        let quarantine = rootURL
            .appendingPathComponent("KeylessQuarantine", isDirectory: true)
            .appendingPathComponent(String(stamp), isDirectory: true)
        try fileManager.createDirectory(at: quarantine, withIntermediateDirectories: true)
        for entry in sealed {
            try fileManager.moveItem(
                at: entry,
                to: quarantine.appendingPathComponent(entry.lastPathComponent)
            )
        }
        try synchronizeDirectory(rootURL)
        nextSequences.removeAll()
    }

    /// Only an owner-tag directory containing encrypted ride evidence proves
    /// that this root already depends on a custody key. Quarantined ownerless
    /// legacy files are intentionally excluded so a fresh install can create
    /// its first key after preserving those bytes.
    private func hasEncryptedRecordingStore() throws -> Bool {
        do {
            let attributes = try fileManager.attributesOfItem(atPath: rootURL.path)
            guard attributes[.type] as? FileAttributeType == .typeDirectory else {
                throw LiveRideCustodyError.keyUnavailable
            }
        } catch let error as CocoaError where [
            CocoaError.Code.fileNoSuchFile,
            .fileReadNoSuchFile,
        ].contains(error.code) {
            // Only a positively identified absent root authorizes first-key
            // creation. Permission, protection, and other I/O errors remain
            // unavailable rather than minting a replacement key.
            return false
        } catch let error as POSIXError where error.code == .ENOENT {
            return false
        }
        let ownerDirectories: [URL]
        do {
            ownerDirectories = try fileManager.contentsOfDirectory(
                at: rootURL,
                includingPropertiesForKeys: [.isDirectoryKey],
                options: []
            )
        } catch let error as CocoaError where error.code == .fileNoSuchFile {
            return false
        }

        for ownerDirectory in ownerDirectories {
            guard ownerDirectory.lastPathComponent.count == 64,
                  ownerDirectory.lastPathComponent.allSatisfy({ $0.isHexDigit }),
                  ownerDirectory.lastPathComponent == ownerDirectory.lastPathComponent.lowercased()
            else { continue }
            guard try ownerDirectory.resourceValues(forKeys: [.isDirectoryKey]).isDirectory == true
            else { throw LiveRideCustodyError.keyUnavailable }
            let candidates = try fileManager.contentsOfDirectory(
                at: ownerDirectory,
                includingPropertiesForKeys: [.isDirectoryKey],
                options: []
            )

            for candidate in candidates {
                guard try candidate.resourceValues(forKeys: [.isDirectoryKey]).isDirectory == true
                else { continue }
                let name = candidate.lastPathComponent
                if name == "Unavailable" { return true }
                let isPublishedRide = UUID(uuidString: name) != nil && name == name.lowercased()
                let isStagedRide = name.hasPrefix(".") && name.hasSuffix(".staging")
                if isPublishedRide || isStagedRide {
                    // A valid encrypted-record directory name is itself the
                    // fail-closed evidence boundary. A missing manifest is
                    // corrupt/torn evidence, not permission to mint a key.
                    return true
                }
            }
        }
        return false
    }

    private func writeSealed<Value: Encodable>(
        _ value: Value,
        to destination: URL,
        owner: RecordingOwner,
        rideID: String,
        sequence: UInt64,
        kind: String,
        master: Data
    ) throws {
        let plaintext = try canonicalPlaintext(value)
        let key = Self.ownerKey(owner, master: master)
        let sealed = try AES.GCM.seal(
            plaintext,
            using: key,
            authenticating: Self.aad(
                owner: owner,
                rideID: rideID,
                sequence: sequence,
                kind: kind,
                master: master
            )
        )
        guard let combined = sealed.combined else { throw LiveRideCustodyError.corruptEvidence }
        try writeAtomically(combined, to: destination)
    }

    private func readSealed<Value: Decodable>(
        from source: URL,
        owner: RecordingOwner,
        rideID: String,
        sequence: UInt64,
        kind: String,
        master: Data
    ) throws -> Value {
        try open(
            Data(contentsOf: source),
            owner: owner,
            rideID: rideID,
            sequence: sequence,
            kind: kind,
            master: master
        )
    }

    private func open<Value: Decodable>(
        _ envelope: Data,
        owner: RecordingOwner,
        rideID: String,
        sequence: UInt64,
        kind: String,
        master: Data
    ) throws -> Value {
        let plaintext = try authenticatedPlaintext(
            envelope,
            owner: owner,
            rideID: rideID,
            sequence: sequence,
            kind: kind,
            master: master
        )
        let decoder = JSONDecoder()
        decoder.dateDecodingStrategy = .millisecondsSince1970
        return try decoder.decode(Value.self, from: plaintext)
    }

    private func canonicalPlaintext<Value: Encodable>(_ value: Value) throws -> Data {
        let encoder = JSONEncoder()
        encoder.outputFormatting = [.sortedKeys]
        encoder.dateEncodingStrategy = .millisecondsSince1970
        return try encoder.encode(value)
    }

    private func authenticatedPlaintext(
        _ envelope: Data,
        owner: RecordingOwner,
        rideID: String,
        sequence: UInt64,
        kind: String,
        master: Data
    ) throws -> Data {
        let box = try AES.GCM.SealedBox(combined: envelope)
        return try AES.GCM.open(
            box,
            using: Self.ownerKey(owner, master: master),
            authenticating: Self.aad(
                owner: owner,
                rideID: rideID,
                sequence: sequence,
                kind: kind,
                master: master
            )
        )
    }

    private func writeAtomically(_ data: Data, to destination: URL) throws {
        let directory = destination.deletingLastPathComponent()
        try protectDirectory(directory)
        let temporary = directory.appendingPathComponent(
            ".\(destination.lastPathComponent).\(UUID().uuidString.lowercased()).tmp"
        )
        do {
            try data.write(
                to: temporary,
                options: [.completeFileProtectionUntilFirstUserAuthentication]
            )
            let handle = try FileHandle(forWritingTo: temporary)
            try handle.synchronize()
            try handle.close()
            guard !fileManager.fileExists(atPath: destination.path) else {
                throw LiveRideCustodyError.immutableEvidenceChanged
            }
            try fileManager.moveItem(at: temporary, to: destination)
            try synchronizeDirectory(directory)
        } catch {
            try? fileManager.removeItem(at: temporary)
            throw error
        }
    }

    private func protectDirectory(_ directory: URL) throws {
        if !fileManager.fileExists(atPath: directory.path) {
            try fileManager.createDirectory(at: directory, withIntermediateDirectories: true)
        }
        try fileManager.setAttributes(
            [.protectionKey: FileProtectionType.completeUntilFirstUserAuthentication],
            ofItemAtPath: directory.path
        )
    }

    private func synchronizeDirectory(_ directory: URL) throws {
        try beforeDirectorySync(directory)
        let descriptor = Darwin.open(directory.path, O_RDONLY)
        guard descriptor >= 0 else { throw LiveRideCustodyError.corruptEvidence }
        defer { Darwin.close(descriptor) }
        guard Darwin.fsync(descriptor) == 0 else { throw LiveRideCustodyError.corruptEvidence }
    }

    private func eventURL(in directory: URL, sequence: UInt64) -> URL {
        directory.appendingPathComponent("events", isDirectory: true)
            .appendingPathComponent(Self.eventFileName(sequence))
    }

    private static func eventFileName(_ sequence: UInt64) -> String {
        String(format: "%020llu.sealed", sequence)
    }

    private func recordingDirectory(
        owner: RecordingOwner,
        rideID: String,
        master: Data
    ) -> URL {
        rootURL
            .appendingPathComponent(Self.ownerTag(owner, master: master), isDirectory: true)
            .appendingPathComponent(rideID, isDirectory: true)
    }

    private static func ownerTag(_ owner: RecordingOwner, master: Data) -> String {
        let code = HMAC<SHA256>.authenticationCode(
            for: ownerScope(owner),
            using: SymmetricKey(data: master)
        )
        return Data(code).map { String(format: "%02x", $0) }.joined()
    }

    private static func ownerKey(_ owner: RecordingOwner, master: Data) -> SymmetricKey {
        HKDF<SHA256>.deriveKey(
            inputKeyMaterial: SymmetricKey(data: master),
            salt: Data("br-live-ride-custody-v1".utf8),
            info: ownerScope(owner),
            outputByteCount: 32
        )
    }

    private static func aad(
        owner: RecordingOwner,
        rideID: String,
        sequence: UInt64,
        kind: String,
        master: Data
    ) -> Data {
        Data(
            "br-live-ride|1|\(ownerTag(owner, master: master))|\(rideID)|\(sequence)|\(kind)".utf8
        )
    }

    private static func ownerScope(_ owner: RecordingOwner) -> Data {
        Data("\(owner.id)\u{0}\(owner.wallet)".utf8)
    }

    private func validate(owner: RecordingOwner, rideID: String) throws {
        guard !owner.id.isEmpty, !owner.wallet.isEmpty else {
            throw LiveRideCustodyError.invalidOwner
        }
        try validateIdentifier(rideID)
    }

    private func validateIdentifier(_ identifier: String) throws {
        guard UUID(uuidString: identifier) != nil,
              identifier == identifier.lowercased()
        else { throw LiveRideCustodyError.invalidIdentifier }
    }

    private func quarantineKnownOwnerlessLegacy() throws {
        guard fileManager.fileExists(atPath: rootURL.path) else { return }
        let legacyNames = [
            "recording.json", "unfinished-ride.json", "rides.db", "rides.db-wal", "rides.db-shm",
        ]
        for name in legacyNames {
            let candidate = rootURL.appendingPathComponent(name)
            if fileManager.fileExists(atPath: candidate.path) {
                try quarantineDirectory(candidate)
            }
        }
    }

    private func quarantine(owner: RecordingOwner, rideID: String) throws {
        let master = try masterKey()
        let ownerDirectory = rootURL.appendingPathComponent(
            Self.ownerTag(owner, master: master),
            isDirectory: true
        )
        try quarantineOwnedDirectory(
            recordingDirectory(owner: owner, rideID: rideID, master: master),
            ownerDirectory: ownerDirectory,
            rideID: rideID
        )
        nextSequences.removeValue(forKey: rideID)
    }

    private func quarantineOwnedDirectory(
        _ source: URL,
        ownerDirectory: URL,
        rideID: String
    ) throws {
        guard fileManager.fileExists(atPath: source.path) else { return }
        let unavailable = ownerDirectory.appendingPathComponent("Unavailable", isDirectory: true)
        try protectDirectory(unavailable)
        let destination = unavailable.appendingPathComponent(
            "\(rideID).\(UUID().uuidString.lowercased()).evidence",
            isDirectory: true
        )
        try fileManager.moveItem(at: source, to: destination)
        try synchronizeDirectory(unavailable)
    }

    private func quarantineDirectory(_ source: URL) throws {
        guard fileManager.fileExists(atPath: source.path) else { return }
        let quarantine = rootURL.appendingPathComponent("Quarantine", isDirectory: true)
        try protectDirectory(quarantine)
        let destination = quarantine.appendingPathComponent(
            "\(UUID().uuidString.lowercased()).evidence",
            isDirectory: source.hasDirectoryPath
        )
        try fileManager.moveItem(at: source, to: destination)
        try synchronizeDirectory(quarantine)
    }
}

/// Sole owner of RecordingSession and its retained sample buffer. The actor
/// serializes Core Location batches, pause boundaries, finalization, and the
/// custody-to-existing-upload-store saga under one stable ride/job UUID.
actor RideRecordingRuntime {
    static let shared = RideRecordingRuntime()

    private struct ActiveSession {
        let manifest: RecordingCustodyManifest
        var session: RecordingSession
        var lastBoundaryAt: Date
        let monotonicOriginS: TimeInterval
        var lastMonotonicOffsetS: TimeInterval
    }

    private struct PendingSuspend: Sendable {
        let manifest: RecordingCustodyManifest
        let occurredAt: Date
        let monotonicOffsetS: TimeInterval
        let stateAtBoundary: RecordingSessionState
    }

    /// Exact ownership transfer for one custody append. Moving the sole
    /// ActiveSession value into this record avoids both full-history COW on
    /// every fix and ambiguity after a publish reports failure. A later safe
    /// caller must first re-submit these byte-equivalent event inputs, then
    /// apply the matching RecordingSession mutation once.
    private struct PendingSessionMutation {
        var current: ActiveSession
        let kind: RecordingCustodyEventKind
        let occurredAt: Date
        let monotonicOffsetS: TimeInterval
        let fix: RecordingSessionFix?
        let eventStateAtBoundary: RecordingSessionState?
        let expectedState: RecordingSessionState
    }

    private struct PendingMarkerMutation {
        let manifest: RecordingCustodyManifest
        let kind: RecordingCustodyEventKind
        let occurredAt: Date
        let monotonicOffsetS: TimeInterval
        let finalArtifact: RecordingFinalArtifact?
    }

    private struct PendingDiscard: Equatable {
        let owner: RecordingOwner
        let rideID: String
    }

    private enum PendingMutation {
        case session(PendingSessionMutation)
        case marker(PendingMarkerMutation)

        var kind: RecordingCustodyEventKind {
            switch self {
            case let .session(value): return value.kind
            case let .marker(value): return value.kind
            }
        }

        var manifest: RecordingCustodyManifest {
            switch self {
            case let .session(value): return value.current.manifest
            case let .marker(value): return value.manifest
            }
        }
    }

    private struct AppliedMutation {
        let kind: RecordingCustodyEventKind
        let occurredAt: Date
        let monotonicOffsetS: TimeInterval
        let fixOutcome: RecordingSessionIngestOutcome?
        let projection: RecordingSessionProjection?
    }

    private let custody: FileLiveRideCustodyStore
    private let uploadQueue: any FirstPartyRideUploadQueuing
    private let now: @Sendable () -> Date
    private let monotonicNow: @Sendable () -> TimeInterval
    private let makeID: @Sendable () -> String
    private let accountWorkPermitted: @Sendable (RecordingOwner) -> Bool
    private var activeOwner: RecordingOwner?
    private var active: ActiveSession?
    private var pendingMutation: PendingMutation?
    private var pendingSuspend: PendingSuspend?
    private var pendingDiscard: PendingDiscard?
    private var exclusiveOperationActive = false
    private var exclusiveOperationWaiters: [CheckedContinuation<Void, Never>] = []

#if DEBUG
    /// Test-target bridge only. Production mutators still require callers to
    /// present the exact captured ID+wallet before any pending state is read.
    func activeOwnerForTesting() -> RecordingOwner? { activeOwner }
#endif

    init(
        custody: FileLiveRideCustodyStore = FileLiveRideCustodyStore(),
        uploadQueue: any FirstPartyRideUploadQueuing = RideUploadRuntime.shared,
        now: @escaping @Sendable () -> Date = { .now },
        monotonicNow: @escaping @Sendable () -> TimeInterval = { ProcessInfo.processInfo.systemUptime },
        makeID: @escaping @Sendable () -> String = { UUID().uuidString.lowercased() },
        accountWorkPermitted: @escaping @Sendable (RecordingOwner) -> Bool = {
            AccountDeletionLocalFence.permitsAccountWork(owner: $0)
        }
    ) {
        self.custody = custody
        self.uploadQueue = uploadQueue
        self.now = now
        self.monotonicNow = monotonicNow
        self.makeID = makeID
        self.accountWorkPermitted = accountWorkPermitted
    }

    func activate(user: User?) async throws -> InterruptedRideRecovery? {
        await beginExclusiveOperation()
        defer { endExclusiveOperation() }
        let newOwner = user.map(RecordingOwner.init(user:))
        if let newOwner,
           !accountWorkPermitted(newOwner) {
            activeOwner = nil
            throw LiveRideCustodyError.ownerMismatch
        }
        if let pendingDiscard {
            // Logout/account replacement clears the active authorization but
            // cannot execute, reveal, or forget another owner's destructive
            // intent. Only the exact captured account+wallet may resume the
            // already-validated parent-directory durability boundary.
            guard newOwner == pendingDiscard.owner else {
                activeOwner = nil
                throw LiveRideCustodyError.ownerMismatch
            }
            activeOwner = newOwner
            try await finishPendingDiscardUnlocked(owner: pendingDiscard.owner)
        }
        if pendingMutation != nil || pendingSuspend != nil {
            try await suspendActiveUnlocked(at: now())
        }
        if activeOwner != newOwner {
            try await suspendActiveUnlocked(at: now())
        }
        activeOwner = newOwner
        guard let newOwner else { return nil }
        try await reconcileFinalized(owner: newOwner)
        guard active == nil else { return nil }
        return try await recoveryEvidenceUnlocked(ownerID: newOwner.id)?.recovery
    }

    private func finishPendingDiscardUnlocked(owner: RecordingOwner) async throws {
        guard let intent = pendingDiscard, intent.owner == owner else {
            throw LiveRideCustodyError.ownerMismatch
        }
        try await custody.discardValidated(owner: intent.owner, rideID: intent.rideID)
        if active?.manifest.id == intent.rideID { active = nil }
        if pendingMutation?.manifest.id == intent.rideID { pendingMutation = nil }
        if pendingSuspend?.manifest.id == intent.rideID { pendingSuspend = nil }
        pendingDiscard = nil
    }

    func start(user: User, at startedAt: Date) async throws -> RecordingSessionProjection {
        await beginExclusiveOperation()
        defer { endExclusiveOperation() }
        let owner = RecordingOwner(user: user)
        guard accountWorkPermitted(owner),
              activeOwner == owner
        else { throw LiveRideCustodyError.ownerMismatch }
        guard pendingDiscard == nil else {
            throw LiveRideCustodyError.corruptEvidence
        }
        if pendingMutation != nil || pendingSuspend != nil {
            try await suspendActiveUnlocked(at: now())
        }
        guard active == nil else { throw LiveRideCustodyError.activeRideExists }
        let id = makeID().lowercased()
        let monotonicOrigin = monotonicNow()
        try await custody.create(owner: owner, rideID: id, startedAt: startedAt)
        var session = RecordingSession()
        session.start(at: startedAt, monotonicNowS: 0)
        let manifest = RecordingCustodyManifest(
            schemaVersion: FileLiveRideCustodyStore.schemaVersion,
            truthPolicyVersion: FileLiveRideCustodyStore.truthPolicyVersion,
            id: id,
            uploadJobID: id,
            ownerID: owner.id,
            ownerWallet: owner.wallet,
            startedAt: startedAt
        )
        active = ActiveSession(
            manifest: manifest,
            session: session,
            lastBoundaryAt: startedAt,
            monotonicOriginS: monotonicOrigin,
            lastMonotonicOffsetS: 0
        )
        return session.projection
    }

    func ingest(
        _ fix: RecordingSessionFix,
        wallNow: Date,
        monotonicNowS: TimeInterval? = nil,
        owner: RecordingOwner
    ) async throws -> (RecordingSessionIngestOutcome, RecordingSessionProjection) {
        await beginExclusiveOperation()
        defer { endExclusiveOperation() }
        guard accountWorkPermitted(owner),
              activeOwner == owner
        else { throw LiveRideCustodyError.ownerMismatch }

        if let pendingMutation {
            guard pendingMutation.kind == .fix else {
                // A queued location callback cannot stand in for a rider's
                // failed Pause, Resume, or End intent. Hardware is stopped on
                // those failures; any already-delivered callback fails closed.
                throw LiveRideCustodyError.noActiveRide
            }
            let isExactRetry: Bool
            if case let .session(pending) = pendingMutation {
                isExactRetry = pending.fix == fix && pending.occurredAt == wallNow
            } else {
                isExactRetry = false
            }
            let applied = try await drainPendingMutationUnlocked()
            if isExactRetry {
                guard let outcome = applied?.fixOutcome,
                      let projection = applied?.projection
                else { throw LiveRideCustodyError.corruptEvidence }
                return (outcome, projection)
            }
        }

        guard let current = active, activeOwnerMatches(current.manifest) else {
            throw LiveRideCustodyError.noActiveRide
        }
        let monotonicOffset = nextMonotonicOffset(
            for: current,
            capturedMonotonicNowS: monotonicNowS
        )
        try stageSessionMutation(
            current: current,
            kind: .fix,
            occurredAt: wallNow,
            monotonicOffsetS: monotonicOffset,
            fix: fix,
            eventStateAtBoundary: nil
        )
        let applied = try await drainPendingMutationUnlocked()
        guard let outcome = applied?.fixOutcome,
              let projection = applied?.projection
        else { throw LiveRideCustodyError.corruptEvidence }
        return (outcome, projection)
    }

    func tick(
        at timestamp: Date,
        powerObservation: PowerObservation?,
        owner: RecordingOwner
    ) async throws -> RecordingSessionProjection {
        await beginExclusiveOperation()
        defer { endExclusiveOperation() }
        guard accountWorkPermitted(owner),
              activeOwner == owner
        else { throw LiveRideCustodyError.ownerMismatch }
        // A timer is not testimony for a failed CLLocation. Only the explicit
        // capture Retry boundary may re-authenticate and apply that exact fix.
        guard pendingMutation == nil else {
            throw LiveRideCustodyError.noActiveRide
        }
        guard var current = active else { throw LiveRideCustodyError.noActiveRide }
        let monotonicOffset = nextMonotonicOffset(for: current)
        current.session.tick(
            at: timestamp,
            monotonicNowS: monotonicOffset,
            powerObservation: powerObservation
        )
        active = current
        return current.session.projection
    }

    /// Explicit rider Retry seam for a failed capture. It authenticates and
    /// drains the exact runtime-owned fix intent (including its original
    /// wall/monotonic times) once. Absence or mismatch fails closed rather
    /// than silently dropping the model's rider-visible callback.
    func retryPendingCapture(
        expectedFix: RecordingSessionFix,
        wallNow: Date,
        owner: RecordingOwner
    ) async throws -> (
        RecordingSessionIngestOutcome,
        RecordingSessionProjection
    ) {
        await beginExclusiveOperation()
        defer { endExclusiveOperation() }
        guard accountWorkPermitted(owner),
              activeOwner == owner
        else { throw LiveRideCustodyError.ownerMismatch }
        guard case let .session(pending)? = pendingMutation,
              pending.kind == .fix,
              pending.fix == expectedFix,
              pending.occurredAt == wallNow
        else {
            throw LiveRideCustodyError.immutableEvidenceChanged
        }
        let applied = try await drainPendingMutationUnlocked()
        guard let outcome = applied?.fixOutcome,
              let projection = applied?.projection
        else {
            throw LiveRideCustodyError.corruptEvidence
        }
        return (outcome, projection)
    }

    func manualPause(
        at timestamp: Date,
        monotonicNowS: TimeInterval? = nil,
        owner: RecordingOwner
    ) async throws -> RecordingSessionProjection {
        await beginExclusiveOperation()
        defer { endExclusiveOperation() }
        guard accountWorkPermitted(owner),
              activeOwner == owner
        else { throw LiveRideCustodyError.ownerMismatch }

        if let pendingMutation {
            switch pendingMutation.kind {
            case .manualPause:
                let applied = try await drainPendingMutationUnlocked()
                guard let projection = applied?.projection else {
                    throw LiveRideCustodyError.corruptEvidence
                }
                return projection
            case .fix:
                throw LiveRideCustodyError.noActiveRide
            default:
                throw LiveRideCustodyError.noActiveRide
            }
        }

        guard let current = active,
              activeOwnerMatches(current.manifest),
              current.session.state == .recording
        else {
            throw LiveRideCustodyError.noActiveRide
        }
        let monotonicOffset = nextMonotonicOffset(
            for: current,
            capturedMonotonicNowS: monotonicNowS
        )
        try stageSessionMutation(
            current: current,
            kind: .manualPause,
            occurredAt: timestamp,
            monotonicOffsetS: monotonicOffset,
            fix: nil,
            eventStateAtBoundary: current.session.state
        )
        let applied = try await drainPendingMutationUnlocked()
        guard let projection = applied?.projection else {
            throw LiveRideCustodyError.corruptEvidence
        }
        return projection
    }

    func manualResume(
        at timestamp: Date,
        monotonicNowS: TimeInterval? = nil,
        owner: RecordingOwner
    ) async throws -> RecordingSessionProjection {
        await beginExclusiveOperation()
        defer { endExclusiveOperation() }
        guard accountWorkPermitted(owner),
              activeOwner == owner
        else { throw LiveRideCustodyError.ownerMismatch }

        if let pendingMutation {
            switch pendingMutation.kind {
            case .manualResume:
                let applied = try await drainPendingMutationUnlocked()
                guard let projection = applied?.projection else {
                    throw LiveRideCustodyError.corruptEvidence
                }
                return projection
            case .fix:
                throw LiveRideCustodyError.noActiveRide
            default:
                throw LiveRideCustodyError.noActiveRide
            }
        }

        guard let current = active,
              activeOwnerMatches(current.manifest),
              current.session.state == .manuallyPaused
        else {
            throw LiveRideCustodyError.noActiveRide
        }
        let monotonicOffset = nextMonotonicOffset(
            for: current,
            capturedMonotonicNowS: monotonicNowS
        )
        try stageSessionMutation(
            current: current,
            kind: .manualResume,
            occurredAt: timestamp,
            monotonicOffsetS: monotonicOffset,
            fix: nil,
            eventStateAtBoundary: current.session.state
        )
        let applied = try await drainPendingMutationUnlocked()
        guard let projection = applied?.projection else {
            throw LiveRideCustodyError.corruptEvidence
        }
        return projection
    }

    func stop(
        at timestamp: Date,
        monotonicNowS: TimeInterval? = nil,
        owner: RecordingOwner
    ) async throws -> FinalizedRecording {
        await beginExclusiveOperation()
        defer { endExclusiveOperation() }
        return try await stopUnlocked(
            at: timestamp,
            monotonicNowS: monotonicNowS,
            owner: owner
        )
    }

    private func stopUnlocked(
        at timestamp: Date,
        monotonicNowS: TimeInterval? = nil,
        owner: RecordingOwner
    ) async throws -> FinalizedRecording {
        guard accountWorkPermitted(owner),
              activeOwner == owner
        else { throw LiveRideCustodyError.ownerMismatch }
        guard pendingDiscard == nil else {
            throw LiveRideCustodyError.immutableEvidenceChanged
        }
        if let pendingMutation {
            guard pendingMutation.kind != .fix else {
                throw LiveRideCustodyError.noActiveRide
            }
            _ = try await drainPendingMutationUnlocked()
        }

        guard let currentBeforeStop = active,
              activeOwnerMatches(currentBeforeStop.manifest)
        else {
            throw LiveRideCustodyError.noActiveRide
        }

        if currentBeforeStop.session.state != .ended {
            let monotonicOffset = nextMonotonicOffset(
                for: currentBeforeStop,
                capturedMonotonicNowS: monotonicNowS
            )
            try stageSessionMutation(
                current: currentBeforeStop,
                kind: .stop,
                occurredAt: timestamp,
                monotonicOffsetS: monotonicOffset,
                fix: nil,
                eventStateAtBoundary: currentBeforeStop.session.state
            )
            _ = try await drainPendingMutationUnlocked()
        }

        guard var current = active else {
            throw LiveRideCustodyError.noActiveRide
        }
        do {
            let result = try await finalize(
                &current,
                at: current.lastBoundaryAt,
                monotonicOffsetS: current.lastMonotonicOffsetS
            )
            active = nil
            return result
        } catch {
            // The stop boundary has already been applied exactly once. Marker
            // or handoff failures retain their own exact pending intent while
            // this ended session remains available for a repeated End.
            active = current
            throw error
        }
    }

    func suspendActive(
        at timestamp: Date,
        monotonicNowS: TimeInterval? = nil,
        owner: RecordingOwner
    ) async throws {
        await beginExclusiveOperation()
        defer { endExclusiveOperation() }
        guard accountWorkPermitted(owner),
              activeOwner == owner
        else { throw LiveRideCustodyError.ownerMismatch }
        try await suspendActiveUnlocked(
            at: timestamp,
            capturedMonotonicNowS: monotonicNowS
        )
    }

    private func suspendActiveUnlocked(
        at timestamp: Date,
        capturedMonotonicNowS: TimeInterval? = nil
    ) async throws {
        if let pendingMutation {
            guard activeOwnerMatches(pendingMutation.manifest) else {
                throw LiveRideCustodyError.ownerMismatch
            }
            let kind = pendingMutation.kind
            _ = try await drainPendingMutationUnlocked()
            if kind == .stop || kind == .finalized || kind == .handedOff {
                // A durable Stop is already a stronger terminal boundary than
                // Suspend. Leave its owner-bound row for Save/reconciliation.
                active = nil
                return
            }
        }
        let pending: PendingSuspend
        if let existing = pendingSuspend {
            guard activeOwnerMatches(existing.manifest) else {
                throw LiveRideCustodyError.ownerMismatch
            }
            pending = existing
        } else {
            guard let current = active else { return }
            guard activeOwnerMatches(current.manifest) else {
                throw LiveRideCustodyError.ownerMismatch
            }
            pending = PendingSuspend(
                manifest: current.manifest,
                occurredAt: timestamp,
                monotonicOffsetS: nextMonotonicOffset(
                    for: current,
                    capturedMonotonicNowS: capturedMonotonicNowS
                ),
                stateAtBoundary: current.session.state
            )
            // Exact-owner isolation wins even when durable storage is
            // unavailable: no subsequent callback may retain or mutate the
            // former rider's live session. Keep the exact boundary separately
            // so Retry publishes the original event instead of reporting a
            // successful no-op or extending it to retry time.
            active = nil
            pendingSuspend = pending
        }
        try await custody.append(
            owner: capturedOwner(for: pending.manifest),
            rideID: pending.manifest.id,
            kind: .suspend,
            occurredAt: pending.occurredAt,
            monotonicOffsetS: pending.monotonicOffsetS,
            stateAtBoundary: pending.stateAtBoundary
        )
        pendingSuspend = nil
    }

    func recovery(ownerID: String) async throws -> InterruptedRideRecovery? {
        try await recoveryEvidence(ownerID: ownerID)?.recovery
    }

    func localSavedRides(user: User) async throws -> [LocalSavedRide] {
        await beginExclusiveOperation()
        defer { endExclusiveOperation() }
        let owner = RecordingOwner(user: user)
        guard accountWorkPermitted(owner),
              activeOwner == owner
        else { throw LiveRideCustodyError.ownerMismatch }
        return try await custody.locallySaved(owner: owner)
    }

    func accountDeletionRecords(owner: RecordingOwner) async throws -> [AccountDeletionCustodyRecord] {
        await beginExclusiveOperation()
        defer { endExclusiveOperation() }
        guard activeOwner == nil || activeOwner == owner else {
            throw LiveRideCustodyError.ownerMismatch
        }
        return try await custody.accountDeletionRecords(owner: owner)
    }

    /// Called only after token-authorized server completion. The initiation
    /// boundary has already frozen this runtime; pending writes or another
    /// active owner make cleanup unavailable rather than widening the target.
    func purgeAccount(owner: RecordingOwner) async throws {
        await beginExclusiveOperation()
        defer { endExclusiveOperation() }
        guard activeOwner == nil || activeOwner == owner else {
            throw LiveRideCustodyError.ownerMismatch
        }
        guard pendingMutation == nil,
              pendingSuspend == nil,
              pendingDiscard == nil
        else { throw LiveRideCustodyError.immutableEvidenceChanged }
        try await custody.purgeAccount(owner: owner)
        if activeOwner == owner { activeOwner = nil }
        active = nil
    }

    /// The full local evidence for one saved-on-device ride: exact artifact
    /// plus recorded fixes. Owner-pinned; refuses anything upload-eligible
    /// (those belong to the upload lane, not the local surface).
    func localSavedRideEvidence(
        user: User,
        rideID: String
    ) async throws -> LocalSavedRideEvidence {
        await beginExclusiveOperation()
        defer { endExclusiveOperation() }
        let owner = RecordingOwner(user: user)
        guard accountWorkPermitted(owner),
              activeOwner == owner
        else { throw LiveRideCustodyError.ownerMismatch }
        let persisted = try await custody.persisted(owner: owner, rideID: rideID)
        guard persisted.manifest.ownerID == owner.id,
              persisted.manifest.ownerWallet == owner.wallet
        else { throw LiveRideCustodyError.ownerMismatch }
        guard let artifact = persisted.finalArtifact, !artifact.uploadEligible else {
            throw LiveRideCustodyError.immutableEvidenceChanged
        }
        return LocalSavedRideEvidence(
            artifact: artifact,
            fixes: persisted.events.compactMap(\.fix)
        )
    }

    func recoveryEvidence(ownerID: String) async throws -> InterruptedRideRecoveryEvidence? {
        await beginExclusiveOperation()
        defer { endExclusiveOperation() }
        return try await recoveryEvidenceUnlocked(ownerID: ownerID)
    }

    private func recoveryEvidenceUnlocked(
        ownerID: String
    ) async throws -> InterruptedRideRecoveryEvidence? {
        guard let owner = activeOwner, owner.id == ownerID else { return nil }
        guard let persisted = try await custody.recoverable(owner: owner) else { return nil }
        guard persisted.manifest.ownerID == owner.id,
              persisted.manifest.ownerWallet == owner.wallet
        else { throw LiveRideCustodyError.ownerMismatch }
        let replayed = try replay(persisted)
        let recovery = InterruptedRideRecovery(
            id: persisted.manifest.id,
            ownerID: ownerID,
            startedAt: persisted.manifest.startedAt,
            state: replayed.session.state,
            sampleCount: replayed.session.samples.count,
            durationS: replayed.session.projection.elapsedS,
            distanceM: replayed.session.distanceM,
            elevationGainM: replayed.session.elevationGainM
        )
        return InterruptedRideRecoveryEvidence(
            recovery: recovery,
            samples: replayed.session.samples
        )
    }

    func saveRecovery(_ recovery: InterruptedRideRecovery) async throws -> FinalizedRecording {
        await beginExclusiveOperation()
        defer { endExclusiveOperation() }
        guard let owner = activeOwner,
              accountWorkPermitted(owner),
              owner.id == recovery.ownerID
        else {
            throw LiveRideCustodyError.ownerMismatch
        }
        if let pendingDiscard {
            guard pendingDiscard.owner == owner,
                  pendingDiscard.rideID == recovery.id
            else { throw LiveRideCustodyError.ownerMismatch }
            throw LiveRideCustodyError.immutableEvidenceChanged
        }
        if let pendingMutation {
            guard pendingMutation.manifest.id == recovery.id else {
                throw LiveRideCustodyError.ownerMismatch
            }
            _ = try await drainPendingMutationUnlocked()
        }
        if let current = active, current.manifest.id == recovery.id {
            return try await stopUnlocked(at: current.lastBoundaryAt, owner: owner)
        }
        let persisted = try await custody.persisted(owner: owner, rideID: recovery.id)
        guard persisted.manifest.ownerID == owner.id,
              persisted.manifest.ownerWallet == owner.wallet
        else { throw LiveRideCustodyError.ownerMismatch }
        active = try replay(persisted)
        guard let replayed = active else {
            throw LiveRideCustodyError.corruptEvidence
        }
        return try await stopUnlocked(at: replayed.lastBoundaryAt, owner: owner)
    }

    func discard(_ recovery: InterruptedRideRecovery) async throws {
        await beginExclusiveOperation()
        defer { endExclusiveOperation() }
        guard let owner = activeOwner,
              accountWorkPermitted(owner),
              owner.id == recovery.ownerID
        else {
            throw LiveRideCustodyError.ownerMismatch
        }
        try await discardOwnedCustodyRecordUnlocked(owner: owner, rideID: recovery.id)
    }

    /// Rider-acknowledged discard of a finalized recording that never
    /// produced upload-eligible evidence — the empty-ride End acknowledgment
    /// (bead c6l2l item 5). Fails closed on anything upload-eligible or
    /// already handed off; a durability failure leaves the exact
    /// pending-discard intent for the next activation to complete.
    func discardFinalizedLocalRecording(_ finalized: FinalizedRecording) async throws {
        await beginExclusiveOperation()
        defer { endExclusiveOperation() }
        guard let owner = activeOwner,
              accountWorkPermitted(owner),
              owner.id == finalized.ownerID
        else {
            throw LiveRideCustodyError.ownerMismatch
        }
        guard !finalized.uploadEligible, finalized.uploadJobID == nil else {
            throw LiveRideCustodyError.immutableEvidenceChanged
        }
        try await discardOwnedCustodyRecordUnlocked(
            owner: owner,
            rideID: finalized.id,
            requireIneligibleFinalArtifact: true
        )
        if active?.manifest.id == finalized.id { active = nil }
    }

    private func discardOwnedCustodyRecordUnlocked(
        owner: RecordingOwner,
        rideID: String,
        requireIneligibleFinalArtifact: Bool = false
    ) async throws {
        let intent = PendingDiscard(owner: owner, rideID: rideID)
        if let pendingDiscard {
            guard pendingDiscard == intent else {
                throw LiveRideCustodyError.ownerMismatch
            }
        } else {
            if let pendingMutation,
               pendingMutation.manifest.id == rideID,
               pendingMutation.kind == .handedOff
            {
                // The upload job exists and may already be reconciling. There
                // is no exact-owner upload cancellation contract in this lane,
                // so custody-only Discard cannot contradict committed Save.
                throw LiveRideCustodyError.immutableEvidenceChanged
            }
            let persisted = try await custody.persisted(
                owner: owner,
                rideID: rideID
            )
            guard persisted.manifest.ownerID == owner.id,
                  persisted.manifest.ownerWallet == owner.wallet
            else { throw LiveRideCustodyError.ownerMismatch }
            guard !persisted.isHandedOff else {
                throw LiveRideCustodyError.immutableEvidenceChanged
            }
            // The empty-ride acknowledgment path re-proves ineligibility on
            // the persisted artifact. The interrupted-ride Discard does not:
            // an eligible ride the rider declined to Save (no queue job yet)
            // remains rightfully discardable.
            if requireIneligibleFinalArtifact,
               persisted.finalArtifact?.uploadEligible == true
            {
                throw LiveRideCustodyError.immutableEvidenceChanged
            }
            pendingDiscard = intent
        }

        try await finishPendingDiscardUnlocked(owner: owner)
    }

    private func finalize(
        _ current: inout ActiveSession,
        at timestamp: Date,
        monotonicOffsetS: TimeInterval
    ) async throws -> FinalizedRecording {
        let persisted = try await custody.persisted(
            owner: capturedOwner(for: current.manifest),
            rideID: current.manifest.id
        )
        if let durable = persisted.finalArtifact {
            return try await handOff(
                durable,
                manifest: current.manifest,
                occurredAt: persisted.lastBoundaryAt,
                monotonicOffsetS: persisted.events.last?.monotonicOffsetS ?? 0,
                alreadyHandedOff: persisted.isHandedOff
            )
        }
        guard current.session.state == .ended else {
            throw LiveRideCustodyError.corruptEvidence
        }

        let gpx = GPXWriter.gpx(
            samples: current.session.samples,
            startedAt: current.manifest.startedAt
        )
        let summary: RideSummary
        if current.session.samples.isEmpty {
            summary = try await WorkoutParser.emptyRecordingSummary(
                startedAt: current.manifest.startedAt
            )
        } else {
            // Only denominator-independent fields (canonical hash, parser
            // version) persist from this summary, but the call still states
            // the rider's derived Threshold truthfully — never a silent default.
            summary = try await WorkoutParser.preliminarySummary(
                data: gpx,
                kind: .gpx,
                // This local summary persists only denominator-independent
                // identity and display fields. The backend projects the one
                // current Threshold denominator after upload.
                thresholdWatts: nil
            )
        }
        let fileHash = FileRideUploadJobStore.sha256(gpx)
        let localSummary = LocalRideSummary(
            // The existing upload-job JSON contract stores ISO-8601 whole
            // seconds. Normalize this display-only summary before both
            // custody and queue persistence so a crash retry compares the
            // exact same immutable value. The Rust canonical stamp still uses
            // the original millisecond ride start above.
            startedAt: Date(
                timeIntervalSince1970: floor(current.manifest.startedAt.timeIntervalSince1970)
            ),
            distanceM: current.session.distanceM,
            elevationM: current.session.elevationGainM,
            durationS: current.session.elapsedS
        )
        let artifact = RecordingFinalArtifact(
            gpxBytes: gpx,
            fileName: "Ride-\(current.manifest.id).gpx",
            fileHash: fileHash,
            preliminaryRideHash: summary.canonicalHashHex,
            parserVersion: summary.parserVersion,
            localSummary: localSummary,
            uploadEligible: RecordingUploadEligibility.allows(
                sampleCount: current.session.samples.count,
                distanceM: current.session.distanceM
            )
        )
        try stageMarkerMutation(
            manifest: current.manifest,
            kind: .finalized,
            occurredAt: timestamp,
            monotonicOffsetS: monotonicOffsetS,
            finalArtifact: artifact
        )
        _ = try await drainPendingMutationUnlocked()
        return try await handOff(
            artifact,
            manifest: current.manifest,
            occurredAt: timestamp,
            monotonicOffsetS: monotonicOffsetS,
            alreadyHandedOff: false
        )
    }

    private func handOff(
        _ artifact: RecordingFinalArtifact,
        manifest: RecordingCustodyManifest,
        occurredAt: Date,
        monotonicOffsetS: TimeInterval,
        alreadyHandedOff: Bool
    ) async throws -> FinalizedRecording {
        var uploadJobID: String?
        if artifact.uploadEligible {
            if alreadyHandedOff {
                uploadJobID = manifest.uploadJobID
            } else {
                let job = try await uploadQueue.enqueueFirstParty(
                    owner: RecordingOwner(id: manifest.ownerID, wallet: manifest.ownerWallet),
                    jobID: manifest.uploadJobID,
                    fileName: artifact.fileName,
                    sourceBytes: artifact.gpxBytes,
                    summary: artifact.localSummary,
                    parserVersion: artifact.parserVersion,
                    preliminaryRideHash: artifact.preliminaryRideHash
                )
                uploadJobID = job.id
                try stageMarkerMutation(
                    manifest: manifest,
                    kind: .handedOff,
                    occurredAt: occurredAt,
                    monotonicOffsetS: monotonicOffsetS,
                    finalArtifact: nil
                )
                do {
                    _ = try await drainPendingMutationUnlocked()
                } catch {
                    guard hasPendingHandedOffMarker(for: manifest) else {
                        throw error
                    }
                    // Queue creation is irreversible in this lane and may
                    // already be reconciling. Preserve the exact marker for a
                    // later activation/start drain, but return the committed
                    // Save outcome so UI cannot offer a contradictory Discard.
                }
            }
        }
        return FinalizedRecording(
            id: manifest.id,
            ownerID: manifest.ownerID,
            gpxBytes: artifact.gpxBytes,
            fileHash: artifact.fileHash,
            preliminaryRideHash: artifact.preliminaryRideHash,
            parserVersion: artifact.parserVersion,
            uploadJobID: uploadJobID,
            uploadEligible: artifact.uploadEligible
        )
    }

    private func replay(_ persisted: PersistedRecording) throws -> ActiveSession {
        var session = RecordingSession()
        var lastBoundary = persisted.manifest.startedAt
        var lastMonotonicOffset: TimeInterval = 0
        for event in persisted.events {
            guard event.schemaVersion == FileLiveRideCustodyStore.schemaVersion else {
                throw LiveRideCustodyError.unsupportedVersion
            }
            switch event.kind {
            case .start:
                session.start(at: event.occurredAt, monotonicNowS: event.monotonicOffsetS)
            case .fix:
                guard let fix = event.fix else { throw LiveRideCustodyError.corruptEvidence }
                _ = session.ingest(
                    fix,
                    wallNow: event.occurredAt,
                    monotonicNowS: event.monotonicOffsetS
                )
            case .manualPause:
                guard session.manualPause(
                    at: event.occurredAt,
                    monotonicNowS: event.monotonicOffsetS
                ) else {
                    throw LiveRideCustodyError.corruptEvidence
                }
            case .manualResume:
                guard session.manualResume(
                    at: event.occurredAt,
                    monotonicNowS: event.monotonicOffsetS
                ) else {
                    throw LiveRideCustodyError.corruptEvidence
                }
            case .stop:
                _ = session.end(
                    at: event.occurredAt,
                    monotonicNowS: event.monotonicOffsetS
                )
            case .suspend, .finalized, .handedOff:
                break
            }
            lastBoundary = event.occurredAt
            guard event.monotonicOffsetS >= lastMonotonicOffset else {
                throw LiveRideCustodyError.corruptEvidence
            }
            lastMonotonicOffset = event.monotonicOffsetS
        }
        if session.state == .recording {
            session.tick(
                at: lastBoundary,
                monotonicNowS: lastMonotonicOffset,
                powerObservation: nil
            )
        }
        return ActiveSession(
            manifest: persisted.manifest,
            session: session,
            lastBoundaryAt: lastBoundary,
            monotonicOriginS: monotonicNow() - lastMonotonicOffset,
            lastMonotonicOffsetS: lastMonotonicOffset
        )
    }

    private func reconcileFinalized(owner: RecordingOwner) async throws {
        let pending = try await custody.finalizedPendingUpload(owner: owner)
        for recording in pending {
            guard let artifact = recording.finalArtifact else { continue }
            guard recording.manifest.ownerID == owner.id,
                  recording.manifest.ownerWallet == owner.wallet
            else { throw LiveRideCustodyError.ownerMismatch }
            let capturedOwner = RecordingOwner(
                id: recording.manifest.ownerID,
                wallet: recording.manifest.ownerWallet
            )
            _ = try await uploadQueue.enqueueFirstParty(
                owner: capturedOwner,
                jobID: recording.manifest.uploadJobID,
                fileName: artifact.fileName,
                sourceBytes: artifact.gpxBytes,
                summary: artifact.localSummary,
                parserVersion: artifact.parserVersion,
                preliminaryRideHash: artifact.preliminaryRideHash
            )
            try stageMarkerMutation(
                manifest: recording.manifest,
                kind: .handedOff,
                occurredAt: now(),
                monotonicOffsetS: recording.events.last?.monotonicOffsetS ?? 0,
                finalArtifact: nil
            )
            do {
                _ = try await drainPendingMutationUnlocked()
            } catch {
                guard hasPendingHandedOffMarker(for: recording.manifest) else {
                    throw error
                }
                // The existing queue accepted this immutable job. Retain the
                // exact local marker intent for the next safe drain.
            }
        }
    }

    private func hasPendingHandedOffMarker(
        for manifest: RecordingCustodyManifest
    ) -> Bool {
        guard case let .marker(marker)? = pendingMutation else { return false }
        return marker.kind == .handedOff && marker.manifest == manifest
    }

    private func stageSessionMutation(
        current: ActiveSession,
        kind: RecordingCustodyEventKind,
        occurredAt: Date,
        monotonicOffsetS: TimeInterval,
        fix: RecordingSessionFix?,
        eventStateAtBoundary: RecordingSessionState?
    ) throws {
        guard pendingMutation == nil else {
            throw LiveRideCustodyError.corruptEvidence
        }
        active = nil
        pendingMutation = .session(
            PendingSessionMutation(
                current: current,
                kind: kind,
                occurredAt: occurredAt,
                monotonicOffsetS: monotonicOffsetS,
                fix: fix,
                eventStateAtBoundary: eventStateAtBoundary,
                expectedState: current.session.state
            )
        )
    }

    private func stageMarkerMutation(
        manifest: RecordingCustodyManifest,
        kind: RecordingCustodyEventKind,
        occurredAt: Date,
        monotonicOffsetS: TimeInterval,
        finalArtifact: RecordingFinalArtifact?
    ) throws {
        guard pendingMutation == nil,
              kind == .finalized || kind == .handedOff
        else { throw LiveRideCustodyError.corruptEvidence }
        pendingMutation = .marker(
            PendingMarkerMutation(
                manifest: manifest,
                kind: kind,
                occurredAt: occurredAt,
                monotonicOffsetS: monotonicOffsetS,
                finalArtifact: finalArtifact
            )
        )
    }

    private func drainPendingMutationUnlocked() async throws -> AppliedMutation? {
        guard let pendingMutation else { return nil }
        switch pendingMutation {
        case var .session(pending):
            guard active == nil,
                  activeOwnerMatches(pending.current.manifest),
                  pending.current.session.state == pending.expectedState
            else { throw LiveRideCustodyError.corruptEvidence }

            try await custody.append(
                owner: capturedOwner(for: pending.current.manifest),
                rideID: pending.current.manifest.id,
                kind: pending.kind,
                occurredAt: pending.occurredAt,
                monotonicOffsetS: pending.monotonicOffsetS,
                fix: pending.fix,
                stateAtBoundary: pending.eventStateAtBoundary
            )

            let fixOutcome: RecordingSessionIngestOutcome?
            switch pending.kind {
            case .fix:
                guard let fix = pending.fix else {
                    throw LiveRideCustodyError.corruptEvidence
                }
                fixOutcome = pending.current.session.ingest(
                    fix,
                    wallNow: pending.occurredAt,
                    monotonicNowS: pending.monotonicOffsetS
                )
            case .manualPause:
                guard pending.current.session.manualPause(
                    at: pending.occurredAt,
                    monotonicNowS: pending.monotonicOffsetS
                ) else { throw LiveRideCustodyError.corruptEvidence }
                fixOutcome = nil
            case .manualResume:
                guard pending.current.session.manualResume(
                    at: pending.occurredAt,
                    monotonicNowS: pending.monotonicOffsetS
                ) else { throw LiveRideCustodyError.corruptEvidence }
                fixOutcome = nil
            case .stop:
                _ = pending.current.session.end(
                    at: pending.occurredAt,
                    monotonicNowS: pending.monotonicOffsetS
                )
                fixOutcome = nil
            default:
                throw LiveRideCustodyError.corruptEvidence
            }
            pending.current.lastBoundaryAt = pending.occurredAt
            pending.current.lastMonotonicOffsetS = pending.monotonicOffsetS
            active = pending.current
            self.pendingMutation = nil
            return AppliedMutation(
                kind: pending.kind,
                occurredAt: pending.occurredAt,
                monotonicOffsetS: pending.monotonicOffsetS,
                fixOutcome: fixOutcome,
                projection: pending.current.session.projection
            )

        case let .marker(pending):
            guard activeOwnerMatches(pending.manifest) else {
                throw LiveRideCustodyError.ownerMismatch
            }
            try await custody.append(
                owner: capturedOwner(for: pending.manifest),
                rideID: pending.manifest.id,
                kind: pending.kind,
                occurredAt: pending.occurredAt,
                monotonicOffsetS: pending.monotonicOffsetS,
                finalArtifact: pending.finalArtifact
            )
            self.pendingMutation = nil
            return AppliedMutation(
                kind: pending.kind,
                occurredAt: pending.occurredAt,
                monotonicOffsetS: pending.monotonicOffsetS,
                fixOutcome: nil,
                projection: active?.session.projection
            )
        }
    }

    private func nextMonotonicOffset(
        for current: ActiveSession,
        capturedMonotonicNowS: TimeInterval? = nil
    ) -> TimeInterval {
        max(
            current.lastMonotonicOffsetS,
            (capturedMonotonicNowS ?? monotonicNow()) - current.monotonicOriginS
        )
    }

    private func capturedOwner(for manifest: RecordingCustodyManifest) -> RecordingOwner {
        RecordingOwner(id: manifest.ownerID, wallet: manifest.ownerWallet)
    }

    private func beginExclusiveOperation() async {
        if !exclusiveOperationActive {
            exclusiveOperationActive = true
            return
        }
        await withCheckedContinuation { continuation in
            exclusiveOperationWaiters.append(continuation)
        }
    }

    private func endExclusiveOperation() {
        guard !exclusiveOperationWaiters.isEmpty else {
            exclusiveOperationActive = false
            return
        }
        exclusiveOperationWaiters.removeFirst().resume()
    }

    private func activeOwnerMatches(_ manifest: RecordingCustodyManifest) -> Bool {
        activeOwner == RecordingOwner(id: manifest.ownerID, wallet: manifest.ownerWallet)
    }
}
