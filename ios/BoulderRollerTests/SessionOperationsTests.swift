import Foundation
import Security
import XCTest
@testable import BoulderRoller

/// Session operations (bead `boulderroller-v2-f4acp.2.9`): a stored session
/// dies only on the server's word, offline relaunches resume to the rider's
/// cached state, forced logout is one clean sign-out with custody preserved,
/// and device-clock skew can never veto a request or kill a session.
///
/// The resume-ladder tests are the regression net for the note-11 symptom
/// (bead `c6l2l`): relaunch after a process kill landed on onboarding even
/// though re-auth succeeded. Pre-fix, `testTransientResumeFailure…` and
/// `testRotatedRefresh…` fail against the old always-clear resume path.
final class SessionOperationsTests: XCTestCase {

    override func setUp() {
        super.setUp()
        SessionEndReasonStore.clear()
        AccountDeletionSessionRecordStore.clear()
        CachedRiderStore.clear()
    }

    override func tearDown() {
        SessionEndReasonStore.clear()
        AccountDeletionSessionRecordStore.clear()
        CachedRiderStore.clear()
        super.tearDown()
    }

    // MARK: - Refresh failure classification (server truth only)

    func testDefinitiveAuthCodesEndTheSession() {
        XCTAssertEqual(
            SessionRefreshClassifier.classify(
                APIError.http(status: 401, code: "refresh_expired", message: nil)
            ),
            .rejected(.expired)
        )
        XCTAssertEqual(
            SessionRefreshClassifier.classify(
                APIError.http(status: 401, code: "refresh_revoked", message: nil)
            ),
            .rejected(.revokedByServer)
        )
        XCTAssertEqual(
            SessionRefreshClassifier.classify(
                APIError.http(status: 401, code: "refresh_reuse_detected", message: nil)
            ),
            .rejected(.revokedByServer)
        )
    }

    /// A 409 `refresh_rotated` means the newer token is gone with a killed
    /// process — honest expiry, not a retry loop and not a transient.
    func testRotatedRefreshIsHonestExpiryNotRetryLoop() {
        XCTAssertEqual(
            SessionRefreshClassifier.classify(
                APIError.http(status: 409, code: "refresh_rotated", message: nil)
            ),
            .rejected(.expired)
        )
    }

    func testNetworkAndServerWeatherIsTransient() {
        XCTAssertEqual(
            SessionRefreshClassifier.classify(URLError(.notConnectedToInternet)),
            .transient
        )
        XCTAssertEqual(
            SessionRefreshClassifier.classify(URLError(.timedOut)),
            .transient
        )
        XCTAssertEqual(
            SessionRefreshClassifier.classify(
                APIError.http(status: 502, code: nil, message: "bad gateway")
            ),
            .transient
        )
        XCTAssertEqual(
            SessionRefreshClassifier.classify(
                APIError.http(status: 429, code: "rate_limited", message: nil)
            ),
            .transient
        )
    }

    /// An anonymous 401 (no backend code) is an intermediary artifact, not
    /// the auth route's judgment — the session survives it.
    func testAnonymous401DoesNotEndTheSession() {
        XCTAssertEqual(
            SessionRefreshClassifier.classify(
                APIError.http(status: 401, code: nil, message: nil)
            ),
            .transient
        )
    }

    func testAccountDeletion401sAreDefinitiveServerAccountStates() {
        for code in [
            "account_deletion_pending",
            "account_deleted",
            "account_identity_unavailable",
        ] {
            XCTAssertEqual(
                SessionRefreshClassifier.classify(
                    APIError.http(status: 401, code: code, message: nil)
                ),
                .accountDeletion(AccountDeletionSessionState(rawValue: code)!),
                "\(code) must leave the zombie-session path"
            )
        }
    }

    func testDeletionRootScopesAcceptedOwnerAndPrefersTokenRecoveryOver401Screen() {
        let owner = RecordingOwner(id: "deleting-rider", wallet: "deleting-wallet")
        let other = RecordingOwner(id: "other-rider", wallet: "other-wallet")
        let capability = AccountDeletionCapability(
            requestID: "11111111-1111-4111-8111-111111111111",
            statusToken: String(repeating: "a", count: 43),
            owner: owner,
            inventoryDigest: AccountDeletionLocalInventory.empty.digest,
            acknowledgedRideIDs: [],
            unuploadedRidesAcknowledged: true,
            createdAt: Date(timeIntervalSince1970: 1_777_000_000),
            localCleanupCompletedAt: nil
        )
        let record = AccountDeletionSessionRecord(state: .pending, owner: owner)

        XCTAssertEqual(
            AccountDeletionRootDestination.resolve(
                storage: .unconfirmed(capability),
                sessionRecord: record,
                signedInOwner: nil
            ),
            .lifecycle,
            "a deletion 401 must not hide the still-usable status token"
        )
        XCTAssertEqual(
            AccountDeletionRootDestination.resolve(
                storage: .unconfirmed(capability),
                sessionRecord: nil,
                signedInOwner: nil
            ),
            .account,
            "a merely provisional pair must not lock the app root"
        )
        XCTAssertEqual(
            AccountDeletionRootDestination.resolve(
                storage: .available(capability),
                sessionRecord: nil,
                signedInOwner: other
            ),
            .account,
            "one rider's bearer cannot take over another signed-in rider's root"
        )
        XCTAssertEqual(
            AccountDeletionRootDestination.resolve(
                storage: .available(capability),
                sessionRecord: nil,
                signedInOwner: owner
            ),
            .lifecycle
        )
        XCTAssertFalse(
            AccountDeletionLocalFence.permitsAccountWork(
                owner: owner,
                sessionRecord: nil,
                capabilityState: .available(capability)
            )
        )
        XCTAssertTrue(
            AccountDeletionLocalFence.permitsAccountWork(
                owner: other,
                sessionRecord: nil,
                capabilityState: .available(capability)
            ),
            "the deleting owner remains fenced without globally fencing another rider"
        )
        XCTAssertEqual(
            AccountDeletionRootDestination.resolve(
                storage: .none,
                sessionRecord: record,
                signedInOwner: other
            ),
            .account,
            "one rider's durable recovery record cannot take over another rider's root"
        )
    }

    @MainActor
    func testExactDeletion401JournalWinsOverAnotherOwnersRetainedCapability() throws {
        let ownerA = RecordingOwner(id: "retained-capability-owner", wallet: "retained-capability-wallet")
        let riderB = sessionRider(id: "journal-owner")
        let ownerB = RecordingOwner(user: riderB)
        let capabilityA = AccountDeletionCapability(
            requestID: "11111111-1111-4111-8111-111111111111",
            statusToken: String(repeating: "a", count: 43),
            owner: ownerA,
            inventoryDigest: AccountDeletionLocalInventory.empty.digest,
            acknowledgedRideIDs: [],
            unuploadedRidesAcknowledged: true,
            createdAt: Date(timeIntervalSince1970: 1_777_000_000),
            localCleanupCompletedAt: nil
        )
        let recordB = AccountDeletionSessionRecord(state: .deleted, owner: ownerB)
        try AccountDeletionSessionRecordStore.recordRequired(recordB)
        CachedRiderStore.save(riderB)

        let session = AppSession(
            rideUploads: SessionUploadRuntimeNoop(),
            rideRecordings: SessionRecordingRuntimeSpy(),
            authClient: AuthClientFake(resumeOutcomes: []),
            accountDeletionCapabilityStore: SessionDeletionCapabilityStore(
                capability: capabilityA
            )
        )

        XCTAssertEqual(session.accountDeletionCapabilityState, .none)
        XCTAssertEqual(session.accountDeletionSessionRecord, recordB)
        XCTAssertEqual(
            AccountDeletionRootDestination.resolve(
                storage: session.accountDeletionCapabilityState,
                sessionRecord: session.accountDeletionSessionRecord,
                signedInOwner: session.accountRoutingOwner
            ),
            .deletionSession
        )
    }

    @MainActor
    func testColdStartCapabilityForOwnerADoesNotLockOutCachedOwnerB() async {
        let deletingOwner = RecordingOwner(
            id: "deleting-rider",
            wallet: "deleting-wallet"
        )
        let cachedRider = sessionRider(id: "replacement-rider")
        let cachedOwner = RecordingOwner(user: cachedRider)
        let capability = AccountDeletionCapability(
            requestID: "11111111-1111-4111-8111-111111111111",
            statusToken: String(repeating: "a", count: 43),
            owner: deletingOwner,
            inventoryDigest: AccountDeletionLocalInventory.empty.digest,
            acknowledgedRideIDs: [],
            unuploadedRidesAcknowledged: true,
            createdAt: Date(timeIntervalSince1970: 1_777_000_000),
            localCleanupCompletedAt: nil
        )
        let store = SessionDeletionCapabilityStore(capability: capability)
        let auth = AuthClientFake(
            resumeOutcomes: [.resumed],
            meResults: [.success(cachedRider)]
        )
        CachedRiderStore.save(cachedRider)
        let session = AppSession(
            rideUploads: SessionUploadRuntimeNoop(),
            rideRecordings: SessionRecordingRuntimeSpy(),
            authClient: auth,
            accountDeletionCapabilityStore: store
        )

        await session.resume()

        XCTAssertEqual(session.accountRoutingOwner, cachedOwner)
        XCTAssertEqual(
            AccountDeletionRootDestination.resolve(
                storage: session.accountDeletionCapabilityState,
                sessionRecord: session.accountDeletionSessionRecord,
                signedInOwner: cachedOwner
            ),
            .account
        )
        XCTAssertEqual(session.currentUser?.id, cachedRider.id)
        XCTAssertEqual(store.load(), .available(capability))
        let resumeCallCount = await auth.resumeCallCount
        XCTAssertEqual(resumeCallCount, 1)
    }

    @MainActor
    func testSignedInOwnerBDeletionPreflightCannotInventoryRetainedJournalOwnerA() async throws {
        let ownerA = RecordingOwner(
            id: "retained-journal-owner",
            wallet: "retained-journal-wallet"
        )
        let riderB = sessionRider(id: "signed-in-inventory-owner")
        let ownerB = RecordingOwner(user: riderB)
        let retainedA = AccountDeletionSessionRecord(state: .pending, owner: ownerA)
        try AccountDeletionSessionRecordStore.recordRequired(retainedA)
        CachedRiderStore.save(riderB)

        let custodyB = AccountDeletionCustodyRecord(
            rideID: "owner-b-local-ride",
            uploadJobID: "owner-b-local-job",
            startedAt: Date(timeIntervalSince1970: 1_777_000_000),
            handedOff: false
        )
        let recordings = SessionRecordingRuntimeSpy(
            deletionRecordsByOwner: [ownerA: [], ownerB: [custodyB]]
        )
        let uploads = DeletionFreezeUploadRuntimeSpy(
            deletionRecordsByOwner: [ownerA: [], ownerB: []]
        )
        let capabilityStore = SessionDeletionCapabilityStore(capability: nil)
        let session = AppSession(
            rideUploads: uploads,
            rideRecordings: recordings,
            authClient: AuthClientFake(
                resumeOutcomes: [.resumed],
                meResults: [.success(riderB)]
            ),
            accountDeletionCapabilityStore: capabilityStore
        )
        await session.resume()

        let service = SessionDeletionServiceSpy()
        let model = AccountDeletionModel(
            service: service,
            capabilityStore: capabilityStore,
            inventory: {
                try await session.accountDeletionInventory(owner: ownerB)
            },
            localCleanup: { _, _ in
                XCTFail("a new request cannot perform local cleanup")
            },
            capabilityDidChange: {
                try await session.accountDeletionCapabilityDidChange(
                    expectedOwner: ownerB
                )
            }
        )

        await model.load(owner: ownerB)
        guard case let .ready(_, inventoryB) = model.state else {
            return XCTFail("owner B's deletion room must load B's exact inventory")
        }
        XCTAssertEqual(inventoryB.rides.map(\.id), [custodyB.uploadJobID])

        await model.requestDeletion(
            owner: ownerB,
            reviewedInventoryDigest: AccountDeletionLocalInventory.empty.digest,
            unuploadedRidesAcknowledged: true
        )
        var createCallCount = await service.createCallCount
        XCTAssertEqual(
            createCallCount,
            0,
            "owner A's empty inventory cannot authorize deletion for owner B"
        )

        await model.requestDeletion(
            owner: ownerB,
            reviewedInventoryDigest: inventoryB.digest,
            unuploadedRidesAcknowledged: true
        )
        createCallCount = await service.createCallCount
        XCTAssertEqual(createCallCount, 1)
        let createdCapabilities = await service.createdCapabilities
        XCTAssertEqual(createdCapabilities.first?.acknowledgedRideIDs, [custodyB.uploadJobID])

        do {
            _ = try await session.accountDeletionInventory(owner: ownerA)
            XCTFail("a signed-in owner B session must reject owner A's inventory")
        } catch {}
        let recordingOwners = await recordings.deletionInventoryOwners
        let uploadOwners = await uploads.deletionInventoryOwners
        XCTAssertFalse(recordingOwners.isEmpty)
        XCTAssertFalse(uploadOwners.isEmpty)
        XCTAssertTrue(recordingOwners.allSatisfy { $0 == ownerB })
        XCTAssertTrue(uploadOwners.allSatisfy { $0 == ownerB })
        XCTAssertTrue(AccountDeletionSessionRecordStore.records().contains(retainedA))
    }

    @MainActor
    func testDeletion401ResumePreservesCustodyAndPersistsExactLifecycleState() async {
        for state in [
            AccountDeletionSessionState.pending,
            .deleted,
            .identityUnavailable,
        ] {
            AccountDeletionSessionRecordStore.clear()
            let rider = sessionRider(id: "deletion-401-\(state.rawValue)")
            let owner = RecordingOwner(user: rider)
            let recoveryID = "resume-\(state.rawValue)"
            CachedRiderStore.save(rider)
            let recordings = SessionRecordingRuntimeSpy()
            let uploads = DeletionFreezeUploadRuntimeSpy()
            let auth = AuthClientFake(
                resumeOutcomes: [.accountDeletion(state)],
                deletionRefusalContext: AccountDeletionRefusalContext(
                    recoveryID: recoveryID,
                    attemptedOwner: owner,
                    attemptedWallet: nil
                ),
                armDeletionRecoveryIDOnResume: recoveryID
            )
            let session = AppSession(
                rideUploads: uploads,
                rideRecordings: recordings,
                authClient: auth,
                accountDeletionCapabilityStore: SessionDeletionCapabilityStore(
                    capability: nil
                )
            )

            await session.resume()

            guard case .signedOut = session.phase else {
                return XCTFail("a deletion lifecycle refusal cannot resume account work")
            }
            let expected = AccountDeletionSessionRecord(
                recoveryID: recoveryID,
                state: state,
                owner: owner
            )
            XCTAssertEqual(session.accountDeletionSessionRecord, expected)
            XCTAssertEqual(AccountDeletionSessionRecordStore.pending(), expected)
            XCTAssertNil(CachedRiderStore.load())
            let discardCount = await recordings.discardCount
            let purgedOwners = await recordings.purgedOwners
            let deactivations = await recordings.deactivations
            let clearLocalCount = await auth.clearLocalCount
            XCTAssertEqual(discardCount, 0)
            XCTAssertTrue(purgedOwners.isEmpty)
            XCTAssertEqual(deactivations, 1)
            XCTAssertEqual(clearLocalCount, 1)
        }
    }

    @MainActor
    func testColdOwnerlessDeletionRefusalCannotInheritCachedRiderCleanupAuthority() async throws {
        let cachedRider = sessionRider(id: "stale-cached-owner")
        let cachedOwner = RecordingOwner(user: cachedRider)
        let recoveryID = "cold-ownerless-refusal"
        let context = AccountDeletionRefusalContext(
            recoveryID: recoveryID,
            attemptedOwner: nil,
            attemptedWallet: nil
        )
        CachedRiderStore.save(cachedRider)
        let recordings = SessionRecordingRuntimeSpy()
        let uploads = DeletionFreezeUploadRuntimeSpy()
        let auth = AuthClientFake(
            resumeOutcomes: [.accountDeletion(.deleted)],
            deletionRefusalContext: context,
            armDeletionRecoveryIDOnResume: recoveryID
        )
        let session = AppSession(
            rideUploads: uploads,
            rideRecordings: recordings,
            authClient: auth,
            accountDeletionCapabilityStore: SessionDeletionCapabilityStore(capability: nil)
        )
        await session.resume()

        let ownerless = AccountDeletionSessionRecord(
            recoveryID: recoveryID,
            state: .deleted,
            owner: nil
        )
        XCTAssertEqual(session.accountDeletionSessionRecord, ownerless)
        XCTAssertTrue(AccountDeletionSessionRecordStore.records().contains(ownerless))
        XCTAssertFalse(
            AccountDeletionSessionRecordStore.records().contains {
                $0.owner == cachedOwner
            }
        )
        XCTAssertNil(CachedRiderStore.load())
        do {
            try await session.completeLocalAccountDeletionFromSessionRecord(
                recoveryID: recoveryID,
                reviewedInventoryDigest: AccountDeletionLocalInventory.empty.digest,
                unuploadedRidesAcknowledged: true
            )
            XCTFail("an ownerless cold refusal cannot authorize cached-rider cleanup")
        } catch {}
        let recordingPurges = await recordings.purgedOwners
        let uploadPurges = await uploads.purgedOwners
        XCTAssertTrue(recordingPurges.isEmpty)
        XCTAssertTrue(uploadPurges.isEmpty)
        let resumeCallCount = await auth.resumeCallCount
        let armedDuringResume = await auth.armedDeletionRecoveryDuringResume
        XCTAssertEqual(resumeCallCount, 1)
        XCTAssertTrue(armedDuringResume)
    }

    @MainActor
    func testColdDeletionContextCannotTearDownOwnerSignedInWhileContextReadSuspends() async throws {
        let riderB = sessionRider(id: "context-race-owner-b")
        let ownerB = RecordingOwner(user: riderB)
        let recoveryID = "context-race-recovery"
        let auth = GatedDeletionRefusalContextAuthClient(
            user: riderB,
            context: AccountDeletionRefusalContext(
                recoveryID: recoveryID,
                attemptedOwner: nil,
                attemptedWallet: nil
            )
        )
        let recordings = SessionRecordingRuntimeSpy()
        let uploads = DeletionFreezeUploadRuntimeSpy()
        let session = AppSession(
            rideUploads: uploads,
            rideRecordings: recordings,
            authClient: auth,
            accountDeletionCapabilityStore: SessionDeletionCapabilityStore(capability: nil)
        )

        let resumeTask = Task { @MainActor in await session.resume() }
        await auth.waitUntilContextReadEntered()

        try await session.completeSignIn()
        let ownerBImport = URL(string: "file:///context-race-owner-b.gpx")!
        session.pendingImportURL = ownerBImport
        await auth.releaseContextRead()
        await resumeTask.value

        XCTAssertEqual(session.currentUser.map(RecordingOwner.init(user:)), ownerB)
        XCTAssertEqual(session.pendingImportURL, ownerBImport)
        XCTAssertNil(session.accountDeletionSessionRecord)
        XCTAssertEqual(CachedRiderStore.load().map(RecordingOwner.init(user:)), ownerB)
        XCTAssertTrue(
            AccountDeletionEmergencyFenceStore.records.contains {
                $0.recoveryID == recoveryID
            },
            "the stale resume callback may be dropped only after its exact recovery witness is durable"
        )
        let deactivations = await recordings.deactivations
        let frozenOwners = await uploads.frozenOwners
        let clearLocalCount = await auth.clearLocalCount
        XCTAssertEqual(deactivations, 0)
        XCTAssertTrue(frozenOwners.isEmpty)
        XCTAssertEqual(clearLocalCount, 0)
    }

    @MainActor
    func testRepeatedDeletion401AdvancesStateWithoutLosingOwnerOrRepeatingTeardown() async {
        let rider = sessionRider(id: "deletion-notification-rider")
        let owner = RecordingOwner(user: rider)
        let recoveryID = "repeated-deletion-refusal"
        let auth = AuthClientFake(resumeOutcomes: [])
        let session = AppSession(
            rideUploads: DeletionFreezeUploadRuntimeSpy(),
            rideRecordings: SessionRecordingRuntimeSpy(),
            authClient: auth,
            accountDeletionCapabilityStore: SessionDeletionCapabilityStore(
                capability: nil
            )
        )
        CachedRiderStore.save(rider)
        session.phase = .signedIn(rider)
        try? AccountDeletionEmergencyFenceStore.armRequired(recoveryID: recoveryID)

        NotificationCenter.default.post(
            name: .brAccountDeletionSessionState,
            object: auth,
            userInfo: [
                "state": AccountDeletionSessionState.pending.rawValue,
                "recovery_id": recoveryID,
                "attempted_owner_id": owner.id,
                "attempted_owner_wallet": owner.wallet,
            ]
        )
        let firstDeadline = Date().addingTimeInterval(10)
        while Date() < firstDeadline {
            if await auth.clearLocalCount == 1 { break }
            await Task.yield()
        }
        XCTAssertEqual(
            session.accountDeletionSessionRecord,
            AccountDeletionSessionRecord(state: .pending, owner: owner)
        )

        NotificationCenter.default.post(
            name: .brAccountDeletionSessionState,
            object: auth,
            userInfo: [
                "state": AccountDeletionSessionState.deleted.rawValue,
                "recovery_id": recoveryID,
                "attempted_owner_id": owner.id,
                "attempted_owner_wallet": owner.wallet,
            ]
        )
        let secondDeadline = Date().addingTimeInterval(10)
        while Date() < secondDeadline {
            if session.accountDeletionSessionRecord?.state == .deleted { break }
            await Task.yield()
        }

        let expected = AccountDeletionSessionRecord(state: .deleted, owner: owner)
        XCTAssertEqual(session.accountDeletionSessionRecord, expected)
        XCTAssertEqual(AccountDeletionSessionRecordStore.pending(), expected)
        let clearLocalCount = await auth.clearLocalCount
        XCTAssertEqual(clearLocalCount, 1, "a 401 storm must perform one teardown")
    }

