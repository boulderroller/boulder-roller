import CryptoKit
import Foundation

/// Session operations policy (bead `boulderroller-v2-f4acp.2.9`).
///
/// The one law here: **a stored session dies only on the server's word.**
/// Network weather, server incidents, and device-clock drift are transient —
/// they must never delete the refresh token or silently land the rider on
/// onboarding. The backend's refresh endpoint speaks in exact codes
/// (`refresh_expired`, `refresh_revoked`, …); those and only those end a
/// session, and each ends it with a truthful notice.

// MARK: - Refresh outcome classification

/// What one `/auth/refresh` attempt actually established.
enum SessionRefreshOutcome: Equatable, Sendable {
    /// New tokens adopted.
    case refreshed
    /// The server definitively rejected this session. The stored refresh
    /// token is dead and must be cleared; the rider re-authenticates.
    case rejected(SessionEndReason)
    /// The account lifecycle, not token validity, ended authentication.
    /// This routes to deletion recovery/support while preserving custody.
    case accountDeletion(AccountDeletionSessionState)
    /// Nothing was established: offline, timeout, 5xx, rate-limit, or any
    /// other failure that is not the auth server rejecting the token.
    /// The stored session MUST survive this.
    case transient
}

enum AccountDeletionSessionState: String, Codable, Equatable, Sendable {
    case pending = "account_deletion_pending"
    case deleted = "account_deleted"
    case identityUnavailable = "account_identity_unavailable"
}

/// Non-authorizing correlation carried from the exact server refusal into
/// AppSession's richer owner journal. APIClient persists its recovery ID
/// before exposing the refusal, closing the kill gap before async delivery.
struct AccountDeletionRefusalContext: Equatable, Sendable {
    let recoveryID: String
    /// Exact authenticated identity captured with the rejected bearer. A
    /// later session must never be inferred as the owner of this refusal.
    let attemptedOwner: RecordingOwner?
    /// Pre-auth verification can name only the wallet it attempted.
    let attemptedWallet: String?

    init(
        recoveryID: String,
        attemptedOwner: RecordingOwner? = nil,
        attemptedWallet: String? = nil
    ) {
        self.recoveryID = recoveryID
        self.attemptedOwner = attemptedOwner
        self.attemptedWallet = attemptedWallet
    }
}

struct AccountDeletionSessionRecord: Codable, Equatable, Sendable {
    /// Opaque, non-personal slot identity. It survives owner scrubbing so two
    /// completed recovery rooms can coexist and Done clears only the room the
    /// rider actually acknowledged.
    let recoveryID: String
    let state: AccountDeletionSessionState
    let owner: RecordingOwner?
    /// True only when the rider explicitly removed an accepted bearer status
    /// capability. The durable fence remains while support or a fresh server
    /// sign-in establishes what account work is allowed next.
    let savedStatusRemoved: Bool
    /// Positive local phase for a deletion completed elsewhere. The owner is
    /// removed before this marker is persisted; Done may then clear it without
    /// another server or custody read.
    let localCleanupCompletedAt: Date?

    init(
        recoveryID: String = UUID().uuidString.lowercased(),
        state: AccountDeletionSessionState,
        owner: RecordingOwner?,
        savedStatusRemoved: Bool = false,
        localCleanupCompletedAt: Date? = nil
    ) {
        self.recoveryID = recoveryID
        self.state = state
        self.owner = owner
        self.savedStatusRemoved = savedStatusRemoved
        self.localCleanupCompletedAt = localCleanupCompletedAt
    }

    private enum CodingKeys: String, CodingKey {
        case recoveryID
        case state
        case owner
        case savedStatusRemoved
        case localCleanupCompletedAt
    }

