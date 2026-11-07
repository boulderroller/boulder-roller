import BackgroundTasks
import Foundation
import UIKit
import UserNotifications

private enum RideUploadProcessServices {
    static let backgroundTransfer = BackgroundRideFileTransfer()
}

/// Pure scheduling boundary for system-owned reconciliation. Terminal states
/// and states that require rider authentication/retry input must not keep
/// resubmitting background work that cannot advance them.
enum RideUploadBackgroundSchedulingPolicy {
    static func isAutomaticallyAdvanceable(_ phase: RideUploadPhase) -> Bool {
        switch phase {
        case .queued, .initializing, .transferring, .completing, .processing, .retryable:
            return true
        case .awaitingPrivacyReview, .waitingForAuthentication, .underReview, .failed, .final:
            return false
        }
    }
}

/// Process-wide production composition for the owner-bound upload lifecycle.
/// Views use this seam; tests inject the protocols beneath it directly.
actor RideUploadRuntime: FirstPartyRideUploadQueuing {
    static let shared = RideUploadRuntime()
    static let reconciliationTaskIdentifier = "com.boulderroller.app.ride-upload.reconcile"

    private let store: FileRideUploadJobStore
    private let authorization: RideUploadAuthorization
    private let coordinator: RideUploadCoordinator
    private let transfer: any RideFileTransferring
    private let durableAccountWorkPermitted: @Sendable (RecordingOwner) -> Bool
    private let immediateReconcile: @Sendable (String, String) async -> Void
    private var accountDeletionFrozenOwners = Set<RecordingOwner>()
    private var activeEnqueueOperations = 0
    private var enqueueDrainWaiters: [CheckedContinuation<Void, Never>] = []

    init(
        store: FileRideUploadJobStore = FileRideUploadJobStore(),
        transfer: any RideFileTransferring = RideUploadProcessServices.backgroundTransfer,
        durableAccountWorkPermitted: @escaping @Sendable (RecordingOwner) -> Bool = {
            AccountDeletionLocalFence.permitsAccountWork(owner: $0)
        },
        immediateReconcile: (@Sendable (String, String) async -> Void)? = nil
    ) {
        let authorization = RideUploadAuthorization(
            durableAccountWorkPermitted: durableAccountWorkPermitted
        )
        self.store = store
        self.authorization = authorization
        self.transfer = transfer
        self.durableAccountWorkPermitted = durableAccountWorkPermitted
        let coordinator = RideUploadCoordinator(
            store: store,
            service: LiveRideUploadService(),
            transfer: transfer,
            authorization: authorization,
            revealBuilder: LiveRideRevealBuilder()
        )
        self.coordinator = coordinator
        self.immediateReconcile = immediateReconcile ?? { jobID, ownerID in
            await coordinator.reconcile(jobID: jobID, ownerID: ownerID)
        }
    }

    func activate(user: User?) async {
        let owner = user.map(RecordingOwner.init(user:))
        guard let owner else {
            await authorization.activate(owner: nil)
            return
        }
        guard durableAccountWorkPermitted(owner) else {
            // Cold-start activation can race the AppSession deletion observer.
            // The durable/session/emergency fence is authoritative even when
            // this runtime's volatile frozen-owner set has not been rebuilt.
            await authorization.activate(owner: nil)
            return
        }
        accountDeletionFrozenOwners.remove(owner)
        guard !accountDeletionFrozenOwners.contains(owner) else {
            await authorization.activate(owner: nil)
            return
        }
        await authorization.activate(owner: owner)
    }

    func enqueue(
        user: User,
        fileName: String,
        fileType: String,
        sourceBytes: Data,
        summary: LocalRideSummary,
        jobID: String? = nil,
        parserVersion: UInt32? = nil,
        preliminaryRideHash: String? = nil
    ) async throws -> RideUploadJob {
        let owner = RecordingOwner(user: user)
        try await beginEnqueue(owner: owner)
        defer { finishEnqueue() }
        return try await coordinator.enqueue(
            ownerID: user.id,
            ownerWallet: user.wallet,
            fileName: fileName,
            fileType: fileType,
            sourceBytes: sourceBytes,
            summary: summary,
            jobID: jobID,
            parserVersion: parserVersion,
            preliminaryRideHash: preliminaryRideHash,
            requiresPublicationReview: true
        )
    }

    func enqueueFirstParty(
        owner: RecordingOwner,
        jobID: String,
        fileName: String,
        sourceBytes: Data,
        summary: LocalRideSummary,
        parserVersion: UInt32,
        preliminaryRideHash: String
    ) async throws -> RideUploadJob {
        try await beginEnqueue(owner: owner)
        defer { finishEnqueue() }
        return try await coordinator.enqueue(
            ownerID: owner.id,
            ownerWallet: owner.wallet,
            fileName: fileName,
            fileType: "gpx",
            sourceBytes: sourceBytes,
            summary: summary,
            jobID: jobID,
            parserVersion: parserVersion,
            preliminaryRideHash: preliminaryRideHash,
            requiresPublicationReview: true
        )
    }

    func pendingPrivacyReview(
        owner: RecordingOwner,
        excluding excludedIDs: Set<String> = []
    ) async -> RideUploadJob? {
        guard await authorization.permits(owner: owner),
              let jobs = try? await store.jobs(ownerID: owner.id),
              await authorization.permits(owner: owner)
        else { return nil }
        for stored in jobs where stored.ownerWallet == owner.wallet {
            guard !excludedIDs.contains(stored.id) else { continue }
            if stored.phase == .awaitingPrivacyReview { return stored }
            if stored.publication == nil,
               !stored.attemptedServerHandoff,
               stored.serverRideID == nil,
               stored.phase != .final
            {
                var migrated = stored
                migrated.phase = .awaitingPrivacyReview
                migrated.lastError = nil
                migrated.canRetry = false
                migrated.updatedAt = .now
                do {
                    try await store.save(migrated)
                } catch {
                    return nil
                }
                guard await authorization.permits(owner: owner) else { return nil }
                return migrated
            }
        }
        return nil
    }

    func approvePublication(
        jobID: String,
        owner: RecordingOwner,
        settings: RidePublicationSettings,
        draft: RidePostRideDraft = .empty,
        photoBytes: [String: Data] = [:]
    ) async throws {
        _ = try await coordinator.approvePublication(
            jobID: jobID,
            owner: owner,
            settings: settings,
            draft: draft,
            photoBytes: photoBytes
        )
        guard await authorization.permits(owner: owner) else { return }
        Self.scheduleReconciliation()
        let reconcile = immediateReconcile
        Task {
            await reconcile(jobID, owner.id)
            await self.scheduleIfWorkRemains(owner: owner)
        }
    }

    func reconcile(jobID: String, ownerID: String) async {
        await coordinator.reconcile(jobID: jobID, ownerID: ownerID)
        guard let owner = await authorization.activeOwner(matching: ownerID),
              await authorization.permits(owner: owner)
        else { return }
        await scheduleIfWorkRemains(owner: owner)
    }

    func reconcileAll(owner: RecordingOwner) async {
        guard await authorization.permits(owner: owner) else { return }
        await coordinator.reconcileAll(owner: owner)
        guard await authorization.permits(owner: owner) else { return }
        await scheduleIfWorkRemains(owner: owner)
    }

    func retry(jobID: String, owner: RecordingOwner) async {
        guard await authorization.permits(owner: owner) else { return }
        await coordinator.retry(jobID: jobID, owner: owner)
        guard await authorization.permits(owner: owner) else { return }
        await scheduleIfWorkRemains(owner: owner)
    }

    func jobs(owner: RecordingOwner) async -> [RideUploadJob]? {
        guard await authorization.permits(owner: owner),
              let jobs = try? await store.jobs(ownerID: owner.id),
              await authorization.permits(owner: owner)
        else { return nil }
        return jobs.filter { $0.ownerWallet == owner.wallet }
    }

    func accountDeletionRecords(owner: RecordingOwner) async throws -> [AccountDeletionUploadRecord] {
        let authorized = await authorization.permits(owner: owner)
        guard authorized || accountDeletionFrozenOwners.contains(owner) else {
            throw RideUploadStoreError.invalidOwner
        }
        let records = try await store.accountDeletionRecords(owner: owner)
        let stillAuthorized = await authorization.permits(owner: owner)
        guard stillAuthorized || accountDeletionFrozenOwners.contains(owner) else {
            throw RideUploadStoreError.invalidOwner
        }
        return records
    }

    /// Freeze every owner write before the destructive request crosses the
    /// network. Immutable sources remain on disk until verified completion.
    func freezeForAccountDeletion(owner: RecordingOwner) async throws {
        accountDeletionFrozenOwners.insert(owner)
        await authorization.activate(owner: nil)
        await waitForEnqueuesToDrain()
        let records = try await store.accountDeletionRecords(owner: owner)
        try await validateMultipartBodyAttribution()
        BGTaskScheduler.shared.cancel(taskRequestWithIdentifier: Self.reconciliationTaskIdentifier)
        try await transfer.cancel(jobIDs: Set(records.map(\.id)))
        try await validateMultipartBodyAttribution()
    }

    func purgeAccount(owner: RecordingOwner) async throws {
        guard accountDeletionFrozenOwners.contains(owner) else {
            throw RideUploadStoreError.invalidOwner
        }
        let records = try await store.accountDeletionRecords(owner: owner)
        try await validateMultipartBodyAttribution()
        try await transfer.cancel(jobIDs: Set(records.map(\.id)))
        try await validateMultipartBodyAttribution()
        try await store.purgeAccount(owner: owner)
        // Purge is the exact owner's terminal runtime handoff. Release only
        // after every source/body deletion above has succeeded so another
        // retained lifecycle request can establish its own freeze without
        // reopening this owner's writers.
        accountDeletionFrozenOwners.remove(owner)
    }

    func deleteLocalCopy(serverRideID: String, owner: RecordingOwner) async throws -> Bool {
        guard await authorization.permits(owner: owner) else {
            throw RideUploadStoreError.invalidOwner
        }
        let removed = try await store.deleteFinalizedRide(
            serverRideID: serverRideID,
            owner: owner
        )
        guard await authorization.permits(owner: owner) else {
            throw RideUploadStoreError.invalidOwner
        }
        return removed
    }

    func claimNextReveal(owner: RecordingOwner) async -> PendingRideReveal? {
        guard await authorization.permits(owner: owner) else { return nil }
        let pending = await coordinator.claimNextReveal(owner: owner)
        guard await authorization.permits(owner: owner) else { return nil }
        return pending
    }

    func acknowledgeReveal(
        _ pending: PendingRideReveal,
        owner: RecordingOwner
    ) async -> Bool {
        guard await authorization.permits(owner: owner) else { return false }
        let acknowledged = await coordinator.acknowledgeReveal(pending, owner: owner)
        guard await authorization.permits(owner: owner) else { return false }
        return acknowledged
    }

    /// BGProcessing and foreground entry both restore the real authenticated
    /// session before touching owner-scoped jobs. Missing/expired auth simply
    /// leaves those jobs paused for a later valid session.
    func restoreSessionAndReconcile() async -> Bool {
        guard case .resumed = await APIClient.shared.resumeSession(),
              let user = try? await APIClient.shared.me()
        else {
            await authorization.activate(owner: nil)
            return false
        }
        let owner = RecordingOwner(user: user)
        guard durableAccountWorkPermitted(owner) else {
            await authorization.activate(owner: nil)
            return false
        }
        await authorization.activate(owner: owner)
        guard await authorization.permits(owner: owner) else { return false }
        await coordinator.reconcileAll(owner: owner)
        guard await authorization.permits(owner: owner) else { return false }
        await scheduleIfWorkRemains(owner: owner)
        return await authorization.permits(owner: owner)
    }

    private func scheduleIfWorkRemains(owner: RecordingOwner) async {
        guard await authorization.permits(owner: owner),
              let jobs = try? await store.jobs(ownerID: owner.id),
              await authorization.permits(owner: owner),
              jobs.contains(where: {
                  $0.ownerWallet == owner.wallet
                      && RideUploadBackgroundSchedulingPolicy.isAutomaticallyAdvanceable($0.phase)
              })
        else { return }
        Self.scheduleReconciliation()
    }

    private func beginEnqueue(owner: RecordingOwner) async throws {
        guard durableAccountWorkPermitted(owner),
              !accountDeletionFrozenOwners.contains(owner)
        else {
            throw RideUploadStoreError.invalidOwner
        }
        activeEnqueueOperations += 1
        guard await authorization.permits(owner: owner),
              durableAccountWorkPermitted(owner),
              !accountDeletionFrozenOwners.contains(owner)
        else {
            finishEnqueue()
            throw RideUploadStoreError.invalidOwner
        }
    }

    private func finishEnqueue() {
        guard activeEnqueueOperations > 0 else { return }
        activeEnqueueOperations -= 1
        guard activeEnqueueOperations == 0 else { return }
        let waiters = enqueueDrainWaiters
        enqueueDrainWaiters.removeAll()
        for waiter in waiters { waiter.resume() }
    }

    private func waitForEnqueuesToDrain() async {
        guard activeEnqueueOperations > 0 else { return }
        await withCheckedContinuation { continuation in
            enqueueDrainWaiters.append(continuation)
        }
    }

    private func validateMultipartBodyAttribution() async throws {
        let bodyJobIDs = try await transfer.persistedBodyJobIDs()
        let knownJobIDs = try await store.accountDeletionKnownJobIDs(bodyJobIDs)
        guard bodyJobIDs == knownJobIDs else {
            throw AccountDeletionLocalCleanupError.verificationFailed
        }
    }

    nonisolated static func scheduleReconciliation() {
        let request = BGProcessingTaskRequest(identifier: reconciliationTaskIdentifier)
        request.requiresNetworkConnectivity = true
        request.requiresExternalPower = false
        request.earliestBeginDate = Date(timeIntervalSinceNow: 60)
        try? BGTaskScheduler.shared.submit(request)
    }
}

