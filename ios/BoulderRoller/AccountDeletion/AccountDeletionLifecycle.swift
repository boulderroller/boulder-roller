import CryptoKit
import Foundation
import Observation
import Security

enum AccountDeletionContract {
    static let version = "account-deletion.v1"
    static let capabilityVersion = 1

    static func makeStatusToken() throws -> String {
        var bytes = Data(count: 32)
        let status = bytes.withUnsafeMutableBytes { buffer in
            SecRandomCopyBytes(kSecRandomDefault, 32, buffer.baseAddress!)
        }
        guard status == errSecSuccess else {
            throw AccountDeletionCapabilityStoreError.unavailable
        }
        return bytes.base64EncodedString()
            .replacingOccurrences(of: "+", with: "-")
            .replacingOccurrences(of: "/", with: "_")
            .replacingOccurrences(of: "=", with: "")
    }
}

struct AccountDeletionBlocker: Codable, Equatable, Sendable {
    let code: String
    let category: String
    let asset: String?
    /// Atomic values are decimal strings on the wire. Decoding them as a
    /// number would silently lose precision for large token balances.
    let amountBaseUnits: String?
    let count: Int?
    let source: String?
    let action: String?
}

struct AccountDeletionPreflight: Codable, Equatable, Sendable {
    let contractVersion: String
    let allowed: Bool
    let available: Bool
    let blockers: [AccountDeletionBlocker]
    let checkedAt: String

    var isAuthoritativeReady: Bool {
        contractVersion == AccountDeletionContract.version
            && available
            && allowed
            && blockers.isEmpty
    }

    /// Available server preflight admits a durable request even when its
    /// requirements remain. The backend persists those requirements as
    /// blocked/needs-support status and never dispatches destructive work;
    /// unavailable or wrong-contract preflight remains fail-closed.
    var isAvailableToFile: Bool {
        contractVersion == AccountDeletionContract.version && available
    }
}

enum AccountDeletionStatusCode: String, Codable, Equatable, Sendable {
    case queued
    case processing
    case blocked
    case failedRetryable = "failed_retryable"
    case needsSupport = "needs_support"
    case completed
    case legacyUnverified = "legacy_unverified"
}

struct AccountDeletionStatus: Codable, Equatable, Sendable {
    let contractVersion: String
    let requestID: String
    let status: AccountDeletionStatusCode
    let requestedAt: String?
    let updatedAt: String?
    let completedAt: String?
    let blockers: [AccountDeletionBlocker]
    let failureCode: String?
    let retryable: Bool
    let attemptCount: Int

    private enum CodingKeys: String, CodingKey {
        case contractVersion
        case requestID = "requestId"
        case status
        case requestedAt
        case updatedAt
        case completedAt
        case blockers
        case failureCode
        case retryable
        case attemptCount
    }

    func isVerifiedCompletion(for capability: AccountDeletionCapability) -> Bool {
        contractVersion == AccountDeletionContract.version
            && requestID.caseInsensitiveCompare(capability.requestID) == .orderedSame
            && status == .completed
            && hasValidCompletionTime
            && blockers.isEmpty
            && failureCode == nil
            && !retryable
            && attemptCount > 0
    }

    private var hasValidCompletionTime: Bool {
        guard let completedAt, !completedAt.isEmpty else { return false }
        let fractional = ISO8601DateFormatter()
        fractional.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
        if fractional.date(from: completedAt) != nil { return true }
        let wholeSeconds = ISO8601DateFormatter()
        wholeSeconds.formatOptions = [.withInternetDateTime]
        return wholeSeconds.date(from: completedAt) != nil
    }
}

struct AccountDeletionCustodyRecord: Equatable, Sendable {
    let rideID: String
    let uploadJobID: String
    let startedAt: Date
    let handedOff: Bool
}

struct AccountDeletionUploadRecord: Equatable, Sendable {
    let id: String
    let fileName: String
    let startedAt: Date
    let phase: RideUploadPhase
}

struct AccountDeletionLocalRide: Equatable, Identifiable, Sendable {
    enum State: String, Equatable, Sendable {
        case unuploaded
    }

    let id: String
    let fileName: String
    let startedAt: Date
    let state: State
}

enum AccountDeletionInventoryError: Error, Equatable {
    case inconsistentHandoff
}

struct AccountDeletionLocalInventory: Equatable, Sendable {
    let rides: [AccountDeletionLocalRide]
    let digest: String

    static let empty = AccountDeletionLocalInventory(rides: [])

    init(rides: [AccountDeletionLocalRide]) {
        self.rides = rides.sorted {
            if $0.startedAt == $1.startedAt { return $0.id < $1.id }
            return $0.startedAt < $1.startedAt
        }
        digest = Self.digest(for: self.rides)
    }

    /// Custody and upload storage deliberately share one stable job UUID.
    /// A handed-off custody row is not a second ride: its queue row decides
    /// whether server acceptance is final. Missing queue evidence is an
    /// unavailable inventory, never permission to delete.
    init(
        custody: [AccountDeletionCustodyRecord],
        uploads: [AccountDeletionUploadRecord]
    ) throws {
        let uploadByID = Dictionary(uniqueKeysWithValues: uploads.map { ($0.id, $0) })
        var unuploaded: [String: AccountDeletionLocalRide] = [:]

        for record in custody {
            if record.handedOff {
                guard let upload = uploadByID[record.uploadJobID] else {
                    throw AccountDeletionInventoryError.inconsistentHandoff
                }
                if upload.phase != .final {
                    unuploaded[upload.id] = AccountDeletionLocalRide(
                        id: upload.id,
                        fileName: upload.fileName,
                        startedAt: upload.startedAt,
                        state: .unuploaded
                    )
                }
            } else {
                unuploaded[record.uploadJobID] = AccountDeletionLocalRide(
                    id: record.uploadJobID,
                    fileName: "Ride-\(record.rideID).gpx",
                    startedAt: record.startedAt,
                    state: .unuploaded
                )
            }
        }

        for upload in uploads where upload.phase != .final {
            unuploaded[upload.id] = AccountDeletionLocalRide(
                id: upload.id,
                fileName: upload.fileName,
                startedAt: upload.startedAt,
                state: .unuploaded
            )
        }
        self.init(rides: Array(unuploaded.values))
    }

    private static func digest(for rides: [AccountDeletionLocalRide]) -> String {
        digest(forRideIDs: rides.map(\.id))
    }

    static func digest(forRideIDs rideIDs: [String]) -> String {
        let canonical = rideIDs
            .sorted()
            .map { "\($0)|\(AccountDeletionLocalRide.State.unuploaded.rawValue)" }
            .joined(separator: "\n")
        return SHA256.hash(data: Data(canonical.utf8))
            .map { String(format: "%02x", $0) }
            .joined()
    }
}

