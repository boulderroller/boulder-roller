import Foundation
import Observation
import UIKit
import UserNotifications

protocol AppSessionRideUploadRuntime: Sendable {
    func activate(user: User?) async
    func reconcileAll(owner: RecordingOwner) async
    func pendingPrivacyReview(
        owner: RecordingOwner,
        excluding excludedIDs: Set<String>
    ) async -> RideUploadJob?
    func approvePublication(
        jobID: String,
        owner: RecordingOwner,
        settings: RidePublicationSettings,
        draft: RidePostRideDraft,
        photoBytes: [String: Data]
    ) async throws
    func claimNextReveal(owner: RecordingOwner) async -> PendingRideReveal?
    func acknowledgeReveal(
        _ pending: PendingRideReveal,
        owner: RecordingOwner
    ) async -> Bool
    func accountDeletionRecords(owner: RecordingOwner) async throws -> [AccountDeletionUploadRecord]
    func freezeForAccountDeletion(owner: RecordingOwner) async throws
    func purgeAccount(owner: RecordingOwner) async throws
}

extension RideUploadRuntime: AppSessionRideUploadRuntime {}

extension AppSessionRideUploadRuntime {
    func pendingPrivacyReview(
        owner: RecordingOwner,
        excluding excludedIDs: Set<String>
    ) async -> RideUploadJob? { nil }

    func approvePublication(
        jobID: String,
        owner: RecordingOwner,
        settings: RidePublicationSettings,
        draft: RidePostRideDraft,
        photoBytes: [String: Data]
    ) async throws {
        throw RideUploadStoreError.missingSource
    }

    func accountDeletionRecords(owner: RecordingOwner) async throws -> [AccountDeletionUploadRecord] {
        throw RideUploadStoreError.invalidOwner
    }

    func freezeForAccountDeletion(owner: RecordingOwner) async throws {
        throw RideUploadStoreError.invalidOwner
    }

    func purgeAccount(owner: RecordingOwner) async throws {
        throw RideUploadStoreError.invalidOwner
    }
}

protocol AppSessionRideRecordingRuntime: Sendable {
    func activate(user: User?) async throws -> InterruptedRideRecovery?
    func saveRecovery(_ recovery: InterruptedRideRecovery) async throws -> FinalizedRecording
    func discard(_ recovery: InterruptedRideRecovery) async throws
    func discardFinalizedLocalRecording(_ finalized: FinalizedRecording) async throws
    func localSavedRides(user: User) async throws -> [LocalSavedRide]
    func localSavedRideEvidence(user: User, rideID: String) async throws -> LocalSavedRideEvidence
    func accountDeletionRecords(owner: RecordingOwner) async throws -> [AccountDeletionCustodyRecord]
    func purgeAccount(owner: RecordingOwner) async throws
}

extension RideRecordingRuntime: AppSessionRideRecordingRuntime {}

/// The auth surface AppSession drives, injectable so session-operations
/// tests run deterministically without the network (bead `f4acp.2.9`).
protocol AppSessionAuthClient: Sendable {
    func resumeSession() async -> SessionResumeOutcome
    func me() async throws -> User
    func threshold() async throws -> ThresholdResponse
    /// Revoke the server session, then drop local tokens.
    func logout() async
    /// Drop local tokens only — used when the server already ended the
    /// session (forced sign-out) and a revoke call would be theater.
    func clearLocalSession() async
    /// Account deletion cannot report local completion unless durable session
    /// credentials are positively absent after a throwing delete/readback.
    func clearLocalSessionForAccountDeletion() async throws
    /// Cancel account-bound auth/cache work without revoking the bearer used
    /// to submit a deletion request.
    func advanceAccountBoundary() async
    /// Exact durable refusal witness prepared before APIClient exposes a
    /// deletion-specific auth outcome. Test doubles may return nil.
    func accountDeletionRefusalContext() async -> AccountDeletionRefusalContext?
    /// Best-effort push-token removal while the session is still live.
    func removePushRegistration() async
}

protocol AccountDeletionEmergencyFenceStoring: Sendable {
    func records() -> [AccountDeletionSessionRecord]
    func armRequired(recoveryID: String) throws
    func clearRequired(recoveryID: String) throws
}

struct DurableAccountDeletionEmergencyFenceStore: AccountDeletionEmergencyFenceStoring {
    func records() -> [AccountDeletionSessionRecord] {
        AccountDeletionEmergencyFenceStore.records
    }

    func armRequired(recoveryID: String) throws {
        try AccountDeletionEmergencyFenceStore.armRequired(recoveryID: recoveryID)
    }

    func clearRequired(recoveryID: String) throws {
        try AccountDeletionEmergencyFenceStore.clearRequired(recoveryID: recoveryID)
    }
}

extension APIClient: AppSessionAuthClient {
    func clearLocalSession() { clearSession() }
    func clearLocalSessionForAccountDeletion() async throws { try await clearSessionRequired() }
    func removePushRegistration() async { try? await unregisterPushDevice() }
}

extension AppSessionAuthClient {
    func advanceAccountBoundary() async {}
    func accountDeletionRefusalContext() async -> AccountDeletionRefusalContext? { nil }
    func threshold() async throws -> ThresholdResponse {
        throw URLError(.notConnectedToInternet)
    }
}

extension AppSessionRideRecordingRuntime {
    func localSavedRides(user: User) async throws -> [LocalSavedRide] { [] }

    /// Fail closed by default: only the real custody runtime serves local
    /// ride evidence.
    func localSavedRideEvidence(user: User, rideID: String) async throws -> LocalSavedRideEvidence {
        throw LiveRideCustodyError.noActiveRide
    }

    /// Fail closed by default: only runtimes that implement the exact-owner
    /// discard saga may delete finalized local evidence.
    func discardFinalizedLocalRecording(_ finalized: FinalizedRecording) async throws {
        throw LiveRideCustodyError.noActiveRide
    }

    func accountDeletionRecords(owner: RecordingOwner) async throws -> [AccountDeletionCustodyRecord] {
        throw LiveRideCustodyError.ownerMismatch
    }

    func purgeAccount(owner: RecordingOwner) async throws {
        throw LiveRideCustodyError.ownerMismatch
    }
}

/// App-wide session state: who is signed in, and the one piece of top-bar
/// truth (the settlement dot).
@MainActor
@Observable
final class AppSession {
    enum Phase {
        case resuming
        case signedOut
        case signedIn(User)
    }

    /// Whether the last resume reached the server. `.unreachable` means the
    /// rider is looking at this device's copy — the feed shows one truthful
    /// banner and each foreground retries silently. It is never an error
    /// wall and never signs the rider out.
    enum Connectivity: Equatable {
        case connected
        case unreachable
    }

    var phase: Phase = .resuming
    var connectivity: Connectivity = .connected
    /// Truthful one-liner for onboarding when the previous session ended by
    /// the server's word (expiry after long offline, revocation). `nil` for
    /// ordinary sign-outs and fresh installs.
    var sessionEndNotice: String?
    /// Blue settlement dot on the top-bar avatar (Law: pushes, not rooms —
    /// the dot is the announcement). True when uncollected DUNG exists.
    var hasUncollectedSettlements: Bool?
    /// Server-projected Balance controls. The initial and error state is
    /// deliberately unavailable so no action appears from compiled policy.
    var balanceActions = BalanceActionAvailability.unavailable
    /// A file handed to us by the share sheet / document open, queued for the
    /// import pipeline.
    var pendingImportURL: URL?
    /// Bumped when an import finishes so the feed refreshes.
    var lastImportCompletedAt: Date?
    /// Durably claimed persisted reveal, if an authoritative next-open
    /// reconciliation found one eligible final ride. It remains recoverable
    /// until the rider completes the ceremony and acknowledgement persists.
    var pendingRideReveal: PendingRideReveal?
    /// Immediate, non-durable handoff from a completed reveal into the real
    /// server-backed ride. Relaunch still reaches the same ride from the feed.
    var pendingFinishedRideID: String?
    /// Oldest owner-bound ride that is saved locally but cannot publish until
    /// the rider confirms audience and route visibility.
    var pendingRidePrivacyReview: RideUploadJob?
    /// Owner-bound interrupted ride recovered from encrypted local custody.
    var pendingInterruptedRide: InterruptedRideRecovery?
    /// Current recovery action that must remain exact across an unavailable
    /// local-custody boundary. A confirmed Discard remains destructive and
    /// retry-only until exact-owner deletion durably completes.
    var interruptedRideActionIntent: InterruptedRideRecoveryAction?
    /// Finalized rides retained only on this device because their evidence did
    /// not meet the existing upload threshold.
    var localSavedRides: [LocalSavedRide]?
    /// Local custody is unavailable. This remains nonfinal and retryable; it
    /// is never projected as "no interrupted ride."
    var interruptedRideErrorMessage: String?
    /// Durable bearer capability takes precedence over authentication so a
    /// server tombstone can never hide deletion status on relaunch.
    var accountDeletionCapabilityState: AccountDeletionCapabilityStorageState = .none
    /// A deletion-specific auth refusal may originate on another device and
    /// therefore have no local bearer capability. Preserve the exact server
    /// state and owner long enough to route custody/support truthfully.
    var accountDeletionSessionRecord: AccountDeletionSessionRecord?
    /// The rider asked to establish a fresh server session while a durable
    /// deletion recovery record remains in place. This is deliberately
    /// process-local: relaunch returns to the recovery room, and no sign-in
    /// may erase a saved-status replacement fence.
    var accountDeletionReauthenticationRequested = false