    init(from decoder: Decoder) throws {
        let values = try decoder.container(keyedBy: CodingKeys.self)
        state = try values.decode(AccountDeletionSessionState.self, forKey: .state)
        owner = try values.decodeIfPresent(RecordingOwner.self, forKey: .owner)
        savedStatusRemoved = try values.decodeIfPresent(
            Bool.self,
            forKey: .savedStatusRemoved
        ) ?? false
        localCleanupCompletedAt = try values.decodeIfPresent(
            Date.self,
            forKey: .localCleanupCompletedAt
        )
        recoveryID = try values.decodeIfPresent(String.self, forKey: .recoveryID)
            ?? Self.legacyRecoveryID(
                state: state,
                owner: owner,
                savedStatusRemoved: savedStatusRemoved,
                localCleanupCompletedAt: localCleanupCompletedAt
            )
    }

    private static func legacyRecoveryID(
        state: AccountDeletionSessionState,
        owner: RecordingOwner?,
        savedStatusRemoved: Bool,
        localCleanupCompletedAt: Date?
    ) -> String {
        let source = [
            state.rawValue,
            owner?.id ?? "",
            owner?.wallet ?? "",
            savedStatusRemoved ? "1" : "0",
            localCleanupCompletedAt.map { String($0.timeIntervalSince1970) } ?? "",
        ].joined(separator: "|")
        let digest = SHA256.hash(data: Data(source.utf8))
        return "legacy-" + digest.prefix(16).map {
            String(format: "%02x", $0)
        }.joined()
    }

    static func == (
        lhs: AccountDeletionSessionRecord,
        rhs: AccountDeletionSessionRecord
    ) -> Bool {
        guard lhs.state == rhs.state,
              lhs.owner == rhs.owner,
              lhs.savedStatusRemoved == rhs.savedStatusRemoved,
              lhs.localCleanupCompletedAt == rhs.localCleanupCompletedAt
        else { return false }
        // An owner is already the exact durable slot while it exists. Once
        // privacy cleanup removes it, only the opaque recovery ID can keep
        // multiple anonymous completion rooms distinct.
        if lhs.owner == nil, rhs.owner == nil {
            return lhs.recoveryID == rhs.recoveryID
        }
        return true
    }
}

/// Required journal persistence can fail while this process still has a live
/// account runtime. This exact-owner volatile fence closes that in-process
/// writer window without pretending the lifecycle state survived a restart.
enum AccountDeletionProcessFence {
    private static let lock = NSLock()
    private static var stored: [AccountDeletionSessionRecord] = []

    static func record(_ record: AccountDeletionSessionRecord) {
        lock.withLock {
            stored.removeAll {
                $0.recoveryID == record.recoveryID
                    || ($0.owner != nil && $0.owner == record.owner)
            }
            stored.append(record)
        }
    }

    static func clear(_ record: AccountDeletionSessionRecord) {
        lock.withLock { stored.removeAll { $0.recoveryID == record.recoveryID } }
    }

    static func records() -> [AccountDeletionSessionRecord] {
        lock.withLock { stored }
    }

    static func clearAll() {
        lock.withLock { stored.removeAll() }
    }
}

/// Crash-safe, non-personal witness used only when the richer deletion
/// journal cannot be made durable. It never authorizes deletion or cleanup;
/// it only prevents a cold relaunch from treating unknown lifecycle state as
/// no lifecycle state. A later successful exact journal write removes it.
enum AccountDeletionEmergencyFenceStore {
    private static let key = "br.account_deletion.emergency_fence.v1"
    private static let lock = NSLock()
    private static let malformedWitnessID = "deletion-emergency-unavailable-v1"

    private static func decodedRecoveryIDs() -> [String] {
        guard let storedValue = UserDefaults.standard.object(forKey: key) else {
            return []
        }
        guard let data = storedValue as? Data,
              let values = try? JSONDecoder().decode([String].self, from: data),
              !values.isEmpty,
              values.allSatisfy({ !$0.isEmpty }),
              Set(values).count == values.count
        else {
            // Present-but-malformed is still a durable unknown-owner fence.
            return [malformedWitnessID]
        }
        return values
    }

