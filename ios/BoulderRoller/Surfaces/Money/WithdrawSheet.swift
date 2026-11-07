import SwiftUI
import UIKit

/// Surface 11 — Withdraw: the Deposit mirror, gray commit — blue in, gray
/// out. The truth pass lives in one calm line: pending DUNG is collected to
/// settlements before the unstake, so the forfeit rake can't be stepped on.
struct WithdrawSheet: View {
    let climbName: String
    let vaultId: Int
    let stake: VaultStake
    var onCompleted: () -> Void = {}

    @Environment(\.dismiss) private var dismiss
    @Environment(AppSession.self) private var session

    @State private var amountText = ""
    @State private var money = MoneyModel()
    @FocusState private var amountFocused: Bool

    private var exactPosition: (cal: Double, calBase: UInt128, lpBase: UInt128)? {
        guard let humanRaw = stake.calStaked,
              let cal = Double(humanRaw),
              cal.isFinite,
              cal > 0,
              let humanDecimal = Decimal(
                string: humanRaw,
                locale: Locale(identifier: "en_US_POSIX")
              ),
              let calRaw = stake.calStakedBaseUnits,
              let calBase = UInt128(calRaw),
              calBase > 0,
              let calDecimal = Decimal(
                string: calRaw,
                locale: Locale(identifier: "en_US_POSIX")
              ),
              humanDecimal * Decimal(1_000_000_000) == calDecimal,
              let lpRaw = stake.lpTokensBaseUnits,
              let lpBase = UInt128(lpRaw),
              lpBase > 0
        else { return nil }
        return (cal, calBase, lpBase)
    }

    private var positionCal: Double? { exactPosition?.cal }
    private var amount: Int { Int(amountText) ?? 0 }
    private var amountValid: Bool {
        guard let positionCal else { return false }
        return amount > 0 && Double(amount) <= positionCal
    }
    private var isFullWithdraw: Bool {
        guard let positionCal else { return false }
        return Double(amount) >= positionCal
    }

    var body: some View {
        ZStack {
            Theme.sheet.ignoresSafeArea()
            ScrollView {
                VStack(alignment: .leading, spacing: 0) {
                    SheetHeader(title: "Withdraw", doneLabel: "Cancel") { dismiss() }
                        .padding(.top, 6)

                    VStack(alignment: .leading, spacing: 0) {
                        amountCard
                        connector
                        destinationCard

                        GroupFooter(text: "Pending DUNG is collected to your settlements first.")

                        if case let .failed(message) = money.status {
                            GroupFooter(text: message)
                        }
                        if let reconciliationLabel {
                            GroupFooter(text: reconciliationLabel)
                        }

                        if session.balanceActions.withdraw {
                            HoldCapsule(
                                label: capsuleLabel,
                                tint: Theme.commitGray,
                                enabled: amountValid && money.canSubmit
                            ) {
                                commit()
                            }
                            .padding(.top, 20)
                        }
                    }
                    .padding(.horizontal, Theme.margin)
                    .padding(.top, 22)
                    .padding(.bottom, 32)
                }
            }
        }
        .interactiveDismissDisabled(money.isWorking)
        .onAppear { amountFocused = true }
        .task { await session.refreshBalanceActions() }
        .onChange(of: money.status) {
            if case .done = money.status {
                onCompleted()
                dismiss()
            }
        }
    }

    private var capsuleLabel: String {
        switch money.status {
        case .working: return "Withdrawing…"
        case .pending: return "Pending"
        case .delayed: return "Delayed"
        case .needsReview: return "Needs review"
        case .idle, .done, .failed: break
        }
        return amount > 0 ? "Hold to Withdraw \(Format.amount(Double(amount))) CAL" : "Hold to Withdraw"
    }

    private var reconciliationLabel: String? {
        switch money.status {
        case .pending: return "Pending"
        case .delayed: return "Delayed"
        case .needsReview: return "Needs review"
        case .idle, .working, .done, .failed: return nil
        }
    }

