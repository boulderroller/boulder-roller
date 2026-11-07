import Foundation

protocol RideUploadServicing: Sendable {
    func initialize(job: RideUploadJob, clientRequestID: String) async throws -> UploadInitResponse
    func resumeLegacyUpload(
        job: RideUploadJob,
        clientRequestID: String
    ) async throws -> UploadInitResponse
    func complete(uploadID: String) async throws -> UploadCompleteResponse
    func status(rideID: String) async throws -> RideStatus
    func detail(rideID: String) async throws -> RideDetailResponse
    func patterns(rideID: String) async throws -> PatternsResponse
    func spine(rideID: String) async throws -> RideSpineData?
    func reprocess(rideID: String) async throws
    func updatePostRideDraft(rideID: String, draft: RidePostRideDraft) async throws
    func media(rideID: String) async throws -> [RideMedia]
    func initializeMedia(
        rideID: String,
        photo: RidePhotoDescriptor
    ) async throws -> RideMediaUploadInit
    func uploadMedia(
        signedURL: String,
        sourceURL: URL,
        fileName: String
    ) async throws
    func completeMedia(rideID: String, mediaID: String) async throws -> RideMedia
}

extension RideUploadServicing {
    func spine(rideID: String) async throws -> RideSpineData? { nil }
}

protocol RideFileTransferring: Sendable {
    func isActive(jobID: String) async -> Bool
    func upload(jobID: String, signedURL: String, sourceURL: URL, fileName: String) async throws
    func persistedBodyJobIDs() async throws -> Set<String>
    func cancel(jobIDs: Set<String>) async throws
}

protocol RideUploadAuthorizing: Sendable {
    func activeOwner(matching ownerID: String) async -> RecordingOwner?
    func permits(owner: RecordingOwner) async -> Bool
}

protocol RideRevealBuilding: Sendable {
    func build(
        job: RideUploadJob,
        status: RideStatus,
        detail: RideDetailResponse,
        patterns: PatternsResponse
    ) throws -> RevealData
}

actor RideUploadAuthorization: RideUploadAuthorizing {
    private var owner: RecordingOwner?
    private let durableAccountWorkPermitted: @Sendable (RecordingOwner) -> Bool

    init(
        durableAccountWorkPermitted: @escaping @Sendable (RecordingOwner) -> Bool = {
            AccountDeletionLocalFence.permitsAccountWork(owner: $0)
        }
    ) {
        self.durableAccountWorkPermitted = durableAccountWorkPermitted
    }

    func activate(owner: RecordingOwner?) {
        guard let owner else {
            self.owner = nil
            return
        }
        self.owner = durableAccountWorkPermitted(owner) ? owner : nil
    }

    func activeOwner(matching ownerID: String) -> RecordingOwner? {
        guard owner?.id == ownerID else { return nil }
        return owner
    }

    func permits(owner expectedOwner: RecordingOwner) -> Bool {
        owner == expectedOwner && durableAccountWorkPermitted(expectedOwner)
    }
}

