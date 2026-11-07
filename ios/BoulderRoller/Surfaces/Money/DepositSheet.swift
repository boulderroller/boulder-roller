import SwiftUI
import UIKit

/// Surface 10 — Deposit: Uniswap's giant numeral, Apple Pay's
/// amount-in-button, and no gas/approve/slippage anywhere — Balance eats it;
/// the absence is the feature. The app's only blue filled button, held.
struct DepositSheet: View {
    let climbName: String
    let vaultId: Int
    let depositedCal: String?
    let positionCal: Double?
    let priorCalBaseUnits: String
    var onCompleted: () -> Void = {}

    @Environment(\.dismiss) private var dismiss
    @Environment(AppSession.self) private var session

    @State private var amountText = ""
    @State private var balance: Double?
    @State private var money = MoneyModel()
    @FocusState private var amountFocused: Bool

    private static let minimumStake = 100

    private var amount: Int { Int(amountText) ?? 0 }
    private var amountValid: Bool {
        amount >= Self.minimumStake && Double(amount) <= (balance ?? 0)
    }

    var body: some View {
        ZStack {
            Theme.sheet.ignoresSafeArea()
            ScrollView {
                VStack(alignment: .leading, spacing: 0) {
                    SheetHeader(title: "Deposit", doneLabel: "Cancel") { dismiss() }
                        .padding(.top, 6)

                    VStack(alignment: .leading, spacing: 0) {
                        amountCard
                        connector
                        destinationCard

                        GroupFooter(
                            text: "Counts from the next settlement week — Sunday 12:00 UTC."
                        )

                        // The on-chain minimum, stated where it gates —
                        // never a silently dead capsule.
                        if (amount > 0 && amount < Self.minimumStake)
                            || (balance ?? 0) < Double(Self.minimumStake)
                        {
                            GroupFooter(text: "Minimum deposit is 100 CAL.")
                        }

                        if case let .failed(message) = money.status {
                            GroupFooter(text: message)
                        }
                        if let reconciliationLabel {
                            GroupFooter(text: reconciliationLabel)
                        }

                        if session.balanceActions.deposit {
                            HoldCapsule(
                                label: capsuleLabel,
                                tint: Theme.blue,
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
        .task { await load() }
        .onChange(of: money.status) {
            if case .done = money.status {
                onCompleted()
                dismiss()
                // A confirmed deposit is the first ratified ask moment:
                // settlements just became possible for this rider. The
                // policy makes this a no-op once determined either way.
                PushRegistrar.maybeAsk(.firstDepositConfirmed)
            }
        }
    }

    private var capsuleLabel: String {
        switch money.status {
        case .working: return "Depositing…"
        case .pending: return "Pending"
        case .delayed: return "Delayed"
        case .needsReview: return "Needs review"
        case .idle, .done, .failed: break
        }
        return amount > 0 ? "Hold to Deposit \(Format.amount(Double(amount))) CAL" : "Hold to Deposit"
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
                        // Haptic detent crossing round hundreds.
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
                Text("Balance \(balance.map { Format.amount($0) } ?? "—")")
                    .font(.numeral(.caption, weight: .regular))
                    .monospacedDigit()
                    .foregroundStyle(Theme.gray)
                Spacer()
                Button {
                    guard let balance else { return }
                    amountText = String(Int(balance))
                    // Max tick-and-settle: the detent ticks, this settles.
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
                    if let deposited = FiniteMoneyAmount(depositedCal).value {
                        Text("Vault · \(Format.amount(deposited)) CAL deposited")
                            .font(.caption2)
                            .foregroundStyle(Theme.gray)
                    }
                }
                Spacer()
            }
            .padding(.horizontal, 14)
            .frame(minHeight: Theme.row)
            RowSeparator(inset: 52)
            HStack {
                Text("Your position")
                    .font(.footnote)
                    .foregroundStyle(Theme.gray)
                Spacer()
                Text(positionLabel)
                    .font(.numeral(.footnote))
                    .monospacedDigit()
                    .foregroundStyle(Theme.ink)
            }
            .padding(.horizontal, 14)
            .padding(.leading, 38)
            .frame(minHeight: 44)
        }
        .accessibilityElement(children: .combine)
    }

    private var positionLabel: String {
        guard let current = positionCal else { return "—" }
        if amount > 0 {
            return "\(Format.amount(current)) → \(Format.amount(current + Double(amount)))"
        }
        return Format.amount(current)
    }

    private func commit() {
        guard session.balanceActions.deposit,
              money.canSubmit,
              amountValid,
              let wallet = session.currentUser?.wallet
        else { return }
        Task {
            await money.deposit(
                vaultId: vaultId,
                amount: amount,
                priorCalBaseUnits: priorCalBaseUnits,
                wallet: wallet
            )
        }
    }

    private func load() async {
        // The rider can type at once; nothing about the keyboard waits on
        // the network. Balance paints from the session cache the avatar
        // sheet already warmed, then the fresh read replaces it.
        amountFocused = true
        if let cached = try? await APIClient.shared.calBalance(policy: .cacheOnly) {
            balance = cached.calBalance.flatMap(Double.init)
        }
        async let actions: Void = session.refreshBalanceActions()
        async let fresh: CalOnchainResponse? = try? await APIClient.shared.calBalance()
        let (_, response) = await (actions, fresh)
        if let response { balance = response.calBalance.flatMap(Double.init) }
    }
}
