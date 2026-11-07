import Foundation
import PrivySDK

/// Native Privy auth (email OTP, Sign in with Apple) feeding the backend's
/// `/auth/privy/verify`. The backend verifies the access token against the
/// Privy verification key and resolves the embedded Solana wallet server-side.
final class PrivyAuthService: @unchecked Sendable {
    static let shared = PrivyAuthService()

    private let privy: any Privy

    private init() {
        privy = PrivySdk.initialize(
            config: PrivyConfig(
                appId: AppConfig.privyAppId,
                appClientId: AppConfig.privyAppClientId
            )
        )
    }

    func sendEmailCode(to email: String) async throws {
        try await privy.email.sendCode(to: email)
    }

    func loginWithEmailCode(_ code: String, sentTo email: String) async throws -> (wallet: String, token: String) {
        let user = try await privy.email.loginWithCode(code, sentTo: email)
        return try await sessionMaterial(for: user)
    }

    func loginWithApple() async throws -> (wallet: String, token: String) {
        let user = try await privy.oAuth.login(with: .apple)
        return try await sessionMaterial(for: user)
    }

    func logout() async {
        if let user = await privy.getUser() {
            await user.logout()
        }
    }

    func logoutRequired() async throws {
        if let user = await privy.getUser() {
            await user.logout()
        }
        guard case .unauthenticated = await privy.getAuthState() else {
            throw AccountDeletionLocalCleanupError.verificationFailed
        }
    }

    /// Current Privy auth state — the money room's route to the embedded
    /// Solana wallet for transaction signing.
    func authState() async -> AuthState {
        await privy.getAuthState()
    }

    private func sessionMaterial(for user: any PrivyUser) async throws -> (wallet: String, token: String) {
        let wallet: String
        if let existing = user.embeddedSolanaWallets.first {
            wallet = existing.address
        } else {
            wallet = try await user.createSolanaWallet().address
        }
        let token = try await user.getAccessToken()
        return (wallet, token)
    }
}