    @ObservationIgnored private let rideUploads: any AppSessionRideUploadRuntime
    @ObservationIgnored private let rideRecordings: any AppSessionRideRecordingRuntime
    @ObservationIgnored private let authClient: any AppSessionAuthClient
    @ObservationIgnored private let accountDeletionCapabilityStore: any AccountDeletionCapabilityStoring
    @ObservationIgnored private let accountDeletionSessionStore: any AccountDeletionSessionRecordStoring
    @ObservationIgnored private let accountDeletionEmergencyFenceStore: any AccountDeletionEmergencyFenceStoring
    @ObservationIgnored private var isSelectingRideReveal = false
    @ObservationIgnored private var requestedRevealOwner: RecordingOwner?
    @ObservationIgnored private var isAcknowledgingRideReveal = false
    @ObservationIgnored private var deferredPrivacyReviewIDs = Set<String>()
    @ObservationIgnored private var activeOwner: RecordingOwner?
    @ObservationIgnored private var isHandlingForcedSignOut = false
    @ObservationIgnored private var isAccountDeletionTeardownStarted = false
    @ObservationIgnored private var isAccountDeletionTeardownExecuting = false
    /// A completed token lifecycle is authoritative for this process. Keep
    /// already-enqueued deletion-401 callbacks from recreating a second room
    /// after the rider acknowledges Done; a later successful sign-in proves a
    /// new live account context and clears this suppression.
    @ObservationIgnored private var suppressDeletionSessionStateUntilNextSignIn = false
    /// Correlates repeated 401 notifications only within this process. A cold
    /// ownerless refusal must never be guessed onto an unrelated retained or
    /// already-completed recovery room.
    @ObservationIgnored private var activeDeletionRefusalRecoveryID: String?
    @ObservationIgnored private var accountBoundaryGeneration: UInt64 = 0
    @ObservationIgnored private var sessionInvalidationObserver: (any NSObjectProtocol)?
    @ObservationIgnored private var accountDeletionSessionObserver: (any NSObjectProtocol)?

    init(
        rideUploads: any AppSessionRideUploadRuntime = RideUploadRuntime.shared,
        rideRecordings: any AppSessionRideRecordingRuntime = RideRecordingRuntime.shared,
        authClient: any AppSessionAuthClient = APIClient.shared,
        accountDeletionCapabilityStore: any AccountDeletionCapabilityStoring = KeychainAccountDeletionCapabilityStore(),
        accountDeletionSessionStore: any AccountDeletionSessionRecordStoring = DurableAccountDeletionSessionRecordStore(),
        accountDeletionEmergencyFenceStore: any AccountDeletionEmergencyFenceStoring = DurableAccountDeletionEmergencyFenceStore()
    ) {
        self.rideUploads = rideUploads
        self.rideRecordings = rideRecordings
        self.authClient = authClient
        self.accountDeletionCapabilityStore = accountDeletionCapabilityStore
        self.accountDeletionSessionStore = accountDeletionSessionStore
        self.accountDeletionEmergencyFenceStore = accountDeletionEmergencyFenceStore
        let cachedOwner = CachedRiderStore.load().map { RecordingOwner(user: $0) }
        accountDeletionCapabilityState = cachedOwner.map {
            accountDeletionCapabilityStore.load(owner: $0)
        } ?? accountDeletionCapabilityStore.load()
        let sessionRecords = accountDeletionSessionStore.loadAll()
        let unmatchedEmergency = accountDeletionEmergencyFenceStore.records().last {
            emergency in !sessionRecords.contains { candidate in
                candidate.recoveryID == emergency.recoveryID
                    && (candidate.owner != nil
                        || candidate.localCleanupCompletedAt != nil
                        || candidate.state != .identityUnavailable
                        || candidate.savedStatusRemoved)
            }
        }
        accountDeletionSessionRecord = unmatchedEmergency
            ?? cachedOwner.flatMap { owner in
                sessionRecords.last { $0.owner == owner }
            }
            ?? sessionRecords.last
        sessionInvalidationObserver = NotificationCenter.default.addObserver(
            forName: .brSessionInvalidated, object: nil, queue: .main
        ) { [weak self, weak boundClient = authClient as AnyObject] notification in
            // Only the invalidation from THIS session's own auth client
            // counts — other instances (tests, previews) are not us.
            guard let source = notification.object as AnyObject?,
                  let boundClient,
                  source === boundClient
            else { return }
            let reason = (notification.userInfo?["reason"] as? String)
                .flatMap(SessionEndReason.init(rawValue:)) ?? .revokedByServer
            Task { @MainActor [weak self] in
                await self?.handleForcedSignOut(reason: reason)
            }
        }
        accountDeletionSessionObserver = NotificationCenter.default.addObserver(
            forName: .brAccountDeletionSessionState, object: nil, queue: .main
        ) { [weak self, weak boundClient = authClient as AnyObject] notification in
            guard let source = notification.object as AnyObject?,
                  let boundClient,
                  source === boundClient,
                  let rawState = notification.userInfo?["state"] as? String,
                  let state = AccountDeletionSessionState(rawValue: rawState)
            else { return }
            let context = (notification.userInfo?["recovery_id"] as? String).map {
                AccountDeletionRefusalContext(
                    recoveryID: $0,
                    attemptedOwner: {
                        guard let id = notification.userInfo?["attempted_owner_id"] as? String,
                              let wallet = notification.userInfo?["attempted_owner_wallet"] as? String
                        else { return nil }
                        return RecordingOwner(id: id, wallet: wallet)
                    }(),
                    attemptedWallet: notification.userInfo?["attempted_wallet"] as? String
                )
            }
            Task { @MainActor [weak self] in
                await self?.handleAccountDeletionSessionState(
                    state,
                    refusalContext: context
                )
            }
        }
    }

    deinit {
        if let observer = sessionInvalidationObserver {
            NotificationCenter.default.removeObserver(observer)
        }
        if let observer = accountDeletionSessionObserver {
            NotificationCenter.default.removeObserver(observer)
        }
    }

    var currentUser: User? {
        if case let .signedIn(user) = phase { return user }
        return nil
    }

    /// Adopt a server-returned profile for the already-signed-in rider
    /// (profile edit, avatar change). Identity is pinned: a response for a
    /// different account is refused rather than swapped in.
    func adoptUpdatedUser(_ user: User) {
        guard let current = currentUser, current.id == user.id else { return }
        guard !accountDeletionSessionRecordFences(RecordingOwner(user: current)) else { return }
        guard case .none = accountDeletionCapabilityState else { return }
        phase = .signedIn(user)
    }

    private var currentRecordingOwner: RecordingOwner? {
        currentUser.map(RecordingOwner.init(user:))
    }

    /// A recovery record is an exact-owner fence when both identities are
    /// known. Unknown ownership remains fail-closed.
    private func accountDeletionSessionRecordFences(_ owner: RecordingOwner?) -> Bool {
        var records = accountDeletionSessionStore.loadAll()
        for emergency in accountDeletionEmergencyFenceStore.records()
        where !records.contains(emergency) {
            records.append(emergency)
        }
        for record in AccountDeletionProcessFence.records() where !records.contains(record) {
            records.append(record)
        }
        if let accountDeletionSessionRecord,
           !records.contains(accountDeletionSessionRecord) {
            records.append(accountDeletionSessionRecord)
        }
        guard !records.isEmpty else { return false }
        guard let owner else { return true }
        return records.contains { $0.owner.map { $0 == owner } ?? true }
    }

    private func clearAccountDeletionSessionRecord(
        _ record: AccountDeletionSessionRecord
    ) throws {
        if accountDeletionEmergencyFenceStore.records().contains(where: {
            $0.recoveryID == record.recoveryID
        }) {
            // The rich journal remains the durable writer fence until the
            // crash witness for this exact recovery slot is verifiably gone.
            // A failed witness clear therefore leaves a retryable room rather
            // than reporting Done and resurrecting an ownerless room later.
            try accountDeletionEmergencyFenceStore.clearRequired(
                recoveryID: record.recoveryID
            )
            guard !accountDeletionEmergencyFenceStore.records().contains(where: {
                $0.recoveryID == record.recoveryID
            }) else {
                throw AccountDeletionCapabilityStoreError.unavailable
            }
        }
        try accountDeletionSessionStore.clearRequired(record)
        guard !accountDeletionSessionStore.contains(record) else {
            throw AccountDeletionCapabilityStoreError.unavailable
        }
        if accountDeletionSessionRecord == record {
            accountDeletionSessionRecord = accountDeletionSessionStore.load()
        }
        AccountDeletionProcessFence.clear(record)
        if activeDeletionRefusalRecoveryID == record.recoveryID {
            activeDeletionRefusalRecoveryID = nil
        }
    }

    /// Root routing must use the cached identity during cold start. Otherwise
    /// owner A's retained deletion capability can globally lock owner B before
    /// authentication has had a chance to resume.
    var accountRoutingOwner: RecordingOwner? {
        currentRecordingOwner
            ?? CachedRiderStore.load().map { RecordingOwner(user: $0) }
    }

    /// Relaunch resume ladder (bead `f4acp.2.9`). The stored session ends
    /// only on the server's definitive word; an unreachable server resumes
    /// to the rider's own cached, read-mostly state instead of a false
    /// onboarding.
    func resume() async {
        let boundary = accountBoundaryGeneration
        guard permitsAccountWork(at: boundary) else { return }
        sessionEndNotice = SessionEndReasonStore.pending()?.onboardingNotice
        let outcome = await authClient.resumeSession()
        guard accountBoundaryGeneration == boundary else { return }
        if case .accountDeletion = outcome {
            // The API durably arms this exact refusal during the awaited
            // refresh flight. That new fence is the expected result, not a
            // reason to discard the only callback that can enrich it.
        } else {
            guard permitsAccountWork(at: boundary) else { return }
        }
        switch outcome {
        case .noStoredSession:
            await settleSignedOut()

        case let .rejected(reason):
            // Truthful re-auth prompt, never a silent dead session.
            SessionEndReasonStore.record(reason)
            sessionEndNotice = reason.onboardingNotice
            CachedRiderStore.clear()
            await settleSignedOut()

        case let .accountDeletion(state):
            let context = await authClient.accountDeletionRefusalContext()
            // A fresh sign-in can complete while the actor-backed refusal
            // context read is suspended. The API has already persisted the
            // exact recovery witness, so drop this stale flight rather than
            // letting it tear down the newly adopted account.
            guard accountBoundaryGeneration == boundary else { return }
            let owner = context?.attemptedOwner
                ?? (context == nil
                    ? currentRecordingOwner
                        ?? CachedRiderStore.load().map { RecordingOwner(user: $0) }
                    : nil)
            await adoptAccountDeletionSessionState(
                state,
                owner: owner,
                refusalContext: context
            )

        case .resumed:
            connectivity = .connected
            SessionEndReasonStore.clear()
            sessionEndNotice = nil
            let resumedUser = try? await authClient.me()
            guard permitsAccountWork(at: boundary) else { return }
            if let user = resumedUser {
                suppressDeletionSessionStateUntilNextSignIn = false
                CachedRiderStore.save(user)
                hydrateRiderPhysiology(from: user)
                await refreshRiderThreshold(for: user)
                phase = .signedIn(user)
                await resumeOwnerServices(for: user)
            } else if let cached = CachedRiderStore.load() {
                // Tokens are live but the profile read failed — stay signed
                // in on the cached identity; reads retry per-surface.
                suppressDeletionSessionStateUntilNextSignIn = false
                phase = .signedIn(cached)
                await resumeOwnerServices(for: cached)
            } else {
                // Refreshed but no profile and no cache (first-launch race).
                // The Keychain session survives; next open completes it.
                await settleSignedOut()
            }

        case .transient:
            if let cached = CachedRiderStore.load() {
                // Offline resume: this device's copy, truthfully banner'd.
                connectivity = .unreachable
                phase = .signedIn(cached)
                await resumeOwnerServices(for: cached)
            } else {
                // Fresh install with no server: onboarding is the truth.
                await settleSignedOut()
            }
        }
    }