enum AccountDeletionInventoryAvailability: Equatable, Sendable {
    case unavailable
    case available(AccountDeletionLocalInventory)
}

enum AccountDeletionRequestGate {
    static func allows(
        preflight: AccountDeletionPreflight,
        inventory: AccountDeletionInventoryAvailability,
        reviewedInventoryDigest: String?
    ) -> Bool {
        guard preflight.isAvailableToFile,
              case let .available(current) = inventory
        else { return false }
        return reviewedInventoryDigest == current.digest
    }
}

struct AccountDeletionCapability: Codable, Equatable, Sendable {
    let version: Int
    let requestID: String
    let statusToken: String
    private let ownerID: String?
    private let ownerWallet: String?
    let inventoryDigest: String
    let acknowledgedRideIDs: [String]
    let unuploadedRidesAcknowledged: Bool
    let createdAt: Date
    let verifiedCompletion: AccountDeletionStatus?
    let localCleanupCompletedAt: Date?

    var owner: RecordingOwner? {
        guard let ownerID, !ownerID.isEmpty,
              let ownerWallet, !ownerWallet.isEmpty
        else { return nil }
        return RecordingOwner(id: ownerID, wallet: ownerWallet)
    }

    init(
        requestID: String,
        statusToken: String,
        owner: RecordingOwner,
        inventoryDigest: String,
        acknowledgedRideIDs: [String],
        unuploadedRidesAcknowledged: Bool,
        createdAt: Date,
        verifiedCompletion: AccountDeletionStatus? = nil,
        localCleanupCompletedAt: Date?
    ) {
        version = AccountDeletionContract.capabilityVersion
        self.requestID = requestID
        self.statusToken = statusToken
        ownerID = owner.id
        ownerWallet = owner.wallet
        self.inventoryDigest = inventoryDigest
        self.acknowledgedRideIDs = acknowledgedRideIDs.sorted()
        self.unuploadedRidesAcknowledged = unuploadedRidesAcknowledged
        self.createdAt = createdAt
        self.verifiedCompletion = verifiedCompletion
        self.localCleanupCompletedAt = localCleanupCompletedAt
    }

    static func make(
        owner: RecordingOwner,
        inventory: AccountDeletionLocalInventory,
        unuploadedRidesAcknowledged: Bool
    ) throws -> Self {
        Self(
            requestID: UUID().uuidString.lowercased(),
            statusToken: try AccountDeletionContract.makeStatusToken(),
            owner: owner,
            inventoryDigest: inventory.digest,
            acknowledgedRideIDs: inventory.rides.map(\.id),
            unuploadedRidesAcknowledged: unuploadedRidesAcknowledged,
            createdAt: .now,
            verifiedCompletion: nil,
            localCleanupCompletedAt: nil
        )
    }

    func acknowledging(
        inventory: AccountDeletionLocalInventory,
        unuploadedRidesAcknowledged: Bool
    ) -> Self {
        guard let owner else { return self }
        return Self(
            requestID: requestID,
            statusToken: statusToken,
            owner: owner,
            inventoryDigest: inventory.digest,
            acknowledgedRideIDs: inventory.rides.map(\.id),
            unuploadedRidesAcknowledged: unuploadedRidesAcknowledged,
            createdAt: createdAt,
            verifiedCompletion: nil,
            localCleanupCompletedAt: nil
        )
    }

    func acknowledgingAdditionalCleanupInventory(
        _ inventory: AccountDeletionLocalInventory
    ) -> Self? {
        guard let owner, let verifiedCompletion else { return nil }
        return Self(
            requestID: requestID,
            statusToken: statusToken,
            owner: owner,
            inventoryDigest: inventory.digest,
            acknowledgedRideIDs: inventory.rides.map(\.id),
            unuploadedRidesAcknowledged: true,
            createdAt: createdAt,
            verifiedCompletion: verifiedCompletion,
            localCleanupCompletedAt: nil
        )
    }

    func markingServerCompletionVerified(_ status: AccountDeletionStatus) -> Self? {
        guard let owner, status.isVerifiedCompletion(for: self) else { return nil }
        return Self(
            requestID: requestID,
            statusToken: statusToken,
            owner: owner,
            inventoryDigest: inventoryDigest,
            acknowledgedRideIDs: acknowledgedRideIDs,
            unuploadedRidesAcknowledged: unuploadedRidesAcknowledged,
            createdAt: createdAt,
            verifiedCompletion: status,
            localCleanupCompletedAt: nil
        )
    }

    func markingLocalCleanupCompleted(at date: Date = .now) -> Self? {
        guard owner != nil, let verifiedCompletion else { return nil }
        return Self(
            version: version,
            requestID: requestID,
            statusToken: statusToken,
            ownerID: nil,
            ownerWallet: nil,
            inventoryDigest: AccountDeletionLocalInventory.empty.digest,
            acknowledgedRideIDs: [],
            unuploadedRidesAcknowledged: true,
            createdAt: createdAt,
            verifiedCompletion: verifiedCompletion,
            localCleanupCompletedAt: date
        )
    }

    private init(
        version: Int,
        requestID: String,
        statusToken: String,
        ownerID: String?,
        ownerWallet: String?,
        inventoryDigest: String,
        acknowledgedRideIDs: [String],
        unuploadedRidesAcknowledged: Bool,
        createdAt: Date,
        verifiedCompletion: AccountDeletionStatus?,
        localCleanupCompletedAt: Date?
    ) {
        self.version = version
        self.requestID = requestID
        self.statusToken = statusToken
        self.ownerID = ownerID
        self.ownerWallet = ownerWallet
        self.inventoryDigest = inventoryDigest
        self.acknowledgedRideIDs = acknowledgedRideIDs
        self.unuploadedRidesAcknowledged = unuploadedRidesAcknowledged
        self.createdAt = createdAt
        self.verifiedCompletion = verifiedCompletion
        self.localCleanupCompletedAt = localCleanupCompletedAt
    }

    var isValid: Bool {
        let normalizedRideIDs = Array(Set(acknowledgedRideIDs)).sorted()
        return version == AccountDeletionContract.capabilityVersion
            && UUID(uuidString: requestID) != nil
            && statusToken.count == 43
            && Data(base64URLEncoded: statusToken)?.count == 32
            && unuploadedRidesAcknowledged
            && acknowledgedRideIDs == normalizedRideIDs
            && inventoryDigest == AccountDeletionLocalInventory.digest(
                forRideIDs: acknowledgedRideIDs
            )
            && (owner != nil || localCleanupCompletedAt != nil)
            && (verifiedCompletion == nil || verifiedCompletion?.isVerifiedCompletion(for: self) == true)
            && (localCleanupCompletedAt == nil || verifiedCompletion != nil)
    }