private struct LiveRideUploadService: RideUploadServicing {
    func initialize(job: RideUploadJob, clientRequestID: String) async throws -> UploadInitResponse {
        guard let publication = job.publication, publication.isValid else {
            throw RideUploadStoreError.immutableMetadataChanged
        }
        return try await APIClient.shared.uploadInit(
            fileType: job.fileType,
            fileHash: job.fileHash,
            fileSize: job.fileSize,
            clientRequestId: clientRequestID,
            parserVersion: job.parserVersion,
            preliminaryRideHash: job.preliminaryRideHash,
            publication: publication
        )
    }

    func resumeLegacyUpload(
        job: RideUploadJob,
        clientRequestID: String
    ) async throws -> UploadInitResponse {
        guard job.publication == nil,
              job.attemptedServerHandoff,
              job.serverRideID == nil
        else { throw RideUploadStoreError.immutableMetadataChanged }
        return try await APIClient.shared.uploadInitLegacyResume(
            fileType: job.fileType,
            fileHash: job.fileHash,
            fileSize: job.fileSize,
            clientRequestId: clientRequestID,
            parserVersion: job.parserVersion,
            preliminaryRideHash: job.preliminaryRideHash
        )
    }

    func complete(uploadID: String) async throws -> UploadCompleteResponse {
        try await APIClient.shared.uploadComplete(uploadId: uploadID)
    }

