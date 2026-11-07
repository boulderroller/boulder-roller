import CoreLocation
import Foundation
import WorkoutParse
import XCTest
@testable import BoulderRoller

/// Test-target convenience keeps older direct-runtime fixtures concise while
/// production callers must always present the exact active ID + wallet.
private extension RideRecordingRuntime {
    func gateActiveOwner() throws -> RecordingOwner {
        guard let owner = activeOwnerForTesting() else {
            throw LiveRideCustodyError.ownerMismatch
        }
        return owner
    }

    func ingest(
        _ fix: RecordingSessionFix,
        wallNow: Date,
        monotonicNowS: TimeInterval? = nil
    ) async throws -> (RecordingSessionIngestOutcome, RecordingSessionProjection) {
        try await ingest(
            fix,
            wallNow: wallNow,
            monotonicNowS: monotonicNowS,
            owner: gateActiveOwner()
        )
    }

    func tick(
        at timestamp: Date,
        powerObservation: PowerObservation?
    ) async throws -> RecordingSessionProjection {
        try await tick(
            at: timestamp,
            powerObservation: powerObservation,
            owner: gateActiveOwner()
        )
    }

    func retryPendingCapture(
        expectedFix: RecordingSessionFix,
        wallNow: Date
    ) async throws -> (RecordingSessionIngestOutcome, RecordingSessionProjection) {
        try await retryPendingCapture(
            expectedFix: expectedFix,
            wallNow: wallNow,
            owner: gateActiveOwner()
        )
    }

    func manualPause(
        at timestamp: Date,
        monotonicNowS: TimeInterval? = nil
    ) async throws -> RecordingSessionProjection {
        try await manualPause(
            at: timestamp,
            monotonicNowS: monotonicNowS,
            owner: gateActiveOwner()
        )
    }

    func manualResume(
        at timestamp: Date,
        monotonicNowS: TimeInterval? = nil
    ) async throws -> RecordingSessionProjection {
        try await manualResume(
            at: timestamp,
            monotonicNowS: monotonicNowS,
            owner: gateActiveOwner()
        )
    }

    func stop(
        at timestamp: Date,
        monotonicNowS: TimeInterval? = nil
    ) async throws -> FinalizedRecording {
        try await stop(
            at: timestamp,
            monotonicNowS: monotonicNowS,
            owner: gateActiveOwner()
        )
    }

    func suspendActive(at timestamp: Date) async throws {
        try await suspendActive(at: timestamp, owner: gateActiveOwner())
    }
}

final class NativeGate1CustodyTests: XCTestCase {
    private var rootURL: URL!
    private let masterKey = Data((0..<32).map(UInt8.init))
    private let start = Date(timeIntervalSince1970: 1_800_000_000)

    override func setUpWithError() throws {
        AccountDeletionSessionRecordStore.clear()
        rootURL = FileManager.default.temporaryDirectory.appendingPathComponent(
            "NativeGate1CustodyTests-\(UUID().uuidString)",
            isDirectory: true
        )
    }

    func testDeletionProcessFenceRejectsStaleRecordingMutationsBeforeDeactivationRuns() async throws {
        let custody = makeCustody(at: rootURL)
        let queue = GateUploadQueue()
        let clock = GateClock(wall: start, monotonic: 100)
        let rideID = "11111111-1111-4111-8111-111111111111"
        let runtime = makeRuntime(
            custody: custody,
            queue: queue,
            clock: clock,
            ids: GateIDSequence([rideID]),
            accountWorkPermitted: { owner in
                AccountDeletionLocalFence.permitsAccountWork(
                    owner: owner,
                    sessionRecords: AccountDeletionProcessFence.records(),
                    capabilityStates: [.none]
                )
            }
        )
        let user = fixtureUser(
            id: "deletion-stale-recorder",
            wallet: "deletion-stale-recorder-wallet"
        )
        let owner = RecordingOwner(user: user)
        _ = try await runtime.activate(user: user)
        _ = try await runtime.start(user: user, at: start)

        AccountDeletionProcessFence.record(
            AccountDeletionSessionRecord(state: .pending, owner: owner)
        )

        do {
            _ = try await runtime.ingest(
                fixtureFix(
                    capturedAt: start.addingTimeInterval(1),
                    latitude: 39.95
                ),
                wallNow: start.addingTimeInterval(1),
                owner: owner
            )
            XCTFail("a stale location callback cannot write after deletion truth lands")
        } catch LiveRideCustodyError.ownerMismatch {}
        do {
            _ = try await runtime.stop(
                at: start.addingTimeInterval(2),
                owner: owner
            )
            XCTFail("a stale End action cannot finalize after deletion truth lands")
        } catch LiveRideCustodyError.ownerMismatch {}

        let persisted = try await custody.persisted(owner: owner, rideID: rideID)
        XCTAssertEqual(persisted.events.map(\.kind), [.start])
    }

    func testAccountDeletionBlocksAndPreservesOwnerlessCustodyQuarantine() async throws {
        let custody = makeCustody(at: rootURL)
        let quarantine = rootURL.appendingPathComponent("Quarantine", isDirectory: true)
        let orphan = quarantine.appendingPathComponent("orphan-recording", isDirectory: true)
        try FileManager.default.createDirectory(at: orphan, withIntermediateDirectories: true)
        try Data("ownerless-custody".utf8).write(
            to: orphan.appendingPathComponent("manifest.sealed")
        )
        let owner = RecordingOwner(id: "rider-delete", wallet: "wallet-delete")

        do {
            _ = try await custody.accountDeletionRecords(owner: owner)
            XCTFail("ownerless quarantine must make inventory unavailable")
        } catch {}
        do {
            try await custody.purgeAccount(owner: owner)
            XCTFail("ownerless quarantine must block destructive cleanup")
        } catch {}
        XCTAssertTrue(FileManager.default.fileExists(atPath: orphan.path))
    }

    func testAccountDeletionBlocksAndPreservesHiddenExactOwnerCustodyArtifact() async throws {
        let custody = makeCustody(at: rootURL)
        let owner = RecordingOwner(id: "rider-delete", wallet: "wallet-delete")
        let rideID = "11111111-1111-4111-8111-111111111111"
        try await custody.create(owner: owner, rideID: rideID, startedAt: start)
        let ownerDirectory = try XCTUnwrap(
            FileManager.default.contentsOfDirectory(
                at: rootURL,
                includingPropertiesForKeys: [.isDirectoryKey]
            ).first
        )
        let hidden = ownerDirectory.appendingPathComponent(".pending-delete", isDirectory: true)
        try FileManager.default.createDirectory(at: hidden, withIntermediateDirectories: true)
        try Data("hidden-owner-source".utf8).write(
            to: hidden.appendingPathComponent("source.gpx")
        )

        do {
            _ = try await custody.accountDeletionRecords(owner: owner)
            XCTFail("hidden owner bytes must make inventory unavailable")
        } catch {}
        do {
            try await custody.purgeAccount(owner: owner)
            XCTFail("hidden owner bytes must block destructive cleanup")
        } catch {}
        XCTAssertTrue(FileManager.default.fileExists(atPath: hidden.path))
    }

    func testAccountDeletionBlocksAndPreservesUnknownExactOwnerCustodyFile() async throws {
        let custody = makeCustody(at: rootURL)
        let owner = RecordingOwner(id: "rider-delete", wallet: "wallet-delete")
        let rideID = "11111111-1111-4111-8111-111111111111"
        try await custody.create(owner: owner, rideID: rideID, startedAt: start)
        let ownerDirectory = try XCTUnwrap(
            FileManager.default.contentsOfDirectory(
                at: rootURL,
                includingPropertiesForKeys: [.isDirectoryKey]
            ).first
        )
        let unknownFile = ownerDirectory.appendingPathComponent(
            "pending-delete-source.gpx",
            isDirectory: false
        )
        try Data("unknown-owner-source".utf8).write(to: unknownFile)

        do {
            _ = try await custody.accountDeletionRecords(owner: owner)
            XCTFail("unknown owner bytes must make inventory unavailable")
        } catch {}
        do {
            try await custody.purgeAccount(owner: owner)
            XCTFail("unknown owner bytes must block destructive cleanup")
        } catch {}
        XCTAssertTrue(FileManager.default.fileExists(atPath: unknownFile.path))
    }

    override func tearDownWithError() throws {
        AccountDeletionSessionRecordStore.clear()
        if let rootURL, FileManager.default.fileExists(atPath: rootURL.path) {
            try FileManager.default.removeItem(at: rootURL)
        }
    }

    func testMOBILE_TRUTHSSection3ClockDomainsSurviveRelaunchWithoutAddingDowntime() async throws {
        let user = fixtureUser(id: "clock-owner", wallet: "clock-wallet")
        let rideID = "10000000-0000-4000-8000-000000000001"
        let clock = GateClock(wall: start, monotonic: 100)
        let queue = GateUploadQueue()
        let custody = makeCustody(at: rootURL)
        let runtime = makeRuntime(
            custody: custody,
            queue: queue,
            clock: clock,
            ids: GateIDSequence([rideID])
        )

        _ = try await runtime.activate(user: user)
        _ = try await runtime.start(user: user, at: start)

        let gpsCapture = start.addingTimeInterval(30)
        clock.set(wall: start.addingTimeInterval(-3_600), monotonic: 105)
        _ = try await runtime.ingest(
            fixtureFix(capturedAt: gpsCapture, latitude: 39.9500, powerWatts: 225),
            wallNow: clock.wallValue
        )

        clock.set(wall: start.addingTimeInterval(-7_200), monotonic: 110)
        let paused = try await runtime.manualPause(at: clock.wallValue)
        XCTAssertEqual(paused.state, .manuallyPaused)
        XCTAssertEqual(paused.elapsedS, 10, accuracy: 0.001)
        _ = try await runtime.activate(user: nil)

        // A new process has a new local monotonic origin and a much later wall
        // clock. Neither may be applied to the interrupted recording.
        let relaunchedClock = GateClock(
            wall: start.addingTimeInterval(86_400),
            monotonic: 5
        )
        let relaunched = makeRuntime(
            custody: makeCustody(at: rootURL),
            queue: queue,
            clock: relaunchedClock,
            ids: GateIDSequence([])
        )
        let selectedRecovery = try await relaunched.activate(user: user)
        let recovery = try XCTUnwrap(selectedRecovery)

        XCTAssertEqual(recovery.state, .manuallyPaused)
        XCTAssertEqual(recovery.durationS, 10, accuracy: 0.001)

        let finalized = try await relaunched.saveRecovery(recovery)
        let xml = try XCTUnwrap(String(data: finalized.gpxBytes, encoding: .utf8))
        XCTAssertTrue(xml.contains(iso8601(gpsCapture)))
        XCTAssertTrue(xml.contains(iso8601(start)))
        XCTAssertFalse(xml.contains(iso8601(relaunchedClock.wallValue)))
        let clockQueueCalls = await queue.callSnapshot()
        XCTAssertTrue(clockQueueCalls.isEmpty)
    }

    /// The dead-process gap (bead 5ukpo): a ride killed while RECORDING (no
    /// pause boundary, unlike the test above) and reopened hours later in a
    /// fresh clock domain may never count the gap as moving time. Moving
    /// time is evidence-bounded, not process-alive-bounded.
    func testDeadProcessGapWhileRecordingNeverCountsAsMovingTime() async throws {
        let user = fixtureUser(id: "gap-owner", wallet: "gap-wallet")
        let rideID = "20000000-0000-4000-8000-000000000002"
        let clock = GateClock(wall: start, monotonic: 100)
        let queue = GateUploadQueue()
        let runtime = makeRuntime(
            custody: makeCustody(at: rootURL),
            queue: queue,
            clock: clock,
            ids: GateIDSequence([rideID])
        )

        _ = try await runtime.activate(user: user)
        _ = try await runtime.start(user: user, at: start)

        // Sixty seconds of stationary evidence, then the process dies with
        // the session still .recording — no boundary of any kind.
        for second in stride(from: 5.0, through: 60, by: 5) {
            clock.set(wall: start.addingTimeInterval(second), monotonic: 100 + second)
            _ = try await runtime.ingest(
                fixtureFix(
                    capturedAt: start.addingTimeInterval(second),
                    latitude: 39.9500
                ),
                wallNow: clock.wallValue
            )
        }

        // Six hours later: fresh process, fresh monotonic domain, far wall.
        let relaunchedClock = GateClock(
            wall: start.addingTimeInterval(6 * 3_600),
            monotonic: 7
        )
        let relaunched = makeRuntime(
            custody: makeCustody(at: rootURL),
            queue: queue,
            clock: relaunchedClock,
            ids: GateIDSequence([])
        )
        let activatedRecovery = try await relaunched.activate(user: user)
        let recovery = try XCTUnwrap(activatedRecovery)
        XCTAssertEqual(recovery.state, .recording)
        // Elapsed is bounded by the last recorded fix (60 s), never the
        // six-hour dead gap.
        XCTAssertEqual(recovery.durationS, 60, accuracy: 1.0)

        // Saving the recovery keeps the same evidence-bounded truth in the
        // finalized local summary (stationary ride: upload-ineligible).
        let finalized = try await relaunched.saveRecovery(recovery)
        XCTAssertFalse(finalized.uploadEligible)
        let saved = try await relaunched.localSavedRides(user: user)
        let summary = try XCTUnwrap(saved.first { $0.id == rideID }?.summary)
        XCTAssertEqual(summary.durationS ?? -1, 60, accuracy: 1.0)
        let enqueued = await queue.callSnapshot()
        XCTAssertTrue(enqueued.isEmpty)
    }

    /// The wall itself (bead oazrf): a test process resolving the DEFAULT
    /// custody root must land in an isolated temp directory, never the app
    /// container's rider evidence — the exact leak that put a fake-clock
    /// test ride into the rider's feed on 2026-08-17.
    func testDefaultStoreRootsAreWalledOffFromRiderEvidenceUnderTest() async throws {
        XCTAssertTrue(ProcessSandbox.isTestProcess)
        let defaultCustody = FileLiveRideCustodyStore()
        let riderRoot = FileManager.default.urls(
            for: .applicationSupportDirectory,
            in: .userDomainMask
        )[0].appendingPathComponent("LiveRideCustody", isDirectory: true)
        XCTAssertNotEqual(defaultCustody.rootURL.standardizedFileURL, riderRoot.standardizedFileURL)
        XCTAssertTrue(
            defaultCustody.rootURL.path.contains("BoulderRollerTestIsolated"),
            "default custody root under test must be the isolated sandbox"
        )
        XCTAssertEqual(
            ProcessSandbox.keychainAccount("br.refresh_token"),
            "test.br.refresh_token"
        )
    }

    func testMOBILE_TRUTHSSections4_2And11ReplayPreservesPauseSegmentsAndProvenanceExactly() async throws {
        let user = fixtureUser(id: "replay-owner", wallet: "replay-wallet")
        let rideID = "20000000-0000-4000-8000-000000000002"
        let clock = GateClock(wall: start, monotonic: 100)
        let queue = GateUploadQueue()
        let custody = makeCustody(at: rootURL)
        let runtime = makeRuntime(
            custody: custody,
            queue: queue,
            clock: clock,
            ids: GateIDSequence([rideID])
        )
        var control = RecordingSession()
        control.start(at: start, monotonicNowS: 0)

        _ = try await runtime.activate(user: user)
        _ = try await runtime.start(user: user, at: start)

        let first = fixtureFix(
            capturedAt: start.addingTimeInterval(1),
            latitude: 39.95000,
            gpsAltitudeM: 100,
            relativeBarometerM: 0,
            heartRateBpm: nil,
            cadenceRpm: nil,
            powerWatts: 250
        )
        clock.set(wall: start.addingTimeInterval(1), monotonic: 101)
        _ = try await runtime.ingest(first, wallNow: clock.wallValue)
        _ = control.ingest(first, wallNow: clock.wallValue, monotonicNowS: 1)

        let second = fixtureFix(
            capturedAt: start.addingTimeInterval(2),
            latitude: 39.95004,
            gpsAltitudeM: 101,
            relativeBarometerM: 1,
            heartRateBpm: 150,
            cadenceRpm: nil,
            powerWatts: nil
        )
        clock.set(wall: start.addingTimeInterval(2), monotonic: 102)
        _ = try await runtime.ingest(second, wallNow: clock.wallValue)
        _ = control.ingest(second, wallNow: clock.wallValue, monotonicNowS: 2)

        clock.set(wall: start.addingTimeInterval(3), monotonic: 103)
        _ = try await runtime.manualPause(at: clock.wallValue)
        XCTAssertTrue(control.manualPause(at: clock.wallValue, monotonicNowS: 3))

        let pausedEvidence = fixtureFix(
            capturedAt: start.addingTimeInterval(4),
            latitude: 39.99999,
            gpsAltitudeM: 999,
            relativeBarometerM: 999,
            heartRateBpm: 199,
            cadenceRpm: 199,
            powerWatts: 999
        )
        clock.set(wall: start.addingTimeInterval(4), monotonic: 104)
        let pausedOutcome = try await runtime.ingest(pausedEvidence, wallNow: clock.wallValue).0
        XCTAssertEqual(pausedOutcome, .ignored)
        _ = control.ingest(pausedEvidence, wallNow: clock.wallValue, monotonicNowS: 4)

        clock.set(wall: start.addingTimeInterval(5), monotonic: 105)
        _ = try await runtime.manualResume(at: clock.wallValue)
        XCTAssertTrue(control.manualResume(at: clock.wallValue, monotonicNowS: 5))

        let resumed = fixtureFix(
            capturedAt: start.addingTimeInterval(6),
            latitude: 39.95008,
            gpsAltitudeM: 102,
            relativeBarometerM: 2,
            heartRateBpm: nil,
            cadenceRpm: 0,
            powerWatts: 0
        )
        clock.set(wall: start.addingTimeInterval(6), monotonic: 106)
        _ = try await runtime.ingest(resumed, wallNow: clock.wallValue)
        _ = control.ingest(resumed, wallNow: clock.wallValue, monotonicNowS: 6)

        let postGap = fixtureFix(
            capturedAt: start.addingTimeInterval(20),
            latitude: 39.95012,
            gpsAltitudeM: 103,
            relativeBarometerM: 3,
            heartRateBpm: nil,
            cadenceRpm: nil,
            powerWatts: nil
        )
        clock.set(wall: start.addingTimeInterval(20), monotonic: 120)
        _ = try await runtime.ingest(postGap, wallNow: clock.wallValue)
        _ = control.ingest(postGap, wallNow: clock.wallValue, monotonicNowS: 20)
        _ = control.end(at: clock.wallValue, monotonicNowS: 20)

        _ = try await runtime.activate(user: nil)
        let persistedBeforeRecovery = try await custody.persisted(
            owner: RecordingOwner(user: user),
            rideID: rideID
        )
        XCTAssertEqual(
            persistedBeforeRecovery.events.map(\.kind),
            [.start, .fix, .fix, .manualPause, .fix, .manualResume, .fix, .fix, .suspend]
        )

        let relaunched = makeRuntime(
            custody: makeCustody(at: rootURL),
            queue: queue,
            clock: GateClock(wall: start.addingTimeInterval(500), monotonic: 3),
            ids: GateIDSequence([])
        )
        let selectedRecovery = try await relaunched.activate(user: user)
        let recovery = try XCTUnwrap(selectedRecovery)
        let selectedEvidence = try await relaunched.recoveryEvidence(ownerID: user.id)
        let recoveryEvidence = try XCTUnwrap(selectedEvidence)
        XCTAssertEqual(recovery.state, .recording)
        XCTAssertEqual(recovery.sampleCount, 4)
        XCTAssertEqual(recoveryEvidence.recovery, recovery)
        XCTAssertEqual(recoveryEvidence.samples, control.samples)
        XCTAssertEqual(
            recoveryEvidence.samples.map(\.speedMps),
            control.samples.map(\.speedMps)
        )
        XCTAssertEqual(
            recoveryEvidence.samples.map(\.horizontalAccuracyM),
            control.samples.map(\.horizontalAccuracyM)
        )
        XCTAssertEqual(
            recoveryEvidence.samples.map(\.courseDegrees),
            control.samples.map(\.courseDegrees)
        )
        XCTAssertEqual(
            recoveryEvidence.samples.map(\.elevationSource),
            control.samples.map(\.elevationSource)
        )
        XCTAssertEqual(
            recoveryEvidence.samples.map(\.elevationConfidence),
            control.samples.map(\.elevationConfidence)
        )
        XCTAssertEqual(
            recoveryEvidence.samples.map(\.rawGPSAltitudeM),
            control.samples.map(\.rawGPSAltitudeM)
        )
        XCTAssertEqual(
            recoveryEvidence.samples.map(\.relativeBarometerM),
            control.samples.map(\.relativeBarometerM)
        )
        XCTAssertEqual(
            recoveryEvidence.samples.map(\.startsNewSegment),
            control.samples.map(\.startsNewSegment)
        )

        let finalized = try await relaunched.saveRecovery(recovery)
        let expectedGPX = GPXWriter.gpx(samples: control.samples, startedAt: start)
        XCTAssertEqual(finalized.gpxBytes, expectedGPX)

        let xml = try XCTUnwrap(String(data: finalized.gpxBytes, encoding: .utf8))
        XCTAssertEqual(occurrences(of: "<trkseg>", in: xml), 3)
        XCTAssertFalse(xml.contains("39.9999900"))
        XCTAssertFalse(xml.contains("<br:power>999</br:power>"))
        XCTAssertFalse(xml.contains("<gpxtpx:cad>199</gpxtpx:cad>"))
        XCTAssertTrue(xml.contains("<br:power>250</br:power>"))
        XCTAssertTrue(xml.contains("<br:power>0</br:power>"))
        XCTAssertTrue(xml.contains("<gpxtpx:cad>0</gpxtpx:cad>"))
        XCTAssertTrue(xml.contains("<br:elevation-source>barometer_fused</br:elevation-source>"))
        XCTAssertTrue(xml.contains("<br:raw-gps-altitude-m>100.0</br:raw-gps-altitude-m>"))
        XCTAssertTrue(xml.contains("<br:relative-barometer-m>0.0</br:relative-barometer-m>"))
        let replayQueueCalls = await queue.callSnapshot()
        XCTAssertTrue(replayQueueCalls.isEmpty)
    }

    func testMOBILE_TRUTHSSection6ZeroAndShortStopsStampButDoNotQueue() async throws {
        let user = fixtureUser(id: "short-owner", wallet: "short-wallet")

        let zeroClock = GateClock(wall: start, monotonic: 10)
        let zeroQueue = GateUploadQueue()
        let zeroRuntime = makeRuntime(
            custody: makeCustody(at: rootURL.appendingPathComponent("zero")),
            queue: zeroQueue,
            clock: zeroClock,
            ids: GateIDSequence(["30000000-0000-4000-8000-000000000003"])
        )
        _ = try await zeroRuntime.activate(user: user)
        _ = try await zeroRuntime.start(user: user, at: start)
        zeroClock.set(wall: start.addingTimeInterval(1), monotonic: 11)
        let zero = try await zeroRuntime.stop(at: zeroClock.wallValue)
        let emptySummary = try await WorkoutParser.emptyRecordingSummary(startedAt: start)

        XCTAssertFalse(zero.uploadEligible)
        XCTAssertNil(zero.uploadJobID)
        XCTAssertEqual(zero.parserVersion, emptySummary.parserVersion)
        XCTAssertEqual(zero.preliminaryRideHash, emptySummary.canonicalHashHex)
        XCTAssertEqual(zero.fileHash, FileRideUploadJobStore.sha256(zero.gpxBytes))
        let zeroQueueCalls = await zeroQueue.callSnapshot()
        XCTAssertTrue(zeroQueueCalls.isEmpty)

        let shortClock = GateClock(wall: start, monotonic: 20)
        let shortQueue = GateUploadQueue()
        let shortRuntime = makeRuntime(
            custody: makeCustody(at: rootURL.appendingPathComponent("short")),
            queue: shortQueue,
            clock: shortClock,
            ids: GateIDSequence(["30000000-0000-4000-8000-000000000004"])
        )
        _ = try await shortRuntime.activate(user: user)
        _ = try await shortRuntime.start(user: user, at: start)
        shortClock.set(wall: start.addingTimeInterval(1), monotonic: 21)
        _ = try await shortRuntime.ingest(
            fixtureFix(capturedAt: start.addingTimeInterval(1), latitude: 39.95),
            wallNow: shortClock.wallValue
        )
        shortClock.set(wall: start.addingTimeInterval(2), monotonic: 22)
        let short = try await shortRuntime.stop(at: shortClock.wallValue)
        let parsed = try await WorkoutParser.preliminarySummary(
            data: short.gpxBytes,
            kind: .gpx,
            thresholdWatts: nil
        )

        XCTAssertFalse(short.uploadEligible)
        XCTAssertNil(short.uploadJobID)
        XCTAssertEqual(short.parserVersion, parsed.parserVersion)
        XCTAssertEqual(short.preliminaryRideHash, parsed.canonicalHashHex)
        XCTAssertNotEqual(short.fileHash, short.preliminaryRideHash)
        let shortQueueCalls = await shortQueue.callSnapshot()
        XCTAssertTrue(shortQueueCalls.isEmpty)
    }

    /// Bead c6l2l item 5: the acknowledged empty-ride Discard removes the
    /// zero-sample custody record exactly once, while anything upload-
    /// eligible or handed off stays immune to the same call.
    func testAcknowledgedEmptyRideDiscardRemovesCustodyButNeverEligibleEvidence() async throws {
        let user = fixtureUser(id: "empty-ack-owner", wallet: "empty-ack-wallet")

        let emptyClock = GateClock(wall: start, monotonic: 10)
        let emptyQueue = GateUploadQueue()
        let emptyRuntime = makeRuntime(
            custody: makeCustody(at: rootURL.appendingPathComponent("empty-ack")),
            queue: emptyQueue,
            clock: emptyClock,
            ids: GateIDSequence(["32000000-0000-4000-8000-000000000001"])
        )
        _ = try await emptyRuntime.activate(user: user)
        _ = try await emptyRuntime.start(user: user, at: start)
        emptyClock.set(wall: start.addingTimeInterval(1), monotonic: 11)
        let empty = try await emptyRuntime.stop(at: emptyClock.wallValue)
        XCTAssertFalse(empty.uploadEligible)
        XCTAssertNil(empty.uploadJobID)
        // Before acknowledgment the finalized record is a local saved ride.
        let savedBefore = try await emptyRuntime.localSavedRides(user: user)
        XCTAssertEqual(savedBefore.map(\.id), [empty.id])

        try await emptyRuntime.discardFinalizedLocalRecording(empty)

        let savedAfter = try await emptyRuntime.localSavedRides(user: user)
        XCTAssertTrue(savedAfter.isEmpty)
        let recovery = try await emptyRuntime.recovery(ownerID: user.id)
        XCTAssertNil(recovery)
        // Idempotence is not assumed: the record is gone, so a repeat fails
        // closed instead of pretending a second delete happened.
        do {
            try await emptyRuntime.discardFinalizedLocalRecording(empty)
            XCTFail("expected a second discard to fail closed")
        } catch {}

        // An upload-eligible finalized ride refuses this discard entirely.
        let eligibleClock = GateClock(wall: start, monotonic: 100)
        let eligibleQueue = GateUploadQueue()
        let eligibleRuntime = makeRuntime(
            custody: makeCustody(at: rootURL.appendingPathComponent("eligible-ack")),
            queue: eligibleQueue,
            clock: eligibleClock,
            ids: GateIDSequence(["32000000-0000-4000-8000-000000000002"])
        )
        _ = try await eligibleRuntime.activate(user: user)
        _ = try await eligibleRuntime.start(user: user, at: start)
        _ = try await ingestEligibleRide(runtime: eligibleRuntime, clock: eligibleClock)
        eligibleClock.set(wall: start.addingTimeInterval(40), monotonic: 140)
        let eligible = try await eligibleRuntime.stop(at: eligibleClock.wallValue)
        XCTAssertTrue(eligible.uploadEligible)
        do {
            try await eligibleRuntime.discardFinalizedLocalRecording(eligible)
            XCTFail("expected the eligible artifact to be immune")
        } catch let error as LiveRideCustodyError {
            XCTAssertEqual(error, .immutableEvidenceChanged)
        }
    }

    func testMOBILE_TRUTHSSections6_7_9_1And11RecoveredIneligibleRideStaysEncryptedLocalAcrossRelaunch() async throws {
        let user = fixtureUser(id: "local-save-owner", wallet: "local-save-wallet")
        let rideID = "31000000-0000-4000-8000-000000000003"
        let clock = GateClock(wall: start, monotonic: 100)
        let captureQueue = GateUploadQueue()
        let captureRuntime = makeRuntime(
            custody: makeCustody(at: rootURL),
            queue: captureQueue,
            clock: clock,
            ids: GateIDSequence([rideID])
        )
        _ = try await captureRuntime.activate(user: user)
        _ = try await captureRuntime.start(user: user, at: start)
        clock.set(wall: start.addingTimeInterval(1), monotonic: 101)
        _ = try await captureRuntime.ingest(
            fixtureFix(
                capturedAt: clock.wallValue,
                latitude: 39.9512345,
                heartRateBpm: 171,
                cadenceRpm: 87,
                powerWatts: 321
            ),
            wallNow: clock.wallValue
        )
        clock.set(wall: start.addingTimeInterval(2), monotonic: 102)
        _ = try await captureRuntime.activate(user: nil)

        let recoveryQueue = GateUploadQueue()
        let recoveredRuntime = makeRuntime(
            custody: makeCustody(at: rootURL),
            queue: recoveryQueue,
            clock: GateClock(wall: start.addingTimeInterval(3_600), monotonic: 3),
            ids: GateIDSequence([])
        )
        let selected = try await recoveredRuntime.activate(user: user)
        let recovery = try XCTUnwrap(selected)
        XCTAssertEqual(recovery.id, rideID)
        XCTAssertFalse(recovery.canSaveAndUpload)

        let finalized = try await recoveredRuntime.saveRecovery(recovery)
        XCTAssertFalse(finalized.uploadEligible)
        XCTAssertNil(finalized.uploadJobID)

        let decrypted = try await makeCustody(at: rootURL).persisted(
            owner: RecordingOwner(user: user),
            rideID: rideID
        )
        let artifact = try XCTUnwrap(decrypted.finalArtifact)
        XCTAssertEqual(artifact.gpxBytes, finalized.gpxBytes)
        XCTAssertEqual(artifact.fileHash, finalized.fileHash)
        XCTAssertEqual(artifact.preliminaryRideHash, finalized.preliminaryRideHash)
        XCTAssertEqual(artifact.parserVersion, finalized.parserVersion)
        XCTAssertFalse(artifact.uploadEligible)
        XCTAssertEqual(decrypted.events.filter { $0.kind == .finalized }.count, 1)
        XCTAssertEqual(decrypted.events.filter { $0.kind == .handedOff }.count, 0)

        let encryptedAtRest = try allRegularFileData(in: rootURL)
        XCTAssertNil(encryptedAtRest.range(of: finalized.gpxBytes))
        XCTAssertNil(encryptedAtRest.range(of: Data("<gpx".utf8)))
        XCTAssertNil(encryptedAtRest.range(of: Data("39.9512345".utf8)))

        let relaunchQueue = GateUploadQueue()
        let relaunched = makeRuntime(
            custody: makeCustody(at: rootURL),
            queue: relaunchQueue,
            clock: GateClock(wall: start.addingTimeInterval(7_200), monotonic: 4),
            ids: GateIDSequence([])
        )
        let interruptedAfterSave = try await relaunched.activate(user: user)
        let localRides = try await relaunched.localSavedRides(user: user)
        let saved = try XCTUnwrap(localRides.first)

        XCTAssertNil(interruptedAfterSave, "a locally saved Ride is final, not unfinished")
        XCTAssertEqual(localRides.count, 1)
        XCTAssertEqual(saved.id, rideID)
        XCTAssertEqual(saved.ownerID, user.id)
        XCTAssertEqual(saved.ownerWallet, user.wallet)
        XCTAssertEqual(saved.summary, artifact.localSummary)
        XCTAssertEqual(saved.fileHash, artifact.fileHash)
        XCTAssertEqual(saved.preliminaryRideHash, artifact.preliminaryRideHash)
        XCTAssertEqual(saved.parserVersion, artifact.parserVersion)
        let captureCalls = await captureQueue.callSnapshot()
        let recoveryCalls = await recoveryQueue.callSnapshot()
        let relaunchCalls = await relaunchQueue.callSnapshot()
        XCTAssertTrue(captureCalls.isEmpty)
        XCTAssertTrue(recoveryCalls.isEmpty)
        XCTAssertTrue(relaunchCalls.isEmpty)
    }