    @MainActor
    func testQueuedDeletion401CannotAttachToOwnerAdoptedAfterTheRefusal() async throws {
        let riderA = sessionRider(id: "refused-owner-a")
        let ownerA = RecordingOwner(user: riderA)
        let riderB = sessionRider(id: "replacement-owner-b")
        let ownerB = RecordingOwner(user: riderB)
        let auth = AuthClientFake(resumeOutcomes: [])
        let uploads = DeletionFreezeUploadRuntimeSpy()
        let recordings = SessionRecordingRuntimeSpy()
        let session = AppSession(
            rideUploads: uploads,
            rideRecordings: recordings,
            authClient: auth,
            accountDeletionCapabilityStore: SessionDeletionCapabilityStore(
                capability: nil
            )
        )
        CachedRiderStore.save(riderA)
        session.phase = .signedIn(riderA)
        let recoveryID = "queued-owner-a-refusal"
        try AccountDeletionEmergencyFenceStore.armRequired(recoveryID: recoveryID)

        NotificationCenter.default.post(
            name: .brAccountDeletionSessionState,
            object: auth,
            userInfo: [
                "state": AccountDeletionSessionState.deleted.rawValue,
                "recovery_id": recoveryID,
                "attempted_owner_id": ownerA.id,
                "attempted_owner_wallet": ownerA.wallet,
            ]
        )
        // The observer defers work onto MainActor. Adopt B before yielding so
        // a callback that consults later session state would misattribute A's
        // authoritative refusal to B.
        CachedRiderStore.save(riderB)
        session.phase = .signedIn(riderB)
        for _ in 0..<50 { await Task.yield() }

        XCTAssertEqual(
            session.currentUser.map { RecordingOwner(user: $0) },
            ownerB
        )
        XCTAssertNil(session.accountDeletionSessionRecord)
        let exactARecord = AccountDeletionSessionRecord(
            recoveryID: recoveryID,
            state: .deleted,
            owner: ownerA
        )
        XCTAssertTrue(AccountDeletionSessionRecordStore.records().contains(exactARecord))
        XCTAssertFalse(
            AccountDeletionEmergencyFenceStore.records.contains {
                $0.recoveryID == recoveryID
            },
            "exact owner-A durable truth must replace the ownerless crash witness"
        )
        XCTAssertFalse(
            AccountDeletionSessionRecordStore.records().contains {
                $0.state == .deleted && $0.owner == ownerB
            },
            "a late owner-A refusal must never create an owner-B deletion room"
        )
        XCTAssertTrue(AccountDeletionProcessFence.records().contains(exactARecord))
        let deactivations = await recordings.deactivations
        let frozenOwners = await uploads.frozenOwners
        let clearLocalCount = await auth.clearLocalCount
        let boundaryAdvances = await auth.accountBoundaryAdvances
        XCTAssertEqual(deactivations, 0)
        XCTAssertTrue(frozenOwners.isEmpty)
        XCTAssertEqual(clearLocalCount, 0)
        XCTAssertEqual(boundaryAdvances, 0)
    }

    @MainActor
    func testRetiredRecoveryCannotResurrectAfterDoneAndDifferentOwnerSignIn() async throws {
        let ownerA = RecordingOwner(
            id: "completed-owner-a",
            wallet: "completed-wallet-a"
        )
        let riderB = sessionRider(id: "post-completion-owner-b")
        let ownerB = RecordingOwner(user: riderB)
        let recoveryID = "retired-owner-a-recovery"
        let completed = AccountDeletionSessionRecord(
            recoveryID: recoveryID,
            state: .deleted,
            owner: nil,
            localCleanupCompletedAt: Date(timeIntervalSince1970: 1_777_000_100)
        )
        let sessionStore = TestDeletionSessionRecordStore(record: completed)
        let emergencyStore = TestDeletionEmergencyFenceStore(
            recoveryIDs: [recoveryID]
        )
        let uploads = DeletionFreezeUploadRuntimeSpy()
        let recordings = SessionRecordingRuntimeSpy()
        let auth = AuthClientFake(
            resumeOutcomes: [],
            meResults: [.success(riderB)]
        )
        let session = AppSession(
            rideUploads: uploads,
            rideRecordings: recordings,
            authClient: auth,
            accountDeletionCapabilityStore: SessionDeletionCapabilityStore(capability: nil),
            accountDeletionSessionStore: sessionStore,
            accountDeletionEmergencyFenceStore: emergencyStore
        )

        try session.acknowledgeAccountDeletionSessionCompletion()
        try await session.completeSignIn()
        XCTAssertEqual(session.currentUser.map { RecordingOwner(user: $0) }, ownerB)

        NotificationCenter.default.post(
            name: .brAccountDeletionSessionState,
            object: auth,
            userInfo: [
                "state": AccountDeletionSessionState.deleted.rawValue,
                "recovery_id": recoveryID,
                "attempted_owner_id": ownerA.id,
                "attempted_owner_wallet": ownerA.wallet,
            ]
        )
        for _ in 0..<50 { await Task.yield() }

        XCTAssertNil(session.accountDeletionSessionRecord)
        XCTAssertFalse(sessionStore.loadAll().contains { $0.recoveryID == recoveryID })
        XCTAssertFalse(emergencyStore.records().contains { $0.recoveryID == recoveryID })
        XCTAssertFalse(
            AccountDeletionProcessFence.records().contains {
                $0.recoveryID == recoveryID
            }
        )
        XCTAssertEqual(session.currentUser.map { RecordingOwner(user: $0) }, ownerB)
        let deactivations = await recordings.deactivations
        let frozenOwners = await uploads.frozenOwners
        let clearLocalCount = await auth.clearLocalCount
        XCTAssertEqual(deactivations, 0)
        XCTAssertTrue(frozenOwners.isEmpty)
        XCTAssertEqual(clearLocalCount, 0)
    }

    @MainActor
    func testAuthoritativeDeletedStateSupersedesSavedStatusRemovedPresentation() async throws {
        let rider = sessionRider(id: "saved-status-completed-owner")
        let owner = RecordingOwner(user: rider)
        let savedFence = AccountDeletionSessionRecord(
            state: .pending,
            owner: owner,
            savedStatusRemoved: true
        )
        try AccountDeletionSessionRecordStore.recordRequired(savedFence)
        CachedRiderStore.save(rider)
        let auth = AuthClientFake(resumeOutcomes: [])
        let session = makeSession(auth: auth)

        NotificationCenter.default.post(
            name: .brAccountDeletionSessionState,
            object: auth,
            userInfo: ["state": AccountDeletionSessionState.deleted.rawValue]
        )
        let deadline = Date().addingTimeInterval(10)
        while Date() < deadline {
            if session.accountDeletionSessionRecord?.state == .deleted { break }
            await Task.yield()
        }

        XCTAssertEqual(
            session.accountDeletionSessionRecord,
            AccountDeletionSessionRecord(state: .deleted, owner: owner),
            "authoritative deletion completion must replace the provisional 404 label"
        )
        XCTAssertEqual(AccountDeletionSessionRecordStore.pending(), session.accountDeletionSessionRecord)
    }

    @MainActor
    func testDeletion401RequiredWriteFailurePreservesCredentialsBeforeTeardown() async {
        let rider = sessionRider(id: "deletion-fallback-rider")
        let owner = RecordingOwner(user: rider)
        let store = TestDeletionSessionRecordStore(requiredFailures: 1)
        let auth = AuthClientFake(resumeOutcomes: [])
        let recordings = SessionRecordingRuntimeSpy()
        let session = AppSession(
            rideUploads: SessionUploadRuntimeNoop(),
            rideRecordings: recordings,
            authClient: auth,
            accountDeletionCapabilityStore: SessionDeletionCapabilityStore(capability: nil),
            accountDeletionSessionStore: store
        )
        CachedRiderStore.save(rider)
        session.phase = .signedIn(rider)

        NotificationCenter.default.post(
            name: .brAccountDeletionSessionState,
            object: auth,
            userInfo: ["state": AccountDeletionSessionState.pending.rawValue]
        )
        let deadline = Date().addingTimeInterval(10)
        while Date() < deadline {
            if session.accountDeletionSessionRecord?.owner == owner,
               await recordings.deactivations == 1 {
                break
            }
            await Task.yield()
        }

        let expected = AccountDeletionSessionRecord(state: .pending, owner: owner)
        XCTAssertEqual(session.accountDeletionSessionRecord, expected)
        XCTAssertNil(store.load(), "an unflushed best-effort write is not durable truth")
        XCTAssertEqual(CachedRiderStore.load()?.id, rider.id)
        XCTAssertTrue(AccountDeletionProcessFence.records().contains(expected))
        XCTAssertFalse(
            AccountDeletionLocalFence.permitsAccountWork(
                owner: owner,
                sessionRecords: AccountDeletionProcessFence.records(),
                capabilityState: .none
            ),
            "a required-journal failure must still close same-owner process writers"
        )
        let deactivations = await recordings.deactivations
        let clearLocalCount = await auth.clearLocalCount
        XCTAssertEqual(clearLocalCount, 0, "credentials survive until required read-back succeeds")
        XCTAssertEqual(deactivations, 1, "the irreplaceable recorder stops before persistence recovery")
    }

    @MainActor
    func testDeletion401StopsRecorderAndCacheBoundaryBeforeUploadFreezeCanDrain() async {
        let rider = sessionRider(id: "deletion-freeze-order-rider")
        let owner = RecordingOwner(user: rider)
        CachedRiderStore.save(rider)
        let recordings = SessionRecordingRuntimeSpy()
        let uploads = GatedDeletionFreezeUploadRuntime()
        let auth = AuthClientFake(resumeOutcomes: [])
        let session = AppSession(
            rideUploads: uploads,
            rideRecordings: recordings,
            authClient: auth,
            accountDeletionCapabilityStore: SessionDeletionCapabilityStore(capability: nil)
        )
        session.phase = .signedIn(rider)

        NotificationCenter.default.post(
            name: .brAccountDeletionSessionState,
            object: auth,
            userInfo: ["state": AccountDeletionSessionState.pending.rawValue]
        )
        await uploads.waitUntilFreezeEntered()

        let deactivations = await recordings.deactivations
        let boundaryAdvances = await auth.accountBoundaryAdvances
        let clearBeforeRelease = await auth.clearLocalCount
        XCTAssertEqual(deactivations, 1)
        XCTAssertEqual(boundaryAdvances, 1)
        XCTAssertFalse(
            AccountDeletionLocalFence.permitsAccountWork(
                owner: owner,
                sessionRecords: AccountDeletionProcessFence.records(),
                capabilityState: .none
            )
        )
        XCTAssertEqual(clearBeforeRelease, 0)

        await uploads.releaseFreeze()
        let deadline = Date().addingTimeInterval(10)
        while Date() < deadline {
            if await auth.clearLocalCount == 1 { break }
            await Task.yield()
        }
        let clearAfterRelease = await auth.clearLocalCount
        XCTAssertEqual(clearAfterRelease, 1)
    }

    @MainActor
    func testDeletionRefusalFreezeCannotTearDownNewlyReauthenticatedOwner() async throws {
        let riderA = sessionRider(id: "freeze-refusal-owner-a")
        let ownerA = RecordingOwner(user: riderA)
        let riderB = sessionRider(id: "freeze-reauth-owner-b")
        let ownerB = RecordingOwner(user: riderB)
        let recoveryID = "freeze-refusal-recovery-a"
        let recordings = SessionRecordingRuntimeSpy()
        let uploads = GatedDeletionFreezeUploadRuntime()
        let auth = AuthClientFake(
            resumeOutcomes: [],
            meResults: [.success(riderB)]
        )
        CachedRiderStore.save(riderA)
        let session = AppSession(
            rideUploads: uploads,
            rideRecordings: recordings,
            authClient: auth,
            accountDeletionCapabilityStore: SessionDeletionCapabilityStore(capability: nil)
        )
        session.phase = .signedIn(riderA)
        try AccountDeletionEmergencyFenceStore.armRequired(recoveryID: recoveryID)

        NotificationCenter.default.post(
            name: .brAccountDeletionSessionState,
            object: auth,
            userInfo: [
                "state": AccountDeletionSessionState.pending.rawValue,
                "recovery_id": recoveryID,
                "attempted_owner_id": ownerA.id,
                "attempted_owner_wallet": ownerA.wallet,
            ]
        )
        await uploads.waitUntilFreezeEntered()

        try session.prepareToReauthenticateAfterAccountDeletionState()
        try await session.completeSignIn()
        let ownerBImport = URL(string: "file:///freeze-reauth-owner-b.gpx")!
        session.pendingImportURL = ownerBImport
        await uploads.releaseFreeze()
        try await Task.sleep(for: .milliseconds(50))

        XCTAssertEqual(session.currentUser.map(RecordingOwner.init(user:)), ownerB)
        XCTAssertEqual(CachedRiderStore.load().map(RecordingOwner.init(user:)), ownerB)
        XCTAssertEqual(session.pendingImportURL, ownerBImport)
        XCTAssertTrue(AccountDeletionSessionRecordStore.records().contains {
            $0.recoveryID == recoveryID && $0.owner == ownerA
        })
        let clearLocalCount = await auth.clearLocalCount
        let activatedUserIDs = await uploads.activatedUserIDs
        XCTAssertEqual(clearLocalCount, 0)
        XCTAssertTrue(activatedUserIDs.contains(riderB.id))
    }

    @MainActor
    func testCompletedTokenLifecycleClearsSimultaneousDeletion401BeforeDoneAndRelaunch() async throws {
        let owner = RecordingOwner(id: "completed-rider", wallet: "completed-wallet")
        let capability = AccountDeletionCapability(
            requestID: "11111111-1111-4111-8111-111111111111",
            statusToken: String(repeating: "a", count: 43),
            owner: owner,
            inventoryDigest: AccountDeletionLocalInventory.empty.digest,
            acknowledgedRideIDs: [],
            unuploadedRidesAcknowledged: true,
            createdAt: Date(timeIntervalSince1970: 1_777_000_000),
            localCleanupCompletedAt: nil
        )
        let completed = AccountDeletionStatus(
            contractVersion: AccountDeletionContract.version,
            requestID: capability.requestID,
            status: .completed,
            requestedAt: "2026-08-24T12:00:00Z",
            updatedAt: "2026-08-24T12:01:00Z",
            completedAt: "2026-08-24T12:01:00Z",
            blockers: [],
            failureCode: nil,
            retryable: false,
            attemptCount: 1
        )
        let verified = try XCTUnwrap(capability.markingServerCompletionVerified(completed))
        let capabilityStore = SessionDeletionCapabilityStore(capability: verified)
        let recoveryID = "completed-token-recovery"
        try AccountDeletionEmergencyFenceStore.armRequired(recoveryID: recoveryID)
        let sessionStore = TestDeletionSessionRecordStore(
            record: AccountDeletionSessionRecord(
                recoveryID: recoveryID,
                state: .deleted,
                owner: owner
            )
        )
        let auth = AuthClientFake(resumeOutcomes: [])
        let session = AppSession(
            rideUploads: SessionUploadRuntimeNoop(),
            rideRecordings: SessionRecordingRuntimeSpy(),
            authClient: auth,
            accountDeletionCapabilityStore: capabilityStore,
            accountDeletionSessionStore: sessionStore
        )
        let model = AccountDeletionModel(
            capabilityStore: capabilityStore,
            inventory: { .empty },
            localCleanup: { _, _ in },
            capabilityDidChange: {
                try await session.accountDeletionCapabilityDidChange(
                    expectedOwner: owner
                )
            },
            localCleanupDidComplete: { completionOwner in
                try await session.accountDeletionLocalCleanupDidComplete(owner: completionOwner)
            }
        )

        await model.load(owner: nil)

        XCTAssertEqual(model.state, .completed(completed))
        XCTAssertNil(sessionStore.load(), "verified token completion replaces the 401 journal")
        XCTAssertNil(session.accountDeletionSessionRecord)
        XCTAssertFalse(
            AccountDeletionEmergencyFenceStore.records.contains {
                $0.recoveryID == recoveryID
            },
            "the exact crash witness must retire while its rich journal is still durable"
        )

        await model.acknowledgeCompletion()

        XCTAssertEqual(model.state, .discarded)
        XCTAssertEqual(capabilityStore.load(), .none)
        XCTAssertNil(sessionStore.load())

        NotificationCenter.default.post(
            name: .brAccountDeletionSessionState,
            object: auth,
            userInfo: ["state": AccountDeletionSessionState.deleted.rawValue]
        )
        for _ in 0..<20 { await Task.yield() }
        XCTAssertNil(
            session.accountDeletionSessionRecord,
            "a queued 401 callback cannot recreate a completed room after Done"
        )

        let relaunch = AppSession(
            rideUploads: SessionUploadRuntimeNoop(),
            rideRecordings: SessionRecordingRuntimeSpy(),
            authClient: AuthClientFake(resumeOutcomes: [.noStoredSession]),
            accountDeletionCapabilityStore: capabilityStore,
            accountDeletionSessionStore: sessionStore
        )
        XCTAssertNil(relaunch.accountDeletionSessionRecord)
    }

    @MainActor
    func testEmergencyOnlyDeletionRefusalRetiresBeforeTokenDoneAndRelaunch() async throws {
        let owner = RecordingOwner(
            id: "emergency-only-completed-owner",
            wallet: "emergency-only-completed-wallet"
        )
        let capability = AccountDeletionCapability(
            requestID: "11111111-1111-4111-8111-111111111111",
            statusToken: String(repeating: "a", count: 43),
            owner: owner,
            inventoryDigest: AccountDeletionLocalInventory.empty.digest,
            acknowledgedRideIDs: [],
            unuploadedRidesAcknowledged: true,
            createdAt: Date(timeIntervalSince1970: 1_777_000_000),
            localCleanupCompletedAt: nil
        )
        let completed = AccountDeletionStatus(
            contractVersion: AccountDeletionContract.version,
            requestID: capability.requestID,
            status: .completed,
            requestedAt: "2026-08-24T12:00:00Z",
            updatedAt: "2026-08-24T12:01:00Z",
            completedAt: "2026-08-24T12:01:00Z",
            blockers: [],
            failureCode: nil,
            retryable: false,
            attemptCount: 1
        )
        let verified = try XCTUnwrap(
            capability.markingServerCompletionVerified(completed)
        )
        let capabilityStore = SessionDeletionCapabilityStore(capability: verified)
        let recoveryID = "emergency-only-completed-recovery"
        let context = AccountDeletionRefusalContext(
            recoveryID: recoveryID,
            attemptedOwner: owner,
            attemptedWallet: nil
        )
        let sessionStore = TestDeletionSessionRecordStore(record: nil)
        let emergencyStore = TestDeletionEmergencyFenceStore(
            recoveryIDs: [recoveryID]
        )
        let auth = AuthClientFake(
            resumeOutcomes: [],
            deletionRefusalContext: context
        )
        let session = AppSession(
            rideUploads: SessionUploadRuntimeNoop(),
            rideRecordings: SessionRecordingRuntimeSpy(),
            authClient: auth,
            accountDeletionCapabilityStore: capabilityStore,
            accountDeletionSessionStore: sessionStore,
            accountDeletionEmergencyFenceStore: emergencyStore
        )
        let model = AccountDeletionModel(
            capabilityStore: capabilityStore,
            inventory: { .empty },
            localCleanup: { _, _ in },
            capabilityDidChange: {
                try await session.accountDeletionCapabilityDidChange(
                    expectedOwner: owner
                )
            },
            localCleanupDidComplete: { cleanupOwner in
                try await session.accountDeletionLocalCleanupDidComplete(owner: cleanupOwner)
            }
        )

        await model.load(owner: nil)
        NotificationCenter.default.post(
            name: .brAccountDeletionSessionState,
            object: auth,
            userInfo: [
                "state": AccountDeletionSessionState.deleted.rawValue,
                "recovery_id": recoveryID,
                "attempted_owner_id": owner.id,
                "attempted_owner_wallet": owner.wallet,
            ]
        )
        for _ in 0..<20 { await Task.yield() }
        await model.acknowledgeCompletion()

        XCTAssertEqual(model.state, .discarded)
        XCTAssertEqual(capabilityStore.load(), .none)
        XCTAssertFalse(emergencyStore.records().contains {
            $0.recoveryID == recoveryID
        })
        XCTAssertFalse(sessionStore.loadAll().contains {
            $0.recoveryID == recoveryID
        })
        XCTAssertNil(session.accountDeletionSessionRecord)

        let relaunch = AppSession(
            rideUploads: SessionUploadRuntimeNoop(),
            rideRecordings: SessionRecordingRuntimeSpy(),
            authClient: AuthClientFake(resumeOutcomes: [.noStoredSession]),
            accountDeletionCapabilityStore: capabilityStore,
            accountDeletionSessionStore: sessionStore,
            accountDeletionEmergencyFenceStore: emergencyStore
        )
        XCTAssertNil(relaunch.accountDeletionSessionRecord)
    }

    @MainActor
    func testDeletion401TotalJournalFailurePreservesTokensAndCachedOwner() async {
        let rider = sessionRider(id: "deletion-journal-failure-rider")
        let store = TestDeletionSessionRecordStore(
            requiredFailures: 1,
            dropsBestEffortWrites: true
        )
        let auth = AuthClientFake(resumeOutcomes: [])
        let uploads = DeletionFreezeUploadRuntimeSpy()
        let session = AppSession(
            rideUploads: uploads,
            rideRecordings: SessionRecordingRuntimeSpy(),
            authClient: auth,
            accountDeletionCapabilityStore: SessionDeletionCapabilityStore(capability: nil),
            accountDeletionSessionStore: store
        )
        CachedRiderStore.save(rider)
        session.phase = .signedIn(rider)

        NotificationCenter.default.post(
            name: .brAccountDeletionSessionState,
            object: auth,
            userInfo: ["state": AccountDeletionSessionState.pending.rawValue]
        )
        let deadline = Date().addingTimeInterval(10)
        while Date() < deadline {
            let frozenOwners = await uploads.frozenOwners
            if !frozenOwners.isEmpty { break }
            await Task.yield()
        }

        XCTAssertNil(store.load())
        XCTAssertEqual(session.accountDeletionSessionRecord?.owner, RecordingOwner(user: rider))
        XCTAssertEqual(CachedRiderStore.load()?.id, rider.id)
        let clearLocalCount = await auth.clearLocalCount
        XCTAssertEqual(clearLocalCount, 0, "no token/cache teardown before durable fencing")
    }

    @MainActor
    func testPersistedDeletionSessionFencePreventsAnyResumeAttempt() async {
        let record = AccountDeletionSessionRecord(
            state: .pending,
            owner: RecordingOwner(id: "pending-rider", wallet: "pending-wallet")
        )
        AccountDeletionSessionRecordStore.record(record)
        let auth = AuthClientFake(resumeOutcomes: [.resumed])
        let session = makeSession(auth: auth)

        await session.resume()

        XCTAssertEqual(session.accountDeletionSessionRecord, record)
        let resumeCallCount = await auth.resumeCallCount
        XCTAssertEqual(resumeCallCount, 0)
        XCTAssertNil(session.currentUser)
    }

    @MainActor
    func testSavedStatusRemovedFenceSurvivesSameOwnerReauthentication() async throws {
        let rider = sessionRider(id: "saved-status-owner")
        let owner = RecordingOwner(user: rider)
        let record = AccountDeletionSessionRecord(
            state: .pending,
            owner: owner,
            savedStatusRemoved: true
        )
        try AccountDeletionSessionRecordStore.recordRequired(record)
        let uploads = DeletionFreezeUploadRuntimeSpy()
        let auth = AuthClientFake(
            resumeOutcomes: [],
            meResults: [.success(rider)]
        )
        let session = AppSession(
            rideUploads: uploads,
            rideRecordings: SessionRecordingRuntimeSpy(),
            authClient: auth,
            accountDeletionCapabilityStore: SessionDeletionCapabilityStore(capability: nil)
        )

        try session.prepareToReauthenticateAfterAccountDeletionState()
        do {
            try await session.completeSignIn()
            XCTFail("same-owner sign-in cannot erase a 404 replacement fence")
        } catch {}

        XCTAssertEqual(session.accountDeletionSessionRecord, record)
        XCTAssertEqual(AccountDeletionSessionRecordStore.pending(), record)
        XCTAssertFalse(
            AccountDeletionLocalFence.permitsAccountWork(
                owner: owner,
                sessionRecord: record,
                capabilityState: .none
            )
        )
        let activatedUserIDs = await uploads.activatedUserIDs
        XCTAssertFalse(activatedUserIDs.contains(rider.id))
        let clearLocalCount = await auth.clearLocalCount
        XCTAssertEqual(clearLocalCount, 1, "the rejected same-owner session must be removed")
    }

