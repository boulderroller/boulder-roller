import CoreLocation
import SwiftUI
import UIKit

enum RecordingViewRetryAction: Equatable {
    case model
    case end
    case custodyExit
}

struct RecordingViewRetryPolicy {
    struct EndAttempt: Equatable {
        fileprivate let id = UUID()
        let controlIntent: RecordingControlIntent?
    }

    private(set) var action: RecordingViewRetryAction = .model
    private var activeEndAttempt: EndAttempt?
    private var retryableEndAttempt: EndAttempt?
    private var custodyExitOwnsRetry = false
    private var custodyExitIntent: RecordingSuspendIntent?

    mutating func beginEnd(
        reserveControlIntent: () -> RecordingControlIntent?
    ) -> EndAttempt? {
        guard !custodyExitOwnsRetry,
              activeEndAttempt == nil,
              retryableEndAttempt == nil,
              let intent = reserveControlIntent()
        else { return nil }
        let attempt = EndAttempt(controlIntent: intent)
        activeEndAttempt = attempt
        return attempt
    }

    mutating func beginEnd() -> EndAttempt? {
        guard !custodyExitOwnsRetry,
              activeEndAttempt == nil,
              retryableEndAttempt == nil
        else { return nil }
        let attempt = EndAttempt(controlIntent: nil)
        activeEndAttempt = attempt
        return attempt
    }

    mutating func beginEndRetry() -> EndAttempt? {
        guard !custodyExitOwnsRetry,
              action == .end,
              activeEndAttempt == nil,
              let retryableEndAttempt
        else { return nil }
        self.retryableEndAttempt = nil
        activeEndAttempt = retryableEndAttempt
        return retryableEndAttempt
    }

    mutating func endSucceeded(_ attempt: EndAttempt) -> Bool {
        guard !custodyExitOwnsRetry,
              activeEndAttempt == attempt
        else { return false }
        activeEndAttempt = nil
        retryableEndAttempt = nil
        action = .model
        return true
    }

    mutating func endFailed(_ attempt: EndAttempt) -> Bool {
        guard !custodyExitOwnsRetry,
              activeEndAttempt == attempt
        else { return false }
        activeEndAttempt = nil
        retryableEndAttempt = attempt
        action = .end
        return true
    }

    mutating func endDidNotStart(_ attempt: EndAttempt) -> Bool {
        endFailed(attempt)
    }

    mutating func beginCustodyExit(
        reserveSuspendIntent: () -> RecordingSuspendIntent?
    ) -> RecordingSuspendIntent? {
        if custodyExitOwnsRetry { return custodyExitIntent }
        let intent = reserveSuspendIntent()
        custodyExitOwnsRetry = true
        activeEndAttempt = nil
        retryableEndAttempt = nil
        action = .custodyExit
        custodyExitIntent = intent
        return intent
    }

    mutating func beginCustodyExit() {
        _ = beginCustodyExit(reserveSuspendIntent: { nil })
    }

    mutating func custodyExitFailed() {
        action = .custodyExit
    }

    mutating func custodyExitSucceeded() {
        action = .model
        custodyExitOwnsRetry = false
        activeEndAttempt = nil
        retryableEndAttempt = nil
        custodyExitIntent = nil
    }

    func routeRetry(
        model: () -> Void,
        end: () -> Void,
        custodyExit: () -> Void
    ) {
        switch action {
        case .model:
            model()
        case .end:
            end()
        case .custodyExit:
            custodyExit()
        }
    }
}

/// Surface 13 — Recording: Apple Workout's bones. Black, giant rounded
/// numerals, tracked labels, pause circle. Ours: the sensor provenance row
/// (paired devices, live dot) and the climb band — canon recognizes the hill,
/// shows live grade, progress, and delta vs PR in blue. Power is the hero
/// numeral when a power meter is live (edge rule from platform). The climb
/// band holds the app's only marquee (Law 8).
struct RecordingView: View {
    @Environment(\.dismiss) private var dismiss
    @Environment(\.accessibilityReduceMotion) private var reduceMotion
    @Environment(\.dynamicTypeSize) private var dynamicTypeSize
    @Environment(AppSession.self) private var session
    @Environment(\.units) private var units