    private static func persist(_ recoveryIDs: [String]) throws {
        if recoveryIDs.isEmpty {
            UserDefaults.standard.removeObject(forKey: key)
            return
        }
        guard let data = try? JSONEncoder().encode(recoveryIDs) else {
            throw AccountDeletionCapabilityStoreError.invalid
        }
        UserDefaults.standard.set(data, forKey: key)
    }

    static var records: [AccountDeletionSessionRecord] {
        lock.withLock {
            decodedRecoveryIDs().map {
                AccountDeletionSessionRecord(
                    recoveryID: $0,
                    state: .identityUnavailable,
                    owner: nil
                )
            }
        }
    }

    static var isArmed: Bool { !records.isEmpty }

    static func armRequired(recoveryID: String) throws {
        guard !recoveryID.isEmpty else {
            throw AccountDeletionCapabilityStoreError.invalid
        }
        try lock.withLock {
            var recoveryIDs = decodedRecoveryIDs()
            if !recoveryIDs.contains(recoveryID) { recoveryIDs.append(recoveryID) }
            try persist(recoveryIDs)
            guard UserDefaults.standard.synchronize(),
                  decodedRecoveryIDs().contains(recoveryID)
            else { throw AccountDeletionCapabilityStoreError.unavailable }
        }
    }

    static func clearRequired(recoveryID: String) throws {
        guard !recoveryID.isEmpty else {
            throw AccountDeletionCapabilityStoreError.invalid
        }
        try lock.withLock {
            var recoveryIDs = decodedRecoveryIDs()
            recoveryIDs.removeAll { $0 == recoveryID }
            try persist(recoveryIDs)
            guard UserDefaults.standard.synchronize(),
                  !decodedRecoveryIDs().contains(recoveryID)
            else { throw AccountDeletionCapabilityStoreError.unavailable }
        }
    }

    static func clear() {
        lock.withLock { UserDefaults.standard.removeObject(forKey: key) }
    }
}

enum AccountDeletionSessionRecordStore {
    private static let key = "br.account_deletion.session_state.v1"
    private static let lock = NSLock()

    /// Present-but-unreadable journal bytes are deletion state, not absence.
    /// This ownerless witness keeps every account writer closed across a cold
    /// relaunch and routes the rider to support instead of guessing which
    /// account an undecodable record belonged to.
    static let unavailableJournalRecord = AccountDeletionSessionRecord(
        recoveryID: "deletion-journal-unavailable-v1",
        state: .identityUnavailable,
        owner: nil
    )

    private static func decodedStoredRecords() -> [AccountDeletionSessionRecord] {
        guard let storedValue = UserDefaults.standard.object(forKey: key) else {
            return []
        }
        guard let data = storedValue as? Data else {
            return [unavailableJournalRecord]
        }
        if let records = try? JSONDecoder().decode(
            [AccountDeletionSessionRecord].self,
            from: data
        ) {
            guard !records.isEmpty,
                  records.allSatisfy({ !$0.recoveryID.isEmpty }),
                  Set(records.map(\.recoveryID)).count == records.count
            else { return [unavailableJournalRecord] }
            return records
        }
        guard let record = try? JSONDecoder().decode(
            AccountDeletionSessionRecord.self,
            from: data
        ), !record.recoveryID.isEmpty else {
            return [unavailableJournalRecord]
        }
        return [record]
    }

    private static func decodedRecords() -> [AccountDeletionSessionRecord] {
        let stored = decodedStoredRecords()
        return AccountDeletionEmergencyFenceStore.records.filter {
            emergency in !stored.contains {
                $0.recoveryID == emergency.recoveryID
            }
        } + stored
    }