    func testMOBILE_TRUTHSSections6_7And11RecoveredEligibleRideStillQueuesExactArtifactOnce() async throws {
        let user = fixtureUser(id: "eligible-recovery-owner", wallet: "eligible-recovery-wallet")
        let rideID = "32000000-0000-4000-8000-000000000003"
        let clock = GateClock(wall: start, monotonic: 100)
        let queue = GateUploadQueue()
        let captureRuntime = makeRuntime(
            custody: makeCustody(at: rootURL),
            queue: queue,
            clock: clock,
            ids: GateIDSequence([rideID])
        )
        _ = try await captureRuntime.activate(user: user)
        _ = try await captureRuntime.start(user: user, at: start)
        _ = try await ingestEligibleRide(runtime: captureRuntime, clock: clock)
        _ = try await captureRuntime.activate(user: nil)

        let recoveredRuntime = makeRuntime(
            custody: makeCustody(at: rootURL),
            queue: queue,
            clock: GateClock(wall: start.addingTimeInterval(3_600), monotonic: 3),
            ids: GateIDSequence([])
        )
        let selected = try await recoveredRuntime.activate(user: user)
        let recovery = try XCTUnwrap(selected)
        XCTAssertTrue(recovery.canSaveAndUpload)

        let finalized = try await recoveredRuntime.saveRecovery(recovery)
        let calls = await queue.callSnapshot()
        let localRides = try await recoveredRuntime.localSavedRides(user: user)
        let persisted = try await makeCustody(at: rootURL).persisted(
            owner: RecordingOwner(user: user),
            rideID: rideID
        )

        XCTAssertTrue(finalized.uploadEligible)
        XCTAssertEqual(finalized.uploadJobID, rideID)
        XCTAssertEqual(calls.count, 1)
        XCTAssertEqual(calls.first?.jobID, rideID)
        XCTAssertEqual(calls.first?.owner, RecordingOwner(user: user))
        XCTAssertEqual(calls.first?.sourceBytes, finalized.gpxBytes)
        XCTAssertEqual(calls.first?.parserVersion, finalized.parserVersion)
        XCTAssertEqual(calls.first?.preliminaryRideHash, finalized.preliminaryRideHash)
        XCTAssertTrue(localRides.isEmpty)
        XCTAssertEqual(persisted.events.filter { $0.kind == .finalized }.count, 1)
        XCTAssertEqual(persisted.events.filter { $0.kind == .handedOff }.count, 1)
    }

    func testMOBILE_TRUTHSSection6FinalizedEventFailureKeepsOneEndedStopForRetry() async throws {
        let user = fixtureUser(id: "finalize-owner", wallet: "finalize-wallet")
        let rideID = "40000000-0000-4000-8000-000000000004"
        let clock = GateClock(wall: start, monotonic: 100)
        let fault = GateFinalizedEventFault()
        let custody = makeCustody(
            at: rootURL,
            beforeEventPublish: { kind, sequence in
                try fault.beforePublish(kind: kind, sequence: sequence)
            }
        )
        let queue = GateUploadQueue()
        let runtime = makeRuntime(
            custody: custody,
            queue: queue,
            clock: clock,
            ids: GateIDSequence([rideID])
        )
        _ = try await runtime.activate(user: user)
        _ = try await runtime.start(user: user, at: start)
        let projection = try await ingestEligibleRide(runtime: runtime, clock: clock)
        XCTAssertGreaterThanOrEqual(projection.sampleCount, 30)
        XCTAssertGreaterThanOrEqual(projection.distanceM, 100)

        clock.set(wall: start.addingTimeInterval(40), monotonic: 140)
        do {
            _ = try await runtime.stop(at: clock.wallValue)
            XCTFail("the injected finalized-event failure must remain visible")
        } catch GateTestError.injectedFailure {
            // Retained behavioral red boundary.
        }
        var persisted = try await custody.persisted(
            owner: RecordingOwner(user: user),
            rideID: rideID
        )
        XCTAssertEqual(persisted.events.filter { $0.kind == .stop }.count, 1)
        XCTAssertNil(persisted.finalArtifact)
        let callsAfterFault = await queue.callSnapshot()
        XCTAssertTrue(callsAfterFault.isEmpty)

        clock.set(wall: start.addingTimeInterval(9_999), monotonic: 10_099)
        let retried = try await runtime.stop(at: clock.wallValue)
        let calls = await queue.callSnapshot()
        persisted = try await custody.persisted(
            owner: RecordingOwner(user: user),
            rideID: rideID
        )

        XCTAssertEqual(persisted.events.filter { $0.kind == .stop }.count, 1)
        XCTAssertEqual(persisted.events.filter { $0.kind == .finalized }.count, 1)
        XCTAssertEqual(calls.count, 1)
        XCTAssertEqual(calls.first?.summary.durationS, 40)
        XCTAssertEqual(retried.uploadJobID, rideID)
    }

    func testMOBILE_TRUTHSSection6CustodyFailureClearsOnlyAfterMatchingPauseOrResume() {
        XCTAssertFalse(
            RecordingCustodyFailurePolicy.clears(failed: .pause, completed: .capture),
            "a successful tick/fix cannot dismiss a failed pause boundary"
        )
        XCTAssertTrue(
            RecordingCustodyFailurePolicy.clears(failed: .pause, completed: .pause),
            "only the matching durable pause may clear its failure"
        )
        XCTAssertFalse(
            RecordingCustodyFailurePolicy.clears(failed: .resume, completed: .capture),
            "a successful tick/fix cannot dismiss a failed resume boundary"
        )
        XCTAssertTrue(
            RecordingCustodyFailurePolicy.clears(failed: .resume, completed: .resume),
            "only the matching durable resume may clear its failure"
        )
        XCTAssertEqual(
            RecordingCustodyFailurePolicy.retainedFailure(
                current: .pause,
                incoming: .capture
            ),
            .pause,
            "a queued capture failure cannot replace the rider's pause intent"
        )
        XCTAssertEqual(
            RecordingCustodyFailurePolicy.retainedFailure(
                current: .resume,
                incoming: .capture
            ),
            .resume,
            "a queued capture failure cannot replace the rider's resume intent"
        )
        XCTAssertFalse(
            RecordingCustodyFailurePolicy.clears(failed: .suspend, completed: .capture),
            "capture work cannot clear a failed owner-bound suspension"
        )
        XCTAssertTrue(
            RecordingCustodyFailurePolicy.clears(failed: .suspend, completed: .suspend),
            "only the exact successful suspension clears its retry state"
        )
        XCTAssertEqual(
            RecordingCustodyFailurePolicy.retainedFailure(
                current: .suspend,
                incoming: .pause
            ),
            .suspend,
            "a stale Pause failure cannot replace authorization-owned suspension"
        )
        XCTAssertEqual(
            RecordingCustodyFailurePolicy.retainedFailure(
                current: .suspend,
                incoming: .resume
            ),
            .suspend,
            "a stale Resume failure cannot replace authorization-owned suspension"
        )
    }

    func testMOBILE_TRUTHSSection6DuplicateControlTransitionsCoalesce() {
        var inFlight: RecordingControlTransition?

        XCTAssertTrue(RecordingControlTransitionPolicy.begin(.pause, current: &inFlight))
        XCTAssertEqual(inFlight, .pause)
        XCTAssertFalse(RecordingControlTransitionPolicy.begin(.pause, current: &inFlight))
        XCTAssertFalse(RecordingControlTransitionPolicy.begin(.resume, current: &inFlight))
        XCTAssertFalse(RecordingControlTransitionPolicy.begin(.end, current: &inFlight))

        RecordingControlTransitionPolicy.complete(.resume, current: &inFlight)
        XCTAssertEqual(inFlight, .pause)
        RecordingControlTransitionPolicy.complete(.pause, current: &inFlight)
        XCTAssertNil(inFlight)

        XCTAssertTrue(RecordingControlTransitionPolicy.begin(.resume, current: &inFlight))
        XCTAssertFalse(RecordingControlTransitionPolicy.begin(.resume, current: &inFlight))
        RecordingControlTransitionPolicy.complete(.resume, current: &inFlight)
        XCTAssertTrue(RecordingControlTransitionPolicy.begin(.end, current: &inFlight))
        XCTAssertFalse(RecordingControlTransitionPolicy.begin(.end, current: &inFlight))
        RecordingControlTransitionPolicy.complete(.end, current: &inFlight)
        XCTAssertNil(inFlight)
    }

    @MainActor
    func testMOBILE_TRUTHSSection6CaptureProjectionCannotOverwriteCompletedPause() async throws {
        let user = fixtureUser(id: "capture-control-owner", wallet: "capture-control-wallet")
        let rideID = "a2730000-0000-4000-8000-00000000000a"
        let clock = GateClock(wall: start, monotonic: 100)
        let custody = makeCustody(at: rootURL)
        let runtime = makeRuntime(
            custody: custody,
            queue: GateUploadQueue(),
            clock: clock,
            ids: GateIDSequence([rideID])
        )
        _ = try await runtime.activate(user: user)
        let captureBarrier = GateAsyncBarrier()
        let model = RecordingModel(
            user: user,
            runtime: runtime,
            authorizationStatus: .authorizedWhenInUse,
            locationHardwareEnabled: false,
            wallNow: { clock.wallValue },
            monotonicNow: { clock.monotonicValue },
            beforeCaptureProjectionApply: { await captureBarrier.wait() }
        )
        var controlReady = false
        var delivered: [Double] = []
        model.onControlProjectionReady = { transition in
            if transition == .pause { controlReady = true }
        }
        model.onFix = { delivered.append($0.coordinate.latitude) }
        await model.handleAuthorizationChange(.authorizedWhenInUse)
        try await waitForModel {
            model.state == .recording && model.captureHardwareActive
        }

        let first = fixtureLocation(
            capturedAt: start.addingTimeInterval(1),
            latitude: 39.96200
        )
        let capture = Task { @MainActor in
            await model.handleLocations([first])
        }
        await captureBarrier.waitUntilEntered()
        model.pause()
        XCTAssertFalse(
            controlReady,
            "Pause must wait until the older capture projection has been applied"
        )

        await captureBarrier.release()
        await capture.value
        try await waitForModel {
            controlReady && model.controlTransitionInFlight == nil
        }

        XCTAssertEqual(
            model.state,
            .manuallyPaused,
            "an older capture projection cannot overwrite the later durable Pause"
        )
        XCTAssertEqual(delivered, [first.coordinate.latitude])
        let pausedEvidence = try await runtime.recoveryEvidence(ownerID: user.id)
        XCTAssertEqual(pausedEvidence?.recovery.state, .manuallyPaused)
        let persistedBeforeResume = try await custody.persisted(
            owner: RecordingOwner(user: user),
            rideID: rideID
        )
        XCTAssertEqual(
            persistedBeforeResume.events.map(\.kind),
            [.start, .fix, .manualPause]
        )

        model.resume()
        try await waitForModel {
            model.state == .recording && model.controlTransitionInFlight == nil
        }
        let second = fixtureLocation(
            capturedAt: start.addingTimeInterval(2),
            latitude: 39.96204
        )
        await model.handleLocations([second])
        let finalEvidence = try await runtime.recoveryEvidence(ownerID: user.id)
        XCTAssertEqual(finalEvidence?.samples.count, 2)
        XCTAssertEqual(
            delivered,
            [first.coordinate.latitude, second.coordinate.latitude]
        )
        model.stopHardware()
    }

    @MainActor
    func testMOBILE_TRUTHSSection6TickProjectionCannotOverwriteCompletedPause() async throws {
        let user = fixtureUser(id: "tick-control-owner", wallet: "tick-control-wallet")
        let rideID = "a2730000-0000-4000-8000-00000000000b"
        let clock = GateClock(wall: start, monotonic: 100)
        let custody = makeCustody(at: rootURL)
        let runtime = makeRuntime(
            custody: custody,
            queue: GateUploadQueue(),
            clock: clock,
            ids: GateIDSequence([rideID])
        )
        _ = try await runtime.activate(user: user)
        let tickProjectionBarrier = GateAsyncBarrier()
        let model = RecordingModel(
            user: user,
            runtime: runtime,
            authorizationStatus: .authorizedWhenInUse,
            locationHardwareEnabled: false,
            wallNow: { clock.wallValue },
            monotonicNow: { clock.monotonicValue },
            beforeCaptureProjectionApply: { await tickProjectionBarrier.wait() }
        )
        var controlReady = false
        model.onControlProjectionReady = { transition in
            if transition == .pause { controlReady = true }
        }
        await model.handleAuthorizationChange(.authorizedWhenInUse)
        try await waitForModel { model.state == .recording }

        let tickTask = Task { @MainActor in
            await model.handleCaptureTick()
        }
        for _ in 0..<100 where !(await tickProjectionBarrier.hasEntered()) {
            try await Task.sleep(for: .milliseconds(10))
        }
        let tickReachedProjection = await tickProjectionBarrier.hasEntered()
        XCTAssertTrue(
            tickReachedProjection,
            "the production tick projection must participate in the capture/control barrier"
        )
        guard tickReachedProjection else {
            await tickTask.value
            model.stopHardware()
            return
        }

        model.pause()
        try await Task.sleep(for: .milliseconds(50))
        XCTAssertFalse(controlReady)
        await tickProjectionBarrier.release()
        await tickTask.value
        try await waitForModel {
            controlReady && model.controlTransitionInFlight == nil
        }

        XCTAssertEqual(model.state, .manuallyPaused)
        let persisted = try await custody.persisted(
            owner: RecordingOwner(user: user),
            rideID: rideID
        )
        XCTAssertEqual(persisted.events.map(\.kind), [.start, .manualPause])
        model.stopHardware()
    }

    @MainActor
    func testMOBILE_TRUTHSSection6LocationAdmittedDuringTickDrainsAfterTickCompletion() async throws {
        let user = fixtureUser(id: "tick-delegate-owner", wallet: "tick-delegate-wallet")
        let rideID = "a2730000-0000-4000-8000-00000000000c"
        let clock = GateClock(wall: start, monotonic: 100)
        let fixFault = GateFixEventPublishFault()
        let custody = makeCustody(
            at: rootURL,
            beforeEventPublish: { kind, sequence in
                try fixFault.beforePublish(kind: kind, sequence: sequence)
            }
        )
        let runtime = makeRuntime(
            custody: custody,
            queue: GateUploadQueue(),
            clock: clock,
            ids: GateIDSequence([rideID])
        )
        _ = try await runtime.activate(user: user)
        let tickProjectionBarrier = GateAsyncBarrier()
        let model = RecordingModel(
            user: user,
            runtime: runtime,
            authorizationStatus: .authorizedWhenInUse,
            locationHardwareEnabled: false,
            wallNow: { clock.wallValue },
            monotonicNow: { clock.monotonicValue },
            beforeCaptureProjectionApply: { await tickProjectionBarrier.wait() }
        )
        var admitted: [Double] = []
        var delivered: [Double] = []
        var drainDeferred = false
        model.onCaptureCallback = { admitted.append($0.coordinate.latitude) }
        model.onCaptureDrainDeferred = { drainDeferred = true }
        model.onFix = { delivered.append($0.coordinate.latitude) }
        await model.handleAuthorizationChange(.authorizedWhenInUse)
        try await waitForModel {
            model.state == .recording && model.captureHardwareActive
        }

        let first = fixtureLocation(
            capturedAt: start.addingTimeInterval(1),
            latitude: 39.96202
        )
        clock.set(wall: start.addingTimeInterval(1), monotonic: 101)
        let tickTask = Task { @MainActor in
            await model.handleCaptureTick()
        }
        await tickProjectionBarrier.waitUntilEntered()
        model.locationManager(CLLocationManager(), didUpdateLocations: [first])
        try await waitForModel { drainDeferred }
        XCTAssertEqual(admitted, [first.coordinate.latitude])
        XCTAssertEqual(model.queuedCaptureCountForTesting, 1)
        XCTAssertTrue(delivered.isEmpty)

        await tickProjectionBarrier.release()
        await tickTask.value
        for _ in 0..<100 where model.custodyErrorMessage == nil {
            try await Task.sleep(for: .milliseconds(10))
        }
        XCTAssertNotNil(
            model.custodyErrorMessage,
            "a callback already admitted during Tick must run immediately after Tick releases capture ownership"
        )
        guard model.custodyErrorMessage != nil else { return }
        XCTAssertEqual(model.queuedCaptureCountForTesting, 0)
        XCTAssertTrue(model.captureRetryPendingForTesting)
        XCTAssertTrue(delivered.isEmpty)

        clock.set(wall: start.addingTimeInterval(99), monotonic: 199)
        model.retryCustodyOperation()
        try await waitForModel {
            model.custodyErrorMessage == nil && delivered.count == 1
        }
        XCTAssertEqual(delivered, [first.coordinate.latitude])
        XCTAssertEqual(model.queuedCaptureCountForTesting, 0)
        let afterRetry = try await custody.persisted(
            owner: RecordingOwner(user: user),
            rideID: rideID
        )
        XCTAssertEqual(afterRetry.events.map(\.kind), [.start, .fix])
        let firstEvent = try XCTUnwrap(afterRetry.events.last)
        XCTAssertEqual(firstEvent.occurredAt, start.addingTimeInterval(1))
        XCTAssertEqual(firstEvent.fix?.gps.latitude, first.coordinate.latitude)

        let second = fixtureLocation(
            capturedAt: start.addingTimeInterval(2),
            latitude: 39.96206
        )
        clock.set(wall: start.addingTimeInterval(2), monotonic: 102)
        await model.handleCaptureTick()
        model.locationManager(CLLocationManager(), didUpdateLocations: [second])
        try await waitForModel { delivered.count == 2 }
        let final = try await custody.persisted(
            owner: RecordingOwner(user: user),
            rideID: rideID
        )
        XCTAssertEqual(final.events.map(\.kind), [.start, .fix, .fix])
        XCTAssertEqual(
            delivered,
            [first.coordinate.latitude, second.coordinate.latitude]
        )
        model.stopHardware()
    }

    @MainActor
    func testMOBILE_TRUTHSSection6FailedInFlightCaptureRetriesBeforeQueuedPause() async throws {
        let user = fixtureUser(id: "failed-capture-pause-owner", wallet: "failed-capture-pause-wallet")
        let rideID = "a2731000-0000-4000-8000-00000000000a"
        let clock = GateClock(wall: start, monotonic: 100)
        let fixFault = GateBlockingFirstFixPublishFault()
        let custody = makeCustody(
            at: rootURL,
            beforeEventPublish: { kind, sequence in
                try fixFault.beforePublish(kind: kind, sequence: sequence)
            }
        )
        let runtime = makeRuntime(
            custody: custody,
            queue: GateUploadQueue(),
            clock: clock,
            ids: GateIDSequence([rideID])
        )
        _ = try await runtime.activate(user: user)
        let failureBarrier = GateAsyncBarrier()
        let sensorSource = GateCaptureSensorSource(
            RecordingCaptureSensorSnapshot(
                heartRateBpm: 141,
                cadenceRpm: 0,
                powerObservation: PowerObservation(
                    watts: 233,
                    timestamp: start.addingTimeInterval(0.5)
                )
            )
        )
        let model = RecordingModel(
            user: user,
            runtime: runtime,
            authorizationStatus: .authorizedWhenInUse,
            locationHardwareEnabled: false,
            wallNow: { clock.wallValue },
            monotonicNow: { clock.monotonicValue },
            captureSensorSnapshot: { sensorSource.snapshot() },
            beforeCaptureFailureApply: { await failureBarrier.wait() }
        )
        var controlReady = false
        var delivered: [Double] = []
        model.onControlProjectionReady = { transition in
            if transition == .pause { controlReady = true }
        }
        model.onFix = { delivered.append($0.coordinate.latitude) }
        await model.handleAuthorizationChange(.authorizedWhenInUse)
        try await waitForModel {
            model.state == .recording && model.captureHardwareActive
        }

        clock.set(wall: start.addingTimeInterval(1), monotonic: 101)
        let first = fixtureLocation(
            capturedAt: start.addingTimeInterval(1),
            latitude: 39.96210
        )
        let second = fixtureLocation(
            capturedAt: start.addingTimeInterval(1.5),
            latitude: 39.96214
        )
        let capture = Task { @MainActor in
            await model.handleLocations([first, second])
        }
        let fixDidBlock = await Task.detached {
            fixFault.waitUntilBlocked(timeout: 2)
        }.value
        XCTAssertTrue(
            fixDidBlock,
            "the production fix append must overlap the rider's Pause intent"
        )
        clock.set(wall: start.addingTimeInterval(2), monotonic: 102)
        model.pause()
        fixFault.releaseFirstFailure()
        await failureBarrier.waitUntilEntered()
        try await Task.sleep(for: .milliseconds(100))

        XCTAssertFalse(
            controlReady,
            "Pause must not drain a failed fix before explicit capture Retry owns its callback"
        )
        XCTAssertEqual(model.state, .recording)
        XCTAssertTrue(delivered.isEmpty)

        await failureBarrier.release()
        await capture.value
        try await waitForModel { model.custodyErrorMessage != nil }
        XCTAssertFalse(controlReady)

        sensorSource.set(
            RecordingCaptureSensorSnapshot(
                heartRateBpm: 199,
                cadenceRpm: 99,
                powerObservation: PowerObservation(
                    watts: 999,
                    timestamp: start.addingTimeInterval(99)
                )
            )
        )
        clock.set(wall: start.addingTimeInterval(99), monotonic: 199)
        model.retryCustodyOperation()
        try await waitForModel {
            model.state == .manuallyPaused &&
                model.controlTransitionInFlight == nil &&
                model.custodyErrorMessage == nil
        }

        let persisted = try await custody.persisted(
            owner: RecordingOwner(user: user),
            rideID: rideID
        )
        XCTAssertEqual(
            persisted.events.map(\.kind),
            [.start, .fix, .fix, .manualPause]
        )
        XCTAssertEqual(
            delivered,
            [first.coordinate.latitude, second.coordinate.latitude]
        )
        let fixes = persisted.events.filter { $0.kind == .fix }
        XCTAssertEqual(fixes.map(\.occurredAt), [start.addingTimeInterval(1), start.addingTimeInterval(1)])
        XCTAssertEqual(fixes.map { $0.fix?.heartRateBpm }, [141, 141])
        XCTAssertEqual(fixes.map { $0.fix?.cadenceRpm }, [0, 0])
        XCTAssertEqual(fixes.map { $0.fix?.powerObservation?.watts }, [233, 233])
        let pauseEvent = try XCTUnwrap(persisted.events.first { $0.kind == .manualPause })
        XCTAssertEqual(pauseEvent.occurredAt, start.addingTimeInterval(2))
        XCTAssertEqual(pauseEvent.monotonicOffsetS, 2, accuracy: 0.000_001)
        XCTAssertTrue(controlReady)
        model.stopHardware()
    }

    @MainActor
    func testMOBILE_TRUTHSSection6FailedInFlightPausedCaptureRetriesBeforeQueuedResume() async throws {
        let user = fixtureUser(id: "failed-capture-resume-owner", wallet: "failed-capture-resume-wallet")
        let rideID = "a2732000-0000-4000-8000-00000000000a"
        let clock = GateClock(wall: start, monotonic: 100)
        let fixFault = GateBlockingFirstFixPublishFault()
        let custody = makeCustody(
            at: rootURL,
            beforeEventPublish: { kind, sequence in
                try fixFault.beforePublish(kind: kind, sequence: sequence)
            }
        )
        let runtime = makeRuntime(
            custody: custody,
            queue: GateUploadQueue(),
            clock: clock,
            ids: GateIDSequence([rideID])
        )
        _ = try await runtime.activate(user: user)
        let failureBarrier = GateAsyncBarrier()
        let model = RecordingModel(
            user: user,
            runtime: runtime,
            authorizationStatus: .authorizedWhenInUse,
            locationHardwareEnabled: false,
            wallNow: { clock.wallValue },
            monotonicNow: { clock.monotonicValue },
            beforeCaptureFailureApply: { await failureBarrier.wait() }
        )
        var controlReady = false
        var delivered: [Double] = []
        model.onControlProjectionReady = { transition in
            if transition == .resume { controlReady = true }
        }
        model.onFix = { delivered.append($0.coordinate.latitude) }
        await model.handleAuthorizationChange(.authorizedWhenInUse)
        try await waitForModel { model.state == .recording }
        clock.set(wall: start.addingTimeInterval(1), monotonic: 101)
        model.pause()
        try await waitForModel {
            model.state == .manuallyPaused && model.controlTransitionInFlight == nil
        }

        clock.set(wall: start.addingTimeInterval(2), monotonic: 102)
        let pausedFix = fixtureLocation(
            capturedAt: start.addingTimeInterval(2),
            latitude: 39.96220
        )
        let capture = Task { @MainActor in
            await model.handleLocations([pausedFix])
        }
        let fixDidBlock = await Task.detached {
            fixFault.waitUntilBlocked(timeout: 2)
        }.value
        XCTAssertTrue(fixDidBlock)
        clock.set(wall: start.addingTimeInterval(3), monotonic: 103)
        model.resume()
        fixFault.releaseFirstFailure()
        await failureBarrier.waitUntilEntered()
        XCTAssertFalse(controlReady)
        await failureBarrier.release()
        await capture.value
        try await waitForModel { model.custodyErrorMessage != nil }

        clock.set(wall: start.addingTimeInterval(99), monotonic: 199)
        model.retryCustodyOperation()
        try await waitForModel {
            model.state == .recording &&
                model.controlTransitionInFlight == nil &&
                model.custodyErrorMessage == nil
        }
        XCTAssertTrue(controlReady)
        XCTAssertTrue(delivered.isEmpty, "a fix captured while paused remains ignored")

        clock.set(wall: start.addingTimeInterval(4), monotonic: 104)
        let fresh = fixtureLocation(
            capturedAt: start.addingTimeInterval(4),
            latitude: 39.96224
        )
        await model.handleLocations([fresh])
        let persisted = try await custody.persisted(
            owner: RecordingOwner(user: user),
            rideID: rideID
        )
        XCTAssertEqual(
            persisted.events.map(\.kind),
            [.start, .manualPause, .fix, .manualResume, .fix]
        )
        let resumeEvent = try XCTUnwrap(persisted.events.first { $0.kind == .manualResume })
        XCTAssertEqual(resumeEvent.occurredAt, start.addingTimeInterval(3))
        XCTAssertEqual(resumeEvent.monotonicOffsetS, 3, accuracy: 0.000_001)
        XCTAssertEqual(delivered, [fresh.coordinate.latitude])
        let evidence = try await runtime.recoveryEvidence(ownerID: user.id)
        XCTAssertEqual(evidence?.samples.map(\.latitude), [fresh.coordinate.latitude])
        model.stopHardware()
    }

    @MainActor
    func testMOBILE_TRUTHSSections6And7FailedInFlightCaptureBlocksEndUntilExactRetry() async throws {
        let user = fixtureUser(id: "failed-capture-end-owner", wallet: "failed-capture-end-wallet")
        let rideID = "a2733000-0000-4000-8000-00000000000a"
        let clock = GateClock(wall: start, monotonic: 100)
        let queue = GateUploadQueue()
        let fixFault = GateBlockingFirstFixPublishFault()
        let custody = makeCustody(
            at: rootURL,
            beforeEventPublish: { kind, sequence in
                try fixFault.beforePublish(kind: kind, sequence: sequence)
            }
        )
        let runtime = makeRuntime(
            custody: custody,
            queue: queue,
            clock: clock,
            ids: GateIDSequence([rideID])
        )
        _ = try await runtime.activate(user: user)
        let failureBarrier = GateAsyncBarrier()
        let model = RecordingModel(
            user: user,
            runtime: runtime,
            authorizationStatus: .authorizedWhenInUse,
            locationHardwareEnabled: false,
            wallNow: { clock.wallValue },
            monotonicNow: { clock.monotonicValue },
            beforeCaptureFailureApply: { await failureBarrier.wait() }
        )
        var delivered: [Double] = []
        model.onFix = { delivered.append($0.coordinate.latitude) }
        await model.handleAuthorizationChange(.authorizedWhenInUse)
        try await waitForModel {
            model.state == .recording && model.captureHardwareActive
        }

        clock.set(wall: start.addingTimeInterval(1), monotonic: 101)
        let first = fixtureLocation(
            capturedAt: start.addingTimeInterval(1),
            latitude: 39.96230
        )
        let capture = Task { @MainActor in
            await model.handleLocations([first])
        }
        let fixDidBlock = await Task.detached {
            fixFault.waitUntilBlocked(timeout: 2)
        }.value
        XCTAssertTrue(fixDidBlock)
        clock.set(wall: start.addingTimeInterval(2), monotonic: 102)
        let endTask = Task { @MainActor in
            try await model.end()
        }
        fixFault.releaseFirstFailure()
        await failureBarrier.waitUntilEntered()
        let queueBeforeRetry = await queue.callSnapshot()
        XCTAssertTrue(queueBeforeRetry.isEmpty)
        XCTAssertTrue(delivered.isEmpty)
        await failureBarrier.release()
        await capture.value
        try await waitForModel { model.custodyErrorMessage != nil }

        clock.set(wall: start.addingTimeInterval(99), monotonic: 199)
        model.retryCustodyOperation()
        let finalized = try await endTask.value
        let result = try XCTUnwrap(finalized)
        let persisted = try await custody.persisted(
            owner: RecordingOwner(user: user),
            rideID: rideID
        )
        XCTAssertFalse(result.uploadEligible)
        XCTAssertEqual(
            persisted.events.map(\.kind),
            [.start, .fix, .stop, .finalized]
        )
        XCTAssertEqual(persisted.events.filter { $0.kind == .stop }.count, 1)
        XCTAssertEqual(persisted.events.filter { $0.kind == .finalized }.count, 1)
        let stopEvent = try XCTUnwrap(persisted.events.first { $0.kind == .stop })
        XCTAssertEqual(stopEvent.occurredAt, start.addingTimeInterval(2))
        XCTAssertEqual(stopEvent.monotonicOffsetS, 2, accuracy: 0.000_001)
        XCTAssertEqual(delivered, [first.coordinate.latitude])
        XCTAssertEqual(model.state, .ended)
        XCTAssertFalse(model.captureHardwareActive)
        XCTAssertEqual(model.captureHardwareStartCount, 1)
        let queueAfterRetry = await queue.callSnapshot()
        XCTAssertTrue(queueAfterRetry.isEmpty)
    }