    @MainActor
    func testSavedStatusRemovedFenceAllowsDifferentOwnerWithoutDeletingFence() async throws {
        let deletingOwner = RecordingOwner(
            id: "saved-status-owner",
            wallet: "wallet-saved-status-owner"
        )
        let replacementRider = sessionRider(id: "replacement-owner")
        let replacementOwner = RecordingOwner(user: replacementRider)
        let record = AccountDeletionSessionRecord(
            state: .pending,
            owner: deletingOwner,
            savedStatusRemoved: true
        )
        try AccountDeletionSessionRecordStore.recordRequired(record)
        let uploads = DeletionFreezeUploadRuntimeSpy()
        let session = AppSession(
            rideUploads: uploads,
            rideRecordings: SessionRecordingRuntimeSpy(),
            authClient: AuthClientFake(
                resumeOutcomes: [],
                meResults: [.success(replacementRider)]
            ),
            accountDeletionCapabilityStore: SessionDeletionCapabilityStore(capability: nil)
        )

        try session.prepareToReauthenticateAfterAccountDeletionState()
        try await session.completeSignIn()

        XCTAssertEqual(session.currentUser?.id, replacementRider.id)
        XCTAssertEqual(session.accountDeletionSessionRecord, record)
        XCTAssertEqual(AccountDeletionSessionRecordStore.pending(), record)
        XCTAssertTrue(
            AccountDeletionLocalFence.permitsAccountWork(
                owner: replacementOwner,
                sessionRecord: record,
                capabilityState: .none
            )
        )
        XCTAssertFalse(
            AccountDeletionLocalFence.permitsAccountWork(
                owner: deletingOwner,
                sessionRecord: record,
                capabilityState: .none
            )
        )
        let activatedUserIDs = await uploads.activatedUserIDs
        XCTAssertTrue(activatedUserIDs.contains(replacementRider.id))
    }

    @MainActor
    func testReauthenticationChecksSignedInOwnerAcrossMultipleDeletionRecords() async throws {
        let signedInRider = sessionRider(id: "multi-record-owner-a")
        let ownerA = RecordingOwner(user: signedInRider)
        let recordA = AccountDeletionSessionRecord(
            state: .pending,
            owner: ownerA,
            savedStatusRemoved: true
        )
        let ownerB = RecordingOwner(
            id: "multi-record-owner-b",
            wallet: "multi-record-wallet-b"
        )
        let recordB = AccountDeletionSessionRecord(
            state: .pending,
            owner: ownerB,
            savedStatusRemoved: true
        )
        try AccountDeletionSessionRecordStore.recordRequired(recordA)
        try AccountDeletionSessionRecordStore.recordRequired(recordB)
        let auth = AuthClientFake(
            resumeOutcomes: [],
            meResults: [.success(signedInRider)]
        )
        let session = AppSession(
            rideUploads: DeletionFreezeUploadRuntimeSpy(),
            rideRecordings: SessionRecordingRuntimeSpy(),
            authClient: auth,
            accountDeletionCapabilityStore: SessionDeletionCapabilityStore(capability: nil)
        )
        XCTAssertEqual(session.accountDeletionSessionRecord, recordB)

        try session.prepareToReauthenticateAfterAccountDeletionState()
        do {
            try await session.completeSignIn()
            XCTFail("owner A cannot bypass A's fence while the room happens to display owner B")
        } catch {}

        XCTAssertNil(session.currentUser)
        XCTAssertEqual(session.accountDeletionSessionRecord, recordA)
        XCTAssertTrue(AccountDeletionSessionRecordStore.records().contains(recordA))
        XCTAssertTrue(AccountDeletionSessionRecordStore.records().contains(recordB))
        let clearLocalCount = await auth.clearLocalCount
        XCTAssertEqual(clearLocalCount, 1)
    }

    @MainActor
    func testOrdinaryDeletionFenceClearsOnlyAfterLiveSameOwnerReauthentication() async throws {
        let rider = sessionRider(id: "support-restored-owner")
        let record = AccountDeletionSessionRecord(
            state: .identityUnavailable,
            owner: RecordingOwner(user: rider)
        )
        try AccountDeletionSessionRecordStore.recordRequired(record)
        let session = AppSession(
            rideUploads: DeletionFreezeUploadRuntimeSpy(),
            rideRecordings: SessionRecordingRuntimeSpy(),
            authClient: AuthClientFake(
                resumeOutcomes: [],
                meResults: [.success(rider)]
            ),
            accountDeletionCapabilityStore: SessionDeletionCapabilityStore(capability: nil)
        )

        try session.prepareToReauthenticateAfterAccountDeletionState()
        XCTAssertEqual(AccountDeletionSessionRecordStore.pending(), record)

        try await session.completeSignIn()

        XCTAssertEqual(session.currentUser?.id, rider.id)
        XCTAssertNil(session.accountDeletionSessionRecord)
        XCTAssertNil(AccountDeletionSessionRecordStore.pending())
    }

    @MainActor
    func testFailedReauthenticationCannotClearOrdinaryDeletionFence() async throws {
        let record = AccountDeletionSessionRecord(
            state: .pending,
            owner: RecordingOwner(id: "pending-owner", wallet: "pending-wallet")
        )
        try AccountDeletionSessionRecordStore.recordRequired(record)
        let session = AppSession(
            rideUploads: DeletionFreezeUploadRuntimeSpy(),
            rideRecordings: SessionRecordingRuntimeSpy(),
            authClient: AuthClientFake(
                resumeOutcomes: [],
                meResults: [.failure(URLError(.timedOut))]
            ),
            accountDeletionCapabilityStore: SessionDeletionCapabilityStore(capability: nil)
        )

        try session.prepareToReauthenticateAfterAccountDeletionState()
        do {
            try await session.completeSignIn()
            XCTFail("an unavailable authority cannot clear the durable fence")
        } catch {}

        XCTAssertEqual(session.accountDeletionSessionRecord, record)
        XCTAssertEqual(AccountDeletionSessionRecordStore.pending(), record)
    }

    @MainActor
    func testRelaunchResumesCachedDifferentOwnerWhileKeepingSavedStatusFence() async throws {
        let deletingOwner = RecordingOwner(
            id: "saved-status-owner",
            wallet: "wallet-saved-status-owner"
        )
        let replacementRider = sessionRider(id: "cached-replacement-owner")
        let replacementOwner = RecordingOwner(user: replacementRider)
        let record = AccountDeletionSessionRecord(
            state: .pending,
            owner: deletingOwner,
            savedStatusRemoved: true
        )
        try AccountDeletionSessionRecordStore.recordRequired(record)
        CachedRiderStore.save(replacementRider)
        let uploads = DeletionFreezeUploadRuntimeSpy()
        let session = AppSession(
            rideUploads: uploads,
            rideRecordings: SessionRecordingRuntimeSpy(),
            authClient: AuthClientFake(
                resumeOutcomes: [.resumed],
                meResults: [.success(replacementRider)]
            ),
            accountDeletionCapabilityStore: SessionDeletionCapabilityStore(capability: nil)
        )

        XCTAssertEqual(
            AccountDeletionRootDestination.resolve(
                storage: session.accountDeletionCapabilityState,
                sessionRecord: session.accountDeletionSessionRecord,
                signedInOwner: session.accountRoutingOwner
            ),
            .account
        )
        await session.resume()

        XCTAssertEqual(session.currentUser?.id, replacementRider.id)
        XCTAssertEqual(session.accountRoutingOwner, replacementOwner)
        XCTAssertEqual(AccountDeletionSessionRecordStore.pending(), record)
        let activatedUserIDs = await uploads.activatedUserIDs
        XCTAssertTrue(activatedUserIDs.contains(replacementRider.id))
    }

    @MainActor
    func testDifferentOwnerCompletionCannotEraseSavedStatusReplacementFence() async throws {
        let retainedOwner = RecordingOwner(
            id: "retained-fence-owner",
            wallet: "retained-fence-wallet"
        )
        let retainedRecord = AccountDeletionSessionRecord(
            state: .pending,
            owner: retainedOwner,
            savedStatusRemoved: true
        )
        try AccountDeletionSessionRecordStore.recordRequired(retainedRecord)

        let completingOwner = RecordingOwner(
            id: "completing-owner",
            wallet: "completing-wallet"
        )
        let baseCapability = AccountDeletionCapability(
            requestID: "11111111-1111-4111-8111-111111111111",
            statusToken: String(repeating: "a", count: 43),
            owner: completingOwner,
            inventoryDigest: AccountDeletionLocalInventory.empty.digest,
            acknowledgedRideIDs: [],
            unuploadedRidesAcknowledged: true,
            createdAt: Date(timeIntervalSince1970: 1_777_000_000),
            localCleanupCompletedAt: nil
        )
        let completed = AccountDeletionStatus(
            contractVersion: AccountDeletionContract.version,
            requestID: baseCapability.requestID,
            status: .completed,
            requestedAt: "2026-08-24T12:00:00Z",
            updatedAt: "2026-08-24T12:01:00Z",
            completedAt: "2026-08-24T12:01:00Z",
            blockers: [],
            failureCode: nil,
            retryable: false,
            attemptCount: 1
        )
        let verified = try XCTUnwrap(
            baseCapability.markingServerCompletionVerified(completed)
        )
        let capabilityStore = SessionDeletionCapabilityStore(capability: verified)
        let session = AppSession(
            rideUploads: SessionUploadRuntimeNoop(),
            rideRecordings: SessionRecordingRuntimeSpy(),
            authClient: AuthClientFake(resumeOutcomes: []),
            accountDeletionCapabilityStore: capabilityStore
        )
        var cleanupOwners: [RecordingOwner] = []
        let model = AccountDeletionModel(
            capabilityStore: capabilityStore,
            inventory: { .empty },
            localCleanup: { capability, _ in
                cleanupOwners.append(try XCTUnwrap(capability.owner))
            },
            capabilityDidChange: {
                try await session.accountDeletionCapabilityDidChange()
            },
            localCleanupDidComplete: { owner in
                try await session.accountDeletionLocalCleanupDidComplete(owner: owner)
            }
        )

        await model.load(owner: nil)
        guard case .completed = model.state else {
            return XCTFail("verified completion must finish exact-owner local cleanup")
        }
        XCTAssertEqual(cleanupOwners, [completingOwner])
        XCTAssertEqual(AccountDeletionSessionRecordStore.pending(), retainedRecord)

        await model.acknowledgeCompletion()
        XCTAssertEqual(capabilityStore.load(), .none)
        XCTAssertEqual(AccountDeletionSessionRecordStore.pending(), retainedRecord)

        let relaunch = AppSession(
            rideUploads: SessionUploadRuntimeNoop(),
            rideRecordings: SessionRecordingRuntimeSpy(),
            authClient: AuthClientFake(resumeOutcomes: [.noStoredSession]),
            accountDeletionCapabilityStore: capabilityStore
        )
        XCTAssertEqual(relaunch.accountDeletionSessionRecord, retainedRecord)
    }

    @MainActor
    func testDifferentOwnerDeletion401KeepsIndependentDurableOwnerTruth() async throws {
        let retainedOwner = RecordingOwner(
            id: "retained-fence-owner",
            wallet: "retained-fence-wallet"
        )
        let retainedRecord = AccountDeletionSessionRecord(
            state: .pending,
            owner: retainedOwner,
            savedStatusRemoved: true
        )
        try AccountDeletionSessionRecordStore.recordRequired(retainedRecord)

        let refusedRider = sessionRider(id: "refused-different-owner")
        let refusedOwner = RecordingOwner(user: refusedRider)
        let auth = AuthClientFake(resumeOutcomes: [])
        let session = AppSession(
            rideUploads: DeletionFreezeUploadRuntimeSpy(),
            rideRecordings: SessionRecordingRuntimeSpy(),
            authClient: auth,
            accountDeletionCapabilityStore: SessionDeletionCapabilityStore(capability: nil)
        )
        CachedRiderStore.save(refusedRider)
        session.phase = .signedIn(refusedRider)

        NotificationCenter.default.post(
            name: .brAccountDeletionSessionState,
            object: auth,
            userInfo: ["state": AccountDeletionSessionState.pending.rawValue]
        )
        let deadline = Date().addingTimeInterval(10)
        while Date() < deadline {
            if await auth.clearLocalCount == 1 { break }
            await Task.yield()
        }

        XCTAssertEqual(
            session.accountDeletionSessionRecord,
            AccountDeletionSessionRecord(state: .pending, owner: refusedOwner)
        )
        let durableRecords = durableDeletionSessionRecords()
        XCTAssertEqual(Set(durableRecords.compactMap(\.owner)), [retainedOwner, refusedOwner])
        XCTAssertTrue(durableRecords.contains(retainedRecord))
    }

    @MainActor
    func testExternalLocalCleanupJournalAcknowledgesOfflineWithoutResume() async throws {
        let completed = AccountDeletionSessionRecord(
            state: .deleted,
            owner: nil,
            localCleanupCompletedAt: Date(timeIntervalSince1970: 1_777_000_100)
        )
        try AccountDeletionSessionRecordStore.recordRequired(completed)
        let auth = AuthClientFake(resumeOutcomes: [.resumed])
        let session = makeSession(auth: auth)

        XCTAssertEqual(session.accountDeletionSessionRecord, completed)
        try session.acknowledgeAccountDeletionSessionCompletion()

        XCTAssertNil(session.accountDeletionSessionRecord)
        XCTAssertNil(AccountDeletionSessionRecordStore.pending())
        let resumeCallCount = await auth.resumeCallCount
        XCTAssertEqual(resumeCallCount, 0)

        NotificationCenter.default.post(
            name: .brAccountDeletionSessionState,
            object: auth,
            userInfo: ["state": AccountDeletionSessionState.deleted.rawValue]
        )
        for _ in 0..<20 { await Task.yield() }
        XCTAssertNil(
            session.accountDeletionSessionRecord,
            "a queued 401 cannot recreate an undismissable room after external cleanup Done"
        )
        XCTAssertNil(AccountDeletionSessionRecordStore.pending())

        let relaunch = makeSession(auth: AuthClientFake(resumeOutcomes: [.noStoredSession]))
        XCTAssertNil(relaunch.accountDeletionSessionRecord)
    }

    @MainActor
    func testExternalCompletionDoneRetiresExactEmergencyWitnessBeforeJournal() throws {
        let recoveryID = "external-completion-recovery"
        let unrelatedRecoveryID = "unrelated-emergency-recovery"
        let completed = AccountDeletionSessionRecord(
            recoveryID: recoveryID,
            state: .deleted,
            owner: nil,
            localCleanupCompletedAt: Date(timeIntervalSince1970: 1_777_000_100)
        )
        let sessionStore = TestDeletionSessionRecordStore(record: completed)
        let emergencyStore = TestDeletionEmergencyFenceStore(
            recoveryIDs: [recoveryID]
        )
        let session = AppSession(
            rideUploads: SessionUploadRuntimeNoop(),
            rideRecordings: SessionRecordingRuntimeSpy(),
            authClient: AuthClientFake(resumeOutcomes: []),
            accountDeletionCapabilityStore: SessionDeletionCapabilityStore(capability: nil),
            accountDeletionSessionStore: sessionStore,
            accountDeletionEmergencyFenceStore: emergencyStore
        )
        try emergencyStore.armRequired(recoveryID: unrelatedRecoveryID)

        try session.acknowledgeAccountDeletionSessionCompletion()

        XCTAssertNil(sessionStore.load())
        XCTAssertFalse(emergencyStore.records().contains { $0.recoveryID == recoveryID })
        XCTAssertTrue(
            emergencyStore.records().contains { $0.recoveryID == unrelatedRecoveryID },
            "Done may retire only its exact crash witness"
        )
        let relaunch = AppSession(
            rideUploads: SessionUploadRuntimeNoop(),
            rideRecordings: SessionRecordingRuntimeSpy(),
            authClient: AuthClientFake(resumeOutcomes: [.noStoredSession]),
            accountDeletionCapabilityStore: SessionDeletionCapabilityStore(capability: nil),
            accountDeletionSessionStore: sessionStore,
            accountDeletionEmergencyFenceStore: emergencyStore
        )
        XCTAssertEqual(
            relaunch.accountDeletionSessionRecord?.recoveryID,
            unrelatedRecoveryID
        )
    }

    @MainActor
    func testEmergencyWitnessClearFailureKeepsRichCompletionJournalAndScreen() {
        let recoveryID = "failed-emergency-clear-recovery"
        let completed = AccountDeletionSessionRecord(
            recoveryID: recoveryID,
            state: .deleted,
            owner: nil,
            localCleanupCompletedAt: Date(timeIntervalSince1970: 1_777_000_100)
        )
        let sessionStore = TestDeletionSessionRecordStore(record: completed)
        let emergencyStore = TestDeletionEmergencyFenceStore(
            recoveryIDs: [recoveryID],
            clearFails: true
        )
        let session = AppSession(
            rideUploads: SessionUploadRuntimeNoop(),
            rideRecordings: SessionRecordingRuntimeSpy(),
            authClient: AuthClientFake(resumeOutcomes: []),
            accountDeletionCapabilityStore: SessionDeletionCapabilityStore(capability: nil),
            accountDeletionSessionStore: sessionStore,
            accountDeletionEmergencyFenceStore: emergencyStore
        )

        XCTAssertThrowsError(
            try session.acknowledgeAccountDeletionSessionCompletion()
        )

        XCTAssertTrue(sessionStore.contains(completed))
        XCTAssertEqual(session.accountDeletionSessionRecord, completed)
        XCTAssertTrue(
            emergencyStore.records().contains { $0.recoveryID == recoveryID }
        )
    }

    @MainActor
    func testDeletionSessionRelaunchReassertsFreezeBeforeReadingInventory() async throws {
        let owner = RecordingOwner(
            id: "external-relaunch-owner",
            wallet: "external-relaunch-wallet"
        )
        let record = AccountDeletionSessionRecord(state: .deleted, owner: owner)
        try AccountDeletionSessionRecordStore.recordRequired(record)
        let uploads = FreezeRequiredDeletionInventoryRuntime()
        let recordings = SessionRecordingRuntimeSpy()
        let session = AppSession(
            rideUploads: uploads,
            rideRecordings: recordings,
            authClient: AuthClientFake(resumeOutcomes: []),
            accountDeletionCapabilityStore: SessionDeletionCapabilityStore(capability: nil)
        )

        let inventory = try await session.accountDeletionSessionInventory(
            recoveryID: record.recoveryID
        )

        XCTAssertEqual(inventory, .empty)
        let frozenOwners = await uploads.frozenOwners
        XCTAssertEqual(frozenOwners, [owner])
        let deactivations = await recordings.deactivations
        XCTAssertEqual(deactivations, 1)
    }

    @MainActor
    func testStaleRecoveryInventoryCannotClearNewlySignedInOwnerSurfaces() async throws {
        let ownerA = RecordingOwner(
            id: "inventory-recovery-owner-a",
            wallet: "inventory-recovery-wallet-a"
        )
        let recordA = AccountDeletionSessionRecord(state: .deleted, owner: ownerA)
        let sessionStore = TestDeletionSessionRecordStore(record: recordA)
        let riderB = sessionRider(id: "inventory-new-owner-b")
        let uploads = GatedDeletionFreezeUploadRuntime()
        let recordings = SessionRecordingRuntimeSpy()
        let session = AppSession(
            rideUploads: uploads,
            rideRecordings: recordings,
            authClient: AuthClientFake(
                resumeOutcomes: [],
                meResults: [.success(riderB)]
            ),
            accountDeletionCapabilityStore: SessionDeletionCapabilityStore(capability: nil),
            accountDeletionSessionStore: sessionStore
        )

        let inventoryTask = Task { @MainActor in
            try await session.accountDeletionSessionInventory(
                recoveryID: recordA.recoveryID
            )
        }
        await uploads.waitUntilFreezeEntered()

        try session.prepareToReauthenticateAfterAccountDeletionState()
        try await session.completeSignIn()
        let ownerBMarker = URL(string: "file:///owner-b-import.gpx")!
        session.pendingImportURL = ownerBMarker
        await uploads.releaseFreeze()

        let inventoryResult = await inventoryTask.result
        switch inventoryResult {
        case .success:
            XCTFail("owner A's stale inventory must not publish after owner B signs in")
        case .failure:
            break
        }
        XCTAssertEqual(session.currentUser?.id, riderB.id)
        XCTAssertEqual(session.pendingImportURL, ownerBMarker)
        XCTAssertTrue(sessionStore.contains(recordA))
        let activatedUserIDs = await uploads.activatedUserIDs
        XCTAssertTrue(activatedUserIDs.contains(riderB.id))
    }

    func testExternalCleanupCompletionAtomicallyReplacesOnlyItsExactOwnerJournal() throws {
        let retained = AccountDeletionSessionRecord(
            state: .pending,
            owner: RecordingOwner(id: "retained-owner", wallet: "retained-wallet"),
            savedStatusRemoved: true
        )
        let completing = AccountDeletionSessionRecord(
            state: .deleted,
            owner: RecordingOwner(id: "completing-owner", wallet: "completing-wallet")
        )
        let completed = AccountDeletionSessionRecord(
            recoveryID: completing.recoveryID,
            state: .deleted,
            owner: nil,
            localCleanupCompletedAt: Date(timeIntervalSince1970: 1_777_000_100)
        )
        try AccountDeletionSessionRecordStore.recordRequired(retained)
        try AccountDeletionSessionRecordStore.recordRequired(completing)

        try AccountDeletionSessionRecordStore.replaceRequired(
            completing,
            with: completed
        )

        XCTAssertEqual(
            AccountDeletionSessionRecordStore.records(),
            [retained, completed],
            "completion must replace only its exact owner before privacy scrubs the owner"
        )
        try AccountDeletionSessionRecordStore.clearRequired(completed)
        XCTAssertEqual(AccountDeletionSessionRecordStore.records(), [retained])
    }

    func testTwoAnonymousCompletionScreensKeepExactOpaqueSlotsThroughDone() throws {
        let completionA = AccountDeletionSessionRecord(
            recoveryID: "recovery-a",
            state: .deleted,
            owner: nil,
            localCleanupCompletedAt: Date(timeIntervalSince1970: 1_777_000_100)
        )
        let completionB = AccountDeletionSessionRecord(
            recoveryID: "recovery-b",
            state: .deleted,
            owner: nil,
            localCleanupCompletedAt: Date(timeIntervalSince1970: 1_777_000_200)
        )
        try AccountDeletionSessionRecordStore.recordRequired(completionA)
        try AccountDeletionSessionRecordStore.recordRequired(completionB)

        XCTAssertEqual(AccountDeletionSessionRecordStore.records(), [completionA, completionB])
        try AccountDeletionSessionRecordStore.clearRequired(completionB)
        XCTAssertEqual(AccountDeletionSessionRecordStore.records(), [completionA])
    }

    @MainActor
    func testOwnerUnknownDeletionRefusalNeverOverwritesRetainedAnonymousCompletion() async throws {
        let retained = AccountDeletionSessionRecord(
            recoveryID: "retained-anonymous-completion",
            state: .deleted,
            owner: nil,
            localCleanupCompletedAt: Date(timeIntervalSince1970: 1_777_000_100)
        )
        try AccountDeletionSessionRecordStore.recordRequired(retained)
        let auth = AuthClientFake(resumeOutcomes: [])
        let session = makeSession(auth: auth)
        XCTAssertEqual(session.accountDeletionSessionRecord, retained)

        NotificationCenter.default.post(
            name: .brAccountDeletionSessionState,
            object: auth,
            userInfo: ["state": AccountDeletionSessionState.pending.rawValue]
        )
        let deadline = Date().addingTimeInterval(10)
        while Date() < deadline {
            if AccountDeletionSessionRecordStore.records().count == 2 { break }
            await Task.yield()
        }

        let records = AccountDeletionSessionRecordStore.records()
        XCTAssertEqual(records.count, 2)
        XCTAssertTrue(records.contains(retained))
        let added = try XCTUnwrap(records.last { $0.recoveryID != retained.recoveryID })
        XCTAssertNil(added.owner)
        XCTAssertEqual(added.state, .pending)
        XCTAssertNil(added.localCleanupCompletedAt)
    }

