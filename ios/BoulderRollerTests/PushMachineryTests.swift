import Foundation
import UserNotifications
import XCTest
@testable import BoulderRoller

/// Push machinery to the key boundary (bead `boulderroller-v2-odmi6.8`):
/// exactly two deep-link categories, fail-closed parsing, and the ratified
/// ask-timing — never at launch, only at the moment a settlement or
/// displacement becomes possible, never re-asked after denial.
final class PushMachineryTests: XCTestCase {

    override func setUp() {
        super.setUp()
        AccountDeletionSessionRecordStore.clear()
        CachedRiderStore.clear()
    }

    override func tearDown() {
        AccountDeletionSessionRecordStore.clear()
        CachedRiderStore.clear()
        super.tearDown()
    }

    // MARK: - Deep-link parsing (the two categories, fail closed)

    func testSettlementPayloadRoutesToSettlements() {
        let link = PushDeepLink.parse(userInfo: [
            "aps": ["alert": ["title": "x"]],
            "br": ["category": "settlement"],
        ])
        XCTAssertEqual(link, .settlements)
    }

    func testDisplacementPayloadRoutesToClimbSheet() {
        let link = PushDeepLink.parse(userInfo: [
            "aps": ["alert": ["title": "x"]],
            "br": ["category": "displacement", "climb_id": "climb-17"],
        ])
        XCTAssertEqual(link, .climb("climb-17"))
    }

    /// Numeric climb ids survive JSON number decoding.
    func testDisplacementNumericClimbIDIsStringified() {
        let link = PushDeepLink.parse(userInfo: [
            "br": ["category": "displacement", "climb_id": 42],
        ])
        XCTAssertEqual(link, .climb("42"))
    }

    func testUnknownCategoryFailsClosed() {
        XCTAssertNil(PushDeepLink.parse(userInfo: [
            "br": ["category": "kudos"],
        ]))
        XCTAssertNil(PushDeepLink.parse(userInfo: [
            "br": ["category": "ride_finalized"],
        ]))
    }

    func testDisplacementWithoutClimbIDFailsClosed() {
        XCTAssertNil(PushDeepLink.parse(userInfo: [
            "br": ["category": "displacement"],
        ]))
        XCTAssertNil(PushDeepLink.parse(userInfo: [
            "br": ["category": "displacement", "climb_id": ""],
        ]))
        XCTAssertNil(PushDeepLink.parse(userInfo: [
            "br": ["category": "displacement", "climb_id": NSNull()],
        ]))
    }

    func testMissingEnvelopeFailsClosed() {
        XCTAssertNil(PushDeepLink.parse(userInfo: [:]))
        XCTAssertNil(PushDeepLink.parse(userInfo: ["aps": ["alert": "hi"]]))
        XCTAssertNil(PushDeepLink.parse(userInfo: ["br": "settlement"]))
        XCTAssertNil(PushDeepLink.parse(userInfo: ["br": [String: Any]()]))
    }

    // MARK: - Ask policy (ratified choreography)

    func testAskHappensOnlyAtARatifiedTriggerWhileUndetermined() {
        XCTAssertTrue(PushAskPolicy.shouldRequestAuthorization(
            trigger: .firstDepositConfirmed, authorizationStatus: .notDetermined
        ))
        XCTAssertTrue(PushAskPolicy.shouldRequestAuthorization(
            trigger: .firstLeaderboardEntry, authorizationStatus: .notDetermined
        ))
    }

    /// No trigger, no ask — launch, sign-in, and every other moment are
    /// structurally incapable of prompting.
    func testNoTriggerNeverAsks() {
        XCTAssertFalse(PushAskPolicy.shouldRequestAuthorization(
            trigger: nil, authorizationStatus: .notDetermined
        ))
    }

    /// Denial is respected: the policy never re-prompts a denied rider.
    func testDenialIsNeverReAsked() {
        XCTAssertFalse(PushAskPolicy.shouldRequestAuthorization(
            trigger: .firstDepositConfirmed, authorizationStatus: .denied
        ))
        XCTAssertFalse(PushAskPolicy.shouldRequestAuthorization(
            trigger: .firstLeaderboardEntry, authorizationStatus: .denied
        ))
    }

    func testGrantedIsNotReAsked() {
        XCTAssertFalse(PushAskPolicy.shouldRequestAuthorization(
            trigger: .firstDepositConfirmed, authorizationStatus: .authorized
        ))
    }

    /// Session-start token replay happens only for already-granted riders.
    func testSessionStartRegistrationOnlyWhenPreviouslyAuthorized() {
        XCTAssertTrue(PushAskPolicy.shouldRegisterAtSessionStart(authorizationStatus: .authorized))
        XCTAssertTrue(PushAskPolicy.shouldRegisterAtSessionStart(authorizationStatus: .provisional))
        XCTAssertFalse(PushAskPolicy.shouldRegisterAtSessionStart(authorizationStatus: .notDetermined))
        XCTAssertFalse(PushAskPolicy.shouldRegisterAtSessionStart(authorizationStatus: .denied))
    }

    func testApnsEnvironmentFollowsBuildConfiguration() {
        XCTAssertEqual(PushAskPolicy.apnsEnvironment(isDebugBuild: true), "sandbox")
        XCTAssertEqual(PushAskPolicy.apnsEnvironment(isDebugBuild: false), "production")
    }

    // MARK: - Router

    @MainActor
    func testRouterHoldsLinkUntilConsumedAndDropsGarbage() {
        let router = PushRouter(admitsRoute: { true })

        router.route(userInfo: ["br": ["category": "unknown_thing"]])
        XCTAssertNil(router.pending, "unroutable pushes must not park a broken link")

        router.route(userInfo: ["br": ["category": "settlement"]])
        XCTAssertEqual(router.pending, .settlements)

        // Consumption is the presenter's job; simulate it.
        router.pending = nil
        XCTAssertNil(router.pending)
    }

    @MainActor
    func testRouterRefusesNotificationAdmissionAcrossDeletionBoundary() {
        let router = PushRouter(admitsRoute: { false })

        router.route(userInfo: ["br": ["category": "settlement"]])

        XCTAssertNil(router.pending)
    }

    @MainActor
    func testRouterAdmitsSignedInDifferentOwnerDespiteRetainedDeletionFence() {
        let deletingOwner = RecordingOwner(id: "deleting-owner", wallet: "deleting-wallet")
        let activeOwner = RecordingOwner(id: "active-owner", wallet: "active-wallet")
        let records = [
            AccountDeletionSessionRecord(
                state: .pending,
                owner: deletingOwner,
                savedStatusRemoved: true
            )
        ]
        let router = PushRouter(admitsRoute: {
            AccountDeletionLocalFence.permitsCachedOwnerAccountWork(
                cachedOwner: activeOwner,
                sessionRecords: records,
                capabilityState: .none
            )
        })

        router.route(userInfo: ["br": ["category": "settlement"]])

        XCTAssertEqual(router.pending, .settlements)
    }
}