    private func settleSignedOut() async {
        _ = try? await rideRecordings.activate(user: nil)
        await rideUploads.activate(user: nil)
        phase = .signedOut
    }

    /// Retry a degraded session exactly once per foreground. Success flips
    /// the banner off; another transient failure keeps the cached state.
    func revalidateIfDegraded() async {
        guard connectivity == .unreachable else { return }
        await resume()
    }

    func completeSignIn() async throws {
        let boundary = accountBoundaryGeneration
        let reauthenticationRecord: AccountDeletionSessionRecord?
        if accountDeletionReauthenticationRequested,
           let record = accountDeletionSessionRecord,
           case .none = accountDeletionCapabilityState,
           currentUser == nil {
            reauthenticationRecord = record
        } else {
            reauthenticationRecord = nil
        }
        guard reauthenticationRecord != nil || permitsAccountWork(at: boundary) else {
            throw AccountDeletionCapabilityStoreError.invalid
        }
        let user = try await authClient.me()
        guard accountBoundaryGeneration == boundary else {
            throw AccountDeletionCapabilityStoreError.invalid
        }
        if let reauthenticationRecord {
            guard accountDeletionReauthenticationRequested,
                  accountDeletionSessionRecord == reauthenticationRecord,
                  accountDeletionSessionStore.contains(reauthenticationRecord),
                  case .none = accountDeletionCapabilityState,
                  currentUser == nil
            else { throw AccountDeletionCapabilityStoreError.invalid }

            let signedInOwner = RecordingOwner(user: user)
            let exactRecord = accountDeletionSessionStore.load(owner: signedInOwner)
            if let exactRecord, exactRecord.savedStatusRemoved {
                // A successful identity read is not cancellation authority:
                // DELETE may have committed after the preceding 404. Keep the
                // only durable writer fence and remove the newly-made session.
                accountDeletionSessionRecord = exactRecord
                accountDeletionReauthenticationRequested = false
                await tearDownSession(revokeServerSession: false)
                throw AccountDeletionCapabilityStoreError.invalid
            }
            if let exactRecord {
                // Ordinary support recovery may clear only after the server
                // has established a live identity for this exact account.
                try clearAccountDeletionSessionRecord(exactRecord)
                isAccountDeletionTeardownStarted = false
            } else if reauthenticationRecord.owner == nil {
                // An ownerless recovery row cannot be assigned to whichever
                // account happened to authenticate next.
                accountDeletionReauthenticationRequested = false
                await tearDownSession(revokeServerSession: false)
                throw AccountDeletionCapabilityStoreError.invalid
            }
        } else {
            guard permitsAccountWork(at: boundary) else {
                throw AccountDeletionCapabilityStoreError.invalid
            }
        }
        SessionEndReasonStore.clear()
        sessionEndNotice = nil
        connectivity = .connected
        accountBoundaryGeneration &+= 1
        suppressDeletionSessionStateUntilNextSignIn = false
        activeDeletionRefusalRecoveryID = nil
        accountDeletionReauthenticationRequested = false
        CachedRiderStore.save(user)
        hydrateRiderPhysiology(from: user)
        await refreshRiderThreshold(for: user)
        phase = .signedIn(user)
        await resumeOwnerServices(for: user)
        // A fresh session is a drain opportunity for queued diagnostics.
        CrashReporting.drainQueue()
    }

    /// Session-start half of the rider-weight sync rule.
    private func hydrateRiderPhysiology(from user: User) {
        RiderPhysiologyStore.adoptServerWeight(
            weightKg: user.weightKg,
            weightSource: user.weightKgSource,
            riderID: user.id
        )
    }

    @discardableResult
    private func refreshRiderThreshold(
        for user: User,
        requireActiveOwner: Bool = false
    ) async -> Bool {
        RiderThresholdStore.clear(riderID: user.id)
        guard !Task.isCancelled,
              let response = try? await authClient.threshold(),
              !Task.isCancelled,
              !requireActiveOwner || currentUser?.id == user.id,
              RiderThresholdStore.save(response, riderID: user.id)
        else {
            RiderThresholdStore.clear(riderID: user.id)
            return false
        }
        return true
    }

    @discardableResult
    func refreshRiderThresholdAuthority(
        for requestedRiderID: String? = nil
    ) async -> ThresholdDisplay? {
        guard let user = currentUser,
              requestedRiderID == nil || requestedRiderID == user.id,
              await refreshRiderThreshold(for: user, requireActiveOwner: true)
        else { return nil }
        guard !Task.isCancelled, currentUser?.id == user.id else {
            RiderThresholdStore.clear(riderID: user.id)
            return nil
        }
        return RiderThresholdStore.display(riderID: user.id)
    }

    func invalidateRiderThresholdAuthority() {
        guard let user = currentUser else { return }
        RiderThresholdStore.clear(riderID: user.id)
    }

    func signOut() async {
        let boundary = accountBoundaryGeneration
        guard permitsAccountWork(at: boundary) else { return }
        SessionEndReasonStore.record(.riderSignedOut)
        sessionEndNotice = nil
        // Best-effort while the session is still live; the send worker also
        // drops tokens APNs reports gone.
        await authClient.removePushRegistration()
        guard permitsAccountWork(at: boundary) else { return }
        await tearDownSession(
            revokeServerSession: true,
            expectedAccountBoundary: boundary
        )
    }

    /// Settings/token lifecycle inventory is explicitly owner-scoped. A
    /// retained journal for rider A must never redirect rider B's destructive
    /// preflight to A's custody.
    func accountDeletionInventory(
        owner: RecordingOwner
    ) async throws -> AccountDeletionLocalInventory {
        let capabilityOwner = accountDeletionCapabilityState.capability?.owner
        guard currentRecordingOwner == nil || currentRecordingOwner == owner,
              currentRecordingOwner == owner || capabilityOwner == owner
        else {
            throw APIError.notAuthenticated
        }
        return try await readAccountDeletionInventory(
            owner: owner,
            requiresRecoveryFreeze: currentRecordingOwner == nil,
            expectedRecoveryRecord: nil,
            expectedAccountBoundary: nil
        )
    }

    /// Portal/support-completed recovery is bound to the room's opaque slot,
    /// then to that slot's retained exact owner. It cannot infer from a signed
    /// in rider or another journal row.
    func accountDeletionSessionInventory(
        recoveryID: String
    ) async throws -> AccountDeletionLocalInventory {
        let boundary = accountBoundaryGeneration
        guard let record = accountDeletionSessionStore.loadAll().last(where: {
            $0.recoveryID == recoveryID
        }) ?? accountDeletionSessionRecord.flatMap({
            $0.recoveryID == recoveryID ? $0 : nil
        }),
        let owner = record.owner
        else { throw APIError.notAuthenticated }
        return try await readAccountDeletionInventory(
            owner: owner,
            requiresRecoveryFreeze: true,
            expectedRecoveryRecord: record,
            expectedAccountBoundary: boundary
        )
    }

    private func readAccountDeletionInventory(
        owner: RecordingOwner,
        requiresRecoveryFreeze: Bool,
        expectedRecoveryRecord: AccountDeletionSessionRecord?,
        expectedAccountBoundary: UInt64?
    ) async throws -> AccountDeletionLocalInventory {
        if requiresRecoveryFreeze {
            // A deletion-specific 401 can be the only durable lifecycle
            // evidence after relaunch. Re-establish custody before inventory
            // reads so the recovery room never observes or acts through a
            // live writer runtime.
            try validateRecoveryInventoryContext(
                record: expectedRecoveryRecord,
                boundary: expectedAccountBoundary
            )
            _ = try await rideRecordings.activate(user: nil)
            try validateRecoveryInventoryContext(
                record: expectedRecoveryRecord,
                boundary: expectedAccountBoundary
            )
            try await rideUploads.freezeForAccountDeletion(owner: owner)
            try validateRecoveryInventoryContext(
                record: expectedRecoveryRecord,
                boundary: expectedAccountBoundary
            )
            await FileFeedCache.shared.freeze(owner: owner)
            try validateRecoveryInventoryContext(
                record: expectedRecoveryRecord,
                boundary: expectedAccountBoundary
            )
            activeOwner = nil
            pendingRideReveal = nil
            pendingFinishedRideID = nil
            pendingRidePrivacyReview = nil
            pendingInterruptedRide = nil
            pendingImportURL = nil
            interruptedRideActionIntent = nil
            localSavedRides = nil
            PushRouter.shared.clearAccountData()
        }
        async let custody = rideRecordings.accountDeletionRecords(owner: owner)
        async let uploads = rideUploads.accountDeletionRecords(owner: owner)
        let (custodyRecords, uploadRecords) = try await (custody, uploads)
        try validateRecoveryInventoryContext(
            record: expectedRecoveryRecord,
            boundary: expectedAccountBoundary
        )
        return try AccountDeletionLocalInventory(
            custody: custodyRecords,
            uploads: uploadRecords
        )
    }

