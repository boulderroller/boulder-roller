import Foundation
import Testing
@testable import BoulderRoller

/// The auth wire contracts, pinned against the backend's exact response
/// shapes (`backend/app/routes/auth.py`). The Aug 17 defect: `/auth/refresh`
/// returns tokens + wallet but NO user id; decoding it into the sign-in type
/// silently failed, the "transient by law" classifier kept the old token,
/// the retry hit 409 refresh_rotated, and every rider was signed out on
/// every refresh. These tests fail if either contract drifts again.
struct AuthContractTests {
    private var decoder: JSONDecoder {
        let d = JSONDecoder()
        d.keyDecodingStrategy = .convertFromSnakeCase
        return d
    }

    /// The server's RefreshResponse, verbatim shape (TokenPair + wallet).
    private let refreshJSON = Data("""
    {
        "access_token": "eyJhbGciOi.access.example",
        "access_expires_at": "2026-08-17T19:15:00.123456+00:00",
        "refresh_token": "eyJhbGciOi.refresh.example",
        "refresh_expires_at": "2026-09-16T19:00:00.123456+00:00",
        "wallet": "9xQeWvG816bUx9EPjHmaT23yTVSHkq4y4oXAMPLE"
    }
    """.utf8)

    /// The server's VerifyResponse (TokenPair + user_id + wallet).
    private let verifyJSON = Data("""
    {
        "access_token": "eyJhbGciOi.access.example",
        "access_expires_at": "2026-08-17T19:15:00.123456+00:00",
        "refresh_token": "eyJhbGciOi.refresh.example",
        "refresh_expires_at": "2026-09-16T19:00:00.123456+00:00",
        "user_id": "99999999-9999-4999-8999-999999999999",
        "wallet": "9xQeWvG816bUx9EPjHmaT23yTVSHkq4y4oXAMPLE"
    }
    """.utf8)

    @Test func refreshResponseDecodesWithoutUserID() throws {
        let decoded = try decoder.decode(RefreshTokenResponse.self, from: refreshJSON)
        #expect(decoded.accessToken == "eyJhbGciOi.access.example")
        #expect(decoded.refreshToken == "eyJhbGciOi.refresh.example")
        #expect(decoded.wallet != nil)
    }

    /// The canary that documents why the types are split: the sign-in type
    /// must NOT accept the refresh body. If this ever starts passing, the
    /// server began sending user_id on refresh and the split can retire.
    @Test func signInTypeRejectsRefreshBody() {
        #expect(throws: (any Error).self) {
            _ = try decoder.decode(AuthTokenResponse.self, from: refreshJSON)
        }
    }

    @Test func verifyResponseDecodesWithIdentity() throws {
        let decoded = try decoder.decode(AuthTokenResponse.self, from: verifyJSON)
        #expect(decoded.userId == "99999999-9999-4999-8999-999999999999")
    }

    /// Both response shapes adopt into the same token material.
    @Test func sessionTokensCarryTokensOnly() throws {
        let refresh = try decoder.decode(RefreshTokenResponse.self, from: refreshJSON)
        let verify = try decoder.decode(AuthTokenResponse.self, from: verifyJSON)
        let fromRefresh = APIClient.SessionTokens(refresh)
        let fromVerify = APIClient.SessionTokens(verify)
        #expect(fromRefresh == fromVerify)
    }
}
