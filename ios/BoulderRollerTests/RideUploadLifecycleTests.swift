import Foundation
import XCTest
@testable import BoulderRoller

final class RideUploadLifecycleTests: XCTestCase {
    private var rootURL: URL!
    private let ownerID = "rider-1"
    private let ownerWallet = "wallet-1"
    private let jobID = "11111111-1111-4111-8111-111111111111"
    private let now = Date(timeIntervalSince1970: 1_786_400_000)
    private var owner: RecordingOwner {
        RecordingOwner(id: ownerID, wallet: ownerWallet)
    }

    override func setUpWithError() throws {
        AccountDeletionSessionRecordStore.clear()
        rootURL = FileManager.default.temporaryDirectory
            .appendingPathComponent("RideUploadLifecycleTests-\(UUID().uuidString)", isDirectory: true)
    }

    override func tearDownWithError() throws {
        AccountDeletionSessionRecordStore.clear()
        if let rootURL, FileManager.default.fileExists(atPath: rootURL.path) {
            try FileManager.default.removeItem(at: rootURL)
        }
    }

    func testEnqueuePersistsExactOwnerBoundBytesBeforeTransfer() async throws {
        let source = Data("original-gpx-evidence".utf8)
        let store = FileRideUploadJobStore(rootURL: rootURL)
        let service = UploadServiceFake(fixedRideID: jobID, statuses: [status("processing")])
        let transfer = TransferFake()
        let auth = AuthorizationFake(owner: RecordingOwner(id: ownerID, wallet: ownerWallet))
        let coordinator = makeCoordinator(store: store, service: service, transfer: transfer, auth: auth)

        let job = try await enqueue(coordinator, bytes: source)

        let initializeCallCount = await service.initializeCallCount
        let storedJobIDs = try await store.jobs(ownerID: ownerID).map(\.id)
        XCTAssertEqual(initializeCallCount, 0, "enqueue must persist before any transfer call")
        XCTAssertEqual(storedJobIDs, [jobID])
        let storedURL = try await store.sourceURL(for: job)
        XCTAssertEqual(try Data(contentsOf: storedURL), source)
        XCTAssertEqual(FileRideUploadJobStore.sha256(try Data(contentsOf: storedURL)), job.fileHash)
        let otherOwnerJobs = try await store.jobs(ownerID: "rider-2")
        XCTAssertTrue(otherOwnerJobs.isEmpty)
    }

    func testAccountDeletionPurgePreservesSameUserIDDifferentWallet() async throws {
        let store = FileRideUploadJobStore(rootURL: rootURL)
        let deleting = fixtureJob(id: jobID)
        let otherID = "22222222-2222-4222-8222-222222222222"
        let other = fixtureJob(id: otherID, wallet: "wallet-other")
        let bytes = Data("ride-evidence".utf8)
        try await store.create(deleting, sourceBytes: bytes)
        try await store.create(other, sourceBytes: bytes)

        try await store.purgeAccount(owner: owner)

        let remaining = try await store.jobs(ownerID: ownerID)
        XCTAssertEqual(remaining.map(\.id), [otherID])
        XCTAssertEqual(remaining.first?.ownerWallet, "wallet-other")
        let otherSource = try await store.sourceURL(for: other)
        XCTAssertEqual(try Data(contentsOf: otherSource), bytes)
    }

    func testAccountDeletionInventoriesAndPurgesCrashLeftHiddenUploadStaging() async throws {
        let store = FileRideUploadJobStore(rootURL: rootURL)
        let job = fixtureJob(id: jobID)
        try await store.create(job, sourceBytes: Data("ride-evidence".utf8))
        let ownerDirectory = try XCTUnwrap(
            FileManager.default.contentsOfDirectory(
                at: rootURL,
                includingPropertiesForKeys: nil
            ).first
        )
        let published = ownerDirectory.appendingPathComponent(jobID, isDirectory: true)
        let staging = ownerDirectory.appendingPathComponent(
            ".\(jobID).aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa.staging",
            isDirectory: true
        )
        try FileManager.default.moveItem(at: published, to: staging)

        let records = try await store.accountDeletionRecords(owner: owner)
        XCTAssertEqual(records.map(\.id), [jobID])

        try await store.purgeAccount(owner: owner)
        XCTAssertFalse(FileManager.default.fileExists(atPath: staging.path))
    }

    func testAccountDeletionPreservesAndBlocksOnOrphanHiddenUploadArtifact() async throws {
        let store = FileRideUploadJobStore(rootURL: rootURL)
        let job = fixtureJob(id: jobID)
        try await store.create(job, sourceBytes: Data("ride-evidence".utf8))
        let ownerDirectory = try XCTUnwrap(
            FileManager.default.contentsOfDirectory(
                at: rootURL,
                includingPropertiesForKeys: nil
            ).first
        )
        let orphan = ownerDirectory.appendingPathComponent(".orphan.staging", isDirectory: true)
        try FileManager.default.createDirectory(at: orphan, withIntermediateDirectories: true)
        try Data("unattributed-source".utf8).write(
            to: orphan.appendingPathComponent("source.gpx")
        )

        do {
            _ = try await store.accountDeletionRecords(owner: owner)
            XCTFail("unattributed hidden bytes must make inventory unavailable")
        } catch {}
        do {
            try await store.purgeAccount(owner: owner)
            XCTFail("an unavailable inventory must block the exact-owner purge")
        } catch {}
        XCTAssertTrue(FileManager.default.fileExists(atPath: orphan.path))
        let preservedJob = try await store.job(id: jobID, ownerID: ownerID)
        XCTAssertNotNil(preservedJob)
    }

    func testAccountDeletionPurgesOnlyExactWalletRevealContainer() async throws {
        let store = FileRideUploadJobStore(rootURL: rootURL)
        let job = fixtureJob(id: jobID)
        try await store.create(job, sourceBytes: Data("ride-evidence".utf8))
        let ownerDirectory = try XCTUnwrap(
            FileManager.default.contentsOfDirectory(
                at: rootURL,
                includingPropertiesForKeys: nil
            ).first
        )
        let revealRoot = ownerDirectory.appendingPathComponent(".reveal-owners", isDirectory: true)
        let exactHash = FileRideUploadJobStore.sha256(
            Data("\(owner.id)\u{0}\(owner.wallet)".utf8)
        )
        let otherHash = FileRideUploadJobStore.sha256(
            Data("\(owner.id)\u{0}wallet-other".utf8)
        )
        let exact = revealRoot.appendingPathComponent(exactHash, isDirectory: true)
        let other = revealRoot.appendingPathComponent(otherHash, isDirectory: true)
        try FileManager.default.createDirectory(at: exact, withIntermediateDirectories: true)
        try FileManager.default.createDirectory(at: other, withIntermediateDirectories: true)

        let records = try await store.accountDeletionRecords(owner: owner)
        XCTAssertEqual(records.map(\.id), [jobID])
        try await store.purgeAccount(owner: owner)

        XCTAssertFalse(FileManager.default.fileExists(atPath: exact.path))
        XCTAssertTrue(FileManager.default.fileExists(atPath: other.path))
    }

    func testLegacyOwnerIDRevealArtifactBlocksWithoutBeingErased() async throws {
        let store = FileRideUploadJobStore(rootURL: rootURL)
        let job = fixtureJob(id: jobID)
        try await store.create(job, sourceBytes: Data("ride-evidence".utf8))
        let ownerDirectory = try XCTUnwrap(
            FileManager.default.contentsOfDirectory(
                at: rootURL,
                includingPropertiesForKeys: nil
            ).first
        )
        let legacy = ownerDirectory.appendingPathComponent(
            "active-reveal-claim.json",
            isDirectory: false
        )
        try Data("{}".utf8).write(to: legacy)

        do {
            try await store.purgeAccount(owner: owner)
            XCTFail("owner-ID-only reveal data cannot be assigned to this wallet")
        } catch {}
        XCTAssertTrue(FileManager.default.fileExists(atPath: legacy.path))
        let preservedJob = try await store.job(id: jobID, ownerID: ownerID)
        XCTAssertNotNil(preservedJob)
    }

    func testPrivacyReviewBlocksServerHandoffUntilExactPublicationIsSaved() async throws {
        let source = Data("reviewed-ride-evidence".utf8)
        let store = FileRideUploadJobStore(rootURL: rootURL)
        let service = UploadServiceFake(fixedRideID: jobID, statuses: [status("processing")])
        let transfer = TransferFake()
        let auth = AuthorizationFake(owner: owner)
        let coordinator = makeCoordinator(
            store: store,
            service: service,
            transfer: transfer,
            auth: auth
        )
        let publication = RidePublicationSettings(
            visibility: .followers,
            mapVisibility: .hideStartEnd,
            mapHideStartM: 200,
            mapHideEndM: 200
        )

        let job = try await coordinator.enqueue(
            ownerID: ownerID,
            ownerWallet: ownerWallet,
            fileName: "Ride.gpx",
            fileType: "gpx",
            sourceBytes: source,
            summary: LocalRideSummary(
                startedAt: now,
                distanceM: 12_345,
                elevationM: 456,
                durationS: 3_210
            ),
            requiresPublicationReview: true
        )

        XCTAssertEqual(job.phase, .awaitingPrivacyReview)
        await coordinator.reconcile(jobID: job.id, ownerID: ownerID)
        let callsBeforeApproval = await service.initializeCallCount
        XCTAssertEqual(callsBeforeApproval, 0)

        let approved = try await coordinator.approvePublication(
            jobID: job.id,
            owner: owner,
            settings: publication
        )
        XCTAssertEqual(approved.phase, .queued)
        XCTAssertEqual(approved.publication, publication)

        await coordinator.reconcile(jobID: job.id, ownerID: ownerID)
        let callsAfterApproval = await service.initializeCallCount
        let initializedPublication = await service.lastInitializedPublication
        XCTAssertEqual(callsAfterApproval, 1)
        XCTAssertEqual(initializedPublication, publication)

        var changed = approved
        changed.publication = publication.changingVisibility(.everyone)
        do {
            try await store.save(changed)
            XCTFail("publication settings must remain immutable after approval")
        } catch let error as RideUploadStoreError {
            XCTAssertEqual(error, .immutableMetadataChanged)
        }
    }

    /// L3.05: an explicit operator disable pauses server handoff without
    /// touching custody; the next status read (rollback) resumes it. An
    /// unknown capability state is never treated as a kill signal.
    func testUploadKillSwitchPausesHandoffAndRollbackResumes() async throws {
        defer { MobileCapabilityStore.shared.reset() }
        let source = Data("kill-switch-evidence".utf8)
        let store = FileRideUploadJobStore(rootURL: rootURL)
        let service = UploadServiceFake(fixedRideID: jobID, statuses: [status("processing")])
        let transfer = TransferFake()
        let auth = AuthorizationFake(owner: owner)
        let coordinator = makeCoordinator(
            store: store, service: service, transfer: transfer, auth: auth
        )

        let job = try await coordinator.enqueue(
            ownerID: ownerID,
            ownerWallet: ownerWallet,
            fileName: "Ride.gpx",
            fileType: "gpx",
            sourceBytes: source,
            summary: LocalRideSummary(
                startedAt: now, distanceM: 1_000, elevationM: 10, durationS: 300
            ),
            requiresPublicationReview: true
        )
        _ = try await coordinator.approvePublication(
            jobID: job.id,
            owner: owner,
            settings: RidePublicationSettings(
                visibility: .followers,
                mapVisibility: .hideStartEnd,
                mapHideStartM: 200,
                mapHideEndM: 200
            )
        )

        MobileCapabilityStore.shared.adopt(block: MobileCapabilitiesResponse(
            contractVersion: "mobile_caps.v1",
            rideUpload: false, pushRegistration: true, profileWrites: true
        ))
        await coordinator.reconcile(jobID: job.id, ownerID: ownerID)
        let callsWhileKilled = await service.initializeCallCount
        XCTAssertEqual(callsWhileKilled, 0, "disabled capability must pause handoff")
        let paused = try await store.jobs(ownerID: ownerID)[0]
        XCTAssertEqual(paused.phase, .retryable)
        XCTAssertTrue(paused.canRetry)
        let storedURL = try await store.sourceURL(for: paused)
        XCTAssertEqual(try Data(contentsOf: storedURL), source, "custody untouched")

        // Rollback: the operator lever returns and the same job proceeds.
        MobileCapabilityStore.shared.adopt(block: MobileCapabilitiesResponse(
            contractVersion: "mobile_caps.v1",
            rideUpload: true, pushRegistration: true, profileWrites: true
        ))
        await coordinator.reconcile(jobID: job.id, ownerID: ownerID)
        let callsAfterRollback = await service.initializeCallCount
        XCTAssertEqual(callsAfterRollback, 1)
    }