    @State private var model: RecordingModel
    @State private var band = ClimbBandModel()
    @State private var sensors = SensorManager.shared
    @State private var retryPolicy = RecordingViewRetryPolicy()
    @State private var custodyExitInFlight = false
    @State private var finalizedAwaitingExit: FinalizedRecording?
    /// A finalized zero-sample recording awaiting the rider's one-action
    /// acknowledgment (bead c6l2l item 5).
    @State private var finalizedEmptyRide: FinalizedRecording?

    init(user: User) {
        _model = State(initialValue: RecordingModel(user: user))
    }

    #if DEBUG
    /// Render-fixture seam: the fixture supplies a production RecordingModel
    /// wired to synthetic data; this view stays the production surface.
    init(user: User, debugModel: RecordingModel) {
        _model = State(initialValue: debugModel)
    }
    #endif

    var body: some View {
        ZStack {
            Color.black.ignoresSafeArea()

            if model.authorizationDenied {
                deniedView
            } else if !model.hasFix {
                waitingView
            } else {
                recordingBody
            }
        }
        .statusBarHidden()
        .onAppear {
            // Bluetooth choreography: at Record open the central comes up
            // only to reconnect already-paired sensors. A rider with no
            // paired devices never gets a Bluetooth prompt here — the
            // first-ever ask belongs to the Sensors room (f4acp.1.8).
            if PermissionChoreography.shouldActivateSensorsAtRecordOpen(
                pairedDeviceCount: sensors.myDevices.count
            ) {
                sensors.activate()
            }
            model.onFix = { [weak band] fix in band?.update(location: fix) }
            model.requestAndStart()
        }
        .onDisappear { model.leaveOwnerSurface() }
        .onChange(of: model.recoveryExitRequired) { _, required in
            guard required else { return }
            suspendAndLeave()
        }
        .interactiveDismissDisabled()
        .alert(
            "Ride evidence is unavailable",
            isPresented: Binding(
                get: { model.custodyErrorMessage != nil },
                // The unavailable state cannot be dismissed into a frozen,
                // normal-looking recorder. Only a successful retry clears it.
                set: { _ in }
            )
        ) {
            Button("Retry") {
                retryPolicy.routeRetry(
                    model: { model.retryCustodyOperation() },
                    end: { retryEndRide() },
                    custodyExit: { suspendAndLeave() }
                )
            }
            Button("Cancel", role: .cancel) {
                // A session that never started holds no evidence — leaving
                // must not require custody's blessing (fail-closed is for
                // protecting samples, never for trapping the rider).
                if model.state == .idle, model.sampleCount == 0 {
                    dismiss()
                } else {
                    suspendAndLeave()
                }
            }
        }
        // Ending with zero accepted samples: one quiet acknowledgment
        // instead of a silent return (bead c6l2l item 5).
        .alert(
            "No ride data was recorded.",
            isPresented: Binding(
                get: { finalizedEmptyRide != nil },
                set: { _ in }
            )
        ) {
            Button("Discard") { discardEmptyRide() }
        }
    }

    // MARK: States

    private var deniedView: some View {
        VStack(spacing: 18) {
            Spacer()
            Text("Location access is off")
                .font(.body)
                .foregroundStyle(.white)
            Text("Allow location access in Settings to record.")
                .font(.subheadline)
                .foregroundStyle(Theme.gray)
                .multilineTextAlignment(.center)
                .padding(.horizontal, 40)
            Button {
                if let url = URL(string: UIApplication.openSettingsURLString) {
                    UIApplication.shared.open(url)
                }
            } label: {
                Text("Settings")
                    .font(.subheadline.weight(.semibold))
                    .foregroundStyle(Theme.blue)
                    .frame(minHeight: 44)
            }
            .buttonStyle(.plain)
            Spacer()
            closePill
        }
    }

    private var waitingView: some View {
        VStack(spacing: 16) {
            Spacer()
            ProgressView()
                .tint(Theme.gray)
            Text("Waiting for GPS…")
                .font(.subheadline)
                .foregroundStyle(Theme.gray)
            Spacer()
            closePill
        }
    }

