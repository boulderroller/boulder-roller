import Foundation

enum APIError: LocalizedError, Sendable {
    case http(status: Int, code: String?, message: String?)
    case stage1OperationPending(operationID: String, reference: String)
    case uploadConflict(
        status: Int,
        code: String?,
        message: String?,
        existingRideID: String,
        existingStatus: String?
    )
    /// 503 — the server said so and its message (server-authored copy) plus
    /// any Retry-After timing travel with the error (granularity 12).
    case maintenance(message: String?, retryAfterS: Double?)
    /// 429 — retry is real but only after the server's stated interval.
    case rateLimited(message: String?, retryAfterS: Double?)
    /// 426 or an explicit upgrade code — this build can no longer perform
    /// the write; retrying the same request is a lie.
    case staleClient(message: String?)
    case decoding(String)
    case notAuthenticated

    var errorDescription: String? {
        switch self {
        case .stage1OperationPending: return "Pending"
        case let .http(status, code, message):
            return message ?? code ?? "Request failed (\(status))"
        case let .uploadConflict(status, code, message, _, _):
            return message ?? code ?? "Upload conflict (\(status))"
        case let .maintenance(message, _):
            return message ?? "Request failed (503)"
        case let .rateLimited(message, _):
            return message ?? "Request failed (429)"
        case let .staleClient(message):
            return message ?? "Request failed (426)"
        case let .decoding(detail):
            return "Unexpected response: \(detail)"
        case .notAuthenticated:
            return "Signed out"
        }
    }
}

/// How one relaunch resume attempt ended (bead `boulderroller-v2-f4acp.2.9`).
enum SessionResumeOutcome: Equatable, Sendable {
    /// No refresh token stored — a genuinely signed-out device.
    case noStoredSession
    /// New tokens adopted; the session is live.
    case resumed
    /// The server definitively ended the stored session.
    case rejected(SessionEndReason)
    /// Authentication ended because the account is pending deletion,
    /// anonymized, or its identity authority is unavailable.
    case accountDeletion(AccountDeletionSessionState)
    /// The server could not be consulted (offline, outage). The stored
    /// session survives untouched.
    case transient
}

extension Notification.Name {
    /// Posted exactly when a definitive server rejection kills the session
    /// mid-use (the 401→refresh→rejected path). Carries
    /// `userInfo["reason"] = SessionEndReason.rawValue`.
    static let brSessionInvalidated = Notification.Name("br.session.invalidated")
    /// Posted when an in-use session reaches a deletion-specific 401.
    /// Carries `userInfo["state"] = AccountDeletionSessionState.rawValue`.
    static let brAccountDeletionSessionState = Notification.Name(
        "br.account-deletion.session-state"
    )
}

/// Production API client. Mirrors web/portal/src/lib/api.ts: bearer access
/// token (in memory), refresh token in the Keychain, snake_case wire format.
///
/// Cookie policy: **no cookie jar.** The backend prefers a `refresh_token`
/// cookie over the request body when both arrive; iOS persisted cookies
/// asynchronously while the Keychain persisted synchronously, so a process
/// kill could leave the two stores holding different rotation generations —
/// the stale cookie then won on the server, refresh answered
/// `refresh_rotated`, and the old client wiped the session and landed the
/// rider on onboarding (bead `boulderroller-v2-c6l2l` note 11). The Keychain
/// is the single source of session truth; every refresh ships it in the body.
// (APIClient follows CachePolicy below.)

/// Read policy for GETs: `.network` fetches and stores; `.cacheOnly` answers
/// from the session cache or throws `CacheMiss` (stale-while-revalidate:
/// surfaces hydrate with `.cacheOnly`, then refresh with `.network`).
enum CachePolicy: Sendable {
    case network
    case cacheOnly
}

struct CacheMiss: Error {}