/// Injectable lifecycle owner used by ImportFlow, next-open reconciliation,
/// the feed's retry path, and the background-task entry point.
actor RideUploadCoordinator {
    private struct JobKey: Hashable {
        let ownerID: String
        let ownerWallet: String
        let jobID: String
    }

    private let store: any RideUploadJobStoring
    private let service: any RideUploadServicing
    private let transfer: any RideFileTransferring
    private let authorization: any RideUploadAuthorizing
    private let revealBuilder: any RideRevealBuilding
    private let now: @Sendable () -> Date
    private let makeID: @Sendable () -> String
    private var activeJobs: Set<JobKey> = []

    init(
        store: any RideUploadJobStoring,
        service: any RideUploadServicing,
        transfer: any RideFileTransferring,
        authorization: any RideUploadAuthorizing,
        revealBuilder: any RideRevealBuilding,
        now: @escaping @Sendable () -> Date = { .now },
        makeID: @escaping @Sendable () -> String = { UUID().uuidString.lowercased() }
    ) {
        self.store = store
        self.service = service
        self.transfer = transfer
        self.authorization = authorization
        self.revealBuilder = revealBuilder
        self.now = now
        self.makeID = makeID
    }

    func enqueue(
        ownerID: String,
        ownerWallet: String,
        fileName: String,
        fileType: String,
        sourceBytes: Data,
        summary: LocalRideSummary,
        jobID: String? = nil,
        parserVersion: UInt32? = nil,
        preliminaryRideHash: String? = nil,
        requiresPublicationReview: Bool = false
    ) async throws -> RideUploadJob {
        let owner = RecordingOwner(id: ownerID, wallet: ownerWallet)
        guard await authorization.permits(owner: owner) else {
            throw RideUploadStoreError.invalidOwner
        }
        try Self.validateAttestationStamp(
            parserVersion: parserVersion,
            preliminaryRideHash: preliminaryRideHash
        )
        let id = jobID ?? makeID()
        let sourceHash = FileRideUploadJobStore.sha256(sourceBytes)
        if var existing = try await store.job(id: id, ownerID: ownerID) {
            guard existing.ownerWallet == ownerWallet,
                  existing.fileName == fileName,
                  existing.fileType == fileType.lowercased(),
                  existing.fileHash == sourceHash,
                  existing.fileSize == sourceBytes.count,
                  existing.localSummary == summary,
                  existing.parserVersion == parserVersion,
                  existing.preliminaryRideHash == preliminaryRideHash
            else { throw RideUploadStoreError.immutableMetadataChanged }
            _ = try await store.sourceURL(for: existing)
            if requiresPublicationReview,
               existing.publication == nil,
               !existing.attemptedServerHandoff,
               existing.serverRideID == nil,
               existing.phase != .final
            {
                guard await authorization.permits(owner: owner) else {
                    throw RideUploadStoreError.invalidOwner
                }
                existing.phase = .awaitingPrivacyReview
                existing.lastError = nil
                existing.canRetry = false
                existing.updatedAt = now()
                try await store.save(existing)
            }
            guard await authorization.permits(owner: owner) else {
                throw RideUploadStoreError.invalidOwner
            }
            return existing
        }
        let timestamp = now()
        let safeExtension = fileType.lowercased()
        let job = RideUploadJob(
            id: id,
            ownerID: ownerID,
            ownerWallet: ownerWallet,
            fileName: fileName,
            fileType: safeExtension,
            fileHash: sourceHash,
            fileSize: sourceBytes.count,
            sourceFileName: "source.\(safeExtension)",
            localSummary: summary,
            createdAt: timestamp,
            updatedAt: timestamp,
            phase: requiresPublicationReview ? .awaitingPrivacyReview : .queued,
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
            reveal: nil,
            parserVersion: parserVersion,
            preliminaryRideHash: preliminaryRideHash
        )
        guard await authorization.permits(owner: owner) else {
            throw RideUploadStoreError.invalidOwner
        }
        try await store.create(job, sourceBytes: sourceBytes)
        return job
    }

    /// The one publication boundary. It is exact-owner, pre-handoff and
    /// write-once; after this durable save the normal retry machinery may
    /// contact the server with the frozen decision.
    func approvePublication(
        jobID: String,
        owner: RecordingOwner,
        settings: RidePublicationSettings,
        draft: RidePostRideDraft = .empty,
        photoBytes: [String: Data] = [:]
    ) async throws -> RideUploadJob {
        guard settings.isValid,
              draft.photos.count <= RidePhotoContract.maxPhotos,
              await authorization.permits(owner: owner),
              var job = try await store.job(id: jobID, ownerID: owner.id),
              await authorization.permits(owner: owner),
              job.ownerID == owner.id,
              job.ownerWallet == owner.wallet,
              job.phase == .awaitingPrivacyReview,
              job.publication == nil,
              !job.attemptedServerHandoff,
              job.serverRideID == nil
        else { throw RideUploadStoreError.immutableMetadataChanged }

        job.publication = settings
        job.postRideDraft = draft
        job.phase = .queued
        job.lastError = nil
        job.canRetry = false
        job.updatedAt = now()
        try await store.saveApproval(job, photoBytes: photoBytes)
        return job
    }

    private static func validateAttestationStamp(
        parserVersion: UInt32?,
        preliminaryRideHash: String?
    ) throws {
        switch (parserVersion, preliminaryRideHash) {
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

    func reconcileAll(owner: RecordingOwner) async {
        guard await authorization.permits(owner: owner),
              let jobs = try? await store.jobs(ownerID: owner.id),
              await authorization.permits(owner: owner)
        else { return }
        for job in jobs
        where job.ownerWallet == owner.wallet
            && job.phase != .final
            && job.phase != .awaitingPrivacyReview
            && job.revealState != .consumed {
            await reconcile(jobID: job.id, owner: owner)
        }
    }

    func reconcile(jobID: String, ownerID: String) async {
        guard let owner = await authorization.activeOwner(matching: ownerID),
              await authorization.permits(owner: owner)
        else { return }
        await reconcile(jobID: jobID, owner: owner)
    }

    private func reconcile(jobID: String, owner: RecordingOwner) async {
        let key = JobKey(
            ownerID: owner.id,
            ownerWallet: owner.wallet,
            jobID: jobID
        )
        guard activeJobs.insert(key).inserted else { return }
        defer { activeJobs.remove(key) }

        guard await authorization.permits(owner: owner),
              var job = try? await store.job(id: jobID, ownerID: owner.id),
              await authorization.permits(owner: owner),
              job.ownerID == owner.id,
              job.ownerWallet == owner.wallet
        else { return }
        guard job.phase != .final,
              job.phase != .awaitingPrivacyReview,
              job.revealState != .consumed
        else { return }

        // An older app could leave a durable local job without the four-field
        // publication snapshot. Only a provably pre-handoff row is migrated;
        // ambiguous or server-bound rows keep reconciling their existing ID.
        if job.publication == nil,
           !job.attemptedServerHandoff,
           job.serverRideID == nil
        {
            job.phase = .awaitingPrivacyReview
            job.lastError = nil
            job.canRetry = false
            job.updatedAt = now()
            try? await store.save(job)
            return
        }

        // Operator kill switch (L3.05): an explicit fresh disable pauses
        // server handoff — the durable job and local custody stay intact
        // and reconciliation resumes when the capability returns. Unknown
        // (outage, cold start) is not a kill signal.
        guard MobileCapabilityStore.shared.current()
            .allowsUnlessDisabled(.rideUpload)
        else {
            BRLog.upload.log("handoff paused: ride_upload capability disabled")
            if job.phase != .retryable || !job.canRetry {
                job.phase = .retryable
                job.canRetry = true
                job.updatedAt = now()
                try? await store.save(job)
            }
            return
        }

        do {
            if let rideID = job.serverRideID {
                try await reconcileStatus(&job, rideID: rideID, owner: owner)
                return
            }

            // Once any server handoff may have happened, first reconcile the
            // stable UUID. This covers process death or an ambiguous complete
            // response without minting a second logical upload.
            if job.attemptedServerHandoff {
                do {
                    let service = service
                    let completion = try await authorizedHandoff(owner: owner) {
                        try await service.complete(uploadID: job.id)
                    }
                    try validateServerID(completion.rideId, for: job)
                    job.serverRideID = completion.rideId
                    job.phase = .processing
                    job.lastError = nil
                    job.canRetry = false
                    job.updatedAt = now()
                    try await store.save(job)
                    try await reconcileStatus(
                        &job,
                        rideID: completion.rideId,
                        owner: owner
                    )
                    return
                } catch {
                    if isAuthenticationError(error) { throw error }
                    if isMissingUploadRecord(error), job.publication == nil {
                        // A 404 proves the ambiguous old handoff never created
                        // an owned server row. Return it to the rider-owned
                        // review boundary before any fresh init.
                        job.phase = .awaitingPrivacyReview
                        job.attemptedServerHandoff = false
                        job.signedURL = nil
                        job.signedURLExpiresAt = nil
                        job.lastError = nil
                        job.canRetry = false
                        job.updatedAt = now()
                        try await store.save(job)
                        return
                    }
                    if isExistingUploadMissingFile(error), job.publication == nil {
                        // This older client already created the stable server
                        // row, whose privacy decision is immutable there. Ask
                        // only for a replacement signed URL; do not attach a
                        // new privacy choice to that historical request.
                        try await initializeAndTransfer(
                            &job,
                            owner: owner,
                            resumesLegacyServerRow: true
                        )
                        return
                    }
                    if !isMissingUpload(error) {
                        // The row may exist while the response or status read
                        // is unavailable. Keep the same durable job nonfinal.
                        job.phase = .retryable
                        job.lastError = error.localizedDescription
                        job.canRetry = true
                        job.updatedAt = now()
                        try await store.save(job)
                        return
                    }
                }
            }

            try await initializeAndTransfer(&job, owner: owner)
        } catch {
            if let existingRideID = reconcilableExistingRideID(error, for: job) {
                job.serverRideID = existingRideID
                job.phase = .processing
                job.lastError = nil
                job.canRetry = false
                job.updatedAt = now()
                try? await store.save(job)
                do {
                    try await reconcileStatus(
                        &job,
                        rideID: existingRideID,
                        owner: owner
                    )
                } catch {
                    if isAuthenticationError(error) {
                        job.phase = .waitingForAuthentication
                        job.lastError = error.localizedDescription
                        job.canRetry = false
                        job.updatedAt = now()
                        try? await store.save(job)
                    }
                }
                return
            } else if isAuthenticationError(error) {
                job.phase = .waitingForAuthentication
                job.canRetry = false
            } else if job.serverRideID != nil {
                job.phase = .processing
                job.canRetry = true
            } else {
                job.phase = .retryable
                job.canRetry = true
            }
            job.lastError = error.localizedDescription
            job.updatedAt = now()
            try? await store.save(job)
        }
    }

    func retry(jobID: String, owner: RecordingOwner) async {
        guard await authorization.permits(owner: owner),
              var job = try? await store.job(id: jobID, ownerID: owner.id),
              await authorization.permits(owner: owner),
              job.ownerID == owner.id,
              job.ownerWallet == owner.wallet
        else { return }
        if job.phase == .failed, job.canRetry, let rideID = job.serverRideID {
            do {
                let service = service
                try await authorizedHandoff(owner: owner) {
                    try await service.reprocess(rideID: rideID)
                }
                job.phase = .processing
                job.lastError = nil
                job.canRetry = false
                job.updatedAt = now()
                try await store.save(job)
            } catch {
                if isAuthenticationError(error) {
                    job.phase = .waitingForAuthentication
                    job.canRetry = false
                }
                job.lastError = error.localizedDescription
                job.updatedAt = now()
                try? await store.save(job)
                return
            }
        }
        await reconcile(jobID: jobID, owner: owner)
    }

    func claimNextReveal(owner: RecordingOwner) async -> PendingRideReveal? {
        guard await authorization.permits(owner: owner) else { return nil }
        guard let pending = try? await store.claimNextReveal(owner: owner),
              await authorization.permits(owner: owner)
        else { return nil }
        return pending
    }

    func acknowledgeReveal(
        _ pending: PendingRideReveal,
        owner: RecordingOwner
    ) async -> Bool {
        guard pending.ownerID == owner.id,
              await authorization.permits(owner: owner)
        else { return false }
        do {
            try await store.acknowledgeReveal(
                id: pending.id,
                owner: owner,
                claimID: pending.claimID,
                authoritativeRideID: pending.authoritativeRideID
            )
            return await authorization.permits(owner: owner)
        } catch {
            return false
        }
    }

    private func initializeAndTransfer(
        _ job: inout RideUploadJob,
        owner: RecordingOwner,
        resumesLegacyServerRow: Bool = false
    ) async throws {
        if resumesLegacyServerRow {
            guard job.publication == nil,
                  job.attemptedServerHandoff,
                  job.serverRideID == nil
            else { throw RideUploadCoordinatorError.missingPublicationDecision }
        } else {
            guard job.publication?.isValid == true else {
                throw RideUploadCoordinatorError.missingPublicationDecision
            }
        }
        job.phase = .initializing
        job.attemptedServerHandoff = true
        job.attemptCount += 1
        job.lastError = nil
        job.canRetry = false
        job.updatedAt = now()
        try await store.save(job)

        let service = service
        let started = try await authorizedHandoff(owner: owner) {
            if resumesLegacyServerRow {
                return try await service.resumeLegacyUpload(
                    job: job,
                    clientRequestID: job.id
                )
            }
            return try await service.initialize(job: job, clientRequestID: job.id)
        }
        try validateServerID(started.uploadId, for: job)
        try await publishPostRideDraft(job, rideID: started.uploadId, owner: owner)
        job.signedURL = started.signedUrl
        job.signedURLExpiresAt = started.expiresIn.map {
            now().addingTimeInterval(TimeInterval($0))
        }
        job.phase = .transferring
        job.updatedAt = now()
        try await store.save(job)

        let transfer = transfer
        let transferIsActive = try await authorizedHandoff(owner: owner) {
            await transfer.isActive(jobID: job.id)
        }
        if transferIsActive { return }
        let source = try await store.sourceURL(for: job)
        try await authorizedHandoff(owner: owner) {
            try await transfer.upload(
                jobID: job.id,
                signedURL: started.signedUrl,
                sourceURL: source,
                fileName: job.fileName
            )
        }

        job.phase = .completing
        job.updatedAt = now()
        try await store.save(job)
        let completion = try await authorizedHandoff(owner: owner) {
            try await service.complete(uploadID: job.id)
        }
        try validateServerID(completion.rideId, for: job)
        job.serverRideID = completion.rideId
        job.phase = .processing
        job.signedURL = nil
        job.signedURLExpiresAt = nil
        job.lastError = nil
        job.updatedAt = now()
        try await store.save(job)
        try await reconcileStatus(&job, rideID: completion.rideId, owner: owner)
    }

    /// Metadata is an idempotent PATCH. Each local photo owns a stable UUID;
    /// complete is attempted before init so a process death after storage PUT
    /// can finalize the existing object, while ready IDs are never uploaded
    /// twice. Only a proven absent row/file proceeds to stable init + PUT.
    private func publishPostRideDraft(
        _ job: RideUploadJob,
        rideID: String,
        owner: RecordingOwner
    ) async throws {
        guard let draft = job.postRideDraft else { return }
        let service = service
        try await authorizedHandoff(owner: owner) {
            try await service.updatePostRideDraft(rideID: rideID, draft: draft)
        }
        let existing = try await authorizedHandoff(owner: owner) {
            try await service.media(rideID: rideID)
        }
        var readyIDs = Set(existing.map(\.id))

        for photo in draft.photos where !readyIDs.contains(photo.id) {
            do {
                let completed = try await authorizedHandoff(owner: owner) {
                    try await service.completeMedia(rideID: rideID, mediaID: photo.id)
                }
                guard completed.id == photo.id, completed.rideId == rideID else {
                    throw RideUploadCoordinatorError.mismatchedServerIdentifier
                }
                readyIDs.insert(photo.id)
                continue
            } catch {
                if isAuthenticationError(error) { throw error }
                guard isMissingMediaUpload(error) else { throw error }
            }

            let handle = try await authorizedHandoff(owner: owner) {
                try await service.initializeMedia(rideID: rideID, photo: photo)
            }
            guard handle.mediaId == photo.id else {
                throw RideUploadCoordinatorError.mismatchedServerIdentifier
            }
            let sourceURL = try await store.photoURL(for: photo, job: job)
            try await authorizedHandoff(owner: owner) {
                try await service.uploadMedia(
                    signedURL: handle.signedUrl,
                    sourceURL: sourceURL,
                    fileName: photo.fileName
                )
            }
            let completed = try await authorizedHandoff(owner: owner) {
                try await service.completeMedia(rideID: rideID, mediaID: photo.id)
            }
            guard completed.id == photo.id, completed.rideId == rideID else {
                throw RideUploadCoordinatorError.mismatchedServerIdentifier
            }
            readyIDs.insert(photo.id)
        }
    }

    private func reconcileStatus(
        _ job: inout RideUploadJob,
        rideID: String,
        owner: RecordingOwner
    ) async throws {
        do {
            let service = service
            let status = try await authorizedHandoff(owner: owner) {
                try await service.status(rideID: rideID)
            }
            job.authoritativeStatus = status.status
            job.lastError = nil
            job.canRetry = false

            switch status.status {
            case "pending":
                // Backend pending is the durable pre-enqueue state. Replaying
                // complete with the same owned ride ID retries a queue outage
                // or post-verification process interruption without another
                // logical upload or storage transfer.
                let replay = try await authorizedHandoff(owner: owner) {
                    try await service.complete(uploadID: rideID)
                }
                guard replay.rideId.caseInsensitiveCompare(rideID) == .orderedSame else {
                    throw RideUploadCoordinatorError.mismatchedServerIdentifier
                }
                job.authoritativeStatus = replay.status
                job.phase = .processing
                job.canRetry = replay.status == "pending"
            case "completed":
                do {
                    let detail = try await authorizedHandoff(owner: owner) {
                        try await service.detail(rideID: rideID)
                    }
                    let patterns = try await authorizedHandoff(owner: owner) {
                        try await service.patterns(rideID: rideID)
                    }
                    var reveal = try revealBuilder.build(
                        job: job,
                        status: status,
                        detail: detail,
                        patterns: patterns
                    )
                    // Optional geometry never gates finality or creates a
                    // replacement shape. It is read under the same owner fence.
                    do {
                        reveal.spine = try await authorizedHandoff(owner: owner) {
                            try await service.spine(rideID: rideID)
                        }
                    } catch {
                        if isAuthenticationError(error) { throw error }
                    }
                    job.reveal = reveal
                    job.revealState = .queued
                    job.phase = .final
                } catch {
                    if isAuthenticationError(error) { throw error }
                    // A completed status is not enough: required owned detail
                    // and patterns rereads must agree before final ceremony.
                    job.phase = .processing
                    job.canRetry = true
                }
            case "under_review":
                job.phase = .underReview
                job.lastError = "This ride is under review."
            case "failed":
                job.phase = .failed
                job.lastError = status.errorMessage ?? "Processing failed"
                job.canRetry = status.canRetryProcessing
                    ?? status.failure?.retryable
                    ?? false
            default:
                job.phase = .processing
            }
            job.updatedAt = now()
            try await store.save(job)
        } catch {
            if isAuthenticationError(error) { throw error }
            job.phase = .processing
            job.lastError = nil
            job.canRetry = true
            job.updatedAt = now()
            try await store.save(job)
        }
    }

    /// The current authenticated wallet is part of upload custody. Recheck it
    /// after every external suspension, including failures, before consuming
    /// a response or advancing the persisted job.
    private func authorizedHandoff<T>(
        owner: RecordingOwner,
        operation: () async throws -> T
    ) async throws -> T {
        guard await authorization.permits(owner: owner) else {
            throw APIError.notAuthenticated
        }
        do {
            let result = try await operation()
            guard await authorization.permits(owner: owner) else {
                throw APIError.notAuthenticated
            }
            return result
        } catch {
            guard await authorization.permits(owner: owner) else {
                throw APIError.notAuthenticated
            }
            throw error
        }
    }

    private func validateServerID(_ serverID: String, for job: RideUploadJob) throws {
        guard serverID.caseInsensitiveCompare(job.id) == .orderedSame else {
            throw RideUploadCoordinatorError.mismatchedServerIdentifier
        }
    }

    private func isAuthenticationError(_ error: Error) -> Bool {
        if case APIError.notAuthenticated = error { return true }
        return false
    }

    private func reconcilableExistingRideID(
        _ error: Error,
        for job: RideUploadJob
    ) -> String? {
        guard case let APIError.uploadConflict(
            _, code, _, existingRideID, existingStatus
        ) = error else { return nil }
        if code == "upload_already_initialized",
           existingRideID.caseInsensitiveCompare(job.id) == .orderedSame {
            return existingRideID
        }
        // The backend's same-owner, same-file duplicate contract lets a
        // persisted local job bind to the already durable ride. Changed
        // immutable inputs and unknown conflicts remain closed.
        if code == "duplicate_file", existingStatus != "uploading" {
            return existingRideID
        }
        return nil
    }

    private func isMissingUpload(_ error: Error) -> Bool {
        guard case let APIError.http(status, code, _) = error else { return false }
        return status == 404 || (status == 400 && code == "file_missing")
    }

    private func isMissingUploadRecord(_ error: Error) -> Bool {
        guard case let APIError.http(status, _, _) = error else { return false }
        return status == 404
    }

    private func isExistingUploadMissingFile(_ error: Error) -> Bool {
        guard case let APIError.http(status, code, _) = error else { return false }
        return status == 400 && code == "file_missing"
    }

    private func isMissingMediaUpload(_ error: Error) -> Bool {
        guard case let APIError.http(status, _, _) = error else { return false }
        return status == 404 || status == 400
    }
}

private enum RideUploadCoordinatorError: LocalizedError {
    case mismatchedServerIdentifier
    case missingPublicationDecision

    var errorDescription: String? {
        switch self {
        case .mismatchedServerIdentifier:
            return "Ride upload could not be reconciled"
        case .missingPublicationDecision:
            return "Ride privacy must be reviewed"
        }
    }
}

struct RideFeedItem: Identifiable {
    enum Source {
        case local(RideUploadJob)
        case server(Ride)
        case activity(FeedActivity)
    }

    let id: String
    let source: Source
}

enum RideFeedAssembler {
    static func merge(localJobs: [RideUploadJob], serverRides: [Ride]?) -> [RideFeedItem] {
        let remote = serverRides ?? []
        let remoteIDs = Set(remote.map(\.id))
        let local = localJobs
            .filter { job in
                guard let serverRideID = job.serverRideID else { return true }
                return !remoteIDs.contains(serverRideID)
            }
            .map { RideFeedItem(id: $0.id, source: .local($0)) }
        let server = remote.map { RideFeedItem(id: $0.id, source: .server($0)) }
        return stableNewestFirst(local + server)
    }

    static func merge(
        localJobs: [RideUploadJob],
        feedActivities: [FeedActivity]
    ) -> [RideFeedItem] {
        let remoteRideIDs = Set(feedActivities.compactMap(\.rideID))
        let local = localJobs
            .filter { job in
                guard let serverRideID = job.serverRideID else { return true }
                return !remoteRideIDs.contains(serverRideID)
            }
            .map { RideFeedItem(id: $0.id, source: .local($0)) }
        let remote = feedActivities.map {
            RideFeedItem(id: $0.deduplicationKey, source: .activity($0))
        }
        return stableNewestFirst(local + remote)
    }

    private static func stableNewestFirst(_ items: [RideFeedItem]) -> [RideFeedItem] {
        items.enumerated().sorted { lhs, rhs in
            let left = startedAt(lhs.element)
            let right = startedAt(rhs.element)
            return left == right ? lhs.offset < rhs.offset : left > right
        }.map(\.element)
    }

    private static func startedAt(_ item: RideFeedItem) -> Date {
        switch item.source {
        case let .local(job):
            return job.localSummary.startedAt
        case let .server(ride):
            return ISO8601DateFormatter().date(from: ride.startedAt) ?? .distantPast
        case let .activity(activity):
            return activity.occurredDate
        }
    }
}