    private var closePill: some View {
        Button {
            if model.state == .idle, model.sampleCount == 0 {
                // Nothing started (denied, or still waiting for a fix):
                // there is no evidence to protect — just leave.
                dismiss()
            } else if model.authorizationDenied {
                suspendAndLeave()
            } else {
                endRide()
            }
        } label: {
            Text("Cancel")
                .font(.subheadline.weight(.semibold))
                .foregroundStyle(.white)
                .frame(maxWidth: .infinity, minHeight: 44)
                .background(Capsule().fill(Theme.card))
        }
        .buttonStyle(.plain)
        .padding(.horizontal, 70)
        .padding(.bottom, 24)
    }

    // MARK: Live recording

    private var recordingBody: some View {
        VStack(spacing: 0) {
            HStack {
                Text("OUTDOOR RIDE")
                    .font(.caption2)
                    .kerning(0.8)
                    .foregroundStyle(Theme.gray)
                Spacer()
                if model.state == .autoPaused {
                    Text("AUTO-PAUSED")
                        .font(.caption2)
                        .foregroundStyle(Theme.gray)
                } else if model.state == .manuallyPaused {
                    Text("PAUSED")
                        .font(.caption2)
                        .foregroundStyle(Theme.gray)
                }
                sensorProvenanceRow
            }
            .padding(.horizontal, Theme.margin)
            .padding(.top, 18)

            Spacer(minLength: 8)

            metricsStack

            Spacer(minLength: 8)

            if let active = band.active {
                ClimbBand(active: active, reduceMotion: reduceMotion)
                    .padding(.horizontal, Theme.margin)
                    .padding(.bottom, 14)
                    .transition(.move(edge: .bottom).combined(with: .opacity))
            }

            controls
                .padding(.bottom, 30)
        }
        .animation(reduceMotion ? nil : .spring(duration: 0.4), value: band.active == nil)
        .animation(nil, value: model.elapsedS)
    }

    /// Paired devices with a live dot — provenance, not decoration. Blue
    /// marks live/counting things (color ledger).
    @ViewBuilder
    private var sensorProvenanceRow: some View {
        let connected = sensors.myDevices.filter(\.isConnected)
        if !connected.isEmpty {
            HStack(spacing: 6) {
                Text(connected.map(\.name).joined(separator: " · "))
                    .font(.caption2)
                    .foregroundStyle(Theme.gray)
                    .lineLimit(1)
                Circle()
                    .fill(Theme.blue)
                    .frame(width: 5, height: 5)
            }
            .accessibilityElement(children: .combine)
            .accessibilityLabel("Sensors connected: \(connected.map(\.name).joined(separator: ", "))")
        }
    }

    /// Numeral tiers from the gallery frame, mapped to device points on the
    /// 4pt grid (hand-drawn 52/40/26 px at 320 px width → 64/48/32 pt).
    private enum MetricTier {
        case hero, secondary, small

        var pointSize: CGFloat {
            switch self {
            case .hero: return 64
            case .secondary: return 48
            case .small: return 32
            }
        }

        var kerning: CGFloat { self == .hero ? -1.5 : -0.5 }
    }