    private static func occupiesSameOwnerSlot(
        _ lhs: AccountDeletionSessionRecord,
        _ rhs: AccountDeletionSessionRecord
    ) -> Bool {
        if lhs.recoveryID == rhs.recoveryID { return true }
        switch (lhs.owner, rhs.owner) {
        case let (.some(lhsOwner), .some(rhsOwner)):
            return lhsOwner == rhsOwner
        case (.none, .none):
            return false
        case (.some, .none), (.none, .some):
            return false
        }
    }

    private static func recordsReplacingOwnerSlot(
        with record: AccountDeletionSessionRecord
    ) -> [AccountDeletionSessionRecord] {
        decodedStoredRecords().filter { !occupiesSameOwnerSlot($0, record) } + [record]
    }

    private static func persist(_ records: [AccountDeletionSessionRecord]) throws {
        if records.isEmpty {
            UserDefaults.standard.removeObject(forKey: key)
            return
        }
        guard let data = try? JSONEncoder().encode(records) else {
            throw AccountDeletionCapabilityStoreError.invalid
        }
        UserDefaults.standard.set(data, forKey: key)
    }

    static func record(_ record: AccountDeletionSessionRecord) {
        lock.withLock {
            try? persist(recordsReplacingOwnerSlot(with: record))
        }
    }

    static func recordRequired(_ record: AccountDeletionSessionRecord) throws {
        try lock.withLock {
            try persist(recordsReplacingOwnerSlot(with: record))
            guard UserDefaults.standard.synchronize(), decodedRecords().contains(record) else {
                throw AccountDeletionCapabilityStoreError.unavailable
            }
        }
    }

    static func records() -> [AccountDeletionSessionRecord] {
        lock.withLock { decodedRecords() }
    }

    static func pending() -> AccountDeletionSessionRecord? {
        records().last
    }

    static func pending(owner: RecordingOwner) -> AccountDeletionSessionRecord? {
        records().last { $0.owner == owner }
    }

    static func contains(_ record: AccountDeletionSessionRecord) -> Bool {
        records().contains(record)
    }

    static func clear() {
        lock.withLock { UserDefaults.standard.removeObject(forKey: key) }
        AccountDeletionEmergencyFenceStore.clear()
        AccountDeletionProcessFence.clearAll()
    }

    static func clearRequired(_ record: AccountDeletionSessionRecord) throws {
        try lock.withLock {
            var records = decodedStoredRecords()
            guard records.contains(record) else {
                throw AccountDeletionLocalCleanupError.verificationFailed
            }
            records.removeAll { $0 == record }
            try persist(records)
            guard UserDefaults.standard.synchronize(), !decodedRecords().contains(record) else {
                throw AccountDeletionLocalCleanupError.verificationFailed
            }
        }
    }

    /// Atomically privacy-scrub one exact-owner recovery row into the local
    /// completion marker. A crash before the write leaves the owner row for an
    /// idempotent cleanup retry; a crash after it leaves the completed marker.
    /// Other owners' recovery truth is never part of this transition.
    static func replaceRequired(
        _ record: AccountDeletionSessionRecord,
        with replacement: AccountDeletionSessionRecord
    ) throws {
        try lock.withLock {
            let original = decodedStoredRecords()
            guard original.contains(record) else {
                throw AccountDeletionLocalCleanupError.verificationFailed
            }
            var updated = original.filter { $0 != record }
            updated.removeAll { $0.recoveryID == replacement.recoveryID }
            updated.append(replacement)
            do {
                try persist(updated)
                guard UserDefaults.standard.synchronize(), decodedStoredRecords() == updated else {
                    throw AccountDeletionCapabilityStoreError.unavailable
                }
            } catch {
                // Best-effort rollback keeps the pre-cleanup owner fence when
                // UserDefaults reports that the replacement was not durable.
                try? persist(original)
                _ = UserDefaults.standard.synchronize()
                throw error
            }
        }
    }
}