    func testMalformedOrEmptyDeletionJournalsRemainUnknownOwnerFences() throws {
        let journalKey = "br.account_deletion.session_state.v1"
        let emergencyKey = "br.account_deletion.emergency_fence.v1"

        UserDefaults.standard.set(Data("not-json".utf8), forKey: journalKey)
        XCTAssertEqual(
            AccountDeletionSessionRecordStore.records(),
            [AccountDeletionSessionRecordStore.unavailableJournalRecord]
        )

        let emptyRecovery = AccountDeletionSessionRecord(
            recoveryID: "",
            state: .identityUnavailable,
            owner: nil
        )
        UserDefaults.standard.set(
            try JSONEncoder().encode([emptyRecovery]),
            forKey: journalKey
        )
        XCTAssertEqual(
            AccountDeletionSessionRecordStore.records(),
            [AccountDeletionSessionRecordStore.unavailableJournalRecord]
        )

        UserDefaults.standard.removeObject(forKey: journalKey)
        UserDefaults.standard.set(try JSONEncoder().encode([String]()), forKey: emergencyKey)
        let emergency = try XCTUnwrap(AccountDeletionEmergencyFenceStore.records.first)
        XCTAssertEqual(emergency.state, .identityUnavailable)
        XCTAssertNil(emergency.owner)
        XCTAssertFalse(
            AccountDeletionLocalFence.permitsAccountWork(
                owner: RecordingOwner(id: "any-owner", wallet: "any-wallet"),
                sessionRecords: AccountDeletionEmergencyFenceStore.records,
                capabilityState: .none
            )
        )
    }

    func testIndependentEmergencyFenceSurvivesAnotherOwnersJournalSuccess() throws {
        let recoveryA = "emergency-recovery-a"
        try AccountDeletionEmergencyFenceStore.armRequired(recoveryID: recoveryA)
        let ownerB = RecordingOwner(id: "journal-owner-b", wallet: "journal-wallet-b")
        let recordB = AccountDeletionSessionRecord(
            recoveryID: "journal-recovery-b",
            state: .pending,
            owner: ownerB
        )

        try AccountDeletionSessionRecordStore.recordRequired(recordB)
        try AccountDeletionSessionRecordStore.clearRequired(recordB)

        XCTAssertTrue(
            AccountDeletionEmergencyFenceStore.records.contains {
                $0.recoveryID == recoveryA
            },
            "rider B's successful journal write and cleanup cannot clear rider A's unknown witness"
        )
        XCTAssertFalse(
            AccountDeletionLocalFence.permitsAccountWork(
                owner: ownerB,
                sessionRecords: AccountDeletionSessionRecordStore.records(),
                capabilityState: .none
            )
        )
    }

    @MainActor
    func testColdLaunchPrefersExactJournalOverSameRecoveryIDEmergencyWitness() throws {
        let recoveryID = "shared-recovery-id"
        let owner = RecordingOwner(id: "known-journal-owner", wallet: "known-journal-wallet")
        let exact = AccountDeletionSessionRecord(
            recoveryID: recoveryID,
            state: .deleted,
            owner: owner
        )
        try AccountDeletionEmergencyFenceStore.armRequired(recoveryID: recoveryID)
        try AccountDeletionSessionRecordStore.recordRequired(exact)

        let session = AppSession(
            rideUploads: SessionUploadRuntimeNoop(),
            rideRecordings: SessionRecordingRuntimeSpy(),
            authClient: AuthClientFake(resumeOutcomes: []),
            accountDeletionCapabilityStore: SessionDeletionCapabilityStore(capability: nil)
        )

        XCTAssertEqual(session.accountDeletionSessionRecord, exact)
        XCTAssertEqual(AccountDeletionSessionRecordStore.records(), [exact])
        XCTAssertTrue(
            AccountDeletionEmergencyFenceStore.records.contains {
                $0.recoveryID == recoveryID
            },
            "the redundant witness remains until its own verified clear succeeds"
        )
    }

    func testExactCompletionReplacementIgnoresAndPreservesUnrelatedEmergency() throws {
        let ownerA = RecordingOwner(id: "completion-owner-a", wallet: "completion-wallet-a")
        let pendingA = AccountDeletionSessionRecord(
            recoveryID: "completion-recovery-a",
            state: .deleted,
            owner: ownerA
        )
        let completedA = AccountDeletionSessionRecord(
            recoveryID: pendingA.recoveryID,
            state: .deleted,
            owner: nil,
            localCleanupCompletedAt: Date(timeIntervalSince1970: 1_777_000_100)
        )
        let emergencyB = "unrelated-emergency-b"
        try AccountDeletionSessionRecordStore.recordRequired(pendingA)
        try AccountDeletionEmergencyFenceStore.armRequired(recoveryID: emergencyB)

        try AccountDeletionSessionRecordStore.replaceRequired(pendingA, with: completedA)

        let records = AccountDeletionSessionRecordStore.records()
        XCTAssertTrue(records.contains(completedA))
        XCTAssertFalse(records.contains(pendingA))
        XCTAssertTrue(
            AccountDeletionEmergencyFenceStore.records.contains {
                $0.recoveryID == emergencyB
            },
            "another recovery slot must survive exact-owner completion"
        )
    }

    func testPersistedDeletionSessionFenceBlocksProcessIndependentWriters() {
        AccountDeletionSessionRecordStore.record(
            AccountDeletionSessionRecord(
                state: .pending,
                owner: RecordingOwner(id: "pending-rider", wallet: "pending-wallet")
            )
        )

        XCTAssertFalse(AccountDeletionLocalFence.permitsAccountWork)
    }

    @MainActor
    func testRemoteCompletionCannotPurgeUnacknowledgedOrChangedRideCustody() async {
        let owner = RecordingOwner(id: "deleted-rider", wallet: "deleted-wallet")
        let record = AccountDeletionSessionRecord(state: .deleted, owner: owner)
        AccountDeletionSessionRecordStore.record(record)
        let custody = AccountDeletionCustodyRecord(
            rideID: "ride-1",
            uploadJobID: "job-1",
            startedAt: Date(timeIntervalSince1970: 1_777_000_000),
            handedOff: false
        )
        let recordings = SessionRecordingRuntimeSpy(deletionRecords: [custody])
        let uploads = DeletionFreezeUploadRuntimeSpy(deletionRecords: [])
        let session = AppSession(
            rideUploads: uploads,
            rideRecordings: recordings,
            authClient: AuthClientFake(resumeOutcomes: []),
            accountDeletionCapabilityStore: SessionDeletionCapabilityStore(capability: nil)
        )

        do {
            try await session.completeLocalAccountDeletionFromSessionRecord(
                recoveryID: record.recoveryID,
                reviewedInventoryDigest: AccountDeletionLocalInventory.empty.digest,
                unuploadedRidesAcknowledged: false
            )
            XCTFail("an unacknowledged local ride must block cleanup")
        } catch {}
        var recordingPurges = await recordings.purgedOwners
        var uploadPurges = await uploads.purgedOwners
        XCTAssertTrue(recordingPurges.isEmpty)
        XCTAssertTrue(uploadPurges.isEmpty)

        do {
            try await session.completeLocalAccountDeletionFromSessionRecord(
                recoveryID: record.recoveryID,
                reviewedInventoryDigest: AccountDeletionLocalInventory.empty.digest,
                unuploadedRidesAcknowledged: true
            )
            XCTFail("an inventory change after review must block cleanup")
        } catch {}
        recordingPurges = await recordings.purgedOwners
        uploadPurges = await uploads.purgedOwners
        XCTAssertTrue(recordingPurges.isEmpty)
        XCTAssertTrue(uploadPurges.isEmpty)
        XCTAssertEqual(AccountDeletionSessionRecordStore.pending(), record)
    }

    @MainActor
    func testPendingOrUnavailableIdentityNeverAuthorizesLocalPurge() async {
        let owner = RecordingOwner(id: "pending-rider", wallet: "pending-wallet")
        for state in [
            AccountDeletionSessionState.pending,
            .identityUnavailable,
        ] {
            let record = AccountDeletionSessionRecord(state: state, owner: owner)
            AccountDeletionSessionRecordStore.record(record)
            let recordings = SessionRecordingRuntimeSpy(deletionRecords: [])
            let uploads = DeletionFreezeUploadRuntimeSpy(deletionRecords: [])
            let session = AppSession(
                rideUploads: uploads,
                rideRecordings: recordings,
                authClient: AuthClientFake(resumeOutcomes: []),
                accountDeletionCapabilityStore: SessionDeletionCapabilityStore(capability: nil)
            )

            do {
                try await session.completeLocalAccountDeletionFromSessionRecord(
                    recoveryID: record.recoveryID,
                    reviewedInventoryDigest: AccountDeletionLocalInventory.empty.digest,
                    unuploadedRidesAcknowledged: true
                )
                XCTFail("\(state) is not authoritative completion")
            } catch {}
            let recordingPurges = await recordings.purgedOwners
            let uploadPurges = await uploads.purgedOwners
            XCTAssertTrue(recordingPurges.isEmpty)
            XCTAssertTrue(uploadPurges.isEmpty)
        }
    }

    @MainActor
    func testUnavailableDeletionStorageReloadsWithoutPermanentAppLock() async {
        let rider = sessionRider(id: "keychain-retry-rider")
        let owner = RecordingOwner(user: rider)
        let store = ReloadableDeletionCapabilityStore(initial: .unavailable)
        let recordings = SessionRecordingRuntimeSpy()
        let uploads = DeletionFreezeUploadRuntimeSpy()
        let session = AppSession(
            rideUploads: uploads,
            rideRecordings: recordings,
            authClient: AuthClientFake(resumeOutcomes: []),
            accountDeletionCapabilityStore: store
        )
        session.phase = .signedIn(rider)

        await session.reloadAccountDeletionStorage()
        XCTAssertEqual(session.accountDeletionCapabilityState, .unavailable)
        var activatedUserIDs = await uploads.activatedUserIDs
        XCTAssertTrue(activatedUserIDs.allSatisfy { $0 == nil })

        store.set(.none)
        await session.reloadAccountDeletionStorage()
        XCTAssertEqual(session.accountDeletionCapabilityState, .none)
        activatedUserIDs = await uploads.activatedUserIDs
        XCTAssertTrue(activatedUserIDs.contains(rider.id))

        store.set(.unavailable)
        await session.reloadAccountDeletionStorage()
        let capability = AccountDeletionCapability(
            requestID: "11111111-1111-4111-8111-111111111111",
            statusToken: String(repeating: "a", count: 43),
            owner: owner,
            inventoryDigest: AccountDeletionLocalInventory.empty.digest,
            acknowledgedRideIDs: [],
            unuploadedRidesAcknowledged: true,
            createdAt: Date(timeIntervalSince1970: 1_777_000_000),
            localCleanupCompletedAt: nil
        )
        store.set(.available(capability))
        await session.reloadAccountDeletionStorage()
        XCTAssertEqual(session.accountDeletionCapabilityState, .available(capability))
        let frozenOwners = await uploads.frozenOwners
        XCTAssertEqual(frozenOwners, [owner])
    }

    @MainActor
    func testColdStartUnavailableToNoneReloadResumesInsteadOfStrandingSpinner() async {
        let store = ReloadableDeletionCapabilityStore(initial: .unavailable)
        let auth = AuthClientFake(resumeOutcomes: [.noStoredSession])
        let session = AppSession(
            rideUploads: DeletionFreezeUploadRuntimeSpy(),
            rideRecordings: SessionRecordingRuntimeSpy(),
            authClient: auth,
            accountDeletionCapabilityStore: store
        )

        store.set(.none)
        await session.reloadAccountDeletionStorage()

        guard case .signedOut = session.phase else {
            return XCTFail("resolved storage must leave the cold-start spinner")
        }
        let resumeCallCount = await auth.resumeCallCount
        XCTAssertEqual(resumeCallCount, 1)
    }

    @MainActor
    func testColdStartUnavailableToUnconfirmedResumesReadOnlyWithFence() async {
        let rider = sessionRider(id: "unconfirmed-recovery-rider")
        let owner = RecordingOwner(user: rider)
        let capability = AccountDeletionCapability(
            requestID: "11111111-1111-4111-8111-111111111111",
            statusToken: String(repeating: "a", count: 43),
            owner: owner,
            inventoryDigest: AccountDeletionLocalInventory.empty.digest,
            acknowledgedRideIDs: [],
            unuploadedRidesAcknowledged: true,
            createdAt: Date(timeIntervalSince1970: 1_777_000_000),
            localCleanupCompletedAt: nil
        )
        let store = ReloadableDeletionCapabilityStore(initial: .unavailable)
        let uploads = DeletionFreezeUploadRuntimeSpy()
        let auth = AuthClientFake(
            resumeOutcomes: [.resumed],
            meResults: [.success(rider)]
        )
        let session = AppSession(
            rideUploads: uploads,
            rideRecordings: SessionRecordingRuntimeSpy(),
            authClient: auth,
            accountDeletionCapabilityStore: store
        )

        store.set(.unconfirmed(capability))
        await session.reloadAccountDeletionStorage()

        guard case let .signedIn(user) = session.phase else {
            return XCTFail("provisional recovery may resume only into fenced account state")
        }
        XCTAssertEqual(user.id, rider.id)
        XCTAssertEqual(session.accountDeletionCapabilityState, .unconfirmed(capability))
        let frozenOwners = await uploads.frozenOwners
        XCTAssertTrue(frozenOwners.contains(owner))
        let activatedUserIDs = await uploads.activatedUserIDs
        XCTAssertFalse(activatedUserIDs.contains(rider.id))
    }

    @MainActor
    func testDifferentOwnerJournalCannotPromoteProvisionalPairIntoRootLockout() async throws {
        let retainedOwner = RecordingOwner(
            id: "retained-provisional-owner",
            wallet: "retained-provisional-wallet"
        )
        let retainedRecord = AccountDeletionSessionRecord(
            state: .pending,
            owner: retainedOwner,
            savedStatusRemoved: true
        )
        try AccountDeletionSessionRecordStore.recordRequired(retainedRecord)

        let rider = sessionRider(id: "provisional-current-owner")
        let owner = RecordingOwner(user: rider)
        CachedRiderStore.save(rider)
        let capability = AccountDeletionCapability(
            requestID: "11111111-1111-4111-8111-111111111111",
            statusToken: String(repeating: "a", count: 43),
            owner: retainedOwner,
            inventoryDigest: AccountDeletionLocalInventory.empty.digest,
            acknowledgedRideIDs: [],
            unuploadedRidesAcknowledged: true,
            createdAt: Date(timeIntervalSince1970: 1_777_000_000),
            localCleanupCompletedAt: nil
        )
        let store = ReloadableDeletionCapabilityStore(initial: .unconfirmed(capability))
        let uploads = DeletionFreezeUploadRuntimeSpy()
        let session = AppSession(
            rideUploads: uploads,
            rideRecordings: SessionRecordingRuntimeSpy(),
            authClient: AuthClientFake(
                resumeOutcomes: [.resumed],
                meResults: [.success(rider)]
            ),
            accountDeletionCapabilityStore: store
        )

        XCTAssertEqual(
            AccountDeletionRootDestination.resolve(
                storage: session.accountDeletionCapabilityState,
                sessionRecord: session.accountDeletionSessionRecord,
                signedInOwner: session.accountRoutingOwner
            ),
            .account
        )
        await session.resume()

        XCTAssertEqual(session.currentUser?.id, rider.id)
        XCTAssertEqual(AccountDeletionSessionRecordStore.pending(), retainedRecord)
        let frozenOwners = await uploads.frozenOwners
        XCTAssertFalse(frozenOwners.contains(owner))
        let activatedUserIDs = await uploads.activatedUserIDs
        XCTAssertTrue(activatedUserIDs.contains(rider.id))
        XCTAssertEqual(store.load(), .unconfirmed(capability))
    }

    // MARK: - Clock-skew policy (local belief is an optimization only)

    func testProactiveRefreshFiresNearDeclaredExpiry() {
        let policy = SessionClockPolicy(skewTolerance: 300, proactiveRefreshWindow: 60)
        let received = Date(timeIntervalSince1970: 1_000_000)
        let lifetime = SessionClockPolicy.TokenLifetime(
            expiresAt: received.addingTimeInterval(900), receivedAt: received
        )
        XCTAssertFalse(
            policy.shouldProactivelyRefresh(lifetime, now: received.addingTimeInterval(600))
        )
        XCTAssertTrue(
            policy.shouldProactivelyRefresh(lifetime, now: received.addingTimeInterval(841))
        )
        XCTAssertTrue(
            policy.shouldProactivelyRefresh(lifetime, now: received.addingTimeInterval(2_000))
        )
    }

    /// Device clock jumped backwards mid-session: elapsed time is
    /// unknowable, so the belief goes quiet instead of churning refreshes.
    func testBackwardClockJumpDoesNotForceRefresh() {
        let policy = SessionClockPolicy()
        let received = Date(timeIntervalSince1970: 1_000_000)
        let lifetime = SessionClockPolicy.TokenLifetime(
            expiresAt: received.addingTimeInterval(900), receivedAt: received
        )
        XCTAssertFalse(
            policy.shouldProactivelyRefresh(lifetime, now: received.addingTimeInterval(-3_600))
        )
    }

    /// A token that looks already-expired at receipt is skew, not truth —
    /// the request runs and the server's 401 path decides.
    func testBornDeadTokenIsSkewNotTruth() {
        let policy = SessionClockPolicy()
        let received = Date(timeIntervalSince1970: 1_000_000)
        let lifetime = SessionClockPolicy.TokenLifetime(
            expiresAt: received.addingTimeInterval(-120), receivedAt: received
        )
        XCTAssertFalse(policy.shouldProactivelyRefresh(lifetime, now: received))
    }

    func testMissingExpiryNeverTriggersProactiveRefresh() {
        XCTAssertFalse(SessionClockPolicy().shouldProactivelyRefresh(nil, now: .now))
    }

    /// No local clock comparison may gate resume: a stored token is always
    /// worth presenting to the server.
    func testResumeIsAttemptedWheneverATokenIsStored() {
        let policy = SessionClockPolicy()
        XCTAssertTrue(policy.shouldAttemptResume(hasStoredRefreshToken: true))
        XCTAssertFalse(policy.shouldAttemptResume(hasStoredRefreshToken: false))
    }

    // MARK: - Session token persistence (the dev-environment note-11 killer)

    /// The refresh token must survive storage round trips IN THIS HOST.
    /// This test host is an unsigned simulator build where the raw keychain
    /// rejects every write (no application-identifier) — the environment in
    /// which relaunches landed on onboarding (bead c6l2l note 11). Pre-fix
    /// this fails: a probed write+read round trip returned nil. The
    /// DEBUG+simulator fallback (SIWS dev-seed precedent) makes it pass;
    /// signed device builds keep the strict keychain path.
    func testSessionTokenSurvivesStorageRoundTripInThisHost() {
        let original = KeychainStore.read(.refreshToken)
        defer {
            // Leave the host exactly as found.
            if let original {
                KeychainStore.save(original, for: .refreshToken)
            } else {
                KeychainStore.delete(.refreshToken)
            }
        }

        KeychainStore.save("session-roundtrip-probe", for: .refreshToken)
        XCTAssertEqual(
            KeychainStore.read(.refreshToken),
            "session-roundtrip-probe",
            "a stored session token must be readable after a write in this host"
        )
        KeychainStore.delete(.refreshToken)
        XCTAssertNil(KeychainStore.read(.refreshToken), "delete must be effective")
    }

    /// Sign-in verification is unauthenticated, so it never enters the
    /// ordinary 401 -> refresh branch. Stable deletion authority from that
    /// real wire path must still enter AppSession's durable recovery room.
    @MainActor
    func testPrivyVerifyDeletionRefusalsEnterDurableRecoveryScreen() async throws {
        defer { SessionRefreshURLProtocol.reset() }

        for state in [
            AccountDeletionSessionState.pending,
            .deleted,
            .identityUnavailable,
        ] {
            AccountDeletionSessionRecordStore.clear()
            SessionRefreshURLProtocol.install { request in
                XCTAssertEqual(request.url?.path, "/auth/privy/verify")
                let response = try XCTUnwrap(HTTPURLResponse(
                    url: try XCTUnwrap(request.url),
                    statusCode: 401,
                    httpVersion: "HTTP/1.1",
                    headerFields: ["Content-Type": "application/json"]
                ))
                let body = try JSONSerialization.data(withJSONObject: [
                    "detail": [
                        "error": [
                            "code": state.rawValue,
                            "message": "Account lifecycle refusal",
                        ]
                    ]
                ])
                return (response, body)
            }
            let configuration = URLSessionConfiguration.ephemeral
            configuration.protocolClasses = [SessionRefreshURLProtocol.self]
            let client = APIClient(
                configuration: configuration,
                sessionCredentials: SessionCredentialStoreFake()
            )
            let session = AppSession(
                rideUploads: SessionUploadRuntimeNoop(),
                rideRecordings: SessionRecordingRuntimeSpy(),
                authClient: client,
                accountDeletionCapabilityStore: SessionDeletionCapabilityStore(
                    capability: nil
                )
            )

            do {
                _ = try await client.verifyPrivyToken(
                    wallet: "deleting-wallet",
                    privyToken: "privy-token",
                    inviteCode: nil
                )
                XCTFail("\(state.rawValue) must not complete sign-in")
            } catch APIError.notAuthenticated {
                // The durable recovery room, not onboarding error copy, owns
                // this stable backend lifecycle state.
            } catch {
                XCTFail("stable deletion refusal stayed generic: \(error)")
            }

            for _ in 0..<100 where session.accountDeletionSessionRecord?.state != state {
                try await Task.sleep(for: .milliseconds(5))
            }
            let record = try XCTUnwrap(session.accountDeletionSessionRecord)
            XCTAssertEqual(record.state, state)
            XCTAssertTrue(
                AccountDeletionSessionRecordStore.records().contains(record),
                "the room must survive relaunch before verification returns control"
            )
            XCTAssertEqual(
                AccountDeletionRootDestination.resolve(
                    storage: session.accountDeletionCapabilityState,
                    sessionRecord: record,
                    signedInOwner: session.accountRoutingOwner
                ),
                .deletionSession
            )
        }
    }

