import XCTest
@testable import BoulderRoller

final class WkgPrivacyTests: XCTestCase {
    static let settingsJSON = """
    {"contractVersion":"privacy.v2","profileVisibility":"public",
     "defaultRideVisibility":"public","defaultMapVisibility":"hide_start_end",
     "defaultMapHideStartM":200,"defaultMapHideEndM":200,"privacyZoneCount":0,
     "privacyZonesLoaded":true}
    """

    private func settings(_ extra: String = "") throws -> PrivacySettings {
        let json = String(Self.settingsJSON.dropLast()) + extra + "}"
        let decoder = JSONDecoder()
        decoder.keyDecodingStrategy = .convertFromSnakeCase
        return try decoder.decode(PrivacySettings.self, from: Data(json.utf8))
    }

    func testWkgDefaultsOffAndDecodesBothWireSpellings() throws {
        XCTAssertFalse(try settings().shareWkg)
        XCTAssertFalse(try settings(#", "shareWkg":null"#).shareWkg)
        XCTAssertFalse(try settings(#", "shareWkg":false"#).shareWkg)
        XCTAssertTrue(try settings(#", "shareWkg":true"#).shareWkg)
        XCTAssertTrue(try settings(#", "share_wkg":true"#).shareWkg)
        XCTAssertThrowsError(try settings(#", "shareWkg":"true"#))
    }

    @MainActor
    private func loadedModel(sharing: Bool = false) -> PrivacyModel {
        let model = PrivacyModel()
        model.cachedSettings = { nil }
        model.cachedZones = { nil }
        var initial = try! settings()
        initial.shareWkg = sharing
        model.state = .loaded(initial, PrivacyZonesList(zones: [], maxZones: 5))
        return model
    }

    @MainActor
    func testSwitchSavesBothDirectionsAndAdoptsServerResponse() async throws {
        let model = loadedModel()
        let base = try settings()
        var requested: [Bool] = []
        model.putShareWkg = { value in
            requested.append(value)
            var updated = base
            updated.shareWkg = value
            return updated
        }
        XCTAssertEqual(model.currentShareWkg, false)
        let enabled = await model.setShareWkg(true)
        XCTAssertNil(enabled)
        XCTAssertEqual(model.currentShareWkg, true)
        let disabled = await model.setShareWkg(false)
        XCTAssertNil(disabled)
        XCTAssertEqual(model.currentShareWkg, false)
        XCTAssertEqual(requested, [true, false])

        // A successful response is authoritative even if it differs from
        // the requested value. The control never assumes an echo.
        model.putShareWkg = { _ in base }
        _ = await model.setShareWkg(true)
        XCTAssertEqual(model.currentShareWkg, false)
    }

    @MainActor
    func testFailedOptInAndOptOutKeepConfirmedStateAndReturnError() async {
        for prior in [false, true] {
            let model = loadedModel(sharing: prior)
            model.putShareWkg = { _ in
                throw APIError.http(status: 503, code: nil, message: "Please retry.")
            }
            let failure = await model.setShareWkg(!prior)
            XCTAssertEqual(failure, "Please retry.")
            XCTAssertEqual(model.currentShareWkg, prior)
            XCTAssertFalse(model.isSavingSettings)
        }
    }

    @MainActor
    func testUnavailableScreenNeverWrites() async {
        let model = PrivacyModel()
        var calls = 0
        model.putShareWkg = { _ in
            calls += 1
            throw APIError.notAuthenticated
        }
        let failure = await model.setShareWkg(true)
        XCTAssertEqual(failure, "Privacy is unavailable.")
        XCTAssertNil(model.currentShareWkg)
        XCTAssertEqual(calls, 0)
    }

    @MainActor
    func testPendingSaveDoesNotOptimisticallyChangeConsentOrAllowAnotherWrite() async throws {
        let model = loadedModel()
        let started = expectation(description: "save started")
        var finish: CheckedContinuation<PrivacySettings, Error>?
        var calls = 0
        model.putShareWkg = { _ in
            calls += 1
            return try await withCheckedThrowingContinuation { continuation in
                finish = continuation
                started.fulfill()
            }
        }
        let saving = Task { await model.setShareWkg(true) }
        await fulfillment(of: [started], timeout: 2)
        XCTAssertTrue(model.isSavingSettings)
        XCTAssertEqual(model.currentShareWkg, false)
        _ = await model.setShareWkg(true)
        model.putDefaultVisibility = { _ in
            XCTFail("audience and W/kg saves must not race")
            return try self.settings()
        }
        _ = await model.setDefaultVisibility(.followers)
        XCTAssertEqual(calls, 1)
        finish?.resume(returning: try settings(#", "shareWkg":true"#))
        _ = await saving.value
        XCTAssertEqual(model.currentShareWkg, true)
        XCTAssertFalse(model.isSavingSettings)
    }

    @MainActor
    func testOlderRefreshCannotUndoSuccessfulConsentSave() async throws {
        let model = loadedModel()
        let started = expectation(description: "refresh started")
        var finish: CheckedContinuation<PrivacySettings, Error>?
        let old = try settings()
        let saved = try settings(#", "shareWkg":true"#)
        model.fetchSettings = {
            try await withCheckedThrowingContinuation { continuation in
                finish = continuation
                started.fulfill()
            }
        }
        model.fetchZones = { PrivacyZonesList(zones: [], maxZones: 5) }
        model.putShareWkg = { _ in saved }
        let refresh = Task { await model.load() }
        await fulfillment(of: [started], timeout: 2)
        _ = await model.setShareWkg(true)
        finish?.resume(returning: old)
        await refresh.value
        XCTAssertEqual(model.currentShareWkg, true)
    }

    @MainActor
    func testLatePrivacyGetCannotRevokeConfirmedOptInOnReopen() async throws {
        let started = expectation(description: "old GET started")
        let gate = WkgReadGate(started: started)
        DelayedWkgURLProtocol.gate = gate
        defer { DelayedWkgURLProtocol.gate = nil }
        let configuration = URLSessionConfiguration.ephemeral
        configuration.protocolClasses = [DelayedWkgURLProtocol.self]
        let client = APIClient(
            configuration: configuration, sessionCredentials: WkgCredentials(),
            accountMutationPermitted: { _ in true }
        )
        try await client.adoptSession(AuthTokenResponse(
            userId: "wkg-race", wallet: "wkg-race-wallet",
            accessToken: "synthetic-access", accessExpiresAt: nil,
            refreshToken: "synthetic-refresh", refreshExpiresAt: nil
        ))
        let oldRead = Task { try await client.privacySettings() }
        await fulfillment(of: [started], timeout: 2)
        let updated = try await client.updateShareWkg(true)
        XCTAssertTrue(updated.shareWkg)

        // A reopened room must not join the pre-save GET still in flight.
        let freshReadFinished = expectation(description: "new GET is independent")
        let freshRead = Task {
            defer { freshReadFinished.fulfill() }
            return try await client.privacySettings()
        }
        await fulfillment(of: [freshReadFinished], timeout: 2)
        gate.releaseOldRead()
        let fresh = try await freshRead.value
        XCTAssertTrue(fresh.shareWkg)
        do {
            _ = try await oldRead.value
            XCTFail("a read across a privacy mutation must be discarded")
        } catch is CancellationError {
            // The room retains its confirmed value on a superseded read.
        }
        let reopened = try await client.privacySettings(policy: .cacheOnly)
        XCTAssertTrue(reopened.shareWkg, "late old data must not repaint sharing as off")
    }

    @MainActor
    func testReopenedScreenCannotPublishConsentWhileWriteIsPending() async throws {
        let started = expectation(description: "PUT pending")
        let gate = WkgReadGate(started: started, heldMethod: "PUT")
        DelayedWkgURLProtocol.gate = gate
        defer { DelayedWkgURLProtocol.gate = nil }
        let configuration = URLSessionConfiguration.ephemeral
        configuration.protocolClasses = [DelayedWkgURLProtocol.self]
        let client = APIClient(
            configuration: configuration, sessionCredentials: WkgCredentials(),
            accountMutationPermitted: { _ in true }
        )
        try await client.adoptSession(AuthTokenResponse(
            userId: "wkg-pending", wallet: "wkg-pending-wallet",
            accessToken: "synthetic-access", accessExpiresAt: nil,
            refreshToken: "synthetic-refresh", refreshExpiresAt: nil
        ))
        let write = Task { try await client.updateShareWkg(false) }
        await fulfillment(of: [started], timeout: 2)
        do {
            _ = try await client.privacySettings()
            XCTFail("a reopened room must stay unavailable until consent is confirmed")
        } catch is CancellationError {}
        gate.releaseOldRead()
        _ = try await write.value
        let confirmed = try await client.privacySettings(policy: .cacheOnly)
        XCTAssertFalse(confirmed.shareWkg)
    }

    @MainActor
    func testOldAccountWriteCannotClearNewAccountConsentCache() async throws {
        let started = expectation(description: "old account PUT started")
        let gate = WkgReadGate(started: started, heldMethod: "PUT")
        DelayedWkgURLProtocol.gate = gate
        defer { DelayedWkgURLProtocol.gate = nil }
        let configuration = URLSessionConfiguration.ephemeral
        configuration.protocolClasses = [DelayedWkgURLProtocol.self]
        let client = APIClient(
            configuration: configuration, sessionCredentials: WkgCredentials(),
            accountMutationPermitted: { _ in true }
        )
        func session(_ id: String) -> AuthTokenResponse {
            AuthTokenResponse(
                userId: id, wallet: "\(id)-wallet",
                accessToken: "synthetic-\(id)", accessExpiresAt: nil,
                refreshToken: "synthetic-refresh-\(id)", refreshExpiresAt: nil
            )
        }
        try await client.adoptSession(session("old"))
        let oldWrite = Task { try await client.updateShareWkg(false) }
        await fulfillment(of: [started], timeout: 2)
        try await client.adoptSession(session("new"))
        let current = try await client.privacySettings()
        XCTAssertTrue(current.shareWkg)
        gate.releaseOldRead()
        do {
            _ = try await oldWrite.value
            XCTFail("an old-account write must not return across an account change")
        } catch {
            // The existing session boundary rejects the old request.
        }
        let cached = try await client.privacySettings(policy: .cacheOnly)
        XCTAssertTrue(cached.shareWkg)
    }

    @MainActor
    func testApiUsesExistingPrivacyEndpointWithOnlyTheBooleanPreference() async throws {
        let requests = WkgRequests()
        let configuration = URLSessionConfiguration.ephemeral
        configuration.protocolClasses = [WkgURLProtocol.self]
        let client = APIClient(
            configuration: configuration,
            sessionCredentials: WkgCredentials(),
            requestObserver: { requests.record($0) },
            accountMutationPermitted: { owner in
                AccountDeletionLocalFence.permitsAccountWork(
                    owner: owner, sessionRecords: [], capabilityState: .none
                )
            }
        )
        try await client.adoptSession(AuthTokenResponse(
            userId: "wkg-fixture", wallet: "wkg-fixture-wallet",
            accessToken: "synthetic-access", accessExpiresAt: nil,
            refreshToken: "synthetic-refresh", refreshExpiresAt: nil
        ))
        for value in [true, false] {
            _ = try await client.updateShareWkg(value)
        }
        let recorded = requests.snapshot
        XCTAssertEqual(recorded.count, 2)
        for (request, value) in zip(recorded, [true, false]) {
            XCTAssertEqual(request.url?.path, "/privacy/settings")
            XCTAssertEqual(request.httpMethod, "PUT")
            let body = try JSONSerialization.jsonObject(with: XCTUnwrap(request.httpBody)) as? [String: Bool]
            XCTAssertEqual(body, ["share_wkg": value])
        }
    }
}

private final class WkgRequests: @unchecked Sendable {
    private let lock = NSLock()
    private var requests: [URLRequest] = []
    func record(_ request: URLRequest) { lock.withLock { requests.append(request) } }
    var snapshot: [URLRequest] { lock.withLock { requests } }
}

private final class WkgCredentials: SessionCredentialStore, @unchecked Sendable {
    private var token: String?
    func readRefreshToken() throws -> String? { token }
    func saveRefreshToken(_ token: String) throws { self.token = token }
    func deleteRefreshToken() throws { token = nil }
}

private final class WkgURLProtocol: URLProtocol {
    override class func canInit(with request: URLRequest) -> Bool { true }
    override class func canonicalRequest(for request: URLRequest) -> URLRequest { request }
    override func startLoading() {
        client?.urlProtocol(self, didReceive: HTTPURLResponse(
            url: request.url!, statusCode: 200, httpVersion: nil,
            headerFields: ["Content-Type": "application/json"]
        )!, cacheStoragePolicy: .notAllowed)
        client?.urlProtocol(self, didLoad: Data(WkgPrivacyTests.settingsJSON.utf8))
        client?.urlProtocolDidFinishLoading(self)
    }
    override func stopLoading() {}
}

private final class WkgReadGate: @unchecked Sendable {
    private let lock = NSLock()
    private let started: XCTestExpectation
    private let heldMethod: String
    private var pending: DelayedWkgURLProtocol?
    private var heldFirstRead = false

    init(started: XCTestExpectation, heldMethod: String = "GET") {
        self.started = started
        self.heldMethod = heldMethod
    }

    func receive(_ request: DelayedWkgURLProtocol) {
        let hold = lock.withLock {
            if request.request.httpMethod == heldMethod, !heldFirstRead {
                heldFirstRead = true
                pending = request
                return true
            }
            return false
        }
        if hold { started.fulfill() } else { request.respond(sharing: true) }
    }

    func releaseOldRead() {
        let request = lock.withLock {
            defer { pending = nil }
            return pending
        }
        request?.respond(sharing: false)
    }
}

private final class DelayedWkgURLProtocol: URLProtocol {
    static var gate: WkgReadGate?
    override class func canInit(with request: URLRequest) -> Bool { true }
    override class func canonicalRequest(for request: URLRequest) -> URLRequest { request }
    override func startLoading() { Self.gate?.receive(self) }
    override func stopLoading() {}

    func respond(sharing: Bool) {
        let body = String(WkgPrivacyTests.settingsJSON.dropLast()) + ",\"shareWkg\":\(sharing)}"
        client?.urlProtocol(self, didReceive: HTTPURLResponse(
            url: request.url!, statusCode: 200, httpVersion: nil,
            headerFields: ["Content-Type": "application/json"]
        )!, cacheStoragePolicy: .notAllowed)
        client?.urlProtocol(self, didLoad: Data(body.utf8))
        client?.urlProtocolDidFinishLoading(self)
    }
}