protocol AccountDeletionSessionRecordStoring: Sendable {
    func loadAll() -> [AccountDeletionSessionRecord]
    func record(_ record: AccountDeletionSessionRecord)
    func recordRequired(_ record: AccountDeletionSessionRecord) throws
    func clearRequired(_ record: AccountDeletionSessionRecord) throws
    func replaceRequired(
        _ record: AccountDeletionSessionRecord,
        with replacement: AccountDeletionSessionRecord
    ) throws
}

extension AccountDeletionSessionRecordStoring {
    func load() -> AccountDeletionSessionRecord? { loadAll().last }

    func load(owner: RecordingOwner) -> AccountDeletionSessionRecord? {
        loadAll().last { $0.owner == owner }
    }

    func contains(_ record: AccountDeletionSessionRecord) -> Bool {
        loadAll().contains(record)
    }
}

struct DurableAccountDeletionSessionRecordStore: AccountDeletionSessionRecordStoring {
    func loadAll() -> [AccountDeletionSessionRecord] {
        AccountDeletionSessionRecordStore.records()
    }

    func record(_ record: AccountDeletionSessionRecord) {
        AccountDeletionSessionRecordStore.record(record)
    }

    func recordRequired(_ record: AccountDeletionSessionRecord) throws {
        try AccountDeletionSessionRecordStore.recordRequired(record)
    }

    func clearRequired(_ record: AccountDeletionSessionRecord) throws {
        try AccountDeletionSessionRecordStore.clearRequired(record)
    }

    func replaceRequired(
        _ record: AccountDeletionSessionRecord,
        with replacement: AccountDeletionSessionRecord
    ) throws {
        try AccountDeletionSessionRecordStore.replaceRequired(record, with: replacement)
    }
}

/// Process-independent writer gate. A deletion-specific auth refusal can be
/// the only durable evidence on this device when the request began elsewhere,
/// so every background writer checks it alongside the bearer capability.
enum AccountDeletionLocalFence {
    static var permitsAccountWork: Bool {
        permitsAccountWork(owner: nil)
    }

    /// Process-wide caches and routers have no AppSession reference, but the
    /// durable cached rider is the active account identity. Bind their writes
    /// to that owner so rider A's retained fence cannot disable rider B.
    static var permitsCachedOwnerAccountWork: Bool {
        let owner = CachedRiderStore.load().map { RecordingOwner(user: $0) }
        return permitsCachedOwnerAccountWork(
            cachedOwner: owner,
            sessionRecords: allSessionRecords(),
            capabilityStates: KeychainAccountDeletionCapabilityStore().loadAll()
        )
    }

    static func permitsCachedOwnerAccountWork(
        cachedOwner: RecordingOwner?,
        sessionRecords: [AccountDeletionSessionRecord],
        capabilityState: AccountDeletionCapabilityStorageState
    ) -> Bool {
        permitsCachedOwnerAccountWork(
            cachedOwner: cachedOwner,
            sessionRecords: sessionRecords,
            capabilityStates: [capabilityState]
        )
    }

    static func permitsCachedOwnerAccountWork(
        cachedOwner: RecordingOwner?,
        sessionRecords: [AccountDeletionSessionRecord],
        capabilityStates: [AccountDeletionCapabilityStorageState]
    ) -> Bool {
        permitsAccountWork(
            owner: cachedOwner,
            sessionRecords: sessionRecords,
            capabilityStates: capabilityStates
        )
    }

    static func permitsAccountWork(owner: RecordingOwner?) -> Bool {
        permitsAccountWork(
            owner: owner,
            sessionRecords: allSessionRecords(),
            capabilityStates: KeychainAccountDeletionCapabilityStore().loadAll()
        )
    }

    private static func allSessionRecords() -> [AccountDeletionSessionRecord] {
        let durable = AccountDeletionSessionRecordStore.records()
        return durable + AccountDeletionProcessFence.records().filter {
            !durable.contains($0)
        }
    }