    @MainActor
    func testMOBILE_TRUTHSSection6ProductionDelegateAdmissionPrecedesPauseCutoff() async throws {
        let user = fixtureUser(id: "delegate-cutoff-owner", wallet: "delegate-cutoff-wallet")
        let rideID = "a2734000-0000-4000-8000-00000000000a"
        let clock = GateClock(wall: start, monotonic: 100)
        let custody = makeCustody(at: rootURL)
        let runtime = makeRuntime(
            custody: custody,
            queue: GateUploadQueue(),
            clock: clock,
            ids: GateIDSequence([rideID])
        )
        _ = try await runtime.activate(user: user)
        let model = RecordingModel(
            user: user,
            runtime: runtime,
            authorizationStatus: .authorizedWhenInUse,
            locationHardwareEnabled: false,
            wallNow: { clock.wallValue },
            monotonicNow: { clock.monotonicValue }
        )
        var delivered: [Double] = []
        model.onFix = { delivered.append($0.coordinate.latitude) }
        await model.handleAuthorizationChange(.authorizedWhenInUse)
        try await waitForModel { model.state == .recording }

        clock.set(wall: start.addingTimeInterval(1), monotonic: 101)
        let deliveredByCoreLocation = fixtureLocation(
            capturedAt: start.addingTimeInterval(1),
            latitude: 39.96240
        )
        model.locationManager(
            CLLocationManager(),
            didUpdateLocations: [deliveredByCoreLocation]
        )
        clock.set(wall: start.addingTimeInterval(2), monotonic: 102)
        model.pause()
        try await waitForModel {
            model.state == .manuallyPaused && model.controlTransitionInFlight == nil
        }

        let persisted = try await custody.persisted(
            owner: RecordingOwner(user: user),
            rideID: rideID
        )
        XCTAssertEqual(
            persisted.events.map(\.kind),
            [.start, .fix, .manualPause],
            "a callback already delivered by Core Location belongs before the later Pause"
        )
        XCTAssertEqual(delivered, [deliveredByCoreLocation.coordinate.latitude])
        model.stopHardware()
    }

    @MainActor
    func testMOBILE_TRUTHSSection9_1StaleWalletModelCannotMutateReplacementOwnerRide() async throws {
        let original = fixtureUser(id: "rebound-owner", wallet: "wallet-a")
        let replacement = fixtureUser(id: "rebound-owner", wallet: "wallet-b")
        let originalRideID = "a2735000-0000-4000-8000-00000000000a"
        let replacementRideID = "a2735000-0000-4000-8000-00000000000b"
        let clock = GateClock(wall: start, monotonic: 100)
        let custody = makeCustody(at: rootURL)
        let runtime = makeRuntime(
            custody: custody,
            queue: GateUploadQueue(),
            clock: clock,
            ids: GateIDSequence([originalRideID, replacementRideID])
        )
        _ = try await runtime.activate(user: original)
        let staleModel = RecordingModel(
            user: original,
            runtime: runtime,
            authorizationStatus: .authorizedWhenInUse,
            locationHardwareEnabled: false,
            wallNow: { clock.wallValue },
            monotonicNow: { clock.monotonicValue }
        )
        var staleDeliveries: [Double] = []
        staleModel.onFix = { staleDeliveries.append($0.coordinate.latitude) }
        await staleModel.handleAuthorizationChange(.authorizedWhenInUse)
        try await waitForModel { staleModel.state == .recording }

        clock.set(wall: start.addingTimeInterval(1), monotonic: 101)
        _ = try await runtime.activate(user: replacement)
        _ = try await runtime.start(
            user: replacement,
            at: start.addingTimeInterval(1)
        )
        let staleFix = fixtureLocation(
            capturedAt: start.addingTimeInterval(2),
            latitude: 39.96250
        )
        clock.set(wall: start.addingTimeInterval(2), monotonic: 102)
        await staleModel.handleLocations([staleFix])

        let replacementPersisted = try await custody.persisted(
            owner: RecordingOwner(user: replacement),
            rideID: replacementRideID
        )
        XCTAssertEqual(replacementPersisted.events.map(\.kind), [.start])
        XCTAssertTrue(staleDeliveries.isEmpty)
        XCTAssertNotNil(staleModel.custodyErrorMessage)
    }

    func testMOBILE_TRUTHSSection9_1StaleOwnerStartCannotDrainReplacementPendingEvidence() async throws {
        let stale = fixtureUser(id: "stale-start-owner", wallet: "wallet-a")
        let replacement = fixtureUser(id: "stale-start-owner", wallet: "wallet-b")
        let replacementRideID = "a2735000-0000-4000-8000-00000000000c"
        let clock = GateClock(wall: start, monotonic: 100)
        let fixFault = GateFixEventPublishFault()
        let custody = makeCustody(
            at: rootURL,
            beforeEventPublish: { kind, sequence in
                try fixFault.beforePublish(kind: kind, sequence: sequence)
            }
        )
        let runtime = makeRuntime(
            custody: custody,
            queue: GateUploadQueue(),
            clock: clock,
            ids: GateIDSequence([replacementRideID])
        )
        let replacementOwner = RecordingOwner(user: replacement)
        _ = try await runtime.activate(user: replacement)
        _ = try await runtime.start(user: replacement, at: start)
        let pendingFix = fixtureFix(
            capturedAt: start.addingTimeInterval(1),
            latitude: 39.96255
        )
        clock.set(wall: start.addingTimeInterval(1), monotonic: 101)
        do {
            _ = try await runtime.ingest(
                pendingFix,
                wallNow: clock.wallValue,
                monotonicNowS: clock.monotonicValue,
                owner: replacementOwner
            )
            XCTFail("the replacement owner's fix must remain pending")
        } catch GateTestError.injectedFailure {}

        do {
            _ = try await runtime.start(
                user: stale,
                at: start.addingTimeInterval(2)
            )
            XCTFail("a stale wallet must not start in the replacement owner's runtime")
        } catch LiveRideCustodyError.ownerMismatch {}

        let beforeRetry = try await custody.persisted(
            owner: replacementOwner,
            rideID: replacementRideID
        )
        XCTAssertEqual(
            beforeRetry.events.map(\.kind),
            [.start],
            "initial exact-owner rejection must not drain or suspend replacement evidence"
        )
        let (outcome, _) = try await runtime.retryPendingCapture(
            expectedFix: pendingFix,
            wallNow: clock.wallValue,
            owner: replacementOwner
        )
        XCTAssertEqual(outcome, .recorded)
        let afterRetry = try await custody.persisted(
            owner: replacementOwner,
            rideID: replacementRideID
        )
        XCTAssertEqual(afterRetry.events.map(\.kind), [.start, .fix])
    }

    func testMOBILE_TRUTHSSection9_1RejectedOwnerCannotSuspendPendingDiscardEvidence() async throws {
        let ownerUser = fixtureUser(id: "discard-owner-guard", wallet: "wallet-a")
        let rejectedUser = fixtureUser(id: "discard-owner-guard", wallet: "wallet-b")
        let owner = RecordingOwner(user: ownerUser)
        let rejected = RecordingOwner(user: rejectedUser)
        let rideID = "a2735000-0000-4000-8000-00000000000d"
        let clock = GateClock(wall: start, monotonic: 100)
        let removeFault = GateFailFirstDiscardRemoveFault()
        let custody = makeCustody(
            at: rootURL,
            beforeDiscardRemove: { directory in
                try removeFault.beforeRemove(directory: directory)
            }
        )
        let runtime = makeRuntime(
            custody: custody,
            queue: GateUploadQueue(),
            clock: clock,
            ids: GateIDSequence([rideID])
        )
        _ = try await runtime.activate(user: ownerUser)
        _ = try await runtime.start(user: ownerUser, at: start)
        clock.set(wall: start.addingTimeInterval(1), monotonic: 101)
        _ = try await runtime.ingest(
            fixtureFix(capturedAt: clock.wallValue, latitude: 39.96258),
            wallNow: clock.wallValue,
            monotonicNowS: clock.monotonicValue,
            owner: owner
        )
        let evidence = try await runtime.recoveryEvidence(ownerID: owner.id)
        let recovery = try XCTUnwrap(evidence?.recovery)
        removeFault.arm()
        do {
            try await runtime.discard(recovery)
            XCTFail("the injected pre-remove failure must retain the exact discard intent")
        } catch GateTestError.injectedFailure {}
        let beforeRejectedOwner = try await custody.persisted(owner: owner, rideID: rideID)

        do {
            _ = try await runtime.activate(user: rejectedUser)
            XCTFail("another wallet cannot activate a retained discard intent")
        } catch LiveRideCustodyError.ownerMismatch {}
        clock.set(wall: start.addingTimeInterval(2), monotonic: 102)
        do {
            try await runtime.suspendActive(at: clock.wallValue, owner: rejected)
            XCTFail("a rejected owner must not suspend or mutate the captured ride")
        } catch LiveRideCustodyError.ownerMismatch {}

        let afterRejectedOwner = try await custody.persisted(owner: owner, rideID: rideID)
        XCTAssertEqual(afterRejectedOwner.events, beforeRejectedOwner.events)
        let completed = try await runtime.activate(user: ownerUser)
        XCTAssertNil(completed)
        var deleted = false
        do {
            _ = try await custody.persisted(owner: owner, rideID: rideID)
        } catch {
            deleted = true
        }
        XCTAssertTrue(deleted)
    }

    @MainActor
    func testMOBILE_TRUTHSSection9_1OwnerSurfaceExitInvalidatesReturnedControlProjection() async throws {
        let original = fixtureUser(id: "surface-owner", wallet: "wallet-a")
        let replacement = fixtureUser(id: "surface-owner", wallet: "wallet-b")
        let originalRideID = "a2735000-0000-4000-8000-00000000000e"
        let replacementRideID = "a2735000-0000-4000-8000-00000000000f"
        let clock = GateClock(wall: start, monotonic: 100)
        let custody = makeCustody(at: rootURL)
        let runtime = makeRuntime(
            custody: custody,
            queue: GateUploadQueue(),
            clock: clock,
            ids: GateIDSequence([originalRideID, replacementRideID])
        )
        _ = try await runtime.activate(user: original)
        let projectionBarrier = GateAsyncBarrier()
        let model = RecordingModel(
            user: original,
            runtime: runtime,
            authorizationStatus: .authorizedWhenInUse,
            locationHardwareEnabled: false,
            wallNow: { clock.wallValue },
            monotonicNow: { clock.monotonicValue },
            beforeControlProjectionApply: { await projectionBarrier.wait() }
        )
        var controlReady = false
        model.onControlProjectionReady = { _ in controlReady = true }
        await model.handleAuthorizationChange(.authorizedWhenInUse)
        try await waitForModel { model.state == .recording }

        clock.set(wall: start.addingTimeInterval(1), monotonic: 101)
        model.pause()
        await projectionBarrier.waitUntilEntered()
        model.leaveOwnerSurface()
        _ = try await runtime.activate(user: replacement)
        _ = try await runtime.start(user: replacement, at: start.addingTimeInterval(2))
        await projectionBarrier.release()
        try await Task.sleep(for: .milliseconds(50))

        XCTAssertFalse(controlReady)
        XCTAssertFalse(model.captureHardwareActive)
        let replacementPersisted = try await custody.persisted(
            owner: RecordingOwner(user: replacement),
            rideID: replacementRideID
        )
        XCTAssertEqual(replacementPersisted.events.map(\.kind), [.start])
    }

    @MainActor
    func testMOBILE_TRUTHSSection9_1OwnerSurfaceExitRejectsLaterDelegateCallbacks() async throws {
        let user = fixtureUser(id: "surface-callback-owner", wallet: "surface-callback-wallet")
        let rideID = "a2735000-0000-4000-8000-000000000010"
        let clock = GateClock(wall: start, monotonic: 100)
        let custody = makeCustody(at: rootURL)
        let runtime = makeRuntime(
            custody: custody,
            queue: GateUploadQueue(),
            clock: clock,
            ids: GateIDSequence([rideID])
        )
        _ = try await runtime.activate(user: user)
        let model = RecordingModel(
            user: user,
            runtime: runtime,
            authorizationStatus: .authorizedWhenInUse,
            locationHardwareEnabled: false,
            wallNow: { clock.wallValue },
            monotonicNow: { clock.monotonicValue }
        )
        var admitted: [Double] = []
        var delivered: [Double] = []
        model.onCaptureCallback = { admitted.append($0.coordinate.latitude) }
        model.onFix = { delivered.append($0.coordinate.latitude) }
        await model.handleAuthorizationChange(.authorizedWhenInUse)
        try await waitForModel { model.state == .recording }
        model.leaveOwnerSurface()

        let late = fixtureLocation(
            capturedAt: start.addingTimeInterval(1),
            latitude: 39.96259
        )
        model.locationManager(CLLocationManager(), didUpdateLocations: [late])
        XCTAssertTrue(
            admitted.isEmpty,
            "the production delegate must reject evidence delivered after owner-surface exit"
        )
        await model.handleAuthorizationChange(.authorizedWhenInUse)
        try await Task.sleep(for: .milliseconds(50))

        XCTAssertFalse(model.captureHardwareActive)
        XCTAssertTrue(delivered.isEmpty)
        let persisted = try await custody.persisted(
            owner: RecordingOwner(user: user),
            rideID: rideID
        )
        XCTAssertEqual(
            persisted.events.map(\.kind),
            [.start],
            "callbacks queued after owner-surface teardown cannot create new custody work"
        )

        let idleRoot = rootURL.appendingPathComponent("idle-callback", isDirectory: true)
        let idleRideID = "a2735000-0000-4000-8000-000000000011"
        let idleCustody = makeCustody(at: idleRoot)
        let idleRuntime = makeRuntime(
            custody: idleCustody,
            queue: GateUploadQueue(),
            clock: clock,
            ids: GateIDSequence([idleRideID])
        )
        _ = try await idleRuntime.activate(user: user)
        let idleModel = RecordingModel(
            user: user,
            runtime: idleRuntime,
            authorizationStatus: .authorizedWhenInUse,
            locationHardwareEnabled: false,
            wallNow: { clock.wallValue },
            monotonicNow: { clock.monotonicValue }
        )
        idleModel.leaveOwnerSurface()
        await idleModel.handleAuthorizationChange(.authorizedWhenInUse)
        await idleModel.waitForStartForTesting()

        XCTAssertEqual(idleModel.state, .idle)
        XCTAssertFalse(idleModel.captureHardwareActive)
        let idleRecovery = try await idleCustody.recoverable(owner: RecordingOwner(user: user))
        XCTAssertNil(idleRecovery)
    }

    @MainActor
    func testMOBILE_TRUTHSSection6RetainedEndRejectsLateCaptureAndTickUntilRetry() async throws {
        let user = fixtureUser(id: "retained-end-owner", wallet: "retained-end-wallet")
        let rideID = "a2736000-0000-4000-8000-00000000000a"
        let clock = GateClock(wall: start, monotonic: 100)
        let fault = GateFinalizedEventFault()
        let custody = makeCustody(
            at: rootURL,
            beforeEventPublish: { kind, sequence in
                try fault.beforePublish(kind: kind, sequence: sequence)
            }
        )
        let runtime = makeRuntime(
            custody: custody,
            queue: GateUploadQueue(),
            clock: clock,
            ids: GateIDSequence([rideID])
        )
        _ = try await runtime.activate(user: user)
        let model = RecordingModel(
            user: user,
            runtime: runtime,
            authorizationStatus: .authorizedWhenInUse,
            locationHardwareEnabled: false,
            wallNow: { clock.wallValue },
            monotonicNow: { clock.monotonicValue }
        )
        var admittedCallbacks: [Double] = []
        model.onCaptureCallback = { admittedCallbacks.append($0.coordinate.latitude) }
        await model.handleAuthorizationChange(.authorizedWhenInUse)
        try await waitForModel { model.state == .recording }

        clock.set(wall: start.addingTimeInterval(1), monotonic: 101)
        do {
            _ = try await model.end()
            XCTFail("the finalized marker fault must retain the original End intent")
        } catch GateTestError.injectedFailure {
            model.presentFinalizationError()
        }
        let late = fixtureLocation(
            capturedAt: start.addingTimeInterval(2),
            latitude: 39.96260
        )
        clock.set(wall: start.addingTimeInterval(2), monotonic: 102)
        await model.handleLocations([late])
        await model.handleCaptureTick()

        XCTAssertTrue(admittedCallbacks.isEmpty)
        XCTAssertFalse(model.captureRetryPendingForTesting)
        XCTAssertNil(model.failedCustodyOperationForTesting)
        let finalized = try await model.end()
        XCTAssertNotNil(finalized)
        let persisted = try await custody.persisted(
            owner: RecordingOwner(user: user),
            rideID: rideID
        )
        XCTAssertEqual(persisted.events.map(\.kind), [.start, .stop, .finalized])
    }

    @MainActor
    func testMOBILE_TRUTHSSection6SuccessfulEndRejectsLateCaptureAndTick() async throws {
        let user = fixtureUser(id: "successful-end-owner", wallet: "successful-end-wallet")
        let rideID = "a2736000-0000-4000-8000-00000000000b"
        let clock = GateClock(wall: start, monotonic: 100)
        let custody = makeCustody(at: rootURL)
        let runtime = makeRuntime(
            custody: custody,
            queue: GateUploadQueue(),
            clock: clock,
            ids: GateIDSequence([rideID])
        )
        _ = try await runtime.activate(user: user)
        let model = RecordingModel(
            user: user,
            runtime: runtime,
            authorizationStatus: .authorizedWhenInUse,
            locationHardwareEnabled: false,
            wallNow: { clock.wallValue },
            monotonicNow: { clock.monotonicValue }
        )
        var admittedCallbacks: [Double] = []
        model.onCaptureCallback = { admittedCallbacks.append($0.coordinate.latitude) }
        await model.handleAuthorizationChange(.authorizedWhenInUse)
        try await waitForModel { model.state == .recording }
        clock.set(wall: start.addingTimeInterval(1), monotonic: 101)
        _ = try await model.end()

        let late = fixtureLocation(
            capturedAt: start.addingTimeInterval(2),
            latitude: 39.96265
        )
        clock.set(wall: start.addingTimeInterval(2), monotonic: 102)
        await model.handleLocations([late])
        await model.handleCaptureTick()

        XCTAssertEqual(model.state, .ended)
        XCTAssertTrue(admittedCallbacks.isEmpty)
        XCTAssertFalse(model.captureRetryPendingForTesting)
        XCTAssertNil(model.failedCustodyOperationForTesting)
        XCTAssertNil(model.custodyErrorMessage)
        let persisted = try await custody.persisted(
            owner: RecordingOwner(user: user),
            rideID: rideID
        )
        XCTAssertEqual(persisted.events.map(\.kind), [.start, .stop, .finalized])
    }

    @MainActor
    func testMOBILE_TRUTHSSection9_1SuspensionAbortsReturnedControlProjection() async throws {
        let user = fixtureUser(id: "abort-control-owner", wallet: "abort-control-wallet")
        let rideID = "a2737000-0000-4000-8000-00000000000a"
        let clock = GateClock(wall: start, monotonic: 100)
        let publishBarrier = GateEventPublishBarrier(blocking: .manualPause)
        let custody = makeCustody(
            at: rootURL,
            beforeEventPublish: { kind, sequence in
                try publishBarrier.beforePublish(kind: kind, sequence: sequence)
            }
        )
        let runtime = makeRuntime(
            custody: custody,
            queue: GateUploadQueue(),
            clock: clock,
            ids: GateIDSequence([rideID])
        )
        _ = try await runtime.activate(user: user)
        let projectionBarrier = GateAsyncBarrier()
        let model = RecordingModel(
            user: user,
            runtime: runtime,
            authorizationStatus: .authorizedWhenInUse,
            locationHardwareEnabled: false,
            wallNow: { clock.wallValue },
            monotonicNow: { clock.monotonicValue },
            beforeControlProjectionApply: { await projectionBarrier.wait() }
        )
        var controlReady = false
        model.onControlProjectionReady = { _ in controlReady = true }
        await model.handleAuthorizationChange(.authorizedWhenInUse)
        try await waitForModel { model.state == .recording }

        clock.set(wall: start.addingTimeInterval(1), monotonic: 101)
        model.pause()
        let pauseDidBlock = await Task.detached {
            publishBarrier.waitUntilBlocked(timeout: 2)
        }.value
        XCTAssertTrue(pauseDidBlock)
        publishBarrier.release()
        await projectionBarrier.waitUntilEntered()

        clock.set(wall: start.addingTimeInterval(2), monotonic: 102)
        try await model.suspendAndLeave()
        XCTAssertFalse(model.captureHardwareActive)
        XCTAssertFalse(controlReady)
        await projectionBarrier.release()
        try await Task.sleep(for: .milliseconds(50))

        XCTAssertFalse(controlReady)
        XCTAssertFalse(model.captureHardwareActive)
        let persisted = try await custody.persisted(
            owner: RecordingOwner(user: user),
            rideID: rideID
        )
        XCTAssertEqual(persisted.events.map(\.kind), [.start, .manualPause, .suspend])
    }

    @MainActor
    func testMOBILE_TRUTHSSection6PauseFailureQueuesCaptureAndTickUntilRetry() async throws {
        let user = fixtureUser(id: "pause-control-owner", wallet: "pause-control-wallet")
        let rideID = "a2740000-0000-4000-8000-00000000000a"
        let clock = GateClock(wall: start, monotonic: 100)
        let fault = GateEventKindAfterMoveSyncFault(target: .manualPause)
        let custody = makeCustody(
            at: rootURL,
            beforeEventPublish: { kind, sequence in
                fault.beforePublish(kind: kind, sequence: sequence)
            },
            beforeDirectorySync: { directory in
                try fault.beforeSync(directory: directory)
            }
        )
        let runtime = makeRuntime(
            custody: custody,
            queue: GateUploadQueue(),
            clock: clock,
            ids: GateIDSequence([rideID])
        )
        _ = try await runtime.activate(user: user)
        let sensorSource = GateCaptureSensorSource(
            RecordingCaptureSensorSnapshot(
                heartRateBpm: nil,
                cadenceRpm: 0,
                powerObservation: PowerObservation(
                    watts: 211,
                    timestamp: start.addingTimeInterval(2)
                )
            )
        )
        let model = RecordingModel(
            user: user,
            runtime: runtime,
            authorizationStatus: .authorizedWhenInUse,
            locationHardwareEnabled: false,
            wallNow: { clock.wallValue },
            monotonicNow: { clock.monotonicValue },
            captureSensorSnapshot: { sensorSource.snapshot() }
        )
        var delivered: [Double] = []
        model.onFix = { delivered.append($0.coordinate.latitude) }
        await model.handleAuthorizationChange(.authorizedWhenInUse)
        try await waitForModel { model.state == .recording }

        fault.arm()
        model.pause()
        try await waitForModel {
            model.controlTransitionInFlight == nil && model.custodyErrorMessage != nil
        }
        clock.set(wall: start.addingTimeInterval(2), monotonic: 102)
        let held = fixtureLocation(
            capturedAt: start.addingTimeInterval(2),
            latitude: 39.96300
        )
        await model.handleLocations([held])
        await model.handleCaptureTick()
        XCTAssertNotNil(model.custodyErrorMessage)
        XCTAssertTrue(delivered.isEmpty)

        sensorSource.set(
            RecordingCaptureSensorSnapshot(
                heartRateBpm: 199,
                cadenceRpm: 99,
                powerObservation: PowerObservation(
                    watts: 999,
                    timestamp: start.addingTimeInterval(99)
                )
            )
        )
        clock.set(wall: start.addingTimeInterval(99), monotonic: 199)
        model.retryCustodyOperation()
        try await waitForModel {
            model.state == .manuallyPaused &&
                model.controlTransitionInFlight == nil &&
                model.custodyErrorMessage == nil
        }
        model.resume()
        try await waitForModel {
            model.state == .recording && model.controlTransitionInFlight == nil
        }
        let fresh = fixtureLocation(
            capturedAt: start.addingTimeInterval(3),
            latitude: 39.96304
        )
        await model.handleLocations([fresh])

        let evidence = try await runtime.recoveryEvidence(ownerID: user.id)
        let persisted = try await custody.persisted(
            owner: RecordingOwner(user: user),
            rideID: rideID
        )
        XCTAssertEqual(evidence?.samples.map(\.latitude), [fresh.coordinate.latitude])
        XCTAssertEqual(delivered, [fresh.coordinate.latitude])
        XCTAssertEqual(
            persisted.events.map(\.kind),
            [.start, .manualPause, .fix, .manualResume, .fix]
        )
        let heldEvent = try XCTUnwrap(persisted.events.first { $0.kind == .fix })
        XCTAssertEqual(heldEvent.occurredAt, start.addingTimeInterval(2))
        XCTAssertNil(heldEvent.fix?.heartRateBpm)
        XCTAssertEqual(heldEvent.fix?.cadenceRpm, 0)
        XCTAssertEqual(heldEvent.fix?.powerObservation?.watts, 211)
        model.stopHardware()
    }

    @MainActor
    func testMOBILE_TRUTHSSection6ResumeFailureQueuesCaptureAndTickUntilRetry() async throws {
        let user = fixtureUser(id: "resume-control-owner", wallet: "resume-control-wallet")
        let rideID = "a2750000-0000-4000-8000-00000000000a"
        let clock = GateClock(wall: start, monotonic: 100)
        let fault = GateEventKindAfterMoveSyncFault(target: .manualResume)
        let custody = makeCustody(
            at: rootURL,
            beforeEventPublish: { kind, sequence in
                fault.beforePublish(kind: kind, sequence: sequence)
            },
            beforeDirectorySync: { directory in
                try fault.beforeSync(directory: directory)
            }
        )
        let runtime = makeRuntime(
            custody: custody,
            queue: GateUploadQueue(),
            clock: clock,
            ids: GateIDSequence([rideID])
        )
        _ = try await runtime.activate(user: user)
        let model = RecordingModel(
            user: user,
            runtime: runtime,
            authorizationStatus: .authorizedWhenInUse,
            locationHardwareEnabled: false,
            wallNow: { clock.wallValue },
            monotonicNow: { clock.monotonicValue }
        )
        var delivered: [Double] = []
        model.onFix = { delivered.append($0.coordinate.latitude) }
        await model.handleAuthorizationChange(.authorizedWhenInUse)
        try await waitForModel { model.state == .recording }
        model.pause()
        try await waitForModel {
            model.state == .manuallyPaused && model.controlTransitionInFlight == nil
        }

        fault.arm()
        model.resume()
        try await waitForModel {
            model.controlTransitionInFlight == nil && model.custodyErrorMessage != nil
        }
        let held = fixtureLocation(
            capturedAt: start.addingTimeInterval(2),
            latitude: 39.96400
        )
        await model.handleLocations([held])
        await model.handleCaptureTick()
        XCTAssertNotNil(model.custodyErrorMessage)
        XCTAssertTrue(delivered.isEmpty)

        model.retryCustodyOperation()
        try await waitForModel {
            model.state == .recording &&
                model.controlTransitionInFlight == nil &&
                model.custodyErrorMessage == nil &&
                delivered.count == 1
        }
        let fresh = fixtureLocation(
            capturedAt: start.addingTimeInterval(3),
            latitude: 39.96404
        )
        await model.handleLocations([fresh])

        let evidence = try await runtime.recoveryEvidence(ownerID: user.id)
        let persisted = try await custody.persisted(
            owner: RecordingOwner(user: user),
            rideID: rideID
        )
        XCTAssertEqual(
            evidence?.samples.map(\.latitude),
            [held.coordinate.latitude, fresh.coordinate.latitude]
        )
        XCTAssertEqual(
            delivered,
            [held.coordinate.latitude, fresh.coordinate.latitude]
        )
        XCTAssertEqual(
            persisted.events.map(\.kind),
            [.start, .manualPause, .manualResume, .fix, .fix]
        )
        model.stopHardware()
    }

    func testMOBILE_TRUTHSSection6RapidDuplicatePauseDoesNotCreateCustodyFailure() async throws {
        let user = fixtureUser(id: "control-owner", wallet: "control-wallet")
        let rideID = "48000000-0000-4000-8000-000000000004"
        let clock = GateClock(wall: start, monotonic: 100)
        let barrier = GateEventPublishBarrier(blocking: .manualPause)
        let custody = makeCustody(
            at: rootURL,
            beforeEventPublish: { kind, sequence in
                try barrier.beforePublish(kind: kind, sequence: sequence)
            }
        )
        let runtime = makeRuntime(
            custody: custody,
            queue: GateUploadQueue(),
            clock: clock,
            ids: GateIDSequence([rideID])
        )
        _ = try await runtime.activate(user: user)
        _ = try await runtime.start(user: user, at: start)
        let model = await MainActor.run {
            RecordingModel(
                user: user,
                runtime: runtime,
                authorizationStatus: .authorizedWhenInUse,
                locationHardwareEnabled: false
            )
        }

        await MainActor.run { model.pause() }
        let didBlock = await Task.detached {
            barrier.waitUntilBlocked(timeout: 2)
        }.value
        XCTAssertTrue(didBlock, "the first Pause must remain pending while the duplicate arrives")
        await MainActor.run { model.pause() }
        barrier.release()
        try await Task.sleep(for: .milliseconds(200))

        let result = await MainActor.run {
            (model.state, model.custodyErrorMessage, model.controlTransitionInFlight)
        }
        await MainActor.run { model.stopHardware() }
        XCTAssertEqual(result.0, .manuallyPaused)
        XCTAssertNil(result.1)
        XCTAssertNil(result.2)
        XCTAssertEqual(barrier.publishedKinds(), [.start, .manualPause])
    }

    func testMOBILE_TRUTHSSection6EligibleManualPausedStopStampsBeforeExactlyOneQueueJob() async throws {
        let user = fixtureUser(id: "paused-stop-owner", wallet: "paused-stop-wallet")
        let rideID = "49000000-0000-4000-8000-000000000004"
        let clock = GateClock(wall: start, monotonic: 100)
        let custody = makeCustody(at: rootURL)
        let queue = GateUploadQueue()
        let runtime = makeRuntime(
            custody: custody,
            queue: queue,
            clock: clock,
            ids: GateIDSequence([rideID])
        )

        _ = try await runtime.activate(user: user)
        _ = try await runtime.start(user: user, at: start)
        _ = try await ingestEligibleRide(runtime: runtime, clock: clock)
        clock.set(wall: start.addingTimeInterval(32), monotonic: 132)
        let paused = try await runtime.manualPause(at: clock.wallValue)
        XCTAssertEqual(paused.state, .manuallyPaused)

        clock.set(wall: start.addingTimeInterval(40), monotonic: 140)
        let finalized = try await runtime.stop(at: clock.wallValue)
        let calls = await queue.callSnapshot()
        let persisted = try await custody.persisted(
            owner: RecordingOwner(user: user),
            rideID: rideID
        )

        XCTAssertTrue(finalized.uploadEligible)
        XCTAssertEqual(finalized.uploadJobID, rideID)
        XCTAssertEqual(calls.count, 1)
        XCTAssertEqual(calls.first?.jobID, rideID)
        XCTAssertEqual(calls.first?.sourceBytes, finalized.gpxBytes)
        XCTAssertEqual(calls.first?.parserVersion, finalized.parserVersion)
        XCTAssertEqual(calls.first?.preliminaryRideHash, finalized.preliminaryRideHash)
        XCTAssertEqual(persisted.events.filter { $0.kind == .manualPause }.count, 1)
        XCTAssertEqual(persisted.events.filter { $0.kind == .stop }.count, 1)
        XCTAssertEqual(persisted.events.filter { $0.kind == .finalized }.count, 1)
        XCTAssertEqual(persisted.events.filter { $0.kind == .handedOff }.count, 1)
    }

    func testMOBILE_TRUTHSSection7SameProcessQueueFailureReusesExactFinalArtifactAndJobID() async throws {
        let user = fixtureUser(id: "same-process-owner", wallet: "same-process-wallet")
        let rideID = "50000000-0000-4000-8000-000000000005"
        let clock = GateClock(wall: start, monotonic: 100)
        let custody = makeCustody(at: rootURL)
        let queue = GateUploadQueue(failuresRemaining: 1)
        let runtime = makeRuntime(
            custody: custody,
            queue: queue,
            clock: clock,
            ids: GateIDSequence([rideID])
        )
        _ = try await runtime.activate(user: user)
        _ = try await runtime.start(user: user, at: start)
        _ = try await ingestEligibleRide(runtime: runtime, clock: clock)
        clock.set(wall: start.addingTimeInterval(40), monotonic: 140)

        do {
            _ = try await runtime.stop(at: clock.wallValue)
            XCTFail("the first queue handoff must fail")
        } catch GateTestError.uploadUnavailable {
            // Expected.
        }
        let afterFailure = try await custody.persisted(
            owner: RecordingOwner(user: user),
            rideID: rideID
        )
        XCTAssertNotNil(afterFailure.finalArtifact)
        XCTAssertFalse(afterFailure.isHandedOff)

        clock.set(wall: start.addingTimeInterval(400), monotonic: 500)
        let finalized = try await runtime.stop(at: clock.wallValue)
        let calls = await queue.callSnapshot()

        XCTAssertEqual(calls.count, 2)
        XCTAssertEqual(calls[0], calls[1])
        XCTAssertEqual(calls[0].jobID, rideID)
        XCTAssertEqual(finalized.gpxBytes, calls[0].sourceBytes)
        XCTAssertEqual(finalized.fileHash, FileRideUploadJobStore.sha256(calls[0].sourceBytes))
        XCTAssertEqual(finalized.preliminaryRideHash, calls[0].preliminaryRideHash)
        XCTAssertEqual(finalized.uploadJobID, rideID)
    }

