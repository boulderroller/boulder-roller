import Foundation
import SwiftUI
import UIKit
import WorkoutParse
import XCTest
@testable import BoulderRoller

@MainActor
final class ImportProfileTests: XCTestCase {
    /// Optional corpus probe: the ignored real FIT is supplied by the local
    /// validation corpus. No profile fixture and no network/publication handoff.
    func testRealFITImportDrawsReadingSpine() async throws {
        let repo = URL(fileURLWithPath: #filePath).deletingLastPathComponent()
            .deletingLastPathComponent().deletingLastPathComponent()
        let file = repo.appendingPathComponent("tests/validation/in_the_bag_.fit")
        guard FileManager.default.fileExists(atPath: file.path) else {
            throw XCTSkip("Supply tests/validation/in_the_bag_.fit for the real-file simulator probe")
        }
        let root = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        defer { try? FileManager.default.removeItem(at: root) }
        let store = FileRideUploadJobStore(rootURL: root)
        let runtime = makeLocalRuntime(store: store)
        let user = RideUploadRenderFixtureData.rider
        await runtime.activate(user: user)
        let model = ImportModel()
        let scene = try XCTUnwrap(UIApplication.shared.connectedScenes.first as? UIWindowScene)
        let previousWindow = scene.windows.first(where: \.isKeyWindow)
        let window = UIWindow(windowScene: scene)
        window.rootViewController = UIHostingController(rootView:
            ImportProfileProbeView(model: model).preferredColorScheme(.dark))
        window.makeKeyAndVisible()
        defer { window.isHidden = true; previousWindow?.makeKey() }
        let run = Task { await model.run(fileURL: file, user: user, uploadRuntime: runtime) }
        for _ in 0..<1000 {
            if !model.spine.runs.isEmpty || !model.stageIsWorking { break }
            try await Task.sleep(for: .milliseconds(10))
        }
        XCTAssertEqual(model.spine.runs.first?.count, 64)
        guard !model.spine.runs.isEmpty else { await run.value; return }
        let readingStart = ContinuousClock.now
        try await ContinuousClock().sleep(until: readingStart.advanced(by: .milliseconds(250)))
        XCTAssertTrue(model.stageIsWorking, "Reading must stay visible while the supplied spine draws")
        capture(window, name: "real-fit-reading-early")
        try await ContinuousClock().sleep(until: readingStart.advanced(by: .milliseconds(750)))
        XCTAssertTrue(model.stageIsWorking)
        capture(window, name: "real-fit-reading-late")
        await run.value
        XCTAssertTrue(model.wasPersisted)
        let jobs = try await store.jobs(ownerID: user.id)
        XCTAssertEqual(jobs.count, 1)
        XCTAssertEqual(jobs.first?.phase, .awaitingPrivacyReview)
        XCTAssertFalse(jobs.first?.attemptedServerHandoff ?? true)
        let profile = try JSONEncoder().encode(model.spine)
        let attachment = XCTAttachment(data: profile, uniformTypeIdentifier: "public.json")
        attachment.name = "real-fit-profile"
        attachment.lifetime = .keepAlways
        add(attachment)
    }

    private func capture(_ window: UIWindow, name: String) {
        let image = UIGraphicsImageRenderer(bounds: window.bounds).image { _ in
            window.drawHierarchy(in: window.bounds, afterScreenUpdates: false)
        }
        let attachment = XCTAttachment(image: image)
        attachment.name = name
        attachment.lifetime = .keepAlways
        add(attachment)
    }

    func testImportPublishesParserProfileAndPreservesLocalCustody() async throws {
        let root = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        try FileManager.default.createDirectory(at: root, withIntermediateDirectories: true)
        defer { try? FileManager.default.removeItem(at: root) }
        let file = root.appendingPathComponent("ride.gpx")
        let bytes = Data("""
        <?xml version="1.0"?><gpx><trk><trkseg>
        <trkpt lat="40.0" lon="-75.0"><ele>100</ele><time>2026-09-06T12:00:00Z</time></trkpt>
        <trkpt lat="40.001" lon="-75.0"><ele>120</ele><time>2026-09-06T12:01:00Z</time></trkpt>
        <trkpt lat="40.002" lon="-75.0"><ele>110</ele><time>2026-09-06T12:02:00Z</time></trkpt>
        </trkseg></trk></gpx>
        """.utf8)
        try bytes.write(to: file)
        let expected = try await WorkoutParser.preliminarySummary(data: bytes, kind: .gpx, thresholdWatts: nil)
        let store = FileRideUploadJobStore(rootURL: root.appendingPathComponent("jobs"))
        let runtime = makeLocalRuntime(store: store)
        let user = RideUploadRenderFixtureData.rider
        await runtime.activate(user: user)
        let model = ImportModel()
        await model.run(fileURL: file, user: user, uploadRuntime: runtime)
        XCTAssertTrue(model.wasPersisted)
        XCTAssertFalse(model.spine.runs.isEmpty)
        XCTAssertEqual(model.spine.runs.first?.map(\.distanceM), expected.elevationProfile.map(\.distanceM))
        XCTAssertEqual(model.spine.runs.first?.map(\.elevationM), expected.elevationProfile.map(\.elevationM))
        XCTAssertTrue(model.spine.spans.isEmpty)
        let jobs = try await store.jobs(ownerID: user.id)
        XCTAssertEqual(jobs.count, 1)
        XCTAssertEqual(jobs.first?.phase, .awaitingPrivacyReview)
        XCTAssertEqual(jobs.first?.localSummary.distanceM, Double(expected.distanceM))
        XCTAssertFalse(jobs.first?.attemptedServerHandoff ?? true)
    }

    private func makeLocalRuntime(store: FileRideUploadJobStore) -> RideUploadRuntime {
        RideUploadRuntime(
            store: store,
            transfer: ImportProfileTransfer(),
            // These probes exercise parsing and file-backed custody. Their
            // account state must not depend on a simulator keychain or on
            // deletion records left by another test. The real fence policy
            // still evaluates an explicitly unfenced test account.
            durableAccountWorkPermitted: { owner in
                AccountDeletionLocalFence.permitsAccountWork(
                    owner: owner,
                    sessionRecords: [],
                    capabilityState: .none
                )
            },
            immediateReconcile: { _, _ in
                XCTFail("Import must remain local until publication review")
            }
        )
    }
}

private struct ImportProfileTransfer: RideFileTransferring {
    func isActive(jobID: String) async -> Bool { false }
    func persistedBodyJobIDs() async throws -> Set<String> { [] }
    func cancel(jobIDs: Set<String>) async throws {}

    func upload(jobID: String, signedURL: String, sourceURL: URL, fileName: String) async throws {
        XCTFail("Import must not transfer bytes before publication review")
        throw URLError(.unsupportedURL)
    }
}

private struct ImportProfileProbeView: View {
    let model: ImportModel
    var body: some View {
        ProcessingBeat(spine: model.spine)
    }
}