    /// The SIWS verify endpoint is a separate production sign-in path and
    /// must publish the same stable lifecycle refusal.
    @MainActor
    func testSignatureVerifyDeletionRefusalEntersDurableRecoveryScreen() async throws {
        defer { SessionRefreshURLProtocol.reset() }
        let exactCaseWallet = "0xDeLeTiOn-WaLLeT"
        SessionRefreshURLProtocol.install { request in
            XCTAssertEqual(request.url?.path, "/auth/verify")
            let response = try XCTUnwrap(HTTPURLResponse(
                url: try XCTUnwrap(request.url),
                statusCode: 401,
                httpVersion: "HTTP/1.1",
                headerFields: ["Content-Type": "application/json"]
            ))
            let body = try JSONSerialization.data(withJSONObject: [
                "detail": [
                    "error": [
                        "code": AccountDeletionSessionState.pending.rawValue,
                        "message": "Account deletion is in progress",
                    ]
                ]
            ])
            return (response, body)
        }
        let configuration = URLSessionConfiguration.ephemeral
        configuration.protocolClasses = [SessionRefreshURLProtocol.self]
        let client = APIClient(
            configuration: configuration,
            sessionCredentials: SessionCredentialStoreFake()
        )
        let notifications = LockedDeletionNotificationRecorder()
        let observer = NotificationCenter.default.addObserver(
            forName: .brAccountDeletionSessionState,
            object: nil,
            queue: nil
        ) { notification in
            guard let source = notification.object as AnyObject?, source === client else {
                return
            }
            notifications.record(notification)
        }
        defer { NotificationCenter.default.removeObserver(observer) }
        let uploads = DeletionFreezeUploadRuntimeSpy()
        let session = AppSession(
            rideUploads: uploads,
            rideRecordings: SessionRecordingRuntimeSpy(),
            authClient: client,
            accountDeletionCapabilityStore: SessionDeletionCapabilityStore(
                capability: nil
            )
        )

        do {
            _ = try await client.verifySignature(
                wallet: exactCaseWallet,
                signature: "signature",
                nonce: "nonce",
                inviteCode: nil
            )
            XCTFail("deletion refusal must not complete sign-in")
        } catch APIError.notAuthenticated {
            // Expected after the state is handed to AppSession.
        } catch {
            XCTFail("stable deletion refusal stayed generic: \(error)")
        }

        for _ in 0..<100 where session.accountDeletionSessionRecord?.state != .pending {
            try await Task.sleep(for: .milliseconds(5))
        }
        XCTAssertEqual(session.accountDeletionSessionRecord?.state, .pending)
        XCTAssertTrue(
            AccountDeletionSessionRecordStore.records().contains {
                $0 == session.accountDeletionSessionRecord
            }
        )
        XCTAssertEqual(
            notifications.snapshots.last?.attemptedWallet,
            exactCaseWallet,
            "wallet correlation is exact backend identity, not normalized display data"
        )
        for _ in 0..<100 where await uploads.activatedUserIDs.isEmpty {
            try await Task.sleep(for: .milliseconds(5))
        }
        let activatedUserIDs = await uploads.activatedUserIDs
        XCTAssertEqual(
            activatedUserIDs,
            [nil],
            "the recovery observer must finish teardown before this test releases shared state"
        )
    }

    /// A proxy-style anonymous 401 and an ordinary invalid sign-in code carry
    /// no deletion authority. They stay ordinary HTTP errors and must not
    /// manufacture a recovery room.
    @MainActor
    func testVerifyAnonymousAndUnrecognized401sStayGeneric() async throws {
        defer { SessionRefreshURLProtocol.reset() }

        for code in [String?.none, "privy_invalid"] {
            AccountDeletionSessionRecordStore.clear()
            SessionRefreshURLProtocol.install { request in
                XCTAssertEqual(request.url?.path, "/auth/privy/verify")
                let response = try XCTUnwrap(HTTPURLResponse(
                    url: try XCTUnwrap(request.url),
                    statusCode: 401,
                    httpVersion: "HTTP/1.1",
                    headerFields: ["Content-Type": "application/json"]
                ))
                var error: [String: Any] = ["message": "Sign-in refused"]
                if let code { error["code"] = code }
                let body = try JSONSerialization.data(withJSONObject: [
                    "detail": ["error": error]
                ])
                return (response, body)
            }
            let configuration = URLSessionConfiguration.ephemeral
            configuration.protocolClasses = [SessionRefreshURLProtocol.self]
            let client = APIClient(
                configuration: configuration,
                sessionCredentials: SessionCredentialStoreFake()
            )
            let session = AppSession(
                rideUploads: SessionUploadRuntimeNoop(),
                rideRecordings: SessionRecordingRuntimeSpy(),
                authClient: client,
                accountDeletionCapabilityStore: SessionDeletionCapabilityStore(
                    capability: nil
                )
            )

            do {
                _ = try await client.verifyPrivyToken(
                    wallet: "ordinary-wallet",
                    privyToken: "invalid-token",
                    inviteCode: nil
                )
                XCTFail("401 must not complete sign-in")
            } catch let APIError.http(status, returnedCode, _) {
                XCTAssertEqual(status, 401)
                XCTAssertEqual(returnedCode, code)
            } catch {
                XCTFail("ordinary 401 changed taxonomy: \(error)")
            }

            try await Task.sleep(for: .milliseconds(20))
            XCTAssertNil(session.accountDeletionSessionRecord)
            XCTAssertTrue(AccountDeletionSessionRecordStore.records().isEmpty)
        }
    }

    /// Authenticated middleware already consulted lifecycle authority before
    /// returning this 401. A later refresh outage cannot downgrade that
    /// stable original response into an ordinary HTTP failure or defer the
    /// crash-safe recovery witness.
    @MainActor
    func testOriginalAuthenticatedDeletion401RoutesBeforeTransientRefresh() async throws {
        defer { SessionRefreshURLProtocol.reset() }

        for state in [
            AccountDeletionSessionState.pending,
            .deleted,
            .identityUnavailable,
        ] {
            AccountDeletionSessionRecordStore.clear()
            let refreshRequests = LockedCounter()
            SessionRefreshURLProtocol.install { request in
                let path = try XCTUnwrap(request.url?.path)
                if path == "/auth/refresh" {
                    refreshRequests.increment()
                    let response = try XCTUnwrap(HTTPURLResponse(
                        url: try XCTUnwrap(request.url),
                        statusCode: 503,
                        httpVersion: "HTTP/1.1",
                        headerFields: ["Content-Type": "application/json"]
                    ))
                    return (response, Data("service unavailable".utf8))
                }
                XCTAssertEqual(path, "/users/me")
                let response = try XCTUnwrap(HTTPURLResponse(
                    url: try XCTUnwrap(request.url),
                    statusCode: 401,
                    httpVersion: "HTTP/1.1",
                    headerFields: ["Content-Type": "application/json"]
                ))
                let body = try JSONSerialization.data(withJSONObject: [
                    "detail": [
                        "error": [
                            "code": state.rawValue,
                            "message": "Account lifecycle refusal",
                        ]
                    ]
                ])
                return (response, body)
            }
            let credentials = SessionCredentialStoreFake(token: "deletion-refresh-token")
            let configuration = URLSessionConfiguration.ephemeral
            configuration.protocolClasses = [SessionRefreshURLProtocol.self]
            let client = APIClient(
                configuration: configuration,
                sessionCredentials: credentials
            )
            try await client.adoptSession(AuthTokenResponse(
                userId: "deleting-rider",
                wallet: "deleting-wallet",
                accessToken: "deletion-access-token",
                accessExpiresAt: nil,
                refreshToken: "deletion-refresh-token",
                refreshExpiresAt: nil
            ))
            let session = AppSession(
                rideUploads: SessionUploadRuntimeNoop(),
                rideRecordings: SessionRecordingRuntimeSpy(),
                authClient: client,
                accountDeletionCapabilityStore: SessionDeletionCapabilityStore(
                    capability: nil
                )
            )

            do {
                _ = try await client.me()
                XCTFail("\(state.rawValue) must stop authenticated account work")
            } catch APIError.notAuthenticated {
                // Expected after the original response enters recovery.
            } catch {
                XCTFail("stable original 401 was hidden by refresh: \(error)")
            }

            for _ in 0..<100 where session.accountDeletionSessionRecord?.state != state {
                try await Task.sleep(for: .milliseconds(5))
            }
            let record = try XCTUnwrap(session.accountDeletionSessionRecord)
            XCTAssertEqual(record.state, state)
            XCTAssertTrue(AccountDeletionSessionRecordStore.records().contains(record))
            XCTAssertEqual(
                refreshRequests.value,
                0,
                "stable original deletion authority must be adopted before refresh"
            )
        }
    }

    func testAuthenticatedDeletionRefusalCarriesPinnedExactOwner() async throws {
        defer {
            SessionRefreshURLProtocol.reset()
            AccountDeletionSessionRecordStore.clear()
        }
        SessionRefreshURLProtocol.install { request in
            XCTAssertEqual(request.url?.path, "/users/me")
            return try deletionRefusalHTTPResponse(
                for: request,
                code: AccountDeletionSessionState.pending.rawValue
            )
        }
        let configuration = URLSessionConfiguration.ephemeral
        configuration.protocolClasses = [SessionRefreshURLProtocol.self]
        let client = APIClient(
            configuration: configuration,
            sessionCredentials: SessionCredentialStoreFake()
        )
        let owner = RecordingOwner(
            id: "exact-refusal-rider",
            wallet: "Exact-Refusal-Wallet"
        )
        try await client.adoptSession(AuthTokenResponse(
            userId: owner.id,
            wallet: owner.wallet,
            accessToken: "exact-refusal-access",
            accessExpiresAt: nil,
            refreshToken: "exact-refusal-refresh",
            refreshExpiresAt: nil
        ))
        let notifications = LockedDeletionNotificationRecorder()
        let observer = NotificationCenter.default.addObserver(
            forName: .brAccountDeletionSessionState,
            object: nil,
            queue: nil
        ) { notification in
            guard let source = notification.object as AnyObject?, source === client else {
                return
            }
            notifications.record(notification)
        }
        defer { NotificationCenter.default.removeObserver(observer) }

        do {
            _ = try await client.me()
            XCTFail("authenticated deletion refusal must stop account work")
        } catch APIError.notAuthenticated {
            // Expected after the exact refusal context is made durable.
        }

        let refusal = try XCTUnwrap(notifications.snapshots.last)
        XCTAssertNil(refusal.attemptedWallet)
        XCTAssertEqual(refusal.attemptedOwnerID, owner.id)
        XCTAssertEqual(refusal.attemptedOwnerWallet, owner.wallet)
    }

    func testAuthenticatedDeletionRefusalPreparationCannotTearDownReplacementSession() async throws {
        defer {
            SessionRefreshURLProtocol.reset()
            AccountDeletionSessionRecordStore.clear()
        }
        SessionRefreshURLProtocol.install { request in
            XCTAssertEqual(request.url?.path, "/users/me")
            return try deletionRefusalHTTPResponse(
                for: request,
                code: AccountDeletionSessionState.pending.rawValue
            )
        }
        let preparationEntered = DispatchSemaphore(value: 0)
        let releasePreparation = DispatchSemaphore(value: 0)
        let configuration = URLSessionConfiguration.ephemeral
        configuration.protocolClasses = [SessionRefreshURLProtocol.self]
        let credentials = SessionCredentialStoreFake()
        let client = APIClient(
            configuration: configuration,
            sessionCredentials: credentials,
            accountDeletionEmergencyFenceArm: { recoveryID in
                // Model a store that wrote A's exact witness, then suspended
                // and ultimately reported failure after B was adopted.
                try AccountDeletionEmergencyFenceStore.armRequired(
                    recoveryID: recoveryID
                )
                preparationEntered.signal()
                let released = await Task.detached {
                    releasePreparation.wait(timeout: .now() + 10)
                }.value
                guard released == .success else { throw URLError(.timedOut) }
                throw AccountDeletionCapabilityStoreError.unavailable
            }
        )
        try await client.adoptSession(AuthTokenResponse(
            userId: "refusal-owner-a",
            wallet: "refusal-wallet-a",
            accessToken: "access-a",
            accessExpiresAt: nil,
            refreshToken: "refresh-a",
            refreshExpiresAt: nil
        ))
        let deletionNotifications = LockedDeletionNotificationRecorder()
        let deletionObserver = NotificationCenter.default.addObserver(
            forName: .brAccountDeletionSessionState,
            object: nil,
            queue: nil
        ) { notification in
            guard let source = notification.object as AnyObject?, source === client else {
                return
            }
            deletionNotifications.record(notification)
        }
        let invalidationNotifications = LockedCounter()
        let invalidationObserver = NotificationCenter.default.addObserver(
            forName: .brSessionInvalidated,
            object: nil,
            queue: nil
        ) { notification in
            guard let source = notification.object as AnyObject?, source === client else {
                return
            }
            invalidationNotifications.increment()
        }
        defer {
            NotificationCenter.default.removeObserver(deletionObserver)
            NotificationCenter.default.removeObserver(invalidationObserver)
        }

        let refusal = Task { () -> String? in
            do {
                _ = try await client.me()
                return "stale authenticated refusal unexpectedly succeeded"
            } catch APIError.notAuthenticated {
                return nil
            } catch {
                return "stale authenticated refusal returned \(error)"
            }
        }
        let didEnter = await Task.detached {
            preparationEntered.wait(timeout: .now() + 10)
        }.value
        guard didEnter == .success else {
            releasePreparation.signal()
            return XCTFail("refusal preparation never reached its gate")
        }

        try await client.adoptSession(AuthTokenResponse(
            userId: "replacement-owner-b",
            wallet: "replacement-wallet-b",
            accessToken: "access-b",
            accessExpiresAt: nil,
            refreshToken: "refresh-b",
            refreshExpiresAt: nil
        ))
        releasePreparation.signal()

        let refusalFailure = await refusal.value
        let remainsAuthenticated = await client.isAuthenticated
        let refusalContext = await client.accountDeletionRefusalContext()
        XCTAssertNil(refusalFailure)
        XCTAssertTrue(remainsAuthenticated)
        XCTAssertEqual(credentials.storedToken, "refresh-b")
        XCTAssertTrue(deletionNotifications.snapshots.isEmpty)
        XCTAssertEqual(invalidationNotifications.value, 0)
        XCTAssertNil(refusalContext)
        XCTAssertTrue(AccountDeletionEmergencyFenceStore.records.isEmpty)
        XCTAssertTrue(AccountDeletionSessionRecordStore.records().isEmpty)
    }

    func testRefreshDeletionRefusalPreparationCannotDowngradeReplacementSession() async throws {
        defer {
            SessionRefreshURLProtocol.reset()
            AccountDeletionSessionRecordStore.clear()
        }
        SessionRefreshURLProtocol.install { request in
            switch request.url?.path {
            case "/users/me":
                return try deletionRefusalHTTPResponse(
                    for: request,
                    code: "access_token_expired"
                )
            case "/auth/refresh":
                return try deletionRefusalHTTPResponse(
                    for: request,
                    code: AccountDeletionSessionState.pending.rawValue
                )
            default:
                throw URLError(.badURL)
            }
        }
        let preparationEntered = DispatchSemaphore(value: 0)
        let releasePreparation = DispatchSemaphore(value: 0)
        let configuration = URLSessionConfiguration.ephemeral
        configuration.protocolClasses = [SessionRefreshURLProtocol.self]
        let credentials = SessionCredentialStoreFake()
        let client = APIClient(
            configuration: configuration,
            sessionCredentials: credentials,
            accountDeletionEmergencyFenceArm: { recoveryID in
                try AccountDeletionEmergencyFenceStore.armRequired(
                    recoveryID: recoveryID
                )
                preparationEntered.signal()
                let released = await Task.detached {
                    releasePreparation.wait(timeout: .now() + 10)
                }.value
                guard released == .success else { throw URLError(.timedOut) }
                throw AccountDeletionCapabilityStoreError.unavailable
            }
        )
        try await client.adoptSession(AuthTokenResponse(
            userId: "refresh-owner-a",
            wallet: "refresh-wallet-a",
            accessToken: "access-a",
            accessExpiresAt: nil,
            refreshToken: "refresh-a",
            refreshExpiresAt: nil
        ))
        let notifications = LockedDeletionNotificationRecorder()
        let observer = NotificationCenter.default.addObserver(
            forName: .brAccountDeletionSessionState,
            object: nil,
            queue: nil
        ) { notification in
            guard let source = notification.object as AnyObject?, source === client else {
                return
            }
            notifications.record(notification)
        }
        defer { NotificationCenter.default.removeObserver(observer) }

        let refusal = Task { try? await client.me() }
        let didEnter = await Task.detached {
            preparationEntered.wait(timeout: .now() + 10)
        }.value
        guard didEnter == .success else {
            releasePreparation.signal()
            return XCTFail("refresh refusal preparation never reached its gate")
        }
        try await client.adoptSession(AuthTokenResponse(
            userId: "replacement-owner-b",
            wallet: "replacement-wallet-b",
            accessToken: "access-b",
            accessExpiresAt: nil,
            refreshToken: "refresh-b",
            refreshExpiresAt: nil
        ))
        releasePreparation.signal()
        _ = await refusal.value

        let remainsAuthenticated = await client.isAuthenticated
        let context = await client.accountDeletionRefusalContext()
        XCTAssertTrue(remainsAuthenticated)
        XCTAssertEqual(credentials.storedToken, "refresh-b")
        XCTAssertNil(context)
        XCTAssertTrue(notifications.snapshots.isEmpty)
        XCTAssertTrue(AccountDeletionEmergencyFenceStore.records.isEmpty)
        XCTAssertTrue(AccountDeletionSessionRecordStore.records().isEmpty)
    }

    func testMeCannotRepinBearerOwnerOrAuthorizeResponseOwnerDeletion() async throws {
        defer {
            SessionRefreshURLProtocol.reset()
            AccountDeletionSessionRecordStore.clear()
        }
        addTeardownBlock {
            CachedRiderStore.clear()
            await MainActor.run { ResponseCache.shared.clear() }
        }
        await MainActor.run { ResponseCache.shared.clear() }
        let riderA = sessionRider(id: "bearer-owner-a")
        let riderB = sessionRider(id: "me-response-owner-b")
        let ownerB = RecordingOwner(user: riderB)
        CachedRiderStore.save(riderA)
        let deletionRequests = LockedCounter()
        SessionRefreshURLProtocol.install { request in
            let url = try XCTUnwrap(request.url)
            let response = try XCTUnwrap(HTTPURLResponse(
                url: url,
                statusCode: 200,
                httpVersion: "HTTP/1.1",
                headerFields: ["Content-Type": "application/json"]
            ))
            if url.path == "/users/me" {
                let encoder = JSONEncoder()
                encoder.keyEncodingStrategy = .convertToSnakeCase
                return (response, try encoder.encode(riderB))
            }
            XCTAssertEqual(url.path, "/compliance/account")
            deletionRequests.increment()
            return (response, try accountDeletionStatusJSON(
                requestID: "22222222-2222-4222-8222-222222222222"
            ))
        }
        let configuration = URLSessionConfiguration.ephemeral
        configuration.protocolClasses = [SessionRefreshURLProtocol.self]
        let credentials = SessionCredentialStoreFake()
        let client = APIClient(
            configuration: configuration,
            sessionCredentials: credentials
        )
        try await client.adoptSession(AuthTokenResponse(
            userId: riderA.id,
            wallet: riderA.wallet,
            accessToken: "access-a",
            accessExpiresAt: nil,
            refreshToken: "refresh-a",
            refreshExpiresAt: nil
        ))

        do {
            _ = try await client.me()
            XCTFail("bearer A must reject a /users/me response naming B")
        } catch APIError.notAuthenticated {
            // Exact bearer ownership remains A.
        }
        let cachedMe: User? = await MainActor.run {
            ResponseCache.shared.value(User.self, path: "/users/me")
        }
        XCTAssertNil(cachedMe, "a rejected rider B response must never enter rider A's cache")
        XCTAssertEqual(CachedRiderStore.load()?.id, riderA.id)
        let capabilityB = AccountDeletionCapability(
            requestID: "22222222-2222-4222-8222-222222222222",
            statusToken: String(repeating: "b", count: 43),
            owner: ownerB,
            inventoryDigest: AccountDeletionLocalInventory.empty.digest,
            acknowledgedRideIDs: [],
            unuploadedRidesAcknowledged: true,
            createdAt: Date(timeIntervalSince1970: 1_777_000_000),
            localCleanupCompletedAt: nil
        )
        do {
            _ = try await client.create(capability: capabilityB)
            XCTFail("bearer A must not authorize B's account DELETE")
        } catch APIError.notAuthenticated {
            // Owner correlation remained A.
        }

        let remainsAuthenticated = await client.isAuthenticated
        XCTAssertTrue(remainsAuthenticated)
        XCTAssertEqual(credentials.storedToken, "refresh-a")
        XCTAssertEqual(deletionRequests.value, 0)
    }

    func testDeletionFenceBlocksOrdinaryMutationsButNotReadsRecoveryOrOtherOwner() async throws {
        defer {
            SessionRefreshURLProtocol.reset()
            AccountDeletionSessionRecordStore.clear()
        }
        let riderA = sessionRider(id: "mutation-fenced-owner-a")
        let ownerA = RecordingOwner(user: riderA)
        let riderB = sessionRider(id: "mutation-unfenced-owner-b")
        let capabilityA = AccountDeletionCapability(
            requestID: "33333333-3333-4333-8333-333333333333",
            statusToken: String(repeating: "c", count: 43),
            owner: ownerA,
            inventoryDigest: AccountDeletionLocalInventory.empty.digest,
            acknowledgedRideIDs: [],
            unuploadedRidesAcknowledged: true,
            createdAt: Date(timeIntervalSince1970: 1_777_000_000),
            localCleanupCompletedAt: nil
        )
        let processFence = AccountDeletionSessionRecord(state: .pending, owner: ownerA)
        XCTAssertFalse(AccountDeletionLocalFence.permitsAccountWork(
            owner: ownerA,
            sessionRecords: [],
            capabilityStates: [.unconfirmed(capabilityA)]
        ))
        XCTAssertTrue(AccountDeletionLocalFence.permitsAccountWork(
            owner: RecordingOwner(user: riderB),
            sessionRecords: [],
            capabilityStates: [.unconfirmed(capabilityA)]
        ))
        XCTAssertFalse(AccountDeletionLocalFence.permitsAccountWork(
            owner: nil,
            sessionRecords: [],
            capabilityStates: [.unconfirmed(capabilityA)]
        ))
        AccountDeletionProcessFence.record(processFence)
        CachedRiderStore.save(riderA)

        let ordinaryWrites = LockedCounter()
        let recoveryWrites = LockedCounter()
        SessionRefreshURLProtocol.install { request in
            let url = try XCTUnwrap(request.url)
            let response = try XCTUnwrap(HTTPURLResponse(
                url: url,
                statusCode: 200,
                httpVersion: "HTTP/1.1",
                headerFields: ["Content-Type": "application/json"]
            ))
            switch (request.httpMethod, url.path) {
            case ("GET", "/compliance/account/preflight"):
                return (response, try JSONSerialization.data(withJSONObject: [
                    "contract_version": AccountDeletionContract.version,
                    "allowed": true,
                    "available": true,
                    "blockers": [],
                    "checked_at": "2026-08-25T12:00:00Z",
                ]))
            case ("DELETE", "/compliance/account"):
                recoveryWrites.increment()
                return (response, try accountDeletionStatusJSON(
                    requestID: capabilityA.requestID
                ))
            default:
                ordinaryWrites.increment()
                let encoder = JSONEncoder()
                encoder.keyEncodingStrategy = .convertToSnakeCase
                return (response, try encoder.encode(riderB))
            }
        }
        let configuration = URLSessionConfiguration.ephemeral
        configuration.protocolClasses = [SessionRefreshURLProtocol.self]
        let client = APIClient(
            configuration: configuration,
            sessionCredentials: SessionCredentialStoreFake()
        )
        try await client.adoptSession(AuthTokenResponse(
            userId: ownerA.id,
            wallet: ownerA.wallet,
            accessToken: "access-a",
            accessExpiresAt: nil,
            refreshToken: "refresh-a",
            refreshExpiresAt: nil
        ))

        let mutations: [() async throws -> Void] = [
            { _ = try await client.updateProfile(displayName: .some("Blocked")) },
            { _ = try await client.createPrivacyZone(
                latitude: 40, longitude: -105, radiusM: 200, label: nil
            ) },
            { try await client.updateRidePrivacy(
                rideId: "blocked-ride",
                publication: RidePublicationSettings(
                    visibility: .onlyYou,
                    mapVisibility: .hideEntire,
                    mapHideStartM: 0,
                    mapHideEndM: 0
                )
            ) },
            { try await client.deletePrivacyZone(id: "blocked-zone") },
        ]
        for mutation in mutations {
            do {
                try await mutation()
                XCTFail("same-owner deletion fence must reject every mutation verb")
            } catch APIError.notAuthenticated {
                // Must fail before URLSession can send bytes.
            }
        }
        XCTAssertEqual(ordinaryWrites.value, 0)
        _ = try await client.preflight()
        _ = try await client.create(capability: capabilityA)
        XCTAssertEqual(recoveryWrites.value, 1)

        XCTAssertTrue(AccountDeletionLocalFence.permitsAccountWork(
            owner: RecordingOwner(user: riderB),
            sessionRecords: [processFence],
            capabilityStates: [.none]
        ))
        XCTAssertEqual(ordinaryWrites.value, 0)
    }

