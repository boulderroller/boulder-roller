import Foundation
import XCTest
@testable import BoulderRoller

final class RideRevealAcknowledgementDurabilityTests: XCTestCase {
    private var rootURL: URL!
    private let ownerID = "reveal-owner-1"
    private let otherOwnerID = "reveal-owner-2"
    private let authoritativeRideID = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
    private let source = Data("exact-reveal-source".utf8)

    override func setUpWithError() throws {
        rootURL = FileManager.default.temporaryDirectory.appendingPathComponent(
            "RideRevealAcknowledgementDurabilityTests-\(UUID().uuidString)",
            isDirectory: true
        )
    }

    override func tearDownWithError() throws {
        if let rootURL, FileManager.default.fileExists(atPath: rootURL.path) {
            try FileManager.default.removeItem(at: rootURL)
        }
    }

    func testSelectedRevealSurvivesStoreRecreationUntilAcknowledged() async throws {
        let store = FileRideUploadJobStore(rootURL: rootURL)
        let job = revealJob(
            id: "11111111-1111-4111-8111-111111111111",
            ownerID: ownerID,
            createdAt: Date(timeIntervalSince1970: 1_786_500_000)
        )
        try await store.create(job, sourceBytes: source)

        let owner = recordingOwner(ownerID)
        let selectedValue = try await store.claimNextReveal(owner: owner)
        let selected = try XCTUnwrap(selectedValue)
        let restartedStore = FileRideUploadJobStore(rootURL: rootURL)
        let recovered = try await restartedStore.claimNextReveal(owner: owner)

        XCTAssertEqual(
            recovered,
            selected,
            "selection is not acknowledgement; process recreation must recover the same reveal"
        )
    }

    func testOwnerSwitchCannotTakeRevealAndOriginalOwnerRecoversAfterRestart() async throws {
        let store = FileRideUploadJobStore(rootURL: rootURL)
        let job = revealJob(
            id: "22222222-2222-4222-8222-222222222222",
            ownerID: ownerID,
            createdAt: Date(timeIntervalSince1970: 1_786_500_100)
        )
        try await store.create(job, sourceBytes: source)

        let owner = recordingOwner(ownerID)
        let selectedValue = try await store.claimNextReveal(owner: owner)
        let selected = try XCTUnwrap(selectedValue)
        let switchedOwnerStore = FileRideUploadJobStore(rootURL: rootURL)
        let switchedOwnerReveal = try await switchedOwnerStore.claimNextReveal(
            owner: recordingOwner(otherOwnerID)
        )
        XCTAssertNil(switchedOwnerReveal)

        let resumedOwnerStore = FileRideUploadJobStore(rootURL: rootURL)
        let recovered = try await resumedOwnerStore.claimNextReveal(owner: owner)
        XCTAssertEqual(
            recovered,
            selected,
            "sign-out or owner switching must not consume the original owner's unacknowledged reveal"
        )
    }

    func testAcknowledgementConsumesSameAuthoritativeIDSiblingsAndPreventsReplay() async throws {
        let store = FileRideUploadJobStore(rootURL: rootURL)
        let first = revealJob(
            id: "33333333-3333-4333-8333-333333333333",
            ownerID: ownerID,
            createdAt: Date(timeIntervalSince1970: 1_786_500_200)
        )
        let sibling = revealJob(
            id: "44444444-4444-4444-8444-444444444444",
            ownerID: ownerID,
            createdAt: Date(timeIntervalSince1970: 1_786_500_201)
        )
        try await store.create(first, sourceBytes: source)
        try await store.create(sibling, sourceBytes: source)

        let owner = recordingOwner(ownerID)
        let selectedValue = try await store.claimNextReveal(owner: owner)
        let selected = try XCTUnwrap(selectedValue)
        let statesBeforeAcknowledgement = try await store.jobs(ownerID: ownerID).map(\.revealState)

        XCTAssertEqual(
            statesBeforeAcknowledgement,
            [.queued, .queued],
            "selection alone must leave every same-authoritative-ID sibling pending acknowledgement"
        )

        try await store.acknowledgeReveal(
            id: selected.id,
            owner: owner,
            claimID: selected.claimID,
            authoritativeRideID: selected.authoritativeRideID
        )
        let restartedStore = FileRideUploadJobStore(rootURL: rootURL)
        let replay = try await restartedStore.claimNextReveal(owner: owner)
        let statesAfterAcknowledgement = try await restartedStore.jobs(ownerID: ownerID)
            .map(\.revealState)

        XCTAssertNil(replay)
        XCTAssertEqual(statesAfterAcknowledgement, [.consumed, .consumed])
    }