    static func permitsAccountWork(
        owner: RecordingOwner?,
        sessionRecord: AccountDeletionSessionRecord?,
        capabilityState: AccountDeletionCapabilityStorageState
    ) -> Bool {
        permitsAccountWork(
            owner: owner,
            sessionRecords: sessionRecord.map { [$0] } ?? [],
            capabilityStates: [capabilityState]
        )
    }

    static func permitsAccountWork(
        owner: RecordingOwner?,
        sessionRecords: [AccountDeletionSessionRecord],
        capabilityState: AccountDeletionCapabilityStorageState
    ) -> Bool {
        permitsAccountWork(
            owner: owner,
            sessionRecords: sessionRecords,
            capabilityStates: [capabilityState]
        )
    }

    static func permitsAccountWork(
        owner: RecordingOwner?,
        sessionRecords: [AccountDeletionSessionRecord],
        capabilityStates: [AccountDeletionCapabilityStorageState]
    ) -> Bool {
        if !sessionRecords.isEmpty {
            guard let owner else { return false }
            guard !sessionRecords.contains(where: { record in
                record.owner.map { $0 == owner } ?? true
            }) else { return false }
        }
        for capabilityState in capabilityStates {
            switch capabilityState {
            case .none:
                continue
            case .unavailable:
                return false
            case let .available(capability), let .unconfirmed(capability):
                guard let owner,
                      let fencedOwner = capability.owner,
                      owner != fencedOwner
                else { return false }
            }
        }
        return true
    }
}

/// Why a session ended — drives the truthful line on onboarding.
/// Persisted as a raw value; never contains token material.
enum SessionEndReason: String, Equatable, Sendable {
    /// The refresh token aged out (long offline) or was already rotated
    /// past recovery (process killed mid-rotation before the new token
    /// persisted).
    case expired
    /// The server revoked this session (sign-out elsewhere, reuse
    /// detection, operator action).
    case revokedByServer
    /// The rider signed out on this device. No notice is shown.
    case riderSignedOut

    /// Truthful system string for onboarding. Strava-shaped: terse,
    /// factual, no apology, no mechanism.
    var onboardingNotice: String? {
        switch self {
        case .expired: return "Your session expired. Sign in again."
        case .revokedByServer: return "You were signed out. Sign in again."
        case .riderSignedOut: return nil
        }
    }
}

enum SessionRefreshClassifier {
    /// Backend refresh error codes that definitively end the stored session
    /// (`backend/app/routes/auth.py: refresh_tokens`). Anything outside this
    /// exact vocabulary is treated as transient — fail open toward keeping
    /// the rider's session, closed toward deleting it.
    private static let expiredCodes: Set<String> = [
        "refresh_expired",
        // Rotated past recovery: the newer token was lost with the killed
        // process. Nothing stored can revive this session; honest expiry.
        "refresh_rotated",
    ]
    private static let revokedCodes: Set<String> = [
        "refresh_revoked",
        "refresh_reuse_detected",
        "refresh_unknown",
        "refresh_mismatch",
        "refresh_invalid",
        "refresh_missing",
    ]

    /// Classify one failed refresh attempt.
    static func classify(_ error: Error) -> SessionRefreshOutcome {
        guard case let APIError.http(status, code, _) = error else {
            // URLError (offline, DNS, timeout), decoding surprises, storage
            // failures: transient by law.
            return .transient
        }
        switch status {
        case 401, 403, 409:
            guard let code else {
                // An auth-shaped status with no recognizable code: the auth
                // route always names its rejections, so an anonymous 401 is
                // most likely an intermediary (proxy, gateway). Transient.
                return .transient
            }
            if let deletion = AccountDeletionSessionState(rawValue: code) {
                return .accountDeletion(deletion)
            }
            if expiredCodes.contains(code) { return .rejected(.expired) }
            if revokedCodes.contains(code) { return .rejected(.revokedByServer) }
            return .transient
        default:
            // 429, 5xx, anything else: the server did not judge the token.
            return .transient
        }
    }
}

// MARK: - Clock-skew tolerant expiry reads

