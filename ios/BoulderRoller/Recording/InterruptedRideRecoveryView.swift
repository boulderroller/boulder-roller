import SwiftUI

enum InterruptedRideRecoveryAction: Equatable, Sendable {
    case save
    case discard
}

/// Production-used recovery action policy. The fail-first extraction keeps
/// the current behavior intact so the destructive-intent regression can be
/// demonstrated before the bounded correction.
struct InterruptedRideRecoveryActionPolicy: Equatable, Sendable {
    let discardIntentPending: Bool
    let retryAction: InterruptedRideRecoveryAction?

    var allowsSave: Bool {
        !discardIntentPending && retryAction != .discard
    }
}

/// Real owner-recovery surface. Copy is the exact retained mobile precedent;
/// the DEBUG render fixture injects data into this same production view.
struct InterruptedRideRecoveryView: View {
    @Environment(\.units) private var units
    let recovery: InterruptedRideRecovery
    var discardIntentPending = false
    let onSave: () async throws -> Void
    let onDiscard: () async throws -> Void

    @State private var isWorking = false
    @State private var confirmsDiscard = false
    @State private var retryAction: InterruptedRideRecoveryAction?
    @State private var errorMessage: String?

    private var actionPolicy: InterruptedRideRecoveryActionPolicy {
        InterruptedRideRecoveryActionPolicy(
            discardIntentPending: discardIntentPending,
            retryAction: retryAction
        )
    }

    var body: some View {
        ZStack {
            Theme.screen.ignoresSafeArea()
            VStack(spacing: 28) {
                Spacer()
                Text("Unfinished Ride Found")
                    .font(.title2.weight(.semibold))
                    .foregroundStyle(.white)

                HStack(spacing: 30) {
                    metric("Duration", Format.clockDuration(max(0, recovery.durationS)))
                    metric("Distance", Format.distance(fromMeters: recovery.distanceM, units: units), unit: units.distanceUnit)
                    metric(
                        "Elevation",
                        recovery.elevationGainM.map({ Format.elevation(fromMeters: $0, units: units) }) ?? "—",
                        unit: recovery.elevationGainM == nil ? nil : units.elevationUnit
                    )
                }
                .accessibilityElement(children: .contain)

                Spacer()

                if isWorking {
                    ProgressView().tint(Theme.gray)
                } else {
                    VStack(spacing: 12) {
                        // Below the upload floor the blue capsule would
                        // promise an upload eligibility will refuse — the
                        // save action stays, its primary dress doesn't.
                        if actionPolicy.allowsSave, recovery.canSaveAndUpload {
                            Button("Save & Upload") {
                                Task { await perform(.save) }
                            }
                            .buttonStyle(RecoveryPrimaryButtonStyle())
                        } else if actionPolicy.allowsSave {
                            Button("Save Ride") {
                                Task { await perform(.save) }
                            }
                            .font(.subheadline.weight(.semibold))
                            .foregroundStyle(Theme.gray)
                            .frame(maxWidth: .infinity, minHeight: 44)
                        }

                        Button("Discard", role: .destructive) {
                            confirmsDiscard = true
                        }
                        .font(.subheadline.weight(.semibold))
                        .frame(maxWidth: .infinity, minHeight: 44)
                    }
                }
            }
            .padding(.horizontal, Theme.margin)
            .padding(.bottom, 30)
        }
        .confirmationDialog("Discard Ride?", isPresented: $confirmsDiscard) {
            Button("Discard", role: .destructive) {
                Task { await perform(.discard) }
            }
            Button("Cancel", role: .cancel) {}
        } message: {
            Text("This will permanently delete your ride data.")
        }
        .alert(
            "Ride evidence is unavailable",
            isPresented: Binding(
                get: { errorMessage != nil },
                set: { if !$0 { errorMessage = nil } }
            )
        ) {
            Button("Retry") {
                guard let retryAction else { return }
                Task { await perform(retryAction) }
            }
            Button("Cancel", role: .cancel) {}
        }
        .interactiveDismissDisabled()
    }

    @MainActor
    private func perform(_ action: InterruptedRideRecoveryAction) async {
        isWorking = true
        errorMessage = nil
        do {
            switch action {
            case .save:
                try await onSave()
            case .discard:
                try await onDiscard()
            }
            retryAction = nil
        } catch {
            retryAction = action
            errorMessage = LiveRideCustodyError.corruptEvidence.localizedDescription
        }
        isWorking = false
    }

    /// Every numeral carries its unit (metrics are sacred) — the bare figure
    /// never stands alone.
    private func metric(_ label: String, _ value: String, unit: String? = nil) -> some View {
        VStack(spacing: 5) {
            Text(label.uppercased())
                .font(.caption2)
                .kerning(0.8)
                .foregroundStyle(Theme.gray)
            StatValueText(value: value, unit: unit, valueFont: .numeral(.body, weight: .semibold))
        }
        .frame(maxWidth: .infinity)
        .accessibilityElement(children: .combine)
        .accessibilityLabel("\(label) \(value) \(unit ?? "")")
    }
}

private struct RecoveryPrimaryButtonStyle: ButtonStyle {
    func makeBody(configuration: Configuration) -> some View {
        configuration.label
            .font(.subheadline.weight(.semibold))
            .foregroundStyle(.white)
            .frame(maxWidth: .infinity, minHeight: 52)
            .background(
                Capsule().fill(Theme.blue.opacity(configuration.isPressed ? 0.75 : 1))
            )
    }
}