    /// The Apple Workout stack, left-aligned to the page margin (gallery
    /// spec): TIME above the POWER hero when a power source is live, TIME as
    /// the hero otherwise, then small metrics in leading grid rows.
    private var metricsStack: some View {
        let powerIsHero = model.power3sW != nil
        return VStack(alignment: .leading, spacing: 22) {
            if powerIsHero {
                metric(
                    "TIME",
                    value: Format.clockDuration(max(model.elapsedS, 1)),
                    unit: nil,
                    tier: .secondary
                )
                metric("POWER", value: "\(model.power3sW ?? 0)", unit: "W", tier: .hero)
            } else {
                metric(
                    "TIME",
                    value: Format.clockDuration(max(model.elapsedS, 1)),
                    unit: nil,
                    tier: .hero
                )
            }

            smallMetricsLayout(powerIsHero: powerIsHero)
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .padding(.horizontal, Theme.margin)
    }

    private func smallMetrics(powerIsHero: Bool) -> [(label: String, value: String, unit: String?)] {
        var metrics: [(String, String, String?)] = [
            ("DISTANCE", Format.distance(fromMeters: model.distanceM, units: units), units.distanceUnit),
            ("SPEED", Format.speed(fromMps: model.speedMps, units: units), units.speedUnit),
            // Truthful null stays a dash — quieter than a numeral.
            (
                "CLIMBING",
                model.elevationGainM.map({ Format.elevation(fromMeters: $0, units: units) }) ?? "—",
                model.elevationGainM == nil ? nil : units.elevationUnit
            ),
        ]
        if let hr = sensors.liveHeartRate {
            metrics.append(("HEART RATE", "\(hr)", "bpm"))
        }
        if let cadence = sensors.liveCadence {
            metrics.append(("CADENCE", "\(cadence)", "rpm"))
        }
        if powerIsHero {
            metrics.append((
                "10S POWER",
                model.power10sW.map(String.init) ?? "—",
                model.power10sW == nil ? nil : "W"
            ))
        }
        return metrics
    }

    /// Three leading columns at standard type; one metric per row at
    /// accessibility sizes so no numeral ever truncates.
    @ViewBuilder
    private func smallMetricsLayout(powerIsHero: Bool) -> some View {
        let metrics = smallMetrics(powerIsHero: powerIsHero)
        if dynamicTypeSize.isAccessibilitySize {
            VStack(alignment: .leading, spacing: 22) {
                ForEach(metrics, id: \.label) { entry in
                    metric(entry.label, value: entry.value, unit: entry.unit, tier: .small)
                }
            }
        } else {
            Grid(alignment: .topLeading, horizontalSpacing: 36, verticalSpacing: 22) {
                ForEach(
                    Array(stride(from: 0, to: metrics.count, by: 3)),
                    id: \.self
                ) { rowStart in
                    GridRow {
                        ForEach(
                            metrics[rowStart..<min(rowStart + 3, metrics.count)],
                            id: \.label
                        ) { entry in
                            metric(entry.label, value: entry.value, unit: entry.unit, tier: .small)
                        }
                    }
                }
            }
        }
    }

    private func metric(_ label: String, value: String, unit: String?, tier: MetricTier) -> some View {
        // The quiet dash (bead c6l2l): a truthful null renders smaller and
        // gray2 — a dash is an absence, never a value competing in white.
        let isDash = value == "—"
        return VStack(alignment: .leading, spacing: 2) {
            Text(label)
                .font(.caption2)
                .kerning(1.1)
                .foregroundStyle(Theme.gray)
            HStack(alignment: .firstTextBaseline, spacing: 4) {
                Text(value)
                    .font(.system(
                        size: isDash ? 20 : tier.pointSize,
                        weight: isDash ? .regular : .semibold,
                        design: .rounded
                    ))
                    .monospacedDigit()
                    .kerning(isDash ? 0 : tier.kerning)
                    .foregroundStyle(isDash ? Theme.gray2 : .white)
                if let unit {
                    Text(unit)
                        .font(.caption.weight(.medium))
                        .foregroundStyle(Theme.gray)
                }
            }
        }
        .accessibilityElement(children: .combine)
        .accessibilityLabel(
            isDash
                ? "\(label.capitalized) unavailable"
                : "\(label.capitalized) \(value) \(unit ?? "")"
        )
    }

    // MARK: Controls — Apple Workout's circles, icon-only (gallery spec);
    // paused shows End + Resume. Accessibility keeps the verb.

    @ViewBuilder
    private var controls: some View {
        switch model.controlMode {
        case .endAndResume:
            HStack(spacing: 44) {
                controlCircle("stop.fill", label: "End") { endRide() }
                controlCircle("arrow.clockwise", label: "Resume") { model.resume() }
            }
        case .endOnly:
            controlCircle("stop.fill", label: "End") { endRide() }
        case .pause:
            controlCircle("pause.fill", label: "Pause") {
                model.pause()
                UIImpactFeedbackGenerator(style: .medium).impactOccurred()
            }
        case .unavailable:
            EmptyView()
        }
    }

    private func controlCircle(_ systemName: String, label: String, action: @escaping () -> Void) -> some View {
        Button(action: action) {
            Image(systemName: systemName)
                .font(.title2.weight(.semibold))
                .foregroundStyle(.white)
                .frame(width: 72, height: 72)
                .background(Circle().fill(Theme.card))
                .overlay(Circle().stroke(.white.opacity(0.14), lineWidth: 0.5))
        }
        .buttonStyle(.plain)
        .disabled(model.controlTransitionInFlight != nil)
        .accessibilityLabel(label)
    }

    private func endRide() {
        band.reset()
        guard let attempt = retryPolicy.beginEnd(
            reserveControlIntent: { model.reserveEndIntent() }
        ) else { return }
        completeEndRide(attempt)
    }

    private func retryEndRide() {
        guard let attempt = retryPolicy.beginEndRetry() else { return }
        completeEndRide(attempt)
    }

    private func completeEndRide(_ attempt: RecordingViewRetryPolicy.EndAttempt) {
        Task { @MainActor in
            do {
                let finalized: FinalizedRecording
                if let existing = finalizedAwaitingExit {
                    finalized = existing
                } else {
                    let created: FinalizedRecording?
                    if let intent = attempt.controlIntent {
                        created = try await model.completeEnd(intent)
                    } else {
                        created = try await model.end()
                    }
                    guard let created else {
                        guard retryPolicy.endDidNotStart(attempt) else { return }
                        model.presentFinalizationError()
                        return
                    }
                    finalizedAwaitingExit = created
                    finalized = created
                }
                // Zero accepted samples: the truth boundary already
                // classified this End (projection sampleCount synced through
                // the End cutoff; eligibility withheld the upload). Ask for
                // the rider's one-action acknowledgment instead of silently
                // keeping an empty saved ride.
                if !finalized.uploadEligible, model.sampleCount == 0 {
                    guard retryPolicy.endSucceeded(attempt) else { return }
                    finalizedAwaitingExit = nil
                    finalizedEmptyRide = finalized
                    return
                }
                if !finalized.uploadEligible {
                    try await session.refreshLocalRideCustody()
                }
                guard retryPolicy.endSucceeded(attempt) else { return }
                finalizedAwaitingExit = nil
                await session.refreshRideUploads()
                dismiss()
            } catch {
                guard retryPolicy.endFailed(attempt) else { return }
                model.presentFinalizationError()
            }
        }
    }

    /// The acknowledged empty ride is discarded; if the discard cannot be
    /// proven durable the evidence stays in custody (a truthful saved-ride
    /// card) and the pending intent completes on a later activation.
    private func discardEmptyRide() {
        guard let finalized = finalizedEmptyRide else { return }
        finalizedEmptyRide = nil
        Task { @MainActor in
            do {
                try await session.discardEmptyRecording(finalized)
            } catch {
                try? await session.refreshLocalRideCustody()
            }
            session.lastImportCompletedAt = .now
            dismiss()
        }
    }

    private func suspendAndLeave() {
        guard !custodyExitInFlight else { return }
        let suspendIntent = retryPolicy.beginCustodyExit(
            reserveSuspendIntent: { model.reserveSuspendAndLeaveIntent() }
        )
        custodyExitInFlight = true
        Task { @MainActor in
            defer { custodyExitInFlight = false }
            do {
                try await session.suspendRecordingAndRefresh(
                    {
                        if let suspendIntent {
                            try await model.completeSuspendAndLeave(suspendIntent)
                        } else {
                            try await model.suspendAndLeave()
                        }
                    },
                    onSuccess: {
                        retryPolicy.custodyExitSucceeded()
                        dismiss()
                    }
                )
            } catch {
                retryPolicy.custodyExitFailed()
                // Retry reruns this complete suspend -> exact-owner refresh ->
                // dismissal transaction. A model-only suspend can never make
                // the unavailable recovery state disappear.
                model.presentFinalizationError()
            }
        }
    }
}

// MARK: - Climb band

/// Canon recognized the hill. Name (the app's only marquee), live grade,
/// the climb's own shape with the rider drawn onto it in blue, delta vs PR.
struct ClimbBand: View {
    let active: ClimbBandModel.ActiveClimb
    let reduceMotion: Bool

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            HStack(alignment: .firstTextBaseline, spacing: 10) {
                MarqueeText(text: active.name, reduceMotion: reduceMotion)
                Spacer(minLength: 8)
                if let grade = active.gradePct {
                    Text(Format.grade(grade))
                        .font(.numeral(.body, weight: .semibold))
                        .monospacedDigit()
                        .foregroundStyle(.white)
                }
            }

