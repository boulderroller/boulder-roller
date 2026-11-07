import XCTest
@testable import BoulderRoller

final class RideUploadBackgroundSchedulingPolicyTests: XCTestCase {
    func testOnlyAutomaticallyAdvanceablePhasesRequestBackgroundReconciliation() {
        let expected: [RideUploadPhase: Bool] = [
            .awaitingPrivacyReview: false,
            .queued: true,
            .initializing: true,
            .transferring: true,
            .completing: true,
            .processing: true,
            .retryable: true,
            .waitingForAuthentication: false,
            .underReview: false,
            .failed: false,
            .final: false,
        ]

        for (phase, isExpectedToAdvance) in expected {
            XCTAssertEqual(
                RideUploadBackgroundSchedulingPolicy.isAutomaticallyAdvanceable(phase),
                isExpectedToAdvance,
                "Unexpected background scheduling decision for \(phase.rawValue)"
            )
        }
    }
}