    private func validateRecoveryInventoryContext(
        record: AccountDeletionSessionRecord?,
        boundary: UInt64?
    ) throws {
        guard let record, let boundary else { return }
        guard accountBoundaryGeneration == boundary,
              accountDeletionSessionStore.contains(record)
        else { throw APIError.notAuthenticated }
    }

    /// Called after the capability has survived a Keychain read-back and
    /// before DELETE. Recording is durably suspended; upload authorization,
    /// scheduled reconciliation, and exact active transfers are stopped while
    /// every source byte remains recoverable.
    func accountDeletionCapabilityDidChange(
        expectedOwner: RecordingOwner? = nil
    ) async throws {
        let previousCapability = accountDeletionCapabilityState.capability
        let isReconcilingScrubbedCompletion = previousCapability?.owner == nil
            && previousCapability?.localCleanupCompletedAt != nil
            && previousCapability?.verifiedCompletion != nil
        let routingOwner = currentRecordingOwner
            ?? CachedRiderStore.load().map { RecordingOwner(user: $0) }
        if let expectedOwner {
            guard currentRecordingOwner == nil || currentRecordingOwner == expectedOwner,
                  routingOwner == expectedOwner
                    || previousCapability?.owner == expectedOwner
                    || isReconcilingScrubbedCompletion
            else { throw AccountDeletionCapabilityStoreError.invalid }
        }
        if let routingOwner,
           previousCapability?.owner != routingOwner {
            accountDeletionCapabilityState = accountDeletionCapabilityStore.load(
                owner: routingOwner
            )
        } else if let requestID = previousCapability?.requestID {
            // Request ID remains the stable slot after verified cleanup
            // scrubs identity. Never let that update collide with another
            // rider's retained or already-ownerless completion.
            let exactState = accountDeletionCapabilityStore.load(
                requestID: requestID
            )
            if case .none = exactState {
                if isReconcilingScrubbedCompletion {
                    // Done removed this exact anonymous completion. Do not
                    // fall through to another rider's ledger row while the
                    // stale sheet is reconciling its now-absent request.
                    accountDeletionCapabilityState = .none
                } else {
                    accountDeletionCapabilityState = routingOwner.map {
                        accountDeletionCapabilityStore.load(owner: $0)
                    } ?? accountDeletionCapabilityStore.load()
                }
            } else {
                accountDeletionCapabilityState = exactState
            }
        } else if let routingOwner {
            accountDeletionCapabilityState = accountDeletionCapabilityStore.load(
                owner: routingOwner
            )
        } else {
            accountDeletionCapabilityState = accountDeletionCapabilityStore.load()
        }
        accountBoundaryGeneration &+= 1
        await authClient.advanceAccountBoundary()
        RouteMapSnapshot.SnapshotDisk.advanceAccountBoundary()
        RouteMapSnapshot.SnapshotCache.shared.removeAll()
        RemoteImageCache.shared.advanceAccountBoundary()
        let capability: AccountDeletionCapability
        switch accountDeletionCapabilityState {
        case let .available(value), let .unconfirmed(value):
            capability = value
        case .none:
            if let user = currentUser,
               !accountDeletionSessionRecordFences(RecordingOwner(user: user)) {
                await resumeOwnerServices(for: user)
            } else if accountDeletionSessionRecord != nil {
                _ = try? await rideRecordings.activate(user: nil)
                await rideUploads.activate(user: nil)
                activeOwner = nil
            }
            return
        case .unavailable:
            _ = try? await rideRecordings.activate(user: nil)
            await rideUploads.activate(user: nil)
            activeOwner = nil
            pendingImportURL = nil
            pendingInterruptedRide = nil
            pendingRidePrivacyReview = nil
            pendingRideReveal = nil
            return
        }
        if let expectedOwner, capability.owner != expectedOwner {
            let reconciledScrubbedCompletion = capability.owner == nil
                && capability.localCleanupCompletedAt != nil
                && capability.verifiedCompletion != nil
                && capability.requestID == previousCapability?.requestID
                && (previousCapability?.owner == expectedOwner
                    || isReconcilingScrubbedCompletion)
            guard reconciledScrubbedCompletion else {
                throw AccountDeletionCapabilityStoreError.invalid
            }
        }
        guard let owner = capability.owner else { return }
        guard currentRecordingOwner == nil || currentRecordingOwner == owner else {
            throw AccountDeletionCapabilityStoreError.invalid
        }
        _ = try await rideRecordings.activate(user: nil)
        try await rideUploads.freezeForAccountDeletion(owner: owner)
        await FileFeedCache.shared.freeze(owner: owner)
        activeOwner = nil
        pendingRideReveal = nil
        pendingFinishedRideID = nil
        pendingRidePrivacyReview = nil
        pendingInterruptedRide = nil
        pendingImportURL = nil
        interruptedRideActionIntent = nil
        localSavedRides = nil
        PushRouter.shared.clearAccountData()
    }

    /// Local cleanup has succeeded while the verified capability still owns
    /// its exact identity. Reconcile only that owner's deletion-401 journal
    /// before the capability is privacy-scrubbed; a different owner's durable
    /// recovery record must survive cleanup, Done, and relaunch.
    func accountDeletionLocalCleanupDidComplete(owner: RecordingOwner) async throws {
        guard case let .available(selectedCapability) = accountDeletionCapabilityState,
              case let .available(capability) = accountDeletionCapabilityStore.load(
                  requestID: selectedCapability.requestID
              ),
              capability.owner == owner,
              capability.verifiedCompletion != nil,
              capability.localCleanupCompletedAt == nil
        else { throw AccountDeletionCapabilityStoreError.invalid }
        let refusalContext = await authClient.accountDeletionRefusalContext()
        guard case let .available(currentSelection) = accountDeletionCapabilityState,
              currentSelection.requestID == selectedCapability.requestID,
              case let .available(currentCapability) = accountDeletionCapabilityStore.load(
                  requestID: selectedCapability.requestID
              ),
              currentCapability.owner == owner,
              currentCapability.verifiedCompletion != nil,
              currentCapability.localCleanupCompletedAt == nil
        else { throw AccountDeletionCapabilityStoreError.invalid }
        if let record = accountDeletionSessionStore.load(owner: owner) {
            try clearAccountDeletionSessionRecord(record)
            isAccountDeletionTeardownStarted = false
        }
        if let refusalContext,
           refusalContext.attemptedOwner == owner,
           accountDeletionEmergencyFenceStore.records().contains(where: {
               $0.recoveryID == refusalContext.recoveryID
           }) {
            try accountDeletionEmergencyFenceStore.clearRequired(
                recoveryID: refusalContext.recoveryID
            )
            guard !accountDeletionEmergencyFenceStore.records().contains(where: {
                $0.recoveryID == refusalContext.recoveryID
            }) else { throw AccountDeletionCapabilityStoreError.unavailable }

            if let selectedRecord = accountDeletionSessionRecord,
               selectedRecord.recoveryID == refusalContext.recoveryID,
               !accountDeletionSessionStore.loadAll().contains(where: {
                   $0.recoveryID == refusalContext.recoveryID
               }) {
                accountDeletionSessionRecord = accountDeletionSessionStore.load()
                AccountDeletionProcessFence.clear(selectedRecord)
                if activeDeletionRefusalRecoveryID == refusalContext.recoveryID {
                    activeDeletionRefusalRecoveryID = nil
                }
            }
        }
        // A delayed refusal may be suppressed only after its exact durable
        // recovery witness has been retired and verified absent.
        suppressDeletionSessionStateUntilNextSignIn = true
    }

    /// Retry a transient Keychain read on explicit rider action or foreground.
    /// The same method updates RootView's observable switch and re-applies the
    /// corresponding writer fence before returning.
    func reloadAccountDeletionStorage() async {
        guard case .unavailable = accountDeletionCapabilityState else {
            try? await accountDeletionCapabilityDidChange()
            return
        }
        do {
            try await accountDeletionCapabilityDidChange()
        } catch {
            return
        }
        guard !accountDeletionSessionRecordFences(accountRoutingOwner),
              case .resuming = phase
        else { return }
        switch accountDeletionCapabilityState {
        case .none, .unconfirmed:
            await resume()
        case .available, .unavailable:
            break
        }
    }

    /// Local cleanup is a distinct exact-owner path, never ordinary sign-out.
    /// It runs only for a matching token-authorized completed response.
    func completeLocalAccountDeletion(
        capability: AccountDeletionCapability,
        status: AccountDeletionStatus
    ) async throws {
        guard status.isVerifiedCompletion(for: capability),
              capability.unuploadedRidesAcknowledged,
              let owner = capability.owner
        else { throw AccountDeletionCapabilityStoreError.invalid }

        guard case let .available(selectedCapability) = accountDeletionCapabilityState,
              case let .available(durableCapability) = accountDeletionCapabilityStore.load(
                requestID: selectedCapability.requestID
              ),
              durableCapability == capability,
              currentRecordingOwner == nil || currentRecordingOwner == owner
        else { throw AccountDeletionCapabilityStoreError.invalid }

        // Reassert every local writer fence here as well as during status
        // tracking. Cleanup remains fail-closed even if an earlier freeze was
        // partial or the completion callback is invoked from another path.
        try await accountDeletionCapabilityDidChange()
        async let custody = rideRecordings.accountDeletionRecords(owner: owner)
        async let uploads = rideUploads.accountDeletionRecords(owner: owner)
        let currentInventory = try await AccountDeletionLocalInventory(
            custody: custody,
            uploads: uploads
        )
        guard capability.acknowledgesForCleanup(currentInventory) else {
            throw AccountDeletionCapabilityStoreError.invalid
        }

        try await purgeLocalAccountData(owner: owner)
    }