            if active.profile.count >= 2 {
                CanonProfileView(profile: active.profile, compact: true, cursorM: active.progressM)
            } else {
                GeometryReader { proxy in
                    ZStack(alignment: .leading) {
                        Capsule()
                            .fill(Color.white.opacity(0.14))
                        Capsule()
                            .fill(Theme.blue)
                            .frame(width: max(proxy.size.width * active.progress, 6))
                    }
                }
                .frame(height: 4)
            }

            HStack {
                Text(Format.clockDuration(max(active.elapsedS, 1)))
                    .font(.numeral(.footnote, weight: .regular))
                    .monospacedDigit()
                    .foregroundStyle(Theme.gray)
                Spacer()
                if let delta = active.deltaVsPRSeconds {
                    Text(deltaLabel(delta))
                        .font(.numeral(.footnote, weight: .medium))
                        .monospacedDigit()
                        .foregroundStyle(delta <= 0 ? Theme.blue : Theme.gray)
                }
            }
        }
        .padding(14)
        // Warm card (Tim-ratified 2026-09-01): the terrain bands were built on
        // the warm ladder; blue lives only on the live marker and the delta.
        .background(
            RoundedRectangle(cornerRadius: Theme.cardRadius, style: .continuous)
                .fill(Theme.card)
        )
        .overlay(
            RoundedRectangle(cornerRadius: Theme.cardRadius, style: .continuous)
                .stroke(Theme.gray3.opacity(0.7), lineWidth: 0.5)
        )
        .accessibilityElement(children: .combine)
        .accessibilityLabel(accessibilitySummary)
    }

    private func deltaLabel(_ delta: Double) -> String {
        let magnitude = Int(abs(delta).rounded())
        let clock = String(format: "%d:%02d", magnitude / 60, magnitude % 60)
        return "\(delta <= 0 ? "−" : "+")\(clock) vs PR"
    }

    private var accessibilitySummary: String {
        var parts = [active.name]
        if let grade = active.gradePct { parts.append("\(Format.gradeValue(grade)) percent grade") }
        parts.append("\(Int((active.progress * 100).rounded())) percent up")
        if let delta = active.deltaVsPRSeconds {
            parts.append(deltaLabel(delta))
        }
        return parts.joined(separator: ", ")
    }
}

