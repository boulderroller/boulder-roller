import Foundation
import XCTest
@testable import BoulderRoller

/// Crash-reporting floor (bead `boulderroller-v2-odmi6.14`, LIST THREE
/// item 3): the persisted diagnostic queue is bounded, honest about what it
/// drops, and the wire envelope carries exactly the metadata the
/// symbolication runbook needs — no location, no ride payloads.
final class CrashDiagnosticsTests: XCTestCase {
    private var directory: URL!
    private var queue: DiagnosticQueue!

    override func setUp() {
        super.setUp()
        directory = FileManager.default.temporaryDirectory
            .appendingPathComponent("crash-diag-tests-\(UUID().uuidString)", isDirectory: true)
        queue = DiagnosticQueue(
            directory: directory,
            accountWorkPermitted: { true }
        )
    }

    override func tearDown() {
        try? FileManager.default.removeItem(at: directory)
        super.tearDown()
    }

    func testEnqueuePersistsRoundTrippableEnvelope() async {
        let envelope = DiagnosticEnvelope.wireDict(
            diagnosticType: "crash",
            payload: ["callStackTree": ["callStacks": []]]
        )
        await queue.enqueue(envelope)

        let files = await queue.pendingFiles()
        XCTAssertEqual(files.count, 1)
        let data = try? Data(contentsOf: files[0])
        let object = data.flatMap {
            try? JSONSerialization.jsonObject(with: $0) as? [String: Any]
        }
        XCTAssertEqual(object?["diagnostic_type"] as? String, "crash")
        XCTAssertEqual(object?["schema"] as? Int, 1)
        XCTAssertNotNil(object?["app_version"])
        XCTAssertNotNil(object?["build_number"])
        XCTAssertNotNil(object?["os_version"])
        XCTAssertNotNil(object?["device_model"])
        XCTAssertNotNil(object?["payload"])
    }

    /// The envelope schema is closed: metadata + payload only. No location,
    /// no ride identifiers, no rider text can ride along unnoticed.
    func testEnvelopeCarriesOnlyTheClosedMetadataSet() {
        let envelope = DiagnosticEnvelope.wireDict(
            diagnosticType: "hang", payload: ["simulated": true]
        )
        XCTAssertEqual(
            Set(envelope.keys),
            [
                "schema", "diagnostic_type", "captured_at", "app_version",
                "build_number", "os_version", "device_model", "payload",
            ]
        )
    }

    func testQueueEvictsOldestBeyondCap() async {
        for index in 0..<(DiagnosticQueue.maxFiles + 5) {
            await queue.enqueue(
                DiagnosticEnvelope.wireDict(
                    diagnosticType: "crash", payload: ["index": index]
                )
            )
        }
        let files = await queue.pendingFiles()
        XCTAssertEqual(files.count, DiagnosticQueue.maxFiles)

        // The survivors are the newest: the oldest five indices are gone.
        let survivingIndices = files.compactMap { url -> Int? in
            guard let data = try? Data(contentsOf: url),
                  let object = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
                  let payload = object["payload"] as? [String: Any]
            else { return nil }
            return payload["index"] as? Int
        }
        XCTAssertEqual(survivingIndices.min(), 5)
    }

    /// An envelope above the per-file cap is dropped whole — matching the
    /// server cap — never truncated into an unsymbolicatable fragment.
    func testOversizeEnvelopeIsDroppedNotTruncated() async {
        let oversized = DiagnosticEnvelope.wireDict(
            diagnosticType: "crash",
            payload: ["blob": String(repeating: "x", count: DiagnosticQueue.maxBytesPerFile)]
        )
        await queue.enqueue(oversized)
        let files = await queue.pendingFiles()
        XCTAssertTrue(files.isEmpty)
    }

    func testPendingFilesAreOldestFirstAndRemovable() async {
        await queue.enqueue(
            DiagnosticEnvelope.wireDict(diagnosticType: "crash", payload: ["n": 1])
        )
        // Millisecond filename prefix orders same-run enqueues.
        try? await Task.sleep(for: .milliseconds(3))
        await queue.enqueue(
            DiagnosticEnvelope.wireDict(diagnosticType: "hang", payload: ["n": 2])
        )
        var files = await queue.pendingFiles()
        XCTAssertEqual(files.count, 2)
        XCTAssertLessThan(files[0].lastPathComponent, files[1].lastPathComponent)

        await queue.remove(files[0])
        files = await queue.pendingFiles()
        XCTAssertEqual(files.count, 1)
    }

    func testDeletionPurgeInvalidatesAlreadyQueuedDiagnosticContinuation() async throws {
        let gate = DiagnosticPersistGate()
        let gatedQueue = DiagnosticQueue(
            directory: directory,
            accountWorkPermitted: { true },
            beforePersist: { await gate.pause() }
        )
        let boundary = DiagnosticQueue.captureAccountBoundary()
        let enqueue = Task {
            await gatedQueue.enqueue(
                DiagnosticEnvelope.wireDict(
                    diagnosticType: "crash",
                    payload: ["queued_before_deletion": true]
                ),
                expectedAccountBoundary: boundary
            )
        }
        await gate.waitUntilPaused()

        try await gatedQueue.purge()
        await gate.release()
        await enqueue.value

        let files = await gatedQueue.pendingFiles()
        XCTAssertTrue(files.isEmpty, "a pre-cleanup continuation cannot recreate diagnostics")
    }

    #if DEBUG
    /// The forced-test envelope is honest at every layer: its type names it
    /// and its payload flags itself simulated.
    func testDebugForcedTestEnvelopeIsLabeledSynthetic() {
        let envelope = CrashReporting.debugForcedTestEnvelope()
        XCTAssertEqual(envelope["diagnostic_type"] as? String, "debug_forced_test")
        let payload = envelope["payload"] as? [String: Any]
        XCTAssertEqual(payload?["simulated"] as? Bool, true)
    }
    #endif
}

private actor DiagnosticPersistGate {
    private var paused = false
    private var continuation: CheckedContinuation<Void, Never>?

    func pause() async {
        paused = true
        await withCheckedContinuation { continuation in
            self.continuation = continuation
        }
    }

    func waitUntilPaused() async {
        while !paused { await Task.yield() }
    }

    func release() {
        continuation?.resume()
        continuation = nil
    }
}