    private var amountCard: some View {
        VStack(alignment: .leading, spacing: 8) {
            HStack(alignment: .firstTextBaseline, spacing: 7) {
                TextField("0", text: $amountText)
                    .keyboardType(.numberPad)
                    .focused($amountFocused)
                    .font(.system(size: 40, weight: .semibold, design: .rounded))
                    .monospacedDigit()
                    .kerning(-0.5)
                    .foregroundStyle(Theme.ink)
                    .onChange(of: amountText) { old, new in
                        let cleaned = String(new.prefix(7)).filter(\.isNumber)
                        if cleaned != new { amountText = cleaned }
                        if (Int(old) ?? 0) / 100 != (Int(cleaned) ?? 0) / 100 {
                            UISelectionFeedbackGenerator().selectionChanged()
                        }
                    }
                    .accessibilityLabel("Amount in CAL")
                Text("CAL")
                    .font(.body)
                    .foregroundStyle(Theme.gray)
            }
            HStack {
                Text("Position \(positionCal.map { Format.amount($0) } ?? "—")")
                    .font(.numeral(.caption, weight: .regular))
                    .monospacedDigit()
                    .foregroundStyle(Theme.gray)
                Spacer()
                if let positionCal {
                    Button {
                        amountText = String(Int(positionCal))
                        Task {
                            try? await Task.sleep(for: .milliseconds(140))
                            UIImpactFeedbackGenerator(style: .light).impactOccurred()
                        }
                    } label: {
                        Text("Max")
                            .font(.caption.weight(.medium))
                            .foregroundStyle(Theme.blue)
                    }
                    .buttonStyle(.plain)
                }
            }
        }
        .padding(16)
        .background(Theme.card)
        .clipShape(RoundedRectangle(cornerRadius: Theme.cardRadius, style: .continuous))
        .onTapGesture { amountFocused = true }
    }

    private var connector: some View {
        HStack {
            Spacer()
            Image(systemName: "arrow.down")
                .font(.caption2.weight(.semibold))
                .foregroundStyle(Theme.gray)
                .frame(width: 26, height: 26)
                .background(Circle().fill(Theme.card))
                .overlay(Circle().stroke(Theme.sheet, lineWidth: 3))
            Spacer()
        }
        .padding(.vertical, -5)
        .zIndex(1)
        .accessibilityHidden(true)
    }

    private var destinationCard: some View {
        GroupCard {
            HStack(spacing: 12) {
                Image(systemName: "mountain.2")
                    .font(.caption)
                    .foregroundStyle(Theme.blue)
                    .frame(width: 26, height: 26)
                    .background(
                        RoundedRectangle(cornerRadius: 8, style: .continuous)
                            .fill(Theme.countedFill.opacity(0.6))
                    )
                    .accessibilityHidden(true)
                VStack(alignment: .leading, spacing: 1) {
                    Text(climbName)
                        .font(.body)
                        .foregroundStyle(Theme.ink)
                    Text(positionSubtitle)
                        .font(.caption2)
                        .foregroundStyle(Theme.gray)
                }
                Spacer()
            }
            .padding(.horizontal, 14)
            .frame(minHeight: Theme.row)
            RowSeparator(inset: 52)
            HStack {
                Text("Returns to")
                    .font(.footnote)
                    .foregroundStyle(Theme.gray)
                Spacer()
                Text("CAL balance")
                    .font(.footnote.weight(.medium))
                    .foregroundStyle(Theme.ink)
            }
            .padding(.horizontal, 14)
            .padding(.leading, 38)
            .frame(minHeight: 44)
            RowSeparator(inset: 52)
            // The 0.5% exit fee is live on-chain; the sheet says so
            // (constitution surface 11: the line ships when the fee does).
            HStack {
                Text("Exit fee")
                    .font(.footnote)
                    .foregroundStyle(Theme.gray)
                Spacer()
                Text("0.5%")
                    .font(.numeral(.footnote, weight: .medium))
                    .monospacedDigit()
                    .foregroundStyle(Theme.ink)
            }
            .padding(.horizontal, 14)
            .padding(.leading, 38)
            .frame(minHeight: 44)
        }
        .accessibilityElement(children: .combine)
    }

    private var positionSubtitle: String {
        guard let positionCal else { return "Vault · your position —" }
        if amount > 0 {
            let after = max(positionCal - Double(amount), 0)
            return "Vault · your position \(Format.amount(positionCal)) → \(Format.amount(after))"
        }
        return "Vault · your position \(Format.amount(positionCal))"
    }

    private func commit() {
        guard session.balanceActions.withdraw,
              money.canSubmit,
              amountValid,
              let exactPosition,
              let wallet = session.currentUser?.wallet
        else { return }
        let lpBaseUnits = isFullWithdraw ? nil : partialLpBaseUnits()
        if !isFullWithdraw, lpBaseUnits == nil {
            // Exact partial conversion unavailable — never guess with money.
            return
        }
        Task {
            await money.withdraw(
                vaultId: vaultId,
                lpAmountBaseUnits: lpBaseUnits,
                priorLpAmountBaseUnits: String(exactPosition.lpBase),
                wallet: wallet
            )
        }
    }

    /// LP base units proportional to the requested CAL amount, floored —
    /// exact integer math over the wire strings.
    private func partialLpBaseUnits() -> String? {
        guard let exactPosition else { return nil }
        let amountBase = UInt128(amount) * 1_000_000_000
        let lp = exactPosition.lpBase * amountBase / exactPosition.calBase
        guard lp > 0 else { return nil }
        return String(min(lp, exactPosition.lpBase))
    }
}
