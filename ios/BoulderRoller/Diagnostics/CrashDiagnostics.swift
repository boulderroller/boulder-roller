import Foundation
import MetricKit
#if canImport(UIKit)
import UIKit
#endif

/// Zero-cost self-hosted crash reporting (bead `boulderroller-v2-odmi6.14`,
/// LIST THREE item 3). No SaaS, no SDK: MetricKit hands the app its own
/// crash/hang/CPU/disk diagnostics on the next launch; they are persisted to
/// a bounded local queue and POSTed to the backend's authenticated ingest
/// (`POST /mobile/diagnostics`) for later offline symbolication against the
/// archived dSYMs (`docs/runbooks/IOS_CRASH_SYMBOLICATION.md`).
///
/// Privacy: an envelope carries app/OS/device metadata and Apple's
/// diagnostic JSON only — no location, no ride payloads, no rider text.
/// Identity is server-side from the bearer token; nothing is uploaded while
/// signed out (the queue simply holds).
///
/// Simulator note: MetricKit never delivers diagnostics on the simulator —
/// that is exactly why the DEBUG forced-test path exists. It pushes one
/// clearly-labeled synthetic envelope through the REAL queue, uploader, and
/// deployed endpoint.
enum CrashReporting {
    private static let subscriber = MetricKitCrashSubscriber()
    private static var started = false

    /// Idempotent app-start hookup. DEBUG builds additionally honor the
    /// `-BRDebugForceCrashDiagnostic` launch argument.
    @MainActor
    static func start() {
        guard !started else { return }
        started = true
        MXMetricManager.shared.add(subscriber)
        #if DEBUG
        if ProcessInfo.processInfo.arguments.contains("-BRDebugForceCrashDiagnostic") {
            let boundary = DiagnosticQueue.captureAccountBoundary()
            Task {
                await DiagnosticQueue.shared.enqueue(
                    Self.debugForcedTestEnvelope(),
                    expectedAccountBoundary: boundary
                )
            }
        }
        #endif
    }

    /// Drain opportunity: app foreground and sign-in both call this. Quiet
    /// no-op when signed out or offline — files wait for the next chance.
    static func drainQueue() {
        Task { await DiagnosticUploader.shared.drain() }
    }

    #if DEBUG
    /// A synthetic diagnostic, honestly labeled as such at every layer
    /// (type + payload flag). It exists to prove the real pipeline
    /// end-to-end where MetricKit cannot fire (simulator).
    static func debugForcedTestEnvelope() -> [String: Any] {
        DiagnosticEnvelope.wireDict(
            diagnosticType: "debug_forced_test",
            payload: [
                "simulated": true,
                "note": "DEBUG forced test diagnostic - synthetic payload through the real queue, uploader, and deployed ingest",
                "callStackTree": [
                    "callStacks": [
                        [
                            "threadAttributed": true,
                            "callStackRootFrames": [
                                [
                                    "binaryName": "BoulderRoller",
                                    "address": 4_369_842_176,
                                    "offsetIntoBinaryTextSegment": 12_345,
                                ] as [String: Any],
                            ],
                        ] as [String: Any],
                    ],
                ],
            ]
        )
    }
    #endif
}

/// Envelope metadata assembly — shared by real MetricKit deliveries and the
/// DEBUG forced-test path so both exercise one wire shape.
enum DiagnosticEnvelope {
    static func wireDict(diagnosticType: String, payload: [String: Any]) -> [String: Any] {
        [
            "schema": 1,
            "diagnostic_type": diagnosticType,
            "captured_at": ISO8601DateFormatter().string(from: .now),
            "app_version": Bundle.main.object(
                forInfoDictionaryKey: "CFBundleShortVersionString"
            ) as? String ?? "unknown",
            "build_number": Bundle.main.object(
                forInfoDictionaryKey: "CFBundleVersion"
            ) as? String ?? "unknown",
            "os_version": ProcessInfo.processInfo.operatingSystemVersionString,
            "device_model": Self.deviceModel(),
            "payload": payload,
        ]
    }

    static func deviceModel() -> String {
        var systemInfo = utsname()
        uname(&systemInfo)
        return withUnsafePointer(to: &systemInfo.machine) { pointer in
            pointer.withMemoryRebound(to: CChar.self, capacity: 1) { cString in
                String(validatingCString: cString) ?? "unknown"
            }
        }
    }
}

