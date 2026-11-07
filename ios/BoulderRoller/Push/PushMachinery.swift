import Foundation
import Observation
import UserNotifications
#if canImport(UIKit)
import UIKit
#endif

/// APNs machinery to the key boundary (bead `boulderroller-v2-odmi6.8`,
/// L1.08 + LIST THREE item 6).
///
/// Law 7: pushes, not rooms. Exactly two notification categories exist —
/// settlement and displacement — and each deep-links to its existing
/// surface (Settlements room; climb sheet). Unknown categories fail closed.
///
/// Ask-timing (the ratified choreography seam in
/// `PermissionChoreography.swift`): the system ask happens at the moment
/// the first settlement or displacement becomes POSSIBLE for this rider —
/// the first confirmed deposit, or the first Leaderboard entry — after the
/// ceremony, never at launch, never before the rider holds anything a push
/// could be about. Denial leaves no dead control: both destinations remain
/// plain in-app surfaces.
///
/// Key boundary: everything here runs without the founder's Apple keys.
/// Real delivery additionally needs (1) team signing so the aps-environment
/// entitlement is provisioned on device, and (2) the APNs .p8 on the
/// backend send worker. Until then registration is attempted, tokens POST
/// to the backend, and the send worker stays flagged off/dry-run.

// MARK: - Deep links (fail closed)

enum PushDeepLink: Equatable, Sendable, Identifiable {
    case settlements
    case climb(String)

    var id: String {
        switch self {
        case .settlements: return "settlements"
        case let .climb(id): return "climb-\(id)"
        }
    }

    /// Parse an APNs userInfo dictionary. Contract (mirrored by the backend
    /// payload builder): `{"br": {"category": "settlement"}}` or
    /// `{"br": {"category": "displacement", "climb_id": "<id>"}}`.
    /// Anything else — unknown category, missing climb id, absent envelope —
    /// is nil: an unroutable push opens nothing rather than something wrong.
    static func parse(userInfo: [AnyHashable: Any]) -> PushDeepLink? {
        guard let br = userInfo["br"] as? [String: Any],
              let category = br["category"] as? String
        else { return nil }
        switch category {
        case "settlement":
            return .settlements
        case "displacement":
            guard let climbID = br["climb_id"].map({ "\($0)" }),
                  !climbID.isEmpty, climbID != "<null>"
            else { return nil }
            return .climb(climbID)
        default:
            return nil
        }
    }
}

// MARK: - Ask policy (pure, tested)

enum PushAskPolicy {
    /// The two ratified moments. Nothing else may trigger the system ask.
    enum Trigger: Equatable, Sendable {
        /// First deposit confirmed — settlements become possible.
        case firstDepositConfirmed
        /// First Leaderboard entry ceremony completed — displacement
        /// becomes possible.
        case firstLeaderboardEntry
    }

    /// Ask exactly while the system state is undetermined. Denied means
    /// denied — no re-prompt nagging; granted means already registered.
    static func shouldRequestAuthorization(
        trigger: Trigger?,
        authorizationStatus: UNAuthorizationStatus
    ) -> Bool {
        guard trigger != nil else { return false }
        return authorizationStatus == .notDetermined
    }

    /// Re-register for a token on session start only when the rider already
    /// granted authorization earlier (token rotation replay) — never as a
    /// first ask.
    static func shouldRegisterAtSessionStart(
        authorizationStatus: UNAuthorizationStatus
    ) -> Bool {
        switch authorizationStatus {
        case .authorized, .provisional, .ephemeral: return true
        case .notDetermined, .denied: return false
        @unknown default: return false
        }
    }

    /// APNs environment string recorded with the device token. Sandbox vs
    /// production APNs follows the signing profile; until team signing
    /// exists only DEBUG/simulator builds run, which map to sandbox.
    static func apnsEnvironment(isDebugBuild: Bool) -> String {
        isDebugBuild ? "sandbox" : "production"
    }
}

// MARK: - Router (notification tap → surface)

/// Holds the tapped notification's destination until a signed-in feed can
/// present it. Pushes arriving signed out wait for the session — the link
/// is consumed exactly once.
@MainActor
@Observable
final class PushRouter {
    static let shared = PushRouter()