    /// A portal/support-completed deletion has no local bearer token. The
    /// backend's exact `account_deleted` authentication refusal is the server
    /// authority; the current local inventory and the rider's acknowledgement
    /// are still rechecked after every writer is fenced before any purge.
    func completeLocalAccountDeletionFromSessionRecord(
        recoveryID: String,
        reviewedInventoryDigest: String?,
        unuploadedRidesAcknowledged: Bool
    ) async throws {
        guard let record = accountDeletionSessionRecord,
              record.recoveryID == recoveryID,
              record.state == .deleted,
              accountDeletionSessionStore.contains(record),
              let owner = record.owner,
              unuploadedRidesAcknowledged,
              currentUser == nil,
              case .none = accountDeletionCapabilityState
        else { throw AccountDeletionCapabilityStoreError.invalid }

        _ = try await rideRecordings.activate(user: nil)
        try await rideUploads.freezeForAccountDeletion(owner: owner)
        await FileFeedCache.shared.freeze(owner: owner)
        activeOwner = nil

        async let custody = rideRecordings.accountDeletionRecords(owner: owner)
        async let uploads = rideUploads.accountDeletionRecords(owner: owner)
        let currentInventory = try await AccountDeletionLocalInventory(
            custody: custody,
            uploads: uploads
        )
        guard reviewedInventoryDigest == currentInventory.digest else {
            throw AccountDeletionCapabilityStoreError.invalid
        }

        try await purgeLocalAccountData(owner: owner)
        let completedRecord = AccountDeletionSessionRecord(
            recoveryID: record.recoveryID,
            state: .deleted,
            owner: nil,
            localCleanupCompletedAt: .now
        )
        try accountDeletionSessionStore.replaceRequired(record, with: completedRecord)
        guard accountDeletionSessionStore.contains(completedRecord),
              !accountDeletionSessionStore.contains(record)
        else { throw AccountDeletionCapabilityStoreError.unavailable }
        accountDeletionSessionRecord = completedRecord
    }

    func acknowledgeAccountDeletionSessionCompletion() throws {
        guard let record = accountDeletionSessionRecord,
              record.localCleanupCompletedAt != nil
        else {
            throw AccountDeletionCapabilityStoreError.invalid
        }
        suppressDeletionSessionStateUntilNextSignIn = true
        try clearAccountDeletionSessionRecord(record)
        isAccountDeletionTeardownStarted = false
        accountDeletionReauthenticationRequested = false
        phase = .signedOut
    }

    private func purgeLocalAccountData(owner: RecordingOwner) async throws {

        // Custody first: if it is unavailable, upload sources remain intact.
        // Both purges are idempotent so a process kill between them retries.
        try await rideRecordings.purgeAccount(owner: owner)
        try await rideUploads.purgeAccount(owner: owner)
        try await FileFeedCache.shared.purge(owner: owner)
        try RiderPhysiologyStore.removeAccountDataRequired(riderID: owner.id)
        try CachedRiderStore.clearRequired()
        try SessionEndReasonStore.clearRequired()
        try await MainActor.run {
            ResponseCache.shared.clear()
            RemoteImageCache.shared.removeAll()
            RouteMapSnapshot.SnapshotCache.shared.removeAll()
            PushRouter.shared.clearAccountData()
            try SensorManager.shared.removeAccountData()
            URLCache.shared.removeAllCachedResponses()
        }
        try RouteMapSnapshot.SnapshotDisk.removeAll()
        try await DiagnosticQueue.shared.purge()
        try APIClient.rotateDeviceIDRequired()
        try KeychainStore.deleteRequired(.devWalletSeed)
        guard try KeychainStore.readRequired(.devWalletSeed) == nil else {
            throw AccountDeletionLocalCleanupError.verificationFailed
        }
        try SIWS.removeDeveloperWalletSeedRequired()
        let notifications = UNUserNotificationCenter.current()
        await notifications.removeAllDeliveredNotifications()
        notifications.removeAllPendingNotificationRequests()
        guard await notifications.deliveredNotifications().isEmpty,
              await notifications.pendingNotificationRequests().isEmpty
        else { throw AccountDeletionLocalCleanupError.verificationFailed }
        UIApplication.shared.applicationIconBadgeNumber = 0
        try await authClient.clearLocalSessionForAccountDeletion()
        try await PrivyAuthService.shared.logoutRequired()
        await tearDownSession(
            revokeServerSession: false,
            recordingAlreadyDeactivated: true
        )
        guard PushRouter.shared.pending == nil else {
            throw AccountDeletionLocalCleanupError.verificationFailed
        }
    }

    /// Server 401 storm → one clean sign-out. The refresh path already
    /// established the definitive rejection; this only lands the app state.
    /// Owner-bound local custody (interrupted rides, saved rides, reveal
    /// queue) is preserved on disk for the same rider's next sign-in —
    /// account-bound custody per MOBILE_TRUTHS.
    private func handleForcedSignOut(reason: SessionEndReason) async {
        guard case .signedIn = phase, !isHandlingForcedSignOut else { return }
        let boundary = accountBoundaryGeneration
        guard permitsAccountWork(at: boundary) else { return }
        isHandlingForcedSignOut = true
        defer { isHandlingForcedSignOut = false }
        SessionEndReasonStore.record(reason)
        sessionEndNotice = reason.onboardingNotice
        // No server logout call: the server already ended this session.
        await tearDownSession(
            revokeServerSession: false,
            expectedAccountBoundary: boundary
        )
    }

    private func handleAccountDeletionSessionState(
        _ state: AccountDeletionSessionState,
        refusalContext: AccountDeletionRefusalContext? = nil
    ) async {
        // A durable refusal context owns its identity correlation. Never bind
        // an authenticated callback to whichever rider arrived while this
        // observer task was waiting for MainActor execution.
        let owner = refusalContext?.attemptedOwner
            ?? (refusalContext == nil
                ? currentRecordingOwner
                    ?? CachedRiderStore.load().map { RecordingOwner(user: $0) }
                : nil)
        await adoptAccountDeletionSessionState(
            state,
            owner: owner,
            refusalContext: refusalContext
        )
    }

    private func adoptAccountDeletionSessionState(
        _ state: AccountDeletionSessionState,
        owner: RecordingOwner?,
        refusalContext: AccountDeletionRefusalContext? = nil
    ) async {
        if let refusalContext,
           let attemptedOwner = refusalContext.attemptedOwner,
           let liveOwner = currentRecordingOwner,
           liveOwner != attemptedOwner {
            // This callback belonged to an earlier bearer generation. Keep
            // its exact lifecycle truth durable without selecting that room
            // or touching the newly adopted rider's session and runtimes.
            preserveDetachedAccountDeletionSessionState(
                state,
                owner: attemptedOwner,
                refusalContext: refusalContext
            )
            return
        }
        if suppressDeletionSessionStateUntilNextSignIn {
            let hasUnretiredExactWitness = refusalContext.map { context in
                accountDeletionEmergencyFenceStore.records().contains {
                    $0.recoveryID == context.recoveryID
                }
            } ?? false
            guard hasUnretiredExactWitness else { return }
        }
        if case let .available(capability) = accountDeletionCapabilityState,
           capability.localCleanupCompletedAt != nil {
            // Cleanup completion may have persisted just before this observer
            // task ran. The capability callback owns reconciliation; never
            // create a fresh lower-authority journal behind it.
            suppressDeletionSessionStateUntilNextSignIn = true
            return
        }
        let previous: AccountDeletionSessionRecord?
        let resolvedOwner: RecordingOwner?
        if let attemptedOwner = refusalContext?.attemptedOwner {
            previous = accountDeletionSessionStore.load(owner: attemptedOwner)
                ?? accountDeletionSessionRecord.flatMap {
                    $0.owner == attemptedOwner ? $0 : nil
                }
            resolvedOwner = previous?.owner ?? attemptedOwner
        } else if let attemptedWallet = refusalContext?.attemptedWallet {
            previous = accountDeletionSessionStore.loadAll().last {
                $0.owner?.wallet == attemptedWallet
            }
            // A verification refusal is authority only for the wallet that
            // was actually presented. It may advance a retained exact-wallet
            // room or establish the same still-cached exact wallet; it can
            // never inherit a different cached rider. An older ownerless
            // emergency witness remains separate because it has no durable
            // wallet attribution and therefore cannot safely be cleared.
            if let previous {
                resolvedOwner = previous.owner
            } else if let owner, owner.wallet == attemptedWallet {
                resolvedOwner = owner
            } else {
                resolvedOwner = nil
            }
        } else if let owner {
            previous = accountDeletionSessionStore.load(owner: owner)
                ?? accountDeletionSessionRecord.flatMap { $0.owner == owner ? $0 : nil }
            resolvedOwner = previous?.owner ?? owner
        } else if let activeDeletionRefusalRecoveryID {
            previous = accountDeletionSessionStore.loadAll().last {
                $0.recoveryID == activeDeletionRefusalRecoveryID
            } ?? accountDeletionSessionRecord.flatMap {
                $0.recoveryID == activeDeletionRefusalRecoveryID ? $0 : nil
            }
            resolvedOwner = previous?.owner
        } else {
            previous = nil
            resolvedOwner = nil
        }
        let advancedState = advancingDeletionState(from: previous?.state, to: state)
        let record = AccountDeletionSessionRecord(
            recoveryID: previous?.recoveryID
                ?? refusalContext?.recoveryID
                ?? UUID().uuidString.lowercased(),
            state: advancedState,
            owner: resolvedOwner,
            savedStatusRemoved: advancedState == .deleted
                ? false
                : (previous?.savedStatusRemoved ?? false),
            localCleanupCompletedAt: previous?.localCleanupCompletedAt
        )
        activeDeletionRefusalRecoveryID = record.recoveryID
        accountDeletionSessionRecord = record
        AccountDeletionProcessFence.record(record)
        accountBoundaryGeneration &+= 1
        let adoptionBoundary = accountBoundaryGeneration
        // Stop routing every owner surface synchronously with the process
        // fence, before the first suspension point. Stale sheets still guard
        // their mutations independently below.
        phase = .signedOut
        activeOwner = nil
        requestedRevealOwner = nil
        pendingImportURL = nil
        pendingInterruptedRide = nil
        interruptedRideActionIntent = nil
        localSavedRides = nil
        pendingRidePrivacyReview = nil
        pendingRideReveal = nil
        pendingFinishedRideID = nil
        deferredPrivacyReviewIDs.removeAll()
        SessionEndReasonStore.clear()
        sessionEndNotice = nil
        let durable: Bool
        let emergencyRecoveryID = refusalContext?.recoveryID ?? record.recoveryID
        do {
            try persistAccountDeletionSessionRecord(record)
            try accountDeletionEmergencyFenceStore.clearRequired(
                recoveryID: emergencyRecoveryID
            )
            durable = true
        } catch {
            durable = false
            // Preserve pre-completion owner data and credentials. This
            // non-personal durable witness prevents cached offline resume if
            // the richer journal could not survive a process death.
            do {
                try accountDeletionEmergencyFenceStore.armRequired(
                    recoveryID: emergencyRecoveryID
                )
            } catch {
                // Last-resort fail closed: if neither durable fence can be
                // written, require verified removal of the refresh credential
                // instead of trusting a best-effort sign-out.
                try? await authClient.clearLocalSessionForAccountDeletion()
            }
        }
        guard deletionAdoptionIsCurrent(record, boundary: adoptionBoundary) else {
            return
        }
        // The recorder is the irreplaceable writer. Stop it before any upload
        // drain, cache clear, or network boundary can suspend this task.
        let recorderDeactivated: Bool
        do {
            _ = try await rideRecordings.activate(user: nil)
            recorderDeactivated = true
        } catch {
            recorderDeactivated = false
        }
        guard deletionAdoptionIsCurrent(record, boundary: adoptionBoundary) else {
            return
        }
        await authClient.advanceAccountBoundary()
        guard deletionAdoptionIsCurrent(record, boundary: adoptionBoundary) else {
            return
        }
        RouteMapSnapshot.SnapshotDisk.advanceAccountBoundary()
        RouteMapSnapshot.SnapshotCache.shared.removeAll()
        RemoteImageCache.shared.advanceAccountBoundary()
        let uploadFrozen: Bool
        if let recordOwner = record.owner {
            do {
                try await rideUploads.freezeForAccountDeletion(owner: recordOwner)
                uploadFrozen = true
            } catch {
                uploadFrozen = false
            }
            guard deletionAdoptionIsCurrent(record, boundary: adoptionBoundary) else {
                return
            }
            await FileFeedCache.shared.freeze(owner: recordOwner)
            guard deletionAdoptionIsCurrent(record, boundary: adoptionBoundary) else {
                return
            }
        } else {
            // With no cached or live owner there is no exact upload runtime to
            // suspend. The ownerless durable/process witness remains the
            // process-independent global admission fence.
            uploadFrozen = true
        }
        guard deletionAdoptionIsCurrent(record, boundary: adoptionBoundary) else {
            return
        }
        let shouldTearDown = durable
            && recorderDeactivated
            && uploadFrozen
            && !isAccountDeletionTeardownStarted
        if shouldTearDown { isAccountDeletionTeardownStarted = true }
        guard shouldTearDown else {
            // A failed durable write or custody fence leaves the retryable
            // recovery room and process fence in place. Credentials survive
            // when cache removal proved cold-relaunch safety; another server
            // refusal can reattempt every required boundary.
            return
        }
        isAccountDeletionTeardownExecuting = true
        defer { isAccountDeletionTeardownExecuting = false }
        await tearDownSession(
            revokeServerSession: false,
            recordingAlreadyDeactivated: true,
            expectedAccountBoundary: adoptionBoundary,
            permitsDeletionFenceAtExpectedBoundary: true
        )
    }

