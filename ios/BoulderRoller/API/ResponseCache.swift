import Foundation

/// Session read cache — stale-while-revalidate for read surfaces
/// (Tim, 2026-08-21: a second visit must not cost what the first did).
///
/// In-memory only, keyed by GET path+query, cleared on sign-out so one
/// owner's reads never outlive their session. Any mutation drops every
/// entry under the mutated resource, so a stale page cannot outlive a
/// write. Surfaces render a cached value instantly and revalidate quietly.
@MainActor
final class ResponseCache {
    static let shared = ResponseCache()

    private var entries: [String: (value: Any, storedAt: Date)] = [:]
    /// Insertion order for a bounded cache — the oldest read leaves first.
    private var order: [String] = []
    /// Final-write fence for reads that crossed an account clear while their
    /// network task was awaiting this actor.
    private(set) var accountBoundaryGeneration: UInt64 = 0
    static let capacity = 160

    nonisolated static func key(path: String, query: [URLQueryItem] = []) -> String {
        guard !query.isEmpty else { return path }
        let q = query
            .map { "\($0.name)=\($0.value ?? "")" }
            .sorted()
            .joined(separator: "&")
        return "\(path)?\(q)"
    }

    func value<T>(_ type: T.Type, path: String, query: [URLQueryItem] = []) -> T? {
        entries[Self.key(path: path, query: query)]?.value as? T
    }

    @discardableResult
    func store(
        _ value: Any,
        path: String,
        query: [URLQueryItem] = [],
        at date: Date = .now,
        ifAccountBoundaryGeneration expectedGeneration: UInt64? = nil
    ) -> Bool {
        if let expectedGeneration,
           expectedGeneration != accountBoundaryGeneration
        {
            return false
        }
        let key = Self.key(path: path, query: query)
        if entries[key] == nil { order.append(key) }
        entries[key] = (value, date)
        while order.count > Self.capacity, let oldest = order.first {
            order.removeFirst()
            entries.removeValue(forKey: oldest)
        }
        return true
    }

    /// Drop everything under a resource prefix ("/rides/123" drops the
    /// ride, its gps, patterns, and streams).
    func invalidate(pathPrefix: String) {
        entries = entries.filter { !$0.key.hasPrefix(pathPrefix) }
        order.removeAll { $0.hasPrefix(pathPrefix) }
    }

    func clear() {
        accountBoundaryGeneration &+= 1
        entries.removeAll()
        order.removeAll()
    }

    var count: Int { entries.count }

    /// The resource a mutation touches: the first two path segments
    /// ("/rides/123/photos" -> "/rides/123", "/users/me/avatar" -> "/users/me").
    nonisolated static func resourcePrefix(for path: String) -> String {
        let segments = path.split(separator: "/").prefix(2)
        return "/" + segments.joined(separator: "/")
    }
}
