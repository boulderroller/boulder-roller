import Foundation
import PrivySDK

/// Signs backend-prepared transactions with whichever key owns the session's
/// wallet: the Privy embedded Solana wallet for product accounts, or the
/// DEBUG developer wallet (SIWS local key) for agent-run simulator sessions.
/// Both paths produce the same thing — the rider's signature on the prepared
/// message; Boulder Roller Balance carries everything else.
enum TransactionSigner {
    enum SignerError: LocalizedError {
        case noWallet

        var errorDescription: String? {
            "No signing key is available for this account"
        }
    }

    static func sign(
        transactionB64: String,
        wallet: String,
        intent: BalanceTransactionIntent,
        lookupTables: [SolanaTransaction.ResolvedLookupTable] = [],
        stage1TestPool: Stage1TestPool? = nil
    ) async throws -> String {
        // Validate before resolving or invoking the wallet provider. A backend
        // exact-message check remains the second guard at submission.
        try BalanceTransactionFirewall.validate(transactionB64: transactionB64, intent: intent, lookupTables: lookupTables, stage1TestPool: stage1TestPool)
        #if DEBUG
        let dev = SIWS.loadOrCreateWallet()
        if dev.address == wallet {
            return try SolanaTransaction.partiallySign(
                transactionB64: transactionB64, privateKey: dev.privateKey
            )
        }
        #endif
        return try await signWithPrivy(transactionB64: transactionB64, wallet: wallet)
    }

    private static func signWithPrivy(transactionB64: String, wallet: String) async throws -> String {
        guard case let .authenticated(user) = await PrivyAuthService.shared.authState(),
              let embedded = user.embeddedSolanaWallets.first(where: { $0.address == wallet }),
              let transaction = Data(base64Encoded: transactionB64)
        else { throw SignerError.noWallet }
        return try await embedded.provider.signTransaction(transaction: transaction)
    }
}
