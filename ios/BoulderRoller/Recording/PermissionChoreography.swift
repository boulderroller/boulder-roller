import CoreLocation
import Foundation

/// Point-of-need permission choreography (bead `boulderroller-v2-f4acp.1.8`).
///
/// Law: every system permission ask happens at the rider action that
/// demonstrates the need — never a first-launch wall, never a stacked pile
/// of prompts. The concrete moments:
///
/// - **Location (While Using)** — at the first Record tap. An actively
///   recording ride continues when the screen locks; Apple extends this
///   foreground-started authorization while the background indicator is on.
///   `RecordingModel.requestAndStart()` asks exactly when `.notDetermined`,
///   directly on the recording surface. No pre-prompt context screen exists:
///   the constitution bans invented copy (Law 9), so the OS prompt at the
///   right moment *is* the choreography. Denied/restricted renders the
///   truthful blocked state with a Settings hand-off.
///
/// - **Bluetooth** — at the first entry to the Sensors room (scanning is the
///   demonstrated need). At Record open the central comes up only when the
///   rider has paired devices to reconnect; a rider with no sensors never
///   sees a Bluetooth prompt from Record.
///
/// - **Notifications** — implemented per the ratified seam (bead
///   `boulderroller-v2-odmi6.8`, `PushAskPolicy` + `PushRegistrar`): the
///   one system ask happens when the first settlement or displacement
///   becomes *possible* for this rider — the first confirmed deposit
///   (DepositSheet `.done`) or the first Leaderboard-entry ceremony's Done —
///   never at launch, never before the rider holds anything a push could
///   be about. Deep-link targets shipped first; denial leaves both
///   destinations as ordinary in-app surfaces (no dead control, no
///   re-prompt nagging). Delivery itself waits at the key boundary: team
///   signing + the APNs p8 on the send worker.
///
/// - **Location Always** — not needed merely to lock the screen during an
///   active ride. The seam below remains reserved for a later service that
///   can relaunch location collection after process termination. It is never
///   part of the first-record permission stack.
enum PermissionChoreography {
    /// Record-open Bluetooth rule: reconnecting paired sensors is the only
    /// demonstrated need at Record. First-ever activation (and therefore the
    /// system Bluetooth ask) belongs to the Sensors room.
    static func shouldActivateSensorsAtRecordOpen(pairedDeviceCount: Int) -> Bool {
        pairedDeviceCount > 0
    }

    /// The production app declares and exercises continuous background
    /// location for a foreground-started ride. This is the locked-screen
    /// capability, independent of any later Always-only relaunch feature.
    static let lockedScreenRecordingReleased = true

    /// Automatic location relaunch after the app is terminated is a distinct
    /// capability. Keep the broader Always permission dormant until that
    /// service exists and has its own physical proof.
    static let alwaysLocationRelaunchReleased = false

    /// The Always-upgrade moment, encoded ahead of the capability: offer it
    /// only after at least one successful While-Using recording (the rider
    /// has demonstrated the workflow the upgrade serves), only at the next
    /// Record open (the surface the permission belongs to), and only once
    /// automatic relaunch actually ships. Never at launch, never mid-ride,
    /// never while `.notDetermined` (the While-Using ask owns that state).
    static func shouldOfferAlwaysUpgrade(
        status: CLAuthorizationStatus,
        hasCompletedWhileInUseRecording: Bool,
        alwaysLocationRelaunchReleased: Bool = Self.alwaysLocationRelaunchReleased
    ) -> Bool {
        guard alwaysLocationRelaunchReleased else { return false }
        guard hasCompletedWhileInUseRecording else { return false }
        return status == .authorizedWhenInUse
    }
}

/// The Core Location settings that make one foreground-started fitness ride
/// continue through screen lock. Enabling background delivery without the
/// matching Info.plist mode is fatal, so the built-bundle test pins both sides.
enum RecordingLocationHardwarePolicy {
    static func configureForActiveCapture(_ manager: CLLocationManager) {
        manager.activityType = .fitness
        manager.pausesLocationUpdatesAutomatically = false
        manager.allowsBackgroundLocationUpdates = true
        manager.showsBackgroundLocationIndicator = true
    }

    static func configureForIdle(_ manager: CLLocationManager) {
        manager.allowsBackgroundLocationUpdates = false
        manager.showsBackgroundLocationIndicator = false
    }
}