    private func deletionAdoptionIsCurrent(
        _ record: AccountDeletionSessionRecord,
        boundary: UInt64
    ) -> Bool {
        guard accountBoundaryGeneration == boundary,
              let selected = accountDeletionSessionRecord
        else { return false }
        return selected.recoveryID == record.recoveryID
            && selected.owner == record.owner
            && selected.state == record.state
    }

    private func preserveDetachedAccountDeletionSessionState(
        _ state: AccountDeletionSessionState,
        owner: RecordingOwner,
        refusalContext: AccountDeletionRefusalContext
    ) {
        guard accountDeletionEmergencyFenceStore.records().contains(where: {
            $0.recoveryID == refusalContext.recoveryID
        }) else {
            // Production refusal notifications are admitted only after this
            // exact durable witness is armed. Its absence means the recovery
            // slot was already retired (for example by Done), so a queued
            // callback cannot recreate it after another rider signs in.
            return
        }
        let previous = accountDeletionSessionStore.load(owner: owner)
        let advancedState = advancingDeletionState(from: previous?.state, to: state)
        let record = AccountDeletionSessionRecord(
            recoveryID: previous?.recoveryID ?? refusalContext.recoveryID,
            state: advancedState,
            owner: owner,
            savedStatusRemoved: advancedState == .deleted
                ? false
                : (previous?.savedStatusRemoved ?? false),
            localCleanupCompletedAt: previous?.localCleanupCompletedAt
        )
        AccountDeletionProcessFence.record(record)
        do {
            // Establish exact-owner durable truth first. Only then may the
            // ownerless crash witness for this notification be retired.
            try persistAccountDeletionSessionRecord(record)
            try accountDeletionEmergencyFenceStore.clearRequired(
                recoveryID: refusalContext.recoveryID
            )
            guard !accountDeletionEmergencyFenceStore.records().contains(where: {
                $0.recoveryID == refusalContext.recoveryID
            }) else {
                throw AccountDeletionCapabilityStoreError.unavailable
            }
        } catch {
            // The API normally arms this before posting. Direct/legacy event
            // sources get the same cold-process fail-closed fallback.
            try? accountDeletionEmergencyFenceStore.armRequired(
                recoveryID: refusalContext.recoveryID
            )
        }
    }

    private func persistAccountDeletionSessionRecord(
        _ record: AccountDeletionSessionRecord
    ) throws {
        try accountDeletionSessionStore.recordRequired(record)
        guard accountDeletionSessionStore.contains(record) else {
            throw AccountDeletionCapabilityStoreError.unavailable
        }
    }

    private func advancingDeletionState(
        from current: AccountDeletionSessionState?,
        to incoming: AccountDeletionSessionState
    ) -> AccountDeletionSessionState {
        guard let current else { return incoming }
        if current == .deleted || incoming == .deleted { return .deleted }
        if current == .identityUnavailable { return .identityUnavailable }
        return incoming
    }

    /// A pending/authority state may be checked by signing in again without
    /// first removing its durable writer fence. Ordinary support recovery may
    /// clear the record only after an exact live identity is established;
    /// saved-status replacement fences are never locally cancellable.
    func prepareToReauthenticateAfterAccountDeletionState() throws {
        guard accountDeletionSessionRecord != nil,
              case .none = accountDeletionCapabilityState,
              currentUser == nil,
              !isAccountDeletionTeardownExecuting
        else { throw AccountDeletionCapabilityStoreError.invalid }
        // A fresh sign-in is a new identity correlation attempt. An ownerless
        // deletion refusal from it must append its own opaque recovery slot,
        // never replace the prior room that initiated reauthentication.
        activeDeletionRefusalRecoveryID = nil
        accountDeletionReauthenticationRequested = true
        accountBoundaryGeneration &+= 1
        phase = .signedOut
    }

    /// Removing an accepted local status token must never re-enable cached
    /// writers. Persist a lighter lifecycle fence first, then the model may
    /// delete the bearer capability and route this signed-out device to
    /// support or a fresh server-authorized sign-in.
    func preserveFenceForRemovedAccountDeletionStatus(
        owner: RecordingOwner?
    ) async throws {
        let record = AccountDeletionSessionRecord(
            state: .pending,
            owner: owner,
            savedStatusRemoved: true
        )
        try persistAccountDeletionSessionRecord(record)
        accountDeletionSessionRecord = record
        accountDeletionReauthenticationRequested = false
        isAccountDeletionTeardownStarted = true
        if let owner {
            try await rideUploads.freezeForAccountDeletion(owner: owner)
            await FileFeedCache.shared.freeze(owner: owner)
        }
        await tearDownSession(revokeServerSession: false)
    }

    /// The one sign-out path. Clears in-memory session state and the cached
    /// rider snapshot; never deletes owner-bound ride custody from disk.
    private func tearDownSession(
        revokeServerSession: Bool,
        recordingAlreadyDeactivated: Bool = false,
        expectedAccountBoundary: UInt64? = nil,
        permitsDeletionFenceAtExpectedBoundary: Bool = false
    ) async {
        if let expectedAccountBoundary,
           !tearDownBoundaryIsCurrent(
               expectedAccountBoundary,
               permitsDeletionFence: permitsDeletionFenceAtExpectedBoundary
           ) {
            return
        }
        // Owner isolation: one session's cached reads never outlive it.
        await MainActor.run { ResponseCache.shared.clear() }
        if let expectedAccountBoundary,
           !tearDownBoundaryIsCurrent(
               expectedAccountBoundary,
               permitsDeletionFence: permitsDeletionFenceAtExpectedBoundary
           ) {
            return
        }
        phase = .signedOut
        accountDeletionReauthenticationRequested = false
        connectivity = .connected
        requestedRevealOwner = nil
        pendingRideReveal = nil
        pendingFinishedRideID = nil
        pendingRidePrivacyReview = nil
        pendingInterruptedRide = nil
        interruptedRideActionIntent = nil
        localSavedRides = nil
        interruptedRideErrorMessage = nil
        activeOwner = nil
        deferredPrivacyReviewIDs.removeAll()
        CachedRiderStore.clear()
        if !recordingAlreadyDeactivated {
            _ = try? await rideRecordings.activate(user: nil)
            if let expectedAccountBoundary,
               !tearDownBoundaryIsCurrent(
                   expectedAccountBoundary,
                   permitsDeletionFence: permitsDeletionFenceAtExpectedBoundary
               ) {
                return
            }
        }
        await rideUploads.activate(user: nil)
        if let expectedAccountBoundary,
           !tearDownBoundaryIsCurrent(
               expectedAccountBoundary,
               permitsDeletionFence: permitsDeletionFenceAtExpectedBoundary
           ) {
            return
        }
        await PrivyAuthService.shared.logout()
        if let expectedAccountBoundary,
           !tearDownBoundaryIsCurrent(
               expectedAccountBoundary,
               permitsDeletionFence: permitsDeletionFenceAtExpectedBoundary
           ) {
            return
        }
        if revokeServerSession {
            await authClient.logout()
        } else {
            await authClient.clearLocalSession()
        }
        hasUncollectedSettlements = false
        balanceActions = .unavailable
    }