    func testMOBILE_TRUTHSSection7RelaunchAfterQueueFailureReusesExactFinalArtifactAndJobID() async throws {
        let user = fixtureUser(id: "relaunch-owner", wallet: "relaunch-wallet")
        let rideID = "60000000-0000-4000-8000-000000000006"
        let fractionalStart = Date(timeIntervalSince1970: 1_800_000_000.123)
        let clock = GateClock(wall: fractionalStart, monotonic: 100)
        let firstQueue = GateUploadQueue(failuresRemaining: 1)
        let firstRuntime = makeRuntime(
            custody: makeCustody(at: rootURL),
            queue: firstQueue,
            clock: clock,
            ids: GateIDSequence([rideID])
        )
        _ = try await firstRuntime.activate(user: user)
        _ = try await firstRuntime.start(user: user, at: fractionalStart)
        _ = try await ingestEligibleRide(
            runtime: firstRuntime,
            clock: clock,
            rideStart: fractionalStart
        )
        clock.set(wall: fractionalStart.addingTimeInterval(40), monotonic: 140)
        do {
            _ = try await firstRuntime.stop(at: clock.wallValue)
            XCTFail("the first queue handoff must fail")
        } catch GateTestError.uploadUnavailable {
            // Expected.
        }

        let secondQueue = GateUploadQueue()
        let relaunched = makeRuntime(
            custody: makeCustody(at: rootURL),
            queue: secondQueue,
            clock: GateClock(wall: fractionalStart.addingTimeInterval(500), monotonic: 3),
            ids: GateIDSequence([])
        )
        let recovery = try await relaunched.activate(user: user)
        let firstCalls = await firstQueue.callSnapshot()
        let secondCalls = await secondQueue.callSnapshot()

        XCTAssertNil(recovery, "a finalized ride is reconciled, not offered as an unfinished ride")
        XCTAssertEqual(firstCalls.count, 1)
        XCTAssertEqual(secondCalls.count, 1)
        XCTAssertEqual(firstCalls[0], secondCalls[0])
        XCTAssertEqual(firstCalls[0].summary, secondCalls[0].summary)
        XCTAssertEqual(
            firstCalls[0].summary.startedAt,
            Date(timeIntervalSince1970: floor(fractionalStart.timeIntervalSince1970))
        )
        XCTAssertEqual(firstCalls[0].preliminaryRideHash, secondCalls[0].preliminaryRideHash)
        let persisted = try await makeCustody(at: rootURL).persisted(
            owner: RecordingOwner(user: user),
            rideID: rideID
        )
        XCTAssertTrue(persisted.isHandedOff)
    }

    func testMOBILE_TRUTHSSections7And8FirstPartyEnqueuePersistsBeforePrivacyReviewWithoutNetwork() async throws {
        let owner = RecordingOwner(id: "runtime-owner", wallet: "runtime-wallet")
        let jobID = "61000000-0000-4000-8000-000000000006"
        let source = Data("first-party-native-gpx-evidence".utf8)
        let store = FileRideUploadJobStore(
            rootURL: rootURL.appendingPathComponent("runtime-upload", isDirectory: true)
        )
        let transfer = GateNoNetworkRideTransfer()
        let reconciliation = GateImmediateReconcileProbe()
        let runtime = RideUploadRuntime(
            store: store,
            transfer: transfer,
            durableAccountWorkPermitted: { _ in true },
            immediateReconcile: { reconciledJobID, reconciledOwnerID in
                await reconciliation.reconcile(
                    jobID: reconciledJobID,
                    ownerID: reconciledOwnerID
                )
            }
        )
        await runtime.activate(user: fixtureUser(id: owner.id, wallet: owner.wallet))

        let returned = try await runtime.enqueueFirstParty(
            owner: owner,
            jobID: jobID,
            fileName: "Ride-\(jobID).gpx",
            sourceBytes: source,
            summary: LocalRideSummary(
                startedAt: start,
                distanceM: 1_234,
                elevationM: 56,
                durationS: 321
            ),
            parserVersion: 7,
            preliminaryRideHash: String(repeating: "b", count: 64)
        )
        await Task.yield()

        let storedValue = try await store.job(id: jobID, ownerID: owner.id)
        let stored = try XCTUnwrap(storedValue)
        let storedSourceURL = try await store.sourceURL(for: stored)
        let storedSource = try Data(contentsOf: storedSourceURL)
        let reconciliationCalls = await reconciliation.snapshot()
        let transferCallCount = await transfer.callCount()
        let reconciliationFinishedBeforeRelease = await reconciliation.hasFinished()

        XCTAssertEqual(returned.id, stored.id)
        XCTAssertEqual(returned.ownerID, stored.ownerID)
        XCTAssertEqual(returned.ownerWallet, stored.ownerWallet)
        XCTAssertEqual(returned.fileHash, stored.fileHash)
        XCTAssertEqual(returned.localSummary, stored.localSummary)
        XCTAssertEqual(returned.parserVersion, stored.parserVersion)
        XCTAssertEqual(returned.preliminaryRideHash, stored.preliminaryRideHash)
        XCTAssertEqual(returned.phase, stored.phase)
        XCTAssertEqual(storedSource, source)
        XCTAssertEqual(returned.phase, .awaitingPrivacyReview)
        XCTAssertTrue(reconciliationCalls.isEmpty)
        XCTAssertEqual(transferCallCount, 0)
        XCTAssertFalse(reconciliationFinishedBeforeRelease)
    }

    func testMOBILE_TRUTHSSections6And7UploadJobMigrationDecodeAndStampedStoreRoundTrip() async throws {
        let source = Data("exact-first-party-gpx".utf8)
        let stamped = fixtureUploadJob(
            id: "70000000-0000-4000-8000-000000000007",
            ownerID: "migration-owner",
            ownerWallet: "migration-wallet",
            sourceBytes: source,
            parserVersion: 7,
            preliminaryRideHash: String(repeating: "a", count: 64)
        )

        let encoder = JSONEncoder()
        let decoder = JSONDecoder()
        let legacy = fixtureUploadJob(
            id: "70000000-0000-4000-8000-000000000008",
            ownerID: "migration-owner",
            ownerWallet: "migration-wallet",
            sourceBytes: source,
            parserVersion: nil,
            preliminaryRideHash: nil
        )
        let legacyBytes = try encoder.encode(legacy)
        let legacyObject = try XCTUnwrap(
            try JSONSerialization.jsonObject(with: legacyBytes) as? [String: Any]
        )
        XCTAssertNil(legacyObject["parserVersion"])
        XCTAssertNil(legacyObject["preliminaryRideHash"])
        let decodedLegacy = try decoder.decode(RideUploadJob.self, from: legacyBytes)
        XCTAssertNil(decodedLegacy.parserVersion)
        XCTAssertNil(decodedLegacy.preliminaryRideHash)
        XCTAssertNil(decodedLegacy.publication)

        let uploadRoot = rootURL.appendingPathComponent("upload-store", isDirectory: true)
        let firstStore = FileRideUploadJobStore(rootURL: uploadRoot)
        try await firstStore.create(stamped, sourceBytes: source)
        let relaunchedStore = FileRideUploadJobStore(rootURL: uploadRoot)
        let reloadedStamped = try await relaunchedStore.job(
            id: stamped.id,
            ownerID: stamped.ownerID
        )
        let decodedStamped = try XCTUnwrap(reloadedStamped)

        XCTAssertEqual(decodedStamped, stamped)
        XCTAssertEqual(decodedStamped.parserVersion, 7)
        XCTAssertEqual(decodedStamped.preliminaryRideHash, String(repeating: "a", count: 64))
    }

    func testMOBILE_TRUTHSSections9_1And11CrossOwnerSuspendAndDiscardStayOwnerExact() async throws {
        let ownerA = fixtureUser(id: "owner-a", wallet: "wallet-a")
        let ownerB = fixtureUser(id: "owner-b", wallet: "wallet-b")
        let rideA = "80000000-0000-4000-8000-000000000008"
        let rideB = "80000000-0000-4000-8000-000000000009"
        let clock = GateClock(wall: start, monotonic: 100)
        let custody = makeCustody(at: rootURL)
        let runtime = makeRuntime(
            custody: custody,
            queue: GateUploadQueue(),
            clock: clock,
            ids: GateIDSequence([rideA, rideB])
        )

        _ = try await runtime.activate(user: ownerA)
        _ = try await runtime.start(user: ownerA, at: start)
        clock.set(wall: start.addingTimeInterval(1), monotonic: 101)
        _ = try await runtime.ingest(
            fixtureFix(capturedAt: clock.wallValue, latitude: 39.95),
            wallNow: clock.wallValue
        )

        let initialOwnerBRecovery = try await runtime.activate(user: ownerB)
        XCTAssertNil(initialOwnerBRecovery)
        _ = try await runtime.start(user: ownerB, at: start.addingTimeInterval(2))
        clock.set(wall: start.addingTimeInterval(3), monotonic: 103)
        _ = try await runtime.ingest(
            fixtureFix(capturedAt: clock.wallValue, latitude: 40.01),
            wallNow: clock.wallValue
        )

        let forgedA = InterruptedRideRecovery(
            id: rideA,
            ownerID: ownerA.id,
            startedAt: start,
            state: .recording,
            sampleCount: 1,
            durationS: 1,
            distanceM: 0,
            elevationGainM: nil
        )
        do {
            try await runtime.discard(forgedA)
            XCTFail("owner B must not discard owner A evidence")
        } catch let error as LiveRideCustodyError {
            XCTAssertEqual(error, .ownerMismatch)
        }

        let selectedA = try await runtime.activate(user: ownerA)
        let recoveredA = try XCTUnwrap(selectedA)
        XCTAssertEqual(recoveredA.id, rideA)
        try await runtime.discard(recoveredA)
        let selectedB = try await runtime.activate(user: ownerB)
        let recoveredB = try XCTUnwrap(selectedB)

        XCTAssertEqual(recoveredB.id, rideB)
        let remainingA = try await custody.recoverable(owner: RecordingOwner(user: ownerA))
        let remainingB = try await custody.recoverable(owner: RecordingOwner(user: ownerB))
        XCTAssertNil(remainingA)
        XCTAssertEqual(remainingB?.manifest.id, rideB)
    }

    func testMOBILE_TRUTHSSection9_1JournalIsCiphertextAndOtherOwnerSeesNoRide() async throws {
        let owner = fixtureUser(
            id: "owner-secret-cc01-9f02a5a7",
            wallet: "wallet-secret-cc01-evidence-47d6f1c3"
        )
        let other = fixtureUser(id: "other-owner", wallet: "other-wallet")
        let rideID = "90000000-0000-4000-8000-000000000009"
        let clock = GateClock(wall: start, monotonic: 100)
        let runtime = makeRuntime(
            custody: makeCustody(at: rootURL),
            queue: GateUploadQueue(),
            clock: clock,
            ids: GateIDSequence([rideID])
        )
        _ = try await runtime.activate(user: owner)
        _ = try await runtime.start(user: owner, at: start)
        clock.set(wall: start.addingTimeInterval(1), monotonic: 101)
        _ = try await runtime.ingest(
            fixtureFix(
                capturedAt: clock.wallValue,
                latitude: 39.9512345,
                heartRateBpm: 177,
                cadenceRpm: 88,
                powerWatts: 377
            ),
            wallNow: clock.wallValue
        )
        _ = try await runtime.activate(user: nil)

        let storedBytes = try allRegularFileData(in: rootURL)
        for secret in [owner.id, owner.wallet, "39.9512345", "\"377\""] {
            XCTAssertNil(
                storedBytes.range(of: Data(secret.utf8)),
                "MOBILE_TRUTHS §9.1 local evidence must not be plaintext at rest"
            )
        }

        let relaunched = makeRuntime(
            custody: makeCustody(at: rootURL),
            queue: GateUploadQueue(),
            clock: GateClock(wall: start.addingTimeInterval(10), monotonic: 1),
            ids: GateIDSequence([])
        )
        let otherRecovery = try await relaunched.activate(user: other)
        XCTAssertNil(otherRecovery)
        let selectedOwnerRecovery = try await relaunched.activate(user: owner)
        let recovered = try XCTUnwrap(selectedOwnerRecovery)
        XCTAssertEqual(recovered.id, rideID)
        XCTAssertEqual(recovered.sampleCount, 1)
    }

    func testMOBILE_TRUTHSSection9_1LegacyQuarantineAndKeyBootstrapAreFailClosed() async throws {
        let owner = RecordingOwner(id: "bootstrap-owner", wallet: "bootstrap-wallet")
        let rideID = "a0000000-0000-4000-8000-00000000000a"
        let freshRoot = rootURL.appendingPathComponent("fresh", isDirectory: true)
        let freshProbe = GateKeyLoaderProbe(key: masterKey)
        let freshStore = FileLiveRideCustodyStore(
            rootURL: freshRoot,
            keyLoader: { existingStore in
                freshProbe.load(existingStore: existingStore)
            }
        )
        try await freshStore.create(owner: owner, rideID: rideID, startedAt: start)
        XCTAssertEqual(freshProbe.snapshot(), [false])

        let relaunchProbe = GateKeyLoaderProbe(key: masterKey)
        let relaunched = FileLiveRideCustodyStore(
            rootURL: freshRoot,
            keyLoader: { existingStore in
                relaunchProbe.load(existingStore: existingStore)
            }
        )
        let relaunchedRecovery = try await relaunched.recoverable(owner: owner)
        XCTAssertEqual(relaunchedRecovery?.manifest.id, rideID)
        XCTAssertEqual(relaunchProbe.snapshot(), [true])

        let legacyRoot = rootURL.appendingPathComponent("legacy", isDirectory: true)
        try FileManager.default.createDirectory(at: legacyRoot, withIntermediateDirectories: true)
        let legacyBytes = Data("ownerless-legacy-evidence-must-be-preserved".utf8)
        let legacyURL = legacyRoot.appendingPathComponent("recording.json")
        try legacyBytes.write(to: legacyURL)
        let legacyProbe = GateKeyLoaderProbe(key: masterKey)
        let legacyStore = FileLiveRideCustodyStore(
            rootURL: legacyRoot,
            keyLoader: { existingStore in
                legacyProbe.load(existingStore: existingStore)
            }
        )

        let attributedLegacy = try await legacyStore.recoverable(owner: owner)
        XCTAssertNil(attributedLegacy)
        XCTAssertFalse(FileManager.default.fileExists(atPath: legacyURL.path))
        let quarantine = legacyRoot.appendingPathComponent("Quarantine", isDirectory: true)
        let quarantinedBytes = try allRegularFileData(in: quarantine)
        XCTAssertNotNil(quarantinedBytes.range(of: legacyBytes))
        XCTAssertEqual(
            legacyProbe.snapshot(),
            [false],
            "ownerless quarantine is not evidence that an encrypted-store key already exists"
        )

        let postLegacyRideID = "a0000000-0000-4000-8000-00000000000b"
        try await legacyStore.create(
            owner: owner,
            rideID: postLegacyRideID,
            startedAt: start.addingTimeInterval(1)
        )
        let sameProcessRecovery = try await legacyStore.recoverable(owner: owner)
        XCTAssertEqual(sameProcessRecovery?.manifest.id, postLegacyRideID)

        let postLegacyRelaunchProbe = GateKeyLoaderProbe(key: masterKey)
        let postLegacyRelaunch = FileLiveRideCustodyStore(
            rootURL: legacyRoot,
            keyLoader: { existingStore in
                postLegacyRelaunchProbe.load(existingStore: existingStore)
            }
        )
        let postLegacyRecovery = try await postLegacyRelaunch.recoverable(owner: owner)
        XCTAssertEqual(postLegacyRecovery?.manifest.id, postLegacyRideID)
        XCTAssertEqual(postLegacyRelaunchProbe.snapshot(), [true])
    }

    /// §9.1 as amended 2026-08-18: a keychain ERROR stays fail-closed
    /// forever — errors are never proof of absence.
    func testMOBILE_TRUTHSSection9_1KeyErrorForEncryptedStoreFailsClosed() async throws {
        let owner = RecordingOwner(id: "missing-key-owner", wallet: "missing-key-wallet")
        let rideID = "a1000000-0000-4000-8000-00000000000a"
        let encryptedRoot = rootURL.appendingPathComponent("missing-key", isDirectory: true)
        let key = masterKey
        let seeded = FileLiveRideCustodyStore(
            rootURL: encryptedRoot,
            keyLoader: { _ in key }
        )
        try await seeded.create(owner: owner, rideID: rideID, startedAt: start)

        let missingKey = GateMissingKeyLoaderProbe()
        let unavailable = FileLiveRideCustodyStore(
            rootURL: encryptedRoot,
            keyLoader: { existingStore in
                try missingKey.load(existingStore: existingStore)
            },
            keyAbsenceProbe: { false } // keychain errored; absence unproven
        )
        do {
            _ = try await unavailable.recoverable(owner: owner)
            XCTFail("a keychain error must never mint or substitute a new key")
        } catch let error as LiveRideCustodyError {
            XCTAssertEqual(error, .keyUnavailable)
        }
        XCTAssertEqual(missingKey.snapshot(), [true])
    }

    /// §9.1 as amended 2026-08-18 (founder-device incident): POSITIVE key
    /// absence quarantines the unreadable evidence intact and mints a fresh
    /// key — recording is never bricked, and no new key ever reads old bytes.
    func testMOBILE_TRUTHSSection9_1PositiveKeyAbsenceQuarantinesAndRecovers() async throws {
        let owner = RecordingOwner(id: "keyless-owner", wallet: "keyless-wallet")
        let rideID = "a1000000-0000-4000-8000-00000000000b"
        let encryptedRoot = rootURL.appendingPathComponent("keyless", isDirectory: true)
        let oldKey = masterKey
        let seeded = FileLiveRideCustodyStore(
            rootURL: encryptedRoot,
            keyLoader: { _ in oldKey }
        )
        try await seeded.create(owner: owner, rideID: rideID, startedAt: start)
        let sealedBytesBefore = try allRegularFileData(in: encryptedRoot)
        XCTAssertFalse(sealedBytesBefore.isEmpty)

        // Relaunch: the key is gone from the keychain (positively absent).
        var mintCalls: [Bool] = []
        var freshKey = Data(count: 32)
        freshKey[0] = 7
        let recovered = FileLiveRideCustodyStore(
            rootURL: encryptedRoot,
            keyLoader: { existingStore in
                mintCalls.append(existingStore)
                if existingStore { throw KeychainStore.CustodyKeyError.unavailable }
                return freshKey
            },
            keyAbsenceProbe: { true }
        )

        // The unreadable ride is gone from recovery (quarantined, not read).
        let recovery = try await recovered.recoverable(owner: owner)
        XCTAssertNil(recovery)
        XCTAssertEqual(mintCalls, [true, false])

        // The old sealed bytes are preserved exactly under KeylessQuarantine.
        let quarantine = encryptedRoot.appendingPathComponent(
            "KeylessQuarantine", isDirectory: true
        )
        XCTAssertTrue(FileManager.default.fileExists(atPath: quarantine.path))
        let quarantinedBytes = try allRegularFileData(in: quarantine)
        XCTAssertEqual(quarantinedBytes.count, sealedBytesBefore.count)

        // Recording works again with the fresh key.
        let newRideID = "a1000000-0000-4000-8000-00000000000c"
        try await recovered.create(owner: owner, rideID: newRideID, startedAt: start.addingTimeInterval(10))
        let newRecovery = try await recovered.recoverable(owner: owner)
        XCTAssertEqual(newRecovery?.manifest.id, newRideID)
    }

    func testMOBILE_TRUTHSSection9_1TamperedEvidenceStaysOwnerDetectablyUnavailable() async throws {
        let owner = RecordingOwner(id: "tamper-owner", wallet: "tamper-wallet")
        let otherOwnerID = "tamper-other-owner"
        let rideID = "a2000000-0000-4000-8000-00000000000a"
        let tamperRoot = rootURL.appendingPathComponent("tampered", isDirectory: true)
        let key = masterKey
        let seeded = FileLiveRideCustodyStore(
            rootURL: tamperRoot,
            keyLoader: { _ in key }
        )
        try await seeded.create(owner: owner, rideID: rideID, startedAt: start)

        let startEvent = try XCTUnwrap(
            try regularFileURLs(in: tamperRoot).first(where: {
                $0.lastPathComponent == "00000000000000000001.sealed"
            })
        )
        var tamperedBytes = try Data(contentsOf: startEvent)
        XCTAssertFalse(tamperedBytes.isEmpty)
        tamperedBytes[tamperedBytes.startIndex] ^= 0xff
        try tamperedBytes.write(to: startEvent, options: .atomic)

        let relaunched = FileLiveRideCustodyStore(
            rootURL: tamperRoot,
            keyLoader: { _ in key }
        )
        for _ in 0..<2 {
            do {
                _ = try await relaunched.recoverable(owner: owner)
                XCTFail("the owning rider must see unavailable evidence, never an empty recovery")
            } catch let error as LiveRideCustodyError {
                XCTAssertEqual(error, .corruptEvidence)
            }
        }
        let otherOwnerRecovery = try await relaunched.recoverable(
            owner: RecordingOwner(id: otherOwnerID, wallet: "other-wallet")
        )
        XCTAssertNil(otherOwnerRecovery)
        XCTAssertTrue(
            try directoryURLs(in: tamperRoot).contains(where: {
                $0.lastPathComponent == "Unavailable"
            })
        )
    }

    func testMOBILE_TRUTHSSection9_1SuspendFailureClearsMemoryAndRemainsUnavailable() async throws {
        let owner = fixtureUser(id: "suspend-owner", wallet: "suspend-wallet")
        let other = fixtureUser(id: "suspend-other", wallet: "suspend-other-wallet")
        let rideID = "a2500000-0000-4000-8000-00000000000a"
        let clock = GateClock(wall: start, monotonic: 100)
        let fault = GateSuspendEventFault()
        let custody = makeCustody(
            at: rootURL,
            beforeEventPublish: { kind, sequence in
                try fault.beforePublish(kind: kind, sequence: sequence)
            }
        )
        let runtime = makeRuntime(
            custody: custody,
            queue: GateUploadQueue(),
            clock: clock,
            ids: GateIDSequence([rideID])
        )

        _ = try await runtime.activate(user: owner)
        _ = try await runtime.start(user: owner, at: start)
        clock.set(wall: start.addingTimeInterval(1), monotonic: 101)
        _ = try await runtime.ingest(
            fixtureFix(capturedAt: clock.wallValue, latitude: 39.9500),
            wallNow: clock.wallValue
        )

        clock.set(wall: start.addingTimeInterval(2), monotonic: 102)
        do {
            _ = try await runtime.activate(user: other)
            XCTFail("a failed suspend append must not report a clean owner activation")
        } catch GateTestError.injectedFailure {
            // Retained behavioral red: the pre-change runtime swallowed this.
        }

        do {
            _ = try await runtime.ingest(
                fixtureFix(capturedAt: clock.wallValue, latitude: 39.9501),
                wallNow: clock.wallValue
            )
            XCTFail("owner deactivation must clear in-memory capture even when persistence fails")
        } catch let error as LiveRideCustodyError {
            XCTAssertEqual(error, .noActiveRide)
        }

        var persisted = try await custody.persisted(
            owner: RecordingOwner(user: owner),
            rideID: rideID
        )
        XCTAssertEqual(persisted.events.map(\.kind), [.start, .fix])

        clock.set(wall: start.addingTimeInterval(999), monotonic: 1_099)
        try await runtime.suspendActive(at: clock.wallValue)
        persisted = try await custody.persisted(
            owner: RecordingOwner(user: owner),
            rideID: rideID
        )
        XCTAssertEqual(persisted.events.map(\.kind), [.start, .fix, .suspend])
        let suspended = try XCTUnwrap(persisted.events.last)
        XCTAssertEqual(
            suspended.occurredAt,
            start.addingTimeInterval(2),
            "Retry must publish the original failed boundary, never retry time"
        )
        XCTAssertEqual(suspended.monotonicOffsetS, 2, accuracy: 0.001)

        let rightfulRecovery = try await runtime.activate(user: owner)
        XCTAssertEqual(rightfulRecovery?.id, rideID)
        XCTAssertEqual(rightfulRecovery?.sampleCount, 1)
    }

    func testMOBILE_TRUTHSSection9_1PostRenameSyncFailureRetriesExactPendingSuspend() async throws {
        let owner = fixtureUser(id: "sync-suspend-owner", wallet: "sync-suspend-wallet")
        let other = fixtureUser(id: "sync-suspend-other", wallet: "sync-suspend-other-wallet")
        let rideID = "a2510000-0000-4000-8000-00000000000a"
        let clock = GateClock(wall: start, monotonic: 100)
        let fault = GateAfterMoveDirectorySyncFault()
        let custody = makeCustody(
            at: rootURL,
            beforeDirectorySync: { directory in
                try fault.beforeSync(directory: directory)
            }
        )
        let runtime = makeRuntime(
            custody: custody,
            queue: GateUploadQueue(),
            clock: clock,
            ids: GateIDSequence([rideID])
        )

        _ = try await runtime.activate(user: owner)
        _ = try await runtime.start(user: owner, at: start)
        clock.set(wall: start.addingTimeInterval(1), monotonic: 101)
        _ = try await runtime.ingest(
            fixtureFix(capturedAt: clock.wallValue, latitude: 39.9500),
            wallNow: clock.wallValue
        )

        fault.arm()
        clock.set(wall: start.addingTimeInterval(2), monotonic: 102)
        do {
            _ = try await runtime.activate(user: other)
            XCTFail("the injected post-move directory sync failure must remain unavailable")
        } catch GateTestError.injectedFailure {
            // Retained fault red: the authentic destination exists while the
            // in-memory append cursor still points at this sequence.
        }

        clock.set(wall: start.addingTimeInterval(999), monotonic: 1_099)
        try await runtime.suspendActive(at: clock.wallValue)

        let persisted = try await custody.persisted(
            owner: RecordingOwner(user: owner),
            rideID: rideID
        )
        XCTAssertEqual(persisted.events.map(\.kind), [.start, .fix, .suspend])
        XCTAssertEqual(persisted.events.map(\.sequence), [1, 2, 3])
        let suspended = try XCTUnwrap(persisted.events.last)
        XCTAssertEqual(suspended.occurredAt, start.addingTimeInterval(2))
        XCTAssertEqual(suspended.monotonicOffsetS, 2, accuracy: 0.001)
        XCTAssertEqual(fault.failureCount(), 1)

        let selected = try await runtime.activate(user: owner)
        XCTAssertEqual(selected?.id, rideID)
        XCTAssertEqual(selected?.sampleCount, 1)
    }

    func testMOBILE_TRUTHSSection9_1PostRenameSyncFailureIdempotentlyRetriesAnyExactEvent() async throws {
        let owner = RecordingOwner(id: "sync-event-owner", wallet: "sync-event-wallet")
        let rideID = "a2520000-0000-4000-8000-00000000000a"
        let fault = GateAfterMoveDirectorySyncFault()
        let custody = makeCustody(
            at: rootURL,
            beforeDirectorySync: { directory in
                try fault.beforeSync(directory: directory)
            }
        )
        try await custody.create(owner: owner, rideID: rideID, startedAt: start)
        fault.arm()

        do {
            try await custody.append(
                owner: owner,
                rideID: rideID,
                kind: .manualPause,
                occurredAt: start.addingTimeInterval(3),
                monotonicOffsetS: 3,
                stateAtBoundary: .recording
            )
            XCTFail("the first event publish must surface the injected directory sync failure")
        } catch GateTestError.injectedFailure {
            // Destination has moved into place; retry must authenticate it.
        }

        try await custody.append(
            owner: owner,
            rideID: rideID,
            kind: .manualPause,
            occurredAt: start.addingTimeInterval(3),
            monotonicOffsetS: 3,
            stateAtBoundary: .recording
        )
        let persisted = try await custody.persisted(owner: owner, rideID: rideID)
        XCTAssertEqual(persisted.events.map(\.kind), [.start, .manualPause])
        XCTAssertEqual(persisted.events.map(\.sequence), [1, 2])
        XCTAssertEqual(fault.failureCount(), 1)
    }

    func testMOBILE_TRUTHSSection9_1PostRenameFixFailureReplaysBeforeNextDistinctFix() async throws {
        let user = fixtureUser(id: "pending-fix-owner", wallet: "pending-fix-wallet")
        let rideID = "a2530000-0000-4000-8000-00000000000a"
        let clock = GateClock(wall: start, monotonic: 100)
        let fault = GateAfterMoveDirectorySyncFault()
        let custody = makeCustody(
            at: rootURL,
            beforeDirectorySync: { directory in
                try fault.beforeSync(directory: directory)
            }
        )
        let runtime = makeRuntime(
            custody: custody,
            queue: GateUploadQueue(),
            clock: clock,
            ids: GateIDSequence([rideID])
        )
        _ = try await runtime.activate(user: user)
        _ = try await runtime.start(user: user, at: start)

        let first = fixtureFix(
            capturedAt: start.addingTimeInterval(1),
            latitude: 39.9500,
            powerWatts: 210,
            speedMps: 5
        )
        fault.arm()
        clock.set(wall: start.addingTimeInterval(1), monotonic: 101)
        do {
            _ = try await runtime.ingest(first, wallNow: clock.wallValue)
            XCTFail("the first fix must surface the injected post-rename sync failure")
        } catch GateTestError.injectedFailure {}

        let second = fixtureFix(
            capturedAt: start.addingTimeInterval(2),
            latitude: 39.95004,
            powerWatts: 220,
            speedMps: 5
        )
        clock.set(wall: start.addingTimeInterval(2), monotonic: 102)
        let secondResult = try await runtime.ingest(second, wallNow: clock.wallValue)
        XCTAssertEqual(secondResult.0, RecordingSessionIngestOutcome.recorded)
        XCTAssertEqual(secondResult.1.sampleCount, 2)
        XCTAssertEqual(secondResult.1.lastSample?.latitude, second.gps.latitude)

        let evidence = try await runtime.recoveryEvidence(ownerID: user.id)
        XCTAssertEqual(evidence?.samples.count, 2)
        XCTAssertEqual(evidence?.samples.map(\.latitude), [first.gps.latitude, second.gps.latitude])
        let persisted = try await custody.persisted(
            owner: RecordingOwner(user: user),
            rideID: rideID
        )
        XCTAssertEqual(persisted.events.map(\.kind), [.start, .fix, .fix])
        XCTAssertEqual(persisted.events.map(\.sequence), [1, 2, 3])
        XCTAssertEqual(persisted.events.compactMap(\.fix), [first, second])
    }

