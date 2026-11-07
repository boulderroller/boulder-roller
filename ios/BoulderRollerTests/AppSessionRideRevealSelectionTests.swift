import Foundation
import XCTest
@testable import BoulderRoller

final class AppSessionRideRevealSelectionTests: XCTestCase {
    @MainActor
    func testPrivacyReviewPrecedesRevealAndApprovalResumesTheSameRide() async throws {
        let job = pendingPrivacyJob()
        let reveal = pendingReveal(id: "final-ride")
        let gate = AppSessionRevealTakeGate()
        let runtime = AppSessionRideUploadRuntimeFake(
            reveals: [reveal],
            gate: gate,
            privacyReviews: [job]
        )
        let session = AppSession(
            rideUploads: runtime,
            rideRecordings: AppSessionRideRecordingRuntimeNoop(),
            accountDeletionCapabilityStore: SessionDeletionCapabilityStore(capability: nil)
        )
        session.phase = .signedIn(rider())

        await session.refreshRideUploads()

        XCTAssertEqual(session.pendingRidePrivacyReview?.id, job.id)
        XCTAssertNil(session.pendingRideReveal)
        let claimsBeforeApproval = await runtime.claimedOwnerIDs
        XCTAssertTrue(claimsBeforeApproval.isEmpty)

        let settings = RidePublicationSettings(
            visibility: .followers,
            mapVisibility: .hideStartEnd,
            mapHideStartM: 200,
            mapHideEndM: 200
        )
        try await session.approveRidePublication(job, settings: settings)
        XCTAssertNil(session.pendingRidePrivacyReview)
        XCTAssertNil(session.pendingRideReveal)

        let refresh = Task { @MainActor in
            await session.refreshRideUploads()
        }
        while await gate.enteredCount == 0 { await Task.yield() }
        await gate.release()
        await refresh.value

        XCTAssertEqual(session.pendingRideReveal, reveal)
        let approved = await runtime.approvedPublications
        XCTAssertEqual(approved, [settings])
    }

    @MainActor
    func testWalletChangeWhilePrivacyReviewIsLoadingCannotInstallOldOwnersRide() async {
        let privacyGate = AppSessionRevealTakeGate()
        let runtime = AppSessionRideUploadRuntimeFake(
            reveals: [],
            gate: AppSessionRevealTakeGate(),
            privacyReviews: [pendingPrivacyJob()],
            privacyGate: privacyGate
        )
        let session = AppSession(
            rideUploads: runtime,
            rideRecordings: AppSessionRideRecordingRuntimeNoop(),
            accountDeletionCapabilityStore: SessionDeletionCapabilityStore(capability: nil)
        )
        session.phase = .signedIn(rider(wallet: "wallet-1"))

        let refresh = Task { @MainActor in
            await session.refreshRideUploads()
        }
        while await privacyGate.enteredCount == 0 { await Task.yield() }
        session.phase = .signedIn(rider(wallet: "wallet-2"))
        await privacyGate.release()
        await refresh.value

        XCTAssertNil(session.pendingRidePrivacyReview)
        XCTAssertEqual(session.currentUser?.wallet, "wallet-2")
    }