    func acknowledgesForCleanup(_ inventory: AccountDeletionLocalInventory) -> Bool {
        let acknowledged = Set(acknowledgedRideIDs)
        return inventory.rides.allSatisfy { acknowledged.contains($0.id) }
    }
}

private extension Data {
    init?(base64URLEncoded value: String) {
        let standard = value
            .replacingOccurrences(of: "-", with: "+")
            .replacingOccurrences(of: "_", with: "/")
        let padding = String(repeating: "=", count: (4 - standard.count % 4) % 4)
        self.init(base64Encoded: standard + padding)
    }
}

enum AccountDeletionCapabilityStorageState: Equatable, Sendable {
    case none
    case unavailable
    /// A committing request may have crossed the network, but the server has
    /// not yet confirmed the request ID/token pair. It fences local writers
    /// without activating the app-wide accepted-status route.
    case unconfirmed(AccountDeletionCapability)
    case available(AccountDeletionCapability)

    var capability: AccountDeletionCapability? {
        switch self {
        case let .unconfirmed(capability), let .available(capability):
            return capability
        case .none, .unavailable:
            return nil
        }
    }
}

private struct AccountDeletionCapabilityEnvelope: Codable, Equatable {
    enum Phase: String, Codable {
        case unconfirmed
        case accepted
    }

    let version: Int
    let phase: Phase
    let capability: AccountDeletionCapability

    init(phase: Phase, capability: AccountDeletionCapability) {
        version = 2
        self.phase = phase
        self.capability = capability
    }
}

private struct AccountDeletionCapabilityLedger: Codable, Equatable {
    let version: Int
    let entries: [AccountDeletionCapabilityEnvelope]

    init(entries: [AccountDeletionCapabilityEnvelope]) {
        version = 3
        self.entries = entries
    }
}

enum AccountDeletionCapabilityStoreError: Error, Equatable {
    case unavailable
    case invalid
}

enum AccountDeletionLocalCleanupError: Error, Equatable {
    case verificationFailed
}

protocol AccountDeletionCapabilityStoring: Sendable {
    func load() -> AccountDeletionCapabilityStorageState
    func load(owner: RecordingOwner?) -> AccountDeletionCapabilityStorageState
    func load(requestID: String) -> AccountDeletionCapabilityStorageState
    func loadAll() -> [AccountDeletionCapabilityStorageState]
    func saveUnconfirmed(_ capability: AccountDeletionCapability) throws
    /// Saving through this method means a matching server response has
    /// authoritatively accepted the request ID/token pair.
    func save(_ capability: AccountDeletionCapability) throws
    func delete() throws
    func delete(_ capability: AccountDeletionCapability) throws
}

extension AccountDeletionCapabilityStoring {
    func load(owner: RecordingOwner?) -> AccountDeletionCapabilityStorageState {
        let state = load()
        guard let owner, let capability = state.capability else { return state }
        return capability.owner == owner ? state : .none
    }

    func load(requestID: String) -> AccountDeletionCapabilityStorageState {
        let state = load()
        guard let capability = state.capability else { return state }
        return capability.requestID.caseInsensitiveCompare(requestID) == .orderedSame
            ? state
            : .none
    }

    func loadAll() -> [AccountDeletionCapabilityStorageState] {
        [load()]
    }

    func saveUnconfirmed(_ capability: AccountDeletionCapability) throws {
        try save(capability)
    }

    func delete(_ capability: AccountDeletionCapability) throws {
        try delete()
    }
}

struct KeychainAccountDeletionCapabilityStore: AccountDeletionCapabilityStoring {
    private static let markerKey = "br.account_deletion.capability_present.v1"
    private static let storageLock = NSLock()

    func load() -> AccountDeletionCapabilityStorageState {
        Self.selectLast(from: loadAll())
    }

    func load(owner: RecordingOwner?) -> AccountDeletionCapabilityStorageState {
        guard let owner else { return load() }
        return Self.selectLast(from: loadAll()) { $0.owner == owner }
    }

    func load(requestID: String) -> AccountDeletionCapabilityStorageState {
        Self.selectLast(from: loadAll()) {
            $0.requestID.caseInsensitiveCompare(requestID) == .orderedSame
        }
    }

    func loadAll() -> [AccountDeletionCapabilityStorageState] {
        Self.storageLock.withLock {
            let marked = UserDefaults.standard.bool(forKey: Self.markerKey)
            return Self.loadStates(marked: marked) {
                try KeychainStore.readRequired(.accountDeletionCapability)
            }
        }
    }

    private static func selectLast(
        from states: [AccountDeletionCapabilityStorageState],
        where predicate: (AccountDeletionCapability) -> Bool = { _ in true }
    ) -> AccountDeletionCapabilityStorageState {
        if states.contains(.unavailable) { return .unavailable }
        return states.last(where: { state in
            state.capability.map(predicate) ?? false
        }) ?? .none
    }

    static func loadState(
        marked: Bool,
        readValue: () throws -> String?
    ) -> AccountDeletionCapabilityStorageState {
        selectLast(from: loadStates(marked: marked, readValue: readValue))
    }

    static func loadStates(
        marked: Bool,
        readValue: () throws -> String?
    ) -> [AccountDeletionCapabilityStorageState] {
        do {
            guard let encoded = try readValue() else {
                return [marked ? .unavailable : .none]
            }
            guard let data = encoded.data(using: .utf8) else { return [.unavailable] }
            if let ledger = try? JSONDecoder().decode(
                AccountDeletionCapabilityLedger.self,
                from: data
            ), ledger.version == 3,
               !ledger.entries.isEmpty,
               Self.validLedgerEntries(ledger.entries) {
                return ledger.entries.map(Self.storageState)
            }
            if let envelope = try? JSONDecoder().decode(
                AccountDeletionCapabilityEnvelope.self,
                from: data
            ), envelope.version == 2, envelope.capability.isValid {
                return [Self.storageState(envelope)]
            }
            // Version-1 native builds wrote a raw capability before DELETE.
            // Its server acceptance is unknowable, so migrate it into scoped
            // recovery and probe status instead of globally locking the app.
            if let legacy = try? JSONDecoder().decode(AccountDeletionCapability.self, from: data),
               legacy.isValid {
                return [.unconfirmed(legacy)]
            }
            return [.unavailable]
        } catch {
            // Only a positive missing-item read can mean no request. A locked,
            // unavailable, or otherwise failed Keychain read must never route
            // a possibly pending deletion back into ordinary account work.
            return [.unavailable]
        }
    }

