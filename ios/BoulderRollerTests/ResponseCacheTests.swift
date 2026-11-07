import Foundation
import Testing
@testable import BoulderRoller

/// Stale-while-revalidate read cache: keyed by path+query, invalidated
/// under a mutated resource, cleared on sign-out.
@MainActor
struct ResponseCacheTests {
    @Test func storesAndReadsByPathAndQuery() {
        let cache = ResponseCache()
        cache.store("a", path: "/climbs/1")
        cache.store("b", path: "/rides/9/streams", query: [.init(name: "type", value: "power")])
        #expect(cache.value(String.self, path: "/climbs/1") == "a")
        #expect(cache.value(String.self, path: "/climbs/2") == nil)
        #expect(cache.value(
            String.self, path: "/rides/9/streams", query: [.init(name: "type", value: "power")]
        ) == "b")
        #expect(cache.value(
            String.self, path: "/rides/9/streams", query: [.init(name: "type", value: "speed")]
        ) == nil)
        // A type mismatch is a miss, never a crash.
        #expect(cache.value(Int.self, path: "/climbs/1") == nil)
    }

    @Test func mutationDropsEverythingUnderTheResource() {
        let cache = ResponseCache()
        cache.store("d", path: "/rides/9")
        cache.store("g", path: "/rides/9/gps")
        cache.store("p", path: "/rides/9/patterns")
        cache.store("other", path: "/rides/10")
        cache.store("c", path: "/climbs/1")
        cache.invalidate(pathPrefix: ResponseCache.resourcePrefix(for: "/rides/9/photos"))
        #expect(cache.value(String.self, path: "/rides/9") == nil)
        #expect(cache.value(String.self, path: "/rides/9/gps") == nil)
        #expect(cache.value(String.self, path: "/rides/9/patterns") == nil)
        #expect(cache.value(String.self, path: "/rides/10") == "other")
        #expect(cache.value(String.self, path: "/climbs/1") == "c")
    }

    @Test func resourcePrefixIsTheFirstTwoSegments() {
        #expect(ResponseCache.resourcePrefix(for: "/rides/9/photos") == "/rides/9")
        #expect(ResponseCache.resourcePrefix(for: "/users/me/avatar/init") == "/users/me")
        #expect(ResponseCache.resourcePrefix(for: "/vaults") == "/vaults")
    }

    @Test func clearDropsEverything() {
        let cache = ResponseCache()
        cache.store("a", path: "/a"); cache.store("b", path: "/b")
        cache.clear()
        #expect(cache.count == 0)
    }

    @Test func accountBoundaryRefusesAStoreThatStartedBeforeClear() {
        let cache = ResponseCache()
        let boundary = cache.accountBoundaryGeneration

        cache.clear()
        let stored = cache.store(
            "stale-owner",
            path: "/users/me",
            ifAccountBoundaryGeneration: boundary
        )

        #expect(stored == false)
        #expect(cache.value(String.self, path: "/users/me") == nil)
    }

    @Test func capacityEvictsTheOldestRead() {
        let cache = ResponseCache()
        for i in 0..<(ResponseCache.capacity + 5) {
            cache.store(i, path: "/p/\(i)")
        }
        #expect(cache.count == ResponseCache.capacity)
        #expect(cache.value(Int.self, path: "/p/0") == nil)
        #expect(cache.value(Int.self, path: "/p/\(ResponseCache.capacity + 4)") == ResponseCache.capacity + 4)
    }
}
