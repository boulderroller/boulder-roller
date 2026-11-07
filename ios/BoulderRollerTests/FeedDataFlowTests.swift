import Foundation
import XCTest
@testable import BoulderRoller

final class FeedDataFlowTests: XCTestCase {
    private var rootURL: URL!
    private let owner = RecordingOwner(id: "rider-a", wallet: "wallet-a")

    override func setUpWithError() throws {
        AccountDeletionSessionRecordStore.clear()
        rootURL = FileManager.default.temporaryDirectory
            .appendingPathComponent("FeedDataFlowTests-\(UUID().uuidString)", isDirectory: true)
    }

    override func tearDownWithError() throws {
        AccountDeletionSessionRecordStore.clear()
        if let rootURL, FileManager.default.fileExists(atPath: rootURL.path) {
            try FileManager.default.removeItem(at: rootURL)
        }
    }

    func testFeedPageDecodesTheBackendCursorAndRideContract() throws {
        let json = Data(
            """
            {
              "contractVersion": "feed.v1",
              "activities": [{
                "id": "ride-a",
                "type": "ride",
                "eventType": "ride_completed",
                "title": "Lunch Ride",
                "createdAt": "2026-08-14T17:00:00Z",
                "occurredAt": "2026-08-14T17:00:00Z",
                "status": "completed",
                "actor": {"id": "rider-a", "displayName": "Gabe"},
                "target": {"type": "ride", "id": "ride-a"},
                "metadata": {"distanceM": 12300, "durationS": 2900}
              }],
              "has_more": true,
              "next_cursor": "2026-08-14T17:00:00Z"
            }
            """.utf8
        )
        let decoder = JSONDecoder()
        decoder.keyDecodingStrategy = .convertFromSnakeCase

        let page = try decoder.decode(FeedPage.self, from: json)

        XCTAssertEqual(page.activities.first?.rideID, "ride-a")
        XCTAssertEqual(page.activities.first?.rider?.shownName, "Gabe")
        XCTAssertTrue(page.hasMore)
        XCTAssertEqual(page.nextCursor, "2026-08-14T17:00:00Z")
    }

    func testFileCacheRequiresTheExactOwnerWalletAndScope() async throws {
        let cache = makeCache()
        let snapshot = FeedCacheSnapshot(
            owner: owner,
            scope: .following,
            activities: [activity("ride-a", secondsAgo: 0)],
            hasMore: false,
            nextCursor: nil
        )
        try await cache.save(snapshot)

        let exact = try await cache.load(owner: owner, scope: .following)
        let replacement = try await cache.load(
            owner: RecordingOwner(id: owner.id, wallet: "replacement-wallet"),
            scope: .following
        )
        let otherScope = try await cache.load(owner: owner, scope: .global)
        XCTAssertNotNil(exact)
        XCTAssertNil(replacement)
        XCTAssertNil(otherScope)
    }

    @MainActor
    func testCachedFeedSurvivesAnUnavailableRefresh() async throws {
        let cache = makeCache()
        try await cache.save(FeedCacheSnapshot(
            owner: owner,
            scope: .following,
            activities: [activity("cached-ride", secondsAgo: 0)],
            hasMore: false,
            nextCursor: nil
        ))
        let model = FeedModel(
            loadFeedPage: { _, _, _ in throw URLError(.notConnectedToInternet) },
            loadLocalJobs: { _ in [] },
            cache: cache
        )

        await model.reload(owner: owner, scope: .following)

        XCTAssertTrue(model.loaded)
        XCTAssertTrue(model.loadFailed)
        XCTAssertTrue(model.isShowingCachedData)
        XCTAssertEqual(activityIDs(model.items), ["cached-ride"])
    }

    @MainActor
    func testSuccessfulRefreshAtomicallyReplacesTheCachedFirstPage() async throws {
        let cache = makeCache()
        try await cache.save(FeedCacheSnapshot(
            owner: owner,
            scope: .following,
            activities: [activity("old-ride", secondsAgo: 10)],
            hasMore: false,
            nextCursor: nil
        ))
        let fresh = activity("fresh-ride", secondsAgo: 0)
        let model = FeedModel(
            loadFeedPage: { _, _, _ in
                FeedPage(activities: [fresh], hasMore: false, nextCursor: nil)
            },
            loadLocalJobs: { _ in [] },
            cache: cache
        )

        await model.reload(owner: owner, scope: .following)

        XCTAssertEqual(activityIDs(model.items), ["fresh-ride"])
        XCTAssertFalse(model.isShowingCachedData)
        let saved = try await cache.load(owner: owner, scope: .following)
        XCTAssertEqual(saved?.activities.map(\.id), ["fresh-ride"])
    }