    func testPostRideApprovalPersistsDraftAndPhotoBeforeStablePublication() async throws {
        let store = FileRideUploadJobStore(rootURL: rootURL)
        let service = UploadServiceFake(fixedRideID: jobID, statuses: [status("processing")])
        let transfer = TransferFake()
        let auth = AuthorizationFake(owner: owner)
        let coordinator = makeCoordinator(
            store: store,
            service: service,
            transfer: transfer,
            auth: auth
        )
        let photoBytes = Data("exact-photo-bytes".utf8)
        let photo = try RidePhotoSelection(
            id: "22222222-2222-4222-8222-222222222222",
            fileName: "summit.jpg",
            mimeType: "image/jpeg",
            data: photoBytes
        )
        let draft = RidePostRideDraft(
            title: "Barren Hill before lunch",
            notes: "Quiet roads and a steady north wind.",
            photos: [photo.descriptor]
        )
        let publication = RidePublicationSettings(
            visibility: .followers,
            mapVisibility: .hideStartEnd,
            mapHideStartM: 200,
            mapHideEndM: 200
        )
        let job = try await coordinator.enqueue(
            ownerID: ownerID,
            ownerWallet: ownerWallet,
            fileName: "Ride.gpx",
            fileType: "gpx",
            sourceBytes: Data("ride-source".utf8),
            summary: LocalRideSummary(
                startedAt: now,
                distanceM: 12_345,
                elevationM: 456,
                durationS: 3_210
            ),
            requiresPublicationReview: true
        )

        let approved = try await coordinator.approvePublication(
            jobID: job.id,
            owner: owner,
            settings: publication,
            draft: draft,
            photoBytes: [photo.id: photo.data]
        )

        XCTAssertEqual(approved.postRideDraft, draft)
        let storedPhotoURL = try await store.photoURL(for: photo.descriptor, job: approved)
        XCTAssertEqual(try Data(contentsOf: storedPhotoURL), photoBytes)
        let callsBeforePublication = await service.initializeCallCount
        XCTAssertEqual(callsBeforePublication, 0)

        await coordinator.reconcile(jobID: job.id, ownerID: ownerID)

        let metadataDrafts = await service.metadataDrafts
        let initializedMediaIDs = await service.initializedMediaIDs
        let completedMediaIDs = await service.completedMediaIDs
        let uploadedJobIDs = await transfer.uploadedJobIDs
        XCTAssertEqual(metadataDrafts, [draft])
        XCTAssertEqual(initializedMediaIDs, [photo.id])
        XCTAssertEqual(completedMediaIDs, [photo.id])
        XCTAssertEqual(uploadedJobIDs, [jobID])
    }

    func testPhotoRetryReusesStableIdentityWithoutPublishingDuplicate() async throws {
        let store = FileRideUploadJobStore(rootURL: rootURL)
        let fileMissing = APIError.http(
            status: 400,
            code: "file_missing",
            message: "Photo not found in storage"
        )
        let service = UploadServiceFake(
            fixedRideID: jobID,
            completeResults: [
                .failure(fileMissing),
                .success(UploadCompleteResponse(rideId: jobID, status: "processing")),
            ],
            statuses: [status("processing")],
            mediaUploadResults: [
                .failure(URLError(.networkConnectionLost)),
                .success(()),
            ]
        )
        let transfer = TransferFake()
        let coordinator = makeCoordinator(
            store: store,
            service: service,
            transfer: transfer,
            auth: AuthorizationFake(owner: owner)
        )
        let photo = try RidePhotoSelection(
            id: "33333333-3333-4333-8333-333333333333",
            fileName: "road.jpg",
            mimeType: "image/jpeg",
            data: Data("retry-photo".utf8)
        )
        let job = try await coordinator.enqueue(
            ownerID: ownerID,
            ownerWallet: ownerWallet,
            fileName: "Ride.gpx",
            fileType: "gpx",
            sourceBytes: Data("retry-source".utf8),
            summary: LocalRideSummary(
                startedAt: now,
                distanceM: 1_000,
                elevationM: 20,
                durationS: 300
            ),
            requiresPublicationReview: true
        )
        _ = try await coordinator.approvePublication(
            jobID: job.id,
            owner: owner,
            settings: RidePublicationSettings(
                visibility: .everyone,
                mapVisibility: .showAll,
                mapHideStartM: 0,
                mapHideEndM: 0
            ),
            draft: RidePostRideDraft(
                title: "Road loop",
                notes: nil,
                photos: [photo.descriptor]
            ),
            photoBytes: [photo.id: photo.data]
        )

        await coordinator.reconcile(jobID: job.id, ownerID: ownerID)
        let failedJob = try await store.job(id: job.id, ownerID: ownerID)
        XCTAssertEqual(failedJob?.phase, .retryable)

        await coordinator.reconcile(jobID: job.id, ownerID: ownerID)

        let mediaIDs = await service.initializedMediaIDs
        let completedIDs = await service.completedMediaIDs
        let uploadIDs = await transfer.uploadedJobIDs
        XCTAssertEqual(mediaIDs, [photo.id, photo.id])
        XCTAssertEqual(completedIDs, [photo.id])
        XCTAssertEqual(uploadIDs, [jobID])
    }

    func testLegacyPreHandoffJobMigratesToPrivacyReviewBeforeAnyServerCall() async throws {
        let store = FileRideUploadJobStore(rootURL: rootURL)
        let service = UploadServiceFake(fixedRideID: jobID)
        let coordinator = makeCoordinator(
            store: store,
            service: service,
            transfer: TransferFake(),
            auth: AuthorizationFake(owner: owner)
        )
        let legacy = try await coordinator.enqueue(
            ownerID: ownerID,
            ownerWallet: ownerWallet,
            fileName: "Ride.gpx",
            fileType: "gpx",
            sourceBytes: Data("legacy-local-ride".utf8),
            summary: LocalRideSummary(
                startedAt: now,
                distanceM: 12_345,
                elevationM: 456,
                durationS: 3_210
            )
        )

        XCTAssertEqual(legacy.phase, .queued)
        XCTAssertNil(legacy.publication)

        await coordinator.reconcile(jobID: legacy.id, ownerID: ownerID)

        let migratedValue = try await store.job(id: legacy.id, ownerID: ownerID)
        let migrated = try XCTUnwrap(migratedValue)
        let initializeCallCount = await service.initializeCallCount
        XCTAssertEqual(migrated.phase, .awaitingPrivacyReview)
        XCTAssertNil(migrated.publication)
        XCTAssertEqual(initializeCallCount, 0)
    }

    func testLegacyAmbiguousHandoffReturnsToReviewOnlyAfterServerRowIsAbsent() async throws {
        let store = FileRideUploadJobStore(rootURL: rootURL)
        let service = UploadServiceFake(
            fixedRideID: jobID,
            completeResults: [
                .failure(
                    APIError.http(
                        status: 404,
                        code: nil,
                        message: "Upload not found"
                    )
                )
            ]
        )
        let coordinator = makeCoordinator(
            store: store,
            service: service,
            transfer: TransferFake(),
            auth: AuthorizationFake(owner: owner)
        )
        var legacy = try await coordinator.enqueue(
            ownerID: ownerID,
            ownerWallet: ownerWallet,
            fileName: "Ride.gpx",
            fileType: "gpx",
            sourceBytes: Data("legacy-ambiguous-ride".utf8),
            summary: LocalRideSummary(
                startedAt: now,
                distanceM: 12_345,
                elevationM: 456,
                durationS: 3_210
            )
        )
        legacy.phase = .retryable
        legacy.attemptedServerHandoff = true
        legacy.canRetry = true
        try await store.save(legacy)

        await coordinator.reconcile(jobID: legacy.id, ownerID: ownerID)

        let migratedValue = try await store.job(id: legacy.id, ownerID: ownerID)
        let migrated = try XCTUnwrap(migratedValue)
        let initializeCallCount = await service.initializeCallCount
        let completeUploadIDs = await service.completeUploadIDs
        XCTAssertEqual(migrated.phase, .awaitingPrivacyReview)
        XCTAssertFalse(migrated.attemptedServerHandoff)
        XCTAssertNil(migrated.publication)
        XCTAssertEqual(initializeCallCount, 0)
        XCTAssertEqual(completeUploadIDs, [jobID])
    }

    func testLegacyExistingServerRowResumesTransferWithoutRewritingPrivacy() async throws {
        let store = FileRideUploadJobStore(rootURL: rootURL)
        let service = UploadServiceFake(
            fixedRideID: jobID,
            completeResults: [
                .failure(
                    APIError.http(
                        status: 400,
                        code: "file_missing",
                        message: "File not found"
                    )
                )
            ]
        )
        let transfer = TransferFake()
        let coordinator = makeCoordinator(
            store: store,
            service: service,
            transfer: transfer,
            auth: AuthorizationFake(owner: owner)
        )
        var legacy = try await coordinator.enqueue(
            ownerID: ownerID,
            ownerWallet: ownerWallet,
            fileName: "Ride.gpx",
            fileType: "gpx",
            sourceBytes: Data("legacy-server-row".utf8),
            summary: LocalRideSummary(
                startedAt: now,
                distanceM: 12_345,
                elevationM: 456,
                durationS: 3_210
            )
        )
        legacy.phase = .retryable
        legacy.attemptedServerHandoff = true
        legacy.canRetry = true
        try await store.save(legacy)

        await coordinator.reconcile(jobID: legacy.id, ownerID: ownerID)

        let restoredValue = try await store.job(id: legacy.id, ownerID: ownerID)
        let restored = try XCTUnwrap(restoredValue)
        let initializeCallCount = await service.initializeCallCount
        let initializedPublications = await service.initializedPublications
        let completeUploadIDs = await service.completeUploadIDs
        let transferCount = await transfer.sourceHashes.count
        XCTAssertEqual(restored.serverRideID, jobID)
        XCTAssertEqual(restored.phase, .processing)
        XCTAssertNil(restored.publication)
        XCTAssertEqual(initializeCallCount, 1)
        XCTAssertEqual(initializedPublications, [nil])
        XCTAssertEqual(completeUploadIDs, [jobID, jobID])
        XCTAssertEqual(transferCount, 1)
    }

    func testInterruptedCreateNeverPublishesSourceWithoutJobMetadata() async throws {
        let source = Data("ride-evidence".utf8)
        let store = FileRideUploadJobStore(
            rootURL: rootURL,
            beforePublish: { throw TestFault.interrupted }
        )
        let job = fixtureJob(id: jobID)

        do {
            try await store.create(job, sourceBytes: source)
            XCTFail("fault injection must interrupt publication")
        } catch TestFault.interrupted {
            // Expected process-interruption seam.
        }

        let ownerKey = FileRideUploadJobStore.sha256(Data(ownerID.utf8))
        let publishedDirectory = rootURL
            .appendingPathComponent(ownerKey, isDirectory: true)
            .appendingPathComponent(job.id, isDirectory: true)
        XCTAssertFalse(
            FileManager.default.fileExists(atPath: publishedDirectory.path),
            "a restart must never discover source bytes without the durable job that owns them"
        )
        let storedJobs = try await store.jobs(ownerID: ownerID)
        XCTAssertTrue(storedJobs.isEmpty)
    }