    func testMOBILE_TRUTHSSection9_1PrepublicationFixFailureRetainsOriginalBeforeNextFix() async throws {
        let user = fixtureUser(id: "pending-prepublish-owner", wallet: "pending-prepublish-wallet")
        let rideID = "a2540000-0000-4000-8000-00000000000a"
        let clock = GateClock(wall: start, monotonic: 100)
        let fault = GateFixEventPublishFault()
        let custody = makeCustody(
            at: rootURL,
            beforeEventPublish: { kind, sequence in
                try fault.beforePublish(kind: kind, sequence: sequence)
            }
        )
        let runtime = makeRuntime(
            custody: custody,
            queue: GateUploadQueue(),
            clock: clock,
            ids: GateIDSequence([rideID])
        )
        _ = try await runtime.activate(user: user)
        _ = try await runtime.start(user: user, at: start)

        let first = fixtureFix(
            capturedAt: start.addingTimeInterval(1),
            latitude: 39.9510,
            speedMps: 5
        )
        clock.set(wall: start.addingTimeInterval(1), monotonic: 101)
        do {
            _ = try await runtime.ingest(first, wallNow: clock.wallValue)
            XCTFail("the pre-publication failure must remain visible")
        } catch GateTestError.injectedFailure {}

        let second = fixtureFix(
            capturedAt: start.addingTimeInterval(2),
            latitude: 39.95104,
            speedMps: 5
        )
        clock.set(wall: start.addingTimeInterval(2), monotonic: 102)
        let result = try await runtime.ingest(second, wallNow: clock.wallValue)
        XCTAssertEqual(result.1.sampleCount, 2)
        let persisted = try await custody.persisted(
            owner: RecordingOwner(user: user),
            rideID: rideID
        )
        XCTAssertEqual(persisted.events.compactMap(\.fix), [first, second])
    }

    @MainActor
    func testMOBILE_TRUTHSSection9_1CaptureBatchCannotSelfClearFailedFixBeforeExplicitRetry() async throws {
        let user = fixtureUser(id: "capture-batch-owner", wallet: "capture-batch-wallet")
        let rideID = "a2580000-0000-4000-8000-00000000000a"
        let clock = GateClock(wall: start, monotonic: 100)
        let fault = GateAfterMoveDirectorySyncFault()
        let custody = makeCustody(
            at: rootURL,
            beforeDirectorySync: { directory in
                try fault.beforeSync(directory: directory)
            }
        )
        let runtime = makeRuntime(
            custody: custody,
            queue: GateUploadQueue(),
            clock: clock,
            ids: GateIDSequence([rideID])
        )
        _ = try await runtime.activate(user: user)
        let model = RecordingModel(
            user: user,
            runtime: runtime,
            authorizationStatus: .authorizedWhenInUse,
            locationHardwareEnabled: false,
            wallNow: { clock.wallValue },
            monotonicNow: { clock.monotonicValue }
        )
        var deliveredLatitudes: [Double] = []
        model.onFix = { deliveredLatitudes.append($0.coordinate.latitude) }
        await model.handleAuthorizationChange(.authorizedWhenInUse)
        try await waitForModel {
            model.state == .recording && model.captureHardwareActive
        }
        XCTAssertEqual(model.captureHardwareStartCount, 1)

        let first = fixtureLocation(
            capturedAt: start.addingTimeInterval(1),
            latitude: 39.95200
        )
        let second = fixtureLocation(
            capturedAt: start.addingTimeInterval(2),
            latitude: 39.95204
        )
        fault.arm()
        await model.handleLocations([first, second])

        XCTAssertNotNil(
            model.custodyErrorMessage,
            "the rest of a delivered batch cannot clear a failed first fix"
        )
        XCTAssertFalse(model.captureHardwareActive)
        XCTAssertTrue(deliveredLatitudes.isEmpty)

        model.retryCustodyOperation()
        try await waitForModel {
            model.custodyErrorMessage == nil &&
                model.captureHardwareActive &&
                deliveredLatitudes.count == 2
        }
        var evidence = try await runtime.recoveryEvidence(ownerID: user.id)
        XCTAssertEqual(evidence?.samples.count, 2)
        XCTAssertEqual(
            evidence?.samples.map(\.latitude),
            [first.coordinate.latitude, second.coordinate.latitude]
        )
        XCTAssertEqual(
            deliveredLatitudes,
            [first.coordinate.latitude, second.coordinate.latitude]
        )
        XCTAssertEqual(model.captureHardwareStartCount, 2)

        let third = fixtureLocation(
            capturedAt: start.addingTimeInterval(3),
            latitude: 39.95208
        )
        await model.handleLocations([third])
        evidence = try await runtime.recoveryEvidence(ownerID: user.id)
        XCTAssertEqual(evidence?.samples.count, 3)
        XCTAssertEqual(
            evidence?.samples.map(\.latitude),
            [
                first.coordinate.latitude,
                second.coordinate.latitude,
                third.coordinate.latitude,
            ]
        )
        XCTAssertEqual(
            deliveredLatitudes,
            [
                first.coordinate.latitude,
                second.coordinate.latitude,
                third.coordinate.latitude,
            ]
        )
        XCTAssertEqual(model.captureHardwareStartCount, 2)
        model.stopHardware()
    }

    @MainActor
    func testMOBILE_TRUTHSSection9_1QueuedTickCannotConsumeFailedFixOrClearCaptureError() async throws {
        let user = fixtureUser(id: "capture-tick-owner", wallet: "capture-tick-wallet")
        let rideID = "a2590000-0000-4000-8000-00000000000a"
        let clock = GateClock(wall: start, monotonic: 100)
        let fault = GateAfterMoveDirectorySyncFault()
        let custody = makeCustody(
            at: rootURL,
            beforeDirectorySync: { directory in
                try fault.beforeSync(directory: directory)
            }
        )
        let runtime = makeRuntime(
            custody: custody,
            queue: GateUploadQueue(),
            clock: clock,
            ids: GateIDSequence([rideID])
        )
        _ = try await runtime.activate(user: user)
        let model = RecordingModel(
            user: user,
            runtime: runtime,
            authorizationStatus: .authorizedWhenInUse,
            locationHardwareEnabled: false,
            wallNow: { clock.wallValue },
            monotonicNow: { clock.monotonicValue }
        )
        var deliveredFixes = 0
        model.onFix = { _ in deliveredFixes += 1 }
        await model.handleAuthorizationChange(.authorizedWhenInUse)
        try await waitForModel {
            model.state == .recording && model.captureHardwareActive
        }

        fault.arm()
        let first = fixtureLocation(
            capturedAt: start.addingTimeInterval(1),
            latitude: 39.95300
        )
        await model.handleLocations([first])
        XCTAssertNotNil(model.custodyErrorMessage)
        XCTAssertFalse(model.captureHardwareActive)

        await model.handleCaptureTick()
        XCTAssertNotNil(
            model.custodyErrorMessage,
            "a queued timer callback cannot report the pending fix as recovered"
        )
        XCTAssertFalse(model.captureHardwareActive)
        XCTAssertEqual(deliveredFixes, 0)

        model.retryCustodyOperation()
        try await waitForModel {
            model.custodyErrorMessage == nil && model.captureHardwareActive
        }
        let evidence = try await runtime.recoveryEvidence(ownerID: user.id)
        XCTAssertEqual(evidence?.samples.count, 1)
        XCTAssertEqual(evidence?.samples.first?.latitude, first.coordinate.latitude)
        XCTAssertEqual(deliveredFixes, 1)
        XCTAssertEqual(model.captureHardwareStartCount, 2)
        model.stopHardware()
    }

    @MainActor
    func testMOBILE_TRUTHSSection9_1OverlappingLocationCallbacksWaitForExplicitCaptureRetry() async throws {
        let user = fixtureUser(id: "capture-overlap-owner", wallet: "capture-overlap-wallet")
        let rideID = "a2720000-0000-4000-8000-00000000000a"
        let clock = GateClock(wall: start, monotonic: 100)
        let fault = GateBlockingFirstFixPublishFault()
        let custody = makeCustody(
            at: rootURL,
            beforeEventPublish: { kind, sequence in
                try fault.beforePublish(kind: kind, sequence: sequence)
            }
        )
        let runtime = makeRuntime(
            custody: custody,
            queue: GateUploadQueue(),
            clock: clock,
            ids: GateIDSequence([rideID])
        )
        _ = try await runtime.activate(user: user)
        let model = RecordingModel(
            user: user,
            runtime: runtime,
            authorizationStatus: .authorizedWhenInUse,
            locationHardwareEnabled: false
        )
        var enteredCallbacks: [Double] = []
        var deliveredLatitudes: [Double] = []
        model.onCaptureCallback = { enteredCallbacks.append($0.coordinate.latitude) }
        model.onFix = { deliveredLatitudes.append($0.coordinate.latitude) }
        await model.handleAuthorizationChange(.authorizedWhenInUse)
        try await waitForModel {
            model.state == .recording && model.captureHardwareActive
        }

        let first = fixtureLocation(
            capturedAt: start.addingTimeInterval(1),
            latitude: 39.96100
        )
        let second = fixtureLocation(
            capturedAt: start.addingTimeInterval(2),
            latitude: 39.96104
        )
        let firstCallback = Task { @MainActor in
            await model.handleLocations([first])
        }
        let didBlock = await Task.detached {
            fault.waitUntilBlocked(timeout: 2)
        }.value
        XCTAssertTrue(didBlock)

        let secondCallback = Task { @MainActor in
            await model.handleLocations([second])
        }
        try await waitForModel { enteredCallbacks.count == 2 }
        fault.releaseFirstFailure()
        await firstCallback.value
        await secondCallback.value

        XCTAssertNotNil(model.custodyErrorMessage)
        XCTAssertFalse(model.captureHardwareActive)
        XCTAssertTrue(deliveredLatitudes.isEmpty)
        let beforeRetry = try await custody.persisted(
            owner: RecordingOwner(user: user),
            rideID: rideID
        )
        XCTAssertEqual(
            beforeRetry.events.map(\.kind),
            [.start],
            "the later callback cannot drain or publish either fix before explicit Retry"
        )

        model.retryCustodyOperation()
        try await waitForModel {
            model.custodyErrorMessage == nil &&
                model.captureHardwareActive &&
                deliveredLatitudes.count == 2
        }
        let afterRetry = try await custody.persisted(
            owner: RecordingOwner(user: user),
            rideID: rideID
        )
        XCTAssertEqual(
            afterRetry.events.compactMap(\.fix).map { $0.gps.latitude },
            [first.coordinate.latitude, second.coordinate.latitude]
        )
        XCTAssertEqual(
            deliveredLatitudes,
            [first.coordinate.latitude, second.coordinate.latitude]
        )
        XCTAssertEqual(model.captureHardwareStartCount, 2)
        model.stopHardware()
    }

    @MainActor
    func testMOBILE_TRUTHSSection6PauseRetryReusesPostRenameCommittedBoundary() async throws {
        let user = fixtureUser(id: "pending-pause-owner", wallet: "pending-pause-wallet")
        let rideID = "a2550000-0000-4000-8000-00000000000a"
        let clock = GateClock(wall: start, monotonic: 100)
        let fault = GateAfterMoveDirectorySyncFault()
        let custody = makeCustody(
            at: rootURL,
            beforeDirectorySync: { directory in
                try fault.beforeSync(directory: directory)
            }
        )
        let runtime = makeRuntime(
            custody: custody,
            queue: GateUploadQueue(),
            clock: clock,
            ids: GateIDSequence([rideID])
        )
        _ = try await runtime.activate(user: user)
        _ = try await runtime.start(user: user, at: start)
        let model = RecordingModel(
            user: user,
            runtime: runtime,
            authorizationStatus: .authorizedWhenInUse,
            locationHardwareEnabled: false,
            wallNow: { clock.wallValue },
            monotonicNow: { clock.monotonicValue }
        )

        clock.set(wall: start.addingTimeInterval(2), monotonic: 102)
        fault.arm()
        model.pause()
        try await waitForModel {
            model.controlTransitionInFlight == nil && model.custodyErrorMessage != nil
        }
        clock.set(wall: start.addingTimeInterval(999), monotonic: 1_099)
        model.retryCustodyOperation()
        try await waitForModel {
            model.state == .manuallyPaused && model.custodyErrorMessage == nil
        }

        let persisted = try await custody.persisted(
            owner: RecordingOwner(user: user),
            rideID: rideID
        )
        let pauses = persisted.events.filter { $0.kind == .manualPause }
        XCTAssertEqual(pauses.count, 1)
        XCTAssertEqual(pauses.first?.monotonicOffsetS, 2)
        XCTAssertEqual(pauses.first?.stateAtBoundary, .recording)
    }

    @MainActor
    func testMOBILE_TRUTHSSection6ResumeRetryReusesPostRenameCommittedBoundary() async throws {
        let user = fixtureUser(id: "pending-resume-owner", wallet: "pending-resume-wallet")
        let rideID = "a2560000-0000-4000-8000-00000000000a"
        let clock = GateClock(wall: start, monotonic: 100)
        let fault = GateAfterMoveDirectorySyncFault()
        let custody = makeCustody(
            at: rootURL,
            beforeDirectorySync: { directory in
                try fault.beforeSync(directory: directory)
            }
        )
        let runtime = makeRuntime(
            custody: custody,
            queue: GateUploadQueue(),
            clock: clock,
            ids: GateIDSequence([rideID])
        )
        _ = try await runtime.activate(user: user)
        _ = try await runtime.start(user: user, at: start)
        clock.set(wall: start.addingTimeInterval(1), monotonic: 101)
        _ = try await runtime.manualPause(at: clock.wallValue)
        let model = RecordingModel(
            user: user,
            runtime: runtime,
            authorizationStatus: .authorizedWhenInUse,
            locationHardwareEnabled: false,
            wallNow: { clock.wallValue },
            monotonicNow: { clock.monotonicValue }
        )

        clock.set(wall: start.addingTimeInterval(2), monotonic: 102)
        fault.arm()
        model.resume()
        try await waitForModel {
            model.controlTransitionInFlight == nil && model.custodyErrorMessage != nil
        }
        clock.set(wall: start.addingTimeInterval(999), monotonic: 1_099)
        model.retryCustodyOperation()
        try await waitForModel {
            model.state == .recording && model.custodyErrorMessage == nil
        }

        let persisted = try await custody.persisted(
            owner: RecordingOwner(user: user),
            rideID: rideID
        )
        let resumes = persisted.events.filter { $0.kind == .manualResume }
        XCTAssertEqual(resumes.count, 1)
        XCTAssertEqual(resumes.first?.monotonicOffsetS, 2)
        XCTAssertEqual(resumes.first?.stateAtBoundary, .manuallyPaused)
    }

    func testMOBILE_TRUTHSSection6EndRetryReusesOriginalStopAndFinalizesOnce() async throws {
        let user = fixtureUser(id: "pending-stop-owner", wallet: "pending-stop-wallet")
        let rideID = "a2570000-0000-4000-8000-00000000000a"
        let clock = GateClock(wall: start, monotonic: 100)
        let queue = GateUploadQueue()
        let fault = GateAfterMoveDirectorySyncFault()
        let custody = makeCustody(
            at: rootURL,
            beforeDirectorySync: { directory in
                try fault.beforeSync(directory: directory)
            }
        )
        let runtime = makeRuntime(
            custody: custody,
            queue: queue,
            clock: clock,
            ids: GateIDSequence([rideID])
        )
        _ = try await runtime.activate(user: user)
        _ = try await runtime.start(user: user, at: start)
        _ = try await ingestEligibleRide(runtime: runtime, clock: clock)

        let originalStop = start.addingTimeInterval(40)
        clock.set(wall: originalStop, monotonic: 140)
        fault.arm()
        do {
            _ = try await runtime.stop(at: originalStop)
            XCTFail("the first End must surface the injected post-rename sync failure")
        } catch GateTestError.injectedFailure {}

        clock.set(wall: start.addingTimeInterval(999), monotonic: 1_099)
        let finalized = try await runtime.stop(at: clock.wallValue)
        let persisted = try await custody.persisted(
            owner: RecordingOwner(user: user),
            rideID: rideID
        )
        let stops = persisted.events.filter { $0.kind == .stop }
        XCTAssertEqual(stops.count, 1)
        XCTAssertEqual(stops.first?.occurredAt, originalStop)
        XCTAssertEqual(stops.first?.monotonicOffsetS, 40)
        XCTAssertEqual(persisted.events.filter { $0.kind == .finalized }.count, 1)
        XCTAssertEqual(persisted.events.filter { $0.kind == .handedOff }.count, 1)
        let finalizedDuration = try XCTUnwrap(
            persisted.finalArtifact?.localSummary.durationS
        )
        XCTAssertEqual(finalizedDuration, 40, accuracy: 0.001)
        let calls = await queue.callSnapshot()
        XCTAssertEqual(calls.count, 1)
        XCTAssertEqual(calls.first?.jobID, rideID)
        XCTAssertEqual(calls.first?.sourceBytes, finalized.gpxBytes)
    }

    @MainActor
    func testMOBILE_TRUTHSSection9_1DiscardPendingStopClearsOnlyAfterDurableDelete() async throws {
        try await exerciseDiscardAfterPendingMarker(
            target: .stop,
            ownerID: "discard-stop-owner",
            ownerWallet: "discard-stop-wallet",
            rideID: "a2600000-0000-4000-8000-00000000000a",
            nextRideID: "a2610000-0000-4000-8000-00000000000a"
        )
    }

    @MainActor
    func testMOBILE_TRUTHSSections9_1And11FailedPreRemoveDiscardCannotBeSupersededBySave() async throws {
        let user = fixtureUser(id: "discard-save-owner", wallet: "discard-save-wallet")
        let rideID = "a2760000-0000-4000-8000-00000000000a"
        let clock = GateClock(wall: start, monotonic: 100)
        let queue = GateUploadQueue()
        let removeFault = GateFailFirstDiscardRemoveFault()
        let custody = makeCustody(
            at: rootURL,
            beforeDiscardRemove: { directory in
                try removeFault.beforeRemove(directory: directory)
            }
        )
        let runtime = makeRuntime(
            custody: custody,
            queue: queue,
            clock: clock,
            ids: GateIDSequence([rideID])
        )
        _ = try await runtime.activate(user: user)
        _ = try await runtime.start(user: user, at: start)
        clock.set(wall: start.addingTimeInterval(1), monotonic: 101)
        _ = try await runtime.ingest(
            fixtureFix(capturedAt: clock.wallValue, latitude: 39.96500),
            wallNow: clock.wallValue
        )
        _ = try await runtime.activate(user: nil)

        let session = AppSession(
            rideUploads: GateAppSessionUploadRuntime(),
            rideRecordings: runtime,
            accountDeletionCapabilityStore: SessionDeletionCapabilityStore(capability: nil)
        )
        session.phase = .signedIn(user)
        await session.refreshRideUploads()
        let recovery = try XCTUnwrap(session.pendingInterruptedRide)

        removeFault.arm()
        do {
            try await session.discardInterruptedRide(recovery)
            XCTFail("the injected pre-remove failure must retain the destructive intent")
        } catch GateTestError.injectedFailure {}
        XCTAssertEqual(session.pendingInterruptedRide, recovery)
        XCTAssertEqual(
            session.interruptedRideActionIntent,
            .discard,
            "the production session must keep the confirmed Discard intent"
        )

        var saveRejected = false
        do {
            try await session.saveInterruptedRide(recovery)
        } catch {
            saveRejected = true
        }
        XCTAssertTrue(
            saveRejected,
            "Save cannot supersede a confirmed Discard whose removal is unavailable"
        )
        let afterSaveAttempt = try await custody.persisted(
            owner: RecordingOwner(user: user),
            rideID: rideID
        )
        XCTAssertNil(afterSaveAttempt.finalArtifact)
        XCTAssertFalse(afterSaveAttempt.isHandedOff)
        let queueCalls = await queue.callSnapshot()
        XCTAssertTrue(queueCalls.isEmpty)
        let localSaved = try await runtime.localSavedRides(user: user)
        XCTAssertTrue(localSaved.isEmpty)

        try await session.discardInterruptedRide(recovery)
        XCTAssertNil(session.pendingInterruptedRide)
        XCTAssertNil(session.interruptedRideActionIntent)
        XCTAssertEqual(removeFault.failureCount(), 1)
        var deleted = false
        do {
            _ = try await custody.persisted(
                owner: RecordingOwner(user: user),
                rideID: rideID
            )
        } catch {
            deleted = true
        }
        XCTAssertTrue(deleted)
        let later = try await runtime.activate(user: user)
        XCTAssertNil(later, "activation cannot later delete a ride that was reported Saved")
    }

    func testMOBILE_TRUTHSSection11FailedDiscardRecoveryPolicyIsRetryDiscardOnly() {
        let policy = InterruptedRideRecoveryActionPolicy(
            discardIntentPending: false,
            retryAction: .discard
        )
        XCTAssertFalse(
            policy.allowsSave,
            "Cancel after a failed confirmed Discard cannot expose Save again"
        )
        XCTAssertEqual(policy.retryAction, .discard)
        XCTAssertFalse(
            InterruptedRideRecoveryActionPolicy(
                discardIntentPending: true,
                retryAction: nil
            ).allowsSave,
            "a reconstructed production view must honor AppSession's destructive intent"
        )
    }

    @MainActor
    func testMOBILE_TRUTHSSection9_1DiscardPendingFinalizedClearsOnlyAfterDurableDelete() async throws {
        try await exerciseDiscardAfterPendingMarker(
            target: .finalized,
            ownerID: "discard-final-owner",
            ownerWallet: "discard-final-wallet",
            rideID: "a2620000-0000-4000-8000-00000000000a",
            nextRideID: "a2630000-0000-4000-8000-00000000000a"
        )
    }

    @MainActor
    func testMOBILE_TRUTHSSection9_1DiscardRetriesRemoveBeforeParentFsyncAmbiguity() async throws {
        let user = fixtureUser(id: "discard-sync-owner", wallet: "discard-sync-wallet")
        let rideID = "a2640000-0000-4000-8000-00000000000a"
        let nextRideID = "a2650000-0000-4000-8000-00000000000a"
        let clock = GateClock(wall: start, monotonic: 100)
        let deleteFault = GateNextParentDirectorySyncFault()
        let custody = makeCustody(
            at: rootURL,
            beforeDirectorySync: { directory in
                try deleteFault.beforeSync(directory: directory)
            }
        )
        let runtime = makeRuntime(
            custody: custody,
            queue: GateUploadQueue(),
            clock: clock,
            ids: GateIDSequence([rideID, nextRideID])
        )
        _ = try await runtime.activate(user: user)
        _ = try await runtime.start(user: user, at: start)
        clock.set(wall: start.addingTimeInterval(1), monotonic: 101)
        _ = try await runtime.ingest(
            fixtureFix(capturedAt: clock.wallValue, latitude: 39.9540),
            wallNow: clock.wallValue
        )
        _ = try await runtime.activate(user: nil)

        let session = AppSession(
            rideUploads: GateAppSessionUploadRuntime(),
            rideRecordings: runtime,
            accountDeletionCapabilityStore: SessionDeletionCapabilityStore(capability: nil)
        )
        session.phase = .signedIn(user)
        await session.refreshRideUploads()
        let recovery = try XCTUnwrap(session.pendingInterruptedRide)

        deleteFault.arm()
        do {
            try await session.discardInterruptedRide(recovery)
            XCTFail("remove-before-parent-fsync ambiguity must remain retryable")
        } catch GateTestError.injectedFailure {}
        XCTAssertEqual(session.pendingInterruptedRide, recovery)

        try await session.discardInterruptedRide(recovery)
        XCTAssertNil(session.pendingInterruptedRide)
        XCTAssertEqual(deleteFault.failureCount(), 1)

        _ = try await runtime.start(user: user, at: start.addingTimeInterval(10))
        clock.set(wall: start.addingTimeInterval(11), monotonic: 111)
        _ = try await runtime.ingest(
            fixtureFix(capturedAt: clock.wallValue, latitude: 39.9550),
            wallNow: clock.wallValue
        )
        let next = try await custody.persisted(
            owner: RecordingOwner(user: user),
            rideID: nextRideID
        )
        XCTAssertEqual(next.events.map(\.kind), [.start, .fix])
    }

    func testMOBILE_TRUTHSSection9_1PendingDiscardResumesAfterLogoutForExactOwner() async throws {
        let user = fixtureUser(id: "discard-resume-owner", wallet: "discard-resume-wallet")
        let rideID = "a2680000-0000-4000-8000-00000000000a"
        let nextRideID = "a2690000-0000-4000-8000-00000000000a"
        let clock = GateClock(wall: start, monotonic: 100)
        let deleteFault = GateNextParentDirectorySyncFault()
        let custody = makeCustody(
            at: rootURL,
            beforeDirectorySync: { directory in
                try deleteFault.beforeSync(directory: directory)
            }
        )
        let runtime = makeRuntime(
            custody: custody,
            queue: GateUploadQueue(),
            clock: clock,
            ids: GateIDSequence([rideID, nextRideID])
        )
        _ = try await runtime.activate(user: user)
        _ = try await runtime.start(user: user, at: start)
        clock.set(wall: start.addingTimeInterval(1), monotonic: 101)
        _ = try await runtime.ingest(
            fixtureFix(capturedAt: clock.wallValue, latitude: 39.9570),
            wallNow: clock.wallValue
        )
        _ = try await runtime.activate(user: nil)
        let selectedRecovery = try await runtime.activate(user: user)
        let recovery = try XCTUnwrap(selectedRecovery)

        deleteFault.arm()
        do {
            try await runtime.discard(recovery)
            XCTFail("the first parent-directory sync must remain unavailable")
        } catch GateTestError.injectedFailure {}

        do {
            _ = try await runtime.activate(user: nil)
            XCTFail("logout cannot report a clean activation while deletion is pending")
        } catch {}

        let selected = try await runtime.activate(user: user)
        XCTAssertNil(selected)
        XCTAssertEqual(deleteFault.failureCount(), 1)

        _ = try await runtime.start(user: user, at: start.addingTimeInterval(10))
        clock.set(wall: start.addingTimeInterval(11), monotonic: 111)
        _ = try await runtime.ingest(
            fixtureFix(capturedAt: clock.wallValue, latitude: 39.9580),
            wallNow: clock.wallValue
        )
        let next = try await custody.persisted(
            owner: RecordingOwner(user: user),
            rideID: nextRideID
        )
        XCTAssertEqual(next.events.map(\.kind), [.start, .fix])
    }

    func testMOBILE_TRUTHSSection9_1PendingDiscardRejectsOtherOwnerAndRetainsRetryAfterAnotherFsyncFailure() async throws {
        let owner = fixtureUser(id: "discard-private-owner", wallet: "discard-private-wallet")
        let other = fixtureUser(id: "discard-private-other", wallet: "discard-private-other-wallet")
        let rideID = "a2700000-0000-4000-8000-00000000000a"
        let nextRideID = "a2710000-0000-4000-8000-00000000000a"
        let clock = GateClock(wall: start, monotonic: 100)
        let deleteFault = GateNextParentDirectorySyncFault()
        let custody = makeCustody(
            at: rootURL,
            beforeDirectorySync: { directory in
                try deleteFault.beforeSync(directory: directory)
            }
        )
        let runtime = makeRuntime(
            custody: custody,
            queue: GateUploadQueue(),
            clock: clock,
            ids: GateIDSequence([rideID, nextRideID])
        )
        _ = try await runtime.activate(user: owner)
        _ = try await runtime.start(user: owner, at: start)
        clock.set(wall: start.addingTimeInterval(1), monotonic: 101)
        _ = try await runtime.ingest(
            fixtureFix(capturedAt: clock.wallValue, latitude: 39.9590),
            wallNow: clock.wallValue
        )
        _ = try await runtime.activate(user: nil)
        let selectedRecovery = try await runtime.activate(user: owner)
        let recovery = try XCTUnwrap(selectedRecovery)

        deleteFault.arm()
        do {
            try await runtime.discard(recovery)
            XCTFail("the first parent-directory sync must remain unavailable")
        } catch GateTestError.injectedFailure {}

        do {
            _ = try await runtime.activate(user: other)
            XCTFail("another owner cannot resume or clear this deletion intent")
        } catch {}
        let otherRecovery = try? await runtime.recovery(ownerID: other.id)
        XCTAssertNil(otherRecovery)
        XCTAssertEqual(deleteFault.failureCount(), 1)

        deleteFault.arm()
        do {
            _ = try await runtime.activate(user: owner)
            XCTFail("a repeated parent sync failure must preserve the exact retry intent")
        } catch GateTestError.injectedFailure {}
        XCTAssertEqual(deleteFault.failureCount(), 2)

        let selected = try await runtime.activate(user: owner)
        XCTAssertNil(selected)
        _ = try await runtime.start(user: owner, at: start.addingTimeInterval(10))
        clock.set(wall: start.addingTimeInterval(11), monotonic: 111)
        _ = try await runtime.ingest(
            fixtureFix(capturedAt: clock.wallValue, latitude: 39.9600),
            wallNow: clock.wallValue
        )
        let next = try await custody.persisted(
            owner: RecordingOwner(user: owner),
            rideID: nextRideID
        )
        XCTAssertEqual(next.events.map(\.kind), [.start, .fix])
    }

    @MainActor
    func testMOBILE_TRUTHSSections7And11PostEnqueueHandedOffFaultIsCommittedSave() async throws {
        let user = fixtureUser(id: "handoff-save-owner", wallet: "handoff-save-wallet")
        let rideID = "a2660000-0000-4000-8000-00000000000a"
        let clock = GateClock(wall: start, monotonic: 100)
        let queue = GateUploadQueue()
        let markerFault = GateEventKindAfterMoveSyncFault(target: .handedOff)
        let custody = makeCustody(
            at: rootURL,
            beforeEventPublish: { kind, sequence in
                markerFault.beforePublish(kind: kind, sequence: sequence)
            },
            beforeDirectorySync: { directory in
                try markerFault.beforeSync(directory: directory)
            }
        )
        let runtime = makeRuntime(
            custody: custody,
            queue: queue,
            clock: clock,
            ids: GateIDSequence([rideID])
        )
        _ = try await runtime.activate(user: user)
        _ = try await runtime.start(user: user, at: start)
        _ = try await ingestEligibleRide(runtime: runtime, clock: clock)
        _ = try await runtime.activate(user: nil)

        let session = AppSession(
            rideUploads: GateAppSessionUploadRuntime(),
            rideRecordings: runtime,
            accountDeletionCapabilityStore: SessionDeletionCapabilityStore(capability: nil)
        )
        session.phase = .signedIn(user)
        await session.refreshRideUploads()
        let recovery = try XCTUnwrap(session.pendingInterruptedRide)

        markerFault.arm()
        try await session.saveInterruptedRide(recovery)
        XCTAssertNil(session.pendingInterruptedRide)
        let callsAfterSave = await queue.callSnapshot()
        XCTAssertEqual(callsAfterSave.count, 1)
        XCTAssertEqual(callsAfterSave.first?.jobID, rideID)

        do {
            try await runtime.discard(recovery)
            XCTFail("a queued Save & Upload cannot expose a destructive custody-only Discard")
        } catch {}

        let selected = try await runtime.activate(user: user)
        XCTAssertNil(selected)
        let persisted = try await custody.persisted(
            owner: RecordingOwner(user: user),
            rideID: rideID
        )
        let callsAfterDrain = await queue.callSnapshot()
        XCTAssertEqual(callsAfterDrain.count, 1)
        XCTAssertEqual(persisted.events.filter { $0.kind == .finalized }.count, 1)
        XCTAssertEqual(persisted.events.filter { $0.kind == .handedOff }.count, 1)
        XCTAssertTrue(persisted.isHandedOff)
    }

    func testMOBILE_TRUTHSSection7FinalizedPostRenameFaultRetriesExactMarkerBeforeOneHandoff() async throws {
        let user = fixtureUser(id: "finalized-sync-owner", wallet: "finalized-sync-wallet")
        let rideID = "a2670000-0000-4000-8000-00000000000a"
        let clock = GateClock(wall: start, monotonic: 100)
        let queue = GateUploadQueue()
        let markerFault = GateEventKindAfterMoveSyncFault(target: .finalized)
        let custody = makeCustody(
            at: rootURL,
            beforeEventPublish: { kind, sequence in
                markerFault.beforePublish(kind: kind, sequence: sequence)
            },
            beforeDirectorySync: { directory in
                try markerFault.beforeSync(directory: directory)
            }
        )
        let runtime = makeRuntime(
            custody: custody,
            queue: queue,
            clock: clock,
            ids: GateIDSequence([rideID])
        )
        _ = try await runtime.activate(user: user)
        _ = try await runtime.start(user: user, at: start)
        _ = try await ingestEligibleRide(runtime: runtime, clock: clock)
        clock.set(wall: start.addingTimeInterval(40), monotonic: 140)

        markerFault.arm()
        do {
            _ = try await runtime.stop(at: clock.wallValue)
            XCTFail("the finalized marker durability fault must remain visible before enqueue")
        } catch GateTestError.injectedFailure {}
        let callsBeforeRetry = await queue.callSnapshot()
        XCTAssertTrue(callsBeforeRetry.isEmpty)

        clock.set(wall: start.addingTimeInterval(999), monotonic: 1_099)
        let finalized = try await runtime.stop(at: clock.wallValue)
        let callsAfterRetry = await queue.callSnapshot()
        let persisted = try await custody.persisted(
            owner: RecordingOwner(user: user),
            rideID: rideID
        )
        XCTAssertEqual(callsAfterRetry.count, 1)
        XCTAssertEqual(callsAfterRetry.first?.sourceBytes, finalized.gpxBytes)
        XCTAssertEqual(persisted.events.filter { $0.kind == .stop }.count, 1)
        XCTAssertEqual(persisted.events.filter { $0.kind == .finalized }.count, 1)
        XCTAssertEqual(persisted.events.filter { $0.kind == .handedOff }.count, 1)
    }

