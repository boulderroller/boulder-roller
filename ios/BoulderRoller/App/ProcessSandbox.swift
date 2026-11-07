import Foundation
import Security

/// The hard wall between rider evidence and test processes.
///
/// Once simulator builds gained working keychains (2026-08-17), any test
/// suite that reached a shared singleton wrote REAL custody records into the
/// rider's app container — a test-born ride appeared in the feed, and a
/// fake-clock suite stamped a five-hour "moving time" onto it. Suites that
/// construct their own stores already isolate; this wall covers every path
/// that resolves a DEFAULT root or the default custody key, so a test
/// process is physically incapable of touching rider evidence no matter how
/// it reaches the storage layer.
enum ProcessSandbox {
    /// True when this process hosts XCTest (unit or UI test runner).
    static let isTestProcess: Bool = NSClassFromString("XCTestCase") != nil

    /// One isolated root per test process, cleaned by the OS temp policy.
    private static let testRoot: URL = FileManager.default.temporaryDirectory
        .appendingPathComponent(
            "BoulderRollerTestIsolated-\(UUID().uuidString)",
            isDirectory: true
        )

    /// The production location — or an isolated stand-in under test.
    static func isolatedIfTesting(_ productionRoot: URL, label: String) -> URL {
        guard isTestProcess else { return productionRoot }
        return testRoot.appendingPathComponent(label, isDirectory: true)
    }

    /// Ephemeral custody master key for test processes: random, in-memory,
    /// never the rider's keychain item.
    static let ephemeralTestCustodyKey: Data = {
        var bytes = Data(count: 32)
        let status = bytes.withUnsafeMutableBytes { buffer in
            SecRandomCopyBytes(kSecRandomDefault, 32, buffer.baseAddress!)
        }
        precondition(status == errSecSuccess)
        return bytes
    }()

    /// Keychain account names get a test prefix so token reads/writes from
    /// suites can never clobber the rider's stored session.
    static func keychainAccount(_ production: String) -> String {
        isTestProcess ? "test.\(production)" : production
    }
}