    func testRevealConsumptionDedupesTwoLocalJobsBoundToOneAuthoritativeRide() async throws {
        let store = FileRideUploadJobStore(rootURL: rootURL)
        let source = Data("ride-evidence".utf8)
        let sharedRideID = "99999999-9999-4999-8999-999999999999"
        let reveal = RevealData(
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
        var first = fixtureJob(id: jobID)
        first.phase = .final
        first.serverRideID = sharedRideID
        first.revealState = .queued
        first.reveal = reveal
        var second = fixtureJob(id: "22222222-2222-4222-8222-222222222222")
        second.phase = .final
        second.serverRideID = sharedRideID
        second.revealState = .queued
        second.reveal = reveal
        try await store.create(first, sourceBytes: source)
        try await store.create(second, sourceBytes: source)

        let owner = RecordingOwner(id: ownerID, wallet: ownerWallet)
        let selectedValue = try await store.claimNextReveal(owner: owner)
        let selected = try XCTUnwrap(selectedValue)
        let restartedStore = FileRideUploadJobStore(rootURL: rootURL)
        let recovered = try await restartedStore.claimNextReveal(owner: owner)

        XCTAssertEqual(recovered, selected)
        try await restartedStore.acknowledgeReveal(
            id: selected.id,
            owner: owner,
            claimID: selected.claimID,
            authoritativeRideID: selected.authoritativeRideID
        )
        let replayStore = FileRideUploadJobStore(rootURL: rootURL)
        let replay = try await replayStore.claimNextReveal(owner: owner)
        XCTAssertNil(replay, "one acknowledged authoritative ride cannot replay")
    }

    func testTransientRestartRetriesSamePersistedLogicalAndServerID() async throws {
        let store = FileRideUploadJobStore(rootURL: rootURL)
        let service = UploadServiceFake(
            fixedRideID: jobID,
            completeResults: [
                .failure(APIError.http(status: 400, code: "file_missing", message: "File not found")),
                .success(UploadCompleteResponse(rideId: jobID, status: "processing")),
            ],
            statuses: [status("processing")]
        )
        let firstTransfer = TransferFake(results: [.failure(URLError(.networkConnectionLost))])
        let auth = AuthorizationFake(owner: RecordingOwner(id: ownerID, wallet: ownerWallet))
        let first = makeCoordinator(store: store, service: service, transfer: firstTransfer, auth: auth)
        let job = try await enqueue(first)

        await first.reconcile(jobID: job.id, ownerID: ownerID)

        let secondTransfer = TransferFake()
        let second = makeCoordinator(store: store, service: service, transfer: secondTransfer, auth: auth)
        await second.reconcile(jobID: job.id, ownerID: ownerID)

        let requestIDs = await service.initializeClientRequestIDs
        let firstHashes = await transferHashes(firstTransfer)
        let secondHashes = await transferHashes(secondTransfer)
        XCTAssertEqual(requestIDs, [jobID, jobID])
        XCTAssertEqual(firstHashes + secondHashes, [job.fileHash, job.fileHash])
        let restoredValue = try await store.job(id: job.id, ownerID: ownerID)
        let restored = try XCTUnwrap(restoredValue)
        XCTAssertEqual(restored.id, job.id)
        XCTAssertEqual(restored.serverRideID, job.id)
        XCTAssertEqual(restored.phase, .processing)
    }

    func testPendingAuthoritativeStatusReplaysCompleteForSamePersistedRideID() async throws {
        let store = FileRideUploadJobStore(rootURL: rootURL)
        let source = Data("ride-evidence".utf8)
        var job = fixtureJob(id: jobID)
        job.authoritativeStatus = "pending"
        try await store.create(job, sourceBytes: source)
        let service = UploadServiceFake(
            fixedRideID: jobID,
            completeResults: [
                .success(UploadCompleteResponse(rideId: jobID, status: "processing")),
            ],
            statuses: [status("pending")]
        )
        let coordinator = makeCoordinator(
            store: store,
            service: service,
            transfer: TransferFake(),
            auth: AuthorizationFake(owner: RecordingOwner(id: ownerID, wallet: ownerWallet))
        )

        await coordinator.reconcile(jobID: job.id, ownerID: ownerID)

        let statusRideIDs = await service.statusRideIDs
        let completeUploadIDs = await service.completeUploadIDs
        let restoredValue = try await store.job(id: job.id, ownerID: ownerID)
        XCTAssertEqual(statusRideIDs, [job.id])
        XCTAssertEqual(
            completeUploadIDs,
            [job.id],
            "pending is the durable pre-enqueue state and must replay completion with the same ID"
        )
        let restored = try XCTUnwrap(restoredValue)
        XCTAssertEqual(restored.serverRideID, job.id)
        XCTAssertEqual(restored.authoritativeStatus, "processing")
        XCTAssertNotEqual(restored.phase, .final)
    }

    func testConcurrentReconciliationIsSingleFlightPerPersistedJob() async throws {
        let store = FileRideUploadJobStore(rootURL: rootURL)
        let gate = AsyncGate()
        let service = UploadServiceFake(
            fixedRideID: jobID,
            statuses: [status("processing"), status("processing")],
            initializeGate: gate
        )
        let coordinator = makeCoordinator(
            store: store,
            service: service,
            transfer: TransferFake(),
            auth: AuthorizationFake(owner: RecordingOwner(id: ownerID, wallet: ownerWallet))
        )
        let job = try await enqueue(coordinator)

        let first = Task {
            await coordinator.reconcile(jobID: job.id, ownerID: ownerID)
        }
        while await gate.enteredCount == 0 { await Task.yield() }
        let second = Task {
            await coordinator.reconcile(jobID: job.id, ownerID: ownerID)
        }
        try await Task.sleep(for: .milliseconds(75))
        let overlappingInitializeCount = await gate.enteredCount
        await gate.releaseAll()
        await first.value
        await second.value
        let initializeCallCount = await service.initializeCallCount
        let completeCallCount = await service.completeUploadIDs.count

        XCTAssertEqual(
            overlappingInitializeCount,
            1,
            "scene, import, and background triggers must share one in-flight lifecycle per job"
        )
        XCTAssertEqual(initializeCallCount, 1)
        XCTAssertEqual(completeCallCount, 1)
    }

    func testExpiredAuthenticationPreservesQueuedJobAndSameJobResumesAfterValidSession() async throws {
        let store = FileRideUploadJobStore(rootURL: rootURL)
        let service = UploadServiceFake(fixedRideID: jobID, statuses: [status("processing")])
        let transfer = TransferFake()
        let auth = AuthorizationFake(owner: owner)
        let first = makeCoordinator(store: store, service: service, transfer: transfer, auth: auth)
        let job = try await enqueue(first)
        await auth.activate(owner: nil)

        await first.reconcile(jobID: job.id, ownerID: ownerID)
        var restoredValue = try await store.job(id: job.id, ownerID: ownerID)
        var restored = try XCTUnwrap(restoredValue)
        XCTAssertEqual(restored.phase, .queued)
        XCTAssertEqual(restored.attemptCount, 0)
        let preAuthCallCount = await service.initializeCallCount
        XCTAssertEqual(preAuthCallCount, 0)

        await auth.activate(owner: RecordingOwner(id: ownerID, wallet: ownerWallet))
        let second = makeCoordinator(store: store, service: service, transfer: transfer, auth: auth)
        await second.reconcile(jobID: job.id, ownerID: ownerID)
        restoredValue = try await store.job(id: job.id, ownerID: ownerID)
        restored = try XCTUnwrap(restoredValue)
        XCTAssertEqual(restored.id, job.id)
        XCTAssertEqual(restored.serverRideID, job.id)
        let requestIDs = await service.initializeClientRequestIDs
        XCTAssertEqual(requestIDs, [job.id])
    }

    func testOwnerSwitchCannotSendAnotherRidersPersistedJob() async throws {
        let store = FileRideUploadJobStore(rootURL: rootURL)
        let service = UploadServiceFake(fixedRideID: jobID)
        let transfer = TransferFake()
        let auth = AuthorizationFake(owner: owner)
        let coordinator = makeCoordinator(store: store, service: service, transfer: transfer, auth: auth)
        let job = try await enqueue(coordinator)
        await auth.activate(owner: RecordingOwner(id: "rider-2", wallet: "wallet-rider-2"))

        await coordinator.reconcile(jobID: job.id, ownerID: ownerID)

        let initializeCount = await service.initializeCallCount
        let transferCount = await transfer.callCount
        let storedPhase = try await store.job(id: job.id, ownerID: ownerID)?.phase
        XCTAssertEqual(initializeCount, 0)
        XCTAssertEqual(transferCount, 0)
        XCTAssertEqual(storedPhase, .queued)
    }

    func testSameIDDifferentWalletCannotSendPersistedJob() async throws {
        let store = FileRideUploadJobStore(rootURL: rootURL)
        let service = UploadServiceFake(fixedRideID: jobID, statuses: [status("processing")])
        let transfer = TransferFake()
        let auth = AuthorizationFake(owner: owner)
        let coordinator = makeCoordinator(
            store: store,
            service: service,
            transfer: transfer,
            auth: auth
        )
        let job = try await enqueue(coordinator)
        await auth.activate(owner: RecordingOwner(id: ownerID, wallet: "wallet-2"))
        let persistedSourceURL = try await store.sourceURL(for: job)
        let persistedSource = try Data(contentsOf: persistedSourceURL)

        await coordinator.reconcile(jobID: job.id, ownerID: ownerID)

        let initializeCount = await service.initializeCallCount
        let transferCount = await transfer.callCount
        let completeIDs = await service.completeUploadIDs
        let statusIDs = await service.statusRideIDs
        let stored = try await store.job(id: job.id, ownerID: ownerID)
        let sourceAfterReconcile = try Data(contentsOf: persistedSourceURL)
        XCTAssertEqual(initializeCount, 0)
        XCTAssertEqual(transferCount, 0)
        XCTAssertTrue(completeIDs.isEmpty)
        XCTAssertTrue(statusIDs.isEmpty)
        XCTAssertEqual(stored, job)
        XCTAssertEqual(sourceAfterReconcile, persistedSource)
        XCTAssertEqual(stored?.phase, .queued)
    }

    func testSameIDDifferentWalletRetryIsNoOpAndPreservesPersistedJob() async throws {
        let store = FileRideUploadJobStore(rootURL: rootURL)
        let service = UploadServiceFake(fixedRideID: jobID)
        let auth = AuthorizationFake(owner: owner)
        let coordinator = makeCoordinator(
            store: store,
            service: service,
            transfer: TransferFake(),
            auth: auth
        )
        var failed = try await enqueue(coordinator)
        failed.phase = .failed
        failed.attemptedServerHandoff = true
        failed.serverRideID = failed.id
        failed.authoritativeStatus = "failed"
        failed.lastError = "Processing failed"
        failed.canRetry = true
        try await store.save(failed)
        await auth.activate(owner: RecordingOwner(id: ownerID, wallet: "wallet-2"))
        let persistedSourceURL = try await store.sourceURL(for: failed)
        let persistedSource = try Data(contentsOf: persistedSourceURL)

        await coordinator.retry(
            jobID: failed.id,
            owner: RecordingOwner(id: ownerID, wallet: "wallet-2")
        )

        let reprocessIDs = await service.reprocessRideIDs
        let stored = try await store.job(id: failed.id, ownerID: ownerID)
        let sourceAfterRetry = try Data(contentsOf: persistedSourceURL)
        XCTAssertTrue(reprocessIDs.isEmpty)
        XCTAssertEqual(stored, failed)
        XCTAssertEqual(sourceAfterRetry, persistedSource)
    }

    func testSameIDWalletChangeDuringInitializeCannotReachTransfer() async throws {
        let store = FileRideUploadJobStore(rootURL: rootURL)
        let initializeGate = AsyncGate()
        let service = UploadServiceFake(
            fixedRideID: jobID,
            statuses: [status("processing")],
            initializeGate: initializeGate
        )
        let transfer = TransferFake()
        let auth = AuthorizationFake(
            owner: RecordingOwner(id: ownerID, wallet: ownerWallet)
        )
        let coordinator = makeCoordinator(
            store: store,
            service: service,
            transfer: transfer,
            auth: auth
        )
        let job = try await enqueue(coordinator)

        let reconcile = Task {
            await coordinator.reconcile(jobID: job.id, ownerID: ownerID)
        }
        while await initializeGate.enteredCount == 0 { await Task.yield() }
        await auth.activate(owner: RecordingOwner(id: ownerID, wallet: "wallet-2"))
        await initializeGate.releaseAll()
        await reconcile.value

        let initializeCount = await service.initializeCallCount
        let transferCount = await transfer.callCount
        let completeIDs = await service.completeUploadIDs
        let statusIDs = await service.statusRideIDs
        let storedPhase = try await store.job(id: job.id, ownerID: ownerID)?.phase
        XCTAssertEqual(initializeCount, 1)
        XCTAssertEqual(transferCount, 0)
        XCTAssertTrue(completeIDs.isEmpty)
        XCTAssertTrue(statusIDs.isEmpty)
        XCTAssertEqual(storedPhase, .waitingForAuthentication)
    }

    func testOwnerIsRecheckedAfterStorageHandoffBeforeComplete() async throws {
        let store = FileRideUploadJobStore(rootURL: rootURL)
        let service = UploadServiceFake(fixedRideID: jobID)
        let auth = AuthorizationFake(owner: RecordingOwner(id: ownerID, wallet: ownerWallet))
        let coordinator = RideUploadCoordinator(
            store: store,
            service: service,
            transfer: OwnerSwitchTransfer(authorization: auth),
            authorization: auth,
            revealBuilder: StrictRevealBuilder(),
            now: { self.now },
            makeID: { self.jobID }
        )
        let job = try await enqueue(coordinator)

        await coordinator.reconcile(jobID: job.id, ownerID: ownerID)

        let completeIDs = await service.completeUploadIDs
        let storedPhase = try await store.job(id: job.id, ownerID: ownerID)?.phase
        XCTAssertTrue(completeIDs.isEmpty)
        XCTAssertEqual(storedPhase, .waitingForAuthentication)
    }

    func testUnavailableAndNonfinalOutcomesNeverQueueReveal() async throws {
        let cases: [Result<RideStatus, Error>] = [
            .success(status("pending")),
            .success(status("processing")),
            .success(status("metrics_ready")),
            .success(status("enriched")),
            .success(status("under_review")),
            .success(status("failed", error: "Processing failed")),
            .failure(URLError(.notConnectedToInternet)),
        ]

        for (index, statusResult) in cases.enumerated() {
            let caseRoot = rootURL.appendingPathComponent("case-\(index)")
            let store = FileRideUploadJobStore(rootURL: caseRoot)
            let id = String(format: "00000000-0000-4000-8000-%012d", index + 1)
            let service = UploadServiceFake(fixedRideID: id, statusResults: [statusResult])
            let coordinator = RideUploadCoordinator(
                store: store,
                service: service,
                transfer: TransferFake(),
                authorization: AuthorizationFake(
                    owner: RecordingOwner(id: ownerID, wallet: ownerWallet)
                ),
                revealBuilder: StrictRevealBuilder(),
                now: { self.now },
                makeID: { id }
            )
            let job = try await enqueue(coordinator)

            await coordinator.reconcile(jobID: job.id, ownerID: ownerID)

            let reveal = await coordinator.claimNextReveal(
                owner: RecordingOwner(id: ownerID, wallet: ownerWallet)
            )
            XCTAssertNil(reveal, "case \(index)")
            let storedValue = try await store.job(id: id, ownerID: ownerID)
            let stored = try XCTUnwrap(storedValue)
            XCTAssertNotEqual(stored.phase, .final, "case \(index)")
            if case .failure = statusResult {
                XCTAssertEqual(stored.phase, .processing, "unavailable status remains nonfinal")
            }
        }
    }

    func testFinalRevealRequiresOwnedCompletedDetailAndPatternsThenAcknowledgesOnceAcrossRestart() async throws {
        let store = FileRideUploadJobStore(rootURL: rootURL)
        let service = UploadServiceFake(
            fixedRideID: jobID,
            statuses: [status("completed")],
            detail: detail(id: jobID, status: "completed", isOwner: true),
            patterns: PatternsResponse(rideId: jobID, patterns: PatternsPayload(climbPatterns: []))
        )
        let auth = AuthorizationFake(owner: RecordingOwner(id: ownerID, wallet: ownerWallet))
        let owner = RecordingOwner(id: ownerID, wallet: ownerWallet)
        let first = makeCoordinator(store: store, service: service, transfer: TransferFake(), auth: auth)
        let job = try await enqueue(first)

        await first.reconcile(jobID: job.id, ownerID: ownerID)

        let statusRideIDs = await service.statusRideIDs
        let detailRideIDs = await service.detailRideIDs
        let patternRideIDs = await service.patternRideIDs
        let queuedState = try await store.job(id: job.id, ownerID: ownerID)?.revealState
        XCTAssertEqual(statusRideIDs, [job.id])
        XCTAssertEqual(detailRideIDs, [job.id])
        XCTAssertEqual(patternRideIDs, [job.id])
        XCTAssertEqual(queuedState, .queued)

        // Simulate process death before the app presents the queued ceremony.
        let second = makeCoordinator(store: store, service: service, transfer: TransferFake(), auth: auth)
        let firstReveal = await second.claimNextReveal(owner: owner)
        XCTAssertEqual(firstReveal?.id, job.id)

        let third = makeCoordinator(store: store, service: service, transfer: TransferFake(), auth: auth)
        let recovered = await third.claimNextReveal(owner: owner)
        XCTAssertEqual(recovered, firstReveal)
        let acknowledged = if let recovered {
            await third.acknowledgeReveal(recovered, owner: owner)
        } else {
            false
        }
        let fourth = makeCoordinator(store: store, service: service, transfer: TransferFake(), auth: auth)
        let replay = await fourth.claimNextReveal(owner: owner)
        let consumedState = try await store.job(id: job.id, ownerID: ownerID)?.revealState
        XCTAssertTrue(acknowledged)
        XCTAssertNil(replay)
        XCTAssertEqual(consumedState, .consumed)
    }

    func testSameIDDifferentWalletCannotClaimOrAcknowledgeReveal() async throws {
        let store = FileRideUploadJobStore(rootURL: rootURL)
        let source = Data("ride-evidence".utf8)
        var job = fixtureJob(id: jobID)
        job.phase = .final
        job.revealState = .queued
        job.reveal = RevealData(
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
        try await store.create(job, sourceBytes: source)
        let auth = AuthorizationFake(
            owner: RecordingOwner(id: ownerID, wallet: "wallet-2")
        )
        let coordinator = makeCoordinator(
            store: store,
            service: UploadServiceFake(fixedRideID: jobID),
            transfer: TransferFake(),
            auth: auth
        )

        let mismatchedOwner = RecordingOwner(id: ownerID, wallet: "wallet-2")
        let mismatchedClaim = await coordinator.claimNextReveal(owner: mismatchedOwner)
        XCTAssertNil(mismatchedClaim)

        let rightfulOwner = RecordingOwner(id: ownerID, wallet: ownerWallet)
        await auth.activate(owner: rightfulOwner)
        let rightfulValue = await coordinator.claimNextReveal(owner: rightfulOwner)
        let rightful = try XCTUnwrap(rightfulValue)
        await auth.activate(owner: RecordingOwner(id: ownerID, wallet: "wallet-2"))

        let acknowledged = await coordinator.acknowledgeReveal(
            rightful,
            owner: mismatchedOwner
        )
        let revealState = try await store.job(id: job.id, ownerID: ownerID)?.revealState
        XCTAssertFalse(acknowledged)
        XCTAssertEqual(revealState, .queued)
    }

    func testSameIDWalletChangeDuringFinalRereadCannotQueueReveal() async throws {
        let store = FileRideUploadJobStore(rootURL: rootURL)
        let detailGate = AsyncGate()
        let service = UploadServiceFake(
            fixedRideID: jobID,
            statuses: [status("completed")],
            detail: detail(id: jobID, status: "completed", isOwner: true),
            patterns: PatternsResponse(
                rideId: jobID,
                patterns: PatternsPayload(climbPatterns: [])
            ),
            detailGate: detailGate
        )
        let auth = AuthorizationFake(
            owner: RecordingOwner(id: ownerID, wallet: ownerWallet)
        )
        let coordinator = makeCoordinator(
            store: store,
            service: service,
            transfer: TransferFake(),
            auth: auth
        )
        let job = try await enqueue(coordinator)

        let reconcile = Task {
            await coordinator.reconcile(jobID: job.id, ownerID: ownerID)
        }
        while await detailGate.enteredCount == 0 { await Task.yield() }
        await auth.activate(owner: RecordingOwner(id: ownerID, wallet: "wallet-2"))
        await detailGate.releaseAll()
        await reconcile.value

        let patternIDs = await service.patternRideIDs
        let reveal = await coordinator.claimNextReveal(
            owner: RecordingOwner(id: ownerID, wallet: "wallet-2")
        )
        let storedValue = try await store.job(id: job.id, ownerID: ownerID)
        let stored = try XCTUnwrap(storedValue)
        XCTAssertTrue(patternIDs.isEmpty)
        XCTAssertNil(reveal)
        XCTAssertEqual(stored.phase, .waitingForAuthentication)
        XCTAssertEqual(stored.revealState, .none)
        XCTAssertNil(stored.reveal)
    }

    func testSameIDWalletChangeDuringOptionalGeometryCannotQueueReveal() async throws {
        let store = FileRideUploadJobStore(rootURL: rootURL)
        let gpsGate = AsyncGate()
        let service = UploadServiceFake(
            fixedRideID: jobID,
            statuses: [status("completed")],
            detail: detail(id: jobID, status: "completed", isOwner: true),
            patterns: PatternsResponse(
                rideId: jobID,
                patterns: PatternsPayload(climbPatterns: [])
            ),
            gpsGate: gpsGate
        )
        let auth = AuthorizationFake(
            owner: RecordingOwner(id: ownerID, wallet: ownerWallet)
        )
        let coordinator = makeCoordinator(
            store: store,
            service: service,
            transfer: TransferFake(),
            auth: auth
        )
        let job = try await enqueue(coordinator)

        let reconcile = Task {
            await coordinator.reconcile(jobID: job.id, ownerID: ownerID)
        }
        while await gpsGate.enteredCount == 0 { await Task.yield() }
        await auth.activate(owner: RecordingOwner(id: ownerID, wallet: "wallet-2"))
        await gpsGate.releaseAll()
        await reconcile.value

        let patternIDs = await service.patternRideIDs
        let reveal = await coordinator.claimNextReveal(
            owner: RecordingOwner(id: ownerID, wallet: "wallet-2")
        )
        let storedValue = try await store.job(id: job.id, ownerID: ownerID)
        let stored = try XCTUnwrap(storedValue)
        XCTAssertEqual(patternIDs, [jobID])
        XCTAssertNil(reveal)
        XCTAssertEqual(stored.phase, .waitingForAuthentication)
        XCTAssertEqual(stored.revealState, .none)
        XCTAssertNil(stored.reveal)
    }

    func testCompletedWithMismatchedOrUnavailableRereadStaysNonfinal() async throws {
        let store = FileRideUploadJobStore(rootURL: rootURL)
        let service = UploadServiceFake(
            fixedRideID: jobID,
            statuses: [status("completed")],
            detail: detail(id: "22222222-2222-4222-8222-222222222222", status: "completed", isOwner: true)
        )
        let coordinator = makeCoordinator(
            store: store,
            service: service,
            transfer: TransferFake(),
            auth: AuthorizationFake(owner: RecordingOwner(id: ownerID, wallet: ownerWallet))
        )
        let job = try await enqueue(coordinator)

        await coordinator.reconcile(jobID: job.id, ownerID: ownerID)

        let reveal = await coordinator.claimNextReveal(
            owner: RecordingOwner(id: ownerID, wallet: ownerWallet)
        )
        let storedPhase = try await store.job(id: job.id, ownerID: ownerID)?.phase
        XCTAssertNil(reveal)
        XCTAssertEqual(storedPhase, .processing)
    }

    func testProductionRevealFailsClosedUntilAttestedFinalOwnedRereadsAgree() throws {
        let job = fixtureJob(id: jobID)
        let detail = detail(id: jobID, status: "completed", isOwner: true)
        let patterns = PatternsResponse(
            rideId: jobID,
            patterns: PatternsPayload(climbPatterns: [])
        )
        var provisional = status("completed")
        provisional.processingStage = "completed"
        provisional.attestationStatus = "provisional"
        provisional.canonicalMatch = true

        XCTAssertThrowsError(
            try LiveRideRevealBuilder().build(
                job: job,
                status: provisional,
                detail: detail,
                patterns: patterns
            )
        )

        var attested = provisional
        attested.attestationStatus = "attested"
        let reveal = try LiveRideRevealBuilder().build(
            job: job,
            status: attested,
            detail: detail,
            patterns: patterns
        )
        XCTAssertEqual(reveal.calEarned, 47)

        attested.failure = RideProcessingFailure(
            phase: "phase3",
            message: "Processing failed",
            retryable: true,
            code: "processing_failed"
        )
        XCTAssertThrowsError(
            try LiveRideRevealBuilder().build(
                job: job,
                status: attested,
                detail: detail,
                patterns: patterns
            )
        )
    }

    func testProductionRevealCarriesReleaseAwareHeldStateWithoutCAL() throws {
        let job = fixtureJob(id: jobID)
        let detail = detail(id: jobID, status: "completed", isOwner: true)
        let patterns = PatternsResponse(
            rideId: jobID,
            patterns: PatternsPayload(climbPatterns: [])
        )
        let heldStatus = RideStatus(
            rideId: jobID,
            status: "completed",
            attestationStatus: "attested",
            canonicalMatch: true,
            processingStage: "completed",
            calEarned: nil,
            metrics: nil,
            effortPolicy: RideEffortPolicy(
                effortEvidenceTier: "power_verified",
                rewardPolicy: "threshold_provisional_hold_v1",
                thresholdEconomyState: "held",
                estimatedCal: nil,
                rewardableCal: nil,
                tributableCal: nil
            ),
            hasPatterns: true,
            errorMessage: nil,
            phase1Error: nil,
            phase2Error: nil,
            phase3Error: nil
        )

        let reveal = try LiveRideRevealBuilder().build(
            job: job,
            status: heldStatus,
            detail: detail,
            patterns: patterns
        )

        XCTAssertNil(reveal.calEarned)
        XCTAssertEqual(reveal.thresholdEconomyState, "held")
    }

    func testRideUploadRenderFixtureRequiresExactDebugMode() {
        XCTAssertEqual(
            RideUploadRenderFixtureMode(
                arguments: ["app", "-BRRideUploadRenderFixture", "processing"]
            ),
            .processing
        )
        XCTAssertEqual(
            RideUploadRenderFixtureMode(
                arguments: ["app", "-BRRideUploadRenderFixture", "failed"]
            ),
            .failed
        )
        XCTAssertEqual(
            RideUploadRenderFixtureMode(
                arguments: ["app", "-BRRideUploadRenderFixture", "held"]
            ),
            .held
        )
        XCTAssertNil(RideUploadRenderFixtureMode(arguments: ["app"]))
        XCTAssertNil(
            RideUploadRenderFixtureMode(
                arguments: ["app", "-BRRideUploadRenderFixture", "unknown"]
            )
        )
        XCTAssertNil(
            RideUploadRenderFixtureMode(
                arguments: [
                    "app", "-BRRideUploadRenderFixture", "processing",
                    "-BRRideUploadRenderFixture", "failed",
                ]
            )
        )
    }

    func testRideStatusDecodingPreservesAuthoritativeFinalityFields() throws {
        let payload = Data(
            """
            {
              "ride_id": "\(jobID)",
              "status": "completed",
              "attestation_status": "attested",
              "canonical_match": true,
              "processing_stage": "completed",
              "can_retry_processing": false,
              "failure": null
            }
            """.utf8
        )
        let decoder = JSONDecoder()
        decoder.keyDecodingStrategy = .convertFromSnakeCase
        let decoded = try decoder.decode(RideStatus.self, from: payload)

        XCTAssertEqual(decoded.rideId, jobID)
        XCTAssertEqual(decoded.processingStage, "completed")
        XCTAssertEqual(decoded.attestationStatus, "attested")
        XCTAssertEqual(decoded.canonicalMatch, true)
        XCTAssertEqual(decoded.canRetryProcessing, false)
        XCTAssertNil(decoded.failure)
    }

    @MainActor
    func testProductionFeedKeepsLocalProcessingWhenServerListIsUnavailable() async {
        let job = fixtureJob(id: jobID)
        let model = FeedModel(
            loadServerRides: { throw URLError(.notConnectedToInternet) },
            loadLocalJobs: { _ in [job] }
        )

        await model.reload(owner: owner)

        XCTAssertTrue(model.loaded)
        XCTAssertEqual(model.items.map(\.id), [jobID])
        guard case .local = model.items.first?.source else {
            return XCTFail("nonfinal local ride must remain the feed truth")
        }
    }

    @MainActor
    func testProductionFeedWithholdsEmptyWhenLocalAndServerReadsAreUnavailable() async {
        let model = FeedModel(
            loadServerRides: { throw URLError(.notConnectedToInternet) },
            loadLocalJobs: { _ in nil }
        )

        await model.reload(owner: owner)

        XCTAssertFalse(model.loaded)
        XCTAssertTrue(model.items.isEmpty)
    }

    func testRuntimeJobListingRequiresExactIDAndWallet() async throws {
        let store = FileRideUploadJobStore(rootURL: rootURL)
        let job = fixtureJob(id: jobID)
        try await store.create(job, sourceBytes: Data("ride-evidence".utf8))
        let runtime = RideUploadRuntime(
            store: store,
            transfer: TransferFake(),
            durableAccountWorkPermitted: testAccountWorkPermitted,
            immediateReconcile: { _, _ in }
        )
        let rebound = RecordingOwner(id: owner.id, wallet: "wallet-rebound")

        await runtime.activate(user: fixtureUser(owner: rebound))
        let reboundJobs = await runtime.jobs(owner: rebound)
        let formerOwnerWhileRebound = await runtime.jobs(owner: owner)
        XCTAssertEqual(reboundJobs, [])
        XCTAssertNil(formerOwnerWhileRebound)

        await runtime.activate(user: fixtureUser(owner: owner))
        let rightfulJobs = await runtime.jobs(owner: owner)
        XCTAssertEqual(rightfulJobs?.map(\.id), [jobID])
    }

    func testAccountDeletionFreezeRejectsNewImportEnqueue() async throws {
        let store = FileRideUploadJobStore(rootURL: rootURL)
        let runtime = RideUploadRuntime(
            store: store,
            transfer: TransferFake(),
            durableAccountWorkPermitted: testAccountWorkPermitted,
            immediateReconcile: { _, _ in }
        )
        let user = fixtureUser(owner: owner)
        await runtime.activate(user: user)

        try await runtime.freezeForAccountDeletion(owner: owner)

        do {
            _ = try await runtime.enqueue(
                user: user,
                fileName: "Late-Ride.gpx",
                fileType: "gpx",
                sourceBytes: Data("late-ride".utf8),
                summary: LocalRideSummary(
                    startedAt: now,
                    distanceM: 100,
                    elevationM: 10,
                    durationS: 30
                )
            )
            XCTFail("a frozen deletion owner must not admit a new import")
        } catch let error as RideUploadStoreError {
            XCTAssertEqual(error, .invalidOwner)
        }
        let storedJobs = try await store.jobs(ownerID: owner.id)
        XCTAssertTrue(storedJobs.isEmpty)
    }

    func testProcessDeletionFenceRejectsEnqueueBeforeRuntimeFreezeStarts() async throws {
        let store = FileRideUploadJobStore(rootURL: rootURL)
        let runtime = RideUploadRuntime(
            store: store,
            transfer: TransferFake(),
            durableAccountWorkPermitted: testAccountWorkPermitted,
            immediateReconcile: { _, _ in }
        )
        let user = fixtureUser(owner: owner)
        await runtime.activate(user: user)
        AccountDeletionProcessFence.record(
            AccountDeletionSessionRecord(state: .pending, owner: owner)
        )

        do {
            _ = try await runtime.enqueue(
                user: user,
                fileName: "Late-Ride.gpx",
                fileType: "gpx",
                sourceBytes: Data("late-ride".utf8),
                summary: LocalRideSummary(
                    startedAt: now,
                    distanceM: 100,
                    elevationM: 10,
                    durationS: 30
                )
            )
            XCTFail("the process deletion fence must close enqueue before upload freeze")
        } catch let error as RideUploadStoreError {
            XCTAssertEqual(error, .invalidOwner)
        }
        let storedJobs = try await store.jobs(ownerID: owner.id)
        XCTAssertTrue(storedJobs.isEmpty)
    }

    func testColdRuntimeActivationCannotReauthorizeDurablyFencedOwner() async throws {
        let store = FileRideUploadJobStore(rootURL: rootURL)
        let job = fixtureJob(id: jobID)
        try await store.create(job, sourceBytes: Data("ride-evidence".utf8))
        try AccountDeletionSessionRecordStore.recordRequired(
            AccountDeletionSessionRecord(state: .pending, owner: owner)
        )
        let runtime = RideUploadRuntime(
            store: store,
            transfer: TransferFake(),
            durableAccountWorkPermitted: testAccountWorkPermitted,
            immediateReconcile: { _, _ in }
        )

        await runtime.activate(user: fixtureUser(owner: owner))

        let writerVisibleJobs = await runtime.jobs(owner: owner)
        XCTAssertNil(
            writerVisibleJobs,
            "cold activation must not authorize ordinary upload work behind the durable fence"
        )

        try await runtime.freezeForAccountDeletion(owner: owner)
        let deletionRecords = try await runtime.accountDeletionRecords(owner: owner)
        XCTAssertEqual(
            deletionRecords.map(\.id),
            [jobID],
            "the same fence must leave exact-owner deletion inventory reachable"
        )
        try await runtime.purgeAccount(owner: owner)
        let remaining = try await store.jobs(ownerID: owner.id)
        XCTAssertTrue(remaining.isEmpty)
    }

    func testDurableDeletionFenceStopsAlreadyActiveInitializeContinuation() async throws {
        let store = FileRideUploadJobStore(rootURL: rootURL)
        let gate = AsyncGate()
        let service = UploadServiceFake(
            fixedRideID: jobID,
            statuses: [status("processing")],
            initializeGate: gate
        )
        let transfer = TransferFake()
        let authorization = RideUploadAuthorization(
            durableAccountWorkPermitted: testAccountWorkPermitted
        )
        await authorization.activate(owner: owner)
        let coordinator = RideUploadCoordinator(
            store: store,
            service: service,
            transfer: transfer,
            authorization: authorization,
            revealBuilder: StrictRevealBuilder(),
            now: { self.now },
            makeID: { self.jobID }
        )
        let job = try await enqueue(coordinator)
        let reconcile = Task {
            await coordinator.reconcile(jobID: job.id, ownerID: ownerID)
        }
        while await gate.enteredCount == 0 { await Task.yield() }

        try AccountDeletionSessionRecordStore.recordRequired(
            AccountDeletionSessionRecord(state: .pending, owner: owner)
        )
        await gate.releaseAll()
        await reconcile.value

        let initializeCount = await service.initializeCallCount
        let transferCount = await transfer.callCount
        let completeIDs = await service.completeUploadIDs
        let stored = try await store.job(id: job.id, ownerID: ownerID)
        XCTAssertEqual(initializeCount, 1, "the already-issued request may return")
        XCTAssertEqual(transferCount, 0, "its response cannot authorize the next writer")
        XCTAssertTrue(completeIDs.isEmpty, "completion cannot cross the deletion fence")
        XCTAssertNil(stored?.serverRideID)
        XCTAssertNil(stored?.signedURL)
        XCTAssertEqual(stored?.phase, .waitingForAuthentication)
    }

    func testPurgedDeletionOwnerReleasesRuntimeForNextExactRecoveryOwner() async throws {
        let runtime = RideUploadRuntime(
            store: FileRideUploadJobStore(rootURL: rootURL),
            transfer: TransferFake(),
            durableAccountWorkPermitted: testAccountWorkPermitted,
            immediateReconcile: { _, _ in }
        )
        let nextOwner = RecordingOwner(id: "next-owner", wallet: "next-wallet")

        try await runtime.freezeForAccountDeletion(owner: owner)
        try await runtime.purgeAccount(owner: owner)
        try await runtime.freezeForAccountDeletion(owner: nextOwner)

        let records = try await runtime.accountDeletionRecords(owner: nextOwner)
        XCTAssertTrue(records.isEmpty)
    }

    func testAccountDeletionFreezeWaitsForAdmittedEnqueueAndInventoriesItsPublishedJob() async throws {
        let enteredPublish = DispatchSemaphore(value: 0)
        let allowPublish = DispatchSemaphore(value: 0)
        let store = FileRideUploadJobStore(rootURL: rootURL) {
            enteredPublish.signal()
            guard allowPublish.wait(timeout: .now() + 3) == .success else {
                throw TestFault.interrupted
            }
        }
        let runtime = RideUploadRuntime(
            store: store,
            transfer: TransferFake(),
            durableAccountWorkPermitted: testAccountWorkPermitted,
            immediateReconcile: { _, _ in }
        )
        let user = fixtureUser(owner: owner)
        await runtime.activate(user: user)
        let enqueue = Task {
            try await runtime.enqueue(
                user: user,
                fileName: "Ride.gpx",
                fileType: "gpx",
                sourceBytes: Data("ride-evidence".utf8),
                summary: LocalRideSummary(
                    startedAt: now,
                    distanceM: 100,
                    elevationM: 10,
                    durationS: 30
                ),
                jobID: jobID
            )
        }
        XCTAssertEqual(enteredPublish.wait(timeout: .now() + 2), .success)
        let completion = FreezeCompletionProbe()
        let freeze = Task {
            try await runtime.freezeForAccountDeletion(owner: owner)
            await completion.markCompleted()
        }
        try await Task.sleep(for: .milliseconds(75))
        let completedWhilePublishing = await completion.completed
        XCTAssertFalse(completedWhilePublishing)

        allowPublish.signal()
        _ = try await enqueue.value
        try await freeze.value

        let records = try await runtime.accountDeletionRecords(owner: owner)
        XCTAssertEqual(records.map(\.id), [jobID])
    }

    func testOrphanMultipartBodyBlocksFreezeBeforeAnyCancellation() async throws {
        let transfer = DeletionBodyTransferFake(bodyJobIDs: [jobID])
        let runtime = RideUploadRuntime(
            store: FileRideUploadJobStore(rootURL: rootURL),
            transfer: transfer,
            durableAccountWorkPermitted: testAccountWorkPermitted,
            immediateReconcile: { _, _ in }
        )
        await runtime.activate(user: fixtureUser(owner: owner))

        do {
            try await runtime.freezeForAccountDeletion(owner: owner)
            XCTFail("a multipart body without a durable job must route to support")
        } catch {}

        let cancellations = await transfer.cancelledJobIDs
        XCTAssertTrue(cancellations.isEmpty)
        let bodyJobIDs = try await transfer.persistedBodyJobIDs()
        XCTAssertEqual(bodyJobIDs, [jobID])
    }

    func testExactMultipartBodyIsCancelledAndVerifiedAbsentDuringFreeze() async throws {
        let store = FileRideUploadJobStore(rootURL: rootURL)
        try await store.create(fixtureJob(id: jobID), sourceBytes: Data("ride-evidence".utf8))
        let transfer = DeletionBodyTransferFake(bodyJobIDs: [jobID])
        let runtime = RideUploadRuntime(
            store: store,
            transfer: transfer,
            durableAccountWorkPermitted: testAccountWorkPermitted,
            immediateReconcile: { _, _ in }
        )
        await runtime.activate(user: fixtureUser(owner: owner))

        try await runtime.freezeForAccountDeletion(owner: owner)

        let cancelledJobIDs = await transfer.cancelledJobIDs
        let remainingBodyJobIDs = try await transfer.persistedBodyJobIDs()
        XCTAssertEqual(cancelledJobIDs, [jobID])
        XCTAssertTrue(remainingBodyJobIDs.isEmpty)
    }

    func testBackgroundTransferDeletesAndReadsBackExactMultipartBody() async throws {
        let bodyRoot = rootURL.appendingPathComponent("bodies", isDirectory: true)
        try FileManager.default.createDirectory(at: bodyRoot, withIntermediateDirectories: true)
        let body = bodyRoot.appendingPathComponent("\(jobID).multipart")
        try Data("multipart-source".utf8).write(to: body)
        let transfer = BackgroundRideFileTransfer(
            bodyDirectoryURL: bodyRoot,
            sessionIdentifier: "com.boulderroller.tests.account-deletion.\(UUID().uuidString)"
        )

        let initialBodyJobIDs = try await transfer.persistedBodyJobIDs()
        XCTAssertEqual(initialBodyJobIDs, [jobID])
        try await transfer.cancel(jobIDs: [jobID])
        let remainingBodyJobIDs = try await transfer.persistedBodyJobIDs()
        XCTAssertTrue(remainingBodyJobIDs.isEmpty)
        XCTAssertFalse(FileManager.default.fileExists(atPath: body.path))
    }

    func testAccountDeletionCancellationFencesUploadBeforeMultipartPublication() async throws {
        let bodyRoot = rootURL.appendingPathComponent("bodies", isDirectory: true)
        let source = rootURL.appendingPathComponent("ride.gpx")
        try FileManager.default.createDirectory(at: rootURL, withIntermediateDirectories: true)
        try Data("ride-evidence".utf8).write(to: source)
        let enteredPublish = TestBlockingGate()
        let allowPublish = TestBlockingGate()
        let bodyWritten = TestBlockingGate()
        let allowTaskCreation = TestBlockingGate()
        let transfer = BackgroundRideFileTransfer(
            bodyDirectoryURL: bodyRoot,
            sessionIdentifier: "com.boulderroller.tests.account-deletion-fence.\(UUID().uuidString)",
            beforeUploadPublish: {
                enteredPublish.signal()
                _ = allowPublish.wait(seconds: 3)
            },
            afterUploadBodyWritten: {
                bodyWritten.signal()
                _ = allowTaskCreation.wait(seconds: 3)
            }
        )
        let upload = Task {
            try await transfer.upload(
                jobID: jobID,
                signedURL: "https://127.0.0.1:1/upload",
                sourceURL: source,
                fileName: "ride.gpx"
            )
        }
        XCTAssertTrue(enteredPublish.wait(seconds: 2))

        try await transfer.cancel(jobIDs: [jobID])
        allowPublish.signal()

        let crossedCancellation = await Task.detached {
            bodyWritten.wait(seconds: 1)
        }.value
        XCTAssertFalse(
            crossedCancellation,
            "a transfer admitted before deletion must not publish its body after cancellation"
        )
        allowTaskCreation.signal()
        _ = try? await upload.value
        let remainingBodyJobIDs = try await transfer.persistedBodyJobIDs()
        XCTAssertTrue(remainingBodyJobIDs.isEmpty)
    }

    func testAccountDeletionCancellationWaitsForTransferCompletionCallback() async throws {
        let bodyRoot = rootURL.appendingPathComponent("bodies", isDirectory: true)
        let source = rootURL.appendingPathComponent("ride.gpx")
        try FileManager.default.createDirectory(at: rootURL, withIntermediateDirectories: true)
        try Data("ride-evidence".utf8).write(to: source)
        let taskResumed = TestBlockingGate()
        let completionEntered = TestBlockingGate()
        let allowCompletion = TestBlockingGate()
        let transfer = BackgroundRideFileTransfer(
            bodyDirectoryURL: bodyRoot,
            sessionIdentifier: "com.boulderroller.tests.account-deletion-barrier.\(UUID().uuidString)",
            afterUploadTaskResumed: { taskResumed.signal() },
            beforeTaskCompletion: {
                completionEntered.signal()
                _ = allowCompletion.wait(seconds: 3)
            }
        )
        let upload = Task {
            try await transfer.upload(
                jobID: jobID,
                signedURL: "https://127.0.0.1:1/upload",
                sourceURL: source,
                fileName: "ride.gpx"
            )
        }
        let didResume = await Task.detached {
            taskResumed.wait(seconds: 2)
        }.value
        XCTAssertTrue(didResume)

        let cancellationCompletion = FreezeCompletionProbe()
        let cancellation = Task {
            try await transfer.cancel(jobIDs: [jobID])
            await cancellationCompletion.markCompleted()
        }
        let didEnterCompletion = await Task.detached {
            completionEntered.wait(seconds: 2)
        }.value
        XCTAssertTrue(didEnterCompletion)
        try await Task.sleep(for: .milliseconds(75))
        let completedBeforeCallback = await cancellationCompletion.completed
        XCTAssertFalse(
            completedBeforeCallback,
            "deletion cancellation must wait until URLSession completes the exact transfer"
        )

        allowCompletion.signal()
        try await cancellation.value
        _ = try? await upload.value
        let completedAfterCallback = await cancellationCompletion.completed
        XCTAssertTrue(completedAfterCallback)
    }

    func testDeletingACompletedRideRemovesOnlyTheExactOwnersFinalLocalCopy() async throws {
        let store = FileRideUploadJobStore(rootURL: rootURL)
        var job = fixtureJob(id: jobID)
        job.phase = .final
        try await store.create(job, sourceBytes: Data("ride-evidence".utf8))

        let wrongWallet = RecordingOwner(id: owner.id, wallet: "wallet-rebound")
        let refused = try await store.deleteFinalizedRide(
            serverRideID: jobID,
            owner: wrongWallet
        )
        let stillStored = try await store.jobs(ownerID: owner.id)
        XCTAssertFalse(refused)
        XCTAssertEqual(stillStored.map(\.id), [jobID])

        let removed = try await store.deleteFinalizedRide(
            serverRideID: jobID.uppercased(),
            owner: owner
        )
        let remaining = try await store.jobs(ownerID: owner.id)
        XCTAssertTrue(removed)
        XCTAssertTrue(remaining.isEmpty)
    }

    @MainActor
    func testFeedSameIDDifferentWalletClearsBeforeUnavailableReads() async {
        let job = fixtureJob(id: jobID)
        let rebound = RecordingOwner(id: owner.id, wallet: "wallet-rebound")
        let model = FeedModel(
            loadServerRides: { throw URLError(.notConnectedToInternet) },
            loadLocalJobs: { requested in requested == self.owner ? [job] : nil }
        )

        await model.reload(owner: owner)
        XCTAssertEqual(model.items.map(\.id), [jobID])

        await model.reload(owner: rebound)
        XCTAssertEqual(model.loadedOwner, rebound)
        XCTAssertTrue(model.items.isEmpty)
        XCTAssertFalse(model.loaded)
    }

    func testFeedDisplayInterleavesLocalSavedAndFractionalServerRideByRideTime() {
        let local = LocalSavedRide(
            id: "22222222-2222-4222-8222-222222222222",
            ownerID: owner.id,
            ownerWallet: owner.wallet,
            summary: LocalRideSummary(
                startedAt: Date(timeIntervalSince1970: 1_786_300_000),
                distanceM: 80,
                elevationM: 4,
                durationS: 20
            ),
            fileHash: String(repeating: "a", count: 64),
            preliminaryRideHash: String(repeating: "b", count: 64),
            parserVersion: 1
        )
        let server = Ride(
            id: jobID,
            title: "Ride",
            status: "completed",
            startedAt: "2026-08-10T12:00:00.123Z",
            distanceM: 12_345,
            elevationM: 456,
            elevationCorrectedM: nil,
            elevationCorrection: nil,
            durationS: 3_210,
            avgPowerW: nil,
            normalizedPowerW: nil,
            avgHrBpm: nil,
            tss: nil,
            calEarned: nil,
            tributableCal: nil,
            rewardableCal: nil,
            routePreview: nil,
            earnings: nil,
            calItemization: nil,
            isOwner: true
        )

        let ordered = FeedDisplayAssembler.merge(
            localSavedRides: [local],
            items: [RideFeedItem(id: server.id, source: .server(server))]
        )

        XCTAssertEqual(ordered.map(\.id), ["existing:\(jobID)", "local-saved:\(local.id)"])
    }

    @MainActor
    func testFeedClearsPriorOwnerWhenNextOwnersReadsAreUnavailable() async {
        let rideA = detail(id: jobID, status: "completed", isOwner: true).ride
        let serverReads = ServerRideReadSequence(
            results: [
                .success([rideA]),
                .failure(URLError(.notConnectedToInternet)),
            ]
        )
        let model = FeedModel(
            loadServerRides: { try await serverReads.next() },
            loadLocalJobs: { owner in owner.id == "owner-a" ? [] : nil }
        )

        await model.reload(owner: RecordingOwner(id: "owner-a", wallet: "wallet-a"))
        XCTAssertEqual(model.items.map(\.id), [rideA.id])

        await model.reload(owner: RecordingOwner(id: "owner-b", wallet: "wallet-b"))

        XCTAssertTrue(model.items.isEmpty)
        XCTAssertFalse(model.loaded, "owner A's cards cannot remain visible for owner B")
    }

    @MainActor
    func testSlowerPriorOwnerReloadCannotOverwriteCurrentOwner() async {
        let rideA = detail(id: jobID, status: "completed", isOwner: true).ride
        let rideB = detail(
            id: "22222222-2222-4222-8222-222222222222",
            status: "completed",
            isOwner: true
        ).ride
        let serverReads = TimedServerRideRace(slowRide: rideA, fastRide: rideB)
        let model = FeedModel(
            loadServerRides: { try await serverReads.next() },
            loadLocalJobs: { _ in [] }
        )

        let priorOwner = Task {
            await model.reload(owner: RecordingOwner(id: "owner-a", wallet: "wallet-a"))
        }
        while await serverReads.readCount == 0 { await Task.yield() }
        let currentOwner = Task {
            await model.reload(owner: RecordingOwner(id: "owner-b", wallet: "wallet-b"))
        }
        await currentOwner.value
        await priorOwner.value

        XCTAssertEqual(model.items.map(\.id), [rideB.id])
        guard case .server = model.items.first?.source else {
            return XCTFail("the current owner's successful server read must remain authoritative")
        }
    }

    @MainActor
    func testFeedPreservesLocalCardWhenRefreshLosesLocalStoreAvailability() async {
        let job = fixtureJob(id: jobID)
        let ride = detail(id: jobID, status: "completed", isOwner: true).ride
        let localReads = LocalJobReadSequence(results: [[job], nil])
        let model = FeedModel(
            loadServerRides: { [ride] },
            loadLocalJobs: { _ in await localReads.next() }
        )

        await model.reload(owner: owner)

        XCTAssertEqual(model.items.count, 1)
        guard case .local = model.items[0].source else {
            return XCTFail("an unavailable owner store cannot erase its already rendered local ride")
        }
    }

    @MainActor
    func testCompletedServerRideReplacesLocalCardOnlyAfterOwnedRereadsFinalizeJob() async {
        let job = fixtureJob(id: jobID)
        let ride = detail(id: jobID, status: "completed", isOwner: true).ride
        let nonfinalModel = FeedModel(
            loadServerRides: { [ride] },
            loadLocalJobs: { _ in [job] }
        )

        await nonfinalModel.reload(owner: owner)

        XCTAssertEqual(nonfinalModel.items.count, 1)
        guard case .local = nonfinalModel.items[0].source else {
            return XCTFail("a completed list row is nonfinal until owned rereads finalize the job")
        }

        let finalJob: RideUploadJob = {
            var copy = job
            copy.phase = .final
            copy.revealState = .consumed
            return copy
        }()
        let finalModel = FeedModel(
            loadServerRides: { [ride] },
            loadLocalJobs: { _ in [finalJob] }
        )

        await finalModel.reload(owner: owner)

        XCTAssertEqual(finalModel.items.count, 1)
        guard case let .server(rendered) = finalModel.items[0].source else {
            return XCTFail("the final owned ride must replace its local card")
        }
        XCTAssertEqual(rendered.id, jobID)
    }

    func testFeedRetainsLocalProcessingAndFailureWhenServerReadIsUnavailable() async throws {
        let store = FileRideUploadJobStore(rootURL: rootURL)
        let service = UploadServiceFake(fixedRideID: jobID)
        let coordinator = makeCoordinator(
            store: store,
            service: service,
            transfer: TransferFake(),
            auth: AuthorizationFake(owner: RecordingOwner(id: ownerID, wallet: ownerWallet))
        )
        let processing = try await enqueue(coordinator)
        var failed = processing
        failed = RideUploadJob(
            id: "33333333-3333-4333-8333-333333333333",
            ownerID: failed.ownerID,
            ownerWallet: failed.ownerWallet,
            fileName: failed.fileName,
            fileType: failed.fileType,
            fileHash: failed.fileHash,
            fileSize: failed.fileSize,
            sourceFileName: failed.sourceFileName,
            localSummary: failed.localSummary,
            createdAt: failed.createdAt.addingTimeInterval(1),
            updatedAt: failed.updatedAt,
            phase: .failed,
            attemptedServerHandoff: false,
            signedURL: nil,
            signedURLExpiresAt: nil,
            serverRideID: nil,
            authoritativeStatus: "failed",
            attemptCount: 1,
            nextRetryAt: nil,
            lastError: "Processing failed",
            canRetry: true,
            revealState: .none,
            reveal: nil
        )

        let items = RideFeedAssembler.merge(localJobs: [processing, failed], serverRides: nil)

        XCTAssertEqual(items.count, 2)
        XCTAssertEqual(Set(items.map(\.id)), Set([processing.id, failed.id]))
    }

    func testAmbiguousRetryableUploadRendersProcessingNotAuthoritativeFailure() {
        XCTAssertEqual(
            RideUploadFeedPresentation.statusText(for: .retryable),
            "Processing",
            "ambiguous transport and unavailable reads remain nonfinal"
        )
        XCTAssertEqual(
            RideUploadFeedPresentation.statusText(for: .failed),
            "Processing failed"
        )
    }

    /// Status renders as a caption under the title, never as the title —
    /// the strings are caption-shaped facts (bead c6l2l item 6).
    func testStatusCaptionsAreCaptionShapedFacts() {
        XCTAssertEqual(
            RideUploadFeedPresentation.statusText(for: .underReview),
            "Under review"
        )
        XCTAssertEqual(
            RideUploadFeedPresentation.statusText(for: .waitingForAuthentication),
            "Signed out"
        )
    }

    private func makeCoordinator(
        store: FileRideUploadJobStore,
        service: UploadServiceFake,
        transfer: TransferFake,
        auth: AuthorizationFake
    ) -> RideUploadCoordinator {
        RideUploadCoordinator(
            store: store,
            service: service,
            transfer: transfer,
            authorization: auth,
            revealBuilder: StrictRevealBuilder(),
            now: { self.now },
            makeID: { self.jobID }
        )
    }

    private func enqueue(
        _ coordinator: RideUploadCoordinator,
        bytes: Data = Data("ride-evidence".utf8)
    ) async throws -> RideUploadJob {
        let job = try await coordinator.enqueue(
            ownerID: ownerID,
            ownerWallet: ownerWallet,
            fileName: "Ride.gpx",
            fileType: "gpx",
            sourceBytes: bytes,
            summary: LocalRideSummary(
                startedAt: now.addingTimeInterval(-3_600),
                distanceM: 12_345,
                elevationM: 456,
                durationS: 3_210
            ),
            requiresPublicationReview: true
        )
        return try await coordinator.approvePublication(
            jobID: job.id,
            owner: owner,
            settings: RidePublicationSettings(
                visibility: .everyone,
                mapVisibility: .hideStartEnd,
                mapHideStartM: 200,
                mapHideEndM: 200
            )
        )
    }

    private func status(_ value: String, error: String? = nil) -> RideStatus {
        RideStatus(
            rideId: jobID,
            status: value,
            calEarned: value == "completed" ? 47 : nil,
            metrics: RideStatusMetrics(
                tss: nil,
                distanceM: 12_345,
                elevationGainM: 456,
                durationSec: 3_210,
                avgPowerW: nil,
                normalizedPowerW: nil
            ),
            effortPolicy: nil,
            hasPatterns: value == "completed",
            errorMessage: error,
            phase1Error: nil,
            phase2Error: nil,
            phase3Error: nil
        )
    }

    private func detail(id: String, status: String, isOwner: Bool) -> RideDetailResponse {
        RideDetailResponse(
            ride: Ride(
                id: id,
                title: "Morning Ride",
                status: status,
                startedAt: "2026-08-10T12:00:00Z",
                distanceM: 12_345,
                elevationM: 456,
                elevationCorrectedM: nil,
                elevationCorrection: nil,
                durationS: 3_210,
                avgPowerW: nil,
                normalizedPowerW: nil,
                avgHrBpm: nil,
                tss: nil,
                calEarned: 47,
                tributableCal: nil,
                rewardableCal: 47,
                routePreview: nil,
                earnings: nil,
                calItemization: nil,
                isOwner: isOwner
            ),
            status: nil
        )
    }

    private func transferHashes(_ transfer: TransferFake) async -> [String] {
        await transfer.sourceHashes
    }

    private func fixtureJob(id: String, wallet: String? = nil) -> RideUploadJob {
        let bytes = Data("ride-evidence".utf8)
        return RideUploadJob(
            id: id,
            ownerID: ownerID,
            ownerWallet: wallet ?? ownerWallet,
            fileName: "Ride.gpx",
            fileType: "gpx",
            fileHash: FileRideUploadJobStore.sha256(bytes),
            fileSize: bytes.count,
            sourceFileName: "source.gpx",
            localSummary: LocalRideSummary(
                startedAt: now,
                distanceM: 12_345,
                elevationM: 456,
                durationS: 3_210
            ),
            createdAt: now,
            updatedAt: now,
            phase: .processing,
            attemptedServerHandoff: true,
            signedURL: nil,
            signedURLExpiresAt: nil,
            serverRideID: id,
            authoritativeStatus: "completed",
            attemptCount: 1,
            nextRetryAt: nil,
            lastError: nil,
            canRetry: false,
            revealState: .none,
            reveal: nil
        )
    }

    private func fixtureUser(owner: RecordingOwner) -> User {
        User(
            id: owner.id,
            wallet: owner.wallet,
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
}

private enum TestFault: Error {
    case interrupted
}

private let testAccountWorkPermitted: @Sendable (RecordingOwner) -> Bool = { owner in
    AccountDeletionLocalFence.permitsAccountWork(
        owner: owner,
        sessionRecords: AccountDeletionSessionRecordStore.records()
            + AccountDeletionProcessFence.records(),
        capabilityState: .none
    )
}

private final class TestBlockingGate: @unchecked Sendable {
    private let semaphore = DispatchSemaphore(value: 0)

    func signal() {
        semaphore.signal()
    }

    func wait(seconds: Double) -> Bool {
        semaphore.wait(timeout: .now() + seconds) == .success
    }
}

private actor FreezeCompletionProbe {
    private(set) var completed = false

    func markCompleted() {
        completed = true
    }
}

private actor DeletionBodyTransferFake: RideFileTransferring {
    private var bodyJobIDs: Set<String>
    private(set) var cancelledJobIDs: Set<String> = []

    init(bodyJobIDs: Set<String>) {
        self.bodyJobIDs = bodyJobIDs
    }

    func isActive(jobID: String) -> Bool { false }

    func upload(
        jobID: String,
        signedURL: String,
        sourceURL: URL,
        fileName: String
    ) async throws {}

    func persistedBodyJobIDs() async throws -> Set<String> { bodyJobIDs }

    func cancel(jobIDs: Set<String>) async throws {
        cancelledJobIDs.formUnion(jobIDs)
        bodyJobIDs.subtract(jobIDs)
    }
}

private actor LocalJobReadSequence {
    private var results: [[RideUploadJob]?]

    init(results: [[RideUploadJob]?]) {
        self.results = results
    }

    func next() -> [RideUploadJob]? {
        guard !results.isEmpty else { return nil }
        return results.removeFirst()
    }
}

private actor ServerRideReadSequence {
    private var results: [Result<[Ride], Error>]
    private(set) var readCount = 0

    init(results: [Result<[Ride], Error>]) {
        self.results = results
    }

    func next() throws -> [Ride] {
        readCount += 1
        guard !results.isEmpty else { throw URLError(.badServerResponse) }
        return try results.removeFirst().get()
    }
}

private actor TimedServerRideRace {
    private let slowRide: Ride
    private let fastRide: Ride
    private(set) var readCount = 0

    init(slowRide: Ride, fastRide: Ride) {
        self.slowRide = slowRide
        self.fastRide = fastRide
    }

    func next() async throws -> [Ride] {
        readCount += 1
        if readCount == 1 {
            try await Task.sleep(for: .milliseconds(200))
            return [slowRide]
        }
        return [fastRide]
    }
}

private actor AsyncGate {
    private var continuations: [CheckedContinuation<Void, Never>] = []
    private(set) var enteredCount = 0

    func wait() async {
        enteredCount += 1
        await withCheckedContinuation { continuation in
            continuations.append(continuation)
        }
    }

    func releaseAll() {
        let pending = continuations
        continuations.removeAll()
        pending.forEach { $0.resume() }
    }
}

private enum RevealBuildError: Error { case notOwnedFinalRide }

private struct StrictRevealBuilder: RideRevealBuilding {
    func build(
        job: RideUploadJob,
        status: RideStatus,
        detail: RideDetailResponse,
        patterns: PatternsResponse
    ) throws -> RevealData {
        guard status.status == "completed",
              detail.ride.id == job.id,
              detail.ride.status == "completed",
              detail.ride.isOwner == true,
              patterns.rideId == job.id
        else { throw RevealBuildError.notOwnedFinalRide }
        return RevealData(
            title: detail.ride.title,
            subtitle: "Sunday 8:00 AM",
            calEarned: detail.ride.calEarned ?? 0,
            distanceM: detail.ride.distanceM,
            elevationM: detail.ride.elevationM,
            durationS: detail.ride.durationS,
            climbs: [],
            tributeCal: detail.ride.tributableCal,
            leaderboardEntry: nil
        )
    }
}

private actor AuthorizationFake: RideUploadAuthorizing {
    private var owner: RecordingOwner?

    init(owner: RecordingOwner?) { self.owner = owner }

    func activate(owner: RecordingOwner?) { self.owner = owner }

    func activeOwner(matching ownerID: String) -> RecordingOwner? {
        guard owner?.id == ownerID else { return nil }
        return owner
    }

    func permits(owner expectedOwner: RecordingOwner) -> Bool {
        owner == expectedOwner
    }
}

private actor TransferFake: RideFileTransferring {
    private var results: [Result<Void, Error>]
    private(set) var sourceHashes: [String] = []
    private(set) var uploadedJobIDs: [String] = []
    private(set) var callCount = 0

    init(results: [Result<Void, Error>] = []) { self.results = results }
    func isActive(jobID: String) -> Bool { false }

    func persistedBodyJobIDs() async throws -> Set<String> { [] }

    func cancel(jobIDs: Set<String>) async throws {}

    func upload(jobID: String, signedURL: String, sourceURL: URL, fileName: String) throws {
        callCount += 1
        uploadedJobIDs.append(jobID)
        sourceHashes.append(FileRideUploadJobStore.sha256(try Data(contentsOf: sourceURL)))
        if !results.isEmpty {
            try results.removeFirst().get()
        }
    }
}

private actor OwnerSwitchTransfer: RideFileTransferring {
    let authorization: AuthorizationFake

    init(authorization: AuthorizationFake) {
        self.authorization = authorization
    }

    func isActive(jobID: String) -> Bool { false }

    func persistedBodyJobIDs() async throws -> Set<String> { [] }

    func cancel(jobIDs: Set<String>) async throws {}

    func upload(jobID: String, signedURL: String, sourceURL: URL, fileName: String) async {
        await authorization.activate(
            owner: RecordingOwner(id: "rider-2", wallet: "wallet-rider-2")
        )
    }
}

private actor UploadServiceFake: RideUploadServicing {
    let fixedRideID: String
    private var completeResults: [Result<UploadCompleteResponse, Error>]
    private var statusResults: [Result<RideStatus, Error>]
    private var mediaUploadResults: [Result<Void, Error>]
    private let fixedDetail: RideDetailResponse?
    private let fixedPatterns: PatternsResponse?
    private let initializeGate: AsyncGate?
    private let detailGate: AsyncGate?
    private let gpsGate: AsyncGate?

    private(set) var initializeClientRequestIDs: [String] = []
    private(set) var initializedPublications: [RidePublicationSettings?] = []
    private(set) var completeUploadIDs: [String] = []
    private(set) var statusRideIDs: [String] = []
    private(set) var detailRideIDs: [String] = []
    private(set) var patternRideIDs: [String] = []
    private(set) var reprocessRideIDs: [String] = []
    private(set) var metadataDrafts: [RidePostRideDraft] = []
    private(set) var initializedMediaIDs: [String] = []
    private(set) var completedMediaIDs: [String] = []
    private var readyMedia: [RideMedia] = []
    private var pendingMediaID: String?
    private var uploadedMediaIDs: Set<String> = []
    var initializeCallCount: Int { initializeClientRequestIDs.count }
    var lastInitializedPublication: RidePublicationSettings? {
        initializedPublications.last ?? nil
    }

    init(
        fixedRideID: String,
        completeResults: [Result<UploadCompleteResponse, Error>] = [],
        statuses: [RideStatus] = [],
        statusResults: [Result<RideStatus, Error>] = [],
        detail: RideDetailResponse? = nil,
        patterns: PatternsResponse? = nil,
        initializeGate: AsyncGate? = nil,
        detailGate: AsyncGate? = nil,
        gpsGate: AsyncGate? = nil,
        mediaUploadResults: [Result<Void, Error>] = []
    ) {
        self.fixedRideID = fixedRideID
        self.completeResults = completeResults
        self.statusResults = statusResults.isEmpty ? statuses.map(Result.success) : statusResults
        self.fixedDetail = detail
        self.fixedPatterns = patterns
        self.initializeGate = initializeGate
        self.detailGate = detailGate
        self.gpsGate = gpsGate
        self.mediaUploadResults = mediaUploadResults
    }

    func initialize(job: RideUploadJob, clientRequestID: String) async -> UploadInitResponse {
        initializeClientRequestIDs.append(clientRequestID)
        initializedPublications.append(job.publication)
        if let initializeGate { await initializeGate.wait() }
        return UploadInitResponse(
            uploadId: fixedRideID,
            signedUrl: "https://example.invalid/upload",
            expiresIn: 600
        )
    }

    func resumeLegacyUpload(
        job: RideUploadJob,
        clientRequestID: String
    ) async -> UploadInitResponse {
        initializeClientRequestIDs.append(clientRequestID)
        initializedPublications.append(job.publication)
        if let initializeGate { await initializeGate.wait() }
        return UploadInitResponse(
            uploadId: fixedRideID,
            signedUrl: "https://example.invalid/upload",
            expiresIn: 600
        )
    }

    func complete(uploadID: String) throws -> UploadCompleteResponse {
        completeUploadIDs.append(uploadID)
        if !completeResults.isEmpty { return try completeResults.removeFirst().get() }
        return UploadCompleteResponse(rideId: fixedRideID, status: "processing")
    }

    func status(rideID: String) throws -> RideStatus {
        statusRideIDs.append(rideID)
        guard !statusResults.isEmpty else {
            throw URLError(.notConnectedToInternet)
        }
        return try statusResults.removeFirst().get()
    }

    func detail(rideID: String) async throws -> RideDetailResponse {
        detailRideIDs.append(rideID)
        if let detailGate { await detailGate.wait() }
        guard let fixedDetail else { throw URLError(.cannotDecodeContentData) }
        return fixedDetail
    }

    func spine(rideID: String) async throws -> RideSpineData? {
        if let gpsGate { await gpsGate.wait() }
        return nil
    }

    func patterns(rideID: String) throws -> PatternsResponse {
        patternRideIDs.append(rideID)
        guard let fixedPatterns else { throw URLError(.cannotDecodeContentData) }
        return fixedPatterns
    }

    func reprocess(rideID: String) {
        reprocessRideIDs.append(rideID)
    }

    func updatePostRideDraft(rideID: String, draft: RidePostRideDraft) {
        metadataDrafts.append(draft)
    }

    func media(rideID: String) -> [RideMedia] { readyMedia }

    func initializeMedia(
        rideID: String,
        photo: RidePhotoDescriptor
    ) -> RideMediaUploadInit {
        initializedMediaIDs.append(photo.id)
        pendingMediaID = photo.id
        return RideMediaUploadInit(
            mediaId: photo.id,
            signedUrl: "https://example.invalid/photo",
            expiresIn: 600
        )
    }

    func uploadMedia(signedURL: String, sourceURL: URL, fileName: String) throws {
        _ = try Data(contentsOf: sourceURL)
        if !mediaUploadResults.isEmpty {
            try mediaUploadResults.removeFirst().get()
        }
        if let pendingMediaID { uploadedMediaIDs.insert(pendingMediaID) }
    }

    func completeMedia(rideID: String, mediaID: String) throws -> RideMedia {
        guard uploadedMediaIDs.contains(mediaID) else {
            throw APIError.http(status: 404, code: nil, message: "Media upload not found")
        }
        let media = RideMedia(
            id: mediaID,
            rideId: rideID,
            url: "https://example.invalid/photo.jpg",
            fileName: "summit.jpg",
            mimeType: "image/jpeg",
            sizeBytes: 17,
            width: nil,
            height: nil,
            sortOrder: readyMedia.count,
            role: readyMedia.isEmpty ? "cover" : "photo",
            moderationState: "visible",
            createdAt: nil
        )
        completedMediaIDs.append(mediaID)
        readyMedia.append(media)
        return media
    }
}
