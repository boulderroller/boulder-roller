import Foundation

/// The app→API version contract (L3.08). Every API request names the wire
/// contract this build speaks and its build number — platform and build
/// only, never identity, device ids, or install ids. The server refuses
/// unsupported versions with the typed upgrade signal that the error
/// taxonomy maps to `.staleClient`.
enum ClientContract {
    /// The DTO contract this build is compiled against. Matches the
    /// `contract_version` the API stamps on client-facing responses.
    static let contractVersion = "client.v1"

    static let contractHeader = "X-BR-Contract"
    static let clientHeader = "X-BR-Client"

    /// "ios/214" — platform slash CFBundleVersion.
    static func clientValue(
        build: String? = Bundle.main.object(
            forInfoDictionaryKey: "CFBundleVersion"
        ) as? String
    ) -> String {
        "ios/\(build ?? "0")"
    }

    /// The one place headers are attached, so the exact wire shape is
    /// unit-testable against the production path.
    static func attach(to request: inout URLRequest) {
        request.setValue(contractVersion, forHTTPHeaderField: contractHeader)
        request.setValue(clientValue(), forHTTPHeaderField: clientHeader)
    }
}