    func status(rideID: String) async throws -> RideStatus {
        try await APIClient.shared.rideStatus(id: rideID)
    }

    func spine(rideID: String) async throws -> RideSpineData? {
        try await APIClient.shared.rideSpine(id: rideID)
    }

    func detail(rideID: String) async throws -> RideDetailResponse {
        try await APIClient.shared.rideDetail(id: rideID)
    }

    func patterns(rideID: String) async throws -> PatternsResponse {
        try await APIClient.shared.ridePatterns(id: rideID)
    }

    func reprocess(rideID: String) async throws {
        try await APIClient.shared.reprocessRide(id: rideID)
    }

    func updatePostRideDraft(rideID: String, draft: RidePostRideDraft) async throws {
        try await APIClient.shared.updateRideMetadata(
            rideId: rideID,
            title: draft.title,
            notes: draft.notes
        )
    }

    func media(rideID: String) async throws -> [RideMedia] {
        try await APIClient.shared.rideMedia(rideId: rideID)
    }

    func initializeMedia(
        rideID: String,
        photo: RidePhotoDescriptor
    ) async throws -> RideMediaUploadInit {
        try await APIClient.shared.rideMediaUploadInit(rideId: rideID, photo: photo)
    }

    func uploadMedia(
        signedURL: String,
        sourceURL: URL,
        fileName: String
    ) async throws {
        try await APIClient.shared.uploadToStorage(
            signedUrl: signedURL,
            data: Data(contentsOf: sourceURL, options: [.mappedIfSafe]),
            fileName: fileName
        )
    }

