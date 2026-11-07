import SwiftUI

extension RideTrainingMetrics {
    /// Either explicit API flag can mark the existing load readout. Older
    /// payloads carry only loadEstimate; missing provenance stays missing.
    func loadDisclosure(value: Double, isPending: Bool = false) -> EstimatePresentation {
        let envelope = estimates?["load"] ?? nil
        return EstimatePresentation(
            value: value,
            estimate: loadEstimate == true || envelope?.estimate == true,
            basis: envelope?.basis,
            range: envelope?.range,
            valueSuffix: isPending ? " · Pending" : "",
            format: { Format.amount($0) }
        )
    }
}

/// Display only. Flags, provenance and bounds are supplied by the API;
/// the same existing surface formatter formats the value and both bounds.
struct EstimatePresentation {
    let isEstimate: Bool
    let formattedValue: String
    let formattedRange: String?
    let copyLines: [String]
    let valueSuffix: String

    init(
        value: Double,
        estimate: Bool,
        basis: String? = nil,
        range: [Double?]? = nil,
        valueSuffix: String = "",
        format: (Double) -> String
    ) {
        isEstimate = estimate
        formattedValue = format(value)
        self.valueSuffix = valueSuffix
        copyLines = EstimateCopy.lines(basis: basis)
        if let range, range.count == 2,
           let lowValue = range[0], let highValue = range[1],
           lowValue.isFinite, highValue.isFinite {
            var low = format(lowValue)
            let high = format(highValue)
            if let unitRange = high.range(of: #"\s+[^\d\s]+$"#, options: .regularExpression) {
                let unit = String(high[unitRange])
                if low.hasSuffix(unit) { low.removeLast(unit.count) }
            }
            formattedRange = "\(low)–\(high)"
        } else {
            formattedRange = nil
        }
    }

    var accessibilityLabel: String {
        let spoken = Self.spokenValue(formattedValue)
        return (isEstimate ? "Estimated \(spoken)" : spoken) + valueSuffix
    }

    var hasDetails: Bool {
        isEstimate && (formattedRange != nil || !copyLines.isEmpty)
    }

    static func spokenValue(_ formatted: String) -> String {
        formatted
            .replacingOccurrences(of: #"\bW$"#, with: "watts", options: .regularExpression)
            .replacingOccurrences(of: #"\bkcal$"#, with: "kilocalories", options: [.regularExpression, .caseInsensitive])
            .replacingOccurrences(of: #"\bbpm$"#, with: "beats per minute", options: [.regularExpression, .caseInsensitive])
    }
}

/// Variant B. The measured branch returns the caller's existing label intact.
struct EstimatedValue<Label: View>: View {
    let presentation: EstimatePresentation
    var markFont: Font = .numeral(.body)
    var markColor: Color = Theme.gray
    @ViewBuilder let label: () -> Label
    @State private var showingDetails = false

    var body: some View {
        if presentation.hasDetails {
            Button { showingDetails.toggle() } label: {
                markedLabel
                    .overlay(alignment: .bottom) {
                        GeometryReader { geometry in
                            Path { path in
                                path.move(to: .zero)
                                path.addLine(to: CGPoint(x: geometry.size.width, y: 0))
                            }
                            .stroke(Theme.separator, style: StrokeStyle(lineWidth: 1, lineCap: .round, dash: [1, 3]))
                        }
                        .frame(height: 1)
                        .offset(y: 4)
                        .accessibilityHidden(true)
                    }
                    .contentShape(Rectangle())
            }
            .buttonStyle(.plain)
            .accessibilityLabel(presentation.accessibilityLabel)
            .popover(isPresented: $showingDetails, attachmentAnchor: .rect(.bounds), arrowEdge: .bottom) {
                EstimateDetailsCard(presentation: presentation, copyLines: presentation.copyLines)
                    .presentationCompactAdaptation(.popover)
                    .presentationBackground(Theme.sheet)
                    .accessibilityAction(.escape) { showingDetails = false }
            }
        } else if presentation.isEstimate {
            markedLabel
                .accessibilityElement(children: .ignore)
                .accessibilityLabel(presentation.accessibilityLabel)
        } else {
            label()
        }
    }

    private var markedLabel: some View {
        HStack(alignment: .firstTextBaseline, spacing: 0) {
            Text("≈")
                .font(markFont)
                .foregroundStyle(markColor)
                .accessibilityHidden(true)
            label()
        }
    }

}

/// The fixture and the production popover use the same wrapped, scrollable card.
struct EstimateDetailsCard: View {
    let presentation: EstimatePresentation
    let copyLines: [String]

    var body: some View {
        ScrollView {
            EstimateCardContentLayout {
                VStack(alignment: .leading, spacing: 8) {
                    cardValue
                    cardRange
                    ForEach(Array(copyLines.enumerated()), id: \.offset) { index, line in
                        Text(line)
                            .font(.caption)
                            .foregroundStyle(index == 0 ? Theme.gray : Theme.gray2)
                            .fixedSize(horizontal: false, vertical: true)
                    }
                }
                .padding(16)
            }
        }
        .scrollBounceBehavior(.basedOnSize)
        .frame(maxHeight: 400)
        .fixedSize(horizontal: true, vertical: true)
    }

    private var cardValue: some View {
        HStack(alignment: .firstTextBaseline, spacing: 0) {
            Text("≈")
                .foregroundStyle(Theme.gray)
                .accessibilityHidden(true)
            Text(presentation.formattedValue + presentation.valueSuffix)
                .foregroundStyle(Theme.ink)
        }
        .font(.numeral(.body))
        .monospacedDigit()
        .accessibilityElement(children: .ignore)
        .accessibilityLabel(presentation.accessibilityLabel)
    }

    @ViewBuilder private var cardRange: some View {
        if let range = presentation.formattedRange {
            Text(range)
                .font(.numeral(.caption, weight: .regular))
                .monospacedDigit()
                .foregroundStyle(Theme.gray)
                .accessibilityLabel(EstimatePresentation.spokenValue(range))
        }
    }
}

/// Measure the stack again at its capped width before reporting its height.
/// The enclosing scroll view can then use that wrapped height, or scroll at 400pt.
private struct EstimateCardContentLayout: Layout {
    func sizeThatFits(proposal: ProposedViewSize, subviews: Subviews, cache: inout ()) -> CGSize {
        guard let content = subviews.first else { return .zero }
        let ideal = content.sizeThatFits(.unspecified)
        let width = min(300, ideal.width, proposal.width ?? .infinity)
        return content.sizeThatFits(ProposedViewSize(width: width, height: nil))
    }

    func placeSubviews(in bounds: CGRect, proposal: ProposedViewSize, subviews: Subviews, cache: inout ()) {
        subviews.first?.place(at: bounds.origin, anchor: .topLeading,
            proposal: ProposedViewSize(width: bounds.width, height: nil))
    }
}