    @MainActor
    func testInFlightFeedRefreshCannotRepopulateCacheAfterDeletionFence() async throws {
        let cache = makeCache()
        let gate = FeedPageGate()
        let fresh = activity("late-ride", secondsAgo: 0)
        let model = FeedModel(
            loadFeedPage: { _, _, _ in
                await gate.wait()
                return FeedPage(activities: [fresh], hasMore: false, nextCursor: nil)
            },
            loadLocalJobs: { _ in [] },
            cache: cache
        )
        let reload = Task { await model.reload(owner: owner, scope: .following) }
        while !(await gate.hasWaiter) {
            try await Task.sleep(for: .milliseconds(5))
        }

        await cache.freeze(owner: owner)
        await gate.release()
        await reload.value

        let stored = try await cache.load(owner: owner, scope: .following)
        XCTAssertNil(stored)
        let files = (try? FileManager.default.contentsOfDirectory(atPath: rootURL.path)) ?? []
        XCTAssertTrue(files.isEmpty)
    }

    func testDurableDeletionFenceBlocksColdCacheReadsAndWritesWithoutVolatileFreeze() async throws {
        let cache = makeCache()
        let existing = FeedCacheSnapshot(
            owner: owner,
            scope: .following,
            activities: [activity("existing-ride", secondsAgo: 10)],
            hasMore: false,
            nextCursor: nil
        )
        try await cache.save(existing)
        try AccountDeletionSessionRecordStore.recordRequired(
            AccountDeletionSessionRecord(state: .pending, owner: owner)
        )

        let blockedRead = try await cache.load(owner: owner, scope: .following)
        XCTAssertNil(blockedRead, "cold cache reads must honor the durable exact-owner fence")

        let late = FeedCacheSnapshot(
            owner: owner,
            scope: .global,
            activities: [activity("late-ride", secondsAgo: 0)],
            hasMore: false,
            nextCursor: nil
        )
        do {
            try await cache.save(late)
            XCTFail("cold cache writes must honor the durable exact-owner fence")
        } catch AccountDeletionLocalCleanupError.verificationFailed {}

        AccountDeletionSessionRecordStore.clear()
        let retained = try await cache.load(owner: owner, scope: .following)
        let lateWrite = try await cache.load(owner: owner, scope: .global)
        XCTAssertEqual(retained?.activities.map(\.id), ["existing-ride"])
        XCTAssertNil(lateWrite, "the refused late page must never reach disk")
    }

    func testUnfreezeCannotReopenCacheWhileDurableDeletionFenceRemains() async throws {
        let cache = makeCache()
        await cache.freeze(owner: owner)
        try AccountDeletionSessionRecordStore.recordRequired(
            AccountDeletionSessionRecord(state: .pending, owner: owner)
        )

        await cache.unfreeze(owner: owner)
        AccountDeletionSessionRecordStore.clear()

        do {
            try await cache.save(FeedCacheSnapshot(
                owner: owner,
                scope: .following,
                activities: [activity("reopened-ride", secondsAgo: 0)],
                hasMore: false,
                nextCursor: nil
            ))
            XCTFail("unfreeze must preserve the volatile fence until durable deletion truth clears")
        } catch AccountDeletionLocalCleanupError.verificationFailed {}

        await cache.unfreeze(owner: owner)
        try await cache.save(FeedCacheSnapshot(
            owner: owner,
            scope: .following,
            activities: [activity("safe-ride", secondsAgo: 0)],
            hasMore: false,
            nextCursor: nil
        ))
        let stored = try await cache.load(owner: owner, scope: .following)
        XCTAssertEqual(stored?.activities.map(\.id), ["safe-ride"])
    }

    @MainActor
    func testPaginationDeduplicatesRideIDsAndRetryKeepsThePriorPage() async {
        let script = FeedPageScript([
            FeedPage(
                activities: [activity("ride-a", secondsAgo: 0), activity("ride-b", secondsAgo: 10)],
                hasMore: true,
                nextCursor: "cursor-1"
            ),
            nil,
            FeedPage(
                activities: [activity("ride-b", secondsAgo: 10), activity("ride-c", secondsAgo: 20)],
                hasMore: false,
                nextCursor: nil
            ),
        ])
        let model = FeedModel(
            loadFeedPage: { scope, before, limit in
                try await script.next(scope: scope, before: before, limit: limit)
            },
            loadLocalJobs: { _ in [] },
            cache: makeCache()
        )

        await model.reload(owner: owner, scope: .following)
        await model.loadNextPage(owner: owner, scope: .following)

        XCTAssertTrue(model.paginationFailed)
        XCTAssertEqual(activityIDs(model.items), ["ride-a", "ride-b"])

        await model.loadNextPage(owner: owner, scope: .following)

        XCTAssertFalse(model.paginationFailed)
        XCTAssertEqual(activityIDs(model.items), ["ride-a", "ride-b", "ride-c"])
        XCTAssertFalse(model.hasMore)
    }

