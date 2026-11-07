import XCTest
@testable import BoulderRoller

final class AccountDeletionLifecycleTests: XCTestCase {
    func testRatifiedExplainerShipsInDestructiveConfirmationDialog() throws {
        let testsDirectory = URL(fileURLWithPath: #filePath).deletingLastPathComponent()
        let viewURL = testsDirectory
            .deletingLastPathComponent()
            .appendingPathComponent("BoulderRoller/Surfaces/Avatar/AccountDeletionRoomView.swift")
        let source = try String(contentsOf: viewURL, encoding: .utf8)
        let expected = "Text(\"Your identity and personal data will be removed. Your climb times, leaderboard history, and settled economics will remain linked to an anonymous account.\")"

        XCTAssertTrue(
            source.contains(expected),
            "the ratified deletion contract must be visible in the system confirmation dialog"
        )
        XCTAssertEqual(
            AccountDeletionConsentCopy.unuploadedRideRemoval,
            "These rides were never uploaded. Deleting your account permanently destroys the only copies.",
            "the Tim-delegated N14 warning must remain exact"
        )
    }

    func testRatifiedN14CopyStillRequiresExplicitInventoryReview() {
        let oneRide = AccountDeletionLocalInventory.fixture(rideIDs: ["ride-1"])

        XCTAssertTrue(
            AccountDeletionConsentCopy.hasRequiredRemovalCopy(for: oneRide),
            "the ratified N14 warning opens the copy gate for an unuploaded ride"
        )
        XCTAssertTrue(
            AccountDeletionConsentCopy.acknowledgesRemoval(of: oneRide, reviewed: true),
            "the exact warning plus explicit current-inventory review acknowledges removal"
        )
        XCTAssertFalse(
            AccountDeletionConsentCopy.acknowledgesRemoval(of: oneRide, reviewed: false),
            "shipping the warning cannot substitute for the rider reviewing the inventory"
        )
        XCTAssertTrue(AccountDeletionConsentCopy.hasRequiredRemovalCopy(for: .empty))
        XCTAssertTrue(
            AccountDeletionConsentCopy.acknowledgesRemoval(of: .empty, reviewed: true)
        )
    }

    func testWorkerOwnedFailurePresentsRecoveryWithoutRetryOrSupport() {
        let workerRecovery = AccountDeletionStatus.fixture(
            status: .failedRetryable,
            retryable: false
        )

        XCTAssertEqual(
            AccountDeletionPresentation.statusLabel(workerRecovery),
            "Recovering"
        )
        XCTAssertTrue(AccountDeletionPresentation.pollsAutomatically(workerRecovery))
        XCTAssertTrue(AccountDeletionPresentation.showsProgress(workerRecovery))
        XCTAssertFalse(AccountDeletionPresentation.offersSupport(workerRecovery))

        let riderRetry = AccountDeletionStatus.fixture(
            status: .failedRetryable,
            retryable: true
        )
        XCTAssertEqual(AccountDeletionPresentation.statusLabel(riderRetry), "Try Again")
        XCTAssertFalse(AccountDeletionPresentation.pollsAutomatically(riderRetry))
        XCTAssertFalse(AccountDeletionPresentation.offersSupport(riderRetry))
    }

    func testServerBlockersExposeEveryFunctionalRemedyAndPinnedDestination() {
        let blockers = [
            AccountDeletionBlocker(
                code: "claim_remains",
                category: "claim",
                asset: "DUNG",
                amountBaseUnits: nil,
                count: 1,
                source: "settlements",
                action: "contact_support"
            ),
            AccountDeletionBlocker(
                code: "balance_remains",
                category: "balance",
                asset: "CAL",
                amountBaseUnits: "1",
                count: nil,
                source: "balance",
                action: "open_balance"
            ),
            AccountDeletionBlocker(
                code: "preflight_unavailable",
                category: "authority",
                asset: nil,
                amountBaseUnits: nil,
                count: nil,
                source: "server",
                action: "retry"
            ),
        ]

        XCTAssertEqual(
            AccountDeletionPresentation.remedies(for: blockers),
            [.reviewSettlements, .openBalance, .retry, .contactSupport]
        )
        XCTAssertEqual(
            AppConfig.portalBalanceURL.absoluteString,
            "https://app.boulderroller.xyz/portfolio"
        )
        XCTAssertEqual(
            AppConfig.supportURL.absoluteString,
            "https://docs.boulderroller.xyz/support/contact"
        )
    }

    func testFailureAndUnknownBlockerLabelsStayFactual() {
        let unknown = AccountDeletionBlocker(
            code: "future_server_requirement",
            category: "future",
            asset: nil,
            amountBaseUnits: nil,
            count: nil,
            source: nil,
            action: nil
        )

        XCTAssertEqual(
            AccountDeletionPresentation.blockerLabel(unknown),
            "Account Requirement"
        )
        XCTAssertEqual(
            AccountDeletionPresentation.failureLabel("queue_unavailable"),
            "Request Queue Unavailable"
        )
        XCTAssertEqual(
            AccountDeletionPresentation.failureLabel("future_failure"),
            "Previous Attempt Could Not Finish"
        )
    }

    func testDeletionHeadersCannotDismissWorkingOrUncleanedLifecycles() {
        XCTAssertFalse(AccountDeletionHeaderPolicy.settingsDoneEnabled(isWorking: true))
        XCTAssertTrue(AccountDeletionHeaderPolicy.settingsDoneEnabled(isWorking: false))

        let pending = AccountDeletionSessionRecord(
            recoveryID: "pending-recovery",
            state: .deleted,
            owner: RecordingOwner.fixture
        )
        let cleaned = AccountDeletionSessionRecord(
            recoveryID: pending.recoveryID,
            state: .deleted,
            owner: nil,
            localCleanupCompletedAt: Date(timeIntervalSince1970: 1_777_000_100)
        )
        XCTAssertFalse(AccountDeletionHeaderPolicy.recoveryDoneEnabled(record: pending))
        XCTAssertTrue(AccountDeletionHeaderPolicy.recoveryDoneEnabled(record: cleaned))
    }

    func testKeychainReadFailureNeverMeansNoDeletionWhenMarkerIsAbsent() {
        let state = KeychainAccountDeletionCapabilityStore.loadState(marked: false) {
            throw TestError.unavailable
        }

        XCTAssertEqual(state, .unavailable)
    }

    func testCapabilitySaveNeverSetsMarkerBeforeDurableKeychainReadback() {
        var events: [String] = []

        XCTAssertThrowsError(
            try KeychainAccountDeletionCapabilityStore.saveCrashConsistently(
                saveCapability: {
                    events.append("keychain-write")
                    throw TestError.unavailable
                },
                capabilityMatches: {
                    events.append("keychain-readback")
                    return false
                },
                setMarker: { events.append("marker-write") },
                markerIsPresent: {
                    events.append("marker-readback")
                    return true
                },
                synchronizeMarker: {
                    events.append("marker-sync")
                    return true
                }
            )
        )

        XCTAssertEqual(
            events,
            ["keychain-write"],
            "a failed pre-DELETE capability write cannot leave a terminal marker-only state"
        )
    }

    func testForegroundRetriesUnavailableDeletionStorageBeforeRootRouting() {
        XCTAssertTrue(
            AccountDeletionForegroundRecovery.shouldReload(storage: .unavailable)
        )
        XCTAssertFalse(
            AccountDeletionForegroundRecovery.shouldReload(storage: .none)
        )
    }

    func testCompletionAcknowledgementRemovesMarkerBeforeFallibleKeychainDelete() throws {
        var markerPresent = true
        let capabilityData = try JSONEncoder().encode(
            AccountDeletionCapability.fixture(owner: .fixture)
        )
        let encodedCapability = String(data: capabilityData, encoding: .utf8)

        XCTAssertThrowsError(
            try KeychainAccountDeletionCapabilityStore.deleteCrashConsistently(
                removeMarker: { markerPresent = false },
                markerIsAbsent: { !markerPresent },
                synchronizeMarker: { true },
                deleteCapability: { throw TestError.unavailable },
                readCapability: { encodedCapability }
            )
        )
        XCTAssertFalse(markerPresent)
        XCTAssertNotNil(encodedCapability)
        let recovery = KeychainAccountDeletionCapabilityStore.loadState(
            marked: markerPresent,
            readValue: { encodedCapability }
        )
        guard case .unconfirmed = recovery else {
            XCTFail("a legacy raw capability must remain readable as scoped recovery")
            return
        }
    }

    func testRequestGateBlocksServerDeleteUntilPreflightAndLocalCustodyAreAcknowledged() {
        let ready = AccountDeletionPreflight(
            contractVersion: AccountDeletionContract.version,
            allowed: true,
            available: true,
            blockers: [],
            checkedAt: "2026-08-24T12:00:00Z"
        )
        let blocked = AccountDeletionPreflight(
            contractVersion: AccountDeletionContract.version,
            allowed: false,
            available: true,
            blockers: [.fixture(code: "balance_remains", category: "balance")],
            checkedAt: "2026-08-24T12:00:00Z"
        )
        let oneRide = AccountDeletionLocalInventory.fixture(rideIDs: ["ride-1"])

        XCTAssertFalse(AccountDeletionRequestGate.allows(
            preflight: blocked,
            inventory: .available(.empty),
            reviewedInventoryDigest: nil
        ))
        XCTAssertFalse(AccountDeletionRequestGate.allows(
            preflight: ready,
            inventory: .unavailable,
            reviewedInventoryDigest: nil
        ))
        XCTAssertFalse(AccountDeletionRequestGate.allows(
            preflight: ready,
            inventory: .available(oneRide),
            reviewedInventoryDigest: nil
        ))
        XCTAssertFalse(AccountDeletionRequestGate.allows(
            preflight: ready,
            inventory: .available(.empty),
            reviewedInventoryDigest: nil
        ))
        XCTAssertTrue(AccountDeletionRequestGate.allows(
            preflight: ready,
            inventory: .available(.empty),
            reviewedInventoryDigest: AccountDeletionLocalInventory.empty.digest
        ))
        XCTAssertTrue(AccountDeletionRequestGate.allows(
            preflight: ready,
            inventory: .available(oneRide),
            reviewedInventoryDigest: oneRide.digest
        ))
    }

    @MainActor
    func testCapabilityPersistenceFailurePreventsDeleteRequest() async {
        let service = AccountDeletionServiceSpy()
        let store = AccountDeletionCapabilityStoreSpy(saveError: TestError.unavailable)
        let inventory = AccountDeletionLocalInventory.fixture(rideIDs: [])
        let model = AccountDeletionRoomModel(
            service: service,
            capabilityStore: store,
            inventory: { inventory },
            localCleanup: { _, _ in XCTFail("cleanup cannot run during initiation") }
        )

        await model.load(owner: .fixture)
        await model.requestDeletion(
            owner: .fixture,
            reviewedInventoryDigest: inventory.digest,
            unuploadedRidesAcknowledged: true
        )

        let createCallCount = await service.createCallCount
        XCTAssertEqual(createCallCount, 0)
        XCTAssertEqual(model.state, .storageUnavailable)
    }

    @MainActor
    func testCapabilityBecomingUnreadablePreventsAReplacementDeleteRequest() async {
        let service = AccountDeletionServiceSpy()
        let store = AccountDeletionCapabilityStoreSpy()
        let inventory = AccountDeletionLocalInventory.fixture(rideIDs: [])
        let model = AccountDeletionRoomModel(
            service: service,
            capabilityStore: store,
            inventory: { inventory },
            localCleanup: { _, _ in XCTFail("cleanup cannot run during initiation") }
        )

        await model.load(owner: .fixture)
        store.isUnavailable = true
        await model.requestDeletion(
            owner: .fixture,
            reviewedInventoryDigest: inventory.digest,
            unuploadedRidesAcknowledged: true
        )

        let createCallCount = await service.createCallCount
        XCTAssertEqual(createCallCount, 0)
        XCTAssertEqual(model.state, .storageUnavailable)
        XCTAssertNil(store.savedCapability)
    }

    @MainActor
    func testFailedDeleteKeepsRecoveryScopedWithoutActivatingAcceptedCapability() async throws {
        let service = AccountDeletionServiceSpy(
            createError: URLError(.timedOut),
            statusError: APIError.http(status: 404, code: nil, message: nil)
        )
        let store = AccountDeletionCapabilityStoreSpy()
        let inventory = AccountDeletionLocalInventory.fixture(rideIDs: ["ride-1"])
        let model = AccountDeletionRoomModel(
            service: service,
            capabilityStore: store,
            inventory: { inventory },
            localCleanup: { _, _ in XCTFail("cleanup cannot run during initiation") }
        )

        await model.load(owner: .fixture)
        await model.requestDeletion(
            owner: .fixture,
            reviewedInventoryDigest: inventory.digest,
            unuploadedRidesAcknowledged: true
        )
        let firstCreatedCapabilities = await service.createdCapabilities
        XCTAssertEqual(firstCreatedCapabilities.count, 1)
        let first = try XCTUnwrap(firstCreatedCapabilities.first)
        XCTAssertEqual(model.state, .requestNotFound)
        XCTAssertNil(
            store.savedCapability,
            "an unconfirmed network outcome must not activate the app-wide accepted capability"
        )
        XCTAssertEqual(store.unconfirmedCapability, first)

        await model.reissueDeletion()
        let recoveredCapabilities = await service.createdCapabilities
        XCTAssertEqual(recoveredCapabilities, [first, first])
        XCTAssertEqual(store.saveCount, 0, "recovery remains scoped until the server confirms acceptance")
        XCTAssertEqual(store.saveUnconfirmedCount, 1, "the same recovery pair stays durable")
    }

    @MainActor
    func testRelaunchReassertsLocalWriteFenceBeforeReadingDurableStatus() async {
        let capability = AccountDeletionCapability.fixture(owner: .fixture)
        let service = AccountDeletionServiceSpy()
        let store = AccountDeletionCapabilityStoreSpy(capability: capability)
        var fenceCalls = 0
        let model = AccountDeletionRoomModel(
            service: service,
            capabilityStore: store,
            inventory: { .empty },
            localCleanup: { _, _ in XCTFail("queued status cannot clean") },
            capabilityDidChange: { fenceCalls += 1 }
        )

        await model.load(owner: nil)

        XCTAssertEqual(fenceCalls, 1)
        XCTAssertEqual(model.state, .tracking(.fixture(status: .queued)))
    }

    @MainActor
    func testNewRideAfterReviewInvalidatesAcknowledgementAndPreventsDelete() async {
        let service = AccountDeletionServiceSpy()
        let store = AccountDeletionCapabilityStoreSpy()
        let reviewed = AccountDeletionLocalInventory.fixture(rideIDs: ["ride-1"])
        let changed = AccountDeletionLocalInventory.fixture(rideIDs: ["ride-1", "ride-2"])
        var snapshots = [reviewed, changed]
        let model = AccountDeletionRoomModel(
            service: service,
            capabilityStore: store,
            inventory: { snapshots.removeFirst() },
            localCleanup: { _, _ in XCTFail("cleanup cannot run during initiation") }
        )

        await model.load(owner: .fixture)
        await model.requestDeletion(
            owner: .fixture,
            reviewedInventoryDigest: reviewed.digest,
            unuploadedRidesAcknowledged: true
        )

        let createCallCount = await service.createCallCount
        XCTAssertEqual(createCallCount, 0)
        XCTAssertEqual(model.state, .ready(.destructiveBoundaryOpenForTest, changed))
        XCTAssertNil(store.savedCapability)
    }

    @MainActor
    func testRideCreatedDuringFreezeIsCaughtBeforeDeleteCrossesNetwork() async {
        let service = AccountDeletionServiceSpy()
        let store = AccountDeletionCapabilityStoreSpy()
        let reviewed = AccountDeletionLocalInventory.fixture(rideIDs: ["ride-1"])
        let changed = AccountDeletionLocalInventory.fixture(rideIDs: ["ride-1", "ride-2"])
        var snapshots = [reviewed, reviewed, changed]
        let model = AccountDeletionRoomModel(
            service: service,
            capabilityStore: store,
            inventory: { snapshots.removeFirst() },
            localCleanup: { _, _ in XCTFail("cleanup cannot run during initiation") }
        )

        await model.load(owner: .fixture)
        await model.requestDeletion(
            owner: .fixture,
            reviewedInventoryDigest: reviewed.digest,
            unuploadedRidesAcknowledged: true
        )

        let createCallCount = await service.createCallCount
        XCTAssertEqual(createCallCount, 0)
        XCTAssertEqual(model.state, .ready(.destructiveBoundaryOpenForTest, changed))
        XCTAssertNil(store.savedCapability)
        XCTAssertNil(
            store.unconfirmedCapability,
            "no request crossed the network, so the provisional fence is removed"
        )
    }

    @MainActor
    func testChangedBlockedInventoryReReviewUsesRetryInsteadOfDelete() async {
        let oldInventory = AccountDeletionLocalInventory.fixture(rideIDs: ["ride-1"])
        let changed = AccountDeletionLocalInventory.fixture(rideIDs: ["ride-1", "ride-2"])
        let capability = AccountDeletionCapability.fixture(
            owner: .fixture,
            inventory: oldInventory
        )
        let blocked = AccountDeletionStatus.fixture(status: .blocked, retryable: true)
        let service = AccountDeletionServiceSpy(status: blocked)
        let store = AccountDeletionCapabilityStoreSpy(capability: capability)
        let model = AccountDeletionRoomModel(
            service: service,
            capabilityStore: store,
            inventory: { changed },
            localCleanup: { _, _ in XCTFail("cleanup cannot run before completion") }
        )

        await model.load(owner: nil)
        await model.retry()
        XCTAssertEqual(model.state, .retryReview(blocked, changed))

        await model.retry(
            reviewedInventoryDigest: changed.digest,
            unuploadedRidesAcknowledged: false
        )
        var retryCallCount = await service.retryCallCount
        XCTAssertEqual(
            retryCallCount,
            0,
            "a reviewed digest without the destructive recording acknowledgement cannot retry"
        )

        await model.retry(
            reviewedInventoryDigest: changed.digest,
            unuploadedRidesAcknowledged: true
        )

        let createCallCount = await service.createCallCount
        retryCallCount = await service.retryCallCount
        XCTAssertEqual(createCallCount, 0)
        XCTAssertEqual(retryCallCount, 1)
        XCTAssertEqual(store.savedCapability?.inventoryDigest, changed.digest)
    }

    func testStatusUsesBearerHeaderWithoutAuthURLLeakOrResponseCache() async throws {
        AccountDeletionURLProtocol.reset()
        let configuration = URLSessionConfiguration.ephemeral
        configuration.protocolClasses = [AccountDeletionURLProtocol.self]
        let recorder = AccountDeletionRequestRecorder()
        let client = APIClient(
            configuration: configuration,
            sessionCredentials: EmptySessionCredentialStore(),
            requestObserver: { recorder.record($0) }
        )
        let capability = AccountDeletionCapability.fixture(owner: .fixture)

        _ = try await client.status(capability: capability)
        _ = try await client.status(capability: capability)

        let requests = recorder.requests
        XCTAssertEqual(requests.count, 2, "status bypasses GET coalescing and response cache")
        for request in requests {
            XCTAssertEqual(
                request.value(forHTTPHeaderField: "X-Account-Deletion-Token"),
                capability.statusToken
            )
            XCTAssertNil(request.value(forHTTPHeaderField: "Authorization"))
            XCTAssertFalse(request.url?.absoluteString.contains(capability.statusToken) == true)
        }
    }

    func testDeleteAndRetryPinTheFixedBackendWireContract() async throws {
        AccountDeletionURLProtocol.reset()
        let configuration = URLSessionConfiguration.ephemeral
        configuration.protocolClasses = [AccountDeletionURLProtocol.self]
        let recorder = AccountDeletionRequestRecorder()
        let client = APIClient(
            configuration: configuration,
            sessionCredentials: EmptySessionCredentialStore(),
            requestObserver: { recorder.record($0) }
        )
        let capability = AccountDeletionCapability.fixture(owner: .fixture)
        let rider = User(
            id: RecordingOwner.fixture.id,
            wallet: RecordingOwner.fixture.wallet,
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
        CachedRiderStore.save(rider)
        defer { CachedRiderStore.clear() }
        try await client.adoptSession(AuthTokenResponse(
            userId: rider.id,
            wallet: rider.wallet,
            accessToken: "wire-access-token",
            accessExpiresAt: nil,
            refreshToken: "wire-refresh-token",
            refreshExpiresAt: nil
        ))

        _ = try await client.create(capability: capability)
        _ = try await client.retry(capability: capability)

        let requests = recorder.requests
        XCTAssertEqual(requests.count, 2)
        let create = try XCTUnwrap(requests.first)
        XCTAssertEqual(create.httpMethod, "DELETE")
        XCTAssertEqual(create.url?.path, "/compliance/account")
        XCTAssertEqual(
            create.value(forHTTPHeaderField: "Authorization"),
            "Bearer wire-access-token"
        )
        let createBody = try XCTUnwrap(create.httpBody)
        let createJSON = try XCTUnwrap(
            JSONSerialization.jsonObject(with: createBody) as? [String: Any]
        )
        XCTAssertEqual(Set(createJSON.keys), [
            "request_id", "status_token", "unuploaded_rides_acknowledged",
        ])
        XCTAssertEqual(createJSON["request_id"] as? String, capability.requestID)
        XCTAssertEqual(createJSON["status_token"] as? String, capability.statusToken)
        XCTAssertEqual(createJSON["unuploaded_rides_acknowledged"] as? Bool, true)

        let retry = try XCTUnwrap(requests.last)
        XCTAssertEqual(retry.httpMethod, "POST")
        XCTAssertEqual(
            retry.url?.path,
            "/compliance/deletion-status/\(capability.requestID)/retry"
        )
        XCTAssertEqual(
            retry.value(forHTTPHeaderField: "X-Account-Deletion-Token"),
            capability.statusToken
        )
        XCTAssertNil(retry.value(forHTTPHeaderField: "Authorization"))
        let retryBody = try XCTUnwrap(retry.httpBody)
        let retryJSON = try XCTUnwrap(
            JSONSerialization.jsonObject(with: retryBody) as? [String: Any]
        )
        XCTAssertTrue(
            retryJSON.isEmpty,
            "DeletionRetryRequest forbids the legacy acknowledgement field"
        )
    }

    func testFixedBackendNestedConflictCodesRemainMachineReadable() throws {
        for code in [
            "request_already_active",
            "account_unavailable",
            "request_id_conflict",
            "retry_unavailable",
            "retry_requires_support",
        ] {
            let body = try JSONSerialization.data(
                withJSONObject: ["detail": ["code": code]]
            )
            guard case let .http(status, decodedCode, _) = APIClient.httpError(
                status: 409,
                body: body
            ) else {
                return XCTFail("\(code) must decode as a stable HTTP conflict")
            }
            XCTAssertEqual(status, 409)
            XCTAssertEqual(decodedCode, code)
        }
    }

    @MainActor
    func testServerRetryableFalseNeverCrossesTheRetryBoundary() async {
        let capability = AccountDeletionCapability.fixture(owner: .fixture)
        let nonRetryable = AccountDeletionStatus(
            contractVersion: AccountDeletionContract.version,
            requestID: capability.requestID,
            status: .failedRetryable,
            requestedAt: "2026-08-24T12:00:00Z",
            updatedAt: "2026-08-24T12:00:30Z",
            completedAt: nil,
            blockers: [],
            failureCode: "storage_boundary_crossed",
            retryable: false,
            attemptCount: 1
        )
        let service = AccountDeletionServiceSpy(status: nonRetryable)
        let store = AccountDeletionCapabilityStoreSpy(capability: capability)
        let model = AccountDeletionRoomModel(
            service: service,
            capabilityStore: store,
            inventory: { .empty },
            localCleanup: { _, _ in XCTFail("a failed status cannot clean") }
        )

        await model.load(owner: nil)
        await model.retry()

        let retryCallCount = await service.retryCallCount
        XCTAssertEqual(retryCallCount, 0)
    }

    func testRefreshCredentialDeletionFailureCannotVerifyLocalCleanup() async {
        let credentials = FailingDeletionCredentialStore(token: "still-present")
        let client = APIClient(sessionCredentials: credentials)

        do {
            try await client.clearSessionRequired()
            XCTFail("credential deletion failure must remain visible")
        } catch {
            XCTAssertEqual(credentials.token, "still-present")
        }
    }

    func testInFlightGetCannotRepopulateResponseCacheAcrossAccountBoundary() async throws {
        DelayedAccountBoundaryURLProtocol.reset()
        await MainActor.run { ResponseCache.shared.clear() }
        let configuration = URLSessionConfiguration.ephemeral
        configuration.protocolClasses = [DelayedAccountBoundaryURLProtocol.self]
        let client = APIClient(
            configuration: configuration,
            sessionCredentials: EmptySessionCredentialStore()
        )
        let request = Task { try await client.systemStatus() }
        for _ in 0..<100 where DelayedAccountBoundaryURLProtocol.requestCount == 0 {
            try await Task.sleep(for: .milliseconds(5))
        }
        XCTAssertEqual(DelayedAccountBoundaryURLProtocol.requestCount, 1)

        await client.advanceAccountBoundary()
        _ = await request.result
        try await Task.sleep(for: .milliseconds(250))

        let cached: SystemStatusResponse? = await MainActor.run {
            ResponseCache.shared.value(SystemStatusResponse.self, path: "/status")
        }
        XCTAssertNil(cached)
    }

    @MainActor
    func testOnlyAuthoritativeCompletionCanInvokeExactOwnerCleanup() async throws {
        let owner = RecordingOwner.fixture
        let statuses: [AccountDeletionStatusCode] = [
            .queued, .processing, .blocked, .failedRetryable, .needsSupport, .legacyUnverified,
        ]

        for statusCode in statuses {
            let service = AccountDeletionServiceSpy(status: .fixture(status: statusCode))
            let store = AccountDeletionCapabilityStoreSpy(capability: .fixture(owner: owner))
            let cleanup = CleanupSpy()
            let model = AccountDeletionRoomModel(
                service: service,
                capabilityStore: store,
                inventory: { .empty },
                localCleanup: { capability, status in
                    await cleanup.record(capability: capability, status: status)
                }
            )

            await model.load(owner: nil)
            let callCount = await cleanup.callCount
            XCTAssertEqual(callCount, 0, "\(statusCode) must preserve local owner data")
        }

        let completed = AccountDeletionStatus.fixture(status: .completed, completedAt: "2026-08-24T12:01:00Z")
        let service = AccountDeletionServiceSpy(status: completed)
        let store = AccountDeletionCapabilityStoreSpy(capability: .fixture(owner: owner))
        let cleanup = CleanupSpy()
        let model = AccountDeletionRoomModel(
            service: service,
            capabilityStore: store,
            inventory: { .empty },
            localCleanup: { capability, status in
                await cleanup.record(capability: capability, status: status)
            }
        )

        await model.load(owner: nil)
        let completedCallCount = await cleanup.callCount
        let completedOwner = await cleanup.lastOwner
        XCTAssertEqual(completedCallCount, 1)
        XCTAssertEqual(completedOwner, owner)
    }

    @MainActor
    func testContradictoryCompletedResponseCannotInvokeCleanup() async {
        let owner = RecordingOwner.fixture
        let contradictory = AccountDeletionStatus(
            contractVersion: AccountDeletionContract.version,
            requestID: "11111111-1111-4111-8111-111111111111",
            status: .completed,
            requestedAt: "2026-08-24T12:00:00Z",
            updatedAt: "2026-08-24T12:01:00Z",
            completedAt: "2026-08-24T12:01:00Z",
            blockers: [.fixture(code: "claim_remains", category: "claim")],
            failureCode: nil,
            retryable: false,
            attemptCount: 1
        )
        let service = AccountDeletionServiceSpy(status: contradictory)
        let store = AccountDeletionCapabilityStoreSpy(capability: .fixture(owner: owner))
        let cleanup = CleanupSpy()
        let model = AccountDeletionRoomModel(
            service: service,
            capabilityStore: store,
            inventory: { .empty },
            localCleanup: { capability, status in
                await cleanup.record(capability: capability, status: status)
            }
        )

        await model.load(owner: nil)

        let cleanupCount = await cleanup.callCount
        XCTAssertEqual(cleanupCount, 0)
        XCTAssertEqual(model.state, .statusUnavailable)
    }

    @MainActor
    func testMalformedCompletionTimestampCannotInvokeCleanup() async {
        let owner = RecordingOwner.fixture
        let malformed = AccountDeletionStatus.fixture(
            status: .completed,
            completedAt: "not-a-timestamp"
        )
        let service = AccountDeletionServiceSpy(status: malformed)
        let store = AccountDeletionCapabilityStoreSpy(capability: .fixture(owner: owner))
        let cleanup = CleanupSpy()
        let model = AccountDeletionRoomModel(
            service: service,
            capabilityStore: store,
            inventory: { .empty },
            localCleanup: { capability, status in
                await cleanup.record(capability: capability, status: status)
            }
        )

        await model.load(owner: nil)

        let cleanupCallCount = await cleanup.callCount
        XCTAssertEqual(cleanupCallCount, 0)
        XCTAssertEqual(model.state, .statusUnavailable)
    }

    @MainActor
    func testCleanupFailureRetainsOwnerCapabilityForRetry() async {
        let owner = RecordingOwner.fixture
        let completed = AccountDeletionStatus.fixture(
            status: .completed,
            completedAt: "2026-08-24T12:01:00Z"
        )
        let service = AccountDeletionServiceSpy(status: completed)
        let capability = AccountDeletionCapability.fixture(owner: owner)
        let store = AccountDeletionCapabilityStoreSpy(capability: capability)
        let model = AccountDeletionRoomModel(
            service: service,
            capabilityStore: store,
            inventory: { .empty },
            localCleanup: { _, _ in throw TestError.unavailable }
        )

        await model.load(owner: nil)

        XCTAssertEqual(model.state, .localCleanupFailed)
        XCTAssertEqual(store.savedCapability?.verifiedCompletion, completed)
        XCTAssertEqual(store.savedCapability?.owner, capability.owner)
        XCTAssertNil(store.savedCapability?.localCleanupCompletedAt)
    }

    @MainActor
    func testRideDiscoveredAfterServerCompletionRemainsVisibleBeforeAnyCleanup() async {
        let owner = RecordingOwner.fixture
        let completed = AccountDeletionStatus.fixture(
            status: .completed,
            completedAt: "2026-08-24T12:01:00Z"
        )
        let discovered = AccountDeletionLocalInventory.fixture(
            rideIDs: ["late-unuploaded-ride"]
        )
        let store = AccountDeletionCapabilityStoreSpy(
            capability: .fixture(owner: owner)
        )
        var cleanupCount = 0
        let model = AccountDeletionRoomModel(
            service: AccountDeletionServiceSpy(status: completed),
            capabilityStore: store,
            inventory: { discovered },
            localCleanup: { _, _ in cleanupCount += 1 }
        )

        await model.load(owner: owner)

        XCTAssertEqual(model.state, .retryReview(completed, discovered))
        XCTAssertEqual(cleanupCount, 0)
        XCTAssertEqual(store.savedCapability?.acknowledgedRideIDs, [])
        XCTAssertEqual(store.savedCapability?.verifiedCompletion, completed)
        XCTAssertEqual(store.savedCapability?.owner, owner)
        XCTAssertNil(store.savedCapability?.localCleanupCompletedAt)
    }

    @MainActor
    func testPartialCleanupRetryAllowsOnlyRemainingAcknowledgedRideIDs() async {
        let owner = RecordingOwner.fixture
        let acknowledged = AccountDeletionLocalInventory.fixture(rideIDs: ["ride-1", "ride-2"])
        let remaining = AccountDeletionLocalInventory.fixture(rideIDs: ["ride-2"])
        let completed = AccountDeletionStatus.fixture(
            status: .completed,
            completedAt: "2026-08-24T12:01:00Z"
        )
        let service = AccountDeletionServiceSpy(status: completed)
        let capability = AccountDeletionCapability.fixture(
            owner: owner,
            inventory: acknowledged
        )
        let store = AccountDeletionCapabilityStoreSpy(capability: capability)
        let cleanup = CleanupSpy()
        let model = AccountDeletionRoomModel(
            service: service,
            capabilityStore: store,
            inventory: { remaining },
            localCleanup: { capability, status in
                await cleanup.record(capability: capability, status: status)
            }
        )

        await model.load(owner: nil)

        let cleanupCount = await cleanup.callCount
        XCTAssertEqual(cleanupCount, 1)
        XCTAssertEqual(model.state, .completed(completed))
        XCTAssertNil(store.savedCapability?.owner)
        XCTAssertEqual(store.savedCapability?.acknowledgedRideIDs, [])
        XCTAssertEqual(
            store.savedCapability?.inventoryDigest,
            AccountDeletionLocalInventory.empty.digest
        )
    }

    @MainActor
    func testRemainingValueFilesDurableBlockedStatusWithoutCleanup() async {
        let blocker = AccountDeletionBlocker.fixture(
            code: "balance_remains",
            category: "balance"
        )
        let blocked = AccountDeletionPreflight(
            contractVersion: AccountDeletionContract.version,
            allowed: false,
            available: true,
            blockers: [blocker],
            checkedAt: "2026-08-25T12:00:00Z"
        )
        let service = AccountDeletionServiceSpy(
            preflight: blocked,
            status: .fixture(status: .blocked, retryable: true, blockers: [blocker])
        )
        let store = AccountDeletionCapabilityStoreSpy()
        let model = AccountDeletionRoomModel(
            service: service,
            capabilityStore: store,
            inventory: { .empty },
            localCleanup: { _, _ in XCTFail("blocked value cannot clean") }
        )

        await model.load(owner: .fixture)
        await model.requestDeletion(
            owner: .fixture,
            reviewedInventoryDigest: AccountDeletionLocalInventory.empty.digest,
            unuploadedRidesAcknowledged: true
        )

        let createCallCount = await service.createCallCount
        XCTAssertEqual(createCallCount, 1)
        XCTAssertEqual(store.saveUnconfirmedCount, 1)
        XCTAssertEqual(store.saveCount, 1)
        XCTAssertEqual(store.deleteCount, 0)
        guard case let .tracking(status) = model.state else {
            return XCTFail("value must remain a visible durable blocked status")
        }
        XCTAssertEqual(status.status, .blocked)
        XCTAssertEqual(status.blockers, [blocker])
    }

    @MainActor
    func testRemainingClaimFilesDurableBlockedStatusWithoutCleanup() async {
        let blocker = AccountDeletionBlocker.fixture(
            code: "claim_remains",
            category: "claim"
        )
        let blocked = AccountDeletionPreflight(
            contractVersion: AccountDeletionContract.version,
            allowed: false,
            available: true,
            blockers: [blocker],
            checkedAt: "2026-08-25T12:00:00Z"
        )
        let service = AccountDeletionServiceSpy(
            preflight: blocked,
            status: .fixture(status: .blocked, retryable: true, blockers: [blocker])
        )
        let store = AccountDeletionCapabilityStoreSpy()
        let model = AccountDeletionRoomModel(
            service: service,
            capabilityStore: store,
            inventory: { .empty },
            localCleanup: { _, _ in XCTFail("blocked claim cannot clean") }
        )

        await model.load(owner: .fixture)
        await model.requestDeletion(
            owner: .fixture,
            reviewedInventoryDigest: AccountDeletionLocalInventory.empty.digest,
            unuploadedRidesAcknowledged: true
        )

        let createCallCount = await service.createCallCount
        XCTAssertEqual(createCallCount, 1)
        XCTAssertEqual(store.saveUnconfirmedCount, 1)
        XCTAssertEqual(store.saveCount, 1)
        XCTAssertEqual(store.deleteCount, 0)
        guard case let .tracking(status) = model.state else {
            return XCTFail("claim must remain a visible durable blocked status")
        }
        XCTAssertEqual(status.status, .blocked)
        XCTAssertEqual(status.blockers, [blocker])
    }

    @MainActor
    func testRatifiedHumanGateFilesDurableRequestWithoutOpeningExecution() async {
        let policyBlocker = AccountDeletionBlocker(
            code: "policy_review_required",
            category: "policy",
            asset: nil,
            amountBaseUnits: nil,
            count: 1,
            source: "on_chain_deletion_boundary",
            action: "contact_support"
        )
        let preflight = AccountDeletionPreflight(
            contractVersion: AccountDeletionContract.version,
            allowed: false,
            available: true,
            blockers: [policyBlocker],
            checkedAt: "2026-08-25T12:00:00Z"
        )
        let status = AccountDeletionStatus(
            contractVersion: AccountDeletionContract.version,
            requestID: "placeholder",
            status: .needsSupport,
            requestedAt: "2026-08-25T12:00:00Z",
            updatedAt: "2026-08-25T12:00:01Z",
            completedAt: nil,
            blockers: [policyBlocker],
            failureCode: nil,
            retryable: false,
            attemptCount: 0
        )
        let service = AccountDeletionServiceSpy(preflight: preflight, status: status)
        let store = AccountDeletionCapabilityStoreSpy()
        let model = AccountDeletionRoomModel(
            service: service,
            capabilityStore: store,
            inventory: { .empty },
            localCleanup: { _, _ in XCTFail("the ratified human gate cannot clean") }
        )

        await model.load(owner: .fixture)
        await model.requestDeletion(
            owner: .fixture,
            reviewedInventoryDigest: AccountDeletionLocalInventory.empty.digest,
            unuploadedRidesAcknowledged: true
        )

        let createCallCount = await service.createCallCount
        XCTAssertEqual(createCallCount, 1)
        XCTAssertNotNil(store.savedCapability)
        guard case let .tracking(current) = model.state else {
            return XCTFail("the filed request must surface durable needs-support status")
        }
        XCTAssertEqual(current.status, .needsSupport)
        XCTAssertFalse(current.retryable)
    }

    @MainActor
    func testUnacknowledgedLocalRidePreventsAnyDeleteRequest() async {
        let inventory = AccountDeletionLocalInventory.fixture(rideIDs: ["ride-1"])
        let service = AccountDeletionServiceSpy()
        let store = AccountDeletionCapabilityStoreSpy()
        let model = AccountDeletionRoomModel(
            service: service,
            capabilityStore: store,
            inventory: { inventory },
            localCleanup: { _, _ in XCTFail("unacknowledged custody cannot clean") }
        )

        await model.load(owner: .fixture)
        await model.requestDeletion(
            owner: .fixture,
            reviewedInventoryDigest: inventory.digest,
            unuploadedRidesAcknowledged: false
        )

        let createCallCount = await service.createCallCount
        XCTAssertEqual(createCallCount, 0)
        XCTAssertEqual(store.saveUnconfirmedCount, 0)
        XCTAssertEqual(store.deleteCount, 0)
        let unacknowledged = AccountDeletionCapability(
            requestID: "11111111-1111-4111-8111-111111111111",
            statusToken: String(repeating: "a", count: 43),
            owner: .fixture,
            inventoryDigest: inventory.digest,
            acknowledgedRideIDs: inventory.rides.map(\.id),
            unuploadedRidesAcknowledged: false,
            createdAt: Date(timeIntervalSince1970: 1_777_000_000),
            localCleanupCompletedAt: nil
        )
        XCTAssertFalse(unacknowledged.isValid)
        XCTAssertFalse(
            AccountDeletionWire.createPayload(for: unacknowledged)
                .unuploadedRidesAcknowledged
        )
    }

    @MainActor
    func testStableCreateConflictPersistsReplacementFenceBeforeClearingPair() async {
        let service = AccountDeletionServiceSpy(
            createError: APIError.http(
                status: 409,
                code: AccountDeletionConflictCode.requestAlreadyActive.rawValue,
                message: nil
            )
        )
        let store = AccountDeletionCapabilityStoreSpy()
        var replacementFenceOwner: RecordingOwner?
        let model = AccountDeletionRoomModel(
            service: service,
            capabilityStore: store,
            inventory: { .empty },
            localCleanup: { _, _ in XCTFail("conflict cannot clean") },
            acceptedStatusDiscarded: { owner in
                guard case .unconfirmed = store.load() else {
                    return XCTFail("the replacement fence must precede bearer deletion")
                }
                replacementFenceOwner = owner
            }
        )

        await model.load(owner: .fixture)
        await model.requestDeletion(
            owner: .fixture,
            reviewedInventoryDigest: AccountDeletionLocalInventory.empty.digest,
            unuploadedRidesAcknowledged: true
        )

        XCTAssertEqual(model.state, .supportRequired(.requestAlreadyActive))
        XCTAssertEqual(replacementFenceOwner, .fixture)
        XCTAssertNil(store.savedCapability)
        XCTAssertNil(store.unconfirmedCapability)
        XCTAssertEqual(store.deleteCount, 1)
    }

    @MainActor
    func testOwnerSwitchBeforeDeleteCannotSendProvisionalPair() async {
        let store = AccountDeletionCapabilityStoreSpy()
        let service = AccountDeletionServiceSpy()
        var fenceChecks = 0
        let model = AccountDeletionRoomModel(
            service: service,
            capabilityStore: store,
            inventory: { .empty },
            localCleanup: { _, _ in XCTFail("owner mismatch cannot clean") },
            capabilityDidChange: {
                fenceChecks += 1
                if fenceChecks == 2 {
                    throw AccountDeletionCapabilityStoreError.invalid
                }
            }
        )

        await model.load(owner: .fixture)
        await model.requestDeletion(
            owner: .fixture,
            reviewedInventoryDigest: AccountDeletionLocalInventory.empty.digest,
            unuploadedRidesAcknowledged: true
        )

        let createCallCount = await service.createCallCount
        XCTAssertEqual(createCallCount, 0, "owner change must be caught before DELETE")
        XCTAssertNil(store.savedCapability)
        XCTAssertNotNil(store.unconfirmedCapability)
        XCTAssertEqual(model.state, .ownerMismatch)
    }

    @MainActor
    func testOwnerSwitchDuringReissueCannotResendProvisionalPair() async {
        let capability = AccountDeletionCapability.fixture(owner: .fixture)
        let store = AccountDeletionCapabilityStoreSpy()
        store.unconfirmedCapability = capability
        let service = AccountDeletionServiceSpy(
            statusError: APIError.http(status: 404, code: nil, message: nil)
        )
        var fenceChecks = 0
        let model = AccountDeletionRoomModel(
            service: service,
            capabilityStore: store,
            inventory: { .empty },
            localCleanup: { _, _ in XCTFail("an unconfirmed request cannot clean") },
            capabilityDidChange: {
                fenceChecks += 1
                if fenceChecks == 2 {
                    throw AccountDeletionCapabilityStoreError.invalid
                }
            }
        )

        await model.load(owner: .fixture)
        XCTAssertEqual(model.state, .requestNotFound)
        await model.reissueDeletion()

        let createCallCount = await service.createCallCount
        XCTAssertEqual(createCallCount, 0, "owner change must be caught before reissued DELETE")
        XCTAssertNil(store.savedCapability)
        XCTAssertEqual(store.unconfirmedCapability, capability)
        XCTAssertEqual(model.state, .ownerMismatch)
    }

    @MainActor
    func testRetryConflictKeepsAcceptedPairAndRoutesToSupport() async {
        let status = AccountDeletionStatus.fixture(status: .blocked, retryable: true)
        let capability = AccountDeletionCapability.fixture(owner: .fixture)
        let service = AccountDeletionServiceSpy(
            retryError: APIError.http(
                status: 409,
                code: AccountDeletionConflictCode.accountUnavailable.rawValue,
                message: nil
            ),
            status: status
        )
        let store = AccountDeletionCapabilityStoreSpy(capability: capability)
        let model = AccountDeletionRoomModel(
            service: service,
            capabilityStore: store,
            inventory: { .empty },
            localCleanup: { _, _ in XCTFail("retry conflict cannot clean") }
        )

        await model.load(owner: nil)
        await model.retry()

        XCTAssertEqual(model.state, .supportRequired(.accountUnavailable))
        XCTAssertEqual(store.savedCapability, capability)
        XCTAssertEqual(store.deleteCount, 0)
    }

    @MainActor
    func testAcceptedStatusDiscardPersistsWriterFenceBeforeRemovingBearer() async {
        let owner = RecordingOwner.fixture
        let capability = AccountDeletionCapability.fixture(owner: owner)
        let service = AccountDeletionServiceSpy(
            status: .fixture(status: .needsSupport)
        )
        let store = AccountDeletionCapabilityStoreSpy(capability: capability)
        var fencedOwner: RecordingOwner?
        let model = AccountDeletionRoomModel(
            service: service,
            capabilityStore: store,
            inventory: { .empty },
            localCleanup: { _, _ in XCTFail("support status cannot clean") },
            acceptedStatusDiscarded: { owner in
                guard case .available = store.load() else {
                    XCTFail("the replacement fence must persist before bearer deletion")
                    return
                }
                fencedOwner = owner
            }
        )

        await model.load(owner: nil)
        await model.discardSavedStatus()

        XCTAssertEqual(fencedOwner, owner)
        XCTAssertEqual(store.deleteCount, 1)
        XCTAssertNil(store.savedCapability)
        XCTAssertEqual(model.state, .discarded)
    }

    @MainActor
    func testUnconfirmed404DiscardPersistsReplacementWriterFenceBeforeRemovingPair() async {
        let capability = AccountDeletionCapability.fixture(owner: .fixture)
        let service = AccountDeletionServiceSpy(
            statusError: APIError.http(status: 404, code: nil, message: nil)
        )
        let store = AccountDeletionCapabilityStoreSpy()
        store.unconfirmedCapability = capability
        var replacementFenceOwner: RecordingOwner?
        let model = AccountDeletionRoomModel(
            service: service,
            capabilityStore: store,
            inventory: { .empty },
            localCleanup: { _, _ in XCTFail("unconfirmed request cannot clean") },
            acceptedStatusDiscarded: { owner in
                guard case .unconfirmed = store.load() else {
                    return XCTFail("the replacement fence must precede provisional pair deletion")
                }
                replacementFenceOwner = owner
            }
        )

        await model.load(owner: .fixture)
        await model.discardSavedStatus()

        XCTAssertEqual(replacementFenceOwner, capability.owner)
        XCTAssertEqual(store.deleteCount, 1)
        XCTAssertNil(store.unconfirmedCapability)
        XCTAssertEqual(model.state, .discarded)
    }

    @MainActor
    func testDifferentOwnerCapabilityDoesNotBlockNewOwnersDeletionSurface() async {
        let deletingOwner = RecordingOwner(id: "deleting-rider", wallet: "deleting-wallet")
        let signedInOwner = RecordingOwner(id: "signed-in-rider", wallet: "signed-in-wallet")
        let capability = AccountDeletionCapability.fixture(owner: deletingOwner)
        let service = AccountDeletionServiceSpy(status: .fixture(status: .completed))
        let store = AccountDeletionCapabilityStoreSpy(capability: capability)
        var cleanupCount = 0
        var replacementFenceCount = 0
        let model = AccountDeletionRoomModel(
            service: service,
            capabilityStore: store,
            inventory: { .empty },
            localCleanup: { _, _ in cleanupCount += 1 },
            acceptedStatusDiscarded: { _ in replacementFenceCount += 1 }
        )

        await model.load(owner: signedInOwner)
        await model.discardSavedStatus()

        let statusCallCount = await service.statusCallCount
        XCTAssertEqual(
            model.state,
            .ready(.destructiveBoundaryOpenForTest, .empty)
        )
        XCTAssertEqual(statusCallCount, 0)
        XCTAssertEqual(cleanupCount, 0)
        XCTAssertEqual(replacementFenceCount, 0)
        XCTAssertEqual(store.deleteCount, 0)
        XCTAssertEqual(store.savedCapability, capability)
    }

    @MainActor
    func testLifecycleLoadsTheSessionSelectedRequestInsteadOfLedgerOrder() async {
        let ownerA = RecordingOwner(id: "ledger-owner-a", wallet: "ledger-wallet-a")
        let ownerB = RecordingOwner(id: "ledger-owner-b", wallet: "ledger-wallet-b")
        let capabilityB = AccountDeletionCapability.fixture(
            owner: ownerB,
            requestID: "22222222-2222-4222-8222-222222222222",
            tokenCharacter: "b"
        )
        let capabilityA = AccountDeletionCapability.fixture(owner: ownerA)
        let store = MultiOwnerDeletionCapabilityStore(states: [
            .available(capabilityB),
            .available(capabilityA),
        ])
        let model = AccountDeletionRoomModel(
            service: AccountDeletionServiceSpy(status: .fixture(status: .queued)),
            capabilityStore: store,
            inventory: { .empty }
        )

        await model.load(owner: nil, requestID: capabilityB.requestID)

        guard case let .tracking(status) = model.state else {
            return XCTFail("the selected request must own the lifecycle room")
        }
        XCTAssertEqual(status.requestID, capabilityB.requestID)
    }

    func testCapabilityLedgerPreservesExactRequestsAcrossScrubAndDone() throws {
        let ownerA = RecordingOwner(id: "ledger-owner-a", wallet: "ledger-wallet-a")
        let ownerB = RecordingOwner(id: "ledger-owner-b", wallet: "ledger-wallet-b")
        let capabilityA = AccountDeletionCapability.fixture(owner: ownerA)
        let capabilityB = AccountDeletionCapability.fixture(
            owner: ownerB,
            requestID: "22222222-2222-4222-8222-222222222222",
            tokenCharacter: "b"
        )
        var encoded = try KeychainAccountDeletionCapabilityStore.ledgerValue(
            existingValue: nil,
            upserting: capabilityA,
            accepted: true
        )
        encoded = try KeychainAccountDeletionCapabilityStore.ledgerValue(
            existingValue: encoded,
            upserting: capabilityB,
            accepted: false
        )
        let completedA = AccountDeletionStatus.fixture(
            status: .completed,
            completedAt: "2026-08-24T12:01:00Z"
        ).with(requestID: capabilityA.requestID)
        let scrubbedA = try XCTUnwrap(
            capabilityA
                .markingServerCompletionVerified(completedA)?
                .markingLocalCleanupCompleted()
        )
        encoded = try KeychainAccountDeletionCapabilityStore.ledgerValue(
            existingValue: encoded,
            upserting: scrubbedA,
            accepted: true
        )

        var states = KeychainAccountDeletionCapabilityStore.loadStates(marked: true) {
            encoded
        }
        XCTAssertEqual(states.count, 2)
        XCTAssertNil(states.first { $0.capability?.requestID == capabilityA.requestID }?.capability?.owner)
        XCTAssertEqual(
            states.first { $0.capability?.requestID == capabilityB.requestID }?.capability?.owner,
            ownerB
        )

        encoded = try XCTUnwrap(
            KeychainAccountDeletionCapabilityStore.ledgerValue(
                existingValue: encoded,
                removing: scrubbedA
            )
        )
        states = KeychainAccountDeletionCapabilityStore.loadStates(marked: true) { encoded }
        XCTAssertEqual(states, [.unconfirmed(capabilityB)])
    }

    @MainActor
    func testAmbiguousUnconfirmedStatusCannotDiscardTheOnlyWriterFence() async {
        let capability = AccountDeletionCapability.fixture(owner: .fixture)
        let service = AccountDeletionServiceSpy(
            statusError: URLError(.timedOut)
        )
        let store = AccountDeletionCapabilityStoreSpy()
        store.unconfirmedCapability = capability
        var replacementFenceCalled = false
        let model = AccountDeletionRoomModel(
            service: service,
            capabilityStore: store,
            inventory: { .empty },
            localCleanup: { _, _ in XCTFail("ambiguous request cannot clean") },
            acceptedStatusDiscarded: { _ in replacementFenceCalled = true }
        )

        await model.load(owner: .fixture)
        XCTAssertEqual(model.state, .statusUnavailable)
        XCTAssertFalse(model.canDiscardSavedStatus)
        await model.discardSavedStatus()

        XCTAssertFalse(replacementFenceCalled)
        XCTAssertEqual(store.deleteCount, 0)
        XCTAssertEqual(store.unconfirmedCapability, capability)
    }

    @MainActor
    func testAcceptedRetryUsesOnlyCapabilityStatusAndNeverAuthenticatedPreflight() async {
        let status = AccountDeletionStatus.fixture(status: .blocked, retryable: true)
        let service = AccountDeletionServiceSpy(status: status)
        let store = AccountDeletionCapabilityStoreSpy(
            capability: .fixture(owner: .fixture)
        )
        let model = AccountDeletionRoomModel(
            service: service,
            capabilityStore: store,
            inventory: { .empty },
            localCleanup: { _, _ in XCTFail("blocked retry cannot clean") }
        )

        await model.load(owner: nil)
        await model.retry()

        let preflightCallCount = await service.preflightCallCount
        let retryCallCount = await service.retryCallCount
        XCTAssertEqual(preflightCallCount, 0)
        XCTAssertEqual(retryCallCount, 1)
    }

    @MainActor
    func testLocallyCompletedJournalDismissesOfflineWithoutStatusRead() async throws {
        let base = AccountDeletionCapability.fixture(owner: .fixture)
        let completed = AccountDeletionStatus.fixture(
            status: .completed,
            completedAt: "2026-08-24T12:01:00Z"
        )
        let verified = try XCTUnwrap(base.markingServerCompletionVerified(completed))
        let locallyCompleted = try XCTUnwrap(
            verified.markingLocalCleanupCompleted(
                at: Date(timeIntervalSince1970: 1_777_000_100)
            )
        )
        let service = AccountDeletionServiceSpy(
            statusError: APIError.http(status: 404, code: nil, message: nil)
        )
        let store = AccountDeletionCapabilityStoreSpy(capability: locallyCompleted)
        let cleanup = CleanupSpy()
        let model = AccountDeletionRoomModel(
            service: service,
            capabilityStore: store,
            inventory: { throw TestError.unavailable },
            localCleanup: { capability, status in
                await cleanup.record(capability: capability, status: status)
            }
        )

        await model.load(owner: nil)

        XCTAssertEqual(model.state, .completedLocally)
        let statusCallCount = await service.statusCallCount
        let cleanupCallCount = await cleanup.callCount
        XCTAssertEqual(statusCallCount, 0)
        XCTAssertEqual(cleanupCallCount, 0)
        await model.acknowledgeCompletion()
        XCTAssertEqual(store.deleteCount, 1)
        XCTAssertEqual(model.state, .discarded)
    }

    @MainActor
    func testPollingPreservesLastStatusAndBacksOffFiveTenTwentySeconds() async {
        let queued = AccountDeletionStatus.fixture(status: .queued)
        let service = AccountDeletionServiceSpy(status: queued)
        let store = AccountDeletionCapabilityStoreSpy(
            capability: .fixture(owner: .fixture)
        )
        let model = AccountDeletionRoomModel(
            service: service,
            capabilityStore: store,
            inventory: { .empty },
            localCleanup: { _, _ in XCTFail("queued status cannot clean") }
        )

        await model.load(owner: nil)
        XCTAssertEqual(model.pollDelaySeconds, 5)
        await service.setStatusError(URLError(.timedOut))
        await model.pollStatus()
        XCTAssertEqual(model.state, .tracking(queued))
        XCTAssertEqual(model.pollDelaySeconds, 10)
        await model.pollStatus()
        XCTAssertEqual(model.pollDelaySeconds, 20)
        await model.pollStatus()
        XCTAssertEqual(model.pollDelaySeconds, 20)
        await service.setStatusError(nil)
        await model.pollStatus()
        XCTAssertEqual(model.state, .tracking(queued))
        XCTAssertEqual(model.pollDelaySeconds, 5)
    }

    @MainActor
    func testOverlappingCompletionRefreshCannotSkipDurableLocalMarker() async throws {
        let completed = AccountDeletionStatus.fixture(
            status: .completed,
            completedAt: "2026-08-24T12:01:00Z"
        )
        let service = AccountDeletionServiceSpy(status: completed)
        let store = AccountDeletionCapabilityStoreSpy(
            capability: .fixture(owner: .fixture)
        )
        let cleanup = CleanupGate()
        let model = AccountDeletionRoomModel(
            service: service,
            capabilityStore: store,
            inventory: { .empty },
            localCleanup: { _, _ in await cleanup.run() }
        )

        let first = Task { await model.load(owner: nil) }
        await cleanup.waitUntilEntered()
        await model.refreshStatus()
        await cleanup.release()
        await first.value

        let cleanupCallCount = await cleanup.callCount
        XCTAssertEqual(cleanupCallCount, 1)
        XCTAssertNotNil(store.savedCapability?.verifiedCompletion)
        XCTAssertNotNil(store.savedCapability?.localCleanupCompletedAt)
        XCTAssertEqual(model.state, .completed(completed))
    }

    func testInventoryUnionsCustodyAndUploadRowsByStableJobID() throws {
        let inventory = try AccountDeletionLocalInventory(
            custody: [
                .fixture(rideID: "custody-1", uploadJobID: "job-1", handedOff: true),
                .fixture(rideID: "custody-2", uploadJobID: "job-2", handedOff: false),
            ],
            uploads: [
                .fixture(id: "job-1", phase: .processing),
                .fixture(id: "job-3", phase: .final),
            ]
        )

        XCTAssertEqual(Set(inventory.rides.map(\.id)), Set(["job-1", "job-2"]))
        XCTAssertEqual(inventory.rides.count, 2, "handed-off custody and its upload job are one ride")
    }

    func testHandedOffCustodyWithoutItsQueueRowFailsClosed() {
        XCTAssertThrowsError(
            try AccountDeletionLocalInventory(
                custody: [.fixture(rideID: "custody-1", uploadJobID: "job-1", handedOff: true)],
                uploads: []
            )
        )
    }
}

private enum TestError: Error { case unavailable }

private struct EmptySessionCredentialStore: SessionCredentialStore {
    func readRefreshToken() throws -> String? { nil }
    func saveRefreshToken(_ token: String) throws {}
    func deleteRefreshToken() throws {}
}

private final class FailingDeletionCredentialStore: SessionCredentialStore, @unchecked Sendable {
    var token: String?

    init(token: String?) { self.token = token }

    func readRefreshToken() throws -> String? { token }
    func saveRefreshToken(_ token: String) throws { self.token = token }
    func deleteRefreshToken() throws { throw TestError.unavailable }
}

private final class AccountDeletionRequestRecorder: @unchecked Sendable {
    private let lock = NSLock()
    private var storedRequests: [URLRequest] = []

    var requests: [URLRequest] { lock.withLock { storedRequests } }

    func record(_ request: URLRequest) {
        lock.withLock { storedRequests.append(request) }
    }
}

private final class AccountDeletionURLProtocol: URLProtocol, @unchecked Sendable {
    private static let lock = NSLock()
    private static var storedRequests: [URLRequest] = []

    static var requests: [URLRequest] {
        lock.lock()
        defer { lock.unlock() }
        return storedRequests
    }

    static func reset() {
        lock.lock()
        storedRequests = []
        lock.unlock()
    }

    override class func canInit(with request: URLRequest) -> Bool { true }
    override class func canonicalRequest(for request: URLRequest) -> URLRequest { request }

    override func startLoading() {
        Self.lock.lock()
        Self.storedRequests.append(request)
        Self.lock.unlock()
        let requestID = request.url?.lastPathComponent ?? ""
        let body = Data(
            """
            {
              "contract_version":"account-deletion.v1",
              "request_id":"\(requestID)",
              "status":"queued",
              "requested_at":"2026-08-24T12:00:00Z",
              "updated_at":"2026-08-24T12:00:01Z",
              "completed_at":null,
              "blockers":[],
              "failure_code":null,
              "retryable":false,
              "attempt_count":0
            }
            """.utf8
        )
        let response = HTTPURLResponse(
            url: request.url!,
            statusCode: 200,
            httpVersion: "HTTP/1.1",
            headerFields: ["Content-Type": "application/json"]
        )!
        client?.urlProtocol(self, didReceive: response, cacheStoragePolicy: .notAllowed)
        client?.urlProtocol(self, didLoad: body)
        client?.urlProtocolDidFinishLoading(self)
    }

    override func stopLoading() {}
}

private final class DelayedAccountBoundaryURLProtocol: URLProtocol, @unchecked Sendable {
    private static let lock = NSLock()
    private static var storedRequestCount = 0

    static var requestCount: Int {
        lock.withLock { storedRequestCount }
    }

    static func reset() {
        lock.withLock { storedRequestCount = 0 }
    }

    override class func canInit(with request: URLRequest) -> Bool { true }
    override class func canonicalRequest(for request: URLRequest) -> URLRequest { request }

    override func startLoading() {
        Self.lock.withLock { Self.storedRequestCount += 1 }
        let url = request.url!
        DispatchQueue.global().asyncAfter(deadline: .now() + 0.12) { [weak self] in
            guard let self else { return }
            let body = Data(
                """
                {
                  "balance_rollout": {
                    "stage": "disabled",
                    "cohort": "none",
                    "enabled_actions": [],
                    "action_order": [],
                    "enforced": true,
                    "order_valid": true,
                    "blockers": []
                  },
                  "mobile_capabilities": null
                }
                """.utf8
            )
            let response = HTTPURLResponse(
                url: url,
                statusCode: 200,
                httpVersion: "HTTP/1.1",
                headerFields: ["Content-Type": "application/json"]
            )!
            self.client?.urlProtocol(self, didReceive: response, cacheStoragePolicy: .notAllowed)
            self.client?.urlProtocol(self, didLoad: body)
            self.client?.urlProtocolDidFinishLoading(self)
        }
    }

    override func stopLoading() {}
}

private actor AccountDeletionServiceSpy: AccountDeletionServing {
    private(set) var createdCapabilities: [AccountDeletionCapability] = []
    private(set) var retriedCapabilities: [AccountDeletionCapability] = []
    private(set) var preflightCallCount = 0
    private(set) var statusCallCount = 0
    var createCallCount: Int { createdCapabilities.count }
    var retryCallCount: Int { retriedCapabilities.count }
    private let createError: Error?
    private var statusError: Error?
    private let retryError: Error?
    private let preflightValue: AccountDeletionPreflight
    private let statusValue: AccountDeletionStatus

    init(
        createError: Error? = nil,
        statusError: Error? = nil,
        retryError: Error? = nil,
        preflight: AccountDeletionPreflight = .destructiveBoundaryOpenForTest,
        status: AccountDeletionStatus = .fixture(status: .queued)
    ) {
        self.createError = createError
        self.statusError = statusError
        self.retryError = retryError
        preflightValue = preflight
        statusValue = status
    }

    func preflight() async throws -> AccountDeletionPreflight {
        preflightCallCount += 1
        return preflightValue
    }

    func create(capability: AccountDeletionCapability) async throws -> AccountDeletionStatus {
        createdCapabilities.append(capability)
        if let createError { throw createError }
        return statusValue.with(requestID: capability.requestID)
    }

    func status(capability: AccountDeletionCapability) async throws -> AccountDeletionStatus {
        statusCallCount += 1
        if let statusError { throw statusError }
        return statusValue.with(requestID: capability.requestID)
    }

    func retry(capability: AccountDeletionCapability) async throws -> AccountDeletionStatus {
        retriedCapabilities.append(capability)
        if let retryError { throw retryError }
        return statusValue.with(requestID: capability.requestID)
    }

    func setStatusError(_ error: Error?) {
        statusError = error
    }
}

private final class AccountDeletionCapabilityStoreSpy: AccountDeletionCapabilityStoring, @unchecked Sendable {
    var savedCapability: AccountDeletionCapability?
    var unconfirmedCapability: AccountDeletionCapability?
    var saveCount = 0
    var saveUnconfirmedCount = 0
    var deleteCount = 0
    var isUnavailable = false
    let saveError: Error?

    init(capability: AccountDeletionCapability? = nil, saveError: Error? = nil) {
        savedCapability = capability
        self.saveError = saveError
    }

    func load() -> AccountDeletionCapabilityStorageState {
        if isUnavailable { return .unavailable }
        if let savedCapability { return .available(savedCapability) }
        if let unconfirmedCapability { return .unconfirmed(unconfirmedCapability) }
        return .none
    }

    func saveUnconfirmed(_ capability: AccountDeletionCapability) throws {
        if let saveError { throw saveError }
        unconfirmedCapability = capability
        savedCapability = nil
        saveUnconfirmedCount += 1
    }

    func save(_ capability: AccountDeletionCapability) throws {
        if let saveError { throw saveError }
        savedCapability = capability
        unconfirmedCapability = nil
        saveCount += 1
    }

    func delete() throws {
        deleteCount += 1
        savedCapability = nil
        unconfirmedCapability = nil
    }
}

private final class MultiOwnerDeletionCapabilityStore: AccountDeletionCapabilityStoring, @unchecked Sendable {
    private let lock = NSLock()
    private var states: [AccountDeletionCapabilityStorageState]

    init(states: [AccountDeletionCapabilityStorageState]) {
        self.states = states
    }

    func load() -> AccountDeletionCapabilityStorageState {
        lock.withLock { states.last ?? .none }
    }

    func load(owner: RecordingOwner?) -> AccountDeletionCapabilityStorageState {
        guard let owner else { return load() }
        return lock.withLock {
            states.last { $0.capability?.owner == owner } ?? .none
        }
    }

    func load(requestID: String) -> AccountDeletionCapabilityStorageState {
        lock.withLock {
            states.last {
                $0.capability?.requestID.caseInsensitiveCompare(requestID) == .orderedSame
            } ?? .none
        }
    }

    func loadAll() -> [AccountDeletionCapabilityStorageState] {
        lock.withLock { states }
    }

    func saveUnconfirmed(_ capability: AccountDeletionCapability) throws {
        upsert(.unconfirmed(capability))
    }

    func save(_ capability: AccountDeletionCapability) throws {
        upsert(.available(capability))
    }

    func delete() throws {
        guard let capability = load().capability else {
            throw AccountDeletionCapabilityStoreError.invalid
        }
        try delete(capability)
    }

    func delete(_ capability: AccountDeletionCapability) throws {
        lock.withLock {
            states.removeAll {
                $0.capability?.requestID.caseInsensitiveCompare(capability.requestID) == .orderedSame
            }
        }
    }

    private func upsert(_ state: AccountDeletionCapabilityStorageState) {
        guard let capability = state.capability else { return }
        lock.withLock {
            if let index = states.firstIndex(where: {
                $0.capability?.requestID.caseInsensitiveCompare(capability.requestID) == .orderedSame
            }) {
                states[index] = state
            } else {
                states.append(state)
            }
        }
    }
}

private actor CleanupSpy {
    private(set) var callCount = 0
    private(set) var lastOwner: RecordingOwner?

    func record(capability: AccountDeletionCapability, status: AccountDeletionStatus) {
        callCount += 1
        lastOwner = capability.owner
    }
}

private actor CleanupGate {
    private(set) var callCount = 0
    private var entered = false
    private var releaseContinuation: CheckedContinuation<Void, Never>?

    func run() async {
        callCount += 1
        entered = true
        await withCheckedContinuation { continuation in
            releaseContinuation = continuation
        }
    }

    func waitUntilEntered() async {
        while !entered { await Task.yield() }
    }

    func release() {
        releaseContinuation?.resume()
        releaseContinuation = nil
    }
}

private extension RecordingOwner {
    static let fixture = RecordingOwner(id: "rider-1", wallet: "wallet-1")
}

private extension AccountDeletionBlocker {
    static func fixture(code: String, category: String) -> Self {
        Self(code: code, category: category, asset: nil, amountBaseUnits: nil, count: nil, source: nil, action: nil)
    }
}

private extension AccountDeletionPreflight {
    /// Explicitly future-only: the ratified v1 backend keeps its destructive
    /// boundary closed. Tests use this solely to exercise client-side fences.
    static let destructiveBoundaryOpenForTest = Self(
        contractVersion: AccountDeletionContract.version,
        allowed: true,
        available: true,
        blockers: [],
        checkedAt: "2026-08-24T12:00:00Z"
    )
}

private extension AccountDeletionCapability {
    static func fixture(
        owner: RecordingOwner,
        inventory: AccountDeletionLocalInventory = .empty,
        requestID: String = "11111111-1111-4111-8111-111111111111",
        tokenCharacter: Character = "a"
    ) -> Self {
        Self(
            requestID: requestID,
            statusToken: String(repeating: tokenCharacter, count: 43),
            owner: owner,
            inventoryDigest: inventory.digest,
            acknowledgedRideIDs: inventory.rides.map(\.id),
            unuploadedRidesAcknowledged: true,
            createdAt: Date(timeIntervalSince1970: 1_777_000_000),
            localCleanupCompletedAt: nil
        )
    }
}

private extension AccountDeletionStatus {
    static func fixture(
        status: AccountDeletionStatusCode,
        completedAt: String? = nil,
        retryable: Bool? = nil,
        blockers: [AccountDeletionBlocker] = []
    ) -> Self {
        Self(
            contractVersion: AccountDeletionContract.version,
            requestID: "11111111-1111-4111-8111-111111111111",
            status: status,
            requestedAt: "2026-08-24T12:00:00Z",
            updatedAt: "2026-08-24T12:00:30Z",
            completedAt: completedAt,
            blockers: blockers,
            failureCode: nil,
            retryable: retryable ?? (status == .failedRetryable),
            attemptCount: 1
        )
    }

    func with(requestID: String) -> Self {
        Self(
            contractVersion: contractVersion,
            requestID: requestID,
            status: status,
            requestedAt: requestedAt,
            updatedAt: updatedAt,
            completedAt: completedAt,
            blockers: blockers,
            failureCode: failureCode,
            retryable: retryable,
            attemptCount: attemptCount
        )
    }
}

private extension AccountDeletionCustodyRecord {
    static func fixture(rideID: String, uploadJobID: String, handedOff: Bool) -> Self {
        Self(
            rideID: rideID,
            uploadJobID: uploadJobID,
            startedAt: Date(timeIntervalSince1970: 1_777_000_000),
            handedOff: handedOff
        )
    }
}

private extension AccountDeletionUploadRecord {
    static func fixture(id: String, phase: RideUploadPhase) -> Self {
        Self(
            id: id,
            fileName: "Ride-\(id).gpx",
            startedAt: Date(timeIntervalSince1970: 1_777_000_000),
            phase: phase
        )
    }
}

private extension AccountDeletionLocalInventory {
    static func fixture(rideIDs: [String]) -> Self {
        Self(rides: rideIDs.map {
            AccountDeletionLocalRide(
                id: $0,
                fileName: "Ride-\($0).gpx",
                startedAt: Date(timeIntervalSince1970: 1_777_000_000),
                state: .unuploaded
            )
        })
    }
}
