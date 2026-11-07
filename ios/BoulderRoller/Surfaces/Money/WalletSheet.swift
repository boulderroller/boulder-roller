import SwiftUI
import UIKit

/// The boundary between Boulder Roller Balance and the external wallet
/// (L2.12): the exact protocol wallet address, a copy action, and the one
/// approved external destination. The stage-6 "Withdraw to wallet" action
/// renders here only when production `/status` enables it for the rider's
/// cohort — until then no control exists, dead or otherwise (rollout
/// authority stays with bead bu9k; nothing is simulated).
struct WalletSheet: View {
    @Environment(\.dismiss) private var dismiss
    @Environment(AppSession.self) private var session

    private var address: String? {
        let wallet = session.currentUser?.wallet ?? ""
        return wallet.isEmpty ? nil : wallet
    }

    var body: some View {
        ZStack {
            Theme.sheet.ignoresSafeArea()
            ScrollView {
                VStack(alignment: .leading, spacing: 0) {
                    SheetHeader(title: "Wallet") { dismiss() }
                        .padding(.top, 6)

                    VStack(alignment: .leading, spacing: 0) {
                        GroupCard {
                            // The exact address, never truncated here —
                            // this surface exists to inspect it.
                            // One line, scaled to fit: a mid-address wrap
                            // inserts a hyphen glyph that reads as part of
                            // the address (fresh-eyes 2026-08-21).
                            Text(address ?? "—")
                                .font(.numeral(.footnote, weight: .medium))
                                .monospaced()
                                .foregroundStyle(address == nil ? Theme.gray2 : Theme.ink)
                                .textSelection(.enabled)
                                .lineLimit(1)
                                .minimumScaleFactor(0.6)
                                .frame(maxWidth: .infinity, alignment: .leading)
                                .padding(.horizontal, 14)
                                .padding(.vertical, 14)
                                .accessibilityLabel("Wallet address")

                            if let address {
                                RowSeparator(inset: 0)
                                CenteredActionRow(label: "Copy Address") {
                                    UIPasteboard.general.string = address
                                }
                                if let url = AppConfig.solanaExplorerAddressURL(address) {
                                    RowSeparator(inset: 0)
                                    CenteredActionRow(label: "View on Solana Explorer") {
                                        UIApplication.shared.open(url)
                                    }
                                }
                            }
                        }
                        Stage1Section().id(Stage1Owner(session.currentUser)?.key)
                    }
                    .padding(.horizontal, Theme.margin)
                    .padding(.top, 22)
                    .padding(.bottom, 32)
                }
            }
        }
    }
}