    func testColdRefreshDeletionRefusalDoesNotBorrowCachedOwner() async throws {
        defer {
            SessionRefreshURLProtocol.reset()
            AccountDeletionSessionRecordStore.clear()
        }
        let cachedRider = sessionRider(id: "stale-cached-owner-a")
        CachedRiderStore.save(cachedRider)
        SessionRefreshURLProtocol.install { request in
            XCTAssertEqual(request.url?.path, "/auth/refresh")
            return try deletionRefusalHTTPResponse(
                for: request,
                code: AccountDeletionSessionState.deleted.rawValue
            )
        }
        let configuration = URLSessionConfiguration.ephemeral
        configuration.protocolClasses = [SessionRefreshURLProtocol.self]
        let credentials = SessionCredentialStoreFake(token: "refresh-owner-b")
        let client = APIClient(
            configuration: configuration,
            sessionCredentials: credentials
        )

        let outcome = await client.resumeSession()
        let context = await client.accountDeletionRefusalContext()

        XCTAssertEqual(outcome, .accountDeletion(.deleted))
        XCTAssertNotNil(context?.recoveryID)
        XCTAssertNil(
            context?.attemptedOwner,
            "a cached profile is not durable authority for the stored refresh credential"
        )
        XCTAssertNil(context?.attemptedWallet)
    }

    func testStaleVerificationResultCannotReplaceOrClearNewerSession() async throws {
        defer {
            SessionRefreshURLProtocol.reset()
            AccountDeletionSessionRecordStore.clear()
        }
        for endpoint in ["/auth/verify", "/auth/privy/verify"] {
            for returnsDeletionRefusal in [false, true] {
                AccountDeletionSessionRecordStore.clear()
                let entered = DispatchSemaphore(value: 0)
                let release = DispatchSemaphore(value: 0)
                SessionRefreshURLProtocol.install { request in
                    let url = try XCTUnwrap(request.url)
                    XCTAssertEqual(url.path, endpoint)
                    entered.signal()
                    guard release.wait(timeout: .now() + 10) == .success else {
                        throw URLError(.timedOut)
                    }
                    if returnsDeletionRefusal {
                        return try deletionRefusalHTTPResponse(
                            for: request,
                            code: AccountDeletionSessionState.pending.rawValue
                        )
                    }
                    let response = try XCTUnwrap(HTTPURLResponse(
                        url: url,
                        statusCode: 200,
                        httpVersion: "HTTP/1.1",
                        headerFields: ["Content-Type": "application/json"]
                    ))
                    let body = try JSONSerialization.data(withJSONObject: [
                        "user_id": "verification-owner-a",
                        "wallet": "verification-wallet-a",
                        "access_token": "access-a",
                        "access_expires_at": "2099-01-01T00:00:00Z",
                        "refresh_token": "refresh-a",
                        "refresh_expires_at": "2099-02-01T00:00:00Z",
                    ])
                    return (response, body)
                }
                let configuration = URLSessionConfiguration.ephemeral
                configuration.protocolClasses = [SessionRefreshURLProtocol.self]
                let credentials = SessionCredentialStoreFake()
                let client = APIClient(
                    configuration: configuration,
                    sessionCredentials: credentials
                )
                let notifications = LockedDeletionNotificationRecorder()
                let observer = NotificationCenter.default.addObserver(
                    forName: .brAccountDeletionSessionState,
                    object: nil,
                    queue: nil
                ) { notification in
                    guard let source = notification.object as AnyObject?,
                          source === client
                    else { return }
                    notifications.record(notification)
                }

                let verification = Task { () -> String? in
                    do {
                        if endpoint == "/auth/verify" {
                            _ = try await client.verifySignature(
                                wallet: "verification-wallet-a",
                                signature: "signature-a",
                                nonce: "nonce-a",
                                inviteCode: nil
                            )
                        } else {
                            _ = try await client.verifyPrivyToken(
                                wallet: "verification-wallet-a",
                                privyToken: "privy-token-a",
                                inviteCode: nil
                            )
                        }
                        return "stale verification unexpectedly succeeded"
                    } catch APIError.notAuthenticated {
                        return nil
                    } catch {
                        return "stale verification returned \(error)"
                    }
                }
                let didEnter = await Task.detached {
                    entered.wait(timeout: .now() + 10)
                }.value
                guard didEnter == .success else {
                    release.signal()
                    NotificationCenter.default.removeObserver(observer)
                    return XCTFail("verification never reached its response gate")
                }

                try await client.adoptSession(AuthTokenResponse(
                    userId: "replacement-owner-b",
                    wallet: "replacement-wallet-b",
                    accessToken: "access-b",
                    accessExpiresAt: nil,
                    refreshToken: "refresh-b",
                    refreshExpiresAt: nil
                ))
                release.signal()

                let verificationFailure = await verification.value
                let remainsAuthenticated = await client.isAuthenticated
                let refusalContext = await client.accountDeletionRefusalContext()
                XCTAssertNil(
                    verificationFailure,
                    "\(endpoint), deletion refusal=\(returnsDeletionRefusal)"
                )
                XCTAssertTrue(remainsAuthenticated)
                XCTAssertEqual(credentials.storedToken, "refresh-b")
                XCTAssertTrue(notifications.snapshots.isEmpty)
                XCTAssertNil(refusalContext)
                XCTAssertTrue(
                    AccountDeletionEmergencyFenceStore.records.isEmpty,
                    "stale \(endpoint) work must not leave an emergency fence"
                )
                XCTAssertTrue(
                    AccountDeletionSessionRecordStore.records().isEmpty,
                    "stale \(endpoint) work must not leave a deletion journal"
                )
                NotificationCenter.default.removeObserver(observer)
            }
        }
    }

    /// A wallet-attributed sign-in refusal belongs only to that attempted
    /// owner. If its emergency witness could not be cleared before another
    /// rider signs in, the next authenticated refusal must open a new,
    /// ownerless recovery slot without mutating the retained first slot.
    func testNewAuthGenerationCannotReusePriorWalletDeletionRefusalContext() async throws {
        defer {
            SessionRefreshURLProtocol.reset()
            AccountDeletionSessionRecordStore.clear()
        }
        SessionRefreshURLProtocol.install { request in
            XCTAssertEqual(request.url?.path, "/auth/verify")
            return try deletionRefusalHTTPResponse(
                for: request,
                code: AccountDeletionSessionState.pending.rawValue
            )
        }
        let configuration = URLSessionConfiguration.ephemeral
        configuration.protocolClasses = [SessionRefreshURLProtocol.self]
        let client = APIClient(
            configuration: configuration,
            sessionCredentials: SessionCredentialStoreFake()
        )
        let notifications = LockedDeletionNotificationRecorder()
        let observer = NotificationCenter.default.addObserver(
            forName: .brAccountDeletionSessionState,
            object: nil,
            queue: nil
        ) { notification in
            guard let source = notification.object as AnyObject?, source === client else {
                return
            }
            notifications.record(notification)
        }
        defer { NotificationCenter.default.removeObserver(observer) }

        do {
            _ = try await client.verifySignature(
                wallet: "Wallet-A-ExactCase",
                signature: "signature-a",
                nonce: "nonce-a",
                inviteCode: nil
            )
            XCTFail("wallet A deletion refusal must stop sign-in")
        } catch APIError.notAuthenticated {
            // Model the emergency witness surviving a later failed journal clear.
        }
        let refusalA = try XCTUnwrap(notifications.snapshots.last)
        let recoveryIDA = try XCTUnwrap(refusalA.recoveryID)
        let ledgerA = AccountDeletionEmergencyFenceStore.records
        XCTAssertEqual(refusalA.attemptedWallet, "Wallet-A-ExactCase")
        XCTAssertEqual(ledgerA.map(\.recoveryID), [recoveryIDA])

        try await client.adoptSession(AuthTokenResponse(
            userId: "rider-b",
            wallet: "Wallet-B-ExactCase",
            accessToken: "access-b",
            accessExpiresAt: nil,
            refreshToken: "refresh-b",
            refreshExpiresAt: nil
        ))
        XCTAssertEqual(
            AccountDeletionEmergencyFenceStore.records,
            ledgerA,
            "auth adoption must not erase wallet A's unresolved durable witness"
        )

        SessionRefreshURLProtocol.install { request in
            XCTAssertEqual(request.url?.path, "/users/me")
            return try deletionRefusalHTTPResponse(
                for: request,
                code: AccountDeletionSessionState.deleted.rawValue
            )
        }
        do {
            _ = try await client.me()
            XCTFail("wallet B deletion refusal must stop account work")
        } catch APIError.notAuthenticated {
            // Expected after the exact original middleware response is routed.
        }

        let refusalB = try XCTUnwrap(notifications.snapshots.last)
        let recoveryIDB = try XCTUnwrap(refusalB.recoveryID)
        XCTAssertNil(refusalB.attemptedWallet)
        XCTAssertNotEqual(recoveryIDB, recoveryIDA)
        XCTAssertEqual(
            Set(AccountDeletionEmergencyFenceStore.records.map(\.recoveryID)),
            Set([recoveryIDA, recoveryIDB]),
            "wallet A's row survives while wallet B receives a fresh ownerless slot"
        )
    }

    /// A response is authorized by the bearer generation that sent it, not by
    /// whichever rider happens to own the actor when URLSession returns.
    func testStaleAuthenticatedDeletionResponseCannotJournalReplacementRider() async throws {
        defer {
            SessionRefreshURLProtocol.reset()
            AccountDeletionSessionRecordStore.clear()
        }
        let entered = DispatchSemaphore(value: 0)
        let release = DispatchSemaphore(value: 0)
        defer { release.signal() }
        SessionRefreshURLProtocol.install { request in
            XCTAssertEqual(request.url?.path, "/users/me")
            entered.signal()
            guard release.wait(timeout: .now() + 10) == .success else {
                throw URLError(.timedOut)
            }
            return try deletionRefusalHTTPResponse(
                for: request,
                code: AccountDeletionSessionState.deleted.rawValue
            )
        }
        let configuration = URLSessionConfiguration.ephemeral
        configuration.protocolClasses = [SessionRefreshURLProtocol.self]
        let client = APIClient(
            configuration: configuration,
            sessionCredentials: SessionCredentialStoreFake(),
            accountMutationPermitted: { _ in true }
        )
        try await client.adoptSession(AuthTokenResponse(
            userId: "rider-a",
            wallet: "wallet-a",
            accessToken: "access-a",
            accessExpiresAt: nil,
            refreshToken: "refresh-a",
            refreshExpiresAt: nil
        ))
        let notifications = LockedDeletionNotificationRecorder()
        let observer = NotificationCenter.default.addObserver(
            forName: .brAccountDeletionSessionState,
            object: nil,
            queue: nil
        ) { notification in
            guard let source = notification.object as AnyObject?, source === client else {
                return
            }
            notifications.record(notification)
        }
        defer { NotificationCenter.default.removeObserver(observer) }

        let staleRequest = Task { () -> String? in
            do {
                _ = try await client.updateWeight(kg: 71)
                return "stale request unexpectedly succeeded"
            } catch APIError.notAuthenticated {
                return nil
            } catch {
                return "stale request returned \(error)"
            }
        }
        let waitResult = await Task.detached {
            entered.wait(timeout: .now() + 10)
        }.value
        guard waitResult == .success else {
            return XCTFail("stale rider A request never reached the response gate")
        }

        try await client.adoptSession(AuthTokenResponse(
            userId: "rider-b",
            wallet: "wallet-b",
            accessToken: "access-b",
            accessExpiresAt: nil,
            refreshToken: "refresh-b",
            refreshExpiresAt: nil
        ))
        release.signal()

        let staleFailure = await staleRequest.value
        let authenticated = await client.isAuthenticated
        XCTAssertNil(staleFailure)
        XCTAssertTrue(notifications.snapshots.isEmpty)
        XCTAssertTrue(AccountDeletionEmergencyFenceStore.records.isEmpty)
        XCTAssertTrue(authenticated)
    }

    /// The destructive request is admitted for the bearer generation and
    /// exact owner that entered it. If proactive refresh suspends and a
    /// replacement rider signs in, the original call must die before URLSession
    /// can send DELETE with the replacement rider's bearer.
    func testAccountDeletionCannotSendWithReplacementBearerAfterProactiveRefresh() async throws {
        defer { SessionRefreshURLProtocol.reset() }
        let refreshEntered = DispatchSemaphore(value: 0)
        let releaseRefresh = DispatchSemaphore(value: 0)
        let deletionRequests = LockedCounter()
        defer { releaseRefresh.signal() }
        SessionRefreshURLProtocol.install { request in
            let url = try XCTUnwrap(request.url)
            if url.path == "/auth/refresh" {
                refreshEntered.signal()
                guard releaseRefresh.wait(timeout: .now() + 10) == .success else {
                    throw URLError(.timedOut)
                }
                let response = try XCTUnwrap(HTTPURLResponse(
                    url: url,
                    statusCode: 503,
                    httpVersion: "HTTP/1.1",
                    headerFields: ["Content-Type": "application/json"]
                ))
                return (response, Data("service unavailable".utf8))
            }

            XCTAssertEqual(url.path, "/compliance/account")
            XCTAssertEqual(request.httpMethod, "DELETE")
            deletionRequests.increment()
            let response = try XCTUnwrap(HTTPURLResponse(
                url: url,
                statusCode: 200,
                httpVersion: "HTTP/1.1",
                headerFields: ["Content-Type": "application/json"]
            ))
            return (response, Data())
        }

        let riderA = sessionRider(id: "destructive-rider-a")
        let ownerA = RecordingOwner(user: riderA)
        CachedRiderStore.save(riderA)
        let configuration = URLSessionConfiguration.ephemeral
        configuration.protocolClasses = [SessionRefreshURLProtocol.self]
        let client = APIClient(
            configuration: configuration,
            sessionCredentials: SessionCredentialStoreFake()
        )
        let expiresSoon = ISO8601DateFormatter().string(
            from: Date().addingTimeInterval(30)
        )
        try await client.adoptSession(AuthTokenResponse(
            userId: riderA.id,
            wallet: riderA.wallet,
            accessToken: "access-a",
            accessExpiresAt: expiresSoon,
            refreshToken: "refresh-a",
            refreshExpiresAt: nil
        ))
        let capability = AccountDeletionCapability(
            requestID: "11111111-1111-4111-8111-111111111111",
            statusToken: String(repeating: "a", count: 43),
            owner: ownerA,
            inventoryDigest: AccountDeletionLocalInventory.empty.digest,
            acknowledgedRideIDs: [],
            unuploadedRidesAcknowledged: true,
            createdAt: Date(timeIntervalSince1970: 1_777_000_000),
            localCleanupCompletedAt: nil
        )

        let deletion = Task { () -> String? in
            do {
                _ = try await client.create(capability: capability)
                return "account deletion unexpectedly succeeded"
            } catch APIError.notAuthenticated {
                return nil
            } catch {
                return "account deletion returned \(error)"
            }
        }
        let entered = await Task.detached {
            refreshEntered.wait(timeout: .now() + 10)
        }.value
        guard entered == .success else {
            return XCTFail("account deletion never entered proactive refresh")
        }

        let riderB = sessionRider(id: "replacement-rider-b")
        try await client.adoptSession(AuthTokenResponse(
            userId: riderB.id,
            wallet: riderB.wallet,
            accessToken: "access-b",
            accessExpiresAt: nil,
            refreshToken: "refresh-b",
            refreshExpiresAt: nil
        ))
        releaseRefresh.signal()

        let deletionFailure = await deletion.value
        XCTAssertNil(deletionFailure)
        XCTAssertEqual(
            deletionRequests.value,
            0,
            "rider A's destructive call must not send with rider B's bearer"
        )
    }

    /// Both callers awaiting one refresh flight must cross the same durable
    /// postflight barrier. The joiner may not publish account deletion before
    /// the flight owner has armed the crash-safe recovery witness.
    func testSharedDeletionRefreshArmsOneWitnessBeforeBothNotifications() async throws {
        defer {
            GatedDeletionRefreshURLProtocol.reset()
            AccountDeletionSessionRecordStore.clear()
        }
        let responder = GatedDeletionRefreshResponder()
        defer { responder.releaseRefresh() }
        GatedDeletionRefreshURLProtocol.install(responder)
        let credentials = SessionCredentialStoreFake(token: "deletion-refresh-token")
        let configuration = URLSessionConfiguration.ephemeral
        configuration.protocolClasses = [GatedDeletionRefreshURLProtocol.self]
        let client = APIClient(
            configuration: configuration,
            sessionCredentials: credentials,
            refreshFlightJoinObserver: { responder.recordRefreshFlightJoin() },
            accountMutationPermitted: { _ in true }
        )
        try await client.adoptSession(AuthTokenResponse(
            userId: "deleting-rider",
            wallet: "0xExAcT-WaLLeT",
            accessToken: "rejected-access-token",
            accessExpiresAt: nil,
            refreshToken: "deletion-refresh-token",
            refreshExpiresAt: nil
        ))

        let notifications = LockedDeletionNotificationRecorder()
        let observer = NotificationCenter.default.addObserver(
            forName: .brAccountDeletionSessionState,
            object: nil,
            queue: nil
        ) { notification in
            guard let source = notification.object as AnyObject?, source === client else {
                return
            }
            notifications.record(notification)
        }
        defer { NotificationCenter.default.removeObserver(observer) }

        // The responder and refresh-flight observer establish overlap below.
        // Inherit the test's priority: polling for a background-priority task
        // does not escalate it, so a busy simulator can starve setup entirely.
        let owner = Task { () -> String? in
            do {
                _ = try await client.updateWeight(kg: 71)
                return "owner request unexpectedly succeeded"
            } catch APIError.notAuthenticated {
                return nil
            } catch {
                return "owner request returned \(error)"
            }
        }
        try await responder.waitUntilRefreshEntered()

        let joiner = Task { () -> String? in
            do {
                _ = try await client.updateWeight(kg: 72)
                return "joiner request unexpectedly succeeded"
            } catch APIError.notAuthenticated {
                return nil
            } catch {
                return "joiner request returned \(error)"
            }
        }
        try await responder.waitUntilAccountRequests(2)
        try await responder.waitUntilRefreshFlightJoined()
        responder.releaseRefresh()

        let ownerFailure = await owner.value
        let joinerFailure = await joiner.value
        XCTAssertNil(ownerFailure)
        XCTAssertNil(joinerFailure)

        let snapshots = notifications.snapshots
        XCTAssertEqual(snapshots.count, 2)
        let recoveryIDs = snapshots.compactMap(\.recoveryID)
        XCTAssertEqual(recoveryIDs.count, 2, "neither notification may cross without a witness")
        XCTAssertEqual(Set(recoveryIDs).count, 1, "one refresh flight owns one recovery slot")
        XCTAssertTrue(
            snapshots.allSatisfy(\.witnessWasAlreadyDurable),
            "the emergency ledger must contain the shared recovery ID before each post"
        )
    }

    /// A successful backend exchange is not a successful sign-in until the
    /// refresh token is durable. The old production path installed the access
    /// token first and silently ignored the Keychain status.
    func testInitialSignInRefusesMemoryOnlySessionWhenCredentialSaveFails() async throws {
        defer { SessionRefreshURLProtocol.reset() }
        let credentials = SessionCredentialStoreFake(
            saveError: .unavailable(status: errSecInteractionNotAllowed)
        )
        SessionRefreshURLProtocol.install { request in
            XCTAssertEqual(request.url?.path, "/auth/privy/verify")
            return try sessionTokenHTTPResponse(for: request)
        }
        let configuration = URLSessionConfiguration.ephemeral
        configuration.protocolClasses = [SessionRefreshURLProtocol.self]
        let client = APIClient(
            configuration: configuration,
            sessionCredentials: credentials
        )

        do {
            _ = try await client.verifyPrivyToken(
                wallet: "session-wallet",
                privyToken: "privy-token",
                inviteCode: nil
            )
            XCTFail("sign-in must not succeed with a memory-only session")
        } catch let error as SessionCredentialStoreError {
            XCTAssertEqual(
                error,
                .unavailable(status: errSecInteractionNotAllowed)
            )
        }

        let authenticated = await client.isAuthenticated
        XCTAssertFalse(authenticated)
        XCTAssertNil(credentials.storedToken)
    }

    /// A temporarily unreadable Keychain is not the same thing as a device
    /// with no session. AppSession maps transient resume to the cached rider
    /// instead of forcing a new email code.
    func testCredentialReadFailureIsTransientNotSignedOut() async {
        let credentials = SessionCredentialStoreFake(
            readError: .unavailable(status: errSecInteractionNotAllowed)
        )
        let client = APIClient(
            configuration: .ephemeral,
            sessionCredentials: credentials
        )

        let outcome = await client.resumeSession()
        let authenticated = await client.isAuthenticated
        XCTAssertEqual(outcome, .transient)
        XCTAssertFalse(authenticated)
    }

    /// If the server rotates successfully but the first durable write is
    /// temporarily unavailable, retain that returned generation in-process
    /// and retry the write before making another server request.
    func testRotatedSessionRetriesDurabilityBeforeAnotherRefresh() async throws {
        defer { SessionRefreshURLProtocol.reset() }
        let credentials = SessionCredentialStoreFake(
            token: "refresh-generation-1",
            saveError: .unavailable(status: errSecInteractionNotAllowed)
        )
        let requestCount = LockedCounter()
        SessionRefreshURLProtocol.install { request in
            XCTAssertEqual(request.url?.path, "/auth/refresh")
            requestCount.increment()
            return try sessionTokenHTTPResponse(
                for: request,
                refreshToken: "refresh-generation-2"
            )
        }
        let configuration = URLSessionConfiguration.ephemeral
        configuration.protocolClasses = [SessionRefreshURLProtocol.self]
        let client = APIClient(
            configuration: configuration,
            sessionCredentials: credentials
        )

        let unavailableOutcome = await client.resumeSession()
        let unavailableAuthentication = await client.isAuthenticated
        XCTAssertEqual(unavailableOutcome, .transient)
        XCTAssertFalse(unavailableAuthentication)
        XCTAssertEqual(credentials.storedToken, "refresh-generation-1")
        XCTAssertEqual(requestCount.value, 1)

        credentials.allowSaves()
        let resumedOutcome = await client.resumeSession()
        let resumedAuthentication = await client.isAuthenticated
        XCTAssertEqual(resumedOutcome, .resumed)
        XCTAssertTrue(resumedAuthentication)
        XCTAssertEqual(credentials.storedToken, "refresh-generation-2")
        XCTAssertEqual(
            requestCount.value,
            1,
            "the already-returned token must become durable without rotating again"
        )
    }