/// MetricKit subscriber: flattens each payload's diagnostics into typed
/// envelopes and enqueues them. Delivery happens on MetricKit's own queue;
/// everything downstream is actor-isolated.
final class MetricKitCrashSubscriber: NSObject, MXMetricManagerSubscriber {
    func didReceive(_ payloads: [MXDiagnosticPayload]) {
        var envelopes: [[String: Any]] = []
        for payload in payloads {
            for diagnostic in payload.crashDiagnostics ?? [] {
                envelopes.append(envelope(type: "crash", diagnostic: diagnostic))
            }
            for diagnostic in payload.hangDiagnostics ?? [] {
                envelopes.append(envelope(type: "hang", diagnostic: diagnostic))
            }
            for diagnostic in payload.cpuExceptionDiagnostics ?? [] {
                envelopes.append(envelope(type: "cpu_exception", diagnostic: diagnostic))
            }
            for diagnostic in payload.diskWriteExceptionDiagnostics ?? [] {
                envelopes.append(envelope(type: "disk_write_exception", diagnostic: diagnostic))
            }
            for diagnostic in payload.appLaunchDiagnostics ?? [] {
                envelopes.append(envelope(type: "app_launch", diagnostic: diagnostic))
            }
        }
        guard !envelopes.isEmpty else { return }
        let boundary = DiagnosticQueue.captureAccountBoundary()
        Task {
            for envelope in envelopes {
                await DiagnosticQueue.shared.enqueue(
                    envelope,
                    expectedAccountBoundary: boundary
                )
            }
            await DiagnosticUploader.shared.drain()
        }
    }

    private func envelope(type: String, diagnostic: MXDiagnostic) -> [String: Any] {
        let json = diagnostic.jsonRepresentation()
        let payload = (try? JSONSerialization.jsonObject(with: json) as? [String: Any])
            ?? ["raw_b64": json.base64EncodedString()]
        return DiagnosticEnvelope.wireDict(diagnosticType: type, payload: payload ?? [:])
    }
}

