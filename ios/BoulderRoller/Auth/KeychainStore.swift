import Foundation
import Security

enum SessionCredentialStoreError: LocalizedError, Equatable, Sendable {
    case unavailable(status: OSStatus)
    case invalidData

    var errorDescription: String? {
        switch self {
        case .unavailable, .invalidData:
            return "Sign-in couldn’t be saved on this iPhone. Try again."
        }
    }
}

/// The one durable session credential boundary. Production uses Keychain;
/// tests inject failures so a storage outage can never masquerade as either a
/// successful sign-in or a genuinely signed-out phone.
protocol SessionCredentialStore: Sendable {
    func readRefreshToken() throws -> String?
    func saveRefreshToken(_ token: String) throws
    func deleteRefreshToken() throws
}

struct KeychainSessionCredentialStore: SessionCredentialStore {
    func readRefreshToken() throws -> String? {
        try KeychainStore.readRequired(.refreshToken)
    }

    func saveRefreshToken(_ token: String) throws {
        try KeychainStore.saveRequired(token, for: .refreshToken)
    }

    func deleteRefreshToken() throws {
        try KeychainStore.deleteRequired(.refreshToken)
    }
}

#if DEBUG && targetEnvironment(simulator)
/// DEBUG+simulator-only session-token fallback (see KeychainStore.save).
/// Exists because unsigned simulator builds (CODE_SIGNING_ALLOWED=NO) have
/// no application-identifier and the keychain rejects every write — the
/// same reality that moved the SIWS dev seed to UserDefaults. Signed
/// builds never compile it; production custody semantics are untouched.
enum UnsignedSimulatorTokenStore {
    private static func defaultsKey(_ key: KeychainStore.Key) -> String {
        "br.unsigned_sim_keychain_fallback.\(key.rawValue)"
    }

    static func save(_ data: Data, for key: KeychainStore.Key) {
        UserDefaults.standard.set(data, forKey: defaultsKey(key))
    }

    static func read(_ key: KeychainStore.Key) -> Data? {
        UserDefaults.standard.data(forKey: defaultsKey(key))
    }

    static func delete(_ key: KeychainStore.Key) {
        UserDefaults.standard.removeObject(forKey: defaultsKey(key))
    }
}
#endif

enum KeychainStore {
    enum Key: String {
        case refreshToken = "br.refresh_token"
        case devWalletSeed = "br.dev_wallet_seed"
        case liveRideCustodyKey = "br.live_ride_custody_key.v1"
        case accountDeletionCapability = "br.account_deletion_capability.v1"
    }

    enum CustodyKeyError: Error {
        case unavailable
        case invalid
    }

    private enum ReadResult {
        case value(Data)
        case missing
        case unavailable(OSStatus)
    }

    static func save(_ value: String, for key: Key) {
        _ = persist(Data(value.utf8), for: key)
    }

    static func save(_ data: Data, for key: Key) {
        _ = persist(data, for: key)
    }

    static func saveRequired(_ value: String, for key: Key) throws {
        let status = persist(Data(value.utf8), for: key)
        guard status == errSecSuccess else {
            throw SessionCredentialStoreError.unavailable(status: status)
        }
    }