    func testSameIDDifferentWalletsHoldIndependentActiveRevealClaims() async throws {
        let store = FileRideUploadJobStore(rootURL: rootURL)
        let ownerA = RecordingOwner(id: ownerID, wallet: "wallet-a")
        let ownerB = RecordingOwner(id: ownerID, wallet: "wallet-b")
        let jobA = revealJob(
            id: "55555555-5555-4555-8555-555555555555",
            ownerID: ownerID,
            ownerWallet: ownerA.wallet,
            authoritativeRideID: "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
            createdAt: Date(timeIntervalSince1970: 1_786_500_300)
        )
        let jobB = revealJob(
            id: "66666666-6666-4666-8666-666666666666",
            ownerID: ownerID,
            ownerWallet: ownerB.wallet,
            authoritativeRideID: "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb",
            createdAt: Date(timeIntervalSince1970: 1_786_500_301)
        )
        try await store.create(jobA, sourceBytes: source)
        try await store.create(jobB, sourceBytes: source)

        let claimA = try await store.claimNextReveal(owner: ownerA)
        let claimB = try await store.claimNextReveal(owner: ownerB)

        XCTAssertEqual(claimA?.id, jobA.id)
        XCTAssertEqual(claimB?.id, jobB.id)

        let restarted = FileRideUploadJobStore(rootURL: rootURL)
        let recoveredA = try await restarted.claimNextReveal(owner: ownerA)
        let recoveredB = try await restarted.claimNextReveal(owner: ownerB)
        XCTAssertEqual(recoveredA, claimA)
        XCTAssertEqual(recoveredB, claimB)
    }

    func testSameIDDifferentWalletConsumptionMarkersAreIndependent() async throws {
        let store = FileRideUploadJobStore(rootURL: rootURL)
        let ownerA = RecordingOwner(id: ownerID, wallet: "wallet-a")
        let ownerB = RecordingOwner(id: ownerID, wallet: "wallet-b")
        let sharedRideID = "cccccccc-cccc-4ccc-8ccc-cccccccccccc"
        let jobA = revealJob(
            id: "77777777-7777-4777-8777-777777777777",
            ownerID: ownerID,
            ownerWallet: ownerA.wallet,
            authoritativeRideID: sharedRideID,
            createdAt: Date(timeIntervalSince1970: 1_786_500_400)
        )
        try await store.create(jobA, sourceBytes: source)
        let claimAValue = try await store.claimNextReveal(owner: ownerA)
        let claimA = try XCTUnwrap(claimAValue)
        try await store.acknowledgeReveal(
            id: claimA.id,
            owner: ownerA,
            claimID: claimA.claimID,
            authoritativeRideID: claimA.authoritativeRideID
        )

        let jobB = revealJob(
            id: "88888888-8888-4888-8888-888888888888",
            ownerID: ownerID,
            ownerWallet: ownerB.wallet,
            authoritativeRideID: sharedRideID,
            createdAt: Date(timeIntervalSince1970: 1_786_500_401)
        )
        try await store.create(jobB, sourceBytes: source)

        let claimB = try await store.claimNextReveal(owner: ownerB)
        let storedB = try await store.job(id: jobB.id, ownerID: ownerID)
        XCTAssertEqual(claimB?.id, jobB.id)
        XCTAssertEqual(storedB?.revealState, .queued)
    }

    private func revealJob(
        id: String,
        ownerID: String,
        ownerWallet: String? = nil,
        authoritativeRideID: String? = nil,
        createdAt: Date
    ) -> RideUploadJob {
        RideUploadJob(
            id: id,
            ownerID: ownerID,
            ownerWallet: ownerWallet ?? "wallet-\(ownerID)",
            fileName: "Sunday Ride.gpx",
            fileType: "gpx",
            fileHash: FileRideUploadJobStore.sha256(source),
            fileSize: source.count,
            sourceFileName: "source.gpx",
            localSummary: LocalRideSummary(
                startedAt: Date(timeIntervalSince1970: 1_786_499_000),
                distanceM: 12_345,
                elevationM: 456,
                durationS: 3_210
            ),
            createdAt: createdAt,
            updatedAt: createdAt,
            phase: .final,
            attemptedServerHandoff: true,
            signedURL: nil,
            signedURLExpiresAt: nil,
            serverRideID: authoritativeRideID ?? self.authoritativeRideID,
            authoritativeStatus: "completed",
            attemptCount: 1,
            nextRetryAt: nil,
            lastError: nil,
            canRetry: false,
            revealState: .queued,
            reveal: RevealData(
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

    private func recordingOwner(_ ownerID: String) -> RecordingOwner {
        RecordingOwner(id: ownerID, wallet: "wallet-\(ownerID)")
    }
}