    private static func storageState(
        _ envelope: AccountDeletionCapabilityEnvelope
    ) -> AccountDeletionCapabilityStorageState {
        switch envelope.phase {
        case .unconfirmed: return .unconfirmed(envelope.capability)
        case .accepted: return .available(envelope.capability)
        }
    }

    private static func validLedgerEntries(
        _ entries: [AccountDeletionCapabilityEnvelope]
    ) -> Bool {
        guard entries.allSatisfy({
            $0.version == 2 && $0.capability.isValid
        }) else { return false }
        let requestIDs = entries.map { $0.capability.requestID.lowercased() }
        return Set(requestIDs).count == requestIDs.count
    }

    private static func decodeLedgerEntries(
        _ encoded: String?
    ) throws -> [AccountDeletionCapabilityEnvelope] {
        guard let encoded else { return [] }
        guard let data = encoded.data(using: .utf8) else {
            throw AccountDeletionCapabilityStoreError.invalid
        }
        if let ledger = try? JSONDecoder().decode(
            AccountDeletionCapabilityLedger.self,
            from: data
        ), ledger.version == 3,
           !ledger.entries.isEmpty,
           validLedgerEntries(ledger.entries) {
            return ledger.entries
        }
        if let envelope = try? JSONDecoder().decode(
            AccountDeletionCapabilityEnvelope.self,
            from: data
        ), envelope.version == 2, envelope.capability.isValid {
            return [envelope]
        }
        if let legacy = try? JSONDecoder().decode(AccountDeletionCapability.self, from: data),
           legacy.isValid {
            return [AccountDeletionCapabilityEnvelope(phase: .unconfirmed, capability: legacy)]
        }
        throw AccountDeletionCapabilityStoreError.invalid
    }

    private static func encodedLedger(
        _ entries: [AccountDeletionCapabilityEnvelope]
    ) throws -> String {
        guard !entries.isEmpty, validLedgerEntries(entries),
              let value = String(
                data: try JSONEncoder().encode(
                    AccountDeletionCapabilityLedger(entries: entries)
                ),
                encoding: .utf8
              )
        else { throw AccountDeletionCapabilityStoreError.invalid }
        return value
    }

    static func ledgerValue(
        existingValue: String?,
        upserting capability: AccountDeletionCapability,
        accepted: Bool
    ) throws -> String {
        guard capability.isValid else { throw AccountDeletionCapabilityStoreError.invalid }
        var entries = try decodeLedgerEntries(existingValue)
        let replacement = AccountDeletionCapabilityEnvelope(
            phase: accepted ? .accepted : .unconfirmed,
            capability: capability
        )
        if let index = entries.firstIndex(where: {
            $0.capability.requestID.caseInsensitiveCompare(capability.requestID) == .orderedSame
        }) {
            entries[index] = replacement
        } else {
            entries.append(replacement)
        }
        return try encodedLedger(entries)
    }

    static func ledgerValue(
        existingValue: String?,
        removing capability: AccountDeletionCapability
    ) throws -> String? {
        var entries = try decodeLedgerEntries(existingValue)
        guard let index = entries.firstIndex(where: {
            $0.capability.requestID.caseInsensitiveCompare(capability.requestID) == .orderedSame
                && $0.capability.statusToken == capability.statusToken
        }) else { throw AccountDeletionCapabilityStoreError.invalid }
        entries.remove(at: index)
        return entries.isEmpty ? nil : try encodedLedger(entries)
    }

    func saveUnconfirmed(_ capability: AccountDeletionCapability) throws {
        try save(capability, phase: .unconfirmed)
    }

    func save(_ capability: AccountDeletionCapability) throws {
        try save(capability, phase: .accepted)
    }

    private func save(
        _ capability: AccountDeletionCapability,
        phase: AccountDeletionCapabilityEnvelope.Phase
    ) throws {
        try Self.storageLock.withLock {
            do {
                let existing = try KeychainStore.readRequired(.accountDeletionCapability)
                let value = try Self.ledgerValue(
                    existingValue: existing,
                    upserting: capability,
                    accepted: phase == .accepted
                )
                try Self.saveCrashConsistently(
                    saveCapability: {
                        try KeychainStore.saveRequired(value, for: .accountDeletionCapability)
                    },
                    capabilityMatches: {
                        try KeychainStore.readRequired(.accountDeletionCapability) == value
                    },
                    setMarker: {
                        UserDefaults.standard.set(true, forKey: Self.markerKey)
                    },
                    markerIsPresent: {
                        UserDefaults.standard.bool(forKey: Self.markerKey)
                    },
                    synchronizeMarker: { UserDefaults.standard.synchronize() }
                )
            } catch let error as AccountDeletionCapabilityStoreError {
                throw error
            } catch {
                throw AccountDeletionCapabilityStoreError.unavailable
            }
        }
    }

    static func saveCrashConsistently(
        saveCapability: () throws -> Void,
        capabilityMatches: () throws -> Bool,
        setMarker: () -> Void,
        markerIsPresent: () -> Bool,
        synchronizeMarker: () -> Bool
    ) throws {
        // The recoverable envelope comes first. loadState reads Keychain even
        // without the marker, so a crash here still rehydrates the fenced
        // request. DELETE remains forbidden until both stores read back.
        try saveCapability()
        guard try capabilityMatches() else {
            throw AccountDeletionCapabilityStoreError.unavailable
        }
        setMarker()
        guard markerIsPresent(), synchronizeMarker(), markerIsPresent(),
              try capabilityMatches()
        else { throw AccountDeletionCapabilityStoreError.unavailable }
    }

    func delete() throws {
        guard let capability = load().capability else {
            throw AccountDeletionCapabilityStoreError.invalid
        }
        try delete(capability)
    }

    func delete(_ capability: AccountDeletionCapability) throws {
        try Self.storageLock.withLock {
            do {
                let existingValue = try KeychainStore.readRequired(.accountDeletionCapability)
                let remainingValue = try Self.ledgerValue(
                    existingValue: existingValue,
                    removing: capability
                )
                if remainingValue == nil {
                    try Self.deleteCrashConsistently(
                        removeMarker: {
                            UserDefaults.standard.removeObject(forKey: Self.markerKey)
                        },
                        markerIsAbsent: {
                            UserDefaults.standard.object(forKey: Self.markerKey) == nil
                        },
                        synchronizeMarker: { UserDefaults.standard.synchronize() },
                        deleteCapability: {
                            try KeychainStore.deleteRequired(.accountDeletionCapability)
                        },
                        readCapability: {
                            try KeychainStore.readRequired(.accountDeletionCapability)
                        }
                    )
                } else {
                    guard let value = remainingValue else {
                        throw AccountDeletionCapabilityStoreError.invalid
                    }
                    try Self.saveCrashConsistently(
                        saveCapability: {
                            try KeychainStore.saveRequired(value, for: .accountDeletionCapability)
                        },
                        capabilityMatches: {
                            try KeychainStore.readRequired(.accountDeletionCapability) == value
                        },
                        setMarker: {
                            UserDefaults.standard.set(true, forKey: Self.markerKey)
                        },
                        markerIsPresent: {
                            UserDefaults.standard.bool(forKey: Self.markerKey)
                        },
                        synchronizeMarker: { UserDefaults.standard.synchronize() }
                    )
                }
            } catch let error as AccountDeletionCapabilityStoreError {
                throw error
            } catch {
                throw AccountDeletionCapabilityStoreError.unavailable
            }
        }
    }

