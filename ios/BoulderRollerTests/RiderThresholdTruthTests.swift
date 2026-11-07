import XCTest
@testable import BoulderRoller

final class RiderThresholdTruthTests: XCTestCase {
    private let now = ISO8601DateFormatter().date(from: "2026-08-24T18:00:00Z")!

    private func defaults() -> UserDefaults {
        UserDefaults(suiteName: "RiderThresholdTruthTests-\(UUID().uuidString)")!
    }

    private func established(
        lastRaisedAt: String? = nil,
        pending: ThresholdPendingMondayResponse? = nil
    ) -> ThresholdResponse {
        ThresholdResponse(
            contractVersion: "threshold.v1",
            state: "established",
            currentW: 245,
            establishedAt: "2026-08-17T12:00:00Z",
            lastRaisedAt: lastRaisedAt,
            pendingMonday: pending,
            sealingInProgress: false
        )
    }

    func testSuccessfulEstablishingIsDistinctFromUnavailable() {
        let defaults = defaults()
        XCTAssertNil(RiderThresholdStore.display(riderID: "rider", now: now, defaults: defaults))

        let response = ThresholdResponse(
            contractVersion: "threshold.v1",
            state: "establishing",
            currentW: nil,
            establishedAt: nil,
            lastRaisedAt: nil,
            pendingMonday: nil,
            sealingInProgress: false
        )
        XCTAssertTrue(RiderThresholdStore.save(response, riderID: "rider", now: now, defaults: defaults))
        XCTAssertEqual(
            RiderThresholdStore.display(riderID: "rider", now: now, defaults: defaults),
            .establishing
        )
        XCTAssertNil(
            RiderThresholdStore.zoneThreshold(
                riderID: "rider", now: now, defaults: defaults
            )
        )
    }

    func testFirstEverValueUsesEstablishedAnchorNotLastRaised() {
        let display = RiderThresholdStore.display(response: established(), now: now)
        XCTAssertEqual(
            display,
            .established(
                currentW: 245,
                establishedISO: "2026-08-17T12:00:00Z",
                lastRaisedISO: nil,
                pendingW: nil,
                pendingEffectiveISO: nil
            )
        )
    }

    func testOnlyFutureScheduledRaiseBecomesSurfaceDenominator() {
        let defaults = defaults()
        let response = established(
            pending: ThresholdPendingMondayResponse(
                watts: 251,
                effectiveAt: "2026-08-31T12:00:00Z"
            )
        )
        XCTAssertTrue(RiderThresholdStore.save(response, riderID: "rider", now: now, defaults: defaults))
        XCTAssertEqual(
            RiderThresholdStore.zoneThreshold(
                riderID: "rider", now: now, defaults: defaults
            ),
            ThresholdSurfaceValue(watts: 251, isPending: true)
        )
    }

    func testScheduledPromotionPreservesTheLastRaisedFact() {
        let response = ThresholdResponse(
            contractVersion: "threshold.v1",
            state: "established",
            currentW: 245,
            establishedAt: "2026-08-10T12:00:00Z",
            lastRaisedAt: "2026-08-17T12:00:00Z",
            pendingMonday: ThresholdPendingMondayResponse(
                watts: 251,
                effectiveAt: "2026-08-31T12:00:00Z"
            ),
            sealingInProgress: false
        )

        XCTAssertEqual(
            RiderThresholdStore.display(response: response, now: now),
            .established(
                currentW: 245,
                establishedISO: "2026-08-10T12:00:00Z",
                lastRaisedISO: "2026-08-17T12:00:00Z",
                pendingW: 251,
                pendingEffectiveISO: "2026-08-31T12:00:00Z"
            )
        )
        XCTAssertEqual(Format.monthDay(response.lastRaisedAt), "Aug 17")
    }

    func testMaterializedPendingMondayExpiresAtItsEffectiveBoundary() throws {
        let effectiveAt = try XCTUnwrap(
            ISO8601DateFormatter().date(from: "2026-08-31T12:00:00Z")
        )
        let beforeBoundary = effectiveAt.addingTimeInterval(-1)
        let response = established(
            pending: ThresholdPendingMondayResponse(
                watts: 251,
                effectiveAt: "2026-08-31T12:00:00Z"
            )
        )
        let display = try XCTUnwrap(
            RiderThresholdStore.display(response: response, now: beforeBoundary)
        )

        XCTAssertEqual(display.pendingWatts(at: beforeBoundary), 251)
        XCTAssertNil(display.pendingWatts(at: effectiveAt))
    }

    func testLastRaisedMustFollowEstablishment() {
        XCTAssertNil(
            RiderThresholdStore.display(
                response: established(lastRaisedAt: "2026-08-17T12:00:00Z"),
                now: now
            )
        )
    }

    func testPastMondayPreservesSealedCurrentWhileTheSealRefreshes() {
        let defaults = defaults()
        let response = established(
            pending: ThresholdPendingMondayResponse(
                watts: 251,
                effectiveAt: "2026-08-24T12:00:00Z"
            )
        )
        XCTAssertTrue(RiderThresholdStore.save(response, riderID: "rider", now: now, defaults: defaults))
        XCTAssertEqual(
            RiderThresholdStore.zoneThreshold(
                riderID: "rider", now: now, defaults: defaults
            ),
            ThresholdSurfaceValue(watts: 245, isPending: false)
        )
        XCTAssertEqual(
            RiderThresholdStore.display(riderID: "rider", now: now, defaults: defaults),
            .established(
                currentW: 245,
                establishedISO: "2026-08-17T12:00:00Z",
                lastRaisedISO: nil,
                pendingW: nil,
                pendingEffectiveISO: nil
            )
        )
    }

    func testMalformedAuthorityAndCrossRiderReadsFailClosed() {
        let defaults = defaults()
        let malformed = ThresholdResponse(
            contractVersion: "threshold.v1",
            state: "established",
            currentW: 245,
            establishedAt: nil,
            lastRaisedAt: nil,
            pendingMonday: nil,
            sealingInProgress: false
        )
        XCTAssertFalse(RiderThresholdStore.save(malformed, riderID: "one", now: now, defaults: defaults))
        XCTAssertNil(RiderThresholdStore.load(riderID: "one", now: now, defaults: defaults))

        XCTAssertTrue(RiderThresholdStore.save(established(), riderID: "one", now: now, defaults: defaults))
        XCTAssertNil(RiderThresholdStore.load(riderID: "two", now: now, defaults: defaults))
    }
}