    @MainActor
    func testLocalProcessingRideSupersedesItsServerFeedEventUntilFinal() async {
        let ride = activity("ride-a", secondsAgo: 0)
        let processing = uploadJob(serverRideID: ride.id, phase: .processing)
        let model = FeedModel(
            loadFeedPage: { _, _, _ in
                FeedPage(activities: [ride], hasMore: false, nextCursor: nil)
            },
            loadLocalJobs: { _ in [processing] },
            cache: makeCache()
        )

        await model.reload(owner: owner, scope: .following)

        XCTAssertEqual(model.items.count, 1)
        guard case .local = model.items[0].source else {
            return XCTFail("the durable local processing card must remain visible")
        }
    }

    private func makeCache() -> FileFeedCache {
        FileFeedCache(
            rootURL: rootURL,
            durableAccountWorkPermitted: { owner in
                AccountDeletionLocalFence.permitsAccountWork(
                    owner: owner,
                    sessionRecords: AccountDeletionSessionRecordStore.records()
                        + AccountDeletionProcessFence.records(),
                    capabilityState: .none
                )
            }
        )
    }

    private func activity(_ id: String, secondsAgo: TimeInterval) -> FeedActivity {
        let date = Date(timeIntervalSince1970: 1_786_720_000 - secondsAgo)
        let iso = Format.isoParser.string(from: date)
        return FeedActivity(
            id: id,
            type: "ride",
            eventType: "ride_completed",
            title: "Lunch Ride",
            createdAt: iso,
            occurredAt: iso,
            status: "completed",
            actor: FeedActor(
                id: "rider-a",
                username: "gabe",
                displayName: "Gabe",
                avatarUrl: nil
            ),
            user: nil,
            target: FeedTarget(type: "ride", id: id),
            metadata: FeedActivityMetadata(
                distanceM: 12_300,
                elevationM: 230,
                elevationCorrectedM: 220,
                durationS: 2_900,
                dungEarned: nil,
                calEarned: 42,
                status: "completed",
                kudosCount: 2,
                commentCount: 1,
                viewerHasKudos: false,
                media: nil,
                primaryMedia: nil,
                routePreview: nil
            ),
            privacy: nil
        )
    }

    private func uploadJob(serverRideID: String, phase: RideUploadPhase) -> RideUploadJob {
        RideUploadJob(
            id: "local-job",
            ownerID: owner.id,
            ownerWallet: owner.wallet,
            fileName: "ride.gpx",
            fileType: "gpx",
            fileHash: String(repeating: "a", count: 64),
            fileSize: 1_024,
            sourceFileName: "ride.gpx",
            localSummary: LocalRideSummary(
                startedAt: Date(timeIntervalSince1970: 1_786_720_000),
                distanceM: 12_300,
                elevationM: 230,
                durationS: 2_900
            ),
            createdAt: Date(timeIntervalSince1970: 1_786_720_000),
            updatedAt: Date(timeIntervalSince1970: 1_786_720_000),
            phase: phase,
            attemptedServerHandoff: true,
            signedURL: nil,
            signedURLExpiresAt: nil,
            serverRideID: serverRideID,
            authoritativeStatus: "processing",
            attemptCount: 1,
            nextRetryAt: nil,
            lastError: nil,
            canRetry: false,
            revealState: .none,
            reveal: nil
        )
    }

    @MainActor
    private func activityIDs(_ items: [RideFeedItem]) -> [String] {
        items.compactMap { item in
            guard case let .activity(activity) = item.source else { return nil }
            return activity.id
        }
    }
}

private actor FeedPageScript {
    private var pages: [FeedPage?]

    init(_ pages: [FeedPage?]) {
        self.pages = pages
    }

    func next(scope: FeedScope, before: String?, limit: Int) throws -> FeedPage {
        guard !pages.isEmpty else { throw URLError(.badServerResponse) }
        guard let page = pages.removeFirst() else {
            throw URLError(.notConnectedToInternet)
        }
        return page
    }
}

private actor FeedPageGate {
    private var waiter: CheckedContinuation<Void, Never>?

    var hasWaiter: Bool { waiter != nil }

    func wait() async {
        await withCheckedContinuation { continuation in
            waiter = continuation
        }
    }

    func release() {
        waiter?.resume()
        waiter = nil
    }
}