/// Client-side view of an access token's lifetime that never trusts the
/// device wall clock as an authority.
///
/// The server's `access_expires_at` is server wall time; the device clock
/// may be minutes off (or jump entirely). Two rules:
/// 1. Lifetime is measured from the *receipt instant* on a monotonic-ish
///    basis (two `Date()` reads subtracted — immune to absolute skew,
///    exposed only to mid-flight clock *jumps*, which rule 2 absorbs).
/// 2. Local expiry belief is an optimization only. It may trigger an early
///    proactive refresh; it must NEVER veto a request or kill a session —
///    the server's 401 remains the sole authority.
struct SessionClockPolicy: Sendable {
    /// How much disagreement we absorb before the local belief is
    /// considered meaningless (rebooted clock, timezone jump mid-flight).
    let skewTolerance: TimeInterval
    /// Refresh this close to believed expiry so requests ride fresh tokens.
    let proactiveRefreshWindow: TimeInterval

    init(skewTolerance: TimeInterval = 300, proactiveRefreshWindow: TimeInterval = 60) {
        self.skewTolerance = skewTolerance
        self.proactiveRefreshWindow = proactiveRefreshWindow
    }

    /// One adopted access token, anchored to its receipt instant.
    struct TokenLifetime: Equatable, Sendable {
        /// Server-declared expiry (server wall clock).
        let expiresAt: Date
        /// Local instant the token was adopted.
        let receivedAt: Date

        /// Server-declared remaining lifetime at receipt. Skew-free: both
        /// operands are the server's own clock domain, except `receivedAt`
        /// substitutes for the unavailable server issue instant (bounded by
        /// one network round trip, far inside the tolerance).
        var declaredLifetime: TimeInterval { expiresAt.timeIntervalSince(receivedAt) }
    }

    /// Should a request proactively refresh before using the stored token?
    /// `nil` lifetime (server omitted expiry) → never proactive; the 401
    /// path owns correctness.
    func shouldProactivelyRefresh(_ lifetime: TokenLifetime?, now: Date) -> Bool {
        guard let lifetime else { return false }
        let declared = lifetime.declaredLifetime
        guard declared > 0 else {
            // Server says the token was born dead relative to our receipt
            // clock — that is skew, not truth. Don't churn refreshes; let
            // the request run and the 401 path decide.
            return false
        }
        let elapsed = now.timeIntervalSince(lifetime.receivedAt)
        if elapsed < 0 {
            // Wall clock jumped backwards mid-session. Elapsed time is
            // unknowable; treat the belief as meaningless, not expired.
            return false
        }
        return elapsed >= max(0, declared - proactiveRefreshWindow)
    }

    /// Is a *stored* (relaunch) session worth attempting to resume?
    /// Always yes while a refresh token exists: refresh expiry is the
    /// server's call. This exists as an explicit, tested statement that no
    /// local clock comparison may gate resume.
    func shouldAttemptResume(hasStoredRefreshToken: Bool) -> Bool {
        hasStoredRefreshToken
    }
}

// MARK: - Session end notice persistence

/// Why the last session ended, persisted so the truthful line survives the
/// relaunch that shows onboarding. Raw reason string only — never tokens.
enum SessionEndReasonStore {
    private static let key = "br.session_end_reason"
    private static var defaults: UserDefaults { .standard }

    static func record(_ reason: SessionEndReason) {
        if reason == .riderSignedOut {
            clear()
        } else {
            defaults.set(reason.rawValue, forKey: key)
        }
    }

    static func pending() -> SessionEndReason? {
        defaults.string(forKey: key).flatMap(SessionEndReason.init(rawValue:))
    }

    static func clear() {
        defaults.removeObject(forKey: key)
    }

    static func clearRequired() throws {
        defaults.removeObject(forKey: key)
        guard defaults.object(forKey: key) == nil else {
            throw AccountDeletionLocalCleanupError.verificationFailed
        }
    }
}
