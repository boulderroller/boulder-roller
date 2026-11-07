import CoreLocation
import Foundation
import OSLog
import UserNotifications

/// The app's os_log categories (L3.10). One subsystem, named lanes — the
/// diagnostics bundle reads exactly these back through OSLogStore.
enum BRLog {
    static let subsystem = "com.boulderroller.app"

    static let session = Logger(subsystem: subsystem, category: "session")
    static let upload = Logger(subsystem: subsystem, category: "upload")
    static let recording = Logger(subsystem: subsystem, category: "recording")
    static let money = Logger(subsystem: subsystem, category: "money")
    static let push = Logger(subsystem: subsystem, category: "push")
    static let api = Logger(subsystem: subsystem, category: "api")
}

/// Pure redaction over diagnostic text (L3.10): tokens, emails, wallet
/// addresses, long hashes, coordinates, and ride filenames never leave the
/// device. Kept as one testable function so the exclusion proof and the
/// production path are the same code.
enum DiagnosticRedactor {
    /// Order matters: broader secrets (bearer blobs, JWTs) go before the
    /// generic base58/hex sweeps so counts attribute sensibly.
    private static let rules: [(kind: String, pattern: String)] = [
        ("token", #"Bearer\s+\S+"#),
        ("token", #"eyJ[A-Za-z0-9_\-\.]{8,}"#),
        ("email", #"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}"#),
        ("ride-file", #"[\w\-/\.]+\.(?i:gpx|fit|tcx)"#),
        ("coordinates", #"-?\d{1,3}\.\d{3,}\s*,\s*-?\d{1,3}\.\d{3,}"#),
        ("hash", #"\b[0-9a-fA-F]{40,}\b"#),
        ("wallet", #"\b[1-9A-HJ-NP-Za-km-z]{32,44}\b"#),
    ]

    /// Returns the scrubbed text plus per-kind redaction counts.
    static func scrub(_ text: String) -> (text: String, counts: [String: Int]) {
        var output = text
        var counts: [String: Int] = [:]
        for rule in rules {
            guard let regex = try? NSRegularExpression(pattern: rule.pattern) else {
                continue
            }
            let range = NSRange(output.startIndex..., in: output)
            let hits = regex.numberOfMatches(in: output, range: range)
            guard hits > 0 else { continue }
            counts[rule.kind, default: 0] += hits
            output = regex.stringByReplacingMatches(
                in: output,
                range: range,
                withTemplate: "[redacted-\(rule.kind)]"
            )
        }
        return (output, counts)
    }
}

/// The rider-shareable support bundle: bounded, offline-buildable, and
/// scrubbed through `DiagnosticRedactor` with the redaction counts stated
/// inside the bundle itself.
struct DiagnosticsBundle: Codable, Equatable {
    static let maxLogEntries = 200

    let createdAt: String
    let appBuild: String
    let contractVersion: String
    let deviceModel: String
    let osVersion: String
    let locationAuthorization: String
    let notificationAuthorization: String
    let connectivity: String
    let capabilityVerdicts: [String: String]
    let recentLogs: [String]
    /// Per-kind counts of what was removed — the redaction report.
    let redactions: [String: Int]

    /// Assemble from raw parts; every free-text line passes the redactor.
    static func assemble(
        appBuild: String,
        deviceModel: String,
        osVersion: String,
        locationAuthorization: String,
        notificationAuthorization: String,
        connectivity: String,
        capabilityVerdicts: [String: String],
        rawLogs: [String],
        now: Date = .now
    ) -> DiagnosticsBundle {
        var counts: [String: Int] = [:]
        let scrubbedLogs = rawLogs.suffix(maxLogEntries).map { line -> String in
            let result = DiagnosticRedactor.scrub(line)
            counts.merge(result.counts, uniquingKeysWith: +)
            return result.text
        }
        return DiagnosticsBundle(
            createdAt: Format.isoParser.string(from: now),
            appBuild: appBuild,
            contractVersion: ClientContract.contractVersion,
            deviceModel: deviceModel,
            osVersion: osVersion,
            locationAuthorization: locationAuthorization,
            notificationAuthorization: notificationAuthorization,
            connectivity: connectivity,
            capabilityVerdicts: capabilityVerdicts,
            recentLogs: Array(scrubbedLogs),
            redactions: counts
        )
    }

    var asJSON: String {
        let encoder = JSONEncoder()
        encoder.outputFormatting = [.prettyPrinted, .sortedKeys]
        guard let data = try? encoder.encode(self),
              let text = String(data: data, encoding: .utf8)
        else { return "{}" }
        return text
    }
}

/// Live collection: reads the app's own recent os_log entries and the
/// current permission/connectivity states. Works offline by construction.
enum DiagnosticsCollector {
    @MainActor
    static func collect(session: AppSession) async -> DiagnosticsBundle {
        let build = Bundle.main.object(
            forInfoDictionaryKey: "CFBundleVersion"
        ) as? String ?? "0"

        let notificationSettings = await UNUserNotificationCenter
            .current().notificationSettings()

        let policy = MobileCapabilityStore.shared.current()
        let verdicts = Dictionary(
            uniqueKeysWithValues: MobileCapabilityPolicy.Capability.allCases.map {
                (String(describing: $0), String(describing: policy.verdict($0)))
            }
        )

        return DiagnosticsBundle.assemble(
            appBuild: build,
            deviceModel: deviceModelIdentifier(),
            osVersion: ProcessInfo.processInfo.operatingSystemVersionString,
            locationAuthorization: describe(
                CLLocationManager().authorizationStatus
            ),
            notificationAuthorization: describe(
                notificationSettings.authorizationStatus
            ),
            connectivity: String(describing: session.connectivity),
            capabilityVerdicts: verdicts,
            rawLogs: recentOwnLogs()
        )
    }

    /// The app's own recent log lines from the BRLog subsystem (best
    /// effort; an unreadable store yields an explicit line, not silence).
    static func recentOwnLogs(sinceMinutes: Double = 60) -> [String] {
        do {
            let store = try OSLogStore(scope: .currentProcessIdentifier)
            let position = store.position(date: .now.addingTimeInterval(-sinceMinutes * 60))
            let entries = try store.getEntries(at: position)
            return entries.compactMap { entry -> String? in
                guard let log = entry as? OSLogEntryLog,
                      log.subsystem == BRLog.subsystem
                else { return nil }
                let stamp = Format.isoParser.string(from: log.date)
                return "\(stamp) [\(log.category)] \(log.composedMessage)"
            }
        } catch {
            return ["log store unavailable: \(error.localizedDescription)"]
        }
    }

    private static func deviceModelIdentifier() -> String {
        var systemInfo = utsname()
        uname(&systemInfo)
        return withUnsafeBytes(of: &systemInfo.machine) { buffer in
            String(decoding: buffer.prefix(while: { $0 != 0 }), as: UTF8.self)
        }
    }

    private static func describe(_ status: CLAuthorizationStatus) -> String {
        switch status {
        case .notDetermined: "notDetermined"
        case .restricted: "restricted"
        case .denied: "denied"
        case .authorizedAlways: "authorizedAlways"
        case .authorizedWhenInUse: "authorizedWhenInUse"
        @unknown default: "unknown"
        }
    }

    private static func describe(_ status: UNAuthorizationStatus) -> String {
        switch status {
        case .notDetermined: "notDetermined"
        case .denied: "denied"
        case .authorized: "authorized"
        case .provisional: "provisional"
        case .ephemeral: "ephemeral"
        @unknown default: "unknown"
        }
    }
}