    static func deleteCrashConsistently(
        removeMarker: () -> Void,
        markerIsAbsent: () -> Bool,
        synchronizeMarker: () -> Bool,
        deleteCapability: () throws -> Void,
        readCapability: () throws -> String?
    ) throws {
        // Clear and flush the witness while the capability is still durable.
        // A process kill before the Keychain delete therefore reloads the
        // request and makes acknowledgement safely repeatable.
        removeMarker()
        guard markerIsAbsent(), synchronizeMarker(), markerIsAbsent()
        else { throw AccountDeletionCapabilityStoreError.unavailable }
        try deleteCapability()
        guard try readCapability() == nil else {
            throw AccountDeletionCapabilityStoreError.unavailable
        }
    }

}

protocol AccountDeletionServing: Sendable {
    func preflight() async throws -> AccountDeletionPreflight
    func create(capability: AccountDeletionCapability) async throws -> AccountDeletionStatus
    func status(capability: AccountDeletionCapability) async throws -> AccountDeletionStatus
    func retry(capability: AccountDeletionCapability) async throws -> AccountDeletionStatus
}

struct AccountDeletionCreatePayload: Encodable, Equatable, Sendable {
    let requestID: String
    let statusToken: String
    let unuploadedRidesAcknowledged: Bool
}

struct AccountDeletionRetryPayload: Encodable, Equatable, Sendable {}

enum AccountDeletionWire {
    static func createPayload(
        for capability: AccountDeletionCapability
    ) -> AccountDeletionCreatePayload {
        AccountDeletionCreatePayload(
            requestID: capability.requestID,
            statusToken: capability.statusToken,
            unuploadedRidesAcknowledged: capability.unuploadedRidesAcknowledged
        )
    }

    static let retryPayload = AccountDeletionRetryPayload()
}

enum AccountDeletionConflictCode: String, Equatable, Sendable {
    case requestAlreadyActive = "request_already_active"
    case accountUnavailable = "account_unavailable"
    case requestIDConflict = "request_id_conflict"
    case retryUnavailable = "retry_unavailable"
    case retryRequiresSupport = "retry_requires_support"
}

@MainActor
@Observable
final class AccountDeletionModel {
    enum State: Equatable {
        case loading
        case ready(AccountDeletionPreflight, AccountDeletionLocalInventory)
        case retryReview(AccountDeletionStatus, AccountDeletionLocalInventory)
        case requesting
        case tracking(AccountDeletionStatus)
        case requestNotFound
        case statusUnavailable
        case storageUnavailable
        case ownerMismatch
        case supportRequired(AccountDeletionConflictCode?)
        case clearingLocalData
        case localCleanupFailed
        case completed(AccountDeletionStatus)
        case completedLocally
        case discarded
    }

    var state: State = .loading
    private(set) var pollFailureCount = 0

    var pollDelaySeconds: Int {
        min(5 * (1 << min(pollFailureCount, 2)), 20)
    }

    var canDiscardSavedStatus: Bool {
        switch activeCapabilityStorage() {
        case .unconfirmed:
            return state == .requestNotFound
        case .available:
            switch state {
            case .requestNotFound, .statusUnavailable, .storageUnavailable,
                 .supportRequired, .discarded:
                return true
            case let .tracking(status):
                return status.status == .needsSupport
                    || status.status == .legacyUnverified
                    || (status.status == .blocked && !status.retryable)
            default:
                return false
            }
        case .none, .unavailable:
            return false
        }
    }

    @ObservationIgnored private let service: any AccountDeletionServing
    @ObservationIgnored private let capabilityStore: any AccountDeletionCapabilityStoring
    @ObservationIgnored private var loadInventory: @MainActor @Sendable () async throws -> AccountDeletionLocalInventory
    @ObservationIgnored private var localCleanup: @MainActor @Sendable (AccountDeletionCapability, AccountDeletionStatus) async throws -> Void
    @ObservationIgnored private var capabilityDidChange: @MainActor @Sendable () async throws -> Void
    @ObservationIgnored private var localCleanupDidComplete: @MainActor @Sendable (RecordingOwner) async throws -> Void
    @ObservationIgnored private var acceptedStatusDiscarded: @MainActor @Sendable (RecordingOwner?) async throws -> Void
    @ObservationIgnored private var generation = UUID()
    @ObservationIgnored private var isCleaningLocalData = false
    @ObservationIgnored private var activeRequestID: String?

    init(
        service: any AccountDeletionServing = APIClient.shared,
        capabilityStore: any AccountDeletionCapabilityStoring = KeychainAccountDeletionCapabilityStore(),
        inventory: @escaping @MainActor @Sendable () async throws -> AccountDeletionLocalInventory = {
            throw AccountDeletionCapabilityStoreError.unavailable
        },
        localCleanup: @escaping @MainActor @Sendable (AccountDeletionCapability, AccountDeletionStatus) async throws -> Void = { _, _ in
            throw AccountDeletionCapabilityStoreError.unavailable
        },
        capabilityDidChange: @escaping @MainActor @Sendable () async throws -> Void = {},
        localCleanupDidComplete: @escaping @MainActor @Sendable (RecordingOwner) async throws -> Void = { _ in },
        acceptedStatusDiscarded: @escaping @MainActor @Sendable (RecordingOwner?) async throws -> Void = { _ in
            throw AccountDeletionCapabilityStoreError.unavailable
        }
    ) {
        self.service = service
        self.capabilityStore = capabilityStore
        loadInventory = inventory
        self.localCleanup = localCleanup
        self.capabilityDidChange = capabilityDidChange
        self.localCleanupDidComplete = localCleanupDidComplete
        self.acceptedStatusDiscarded = acceptedStatusDiscarded
    }

