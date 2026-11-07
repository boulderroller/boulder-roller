import SwiftUI

/// What the Threshold room renders — the authority's display contract, not
/// the derivation. Established carries the sealed value that pays; a pending
/// next-Monday value exists only while a raise is sealed to activate.
enum ThresholdDisplay: Equatable {
    case establishing
    case established(
        currentW: Int,
        establishedISO: String,
        lastRaisedISO: String?,
        pendingW: Int?,
        pendingEffectiveISO: String?
    )

    var pendingEffectiveAt: Date? {
        guard case let .established(_, _, _, _, pendingEffectiveISO) = self,
              let pendingEffectiveISO
        else { return nil }
        return ISO8601DateFormatter().date(from: pendingEffectiveISO)
    }

    func pendingWatts(at now: Date) -> Int? {
        guard case let .established(_, _, _, pendingW, _) = self,
              let effectiveAt = pendingEffectiveAt,
              effectiveAt > now
        else { return nil }
        return pendingW
    }
}

/// The Threshold room (bead boulderroller-v2-2982). Read-only facts in the
/// Sensor Detail shape: facts card, quiet
/// footer, no input. The rider's denominator is derived, never declared, so
/// this room states facts and offers nothing to edit. Rows that have no
/// truth to state simply do not appear (SettlementsView conditional-row
/// precedent).
struct ThresholdSheet: View {
    let display: ThresholdDisplay
    private let onPendingBoundary: @MainActor () -> Void

    @Environment(\.dismiss) private var dismiss
    @State private var now: Date

    init(
        display: ThresholdDisplay,
        now: Date = .now,
        onPendingBoundary: @escaping @MainActor () -> Void = {}
    ) {
        self.display = display
        self.onPendingBoundary = onPendingBoundary
        _now = State(initialValue: now)
    }

    var body: some View {
        ZStack {
            Theme.sheet.ignoresSafeArea()
            ScrollView {
                VStack(alignment: .leading, spacing: 0) {
                    SheetHeader(title: "Threshold") { dismiss() }
                        .padding(.top, 6)

                    VStack(alignment: .leading, spacing: 0) {
                        GroupCard {
                            switch display {
                            case .establishing:
                                GrammarRow(label: "Status", value: "Establishing")
                            case let .established(
                                currentW, establishedISO, lastRaisedISO, _, _
                            ):
                                GrammarRow(
                                    label: "Current",
                                    value: Format.threshold(currentW),
                                    valueIsNumeral: true,
                                    valueColor: Theme.ink
                                )
                                if let lastRaisedISO {
                                    RowSeparator()
                                    GrammarRow(
                                        label: "Last raised",
                                        value: Format.monthDay(lastRaisedISO)
                                    )
                                } else {
                                    RowSeparator()
                                    GrammarRow(
                                        label: "Established",
                                        value: Format.monthDay(establishedISO)
                                    )
                                }
                                if let pendingW = display.pendingWatts(at: now) {
                                    RowSeparator()
                                    GrammarRow(
                                        label: "Next Monday",
                                        value: "\(Format.threshold(pendingW)) · Pending",
                                        valueIsNumeral: true
                                    )
                                }
                            }
                        }
                        GroupFooter(text: "derived from your rides")
                    }
                    .padding(.horizontal, Theme.margin)
                    .padding(.top, 22)
                    .padding(.bottom, 32)
                }
            }
        }
        .task(id: display.pendingEffectiveAt) {
            guard let effectiveAt = display.pendingEffectiveAt else { return }
            let remaining = effectiveAt.timeIntervalSince(now)
            if remaining > 0 {
                do {
                    try await Task.sleep(
                        nanoseconds: UInt64(remaining * 1_000_000_000)
                    )
                } catch {
                    return
                }
            }
            guard !Task.isCancelled else { return }
            now = max(.now, effectiveAt)
            onPendingBoundary()
        }
    }
}
