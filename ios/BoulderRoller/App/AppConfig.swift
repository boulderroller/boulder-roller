import Foundation

/// Client-side configuration. These identifiers are plain client config, not
/// secrets — the same values are committed in mobile/app.config.ts (Expo era)
/// and web/portal env. Secrets and invite codes never live in source.
enum AppConfig {
    static let apiBaseURL = "https://api.boulderroller.xyz"
    static let portalBaseURL = "https://app.boulderroller.xyz"
    static let supportURL = URL(string: "https://docs.boulderroller.xyz/support/contact")!
    static let portalBalanceURL = URL(string: "https://app.boulderroller.xyz/portfolio")!

    /// Solana cluster, mirroring the portal's VITE_SOLANA_NETWORK default.
    /// Mainnet remains trigger-gated (bead u82.6); flipping this is part of
    /// that ceremony, never a routine edit.
    static let solanaNetwork = "devnet"
    /// Shared read endpoint. Custom RPC endpoints belong in this configuration,
    /// alongside the cluster; individual features must not select a network.
    static let solanaRPCURL = URL(string: "https://api.\(solanaNetwork).solana.com")!

    /// The approved external wallet destination (portal precedent,
    /// web/portal/src/lib/solana.ts): Solana Explorer with the cluster
    /// named except on mainnet-beta.
    static func solanaExplorerAddressURL(_ address: String) -> URL? {
        var components = URLComponents(
            string: "https://explorer.solana.com/address/\(address)"
        )
        if solanaNetwork != "mainnet-beta" {
            components?.queryItems = [
                URLQueryItem(name: "cluster", value: solanaNetwork)
            ]
        }
        return components?.url
    }

    /// Privy app + mobile app-client identifiers (see mobile/app.config.ts).
    static let privyAppId = "cmjp145cl008xl70clr2ho821"
    static let privyAppClientId = "client-WY6UGQdegv84Ug3Gx9KnPFVkagwsCJ41YcPQ8oRJYoCqy"

    #if DEBUG
    /// DEBUG-only developer sign-in (SIWS wallet auth, a real production auth
    /// flow) reads its invite code from the environment, never from source.
    static var devInviteCode: String? {
        ProcessInfo.processInfo.environment["BR_DEV_INVITE_CODE"]
    }
    #endif
}
