import CryptoKit
import Foundation

/// Sign-In-With-Solana over a locally held ed25519 key. This is one of the
/// backend's two production auth flows (backend/app/security/siws.py); the
/// portal drives it through Phantom/Solflare. The DEBUG developer sign-in
/// drives it with a Keychain-held key so an agent-run simulator can produce a
/// real production session without an inbox for email OTP.
enum SIWS {
    private static let developerWalletSeedKey = "br_dev_wallet_seed"

    struct Wallet {
        let privateKey: Curve25519.Signing.PrivateKey
        var address: String { Base58.encode(privateKey.publicKey.rawRepresentation) }
    }

    /// Load (or create once) the local dev wallet key. DEBUG-only tooling:
    /// the seed lives in UserDefaults so it survives unsigned-simulator
    /// reinstalls (the Keychain does not); product credentials never use
    /// this path.
    static func loadOrCreateWallet() -> Wallet {
        if let seed = UserDefaults.standard.data(forKey: developerWalletSeedKey),
           let existing = try? Curve25519.Signing.PrivateKey(rawRepresentation: seed) {
            return Wallet(privateKey: existing)
        }
        let fresh = Curve25519.Signing.PrivateKey()
        UserDefaults.standard.set(fresh.rawRepresentation, forKey: developerWalletSeedKey)
        return Wallet(privateKey: fresh)
    }

    static func removeDeveloperWalletSeedRequired() throws {
        UserDefaults.standard.removeObject(forKey: developerWalletSeedKey)
        guard UserDefaults.standard.object(forKey: developerWalletSeedKey) == nil else {
            throw AccountDeletionLocalCleanupError.verificationFailed
        }
    }

    /// Sign the server-provided SIWS message; returns base58 signature.
    static func sign(message: String, with wallet: Wallet) throws -> String {
        let signature = try wallet.privateKey.signature(for: Data(message.utf8))
        return Base58.encode(signature)
    }
}

enum Base58 {
    private static let alphabet = Array("123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz")

    static func encode(_ data: Data) -> String {
        let bytes = Array(data)
        var zeros = 0
        while zeros < bytes.count, bytes[zeros] == 0 { zeros += 1 }
        var input = Array(bytes[zeros...])
        var encoded: [Character] = []
        while !input.isEmpty {
            var remainder = 0
            var quotient: [UInt8] = []
            for byte in input {
                let value = remainder * 256 + Int(byte)
                let q = value / 58
                remainder = value % 58
                if !quotient.isEmpty || q > 0 { quotient.append(UInt8(q)) }
            }
            encoded.append(alphabet[remainder])
            input = quotient
        }
        return String(repeating: "1", count: zeros) + String(encoded.reversed())
    }
}