/// The app's only marquee (Law 8: recording climb band, Music-app precedent).
/// Scrolls only when the name exceeds the space; Reduce Motion truncates.
private struct MarqueeText: View {
    let text: String
    let reduceMotion: Bool

    @State private var textWidth: CGFloat = 0
    @State private var containerWidth: CGFloat = 0
    @State private var offset: CGFloat = 0

    private var needsScroll: Bool { textWidth > containerWidth + 1 }
    private static let gap: CGFloat = 44

    var body: some View {
        GeometryReader { container in
            let label = Text(text)
                .font(.body.weight(.semibold))
                .foregroundStyle(.white)
                .lineLimit(1)
                .fixedSize()

            HStack(spacing: Self.gap) {
                label
                    .background(
                        GeometryReader { proxy in
                            Color.clear.onAppear { textWidth = proxy.size.width }
                        }
                    )
                if needsScroll, !reduceMotion {
                    label
                }
            }
            .offset(x: offset)
            .frame(maxHeight: .infinity, alignment: .leading)
            .onAppear {
                containerWidth = container.size.width
                startIfNeeded()
            }
            .onChange(of: textWidth) { startIfNeeded() }
        }
        .frame(height: 22)
        .clipped()
        .accessibilityLabel(text)
    }

    private func startIfNeeded() {
        guard needsScroll, !reduceMotion else {
            offset = 0
            return
        }
        let distance = textWidth + Self.gap
        offset = 0
        withAnimation(
            .linear(duration: Double(distance) / 30.0)
            .delay(1.6)
            .repeatForever(autoreverses: false)
        ) {
            offset = -distance
        }
    }
}