actor APIClient {
    static let shared = APIClient()

    private let baseURL = URL(string: AppConfig.apiBaseURL)!
    private let session: URLSession
    private let sessionCredentials: any SessionCredentialStore
    /// Internal request-construction probe used by contract tests before
    /// URLSession may convert an encoded body into an opaque stream.
    private let requestObserver: (@Sendable (URLRequest) -> Void)?
    /// Internal single-flight probe used by contract tests to wait until a
    /// second caller is actually awaiting the existing refresh task.
    private let refreshFlightJoinObserver: (@Sendable () -> Void)?
    /// Async seam around the durable refusal witness. Production writes the
    /// real emergency fence; tests can hold this boundary to prove that an
    /// account replacement during preparation cannot be torn down by A.
    private let accountDeletionEmergencyFenceArm:
        @Sendable (String) async throws -> Void
    /// Production admission for authenticated account mutations. Kept as a
    /// dependency so race-focused tests can isolate bearer-generation behavior
    /// from an unsigned simulator's intentionally unavailable Keychain.
    private let accountMutationPermitted:
        @Sendable (RecordingOwner?) -> Bool
    private var accessToken: String?
    private var accessTokenLifetime: SessionClockPolicy.TokenLifetime?
    /// Exact identity bound to the active bearer generation. Refresh may
    /// rotate token bytes, but it may never silently replace this owner.
    private var authenticatedOwner: RecordingOwner?
    /// A server-returned generation whose Keychain write was temporarily
    /// unavailable. It may become active only after the same bytes are durable.
    private var pendingSession: PendingSession?
    /// Prepared durably before any deletion-specific refusal is returned or
    /// posted. AppSession consumes the same opaque ID when it persists the
    /// exact owner/state journal.
    private var deletionRefusalContext: AccountDeletionRefusalContext?
    private let clockPolicy = SessionClockPolicy()
    private struct RefreshFlightResult: Sendable {
        let outcome: SessionRefreshOutcome
        let continuationGeneration: UInt64
        let preparedRefusal: AccountDeletionRefusalContext?
    }
    private struct RefreshFlight {
        let id: UUID
        let task: Task<RefreshFlightResult, Never>
    }
    private var refreshFlight: RefreshFlight?
    /// Invalidates refresh flights and cached reads that crossed an account
    /// boundary while the actor was reentrant on network I/O.
    private var sessionGeneration: UInt64 = 0
    /// Identical GETs in flight share one task, so a warmer and a tap for
    /// the same page never fetch twice (grout pass, 2026-08-21).
    private var inFlightGETs: [String: Task<Any, Error>] = [:]
    /// Consent snapshots are fenced across writes and account changes in
    /// this actor. A late GET must not cache or coalesce pre-save consent.
    private var privacySettingsRevision: UInt64 = 0
    private var privacySettingsSnapshot: (session: UInt64, settings: PrivacySettings)?
    private var pendingPrivacySettingsWrite: UInt64?

    private let decoder: JSONDecoder = {
        let d = JSONDecoder()
        d.keyDecodingStrategy = .convertFromSnakeCase
        return d
    }()

    private let encoder: JSONEncoder = {
        let e = JSONEncoder()
        e.keyEncodingStrategy = .convertToSnakeCase
        return e
    }()

    init(
        configuration: URLSessionConfiguration = .default,
        sessionCredentials: any SessionCredentialStore = KeychainSessionCredentialStore(),
        requestObserver: (@Sendable (URLRequest) -> Void)? = nil,
        refreshFlightJoinObserver: (@Sendable () -> Void)? = nil,
        accountDeletionEmergencyFenceArm:
            @escaping @Sendable (String) async throws -> Void = { recoveryID in
                try AccountDeletionEmergencyFenceStore.armRequired(
                    recoveryID: recoveryID
                )
            },
        accountMutationPermitted:
            @escaping @Sendable (RecordingOwner?) -> Bool = {
                AccountDeletionLocalFence.permitsAccountWork(owner: $0)
            }
    ) {
        let config = configuration
        // Single source of session truth: the Keychain. See the type comment.
        config.httpCookieStorage = nil
        config.httpShouldSetCookies = false
        config.httpCookieAcceptPolicy = .never
        config.timeoutIntervalForRequest = 30
        session = URLSession(configuration: config)
        self.sessionCredentials = sessionCredentials
        self.requestObserver = requestObserver
        self.refreshFlightJoinObserver = refreshFlightJoinObserver
        self.accountDeletionEmergencyFenceArm = accountDeletionEmergencyFenceArm
        self.accountMutationPermitted = accountMutationPermitted
    }

    // MARK: Session state

    var isAuthenticated: Bool { accessToken != nil }

    /// Token material shared by sign-in and refresh response shapes. Exact
    /// owner correlation is carried separately so token-contract equality
    /// remains independent of identity metadata.
    struct SessionTokens: Equatable {
        let accessToken: String
        let accessExpiresAt: String?
        let refreshToken: String

        init(_ response: AuthTokenResponse) {
            accessToken = response.accessToken
            accessExpiresAt = response.accessExpiresAt
            refreshToken = response.refreshToken
        }

        init(_ response: RefreshTokenResponse) {
            accessToken = response.accessToken
            accessExpiresAt = response.accessExpiresAt
            refreshToken = response.refreshToken
        }
    }

    private struct PendingSession {
        let tokens: SessionTokens
        let owner: RecordingOwner?
    }

    func adoptSession(_ tokens: AuthTokenResponse) throws {
        try adoptSession(
            SessionTokens(tokens),
            owner: RecordingOwner(id: tokens.userId, wallet: tokens.wallet),
            startsNewIdentity: true
        )
    }

    private func adoptSession(
        _ tokens: SessionTokens,
        owner: RecordingOwner?,
        startsNewIdentity: Bool
    ) throws {
        do {
            try sessionCredentials.saveRefreshToken(tokens.refreshToken)
        } catch {
            pendingSession = PendingSession(tokens: tokens, owner: owner)
            throw error
        }
        pendingSession = nil
        if startsNewIdentity {
            invalidateSessionWork()
        }
        // A successful token adoption starts a new authenticated generation.
        // Drop only the in-memory owner correlation; any unresolved emergency
        // witness remains durable until AppSession clears its exact row.
        deletionRefusalContext = nil
        accessToken = tokens.accessToken
        accessTokenLifetime = Self.lifetime(fromExpiresAt: tokens.accessExpiresAt)
        authenticatedOwner = owner
    }

    /// Server-declared access expiry, anchored to the local receipt instant.
    /// Absent or unparseable expiry → no local belief; the 401 path owns
    /// correctness (SessionClockPolicy rule 2).
    private static func lifetime(fromExpiresAt raw: String?) -> SessionClockPolicy.TokenLifetime? {
        guard let raw else { return nil }
        let parser = ISO8601DateFormatter()
        parser.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
        let fallback = ISO8601DateFormatter()
        guard let expiresAt = parser.date(from: raw) ?? fallback.date(from: raw) else {
            return nil
        }
        return .init(expiresAt: expiresAt, receivedAt: .now)
    }

    func clearSession(cancelRefreshFlight: Bool = true) {
        invalidateSessionWork(cancelRefreshFlight: cancelRefreshFlight)
        accessToken = nil
        accessTokenLifetime = nil
        authenticatedOwner = nil
        pendingSession = nil
        try? sessionCredentials.deleteRefreshToken()
    }

    func clearSessionRequired() async throws {
        invalidateSessionWork()
        accessToken = nil
        accessTokenLifetime = nil
        authenticatedOwner = nil
        pendingSession = nil
        try sessionCredentials.deleteRefreshToken()
        guard try sessionCredentials.readRefreshToken() == nil else {
            throw SessionCredentialStoreError.invalidData
        }
        await MainActor.run { ResponseCache.shared.clear() }
    }

    /// Account deletion boundary without dropping the still-needed bearer
    /// session. Cancels and epochs every ordinary cached read immediately;
    /// status calls opt out of that cache and retain their own capability.
    func advanceAccountBoundary() async {
        invalidateSessionWork()
        await MainActor.run { ResponseCache.shared.clear() }
    }

    private func invalidateSessionWork(cancelRefreshFlight: Bool = true) {
        sessionGeneration &+= 1
        if cancelRefreshFlight {
            refreshFlight?.task.cancel()
            refreshFlight = nil
        }
        for task in inFlightGETs.values { task.cancel() }
        inFlightGETs.removeAll()
        privacySettingsRevision &+= 1
        privacySettingsSnapshot = nil
        pendingPrivacySettingsWrite = nil
    }

    /// A deletion-specific auth refusal must leave only the durable refresh
    /// credential needed for AppSession's journal-before-teardown contract.
    /// The rejected access generation and every volatile continuation are no
    /// longer authorized account state; retaining any of them can let a later
    /// resume bypass the server refusal while the required journal is retried.
    private func invalidateVolatileSessionForAccountDeletion(
        requiredSessionGeneration: UInt64? = nil,
        cancelRefreshFlight: Bool = true
    ) async -> UInt64? {
        if let requiredSessionGeneration,
           sessionGeneration != requiredSessionGeneration {
            return nil
        }
        invalidateSessionWork(cancelRefreshFlight: cancelRefreshFlight)
        let continuationGeneration = sessionGeneration
        accessToken = nil
        accessTokenLifetime = nil
        authenticatedOwner = nil
        pendingSession = nil
        await MainActor.run { ResponseCache.shared.clear() }
        guard sessionGeneration == continuationGeneration else { return nil }
        return continuationGeneration
    }

    func accountDeletionRefusalContext() async -> AccountDeletionRefusalContext? {
        deletionRefusalContext
    }

    private struct PreparedAccountDeletionRefusal {
        let context: AccountDeletionRefusalContext
        /// Generation still authorized to publish this refusal. When durable
        /// witness storage fails, verified credential teardown advances the
        /// original generation exactly once before routing may continue.
        let continuationGeneration: UInt64?
    }

    private func discardPreparedAccountDeletionRefusal(
        _ context: AccountDeletionRefusalContext
    ) {
        try? AccountDeletionEmergencyFenceStore.clearRequired(
            recoveryID: context.recoveryID
        )
        if !AccountDeletionEmergencyFenceStore.records.contains(where: {
            $0.recoveryID == context.recoveryID
        }), deletionRefusalContext?.recoveryID == context.recoveryID {
            deletionRefusalContext = nil
        }
    }

    private func prepareAccountDeletionRefusal(
        attemptedOwner: RecordingOwner?,
        attemptedWallet: String?,
        requiredSessionGeneration: UInt64? = nil
    ) async -> PreparedAccountDeletionRefusal? {
        if let requiredSessionGeneration,
           sessionGeneration != requiredSessionGeneration {
            return nil
        }
        if let existing = deletionRefusalContext,
           existing.attemptedOwner == attemptedOwner,
           existing.attemptedWallet == attemptedWallet,
           AccountDeletionEmergencyFenceStore.records.contains(where: {
               $0.recoveryID == existing.recoveryID
           }) {
            return PreparedAccountDeletionRefusal(
                context: existing,
                continuationGeneration: requiredSessionGeneration
            )
        }
        let context = AccountDeletionRefusalContext(
            recoveryID: UUID().uuidString.lowercased(),
            attemptedOwner: attemptedOwner,
            attemptedWallet: attemptedWallet
        )
        var continuationGeneration = requiredSessionGeneration
        do {
            try await accountDeletionEmergencyFenceArm(context.recoveryID)
        } catch {
            if let requiredSessionGeneration,
               sessionGeneration != requiredSessionGeneration {
                // A test seam or a partially failed store may already have
                // written this exact witness. Remove only A's recovery ID.
                discardPreparedAccountDeletionRefusal(context)
                return nil
            }
            // If the non-personal witness cannot be written, verified removal
            // of the refresh credential is the only cold-relaunch fail-closed
            // fallback available at this layer.
            let generationBeforeFallback = sessionGeneration
            try? await clearSessionRequired()
            if requiredSessionGeneration != nil {
                let fallbackGeneration = generationBeforeFallback &+ 1
                guard sessionGeneration == fallbackGeneration else {
                    discardPreparedAccountDeletionRefusal(context)
                    return nil
                }
                continuationGeneration = fallbackGeneration
            }
        }
        if let continuationGeneration,
           sessionGeneration != continuationGeneration {
            discardPreparedAccountDeletionRefusal(context)
            return nil
        }
        deletionRefusalContext = context
        return PreparedAccountDeletionRefusal(
            context: context,
            continuationGeneration: continuationGeneration
        )
    }

    /// Route only the backend's stable deletion vocabulary. Verification
    /// calls use the attempted wallet; authenticated middleware carries the
    /// exact owner pinned to the rejected bearer. Anonymous or unrelated 401s
    /// keep their original HTTP taxonomy.
    private func routeAccountDeletionRefusal(
        _ error: Error,
        attemptedOwner: RecordingOwner?,
        attemptedWallet: String?,
        requiredSessionGeneration: UInt64? = nil
    ) async throws -> Never {
        guard case let .accountDeletion(state) =
            SessionRefreshClassifier.classify(error)
        else { throw error }
        guard requiredSessionGeneration == nil
                || sessionGeneration == requiredSessionGeneration
        else { throw APIError.notAuthenticated }

        guard let prepared = await prepareAccountDeletionRefusal(
            attemptedOwner: attemptedOwner,
            attemptedWallet: attemptedWallet,
            requiredSessionGeneration: requiredSessionGeneration
        ) else { throw APIError.notAuthenticated }
        let context = prepared.context
        // Emergency-fence fallback can suspend. A different rider may be
        // adopted while it does, so stale verification work must recheck its
        // epoch before it can invalidate or notify the replacement session.
        if let continuationGeneration = prepared.continuationGeneration,
           sessionGeneration != continuationGeneration {
            discardPreparedAccountDeletionRefusal(context)
            throw APIError.notAuthenticated
        }
        guard await invalidateVolatileSessionForAccountDeletion(
            requiredSessionGeneration: prepared.continuationGeneration
        ) != nil else {
            discardPreparedAccountDeletionRefusal(context)
            throw APIError.notAuthenticated
        }
        NotificationCenter.default.post(
            name: .brAccountDeletionSessionState,
            object: self,
            userInfo: [
                "state": state.rawValue,
                "recovery_id": context.recoveryID,
                "attempted_owner_id": context.attemptedOwner?.id as Any,
                "attempted_owner_wallet": context.attemptedOwner?.wallet as Any,
                "attempted_wallet": context.attemptedWallet as Any,
            ]
        )
        throw APIError.notAuthenticated
    }

    static func deviceID() -> String {
        let key = "br_device_id"
        if let existing = UserDefaults.standard.string(forKey: key) { return existing }
        let fresh = UUID().uuidString
        UserDefaults.standard.set(fresh, forKey: key)
        return fresh
    }

    static func rotateDeviceIDRequired() throws {
        let prior = UserDefaults.standard.string(forKey: "br_device_id")
        UserDefaults.standard.removeObject(forKey: "br_device_id")
        let replacement = deviceID()
        guard !replacement.isEmpty, replacement != prior else {
            throw AccountDeletionLocalCleanupError.verificationFailed
        }
    }

    /// Resume a previous session from the stored refresh token.
    ///
    /// The stored session is cleared **only** on a definitive server
    /// rejection. Offline, timeouts, and server incidents leave the Keychain
    /// untouched so the very next launch (or foreground) can succeed — a
    /// transient failure must never become a silent dead session.
    func resumeSession() async -> SessionResumeOutcome {
        // Foreground startup and BG reconciliation may both ask to resume.
        // Once this process already owns a live access token, a later caller
        // must reuse it; rotating again can replay a just-retired token if the
        // previous generation has not reached durable storage yet.
        if accessToken != nil { return .resumed }
        if let pendingSession {
            do {
                try adoptSession(
                    pendingSession.tokens,
                    owner: pendingSession.owner,
                    startsNewIdentity: true
                )
                return .resumed
            } catch {
                return .transient
            }
        }
        let storedRefreshToken: String?
        do {
            storedRefreshToken = try sessionCredentials.readRefreshToken()
        } catch {
            return .transient
        }
        let hasStored = storedRefreshToken != nil
        #if DEBUG
        print("[Session] resumeSession begins (stored refresh token: \(hasStored))")
        #endif
        guard clockPolicy.shouldAttemptResume(
            hasStoredRefreshToken: hasStored
        ) else { return .noStoredSession }
        switch await refreshAccessToken() {
        case .refreshed: return .resumed
        case let .rejected(reason): return .rejected(reason)
        case let .accountDeletion(state): return .accountDeletion(state)
        case .transient: return .transient
        }
    }

    /// Single-flight refresh. Concurrent 401s coalesce onto one in-flight
    /// attempt; the Keychain token is deleted only on `.rejected`.
    ///
    /// Rotation-race retry: `refresh_rotated` (409) is the backend's benign
    /// race signal (bead i15a.5 — "retry with the latest token"). If storage
    /// holds a NEWER token than the one this flight presented (another local
    /// flight or device rotated first), one retry with the stored token
    /// recovers the session. Only when no newer token exists is the rotation
    /// an honest session loss.
    private func refreshAccessToken() async -> SessionRefreshOutcome {
        if let running = refreshFlight {
            refreshFlightJoinObserver?()
            let result = await running.task.value
            guard sessionGeneration == result.continuationGeneration else {
                if let context = result.preparedRefusal {
                    discardPreparedAccountDeletionRefusal(context)
                }
                return .transient
            }
            return result.outcome
        }
        let flightGeneration = sessionGeneration
        let flightOwner = authenticatedOwner
        let flightID = UUID()
        let task = Task<RefreshFlightResult, Never> {
            func result(
                _ outcome: SessionRefreshOutcome,
                generation: UInt64,
                refusal: AccountDeletionRefusalContext? = nil
            ) -> RefreshFlightResult {
                RefreshFlightResult(
                    outcome: outcome,
                    continuationGeneration: generation,
                    preparedRefusal: refusal
                )
            }
            var attempts = 0
            let initialToken: String?
            do {
                initialToken = try sessionCredentials.readRefreshToken()
            } catch {
                return result(.transient, generation: sessionGeneration)
            }
            guard let initialToken else {
                return result(.transient, generation: sessionGeneration)
            }
            var presented: String? = initialToken
            while true {
                attempts += 1
                do {
                    let body: [String: String?] = [
                        "device_id": Self.deviceID(),
                        "refresh_token": presented,
                    ]
                    let tokens: RefreshTokenResponse = try await request(
                        "POST", "/auth/refresh", jsonBody: body,
                        authenticated: false, retryOn401: false
                    )
                    guard sessionGeneration == flightGeneration,
                          !Task.isCancelled
                    else { return result(.transient, generation: sessionGeneration) }
                    if let flightOwner,
                       tokens.wallet != flightOwner.wallet {
                        // A refresh is token rotation, never an identity
                        // transition. Refuse a server shape that disagrees
                        // with (or omits) the exact owner's wallet.
                        return result(.transient, generation: sessionGeneration)
                    }
                    try adoptSession(
                        SessionTokens(tokens),
                        // A cold refresh has no exact owner authority. It
                        // remains ownerless until the bearer returns /users/me;
                        // CachedRiderStore is display continuity, never auth.
                        owner: flightOwner,
                        startsNewIdentity: false
                    )
                    #if DEBUG
                    print("[Session] refresh flight succeeded (attempt \(attempts))")
                    #endif
                    return result(.refreshed, generation: sessionGeneration)
                } catch {
                    let outcome = SessionRefreshClassifier.classify(error)
                    if case .rejected(.expired) = outcome,
                       case APIError.http(409, _, _) = error,
                       attempts < 2
                    {
                        do {
                            let stored = try sessionCredentials.readRefreshToken()
                            if let stored, stored != presented {
                                presented = stored
                                continue
                            }
                        } catch {
                            return result(.transient, generation: sessionGeneration)
                        }
                    }
                    #if DEBUG
                    print("[Session] refresh flight failed (attempt \(attempts)): \(outcome)")
                    #endif
                    if case .accountDeletion = outcome {
                        // This preparation is part of the shared flight, not
                        // owner-only cleanup below. Every joiner therefore
                        // crosses the same durable witness barrier before it
                        // can post or return the deletion state.
                        guard let prepared = await prepareAccountDeletionRefusal(
                            attemptedOwner: flightOwner,
                            attemptedWallet: nil,
                            requiredSessionGeneration: flightGeneration
                        ) else {
                            return result(.transient, generation: sessionGeneration)
                        }
                        guard let invalidatedGeneration =
                            await invalidateVolatileSessionForAccountDeletion(
                                requiredSessionGeneration:
                                    prepared.continuationGeneration,
                                cancelRefreshFlight: false
                            )
                        else {
                            discardPreparedAccountDeletionRefusal(prepared.context)
                            return result(.transient, generation: sessionGeneration)
                        }
                        return result(
                            outcome,
                            generation: invalidatedGeneration,
                            refusal: prepared.context
                        )
                    }
                    if case .rejected = outcome,
                       sessionGeneration == flightGeneration {
                        clearSession(cancelRefreshFlight: false)
                    }
                    return result(outcome, generation: sessionGeneration)
                }
            }
        }
        refreshFlight = RefreshFlight(id: flightID, task: task)
        let result = await task.value
        if refreshFlight?.id == flightID { refreshFlight = nil }
        guard sessionGeneration == result.continuationGeneration else {
            if let context = result.preparedRefusal {
                discardPreparedAccountDeletionRefusal(context)
            }
            return .transient
        }
        return result.outcome
    }

    // MARK: Core request

    /// Immutable admission captured before an authenticated request can
    /// suspend. A refreshed bearer may replace `bearer` only while generation
    /// and owner remain identical; the final tuple is checked again at send.
    private struct AuthenticatedRequestAdmission: Equatable {
        let bearer: String
        let generation: UInt64
        let owner: RecordingOwner?
    }

    private var authenticatedRequestAdmission: AuthenticatedRequestAdmission? {
        guard let accessToken else { return nil }
        return AuthenticatedRequestAdmission(
            bearer: accessToken,
            generation: sessionGeneration,
            owner: authenticatedOwner
        )
    }

    private static func requiresAccountMutationAdmission(
        method: String,
        path: String,
        authenticated: Bool
    ) -> Bool {
        guard authenticated, method != "GET", method != "HEAD" else {
            return false
        }
        // The unconfirmed capability is deliberately durable before DELETE;
        // this one lifecycle commit must remain able to cross its own fence.
        return !(method == "DELETE" && path == "/compliance/account")
    }

    private func request<T: Decodable>(
        _ method: String,
        _ path: String,
        query: [URLQueryItem] = [],
        jsonBody: (some Encodable)? = Optional<Int>.none,
        rawBody: [String: Any?]? = nil,
        headers: [String: String] = [:],
        authenticated: Bool = true,
        retryOn401: Bool = true,
        cacheResponse: Bool = true,
        policy: CachePolicy = .network,
        requiredSessionOwner: RecordingOwner? = nil,
        requiredInitialAuthentication: AuthenticatedRequestAdmission? = nil
    ) async throws -> T {
        // Coalesce identical network GETs: the second caller awaits the
        // first caller's task instead of opening a duplicate request.
        if method == "GET", policy == .network, jsonBody == nil, rawBody == nil,
           headers.isEmpty, retryOn401, cacheResponse
        {
            let key = ResponseCache.key(path: path, query: query)
            if let running = inFlightGETs[key] {
                if let value = try await running.value as? T { return value }
            }
            let task = Task<Any, Error> {
                let value: T = try await self.performRequest(
                    method, path, query: query, jsonBody: jsonBody, rawBody: rawBody,
                    headers: headers, authenticated: authenticated,
                    retryOn401: retryOn401, cacheResponse: cacheResponse, policy: policy,
                    requiredSessionOwner: requiredSessionOwner,
                    requiredInitialAuthentication: requiredInitialAuthentication
                )
                return value
            }
            inFlightGETs[key] = task
            defer { inFlightGETs[key] = nil }
            guard let value = try await task.value as? T else {
                throw APIError.decoding("\(T.self): coalesced type mismatch")
            }
            return value
        }
        return try await performRequest(
            method, path, query: query, jsonBody: jsonBody, rawBody: rawBody,
            headers: headers, authenticated: authenticated,
            retryOn401: retryOn401, cacheResponse: cacheResponse, policy: policy,
            requiredSessionOwner: requiredSessionOwner,
            requiredInitialAuthentication: requiredInitialAuthentication
        )
    }

    private func performRequest<T: Decodable>(
        _ method: String,
        _ path: String,
        query: [URLQueryItem] = [],
        jsonBody: (some Encodable)? = Optional<Int>.none,
        rawBody: [String: Any?]? = nil,
        headers: [String: String] = [:],
        authenticated: Bool = true,
        retryOn401: Bool = true,
        cacheResponse: Bool = true,
        policy: CachePolicy = .network,
        requiredSessionOwner: RecordingOwner? = nil,
        requiredInitialAuthentication: AuthenticatedRequestAdmission? = nil
    ) async throws -> T {
        // Capture the bearer generation and exact owner before the first
        // possible suspension in this request.
        let initialAuthentication = authenticated ? authenticatedRequestAdmission : nil
        let requiresMutationAdmission = Self.requiresAccountMutationAdmission(
            method: method,
            path: path,
            authenticated: authenticated
        )
        if authenticated {
            guard let initialAuthentication else { throw APIError.notAuthenticated }
            if let requiredInitialAuthentication,
               initialAuthentication != requiredInitialAuthentication
            {
                throw APIError.notAuthenticated
            }
            if let requiredSessionOwner,
               initialAuthentication.owner != requiredSessionOwner
            {
                throw APIError.notAuthenticated
            }
            if requiresMutationAdmission,
               !accountMutationPermitted(initialAuthentication.owner) {
                throw APIError.notAuthenticated
            }
        }
        let responseCacheGeneration = sessionGeneration
        let responseCacheAccountBoundaryGeneration = await MainActor.run {
            ResponseCache.shared.accountBoundaryGeneration
        }
        if policy == .cacheOnly {
            if let cached = await MainActor.run(body: {
                ResponseCache.shared.value(T.self, path: path, query: query)
            }) {
                return cached
            }
            throw CacheMiss()
        }
        var components = URLComponents(
            url: baseURL.appending(path: path), resolvingAgainstBaseURL: false
        )!
        if !query.isEmpty { components.queryItems = query }
        var req = URLRequest(url: components.url!)
        req.httpMethod = method
        ClientContract.attach(to: &req)
        if let jsonBody {
            req.setValue("application/json", forHTTPHeaderField: "Content-Type")
            req.httpBody = try encoder.encode(jsonBody)
        } else if let rawBody {
            req.setValue("application/json", forHTTPHeaderField: "Content-Type")
            req.httpBody = try JSONSerialization.data(
                withJSONObject: rawBody.compactMapValues { $0 }, options: []
            )
        }
        for (name, value) in headers {
            req.setValue(value, forHTTPHeaderField: name)
        }
        var sendingAuthentication: AuthenticatedRequestAdmission?
        if authenticated {
            // Clock-skew rule: local expiry belief may trigger an early
            // refresh, never veto a request. A transient refresh failure
            // falls through to the attempt; the 401 path owns correctness.
            if retryOn401,
               clockPolicy.shouldProactivelyRefresh(accessTokenLifetime, now: .now)
            {
                _ = await refreshAccessToken()
            }
            guard let initialAuthentication,
                  let currentAuthentication = authenticatedRequestAdmission,
                  currentAuthentication.generation == initialAuthentication.generation,
                  currentAuthentication.owner == initialAuthentication.owner
            else { throw APIError.notAuthenticated }
            if let requiredSessionOwner,
               currentAuthentication.owner != requiredSessionOwner
            {
                throw APIError.notAuthenticated
            }
            sendingAuthentication = currentAuthentication
            req.setValue(
                "Bearer \(currentAuthentication.bearer)",
                forHTTPHeaderField: "Authorization"
            )
        }

        requestObserver?(req)
        // Destructive admission is revalidated immediately before URLSession
        // gains the first opportunity to put bytes on the wire.
        if authenticated {
            guard authenticatedRequestAdmission == sendingAuthentication else {
                throw APIError.notAuthenticated
            }
        }
        if requiresMutationAdmission,
           !accountMutationPermitted(sendingAuthentication?.owner) {
            throw APIError.notAuthenticated
        }
        let (data, response) = try await session.data(for: req)
        let status = (response as? HTTPURLResponse)?.statusCode ?? 0
        guard !authenticated || responseCacheGeneration == sessionGeneration else {
            // The response belongs to a superseded bearer identity or account
            // boundary. It cannot publish lifecycle state, mutate caches, or
            // trigger a refresh under the replacement rider.
            throw APIError.notAuthenticated
        }

        if status == 401, authenticated, retryOn401 {
            let originalError = Self.httpError(status: status, body: data)
            if case .accountDeletion = SessionRefreshClassifier.classify(originalError) {
                // Authenticated middleware already resolved account lifecycle
                // authority. Arm the crash-safe witness and hand off that
                // state before a later refresh outage can downgrade it.
                try await routeAccountDeletionRefusal(
                    originalError,
                    attemptedOwner: sendingAuthentication?.owner,
                    attemptedWallet: nil,
                    requiredSessionGeneration: sendingAuthentication?.generation
                )
            }
            #if DEBUG
            print("[Session] 401 on \(path); attempting refresh")
            #endif
            switch await refreshAccessToken() {
            case .refreshed:
                return try await request(
                    method, path, query: query, jsonBody: jsonBody, rawBody: rawBody,
                    headers: headers, authenticated: authenticated,
                    retryOn401: false, cacheResponse: cacheResponse, policy: policy,
                    requiredSessionOwner: requiredSessionOwner,
                    requiredInitialAuthentication: requiredInitialAuthentication == nil
                        ? nil
                        : authenticatedRequestAdmission
                )
            case let .rejected(reason):
                // Forced logout: the server ended this session while the app
                // was signed in. Announce once; the AppSession bound to THIS
                // client performs the one clean sign-out (custody preserved).
                // `object: self` scopes delivery — listeners match identity.
                NotificationCenter.default.post(
                    name: .brSessionInvalidated,
                    object: self,
                    userInfo: ["reason": reason.rawValue]
                )
                throw APIError.notAuthenticated
            case let .accountDeletion(state):
                let context = deletionRefusalContext
                NotificationCenter.default.post(
                    name: .brAccountDeletionSessionState,
                    object: self,
                    userInfo: [
                        "state": state.rawValue,
                        "recovery_id": context?.recoveryID as Any,
                        "attempted_owner_id": context?.attemptedOwner?.id as Any,
                        "attempted_owner_wallet": context?.attemptedOwner?.wallet as Any,
                        "attempted_wallet": context?.attemptedWallet as Any,
                    ]
                )
                throw APIError.notAuthenticated
            case .transient:
                // The session was not judged — surface the real 401 rather
                // than pretending the rider signed out.
                throw originalError
            }
        }

        guard (200..<300).contains(status) else {
            if status >= 500 || status == 426 || status == 429 {
                BRLog.api.error("\(method) \(path) failed (\(status))")
            }
            throw Self.httpError(
                status: status,
                body: data,
                retryAfterHeader: (response as? HTTPURLResponse)?
                    .value(forHTTPHeaderField: "Retry-After")
            )
        }

        if method != "GET" {
            // A write drops every cached read under its resource so a
            // stale page cannot outlive the mutation.
            let prefix = ResponseCache.resourcePrefix(for: path)
            await MainActor.run { ResponseCache.shared.invalidate(pathPrefix: prefix) }
        }

        if T.self == EmptyResponse.self, data.isEmpty {
            return EmptyResponse() as! T
        }
        let decoded: T
        do {
            decoded = try decoder.decode(T.self, from: data)
        } catch {
            // A shape mismatch is as loud as a 5xx in the diagnostics
            // bundle — the type name only, never the payload.
            BRLog.api.error("\(method) \(path) decode failed (\(T.self))")
            throw APIError.decoding("\(T.self): \(error)")
        }
        if method == "GET", cacheResponse,
           responseCacheGeneration == sessionGeneration,
           !Task.isCancelled
        {
            await MainActor.run {
                ResponseCache.shared.store(
                    decoded,
                    path: path,
                    query: query,
                    ifAccountBoundaryGeneration: responseCacheAccountBoundaryGeneration
                )
            }
        }
        return decoded
    }

    private struct ErrorDetail {
        let code: String?
        let message: String?
        let existingRideID: String?
        let existingStatus: String?
    }

    /// The production HTTP failure decoder, exposed internally so contract
    /// tests exercise the exact same structured-detail path as live requests.
    static func httpError(
        status: Int, body: Data, retryAfterHeader: String? = nil
    ) -> APIError {
        let detail = errorDetail(from: body)
        if status == 409, detail.code == "stage1_operation_pending",
           let json = try? JSONSerialization.jsonObject(with: body) as? [String: Any],
           let fields = json["detail"] as? [String: Any],
           let operation = fields["operation_id"] as? String, !operation.isEmpty,
           let reference = fields["reference_id"] as? String,
           (try? Stage1Address.key(reference)) != nil {
            return .stage1OperationPending(operationID: operation, reference: reference)
        }
        if status == 409, let existingRideID = detail.existingRideID {
            return APIError.uploadConflict(
                status: status,
                code: detail.code,
                message: detail.message,
                existingRideID: existingRideID,
                existingStatus: detail.existingStatus
            )
        }
        let retryAfterS = retryAfterHeader.flatMap(Double.init)
        switch status {
        case 503:
            return APIError.maintenance(message: detail.message, retryAfterS: retryAfterS)
        case 429:
            return APIError.rateLimited(message: detail.message, retryAfterS: retryAfterS)
        case 426:
            return APIError.staleClient(message: detail.message)
        default:
            if detail.code == "upgrade_required" {
                return APIError.staleClient(message: detail.message)
            }
            return APIError.http(status: status, code: detail.code, message: detail.message)
        }
    }

    private static func errorDetail(from data: Data) -> ErrorDetail {
        guard let json = try? JSONSerialization.jsonObject(with: data) as? [String: Any]
        else {
            return ErrorDetail(
                code: nil,
                message: String(data: data.prefix(300), encoding: .utf8),
                existingRideID: nil,
                existingStatus: nil
            )
        }
        if let detail = json["detail"] as? [String: Any] {
            if let nested = detail["error"] as? [String: Any] {
                return ErrorDetail(
                    code: nested["code"] as? String,
                    message: nested["message"] as? String,
                    existingRideID: detail["existing_ride_id"] as? String,
                    existingStatus: detail["existing_status"] as? String
                )
            }
            return ErrorDetail(
                code: detail["error"] as? String ?? detail["code"] as? String,
                message: detail["message"] as? String,
                existingRideID: detail["existing_ride_id"] as? String,
                existingStatus: detail["existing_status"] as? String
            )
        }
        if let detail = json["detail"] as? String {
            return ErrorDetail(
                code: nil,
                message: detail,
                existingRideID: nil,
                existingStatus: nil
            )
        }
        return ErrorDetail(
            code: nil,
            message: nil,
            existingRideID: nil,
            existingStatus: nil
        )
    }

    struct EmptyResponse: Decodable {}

    // MARK: Auth

    func bootstrap() async throws -> AuthBootstrapState {
        try await request("GET", "/auth/bootstrap", authenticated: isAuthenticated)
    }

    func validateInvite(code: String, wallet: String? = nil) async throws -> InviteValidationResult {
        try await request(
            "POST", "/auth/invite/validate",
            rawBody: ["code": code, "wallet": wallet], authenticated: false
        )
    }

    func nonce(wallet: String) async throws -> NonceResponse {
        try await request(
            "POST", "/auth/nonce",
            rawBody: ["wallet": wallet, "device_id": Self.deviceID()], authenticated: false
        )
    }

    func verifySignature(
        wallet: String, signature: String, nonce: String, inviteCode: String?
    ) async throws -> AuthTokenResponse {
        let verificationGeneration = sessionGeneration
        do {
            let tokens: AuthTokenResponse = try await request(
                "POST", "/auth/verify",
                rawBody: [
                    "wallet": wallet, "signature": signature, "nonce": nonce,
                    "device_id": Self.deviceID(), "invite_code": inviteCode,
                ],
                authenticated: false
            )
            guard sessionGeneration == verificationGeneration else {
                throw APIError.notAuthenticated
            }
            try adoptSession(tokens)
            return tokens
        } catch {
            guard sessionGeneration == verificationGeneration else {
                throw APIError.notAuthenticated
            }
            try await routeAccountDeletionRefusal(
                error,
                attemptedOwner: nil,
                attemptedWallet: wallet,
                requiredSessionGeneration: verificationGeneration
            )
        }
    }

    func verifyPrivyToken(
        wallet: String, privyToken: String, inviteCode: String?
    ) async throws -> AuthTokenResponse {
        let verificationGeneration = sessionGeneration
        do {
            let tokens: AuthTokenResponse = try await request(
                "POST", "/auth/privy/verify",
                rawBody: [
                    "wallet": wallet, "privy_token": privyToken,
                    "device_id": Self.deviceID(), "invite_code": inviteCode,
                ],
                authenticated: false
            )
            guard sessionGeneration == verificationGeneration else {
                throw APIError.notAuthenticated
            }
            try adoptSession(tokens)
            return tokens
        } catch {
            guard sessionGeneration == verificationGeneration else {
                throw APIError.notAuthenticated
            }
            try await routeAccountDeletionRefusal(
                error,
                attemptedOwner: nil,
                attemptedWallet: wallet,
                requiredSessionGeneration: verificationGeneration
            )
        }
    }

    func logout() async {
        // No cookie jar: the refresh token must travel in the body or the
        // server cannot revoke this session's row.
        _ = try? await request(
            "POST", "/auth/logout",
            rawBody: [
                "device_id": Self.deviceID(),
                "refresh_token": try? sessionCredentials.readRefreshToken(),
            ],
            authenticated: false
        ) as EmptyResponse
        clearSession()
    }

    func me() async throws -> User {
        guard let initialAuthentication = authenticatedRequestAdmission else {
            throw APIError.notAuthenticated
        }
        let user: User = try await request(
            "GET", "/users/me",
            // The generic request layer cannot validate this identity against
            // the bearer owner. Do not publish it before the exact check below.
            cacheResponse: false,
            requiredInitialAuthentication: initialAuthentication
        )
        guard let currentAuthentication = authenticatedRequestAdmission,
              currentAuthentication.generation == initialAuthentication.generation,
              currentAuthentication.owner == initialAuthentication.owner
        else { throw APIError.notAuthenticated }
        let responseOwner = RecordingOwner(user: user)
        if let boundOwner = initialAuthentication.owner {
            guard responseOwner == boundOwner else {
                throw APIError.notAuthenticated
            }
        } else {
            // Cold refresh has token authority but no exact identity. Only a
            // live /users/me response under the unchanged bearer generation
            // may establish that owner; cached profile data never may.
            authenticatedOwner = responseOwner
        }
        return user
    }

    func threshold() async throws -> ThresholdResponse {
        try await request("GET", "/users/me/threshold")
    }

    /// The exact `PUT /users/me` body for one physiology edit. The live
    /// contract (bead `boulderroller-v2-coq7q`) treats an absent key as
    /// untouched and an explicit JSON null as a clear, so a clear must ship
    /// the key with `NSNull` — the raw-body path drops Swift nils.
    static func physiologyUpdateBody(weightKg: Double?? = nil) -> [String: Any] {
        var body: [String: Any] = [:]
        if let weightKg { body["weight_kg"] = weightKg.map { $0 as Any } ?? NSNull() }
        return body
    }

    /// Push one weight edit (kilograms) to the rider's profile.
    /// `nil` = explicit clear.
    func updateWeight(kg: Double?) async throws -> User {
        try await request(
            "PUT", "/users/me",
            rawBody: Self.physiologyUpdateBody(weightKg: .some(kg))
        )
    }

    /// Push the account's preferred units ("imperial" | "metric").
    func updatePreferredUnits(_ units: String) async throws -> User {
        try await request(
            "PUT", "/users/me",
            rawBody: ["units": units]
        )
    }

    /// Public rollout state. Clients consume this read model; they never infer
    /// action availability from a compiled stage or mutate rollout controls.
    func systemStatus() async throws -> SystemStatusResponse {
        try await request("GET", "/status", authenticated: false)
    }

    func trainingWeeks(policy: CachePolicy = .network) async throws -> [TrainingWeek] {
        let timezone = TimeZone.current.identifier
        if policy == .network {
            // Initialize absence only; the server preserves a configured zone.
            // A preference outage does not prevent the owner from reading weeks.
            let _: EmptyResponse? = try? await request("POST", "/analytics/timezone", rawBody: ["timezone": timezone])
        }
        return try await request("GET", "/analytics/weeks",
                                 query: [.init(name: "timezone", value: timezone)], policy: policy)
    }

    // MARK: Rides

    func rides(limit: Int = 20, offset: Int = 0, policy: CachePolicy = .network) async throws -> [Ride] {
        try await request(
            "GET", "/rides",
            query: [.init(name: "limit", value: "\(limit)"), .init(name: "offset", value: "\(offset)")],
            policy: policy
        )
    }

    /// The owner list is presently the only API projection with frozen
    /// counted distances and a trustworthy time origin. Paginate for an old
    /// imported ride rather than guessing offsets from the map track.
    func rideSpine(id: String) async throws -> RideSpineData? {
        guard let admission = authenticatedRequestAdmission else { throw APIError.notAuthenticated }
        var offset = 0
        while !Task.isCancelled {
            let page: [Ride] = try await request("GET", "/rides",
                query: [.init(name: "limit", value: "100"), .init(name: "offset", value: "\(offset)")],
                requiredInitialAuthentication: admission)
            guard let current = authenticatedRequestAdmission,
                  current.generation == admission.generation, current.owner == admission.owner
            else { throw APIError.notAuthenticated }
            if let ride = page.first(where: { $0.id == id }) {
                guard let profile = ride.elevationProfile, profile.count > 1 else { return nil }
                return RideSpineData(runs: [profile], spans: ride.countedSpans ?? [])
            }
            if page.count < 100 { return nil }
            offset += page.count
        }
        throw CancellationError()
    }

    /// Home first paint and its cursor pages share the backend's privacy-safe
    /// feed contract. The first page uses the aggregate endpoint; later pages
    /// use the narrow scope endpoint so scrolling does not refetch sidecars.
    func feedPage(
        scope: FeedScope,
        before: String? = nil,
        limit: Int = 20
    ) async throws -> FeedPage {
        if before == nil {
            let home: HomeFeedResponse = try await request(
                "GET", "/feed/home",
                query: [
                    .init(name: "scope", value: scope.rawValue),
                    .init(name: "limit", value: "\(limit)"),
                    .init(name: "sidecar_limit", value: "1"),
                ]
            )
            return home.feed
        }

        var query = [URLQueryItem(name: "limit", value: "\(limit)")]
        if let before { query.append(.init(name: "before", value: before)) }
        let path = scope == .following ? "/feed" : "/feed/global"
        return try await request("GET", path, query: query)
    }

    func rideDetail(id: String, policy: CachePolicy = .network) async throws -> RideDetailResponse {
        try await request("GET", "/rides/\(id)/detail", policy: policy)
    }

    func rideStatus(id: String) async throws -> RideStatus {
        try await request("GET", "/rides/\(id)/status")
    }

    func rideGps(id: String, policy: CachePolicy = .network) async throws -> GpsResponse {
        try await request("GET", "/rides/\(id)/gps", policy: policy)
    }

    func ridePatterns(id: String, policy: CachePolicy = .network) async throws -> PatternsResponse {
        try await request("GET", "/rides/\(id)/patterns", policy: policy)
    }

    func rideStream(
        id: String, kind: RideStreamKind, policy: CachePolicy = .network
    ) async throws -> RideStreamResponse {
        try await request(
            "GET", "/rides/\(id)/streams",
            query: [.init(name: "type", value: kind.rawValue)],
            policy: policy
        )
    }

    func rideOriginalFile(id: String) async throws -> RideOriginalFile {
        try await request("GET", "/rides/\(id)/original")
    }

    /// The download-URL truth gate, exposed for tests: https only, parseable
    /// only — an inaccessible original never becomes an empty file.
    static func validatedOriginalURL(_ original: RideOriginalFile) -> URL? {
        guard let url = URL(string: original.signedUrl), url.scheme == "https"
        else { return nil }
        return url
    }

    /// Deletion is claimed only on the server's explicit confirmation for
    /// exactly this ride.
    static func confirmsDeletion(_ response: RideDeleteResponse, id: String) -> Bool {
        response.status == "deleted" && response.rideId == id
    }

    func downloadOriginalRide(id: String) async throws -> (RideOriginalFile, Data) {
        let original = try await rideOriginalFile(id: id)
        guard let url = Self.validatedOriginalURL(original) else {
            throw APIError.decoding("Original ride URL is invalid")
        }
        let (data, response) = try await session.data(from: url)
        let status = (response as? HTTPURLResponse)?.statusCode ?? 0
        guard (200..<300).contains(status) else {
            throw APIError.http(status: status, code: nil, message: "Original ride file is unavailable")
        }
        return (original, data)
    }

    func deleteRide(id: String) async throws {
        let response: RideDeleteResponse = try await request("DELETE", "/rides/\(id)")
        guard Self.confirmsDeletion(response, id: id) else {
            throw APIError.decoding("Ride deletion was not confirmed")
        }
    }

    // MARK: Climbs

    func climb(id: String, policy: CachePolicy = .network) async throws -> Climb {
        try await request("GET", "/climbs/\(id)", policy: policy)
    }

    func climbVaultDetail(vaultId: Int, policy: CachePolicy = .network) async throws -> VaultClimbDetail {
        try await request("GET", "/vaults/\(vaultId)", policy: policy)
    }

    func myClimbResults(
        vaultId: Int, limit: Int = 50, policy: CachePolicy = .network
    ) async throws -> VaultEffortHistoryResponse {
        try await request(
            "GET", "/vaults/\(vaultId)/my-completions",
            query: [.init(name: "limit", value: "\(limit)")],
            policy: policy
        )
    }

    /// Ratified canon climbs inside a bounding box — the recording screen's
    /// climb-recognition source. bbox: min_lon,min_lat,max_lon,max_lat.
    func climbs(bbox: String, limit: Int = 50, policy: CachePolicy = .network) async throws -> ClimbListResponse {
        try await request(
            "GET", "/climbs/list",
            query: [
                .init(name: "bbox", value: bbox),
                .init(name: "limit", value: "\(limit)"),
            ],
            policy: policy
        )
    }

    /// Your Climbs: every canon climb with confirmed completions.
    func myClimbs(policy: CachePolicy = .network) async throws -> RiddenClimbsResponse {
        try await request("GET", "/users/me/climbs", policy: policy)
    }

    /// A sporting window over one climb's confirmed completions.
    func climbWindowBoard(
        climbId: String, window: String, policy: CachePolicy = .network
    ) async throws -> RecordBoard {
        try await request(
            "GET", "/climbs/\(climbId)/leaderboard/window",
            query: [.init(name: "window", value: window)],
            policy: policy
        )
    }

    /// Push one perceived-exertion edit; explicit nil clears.
    func updateRidePerceivedExertion(rideId: String, value: Int?) async throws {
        struct Empty: Codable {}
        let _: RideUpdateAck = try await request(
            "PATCH", "/rides/\(rideId)",
            rawBody: ["perceivedExertion": value.map { $0 as Any } ?? NSNull()]
        )
    }

    func popularClimbs(limit: Int = 6) async throws -> PopularClimbsResponse {
        try await request(
            "GET", "/climbs/popular",
            query: [.init(name: "limit", value: "\(limit)")], authenticated: false
        )
    }

    // MARK: Riders

    func riderProfile(identifier: String, policy: CachePolicy = .network) async throws -> PublicRiderProfileResponse {
        try await request("GET", "/users/\(identifier)/profile", policy: policy)
    }

    func leaderboardPositions(wallet: String, policy: CachePolicy = .network) async throws -> UserLeaderboardSummaryResponse {
        try await request("GET", "/users/\(wallet)/leaderboard-positions", policy: policy)
    }

    func myLeaderboardPositions() async throws -> UserLeaderboardSummaryResponse {
        try await request("GET", "/users/me/leaderboard-positions")
    }

    // MARK: Account deletion

    func preflight() async throws -> AccountDeletionPreflight {
        try await request(
            "GET", "/compliance/account/preflight",
            cacheResponse: false
        )
    }

    func create(capability: AccountDeletionCapability) async throws -> AccountDeletionStatus {
        guard let owner = capability.owner,
              CachedRiderStore.load().map(RecordingOwner.init(user:)) == owner,
              let initialAuthentication = authenticatedRequestAdmission,
              initialAuthentication.owner == owner
        else { throw APIError.notAuthenticated }
        return try await request(
            "DELETE", "/compliance/account",
            jsonBody: AccountDeletionWire.createPayload(for: capability),
            requiredSessionOwner: owner,
            requiredInitialAuthentication: initialAuthentication
        )
    }

    func status(capability: AccountDeletionCapability) async throws -> AccountDeletionStatus {
        try await request(
            "GET", "/compliance/deletion-status/\(capability.requestID)",
            headers: ["X-Account-Deletion-Token": capability.statusToken],
            authenticated: false,
            retryOn401: false,
            cacheResponse: false
        )
    }

    func retry(capability: AccountDeletionCapability) async throws -> AccountDeletionStatus {
        try await request(
            "POST", "/compliance/deletion-status/\(capability.requestID)/retry",
            jsonBody: AccountDeletionWire.retryPayload,
            headers: ["X-Account-Deletion-Token": capability.statusToken],
            authenticated: false,
            retryOn401: false,
            cacheResponse: false
        )
    }

    // MARK: Privacy (account defaults, zones, per-ride audience)

    func privacySettings(policy: CachePolicy = .network) async throws -> PrivacySettings {
        // Reopening during a save must not publish a pre-save choice. The
        // existing unavailable/retry state holds until the write resolves.
        guard pendingPrivacySettingsWrite == nil else { throw CancellationError() }
        if policy == .cacheOnly {
            guard let snapshot = privacySettingsSnapshot,
                  snapshot.session == sessionGeneration else { throw CacheMiss() }
            return snapshot.settings
        }
        let revision = privacySettingsRevision
        let generation = sessionGeneration
        let settings: PrivacySettings = try await request(
            "GET", "/privacy/settings", cacheResponse: false
        )
        guard revision == privacySettingsRevision, generation == sessionGeneration else {
            throw CancellationError()
        }
        privacySettingsSnapshot = (generation, settings)
        return settings
    }

    /// Update the account's default audience for future rides. The server is
    /// the policy owner; this only records the rider's explicit choice.
    func updateDefaultRideVisibility(_ visibility: RideVisibility) async throws -> PrivacySettings {
        try await updatePrivacySettings(["default_ride_visibility": visibility.rawValue])
    }

    func updateShareWkg(_ shareWkg: Bool) async throws -> PrivacySettings {
        try await updatePrivacySettings(["share_wkg": shareWkg])
    }

    private func updatePrivacySettings(_ body: [String: Any?]) async throws -> PrivacySettings {
        privacySettingsRevision &+= 1
        privacySettingsSnapshot = nil
        let revision = privacySettingsRevision
        let generation = sessionGeneration
        pendingPrivacySettingsWrite = revision
        defer {
            if pendingPrivacySettingsWrite == revision { pendingPrivacySettingsWrite = nil }
        }
        do {
            let settings: PrivacySettings = try await request(
                "PUT", "/privacy/settings", rawBody: body
            )
            guard revision == privacySettingsRevision, generation == sessionGeneration else {
                throw CancellationError()
            }
            // Also supersede reads that began while the write was in flight.
            privacySettingsRevision &+= 1
            privacySettingsSnapshot = (generation, settings)
            return settings
        } catch {
            if revision == privacySettingsRevision {
                privacySettingsRevision &+= 1
                privacySettingsSnapshot = nil
            }
            throw error
        }
    }

    func privacyZones(policy: CachePolicy = .network) async throws -> PrivacyZonesList {
        try await request("GET", "/privacy/zones", policy: policy)
    }

    /// The exact zone-create body the backend validates: coordinates plus a
    /// radius from the allowed set and an optional label.
    static func privacyZoneBody(
        latitude: Double, longitude: Double, radiusM: Int, label: String?
    ) -> [String: Any] {
        var body: [String: Any] = [
            "latitude": latitude,
            "longitude": longitude,
            "radius_m": radiusM,
        ]
        if let label, !label.isEmpty { body["label"] = label }
        return body
    }

    func createPrivacyZone(
        latitude: Double, longitude: Double, radiusM: Int, label: String?
    ) async throws -> PrivacyZone {
        try await request(
            "POST", "/privacy/zones",
            rawBody: Self.privacyZoneBody(
                latitude: latitude, longitude: longitude, radiusM: radiusM, label: label
            )
        )
    }

    func updatePrivacyZone(
        id: String, latitude: Double, longitude: Double, radiusM: Int, label: String?
    ) async throws -> PrivacyZone {
        // Label is always shipped on edit so clearing one is expressible.
        var body = Self.privacyZoneBody(
            latitude: latitude, longitude: longitude, radiusM: radiusM, label: label
        )
        body["label"] = (label?.isEmpty == false) ? label! : NSNull()
        return try await request("PUT", "/privacy/zones/\(id)", rawBody: body)
    }

    func deletePrivacyZone(id: String) async throws {
        _ = try await request(
            "DELETE", "/privacy/zones/\(id)"
        ) as PrivacyZoneDeleteResponse
    }

    /// Change one ride's audience (owner only server-side). The response is
    /// an acknowledgment; callers re-read the ride for authoritative state.
    func updateRideVisibility(rideId: String, _ visibility: RideVisibility) async throws {
        _ = try await request(
            "PATCH", "/rides/\(rideId)",
            rawBody: ["visibility": visibility.rawValue]
        ) as RideUpdateAck
    }

    static func ridePrivacyBody(_ publication: RidePublicationSettings) -> [String: Any] {
        [
            "visibility": publication.visibility.rawValue,
            "map_visibility": publication.mapVisibility.rawValue,
            "map_hide_start_m": publication.mapHideStartM,
            "map_hide_end_m": publication.mapHideEndM,
        ]
    }

    func updateRidePrivacy(
        rideId: String,
        publication: RidePublicationSettings
    ) async throws {
        _ = try await request(
            "PATCH", "/rides/\(rideId)",
            rawBody: Self.ridePrivacyBody(publication)
        ) as RideUpdateAck
    }

    static func rideMetadataBody(title: String?, notes: String?) -> [String: Any] {
        var body: [String: Any] = [:]
        if let title { body["title"] = title }
        if let notes { body["description"] = notes }
        return body
    }

    func updateRideMetadata(
        rideId: String,
        title: String?,
        notes: String?
    ) async throws {
        let body = Self.rideMetadataBody(title: title, notes: notes)
        guard !body.isEmpty else { return }
        _ = try await request(
            "PATCH", "/rides/\(rideId)", rawBody: body
        ) as RideUpdateAck
    }

    func rideMedia(rideId: String) async throws -> [RideMedia] {
        try await request("GET", "/rides/\(rideId)/media")
    }

    func rideMediaUploadInit(
        rideId: String,
        photo: RidePhotoDescriptor
    ) async throws -> RideMediaUploadInit {
        try await request(
            "POST", "/rides/\(rideId)/media/init",
            rawBody: [
                "client_request_id": photo.id,
                "file_name": photo.fileName,
                "mime_type": photo.mimeType,
                "file_size": photo.byteCount,
                "sort_order": photo.sortOrder,
                "role": photo.role,
            ]
        )
    }

    func rideMediaUploadComplete(rideId: String, mediaId: String) async throws -> RideMedia {
        try await request(
            "POST", "/rides/\(rideId)/media/complete",
            rawBody: ["media_id": mediaId]
        )
    }

    func deleteRideMedia(rideId: String, mediaId: String) async throws {
        _ = try await request(
            "DELETE", "/rides/\(rideId)/media/\(mediaId)"
        ) as EmptyResponse
    }

    func setRideMediaCover(rideId: String, mediaId: String) async throws -> RideMedia {
        try await request(
            "PATCH", "/rides/\(rideId)/media/\(mediaId)",
            rawBody: ["role": "cover"]
        )
    }

    func reorderRideMedia(rideId: String, media: [RideMedia]) async throws -> [RideMedia] {
        try await request(
            "PATCH", "/rides/\(rideId)/media/reorder",
            rawBody: [
                "items": media.enumerated().map { index, item in
                    ["media_id": item.id, "sort_order": index]
                },
            ]
        )
    }

    // MARK: Profile editing (PUT /users/me + avatar media lane)

    /// The exact `PUT /users/me` body for identity edits: absent key =
    /// untouched. A clear ships the EMPTY STRING, not JSON null — the
    /// backend's `update_user_profile` drops nulls for identity fields
    /// (only physiology is null-clearable, bead coq7q), so a null "clear"
    /// would be a silent no-op the sheet would misreport as success.
    /// Empty string persists, and every rendering surface treats empty as
    /// absent.
    static func profileUpdateBody(
        displayName: String?? = nil,
        location: String?? = nil,
        bio: String?? = nil
    ) -> [String: Any] {
        var body: [String: Any] = [:]
        if let displayName {
            body["display_name"] = displayName ?? ""
        }
        if let location {
            body["location"] = location ?? ""
        }
        if let bio {
            body["bio"] = bio ?? ""
        }
        return body
    }

    func updateProfile(
        displayName: String?? = nil,
        location: String?? = nil,
        bio: String?? = nil
    ) async throws -> User {
        try await request(
            "PUT", "/users/me",
            rawBody: Self.profileUpdateBody(
                displayName: displayName, location: location, bio: bio
            )
        )
    }

    func avatarUploadInit(
        mimeType: String, fileName: String?, fileSize: Int
    ) async throws -> AvatarUploadInit {
        try await request(
            "POST", "/users/me/avatar/init",
            rawBody: [
                "mime_type": mimeType,
                "file_name": fileName,
                "file_size": fileSize,
            ]
        )
    }

    func avatarUploadComplete(uploadId: String) async throws -> User {
        try await request(
            "POST", "/users/me/avatar/complete",
            rawBody: ["upload_id": uploadId]
        )
    }

    func deleteAvatar() async throws -> User {
        try await request("DELETE", "/users/me/avatar")
    }

    // MARK: Money (read-only)

    func calBalance(policy: CachePolicy = .network) async throws -> CalOnchainResponse {
        try await request("GET", "/cal/onchain", policy: policy)
    }

    func myDistributions(limit: Int = 30, policy: CachePolicy = .network) async throws -> MyDistributionsResponse {
        try await request(
            "GET", "/distributions/my", query: [.init(name: "limit", value: "\(limit)")],
            policy: policy
        )
    }

    func portfolio() async throws -> Portfolio {
        try await request("GET", "/portfolio")
    }

    func myStakes(policy: CachePolicy = .network) async throws -> MyVaultStakesResponse {
        try await request("GET", "/vaults/my/stakes", policy: policy)
    }

    func vaults(limit: Int = 100, offset: Int = 0) async throws -> VaultListResponse {
        try await request(
            "GET", "/vaults",
            query: [.init(name: "limit", value: "\(limit)"), .init(name: "offset", value: "\(offset)")]
        )
    }

    func pendingRewards(vaultId: Int, policy: CachePolicy = .network) async throws -> VaultPendingRewardsResponse {
        try await request("GET", "/vaults/\(vaultId)/pending-rewards", policy: policy)
    }

    func balanceOperation(operationId: String) async throws -> BalanceOperationStatusResponse? {
        do {
            return try await request("GET", "/balance/operations/\(operationId)")
        } catch APIError.http(status: 404, code: _, message: _) {
            return nil
        }
    }

    func balanceOperation(
        clientRequestId: String,
        referenceType: String,
        referenceId: String,
        actionType: String
    ) async throws -> BalanceOperationStatusResponse? {
        do {
            return try await request(
                "GET", "/balance/operations/lookup",
                query: [
                    .init(name: "client_request_id", value: clientRequestId),
                    .init(name: "reference_type", value: referenceType),
                    .init(name: "reference_id", value: referenceId),
                    .init(name: "action_type", value: actionType),
                ]
            )
        } catch APIError.http(status: 404, code: _, message: _) {
            return nil
        }
    }

    // MARK: Money (Balance writes: prepare → rider signs → submit)

    func stage1Status() async throws -> Stage1Status {
        try await request("GET", "/status", authenticated: false, cacheResponse: false)
    }

    func stage1Request(_ method: String, _ path: String, query: [URLQueryItem],
                       body: [String: Stage1JSON]?, owner: Stage1Owner?) async throws -> Stage1JSON {
        // Every native Stage 1 route crosses this fresh gate, including retry,
        // pagination and mutations. Off/absent/error never sends /stage1/*.
        let status = try await stage1Status()
        guard status.live else { throw Stage1Error.disabled }
        if path.hasPrefix("/stage1/"), method != "GET" || path == "/stage1/me/claims" || path == "/stage1/me/lookups" {
            guard status.actionsLive else { throw Stage1Error.actionsDisabled }
        }
        try Task.checkCancellation()
        guard path.hasPrefix("/stage1/") || path.hasPrefix("/balance/operations/") else { throw Stage1Error.unavailable }
        return try await request(method, path, query: query, jsonBody: body.map(Stage1JSON.object),
            authenticated: owner != nil, retryOn401: method == "GET", cacheResponse: false,
            requiredSessionOwner: owner.map { RecordingOwner(id: $0.id, wallet: $0.wallet) })
    }

    func prepareStake(vaultId: Int, calAmount: Int) async throws -> PreparedVaultTransaction {
        try await request(
            "POST", "/vaults/\(vaultId)/stake/prepare", rawBody: ["cal_amount": calAmount]
        )
    }

    func submitStake(
        vaultId: Int, calAmount: Int, signedTransaction: String,
        lastValidBlockHeight: Int, clientRequestId: String
    ) async throws -> StakeSubmitResponse {
        try await request(
            "POST", "/vaults/\(vaultId)/stake",
            rawBody: [
                "cal_amount": calAmount,
                "signed_transaction": signedTransaction,
                "last_valid_block_height": lastValidBlockHeight,
                "client_request_id": clientRequestId,
            ]
        )
    }

    /// amount: nil = withdraw all; otherwise LP base units (exact string).
    func prepareUnstake(vaultId: Int, lpAmountBaseUnits: String?) async throws -> PreparedVaultTransaction {
        try await request(
            "POST", "/vaults/\(vaultId)/unstake/prepare",
            rawBody: lpAmountBaseUnits.map { ["lp_amount_base_units": $0] }
                ?? ["withdraw_all": true]
        )
    }

    func submitUnstake(
        vaultId: Int, lpAmountBaseUnits: String?, signedTransaction: String,
        lastValidBlockHeight: Int, clientRequestId: String
    ) async throws -> UnstakeSubmitResponse {
        var body: [String: Any?] = [
            "signed_transaction": signedTransaction,
            "last_valid_block_height": lastValidBlockHeight,
            "client_request_id": clientRequestId,
        ]
        if let lpAmountBaseUnits {
            body["lp_amount_base_units"] = lpAmountBaseUnits
        } else {
            body["withdraw_all"] = true
        }
        return try await request("POST", "/vaults/\(vaultId)/unstake", rawBody: body)
    }

    func collectHarvest(vaultId: Int, clientRequestId: String) async throws -> HarvestSubmitResponse {
        try await request(
            "POST", "/vaults/\(vaultId)/harvest",
            rawBody: ["client_request_id": clientRequestId]
        )
    }

    // MARK: Push device registration (APNs key boundary)

    struct PushDeviceAck: Decodable {
        let deviceId: String?
    }

    /// Record (or replace) this install's APNs token. Keyed by the stable
    /// per-install device id; re-registration upserts.
    func registerPushDevice(token: String, environment: String) async throws {
        _ = try await request(
            "POST", "/mobile/push/devices",
            rawBody: [
                "device_id": Self.deviceID(),
                "apns_token": token,
                "environment": environment,
                "app_version": Bundle.main.object(
                    forInfoDictionaryKey: "CFBundleShortVersionString"
                ) as? String,
            ]
        ) as PushDeviceAck
    }

    /// Remove this install's token registration (sign-out path).
    func unregisterPushDevice() async throws {
        _ = try await request(
            "DELETE", "/mobile/push/devices/\(Self.deviceID())"
        ) as EmptyResponse
    }

    // MARK: Diagnostics (crash reporting ingest)

    struct DiagnosticsAccepted: Decodable {
        let accepted: Int
    }

    /// POST queued MetricKit diagnostic envelopes to the authenticated
    /// ingest. The server enforces the same caps the client queue does.
    func postDiagnostics(_ envelopes: [[String: Any]]) async throws -> Int {
        let response: DiagnosticsAccepted = try await request(
            "POST", "/mobile/diagnostics",
            rawBody: ["diagnostics": envelopes]
        )
        return response.accepted
    }

    // MARK: Upload (the one sanctioned production write path)

    func uploadInit(
        fileType: String,
        fileHash: String,
        fileSize: Int,
        clientRequestId: String? = nil,
        parserVersion: UInt32? = nil,
        preliminaryRideHash: String? = nil,
        publication: RidePublicationSettings
    ) async throws -> UploadInitResponse {
        guard (parserVersion == nil) == (preliminaryRideHash == nil) else {
            throw APIError.http(
                status: 0,
                code: "invalid_attestation_stamp",
                message: "Ride attestation is unavailable"
            )
        }
        guard publication.isValid else {
            throw APIError.http(
                status: 0,
                code: "invalid_privacy_settings",
                message: "Ride privacy is unavailable"
            )
        }
        return try await request(
            "POST", "/rides/upload/init",
            rawBody: Self.uploadInitBody(
                fileType: fileType,
                fileHash: fileHash,
                fileSize: fileSize,
                clientRequestId: clientRequestId,
                parserVersion: parserVersion,
                preliminaryRideHash: preliminaryRideHash,
                publication: publication
            )
        )
    }

    /// Compatibility-only retry for an older local job whose stable server
    /// row already exists. Omitting privacy preserves the decision frozen on
    /// that row; new uploads cannot enter through this API.
    func uploadInitLegacyResume(
        fileType: String,
        fileHash: String,
        fileSize: Int,
        clientRequestId: String,
        parserVersion: UInt32? = nil,
        preliminaryRideHash: String? = nil
    ) async throws -> UploadInitResponse {
        guard (parserVersion == nil) == (preliminaryRideHash == nil) else {
            throw APIError.http(
                status: 0,
                code: "invalid_attestation_stamp",
                message: "Ride attestation is unavailable"
            )
        }
        return try await request(
            "POST", "/rides/upload/init",
            rawBody: Self.uploadInitLegacyResumeBody(
                fileType: fileType,
                fileHash: fileHash,
                fileSize: fileSize,
                clientRequestId: clientRequestId,
                parserVersion: parserVersion,
                preliminaryRideHash: preliminaryRideHash
            )
        )
    }

    static func uploadInitBody(
        fileType: String,
        fileHash: String,
        fileSize: Int,
        clientRequestId: String?,
        parserVersion: UInt32?,
        preliminaryRideHash: String?,
        publication: RidePublicationSettings
    ) -> [String: Any] {
        var body = uploadInitBaseBody(
            fileType: fileType,
            fileHash: fileHash,
            fileSize: fileSize,
            clientRequestId: clientRequestId,
            parserVersion: parserVersion,
            preliminaryRideHash: preliminaryRideHash
        )
        body.merge(Self.ridePrivacyBody(publication)) { _, selected in selected }
        return body
    }

    static func uploadInitLegacyResumeBody(
        fileType: String,
        fileHash: String,
        fileSize: Int,
        clientRequestId: String,
        parserVersion: UInt32?,
        preliminaryRideHash: String?
    ) -> [String: Any] {
        uploadInitBaseBody(
            fileType: fileType,
            fileHash: fileHash,
            fileSize: fileSize,
            clientRequestId: clientRequestId,
            parserVersion: parserVersion,
            preliminaryRideHash: preliminaryRideHash
        )
    }

    private static func uploadInitBaseBody(
        fileType: String,
        fileHash: String,
        fileSize: Int,
        clientRequestId: String?,
        parserVersion: UInt32?,
        preliminaryRideHash: String?
    ) -> [String: Any] {
        var body: [String: Any] = [
            "file_type": fileType,
            "file_hash": fileHash,
            "file_size": fileSize,
        ]
        if let clientRequestId { body["client_request_id"] = clientRequestId }
        if let parserVersion { body["parser_version"] = Int(parserVersion) }
        if let preliminaryRideHash { body["preliminary_ride_hash"] = preliminaryRideHash }
        return body
    }

    func uploadComplete(uploadId: String) async throws -> UploadCompleteResponse {
        try await request("POST", "/rides/upload/complete", rawBody: ["upload_id": uploadId])
    }

    /// Legacy inline upload — the backend's retained rollback path for the
    /// direct-to-storage flow. Used as a fallback when signed-URL creation
    /// is unavailable server-side.
    func uploadInline(fileType: String, data: Data) async throws -> UploadCompleteResponse {
        try await request(
            "POST", "/rides/upload",
            rawBody: ["file_data_b64": data.base64EncodedString(), "file_type": fileType]
        )
    }

    func uploadAbort(uploadId: String) async {
        _ = try? await request(
            "POST", "/rides/upload/abort", rawBody: ["upload_id": uploadId]
        ) as EmptyResponse
    }

    func reprocessRide(id: String) async throws {
        _ = try await request("POST", "/rides/\(id)/reprocess") as EmptyResponse
    }

    /// PUT the file to the presigned storage URL as multipart form data
    /// (Supabase signed upload URLs expect a "file" field — portal parity).
    nonisolated func uploadToStorage(signedUrl: String, data: Data, fileName: String) async throws {
        guard let url = URL(string: signedUrl) else {
            throw APIError.http(status: 0, code: "bad_signed_url", message: "Bad signed URL")
        }
        var req = URLRequest(url: url)
        req.httpMethod = "PUT"
        req.setValue("false", forHTTPHeaderField: "x-upsert")
        let boundary = "br-\(UUID().uuidString)"
        req.setValue("multipart/form-data; boundary=\(boundary)", forHTTPHeaderField: "Content-Type")
        let safeFileName = fileName
            .replacingOccurrences(of: "\\", with: "_")
            .replacingOccurrences(of: "\"", with: "_")
            .replacingOccurrences(of: "\r", with: "_")
            .replacingOccurrences(of: "\n", with: "_")
        var body = Data()
        body.append("--\(boundary)\r\n".data(using: .utf8)!)
        body.append(
            "Content-Disposition: form-data; name=\"file\"; filename=\"\(safeFileName)\"\r\n".data(using: .utf8)!
        )
        body.append("Content-Type: application/octet-stream\r\n\r\n".data(using: .utf8)!)
        body.append(data)
        body.append("\r\n--\(boundary)--\r\n".data(using: .utf8)!)
        req.httpBody = body
        let (respData, response) = try await URLSession.shared.data(for: req)
        let status = (response as? HTTPURLResponse)?.statusCode ?? 0
        guard (200..<300).contains(status) else {
            throw APIError.http(
                status: status, code: "storage_upload_failed",
                message: String(data: respData.prefix(200), encoding: .utf8)
            )
        }
    }
}

extension APIClient: AccountDeletionServing {}
