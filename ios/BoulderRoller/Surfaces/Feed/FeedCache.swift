import CryptoKit
import Foundation

struct FeedCacheSnapshot: Codable, Sendable {
    static let currentSchemaVersion = 1

    let schemaVersion: Int
    let owner: RecordingOwner
    let scope: FeedScope
    let savedAt: Date
    let activities: [FeedActivity]
    let hasMore: Bool
    let nextCursor: String?

    init(
        owner: RecordingOwner,
        scope: FeedScope,
        savedAt: Date = .now,
        activities: [FeedActivity],
        hasMore: Bool,
        nextCursor: String?
    ) {
        schemaVersion = Self.currentSchemaVersion
        self.owner = owner
        self.scope = scope
        self.savedAt = savedAt
        self.activities = activities
        self.hasMore = hasMore
        self.nextCursor = nextCursor
    }
}

protocol FeedCacheStoring: Sendable {
    func load(owner: RecordingOwner, scope: FeedScope) async throws -> FeedCacheSnapshot?
    func save(_ snapshot: FeedCacheSnapshot) async throws
}

/// A small owner-bound first-paint cache. Exact user ID + wallet binding keeps
/// an account replacement from inheriting another rider's social feed.
actor FileFeedCache: FeedCacheStoring {
    static let shared = FileFeedCache()

    private let rootURL: URL
    private let fileManager: FileManager
    private let encoder: JSONEncoder
    private let decoder: JSONDecoder
    private let durableAccountWorkPermitted: @Sendable (RecordingOwner) -> Bool
    /// Exact-owner write fence. A feed request that began before account
    /// deletion may finish afterward; its detached save must not recreate the
    /// just-purged cache.
    private var accountDeletionFences: Set<String> = []

    init(
        rootURL: URL? = nil,
        fileManager: FileManager = .default,
        durableAccountWorkPermitted: @escaping @Sendable (RecordingOwner) -> Bool = {
            AccountDeletionLocalFence.permitsAccountWork(owner: $0)
        }
    ) {
        self.fileManager = fileManager
        self.durableAccountWorkPermitted = durableAccountWorkPermitted
        if let rootURL {
            self.rootURL = rootURL
        } else {
            let support = fileManager.urls(
                for: .applicationSupportDirectory,
                in: .userDomainMask
            ).first!
            self.rootURL = ProcessSandbox.isolatedIfTesting(
                support
                    .appendingPathComponent("BoulderRoller", isDirectory: true)
                    .appendingPathComponent("FeedCache", isDirectory: true),
                label: "FeedCache"
            )
        }
        let encoder = JSONEncoder()
        encoder.dateEncodingStrategy = .iso8601
        self.encoder = encoder
        let decoder = JSONDecoder()
        decoder.dateDecodingStrategy = .iso8601
        self.decoder = decoder
    }

    func load(owner: RecordingOwner, scope: FeedScope) async throws -> FeedCacheSnapshot? {
        guard permitsAccountWork(owner: owner) else { return nil }
        let url = fileURL(owner: owner, scope: scope)
        guard fileManager.fileExists(atPath: url.path) else { return nil }
        let snapshot = try decoder.decode(FeedCacheSnapshot.self, from: Data(contentsOf: url))
        guard snapshot.schemaVersion == FeedCacheSnapshot.currentSchemaVersion,
              snapshot.owner == owner,
              snapshot.scope == scope,
              permitsAccountWork(owner: owner)
        else { return nil }
        return snapshot
    }

    func save(_ snapshot: FeedCacheSnapshot) async throws {
        guard permitsAccountWork(owner: snapshot.owner) else {
            throw AccountDeletionLocalCleanupError.verificationFailed
        }
        try ensureDirectory()
        let url = fileURL(owner: snapshot.owner, scope: snapshot.scope)
        try encoder.encode(snapshot).write(to: url, options: .atomic)
        try fileManager.setAttributes(
            [.protectionKey: FileProtectionType.completeUntilFirstUserAuthentication],
            ofItemAtPath: url.path
        )
        guard permitsAccountWork(owner: snapshot.owner) else {
            // A durable deletion refusal can be armed outside this actor while
            // an already-returned page is crossing the atomic file boundary.
            // Never leave that late page behind the newly established fence.
            if fileManager.fileExists(atPath: url.path) {
                try fileManager.removeItem(at: url)
            }
            throw AccountDeletionLocalCleanupError.verificationFailed
        }
    }

    func purge(owner: RecordingOwner) throws {
        accountDeletionFences.insert(ownerKey(owner))
        for scope in FeedScope.allCases {
            let url = fileURL(owner: owner, scope: scope)
            if fileManager.fileExists(atPath: url.path) {
                try fileManager.removeItem(at: url)
            }
            guard !fileManager.fileExists(atPath: url.path) else {
                throw AccountDeletionLocalCleanupError.verificationFailed
            }
        }
    }

    func freeze(owner: RecordingOwner) {
        accountDeletionFences.insert(ownerKey(owner))
    }

    func unfreeze(owner: RecordingOwner) {
        guard durableAccountWorkPermitted(owner) else {
            return
        }
        accountDeletionFences.remove(ownerKey(owner))
    }

    private func ensureDirectory() throws {
        try fileManager.createDirectory(
            at: rootURL,
            withIntermediateDirectories: true,
            attributes: [.protectionKey: FileProtectionType.completeUntilFirstUserAuthentication]
        )
    }

    private func fileURL(owner: RecordingOwner, scope: FeedScope) -> URL {
        rootURL.appendingPathComponent("\(ownerKey(owner))-\(scope.rawValue).json")
    }

    private func ownerKey(_ owner: RecordingOwner) -> String {
        let exactOwner = Data("\(owner.id)\u{0}\(owner.wallet)".utf8)
        return SHA256.hash(data: exactOwner).map { String(format: "%02x", $0) }.joined()
    }

    private func permitsAccountWork(owner: RecordingOwner) -> Bool {
        !accountDeletionFences.contains(ownerKey(owner))
            && durableAccountWorkPermitted(owner)
    }
}
