import SwiftUI
import UIKit

/// The app's only filled button species: transaction commit. States the
/// amount, and is held — ~600ms fill, one deep haptic at completion
/// (constitution §4). Blue for deposit, gray for withdraw — blue in, gray
/// out. VoiceOver activates it directly (a timed hold is not an
/// accessibility gate).
struct HoldCapsule: View {
    let label: String
    var tint: Color = Theme.blue
    var enabled: Bool = true
    let action: () -> Void

    @Environment(\.accessibilityReduceMotion) private var reduceMotion
    @State private var holding = false
    @State private var fill: CGFloat = 0
    @State private var fillTask: Task<Void, Never>?

    private static let holdDuration: TimeInterval = 0.6

    var body: some View {
        ZStack {
            Capsule().fill(tint.opacity(enabled ? 1 : 0.35))

            // The hold fill — a luminance sweep, not a second color.
            GeometryReader { proxy in
                Capsule()
                    .fill(.white.opacity(0.28))
                    .frame(width: proxy.size.width * fill)
                    .animation(reduceMotion ? nil : .linear(duration: 0.05), value: fill)
            }
            .clipShape(Capsule())

            Text(label)
                .font(.body.weight(.semibold))
                .foregroundStyle(Theme.ink)
                .padding(.horizontal, 16)
                .lineLimit(1)
                .minimumScaleFactor(0.8)
        }
        .frame(height: 50)
        .contentShape(Capsule())
        .onLongPressGesture(
            minimumDuration: Self.holdDuration,
            perform: { commit() },
            onPressingChanged: { pressing in
                guard enabled else { return }
                holding = pressing
                if pressing {
                    startFill()
                } else {
                    cancelFill()
                }
            }
        )
        .disabled(!enabled)
        .accessibilityElement()
        .accessibilityLabel(label)
        .accessibilityAddTraits(.isButton)
        .accessibilityAction { if enabled { commit() } }
    }

    private func startFill() {
        fillTask?.cancel()
        fillTask = Task { @MainActor in
            let steps = 24
            for step in 1...steps {
                try? await Task.sleep(for: .seconds(Self.holdDuration / Double(steps)))
                guard !Task.isCancelled else { return }
                fill = CGFloat(step) / CGFloat(steps)
            }
        }
    }

    private func cancelFill() {
        fillTask?.cancel()
        fillTask = nil
        fill = 0
    }

    private func commit() {
        cancelFill()
        fill = 1
        UIImpactFeedbackGenerator(style: .heavy).impactOccurred()
        action()
    }
}