    func testMOBILE_TRUTHSSections9_1And11PermissionLossSuspendsForSameOwnerRecovery() async throws {
        XCTAssertTrue(
            RecordingAuthorizationCustodyPolicy.requiresSuspension(
                status: .denied,
                state: .recording
            )
        )
        XCTAssertTrue(
            RecordingAuthorizationCustodyPolicy.requiresSuspension(
                status: .restricted,
                state: .manuallyPaused
            )
        )
        XCTAssertFalse(
            RecordingAuthorizationCustodyPolicy.requiresSuspension(
                status: .authorizedWhenInUse,
                state: .recording
            )
        )
        XCTAssertFalse(
            RecordingAuthorizationCustodyPolicy.requiresSuspension(
                status: .denied,
                state: .idle
            )
        )

        let user = fixtureUser(id: "permission-owner", wallet: "permission-wallet")
        let rideID = "a2600000-0000-4000-8000-00000000000a"
        let nextRideID = "a2600000-0000-4000-8000-00000000000b"
        let clock = GateClock(wall: start, monotonic: 100)
        let custody = makeCustody(at: rootURL)
        let runtime = makeRuntime(
            custody: custody,
            queue: GateUploadQueue(),
            clock: clock,
            ids: GateIDSequence([rideID, nextRideID])
        )
        _ = try await runtime.activate(user: user)
        _ = try await runtime.start(user: user, at: start)
        clock.set(wall: start.addingTimeInterval(1), monotonic: 101)
        _ = try await runtime.ingest(
            fixtureFix(capturedAt: clock.wallValue, latitude: 39.9500),
            wallNow: clock.wallValue
        )

        clock.set(wall: start.addingTimeInterval(2), monotonic: 102)
        try await runtime.suspendActive(at: clock.wallValue)
        let selected = try await runtime.recovery(ownerID: user.id)
        let recovery = try XCTUnwrap(selected)
        XCTAssertEqual(recovery.id, rideID)
        XCTAssertEqual(recovery.sampleCount, 1)

        let persisted = try await custody.persisted(
            owner: RecordingOwner(user: user),
            rideID: rideID
        )
        XCTAssertEqual(persisted.events.map(\.kind), [.start, .fix, .suspend])

        try await runtime.discard(recovery)
        let restarted = try await runtime.start(
            user: user,
            at: start.addingTimeInterval(3)
        )
        XCTAssertEqual(restarted.state, .recording)
        XCTAssertEqual(restarted.sampleCount, 0)
    }

    @MainActor
    func testMOBILE_TRUTHSSections9_1And11AuthorizationLossRequiresOneWayRecoveryExit() async throws {
        let user = fixtureUser(id: "auth-exit-owner", wallet: "auth-exit-wallet")
        let rideID = "a2610000-0000-4000-8000-00000000000a"
        let clock = GateClock(wall: start, monotonic: 100)
        let custody = makeCustody(at: rootURL)
        let runtime = makeRuntime(
            custody: custody,
            queue: GateUploadQueue(),
            clock: clock,
            ids: GateIDSequence([rideID])
        )
        _ = try await runtime.activate(user: user)
        let model = RecordingModel(
            user: user,
            runtime: runtime,
            authorizationStatus: .authorizedWhenInUse,
            locationHardwareEnabled: false
        )

        await model.handleAuthorizationChange(.authorizedWhenInUse)
        for _ in 0..<200 where model.state != .recording {
            try await Task.sleep(for: .milliseconds(10))
        }
        XCTAssertEqual(model.state, .recording)

        await model.handleAuthorizationChange(.denied)
        XCTAssertTrue(model.recoveryExitRequired)
        XCTAssertEqual(model.controlMode, .unavailable)
        await model.handleAuthorizationChange(.authorizedWhenInUse)
        XCTAssertTrue(model.recoveryExitRequired)
        XCTAssertEqual(model.controlMode, .unavailable)

        let recordings = GateFailOnceThenLiveRecordingRuntime(runtime: runtime)
        let session = AppSession(
            rideUploads: GateAppSessionUploadRuntime(),
            rideRecordings: recordings,
            accountDeletionCapabilityStore: SessionDeletionCapabilityStore(capability: nil)
        )
        session.phase = .signedIn(user)
        var dismissCalls = 0
        do {
            try await session.suspendRecordingAndRefresh(
                {
                    try await model.suspendAndLeave()
                },
                onSuccess: {
                    dismissCalls += 1
                }
            )
            XCTFail("a failed recovery refresh must retain the completed suspend stage")
        } catch {
            // The durable suspend remains complete; only refresh is retried.
        }
        XCTAssertTrue(model.custodySuspensionCompleted)
        XCTAssertEqual(dismissCalls, 0)

        try await session.suspendRecordingAndRefresh(
            {
                try await model.suspendAndLeave()
            },
            onSuccess: {
                dismissCalls += 1
            }
        )
        XCTAssertEqual(session.pendingInterruptedRide?.id, rideID)
        XCTAssertEqual(dismissCalls, 1)
        let persisted = try await custody.persisted(
            owner: RecordingOwner(user: user),
            rideID: rideID
        )
        XCTAssertEqual(persisted.events.filter { $0.kind == .suspend }.count, 1)
    }

    @MainActor
    func testMOBILE_TRUTHSSections9_1And11AuthorizationLossDuringStartStillExitsToRecovery() async throws {
        let user = fixtureUser(id: "auth-start-owner", wallet: "auth-start-wallet")
        let rideID = "a2620000-0000-4000-8000-00000000000a"
        let clock = GateClock(wall: start, monotonic: 100)
        let barrier = GateEventPublishBarrier(blocking: .start)
        let runtime = makeRuntime(
            custody: makeCustody(
                at: rootURL,
                beforeEventPublish: { kind, sequence in
                    try barrier.beforePublish(kind: kind, sequence: sequence)
                }
            ),
            queue: GateUploadQueue(),
            clock: clock,
            ids: GateIDSequence([rideID])
        )
        _ = try await runtime.activate(user: user)
        let model = RecordingModel(
            user: user,
            runtime: runtime,
            authorizationStatus: .authorizedWhenInUse,
            locationHardwareEnabled: false
        )

        await model.handleAuthorizationChange(.authorizedWhenInUse)
        let didBlock = await Task.detached {
            barrier.waitUntilBlocked(timeout: 2)
        }.value
        XCTAssertTrue(didBlock)

        let denied = Task { @MainActor in
            await model.handleAuthorizationChange(.denied)
        }
        await Task.yield()
        await model.handleAuthorizationChange(.authorizedWhenInUse)
        barrier.release()
        await denied.value

        XCTAssertTrue(model.recoveryExitRequired)
        XCTAssertEqual(model.controlMode, .unavailable)
        let selected = try await runtime.recovery(ownerID: user.id)
        XCTAssertEqual(selected?.id, rideID)
    }

    func testMOBILE_TRUTHSSections9_1And11SameIDDifferentWalletCannotRecoverRide() async throws {
        let original = fixtureUser(id: "stable-rider-id", wallet: "original-wallet")
        let mismatched = fixtureUser(id: original.id, wallet: "different-wallet")
        let rideID = "a3000000-0000-4000-8000-00000000000a"
        let mismatchedRideID = "a3000000-0000-4000-8000-00000000000b"
        let clock = GateClock(wall: start, monotonic: 100)
        let runtime = makeRuntime(
            custody: makeCustody(at: rootURL),
            queue: GateUploadQueue(),
            clock: clock,
            ids: GateIDSequence([rideID])
        )
        _ = try await runtime.activate(user: original)
        _ = try await runtime.start(user: original, at: start)
        clock.set(wall: start.addingTimeInterval(1), monotonic: 101)
        _ = try await runtime.ingest(
            fixtureFix(capturedAt: clock.wallValue, latitude: 39.95),
            wallNow: clock.wallValue
        )
        _ = try await runtime.activate(user: nil)

        let mismatchedRuntime = makeRuntime(
            custody: makeCustody(at: rootURL),
            queue: GateUploadQueue(),
            clock: GateClock(wall: start.addingTimeInterval(2), monotonic: 1),
            ids: GateIDSequence([mismatchedRideID])
        )
        let mismatchedRecovery = try await mismatchedRuntime.activate(user: mismatched)
        XCTAssertNil(mismatchedRecovery)
        _ = try await mismatchedRuntime.start(user: mismatched, at: start.addingTimeInterval(2))
        _ = try await mismatchedRuntime.activate(user: nil)

        let rightfulRuntime = makeRuntime(
            custody: makeCustody(at: rootURL),
            queue: GateUploadQueue(),
            clock: GateClock(wall: start.addingTimeInterval(3), monotonic: 1),
            ids: GateIDSequence([])
        )
        let selectedRightfulRecovery = try await rightfulRuntime.activate(user: original)
        let rightfulRecovery = try XCTUnwrap(selectedRightfulRecovery)
        XCTAssertEqual(rightfulRecovery.id, rideID)
    }

    func testMOBILE_TRUTHSSections6And7OverlappingIngestAndEndSerializeOneFinalRide() async throws {
        let user = fixtureUser(id: "overlap-owner", wallet: "overlap-wallet")
        let rideID = "a4000000-0000-4000-8000-00000000000a"
        let clock = GateClock(wall: start, monotonic: 100)
        let barrier = GateEventPublishBarrier(blocking: .fix)
        let custody = makeCustody(
            at: rootURL,
            beforeEventPublish: { kind, sequence in
                try barrier.beforePublish(kind: kind, sequence: sequence)
            }
        )
        let runtime = makeRuntime(
            custody: custody,
            queue: GateUploadQueue(),
            clock: clock,
            ids: GateIDSequence([rideID])
        )
        _ = try await runtime.activate(user: user)
        _ = try await runtime.start(user: user, at: start)

        let fixTime = start.addingTimeInterval(1)
        clock.set(wall: fixTime, monotonic: 101)
        let ingestTask = Task {
            try await runtime.ingest(
                fixtureFix(capturedAt: fixTime, latitude: 39.95123),
                wallNow: fixTime
            )
        }
        XCTAssertTrue(
            barrier.waitUntilBlocked(timeout: 2),
            "the retained fixture must overlap end with a custody append"
        )

        let endTime = start.addingTimeInterval(2)
        clock.set(wall: endTime, monotonic: 102)
        let stopTask = Task { try await runtime.stop(at: endTime) }
        await Task.yield()
        barrier.release()

        let ingestResult = try await ingestTask.value
        let finalized = try await stopTask.value
        let persisted = try await custody.persisted(
            owner: RecordingOwner(user: user),
            rideID: rideID
        )
        XCTAssertEqual(ingestResult.0, .recorded)
        XCTAssertEqual(
            persisted.events.map(\.kind),
            [.start, .fix, .stop, .finalized]
        )
        XCTAssertEqual(persisted.events.map(\.sequence), [1, 2, 3, 4])
        XCTAssertEqual(persisted.events.filter { $0.kind == .stop }.count, 1)
        XCTAssertEqual(persisted.events.filter { $0.kind == .finalized }.count, 1)
        let xml = try XCTUnwrap(String(data: finalized.gpxBytes, encoding: .utf8))
        XCTAssertTrue(xml.contains("39.9512300"))
        XCTAssertEqual(barrier.publishedKinds(), [.start, .fix, .stop, .finalized])
    }

    func testMOBILE_TRUTHSSections6And9_1EachFixPublishesOneBoundedImmutableEvent() async throws {
        let user = fixtureUser(id: "bounded-owner", wallet: "bounded-wallet")
        let rideID = "a5000000-0000-4000-8000-00000000000a"
        let clock = GateClock(wall: start, monotonic: 100)
        let custody = makeCustody(at: rootURL)
        let runtime = makeRuntime(
            custody: custody,
            queue: GateUploadQueue(),
            clock: clock,
            ids: GateIDSequence([rideID])
        )
        _ = try await runtime.activate(user: user)
        _ = try await runtime.start(user: user, at: start)

        clock.set(wall: start.addingTimeInterval(1), monotonic: 101)
        _ = try await runtime.ingest(
            fixtureFix(capturedAt: clock.wallValue, latitude: 39.950001),
            wallNow: clock.wallValue
        )
        let manifestURL = try XCTUnwrap(
            try regularFileURLs(in: rootURL).first(where: {
                $0.lastPathComponent == "manifest.sealed"
            })
        )
        let firstFixURL = try XCTUnwrap(
            try regularFileURLs(in: rootURL).first(where: {
                $0.lastPathComponent == "00000000000000000002.sealed"
            })
        )
        let originalManifest = try Data(contentsOf: manifestURL)
        let originalFirstFix = try Data(contentsOf: firstFixURL)

        for index in 2...41 {
            let offset = TimeInterval(index)
            clock.set(wall: start.addingTimeInterval(offset), monotonic: 100 + offset)
            _ = try await runtime.ingest(
                fixtureFix(
                    capturedAt: clock.wallValue,
                    latitude: 39.950000 + Double(index) * 0.000001
                ),
                wallNow: clock.wallValue
            )
        }

        let persisted = try await custody.persisted(
            owner: RecordingOwner(user: user),
            rideID: rideID
        )
        let eventFiles = try regularFileURLs(in: rootURL)
            .filter { $0.deletingLastPathComponent().lastPathComponent == "events" }
            .sorted { $0.lastPathComponent < $1.lastPathComponent }
        let fixFileSizes = try eventFiles.dropFirst().map {
            try $0.resourceValues(forKeys: [.fileSizeKey]).fileSize ?? 0
        }
        let minimumFixSize = try XCTUnwrap(fixFileSizes.min())
        let maximumFixSize = try XCTUnwrap(fixFileSizes.max())

        XCTAssertEqual(persisted.events.count, 42)
        XCTAssertEqual(eventFiles.count, 42)
        XCTAssertEqual(persisted.events.map(\.sequence), Array(1...42).map(UInt64.init))
        XCTAssertEqual(try Data(contentsOf: manifestURL), originalManifest)
        XCTAssertEqual(try Data(contentsOf: firstFixURL), originalFirstFix)
        XCTAssertLessThanOrEqual(
            maximumFixSize - minimumFixSize,
            256,
            "one encrypted fix event stays bounded instead of rewriting growing ride history"
        )
    }

    func testMOBILE_TRUTHSSections6And11RecoverySaveAndUploadUsesExactUploadThreshold() {
        func recovery(sampleCount: Int, distanceM: Double) -> InterruptedRideRecovery {
            InterruptedRideRecovery(
                id: "a6000000-0000-4000-8000-00000000000a",
                ownerID: "eligibility-owner",
                startedAt: start,
                state: .recording,
                sampleCount: sampleCount,
                durationS: 60,
                distanceM: distanceM,
                elevationGainM: nil
            )
        }

        XCTAssertFalse(recovery(sampleCount: 0, distanceM: 0).canSaveAndUpload)
        XCTAssertFalse(recovery(sampleCount: 1, distanceM: 1_000).canSaveAndUpload)
        XCTAssertFalse(recovery(sampleCount: 29, distanceM: 1_000).canSaveAndUpload)
        XCTAssertFalse(recovery(sampleCount: 30, distanceM: 99.999).canSaveAndUpload)
        XCTAssertTrue(recovery(sampleCount: 30, distanceM: 100).canSaveAndUpload)
    }

