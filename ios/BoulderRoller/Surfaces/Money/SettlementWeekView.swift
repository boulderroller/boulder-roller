import SwiftUI

/// Pure settlement arithmetic, testable: exact decimal strings in, exact
/// display out — never binary float (L2.10).
enum SettlementFacts {
    /// The rider's own week total: the exact sum of their receipt rows.
    /// Any unreadable row keeps the whole total unavailable — a partial
    /// sum would be a lie.
    static func riderShare(_ receipts: [DistributionReceiptRow]?) -> String? {
        guard let receipts, !receipts.isEmpty else { return nil }
        var total = Decimal.zero
        for receipt in receipts {
            guard let raw = receipt.amount,
                  let value = Decimal(string: raw, locale: Locale(identifier: "en_US_POSIX"))
            else { return nil }
            total += value
        }
        return Format.exactAmount("\(total)")
    }
}

/// One Settlement Week's detail (L2.10): the canonical itemized amounts,
/// the rider's own allocation rows, and the vault's current carry — every
/// fact rendered only when authoritative data supplies it, exact decimal
/// strings all the way to the glyphs. Labels are the retained portal
/// vocabulary; no new payout category or receipt language exists here.
struct SettlementWeekView: View {
    let group: DistributionGroup
    /// The room's existing Collect action, shown here only when the room
    /// itself would show it — never a second implementation.
    let collectRow: (available: Bool, action: () -> Void)

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 0) {
                GroupCard {
                    row("Total", group.totalAmount)
                    RowSeparator()
                    row("Leaderboard pool", group.leaderboardAmount)
                    RowSeparator()
                    row("Backers", group.stakerAmount)
                    RowSeparator()
                    row("Local Legend", group.localLegendAmount)
                    RowSeparator()
                    row("POL", group.polAmount)
                    RowSeparator()
                    row("Treasury", group.protocolAmount)
                }

                statusFooter

                if let receipts = group.receipts, !receipts.isEmpty {
                    // The rider's own rows — dates and amounts, the room's
                    // grammar (+DUNG for what reached this rider).
                    GroupCard {
                        ForEach(Array(receipts.enumerated()), id: \.element.id) { index, receipt in
                            if index > 0 { RowSeparator() }
                            GrammarRow(
                                label: Format.rideTimestamp(receipt.createdAt),
                                value: Format.exactAmount(receipt.amount)
                                    .map { "+\($0) DUNG" } ?? "—",
                                valueIsNumeral: receipt.amount != nil,
                                subtitle: receipt.rank.map { "Rank #\($0)" }
                            )
                        }
                    }
                    .padding(.top, 24)
                }

                if let carry = group.currentCarry, hasAnyCarry(carry) {
                    SectionHeader(title: "Carry")
                        .padding(.top, 24)
                    GroupCard {
                        row("Leaderboard pool", carry.recordRoyalty)
                        RowSeparator()
                        row("Backers", carry.stakers)
                        RowSeparator()
                        row("Local Legend", carry.localLegend)
                        RowSeparator()
                        row("POL", carry.pol)
                        RowSeparator()
                        row("Treasury", carry.treasury)
                    }
                }

                if collectRow.available {
                    GroupCard {
                        CenteredActionRow(label: "Collect", action: collectRow.action)
                    }
                    .padding(.top, 24)
                }
            }
            .padding(.horizontal, Theme.margin)
            .padding(.top, 18)
            .padding(.bottom, 32)
        }
        .background(Theme.sheet.ignoresSafeArea())
        .navigationTitle(Format.weekOf(group.distributedAt))
        .navigationBarTitleDisplayMode(.inline)
    }

    /// Finalization is chain truth: a timestamp means immutable, absence
    /// means the event hasn't been observed — shown as the app's existing
    /// Pending word, never invented as final.
    @ViewBuilder
    private var statusFooter: some View {
        if let finalized = group.finalizedAt, !finalized.isEmpty {
            GroupFooter(text: "Finalized \(Format.rideTimestamp(finalized))")
        } else {
            GroupFooter(text: "Pending")
        }
    }

    private func row(_ label: String, _ unitsString: String?) -> some View {
        GrammarRow(
            label: label,
            value: Format.exactAmount(unitsString).map { "\($0) DUNG" } ?? "—",
            valueIsNumeral: Format.exactAmount(unitsString) != nil
        )
    }

    private func hasAnyCarry(_ carry: CarryBucketsResponse) -> Bool {
        [carry.recordRoyalty, carry.stakers, carry.localLegend, carry.pol, carry.treasury]
            .contains { value in
                guard let value, let decimal = Decimal(string: value) else { return false }
                return decimal > 0
            }
    }
}