    @MainActor
    func testConcurrentRefreshesClaimOnlyOnePersistedReveal() async {
        let gate = AppSessionRevealTakeGate()
        let runtime = AppSessionRideUploadRuntimeFake(
            reveals: [
                pendingReveal(id: "first-ride"),
                pendingReveal(id: "second-ride"),
            ],
            gate: gate
        )
        let session = AppSession(
            rideUploads: runtime,
            rideRecordings: AppSessionRideRecordingRuntimeNoop(),
            accountDeletionCapabilityStore: SessionDeletionCapabilityStore(capability: nil)
        )
        let rider = User(
            id: "rider-1",
            wallet: "wallet-1",
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
        session.phase = .signedIn(rider)

        let first = Task { @MainActor in
            await session.refreshRideUploads()
        }
        while await gate.enteredCount == 0 { await Task.yield() }

        let overlapping = Task { @MainActor in
            await session.refreshRideUploads()
        }
        await overlapping.value
        await gate.release()
        await first.value

        let claimedOwnerIDs = await runtime.claimedOwnerIDs
        let remainingRevealCount = await runtime.remainingRevealCount
        XCTAssertEqual(claimedOwnerIDs, [rider.id])
        XCTAssertEqual(session.pendingRideReveal?.id, "first-ride")
        XCTAssertEqual(
            remainingRevealCount,
            1,
            "a concurrent resume trigger must not consume and overwrite a second ceremony"
        )
    }

    @MainActor
    func testAcknowledgementFailureRetainsClaimAndSuccessClearsIt() async {
        let gate = AppSessionRevealTakeGate()
        let pending = pendingReveal(id: "first-ride")
        let runtime = AppSessionRideUploadRuntimeFake(
            reveals: [pending],
            gate: gate,
            acknowledgementResults: [false, true]
        )
        let session = AppSession(
            rideUploads: runtime,
            rideRecordings: AppSessionRideRecordingRuntimeNoop(),
            accountDeletionCapabilityStore: SessionDeletionCapabilityStore(capability: nil)
        )
        session.phase = .signedIn(rider())

        let refresh = Task { @MainActor in await session.refreshRideUploads() }
        while await gate.enteredCount == 0 { await Task.yield() }
        await gate.release()
        await refresh.value

        await session.acknowledgePendingRideReveal(pending)
        XCTAssertEqual(session.pendingRideReveal, pending)
        XCTAssertNil(session.pendingFinishedRideID)

        await session.acknowledgePendingRideReveal(pending)
        XCTAssertNil(session.pendingRideReveal)
        XCTAssertEqual(session.pendingFinishedRideID, pending.authoritativeRideID)
        let acknowledgedClaimIDs = await runtime.acknowledgedClaimIDs
        XCTAssertEqual(acknowledgedClaimIDs, [pending.claimID, pending.claimID])
    }

    @MainActor
    func testStoneDoneAcknowledgesWithoutOpeningARideSheet() async {
        let gate = AppSessionRevealTakeGate()
        let pending = pendingReveal(id: "stone-ride")
        let runtime = AppSessionRideUploadRuntimeFake(reveals: [pending], gate: gate,
                                                     acknowledgementResults: [true])
        let session = AppSession(rideUploads: runtime,
            rideRecordings: AppSessionRideRecordingRuntimeNoop(),
            accountDeletionCapabilityStore: SessionDeletionCapabilityStore(capability: nil))
        session.phase = .signedIn(rider())
        let refresh = Task { @MainActor in await session.refreshRideUploads() }
        while await gate.enteredCount == 0 { await Task.yield() }
        await gate.release()
        await refresh.value
        await session.acknowledgePendingRideReveal(pending, openRide: false)
        XCTAssertNil(session.pendingRideReveal)
        XCTAssertNil(session.pendingFinishedRideID)
        let acknowledged = await runtime.acknowledgedClaimIDs
        XCTAssertEqual(acknowledged, [pending.claimID])
    }

    @MainActor
    func testSameIDDifferentWalletDuringActivationCannotInstallCapturedRecovery() async {
        let recovery = InterruptedRideRecovery(
            id: "22222222-2222-4222-8222-222222222222",
            ownerID: "rider-1",
            startedAt: Date(timeIntervalSince1970: 1_800_000_000),
            state: .recording,
            sampleCount: 10,
            durationS: 10,
            distanceM: 100,
            elevationGainM: 5
        )
        let services = await exerciseSameIDWalletSwitch(
            recordingOutcome: .recovery(recovery)
        )

        XCTAssertNil(services.session.pendingInterruptedRide)
        XCTAssertNil(services.session.interruptedRideErrorMessage)
        XCTAssertNil(services.session.pendingRideReveal)
        let reconciledOwners = await services.uploads.reconciledOwnerIDs
        let claimedOwners = await services.uploads.claimedOwnerIDs
        XCTAssertTrue(reconciledOwners.isEmpty)
        XCTAssertTrue(claimedOwners.isEmpty)
    }

    @MainActor
    func testSameIDDifferentWalletDuringActivationCannotInstallCapturedError() async {
        let services = await exerciseSameIDWalletSwitch(recordingOutcome: .failure)

        XCTAssertNil(services.session.pendingInterruptedRide)
        XCTAssertNil(services.session.interruptedRideErrorMessage)
        XCTAssertNil(services.session.pendingRideReveal)
        let reconciledOwners = await services.uploads.reconciledOwnerIDs
        let claimedOwners = await services.uploads.claimedOwnerIDs
        XCTAssertTrue(reconciledOwners.isEmpty)
        XCTAssertTrue(claimedOwners.isEmpty)
    }

    @MainActor
    func testSameIDDifferentWalletDuringActivationCannotAdvanceOldOwnerRevealSelection() async {
        let services = await exerciseSameIDWalletSwitch(recordingOutcome: .recovery(nil))

        XCTAssertNil(services.session.pendingInterruptedRide)
        XCTAssertNil(services.session.interruptedRideErrorMessage)
        XCTAssertNil(services.session.pendingRideReveal)
        let reconciledOwners = await services.uploads.reconciledOwnerIDs
        let claimedOwners = await services.uploads.claimedOwnerIDs
        XCTAssertTrue(reconciledOwners.isEmpty)
        XCTAssertTrue(claimedOwners.isEmpty)
    }

    @MainActor
    private func exerciseSameIDWalletSwitch(
        recordingOutcome: AppSessionRecordingActivationOutcome
    ) async -> (
        session: AppSession,
        uploads: AppSessionOwnerSwitchUploadRuntimeFake
    ) {
        let activationGate = AppSessionOwnerServiceActivationGate()
        let recordings = AppSessionOwnerSwitchRecordingRuntimeFake(
            outcome: recordingOutcome,
            gate: activationGate
        )
        let uploads = AppSessionOwnerSwitchUploadRuntimeFake(
            reveal: pendingReveal(id: "stale-owner-reveal")
        )
        let session = AppSession(
            rideUploads: uploads,
            rideRecordings: recordings,
            accountDeletionCapabilityStore: SessionDeletionCapabilityStore(capability: nil)
        )
        let original = rider(wallet: "wallet-before-await")
        session.phase = .signedIn(original)

        let refresh = Task { @MainActor in
            await session.refreshRideUploads()
        }
        while await activationGate.enteredCount == 0 { await Task.yield() }
        session.phase = .signedIn(rider(wallet: "wallet-after-await"))
        await activationGate.release()
        await refresh.value

        let activatedOwners = await recordings.activatedOwners
        XCTAssertEqual(
            activatedOwners,
            [RecordingOwner(user: original)],
            "the suspended call must remain identifiable as the old exact owner"
        )
        XCTAssertEqual(session.currentUser?.wallet, "wallet-after-await")
        return (session, uploads)
    }

    private func pendingReveal(id: String) -> PendingRideReveal {
        PendingRideReveal(
            id: id,
            ownerID: "rider-1",
            claimID: "11111111-1111-4111-8111-111111111111",
            authoritativeRideID: id,
            data: RevealData(
                title: "Sunday Ride",
                subtitle: "Sunday 8:00 AM",
                calEarned: nil,
                distanceM: 12_345,
                elevationM: 456,
                durationS: 3_210,
                climbs: [],
                tributeCal: nil,
                leaderboardEntry: nil
            )
        )
    }

    private func rider(wallet: String = "wallet-1") -> User {
        User(
            id: "rider-1",
            wallet: wallet,
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

    private func pendingPrivacyJob() -> RideUploadJob {
        let startedAt = Date(timeIntervalSince1970: 1_800_000_000)
        return RideUploadJob(
            id: "99999999-9999-4999-8999-999999999999",
            ownerID: "rider-1",
            ownerWallet: "wallet-1",
            fileName: "Ride.gpx",
            fileType: "gpx",
            fileHash: String(repeating: "a", count: 64),
            fileSize: 100,
            sourceFileName: "source.gpx",
            localSummary: LocalRideSummary(
                startedAt: startedAt,
                distanceM: 12_345,
                elevationM: 456,
                durationS: 3_210
            ),
            createdAt: startedAt,
            updatedAt: startedAt,
            phase: .awaitingPrivacyReview,
            attemptedServerHandoff: false,
            signedURL: nil,
            signedURLExpiresAt: nil,
            serverRideID: nil,
            authoritativeStatus: nil,
            attemptCount: 0,
            nextRetryAt: nil,
            lastError: nil,
            canRetry: false,
            revealState: .none,
            reveal: nil
        )
    }
}

private actor AppSessionRideRecordingRuntimeNoop: AppSessionRideRecordingRuntime {
    func activate(user: User?) -> InterruptedRideRecovery? { nil }

    func saveRecovery(_ recovery: InterruptedRideRecovery) throws -> FinalizedRecording {
        throw LiveRideCustodyError.noActiveRide
    }

    func discard(_ recovery: InterruptedRideRecovery) throws {
        throw LiveRideCustodyError.noActiveRide
    }
}

private enum AppSessionRecordingActivationOutcome: Sendable {
    case recovery(InterruptedRideRecovery?)
    case failure
}

private actor AppSessionOwnerServiceActivationGate {
    private var continuation: CheckedContinuation<Void, Never>?
    private(set) var enteredCount = 0

    func wait() async {
        enteredCount += 1
        await withCheckedContinuation { continuation in
            self.continuation = continuation
        }
    }

    func release() {
        continuation?.resume()
        continuation = nil
    }
}

private actor AppSessionOwnerSwitchRecordingRuntimeFake: AppSessionRideRecordingRuntime {
    private let outcome: AppSessionRecordingActivationOutcome
    private let gate: AppSessionOwnerServiceActivationGate
    private(set) var activatedOwners: [RecordingOwner?] = []

    init(
        outcome: AppSessionRecordingActivationOutcome,
        gate: AppSessionOwnerServiceActivationGate
    ) {
        self.outcome = outcome
        self.gate = gate
    }

    func activate(user: User?) async throws -> InterruptedRideRecovery? {
        activatedOwners.append(user.map(RecordingOwner.init(user:)))
        await gate.wait()
        switch outcome {
        case let .recovery(recovery): return recovery
        case .failure: throw LiveRideCustodyError.keyUnavailable
        }
    }

    func saveRecovery(_ recovery: InterruptedRideRecovery) throws -> FinalizedRecording {
        throw LiveRideCustodyError.noActiveRide
    }

    func discard(_ recovery: InterruptedRideRecovery) throws {
        throw LiveRideCustodyError.noActiveRide
    }
}

private actor AppSessionOwnerSwitchUploadRuntimeFake: AppSessionRideUploadRuntime {
    private let reveal: PendingRideReveal
    private(set) var activatedOwners: [RecordingOwner?] = []
    private(set) var reconciledOwnerIDs: [String] = []
    private(set) var claimedOwnerIDs: [String] = []

    init(reveal: PendingRideReveal) {
        self.reveal = reveal
    }

    func activate(user: User?) {
        activatedOwners.append(user.map(RecordingOwner.init(user:)))
    }

    func reconcileAll(owner: RecordingOwner) {
        reconciledOwnerIDs.append(owner.id)
    }

    func claimNextReveal(owner: RecordingOwner) -> PendingRideReveal? {
        claimedOwnerIDs.append(owner.id)
        return reveal
    }

    func acknowledgeReveal(
        _ pending: PendingRideReveal,
        owner: RecordingOwner
    ) -> Bool { false }
}

private actor AppSessionRevealTakeGate {
    private var continuation: CheckedContinuation<Void, Never>?
    private(set) var enteredCount = 0

    func wait() async {
        enteredCount += 1
        guard enteredCount == 1 else { return }
        await withCheckedContinuation { continuation in
            self.continuation = continuation
        }
    }

    func release() {
        continuation?.resume()
        continuation = nil
    }
}

private actor AppSessionRideUploadRuntimeFake: AppSessionRideUploadRuntime {
    private var reveals: [PendingRideReveal]
    private var privacyReviews: [RideUploadJob]
    private let gate: AppSessionRevealTakeGate
    private let privacyGate: AppSessionRevealTakeGate?
    private var acknowledgementResults: [Bool]
    private(set) var claimedOwnerIDs: [String] = []
    private(set) var acknowledgedClaimIDs: [String] = []
    private(set) var approvedPublications: [RidePublicationSettings] = []

    init(
        reveals: [PendingRideReveal],
        gate: AppSessionRevealTakeGate,
        acknowledgementResults: [Bool] = [],
        privacyReviews: [RideUploadJob] = [],
        privacyGate: AppSessionRevealTakeGate? = nil
    ) {
        self.reveals = reveals
        self.gate = gate
        self.acknowledgementResults = acknowledgementResults
        self.privacyReviews = privacyReviews
        self.privacyGate = privacyGate
    }

    var remainingRevealCount: Int { reveals.count }

    func activate(user: User?) {}

    func reconcileAll(owner: RecordingOwner) async {}

    func pendingPrivacyReview(
        owner: RecordingOwner,
        excluding excludedIDs: Set<String>
    ) async -> RideUploadJob? {
        if let privacyGate { await privacyGate.wait() }
        guard let index = privacyReviews.firstIndex(where: {
            $0.ownerID == owner.id
                && $0.ownerWallet == owner.wallet
                && !excludedIDs.contains($0.id)
        }) else { return nil }
        return privacyReviews.remove(at: index)
    }

    func approvePublication(
        jobID: String,
        owner: RecordingOwner,
        settings: RidePublicationSettings,
        draft: RidePostRideDraft,
        photoBytes: [String: Data]
    ) {
        approvedPublications.append(settings)
    }

    func claimNextReveal(owner: RecordingOwner) async -> PendingRideReveal? {
        claimedOwnerIDs.append(owner.id)
        await gate.wait()
        guard !reveals.isEmpty else { return nil }
        return reveals.removeFirst()
    }

    func acknowledgeReveal(
        _ pending: PendingRideReveal,
        owner: RecordingOwner
    ) async -> Bool {
        acknowledgedClaimIDs.append(pending.claimID)
        guard !acknowledgementResults.isEmpty else { return false }
        return acknowledgementResults.removeFirst()
    }
}