    func configure(
        inventory: @escaping @MainActor @Sendable () async throws -> AccountDeletionLocalInventory,
        localCleanup: @escaping @MainActor @Sendable (AccountDeletionCapability, AccountDeletionStatus) async throws -> Void,
        capabilityDidChange: @escaping @MainActor @Sendable () async throws -> Void,
        localCleanupDidComplete: @escaping @MainActor @Sendable (RecordingOwner) async throws -> Void,
        acceptedStatusDiscarded: @escaping @MainActor @Sendable (RecordingOwner?) async throws -> Void
    ) {
        loadInventory = inventory
        self.localCleanup = localCleanup
        self.capabilityDidChange = capabilityDidChange
        self.localCleanupDidComplete = localCleanupDidComplete
        self.acceptedStatusDiscarded = acceptedStatusDiscarded
    }

    func load(owner: RecordingOwner?, requestID: String? = nil) async {
        let operation = UUID()
        generation = operation
        state = .loading
        let storage = requestID.map { capabilityStore.load(requestID: $0) }
            ?? capabilityStore.load(owner: owner)
        activeRequestID = storage.capability?.requestID
        switch storage {
        case .unavailable:
            state = .storageUnavailable
        case let .unconfirmed(capability):
            guard capabilityBelongsTo(owner: owner, capability: capability) else {
                state = .ownerMismatch
                return
            }
            if capability.localCleanupCompletedAt != nil {
                await presentCompletedLocally(operation: operation)
                return
            }
            if let completion = capability.verifiedCompletion {
                await resumeVerifiedCompletion(
                    completion,
                    capability: capability,
                    operation: operation
                )
                return
            }
            await readStatus(
                capability: capability,
                operation: operation,
                promoteUnconfirmed: true
            )
        case let .available(capability):
            guard capabilityBelongsTo(owner: owner, capability: capability) else {
                state = .ownerMismatch
                return
            }
            if capability.localCleanupCompletedAt != nil {
                await presentCompletedLocally(operation: operation)
                return
            }
            if let completion = capability.verifiedCompletion {
                await resumeVerifiedCompletion(
                    completion,
                    capability: capability,
                    operation: operation
                )
                return
            }
            // Relaunch may occur after ordinary auth is tombstoned. Reassert
            // the local write fence first, but never let a local freeze error
            // hide the server status capability.
            try? await capabilityDidChange()
            guard generation == operation else { return }
            await readStatus(
                capability: capability,
                operation: operation,
                promoteUnconfirmed: false
            )
        case .none:
            guard owner != nil else {
                state = .statusUnavailable
                return
            }
            await loadReady(operation: operation)
        }
    }

    func requestDeletion(
        owner: RecordingOwner,
        reviewedInventoryDigest: String?,
        unuploadedRidesAcknowledged: Bool
    ) async {
        let operation = UUID()
        generation = operation
        state = .requesting
        do {
            async let preflight = service.preflight()
            async let inventory = loadInventory()
            let (freshPreflight, freshInventory) = try await (preflight, inventory)
            guard generation == operation else { return }
            guard AccountDeletionRequestGate.allows(
                preflight: freshPreflight,
                inventory: .available(freshInventory),
                reviewedInventoryDigest: reviewedInventoryDigest
            ), unuploadedRidesAcknowledged else {
                state = .ready(freshPreflight, freshInventory)
                return
            }

            let capability: AccountDeletionCapability
            switch capabilityStore.load(owner: owner) {
            case let .unconfirmed(existing):
                guard existing.owner == owner else {
                    state = .storageUnavailable
                    return
                }
                capability = existing.acknowledging(
                    inventory: freshInventory,
                    unuploadedRidesAcknowledged: unuploadedRidesAcknowledged
                )
            case .none:
                capability = try .make(
                    owner: owner,
                    inventory: freshInventory,
                    unuploadedRidesAcknowledged: unuploadedRidesAcknowledged
                )
            case .available:
                await load(owner: owner)
                return
            case .unavailable:
                state = .storageUnavailable
                return
            }
            activeRequestID = capability.requestID
            do {
                try capabilityStore.saveUnconfirmed(capability)
            } catch {
                guard generation == operation else { return }
                state = .storageUnavailable
                return
            }
            try await capabilityDidChange()
            guard generation == operation else { return }
            async let finalPreflight = service.preflight()
            async let finalInventory = loadInventory()
            let (fencedPreflight, fencedInventory) = try await (finalPreflight, finalInventory)
            guard generation == operation else { return }
            guard AccountDeletionRequestGate.allows(
                preflight: fencedPreflight,
                inventory: .available(fencedInventory),
                reviewedInventoryDigest: capability.inventoryDigest
            ) else {
                try capabilityStore.delete(capability)
                try await capabilityDidChange()
                state = .ready(fencedPreflight, fencedInventory)
                return
            }
            // Re-run the exact-owner session/capability boundary immediately
            // before handing DELETE to the network actor. A rider switch
            // during either preflight/inventory await cannot bind B's local
            // capability to A's bearer session.
            guard await validateOwnerBoundaryBeforeDelete(operation: operation) else {
                return
            }
            let status: AccountDeletionStatus
            do {
                status = try await service.create(capability: capability)
            } catch let error as APIError {
                guard generation == operation else { return }
                if await handleCreateConflict(error) { return }
                await probeUnconfirmedStatus(capability: capability, operation: operation)
                return
            } catch {
                guard generation == operation else { return }
                await probeUnconfirmedStatus(capability: capability, operation: operation)
                return
            }
            do {
                try await promoteAndApply(
                    status: status,
                    capability: capability,
                    operation: operation
                )
            } catch {
                guard generation == operation else { return }
                state = .storageUnavailable
            }
        } catch AccountDeletionCapabilityStoreError.unavailable {
            guard generation == operation else { return }
            state = .storageUnavailable
        } catch {
            guard generation == operation else { return }
            state = .statusUnavailable
        }
    }

    /// A lost 202 is recovered with the same durable request/token pair. The
    /// server preflight and current custody inventory are re-read first.
    func reissueDeletion() async {
        guard case let .unconfirmed(capability) = activeCapabilityStorage(),
              capability.owner != nil
        else {
            state = .storageUnavailable
            return
        }
        let operation = UUID()
        generation = operation
        state = .requesting
        do {
            try await capabilityDidChange()
            async let preflight = service.preflight()
            async let inventory = loadInventory()
            let (freshPreflight, freshInventory) = try await (preflight, inventory)
            guard generation == operation else { return }
            guard AccountDeletionRequestGate.allows(
                preflight: freshPreflight,
                inventory: .available(freshInventory),
                reviewedInventoryDigest: capability.inventoryDigest
            ) else {
                state = .ready(freshPreflight, freshInventory)
                return
            }
            guard await validateOwnerBoundaryBeforeDelete(operation: operation) else {
                return
            }
            let status: AccountDeletionStatus
            do {
                status = try await service.create(capability: capability)
            } catch let error as APIError {
                guard generation == operation else { return }
                if await handleCreateConflict(error) { return }
                await probeUnconfirmedStatus(capability: capability, operation: operation)
                return
            } catch {
                guard generation == operation else { return }
                await probeUnconfirmedStatus(capability: capability, operation: operation)
                return
            }
            do {
                try await promoteAndApply(
                    status: status,
                    capability: capability,
                    operation: operation
                )
            } catch {
                guard generation == operation else { return }
                state = .storageUnavailable
            }
        } catch {
            guard generation == operation else { return }
            state = .statusUnavailable
        }
    }

