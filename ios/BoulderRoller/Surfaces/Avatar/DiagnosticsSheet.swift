import SwiftUI

/// Rider-shareable diagnostics (L3.10): the exact scrubbed bundle is
/// previewed before anything leaves the device, and Share hands off the
/// same text the preview shows. Builds offline; support destination is
/// whoever the rider shares it with.
struct DiagnosticsSheet: View {
    @Environment(\.dismiss) private var dismiss
    @Environment(AppSession.self) private var session

    @State private var bundle: DiagnosticsBundle?

    var body: some View {
        ZStack {
            Theme.sheet.ignoresSafeArea()
            VStack(alignment: .leading, spacing: 0) {
                SheetHeader(title: "Diagnostics") { dismiss() }
                    .padding(.top, 6)

                if let bundle {
                    GroupCard {
                        GrammarRow(
                            label: "Redacted",
                            value: redactionSummary(bundle),
                            valueIsNumeral: true
                        )
                        RowSeparator(inset: 0)
                        ShareLink(item: bundle.asJSON) {
                            Text("Share")
                                .font(.body.weight(.medium))
                                .foregroundStyle(Theme.blue)
                                .frame(maxWidth: .infinity, minHeight: Theme.row)
                        }
                    }
                    .padding(.horizontal, Theme.margin)
                    .padding(.top, 18)

                    // The exact bytes that Share sends — no hidden extras.
                    ScrollView {
                        Text(bundle.asJSON)
                            .font(.caption2.monospaced())
                            .foregroundStyle(Theme.gray)
                            .textSelection(.enabled)
                            .frame(maxWidth: .infinity, alignment: .leading)
                            .padding(14)
                    }
                    .background(Theme.card)
                    .clipShape(
                        RoundedRectangle(cornerRadius: Theme.cardRadius, style: .continuous)
                    )
                    .padding(.horizontal, Theme.margin)
                    .padding(.top, 14)
                    .padding(.bottom, 24)
                } else {
                    ProgressView()
                        .tint(Theme.gray)
                        .frame(maxWidth: .infinity, maxHeight: .infinity)
                        .accessibilityLabel("Preparing diagnostics")
                }
            }
        }
        .task {
            bundle = await DiagnosticsCollector.collect(session: session)
        }
    }

    private func redactionSummary(_ bundle: DiagnosticsBundle) -> String {
        let total = bundle.redactions.values.reduce(0, +)
        return "\(total)"
    }
}