    private static func persist(_ data: Data, for key: Key) -> OSStatus {
        // Replace in place. A delete/add rotation leaves a process-kill window
        // where the server has retired generation N but generation N+1 is not
        // durable. Update first closes that window; add is only for a genuinely
        // new item, with a duplicate-race retry back through update.
        let match: [String: Any] = [
            kSecClass as String: kSecClassGenericPassword,
            kSecAttrService as String: "com.boulderroller.app",
            kSecAttrAccount as String: ProcessSandbox.keychainAccount(key.rawValue),
        ]
        let values: [String: Any] = [
            kSecValueData as String: data,
            kSecAttrAccessible as String: kSecAttrAccessibleAfterFirstUnlock,
        ]
        let updateStatus = SecItemUpdate(match as CFDictionary, values as CFDictionary)
        var finalStatus = updateStatus
        var addStatus: OSStatus?
        if updateStatus == errSecItemNotFound {
            let addQuery = match.merging(values) { _, replacement in replacement }
            let attemptedAdd = SecItemAdd(addQuery as CFDictionary, nil)
            addStatus = attemptedAdd
            finalStatus = attemptedAdd == errSecDuplicateItem
                ? SecItemUpdate(match as CFDictionary, values as CFDictionary)
                : attemptedAdd
        }
        #if DEBUG && targetEnvironment(simulator)
        let addDescription = addStatus.map { String($0) } ?? "not-attempted"
        print(
            "[Keychain] save \(key.rawValue) update=\(updateStatus) "
                + "add=\(addDescription) "
                + "final=\(finalStatus)"
        )
        // Unsigned-simulator seam (bead f4acp.2.9, c6l2l note 11): with
        // CODE_SIGNING_ALLOWED=NO the simulator keychain rejects every write
        // (no application-identifier), so sessions could never survive a
        // relaunch in the dev environment — the "lands on onboarding though
        // re-auth succeeds" symptom. Mirror the SIWS dev-seed precedent:
        // fall back to UserDefaults, DEBUG+simulator builds only. Signed
        // device/TestFlight builds never compile this path.
        if finalStatus != errSecSuccess, key == .refreshToken {
            UnsignedSimulatorTokenStore.save(data, for: key)
            return UnsignedSimulatorTokenStore.read(key) == data
                ? errSecSuccess
                : finalStatus
        } else if key == .refreshToken {
            UnsignedSimulatorTokenStore.delete(key)
        }
        #endif
        return finalStatus
    }

    static func read(_ key: Key) -> String? {
        readData(key).flatMap { String(data: $0, encoding: .utf8) }
    }

    static func readData(_ key: Key) -> Data? {
        guard case let .value(data) = readResult(key) else { return nil }
        return data
    }

    static func readRequired(_ key: Key) throws -> String? {
        switch readResult(key) {
        case let .value(data):
            guard let value = String(data: data, encoding: .utf8) else {
                throw SessionCredentialStoreError.invalidData
            }
            return value
        case .missing:
            return nil
        case let .unavailable(status):
            throw SessionCredentialStoreError.unavailable(status: status)
        }
    }

    private static func readResult(_ key: Key) -> ReadResult {
        let query: [String: Any] = [
            kSecClass as String: kSecClassGenericPassword,
            kSecAttrService as String: "com.boulderroller.app",
            kSecAttrAccount as String: ProcessSandbox.keychainAccount(key.rawValue),
            kSecReturnData as String: true,
            kSecMatchLimit as String: kSecMatchLimitOne,
        ]
        var item: CFTypeRef?
        let status = SecItemCopyMatching(query as CFDictionary, &item)
        #if DEBUG && targetEnvironment(simulator)
        print("[Keychain] read \(key.rawValue) status=\(status)")
        #endif
        if status == errSecSuccess {
            guard let data = item as? Data else { return .unavailable(errSecDecode) }
            return .value(data)
        }
        #if DEBUG && targetEnvironment(simulator)
        if key == .refreshToken {
            return UnsignedSimulatorTokenStore.read(key).map(ReadResult.value) ?? .missing
        }
        #endif
        return status == errSecItemNotFound ? .missing : .unavailable(status)
    }

    static func delete(_ key: Key) {
        _ = remove(key)
    }

    static func deleteRequired(_ key: Key) throws {
        let status = remove(key)
        guard status == errSecSuccess || status == errSecItemNotFound else {
            throw SessionCredentialStoreError.unavailable(status: status)
        }
    }