    func refreshStatus() async {
        let capability: AccountDeletionCapability
        let promoteUnconfirmed: Bool
        switch activeCapabilityStorage() {
        case let .available(value):
            capability = value
            promoteUnconfirmed = false
        case let .unconfirmed(value):
            capability = value
            promoteUnconfirmed = true
        case .none, .unavailable:
            state = .storageUnavailable
            return
        }
        if capability.localCleanupCompletedAt != nil {
            let operation = UUID()
            generation = operation
            await presentCompletedLocally(operation: operation)
            return
        }
        if let completion = capability.verifiedCompletion {
            let operation = UUID()
            generation = operation
            await resumeVerifiedCompletion(
                completion,
                capability: capability,
                operation: operation
            )
            return
        }
        let operation = UUID()
        generation = operation
        await readStatus(
            capability: capability,
            operation: operation,
            promoteUnconfirmed: promoteUnconfirmed
        )
    }

    func pollStatus() async {
        guard case let .tracking(previousStatus) = state else { return }
        await refreshStatus()
        if case .statusUnavailable = state {
            pollFailureCount = min(pollFailureCount + 1, 2)
            state = .tracking(previousStatus)
        } else {
            pollFailureCount = 0
        }
    }

    func retry(
        reviewedInventoryDigest: String? = nil,
        unuploadedRidesAcknowledged: Bool = false
    ) async {
        guard case let .available(capability) = activeCapabilityStorage() else {
            state = .storageUnavailable
            return
        }
        let priorStatus: AccountDeletionStatus
        switch state {
        case let .tracking(status), let .retryReview(status, _):
            priorStatus = status
        default:
            return
        }
        guard priorStatus.retryable else { return }
        let operation = UUID()
        generation = operation
        state = .requesting
        do {
            let currentInventory = try await loadInventory()
            var retryCapability = capability
            if currentInventory.digest != capability.inventoryDigest {
                guard unuploadedRidesAcknowledged,
                      reviewedInventoryDigest == currentInventory.digest
                else {
                    state = .retryReview(priorStatus, currentInventory)
                    return
                }
                retryCapability = capability.acknowledging(
                    inventory: currentInventory,
                    unuploadedRidesAcknowledged: true
                )
                try capabilityStore.save(retryCapability)
            }
            try await capabilityDidChange()
            let fencedInventory = try await loadInventory()
            guard fencedInventory.digest == retryCapability.inventoryDigest else {
                state = .retryReview(priorStatus, fencedInventory)
                return
            }
            let status = try await service.retry(capability: retryCapability)
            await apply(
                status: status,
                capability: retryCapability,
                operation: operation
            )
        } catch let error as APIError {
            guard generation == operation else { return }
            if handleRetryConflict(error) { return }
            state = .statusUnavailable
        } catch {
            guard generation == operation else { return }
            state = .statusUnavailable
        }
    }

    /// Server completion is already authoritative, but a ride discovered
    /// afterward is new destructive scope. Persist a fresh exact inventory
    /// acknowledgement before local cleanup; never send a false server retry.
    func acknowledgeCompletedInventory(
        reviewedInventoryDigest: String?,
        unuploadedRidesAcknowledged: Bool
    ) async {
        guard case let .retryReview(status, inventory) = state,
              status.status == .completed,
              unuploadedRidesAcknowledged,
              reviewedInventoryDigest == inventory.digest,
              case let .available(capability) = activeCapabilityStorage(),
              capability.verifiedCompletion == status,
              let updated = capability.acknowledgingAdditionalCleanupInventory(inventory)
        else { return }
        let operation = UUID()
        generation = operation
        state = .clearingLocalData
        do {
            try capabilityStore.save(updated)
            try await capabilityDidChange()
            guard generation == operation else { return }
            await resumeVerifiedCompletion(
                status,
                capability: updated,
                operation: operation
            )
        } catch {
            guard generation == operation else { return }
            state = .localCleanupFailed
        }
    }

    func acknowledgeCompletion() async {
        switch state {
        case .completed, .completedLocally:
            break
        default:
            return
        }
        do {
            // Reconcile any simultaneous deletion-401 journal while the
            // completed capability is still durable. Only then may Done
            // remove the last token-authorized lifecycle record.
            try await capabilityDidChange()
            guard let capability = activeCapabilityStorage().capability else {
                throw AccountDeletionCapabilityStoreError.invalid
            }
            try capabilityStore.delete(capability)
            try await capabilityDidChange()
            state = .discarded
        } catch {
            state = .storageUnavailable
        }
    }

    func discardSavedStatus() async {
        let storage = activeCapabilityStorage()
        let capabilityRequiringReplacementFence: AccountDeletionCapability?
        switch storage {
        case let .unconfirmed(capability):
            capabilityRequiringReplacementFence = capability
        case let .available(capability):
            capabilityRequiringReplacementFence = capability
        case .none, .unavailable:
            capabilityRequiringReplacementFence = nil
        }
        guard canDiscardSavedStatus else { return }
        do {
            if let capabilityRequiringReplacementFence {
                // A status 404 can race the original DELETE commit. Persist
                // the process-independent fence for provisional and accepted
                // pairs alike before either bearer is removed.
                try await acceptedStatusDiscarded(
                    capabilityRequiringReplacementFence.owner
                )
            }
            guard let capabilityRequiringReplacementFence else {
                throw AccountDeletionCapabilityStoreError.invalid
            }
            try capabilityStore.delete(capabilityRequiringReplacementFence)
            try await capabilityDidChange()
            state = .discarded
        } catch {
            state = .storageUnavailable
        }
    }

    private func loadReady(operation: UUID) async {
        do {
            async let preflight = service.preflight()
            async let inventory = loadInventory()
            let values = try await (preflight, inventory)
            guard generation == operation else { return }
            state = .ready(values.0, values.1)
        } catch {
            guard generation == operation else { return }
            state = .statusUnavailable
        }
    }

    /// The final local identity check is adjacent to DELETE. Earlier writer
    /// fencing is necessary but cannot authorize a request after an owner
    /// switch during the server preflight or inventory reads.
    private func validateOwnerBoundaryBeforeDelete(operation: UUID) async -> Bool {
        do {
            try await capabilityDidChange()
            return generation == operation
        } catch {
            guard generation == operation else { return false }
            state = .ownerMismatch
            return false
        }
    }