    private func tearDownBoundaryIsCurrent(
        _ boundary: UInt64,
        permitsDeletionFence: Bool
    ) -> Bool {
        guard accountBoundaryGeneration == boundary else { return false }
        return permitsDeletionFence || permitsAccountWork(at: boundary)
    }

    func refreshRideUploads() async {
        guard let user = currentUser else { return }
        await resumeOwnerServices(for: user)
    }

    private func resumeOwnerServices(for user: User) async {
        let owner = RecordingOwner(user: user)
        let boundary = accountBoundaryGeneration
        guard permitsAccountWork(at: boundary), currentRecordingOwner == owner else { return }
        guard !accountDeletionSessionRecordFences(owner) else {
            _ = try? await rideRecordings.activate(user: nil)
            await rideUploads.activate(user: nil)
            activeOwner = nil
            return
        }
        switch accountDeletionCapabilityState {
        case .none:
            await FileFeedCache.shared.unfreeze(owner: owner)
            guard permitsAccountWork(at: boundary), currentRecordingOwner == owner else { return }
            break
        case let .available(capability), let .unconfirmed(capability):
            if let fencedOwner = capability.owner, fencedOwner != owner {
                await FileFeedCache.shared.unfreeze(owner: owner)
                guard permitsAccountWork(at: boundary), currentRecordingOwner == owner else { return }
                break
            }
            _ = try? await rideRecordings.activate(user: nil)
            try? await rideUploads.freezeForAccountDeletion(owner: owner)
            return
        case .unavailable:
            _ = try? await rideRecordings.activate(user: nil)
            await rideUploads.activate(user: nil)
            return
        }
        if activeOwner != owner {
            activeOwner = owner
            requestedRevealOwner = nil
            pendingRideReveal = nil
            pendingFinishedRideID = nil
            pendingRidePrivacyReview = nil
            pendingInterruptedRide = nil
            interruptedRideActionIntent = nil
            localSavedRides = nil
            interruptedRideErrorMessage = nil
            deferredPrivacyReviewIDs.removeAll()
        }
        await rideUploads.activate(user: user)
        guard permitsAccountWork(at: boundary), currentRecordingOwner == owner else { return }
        let custodyAvailable = await refreshRecordingCustody(for: user, owner: owner)
        guard permitsAccountWork(at: boundary), currentRecordingOwner == owner else { return }
        if custodyAvailable,
           pendingInterruptedRide == nil,
           interruptedRideErrorMessage == nil,
           pendingRidePrivacyReview == nil
        {
            let selected = await rideUploads.pendingPrivacyReview(
                owner: owner,
                excluding: deferredPrivacyReviewIDs
            )
            guard permitsAccountWork(at: boundary),
                  currentRecordingOwner == owner,
                  activeOwner == owner
            else { return }
            if let selected,
               selected.ownerID == owner.id,
               selected.ownerWallet == owner.wallet,
               selected.phase == .awaitingPrivacyReview
            {
                pendingRidePrivacyReview = selected
            }
        }
        guard permitsAccountWork(at: boundary), currentRecordingOwner == owner else { return }
        await rideUploads.reconcileAll(owner: owner)
        guard permitsAccountWork(at: boundary), currentRecordingOwner == owner else { return }
        if custodyAvailable,
           pendingInterruptedRide == nil,
           interruptedRideErrorMessage == nil,
           pendingRidePrivacyReview == nil
        {
            await selectNextRideReveal(owner: owner)
        }
        guard currentRecordingOwner == owner else { return }
        lastImportCompletedAt = .now
    }

    private func permitsAccountWork(at boundary: UInt64) -> Bool {
        guard accountBoundaryGeneration == boundary else { return false }
        let owner = accountRoutingOwner
        guard !accountDeletionSessionRecordFences(owner) else { return false }
        switch accountDeletionCapabilityState {
        case .none:
            return true
        case .unavailable:
            return false
        case let .available(capability):
            guard let fencedOwner = capability.owner else { return false }
            guard let owner else { return false }
            return owner != fencedOwner
        case let .unconfirmed(capability):
            // A pair written before DELETE is deliberately provisional. With
            // no 401 journal, cold-start authentication must be allowed to
            // recover into the already-fenced account surface.
            if let fencedOwner = capability.owner,
               currentRecordingOwner == nil,
               !accountDeletionSessionRecordFences(fencedOwner) {
                return true
            }
            guard let fencedOwner = capability.owner else { return false }
            guard let owner else { return true }
            return owner != fencedOwner
        }
    }

    func presentRidePrivacyReview(_ job: RideUploadJob) {
        let boundary = accountBoundaryGeneration
        guard permitsAccountWork(at: boundary),
              let owner = currentRecordingOwner,
              activeOwner == owner,
              job.ownerID == owner.id,
              job.ownerWallet == owner.wallet,
              job.phase == .awaitingPrivacyReview,
              pendingInterruptedRide == nil,
              interruptedRideErrorMessage == nil
        else { return }
        deferredPrivacyReviewIDs.remove(job.id)
        pendingRidePrivacyReview = job
    }

    func deferRidePrivacyReview(_ job: RideUploadJob) {
        let boundary = accountBoundaryGeneration
        guard permitsAccountWork(at: boundary),
              pendingRidePrivacyReview?.id == job.id
        else { return }
        deferredPrivacyReviewIDs.insert(job.id)
        pendingRidePrivacyReview = nil
        if let owner = currentRecordingOwner {
            Task { await selectNextRideReveal(owner: owner) }
        }
    }

    func approveRidePublication(
        _ job: RideUploadJob,
        settings: RidePublicationSettings,
        draft: RidePostRideDraft = .empty,
        photoBytes: [String: Data] = [:]
    ) async throws {
        let boundary = accountBoundaryGeneration
        guard permitsAccountWork(at: boundary),
              let owner = currentRecordingOwner,
              activeOwner == owner,
              job.ownerID == owner.id,
              job.ownerWallet == owner.wallet,
              pendingRidePrivacyReview?.id == job.id
        else { throw RideUploadStoreError.invalidOwner }
        try await rideUploads.approvePublication(
            jobID: job.id,
            owner: owner,
            settings: settings,
            draft: draft,
            photoBytes: photoBytes
        )
        guard permitsAccountWork(at: boundary),
              let user = currentUser,
              RecordingOwner(user: user) == owner,
              activeOwner == owner
        else {
            throw RideUploadStoreError.invalidOwner
        }
        deferredPrivacyReviewIDs.remove(job.id)
        pendingRidePrivacyReview = nil
        lastImportCompletedAt = .now
    }

    func saveInterruptedRide(_ recovery: InterruptedRideRecovery) async throws {
        let boundary = accountBoundaryGeneration
        guard permitsAccountWork(at: boundary),
              let user = currentUser,
              let owner = currentRecordingOwner,
              activeOwner == owner,
              owner.id == recovery.ownerID,
              pendingInterruptedRide == recovery,
              interruptedRideActionIntent != .discard
        else { throw LiveRideCustodyError.ownerMismatch }
        let finalized = try await rideRecordings.saveRecovery(recovery)
        guard permitsAccountWork(at: boundary),
              currentRecordingOwner == owner,
              activeOwner == owner,
              pendingInterruptedRide == recovery
        else { throw LiveRideCustodyError.ownerMismatch }
        if !finalized.uploadEligible {
            let saved = try await rideRecordings.localSavedRides(user: user)
            guard permitsAccountWork(at: boundary),
                  currentRecordingOwner == owner,
                  activeOwner == owner,
                  pendingInterruptedRide == recovery
            else { throw LiveRideCustodyError.ownerMismatch }
            localSavedRides = saved
        }
        pendingInterruptedRide = nil
        interruptedRideErrorMessage = nil
        lastImportCompletedAt = .now
    }

    func discardInterruptedRide(_ recovery: InterruptedRideRecovery) async throws {
        let boundary = accountBoundaryGeneration
        guard permitsAccountWork(at: boundary),
              let owner = currentRecordingOwner,
              activeOwner == owner,
              owner.id == recovery.ownerID,
              pendingInterruptedRide == recovery
        else { throw LiveRideCustodyError.ownerMismatch }
        interruptedRideActionIntent = .discard
        try await rideRecordings.discard(recovery)
        guard permitsAccountWork(at: boundary),
              currentRecordingOwner == owner,
              activeOwner == owner,
              pendingInterruptedRide == recovery
        else { throw LiveRideCustodyError.ownerMismatch }
        pendingInterruptedRide = nil
        interruptedRideActionIntent = nil
        interruptedRideErrorMessage = nil
        lastImportCompletedAt = .now
    }

    func retryInterruptedRideRecovery() async {
        guard let user = currentUser else { return }
        await resumeOwnerServices(for: user)
    }

    /// The empty-ride End acknowledgment (bead c6l2l item 5): the rider
    /// acknowledged that a zero-sample recording holds nothing, so its
    /// finalized-but-ineligible custody record is discarded and local
    /// custody refreshes so no saved-ride card appears.
    func discardEmptyRecording(_ finalized: FinalizedRecording) async throws {
        let boundary = accountBoundaryGeneration
        guard permitsAccountWork(at: boundary),
              let owner = currentRecordingOwner,
              owner.id == finalized.ownerID
        else {
            throw LiveRideCustodyError.ownerMismatch
        }
        try await rideRecordings.discardFinalizedLocalRecording(finalized)
        guard permitsAccountWork(at: boundary), currentRecordingOwner == owner else {
            throw LiveRideCustodyError.ownerMismatch
        }
        try await refreshLocalRideCustody()
    }