/// Bounded on-disk queue. One JSON file per envelope under Application
/// Support/Diagnostics/pending; FIFO eviction beyond `maxFiles`; single
/// envelopes above `maxBytesPerFile` are dropped with a truthful log line
/// (matching the server-side per-diagnostic cap) rather than truncated into
/// unsymbolicatable fragments.
actor DiagnosticQueue {
    static let shared = DiagnosticQueue()

    static let maxFiles = 24
    static let maxBytesPerFile = 512 * 1024

    private let directory: URL
    private let accountWorkPermitted: @Sendable () -> Bool
    private let beforePersist: @Sendable () async -> Void
    /// Last sortable filename prefix allocated by this actor. Seeded from the
    /// on-disk queue so a same-millisecond burst (or a clock step backward)
    /// still has a strict FIFO order across actor recreation.
    private var lastFilenameOrder: Int64?

    private static let boundaryLock = NSLock()
    private static var accountBoundary: UInt64 = 0

    init(
        directory: URL? = nil,
        accountWorkPermitted: @escaping @Sendable () -> Bool = {
            AccountDeletionLocalFence.permitsCachedOwnerAccountWork
        },
        beforePersist: @escaping @Sendable () async -> Void = {}
    ) {
        self.directory = directory ?? FileManager.default
            .urls(for: .applicationSupportDirectory, in: .userDomainMask)[0]
            .appendingPathComponent("Diagnostics/pending", isDirectory: true)
        self.accountWorkPermitted = accountWorkPermitted
        self.beforePersist = beforePersist
    }

    nonisolated static func captureAccountBoundary() -> UInt64 {
        boundaryLock.withLock { accountBoundary }
    }

    private nonisolated static func advanceAccountBoundary() {
        boundaryLock.withLock { accountBoundary &+= 1 }
    }

    func enqueue(
        _ envelope: [String: Any],
        expectedAccountBoundary: UInt64 = DiagnosticQueue.captureAccountBoundary()
    ) async {
        guard accountWorkPermitted(),
              expectedAccountBoundary == Self.captureAccountBoundary(),
              JSONSerialization.isValidJSONObject(envelope),
              let data = try? JSONSerialization.data(withJSONObject: envelope)
        else { return }
        guard data.count <= Self.maxBytesPerFile else {
            print("[CrashDiagnostics] dropping oversize diagnostic (\(data.count) bytes)")
            return
        }
        await beforePersist()
        guard accountWorkPermitted(),
              expectedAccountBoundary == Self.captureAccountBoundary()
        else { return }
        try? FileManager.default.createDirectory(
            at: directory, withIntermediateDirectories: true
        )
        let name = "\(nextFilenameOrder())-\(UUID().uuidString).json"
        let destination = directory.appendingPathComponent(name)
        try? data.write(to: destination, options: [.atomic])
        guard accountWorkPermitted(),
              expectedAccountBoundary == Self.captureAccountBoundary()
        else {
            try? FileManager.default.removeItem(at: destination)
            if pendingFiles().isEmpty {
                try? FileManager.default.removeItem(at: directory)
            }
            return
        }
        evictBeyondCap()
    }

    private func nextFilenameOrder() -> Int64 {
        if lastFilenameOrder == nil {
            lastFilenameOrder = pendingFiles().compactMap { file in
                Int64(file.lastPathComponent.split(separator: "-", maxSplits: 1)[0])
            }.max()
        }
        let wallClockOrder = Int64(Date.now.timeIntervalSince1970 * 1_000)
        let order = max(wallClockOrder, (lastFilenameOrder ?? (wallClockOrder - 1)) + 1)
        lastFilenameOrder = order
        return order
    }

    /// Oldest-first pending files (filename sort = strict persistence order).
    func pendingFiles() -> [URL] {
        let contents = (try? FileManager.default.contentsOfDirectory(
            at: directory, includingPropertiesForKeys: nil
        )) ?? []
        return contents
            .filter { $0.pathExtension == "json" }
            .sorted { $0.lastPathComponent < $1.lastPathComponent }
    }

    func remove(_ url: URL) {
        try? FileManager.default.removeItem(at: url)
    }

    func purge() throws {
        Self.advanceAccountBoundary()
        if FileManager.default.fileExists(atPath: directory.path) {
            try FileManager.default.removeItem(at: directory)
        }
        guard !FileManager.default.fileExists(atPath: directory.path) else {
            throw AccountDeletionLocalCleanupError.verificationFailed
        }
    }

    private func evictBeyondCap() {
        let files = pendingFiles()
        guard files.count > Self.maxFiles else { return }
        for stale in files.prefix(files.count - Self.maxFiles) {
            try? FileManager.default.removeItem(at: stale)
        }
    }
}

/// Uploads queued envelopes to the authenticated ingest. Files are deleted
/// only on server acceptance; auth or network failure leaves them for the
/// next drain (foreground / sign-in).
actor DiagnosticUploader {
    static let shared = DiagnosticUploader()

    /// Server contract mirror: at most 4 envelopes per request.
    static let maxPerRequest = 4

    private var draining = false

    func drain() async {
        guard !draining else { return }
        draining = true
        defer { draining = false }

        guard AccountDeletionLocalFence.permitsCachedOwnerAccountWork,
              await APIClient.shared.isAuthenticated,
              AccountDeletionLocalFence.permitsCachedOwnerAccountWork
        else { return }
        let files = await DiagnosticQueue.shared.pendingFiles()
        guard !files.isEmpty else { return }

        for batch in stride(from: 0, to: files.count, by: Self.maxPerRequest).map({
            Array(files[$0..<min($0 + Self.maxPerRequest, files.count)])
        }) {
            guard AccountDeletionLocalFence.permitsCachedOwnerAccountWork else { return }
            var envelopes: [[String: Any]] = []
            var readable: [URL] = []
            for url in batch {
                guard let data = try? Data(contentsOf: url),
                      let object = try? JSONSerialization.jsonObject(with: data) as? [String: Any]
                else {
                    // Unreadable file: nothing a retry can recover.
                    await DiagnosticQueue.shared.remove(url)
                    continue
                }
                envelopes.append(object)
                readable.append(url)
            }
            guard !envelopes.isEmpty else { continue }
            guard AccountDeletionLocalFence.permitsCachedOwnerAccountWork else { return }
            do {
                _ = try await APIClient.shared.postDiagnostics(envelopes)
                for url in readable {
                    await DiagnosticQueue.shared.remove(url)
                }
            } catch {
                // Auth/network/server failure: keep the files, stop the pass.
                return
            }
        }
    }
}
