import Foundation
import Testing
@testable import BoulderRoller

/// Granularity 12: typed errors preserve status and retry metadata, and the
/// classification's retry semantics are truthful — retry offered only where
/// an unchanged retry can actually work.
struct ErrorTaxonomyTests {
    private func body(_ detail: String) -> Data {
        Data(#"{"detail": "\#(detail)"}"#.utf8)
    }

    // MARK: httpError mapping (the exact production decoder)

    @Test func maintenanceCarriesServerMessageAndTiming() {
        let error = APIClient.httpError(
            status: 503,
            body: body("System under maintenance: back soon"),
            retryAfterHeader: "120"
        )
        guard case let .maintenance(message, retryAfterS) = error else {
            Issue.record("503 must classify as maintenance, got \(error)")
            return
        }
        #expect(message == "System under maintenance: back soon")
        #expect(retryAfterS == 120)
        #expect(APIFailureClass.classify(error) == .maintenance(retryAfterS: 120))
        #expect(APIFailureClass.classify(error).isRetryable)
        #expect(APIFailureClass.classify(error).retryAfterS == 120)
    }

    @Test func rateLimitCarriesRetryAfter() {
        let error = APIClient.httpError(
            status: 429, body: body("Rate limit exceeded"), retryAfterHeader: "7"
        )
        guard case let .rateLimited(_, retryAfterS) = error else {
            Issue.record("429 must classify as rateLimited, got \(error)")
            return
        }
        #expect(retryAfterS == 7)
        #expect(APIFailureClass.classify(error).isRetryable)
        #expect(APIFailureClass.classify(error).retryAfterS == 7)
    }

    @Test func staleClientBlocksRetry() {
        for error in [
            APIClient.httpError(status: 426, body: body("Update required")),
            APIClient.httpError(
                status: 400,
                body: Data(#"{"detail": {"code": "upgrade_required"}}"#.utf8)
            ),
        ] {
            guard case .staleClient = error else {
                Issue.record("upgrade signals must classify as staleClient, got \(error)")
                return
            }
            #expect(APIFailureClass.classify(error) == .staleClient)
            #expect(!APIFailureClass.classify(error).isRetryable)
        }
    }

    @Test func plainStatusesKeepTheirClassAndRetrySemantics() {
        let serverError = APIClient.httpError(status: 500, body: Data())
        #expect(APIFailureClass.classify(serverError) == .serverError)
        #expect(APIFailureClass.classify(serverError).isRetryable)

        let notFound = APIClient.httpError(status: 404, body: body("Not Found"))
        #expect(APIFailureClass.classify(notFound) == .client)
        #expect(!APIFailureClass.classify(notFound).isRetryable)

        // The 409 upload-conflict contract is untouched by the taxonomy.
        let conflict = APIClient.httpError(
            status: 409,
            body: Data(
                #"{"detail": {"code": "duplicate", "existing_ride_id": "r1"}}"#.utf8
            )
        )
        guard case .uploadConflict = conflict else {
            Issue.record("409 with existing ride must stay uploadConflict")
            return
        }
        #expect(APIFailureClass.classify(conflict) == .client)
    }

    // MARK: Transport and unknown shapes

    @Test func offlineTransportIsRetryable() {
        for code in [URLError.notConnectedToInternet, .networkConnectionLost, .timedOut] {
            let cls = APIFailureClass.classify(URLError(code))
            #expect(cls == .offline)
            #expect(cls.isRetryable)
        }
    }

    @Test func unknownShapesNeedReviewNotFakeSuccess() {
        #expect(APIFailureClass.classify(APIError.decoding("Ride: gibberish")) == .needsReview)
        #expect(!APIFailureClass.classify(APIError.decoding("x")).isRetryable)
        struct Mystery: Error {}
        #expect(APIFailureClass.classify(Mystery()) == .needsReview)
    }

    @Test func signedOutOnlyRemediesThroughSignIn() {
        let cls = APIFailureClass.classify(APIError.notAuthenticated)
        #expect(cls == .notAuthenticated)
        #expect(!cls.isRetryable)
    }
}
