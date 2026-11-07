import CoreLocation
import XCTest
@testable import BoulderRoller

/// Batch C item 3 (bead boulderroller-v2-f4acp.1.8): every permission ask
/// happens at its moment of demonstrated need. These tests pin the two
/// codified rules — Record-open Bluetooth activation and the (dormant)
/// Location-Always upgrade timing — so the choreography cannot regress
/// silently.
final class PermissionChoreographyTests: XCTestCase {
    // MARK: Bluetooth at Record open

    /// A rider with no paired sensors has demonstrated no Bluetooth need at
    /// Record: the central must not come up (its first creation triggers the
    /// system Bluetooth prompt, which would stack onto the location ask).
    func testRecordOpenWithoutPairedDevicesNeverActivatesBluetooth() {
        XCTAssertFalse(
            PermissionChoreography.shouldActivateSensorsAtRecordOpen(pairedDeviceCount: 0)
        )
    }

    /// Paired devices are the demonstrated need — reconnect them for the
    /// ride. (Their pairing already carried the system ask in the Sensors
    /// room, so no new prompt stacks here.)
    func testRecordOpenWithPairedDevicesReconnects() {
        XCTAssertTrue(
            PermissionChoreography.shouldActivateSensorsAtRecordOpen(pairedDeviceCount: 1)
        )
        XCTAssertTrue(
            PermissionChoreography.shouldActivateSensorsAtRecordOpen(pairedDeviceCount: 3)
        )
    }

    // MARK: Locked-screen recording + Location-Always upgrade

    /// Screen locking is part of the ordinary recording journey, not a
    /// future permission seam. The production capability flag must stay on.
    func testLockedScreenRecordingCapabilityIsShipped() {
        XCTAssertTrue(PermissionChoreography.lockedScreenRecordingShipped)
    }

    /// Locked-screen continuity must not silently arm the broader Always
    /// permission. Automatic relaunch remains a separate future capability.
    func testAlwaysUpgradeStaysDormantWithoutRelaunchCapability() {
        XCTAssertFalse(
            PermissionChoreography.shouldOfferAlwaysUpgrade(
                status: .authorizedWhenInUse,
                hasCompletedWhileInUseRecording: true
            )
        )
    }

    /// The built app must declare every privacy key and background mode used
    /// by the production recorder. Missing motion copy is a TCC crash; setting
    /// `allowsBackgroundLocationUpdates` without `location` is also fatal.
    func testBuiltAppDeclaresRecorderPrivacyAndBackgroundModes() throws {
        let info = try XCTUnwrap(Bundle.main.infoDictionary)
        let motion = try XCTUnwrap(info["NSMotionUsageDescription"] as? String)
        let backgroundLocation = try XCTUnwrap(
            info["NSLocationAlwaysAndWhenInUseUsageDescription"] as? String
        )
        let modes = try XCTUnwrap(info["UIBackgroundModes"] as? [String])

        XCTAssertFalse(motion.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty)
        XCTAssertFalse(
            backgroundLocation.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
        )
        XCTAssertTrue(modes.contains("location"))
        XCTAssertTrue(modes.contains("processing"))
    }

    /// Background delivery is enabled only during an active capture and is
    /// fully disabled at every stop boundary.
    func testLocationManagerBackgroundConfigurationIsSymmetric() {
        let manager = CLLocationManager()

        RecordingLocationHardwarePolicy.configureForActiveCapture(manager)
        XCTAssertTrue(manager.allowsBackgroundLocationUpdates)
        XCTAssertFalse(manager.pausesLocationUpdatesAutomatically)
        XCTAssertTrue(manager.showsBackgroundLocationIndicator)
        XCTAssertEqual(manager.activityType, .fitness)

        RecordingLocationHardwarePolicy.configureForIdle(manager)
        XCTAssertFalse(manager.allowsBackgroundLocationUpdates)
        XCTAssertFalse(manager.showsBackgroundLocationIndicator)
    }

    /// The ratified timing once the capability ships: only after a first
    /// successful While-Using recording, and only from the While-Using
    /// state (the upgrade is surfaced at the next Record open).
    func testAlwaysUpgradeTimingOnceCapabilityShips() {
        // Qualified: capability + completed recording + currently WhenInUse.
        XCTAssertTrue(
            PermissionChoreography.shouldOfferAlwaysUpgrade(
                status: .authorizedWhenInUse,
                hasCompletedWhileInUseRecording: true,
                alwaysLocationRelaunchShipped: true
            )
        )
        // Never before a first successful while-in-use recording.
        XCTAssertFalse(
            PermissionChoreography.shouldOfferAlwaysUpgrade(
                status: .authorizedWhenInUse,
                hasCompletedWhileInUseRecording: false,
                alwaysLocationRelaunchShipped: true
            )
        )
        // .notDetermined belongs to the While-Using ask, never the upgrade.
        XCTAssertFalse(
            PermissionChoreography.shouldOfferAlwaysUpgrade(
                status: .notDetermined,
                hasCompletedWhileInUseRecording: true,
                alwaysLocationRelaunchShipped: true
            )
        )
        // Denied riders get the truthful Settings hand-off, not a re-ask.
        XCTAssertFalse(
            PermissionChoreography.shouldOfferAlwaysUpgrade(
                status: .denied,
                hasCompletedWhileInUseRecording: true,
                alwaysLocationRelaunchShipped: true
            )
        )
        // Already Always: nothing to offer.
        XCTAssertFalse(
            PermissionChoreography.shouldOfferAlwaysUpgrade(
                status: .authorizedAlways,
                hasCompletedWhileInUseRecording: true,
                alwaysLocationRelaunchShipped: true
            )
        )
    }
}