    func completeMedia(rideID: String, mediaID: String) async throws -> RideMedia {
        try await APIClient.shared.rideMediaUploadComplete(
            rideId: rideID,
            mediaId: mediaID
        )
    }
}

private enum LiveRideRevealError: Error {
    case nonfinal
    case ownershipMismatch
}

struct LiveRideRevealBuilder: RideRevealBuilding {
    func build(
        job: RideUploadJob,
        status: RideStatus,
        detail: RideDetailResponse,
        patterns: PatternsResponse
    ) throws -> RevealData {
        let expectedRideID = job.serverRideID ?? job.id
        guard status.rideId == expectedRideID,
              status.status == "completed",
              status.processingStage == "completed",
              status.attestationStatus == "attested",
              status.canonicalMatch != false,
              status.failure == nil
        else { throw LiveRideRevealError.nonfinal }
        guard detail.ride.id == expectedRideID,
              detail.ride.status == "completed",
              detail.ride.isOwner == true,
              patterns.rideId == expectedRideID
        else { throw LiveRideRevealError.ownershipMismatch }

        let ride = detail.ride
        let thresholdEconomyState = status.effortPolicy?.thresholdEconomyState ?? ride.thresholdEconomyState
        let allPatterns = patterns.patterns?.climbPatterns ?? []
        let frozenIDs = Set((ride.calItemization?.climbs ?? []).compactMap(\.patternId))
        let climbPatterns = allPatterns.filter { pattern in
            frozenIDs.contains(pattern.id ?? "") || pattern.vaultMatch?.isAuthoritativeCompletion == true
                || (thresholdEconomyState == "held" && pattern.climbId != nil)
        }.sorted { ($0.effortStartS ?? .infinity) < ($1.effortStartS ?? .infinity) }
        var leaderboardEntry: RevealData.LeaderboardEntry?
        var entryClimbIDs = Set<String>()
        for pattern in climbPatterns {
            guard let match = pattern.vaultMatch, match.isAuthoritativeCompletion,
                  let rank = match.yourRank, (1...10).contains(rank),
                  match.isPR == true
            else { continue }
            entryClimbIDs.insert(pattern.stableId)
            if leaderboardEntry == nil {
                leaderboardEntry = RevealData.LeaderboardEntry(
                    rank: rank,
                    climbName: match.name ?? pattern.shownName,
                    timeS: match.yourTime,
                    wasTimeS: nil
                )
            }
        }

        return RevealData(
            title: ride.title,
            subtitle: Format.rideTimestamp(ride.startedAt),
            calEarned: thresholdEconomyState == "held"
                ? nil
                : status.calEarned
                    ?? status.effortPolicy?.rewardableCal
                    ?? ride.calEarned,
            distanceM: ride.distanceM,
            elevationM: ride.shownElevationM,
            durationS: ride.durationS,
            climbs: climbPatterns.map {
                RevealData.ClimbLine(
                    name: $0.shownName,
                    timeS: $0.vaultMatch?.yourTime ?? $0.effortDurationS,
                    isLeaderboardEntry: entryClimbIDs.contains($0.stableId),
                    patternID: $0.stableId,
                    isNewBest: $0.vaultMatch?.isAuthoritativeCompletion == true ? $0.vaultMatch?.isPR : nil
                )
            },
            tributeCal: status.effortPolicy?.tributableCal ?? ride.tributableCal,
            thresholdEconomyState: thresholdEconomyState,
            leaderboardEntry: leaderboardEntry,
            tributeLines: RevealData.tribute(itemization: ride.calItemization, climbs: allPatterns),
            verification: RevealData.Verification(status: status.attestationStatus,
                rideHash: ride.rideHashHex, transaction: ride.rideAttestationTxSignature)
        )
    }
}

