import Foundation
import Testing
import UIKit
@testable import BoulderRoller

/// Avatar and ride-photo images are cached by identity (URL without its
/// signature query), so a re-signed URL still hits.
struct RemoteImageCacheTests {
    @Test func keyIgnoresTheSignatureQuery() {
        let a = URL(string: "https://storage.example/avatars/u1.jpg?token=abc&expires=1")!
        let b = URL(string: "https://storage.example/avatars/u1.jpg?token=xyz&expires=2")!
        let other = URL(string: "https://storage.example/avatars/u2.jpg?token=abc")!
        #expect(RemoteImageCache.key(for: a) == RemoteImageCache.key(for: b))
        #expect(RemoteImageCache.key(for: a) != RemoteImageCache.key(for: other))
        #expect(RemoteImageCache.key(for: a) == "https://storage.example/avatars/u1.jpg")
    }

    @Test func storeThenHitAcrossResignedURLs() {
        let cache = RemoteImageCache(permitsAccountWork: { true })
        let image = UIGraphicsImageRenderer(size: CGSize(width: 4, height: 4)).image { _ in }
        cache.store(image, for: URL(string: "https://s.example/p/1.jpg?sig=1")!)
        #expect(cache.image(for: URL(string: "https://s.example/p/1.jpg?sig=2")!) != nil)
        #expect(cache.image(for: URL(string: "https://s.example/p/2.jpg?sig=1")!) == nil)
        cache.removeAll()
        #expect(cache.image(for: URL(string: "https://s.example/p/1.jpg?sig=1")!) == nil)
    }

    @Test func inFlightStoreCannotSurviveAnAccountBoundaryAdvance() async {
        let enteredStore = RemoteImageCacheGate()
        let releaseStore = DispatchSemaphore(value: 0)
        let advanceStarted = RemoteImageCacheGate()
        let cache = RemoteImageCache(
            beforeStore: {
                enteredStore.signal()
                releaseStore.wait()
            },
            permitsAccountWork: { true }
        )
        let url = URL(string: "https://s.example/p/deleted.jpg?sig=1")!
        let boundary = cache.captureAccountBoundary()
        let image = UIGraphicsImageRenderer(size: CGSize(width: 4, height: 4)).image { _ in }
        // These synchronous operations deliberately contend on the cache lock.
        // Keep blocked workers off Swift's cooperative executor; the test only
        // suspends on explicit entry and completion signals, never deadlines.
        let store = Task {
            await withCheckedContinuation { completion in
                DispatchQueue(label: "RemoteImageCacheTests.store").async {
                    completion.resume(returning: cache.store(image, for: url, at: boundary))
                }
            }
        }
        await enteredStore.wait()
        let advance = Task {
            await withCheckedContinuation { (completion: CheckedContinuation<Void, Never>) in
                DispatchQueue(label: "RemoteImageCacheTests.advance").async {
                    advanceStarted.signal()
                    cache.advanceAccountBoundary()
                    completion.resume()
                }
            }
        }
        await advanceStarted.wait()

        releaseStore.signal()
        let stored = await store.value
        await advance.value

        #expect(stored)
        #expect(cache.captureAccountBoundary() == boundary &+ 1)
        #expect(cache.image(for: url) == nil)
    }
}

private final class RemoteImageCacheGate: @unchecked Sendable {
    private let lock = NSLock()
    private var signaled = false
    private var waiter: CheckedContinuation<Void, Never>?

    func signal() {
        let pending = lock.withLock {
            signaled = true
            defer { waiter = nil }
            return waiter
        }
        pending?.resume()
    }

    func wait() async {
        await withCheckedContinuation { continuation in
            let alreadySignaled = lock.withLock {
                if signaled { return true }
                precondition(waiter == nil)
                waiter = continuation
                return false
            }
            if alreadySignaled { continuation.resume() }
        }
    }
}