    func testDeletionRefreshRefusalRetainsCredentialUntilLifecycleJournalIsDurable() async throws {
        defer { SessionRefreshURLProtocol.reset() }
        let credentials = SessionCredentialStoreFake(token: "deletion-refresh-token")
        SessionRefreshURLProtocol.install { request in
            let response = try XCTUnwrap(
                HTTPURLResponse(
                    url: try XCTUnwrap(request.url),
                    statusCode: 401,
                    httpVersion: "HTTP/1.1",
                    headerFields: ["Content-Type": "application/json"]
                )
            )
            let body = try JSONSerialization.data(withJSONObject: [
                "detail": ["code": AccountDeletionSessionState.pending.rawValue],
            ])
            return (response, body)
        }
        let configuration = URLSessionConfiguration.ephemeral
        configuration.protocolClasses = [SessionRefreshURLProtocol.self]
        let client = APIClient(
            configuration: configuration,
            sessionCredentials: credentials
        )

        let outcome = await client.resumeSession()

        XCTAssertEqual(outcome, .accountDeletion(.pending))
        XCTAssertEqual(
            credentials.storedToken,
            "deletion-refresh-token",
            "AppSession owns credential teardown only after its required journal read-back"
        )
    }

    /// If AppSession cannot persist the deletion journal after an in-use 401,
    /// the durable refresh credential must survive so a later resume can ask
    /// the server again. The rejected access generation itself must not
    /// survive: otherwise `resumeSession()` short-circuits to `.resumed` and
    /// bypasses the authoritative deletion refusal.
    func testDeletionRefreshRefusalRetriesAfterJournalPersistenceFailure() async throws {
        defer { SessionRefreshURLProtocol.reset() }
        let credentials = SessionCredentialStoreFake(token: "deletion-refresh-token")
        let refreshRequests = LockedCounter()
        SessionRefreshURLProtocol.install { request in
            let path = try XCTUnwrap(request.url?.path)
            if path == "/auth/refresh" {
                refreshRequests.increment()
            } else {
                XCTAssertEqual(path, "/users/me")
            }
            let response = try XCTUnwrap(
                HTTPURLResponse(
                    url: try XCTUnwrap(request.url),
                    statusCode: 401,
                    httpVersion: "HTTP/1.1",
                    headerFields: ["Content-Type": "application/json"]
                )
            )
            let detail: [String: Any]
            if path == "/auth/refresh" {
                detail = ["code": AccountDeletionSessionState.pending.rawValue]
            } else {
                detail = ["code": "access_token_expired"]
            }
            let body = try JSONSerialization.data(withJSONObject: ["detail": detail])
            return (response, body)
        }
        let configuration = URLSessionConfiguration.ephemeral
        configuration.protocolClasses = [SessionRefreshURLProtocol.self]
        let client = APIClient(
            configuration: configuration,
            sessionCredentials: credentials
        )
        try await client.adoptSession(
            AuthTokenResponse(
                userId: "deleting-rider",
                wallet: "deleting-wallet",
                accessToken: "rejected-access-token",
                accessExpiresAt: nil,
                refreshToken: "deletion-refresh-token",
                refreshExpiresAt: nil
            )
        )

        do {
            _ = try await client.me()
            XCTFail("the in-use deletion refusal must reject account work")
        } catch APIError.notAuthenticated {
            // AppSession receives the deletion notification. Model its
            // required journal write failing by deliberately not clearing
            // the durable credential before the next resume.
        }

        let secondOutcome = await client.resumeSession()

        XCTAssertEqual(secondOutcome, .accountDeletion(.pending))
        XCTAssertEqual(refreshRequests.value, 2, "the second resume must retry server truth")
        let authenticated = await client.isAuthenticated
        XCTAssertFalse(authenticated)
        XCTAssertEqual(
            credentials.storedToken,
            "deletion-refresh-token",
            "the lifecycle journal still owns durable credential teardown"
        )
    }

    /// Cold launch has two legitimate callers: the foreground AppSession and
    /// BG upload reconciliation. They must share one rotation, and a caller
    /// arriving just after that flight must reuse the in-memory session
    /// instead of rotating again. The second response deliberately models the
    /// production `refresh_rotated` result so this fails on the old behavior.
    func testColdStartResumeUsesOneRotationAcrossOverlappingAndSequentialCallers() async {
        let original = KeychainStore.read(.refreshToken)
        defer {
            SessionRefreshURLProtocol.reset()
            if let original {
                KeychainStore.save(original, for: .refreshToken)
            } else {
                KeychainStore.delete(.refreshToken)
            }
        }

        KeychainStore.save("refresh-generation-1", for: .refreshToken)
        let recorder = SessionRefreshRecorder()
        SessionRefreshURLProtocol.install { try recorder.response(for: $0) }
        let configuration = URLSessionConfiguration.ephemeral
        configuration.protocolClasses = [SessionRefreshURLProtocol.self]
        let client = APIClient(configuration: configuration)

        async let foreground = client.resumeSession()
        async let background = client.resumeSession()
        let foregroundOutcome = await foreground
        let backgroundOutcome = await background
        let justAfterOutcome = await client.resumeSession()

        XCTAssertEqual(foregroundOutcome, .resumed)
        XCTAssertEqual(backgroundOutcome, .resumed)
        XCTAssertEqual(justAfterOutcome, .resumed)
        XCTAssertEqual(recorder.presentedTokens, ["refresh-generation-1"])
        XCTAssertEqual(recorder.requestCount, 1, "one cold start must rotate only once")
        XCTAssertEqual(KeychainStore.read(.refreshToken), "refresh-generation-2")
    }

    // MARK: - Resume ladder

    /// THE note-11 regression: relaunch while the server is unreachable must
    /// resume to the rider's cached state — not onboarding, and the stored
    /// session must survive untouched.
    @MainActor
    func testTransientResumeFailureKeepsRiderSignedInOnCachedState() async {
        let rider = sessionRider(id: "session-rider-offline")
        CachedRiderStore.save(rider)
        let auth = AuthClientFake(resumeOutcomes: [.transient])
        let session = makeSession(auth: auth)

        await session.resume()

        guard case let .signedIn(user) = session.phase else {
            return XCTFail("offline relaunch with a cached rider must stay signed in")
        }
        XCTAssertEqual(user.id, rider.id)
        XCTAssertEqual(session.connectivity, .unreachable)
        XCTAssertNil(session.sessionEndNotice)
        let logoutCount = await auth.logoutCount
        let clearCount = await auth.clearLocalCount
        XCTAssertEqual(logoutCount, 0, "a transient failure must not revoke the session")
        XCTAssertEqual(clearCount, 0, "a transient failure must not drop stored tokens")
    }

    @MainActor
    func testTransientResumeWithoutCacheShowsOnboardingWithoutNotice() async {
        let auth = AuthClientFake(resumeOutcomes: [.transient])
        let session = makeSession(auth: auth)

        await session.resume()

        guard case .signedOut = session.phase else {
            return XCTFail("fresh install offline lands on onboarding")
        }
        XCTAssertNil(session.sessionEndNotice, "no false expiry story on a fresh install")
    }

    @MainActor
    func testTombstonedRelaunchRehydratesDeletionFenceWithoutCurrentUser() async throws {
        let owner = RecordingOwner(id: "deleted-rider", wallet: "deleted-wallet")
        let capability = AccountDeletionCapability(
            requestID: "11111111-1111-4111-8111-111111111111",
            statusToken: String(repeating: "a", count: 43),
            owner: owner,
            inventoryDigest: AccountDeletionLocalInventory.empty.digest,
            acknowledgedRideIDs: [],
            unuploadedRidesAcknowledged: true,
            createdAt: Date(timeIntervalSince1970: 1_777_000_000),
            localCleanupCompletedAt: nil
        )
        let uploads = DeletionFreezeUploadRuntimeSpy()
        let recordings = SessionRecordingRuntimeSpy()
        let store = SessionDeletionCapabilityStore(capability: capability)
        let session = AppSession(
            rideUploads: uploads,
            rideRecordings: recordings,
            authClient: AuthClientFake(resumeOutcomes: []),
            accountDeletionCapabilityStore: store
        )
        XCTAssertNil(session.currentUser)
        PushRouter.shared.pending = .settlements
        defer { PushRouter.shared.clearAccountData() }

        try await session.accountDeletionCapabilityDidChange()

        let frozenOwners = await uploads.frozenOwners
        let deactivations = await recordings.deactivations
        XCTAssertEqual(frozenOwners, [owner])
        XCTAssertEqual(deactivations, 1)
        XCTAssertNil(PushRouter.shared.pending)
    }

    @MainActor
    func testDeletionCapabilityForDifferentSignedInOwnerFreezesNothing() async {
        let owner = RecordingOwner(id: "deleted-rider", wallet: "deleted-wallet")
        let capability = AccountDeletionCapability(
            requestID: "11111111-1111-4111-8111-111111111111",
            statusToken: String(repeating: "a", count: 43),
            owner: owner,
            inventoryDigest: AccountDeletionLocalInventory.empty.digest,
            acknowledgedRideIDs: [],
            unuploadedRidesAcknowledged: true,
            createdAt: Date(timeIntervalSince1970: 1_777_000_000),
            localCleanupCompletedAt: nil
        )
        let uploads = DeletionFreezeUploadRuntimeSpy()
        let recordings = SessionRecordingRuntimeSpy()
        let store = SessionDeletionCapabilityStore(capability: capability)
        let session = AppSession(
            rideUploads: uploads,
            rideRecordings: recordings,
            authClient: AuthClientFake(resumeOutcomes: []),
            accountDeletionCapabilityStore: store
        )
        session.phase = .signedIn(sessionRider(id: "different-rider"))

        do {
            try await session.accountDeletionCapabilityDidChange()
        } catch {
            XCTFail("rider A's capability must not block rider B: \(error)")
        }

        let frozenOwners = await uploads.frozenOwners
        let deactivations = await recordings.deactivations
        XCTAssertTrue(frozenOwners.isEmpty)
        XCTAssertEqual(deactivations, 0)

        await session.refreshRideUploads()
        let activatedUserIDs = await uploads.activatedUserIDs
        XCTAssertTrue(
            activatedUserIDs.contains("different-rider"),
            "a different signed-in owner must retain their own upload authority"
        )
        XCTAssertEqual(
            store.load(owner: owner),
            .available(capability),
            "routing rider B cannot erase rider A's retained capability"
        )
    }

    @MainActor
    func testCompletedDeletionForDifferentSignedInOwnerPurgesNothing() async {
        let owner = RecordingOwner(id: "deleted-rider", wallet: "deleted-wallet")
        let capability = AccountDeletionCapability(
            requestID: "11111111-1111-4111-8111-111111111111",
            statusToken: String(repeating: "a", count: 43),
            owner: owner,
            inventoryDigest: AccountDeletionLocalInventory.empty.digest,
            acknowledgedRideIDs: [],
            unuploadedRidesAcknowledged: true,
            createdAt: Date(timeIntervalSince1970: 1_777_000_000),
            localCleanupCompletedAt: nil
        )
        let completed = AccountDeletionStatus(
            contractVersion: AccountDeletionContract.version,
            requestID: capability.requestID,
            status: .completed,
            requestedAt: "2026-08-24T12:00:00Z",
            updatedAt: "2026-08-24T12:01:00Z",
            completedAt: "2026-08-24T12:01:00Z",
            blockers: [],
            failureCode: nil,
            retryable: false,
            attemptCount: 1
        )
        let recordings = SessionRecordingRuntimeSpy()
        let session = AppSession(
            rideUploads: DeletionFreezeUploadRuntimeSpy(),
            rideRecordings: recordings,
            authClient: AuthClientFake(resumeOutcomes: []),
            accountDeletionCapabilityStore: SessionDeletionCapabilityStore(capability: capability)
        )
        session.phase = .signedIn(sessionRider(id: "different-rider"))

        do {
            try await session.completeLocalAccountDeletion(
                capability: capability,
                status: completed
            )
            XCTFail("replacement rider must block local deletion cleanup")
        } catch {}

        let purgedOwners = await recordings.purgedOwners
        XCTAssertTrue(purgedOwners.isEmpty)
    }

    @MainActor
    func testResumeCrossingDeletionBoundaryCannotRecreateCachedIdentity() async throws {
        let owner = RecordingOwner(id: "deleted-rider", wallet: "deleted-wallet")
        let capability = AccountDeletionCapability(
            requestID: "11111111-1111-4111-8111-111111111111",
            statusToken: String(repeating: "a", count: 43),
            owner: owner,
            inventoryDigest: AccountDeletionLocalInventory.empty.digest,
            acknowledgedRideIDs: [],
            unuploadedRidesAcknowledged: true,
            createdAt: Date(timeIntervalSince1970: 1_777_000_000),
            localCleanupCompletedAt: nil
        )
        let capabilityStore = SessionDeletionCapabilityStore(capability: nil)
        let auth = GatedResumeAuthClient(user: sessionRider(id: owner.id))
        let uploads = DeletionFreezeUploadRuntimeSpy()
        let recordings = SessionRecordingRuntimeSpy()
        let session = AppSession(
            rideUploads: uploads,
            rideRecordings: recordings,
            authClient: auth,
            accountDeletionCapabilityStore: capabilityStore
        )
        let resume = Task { await session.resume() }
        while !(await auth.resumeEntered) {
            try await Task.sleep(for: .milliseconds(5))
        }

        capabilityStore.setCapability(capability)
        try await session.accountDeletionCapabilityDidChange()
        await auth.releaseResume()
        await resume.value

        XCTAssertNil(CachedRiderStore.load())
        XCTAssertNil(session.currentUser)
        let meCallCount = await auth.meCallCount
        XCTAssertEqual(meCallCount, 0)
    }

    /// Long-offline expiry: a truthful re-auth prompt, never a silent dead
    /// session — and the notice survives a relaunch.
    @MainActor
    func testExpiredSessionShowsTruthfulReauthPromptAcrossRelaunch() async {
        CachedRiderStore.save(sessionRider(id: "session-rider-expired"))
        let auth = AuthClientFake(resumeOutcomes: [.rejected(.expired)])
        let session = makeSession(auth: auth)

        await session.resume()

        guard case .signedOut = session.phase else {
            return XCTFail("expired session lands on onboarding")
        }
        XCTAssertEqual(session.sessionEndNotice, "Your session expired. Sign in again.")
        XCTAssertNil(CachedRiderStore.load(), "a dead session leaves no cached identity")

        // Relaunch: the reason persisted, so onboarding still tells the truth.
        let relaunch = makeSession(auth: AuthClientFake(resumeOutcomes: [.noStoredSession]))
        await relaunch.resume()
        XCTAssertEqual(relaunch.sessionEndNotice, "Your session expired. Sign in again.")
    }

    @MainActor
    func testSuccessfulResumeCachesRiderAndClearsStaleNotice() async {
        SessionEndReasonStore.record(.expired)
        let rider = sessionRider(id: "session-rider-live")
        let auth = AuthClientFake(
            resumeOutcomes: [.resumed], meResults: [.success(rider)]
        )
        let session = makeSession(auth: auth)

        await session.resume()

        guard case let .signedIn(user) = session.phase else {
            return XCTFail("resumed session is signed in")
        }
        XCTAssertEqual(user.id, rider.id)
        XCTAssertEqual(session.connectivity, .connected)
        XCTAssertNil(session.sessionEndNotice)
        XCTAssertEqual(CachedRiderStore.load()?.id, rider.id)
    }

    /// Tokens live but the profile read hiccuped: the cached identity keeps
    /// the rider in; per-surface reads own their own retries.
    @MainActor
    func testResumedSessionWithFailedProfileReadUsesCachedRider() async {
        let rider = sessionRider(id: "session-rider-cachedme")
        CachedRiderStore.save(rider)
        let auth = AuthClientFake(
            resumeOutcomes: [.resumed],
            meResults: [.failure(URLError(.timedOut))]
        )
        let session = makeSession(auth: auth)

        await session.resume()

        guard case let .signedIn(user) = session.phase else {
            return XCTFail("live tokens with a cached rider stay signed in")
        }
        XCTAssertEqual(user.id, rider.id)
        XCTAssertEqual(session.connectivity, .connected)
    }

    // MARK: - Forced logout (server 401 storm → one clean sign-out)

    @MainActor
    func testForcedSignOutIsOneCleanSignOutPreservingCustody() async {
        let rider = sessionRider(id: "session-rider-forced")
        CachedRiderStore.save(rider)
        let recordings = SessionRecordingRuntimeSpy()
        let auth = AuthClientFake(resumeOutcomes: [])
        let session = makeSession(auth: auth, recordings: recordings)
        session.phase = .signedIn(rider)

        NotificationCenter.default.post(
            name: .brSessionInvalidated,
            object: auth,
            userInfo: ["reason": SessionEndReason.revokedByServer.rawValue]
        )
        // The observer hops to the main actor; wait for the full teardown
        // (dropping local tokens is its final effect).
        let deadline = Date().addingTimeInterval(10)
        while Date() < deadline {
            if await auth.clearLocalCount == 1 { break }
            await Task.yield()
        }

        guard case .signedOut = session.phase else {
            return XCTFail("forced sign-out lands on onboarding")
        }
        XCTAssertEqual(session.sessionEndNotice, "You were signed out. Sign in again.")
        XCTAssertNil(CachedRiderStore.load())
        let logoutCount = await auth.logoutCount
        let clearCount = await auth.clearLocalCount
        XCTAssertEqual(logoutCount, 0, "the server already ended the session; no revoke theater")
        XCTAssertEqual(clearCount, 1, "local tokens are dropped exactly once")
        let discards = await recordings.discardCount
        XCTAssertEqual(discards, 0, "custody data survives a forced sign-out")
        let deactivations = await recordings.deactivations
        XCTAssertEqual(deactivations, 1, "owner services are unloaded, not destroyed")
    }

    @MainActor
    func testRiderSignOutRevokesServerSessionAndLeavesNoNotice() async {
        let rider = sessionRider(id: "session-rider-manual")
        CachedRiderStore.save(rider)
        let auth = AuthClientFake(resumeOutcomes: [])
        let session = makeSession(auth: auth)
        session.phase = .signedIn(rider)

        await session.signOut()

        guard case .signedOut = session.phase else {
            return XCTFail("sign-out lands on onboarding")
        }
        XCTAssertNil(session.sessionEndNotice)
        XCTAssertNil(SessionEndReasonStore.pending())
        XCTAssertNil(CachedRiderStore.load())
        let logoutCount = await auth.logoutCount
        XCTAssertEqual(logoutCount, 1, "a rider sign-out revokes the server session")
        let pushDeregistrations = await auth.pushDeregistrations
        XCTAssertEqual(
            pushDeregistrations, 1,
            "sign-out removes this install's push registration while the session is live"
        )
    }

    // MARK: - Helpers

    @MainActor
    private func makeSession(
        auth: AuthClientFake,
        recordings: any AppSessionRideRecordingRuntime = SessionRecordingRuntimeSpy()
    ) -> AppSession {
        AppSession(
            rideUploads: SessionUploadRuntimeNoop(),
            rideRecordings: recordings,
            authClient: auth,
            accountDeletionCapabilityStore: SessionDeletionCapabilityStore(
                capability: nil
            )
        )
    }

    private func sessionRider(id: String) -> User {
        User(
            id: id,
            wallet: "wallet-\(id)",
            username: nil,
            displayName: nil,
            avatarUrl: nil,
            email: nil,
            location: nil,
            preferredUnits: nil,
            totalRides: nil,
            totalDistanceKm: nil,
            totalElevationM: nil
        )
    }

    private func durableDeletionSessionRecords() -> [AccountDeletionSessionRecord] {
        guard let data = UserDefaults.standard.data(
            forKey: "br.account_deletion.session_state.v1"
        ) else { return [] }
        if let records = try? JSONDecoder().decode(
            [AccountDeletionSessionRecord].self,
            from: data
        ) {
            return records
        }
        return (try? JSONDecoder().decode(
            AccountDeletionSessionRecord.self,
            from: data
        )).map { [$0] } ?? []
    }
}

// MARK: - Fakes

private actor SessionDeletionServiceSpy: AccountDeletionServing {
    private(set) var createCallCount = 0
    private(set) var createdCapabilities: [AccountDeletionCapability] = []

    func preflight() async throws -> AccountDeletionPreflight {
        AccountDeletionPreflight(
            contractVersion: AccountDeletionContract.version,
            allowed: true,
            available: true,
            blockers: [],
            checkedAt: "2026-08-24T12:00:00Z"
        )
    }

    func create(
        capability: AccountDeletionCapability
    ) async throws -> AccountDeletionStatus {
        createCallCount += 1
        createdCapabilities.append(capability)
        return response(requestID: capability.requestID)
    }

    func status(
        capability: AccountDeletionCapability
    ) async throws -> AccountDeletionStatus {
        response(requestID: capability.requestID)
    }

    func retry(
        capability: AccountDeletionCapability
    ) async throws -> AccountDeletionStatus {
        response(requestID: capability.requestID)
    }

    private func response(requestID: String) -> AccountDeletionStatus {
        AccountDeletionStatus(
            contractVersion: AccountDeletionContract.version,
            requestID: requestID,
            status: .queued,
            requestedAt: "2026-08-24T12:00:00Z",
            updatedAt: "2026-08-24T12:00:00Z",
            completedAt: nil,
            blockers: [],
            failureCode: nil,
            retryable: false,
            attemptCount: 1
        )
    }
}

private actor AuthClientFake: AppSessionAuthClient {
    private var resumeOutcomes: [SessionResumeOutcome]
    private var meResults: [Result<User, Error>]
    private let deletionRefusal: AccountDeletionRefusalContext?
    private let deletionRecoveryIDToArmOnResume: String?
    private(set) var logoutCount = 0
    private(set) var clearLocalCount = 0
    private(set) var pushDeregistrations = 0
    private(set) var resumeCallCount = 0
    private(set) var accountBoundaryAdvances = 0
    private(set) var armedDeletionRecoveryDuringResume = false

    init(
        resumeOutcomes: [SessionResumeOutcome],
        meResults: [Result<User, Error>] = [],
        deletionRefusalContext: AccountDeletionRefusalContext? = nil,
        armDeletionRecoveryIDOnResume: String? = nil
    ) {
        self.resumeOutcomes = resumeOutcomes
        self.meResults = meResults
        deletionRefusal = deletionRefusalContext
        deletionRecoveryIDToArmOnResume = armDeletionRecoveryIDOnResume
    }

    func resumeSession() async -> SessionResumeOutcome {
        resumeCallCount += 1
        if let deletionRecoveryIDToArmOnResume {
            do {
                try AccountDeletionEmergencyFenceStore.armRequired(
                    recoveryID: deletionRecoveryIDToArmOnResume
                )
                armedDeletionRecoveryDuringResume = true
            } catch {}
        }
        return resumeOutcomes.isEmpty ? .transient : resumeOutcomes.removeFirst()
    }

    func me() async throws -> User {
        guard !meResults.isEmpty else { throw URLError(.timedOut) }
        return try meResults.removeFirst().get()
    }

    func logout() async { logoutCount += 1 }

    func clearLocalSession() async { clearLocalCount += 1 }

    func clearLocalSessionForAccountDeletion() async throws { clearLocalCount += 1 }

    func removePushRegistration() async { pushDeregistrations += 1 }

    func advanceAccountBoundary() async { accountBoundaryAdvances += 1 }

    func accountDeletionRefusalContext() async -> AccountDeletionRefusalContext? {
        deletionRefusal
    }
}