final class RideUploadApplicationDelegate: NSObject, UIApplicationDelegate {
    func application(
        _ application: UIApplication,
        didFinishLaunchingWithOptions launchOptions: [UIApplication.LaunchOptionsKey: Any]? = nil
    ) -> Bool {
        BGTaskScheduler.shared.register(
            forTaskWithIdentifier: RideUploadRuntime.reconciliationTaskIdentifier,
            using: nil
        ) { task in
            guard let processingTask = task as? BGProcessingTask else {
                task.setTaskCompleted(success: false)
                return
            }
            let work = Task {
                let restored = await RideUploadRuntime.shared.restoreSessionAndReconcile()
                processingTask.setTaskCompleted(success: restored && !Task.isCancelled)
            }
            processingTask.expirationHandler = { work.cancel() }
        }
        // Notification taps route through the push machinery (Law 7:
        // pushes deep-link to surfaces; no notification room exists).
        UNUserNotificationCenter.current().delegate = PushNotificationDelegate.shared
        return true
    }

    // MARK: APNs registration (bead odmi6.8)

    func application(
        _ application: UIApplication,
        didRegisterForRemoteNotificationsWithDeviceToken deviceToken: Data
    ) {
        PushRegistrar.handleDeviceToken(deviceToken)
    }

    func application(
        _ application: UIApplication,
        didFailToRegisterForRemoteNotificationsWithError error: Error
    ) {
        // Truthful no-op: registration failure (no entitlement provisioning
        // yet, simulator limitations) leaves the app exactly as functional —
        // deep-link destinations are ordinary surfaces.
        print("[Push] APNs registration failed: \(error.localizedDescription)")
    }

    func application(
        _ application: UIApplication,
        handleEventsForBackgroundURLSession identifier: String,
        completionHandler: @escaping () -> Void
    ) {
        if !RideUploadProcessServices.backgroundTransfer.handleEvents(
            forBackgroundURLSession: identifier,
            completionHandler: completionHandler
        ) {
            completionHandler()
        }
    }
}
