import XCTest
@testable import BoulderRoller

final class TrainingMetricsTruthTests: XCTestCase {
    @MainActor
    func testOwnerWeeksSendsDeviceZoneAndInitializesMissingPreference() async throws {
        let requests = TrainingClockRequests()
        let credentials = TrainingClockCredentials()
        let zone = TimeZone.current.identifier
        let configuration = URLSessionConfiguration.ephemeral
        configuration.protocolClasses = [TrainingClockURLProtocol.self]
        let client = APIClient(
            configuration: configuration,
            sessionCredentials: credentials,
            requestObserver: { requests.record($0) },
            accountMutationPermitted: { owner in
                // Evaluate the real fence policy against an unfenced test
                // account, independent of keychain and persisted session state.
                AccountDeletionLocalFence.permitsAccountWork(
                    owner: owner,
                    sessionRecords: [],
                    capabilityState: .none
                )
            }
        )
        try await client.adoptSession(AuthTokenResponse(userId: "training-owner", wallet: "training-wallet", accessToken: "synthetic-access", accessExpiresAt: nil, refreshToken: "synthetic-refresh", refreshExpiresAt: nil))
        // This awaits both the preference attempt and the weeks response; the
        // synchronous request observer is complete when the call returns.
        let result = try await client.trainingWeeks()
        XCTAssertTrue(result.isEmpty)
        let recorded = requests.snapshot
        XCTAssertEqual(recorded.compactMap { $0.url?.path }, ["/analytics/timezone", "/analytics/weeks"])
        let preference = try XCTUnwrap(recorded.first)
        XCTAssertEqual(preference.httpMethod, "POST")
        let body = try JSONSerialization.jsonObject(with: XCTUnwrap(preference.httpBody)) as? [String: String]
        XCTAssertEqual(body?["timezone"], zone)
        let weeks = try XCTUnwrap(recorded.last)
        XCTAssertEqual(weeks.httpMethod, "GET")
        XCTAssertEqual(URLComponents(url: try XCTUnwrap(weeks.url), resolvingAgainstBaseURL: false)?.queryItems?.first(where: { $0.name == "timezone" })?.value, zone)
        XCTAssertEqual(try credentials.readRefreshToken(), "synthetic-refresh")
    }
    func testMovingTimeAndZonesComeFromServer() throws {
        let decoder = JSONDecoder()
        decoder.keyDecodingStrategy = .convertFromSnakeCase
        let metrics = try decoder.decode(RideTrainingMetrics.self, from: Data(#"{"engine_version":2,"elapsed_s":900,"moving_s":0,"power_zone_s":[12,0,0,0,0,0,0],"power_zone_ranges_w":[[0,137],[138,187]],"threshold":{"value":251,"estimate":true,"basis":"threshold_cp_3_7_15_v1"}}"#.utf8))
        XCTAssertEqual(metrics.movingS, 0)
        XCTAssertEqual(metrics.elapsedS, 900)
        XCTAssertEqual(metrics.powerZoneRangesW?[1][0], 138)
        XCTAssertEqual(metrics.threshold?.estimate, true)
    }
    func testUnavailableTrainingDoesNotInventNumbers() throws {
        let metrics = try JSONDecoder().decode(RideTrainingMetrics.self, from: Data("{}".utf8))
        XCTAssertNil(metrics.movingS)
        XCTAssertNil(metrics.powerCurveW)
    }
    func testWeekTotalsAreBackendValuesAndUnknownTimeStaysAbsent() throws {
        let decoder = JSONDecoder()
        decoder.keyDecodingStrategy = .convertFromSnakeCase
        let week = try decoder.decode(TrainingWeek.self, from: Data(#"{"week_start":"2026-10-05","distance_m":1234,"duration_s":null,"climb_m":90,"partial":true}"#.utf8))
        XCTAssertEqual(week.distanceM, 1234)
        XCTAssertEqual(week.climbM, 90)
        XCTAssertNil(week.durationS)
        XCTAssertTrue(week.partial)
    }
}

private final class TrainingClockRequests: @unchecked Sendable {
    private let lock = NSLock()
    private var requests: [URLRequest] = []

    func record(_ request: URLRequest) {
        lock.withLock { requests.append(request) }
    }

    var snapshot: [URLRequest] {
        lock.withLock { requests }
    }
}

private final class TrainingClockCredentials: SessionCredentialStore, @unchecked Sendable {
    private var token: String?
    func readRefreshToken() throws -> String? { token }
    func saveRefreshToken(_ token: String) throws { self.token = token }
    func deleteRefreshToken() throws { token = nil }
}

private final class TrainingClockURLProtocol: URLProtocol {
    override class func canInit(with request: URLRequest) -> Bool { true }
    override class func canonicalRequest(for request: URLRequest) -> URLRequest { request }
    override func startLoading() {
        let body = request.url!.path.hasSuffix("/analytics/timezone") ? "{}" : "[]"
        client?.urlProtocol(self, didReceive: HTTPURLResponse(url: request.url!, statusCode: 200, httpVersion: nil, headerFields: ["Content-Type": "application/json"])!, cacheStoragePolicy: .notAllowed)
        client?.urlProtocol(self, didLoad: Data(body.utf8))
        client?.urlProtocolDidFinishLoading(self)
    }
    override func stopLoading() {}
}
