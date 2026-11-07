import SwiftUI
import UIKit

/// Memory-only image cache for avatars and ride photos (grout pass 3,
/// 2026-08-21). Keyed by identity, not by signed URL: storage URLs carry a
/// fresh signature on every response, which defeats URLCache — so the key
/// is the URL without its query. Cost-limited and emptied under memory
/// pressure by NSCache itself.
final class RemoteImageCache: @unchecked Sendable {
    static let shared = RemoteImageCache()

    private let cache: NSCache<NSString, UIImage> = {
        let c = NSCache<NSString, UIImage>()
        c.totalCostLimit = 32 * 1024 * 1024
        return c
    }()
    private let boundaryLock = NSLock()
    private var accountBoundary: UInt64 = 0
    private let beforeStore: @Sendable () -> Void
    private let permitsAccountWork: @Sendable () -> Bool

    init(
        beforeStore: @escaping @Sendable () -> Void = {},
        permitsAccountWork: @escaping @Sendable () -> Bool = {
            AccountDeletionLocalFence.permitsCachedOwnerAccountWork
        }
    ) {
        self.beforeStore = beforeStore
        self.permitsAccountWork = permitsAccountWork
    }

    /// Identity for a signed storage URL: scheme + host + path, no query.
    static func key(for url: URL) -> String {
        var components = URLComponents(url: url, resolvingAgainstBaseURL: false)
        components?.query = nil
        components?.fragment = nil
        return components?.string ?? url.absoluteString
    }

    func image(for url: URL) -> UIImage? {
        boundaryLock.withLock {
            cache.object(forKey: Self.key(for: url) as NSString)
        }
    }

    func store(_ image: UIImage, for url: URL) {
        let boundary = captureAccountBoundary()
        _ = store(image, for: url, at: boundary)
    }

    @discardableResult
    func store(_ image: UIImage, for url: URL, at boundary: UInt64) -> Bool {
        boundaryLock.withLock {
            guard boundary == accountBoundary else { return false }
            guard permitsAccountWork() else { return false }
            let cost = Int(image.size.width * image.size.height * image.scale * image.scale * 4)
            beforeStore()
            cache.setObject(image, forKey: Self.key(for: url) as NSString, cost: cost)
            return true
        }
    }

    func removeAll() {
        boundaryLock.withLock { cache.removeAllObjects() }
    }

    func captureAccountBoundary() -> UInt64 {
        boundaryLock.withLock { accountBoundary }
    }

    func advanceAccountBoundary() {
        boundaryLock.withLock {
            accountBoundary &+= 1
            cache.removeAllObjects()
        }
    }
}

private enum RemoteImageLoader {
    static let session: URLSession = {
        let configuration = URLSessionConfiguration.ephemeral
        configuration.urlCache = nil
        configuration.requestCachePolicy = .reloadIgnoringLocalCacheData
        return URLSession(configuration: configuration)
    }()
}

/// Drop-in for AsyncImage on identity-stable remote images: a cached image
/// paints synchronously on first layout (no flash), a miss loads once and
/// stores. `content` receives the image; `placeholder` fills until then.
struct CachedRemoteImage<Content: View, Placeholder: View>: View {
    let url: URL?
    @ViewBuilder var content: (Image) -> Content
    @ViewBuilder var placeholder: () -> Placeholder

    @State private var loaded: UIImage?

    private var cached: UIImage? {
        url.flatMap { RemoteImageCache.shared.image(for: $0) }
    }

    var body: some View {
        Group {
            if let image = cached ?? loaded {
                content(Image(uiImage: image))
            } else {
                placeholder()
            }
        }
        .task(id: url) {
            guard let url, cached == nil else { return }
            let accountBoundary = RemoteImageCache.shared.captureAccountBoundary()
            guard let (data, response) = try? await RemoteImageLoader.session.data(from: url),
                  (200..<300).contains((response as? HTTPURLResponse)?.statusCode ?? 0)
            else { return }
            // Decode off the main actor so a large ride photo never stalls
            // the scroll it appears in.
            let decoded = await Task.detached(priority: .userInitiated) {
                UIImage(data: data)?.preparingForDisplay()
            }.value
            guard let image = decoded else { return }
            guard RemoteImageCache.shared.store(image, for: url, at: accountBoundary) else {
                return
            }
            loaded = image
        }
    }
}