    var pending: PushDeepLink?
    @ObservationIgnored private let admitsRoute: @Sendable () -> Bool

    init(admitsRoute: @escaping @Sendable () -> Bool = {
        AccountDeletionLocalFence.permitsCachedOwnerAccountWork
    }) {
        self.admitsRoute = admitsRoute
    }

    func route(userInfo: [AnyHashable: Any]) {
        guard admitsRoute() else { return }
        guard let link = PushDeepLink.parse(userInfo: userInfo) else { return }
        pending = link
    }

    func clearAccountData() {
        pending = nil
    }
}

// MARK: - Registrar (system ask + APNs registration + token POST)

@MainActor
enum PushRegistrar {
    /// The ratified-moment entry point. Safe to call repeatedly; the policy
    /// and the system's own authorization state make it idempotent.
    static func maybeAsk(_ trigger: PushAskPolicy.Trigger) {
        Task {
            let settings = await UNUserNotificationCenter.current().notificationSettings()
            if PushAskPolicy.shouldRequestAuthorization(
                trigger: trigger, authorizationStatus: settings.authorizationStatus
            ) {
                let granted = (try? await UNUserNotificationCenter.current()
                    .requestAuthorization(options: [.alert, .sound, .badge])) ?? false
                if granted {
                    UIApplication.shared.registerForRemoteNotifications()
                }
                // Denied: nothing else happens — no fake registration, no
                // dead control; Settlements and climb sheets stay reachable.
            } else if PushAskPolicy.shouldRegisterAtSessionStart(
                authorizationStatus: settings.authorizationStatus
            ) {
                UIApplication.shared.registerForRemoteNotifications()
            }
        }
    }

    /// Session-start replay: refresh the token registration only for riders
    /// who already granted authorization.
    static func registerIfPreviouslyAuthorized() {
        Task {
            let settings = await UNUserNotificationCenter.current().notificationSettings()
            if PushAskPolicy.shouldRegisterAtSessionStart(
                authorizationStatus: settings.authorizationStatus
            ) {
                UIApplication.shared.registerForRemoteNotifications()
            }
        }
    }

    /// APNs handed the app a token — record it with the backend.
    static func handleDeviceToken(_ tokenData: Data) {
        // Operator kill switch (L3.04): registration proceeds unless the
        // capability is explicitly disabled — a status blip never silently
        // breaks pushes.
        guard MobileCapabilityStore.shared.current()
            .allowsUnlessDisabled(.pushRegistration)
        else {
            BRLog.push.log("token registration skipped: capability disabled")
            return
        }
        BRLog.push.log("registering device token with backend")
        let token = tokenData.map { String(format: "%02x", $0) }.joined()
        #if DEBUG
        let environment = PushAskPolicy.apnsEnvironment(isDebugBuild: true)
        #else
        let environment = PushAskPolicy.apnsEnvironment(isDebugBuild: false)
        #endif
        Task {
            try? await APIClient.shared.registerPushDevice(
                token: token, environment: environment
            )
        }
    }

}

// MARK: - UNUserNotificationCenter delegate

final class PushNotificationDelegate: NSObject, UNUserNotificationCenterDelegate {
    static let shared = PushNotificationDelegate()

    /// Rider tapped a delivered notification: route it.
    func userNotificationCenter(
        _ center: UNUserNotificationCenter,
        didReceive response: UNNotificationResponse,
        withCompletionHandler completionHandler: @escaping () -> Void
    ) {
        let userInfo = response.notification.request.content.userInfo
        Task { @MainActor in
            PushRouter.shared.route(userInfo: userInfo)
            completionHandler()
        }
    }

    /// Foreground delivery: show the system banner — the app deliberately
    /// has no in-app notification surface to duplicate it (Law 7).
    func userNotificationCenter(
        _ center: UNUserNotificationCenter,
        willPresent notification: UNNotification,
        withCompletionHandler completionHandler: @escaping (UNNotificationPresentationOptions) -> Void
    ) {
        completionHandler([.banner, .sound])
    }
}