    /// The local evidence for one saved-on-device ride, owner-pinned.
    func localSavedRideEvidence(_ ride: LocalSavedRide) async throws -> LocalSavedRideEvidence {
        let boundary = accountBoundaryGeneration
        guard permitsAccountWork(at: boundary),
              let user = currentUser,
              user.id == ride.ownerID
        else {
            throw LiveRideCustodyError.ownerMismatch
        }
        let evidence = try await rideRecordings.localSavedRideEvidence(
            user: user,
            rideID: ride.id
        )
        guard permitsAccountWork(at: boundary), currentUser?.id == ride.ownerID else {
            throw LiveRideCustodyError.ownerMismatch
        }
        return evidence
    }

    /// Delete one saved-on-device ride through the owner-safe discard saga,
    /// then re-read custody so the feed reflects the durable outcome.
    func discardLocalSavedRide(
        _ ride: LocalSavedRide,
        artifact: RecordingFinalArtifact
    ) async throws {
        let boundary = accountBoundaryGeneration
        guard permitsAccountWork(at: boundary),
              let user = currentUser,
              user.id == ride.ownerID
        else {
            throw LiveRideCustodyError.ownerMismatch
        }
        try await rideRecordings.discardFinalizedLocalRecording(FinalizedRecording(
            id: ride.id,
            ownerID: ride.ownerID,
            gpxBytes: artifact.gpxBytes,
            fileHash: artifact.fileHash,
            preliminaryRideHash: artifact.preliminaryRideHash,
            parserVersion: artifact.parserVersion,
            uploadJobID: nil,
            uploadEligible: false
        ))
        guard permitsAccountWork(at: boundary), currentUser?.id == ride.ownerID else {
            throw LiveRideCustodyError.ownerMismatch
        }
        try await refreshLocalRideCustody()
    }

    func refreshLocalRideCustody() async throws {
        let boundary = accountBoundaryGeneration
        guard permitsAccountWork(at: boundary), let user = currentUser else {
            throw LiveRideCustodyError.ownerMismatch
        }
        let owner = RecordingOwner(user: user)
        let available = await refreshRecordingCustody(for: user, owner: owner)
        guard permitsAccountWork(at: boundary), currentRecordingOwner == owner else {
            throw LiveRideCustodyError.ownerMismatch
        }
        guard available else {
            throw LiveRideCustodyError.corruptEvidence
        }
    }

    /// Production exit seam for recording custody. Suspension completes before
    /// the exact signed-in owner refreshes recovery, so dismissing the recorder
    /// cannot leave a hidden row that wedges the next Record attempt.
    func suspendRecordingAndRefresh(
        _ suspend: () async throws -> Void,
        onSuccess: () -> Void = {}
    ) async throws {
        let boundary = accountBoundaryGeneration
        guard permitsAccountWork(at: boundary), let owner = currentRecordingOwner else {
            throw LiveRideCustodyError.ownerMismatch
        }
        try await suspend()
        guard permitsAccountWork(at: boundary), currentRecordingOwner == owner else {
            throw LiveRideCustodyError.ownerMismatch
        }
        try await refreshLocalRideCustody()
        guard permitsAccountWork(at: boundary), currentRecordingOwner == owner else {
            throw LiveRideCustodyError.ownerMismatch
        }
        onSuccess()
    }

    private func refreshRecordingCustody(
        for user: User,
        owner: RecordingOwner
    ) async -> Bool {
        let boundary = accountBoundaryGeneration
        guard permitsAccountWork(at: boundary), currentRecordingOwner == owner else {
            return false
        }
        do {
            let interrupted = try await rideRecordings.activate(user: user)
            guard permitsAccountWork(at: boundary), currentRecordingOwner == owner else {
                return false
            }
            let saved = try await rideRecordings.localSavedRides(user: user)
            guard permitsAccountWork(at: boundary), currentRecordingOwner == owner else {
                return false
            }
            interruptedRideErrorMessage = nil
            let previousInterruptedRide = pendingInterruptedRide
            pendingInterruptedRide = interrupted
            if interrupted == nil || interrupted?.id != previousInterruptedRide?.id {
                interruptedRideActionIntent = nil
            }
            localSavedRides = saved
            return true
        } catch {
            guard permitsAccountWork(at: boundary), currentRecordingOwner == owner else {
                return false
            }
            // Diagnostic identity of the real failure (the rider-facing
            // message stays generic; the console keeps the cause).
            print("[Custody] refresh failed: \(error)")
            interruptedRideErrorMessage = LiveRideCustodyError.corruptEvidence.localizedDescription
            return false
        }
    }

    /// Coalesces scene, import, and foreground refreshes into one reveal
    /// selection. A request arriving while selection is suspended is handled
    /// by the active selector, which rechecks the signed-in owner before and
    /// after touching the persisted owner-bound reveal queue.
    private func selectNextRideReveal(owner: RecordingOwner) async {
        let boundary = accountBoundaryGeneration
        guard permitsAccountWork(at: boundary), currentRecordingOwner == owner else { return }
        requestedRevealOwner = owner
        guard !isSelectingRideReveal else { return }

        isSelectingRideReveal = true
        defer { isSelectingRideReveal = false }

        while let requestedOwner = requestedRevealOwner {
            self.requestedRevealOwner = nil
            guard permitsAccountWork(at: boundary),
                  currentRecordingOwner == requestedOwner,
                  pendingRideReveal == nil,
                  pendingRidePrivacyReview == nil
            else {
                continue
            }

            let selected = await rideUploads.claimNextReveal(owner: requestedOwner)
            guard permitsAccountWork(at: boundary),
                  currentRecordingOwner == requestedOwner,
                  pendingRideReveal == nil,
                  pendingRidePrivacyReview == nil
            else {
                continue
            }
            pendingRideReveal = selected
            if let selected { Self.warmRevealedRide(selected.authoritativeRideID) }
        }
    }

    /// The reveal's "View Ride" is the most certain tap in the app: warm the
    /// full ride page (detail, map, climbs, owner streams) the moment the
    /// ceremony is claimed, so the handoff paints from cache (grout pass).
    nonisolated private static func warmRevealedRide(_ rideID: String) {
        Task.detached(priority: .utility) {
            _ = try? await APIClient.shared.rideDetail(id: rideID)
            _ = try? await APIClient.shared.ridePatterns(id: rideID)
            _ = try? await APIClient.shared.rideGps(id: rideID)
            for kind in RideStreamKind.allCases {
                _ = try? await APIClient.shared.rideStream(id: rideID, kind: kind)
            }
        }
    }

    /// The reveal stays claimed and visible until the explicit Done action is
    /// durably acknowledged. A failed write, sign-out, or owner change leaves
    /// it recoverable for the original owner on a later open.
    func acknowledgePendingRideReveal(_ pending: PendingRideReveal, openRide: Bool = true) async {
        let boundary = accountBoundaryGeneration
        guard permitsAccountWork(at: boundary),
              !isAcknowledgingRideReveal,
              let owner = currentRecordingOwner,
              activeOwner == owner,
              owner.id == pending.ownerID,
              pendingRideReveal == pending
        else { return }

        isAcknowledgingRideReveal = true
        defer { isAcknowledgingRideReveal = false }

        guard await rideUploads.acknowledgeReveal(pending, owner: owner),
              permitsAccountWork(at: boundary),
              currentRecordingOwner == owner,
              activeOwner == owner,
              pendingRideReveal == pending
        else { return }

        pendingRideReveal = nil
        pendingFinishedRideID = openRide ? pending.authoritativeRideID : nil
        lastImportCompletedAt = .now
    }

    // MARK: Sign-in flows

    /// Email OTP through Privy, then backend verify.
    func confirmEmailCode(_ code: String, email: String, inviteCode: String?) async throws {
        let material = try await PrivyAuthService.shared.loginWithEmailCode(code, sentTo: email)
        _ = try await APIClient.shared.verifyPrivyToken(
            wallet: material.wallet, privyToken: material.token, inviteCode: inviteCode
        )
        try await completeSignIn()
    }

    func signInWithApple(inviteCode: String?) async throws {
        let material = try await PrivyAuthService.shared.loginWithApple()
        _ = try await APIClient.shared.verifyPrivyToken(
            wallet: material.wallet, privyToken: material.token, inviteCode: inviteCode
        )
        try await completeSignIn()
    }

    #if DEBUG
    /// Developer sign-in: the backend's SIWS wallet flow with a local key.
    /// A real production auth path — used because agent-run simulators have
    /// no inbox for email OTP. DEBUG builds only.
    func devSignIn() async throws {
        let wallet = SIWS.loadOrCreateWallet()
        let address = wallet.address
        let nonce = try await APIClient.shared.nonce(wallet: address)
        let signature = try SIWS.sign(message: nonce.message, with: wallet)
        _ = try await APIClient.shared.verifySignature(
            wallet: address,
            signature: signature,
            nonce: nonce.nonce,
            inviteCode: AppConfig.devInviteCode
        )
        try await completeSignIn()
    }
    #endif

    // MARK: Settlement dot

    func refreshBalanceActions() async {
        let status = try? await APIClient.shared.systemStatus()
        balanceActions = BalanceActionAvailability(status: status)
        // A failed read adopts nothing; the policy's bounded cache decays
        // stale verdicts to unknown on its own (L3.04).
        if let status {
            MobileCapabilityStore.shared.adopt(block: status.mobileCapabilities)
            BRLog.session.log("status read adopted; capabilities refreshed")
        } else {
            BRLog.session.log("status read failed; capability cache unchanged")
        }
    }

    func refreshSettlementDot() async {
        // Uncollected DUNG = pending rewards across the rider's stakes.
        hasUncollectedSettlements = (await Self.uncollectedTotal()).map { $0 > 0 }
    }

    /// Sum of pending DUNG across every position. Any unavailable position,
    /// identity, or reward read keeps the aggregate unavailable.
    static func uncollectedTotal(policy: CachePolicy = .network) async -> Double? {
        guard let total = await SettlementTruth.uncollectedTotal(policy: policy) else { return nil }
        return NSDecimalNumber(decimal: total).doubleValue
    }
}