    func testMOBILE_TRUTHSSection12InterruptedRideViewUsesExactRideVocabularyAndActions() throws {
        let testsDirectory = URL(fileURLWithPath: #filePath).deletingLastPathComponent()
        let iosDirectory = testsDirectory.deletingLastPathComponent()
        let viewURL = iosDirectory.appendingPathComponent(
            "BoulderRoller/Recording/InterruptedRideRecoveryView.swift"
        )
        let fixtureURL = iosDirectory.appendingPathComponent(
            "BoulderRoller/Debug/RecordingRecoveryRenderFixture.swift"
        )
        let feedURL = iosDirectory.appendingPathComponent(
            "BoulderRoller/Surfaces/Feed/FeedView.swift"
        )
        let viewSource = try String(contentsOf: viewURL, encoding: .utf8)
        let fixtureSource = try String(contentsOf: fixtureURL, encoding: .utf8)
        let feedSource = try String(contentsOf: feedURL, encoding: .utf8)

        let exactProductionLabels = [
            "Text(\"Unfinished Ride Found\")",
            "metric(\"Duration\"",
            "metric(\"Distance\"",
            "\"Elevation\"",
            // Below the upload floor the save action keeps its exact label
            // but loses the primary capsule (cdyum): two buttons, same
            // vocabulary.
            "recovery.canSaveAndUpload {",
            "Button(\"Save & Upload\")",
            "Button(\"Save Ride\")",
            "Button(\"Discard\", role: .destructive)",
            "confirmationDialog(\"Discard Ride?\"",
            "Text(\"This will permanently delete your ride data.\")",
            "\"Ride evidence is unavailable\"",
            "Button(\"Retry\")",
            "Button(\"Cancel\", role: .cancel)",
        ]
        for exactLabel in exactProductionLabels {
            XCTAssertTrue(
                viewSource.contains(exactLabel),
                "missing exact production-view contract: \(exactLabel)"
            )
        }
        for forbiddenRiderLabel in ["Workout", "Activity", "Save Activity", "Save Workout"] {
            XCTAssertFalse(viewSource.contains("\"\(forbiddenRiderLabel)"))
        }
        XCTAssertTrue(fixtureSource.contains("#if DEBUG"))
        XCTAssertTrue(fixtureSource.contains("-BRRecordingRecoveryRenderFixture"))
        XCTAssertTrue(fixtureSource.contains("case eligible = \"eligible\""))
        XCTAssertTrue(fixtureSource.contains("case ineligible = \"ineligible\""))
        XCTAssertTrue(fixtureSource.contains("case localSaved = \"local-saved\""))
        XCTAssertTrue(fixtureSource.contains("InterruptedRideRecoveryView("))
        XCTAssertTrue(fixtureSource.contains("eligibleRecovery"))
        XCTAssertTrue(fixtureSource.contains("sampleCount: 842"))
        XCTAssertTrue(fixtureSource.contains("distanceM: 12_874"))
        XCTAssertTrue(fixtureSource.contains("ineligibleRecovery"))
        XCTAssertTrue(fixtureSource.contains("sampleCount: 12"))
        XCTAssertTrue(fixtureSource.contains("distanceM: 64"))
        XCTAssertTrue(fixtureSource.contains("localSavedRide"))
        XCTAssertTrue(fixtureSource.contains("ownerID: rider.id"))
        XCTAssertTrue(fixtureSource.contains("ownerWallet: rider.wallet"))
        XCTAssertTrue(fixtureSource.contains("FeedView("))
        XCTAssertTrue(fixtureSource.contains("debugItems: []"))
        XCTAssertFalse(fixtureSource.contains("#else"))
        XCTAssertTrue(feedSource.contains("Text(\"Saved on this device\")"))

        let nativeRiderFacingRoots = ["Surfaces", "Recording", "Components"].map {
            iosDirectory.appendingPathComponent("BoulderRoller/\($0)", isDirectory: true)
        }
        var scannedFiles: [URL] = []
        for root in nativeRiderFacingRoots {
            let enumerator = try XCTUnwrap(
                FileManager.default.enumerator(
                    at: root,
                    includingPropertiesForKeys: [.isRegularFileKey],
                    options: [.skipsHiddenFiles]
                )
            )
            for case let file as URL in enumerator where file.pathExtension == "swift" {
                scannedFiles.append(file)
            }
        }
        XCTAssertGreaterThan(scannedFiles.count, 0)

        let forbiddenWholeWord = #"(?i)\b(workout|activity|segment)\b"#
        for file in scannedFiles {
            let source = try String(contentsOf: file, encoding: .utf8)
            let sourceWithoutComments = strippingSwiftComments(from: source)
            let stringLiterals = swiftStringLiterals(in: sourceWithoutComments)
            for literal in stringLiterals {
                XCTAssertNil(
                    literal.range(of: forbiddenWholeWord, options: .regularExpression),
                    "MOBILE_TRUTHS §12 forbidden rider noun in \(file.path): \(literal)"
                )
            }
        }
    }

    @MainActor
    func testMOBILE_TRUTHSSections8And11CustodyFailureBlocksRevealUntilRecoveryRetrySucceeds() async {
        let user = fixtureUser(id: "app-session-owner", wallet: "app-session-wallet")
        let uploads = GateAppSessionUploadRuntime()
        let recordings = GateAppSessionRecordingRuntime()
        let session = AppSession(
            rideUploads: uploads,
            rideRecordings: recordings,
            accountDeletionCapabilityStore: SessionDeletionCapabilityStore(capability: nil)
        )
        session.phase = .signedIn(user)

        await session.refreshRideUploads()
        XCTAssertNotNil(session.interruptedRideErrorMessage)
        XCTAssertNil(session.pendingInterruptedRide)
        let claimsWhileUnavailable = await uploads.claimCount()
        XCTAssertEqual(claimsWhileUnavailable, 0)

        await session.retryInterruptedRideRecovery()
        XCTAssertNil(session.interruptedRideErrorMessage)
        XCTAssertNil(session.pendingInterruptedRide)
        let claimsAfterRecovery = await uploads.claimCount()
        let recordingActivations = await recordings.activationCount()
        XCTAssertEqual(claimsAfterRecovery, 1)
        XCTAssertEqual(recordingActivations, 2)
    }

    @MainActor
    func testMOBILE_TRUTHSSections9_1And11AppSessionInstallsProductionLocalRideProjection() async {
        let user = fixtureUser(id: "app-local-owner", wallet: "app-local-wallet")
        let localRide = LocalSavedRide(
            id: "a7000000-0000-4000-8000-00000000000a",
            ownerID: user.id,
            ownerWallet: user.wallet,
            summary: LocalRideSummary(
                startedAt: start,
                distanceM: 12,
                elevationM: 2,
                durationS: 8
            ),
            fileHash: String(repeating: "a", count: 64),
            preliminaryRideHash: String(repeating: "b", count: 64),
            parserVersion: 1
        )
        let uploads = GateAppSessionUploadRuntime()
        let recordings = GateAppSessionLocalSavedRecordingRuntime(saved: [localRide])
        let session = AppSession(
            rideUploads: uploads,
            rideRecordings: recordings,
            accountDeletionCapabilityStore: SessionDeletionCapabilityStore(capability: nil)
        )
        session.phase = .signedIn(user)

        await session.refreshRideUploads()

        XCTAssertEqual(session.localSavedRides, [localRide])
        XCTAssertNil(session.pendingInterruptedRide)
        XCTAssertNil(session.interruptedRideErrorMessage)
        let loadedOwners = await recordings.loadedOwnersSnapshot()
        XCTAssertEqual(loadedOwners, [RecordingOwner(user: user)])
    }

    @MainActor
    func testMOBILE_TRUTHSSections9_1And11SuspendedExitInstallsOwnerRecoveryBeforeNextRecord() async throws {
        let user = fixtureUser(id: "exit-owner", wallet: "exit-wallet")
        let rideID = "a8000000-0000-4000-8000-00000000000a"
        let clock = GateClock(wall: start, monotonic: 100)
        let runtime = makeRuntime(
            custody: makeCustody(at: rootURL),
            queue: GateUploadQueue(),
            clock: clock,
            ids: GateIDSequence([rideID])
        )
        _ = try await runtime.activate(user: user)
        _ = try await runtime.start(user: user, at: start)
        clock.set(wall: start.addingTimeInterval(1), monotonic: 101)
        _ = try await runtime.ingest(
            fixtureFix(capturedAt: clock.wallValue, latitude: 39.9500),
            wallNow: clock.wallValue
        )
        clock.set(wall: start.addingTimeInterval(2), monotonic: 102)

        let session = AppSession(
            rideUploads: GateAppSessionUploadRuntime(),
            rideRecordings: runtime,
            accountDeletionCapabilityStore: SessionDeletionCapabilityStore(capability: nil)
        )
        session.phase = .signedIn(user)
        try await session.suspendRecordingAndRefresh {
            try await runtime.suspendActive(at: clock.wallValue)
        }

        XCTAssertEqual(session.pendingInterruptedRide?.id, rideID)
        XCTAssertEqual(session.pendingInterruptedRide?.ownerID, user.id)
        XCTAssertEqual(session.pendingInterruptedRide?.sampleCount, 1)
        XCTAssertNil(session.interruptedRideErrorMessage)
    }

    @MainActor
    func testMOBILE_TRUTHSSections9_1And11ExitRefreshFailureCannotDismissAsSuccess() async {
        let user = fixtureUser(id: "exit-refresh-owner", wallet: "exit-refresh-wallet")
        let recordings = GateAppSessionRecordingRuntime()
        let session = AppSession(
            rideUploads: GateAppSessionUploadRuntime(),
            rideRecordings: recordings,
            accountDeletionCapabilityStore: SessionDeletionCapabilityStore(capability: nil)
        )
        session.phase = .signedIn(user)
        var suspendCalls = 0
        var dismissCalls = 0

        do {
            try await session.suspendRecordingAndRefresh(
                {
                    suspendCalls += 1
                },
                onSuccess: {
                    dismissCalls += 1
                }
            )
            XCTFail("an unavailable recovery refresh must not complete the exit transaction")
        } catch {
            // Retained behavioral red: the pre-change refresh swallowed this
            // failure and let RecordingView dismiss.
        }
        XCTAssertEqual(suspendCalls, 1)
        XCTAssertEqual(dismissCalls, 0)
        XCTAssertNotNil(session.interruptedRideErrorMessage)
        XCTAssertNil(session.pendingInterruptedRide)

        do {
            try await session.suspendRecordingAndRefresh(
                {
                    suspendCalls += 1
                },
                onSuccess: {
                    dismissCalls += 1
                }
            )
        } catch {
            XCTFail("a retry must rerun the complete suspend-and-refresh transaction: \(error)")
        }
        XCTAssertEqual(suspendCalls, 2)
        XCTAssertEqual(dismissCalls, 1)
        XCTAssertNil(session.interruptedRideErrorMessage)
    }

    @MainActor
    func testMOBILE_TRUTHSSections6And11CancelledWaitingEndCannotOverrideCustodyExitRetry() async throws {
        enum StaleEndOrdering: CaseIterable {
            case beforeExitFailure
            case afterExitFailure
        }

        for (index, ordering) in StaleEndOrdering.allCases.enumerated() {
            let user = fixtureUser(
                id: "exit-end-owner-\(index)",
                wallet: "exit-end-wallet-\(index)"
            )
            let rideID = "a8100000-0000-4000-8000-00000000000\(index)"
            let caseRoot = rootURL.appendingPathComponent(
                "exit-end-order-\(index)",
                isDirectory: true
            )
            let clock = GateClock(wall: start, monotonic: 100)
            let fixFault = GateBlockingFirstFixPublishFault()
            let custody = makeCustody(
                at: caseRoot,
                beforeEventPublish: { kind, sequence in
                    try fixFault.beforePublish(kind: kind, sequence: sequence)
                }
            )
            let runtime = makeRuntime(
                custody: custody,
                queue: GateUploadQueue(),
                clock: clock,
                ids: GateIDSequence([rideID])
            )
            _ = try await runtime.activate(user: user)
            let captureFailureBarrier = GateAsyncBarrier()
            let model = RecordingModel(
                user: user,
                runtime: runtime,
                authorizationStatus: .authorizedWhenInUse,
                locationHardwareEnabled: false,
                wallNow: { clock.wallValue },
                monotonicNow: { clock.monotonicValue },
                beforeCaptureFailureApply: { await captureFailureBarrier.wait() }
            )
            await model.handleAuthorizationChange(.authorizedWhenInUse)
            try await waitForModel { model.state == .recording }

            clock.set(wall: start.addingTimeInterval(1), monotonic: 101)
            let location = fixtureLocation(
                capturedAt: start.addingTimeInterval(1),
                latitude: 39.963 + Double(index) / 10_000
            )
            let captureTask = Task { @MainActor in
                await model.handleLocations([location])
            }
            let fixDidBlock = await Task.detached {
                fixFault.waitUntilBlocked(timeout: 2)
            }.value
            XCTAssertTrue(fixDidBlock)

            var retryPolicy = RecordingViewRetryPolicy()
            let endAttempt = try XCTUnwrap(retryPolicy.beginEnd())
            clock.set(wall: start.addingTimeInterval(2), monotonic: 102)
            let endTask = Task { @MainActor in
                try await model.end()
            }
            fixFault.releaseFirstFailure()
            await captureFailureBarrier.waitUntilEntered()
            await captureFailureBarrier.release()
            await captureTask.value
            try await waitForModel { model.custodyErrorMessage != nil }

            let recordings = GateFailOnceThenLiveRecordingRuntime(runtime: runtime)
            let session = AppSession(
                rideUploads: GateAppSessionUploadRuntime(),
                rideRecordings: recordings,
                accountDeletionCapabilityStore: SessionDeletionCapabilityStore(capability: nil)
            )
            session.phase = .signedIn(user)
            retryPolicy.beginCustodyExit()
            var dismissCount = 0
            var sawCancelledEnd = false

            do {
                try await session.suspendRecordingAndRefresh {
                    try await model.suspendAndLeave()
                    if ordering == .beforeExitFailure {
                        do {
                            _ = try await endTask.value
                            XCTFail("the custody Exit must cancel the waiting End")
                        } catch is CancellationError {
                            sawCancelledEnd = true
                            _ = retryPolicy.endFailed(endAttempt)
                        } catch {
                            XCTFail("unexpected waiting End failure: \(error)")
                        }
                    }
                }
                XCTFail("the first exact-owner recovery refresh must fail")
            } catch {
                retryPolicy.custodyExitFailed()
            }

            if ordering == .afterExitFailure {
                do {
                    _ = try await endTask.value
                    XCTFail("the custody Exit must cancel the waiting End")
                } catch is CancellationError {
                    sawCancelledEnd = true
                    _ = retryPolicy.endFailed(endAttempt)
                } catch {
                    XCTFail("unexpected waiting End failure: \(error)")
                }
            }
            XCTAssertTrue(sawCancelledEnd)
            XCTAssertEqual(
                retryPolicy.action,
                .custodyExit,
                "custody Exit must exclusively own Retry after cancelling an older End"
            )

            var routedEnd = 0
            var routedExit = 0
            retryPolicy.routeRetry(
                model: {},
                end: { routedEnd += 1 },
                custodyExit: { routedExit += 1 }
            )
            XCTAssertEqual(routedEnd, 0)
            XCTAssertEqual(routedExit, 1)
            guard routedExit == 1 else { continue }

            do {
                try await session.suspendRecordingAndRefresh(
                    { try await model.suspendAndLeave() },
                    onSuccess: {
                        retryPolicy.custodyExitSucceeded()
                        dismissCount += 1
                    }
                )
            } catch {
                XCTFail("custody Exit Retry must refresh and dismiss: \(error)")
            }
            XCTAssertEqual(dismissCount, 1)
            XCTAssertEqual(session.pendingInterruptedRide?.id, rideID)
            XCTAssertNil(session.interruptedRideErrorMessage)
            let persisted = try await custody.persisted(
                owner: RecordingOwner(user: user),
                rideID: rideID
            )
            XCTAssertEqual(
                persisted.events.map(\.kind),
                [.start, .fix, .suspend],
                "Exit retains the exact already-delivered fix before suspension"
            )
            XCTAssertFalse(persisted.events.contains { $0.kind == .stop })
            XCTAssertFalse(persisted.events.contains { $0.kind == .finalized })
        }
    }

    @MainActor
    func testMOBILE_TRUTHSSection6RapidDuplicateEndKeepsOriginalAttemptUntilCompletion() async throws {
        let user = fixtureUser(id: "duplicate-end-owner", wallet: "duplicate-end-wallet")
        let rideID = "a8200000-0000-4000-8000-00000000000a"
        let clock = GateClock(wall: start, monotonic: 100)
        let custody = makeCustody(at: rootURL)
        let runtime = makeRuntime(
            custody: custody,
            queue: GateUploadQueue(),
            clock: clock,
            ids: GateIDSequence([rideID])
        )
        _ = try await runtime.activate(user: user)
        let model = RecordingModel(
            user: user,
            runtime: runtime,
            authorizationStatus: .authorizedWhenInUse,
            locationHardwareEnabled: false,
            wallNow: { clock.wallValue },
            monotonicNow: { clock.monotonicValue }
        )
        await model.handleAuthorizationChange(.authorizedWhenInUse)
        try await waitForModel { model.state == .recording }

        var policy = RecordingViewRetryPolicy()
        clock.set(wall: start.addingTimeInterval(2), monotonic: 102)
        let first = try XCTUnwrap(
            policy.beginEnd(reserveControlIntent: { model.reserveEndIntent() })
        )
        let duplicate = policy.beginEnd(
            reserveControlIntent: { model.reserveEndIntent() }
        )
        XCTAssertNil(
            duplicate,
            "the first accepted End token must remain exclusive before its Task starts"
        )

        let finalized: FinalizedRecording?
        if let intent = first.controlIntent {
            finalized = try await model.completeEnd(intent)
        } else {
            finalized = try await model.end()
        }
        XCTAssertNotNil(finalized)
        var dismissCount = 0
        if policy.endSucceeded(first) { dismissCount += 1 }
        XCTAssertEqual(dismissCount, 1)
        let persisted = try await custody.persisted(
            owner: RecordingOwner(user: user),
            rideID: rideID
        )
        XCTAssertEqual(persisted.events.filter { $0.kind == .stop }.count, 1)
        XCTAssertEqual(persisted.events.filter { $0.kind == .finalized }.count, 1)

        var retryPolicy = RecordingViewRetryPolicy()
        let failed = try XCTUnwrap(retryPolicy.beginEnd())
        XCTAssertTrue(retryPolicy.endFailed(failed))
        let retry = try XCTUnwrap(retryPolicy.beginEndRetry())
        XCTAssertEqual(retry, failed, "explicit Retry must resume the owned End attempt")
        XCTAssertNil(
            retryPolicy.beginEndRetry(),
            "a rapid duplicate Retry cannot replace its active token"
        )
    }

    @MainActor
    func testMOBILE_TRUTHSSection6EndTapSynchronouslyFreezesCutoffWallAndMonotonic() async throws {
        let user = fixtureUser(id: "end-tap-owner", wallet: "end-tap-wallet")
        let rideID = "a8200000-0000-4000-8000-00000000000b"
        let clock = GateClock(wall: start, monotonic: 100)
        let custody = makeCustody(at: rootURL)
        let runtime = makeRuntime(
            custody: custody,
            queue: GateUploadQueue(),
            clock: clock,
            ids: GateIDSequence([rideID])
        )
        _ = try await runtime.activate(user: user)
        let model = RecordingModel(
            user: user,
            runtime: runtime,
            authorizationStatus: .authorizedWhenInUse,
            locationHardwareEnabled: false,
            wallNow: { clock.wallValue },
            monotonicNow: { clock.monotonicValue }
        )
        var admitted: [Double] = []
        var delivered: [Double] = []
        model.onCaptureCallback = { admitted.append($0.coordinate.latitude) }
        model.onFix = { delivered.append($0.coordinate.latitude) }
        await model.handleAuthorizationChange(.authorizedWhenInUse)
        try await waitForModel { model.state == .recording }

        clock.set(wall: start.addingTimeInterval(2), monotonic: 102)
        var policy = RecordingViewRetryPolicy()
        let attempt = try XCTUnwrap(
            policy.beginEnd(reserveControlIntent: { model.reserveEndIntent() })
        )
        let afterTap = fixtureLocation(
            capturedAt: start.addingTimeInterval(3),
            latitude: 39.96400
        )
        model.locationManager(CLLocationManager(), didUpdateLocations: [afterTap])
        XCTAssertTrue(
            admitted.isEmpty,
            "the real delegate must reject testimony delivered after the End tap"
        )
        XCTAssertEqual(model.queuedCaptureCountForTesting, 0)

        clock.set(wall: start.addingTimeInterval(99), monotonic: 199)
        let finalized: FinalizedRecording?
        if let intent = attempt.controlIntent {
            finalized = try await model.completeEnd(intent)
        } else {
            finalized = try await model.end()
        }
        XCTAssertNotNil(finalized)
        XCTAssertTrue(policy.endSucceeded(attempt))
        XCTAssertTrue(delivered.isEmpty)
        let persisted = try await custody.persisted(
            owner: RecordingOwner(user: user),
            rideID: rideID
        )
        XCTAssertEqual(persisted.events.map(\.kind), [.start, .stop, .finalized])
        let stop = try XCTUnwrap(persisted.events.first { $0.kind == .stop })
        XCTAssertEqual(stop.occurredAt, start.addingTimeInterval(2))
        XCTAssertEqual(stop.monotonicOffsetS, 2, accuracy: 0.000_001)
    }

    @MainActor
    func testMOBILE_TRUTHSSections6And11CancelTapSynchronouslyDeactivatesAndRetriesExactSuspendBoundary() async throws {
        let user = fixtureUser(id: "cancel-tap-owner", wallet: "cancel-tap-wallet")
        let rideID = "a8200000-0000-4000-8000-00000000000c"
        let clock = GateClock(wall: start, monotonic: 100)
        let suspendFault = GateSuspendEventFault()
        let custody = makeCustody(
            at: rootURL,
            beforeEventPublish: { kind, sequence in
                try suspendFault.beforePublish(kind: kind, sequence: sequence)
            }
        )
        let runtime = makeRuntime(
            custody: custody,
            queue: GateUploadQueue(),
            clock: clock,
            ids: GateIDSequence([rideID])
        )
        _ = try await runtime.activate(user: user)
        let model = RecordingModel(
            user: user,
            runtime: runtime,
            authorizationStatus: .authorizedWhenInUse,
            locationHardwareEnabled: false,
            wallNow: { clock.wallValue },
            monotonicNow: { clock.monotonicValue }
        )
        var admitted: [Double] = []
        var delivered: [Double] = []
        model.onCaptureCallback = { admitted.append($0.coordinate.latitude) }
        model.onFix = { delivered.append($0.coordinate.latitude) }
        await model.handleAuthorizationChange(.authorizedWhenInUse)
        try await waitForModel {
            model.state == .recording && model.captureHardwareActive
        }

        var policy = RecordingViewRetryPolicy()
        clock.set(wall: start.addingTimeInterval(2), monotonic: 102)
        let firstIntent = policy.beginCustodyExit(
            reserveSuspendIntent: { model.reserveSuspendAndLeaveIntent() }
        )
        XCTAssertFalse(
            model.captureHardwareActive,
            "Cancel must stop the production hardware boundary before returning"
        )
        let afterTap = fixtureLocation(
            capturedAt: start.addingTimeInterval(3),
            latitude: 39.96410
        )
        clock.set(wall: start.addingTimeInterval(3), monotonic: 103)
        model.locationManager(CLLocationManager(), didUpdateLocations: [afterTap])
        await model.handleCaptureTick()
        XCTAssertTrue(admitted.isEmpty)
        XCTAssertTrue(delivered.isEmpty)
        XCTAssertEqual(model.queuedCaptureCountForTesting, 0)

        let session = AppSession(
            rideUploads: GateAppSessionUploadRuntime(),
            rideRecordings: runtime,
            accountDeletionCapabilityStore: SessionDeletionCapabilityStore(capability: nil)
        )
        session.phase = .signedIn(user)
        clock.set(wall: start.addingTimeInterval(99), monotonic: 199)
        do {
            try await session.suspendRecordingAndRefresh {
                if let firstIntent {
                    try await model.completeSuspendAndLeave(firstIntent)
                } else {
                    try await model.suspendAndLeave()
                }
            }
            XCTFail("the first durable Suspend publication must fail")
        } catch GateTestError.injectedFailure {
            policy.custodyExitFailed()
        } catch {
            XCTFail("unexpected first custody Exit failure: \(error)")
        }
        XCTAssertEqual(policy.action, .custodyExit)

        var routedExit = 0
        policy.routeRetry(
            model: {},
            end: {},
            custodyExit: { routedExit += 1 }
        )
        XCTAssertEqual(routedExit, 1)
        clock.set(wall: start.addingTimeInterval(199), monotonic: 299)
        let retryIntent = policy.beginCustodyExit(
            reserveSuspendIntent: { model.reserveSuspendAndLeaveIntent() }
        )
        var dismissCount = 0
        do {
            try await session.suspendRecordingAndRefresh(
                {
                    if let retryIntent {
                        try await model.completeSuspendAndLeave(retryIntent)
                    } else {
                        try await model.suspendAndLeave()
                    }
                },
                onSuccess: {
                    policy.custodyExitSucceeded()
                    dismissCount += 1
                }
            )
        } catch {
            XCTFail("custody Exit Retry must preserve and publish its tap boundary: \(error)")
        }
        XCTAssertEqual(dismissCount, 1)
        XCTAssertEqual(session.pendingInterruptedRide?.id, rideID)
        let persisted = try await custody.persisted(
            owner: RecordingOwner(user: user),
            rideID: rideID
        )
        XCTAssertEqual(persisted.events.map(\.kind), [.start, .suspend])
        let suspend = try XCTUnwrap(persisted.events.last)
        XCTAssertEqual(suspend.occurredAt, start.addingTimeInterval(2))
        XCTAssertEqual(suspend.monotonicOffsetS, 2, accuracy: 0.000_001)
    }

    @MainActor
    func testMOBILE_TRUTHSSection6ReservedEndRemainsAuthoritativeAcrossLaterAuthorizationDenial() async throws {
        let cases: [(status: CLAuthorizationStatus, suffix: String)] = [
            (.denied, "d"),
            (.restricted, "e"),
        ]

        for testCase in cases {
            let user = fixtureUser(
                id: "end-auth-owner-\(testCase.suffix)",
                wallet: "end-auth-wallet-\(testCase.suffix)"
            )
            let rideID = "a8300000-0000-4000-8000-00000000000\(testCase.suffix)"
            let caseRoot = rootURL.appendingPathComponent(
                "reserved-end-auth-\(testCase.suffix)",
                isDirectory: true
            )
            let clock = GateClock(wall: start, monotonic: 100)
            let custody = makeCustody(at: caseRoot)
            let runtime = makeRuntime(
                custody: custody,
                queue: GateUploadQueue(),
                clock: clock,
                ids: GateIDSequence([rideID])
            )
            _ = try await runtime.activate(user: user)
            let model = RecordingModel(
                user: user,
                runtime: runtime,
                authorizationStatus: .authorizedWhenInUse,
                locationHardwareEnabled: false,
                wallNow: { clock.wallValue },
                monotonicNow: { clock.monotonicValue }
            )
            await model.handleAuthorizationChange(.authorizedWhenInUse)
            try await waitForModel {
                model.state == .recording && model.captureHardwareActive
            }

            clock.set(wall: start.addingTimeInterval(2), monotonic: 102)
            let hardwareStartsAtTap = model.captureHardwareStartCount
            let endIntent = try XCTUnwrap(model.reserveEndIntent())
            XCTAssertFalse(model.captureHardwareActive)

            await model.handleAuthorizationChange(testCase.status)
            XCTAssertFalse(model.captureHardwareActive)
            XCTAssertFalse(model.recoveryExitRequired)

            // A restoration callback cannot restart capture while the exact
            // terminal intent remains reserved.
            await model.handleAuthorizationChange(.authorizedWhenInUse)
            XCTAssertFalse(model.captureHardwareActive)
            XCTAssertEqual(model.captureHardwareStartCount, hardwareStartsAtTap)

            let finalized = try await model.completeEnd(endIntent)
            XCTAssertNotNil(finalized)
            let persisted = try await custody.persisted(
                owner: RecordingOwner(user: user),
                rideID: rideID
            )
            XCTAssertEqual(persisted.events.map(\.kind), [.start, .stop, .finalized])
            XCTAssertFalse(persisted.events.contains { $0.kind == .suspend })
            let stop = try XCTUnwrap(persisted.events.first { $0.kind == .stop })
            XCTAssertEqual(stop.occurredAt, start.addingTimeInterval(2))
            XCTAssertEqual(stop.monotonicOffsetS, 2, accuracy: 0.000_001)
        }
    }

    @MainActor
    func testMOBILE_TRUTHSSections6And9_1AuthorizationSuspensionRejectsLaterEnd() async throws {
        let user = fixtureUser(id: "auth-first-owner", wallet: "auth-first-wallet")
        let rideID = "a8300000-0000-4000-8000-00000000000f"
        let clock = GateClock(wall: start, monotonic: 100)
        let custody = makeCustody(at: rootURL)
        let runtime = makeRuntime(
            custody: custody,
            queue: GateUploadQueue(),
            clock: clock,
            ids: GateIDSequence([rideID])
        )
        _ = try await runtime.activate(user: user)
        let model = RecordingModel(
            user: user,
            runtime: runtime,
            authorizationStatus: .authorizedWhenInUse,
            locationHardwareEnabled: false,
            wallNow: { clock.wallValue },
            monotonicNow: { clock.monotonicValue }
        )
        await model.handleAuthorizationChange(.authorizedWhenInUse)
        try await waitForModel {
            model.state == .recording && model.captureHardwareActive
        }

        clock.set(wall: start.addingTimeInterval(2), monotonic: 102)
        let hardwareStartsBeforeDenial = model.captureHardwareStartCount
        await model.handleAuthorizationChange(.denied)
        XCTAssertTrue(model.recoveryExitRequired)
        XCTAssertFalse(model.captureHardwareActive)
        XCTAssertNil(
            model.reserveEndIntent(),
            "authorization-owned suspension must reject a later End intent"
        )

        await model.handleAuthorizationChange(.authorizedWhenInUse)
        XCTAssertFalse(model.captureHardwareActive)
        XCTAssertEqual(model.captureHardwareStartCount, hardwareStartsBeforeDenial)
        let persisted = try await custody.persisted(
            owner: RecordingOwner(user: user),
            rideID: rideID
        )
        XCTAssertEqual(persisted.events.map(\.kind), [.start, .suspend])
        XCTAssertFalse(persisted.events.contains { $0.kind == .stop })
        XCTAssertFalse(persisted.events.contains { $0.kind == .finalized })
        let suspend = try XCTUnwrap(persisted.events.last)
        XCTAssertEqual(suspend.occurredAt, start.addingTimeInterval(2))
        XCTAssertEqual(suspend.monotonicOffsetS, 2, accuracy: 0.000_001)
    }

    @MainActor
    func testMOBILE_TRUTHSSections3And9_1AuthorizationLossDuringBlockedStartKeepsCallbackBoundary() async throws {
        let cases: [(status: CLAuthorizationStatus, suffix: String)] = [
            (.denied, "d"),
            (.restricted, "e"),
        ]

        for testCase in cases {
            let user = fixtureUser(
                id: "blocked-auth-owner-\(testCase.suffix)",
                wallet: "blocked-auth-wallet-\(testCase.suffix)"
            )
            let rideID = "a8400000-0000-4000-8000-00000000000\(testCase.suffix)"
            let caseRoot = rootURL.appendingPathComponent(
                "blocked-auth-boundary-\(testCase.suffix)",
                isDirectory: true
            )
            let clock = GateClock(wall: start, monotonic: 100)
            let startBarrier = GateEventPublishBarrier(blocking: .start)
            let custody = makeCustody(
                at: caseRoot,
                beforeEventPublish: { kind, sequence in
                    try startBarrier.beforePublish(kind: kind, sequence: sequence)
                }
            )
            let runtime = makeRuntime(
                custody: custody,
                queue: GateUploadQueue(),
                clock: clock,
                ids: GateIDSequence([rideID])
            )
            _ = try await runtime.activate(user: user)
            let model = RecordingModel(
                user: user,
                runtime: runtime,
                authorizationStatus: .authorizedWhenInUse,
                locationHardwareEnabled: false,
                wallNow: { clock.wallValue },
                monotonicNow: { clock.monotonicValue }
            )

            await model.handleAuthorizationChange(.authorizedWhenInUse)
            let didBlock = await Task.detached {
                startBarrier.waitUntilBlocked(timeout: 2)
            }.value
            XCTAssertTrue(didBlock)

            clock.set(wall: start.addingTimeInterval(2), monotonic: 102)
            let denial = Task { @MainActor in
                await model.handleAuthorizationChange(testCase.status)
            }
            try await waitForModel { model.authorization == testCase.status }

            // The durable Start may finish much later, but permission loss
            // owns the exact callback clocks rather than this release time.
            clock.set(wall: start.addingTimeInterval(99), monotonic: 199)
            startBarrier.release()
            await denial.value

            XCTAssertTrue(model.recoveryExitRequired)
            let persisted = try await custody.persisted(
                owner: RecordingOwner(user: user),
                rideID: rideID
            )
            XCTAssertEqual(persisted.events.map(\.kind), [.start, .suspend])
            let suspend = try XCTUnwrap(persisted.events.last)
            XCTAssertEqual(suspend.occurredAt, start.addingTimeInterval(2))
            XCTAssertEqual(suspend.monotonicOffsetS, 2, accuracy: 0.000_001)
            let recovery = try await runtime.recovery(ownerID: user.id)
            XCTAssertEqual(recovery?.durationS ?? -1, 2, accuracy: 0.000_001)
        }
    }

    @MainActor
    func testMOBILE_TRUTHSSections6And11CancelDrainsEveryPretapDelegateFixBeforeExactSuspend() async throws {
        let user = fixtureUser(id: "cancel-cutoff-owner", wallet: "cancel-cutoff-wallet")
        let rideID = "a8400000-0000-4000-8000-00000000000f"
        let clock = GateClock(wall: start, monotonic: 100)
        let fixFault = GateBlockingFirstFixPublishFault()
        let custody = makeCustody(
            at: rootURL,
            beforeEventPublish: { kind, sequence in
                try fixFault.beforePublish(kind: kind, sequence: sequence)
            }
        )
        let runtime = makeRuntime(
            custody: custody,
            queue: GateUploadQueue(),
            clock: clock,
            ids: GateIDSequence([rideID])
        )
        _ = try await runtime.activate(user: user)
        let model = RecordingModel(
            user: user,
            runtime: runtime,
            authorizationStatus: .authorizedWhenInUse,
            locationHardwareEnabled: false,
            wallNow: { clock.wallValue },
            monotonicNow: { clock.monotonicValue }
        )
        var admitted: [Double] = []
        var delivered: [Double] = []
        model.onCaptureCallback = { admitted.append($0.coordinate.latitude) }
        model.onFix = { delivered.append($0.coordinate.latitude) }
        await model.handleAuthorizationChange(.authorizedWhenInUse)
        try await waitForModel {
            model.state == .recording && model.captureHardwareActive
        }

        clock.set(wall: start.addingTimeInterval(1), monotonic: 101)
        let first = fixtureLocation(
            capturedAt: start.addingTimeInterval(1),
            latitude: 39.96500
        )
        let second = fixtureLocation(
            capturedAt: start.addingTimeInterval(1.5),
            latitude: 39.96510
        )
        model.locationManager(
            CLLocationManager(),
            didUpdateLocations: [first, second]
        )
        let fixDidBlock = await Task.detached {
            fixFault.waitUntilBlocked(timeout: 2)
        }.value
        XCTAssertTrue(fixDidBlock)
        XCTAssertEqual(
            admitted,
            [first.coordinate.latitude, second.coordinate.latitude]
        )

        clock.set(wall: start.addingTimeInterval(2), monotonic: 102)
        guard let suspendIntent = model.reserveSuspendAndLeaveIntent() else {
            fixFault.releaseFirstFailure()
            XCTFail("Cancel must synchronously reserve its suspension intent")
            return
        }
        XCTAssertFalse(model.captureHardwareActive)

        clock.set(wall: start.addingTimeInterval(3), monotonic: 103)
        let postTap = fixtureLocation(
            capturedAt: start.addingTimeInterval(3),
            latitude: 39.96520
        )
        model.locationManager(CLLocationManager(), didUpdateLocations: [postTap])
        await model.handleCaptureTick()
        XCTAssertEqual(
            admitted,
            [first.coordinate.latitude, second.coordinate.latitude],
            "Cancel must reject every callback delivered after its cutoff"
        )

        let suspend = Task { @MainActor in
            try await model.completeSuspendAndLeave(suspendIntent)
        }
        fixFault.releaseFirstFailure()
        try await suspend.value

        let persisted = try await custody.persisted(
            owner: RecordingOwner(user: user),
            rideID: rideID
        )
        XCTAssertEqual(
            persisted.events.map(\.kind),
            [.start, .fix, .fix, .suspend]
        )
        let durableSuspend = try XCTUnwrap(persisted.events.last)
        XCTAssertEqual(durableSuspend.occurredAt, start.addingTimeInterval(2))
        XCTAssertEqual(durableSuspend.monotonicOffsetS, 2, accuracy: 0.000_001)
        let evidence = try await runtime.recoveryEvidence(ownerID: user.id)
        XCTAssertEqual(
            evidence?.samples.map(\.latitude),
            [first.coordinate.latitude, second.coordinate.latitude]
        )
        XCTAssertTrue(delivered.isEmpty)
        XCTAssertEqual(model.queuedCaptureCountForTesting, 0)
    }

    @MainActor
    func testMOBILE_TRUTHSSections6And9_1And11AuthorizationLossAndCancelShareOneSuspensionCompletion() async throws {
        let user = fixtureUser(
            id: "shared-suspend-owner",
            wallet: "shared-suspend-wallet"
        )
        let rideID = "a8500000-0000-4000-8000-00000000000a"
        let clock = GateClock(wall: start, monotonic: 100)
        let fixBarrier = GateEventPublishBarrier(blocking: .fix)
        let tickBarrier = GateAsyncBarrier()
        let custody = makeCustody(
            at: rootURL,
            beforeEventPublish: { kind, sequence in
                try fixBarrier.beforePublish(kind: kind, sequence: sequence)
            }
        )
        let runtime = makeRuntime(
            custody: custody,
            queue: GateUploadQueue(),
            clock: clock,
            ids: GateIDSequence([rideID])
        )
        _ = try await runtime.activate(user: user)
        let model = RecordingModel(
            user: user,
            runtime: runtime,
            authorizationStatus: .authorizedWhenInUse,
            locationHardwareEnabled: false,
            wallNow: { clock.wallValue },
            monotonicNow: { clock.monotonicValue },
            beforeCaptureProjectionApply: {
                await tickBarrier.wait()
            }
        )
        var admitted: [Double] = []
        var delivered: [Double] = []
        model.onCaptureCallback = { admitted.append($0.coordinate.latitude) }
        model.onFix = { delivered.append($0.coordinate.latitude) }
        await model.handleAuthorizationChange(.authorizedWhenInUse)
        try await waitForModel {
            model.state == .recording && model.captureHardwareActive
        }

        let tick = Task { @MainActor in
            await model.handleCaptureTick()
        }
        await tickBarrier.waitUntilEntered()

        clock.set(wall: start.addingTimeInterval(1), monotonic: 101)
        let first = fixtureLocation(
            capturedAt: start.addingTimeInterval(1),
            latitude: 39.96600
        )
        let second = fixtureLocation(
            capturedAt: start.addingTimeInterval(1.5),
            latitude: 39.96610
        )
        model.locationManager(
            CLLocationManager(),
            didUpdateLocations: [first, second]
        )
        XCTAssertEqual(
            admitted,
            [first.coordinate.latitude, second.coordinate.latitude]
        )
        XCTAssertEqual(model.queuedCaptureCountForTesting, 2)

        clock.set(wall: start.addingTimeInterval(2), monotonic: 102)
        let authorizationLoss = Task { @MainActor in
            await model.handleAuthorizationChange(.denied)
        }
        try await waitForModel { model.authorization == .denied }
        guard let sharedIntent = model.reserveSuspendAndLeaveIntent() else {
            await tickBarrier.release()
            fixBarrier.release()
            XCTFail("Cancel must reuse the authorization-owned Suspend intent")
            return
        }
        var cancelBegan = false
        let cancel = Task { @MainActor () -> Result<Void, Error> in
            cancelBegan = true
            do {
                try await model.completeSuspendAndLeave(sharedIntent)
                return .success(())
            } catch {
                return .failure(error)
            }
        }
        try await waitForModel { cancelBegan }

        await tickBarrier.release()
        await tick.value
        let fixDidBlock = await Task.detached {
            fixBarrier.waitUntilBlocked(timeout: 2)
        }.value
        XCTAssertTrue(
            fixDidBlock,
            "the shared terminal transaction must persist the pre-tap queue"
        )
        for _ in 0..<20 { await Task.yield() }
        fixBarrier.release()

        await authorizationLoss.value
        switch await cancel.value {
        case .success:
            break
        case let .failure(error):
            XCTFail("the shared Cancel waiter must observe terminal success: \(error)")
        }

        let persisted = try await custody.persisted(
            owner: RecordingOwner(user: user),
            rideID: rideID
        )
        XCTAssertEqual(
            persisted.events.map(\.kind),
            [.start, .fix, .fix, .suspend]
        )
        XCTAssertEqual(persisted.events.filter { $0.kind == .suspend }.count, 1)
        let evidence = try await runtime.recoveryEvidence(ownerID: user.id)
        XCTAssertEqual(
            evidence?.samples.map(\.latitude),
            [first.coordinate.latitude, second.coordinate.latitude]
        )
        XCTAssertTrue(delivered.isEmpty)
        XCTAssertTrue(model.custodySuspensionCompleted)
        XCTAssertTrue(model.recoveryExitRequired)
        XCTAssertNil(model.custodyErrorMessage)
        XCTAssertEqual(model.queuedCaptureCountForTesting, 0)
    }

    @MainActor
    func testMOBILE_TRUTHSSections9_1And11RepeatedAuthorizationLossSharesOneSuspensionFailureAndRetry() async throws {
        let user = fixtureUser(
            id: "repeated-auth-suspend-owner",
            wallet: "repeated-auth-suspend-wallet"
        )
        let rideID = "a8500000-0000-4000-8000-00000000000b"
        let clock = GateClock(wall: start, monotonic: 100)
        let suspendBarrier = GateEventPublishBarrier(blocking: .suspend)
        let suspendFault = GateSuspendEventFault()
        let custody = makeCustody(
            at: rootURL,
            beforeEventPublish: { kind, sequence in
                try suspendBarrier.beforePublish(kind: kind, sequence: sequence)
                try suspendFault.beforePublish(kind: kind, sequence: sequence)
            }
        )
        let runtime = makeRuntime(
            custody: custody,
            queue: GateUploadQueue(),
            clock: clock,
            ids: GateIDSequence([rideID])
        )
        _ = try await runtime.activate(user: user)
        let model = RecordingModel(
            user: user,
            runtime: runtime,
            authorizationStatus: .authorizedWhenInUse,
            locationHardwareEnabled: false,
            wallNow: { clock.wallValue },
            monotonicNow: { clock.monotonicValue }
        )
        await model.handleAuthorizationChange(.authorizedWhenInUse)
        try await waitForModel {
            model.state == .recording && model.captureHardwareActive
        }

        clock.set(wall: start.addingTimeInterval(2), monotonic: 102)
        let denied = Task { @MainActor in
            await model.handleAuthorizationChange(.denied)
        }
        let suspendDidBlock = await Task.detached {
            suspendBarrier.waitUntilBlocked(timeout: 2)
        }.value
        XCTAssertTrue(suspendDidBlock)

        let restricted = Task { @MainActor in
            await model.handleAuthorizationChange(.restricted)
        }
        try await waitForModel { model.authorization == .restricted }
        suspendBarrier.release()
        await denied.value
        await restricted.value

        XCTAssertFalse(
            model.custodySuspensionCompleted,
            "concurrent callers must observe the same failed durable transaction"
        )
        XCTAssertFalse(model.recoveryExitRequired)
        XCTAssertNotNil(model.custodyErrorMessage)
        let beforeRetry = try await custody.persisted(
            owner: RecordingOwner(user: user),
            rideID: rideID
        )
        XCTAssertEqual(beforeRetry.events.map(\.kind), [.start])

        clock.set(wall: start.addingTimeInterval(99), monotonic: 199)
        model.retryCustodyOperation()
        try await waitForModel {
            model.custodySuspensionCompleted && model.recoveryExitRequired
        }
        let afterRetry = try await custody.persisted(
            owner: RecordingOwner(user: user),
            rideID: rideID
        )
        XCTAssertEqual(afterRetry.events.map(\.kind), [.start, .suspend])
        XCTAssertEqual(afterRetry.events.filter { $0.kind == .suspend }.count, 1)
        let suspend = try XCTUnwrap(afterRetry.events.last)
        XCTAssertEqual(suspend.occurredAt, start.addingTimeInterval(2))
        XCTAssertEqual(suspend.monotonicOffsetS, 2, accuracy: 0.000_001)
        XCTAssertNil(model.custodyErrorMessage)
    }

    @MainActor
    func testMOBILE_TRUTHSSections6And9_1And11OwnerSurfaceExitPreservesSuspendOwnedDelegateCutoff() async throws {
        let user = fixtureUser(
            id: "surface-exit-suspend-owner",
            wallet: "surface-exit-suspend-wallet"
        )
        let rideID = "a8500000-0000-4000-8000-00000000000c"
        let clock = GateClock(wall: start, monotonic: 100)
        let fixFault = GateBlockingFirstFixPublishFault()
        let custody = makeCustody(
            at: rootURL,
            beforeEventPublish: { kind, sequence in
                try fixFault.beforePublish(kind: kind, sequence: sequence)
            }
        )
        let runtime = makeRuntime(
            custody: custody,
            queue: GateUploadQueue(),
            clock: clock,
            ids: GateIDSequence([rideID])
        )
        _ = try await runtime.activate(user: user)
        let model = RecordingModel(
            user: user,
            runtime: runtime,
            authorizationStatus: .authorizedWhenInUse,
            locationHardwareEnabled: false,
            wallNow: { clock.wallValue },
            monotonicNow: { clock.monotonicValue }
        )
        var admitted: [Double] = []
        var delivered: [Double] = []
        model.onCaptureCallback = { admitted.append($0.coordinate.latitude) }
        model.onFix = { delivered.append($0.coordinate.latitude) }
        await model.handleAuthorizationChange(.authorizedWhenInUse)
        try await waitForModel {
            model.state == .recording && model.captureHardwareActive
        }

        clock.set(wall: start.addingTimeInterval(1), monotonic: 101)
        let first = fixtureLocation(
            capturedAt: start.addingTimeInterval(1),
            latitude: 39.96620
        )
        let second = fixtureLocation(
            capturedAt: start.addingTimeInterval(1.5),
            latitude: 39.96630
        )
        model.locationManager(
            CLLocationManager(),
            didUpdateLocations: [first, second]
        )
        let fixDidBlock = await Task.detached {
            fixFault.waitUntilBlocked(timeout: 2)
        }.value
        XCTAssertTrue(fixDidBlock)
        XCTAssertEqual(
            admitted,
            [first.coordinate.latitude, second.coordinate.latitude]
        )

        clock.set(wall: start.addingTimeInterval(2), monotonic: 102)
        guard let suspendIntent = model.reserveSuspendAndLeaveIntent() else {
            fixFault.releaseFirstFailure()
            XCTFail("Cancel must synchronously reserve its capture cutoff")
            return
        }
        let suspend = Task { @MainActor in
            try await model.completeSuspendAndLeave(suspendIntent)
        }
        do {
            try await waitForModel {
                model.suspensionCompletionInFlightForTesting
            }
        } catch {
            fixFault.releaseFirstFailure()
            throw error
        }

        model.leaveOwnerSurface()
        let postTap = fixtureLocation(
            capturedAt: start.addingTimeInterval(3),
            latitude: 39.96640
        )
        clock.set(wall: start.addingTimeInterval(3), monotonic: 103)
        model.locationManager(CLLocationManager(), didUpdateLocations: [postTap])
        await model.handleCaptureTick()
        XCTAssertEqual(
            admitted,
            [first.coordinate.latitude, second.coordinate.latitude],
            "owner-surface exit must reject every post-cutoff callback"
        )

        fixFault.releaseFirstFailure()
        try await suspend.value

        let persisted = try await custody.persisted(
            owner: RecordingOwner(user: user),
            rideID: rideID
        )
        XCTAssertEqual(
            persisted.events.map(\.kind),
            [.start, .fix, .fix, .suspend]
        )
        XCTAssertEqual(persisted.events.filter { $0.kind == .suspend }.count, 1)
        let durableSuspend = try XCTUnwrap(persisted.events.last)
        XCTAssertEqual(durableSuspend.occurredAt, start.addingTimeInterval(2))
        XCTAssertEqual(durableSuspend.monotonicOffsetS, 2, accuracy: 0.000_001)
        let evidence = try await runtime.recoveryEvidence(ownerID: user.id)
        XCTAssertEqual(
            evidence?.samples.map(\.latitude),
            [first.coordinate.latitude, second.coordinate.latitude]
        )
        XCTAssertTrue(delivered.isEmpty)
        XCTAssertEqual(model.queuedCaptureCountForTesting, 0)
    }

    private func makeCustody(
        at root: URL,
        beforeEventPublish: @escaping @Sendable (
            RecordingCustodyEventKind,
            UInt64
        ) throws -> Void = { _, _ in },
        beforeDirectorySync: @escaping @Sendable (URL) throws -> Void = { _ in },
        beforeDiscardRemove: @escaping @Sendable (URL) throws -> Void = { _ in }
    ) -> FileLiveRideCustodyStore {
        let key = masterKey
        return FileLiveRideCustodyStore(
            rootURL: root,
            keyLoader: { _ in key },
            beforeEventPublish: beforeEventPublish,
            beforeDirectorySync: beforeDirectorySync,
            beforeDiscardRemove: beforeDiscardRemove
        )
    }

    @MainActor
    private func exerciseDiscardAfterPendingMarker(
        target: RecordingCustodyEventKind,
        ownerID: String,
        ownerWallet: String,
        rideID: String,
        nextRideID: String
    ) async throws {
        let user = fixtureUser(id: ownerID, wallet: ownerWallet)
        let clock = GateClock(wall: start, monotonic: 100)
        let queue = GateUploadQueue()
        let markerFault = GateEventKindAfterMoveSyncFault(target: target)
        let deleteFault = GateNextParentDirectorySyncFault()
        let custody = makeCustody(
            at: rootURL,
            beforeEventPublish: { kind, sequence in
                markerFault.beforePublish(kind: kind, sequence: sequence)
            },
            beforeDirectorySync: { directory in
                try markerFault.beforeSync(directory: directory)
                try deleteFault.beforeSync(directory: directory)
            }
        )
        let runtime = makeRuntime(
            custody: custody,
            queue: queue,
            clock: clock,
            ids: GateIDSequence([rideID, nextRideID])
        )
        _ = try await runtime.activate(user: user)
        _ = try await runtime.start(user: user, at: start)
        _ = try await ingestEligibleRide(runtime: runtime, clock: clock)
        _ = try await runtime.activate(user: nil)

        let session = AppSession(
            rideUploads: GateAppSessionUploadRuntime(),
            rideRecordings: runtime,
            accountDeletionCapabilityStore: SessionDeletionCapabilityStore(capability: nil)
        )
        session.phase = .signedIn(user)
        await session.refreshRideUploads()
        let recovery = try XCTUnwrap(session.pendingInterruptedRide)

        markerFault.arm()
        do {
            try await session.saveInterruptedRide(recovery)
            XCTFail("the targeted \(target.rawValue) durability fault must stay nonfinal")
        } catch GateTestError.injectedFailure {}
        XCTAssertEqual(session.pendingInterruptedRide, recovery)
        let queueCallsBeforeDiscard = await queue.callSnapshot()
        XCTAssertTrue(queueCallsBeforeDiscard.isEmpty)

        deleteFault.arm()
        do {
            try await session.discardInterruptedRide(recovery)
            XCTFail("discard cannot clear UI state before the parent directory is durable")
        } catch GateTestError.injectedFailure {}
        XCTAssertEqual(session.pendingInterruptedRide, recovery)

        try await session.discardInterruptedRide(recovery)
        XCTAssertNil(session.pendingInterruptedRide)
        XCTAssertEqual(deleteFault.failureCount(), 1)

        _ = try await runtime.start(user: user, at: start.addingTimeInterval(100))
        clock.set(wall: start.addingTimeInterval(101), monotonic: 201)
        _ = try await runtime.ingest(
            fixtureFix(capturedAt: clock.wallValue, latitude: 39.9560),
            wallNow: clock.wallValue
        )
        let next = try await custody.persisted(
            owner: RecordingOwner(user: user),
            rideID: nextRideID
        )
        XCTAssertEqual(next.events.map(\.kind), [.start, .fix])
        let queueCallsAfterDiscard = await queue.callSnapshot()
        XCTAssertTrue(queueCallsAfterDiscard.isEmpty)
    }

    @MainActor
    private func waitForModel(
        timeout: Duration = .seconds(2),
        _ condition: @escaping @MainActor () -> Bool
    ) async throws {
        let clock = ContinuousClock()
        let deadline = clock.now.advanced(by: timeout)
        while !condition(), clock.now < deadline {
            try await Task.sleep(for: .milliseconds(10))
        }
        XCTAssertTrue(condition(), "timed out waiting for the production RecordingModel state")
    }

    private func makeRuntime(
        custody: FileLiveRideCustodyStore,
        queue: GateUploadQueue,
        clock: GateClock,
        ids: GateIDSequence,
        accountWorkPermitted: @escaping @Sendable (RecordingOwner) -> Bool = { _ in true }
    ) -> RideRecordingRuntime {
        RideRecordingRuntime(
            custody: custody,
            uploadQueue: queue,
            now: { clock.wallValue },
            monotonicNow: { clock.monotonicValue },
            makeID: { ids.next() },
            accountWorkPermitted: accountWorkPermitted
        )
    }

    private func ingestEligibleRide(
        runtime: RideRecordingRuntime,
        clock: GateClock,
        rideStart: Date? = nil
    ) async throws -> RecordingSessionProjection {
        let baseStart = rideStart ?? start
        var latest: RecordingSessionProjection?
        for index in 0...30 {
            let second = TimeInterval(index + 1)
            clock.set(wall: baseStart.addingTimeInterval(second), monotonic: 100 + second)
            latest = try await runtime.ingest(
                fixtureFix(
                    capturedAt: baseStart.addingTimeInterval(second),
                    latitude: 39.9500 + Double(index) * 0.00004,
                    speedMps: 5
                ),
                wallNow: clock.wallValue
            ).1
        }
        return try XCTUnwrap(latest)
    }

    private func fixtureFix(
        capturedAt: Date,
        latitude: Double,
        gpsAltitudeM: Double? = 100,
        relativeBarometerM: Double? = nil,
        heartRateBpm: Int? = nil,
        cadenceRpm: Int? = nil,
        powerWatts: Int? = nil,
        speedMps: Double? = 5
    ) -> RecordingSessionFix {
        RecordingSessionFix(
            gps: GPSObservation(
                timestamp: capturedAt,
                latitude: latitude,
                longitude: -75.1600,
                horizontalAccuracyM: 0.1,
                speedMps: speedMps,
                speedAccuracyMps: speedMps == nil ? nil : 0.2,
                courseDegrees: 0
            ),
            gpsAltitudeM: gpsAltitudeM,
            gpsVerticalAccuracyM: gpsAltitudeM == nil ? nil : 2,
            relativeBarometerM: relativeBarometerM,
            barometerTimestamp: relativeBarometerM == nil ? nil : capturedAt,
            heartRateBpm: heartRateBpm,
            cadenceRpm: cadenceRpm,
            powerObservation: powerWatts.map { PowerObservation(watts: $0, timestamp: capturedAt) }
        )
    }

    private func fixtureLocation(
        capturedAt: Date,
        latitude: Double,
        speedMps: Double = 5
    ) -> CLLocation {
        CLLocation(
            coordinate: CLLocationCoordinate2D(
                latitude: latitude,
                longitude: -75.1600
            ),
            altitude: 100,
            horizontalAccuracy: 0.1,
            verticalAccuracy: 2,
            course: 0,
            speed: speedMps,
            timestamp: capturedAt
        )
    }

    private func fixtureUser(id: String, wallet: String) -> User {
        User(
            id: id,
            wallet: wallet,
            username: nil,
            displayName: nil,
            avatarUrl: nil,
            email: nil,
            location: nil,
            preferredUnits: nil,
            totalRides: nil,
            totalDistanceKm: nil,
            totalElevationM: nil
        )
    }

    private func fixtureUploadJob(
        id: String,
        ownerID: String,
        ownerWallet: String,
        sourceBytes: Data,
        parserVersion: UInt32?,
        preliminaryRideHash: String?
    ) -> RideUploadJob {
        RideUploadJob(
            id: id,
            ownerID: ownerID,
            ownerWallet: ownerWallet,
            fileName: "Ride.gpx",
            fileType: "gpx",
            fileHash: FileRideUploadJobStore.sha256(sourceBytes),
            fileSize: sourceBytes.count,
            sourceFileName: "source.gpx",
            localSummary: LocalRideSummary(
                startedAt: start,
                distanceM: 1_000,
                elevationM: 100,
                durationS: 180
            ),
            createdAt: start,
            updatedAt: start,
            phase: .queued,
            attemptedServerHandoff: false,
            signedURL: nil,
            signedURLExpiresAt: nil,
            serverRideID: nil,
            authoritativeStatus: nil,
            attemptCount: 0,
            nextRetryAt: nil,
            lastError: nil,
            canRetry: false,
            revealState: .none,
            reveal: nil,
            parserVersion: parserVersion,
            preliminaryRideHash: preliminaryRideHash
        )
    }

    private func iso8601(_ date: Date) -> String {
        let formatter = ISO8601DateFormatter()
        formatter.formatOptions = [.withInternetDateTime]
        return formatter.string(from: date)
    }

    private func occurrences(of needle: String, in value: String) -> Int {
        value.components(separatedBy: needle).count - 1
    }

    private func strippingSwiftComments(from source: String) -> String {
        let characters = Array(source)
        var output = ""
        var index = 0
        var mode = GateSwiftLexMode.code
        var blockCommentDepth = 0

        while index < characters.count {
            let character = characters[index]
            let next = index + 1 < characters.count ? characters[index + 1] : nil
            let afterNext = index + 2 < characters.count ? characters[index + 2] : nil

            switch mode {
            case .code:
                if character == "/", next == "/" {
                    mode = .lineComment
                    index += 2
                } else if character == "/", next == "*" {
                    mode = .blockComment
                    blockCommentDepth = 1
                    index += 2
                } else if character == "\"", next == "\"", afterNext == "\"" {
                    output.append(contentsOf: "\"\"\"")
                    mode = .multilineString
                    index += 3
                } else {
                    output.append(character)
                    if character == "\"" { mode = .string }
                    index += 1
                }

            case .lineComment:
                if character == "\n" {
                    output.append(character)
                    mode = .code
                }
                index += 1

            case .blockComment:
                if character == "/", next == "*" {
                    blockCommentDepth += 1
                    index += 2
                } else if character == "*", next == "/" {
                    blockCommentDepth -= 1
                    index += 2
                    if blockCommentDepth == 0 { mode = .code }
                } else {
                    if character == "\n" { output.append(character) }
                    index += 1
                }

            case .string:
                output.append(character)
                if character == "\\", let next {
                    output.append(next)
                    index += 2
                } else {
                    if character == "\"" { mode = .code }
                    index += 1
                }

            case .multilineString:
                if character == "\"", next == "\"", afterNext == "\"" {
                    output.append(contentsOf: "\"\"\"")
                    mode = .code
                    index += 3
                } else {
                    output.append(character)
                    index += 1
                }
            }
        }
        return output
    }

    private func swiftStringLiterals(in source: String) -> [String] {
        let characters = Array(source)
        var literals: [String] = []
        var current = ""
        var index = 0
        var mode = GateSwiftLexMode.code

        while index < characters.count {
            let character = characters[index]
            let next = index + 1 < characters.count ? characters[index + 1] : nil
            let afterNext = index + 2 < characters.count ? characters[index + 2] : nil

            switch mode {
            case .code, .lineComment, .blockComment:
                if character == "\"", next == "\"", afterNext == "\"" {
                    current = ""
                    mode = .multilineString
                    index += 3
                } else if character == "\"" {
                    current = ""
                    mode = .string
                    index += 1
                } else {
                    index += 1
                }

            case .string:
                if character == "\\", let next {
                    current.append(character)
                    current.append(next)
                    index += 2
                } else if character == "\"" {
                    literals.append(current)
                    current = ""
                    mode = .code
                    index += 1
                } else {
                    current.append(character)
                    index += 1
                }

            case .multilineString:
                if character == "\"", next == "\"", afterNext == "\"" {
                    literals.append(current)
                    current = ""
                    mode = .code
                    index += 3
                } else {
                    current.append(character)
                    index += 1
                }
            }
        }
        return literals
    }

    private func allRegularFileData(in root: URL) throws -> Data {
        guard FileManager.default.fileExists(atPath: root.path) else { return Data() }
        let enumerator = try XCTUnwrap(
            FileManager.default.enumerator(
                at: root,
                includingPropertiesForKeys: [.isRegularFileKey],
                options: [.skipsHiddenFiles]
            )
        )
        var combined = Data()
        for case let url as URL in enumerator {
            if try url.resourceValues(forKeys: [.isRegularFileKey]).isRegularFile == true {
                combined.append(try Data(contentsOf: url))
            }
        }
        return combined
    }

    private func regularFileURLs(in root: URL) throws -> [URL] {
        guard FileManager.default.fileExists(atPath: root.path) else { return [] }
        let enumerator = try XCTUnwrap(
            FileManager.default.enumerator(
                at: root,
                includingPropertiesForKeys: [.isRegularFileKey],
                options: [.skipsHiddenFiles]
            )
        )
        var result: [URL] = []
        for case let url as URL in enumerator {
            if try url.resourceValues(forKeys: [.isRegularFileKey]).isRegularFile == true {
                result.append(url)
            }
        }
        return result
    }

    private func directoryURLs(in root: URL) throws -> [URL] {
        guard FileManager.default.fileExists(atPath: root.path) else { return [] }
        let enumerator = try XCTUnwrap(
            FileManager.default.enumerator(
                at: root,
                includingPropertiesForKeys: [.isDirectoryKey],
                options: [.skipsHiddenFiles]
            )
        )
        var result: [URL] = []
        for case let url as URL in enumerator {
            if try url.resourceValues(forKeys: [.isDirectoryKey]).isDirectory == true {
                result.append(url)
            }
        }
        return result
    }
}

private enum GateSwiftLexMode {
    case code
    case lineComment
    case blockComment
    case string
    case multilineString
}

private enum GateTestError: Error {
    case injectedFailure
    case uploadUnavailable
}

private final class GateClock: @unchecked Sendable {
    private let lock = NSLock()
    private var wall: Date
    private var monotonic: TimeInterval