private struct SessionUploadRuntimeNoop: AppSessionRideUploadRuntime {
    func activate(user: User?) async {}
    func reconcileAll(owner: RecordingOwner) async {}
    func claimNextReveal(owner: RecordingOwner) async -> PendingRideReveal? { nil }
    func acknowledgeReveal(
        _ pending: PendingRideReveal, owner: RecordingOwner
    ) async -> Bool { false }
}

private actor GatedDeletionFreezeUploadRuntime: AppSessionRideUploadRuntime {
    private var freezeEntered = false
    private var freezeContinuation: CheckedContinuation<Void, Never>?
    private(set) var activatedUserIDs: [String?] = []

    func activate(user: User?) async { activatedUserIDs.append(user?.id) }
    func reconcileAll(owner: RecordingOwner) async {}
    func claimNextReveal(owner: RecordingOwner) async -> PendingRideReveal? { nil }
    func acknowledgeReveal(
        _ pending: PendingRideReveal,
        owner: RecordingOwner
    ) async -> Bool { false }

    func freezeForAccountDeletion(owner: RecordingOwner) async throws {
        freezeEntered = true
        await withCheckedContinuation { continuation in
            freezeContinuation = continuation
        }
    }

    func accountDeletionRecords(
        owner: RecordingOwner
    ) async throws -> [AccountDeletionUploadRecord] { [] }

    func waitUntilFreezeEntered() async {
        while !freezeEntered { await Task.yield() }
    }

    func releaseFreeze() {
        freezeContinuation?.resume()
        freezeContinuation = nil
    }
}

private actor DeletionFreezeUploadRuntimeSpy: AppSessionRideUploadRuntime {
    private(set) var frozenOwners: [RecordingOwner] = []
    private(set) var purgedOwners: [RecordingOwner] = []
    private(set) var activatedUserIDs: [String?] = []
    private(set) var deletionInventoryOwners: [RecordingOwner] = []
    private let deletionRecords: [AccountDeletionUploadRecord]
    private let deletionRecordsByOwner: [RecordingOwner: [AccountDeletionUploadRecord]]?

    init(deletionRecords: [AccountDeletionUploadRecord] = []) {
        self.deletionRecords = deletionRecords
        deletionRecordsByOwner = nil
    }

    init(deletionRecordsByOwner: [RecordingOwner: [AccountDeletionUploadRecord]]) {
        deletionRecords = []
        self.deletionRecordsByOwner = deletionRecordsByOwner
    }

    func activate(user: User?) async { activatedUserIDs.append(user?.id) }
    func reconcileAll(owner: RecordingOwner) async {}
    func claimNextReveal(owner: RecordingOwner) async -> PendingRideReveal? { nil }
    func acknowledgeReveal(
        _ pending: PendingRideReveal,
        owner: RecordingOwner
    ) async -> Bool { false }
    func freezeForAccountDeletion(owner: RecordingOwner) async throws {
        frozenOwners.append(owner)
    }

    func accountDeletionRecords(
        owner: RecordingOwner
    ) async throws -> [AccountDeletionUploadRecord] {
        deletionInventoryOwners.append(owner)
        return deletionRecordsByOwner?[owner] ?? deletionRecords
    }

    func purgeAccount(owner: RecordingOwner) async throws {
        purgedOwners.append(owner)
    }
}

private actor FreezeRequiredDeletionInventoryRuntime: AppSessionRideUploadRuntime {
    private(set) var frozenOwners: [RecordingOwner] = []
    private var frozenOwner: RecordingOwner?

    func activate(user: User?) async {
        frozenOwner = user.map { RecordingOwner(user: $0) }
    }

    func reconcileAll(owner: RecordingOwner) async {}
    func claimNextReveal(owner: RecordingOwner) async -> PendingRideReveal? { nil }
    func acknowledgeReveal(
        _ pending: PendingRideReveal,
        owner: RecordingOwner
    ) async -> Bool { false }

    func freezeForAccountDeletion(owner: RecordingOwner) async throws {
        frozenOwner = owner
        frozenOwners.append(owner)
    }

    func accountDeletionRecords(
        owner: RecordingOwner
    ) async throws -> [AccountDeletionUploadRecord] {
        guard frozenOwner == owner else { throw RideUploadStoreError.invalidOwner }
        return []
    }

    func purgeAccount(owner: RecordingOwner) async throws {}
}

final class SessionDeletionCapabilityStore: AccountDeletionCapabilityStoring, @unchecked Sendable {
    private var capability: AccountDeletionCapability?

    init(capability: AccountDeletionCapability?) { self.capability = capability }

    func load() -> AccountDeletionCapabilityStorageState {
        capability.map(AccountDeletionCapabilityStorageState.available) ?? .none
    }

    func save(_ capability: AccountDeletionCapability) throws { self.capability = capability }
    func delete() throws { capability = nil }
    func setCapability(_ capability: AccountDeletionCapability?) { self.capability = capability }
}

private final class ReloadableDeletionCapabilityStore: AccountDeletionCapabilityStoring, @unchecked Sendable {
    private let lock = NSLock()
    private var state: AccountDeletionCapabilityStorageState

    init(initial: AccountDeletionCapabilityStorageState) {
        state = initial
    }

    func load() -> AccountDeletionCapabilityStorageState {
        lock.withLock { state }
    }

    func saveUnconfirmed(_ capability: AccountDeletionCapability) throws {
        lock.withLock { state = .unconfirmed(capability) }
    }

    func save(_ capability: AccountDeletionCapability) throws {
        lock.withLock { state = .available(capability) }
    }

    func delete() throws {
        lock.withLock { state = .none }
    }

    func set(_ newState: AccountDeletionCapabilityStorageState) {
        lock.withLock { state = newState }
    }
}

private final class TestDeletionSessionRecordStore: AccountDeletionSessionRecordStoring, @unchecked Sendable {
    private let lock = NSLock()
    private var stored: [AccountDeletionSessionRecord]
    private var requiredFailures: Int
    private let dropsBestEffortWrites: Bool

    init(
        record: AccountDeletionSessionRecord? = nil,
        requiredFailures: Int = 0,
        dropsBestEffortWrites: Bool = false
    ) {
        stored = record.map { [$0] } ?? []
        self.requiredFailures = requiredFailures
        self.dropsBestEffortWrites = dropsBestEffortWrites
    }

    func loadAll() -> [AccountDeletionSessionRecord] {
        lock.withLock { stored }
    }

    func record(_ record: AccountDeletionSessionRecord) {
        lock.withLock {
            guard !dropsBestEffortWrites else { return }
            stored.removeAll { $0.owner == record.owner }
            stored.append(record)
        }
    }

    func recordRequired(_ record: AccountDeletionSessionRecord) throws {
        try lock.withLock {
            if requiredFailures > 0 {
                requiredFailures -= 1
                throw AccountDeletionCapabilityStoreError.unavailable
            }
            stored.removeAll { $0.owner == record.owner }
            stored.append(record)
        }
    }

    func clearRequired(_ record: AccountDeletionSessionRecord) throws {
        try lock.withLock {
            guard stored.contains(record) else {
                throw AccountDeletionLocalCleanupError.verificationFailed
            }
            stored.removeAll { $0 == record }
        }
    }

    func replaceRequired(
        _ record: AccountDeletionSessionRecord,
        with replacement: AccountDeletionSessionRecord
    ) throws {
        try lock.withLock {
            guard stored.contains(record) else {
                throw AccountDeletionLocalCleanupError.verificationFailed
            }
            stored.removeAll { $0 == record || $0.owner == replacement.owner }
            stored.append(replacement)
        }
    }
}

private final class TestDeletionEmergencyFenceStore: AccountDeletionEmergencyFenceStoring, @unchecked Sendable {
    private let lock = NSLock()
    private var stored: [AccountDeletionSessionRecord]
    private let clearFails: Bool

    init(recoveryIDs: [String], clearFails: Bool = false) {
        stored = recoveryIDs.map {
            AccountDeletionSessionRecord(
                recoveryID: $0,
                state: .identityUnavailable,
                owner: nil
            )
        }
        self.clearFails = clearFails
    }

    func records() -> [AccountDeletionSessionRecord] {
        lock.withLock { stored }
    }

    func armRequired(recoveryID: String) throws {
        lock.withLock {
            guard !stored.contains(where: { $0.recoveryID == recoveryID }) else {
                return
            }
            stored.append(
                AccountDeletionSessionRecord(
                    recoveryID: recoveryID,
                    state: .identityUnavailable,
                    owner: nil
                )
            )
        }
    }

    func clearRequired(recoveryID: String) throws {
        try lock.withLock {
            if clearFails {
                throw AccountDeletionCapabilityStoreError.unavailable
            }
            stored.removeAll { $0.recoveryID == recoveryID }
        }
    }
}

private actor GatedResumeAuthClient: AppSessionAuthClient {
    private let user: User
    private var resumeContinuation: CheckedContinuation<Void, Never>?
    private(set) var resumeEntered = false
    private(set) var meCallCount = 0

    init(user: User) { self.user = user }

    func resumeSession() async -> SessionResumeOutcome {
        resumeEntered = true
        await withCheckedContinuation { continuation in
            resumeContinuation = continuation
        }
        return .resumed
    }

    func releaseResume() {
        resumeContinuation?.resume()
        resumeContinuation = nil
    }

    func me() -> User {
        meCallCount += 1
        return user
    }

    func logout() async {}
    func clearLocalSession() async {}
    func clearLocalSessionForAccountDeletion() async throws {}
    func removePushRegistration() async {}
}

private actor GatedDeletionRefusalContextAuthClient: AppSessionAuthClient {
    private let user: User
    private let context: AccountDeletionRefusalContext
    private var contextReadContinuation: CheckedContinuation<Void, Never>?
    private var contextReadEntered = false
    private(set) var clearLocalCount = 0

    init(user: User, context: AccountDeletionRefusalContext) {
        self.user = user
        self.context = context
    }

    func resumeSession() async -> SessionResumeOutcome {
        .accountDeletion(.deleted)
    }

    func accountDeletionRefusalContext() async -> AccountDeletionRefusalContext? {
        contextReadEntered = true
        await withCheckedContinuation { continuation in
            contextReadContinuation = continuation
        }
        try? AccountDeletionEmergencyFenceStore.armRequired(
            recoveryID: context.recoveryID
        )
        return context
    }

    func waitUntilContextReadEntered() async {
        while !contextReadEntered { await Task.yield() }
    }

    func releaseContextRead() {
        contextReadContinuation?.resume()
        contextReadContinuation = nil
    }

    func me() async throws -> User { user }
    func logout() async {}
    func clearLocalSession() async { clearLocalCount += 1 }
    func clearLocalSessionForAccountDeletion() async throws {
        clearLocalCount += 1
    }
    func removePushRegistration() async {}
}

private actor SessionRecordingRuntimeSpy: AppSessionRideRecordingRuntime {
    private(set) var deactivations = 0
    private(set) var discardCount = 0
    private(set) var purgedOwners: [RecordingOwner] = []
    private(set) var deletionInventoryOwners: [RecordingOwner] = []
    private let deletionRecords: [AccountDeletionCustodyRecord]
    private let deletionRecordsByOwner: [RecordingOwner: [AccountDeletionCustodyRecord]]?

    init(deletionRecords: [AccountDeletionCustodyRecord] = []) {
        self.deletionRecords = deletionRecords
        deletionRecordsByOwner = nil
    }

    init(deletionRecordsByOwner: [RecordingOwner: [AccountDeletionCustodyRecord]]) {
        deletionRecords = []
        self.deletionRecordsByOwner = deletionRecordsByOwner
    }

    func activate(user: User?) async throws -> InterruptedRideRecovery? {
        if user == nil { deactivations += 1 }
        return nil
    }

    func saveRecovery(_ recovery: InterruptedRideRecovery) async throws -> FinalizedRecording {
        throw LiveRideCustodyError.noActiveRide
    }

    func discard(_ recovery: InterruptedRideRecovery) async throws {
        discardCount += 1
    }

    func localSavedRides(user: User) async throws -> [LocalSavedRide] { [] }

    func accountDeletionRecords(
        owner: RecordingOwner
    ) async throws -> [AccountDeletionCustodyRecord] {
        deletionInventoryOwners.append(owner)
        return deletionRecordsByOwner?[owner] ?? deletionRecords
    }

    func purgeAccount(owner: RecordingOwner) async throws {
        purgedOwners.append(owner)
        throw LiveRideCustodyError.ownerMismatch
    }
}

private final class SessionRefreshRecorder: @unchecked Sendable {
    private let lock = NSLock()
    private var requests = 0
    private var tokens: [String] = []

    var requestCount: Int { lock.withLock { requests } }
    var presentedTokens: [String] { lock.withLock { tokens } }

    func response(for request: URLRequest) throws -> (HTTPURLResponse, Data) {
        XCTAssertEqual(request.url?.path, "/auth/refresh")
        // URLProtocol does not preserve an encoded request body on every
        // simulator runtime. Record the storage generation APIClient reads
        // immediately before constructing this request instead.
        let token = KeychainStore.read(.refreshToken) ?? "<missing>"
        let requestNumber = lock.withLock { () -> Int in
            requests += 1
            tokens.append(token)
            return requests
        }

        // Keep the first flight open long enough for the second cold-start
        // caller to prove it coalesces onto the same actor task.
        if requestNumber == 1 { Thread.sleep(forTimeInterval: 0.05) }

        let status: Int
        let responseObject: [String: Any]
        if requestNumber == 1 {
            status = 200
            responseObject = [
                "user_id": "session-rider",
                "wallet": "session-wallet",
                "access_token": "access-generation-1",
                "access_expires_at": "2099-01-01T00:00:00Z",
                "refresh_token": "refresh-generation-2",
                "refresh_expires_at": "2099-02-01T00:00:00Z",
            ]
        } else {
            status = 409
            responseObject = [
                "detail": [
                    "error": [
                        "code": "refresh_rotated",
                        "message": "A newer refresh token already exists",
                    ]
                ]
            ]
        }
        let response = try XCTUnwrap(
            HTTPURLResponse(
                url: try XCTUnwrap(request.url),
                statusCode: status,
                httpVersion: "HTTP/1.1",
                headerFields: ["Content-Type": "application/json"]
            )
        )
        return (response, try JSONSerialization.data(withJSONObject: responseObject))
    }
}

private final class SessionRefreshURLProtocol: URLProtocol {
    private static let lock = NSLock()
    private static var handler: ((URLRequest) throws -> (HTTPURLResponse, Data))?

    static func install(
        _ newHandler: @escaping (URLRequest) throws -> (HTTPURLResponse, Data)
    ) {
        lock.withLock { handler = newHandler }
    }

    static func reset() {
        lock.withLock { handler = nil }
    }

    override class func canInit(with request: URLRequest) -> Bool { true }
    override class func canonicalRequest(for request: URLRequest) -> URLRequest { request }

    override func startLoading() {
        do {
            let current = Self.lock.withLock { Self.handler }
            let handler = try XCTUnwrap(current)
            let (response, data) = try handler(request)
            client?.urlProtocol(self, didReceive: response, cacheStoragePolicy: .notAllowed)
            client?.urlProtocol(self, didLoad: data)
            client?.urlProtocolDidFinishLoading(self)
        } catch {
            client?.urlProtocol(self, didFailWithError: error)
        }
    }

    override func stopLoading() {}
}

private final class GatedDeletionRefreshURLProtocol: URLProtocol, @unchecked Sendable {
    private static let lock = NSLock()
    private static var responder: GatedDeletionRefreshResponder?
    private let stateLock = NSLock()
    private var stopped = false

    static func install(_ newResponder: GatedDeletionRefreshResponder) {
        lock.withLock { responder = newResponder }
    }

    static func reset() {
        lock.withLock { responder = nil }
    }

    override class func canInit(with request: URLRequest) -> Bool { true }
    override class func canonicalRequest(for request: URLRequest) -> URLRequest { request }

    override func startLoading() {
        guard let responder = Self.lock.withLock({ Self.responder }) else {
            client?.urlProtocol(self, didFailWithError: URLError(.resourceUnavailable))
            return
        }
        responder.load(request) { [weak self] result in
            guard let self, !self.stateLock.withLock({ self.stopped }) else { return }
            switch result {
            case let .success((response, data)):
                self.client?.urlProtocol(
                    self,
                    didReceive: response,
                    cacheStoragePolicy: .notAllowed
                )
                self.client?.urlProtocol(self, didLoad: data)
                self.client?.urlProtocolDidFinishLoading(self)
            case let .failure(error):
                self.client?.urlProtocol(self, didFailWithError: error)
            }
        }
    }

    override func stopLoading() {
        stateLock.withLock { stopped = true }
    }
}

private final class GatedDeletionRefreshResponder: @unchecked Sendable {
    private let lock = NSLock()
    private let refreshRelease = DispatchSemaphore(value: 0)
    private var refreshRequests = 0
    private var refreshFlightJoins = 0
    private var accountRequests = 0

    func load(
        _ request: URLRequest,
        completion: @escaping (Result<(HTTPURLResponse, Data), Error>) -> Void
    ) {
        guard request.url?.path == "/auth/refresh" else {
            completion(Result { try response(for: request, code: "access_token_expired") })
            return
        }
        lock.withLock { refreshRequests += 1 }
        DispatchQueue.global().async { [self] in
            guard refreshRelease.wait(timeout: .now() + 10) == .success else {
                completion(.failure(URLError(.timedOut)))
                return
            }
            completion(Result {
                try response(
                    for: request,
                    code: AccountDeletionSessionState.pending.rawValue
                )
            })
        }
    }

    private func response(
        for request: URLRequest,
        code: String
    ) throws -> (HTTPURLResponse, Data) {
        let url = try XCTUnwrap(request.url)
        let response = try XCTUnwrap(HTTPURLResponse(
            url: url,
            statusCode: 401,
            httpVersion: "HTTP/1.1",
            headerFields: ["Content-Type": "application/json"]
        ))
        if url.path != "/auth/refresh" {
            XCTAssertEqual(url.path, "/users/me")
            lock.withLock { accountRequests += 1 }
        }
        let body = try JSONSerialization.data(withJSONObject: [
            "detail": [
                "error": [
                    "code": code,
                    "message": "Account lifecycle refusal",
                ]
            ]
        ])
        return (response, body)
    }

    func waitUntilRefreshEntered() async throws {
        for _ in 0..<2_000 {
            if lock.withLock({ refreshRequests > 0 }) { return }
            try await Task.sleep(for: .milliseconds(5))
        }
        throw URLError(.timedOut)
    }

    func waitUntilAccountRequests(_ expected: Int) async throws {
        for _ in 0..<2_000 {
            if lock.withLock({ accountRequests >= expected }) { return }
            try await Task.sleep(for: .milliseconds(5))
        }
        throw URLError(.timedOut)
    }

    func recordRefreshFlightJoin() {
        lock.withLock { refreshFlightJoins += 1 }
    }

    func waitUntilRefreshFlightJoined() async throws {
        for _ in 0..<2_000 {
            if lock.withLock({ refreshFlightJoins > 0 }) { return }
            try await Task.sleep(for: .milliseconds(5))
        }
        throw URLError(.timedOut)
    }

    func releaseRefresh() {
        refreshRelease.signal()
    }
}

private final class LockedDeletionNotificationRecorder: @unchecked Sendable {
    struct Snapshot: Sendable {
        let recoveryID: String?
        let attemptedWallet: String?
        let attemptedOwnerID: String?
        let attemptedOwnerWallet: String?
        let witnessWasAlreadyDurable: Bool
    }

    private let lock = NSLock()
    private var stored: [Snapshot] = []

    var snapshots: [Snapshot] { lock.withLock { stored } }

    func record(_ notification: Notification) {
        let recoveryID = notification.userInfo?["recovery_id"] as? String
        let witnessWasAlreadyDurable = recoveryID.map { expected in
            AccountDeletionEmergencyFenceStore.records.contains {
                $0.recoveryID == expected
            }
        } ?? false
        lock.withLock {
            stored.append(Snapshot(
                recoveryID: recoveryID,
                attemptedWallet: notification.userInfo?["attempted_wallet"] as? String,
                attemptedOwnerID: notification.userInfo?["attempted_owner_id"] as? String,
                attemptedOwnerWallet: notification.userInfo?["attempted_owner_wallet"] as? String,
                witnessWasAlreadyDurable: witnessWasAlreadyDurable
            ))
        }
    }
}

private final class SessionCredentialStoreFake: SessionCredentialStore, @unchecked Sendable {
    private let lock = NSLock()
    private var token: String?
    private var readFailure: SessionCredentialStoreError?
    private var saveFailure: SessionCredentialStoreError?

    init(
        token: String? = nil,
        readError: SessionCredentialStoreError? = nil,
        saveError: SessionCredentialStoreError? = nil
    ) {
        self.token = token
        readFailure = readError
        saveFailure = saveError
    }

    var storedToken: String? { lock.withLock { token } }

    func allowSaves() {
        lock.withLock { saveFailure = nil }
    }

    func readRefreshToken() throws -> String? {
        try lock.withLock {
            if let readFailure { throw readFailure }
            return token
        }
    }

    func saveRefreshToken(_ token: String) throws {
        try lock.withLock {
            if let saveFailure { throw saveFailure }
            self.token = token
        }
    }

    func deleteRefreshToken() throws {
        lock.withLock { token = nil }
    }
}

private final class LockedCounter: @unchecked Sendable {
    private let lock = NSLock()
    private var count = 0

    var value: Int { lock.withLock { count } }
    func increment() { lock.withLock { count += 1 } }
}

private func sessionTokenHTTPResponse(
    for request: URLRequest,
    refreshToken: String = "refresh-generation-1"
) throws -> (HTTPURLResponse, Data) {
    let response = try XCTUnwrap(
        HTTPURLResponse(
            url: try XCTUnwrap(request.url),
            statusCode: 200,
            httpVersion: "HTTP/1.1",
            headerFields: ["Content-Type": "application/json"]
        )
    )
    let body: [String: Any] = [
        "user_id": "session-rider",
        "wallet": "session-wallet",
        "access_token": "access-generation-1",
        "access_expires_at": "2099-01-01T00:00:00Z",
        "refresh_token": refreshToken,
        "refresh_expires_at": "2099-02-01T00:00:00Z",
    ]
    return (response, try JSONSerialization.data(withJSONObject: body))
}

private func accountDeletionStatusJSON(requestID: String) throws -> Data {
    try JSONSerialization.data(withJSONObject: [
        "contractVersion": AccountDeletionContract.version,
        "requestId": requestID,
        "status": AccountDeletionStatusCode.queued.rawValue,
        "requestedAt": "2026-08-25T12:00:00Z",
        "updatedAt": "2026-08-25T12:00:00Z",
        "blockers": [],
        "retryable": false,
        "attemptCount": 1,
    ])
}

private func deletionRefusalHTTPResponse(
    for request: URLRequest,
    code: String
) throws -> (HTTPURLResponse, Data) {
    let response = try XCTUnwrap(HTTPURLResponse(
        url: try XCTUnwrap(request.url),
        statusCode: 401,
        httpVersion: "HTTP/1.1",
        headerFields: ["Content-Type": "application/json"]
    ))
    let body = try JSONSerialization.data(withJSONObject: [
        "detail": [
            "error": [
                "code": code,
                "message": "Account lifecycle refusal",
            ]
        ]
    ])
    return (response, body)
}
