import SwiftUI

/// One power reading on every climb surface. Estimates stay muted; their
/// range is a secondary fact and is read aloud with the estimate.
struct ClimbPowerLabel: View {
    let power: FormattedClimbPower?

    var body: some View {
        if let power {
            VStack(alignment: .leading, spacing: 2) {
                ViewThatFits(in: .horizontal) {
                    HStack(spacing: 6) {
                        watts(power)
                        if let wkg = power.wattsPerKg { Text(wkg) }
                    }
                    VStack(alignment: .leading, spacing: 2) {
                        watts(power)
                        if let wkg = power.wattsPerKg { Text(wkg) }
                    }
                }
                .foregroundStyle(power.isEstimated ? Theme.gray : Theme.ink)
                if let range = power.range {
                    Text(range)
                        .foregroundStyle(Theme.gray)
                }
            }
            .font(.numeral(.caption2))
            .monospacedDigit()
            .fixedSize(horizontal: false, vertical: true)
            .accessibilityElement(children: .ignore)
            .accessibilityLabel(power.accessibilityLabel)
        }
    }

    private func watts(_ power: FormattedClimbPower) -> Text {
        if power.isEstimated {
            return Text(power.text)
        }
        // The native bolt inherits the ink color; an emoji would add gold
        // to a permanent sporting fact, outside the color ledger.
        return Text("\(Image(systemName: "bolt.fill")) \(power.watts)")
    }
}