    private static func remove(_ key: Key) -> OSStatus {
        let query: [String: Any] = [
            kSecClass as String: kSecClassGenericPassword,
            kSecAttrService as String: "com.boulderroller.app",
            kSecAttrAccount as String: ProcessSandbox.keychainAccount(key.rawValue),
        ]
        let status = SecItemDelete(query as CFDictionary)
        #if DEBUG && targetEnvironment(simulator)
        print("[Keychain] delete \(key.rawValue) status=\(status)")
        if key == .refreshToken {
            UnsignedSimulatorTokenStore.delete(key)
            return errSecSuccess
        }
        #endif
        return status
    }

    /// Read-or-create without the delete/add window used by replaceable auth
    /// tokens. Once encrypted custody exists, a missing key is an unavailable
    /// store—not permission to generate a key that would orphan rider truth.
    /// NOTE: this custody key path deliberately does NOT use the
    /// unsigned-simulator fallback — custody unavailability must stay a
    /// truthful, visible state (its dev-sim behavior is tracked on the
    /// custody lane, bead c6l2l item 7), and replaceable session tokens and
    /// irreplaceable custody keys must never share a downgrade path.
    /// True ONLY when the keychain positively reports the custody key absent
    /// (errSecItemNotFound). Any error status returns false — errors stay
    /// fail-closed; only proven absence may unlock keyless recovery.
    static func custodyKeyPositivelyAbsent() -> Bool {
        let query: [String: Any] = [
            kSecClass as String: kSecClassGenericPassword,
            kSecAttrService as String: "com.boulderroller.app",
            kSecAttrAccount as String: ProcessSandbox.keychainAccount(Key.liveRideCustodyKey.rawValue),
            kSecReturnData as String: false,
            kSecMatchLimit as String: kSecMatchLimitOne,
        ]
        var item: CFTypeRef?
        return SecItemCopyMatching(query as CFDictionary, &item) == errSecItemNotFound
    }

    static func liveRideCustodyMasterKey(existingStore: Bool) throws -> Data {
        let readQuery: [String: Any] = [
            kSecClass as String: kSecClassGenericPassword,
            kSecAttrService as String: "com.boulderroller.app",
            kSecAttrAccount as String: ProcessSandbox.keychainAccount(Key.liveRideCustodyKey.rawValue),
            kSecReturnData as String: true,
            kSecMatchLimit as String: kSecMatchLimitOne,
        ]
        var item: CFTypeRef?
        let readStatus = SecItemCopyMatching(readQuery as CFDictionary, &item)
        if readStatus == errSecSuccess {
            guard let data = item as? Data, data.count == 32 else {
                throw CustodyKeyError.invalid
            }
            return data
        }
        print("[Keychain] custody key read=\(readStatus) existingStore=\(existingStore)")
        guard readStatus == errSecItemNotFound, !existingStore else {
            throw CustodyKeyError.unavailable
        }

        var bytes = Data(count: 32)
        let randomStatus = bytes.withUnsafeMutableBytes { rawBuffer in
            SecRandomCopyBytes(kSecRandomDefault, 32, rawBuffer.baseAddress!)
        }
        guard randomStatus == errSecSuccess else { throw CustodyKeyError.unavailable }

        let addQuery: [String: Any] = [
            kSecClass as String: kSecClassGenericPassword,
            kSecAttrService as String: "com.boulderroller.app",
            kSecAttrAccount as String: ProcessSandbox.keychainAccount(Key.liveRideCustodyKey.rawValue),
            kSecValueData as String: bytes,
            kSecAttrAccessible as String: kSecAttrAccessibleAfterFirstUnlock,
        ]
        let addStatus = SecItemAdd(addQuery as CFDictionary, nil)
        print("[Keychain] custody key add=\(addStatus)")
        if addStatus == errSecSuccess { return bytes }
        if addStatus == errSecDuplicateItem {
            var concurrentItem: CFTypeRef?
            guard SecItemCopyMatching(readQuery as CFDictionary, &concurrentItem) == errSecSuccess,
                  let concurrent = concurrentItem as? Data,
                  concurrent.count == 32
            else { throw CustodyKeyError.unavailable }
            return concurrent
        }
        throw CustodyKeyError.unavailable
    }
}
