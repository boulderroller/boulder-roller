import Foundation
import Testing
@testable import BoulderRoller

/// L2.12: the external wallet destination is the one approved URL, cluster
/// named except on mainnet — mainnet flipping stays part of the u82.6
/// ceremony, so today's build must name devnet.
struct WalletBoundaryTests {
    @Test func explorerURLNamesTheCluster() {
        let url = AppConfig.solanaExplorerAddressURL("G8DMexample")
        #expect(url?.host() == "explorer.solana.com")
        #expect(url?.path() == "/address/G8DMexample")
        #expect(url?.query() == "cluster=devnet")
    }

    @Test func currentBuildIsDevnet() {
        #expect(AppConfig.solanaNetwork == "devnet")
    }
}