    init(wall: Date, monotonic: TimeInterval) {
        self.wall = wall
        self.monotonic = monotonic
    }

    var wallValue: Date {
        lock.lock()
        defer { lock.unlock() }
        return wall
    }

    var monotonicValue: TimeInterval {
        lock.lock()
        defer { lock.unlock() }
        return monotonic
    }

    func set(wall: Date, monotonic: TimeInterval) {
        lock.lock()
        self.wall = wall
        self.monotonic = monotonic
        lock.unlock()
    }
}

private final class GateIDSequence: @unchecked Sendable {
    private let lock = NSLock()
    private var values: [String]

    init(_ values: [String]) {
        self.values = values
    }

    func next() -> String {
        lock.lock()
        defer { lock.unlock() }
        precondition(!values.isEmpty, "unexpected ride ID allocation")
        return values.removeFirst()
    }
}

private final class GateFinalizedEventFault: @unchecked Sendable {
    private let lock = NSLock()
    private var shouldFail = true

    func beforePublish(kind: RecordingCustodyEventKind, sequence: UInt64) throws {
        lock.lock()
        defer { lock.unlock() }
        if kind == .finalized, shouldFail {
            shouldFail = false
            throw GateTestError.injectedFailure
        }
    }
}

private final class GateSuspendEventFault: @unchecked Sendable {
    private let lock = NSLock()
    private var shouldFail = true

    func beforePublish(kind: RecordingCustodyEventKind, sequence: UInt64) throws {
        lock.lock()
        defer { lock.unlock() }
        if kind == .suspend, shouldFail {
            shouldFail = false
            throw GateTestError.injectedFailure
        }
    }
}

private final class GateFixEventPublishFault: @unchecked Sendable {
    private let lock = NSLock()
    private var shouldFail = true

    func beforePublish(kind: RecordingCustodyEventKind, sequence: UInt64) throws {
        lock.lock()
        defer { lock.unlock() }
        if kind == .fix, shouldFail {
            shouldFail = false
            throw GateTestError.injectedFailure
        }
    }
}

private final class GateBlockingFirstFixPublishFault: @unchecked Sendable {
    private let condition = NSCondition()
    private var fixPublishCount = 0
    private var firstBlocked = false
    private var firstReleased = false

    func beforePublish(kind: RecordingCustodyEventKind, sequence: UInt64) throws {
        guard kind == .fix else { return }
        condition.lock()
        fixPublishCount += 1
        guard fixPublishCount == 1 else {
            condition.unlock()
            return
        }
        firstBlocked = true
        condition.broadcast()
        while !firstReleased {
            condition.wait()
        }
        condition.unlock()
        throw GateTestError.injectedFailure
    }

    func waitUntilBlocked(timeout: TimeInterval) -> Bool {
        condition.lock()
        defer { condition.unlock() }
        let deadline = Date().addingTimeInterval(timeout)
        while !firstBlocked, !firstReleased {
            if !condition.wait(until: deadline) { break }
        }
        return firstBlocked
    }

    func releaseFirstFailure() {
        condition.lock()
        firstReleased = true
        condition.broadcast()
        condition.unlock()
    }
}

private actor GateAsyncBarrier {
    private var entered = false
    private var released = false
    private var entryWaiters: [CheckedContinuation<Void, Never>] = []
    private var releaseWaiters: [CheckedContinuation<Void, Never>] = []

    func wait() async {
        entered = true
        let waiters = entryWaiters
        entryWaiters.removeAll()
        waiters.forEach { $0.resume() }
        guard !released else { return }
        await withCheckedContinuation { continuation in
            releaseWaiters.append(continuation)
        }
    }

    func waitUntilEntered() async {
        guard !entered else { return }
        await withCheckedContinuation { continuation in
            entryWaiters.append(continuation)
        }
    }

    func hasEntered() -> Bool { entered }

    func release() {
        released = true
        let waiters = releaseWaiters
        releaseWaiters.removeAll()
        waiters.forEach { $0.resume() }
    }
}

private final class GateCaptureSensorSource: @unchecked Sendable {
    private let lock = NSLock()
    private var value: RecordingCaptureSensorSnapshot

    init(_ value: RecordingCaptureSensorSnapshot) {
        self.value = value
    }

    func set(_ value: RecordingCaptureSensorSnapshot) {
        lock.lock()
        self.value = value
        lock.unlock()
    }

    func snapshot() -> RecordingCaptureSensorSnapshot {
        lock.lock()
        defer { lock.unlock() }
        return value
    }
}

private final class GateFailFirstDiscardRemoveFault: @unchecked Sendable {
    private let lock = NSLock()
    private var armed = false
    private var failures = 0

    func arm() {
        lock.lock()
        armed = true
        lock.unlock()
    }

    func beforeRemove(directory: URL) throws {
        lock.lock()
        defer { lock.unlock() }
        guard armed else { return }
        armed = false
        failures += 1
        throw GateTestError.injectedFailure
    }

    func failureCount() -> Int {
        lock.lock()
        defer { lock.unlock() }
        return failures
    }
}

private final class GateAfterMoveDirectorySyncFault: @unchecked Sendable {
    private let lock = NSLock()
    private var armed = false
    private var failures = 0

    func arm() {
        lock.lock()
        armed = true
        lock.unlock()
    }

    func beforeSync(directory: URL) throws {
        lock.lock()
        defer { lock.unlock() }
        guard armed, failures == 0, directory.lastPathComponent == "events" else {
            return
        }
        failures += 1
        throw GateTestError.injectedFailure
    }

    func failureCount() -> Int {
        lock.lock()
        defer { lock.unlock() }
        return failures
    }
}

private final class GateEventKindAfterMoveSyncFault: @unchecked Sendable {
    private let lock = NSLock()
    private let target: RecordingCustodyEventKind
    private var armed = false
    private var targetPublished = false
    private var failures = 0

    init(target: RecordingCustodyEventKind) {
        self.target = target
    }

    func arm() {
        lock.lock()
        armed = true
        lock.unlock()
    }

    func beforePublish(kind: RecordingCustodyEventKind, sequence: UInt64) {
        lock.lock()
        if armed, kind == target {
            armed = false
            targetPublished = true
        }
        lock.unlock()
    }

    func beforeSync(directory: URL) throws {
        lock.lock()
        defer { lock.unlock() }
        guard targetPublished,
              failures == 0,
              directory.lastPathComponent == "events"
        else { return }
        targetPublished = false
        failures += 1
        throw GateTestError.injectedFailure
    }

    func failureCount() -> Int {
        lock.lock()
        defer { lock.unlock() }
        return failures
    }
}

private final class GateNextParentDirectorySyncFault: @unchecked Sendable {
    private let lock = NSLock()
    private var armed = false
    private var failures = 0

    func arm() {
        lock.lock()
        armed = true
        lock.unlock()
    }

    func beforeSync(directory: URL) throws {
        lock.lock()
        defer { lock.unlock() }
        guard armed,
              directory.lastPathComponent != "events"
        else { return }
        armed = false
        failures += 1
        throw GateTestError.injectedFailure
    }

    func failureCount() -> Int {
        lock.lock()
        defer { lock.unlock() }
        return failures
    }
}

private final class GateKeyLoaderProbe: @unchecked Sendable {
    private let lock = NSLock()
    private let key: Data
    private var observedExistingValues: [Bool] = []

    init(key: Data) {
        self.key = key
    }

    func load(existingStore: Bool) -> Data {
        lock.lock()
        observedExistingValues.append(existingStore)
        lock.unlock()
        return key
    }

    func snapshot() -> [Bool] {
        lock.lock()
        defer { lock.unlock() }
        return observedExistingValues
    }
}

private final class GateMissingKeyLoaderProbe: @unchecked Sendable {
    private let lock = NSLock()
    private var observedExistingValues: [Bool] = []

    func load(existingStore: Bool) throws -> Data {
        lock.lock()
        observedExistingValues.append(existingStore)
        lock.unlock()
        throw LiveRideCustodyError.keyUnavailable
    }

    func snapshot() -> [Bool] {
        lock.lock()
        defer { lock.unlock() }
        return observedExistingValues
    }
}

private final class GateEventPublishBarrier: @unchecked Sendable {
    private let condition = NSCondition()
    private let blockingKind: RecordingCustodyEventKind
    private var isBlocked = false
    private var isReleased = false
    private var kinds: [RecordingCustodyEventKind] = []

    init(blocking kind: RecordingCustodyEventKind) {
        blockingKind = kind
    }

    func beforePublish(kind: RecordingCustodyEventKind, sequence: UInt64) throws {
        condition.lock()
        kinds.append(kind)
        guard kind == blockingKind, !isReleased else {
            condition.unlock()
            return
        }
        isBlocked = true
        condition.broadcast()
        while !isReleased {
            condition.wait()
        }
        condition.unlock()
    }

    func waitUntilBlocked(timeout: TimeInterval) -> Bool {
        condition.lock()
        defer { condition.unlock() }
        let deadline = Date().addingTimeInterval(timeout)
        while !isBlocked, !isReleased {
            if !condition.wait(until: deadline) { break }
        }
        return isBlocked
    }

    func release() {
        condition.lock()
        isReleased = true
        condition.broadcast()
        condition.unlock()
    }

    func publishedKinds() -> [RecordingCustodyEventKind] {
        condition.lock()
        defer { condition.unlock() }
        return kinds
    }
}

private actor GateUploadQueue: FirstPartyRideUploadQueuing {
    struct Call: Equatable, Sendable {
        let owner: RecordingOwner
        let jobID: String
        let fileName: String
        let sourceBytes: Data
        let summary: LocalRideSummary
        let parserVersion: UInt32
        let preliminaryRideHash: String
    }

    private var failuresRemaining: Int
    private var calls: [Call] = []

    init(failuresRemaining: Int = 0) {
        self.failuresRemaining = failuresRemaining
    }

    func enqueueFirstParty(
        owner: RecordingOwner,
        jobID: String,
        fileName: String,
        sourceBytes: Data,
        summary: LocalRideSummary,
        parserVersion: UInt32,
        preliminaryRideHash: String
    ) throws -> RideUploadJob {
        calls.append(
            Call(
                owner: owner,
                jobID: jobID,
                fileName: fileName,
                sourceBytes: sourceBytes,
                summary: summary,
                parserVersion: parserVersion,
                preliminaryRideHash: preliminaryRideHash
            )
        )
        if failuresRemaining > 0 {
            failuresRemaining -= 1
            throw GateTestError.uploadUnavailable
        }
        return RideUploadJob(
            id: jobID,
            ownerID: owner.id,
            ownerWallet: owner.wallet,
            fileName: fileName,
            fileType: "gpx",
            fileHash: FileRideUploadJobStore.sha256(sourceBytes),
            fileSize: sourceBytes.count,
            sourceFileName: "source.gpx",
            localSummary: summary,
            createdAt: summary.startedAt,
            updatedAt: summary.startedAt,
            phase: .queued,
            attemptedServerHandoff: false,
            signedURL: nil,
            signedURLExpiresAt: nil,
            serverRideID: nil,
            authoritativeStatus: nil,
            attemptCount: 0,
            nextRetryAt: nil,
            lastError: nil,
            canRetry: false,
            revealState: .none,
            reveal: nil,
            parserVersion: parserVersion,
            preliminaryRideHash: preliminaryRideHash
        )
    }

    func callSnapshot() -> [Call] {
        calls
    }
}

private actor GateNoNetworkRideTransfer: RideFileTransferring {
    private var calls = 0

    func isActive(jobID: String) -> Bool { false }

    func persistedBodyJobIDs() async throws -> Set<String> { [] }

    func cancel(jobIDs: Set<String>) async throws {}

    func upload(
        jobID: String,
        signedURL: String,
        sourceURL: URL,
        fileName: String
    ) throws {
        calls += 1
        throw GateTestError.uploadUnavailable
    }

    func callCount() -> Int { calls }
}

private actor GateImmediateReconcileProbe {
    struct Call: Equatable, Sendable {
        let jobID: String
        let ownerID: String
    }

    private var calls: [Call] = []
    private var enteredWaiters: [CheckedContinuation<Void, Never>] = []
    private var releaseWaiter: CheckedContinuation<Void, Never>?
    private var releaseRequested = false
    private var finished = false
    private var finishedWaiters: [CheckedContinuation<Void, Never>] = []

    func reconcile(jobID: String, ownerID: String) async {
        calls.append(Call(jobID: jobID, ownerID: ownerID))
        let waiters = enteredWaiters
        enteredWaiters.removeAll()
        waiters.forEach { $0.resume() }
        await withCheckedContinuation { continuation in
            if releaseRequested {
                continuation.resume()
            } else {
                releaseWaiter = continuation
            }
        }
        finished = true
        let completionWaiters = finishedWaiters
        finishedWaiters.removeAll()
        completionWaiters.forEach { $0.resume() }
    }

    func waitUntilEntered() async {
        guard calls.isEmpty else { return }
        await withCheckedContinuation { continuation in
            enteredWaiters.append(continuation)
        }
    }

    func release() {
        releaseRequested = true
        releaseWaiter?.resume()
        releaseWaiter = nil
    }

    func waitUntilFinished() async {
        guard !finished else { return }
        await withCheckedContinuation { continuation in
            finishedWaiters.append(continuation)
        }
    }

    func snapshot() -> [Call] { calls }
    func hasFinished() -> Bool { finished }
}

private actor GateAppSessionUploadRuntime: AppSessionRideUploadRuntime {
    private var claimedOwners: [String] = []

    func activate(user: User?) async {}
    func reconcileAll(owner: RecordingOwner) async {}

    func claimNextReveal(owner: RecordingOwner) async -> PendingRideReveal? {
        claimedOwners.append(owner.id)
        return nil
    }

    func acknowledgeReveal(
        _ pending: PendingRideReveal,
        owner: RecordingOwner
    ) async -> Bool {
        false
    }

    func claimCount() -> Int {
        claimedOwners.count
    }
}

private actor GateAppSessionRecordingRuntime: AppSessionRideRecordingRuntime {
    private var activations = 0

    func activate(user: User?) async throws -> InterruptedRideRecovery? {
        activations += 1
        if activations == 1 {
            throw LiveRideCustodyError.keyUnavailable
        }
        return nil
    }

    func saveRecovery(_ recovery: InterruptedRideRecovery) async throws -> FinalizedRecording {
        throw GateTestError.injectedFailure
    }

    func discard(_ recovery: InterruptedRideRecovery) async throws {
        throw GateTestError.injectedFailure
    }

    func activationCount() -> Int {
        activations
    }
}

private actor GateFailOnceThenLiveRecordingRuntime: AppSessionRideRecordingRuntime {
    private let runtime: RideRecordingRuntime
    private var shouldFailActivation = true

    init(runtime: RideRecordingRuntime) {
        self.runtime = runtime
    }

    func activate(user: User?) async throws -> InterruptedRideRecovery? {
        if shouldFailActivation {
            shouldFailActivation = false
            throw LiveRideCustodyError.keyUnavailable
        }
        return try await runtime.activate(user: user)
    }

    func saveRecovery(_ recovery: InterruptedRideRecovery) async throws -> FinalizedRecording {
        try await runtime.saveRecovery(recovery)
    }

    func discard(_ recovery: InterruptedRideRecovery) async throws {
        try await runtime.discard(recovery)
    }

    func localSavedRides(user: User) async throws -> [LocalSavedRide] {
        try await runtime.localSavedRides(user: user)
    }
}

private actor GateAppSessionLocalSavedRecordingRuntime: AppSessionRideRecordingRuntime {
    private let saved: [LocalSavedRide]
    private var loadedOwners: [RecordingOwner] = []

    init(saved: [LocalSavedRide]) {
        self.saved = saved
    }

    func activate(user: User?) async throws -> InterruptedRideRecovery? { nil }

    func saveRecovery(_ recovery: InterruptedRideRecovery) async throws -> FinalizedRecording {
        throw GateTestError.injectedFailure
    }

    func discard(_ recovery: InterruptedRideRecovery) async throws {
        throw GateTestError.injectedFailure
    }

    func localSavedRides(user: User) async throws -> [LocalSavedRide] {
        loadedOwners.append(RecordingOwner(user: user))
        return saved
    }

    func loadedOwnersSnapshot() -> [RecordingOwner] {
        loadedOwners
    }
}