    private func activeCapabilityStorage() -> AccountDeletionCapabilityStorageState {
        guard let activeRequestID else { return .none }
        return capabilityStore.load(requestID: activeRequestID)
    }

    private func capabilityBelongsTo(
        owner: RecordingOwner?,
        capability: AccountDeletionCapability
    ) -> Bool {
        guard let owner, let capabilityOwner = capability.owner else { return true }
        return owner == capabilityOwner
    }

    private func presentCompletedLocally(operation: UUID) async {
        do {
            try await capabilityDidChange()
            guard generation == operation else { return }
            state = .completedLocally
        } catch {
            guard generation == operation else { return }
            state = .localCleanupFailed
        }
    }

    private func readStatus(
        capability: AccountDeletionCapability,
        operation: UUID,
        promoteUnconfirmed: Bool
    ) async {
        do {
            let status = try await service.status(capability: capability)
            if promoteUnconfirmed {
                try await promoteAndApply(
                    status: status,
                    capability: capability,
                    operation: operation
                )
            } else {
                await apply(status: status, capability: capability, operation: operation)
            }
        } catch let error as APIError {
            guard generation == operation else { return }
            if case let .http(status, _, _) = error, status == 404 {
                state = .requestNotFound
            } else {
                state = .statusUnavailable
            }
        } catch {
            guard generation == operation else { return }
            state = .statusUnavailable
        }
    }

    private func promoteAndApply(
        status: AccountDeletionStatus,
        capability: AccountDeletionCapability,
        operation: UUID
    ) async throws {
        guard status.contractVersion == AccountDeletionContract.version,
              status.requestID.caseInsensitiveCompare(capability.requestID) == .orderedSame
        else {
            state = .statusUnavailable
            return
        }
        // Revalidate/fence the exact owner while the pair is still
        // provisional. A rider switch during the network request must never
        // turn another owner's pair into an app-wide accepted takeover.
        try await capabilityDidChange()
        guard generation == operation else { return }
        try capabilityStore.save(capability)
        try await capabilityDidChange()
        guard generation == operation else { return }
        await apply(status: status, capability: capability, operation: operation)
    }

    private func probeUnconfirmedStatus(
        capability: AccountDeletionCapability,
        operation: UUID
    ) async {
        do {
            let status = try await service.status(capability: capability)
            try await promoteAndApply(
                status: status,
                capability: capability,
                operation: operation
            )
        } catch let error as APIError {
            guard generation == operation else { return }
            if case let .http(status, _, _) = error, status == 404 {
                state = .requestNotFound
            } else {
                state = .statusUnavailable
            }
        } catch {
            guard generation == operation else { return }
            state = .statusUnavailable
        }
    }

    private func handleCreateConflict(_ error: APIError) async -> Bool {
        guard case let .http(status, rawCode, _) = error,
              status == 409,
              let rawCode,
              let code = AccountDeletionConflictCode(rawValue: rawCode),
              [.requestAlreadyActive, .accountUnavailable, .requestIDConflict].contains(code)
        else { return false }
        do {
            guard case let .unconfirmed(capability) = activeCapabilityStorage() else {
                state = .storageUnavailable
                return true
            }
            // A 409 does not prove this DELETE missed the server. Replace the
            // provisional bearer with a process-independent lifecycle fence
            // before removing it, so cached writers can never reopen.
            try await acceptedStatusDiscarded(capability.owner)
            try capabilityStore.delete(capability)
            try await capabilityDidChange()
            state = .supportRequired(code)
        } catch {
            state = .storageUnavailable
        }
        return true
    }

    private func handleRetryConflict(_ error: APIError) -> Bool {
        guard case let .http(status, rawCode, _) = error,
              status == 409,
              let rawCode,
              let code = AccountDeletionConflictCode(rawValue: rawCode),
              code == .retryUnavailable
                || code == .retryRequiresSupport
                || code == .accountUnavailable
        else { return false }
        state = .supportRequired(code)
        return true
    }

    private func apply(
        status: AccountDeletionStatus,
        capability: AccountDeletionCapability,
        operation: UUID
    ) async {
        guard generation == operation,
              status.contractVersion == AccountDeletionContract.version,
              status.requestID.caseInsensitiveCompare(capability.requestID) == .orderedSame
        else {
            state = .statusUnavailable
            return
        }
        guard status.isVerifiedCompletion(for: capability) else {
            state = status.status == .completed ? .statusUnavailable : .tracking(status)
            return
        }
        if capability.localCleanupCompletedAt != nil {
            state = .completedLocally
            return
        }
        let verified: AccountDeletionCapability
        do {
            guard let marked = capability.markingServerCompletionVerified(status) else {
                state = .statusUnavailable
                return
            }
            verified = marked
            // The verified-completion journal is durable before any local
            // source byte is removed. Relaunch can therefore finish cleanup
            // without another network read.
            try capabilityStore.save(verified)
            try await capabilityDidChange()
        } catch {
            guard generation == operation else { return }
            state = .localCleanupFailed
            return
        }
        await resumeVerifiedCompletion(status, capability: verified, operation: operation)
    }

    private func resumeVerifiedCompletion(
        _ status: AccountDeletionStatus,
        capability: AccountDeletionCapability,
        operation: UUID
    ) async {
        guard capability.verifiedCompletion == status,
              status.isVerifiedCompletion(for: capability),
              !isCleaningLocalData
        else {
            if isCleaningLocalData { return }
            state = .statusUnavailable
            return
        }
        isCleaningLocalData = true
        state = .clearingLocalData
        defer { isCleaningLocalData = false }
        do {
            let fencedInventory = try await loadInventory()
            guard capability.acknowledgesForCleanup(fencedInventory) else {
                state = .retryReview(status, fencedInventory)
                return
            }
            try await localCleanup(capability, status)
            guard let cleanupOwner = capability.owner else {
                state = .localCleanupFailed
                return
            }
            // Reconcile this exact owner's auth journal while identity is
            // still available. Once the completion capability is scrubbed,
            // no different-owner record may be guessed or removed.
            try await localCleanupDidComplete(cleanupOwner)
            guard let cleaned = capability.markingLocalCleanupCompleted() else {
                state = .localCleanupFailed
                return
            }
            // Never let a concurrent refresh generation skip this write after
            // destructive cleanup has succeeded.
            try capabilityStore.save(cleaned)
            try await capabilityDidChange()
            generation = operation
            state = .completed(status)
        } catch {
            state = .localCleanupFailed
        }
    }
}
