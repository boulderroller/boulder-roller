import Foundation
import Testing
@testable import BoulderRoller

/// L3.08: every API request names its wire contract and build — nothing
/// else — and the server's typed refusal lands in the stale-client class.
struct ClientContractTests {
    @Test func headersCarryContractAndBuildOnly() {
        var request = URLRequest(url: URL(string: "https://api.example/rides")!)
        ClientContract.attach(to: &request)
        #expect(request.value(forHTTPHeaderField: "X-BR-Contract") == "client.v1")
        let client = request.value(forHTTPHeaderField: "X-BR-Client")
        #expect(client?.hasPrefix("ios/") == true)
        // Exactly the two contract headers — no identity, no device ids.
        #expect(request.allHTTPHeaderFields?.count == 2)
    }

    @Test func clientValueIsPlatformSlashBuild() {
        #expect(ClientContract.clientValue(build: "214") == "ios/214")
        #expect(ClientContract.clientValue(build: nil) == "ios/0")
    }

    /// The server's refusal shape decodes into the never-retryable
    /// stale-client class without any client-side guessing.
    @Test func serverRefusalMapsToStaleClient() {
        let error = APIClient.httpError(
            status: 426,
            body: Data(#"{"detail": {"code": "upgrade_required"}}"#.utf8)
        )
        guard case .staleClient = error else {
            Issue.record("426 must map to staleClient, got \(error)")
            return
        }
        #expect(APIFailureClass.classify(error) == .staleClient)
        #expect(!APIFailureClass.classify(error).isRetryable)
    }
}
