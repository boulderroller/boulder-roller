import Foundation

/// Last-known signed-in rider, persisted so a relaunch with the network down
/// resumes to the rider's own cached, read-only state instead of a false
/// onboarding (bead `boulderroller-v2-f4acp.2.9`).
///
/// Contents: the server's own `/users/me` profile projection — identity and
/// display fields only. No tokens, no secrets (those live in the Keychain),
/// no ride payloads. Cleared whenever the session truly ends.
enum CachedRiderStore {
    private static let fileName = "br_cached_rider.json"

    private static var fileURL: URL? {
        guard let dir = FileManager.default.urls(
            for: .applicationSupportDirectory, in: .userDomainMask
        ).first else { return nil }
        return dir.appendingPathComponent(fileName)
    }

    private struct Envelope: Codable {
        let schema: Int
        let savedAt: Date
        let user: User
    }

    static func save(_ user: User) {
        guard let url = fileURL else { return }
        let envelope = Envelope(schema: 1, savedAt: .now, user: user)
        guard let data = try? JSONEncoder().encode(envelope) else { return }
        try? FileManager.default.createDirectory(
            at: url.deletingLastPathComponent(), withIntermediateDirectories: true
        )
        try? data.write(to: url, options: [.atomic])
    }

    static func load() -> User? {
        guard let url = fileURL, let data = try? Data(contentsOf: url) else { return nil }
        return (try? JSONDecoder().decode(Envelope.self, from: data))?.user
    }

    static func clear() {
        guard let url = fileURL else { return }
        try? FileManager.default.removeItem(at: url)
    }

    static func clearRequired() throws {
        guard let url = fileURL else {
            throw AccountDeletionLocalCleanupError.verificationFailed
        }
        if FileManager.default.fileExists(atPath: url.path) {
            try FileManager.default.removeItem(at: url)
        }
        guard !FileManager.default.fileExists(atPath: url.path) else {
            throw AccountDeletionLocalCleanupError.verificationFailed
        }
    }
}
